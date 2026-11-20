# -*- coding: utf-8 -*-
"""公司印信：签字+公章定位与注入。

定位规则：公司恒为「华星资源开发有限公司」，签署块表（含「签署」）里含公司名的格
就是公司格、另一个签署格是客户格——不按甲/乙关键字定位，因为各业务里公司可能是
甲方（卖车/过户）也可能是乙方（新办/高才移民），客户侧角色随业务翻转。
印信文件 = data/seals/sign.png + seal.png，缺失时跳过注入（模板保持无章，不报错）。
"""
import os

from docx.document import Document as _Doc
from docx.table import _Cell
from docx.shared import Inches

COMPANY_NAME = "华星资源开发有限公司"
SIGN_W = Inches(1.6)   # 签字条宽
SEAL_W = Inches(1.3)   # 公章宽


def seals_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "seals")


def _assets():
    d = seals_dir()
    sign, seal = os.path.join(d, "sign.png"), os.path.join(d, "seal.png")
    return (sign, seal) if os.path.exists(sign) and os.path.exists(seal) else None


def locate(doc: _Doc):
    """→ (公司格, 客户格) 或 None。

    签署块表识别：含公司名且含签署特征（签署/签名/盖章/下划线栏）——车/过户/新办的
    签署表是「甲方…签署…｜乙方…签署…」，高才移民是「甲方：____｜乙方：华星 /
    签名：/代表签名/盖章：」，特征词不同。公司格=含公司名的格；客户格优先取下划线
    签名栏，否则取含签署/签名字样的另一格。"""
    for t in doc.tables:
        txt = " ".join(c.text for r in t.rows for c in r.cells)
        if COMPANY_NAME not in txt:
            continue
        if not any(k in txt for k in ("签署", "签名", "盖章", "____")):
            continue
        comp = cli = None
        for row in t.rows:
            for c in row.cells:
                if COMPANY_NAME in c.text:
                    comp = c
                elif "____" in c.text:
                    cli = cli or c
                elif ("签署" in c.text or "签名" in c.text) and len(c.text.strip()) > 2:
                    cli = cli or c
        if comp is not None and cli is not None and comp._tc is not cli._tc:
            return comp, cli
    return None


def apply_company_seal(doc: _Doc) -> bool:
    """公司签字+公章合成进公司格（签字在上、公章在下，仿现实先签后盖）。
    印信文件缺失或找不到签署格 → False，文档零改动。"""
    assets = _assets()
    if not assets:
        return False
    located = locate(doc)
    if not located:
        return False
    comp, _cli = located
    sign_path, seal_path = assets
    # 印图追加进公司格最后一段（不新增段落）：新增空段会让 cell.text 末尾多出换行，
    # 触发 checker「表格内容被意外改动：签署确认块」
    p = comp.paragraphs[-1]
    p.add_run().add_picture(sign_path, width=SIGN_W)
    p.add_run().add_picture(seal_path, width=SEAL_W)
    return True
