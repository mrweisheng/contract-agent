# -*- coding: utf-8 -*-
"""服务入口：uvicorn server.main:app"""
import mimetypes
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api import store
from api.routes import router
from api.open_api import router as open_router
from api.users_api import router as users_router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")


def _load_env_file() -> None:
    """把 .env 灌进 os.environ，供 os.getenv 读取（WX_APPID/WX_APP_SECRET/OPEN_API_KEY）。

    之前只有 `python main.py` 直跑时读 .env，且只取 HOST/PORT，导致
    `python -m uvicorn main:app`（start.bat 与 systemd 的实际启动方式）下
    这些键读不到，微信登录恒 503。这里在 import 阶段统一加载；
    进程里已有的真实环境变量优先，不覆盖。
    """
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env_file()

# 自托管字体的 MIME：部分系统 mimetypes 库无 .woff2 映射，显式注册
mimetypes.add_type("font/woff2", ".woff2")

app = FastAPI(title="华星智能合同生成系统")
app.include_router(router)
app.include_router(open_router)
app.include_router(users_router)
store.init()


@app.middleware("http")
async def no_cache_html(request, call_next):
    """首页与前端入口资源不缓存：浏览器每次都拿最新 index.html/app.js，避免改版后被缓存坑。
    workbench.css/alias.css 是主布局与字体别名，同样纳入，避免忘记升 ?v= 时拿到旧样式。"""
    resp = await call_next(request)
    if request.url.path in ("/", "/index.html", "/app.js", "/style.css",
                            "/workbench.css", "/fonts/noto-sans-sc/alias.css"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

# 静态前端（放在 API 路由之后挂载，/api/* 优先匹配）
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    # .env 已由 _load_env_file() 灌入 os.environ，这里直接取
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8300")))
