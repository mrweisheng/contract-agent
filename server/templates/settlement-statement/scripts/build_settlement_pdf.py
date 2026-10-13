from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

OUT = "/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv/output/pdf/客户收款结算单模板.pdf"
LOGO = "/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv/assets/ming-ge-cross-border-logo-v1.png"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

pdfmetrics.registerFont(TTFont("CJK", FONT))
W, H = letter
NAVY = HexColor("#0B2E59")
BLUE = HexColor("#1769AA")
RMB = HexColor("#EAF3FA")
RMB_ALT = HexColor("#F6FAFD")
HKD = HexColor("#E8F5F2")
HKD_ALT = HexColor("#F4FAF8")
TEXT = HexColor("#1D2733")
GRAY = HexColor("#687386")
BORDER = HexColor("#CBD8E5")

c = canvas.Canvas(OUT, pagesize=letter)
c.setTitle("收款結算單")

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
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(sw)
    c.rect(x, top-h, w, h, fill=1, stroke=1)

def cell(x, top, w, h, s, fill=white, color=TEXT, align="left", size=8.3, bold=False, pad=7):
    box(x, top, w, h, fill)
    px = x+pad if align == "left" else (x+w/2 if align == "center" else x+w-pad)
    txt(px, top-h/2-3, s, size, color, align, bold)

# Header
c.drawImage(ImageReader(LOGO), 45, 690, width=195, height=78, preserveAspectRatio=True, mask="auto")
txt(565, 748, "SETTLEMENT STATEMENT", 9.5, GRAY, "right", True)
txt(565, 714, "收款結算單", 22, NAVY, "right", True)
txt(565, 681, "日期  2026年9月21日", 8.5, GRAY, "right")

# Basic information
x0, top = 45, 655
mw = [78, 180, 78, 186]
meta = [
    ["客戶名稱", "[客戶名稱]", "群名", "[業務群名稱]"],
    ["申請口岸", "[申請口岸]", "結算類型", "[尾款／雜費／補款／階段款]"],
]
for r, row in enumerate(meta):
    x = x0
    for i, s in enumerate(row):
        label = i in (0, 2)
        cell(x, top-r*29, mw[i], 29, s, NAVY if label else white,
             white if label else TEXT, "center" if label else "left", 9.1, label)
        x += mw[i]

# Collection table: sequence, item, receivable, digit boxes
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

def group_row(top_y, label, fill, color):
    cell(x0, top_y, 522, 19, label, fill, color, "left", 9.2, True, 10)

def amount_row(top_y, no, item, amount, fill):
    cell(x0, top_y, seq_w, 25, str(no), fill, TEXT, "center", 9.1)
    cell(x0+seq_w, top_y, item_w, 25, item, fill, TEXT, "left", 8.9)
    cell(x0+seq_w+item_w, top_y, due_w, 25, amount, fill, TEXT, "center", 9.2)
    for i in range(8):
        cell(digits_x+i*digit_w, top_y, digit_w, 25, "", fill, TEXT, "center", 8)

y = table_top-38
group_row(y, "人民幣 CNY", RMB, NAVY)
y -= 19
rmb_rows = [
    (1, "業務合同金額或階段款", "¥ 0.00"),
    (2, "訂金或前期已付款", "¥ 0.00"),
    (3, "物流或倉儲費用", "¥ 0.00"),
    (4, "其他增加或減少項", "¥ 0.00"),
]
for i, row in enumerate(rmb_rows):
    amount_row(y, *row, RMB)
    y -= 25
group_row(y, "港幣 HKD", HKD, HexColor("#176B61"))
y -= 19
hkd_rows = [
    (5, "保險 驗車 校正本等雜費", "$ 0.00"),
    (6, "其他增加或減少項", "$ 0.00"),
]
for i, row in enumerate(hkd_rows):
    amount_row(y, *row, HKD)
    y -= 25

# Notes and grand total
cell(x0, y, 522, 30, "備註：", white, NAVY, "left", 9.5, True, 9)
y -= 30
box(x0, y, 522, 35, NAVY)
txt(x0+12, y-23, "本次應收總額：", 12, white, "left", True)
txt(x0+160, y-23, "¥", 13, white, "left", True)
txt(x0+320, y-23, "/", 13, white, "center", True)
txt(x0+365, y-23, "$", 13, white, "left", True)
y -= 35

txt(x0, y-17, "金額說明", 8.8, NAVY, "left", True)
txt(x0+52, y-17,
    "正數表示新增應收，負數表示已付款、退款、優惠或扣減。人民幣與港幣分開核算；如需折算，按照合同簽訂日期的匯率進行折算。",
    7.15, TEXT)
y -= 31

# Mainland and Hong Kong account details
left_x, right_x = x0, x0+261
label_w, value_w = 83, 178
row_h = 22
mainland = [
    ("大陸收款帳戶", "陳振耀"),
    ("開戶銀行", "工商銀行"),
    ("收款帳號", "2009020501023937427"),
    ("網點號", "0205"),
    ("名稱", "汕尾海豐東門頭支行"),
    ("地址", "海豐縣城人民中路7號"),
    ("電話", "0660-6623712"),
]
hongkong = [
    ("香港收款帳戶", "華星資源開發有限公司"),
    ("英文名稱", "CHINA STAR RESOURCE DEVELOPMENT LIMITED"),
    ("開戶銀行", "華僑銀行"),
    ("收款帳號", "035-802-129-690-051"),
    ("轉數快識別碼", "131-831-406"),
    ("", ""),
    ("", ""),
]
for r in range(7):
    lt, lv = mainland[r]
    rt, rv = hongkong[r]
    cell(left_x, y-r*row_h, label_w, row_h, lt, RMB, NAVY, "center", 7.2, True, 2)
    cell(left_x+label_w, y-r*row_h, value_w, row_h, lv, white, TEXT, "left", 7.25, False, 6)
    if rt:
        cell(right_x, y-r*row_h, label_w, row_h, rt, RMB, NAVY, "center", 7.0, True, 2)
        value_size = 6.4 if r == 1 else 7.15
        cell(right_x+label_w, y-r*row_h, value_w, row_h, rv, white, TEXT, "left", value_size, False, 5)

txt(W/2, 35, "明哥中港牌  MING GE CROSS BORDER", 8, GRAY, "center")
c.showPage()
c.save()
print(OUT)
