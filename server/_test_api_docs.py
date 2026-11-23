# -*- coding: utf-8 -*-
"""对外/小程序 API 与文档的一致性检查（离线，不联网）。

规则：凡是 `/api/open/*`、`/api/auth/*`、`/api/users*` 这些对外或小程序可调用的路径，
必须出现在下面两篇接口文档之一；缺一条就 FAIL，防止改了接口忘了同步文档。
工作台内部接口（/api/extract、/api/generate、/api/settlement/* 等）不在检查范围。

用法：cd server && python _test_api_docs.py
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

import main  # noqa: E402

DOC_FILES = ("docs/对外合同查询接口说明.md", "docs/小程序用户登录接口说明.md")
PUBLIC_PREFIXES = ("/api/open/", "/api/auth/", "/api/users")


def norm(s: str) -> str:
    """路径占位符两边都去掉（{no}/{id}/{uid} 写法可以不同）。"""
    return re.sub(r"\{[^}]*\}", "", s)


FAIL = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


docs = {}
for rel in DOC_FILES:
    path = os.path.join(ROOT, rel)
    check(os.path.exists(path), f"文档存在：{rel}")
    if os.path.exists(path):
        docs[rel] = norm(open(path, encoding="utf-8").read())
merged = "\n".join(docs.values())

routes, seen = [], set()
for mod in (main.router, main.open_router, main.users_router, main.my_router):
    for r in mod.routes:
        p = getattr(r, "path", "") or ""
        ms = tuple(sorted(getattr(r, "methods", []) or []))
        if not p.startswith(PUBLIC_PREFIXES):
            continue
        if (ms, p) in seen:
            continue
        seen.add((ms, p))
        routes.append((ms, p))

check(bool(routes), f"收集到对外/小程序路由 {len(routes)} 条")
for ms, p in sorted(routes, key=lambda x: x[1]):
    label = f"{'/'.join(ms):10s} {p}"
    check(norm(p) in merged, label)

print()
print("总体:", "全部通过" if not FAIL else f"存在失败 {len(FAIL)} 项（有接口没写进文档）")
sys.exit(1 if FAIL else 0)
