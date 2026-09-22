# -*- coding: utf-8 -*-
"""
合同组装器：按类型配置 + 表单数据 + 付款计划，在模板副本上生成合同。
确定性渲染（条款文字由模板句式生成，LLM 不参与落盘文字），保证可控。
"""
import copy
import datetime
import os
import re
import shutil
from docx import Document

from engine import writer as W
from engine.types_config import get_type, template_path
from engine.money import (to_cn_upper, with_commas, currency_label, currency_symbol,
                          amount_phrase, clean_amount, clean_currency)

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


def _archive_existing(out_path: str) -> str:
    """目标文件已存在时，先归档旧件（改名加时间戳）再写入，绝不静默覆盖。"""
    base, ext = os.path.splitext(out_path)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    archived = f"{base}-归档{stamp}{ext}"
    n = 1
    while os.path.exists(archived):
        archived = f"{base}-归档{stamp}-{n}{ext}"
        n += 1
    shutil.move(out_path, archived)
    return archived


def build_contract(type_key: str, form: dict, payment: dict, agreement_no: str, out_path: str):
    """生成合同，返回变更报告（供核对器比对）。"""
    cfg = get_type(type_key)
    tpl = template_path(cfg, form)
    # 入参校验前置：币种与总费用先解析，任一不合法就在复制模板之前失败，
    # 避免在 out/ 留下不在历史列表里的孤儿模板副本。
    cur = clean_currency(form.get("currency") or cfg["currency_default"])
    total = clean_amount(form.get("total_price") or form.get("total_fee") or 0, "总费用")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # 纵深防御：同号文件若已存在，先归档旧件，避免旧合同被静默覆盖
    if os.path.exists(out_path):
        _archive_existing(out_path)
    shutil.copyfile(tpl, out_path)
    doc = Document(out_path)

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
                    W.set_cell_text(row.cells[1], str(val or "").strip() or "—")

    # 4. 换车费用（过户类）
    if cfg.get("exchange_fee"):
        t = W.find_table(doc, cfg["exchange_fee"]["anchor"])
        if t is not None:
            amt = clean_amount(form.get("exchange_fee") or 0, "换车费用")
            row = t.rows[0]
            W.set_cell_text(row.cells[1], amount_phrase(amt, cur))
            report["exchange_fee"] = amt

    # 5. 付款计划 → 条款区 + 费用表
    fee_tbl = W.find_table(doc, cfg["fee_table_anchor"])
    if fee_tbl is None:
        raise ValueError("找不到费用表")
    report["total"] = total  # total 已在函数开头严格解析（P1-4：绝不静默截断）
    mode = payment.get("mode", "default")
    report["mode"] = mode
    sec_no, next_no = cfg["payment_section"]

    if mode == "default":
        _default_mode(doc, cfg, fee_tbl, form, payment, cur, total, report, sign_cn)
    elif mode == "one_time":
        _one_time_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no)
    elif mode == "custom":
        _custom_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no)
    else:
        raise ValueError(f"未知付款模式 {mode}")

    # 6. 卖车可选内容：附赠项 / 发动机质保（客户信息提到才落盘，默认全无）
    if type_key == "car":
        _apply_car_extras(doc, form, report)

    doc.save(out_path)
    report["template"] = tpl
    report["output"] = out_path
    return report


# ---------------- 统一付款表 → 生成器付款 dict ----------------

def _apply_car_extras(doc, form: dict, report: dict):
    """附赠（模板 05 节）/ 售后质保（模板 06 节）独立成节：有内容整节保留并写入推导
    文字，无内容整节删除，最后全量重排条款号——无附赠无售后时编号回到 01–09，
    与历史合同形态一致。赠过户费/车险时原 08 条（文件、过户及保险）过户费用句
    与赠项矛盾，须最小改写。文字推导统一走 car_extras。"""
    from engine import car_extras as X

    gifts = X.gift_lines(form)
    wp = X.warranty_paragraph(form)

    # 模板号操作（重排在最后，此前标题仍是模板号）
    if gifts:
        W.rewrite_section(doc, "05", "06", gifts)
    else:
        W.delete_section(doc, "05", "06")
    if wp:
        W.rewrite_section(doc, "06", "07", [wp])
    else:
        W.delete_section(doc, "06", "07")
    report["gift_lines"] = gifts
    report["warranty_on"] = bool(wp)

    if X.gift_transfer_on(form) or X.gift_insurance(form):
        p17 = next((p for p in doc.paragraphs if "车辆过户手续由甲方负责办理" in p.text), None)
        if p17 is None:
            raise ValueError("找不到文件、过户及保险条款的过户费用句，请检查模板")
        if p17.text.strip() != X.P17_ORIG:
            raise ValueError("模板过户费用句原文与预设不符，禁止改写，请检查模板")
        W.set_paragraph_text(p17, X.p17_text(form))

    W.renumber_headings(doc)


def _node_match(x: dict, p: dict) -> bool:
    """分期行与模板预设行是否同一节点：事件行须与预设原文一致；签约当日期行有日期即可。"""
    ev = (x.get("trigger") or "").strip()
    pe = (p.get("event") or "").strip()
    if pe:
        return ev == pe
    if ev and "签约" not in ev:
        return False
    return W.is_valid_iso_date(x.get("trigger_date")) or bool(ev)


def derive_payment(type_key: str, payment: dict, total: int = None) -> dict:
    """前端统一分期表 → 生成器所需的付款 dict。
    判定：与模板预设逐期一致 → default（保持模板条款，仅填金额）；
    单期 → one_time；其余 → custom（重写条款为一句总括）。

    total：可选，传入总售价/总费用时，对「尾款 = 总额 − 订金」做一致性校验（P2-10 纵深防御）。
    """
    cfg = get_type(type_key)
    preset = cfg.get("pay_preset") or []
    inst = []
    for i, x in enumerate(payment.get("installments") or []):
        raw = x.get("amount", 0)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise ValueError(f"第{i + 1}期金额为空，请填写后再生成")
        try:
            amt = clean_amount(raw, f"第{i + 1}期金额")
        except ValueError as ex:
            raise ValueError(str(ex))
        if amt <= 0:
            raise ValueError(f"第{i + 1}期金额必须大于 0")
        inst.append({
            "seq": len(inst) + 1,
            "amount": amt,
            "label": (x.get("label") or "").strip()[:6],
            "trigger": (x.get("event") or "").strip(),
            "trigger_date": (x.get("date") or "").strip() or None,
        })
    if not inst:
        raise ValueError("缺少付款计划（至少一期）")
    # P2-10 纵深防御：各期合计必须等于总额（覆盖 default/one_time/custom 全部模式）。
    # 否则尾款被引擎按「总额 − 订金」重算、或自定义分期写错时，合同金额会与用户输入不符且无人知晓。
    if total is not None:
        s = sum(x["amount"] for x in inst)
        if s != total:
            raise ValueError(
                f"分期合计（{s}）与总费用（{total}）不一致，请核对各期金额")
    for i, x in enumerate(inst):
        if not (W.is_valid_iso_date(x["trigger_date"]) or x["trigger"]):
            raise ValueError(f"第{i + 1}期缺少付款日期／事件条件")
    src = payment.get("source_text")

    if preset and len(inst) == len(preset) and all(_node_match(x, p) for x, p in zip(inst, preset)):
        legacy = {"mode": "default", "source_text": src}
        if cfg.get("car_default"):
            d1 = inst[0]["trigger_date"]
            if not W.is_valid_iso_date(d1):
                raise ValueError("卖车订金须填写付款日期（签约当日即选签署日期）")
            legacy.update(deposit_amount=inst[0]["amount"], deposit_date=d1)
            d2 = inst[1]["trigger_date"]
            if W.is_valid_iso_date(d2):
                legacy["balance_date"] = d2
            else:
                # 客户未给尾款日期：不造日期，保留事件改写条款
                legacy["balance_event"] = inst[1]["trigger"]
        else:
            legacy.update(pay1=inst[0]["amount"], pay2=inst[1]["amount"], pay3=inst[2]["amount"])
        return legacy
    if len(inst) == 1:
        return {"mode": "one_time", "pay_date": inst[0]["trigger_date"],
                "pay_event": inst[0]["trigger"], "source_text": src}
    return {"mode": "custom", "installments": inst, "source_text": src}


# ---------------- 三种付款模式 ----------------

def _rewrite_payment(doc, cfg, report, sec_no, next_no, texts):
    """改写条款区付款段（只动分期段，保留费用范围/逾期/收款账户等无关条款）。"""
    labels = [p["label"] for p in (cfg.get("pay_preset") or [])]
    total, a, b = W.rewrite_section(doc, sec_no, next_no, texts, labels or None)
    report["section_paras"] = total
    report["payment_rewrite"] = (a, b)


def _row_name(installments, i: int) -> str:
    """分期行名（与解析回填共用 writer.payment_row_name，所见即所得）。"""
    labels = [str(x.get("label") or "").strip() for x in installments]
    return W.payment_row_name(labels, i)


def _fill_amount_cell(row, cfg, cur, amount, total=None):
    style = cfg["fee_cell_style"]
    if style == "split":
        W.set_cell_text(row.cells[1], f"{currency_label(cur)}（大写）{to_cn_upper(amount)}")
        W.set_cell_text(row.cells[2], f"{currency_symbol(cur)}{with_commas(amount)}")
    else:  # single / single_rmb 统一替换单元格为完整金额短语
        W.set_cell_text(row.cells[1], amount_phrase(amount, cur))


def _default_mode(doc, cfg, fee_tbl, form, payment, cur, total, report, sign_cn):
    # 费用表：总金额行
    rows = fee_tbl.rows
    _fill_amount_cell(rows[0], cfg, cur, total)

    if cfg.get("car_default"):
        # 卖车默认两段：订金 / 订金日期 / 尾款（自动=总价-订金）
        deposit = clean_amount(payment.get("deposit_amount") or 0, "订金金额")
        if not 0 < deposit < total:
            raise ValueError(f"订金金额须大于 0 且小于总售价（当前订金 {deposit}，总价 {total}；"
                             f"一次性付清请用「一次性付款」模式）")
        balance = total - deposit
        _fill_amount_cell(rows[1], cfg, cur, deposit)
        W.set_cell_text(rows[2].cells[1], W.date_cn(payment["deposit_date"]))
        _fill_amount_cell(rows[3], cfg, cur, balance)
        report["fee_rows"] = [W.row_label(r) for r in rows]
        report["amounts"] = [total, deposit, balance]
        # 03 条：客户给了尾款日期 → 填空保留「日期或过户当日」；
        # 只有事件 → 整句改写为单事件句（绝不编造日期）
        start, end = W.section_range(doc, *cfg["payment_section"])
        p = doc.paragraphs[start]
        bd = payment.get("balance_date")
        if bd:
            y, m, d = W.iso_date_parts(bd)
            W.fill_blanks_in_paragraph(p, [y, m, d])
            if BLANK_LEFT(p):
                raise ValueError("卖车 03 条填空后仍有残留空位")
        else:
            ev = (payment.get("balance_event") or "").strip() or "车辆完成香港运输署过户登记手续当日"
            W.set_paragraph_text(p, f"购车尾款须于{ev}，由乙方一次性支付予甲方。")
        report["section_paras"] = end - start
    else:
        # 过户/新办默认三期（触发时点为模板固定文字，仅填金额）
        amounts = [clean_amount(payment.get(k) or 0, f"第{i + 1}期金额")
                   for i, k in enumerate(("pay1", "pay2", "pay3"))]
        for i, amt in enumerate(amounts):
            _fill_amount_cell(rows[i + 1], cfg, cur, amt)
        report["fee_rows"] = [W.row_label(r) for r in rows]
        report["amounts"] = [total] + amounts
        # 定金时点展开为绝对日期（生成日即签约日，与顶部签署日期同源）：
        # 新办「本协议签订后即日支付」/ 过户「于本合约签订当日支付」
        start, end = W.section_range(doc, *cfg["payment_section"])
        for p in doc.paragraphs[start:end]:
            for old, new in (
                ("本协议签订后即日支付", f"本协议签订当日（{sign_cn}）支付"),
                ("于本合约签订当日支付", f"于本合约签订当日（{sign_cn}）支付"),
            ):
                if old in p.text:
                    W.replace_in_paragraph(p, old, new)
                    break
        report["section_paras"] = None  # 条款文字不变（仅定金句内替换日期）


def BLANK_LEFT(p) -> bool:
    return bool(re.search(r"_{2,}", "".join(r.text for r in p.runs)))


def _ot_desc(payment) -> str:
    date = payment.get("pay_date") or ""
    event = (payment.get("pay_event") or "").strip()
    if date and event:
        return f"{W.date_cn(date)}或{event}"
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
    _rewrite_payment(doc, cfg, report, sec_no, next_no, [text])


def _custom_mode(doc, cfg, fee_tbl, payment, cur, total, report, sec_no, next_no):
    installments = payment.get("installments") or []
    if not installments:
        raise ValueError("自定义分期缺少期次数据")
    amounts = [clean_amount(x.get("amount") or 0, f"第{i + 1}期金额")
               for i, x in enumerate(installments)]
    if any(a <= 0 for a in amounts):
        raise ValueError("各期金额必须大于 0")
    if sum(amounts) != total:
        raise ValueError(f"各期合计 {sum(amounts)} ≠ 总费用 {total}，请先在界面修正")
    for i, ins in enumerate(installments):
        has_date = W.is_valid_iso_date((ins.get("trigger_date") or "").strip())
        has_cond = bool((ins.get("trigger") or "").strip())
        if not (has_date or has_cond):
            raise ValueError(f"第{i + 1}期缺少付款时间／节点／条件（既无日期也无触发条件），不能生成")
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
        W.set_cell_text(row.cells[0], _row_name(installments, i))
        _fill_amount_cell(row, cfg, cur, amounts[i])
    report["fee_rows"] = [W.row_label(r) for r in rows]
    report["amounts"] = [total] + amounts

    # 付款时间节点列：有绝对日期（LLM 基于签署日推算）或事件触发描述即进表，
    # 日期金额都在表里后，条款区无需逐期复述
    def _node(ins) -> str:
        iso = None
        td = (ins.get("trigger_date") or "").strip()
        if W.is_valid_iso_date(td):
            iso = td
        else:
            # trigger_date 缺失/非法时，从条件描述里捞「X年X月X日」
            m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", (ins.get("trigger") or "").strip())
            if m:
                cand = f"{int(m.group(1))}-{int(m.group(2))}-{int(m.group(3))}"
                if W.is_valid_iso_date(cand):
                    iso = cand
        if iso:
            return W.date_cn(iso)
        return (ins.get("trigger") or "").strip()

    nodes = [_node(ins) for ins in installments]
    if any(nodes):
        date_cells = W.append_column(fee_tbl, 2000)
        header = "付款日期 PAYMENT DATE" if cfg.get("car_default") else "付款日期"
        W.set_cell_text(date_cells[0], header)
        for cell, node in zip(date_cells[1:], nodes):
            W.set_cell_text(cell, node)
        report["date_column"] = True

    # 条款区改写：一句话总括（总价、期数、付款方），日期与各期金额以表为准
    payer, payee = cfg["payer"], cfg["payee"]
    total_label = cfg.get("fee_total_label", "总价款")
    if n == 1:
        how, by = "一次性支付", "足额"
    elif n == 2:
        how, by = "分两期支付", "按期足额"
    else:
        how, by = f"分{W.seq_cn(n)}期支付", "按期足额"
    scope = "付款日期及各期金额" if any(nodes) else "各期金额"
    texts = [
        f"{total_label}{amount_phrase(total, cur)}，{how}，"
        f"{scope}以上表所列为准，由{payer}{by}支付予{payee}。"
    ]
    _rewrite_payment(doc, cfg, report, sec_no, next_no, texts)
