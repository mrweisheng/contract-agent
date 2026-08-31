# -*- coding: utf-8 -*-
"""生成 CRLF 换行的 start.bat（cmd 要求 CRLF，LF 会被截断解析）。"""
lines = [
    "@echo off",
    "chcp 65001 >nul",
    "title 华星智能合同生成系统",
    'cd /d "%~dp0server"',
    "",
    "REM 优先使用已安装依赖的 Python；不存在时回退系统 python",
    'set "PY=E:\\Espressif\\tools\\python\\python.exe"',
    'if not exist "%PY%" set "PY=python"',
    "",
    "echo ============================================================",
    "echo   华星智能合同生成系统 启动中...",
    "echo   本机访问:   http://127.0.0.1:8300",
    "echo   局域网访问: http://本机IP:8300",
    "echo   停止服务:   在本窗口按 Ctrl+C",
    "echo ============================================================",
    '"%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8300',
    "pause",
]
content = "\r\n".join(lines) + "\r\n"
path = r"E:\华星客服\简体\contract-agent\start.bat"
with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(content)
raw = open(path, "rb").read()
print("CRLF行数:", raw.count(b"\r\n"), "| 孤立LF:", raw.count(b"\n") - raw.count(b"\r\n"), "| 含BOM:", raw.startswith(b"\xef\xbb\xbf"))
