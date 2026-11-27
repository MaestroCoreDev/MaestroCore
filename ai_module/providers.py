"""MaestroCore / ai_module 模型通道层

豆包：已接好，走火山方舟 Ark。
DeepSeek：留好口子，OpenAI 兼容接口，填上 Key 就能用，其他代码一行都不用改。

对外只有一个入口：ask_model(provider, system, user) -> str
"""

import json
import time

import requests

from maestro_config import (
    ARK_BASE_URL,
    ARK_MODEL,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    load_api_key,
    load_deepseek_key,
)

# 想加第三个模型，就在这里登记一下，结构和下面两个一样
PROVIDERS = ("doubao", "deepseek")


def _post_stream(url, headers, body, timeout, retries, provider):
    """流式 POST：逐块读，避免长回答卡在读超时上；返回拼好的纯文本。"""
    body = dict(body, stream=True)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with requests.post(url, headers=headers, json=body, timeout=(10, timeout), stream=True) as resp:
                if resp.status_code != 200:
                    text = resp.text[:300]
                    if resp.status_code in (429, 500, 502, 503, 504):
                        last_err = f"{provider} HTTP {resp.status_code}"
                    else:
                        raise RuntimeError(_friendly_http_error(provider, resp.status_code, text))
                else:
                    parts = []
                    stream_done = False
                    finish_reason = None
                    for raw_line in resp.iter_lines(decode_unicode=False):
                        if not raw_line:
                            continue
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            stream_done = True
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        for choice in chunk.get("choices", []):
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
                                stream_done = True
                            delta = choice.get("delta") or {}
                            if delta.get("content"):
                                parts.append(delta["content"])
                    text = "".join(parts)
                    if not text.strip():
                        last_err = f"{provider} 返回内容为空"
                    elif not stream_done and finish_reason is None:
                        # 连接被中途掐断：这次结果不完整，整段重来
                        last_err = f"{provider} 回答被中断（已收到 {len(text)} 字）"
                    else:
                        if finish_reason == "length":
                            print(f"[提醒] {provider} 输出被 max_tokens 截断，可能不完整")
                        return text
        except requests.RequestException as exc:
            last_err = f"{provider} 网络错误: {exc}"

        if attempt < retries:
            wait = min(4, 1 + attempt)
            print(f"[重试 {attempt}/{retries - 1}] {last_err}，{wait} 秒后再试")
            time.sleep(wait)

    raise RuntimeError(f"{provider} 调用失败：{last_err}")


def ask_doubao(system, user, timeout=90, retries=2):
    headers = {
        "Authorization": f"Bearer {load_api_key()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": ARK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 2400,
        # 关掉思考模式：实测同一句话 23s -> 5s，reasoning_tokens 从 751 降到 0
        "thinking": {"type": "disabled"},
    }
    return _post_stream(
        ARK_BASE_URL + "/chat/completions", headers, body, timeout, retries, "豆包"
    )


def ask_deepseek(system, user, timeout=90, retries=2):
    """DeepSeek 通道（OpenAI 兼容）。

    现在没配 Key，调用会明确告诉你缺什么；
    等你去 platform.deepseek.com 拿到 sk- 开头的 Key，
    写进 ai_module/api_key.txt 里一行 DEEPSEEK_API_KEY=sk-xxx，
    或者设环境变量，这段代码不用动就能跑。
    """
    key = load_deepseek_key()
    if not key:
        raise RuntimeError(
            "DeepSeek 还没配 Key：在 ai_module/api_key.txt 里加一行 "
            "DEEPSEEK_API_KEY=sk-xxx，或设置同名环境变量。"
        )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 2400,
    }
    return _post_stream(
        DEEPSEEK_BASE_URL + "/chat/completions", headers, body, timeout, retries, "DeepSeek"
    )


def _key_from_file(name):
    """从 ai_module/api_key.txt 里读 KEY=VALUE 形式的密钥。"""
    import pathlib

    f = pathlib.Path(__file__).resolve().parent / "api_key.txt"
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith(name):
            return line.split("=", 1)[-1].strip()
    return ""


def _friendly_http_error(provider, status, text):
    """把常见的 HTTP 错误翻译成人话，别让人对着 402/401 干瞪眼。"""
    if status == 401:
        return (f"{provider} 的 API Key 不对或已失效（401）。"
                f"检查 ai_module/api_key.txt 或桌面那个 Key 文件是不是拄错了。")
    if status == 402:
        return (f"{provider} 账户余额不足（402）。去 platform.deepseek.com 充值后重试；"
                f"这次没有产生任何扣费。")
    if status == 403:
        return f"{provider} 没有权限调用该模型（403），检查模型 ID 是否已开通。"
    if status == 429:
        return f"{provider} 触发限流（429），等一会儿再试或降低频率。"
    return f"{provider} 接口返回 {status}: {text}"


def check_provider(provider):
    """只验证 Key 能不能用，不花 token：调一次 /models 列表接口。"""
    provider = (provider or "").strip().lower()
    if provider in ("doubao", "豆包", "ark"):
        key, base, label = load_api_key(), ARK_BASE_URL, "豆包"
    elif provider in ("deepseek", "ds"):
        key, base, label = load_deepseek_key(), DEEPSEEK_BASE_URL, "DeepSeek"
        if not key:
            return {"ok": False, "msg": "没读到 DeepSeek Key（环境变量 / api_key.txt / 桌面文件都没有）"}
    else:
        return {"ok": False, "msg": f"不认识的通道：{provider}"}

    try:
        resp = requests.get(base + "/models",
                            headers={"Authorization": f"Bearer {key}"}, timeout=20)
    except requests.RequestException as exc:
        return {"ok": False, "msg": f"{label} 网络不通：{exc}"}

    if resp.status_code == 200:
        names = []
        try:
            names = [m.get("id", "") for m in resp.json().get("data", [])][:12]
        except ValueError:
            pass
        return {"ok": True, "msg": f"{label} Key 可用（{len(names)} 个模型可见）", "models": names}
    return {"ok": False, "msg": _friendly_http_error(label, resp.status_code, resp.text[:200])}


def ask_model(provider, system, user):
    provider = (provider or "doubao").strip().lower()
    if provider in ("doubao", "豆包", "ark"):
        return ask_doubao(system, user)
    if provider in ("deepseek", "ds"):
        return ask_deepseek(system, user)
    raise RuntimeError(f"不认识的模型通道：{provider}（可选：{', '.join(PROVIDERS)}）")

