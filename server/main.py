# -*- coding: utf-8 -*-
"""服务入口：uvicorn server.main:app"""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api import store
from api.routes import router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")

app = FastAPI(title="华星智能合同生成系统")
app.include_router(router)
store.init()

# 静态前端（放在 API 路由之后挂载，/api/* 优先匹配）
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    env = {}
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    uvicorn.run(app, host=env.get("HOST", "0.0.0.0"), port=int(env.get("PORT", "8300")))
