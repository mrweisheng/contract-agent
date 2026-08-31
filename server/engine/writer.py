# -*- coding: utf-8 -*-
"""
docx 落盘执行器：所有修改都在原模板副本上做最小化编辑，
继承原有 run 格式（字体/字号/加粗/颜色），保证排版零变化。
"""
import copy
import re
from docx import Document

BLANK_RE = re.compile(r"_{2,}")


# ---------------- 段落级操作 ----------------

def para_text(p) -> str:
    return "".join(r.text for r in p.runs)


def replace_in_paragraph(p, old: str, new: str) -> bool:
    """跨 run 查找替换：新文本放入首个受影响 run（继承其格式）。"""
    full = "".join(r.text for r in p.runs)
    idx = full.find(old)
    if idx < 0:
        return False
    pos = 0
    first = True
    for r in p.runs:
        rs, re_ = pos, pos + len(r.text)
        pos = re_
        if re_ <= idx or rs >= idx + len(old):
            continue
        pre = r.text[: max(0, idx - rs)]
        post = r.text[max(0, min(len(r.text), idx + len(old) - rs)):]
        if first:
            r.text = pre + new + post
            first = False
        else:
            r.text = pre + post
    return True


def fill_blanks_in_paragraph(p, values) -> int:
    """按顺序把段落中连续下划线空位替换为 values（日期空「____年__月__日」即三空）。"""
    n = 0
    for v in values:
        full = "".join(r.text for r in p.runs)
        m = BLANK_RE.search(full)
        if not m:
            break
        _splice(p, m.start(), m.end(), str(v))
        n += 1
    return n


def _splice(p, start: int, end: int, new: str):
    pos = 0
    first = True
    for r in p.runs:
        rs, re_ = pos, pos + len(r.text)
        pos = re_
        if re_ <= start or rs >= end:
            continue
        pre = r.text[: max(0, start - rs)]
        post = r.text[max(0, min(len(r.text), end - rs)):]
        if first:
            r.text = pre + new + post
            first = False
        else:
            r.text = pre + post


def set_paragraph_text(p, text: str):
    """整段替换文字，保留格式：写入首个非空 run，清空其余。"""
    runs = [r for r in p.runs]
    if not runs:
        p.add_run(text)
        return
    target = None
    for r in runs:
        if target is None and r.text:
            target = r
        else:
            r.text = ""
    if target is None:
        runs[0].text = text
    else:
        target.text = text


def find_paragraph(doc, contains: str):
    for p in doc.paragraphs:
        if contains in p.text:
            return p
    return None


def _is_heading(p, no: str) -> bool:
    t = p.text.strip()
    return bool(re.match(rf"^{no}[\s　]", t)) or t.startswith(no)


def section_range(doc, sec_no: str, next_no: str):
    """返回（起始下标, 结束下标）之间的正文段落（不含标题）。"""
    start = end = None
    paras = doc.paragraphs
    for i, p in enumerate(paras):
        if start is None and _is_heading(p, sec_no):
            start = i + 1
            continue
        if start is not None and _is_heading(p, next_no):
            end = i
            break
    if start is None:
        raise ValueError(f"找不到条款 {sec_no} 标题")
    if end is None:
        end = len(paras)
    return start, end


def rewrite_section(doc, sec_no: str, next_no: str, texts):
    """把条款区段落数量调整为 len(texts) 并逐段写入文字（克隆/删除保持格式）。"""
    start, end = section_range(doc, sec_no, next_no)
    paras = doc.paragraphs
    cur = paras[start:end]
    n_need = len(texts)
    n_have = len(cur)
    if n_need > n_have:
        last = cur[-1]._p
        for _ in range(n_need - n_have):
            new_p = copy.deepcopy(last)
            last.addnext(new_p)
            last = new_p
    elif n_need < n_have:
        for p in cur[n_need:]:
            p._p.getparent().remove(p._p)
    # 重新抓取（索引已变）
    start2, end2 = section_range(doc, sec_no, next_no)
    for p, t in zip(doc.paragraphs[start2:end2], texts):
        set_paragraph_text(p, t)
    return len(texts)


# ---------------- 表格级操作 ----------------

def iter_tables(doc):
    return list(doc.tables)


def find_table(doc, anchor: str):
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                if anchor in c.text:
                    return t
    return None


def cell_text(cell) -> str:
    return cell.text.strip()


def set_cell_text(cell, text: str):
    """单元格写文字（首个段落），保留原格式。"""
    p = cell.paragraphs[0]
    set_paragraph_text(p, text)
    # 单元格可能有多个段落，多余段落清空（模板单元格均为单段）
    for extra in cell.paragraphs[1:]:
        set_paragraph_text(extra, "")


def clone_row(table, src_idx: int):
    """克隆第 src_idx 行（含格式）追加到表尾，返回新行。"""
    src_tr = table.rows[src_idx]._tr
    new_tr = copy.deepcopy(src_tr)
    # 去掉克隆行的 paraId 重复
    for el in new_tr.iter():
        for attr in list(el.attrib):
            if attr.endswith("}paraId") or attr.endswith("}textId"):
                del el.attrib[attr]
    table._tbl.append(new_tr)
    return table.rows[-1]


def delete_row(table, idx: int):
    tr = table.rows[idx]._tr
    tr.getparent().remove(tr)


def row_label(row) -> str:
    return row.cells[0].text.strip()


# ---------------- 日期工具 ----------------

def iso_date_parts(iso: str):
    y, m, d = iso.split("-")
    return y, str(int(m)), str(int(d))


def date_cn(iso: str) -> str:
    y, m, d = iso_date_parts(iso)
    return f"{y}年{m}月{d}日"


def today_cn():
    import datetime
    t = datetime.date.today()
    return f"{t.year}年{t.month}月{t.day}日"


_CN_SEQ = "零一二三四五六七八九"


def seq_cn(i: int) -> str:
    if 1 <= i <= 10:
        return "一二三四五六七八九十"[i - 1]
    if i < 20:
        return "十" + (_CN_SEQ[i % 10] if i % 10 else "")
    if i < 100:
        t, u = divmod(i, 10)
        return _CN_SEQ[t] + "十" + (_CN_SEQ[u] if u else "")
    return str(i)
