# -*- coding: utf-8 -*-
"""公司印信：签字+公章定位与注入。

定位规则：公司恒为「华星资源开发有限公司」，签署块表（含签署特征）里含公司名的格
就是公司格、另一格是客户格——不按甲/乙关键字定位，因为各业务里公司可能是
甲方（卖车/过户）也可能是乙方（新办/高才移民），客户侧角色随业务翻转。

注入方式＝内嵌图+对称占位：公司格在签名线之后、日期段之前插「签字段」「章段」；
客户格同位置插两个等高空段——两边日期同步下移，同一水平线（docx-preview 与
Word 行为一致；浮动图在预览库会占流式空间且偏移不生效，弃用）。
高才移民签署表的日期在通栏共享行，公司格加图整行一起下移，天然对齐。
印信文件 = data/seals/sign.png + seal.png，缺失时跳过注入（模板保持无章，不报错）。
"""
import copy
import os

from docx.document import Document as _Doc
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.table import _Cell

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


def _img_height_in(path: str, width_in: float) -> float:
    """按原图纵横比算显示高度（英寸）。"""
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
    return width_in * h / w


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


def blank_para_before(ref_para, height_in: float):
    """在 ref_para 前插一个继承其样式的空段，行高锁定 height_in 英寸，返回该段。"""
    p = copy.deepcopy(ref_para._p)
    for r in p.findall(qn("w:r")):
        p.remove(r)
    ref_para._p.addprevious(p)
    para = ref_para.__class__(p, ref_para._parent)
    pf = para.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(height_in * 72)
    return para


def blank_para_after(ref_para, height_in: float):
    """在 ref_para 后插一个继承其样式的空段，行高锁定 height_in 英寸，返回该段。"""
    p = copy.deepcopy(ref_para._p)
    for r in p.findall(qn("w:r")):
        p.remove(r)
    ref_para._p.addnext(p)
    para = ref_para.__class__(p, ref_para._parent)
    pf = para.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(height_in * 72)
    return para


def first_para_with(cell: _Cell, *keys):
    for p in cell.paragraphs:
        if any(k in p.text for k in keys):
            return p
    return None


def _transparent_png(w_px: int, h_px: int) -> "io.BytesIO":
    """透明占位图（与签字/章同显示尺寸）——客户格里放同尺寸透明图占位，
    与公司格真实图片走完全相同的渲染路径，任何渲染器里两边高度都一致。"""
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGBA", (w_px, h_px), (0, 0, 0, 0)).save(buf, "PNG")
    buf.seek(0)
    return buf


def transparent_spacer_para_before(ref_para, width, height_in: float):
    """在 ref_para 前插一个含同尺寸透明图的占位段——与真实图片段渲染路径一致，
    预览库（docx-preview）与 Word 里高度都相同，保证甲乙两列日期对齐。"""
    p = blank_para_before(ref_para, height_in)
    p.add_run().add_picture(_transparent_png(int(width.inches * 200), int(height_in * 200)),
                            width=width)
    return p


def _pic_runs_after_softbreak(p, after_key: str, images: list) -> bool:
    """软换行单段版式：在含 after_key 文本的 run 之后的首个换行（w:br）处，
    依序插入图片 run（图片之间补换行）。images = [(路径或 BytesIO, 宽), ...]。
    失败时移除已插入的 run 并返回 False，段落零改动。"""
    runs_before = list(p._p.findall(qn("w:r")))
    new_elems = []
    first = True
    for src, width in images:
        if not first:
            br_run = p.add_run()
            br_run._r.append(br_run._r.makeelement(qn("w:br"), {}))
            new_elems.append(br_run._r)
        r = p.add_run()
        r.add_picture(src, width=width)
        new_elems.append(r._r)
        first = False
    target_idx = None
    for i, r in enumerate(runs_before):
        t = "".join(n.text or "" for n in r.findall(qn("w:t")))
        if after_key in t:
            target_idx = i
    anchor = None
    if target_idx is not None:
        for i in range(target_idx, len(runs_before)):
            if runs_before[i].find(qn("w:br")) is not None:
                anchor = runs_before[i]
                break
    if anchor is None:
        for el in new_elems:
            el.getparent().remove(el)
        return False
    prev = anchor
    for el in new_elems:
        prev.addnext(el)
        prev = el
    return True


def apply_company_seal(doc: _Doc) -> bool:
    """公司签字+公章合成进公司格：签名线之后、日期之前插「签字段」「章段」
    （签字贴签名线下缘、章压日期上方，与真实签字页同序）；客户格同位插同尺寸
    透明占位图，两边日期保持同一水平线。高才移民版式公司格只有公司名段、日期在
    通栏共享行——签字/章段插在公司名段之后，整表行随之下移，日期天然对齐。
    软换行单段版式（过户：签署文字挤在一个段落、行间 w:br 分隔）按段内换行位插图。
    印信文件缺失或找不到签署格 → False，文档零改动。"""
    assets = _assets()
    if not assets:
        return False
    located = locate(doc)
    if not located:
        return False
    comp, cli = located
    sign_path, seal_path = assets
    sign_h = _img_height_in(sign_path, SIGN_W.inches)
    seal_h = _img_height_in(seal_path, SEAL_W.inches)

    p_date = first_para_with(comp, "日期")
    # 软换行单段版式（过户）：签署文字与日期挤在同一段落、行间 w:br 分隔——
    # 签字插在签名线换行后、章插在「公司印章」换行后；客户格同位插透明占位
    soft_p = None
    for p in comp.paragraphs:
        if "日期" in p.text and ("____" in p.text or "签署" in p.text):
            soft_p = p
            break
    if soft_p is not None:
        import io as _io
        dpi = 200
        ok_sign = _pic_runs_after_softbreak(soft_p, "____", [(sign_path, SIGN_W)])
        ok_seal = _pic_runs_after_softbreak(soft_p, "公司印章", [(seal_path, SEAL_W)]) or \
            _pic_runs_after_softbreak(soft_p, "____", [(seal_path, SEAL_W)])
        spacers = [(_transparent_png(int(SIGN_W.inches * dpi), int(sign_h * dpi)), SIGN_W),
                   (_transparent_png(int(SEAL_W.inches * dpi), int(seal_h * dpi)), SEAL_W)]
        for p in cli.paragraphs:
            if "日期" in p.text and ("____" in p.text or "签署" in p.text):
                _pic_runs_after_softbreak(p, "____", spacers)
                break
        return ok_sign and ok_seal
    if p_date is None:
        # B 路径（高才移民）：公司格只有公司名段 → 签字/章段插在其后
        p_name = first_para_with(comp, COMPANY_NAME) or comp.paragraphs[0]
        p_sign = blank_para_after(p_name, sign_h)
        p_sign.add_run().add_picture(sign_path, width=SIGN_W)
        p_seal = blank_para_after(p_sign, seal_h)
        p_seal.add_run().add_picture(seal_path, width=SEAL_W)
        return True

    # A 路径（车/过户/新办）：签字段插在「公司印章」标签（无则日期段）之前，
    # 章段插在标签之后——章贴标签、压日期上方；客户格对称插同尺寸透明占位图
    p_stamp = first_para_with(comp, "公司印章", "盖章")
    p_sign = blank_para_before(p_stamp or p_date, sign_h)
    p_sign.add_run().add_picture(sign_path, width=SIGN_W)
    p_seal = blank_para_before(p_date, seal_h)
    p_seal.add_run().add_picture(seal_path, width=SEAL_W)
    if first_para_with(cli, "日期") is not None:
        transparent_spacer_para_before(first_para_with(cli, "日期"), SIGN_W, sign_h)
        transparent_spacer_para_before(first_para_with(cli, "日期"), SEAL_W, seal_h)
    return True
