# -*- coding: utf-8 -*-
"""端到端管线测试（不调用 LLM）：三种付款模式 × 四个业务类型。"""
import os
import sys
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from engine.builder import build_contract, derive_payment
from engine.checker import check_rules, check_fingerprint, extract_contract_text
from engine.types_config import get_type
from docx import Document

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "data", "test_out")
# 每次运行前清空历史产物：用例文件名固定，重跑会触发 builder 的旧件归档逻辑而堆积归档文件。
# 用逐文件删除而非 rmtree（后者在部分受保护环境下会失败）。
os.makedirs(OUT, exist_ok=True)
for _f in os.listdir(OUT):
    if _f.lower().endswith(".docx"):
        try:
            os.remove(os.path.join(OUT, _f))
        except OSError:
            pass

CASES = [
    # ---- 卖车：默认两段 ----
    ("car_default", "car", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "HKD",
        "client_name": "陈大文", "client_id": "H123456(7)", "client_contact": "",
        "client_phone": "91234567", "client_address": "",
        "plate": "LN 1234", "vin": "WBA12345678ABCD12", "model": "Toyota Alphard 3.5", "year": "2022",
        "total_price": 500000,
    }, {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-08-31",
        "balance_date": "2026-09-30", "choice": "较早者"}),
    # ---- 卖车：客户只约定"尾款过户完成当日付"（无尾款日期 → 03 条改写单事件句，不出现日期）----
    ("car_default_event", "car", {
        "agreement_no": "", "sign_date": "2026-09-02", "currency": "HKD",
        "client_name": "张三", "client_id": "H1234567", "client_phone": "91234567",
        "plate": "LN 1234", "vin": "WBA123456789", "model": "Toyota Alphard", "year": "2022",
        "total_price": 500000,
    }, {"mode": "default", "deposit_amount": 150000, "deposit_date": "2026-09-02",
        "balance_event": "车辆完成香港运输署过户登记手续当日"}),
    # ---- 卖车：一次性付清 ----
    ("car_onetime", "car", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "CNY",
        "client_name": "李四", "client_id": "P9876543", "client_phone": "66001122",
        "plate": "KM 5678", "vin": "JTE12345678000123", "model": "BMW X5", "year": "2023",
        "total_price": 800000,
    }, {"mode": "one_time", "pay_date": "2026-09-15", "pay_event": "车辆完成过户登记手续当日", "choice": "较早者"}),
    # ---- 卖车：自定义五期（用户举过的例子）----
    ("car_custom", "car", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "HKD",
        "client_name": "王五", "client_id": "H7654321", "client_phone": "90987654",
        "plate": "SB 8888", "vin": "WDD1234567A888888", "model": "Mercedes V-Class", "year": "2021",
        "total_price": 500000,
    }, {"mode": "custom", "installments": [
        {"seq": 1, "amount": 100000, "label": "定金", "trigger": "签约当日支付", "trigger_date": "2026-08-31", "trigger_type": "mixed"},
        {"seq": 2, "amount": 100000, "trigger": "每月10号支付", "trigger_date": "2026-10-10", "trigger_type": "date"},
        {"seq": 3, "amount": 100000, "trigger": "每月10号支付", "trigger_date": "2026-11-10", "trigger_type": "date"},
        {"seq": 4, "amount": 100000, "trigger": "每月10号支付", "trigger_date": "2026-12-10", "trigger_type": "date"},
        {"seq": 5, "amount": 100000, "trigger": "每月10号支付", "trigger_date": "2027-01-10", "trigger_type": "date"},
    ]}),
    # ---- 卖车：款项名称兜底（超长 / 重名 → 全部退回第X期）----
    ("car_label_fallback", "car", {
        "agreement_no": "", "sign_date": "2026-09-01", "currency": "HKD",
        "client_name": "冯十一", "client_id": "H5566778", "client_phone": "96667777",
        "plate": "LT 1111", "vin": "WBA111222333AAA11", "model": "Lexus LM", "year": "2023",
        "total_price": 300000,
    }, {"mode": "custom", "installments": [
        {"seq": 1, "amount": 100000, "label": "首期款项支付费用", "trigger": "签约当日支付", "trigger_date": "2026-09-01", "trigger_type": "date"},
        {"seq": 2, "amount": 100000, "label": "定金", "trigger": "2026年10月1日支付", "trigger_date": "2026-10-01", "trigger_type": "date"},
        {"seq": 3, "amount": 100000, "label": "定金", "trigger": "2026年11月1日支付", "trigger_date": "2026-11-01", "trigger_type": "date"},
    ]}),
    # ---- 卖车：新车未上牌，车牌留空（选填，合同车辆表填"—"）----
    ("car_noplate", "car", {
        "agreement_no": "", "sign_date": "2026-09-02", "currency": "HKD",
        "client_name": "王新车", "client_id": "H7788990", "client_phone": "93334444",
        "plate": "", "vin": "WBA777888999AAA22", "model": "Toyota Alphard", "year": "2026",
        "total_price": 500000,
    }, {"mode": "default", "deposit_amount": 150000, "deposit_date": "2026-09-02",
        "balance_event": "车辆完成香港运输署过户登记手续当日"}),

    # ---- 高新过户：默认三期 + 换车费 ----
    ("gx_default", "transfer_gx", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "HKD",
        "client_name": "张三", "client_id": "H1112223", "client_phone": "93001122",
        "plate": "粤Z·H123港", "port": "深圳湾口岸", "quota_type": "高新",
        "target_hk_company": "香港example有限公司",
        "total_fee": 300000, "exchange_fee": 20000,
    }, {"mode": "default", "pay1": 100000, "pay2": 150000, "pay3": 50000}),
    # ---- 纳税过户：自定义四期 ----
    ("ns_custom", "transfer_ns", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "CNY",
        "client_name": "赵六", "client_id": "H3334445", "client_phone": "94455667",
        "plate": "粤Z·N456港", "port": "港珠澳大桥口岸", "quota_type": "纳税",
        "target_hk_company": "香港AB有限公司", "target_ml_company": "深圳市CD科技有限公司",
        "total_fee": 400000, "exchange_fee": 0,
    }, {"mode": "custom", "installments": [
        {"seq": 1, "amount": 100000, "trigger": "签约当日支付", "trigger_type": "event"},
        {"seq": 2, "amount": 100000, "trigger": "完成两家公司股权转让文件后支付", "trigger_type": "event"},
        {"seq": 3, "amount": 100000, "trigger": "交付新行驶证及批文卡时支付", "trigger_type": "event"},
        {"seq": 4, "amount": 100000, "trigger": "交付铁牌资料时支付", "trigger_type": "event"},
    ]}),
    # ---- 新办：默认三期（人民币）----
    ("new_default", "new_port", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "CNY", "port": "莲塘口岸",
        "client_name": "钱七", "client_id": "4415**********1234", "client_phone": "13800138000",
        "total_fee": 200000,
    }, {"mode": "default", "pay1": 50000, "pay2": 100000, "pay3": 50000}),
    # ---- 新办：自定义两期（一期有日期、一期事件触发，验 single_rmb 表加日期列）----
    ("new_custom", "new_port", {
        "agreement_no": "", "sign_date": "2026-09-01", "currency": "CNY", "port": "港珠澳大桥口岸",
        "client_name": "吴十", "client_id": "4415**********5678", "client_phone": "13900139000",
        "total_fee": 200000,
    }, {"mode": "custom", "installments": [
        {"seq": 1, "amount": 100000, "label": "定金", "trigger": "签约当日支付", "trigger_date": "2026-09-01", "trigger_type": "mixed"},
        {"seq": 2, "amount": 100000, "label": "尾款", "trigger": "省厅批复后3个工作日内支付", "trigger_type": "event"},
    ]}),
    # ---- 新办：港币一次性（沙头角）----
    ("new_onetime", "new_port", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "HKD", "port": "沙头角口岸",
        "client_name": "孙八", "client_id": "H9998887", "client_phone": "97788990",
        "total_fee": 300000,
    }, {"mode": "one_time", "pay_date": "2026-09-20", "pay_event": "", "choice": "较早者"}),
]


CAR_FORM = {
    "agreement_no": "", "sign_date": "2026-09-01", "currency": "HKD",
    "client_name": "边界", "client_id": "H0000001", "client_phone": "90000000",
    "plate": "ED 0001", "vin": "EDGE000000000001", "model": "Edge Car", "year": "2024",
    "total_price": 500000,
}
NEG_CASES = [
    ("订金≥总价", {"mode": "default", "deposit_amount": 600000, "deposit_date": "2026-09-01",
                    "balance_date": "2026-10-01", "choice": "较早者"}),
    ("订金为0", {"mode": "default", "deposit_amount": 0, "deposit_date": "2026-09-01",
                  "balance_date": "2026-10-01", "choice": "较早者"}),
    ("分期含0金额", {"mode": "custom", "installments": [
        {"seq": 1, "amount": 0, "trigger": "签约当日", "trigger_date": "2026-09-01"},
        {"seq": 2, "amount": 500000, "trigger": "过户当日"},
    ]}),
    ("分期无任何付款时点", {"mode": "custom", "installments": [
        {"seq": 1, "amount": 100000, "trigger": "签约当日支付", "trigger_date": "2026-09-01"},
        {"seq": 2, "amount": 400000, "trigger": ""},   # 既无日期也无条件
    ]}),
]


def run_negative():
    """负向用例：必须被 ValueError 拦截且报错信息可读。"""
    ok = True
    out = os.path.join(OUT, "_neg.docx")
    for name, payment in NEG_CASES:
        try:
            build_contract("car", dict(CAR_FORM), payment, "2026090199", out)
            print(f"[FAIL] {name}: 未拦截")
            ok = False
        except ValueError as ex:
            print(f"[PASS] {name}（拦截：{ex}）")
    if os.path.exists(out):
        os.remove(out)
    return ok


# 用例 → 费用表行名预期（校验款项名称提取与兜底）
EXPECT_LABELS = {
    "car_custom": ["车辆总售价", "定金", "第二期", "第三期", "第四期", "第五期"],
    "car_label_fallback": ["车辆总售价", "第一期", "第二期", "第三期"],
    "new_custom": ["服务总费用", "定金", "尾款"],
}

# 用例 → 默认三期定金条款应展开的绝对日期（生成日=签约日）
EXPECT_DEPOSIT_DATE = {
    "gx_default": "2026年8月31日",
    "new_default": "2026年8月31日",
}

# 用例 → 卖车 03 条尾款句原文（锁死：客户没给尾款日期，合同就不得出现日期）
EXPECT_BALANCE_CLAUSE = {
    "car_default": "购车尾款须于2026年9月30日或车辆完成香港运输署过户登记手续当日，由乙方一次性支付予甲方。",
    "car_default_event": "购车尾款须于车辆完成香港运输署过户登记手续当日，由乙方一次性支付予甲方。",
}

# 用例 → 条款区改写后必须原样保留的无关条款（新办 03 区混有非付款条款）
EXPECT_KEEP = {
    "new_custom": ["费用范围", "逾期付款", "乙方指定收款账户", "付款效力"],
    "new_onetime": ["费用范围", "逾期付款", "乙方指定收款账户", "付款效力"],
}


# 统一付款表 → derive_payment 判定用例（None=应被 ValueError 拦截）
DERIVE_CASES = [
    ("新办·匹配预设→default", "new_port", [
        {"label": "定金", "amount": 50000, "date": "2026-09-01", "event": ""},
        {"label": "", "amount": 100000, "date": None, "event": "甲方香港公司成功入股大陆高新企业，完成省厅系统提交并获得提交编号后，于1个工作日内支付"},
        {"label": "", "amount": 100000, "date": None, "event": "乙方完成两地牌代办申请并取得车辆行驶证、批文卡及禁区纸后，甲方在乙方处领取车辆铁牌等通关资料时现场支付"},
    ], {"mode": "default", "pay1": 50000, "pay2": 100000, "pay3": 100000}),
    ("过户·节点偏差→custom", "transfer_gx", [
        {"label": "定金", "amount": 100000, "date": "2026-09-01", "event": ""},
        {"label": "", "amount": 100000, "date": None, "event": "提交资料后3日内支付"},
        {"label": "", "amount": 100000, "date": None, "event": "过户完成后支付"},
    ], {"mode": "custom"}),
    ("单期→one_time", "new_port", [
        {"label": "", "amount": 250000, "date": "2026-09-20", "event": ""},
    ], {"mode": "one_time", "pay_date": "2026-09-20", "pay_event": ""}),
    ("卖车·匹配预设→default", "car", [
        {"label": "订金", "amount": 100000, "date": "2026-09-01", "event": ""},
        {"label": "尾款", "amount": 400000, "date": "2026-09-30", "event": "车辆完成香港运输署过户登记手续当日"},
    ], {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-09-01", "balance_date": "2026-09-30"}),
    ("卖车·尾款纯事件→不造日期", "car", [
        {"label": "订金", "amount": 150000, "date": "2026-09-02", "event": ""},
        {"label": "尾款", "amount": 350000, "date": None, "event": "车辆完成香港运输署过户登记手续当日"},
    ], {"mode": "default", "deposit_amount": 150000, "deposit_date": "2026-09-02",
        "balance_date": None, "balance_event": "车辆完成香港运输署过户登记手续当日"}),
    ("卖车·订金缺日期→拦截", "car", [
        {"label": "订金", "amount": 150000, "date": None, "event": ""},
        {"label": "尾款", "amount": 350000, "date": None, "event": "车辆完成香港运输署过户登记手续当日"},
    ], None),
    ("某期无日期无条件→拦截", "new_port", [
        {"label": "定金", "amount": 50000, "date": "2026-09-01", "event": ""},
        {"label": "", "amount": 100000, "date": None, "event": ""},
        {"label": "", "amount": 100000, "date": None, "event": "乙方完成两地牌代办申请并取得车辆行驶证、批文卡及禁区纸后，甲方在乙方处领取车辆铁牌等通关资料时现场支付"},
    ], None),
]


def run_derive():
    ok = True
    for name, tkey, rows, expect in DERIVE_CASES:
        try:
            got = derive_payment(tkey, {"installments": rows})
            if expect is None:
                print(f"[FAIL] {name}: 未拦截")
                ok = False
                continue
            bad = {k: got.get(k) for k, v in expect.items() if got.get(k) != v}
            if bad:
                print(f"[FAIL] {name}: 不符项 {bad}")
                ok = False
            else:
                print(f"[PASS] {name}")
        except ValueError as ex:
            if expect is None:
                print(f"[PASS] {name}（拦截：{ex}）")
            else:
                print(f"[FAIL] {name}: 异常 {ex}")
                ok = False
    return ok


def main():
    all_ok = True
    for name, tkey, form, payment in CASES:
        cfg = get_type(tkey)
        out = os.path.join(OUT, f"{name}.docx")
        try:
            no = f"2026083199{len(name):02d}"
            report = build_contract(tkey, form, payment, no, out)
            report["agreement_no"] = no
            doc = Document(out)
            errs = check_rules(tkey, form, payment, report, doc)
            errs += check_fingerprint(report["template"], out, tkey, report)
            if errs:
                all_ok = False
                print(f"[FAIL] {name}")
                for e in errs:
                    print(f"   - {e}")
            else:
                from engine import writer as W
                body = "\n".join(p.text for p in doc.paragraphs)
                t = W.find_table(doc, cfg["fee_table_anchor"])
                got_labels = [r.cells[0].text.strip().splitlines()[0] for r in t.rows]
                fails = []
                if name in EXPECT_LABELS and got_labels != EXPECT_LABELS[name]:
                    fails.append(f"行名 {got_labels} ≠ 预期 {EXPECT_LABELS[name]}")
                if name in EXPECT_DEPOSIT_DATE and f"（{EXPECT_DEPOSIT_DATE[name]}）支付" not in body:
                    fails.append(f"定金条款未展开绝对日期 {EXPECT_DEPOSIT_DATE[name]}")
                if name in EXPECT_BALANCE_CLAUSE and EXPECT_BALANCE_CLAUSE[name] not in body:
                    fails.append(f"尾款条款 ≠ 预期「{EXPECT_BALANCE_CLAUSE[name]}」")
                keep = EXPECT_KEEP.get(name)
                if keep:
                    missing = [k for k in keep if k not in body]
                    if missing:
                        fails.append(f"条款区改写误删无关条款 {missing}")
                if fails:
                    all_ok = False
                    print(f"[FAIL] {name}")
                    for f_ in fails:
                        print(f"   - {f_}")
                else:
                    print(f"[PASS] {name}")
        except Exception as ex:
            all_ok = False
            print(f"[ERROR] {name}: {ex}")
            import traceback
            traceback.print_exc()
    all_ok = all_ok and run_negative() and run_derive()
    print("\n总体:", "全部通过" if all_ok else "存在失败")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
