"""谱面版面分析：识别谱行（system）与小节线（barline），为速度标记定位小节号。

单声部大河谱常见结构：每行五线谱，行内若干小节由竖线分隔；
多小节休止（谱上写个 7、8、9 的长休止）算作 N 个小节。
"""
import numpy as np
from PIL import Image


def load_binary(path, thresh=165):
    im = Image.open(path).convert("L")
    a = np.array(im)
    return a < thresh, a.shape


def staff_lines(binary, min_ratio=0.35):
    """横线：整行暗像素比例很高。返回行号列表。"""
    h, w = binary.shape
    counts = binary.sum(axis=1)
    rows = counts > w * min_ratio
    groups = []
    i = 0
    while i < h:
        if rows[i]:
            j = i
            while j < h and rows[j]:
                j += 1
            groups.append((i + j - 1) // 2)
            i = j
        else:
            i += 1
    return groups


def systems(lines, max_gap=90):
    if not lines:
        return []
    out = []
    cur = [lines[0]]
    for y in lines[1:]:
        if y - cur[-1] <= max_gap:
            cur.append(y)
        else:
            out.append(cur)
            cur = [y]
    out.append(cur)
    return out


def barlines(binary, y0, y1, min_ratio=0.82, min_width=2):
    band = binary[max(0, y0 - 6):y1 + 6, :]
    if band.size == 0:
        return []
    ratio = band.sum(axis=0) / float(band.shape[0])
    cols = ratio > min_ratio
    out = []
    i = 0
    n = len(cols)
    while i < n:
        if cols[i]:
            j = i
            while j < n and cols[j]:
                j += 1
            if j - i >= min_width:
                out.append((i + j - 1) // 2)
            i = j
        else:
            i += 1
    return out


def analyze(path):
    binary, shape = load_binary(path)
    lines = staff_lines(binary)
    syss = systems(lines)
    print(f"{path}: shape={shape} staff_lines={len(lines)} systems={len(syss)}")
    detail = []
    for k, s in enumerate(syss):
        y0, y1 = s[0], s[-1]
        bl = barlines(binary, y0, y1)
        bl2 = [x for x in bl if x > 120]
        detail.append({"system": k + 1, "y0": y0, "y1": y1, "lines": len(s), "barlines": len(bl2), "xs": bl2})
        print(f"  system {k+1}: y={y0}-{y1} lines={len(s)} barlines={len(bl2)}")
        print("     xs:", bl2)
    return detail


if __name__ == "__main__":
    import json, sys
    for p in sys.argv[1:]:
        d = analyze(p)
        json.dump(d, open(p + ".layout.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
