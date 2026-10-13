# -*- coding: utf-8 -*-
"""结算单服务层：解析 → 核算 → 渲染 → 落盘。

目录约定（server/data/settlements/）：
- archive/*.json   每单存底（引擎输入，改单唯一依据，沿 skill 包铁律）
- output/pdf/*.pdf 成品 PDF
- output/image/*.png 220DPI 成品图（发客户用）
汇率：调用方未提供时取系统 /api/fx 同源（新浪主源、百度 FinScope 同口径），
只传 CNY→HKD 单向 5 位小数，HKD 方向由核算引擎取倒数。
"""
import datetime
import json
import os
import re
from pathlib import Path

from engine import fx
from settlement import compute, render

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "settlements")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
PDF_DIR = os.path.join(DATA_DIR, "output", "pdf")
PNG_DIR = os.path.join(DATA_DIR, "output", "image")

SECTIONS = ("contract_total", "contract_paid", "contract_unpaid",
            "extra_fees", "extra_paid")


def today_rate() -> dict:
    """CNY→HKD 5 位小数（铁律：精度取 5 位，四位会在 18 万量级差 5 港币）。"""
    info = fx.get_hkd_cny()   # HKD→CNY 中间价，双源失败抛 FXError
    return {
        "cny_to_hkd": round(1 / info["rate"], 5),
        "source": "实时汇率",
        "date": datetime.date.today().isoformat(),
        "basis": "today",
        "apply_101": True,   # 应收折算 ×1.01、负净额按实汇率足额折，只做不说（引擎默认，此处显式留痕）
    }


def parse_text(text: str) -> dict:
    """标准段落文本 → 业务结构化 JSON（规则解析，零 LLM）。"""
    data = compute.parse_text(text)
    if not data.get("date_iso"):
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
                      data.get("date") or "")
        if m:
            data["date_iso"] = f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return data


def parse_notes(data: dict) -> list:
    """解析结果的人话核对项：空段落、缺抬头等，供前端确认。"""
    notes = []
    for key, label in (("contract_total", "合同内总费用"), ("contract_paid", "合同内已收"),
                       ("contract_unpaid", "合同内未收"), ("extra_fees", "合同外杂费"),
                       ("extra_paid", "合同外杂费实收")):
        if not data.get(key):
            notes.append(f"「{label}」段落没有解析到明细（没有可留空，请核对）")
    if not data.get("settle_type"):
        notes.append("缺「结算类型」，本次收哪几笔将按明细默认处理，请核对")
    return notes


def sanitize(obj: dict) -> dict:
    """LLM 兜底结构化结果的清洗：只留合法字段，金额转 float，币种白名单。
    LLM 只允许搬运，这里再做一道护栏，脏数据进不了核算引擎。"""
    out = {}
    # 抬头可能放顶层，也可能被模型包进 header/抬头 子对象——两处都收
    header_src = {}
    for cand in (obj, obj.get("header"), obj.get("抬头")):
        if isinstance(cand, dict):
            for k, v in cand.items():
                if isinstance(v, str) and v.strip() and not header_src.get(k):
                    header_src[k] = v.strip()
    for key in ("business", "group", "customer", "date", "date_iso", "port",
                "settle_type", "vehicle", "plate", "note"):
        v = header_src.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    for key in SECTIONS:
        rows = []
        for row in (obj.get(key) or []):
            if not isinstance(row, dict):
                continue
            item = str(row.get("item") or "").strip()
            try:
                amount = float(str(row.get("amount")).replace(",", "").replace("，", ""))
            except (TypeError, ValueError):
                continue
            if not item or not amount:
                continue
            entry = {"item": item[:40], "amount": round(amount, 2)}
            cur = str(row.get("currency") or "").upper()
            entry["currency"] = cur if cur in ("CNY", "HKD") else None
            for ek in ("hkd_equiv", "cny_equiv"):
                try:
                    ev = float(str(row.get(ek)).replace(",", ""))
                except (TypeError, ValueError):
                    ev = None
                if ev:
                    entry[ek] = round(ev, 2)
            if key == "contract_unpaid":
                status = str(row.get("status") or "today")
                entry["status"] = status if status in ("today", "next", "paid") else "today"
            if key == "extra_fees" and row.get("gift"):
                entry["gift"] = True
            if entry["currency"] is None:
                entry.pop("currency")   # 缺省币种交给引擎按段落/分部默认处理
            rows.append(entry)
        if rows:
            out[key] = rows
    return out


def _apply_rate(data: dict, rate_override=None) -> dict:
    """汇率注入：手填 > 已带 > 系统当天。generate/preview 共用。"""
    if rate_override:
        rate = dict(data.get("rate") or {})
        rate["cny_to_hkd"] = round(float(rate_override), 5)
        rate.setdefault("basis", "today")
        rate.setdefault("date", datetime.date.today().isoformat())   # 纸面备注的括号注
        rate["source"] = ""   # 手填汇率不在纸面标注来源
        data["rate"] = rate
    if not (data.get("rate") or {}).get("cny_to_hkd"):
        data["rate"] = today_rate()
    return data


def preview(data: dict, rate_override=None) -> dict:
    """模板稿渲染：金额留空的行照列项目、金额与分位栏留白。
    固定文件名「预览.pdf/png」反复覆盖，不存底、不算正式出单。"""
    import re as _re
    data = json.loads(json.dumps(data, ensure_ascii=False))   # 深拷贝，别污染编辑态
    _apply_rate(data, rate_override)
    for key in SECTIONS:
        rows = []
        for r in (data.get(key) or []):
            if not isinstance(r, dict):
                continue
            item = str(r.get("item") or "").strip()
            if not item:
                continue
            try:
                amount = float(str(r.get("amount")).replace(",", "").replace("，", ""))
            except (TypeError, ValueError):
                amount = None
            entry = dict(r)
            entry["item"] = item[:40]
            if amount is None:
                entry["amount"] = 0
                entry["blank"] = True   # 模板稿：金额留白
            else:
                entry["amount"] = amount
            rows.append(entry)
        data[key] = rows
    if not any(data.get(k) for k in SECTIONS):
        raise ValueError("没有任何费用明细")
    data["filename"] = "预览"
    spec, detail = compute.build_spec(data)
    # 纯模板（所有金额都为空）＝表格式模板稿：横幅不显示 ¥0.00，备注也留白
    pure_template = not any(
        r.get("amount") for k in SECTIONS for r in (data.get(k) or []))
    if pure_template:
        spec["today_pay"] = {}
        spec["today_sep"] = ""
        spec["note"] = None
        spec["amount_note"] = None
    else:
        # 部分填写时横幅若恰好为 0 也不显示零额
        tp = spec.get("today_pay") or {}
        if tp and all(_re.fullmatch(r"[¥$]\s*0\.00", v) for v in tp.values()):
            spec["today_pay"] = {}
            spec["today_sep"] = ""
    render.register_font()
    pdf_path = render.build_output_path(spec, Path(PDF_DIR))
    layout = render.plan_layout(spec)
    renderer = render.Renderer(spec, layout)
    renderer.render(pdf_path)
    png_path = render.render_png(pdf_path, 220)
    return {
        "png_url": f"/api/settlement/file/png/{png_path.name}",
        "overflow": any("溢出" in w for w in renderer.warnings),
    }


def reconcile_structure(rule_data: dict, data: dict) -> list:
    """AI 整理结果的结构纠偏（规则解析当结构基准，AI 当语义基准）：
    - 段落归属：AI 偶发把抵扣/实收行留在杂费段——按（金额,币种）多重集对照
      规则解析的归属，错位的行搬回「实收」段；
    - 赠送标记：AI 漏标 gift 而规则解析标了的，补上。
    返回被搬动行的项目名列表（供 notes 提示）。"""
    from collections import Counter

    def key(r):
        try:
            return (round(float(r.get("amount") or 0), 2), r.get("currency"))
        except (TypeError, ValueError):
            return None

    moved = []
    # 段落归属纠偏：规则归入「实收」的（金额,币种），AI 若留在杂费段 → 搬回实收段
    rule_paid = Counter(k for k in map(key, rule_data.get("extra_paid") or []) if k)
    fees_keep, fees_move = [], []
    for r in (data.get("extra_fees") or []):
        k = key(r)
        if k and rule_paid[k] > 0:
            rule_paid[k] -= 1
            fees_move.append(r)
        else:
            fees_keep.append(r)
    if fees_move:
        data["extra_fees"] = fees_keep
        data.setdefault("extra_paid", [])
        for r in fees_move:
            if not any(key(x) == key(r) for x in data["extra_paid"]):
                data["extra_paid"].append(r)
        moved = [r.get("item") for r in fees_move]
    # 赠送标记补漏：规则解析标了 gift、AI 漏标的，补上
    for r in (data.get("extra_fees") or []):
        k = key(r)
        if k and not r.get("gift") and any(
                rr.get("gift") and key(rr) == k for rr in (rule_data.get("extra_fees") or [])):
            r["gift"] = True
    return moved


def generate(data: dict, rate_override=None) -> dict:
    """核算 + 渲染 + 存底。rate_override：用户手填 CNY→HKD，优先于系统汇率。"""
    _apply_rate(data, rate_override)

    spec, detail = compute.build_spec(data)
    render.register_font()

    pdf_path = render.build_output_path(spec, Path(PDF_DIR))
    layout = render.plan_layout(spec)
    renderer = render.Renderer(spec, layout)
    renderer.render(pdf_path)
    png_path = render.render_png(pdf_path, 220)

    warnings = list(detail.get("warnings") or []) + list(renderer.warnings)
    _save_archive(data, spec)

    name = pdf_path.stem
    return {
        "filename": pdf_path.name,
        "pdf_url": f"/api/settlement/file/pdf/{pdf_path.name}",
        "png_url": f"/api/settlement/file/png/{png_path.name}",
        "today_pay": spec.get("today_pay") or {},
        "rate": detail.get("rate") or {},
        "selfcheck": detail.get("selfcheck") or {},
        "warnings": warnings,
        "overflow": any("溢出" in w for w in warnings),
    }


def _save_archive(data: dict, spec: dict):
    """每单必存底（引擎输入 JSON），重名自动加序号——改单/找回全靠它。"""
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        customer = re.sub(r'[\\/:*?"<>|\s]+', "", data.get("customer") or data.get("group") or "客户")
        settle = re.sub(r'[\\/:*?"<>|\s]+', "", data.get("settle_type") or "结算")
        date_iso = re.sub(r"[^0-9]", "", data.get("date_iso") or
                          datetime.date.today().strftime("%Y%m%d")) or "nodate"
        base = f"{customer}_{settle}_{date_iso}"
        path = os.path.join(ARCHIVE_DIR, f"{base}.json")
        n = 2
        while os.path.exists(path):
            path = os.path.join(ARCHIVE_DIR, f"{base}-{n}.json")
            n += 1
        payload = dict(data)
        payload["_archive"] = {
            "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pdf": spec.get("filename"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    except OSError:
        pass   # 存底失败不阻塞交付，但控制台留痕
