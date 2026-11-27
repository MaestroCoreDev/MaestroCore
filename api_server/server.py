"""MaestroCore 本地网页服务（零依赖，只用 Python 标准库）

为什么不用 Flask：这台机器没装，而且机房/断网环境 pip 也拉不动。
标准库的 ThreadingHTTPServer 完全够用，一个文件就能跑。

启动：
    py api_server\\server.py            # 默认 http://127.0.0.1:8765/
    py api_server\\server.py --port 9000 --no-browser

接口：
    GET  /api/latest              最新一次结果（结果页/节拍器用）
    GET  /api/history             历史记录清单（history/index.json）
    GET  /api/result/<编号>        指定编号的完整结果
    GET  /api/theme               当前主题名 + 是否已解锁
    POST /api/redeem              兑换码 {"code": "...", "theme": "青暮"}
    POST /api/analyze             上传谱面跑流水线 {"images": [绝对路径...], "instrument": "", "tempo": "", "provider": "doubao"}
    GET  /api/job/<id>            查任务进度（log / done / error / result）
    GET  /theme.css               theme_module/theme.css（所有页面共用）

静态页面：frontend_module/ 下的 html/js/css
"""

import base64
import io
import json
import os
import pathlib
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend_module"
AI_DIR = ROOT / "ai_module"
THEME_DIR = ROOT / "theme_module"
HISTORY_DIR = ROOT / "history"

for p in (str(AI_DIR), str(THEME_DIR), str(ROOT / "main_app")):
    if p not in sys.path:
        sys.path.insert(0, p)

DEFAULT_PORT = 8765

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".musicxml": "application/xml; charset=utf-8",
}

# 后台任务表：job_id -> {"status","log","error","result"}
_jobs = {}
_jobs_lock = threading.Lock()

# 同一时间只跑一条流水线：homr 会 chdir 到自己的目录，两条并行必然互相踩
_pipeline_lock = threading.Lock()
_running_job = {"id": None}


class _JobLog(io.TextIOBase):
    """把流水线的 print 实时喂给 /api/job，页面才能看到「第 1/2 页」「已识别 40%」。"""

    def __init__(self, job_id, interval=0.6):
        self.job_id = job_id
        self.buf = io.StringIO()
        self.interval = interval
        self._last = 0.0

    def write(self, s):
        self.buf.write(s)
        now = time.time()
        if now - self._last >= self.interval:
            self._last = now
            self.flush()
        return len(s)

    def flush(self):
        with _jobs_lock:
            job = _jobs.get(self.job_id)
            if job is not None:
                job["log"] = self.buf.getvalue()

    def text(self):
        return self.buf.getvalue()



# ---------------------------------------------------------------- 数据读取
def _stamp():
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _meta():
    """版本号：frontend_module/VERSION 是唯一真值，构建时间是 VERSION 文件的修改时间。"""
    vfile = FRONTEND / "VERSION"
    version = "0.0.0"
    built = ""
    try:
        version = vfile.read_text(encoding="utf-8").strip() or version
        from datetime import datetime
        built = datetime.fromtimestamp(vfile.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        pass
    return {"version": version, "built": built, "channel": "server"}


# ---------------------------------------------------------------- 用量与限额
# 部署到服务器之后，Key 只在服务端存在，用户看不到；
# 但得防着有人写脚本刷，所以按“人 + 天”计数，超了直接拒。
USAGE_FILE = ROOT / "var" / "usage.json"
_usage_lock = threading.Lock()
DAILY_LIMIT = int(os.environ.get("MC_DAILY_LIMIT", "10"))


def _today():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _user_key(handler):
    uid = (handler.headers.get("X-MC-User") or "").strip()[:64]
    if uid:
        return "u_" + uid
    return "ip_" + (handler.client_address[0] if handler.client_address else "?")


def _usage_read():
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _usage_write(data):
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _quota_check(user_key):
    """返回 (已用次数, 剩余次数)"""
    with _usage_lock:
        data = _usage_read()
        day = data.get(_today()) or {}
        rec = day.get(user_key) or {}
        used = int(rec.get("count") or 0)
        return used, max(0, DAILY_LIMIT - used)


def _quota_add(user_key, tokens):
    with _usage_lock:
        data = _usage_read()
        day = data.setdefault(_today(), {})
        rec = day.setdefault(user_key, {"count": 0, "tokens": 0})
        rec["count"] = int(rec.get("count") or 0) + 1
        rec["tokens"] = int(rec.get("tokens") or 0) + int(tokens or 0)
        # 只留最近 60 天，别让文件无限长
        for old in sorted(data.keys())[:-60]:
            data.pop(old, None)
        _usage_write(data)


def _load_json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _index_records():
    data = _load_json(HISTORY_DIR / "index.json", [])
    if isinstance(data, dict):
        data = [data]
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _history_result(number):
    """按编号（01、02…）找那次结果。"""
    for rec in _index_records():
        if str(rec.get("index", "")).zfill(2) == str(number).zfill(2):
            folder = HISTORY_DIR / rec.get("folder", "")
            payload = _load_json(folder / "ai_result.json")
            if payload:
                payload.setdefault("meta", rec)
                return payload
    return None


def latest_payload():
    """最近一次结果：先看 history 里最新的，再看根目录兜底。"""
    records = _index_records()
    if records:
        newest = max(records, key=lambda r: r.get("index", 0))
        payload = _load_json(HISTORY_DIR / newest.get("folder", "") / "ai_result.json")
        if payload:
            payload.setdefault("meta", newest)
            return payload
    return _load_json(ROOT / "ai_result.json")


def theme_state():
    try:
        import redeem  # theme_module/redeem.py
        state = redeem.load_state()
    except Exception:  # noqa: BLE001
        return {"theme": "默认", "unlocked": False}
    theme = state.get("theme") or "默认"
    if not state.get("unlocked"):
        theme = "默认"
    return {"theme": theme, "unlocked": bool(state.get("unlocked"))}


# ---------------------------------------------------------------- 跑流水线
def _run_pipeline_job(job_id, payload):
    log = _JobLog(job_id)
    try:
        from run_pipeline import run_pipeline

        with redirect_stdout(log):
            result = run_pipeline(
                [os.path.abspath(p) for p in payload.get("images", [])] or None,
                tempo_spec=payload.get("tempo") or None,
                instrument=payload.get("instrument") or None,
                provider=payload.get("provider") or "doubao",
            )
        log.flush()
        if not result:
            result = latest_payload()
        meta = _meta()
        log.write(f"\n[完成] 版本 {meta.get('version')}，结果已更新。\n")
        log.flush()
        with _jobs_lock:
            _jobs[job_id].update({"status": "done", "result": result})
    except Exception as exc:  # noqa: BLE001
        log.write(f"\n[失败] {exc}\n")
        log.flush()
        with _jobs_lock:
            _jobs[job_id].update({
                "status": "error",
                "error": f"{exc}",
                "trace": traceback.format_exc()[-1200:],
            })
    finally:
        _running_job["id"] = None
        _pipeline_lock.release()
        # 只留最近 20 个任务，免得内存里越堆越多
        with _jobs_lock:
            for old in sorted(_jobs.keys())[:-20]:
                _jobs.pop(old, None)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "MaestroCore/1.0"

    def log_message(self, fmt, *args):  # 静默访问日志，终端只留我们自己的提示
        pass

    # ---- 小工具 ----
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, data)

    def _body_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def _file(self, path, ctype=None):
        try:
            data = pathlib.Path(path).read_bytes()
        except OSError:
            return False
        self._send(200, data, ctype or MIME.get(path.suffix.lower(), "application/octet-stream"))
        return True

    # ---- 路由 ----
    def do_GET(self):
        route = urlparse(self.path).path
        route = unquote(route)

        if route in ("/", "/index.html"):
            return self._file(FRONTEND / "index.html")
        if route == "/theme.css":
            return self._file(THEME_DIR / "theme.css", "text/css; charset=utf-8")
        if route == "/api/theme":
            return self._json(theme_state())
        if route == "/api/meta":
            return self._json(_meta())
        if route == "/api/health":
            return self._json({
                "ok": True,
                "version": _meta().get("version"),
                "busy": _running_job["id"] or "",
                "jobs": len(_jobs),
            })
        if route == "/api/usage":
            uk = _user_key(self)
            used, left = _quota_check(uk)
            return self._json({"used": used, "left": left, "limit": DAILY_LIMIT, "today": _today()})
        if route == "/api/sponsors":
            data = _load_json(ROOT / "var" / "sponsors.json", {"sponsors": []})
            return self._json(data or {"sponsors": []})
        if route == "/api/latest":
            return self._json(latest_payload() or {"empty": True})
        if route == "/api/history":
            return self._json(_index_records())
        if route.startswith("/api/result/"):
            number = route.rsplit("/", 1)[-1]
            payload = _history_result(number)
            return self._json(payload) if payload else self._json({"error": "没有这条记录"}, 404)
        if route.startswith("/api/job/"):
            job_id = route.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            return self._json(job) if job else self._json({"error": "任务不存在"}, 404)

        if route.startswith("/assets/"):
            return self._file(FRONTEND / route.lstrip("/"))

        # 其它 .html 直接给文件
        if route.endswith(".html"):
            target = FRONTEND / route.lstrip("/")
            if target.exists():
                return self._file(target)
        self._json({"error": "not found", "path": route}, 404)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        route = urlparse(self.path).path

        if route == "/api/analyze":
            payload = self._body_json()

            # 网页上传的图片是 base64，先落到 temp_debug/uploads/<时间戳>/ 里
            images = []
            for idx, item in enumerate(payload.get("images_data") or [], start=1):
                data = (item.get("data") or "").split(",", 1)[-1]
                name = os.path.basename(item.get("name") or f"page{idx}.png")
                if not data:
                    continue
                folder = ROOT / "temp_debug" / "uploads" / _stamp()
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / name
                try:
                    target.write_bytes(base64.b64decode(data))
                except (ValueError, OSError) as exc:
                    return self._json({"error": f"图片解码失败：{exc}"}, 400)
                images.append(str(target))

            images += [p for p in (payload.get("images") or []) if os.path.exists(p)]
            if (payload.get("images_data") or payload.get("images")) and not images:
                return self._json({"error": "给的图片都不可用"}, 400)

            # 上一单还没跑完就别开第二单：homr 会在进程里 chdir，两个一起跑必出错图
            if not _pipeline_lock.acquire(blocking=False):
                return self._json({
                    "error": "上一份谱子还在识别，等它跑完再传（大约 1–3 分钟）。",
                    "busy": _running_job["id"],
                }, 409)

            job_id = uuid.uuid4().hex[:8]
            _running_job["id"] = job_id
            with _jobs_lock:
                _jobs[job_id] = {"status": "running", "log": "", "error": None, "result": None}
            threading.Thread(target=_run_pipeline_job, args=(job_id, payload), daemon=True).start()
            return self._json({"job": job_id})

        if route == "/api/chat":
            payload = self._body_json()
            user = (payload.get("user") or "").strip()
            system = (payload.get("system") or "你是乐队指导老师，说话短、具体、能直接照着练。用中文。").strip()
            provider = (payload.get("provider") or "deepseek").strip().lower()
            if not user:
                return self._json({"error": "没有内容"}, 400)

            uk = _user_key(self)
            used, left = _quota_check(uk)
            if left <= 0:
                return self._json({
                    "error": f"今天的免费次数用完了（每天 {DAILY_LIMIT} 次），明天再来；赞助后提升额度。",
                    "used": used, "left": 0, "limit": DAILY_LIMIT,
                }, 429)

            try:
                from providers import ask_model
                text = ask_model(provider, system, user)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": f"模型调用失败：{exc}"}, 502)

            # 粗略记账：模型没回 usage，就按字数估（中文约 1.6 字/token）
            tokens = int((len(user) + len(text)) / 1.6)
            _quota_add(uk, tokens)
            used, left = _quota_check(uk)
            return self._json({"text": text, "used": used, "left": left, "limit": DAILY_LIMIT})

        if route == "/api/usage":
            uk = _user_key(self)
            used, left = _quota_check(uk)
            return self._json({"used": used, "left": left, "limit": DAILY_LIMIT, "today": _today()})

        if route == "/api/redeem":
            payload = self._body_json()
            code = (payload.get("code") or "").strip()
            theme = payload.get("theme") or None
            try:
                import redeem
                ok, msg = redeem.unlock(code, theme)
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "msg": f"兑换失败：{exc}"}, 500)
            state = theme_state()
            return self._json({"ok": ok, "msg": msg, **state})

        if route == "/api/theme":
            # 仅临时切换（未解锁时会被 palette 挡回默认）
            payload = self._body_json()
            try:
                import redeem
                state = redeem.load_state()
                name = payload.get("theme")
                if state.get("unlocked") and name:
                    state["theme"] = name
                    redeem.save_state(state)
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": f"{exc}"}, 500)
            return self._json(theme_state())

        self._json({"error": "not found"}, 404)


def _lan_ip():
    """猜一下本机局域网 IP，方便手机/别的设备连同一个服务。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def _self_check(port, timeout=3.0):
    """起完服务自己连一下，好让终端直接告诉你「浏览器应该能打开」。"""
    for host in ("127.0.0.1", "localhost"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        try:
            s.connect((host, port))
            return True
        except OSError:
            continue
        finally:
            s.close()
    return False


def main(argv):
    port = DEFAULT_PORT
    open_browser = True
    host = "127.0.0.1"
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if "--host" in argv:
        host = argv[argv.index("--host") + 1]
    if "--no-browser" in argv:
        open_browser = False

    # 每次启动把 theme.css 重新按 palette 生成一遍，避免和代码里的颜色脱节
    try:
        import palette
        palette.write_css_file()
    except Exception as exc:  # noqa: BLE001
        print(f"[主题] theme.css 生成失败（不影响启动）：{exc}")

    if not (FRONTEND / "index.html").exists():
        print("[警告] frontend_module/index.html 还不存在，页面会 404。")

    addr = (host, port)
    httpd = None
    last_err = None
    for offset in range(0, 11):  # 端口被占就往后找一个空的，避免「地址已在使用」
        try:
            httpd = ThreadingHTTPServer((addr[0], port + offset), Handler)
            port = port + offset
            break
        except OSError as exc:
            last_err = exc
            continue
    if httpd is None:
        print(f"[错误] 端口 {DEFAULT_PORT} 起不来：{last_err}")
        print("  多半是上一次的黑窗口还开着，关掉再双击。")
        return
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown_host}:{port}/"
    print("========================================")
    print("        MaestroCore 本地服务已启动      ")
    print("========================================")
    print(f"  地址：{url}")
    if host in ("0.0.0.0", "::"):
        lan = _lan_ip()
        if lan:
            print(f"  同一 Wi-Fi 的手机/平板：http://{lan}:{port}/")
    print("  关掉这个窗口（或按 Ctrl+C）服务就停。")
    print("----------------------------------------")
    if not _self_check(port):
        print("[自检] 本机连不上自己的端口：多半是安全软件/网络过滤拦了 127.0.0.1。")
        print("       浏览器如果打不开，按这个顺序试：")
        print("       1) 关掉电脑管家/360 的「网络防护」，或把 python.exe 加进信任；")
        print("       2) 用管理员身份打开命令行，执行：netsh winsock reset  然后重启电脑；")
        print("       3) 用手机连同一个 Wi-Fi，打开局域网地址（见上方）。")
        print("       4) 实在连不上，就别等网页了：双击「打开网页预览.bat」看离线界面，")
        print("          识别用「识别谱面.bat」（桌面助手跑完会自动重建离线网页）。")
        print("----------------------------------------")
    else:
        print("[自检] 端口连通正常。")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")


if __name__ == "__main__":
    main(sys.argv[1:])

