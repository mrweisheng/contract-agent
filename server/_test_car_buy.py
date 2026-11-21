# -*- coding: utf-8 -*-
"""收车业务离线测试：模板适配件 + 散文金额落位 + 登记号码二选一 + 印章/签名块适配。
覆盖：编号行/双方表/车辆表落值、金额三句双币（对外付款免 1.01 加成）、日期/期限、
二选一两种取值、金额合计拦截、印章 A 路径在新签署块版式上的落位。"""
import sys, io, os, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "carbuy_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(os.path.join(TMP, "seals"))

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP
store.OUT_DIR = TMP
store.init()

from PIL import Image as PILImage
for name, size, color in (("seal.png", (60, 60), (40, 40, 160)), ("sign.png", (80, 30), (20, 20, 20))):
    PILImage.new("RGB", size, color).save(os.path.join(TMP, "seals", name), "PNG")
from engine import seal as seal_mod
seal_mod.seals_dir = lambda: os.path.join(TMP, "seals")

from engine.builder import build_contract, derive_payment
from engine import checker as C
from engine import seal as S
from docx import Document

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)

FORM = {"agreement_no": "20261121001", "sign_date": "2026-11-21", "currency": "HKD",
        "client_name": "李四", "client_id": "ID4321", "client_phone": "13900000000",
        "client_address": "深圳市福田区", "seller_rep": "", "plate": "AB1234",
        "vin": "WBA123456", "mileage": "45000", "reg_number": "", "total_price": 300000,
        "delivery_date": "2026-11-28", "transfer_deadline": "", "reg_keep": "随车辆一并转让"}
PAY = {"mode": "car_buy", "installments": [
    {"seq": 1, "label": "首期款", "amount": 100000},
    {"seq": 2, "label": "余款", "amount": 200000}]}

issues = []
out = os.path.join(TMP, "收车.docx")
r = build_contract("car_buy", FORM, PAY, "20261121001", out, draft=True, issues=issues)
check(not issues, f"构建零 issue（{issues}）")
check(r.get("company_sealed") is True, "report.company_sealed=True")
doc = Document(out)
full = "\n".join(p.text for p in doc.paragraphs)

# 1) 编号行
check(doc.paragraphs[0].text.startswith("合约编号 / AGREEMENT NO.: 20261121001")
      and "2026年11月21日" in doc.paragraphs[0].text, "顶部编号/签署日期行落值")

# 2) 双方表 + 车辆表
comp, cli = seal_mod_locate = S.locate(doc), None
party_t = next(t for t in doc.tables if "卖方（甲方）" in " ".join(c.text for c in t.rows[0].cells))
vals = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in party_t.rows}
check(vals.get("卖方（甲方）") == "李四", "卖方名称落值（双栏表 col1）")
check(vals.get("身份证明／公司注册编号") == "ID4321", "卖方证件落值（身份证明映射）")
buyer_vals = {row.cells[2].text.strip(): row.cells[3].text.strip() for row in party_t.rows}
check(buyer_vals.get("买方（乙方）") == "华星资源开发有限公司"
      and buyer_vals.get("公司注册编号") == "77788156", "买方侧常量在 col2/col3")
veh_t = next(t for t in doc.tables if "车牌号码" in " ".join(c.text for c in t.rows[0].cells))
vvals = {row.cells[0].text.strip(): row.cells[1].text.strip() for row in veh_t.rows}
check(vvals.get("车牌号码") == "AB1234" and "WBA123456" in vvals.get("车身底盘号码", ""), "车牌/底盘落值")
check("45000 公里" in vvals.get("签约时里程表读数", ""), f"里程带单位（{vvals.get('签约时里程表读数')}）")

# 3) 金额三句：大写 + 双币（对外付款按实汇率，无 1.01 加成）
def para_has(*keys):
    for p in doc.paragraphs:
        if all(k in p.text for k in keys):
            return p
    return None
rate = r["fx_rate"]
import sys as _sys
_sys.path.insert(0, os.path.join(ROOT, "server"))
from engine.money import convert_amount
p_total = para_has("购买总价为港币")
check(p_total is not None and "港币叁拾万元整" in p_total.text and "HK$300,000 / ¥" in p_total.text,
      f"总价句大写+双币（{p_total.text.strip()[:50]}）")
cny = int(p_total.text.split("¥")[1].split("）")[0].replace(",", ""))
check(cny == convert_amount(300000, "HKD", rate, markup=False), f"总价人民币按实汇率（¥{cny}，无加成）")
p_dep = para_has("支付首期款港币")
check(p_dep is not None and "港币壹拾万元" in p_dep.text and "HK$100,000 / ¥" in p_dep.text, "首期款句落值")
p_bal = para_has("向卖方支付余款港币")
check(p_bal is not None and "HK$200,000 / ¥" in p_bal.text, "余款句落值")

# 4) 日期/期限
p_dd = para_has("卖方应于2026年11月28日")
check(p_dd is not None, "交资料日期落值")
check(para_has("2027年1月21日或之前") is not None, "过户期限=签署日+2个月")

# 5) 登记号码 + 二选一
check(para_has("现有登记号码为：AB1234") is not None, "登记号码随车牌自动带出")
check(para_has("随车辆一并转让予买方或买方指定承让人") is not None
      and not any("不包括在本次交易内" in p.text for p in doc.paragraphs)
      and not any("☐" in p.text for p in doc.paragraphs), "二选一：随车转让选中、保留项删除、无☐残留")

# 6) 签署块：印章 A 路径在新版式上生效 + 签署日期落值
comp, cli = S.locate(doc)
check(comp is not None and cli is not None and "华星" in comp.text and "____" in cli.text,
      "签署块公司格/客户格定位（华星=买方格）")
check(len(comp._tc.xpath(".//pic:pic")) == 2, "公司格 2 图（签字+章）")
sign_dates = [p.text for t in doc.tables for row in t.rows for c in row.cells
              for p in c.paragraphs if "日期：2026" in p.text]
check(len(sign_dates) == 2, f"签署块两侧日期落值（{len(sign_dates)} 处）")

# 7) checker：签署块/信息表指纹与空位
r2 = dict(r); r2["agreement_no"] = "20261121001"
more = C.check_rules("car_buy", FORM, PAY, r2, doc)
check(not [i for i in more if "空位" in i or "格式异常" in i],
      f"checker 无结构类问题（{more}）")

# 8) reg_keep 卖方保留变体
form_b = dict(FORM, reg_keep="卖方保留或更换")
out_b = os.path.join(TMP, "收车保留.docx")
build_contract("car_buy", form_b, PAY, "20261121002", out_b, draft=True, issues=[])
doc_b = Document(out_b)
check(any("不包括在本次交易内" in p.text for p in doc_b.paragraphs)
      and not any("随车辆一并转让" in p.text for p in doc_b.paragraphs), "保留变体：留下保留项、删除随车项")

# 9) 金额合计拦截（首期+余款 ≠ 总价）
try:
    derive_payment("car_buy", {"installments": [
        {"label": "首期款", "amount": 100000}, {"label": "余款", "amount": 150000}]},
        total=300000)
    check(False, "金额不齐应拦截")
except ValueError as ex:
    check("购买总价" in str(ex), f"金额不齐拦截（{str(ex)[:36]}…）")

# 10) 实际交付日期（四.3）：填了→年月日+当天24:00；未填→空位保留打印后手写
check(any("实际交付日期及时间为：____" in p.text for p in doc.paragraphs),
      "未填时实际交付空位保留（手写签注）")
form_c = dict(FORM, actual_delivery="2026-12-01")
out_c = os.path.join(TMP, "收车实际交车.docx")
build_contract("car_buy", form_c, PAY, "20261121003", out_c, draft=True, issues=[])
doc_c = Document(out_c)
check(any("实际交付日期及时间为：2026年12月1日24时00分" in p.text for p in doc_c.paragraphs),
      "实际交付日期落值（时分按当天24:00 口径）")

# 11) 真实生成（非 draft）+ 完整指纹比对 = 生产下载路径：必须零错误
from engine.checker import check_fingerprint
form_r = dict(FORM, actual_delivery="2026-12-05", reg_keep="卖方保留或更换")
out_r = os.path.join(TMP, "收车真实.docx")
r_r = build_contract("car_buy", form_r, PAY, "20261121004", out_r)
fp = check_fingerprint(r_r["template"], out_r, "car_buy", r_r, form_r)
check(not fp, f"指纹比对零错误（{fp}）")
doc_r = Document(out_r)
check(any("不包括在本次交易内" in p.text for p in doc_r.paragraphs),
      "真实件：保留变体落盘")
check(any("实际交付日期及时间为：2026年12月5日24时00分" in p.text for p in doc_r.paragraphs),
      "真实件：实际交付落值")

print()
print("总体:", "全部通过" if not FAIL else f"{len(FAIL)} 项失败")
sys.exit(1 if FAIL else 0)
