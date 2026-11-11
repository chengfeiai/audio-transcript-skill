# 录音转写 · DSH 版说明

本包是 `audio-transcript-skill` 仓库的 **DSH 版**技能包。技能定义见 `SKILL.md`，完整命令与目录说明见 `安装说明.md`；本文件只交代版本、安装方式与分发边界，随包一起走，脱离 GitHub 页面也能看懂。

## 版本

- 版本标识：`v1.0.0-dsh`
- 技能包源码与仓库 `v1.0.0` 完全相同；这次发布只做版本标注、安装说明与分发形态，没有改动脚本、样式或模板，不是功能升级。
- 仓库：https://github.com/chengfeiai/audio-transcript-skill
- 发布页：https://github.com/chengfeiai/audio-transcript-skill/releases/tag/v1.0.0-dsh

## DSH 插件安装

本仓库提供 DSH 插件 bundle，安装后向技能注册表提供 `audio-transcript`，资源从插件包读取，不会自动安装转写依赖或模型。卸载插件会移除注册项，但不会删除用户手动创建的数据。转写功能需要 Apple Silicon macOS 和自行配置的 Python、模型等依赖；只生成交互纪要的渲染链路使用 Python 标准库。

## 手动安装 Skill

插件方式以 `audio-transcript` 注册技能；下述原始文件仅供支持原始技能名称的其他宿主使用，不能保证当前 DSH 文件系统扫描器接受中文技能名。

原始 `SKILL.md` 的 frontmatter：

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
