// Host 半冒烟（开发用，不进安装产物）：用假的 cordis ctx 装起 lib/index.js，
// 拿它注册的路由直接发请求，走真实的 shell → Python → JSON 链路。
//
// 跑法：node dsh-plugins/dsh-sleuth-copilot/test/host-smoke.mjs
// 它证明不了浏览器的会话 cookie 与页面渲染；证明的是：路由注册、取数链路、能力位、
// 状态写入的真实参数与返回（写操作全部在系统临时目录里的 trace 副本上做，仓库不被改）。

import { exec } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const REPO = join(ROOT, '..', '..')
const TRACE_ID = '2026-09-08-copilot-smoke'
const TRACE_FILE = TRACE_ID + '.yaml'
// 自带一份最小 trace：CI 与 worktree 里都没有 traces/（运行时件、gitignored），
// 冒烟不能依赖主检出的真实数据。字段按 skills/diagnose 的 trace 形状写。
const TRACE_FIXTURE = [
  'session_id: "' + TRACE_ID + '"',
  'status: in_progress',
  'current_step: 3',
  'summary: "Copilot host smoke 夹具：验证取数、能力位与状态写入；不依赖真实 traces/。"',
  'created_at: "2026-09-08T15:29:00+08:00"',
  'updated_at: "2026-09-08T15:29:00+08:00"',
  'detected_framework: vllm-ascend',
  'detected_platform: A3-910C',
  'detected_category: interrupt',
  'feedback:',
  '  case: ""',
  '  outcome: pending',
  '  confirmed_at: ""',
  'sedimented:',
  '  state: none',
  '  case_id: ""',
  'active_case: ""',
  'excluded_cases: []',
  'report_file: "alt-smoke.md"',
  'sediment_candidates:',
  '  - kind: case',
  '    summary: "夹具候选：vendor TopKV2 kernel 崩溃"',
  'trace:',
  '  - role: user',
  '    step: 1',
  '    content: "夹具用户事件"',
  '    evidence:',
  '      inline: "夹具证据"',
  '      files: ["traces/evidence/2026-09-08-copilot-smoke/crash.log"]',
  '      missing: "缺 device plog；首次崩溃 16h"',
  '  - role: agent',
  '    step: 2',
  '    action: triage',
  '    output: "夹具输出"',
  '    reason: "夹具原因"',
  '',
].join('\n')

// ── 临时检出：scripts / knowledge / trace-status.yaml 走符号链接，traces 用自带夹具 ──
const SANDBOX = mkdtempSync(join(tmpdir(), 'scp-host-'))
mkdirSync(join(SANDBOX, 'traces'))
symlinkSync(join(REPO, 'scripts'), join(SANDBOX, 'scripts'), 'dir')
symlinkSync(join(REPO, 'knowledge'), join(SANDBOX, 'knowledge'), 'dir')
copyFileSync(join(REPO, 'trace-status.yaml'), join(SANDBOX, 'trace-status.yaml'))
writeFileSync(join(SANDBOX, 'traces', TRACE_FILE), TRACE_FIXTURE, 'utf8')
writeFileSync(join(SANDBOX, 'traces', 'alt-smoke.md'), '# 诊断报告\n根因：夹具里的 vendor TopKV2 kernel。\n', 'utf8')
const TRACES = join(SANDBOX, 'traces')

function runCommand(spec) {
  return new Promise((resolve) => {
    const child = exec(spec.command, {
      cwd: spec.workdir,
      timeout: spec.timeoutMs || 30000,
      maxBuffer: 8 * 1024 * 1024,
      env: Object.assign({}, process.env, spec.env || {}),
    }, (error, stdout, stderr) => {
      resolve({
        exitCode: error && typeof error.code === 'number' ? error.code : (error ? 1 : 0),
        timedOut: Boolean(error && error.killed),
        stdout: { text: stdout || '' },
        stderr: { text: stderr || '' },
      })
    })
    child.on('error', () => {
      resolve({ exitCode: 127, timedOut: false, stdout: { text: '' }, stderr: { text: 'exec failed' } })
    })
  })
}

function makeShell() {
  return {
    resolve(request) {
      return request
    },
    async execute(spec) {
      return { result: () => runCommand(spec) }
    },
  }
}

function makeHarness(ctxExtra) {
  let route = null
  const effects = []
  const webCtx = {
    effect(fn) {
      const cleanup = fn()
      if (typeof cleanup === 'function') effects.push(cleanup)
      return cleanup
    },
    get(name) {
      if (name === 'connection') return { requestRejection: () => undefined }
      return undefined
    },
    webServer: {
      register(definition) {
        route = definition
        return () => { route = null }
      },
    },
  }
  const ctx = Object.assign({
    effect(fn) {
      const cleanup = fn()
      if (typeof cleanup === 'function') effects.push(cleanup)
      return cleanup
    },
    get(name) {
      if (name === 'shell') return makeShell()
      if (name === 'connection') return { rpc: {} }
      if (ctxExtra && ctxExtra[name] !== undefined) return ctxExtra[name]
      return undefined
    },
    inject(_services, callback) {
      callback(webCtx)
    },
  }, {})
  return { ctx, webCtx, getRoute: () => route, effects }
}

function makeRequest(body, url) {
  return {
    method: 'POST',
    url: url || '/sleuth-copilot/copilot-state',
    async *[Symbol.asyncIterator]() {
      yield Buffer.from(JSON.stringify(body), 'utf8')
    },
  }
}

function makeResponse() {
  const captured = { status: 0, headers: {}, body: '' }
  return {
    captured,
    setHeader(name, value) {
      captured.headers[name.toLowerCase()] = value
    },
    writeHead(status) {
      captured.status = status
    },
    end(chunk) {
      if (chunk !== undefined) captured.body += String(chunk)
    },
  }
}

async function transition(harness, payload, rpcId) {
  return request(harness, {
    type: 'client-request', rpcId: rpcId || 'write', method: 'copilot-transition', payload,
  }, '/sleuth-copilot/copilot-transition')
}

async function readReport(harness, payload, rpcId) {
  return request(harness, {
    type: 'client-request', rpcId: rpcId || 'report', method: 'copilot-report', payload,
  }, '/sleuth-copilot/copilot-report')
}

async function request(harness, body, url) {
  const response = makeResponse()
  await harness.getRoute().handler(makeRequest(body, url), response)
  let envelope = null
  try {
    envelope = JSON.parse(response.captured.body)
  } catch {
    envelope = null
  }
  return { status: response.captured.status, envelope }
}

let failures = 0
let checks = 0
function expect(name, condition, detail) {
  checks += 1
  if (condition) process.stdout.write('  ok   ' + name + '\n')
  else {
    failures += 1
    process.stdout.write('  FAIL ' + name + (detail ? ' — ' + detail : '') + '\n')
  }
}

const mod = await import(join(ROOT, 'lib', 'index.js'))
if (mod.name !== 'dsh-sleuth-copilot') throw new Error('unexpected plugin name')

process.stdout.write('诊断状态条 · Host 冒烟\n')

// ── 可写会话 ────────────────────────────────────────────────────────────────
const rw = makeHarness({})
mod.apply(rw.ctx)
expect('路由注册成功', !!rw.getRoute())

const state = await request(rw, {
  type: 'client-request', rpcId: 'state-1', method: 'copilot-state',
  payload: { sessionId: 'smoke-session', cwd: SANDBOX },
})
expect('读：HTTP 200', state.status === 200)
const stateValue = state.envelope && state.envelope.result && state.envelope.result.value
expect('读：可写能力位', stateValue && stateValue.capabilities && stateValue.capabilities.canWrite === true, JSON.stringify(stateValue && stateValue.capabilities))
expect('读：全库列表非空', stateValue && Array.isArray(stateValue.all) && stateValue.all.length === 1)
expect('读：traces 目录指向副本', stateValue && stateValue.tracesDir === TRACES, stateValue && stateValue.tracesDir)
const row = stateValue && stateValue.all && stateValue.all[0]
expect('读：带内容指纹', row && /^[0-9a-f]{64}$/.test(row.contentSha256))
expect('读：带上游查询能力位', stateValue && stateValue.upstream && typeof stateValue.upstream.ready === 'boolean', JSON.stringify(stateValue && stateValue.upstream))
expect('读：证据文件清单', row && Array.isArray(row.extra.evidenceList) && row.extra.evidenceList.length === 1 && row.extra.evidenceList[0].includes('crash.log'), JSON.stringify(row && row.extra))
expect('读：沉淀候选清单', row && Array.isArray(row.extra.sedimentCandidateList) && row.extra.sedimentCandidateList[0].summary.includes('TopKV2'), JSON.stringify(row && row.extra))
expect('读：缺失材料清单', row && Array.isArray(row.extra.missingMaterials) && row.extra.missingMaterials[0].includes('device plog'), JSON.stringify(row && row.extra.missingMaterials))
expect('读：按顶层 report_file 识别报告', row && row.extra.hasReport === true && row.reportFile === 'traces/alt-smoke.md')
const originalSha = row.contentSha256

// 人读报告：只读，不写回；不存在时给 E_NOT_FOUND
const reportRead = await readReport(rw, {
  cwd: SANDBOX, tracesDir: TRACES, traceSessionId: TRACE_ID, reportFile: row.reportFile,
}, 'report-1')
const reportValue = reportRead.envelope && reportRead.envelope.result && reportRead.envelope.result.value
expect('报告：读到内容', reportValue && reportValue.ok === true && reportValue.text.includes('TopKV2 kernel'), JSON.stringify(reportValue))
const timelineRead = await request(rw, {
  type: 'client-request', rpcId: 'timeline-1', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: TRACE_FILE },
}, '/sleuth-copilot/copilot-timeline')
const timelineValue = timelineRead.envelope && timelineRead.envelope.result && timelineRead.envelope.result.value
expect('时间线：读到步骤', timelineValue && timelineValue.ok === true && Array.isArray(timelineValue.timeline) && timelineValue.timeline.length >= 2, JSON.stringify(timelineValue))
expect('时间线：角色与动作', timelineValue && timelineValue.timeline[0].role === 'user' && timelineValue.timeline[1].action === 'triage', JSON.stringify(timelineValue && timelineValue.timeline))
const timelineBad = await request(rw, {
  type: 'client-request', rpcId: 'timeline-2', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: '../x.yaml' },
}, '/sleuth-copilot/copilot-timeline')
expect('时间线：非法文件名被拒', timelineBad.envelope.result.value.ok === false && timelineBad.envelope.result.value.code === 'E_SCHEMA')
const reportMissing = await readReport(rw, { cwd: SANDBOX, tracesDir: TRACES, traceSessionId: '2026-01-01-no-such' }, 'report-2')
const missingValue = reportMissing.envelope && reportMissing.envelope.result && reportMissing.envelope.result.value
expect('报告：不存在时 E_NOT_FOUND', missingValue && missingValue.ok === false && missingValue.code === 'E_NOT_FOUND', JSON.stringify(missingValue))
const reportTraversal = await readReport(rw, {
  cwd: SANDBOX, tracesDir: TRACES, traceSessionId: TRACE_ID, reportFile: '../etc/passwd',
}, 'report-3')
const traversalValue = reportTraversal.envelope && reportTraversal.envelope.result && reportTraversal.envelope.result.value
expect('报告：路径穿越被拒 E_SCHEMA', traversalValue && traversalValue.ok === false && traversalValue.code === 'E_SCHEMA', JSON.stringify(traversalValue))

// 收尾：已定位
const closeResult = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: originalSha,
    kind: 'close', to: 'resolved', endingKind: 'root_cause',
    severity: 'service-affecting', fix_emitted: true,
  }, 'write-1')
const closed = closeResult.envelope && closeResult.envelope.result && closeResult.envelope.result.value
expect('写收尾：ok', closed && closed.ok === true, JSON.stringify(closed))
expect('写收尾：状态变已定位', closed && closed.to === 'resolved')
expect('写收尾：返回新指纹', closed && closed.current && /^[0-9a-f]{64}$/.test(closed.current.sha256))
const afterClose = readFileSync(join(TRACES, TRACE_FILE), 'utf8')
expect('写收尾：文件已落盘', /status: "?resolved"?/.test(afterClose) && /transitions:/.test(afterClose), (afterClose.match(/^status:.*$/m) || [''])[0] + ' | ' + (afterClose.match(/^transitions:.*$/m) || [''])[0])

// 旧指纹：被 CAS 拦下
const stale = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: originalSha, kind: 'reopen',
  }, 'write-2')
const staleValue = stale.envelope && stale.envelope.result && stale.envelope.result.value
expect('写重开（旧指纹）：被 CAS 拦下', staleValue && staleValue.ok === false && staleValue.code === 'E_STATE_CHANGED', JSON.stringify(staleValue))

// 新指纹：重开 + 标记已交草稿
const reopen = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: closed.current.sha256, kind: 'reopen',
  }, 'write-3')
const reopened = reopen.envelope && reopen.envelope.result && reopen.envelope.result.value
expect('写重开：ok', reopened && reopened.ok === true, JSON.stringify(reopened))
const sedimented = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: reopened.current.sha256, kind: 'sedimented', state: 'submitted',
  }, 'write-4')
const sedValue = sedimented.envelope && sedimented.envelope.result && sedimented.envelope.result.value
expect('写沉淀：ok', sedValue && sedValue.ok === true, JSON.stringify(sedValue))
expect('写沉淀：changed 里有 sedimented', sedValue && Array.isArray(sedValue.changed) && sedValue.changed.indexOf('sedimented') >= 0)
const afterSed = readFileSync(join(TRACES, TRACE_FILE), 'utf8')
expect('写沉淀：文件里 state 是 submitted', /state: "submitted"/.test(afterSed) || /state: submitted/.test(afterSed))

// 不支持的写入类型与非法单据号
const badKind = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: reopened.current.sha256, kind: 'report',
  }, 'write-5')
expect('写回报：显式不支持（回报轴没有脚本写入口）', badKind.envelope.result.value.ok === false && badKind.envelope.result.value.code === 'E_SCHEMA')
const badId = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: '../etc/passwd',
    tracesDir: TRACES, expectSha256: closed.current.sha256, kind: 'reopen',
  }, 'write-6')
expect('写：单据号带路径被拒', badId.envelope.result.value.ok === false && badId.envelope.result.value.code === 'E_SCHEMA')

// ── 只读会话 ────────────────────────────────────────────────────────────────
const ro = makeHarness({
  sandboxPolicy: { resolve: () => ({ mode: 'read-only' }) },
  sessions: { get: () => ({ header: {} }) },
})
mod.apply(ro.ctx)
const roState = await request(ro, {
  type: 'client-request', rpcId: 'state-ro', method: 'copilot-state',
  payload: { sessionId: 'smoke-ro', cwd: SANDBOX },
})
const roValue = roState.envelope.result.value
expect('只读：能力位为 false', roValue && roValue.capabilities && roValue.capabilities.canWrite === false, JSON.stringify(roValue && roValue.capabilities))
const roWrite = await transition(ro, {
    sessionId: 'smoke-ro', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: roValue.all[0].contentSha256, kind: 'reopen',
  }, 'write-ro')
const roWrote = roWrite.envelope.result.value
expect('只读：写入被拒 E_PERM', roWrote && roWrote.ok === false && roWrote.code === 'E_PERM', JSON.stringify(roWrote))

// ── 非检出工作区 ────────────────────────────────────────────────────────────
const outsideState = await request(rw, {
  type: 'client-request', rpcId: 'state-outside', method: 'copilot-state',
  payload: { sessionId: 'smoke-session', cwd: tmpdir() },
})
expect('非检出：E_NO_ROOT', outsideState.envelope.result.value.ok === false && outsideState.envelope.result.value.code === 'E_NO_ROOT')

// ── 信封与 HTTP 边界 ────────────────────────────────────────────────────────
const unknown = await request(rw, {
  type: 'client-request', rpcId: 'x', method: 'nope', payload: {},
}, '/sleuth-copilot/nope')
expect('未知端点：not-found', unknown.envelope.result.ok === false && unknown.envelope.result.error.code === 'not-found')
const wrongMethod = makeRequest({})
wrongMethod.method = 'GET'
const wrongResponse = makeResponse()
await rw.getRoute().handler(wrongMethod, wrongResponse)
expect('非 POST：405', wrongResponse.captured.status === 405)

for (const harness of [rw, ro]) {
  for (const cleanup of harness.effects) {
    try {
      cleanup()
    } catch {
      // 清理失败不影响退出码
    }
  }
}
rmSync(SANDBOX, { recursive: true, force: true })

process.stdout.write('\n' + checks + ' 条断言，' + failures + ' 条失败\n')
process.exit(failures === 0 ? 0 : 1)
