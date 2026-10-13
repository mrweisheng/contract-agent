#!/usr/bin/env python3
"""收款结算单核算引擎：把 rules.md 的算术规则固化成代码。

输入：业务结构化 JSON（或按 input-format.md 书写的标准段落文本）
输出：可直接交给 settlement_engine.py 的 spec JSON + 校验警告

用法：
    python settlement_compute.py --input business.json [--out spec.json]
    python settlement_compute.py --text note.txt
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

CUR_ORDER = ("CNY", "HKD")
CUR_LABEL = {"CNY": "人民幣 CNY", "HKD": "港幣 HKD"}
CUR_SYMBOL = {"CNY": "¥", "HKD": "$"}
CUR_NAME = {"CNY": "人民幣", "HKD": "港幣"}

# 内容用字：输入什么就印什么，引擎不做繁简转换（2026-10-13 定，取代旧手写字表）。
# 纸面仍是繁体的只有代码里的固定标签（人民幣/港幣、結算類型、分位栏 十萬/萬）。

# ---------- 金额解析 ----------

CNY_HINTS = ("人民币", "人民幣", "rmb", "cny", "¥", "元人民")
HKD_HINTS = ("港币", "港幣", "港元", "hkd", "$", "元港")

# 「；人民币、港币等值金额：¥50000/$58999（已收）」这类双币等值后缀。
# 必须先切下来再判币种：整行含「人民币」字样（来自标签本身），
# 曾把 58999港币 的定金误判成 CNY，还污染了等值反推汇率。
EQUIV_MARK = re.compile(
    r"[；;]\s*(?:人民币|人民幣)\s*[、/，,]?\s*(?:港币|港幣)?\s*"
    r"等值(?:金额|金額)?\s*[：:]\s*"
)


def _number(raw: str) -> float:
    raw = raw.replace(",", "").replace("，", "").strip()
    mult = 10000 if ("万" in raw or "萬" in raw) else 1
    raw = raw.replace("万", "").replace("萬", "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        raise ValueError(f"无法解析金额：{raw}")
    return float(match.group()) * mult


def _equiv_amounts(seg: str) -> tuple:
    """等值段 → (cny_equiv, hkd_equiv)。认「¥50000/$58999」「¥50000，$58999」
    「50000人民币/58999港币」等写法；无标记裸数字歧义，不取。"""
    cny = hkd = None
    for token in re.split(r"[/／,，、;；]", seg):
        token = token.strip()
        if not token:
            continue
        low = token.lower()
        is_cny = any(h in low for h in ("¥", "￥", "人民币", "人民幣", "rmb", "cny"))
        is_hkd = any(h in low for h in ("$", "港币", "港幣", "港元", "hkd"))
        if is_cny and is_hkd:
            continue
        try:
            num = _number(token)
        except ValueError:
            continue
        if is_cny:
            cny = num
        elif is_hkd:
            hkd = num
    return cny, hkd


def parse_amount(text: str):
    """返回 (金额, 币种, 港币等值, 等值对 dict)。

    币种为 None 表示需从段落继承；等值对只含与主币种不同侧的等值
    （cny_equiv / hkd_equiv），斜杠双币写法与等值段写法都支持。
    """
    raw = str(text).strip()
    extra: dict = {}
    m = EQUIV_MARK.search(raw)
    if m:
        cny, hkd = _equiv_amounts(raw[m.end():])
        if cny is not None:
            extra["cny_equiv"] = cny
        if hkd is not None:
            extra["hkd_equiv"] = hkd
        raw = raw[:m.start()]
    low = raw.lower()
    currency = None
    if any(h in low for h in CNY_HINTS):
        currency = "CNY"
    elif any(h in low for h in HKD_HINTS):
        currency = "HKD"

    hkd_equiv = extra.pop("hkd_equiv", None)
    parts = re.split(r"[/／]|[,，](?=\s*\$|港)", raw)
    main = _number(parts[0])
    if len(parts) > 1 and hkd_equiv is None:
        try:
            hkd_equiv = _number(parts[1])
        except ValueError:
            hkd_equiv = None
    return main, currency, hkd_equiv, extra


# ---------- 标准段落文本解析 ----------

HEAD_FIELDS = {
    "群名": "group", "客户": "customer", "客戶": "customer",
    "结算类型": "settle_type", "結算類型": "settle_type", "结算類型": "settle_type",
    "申请口岸": "port", "申請口岸": "port", "口岸": "port",
    "日期": "date", "购买车辆": "vehicle", "購買車輛": "vehicle",
    "车辆": "vehicle", "車輛": "vehicle", "车牌": "plate", "車牌": "plate",
    # 业务类型仅存档（现牌结算单/港车买卖结算单…），核算与版式不区分
    "业务类型": "business", "業務類型": "business",
}
SECTION_MAP = {
    "合同内总费用": "contract_total", "合同內總費用": "contract_total",
    "合同内總費用": "contract_total", "合同內总费用": "contract_total",
    "合同总价": "contract_total", "合同總價": "contract_total",
    "合同内已收费用": "contract_paid", "合同內已收費用": "contract_paid",
    "合同内已收": "contract_paid", "合同內已收": "contract_paid",
    "合同内已收明细": "contract_paid", "合同內已收明細": "contract_paid",
    "合同内未收": "contract_unpaid", "合同內未收": "contract_unpaid",
    "合同内未收明细": "contract_unpaid", "合同內未收明細": "contract_unpaid",
    "合同外杂费明细": "extra_fees", "合同外雜費明細": "extra_fees",
    "合同外杂费": "extra_fees", "合同外雜費": "extra_fees",
    "合同外杂费实收": "extra_paid", "合同外雜費實收": "extra_paid",
    "合同外杂费实收明细": "extra_paid", "合同外雜費實收明細": "extra_paid",
    "合同外实收": "extra_paid", "合同外實收": "extra_paid",
    # 旧格式「合同外杂费已收：0」＝总数为 0 的段落头，后接明细行
    "合同外杂费已收": "extra_paid", "合同外雜費已收": "extra_paid",
}

# 行内标记：赠送＝金额照显示、不进任何合计（淇淇 2026-10-09 规则，2026-10-12 补文本解析）；
# 减免＝客户已付/抵扣，从杂费明细挪进「实收」段落（抵扣行，纸面红色负数）
GIFT_MARK = re.compile(r"[（(]\s*赠送\s*[)）]|[（(]\s*贈送\s*[)）]")
DEDUCT_MARK = re.compile(r"[（(]\s*减免\s*[)）]|[（(]\s*減免\s*[)）]")


def parse_text(text: str) -> dict:
    """把 input-format.md 的标准段落文本解析为业务结构化 JSON。"""
    data: dict = {
        "contract_total": [], "contract_paid": [], "contract_unpaid": [],
        "extra_fees": [], "extra_paid": [],
    }
    section = None
    inherited = None
    for line in text.splitlines():
        line = line.replace("\\", "").replace("\u00a0", " ").strip().rstrip("。.：:")
        if not line:
            continue
        head_key, head_val = None, None
        for key, field in HEAD_FIELDS.items():
            if line.startswith(key) and re.search(r"[：:]", line[: len(key) + 2]):
                head_key, head_val = field, line.split("：", 1)[-1].split(":", 1)[-1].strip()
                break
        if head_key:
            data[head_key] = head_val
            continue
        if line in SECTION_MAP:
            section = SECTION_MAP[line]
            inherited = None
            continue
        head = re.split(r"[：:]", line, 1)[0].strip()
        if head in SECTION_MAP:   # 「合同外杂费已收：0」＝段落头带总数，总数丢弃
            section = SECTION_MAP[head]
            inherited = None
            continue
        if section is None:
            continue
        if "：" not in line and ":" not in line:
            continue
        item, value = re.split(r"[：:]", line, 1)
        item = item.strip()
        try:
            amount, currency, hkd_equiv, extra = parse_amount(value)
        except ValueError:
            continue
        entry = {"item": item, "amount": amount}
        if currency:
            entry["currency"] = currency
            inherited = currency
        elif inherited:
            entry["currency"] = inherited
        # 等值只保留与主币种不同侧的数字：等值段里与原币相同的数字（如
        # 「180000人民币；…等值：¥180000/$212399」的 ¥180000）是冗余，不入库
        cur = entry.get("currency")
        if cur != "HKD" and hkd_equiv is not None:
            entry["hkd_equiv"] = hkd_equiv
        if cur != "CNY" and extra.get("cny_equiv") is not None:
            entry["cny_equiv"] = extra["cny_equiv"]
        # 赠送：金额照显示、不进合计（gift 标记由引擎的 _sum skip_gift 消费）
        if GIFT_MARK.search(item) or GIFT_MARK.search(value):
            entry["gift"] = True
        # 减免：客户已付/抵扣，挪进「实收」段落（纸面红色负数扣减行）
        target = section
        if DEDUCT_MARK.search(item) or DEDUCT_MARK.search(value):
            target = "extra_paid"
        data[target].append(entry)
    return data


# ---------- 核算 ----------


def floor_amount(value: float) -> float:
    """「您今日需付」展示金额：截尾到元，小数固定 .00（铁律，淇淇 2026-10-02 指定）。"""
    return math.floor(value + 1e-6)


def _sum(entries, currency, skip_gift: bool = False):
    total = 0.0
    for e in entries:
        if e.get("currency") != currency:
            continue
        # 赠送项照显示金额，但不进任何合计（淇淇 2026-10-09 指定）
        if skip_gift and e.get("gift"):
            continue
        total += float(e.get("amount", 0))
    return total


def normalize_currency(data: dict, warnings: list) -> dict:
    """总价币种自动纠偏：总价写错币种是最常见的人工录入错误。

    判据：总价金额与「已收+未收」在同一币种下对不上，但与另一币种的
    等值合计精确吻合时，按后者重标总价币种，并把警告写进输出。
    """
    total = data.get("contract_total") or []
    entries = list(data.get("contract_paid") or []) + list(data.get("contract_unpaid") or [])
    if len(total) != 1 or not entries:
        return data
    head = total[0]
    declared = head.get("currency", "HKD")
    amount = float(head.get("amount", 0))

    def native_sum(entries, cur):
        s = 0.0
        for e in entries:
            ecur = e.get("currency", "HKD")
            if ecur == cur:
                s += float(e.get("amount", 0))
            else:
                key = "hkd_equiv" if cur == "HKD" else "cny_equiv"
                if e.get(key):
                    s += float(e[key])
        return s

    if abs(amount - native_sum(entries, declared)) <= 1.0:
        return data  # 原口径自洽，不动

    other = "CNY" if declared == "HKD" else "HKD"
    if abs(amount - native_sum(entries, other)) <= 1.0:
        head["currency"] = other
        head["hkd_equiv" if other == "CNY" else "cny_equiv"] = native_sum(entries, declared)
        warnings.append(
            f"總價金額與「已收+未收」在{declared}下對不上，但與{other}等值合計吻合，"
            f"已自動按{CUR_NAME[other]} {amount:,.2f} 計價核算（如需改回請明確告知）。"
        )
    return data


def derive_rate_from_equiv(data: dict):
    """用户没给汇率、但给了某笔款项的双币等值时，反推 1 CNY = ? HKD。

    该比率仅是基准比率；按铁律，应收折算另乘 ×1.01（apply_101 默认 true），负净额按实汇率足额折。
    """
    ratios = []
    for key in ("contract_total", "contract_paid", "contract_unpaid", "extra_fees"):
        for e in data.get(key) or []:
            cur = e.get("currency", "HKD")
            try:
                amount = float(e.get("amount", 0))
            except (TypeError, ValueError):
                continue
            if not amount:
                continue
            if cur == "CNY" and e.get("hkd_equiv"):
                ratios.append(float(e["hkd_equiv"]) / amount)
            elif cur == "HKD" and e.get("cny_equiv"):
                ratios.append(amount / float(e["cny_equiv"]))
    if not ratios:
        return None
    return sum(ratios) / len(ratios)


SCOPE_RULES = (
    # 结算类型关键词 → 本次该收的款项名称关键词
    (("第二期",), ("第二期",)),
    (("尾款",), ("尾款",)),
)


def apply_settle_scope(data: dict, warnings: list) -> dict:
    """结算类型决定本次收款范围（rules.md「核算」第 65 条）。

    结算类型写「收第二期款」时，车牌尾款一类的未收款只是「应收」事实，
    不属于本次收款安排，必须按「下次收款」列示、不计入今日需付。
    只有当结算类型本身涵盖该款项（如「收尾款」「收第二期款及尾款」）时才计入。
    """
    settle_type = str(data.get("settle_type") or "")
    if not settle_type:
        return data
    scope = None
    for type_keys, item_keys in SCOPE_RULES:
        if any(k in settle_type for k in type_keys):
            scope = item_keys if scope is None else tuple(scope) + item_keys
    if not scope:
        return data

    demoted = []
    for e in data.get("contract_unpaid") or []:
        status = e.get("status", "today")
        if status in ("next", "paid"):
            continue
        name = str(e.get("item") or "")
        if any(k in name for k in scope):
            continue
        e["status"] = "next"
        demoted.append(name)
    if demoted:
        warnings.append(
            f"結算類型為「{settle_type}」，本次只收與此相關的款項；"
            f"{'、'.join(demoted)} 已按「下次收款」列示，不計入今日需付。"
            "如需本次一併收取，请明确告知。"
        )
    return data


def build_spec(data: dict) -> tuple:
    warnings: list[str] = []
    data = normalize_currency(data, warnings)
    data = apply_settle_scope(data, warnings)
    rate = dict(data.get("rate") or {})
    cny_to_hkd = rate.get("cny_to_hkd")
    hkd_to_cny = rate.get("hkd_to_cny")
    if not cny_to_hkd and not hkd_to_cny:
        derived = derive_rate_from_equiv(data)
        if derived:
            cny_to_hkd = derived
            hkd_to_cny = 1 / derived
            rate.setdefault("basis", "contract")
            rate.setdefault("apply_101", True)  # 铁律：应收折算 ×1.01；负净额（往外掏）足额折
            rate["derived_from_equiv"] = True
    if cny_to_hkd and hkd_to_cny and abs(cny_to_hkd * hkd_to_cny - 1) > 0.0005:
        warnings.append(
            f"双向汇率不互为倒数（1 CNY→{cny_to_hkd} HKD，1 HKD→{hkd_to_cny} CNY），"
            "已按 1 CNY 对 HKD 的基准汇率取倒数使用。"
        )
        hkd_to_cny = 1 / cny_to_hkd
    elif cny_to_hkd:
        hkd_to_cny = 1 / cny_to_hkd
    elif hkd_to_cny:
        cny_to_hkd = 1 / hkd_to_cny

    rows_by_cur: dict = {"CNY": [], "HKD": []}

    def push(currency, item, amount, status="normal", blank=False, block="extra"):
        row = {"item": item, "amount": float(amount), "status": status, "block": block}
        if blank:
            row["blank"] = True   # 模板稿行：渲染层金额与分位栏留白
        rows_by_cur.setdefault(currency, []).append(row)

    for e in data.get("contract_total", []):
        push(e.get("currency", "HKD"), e.get("item", ""), abs(float(e.get("amount", 0))),
             blank=bool(e.get("blank")), block="contract")
    for e in data.get("contract_paid", []):
        # 纸面已有「減：」前缀，项目名里的（已收）/（已付）标记剥掉免得重复
        item = str(e.get("item", "") or "")
        for mark in ("（已收）", "（已付）", "(已收)", "(已付)"):
            item = item.replace(mark, "")
        push(e.get("currency", "HKD"), item,
             -abs(float(e.get("amount", 0))), "paid", blank=bool(e.get("blank")), block="contract")

    due = {"CNY": 0.0, "HKD": 0.0}
    unpaid_face = {"CNY": 0.0, "HKD": 0.0}
    # 计入今日的未收款：原币合计，以及另一个币种下的等值（用户明确给出等值时优先采用）
    unpaid_native = {"CNY": 0.0, "HKD": 0.0}
    unpaid_equiv = {"CNY": 0.0, "HKD": 0.0}
    apply_101 = rate.get("apply_101", True)
    factor = 1.01 if apply_101 else 1.0
    has_unpaid = bool(data.get("contract_unpaid"))
    for e in data.get("contract_unpaid", []):
        currency = e.get("currency", "CNY")
        amount = float(e.get("amount", 0))
        unpaid_face[currency] += amount
        status = e.get("status", "today")
        # 下次收款属于收款安排，不是本次应收；已收是事实扣减，都不计入今日需付
        counts_today = status not in ("next", "paid")
        mark = {"today": "today", "next": "next", "paid": "paid"}.get(status, "today")
        # rules.md 71/72/73：同一笔款项只在原币种明细里列示一次；
        # 跨币种等值只进备注和「您今日需付」的另一个口径，不另开明细行。
        push(currency, e.get("item", ""), amount, mark, blank=bool(e.get("blank")), block="contract")
        if not counts_today:
            continue
        due[currency] += amount
        unpaid_native[currency] += amount
        # rules.md 124：用户已直接给出最终等值金额时以该金额为准，不重复折算
        if currency == "CNY":
            if e.get("hkd_equiv"):
                unpaid_equiv["HKD"] += float(e["hkd_equiv"])
            else:
                # 同一原则：应收（正数）折算加手续费，负数异常数据足额折
                unpaid_equiv["HKD"] += amount * (cny_to_hkd or 0.0) * (factor if amount > 0 else 1.0)
        elif e.get("cny_equiv"):
            unpaid_equiv["CNY"] += float(e["cny_equiv"])
        else:
            unpaid_equiv["CNY"] += amount * (hkd_to_cny or 0.0) * (factor if amount > 0 else 1.0)

    for e in data.get("extra_fees", []):
        # 赠送项：明细行照原价列示，但不计入合同外应收合计。
        # 纸面已有绿字+〔贈送〕标签（render 按 status 画），项目名里的标记后缀剥掉免得重复。
        item = str(e.get("item", "") or "")
        for mark in ("（赠送）", "（贈送）", "(赠送)", "(贈送)", "（不计入应收）", "（不計入應收）"):
            item = item.replace(mark, "")
        push(e.get("currency", "HKD"), item, abs(float(e.get("amount", 0))),
             "gift" if e.get("gift") else "normal", blank=bool(e.get("blank")), block="extra")
    for e in data.get("extra_paid", []):
        item = str(e.get("item", "") or "")
        for mark in ("（减免）", "（減免）", "(减免)", "(減免)", "（已收）", "（已付）"):
            item = item.replace(mark, "")
        push(e.get("currency", "HKD"), item,
             -abs(float(e.get("amount", 0))), "paid", blank=bool(e.get("blank")), block="extra")
    # 铁律（淇淇 2026-10-10 严厉纠正）：【严禁】把不同币种的钱直接相加减。
    # 客户垫付港币现金要抵扣人民币尾款，必须先把港币按汇率折成人民币再减。
    # 曾经的 face_offset「面值直减」开关会算出「¥178,000 − $5,000 = ¥173,000」这种
    # 荒唐结果（凭空少收 736 元），已**永久禁用**；遇到旧数据带这个标记一律忽略并报警。
    face_hkd = 0.0
    face_cny = 0.0
    if any(e.get("face_offset") for e in (data.get("extra_paid") or [])):
        warnings.append(
            "已忽略 face_offset（面值直减）：跨币种抵扣必须先把港币按汇率折成人民币再减，"
            "直接拿人民币减港币属严重错误，本单已按汇率折算处理。"
        )
    face_mode = False

    for currency in CUR_ORDER:
        # 赠送项只上纸面、不进合计
        extra_balance = (_sum(data.get("extra_fees", []), currency, skip_gift=True)
                         - _sum(data.get("extra_paid", []), currency))
        if not has_unpaid:
            contract_balance = _sum(data.get("contract_total", []), currency) - _sum(
                data.get("contract_paid", []), currency)
            due[currency] += contract_balance
        due[currency] += extra_balance
        # 面值抵扣是淇淇指定的正常做法，不算异常，不再报警
        if extra_balance < -0.01 and not face_mode:
            warnings.append(
                f"{CUR_NAME[currency]}合同外杂费应收 "
                f"{_sum(data.get('extra_fees', []), currency, skip_gift=True):,.2f}，"
                f"客户已付 {_sum(data.get('extra_paid', []), currency):,.2f}，"
                f"差额 {extra_balance:,.2f} 已作抵扣（客户垫付／预付现金），请核对。"
            )
        if has_unpaid:
            total = _sum(data.get("contract_total", []), currency)
            paid = _sum(data.get("contract_paid", []), currency)
            if total and paid and abs(total - paid - unpaid_face[currency]) > 0.01:
                warnings.append(
                    f"{CUR_NAME[currency]}尾款对账不一致：合同总价减已收 = "
                    f"{total - paid:,.2f}，但合同内未收合计 = {unpaid_face[currency]:,.2f}。"
                )

    currencies = [c for c in CUR_ORDER if rows_by_cur.get(c)]
    if not currencies:
        raise ValueError("没有任何带币种的明细，无法核算。")
    due_currencies = [c for c in currencies if abs(due.get(c, 0.0)) > 0.005] or currencies

    sections = [{"currency": c, "label": CUR_LABEL[c], "rows": rows_by_cur[c]} for c in currencies]

    # 今日需付：rules.md 67-69，涉及多币种时汇总区并列两个付款口径
    today_pay = {}
    selfcheck = {}
    if len(currencies) == 1:
        c = currencies[0]
        today_pay = {("cny" if c == "CNY" else "hkd"):
                     f"{CUR_SYMBOL[c]} {floor_amount(due[c]):,.2f}"}
    else:
        if not cny_to_hkd:
            warnings.append(
                "缺少汇率：本单涉及双币种，但未提供合同签订日或合同汇率。"
                "按规则不得默认使用操作日实时汇率，请先向用户索取。"
            )
            cny_to_hkd = 0.0
            hkd_to_cny = 0.0
        # rules.md 67-69：并列两个付款口径
        # 汇总顺序（2026-10-13 用户定稿）：同币种先各自加减出净额（赠送完全不参与），
        # 再只对净额做跨币种折算。折算手续费（静默，单据不出现字样）只加在「要收的钱」上：
        # 被折净额为正 ×1.01；净额为负（减免/多付，往外掏）按实际汇率足额折算，不收手续费。
        other_cny = due.get("CNY", 0.0) - unpaid_native["CNY"]
        other_hkd = due.get("HKD", 0.0) - unpaid_native["HKD"]
        cny_fold_factor = factor if other_hkd + face_hkd > 0 else 1.0
        cny_total = (other_cny + (other_hkd + face_hkd) * hkd_to_cny * cny_fold_factor - face_hkd
                     + unpaid_native["CNY"] + unpaid_equiv["CNY"])
        # 铁律（淇淇 2026-10-10 澄清）：汇率【分部分】套用，不能一刀切——
        #   ① 合同内款项（总价 / 定金 / 二期款 / 尾款）＝合同签订日的折算金额：
        #      用户已经给了双币等值，就是合同白纸黑字写明的，原样取用，
        #      严禁再按制作当日汇率重新折算（许兰坛教训：¥178,000 的合同等值
        #      是 $210,044，重折会算成 $208,7xx，跟合同对不上）。
        #   ② 合同外杂费 / 政府收费＝制作当天的百度实时汇率折算 × 1.01。
        #   ③ 既无合同也无等值、只有总金额时，全部按当天汇率算。
        # 因此人民币、港币两个口径不再强行互相验算（合同等值本就是签订日汇率），
        # 但自检必须把「合同内 / 合同外」两部分金额摊开打印，方便人眼核对。
        contract_hkd = unpaid_native["HKD"] + unpaid_equiv["HKD"]
        hkd_fold_factor = factor if other_cny - face_cny > 0 else 1.0
        extra_hkd = other_hkd + (other_cny - face_cny) * cny_to_hkd * hkd_fold_factor - face_cny
        hkd_total = contract_hkd + extra_hkd
        cny_shown = floor_amount(cny_total)
        today_pay = {
            "cny": f"¥ {cny_shown:,.2f}",
            "hkd": f"$ {floor_amount(hkd_total):,.2f}",
        }
        # 参考值：若整单都按当天汇率折算会是多少，只做提示不做断言。
        # 走面值抵扣时两口径本来就是各自直减，互验没有意义，不再提示。
        ref_hkd = cny_shown * cny_to_hkd * factor
        drift = 0.0 if face_mode else abs(floor_amount(hkd_total) - floor_amount(ref_hkd))
        selfcheck = {
            "cny_used": cny_shown,
            "cny_exact": round(cny_total, 2),
            "hkd_used": floor_amount(hkd_total),
            "hkd_exact": round(hkd_total, 2),
            "cny_to_hkd": cny_to_hkd,
            "factor": factor,
            "contract_part_hkd": round(contract_hkd, 2),
            "extra_part_hkd": round(extra_hkd, 2),
            "ref_all_today_hkd": floor_amount(ref_hkd),
            "expr": (f"合同内 ${contract_hkd:,.2f}（合同等值，不重折）"
                     f" ＋ 合同外 ${extra_hkd:,.2f}（当日汇率 {cny_to_hkd}）"
                     f" = ${hkd_total:,.2f}"),
            "ok": drift <= 1.0,
            "face_mode": face_mode,
            "verdict": ("客户垫付现金按面值直减，两个口径各自抵扣 ✓" if face_mode
                        else ("合同内已按合同等值取用 ✓" if drift > 1.0
                              else "合同内与当日汇率两口径一致 ✓")),
        }
        # 「合同内等值 vs 整单按当日重折」差异不进 warnings（用户 2026-10-12 确认删除）：
        # 该差异是"等值为准、不重折"铁律的必然结果，对错误零检出能力；
        # 分解式仍在 selfcheck.expr，供图下方小字核对。

    # 备注
    # 铁律（淇淇 2026-10-09 强调）：明细最后一行＝本次应收的合同内款项（不是含杂费的今日需付），
    # 必须在备注里给出这一笔的人民币／港币等值换算金额，两个货币符号之间用 "/" 分隔。
    today_entries = [
        e for e in (data.get("contract_unpaid") or [])
        if str(e.get("status", "today")) not in ("next", "paid")
        and abs(float(e.get("amount", 0) or 0)) > 0.005
    ]
    bits: list = []
    for e in today_entries:
        amount = abs(float(e.get("amount", 0) or 0))
        if e.get("currency", "CNY") == "CNY":
            if e.get("hkd_equiv"):
                other_v = float(e["hkd_equiv"])
            elif cny_to_hkd:
                other_v = amount * cny_to_hkd * factor
            else:
                continue
            pair = f"¥{amount:,.2f} / ${other_v:,.2f}"
        else:
            if e.get("cny_equiv"):
                other_v = float(e["cny_equiv"])
            elif hkd_to_cny:
                other_v = amount * hkd_to_cny * factor
            else:
                continue
            pair = f"${amount:,.2f} / ¥{other_v:,.2f}"
        bits.append(f"{e.get('item', '') or '本次應收款項'}為 {pair}。")

    note = data.get("note")
    if note is None:
        # 括号注（日期+来源）拼出来是空的就不画括号，避免纸面出现「（）」
        def _rate_tail() -> str:
            if rate.get("basis") == "contract":
                meta = "合同簽訂日"
            else:
                meta = f"{rate.get('date') or ''}{rate.get('source') or ''}"
            body = f"匯率 1 CNY = {cny_to_hkd} HKD"
            return body + (f"（{meta}）。" if meta else "。")
        if bits:
            if rate.get("basis") == "contract":
                tail = "匯率核算以合同簽訂日為標準。"
            else:
                tail = _rate_tail()
            note = "".join(bits) + tail
        elif len(due_currencies) > 1 and cny_to_hkd:
            # 内部仍按 ×1.01 计算，但单据备注不得出现该字样（淇淇 2026-10-02 指定）
            note = _rate_tail()
        else:
            note = None

    amount_note = data.get("amount_note")
    if amount_note is None:
        # 有赠送行时备注里点明性质（纸面绿字+〔贈送〕标，客户一眼分清收不收钱）
        has_gift = any(e.get("gift") for e in data.get("extra_fees") or [])
        gift_clause = "贈送項目由本公司承擔，僅列示價值、不計入應收；" if has_gift else ""
        if bits:
            amount_note = (f"{gift_clause}負數表示已付款或扣減。人民幣與港幣分開核算，"
                           "港幣等值僅作匯算參考，明細行只列示一次。")
        elif len(currencies) == 1:
            amount_note = (f"{gift_clause}本單全部款項均為{CUR_NAME[currencies[0]]}，"
                           "無需進行跨幣種換算。")
        else:
            amount_note = f"{gift_clause}負數表示已付款或扣減。人民幣與港幣分開核算，港幣總額已按上述匯率折算。"

    # 基本资料
    group = data.get("group", "")
    customer = data.get("customer", "") or group
    second_label = "購買車輛" if data.get("vehicle") else "申請口岸"
    second_value = data.get("vehicle") or data.get("port") or ""
    meta = [
        ["客戶名稱", customer, "群名", group],
        [second_label, second_value, "結算類型", data.get("settle_type", "")],
    ]

    filename = data.get("filename")
    if not filename:
        date_digits = re.sub(r"[^0-9]", "", data.get("date_iso") or "")
        if not date_digits:
            m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
                          data.get("date", ""))
            date_digits = (f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
                           if m else re.sub(r"[^0-9]", "", data.get("date", "")))
        suffix = f"_{date_digits}" if date_digits else ""
        filename = (f"{data.get('customer') or group}_"
                    f"{data.get('settle_type', '结算')}结算单{suffix}")

    spec = {
        "filename": filename + ("" if filename.lower().endswith(".pdf") else ".pdf"),
        "title": data.get("title", "收款結算單"),
        "subtitle": data.get("subtitle", "SETTLEMENT STATEMENT"),
        "date": data.get("date", ""),
        "meta": meta,
        "sections": sections,
        "note": note,
        "today_pay": today_pay,
        "amount_note": amount_note,
    }
    if data.get("overrides"):
        spec["overrides"] = data["overrides"]
    if data.get("today_sep") is not None:
        spec["today_sep"] = str(data["today_sep"])
    else:
        # 铁律：并列两个付款口径时，两个金额之间必须用 "/" 分隔
        spec["today_sep"] = "/" if ("cny" in today_pay and "hkd" in today_pay) else ""

    detail = {
        "currencies": currencies,
        "due_by_currency": {c: round(due.get(c, 0.0), 2) for c in currencies},
        "today_pay": today_pay,
        "selfcheck": selfcheck,
        "rate": {"cny_to_hkd": cny_to_hkd, "hkd_to_cny": hkd_to_cny,
                 "date": rate.get("date"), "source": rate.get("source"),
                 "basis": rate.get("basis")},
        "warnings": warnings,
    }
    return spec, detail


def main() -> int:
    parser = argparse.ArgumentParser(description="收款结算单核算引擎")
    parser.add_argument("--input", help="业务结构化 JSON")
    parser.add_argument("--text", help="按标准段落书写的业务文本")
    parser.add_argument("--out", help="spec JSON 输出路径，默认 stdout")
    args = parser.parse_args()

    if args.text:
        data = parse_text(Path(args.text).read_text(encoding="utf-8"))
    elif args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        data = json.loads(sys.stdin.read())

    spec, detail = build_spec(data)
    payload = {"spec": spec, "detail": detail}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if any("缺少汇率" in w or "对账不一致" in w for w in detail["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
