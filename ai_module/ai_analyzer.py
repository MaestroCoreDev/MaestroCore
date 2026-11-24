"""MaestroCore 模块 3：AI 谱面讲解引擎（豆包已接好，DeepSeek 留口子）

流程：Homr 的 MusicXML -> 结构化摘要 -> 模型通道 -> 练琴方案(JSON + 人话版)

直接跑（自动找项目里最新的 .musicxml）：
    python ai_module/ai_analyzer.py
指定文件、指定模型：
    python ai_module/ai_analyzer.py test_rectified.musicxml doubao
    python ai_module/ai_analyzer.py test_rectified.musicxml deepseek
"""

import glob
import json
import os
import sys

sys.dont_write_bytecode = True  # 不生成 __pycache__

AI_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(AI_DIR)
if AI_DIR not in sys.path:
    sys.path.insert(0, AI_DIR)

from maestro_config import ARK_MODEL, DEEPSEEK_MODEL  # noqa: E402
from providers import PROVIDERS, ask_model  # noqa: E402
from xml_summary import apply_tempo_override, summarize_musicxml  # noqa: E402

SYSTEM_PROMPT = (
    "你是 MaestroCore 的乐谱辅导老师，服务对象是学乐器的学生。"
    "你只依据用户提供的乐谱结构化数据作答，数据里没有的内容不要编造。"
    "如果这是乐团/室内乐的总谱而不是独奏曲，要站在指定乐器的声部角度讲，"
    "重点指出该声部的独奏段、重要旋律段和与乐队配合的关键点。"
    "必须返回纯 JSON，不要 markdown 代码块，不要任何多余解释。"
)

USER_TEMPLATE = """这是一份乐谱的机器识别摘要，请据此制定练琴方案。

演奏者身份：{instrument_note}

谱面 OCR 文字（标题、作者、编者等，可能有识别错误）：
{score_text}

摘要：
{summary}

严格按下面 JSON 结构返回，字段名不要改：
{{
  "level": "入门 / 初级 / 中级 / 中高级 / 高级",
  "overview": "两三句话概括这首曲子练什么、难点在哪",
  "background": "乐曲风格与背景，简短；不确定就写保守推测并注明是推测",
  "piece_guess": {{
    "name": "据标题/作者推断的曲名，查不到就写原文标题",
    "composer": "作曲家或编者；不知道就写「未知」，不许编",
    "confidence": "确定 / 较可能 / 推测 / 无法判断",
    "reason": "凭什么这么判断，一句话"
  }},
  "ensemble_role": "这份谱里演奏者声部的角色：独奏 / 主力旋律 / 伴奏 / 齐奏 / 无法判断；说明依据",
  "solo_highlights": [
    {{"measures": "5-9", "type": "SOLO / 重要旋律 / 华彩段 / 与乐队呼应", "note": "这段要突出什么、气息或把位怎么处理"}}
  ],
  "practice_blocks": [
    {{"measures": "1-8", "tempo_bpm": 70, "focus": "这一块练什么", "tips": "怎么练，要具体可操作"}}
  ],
  "hard_spots": [
    {{"measures": "9-12", "why": "难点原因", "how": "分解练法"}}
  ],
  "tempo_notes": "速度变化处怎么处理，先慢到什么速度再回原速",
  "metronome_plan": [
    {{"start_measure": 1, "end_measure": 8, "bpm": 70, "beats": 4, "beat_type": 4}}
  ]
}}

硬要求：
1. practice_blocks 按由易到难、由慢到快排序；小节号必须来自摘要里真实存在的小节，不许超过第 {total_measures} 小节；
2. 慢练速度取原速的 60%~75%，取整数；
3. metronome_plan 从第 1 小节开始、到第 {total_measures} 小节结束，分段首尾相接、不重叠；
4. 如果谱面数据分不出是不是独奏段（例如只有单声部旋律、没有 SOLO 标记），
   solo_highlights 就给最像主旋律/最难上手的段落，并在 note 里写「依据旋律位置推测，需对谱确认」，不许硬说成 SOLO；
5. 要结合「谱面 OCR 文字」里的标题、作者、编者、乐器去推断是哪一首曲子：
   能对上是名曲的写「确定」或「较可能」，只有风格线索的写「推测」，查不到就写「无法判断」；
   composer 不知道就写「未知」，绝不编造作曲家和作品号；OCR 可能把字认错，判断时说明依据在哪个词上；
6. 中文作答，句子短，能直接照着练。"""


def _instrument_note(instrument):
    name = (instrument or "").strip()
    if not name:
        return "未指定乐器，按谱面声部通用讲解"
    return (
        f"{name}演奏者。请站在{name}声部角度讲解："
        f"标出{name}的独奏段、重要旋律段、与乐队/钢琴配合的关键点，"
        f"技巧提示用{name}的说法（气息、把位、音准、音色）"
    )


def find_musicxml(app_root=APP_ROOT):
    """自动找 Homr 刚导出（最新）的 MusicXML。"""
    candidates = glob.glob(os.path.join(app_root, "*.musicxml"))
    if not candidates:
        for path in glob.glob(os.path.join(app_root, "**", "*.musicxml"), recursive=True):
            if os.sep + "homr-main" + os.sep in path:
                continue  # Homr 自带的示例文件不算
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _strip_fence(text):
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return text.strip()


def build_summary_payload(summary):
    """给模型的精简版摘要（去掉逐小节明细，只留轮廓）。"""
    payload = {k: v for k, v in summary.items() if k != "measures"}
    payload["measures_outline"] = [
        {k: m[k] for k in ("measure", "notes", "shortest_note", "bpm") if k in m}
        for m in summary.get("measures", [])
    ]
    return payload


def _try_repair_json(text):
    """模型输出被截断时，尽力把括号/引号补全，救回前面已经完整的字段。"""
    depth = []
    in_str = False
    escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth.append("}" if ch == "{" else "]")
        elif ch in "}]" and depth:
            depth.pop()

    fixed = text.rstrip().rstrip(",")
    if in_str:
        fixed += '"'
    # 截断可能停在 “键:” 后面，补个 null 让它合法
    if fixed.endswith(":"):
        fixed += "null"
    fixed += "".join(reversed(depth))
    fixed = fixed.replace(",}", "}").replace(",]", "]")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def ask_with_provider(provider, summary, instrument=None, score_text=None):
    """选通道 -> 拼提示词 -> 拿回答 -> 尽力解析 JSON（截断会自动重试一次）。"""
    text_lines = [t["text"] for t in (score_text or [])]
    user = USER_TEMPLATE.format(
        summary=json.dumps(build_summary_payload(summary), ensure_ascii=False),
        total_measures=summary["total_measures"],
        instrument_note=_instrument_note(instrument),
        score_text=" / ".join(text_lines) if text_lines else "（没读到文字）",
    )

    last_raw = ""
    for attempt in (1, 2):
        raw = ask_model(provider, SYSTEM_PROMPT, user)
        last_raw = raw
        cleaned = _strip_fence(raw)
        try:
            return json.loads(cleaned), raw
        except json.JSONDecodeError:
            repaired = _try_repair_json(cleaned)
            if repaired and isinstance(repaired, dict) and len(repaired) >= 3:
                print("[警告] 模型输出不完整，已补全括号救回可用字段（建议复核一次）")
                return repaired, raw
            if attempt == 1:
                print("[重试] 模型没返回合法 JSON，重新请求一次...")

    return {"raw": last_raw, "parse_error": "模型未返回合法 JSON，已保留原文"}, last_raw


def _normalize(result, summary):
    """补齐缺字段，并用摘要兜底节拍器分段，保证下游不因缺键报错。"""
    for key, default in (
        ("level", "未评定"), ("overview", ""), ("background", ""),
        ("ensemble_role", "无法判断"), ("solo_highlights", []),
        ("piece_guess", {}),
        ("practice_blocks", []), ("hard_spots", []), ("tempo_notes", ""),
    ):
        result.setdefault(key, default)

    plan = result.get("metronome_plan") or []
    if not plan:
        total = summary["total_measures"]
        tempos = summary["tempo_map"]
        times = summary["time_map"]
        for i, t in enumerate(tempos):
            start = t["measure"]
            end = tempos[i + 1]["measure"] - 1 if i + 1 < len(tempos) else total
            beats, beat_type = 4, 4
            for ts in times:
                if ts["measure"] <= start:
                    beats, beat_type = ts["beats"], ts["beat_type"]
            plan.append({"start_measure": start, "end_measure": end,
                         "bpm": max(40, int(t["bpm"] * 0.7)),
                         "beats": beats, "beat_type": beat_type})
        result["metronome_plan"] = plan

    for item in result["metronome_plan"]:
        item.setdefault("beats", 4)
        item.setdefault("beat_type", 4)
        item["bpm"] = int(item.get("bpm", 60))

    # 练琴顺序可以乱，节拍器必须按小节从头到尾排
    result["metronome_plan"].sort(key=lambda p: p.get("start_measure", 1))
    return result


def analyze_music_with_ai(xml_path=None, model_name="doubao", save=True,
                          tempo_spec=None, image_path=None, instrument=None):
    """Homr 出了 XML 就能直接跑。返回 {source_file, summary, ai}。

    tempo_spec：人工指定速度，格式 "1:96,13:120"，优先级最高；
    image_path：给了就自动 OCR 谱面上的速度标记（Largo ♩=96 这类），不用手填；
    instrument：演奏乐器（如 长号）。乐队总谱会按这个声部讲独奏段和重点。
    """
    provider = (model_name or "doubao").lower()
    print("\n>>> [模块 3] AI 谱面讲解引擎")
    print(f"    通道：{provider}｜模型：{ARK_MODEL if provider != 'deepseek' else DEEPSEEK_MODEL}")

    if provider not in PROVIDERS:
        print(f"[中断] 不认识的模型通道：{provider}，可选 {', '.join(PROVIDERS)}")
        return None

    if xml_path is None:
        xml_path = find_musicxml()
    if not xml_path or not os.path.exists(xml_path):
        print("[中断] 项目里没找到 Homr 导出的 .musicxml，先把流水线跑到第二步。")
        return None
    print(f"    谱面文件：{xml_path}")

    try:
        summary = summarize_musicxml(xml_path)
    except Exception as exc:
        print(f"[中断] MusicXML 解析失败：{exc}")
        return None

    # 本次运行的副产物（放大图、页眉裁剪、OCR 原文）统一进 temp_debug
    debug_owner = False
    try:
        import debug_store
        debug_owner = debug_store.path() is None   # 流水线已开会话就复用它
        debug_store.begin_session(summary.get("title") or "")
    except Exception:  # noqa: BLE001
        debug_store = None
        debug_owner = False

    if tempo_spec:
        try:
            summary = apply_tempo_override(summary, tempo_spec)
            print("    [速度] 人工指定：" + "；".join(
                f"第 {t['measure']} 小节起 {t['bpm']} BPM" for t in summary["tempo_map"]))
        except ValueError as exc:
            print(f"[中断] {exc}")
            if debug_owner and debug_store:
                debug_store.end_session()
            return None
    elif image_path and os.path.exists(image_path):
        try:
            from tempo_ocr import detect_tempos, tempos_to_spec
            tempos = detect_tempos(image_path, summary)
            if tempos:
                summary = apply_tempo_override(summary, tempos_to_spec(tempos))
                summary["tempo_ocr"] = tempos
                print("    [速度] 从谱面自动识别：" + "；".join(
                    f"第 {t['measure']} 小节起 {int(t['bpm'])} BPM（{t['text']}，{t['source']}）"
                    for t in tempos))
            else:
                print("    [速度] 谱面没识别到速度标记，沿用 homr 默认 120")
        except Exception as exc:
            print(f"    [速度] 自动识别跳过：{exc}")

    print(f"    {summary['title']}｜{summary['total_measures']} 小节｜"
          f"{summary['total_notes']} 音符｜约 {summary['estimated_duration_sec']} 秒")

    print(f"    演奏乐器：{instrument or '未指定'}")

    score_text = None
    if image_path and os.path.exists(image_path):
        try:
            from tempo_ocr import page_text
            score_text = page_text(image_path)
            if score_text:
                print("    [页眉文字] " + " / ".join(t["text"] for t in score_text))
        except Exception as exc:
            print(f"    [页眉文字] 识别跳过：{exc}")

    try:
        from progress import Ticker
        with Ticker("正在思考", "已思考"):
            result, _raw = ask_with_provider(provider, summary, instrument=instrument,
                                             score_text=score_text)
    except RuntimeError as exc:
        print(f"[中断] {exc}")
        if debug_owner and debug_store:
            debug_store.end_session()
        return None

    result = _normalize(result, summary)
    payload = {
        "source_file": os.path.basename(xml_path),
        "provider": provider,
        "instrument": instrument or "",
        "score_text": [t["text"] for t in (score_text or [])],
        "summary": summary,
        "ai": result,
    }

    print("\n[AI 讲解]")
    print(f"    难度：{result['level']}")
    guess = result.get("piece_guess") or {}
    if guess.get("name"):
        print(f"    曲目推测：{guess.get('name')}｜{guess.get('composer', '未知')}"
              f"｜把握度：{guess.get('confidence', '')}（{guess.get('reason', '')}）")
    if result["overview"]:
        print(f"    概览：{result['overview']}")
    if result["background"]:
        print(f"    背景：{result['background']}")
    if result["ensemble_role"]:
        print(f"    声部角色：{result['ensemble_role']}")
    for solo in result["solo_highlights"]:
        print(f"    ★ {solo.get('type', '重点段')} {solo.get('measures')}｜{solo.get('note')}")
    for blk in result["practice_blocks"]:
        print(f"    第 {blk.get('measures')} 小节｜{blk.get('tempo_bpm')} BPM｜"
              f"{blk.get('focus')}｜{blk.get('tips')}")
    for spot in result["hard_spots"]:
        print(f"    难点 {spot.get('measures')}：{spot.get('why')} -> {spot.get('how')}")
    if result["tempo_notes"]:
        print(f"    速度：{result['tempo_notes']}")
    print("    节拍器分段：" + "；".join(
        f"{p['start_measure']}-{p['end_measure']} 小节 {p['bpm']}BPM {p['beats']}/{p['beat_type']}"
        for p in result["metronome_plan"]))

    if save:
        # 先归档到 history/（编号 + 曲名），再把根目录的 ai_result.json 写成最新指针
        folder = None
        try:
            from history_store import save_record
            folder = save_record(payload, xml_path)
            print(f"[归档] 已存入历史记录：{folder}（曲名：{payload['summary']['title']}）")
        except Exception as exc:
            print(f"[归档] 历史记录保存失败（不影响本次结果）：{exc}")

        out = os.path.join(APP_ROOT, "ai_result.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"[保存] 最新结果：{out}")

        try:
            if debug_store:
                debug_store.note("ai_level", result.get("level"))
                debug_store.note("piece_guess", result.get("piece_guess"))
                if debug_owner:          # 流水线开的会话由流水线自己收尾
                    debug_store.end_session()
        except Exception:  # noqa: BLE001
            pass
    return payload


if __name__ == "__main__":
    args = sys.argv[1:]
    options = {"--tempo": None, "--image": None, "--instrument": None}
    positional = []
    i = 0
    while i < len(args):
        if args[i] in options and i + 1 < len(args):
            options[args[i]] = args[i + 1]
            i += 2
            continue
        positional.append(args[i])
        i += 1

    target = positional[0] if positional else None
    model = positional[1] if len(positional) > 1 else "doubao"
    analyze_music_with_ai(target, model, tempo_spec=options["--tempo"],
                          image_path=options["--image"], instrument=options["--instrument"])
    print("\n========================================")
    print("           MaestroCore 运行结束         ")
    print("========================================")
