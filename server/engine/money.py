# -*- coding: utf-8 -*-
"""数字金额 → 中文大写（人民币/港币通用，模板格式为「……元整」）"""

_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_UNITS = ["", "拾", "佰", "仟"]
_GROUPS = ["", "万", "亿", "兆"]


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
