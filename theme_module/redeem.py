"""MaestroCore 主题兑换码（仿 PCL2 那套：只解锁装饰，不阀割功能）

原则：核心功能人人可用，兑换码只换主题色/皮肤，不锁识别、不锁讲解、不锁节拍器。

码制：10 位 Base32（去掉容易看错的 I/L/O/U），格式 XXXX-XXXX-XX
- 前 8 位是随机主体
- 后 2 位是用密钥算出来的校验位，防止随手乱编蒙对

用法：
    生成（只有你自己用，需要 theme_module/_salt.txt）：
        py theme_module\\redeem.py --gen 5
    兑换：
        py theme_module\\redeem.py ABCD-EFGH-23
    查看当前状态：
        py theme_module\\redeem.py --status
"""

import hashlib
import hmac
import json
import os
import pathlib
import secrets
import sys

sys.dont_write_bytecode = True

MODULE_DIR = pathlib.Path(__file__).resolve().parent
APP_ROOT = MODULE_DIR.parent
SALT_FILE = MODULE_DIR / "_salt.txt"
STATE_FILE = MODULE_DIR / "theme_config.json"

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford Base32，无 I L O U
BODY_LEN = 8
CHECK_LEN = 2

THEMES = {
    "PCL 默认": "#4B7BE5",
    "青竹": "#2FA37C",
    "琥珀": "#C98A2E",
    "暮紫": "#7A67D8",
    "霁蓝": "#3C87C9",
    "赤陶": "#C06A4E",
}
DEFAULT_THEME = "PCL 默认"


# ---------------------------------------------------------------- 码的生成与校验
def _salt():
    """读生成密钥；没有就报错，避免在客户端里硬编码。"""
    if not SALT_FILE.exists():
        raise RuntimeError(
            f"缺少生成密钥：{SALT_FILE}（自己写一串随机字符进去，别提交到仓库）"
        )
    return SALT_FILE.read_text(encoding="utf-8").strip()


def _checksum(body, salt):
    digest = hmac.new(salt.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return "".join(ALPHABET[int(digest[i * 2:i * 2 + 2], 16) % 32] for i in range(CHECK_LEN))


def _format(body, check):
    return f"{body[:4]}-{body[4:8]}-{check}"


def generate(count=1):
    """给赞助者发码用。"""
    salt = _salt()
    codes = []
    for _ in range(count):
        body = "".join(secrets.choice(ALPHABET) for _ in range(BODY_LEN))
        codes.append(_format(body, _checksum(body, salt)))
    return codes


def normalize(code):
    """去掉横线/空格，统一大写，顺手把常见的看错字符纠正回来。"""
    if not code:
        return ""
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    fix = {"I": "1", "L": "1", "O": "0", "U": "V"}
    return "".join(fix.get(ch, ch) for ch in raw)


def verify(code):
    """校验码对不对，返回 (是否有效, 提示语)。"""
    raw = normalize(code)
    if len(raw) != BODY_LEN + CHECK_LEN:
        return False, "位数不对：兑换码是 10 位，格式像 ABCD-EFGH-23"
    body, check = raw[:BODY_LEN], raw[BODY_LEN:]
    if any(ch not in ALPHABET for ch in raw):
        return False, "兑换码里有不认识的字符，检查一下是不是拄错了"
    try:
        salt = _salt()
    except RuntimeError:
        return False, "本地缺少生成密钥，无法校验"
    return (_checksum(body, salt) == check), "兑换码有效" if _checksum(body, salt) == check else "兑换码无效"


# ---------------------------------------------------------------- 解锁状态
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"unlocked": False, "code": "", "theme": DEFAULT_THEME}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def unlock(code, theme=None):
    ok, msg = verify(code)
    if not ok:
        return False, msg
    state = load_state()
    state.update({"unlocked": True, "code": _format(*[normalize(code)[:BODY_LEN], normalize(code)[BODY_LEN:]])})
    if theme and theme in THEMES:
        state["theme"] = theme
    save_state(state)
    return True, f"已解锁，当前主题：{state['theme']}"


def current_theme():
    state = load_state()
    if state.get("unlocked"):
        return state.get("theme", DEFAULT_THEME), THEMES.get(state.get("theme"), "#5ad1b1")
    return DEFAULT_THEME, THEMES[DEFAULT_THEME]


# ---------------------------------------------------------------- 命令行
def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("可用主题：" + "、".join(THEMES))
        return 0

    if argv[0] in ("--gen", "-g"):
        try:
            n = int(argv[1]) if len(argv) > 1 else 1
        except ValueError:
            n = 1
        for code in generate(n):
            print(code)
        return 0

    if argv[0] == "--status":
        state = load_state()
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print("主题列表：" + "、".join(THEMES))
        return 0

    code = argv[0]
    theme = argv[1] if len(argv) > 1 else None
    ok, msg = unlock(code, theme)
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
