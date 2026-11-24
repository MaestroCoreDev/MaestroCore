"""MaestroCore / ai_module 密钥体检

只调各家的模型列表接口，不产生任何推理费用，用来确认 Key 有没有接对：

    py ai_module\\check_keys.py            # 豆包 + DeepSeek 都查
    py ai_module\\check_keys.py deepseek   # 只查 DeepSeek
"""

import sys

sys.dont_write_bytecode = True

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from providers import check_provider  # noqa: E402


def main(argv):
    targets = argv or ["doubao", "deepseek"]
    print("========================================")
    print("          MaestroCore 密钥体检          ")
    print("========================================")
    all_ok = True
    for name in targets:
        result = check_provider(name)
        mark = "✓" if result["ok"] else "✗"
        print(f"{mark} {name}：{result['msg']}")
        if result.get("models"):
            print("    可见模型：" + "、".join(result["models"]))
        all_ok = all_ok and result["ok"]
    print("----------------------------------------")
    print("全部通过，可以开跑。" if all_ok else "有通道没通，按上面的提示处理。")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
