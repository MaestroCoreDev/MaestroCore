"""MaestroCore 识别助手（桌面窗口版）

为什么要有这个：本机 127.0.0.1 的回环被安全软件/网络过滤挡住时，
浏览器打不开 http://127.0.0.1:8765/，但谱面识别本身不依赖网络。
这个窗口直接把「选照片 → 识别 → 生成网页 → 打开网页」串起来，
识别完自动重新生成离线网页，然后在浏览器里看结果、进节拍器。

用法：
    双击项目根目录的 识别谱面.bat
"""

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PREVIEW_INDEX = os.path.join(ROOT, "frontend_module", "_offline", "index.html")


class App:
    def __init__(self, master):
        self.master = master
        master.title("MaestroCore 识别助手")
        master.geometry("820x620")
        master.configure(bg="#101418")

        self.files = []
        self.q = queue.Queue()
        self.running = False

        head = tk.Label(
            master, text="谱面识别助手",
            bg="#101418", fg="#eaf2ff", font=("Microsoft YaHei UI", 18, "bold"),
        )
        head.pack(anchor="w", padx=20, pady=(16, 2))
        tk.Label(
            master,
            text="选好几张谱面照片（按页顺序），点开始。识别完会自动生成网页并在浏览器打开。",
            bg="#101418", fg="#8fa3b8", font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=20, pady=(0, 12))

        bar = tk.Frame(master, bg="#101418")
        bar.pack(fill="x", padx=20)

        self.btn_add = self._btn(bar, "添加照片", self.add_files, "#2b3a4b")
        self.btn_del = self._btn(bar, "移除选中", self.remove_selected, "#2b3a4b")
        self.btn_clear = self._btn(bar, "清空", self.clear_files, "#2b3a4b")
        self.btn_run = self._btn(bar, "开始识别", self.start, "#2f6cf6")

        self.listbox = tk.Listbox(
            master, bg="#161c22", fg="#dfe9f3", selectbackground="#2f6cf6",
            highlightthickness=0, borderwidth=0, font=("Microsoft YaHei UI", 10),
        )
        self.listbox.pack(fill="x", padx=20, pady=(12, 10), ipady=4, height=6)

        mid = tk.Frame(master, bg="#101418")
        mid.pack(fill="x", padx=20)
        tk.Label(mid, text="乐器（可留空）", bg="#101418", fg="#8fa3b8").pack(side="left")
        self.instrument = tk.Entry(
            mid, bg="#161c22", fg="#dfe9f3", insertbackground="#dfe9f3",
            relief="flat", width=22,
        )
        self.instrument.pack(side="left", padx=(8, 24), ipady=3)
        tk.Label(mid, text="速度（可留空，1:96,13:120）", bg="#101418", fg="#8fa3b8").pack(side="left")
        self.tempo = tk.Entry(
            mid, bg="#161c22", fg="#dfe9f3", insertbackground="#dfe9f3",
            relief="flat", width=22,
        )
        self.tempo.pack(side="left", padx=8, ipady=3)

        self.status = tk.Label(
            master, text="还没选照片。", bg="#101418", fg="#7ee2a8",
            font=("Microsoft YaHei UI", 10), anchor="w",
        )
        self.status.pack(fill="x", padx=20, pady=(12, 4))

        self.log = tk.Text(
            master, bg="#0b0f14", fg="#9db4c9", relief="flat",
            font=("Consolas", 9), wrap="word", height=12,
        )
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        bottom = tk.Frame(master, bg="#101418")
        bottom.pack(fill="x", padx=20, pady=(0, 16))
        self._btn(bottom, "打开结果网页", self.open_preview, "#243040")
        self._btn(bottom, "打开节拍器", self.open_metronome, "#243040")

        self.master.after(120, self.pump)

    def _btn(self, parent, text, cmd, color):
        b = tk.Button(
            parent, text=text, command=cmd, bg=color, fg="#ffffff",
            activebackground="#3b4d63", activeforeground="#ffffff",
            relief="flat", borderwidth=0, padx=16, pady=6,
            font=("Microsoft YaHei UI", 10), cursor="hand2",
        )
        b.pack(side="left", padx=(0, 10))
        return b

    # ---------------- 文件 ----------------
    def add_files(self):
        picked = filedialog.askopenfilenames(
            title="选谱面照片（可以多选，按页顺序）",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp *.webp"), ("全部文件", "*.*")],
        )
        for f in sorted(picked, key=lambda x: os.path.basename(x)):
            if f not in self.files:
                self.files.append(f)
                self.listbox.insert("end", f"{len(self.files)}.  {os.path.basename(f)}")
        self.refresh_status()

    def remove_selected(self):
        for idx in reversed(self.listbox.curselection()):
            self.listbox.delete(idx)
            self.files.pop(idx)
        self.refresh_status()

    def clear_files(self):
        self.listbox.delete(0, "end")
        self.files.clear()
        self.refresh_status()

    def refresh_status(self):
        if not self.files:
            self.status.config(text="还没选照片。", fg="#7ee2a8")
        else:
            self.status.config(text=f"已选 {len(self.files)} 页，可以开始了。", fg="#7ee2a8")

    # ---------------- 跑流水线 ----------------
    def start(self):
        if self.running:
            return
        if not self.files:
            messagebox.showinfo("MaestroCore", "先添加谱面照片。")
            return
        self.running = True
        self.btn_run.config(state="disabled", text="识别中…")
        self.status.config(text="正在启动流水线…", fg="#ffd479")
        self.log.delete("1.0", "end")
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        import io
        from contextlib import redirect_stdout

        ok = False
        try:
            main_dir = os.path.join(ROOT, "main_app")
            if main_dir not in sys.path:
                sys.path.insert(0, main_dir)
            import run_pipeline as rp

            buf = io.StringIO()

            class Tee(io.TextIOBase):
                def write(self, s):
                    buf.write(s)
                    self_q.put(s)
                    return len(s)

            self_q = self.q
            with redirect_stdout(Tee()):
                payload = rp.run_pipeline(
                    self.files,
                    tempo_spec=(self.tempo.get().strip() or None),
                    instrument=(self.instrument.get().strip() or None),
                    provider="doubao",
                )
            ok = bool(payload)
            self.q.put(("\n>>> 重新生成网页…\n", "log"))
            self.rebuild_preview()
            self.q.put((payload, "done" if ok else "warn"))
        except Exception as exc:  # noqa: BLE001
            self.q.put((f"\n[失败] {exc}\n{traceback.format_exc()[-900:]}\n", "log"))
            self.q.put((exc, "warn"))

    def rebuild_preview(self):
        script = os.path.join(ROOT, "frontend_module", "build_preview.py")
        proc = subprocess.run([sys.executable, script], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", errors="ignore")
        out = (proc.stdout or "") + (proc.stderr or "")
        self.q.put((out + "\n", "log"))

    def pump(self):
        try:
            while True:
                item, kind = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", item)
                    self.log.see("end")
                    last = [ln for ln in str(item).splitlines() if ln.strip()]
                    if last:
                        self.status.config(text=last[-1].strip()[:80], fg="#ffd479")
                elif kind == "done":
                    self.running = False
                    self.btn_run.config(state="normal", text="开始识别")
                    summary = (item or {}).get("summary") or {}
                    self.status.config(
                        text=f"识别完成：{summary.get('title') or '谱面'}，"
                             f"{summary.get('total_measures') or '?'} 小节。已打开网页。",
                        fg="#7ee2a8",
                    )
                    self.open_preview()
                elif kind == "warn":
                    self.running = False
                    self.btn_run.config(state="normal", text="开始识别")
                    self.status.config(text="这次没成功，看下面日志的最后几行。", fg="#ff8080")
        except queue.Empty:
            pass
        self.master.after(150, self.pump)

    # ---------------- 打开网页 ----------------
    def open_preview(self):
        if os.path.exists(PREVIEW_INDEX):
            webbrowser.open("file:///" + PREVIEW_INDEX.replace("\\", "/"))
        else:
            messagebox.showinfo("MaestroCore", "还没有生成网页，先跑一次识别。")

    def open_metronome(self):
        page = os.path.join(ROOT, "frontend_module", "_offline", "metronome.html")
        if os.path.exists(page):
            webbrowser.open("file:///" + page.replace("\\", "/"))
        else:
            messagebox.showinfo("MaestroCore", "还没有生成网页，先跑一次识别。")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
