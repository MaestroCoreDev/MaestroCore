# MaestroCore

## 支持作者

MaestroCore 的核心功能一直免费开放。如果你想支持服务器与大模型调用开销，
可以在这里支持我继续做下去：https://afdian.com/a/maestrocore

（谱面识别 · AI 练琴方案 · 节拍器变速 · 主题配色）

把手机拍的乐谱照片，变成「能照着练」的练琴方案：图像矫正 → 谱面识别 → 结构化解析 → 大模型讲解 → 节拍器。

给管乐团/学乐器的学生用，专门处理单声部分谱（长号、小号、单簧管这类）。支持多页合并，能自动读谱面上印的速度标记（`Largo ♩=96` 这种），并站在指定乐器的角度标出独奏段和重点段。

## 它做什么

```
谱面照片 ──► 透视矫正 ──► HOMR 识别 ──► 结构化摘要 ──► 大模型 ──► 练琴方案 + 节拍器分段
                                    └──► 速度/标题 OCR ──┘            └──► 历史记录归档
```

产物：

- `ai_result.json`：最新一次结果（难度、曲目推测、SOLO 段、练习分段、节拍器计划）
- `history/NN_曲名/`：每次跑完自动归档（结果 + MusicXML + 元信息），`index.json` 给前端历史页用
- `temp_debug/<时间_曲名>/`：副产物（放大的速度数字、页眉裁剪、整页预览、homr 日志）

## 依赖与环境

- Windows，Python **3.11**
- 需要 `opencv-python`、`numpy`、`onnxruntime`、`rapidocr-onnxruntime`、`Pillow`、`requests`、`pypdfium2`
- 谱面识别引擎 [homr](https://github.com/liebharc/homr)（AGPL-3.0，**没有 pip 包**）

装 homr 的推荐做法：把仓库放到 `homr_module/homr-main`，然后在 Python 3.11 的 `Lib\site-packages` 下放一个 `homr-local.pth`，内容写这个目录的绝对路径：

```
C:\path\to\MaestroCore\homr_module\homr-main
```

之后任何目录都能 `import homr`、`python -m homr.main`，不会拉 torch。

## 配置密钥

支持两个通道，任选其一或都配：

1. 豆包（火山方舟）：`ARK_API_KEY=ark-xxx`
2. DeepSeek：`DEEPSEEK_API_KEY=sk-xxx`

写到 `ai_module/api_key.txt`（一行一个），或设置同名环境变量。默认模型：

- `ARK_MODEL=doubao-seed-2-1-pro-260915`
- `DEEPSEEK_MODEL=deepseek-v4-pro`（也可换 `deepseek-flash`）

先体检一下 Key 有没有接对（不花 token）：

```bash
py ai_module\check_keys.py
```

## 用法

一条龙：

```bash
py main_app\run_pipeline.py 第一页.png 第二页.png --instrument 长号
```

可选参数：

- `--tempo 1:96,13:120` 人工指定每段速度（不填就自动 OCR 谱面）
- `--instrument 长号` 按乐器声部讲 SOLO/重点段
- `--provider deepseek` 换模型通道（默认 doubao）

单独跑 AI 讲解：

```bash
py ai_module\ai_analyzer.py [xml路径] [doubao|deepseek] [--image 矫正图.png] [--instrument 长号]
```

节拍器：

```bash
py metronome_module\metronome.py            # 图形界面
py metronome_module\metronome.py --cli --plan --seconds 12   # 无界面，读练习方案分段跑
```

节拍器功能：40–208 BPM、±1/±5、拍号 2/4 3/4 4/4 6/8 9/8 12/8、首拍重音、点数测速、按 `metronome_plan` 自动分段变速、空格启停。

## 目录结构

```
ai_module/       摘要解析、速度 OCR、模型通道、讲解、归档、副产物、秒表
main_app/        一条龙流水线
metronome_module/节拍器（独立引擎 + Tk 界面）
rectify_module/  纸张透视矫正
homr_module/     谱面识别引擎（外部项目，不随本仓库分发）
history/         历史记录（运行时生成，已 gitignore）
temp_debug/      副产物（运行时生成，已 gitignore）
scores/          待识别谱面输入目录（已 gitignore）
```

## 已知限制

- homr 对小节线的切分偶尔与印刷小节号差 1（第一行多切一节）；
- homr 只输出单声部，**拍乐队总谱会把声部粘成一条线**，只适合单行分谱；
- SOLO/TUTTI 的印刷标记尚未 OCR，独奏段目前按旋律位置推测；
- 前端（`frontend_module/`）与接口层（`api_server/`）尚未实现。

## 主题与兑换码

- 默认配色走：浅灰底、白卡片、蓝主色。
- 兑换码只解锁主题色，**核心功能不锁、不阉割**：青竹、琥珀、暮紫、霁蓝、赤陶。
- 所有颜色只在 `theme_module/palette.py` 定义，网页用 `theme_module/theme.css` 里的 CSS 变量（`var(--mc-accent)` 等），节拍器窗口用同一份 palette，换主题全局一起变。

```bash
py theme_module\redeem.py ABCD-EFGH-23 暮紫   # 兑换并指定主题
py theme_module\palette.py --css              # 导出全部主题的 CSS 变量
py theme_module\palette.py --list             # 看主题色
```

发码（自己用，密钥在 `theme_module/_salt.txt`，已 gitignore）：

```bash
py theme_module\redeem.py --gen 5
```

## 版权与许可

- 本项目代码与 homr 一致，采用 **AGPL-3.0**（见 `LICENSE`）。
- 谱面识别基于开源项目 [homr](https://github.com/liebharc/homr)，本项目未修改其内核，仅作为独立进程调用。
- **不要**把有版权的谱面（乐团改编谱、教材扫描件）提交到本仓库或公开传播；演示请用 homr 自带的示例谱或公有领域谱。
- 模型调用费用由使用者自己的 API Key 承担，本项目不转售任何模型额度。 
