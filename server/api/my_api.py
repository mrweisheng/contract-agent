# -*- coding: utf-8 -*-
"""小程序「我的合同」：按登录用户隔离的查询与签署（签字即绑定）。

与对外接口的分工：
- `/api/open/*`（X-API-Key，全局共享）＝内部系统/管理员视角，可看全量；
- `/api/users/me/contracts*`（Bearer token）＝登录用户视角：普通用户只认本人合同
  + 一份独立示例合同；管理员可读可见范围内的全部正式合同。

绑定规则（2026-11-23 定稿）：
1. 合同生成时无主（signed_user_id 为空）；
2. 客户回传手写签名成功的那一刻自动绑定该登录用户，并落 bound_at——没有二次确认步骤；
3. 绑定之后：本人可见、管理员（工作台/对外 key）可见，其他登录用户一律 404；
4. 未授权手机号（users.phone 为空）不允许签署；
5. 一个用户可以绑定多份合同；同一份只能绑一次（条件更新，并发不会互相覆盖）；
6. 示例合同（2026-11-23 追加）：每个普通用户一份，生成时即归属本人、可签，
   编号 9 开头且 is_sample=1，不进工作台/对外接口，也不与其他人共享签署状态。
"""
from fastapi import APIRouter, Depends, HTTPException

from . import sample_api, store, open_api
from .users_api import _current_user

router = APIRouter()


def _mine(no: str, user: dict, allow_admin: bool = False) -> dict:
    """取一份可见合同：示例单只归本人；正式单归本人；管理员可读全量（只读）。"""
    rec = open_api._gen(no, allow_sample=True)
    if rec.get("is_sample"):
        if rec.get("signed_user_id") != user["id"]:
            raise HTTPException(404, "合同不存在")
        return rec
    if allow_admin and sample_api.is_admin(user):
        return rec
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
    """我的合同：普通用户＝本人已签合同 + 示例合同；管理员＝可见范围内全部合同。

    示例合同（2026-11-23）：每个普通用户首次查询时自动生成一份卖车示例（客户名
    「测试用户」、编号 9 开头），归属本人、可查看可签署；与他人互不影响，也不进
    工作台/对外列表（is_sample=1 过滤）。管理员看可见起始日之后的全部正式合同。
    """
    limit = max(1, min(int(limit), 200))
    if sample_api.is_admin(user):
        total, rows = store.contracts_query(date_from=open_api.VISIBLE_FROM, limit=limit)
    else:
        try:
            sample_api.ensure_sample(user["id"])
        except Exception as ex:   # 示例生成失败不拖垮列表；模板/磁盘问题留日志
            print("[sample] 示例合同生成失败:", ex)
        total, rows = store.contracts_by_user(user["id"], limit)
    return {"total": total, "items": [{
        "no": r["no"],
        "type": r["type"], "type_label": _label(r["type"]),
        "client": r["client"] or "",
        "currency": r["currency"] or "",
        "filename": r["filename"] or "",
        "created_at": r["created_at"] or "",
        # 前端判「签没签」直接看 signed（signed_at 仅供展示时间）
        "signed": bool(r.get("signed_path")),
        "signed_at": r.get("signed_at") or "",
        "bound_at": r.get("bound_at") or "",
    } for r in rows]}


@router.get("/api/users/me/contracts/{no}")
def my_contract_detail(no: str, user: dict = Depends(_current_user)):
    """本人合同详情：blocks 渲染数据 + 结构化表单，字段同对外接口的详情。"""
    _mine(no, user, allow_admin=True)
    return open_api._contract_detail(no, allow_sample=True)


@router.get("/api/users/me/contracts/{no}/file")
def my_contract_file(no: str, user: dict = Depends(_current_user)):
    """下载本人合同的已签版 docx。"""
    _mine(no, user, allow_admin=True)
    return open_api._contract_file(no, allow_sample=True)


@router.get("/api/users/me/contracts/{no}/signature")
def my_signature_image(no: str, user: dict = Depends(_current_user)):
    """本人合同的客户手写签名图（透明 PNG），用于已签页叠加显示。"""
    _mine(no, user, allow_admin=True)
    return open_api._contract_signature_image(no, allow_sample=True)


@router.post("/api/users/me/contracts/{no}/signature")
def my_sign(no: str, body: dict, user: dict = Depends(_current_user)):
    """提交手写签名：合成进合同 → 存已签版 → 自动绑定到当前登录用户。

    校验顺序：先绑手机号（未授权不允许签）→ 合同可见且未签 → 合成签名 → 条件绑定。
    示例合同已预先归属本人（不再改绑）；正式单仍遵循「签字即认领」。
    """
    if not str(user.get("phone") or "").strip():
        raise HTTPException(403, "请先授权手机号再签署")
    rec = open_api._gen(no, allow_sample=True)      # 存在/已生成/在可见范围内
    if rec.get("is_sample"):
        if rec.get("signed_user_id") != user["id"]:
            raise HTTPException(404, "合同不存在")
    elif rec.get("signed_user_id") not in (None, "", user["id"]):
        raise HTTPException(409, "该合同已被签署")
    if rec.get("signed_path"):
        raise HTTPException(409, "该合同已签署")
    res = open_api._contract_signature(no, body, allow_sample=True)   # 合成签名 + 落 -签名.png + set_signed
    if not store.bind_signed_user(no, user["id"]):
        # 正式单并发抢签：另一位用户抢先绑定。签名已落盘，但归属不写，交管理员处理；
        # 示例单事先已归属本人，bind 返回 False 属正常（跳过即可）
        if open_api._gen(no, allow_sample=True).get("signed_user_id") != user["id"]:
            raise HTTPException(409, "该合同已被签署")
    return {**res, "bound": True, "signed_user_id": user["id"]}
