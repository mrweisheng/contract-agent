# -*- coding: utf-8 -*-
"""小程序「我的合同」：按登录用户隔离的查询与签署（签字即绑定）。

与对外接口的分工：
- `/api/open/*`（X-API-Key，全局共享）＝内部系统/管理员视角，可看全量；
- `/api/users/me/contracts*`（Bearer token）＝客户本人视角，只认 gens.signed_user_id = 本人。

绑定规则（2026-11-23 定稿）：
1. 合同生成时无主（signed_user_id 为空）；
2. 客户回传手写签名成功的那一刻自动绑定该登录用户，并落 bound_at——没有二次确认步骤；
3. 绑定之后：本人可见、管理员（工作台/对外 key）可见，其他登录用户一律 404；
4. 未授权手机号（users.phone 为空）不允许签署；
5. 一个用户可以绑定多份合同；同一份只能绑一次（条件更新，并发不会互相覆盖）。
"""
from fastapi import APIRouter, Depends, HTTPException

from . import store, open_api
from .users_api import _current_user

router = APIRouter()


def _mine(no: str, user: dict) -> dict:
    """取本人的一份合同：不存在/未生成/超出可见范围/不是本人 → 统一 404（不暴露他人单存在）。"""
    rec = open_api._gen(no)
    if rec.get("signed_user_id") != user["id"]:
        raise HTTPException(404, "合同不存在")
    return rec


def _label(type_key: str) -> str:
    from engine.types_config import get_type
    try:
        return get_type(type_key).get("label") or type_key
    except Exception:
        return type_key


@router.get("/api/users/me/contracts")
def my_contracts(user: dict = Depends(_current_user), limit: int = 100):
    """我的合同：只返回绑定到本人的已签合同，按生成时间倒序。"""
    limit = max(1, min(int(limit), 200))
    total, rows = store.contracts_by_user(user["id"], limit)
    return {"total": total, "items": [{
        "no": r["no"],
        "type": r["type"], "type_label": _label(r["type"]),
        "client": r["client"] or "",
        "currency": r["currency"] or "",
        "filename": r["filename"] or "",
        "created_at": r["created_at"] or "",
        "signed_at": r.get("signed_at") or "",
        "bound_at": r.get("bound_at") or "",
    } for r in rows]}


@router.get("/api/users/me/contracts/{no}")
def my_contract_detail(no: str, user: dict = Depends(_current_user)):
    """本人合同详情：blocks 渲染数据 + 结构化表单，字段同对外接口的详情。"""
    _mine(no, user)
    return open_api.contract_detail(no)


@router.get("/api/users/me/contracts/{no}/file")
def my_contract_file(no: str, user: dict = Depends(_current_user)):
    """下载本人合同的已签版 docx。"""
    _mine(no, user)
    return open_api.contract_file(no)


@router.get("/api/users/me/contracts/{no}/signature")
def my_signature_image(no: str, user: dict = Depends(_current_user)):
    """本人合同的客户手写签名图（透明 PNG），用于已签页叠加显示。"""
    _mine(no, user)
    return open_api.contract_signature_image(no)


@router.post("/api/users/me/contracts/{no}/signature")
def my_sign(no: str, body: dict, user: dict = Depends(_current_user)):
    """提交手写签名：合成进合同 → 存已签版 → 自动绑定到当前登录用户。

    校验顺序：先绑手机号（未授权不允许签）→ 合同可见且未签 → 合成签名 → 条件绑定。
    """
    if not str(user.get("phone") or "").strip():
        raise HTTPException(403, "请先授权手机号再签署")
    rec = open_api._gen(no)                       # 存在/已生成/在可见范围内
    if rec.get("signed_path"):
        raise HTTPException(409, "该合同已签署")
    if rec.get("signed_user_id") not in (None, "", user["id"]):
        raise HTTPException(409, "该合同已被签署")
    res = open_api.contract_signature(no, body)   # 合成签名 + 落 -签名.png + set_signed
    if not store.bind_signed_user(no, user["id"]):
        # 并发下的极端情况：另一位用户抢先绑定。签名已落盘，但归属不写，交管理员处理
        raise HTTPException(409, "该合同已被签署")
    return {**res, "bound": True, "signed_user_id": user["id"]}
