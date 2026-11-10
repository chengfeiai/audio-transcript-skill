---
name: 录音转写
description: 转写录音/录音转文字/做录音纪要时用：m4a/mp3/wav → 带时间戳对话稿（可分离说话人），并生成交互式纪要页（含时间轴回听、搜索、导出 Word、复制文字）；也可从公开短视频分享链接直接取音轨再转写。本地 mlx-whisper 为主，识别不住时换云端引擎；另含出稿规整、实时采集、AI 理解、知识库与分享等可插拔能力，云端相关默认关闭。
---

# 录音转写

> 目录名与技能名同为「录音转写」。放哪都行：把整个文件夹放进当前 profile 的 skills 目录即可，下文用 `SKILL` 代指这个文件夹的绝对路径。

把录音文件（会议录音、语音备忘录、采访等）转成带时间戳的文字稿，并可继续做总结、纪要、待办提取。

## 引擎（自备环境，本包不含）

- **转写引擎**：`mlx-whisper`（Apple Silicon 加速，~4x 实时速度）
- **Python**：转写 / 说话人分离脚本需要装有 mlx-whisper 等依赖的 Python 3.11 环境，下文记作 `<PY>`；渲染器只用标准库，系统 `python3` 即可。
- **模型**：`mlx-community/whisper-medium-mlx`（medium=质量/速度均衡；可换 small/large/turbo）。首次运行会下载到 HuggingFace 缓存，需网络与磁盘。
- **ffmpeg**：`transcribe.py` / `diarize.py` 的 `get_ffmpeg()` 先取 `imageio_ffmpeg.get_ffmpeg_exe()`，再退回 PATH / brew，通常无需手动配。
- **依赖清单**：见 `requirements.txt`（转写链路重依赖 / 渲染链路零依赖，分开列）。
- **TTS 测试/占位音频（可选）**：`<PY> -m edge_tts --voice zh-CN-XiaoxiaoNeural --text "..." --write-media out.mp3`（需另装 `edge-tts`；macOS 自带 `say` 中文语音包不可用）。

## 引擎选择：本地不准就换云端，别死磕模型

**判据**——转写稿出现以下任一症状，说明是引擎在该音轨上失效，不是参数问题：

- 整段循环重复（同一短语反复几十遍，如「搞搞搞搞…」「死了死了死了…」）
- 句子不成句，只有零星词能对上
- 换 `--model large` 后更碎（模型更大反而更敏感，会把噪声也拟合进去）

**这时直接换引擎，不要继续调 temperature / initial-prompt / 切片。** 云端引擎（**外部服务，本包不含其调用代码**）一次即可产出句子成形的结果，且自带说话人编号（0/1/2）。

**判据补充**：方言重、串音多、多人抢话的音轨容易触发上述症状；此时优先换引擎，不要在本地反复调参。

**产物链路**（云端稿同样要留底 + 校订）：
1. 云端原始稿存为 `<名>.对话稿(云端原始).txt`（可追溯，不要直接改）
2. 人工校订成 `<名>.整理稿.txt`：姓名一律标「音」（读音不确定的）、听不清处标「不清」，**不替它编一个通顺版本**
3. **停下问风格**（见下文「风格提问环节」）：版式二选一 → 双栏再问皮肤六选一
4. 按选定版式写内容，渲染**一版**出稿

> **外部 / 云端稿怎么接进来**：外部转写服务不在本包内，本包没有封装它的 API。拿到它的转写稿（或任何人工校订稿）后，手工存成 `<名>.整理稿.txt`（每行 `[mm:ss] 说话人：正文`），再用 `render_split.py --transcript "<名>.整理稿.txt"` 或 `render_minutes.py --transcript` 直接渲染即可 —— 这条「外部稿 → 渲染」链路本包已完整支持，不依赖任何云端 SDK。

## 素材来源（可选）：公开短视频分享链接 → 本地音轨

本包默认吃本地音频文件。**当用户只给一条公开短视频分享链接（或一段带短链的分享文案）时**，先用 `fetch_douyin_audio.py` 把音轨落到本地，再走下面「用法」的标准链路。脚本纯标准库，不需要 pip install。

### 为什么不能直接用 yt-dlp

平台 Web 播放地址带签名参数，yt-dlp / 裸请求会报 `Fresh cookies (not necessarily logged in) are needed`。带登录态 cookie、绕代理、走旧接口均无法稳定通过。**这条路线不推荐反复重试**（重试只会浪费时间、触发风控）。

### 换一条路：借页面自己算好的签名

| 步 | 做法 | 要点 |
|---|---|---|
| 1 | `ego-browser` 打开真实视频页 | 分享短链自动跳到 `/video/<aweme_id>`；页面能正常播放（blob 流）就说明签名链路是通的 |
| 2 | 读 `performance.getEntriesByType("resource")` | 页面发出的每个请求都带**已算好的合法签名**；不伪造签名、不用 cookie、不用装扩展 |
| 3 | 过滤 `media-audio-und-mp4a` 独立音频轨 | 平台 CDN 把音视频拆轨；转写只要声音，拿到的是带签名的完整音轨 |
| 4 | `curl` 带站点 Referer 落盘 | 只取声音不下整段视频；未拆音轨时脚本自动下视频流并用 ffmpeg 提轨 |
| 5 | ffmpeg 校验时长 / 音轨 | 落盘后先切 60 秒样本试转，确认口播与引擎可用，再跑全量 |

**核心一句：与其破解签名，不如让页面把签名算好；与其下整段视频，不如只取它已经拆好的那条音轨。**

### 命令

```bash
SKILL="<解压后的绝对路径>"

# 先探测（不下载）：看是否公开可播、有没有独立音轨
python3 "$SKILL/scripts/fetch_douyin_audio.py" "https://v.douyin.com/xxxxxxx/" --dry-run

# 正式取流，--json 便于上层 Agent 直接接着跑转写
python3 "$SKILL/scripts/fetch_douyin_audio.py" "https://v.douyin.com/xxxxxxx/" \
  --out "音频.m4a" --json
```

`--json` 输出 `out / aweme_id / duration / codec / bytes / stream`。前置命令：`ego-browser`（真实浏览器驱动）、`curl`、`ffmpeg`（校验与视频提轨），**三者均非本包自带**；缺任一会给明确报错，不静默降级。

### 失败分支诊断

| 现象 | 原因 | 处理 |
|---|---|---|
| `Fresh cookies ... needed`（yt-dlp / 通用下载器） | 签名风控，不是链接失效 | 别重试，改用本脚本；本脚本从不调用 yt-dlp |
| 探测不到音频轨也没有视频轨 | 图文 / 直播回放 / 登录墙 / 验证码 | 先在浏览器确认能公开播放；登录、付费、私密内容不适用本流程 |
| `page.evaluate timed out` / `waiting for load` 超时 | 平台页面主线程忙、load 事件不触发 | 脚本只等 `domcontentloaded`、分两阶段读取，并自动换浏览器空间重试 3 次；仍失败就隔几分钟重跑，或让用户直接给本地音频文件 |
| 下载 HTTP 403 / 401 / 空文件 | **CDN 签名 URL 有时效** | 脚本自动重开页面取新签名重试一次；仍失败就隔几分钟重跑一次脚本 |
| 只有视频流、没有独立音轨 | 该视频未拆轨 | 脚本自动下整段并 `ffmpeg -vn -acodec copy` 提音轨，体积会大很多 |
| 转写时模型联网校验报 502 | 本机代理挡住模型校验，但模型缓存在本地 | 加 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 走离线缓存，别去修网络 |

### 完整流水线（含两道闸门）

```bash
# 1 取流（上节）→ 2 先切 60s 样本试转，再跑全量
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 <PY> "$SKILL/scripts/transcribe.py" \
  "音频.m4a" --lang zh --srt --md --initial-prompt "领域词,人名,术语"

# 3 校订成 <名>.整理稿.txt（[mm:ss] 说话人：正文），原始稿保留可追溯
# 4 停下问版式（二选一）→ 若双栏再问皮肤（六选一）；只写选中版式的内容
# 5 渲染一版，--check 断链必须为 0
python3 "$SKILL/scripts/render_split.py" --content "<名>.json" \
  --transcript "<名>.整理稿.txt" --audio "音频.m4a" --skin default \
  --check --out "<名>-交互纪要(双栏).html"
```

闸门不许跨：**不预渲染多版样张让用户挑**；版式/皮肤没点选就不落默认值。详见「风格提问环节」。

### 边界与合规

- 仅用于**公开可播放**的视频页；不绕过登录墙、付费墙、私密内容与地域限制。
- 只取声音用于本地转写，**不缓存带签名的 URL、不分发音视频原件**；分享/归档时给文字稿与纪要页，遵守平台服务条款与内容版权。
- 签名 URL 有时效且不得外传，脚本日志已省略完整 URL。
- 换其他平台时风控机制不同，不要照搬正则与过滤条件；实现中的域名与请求头仅为兼容性细节。
- 音频与 HTML 必须同目录才能点时间码回听（见「已知问题」第 7 条）。

**链路要点**：取到独立音轨后先切 60 秒样本试转，确认口播可识别再跑全量；全程不装扩展、不用 cookie、不伪造签名。

## 用法

**路径约定**（全文通用）：
- `SKILL` = 本技能包（「录音转写」文件夹）的绝对路径，用前设一次：`SKILL="<解压后的绝对路径>"`。
- `<PY>` = 装有 mlx-whisper 等依赖的 Python 3.11 解释器（仅 `transcribe.py` / `diarize.py` 需要）；`render_*.py` 用 `python3` 即可。
- 本包**不含**虚拟环境、模型与第三方库；脚本按「技能包相对路径优先」查找模板 / 皮肤 / 能力模块，不必把文件复制到宿主环境的固定脚本目录。首次安装见 `安装说明.md`。

```bash
# 基本转写（输出与音频同目录同名 .txt；--srt 字幕 --md 时间轴 --outdir 指定目录）
<PY> "$SKILL/scripts/transcribe.py" "录音.m4a" --srt --md

# 领域术语纠错（重要：专业词/英文品牌名易同音错，用 initial-prompt 显著改善）
<PY> "$SKILL/scripts/transcribe.py" "录音.m4a" --initial-prompt "AiPPT,联调,测试用例,边界场景,模板继承"

# 换模型 / 指定语言
<PY> "$SKILL/scripts/transcribe.py" "录音.m4a" --model large --lang zh
```

用户说「转写这个录音」时：**先用上述脚本转写**，然后（按需）把 txt 喂给主模型做总结/纪要/待办提取。多个文件批量：逐个调用脚本即可（脚本一次一个文件）。

## 说话人分离（写明说话人1/2/3）

```bash
# 单文件：whisper 转写 + speechbrain ECAPA 声纹聚类（免费、无 token，首次自动下载 ~200MB 模型）
<PY> "$SKILL/scripts/diarize.py" "录音.m4a"

# 多文件批量（模型只加载一次）+ 自动估计说话人数（1-6，可 --min-speakers/--max-speakers 限制）
<PY> "$SKILL/scripts/diarize.py" "a.m4a" "b.mp3" --max-speakers 4

# 输出：<名>.对话稿.txt（[mm:ss] 说话人N: 文字）+ <名>.对话稿.md（时间轴+说话人）
```

要点：
- 说话人数用 KMeans + silhouette 自动估计（对话录音通常 2 人；含客服/转接可能 3 人）
- 过短段（<1.2s）自动并入相邻段，保证声纹质量
- 依赖：`speechbrain`、`scikit-learn`、`torch`、`soundfile`（需装进 `<PY>` 所在环境，见 `requirements.txt`）
- 声纹模型缓存：默认落在 SpeechBrain / HuggingFace 缓存目录，首次自动下载约 200MB，删了会重下
- 同音字问题同 transcribe.py，可加 `--initial-prompt`

## 输出格式

- `.txt`：每行 `[mm:ss] 段落文字`（whisper 自动分段）
- `.srt`：标准字幕（可拖进剪映/Pr）
- `.md`：Markdown 时间轴 `**[mm:ss–mm:ss]** 文字`

## 风格提问环节（转写＋校订完成 → 开始写内容之前）

**触发点**：`<名>.整理稿.txt` 定稿、正文不会再变的那一刻，**停下来问用户要哪种风格**。不要先渲染出来让他挑，也不要拿默认值替他定。

**为什么必须在这里问**：两种版式吃的是两份完全不同的内容结构——双栏要 JSON（`blocks / cards / steps / checks / duel`），深色 v3 要 `.minutes` 标记语法。版式没定就写内容，等于押一次盲注；等 JSON 写完才发现要深色，整份内容重写。

### 第 1 问：版式（必问，二选一）

| 选项 | 适合什么材料 | 交付形态 |
|---|---|---|
| **浅色双栏「阅读器」** | 要逐段核对原音、按说话人筛选、打印归档的：会议、访谈、面谈、通话 | 左栏结构化纪要 / 右栏全文，时间戳点一下回听，带搜索与角色筛选 |
| **深色 v3 图文纪要** | 要「一页看完」的：汇报、对外呈现、给人快速过一遍 | 单页玻璃拟态，四色板块 + 时间线，全文可折叠；**没有搜索、没有按说话人筛选** |

拿不准时用这一条判：**这份材料需不需要「每句话都对得上原音」**——需要就是双栏，只想知道「发生了什么」就是深色。

⚠️ 提问时要把代价说在明处：**深色版查不了**（全文只能在 620px 的框里滚，不能搜、不能筛人），**双栏版一眼看不完**（要先看左栏结论）。用户选了深色又回头要搜索，就是这一步没说清。

### 第 2 问：皮肤（仅当第 1 问答「浅色双栏」）

六选一（名称以 `--list-skins` 输出为准）：`default`（模板原生，不加皮肤层）/ `mist`（灰蓝粉彩：灰蓝画布＋四节粉彩分色＋双列白芯卡片）/ `plain`（素白极简：纯白无卡、38:62 左窄右宽、分隔条可拖动、紫粉渐变标题）/ `dark`（深蓝学术：深藏青＋细网格＋宋体标题）/ `neutral`（中性灰阶：#F7F7F7 画布＋白卡 1px 描边＋唯一强调 #335CFF，克制阴影、Badge/Filter/Table 组件语义）/ `obsidian`（黑曜潮青：#07080A 黑曜底＋骨白正文 #F3F5F8＋四节深夜分色＋薄荷 #8BF3E6 强调，结构与灰蓝粉彩一致）。把 `--list-skins` 输出里的六张 `previews/*.png`（绝对路径）给用户看，并**口头注明预览用的是 `examples/split-示例.json` 的虚构示例内容，他自己的录音会换成自己的标题与正文**（预览均为中性示例，不含任何真实材料）。
  > **版式**：桌面并排（视口 ≥ 921px）统一「双面板独立内滚」——左右两栏各滚各的，拖哪栏哪栏动，互不带动；播放条常驻右栏底部。窄屏（≤920px）回到单列整页滚动。`templates/split/page.js` 的 `detectScrollMode()` 自动识别，目录高亮/锚点跳转/回顶两套分支都覆盖。中间分隔条可拖动改栏宽（双击复位），与滚动互不影响。

问法要点：
- 用点选卡片（AskUserQuestion），**一次只问一个**；第 1 问回答完再发第 2 问，不要两张卡片一起发——选了深色就不存在皮肤问题。
- 用户在任意一问上不选 / 说「都行」/ 跳过 → **再问一次**，可加一句你的建议帮他判断（如「这份是要归档的，我建议双栏 default」），但**不自动落默认值**；只有他明确说「你定」才代为决定。
- 别把两个问题合并成一张多选项卡片：那会逼用户在「版式」和「皮肤」两个维度里做交叉选择，很难点。

### 闸门

**只渲染被选中的那一版，一次一条命令。禁止预渲染多版样张让用户挑**——几份几乎相同的大文件，用户得自己比差异、自己收拾没选中的。验证注入是否正常用 `--skin default` 的哈希比对即可，不必产出成品。

> ✅ **皮肤与内容完全无关**：`mist / plain / dark` 三套 CSS 的装饰文案走 `content:attr(data-*)`，由 `render_split.py` 把标题 / 副标题写入 DOM 的 `data-*` 属性；`plain` 不隐藏真实 h1。六张预览图均为 `examples/split-示例.json` 的虚构示例。详见 `发布自查清单.md`。

## 深色 v3 图文纪要（render_minutes.py）

> **两套版式，用哪套由用户在上文「风格提问环节」定，此处只列特性：**
> - **浅色双栏「阅读器」版**（`render_split.py`）：左篇纪要 / 右栏全文 + 时间轴回听 + 搜索筛选。需要逐段核对原音、打印归档、发给人看时用这套。会议纪要、访谈、面谈这类"要拿证据"的材料都用它。
> - **深色 v3 图文纪要版**（`render_minutes.py`）：玻璃拟态 + 霓虹发光 + 极光背景，四色板块 + 时间线卡片。要"一页看完"的汇报、对外呈现时用它。
> 两套都内联同一个能力模块（导出 Word / 复制文字，见下节），都支持点时间戳回听原音。**但能力不对等，选之前要知情**：双栏版还有全文搜索、按说话人筛选、待核清单可勾选；深色版没有搜索与筛选，全文只能滚动翻（`t-body` 是 620px 内的独立滚动区），适合通读不适合查证。选错不是只影响观感。
> 设计语言：深蓝黑背景 #080D1A + 三处极光径向光晕；板块/横幅/摘要全玻璃拟态（rgba 半透明 + backdrop-blur + 顶部高光边）；四板块霓虹色系（粉=争议/橙=回应/绿=行动/蓝=背景），卡片左侧发光色条 + 标题发光；时间线节点渐变圆+双层光晕；全文区深色代码风 + 说话人发光圆点（1蓝 2绿 3橙 4紫 5红）。

转写+说话人分离后，**确定要「一页看完」的图文纪要**（汇报、对外呈现）时走此流程；要逐段核对原音、打印归档则用下面的双栏版式。

### 流程
1. `transcribe.py` / `diarize.py` 转写出对话稿（带 [mm:ss] 时间戳）
2. **读对话稿**，提炼结构化纪要，按标记语法写成 `<名>.minutes` 文件：
   - 元信息 5 要素（会议主题/主要参会方[角色化]/核心争议/会议结果/摘要）
   - 四段式板块：背景与材料 → 核心争议焦点 → 部门回应与处理态度 → 关键决策与行动方向（或 后续行动项）
   - 每条要点带 `[mm:ss]` 时间引用（比按段落行号引用更直观）
3. 渲染（`--transcript` 附完整转写全文，自动繁→简）：
```bash
SKILL="<解压后的绝对路径>"
python3 "$SKILL/scripts/render_minutes.py" \
  --from-markup "<名>.minutes" --duration "6:53" --date "06-26 16:17" \
  --audio "<录音名>.m4a" --transcript "<名>.对话稿.txt" --out "<名>-图文纪要.html"
```
产出：一页含 回听横幅 → 标题摘要 → 四色板块 → 转写全文（可折叠）

**三个必须知道的约束**：

- **板块名要对上表才上色**。配色按标题精确匹配：`背景与材料`(蓝) / `核心争议焦点`(粉) / `部门回应与处理态度`(橙) / `关键决策与行动方向` 或 `后续行动项`(绿)。写成「四个争议焦点」「交锋链条」这类自拟名会一律落到默认蓝，四色编码就废了。要分段就在这五个名字里挑。
- **`--transcript` 要传纯正文稿**。整理稿常带 6—10 行头部说明（场景/在场/校订原则），渲染时会被当成正文逐行塞进全文区。渲染前先剥一层：只留匹配 `^\[\d{1,3}:\d{2}\]` 的行。
- **正文里的时间必须带括号**：写 `（01:42）` 或 `[01:42]`，渲染时会变成可点跳转（跳到播放器对应秒数）；写成 `01:42` 裸数字不会链接。`--audio` 给了才内嵌播放器，没给横幅显示「未附音频」。

### 标记语法
```
# 大标题
> 摘要
<section>
## 核心争议焦点        ← 板块标题自动配色：争议=粉 / 回应=橙 / 行动=绿 / 背景=蓝
<flex-view>
<simple-card label="短标签" comment="一句话点评">正文（可含<li>列表）</simple-card>
<rich-card label="标题" icon="flag" tags="已受理" comment="点评">正文</rich-card>
</flex-view>
</section>
<section>
## 关键决策与行动方向
<step-view label="处理流程">
<rich-card label="节点" icon="book" tags="起点|核心|进行中|明确要求" comment="点评">正文</rich-card>
</step-view>
</section>
```
- icon 支持：flag/calendar/person/book/fire/alarm-clock/trophy/compass/check/question/warning/target/link
- step 节点圆形图标自动取标签首字：起点→起 / 核心→核 / 进行中→办 / 明确要求→诉 / 转折→转 / 关键→键 / 结束→终；标签不在表里会退化成序号（1、2、3），一眼能看出没用对

### 深色渲染器的两种输入模式
- `--from-markup <file>`：自定义标记语言（推荐，标准流程）
- `--from-json <json>`：解析第三方 INFOGRAPHIC_SUMMARY 结构 JSON（纪要 / 思维导图 / 章节速览 / 关键词），迁移或对比用

### 图文纪要格式要点
- 颜色分区编码：一个板块一个色系，扫一眼知归属
- 卡片组件化：标题+正文+底部标签（comment 一句话点评）
- 时间线流程化：决策链用竖线+圆形图标节点（起/核/办/诉）
- 标签即状态：已受理/督办/起点/核心/进行中/明确要求
- 顶部回听横幅：二维码占位+时长+日期
- 若你手上已有第三方产品的 INFOGRAPHIC_SUMMARY 结构 JSON（纪要 / 思维导图 / 章节速览 / 关键词），可用 `--from-json` 直接渲染成同款图文纪要；**本包不内置任何平台抓取实现**，数据由使用者自行合法取得

## 浅色双栏「阅读器」版式（render_split.py）

用于**要拿证据的场合**：逐段核对原音、点击时间戳回听、按说话人筛选、打印归档。左栏是结构化纪要（标题 / 三句结论 / 多板块卡片 / 处理链条 / 待核清单），右栏是全文（搜索 + 筛选 + 发言节奏条 + 播放器）。

```bash
SKILL="<解压后的绝对路径>"
python3 "$SKILL/scripts/render_split.py" --content "<名>.json" \
  --transcript "<名>.整理稿.txt" --audio "<录音名>.m4a" \
  --check --out "<名>-交互纪要(双栏).html"
```

- `--check`：渲染前校验，输出「段落 N 段 · 引用 M 处 · 断链 K 处」。**断链必须为 0**，否则页面里会出现点了不跳的时间标签。
- `--transcript`：直接从整理稿（`[mm:ss] 说话人：正文`）解析全文，可替代 JSON 里的 `transcript` 字段。
- `--no-tools`：不内联导出/复制模块。
- `--skin <id>`：注入展示皮肤（`default` / `mist` / `plain` / `dark` / `neutral` / `obsidian`），见下节。
- 最小可用示例：`examples/split-示例.json`（虚构场景，全字段覆盖，可直接跑通）。

### 皮肤注入（提问已在前文「风格提问环节」完成，此处只管落参数）

用户在风格提问环节选定的 id 直接传给 `--skin`。**这一步不再提问，也不要在这里预渲染别的版本做备选。**

1. 清单（五 id / 名称 / 一句话 / 预览图绝对路径），只在需要复核 id 时用：
   ```bash
   python3 "$SKILL/scripts/render_split.py" --list-skins
   ```
2. 一次命令、一个 `--skin`，出稿。找不到皮肤包或文件缺失会**直接报错退出**（退出码 4），不静默降级成 default。

```bash
python3 "$SKILL/scripts/render_split.py" --content "<名>.json" \
  --transcript "<名>.整理稿.txt" --audio "<录音名>.m4a" \
  --skin mist --check --out "<名>-交互纪要(双栏).html"
```

注入实现（`render_split.py`）：皮肤 CSS 全文放进**独立的** `<style data-skin="<id>">`，插在 `</head>` 之前——即主 `<style>` 之后。**不能拼到主 style 末尾**：主 style 一旦有未闭合注释，追加的样式会被整段吞掉。`default` 不注入任何东西。

皮肤包目录按 `cwd/skins` → 技能包 `../skins` → 当前 profile 的 skills 目录 顺序找，也可用 `--skins-dir` 指定。皮肤只含 `@media screen` 视觉规则，不动 DOM/文本/脚本/音频；打印走模板原始打印样式。

> ⏱ **播放速度**：点倍速框弹出 6 档菜单（0.5–2.0x）选择后生效，不是循环切换；选择记进 `localStorage`。菜单节点挂在 `document.body` 上用 fixed 定位（`#pR` 的 `backdrop-filter` 会为 fixed 造包含块，放播放条里会被裁掉或错位）。

> 🌑 **obsidian 皮肤（黑曜潮青）**：结构与 `mist` 完全一致，只换配色层 —— 黑曜底 `#07080A`、骨白正文 `#F3F5F8`、四节深夜分色（暗红/暗绿/暗蓝/暗金）、薄荷 `#8BF3E6` 强调。深色底按三级文字明度递减，强调色用低透明度叠加而非满色块。深色底上有四个模板写死 `#fff` 的容器（`.pill` / `.card` / `.rhythm-bars` / `.pl-speed`）已被皮肤换面；`--slate`（`.seg-x` 与 `.brief li` 的正文色）改骨白系，否则正文读不出；播放键图标改深色，否则亮薄荷上的白图标不可见。

> 📐 **neutral 皮肤**：采用的通用中性界面规范（灰阶 / 语义色 / 字阶 / 1px 描边 / 极轻阴影 / 组件对位）见 `设计参考-中性界面规范.md`。它是纯 CSS 覆盖层：先关掉模板的光晕、渐变、纸感颗粒与品牌光带，再把 Tabs、Badge、Text Input、Filter、Checkbox、Timeline、Tooltip 等组件语义重铸到现有 DOM 上。**不新增交互**（Command Menu、Drawer 等需要 JS 的组件明确不迁移），模板原有的搜索、筛选、回听、导出能力一个不少。

> ✅ **皮肤与内容完全无关**：装饰文案一律走 `content:attr(data-*)`——渲染器把 `__SKIN_TITLE__` / `__SKIN_SUBLINE__` / `__SKIN_CAPTION__` 写进 `<body>` / `.rhythm` / `.player` 的 `data-*` 属性，CSS 只负责显示、内容随 JSON 走；缺属性时 `:not([data-x])` 兜底不画空栏。禁止在皮肤里硬编码任何标题、日期、人名或副标题，六套皮肤换任意录音都不会串字。

### 内容 JSON 字段

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `title` | ✅ | 字符串，或数组（数组按行用 `<br>` 断开，第一行最醒目） |
| `title_tag` | | `<title>` 内容，缺省取 title |
| `kicker` / `sub` | | 标题上方小标签 / 标题下副标题 |
| `meta` | | `[{"k","v"}]`，`"mono": true` 用等宽字体（适合文件名） |
| `brief_title` | | 缺省「三句话结论」 |
| `brief` | | `[{"x":"..."}]`，支持 `<b>` 与 `{{mm:ss}}` |
| `chips` | | `[{"tone":"no\|mid\|ok","k":"未定","v":"交付时间"}]` |
| `audio` | ✅ | 音频文件名，相对 HTML 所在目录 |
| `duration` | | 总时长 `mm:ss`；缺省按末段 +60 秒估算 |
| `roles` | | 说话人全名数组（按顺序配 蓝/琥珀/绿）；缺省从 transcript 推断 |
| `aliases` | | `{"干部方":["干部"]}`，把整理稿简称归一到全名——**漏配会导致配色退化**（stderr 会提示） |
| `search_placeholder` | | 搜索框提示语 |
| `sections` | ✅ | 板块数组，见下 |
| `decl` / `stamp` | | 页脚声明 `[{"k","v"}]` 与落款 |
| `transcript` | | `[{"t":"08:44","who":"干部方","x":"正文"}]` |

`sections` 四种类型（导航序号按数组顺序自动生成，`num` 可覆盖）：

- `{"type":"cards","num":1,"title":"核心争议","sub":"4 个分歧点","tone":"blue","cards":[{"label":"…","body":["条目1","条目2"] 或 "整段HTML","comment":"一句话点评"}]}` — tone 取 `blue` / `amber` / `green`
- `{"type":"steps","num":3,"title":"处理链条","steps":[{"k":"节点","time":"06:42","tags":["起点"],"body":"…","cm":"点评"}]}`
- `{"type":"checks","num":4,"title":"待核实体","checks":[{"k":"靶点","v":"为什么待核"}]}`
- `{"type":"duel", …}` — 左右对照面板，或作为 cards 板块的 `"duel": {...}` 附在卡片下方

正文里所有 `{{mm:ss}}` 都会渲染成可点击的时间标签，`--check` 保证它们都能命中段落。

### 改模板前必读

版式在 `templates/split/` 三件（`page.css` / `page.js` / `page.html`），`render_split.py` 只负责填内容：

- 占位符形式 `__XXX__`（双下划线），**不能**用 `{}` —— CSS/JS 里大括号太多，`str.format` 会炸。
- `page.js` 里有两个占位由渲染器二次替换：`__TOTAL__`（总秒数）、`__WHOCOLORS__`（角色→颜色字典）。渲染器先替换 JS 自身占位，再把 JS 塞进页面；顺序反了页面就会显示原始占位符。
- 渲染完会扫一遍残留占位符，有残留打到 stderr。
- 三个角色固定三色（`--brand` / `#D69A2D` / `--green`），超过三人按模 3 循环配色。要改色改 `page.css` 的 `.sp-a/.sp-b/.sp-c` 与渲染器里的 `ROLE_COLOR`。

页面自带三种降级，无需额外配置：窗口 ≤920px 两栏堆叠、去装饰改纯白；打印时背景层与所有按钮 `display:none`、面板强制白底；系统开启「减弱动态」时入场动画与光团漂移停止。

## 导出 Word / 复制文字（内置，默认开启，两套版式通用）

渲染器会把 `assets/minutes-tools.js` 内联进页面，自动长出四个入口，不需要改模板、不需要联网：

| 入口 | 位置 | 行为 |
| --- | --- | --- |
| `Word ▾` | 工具栏（或右上浮动条） | 下拉两项：`纪要 + 全文`（归档用）/ `仅纪要`（只要结论与清单） |
| 复制（工具栏） | 左栏 | 一键复制整篇纪要，Markdown 格式，粘进聊天工具 / 邮件 / 文档仍是结构化的 |
| 复制（右侧工具栏） | 右栏 | 复制转写全文，每行带 `[mm:ss] 说话人：` |
| 复制（悬浮小按钮） | 卡片、时间线节点、结论块、每条对话段 | 只取这一条，鼠标移上去才出现 |

快捷键：`⌘/Ctrl + Shift + C` 复制整篇纪要。

实现要点（改这个模块前先读）：
- `.docx` 是**在浏览器里手工打包**的：store 模式 zip（自写 CRC32）+ 最小 OOXML（`[Content_Types].xml` / `_rels/.rels` / `word/document.xml` / `word/styles.xml` / `docProps/core.xml`）。不是把 HTML 改后缀冒充 Word —— 那种文件 Word/WPS 会提示格式不符。
- 页面版式：A4、页边距 2cm、标题 18pt、节标题 14pt 蓝色带下划线、卡片 12pt、正文 10.5pt；时间码灰色、说话人按角色着色、点评是带左边框的引用块。
- **OOXML 子元素顺序是强制的**（`pPr` 里 `pBdr`/`keepNext` 必须在 `spacing` 前，`rPr` 里 `color` 必须在 `sz` 前）。顺序错了 Word 会提示文档损坏，LibreOffice 却照样打开 —— 别只看 LibreOffice 的渲染结果。
- 中文字体**不要锁死** `w:eastAsia="微软雅黑"`：macOS 没这个字体，fallback 后字距会被拉开。交给 Word 主题字体（Win 等线 / Mac 苹方）最稳。
- 模块源码里**绝不能出现字符串形式的 `</script>`**，内联时会被 HTML 解析器提前截断，整段脚本静默失效（2026-10-30 踩过）。渲染器和两个构建脚本都会在写入前 `replace("</script", "<\\/script")` 兜底。
- 兼容旧模板：页面没有 `.doc` / `#pL .pill` 这类结构时，模块按语义标签（`h1–h4` / `p` / `li` / `.t-row` / `.block-title` / `.gc-title`）兜底抽取，并在右上角挂一个浮动工具条，能力照常可用。
- 关闭：加 `--no-tools`。

已知限制：剪贴板受浏览器权限约束，`navigator.clipboard` 被拒时回退 `execCommand('copy')`，仍失败会提示手动选中；`file://` 双击打开可用，但部分浏览器在窗口失焦时拒绝写剪贴板。

## 字号与层级（v1.3.1）

全站字号由 `templates/split/page.css` `:root` 的 7 个 token 统一控制：
`--fs-xxl` 26 / `--fs-xl` 20 / `--fs-lg` 17 / `--fs-md` 15（正文）/ `--fs-sm` 13.5 /
`--fs-xs` 12 / `--fs-xxs` 10.5（px），行高 `--lh-md:1.75` / `--lh-sm:1.6`。
模板与四套皮肤全部引用它们，**改字号只改这 7 个值**。正文类元素带 `max-width:40em`，
宽屏不会出现超长行。

## 能力全景

> 完整对照表与非代码形态接入清单见 **`能力全景与接入清单.md`**。

**分层原则**：所有能力都进包，但按「默认本地 / 显式启用云端」分层。任何把音频或转写文本送出本机的路径，
都必须显式传 `--i-understand-data-leaves-this-machine`，脚本执行前会打印醒目警告；不静默联网、
不静默降级、不把未启用的能力说成已可用。

### 五层速查

| 层 | 对应能力 | 入口 |
|---|---|---|
| 采集 | 实时录音 / 边录边转 / 录音中插照片批注 / 系统内录检测 / 实时字幕 | `scripts/record.py` |
| 识别 | 统一引擎适配（local / manual / cloud / workbuddy）、外部精转稿规范化、持久化热词库与领域词表、语种与方言边界表 | `scripts/engines.py`、`hotwords.json`、`languages.json` |
| 出稿 | 出稿四选 + md/json、三档规整、场记时间码、字幕单行字数、语篇规整与翻译接入位 | `scripts/postprocess.py`、`scripts/analyze.py` |
| AI 理解 | 问答与推荐追问、风险识别 / 决策建议 / 知识拓展、照片批注理解、重点与待办、一键结构化纪要、章节速览、关键词、思维导图、AI 写作与润色 | `scripts/analyze.py` |
| 资产 | 自动分类知识库索引、同步适配器、分享包与二维码、链接格式导出、企业接入清单 | `scripts/library.py` |

### 命令速查

```bash
# 出稿四选 / 三档规整 / 场记时间码 / 字幕折行 / 持久化词库
python3 "$SKILL/scripts/postprocess.py" "稿.txt" --format roles --clean fluent \
  --fieldcode 5 --max-chars 16
python3 "$SKILL/scripts/postprocess.py" --hotwords --domain 教育 --prompt
python3 "$SKILL/scripts/postprocess.py" --languages --check-lang yue

# 实时采集（--check 只探测不占麦克风；--dry-run 不录音）
python3 "$SKILL/scripts/record.py" --check
python3 "$SKILL/scripts/record.py" --list-devices
python3 "$SKILL/scripts/record.py" --seconds 10 --device 1

# 引擎与外部精转稿
python3 "$SKILL/scripts/engines.py" --list
python3 "$SKILL/scripts/engines.py" ingest --input 外部稿.srt --out 规范稿.txt

# AI 理解层：默认 agent 引擎，不出本机
python3 "$SKILL/scripts/analyze.py" --input "稿.txt" \
  --tasks summary,chapters,keywords,todos,insights,questions,minutes --ask "关键问题"
# 宿主 Agent 回写 analysis-result.json 后：
python3 "$SKILL/scripts/analyze.py" --apply analysis-result.json \
  --transcript "稿.txt" --audio "录音.m4a" --duration "12:30" --verify-render

# 资产层
python3 "$SKILL/scripts/library.py" --root . --index
python3 "$SKILL/scripts/library.py" --share "纪要.html" --publish
python3 "$SKILL/scripts/library.py" --access
```

### 三条不可越过的闸门

1. **数据出本机**：`cloud` / `workbuddy` 引擎、`library.py --sync` 都必须显式确认开关。
   `workbuddy` 引擎只生成请求包，**不自行构造后端地址、不虚构 publicConfig**，由 agent 用平台能力完成。
2. **时间码守门**：`analyze.py --apply` 校验所有 `{{mm:ss}}` 与 `time` 是否命中真实段首；
   不命中直接拒绝，不擅自对齐。只有显式 `--snap-times` 才允许对齐到 ±5 秒内最近段首，
   超过 5 秒仍拒绝（防止指错内容）。`postprocess.py --clean digest` 同理拒绝机械硬截。
3. **版式与皮肤两道点选闸门保持不变**：素材与内容生产能力只扩展输入与整理环节，
   「停下问版式 → 双栏再问皮肤 → 只渲染选中那一版」的规矩不受影响，禁止预渲染样张。

### 关键设计取舍

- **AI 理解层由 agent 承担**：默认引擎不联网。脚本把全文 + 任务清单 + 输出 schema 打成
  `analysis-request.md`，宿主 Agent 在对话里完成后回写 `analysis-result.json`，
  `--apply` 再拆成 11 类产物并生成可直接渲染的 `纪要内容.json`（可加 `--verify-render` 跑断链校验）。
  能力真实可闭环，且音频与正文一步不出本机。
- **不造空壳**：桌面客户端、App、录音笔、人工精转团队、厂商准确率数字、私有化部署、账号计费
  这类不是 Python 脚本能交付的形态，统一写进 `能力全景与接入清单.md` 第 4 节，标清「由谁点一下」；
  凡能由代码交付的等价能力（CLI 录音、外部稿接入、分享包、发布请求包）均已落地。
- **不宣称准确率**：本地 whisper 面向标准语场景；方言、混说、翻译、垂直模型
  统一走 `languages.json` 的路由规则，按既有结论显式换云端引擎，不在 medium 上调参死磕。
- **合并段落会破坏时间锚点**：`postprocess.py --merge-paragraphs` 明确提示重渲纪要需重新对齐引用。

## 已知问题与提示

1. **同音字错误**是正常现象（联调→连条、用例→用力 等），尤其 TTS 快速语音或口音重时；先用 `--initial-prompt` 注入领域术语，仍错就换 `--model large`。真实会议录音语速正常，medium 准确率足够。
2. **说话人分离**：whisper 不做 diarization；本包已内置 `diarize.py`（speechbrain ECAPA 声纹聚类 + KMeans 自动估人数，免费无 token），不需要 pyannote。转写稿本身只含时间轴，要标角色需跑分离脚本或 `postprocess.py --format roles`。
3. **输出覆盖**：同名文件直接覆盖，无提示。
4. 临时 16k wav 在转写后自动删除。
5. **超长录音**（>1h）：脚本无内置分段，whisper 会整段处理（16GB 内存可跑 large，medium 无压力）。
6. ffmpeg：`get_ffmpeg()` 先取 `imageio_ffmpeg.get_ffmpeg_exe()`，再退回 PATH / brew，一般不用管。若确实要在 PATH 上放软链：
   把 `imageio_ffmpeg.get_ffmpeg_exe()` 返回的路径软链到 PATH 内任意目录即可。
7. **双栏页的音频必须与 HTML 同目录**（页面用相对路径引用）。单独移动或转发 HTML，播放器会显示「音频不可用：文件需与本页同目录」，文字检索、时间标签定位、导出全部不受影响 —— 只是不能回听。要分享就音频 + HTML 一起给。
8. **在部分带 shim 的宿主终端里跑 `diarize.py` 可能报 `FileExistsError: ... mkdir ~/.cache/speechbrain`**：这是宿主 shim 对 `Path.mkdir(exist_ok=True)` 的处理缺陷（目标目录已存在仍转交宿主，宿主回 EEXIST），**不是模型缺失、也不是脚本 bug**——`~/.cache/speechbrain` 里的模型软链与 HF 缓存通常都是齐的。规避：在进程内垫一层「目标已是目录就直接放行」的 `Path.mkdir` / `os.makedirs` 补丁，再 `runpy.run_path` 执行本脚本；或换非 shim 终端跑。**不要删缓存目录**，也不要因此改用云端引擎。该补丁后可正常加载 ECAPA 声纹模型。

## 自检

```bash
python3 scripts/verify.py
python3 scripts/render_split.py --content examples/split-示例.json --check --out /tmp/t.html
```

前者逐项打印 PASS/FAIL（脚本语法、示例数据、六套皮肤渲染断链、产物占位符与串字、CSS 内容无关化、预览图尺寸、词库与语言表、出稿与引擎守门、AI 理解层闭环、资产层索引与分享包）；后者验证单页渲染与时间引用断链，应报 0 断链。

`verify.py` 不覆盖转写 / 说话人分离的重依赖链路，也不做浏览器像素级比对；新环境请按 `requirements.txt` 安装依赖后另跑一次端到端转写。平台页面结构变动会让取流失效，属正常失效，届时停用即可，不应改写成绕过行为。发布前的逐项核对见 `发布自查清单.md`。
