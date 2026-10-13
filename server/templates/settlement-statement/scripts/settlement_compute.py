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

PHRASES = {
    "车牌": "車牌", "车辆": "車輛", "买卖": "買賣", "总价": "總價", "车价": "車價",
    "过户": "過戶", "保险": "保險", "牌费": "牌費", "验车": "驗車", "运输": "運輸",
    "维修": "維修", "代办": "代辦", "手续费": "手續費", "换车": "換車", "境内": "境內",
    "购买": "購買", "杂费": "雜費", "物流": "物流", "仓储": "倉儲", "费用": "費用",
    "批文卡": "批文卡", "禁区纸": "禁區紙", "核证本": "核證本", "结算": "結算",
    "类型": "類型", "申请": "申請", "备注": "備註", "说明": "說明", "金额": "金額",
    "余额": "餘額", "优惠": "優惠", "退款": "退款", "签订": "簽訂", "标准": "標準",
    "今日应收": "今日應收", "下次收款": "下次收款", "已收": "已收", "未收": "未收",
    "应付": "應付", "垫付": "墊付", "实收": "實收", "项目": "項目", "其他": "其他",
    "旧车": "舊車", "通车": "通車", "日期": "日期", "客户": "客戶", "资料": "資料",
    "账户": "帳戶", "简体": "簡體", "号码": "號碼", "电话": "電話", "银行": "銀行",
    "莲塘": "蓮塘", "深圳湾": "深圳灣", "落马洲": "落馬洲", "文锦渡": "文錦渡",
    "沙头角": "沙頭角", "港珠澳": "港珠澳", "皇岗": "皇崗", "福田": "福田",
}
CHARS = {
    "车": "車", "辆": "輛", "费": "費", "险": "險", "验": "驗", "证": "證", "总": "總",
    "价": "價", "币": "幣", "办": "辦", "现": "現", "莲": "蓮", "杂": "雜", "仓": "倉",
    "储": "儲", "运": "運", "输": "輸", "维": "維", "修": "修", "务": "務", "续": "續",
    "补": "補", "减": "減", "旧": "舊", "垫": "墊", "汇": "匯", "签": "簽", "标": "標",
    "准": "準", "应": "應", "额": "額", "项": "項", "余": "餘", "优": "優", "惠": "惠",
    "区": "區", "纸": "紙", "湾": "灣", "锦": "錦", "岗": "崗", "号": "號", "话": "話",
    "银": "銀", "帐": "帳", "户": "戶", "体": "體", "资": "資", "买卖": "買賣",
    "关": "關", "单": "單", "据": "據", "发": "發", "票": "票", "经": "經", "纪": "紀",
    "约": "約", "档": "檔", "检": "檢", "测": "測", "养": "養", "护": "護", "税": "稅",
    "务": "務", "临": "臨", "时": "時", "费": "費", "计": "計", "划": "劃", "转": "轉",
    "数": "數", "码": "碼", "别": "別", "识": "識", "内": "內", "广": "廣", "东": "東",
    "门": "門", "县": "縣", "丰": "豐", "华": "華", "侨": "僑", "开": "開", "网": "網",
    "点": "點", "址": "址",
    # 常见姓名用字
    "温": "溫", "汉": "漢", "伟": "偉", "强": "強", "军": "軍", "涛": "濤", "静": "靜",
    "丽": "麗", "鹏": "鵬", "杰": "傑", "艳": "艷", "辉": "輝", "刚": "剛", "荣": "榮",
    "龙": "龍", "凤": "鳳", "兰": "蘭", "国": "國", "义": "義", "礼": "禮", "寿": "壽",
    "宁": "寧", "进": "進", "远": "遠", "达": "達", "顺": "順", "财": "財", "贵": "貴",
    "兴": "興", "隆": "隆", "瑞": "瑞", "祥": "祥", "豪": "豪", "俊": "俊", "雄": "雄",
    "健": "健", "学": "學", "兵": "兵", "毅": "毅", "峰": "峰", "树": "樹", "铜": "銅",
    "铁": "鐵", "钦": "欽", "铭": "銘", "锦": "錦", "镇": "鎮", "钊": "釗", "铨": "銓",
    "培": "培", "坤": "坤", "城": "城", "基": "基", "业": "業", "庆": "慶",
    "传": "傳", "伦": "倫", "仪": "儀", "娇": "嬌", "娴": "嫻",
    "嫦": "嫦", "嫒": "嬡", "贻": "貽", "赞": "讚",
}


def to_traditional(value: str) -> str:
    """业务字段转香港繁体。群名与大陆账户不走此函数。"""
    if not value:
        return value
    result = value
    for src, dst in PHRASES.items():
        result = result.replace(src, dst)
    return "".join(CHARS.get(ch, ch) for ch in result)


# ---------- 金额解析 ----------

CNY_HINTS = ("人民币", "人民幣", "rmb", "cny", "¥", "元人民")
HKD_HINTS = ("港币", "港幣", "港元", "hkd", "$", "元港")


def _number(raw: str) -> float:
    raw = raw.replace(",", "").replace("，", "").strip()
    mult = 10000 if ("万" in raw or "萬" in raw) else 1
    raw = raw.replace("万", "").replace("萬", "")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        raise ValueError(f"无法解析金额：{raw}")
    return float(match.group()) * mult


def parse_amount(text: str):
    """返回 (金额, 币种, 港币等值)。币种为 None 表示需从段落继承。"""
    raw = str(text).strip()
    low = raw.lower()
    currency = None
    if any(h in low for h in CNY_HINTS):
        currency = "CNY"
    elif any(h in low for h in HKD_HINTS):
        currency = "HKD"

    hkd_equiv = None
    parts = re.split(r"[/／]|[,，](?=\s*\$|港)", raw)
    main = _number(parts[0])
    if len(parts) > 1:
        try:
            hkd_equiv = _number(parts[1])
        except ValueError:
            hkd_equiv = None
    return main, currency, hkd_equiv


# ---------- 标准段落文本解析 ----------

HEAD_FIELDS = {
    "群名": "group", "客户": "customer", "客戶": "customer",
    "结算类型": "settle_type", "結算類型": "settle_type", "结算類型": "settle_type",
    "申请口岸": "port", "申請口岸": "port", "口岸": "port",
    "日期": "date", "购买车辆": "vehicle", "購買車輛": "vehicle",
    "车辆": "vehicle", "車輛": "vehicle", "车牌": "plate", "車牌": "plate",
}
SECTION_MAP = {
    "合同内总费用": "contract_total", "合同內總費用": "contract_total",
    "合同内總費用": "contract_total", "合同內总费用": "contract_total",
    "合同总价": "contract_total", "合同總價": "contract_total",
    "合同内已收费用": "contract_paid", "合同內已收費用": "contract_paid",
    "合同内已收": "contract_paid", "合同內已收": "contract_paid",
    "合同内未收": "contract_unpaid", "合同內未收": "contract_unpaid",
    "合同外杂费明细": "extra_fees", "合同外雜費明細": "extra_fees",
    "合同外杂费": "extra_fees", "合同外雜費": "extra_fees",
    "合同外杂费实收": "extra_paid", "合同外雜費實收": "extra_paid",
    "合同外实收": "extra_paid", "合同外實收": "extra_paid",
}


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
        if section is None:
            continue
        if "：" not in line and ":" not in line:
            continue
        item, value = re.split(r"[：:]", line, 1)
        item = item.strip()
        try:
            amount, currency, hkd_equiv = parse_amount(value)
        except ValueError:
            continue
        entry = {"item": item, "amount": amount}
        if currency:
            entry["currency"] = currency
            inherited = currency
        elif inherited:
            entry["currency"] = inherited
        if hkd_equiv is not None:
            entry["hkd_equiv"] = hkd_equiv
        data[section].append(entry)
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

    该比率仅是基准比率；按铁律，人民币折港币时仍须另乘 ×1.01（apply_101 默认 true）。
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
            rate.setdefault("apply_101", True)  # 铁律：人民币折港币一律 ×1.01
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

    def push(currency, item, amount, status="normal"):
        rows_by_cur.setdefault(currency, []).append(
            {"item": to_traditional(item), "amount": float(amount), "status": status})

    for e in data.get("contract_total", []):
        push(e.get("currency", "HKD"), e.get("item", ""), abs(float(e.get("amount", 0))))
    for e in data.get("contract_paid", []):
        push(e.get("currency", "HKD"), e.get("item", ""),
             -abs(float(e.get("amount", 0))), "paid")

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
        push(currency, e.get("item", ""), amount, mark)
        if not counts_today:
            continue
        due[currency] += amount
        unpaid_native[currency] += amount
        # rules.md 124：用户已直接给出最终等值金额时以该金额为准，不重复折算
        if currency == "CNY":
            if e.get("hkd_equiv"):
                unpaid_equiv["HKD"] += float(e["hkd_equiv"])
            else:
                unpaid_equiv["HKD"] += amount * (cny_to_hkd or 0.0) * factor
        elif e.get("cny_equiv"):
            unpaid_equiv["CNY"] += float(e["cny_equiv"])
        else:
            unpaid_equiv["CNY"] += amount * (hkd_to_cny or 0.0)

    for e in data.get("extra_fees", []):
        # 赠送项：明细行照原价列示，但不计入合同外应收合计
        push(e.get("currency", "HKD"), e.get("item", ""), abs(float(e.get("amount", 0))),
             "gift" if e.get("gift") else "normal")
    for e in data.get("extra_paid", []):
        push(e.get("currency", "HKD"), e.get("item", ""),
             -abs(float(e.get("amount", 0))), "paid")
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
        other_cny = due.get("CNY", 0.0) - unpaid_native["CNY"]
        other_hkd = due.get("HKD", 0.0) - unpaid_native["HKD"]
        cny_total = (other_cny + (other_hkd + face_hkd) * hkd_to_cny - face_hkd
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
        extra_hkd = other_hkd + (other_cny - face_cny) * cny_to_hkd * factor - face_cny
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
        if drift > 1.0:
            warnings.append(
                f"港币口径 ${floor_amount(hkd_total):,.2f} ＝ 合同内等值 ${contract_hkd:,.2f}"
                f" ＋ 合同外当日折算 ${extra_hkd:,.2f}；若整单按当日汇率重折为"
                f" ${floor_amount(ref_hkd):,.2f}，相差 {drift:,.2f}。"
                "差异来自合同签订日的折算金额（合同内款项不重折），属正常，请复核。" 
            )

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
                other_v = amount * hkd_to_cny
            else:
                continue
            pair = f"${amount:,.2f} / ¥{other_v:,.2f}"
        bits.append(f"{to_traditional(e.get('item', '') or '本次應收款項')}為 {pair}。")

    note = data.get("note")
    if note is None:
        if bits:
            if rate.get("basis") == "contract":
                tail = "匯率核算以合同簽訂日為標準。"
            else:
                tail = (f"匯率 1 CNY = {cny_to_hkd} HKD"
                        f"（{rate.get('date') or ''}{rate.get('source', '')}）。")
            note = "".join(bits) + tail
        elif len(due_currencies) > 1 and cny_to_hkd:
            basis = "合同簽訂日" if rate.get("basis") == "contract" else rate.get("date", "")
            # 内部仍按 ×1.01 计算，但单据备注不得出现该字样（淇淇 2026-10-02 指定）
            note = (f"匯率 1 CNY = {cny_to_hkd} HKD"
                    f"（{basis}{rate.get('source', '')}）。")
        else:
            note = None

    amount_note = data.get("amount_note")
    if amount_note is None:
        if bits:
            amount_note = ("負數表示已付款或扣減。人民幣與港幣分開核算，"
                           "港幣等值僅作匯算參考，明細行只列示一次。")
        elif len(currencies) == 1:
            amount_note = (f"本單全部款項均為{CUR_NAME[currencies[0]]}，"
                           "無需進行跨幣種換算。")
        else:
            amount_note = "負數表示已付款或扣減。人民幣與港幣分開核算，港幣總額已按上述匯率折算。"

    # 基本资料
    group = data.get("group", "")
    customer = to_traditional(data.get("customer", "")) or group
    second_label = "購買車輛" if data.get("vehicle") else "申請口岸"
    second_value = data.get("vehicle") or data.get("port") or ""
    meta = [
        ["客戶名稱", customer, "群名", group],
        [second_label, to_traditional(second_value), "結算類型",
         to_traditional(data.get("settle_type", ""))],
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
