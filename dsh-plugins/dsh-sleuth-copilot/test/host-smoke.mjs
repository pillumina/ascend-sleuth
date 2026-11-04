// Host 半冒烟（开发用，不进安装产物）：用假的 cordis ctx 装起 lib/index.js，
// 拿它注册的路由直接发请求，走真实的 shell → Python → JSON 链路。
//
// 跑法：node dsh-plugins/dsh-sleuth-copilot/test/host-smoke.mjs
// 它证明不了浏览器的会话 cookie 与页面渲染；证明的是：路由注册、取数链路、能力位、
// 状态写入的真实参数与返回（写操作全部在系统临时目录里的 trace 副本上做，仓库不被改）。

import { exec, execSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
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
  'summary: "Copilot host smoke 夹具：A3-910C w8a8c8，验证取数、能力位与状态写入；不依赖真实 traces/。"',
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
  'harness_session: "origin-session"',
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
  '      missing: "缺驱动版本；缺硬件侧 plog 与 die 温度；缺 device plog；需要提供 npu-smi 输出；未提供：具体硬件 A2/A3、量化档（w8a8c8 或 w4a8c8）、完整 --additional-config 启动脚本、P 节点日志、triage 命中进程信息；首次崩溃 16h"',
  '  - role: agent',
  '    step: 2',
  '    action: triage',
  '    output: "夹具输出"',
  '    reason: "夹具原因"',
  '  - role: agent',
  '    action: resume',
  '    harness_session: "resumed-session"',
  '    step: 3',
  '    output: "续接夹具"',
  '',
].join('\n')

// 老单夹具：已收尾但缺收尾方式（补记收尾方式的写通道用它），current_step 写成非数字，
// 读侧要把它降级成 0 而不是让整行失败。updated_at 早于主夹具，保证列表里主夹具排前面。
const TRACE2_ID = '2026-08-01-copilot-legacy'
const TRACE2_FILE = TRACE2_ID + '.yaml'
const TRACE2_FIXTURE = [
  'session_id: "' + TRACE2_ID + '"',
  'status: resolved',
  'current_step: "第三步"',
  'summary: "老单夹具：已定位但缺收尾方式；current_step 非数字。"',
  'created_at: "2026-08-01T10:00:00+08:00"',
  'updated_at: "2026-08-01T10:00:00+08:00"',
  'detected_framework: vllm-ascend',
  'detected_platform: A3-910C',
  'detected_category: interrupt',
  'feedback:',
  '  case: ""',
  '  outcome: pending',
  'active_case: ""',
  'harness_session: "legacy-session"',
  'trace:',
  '  - role: user',
  '    step: 1',
  '    content: "老单用户事件"',
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
mkdirSync(join(SANDBOX, 'postmortems', 'inbox'), { recursive: true })
// 沉淀队列要读 git（目标 commit / 知识库新鲜度）；临时检出建一个最小 commit。
// 没有 git 的环境跳过沉淀端点断言，不把环境缺失算成代码失败。
let hasGit = true
try {
  execSync('git init -q', { cwd: SANDBOX, stdio: 'ignore' })
  execSync('git config user.email smoke@example.com', { cwd: SANDBOX, stdio: 'ignore' })
  execSync('git config user.name smoke', { cwd: SANDBOX, stdio: 'ignore' })
  writeFileSync(join(SANDBOX, '.smoke-commit'), 'seed\n', 'utf8')
  execSync('git add .smoke-commit && git commit -qm seed', { cwd: SANDBOX, stdio: 'ignore' })
  // PR 目标要有一个能选的远端（只写 .git/config，不探测网络）。
  execSync('git remote add origin https://github.com/pillumina/ascend-sleuth.git', { cwd: SANDBOX, stdio: 'ignore' })
} catch {
  hasGit = false
}
const TRACES = realpathSync(join(SANDBOX, 'traces'))

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
  const calls = []
  return {
    calls,
    resolve(request) {
      return request
    },
    async execute(spec) {
      calls.push(String(spec.command || ''))
      return { result: () => runCommand(spec) }
    },
  }
}

// 只改「子进程结果」的假 shell：用来验证超时 / 中止 / 沙箱拒绝各自映射成哪个错误码。
// 解释器探测（`--version`）照常成功——失败注入针对的是数据脚本本身。
function makeResultShell(result) {
  return {
    resolve(request) {
      return request
    },
    async execute(spec) {
      if (typeof spec.command === 'string' && / --version$/.test(spec.command)) {
        return {
          result: () => Promise.resolve({
            exitCode: 0, timedOut: false, aborted: false,
            stdout: { text: 'Python 3.11.0' }, stderr: { text: '' },
          }),
        }
      }
      return { result: () => Promise.resolve(result) }
    },
  }
}

function makeHarness(ctxExtra) {
  let route = null
  const effects = []
  // 默认可写档位：真机上 sandbox-policy 服务总在；这里只给一个稳定的 workspace-write，
  // 让写断言走的是「档位可写」这条分支。传 sandboxPolicy: undefined 可以模拟解析不出的情形。
  const defaultPolicy = { resolve: () => ({ mode: 'workspace-write', workspaceRoot: SANDBOX }) }
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
      if (name === 'shell') return (ctxExtra && ctxExtra.shell) || makeShell()
      if (name === 'connection') return { rpc: {} }
      if (name === 'sandboxPolicy') {
        if (ctxExtra && Object.prototype.hasOwnProperty.call(ctxExtra, 'sandboxPolicy')) {
          return ctxExtra.sandboxPolicy
        }
        return defaultPolicy
      }
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

async function prTarget(harness, payload, rpcId) {
  return request(harness, {
    type: 'client-request', rpcId: rpcId || 'pr', method: 'copilot-pr-target', payload,
  }, '/sleuth-copilot/copilot-pr-target')
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

// 脚本侧失败分两种信封：host 自己的错误是平铺的 `{ok:false, code}`，
// pr_status.py 的 `_fail` 是嵌套的 `{ok:false, error:{code}}`。断言两种都认。
function resultCode(value) {
  if (!value || typeof value !== 'object') return ''
  return String(value.code || (value.error && value.error.code) || '')
}

const mod = await import(join(ROOT, 'lib', 'index.js'))
if (mod.name !== 'dsh-sleuth-copilot') throw new Error('unexpected plugin name')

process.stdout.write('诊断状态条 · Host 冒烟\n')

// ── 可写会话 ────────────────────────────────────────────────────────────────
// shell 记下每次子进程命令：用来确认 pr-target 的 list 一次就带回台账指纹。
const rwShell = makeShell()
const rw = makeHarness({ shell: rwShell })
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
expect('读：缺失材料清单（含无空格写法与末项）', row && Array.isArray(row.extra.missingMaterials)
  && row.extra.missingMaterials.includes('驱动版本')
  && row.extra.missingMaterials.includes('npu-smi 输出')
  && row.extra.missingMaterials.includes('triage 命中进程信息'), JSON.stringify(row && row.extra.missingMaterials))
expect('读：summary 已给的硬件 / 量化档不列为缺口', row
  && !row.extra.missingMaterials.includes('具体硬件 A2/A3')
  && !row.extra.missingMaterials.some((item) => item.startsWith('量化档')), JSON.stringify(row && row.extra.missingMaterials))
expect('读：普通硬件缺口不被过滤', row && row.extra.missingMaterials.includes('硬件侧 plog 与 die 温度'), JSON.stringify(row && row.extra.missingMaterials))
expect('读：按顶层 report_file 识别报告', row && row.extra.hasReport === true && row.reportFile === 'traces/alt-smoke.md')
const originalSha = row.contentSha256

// 会话归属：顶层 harness_session 是原始会话；resume 事件带接手会话
const resumedState = await request(rw, {
  type: 'client-request', rpcId: 'state-resumed', method: 'copilot-state',
  payload: { sessionId: 'resumed-session', cwd: SANDBOX },
})
const resumedValue = resumedState.envelope && resumedState.envelope.result && resumedState.envelope.result.value
expect('会话归属：接手会话绑定到这一单', resumedValue && resumedValue.bound && resumedValue.bound.sessionId === TRACE_ID && resumedValue.bound.boundBy === 'resume', JSON.stringify(resumedValue && resumedValue.bound))
expect('会话归属：返回续接会话', resumedValue && Array.isArray(resumedValue.bound.resumeSessions) && resumedValue.bound.resumeSessions.includes('resumed-session'), JSON.stringify(resumedValue && resumedValue.bound.resumeSessions))
const originState = await request(rw, {
  type: 'client-request', rpcId: 'state-origin', method: 'copilot-state',
  payload: { sessionId: 'origin-session', cwd: SANDBOX },
})
const originValue = originState.envelope && originState.envelope.result && originState.envelope.result.value
expect('会话归属：原始会话仍可绑定', originValue && originValue.bound && originValue.bound.boundBy === 'origin', JSON.stringify(originValue && originValue.bound))
const noCwdState = await request(rw, {
  type: 'client-request', rpcId: 'state-no-cwd', method: 'copilot-state',
  payload: { sessionId: 'origin-session', cwd: '' },
})
const noCwdValue = noCwdState.envelope && noCwdState.envelope.result && noCwdState.envelope.result.value
expect('工作区门禁：无 cwd 不显示', noCwdValue && noCwdValue.ok === false && noCwdValue.code === 'E_NO_ROOT', JSON.stringify(noCwdValue))
const subdirState = await request(rw, {
  type: 'client-request', rpcId: 'state-subdir', method: 'copilot-state',
  payload: { sessionId: 'origin-session', cwd: join(SANDBOX, 'traces') },
})
const subdirValue = subdirState.envelope && subdirState.envelope.result && subdirState.envelope.result.value
expect('工作区门禁：仓库子目录仍显示', subdirValue && subdirValue.ok === true && subdirValue.repoRoot === SANDBOX, JSON.stringify(subdirValue && subdirValue.repoRoot))

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
if (hasGit) {
  const sedimentRead = await request(rw, {
    type: 'client-request', rpcId: 'sediment-1', method: 'copilot-sediment',
    payload: { cwd: SANDBOX, sessionId: 'smoke-session' },
  }, '/sleuth-copilot/copilot-sediment')
  const sedimentValue = sedimentRead.envelope && sedimentRead.envelope.result && sedimentRead.envelope.result.value
  expect('沉淀：端点返回 ok', sedimentValue && sedimentValue.ok === true, JSON.stringify(sedimentValue && sedimentValue.code))
  expect('沉淀：空 inbox 计数为 0', sedimentValue && sedimentValue.counts && sedimentValue.counts.total === 0, JSON.stringify(sedimentValue && sedimentValue.counts))
  expect('沉淀：目标结构存在', sedimentValue && sedimentValue.target && Array.isArray(sedimentValue.target.remotes), JSON.stringify(sedimentValue && sedimentValue.target))
  expect('沉淀：prompts 结构存在', sedimentValue && sedimentValue.prompts && typeof sedimentValue.prompts.pr === 'string', JSON.stringify(sedimentValue && sedimentValue.prompts))

  const targetRead = await request(rw, {
    type: 'client-request', rpcId: 'target-1', method: 'copilot-pr-target',
    payload: { cwd: SANDBOX, action: 'list' },
  }, '/sleuth-copilot/copilot-pr-target')
  const targetValue = targetRead.envelope && targetRead.envelope.result && targetRead.envelope.result.value
  expect('目标：端点返回 ok', targetValue && targetValue.ok === true, JSON.stringify(targetValue))
  expect('目标：remotes 是数组', targetValue && Array.isArray(targetValue.remotes), JSON.stringify(targetValue && targetValue.remotes))
  expect('目标：台账不存在时 list 指纹为 null', targetValue
    && Object.prototype.hasOwnProperty.call(targetValue, 'sha256') && targetValue.sha256 === null,
  JSON.stringify(targetValue && targetValue.sha256))

  // PR 台账写动作：list 一次调用就把台账指纹带回来（pr_status.py 的 list-targets 直接给），
  // mark / set-target / check 都带 --expect-sha256；旧令牌由脚本的 CAS 拦下且不写盘。
  const ledgerPath = join(SANDBOX, 'postmortems', 'inbox', '.groom', 'pr-state.json')
  mkdirSync(dirname(ledgerPath), { recursive: true })
  const ledgerDoc = {
    schema: 'groom-pr-state/v1',
    updated_at: '',
    target: null,
    prs: {
      'demo-draft': {
        // host 故意用没有适配器的域名：--check 的 CAS 放行后会走到「没有适配器」，
        // 不发起平台查询（冒烟不联网）。
        platform: 'github', repo: 'example/repo', number: 1,
        url: 'https://example.invalid/example/repo/pull/1', state: 'open',
        source: 'ledger', created_at: '2026-08-01T00:00:00+00:00',
      },
    },
  }
  writeFileSync(ledgerPath, JSON.stringify(ledgerDoc, null, 2) + '\n', 'utf8')
  const ledgerSha = createHash('sha256').update(readFileSync(ledgerPath)).digest('hex')
  const listCallsBefore = rwShell.calls.length
  const listWithLedger = await prTarget(rw, { cwd: SANDBOX, action: 'list' }, 'pr-list-2')
  const listWithLedgerValue = listWithLedger.envelope.result.value
  const listCommands = rwShell.calls.slice(listCallsBefore)
  expect('目标：list 一次调用就带台账指纹', listWithLedgerValue && listWithLedgerValue.sha256 === ledgerSha
    && listCommands.length === 1 && /--list-targets/.test(listCommands[0]) && !/--status/.test(listCommands[0]),
  JSON.stringify({ sha: listWithLedgerValue && listWithLedgerValue.sha256, calls: listCommands }))
  const markOk = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'mark',
    key: 'demo-draft', state: 'merged', expectSha256: ledgerSha,
  }, 'pr-mark-1')
  const markOkValue = markOk.envelope.result.value
  expect('目标：mark 写台账 ok', markOkValue && markOkValue.ok === true && markOkValue.pr && markOkValue.pr.state === 'merged', JSON.stringify(markOkValue))
  const markStale = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'mark',
    key: 'demo-draft', state: 'open', expectSha256: ledgerSha,
  }, 'pr-mark-2')
  const markStaleValue = markStale.envelope.result.value
  expect('目标：mark 旧指纹被 CAS 拦下', markStaleValue && markStaleValue.ok === false && resultCode(markStaleValue) === 'E_CAS', JSON.stringify(markStaleValue))
  const setTargetOk = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'set-target',
    remote: 'origin', base: 'main', expectSha256: markOkValue && markOkValue.sha256,
  }, 'pr-target-2')
  const setTargetOkValue = setTargetOk.envelope.result.value
  expect('目标：set-target 写台账 ok', setTargetOkValue && setTargetOkValue.ok === true, JSON.stringify(setTargetOkValue))
  const setTargetStale = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'set-target',
    remote: 'origin', base: 'main', expectSha256: markOkValue && markOkValue.sha256,
  }, 'pr-target-3')
  const setTargetStaleValue = setTargetStale.envelope.result.value
  expect('目标：set-target 旧指纹被 CAS 拦下', setTargetStaleValue && setTargetStaleValue.ok === false && resultCode(setTargetStaleValue) === 'E_CAS', JSON.stringify(setTargetStaleValue))
  const ledgerBeforeStaleCheck = readFileSync(ledgerPath)
  const checkStale = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'check',
    key: 'demo-draft', expectSha256: '0'.repeat(64),
  }, 'pr-check-stale')
  const checkStaleValue = checkStale.envelope.result.value
  expect('目标：check 旧指纹被脚本 CAS 拦下且不写盘', checkStaleValue && checkStaleValue.ok === false
    && resultCode(checkStaleValue) === 'E_CAS'
    && readFileSync(ledgerPath).equals(ledgerBeforeStaleCheck), JSON.stringify(checkStaleValue))
  const listBeforeCheck = await prTarget(rw, { cwd: SANDBOX, action: 'list' }, 'pr-list-3')
  const checkToken = listBeforeCheck.envelope.result.value.sha256
  const checkCurrent = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'check',
    key: 'demo-draft', expectSha256: checkToken,
  }, 'pr-check-current')
  const checkCurrentValue = checkCurrent.envelope.result.value
  const checkCurrentMessage = String((checkCurrentValue && checkCurrentValue.error && checkCurrentValue.error.message) || '')
  expect('目标：check 当前指纹放行（走到查询，没有适配器）', checkCurrentValue && checkCurrentValue.ok === false
    && resultCode(checkCurrentValue) === 'E_NO_ADAPTER' && /适配器/.test(checkCurrentMessage)
    && typeof checkCurrentValue.sha256 === 'string', JSON.stringify(checkCurrentValue))
}

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

// ── canonical traces、终态写入映射与子进程失败映射 ──────────────────────────

// tracesDir 由客户端带回，但只有「本会话检出的 traces/」与「主检出的 traces/」两种合法；
// 别的绝对路径不能当写沙箱根，也不能拿它读报告。
const currentSha = sedValue && sedValue.current && sedValue.current.sha256
const outsideTraces = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: tmpdir(), expectSha256: currentSha, kind: 'reopen',
  }, 'write-outside-traces')
const outsideTracesValue = outsideTraces.envelope.result.value
expect('写：tracesDir 越界被拒 E_SCHEMA', outsideTracesValue && outsideTracesValue.ok === false && outsideTracesValue.code === 'E_SCHEMA', JSON.stringify(outsideTracesValue))

const outsideReport = await readReport(rw, {
  cwd: SANDBOX, tracesDir: tmpdir(), traceSessionId: TRACE_ID,
}, 'report-outside')
const outsideReportValue = outsideReport.envelope.result.value
expect('报告：tracesDir 越界被拒 E_SCHEMA', outsideReportValue && outsideReportValue.ok === false && outsideReportValue.code === 'E_SCHEMA', JSON.stringify(outsideReportValue))

// archived 缺收尾方式：脚本要求 ending.kind，host 不替它编一个。
const archivedNoKind = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: currentSha, kind: 'close', to: 'archived',
  }, 'write-archived-no-kind')
const archivedNoKindValue = archivedNoKind.envelope.result.value
expect('写收尾（archived 缺 kind）：E_SCHEMA 且带回 requirements', archivedNoKindValue && archivedNoKindValue.ok === false
  && archivedNoKindValue.code === 'E_SCHEMA'
  && Array.isArray(archivedNoKindValue.requirements)
  && archivedNoKindValue.requirements.indexOf('ending.kind') >= 0, JSON.stringify(archivedNoKindValue))

// scheme 版本错配：面板与脚本不一致时给 E_SCHEMA_VERSION，不按旧词表写。
const schemeMismatch = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: currentSha, kind: 'close', to: 'resolved', endingKind: 'root_cause',
    schemeVersion: 'ascend-sleuth-trace-state/0',
  }, 'write-scheme-mismatch')
const schemeMismatchValue = schemeMismatch.envelope.result.value
expect('写：scheme 版本错配回 E_SCHEMA_VERSION', schemeMismatchValue && schemeMismatchValue.ok === false
  && schemeMismatchValue.code === 'E_SCHEMA_VERSION', JSON.stringify(schemeMismatchValue))

// 终态单改收尾方式：先回到 resolved，再改成 escalated（--correct-ending）。
const closeAgain = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: currentSha, kind: 'close', to: 'resolved', endingKind: 'root_cause',
  }, 'write-close-again')
const closeAgainValue = closeAgain.envelope.result.value
expect('写收尾（再收一次）：ok', closeAgainValue && closeAgainValue.ok === true, JSON.stringify(closeAgainValue))
const corrected = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: closeAgainValue && closeAgainValue.current && closeAgainValue.current.sha256,
    kind: 'correct-ending', to: 'escalated', endingKind: 'handed_off', handedTo: '张工 · CANN 组',
  }, 'write-correct-ending')
const correctedValue = corrected.envelope.result.value
expect('写改收尾方式：ok 且落到 escalated', correctedValue && correctedValue.ok === true && correctedValue.to === 'escalated', JSON.stringify(correctedValue))
const afterCorrect = readFileSync(join(TRACES, TRACE_FILE), 'utf8')
expect('写改收尾方式：文件里是 handed_off', /kind: "?handed_off"?/.test(afterCorrect) && /status: "?escalated"?/.test(afterCorrect), (afterCorrect.match(/^status:.*$/m) || [''])[0])

// 报告读取支持 traces/ 下的子目录，但 realpath 后必须仍在 traces/ 里。
mkdirSync(join(TRACES, 'exports'), { recursive: true })
writeFileSync(join(TRACES, 'exports', 'sub.report.md'), '# 子目录报告\n', 'utf8')
const subReport = await readReport(rw, {
  cwd: SANDBOX, tracesDir: TRACES, traceSessionId: TRACE_ID, reportFile: 'traces/exports/sub.report.md',
}, 'report-sub')
const subReportValue = subReport.envelope.result.value
expect('报告：支持 traces/ 子目录', subReportValue && subReportValue.ok === true
  && subReportValue.text.includes('子目录报告') && subReportValue.file === 'traces/exports/sub.report.md', JSON.stringify(subReportValue))
const secretFile = join(SANDBOX, 'outside-secret.md')
writeFileSync(secretFile, '不该被读到\n', 'utf8')
symlinkSync(secretFile, join(TRACES, 'escape.md'))
const escapedReport = await readReport(rw, {
  cwd: SANDBOX, tracesDir: TRACES, traceSessionId: TRACE_ID, reportFile: 'escape.md',
}, 'report-escape')
const escapedValue = escapedReport.envelope.result.value
expect('报告：符号链接越界被拒 E_SCHEMA', escapedValue && escapedValue.ok === false && escapedValue.code === 'E_SCHEMA', JSON.stringify(escapedValue))

// 老单（已收尾、缺收尾方式）加进来：验证补记收尾方式的写通道与读侧降级。
writeFileSync(join(TRACES, TRACE2_FILE), TRACE2_FIXTURE, 'utf8')
const stateWithLegacy = await request(rw, {
  type: 'client-request', rpcId: 'state-legacy', method: 'copilot-state',
  payload: { sessionId: 'smoke-session', cwd: SANDBOX, refresh: true },
})
const legacyStateValue = stateWithLegacy.envelope.result.value
const legacyRow = legacyStateValue && Array.isArray(legacyStateValue.all)
  ? legacyStateValue.all.find((item) => item.sessionId === TRACE2_ID) : null
expect('读：薄行保留 file 并透传 actions', legacyRow && legacyRow.file === TRACE2_FILE
  && Array.isArray(legacyRow.actions) && legacyRow.actions.some((action) => action.id === 'reopen'),
  JSON.stringify(legacyRow && { file: legacyRow.file, actions: legacyRow.actions }))
expect('读：非数字 current_step 降级为 0', legacyRow && legacyRow.extra
  && legacyRow.extra.currentStep === 0 && legacyRow.extra.maxSteps > 0, JSON.stringify(legacyRow && legacyRow.extra))
expect('读：fixEmitted 透传到薄行与 extra', legacyRow
  && Object.prototype.hasOwnProperty.call(legacyRow, 'fixEmitted') && legacyRow.fixEmitted === null
  && legacyRow.extra.fixEmitted === null, JSON.stringify(legacyRow && legacyRow.fixEmitted))
const legacyTraceSha = createHash('sha256').update(readFileSync(join(TRACES, TRACE2_FILE))).digest('hex')
const backfill = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE2_ID, traceFile: TRACE2_FILE,
    tracesDir: TRACES, expectSha256: legacyTraceSha, kind: 'backfill-ending', endingKind: 'root_cause',
  }, 'write-backfill')
const backfillValue = backfill.envelope.result.value
expect('写补记收尾方式：ok', backfillValue && backfillValue.ok === true, JSON.stringify(backfillValue))
const afterBackfill = readFileSync(join(TRACES, TRACE2_FILE), 'utf8')
expect('写补记收尾方式：文件里是 root_cause 且状态未变', /kind: "?root_cause"?/.test(afterBackfill)
  && /status: "?resolved"?/.test(afterBackfill), (afterBackfill.match(/^status:.*$/m) || [''])[0])

// worktree 会话：读写落到主检出的 traces/（canonical 允许这一种）。
const WT = mkdtempSync(join(tmpdir(), 'scp-wt-'))
const wtMeta = join(SANDBOX, '.git', 'worktrees', 'smoke-wt')
mkdirSync(wtMeta, { recursive: true })
writeFileSync(join(WT, '.git'), 'gitdir: ' + wtMeta + '\n')
writeFileSync(join(wtMeta, 'commondir'), '../..\n')
writeFileSync(join(wtMeta, 'gitdir'), join(WT, '.git') + '\n')
writeFileSync(join(wtMeta, 'HEAD'), 'ref: refs/heads/main\n')
symlinkSync(join(REPO, 'scripts'), join(WT, 'scripts'), 'dir')
symlinkSync(join(REPO, 'knowledge'), join(WT, 'knowledge'), 'dir')
copyFileSync(join(REPO, 'trace-status.yaml'), join(WT, 'trace-status.yaml'))
const wtState = await request(rw, {
  type: 'client-request', rpcId: 'state-worktree', method: 'copilot-state',
  payload: { sessionId: 'smoke-session', cwd: WT },
})
const wtValue = wtState.envelope.result.value
expect('worktree：检出根是自己的，traces 落到主检出', wtValue && wtValue.ok === true
  && wtValue.repoRoot === WT && wtValue.tracesDir === TRACES,
  JSON.stringify(wtValue && { root: wtValue.repoRoot, traces: wtValue.tracesDir }))
const wtWrite = await transition(rw, {
    sessionId: 'smoke-session', cwd: WT, traceSessionId: TRACE2_ID, traceFile: TRACE2_FILE,
    tracesDir: TRACES, expectSha256: backfillValue && backfillValue.current && backfillValue.current.sha256,
    kind: 'reopen',
  }, 'write-worktree')
const wtWriteValue = wtWrite.envelope.result.value
expect('worktree：写落到主检出的 traces（reopen ok）', wtWriteValue && wtWriteValue.ok === true, JSON.stringify(wtWriteValue))
rmSync(WT, { recursive: true, force: true })

// 参数文件无论成功、失败都清掉，且只有本进程这一份命名前缀。
const leftovers = readdirSync(tmpdir()).filter((name) => name.startsWith('sleuth-copilot-' + process.pid + '-'))
expect('写参数文件：调用结束后不留临时文件', leftovers.length === 0, leftovers.join(','))

// ── 子进程失败映射（超时 / 中止 / 沙箱拒绝）────────────────────────────────
const timeoutHarness = makeHarness({
  shell: makeResultShell({ exitCode: null, timedOut: true, aborted: false, stdout: { text: '' }, stderr: { text: '' } }),
})
mod.apply(timeoutHarness.ctx)
const timeoutState = await request(timeoutHarness, {
  type: 'client-request', rpcId: 'state-timeout', method: 'copilot-state',
  payload: { sessionId: 'smoke-timeout', cwd: SANDBOX },
})
const timeoutValue = timeoutState.envelope.result.value
expect('子进程超时：E_TIMEOUT', timeoutValue && timeoutValue.ok === false && timeoutValue.code === 'E_TIMEOUT', JSON.stringify(timeoutValue))

const abortHarness = makeHarness({
  shell: makeResultShell({ exitCode: null, timedOut: false, aborted: true, stdout: { text: '' }, stderr: { text: '' } }),
})
mod.apply(abortHarness.ctx)
const abortState = await request(abortHarness, {
  type: 'client-request', rpcId: 'state-abort', method: 'copilot-state',
  payload: { sessionId: 'smoke-abort', cwd: SANDBOX },
})
const abortValue = abortState.envelope.result.value
expect('子进程中止：E_ABORT', abortValue && abortValue.ok === false && abortValue.code === 'E_ABORT', JSON.stringify(abortValue))

const deniedHarness = makeHarness({
  shell: makeResultShell({
    exitCode: 1, timedOut: false, aborted: false,
    sandbox: { denied: true, mode: 'workspace-write' },
    stdout: { text: '' }, stderr: { text: '' },
  }),
})
mod.apply(deniedHarness.ctx)
const deniedState = await request(deniedHarness, {
  type: 'client-request', rpcId: 'state-denied', method: 'copilot-state',
  payload: { sessionId: 'smoke-denied', cwd: SANDBOX },
})
const deniedValue = deniedState.envelope.result.value
expect('沙箱拒绝：E_PERM 且文案点明沙箱', deniedValue && deniedValue.ok === false
  && deniedValue.code === 'E_PERM' && /沙箱/.test(deniedValue.message), JSON.stringify(deniedValue))

const truncatedHarness = makeHarness({
  shell: makeResultShell({
    exitCode: 0, timedOut: false, aborted: false,
    stdout: { text: '', truncated: true }, stderr: { text: '' },
  }),
})
mod.apply(truncatedHarness.ctx)
const truncatedState = await request(truncatedHarness, {
  type: 'client-request', rpcId: 'state-truncated', method: 'copilot-state',
  payload: { sessionId: 'smoke-truncated', cwd: SANDBOX },
})
const truncatedValue = truncatedState.envelope.result.value
expect('输出截断：E_TRUNCATED', truncatedValue && truncatedValue.ok === false
  && truncatedValue.code === 'E_TRUNCATED', JSON.stringify(truncatedValue))

// 沙箱档位解析不出：读照常，写按只读拒绝（不把「服务缺席」当「未限制」）。
const noPolicyHarness = makeHarness({ sandboxPolicy: undefined })
mod.apply(noPolicyHarness.ctx)
const noPolicyState = await request(noPolicyHarness, {
  type: 'client-request', rpcId: 'state-no-policy', method: 'copilot-state',
  payload: { sessionId: 'smoke-no-policy', cwd: SANDBOX },
})
const noPolicyValue = noPolicyState.envelope.result.value
expect('无档位：读照常但能力位不可写', noPolicyValue && noPolicyValue.ok === true
  && noPolicyValue.capabilities && noPolicyValue.capabilities.canWrite === false
  && noPolicyValue.capabilities.reasonCode === 'E_POLICY'
  && /档位/.test(String(noPolicyValue.capabilities.reason)),
  JSON.stringify(noPolicyValue && noPolicyValue.capabilities))
const noPolicyWrite = await transition(noPolicyHarness, {
    sessionId: 'smoke-no-policy', cwd: SANDBOX, traceSessionId: TRACE2_ID, traceFile: TRACE2_FILE,
    tracesDir: TRACES, expectSha256: backfillValue && backfillValue.current && backfillValue.current.sha256,
    kind: 'reopen',
  }, 'write-no-policy')
const noPolicyWrote = noPolicyWrite.envelope.result.value
expect('无档位：写入被拒 E_POLICY（不当成可写）', noPolicyWrote && noPolicyWrote.ok === false
  && noPolicyWrote.code === 'E_POLICY', JSON.stringify(noPolicyWrote))

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

for (const harness of [rw, ro, timeoutHarness, abortHarness, deniedHarness, truncatedHarness, noPolicyHarness]) {
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
