# -*- coding: utf-8 -*-
"""PDF 交付链离线测试：骑缝章叠加 + soffice 降级，不依赖 LibreOffice（转换真链路靠部署冒烟）。
覆盖：章切片逐页落位、透明边裁除、页数自适应、缓存双检降级（无 soffice 报 PdfError）。"""
import sys, io, os, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "pdf_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)

# 造一份 3 页 A4 空白 PDF（reportlab 直接产，不依赖 soffice）
from reportlab.pdfgen import canvas as rl_canvas
base_pdf = os.path.join(TMP, "三页合同.pdf")
c = rl_canvas.Canvas(base_pdf, pagesize=(595, 842))
for i in range(3):
    c.setFont("Helvetica", 12)
    c.drawString(72, 770, f"page {i + 1}")
    c.showPage()
c.save()

from engine import pdf as pdf_mod

# 1) 骑缝章：3 页各贴 1/3 纵切片，页数自适应
stamped = pdf_mod.stamp_cross_page_seal(base_pdf)
check(stamped is True, "盖章成功返回 True（本地 data/seals 有 seal.png）")
from pypdf import PdfReader
reader = PdfReader(base_pdf)
check(len(reader.pages) == 3, f"页数不变（{len(reader.pages)}）")
imgs = [len(p.images) for p in reader.pages]
check(all(n == 1 for n in imgs), f"每页右缘 1 条章切片（{imgs}）")

# 2) 渲染校验：右缘章带非白（章墨落上了），左半页仍空白（没污染正文）
import pypdfium2 as pdfium
doc = pdfium.PdfDocument(base_pdf)
from PIL import Image
band_nonwhite = []
for i in range(len(doc)):
    im = doc[i].render(scale=2).to_pil().convert("L")   # A4@2x: 1190x1684
    band = im.crop((1080, 500, 1180, 1180))             # 右缘章带（sw≈29pt→58px，取内带）
    body = im.crop((100, 500, 700, 1180))               # 正文带
    band_nonwhite.append(sum(1 for px in band.getdata() if px < 245))
    check(any(px < 245 for px in band.getdata()), f"第{i + 1}页右缘有章墨")
    check(all(px >= 245 for px in body.getdata()), f"第{i + 1}页正文带未被污染")
doc.close()

# 3) 切片拼合 ≈ 完整章（ eyeball 用：拼图落 TMP，断言非空即可）
check(pdf_mod._seal_strips(os.path.join(ROOT, "server", "data", "seals", "seal.png"), 3).__len__() == 3,
      "_seal_strips 产 3 条切片")
# 透明边裁除：用未裁剪的旧版尺寸印章验证切片不含全透明条
old_seal = os.path.join(TMP, "old_seal.png")
PILImage = Image
canvas_img = PILImage.new("RGBA", (400, 522), (0, 0, 0, 0))
for x in range(20, 380):
    for y in range(40, 400):
        canvas_img.putpixel((x, y), (40, 40, 160, 200))
canvas_img.save(old_seal)
strips = pdf_mod._seal_strips(old_seal, 3)
import io as _io
contents_ok = all(Image.open(_io.BytesIO(b)).convert("L").getextrema()[0] < 200 for b, _, _ in strips)
check(contents_ok, "旧版带透明边印章：切片前裁除透明边，每条都有内容")

# 4) ensure_pdf 降级：soffice 不在（本地 Windows）→ PdfError；缓存双检路径
if pdf_mod.soffice_available():
    print("skip  本机有 soffice，跳过降级断言（真链路由部署冒烟覆盖）")
else:
    try:
        pdf_mod.ensure_pdf(base_pdf.replace(".pdf", ".docx") if os.path.exists(base_pdf.replace(".pdf", ".docx")) else os.path.join(TMP, "不存在.docx"))
        check(False, "无 soffice 时应抛 PdfError")
    except pdf_mod.PdfError as ex:
        check("LibreOffice" in str(ex), f"无 soffice → PdfError（{ex}）")

print()
print("总体:", "全部通过" if not FAIL else f"{len(FAIL)} 项失败")
sys.exit(1 if FAIL else 0)
