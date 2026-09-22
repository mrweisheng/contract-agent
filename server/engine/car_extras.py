# -*- coding: utf-8 -*-
"""卖车合同可选内容（附赠项 / 发动机质保）的文字推导。
builder 落盘与 checker 校验共用此模块，保证表单所见即合同所得。
原则：客户信息没提到就完全不出现（默认全关）；提到才落盘。
"""
import re

from engine.writer import seq_cn

DEFAULT_MONTHS_PHRASE = "六（6）个月"
DEFAULT_KM_PHRASE = "行驶30,000公里"

# 模板 06 条第二段原文（改写前必须与模板逐字一致，否则拒绝落盘）
P17_ORIG = ("车辆过户手续由甲方负责办理，相关政府费用及代办费用由乙方承担。"
            "车辆现有保险不随车转移，乙方须自行购买有效汽车保险。")

WARRANTY_TMPL = ("甲方就本车辆发动机提供售后质保：质保期为自车辆交付之日起{a}或{b}（以先到者为准）。"
                 "质保期内发动机故障由甲方负责免费维修，不构成退车、退款的理由。"
                 "因碰撞、涉水、意外事故、保养不当、私自改装或未经甲方书面同意的第三方拆修所致的故障或损坏，"
                 "以及正常损耗件（皮带、软管、密封件、火花塞、滤清器、机油及各类油液）的更换，不属于质保范围。")


def _on(v) -> bool:
    return str(v or "").strip() in ("赠送", "含", "是", "true", "True", "1", "1.0")


def gift_transfer_on(form: dict) -> bool:
    return _on(form.get("gift_transfer"))


def gift_plate(form: dict):
    """附赠香港牌费期限：'4个月' / '12个月' / None（不赠）。"""
    v = str(form.get("gift_plate") or "").strip()
    return v if v in ("4个月", "12个月") else None


def gift_insurance(form: dict) -> str:
    """附赠车险：险种描述原文，非空即赠送。"""
    return str(form.get("gift_insurance") or "").strip()


def warranty_on(form: dict) -> bool:
    return _on(form.get("warranty_enabled"))


def _period_cn(s) -> str:
    """'1年'/'12个月'/'半年' → '一（1）年'/'十二（12）个月'/'六（6）个月'。空→''；无法识别→ValueError。"""
    s = str(s or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d+)\s*个?月", s)
    if m:
        n = int(m.group(1))
        return f"{seq_cn(n)}（{n}）个月"
    m = re.fullmatch(r"(\d+)\s*年", s)
    if m:
        n = int(m.group(1))
        return f"{seq_cn(n)}（{n}）年"
    if s in ("半年", "一年", "两年"):
        n = {"半年": 6, "一年": 1, "两年": 2}[s]
        return f"六（6）个月" if s == "半年" else f"{seq_cn(n)}（{n}）年"
    raise ValueError(f"质保时长「{s}」无法识别，请填「1年」「6个月」这类格式，或留空用默认半年")


def _km_phrase(s) -> str:
    """'30000'/'30000公里'/'3万公里' → '行驶30,000公里'。空→''；无法识别→ValueError。"""
    s = str(s or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d+(?:,\d{3})*)\s*(?:公里|km|KM)?", s)
    if m:
        n = int(m.group(1).replace(",", ""))
        return f"行驶{n:,}公里"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*万(?:公里)?", s)
    if m:
        n = int(round(float(m.group(1)) * 10000))
        return f"行驶{n:,}公里"
    raise ValueError(f"质保公里数「{s}」无法识别，请填纯数字（如 30000），或留空用默认3万公里")


def warranty_parts(form: dict):
    """质保期限两段短语（时间, 公里），用户给的条件在前、默认值补后。
    未开启质保返回 None。"""
    if not warranty_on(form):
        return None
    p = _period_cn(form.get("warranty_period"))
    k = _km_phrase(form.get("warranty_km"))
    if p and k:
        return p, k
    if p:
        return p, DEFAULT_KM_PHRASE
    if k:
        return k, DEFAULT_MONTHS_PHRASE
    return DEFAULT_MONTHS_PHRASE, DEFAULT_KM_PHRASE


def warranty_paragraph(form: dict):
    """04 条末尾追加的质保段全文；未开启返回 None。"""
    parts = warranty_parts(form)
    if not parts:
        return None
    return WARRANTY_TMPL.format(a=parts[0], b=parts[1])


def gift_lines(form: dict) -> list:
    """06 条末尾追加的附赠行（只记录赠了什么，不加描述）。"""
    lines = []
    if gift_transfer_on(form):
        lines.append("附赠：本车辆过户登记手续的全部费用。")
    plate = gift_plate(form)
    if plate:
        cn = "四（4）个月" if plate == "4个月" else "十二（12）个月"
        lines.append(f"附赠：本车辆香港车辆牌照费{cn}。")
    ins = gift_insurance(form)
    if ins:
        lines.append(f"附赠：本车辆汽车保险（{ins}）。")
    return lines


def p17_text(form: dict) -> str:
    """06 条第二段按赠项改写后的全文（赠过户费/车险时与原文冲突，须最小改写）。"""
    s = P17_ORIG
    if gift_transfer_on(form):
        s = s.replace("相关政府费用及代办费用由乙方承担", "全部费用由甲方承担")
    if gift_insurance(form):
        s = s.replace("车辆现有保险不随车转移，乙方须自行购买有效汽车保险",
                      "甲方为乙方代办投保本车辆汽车保险（险种见上列附赠），续保费用由乙方自行承担")
    return s
