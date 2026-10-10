# -*- coding: utf-8 -*-
"""HKD→CNY 汇率提供器：新浪主源 + 腾讯备源，双源失败即报错。

取价顺序：缓存（≤TTL，仅限流）→ 新浪外汇 → 腾讯财经。两源都失败抛 FXError，
由路由层转 502——合同上的第二币种换算宁可失败，也不用写死常量或过期旧值
静默兜底（写死 0.88 曾比市场偏低约 2%，客户拿百度核对必然有异议）。

口径说明：新浪/腾讯都是市场买卖报价，取买卖中间价——与百度 FinScope、XE
等客户常查工具同口径（2026-10-10 实测与百度 FinScope 差 0.01%，与 er-api 差
0.21%）；中行折算价属银行内部口径、比市场中间价高约 0.6%，不采用。
汇率仅供费用表第二币种换算展示，主币种金额不受影响；
换算加成见 money.CONV_MARKUP（静默系数，界面不展示不提醒）。
"""
import datetime
import urllib.request

from api import store

TTL_HOURS = 1   # 缓存只为限流（预览每次编辑都取价，不能裸打外网），不为扛故障——故障就该报错

_SINA_URL = "https://hq.sinajs.cn/list=fx_shkdcny"
_SINA_REFERER = "https://finance.sina.com.cn/"
_TENCENT_URL = "https://qt.gtimg.cn/q=whHKDCNY"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 合理区间校验：源返回异常数据（改版/劫持）一律弃用，等同源失败
_RATE_MIN, _RATE_MAX = 0.5, 1.5


class FXError(Exception):
    """新浪、腾讯两个汇率源均不可用（合同生成/预览中止）。"""


def _http_get(url: str, referer: str | None = None, encoding: str = "utf-8") -> str | None:
    try:
        headers = {"User-Agent": _UA}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode(encoding, errors="ignore")
    except Exception:
        return None


def _rate_from_sina() -> float | None:
    """新浪外汇（国内财经工具报价的事实标准，与百度 FinScope 同源同值）：
    var hq_str_fx_shkdcny="港币人民币,买价,卖价,..."，取买卖中间价。"""
    raw = _http_get(_SINA_URL, referer=_SINA_REFERER, encoding="gbk")
    if not raw or '"' not in raw:
        return None
    try:
        fields = raw.split('"')[1].split(",")
        rate = (float(fields[1]) + float(fields[2])) / 2
    except (IndexError, ValueError):
        return None
    return round(rate, 6) if _RATE_MIN < rate < _RATE_MAX else None


def _rate_from_tencent() -> float | None:
    """腾讯财经：v_whHKDCNY="...~港元人民币~...~现价~..."（~ 分隔，第 4 段为现价）。"""
    raw = _http_get(_TENCENT_URL, encoding="gbk")
    if not raw or "~" not in raw:
        return None
    try:
        rate = float(raw.split("~")[3])
    except (IndexError, ValueError):
        return None
    return round(rate, 6) if _RATE_MIN < rate < _RATE_MAX else None


def _age_hours(fetched_at: str) -> float:
    try:
        t = datetime.datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
        return (datetime.datetime.now() - t).total_seconds() / 3600
    except ValueError:
        return 1e9   # 解析不了的缓存视为过期


def get_hkd_cny() -> dict:
    """返回 {rate, source}，source ∈ sina/tencent；双源失败抛 FXError。
    缓存读写失败静默忽略（缓存只是限流手段，不影响正确性）。"""
    try:
        cached = store.fx_get("HKD", "CNY")
    except Exception:
        cached = None
    if cached and _age_hours(cached["fetched_at"]) < TTL_HOURS:
        return {"rate": cached["rate"], "source": cached["source"]}
    for fetch, name in ((_rate_from_sina, "sina"), (_rate_from_tencent, "tencent")):
        rate = fetch()
        if rate is not None:
            try:
                store.fx_put("HKD", "CNY", rate, name)
            except Exception:
                pass
            return {"rate": rate, "source": name}
    raise FXError("新浪、腾讯汇率源均不可达，请检查服务器网络后重试")
