# -*- coding: utf-8 -*-
"""小程序用户接口离线测试：微信 HTTP 全部打桩（不联网），直接调函数。
隔离：store.DB_PATH/DATA_DIR/OUT_DIR 全部落临时目录，不碰真实库。"""
import sys, io, os, json, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "users_api_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP
store.OUT_DIR = TMP
store.init()

from api import users_api

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)

# ---- 微信打桩：打在 HTTP 层（_wx_api），保留 _wx_conf 配置检查的真实路径 ----
WX_STATE = {"phone": "91234567"}
from fastapi import HTTPException as _HE
def fake_wx_api(url, *, params=None, body=None, method="GET"):
    if "stable_token" in url:
        return {"access_token": "fake-access-token", "expires_in": 7200}
    if "jscode2session" in url:
        code = params["js_code"]
        if code == "bad-code":
            # 真实 _wx_api 对 errcode!=0 抛 401，桩保持同语义
            raise _HE(401, "微信接口返回错误 40029：invalid code")
        return {"openid": f"oTEST-{code}", "unionid": "u-union-1", "session_key": "sk"}
    if "getuserphonenumber" in url:
        return {"errcode": 0, "phone_info": {"purePhoneNumber": WX_STATE["phone"], "countryCode": "86"}}
    raise AssertionError("unexpected wx url: " + url)
users_api._wx_api = fake_wx_api

# 1) 未配 WX_APPID → 登录 503（微信登录整体关闭）
os.environ.pop("WX_APPID", None); os.environ.pop("WX_APP_SECRET", None)
try:
    users_api.wx_login({"code": "x"}); check(False, "未配 WX_APPID 应 503")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 503, "未配 WX_APPID → 503")

# 2) 配置后登录：建户 + 发 token
os.environ["WX_APPID"] = "wx-test"; os.environ["WX_APP_SECRET"] = "sec-test"
r1 = users_api.wx_login({"code": "login-1"})
u1, t1 = r1["user"], r1["token"]
check(u1["id"] >= 1 and t1, f"首登建户 id={u1['id']} 并发 token")
check(u1["nickname"] == "" and u1["avatar_url"] == "", "新户昵称/头像为空")

# 3) 同 openid 二次登录 → 同一户、token 独立且都有效
r2 = users_api.wx_login({"code": "login-1"})
check(r2["user"]["id"] == u1["id"], "同 openid 复登录返回同一用户")
check(r2["token"] != t1, "复登录发新 token")
check(store.session_user(t1)["id"] == u1["id"] and store.session_user(r2["token"])["id"] == u1["id"],
      "两个 token 均有效")

# 4) 不同 openid → 不同户
r3 = users_api.wx_login({"code": "login-2"})
check(r3["user"]["id"] != u1["id"], "不同 openid 是不同用户")

# 4b) 微信侧错误码：坏 code → 401
try:
    users_api.wx_login({"code": "bad-code"}); check(False, "微信坏 code 应 401")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 401, "微信坏 code → 401")

# 5) token 鉴权：好 token 过、垃圾 token 401、缺头 401
check(users_api._user_from_token(f"Bearer {t1}")["id"] == u1["id"], "Bearer 解析通过")
check(users_api._user_from_token("garbage") is None, "垃圾头不通过")
check(users_api._user_from_token("") is None, "缺头不通过")
try:
    users_api._current_user("Bearer bogus"); check(False, "坏 token 应 401")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 401, "坏 token → 401")

# 6) 过期会话 → None（直接插一条过期行）
import datetime
past = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
with store._conn() as c:
    c.execute("INSERT INTO user_sessions(token,user_id,expires_at) VALUES(?,?,?)",
              ("expired-tok", u1["id"], past))
check(store.session_user("expired-tok") is None, "过期会话拒绝")
check(store.session_user("") is None, "空 token 拒绝")

# 7) 资料改昵称：合法生效、空/超长 422（直调时依赖不生效，先经 _current_user 解析出用户）
U = users_api._current_user(f"Bearer {t1}")
me = users_api.get_me(U)
check(me["id"] == u1["id"], "me 返回本人")
users_api.patch_me({"nickname": "陈大文"}, U)
# 每次真实请求都会由 _current_user 重新查库，这里同样重取一份（模拟下一次请求）
check(users_api.get_me(users_api._current_user(f"Bearer {t1}"))["nickname"] == "陈大文", "改昵称生效")
for bad in ("", "x" * 31):
    try:
        users_api.patch_me({"nickname": bad}, U); check(False, f"昵称[{bad[:5]}…]应 422")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 422, "昵称空/超长 → 422")

# 8) 头像：真 PNG（800×600 非方图）→ 方形居中裁剪 512×512 JPEG
from PIL import Image as PILImage
img = PILImage.new("RGB", (800, 600), (200, 60, 60))
buf = io.BytesIO(); img.save(buf, "PNG"); png_bytes = buf.getvalue()
r = users_api._save_avatar(u1["id"], png_bytes)
check(r["user"]["avatar_url"].endswith("?v=1"), "头像 URL 带版本参数 v=1")
av_path = os.path.join(TMP, "uploads", "avatars", f"u{u1['id']}.jpg")
check(os.path.exists(av_path), "头像落盘 uploads/avatars/u{id}.jpg")
with PILImage.open(av_path) as got:
    check(got.size == (512, 512) and got.format == "JPEG", f"重编码 512×512 JPEG (实际 {got.size} {got.format})")
resp = users_api.get_avatar(u1["id"])
check(os.path.basename(resp.path) == f"u{u1['id']}.jpg", "头像 GET 可取")

# 9) 再传一次 → 版本号递增、覆盖同文件
img2 = PILImage.new("RGB", (300, 300), (60, 200, 60))
buf2 = io.BytesIO(); img2.save(buf2, "JPEG"); jpg_bytes = buf2.getvalue()
r = users_api._save_avatar(u1["id"], jpg_bytes)
check(r["user"]["avatar_url"].endswith("?v=2"), "二次上传版本递增 v=2")

# 10) 非法图：GIF 魔数 422、超 5MB 422、空 422
gif = b"GIF89a" + b"\x00" * 50
for bad, why in ((gif, "GIF 魔数"), (b"\x00" * (5 * 1024 * 1024 + 1), "超 5MB"), (b"", "空字节")):
    try:
        users_api._save_avatar(u1["id"], bad); check(False, f"{why} 应 422")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 422, f"{why} → 422")

# 11) 请求体三形态：JSON dataurl / 裸 image/* 字节
class FakeReq:
    def __init__(self, ct, body): self.headers = {"content-type": ct}; self._b = body
    async def body(self): return self._b
import asyncio
from fastapi import HTTPException as HE
dataurl = "data:image/png;base64," + __import__("base64").b64encode(png_bytes).decode()
raw = asyncio.run(users_api._avatar_bytes_from_request(
    FakeReq("application/json", json.dumps({"image": dataurl}).encode())))
check(raw == png_bytes, "JSON dataurl 解出原图")
raw = asyncio.run(users_api._avatar_bytes_from_request(FakeReq("image/jpeg", jpg_bytes)))
check(raw == jpg_bytes, "裸 image/* 字节直通")
try:
    asyncio.run(users_api._avatar_bytes_from_request(FakeReq("text/plain", b"hello")))
    check(False, "无法识别的请求体应 422")
except HE as ex:
    check(ex.status_code == 422, "无法识别请求体 → 422")

# 12) 手机号：打桩 code 绑定 + 手动提交 + 非法格式 422
r = users_api.bind_phone({"code": "phone-btn-code"}, U)
check(r["user"]["phone"] == "91234567", "微信按钮 code 绑定手机号")
r = users_api.bind_phone({"phone": "13800138000"}, U)
check(r["user"]["phone"] == "13800138000", "手动提交手机号覆盖")
try:
    users_api.bind_phone({"phone": "abc"}, U); check(False, "非法手机号应 422")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 422, "非法手机号 → 422")
try:
    users_api.bind_phone({}, U); check(False, "code/phone 都缺应 422")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 422, "缺 code 与 phone → 422")

# 13) public_user 收敛：不漏 openid/unionid/路径
pub = json.dumps(users_api.get_me(U))
check("oTEST" not in pub and "uploads" not in pub and "fake-access" not in pub,
      "公开资料不泄漏 openid/服务器路径/access_token")

# 14) 头像 URL 绝对化：小程序 <image> 不认同源相对路径。
#     uvicorn 的 ProxyHeaders 会把 Nginx 送来的 X-Forwarded-Proto/Host 落进 scope，
#     这里直接用 scheme=https + host 头构造 scope 复现
from starlette.requests import Request as _Req
_req = _Req({
    "type": "http", "method": "GET", "path": "/api/users/me", "raw_path": b"/api/users/me",
    "headers": [(b"host", b"contract.eazycar.top")], "query_string": b"",
    "server": ("127.0.0.1", 8300), "scheme": "https", "client": ("127.0.0.1", 5000),
})
_abs = users_api._public_user(store.user_get(u1["id"]), users_api._base(_req))["avatar_url"]
check(_abs.startswith("https://contract.eazycar.top/api/users/"), f"有 request 时头像 URL 为绝对地址（{_abs}）")
check(users_api._base(None) == "", "直调不传 request 时退回相对路径（测试兼容）")

# 15) 登出吊销：token 立即失效，幂等
tok = store.session_create(u1["id"])
check(store.session_user(tok) is not None, "登出前 token 有效")
check(users_api.logout(f"Bearer {tok}")["ok"] is True, "登出返回 ok")
check(store.session_user(tok) is None, "登出后 token 立即失效")
check(users_api.logout("")["ok"] is True and users_api.logout("garbage")["ok"] is True,
      "无头/垃圾头登出幂等不报错")

# 16) 建新会话时清扫全库过期行（旧 token 不再被使用否则永远留着）
with store._conn() as c:
    c.execute("INSERT INTO user_sessions(token,user_id,expires_at) VALUES(?,?,?)",
              ("stale-tok", u1["id"], past))
store.session_create(u1["id"])
with store._conn() as c:
    left = c.execute("SELECT 1 FROM user_sessions WHERE token='stale-tok'").fetchone()
check(left is None, "建新会话时清扫过期行")

# 17) 超大像素图 → 422（原 Pillow DecompressionBombError 会冒成 500）
_orig_open = users_api.Image.open
def _boom(*a, **k):
    raise users_api.Image.DecompressionBombError("too big")
users_api.Image.open = _boom
try:
    users_api._save_avatar(u1["id"], png_bytes); check(False, "超大像素图应 422")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 422, "超大像素图 → 422（不再 500）")
finally:
    users_api.Image.open = _orig_open

# 18) 用户不存在时上传头像 → 404（而不是 AttributeError 500）
try:
    users_api._save_avatar(999999, png_bytes); check(False, "用户不存在应 404")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "用户不存在 → 404")

# 19) 用户管理列表（只读）：字段、排序、模糊搜索、脱敏
with store._conn() as c:
    c.execute("UPDATE users SET last_login_at=? WHERE id=?", ("2026-01-01 00:00:00", u1["id"]))
r = users_api.list_users()
check(r["total"] == 2, f"用户总数（实际 {r['total']}）")
check([i["id"] for i in r["items"]][0] == r3["user"]["id"], "按最近登录倒序（新用户在前）")
first = r["items"][0]
check(first["account"] == f"#{first['id']}", "账号＝系统用户编号")
check(all(k in first for k in ("account", "nickname", "avatar_url", "phone", "last_login_at", "created_at")),
      "四个展示字段 + 时间都在")
check(not any("uploads" in str(i) or "avatar_path" in i for i in r["items"]), "不泄漏服务器路径")
check(all("…" in i["openid"] or len(i["openid"]) <= 12 for i in r["items"] if i["openid"]), "openid 已脱敏")
check(users_api._mask_openid("oTEST-abcdefghijklmn") == "oTEST-…klmn", "脱敏规则：前6+后4")

check([i["id"] for i in users_api.list_users(keyword="陈")["items"]] == [u1["id"]], "昵称模糊搜索")
check([i["id"] for i in users_api.list_users(keyword="1380")["items"]] == [u1["id"]], "手机号模糊搜索")
check(users_api.list_users(keyword="不存在的人")["total"] == 0, "无匹配 → 0")

# 头像在列表里也是绝对地址（有 request 时）
ra = users_api.list_users(request=_req)
u1_row = [i for i in ra["items"] if i["id"] == u1["id"]][0]
check(u1_row["avatar_url"].startswith("https://contract.eazycar.top/api/users/"), "列表头像 URL 为绝对地址")

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
