# MaestroCore

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

## 网页端（本机跑，不用买服务器）

双击根目录的 `启动网页.bat`，或者：

```bash
py api_server\server.py            # 默认 http://127.0.0.1:8765/
py api_server\server.py --port 9000 --no-browser
```

零依赖，只用 Python 标准库（没装 Flask 也不影响）。浏览器打开 `http://127.0.0.1:8765/` 就能用。

五个页面各是一个独立网址（点导航就换 URL，跟火山引擎控制台一个思路）：

| 页面 | 地址 | 干什么 |
| --- | --- | --- |
| 识别 | `/index.html` | 拖谱面图片 → 矫正 → homr 识别 → 模型讲解，右侧出结果 |
| 历史 | `/history.html` | 以前跑过的记录清单 |
| 记录详情 | `/record.html?no=01` | 某一次的完整结果 |
| 节拍器 | `/metronome.html` | 网页版节拍器，可跟随谱面按小节自动变速 |
| 设置 | `/settings.html` | 音色、重音、音量、玻璃/动画、主题与兑换码 |

顶部那颗「灵动岛」全站共用：中间 BPM（点数字可直接输入）、左边拍号、右边齿轮进设置页；`−` `+` 单击 ±1、按住 Shift 单击 ±5。外观有毛玻璃 / 液态玻璃 / 不用玻璃三档。

`MaestroCore` 读作 **ma-ES-tro core**，日常就叫「麦斯特阔」。

## 目录结构

```
ai_module/       摘要解析、速度 OCR、模型通道、讲解、归档、副产物、秒表
api_server/      本地网页服务（标准库 HTTP，一个文件）
frontend_module/ 网页界面（5 个页面 + 灵动岛 + 网页节拍器）
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
- 网页端目前只在本机 `127.0.0.1` 跑，没有登录、没有并发保护，也没做部署（服务器/域名/备案都在后面）；
- 网页节拍器和桌面版是两套独立引擎（桌面走 Tk，网页走 Web Audio），同一个 `metronome_plan` 数据。

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

## 开发说明

这个项目是作者一个人在做：需求、界面取舍、验收标准都是自己定的，实现过程中大量使用了 AI 辅助。

- **豆包（Doubao）**：网页端的界面与交互、主题系统、节拍器的动画与手感调试、离线预览工具、部分文档，基本都是和豆包来回磨出来的；
- **DeepSeek**：后端流水线、模块拆分、部分重构与调试，主要靠 DeepSeek 协助；
- 所有 AI 生成的代码都经过实际运行验证（谱面识别、AI 讲解、节拍器三条链路都跑过真实谱子），不是生搬硬套。

代码写得不算漂亮，但能跑。发现问题直接开 issue 就行。

## 版权与许可

- 本项目代码与 homr 一致，采用 **AGPL-3.0**（见 `LICENSE`）。
- 谱面识别基于开源项目 [homr](https://github.com/liebharc/homr)，本项目未修改其内核，仅作为独立进程调用。
- **不要**把有版权的谱面（乐团改编谱、教材扫描件）提交到本仓库或公开传播；演示请用 homr 自带的示例谱或公有领域谱。
- 模型调用的费用由本项目作者自己承担，不向使用者收取，也不转售任何模型额度。
