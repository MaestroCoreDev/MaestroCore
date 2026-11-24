"""MaestroCore / ai_module 速度标记识别

homr 只认音符、不认文字，谱面印的 Largo ♩=96 / Allegro ♩=120 它完全看不到。
这里用 OCR 把这种标记找出来，并换算成「第几小节起 = 多少 BPM」。

做法：
1. 全页 OCR，抓速度术语（Largo/Allegro/Andante…）和紧跟着的数字；
2. 术语附近没读清数字，就把那一小块裁出来放大 5 倍再 OCR 一次；
3. 用文字框的坐标去对 homr 记下的每个小节首音符坐标，落到具体小节号。
"""

import re
from pathlib import Path

from PIL import Image

TEMPO_WORDS = {
    "grave": 44,
    "largo": 50,
    "larghetto": 60,
    "lento": 54,
    "adagio": 66,
    "andante": 84,
    "andantino": 92,
    "moderato": 108,
    "allegretto": 112,
    "allegro": 120,
    "vivace": 152,
    "presto": 180,
    "prestissimo": 200,
}

_WORD_RE = re.compile("|".join(sorted(TEMPO_WORDS, key=len, reverse=True)))
_BPM_RE = re.compile(r"[=＝:：]\s*(\d{2,3})")
_NUM_RE = re.compile(r"\d{2,3}")

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _ocr(path):
    result, _ = _get_engine()(str(path))
    items = []
    for box, text, score in (result or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append({
            "text": text.strip(),
            "score": float(score),
            "x0": float(min(xs)), "x1": float(max(xs)),
            "y0": float(min(ys)), "y1": float(max(ys)),
        })
    return items


def _ocr_digits_near(image, item, label="", tmp_dir=None):
    """在术语右侧裁一小块放大后 OCR，专门找 ♩=120 这种数字。

    放大图直接存进 temp_debug 本次会话的 tempo/ 里，方便以后核对
    “到底是谱上写的 96，还是模型瞎猜的 96”。
    """
    import tempfile

    y0 = max(0, int(item["y0"]) - 8)
    y1 = min(image.height, int(item["y1"]) + 8)
    x0 = int(item["x1"])
    x1 = min(image.width, x0 + 160)
    if x1 - x0 < 20 or y1 - y0 < 8:
        return None

    crop = image.crop((x0, y0, x1, y1))
    crop = crop.resize((crop.width * 5, crop.height * 5), Image.LANCZOS)

    saved = None
    try:
        import debug_store
        saved = debug_store.capture(f"{label or 'bpm'}放大5倍", crop, sub="tempo")
    except Exception:  # noqa: BLE001
        saved = None
    if saved is None:
        saved = Path(tempfile.gettempdir()) / "maestro_tempo_crop.png"
        crop.save(saved)

    for box, text, score in (_get_engine()(str(saved))[0] or []):
        for num in _NUM_RE.findall(text):
            value = int(num)
            if 30 <= value <= 260:
                return value
    return None


def _system_and_measure(item, measures):
    """把文字框落到具体小节：先找同一谱行，再找该行里最后一个在它左边的小节。"""
    if not measures:
        return 1
    cy = (item["y0"] + item["y1"]) / 2
    cx = (item["x0"] + item["x1"]) / 2

    nearest = min(measures, key=lambda m: abs(cy - m["imgpos"][1]))
    same_system = [m for m in measures if abs(m["imgpos"][1] - nearest["imgpos"][1]) < 30]
    same_system.sort(key=lambda m: m["imgpos"][0])

    chosen = same_system[0]["measure"]
    for m in same_system:
        if m["imgpos"][0] <= cx:
            chosen = m["measure"]
    return chosen


def page_text(image_path, max_items=14):
    """抓谱面页眉/标题区的文字，给大模型做曲目推测用。

    只保留标题区（顶部 35%）和看着像文字的条目，过滤掉孤零零的数字/噪点。
    """
    image = Image.open(image_path)
    height = image.height
    items = []
    for item in _ocr(image_path):
        text = item["text"].strip()
        if len(text) < 2:
            continue
        if item["y0"] > height * 0.35 and not re.search(
                r"[曲子调编作曲作改编OpA-Za-z]{2,}", text):
            continue
        items.append({"text": text, "y": int(item["y0"])})
    items.sort(key=lambda x: x["y"])

    try:  # 页眉那一块单独裁出来存 temp_debug/header，方便核对曲名/作者
        import debug_store
        debug_store.capture("页眉区", image.crop((0, 0, image.width, int(height * 0.35))), sub="header")
        debug_store.note("header_text", items[:max_items])
    except Exception:  # noqa: BLE001
        pass

    return items[:max_items]


def detect_tempos(image_path, summary, debug=False):
    """返回 [{'measure':1,'bpm':96,'text':'Largo=96','source':'ocr'}, ...]。"""
    image = Image.open(image_path).convert("RGB")

    measures = [m for m in summary.get("measures", []) if m.get("imgpos")]
    items = _ocr(image_path)

    found = []
    for item in items:
        text = item["text"]
        low = text.lower()

        word = _WORD_RE.search(low)
        word = word.group(0) if word else None

        bpm = None
        origin = ""
        bm = _BPM_RE.search(text)
        if bm:
            value = int(bm.group(1))
            if 30 <= value <= 260:
                bpm = value
                origin = "谱面数字"

        if bpm is None and word:
            value = _ocr_digits_near(image, item, label=word)
            if value:
                bpm = value
                origin = "放大后读到数字"

        if bpm is None and word:
            bpm = TEMPO_WORDS[word]
            origin = f"按「{word}」惯例推算"

        if bpm is None:
            continue

        measure = _system_and_measure(item, measures)
        found.append({
            "measure": measure,
            "bpm": float(bpm),
            "text": text,
            "source": origin,
        })
        if debug:
            print(f"    OCR: {text} -> 第 {measure} 小节 {bpm} BPM（{origin}）")

    try:  # 把全页 OCR 原始结果也存一份，方便核对是 OCR 错还是模型错
        import debug_store
        debug_store.note("tempo_ocr_raw", items)
        debug_store.note("tempo_found", found)
    except Exception:  # noqa: BLE001
        pass

    # 同一小节只要第一个，按小节排序
    dedup = {}
    for f in sorted(found, key=lambda x: x["measure"]):
        dedup.setdefault(f["measure"], f)
    tempos = list(dedup.values())

    if not tempos:
        return []

    # 全曲开头必须有速度，否则前面那段没有基准
    if tempos[0]["measure"] != 1:
        tempos.insert(0, {"measure": 1, "bpm": tempos[0]["bpm"], "text": "（开头沿用）", "source": "沿用"})

    return tempos


def tempos_to_spec(tempos):
    """转成 --tempo 的写法，方便人工核对或保存。"""
    return ",".join(f"{int(t['measure'])}:{int(t['bpm'])}" for t in tempos)


if __name__ == "__main__":
    import json
    import os
    import sys

    AI_DIR = os.path.dirname(os.path.abspath(__file__))
    if AI_DIR not in sys.path:
        sys.path.insert(0, AI_DIR)
    from xml_summary import summarize_musicxml

    img = sys.argv[1] if len(sys.argv) > 1 else "test.png"
    xml = sys.argv[2] if len(sys.argv) > 2 else "test_rectified.musicxml"
    summary = summarize_musicxml(xml)
    tempos = detect_tempos(img, summary, debug=True)
    print(json.dumps(tempos, ensure_ascii=False, indent=2))
    print("可用写法:", tempos_to_spec(tempos))
