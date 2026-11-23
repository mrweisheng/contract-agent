# -*- coding: utf-8 -*-
"""「我的合同」离线测试：签字即绑定 + 按用户隔离 + 未授权手机号禁签。
隔离：库与产物全落临时目录，不碰真实数据；签名合成用真模板真引擎。"""
import sys, io, os, json, base64, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "my_contracts_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP
store.OUT_DIR = TMP
store.init()

# 公司印信打桩（builder 生成即盖章，需要 seal.png / sign.png）
os.makedirs(os.path.join(TMP, "seals"), exist_ok=True)
from PIL import Image as _PILImage
for _n, _sz, _c in (("seal.png", (60, 60), (40, 40, 160)), ("sign.png", (80, 30), (20, 20, 20))):
    _PILImage.new("RGB", _sz, _c).save(os.path.join(TMP, "seals", _n), "PNG")
from engine import seal as _seal_mod
_seal_mod.seals_dir = lambda: os.path.join(TMP, "seals")

from engine.builder import build_contract
from api import open_api, my_api, routes

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)


# ---------- 准备：一份真合同 + 三个用户（A 有手机号、B 有手机号、C 未授权） ----------
form = {"agreement_no": "", "sign_date": "2026-11-23", "currency": "HKD",
        "client_name": "陈大文", "client_id": "H123456(7)", "client_phone": "13800138000",
        "plate": "LN 1234", "vin": "WIN0000000000001", "model": "Toyota Alphard", "year": "2024",
        "total_price": 500000}
payment = {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-11-23",
           "balance_date": "2026-12-23", "choice": "较早者"}
NO = "20261123001"
FN = "20261123陈大文卖车.docx"
build_contract("car", dict(form), payment, NO, os.path.join(TMP, FN))
store.confirm_no(NO, "car", "陈大文", "default", "HKD", FN, "ok")   # created_at=现在，落在可见范围内

def mkuser(openid, phone, nickname):
    u = store.user_upsert_by_openid(openid, "")
    if phone or nickname:
        u = store.user_update(u["id"], phone=phone, nickname=nickname)
    return u

A = mkuser("o-A", "13800138000", "陈大文")
B = mkuser("o-B", "13700137000", "李小明")
C = mkuser("o-C", "", "")                      # 未授权手机号

def back(code):
    return {"image": code}

# 签名图（透明 PNG，真人签名笔迹形状无所谓，接口只校验 PNG/尺寸）
from PIL import Image, ImageDraw
_img = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
ImageDraw.Draw(_img).line([(30, 180), (200, 60), (380, 180), (560, 90)], fill=(0, 0, 0, 255), width=6)
_buf = io.BytesIO(); _img.save(_buf, "PNG")
SIG = "data:image/png;base64," + base64.b64encode(_buf.getvalue()).decode()

# 1) 签署前：谁都没有这份合同；未授权手机号禁签
check(my_api.my_contracts(A)["total"] == 0, "签署前本人列表为空")
try:
    my_api.my_contract_detail(NO, A); check(False, "签署前详情应 404")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "签署前详情 → 404")
try:
    my_api.my_sign(NO, back(SIG), C); check(False, "未授权手机号应 403")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 403, "未授权手机号签署 → 403")

# 2) A 签署 → 已签 + 自动绑定（无二次确认）
r = my_api.my_sign(NO, back(SIG), A)
check(r.get("ok") is True and r.get("bound") is True, "签署成功并绑定")
rec = store.get_gen(NO)
check(bool(rec.get("signed_path")), "signed_path 已落（状态＝已签署）")
check(rec.get("signed_user_id") == A["id"], f"signed_user_id 绑定到 A（实际 {rec.get('signed_user_id')}）")
check(bool(rec.get("bound_at")), "bound_at 已落库")

# 3) 绑定后：本人可见（列表/详情/文件/签名图）
lst = my_api.my_contracts(A)
check(lst["total"] == 1 and lst["items"][0]["no"] == NO, "本人列表查得到这份合同")
check(lst["items"][0]["type_label"] and lst["items"][0]["signed_at"], "列表带业务名与签署时间")
check(my_api.my_contract_detail(NO, A)["no"] == NO, "本人详情可取（blocks）")
check(os.path.basename(my_api.my_contract_file(NO, A).path).endswith("-已签.docx"), "本人可下载已签版")
check(os.path.basename(my_api.my_signature_image(NO, A).path).endswith("-签名.png"), "本人可取签名图")

# 4) 其他登录用户：完全看不到（列表空、详情/下载/签名一律 404）
check(my_api.my_contracts(B)["total"] == 0, "他人列表为空")
for label, fn in (("详情", lambda: my_api.my_contract_detail(NO, B)),
                  ("下载", lambda: my_api.my_contract_file(NO, B)),
                  ("签名图", lambda: my_api.my_signature_image(NO, B))):
    try:
        fn(); check(False, f"他人{label}应 404")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 404, f"他人{label} → 404（不暴露存在）")

# 5) 重复签署 / 他人抢签 都被拒
for who, label in ((A, "本人"), (B, "他人")):
    try:
        my_api.my_sign(NO, back(SIG), who); check(False, f"{label}重复签署应 409")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 409, f"{label}重复签署 → 409")

# 6) 一个用户可绑多份
NO2, FN2 = "20261123002", "20261123陈大文卖车-2.docx"
build_contract("car", dict(form), payment, NO2, os.path.join(TMP, FN2))
store.confirm_no(NO2, "car", "陈大文", "default", "HKD", FN2, "ok")
my_api.my_sign(NO2, back(SIG), A)
check(my_api.my_contracts(A)["total"] == 2, "同一用户可绑多份合同")
check(my_api.my_contracts(B)["total"] == 0, "他人仍为 0 份")

# 7) 管理员视角：合同管理列表带签署人（昵称 + 手机号）
admin = {i["no"]: i for i in routes.list_contracts()["items"]}
check(admin[NO]["signed"] is True, "管理员列表 signed=true")
check(admin[NO]["signer_nickname"] == "陈大文" and admin[NO]["signer_phone"] == "13800138000",
      "管理员列表带签署人昵称/手机号")

# 8) 可见范围外的历史单：本人也签不了（与对外接口同口径）
OLD, OLDFN = "20261121009", "20261121历史客户卖车.docx"
build_contract("car", dict(form), payment, OLD, os.path.join(TMP, OLDFN))
with store._conn() as c:
    c.execute("INSERT INTO gens(no,type,client,mode,currency,filename,status,created_at) "
              "VALUES(?,?,?,?,?,?,?,?)",
              (OLD, "car", "历史客户", "default", "HKD", OLDFN, "ok", "2026-11-21 10:00:00"))
try:
    my_api.my_sign(OLD, back(SIG), A); check(False, "可见范围外的单应 404")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "可见范围外的单签署 → 404（同对外口径）")

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
