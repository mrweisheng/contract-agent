from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path("/Users/chenqiqi/Documents/ChatGPT/cqtzVntTAhsv")
OUT = ROOT / "output/pdf/0922黄俊海20系埃尔法YZ3891_收尾款结算单_20260924.pdf"
LOGO = Path("/Users/chenqiqi/.codex/skills/settlement-statement/assets/明哥中港牌-logo.png")
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
RED = HexColor("#C62828")
GREEN = HexColor("#176B61")
YELLOW = HexColor("#FFF1B8")

c = canvas.Canvas(str(OUT), pagesize=letter)
c.setTitle("鄭寶測車輛買賣收尾款結算單")


def txt(x, y, value, size=9, color=TEXT, align="left", bold=False):
    size += 4
    c.setFillColor(color)
    c.setFont("CJK", size + (0.55 if bold else 0))
    if align == "center":
        c.drawCentredString(x, y, value)
    elif align == "right":
        c.drawRightString(x, y, value)
    else:
        c.drawString(x, y, value)


def box(x, top, width, height, fill=white, stroke=BORDER, stroke_width=0.6):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(stroke_width)
    c.rect(x, top - height, width, height, fill=1, stroke=1)


def cell(x, top, width, height, value, fill=white, color=TEXT,
         align="left", size=8.3, bold=False, pad=7):
    box(x, top, width, height, fill)
    px = x + pad if align == "left" else (x + width / 2 if align == "center" else x + width - pad)
    txt(px, top - height / 2 - 3, value, size, color, align, bold)


def digits(value):
    cents = int(round(abs(value) * 100))
    values = list(f"{cents:08d}"[-8:])
    first_nonzero = next((i for i, digit in enumerate(values[:6]) if digit != "0"), 6)
    for index in range(first_nonzero):
        values[index] = ""
    return values


# Header
c.drawImage(ImageReader(str(LOGO)), 35, 700, width=195, height=78,
            preserveAspectRatio=True, mask="auto")
txt(565, 748, "SETTLEMENT STATEMENT", 9.5, GRAY, "right", True)
txt(565, 714, "收款結算單", 22, NAVY, "right", True)
txt(565, 681, "日期  2026年9月24日", 8.5, GRAY, "right")

# Basic information
x0, top = 45, 655
meta_widths = [78, 180, 78, 186]
meta = [
    ["客戶名稱", "鄭寶測", "群名", "0922黄俊海20系埃尔法YZ3891"],
    ["購買車輛", "20系埃爾法 YZ3891", "結算類型", "收尾款"],
]
for row_index, row in enumerate(meta):
    x = x0
    for index, value in enumerate(row):
        is_label = index in (0, 2)
        cell(
            x, top - row_index * 29, meta_widths[index], 29, value,
            NAVY if is_label else white,
            white if is_label else TEXT,
            "center" if is_label else "left",
            8.65 if index == 3 and row_index == 0 else 9.1,
            is_label,
        )
        x += meta_widths[index]

# Collection table
table_top = 586
seq_w, item_w, due_w = 34, 168, 90
digit_w = 28.75
digit_labels = ["十萬", "萬", "千", "百", "十", "元", "角", "分"]
cell(x0, table_top, seq_w, 38, "序號", NAVY, white, "center", 10.2, True)
cell(x0 + seq_w, table_top, item_w, 38, "收款項目", NAVY, white, "center", 10.5, True)
cell(x0 + seq_w + item_w, table_top, due_w, 38, "應收金額", NAVY, white, "center", 10.5, True)
digits_x = x0 + seq_w + item_w + due_w
box(digits_x, table_top, digit_w * 8, 18, NAVY)
txt(digits_x + digit_w * 4, table_top - 13, "金額", 10.5, white, "center", True)
for index, label in enumerate(digit_labels):
    cell(digits_x + index * digit_w, table_top - 18, digit_w, 20, label,
         NAVY, white, "center", 8.8, True, 1)


def group_row(top_y, label, fill, color):
    cell(x0, top_y, 522, 19, label, fill, color, "left", 9.2, True, 10)


def amount_row(top_y, number, item, amount, currency, negative, fill, item_color=TEXT):
    color = item_color
    sign = "-" if negative else ""
    symbol = "¥" if currency == "CNY" else "$"
    shown = f"{sign}{symbol} {abs(amount):,.2f}"
    cell(x0, top_y, seq_w, 22, str(number), fill, color, "center", 9.1)
    cell(x0 + seq_w, top_y, item_w, 22, item, fill, color, "left", 8.6)
    cell(x0 + seq_w + item_w, top_y, due_w, 22, shown, fill, color, "center", 9.0)
    for index, digit in enumerate(digits(amount)):
        cell(digits_x + index * digit_w, top_y, digit_w, 22, digit,
             fill, color, "center", 8.8)


y = table_top - 38
group_row(y, "港幣 HKD", HKD, NAVY)
y -= 19
hkd_rows = [
    (1, "車輛總價（已收）", 36000, "HKD", True, HKD, RED),
    (2, "過戶", 1500, "HKD", False, HKD, NAVY),
    (3, "保險", 4068, "HKD", False, HKD, NAVY),
    (4, "牌費", 4000, "HKD", False, HKD, NAVY),
    (5, "驗車費", 1500, "HKD", False, HKD, NAVY),
    (6, "告票", 4620, "HKD", False, HKD, NAVY),
    (7, "舊車通車費用", 5000, "HKD", True, HKD, RED),
]
for row in hkd_rows:
    amount_row(y, *row)
    y -= 22

# Today's payable
box(x0, y, 522, 35, YELLOW)
txt(x0 + 12, y - 23, "您今日需付：", 12, NAVY, "left", True)
txt(x0 + 238, y - 23, "$ 10,688.00", 12, NAVY, "center", True)
y -= 35

txt(x0, y - 17, "金額說明：", 7.8, NAVY, "left", True)
txt(x0 + 60, y - 17,
    "負數表示已付款或扣減。本單全部款項均為港幣，無需進行跨幣種換算。",
    7.05, TEXT)
y -= 31
y -= 16

# Account details retained from the fixed template
left_x, right_x = x0, x0 + 261
label_w, value_w, row_h = 78, 183, 22
mainland = [
    ("大陆收款账户", "陈振耀"),
    ("开户银行", "工商银行"),
    ("收款账号", "2009020501023937427"),
    ("网点号", "0205"),
    ("名称", "汕尾海丰东门头支行"),
    ("地址", "海丰县城人民中路7号"),
    ("电话", "0660-6623712"),
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
account_row_heights = [20, 28, 20, 20, 20, 20, 20]
account_offset = 0
for row_index in range(7):
    left_label, left_value = mainland[row_index]
    right_label, right_value = hongkong[row_index]
    current_top = y - account_offset
    current_height = account_row_heights[row_index]
    cell(left_x, current_top, label_w, current_height, left_label,
         RMB, NAVY, "center", 7.2, True, 2)
    cell(left_x + label_w, current_top, value_w, current_height, left_value,
         white, TEXT, "left", 7.25, False, 6)
    if right_label:
        cell(right_x, current_top, label_w, current_height, right_label,
             RMB, NAVY, "center", 7.0, True, 2)
        if row_index == 1:
            box(right_x + label_w, current_top, value_w, current_height, white)
            txt(right_x + label_w + 5, current_top - 12,
                "CHINA STAR RESOURCE", 6.4, TEXT)
            txt(right_x + label_w + 5, current_top - 25,
                "DEVELOPMENT LIMITED", 6.4, TEXT)
        else:
            cell(right_x + label_w, current_top, value_w, current_height, right_value,
                 white, TEXT, "left", 7.15, False, 5)
    account_offset += current_height

txt(W / 2, 10, "明哥中港牌  MING GE CROSS BORDER", 8, GRAY, "center")
c.showPage()
c.save()
print(OUT)
