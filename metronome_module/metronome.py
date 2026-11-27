"""MaestroCore 节拍器模块

手机上那种节拍器该有的功能，这里全有，但代码保持精简：

  - 速度：40–208 BPM，±1 / ±5 调，也可直接输入；空格 启动/暂停
  - 拍号：2/4、3/4、4/4、6/8、9/8、12/8，运行中随时切换
  - 重音：第一拍咚、其余哒；每小节第一拍自动重音
  - 点数测速（Tap Tempo）：跟着自己的演奏点几下，自动算出速度
  - 分段练习：读 ai_result.json 里的 metronome_plan，
    从第 1 小节一路走到底，到段末自动换速度/拍号，屏幕上显示当前第几小节
  - 两条命令：
        py metronome_module\\metronome.py                 # 打开图形节拍器
        py metronome_module\\metronome.py --cli --bpm 96 --beats 4 --seconds 8
"""

import json
import os
import sys
import threading
import time

sys.dont_write_bytecode = True

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_MODULE = os.path.join(APP_ROOT, "ai_module")
if AI_MODULE not in sys.path:
    sys.path.insert(0, AI_MODULE)

try:
    import winsound
except ImportError:  # 非 Windows 也能跑，只是没声音
    winsound = None

MIN_BPM, MAX_BPM = 40, 208


# --------------------------------------------------------------------------- #
# 发声：winsound.Beep 是阻塞的，所以丢到小线程里，避免打乱节拍
# --------------------------------------------------------------------------- #
def click(accent=False, sound=True):
    if not sound or winsound is None:
        return

    def _beep():
        try:
            winsound.Beep(1560 if accent else 1040, 90 if accent else 60)
        except RuntimeError:
            pass

    threading.Thread(target=_beep, daemon=True).start()


# --------------------------------------------------------------------------- #
# 节拍引擎：跟界面无关，也能被别的模块直接调用
# --------------------------------------------------------------------------- #
class Metronome:
    def __init__(self, bpm=100, beats=4, beat_type=4, accent=True, sound=True,
                 on_beat=None, plan=None):
        self.bpm = float(max(MIN_BPM, min(MAX_BPM, bpm)))
        self.beats = beats
        self.beat_type = beat_type
        self.accent = accent
        self.sound = sound
        self.on_beat = on_beat

        self.plan = plan or []        # [{'start_measure','end_measure','bpm','beats','beat_type'}]
        self.plan_index = 0
        self.measure = 1

        self.beat_in_bar = 0
        self.total_beats = 0
        self._running = False
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._thread = None

        self._tap_times = []

        if self.plan:            # 一开就按方案第一段的速度/拍号走
            self._apply_plan()

    # --- 控制 ---
    def start(self):
        if self._running:
            return
        self._stop.clear()
        self._paused.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def pause(self):
        if self._running:
            self._paused.set()

    def resume(self):
        self._paused.clear()

    def stop(self):
        self._stop.set()
        self._running = False

    @property
    def running(self):
        return self._running and not self._paused.is_set()

    def toggle(self):
        if not self._running:
            self.start()
        elif self._paused.is_set():
            self.resume()
        else:
            self.pause()

    # --- 参数 ---
    def set_bpm(self, bpm):
        self.bpm = float(max(MIN_BPM, min(MAX_BPM, bpm)))

    def nudge_bpm(self, delta):
        self.set_bpm(round(self.bpm) + delta)

    def set_meter(self, beats, beat_type):
        self.beats, self.beat_type = beats, beat_type
        self.beat_in_bar = 0

    def tap(self):
        """点数测速：最近 4 次间隔取平均。"""
        now = time.perf_counter()
        self._tap_times = [t for t in self._tap_times if now - t < 3.0] + [now]
        if len(self._tap_times) >= 2:
            gaps = [b - a for a, b in zip(self._tap_times, self._tap_times[1:])]
            avg = sum(gaps) / len(gaps)
            if avg > 0:
                self.set_bpm(round(60 / avg))
        return int(self.bpm)

    # --- 分段练习 ---
    def _apply_plan(self):
        if not self.plan:
            return
        seg = self.plan[self.plan_index]
        self.bpm = float(max(MIN_BPM, min(MAX_BPM, seg.get("bpm", self.bpm))))
        self.beats = int(seg.get("beats", self.beats)) or 4
        self.beat_type = int(seg.get("beat_type", self.beat_type)) or 4
        self.measure = int(seg.get("start_measure", 1))
        self.beat_in_bar = 0

    def _advance_plan(self):
        if not self.plan:
            return
        if self.measure >= int(self.plan[self.plan_index].get("end_measure", 1)):
            if self.plan_index + 1 < len(self.plan):
                self.plan_index += 1
                self._apply_plan()

    # --- 主循环 ---
    def _loop(self):
        next_tick = time.perf_counter()
        while not self._stop.is_set():
            while self._paused.is_set() and not self._stop.is_set():
                time.sleep(0.01)
                next_tick = time.perf_counter()
            if self._stop.is_set():
                break

            # 小节第一拍重音
            is_accent = (self.beat_in_bar == 0) and (self.accent or self.plan)
            click(is_accent, self.sound)

            if self.on_beat:
                try:
                    self.on_beat(self.measure, self.beat_in_bar + 1, self.beats,
                                 int(self.bpm), self.beat_type)
                except Exception:  # noqa: BLE001
                    pass

            self.beat_in_bar += 1
            self.total_beats += 1
            if self.beat_in_bar >= max(1, self.beats):
                self.beat_in_bar = 0
                self.measure += 1
                self._advance_plan()

            interval = 60.0 / self.bpm
            next_tick += interval
            lag = next_tick - time.perf_counter()
            if lag < -interval:      # 卡顿太狼就重新对表，别疯狂追赶
                next_tick = time.perf_counter() + interval
                lag = interval
            if lag > 0:
                # 分段睡，保证暂停/停止能立刻响应
                end = time.perf_counter() + lag
                while time.perf_counter() < end and not self._stop.is_set():
                    time.sleep(min(0.02, max(0, end - time.perf_counter())))


# --------------------------------------------------------------------------- #
# 读谱面/上次分析结果
# --------------------------------------------------------------------------- #
def load_plan(source=None):
    """优先读根目录 ai_result.json；没有就读 history 里最新一次。"""
    candidates = []
    if source and os.path.exists(source):
        candidates.append(source)
    candidates.append(os.path.join(APP_ROOT, "ai_result.json"))
    try:
        from history_store import latest_record
        folder, _meta = latest_record()
        if folder:
            candidates.append(str(folder / "ai_result.json"))
    except Exception:  # noqa: BLE001
        pass

    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            payload = json.loads(open(path, encoding="utf-8").read())
        except (OSError, json.JSONDecodeError):
            continue
        plan = (payload.get("ai") or {}).get("metronome_plan") or []
        title = (payload.get("summary") or {}).get("title") or ""
        if plan:
            return plan, title, path
    return [], "", None


# --------------------------------------------------------------------------- #
# 图形界面（手机 APP 那种布局，窗口很小）
# --------------------------------------------------------------------------- #
def _tk_palette():
    """颜色从 theme_module/palette 统一取，跟着兑换的主题一起变。"""
    default = {
        "bg": "#F2F3F5", "card": "#FFFFFF", "soft": "#F7F8FA", "fg": "#1F2328",
        "muted": "#7A8088", "accent": "#4B7BE5", "accent_active": "#3A68D0",
        "accent_soft": "#EAF1FE", "on_accent": "#FFFFFF", "border": "#E3E5E9",
    }
    try:
        theme_dir = os.path.join(APP_ROOT, "theme_module")
        if theme_dir not in sys.path:
            sys.path.insert(0, theme_dir)
        from palette import to_tk
        return {**default, **to_tk()}
    except Exception:  # noqa: BLE001
        return default


def run_gui(plan=None, title=""):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("MaestroCore 节拍器")
    root.geometry("360x430")
    C = _tk_palette()
    root.configure(bg=C["bg"])
    root.resizable(False, False)

    seg_label = tk.StringVar(value=title or "自由练习")
    measure_var = tk.StringVar(value="第 1 小节")
    beat_var = tk.StringVar(value="1")
    bpm_var = tk.StringVar(value="100")

    metro = Metronome(bpm=int(bpm_var.get()), beats=4, sound=True)

    # 顶部：曲名 / 进度
    tk.Label(root, textvariable=seg_label, bg=C["bg"], fg=C["muted"],
             font=("Microsoft YaHei", 10)).pack(pady=(10, 0))
    tk.Label(root, textvariable=measure_var, bg=C["bg"], fg=C["fg"],
             font=("Microsoft YaHei", 12, "bold")).pack()

    # 中间：大号 BPM + 拍点
    bpm_show = tk.Label(root, textvariable=bpm_var, bg=C["bg"], fg=C["accent"],
                        font=("Consolas", 52, "bold"))
    bpm_show.pack(pady=(4, 0))
    tk.Label(root, text="BPM", bg=C["bg"], fg=C["muted"],
             font=("Microsoft YaHei", 9)).pack()
    beat_show = tk.Label(root, textvariable=beat_var, bg=C["bg"], fg=C["accent_active"],
                         font=("Consolas", 20, "bold"))
    beat_show.pack(pady=(2, 8))

    def on_beat(measure, beat, beats, bpm, beat_type):
        measure_var.set(f"第 {measure} 小节")
        beat_var.set("●" * beat + "○" * max(0, beats - beat))
        bpm_var.set(str(bpm))

    metro.on_beat = on_beat

    # 速度按钮
    row = tk.Frame(root, bg=C["bg"])
    row.pack()
    for text, delta in (("−5", -5), ("−1", -1), ("+1", +1), ("+5", +5)):
        tk.Button(row, text=text, width=5, bg=C["soft"], fg=C["fg"],
                  activebackground=C["accent_soft"], activeforeground=C["fg"], bd=0,
                  command=lambda d=delta: (metro.nudge_bpm(d), bpm_var.set(str(int(metro.bpm)))
                                           if not metro.running else None)
                  ).pack(side="left", padx=3, pady=4)

    scale = ttk.Scale(root, from_=MIN_BPM, to=MAX_BPM, value=100,
                      command=lambda v: metro.set_bpm(float(v)))
    scale.pack(fill="x", padx=20, pady=(4, 6))

    # 拍号 + 重音
    row2 = tk.Frame(root, bg=C["bg"])
    row2.pack(pady=2)
    meter = ttk.Combobox(row2, values=["1/4", "2/4", "3/4", "4/4", "3/8", "6/8", "9/8", "12/8"],
                         width=6, state="readonly")
    meter.set("4/4")
    meter.pack(side="left", padx=6)

    accent_on = tk.BooleanVar(value=True)
    tk.Checkbutton(row2, text="重音", variable=accent_on, bg=C["bg"], fg=C["muted"],
                   selectcolor=C["card"], activebackground=C["bg"], activeforeground=C["fg"],
                   command=lambda: setattr(metro, "accent", accent_on.get())).pack(side="left")

    def apply_meter(_=None):
        b, t = meter.get().split("/")
        metro.set_meter(int(b), int(t))

    meter.bind("<<ComboboxSelected>>", apply_meter)

    # 启动 / 暂停
    big = tk.Button(root, text="启动", bg=C["accent"], fg=C["on_accent"], bd=0,
                    font=("Microsoft YaHei", 15, "bold"), height=2,
                    activebackground=C["accent_active"], activeforeground=C["on_accent"])
    big.pack(fill="x", padx=20, pady=(10, 4))

    def toggle():
        metro.sound = True
        metro.toggle()
        big.configure(text="暂停" if metro.running else "启动",
                      bg=C["accent_active"] if metro.running else C["accent"])

    big.configure(command=toggle)
    root.bind("<space>", lambda e: toggle())

    # 点数测速 / 加载方案 / 停止
    row3 = tk.Frame(root, bg=C["bg"])
    row3.pack(pady=(2, 10))
    tk.Button(row3, text="点数测速", bg=C["soft"], fg=C["fg"], bd=0, width=9,
              activebackground=C["accent_soft"],
              command=lambda: bpm_var.set(str(metro.tap()))).pack(side="left", padx=3)
    tk.Button(row3, text="加载练习方案", bg=C["soft"], fg=C["fg"], bd=0, width=11,
              activebackground=C["accent_soft"],
              command=lambda: load_into(metro, seg_label)).pack(side="left", padx=3)
    tk.Button(row3, text="停止", bg=C["soft"], fg=C["fg"], bd=0, width=6,
              activebackground=C["accent_soft"],
              command=lambda: (metro.stop(), big.configure(text="启动", bg=C["accent"]))
              ).pack(side="left", padx=3)

    tk.Label(root, text="空格 启动/暂停　←→ 调速　T 测速", bg=C["bg"], fg=C["muted"],
             font=("Microsoft YaHei", 8)).pack(side="bottom", pady=4)
    root.bind("<Left>", lambda e: (metro.nudge_bpm(-1), bpm_var.set(str(int(metro.bpm)))))
    root.bind("<Right>", lambda e: (metro.nudge_bpm(1), bpm_var.set(str(int(metro.bpm)))))
    root.bind("<t>", lambda e: bpm_var.set(str(metro.tap())))

    if plan:
        load_into(metro, seg_label, plan, title)

    root.protocol("WM_DELETE_WINDOW", lambda: (metro.stop(), root.destroy()))
    root.mainloop()


def load_into(metro, seg_label, plan=None, title=""):
    if plan is None:
        plan, title, _src = load_plan()
    if not plan:
        seg_label.set("没找到练习方案（先跑一次一条龙）")
        return
    metro.plan = plan
    metro.plan_index = 0
    metro._apply_plan()
    seg_label.set(f"{title or '练习方案'}｜{len(plan)} 段")


# --------------------------------------------------------------------------- #
# 命令行模式（测试/无界面用）
# --------------------------------------------------------------------------- #
def run_cli(bpm=100, beats=4, beat_type=4, seconds=8, sound=False, use_plan=False):
    plan, title, src = load_plan() if use_plan else ([], "", None)
    metro = Metronome(bpm=bpm, beats=beats, beat_type=beat_type, sound=sound, plan=plan)
    if plan:
        print(f"练习方案：{title}（{len(plan)} 段，来自 {os.path.basename(src or '')}）")

    def on_beat(measure, beat, beats, bpm, beat_type):
        mark = "咚" if beat == 1 else "哒"
        print(f"  第 {measure:>2} 小节 {beat}/{beats}  {mark}  {bpm} BPM", flush=True)

    metro.on_beat = on_beat
    metro.start()
    time.sleep(seconds)
    metro.pause()
    time.sleep(0.5)
    metro.resume()
    time.sleep(1.0)
    metro.stop()
    print(f"共打了 {metro.total_beats} 拍，最后停在 {int(metro.bpm)} BPM")


def main(argv):
    opts = {"--bpm": 100, "--beats": 4, "--beat-type": 4, "--seconds": 8,
            "--plan": False, "--sound": False, "--cli": False}
    for i, arg in enumerate(argv):
        if arg == "--plan":
            opts["--plan"] = True
        elif arg == "--sound":
            opts["--sound"] = True
        elif arg == "--cli":
            opts["--cli"] = True
        elif arg in ("--bpm", "--beats", "--beat-type", "--seconds") and i + 1 < len(argv):
            opts[arg] = int(argv[i + 1])

    if opts["--cli"]:
        run_cli(opts["--bpm"], opts["--beats"], opts["--beat-type"],
                opts["--seconds"], opts["--sound"], opts["--plan"])
        return

    plan, title, _src = load_plan()
    run_gui(plan, title)


if __name__ == "__main__":
    main(sys.argv[1:])
