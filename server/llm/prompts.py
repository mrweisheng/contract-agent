# -*- coding: utf-8 -*-
"""LLM 调用的提示词：字段提取 / 付款解析 / 语义复核。"""
from engine.types_config import get_type, PORTS

PORTS_TEXT = "、".join(PORTS)


def _field_lines(cfg: dict) -> str:
    lines = []
    for g in cfg["groups"]:
        for f in g["fields"]:
            req = "必填" if f.get("required") else "选填"
            extra = ""
            if f.get("options"):
                extra = f"，可选值：{'/'.join(f['options'])}"
            if f.get("auto"):
                continue  # 自动带入字段不抽取
            lines.append(f"- {f['key']}（{f['label']}，{req}{extra}）")
    for f in cfg["fee_fields"]:
        lines.append(f"- {f['key']}（{f['label']}，金额，{'必填' if f.get('required') else '选填'}，纯数字不带单位）")
    return "\n".join(lines)


def extract_messages(type_key: str, text: str) -> list:
    cfg = get_type(type_key)
    total_key = "total_price" if type_key == "car" else "total_fee"
    sys_p = (
        "你是合同信息抽取助手。从业务描述中抽取字段，输出严格的 JSON。"
        "规则：只输出 JSON 对象，不输出任何解释；没提到的字段填 null；"
        "金额只能是纯整数数字（不带货币符号、不带千分位）；日期统一为 YYYY-MM-DD；"
        "口岸必须从给定可选值中选；不要编造描述中没有的信息。"
    )
    user_p = (
        f"业务类型：{cfg['label']}。待抽取字段：\n{_field_lines(cfg)}\n"
        f"另外抽取：\n- currency（币种，值为 HKD 或 CNY，描述提到港币/HK$ 则 HKD，提到人民币/¥ 则 CNY，未提及填 null）\n"
        f"- total（即字段 {total_key}，同一值，纯数字）\n"
        "- payment_text（客户关于付款计划/付款方式的原话或概括，没有填 null）\n"
        f"- port（仅当该类型需要口岸时，可选值：{PORTS_TEXT}，本类型{'需要' if cfg.get('port_required') or any(f['key']=='port' for g in cfg['groups'] for f in g['fields']) else '不需要'}）\n\n"
        f"业务描述：\n{text}\n\n"
        '输出格式：{"fields": {字段key: 值或null}, "currency": "HKD|CNY|null", "total": 数字或null, "payment_text": "字符串或null", "notes": ["描述中模糊或冲突之处的提示"]}'
    )
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]


def parse_payment_messages(type_key: str, currency: str, total: int, text: str, sign_date: str = "") -> list:
    cfg = get_type(type_key)
    default_desc = ""
    if type_key == "car":
        default_desc = "默认两段：订金＋尾款（签约时定日期，尾款于指定日期或过户当日付）"
    else:
        default_desc = "默认三期：定金（签约即日）→ 第二期款 → 尾款（事件触发）"
    sys_p = (
        "你是付款计划解析助手。把客户口头约定解析成结构化分期数据，输出严格 JSON，不输出解释。"
        "规则：amount 必须是纯整数；trigger 为该期付款条件的简洁中文描述（如「签约当日支付」「每月10号支付」「完成股权转让后3日内支付」）；"
        "trigger_type 取值：date（具体日期型）/ event（事件触发型）/ mixed（混合）；"
        "如果描述就是把货款/费用一次付清，mode 填 one_time；如果是常规的按合同默认分期，mode 填 default；其余任何分期方式 mode 填 custom。"
        "【关键】trigger_date 必须输出为 YYYY-MM-DD 格式的绝对日期，"
        "基于「合同签署日期」推算所有相对描述："
        "「签约当日」「签约时」→ 等于签署日期；"
        "「之后每月 10 号」「下月起每月 10 号」→ 签约次月起每月 10 日（依次递增）；"
        "「下个月」「次月」→ 签约次月；"
        "「3 日内」「5 个工作日内」→ 签署日期后 3/5 个工作日；"
        "无法推算的事件型 trigger（如「完成过户后」），trigger_date 填 null，trigger 保留原描述。"
    )
    sign_hint = f"\n合同签署日期：{sign_date}（请基于此日期推算所有相对日期）" if sign_date else "\n合同签署日期：未提供（请尽量以 trigger 描述中可识别的日期为准，无法识别时 trigger_date 填 null）"
    user_p = (
        f"业务类型：{cfg['label']}；总金额 {total}；表单已选币种 {currency}（若描述中的币种与此不同，在 notes 里说明）。{sign_hint}\n"
        f"该类型合同默认付款方式：{default_desc}。\n"
        f"客户约定描述：\n{text}\n\n"
        '输出格式：{"mode": "default|one_time|custom", "currency": "HKD|CNY|null", '
        '"one_time": {"date": "YYYY-MM-DD|null", "event": "事件描述或null", "choice": "较早者|较晚者"}, '
        '"installments": [{"seq": 1, "amount": 数字, "trigger": "付款条件描述", "trigger_date": "YYYY-MM-DD|null", "trigger_type": "date|event|mixed"}], '
        '"notes": ["提示"]}'
    )
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]


def review_messages(contract_text: str, summary: str) -> list:
    sys_p = (
        "你是合同质检员。给你「客户业务约定摘要」和「生成的合同全文」，检查合同是否准确反映约定。"
        "重点检查以下几类问题："
        "1) 【金额一致性】总价、各期金额、币种是否与约定一致；"
        "2) 【日期明确性】付款条款是否使用具体日期（YYYY-MM-DD 或 X年X月X日），"
        "   若仍使用相对描述（如「签约当日」「每月 10 号」「下个月」）且没有展开为绝对日期，"
        "   视为问题（应明确具体哪一天）；"
        "3) 【冗余重复】多期付款描述中是否存在完全相同的修饰语被每期重复，"
        "   例如「共 N 期」「由乙方支付予甲方」这种只在第一期说一次就够的内容；"
        "4) 【表格与文字信息重复堆叠】若费用表已列出「第一期 HK$100,000」，"
        "   下方条款文字段是否再次完整重复该金额（应只在文字段描述付款时点，金额已在表格中）；"
        "5) 【主体信息】甲乙方信息是否正确填入。"
        "只输出事实性问题,不评价合同排版美观度。输出严格 JSON。"
    )
    user_p = (
        f"【客户业务约定摘要】\n{summary}\n\n"
        f"【生成的合同全文】\n{contract_text}\n\n"
        '输出格式：{"pass": true|false, "issues": ["问题描述1", ...]}（无问题时 issues 为空数组）'
    )
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]


def build_summary(type_key: str, form: dict, payment: dict) -> str:
    cfg = get_type(type_key)
    parts = [f"业务类型：{cfg['label']}"]
    for g in cfg["groups"]:
        for f in g["fields"]:
            v = form.get(f["key"])
            if v:
                parts.append(f"{f['label']}：{v}")
    total = form.get("total_price") or form.get("total_fee")
    parts.append(f"总金额：{total} {form.get('currency')}")
    if form.get("exchange_fee") is not None:
        parts.append(f"换车费用：{form.get('exchange_fee')}（独立于服务总费用，另行列示，不计入总金额，分期合计也只针对服务总费用）")
    mode = payment.get("mode")
    if mode == "default":
        if type_key == "car":
            parts.append(f"付款：订金 {payment.get('deposit_amount')}（{payment.get('deposit_date')}），尾款 {int(total) - int(payment.get('deposit_amount') or 0)} 于 {payment.get('balance_date')}（以{payment.get('choice')}为准）")
        else:
            parts.append(f"付款：三期 {payment.get('pay1')}/{payment.get('pay2')}/{payment.get('pay3')}")
    elif mode == "one_time":
        parts.append(f"付款：一次性付清（{payment.get('pay_date')} {payment.get('pay_event') or ''}）")
    else:
        rows = "；".join(
            f"第{x.get('seq')}期 {x.get('amount')}（{x.get('trigger')}）"
            for x in payment.get("installments", [])
        )
        parts.append(f"付款：自定义分期 {rows}")
        if payment.get("source_text"):
            parts.append(f"客户原话：{payment.get('source_text')}")
    return "\n".join(str(x) for x in parts)
