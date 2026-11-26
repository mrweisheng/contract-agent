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
        # 示例合同（2026-11-23）：每个普通用户一份、归属本人；与正式单隔离，
        # 不进工作台/对外接口列表（contracts_query/history 一律过滤 is_sample）
        try:
            c.execute("ALTER TABLE gens ADD COLUMN is_sample INTEGER DEFAULT 0")
        except Exception:
            pass  # 列已存在
        # 未盖章标记（2026-11-25）：工作台取消勾选「电子签章」生成的单——PDF 不盖骑缝章、
        # 小程序 sign 块 stamped=false。默认 0＝按原行为，历史单一律不变
        try:
            c.execute("ALTER TABLE gens ADD COLUMN unsealed INTEGER DEFAULT 0")
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
        # 角色（2026-11-23）：user=普通用户（默认）/ admin=管理员 / super=超级管理员。
        # 权限细则后续再定，这里先只落角色本身。
        try:
            c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        except Exception:
            pass  # 列已存在
        c.execute("UPDATE users SET role='user' WHERE role IS NULL OR role=''")
        c.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            expires_at TEXT
        )""")
        # 電子收據（2026-11-26）：与合同流水**完全隔离**的独立表。
        # 不复用 gens —— gens 是合同总表，合同管理页直接全表查，发票混进去会污染列表与统计。
        # 号段独立：六位流水，**不使用数字 4 与 7**（香港讳 4「死」、7「执笠」，与楼宇无 4 楼同理），
        # 作废只置 status='void' 留痕不删（IRD：作废留存根）。
        # revision = 同号覆盖次数：下载即存档，改完再下载覆盖同一编号，不换号。
        c.execute("""CREATE TABLE IF NOT EXISTS receipts (
            no TEXT PRIMARY KEY,
            payer TEXT DEFAULT '',
            purpose TEXT DEFAULT '',
            amount REAL DEFAULT 0,
            currency TEXT DEFAULT 'HKD',
            method TEXT DEFAULT '',
            method_note TEXT DEFAULT '',
            note TEXT DEFAULT '',
            payee TEXT DEFAULT '',
            receipt_date TEXT DEFAULT '',
            sealed INTEGER DEFAULT 1,
            status TEXT,
            created_at TEXT,
            saved_at TEXT DEFAULT '',
            revision INTEGER DEFAULT 0
        )""")
        # 旧库增量迁移：revision（同号覆盖次数）是后加的列
        try:
            c.execute("ALTER TABLE receipts ADD COLUMN revision INTEGER DEFAULT 0")
        except Exception:
            pass  # 列已存在
        # 旧库增量迁移：currency（HKD/CNY，默认港币）是后加的列
        try:
            c.execute("ALTER TABLE receipts ADD COLUMN currency TEXT DEFAULT 'HKD'")
        except Exception:
            pass  # 列已存在
        # 旧库增量迁移：method_note（付款方式右侧补充线文字）是后加的列
        try:
            c.execute("ALTER TABLE receipts ADD COLUMN method_note TEXT DEFAULT ''")
        except Exception:
            pass  # 列已存在


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
    """最近生成记录；pending 占位不对外展示。含后台复核结论（未出为空）。
    示例合同不进工作台历史。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT no,type,client,mode,currency,filename,status,created_at,"
            "review_status,review_issues FROM gens "
            "WHERE status IN ('ok','failed') AND COALESCE(is_sample,0)=0 "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def contracts_query(date_from: str = "", date_to: str = "", client: str = "",
                    type_key: str = "", limit: int = 200):
    """合同管理列表：只取生成成功的单，按生成时间倒序。

    date_from/date_to：YYYY-MM-DD，按 created_at 的日期部分比较（含边界，空=不限）；
    client：模糊匹配 客户 / 合同编号 / 签署人微信昵称 / 签署人手机号（2026-11-25 扩展，
            后台按签署人手机号找单是高频动作）；type_key：业务类型精确匹配。
    返回 (符合条件的总条数, 当前页行) —— 总条数用于前端提示「共 N 份」。
    """
    where, args = ["status='ok'", "COALESCE(is_sample,0)=0"], []
    if date_from:
        where.append("date(created_at) >= date(?)")
        args.append(date_from)
    if date_to:
        where.append("date(created_at) <= date(?)")
        args.append(date_to)
    if client:
        like = f"%{client}%"
        where.append("(client LIKE ? OR no LIKE ? OR signed_user_id IN "
                     "(SELECT id FROM users WHERE nickname LIKE ? OR phone LIKE ?))")
        args += [like, like, like, like]
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
        # 签署人（管理员视角）：补昵称/手机号/头像，空绑定则统一为空串
        for r in items:
            r["signer_nickname"] = ""
            r["signer_phone"] = ""
            r["signer_avatar_path"] = ""
            r["signer_avatar_ver"] = 0
        uids = sorted({r["signed_user_id"] for r in items if r.get("signed_user_id")})
        if uids:
            marks = ",".join("?" * len(uids))
            signers = {r["id"]: dict(r) for r in c.execute(
                f"SELECT id,nickname,phone,avatar_path,avatar_ver FROM users WHERE id IN ({marks})", uids)}
            for r in items:
                s = signers.get(r.get("signed_user_id"))
                if not s:
                    continue
                r["signer_nickname"] = s.get("nickname") or ""
                r["signer_phone"] = s.get("phone") or ""
                r["signer_avatar_path"] = s.get("avatar_path") or ""
                r["signer_avatar_ver"] = s.get("avatar_ver") or 0
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


def reset_signed(no: str) -> bool:
    """撤销签署（管理端重测用）：清已签版/签署时间/签署用户绑定。

    只清签署状态，不动合同本身与编号；文件由调用方先备份。
    条件更新保证并发下只有一方成功；返回是否有行被更新。
    """
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE gens SET signed_path='', signed_at='', signed_user_id=NULL, bound_at='' "
            "WHERE no=? AND status='ok' AND COALESCE(signed_path,'')<>''", (no,))
        return cur.rowcount > 0


def bind_signed_user(no: str, uid: int) -> bool:
    """签字即认领：把已签合同绑定到签署的登录用户（我的合同 2026-11-23）。

    条件更新（signed_user_id IS NULL）保证同一份只会绑一次：并发下后到的一方
    rowcount=0，由调用方按「已被他人签走」处理，不会互相覆盖。
    另要求 signed_path 非空：防止「管理员刚重置、小程序迟到的绑定」把未签合同
    绑到用户名下（重置会清 signed_path 与 signed_user_id，两者必须同进同退）。
    """
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE gens SET signed_user_id=?, bound_at=? "
            "WHERE no=? AND signed_user_id IS NULL AND COALESCE(signed_path,'')<>''",
            (uid, _now(), no))
        return cur.rowcount > 0


def create_sample_gen(no: str, uid: int, client: str, filename: str):
    """示例合同落库（2026-11-23）：每个普通用户一份、直接归属本人，is_sample=1。

    编号以 9 开头（11 位），与正式合同（YYYYMMDD 开头）不可能撞号，也不占正式流水；
    contracts_query/history 均过滤 is_sample，示例单不会出现在工作台与对外接口。
    """
    now = _now()
    with _lock, _conn() as c:
        row = c.execute("SELECT no FROM gens WHERE no=?", (no,)).fetchone()
        if row:
            c.execute(
                "UPDATE gens SET type='car', client=?, mode='default', currency='HKD', "
                "filename=?, status='ok', signed_user_id=?, bound_at=COALESCE(bound_at,?), "
                "is_sample=1 WHERE no=?",
                (client, filename, uid, now, no))
        else:
            c.execute(
                "INSERT INTO gens(no,type,client,mode,currency,filename,status,created_at,"
                "signed_user_id,bound_at,is_sample) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                (no, "car", client, "default", "HKD", filename, "ok", now, uid, now))


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


def mark_unsealed(no: str):
    """未盖章标记：工作台取消勾选「电子签章」生成的单。
    PDF 下载据此不盖骑缝章、对外/小程序详情据此 stamped=false；历史单无此标记＝原行为。"""
    with _lock, _conn() as c:
        c.execute("UPDATE gens SET unsealed=1 WHERE no=? AND status='ok'", (no,))


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
            "SELECT id,openid,phone,nickname,avatar_path,avatar_ver,role,created_at,last_login_at "
            f"FROM users{cond} "
            "ORDER BY COALESCE(NULLIF(last_login_at,''), created_at) DESC, id DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
        return total, [dict(r) for r in rows]


def user_update(uid: int, **fields):
    """白名单字段更新（phone/nickname/avatar_path/avatar_ver/role）。"""
    allowed = {"phone", "nickname", "avatar_path", "avatar_ver", "unionid", "role"}
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


# ===================== 電子收據 =====================
# 與合同 gens 表完全隔離：獨立表、獨立號段、獨立狀態機。
# 狀態機：開頁占號 pending → 下載即存檔 ok（同號可反覆覆蓋，revision 累加）
#        → 切走/新開單釋放 pending 或保留 ok → 超時未存檔的 pending 自動回收。
#
# 編號忌諱：香港諱 4（死）與 7（執笠）。整號不含 4 同時涵蓋 14「實死」、24「易死」、
# 74 等所有組合，也與本地樓宇整段跳過 40–49 樓的慣例一致。
# 代價是必然跳號（000003 → 000005、000039 → 000050）——規則固定、單向遞增、可解釋。

RECEIPT_PENDING_MIN = 30   # 占號超時閾值（分鐘）：未存檔則回收，避免半途離開留下永久空號
RECEIPT_BAD_DIGITS = ("4", "7")


def _receipt_clean(no: str) -> bool:
    """號面是否不含忌諱數字。"""
    return bool(no) and not any(d in no for d in RECEIPT_BAD_DIGITS)


def reserve_receipt_no() -> str:
    """分配一個六位號（不含 4／7），返回 no（如 000190）。

    - 取號基準＝當前最大已存在號 +1（含已作廢單，作廢號不回收不重用）；
    - 撞到諱數或已占用的號直接往後推；
    - 同時清掃超過 RECEIPT_PENDING_MIN 仍未存檔的 pending 占位；
    - 六位用盡直接報錯，不靜默回繞。
    """
    stale = (datetime.datetime.now() - datetime.timedelta(minutes=RECEIPT_PENDING_MIN)
             ).strftime("%Y-%m-%d %H:%M:%S")
    with _lock, _conn(immediate=True) as c:
        c.execute("DELETE FROM receipts WHERE status='pending' AND created_at < ?", (stale,))
        row = c.execute("SELECT no FROM receipts ORDER BY no DESC LIMIT 1").fetchone()
        seq = 1
        if row:
            try:
                seq = int(row["no"]) + 1
            except (TypeError, ValueError):
                seq = 1
        while seq <= 999999:
            no = f"{seq:06d}"
            if _receipt_clean(no) and not c.execute(
                    "SELECT 1 FROM receipts WHERE no=?", (no,)).fetchone():
                c.execute("INSERT INTO receipts(no,status,created_at) VALUES(?,?,?)",
                          (no, "pending", _now()))
                return no
            seq += 1
        raise RuntimeError("電子收據號段已用盡（六位、不含 4／7）")


def save_receipt(payload: dict) -> dict:
    """存檔（下載時自動呼叫）：同號覆蓋，revision 累加。

    只接受本模組 reserve 已占用的號，避免前端傳任意號寫入；
    已作廢的單拒絕改寫；尚未占號的號（理論上不會發生）走 INSERT 兜底。
    """
    no = str(payload.get("no") or "").strip()
    if not no or not no.isdigit():
        raise ValueError("收據編號不合法")
    if not _receipt_clean(no):
        raise ValueError("收據編號含忌諱數字")
    # 幣種白名單：只認港幣 / 人民幣，其餘一律回落港幣（舊前端沒傳時也走默認）
    cur_code = str(payload.get("currency") or "HKD").strip().upper()
    if cur_code not in ("HKD", "CNY"):
        cur_code = "HKD"
    # 必填校驗（與前端同口徑）：除「備註」外全部必填。
    # 前端已在下載前攔一次，這裡是第二道——存檔介面可被腳本直接呼叫，
    # 一張空白/零元收據落庫後照樣能重印，資料髒了沒有撤回的路。
    payer = str(payload.get("payer") or "").strip()
    purpose = str(payload.get("purpose") or "").strip()
    method = str(payload.get("method") or "").strip()
    method_note = str(payload.get("method_note") or "").strip()
    payee = str(payload.get("payee") or "").strip()
    receipt_date = str(payload.get("receipt_date") or "").strip()
    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if not payer:
        raise ValueError("付款方未填寫，不能存檔")
    if not purpose:
        raise ValueError("款項說明未填寫，不能存檔")
    if amount <= 0:
        raise ValueError("實收金額必須大於 0")
    if not method and not method_note:
        raise ValueError("付款方式未選擇")
    if not payee:
        raise ValueError("收款人未填寫")
    if not receipt_date:
        raise ValueError("日期未填寫")
    vals = (
        payer[:200],
        purpose[:200],
        amount,
        method[:40],
        method_note[:200],
        str(payload.get("note") or "")[:200],
        payee[:60],
        receipt_date[:10],
        1 if payload.get("sealed", True) else 0,
        cur_code,
        _now(),
    )
    with _lock, _conn(immediate=True) as c:
        row = c.execute("SELECT status FROM receipts WHERE no=?", (no,)).fetchone()
        if row and row["status"] == "void":
            raise ValueError("該收據已作廢，不可再存檔")
        if row:
            c.execute(
                "UPDATE receipts SET payer=?, purpose=?, amount=?, method=?, method_note=?, note=?, "
                "payee=?, receipt_date=?, sealed=?, currency=?, status='ok', saved_at=?, "
                "revision=COALESCE(revision,0)+1 WHERE no=?", vals + (no,),
            )
        else:
            c.execute(
                "INSERT INTO receipts(no,payer,purpose,amount,method,method_note,note,payee,"
                "receipt_date,sealed,currency,status,saved_at,created_at,revision) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'ok',?,?,1)", (no,) + vals + (_now(),),
            )
        rev = c.execute("SELECT revision FROM receipts WHERE no=?", (no,)).fetchone()["revision"]
    return {"no": no, "status": "ok", "revision": rev}


def release_receipt(no: str) -> bool:
    """釋放占號：切菜單 / 新開一張時，把還沒存檔的號立即收回（不必等 30 分鐘超時）。

    只刪 pending —— 已存檔的 ok 單和作廢單一律不動。
    """
    no = str(no or "").strip()
    if not no.isdigit():
        return False
    with _lock, _conn(immediate=True) as c:
        cur = c.execute("DELETE FROM receipts WHERE no=? AND status='pending'", (no,))
        return cur.rowcount > 0


def void_receipt(no: str) -> bool:
    """作廢：只改狀態留痕，不刪行（IRD 要求作廢單保留存根）。"""
    no = str(no or "").strip()
    if not no.isdigit():
        return False
    with _lock, _conn(immediate=True) as c:
        cur = c.execute("UPDATE receipts SET status='void' WHERE no=? AND status!='void'", (no,))
        return cur.rowcount > 0


def get_receipt(no: str):
    no = str(no or "").strip()
    with _conn() as c:
        row = c.execute("SELECT * FROM receipts WHERE no=?", (no,)).fetchone()
        return dict(row) if row else None


def list_receipts(limit: int = 200) -> list:
    """最近 N 張已存檔發票（不含 pending 占位與作廢單），倒序。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM receipts WHERE status='ok' ORDER BY no DESC LIMIT ?",
            (max(1, min(int(limit or 200), 1000)),),
        ).fetchall()
        return [dict(r) for r in rows]
