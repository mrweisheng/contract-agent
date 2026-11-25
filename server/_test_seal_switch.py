# -*- coding: utf-8 -*-
"""「电子签章」开关离线测试（2026-11-25）：工作台取消勾选 → 预览与生成的合同不带公司签字/公章。
隔离：库/产物/印信打桩全落临时目录；汇率走缓存种子，不联网、不调 LLM。
覆盖：未盖章版式＝盖章版把公司格实体图换成同尺寸透明占位（A 两列 / B 移民四列）、
核对器照过、客户小程序签名落位不变、对外/小程序 blocks stamped=false（含已签后）、
generate/preview 路由开关与未盖章标记、PDF 骑缝章跳过、不传开关＝盖章（老页面零影响）。
用法：cd server && python _test_seal_switch.py"""
import sys, io, os, base64, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "seal_switch_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(os.path.join(TMP, "seals"))

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP
store.OUT_DIR = TMP
store.init()
store.fx_put("HKD", "CNY", 0.88, "test")   # 汇率缓存种子：generate/preview 不打外网

from PIL import Image as PILImage
for name, size, color in (("seal.png", (60, 60), (40, 40, 160)), ("sign.png", (80, 30), (20, 20, 20))):
    PILImage.new("RGB", size, color).save(os.path.join(TMP, "seals", name), "PNG")
SEALS = os.path.join(TMP, "seals")
from engine import seal as seal_mod
from engine import pdf as pdf_mod
seal_mod.seals_dir = lambda: SEALS
pdf_mod._seals_dir = lambda: SEALS

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from engine.builder import build_contract
from engine.checker import check_rules, check_fingerprint
from api import routes, open_api
from fastapi import BackgroundTasks

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)


def solid_pics(el, part) -> int:
    """元素范围内的实体图数（非全透明）：透明占位不算。"""
    n = 0
    for blip in el.xpath(".//a:blip"):
        with PILImage.open(io.BytesIO(part.related_parts[blip.get(qn("r:embed"))].blob)) as im:
            if im.convert("RGBA").getchannel("A").getextrema()[1] > 0:
                n += 1
    return n


def texts(cell):
    return [p.text for p in cell.paragraphs]


def min_heights(cell):
    """格内 AT_LEAST 行高段（图片段/占位段）的行高（pt）：骨架等高的证据。"""
    return [round(p.paragraph_format.line_spacing.pt, 1) for p in cell.paragraphs
            if p.paragraph_format.line_spacing_rule == WD_LINE_SPACING.AT_LEAST]


def rest_of(doc_a, doc_b) -> bool:
    """签署块两格以外的全文文字是否一致（段落序列 + 其余表格格文字）。"""
    def rest(doc):
        loc = seal_mod.locate(doc)
        sign_tc = {loc[0]._tc, loc[1]._tc} if loc else set()
        tbls = [tuple(tuple(c.text for c in r.cells if c._tc not in sign_tc) for r in t.rows)
                for t in doc.tables]
        return [p.text for p in doc.paragraphs], tbls
    return rest(doc_a) == rest(doc_b)


form_car = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "HKD",
            "client_name": "测试买方", "client_id": "H123456(7)", "client_phone": "91234567",
            "plate": "LN 1234", "vin": "WIN0000000000001", "model": "Toyota Alphard",
            "year": "2024", "total_price": 500000}
pay_car = {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-11-20",
           "balance_date": "2026-12-20", "choice": "较早者"}
form_gx = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "CNY",
           "client_name": "测试委托方", "client_id": "H9(8)", "client_phone": "13900000000",
           "plate": "粤Z1234", "port": "莲塘口岸", "target_hk_company": "测试香港公司",
           "quota_type": "高新", "total_fee": 250000, "exchange_fee": 0}
form_np = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "CNY",
           "client_name": "测试委托方", "client_id": "H9(8)", "client_phone": "13900000000",
           "port": "沙头角口岸", "total_fee": 200000}
pay_np = {"mode": "default", "pay1": 50000, "pay2": 100000, "pay3": 50000}
form_imm = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "CNY",
            "client_name": "测试委托方", "client_id": "H98765(8)", "client_phone": "13900000000",
            "client_address": "深圳市福田区", "total_fee": 400000,
            "lead_applicant": "测试委托方", "spouse_name": "测试配偶",
            "minor_children": "1", "total_applicants": "3"}
pay_imm = {"mode": "custom", "installments": [
    {"seq": 1, "amount": 200000, "label": "第一期", "trigger": "签订合约后三个工作日内", "trigger_date": ""},
    {"seq": 2, "amount": 100000, "label": "第二期", "trigger": "递交申请后", "trigger_date": ""},
    {"seq": 3, "amount": 100000, "label": "第三期", "trigger": "获得香港居民身份证后", "trigger_date": ""}]}

# (标签, 类型, 表单, 付款, 盖章版公司格实体图数)
CASES = [("卖车（A 两列）", "car", form_car, pay_car, 2),
         ("高新过户（A 软换行）", "transfer_gx", form_gx, {"mode": "default"}, 2),
         ("新办沙头角（A）", "new_port", form_np, pay_np, 2),
         ("高才移民（B 四列）", "immigration", form_imm, pay_imm, 1)]
sig_buf = io.BytesIO()
PILImage.new("RGBA", (340, 120), (20, 20, 20, 255)).save(sig_buf, "PNG")
SIG = sig_buf.getvalue()
FILES = {}

print("== 1. 引擎：未盖章版式 = 盖章版去掉公司格实体图 ==")
for i, (label, tkey, form, pay, n_pic) in enumerate(CASES):
    p_se, p_un = os.path.join(TMP, f"{tkey}-盖章.docx"), os.path.join(TMP, f"{tkey}-未盖章.docx")
    no = "20261125001"   # 两版同号：签署块以外逐字可比
    r_se = build_contract(tkey, dict(form), pay, no, p_se)
    r_un = build_contract(tkey, dict(form), pay, no, p_un, seal=False)
    r_un["agreement_no"] = no   # 路由层在 build 后补的核对器入参
    check(r_se.get("company_sealed") is True and r_un.get("company_sealed") is False,
          f"{label}：company_sealed 盖章=True / 未盖章=False")
    d_se, d_un = Document(p_se), Document(p_un)
    c_se, l_se = seal_mod.locate(d_se)
    c_un, l_un = seal_mod.locate(d_un)
    FILES[tkey] = (p_se, p_un)
    check(solid_pics(c_se._tc, c_se.part) == n_pic and solid_pics(c_un._tc, c_un.part) == 0,
          f"{label}：公司格实体图 盖章 {solid_pics(c_se._tc, c_se.part)} / 未盖章 {solid_pics(c_un._tc, c_un.part)}")
    check(solid_pics(l_un._tc, l_un.part) == 0, f"{label}：未盖章件客户格无实体图")
    check(texts(c_se) == texts(c_un) and texts(l_se) == texts(l_un),
          f"{label}：两格段落文字序列与盖章版一致")
    check(len(c_se._tc.xpath(".//a:blip")) == len(c_un._tc.xpath(".//a:blip")),
          f"{label}：公司格图片段数不变（实体图→同位置透明占位）")
    check(min_heights(c_se) == min_heights(c_un) and min_heights(l_se) == min_heights(l_un),
          f"{label}：占位段行高与盖章版图片段一致")
    check(rest_of(d_se, d_un), f"{label}：签署块以外全文文字与盖章版一致")
    errs = check_rules(tkey, form, pay, r_un, d_un) + \
        check_fingerprint(r_un["template"], p_un, tkey, r_un, form)
    check(not errs, f"{label}：未盖章件核对器通过 {errs or ''}")

print("\n== 2. 小程序客户签名：落位与盖章版一致 ==")
for label, tkey, form, pay, n_pic in CASES:
    p_se, p_un = FILES[tkey]
    s_se, s_un = p_se[:-5] + "-已签.docx", p_un[:-5] + "-已签.docx"
    open_api.apply_signature(p_se, s_se, SIG)
    open_api.apply_signature(p_un, s_un, SIG)
    k_se, k_un = seal_mod.locate(Document(s_se)), seal_mod.locate(Document(s_un))
    check(texts(k_se[0]) == texts(k_un[0]) and texts(k_se[1]) == texts(k_un[1]),
          f"{label}：已签版两格段落序列与盖章版一致")
    doc_se, doc_un = Document(s_se), Document(s_un)
    idx_se = [j for j, p in enumerate(k_se[1].paragraphs) if solid_pics(p._p, doc_se.part)]
    idx_un = [j for j, p in enumerate(k_un[1].paragraphs) if solid_pics(p._p, doc_un.part)]
    check(len(idx_un) == 1 and idx_un == idx_se,
          f"{label}：客户签名落在同一段位（盖章 {idx_se} / 未盖章 {idx_un}）")

print("\n== 3. 对外/小程序 blocks：未盖章单 stamped=false ==")
p_se, p_un = FILES["car"]
s_un = p_un[:-5] + "-已签.docx"
sign = lambda blks: [b for b in blks if b["kind"] == "sign"][0]
b_se = sign(open_api._extract_blocks_safe({"filename": os.path.basename(p_se), "unsealed": 0}))
b_un = sign(open_api._extract_blocks_safe({"filename": os.path.basename(p_un), "unsealed": 1}))
b_uns = sign(open_api._extract_blocks_safe({"filename": os.path.basename(s_un), "unsealed": 1}))
check(b_se["stamped"] is True, "盖章单 stamped=True")
check(b_un["stamped"] is False, "未盖章单 stamped=False（版式同盖章版，不叠印信图）")
check(b_uns["stamped"] is False, "未盖章单客户签完后仍 stamped=False（签署格里多了签名实体图）")
check(b_se["rows"] == b_un["rows"], "未盖章单 sign 块 rows 与盖章版一致（小程序版式不变）")
check(sign(open_api._extract_blocks_safe({"filename": os.path.basename(p_un)}))["stamped"] is True,
      "记录无 unsealed 键 → 按有图判（历史单原行为）")
check(sign(open_api.extract_blocks(p_un, sealed=False))["stamped"] is False,
      "extract_blocks(sealed=False) 直接判 False")

print("\n== 4. 路由：generate / preview 开关 + 未盖章标记 ==")
rows = [routes.PayRow(label="订金", amount=100000, date="2026-11-20"),
        routes.PayRow(label="尾款", amount=400000, date="2026-12-20")]
payment = routes.Payment(installments=rows)
raw_pay = {"installments": [{"label": r.label, "amount": r.amount, "date": r.date, "event": ""} for r in rows]}
r_un = routes.generate(routes.GenerateReq(type="car", form=dict(form_car), payment=payment, seal=False),
                       BackgroundTasks())
check(r_un.get("ok") is True, f"seal=False 生成成功（{r_un.get('errors') or ''}）")
rec_un = store.get_gen(r_un["no"])
check(rec_un["unsealed"] == 1 and rec_un["sealed_at"] == "",
      f"未盖章标记 unsealed=1 且不记用印日志（sealed_at=「{rec_un['sealed_at']}」）")
doc_un = Document(os.path.join(TMP, r_un["filename"]))
comp_un, _ = seal_mod.locate(doc_un)
check(solid_pics(comp_un._tc, doc_un.part) == 0, "落盘成品公司格无实体图")
r_se = routes.generate(routes.GenerateReq(type="car", form=dict(form_car), payment=payment),
                       BackgroundTasks())   # 不传开关＝老页面/旧调用方
check(r_se.get("ok") is True, "不传开关 生成成功")
rec_se = store.get_gen(r_se["no"])
check(rec_se["unsealed"] == 0 and rec_se["sealed_at"] != "", "不传开关：无未盖章标记、用印日志照记")
doc_se = Document(os.path.join(TMP, r_se["filename"]))
comp_se, _ = seal_mod.locate(doc_se)
check(solid_pics(comp_se._tc, doc_se.part) == 2, "不传开关：落盘成品公司格 2 张实体图")
check(rec_se["filename"] != rec_un["filename"], "两次生成文件名不撞")

pv_un = routes.preview(routes.PreviewReq(type="car", form=dict(form_car), payment=raw_pay, seal=False))
doc_pv = Document(io.BytesIO(base64.b64decode(pv_un["docx_b64"])))
check(solid_pics(seal_mod.locate(doc_pv)[0]._tc, doc_pv.part) == 0, "preview seal=False：预览件无实体图")
pv_se = routes.preview(routes.PreviewReq(type="car", form=dict(form_car), payment=raw_pay))
doc_pv = Document(io.BytesIO(base64.b64decode(pv_se["docx_b64"])))
check(solid_pics(seal_mod.locate(doc_pv)[0]._tc, doc_pv.part) == 2, "preview 不传开关：预览件 2 张实体图")

print("\n== 5. PDF：未盖章合同不盖骑缝章 ==")
from reportlab.pdfgen import canvas as rl_canvas
base_pdf = os.path.join(TMP, "base.pdf")
c = rl_canvas.Canvas(base_pdf, pagesize=(595, 842))
for i in range(3):
    c.setFont("Helvetica", 12)
    c.drawString(72, 770, f"page {i + 1}")
    c.showPage()
c.save()
BASE = open(base_pdf, "rb").read()
pdf_mod.run_soffice = lambda docx_path, out_dir: shutil.copyfile(   # soffice 打桩：不做真转换
    base_pdf, os.path.join(out_dir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"))
check(open(pdf_mod.ensure_pdf(p_se), "rb").read() != BASE, "盖章合同 PDF 叠了骑缝章")
check(open(pdf_mod.ensure_pdf(p_un, cross_seal=False), "rb").read() == BASE,
      "未盖章合同 PDF 不叠骑缝章（＝转换产物）")
check(open(routes.download(r_un["no"], format="pdf").path, "rb").read() == BASE,
      "download?format=pdf：未盖章合同拿到的 PDF 无骑缝章")
check(open(routes.download(r_se["no"], format="pdf").path, "rb").read() != BASE,
      "download?format=pdf：盖章合同照旧盖骑缝章")
# 历史单（无标记）走 ensure_pdf 默认参数 → 照旧盖
hist = os.path.join(TMP, "历史单.docx")
shutil.copyfile(p_se, hist)
check(open(pdf_mod.ensure_pdf(hist), "rb").read() != BASE, "ensure_pdf 默认参数（历史调用方）仍盖骑缝章")

print("\n== 6. 缺印信文件 + 取消勾选 ==")
seal_mod.seals_dir = lambda: os.path.join(TMP, "no-seals")
p_bare = os.path.join(TMP, "缺印-未盖章.docx")
r_bare = build_contract("car", dict(form_car), pay_car, "20261125003", p_bare, seal=False)
check(r_bare.get("company_sealed") is False and len(Document(p_bare).inline_shapes) == 0,
      "缺印信 + 取消勾选：零图、不报错、company_sealed=False")

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
