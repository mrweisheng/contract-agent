# -*- coding: utf-8 -*-
"""docx→PDF 交付链：LibreOffice headless 转换 + 骑缝章叠加（下载格式加固）。

转换：subprocess 调 soffice（服务器 apt 装 libreoffice-writer 即有），每次转换用
独立临时 profile（soffice 用户配置互斥，进程级锁串行化，压住并发内存峰值），
超时强杀。soffice 未装或转换失败抛 PdfError，路由层转 503 提示改下 Word 版。

骑缝章：seal.png 按 alpha 裁边后纵切 N 条（N=PDF 页数），第 i 页右缘贴第 i 条、
垂直居中——各页切片拼起是完整章，换页/抽页即穿帮。reportlab 画叠加层 + pypdf
逐页 merge（切片压平白底——reportlab 不做 alpha 合成；贴位在右页边距，白底不出界）。
印信缺失（开发/测试环境）不盖章照常出 PDF。

缓存：PDF 与 docx 同目录同名（合同落盘后不可变，转换一次永久复用，重复下载零开销）。
"""
import io
import os
import shutil
import subprocess
import tempfile
import threading

from PIL import Image

SOFFICE_TIMEOUT = 60   # 单次转换超时（秒），超时杀进程报 PdfError

# Windows 安装版不进 PATH，常见落点兜底查找（Linux 上 PATH 命中，用不到这些）
_SOFFICE_FALLBACKS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]

_lock = threading.Lock()   # soffice 同 profile 不能并发；串行化同时压住内存峰值


class PdfError(RuntimeError):
    """docx→PDF 转换或盖章失败（路由层转 503，前端提示走 Word 下载）。"""


def _find_soffice() -> str | None:
    exe = shutil.which("soffice")
    if exe:
        return exe
    for p in _SOFFICE_FALLBACKS:
        if os.path.exists(p):
            return p
    return None


def soffice_available() -> bool:
    return _find_soffice() is not None


def _seals_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "seals")


def _file_uri(path: str) -> str:
    """soffice -env:UserInstallation 需要的 file URI（跨 Windows/Linux）。"""
    path = path.replace("\\", "/")
    return "file://" + (path if path.startswith("/") else "/" + path)


def run_soffice(docx_path: str, out_dir: str):
    """soffice headless 把 docx 转进 out_dir（输出名=docx 主名.pdf）。"""
    exe = _find_soffice()
    if not exe:
        raise PdfError("本机/服务器未安装 LibreOffice（soffice），无法生成 PDF")
    profile = tempfile.mkdtemp(prefix="lo_profile_")
    cmd = [exe, "--headless", "--norestore", f"-env:UserInstallation={_file_uri(profile)}",
           "--convert-to", "pdf", "--outdir", out_dir, os.path.abspath(docx_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=SOFFICE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise PdfError(f"PDF 转换超时（>{SOFFICE_TIMEOUT}s），请稍后重试或先下载 Word 版")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["无输出"]
        raise PdfError(f"PDF 转换失败：{tail[0][:200]}")


def _seal_strips(seal_path: str, n: int) -> list:
    """印章图按 alpha 内容界裁边后纵切 n 条（从左到右），切片压平到白底返回。

    返回 [(png 字节, 宽英寸, 高英寸), ...]；总宽=印章显示宽 SEAL_W，条宽=SEAL_W/n，
    高按裁边后纵横比换算——各页切片拼合即完整章。压平原因：reportlab drawImage
    不做 alpha 合成（RGBA 直绘成不透明深色块）；切片贴在右页边距内，白底衬不出界。"""
    from engine import seal as seal_mod
    im = Image.open(seal_path).convert("RGBA")
    bbox = im.getchannel("A").getbbox()   # 兼容服务器上未裁透明边的旧版 seal.png
    if bbox:
        im = im.crop(bbox)
    total_w = seal_mod.SEAL_W.inches
    h_in = total_w * im.height / im.width
    w_in = total_w / n
    base_px = im.width // n
    strips = []
    for i in range(n):
        x0 = i * base_px
        x1 = im.width if i == n - 1 else x0 + base_px   # 余数像素归末条（<n px，忽略）
        part = im.crop((x0, 0, x1, im.height))
        flat = Image.new("RGB", part.size, (255, 255, 255))
        flat.paste(part, (0, 0), part)
        buf = io.BytesIO()
        flat.save(buf, "PNG")
        strips.append((buf.getvalue(), w_in, h_in))
    return strips


def stamp_cross_page_seal(pdf_path: str) -> bool:
    """给 PDF 盖骑缝章：第 i 页（共 N 页）右缘贴章的第 i 条纵切片，垂直居中。

    印信文件缺失 → False（PDF 照常出，不盖章）；成功原地覆写 → True。"""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    seal_path = os.path.join(_seals_dir(), "seal.png")
    if not os.path.exists(seal_path):
        return False
    reader = PdfReader(pdf_path)
    n = len(reader.pages)
    if n < 1:
        return False
    strips = _seal_strips(seal_path, n)

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf)
    for i, page in enumerate(reader.pages):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        c.setPageSize((w, h))
        png, sw_in, sh_in = strips[i]
        sw, sh = sw_in * 72, sh_in * 72   # 英寸 → reportlab 点（1in=72pt）
        c.drawImage(ImageReader(io.BytesIO(png)), w - sw, (h - sh) / 2, width=sw, height=sh)
        c.showPage()
    c.save()

    overlay = PdfReader(io.BytesIO(buf.getvalue()))
    writer = PdfWriter()
    for page in reader.pages:          # pypdf≥7：页先挂 writer 才允许 merge
        writer.add_page(page)
    for page, op in zip(writer.pages, overlay.pages):
        page.merge_page(op)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return True


def _cached_ok(pdf_path: str, docx_path: str) -> bool:
    return os.path.exists(pdf_path) and \
        os.path.getmtime(pdf_path) >= os.path.getmtime(docx_path) - 1


def ensure_pdf(docx_path: str) -> str:
    """docx 对应的骑缝章 PDF（同目录同名 .pdf 缓存），返回 PDF 路径。

    缓存以 docx mtime 为界（合同落盘后不可变，实际即永久复用）；失败抛 PdfError。
    全过程 print 日志（uvicorn 控制台可见），任何未预期异常也转 PdfError——
    路由层只需接 PdfError 一种。进程内串行：单 uvicorn worker 下锁即全局，
    防并发重复转换与 soffice 冲突。"""
    docx_path = os.path.abspath(docx_path)
    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
    if _cached_ok(pdf_path, docx_path):
        return pdf_path
    with _lock:
        if _cached_ok(pdf_path, docx_path):   # 双检：等锁期间并发请求已转好
            return pdf_path
        import time
        t0 = time.time()
        name = os.path.basename(docx_path)
        print(f"[pdf] 转换开始: {name}", flush=True)
        workdir = tempfile.mkdtemp(prefix="pdf_build_")
        try:
            run_soffice(docx_path, workdir)
            raw = os.path.join(workdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
            if not os.path.exists(raw):
                raise PdfError("PDF 转换失败：soffice 未产出文件")
            stamped = stamp_cross_page_seal(raw)
            # 跨卷安全落盘：临时目录常在 C 盘、OUT_DIR 可能在 D 盘，os.replace 不能跨盘符——
            # 先拷到目标同目录（同卷），再原子改名
            building = pdf_path + ".building"
            try:
                shutil.copyfile(raw, building)
                os.replace(building, pdf_path)
            except OSError:
                if os.path.exists(building):
                    os.remove(building)
                raise
            print(f"[pdf] 完成: {os.path.basename(pdf_path)} "
                  f"({os.path.getsize(pdf_path)} bytes, {time.time() - t0:.1f}s, "
                  f"骑缝章{'√' if stamped else '无印信跳过'})", flush=True)
            return pdf_path
        except PdfError as ex:
            print(f"[pdf] 失败: {name} — {ex}", flush=True)
            raise
        except Exception as ex:
            print(f"[pdf] 失败: {name} — 未预期错误 {type(ex).__name__}: {ex}", flush=True)
            raise PdfError(f"{type(ex).__name__}: {ex}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
