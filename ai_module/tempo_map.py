"""MaestroCore / ai_module 谱面速度地图（不依赖 homr 的坐标）

背景：homr 只认音符，谱面印的 ♩=64 / ♩=170 它完全看不到；它输出的 MusicXML
里也没有每小节图像坐标（imgpos），所以原来靠坐标落小节那套全部失效，
所有速度标记都挤到「第 1 小节」，等于没识别。

这里改走版面分析：
1. 横线开运算找出谱行（staff system）；
2. 每一行里用竖直开运算找出距整行高度的竖线，按间距过滤 → 小节线；
3. 相邻小节线之间就是一个“小节框”，多小节休止框上面印着 7 / 8 / 9 这种数字，
   把它读出来，这个框就算 N 个小节；
4. OCR 全页找速度标记（♩=xx / J=xx / Largo… 等），按坐标落进小节框 → 得到
   「第几小节起多少 BPM」。

整套只吃一张图，不要求 homr 提供坐标。
"""

import re

import cv2
import numpy as np

_TEMPO_TOKEN = re.compile(r"(?:[JQq♩♪𝅘𝅥]|1)\s*[=＝]\s*(\d{2,3})")
_TEMPO_WORDS = {
    "grave": 44, "largo": 50, "larghetto": 60, "lento": 54, "adagio": 66,
    "andante": 84, "andantino": 92, "moderato": 108, "allegretto": 112,
    "allegro": 120, "vivace": 152, "presto": 180, "prestissimo": 200,
}

_engine = None


def _ocr_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _imread_gray(path):
    buf = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def _systems(gray):
    h, w = gray.shape
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 40), 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
    rows = (horiz > 0).sum(axis=1)
    line_rows = rows > w * 0.12
    lines, y = [], 0
    while y < h:
        if line_rows[y]:
            y2 = y
            while y2 < h and line_rows[y2]:
                y2 += 1
            lines.append((y + y2 - 1) // 2)
            y = y2
        else:
            y += 1
    groups, cur = [], []
    for yy in lines:
        if cur and yy - cur[-1] > 45:
            groups.append(cur)
            cur = []
        cur.append(yy)
    if cur:
        groups.append(cur)
    return [(g[0], g[-1]) for g in groups if len(g) >= 4 and g[-1] - g[0] > 40]


def _barlines(gray, y0, y1, min_gap=100):
    band = gray[max(0, y0 - 6):y1 + 6, :]
    bw = cv2.adaptiveThreshold(band, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 31, 12)
    staff_h = y1 - y0
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, int(staff_h * 0.9))))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, k)
    col = (vert > 0).sum(axis=0)
    cand = [i for i, v in enumerate(col) if v >= staff_h * 0.85]

    runs, i = [], 0
    while i < len(cand):
        j = i
        while j + 1 < len(cand) and cand[j + 1] - cand[j] <= 2:
            j += 1
        runs.append(((cand[i] + cand[j]) // 2, cand[j] - cand[i] + 1))
        i = j + 1

    keep = []
    for x, w in runs:
        if w > 8:
            continue
        if not keep or x - keep[-1] >= min_gap:
            keep.append(x)
    return keep


def _ocr(gray_or_path):
    """返回 [{text, x0, y0, x1, y1}]"""
    engine = _ocr_engine()
    res, _ = engine(gray_or_path if isinstance(gray_or_path, str) else _to_bgr(gray_or_path))
    items = []
    for box, text, score in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append({
            "text": text.strip(),
            "x0": float(min(xs)), "x1": float(max(xs)),
            "y0": float(min(ys)), "y1": float(max(ys)),
        })
    return items


def _page_ocr(path):
    """整页 OCR 结果按文件（大小+修改时间）缓存到 temp_debug\\ocr_cache。

    全页 OCR 一页要 20 秒上下，同一张图重复跑（比如识别完再生成网页）没必要重来。
    """
    import hashlib
    import json
    import os
    full = os.path.abspath(str(path))
    try:
        st = os.stat(full)
    except OSError:
        return _ocr(str(path))
    key = f"{full}|{st.st_size}|{int(st.st_mtime)}"
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(root, "temp_debug", "ocr_cache")
    cache_file = os.path.join(cache_dir, f"page_{digest}.json")
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except (OSError, ValueError):
        pass
    items = _ocr(str(path))
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
    except OSError:
        pass
    return items


def _to_bgr(gray):
    import tempfile
    from PIL import Image
    p = tempfile.mktemp(suffix=".png")
    Image.fromarray(gray).save(p)
    return p


def _rest_count(gray, a, b, y0):
    """多小节休止框上的数字（7 / 8 / 9 / 10），读不出就当 1 小节。"""
    pad = 8
    x0 = max(0, int(a) + pad)
    x1 = min(gray.shape[1], int(b) - pad)
    yy0 = max(0, int(y0) - 62)
    yy1 = max(0, int(y0) - 2)
    if x1 - x0 < 60 or yy1 - yy0 < 20:
        return 1
    crop = gray[yy0:yy1, x0:x1]
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    items = _ocr(_to_bgr(crop))
    for it in items:
        t = it["text"].strip()
        m = re.fullmatch(r"\d{1,2}", t)
        if m:
            v = int(t)
            if 2 <= v <= 40:
                return v
    return 1


def _cache_path(kind, path):
    import hashlib
    import os
    full = os.path.abspath(str(path))
    try:
        st = os.stat(full)
    except OSError:
        return None
    key = f"{full}|{st.st_size}|{int(st.st_mtime)}"
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:16]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "temp_debug", f"{kind}_cache", f"{kind}_{digest}.json")


def layout(path, debug=False):
    """返回 {'systems': [...], 'boxes': [(x_a, x_b, y0, y1, count)]}，按阅读顺序。

    结果会缓存：同一张图第二次进流水线直接读缓存，省掉十几秒的休止框 OCR。
    """
    import json
    import os
    cache = _cache_path("layout", path)
    if cache and os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("total_measures"):
                if debug:
                    for s in data["systems"]:
                        print(f"    谱行 {s['index']}: y={s['y0']}-{s['y1']} 小节框 "
                              f"{len(s['boxes'])} 合计 {sum(b[4] for b in s['boxes'])} 小节（缓存）")
                return data
        except (OSError, ValueError):
            pass

    gray = _imread_gray(path)
    out = {"systems": [], "boxes": []}
    total = 0
    for si, (y0, y1) in enumerate(_systems(gray), 1):
        xs = _barlines(gray, y0, y1)
        edges = [60] + xs + [gray.shape[1] - 60]
        boxes = []
        for a, b in zip(edges, edges[1:]):
            if b - a < 40:
                continue
            count = 1
            # 多小节休止框比普通小节宽得多（普通小节 300 上下，休止框常见 600+），
            # 阈值定 330：比它窄的肯定不是休止框，不去读上面的数字（读一次 OCR 要好几秒）
            if b - a >= 330:
                count = _rest_count(gray, a, b, y0)
            boxes.append((a, b, y0, y1, count))
            total += count
        out["systems"].append({"index": si, "y0": y0, "y1": y1, "boxes": boxes})
        if debug:
            print(f"    谱行 {si}: y={y0}-{y1} 小节框 {len(boxes)} 合计 {sum(b[4] for b in boxes)} 小节")
    out["boxes"] = [b for s in out["systems"] for b in s["boxes"]]
    out["total_measures"] = total
    if cache:
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
        except OSError:
            pass
    return out


def tempo_marks(path, layout_data=None, debug=False):
    """全页找速度标记，落到小节号上。"""
    lay = layout_data or layout(path, debug=debug)
    items = _page_ocr(str(path))
    sys_start, acc0 = {}, 0
    for s in lay["systems"]:
        sys_start[s["index"]] = acc0 + 1
        acc0 += sum(b[4] for b in s["boxes"])
    marks = []
    for it in items:
        text = it["text"]
        val = None
        m = _TEMPO_TOKEN.search(text)
        if m:
            v = int(m.group(1))
            if 30 <= v <= 300:
                val = v
        if val is None:
            low = text.lower()
            for w, dflt in _TEMPO_WORDS.items():
                if w in low:
                    val = dflt
                    break
        if val is None:
            continue
        cx = (it["x0"] + it["x1"]) / 2
        cy = (it["y0"] + it["y1"]) / 2
        measure = None
        acc = 0
        for box in lay["boxes"]:
            a, b, y0, y1, cnt = box
            # 速度标记一般贴在谱行上方，允许它比谱行高一点
            if a - 10 <= cx <= b + 10 and (y0 - 90) <= cy <= (y1 + 20):
                measure = acc + 1
                break
            acc += cnt
        if measure is None:
            # 退一步：按整行找。标记常常印在两行之间的空白里，x 也可能骑在小节线边上
            for s in lay["systems"]:
                y0, y1 = s["y0"], s["y1"]
                xs = [b[0] for b in s["boxes"]] + [b[1] for b in s["boxes"]]
                if not xs:
                    continue
                if (y0 - 130) <= cy <= (y1 + 30) and min(xs) - 40 <= cx <= max(xs) + 40:
                    # 落在这一行就算这一行的小节起点（行首速度通常管整行）
                    measure = sys_start.get(s["index"], 1)
                    break
        if measure is None:
            continue
        marks.append({"measure": measure, "bpm": float(val), "text": text, "source": "ocr"})
        if debug:
            print(f"    OCR「{text}」→ 第 {measure} 小节 {val} BPM")

    marks.sort(key=lambda x: x["measure"])
    dedup = {}
    for mk in marks:
        dedup.setdefault(mk["measure"], mk)
    marks = list(dedup.values())
    return marks


def build_tempo_map(paths, debug=False):
    """多页合成一张全局速度表。返回 (marks, info)。

    marks: [{'measure','bpm','text','source'}]，小节号是跨页累计的；
    info: {'total_measures', 'pages': [{path, total_measures}]}
    """
    if isinstance(paths, str):
        paths = [paths]
    pages, marks, offset = [], [], 0
    for path in paths:
        lay = layout(path, debug=debug)
        page_marks = tempo_marks(path, lay, debug=debug)
        for mk in page_marks:
            mk = dict(mk)
            mk["measure"] += offset
            mk["page"] = len(pages) + 1
            mk["page_measure"] = mk["measure"] - offset
            marks.append(mk)
        pages.append({"path": str(path), "total_measures": lay["total_measures"]})
        offset += lay["total_measures"]

    marks.sort(key=lambda x: x["measure"])
    clean = []
    for mk in marks:
        if clean and mk["measure"] == clean[-1]["measure"]:
            if clean[-1]["source"] != "ocr":
                clean[-1] = mk
            continue
        if clean and mk["bpm"] == clean[-1]["bpm"]:
            continue
        clean.append(mk)

    # 开头没有标记就用最靠近开头的那个；只补一次，别每页都补
    if clean and clean[0]["measure"] != 1:
        first = dict(clean[0])
        first["measure"] = 1
        first["text"] = first.get("text", "") + "（开头沿用）"
        clean.insert(0, first)

    info = {"total_measures": offset, "pages": pages}
    return clean, info


def spec_text(marks):
    return ",".join(f"{int(m['measure'])}:{int(round(m['bpm']))}" for m in marks)


if __name__ == "__main__":
    import json
    import sys
    paths = sys.argv[1:]
    marks, info = build_tempo_map(paths, debug=True)
    print("总小节数：", info["total_measures"])
    print(json.dumps(marks, ensure_ascii=False, indent=1))
    print("写法：", spec_text(marks))
