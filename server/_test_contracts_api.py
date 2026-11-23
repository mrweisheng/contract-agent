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


def add(no, type_key, client, created, status="ok", signed="", currency="HKD", filename=None):
    fn = filename if filename is not None else f"{client}{type_key}.docx"
    with store._conn() as c:
        c.execute(
            "INSERT INTO gens(no,type,client,mode,currency,filename,status,created_at,signed_path) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (no, type_key, client, "default", currency, fn, status, created, signed))


# 三份有效单（不同日期/业务/客户）+ 失败单 + pending 占位（都不该出现在列表里）
add("20261123001", "car", "陈大文", "2026-11-23 10:00:00", signed="x-已签.docx")
add("20261120002", "car_buy", "李小明", "2026-11-20 09:30:00", currency="CNY")
add("20261101003", "immigration", "陳大丈", "2026-11-01 23:59:59")
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

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
