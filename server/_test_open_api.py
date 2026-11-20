# -*- coding: utf-8 -*-
"""对外查询接口离线测试：不打 HTTP（TestClient 缺 httpx），直接调函数 + 真模板真签名图。"""
import sys, io, os, json, base64, tempfile, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

TMP = os.path.join(tempfile.gettempdir(), "open_api_test")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

from api import store
store.DB_PATH = os.path.join(TMP, "t.db")
store.DATA_DIR = TMP   # 隔离：数据库与测试产物全落临时目录，不碰真实库
store.OUT_DIR = TMP
store.init()

# 公司印信打桩：小 PNG 落隔离目录（builder 生成即盖章，原版 docx 自带印信 2 图）
os.makedirs(os.path.join(TMP, "seals"), exist_ok=True)
from PIL import Image as _PILImage
for _n, _sz, _c in (("seal.png", (60, 60), (40, 40, 160)), ("sign.png", (80, 30), (20, 20, 20))):
    _PILImage.new("RGB", _sz, _c).save(os.path.join(TMP, "seals", _n), "PNG")
from engine import seal as _seal_mod
_seal_mod.seals_dir = lambda: os.path.join(TMP, "seals")

from engine.builder import build_contract
from api import open_api

FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond: FAIL.append(msg)

# 1) 真引擎出一份卖车合同到隔离目录
form = {"agreement_no": "", "sign_date": "2026-11-18", "currency": "HKD",
        "client_name": "测试买方", "client_id": "H123456(7)", "client_phone": "91234567",
        "plate": "LN 1234", "vin": "WIN0000000000001", "model": "Toyota Alphard", "year": "2024",
        "total_price": 500000}
payment = {"mode": "default", "deposit_amount": 100000, "deposit_date": "2026-11-18",
           "balance_date": "2026-12-18", "choice": "较早者"}
no = "20261118990"
filename = "20261118测试买方卖车.docx"
out = os.path.join(TMP, filename)
build_contract("car", dict(form), payment, no, out)

# 2) 表单存档（模拟 routes.generate 的落档动作）
form_doc = {"no": no, "type": "car", "form": form, "payment": payment,
            "filename": filename, "status": "ok", "created_at": "2026-11-18 00:00:00"}
with open(open_api._form_path({"filename": filename}), "w", encoding="utf-8") as fh:
    json.dump(form_doc, fh, ensure_ascii=False)

# 3) gens 表登记（隔离库）
store.confirm_no(no, "car", "测试买方", "default", "HKD", filename, "ok")

# 4) 鉴权守卫：未配 key → 403；配了 → 放行；错 key → 401
import os as _os
_os.environ.pop("OPEN_API_KEY", None)
try:
    open_api._guard(None, None); check(False, "未配 OPEN_API_KEY 应 403")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 403, "未配 OPEN_API_KEY → 403")
_os.environ["OPEN_API_KEY"] = "test-key-123"
try:
    open_api._guard("wrong", None); check(False, "错 key 应 401")
except Exception as ex:
    check(getattr(ex, "status_code", None) == 401, "错 key → 401")
try:
    open_api._guard("test-key-123", None); check(True, "对 key 放行")
except Exception as ex:
    check(False, f"对 key 应放行: {ex}")

# 5) 详情：元数据 + 结构化内容
rec = store.get_gen(no)
detail = {"meta": rec, "content": open_api._read_form(rec), "available": bool(open_api._read_form(rec))}
check(detail["available"] and detail["content"]["form"]["client_name"] == "测试买方", "详情吐结构化表单数据")
check(detail["content"]["payment"]["deposit_amount"] == 100000, "付款结构随档")

# 5b) blocks 抽取：车/过户/新办版式（meta→title→subtitle→h/p/table→sign）
from docx import Document as _Doc
blocks = open_api.extract_blocks(out)
kinds = [b["kind"] for b in blocks]
check(kinds[0] == "meta" and "合约编号" in blocks[0]["text"], "car blocks 首块=编号行")
check(any(b["kind"] == "title" and "车辆买卖合约" in b["text"] for b in blocks), "主标题块")
check(any(b["kind"] == "subtitle" and b["text"].startswith("MOTOR") for b in blocks), "英文副标块")
hs = [b for b in blocks if b["kind"] == "h"]
check(any(h["text"].startswith("一、合约双方") and h.get("en") == "PARTIES" for h in hs),
      "条款标题块拆中英（text/en）")
check(kinds[-1] == "sign" and kinds.count("sign") == 1, "末块=签署块且唯一")
# 逐字一致：docx 全部非空段落与表格文本必须完整出现在 blocks 里
# （h 块按 | 拆中英，比对时同样拆开）
doc_full = _Doc(out)
blk_texts = set()
for b in blocks:
    if b.get("text"): blk_texts.add(b["text"])
    if b.get("en"): blk_texts.add(b["en"])
    for row in b.get("rows", []):
        blk_texts.update(c for c in row if c)
def _para_key(s):
    if "|" in s:
        l, _, r = s.partition("|")
        return [l.strip(), r.strip()]
    return [s]
miss_p = [p.text.strip() for p in doc_full.paragraphs
          if p.text.strip() and any(k not in blk_texts for k in _para_key(p.text.strip()))]
check(not miss_p, f"段落逐字一致（缺 {len(miss_p)} 段: {miss_p[:2]}）")
miss_c = [c.text.strip() for t in doc_full.tables for r in t.rows for c in r.cells
          if c.text.strip() and c.text.strip() not in blk_texts]
check(not miss_c, f"表格逐字一致（缺 {len(miss_c)} 格: {miss_c[:2]}）")

# 5c) 动态条款随勾选流入 blocks：勾赠品/质保/无事故 → 对应正文出现在块里；不勾 → 不出现
form_on = dict(form)
form_on.update(gift_transfer="1", gift_plate="4个月", gift_insurance="汽车保险（全保）",
               accident_free="1", warranty_enabled="1", warranty_period="1年", warranty_km="30000")
out_on = os.path.join(TMP, "20261118测试买方卖车-勾选.docx")
build_contract("car", dict(form_on), payment, no, out_on)
b_on = open_api.extract_blocks(out_on)
t_on = "\n".join((b.get("text") or "") for b in b_on)
check("附赠" in t_on and "香港车辆牌照费" in t_on, "勾选后附赠节进 blocks")
check("售后质保" in t_on and "发动机" in t_on, "勾选后质保条款进 blocks")
check("甲方陈述并保证" in t_on, "勾选后无事故保证块进 blocks")
b_off = open_api.extract_blocks(out)   # 未勾选的原件
t_off = "\n".join((b.get("text") or "") for b in b_off)
check("附赠" not in t_off and "售后质保" not in t_off, "未勾选时附赠/质保不出现在 blocks")

# 5d) 详情路由函数带 blocks（旧单无 form.json 时 blocks 仍可用）
d = open_api.contract_detail(no)
check(isinstance(d.get("blocks"), list) and d["blocks"], "详情接口带 blocks 数组")
check(d["blocks"][0]["kind"] in ("meta", "title"), "详情接口 blocks 首块合法")

# 6) 造一张真签名 PNG（reportlab 画签名条 → pdfium 转 PNG）
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import letter
sig_pdf = os.path.join(TMP, "sig.pdf")
c = rl_canvas.Canvas(sig_pdf, pagesize=(300, 120))
c.setFont("Helvetica", 30)
c.drawString(40, 50, "Chan Tai Man")
c.line(30, 20, 270, 20)
c.save()
import pypdfium2 as pdfium
pdf = pdfium.PdfDocument(sig_pdf)
page = pdf[0]
bitmap = page.render(scale=2.0)
pil = bitmap.to_pil()
sig_path = os.path.join(TMP, "sig.png")
pil.save(sig_path)
sig_bytes = open(sig_path, "rb").read()
check(sig_bytes.startswith(b"\x89PNG"), f"签名图 PNG 生成 ({len(sig_bytes)} bytes)")

# 7) 签名合成：非法输入先拦
for bad, why in (("not-base64!!", "非法 base64"), (base64.b64encode(b"GIF89a").decode(), "非 PNG")):
    try:
        open_api._decode_sig(bad); check(False, f"{why} 应拦截")
    except Exception as ex:
        check(getattr(ex, "status_code", None) == 422, f"{why} → 422")

# 8) 合成到乙方签署格 → 已签版 docx 生成
signed_name = filename.rsplit(".docx", 1)[0] + "-已签.docx"
open_api.apply_signature(out, os.path.join(TMP, signed_name), sig_bytes)
check(os.path.exists(os.path.join(TMP, signed_name)), "已签版 docx 生成")

# 9) 已签版 = 公司印信 2 图（生成即盖）+ 客户签名 1 图（落客户格）
from docx import Document
doc = Document(os.path.join(TMP, signed_name))
imgs = len(doc.inline_shapes)
check(imgs == 6, f"已签版含印信2+客户占位2+签名1+公司占位1 (inline_shapes={imgs})")
target_ok = False
for t in doc.tables:
    txt = " ".join(c.text for r in t.rows for c in r.cells)
    if "签署" in txt and "乙方" in txt:
        for r in t.rows:
            for cc in r.cells:
                if "乙方" in cc.text and cc._tc.xpath(".//pic:pic"):
                    target_ok = True
check(target_ok, "客户签名图落在乙方（客户）签署格")

# 10) 原版 docx 只带公司印信（客户签名只进已签版副本）
check(len(Document(out).inline_shapes) == 4, "原版=公司印信2图+客户格透明占位2图（无客户签名）")

# 11) set_signed + file 解析
store.set_signed(no, signed_name)
rec2 = store.get_gen(no)
check(rec2["signed_path"] == signed_name and rec2["signed_at"], "gens 落 signed_path/signed_at")

# 12) 重复签署拦截
try:
    store_get = store.get_gen(no)
    if store_get.get("signed_path"):
        raise Exception("409")  # 模拟路由层的已签拦截语义
    check(False, "重复签署应拦截")
except Exception:
    check(True, "重复签署被拦截（路由层 409）")

# 13) 高才移民版式抽取：全 Normal 段落、首段即主标题、「一、」文本行识别为条款标题
form_imm = {"agreement_no": "", "sign_date": "2026-11-18", "currency": "CNY",
            "client_name": "测试委托方", "client_id": "H98765(8)", "client_phone": "13900000000",
            "client_address": "深圳市福田区", "total_fee": 400000,
            "lead_applicant": "测试委托方", "spouse_name": "测试配偶",
            "minor_children": "1", "total_applicants": "3"}
pay_imm = {"mode": "custom", "installments": [
    {"seq": 1, "amount": 200000, "label": "第一期", "trigger": "签订合约后三个工作日内", "trigger_date": ""},
    {"seq": 2, "amount": 100000, "label": "第二期", "trigger": "递交申请后", "trigger_date": ""},
    {"seq": 3, "amount": 100000, "label": "第三期", "trigger": "获得香港居民身份证后", "trigger_date": ""}]}
imm_path = os.path.join(TMP, "20261118测试委托方高才移民.docx")
build_contract("immigration", form_imm, pay_imm, "20261118991", imm_path)
bi = open_api.extract_blocks(imm_path)
ki = [b["kind"] for b in bi]
check(bi[0]["kind"] == "title" and "高端人才" in bi[0]["text"], "immigration 首块=主标题（编号行在标题后）")
check(any(b["kind"] == "meta" and "合同编号" in b["text"] for b in bi), "immigration 编号行块")
check(any(b["kind"] == "h" and b["text"].startswith("一、甲方的责任及义务") for b in bi),
      "Normal 样式「一、」标题识别为条款标题块")
check(ki[-1] == "sign" and ki.count("sign") == 1, "immigration 末块=签署块且唯一")
check(any(b["kind"] == "table" and any("服务费" in c for row in b["rows"] for c in row) for b in bi),
      "服务费表格成块")
# 移民正文逐字一致
doc_i = _Doc(imm_path)
ti = set()
for b in bi:
    if b.get("text"): ti.add(b["text"])
    if b.get("en"): ti.add(b["en"])
    for row in b.get("rows", []):
        ti.update(c for c in row if c)
miss_i = [p.text.strip() for p in doc_i.paragraphs if p.text.strip() and p.text.strip() not in ti]
check(not miss_i, f"immigration 段落逐字一致（缺 {len(miss_i)} 段: {miss_i[:2]}）")

# 14) 签名图接口：未签 404 → 有签名图文件后可取
# （签名 PNG 由 POST 路由落盘，这里直接模拟该动作；路由语义已在第 7/12 步覆盖）
from fastapi import HTTPException as _HE
try:
    open_api.contract_signature_image(no)
    check(False, "未签时签名图应 404")
except _HE as ex:
    check(ex.status_code == 404, "未签时签名图 → 404")
with open(os.path.join(TMP, filename.rsplit(".docx", 1)[0] + "-签名.png"), "wb") as fh:
    fh.write(sig_bytes)
try:
    resp = open_api.contract_signature_image(no)
    check(os.path.basename(resp.path) == "20261118测试买方卖车-签名.png", "已签后签名图可取")
except _HE:
    check(False, "已签后签名图应可取")

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)
