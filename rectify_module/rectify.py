import cv2
import numpy as np
import sys
import os


def _imread(path):
    """cv2.imread 读不了中文路径，改用 imdecode 兜一遍。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return cv2.imread(path)


def _imwrite(path, img):
    """cv2.imwrite 写不了中文路径，改用 imencode。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(path)
    return True


def _horizontal_score(gray):
    """横向长直线（五线谱的谱线）越多分数越高，用来判页面朝向。"""
    small = cv2.resize(gray, None, fx=1.0, fy=1.0) if gray.shape[1] <= 900 else cv2.resize(
        gray, (900, int(gray.shape[0] * 900 / gray.shape[1])))
    bw = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 15, 8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
    return float(horiz.sum())


def _column_ink(gray):
    """左端（谱号、小节号、乐器名）比右端墨多，用来分清正着还是上下颠倒。"""
    small = gray if gray.shape[1] <= 900 else cv2.resize(
        gray, (900, int(gray.shape[0] * 900 / gray.shape[1])))
    ink = (small < 128).sum(axis=0).astype(float)
    w = small.shape[1]
    left = float(ink[:max(1, int(w * 0.1))].sum())
    right = float(ink[int(w * 0.9):].sum())
    return left - right


def _auto_orient(img):
    """谱子横着拍进来也能救：谱线最横的方向优先，再用左重右轻分清正反。"""
    options = [
        (0, img),
        (90, cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)),
        (270, cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)),
        (180, cv2.rotate(img, cv2.ROTATE_180)),
    ]
    scored = []
    for deg, cur in options:
        try:
            gray = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY)
            horiz = _horizontal_score(gray)
            sided = _column_ink(gray)
        except Exception:
            continue
        scored.append((deg, horiz, sided, cur))
    if not scored:
        return img
    best_horiz = max(s[1] for s in scored)
    # 横向分数相近的候选里（正反两种都差不多），挑左边墨多的那个
    finals = [s for s in scored if s[1] >= best_horiz * 0.9]
    deg, _, _, cur = max(finals, key=lambda s: s[2])
    if deg:
        print(f"   页面方向不对（转 {deg}° 摆正），已自动旋转。")
    return cur


def rectify_image(input_path, output_path):
    img = _imread(input_path)
    if img is None:
        print(f"找不到图片: {input_path}")
        return False

    img = _auto_orient(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        print("没找到轮廓，原图保存。")
        _imwrite(output_path, img)
        return True
    
    c = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    
    if len(approx) == 4:
        pts = approx.reshape(4, 2)
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        
        (tl, tr, br, bl) = rect
        widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        maxWidth = max(int(widthA), int(widthB))
        
        heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        maxHeight = max(int(heightA), int(heightB))
        
        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]], dtype="float32")
        
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
        _imwrite(output_path, warped)
        print(f"矫正成功！已保存到: {output_path}")
        return True
    else:
        print(f"未找到完美四边形（找到 {len(approx)} 个角），直接输出原图。")
        _imwrite(output_path, img)
        return True

if __name__ == "__main__":
    if len(sys.argv) == 3:
        rectify_image(sys.argv[1], sys.argv[2])
    else:
        print("参数错误，需要输入路径和输出路径。")
