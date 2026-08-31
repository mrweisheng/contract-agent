# -*- coding: utf-8 -*-
"""
核对器：
1) 规则引擎（硬校验）：必填/残留空位/金额一致/分期合计/币种唯一/编号格式
2) 格式指纹：生成文件 vs 模板，逐段逐表比对样式与文字，非修改点必须零变化
"""
import re
from docx import Document

from engine import writer as W
from engine.money import to_cn_upper, currency_label, currency_symbol
from engine.types_config import get_type

BLANK_RE = re.compile(r"_{2,}")
CUR_TOKENS = ["HK$", "¥", "$", "港币", "人民币"]


# ---------------- 文本提取 ----------------

def extract_contract_text(path_or_doc) -> str:
    if isinstance(path_or_doc, str):
        doc = Document(path_or_doc)
    else:
        doc = path_or_doc
    lines = []
    for p in doc.paragraphs:
        if p.text.strip():
            lines.append(p.text.strip())
    for i, t in enumerate(doc.tables):
        lines.append(f"〔表格{i + 1}〕")
        for row in t.rows:
            cells = []
            for c in row.cells:
                if c.text.strip() not in cells:
                    cells.append(c.text.strip())
            lines.append(" | ".join(cells))
    return "\n".join(lines)


# ---------------- 规则引擎 ----------------

def check_rules(type_key: str, form: dict, payment: dict, report: dict, doc) -> list:
    """返回硬错误列表（空列表=通过）。"""
    cfg = get_type(type_key)
    errors = []

    # 1. 必填字段
    for g in cfg["groups"]:
        for f in g["fields"]:
            if f.get("required") and f.get("auto"):
                continue
            if f.get("required") and not str(form.get(f["key"]) or "").strip():
                errors.append(f"必填项缺失：{f['label']}")
    for f in cfg["fee_fields"]:
        if f.get("required") and not form.get(f["key"]):
            errors.append(f"必填项缺失：{f['label']}")
    if cfg.get("port_required") and not form.get("port"):
        errors.append("必填项缺失：口岸")

    # 2. 残留空位（编号行/双方表/数据表/费用表/条款区）
    meta = doc.paragraphs[0].text
    if BLANK_RE.search(meta):
        errors.append("顶部编号/签署日期行仍有空位未填")

    fee_tbl = W.find_table(doc, cfg["fee_table_anchor"])
    for tbl_anchor in [cfg["party_table_anchor"]] + [kv["anchor"] for kv in cfg.get("kv_tables", [])]:
        t = W.find_table(doc, tbl_anchor)
        if t:
            for row in t.rows:
                joined = " ".join(c.text for c in row.cells)
                if BLANK_RE.search(joined):
                    errors.append(f"信息表存在未填空位：{row.cells[0].text.strip()[:20]}")
    if fee_tbl:
        for row in fee_tbl.rows:
            joined = " ".join(c.text for c in row.cells)
            if BLANK_RE.search(joined):
                errors.append(f"费用表存在未填空位：{row.cells[0].text.strip()[:20]}")
    if cfg.get("exchange_fee"):
        t = W.find_table(doc, cfg["exchange_fee"]["anchor"])
        if t and BLANK_RE.search(" ".join(c.text for c in t.rows[0].cells)):
            errors.append("换车费用表存在未填空位")
    # 条款区残留空位
    sec_no, next_no = cfg["payment_section"]
    try:
        s, e = W.section_range(doc, sec_no, next_no)
        for p in doc.paragraphs[s:e]:
            if BLANK_RE.search(p.text):
                errors.append(f"付款条款区仍有空位未填：{p.text[:30]}…")
    except ValueError as ex:
        errors.append(str(ex))

    # 3. 金额一致性（从文档解析）
    cur = report["currency"]
    if fee_tbl:
        # 总额行
        row0 = fee_tbl.rows[0]
        num, cn = _parse_amount_cells(row0, cfg)
        if num is None:
            errors.append("费用表总金额行无法解析金额")
        else:
            if num != report["total"]:
                errors.append(f"总金额不一致：文档 {num} ≠ 表单 {report['total']}")
            if cn and cn != to_cn_upper(num):
                errors.append("总金额大写与数字不符")
        # 分期合计（不含总金额行；无金额的行如日期行自然跳过）
        amounts = []
        for row in fee_tbl.rows[1:]:
            n2, _ = _parse_amount_cells(row, cfg)
            if n2 is not None and n2 > 0:
                amounts.append(n2)
        if amounts and report.get("mode") in ("default", "custom"):
            if sum(amounts) != report["total"]:
                errors.append(f"分期合计 {sum(amounts)} ≠ 总费用 {report['total']}")

    # 4. 币种唯一
    tokens = set()
    if fee_tbl:
        for row in fee_tbl.rows:
            for c in row.cells:
                for tk in ("HK$", "港币"):
                    if tk in c.text:
                        tokens.add("HKD")
                for tk in ("¥", "人民币"):
                    if tk in c.text:
                        tokens.add("CNY")
                # 新办模板残留的孤立 $ 归为港币语义
                if re.search(r"(?<![A-Za-z￥])\$[\d,]", c.text):
                    tokens.add("HKD")
    if tokens and tokens != {cur}:
        errors.append(f"币种不唯一：文档中出现 {sorted(tokens)}，与所选 {cur} 不一致")

    # 5. 编号格式（自动=11位数字；手写放宽为8~14位数字）
    no = report.get("agreement_no", "")
    if not re.fullmatch(r"\d{8,14}", no):
        errors.append(f"合约编号格式异常：{no}")

    return errors


def _parse_amount_cells(row, cfg):
    """从费用行解析（数字金额, 大写金额含「元整」）。"""
    texts = [c.text for c in row.cells]
    num = cn = None
    for t in texts:
        m = re.search(r"(?:HK\$|¥|\$)\s*([\d,]+)", t)
        if m and num is None:
            num = int(m.group(1).replace(",", ""))
        m2 = re.search(r"（大写）(.+?元整)", t)
        if m2 and cn is None:
            cn = m2.group(1)
    return num, cn


# ---------------- 格式指纹 ----------------

def _run_sig(p):
    sigs = []
    for r in p.runs:
        f = r.font
        color = None
        try:
            color = str(f.color.rgb) if f.color and f.color.rgb else None
        except Exception:
            color = None
        sigs.append((f.name, str(f.size) if f.size else None, bool(f.bold), color))
    return (p.style.name, str(p.alignment), tuple(sigs))


def _tbl_texts(t):
    out = []
    for row in t.rows:
        out.append(tuple(c.text for c in row.cells))
    return out


def check_fingerprint(template_path: str, out_path: str, type_key: str, report: dict) -> list:
    """比对模板与生成件：非修改点必须零变化；修改点样式签名必须与源一致。"""
    cfg = get_type(type_key)
    issues = []
    tpl, out = Document(template_path), Document(out_path)

    # 页眉页脚、节设置
    if len(tpl.sections) != len(out.sections):
        issues.append("节数量与模板不一致")
    else:
        for st, so in zip(tpl.sections, out.sections):
            if st.header is not None and so.header is not None:
                ht = "\n".join(p.text for p in st.header.paragraphs)
                ho = "\n".join(p.text for p in so.header.paragraphs)
                if ht != ho:
                    issues.append("页眉内容与模板不一致")
            ft = "\n".join(p.text for p in st.footer.paragraphs)
            fo = "\n".join(p.text for p in so.footer.paragraphs)
            if ft != fo:
                issues.append("页脚内容与模板不一致")

    # 正文段落：条款区前的所有段落必须完全一致
    sec_no, next_no = cfg["payment_section"]
    try:
        ts, te = W.section_range(tpl, sec_no, next_no)
        os_, oe = W.section_range(out, sec_no, next_no)
    except ValueError as ex:
        issues.append(f"找不到条款区：{ex}")
        return issues

    tp, op = tpl.paragraphs, out.paragraphs
    for i in range(ts - 1):
        if i == 0:
            continue  # 首段为编号/日期行（设计内填充）
        if i >= len(op):
            issues.append(f"段落缺失（第{i + 1}段）")
            break
        if tp[i].text != op[i].text:
            issues.append(f"条款区之前段落被改动：第{i + 1}段「{tp[i].text[:20]}…」")
        elif _run_sig(tp[i]) != _run_sig(op[i]):
            issues.append(f"条款区之前段落格式变化：第{i + 1}段")
    # 条款区之后（尾部对齐）
    tpl_tail = tp[te:]
    out_tail = op[oe:]
    if len(tpl_tail) != len(out_tail):
        issues.append("条款区之后段落数量与模板不一致")
    else:
        for i, (a, b) in enumerate(zip(tpl_tail, out_tail)):
            if a.text != b.text:
                issues.append(f"条款区之后段落被改动：「{a.text[:20]}…」")
                break
            if _run_sig(a) != _run_sig(b):
                issues.append("条款区之后段落格式变化")
                break
    # 条款区：段数=预期；每段样式签名=模板该区首段
    if report.get("section_paras"):
        n_expect = report["section_paras"]
        if oe - os_ != n_expect:
            issues.append(f"付款条款段数 {oe - os_} ≠ 预期 {n_expect}")
        base_sig = _run_sig(tp[ts])
        for p in op[os_:oe]:
            if _run_sig(p) != base_sig:
                issues.append("付款条款段落样式与模板不一致")
                break

    # 表格：除设计内会变的表（甲乙双方/数据表/费用表/换车费表）外，其余必须一致
    skip_anchors = [cfg["fee_table_anchor"], cfg["party_table_anchor"]]
    skip_anchors += [kv["anchor"] for kv in cfg.get("kv_tables", [])]
    if cfg.get("exchange_fee"):
        skip_anchors.append(cfg["exchange_fee"]["anchor"])

    def _tbl_alltext(t):
        return " ".join(c.text for r in t.rows for c in r.cells)

    for t_t in tpl.tables:
        t_all = _tbl_alltext(t_t)
        if any(a in t_all for a in skip_anchors):
            continue
        t_first = t_t.rows[0].cells[0].text.strip()
        t_o = None
        for cand in out.tables:
            if t_first and t_first in _tbl_alltext(cand):
                t_o = cand
                break
        if t_o is None:
            issues.append(f"表格丢失：{t_first[:15]}")
            continue
        if _tbl_texts(t_t) != _tbl_texts(t_o):
            issues.append(f"表格内容被意外改动：{t_first[:15]}")

    # 费用表：列数一致；行样式签名=模板同标签行（无同标签时回退模板第1数据行）；标签符合预期
    tpl_fee = W.find_table(tpl, cfg["fee_table_anchor"])
    out_fee = W.find_table(out, cfg["fee_table_anchor"])
    if tpl_fee is None or out_fee is None:
        issues.append("找不到费用表")
        return issues
    if len(tpl_fee.columns) != len(out_fee.columns):
        issues.append("费用表列数与模板不一致")

    def _row_sig(row):
        return tuple(_run_sig(p) for c in row.cells for p in c.paragraphs)

    sig_by_label = {r.cells[0].text.strip(): _row_sig(r) for r in tpl_fee.rows}
    fallback_sig = _row_sig(tpl_fee.rows[1])
    for row in out_fee.rows:
        label = row.cells[0].text.strip()
        expect = sig_by_label.get(label, fallback_sig)
        if _row_sig(row) != expect:
            issues.append(f"费用表行样式与模板不一致：{label[:15]}")
            break
    expect_labels = report.get("fee_rows") or []
    actual_labels = [r.cells[0].text.strip() for r in out_fee.rows]
    if expect_labels and actual_labels != expect_labels:
        issues.append(f"费用表行标签与预期不符：{actual_labels}")

    return issues
