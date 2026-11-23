# -*- coding: utf-8 -*-
"""对外查询接口（只读 + 签名回传）：小程序等外部系统查已生成合同。

鉴权：环境变量 OPEN_API_KEY 未配置时，整个 /api/open 前缀返回 403 未启用；
配置后请求须带 X-API-Key 头（或 ?key= 查询参数，便于小程序简单接入）。
所有接口只读（除签名回传），不暴露服务器内部路径。
签名回传：客户在小程序手写签名（透明 PNG）→ 合成进合同 docx 的乙方签署块 →
存为「已签版」副本，原 docx 不动；gens 表落 signed_path/signed_at。
"""
import base64
import io
import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import FileResponse
from docx import Document
from docx.shared import Inches

from . import store


def _guard(x_api_key: str | None = Header(default=None), key: str | None = None):
    expect = os.getenv("OPEN_API_KEY", "").strip()
    if not expect:
        raise HTTPException(403, "对外查询接口未启用（服务器未配置 OPEN_API_KEY）")
    given = (x_api_key or key or "").strip()
    if given != expect:
        raise HTTPException(401, "API Key 不正确")


router = APIRouter(prefix="/api/open", dependencies=[Depends(_guard)])


# 对外可见起始日（含当天）：只对外提供 2026-11-22 及以后生成的合同。
# 历史单不对外——对外接口的 key 是全局共享的，收敛可见范围即收敛客户隐私暴露面。
# 要放开更早历史，只改这一处；比较取 created_at 的 YYYY-MM-DD 部分。
VISIBLE_FROM = "2026-11-22"


def _visible(rec: dict) -> bool:
    return (rec.get("created_at") or "")[:10] >= VISIBLE_FROM


def _gen(no: str, allow_sample: bool = False) -> dict:
    rec = store.get_gen(no)
    # 早于可见起始日一律按「不存在」处理：不暴露历史单是否存在（编号可按日期枚举）
    if not rec or rec.get("status") != "ok" or not _visible(rec):
        raise HTTPException(404, "合同不存在")
    # 示例合同只走登录用户自己的 /api/users/me/*，对外接口与工作台一律不可见
    if rec.get("is_sample") and not allow_sample:
        raise HTTPException(404, "合同不存在")
    return rec


def _form_path(rec: dict) -> str:
    return os.path.join(store.OUT_DIR, rec["filename"].rsplit(".docx", 1)[0] + ".form.json")


def _read_form(rec: dict) -> dict:
    """生成时存档的表单结构化数据；旧单（存档机制上线前生成）缺这份 → 提示重新生成。"""
    path = _form_path(rec)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------- docx → blocks：把成品合同拆成前端可直接渲染的内容块 ----------

_META_PAT = re.compile(r"合约编号|合同编号|AGREEMENT\s+NO")
_H_PAT = re.compile(r"^[一二三四五六七八九十百]+\s*、")
# 老模板里个别条款标题没套 Heading 样式（如「签署确认  |  SIGNATURES」是 Normal），
# 按「短中文 | 纯英文」形态兜底识别；正文不会出现这个形态
_H_PIPE_PAT = re.compile(r"^[^|]{2,20}\|\s*[A-Za-z][A-Za-z0-9 ,&'().-]*$")


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _body_elements(doc):
    """按文档顺序产出段落与表格（docx 正文是 p/tbl 交错，不能按两类分开遍历）。"""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _table_rows(tb) -> list:
    """表格 → 二维字符串数组；合并格在重复出现处留空串占位（横向/纵向合并都适用）。

    注意必须持有 tc 元素引用做身份比对：lxml 代理对象会被回收，id() 会复用，
    不能拿 id 当去重键。"""
    rows, seen = [], []
    for r in tb.rows:
        row = []
        for c in r.cells:
            if any(prev is c._tc for prev in seen):
                row.append("")
                continue
            seen.append(c._tc)
            row.append(c.text.strip())
        rows.append(row)
    return rows


def _split_heading(text: str) -> dict:
    """「一、合约双方  |  PARTIES」→ {text: 一、合约双方, en: PARTIES}；无英文段则省略 en。"""
    if "|" in text:
        left, _, right = text.partition("|")
        return {"text": left.strip(), "en": right.strip()}
    return {"text": text}


def extract_blocks(docx_path: str) -> list:
    """成品 docx → 内容块数组，顺序与文档完全一致。

    kind: title 主标题 / subtitle 英文副标 / meta 编号日期行 / h 条款标题 /
          p 正文 / table 数据表 / sign 签署块（文档最后一张表）。
    固定文本与动态条款（附赠/质保/其他承诺）在 docx 里已组装完成，这里原样切分，
    前端照块渲染即可，不需要任何模板知识。"""
    doc = Document(docx_path)
    elements = list(_body_elements(doc))
    last_tbl = next((el._tbl for el in reversed(elements) if hasattr(el, "_tbl")), None)
    blocks, title_done, after_title = [], False, False
    for el in elements:
        if hasattr(el, "_tbl"):  # Table
            rows = _table_rows(el)
            if not rows:
                continue
            if el._tbl is last_tbl:
                # 公司印信图在不在签署格里（生成即盖章；旧单/缺印信环境无图）
                blocks.append({"kind": "sign", "rows": rows,
                               "stamped": bool(el._tbl.xpath(".//pic:pic"))})
            else:
                blocks.append({"kind": "table", "rows": rows})
            after_title = False
            continue
        text = el.text.strip()
        if not text:
            continue
        if not title_done:
            if _META_PAT.search(text):  # 车/过户/新办：编号行在标题前
                blocks.append({"kind": "meta", "text": text})
                continue
            blocks.append({"kind": "title", "text": text})  # 高才移民：首段即标题
            title_done, after_title = True, True
            continue
        if after_title and not _has_cjk(text) and len(text) >= 8:
            blocks.append({"kind": "subtitle", "text": text})
            after_title = False
            continue
        after_title = False
        if _META_PAT.search(text):
            blocks.append({"kind": "meta", "text": text})
        else:
            style_name = el.style.name if el.style is not None else ""
            if (style_name or "").lower().startswith("heading") or _H_PAT.match(text) \
                    or _H_PIPE_PAT.match(text):
                blocks.append({"kind": "h", **_split_heading(text)})
            else:
                blocks.append({"kind": "p", "text": text})
    return blocks


def apply_signature(src_docx: str, dst_docx: str, sig_bytes: bytes):
    """把客户签名 PNG 合成进客户签署格，存为已签版。

    客户格不能按甲/乙关键字找：卖车/过户客户是乙方，新办/高才移民客户是甲方——
    公司恒为「华星资源开发有限公司」，客户格=签署格里不含公司名的那个（engine.seal.locate）。
    签名以等高段插在签名线/日期之前，公司格对称插等高空段，两边日期保持同一水平线。"""
    from engine import seal as seal_mod
    doc = Document(src_docx)
    located = seal_mod.locate(doc)
    if not located:
        raise HTTPException(422, "该合同模板缺少客户签署格，无法合成签名")
    comp, cli = located
    width = Inches(1.7)
    from PIL import Image as PILImage
    probe = PILImage.open(io.BytesIO(sig_bytes))
    sig_w, sig_h_px = probe.size
    sig_h = width.inches * sig_h_px / sig_w
    sig_img = io.BytesIO(sig_bytes)

    cli_date = seal_mod.first_para_with(cli, "日期")
    if cli_date is not None:
        # 车/过户/新办：签名段插在签名线之后（贴线下缘），公司格对称插同尺寸透明占位
        p_line = seal_mod.first_para_with(cli, "____") or cli_date
        sig_p = seal_mod.blank_para_before(cli_date, sig_h)
        sig_p.add_run().add_picture(sig_img, width=width)
        comp_date = seal_mod.first_para_with(comp, "日期")
        if comp_date is not None:
            seal_mod.transparent_spacer_para_before(comp_date, width, sig_h)
    else:
        # 高才移民：客户格只有签名线段，签名段插在线段之前（贴线上缘），
        # 行高增长为通栏共享行整体下移，日期天然对齐
        p_line = seal_mod.first_para_with(cli, "____")
        if p_line is None:
            raise HTTPException(422, "该合同模板缺少客户签名栏，无法合成签名")
        sig_p = seal_mod.blank_para_before(p_line, sig_h)
        sig_p.add_run().add_picture(sig_img, width=width)
    doc.save(dst_docx)


def _decode_sig(image: str) -> bytes:
    """解码签名图：支持 data URL 或裸 base64，校验 PNG 魔数与体积上限。"""
    s = (image or "").strip()
    if s.startswith("data:image/png;base64,"):
        s = s[len("data:image/png;base64,"):]
    try:
        raw = base64.b64decode(s, validate=True)
    except Exception:
        raise HTTPException(422, "签名图不是合法的 base64")
    if not raw.startswith(b"\x89PNG"):
        raise HTTPException(422, "签名图必须是 PNG 格式（建议透明底）")
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(422, "签名图过大（上限 2MB）")
    return raw


@router.get("/contracts")
def list_contracts(client: str | None = None, type: str | None = None, limit: int = 50):
    # 只列可见范围内的 ok 单（SQL 层按 created_at 日期过滤），按生成时间倒序
    total, rows = store.contracts_query(
        date_from=VISIBLE_FROM,
        client=(client or "").strip(),
        type_key=(type or "").strip(),
        limit=max(1, min(limit, 200)),
    )
    return {"total": total, "items": [{
        "no": r["no"], "type": r["type"], "client": r["client"], "mode": r["mode"],
        "currency": r["currency"], "filename": r["filename"], "created_at": r["created_at"],
        "review_status": r.get("review_status") or "",
        "signed": bool(r.get("signed_path")), "signed_at": r.get("signed_at") or "",
    } for r in rows]}


def _contract_detail(no: str, allow_sample: bool = False):
    rec = _gen(no, allow_sample=allow_sample)
    form_doc = _read_form(rec)
    from engine.types_config import get_type
    try:
        type_label = get_type(rec["type"]).get("label") or rec["type"]
    except Exception:
        type_label = rec["type"]
    return {
        "no": rec["no"], "type": rec["type"], "type_label": type_label,
        "client": rec["client"], "mode": rec["mode"], "currency": rec["currency"],
        "filename": rec["filename"], "created_at": rec["created_at"],
        "review_status": rec.get("review_status") or "",
        "signed": bool(rec.get("signed_path")), "signed_at": rec.get("signed_at") or "",
        # 渲染正文：成品 docx 拆成的内容块（固定文本+动态条款已组装好，照块渲染即可）
        "blocks": _extract_blocks_safe(rec),
        # 结构化内容：form=合同字段（见接口说明文档的字段表），payment=付款结构。
        # 仅作补充数据（摘要卡片等），渲染合同以 blocks 为准；旧单可能缺。
        "content": {"form": form_doc.get("form") or {}, "payment": form_doc.get("payment") or {}},
        "content_available": bool(form_doc),
    }


@router.get("/contracts/{no}")
def contract_detail(no: str):
    """对外详情：示例合同不在此暴露。"""
    return _contract_detail(no)


def _extract_blocks_safe(rec: dict) -> list:
    path = os.path.join(store.OUT_DIR, rec["filename"])
    if not os.path.exists(path):
        return []
    try:
        return extract_blocks(path)
    except Exception:
        return []


def _contract_file(no: str, allow_sample: bool = False):
    rec = _gen(no, allow_sample=allow_sample)
    signed = rec.get("signed_path")
    path = os.path.join(store.OUT_DIR, signed) if signed else os.path.join(store.OUT_DIR, rec["filename"])
    if not os.path.exists(path):
        raise HTTPException(404, "合同文件不存在")
    return FileResponse(path, filename=os.path.basename(path),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/contracts/{no}/file")
def contract_file(no: str):
    return _contract_file(no)


@router.get("/company-seal.png")
def open_company_seal():
    """公司公章透明 PNG（key 鉴权）——小程序渲染 sign 块公司侧用。"""
    return _seal_asset("seal.png")


@router.get("/company-sign.png")
def open_company_sign():
    """公司签字透明 PNG（key 鉴权）。"""
    return _seal_asset("sign.png")


def _seal_asset(name: str):
    path = os.path.join(store.DATA_DIR, "seals", name)
    if not os.path.exists(path):
        raise HTTPException(404, "公司印信文件未配置")
    return FileResponse(path, media_type="image/png")


def _contract_signature_image(no: str, allow_sample: bool = False):
    rec = _gen(no, allow_sample=allow_sample)
    if not rec.get("signed_path"):
        raise HTTPException(404, "该合同尚未签署")
    path = os.path.join(store.OUT_DIR, rec["filename"].rsplit(".docx", 1)[0] + "-签名.png")
    if not os.path.exists(path):
        raise HTTPException(404, "签名图不存在")
    return FileResponse(path, media_type="image/png")


@router.get("/contracts/{no}/signature")
def contract_signature_image(no: str):
    """已签合同的签名图（透明 PNG）——前端叠在 sign 块乙方格里即可，无需下载 docx。"""
    return _contract_signature_image(no)


def _contract_signature(no: str, body: dict, allow_sample: bool = False):
    rec = _gen(no, allow_sample=allow_sample)
    if rec.get("signed_path"):
        raise HTTPException(409, "该合同已签署过（如需重签请先联系作废已签版）")
    sig = _decode_sig(str(body.get("image") or ""))
    src = os.path.join(store.OUT_DIR, rec["filename"])
    if not os.path.exists(src):
        raise HTTPException(404, "合同文件不存在")
    signed_name = rec["filename"].rsplit(".docx", 1)[0] + "-已签.docx"
    dst = os.path.join(store.OUT_DIR, signed_name)
    apply_signature(src, dst, sig)
    sig_store = os.path.join(store.OUT_DIR, rec["filename"].rsplit(".docx", 1)[0] + "-签名.png")
    with open(sig_store, "wb") as fh:
        fh.write(sig)
    store.set_signed(no, signed_name)
    return {"ok": True, "no": no, "signed_filename": signed_name}


@router.post("/contracts/{no}/signature")
def contract_signature(no: str, body: dict):
    return _contract_signature(no, body)
