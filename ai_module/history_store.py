"""MaestroCore / ai_module 历史记录归档

每跑完一首曲子，就存一份到项目根目录的 history 文件夹：

    history/
      01_奏鸣曲/
         ai_result.json      # 完整结果（摘要 + AI 方案）
         score.musicxml      # 当时的识别结果，留着以后复查
         meta.json           # 编号、曲名、时间、难度
      02_咏叹调/
      index.json            # 全部记录的清单，给 UI 历史页面读

编号从 01 开始按顺序递增，文件夹名就是「编号_曲名」。
"""

import json
import os
import pathlib
import re
import shutil
from datetime import datetime

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent
HISTORY_DIR = APP_ROOT / "history"
INDEX_FILE = HISTORY_DIR / "index.json"

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe_name(title):
    name = _BAD_CHARS.sub("", (title or "").strip()) or "未命名乐曲"
    return name[:40]


def _load_index(history_dir):
    """读 index.json。兼容早期版本写成的单个对象（dict 而不是 list）。"""
    index_file = pathlib.Path(history_dir) / "index.json"
    if index_file.exists():
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []


def _next_number(records):
    return max((r.get("index", 0) for r in records), default=0) + 1


def save_record(payload, xml_path=None, history_dir=HISTORY_DIR):
    """把一次分析结果归档，返回记录文件夹路径。"""
    history_dir = pathlib.Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)

    summary = payload.get("summary", {})
    ai = payload.get("ai", {})
    title = _safe_name(summary.get("title"))

    records = _load_index(history_dir)
    number = _next_number(records)

    folder_name = f"{number:02d}_{title}"
    folder = history_dir / folder_name
    # 同名曲子的第二条记录，不覆盖，自动加序号后缀
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = history_dir / f"{folder_name}_{suffix}"

    folder.mkdir(parents=True, exist_ok=True)

    (folder / "ai_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if xml_path and os.path.exists(xml_path):
        shutil.copy2(xml_path, folder / "score.musicxml")

    meta = {
        "index": number,
        "title": summary.get("title", "未命名乐曲"),
        "folder": folder.name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": ai.get("level", ""),
        "measures": summary.get("total_measures", 0),
        "notes": summary.get("total_notes", 0),
        "source_file": payload.get("source_file", ""),
        "provider": payload.get("provider", ""),
        "instrument": payload.get("instrument", ""),
    }
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    records.append(meta)
    (history_dir / "index.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload["history_folder"] = folder.name
    payload["history_number"] = number
    (folder / "ai_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


def finalize_score(xml_path, folder):
    """把根目录那份 .musicxml 收进历史记录：确认副本完好后删掉原件。

    返回历史里的路径；出错就保留原件，绝不出现“两边都没有”的情况。
    """
    folder = pathlib.Path(folder)
    dst = folder / "score.musicxml"
    if not xml_path or not os.path.exists(xml_path):
        return dst if dst.exists() else None
    try:
        if not dst.exists():
            shutil.copy2(xml_path, dst)
        if dst.stat().st_size == pathlib.Path(xml_path).stat().st_size:
            os.remove(xml_path)
            return dst
        print(f"[归档] 副本大小不一致，原件保留：{xml_path}")
        return dst
    except OSError as exc:
        print(f"[归档] 收走谱面文件失败（原件保留）：{exc}")
        return dst if dst.exists() else None


def latest_record(history_dir=HISTORY_DIR):
    """给节拍器/前端用：返回最近一次记录的文件夹路径与 meta。"""
    history_dir = pathlib.Path(history_dir)
    records = _load_index(history_dir)
    if not records:
        return None, None
    newest = max(records, key=lambda r: r.get("index", 0))
    folder = history_dir / newest.get("folder", "")
    return (folder if folder.exists() else None), newest


if __name__ == "__main__":
    # 手动补录一次：python ai_module/history_store.py ai_result.json [xml路径]
    import sys

    payload_path = sys.argv[1] if len(sys.argv) > 1 else str(APP_ROOT / "ai_result.json")
    xml = sys.argv[2] if len(sys.argv) > 2 else None
    payload = json.loads(pathlib.Path(payload_path).read_text(encoding="utf-8"))
    folder = save_record(payload, xml)
    print(f"已归档到：{folder}")
