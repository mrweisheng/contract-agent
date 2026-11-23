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
        # LLM 语义复核改为后台异步后，结果落库供历史/轮询查询（旧库增量迁移）
        # signed_path/signed_at：客户在小程序手写签名回传后的已签版存档（对外查询接口 2026-11-18）
        # bound_at：签字即绑定登录用户的时间（我的合同 2026-11-23）
        for col in ("review_status", "review_issues", "signed_path", "signed_at", "sealed_at", "bound_at"):
            try:
                c.execute(f"ALTER TABLE gens ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass  # 列已存在
        # 签署归属：signed_user_id 必须是 INTEGER——TEXT 亲和性会把绑定的 int 存成 '5'，
        # 之后 WHERE signed_user_id=? 传 int 就永远匹配不上
        try:
            c.execute("ALTER TABLE gens ADD COLUMN signed_user_id INTEGER DEFAULT NULL")
        except Exception:
            pass  # 列已存在
        c.execute("""CREATE TABLE IF NOT EXISTS fx_rate (
            base TEXT,
            quote TEXT,
            rate REAL,
            source TEXT,
            fetched_at TEXT,
            PRIMARY KEY(base, quote)
        )""")
        # 结算单历史汇率：按日快照（当日最后一次拉取），供业务选历史日期出单用
        c.execute("""CREATE TABLE IF NOT EXISTS fx_daily (
            base TEXT,
            quote TEXT,
            day TEXT,
            rate REAL,
            source TEXT,
            fetched_at TEXT,
            PRIMARY KEY(base, quote, day)
        )""")
        # 小程序用户（微信一键登录 2026-11-20）：openid 唯一定户，手机号用于关联合同客户
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            openid TEXT UNIQUE,
            unionid TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            nickname TEXT DEFAULT '',
            avatar_path TEXT DEFAULT '',
            avatar_ver INTEGER DEFAULT 0,
            created_at TEXT,
            last_login_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            expires_at TEXT
        )""")


def fx_get(base: str, quote: str):
    """最近一次缓存汇率（dict 或 None）。"""
    with _conn() as c:
        row = c.execute(
            "SELECT rate, source, fetched_at FROM fx_rate WHERE base=? AND quote=?",
            (base, quote),
        ).fetchone()
        return dict(row) if row else None


def fx_put(base: str, quote: str, rate: float, source: str):
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO fx_rate(base,quote,rate,source,fetched_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(base,quote) DO UPDATE SET rate=excluded.rate, "
            "source=excluded.source, fetched_at=excluded.fetched_at",
            (base, quote, rate, source, _now()),
        )


FX_DAILY_KEEP_DAYS = 10   # 历史汇率可选窗口：自上线起按日积累，只留最近 10 天


def fx_daily_put(base: str, quote: str, day: str, rate: float, source: str):
    """当日快照 UPSERT——同日多次拉取后写覆盖先写＝当日最后一次；顺带清窗口外旧档。"""
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO fx_daily(base,quote,day,rate,source,fetched_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(base,quote,day) DO UPDATE SET rate=excluded.rate, "
            "source=excluded.source, fetched_at=excluded.fetched_at",
            (base, quote, day, rate, source, _now()),
        )
        c.execute(
            "DELETE FROM fx_daily WHERE base=? AND quote=? "
            "AND day < date('now','localtime', ?)",
            (base, quote, f"-{FX_DAILY_KEEP_DAYS - 1} days"),
        )


def fx_daily_dates(base: str, quote: str, days: int = FX_DAILY_KEEP_DAYS) -> list:
    """最近 N 天内已有快照的日期（升序）——前端日期选择器据此置灰无数据日。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT day FROM fx_daily WHERE base=? AND quote=? "
            "AND day >= date('now','localtime', ?) ORDER BY day",
            (base, quote, f"-{days - 1} days"),
        ).fetchall()
        return [r["day"] for r in rows]


def fx_daily_map(base: str, quote: str, days: int = FX_DAILY_KEEP_DAYS) -> list:
    """最近 N 天内已有快照的日期与当日 HKD→CNY 原始汇率（升序）——
    供前端日期选择器直接展示每天汇值，业务选日之前心里有数。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT day, rate FROM fx_daily WHERE base=? AND quote=? "
            "AND day >= date('now','localtime', ?) ORDER BY day",
            (base, quote, f"-{days - 1} days"),
        ).fetchall()
        return [{"day": r["day"], "rate": r["rate"]} for r in rows]


def fx_daily_get_le(base: str, quote: str, day: str):
    """≤指定日的最近一条快照（休市/停机日沿用上一交易日报价，金融惯例）。无则 None。"""
    with _conn() as c:
        row = c.execute(
            "SELECT day, rate, source, fetched_at FROM fx_daily "
            "WHERE base=? AND quote=? AND day<=? ORDER BY day DESC LIMIT 1",
            (base, quote, day),
        ).fetchone()
        return dict(row) if row else None


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
    """最近生成记录；pending 占位不对外展示。含后台复核结论（未出为空）。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT no,type,client,mode,currency,filename,status,created_at,"
            "review_status,review_issues FROM gens "
            "WHERE status IN ('ok','failed') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def contracts_query(date_from: str = "", date_to: str = "", client: str = "",
                    type_key: str = "", limit: int = 200):
    """合同管理列表：只取生成成功的单，按生成时间倒序。

    date_from/date_to：YYYY-MM-DD，按 created_at 的日期部分比较（含边界，空=不限）；
    client：客户/签约方模糊匹配；type_key：业务类型精确匹配。
    返回 (符合条件的总条数, 当前页行) —— 总条数用于前端提示「共 N 份」。
    """
    where, args = ["status='ok'"], []
    if date_from:
        where.append("date(created_at) >= date(?)")
        args.append(date_from)
    if date_to:
        where.append("date(created_at) <= date(?)")
        args.append(date_to)
    if client:
        where.append("client LIKE ?")
        args.append(f"%{client}%")
    if type_key:
        where.append("type = ?")
        args.append(type_key)
    cond = " AND ".join(where)
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM gens WHERE {cond}", args).fetchone()[0]
        rows = c.execute(
            "SELECT no,type,client,mode,currency,filename,created_at,review_status,"
            "signed_path,signed_at,signed_user_id FROM gens WHERE " + cond +
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
        items = [dict(r) for r in rows]
        # 签署人（管理员视角）：只补昵称/手机号，空绑定则为 None
        uids = sorted({r["signed_user_id"] for r in items if r.get("signed_user_id")})
        if uids:
            marks = ",".join("?" * len(uids))
            signers = {r["id"]: dict(r) for r in c.execute(
                f"SELECT id,nickname,phone FROM users WHERE id IN ({marks})", uids)}
            for r in items:
                s = signers.get(r.get("signed_user_id"))
                r["signer_nickname"] = (s or {}).get("nickname") or ""
                r["signer_phone"] = (s or {}).get("phone") or ""
        return total, items


def set_review(no: str, review_status: str, review_issues: str):
    """后台复核完成：落库结论（pass/warn/skip），供历史与前端轮询查询。"""
    with _conn() as c:
        c.execute("UPDATE gens SET review_status=?, review_issues=? WHERE no=?",
                  (review_status, review_issues, no))


def set_signed(no: str, signed_path: str):
    """客户在小程序手写签名回传后：落已签版存档路径与时间（对外查询接口 2026-11-18）。"""
    with _lock, _conn() as c:
        c.execute("UPDATE gens SET signed_path=?, signed_at=? WHERE no=?",
                  (signed_path, _now(), no))


def bind_signed_user(no: str, uid: int) -> bool:
    """签字即认领：把已签合同绑定到签署的登录用户（我的合同 2026-11-23）。

    条件更新（signed_user_id IS NULL）保证同一份只会绑一次：并发下后到的一方
    rowcount=0，由调用方按「已被他人签走」处理，不会互相覆盖。
    """
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE gens SET signed_user_id=?, bound_at=? WHERE no=? AND signed_user_id IS NULL",
            (uid, _now(), no))
        return cur.rowcount > 0


def contracts_by_user(uid: int, limit: int = 100):
    """「我的合同」：只取绑定到该用户的已签合同，按生成时间倒序。返回 (总数, 当前页行)。"""
    with _conn() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM gens WHERE status='ok' AND signed_user_id=?",
            (uid,),
        ).fetchone()[0]
        rows = c.execute(
            "SELECT no,type,client,mode,currency,filename,created_at,signed_path,signed_at,bound_at "
            "FROM gens WHERE status='ok' AND signed_user_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
        return total, [dict(r) for r in rows]


def mark_sealed(no: str):
    """用印日志：该合同生成时已合成公司印信（图片章方案的留痕生命线）。"""
    with _lock, _conn() as c:
        c.execute("UPDATE gens SET sealed_at=? WHERE no=? AND status='ok'", (_now(), no))


# ---------- 小程序用户（微信一键登录 2026-11-20） ----------

def user_upsert_by_openid(openid: str, unionid: str = "") -> dict:
    """按 openid 定户：首登建户，老户刷新 unionid 与登录时间。"""
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM users WHERE openid=?", (openid,)).fetchone()
        if row:
            c.execute("UPDATE users SET unionid=?, last_login_at=? WHERE id=?",
                      (unionid or row["unionid"] or "", _now(), row["id"]))
            return dict(c.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone())
        cur = c.execute(
            "INSERT INTO users(openid,unionid,created_at,last_login_at) VALUES(?,?,?,?)",
            (openid, unionid, _now(), _now()),
        )
        return dict(c.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone())


def user_get(uid: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None


def users_list(keyword: str = "", limit: int = 200):
    """用户管理（内部只读）：小程序登录过的用户，按最近登录倒序。

    keyword 同时模糊匹配昵称与手机号；返回 (总户数, 当前页行)。
    只读：不提供任何改写入口，登录/改资料仍走 users_api 自身动作。
    """
    where, args = [], []
    if keyword:
        where.append("(nickname LIKE ? OR phone LIKE ?)")
        args += [f"%{keyword}%", f"%{keyword}%"]
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) FROM users{cond}", args).fetchone()[0]
        rows = c.execute(
            "SELECT id,openid,phone,nickname,avatar_path,avatar_ver,created_at,last_login_at "
            f"FROM users{cond} "
            "ORDER BY COALESCE(NULLIF(last_login_at,''), created_at) DESC, id DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
        return total, [dict(r) for r in rows]


def user_update(uid: int, **fields):
    """白名单字段更新（phone/nickname/avatar_path/avatar_ver）。"""
    allowed = {"phone", "nickname", "avatar_path", "avatar_ver", "unionid"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return user_get(uid)
    with _lock, _conn() as c:
        assign = ",".join(f"{k}=?" for k in sets)
        c.execute(f"UPDATE users SET {assign} WHERE id=?", (*sets.values(), uid))
    return user_get(uid)


SESSION_DAYS = 30


def session_create(uid: int, days: int = SESSION_DAYS) -> str:
    """发不透明会话 token，入库可吊销；过期由校验时惰性比较。
    顺手清一遍全库过期行——旧 token 不再被使用就永远不会走到 session_user 的清理分支，
    不清会在库里无限堆积。"""
    import secrets
    token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _lock, _conn() as c:
        c.execute("DELETE FROM user_sessions WHERE expires_at < ?", (_now(),))
        c.execute("INSERT INTO user_sessions(token,user_id,expires_at) VALUES(?,?,?)",
                  (token, uid, expires))
    return token


def session_delete(token: str) -> None:
    """登出/吊销：删掉该 token（幂等）。"""
    if not token:
        return
    with _lock, _conn() as c:
        c.execute("DELETE FROM user_sessions WHERE token=?", (token,))


def session_user(token: str):
    """token → 用户 dict；不存在/过期/用户已删一律 None。顺带清已过期行。"""
    if not token:
        return None
    with _conn() as c:
        c.execute("DELETE FROM user_sessions WHERE expires_at < ?", (_now(),))
        row = c.execute(
            "SELECT u.* FROM user_sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.expires_at >= ?",
            (token, _now()),
        ).fetchone()
        return dict(row) if row else None
