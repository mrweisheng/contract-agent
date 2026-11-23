# -*- coding: utf-8 -*-
"""小程序用户：微信一键登录 + 资料/头像。

登录链路：小程序 wx.login() 拿 code → 服务端调 jscode2session 换 openid（AppSecret 只在
服务端）→ 按 openid 定户（首登自动建户）→ 发不透明会话 token（30 天，库内可吊销）。
手机号：getPhoneNumber 按钮的 code → stable_token + getuserphonenumber 换手机号绑定；
未认证小程序可走手动提交手机号。头像：前端上传（JSON dataurl / 裸图字节 / multipart
三形态）→ Pillow 方形裁剪重编码 512×512 JPEG（洗掉 EXIF 与注入内容）→
data/uploads/avatars/u{id}.jpg，users 表只存路径+版本号，URL 带版本参数破缓存。
配置：WX_APPID / WX_APP_SECRET 未配置时整个前缀 503 对外关闭。
"""
import base64
import io
import json
import os
import re
import threading
import time

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image

from . import store

router = APIRouter()

AVATAR_SIZE = 512          # 方形重编码边长
AVATAR_MAX_RAW = 5 * 1024 * 1024   # 原图上限（重编码后远小于此）
_SESSION_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)
_PHONE_RE = re.compile(r"^[0-9]{8,15}$")   # 大陆 11 位、香港 8 位都落在内

# 角色（2026-11-23）：默认 user；权限细则后续再定，这里只负责角色本身与展示文案
ROLES = {"user": "普通用户", "admin": "管理员", "super": "超级管理员"}
DEFAULT_ROLE = "user"


def _avatar_dir() -> str:
    return os.path.join(store.DATA_DIR, "uploads", "avatars")


# ---------- 微信开放接口封装 ----------

def _wx_conf() -> tuple:
    appid = os.getenv("WX_APPID", "").strip()
    secret = os.getenv("WX_APP_SECRET", "").strip()
    if not appid or not secret:
        raise HTTPException(503, "微信登录未启用（服务器未配置 WX_APPID/WX_APP_SECRET）")
    return appid, secret


def _wx_api(url: str, *, params: dict = None, body: dict = None, method: str = "GET") -> dict:
    try:
        if method == "POST":
            r = requests.post(url, params=params, json=body or {}, timeout=(5, 10))
        else:
            r = requests.get(url, params=params, timeout=(5, 10))
        data = r.json()
    except Exception as ex:
        raise HTTPException(502, f"微信接口通信失败：{ex}")
    if data.get("errcode") not in (0, None):
        raise HTTPException(401, f"微信接口返回错误 {data.get('errcode')}：{data.get('errmsg')}")
    return data


def _wx_jscode2session(code: str) -> dict:
    """wx.login 的 code → {openid, unionid?, session_key}。code 一次性、5 分钟有效。"""
    appid, secret = _wx_conf()
    return _wx_api("https://api.weixin.qq.com/sns/jscode2session",
                   params={"appid": appid, "secret": secret, "js_code": code,
                           "grant_type": "authorization_code"})


_token_cache = {"token": "", "expires": 0.0}
_token_lock = threading.Lock()


def _access_token() -> str:
    """小程序全局凭证。用 stable_token 端点：不会像普通 token 那样互相顶掉，缓存 90 分钟。"""
    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires"]:
            return _token_cache["token"]
        appid, secret = _wx_conf()
        data = _wx_api("https://api.weixin.qq.com/cgi-bin/stable_token", method="POST",
                       body={"grant_type": "client_credential", "appid": appid,
                             "secret": secret, "force_refresh": False})
        _token_cache["token"] = data["access_token"]
        _token_cache["expires"] = time.time() + min(int(data.get("expires_in", 7200)) - 300, 5400)
        return _token_cache["token"]


def _wx_phone_number(code: str) -> str:
    """getPhoneNumber 按钮 code → 手机号（纯号码，可能带国际区号外的正文）。"""
    data = _wx_api("https://api.weixin.qq.com/wxa/business/getuserphonenumber",
                   params={"access_token": _access_token()}, body={"code": code}, method="POST")
    info = data.get("phone_info") or {}
    return str(info.get("purePhoneNumber") or info.get("phoneNumber") or "")


# ---------- 鉴权依赖 ----------

def _user_from_token(authorization: str):
    m = _SESSION_RE.match(authorization or "")
    return store.session_user(m.group(1)) if m else None


def _current_user(authorization: str = Header(default="")):
    user = _user_from_token(authorization)
    if not user:
        raise HTTPException(401, "未登录或会话已过期")
    return user


def _base(request) -> str:
    """对外绝对地址前缀。小程序 <image>/<image src> 不认同源相对路径，头像 URL 必须是完整 https 地址。
    经 Nginx 反代时 uvicorn 默认信任 127.0.0.1 的 X-Forwarded-Proto/Host，base_url 即 https 域名。
    直调（测试）不传 request 时退回相对路径。"""
    if request is None:
        return ""
    return str(request.base_url).rstrip("/")


def _public_user(u: dict, base: str = "") -> dict:
    ver = u.get("avatar_ver") or 0
    role = u.get("role") or DEFAULT_ROLE
    return {
        "id": u["id"],
        "nickname": u.get("nickname") or "",
        "phone": u.get("phone") or "",
        "avatar_url": f"{base}/api/users/{u['id']}/avatar?v={ver}" if u.get("avatar_path") else "",
        "role": role,
        "role_label": ROLES.get(role, ROLES[DEFAULT_ROLE]),
        "created_at": u.get("created_at") or "",
    }


# ---------- 登录 / 手机号 ----------

@router.post("/api/auth/wx-login")
def wx_login(body: dict, request: Request = None):
    """静默登录：{code: wx.login() 的 code}。首登自动建户。返回 token + 用户资料。"""
    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(422, "缺少 code")
    data = _wx_jscode2session(code)
    user = store.user_upsert_by_openid(data["openid"], data.get("unionid") or "")
    token = store.session_create(user["id"])
    return {"token": token, "expires_in_days": store.SESSION_DAYS,
            "user": _public_user(user, _base(request))}


@router.post("/api/auth/phone")
def bind_phone(body: dict, user: dict = Depends(_current_user), request: Request = None):
    """绑定手机号：{code: getPhoneNumber 按钮 code}（需企业认证小程序）或 {phone: 手动填}。"""
    code = str(body.get("code") or "").strip()
    manual = str(body.get("phone") or "").strip()
    if code:
        phone = _wx_phone_number(code)
        if not phone:
            raise HTTPException(401, "微信未返回手机号")
    elif manual:
        if not _PHONE_RE.match(manual):
            raise HTTPException(422, "手机号格式不正确")
        phone = manual
    else:
        raise HTTPException(422, "缺少 code 或 phone")
    user = store.user_update(user["id"], phone=phone)
    return {"ok": True, "user": _public_user(user, _base(request))}


@router.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    """登出：吊销当前 token（文档承诺的「可吊销」）。幂等，token 不存在也返回 ok。"""
    m = _SESSION_RE.match(authorization or "")
    if m:
        store.session_delete(m.group(1))
    return {"ok": True}


# ---------- 资料 ----------

@router.get("/api/users/me")
def get_me(user: dict = Depends(_current_user), request: Request = None):
    # 依赖里拿到的就是完整用户行（session_user 走 SELECT u.*），不必再查一次
    return _public_user(user, _base(request))


def _mask_openid(openid: str) -> str:
    """openid 只用于内部对账，列表里脱敏展示（前 6 + 后 4），前端不需要完整值。"""
    o = openid or ""
    return f"{o[:6]}…{o[-4:]}" if len(o) > 12 else o


@router.get("/api/users")
def list_users(request: Request = None, keyword: str = "", limit: int = 200):
    """用户管理（内部只读）：小程序登录过的用户列表，按最近登录倒序。

    账号＝系统用户编号；openid 正文脱敏展示（前 6 + 后 4），另附 openid_full
    供后台点击复制/核对（前端默认不显示完整值）。支持昵称/手机号模糊搜索。
    暂不提供任何编辑入口。
    """
    limit = max(1, min(int(limit), 500))
    total, rows = store.users_list(keyword.strip(), limit)
    items = []
    for r in rows:
        items.append({
            **_public_user(r, _base(request)),
            "account": f"#{r['id']}",
            "openid": _mask_openid(r.get("openid") or ""),
            "openid_full": r.get("openid") or "",
            "last_login_at": r.get("last_login_at") or "",
        })
    return {"total": total, "items": items, "roles": ROLES, "default_role": DEFAULT_ROLE}


@router.patch("/api/users/{uid}/role")
def set_user_role(uid: int, body: dict, request: Request = None):
    """改角色（内部管理）。三档：user 普通（默认）/ admin 管理员 / super 超级管理员。

    平台暂不做登录鉴权（测试期），所以这里只校验角色值与用户存在；权限收敛后续再定。
    登录/复登不会覆盖角色——user_upsert_by_openid 只刷新 unionid 与登录时间。
    """
    role = str(body.get("role") or "").strip()
    if role not in ROLES:
        raise HTTPException(422, f"角色须为 {'/'.join(ROLES)} 之一")
    if not store.user_get(uid):
        raise HTTPException(404, "用户不存在")
    user = store.user_update(uid, role=role)
    return {"ok": True, "user": _public_user(user, _base(request))}


@router.patch("/api/users/me")
def patch_me(body: dict, user: dict = Depends(_current_user), request: Request = None):
    nickname = str(body.get("nickname") or "").strip()
    if not nickname or len(nickname) > 30:
        raise HTTPException(422, "昵称须为 1-30 个字符")
    user = store.user_update(user["id"], nickname=nickname)
    return {"ok": True, "user": _public_user(user, _base(request))}


# ---------- 头像 ----------

def _decode_image(raw: bytes) -> bytes:
    if not raw or len(raw) > AVATAR_MAX_RAW:
        raise HTTPException(422, "图片为空或超过 5MB 上限")
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    if raw[:3] == b"\xff\xd8\xff":
        return raw
    raise HTTPException(422, "头像必须是 PNG 或 JPG")


def _save_avatar(uid: int, raw: bytes, base: str = "") -> dict:
    """原图 → 方形居中裁剪 → 512×512 JPEG 重编码（顺带洗掉 EXIF/注入内容）。"""
    data = _decode_image(raw)
    cur = store.user_get(uid)
    if not cur:
        raise HTTPException(404, "用户不存在")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError:
        raise HTTPException(422, "图片像素过大，请换一张小一点的图")
    except Exception:
        raise HTTPException(422, "图片无法解析，请换一张 PNG/JPG")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w + side) // 2, (h + side) // 2)).resize((AVATAR_SIZE, AVATAR_SIZE),
                                                              Image.LANCZOS)
    os.makedirs(_avatar_dir(), exist_ok=True)
    path = os.path.join(_avatar_dir(), f"u{uid}.jpg")
    img.save(path, "JPEG", quality=88)
    user = store.user_update(uid, avatar_path=os.path.relpath(path, store.DATA_DIR),
                             avatar_ver=(cur.get("avatar_ver") or 0) + 1)
    return {"ok": True, "user": _public_user(user, base)}


async def _avatar_bytes_from_request(request: Request) -> bytes:
    """三形态收图：multipart 文件（wx.uploadFile）/ 裸图字节 / JSON dataurl（同签名接口）。"""
    ctype = (request.headers.get("content-type") or "").lower()
    if ctype.startswith("multipart/"):
        form = await request.form()
        up = form.get("file") or form.get("image")
        if up is None:
            raise HTTPException(422, "multipart 里缺少 file/image 字段")
        return await up.read()
    raw = await request.body()
    if ctype.startswith("image/"):
        return raw
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(422, "无法识别的请求体：支持 multipart / 裸图字节 / JSON dataurl")
    s = str(payload.get("image") or "")
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    try:
        return base64.b64decode(s, validate=True)
    except Exception:
        raise HTTPException(422, "image 不是合法的 base64")


@router.post("/api/users/me/avatar")
async def upload_avatar(request: Request, user: dict = Depends(_current_user)):
    raw = await _avatar_bytes_from_request(request)
    return _save_avatar(user["id"], raw, _base(request))


@router.get("/api/users/{user_id}/avatar")
def get_avatar(user_id: int):
    """头像公开可读（小程序 <image> 标签带不了鉴权头）；只有一张方图，无敏感信息。"""
    user = store.user_get(user_id)
    if not user or not user.get("avatar_path"):
        raise HTTPException(404, "该用户未设置头像")
    path = os.path.join(store.DATA_DIR, user["avatar_path"])
    if not os.path.exists(path):
        raise HTTPException(404, "头像文件不存在")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
