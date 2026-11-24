"""MaestroCore / ai_module 秒表提示

识别、思考这类要等几秒到几十秒的环节，终端上给个会自己跳秒的提示：

    正在识别中 已识别 12 秒
    正在思考 已思考 8 秒

在真终端里只在同一行改数字（回到行首、擦掉本行、重写），不产生新行；
如果输出被重定向到文件/日志（不是终端），就不逐秒刷，只留最后一行。

用法：
    from progress import Ticker
    with Ticker("正在思考", "已思考"):
        ask_model(...)
"""

import sys
import threading
import time

sys.dont_write_bytecode = True

INDENT = "    "
CLEAR_LINE = "\r\x1b[2K"      # 回到行首 + 擦掉整行


class Ticker:
    """在终端同一行上每秒刷新一次的计时提示。"""

    def __init__(self, doing, done, interval=1.0):
        self.doing = doing
        self.done = done
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._seconds = 0
        self._drawn = False
        self._tty = sys.stdout.isatty()

    def _text(self):
        return f"{INDENT}{self.doing} {self.done} {self._seconds} 秒"

    def _loop(self):
        start = time.perf_counter()
        last_report = 0
        while not self._stop.is_set():
            self._seconds = int(time.perf_counter() - start)
            if self._tty:
                self._draw()
            elif self._seconds and self._seconds % 10 == 0 and self._seconds != last_report:
                # 被重定向时每 10 秒留一句，免得看起来卡死
                last_report = self._seconds
                sys.stdout.write(self._text() + "\n")
                sys.stdout.flush()
            self._stop.wait(self.interval)

    def _draw(self):
        sys.stdout.write(CLEAR_LINE + self._text())
        sys.stdout.flush()
        self._drawn = True

    def start(self):
        self._stop.clear()
        self._seconds = 0
        if self._tty:                     # 先把这一行画出来，之后只改数字
            self._draw()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _final_text(self):
        return f"{INDENT}已用时 {self._seconds} 秒"

    def stop(self, keep_line=True):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)

        if not keep_line:
            if self._drawn:
                sys.stdout.write(CLEAR_LINE)
                sys.stdout.flush()
            return

        if self._tty:
            sys.stdout.write(CLEAR_LINE + self._final_text() + "\n")
        else:
            # 重定向场景：整个过程只留一行结果，不刷屏
            sys.stdout.write(self._final_text() + "\n")
        sys.stdout.flush()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
