# -*- coding: utf-8 -*-
"""SQLite：合约编号流水（原子分配）+ 生成历史。"""
import os
import sqlite3
import threading
import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT_DIR = os.path.join(DATA_DIR, "out")
DB_PATH = os.path.join(DATA_DIR, "contracts.db")

_lock = threading.Lock()


def _conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


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


def next_no() -> str:
    """YYYYMMDD + 当日3位流水（>999 自动4位）。服务端原子分配。"""
    with _lock:
        today = datetime.date.today().strftime("%Y%m%d")
        with _conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM gens WHERE no LIKE ?", (today + "%",)
            ).fetchone()
            seq = row["n"] + 1
            while True:
                no = f"{today}{seq:03d}"
                dup = c.execute("SELECT 1 FROM gens WHERE no=?", (no,)).fetchone()
                if not dup:
                    return no
                seq += 1


def save_gen(no: str, type_key: str, client: str, mode: str, currency: str,
             filename: str, status: str = "ok"):
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO gens(no,type,client,mode,currency,filename,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (no, type_key, client, mode, currency, filename, status,
                 datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )


def update_status(no: str, status: str):
    with _conn() as c:
        c.execute("UPDATE gens SET status=? WHERE no=?", (status, no))


def get_gen(no: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM gens WHERE no=?", (no,)).fetchone()
        return dict(row) if row else None


def history(limit: int = 50):
    with _conn() as c:
        rows = c.execute(
            "SELECT no,type,client,mode,currency,filename,status,created_at FROM gens ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
