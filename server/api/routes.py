# -*- coding: utf-8 -*-
"""API 路由。"""
import os
import re
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from engine.types_config import TYPES, CURRENCY_OPTIONS, PORTS, get_type, template_path
from engine.builder import build_contract, derive_payment
from engine.checker import check_rules, check_fingerprint, extract_contract_text
from engine import writer as W
from llm import client as llm
from llm.prompts import extract_messages, parse_payment_messages, review_messages, build_summary
from api import store

router = APIRouter(prefix="/api")

TYPE_LABEL_FILE = {  # 下载文件名用
    "car": "车辆买卖合约", "transfer_gx": "高新两地牌过户", "transfer_ns": "纳税两地牌过户", "new_port": "粤Z新办协议",
}

# LLM 复核确认项过滤：结论为「检查通过」的条目不作为警告展示（提示词已禁，此处兜底）
NO_ISSUE_RE = re.compile(r"未发现.{0,8}(问题|异常|重复|缺失)")
NEG_MARK_RE = re.compile(r"不一致|未|缺|存在|但|错误|异常|应|建议|需|问题")


def _is_confirmation(iss: str) -> bool:
    if NO_ISSUE_RE.search(iss):
        return True
    return bool(re.search(r"一致|正确|无误", iss)) and not NEG_MARK_RE.search(iss)


# 解析 notes 噪音过滤：系统已自动处理的过程说明不算问题，不进提示/弹窗。
# 噪音＝「与预设不符/不一致/不同」（自定义分期是设计内路径）＋「…一致」类正常确认（"不一致"除外）
# ＋质保参数不全类提醒（客户没给时长/公里数时系统自动按默认「半年或3万公里」写入，无需确认）。
NOTE_NOISE_RE = re.compile(
    r"与.{0,4}预设.{0,12}(不符|不一致|不同)|(?<!不)一致"
    r"|质保.{0,30}(未说明|未提供|未明确|未写明|未给出|没说明|没有说明)"
)


def _filter_notes(notes: list) -> list:
    return [n for n in (notes or []) if not NOTE_NOISE_RE.search(str(n))]


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
            "pay_preset": cfg.get("pay_preset", []),
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
        "notes": _filter_notes(data.get("notes")),
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
    matches = bool(data.get("matches_preset"))
    result = {"matches_preset": matches, "notes": _filter_notes(data.get("notes"))}

    inst, extra_notes = [], []
    for x in (data.get("installments") or []):
        try:
            amt = int(str(x.get("amount", 0)).replace(",", ""))
        except ValueError:
            continue
        if amt <= 0:
            continue
        td = str(x.get("trigger_date") or "").strip() or None
        if td and not W.is_valid_iso_date(td):
            extra_notes.append(f"第{len(inst) + 1}期推算日期「{td}」不是有效日期，已忽略，请核对付款条件")
            td = None
        if td and req.sign_date and td < req.sign_date:
            extra_notes.append(f"第{len(inst) + 1}期付款日期 {td} 早于签署日期 {req.sign_date}，请核对")
        trigger = str(x.get("trigger") or "").strip()
        if not td and not trigger:
            extra_notes.append(f"第{len(inst) + 1}期未写明付款时间／节点／条件，请补充后再生成")
        inst.append({
            "seq": len(inst) + 1,
            "amount": amt,
            "label": str(x.get("label") or "").strip()[:6],
            "trigger": trigger,
            "trigger_date": td,
        })
    if extra_notes:
        result["notes"] = (result.get("notes") or []) + extra_notes
    preset_n = len(get_type(req.type).get("pay_preset") or [])
    if matches and len(inst) != preset_n:
        matches = False
        result["matches_preset"] = False  # 期数不符自动转自定义，属正常路径无需提示
    if not inst:
        raise HTTPException(422, "未解析出任何分期，请在付款计划表中手动填写")
    result["installments"] = inst
    result["sum"] = sum(x["amount"] for x in inst)
    return result


class PayRow(BaseModel):
    label: str = ""
    amount: int
    date: Optional[str] = None  # 绝对付款日期（YYYY-MM-DD）
    event: str = ""              # 付款事件条件


class Payment(BaseModel):
    installments: List[PayRow]
    source_text: Optional[str] = None


class GenerateReq(BaseModel):
    type: str
    form: dict
    payment: Payment


@router.post("/generate")
def generate(req: GenerateReq):
    cfg = get_type(req.type)
    form = req.form
    # 统一分期表 → 生成器付款 dict（服务端判定 模板预设/一次性/自定义，并校验分期合计=总费用）
    total = int(form.get("total_price") or form.get("total_fee") or 0)
    try:
        payment = derive_payment(req.type, req.payment.model_dump(), total)
    except ValueError as ex:
        raise HTTPException(422, str(ex))

    # 编号一律服务端自动分配（预约制：分配即落库占位，失败自动释放，无并发重复窗口）
    no = store.reserve_no()
    filename = f"{no}-{TYPE_LABEL_FILE.get(req.type, req.type)}.docx"
    out_path = os.path.join(store.OUT_DIR, filename)

    try:
        report = build_contract(req.type, form, payment, no, out_path)
        report["agreement_no"] = no

        from docx import Document
        doc = Document(out_path)
        errors = check_rules(req.type, form, payment, report, doc)
        fp_issues = check_fingerprint(report["template"], out_path, req.type, report, form)
        errors.extend(fp_issues)

        # LLM 语义复核（软校验：失败不拦截，标注警告）
        warnings = []
        text = extract_contract_text(doc)
        try:
            rv = llm.chat_json(review_messages(text, build_summary(req.type, form, payment)),
                               max_tokens=1200, timeout=60, thinking=True)
            if not rv.get("pass"):
                for iss in rv.get("issues") or []:
                    if _is_confirmation(iss):
                        continue
                    warnings.append(f"LLM复核：{iss}")
        except llm.LLMError as ex:
            warnings.append(f"LLM复核未完成（{ex}），规则校验已通过")
    except ValueError as ex:
        store.release_no(no)
        raise HTTPException(422, str(ex))
    except Exception as ex:
        traceback.print_exc()
        store.release_no(no)
        raise HTTPException(500, f"生成失败：{ex}")

    status = "ok" if not errors else "failed"
    store.confirm_no(no, req.type, form.get("client_name") or "", payment.get("mode", ""),
                     form.get("currency", ""), filename, status)

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
    if rec["status"] != "ok":
        raise HTTPException(403, "该合同未通过核对，不提供下载；请按问题清单修正后重新生成")
    path = os.path.join(store.OUT_DIR, rec["filename"])
    if not os.path.exists(path):
        raise HTTPException(404, "文件不存在")
    # 中文文件名双格式：filename* (RFC 5987) 供现代浏览器，ASCII 回退 filename 供
    # 部分 macOS/iOS Safari 与下载工具（Starlette 只发 filename*，回退缺失时名称乱码或下载失败）
    from urllib.parse import quote
    fallback = f"{no}{os.path.splitext(rec['filename'])[1]}"
    disposition = (f'attachment; filename="{fallback}"; '
                   f"filename*=utf-8''{quote(rec['filename'])}")
    return FileResponse(path, filename=None,
                        headers={"content-disposition": disposition},
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/history")
def get_history():
    return {"items": store.history()}


@router.get("/health")
def health():
    return {"status": "ok", "model": llm.MODEL, "key_set": bool(llm.API_KEY)}
