# -*- coding: utf-8 -*-
"""数字金额 → 中文大写（人民币/港币通用，模板格式为「……元整」）"""
import re

_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_UNITS = ["", "拾", "佰", "仟"]
_GROUPS = ["", "万", "亿", "兆"]

CURRENCIES = ("HKD", "CNY")

_CUR_PREFIX_RE = re.compile(r"^(hk\$|rmb|rmb\$|¥|￥|cny|hkd)", re.IGNORECASE)


def clean_amount(value, field_name: str = "金额") -> int:
    """严格把任意输入解析为整数金额。

    接受：int、整数值浮点（500000.0）、带千分位或货币符号的字符串（"500,000" / "HK$500000"）。
    拒绝：带小数部分的值（500000.7）、含中文单位（"50万"）、空值、其它非数字内容。
    一律抛 ValueError（由 API 层转 422），**绝不静默截断**——合同金额必须与约定一致。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field_name}不能为空")
    if isinstance(value, bool):
        raise ValueError(f"{field_name}格式不正确：{value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{field_name}必须为整数（合同为「元整」格式），当前为 {value}")
        return int(value)
    s = str(value).strip()
    s = _CUR_PREFIX_RE.sub("", s).replace(",", "").replace("，", "").replace(" ", "")
    if not s:
        raise ValueError(f"{field_name}格式不正确：{value!r}")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError(
            f"{field_name}「{value}」无法识别为数字金额，请填写阿拉伯数字（如 500000），不要使用「万」等中文单位")
    if "." in s:
        int_part, frac = s.split(".", 1)
        if frac.strip("0"):
            raise ValueError(f"{field_name}必须为整数（合同为「元整」格式），当前为 {value}")
        s = int_part
    return int(s)


def clean_currency(code, field_name: str = "币种") -> str:
    """币种白名单校验，非法币种抛 ValueError（转 422）而不是 KeyError（500）。"""
    c = str(code or "").strip().upper()
    if c not in CURRENCIES:
        raise ValueError(f"{field_name}「{code}」不支持，可选：{' / '.join(CURRENCIES)}")
    return c


def _four_digits(n: int) -> str:
    """0 <= n <= 9999 的四位转大写（含进位单位，不含组单位）"""
    if n == 0:
        return ""
    parts = []
    zero_pending = False
    started = False
    for pos in range(3, -1, -1):
        d = (n // (10 ** pos)) % 10
        if d == 0:
            if started:
                zero_pending = True
        else:
            if zero_pending:
                parts.append("零")
                zero_pending = False
            parts.append(_DIGITS[d] + _UNITS[pos])
            started = True
    return "".join(parts)


def to_cn_upper(amount) -> str:
    """整数金额转中文大写，返回如「壹拾万零伍佰元整」；只接受整数金额。"""
    if isinstance(amount, float):
        if not amount.is_integer():
            raise ValueError(f"金额必须为整数（模板为「元整」格式）: {amount}")
        amount = int(amount)
    amount = int(amount)
    if amount < 0:
        raise ValueError("金额不能为负")
    if amount == 0:
        return "零元整"
    segs = []
    n = amount
    while n > 0:
        segs.append(n % 10000)
        n //= 10000
    segs.reverse()  # 高位组在前
    parts = []
    pending_zero = False
    for i, seg in enumerate(segs):
        if seg == 0:
            pending_zero = True
            continue
        s = _four_digits(seg)
        # 非首组且（前面隔了全零组 或 本组缺千位）→ 补零衔接
        if parts and (pending_zero or seg < 1000):
            parts.append("零")
        parts.append(s + _GROUPS[len(segs) - 1 - i])
        pending_zero = False
    return "".join(parts) + "元整"


def with_commas(amount) -> str:
    return f"{int(amount):,}"


def currency_label(code: str) -> str:
    return {"HKD": "港币", "CNY": "人民币"}[code]


def currency_symbol(code: str) -> str:
    return {"HKD": "HK$", "CNY": "¥"}[code]


def amount_phrase(amount, code: str) -> str:
    """组成模板金额单元格式，如「港币（大写）壹拾万元整（HK$100,000）」"""
    return f"{currency_label(code)}（大写）{to_cn_upper(amount)}（{currency_symbol(code)}{with_commas(amount)}）"
