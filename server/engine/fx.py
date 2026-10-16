# -*- coding: utf-8 -*-
"""HKD→CNY 汇率提供器：新浪主源 + 腾讯备源（各带一次重试），近期真实值兜底，
超窗即报错。

取价顺序：缓存（≤30 分钟直接用，不联网）→ 新浪外汇 → 腾讯财经。
刷新失败时，用「≤60 分钟」的真实旧值兜底并标记 source=stale（前端据此提醒
核对）；超过 60 分钟仍未取到才抛 FXError → 路由层转 502。全程**不写死任何
汇率常量**——兜底用的也是真实报价，只是旧一点。

为什么不用写死常量兜底：写死 0.88 曾比市场偏低约 2%，客户拿百度核对必然有
异议。而港币/人民币日内波动极小，30~60 分钟前的真实中间价与现价通常差
<0.1%，所以「近期真实值兜底」安全，「写死常量」不安全。

口径说明：新浪/腾讯都是市场买卖报价，取买卖中间价——与百度 FinScope、XE
等客户常查工具同口径（2026-10-10 实测与百度 FinScope 差 0.01%，与 er-api
差 0.21%）；中行折算价属银行内部口径、比市场中间价高约 0.6%，不采用。
汇率仅供费用表第二币种换算展示，主币种金额不受影响；
换算加成见 money.CONV_MARKUP（静默系数，界面不展示不提醒）。
"""
import datetime
import threading
import time
import urllib.request

from api import store

# 两个时间窗口必须拉开：缓存成功才写，所以「到了该刷新的时刻，手里的值必定
# 已 ≥TTL_MIN」。若 TTL_MIN == STALE_MAX_MIN，刷新失败时旧值正好被兜底规则
# 拒掉 → 兜底形同虚设、直接报错。
TTL_MIN = 30          # fresh 复用窗口：30 分钟内的值直接用，不联网（纯限流，
                      # 预览每次编辑都取价，不能裸打外网）
STALE_MAX_MIN = 60    # 兜底上限：刷新失败时，旧值最多旧到 60 分钟还敢用；超过
                      # 则彻底报错（必须 > TTL_MIN，见上）

_TIMEOUT = 3.0        # 单源单次超时（源是几字节的小 GET，3 秒足够）
_TRIES = 2            # 每个源尝试次数（含首次）：主备各一轮 = 主备重试
_RETRY_GAP = 0.4      # 轮与轮之间的间隔
_TOTAL_BUDGET = 7.0   # 一次刷新的总预算上限（封顶最坏耗时，不拖垮预览）
_BREAKER_SEC = 90     # 熔断：刷新失败后 90 秒内不再重试，避免每个按键都撞满超时

_SINA_URL = "https://hq.sinajs.cn/list=fx_shkdcny"
_SINA_REFERER = "https://finance.sina.com.cn/"
_TENCENT_URL = "https://qt.gtimg.cn/q=whHKDCNY"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 合理区间校验：源返回异常数据（改版/劫持）一律弃用，等同源失败
_RATE_MIN, _RATE_MAX = 0.5, 1.5

_refresh_lock = threading.Lock()   # 单飞：并发预览只放一个请求出去取价
_last_fail = None                  # 熔断时间戳（time.monotonic）；None=从未失败


class FXError(Exception):
    """新浪、腾讯两个汇率源均不可用，且无窗口内可用旧值（合同生成/预览中止）。"""


def _http_get(url: str, referer: str | None = None, encoding: str = "utf-8",
              timeout: float = _TIMEOUT) -> str | None:
    try:
        headers = {"User-Agent": _UA}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode(encoding, errors="ignore")
    except Exception:
        return None


def _rate_from_sina(timeout: float = _TIMEOUT) -> float | None:
    """新浪外汇（国内财经工具报价的事实标准，与百度 FinScope 同源同值）：
    var hq_str_fx_shkdcny="港币人民币,买价,卖价,..."，取买卖中间价。"""
    raw = _http_get(_SINA_URL, referer=_SINA_REFERER, encoding="gbk", timeout=timeout)
    if not raw or '"' not in raw:
        return None
    try:
        fields = raw.split('"')[1].split(",")
        rate = (float(fields[1]) + float(fields[2])) / 2
    except (IndexError, ValueError):
        return None
    return round(rate, 6) if _RATE_MIN < rate < _RATE_MAX else None


def _rate_from_tencent(timeout: float = _TIMEOUT) -> float | None:
    """腾讯财经：v_whHKDCNY="...~港元人民币~...~现价~..."（~ 分隔，第 4 段为现价）。"""
    raw = _http_get(_TENCENT_URL, encoding="gbk", timeout=timeout)
    if not raw or "~" not in raw:
        return None
    try:
        rate = float(raw.split("~")[3])
    except (IndexError, ValueError):
        return None
    return round(rate, 6) if _RATE_MIN < rate < _RATE_MAX else None


_SOURCES = ((_rate_from_sina, "sina"), (_rate_from_tencent, "tencent"))


def _refresh() -> tuple[float, str] | None:
    """主备两源各带一次重试取价；总耗时受 _TOTAL_BUDGET 封顶。成功返回
    (rate, name)，全失败返回 None。"""
    deadline = time.monotonic() + _TOTAL_BUDGET
    for attempt in range(_TRIES):
        for fetch, name in _SOURCES:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            rate = fetch(min(_TIMEOUT, left))   # 越接近预算上限，单次超时越短
            if rate is not None:
                return rate, name
        if attempt < _TRIES - 1:                # 轮间隔；预算不够就不等了
            left = deadline - time.monotonic()
            if left > 0:
                time.sleep(min(_RETRY_GAP, left))
    return None


def _age_min(fetched_at: str) -> float:
    try:
        t = datetime.datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
        return (datetime.datetime.now() - t).total_seconds() / 60
    except ValueError:
        return 1e9   # 解析不了的缓存视为过期


def _cached():
    try:
        return store.fx_get("HKD", "CNY")
    except Exception:
        return None


def get_hkd_cny() -> dict:
    """返回 {rate, source}，source ∈ sina/tencent/stale；无窗口内可用值抛 FXError。
    缓存读写失败静默忽略（缓存只是限流/兜底手段，不影响取价正确性）。"""
    global _last_fail
    cached = _cached()
    if cached and _age_min(cached["fetched_at"]) < TTL_MIN:
        return {"rate": cached["rate"], "source": cached["source"]}

    with _refresh_lock:
        # 双检：等锁期间可能有别的请求刚刷新成功
        cached = _cached()
        if cached and _age_min(cached["fetched_at"]) < TTL_MIN:
            return {"rate": cached["rate"], "source": cached["source"]}

        if _last_fail is None or time.monotonic() - _last_fail >= _BREAKER_SEC:
            got = _refresh()
            if got is not None:
                rate, name = got
                try:
                    store.fx_put("HKD", "CNY", rate, name)
                except Exception:
                    pass
                _last_fail = None
                return {"rate": rate, "source": name}
            _last_fail = time.monotonic()   # 熔断：90 秒内不再撞超时

    # 刷新失败或被熔断 → 仍未过期太久的真实旧值兜底（前端标记 stale 提醒核对）
    if cached and _age_min(cached["fetched_at"]) < STALE_MAX_MIN:
        return {"rate": cached["rate"], "source": "stale"}
    raise FXError("新浪、腾讯汇率源均不可达，且无 60 分钟内的可用汇率，请检查服务器网络后重试")
