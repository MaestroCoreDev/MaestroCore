"""MaestroCore 一条龙流水线：图像矫正 -> HOMR 识别 -> 豆包 AI 讲解 -> 归档

用法：
    py main_app\\run_pipeline.py                       # 默认处理根目录的 test.png
    py main_app\\run_pipeline.py 第一页.png 第二页.png   # 多页一起上，合并成一份谱子
    py main_app\\run_pipeline.py 谱.png --tempo 1:96,13:120 --instrument 长号

跑完之后：
    - 识别出的 .musicxml 自动收进 history\\NN_曲名\\score.musicxml（根目录不再堆文件）
    - 矫正图、放大图、页眉裁剪等副产物全部进 temp_debug\\<时间_曲名>\\
    - history\\index.json 是给以后 UI 历史记录页读的清单
"""

import os
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True  # 不生成 __pycache__，左侧目录保持干净

current_dir = os.path.dirname(os.path.abspath(__file__))
app_root = os.path.dirname(current_dir)

input_img = os.path.join(app_root, "test.png")
rectified_img = os.path.join(app_root, "test_rectified.png")


def _import_ai_module():
    ai_dir = os.path.join(app_root, "ai_module")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)


def _clean_up(rectified_paths, session=None):
    """把矫正图、teaser 图挪进 temp_debug 本次会话的 preview/。"""
    print("\n>>> 收拾副产物（矫正图/预览图 -> temp_debug）...")
    folder = session
    if folder is None:
        try:
            import debug_store
            folder = debug_store.path()
        except Exception:  # noqa: BLE001
            folder = None
    if folder is None:
        folder = os.path.join(app_root, "temp_debug")
        os.makedirs(folder, exist_ok=True)

    for path in rectified_paths:
        teaser = os.path.splitext(path)[0] + "_teaser.png"
        for src in (teaser, path):
            if os.path.exists(src):
                try:
                    shutil.move(src, os.path.join(str(folder), "preview",
                                                   os.path.basename(src)))
                except (OSError, FileNotFoundError):
                    shutil.move(src, os.path.join(str(folder), os.path.basename(src)))
    print("副产物已归类，根目录只留成品。")


def _archive_score(xml_path, payload, session=None):
    """谱面文件用完就收进历史记录文件夹；AI 没跑成的话先塞进本次副产物文件夹。"""
    if not (payload and payload.get("history_folder")):
        if session and os.path.exists(xml_path):
            target = os.path.join(str(session), "未归档")
            os.makedirs(target, exist_ok=True)
            shutil.move(xml_path, os.path.join(target, os.path.basename(xml_path)))
            print(f"[归档] AI 未完成，谱面先放进副产物：{target}")
        else:
            print("[归档] 没有历史记录编号，谱面文件先留在根目录。")
        return xml_path

    _import_ai_module()
    from history_store import HISTORY_DIR, finalize_score

    folder = HISTORY_DIR / payload["history_folder"]
    moved = finalize_score(xml_path, folder)
    if moved:
        print(f"[归档] 谱面已收进历史记录：{moved}")
        return str(moved)
    return xml_path


def run_pipeline(input_paths=None, tempo_spec=None, instrument=None, provider="doubao"):
    print("========================================")
    print("         启动 MaestroCore 引擎          ")
    print("========================================")

    _import_ai_module()
    try:
        import debug_store
        debug_store.begin_session("流水线")
    except Exception:  # noqa: BLE001
        debug_store = None

    if not input_paths:
        input_paths = [input_img]

    missing = [p for p in input_paths if not os.path.exists(p)]
    if missing:
        print(f"找不到这些图片：{missing}")
        return

    page_count = len(input_paths)
    print(f"本次共有 {page_count} 页谱子：{[os.path.basename(p) for p in input_paths]}")

    # --- 步骤 1：图像矫正（逐页矫正）---
    print(f"\n>>> [模块 1/3] 启动图像自动矫正（{page_count} 页）...")
    rectify_script = os.path.join(app_root, "rectify_module", "rectify.py")
    rectified_paths = []
    for idx, src in enumerate(input_paths, start=1):
        if page_count == 1:
            out = rectified_img
        else:
            out = os.path.join(app_root, f"page{idx}_rectified.png")
        print(f"   第 {idx}/{page_count} 页：{os.path.basename(src)}")
        subprocess.run([sys.executable, rectify_script, src, out])
        rectified_paths.append(out)

    # --- 步骤 2：HOMR 识别（多页会合并成一份 MusicXML）---
    print(f"\n>>> [模块 2/3] 启动 HOMR 谱面识别（{page_count} 页合并）...")
    homr_dir = os.path.join(app_root, "homr_module", "homr-main")
    os.chdir(homr_dir)

    # 识别过程很吵，日志收进 temp_debug，终端只留一行会跳秒的进度
    log_file = None
    log_path = os.path.join(str(debug_store.path()), "homr.log") if debug_store and debug_store.path() else None
    if log_path:
        log_file = open(log_path, "w", encoding="utf-8", errors="ignore")
    try:
        from progress import Ticker
        ticker = Ticker("正在识别中", "已识别")
    except Exception:  # noqa: BLE001
        ticker = None

    proc = subprocess.Popen([sys.executable, "-m", "homr.main", *rectified_paths],
                            stdout=log_file or subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    if ticker:
        ticker.start()
    while proc.poll() is None:
        time.sleep(0.2)
    if ticker:
        ticker.stop()
    if log_file:
        log_file.close()
    print(f"    识别完成（进程退出码 {proc.returncode}）")

    # homr 的输出文件名跟着第一张图走
    result_xml = os.path.splitext(rectified_paths[0])[0] + ".musicxml"
    os.chdir(app_root)

    if not os.path.exists(result_xml):
        print("[中断] HOMR 没有生成 MusicXML，后面两步跳过。")
        if log_path and os.path.exists(log_path):
            print(f"    识别日志留在：{log_path}，最后几行：")
            try:
                tail = open(log_path, encoding="utf-8", errors="ignore").read().splitlines()[-8:]
                for line in tail:
                    print("      " + line)
            except OSError:
                pass
        return

    # --- 步骤 3：豆包 AI 讲解（读刚识别出的 XML，出练琴方案）---
    print(f"\n>>> [模块 3/3] 启动 AI 谱面讲解（{provider}）...")
    payload = None
    try:
        from ai_analyzer import analyze_music_with_ai
        # 速度 OCR 必须用矫正后的图，坐标才和 homr 记下的一致
        payload = analyze_music_with_ai(result_xml, provider, tempo_spec=tempo_spec,
                                        image_path=rectified_paths[0], instrument=instrument)
    except Exception as exc:
        print(f"[模块 3] 跳过 AI 讲解：{exc}")

    # --- 收尾：谱面进历史记录，副产物进 temp_debug ---
    result_xml = _archive_score(result_xml, payload,
                                debug_store.path() if debug_store else None)
    _clean_up(rectified_paths, debug_store.path() if debug_store else None)
    if debug_store:
        try:
            debug_store.end_session()
        except Exception:  # noqa: BLE001
            pass

    print("\n========================================")
    print("           MaestroCore 运行结束         ")
    print("========================================")


if __name__ == "__main__":
    args = sys.argv[1:]
    options = {"--tempo": None, "--instrument": None, "--provider": "doubao"}
    images = []
    i = 0
    while i < len(args):
        if args[i] in options and i + 1 < len(args):
            options[args[i]] = args[i + 1]
            i += 2
            continue
        images.append(os.path.abspath(args[i]))
        i += 1

    run_pipeline(images or None, tempo_spec=options["--tempo"],
                 instrument=options["--instrument"], provider=options["--provider"])
