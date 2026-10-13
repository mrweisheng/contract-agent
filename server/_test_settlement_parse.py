# -*- coding: utf-8 -*-
"""解析修复单测：等值后缀、段落标题变体、多形态金额。"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"E:\华星客服\简体\contract-agent\server")
from settlement import compute, service

fails = []
def check(name, cond, got=None):
    if cond:
        print(f"  ✓ {name}")
    else:
        fails.append(name)
        print(f"  ✗ {name}  got={got!r}")

print("== 用户示例全文 ==")
data = service.parse_text(TEXT) if False else None
TEXT = """业务类型：现牌结算单
群名：0906霍荣佳莲塘现牌粤Z5Q19港
客户：霍荣佳
日期：2026年10月10日
口岸：莲塘口岸
结算类型：收尾款

合同内总费用。
总价：¥230000/$271398

合同内已收费用。
合同内已收明细：
定金：58999港币；人民币、港币等值金额：¥50000/$58999（已收）

合同内未收。
车牌尾款：180000人民币；人民币、港币等值金额：¥180000/$212399（应收）

合同外杂费明细。
换车费：5000人民币（应收）
批文卡：260港币（应收）
禁区纸：744港币（应收）
核证本：300港币（应收）
中检验车：790港币（应收）
大陆保险：4819港币（应收）
合同外杂费实收。
港币现金：$5000
"""
data = service.parse_text(TEXT)
paid = data["contract_paid"][0]
check("定金币种=HKD（核心 bug）", paid["currency"] == "HKD", paid)
check("定金 cny_equiv=50000", paid.get("cny_equiv") == 50000, paid)
check("定金无冗余 hkd_equiv", "hkd_equiv" not in paid, paid)
unpaid = data["contract_unpaid"][0]
check("尾款 CNY + hkd_equiv=212399", unpaid["currency"] == "CNY" and unpaid.get("hkd_equiv") == 212399, unpaid)
check("总价双币", data["contract_total"][0]["amount"] == 230000 and data["contract_total"][0].get("hkd_equiv") == 271398)
check("业务类型入档", data.get("business") == "现牌结算单", data.get("business"))
check("杂费 6 笔", len(data["extra_fees"]) == 6, data["extra_fees"])
check("实收 HKD 5000", data["extra_paid"][0]["currency"] == "HKD" and data["extra_paid"][0]["amount"] == 5000)
check("date_iso 补齐", data.get("date_iso") == "20261010", data.get("date_iso"))

print("== 注入系统汇率后核算 ==")
data["rate"] = {"cny_to_hkd": 1.17263, "basis": "today", "source": "实时汇率", "date": "2026-10-12", "apply_101": True}
spec, detail = compute.build_spec(data)
tp = spec["today_pay"]
# 人民币口径 = 尾款 180,000（等值照用）+ 换车费 5,000 + 净港币杂费 1,913×(1/1.17263)×1.01 ≈ 1,647（正净额加 1%，2026-10-13 定稿）
check("人民币口径=186647（正净额折算×1.01）", tp.get("cny") == "¥ 186,647.00", tp)
# 用户给了尾款等值 212399 → 合同内照用；杂费按当天汇率
# extra_hkd = 1913 + 5000*1.17263*1.01 = 7834.78 → hkd = 212399+7834.78 = 220233
check("港币口径=220233（等值照用）", tp.get("hkd") == "$ 220,233.00", tp)
check("无对账误报", not any("对账不一致" in w for w in detail["warnings"]), detail["warnings"])
check("备注含尾款等值对（项目名照抄原文）", "车牌尾款為 ¥180,000.00 / $212,399.00" in (spec.get("note") or ""), spec.get("note"))

print("== 等值段变体 ==")
v = compute.parse_amount("58999港币；人民幣、港幣等值金額：¥50000/$58999")
check("繁体标签", v[0] == 58999 and v[1] == "HKD" and v[3].get("cny_equiv") == 50000, v)
v = compute.parse_amount("50000人民币/58999港币")
check("斜杠双币（港币主）", v[0] == 50000 and v[1] == "CNY" and v[2] == 58999, v)
v = compute.parse_amount("18000")
check("裸数字无币种", v[0] == 18000 and v[1] is None, v)
v = compute.parse_amount("5万港币")
check("万单位", v[0] == 50000 and v[1] == "HKD", v)

print("== 汇率分部分铁律：无等值时走当天汇率 ==")
d2 = service.parse_text("""群名：测试群
客户：测试
日期：2026年10月12日
结算类型：收尾款
合同内总费用。
总价：¥200000/$236000
合同内未收。
车牌尾款：¥100000/$118000（应收）
合同外杂费明细。
批文卡：260港币
""")
d2["rate"] = data["rate"]
spec2, detail2 = compute.build_spec(d2)
# 尾款给了等值 → 港币口径 118000 + 260 = 118260
check("等值原样取用", spec2["today_pay"].get("hkd") == "$ 118,260.00", spec2["today_pay"])

print("== 许兰坛（赠送/减免/已收0）==")
d3 = service.parse_text("""业务类型：现牌结算单
群名：0908许兰坛深圳湾现牌粤ZLT27港
客户：许兰坛
日期：2026年10月9日
口岸：深圳湾口岸
结算类型：收尾款

合同内总费用。
总价：228000人民币

合同内已收费用。
合同内已收明细：
定金：50000人民币（已收）

合同内未收。
车牌尾款：178000人民币；人民币、港币等值金额：¥178000/$210044（应收）

合同外杂费明细。
换车费（赠送）：5000人民币（赠送）（不计入应收）
批文卡（赠送）：260港币（赠送）（不计入应收）
禁区纸（赠送）：744港币（赠送）（不计入应收）
核证本（赠送）：300港币（赠送）（不计入应收）
港币现金：5000港币（减免）
合同外杂费实收。
合同外杂费已收：0
""")
fees = d3["extra_fees"]
check("四笔杂费全 gift", len(fees) == 4 and all(f.get("gift") for f in fees), fees)
check("杂费金额照留", fees and fees[0]["amount"] == 5000 and fees[0]["currency"] == "CNY", fees)
check("减免挪进实收", len(d3["extra_paid"]) == 1 and d3["extra_paid"][0]["item"] == "港币现金"
      and d3["extra_paid"][0]["amount"] == 5000 and d3["extra_paid"][0]["currency"] == "HKD", d3["extra_paid"])
check("已收0段落头", d3["extra_fees"] == fees, d3)
d3["rate"] = {"cny_to_hkd": 1.17263, "hkd_to_cny": 1/1.17263, "basis": "today", "source": "实时汇率", "date": "2026-10-09", "apply_101": True}
spec3, detail3 = compute.build_spec(d3)
tp3 = spec3["today_pay"]
# 负净额足额折（2026-10-13 定稿）：人民币 178000 − 5000×(1/1.17263) = 173,735.76 → 173,736（不加 1%）；
# 港币 210044 − 5000 = 205,044（等值照用，赠送不进算式）
check("人民币口径=173736（赠送不计、负净额足额折）", tp3.get("cny") == "¥ 173,736.00", tp3)
check("港币口径=205044", tp3.get("hkd") == "$ 205,044.00", tp3)
gift_rows = [row for s in spec3["sections"] for row in s["rows"] if row.get("status") == "gift"]
check("赠送行照显示金额", len(gift_rows) == 4 and all(abs(r["amount"]) > 0 for r in gift_rows), gift_rows)
check("赠送行名剥标记（纸面标签接管）", any(r["item"] == "换车费" for r in gift_rows), [r["item"] for r in gift_rows])

print("== 混合正负净额（CNY +10万 / HKD -1万，每边看被折净额正负）==")
d4 = {"contract_total": [{"item": "总价", "amount": 100000, "currency": "CNY", "hkd_equiv": 117224}],
      "contract_unpaid": [{"item": "尾款", "amount": 100000, "currency": "CNY", "hkd_equiv": 117224}],
      "extra_paid": [{"item": "港币现金", "amount": 10000, "currency": "HKD"}],
      "rate": {"cny_to_hkd": 1.17224, "hkd_to_cny": 1/1.17224, "basis": "today",
               "source": "实时汇率", "date": "2026-10-13", "apply_101": True}}
spec4, _ = compute.build_spec(d4)
# 人民币口径 = 100000 − 10000×(1/1.17224)（负净额足额折，不加 1%）= 91,469.37 → floor 91,469
check("负净额折人民币不加1%", spec4["today_pay"].get("cny") == "¥ 91,469.00", spec4["today_pay"])
# 港币口径 = 117224（等值照用）− 10000
check("港币口径=107224", spec4["today_pay"].get("hkd") == "$ 107,224.00", spec4["today_pay"])

print()
print("FAILED:", fails if fails else "无 — 全部通过")
sys.exit(1 if fails else 0)
