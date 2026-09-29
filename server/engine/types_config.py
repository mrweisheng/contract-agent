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


def _client_anchors(party_table: str, name_row: str, value_col: int) -> dict:
    """双方表客户字段锚点：行匹配对整行文本做包含判断
    （甲乙两侧同行布局，同一行左右各一组标签/值，靠列号取客户侧值格）。"""
    return {
        "client_name": {"table": party_table, "row": name_row, "col": value_col},
        "client_id": {"table": party_table, "row": "证件", "col": value_col},
        "client_contact": {"table": party_table, "row": "联络人", "col": value_col},
        "client_phone": {"table": party_table, "row": "联络电话", "col": value_col},
        "client_address": {"table": party_table, "row": "地址", "col": value_col},
    }

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
        "payment_section": ("三", "四"),   # （条款号，下一条款号）
        "car_default": True,               # 三节尾款句金额/日期空由订金/尾款填入
        # 付款计划预设（模板固定结构，前端分期表预置；dated=该期按日期付款）
        "pay_preset": [
            {"label": "订金", "dated": True},
            {"label": "尾款", "event": "车辆完成香港运输署过户登记手续当日", "dated": True},
        ],
        "fee_rows_default": ["车辆总售价", "订金", "订金支付日期", "购车尾款"],
        "exchange_fee": False,
        # 前端「聚焦字段 → 预览联动定位」锚点（结构定位：表格锚文本+行标签子串+值列，或段落子串）
        "field_anchors": {
            **_client_anchors("@party", "买方", 3),
            "plate": {"table": "@kv", "row": "车牌号码", "col": 1},
            "vin": {"table": "@kv", "row": "底盘", "col": 1},
            "model": {"table": "@kv", "row": "品牌及型号", "col": 1},
            "year": {"table": "@kv", "row": "登记年份", "col": 1},
            "total_price": {"table": "@fee", "row": "车辆总售价", "col": 1},
            "currency": {"table": "@fee", "row": "车辆总售价", "col": 1},
            "sign_date": {"table": "授权代表签署"},
            # 分期卡片无固定行：前端按付款模式算行号（订金→1，订金日期→2，尾款→末行）
            "installment": {"table": "@fee"},
            # 条件节：仅当该节落盘时才存在，找不到即静默跳过
            "accident_free": {"para": "甲方陈述并保证"},
            "gift_plate": {"para": "附赠服务"},
            "gift_transfer": {"para": "车辆过户手续"},
            "gift_insurance": {"para": ["代办投保", "现有保险不随车转移"]},
            "warranty_enabled": {"para": "售后质保"},
            "warranty_period": {"para": "保修范围"},
            "warranty_km": {"para": "保修范围"},
        },
        # 表单结构
        "groups": [
            {"title": "买方信息（乙方）", "fields": [
                {"key": "client_name", "label": "买方名称（个人/公司）", "type": "text", "required": True},
                {"key": "client_id", "label": "证件／公司编号", "type": "text", "required": True},
                {"key": "client_contact", "label": "联络人（公司必填）", "type": "text", "required": False},
                {"key": "client_phone", "label": "联络电话", "type": "text", "required": True},
                {"key": "client_address", "label": "联络地址", "type": "text", "required": False},
            ]},
            {"title": "附赠与售后（选填，客户提到才填）", "reveal": "on_fill", "fields": [
                {"key": "gift_transfer", "label": "附赠过户费用", "type": "select",
                 "options": ["不赠送", "赠送"], "required": False, "default": "不赠送"},
                {"key": "gift_plate", "label": "附赠香港牌费", "type": "select",
                 "options": ["不赠送", "4个月", "12个月"], "required": False, "default": "不赠送"},
                {"key": "gift_insurance", "label": "附赠车险·险种（填即赠送）", "type": "text", "required": False},
                {"key": "accident_free", "label": "承诺无重大事故（写明无水泡/无事故）", "type": "select",
                 "options": ["不承诺", "承诺"], "required": False, "default": "不承诺"},
                {"key": "warranty_enabled", "label": "发动机质保", "type": "select",
                 "options": ["不含", "含"], "required": False, "default": "不含"},
                {"key": "warranty_period", "label": "质保时长（如1年/6个月，空=半年）", "type": "text",
                 "required": False, "hint": "未提=默认半年（6个月）"},
                {"key": "warranty_km", "label": "质保公里数（如30000，空=3万）", "type": "text",
                 "required": False, "hint": "未提=默认3万公里"},
            ]},
            {"title": "车辆数据", "fields": [
                {"key": "plate", "label": "车牌号码（新车未上牌可空）", "type": "text", "required": False},
                {"key": "vin", "label": "底盘／识别号码（VIN/Chassis）", "type": "text", "required": True},
                {"key": "model", "label": "品牌及型号", "type": "text", "required": True},
                {"key": "year", "label": "登记年份", "type": "text", "required": True},
            ]},
        ],
        "fee_fields": [
            {"key": "total_price", "label": "车辆总售价", "type": "number", "required": True},
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
        # 付款计划预设（模板固定结构，前端分期表预置）
        "pay_preset": [
            {"label": "定金", "dated": True},
            {"label": "第二期款", "event": "甲方完成目标公司股权转让法律文件并书面通知乙方当日支付"},
            {"label": "尾款", "event": "甲方向乙方交付新的车辆行驶证、新批文卡及铁牌资料时支付"},
        ],
        "payment_section": ("四", "五"),
        "fee_rows_default": ["服务总费用", "第一期｜定金", "第二期款", "尾款"],
        "exchange_fee": {"anchor": "换车费用"},
        "field_anchors": {
            **_client_anchors("@party", "委托方", 3),
            "plate": {"table": "@kv", "row": "车牌号码", "col": 1},
            "port": {"table": "@kv", "row": "通行口岸", "col": 1},
            # quota_type 只读自动项，不做联动
            "target_hk_company": {"table": "@kv", "row": "目标香港公司名称", "col": 1},
            "total_fee": {"table": "@fee", "row": "服务总费用", "col": 2},
            "currency": {"table": "@fee", "row": "服务总费用", "col": 2},
            "exchange_fee": {"table": "@exchange", "row": "换车费用", "col": 1},
            "sign_date": {"table": "授权代表签署"},
            "installment": {"table": "@fee"},
        },
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
        # 付款计划预设（模板固定结构，前端分期表预置）
        "pay_preset": [
            {"label": "定金", "dated": True},
            {"label": "第二期款", "event": "甲方完成目标公司股权转让法律文件并书面通知乙方当日支付"},
            {"label": "尾款", "event": "甲方向乙方交付新的车辆行驶证、新批文卡及铁牌资料时支付"},
        ],
        "payment_section": ("四", "五"),
        "fee_rows_default": ["服务总费用", "第一期｜定金", "第二期款", "尾款"],
        "exchange_fee": {"anchor": "换车费用"},
        "field_anchors": {
            **_client_anchors("@party", "委托方", 3),
            "plate": {"table": "@kv", "row": "车牌号码", "col": 1},
            "port": {"table": "@kv", "row": "通行口岸", "col": 1},
            # quota_type 只读自动项，不做联动
            "target_hk_company": {"table": "@kv", "row": "目标香港公司名称", "col": 1},
            "target_ml_company": {"table": "@kv", "row": "目标内地公司名称", "col": 1},
            "total_fee": {"table": "@fee", "row": "服务总费用", "col": 2},
            "currency": {"table": "@fee", "row": "服务总费用", "col": 2},
            "exchange_fee": {"table": "@exchange", "row": "换车费用", "col": 1},
            "sign_date": {"table": "授权代表签署"},
            "installment": {"table": "@fee"},
        },
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
        # 付款计划预设（模板固定结构，前端分期表预置）
        "pay_preset": [
            {"label": "定金", "dated": True},
            {"label": "第二期款", "event": "甲方香港公司成功入股大陆高新企业，完成省厅系统提交并获得提交编号后，于1个工作日内支付"},
            {"label": "尾款", "event": "乙方完成两地牌代办申请并取得车辆行驶证、批文卡及禁区纸后，甲方在乙方处领取车辆铁牌等通关资料时现场支付"},
        ],
        "payment_section": ("三", "四"),
        "fee_rows_default": ["服务总费用", "第一期｜定金", "第二期款", "第三期｜尾款"],
        "exchange_fee": False,
        "field_anchors": {
            **_client_anchors("@party", "委托方", 1),
            "total_fee": {"table": "@fee", "row": "服务总费用", "col": 1},
            "currency": {"table": "@fee", "row": "服务总费用", "col": 1},
            "sign_date": {"table": "授权代表签署"},
            "installment": {"table": "@fee"},
        },
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
    },
}

CURRENCY_OPTIONS = [
    {"value": "HKD", "label": "港币 HK$"},
    {"value": "CNY", "label": "人民币 ¥"},
]

# field_anchors 里的表名宏展开：@party/@fee/@kv/@exchange 引用各类型已配置的模板锚点，
# 避免「甲方（卖方）」这类模板定位文字写两遍、改模板时漏改一处。
_ANCHOR_TABLE_MACROS = {
    "@party": lambda c: c["party_table_anchor"],
    "@fee": lambda c: c["fee_table_anchor"],
    "@kv": lambda c: c["kv_tables"][0]["anchor"],
    "@exchange": lambda c: c["exchange_fee"]["anchor"],
}
for _cfg in TYPES.values():
    _fa = _cfg.get("field_anchors")
    if not _fa:
        continue
    for _a in _fa.values():
        _t = _a.get("table")
        if _t in _ANCHOR_TABLE_MACROS:
            _a["table"] = _ANCHOR_TABLE_MACROS[_t](_cfg)


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
