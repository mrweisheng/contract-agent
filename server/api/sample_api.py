# -*- coding: utf-8 -*-
"""示例合同（2026-11-23）：每个普通用户一份「车辆买卖」示例，供新用户查看与签署演练。

设计口径：
- 结构完全复用正式卖车模板（8 份业务模板之一），只把客户信息写成「测试用户」；
- 每个普通用户各一份、编号以 9 开头（11 位，与正式 YYYYMMDD 编号不可能撞号），
  互相隔离：A 签了不影响 B，A 的签名也不会出现在 B 的示例里；
- 管理员（admin/super）不生成示例，走另一条「全部合同」查询分支；
- is_sample=1，工作台合同列表 / 最近生成 / 对外查询接口一律不展示。
"""
import datetime
import json
import os
import threading

from . import store

SAMPLE_TYPE = "car"
SAMPLE_CLIENT = "测试用户"
ADMIN_ROLES = ("admin", "super")

# 同一进程内串行生成，避免并发首刷时重复建单（多进程部署下由主键/文件名收敛）
_lock = threading.Lock()


def is_admin(user: dict) -> bool:
    return (user.get("role") or "user") in ADMIN_ROLES


def sample_no(uid: int) -> str:
    return f"9{int(uid):010d}"


def _form() -> dict:
    today = datetime.date.today().isoformat()
    return {
        "agreement_no": "",
        "sign_date": today,
        "currency": "HKD",
        "client_name": SAMPLE_CLIENT,
        "client_id": "TEST-000001",
        "client_contact": SAMPLE_CLIENT,
        "client_phone": "91234567",
        "client_address": "香港特別行政區測試地址 1 號",
        "plate": "TEST 1234",
        "vin": "TESTVIN0000000001",
        "model": "Toyota Alphard",
        "year": "2024",
        "total_price": 500000,
    }


def _payment() -> dict:
    today = datetime.date.today()
    return {
        "mode": "default",
        "deposit_amount": 100000,
        "deposit_date": today.isoformat(),
        "balance_date": (today + datetime.timedelta(days=30)).isoformat(),
        "choice": "较早者",
    }


def ensure_sample(uid: int) -> dict:
    """确保该用户有一份示例合同（库记录 + docx + form.json），返回 gens 行。"""
    no = sample_no(uid)
    filename = f"{no}-{SAMPLE_CLIENT}卖车.docx"
    path = os.path.join(store.OUT_DIR, filename)
    rec = store.get_gen(no)
    if rec and os.path.exists(path):
        return rec

    with _lock:
        rec = store.get_gen(no)
        if rec and os.path.exists(path):
            return rec
        os.makedirs(store.OUT_DIR, exist_ok=True)
        from engine.builder import build_contract
        form, payment = _form(), _payment()
        build_contract(SAMPLE_TYPE, dict(form), payment, no, path)
        form_doc = {
            "no": no, "type": SAMPLE_TYPE, "form": form, "payment": payment,
            "filename": filename, "status": "ok",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        form_path = os.path.join(store.OUT_DIR, filename.rsplit(".docx", 1)[0] + ".form.json")
        with open(form_path, "w", encoding="utf-8") as fh:
            json.dump(form_doc, fh, ensure_ascii=False)
        store.create_sample_gen(no, uid, SAMPLE_CLIENT, filename)
        return store.get_gen(no)
