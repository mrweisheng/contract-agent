# -*- coding: utf-8 -*-
"""端到端管线测试（不调用 LLM）：三种付款模式 × 四个业务类型。"""
import os
import sys
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from engine.builder import build_contract
from engine.checker import check_rules, check_fingerprint, extract_contract_text
from engine.types_config import get_type
from docx import Document

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "data", "test_out")
os.makedirs(OUT, exist_ok=True)

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
        {"seq": 1, "amount": 100000, "trigger": "签约当日支付", "trigger_type": "event"},
        {"seq": 2, "amount": 100000, "trigger": "2026年10月10日支付", "trigger_type": "date"},
        {"seq": 3, "amount": 100000, "trigger": "2026年11月10日支付", "trigger_type": "date"},
        {"seq": 4, "amount": 100000, "trigger": "2026年12月10日支付", "trigger_type": "date"},
        {"seq": 5, "amount": 100000, "trigger": "2027年1月10日支付", "trigger_type": "date"},
    ]}),
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
    # ---- 新办：港币一次性（沙头角）----
    ("new_onetime", "new_port", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "HKD", "port": "沙头角口岸",
        "client_name": "孙八", "client_id": "H9998887", "client_phone": "97788990",
        "total_fee": 300000,
    }, {"mode": "one_time", "pay_date": "2026-09-20", "pay_event": "", "choice": "较早者"}),
]


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
                print(f"[PASS] {name}")
        except Exception as ex:
            all_ok = False
            print(f"[ERROR] {name}: {ex}")
            import traceback
            traceback.print_exc()
    print("\n总体:", "全部通过" if all_ok else "存在失败")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
