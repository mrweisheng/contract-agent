# -*- coding: utf-8 -*-
"""HKD→CNY 汇率提供器：官方牌价优先 + SQLite 缓存 + 多级兜底。

取价顺序：缓存（≤TTL）→ 中行牌价页「中行折算价」→ open.er-api.com →
过期缓存旧值 → FALLBACK_RATE 常量。任何网络异常都不抛出——合同生成
不因汇率源中断，降级路径在 source 字段里体现（路由层据此提示）。

汇率仅供费用表第二币种换算展示，主币种金额不受影响；
第二币种的换算加成见 money.CONV_MARKUP（静默系数，界面不展示不提醒）。
"""
import datetime
import json
import re
import urllib.request

from api import store

TTL_HOURS = 12
FALLBACK_RATE = 0.88   # 全部数据源失败时的最终兜底
_BOC_URL = "https://www.boc.cn/sourcedb/whpj/index_1.html"   # 「港币」行所在分页（实测）
_ERAPI_URL = "https://open.er-api.com/v6/latest/HKD"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def _http_get(url: str, timeout: float = 5.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("gb18030", errors="ignore")   # 中行历史页面可能走 GBK 系编码
    except Exception:
        return None


def _rate_from_boc() -> float | None:
    """中行牌价「港币」行的中行折算价（单位：100 港元兑人民币）→ 除以 100。"""
    html = _http_get(_BOC_URL)
    if not html:
        return None
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if cells and cells[0] == "港币" and len(cells) >= 6:
            try:
                v = float(cells[5])
            except ValueError:
                return None
            return round(v / 100, 6) if 0 < v < 200 else None   # 原始值按「每 100 外币」校验
    return None


def _rate_from_erapi() -> float | None:
    raw = _http_get(_ERAPI_URL)
    if not raw:
        return None
    try:
        r = float(json.loads(raw)["rates"]["CNY"])
        return r if 0 < r < 2 else None
    except Exception:
        return None


def _age_hours(fetched_at: str) -> float:
    try:
        t = datetime.datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
        return (datetime.datetime.now() - t).total_seconds() / 3600
    except ValueError:
        return 1e9   # 解析不了的缓存视为过期


def get_hkd_cny() -> dict:
    """返回 {rate, source}；source ∈ cache/boc/er-api/stale/fallback。
    缓存读写失败一律静默降级（合同生成不因本地 DB 问题中断）。"""
    try:
        cached = store.fx_get("HKD", "CNY")
    except Exception:
        cached = None
    if cached and _age_hours(cached["fetched_at"]) < TTL_HOURS:
        return {"rate": cached["rate"], "source": "cache"}
    for fetch, name in ((_rate_from_boc, "boc"), (_rate_from_erapi, "er-api")):
        rate = fetch()
        if rate:
            try:
                store.fx_put("HKD", "CNY", rate, name)
            except Exception:
                pass
            return {"rate": rate, "source": name}
    if cached:
        return {"rate": cached["rate"], "source": "stale"}
    return {"rate": FALLBACK_RATE, "source": "fallback"}
