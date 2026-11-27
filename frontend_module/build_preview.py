"""生成离线预览页面（双击就能看 UI，不需要跑服务）

用法：
    py frontend_module\\build_preview.py

产物：frontend_module/_offline/  下的 5 个 html + assets + theme.css
数据（主题、最近结果、历史、每条记录）全部内联成 window.MC_PREVIEW，
所以直接 file:// 打开也能看到真数据；提交类操作只会提示“离线预览不能提交”。
"""

import json
import pathlib
import re
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend_module"
OUT = FRONTEND / "_offline"
HISTORY = ROOT / "history"

PAGES = ["index.html", "history.html", "record.html", "metronome.html", "settings.html"]


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def collect():
    records = load(HISTORY / "index.json", [])
    if isinstance(records, dict):
        records = [records]
    records = [r for r in records if isinstance(r, dict)]

    results = {}
    for rec in records:
        no = str(rec.get("index", "")).zfill(2)
        payload = load(HISTORY / rec.get("folder", "") / "ai_result.json")
        if payload:
            summary = payload.get("summary") or {}
            # 小节数这类规模信息以结果里的为准，index.json 里那份可能是旧的
            if summary.get("total_measures"):
                rec["measures"] = summary["total_measures"]
            if summary.get("total_notes"):
                rec["notes"] = summary["total_notes"]
            payload.setdefault("meta", rec)
            results[no] = payload

    latest = load(ROOT / "ai_result.json") or {"empty": True}

    theme = {"theme": "默认", "unlocked": False}
    try:
        sys.path.insert(0, str(ROOT / "theme_module"))
        import redeem  # noqa: WPS433
        state = redeem.load_state()
        if state.get("unlocked"):
            theme = {"theme": state.get("theme") or "默认", "unlocked": True}
    except Exception:
        pass

    return {
        "theme": theme,
        "latest": latest,
        "history": records,
        "results": results,
        "sponsors": load(ROOT / "var" / "sponsors.json", {"sponsors": []}),
    }


def build(data):
    OUT.mkdir(exist_ok=True)
    if (OUT / "assets").exists():
        shutil.rmtree(OUT / "assets")
    shutil.copytree(FRONTEND / "assets", OUT / "assets")

    theme_css = ROOT / "theme_module" / "theme.css"
    if theme_css.exists():
        shutil.copyfile(theme_css, OUT / "theme.css")
    # 让预览里的六套主题自洽：:root 固定是「默认」，各主题靠 data-theme 切
    try:
        sys.path.insert(0, str(ROOT / "theme_module"))
        import palette  # noqa: E402

        (OUT / "theme.css").write_text(palette.to_css_all(), encoding="utf-8")
    except Exception as exc:  # 失败就退回服务启动时生成的那份
        print("主题 CSS 重生成失败，沿用现有 theme.css：", exc)

    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    inject = f'<script>window.MC_PREVIEW = {payload};</script>\n'

    # 版本号：VERSION 文件是唯一的真值，界面上每页都会显示
    version = "0.0.0"
    vfile = FRONTEND / "VERSION"
    if vfile.exists():
        version = vfile.read_text(encoding="utf-8").strip() or version
    built = time.strftime("%Y-%m-%d %H:%M")
    meta = {"version": version, "built": built, "channel": "preview"}
    inject += f'<script>window.MC_META = {json.dumps(meta, ensure_ascii=False)};</script>\n'
    stamp = str(int(max(p.stat().st_mtime for p in (OUT / "assets").iterdir())))
    baked_theme = (data.get("theme") or {}).get("theme") or "PCL \u9ed8\u8ba4"

    for name in PAGES:
        html = (FRONTEND / name).read_text(encoding="utf-8")
        html = html.replace('href="/theme.css"', 'href="theme.css"')
        html = html.replace('<script src="assets/island.js">', inject + '<script src="assets/island.js">')
        # 版本号最后加，否则上面的截图注入会匹配不上
        html = re.sub(
            r'(href|src)="(assets/[^"]+|theme\.css)"',
            lambda m: f'{m.group(1)}="{m.group(2)}?v={stamp}"',
            html,
        )
        # 在 <head> 里就把主题属性打上，避免切页时先闪一下别的主题色
        # 状态袋只用来“补这个页面读不到的键”，绝不用旧快照覆盖本机已有的新值，
        # 否则翻页时会被上一版的玻璃档/速度顶回去（三页三种效果就是这么来的）
        early = (
            '<script>try{'
            'var s=window.name||"",bag=null;'
            'if(s.indexOf("mc:{")===0){try{bag=JSON.parse(s.slice(3));}catch(e){}}'
            'var bagTs=bag?(parseInt(bag["mc.ts"]||"0",10)||0):0,'
            'locTs=0;'
            'try{locTs=parseInt(localStorage.getItem("mc.ts")||"0",10)||0}catch(e){}'
            # 状态袋只补本页读不到的键；真正最新的状态由地址栏 s= 参数负责（preview_state.js）
            'if(bag){for(var k in bag){if(k==="mc.ts")continue;'
            'try{if(localStorage.getItem(k)===null){localStorage.setItem(k,bag[k])}}catch(e){}}}'
            'var t=null;'
            'try{t=localStorage.getItem("mc.theme")}catch(e){}'
            'if(!t&&bag&&bag["mc.theme"]){t=bag["mc.theme"]}'
            'if(!t){t="' + baked_theme + '"}'
            'var qt=new URLSearchParams(location.search).get("t");'
            'if(qt){t=qt}'
            'window.MC_THEME=t;'
            'var d=document.documentElement;'
            'if(t==="PCL \u9ed8\u8ba4"){d.removeAttribute("data-theme")}'
            'else{d.setAttribute("data-theme",t)}'
            '}catch(e){}</script>\n'
        )
        html = html.replace("<head>", "<head>\n" + early, 1)
        html = html.replace('<script src="assets/island.js">',
                            inject + '<script src="assets/preview_state.js"></script>\n'
                            '<script src="assets/island.js">', 1)
        (OUT / name).write_text(html, encoding="utf-8")

    banner = (
        '<div style="position:fixed;left:12px;bottom:12px;z-index:99;'
        'background:rgba(0,0,0,.72);color:#fff;font-size:12px;padding:6px 10px;'
        'border-radius:8px">离线预览：数据是本地快照，提交按钮不可用</div>'
    )
    for name in PAGES:
        f = OUT / name
        text = f.read_text(encoding="utf-8")
        text = text.replace("</body>", banner + "\n</body>")
        if "preview_state.js" not in text:
            text = re.sub(r'<script src="assets/island\.js',
                          '<script src="assets/preview_state.js?v=%s"></script>\\n<script src="assets/island.js' % stamp,
                          text, count=1)
        f.write_text(text, encoding="utf-8")

    print(f"离线预览已生成：{OUT}")
    print(f"  记录 {len(data['history'])} 条，最近结果：{(data['latest'] or {}).get('summary', {}).get('title', '无')}")


if __name__ == "__main__":
    build(collect())

