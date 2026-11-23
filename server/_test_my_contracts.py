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
from api import open_api, my_api, routes, sample_api

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

# 1) 签署前：本人列表只有示例合同；正式单仍不可见；未授权手机号禁签
lst_a0 = my_api.my_contracts(A)
check(lst_a0["total"] == 1 and lst_a0["items"][0]["no"] == sample_api.sample_no(A["id"]),
      "签署前本人列表＝示例合同（1 份）")
check(lst_a0["items"][0]["client"] == "测试用户" and lst_a0["items"][0]["type"] == "car",
      "示例合同为卖车业务、客户名=测试用户")
check(lst_a0["items"][0]["signed"] is False and lst_a0["items"][0]["signed_at"] == "",
      "未签示例返回 signed=false")
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
nos = {i["no"] for i in lst["items"]}
check(lst["total"] == 2 and NO in nos and sample_api.sample_no(A["id"]) in nos,
      "本人列表＝正式单 + 示例合同")
row = next(i for i in lst["items"] if i["no"] == NO)
check(row["type_label"] and row["signed_at"] and row["signed"] is True,
      "列表带业务名、签署时间，且 signed=true")
s_row = next(i for i in lst["items"] if i["no"] == sample_api.sample_no(A["id"]))
check(s_row["signed"] is False, "同一列表里示例合同仍为未签（signed=false）")
check(my_api.my_contract_detail(NO, A)["no"] == NO, "本人详情可取（blocks）")
check(os.path.basename(my_api.my_contract_file(NO, A).path).endswith("-已签.docx"), "本人可下载已签版")
check(os.path.basename(my_api.my_signature_image(NO, A).path).endswith("-签名.png"), "本人可取签名图")

# 4) 其他登录用户：正式单完全看不到；只看到自己的示例合同
lst_b = my_api.my_contracts(B)
check(lst_b["total"] == 1 and lst_b["items"][0]["no"] == sample_api.sample_no(B["id"]),
      "他人列表只有自己的示例合同")
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
check(my_api.my_contracts(A)["total"] == 3 and my_api.my_contracts(B)["total"] == 1,
      "同一用户可绑多份合同（A=正式2+示例1，B=仅示例1）")

# 6b) 示例合同：详情可看、可签、互不影响，且不进工作台列表
SNO, SNO_B = sample_api.sample_no(A["id"]), sample_api.sample_no(B["id"])
d_s = my_api.my_contract_detail(SNO, A)
check(d_s["no"] == SNO and d_s["type_label"] and d_s["blocks"], "示例合同详情可取（blocks）")
check(d_s["content"]["form"]["client_name"] == "测试用户", "示例结构化数据客户名=测试用户")
try:
    my_api.my_contract_detail(SNO, B); check(False, "他人示例详情应 404")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "他人示例详情 → 404")
r_s = my_api.my_sign(SNO, back(SIG), A)
check(r_s.get("ok") is True and r_s.get("bound") is True, "示例合同签署成功")
rec_s = store.get_gen(SNO)
check(bool(rec_s.get("signed_path")) and rec_s.get("signed_user_id") == A["id"],
      "示例已签版落盘并归属 A")
s_row2 = next(i for i in my_api.my_contracts(A)["items"] if i["no"] == SNO)
check(s_row2["signed"] is True and bool(s_row2["signed_at"]),
      "签署后列表返回 signed=true + signed_at")
check(my_api.my_contract_detail(SNO, A)["signed"] is True, "详情同步 signed=true")
check(not store.get_gen(SNO_B).get("signed_path"), "B 的示例合同不受影响（仍未签）")
try:
    open_api.contract_detail(SNO); check(False, "对外接口不应看到示例合同")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "对外接口看不到示例合同（404）")
check(os.path.basename(my_api.my_contract_file(SNO, A).path).endswith("-已签.docx"),
      "示例已签版可下载")
try:
    my_api.my_sign(SNO, back(SIG), A); check(False, "示例重复签署应 409")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 409, "示例重复签署 → 409")
try:
    my_api.my_sign(sample_api.sample_no(C["id"]), back(SIG), C); check(False, "未授权手机号签示例应 403")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 403, "未授权手机号签示例 → 403")

# 7) 管理员视角：合同管理列表带签署人（昵称 + 手机号），且不混入示例合同
admin = {i["no"]: i for i in routes.list_contracts()["items"]}
check(admin[NO]["signed"] is True, "管理员列表 signed=true")
check(admin[NO]["signer_nickname"] == "陈大文" and admin[NO]["signer_phone"] == "13800138000",
      "管理员列表带签署人昵称/手机号")
check(SNO not in admin and SNO_B not in admin, "示例合同不进工作台合同列表")

# 7b) 管理员在「我的合同」里看可见范围内全部正式合同（含他人单），但仍看不到示例
A = store.user_update(A["id"], role="admin")
adm = my_api.my_contracts(A)
adm_nos = {i["no"] for i in adm["items"]}
check(NO in adm_nos and NO2 in adm_nos and SNO not in adm_nos,
      "管理员列表＝全部正式合同（可见范围内），不含示例")
check(my_api.my_contract_detail(NO2, A)["no"] == NO2, "管理员可读他人合同详情")
A = store.user_update(A["id"], role="user")

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
