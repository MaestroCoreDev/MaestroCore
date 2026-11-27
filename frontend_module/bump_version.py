"""版本号进位工具

规则（用户定的）：
    0.0.1  = 网页第一次能加载进来的版本
    小功能/小修复 = 最后一位 +1        例：0.0.1 -> 0.0.2
    满十进一      = 最后一位超过 9 就归零，中间位 +1；中间位也超过 9 再往前进
    大功能        = 最前面 +1，后面回到 0.1  例：0.0.1 -> 1.0.1

用法：
    py frontend_module/bump_version.py --minor    # 小功能 / 修 bug
    py frontend_module/bump_version.py --major    # 大功能
    py frontend_module/bump_version.py            # 只看当前版本
"""

import pathlib
import sys

VFILE = pathlib.Path(__file__).resolve().parent / "VERSION"


def read():
    parts = (VFILE.read_text(encoding="utf-8").strip() or "0.0.1").split(".")
    while len(parts) < 3:
        parts.append("0")
    return [int(p) for p in parts[:3]]


def write(parts):
    VFILE.write_text(".".join(str(p) for p in parts) + "\n", encoding="utf-8")
    print("版本号 ->", ".".join(str(p) for p in parts))


def minor(parts):
    parts[2] += 1
    if parts[2] > 9:
        parts[2] = 0
        parts[1] += 1
        if parts[1] > 9:
            parts[1] = 0
            parts[0] += 1
    return parts


def major(parts):
    parts[0] += 1
    parts[1] = 0
    parts[2] = 1
    return parts


if __name__ == "__main__":
    cur = read()
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if arg == "--minor":
        write(minor(cur))
    elif arg == "--major":
        write(major(cur))
    else:
        print("当前版本号：", ".".join(str(p) for p in cur))
        print("  --minor  小功能 / 修 bug（最后一位 +1，满十进一）")
        print("  --major  大功能（最前面 +1，后面回到 0.1）")
