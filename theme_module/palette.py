"""MaestroCore 主题调色板

一条规矩：所有颜色只从这里出。网页用 CSS 变量、桌面节拍器用同一份 token，
换主题只改这一处，任何一个页面都不许自己写死颜色 —— 否则就会出现“只有首页换了”。

默认配色对齐 PCL2 那种风格：浅灰底、纯白卡片、蓝主色、字色克制，简洁不花。
所有主题都是浅色系，不搞深色反差，免得谱面缩略图、表格看不清。

用法：
    py theme_module\\palette.py                 # 打印当前主题
    py theme_module\\palette.py --css           # 输出 :root 变量块（贴进前端全局 css）
    py theme_module\\palette.py --json          # 给程序读
    py theme_module\\palette.py --list          # 列出所有主题
"""

import json
import pathlib
import sys

sys.dont_write_bytecode = True

MODULE_DIR = pathlib.Path(__file__).resolve().parent
if str(MODULE_DIR.parent / "theme_module") not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

DEFAULT_THEME = "默认"

# 每个主题给齐同一组 token，页面只认 token、不认具体色值
THEMES = {
    "默认": {
        "bg": "#F2F3F5",          # 页面底
        "surface": "#FFFFFF",     # 卡片
        "surface_alt": "#F7F8FA",  # 次级块/输入框
        "text": "#1F2328",
        "text_muted": "#7A8088",
        "accent": "#4B7BE5",      # 主色
        "accent_hover": "#3A68D0",
        "accent_soft": "#EAF1FE",  # 淡底
        "on_accent": "#FFFFFF",
        "border": "#E3E5E9",
        "success": "#3FAE6A",
        "warning": "#E0A54B",
        "danger": "#D9534F",
    },
    "青竹": {
        "bg": "#F2F7F5",
        "surface": "#FFFFFF",
        "surface_alt": "#EFF7F4",
        "text": "#1E2A26",
        "text_muted": "#6F827A",
        "accent": "#2FA37C",
        "accent_hover": "#24876A",
        "accent_soft": "#E3F4EE",
        "on_accent": "#FFFFFF",
        "border": "#DDEBE5",
        "success": "#2FA37C",
        "warning": "#D9A441",
        "danger": "#C9584F",
    },
    "琥珀": {
        "bg": "#FAF6EF",
        "surface": "#FFFFFF",
        "surface_alt": "#FBF3E6",
        "text": "#2B2419",
        "text_muted": "#86765C",
        "accent": "#C98A2E",
        "accent_hover": "#B07824",
        "accent_soft": "#FBEED6",
        "on_accent": "#FFFFFF",
        "border": "#EDE1CD",
        "success": "#5E9A4E",
        "warning": "#C98A2E",
        "danger": "#BF5844",
    },
    "暯紫": {
        "bg": "#F5F3FA",
        "surface": "#FFFFFF",
        "surface_alt": "#F2EFFA",
        "text": "#241F33",
        "text_muted": "#7A728C",
        "accent": "#7A67D8",
        "accent_hover": "#6553C0",
        "accent_soft": "#ECE7FB",
        "on_accent": "#FFFFFF",
        "border": "#E4DFF1",
        "success": "#4C9F7E",
        "warning": "#C58B3C",
        "danger": "#C05563",
    },
    "霎蓝": {
        "bg": "#EFF8FB",
        "surface": "#FFFFFF",
        "surface_alt": "#E8F5FA",
        "text": "#1B2A31",
        "text_muted": "#6A808B",
        "accent": "#0E9BC0",
        "accent_hover": "#0A87A8",
        "accent_soft": "#DDF2F8",
        "on_accent": "#FFFFFF",
        "border": "#D8EDF4",
        "success": "#3E9D75",
        "warning": "#CE9440",
        "danger": "#C25A55",
    },
    "赤陶": {
        "bg": "#FCF5F2",
        "surface": "#FFFFFF",
        "surface_alt": "#FCF0EB",
        "text": "#2E211D",
        "text_muted": "#8B7269",
        "accent": "#C15E43",
        "accent_hover": "#A94F38",
        "accent_soft": "#FAE8E1",
        "on_accent": "#FFFFFF",
        "border": "#F0DDD5",
        "success": "#5C9873",
        "warning": "#C58C3E",
        "danger": "#B94F4A",
    },
}


def _current_name():
    """没解锁就直接用 默认；解锁了再读用户选的主题。"""
    try:
        from redeem import load_state
        state = load_state()
    except Exception:  # noqa: BLE001
        return DEFAULT_THEME
    if not state.get("unlocked"):
        return DEFAULT_THEME
    name = state.get("theme") or DEFAULT_THEME
    return name if name in THEMES else DEFAULT_THEME


def current():
    """返回 (主题名, 颜色字典)。"""
    name = _current_name()
    return name, THEMES[name]


def to_css(name=None):
    """生成 CSS 变量块。前端全局 import 一次，所有页面只写 var(--mc-*) 。"""
    palette = THEMES.get(name or _current_name(), THEMES[DEFAULT_THEME])
    lines = [":root {"]
    for key, value in palette.items():
        lines.append(f"  --mc-{key.replace('_', '-')}: {value};")
    lines.append("}")
    return "\n".join(lines)


def to_tk(name=None):
    """给 Tkinter 用的映射（节拍器窗口可以直接套）。"""
    palette = THEMES.get(name or _current_name(), THEMES[DEFAULT_THEME])
    return {
        "bg": palette["bg"],
        "card": palette["surface"],
        "soft": palette["surface_alt"],
        "fg": palette["text"],
        "muted": palette["text_muted"],
        "accent": palette["accent"],
        "accent_active": palette["accent_hover"],
        "accent_soft": palette["accent_soft"],
        "on_accent": palette["on_accent"],
        "border": palette["border"],
    }


def to_css_all():
    """把全部主题都生成成 CSS：页面只要在 <html data-theme="..."> 上切属性，
    所有用 var(--mc-*) 的地方就一起变，不会出现只有首页换色。"""
    blocks = []
    for name, palette in THEMES.items():
        selector = ":root" if name == DEFAULT_THEME else f'[data-theme="{name}"]'
        lines = [f"{selector} {{"]
        for key, value in palette.items():
            lines.append(f"  --mc-{key.replace('_', '-')}: {value};")
        lines.append("}")
        blocks.append("\n".join(lines))
        # 默认主题再写一份显式选择器，页面把 data-theme 设成「默认」时也认
        if name == DEFAULT_THEME:
            lines = [f'[data-theme="{name}"] {{']
            for key, value in palette.items():
                lines.append(f"  --mc-{key.replace('_', '-')}: {value};")
            lines.append("}")
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def write_css_file(path=None):
    """导出 theme_module/theme.css，前端直接用。"""
    target = pathlib.Path(path) if path else MODULE_DIR / "theme.css"
    target.write_text(to_css_all(), encoding="utf-8")
    return target


def main(argv):
    if "--css" in argv:
        print(to_css_all())
        return 0
    if "--json" in argv:
        name, palette = current()
        print(json.dumps({"theme": name, "palette": palette}, ensure_ascii=False, indent=2))
        return 0
    if "--list" in argv:
        for key in THEMES:
            print(f"{key:8s} 主色 {THEMES[key]['accent']}  底色 {THEMES[key]['bg']}")
        return 0
    name, palette = current()
    print(f"当前主题：{name}")
    for key, value in palette.items():
        print(f"  {key:12s} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

