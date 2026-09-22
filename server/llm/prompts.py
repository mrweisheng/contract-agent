# -*- coding: utf-8 -*-
"""LLM 调用的提示词：字段提取 / 付款解析 / 语义复核。"""
from engine.types_config import get_type, PORTS
from engine import car_extras

PORTS_TEXT = "、".join(PORTS)


def _car_extra_rules() -> str:
    return (
        "\n附赠与售后抽取规则（客户没提到的一律保持默认值，禁止臆测）：\n"
        "- 提到赠送/包过户费用（如「过户费我们出」「包过户」）→ gift_transfer=\"赠送\"；未提 → \"不赠送\"\n"
        "- 提到赠送香港牌费/牌费且含期限：一年/12个月 → \"12个月\"，4个月/一季度 → \"4个月\"；"
        "只说送牌费未说期限 → gift_plate 填 null 并在 notes 里提醒「客户送牌费但未说明期限（4个月或12个月），请确认」；未提 → \"不赠送\"\n"
        "- 提到赠送车险/保险 → gift_insurance=险种原文（如「全保」「三保」「全保+三保」；"
        "客户提到垫底费/金额等也一并原样保留）；未提 → null\n"
        "- 提到质保/保修/发动机质保（如「质保1年」「质保10000公里」）→ warranty_enabled=\"含\"，"
        "同时 warranty_period 填时长原文（如「1年」「6个月」）、warranty_km 填纯数字；"
        "只给了其一就只填其一，另一个 null；未提质保 → \"不含\"\n"
    )


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
        "notes 只列需要用户核对的问题（如同一信息前后矛盾、描述含糊），"
        "禁止输出抽取过程说明、正常确认或技术字段名，无问题时输出空数组。"
    )
    user_p = (
        f"业务类型：{cfg['label']}。待抽取字段：\n{_field_lines(cfg)}\n"
        f"另外抽取：\n- currency（币种，值为 HKD 或 CNY，描述提到港币/HK$ 则 HKD，提到人民币/¥ 则 CNY，未提及填 null）\n"
        f"- total（即字段 {total_key}，同一值，纯数字）\n"
        "- payment_text（客户关于付款计划/付款方式的原话或概括，没有填 null）\n"
        f"- port（仅当该类型需要口岸时，可选值：{PORTS_TEXT}，本类型{'需要' if cfg.get('port_required') or any(f['key']=='port' for g in cfg['groups'] for f in g['fields']) else '不需要'}）\n"
        + (_car_extra_rules() if type_key == "car" else "")
        + f"\n业务描述：\n{text}\n\n"
        '输出格式：{"fields": {字段key: 值或null}, "currency": "HKD|CNY|null", "total": 数字或null, "payment_text": "字符串或null", "notes": ["描述中模糊或冲突之处的提示"]}'
    )
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]


def parse_payment_messages(type_key: str, currency: str, total: int, text: str, sign_date: str = "") -> list:
    cfg = get_type(type_key)
    preset = cfg.get("pay_preset") or []
    plines = "\n".join(
        f"{i + 1}. {p['label']}：{p.get('event') or '签约当日（trigger_date＝签署日期）'}"
        for i, p in enumerate(preset)
    )
    sys_p = (
        "你是付款计划解析助手。把客户口头约定解析成结构化分期数据，输出严格 JSON，不输出解释。"
        "规则：amount 必须是纯整数；"
        "label 为该笔款项的称呼，只从客户原话中提取（如「定金」「订金」「尾款」「余款」「首期款」），2~6 个字，"
        "客户没有明确称呼这笔款项时 label 填 null，禁止编造或自行起名；"
        "trigger 为该期付款条件的简洁中文描述；"
        "【关键】trigger_date 仅当能基于「合同签署日期」推算出绝对日期时输出为 YYYY-MM-DD："
        "「签约当日」「签约时」→ 等于签署日期；"
        "「之后每月 10 号」「下月起每月 10 号」→ 签约次月起每月 10 日（依次递增）；"
        "「下个月」「次月」→ 签约次月；"
        "「3 日内」「5 个工作日内」→ 签署日期后 3/5 个工作日；"
        "事件型条件（如「完成过户后」「领铁牌时」「获编号后 1 个工作日内」）无法推算绝对日期，trigger_date 填 null，trigger 保留原描述。"
        f"\n该类型合同模板预设付款计划：\n{plines}\n"
        "【matches_preset 判定】客户约定的期数与预设一致、且各期触发节点与预设含义相同（仅金额可以不同）→ "
        "matches_preset=true，并把每期 trigger 改写为上面预设的原文（预设为「签约当日」的行 trigger 填「签约当日支付」、trigger_date 填签署日期）；"
        "期数不同、任一节点含义不同、或一次性付清 → matches_preset=false，按客户描述如实输出各期。"
        "【notes 纪律】notes 只列需要用户核对处理的问题（如金额与总价对不上、日期矛盾、描述含糊无法定分期）；客户分期期数或付款节点与模板预设不同不是问题（系统自动按自定义分期处理），禁止输出任何「与预设不符/不一致」类说明；各期合计与总金额一致属正常，同样禁止输出；"
        "禁止输出解析过程说明、正常确认（如币种一致、期数说明、日期推算依据）或任何技术字段名，无问题时输出空数组。"
        "【逐期对照改写】无论 matches_preset 真假，每一期 trigger 都要与上面预设逐条对照："
        "客户表述与预设某期触发节点含义相同时（仅口语与书面的措辞差异，"
        "如「完成转股当天付」＝「甲方完成目标公司股权转让法律文件并书面通知乙方当日支付」），"
        "该期 trigger 必须改写为该预设行的原文表述，使合同用语与模板专业措辞一致；"
        "预设中找不到含义对应节点的期次，保持客户原意如实描述。"
    )
    sign_hint = f"\n合同签署日期：{sign_date}（请基于此日期推算所有相对日期）" if sign_date else "\n合同签署日期：未提供（请尽量以 trigger 描述中可识别的日期为准，无法识别时 trigger_date 填 null）"
    total_line = f"总金额 {total}" if total else "总金额未提供（以描述中的各期金额为准）"
    user_p = (
        f"业务类型：{cfg['label']}；{total_line}；表单已选币种 {currency}（若描述中的币种与此不同，在 notes 里说明）。{sign_hint}\n"
        f"客户约定描述：\n{text}\n\n"
        '输出格式：{"matches_preset": true|false, '
        '"installments": [{"seq": 1, "amount": 数字, "label": "款项称呼或null", "trigger": "付款条件描述", "trigger_date": "YYYY-MM-DD|null"}], '
        '"notes": ["需用户核对的问题（无则空数组）"]}'
    )
    return [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}]


def review_messages(contract_text: str, summary: str) -> list:
    sys_p = (
        "你是合同质检员。给你「客户业务约定摘要」和「生成的合同全文」，检查合同是否准确反映约定。"
        "重点检查以下几类问题："
        "1) 【金额一致性】总价、各期金额、币种是否与约定一致；"
        "2) 【付款时点完整性】每一期款项必须有明确的付款时间、节点或条件之一，只有以下算问题："
        "   ① 日期型描述（如「签约当日」「每月 10 号」「下个月」）应已展开为绝对日期"
        "   （X年X月X日），仍为相对描述则视为问题；"
        "   ② 某期既无日期也无事件条件（如仅写「按双方约定」「另行协商」），视为问题；"
        "   事件触发型（如「过户完成当天」「取得批文后 3 日内」「交付铁牌时」）依赖未来事项，"
        "   本身无确定日期，属正常且严谨的表述，不视为问题，只要求合同所载事件与客户约定一致"
        "（客户约定以摘要中「各期节点」及「客户原话」为准，二者均无时才视为无约定时点）；"
        "3) 【冗余重复】多期付款描述中是否存在完全相同的修饰语被每期重复，"
        "   例如「共 N 期」「由乙方支付予甲方」这种只在第一期说一次就够的内容；"
        "4) 【表格与文字信息重复堆叠】费用表已列明各期金额及付款日期时，"
        "   下方付款条款不逐期复述日期或金额（一句话总括即可）——这是有意设计，"
        "   正文未复述金额/日期不构成信息缺失，不得据此报告问题；"
        "5) 【主体信息】甲乙方信息是否正确填入。"
        "只输出事实性问题，不评价合同排版美观度；issues 只列需要人工处理的缺陷，"
        "「信息正确」「与约定一致」「未发现问题」等检查通过项严禁写入 issues，"
        "全部无误时输出 pass=true 且 issues=[]。输出严格 JSON。"
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
    # 卖车附赠/质保写进合同（客户提到才有），摘要必须带上，否则复核会把它们当约定外内容
    if type_key == "car":
        gifts = car_extras.gift_lines(form)
        if gifts:
            parts.append("附赠（客户约定，逐条写入合同）：" + "；".join(g.rstrip("。") for g in gifts))
        wparts = car_extras.warranty_parts(form)
        if wparts:
            parts.append(f"售后（客户约定）：发动机质保 {wparts[0]}或{wparts[1]}（以先到者为准），"
                         f"质保期内免费维修，不构成退车、退款的理由；碰撞涉水/保养不当/私自改装/第三方拆修及正常损耗件不在范围内")
    if form.get("exchange_fee") is not None:
        parts.append(f"换车费用：{form.get('exchange_fee')}（独立于服务总费用，另行列示，不计入总金额，分期合计也只针对服务总费用）")
    mode = payment.get("mode")
    if mode == "default":
        if type_key == "car":
            bd = payment.get("balance_date")
            tail = f" 于 {bd} 或车辆完成过户登记当日" if bd else " 于车辆完成香港运输署过户登记手续当日"
            parts.append(f"付款：订金 {payment.get('deposit_amount')}（{payment.get('deposit_date')}），尾款 {int(total) - int(payment.get('deposit_amount') or 0)}{tail}")
        else:
            line = f"付款：三期 {payment.get('pay1')}/{payment.get('pay2')}/{payment.get('pay3')}"
            nodes = [f"{p['label']}：{p.get('event') or '签约当日（即签署日期）'}" for p in cfg.get("pay_preset") or []]
            if nodes:
                line += f"（各期节点：{'；'.join(nodes)}）"
            parts.append(line)
    elif mode == "one_time":
        parts.append(f"付款：一次性付清（{payment.get('pay_date')} {payment.get('pay_event') or ''}）")
    else:
        rows = []
        for x in payment.get("installments", []):
            lab = (x.get("label") or "").strip()
            item = f"第{x.get('seq')}期" + (f"（{lab}）" if lab else "") + f" {x.get('amount')}"
            if x.get("trigger_date"):
                item += f"，推算日期 {x.get('trigger_date')}"
            if x.get("trigger"):
                item += f"（{x.get('trigger')}）"
            rows.append(item)
        parts.append(f"付款：自定义分期 {'；'.join(rows)}")
    if payment.get("source_text"):
        parts.append(f"客户原话：{payment.get('source_text')}")
    return "\n".join(str(x) for x in parts)
