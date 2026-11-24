"""把 Homr 导出的 MusicXML 压缩成「结构化乐谱摘要」。

大模型不吃整段 XML（又长又乱、还容易幻觉），
我们先把真正有用的东西抽出来：小节、拍号、速度、难度热点。
"""

import re
import xml.etree.ElementTree as ET
from collections import Counter

SHORT_TYPES = ("eighth", "16th", "32nd", "64th")


def _measure_imgpos(xml_path):
    """从 homr 写在 XML 注释里的 imgpos 取每小节第一个音符的坐标。"""
    try:
        text = open(xml_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return {}

    out = {}
    chunks = re.split(r'<measure number="(\d+)">', text)
    for i in range(1, len(chunks), 2):
        num = int(chunks[i])
        m = re.search(r"imgpos: (\d+), (\d+)", chunks[i + 1])
        if m:
            out[num] = [int(m.group(1)), int(m.group(2))]
    return out


def _int(text, default=0):
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def _pitch_semitone(step, octave, alter=0):
    order = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return order.get(step, 0) + 12 * octave + int(alter)


def summarize_musicxml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    title = root.findtext(".//work/work-title") or root.findtext(".//movement-title") or "未命名乐曲"
    part = root.find(".//part")
    if part is None:
        raise ValueError("这个 MusicXML 里没有 <part>，不是有效的谱面文件")

    part_name = root.findtext(".//score-part/part-name") or "未知声部"

    divisions = 1
    tempos, times, keys, clefs = [], [], [], []
    dynamics = Counter()
    measures_info = []
    total_notes = 0
    total_quarters = 0.0
    total_seconds = 0.0

    for measure in part.findall("measure"):
        num = _int(measure.get("number"), len(measures_info) + 1)

        # 属性：divisions / 拍号 / 调号 / 谱号
        for attr in measure.findall("attributes"):
            div = attr.findtext("divisions")
            if div:
                try:
                    divisions = int(div)
                except ValueError:
                    pass
            time = attr.find("time")
            if time is not None:
                beats = _int(time.findtext("beats"), 4)
                beat_type = _int(time.findtext("beat-type"), 4)
                if not times or times[-1]["beats"] != beats or times[-1]["beat_type"] != beat_type:
                    times.append({"measure": num, "beats": beats, "beat_type": beat_type})
            key = attr.find("key")
            if key is not None:
                fifths = _int(key.findtext("fifths"), 0)
                if not keys or keys[-1]["fifths"] != fifths:
                    keys.append({"measure": num, "fifths": fifths})
            clef = attr.find("clef")
            if clef is not None:
                sign = clef.findtext("sign") or "G"
                line = clef.findtext("line") or "2"
                label = f"{sign}{line}"
                if not clefs or clefs[-1]["clef"] != label:
                    clefs.append({"measure": num, "clef": label})

        # 速度：可能挂在小节或 direction 上
        bpm_here = None
        tempo = measure.get("tempo")
        if tempo is None:
            sound = measure.find("sound")
            tempo = sound.get("tempo") if sound is not None else None
        if tempo is None:
            for direction in measure.findall("direction"):
                s = direction.find("sound")
                if s is not None and s.get("tempo"):
                    tempo = s.get("tempo")
                    break
        if tempo:
            try:
                bpm_here = float(tempo)
                if not tempos or abs(tempos[-1]["bpm"] - bpm_here) > 0.01:
                    tempos.append({"measure": num, "bpm": round(bpm_here, 1)})
            except ValueError:
                pass

        # 音符
        note_count = 0
        measure_quarters = 0.0
        shortest = None
        longest_leap = 0
        accidentals = 0
        slurs = 0
        last_pitch = None
        for note in measure.findall("note"):
            if note.find("rest") is not None:
                measure_quarters += _int(note.findtext("duration"), 0) / divisions
                continue
            dur = _int(note.findtext("duration"), 0)
            measure_quarters += dur / divisions
            ntype = note.findtext("type")
            if ntype in SHORT_TYPES:
                if shortest is None or SHORT_TYPES.index(ntype) > SHORT_TYPES.index(shortest):
                    shortest = ntype
            pitch = note.find("pitch")
            if pitch is not None:
                note_count += 1
                row = pitch.find("alter")
                alter = _int(row.text, 0) if row is not None else 0
                if alter:
                    accidentals += 1
                cur = _pitch_semitone(pitch.findtext("step", "C"), _int(pitch.findtext("octave"), 0), alter)
                if last_pitch is not None and note.find("chord") is None:
                    longest_leap = max(longest_leap, abs(cur - last_pitch))
                last_pitch = cur
            notations = note.find("notations")
            if notations is not None:
                if notations.find("slur") is not None:
                    slurs += 1

        for d in measure.findall(".//direction-type/dynamics"):
            for child in list(d):
                dynamics[child.tag] += 1

        bpm_use = bpm_here or (tempos[-1]["bpm"] if tempos else 120.0)
        measure_seconds = measure_quarters * 60.0 / bpm_use if bpm_use else 0
        total_notes += note_count
        total_quarters += measure_quarters
        total_seconds += measure_seconds

        measures_info.append({
            "measure": num,
            "notes": note_count,
            "shortest_note": shortest,
            "quarters": round(measure_quarters, 2),
            "seconds": round(measure_seconds, 1),
            "max_leap": longest_leap,
            "accidentals": accidentals,
            "slurs": slurs,
            "bpm": round(bpm_use, 1),
        })

    if not measures_info:
        raise ValueError("这个 MusicXML 一个小节都没有解析出来")

    # 难度热点：音符密度高 / 出现三十二分音符 / 大跳 / 大量临时记号
    avg_notes = sum(m["notes"] for m in measures_info) / len(measures_info)
    scored = []
    for m in measures_info:
        score = 0
        if avg_notes > 0:
            score += max(0.0, m["notes"] / avg_notes - 1) * 2
        if m["shortest_note"] == "32nd":
            score += 3
        elif m["shortest_note"] == "16th":
            score += 1
        if m["max_leap"] >= 7:
            score += 2
        if m["accidentals"] >= 3:
            score += 1
        if score > 0:
            scored.append((round(score, 2), m))

    hard = [
        {
            "measure": m["measure"],
            "notes": m["notes"],
            "shortest_note": m["shortest_note"],
            "max_leap": m["max_leap"],
            "accidentals": m["accidentals"],
            "bpm": m["bpm"],
        }
        for score, m in sorted(scored, key=lambda x: -x[0])[:8]
    ]

    # 给每小节补上图像坐标，速度标记要靠它落到具体小节
    imgpos = _measure_imgpos(xml_path)
    for m in measures_info:
        if m["measure"] in imgpos:
            m["imgpos"] = imgpos[m["measure"]]

    summary = {
        "title": title,
        "part": part_name,
        "total_measures": len(measures_info),
        "total_notes": total_notes,
        "avg_notes_per_measure": round(avg_notes, 1),
        "tempo_map": tempos or [{"measure": 1, "bpm": 120.0}],
        "time_map": times or [{"measure": 1, "beats": 4, "beat_type": 4}],
        "key_map": keys or [{"measure": 1, "fifths": 0}],
        "clefs": clefs or [{"measure": 1, "clef": "G2"}],
        "dynamics_used": [f"{k}(×{v})" for k, v in dynamics.most_common()],
        "estimated_duration_sec": round(total_seconds, 1),
        "hard_measures": hard,
        "measures": measures_info,
    }
    return summary


def parse_tempo_spec(spec):
    """把 "1:96,13:120" 解析成 [{'measure':1,'bpm':96}, {'measure':13,'bpm':120}]。

    会做基本校验：小节号从 1 起、速度在 30–300 之间、同一小节不许写两次。
    """
    tempos = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"速度格式不对：{part}，应该是 小节号:速度，例如 13:120")
        m, bpm = part.split(":", 1)
        try:
            measure = int(m.strip())
            value = round(float(bpm.strip()), 1)
        except ValueError:
            raise ValueError(f"速度格式不对：{part}，小节号和速度都要是数字") from None
        if measure < 1:
            raise ValueError(f"小节号要从 1 开始：{part}")
        if not 30 <= value <= 300:
            raise ValueError(f"速度超出范围（30–300）：{part}")
        if any(t["measure"] == measure for t in tempos):
            raise ValueError(f"同一小节写了两次速度：{measure}")
        tempos.append({"measure": measure, "bpm": value})
    if not tempos:
        raise ValueError("速度参数是空的")
    tempos.sort(key=lambda t: t["measure"])
    return tempos


def apply_tempo_override(summary, spec):
    """谱面上印的速度 homr 认不出来，这里用人工给的速度覆盖。"""
    tempos = parse_tempo_spec(spec)

    # 人工只写了后半段（比如只给 13:120），前面那段沿用谱面原有速度，不能一律套第一个值
    if tempos[0]["measure"] > 1:
        base = (summary.get("tempo_map") or [{"bpm": 120.0}])[0].get("bpm", 120.0)
        tempos.insert(0, {"measure": 1, "bpm": base, "source": "沿用谱面"})

    summary["tempo_map"] = tempos
    summary["tempo_source"] = "manual"

    total_seconds = 0.0
    for m in summary.get("measures", []):
        bpm = tempos[0]["bpm"]
        for t in tempos:
            if t["measure"] <= m["measure"]:
                bpm = t["bpm"]
        m["bpm"] = bpm
        m["seconds"] = round(m["quarters"] * 60.0 / bpm, 1) if bpm else 0
        total_seconds += m["seconds"]
    summary["estimated_duration_sec"] = round(total_seconds, 1)
    return summary


def metronome_timeline(summary):
    """给节拍器用的分段速度表：每段的起始小节、速度、拍号。"""
    tempos = summary["tempo_map"]
    times = summary["time_map"]
    total = summary["total_measures"]

    def pick(map_list, m, key, default):
        val = default
        for item in map_list:
            if item["measure"] <= m:
                val = item[key]
        return val

    timeline = []
    for i, t in enumerate(tempos):
        start = t["measure"]
        end = tempos[i + 1]["measure"] - 1 if i + 1 < len(tempos) else total
        timeline.append({
            "start_measure": start,
            "end_measure": end,
            "bpm": t["bpm"],
            "beats": pick(times, start, "beats", 4),
            "beat_type": pick(times, start, "beat_type", 4),
        })
    return timeline


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "test_rectified.musicxml"
    s = summarize_musicxml(path)
    s.pop("measures", None)
    print(json.dumps(s, ensure_ascii=False, indent=2))
