# -*- coding: utf-8 -*-
"""合同管理列表接口离线测试：日期区间 / 客户模糊 / 业务类型 / 金额 / 状态 全部直调函数。
隔离：store.DB_PATH/DATA_DIR/OUT_DIR 落临时目录，不碰真实库与真实合同文件。"""
import sys, io, os, json, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "contracts_api_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP
store.OUT_DIR = TMP
store.init()

from api import routes

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)


def add(no, type_key, client, created, status="ok", signed="", currency="HKD", filename=None, uid=None):
    fn = filename if filename is not None else f"{client}{type_key}.docx"
    with store._conn() as c:
        c.execute(
            "INSERT INTO gens(no,type,client,mode,currency,filename,status,created_at,"
            "signed_path,signed_user_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (no, type_key, client, "default", currency, fn, status, created, signed, uid))


# 签署人资料三态（2026-11-25）：昵称/手机/头像都可能缺失，签名图只要有签名就一定有
def mk_user(openid, **fields):
    u = store.user_upsert_by_openid(openid)
    return store.user_update(u["id"], **fields)

u_full = mk_user("o_full", nickname="陈大文", phone="13800138000",
                 avatar_path="avatars/a.jpg", avatar_ver=3)
u_avatar = mk_user("o_avatar", avatar_path="avatars/b.jpg", avatar_ver=1)
u_none = mk_user("o_none")

# 三份有效单（不同日期/业务/客户）+ 失败单 + pending 占位（都不该出现在列表里）
add("20261123001", "car", "陈大文", "2026-11-23 10:00:00", signed="x-已签.docx", uid=u_full["id"])
add("20261120002", "car_buy", "李小明", "2026-11-20 09:30:00", currency="CNY", uid=u_avatar["id"])
add("20261101003", "immigration", "陳大丈", "2026-11-01 23:59:59", uid=u_none["id"])
add("20261123004", "car", "王失败", "2026-11-23 11:00:00", status="failed")
add("20261123005", "car", "王占位", "2026-11-23 12:00:00", status="pending")

# 给第一份建 form.json（金额取 total_price），第二份建（total=total_fee 不适用 → 走 None）
def write_form(filename, form):
    with open(os.path.join(TMP, filename.rsplit(".docx", 1)[0] + ".form.json"), "w", encoding="utf-8") as f:
        json.dump({"form": form, "payment": {}}, f, ensure_ascii=False)

write_form("陈大文car.docx", {"total_price": 500000})
write_form("陳大丈immigration.docx", {"total_fee": 128000})

# 1) 默认全量：只含 ok，按时间倒序
r = routes.list_contracts()
check(r["total"] == 3, f"total 只数 ok 单（实际 {r['total']}）")
check([i["no"] for i in r["items"]] == ["20261123001", "20261120002", "20261101003"], "按生成时间倒序")
check(all(i["type_label"] for i in r["items"]), "type_label 已下发（不是裸 key）")

# 2) 金额：卖车取 total_price；高才取 total_fee；没有存档的是 None
by_no = {i["no"]: i for i in r["items"]}
check(by_no["20261123001"]["amount"] == 500000, "卖车金额取 total_price")
check(by_no["20261101003"]["amount"] == 128000, "高才金额取 total_fee")
check(by_no["20261120002"]["amount"] is None, "无存档金额 → None（前端显示 —）")
check(by_no["20261123001"]["signed"] is True and by_no["20261120002"]["signed"] is False, "已签标记")

# 2.1) 签署人资料：昵称/手机/头像齐全；只有头像；全无 → 空串（不是 None）
check(by_no["20261123001"]["signer_nickname"] == "陈大文"
      and by_no["20261123001"]["signer_phone"] == "13800138000", "签署人昵称+手机")
check(by_no["20261123001"]["signer_avatar_url"] == "/api/users/%d/avatar?v=3" % u_full["id"],
      "签署人头像 URL 带版本号（换头像不吃缓存）")
check(by_no["20261120002"]["signer_avatar_url"].endswith("?v=1"), "只有头像也下发头像 URL")
check(by_no["20261120002"]["signer_nickname"] == "" and by_no["20261120002"]["signer_phone"] == "",
      "未授权昵称/手机 → 空串")
check(by_no["20261101003"]["signer_avatar_url"] == "", "无任何微信资料 → 头像 URL 为空")
check(by_no["20261123001"]["signer_bound"] is True, "已绑定签署人标记")
check("20261123004" not in by_no, "失败单不参与列表（无 signer_bound 可查）")

# 2.2) 后台签名图：有签名文件才 200；未签/文件缺失一律 404
sig_name = "陈大文car-签名.png"
with open(os.path.join(TMP, sig_name), "wb") as fh:
    fh.write(b"\x89PNG\r\n\x1a\n")
resp = routes.contract_signature_image("20261123001")
check(os.path.basename(resp.path) == sig_name, "已签合同可取签名 PNG")
check(resp.headers.get("cache-control") == "private, no-store", "签名图不缓存（重签后不吃旧图）")
check(routes.contract_signature_image.__name__ == "contract_signature_image", "签名图路由已注册")
for no, label in (("20261120002", "未签合同"), ("20261199999", "不存在合同")):
    try:
        routes.contract_signature_image(no); check(False, f"{label}应 404")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 404, f"{label} → 404")
os.remove(os.path.join(TMP, sig_name))
try:
    routes.contract_signature_image("20261123001"); check(False, "签名文件缺失应 404")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "签名文件缺失 → 404")

# 3) 日期区间：含边界
r = routes.list_contracts(date_from="2026-11-20", date_to="2026-11-23")
check([i["no"] for i in r["items"]] == ["20261123001", "20261120002"], "日期区间（含两端边界）")
r = routes.list_contracts(date_from="2026-11-21")
check([i["no"] for i in r["items"]] == ["20261123001"], "只给起始日期")
r = routes.list_contracts(date_to="2026-11-01")
check([i["no"] for i in r["items"]] == ["20261101003"], "只给结束日期（当日 23:59 也命中）")
check(routes.list_contracts(date_from="2026-11-24")["total"] == 0, "区间内无单 → 0")

# 4) 客户模糊搜索（中英混、部分匹配）
r = routes.list_contracts(client="陈")
check([i["no"] for i in r["items"]] == ["20261123001"], "客户模糊：简体「陈」只命中陈大文")
r = routes.list_contracts(client="陳")
check([i["no"] for i in r["items"]] == ["20261101003"], "客户模糊：繁体「陳」命中陳大丈")
check(routes.list_contracts(client="小明")["items"][0]["no"] == "20261120002", "客户模糊：中间字命中")
check([i["no"] for i in routes.list_contracts(client="13800138000")["items"]] == ["20261123001"],
      "按签署人手机号搜索")
check([i["no"] for i in routes.list_contracts(client="20261123001")["items"]] == ["20261123001"],
      "按合同编号搜索")
check(routes.list_contracts(client="王")["total"] == 0, "失败/占位单不参与搜索")

# 5) 业务类型精确筛选 + 与日期/客户组合
check([i["no"] for i in routes.list_contracts(type="car")["items"]] == ["20261123001"], "按业务类型筛")
r = routes.list_contracts(type="car", client="陈", date_from="2026-11-23")
check([i["no"] for i in r["items"]] == ["20261123001"], "类型+客户+日期 组合")
check(routes.list_contracts(type="immigration", client="陈")["total"] == 0, "组合无交集 → 0")

# 6) 参数安全与边界：SQL 注入串按普通字面量处理；limit 收敛到 1..500
check(routes.list_contracts(client="' OR 1=1 --")["total"] == 0, "客户参数走占位符，注入串不生效")
check(len(routes.list_contracts(limit=0)["items"]) == 1, "limit=0 收敛为 1")
check(len(routes.list_contracts(limit=9999)["items"]) == 3, "limit 超上限不报错（3 条全出）")
check(routes.list_contracts()["items"][0]["created_at"] == "2026-11-23 10:00:00", "created_at 原样下发")

# 7) 日期格式校验：非法串 422（不是静默返回 0 条）
for bad in ("abc", "2026-11", "2026/11/20", "20261120"):
    try:
        routes.list_contracts(date_from=bad); check(False, f"日期 {bad} 应 422")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 422, f"日期 {bad} → 422")

# 8) 重置签署（管理端重测）：解绑微信用户 + 清已签状态 + 旧文件留档，可再次分享签署
#    放在最后：重置会取消绑定，不能影响上面的「按签署人手机号搜索」等断言。
with open(os.path.join(TMP, sig_name), "wb") as fh:
    fh.write(b"\x89PNG\r\n\x1a\n")
with open(os.path.join(TMP, "陈大文car-已签.docx"), "wb") as fh:
    fh.write(b"docx")
res = routes.reset_contract_signature("20261123001")
rec = store.get_gen("20261123001")
check(res["ok"] and len(res["backup"]) == 2, "重置签署并留档已签 docx + 签名图")
check(not rec.get("signed_path") and not rec.get("signed_at")
      and not rec.get("signed_user_id") and not rec.get("bound_at"),
      "签署状态 / 签署时间 / 用户绑定已清空")
for name in res["backup"]:
    check(os.path.exists(os.path.join(TMP, "_signed_reset", "20261123001", name)), "备份文件已落盘")
r = routes.list_contracts(client="20261123001")
check(r["items"][0]["signed"] is False and r["items"][0]["signer_bound"] is False,
      "列表回到未签 / 未绑定，可重新签")
try:
    routes.contract_signature_image("20261123001"); check(False, "重置后签名图应 404")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 404, "重置后签名图 → 404")
try:
    routes.reset_contract_signature("20261123001"); check(False, "重复重置应 409")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 409, "重复重置 → 409")

# 9) 未签合同不能被绑定（防止「刚重置、迟到的绑定」把未签单绑到用户名下）
add("20261125006", "car", "未签绑定", "2026-11-25 12:00:00")
check(store.bind_signed_user("20261125006", u_full["id"]) is False, "未签合同不可绑定用户")
check(store.get_gen("20261125006")["signed_user_id"] is None, "绑定条件未命中时保持未绑定")

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
