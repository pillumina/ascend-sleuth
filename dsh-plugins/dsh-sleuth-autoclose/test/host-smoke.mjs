// dsh-sleuth-autoclose host 冒烟：定时器、开关、无 repo、连续失败暂停、状态文件、清理。
// 不依赖 DSH：fake ctx 只提供 get('shell') 与 effect()。

import assert from 'node:assert'
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from '../lib/index.js'

const calls = []
const disposers = []

function fakeCtx(result = { ok: true, merged: 1, results: [{ status: 'closed' }] }) {
  return {
    get(name) {
      if (name !== 'shell') return undefined
      return {
        async run(spec) {
          if (String(spec.command).includes('import sys, yaml')) {
            return { exitCode: 0, stdout: { text: '3.12.0' }, stderr: { text: '' } }
          }
          calls.push(spec)
          if (result instanceof Error) throw result
          return { exitCode: 0, stdout: { text: JSON.stringify(result) } }
        },
      }
    },
    effect(fn) {
      disposers.push(fn)
      return () => {}
    },
  }
}

function cleanupTimers() {
  for (const fn of disposers) fn()()
  disposers.length = 0
}

// 常开：每次 sweep 调一次脚本，参数与工作目录对得上，状态写进 inbox 的 .groom。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, intervalHours: 24,
                                    checkOnStart: false })
  assert.equal(plugin.state.enabled, true)
  const result = await plugin.sweep()
  assert.equal(result.ok, true)
  assert.equal(calls.length, 1)
  assert.ok(calls[0].command.includes('groom_sweep.py'))
  assert.equal(calls[0].workdir, dir)
  assert.ok(calls[0].command.includes('--source plugin'))
  const saved = JSON.parse(await readFile(
    join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-state.json'), 'utf8'))
  assert.equal(saved.lastOk, true)
  assert.ok(saved.lastRun)
  assert.ok(saved.nextRun)
  cleanupTimers()
  calls.length = 0
}

// 首次运行先 dry-run；面板确认后才带 --apply。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const configFile = join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-config.json')
  const plugin = apply(fakeCtx({
    ok: true, merged: 1, checked: 1,
    results: [{ draft: 'd1', drafts: ['d1'], status: 'ready', merge: 'aaaaaaaaaaaa' }],
  }), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(plugin.state.firstRunPending, true)
  assert.equal(plugin.state.firstRunConfirmed, false)
  assert.equal(plugin.state.preview.total, 1)
  assert.equal(plugin.state.preview.ready[0].draft, 'd1')
  assert.ok(!calls[0].command.includes('--apply'), '首次预览不能带 --apply')
  await writeFile(configFile, JSON.stringify({ confirmFirstRun: true, intervalMinutes: 1440 }))
  const before = calls.length
  await plugin.configTick()
  assert.equal(calls.length, before + 1)
  assert.ok(calls[calls.length - 1].command.includes('--apply'), '确认后要带 --apply')
  assert.equal(plugin.state.firstRunConfirmed, true)
  assert.equal(plugin.state.firstRunPending, false)
  assert.equal(plugin.state.preview, null)
  const savedConfig = JSON.parse(await readFile(configFile, 'utf8'))
  assert.equal(savedConfig.confirmFirstRun, undefined)
  cleanupTimers()
  calls.length = 0
}

// 立即运行一次：即使已暂停也强制执行一轮；不改变暂停状态。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const configFile = join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-config.json')
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  plugin.state.firstRunConfirmed = true
  plugin.state.firstRunPending = false
  plugin.state.preview = null
  plugin.state.paused = true
  plugin.state.failures = 2
  await writeFile(configFile, JSON.stringify({ runNow: true, intervalMinutes: 1440 }))
  const before = calls.length
  await plugin.configTick()
  assert.equal(calls.length, before + 1)
  assert.ok(calls[calls.length - 1].command.includes('--apply'))
  assert.equal(plugin.state.paused, true, '立即运行一次不改变暂停状态')
  assert.equal(plugin.state.failures, 2, '强制成功不抹掉暂停时的失败计数')
  const savedConfig = JSON.parse(await readFile(configFile, 'utf8'))
  assert.equal(savedConfig.runNow, undefined)
  cleanupTimers()
  calls.length = 0
}

// 无 repo：不跑，返回原因。
{
  const plugin = apply(fakeCtx(), { enabled: true, repo: '', discover: false,
                                    checkOnStart: false })
  const result = await plugin.sweep()
  assert.equal(result.reason, 'no-repo')
  assert.equal(calls.length, 0)
  cleanupTimers()
}

// 关闭：不跑。
{
  const plugin = apply(fakeCtx(), { enabled: false, repo: '/tmp/repo', checkOnStart: false })
  const result = await plugin.sweep()
  assert.equal(result.skipped, true)
  assert.equal(calls.length, 0)
  cleanupTimers()
}

// 失败摘要：失败项取 results[].reason，状态里留 lastFailure，面板可直接显示。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx({
    ok: false, merged: 1,
    results: [{ draft: 'd1', drafts: ['d1'], status: 'failed', reason: 'worktree boom' }],
  }), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  // checkOnStart:false 时启动仍会按 0ms 定时器补跑一次；这里断言那一轮的摘要。
  assert.equal(plugin.state.lastFailure.draft, 'd1')
  assert.equal(plugin.state.lastFailure.status, 'failed')
  assert.equal(plugin.state.lastFailure.reason, 'worktree boom')
  assert.match(plugin.state.lastSummary, /收尾失败：d1：worktree boom/)
  assert.equal(plugin.state.failures, 1)
  const saved = JSON.parse(await readFile(
    join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-state.json'), 'utf8'))
  assert.equal(saved.lastFailure.reason, 'worktree boom')
  assert.equal(calls.length, 1)
  cleanupTimers()
  calls.length = 0
}

// cleanup-failed 用「清理未完成」前缀，不再把 cleanup 报告贴成 JSON 尾巴。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx({
    ok: false, merged: 1,
    results: [{ draft: 'd2', status: 'cleanup-failed', reason: 'cleanup boom' }],
    cleanup: { ok: false, findings: [{ severity: 'error', message: 'cleanup boom' }] },
  }), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(plugin.state.lastFailure.status, 'cleanup-failed')
  assert.equal(plugin.state.lastFailure.draft, 'd2')
  assert.match(plugin.state.lastSummary, /清理未完成：d2：cleanup boom/)
  cleanupTimers()
  calls.length = 0
}

// 不是 sweep 结果、而是 shell 自己失败时，lastFailure 记 shell-error。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx(new Error('shell boom')), { enabled: true, repo: dir,
                                                           checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(plugin.state.lastFailure.status, 'shell-error')
  assert.equal(plugin.state.lastFailure.reason, 'shell boom')
  assert.match(plugin.state.lastSummary, /运行失败：shell boom/)
  cleanupTimers()
  calls.length = 0
}

// 连续失败 3 次后暂停，暂停状态写进状态文件。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx(new Error('boom')), { enabled: true, repo: dir,
                                                     checkOnStart: false })
  // 等启动微任务把 Python 探测与 loadState 走完，避免第一次 sweep 撞上 no-python。
  await new Promise((resolve) => setTimeout(resolve, 800))
  // 启动那轮也会算一次失败；清零后只数下面 3 次手动失败。
  plugin.state.failures = 0
  for (let index = 0; index < 3; index += 1) {
    const result = await plugin.sweep()
    assert.equal(result.ok, false)
  }
  assert.equal(plugin.state.failures, 3)
  assert.equal(plugin.state.lastFailure.status, 'shell-error')
  assert.match(plugin.state.lastSummary, /运行失败：boom/)
  assert.equal(plugin.state.paused, true)
  const paused = await plugin.sweep()
  assert.equal(paused.reason, 'paused')
  const saved = JSON.parse(await readFile(
    join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-state.json'), 'utf8'))
  assert.equal(saved.paused, true)
  assert.equal(saved.lastFailure.status, 'shell-error')
  // 暂停态写盘不能残留「下次运行」：写入路径的 nextRun 清空也要钉住。
  assert.equal(saved.nextRun, '')
  cleanupTimers()
}

// 停用：即使状态文件里是 enabled=true，也要发布当前开关并清掉下次运行时间。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  const stateFile = join(stateDir, 'autoclose-state.json')
  await writeFile(stateFile, JSON.stringify({ enabled: true, nextRun: '2026-11-10T00:00:00Z' }))
  apply(fakeCtx(), { enabled: false, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  const saved = JSON.parse(await readFile(stateFile, 'utf8'))
  assert.equal(saved.enabled, false)
  assert.equal(saved.nextRun, '')
  cleanupTimers()
}

// 暂停后 resume：清掉 paused 与 failures 并写回状态文件。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: false })
  // 等启动微任务落定（它也会写状态文件），避免与 resume 的写并发交错。
  await new Promise((resolve) => setTimeout(resolve, 20))
  plugin.state.paused = true
  plugin.state.failures = 3
  await plugin.resume()
  assert.equal(plugin.state.paused, false)
  assert.equal(plugin.state.failures, 0)
  const saved = JSON.parse(await readFile(
    join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-state.json'), 'utf8'))
  assert.equal(saved.paused, false)
  assert.equal(saved.failures, 0)
  cleanupTimers()
}

// 面板恢复：配置文件里的 resume: true 在启动时清暂停，并删掉这把一次性钥匙。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  const stateFile = join(stateDir, 'autoclose-state.json')
  const configFile = join(stateDir, 'autoclose-config.json')
  await writeFile(stateFile, JSON.stringify({ enabled: true, paused: true, failures: 3 }))
  await writeFile(configFile, JSON.stringify({ resume: true, intervalMinutes: 1440 }))
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(plugin.state.paused, false)
  assert.equal(plugin.state.failures, 0)
  const savedConfig = JSON.parse(await readFile(configFile, 'utf8'))
  assert.equal(savedConfig.resume, undefined, 'resume 是一次性钥匙，读过要删掉')
  const saved = JSON.parse(await readFile(stateFile, 'utf8'))
  assert.equal(saved.paused, false)
  cleanupTimers()
}

// 运行中恢复：configTick 读到 resume 后立即 sweep，不能等 lastRun + 24 小时。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  const configFile = join(stateDir, 'autoclose-config.json')
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 300))
  plugin.state.paused = true
  plugin.state.failures = 2
  await writeFile(configFile, JSON.stringify({ resume: true, intervalMinutes: 1440 }))
  const before = calls.length
  await plugin.configTick()
  assert.equal(calls.length, before + 1, '恢复后应立即 sweep，而不是等 lastRun + 间隔')
  assert.equal(plugin.state.paused, false)
  assert.equal(plugin.state.failures, 0)
  const savedConfig = JSON.parse(await readFile(configFile, 'utf8'))
  assert.equal(savedConfig.resume, undefined)
  cleanupTimers()
  calls.length = 0
}

// 重启后的首次触发按上次运行时间算：23 小时前跑过，约 1 小时后跑，不是 24 小时后。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  await writeFile(join(stateDir, 'autoclose-state.json'), JSON.stringify({
    enabled: true,
    lastRun: new Date(Date.now() - 23 * 3_600_000).toISOString(),
  }))
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: true })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.equal(calls.length, 0)
  const ahead = Date.parse(plugin.state.nextRun) - Date.now()
  assert.ok(ahead > 30 * 60_000 && ahead < 90 * 60_000,
    'nextRun 应约 1 小时后，实际 ' + ahead + 'ms')
  cleanupTimers()
  calls.length = 0
}

// 已到期（25 小时前跑过）：启动立即补跑。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  await writeFile(join(stateDir, 'autoclose-state.json'), JSON.stringify({
    enabled: true,
    lastRun: new Date(Date.now() - 25 * 3_600_000).toISOString(),
  }))
  apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: true })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.equal(calls.length, 1)
  cleanupTimers()
  calls.length = 0
}

// 卸载发生在 sweep 进行中：回调返回后不能再建 interval。
{
  calls.length = 0
  let release = null
  const hangingCtx = {
    get(name) {
      if (name !== 'shell') return undefined
      return {
        run(spec) {
          if (String(spec.command).includes('import sys, yaml')) {
            return Promise.resolve({ exitCode: 0, stdout: { text: '3.12.0' }, stderr: { text: '' } })
          }
          calls.push(spec)
          return new Promise((resolve) => {
            release = () => resolve({ exitCode: 0, stdout: { text: JSON.stringify({ ok: true }) } })
          })
        },
      }
    },
    effect(fn) { disposers.push(fn); return () => {} },
  }
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(hangingCtx, { enabled: true, repo: dir, checkOnStart: false })
  plugin.scheduleNext()
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.ok(release, 'sweep 应在进行中')
  cleanupTimers()
  release()
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(plugin.isRunning(), false)
  calls.length = 0
}

// 从持久化暂停恢复：resume 要重新安排执行，而不只是改状态。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  await writeFile(join(stateDir, 'autoclose-state.json'), JSON.stringify({
    enabled: true, paused: true, failures: 3,
  }))
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: true })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.equal(plugin.isRunning(), false)
  assert.equal(plugin.state.paused, true)
  // 暂停态不应残留「下次运行」时间（面板会显示一个永远不会发生的计划）。
  assert.equal(plugin.state.nextRun, '')
  await plugin.resume()
  assert.equal(plugin.state.paused, false)
  assert.equal(plugin.isRunning(), true)
  assert.ok(plugin.state.nextRun)
  cleanupTimers()
  calls.length = 0
}

// 周期运行后 nextRun 要跟着更新，不能停在首次计划时间。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(fakeCtx(), { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  const before = plugin.state.nextRun
  await plugin.sweep()
  const after = plugin.state.nextRun
  assert.notEqual(after, before)
  assert.ok(Date.parse(after) > Date.now() + 23 * 3_600_000)
  cleanupTimers()
  calls.length = 0
}

// 面板只改间隔：配置文件没有 enabled 时，不能把 profile 的关闭状态改成开。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  await writeFile(join(stateDir, 'autoclose-config.json'),
    JSON.stringify({ intervalMinutes: 60 }))
  const plugin = apply(fakeCtx(), { enabled: false, repo: dir, checkOnStart: false })
  await plugin.loadConfig()
  assert.equal(plugin.state.enabled, false)
  assert.equal(plugin.state.intervalMinutes, 60)
  cleanupTimers()
}

// 两轮 sweep 不能并发：第一轮未结束时，第二轮直接跳过。
{
  calls.length = 0
  let release = null
  const hangingCtx = {
    get(name) {
      if (name !== 'shell') return undefined
      return {
        run(spec) {
          if (String(spec.command).includes('import sys, yaml')) {
            return Promise.resolve({ exitCode: 0, stdout: { text: '3.12.0' }, stderr: { text: '' } })
          }
          calls.push(spec)
          return new Promise((resolve) => {
            release = () => resolve({ exitCode: 0, stdout: { text: JSON.stringify({ ok: true }) } })
          })
        },
      }
    },
    effect(fn) { disposers.push(fn); return () => {} },
  }
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(hangingCtx, { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.ok(release, '第一次 sweep 应在进行中')
  const second = await plugin.sweep()
  assert.equal(second.reason, 'in-flight')
  assert.equal(calls.length, 1)
  release()
  await new Promise((resolve) => setTimeout(resolve, 300))
  cleanupTimers()
  calls.length = 0
}

// 运行中改间隔：旧回调结束后不能再建第二个周期定时器。
{
  calls.length = 0
  const intervals = new Set()
  const realSetInterval = globalThis.setInterval
  const realClearInterval = globalThis.clearInterval
  globalThis.setInterval = (fn, ms) => {
    const id = realSetInterval(fn, ms)
    intervals.add(id)
    return id
  }
  globalThis.clearInterval = (id) => {
    intervals.delete(id)
    return realClearInterval(id)
  }
  let release = null
  let first = true
  const hangingCtx = {
    get(name) {
      if (name !== 'shell') return undefined
      return {
        run(spec) {
          if (String(spec.command).includes('import sys, yaml')) {
            return Promise.resolve({ exitCode: 0, stdout: { text: '3.12.0' }, stderr: { text: '' } })
          }
          calls.push(spec)
          if (first) {
            first = false
            return new Promise((resolve) => {
              release = () => resolve({ exitCode: 0, stdout: { text: JSON.stringify({ ok: true }) } })
            })
          }
          return Promise.resolve({ exitCode: 0, stdout: { text: JSON.stringify({ ok: true }) } })
        },
      }
    },
    effect(fn) { disposers.push(fn); return () => {} },
  }
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-'))
  const plugin = apply(hangingCtx, { enabled: true, repo: dir, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.ok(release, '第一次 sweep 应在进行中')
  plugin.scheduleNext()
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(intervals.size, 1, '改间隔后应只剩一个周期定时器')
  release()
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.equal(intervals.size, 1, '旧回调结束后不能新建定时器')
  cleanupTimers()
  assert.equal(intervals.size, 0, '卸载后不应残留周期定时器')
  globalThis.setInterval = realSetInterval
  globalThis.clearInterval = realClearInterval
  calls.length = 0
}

// 不配 repo：按会话 cwd 自动发现检出，并在启动时跑一次。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-discover-'))
  await mkdir(join(dir, 'scripts'), { recursive: true })
  await writeFile(join(dir, 'scripts', 'groom_sweep.py'), '')
  await mkdir(join(dir, 'postmortems', 'inbox'), { recursive: true })
  const ctx = {
    get(name) {
      if (name === 'sessions') return { list: () => [{ header: { cwd: dir } }] }
      if (name !== 'shell') return undefined
      return {
        async run(spec) {
          if (String(spec.command).includes('import sys, yaml')) {
            return { exitCode: 0, stdout: { text: '3.12.0' }, stderr: { text: '' } }
          }
          calls.push(spec)
          return { exitCode: 0, stdout: { text: JSON.stringify({ ok: true }) } }
        },
      }
    },
    effect(fn) { disposers.push(fn); return () => {} },
  }
  const plugin = apply(ctx, { discover: true, checkOnStart: false, runOnStart: true })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.equal(plugin.state.repo, dir)
  assert.equal(calls.length, 1, 'runOnStart 应在启动后跑一次')
  assert.equal(calls[0].workdir, dir)
  assert.ok(calls[0].command.includes('groom_sweep.py'))
  cleanupTimers()
  calls.length = 0
}

// 1 分钟：状态里的 intervalHours 不能是 0（面板会误显示 24 小时）。
{
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-minutes-'))
  const plugin = apply(fakeCtx(), { repo: dir, intervalMinutes: 1, checkOnStart: false })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.equal(plugin.state.intervalMinutes, 1)
  assert.equal(plugin.state.intervalHours, 0.0167)
  const saved = JSON.parse(await readFile(
    join(dir, 'postmortems', 'inbox', '.groom', 'autoclose-state.json'), 'utf8'))
  assert.equal(saved.intervalMinutes, 1)
  assert.equal(saved.intervalHours, 0.0167)
  cleanupTimers()
}

// 卸载：已经排好的 timeout 也要清掉，不能在卸载后再触发 sweep。
{
  calls.length = 0
  const dir = await mkdtemp(join(tmpdir(), 'autoclose-unload-'))
  const stateDir = join(dir, 'postmortems', 'inbox', '.groom')
  await mkdir(stateDir, { recursive: true })
  await writeFile(join(stateDir, 'autoclose-state.json'), JSON.stringify({
    enabled: true,
    lastRun: new Date().toISOString(),
  }))
  const plugin = apply(fakeCtx(), { repo: dir, intervalMinutes: 1, checkOnStart: true })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  assert.equal(plugin.isRunning(), true)
  cleanupTimers()
  assert.equal(plugin.isRunning(), false)
  await new Promise((resolve) => setTimeout(resolve, 1200))
  assert.equal(calls.length, 0, '卸载后不能再触发 sweep')
}

console.log('dsh-sleuth-autoclose host-smoke: ok')
// 测试创建的 24 小时 timer 在部分分支不会自然到期；断言全过后直接退出。
process.exit(0)
