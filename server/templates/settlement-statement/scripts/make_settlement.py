#!/usr/bin/env python3
"""一条命令出结算单：解析/核算 -> 渲染 PDF -> 可选 PNG。

用法：
    python make_settlement.py --input business.json [--png] [--out-dir DIR]
    python make_settlement.py --text note.txt --png
    python make_settlement.py --spec spec.json --png      # 跳过核算，直接排版
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settlement_compute import build_spec, parse_text  # noqa: E402
from settlement_engine import (  # noqa: E402
    PKG,
    build_output_path,
    plan_layout,
    register_font,
    render_png,
    Renderer,
)


def copy_to_clipboard(png_path: str) -> bool:
    """把 PNG 放进系统剪贴板，用户可直接 ⌘V / Ctrl+V 粘贴到微信。

    macOS 走 osascript，Windows 走 PowerShell 的 Clipboard::SetImage，
    都失败也不影响交付（PDF 和 PNG 都已经在磁盘上了）。
    """
    import platform
    import subprocess

    path = str(Path(png_path).resolve())
    system = platform.system()
    try:
        if system == "Darwin":
            script = ('set the clipboard to (read (POSIX file "%s") as «class PNGf»)' % path)
            subprocess.run(["osascript", "-e", script], check=True,
                           capture_output=True, timeout=10)
            return True
        if system == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$img=[System.Drawing.Image]::FromFile('%s');"
                "[System.Windows.Forms.Clipboard]::SetImage($img);"
                "$img.Dispose()" % path.replace("'", "''")
            )
            subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                           check=True, capture_output=True, timeout=20)
            return True
        if system == "Linux":
            # 有 xclip 时可用；没有就静默跳过
            subprocess.run(["xclip", "-selection", "clipboard", "-t", "image/png", "-i", path],
                           check=True, capture_output=True, timeout=10)
            return True
    except Exception:
        return False
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="收款结算单一键生成")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="业务结构化 JSON")
    group.add_argument("--text", help="按标准段落书写的业务文本")
    group.add_argument("--spec", help="已核算好的 spec JSON，跳过核算")
    parser.add_argument("--png", action="store_true", help="同时导出 220 DPI PNG")
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--clipboard", action="store_true",
                        help="生成后把 PNG 复制到系统剪贴板，可直接粘贴到微信")
    parser.add_argument("--brief", action="store_true", help="只打印一行摘要")
    parser.add_argument("--out-dir", default=None, help="PDF 输出目录，默认 <skill>/output/pdf")
    parser.add_argument("--dry-run", action="store_true", help="只输出 spec，不渲染")
    args = parser.parse_args()

    started = time.time()
    detail = {}
    if args.spec:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    else:
        if args.text:
            raw = sys.stdin.read() if args.text == "-" else Path(args.text).read_text(encoding="utf-8")
            data = parse_text(raw)
        else:
            raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
            data = json.loads(raw)
        spec, detail = build_spec(data)

    if args.dry_run:
        print(json.dumps({"spec": spec, "detail": detail}, ensure_ascii=False, indent=2))
        return 0

    register_font()
    out_dir = Path(args.out_dir) if args.out_dir else PKG / "output" / "pdf"
    pdf_path = build_output_path(spec, out_dir)
    layout = plan_layout(spec)
    renderer = Renderer(spec, layout)
    renderer.render(pdf_path)

    result = {
        "pdf": str(pdf_path),
        "row_height": layout["row_height"],
        "detail": detail,
        "warnings": renderer.warnings + list(detail.get("warnings", [])),
        "elapsed_sec": round(time.time() - started, 2),
    }
    if args.png:
        result["png"] = str(render_png(pdf_path, args.dpi))
        result["elapsed_sec"] = round(time.time() - started, 2)
        if args.clipboard:
            result["clipboard"] = copy_to_clipboard(result["png"])

    if args.brief:
        pay = " / ".join(result["detail"].get("today_pay", {}).values()) or "-"
        warn = "；".join(result["warnings"]) or "无"
        print(f"{Path(result['pdf']).name} | 需付 {pay} | 警告 {warn} | "
              f"{result['elapsed_sec']}s | 剪贴板 {'已复制' if result.get('clipboard') else '无'}")
        # 铁律（淇淇 2026-10-10 要求）：每单出完必须自检——把港币口径的
        # 「合同内（合同等值）＋ 合同外（当日百度汇率 × 1.01）」两部分摊开，
        # 并与「整单按当日汇率重折」的参考值对照，差异来源一目了然。
        chk = result["detail"].get("selfcheck") or {}
        if chk:
            print(f"自检：{chk['expr']}")
            if chk.get("face_mode"):
                print(f"      人民币 ¥{chk['cny_used']:,.2f} → {chk.get('verdict', '')}")
            else:
                print(f"      人民币 ¥{chk['cny_used']:,.2f} ｜ "
                      f"整单按当日汇率重折参考 ${chk['ref_all_today_hkd']:,.2f} "
                      f"→ {chk.get('verdict', '')}")
        print(result["png"] if "png" in result else "")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if any("溢出" in w for w in result["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
