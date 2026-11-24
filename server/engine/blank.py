# -*- coding: utf-8 -*-
"""空白模板下载：返回只读模板原件，只清掉模板里写死的默认值（金额/年限），
保留完整条款结构，供打印后手写或下载后自行修改。

与 build_contract 完全无关：不接收表单字段、不分配合同编号、不写 out/、不落历史、
不跑核对。new_port 仍需口岸定位 4 份模板之一（菜单已选定的口岸，不是合同字段值）。
"""
import io
import re

from docx import Document

from engine.types_config import get_type, template_path
from engine import writer as W

# 高才移民模板：金额以「人民币：400000元整 / (大写：人民币肆拾万元整）」写死
_MONEY_RE = re.compile(r"(人民币\s*[：:]?\s*)(\d[\d,，]*)(\s*元整)")
_UPPER_RE = re.compile(r"(大写\s*[：:]\s*人民币)[^）)]*(?=[）)])")
_YEAR_RE = re.compile(r"(20\d{2})年(_{2,})月(_{2,})日")

CAR_GIFT_OLD = "附赠：本车辆过户登记手续的全部费用。"
CAR_GIFT_BLANK = "附赠：________________________________。"
CAR_WARRANTY_MONTHS_OLD = "六个月"
CAR_WARRANTY_MONTHS_BLANK = "______个月"
CAR_WARRANTY_KM_OLD = "三万公里"
CAR_WARRANTY_KM_BLANK = "______公里"


def _iter_paragraphs(doc):
    yield from doc.paragraphs
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _blank_car_defaults(doc):
    """卖车：附赠内容与质保参数是模板默认值，空模板只留空位，保留章节结构。"""
    p_gift = next((p for p in doc.paragraphs if "附赠：" in p.text), None)
    if p_gift is None or not W.replace_in_paragraph(p_gift, CAR_GIFT_OLD, CAR_GIFT_BLANK):
        raise ValueError("卖车模板附赠句与预设不符，无法生成空模板")
    p_warranty = next((p for p in doc.paragraphs if "保修范围" in p.text), None)
    if p_warranty is None:
        raise ValueError("卖车模板缺少保修范围句，无法生成空模板")
    if not W.replace_in_paragraph(p_warranty, CAR_WARRANTY_MONTHS_OLD, CAR_WARRANTY_MONTHS_BLANK):
        raise ValueError("卖车模板质保期限与预设不符，无法生成空模板")
    if not W.replace_in_paragraph(p_warranty, CAR_WARRANTY_KM_OLD, CAR_WARRANTY_KM_BLANK):
        raise ValueError("卖车模板质保公里数与预设不符，无法生成空模板")


def _blank_immigration_amounts(doc):
    """高才移民：模板三节服务费/三期金额是写死的数字，空模板全部改成空位。"""
    n = 0
    for p in _iter_paragraphs(doc):
        n += W.sub_in_paragraph(p, _MONEY_RE, r"\1__________\3")
        n += W.sub_in_paragraph(p, _UPPER_RE, r"\1__________")
        W.sub_in_paragraph(p, _YEAR_RE, "____年____月____日")
    if n == 0:
        raise ValueError("高才移民模板未找到可清空的金额，无法生成空模板")


def build_blank_docx(type_key: str, port: str = "") -> bytes:
    """生成空白模板 docx 字节。只认 type/port，任何表单字段都不参与。"""
    cfg = get_type(type_key)
    tpl = template_path(cfg, {"port": port})
    doc = Document(tpl)
    if type_key == "car":
        _blank_car_defaults(doc)
    elif type_key == "immigration":
        _blank_immigration_amounts(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
