import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile, access } from 'node:fs/promises'
import { join } from 'node:path'
import { apply, inject } from '../dsh-plugin.js'

test('registers a loadable provider with the real skill and full resource base', async () => {
  let provider
  let disposed = false
  const dispose = () => { disposed = true }
  const ctx = { skills: { registerProvider(create) { provider = create({}); return dispose } } }
  assert.deepEqual(inject, ['skills'])
  assert.equal(apply(ctx), dispose)
  const [candidate] = await provider.list({})
  assert.match(candidate.name, /^[a-z0-9]+(?:-[a-z0-9]+)*$/)
  assert.equal(candidate.name, 'audio-transcript')
  assert.equal(candidate.provider, provider.name)
  assert.equal(candidate.rank, 600)
  assert.deepEqual(candidate.invocation, { modelInvocable: true, userInvocable: true })
  assert.equal(candidate.resourceBase.kind, 'directory')
  assert.equal(candidate.locator, candidate.path)
  const loaded = await provider.get(candidate, {})
  assert.ok(loaded.content.endsWith(await readFile(candidate.path, 'utf8')))
  assert.match(loaded.content, /技能调用名为 audio-transcript/)
  assert.match(loaded.content, /Base directory for this skill/)
  assert.match(loaded.content, /无需手动解压/)
  assert.equal(loaded.resourceBase.path, candidate.resourceBase.path)
  for (const resource of ['SKILL.md', 'scripts/verify.py', 'skins', 'templates', 'assets', 'requirements.txt']) {
    await access(join(loaded.resourceBase.path, resource))
  }
  dispose()
  assert.equal(disposed, true)
})

test('read respects cancellation and missing files are not silently registered as loaded', async () => {
  let provider
  apply({ skills: { registerProvider(create) { provider = create({}); return () => {} } } })
  const [candidate] = await provider.list()
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(provider.get(candidate, { signal: controller.signal }), { name: 'AbortError' })
})
