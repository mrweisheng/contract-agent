from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from pathlib import Path

ROOT = Path("/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv")
OUT = ROOT / "output/pdf/6月2日温汉文先生莲塘新办Z1J09港_收尾款结算单_20260922.pdf"
LOGO = ROOT / "assets/ming-ge-cross-border-logo-v1.png"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
OUT.parent.mkdir(parents=True, exist_ok=True)

pdfmetrics.registerFont(TTFont("CJK", FONT))
W, H = letter
NAVY = HexColor("#0B2E59")
RMB = HexColor("#EAF3FA")
HKD = HexColor("#E8F5F2")
TEXT = HexColor("#1D2733")
GRAY = HexColor("#687386")
BORDER = HexColor("#CBD8E5")
RED = HexColor("#D32F2F")

c = canvas.Canvas(str(OUT), pagesize=letter)
c.setTitle("温汉文先生莲塘新办Z1J09港收尾款结算单")

def txt(x, y, s, size=9, color=TEXT, align="left", bold=False):
    c.setFillColor(color)
    c.setFont("CJK", size + (0.55 if bold else 0))
    if align == "center": c.drawCentredString(x, y, s)
    elif align == "right": c.drawRightString(x, y, s)
    else: c.drawString(x, y, s)

def box(x, top, w, h, fill=white, stroke=BORDER, sw=0.6):
    c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(sw)
    c.rect(x, top-h, w, h, fill=1, stroke=1)

def cell(x, top, w, h, s, fill=white, color=TEXT, align="left", size=8.3, bold=False, pad=7):
    box(x, top, w, h, fill)
    px = x+pad if align == "left" else (x+w/2 if align == "center" else x+w-pad)
    txt(px, top-h/2-3, s, size, color, align, bold)

def digits(value):
    cents = int(round(abs(value) * 100))
    values = list(f"{cents:08d}"[-8:])
    # 只省略元及以上部分左侧无意义的前导 0；角、分仍保留两位。
    first_nonzero = next((i for i, d in enumerate(values[:6]) if d != "0"), 6)
    for i in range(first_nonzero):
        values[i] = ""
    return values

c.drawImage(ImageReader(str(LOGO)), 45, 690, width=195, height=78, preserveAspectRatio=True, mask="auto")
txt(565, 748, "SETTLEMENT STATEMENT", 9.5, GRAY, "right", True)
txt(565, 714, "收款結算單", 22, NAVY, "right", True)
txt(565, 681, "日期  2026年9月22日", 8.5, GRAY, "right")

x0, top = 45, 655
mw = [78, 180, 78, 186]
meta = [["客戶名稱", "溫漢文先生", "群名", "6月2日 溫漢文先生蓮塘新辦Z1J09港"], ["申請口岸", "蓮塘口岸", "結算類型", "收尾款"]]
for r, row in enumerate(meta):
    x = x0
    for i, s in enumerate(row):
        label = i in (0, 2)
        cell(x, top-r*29, mw[i], 29, s, NAVY if label else white, white if label else TEXT,
             "center" if label else "left", 9.1, label)
        x += mw[i]

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
for i, lab in enumerate(digit_labels): cell(digits_x+i*digit_w, table_top-18, digit_w, 20, lab, NAVY, white, "center", 8.8, True, 1)

def group_row(top_y, label, fill, color): cell(x0, top_y, 522, 19, label, fill, color, "left", 9.2, True, 10)
def amount_row(top_y, no, item, amount, currency, negative, fill):
    color = RED if negative else TEXT
    sign = "-" if negative else ""
    symbol = "¥" if currency == "CNY" else "$"
    shown = f"{sign}{symbol} {abs(amount):,.2f}"
    cell(x0, top_y, seq_w, 25, str(no), fill, TEXT, "center", 9.1)
    cell(x0+seq_w, top_y, item_w, 25, item, fill, color, "left", 8.9)
    cell(x0+seq_w+item_w, top_y, due_w, 25, shown, fill, color, "center", 9.2)
    for i, d in enumerate(digits(amount)):
        cell(digits_x+i*digit_w, top_y, digit_w, 25, d, fill, color, "center", 8.8)

y = table_top-38
group_row(y, "人民幣 CNY", RMB, NAVY); y -= 19
rmb_rows = [
    (1, "車牌總價", 198000, "CNY", False),
    (2, "車牌未收尾款", 18000, "CNY", False),
]
for row in rmb_rows: amount_row(y, *row, RMB); y -= 25
group_row(y, "港幣 HKD", HKD, HexColor("#176B61")); y -= 19
hkd_rows = [(3, "定金", 58503, "HKD", True), (4, "第二期款", 152108, "HKD", True), (5, "批文卡", 260, "HKD", False), (6, "禁區紙", 744, "HKD", False), (7, "核證本", 300, "HKD", False)]
for row in hkd_rows: amount_row(y, *row, HKD); y -= 25

cell(x0, y, 522, 28, "備註：車牌未收尾款為 ¥18,000.00／$21,060.00。匯率核算以合同簽訂日為標準。", white, NAVY, "left", 7.8, True, 9); y -= 28
box(x0, y, 522, 35, NAVY)
txt(x0+12, y-23, "您今日需付：", 12, white, "left", True)
txt(x0+150, y-23, "¥ 19,114.93", 12, white, "left", True)
txt(x0+315, y-23, "/", 12, white, "center", True)
txt(x0+350, y-23, "$ 22,364.00", 12, white, "left", True)
y -= 35
txt(x0, y-17, "金額說明", 8.8, NAVY, "left", True)
txt(x0+52, y-17, "負數表示已付款或扣減。合同外雜費實收 $0.00；港幣雜費折算人民幣沿用合同等值比例。", 7.15, TEXT)
y -= 31

left_x, right_x = x0, x0+261
label_w, value_w, row_h = 83, 178, 22
mainland = [("大陸收款帳戶", "陳振耀"), ("開戶銀行", "工商銀行"), ("收款帳號", "2009020501023937427"), ("網點號", "0205"), ("名稱", "汕尾海豐東門頭支行"), ("地址", "海豐縣城人民中路7號"), ("電話", "0660-6623712")]
hongkong = [("香港收款帳戶", "華星資源開發有限公司"), ("英文名稱", "CHINA STAR RESOURCE DEVELOPMENT LIMITED"), ("開戶銀行", "華僑銀行"), ("收款帳號", "035-802-129-690-051"), ("轉數快識別碼", "131-831-406"), ("", ""), ("", "")]
for r in range(7):
    lt, lv = mainland[r]; rt, rv = hongkong[r]
    cell(left_x, y-r*row_h, label_w, row_h, lt, RMB, NAVY, "center", 7.2, True, 2)
    cell(left_x+label_w, y-r*row_h, value_w, row_h, lv, white, TEXT, "left", 7.25, False, 6)
    if rt:
        cell(right_x, y-r*row_h, label_w, row_h, rt, RMB, NAVY, "center", 7.0, True, 2)
        cell(right_x+label_w, y-r*row_h, value_w, row_h, rv, white, TEXT, "left", 6.4 if r == 1 else 7.15, False, 5)

txt(W/2, 35, "明哥中港牌  MING GE CROSS BORDER", 8, GRAY, "center")
c.showPage(); c.save(); print(OUT)
