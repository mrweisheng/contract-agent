# -*- coding: utf-8 -*-
"""公司印信注入离线测试：真引擎出合同 + 印信文件落隔离目录，不碰真实印信。
覆盖：生成即盖章（车/高才两种版式）、缺图跳过、客户签名落客户格（角色修正）、用印日志。"""
import sys, io, os, json, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "seal_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(os.path.join(TMP, "seals"))

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP
store.OUT_DIR = TMP
store.init()

# 印信打桩：小 PNG 落隔离目录，seals_dir 指过去
from PIL import Image as PILImage
for name, size, color in (("seal.png", (60, 60), (40, 40, 160)), ("sign.png", (80, 30), (20, 20, 20))):
    PILImage.new("RGB", size, color).save(os.path.join(TMP, "seals", name), "PNG")
from engine import seal as seal_mod
seal_mod.seals_dir = lambda: os.path.join(TMP, "seals")

from engine.builder import build_contract
from api import open_api

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)

def pics(cell):
    return len(cell._tc.xpath(".//pic:pic"))

form_car = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "HKD",
            "client_name": "测试买方", "client_id": "H123456(7)", "client_phone": "91234567",
            "plate": "LN 1234", "vin": "WIN0000000000001", "model": "Toyota Alphard",
            "year": "2024", "total_price": 500000}
pay_car = {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-11-20",
           "balance_date": "2026-12-20", "choice": "较早者"}

# 1) 卖车：生成即盖章（公司=甲方格），客户格零图片；落位=签字/章段紧贴日期段之前，
#    客户格对称插等高空段（两边日期同一水平线）
out_car = os.path.join(TMP, "车.docx")
report = build_contract("car", dict(form_car), pay_car, "T001", out_car)
check(report.get("company_sealed") is True, "卖车 report.company_sealed=True")
from docx import Document
from docx.enum.text import WD_LINE_SPACING
doc_car = Document(out_car)
comp, cli = seal_mod.locate(doc_car)
check("华星" in comp.text and pics(comp) == 2, f"公司格含华星且 2 图（实际 {pics(comp)}）")
check(pics(cli) == 2, "客户格含 2 张透明占位图（与公司格渲染路径一致）")
sign_h = seal_mod._img_height_in(os.path.join(TMP, "seals", "sign.png"), 1.6)
seal_h = seal_mod._img_height_in(os.path.join(TMP, "seals", "seal.png"), 1.3)
paras = comp.paragraphs
pic_idx = [i for i, p in enumerate(paras) if p._p.xpath(".//pic:pic")]
date_idx = next(i for i, p in enumerate(paras) if "日期" in p.text)
stamp_idx = next(i for i, p in enumerate(paras) if "公司印章" in p.text)
check(pic_idx == [stamp_idx - 1, date_idx - 1] and stamp_idx == date_idx - 2,
      f"统一骨架 线→签字→公司印章→章→日期（pic {pic_idx} 印章 {stamp_idx} 日期 {date_idx}）")
spacers = [p for p in cli.paragraphs
           if p.paragraph_format.line_spacing_rule == WD_LINE_SPACING.EXACTLY
           and p.paragraph_format.line_spacing is not None]
hs = sorted([round(p.paragraph_format.line_spacing.pt, 1) for p in spacers], reverse=True)
expect = sorted([round(sign_h * 72, 1), round(seal_h * 72, 1)], reverse=True)
check(len(spacers) == 2 and all(abs(a - b) < 0.5 for a, b in zip(hs, expect)),
      f"客户格两个等高占位段 ({hs} ≈ {expect})")
store.confirm_no("T001", "car", "测试买方", "default", "HKD", "车.docx", "ok")

# 1b) 过户（软换行单段版式）：签字/章插在段内签名线/公司印章换行处，客户格透明占位
form_gx = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "CNY",
           "client_name": "测试委托方", "client_id": "H9(8)", "client_phone": "13900000000",
           "plate": "粤Z1234", "port": "莲塘口岸", "target_hk_company": "测试香港公司",
           "quota_type": "高新", "total_fee": 250000, "exchange_fee": 0}
out_gx = os.path.join(TMP, "过户.docx")
r_gx = build_contract("transfer_gx", dict(form_gx), {"mode": "default"}, "T004", out_gx)
check(r_gx.get("company_sealed") is True, "过户 report.company_sealed=True")
doc_g = Document(out_gx)
comp_g, cli_g = seal_mod.locate(doc_g)
paras_g = comp_g.paragraphs
pic_idx_g = [i for i, p in enumerate(paras_g) if p._p.xpath(".//pic:pic")]
stamp_idx_g = next(i for i, p in enumerate(paras_g) if "公司印章" in p.text)
date_idx_g = next(i for i, p in enumerate(paras_g) if "日期" in p.text)
check(pic_idx_g == [stamp_idx_g - 1, date_idx_g - 1] and stamp_idx_g == date_idx_g - 2,
      f"过户统一骨架（pic {pic_idx_g} 印章 {stamp_idx_g} 日期 {date_idx_g}）")
cli_pics = [i for i, p in enumerate(cli_g.paragraphs) if p._p.xpath(".//pic:pic")]
check(len(cli_pics) == 2, "过户客户格 2 张透明占位图")
store.confirm_no("T004", "transfer_gx", "测试委托方", "default", "CNY", "过户.docx", "ok")

# 2) 高才移民：公司是乙方格，同样盖进公司格；客户签名（角色修正）落甲方客户格
form_imm = {"agreement_no": "", "sign_date": "2026-11-20", "currency": "CNY",
            "client_name": "测试委托方", "client_id": "H98765(8)", "client_phone": "13900000000",
            "client_address": "深圳市福田区", "total_fee": 400000,
            "lead_applicant": "测试委托方", "spouse_name": "测试配偶",
            "minor_children": "1", "total_applicants": "3"}
pay_imm = {"mode": "custom", "installments": [
    {"seq": 1, "amount": 200000, "label": "第一期", "trigger": "签订合约后三个工作日内", "trigger_date": ""},
    {"seq": 2, "amount": 100000, "label": "第二期", "trigger": "递交申请后", "trigger_date": ""},
    {"seq": 3, "amount": 100000, "label": "第三期", "trigger": "获得香港居民身份证后", "trigger_date": ""}]}
out_imm = os.path.join(TMP, "移民.docx")
r2 = build_contract("immigration", form_imm, pay_imm, "T002", out_imm)
check(r2.get("company_sealed") is True, "移民 report.company_sealed=True")
doc_i = Document(out_imm)
comp_i, cli_i = seal_mod.locate(doc_i)
check("华星" in comp_i.text and pics(comp_i) == 2, "移民公司格（乙方侧）2 图")
check(pics(cli_i) == 0 and "华星" not in cli_i.text and "____" in cli_i.text,
      "移民客户格=下划线签名栏且无图（非华星格）")
# 客户签名回传 → 落客户格（旧逻辑按「乙方」找会错盖进华星格）
import base64
sig_png = os.path.join(TMP, "seals", "sign.png")   # 拿小 PNG 顶签名图
sig_b64 = "data:image/png;base64," + base64.b64encode(open(sig_png, "rb").read()).decode()
signed_i = os.path.join(TMP, "移民-已签.docx")
open_api.apply_signature(out_imm, signed_i, base64.b64decode(sig_b64.split(",")[1]))
doc_s = Document(signed_i)
c2, cli2 = seal_mod.locate(doc_s)
check(pics(c2) == 2 and pics(cli2) == 1, f"已签版：公司格 2 图+客户格 1 图（{pics(c2)}/{pics(cli2)}）")
check("华星" in c2.text and "华星" not in cli2.text, "客户签名落在客户格而非华星格")

# 3) 缺印信文件 → 跳过注入，文档零图不报错
seal_mod.seals_dir = lambda: os.path.join(TMP, "no-seals")
out_bare = os.path.join(TMP, "无印.docx")
r3 = build_contract("car", dict(form_car), pay_car, "T003", out_bare)
check(r3.get("company_sealed") is False, "缺图时 company_sealed=False")
check(len(Document(out_bare).inline_shapes) == 0, "缺图时原版零图片")
seal_mod.seals_dir = lambda: os.path.join(TMP, "seals")   # 还原

# 4) blocks sign 块带 stamped 标记（有印信 True / 无印信 False）
blocks = open_api.extract_blocks(out_car)
sign_blk = [b for b in blocks if b["kind"] == "sign"][0]
check(sign_blk.get("stamped") is True, "有印信 → sign 块 stamped=True")
blocks_bare = open_api.extract_blocks(out_bare)
sign_bare = [b for b in blocks_bare if b["kind"] == "sign"][0]
check(sign_bare.get("stamped") is False, "无印信 → sign 块 stamped=False")

# 5) 用印日志：mark_sealed 落 sealed_at
store.mark_sealed("T001")
check(store.get_gen("T001")["sealed_at"], "gens.sealed_at 已留痕")

# 6) 印信端点：固定名白名单
from fastapi import HTTPException as HE
try:
    open_api._seal_asset("../contracts.db"); check(False, "路径穿越应 404")
except HE as ex:
    check(ex.status_code == 404, "印信端点路径穿越 → 404")

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
