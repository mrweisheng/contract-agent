# -*- coding: utf-8 -*-
"""
合同组装器：按类型配置 + 表单数据 + 付款计划，在模板副本上生成合同。
确定性渲染（条款文字由模板句式生成，LLM 不参与落盘文字），保证可控。
"""
import copy
import os
import shutil
from docx import Document

from engine import writer as W
from engine.types_config import get_type, template_path
from engine.money import to_cn_upper, with_commas, currency_label, currency_symbol, amount_phrase

PARTY_LABEL_MAP = [
    ("证件", "client_id"),
    ("联络人", "client_contact"),
    ("联络电话", "client_phone"),
    ("联络地址", "client_address"),
    ("地址", "client_address"),
]


def _party_label_to_field(label_text: str):
    if "买方" in label_text or "委托方" in label_text or "甲方（委托方" in label_text:
        return "client_name"
    for kw, field in PARTY_LABEL_MAP:
        if kw in label_text:
            return field
    return None


def build_contract(type_key: str, form: dict, payment: dict, agreement_no: str, out_path: str):
    """生成合同，返回变更报告（供核对器比对）。"""
    cfg = get_type(type_key)
    tpl = template_path(cfg, form)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    shutil.copyfile(tpl, out_path)
    doc = Document(out_path)

    cur = form.get("currency") or cfg["currency_default"]
    report = {"type": type_key, "currency": cur, "fee_rows": [], "section_paras": None}

    # 1. 顶部编号/日期行
    meta = doc.paragraphs[0]
    sign_date = form.get("sign_date")
    sign_cn = W.date_cn(sign_date) if sign_date else W.today_cn()
    n = W.fill_blanks_in_paragraph(meta, [agreement_no, sign_cn])
    if n < 2:
        raise ValueError("模板顶部编号/日期行缺少空位，请检查模板")

    # 2. 甲乙双方表（客户侧）
    party_tbl = W.find_table(doc, cfg["party_table_anchor"])
    if party_tbl is None:
        raise ValueError("找不到甲乙双方信息表")
    lc, vc = cfg["party_label_col"], cfg["party_value_col"]
    for row in party_tbl.rows:
        label = row.cells[lc].text.strip()
        field = _party_label_to_field(label)
        if field:
            val = str(form.get(field) or "").strip()
            W.set_cell_text(row.cells[vc], val)

    # 3. 键值表（车辆/指标数据）
    for kv in cfg.get("kv_tables", []):
        t = W.find_table(doc, kv["anchor"])
        if t is None:
            raise ValueError(f"找不到数据表（锚点 {kv['anchor']}）")
        for row in t.rows:
            label = row.cells[0].text.strip()
            for key, field in kv["map"].items():
                if key in label:
                    val = form.get(field)
                    if field == "quota_type":
                        val = cfg["quota_auto"]
                    W.set_cell_text(row.cells[1], str(val or "").strip())

    # 4. 换车费用（过户类）
    if cfg.get("exchange_fee"):
        t = W.find_table(doc, cfg["exchange_fee"]["anchor"])
        if t is not None:
            amt = int(form.get("exchange_fee") or 0)
            row = t.rows[0]
            W.set_cell_text(row.cells[1], amount_phrase(amt, cur))
            report["exchange_fee"] = amt

    # 5. 付款计划 → 条款区 + 费用表
    fee_tbl = W.find_table(doc, cfg["fee_table_anchor"])
    if fee_tbl is None:
        raise ValueError("找不到费用表")
    total = int(form.get("total_price") or form.get("total_fee") or 0)
    report["total"] = total
    mode = payment.get("mode", "default")
    report["mode"] = mode
    sec_no, next_no = cfg["payment_section"]

    if mode == "default":
        _default_mode(doc, cfg, fee_tbl, form, payment, cur, total, report)
    elif mode == "one_time":
        _one_time_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no)
    elif mode == "custom":
        _custom_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no)
    else:
        raise ValueError(f"未知付款模式 {mode}")

    doc.save(out_path)
    report["template"] = tpl
    report["output"] = out_path
    return report


# ---------------- 三种付款模式 ----------------

def _fill_amount_cell(row, cfg, cur, amount, total=None):
    style = cfg["fee_cell_style"]
    if style == "split":
        W.set_cell_text(row.cells[1], f"{currency_label(cur)}（大写）{to_cn_upper(amount)}")
        W.set_cell_text(row.cells[2], f"{currency_symbol(cur)}{with_commas(amount)}")
    else:  # single / single_rmb 统一替换单元格为完整金额短语
        W.set_cell_text(row.cells[1], amount_phrase(amount, cur))


def _default_mode(doc, cfg, fee_tbl, form, payment, cur, total, report):
    # 费用表：总金额行
    rows = fee_tbl.rows
    _fill_amount_cell(rows[0], cfg, cur, total)

    if cfg.get("car_default"):
        # 卖车默认两段：订金 / 订金日期 / 尾款（自动=总价-订金）
        deposit = int(payment.get("deposit_amount") or 0)
        balance = total - deposit
        _fill_amount_cell(rows[1], cfg, cur, deposit)
        W.set_cell_text(rows[2].cells[1], W.date_cn(payment["deposit_date"]))
        _fill_amount_cell(rows[3], cfg, cur, balance)
        report["fee_rows"] = [W.row_label(r) for r in rows]
        report["amounts"] = [total, deposit, balance]
        # 03 条填空：较早/较晚选择 + 尾款日期
        start, end = W.section_range(doc, *cfg["payment_section"])
        p = doc.paragraphs[start]
        choice = payment.get("choice") or "较早者"
        W.replace_in_paragraph(p, "较早者／较后者为准：________", f"{choice}为准")
        y, m, d = W.iso_date_parts(payment["balance_date"])
        W.fill_blanks_in_paragraph(p, [y, m, d])
        if BLANK_LEFT(p):
            raise ValueError("卖车 03 条填空后仍有残留空位")
        report["section_paras"] = end - start
    else:
        # 过户/新办默认三期（触发时点为模板固定文字，仅填金额）
        amounts = [int(payment.get(k) or 0) for k in ("pay1", "pay2", "pay3")]
        for i, amt in enumerate(amounts):
            _fill_amount_cell(rows[i + 1], cfg, cur, amt)
        report["fee_rows"] = [W.row_label(r) for r in rows]
        report["amounts"] = [total] + amounts
        report["section_paras"] = None  # 条款文字不变


def BLANK_LEFT(p) -> bool:
    import re
    return bool(re.search(r"_{2,}", "".join(r.text for r in p.runs)))


def _ot_desc(payment) -> str:
    date = payment.get("pay_date") or ""
    event = (payment.get("pay_event") or "").strip()
    choice = payment.get("choice") or "较早者"
    if date and event:
        return f"{W.date_cn(date)}或{event}（以{choice}为准）"
    if date:
        return W.date_cn(date)
    return event or ""


def _one_time_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no):
    rows = fee_tbl.rows
    _fill_amount_cell(rows[0], cfg, cur, total)
    desc = _ot_desc(payment)
    if not desc:
        raise ValueError("一次性付清需提供支付日期或条件")
    W.set_cell_text(rows[1].cells[0], "付款方式")
    if cfg["fee_cell_style"] == "split":
        W.set_cell_text(rows[1].cells[1], f"一次性全款支付（{desc}）")
        W.set_cell_text(rows[1].cells[2], "")
    else:
        W.set_cell_text(rows[1].cells[1], f"一次性全款支付（{desc}）")
    # 删除其余分期行
    for idx in range(len(rows) - 1, 1, -1):
        W.delete_row(fee_tbl, idx)
    report["fee_rows"] = [W.row_label(r) for r in fee_tbl.rows]
    report["amounts"] = [total]
    # 条款改写为单段
    payer, payee = cfg["payer"], cfg["payee"]
    if cfg.get("car_default"):
        text = (f"车辆总售价{amount_phrase(total, cur)}须于{desc}，"
                f"由乙方一次性支付予甲方。")
    else:
        text = (f"服务总费用{amount_phrase(total, cur)}须于{desc}，"
                f"由{payer}一次性支付予{payee}。")
    n = W.rewrite_section(doc, sec_no, next_no, [text])
    report["section_paras"] = n


def _custom_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no):
    installments = payment.get("installments") or []
    if not installments:
        raise ValueError("自定义分期缺少期次数据")
    amounts = [int(x.get("amount") or 0) for x in installments]
    if sum(amounts) != total:
        raise ValueError(f"各期合计 {sum(amounts)} ≠ 总费用 {total}，请先在界面修正")
    rows = fee_tbl.rows
    _fill_amount_cell(rows[0], cfg, cur, total)
    n = len(installments)
    # 统一行样式：以模板第1数据行为源，删除原有分期行后克隆 n 份
    src_tr = copy.deepcopy(rows[1]._tr)
    while len(fee_tbl.rows) > 1:
        W.delete_row(fee_tbl, 1)
    for _ in range(n):
        fee_tbl._tbl.append(copy.deepcopy(src_tr))
    rows = fee_tbl.rows
    for i, ins in enumerate(installments):
        row = rows[i + 1]
        W.set_cell_text(row.cells[0], f"第{W.seq_cn(i + 1)}期")
        _fill_amount_cell(row, cfg, cur, amounts[i])
    report["fee_rows"] = [W.row_label(r) for r in rows]
    report["amounts"] = [total] + amounts
    # 条款区改写：总括句一次说清「共 N 期」「付款方」,每期只说日期+金额,
    # 避免「共 N 期」「由 X 支付予 Y」每期重复造成冗余排版
    payer, payee = cfg["payer"], cfg["payee"]
    total_label = cfg.get("fee_total_label", "总价款")
    texts = [
        f"{total_label}{amount_phrase(total, cur)}，分{W.seq_cn(n)}期支付，由{payer}支付予{payee}："
    ]
    for i, ins in enumerate(installments):
        trigger = (ins.get("trigger") or "").strip() or "按双方约定"
        trigger_date = (ins.get("trigger_date") or "").strip()
        # 优先用绝对日期(LLM 基于签署日期推算),保留原 trigger 作为括注便于人工核对
        if trigger_date:
            time_desc = f"{trigger_date}（{trigger}）"
        else:
            time_desc = trigger
        texts.append(
            f"第{W.seq_cn(i + 1)}期款：{time_desc}，{amount_phrase(amounts[i], cur)}。"
        )
    n_para = W.rewrite_section(doc, sec_no, next_no, texts)
    report["section_paras"] = n_para
