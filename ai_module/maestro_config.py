"""MaestroCore / ai_module 专用配置：模型密钥、地址、模型 ID。

全部收在 ai_module 里，不往项目根目录塞东西。

密钥读取顺序：
1. 环境变量
2. ai_module/api_key.txt（KEY=VALUE 一行一个，别提交到 GitHub）
3. 桌面「火山引擎API Key.txt」（豆包现在放在这里）
"""

import os
import pathlib

AI_DIR = pathlib.Path(__file__).resolve().parent
APP_ROOT = AI_DIR.parent

# ---------- 豆包（火山方舟）----------
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MODEL = os.environ.get("ARK_MODEL", "doubao-seed-2-1-pro-260915")

# ---------- DeepSeek（先留口子，Key 没配也能启动）----------
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
# 账号里实际可见的模型是 deepseek-v4-pro / deepseek-flash
# 实测 deepseek-flash 首字 4.3s、整段 4.8s，v4-pro 要 6s 且思考 token 更多，默认用 flash
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

_DESKTOP_KEY_FILE = pathlib.Path.home() / "Desktop" / "火山引擎API Key.txt"
_DESKTOP_DS_FILE = pathlib.Path.home() / "Desktop" / "DeepSeek  APIKey.txt"


def load_api_key() -> str:
    """豆包 Key：环境变量 -> ai_module/api_key.txt -> 桌面文件。"""
    key = os.environ.get("ARK_API_KEY", "").strip()
    if key:
        return key

    local = AI_DIR / "api_key.txt"
    if local.exists():
        for line in local.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("ARK_API_KEY"):
                return line.split("=", 1)[-1].strip()
            if line.startswith("ark-"):
                return line

    try:
        if _DESKTOP_KEY_FILE.exists():
            for line in _DESKTOP_KEY_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("ark-"):
                    return line
    except OSError:
        pass

    raise RuntimeError(
        "没找到方舟 API Key：请设置环境变量 ARK_API_KEY，"
        f"或在 {AI_DIR / 'api_key.txt'} 里写一行 ARK_API_KEY=ark-xxx"
    )


def load_deepseek_key() -> str:
    """DeepSeek Key：环境变量 -> ai_module/api_key.txt -> 桌面「DeepSeek  APIKey.txt」。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key

    local = AI_DIR / "api_key.txt"
    if local.exists():
        for line in local.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY"):
                return line.split("=", 1)[-1].strip()
            if line.startswith("sk-"):
                return line

    try:
        if _DESKTOP_DS_FILE.exists():
            for line in _DESKTOP_DS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("sk-"):
                    return line
    except OSError:
        pass

    return ""
