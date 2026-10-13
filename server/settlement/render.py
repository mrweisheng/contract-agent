#!/usr/bin/env python3
"""收款结算单渲染引擎。

输入一份 spec JSON，输出一页 PDF（可选同时输出 220 DPI PNG）。
版式、配色、账户区、金额分位栏全部固化在此，调用方只提供业务数据。

用法：
    python settlement_engine.py spec.json [--png] [--out-dir DIR]
    cat spec.json | python settlement_engine.py - --png
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PKG = Path(__file__).resolve().parent

# 字体按「环境变量 → 系统字体 → 包内自带字体」顺序解析，换机器也能跑。
# 首选仍是 macOS 的 Arial Unicode（版式定稿就是按它量的字宽），不要主动降级。
# Windows 首选 msyh：simhei 缺半角「¥」字形（renderlab 落 .notdef 方框，2026-10-12 实测），
# msyh 注册与字形都正常；.ttc 注册失败会自动退到下一个候选。
FONT_CANDIDATES = (
    Path(os.environ["SETTLEMENT_FONT"]) if os.environ.get("SETTLEMENT_FONT") else None,
    # macOS：版式定稿就是按 Arial Unicode 量的字宽，优先
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    # Windows：msyh 优先（有 ¥ 字形），注册失败再退纯 TTF
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhl.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simkai.ttf"),
    # Linux
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    # 包内自带：任何系统都兜底
    *(sorted((PKG / "assets/fonts").glob("*.[to]tf"))
      if (PKG / "assets/fonts").is_dir() else []),
)


def resolve_font() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError(
        "找不到可用的中文字体。请把一个 .ttf/.ttc/.otf 中文字体放到 "
        f"{PKG / 'assets/fonts'} 下，或用环境变量 SETTLEMENT_FONT=<字体路径> 指定。"
    )


FONT_PATH = str(resolve_font())
LOGO_CANDIDATES = (
    PKG / "assets/明哥中港牌-logo.png",
    PKG / "assets/ming-ge-cross-border-logo-v1.png",
)

NAVY = HexColor("#0B2E59")
RMB_FILL = HexColor("#EAF3FA")
ACC_FILL = HexColor("#F2F8FC")
HKD_FILL = HexColor("#E8F5F2")
TEXT = HexColor("#1D2733")
GRAY = HexColor("#687386")
NOTE_GRAY = HexColor("#9AA3B0")
BORDER = HexColor("#CBD8E5")
TABLE_BORDER = HexColor("#9FB4C9")
ACC_BORDER = HexColor("#DEE7F0")
RED = HexColor("#C62828")
YELLOW = HexColor("#FFF1B8")
NEXT_BLUE = HexColor("#8FA6BF")
GIFT_GREEN = HexColor("#2E7955")
GIFT_BG = HexColor("#E6F4EA")
NET_FILL = HexColor("#D9E7F8")

FILLS = {"CNY": RMB_FILL, "HKD": HKD_FILL}
SYMBOLS = {"CNY": "¥", "HKD": "$"}

# 字号已含“相对初版累计放大四号”的增量，不要再叠加。
S_TITLE = 26.0
S_SUB = 13.5
S_DATE = 12.5
S_META = 13.1
S_HEAD_SEQ = 14.5
S_HEAD = 14.5
S_DIGIT_LABEL = 12.4
S_GROUP = 13.2
S_ITEM = 12.6
S_AMOUNT = 13.0
S_DIGIT = 12.8
S_NOTE = 10.2
S_TODAY = 16.0
S_AMTNOTE_LABEL = 11.8
S_AMTNOTE = 11.0
S_ACC_LABEL = 11.2
S_ACC_VALUE = 11.2
S_ACC_VALUE_SMALL = 10.4
S_FOOTER = 12.0

PAGE_W, PAGE_H = letter
X0 = 45.0
TABLE_W = 522.0
META_TOP = 655.0
# 列宽（淇淇 2026-10-09 按实测字宽定）：标签列收窄、群名值列加宽到可容纳
# 一个完整群名（含车牌，「0328 罗总一仔大桥新办粤Z9W89」实测 192.9pt）。
# 目的：做到「一行一个群名」，字号、配色、边框一律不变。
META_W = (70.0, 172.0, 66.0, 214.0)
META_H = 29.0
# 顶部信息栏铁律（淇淇 2026-10-09）：字段过长时**折行**，字号 S_META 不许缩小。
# 含「、」等多个群名时先按分隔符分段，一段一行。
META_LINE_H = 15.5
META_PAD_Y = 9.0
META_GAP = 11.0
TABLE_TOP = 586.0
HEAD_H = 38.0
SEQ_W, ITEM_W, DUE_W = 34.0, 168.0, 90.0
DIGIT_W = 28.75
DIGITS_X = X0 + SEQ_W + ITEM_W + DUE_W
DIGIT_LABELS = ["十萬", "萬", "千", "百", "十", "元", "角", "分"]
GROUP_H = 19.0
NOTE_H = 36.0
NOTE_LINE_H = 15.0
NOTE_PAD = 9.0
TODAY_H = 35.0
AMTNOTE_H = 31.0
AMTNOTE_GAP = 16.0
ACC_LEFT, ACC_RIGHT = X0, X0 + 261.0
ACC_LABEL_W, ACC_VALUE_W = 78.0, 183.0
ACC_ROW_H = (20.0, 28.0, 20.0, 20.0, 20.0, 20.0, 20.0)
BOTTOM_LIMIT = 24.0

MAINLAND_ACCOUNT = (
    ("大陆收款账户", "陈振耀"),
    ("开户银行", "工商银行"),
    ("收款账号", "2009020501023937427"),
    ("网点号", "0205"),
    ("名称", "汕尾海丰东门头支行"),
    ("地址", "海丰县城人民中路7号"),
    ("电话", "0660-6623712"),
)
HK_ACCOUNT = (
    ("香港收款帳戶", "華星資源開發有限公司"),
    ("英文名稱", "CHINA STAR RESOURCE DEVELOPMENT LIMITED"),
    ("開戶銀行", "華僑銀行"),
    ("收款帳號", "035-802-129-690-051"),
    ("轉數快識別碼", "131-831-406"),
    ("", ""),
    ("", ""),
)
HK_ENGLISH_LINES = ("CHINA STAR RESOURCE", "DEVELOPMENT LIMITED")

STATUS_COLORS = {"paid": RED, "next": NEXT_BLUE, "today": NAVY, "normal": NAVY,
                 "gift": GIFT_GREEN}


def register_font() -> str:
    """逐个候选字体试注册，成功即用。

    Windows 的 .ttc（msyh / simsun）并非所有 reportlab 版本都能直接读，
    注册失败要自动退到下一个候选，而不是整单崩掉。
    """
    if "CJK" in pdfmetrics.getRegisteredFontNames():
        return FONT_PATH
    tried = []
    for candidate in FONT_CANDIDATES:
        if not candidate or not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJK", str(candidate)))
            return str(candidate)
        except Exception as exc:  # noqa: BLE001 - 字体不可用时继续试下一个
            tried.append(f"{candidate}（{exc}）")
    raise FileNotFoundError(
        "找不到可注册的中文字体。已尝试：" + ("；".join(tried) or "无")
        + "。请把一个 .ttf/.otf 中文字体放进 "
        f"{PKG / 'assets/fonts'}，或用环境变量 SETTLEMENT_FONT=<字体路径> 指定。"
    )


def text_width(value: str, size: float) -> float:
    return pdfmetrics.stringWidth(value, "CJK", size)


def fit_size(value: str, size: float, max_width: float, min_size: float = 8.0) -> float:
    """按栏宽自动缩字号，替代人工看图判断截断。"""
    if not value:
        return size
    while size > min_size and text_width(value, size) > max_width:
        size -= 0.2
    return size


def money(amount: float, currency: str) -> str:
    sign = "-" if amount < 0 else ""
    return f"{sign}{SYMBOLS.get(currency, '$')} {abs(amount):,.2f}"


def split_digits(amount: float) -> list:
    """金额分位：十万/万/千/百/十/元/角/分，去掉左侧无意义前导 0。"""
    cents = int(round(abs(amount) * 100))
    values = list(f"{cents:08d}"[-8:])
    first = next((i for i, d in enumerate(values[:6]) if d != "0"), 6)
    for i in range(first):
        values[i] = ""
    return values


def wrap_text(text: str, size: float, max_width: float) -> list:
    """按实际字宽折行（备注可能很长，绝不能画出表格被截断）。"""
    lines, cur = [], ""
    for ch in str(text):
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if cur and pdfmetrics.stringWidth(cur + ch, "CJK", size) > max_width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur or not lines:
        lines.append(cur)
    return lines


def wrap_hanging(text: str, size: float, first_width: float, rest_width: float) -> list:
    """悬挂式折行：首行从标签后起（窄），续行用满宽，避免末行孤字。"""
    lines, cur, width = [], "", first_width
    for ch in str(text):
        if ch == "\n":
            lines.append(cur)
            cur = ""
            width = rest_width
            continue
        if cur and pdfmetrics.stringWidth(cur + ch, "CJK", size) > width:
            lines.append(cur)
            cur = ch
            width = rest_width
        else:
            cur += ch
    if cur or not lines:
        lines.append(cur)
    return lines


def split_cell_lines(text: str, max_width: float, size: float = S_META) -> list:
    """顶部信息栏字段折行：先按「、」等分隔符分段（一段一行），段内再按实际字宽折行。

    字号始终为 size，不缩字；调用方可据此算出每格需要几行。
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[、,，;；]\s*", raw) if p.strip()]
    lines: list = []
    for part in parts:
        lines.extend(wrap_text(part, size, max_width))
    return lines


def meta_layout(spec: dict) -> tuple:
    """算顶部信息栏每行高度与表格起始位置。

    字段过长时格子按行数变高，字号不变（淇淇 2026-10-09 指定），
    表格区整体顺延，避免两组信息重叠。
    """
    meta = spec.get("meta", [])
    heights: list = []
    for row in meta:
        count = 1
        for i, value in enumerate(row):
            lines = split_cell_lines(value, META_W[i] - 14.0)
            count = max(count, len(lines) or 1)
        heights.append(max(META_H, count * META_LINE_H + META_PAD_Y))
    total = sum(heights)
    table_top = META_TOP - total - META_GAP if heights else TABLE_TOP
    return heights, table_top


def plan_layout(spec: dict) -> dict:
    """按可用高度选行高与尾部间距，放不下则标记 overflow。"""
    sections = spec.get("sections", [])
    row_count = sum(len(s.get("rows", [])) for s in sections)
    # v2 排版（2026-10-13 淇淇批准）：币种内按 合同內款項/合同外雜費 再分条带；
    # 旧 spec（无 block 标记）退回每币种一条带，渲染层走 legacy 分支。
    legacy_bands = not any(r.get("block") for s in sections for r in s.get("rows", []))
    if legacy_bands:
        group_count = len(sections)
    else:
        group_count = sum(
            len({r.get("block", "contract") for r in s.get("rows", [])})
            for s in sections)
    amtnote_text = " ".join(
        t for t in (spec.get("amount_note", ""), spec.get("note") or "") if t
    )
    amtnote_lines = (wrap_hanging(amtnote_text, S_AMTNOTE,
                                  TABLE_W - 60.0, TABLE_W - 12.0)
                     if amtnote_text else [])
    amtnote_h = max(31.0, len(amtnote_lines) * 15.0 + 16.0)
    meta_heights, table_top = meta_layout(spec)
    available = table_top - BOTTOM_LIMIT
    accounts_h = sum(ACC_ROW_H)
    warnings: list[str] = []

    chosen = None
    for row_h in (22.0, 21.0, 20.0, 19.0, 18.0, 17.0, 16.0):
        for gap in (AMTNOTE_GAP, 8.0, 0.0):
            needed = (
                HEAD_H
                + group_count * GROUP_H
                + row_count * row_h
                + TODAY_H
                + amtnote_h
                + gap
                + accounts_h
            )
            if needed <= available:
                chosen = {"row_height": row_h, "tail_gap": gap, "needed": needed}
                break
        if chosen:
            break

    if chosen is None:
        chosen = {"row_height": 16.0, "tail_gap": 0.0, "needed": available + 1}
        warnings.append(
            f"版式溢出：共 {row_count} 个明细行，最小行高仍放不下，"
            "需要拆分为两张单据或删减合并明细行。"
        )
    elif chosen["row_height"] < 22.0:
        warnings.append(
            f"行高已自动压缩至 {chosen['row_height']:.0f}，明细共 {row_count} 行；"
            "如仍显拥挤，建议合并同类明细行。"
        )
    chosen["amtnote_lines"] = amtnote_lines
    chosen["amtnote_h"] = amtnote_h
    chosen["meta_heights"] = meta_heights
    chosen["table_top"] = table_top
    chosen["legacy_bands"] = legacy_bands
    chosen["warnings"] = warnings
    return chosen


class Renderer:
    def __init__(self, spec: dict, layout: dict):
        self.spec = spec
        self.layout = layout
        self.warnings: list[str] = list(layout["warnings"])
        self.row_h = layout["row_height"]
        self.table_top = layout.get("table_top", TABLE_TOP)
        self.meta_heights = layout.get("meta_heights") or []
        self.canvas = None

    # primitives
    def txt(self, x, y, value, size, color=TEXT, align="left", bold=False):
        if bold:
            size += 0.55
        self.canvas.setFillColor(color)
        self.canvas.setFont("CJK", size)
        if align == "center":
            self.canvas.drawCentredString(x, y, value)
        elif align == "right":
            self.canvas.drawRightString(x, y, value)
        else:
            self.canvas.drawString(x, y, value)

    def box(self, x, top, width, height, fill=white, stroke=BORDER):
        self.canvas.setFillColor(fill)
        self.canvas.setStrokeColor(stroke)
        self.canvas.setLineWidth(0.6)
        self.canvas.rect(x, top - height, width, height, fill=1, stroke=1)

    def cell(self, x, top, width, height, value, fill=white, color=TEXT,
             align="left", size=S_META, bold=False, pad=7.0, autoshrink=True,
             stroke=None):
        self.box(x, top, width, height, fill, stroke or BORDER)
        if not value:
            return
        usable = width - pad * 2
        size = fit_size(str(value), size, usable) if autoshrink else size
        px = x + pad if align == "left" else (x + width / 2 if align == "center" else x + width - pad)
        self.txt(px, top - height / 2 - size * 0.36, value, size, color, align, bold)

    # blocks
    def draw_header(self):
        logo = next((p for p in LOGO_CANDIDATES if p.exists()), None)
        if logo is None:
            self.warnings.append("未找到 Logo 文件，标题区已留空。")
        else:
            self.canvas.drawImage(ImageReader(str(logo)), 20, 700, width=235, height=94,
                                  preserveAspectRatio=True, mask="auto")
        self.txt(565, 748, self.spec.get("subtitle", "SETTLEMENT STATEMENT"),
                 S_SUB, GRAY, "right", True)
        self.txt(565, 714, self.spec.get("title", "收款結算單"), S_TITLE, NAVY, "right", True)
        date = self.spec.get("date", "")
        if date:
            self.txt(565, 681, f"日期  {date}", S_DATE, GRAY, "right")

    def draw_meta(self):
        """顶部信息栏：字段过长时折行、格子变高，字号保持 S_META 不缩小。

        群名等多个值先按「、」分段，一段一行（淇淇 2026-10-09 指定）。
        """
        meta = self.spec.get("meta", [])
        top = META_TOP
        for r, row in enumerate(meta):
            height = self.meta_heights[r] if r < len(self.meta_heights) else META_H
            x = X0
            for i, value in enumerate(row):
                is_label = i in (0, 2)
                width = META_W[i]
                if is_label:
                    self.cell(x, top, width, height, value,
                              NAVY, white, "center", S_META, True)
                else:
                    self.box(x, top, width, height, white, BORDER)
                    lines = split_cell_lines(value, width - 14.0)
                    self.draw_meta_lines(x + 7.0, top, height, lines)
                x += width
            top -= height

    def draw_meta_lines(self, x, top, height, lines):
        if not lines:
            return
        block = (len(lines) - 1) * META_LINE_H
        first = top - height / 2.0 + block / 2.0 - S_META * 0.36
        for i, line in enumerate(lines):
            self.txt(x, first - i * META_LINE_H, line, S_META, TEXT)

    def draw_table_head(self):
        t = self.table_top
        self.cell(X0, t, SEQ_W, HEAD_H, "序號", NAVY, white, "center", S_HEAD_SEQ, True, stroke=TABLE_BORDER)
        self.cell(X0 + SEQ_W, t, ITEM_W, HEAD_H, "收款項目", NAVY, white, "center", S_HEAD, True, stroke=TABLE_BORDER)
        self.cell(X0 + SEQ_W + ITEM_W, t, DUE_W, HEAD_H, "應收金額", NAVY, white, "center", S_HEAD, True, stroke=TABLE_BORDER)
        self.box(DIGITS_X, t, DIGIT_W * 8, 18, NAVY)
        self.txt(DIGITS_X + DIGIT_W * 4, t - 13, "金額", S_HEAD, white, "center", True)
        for i, label in enumerate(DIGIT_LABELS):
            self.cell(DIGITS_X + i * DIGIT_W, t - 18, DIGIT_W, 20, label,
                      NAVY, white, "center", S_DIGIT_LABEL, True, 1, stroke=TABLE_BORDER)

    def draw_sections(self):
        y = self.table_top - HEAD_H
        self.seq = 0
        legacy = bool(self.layout.get("legacy_bands"))
        for section in self.spec.get("sections", []):
            currency = section.get("currency", "HKD")
            fill = FILLS.get(currency, HKD_FILL)
            label = section.get("label") or ("人民幣 CNY" if currency == "CNY" else "港幣 HKD")
            rows = section.get("rows", [])
            if legacy or not any(r.get("block") for r in rows):
                y = self.draw_band(y, label, fill, rows, currency)
                continue
            for block, title in (("contract", "合同內款項"), ("extra", "合同外雜費")):
                part = [r for r in rows if r.get("block", "contract") == block]
                if part:
                    y = self.draw_band(y, f"{title} · {label}", fill, part, currency)
        return y

    def draw_band(self, y, label, fill, rows, currency):
        self.cell(X0, y, TABLE_W, GROUP_H, label, fill, NAVY, "left", S_GROUP, True, 10, stroke=TABLE_BORDER)
        y -= GROUP_H
        for row in rows:
            # 已付/减免行不占序号：读作「減」而不是又一笔收费（淇淇 2026-10-13）
            is_ded = row.get("status") == "paid" and float(row.get("amount", 0)) < 0
            if is_ded:
                seq = ""
            else:
                self.seq += 1
                seq = str(self.seq)
            self.draw_amount_row(y, seq, row, currency, fill, is_ded)
            y -= self.row_h
        return y

    def draw_item_cell(self, top, fill, item, color, status, bold=False):
        """项目格：赠送行画〔贈送〕圆角标签，超宽自动缩字。"""
        x = X0 + SEQ_W
        self.box(x, top, ITEM_W, self.row_h, fill, TABLE_BORDER)
        size = S_ITEM
        avail = ITEM_W - 14.0
        if status == "gift":
            tag_w = pdfmetrics.stringWidth("贈送", "CJK", 8.2) + 9.0
            size = fit_size(item, size, avail - tag_w - 5.0)
            px = x + 7.0
            self.txt(px, top - self.row_h / 2 - size * 0.36, item, size, color, "left", bold)
            cy = top - self.row_h / 2
            ix = px + (pdfmetrics.stringWidth(item, "CJK", size) if item else 0) + 6.0
            self.canvas.setFillColor(GIFT_BG)
            self.canvas.setStrokeColor(GIFT_GREEN)
            self.canvas.setLineWidth(0.7)
            self.canvas.roundRect(ix, cy - 6.5, tag_w, 13, 6.5, fill=1, stroke=1)
            self.txt(ix + tag_w / 2, cy - 8.2 * 0.36, "贈送", 8.2, GIFT_GREEN, "center", True)
        else:
            self.txt(x + 7.0, top - self.row_h / 2 - size * 0.36, item, size, color, "left", bold)

    def draw_amount_row(self, top, seq, row, currency, fill, is_ded=False):
        amount = float(row.get("amount", 0))
        status = row.get("status", "normal")
        color = STATUS_COLORS.get(status, NAVY)
        override_color = row.get("color")
        if override_color:
            color = HexColor(override_color)
        # blank＝模板稿行：项目列出、金额与分位栏整体留白（预览专用，正式单不会出现）
        blank = bool(row.get("blank"))
        shown = "" if blank else (row.get("display") or money(amount, currency))
        item = row.get("item", "")
        # 合同内本次应收＝小计行：浅蓝底加粗+顶部粗线，读作「净额」而不是又一笔
        # （粗线在格子之后画，否则被单元格填充盖住）
        net = row.get("block") == "contract" and status == "today"
        row_fill = NET_FILL if net else fill
        self.cell(X0, top, SEQ_W, self.row_h, seq, row_fill, color, "center", S_ITEM, stroke=TABLE_BORDER)
        item_shown = f"減：{item}" if is_ded else item
        self.draw_item_cell(top, row_fill, item_shown, color, status, bold=net)
        self.cell(X0 + SEQ_W + ITEM_W, top, DUE_W, self.row_h, shown, row_fill, color,
                  "center", S_AMOUNT, bold=net, stroke=TABLE_BORDER)
        digits = [""] * len(DIGIT_LABELS) if blank else split_digits(amount)
        for i, digit in enumerate(digits):
            self.cell(DIGITS_X + i * DIGIT_W, top, DIGIT_W, self.row_h, digit,
                      row_fill, color, "center", S_DIGIT, bold=net, stroke=TABLE_BORDER)
        if net:
            self.canvas.setStrokeColor(NAVY)
            self.canvas.setLineWidth(1.1)
            self.canvas.line(X0, top, X0 + TABLE_W, top)

    def draw_amount_note(self, y):
        lines = self.layout.get("amtnote_lines") or []
        h = self.layout.get("amtnote_h", AMTNOTE_H)
        self.txt(X0, y - 17, "備註：", S_AMTNOTE_LABEL, NAVY, "left", True)
        for i, line in enumerate(lines):
            tx = (X0 + 50) if i == 0 else X0
            self.txt(tx, y - 17 - i * 15.0, line, S_AMTNOTE, NOTE_GRAY)
        return y - h - self.layout["tail_gap"]

    def draw_today_pay(self, y):
        pay = self.spec.get("today_pay") or {}
        cny = pay.get("cny")
        hkd = pay.get("hkd")
        self.box(X0, y, TABLE_W, TODAY_H, YELLOW, TABLE_BORDER)
        self.txt(X0 + 12, y - 23, "您今日需付：", S_TODAY, NAVY, "left", True)
        if cny and hkd:
            self.txt(X0 + 150, y - 23, cny, S_TODAY, NAVY, "left", True)
            self.txt(X0 + 330, y - 23, hkd, S_TODAY, NAVY, "left", True)
            # 铁律（淇淇 2026-10-09 强调）：只要同时有人民币和港币两个付款口径，
            # 中间必须画 "/" 分隔；只有调用方显式传 today_sep="" 才不画。
            sep = self.spec.get("today_sep")
            if sep is None:
                sep = "/"
            if sep:
                w = pdfmetrics.stringWidth(cny, "CJK", S_TODAY + 0.55)
                self.txt((X0 + 150 + w + X0 + 330) / 2.0, y - 23, sep,
                         S_TODAY, NAVY, "center", True)
        else:
            single = cny or hkd or ""
            self.txt(X0 + 238, y - 23, single, S_TODAY, NAVY, "center", True)
        return y - TODAY_H

    def draw_accounts(self, y):
        offset = 0.0
        for i in range(7):
            left_label, left_value = MAINLAND_ACCOUNT[i]
            right_label, right_value = HK_ACCOUNT[i]
            h = ACC_ROW_H[i]
            top = y - offset
            self.cell(ACC_LEFT, top, ACC_LABEL_W, h, left_label, ACC_FILL, NAVY,
                      "center", S_ACC_LABEL, True, 2, stroke=ACC_BORDER)
            self.cell(ACC_LEFT + ACC_LABEL_W, top, ACC_VALUE_W, h, left_value, white, TEXT,
                      "left", S_ACC_VALUE, False, 6, stroke=ACC_BORDER)
            if right_label:
                self.cell(ACC_RIGHT, top, ACC_LABEL_W, h, right_label, ACC_FILL, NAVY,
                          "center", S_ACC_LABEL - 0.2, True, 2, stroke=ACC_BORDER)
                if i == 1:
                    self.box(ACC_RIGHT + ACC_LABEL_W, top, ACC_VALUE_W, h, white, ACC_BORDER)
                    self.txt(ACC_RIGHT + ACC_LABEL_W + 5, top - 13, HK_ENGLISH_LINES[0],
                             S_ACC_VALUE_SMALL, TEXT)
                    self.txt(ACC_RIGHT + ACC_LABEL_W + 5, top - 25, HK_ENGLISH_LINES[1],
                             S_ACC_VALUE_SMALL, TEXT)
                else:
                    self.cell(ACC_RIGHT + ACC_LABEL_W, top, ACC_VALUE_W, h, right_value,
                              white, TEXT, "left", S_ACC_VALUE, False, 5, stroke=ACC_BORDER)
            offset += h

    def render(self, out_path: Path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self.canvas = canvas.Canvas(str(out_path), pagesize=letter)
        self.canvas.setTitle(self.spec.get("pdf_title") or self.spec.get("title", "收款結算單"))
        self.draw_header()
        self.draw_meta()
        self.draw_table_head()
        y = self.draw_sections()
        y = self.draw_today_pay(y)
        y = self.draw_amount_note(y)
        self.draw_accounts(y)
        self.txt(PAGE_W / 2, 10, "明哥中港牌  MING GE CROSS BORDER", S_FOOTER, GRAY, "center")
        self.canvas.showPage()
        self.canvas.save()
        return out_path


def render_png(pdf_path: Path, dpi: int = 220) -> Path:
    import pypdfium2 as pdfium

    out_dir = pdf_path.parent.parent / "image"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf_path))
    for i, page in enumerate(doc):
        suffix = f"_{i + 1}" if len(doc) > 1 else ""
        img = page.render(scale=dpi / 72).to_pil()
        target = out_dir / f"{pdf_path.stem}{suffix}.png"
        img.save(target)
    return out_dir / f"{pdf_path.stem}.png"


def build_output_path(spec: dict, out_dir: Path) -> Path:
    name = spec.get("filename")
    if not name:
        meta = spec.get("meta") or [[]]
        customer = meta[0][1] if len(meta[0]) > 1 else "客戶"
        settle_type = meta[1][3] if len(spec.get("meta", [])) > 1 and len(meta[1]) > 3 else "結算"
        name = f"{customer}_{settle_type}结算单"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return out_dir / name


def main() -> int:
    parser = argparse.ArgumentParser(description="收款结算单渲染引擎")
    parser.add_argument("spec", help="spec JSON 路径，- 表示读 stdin")
    parser.add_argument("--png", action="store_true", help="同时导出 220 DPI PNG")
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--out-dir", default=None, help="PDF 输出目录，默认 <skill>/output/pdf")
    args = parser.parse_args()

    raw = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    spec = json.loads(raw)
    register_font()

    out_dir = Path(args.out_dir) if args.out_dir else PKG / "output" / "pdf"
    pdf_path = build_output_path(spec, out_dir)

    layout = plan_layout(spec)
    renderer = Renderer(spec, layout)
    renderer.render(pdf_path)

    result = {
        "pdf": str(pdf_path),
        "row_height": layout["row_height"],
        "warnings": renderer.warnings,
        "overflow": any("溢出" in w for w in renderer.warnings),
    }
    if args.png:
        result["png"] = str(render_png(pdf_path, args.dpi))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["overflow"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
