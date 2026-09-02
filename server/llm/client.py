# -*- coding: utf-8 -*-
"""硅基流动（OpenAI 兼容）LLM 客户端：JSON 输出约束 + 自动重试。"""
import json
import os
import re
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env() -> dict:
    cfg = {}
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


_ENV = _load_env()
API_KEY = _ENV.get("SILICONFLOW_API_KEY", "")
BASE_URL = _ENV.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
MODEL = _ENV.get("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")


class LLMError(Exception):
    pass


_SESSION = requests.Session()  # 复用连接，省去每次调用的 TLS 握手


def chat_json(messages: list, max_tokens: int = 2000, retries: int = 3,
              temperature: float = 0.1, thinking: bool = False, timeout: int = 30) -> dict:
    """调用 LLM 并解析为 JSON；失败自动重试（附纠错提示）。
    thinking=False 关闭混合推理模型的思考阶段（交互场景提速 5~8 倍）；
    需要深度推理的调用（如语义复核）传 thinking=True 并放宽 timeout。
    """
    if not API_KEY:
        raise LLMError("未配置 SILICONFLOW_API_KEY（检查 .env）")
    url = f"{BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    msgs = list(messages)
    last_err = None
    last_content = None    # 上次模型真实输出（重试注入用）
    content = None         # 本轮模型原始输出；必须在循环外初始化，否则 HTTP 层异常时
                           # except 分支读它会抛 UnboundLocalError（不属于任何已知异常，会直接冒泡）
    use_json_mode = True   # 强制 JSON 输出，避免围栏/解释文字导致的解析重试
    use_fast_mode = not thinking
    for attempt in range(retries):
        payload = {
            "model": MODEL,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if use_fast_mode:
            payload["enable_thinking"] = False
        t0 = time.time()
        print(f"[LLM] 第{attempt + 1}次调用开始（{MODEL}，输出上限{max_tokens}）...", flush=True)
        try:
            resp = _SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code != 200:
                raise LLMError(f"API {resp.status_code}: {resp.text[:200]}")
            content = resp.json()["choices"][0]["message"]["content"]
            data = _parse_json(content)
            if isinstance(data, dict):
                print(f"[LLM] 调用成功，耗时 {time.time() - t0:.1f} 秒", flush=True)
                return data
            raise LLMError("返回不是 JSON 对象")
        except (LLMError, KeyError, json.JSONDecodeError, requests.RequestException,
                AttributeError, TypeError) as ex:
            last_err = ex
            err = str(ex)
            if err.startswith("API 400") and (use_fast_mode or use_json_mode):
                # 模型不支持某个可选参数：逐个撤掉（先 enable_thinking 后 response_format）立即重试
                if use_fast_mode:
                    use_fast_mode = False
                else:
                    use_json_mode = False
                print("[LLM] 模型不支持部分可选参数，已降级重试", flush=True)
                continue
            if isinstance(content, str):
                last_content = content   # 留住 LLM 上次的真实输出（无论是否解析失败），下次重试用
            content_len = f"{len(last_content)} 字符" if isinstance(last_content, str) else "无内容"
            print(f"[LLM] 第{attempt + 1}次失败（{time.time() - t0:.1f} 秒，模型输出 {content_len}）："
                  f"{str(ex)[:150]}", flush=True)
            # 重试时附上失败输出，要求模型纠正
            # 喂模型上次真实输出（比异常字符串更能精准定位），只在没拿到 content 时退化用 last_err 字符串
            msgs = list(messages) + [
                {"role": "assistant", "content": (last_content or str(last_err))[:1500]},
                {"role": "user", "content": "上面的输出无法解析为 JSON。请重新输出，只输出一个合法的 JSON 对象，不要任何解释、不要代码块标记。"},
            ]
            time.sleep(1)
    raise LLMError(f"LLM 调用失败（重试{retries}次）：{last_err}")


def _parse_json(content: str):
    """解析 LLM 返回的 JSON 对象。

    优先级：
    1) `json.JSONDecoder().raw_decode` 从首个 `{` 起状态机扫描，遇到第一个完整对象就停。
       比 find/rfind 更稳：后者会一直截到「最后一个」`}`，在 JSON 后跟了含 `}` 的解释文字、
       或一次吐出多个 JSON 对象时会把多余内容一起截进来而解析失败。
       注：字符串内部的 `}` 不会让 find/rfind 出错（它在结尾 `}` 之前），别按这个理由改代码。
    2) 围栏兜底（```json ... ```）。
    3) 终极截取（首/末大括号），仍失败则抛 JSONDecodeError 给上层重试。
    """
    s = content.find("{")
    if s >= 0:
        try:
            data, _ = json.JSONDecoder().raw_decode(content, s)
            return data
        except json.JSONDecodeError:
            pass
    stripped = content.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.S)
    if m:
        content = m.group(1)
    else:
        content = stripped
    s, e = content.find("{"), content.rfind("}")
    if s >= 0 and e > s:
        content = content[s:e + 1]
    return json.loads(content)
