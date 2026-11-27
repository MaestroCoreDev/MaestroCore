"""MaestroCore / ai_module 谱面拍子结构

从谱面图里读出「哪些小节是空拍（整小节休止）」「开头有没有起拍（弱起）」。

为什么单独一个模块：速度地图只管 ♩=xx，拍号、空拍、起拍这些属于「节奏骨架」，
统一放这里算，结果挂到 summary["structure"] 上，节拍器和界面都读它。

现在能自动做的：
- 整小节空拍：小节里只有一个居中的实心横条（whole rest），没有任何音符 → 空拍
- 起拍（弱起）：第一小节明显比同页普通小节窄 → 拍数按宽度比例估
- 多小节休止：复用 tempo_map.layout 里的 N（7/8/9 那些是印在框上的数字）

拍号本身字太小，OCR 嗗不下来，所以拍号走「手动变拍表」+ 自动提示，
等做了字形模板再补自动识别。
"""

import cv2
import numpy as np

import tempo_map as tm


def _staff_bw(band):
    """谱行条带 → 去掉谱线的二值图（黑为 255）。"""
    _, bw = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (120, 1))
    lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
    return cv2.subtract(bw, cv2.dilate(lines, np.ones((3, 3), np.uint8)))


def _is_whole_rest(gray, box):
    """小节里是不是只有一个 whole rest（整小节空着）。"""
    a, b, y0, y1, _cnt = box
    if b - a < 60:
        return False
    band = gray[max(0, y0 - 4):y1 + 4, max(0, int(a) + 6):int(b) - 6]
    if band.size == 0:
        return False
    bw = _staff_bw(band)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(bw, connectivity=8)
    staff_h = max(1, y1 - y0)
    wide, others = [], 0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 60:
            continue
        aspect = w / max(1, h)
        if aspect >= 2.2 and area >= w * h * 0.55 and h <= staff_h * 0.42:
            wide.append((x, w, h))
        else:
            others += 1
    if not wide or others > 1:
        return False
    # 只留一个横条，且它得落在小节中间那一带
    if len(wide) > 1:
        return False
    x, w, h = wide[0]
    mid = (band.shape[1]) / 2
    return abs((x + w / 2) - mid) <= band.shape[1] * 0.35


def analyze(paths, debug=False):
    """返回 {'empty': [...], 'pickup': {...} | None, 'total_measures': N}"""
    if isinstance(paths, str):
        paths = [paths]
    empty, per_page, offset = [], [], 0
    for path in paths:
        lay = tm.layout(path, debug=debug)
        gray = tm._imread_gray(path)
        boxes = lay["boxes"]
        widths = sorted(b[1] - b[0] for b in boxes)
        median_w = widths[len(widths) // 2] if widths else 0
        page_empty = []
        for bi, box in enumerate(boxes):
            measure = offset + sum(b[4] for b in boxes[:bi]) + 1
            if _is_whole_rest(gray, box):
                page_empty.append((measure, box[4]))
        if debug:
            print(f"  {path.split(chr(92))[-1]}: 空拍小节 {page_empty}")
        empty.extend(page_empty)
        per_page.append({"path": path, "median_w": median_w, "first_w": (boxes[0][1] - boxes[0][0]) if boxes else 0})
        offset += lay["total_measures"]

    runs = []
    for measure, cnt in empty:
        if runs and measure == runs[-1]["to"] + runs[-1]["measures"]:
            runs[-1]["to"] = measure
            runs[-1]["measures"] += cnt
        else:
            runs.append({"from": measure, "to": measure, "measures": cnt})

    pickup = None
    if per_page and per_page[0]["median_w"]:
        fw, mw = per_page[0]["first_w"], per_page[0]["median_w"]
        # 首小节比普通小节窄一截，就当弱起；拍数按宽度比估，最小半拍
        if fw < mw * 0.75:
            ratio = fw / mw
            beats = max(0.5, round(ratio * 4 * 2) / 2)
            pickup = {"measure": 1, "beats": beats, "by_width": True}
    return {"empty": runs, "pickup": pickup, "total_measures": offset}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(analyze(sys.argv[1:], debug=True), ensure_ascii=False, indent=1))
