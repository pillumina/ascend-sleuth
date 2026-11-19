// 自动收尾读模型：失败项带 status/reason；没有本地草稿的不算待处理；
// .done 与 cleanup-log 分开统计；sweep-log 没写成功时用插件状态兜底。
import assert from 'node:assert'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { apply } from '../lib/index.js'

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'autoclose-failure-'))
const inbox = path.join(root, 'postmortems', 'inbox')
const groom = path.join(inbox, '.groom')
const done = path.join(inbox, '.done')
fs.mkdirSync(groom, { recursive: true })
fs.mkdirSync(path.join(done, 'E2E-DONE'), { recursive: true })
fs.mkdirSync(path.join(done, 'E2E-EXTRA'), { recursive: true })
fs.writeFileSync(path.join(inbox, 'E2E-FAIL.case.yaml'), 'cases: []\n')
fs.writeFileSync(path.join(inbox, 'E2E-LOCK.case.yaml'), 'cases: []\n')
const stateAt = '2026-11-11T09:10:00+08:00'
fs.writeFileSync(path.join(groom, 'pr-state.json'), JSON.stringify({
  schema: 'groom-pr-state/v1',
  prs: {
    'E2E-FAIL': { state: 'merged', url: 'https://example/pull/1', platform: 'github',
      repo: 'example/repo', number: 1, merge_commit: 'aaaaaaaaaaaa',
      checked_at: '2026-11-11T09:00:00+08:00' },
    'E2E-LOCK': { state: 'merged', url: 'https://example/pull/2', platform: 'github',
      repo: 'example/repo', number: 2, checked_at: '2026-11-11T09:00:01+08:00' },
    'E2E-NODRAFT': { state: 'merged', url: 'https://example/pull/3', platform: 'github',
      repo: 'example/repo', number: 3, checked_at: '2026-11-11T09:00:02+08:00' },
    'E2E-DONE': { state: 'merged', url: 'https://example/pull/4', platform: 'github',
      repo: 'example/repo', number: 4, checked_at: '2026-11-11T09:00:03+08:00' },
  },
}))
fs.writeFileSync(path.join(groom, 'sweep-log.jsonl'), JSON.stringify({
  at: '2026-11-11T09:00:00+08:00', source: 'plugin', ok: false, merged: 4,
  results: [{ draft: 'E2E-FAIL', drafts: ['E2E-FAIL'], status: 'failed', reason: 'boom from log' }],
}) + '\n')
fs.writeFileSync(path.join(groom, 'autoclose-state.json'), JSON.stringify({
  enabled: true,
  lastRun: stateAt,
  lastOk: false,
  lastSummary: '收尾失败：E2E-LOCK：ledger denied',
  lastFailure: { draft: 'E2E-LOCK', status: 'failed', reason: 'ledger denied' },
  failures: 2,
  paused: true,
  nextRun: '',
  firstRunConfirmed: false,
  firstRunPending: true,
  preview: { at: stateAt, total: 1, ready: [{ draft: 'E2E-FAIL', merge: 'aaaaaaaaaaaa' }],
    missing: 0, already: 0 },
  repo: 'D:\\repo',
  repoSource: 'plugin',
  python: 'python',
  intervalMinutes: 1440,
  intervalHours: 24,
}))
fs.writeFileSync(path.join(groom, 'cleanup-log.jsonl'), [
  { at: '2026-11-11T08:00:00+08:00', complete: false, ok: true,
    deleted: { assessments: ['E2E-DONE'] } },
  { at: '2026-11-11T08:01:00+08:00', complete: false, ok: true,
    deleted: { assessments: ['E2E-EXTRA'] } },
].map(entry => JSON.stringify(entry)).join('\n') + '\n')
fs.writeFileSync(path.join(groom, 'close-log.jsonl'), JSON.stringify({
  at: '2026-11-11T08:30:00+08:00', draft: 'E2E-FAIL', status: 'error',
  reason: 'manual boom',
}) + '\n')

const SESSION = { id: 'test', header: { cwd: root } }
const fsSvc = {
  resolve(target, opts) {
    const cwd = (opts && opts.cwd) || root
    return path.isAbsolute(String(target)) ? String(target) : path.resolve(cwd, String(target))
  },
  processPath(p) { return p },
  async readText(target) { return fs.readFileSync(target, 'utf8') },
  async listDir(target) {
    return fs.readdirSync(target, { withFileTypes: true }).map(entry => ({
      name: entry.name,
      type: entry.isDirectory() ? 'directory' : 'file',
      isDirectory: entry.isDirectory(),
    }))
  },
  async writeText(target, text) { fs.writeFileSync(target, text, 'utf8') },
  async mkdir(target) { fs.mkdirSync(target, { recursive: true }) },
}

let route = null
const webCtx = {
  effect: (fn) => { fn(); return () => {} },
  get: () => undefined,
  webServer: { register: (spec) => { route = spec.handler; return () => {} } },
}
const ctx = {
  get(name) {
    if (name === 'fs') return fsSvc
    if (name === 'sessions') return { list: () => [SESSION], get: () => SESSION }
    return undefined
  },
  inject(_deps, fn) { fn(webCtx) },
  effect() { return () => {} },
  tools: { register() {} },
}
apply(ctx)

function rpc(endpoint, payload) {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(JSON.stringify({
      type: 'client-request', rpcId: 'test', method: endpoint, payload,
    }))
    const req = {
      method: 'POST',
      url: `/ascend-sleuth-panels/${endpoint}`,
      headers: {},
      async *[Symbol.asyncIterator]() { yield body },
    }
    let out = ''
    const res = {
      setHeader() {},
      writeHead() {},
      end(chunk) { out += String(chunk || ''); resolve(JSON.parse(out)) },
    }
    try { route(req, res) } catch (error) { reject(error) }
  })
}

try {
  const response = await rpc('ascend-autoclose-state', { sessionId: 'test' })
  const data = (response.result && response.result.value) || (response.result || {})
  const fail = (data.pending || []).find(item => item.draft === 'E2E-FAIL')
  const lock = (data.pending || []).find(item => item.draft === 'E2E-LOCK')
  assert.ok(fail, 'E2E-FAIL 有本地草稿，应保留在待本地处理')
  assert.equal(fail.lastStatus, 'failed')
  assert.equal(fail.lastReason, 'boom from log')
  assert.equal(fail.mergeCommit, 'aaaaaaaaaaaa')
  assert.ok(lock, 'E2E-LOCK 有本地草稿，应保留在待本地处理')
  assert.equal(lock.lastStatus, 'failed', '没有日志的失败要从插件 lastFailure 兜底')
  assert.equal(lock.lastReason, 'ledger denied')
  assert.equal(data.counts.merged, 4)
  assert.equal(data.counts.pending, 2)
  assert.equal(data.counts.noDraft, 1)
  assert.equal(data.counts.closed, 2)
  assert.equal(data.counts.doneOnly, 1)
  assert.equal(data.counts.cleanupPending, 2)
  assert.equal((data.noDraft || [])[0].draft, 'E2E-NODRAFT')
  assert.equal((data.closed || [])[0].cleanupComplete, false)
  assert.equal(data.failures, 2, '连续失败次数应以插件状态为准')
  assert.equal(data.last && data.last.source, 'plugin')
  assert.equal(data.last && data.last.ok, false)
  assert.equal(data.last && data.last.at, stateAt)
  assert.equal(data.plugin && data.plugin.repo, 'D:\\repo')
  assert.equal(data.plugin && data.plugin.repoSource, 'plugin')
  assert.equal(data.plugin && data.plugin.python, 'python')
  assert.equal(data.plugin && data.plugin.lastFailure && data.plugin.lastFailure.draft, 'E2E-LOCK')
  assert.equal(data.plugin && data.plugin.firstRunPending, true)
  assert.equal(data.plugin && data.plugin.firstRunConfirmed, false)
  assert.equal(data.plugin && data.plugin.preview && data.plugin.preview.total, 1)
  assert.equal(data.lastCleanup && data.lastCleanup.deleted.assessments[0], 'E2E-EXTRA')
  assert.equal(data.lastCleanup && data.lastCleanup.complete, false)
  assert.equal((data.cleanupEntries || []).length, 2)
  assert.equal((data.manualErrors || [])[0].draft, 'E2E-FAIL')
  assert.equal((data.manualErrors || [])[0].reason, 'manual boom')
  console.log('dsh-sleuth-panels autoclose-failure-smoke: ok')
} finally {
  fs.rmSync(root, { recursive: true, force: true })
}
