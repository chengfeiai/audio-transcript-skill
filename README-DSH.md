# 录音转写 · DSH 版说明

本包是 `audio-transcript-skill` 仓库的 **DSH 版**技能包。技能定义见 `SKILL.md`，完整命令与目录说明见 `安装说明.md`；本文件只交代版本、安装方式与分发边界，随包一起走，脱离 GitHub 页面也能看懂。

## 版本

- 版本标识：`v1.0.0-dsh`
- 技能包源码与仓库 `v1.0.0` 完全相同；这次发布只做版本标注、安装说明与分发形态，没有改动脚本、样式或模板，不是功能升级。
- 仓库：https://github.com/chengfeiai/audio-transcript-skill
- 发布页：https://github.com/chengfeiai/audio-transcript-skill/releases/tag/v1.0.0-dsh

## 在 DSH 中安装

1. 解压出 `录音转写/` 文件夹。
2. 把整个文件夹放进当前 DSH profile 的 skills 目录（默认 `~/.dsh/skills/`）。
3. 重新加载后即可通过技能名 `录音转写` 调用。

`SKILL.md` 的 frontmatter 按 DSH 约定组织：

```yaml
---
name: 录音转写
metadata:
  version: 1.0.0-dsh
  edition: DSH
  language: zh-CN
description: ...
---
```

转写链路依赖按 `requirements.txt` 自备（需要装有 `mlx-whisper` 等依赖的 Python 3.11）；渲染器只用系统 `python3`，零额外依赖。不使用 DSH 也可以按 `SKILL.md` 的命令行流程使用同一套脚本。

## 自检

```bash
python3 scripts/verify.py
```

115 项离线断言，当前全 PASS / 0 FAIL。它不覆盖转写与说话人分离的重依赖链路，也不做浏览器像素级比对。

## 与 WorkBuddy 版的区别

两者源码完全一致，差别只在分发形态与安装说明：

| 项目 | DSH 版 | WorkBuddy 版 |
|---|---|---|
| 版本标识 | `v1.0.0-dsh` | `v1.4.1-workbuddy` |
| frontmatter | `metadata.version` 嵌套 | 顶部 `name` + `description` |
| 安装位置 | `~/.dsh/skills/` | WorkBuddy profile 的 skills 目录 |
| 调用方式 | 技能名 `录音转写` | `@skill:"录音转写"` |

## 边界（转发时请一并保留）

- 本包不含 `LICENSE`。授权见仓库根目录 `LICENSE`（MIT），转发时请一并附上；第三方库与模型各有自己的许可。
- 默认全本地，不上传音频或转写正文；启用云端能力必须显式确认。
- 转写与说话人分离会有误，姓名、事实、说话人归属须对照原音核验。
- 运行时产物（录音、转写稿、纪要页）含真实内容，不随包发布。
- 公开短视频分享链接取流仅用于公开可播放内容，不绕过登录、付费墙或风控。
- 不宣称准确率，未引用任何第三方评测数字。
