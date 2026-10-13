#!/usr/bin/env python3
"""一键打开「收款结算单录入看板」。

做的事（SKILL.md 里要求人工做的三步，这里一次性做完）：
  1. 把 templates/录入看板.html（HTML 片段）包成完整 HTML 文档；
  2. 可选：用一份历史 business.json 预填所有字段（--prefill）；
  3. 起一个本地 HTTP 服务，打印带时间戳的强刷地址（避免浏览器复用上一单缓存）。

用法：
    python open_board.py                          # 空白看板
    python open_board.py --prefill data/statements/张三_收尾款_20261001.json
    python open_board.py --no-serve               # 只生成文件，自己起服务
    python open_board.py --port 8790
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_prefilled_board import PRELOAD, TEMPLATE  # noqa: E402

PKG = Path(__file__).resolve().parent.parent
BOARD_DIR = PKG / ".board"


def free_port(preferred: int = 0) -> int:
    if preferred:
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_html(title: str, prefill: str | None) -> str:
    body = TEMPLATE.read_text(encoding="utf-8")
    payload = ""
    if prefill:
        data = json.loads(Path(prefill).read_text(encoding="utf-8"))
        payload = PRELOAD.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n"
        "<style>html,body{margin:0;padding:0;background:#f2f5f9;}</style>\n</head>\n<body>\n"
        + body + "\n" + payload + "\n</body>\n</html>\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="打开收款结算单录入看板")
    ap.add_argument("--prefill", help="历史 business.json，用于回填字段")
    ap.add_argument("--title", default="收款结算单录入看板")
    ap.add_argument("--port", type=int, default=0, help="指定端口，默认自动找空闲端口")
    ap.add_argument("--no-serve", action="store_true", help="只生成 HTML，不起服务")
    args = ap.parse_args()

    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    html_path = BOARD_DIR / "index.html"
    html_path.write_text(build_html(args.title, args.prefill), encoding="utf-8")

    if args.no_serve:
        print(str(html_path))
        return 0

    port = free_port(args.port)
    # start_new_session 在 Windows 上不支持，改挂 DETACHED_PROCESS
    popen_kwargs: dict = {"cwd": str(BOARD_DIR),
                          "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        **popen_kwargs,
    )
    time.sleep(0.6)
    print(f"http://127.0.0.1:{port}/index.html?v={int(time.time())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
