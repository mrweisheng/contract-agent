# -*- coding: utf-8 -*-
"""
业务类型总配置：表单结构（前端渲染用）+ 模板锚点（落盘引擎用）。
单一事实来源，改字段/锚点只改这里。
"""
import os

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

PORTS = ["莲塘口岸", "深圳湾口岸", "港珠澳大桥口岸", "沙头角口岸"]

# 付款计划三模式
PAYMENT_MODES = ["default", "one_time", "custom"]

TYPES = {
    # ============ 卖车 ============
    "car": {
        "label": "卖车（香港车辆买卖）",
        "short": "卖车",
        "template": "1-卖车-香港车辆买卖合约.docx",
        "currency_default": "HKD",
        "client_side": "乙方（买方）",
        "payer": "乙方",           # 付款方（条款行文用）
        "payee": "甲方",
        # 模板锚点
        "party_table_anchor": "甲方（卖方）",
        "party_label_col": 2, "party_value_col": 3,
        "kv_tables": [  # 标签-值 两列表格
            {"anchor": "车牌号码", "map": {
                "车牌号码": "plate",
                "底盘": "vin",
                "品牌及型号": "model",
                "登记年份": "year",
            }},
        ],
        "fee_table_anchor": "车辆总售价",
        "fee_cell_style": "single",        # 单格：「港币（大写）X元整（HK$X）」
        "fee_total_label": "车辆总售价",
        "payment_section": ("03", "04"),   # （条款号，下一条款号）
        "car_default": True,               # 03 条有日期空与较早/较晚选择
        "fee_rows_default": ["车辆总售价", "订金", "订金支付日期", "购车尾款"],
        "exchange_fee": False,
        # 表单结构
        "groups": [
            {"title": "买方信息（乙方）", "fields": [
                {"key": "client_name", "label": "买方名称（个人/公司）", "type": "text", "required": True},
                {"key": "client_id", "label": "证件／公司编号", "type": "text", "required": True},
                {"key": "client_contact", "label": "联络人（公司必填）", "type": "text", "required": False},
                {"key": "client_phone", "label": "联络电话", "type": "text", "required": True},
                {"key": "client_address", "label": "联络地址", "type": "text", "required": False},
            ]},
            {"title": "车辆数据", "fields": [
                {"key": "plate", "label": "车牌号码", "type": "text", "required": True},
                {"key": "vin", "label": "底盘／识别号码（VIN/Chassis）", "type": "text", "required": True},
                {"key": "model", "label": "品牌及型号", "type": "text", "required": True},
                {"key": "year", "label": "登记年份", "type": "text", "required": True},
            ]},
        ],
        "fee_fields": [
            {"key": "total_price", "label": "车辆总售价", "type": "number", "required": True},
        ],
        # 默认两段式付款的额外输入
        "default_pay_fields": [
            {"key": "deposit_amount", "label": "订金金额", "type": "number", "required": True},
            {"key": "deposit_date", "label": "订金支付日期", "type": "date", "required": True},
            {"key": "balance_date", "label": "尾款支付日期", "type": "date", "required": True},
            {"key": "choice", "label": "以较早者／较晚者为准备", "type": "select", "options": ["较早者", "较晚者"], "required": True},
        ],
    },

    # ============ 现牌过户 · 高新 ============
    "transfer_gx": {
        "label": "现牌过户 · 高新",
        "short": "高新过户",
        "template": "2-过户-高新两地牌现牌过户.docx",
        "currency_default": "HKD",
        "client_side": "乙方（委托方）",
        "payer": "乙方",
        "payee": "甲方",
        "party_table_anchor": "甲方（服务方）",
        "party_label_col": 2, "party_value_col": 3,
        "kv_tables": [
            {"anchor": "车牌号码", "map": {
                "车牌号码": "plate",
                "通行口岸": "port",
                "两地牌类型": "quota_type",
                "目标香港公司名称": "target_hk_company",
            }},
        ],
        "quota_auto": "高新",
        "fee_table_anchor": "服务总费用",
        "fee_cell_style": "split",          # 两格：「港币（大写）X元整」＋「HK$X」
        "fee_total_label": "服务总费用",
        "payment_section": ("04", "05"),
        "fee_rows_default": ["服务总费用", "第一期｜定金", "第二期款", "尾款"],
        "exchange_fee": {"anchor": "换车费用"},
        "groups": [
            {"title": "委托方信息（乙方）", "fields": [
                {"key": "client_name", "label": "委托方名称（个人/公司）", "type": "text", "required": True},
                {"key": "client_id", "label": "证件类型及号码", "type": "text", "required": True},
                {"key": "client_contact", "label": "联络人（公司必填）", "type": "text", "required": False},
                {"key": "client_phone", "label": "联络电话", "type": "text", "required": True},
                {"key": "client_address", "label": "联络地址", "type": "text", "required": False},
            ]},
            {"title": "指标与车辆数据", "fields": [
                {"key": "plate", "label": "车牌号码", "type": "text", "required": True},
                {"key": "port", "label": "通行口岸", "type": "select", "options": PORTS, "required": True},
                {"key": "quota_type", "label": "两地牌类型（自动带入）", "type": "text", "required": False, "auto": "高新"},
                {"key": "target_hk_company", "label": "目标香港公司名称", "type": "text", "required": True},
            ]},
        ],
        "fee_fields": [
            {"key": "total_fee", "label": "服务总费用", "type": "number", "required": True},
            {"key": "exchange_fee", "label": "换车费用（可为0，独立于服务总费用）", "type": "number", "required": False, "default": 0},
        ],
        "default_pay_fields": [
            {"key": "pay1", "label": "第一期｜定金", "type": "number", "required": True},
            {"key": "pay2", "label": "第二期款", "type": "number", "required": True},
            {"key": "pay3", "label": "尾款", "type": "number", "required": True},
        ],
    },

    # ============ 现牌过户 · 纳税 ============
    "transfer_ns": {
        "label": "现牌过户 · 纳税（过户两家公司）",
        "short": "纳税过户",
        "template": "3-过户-纳税两地牌现牌过户（需过户两家公司）.docx",
        "currency_default": "HKD",
        "client_side": "乙方（委托方）",
        "payer": "乙方",
        "payee": "甲方",
        "party_table_anchor": "甲方（服务方）",
        "party_label_col": 2, "party_value_col": 3,
        "kv_tables": [
            {"anchor": "车牌号码", "map": {
                "车牌号码": "plate",
                "通行口岸": "port",
                "两地牌类型": "quota_type",
                "目标香港公司名称": "target_hk_company",
                "目标内地公司名称": "target_ml_company",
            }},
        ],
        "quota_auto": "纳税",
        "fee_table_anchor": "服务总费用",
        "fee_cell_style": "split",
        "fee_total_label": "服务总费用",
        "payment_section": ("04", "05"),
        "fee_rows_default": ["服务总费用", "第一期｜定金", "第二期款", "尾款"],
        "exchange_fee": {"anchor": "换车费用"},
        "groups": [
            {"title": "委托方信息（乙方）", "fields": [
                {"key": "client_name", "label": "委托方名称（个人/公司）", "type": "text", "required": True},
                {"key": "client_id", "label": "证件类型及号码", "type": "text", "required": True},
                {"key": "client_contact", "label": "联络人（公司必填）", "type": "text", "required": False},
                {"key": "client_phone", "label": "联络电话", "type": "text", "required": True},
                {"key": "client_address", "label": "联络地址", "type": "text", "required": False},
            ]},
            {"title": "指标与车辆数据", "fields": [
                {"key": "plate", "label": "车牌号码", "type": "text", "required": True},
                {"key": "port", "label": "通行口岸", "type": "select", "options": PORTS, "required": True},
                {"key": "quota_type", "label": "两地牌类型（自动带入）", "type": "text", "required": False, "auto": "纳税"},
                {"key": "target_hk_company", "label": "目标香港公司名称", "type": "text", "required": True},
                {"key": "target_ml_company", "label": "目标内地公司名称", "type": "text", "required": True},
            ]},
        ],
        "fee_fields": [
            {"key": "total_fee", "label": "服务总费用", "type": "number", "required": True},
            {"key": "exchange_fee", "label": "换车费用（可为0，独立于服务总费用）", "type": "number", "required": False, "default": 0},
        ],
        "default_pay_fields": [
            {"key": "pay1", "label": "第一期｜定金", "type": "number", "required": True},
            {"key": "pay2", "label": "第二期款", "type": "number", "required": True},
            {"key": "pay3", "label": "尾款", "type": "number", "required": True},
        ],
    },

    # ============ 四大口岸新办 ============
    "new_port": {
        "label": "粤Z新办（四大口岸，高新指标）",
        "short": "新办",
        "template_map": {  # 按口岸选模板
            "莲塘口岸": "4-新办-莲塘口岸粤Z新办协议.docx",
            "深圳湾口岸": "5-新办-深圳湾口岸粤Z新办协议.docx",
            "港珠澳大桥口岸": "6-新办-港珠澳大桥口岸粤Z新办协议.docx",
            "沙头角口岸": "7-新办-沙头角口岸粤Z新办协议.docx",
        },
        "currency_default": "CNY",
        "client_side": "甲方（委托方·个人）",
        "payer": "甲方",
        "payee": "乙方",
        "party_table_anchor": "乙方（服务方）",
        "party_label_col": 0, "party_value_col": 1,
        "kv_tables": [],   # 新办无车辆数据表；申请信息表为只读展示
        "apply_table_anchor": "申请类型",
        "fee_table_anchor": "服务总费用",
        "fee_cell_style": "single_rmb",     # 「人民币（大写）X元整（¥X / $X）」→ 单币种改写
        "fee_total_label": "服务总费用",
        "payment_section": ("03", "04"),
        "fee_rows_default": ["服务总费用", "第一期｜定金", "第二期款", "第三期｜尾款"],
        "exchange_fee": False,
        "port_required": True,
        "groups": [
            {"title": "委托方信息（甲方 · 个人）", "fields": [
                {"key": "client_name", "label": "委托人姓名（个人签约）", "type": "text", "required": True},
                {"key": "client_id", "label": "证件号码（身份证/回乡证）", "type": "text", "required": True},
                {"key": "client_phone", "label": "联络电话", "type": "text", "required": True},
                {"key": "client_address", "label": "联络地址", "type": "text", "required": False},
            ]},
        ],
        "fee_fields": [
            {"key": "total_fee", "label": "服务总费用", "type": "number", "required": True},
        ],
        "default_pay_fields": [
            {"key": "pay1", "label": "第一期｜定金（签约即日）", "type": "number", "required": True},
            {"key": "pay2", "label": "第二期款（省厅提交获编号后1个工作日内）", "type": "number", "required": True},
            {"key": "pay3", "label": "第三期｜尾款（领取铁牌等通关资料时）", "type": "number", "required": True},
        ],
    },
}

CURRENCY_OPTIONS = [
    {"value": "HKD", "label": "港币 HK$"},
    {"value": "CNY", "label": "人民币 ¥"},
]


def get_type(type_key: str) -> dict:
    cfg = TYPES.get(type_key)
    if not cfg:
        raise ValueError(f"未知业务类型: {type_key}")
    return cfg


def template_path(cfg: dict, form: dict) -> str:
    if "template_map" in cfg:
        port = form.get("port")
        if port not in cfg["template_map"]:
            raise ValueError(f"请选择口岸（{port}）")
        name = cfg["template_map"][port]
    else:
        name = cfg["template"]
    return os.path.join(TEMPLATES_DIR, name)
