# -*- coding: utf-8 -*-
"""公司印信：签字+公章定位与注入（统一签署块骨架）。

定位规则：公司恒为「华星资源开发有限公司」，签署块表（含签署特征）里含公司名的格
就是公司格、另一格是客户格——不按甲/乙关键字定位，因为各业务里公司可能是
甲方（卖车/过户）也可能是乙方（新办），客户侧角色随业务翻转。

注入方式＝重建统一骨架：两格各自保留抬头段，其余段重建成同一序列——
  公司格：抬头 → 授权代表签署：→ ____ → [签字图] → 公司印章：→ [章图] → 日期
  客户格：抬头 → 签署／授权代表签署：→ ____ → [透明占位] → [透明占位] → 日期
两格段落序列完全对称，日期永远同一水平线；各模板签署区原本的空行/软换行差异
在重建时全部抹平，不再按业务写适配。软换行段先按 w:br 拆成独立段再重建。
高才移民签署表是四列两行（甲方签字/盖章行+日期行）结构，公司格只有公司名段——
签字/章合成一张图（章压签尾）插在公司名段后，整行随之下移，日期天然对齐（B 路径）。
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
CELL_MARGIN_IN = 0.075   # Word 默认单元格左右内边距
DPI = 300                # 合成图画布分辨率
SIGN_DROP_IN = 0.37      # 签名相对章的下沉量：章贴右上、签名落左下成对角，
                         # 笔画只擦过章的下缘弧线，不穿章心文字；总高与竖排紧凑版持平
LINE_PAD_PT = 12         # 图片段行高余量：Word 行内图坐在基线上，行高恰好=图高时图片会
                         # 向上顶进上一行（盖住「公司印章：」标签）/向下被裁；图片段与占位段
                         # 同加此量，甲乙两侧高度仍然对称，日期对齐不受影响


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
    签署表是「甲方…签署…｜乙方…签署…」，高才移民是「甲方签字/盖章：____｜
    乙方：华星」没有「签署」二字；公司格=含公司名的格；客户格优先取
    下划线签名栏，否则取含签署/签名字样的另一格。"""
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


def blank_para_before(ref_para, height_in: float = None):
    """在 ref_para 前插一个继承其样式的空段；height_in 给定时设最小行高（含 LINE_PAD_PT 余量）。

    用 AT_LEAST 而非 EXACTLY：固定行高会把高出部分直接裁掉，而各机器 Word 的
    基线度量不同（同一 docx 有的机器裁有的不裁）；最小行高只会撑开、永不裁切，
    图片段与占位段同源同规则，甲乙两侧高度依旧对称。"""
    p = copy.deepcopy(ref_para._p)
    for r in p.findall(qn("w:r")):
        p.remove(r)
    ref_para._p.addprevious(p)
    para = ref_para.__class__(p, ref_para._parent)
    if height_in is not None:
        pf = para.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
        pf.line_spacing = Pt(height_in * 72 + LINE_PAD_PT)
    return para


def blank_para_after(ref_para, height_in: float):
    """在 ref_para 后插一个继承其样式的空段，最小行高 height_in 英寸（含 LINE_PAD_PT 余量）。"""
    p = copy.deepcopy(ref_para._p)
    for r in p.findall(qn("w:r")):
        p.remove(r)
    ref_para._p.addnext(p)
    para = ref_para.__class__(p, ref_para._parent)
    pf = para.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.AT_LEAST
    pf.line_spacing = Pt(height_in * 72 + LINE_PAD_PT)
    return para


def first_para_with(cell: _Cell, *keys):
    for p in cell.paragraphs:
        if any(k in p.text for k in keys):
            return p
    return None


def cell_content_width(cell: _Cell) -> float:
    """格内可用宽度（英寸）：tcW 减去默认左右内边距；取不到宽度时给 0。"""
    try:
        return cell.width.inches - 2 * CELL_MARGIN_IN
    except (AttributeError, TypeError):
        return 0.0


def compose_sign_seal(sign_path: str, seal_path: str, avail_in: float):
    """签字+章合成一张图 → (png 字节流, 高英寸)；格太窄放不下并排时返回 None。

    对角布局：章贴右上（顶端对齐）、签名沉到左下（底端对齐）——横向仍压住签名
    尾部（骑章观感），纵向笔画只擦过章的下缘弧线、避开章心密集文字；
    两张图的显示宽度（SIGN_W/SEAL_W）不变，高度按各自原图纵横比换算。"""
    import io as _io
    from PIL import Image
    if avail_in < SEAL_W.inches + 0.3:
        return None
    px = lambda inch: round(inch * DPI)
    sign = Image.open(sign_path).convert("RGBA")
    seal = Image.open(seal_path).convert("RGBA")
    sign = sign.resize((px(SIGN_W.inches),
                        round(sign.height * px(SIGN_W.inches) / sign.width)), Image.LANCZOS)
    seal = seal.resize((px(SEAL_W.inches),
                        round(seal.height * px(SEAL_W.inches) / seal.width)), Image.LANCZOS)
    canvas_h = max(px(SIGN_DROP_IN) + sign.height, seal.height)
    canvas = Image.new("RGBA", (px(avail_in), canvas_h), (0, 0, 0, 0))
    canvas.alpha_composite(sign, (0, canvas_h - sign.height))   # 底端对齐：沉到左下
    canvas.alpha_composite(seal, (px(avail_in - SEAL_W.inches), 0))   # 顶端对齐：贴右上
    buf = _io.BytesIO()
    canvas.save(buf, "PNG")
    buf.seek(0)
    return buf, canvas.height / DPI


def _transparent_png(w_px: int, h_px: int):
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


def _split_softbreaks(cell: _Cell):
    """把格内含软换行（w:br）的段拆成多个独立段：换行后各段继承原段样式与文字。"""
    for p in list(cell.paragraphs):
        if p._p.find(".//" + qn("w:br")) is None:
            continue
        segments = [[]]   # 每段 = run 子元素列表；遇 br 开新段
        orig_first_r = p._p.find(qn("w:r"))
        for r in p._p.findall(qn("w:r")):
            for sub in list(r):
                if sub.tag == qn("w:br"):
                    segments.append([])
                else:
                    segments[-1].append(sub)
        new_ps = []
        for seg in segments:
            np = copy.deepcopy(p._p)
            for ch in list(np):
                if ch.tag != qn("w:pPr"):
                    np.remove(ch)
            r_el = np.makeelement(qn("w:r"), {})
            if orig_first_r is not None:
                r_pr = orig_first_r.find(qn("w:rPr"))
                if r_pr is not None:
                    r_el.append(copy.deepcopy(r_pr))
            for el in seg:
                r_el.append(copy.deepcopy(el))
            np.append(r_el)
            new_ps.append(np)
        prev = p._p
        for np in new_ps:
            prev.addnext(np)
            prev = np
        p._p.getparent().remove(p._p)


def _stamp_para_before(date_para):
    """在日期段前插「公司印章：」段（克隆日期段样式、替换文字），返回该段。"""
    p = copy.deepcopy(date_para._p)
    for r in p.findall(qn("w:r")):
        p.remove(r)
    date_para._p.addprevious(p)
    para = date_para.__class__(p, date_para._parent)
    para.add_run("公司印章：")
    return para


def apply_company_seal(doc: _Doc) -> bool:
    """公司签字+公章合成进公司格，并把两格重建成统一签署骨架（各业务只保留
    自己的抬头文字与日期）——构图全业务一致，甲乙日期同一水平线。
    高才移民签署表为四列两行结构：签字/章合成一张图（章压签尾）插在公司名段后，
    整行随之下移，日期天然对齐。印信文件缺失或找不到签署格 → False，文档零改动。"""
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

    # 高才移民（B 路径）：公司格只有公司名段、无授权代表签署行 → 签字/章插在其后，
    # 甲方/乙方行与日期行均为通栏共享行，整行随之下移，日期天然对齐。
    # 优先合成一张图（章压签尾，签署区高度减半）；格太窄放不下并排再退回竖排两图
    if first_para_with(comp, "授权代表签署") is None and \
            first_para_with(comp, "____") is None:
        p_name = first_para_with(comp, COMPANY_NAME) or comp.paragraphs[0]
        composed = compose_sign_seal(sign_path, seal_path, cell_content_width(comp))
        if composed is not None:
            png, h = composed
            p_img = blank_para_after(p_name, h)
            p_img.add_run().add_picture(png, width=Inches(cell_content_width(comp)))
            return True
        p_sign = blank_para_after(p_name, sign_h)
        p_sign.add_run().add_picture(sign_path, width=SIGN_W)
        p_seal = blank_para_after(p_sign, seal_h)
        p_seal.add_run().add_picture(seal_path, width=SEAL_W)
        return True

    # 统一骨架（A 路径：车/过户/新办）
    _split_softbreaks(comp)
    _split_softbreaks(cli)

    def canonicalize(cell: _Cell, real: bool) -> bool:
        paras = cell.paragraphs
        p_label = paras[0]
        p_sign_label = first_para_with(cell, "授权代表签署", "签署／授权代表签署")
        p_line = first_para_with(cell, "____")
        p_date = first_para_with(cell, "日期")
        p_stamp = first_para_with(cell, "公司印章")
        if not (p_sign_label and p_line and p_date) or p_label is p_date:
            return False
        # 删除骨架之外的段（空行、姓名行等模板杂项）
        keep = {id(p._p) for p in (p_label, p_sign_label, p_line, p_stamp, p_date) if p}
        for p in list(cell.paragraphs):
            if id(p._p) not in keep:
                p._p.getparent().remove(p._p)
        # 排序：抬头 → 授权代表签署 → ____ → [公司印章] → 日期
        seq = [p_label._p, p_sign_label._p, p_line._p]
        if p_stamp is not None:
            seq.append(p_stamp._p)
        seq.append(p_date._p)
        for i in range(len(seq) - 1):
            seq[i].addnext(seq[i + 1])
        # 刷新引用后插图/占位：签字段在线后、章段紧贴日期前
        p_sign_label = first_para_with(cell, "授权代表签署", "签署／授权代表签署")
        p_line = first_para_with(cell, "____")
        p_date = first_para_with(cell, "日期")
        p_stamp = first_para_with(cell, "公司印章")
        if real:
            p_sig = blank_para_before(p_date, sign_h)
            p_sig.add_run().add_picture(sign_path, width=SIGN_W)
            # 统一骨架：公司印章标签段紧跟签字图之后（过户模板原有则挪位，其余新建）
            if p_stamp is None:
                p_stamp = _stamp_para_before(p_date)
            else:
                p_sig._p.addnext(p_stamp._p)
            p_seal = blank_para_before(p_date, seal_h)
            p_seal.add_run().add_picture(seal_path, width=SEAL_W)
        else:
            transparent_spacer_para_before(p_date, SIGN_W, sign_h)
            blank_para_before(p_date)   # 对应公司格「公司印章：」行的自然高度
            transparent_spacer_para_before(p_date, SEAL_W, seal_h)
        return True

    ok = canonicalize(comp, real=True)
    if ok:
        canonicalize(cli, real=False)
    return ok
