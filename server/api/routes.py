# -*- coding: utf-8 -*-
"""API 路由。"""
import os
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from engine.types_config import TYPES, CURRENCY_OPTIONS, PORTS, get_type, template_path
from engine.builder import build_contract
from engine.checker import check_rules, check_fingerprint, extract_contract_text
from engine import writer as W
from llm import client as llm
from llm.prompts import extract_messages, parse_payment_messages, review_messages, build_summary
from api import store

router = APIRouter(prefix="/api")

TYPE_LABEL_FILE = {  # 下载文件名用
    "car": "车辆买卖合约", "transfer_gx": "高新两地牌过户", "transfer_ns": "纳税两地牌过户", "new_port": "粤Z新办协议",
}


@router.get("/types")
def get_types():
    out = []
    for key, cfg in TYPES.items():
        out.append({
            "key": key,
            "label": cfg["label"],
            "short": cfg["short"],
            "currency_default": cfg["currency_default"],
            "port_required": bool(cfg.get("port_required")),
            "ports": PORTS if cfg.get("port_required") else None,
            "groups": cfg["groups"],
            "fee_fields": cfg["fee_fields"],
            "default_pay_fields": cfg.get("default_pay_fields", []),
            "client_side": cfg["client_side"],
            "car_default": bool(cfg.get("car_default")),
        })
    return {"types": out, "currencies": CURRENCY_OPTIONS}


class ExtractReq(BaseModel):
    type: str
    text: str = Field(min_length=5)


@router.post("/extract")
def extract(req: ExtractReq):
    try:
        data = llm.chat_json(extract_messages(req.type, req.text.strip()))
    except llm.LLMError as ex:
        raise HTTPException(502, f"LLM 抽取失败：{ex}")
    fields = data.get("fields") or {}
    # 口岸纠正到合法值
    for k in ("port",):
        v = fields.get(k)
        if v and v not in PORTS:
            for p in PORTS:
                if v in p or p in v:
                    fields[k] = p
                    break
    return {
        "fields": fields,
        "currency": data.get("currency"),
        "total": data.get("total"),
        "payment_text": data.get("payment_text"),
        "notes": data.get("notes") or [],
    }


class ParsePayReq(BaseModel):
    type: str
    currency: str
    total: int
    text: str = Field(min_length=3)
    sign_date: Optional[str] = None  # 签署日期,用于推算相对日期为绝对日期


@router.post("/parse-payment")
def parse_payment(req: ParsePayReq):
    try:
        data = llm.chat_json(parse_payment_messages(
            req.type, req.currency, req.total, req.text.strip(), req.sign_date or ""
        ))
    except llm.LLMError as ex:
        raise HTTPException(502, f"LLM 解析失败：{ex}")
    mode = data.get("mode")
    if mode not in ("default", "one_time", "custom"):
        raise HTTPException(422, "无法识别付款方式，请换种说法或手动填写")
    result = {"mode": mode, "currency": data.get("currency"), "notes": data.get("notes") or []}
    if mode == "one_time":
        ot = data.get("one_time") or {}
        result["one_time"] = {
            "pay_date": ot.get("date"),
            "pay_event": ot.get("event") or "",
            "choice": ot.get("choice") if ot.get("choice") in ("较早者", "较晚者") else "较早者",
        }
    if mode == "custom":
        inst = []
        for x in (data.get("installments") or []):
            try:
                amt = int(str(x.get("amount", 0)).replace(",", ""))
            except ValueError:
                continue
            if amt <= 0:
                continue
            inst.append({
                "seq": len(inst) + 1,
                "amount": amt,
                "trigger": str(x.get("trigger") or "").strip(),
                "trigger_date": str(x.get("trigger_date") or "").strip() or None,
                "trigger_type": x.get("trigger_type") or "event",
            })
        if not inst:
            raise HTTPException(422, "未解析出任何分期，请手动填写")
        result["installments"] = inst
        result["sum"] = sum(x["amount"] for x in inst)
    return result


class Installment(BaseModel):
    seq: int
    amount: int
    trigger: str = ""
    trigger_type: str = "event"


class Payment(BaseModel):
    mode: str
    deposit_amount: Optional[int] = None
    deposit_date: Optional[str] = None
    balance_date: Optional[str] = None
    choice: Optional[str] = None
    pay1: Optional[int] = None
    pay2: Optional[int] = None
    pay3: Optional[int] = None
    pay_date: Optional[str] = None
    pay_event: Optional[str] = None
    installments: Optional[List[Installment]] = None
    source_text: Optional[str] = None


class GenerateReq(BaseModel):
    type: str
    form: dict
    payment: Payment


@router.post("/generate")
def generate(req: GenerateReq):
    cfg = get_type(req.type)
    form, payment = req.form, req.payment.model_dump()
    agreement_no = str(form.get("agreement_no") or "").strip()
    auto_no = not agreement_no
    no = store.next_no() if auto_no else agreement_no

    filename = f"{no}-{TYPE_LABEL_FILE.get(req.type, req.type)}.docx"
    out_path = os.path.join(store.OUT_DIR, filename)

    # 生成前校验（早期失败不占流水）
    try:
        report = build_contract(req.type, form, payment, no, out_path)
        report["agreement_no"] = no
    except ValueError as ex:
        raise HTTPException(422, str(ex))

    from docx import Document
    doc = Document(out_path)
    errors = check_rules(req.type, form, payment, report, doc)
    fp_issues = check_fingerprint(report["template"], out_path, req.type, report)
    errors.extend(fp_issues)

    # LLM 语义复核（软校验：失败不拦截，标注警告）
    warnings = []
    text = extract_contract_text(doc)
    try:
        rv = llm.chat_json(review_messages(text, build_summary(req.type, form, payment)), max_tokens=1200)
        if not rv.get("pass"):
            for iss in rv.get("issues") or []:
                warnings.append(f"LLM复核：{iss}")
    except llm.LLMError as ex:
        warnings.append(f"LLM复核未完成（{ex}），规则校验已通过")

    status = "ok" if not errors else "failed"
    client_name = form.get("client_name") or ""
    store.save_gen(no, req.type, client_name, payment.get("mode", ""), form.get("currency", ""), filename, status)

    return {
        "ok": not errors,
        "no": no,
        "filename": filename,
        "errors": errors,
        "warnings": warnings,
        "text": text,
        "download_url": f"/api/download/{no}" if not errors else None,
    }


@router.get("/download/{no}")
def download(no: str):
    rec = store.get_gen(no)
    if not rec:
        raise HTTPException(404, "记录不存在")
    path = os.path.join(store.OUT_DIR, rec["filename"])
    if not os.path.exists(path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=rec["filename"],
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/history")
def get_history():
    return {"items": store.history()}


@router.get("/health")
def health():
    return {"status": "ok", "model": llm.MODEL, "key_set": bool(llm.API_KEY)}
