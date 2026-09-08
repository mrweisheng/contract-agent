@echo off
chcp 65001 >nul
title 华星智能合同生成系统
cd /d "%~dp0server"

REM 优先使用已安装依赖的 Python；不存在时回退系统 python
set "PY=E:\Espressif\tools\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo   华星智能合同生成系统 启动中...
echo   本机访问:   http://127.0.0.1:8300
echo   局域网访问: http://本机IP:8300
echo   停止服务:   在本窗口按 Ctrl+C
echo ============================================================
"%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8300 --reload
pause
