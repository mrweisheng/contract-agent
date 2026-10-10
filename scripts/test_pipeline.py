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
    # ---- 卖车：附赠全开 + 质保只给时长（公里用默认，用户值在前）----
    ("car_gifts_full", "car", {
        "agreement_no": "", "sign_date": "2026-09-05", "currency": "HKD",
        "client_name": "周赠", "client_id": "H1212121", "client_phone": "91212121",
        "plate": "GN 9999", "vin": "WBA999888777AAA33", "model": "Toyota Alphard", "year": "2023",
        "total_price": 600000,
        "gift_transfer": "赠送", "gift_plate": "12个月",
        "gift_insurance": "综合汽车保险（全保）",
        "warranty_enabled": "含", "warranty_period": "1年",
    }, {"mode": "default", "deposit_amount": 200000, "deposit_date": "2026-09-05",
        "balance_date": "2026-10-05", "choice": "较早者"}),
    # ---- 卖车：只赠 4 个月牌费（不碰 06 条原文，P17 逐字保留）----
    ("car_gifts_plate_only", "car", {
        "agreement_no": "", "sign_date": "2026-09-05", "currency": "HKD",
        "client_name": "吴牌", "client_id": "H1313131", "client_phone": "91313131",
        "plate": "PN 4444", "vin": "WBA444555666AAA44", "model": "Honda Stepwgn", "year": "2022",
        "total_price": 300000,
        "gift_plate": "4个月",
    }, {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-09-05",
        "balance_event": "车辆完成香港运输署过户登记手续当日"}),
    # ---- 卖车：只赠车险（第二句改写、第一句保留 + 编号重排）----
    ("car_gifts_ins", "car", {
        "agreement_no": "", "sign_date": "2026-09-07", "currency": "HKD",
        "client_name": "何险", "client_id": "H1515151", "client_phone": "91515151",
        "plate": "IN 3333", "vin": "WBA333444555CCC66", "model": "Toyota Noah", "year": "2022",
        "total_price": 250000,
        "gift_insurance": "三保",
    }, {"mode": "default", "deposit_amount": 80000, "deposit_date": "2026-09-07",
        "balance_event": "车辆完成香港运输署过户登记手续当日"}),
    # ---- 卖车：质保只给公里数（公里在前、默认半年补后）----
    ("car_warranty_km", "car", {
        "agreement_no": "", "sign_date": "2026-09-06", "currency": "HKD",
        "client_name": "郑保", "client_id": "H1414141", "client_phone": "91414141",
        "plate": "WB 1111", "vin": "WBA111222333BBB55", "model": "BMW 520i", "year": "2021",
        "total_price": 400000,
        "warranty_enabled": "含", "warranty_km": "10000",
    }, {"mode": "one_time", "pay_date": "2026-09-20", "pay_event": "", "choice": "较早者"}),
    # ---- 卖车：人民币默认两段（尾款句币种字面量随币种改写）----
    ("car_cny_default", "car", {
        "agreement_no": "", "sign_date": "2026-09-10", "currency": "CNY",
        "client_name": "钱人民币", "client_id": "H1818181", "client_phone": "91818181",
        "plate": "CNY 111", "vin": "WBA181818181AAA99", "model": "Toyota Camry", "year": "2023",
        "total_price": 480000,
    }, {"mode": "default", "deposit_amount": 80000, "deposit_date": "2026-09-10",
        "balance_date": "2026-10-10", "choice": "较早者"}),
    # ---- 卖车：只承诺无重大事故（陈述保证块保留，无附赠无质保）----
    ("car_accident_only", "car", {
        "agreement_no": "", "sign_date": "2026-09-08", "currency": "HKD",
        "client_name": "孙无事", "client_id": "H1616161", "client_phone": "91616161",
        "plate": "AF 2222", "vin": "WBA222333444AAA77", "model": "Toyota Prius", "year": "2023",
        "total_price": 450000,
        "accident_free": "承诺",
    }, {"mode": "default", "deposit_amount": 50000, "deposit_date": "2026-09-08",
        "balance_event": "车辆完成香港运输署过户登记手续当日"}),
    # ---- 卖车：全开（无事故+附赠过户费+质保自定义时长公里）----
    ("car_all_on", "car", {
        "agreement_no": "", "sign_date": "2026-09-09", "currency": "HKD",
        "client_name": "周全开", "client_id": "H1717171", "client_phone": "91717171",
        "plate": "ALL 111", "vin": "WBA777888999BBB88", "model": "Nissan Elgrand", "year": "2022",
        "total_price": 550000,
        "accident_free": "承诺", "gift_transfer": "赠送",
        "warranty_enabled": "含", "warranty_period": "6个月", "warranty_km": "5万",
    }, {"mode": "default", "deposit_amount": 55000, "deposit_date": "2026-09-09",
        "balance_date": "2026-10-09", "choice": "较早者"}),

    # ---- 卖车：非预设赠品（轮胎/机油，AI 整理后的短语逐条入附赠节）----
    ("car_gift_other", "car", {
        "agreement_no": "", "sign_date": "2026-09-11", "currency": "HKD",
        "client_name": "马胎", "client_id": "H1919191", "client_phone": "91919191",
        "plate": "TY 5555", "vin": "WBA555666777AAA11", "model": "Toyota Vellfire", "year": "2021",
        "total_price": 380000,
        "gift_other": "四条轮胎、更换全车机油",
    }, {"mode": "default", "deposit_amount": 80000, "deposit_date": "2026-09-11",
        "balance_event": "车辆完成香港运输署过户登记手续当日"}),

    # ---- 高新过户：默认三期 + 换车费 ----
    ("gx_default", "transfer_gx", {
        "agreement_no": "", "sign_date": "2026-08-31", "currency": "HKD",
        "client_name": "张三", "client_id": "H1112223", "client_phone": "93001122",
        "plate": "粤Z·H123港", "port": "深圳湾口岸", "quota_type": "高新",
        "target_hk_company": "香港example有限公司",
        "total_fee": 300000, "exchange_fee": 20000,
    }, {"mode": "default", "pay1": 100000, "pay2": 150000, "pay3": 50000}),
    # ---- 高新过户：自定义三期（用户真实场景：表不加日期列，时点进条款文字，尾款关联预设原文）----
    ("gx_custom", "transfer_gx", {
        "agreement_no": "", "sign_date": "2026-10-09", "currency": "CNY",
        "client_name": "鸿达投资有限公司", "client_id": "统一社会信用代码 91110000MA0000000X",
        "client_contact": "李四", "client_phone": "13800001234",
        "plate": "LN1234", "port": "莲塘口岸", "quota_type": "高新",
        "target_hk_company": "XX物流有限公司",
        "total_fee": 300000, "exchange_fee": 0,
    }, {"mode": "custom", "installments": [
        {"seq": 1, "amount": 100000, "label": "第一期", "trigger": "签约当日支付", "trigger_date": "2026-10-09"},
        {"seq": 2, "amount": 100000, "label": "第二期", "trigger": "提交资料后3日内付", "trigger_date": None},
        {"seq": 3, "amount": 100000, "label": "尾款",
         "trigger": "甲方向乙方交付新的车辆行驶证、新批文卡及铁牌资料时支付", "trigger_date": None},
    ]}),
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
    # ---- 新办：自定义两期（一期有日期、一期事件触发；付款时点进条款文字，表格不加列）----
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
NEG_PAYMENTS = [
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
VALID_PAYMENT = {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-09-01",
                 "balance_date": "2026-10-01", "choice": "较早者"}
NEG_FORMS = [
    ("质保时长无法识别", dict(CAR_FORM, warranty_enabled="含", warranty_period="长期")),
    ("质保公里数无法识别", dict(CAR_FORM, warranty_enabled="含", warranty_km="很多")),
]


def run_negative():
    """负向用例：必须被 ValueError 拦截且报错信息可读。"""
    ok = True
    out = os.path.join(OUT, "_neg.docx")
    for name, payment in NEG_PAYMENTS:
        try:
            build_contract("car", dict(CAR_FORM), payment, "2026090199", out, fx_rate=0.88)
            print(f"[FAIL] {name}: 未拦截")
            ok = False
        except ValueError as ex:
            print(f"[PASS] {name}（拦截：{ex}）")
    for name, form in NEG_FORMS:
        try:
            build_contract("car", dict(form), VALID_PAYMENT, "2026090199", out, fx_rate=0.88)
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
    "gx_custom": ["服务总费用", "第一期", "第二期", "尾款"],
    "new_custom": ["服务总费用", "定金", "尾款"],
}

# 用例 → 逐期付款条款行预期文字（custom：时点进条款、行名与费用表一一对应）
EXPECT_CLAUSE = {
    "gx_custom": [
        "第一期：于2026年10月9日支付。",
        "第二期：于提交资料后3日内付。",   # 客户原话以「付」结尾，不得产出「付支付」
        "尾款：于甲方向乙方交付新的车辆行驶证、新批文卡及铁牌资料时支付。",
    ],
    "car_custom": ["定金：于2026年8月31日", "第五期：于2027年1月10日"],
    "new_custom": ["定金：于2026年9月1日", "尾款：于省厅批复后3个工作日内支付。"],
}

# 用例 → 默认三期定金条款应展开的绝对日期（生成日=签约日）
EXPECT_DEPOSIT_DATE = {
    "gx_default": "2026年8月31日",
    "new_default": "2026年8月31日",
}

# 用例 → 卖车 03 条尾款句原文（锁死：金额必落、客户没给尾款日期，合同就不得出现日期）
EXPECT_BALANCE_CLAUSE = {
    "car_default": "剩余购车尾款港币肆拾万元整（HK$400,000），须于2026年9月30日或该车辆完成香港运输署过户登记手续之当日，由乙方一次性支付予甲方。",
    "car_default_event": "剩余购车尾款港币叁拾伍万元整（HK$350,000），须于车辆完成香港运输署过户登记手续当日，由乙方一次性支付予甲方。",
    "car_cny_default": "剩余购车尾款人民币肆拾万元整（¥400,000），须于2026年10月10日或该车辆完成香港运输署过户登记手续之当日，由乙方一次性支付予甲方。",
}

# 用例 → 卖车可选内容断言：must=必须出现的原文/标题；not=禁止出现的内容。
# 合并版模板条件块：四节尾陈述保证（无事故）/ 五节附赠 / 六节质保，标题号随保留/删除自动重排。
EXPECT_EXTRAS = {
    # 附赠全开 + 质保1年（无事故未承诺 → 陈述保证块不出现）
    "car_gifts_full": {"must": [
        "五、附赠服务  |  COMPLIMENTARY SERVICES",
        "六、售后质保  |  AFTER-SALES WARRANTY",
        "附赠：本车辆过户登记手续的全部费用。",
        "附赠：本车辆香港车辆牌照费十二（12）个月。",
        "附赠：本车辆汽车保险（综合汽车保险（全保））。",
        "自车辆交付之日起计一（1）年或车辆行驶三万公里内（以先到者为准）",
        "2、车辆过户手续由甲方负责办理，全部费用由甲方承担。",
        "3、甲方为乙方代办投保本车辆汽车保险（险种见上列附赠），续保费用由乙方自行承担。",
        "七、车辆交付与责任  |  DELIVERY AND RESPONSIBILITY",
        "八、文件、过户及保险  |  DOCUMENTS, TRANSFER AND INSURANCE",
        "十一、签署确认  |  SIGNATURES",
    ], "not": ["甲方陈述并保证"]},
    # 只赠 4 个月牌费（八节两句原文逐字保留）
    "car_gifts_plate_only": {"must": [
        "五、附赠服务  |  COMPLIMENTARY SERVICES",
        "附赠：本车辆香港车辆牌照费四（4）个月。",
        "2、车辆过户手续由甲方负责办理，相关政府费用及代办费用由乙方承担，除非本合约已明确列明由甲方赠送或代办。",
        "3、该车辆之现有保险不随车转移。乙方须自行购买有效的汽车保险。",
        "六、车辆交付与责任  |  DELIVERY AND RESPONSIBILITY",
        "八、违约责任  |  DEFAULT",
        "十、签署确认  |  SIGNATURES",
    ], "not": ["售后质保", "甲方陈述并保证"]},
    # 只赠车险（过户句保留、保险句改写）
    "car_gifts_ins": {"must": [
        "五、附赠服务  |  COMPLIMENTARY SERVICES",
        "附赠：本车辆汽车保险（三保）。",
        "相关政府费用及代办费用由乙方承担",
        "3、甲方为乙方代办投保本车辆汽车保险（险种见上列附赠），续保费用由乙方自行承担。",
        "十、签署确认  |  SIGNATURES",
    ], "not": ["售后质保", "甲方陈述并保证"]},
    # 质保只给公里数（附赠删除 → 质保升为五节；公里在前、默认半年补后）
    "car_warranty_km": {"must": [
        "五、售后质保  |  AFTER-SALES WARRANTY",
        "自车辆交付之日起计六个月或车辆行驶10,000公里内（以先到者为准）",
        "六、车辆交付与责任  |  DELIVERY AND RESPONSIBILITY",
        "十、签署确认  |  SIGNATURES",
    ], "not": ["附赠服务", "附赠：", "甲方陈述并保证"]},
    # 只承诺无重大事故（四节尾陈述保证块保留，编号 五…九）
    "car_accident_only": {"must": [
        "甲方陈述并保证：",
        "4、该车辆无水泡、无重大事故。",
        "五、车辆交付与责任  |  DELIVERY AND RESPONSIBILITY",
        "九、签署确认  |  SIGNATURES",
    ], "not": ["附赠服务", "附赠：", "售后质保"]},
    # 全开（无事故+附赠过户费+质保6个月/5万公里，编号到十一）
    "car_all_on": {"must": [
        "甲方陈述并保证：",
        "4、该车辆无水泡、无重大事故。",
        "五、附赠服务  |  COMPLIMENTARY SERVICES",
        "附赠：本车辆过户登记手续的全部费用。",
        "六、售后质保  |  AFTER-SALES WARRANTY",
        "自车辆交付之日起计六（6）个月或车辆行驶50,000公里内（以先到者为准）",
        "2、车辆过户手续由甲方负责办理，全部费用由甲方承担。",
        "十一、签署确认  |  SIGNATURES",
    ], "not": []},
    # 只送非预设赠品（预设全关 → 无「附赠：本车辆」行；附赠节保留、编号 六…十）
    "car_gift_other": {"must": [
        "五、附赠服务  |  COMPLIMENTARY SERVICES",
        "附赠：四条轮胎。",
        "附赠：更换全车机油。",
        "六、车辆交付与责任  |  DELIVERY AND RESPONSIBILITY",
        "十、签署确认  |  SIGNATURES",
    ], "not": ["附赠：本车辆", "售后质保", "甲方陈述并保证"]},
}
EXPECT_PLAIN_HEADINGS = [
    "五、车辆交付与责任  |  DELIVERY AND RESPONSIBILITY",
    "六、文件、过户及保险  |  DOCUMENTS, TRANSFER AND INSURANCE",
    "七、违约责任  |  DEFAULT",
    "八、法律、争议及生效  |  GOVERNING LAW AND DISPUTE RESOLUTION",
    "九、签署确认  |  SIGNATURES",
]

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


# draft 预览：7 个模板文件全覆盖
ALL_PORTS = ("莲塘口岸", "深圳湾口岸", "港珠澳大桥口岸", "沙头角口岸")


def run_draft():
    """预览回归：录入残缺/垃圾输入不得中断渲染（draft_issues 记录并占位落盘）；
    真生成（非 draft）对同类问题仍必须拦截。"""
    ok = True
    garbage_form = {"currency": "RMB", "total_price": "很多", "total_fee": "很多",
                    "sign_date": "2026-13-45", "exchange_fee": "50万",
                    "warranty_enabled": "含", "warranty_period": "长期",
                    "accident_free": "承诺", "gift_transfer": "赠送"}
    garbage_pay = {"installments": [
        {"label": "订金", "amount": "", "date": "bad-date", "event": ""},
        {"label": "尾款", "amount": "50万", "date": None, "event": "过户当日"},
    ]}

    def build(tkey, form, raw_pay, expect_in_body):
        issues = []
        try:
            payment = derive_payment(tkey, raw_pay, draft=True, issues=issues)
            out = os.path.join(OUT, f"_draft_{tkey}.docx")
            report = build_contract(tkey, form, payment, "（预览稿）", out, draft=True, issues=issues, fx_rate=0.88)
            doc = Document(out)
            body = "\n".join(p.text for p in doc.paragraphs) + "".join(
                c.text for t in doc.tables for r in t.rows for c in r.cells)
            di = report.get("draft_issues") or []
            fails = []
            if not di:
                fails.append("垃圾输入但 draft_issues 为空")
            for needle in expect_in_body:
                if needle not in body:
                    fails.append(f"合同缺少预期内容「{needle}」")
            if fails:
                return f"{'; '.join(fails)}（issues={di}）"
            print(f"[PASS] draft {tkey}（issues {len(di)} 条）")
            return None
        except Exception as ex:
            return f"预览中断：{ex}"

    for tkey in ("car", "transfer_gx", "transfer_ns", "new_port"):
        err = build(tkey, dict(garbage_form), garbage_pay,
                    ["（日期待填）", "（预览稿）", "零元整"])
        if err:
            print(f"[FAIL] draft {tkey}: {err}")
            ok = False
        # 空表单 + 空付款计划：最早期的录入状态也必须能渲染
        err = build(tkey, {"port": "莲塘口岸"} if tkey == "new_port" else {}, {},
                    ["零元整"])
        if err:
            print(f"[FAIL] draft {tkey} 空表单: {err}")
            ok = False

    # 新办 4 口岸模板逐一覆盖（正常数据渲染）
    for port in ALL_PORTS:
        issues = []
        try:
            payment = derive_payment("new_port", {}, draft=True, issues=issues)
            out = os.path.join(OUT, "_draft_new_port.docx")
            build_contract("new_port", {"port": port}, payment, "（预览稿）", out,
                           draft=True, issues=issues, fx_rate=0.88)
            print(f"[PASS] draft new_port {port}")
        except Exception as ex:
            print(f"[FAIL] draft new_port {port}: {ex}")
            ok = False

    # 一次性模式：非法日期占位、缺时点记录
    issues = []
    try:
        p = derive_payment("car", {"installments": [
            {"label": "", "amount": 300000, "date": "2026-02-30", "event": ""}]},
            draft=True, issues=issues)
        if p["mode"] != "one_time":
            print(f"[FAIL] draft one_time 判定：{p['mode']}")
            ok = False
        else:
            out = os.path.join(OUT, "_draft_ot.docx")
            report = build_contract("car", dict(CAR_FORM, currency="HKD", total_price=300000),
                                    p, "（预览稿）", out, draft=True, issues=issues, fx_rate=0.88)
            doc = Document(out)
            body = "\n".join(x.text for x in doc.paragraphs) + "".join(
                c.text for t in doc.tables for r in t.rows for c in r.cells)
            if "（日期待填）" in body and report.get("draft_issues"):
                print("[PASS] draft one_time 非法日期占位")
            else:
                print(f"[FAIL] draft one_time: 占位或 issues 缺失（{report.get('draft_issues')}）")
                ok = False
    except Exception as ex:
        print(f"[FAIL] draft one_time: {ex}")
        ok = False

    # 非 draft 回归：口岸缺失/币种非法仍必须拦截
    out = os.path.join(OUT, "_neg_draft.docx")
    for name, fn in (
        ("真生成缺口岸", lambda: build_contract("new_port", dict(CAR_FORM), VALID_PAYMENT, "2026090199", out, fx_rate=0.88)),
        ("真生成币种RMB", lambda: build_contract("car", dict(CAR_FORM, currency="RMB"), VALID_PAYMENT, "2026090199", out, fx_rate=0.88)),
        ("真生成空付款", lambda: build_contract("car", dict(CAR_FORM), {"mode": "custom", "installments": []}, "2026090199", out, fx_rate=0.88)),
    ):
        try:
            fn()
            print(f"[FAIL] {name}: 未拦截")
            ok = False
        except ValueError as ex:
            print(f"[PASS] {name}（拦截：{ex}）")
    if os.path.exists(out):
        os.remove(out)
    return ok


def run_dual_currency():
    """双币换算落字：费用表/换车费用行 = 主币种大写 + 数字写法在前、换算币种在后（0.88 固定汇率，
    四舍五入到元）。同时证明 check_rules 币种唯一校验对设计内换算后缀放行。"""
    from engine.writer import find_table
    from engine.money import convert_amount
    ok = True

    def cells_of(doc, anchor):
        return [c.text for r in find_table(doc, anchor).rows for c in r.cells]

    def cell_miss(cells, expects):
        return [e for e in expects if not any(e in c for c in cells)]

    # 卖车 HKD：总价 50万 → / ¥44万；订金 10万 → / ¥8.8万；尾款 40万 → / ¥35.2万
    out = os.path.join(OUT, "_dual_car.docx")
    try:
        form = dict(CAR_FORM)
        report = build_contract("car", form, VALID_PAYMENT, "2026090199", out, fx_rate=0.88)
        report["agreement_no"] = "2026090199"
        doc = Document(out)
        miss = cell_miss(cells_of(doc, "车辆总售价"), [
            "港币（大写）伍拾万元整（HK$500,000 / ¥444,400）",
            "（HK$100,000 / ¥88,880）",
            "（HK$400,000 / ¥355,520）",
        ])
        errs = check_rules("car", form, VALID_PAYMENT, report, doc)
        if miss or errs:
            print(f"[FAIL] 双币·卖车HKD：缺 {miss} 错 {errs}")
            ok = False
        else:
            print("[PASS] 双币·卖车HKD（含币种唯一放行）")
    except Exception as ex:
        print(f"[FAIL] 双币·卖车HKD: {ex}")
        ok = False

    # 高新过户 CNY：总价 30万 → / HK$340,909；各期与换车费用行同格式（除法方向）。
    # 分立式样式：大写格与数字格是两个单元格，数字格无全角括号包裹
    out2 = os.path.join(OUT, "_dual_gx.docx")
    try:
        form = {"agreement_no": "", "sign_date": "2026-08-31", "currency": "CNY",
                "client_name": "双币测试", "client_id": "H2223334", "client_phone": "93001122",
                "plate": "粤Z·D001港", "port": "深圳湾口岸", "quota_type": "高新",
                "target_hk_company": "香港双币测试有限公司",
                "total_fee": 300000, "exchange_fee": 20000}
        pay = {"mode": "default", "pay1": 100000, "pay2": 150000, "pay3": 50000}
        report = build_contract("transfer_gx", form, pay, "2026090199", out2, fx_rate=0.88)
        report["agreement_no"] = "2026090199"
        doc = Document(out2)
        miss = cell_miss(cells_of(doc, "服务总费用"), [
            "人民币（大写）叁拾万元整",
            "¥300,000 / HK$344,318",
            "¥100,000 / HK$114,773",
            "¥150,000 / HK$172,159",
            "¥50,000 / HK$57,386",
        ]) + cell_miss(cells_of(doc, "换车费用"),
                       ["人民币（大写）贰万元整（¥20,000 / HK$22,955）"])
        errs = check_rules("transfer_gx", form, pay, report, doc)
        if miss or errs:
            print(f"[FAIL] 双币·过户CNY：缺 {miss} 错 {errs}")
            ok = False
        else:
            print("[PASS] 双币·过户CNY（含换车费用行）")
    except Exception as ex:
        print(f"[FAIL] 双币·过户CNY: {ex}")
        ok = False

    # 换算取值：乘除两方向 + 四舍五入边界
    for amt, code, want in [(500000, "HKD", 444400), (100000, "HKD", 88880),
                            (400000, "CNY", 459091), (150000, "CNY", 172159),
                            (20000, "CNY", 22955), (0, "HKD", 0)]:
        got = convert_amount(amt, code, 0.88)
        if got != want:
            print(f"[FAIL] convert_amount({amt}, {code}) = {got} ≠ {want}")
            ok = False
    if ok:
        print("[PASS] 双币·convert_amount 取值")
    return ok


def run_newport_matrix():
    """四大口岸 × 付款模式全组合（深圳湾正路径此前无用例）：custom 不加日期列，
    付款时点进条款文字且与表行一一对应；超过预设期数的克隆行/克隆段也须过指纹。"""
    ok = True
    out = os.path.join(OUT, "_np_matrix.docx")
    base = {"agreement_no": "", "sign_date": "2026-10-09", "currency": "CNY",
            "client_name": "口岸矩阵", "client_id": "4415**********1234",
            "client_phone": "13800138000", "total_fee": 200000}
    modes = {
        "default": {"mode": "default", "pay1": 50000, "pay2": 100000, "pay3": 50000},
        "one_time": {"mode": "one_time", "pay_date": "2026-10-20", "pay_event": ""},
        "custom2": {"mode": "custom", "installments": [
            {"seq": 1, "amount": 100000, "label": "定金", "trigger": "签约当日支付", "trigger_date": "2026-10-09"},
            {"seq": 2, "amount": 100000, "label": "尾款", "trigger": "省厅批复后3个工作日内支付", "trigger_date": None},
        ]},
        "custom4": {"mode": "custom", "installments": [
            {"seq": 1, "amount": 50000, "label": "定金", "trigger": "签约当日支付", "trigger_date": "2026-10-09"},
            {"seq": 2, "amount": 50000, "label": "",
             "trigger": "甲方香港公司成功入股大陆高新企业，完成省厅系统提交并获得提交编号后，于1个工作日内支付",
             "trigger_date": None},
            {"seq": 3, "amount": 50000, "label": "第三期", "trigger": "递交资料后10日内", "trigger_date": None},
            {"seq": 4, "amount": 50000, "label": "尾款",
             "trigger": "乙方完成两地牌代办申请并取得车辆行驶证、批文卡及禁区纸后，甲方在乙方处领取车辆铁牌等通关资料时现场支付",
             "trigger_date": None},
        ]},
        # 边界：触发词以「付清」结尾不再补「支付」（病句）；描述已含与 trigger_date 同日不再重复日期
        "custom_edge": {"mode": "custom", "installments": [
            {"seq": 1, "amount": 100000, "label": "定金", "trigger": "签约当日支付", "trigger_date": "2026-10-09"},
            {"seq": 2, "amount": 50000, "label": "第二期", "trigger": "递交资料后3日内付清", "trigger_date": None},
            {"seq": 3, "amount": 50000, "label": "尾款", "trigger": "2026年10月20日前支付", "trigger_date": "2026-10-20"},
        ]},
    }
    for port in ALL_PORTS:
        for mname, pay in modes.items():
            try:
                form = dict(base, port=port)
                report = build_contract("new_port", form, pay, "20260831999", out, fx_rate=0.88)
                report["agreement_no"] = "20260831999"
                doc = Document(out)
                errs = check_rules("new_port", form, pay, report, doc)
                errs += check_fingerprint(report["template"], out, "new_port", report, form)
                if pay["mode"] == "custom":
                    body = "\n".join(p.text for p in doc.paragraphs)
                    if "付款日期" in body:
                        errs.append("custom 出现「付款日期」字样")
                    fee = W_find(doc, "服务总费用")
                    for lab in [r.cells[0].text.strip() for r in fee.rows][1:]:
                        if f"{lab}：于" not in body:
                            errs.append(f"条款缺少分期说明：{lab}")
                    if mname == "custom_edge":
                        for bad in ("付清支付", "付款支付", "支付完毕支付"):
                            if bad in body:
                                errs.append(f"病句：以「{bad}」结尾的条款")
                        if "2026年10月20日或2026年10月20日" in body:
                            errs.append("日期重复：描述已含同日仍并列「X日或X日」")
                        for good in ("第二期：于递交资料后3日内付清。", "尾款：于2026年10月20日前支付。"):
                            if good not in body:
                                errs.append(f"边界条款缺失/不符：{good}")
                if errs:
                    ok = False
                    print(f"[FAIL] 口岸矩阵 {port}×{mname}")
                    for e in errs:
                        print(f"   - {e}")
                else:
                    print(f"[PASS] 口岸矩阵 {port}×{mname}")
            except Exception as ex:
                ok = False
                print(f"[ERROR] 口岸矩阵 {port}×{mname}: {ex}")
    if os.path.exists(out):
        os.remove(out)
    return ok


def W_find(doc, anchor):
    from engine.writer import find_table
    return find_table(doc, anchor)


def run_exchange_alias():
    """换车费用行名跟随客户用词：默认「换车费用」，exchange_label=上车费用 时行名改写；
    checker 按别名仍能找到该表；非法名目回退默认（防幻觉）。"""
    from engine.writer import find_table
    ok = True
    out = os.path.join(OUT, "_alias_gx.docx")
    base = {"agreement_no": "", "sign_date": "2026-08-31", "currency": "CNY",
            "client_name": "名目测试", "client_id": "H2444555", "client_phone": "93001122",
            "plate": "粤Z·E002港", "port": "深圳湾口岸", "quota_type": "高新",
            "target_hk_company": "香港名目测试有限公司",
            "total_fee": 300000, "exchange_fee": 20000}
    pay = {"mode": "default", "pay1": 100000, "pay2": 150000, "pay3": 50000}
    try:
        form = dict(base, exchange_label="上车费用")
        report = build_contract("transfer_gx", form, pay, "2026090199", out, fx_rate=0.88)
        report["agreement_no"] = "2026090199"
        doc = Document(out)
        errs = check_rules("transfer_gx", form, pay, report, doc)
        errs += check_fingerprint(report["template"], out, "transfer_gx", report, form)
        cell0 = find_table(doc, "上车费用").rows[0].cells[0].text.strip()
        if errs or cell0 != "上车费用":
            print(f"[FAIL] 名目·上车费用：行名={cell0} 错 {errs}")
            ok = False
        else:
            print("[PASS] 名目·上车费用（行名随客户用词 + 校验别名查找）")
    except Exception as ex:
        print(f"[FAIL] 名目·上车费用: {ex}")
        ok = False
    try:
        form = dict(base, exchange_label="运费")   # 非法名目 → 回退默认
        build_contract("transfer_gx", form, pay, "2026090199", out, fx_rate=0.88)
        doc = Document(out)
        cell0 = find_table(doc, "换车费用").rows[0].cells[0].text.strip()
        if cell0 != "换车费用":
            print(f"[FAIL] 名目·非法回退：行名={cell0}")
            ok = False
        else:
            print("[PASS] 名目·非法输入回退默认")
    except Exception as ex:
        print(f"[FAIL] 名目·非法回退: {ex}")
        ok = False
    if os.path.exists(out):
        os.remove(out)
    return ok


def run_immigration():
    """高才移民：总费用行对调后（C1大写|C2双币数字）+分期散文表三模式（行含约合港币）、
    「分N期支付」格、申请人信息表、编号行、签署日期（年份预填变体）。固定汇率保证断言。"""
    from engine.writer import find_table
    from engine.money import convert_amount, with_commas as wc, to_cn_upper as up
    FX = 0.88   # 与全套件同款固定测试汇率（仅断言用；生产走 fx.get_hkd_cny 实时汇率）

    def hk(amt):
        return f"HK${wc(convert_amount(amt, 'CNY', FX))}"

    def imm_row(label, verb, amt):
        return (f"{label}  {verb}人民币{amt}元整"
                f"(大写：人民币{up(amt)}，约合港币{hk(amt)})。")

    ok = True
    out = os.path.join(OUT, "_imm.docx")
    base = {
        "agreement_no": "", "sign_date": "2026-10-10", "currency": "CNY",
        "client_name": "赵六", "client_id": "440301199001010000",
        "client_contact": "赵太太", "client_phone": "13800001234",
        "client_address": "深圳市福田区测试路1号",
        "total_fee": 400000,
        "lead_applicant": "", "spouse_name": "钱七", "minor_children": "1", "total_applicants": "3",
    }

    def fee_texts(doc):
        total_tbl = find_table(doc, "甲方需支付乙方服务费")
        inst_tbl = find_table(doc, "元整(大写：")
        return (" | ".join(c.text.strip() for c in total_tbl.rows[0].cells),
                [r.cells[1].text.strip() for r in inst_tbl.rows])

    def total_cell(phase):
        return (f"1.甲方需支付乙方服务费： | 人民币（大写）{up(400000)} "
                f"| ¥400,000 / {hk(400000)} | {phase}")

    def build_and_check(tag, form, pay, expect_total_cell=None, expect_rows=None,
                        expect_phase=None, draft=False):
        nonlocal ok
        try:
            report = build_contract("immigration", form, pay, "20261010001", out,
                                    draft=draft, fx_rate=FX)
            report["agreement_no"] = "20261010001"
            doc = Document(out)
            errs = [] if draft else check_rules("immigration", form, pay, report, doc)
            if not draft:
                errs += check_fingerprint(report["template"], out, "immigration", report, form)
            if expect_total_cell is not None:
                total_cell_txt, rows = fee_texts(doc)
                if expect_total_cell not in total_cell_txt:
                    errs.append(f"总费用行不符：{total_cell_txt}")
                if expect_phase is not None and f"分{expect_phase}期支付：" not in total_cell_txt:
                    errs.append(f"期数格不符：{total_cell_txt}")
                if expect_rows is not None and rows != expect_rows:
                    errs.append(f"分期行不符：{rows}")
            if errs:
                ok = False
                print(f"[FAIL] 移民·{tag}")
                for e in errs:
                    print(f"   - {e}")
            else:
                print(f"[PASS] 移民·{tag}")
        except Exception as ex:
            ok = False
            import traceback
            traceback.print_exc()
            print(f"[ERROR] 移民·{tag}: {ex}")

    # 1) default：预设三期整句改写（模板措辞+约合港币）；主申请人缺省同委托方
    form = dict(base)
    build_and_check(
        "default", form, {"mode": "default", "pay1": 100000, "pay2": 200000, "pay3": 100000},
        expect_total_cell=total_cell("分三期"),
        expect_rows=[
            imm_row("第一期", "于签订合约后三个工作日内支付定金", 100000),
            imm_row("第二期", "于甲方提供乙方所需个人资料清单成功办理公司过户后三个工作日内", 200000),
            imm_row("第三期", "于获得香港入境事务处对甲方的申请发出批准函后的三个工作日内", 100000),
        ])
    doc = Document(out)
    app_tbl = find_table(doc, "为主申请人")
    app0 = app_tbl.rows[0].cells[0].text.strip()
    app1 = app_tbl.rows[1].cells[0].text.strip()
    if app0 != "甲方以赵六为主申请人，" or app1 != "配偶钱七随行，包括未成年子女：（1）人，共计（3）人。":
        ok = False
        print(f"[FAIL] 移民·default 申请人表：{app0!r} / {app1!r}")
    meta = next(p for p in doc.paragraphs if "合同编号" in p.text)
    if meta.text.strip() != "合同编号：20261010001":
        ok = False
        print(f"[FAIL] 移民·default 编号行：{meta.text!r}")
    sig_dates = [c.text for t in doc.tables for r in t.rows for c in r.cells
                 if c.text.strip() == "2026年10月10日"]
    if len(sig_dates) < 2:
        ok = False
        print(f"[FAIL] 移民·default 签署日期填充处数={len(sig_dates)}")

    # 2) custom 两期：克隆首行改写整句；「分两期支付」；签约当日与日期同源只留日期
    form2 = dict(base, spouse_name="", minor_children="", total_applicants="")
    build_and_check(
        "custom2", form2, {"mode": "custom", "installments": [
            {"seq": 1, "amount": 150000, "label": "定金", "trigger": "签约当日支付", "trigger_date": "2026-10-10"},
            {"seq": 2, "amount": 250000, "label": "尾款", "trigger": "获得入境处批准函后3个工作日内", "trigger_date": None},
        ]},
        expect_total_cell=total_cell("分两期"),
        expect_rows=[
            imm_row("定金", "于2026年10月10日支付", 150000),
            imm_row("尾款", "于获得入境处批准函后3个工作日内支付", 250000),
        ])

    # 3) one_time：单行一次性支付 + 「一次性支付」格
    build_and_check(
        "one_time", dict(base), {"mode": "one_time", "pay_date": "2026-11-01", "pay_event": ""},
        expect_total_cell=(f"1.甲方需支付乙方服务费： | 人民币（大写）{up(400000)} "
                           f"| ¥400,000 / {hk(400000)} | 一次性支付："),
        expect_rows=[imm_row("第一期", "于2026年11月1日一次性支付", 400000)])

    # 4) draft 空表单：占位渲染不中断
    build_and_check("draft空表单", {
        "agreement_no": "", "sign_date": "", "currency": "CNY",
        "client_name": "", "client_id": "", "client_phone": "",
        "lead_applicant": "", "spouse_name": "", "minor_children": "", "total_applicants": "",
    }, {"mode": "default", "pay1": 0, "pay2": 0, "pay3": 0}, draft=True)

    if os.path.exists(out):
        os.remove(out)
    return ok


def main():
    all_ok = True
    for name, tkey, form, payment in CASES:
        cfg = get_type(tkey)
        out = os.path.join(OUT, f"{name}.docx")
        try:
            no = f"2026083199{len(name):02d}"
            report = build_contract(tkey, form, payment, no, out, fx_rate=0.88)
            report["agreement_no"] = no
            doc = Document(out)
            errs = check_rules(tkey, form, payment, report, doc)
            errs += check_fingerprint(report["template"], out, tkey, report, form)
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
                # custom：费用表不加日期列，逐期条款行与表行名一一对应
                if payment.get("mode") == "custom":
                    if "付款日期" in body:
                        fails.append("custom 模式出现「付款日期」（时点应写进条款文字而非表格列）")
                    for lab in got_labels[1:]:
                        if f"{lab}：于" not in body:
                            fails.append(f"条款缺少与费用行对应的分期说明：{lab}")
                for s in EXPECT_CLAUSE.get(name, []):
                    if s not in body:
                        fails.append(f"逐期付款条款缺失/不符：{s}")
                if name in EXPECT_DEPOSIT_DATE and f"（{EXPECT_DEPOSIT_DATE[name]}）支付" not in body:
                    fails.append(f"定金条款未展开绝对日期 {EXPECT_DEPOSIT_DATE[name]}")
                if name in EXPECT_BALANCE_CLAUSE and EXPECT_BALANCE_CLAUSE[name] not in body:
                    fails.append(f"尾款条款 ≠ 预期「{EXPECT_BALANCE_CLAUSE[name]}」")
                # 签署确认块：双方日期必须与合同顶部签署日期一致（同日、各 1 处）
                sd = form.get("sign_date")
                if sd:
                    y0, m0, d0 = sd.split("-")
                    sig = f"日期：{int(y0)}年{int(m0)}月{int(d0)}日"
                    n_sig = sum(1 for t in doc.tables for r in t.rows
                                for c in r.cells if sig in c.text)
                    if n_sig < 2:
                        fails.append(f"签署块日期「{sig}」仅出现 {n_sig} 处（应至少甲乙双方各 1 处）")
                keep = EXPECT_KEEP.get(name)
                if keep:
                    missing = [k for k in keep if k not in body]
                    if missing:
                        fails.append(f"条款区改写误删无关条款 {missing}")
                # 卖车可选内容：开启的用例按 must/not 逐条断言；未开启的编号必须回到历史形态
                if name in EXPECT_EXTRAS:
                    spec = EXPECT_EXTRAS[name]
                    miss = [s for s in spec["must"] if s not in body]
                    leak = [s for s in spec.get("not", []) if s in body]
                    if miss:
                        fails.append(f"可选内容缺失/不符：{miss}")
                    if leak:
                        fails.append(f"未启用内容出现在合同：{leak}")
                elif tkey == "car":
                    miss = [h for h in EXPECT_PLAIN_HEADINGS if h not in body]
                    leak = [s for s in ("附赠服务", "售后质保", "附赠：", "甲方陈述并保证") if s in body]
                    if miss:
                        fails.append(f"无附赠无售后时条款号未回到历史形态：{miss}")
                    if leak:
                        fails.append(f"未开启可选内容但合同出现：{leak}")
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
    all_ok = (all_ok and run_negative() and run_derive() and run_draft()
              and run_dual_currency() and run_exchange_alias() and run_newport_matrix()
              and run_immigration())
    print("\n总体:", "全部通过" if all_ok else "存在失败")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
