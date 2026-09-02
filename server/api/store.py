# -*- coding: utf-8 -*-
"""SQLite：合约编号流水（预约制：分配即落库）+ 生成历史。

并发模型：
- 进程内：threading.Lock 串行化取号；
- 跨进程：BEGIN IMMEDIATE 取库级写锁串行；
- 取号后立刻写入 pending 占位，生成完成 confirm（ok/failed）、失败 release，
  从根上关闭"取号到落库之间几十秒生成窗口"的并发重复。
"""
import contextlib
import os
import sqlite3
import threading
import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT_DIR = os.path.join(DATA_DIR, "out")
DB_PATH = os.path.join(DATA_DIR, "contracts.db")

_lock = threading.Lock()

PENDING_STALE_MIN = 15  # 崩溃残留占位的清扫阈值


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextlib.contextmanager
def _conn(immediate: bool = False):
    """连接上下文：immediate=True 时显式开启写锁事务（预约用），
    否则保留默认提交/回滚语义。连接总是被显式关闭。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        if immediate:
            c.isolation_level = None
            c.execute("BEGIN IMMEDIATE")
        with c:
            yield c
    finally:
        c.close()


def init():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS gens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            no TEXT UNIQUE,
            type TEXT,
            client TEXT,
            mode TEXT,
            currency TEXT,
            filename TEXT,
            status TEXT,
            created_at TEXT
        )""")


def reserve_no() -> str:
    """YYYYMMDD + 当日3位流水（>999 自动4位）。分配并立刻写入 pending 占位。

    取号基于当日**最大号 + 1**（不回补低位空号，杜绝与历史号重复）；
    同时清扫超过阈值仍未 confirm 的崩溃残留 pending。
    """
    today = datetime.date.today().strftime("%Y%m%d")
    stale_before = (datetime.datetime.now()
                    - datetime.timedelta(minutes=PENDING_STALE_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    with _lock, _conn(immediate=True) as c:
        c.execute("DELETE FROM gens WHERE status='pending' AND created_at < ?", (stale_before,))
        row = c.execute(
            "SELECT no FROM gens WHERE no LIKE ? ORDER BY no DESC LIMIT 1", (today + "%",)
        ).fetchone()
        seq = 1
        if row:
            suffix = row["no"][len(today):]
            if suffix.isdigit():
                seq = int(suffix) + 1
        while True:
            no = f"{today}{seq:03d}"
            if not c.execute("SELECT 1 FROM gens WHERE no=?", (no,)).fetchone():
                break
            seq += 1
        c.execute(
            "INSERT INTO gens(no,type,client,mode,currency,filename,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (no, "", "", "", "", "", "pending", _now()),
        )
        return no


def confirm_no(no: str, type_key: str, client: str, mode: str, currency: str,
               filename: str, status: str = "ok"):
    """生成流程结束：把 pending 占位升级为正式记录（ok/failed）。"""
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE gens SET type=?,client=?,mode=?,currency=?,filename=?,status=?,created_at=? "
            "WHERE no=?",
            (type_key, client, mode, currency, filename, status, _now(), no),
        )
        if cur.rowcount == 0:  # 占位意外缺失：补记，保证编号不悬空
            c.execute(
                "INSERT INTO gens(no,type,client,mode,currency,filename,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (no, type_key, client, mode, currency, filename, status, _now()),
            )


def release_no(no: str):
    """生成失败：删除 pending 占位（号码不回收复用，走最大号+1继续递增）。"""
    with _lock, _conn() as c:
        c.execute("DELETE FROM gens WHERE no=? AND status='pending'", (no,))


def get_gen(no: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM gens WHERE no=?", (no,)).fetchone()
        return dict(row) if row else None


def history(limit: int = 50):
    """最近生成记录；pending 占位不对外展示。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT no,type,client,mode,currency,filename,status,created_at FROM gens "
            "WHERE status IN ('ok','failed') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
