from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

OUT = "/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv/output/pdf/港車買賣結算單預覽.pdf"
LOGO = "/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv/assets/ming-ge-cross-border-logo-v1.png"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

pdfmetrics.registerFont(TTFont("CJK", FONT))
W, H = letter
NAVY = HexColor("#0B2E59")
PALE_BLUE = HexColor("#EAF3FA")
HKD_GROUP = HexColor("#EAF3FA")
HKD = HexColor("#F4F8FC")
HKD_TEXT = NAVY
TEXT = HexColor("#1D2733")
GRAY = HexColor("#687386")
BORDER = HexColor("#CBD8E5")

c = canvas.Canvas(OUT, pagesize=letter)
c.setTitle("港車買賣結算單")

def txt(x, y, s, size=9, color=TEXT, align="left", bold=False):
    c.setFillColor(color)
    c.setFont("CJK", size + (0.55 if bold else 0))
    if align == "center":
        c.drawCentredString(x, y, s)
    elif align == "right":
        c.drawRightString(x, y, s)
    else:
        c.drawString(x, y, s)

def box(x, top, w, h, fill=white, stroke=BORDER, sw=0.6):
    c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(sw)
    c.rect(x, top-h, w, h, fill=1, stroke=1)

def cell(x, top, w, h, s, fill=white, color=TEXT, align="left", size=8.3, bold=False, pad=7):
    box(x, top, w, h, fill)
    px = x+pad if align == "left" else (x+w/2 if align == "center" else x+w-pad)
    txt(px, top-h/2-3, s, size, color, align, bold)

# Header
c.drawImage(ImageReader(LOGO), 45, 690, width=195, height=78, preserveAspectRatio=True, mask="auto")
txt(565, 748, "VEHICLE SETTLEMENT STATEMENT", 9.2, GRAY, "right", True)
txt(565, 714, "港車買賣結算單", 21, NAVY, "right", True)
txt(565, 681, "日期  2026年9月21日", 8.5, GRAY, "right")

# Basic information
x0, top = 45, 655
mw = [78, 180, 78, 186]
meta = [
    ["客戶名稱", "[客戶名稱]", "群名", "[業務群名稱]"],
    ["購買車輛", "[車輛品牌／型號／車牌]", "結算類型", "[車款／訂金／尾款／雜費]"],
]
for r, row in enumerate(meta):
    x = x0
    for i, s in enumerate(row):
        label = i in (0, 2)
        cell(x, top-r*29, mw[i], 29, s, NAVY if label else white,
             white if label else TEXT, "center" if label else "left", 9.1, label)
        x += mw[i]

# HKD-only collection table
table_top = 580
seq_w, item_w, due_w = 34, 168, 90
digit_w = 28.75
digit_labels = ["十萬", "萬", "千", "百", "十", "元", "角", "分"]
cell(x0, table_top, seq_w, 38, "序號", NAVY, white, "center", 10.2, True)
cell(x0+seq_w, table_top, item_w, 38, "收款項目", NAVY, white, "center", 10.5, True)
cell(x0+seq_w+item_w, table_top, due_w, 38, "應收金額", NAVY, white, "center", 10.5, True)
digits_x = x0+seq_w+item_w+due_w
box(digits_x, table_top, digit_w*8, 18, NAVY)
txt(digits_x+digit_w*4, table_top-13, "金額", 10.5, white, "center", True)
for i, lab in enumerate(digit_labels):
    cell(digits_x+i*digit_w, table_top-18, digit_w, 20, lab, NAVY, white, "center", 8.8, True, 1)

def amount_row(top_y, no, item, amount):
    cell(x0, top_y, seq_w, 29, str(no), HKD, TEXT, "center", 9.1)
    cell(x0+seq_w, top_y, item_w, 29, item, HKD, TEXT, "left", 8.9)
    cell(x0+seq_w+item_w, top_y, due_w, 29, amount, HKD, TEXT, "center", 9.2)
    for i in range(8):
        cell(digits_x+i*digit_w, top_y, digit_w, 29, "", HKD, TEXT, "center", 8)

y = table_top-38
cell(x0, y, 522, 21, "港幣 HKD", HKD_GROUP, HKD_TEXT, "left", 9.2, True, 10)
y -= 21
rows = [
    (1, "車輛成交價", "$ 0.00"),
    (2, "訂金或前期已付款", "$ 0.00"),
    (3, "驗車／維修費用", "$ 0.00"),
    (4, "運輸／拖車費用", "$ 0.00"),
    (5, "文件／過戶費用", "$ 0.00"),
    (6, "其他增加或減少項", "$ 0.00"),
]
for row in rows:
    amount_row(y, *row)
    y -= 29

cell(x0, y, 522, 34, "備註：", white, NAVY, "left", 9.5, True, 9)
y -= 34
box(x0, y, 522, 39, NAVY)
txt(x0+12, y-26, "本次應收總額：", 12, white, "left", True)
txt(x0+175, y-26, "港幣 $", 13, white, "left", True)
y -= 39

txt(x0, y-18, "金額說明", 8.8, NAVY, "left", True)
txt(x0+52, y-18, "所有款項均以港幣計算。正數表示新增應收，負數表示已付款、退款、優惠或扣減。", 7.6, TEXT)
y -= 34

# Hong Kong account only; no mainland account content
label_w, value_w = 112, 410
account = [
    ("香港收款帳戶", "華星資源開發有限公司"),
    ("英文名稱", "CHINA STAR RESOURCE DEVELOPMENT LIMITED"),
    ("開戶銀行", "華僑銀行"),
    ("收款帳號", "035-802-129-690-051"),
    ("轉數快識別碼", "131-831-406"),
]
for r, (label, value) in enumerate(account):
    size = 7.3 if r == 1 else 8.2
    cell(x0, y-r*27, label_w, 27, label, PALE_BLUE, NAVY, "center", 8.2, True, 2)
    cell(x0+label_w, y-r*27, value_w, 27, value, white, TEXT, "left", size, False, 8)

txt(W/2, 35, "明哥中港牌  MING GE CROSS BORDER", 8, GRAY, "center")
c.showPage(); c.save()
print(OUT)
