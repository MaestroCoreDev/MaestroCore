"""MaestroCore / ai_module 副产物仓库（temp_debug）

所有「只是为了看一眼」而生成的东西，统一扔到项目根目录的 temp_debug，
并且按一次运行一个文件夹分好，不再散落在根目录：

    temp_debug/
      20261124_101530_奏鸣曲/
        tempo/       速度标记的裁剪放大图 + OCR 原文
        header/      标题/作者区的裁剪图
        preview/     矫正后的整页图、homr 中间预览
        notes.json   这一次跑了什么、识别出什么（给排查用）

用法（其它模块调用）：
    import debug_store
    debug_store.begin_session("奏鸣曲")
    debug_store.capture("bpm_放大5倍", crop_img, sub="tempo")
    debug_store.note("tempo_ocr", tempos)
    debug_store.end_session()

任何一步出错都不抛异常，绝不因为存副产物把主流程搞挂。
"""

import json
import os
import pathlib
import shutil
from datetime import datetime

import sys
sys.dont_write_bytecode = True

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEBUG_DIR = APP_ROOT / "temp_debug"

_session = None          # 当前会话文件夹
_session_notes = {}
_MAX_KEEP = 12           # 最多留最近 12 次，更早的自动清掉


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe(text):
    bad = '\\/:*?"<>|\r\n\t '
    return "".join(c for c in (text or "") if c not in bad)[:30]


def begin_session(tag=""):
    """开一次新的副产物会话，返回文件夹路径（失败返回 None）。

    如果流水线已经开过会话，这里直接复用，避免一次运行建两三个文件夹。
    """
    global _session, _session_notes
    if _session is not None:
        return _session
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{_stamp()}_{_safe(tag)}" if tag else _stamp()
        folder = DEBUG_DIR / name
        # 同一秒内二次运行
        n = 2
        while folder.exists():
            folder = DEBUG_DIR / f"{name}_{n}"
            n += 1
        for sub in ("tempo", "header", "preview"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        _session = folder
        _session_notes = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tag": tag or "",
            "items": {},
        }
        print(f"[副产物] 本次调试素材收进：temp_debug/{folder.name}")
        return folder
    except Exception as exc:  # noqa: BLE001
        print(f"[副产物] 调试目录创建失败（忽略）：{exc}")
        _session, _session_notes = None, {}
        return None


def capture(name, image, sub="misc"):
    """把一张 PIL 图像或现成文件存进当前会话，返回保存路径。"""
    try:
        if _session is None:
            return None
        sub_dir = _session / sub
        sub_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(image, (str, os.PathLike)):
            src = pathlib.Path(image)
            dst = sub_dir / f"{_safe(name) or src.stem}{src.suffix}"
            shutil.copy2(src, dst)
        else:
            dst = sub_dir / f"{_safe(name) or 'capture'}.png"
            image.save(dst)
        return dst
    except Exception as exc:  # noqa: BLE001
        print(f"[副产物] 保存 {name} 失败（忽略）：{exc}")
        return None


def note(key, value):
    """往 notes.json 里记一条，方便以后回看这次到底认出了什么。"""
    if _session is None:
        return
    _session_notes["items"][key] = value


def path():
    return _session


def end_session():
    """写 notes.json 并清理过旧的会话。"""
    global _session, _session_notes
    try:
        if _session is not None:
            (_session / "notes.json").write_text(
                json.dumps(_session_notes, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[副产物] notes.json 写入失败（忽略）：{exc}")
    finally:
        _session, _session_notes = None, {}
    prune()


def prune(keep=_MAX_KEEP):
    """只保留最近 keep 个会话文件夹，其余删掉。"""
    try:
        if not DEBUG_DIR.exists():
            return
        folders = sorted(
            [p for p in DEBUG_DIR.iterdir() if p.is_dir()],
            key=lambda p: p.name, reverse=True,
        )
        for old in folders[keep:]:
            shutil.rmtree(old, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    # 手动看现状 / 手动清理：py ai_module\\debug_store.py [--prune]
    import sys

    if "--prune" in sys.argv:
        prune()
    folders = sorted(DEBUG_DIR.iterdir()) if DEBUG_DIR.exists() else []
    total = sum(f.stat().st_size for f in DEBUG_DIR.rglob("*") if f.is_file()) if DEBUG_DIR.exists() else 0
    print(f"temp_debug：{len(folders)} 个会话，共 {total / 1024 / 1024:.1f} MB")
    for f in folders[-12:]:
        print("  " + f.name)
