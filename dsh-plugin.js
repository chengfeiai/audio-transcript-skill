import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

export const name = 'audio-transcript-skill'
export const inject = ['skills']

const root = fileURLToPath(new URL('./', import.meta.url))
const skillPath = fileURLToPath(new URL('./SKILL.md', import.meta.url))
const providerName = 'audio-transcript-skill'
const summary = {
  name: 'audio-transcript',
  description: '转写录音或公开短视频音轨，生成带时间戳的文字稿和交互式纪要；支持说话人分离及本地优先的转写流程。',
  provider: providerName,
  source: 'bundled',
  invocation: { modelInvocable: true, userInvocable: true },
  path: skillPath,
  resourceBase: { kind: 'directory', path: root },
}

export function apply(ctx) {
  return ctx.skills.registerProvider(() => ({
    name: providerName,
    async list() {
      return [{ ...summary, rank: 600, locator: skillPath }]
    },
    async get(_candidate, options = {}) {
      const content = await readFile(skillPath, { encoding: 'utf8', signal: options.signal })
      const preface = 'DSH 插件适配说明：技能调用名为 audio-transcript。使用本技能时，将下文命令中的 SKILL 设为上方 <skill_resources> 中 Base directory for this skill 给出的实际目录绝对路径，并在 shell 中安全引用。无需手动解压或复制到 profile skills 目录；忽略正文中与此冲突的安装说明及“<解压后的绝对路径>”占位值。\n\n'
      return { ...summary, content: preface + content }
    },
  }))
}
