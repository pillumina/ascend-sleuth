// Host 半冒烟（开发用，不进安装产物）：用假的 cordis ctx 装起 lib/index.js，
// 拿它注册的路由直接发请求，走真实的 shell → Python → JSON 链路。
//
// 跑法：node dsh-plugins/dsh-sleuth-copilot/test/host-smoke.mjs
// 它证明不了浏览器的会话 cookie 与页面渲染；证明的是：路由注册、取数链路、能力位、
// 状态写入的真实参数与返回（写操作全部在系统临时目录里的 trace 副本上做，仓库不被改）。

import { exec, execSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs'
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
  'incident_env: "A3-910C · vllm-ascend 0.23.0 · CANN 9.0.0"',
  'incident_timeline:',
  '  - id: inc-1',
  '    at: "2026-09-08T15:20:00+08:00"',
  '    what: "服务起来后首个并发长 prompt 请求崩溃，WorkerProc 退出"',
  '    source: log',
  '    step: 1',
  '    evidence:',
  '      files: ["traces/evidence/2026-09-08-copilot-smoke/crash.log"]',
  '      quote: "ERROR 09-08 15:20:00 WorkerProc hit an exception."',
  '      line: 17',
  '  - id: inc-2',
  '    at: "2026-09-08T15:26:00+08:00"',
  '    what: "关掉 TopK dispatch 后压测 2 小时未复现"',
  '    source: field_test',
  '    step: 5',
  'failure_process:',
  '  axis: time',
  '  window:',
  '    from: "2026-09-08T15:20:00+08:00"',
  '    to: "2026-09-08T15:29:00+08:00"',
  '  clock_note: "日志时间比墙钟晚 8 h（日志 07:20:00 = 墙钟 15:20:00）"',
  '  nodes:',
  '    - id: fp-1',
  '      at: "2026-09-08T15:20:00+08:00"',
  '      what: "首次崩溃，WorkerProc 退出"',
  '      quote: "ERROR 09-08 15:20:00 WorkerProc hit an exception."',
  '      repeat: "每 ~1 s 一次，持续到 15:29:00"',
  '      evidence:',
  '        file: "traces/evidence/2026-09-08-copilot-smoke/evidence.txt"',
  '        line: 17',
  'upstream_timeline:',
  '  - id: up-1',
  '    at: "2026-08-12"',
  '    what: "PR #13831 合入，修 dspark_proposer.py"',
  '    source: commit',
  '    ref: "#13831"',
  'revisions:',
  '  - at: "2026-09-08T15:26:00+08:00"',
  '    by: agent',
  '    kind: fact_corrected',
  '    changes:',
  '      - {target: inc-2, before: "首次崩溃后服务自动恢复", after: "服务未恢复，WorkerProc 退出"}',
  '    reason: "新证据：日志显示 WorkerProc 退出后没有重启"',
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
  // 旧单没有四层数据：`incident_timeline: null` 与缺键一样按「未记录」，`revisions: null` 给 []。
  'incident_timeline: null',
  'revisions: null',
  'trace:',
  '  - role: user',
  '    step: 1',
  '    content: "老单用户事件"',
  '',
].join('\n')

// 修订上限夹具：revisions 是 append-only、不设上限。读侧只留最近 24 条（尾部），
// revisionsTotal 仍报总数；这单只用来验证截断方向，不参与写通道。
const TRACE3_ID = '2026-09-01-copilot-many-revisions'
const TRACE3_FILE = TRACE3_ID + '.yaml'
const MANY_REVISIONS = 30
const TRACE3_FIXTURE = [
  'session_id: "' + TRACE3_ID + '"',
  'status: in_progress',
  'summary: "修订上限夹具：30 条修订。"',
  'created_at: "2026-09-01T10:00:00+08:00"',
  'updated_at: "2026-09-01T10:00:00+08:00"',
  'harness_session: "many-rev-session"',
  'revisions:',
  ...Array.from({ length: MANY_REVISIONS }, (_, i) => [
    '  - at: "2026-09-01T10:00:00+08:00"',
    '    by: agent',
    '    kind: fact_corrected',
    '    changes:',
    '      - {target: summary, before: "旧 ' + (i + 1) + '", after: "新 ' + (i + 1) + '"}',
    '    reason: "第 ' + (i + 1) + ' 次修订"',
  ]).flat(),
  'trace:',
  '  - role: user',
  '    step: 1',
  '    content: "夹具"',
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

// ── 知识库更新提醒的假检出 ──────────────────────────────────────────────────
// 检测只认主检出里的 scripts/kb_sync.py：主检出判定按 `.git` 目录走，脚本内容被假 shell
// 顶掉，所以这里只要目录形状。状态文件落在临时根的 .local/ 下，不碰真实主检出。
const KB_SANDBOX = mkdtempSync(join(tmpdir(), 'scp-kb-'))
const KB_REPO = join(KB_SANDBOX, 'repo')
mkdirSync(join(KB_REPO, 'scripts'), { recursive: true })
mkdirSync(join(KB_REPO, '.git'), { recursive: true })
writeFileSync(join(KB_REPO, 'scripts', 'kb_sync.py'), '', 'utf8')
// 必须在任何 mod.apply() 之前设置：插件在 apply 时就开始读状态文件。
process.env.DSH_SLEUTH_KB_ROOT = KB_REPO
const KB_STATE = join(KB_REPO, '.local', 'kb-sync-notify.json')
const KB_SETTINGS = join(KB_REPO, '.local', 'settings.json')

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
  const handles = []
  const specs = []
  return {
    calls,
    handles,
    specs,
    resolve(request) {
      return request
    },
    async execute(spec) {
      calls.push(String(spec.command || ''))
      specs.push(spec)
      // 故意不提供 readOutput：这就是旧宿主 / 旧 run 形态的退化路径（只等 result()）。
      const handle = { command: String(spec.command || ''), result: () => runCommand(spec) }
      handles.push(handle)
      return handle
    },
  }
}

// 带 readOutput 的假句柄：模拟「进程还在跑、stdout 一行行到」。只在 --check-all 命令上
// 返回增量；其他命令（git / 解释器探测）照常真跑，否则工作区解析走不通。
function makeIncrementalShell(chunks, fullStdout) {
  const calls = []
  return {
    calls,
    resolve(request) {
      return request
    },
    async execute(spec) {
      const command = String(spec.command || '')
      calls.push(command)
      if (!command.includes('--check-all')) return { result: () => runCommand(spec) }
      const pending = chunks.slice()
      let reads = 0
      return {
        readOutput() {
          reads += 1
          if (pending.length) return Promise.resolve({ delta: pending.shift(), lossy: false })
          return Promise.resolve({ delta: '', lossy: false })
        },
        async result() {
          // 等增量被读走再返回完整 stdout，模拟「进程运行到一半就有行可读」。
          while (pending.length && reads < 20) {
            await new Promise((resolve) => setTimeout(resolve, 20))
          }
          return {
            exitCode: 0, timedOut: false, aborted: false,
            stdout: { text: fullStdout }, stderr: { text: '' },
          }
        },
      }
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

// 知识库检查的假 shell：凡调 scripts/kb_sync.py 的命令都回夹具 JSON，其余命令真跑
// （解释器探测走真实 python3；不 fetch、不跑 git、不联网）。setForcePayload 模拟脚本的
// 失败冷却：带 --force 的命令回另一份夹具（脚本靠 --force 跳过冷却，回真实结果）。
// setResult 直接替换子进程结果，用来模拟超时 / 中止这类没有 JSON 的收场。
function makeKbShell() {
  const calls = []
  const specs = []
  let payload = kbPayload({})
  let showPayload = kbPayload({})
  let forcedPayload = null
  let rawResult = null
  return {
    calls,
    specs,
    setPayload(next) {
      payload = next
    },
    // 本机 HEAD 变了之后的重算只跑 `--show`：单独一份夹具，模拟「本地已跟上、落后归零」。
    setShowPayload(next) {
      showPayload = next
    },
    setForcePayload(next) {
      forcedPayload = next
    },
    setResult(next) {
      rawResult = next
    },
    resolve(request) {
      return request
    },
    async execute(spec) {
      const command = String(spec.command || '')
      calls.push(command)
      specs.push(spec)
      if (!command.includes('kb_sync.py')) return { result: () => runCommand(spec) }
      if (rawResult !== null) return { result: () => Promise.resolve(rawResult) }
      const body = forcedPayload !== null && /(^|\s)--force(\s|$)/.test(command)
        ? forcedPayload
        : (/--show/.test(command) ? showPayload : payload)
      return {
        result: () => Promise.resolve({
          exitCode: 0, timedOut: false, aborted: false,
          stdout: { text: JSON.stringify(body) }, stderr: { text: '' },
        }),
      }
    },
  }
}

// kb_sync.py --sync --json 的稳定字段（见脚本文件头）；用例只覆盖自己关心的几项。
function kbPayload(overrides) {
  return Object.assign({
    ok: true,
    reason: '',
    enabled: true,
    offline: false,
    remote: 'origin',
    branch: 'main',
    local_rev: '1111111',
    remote_rev: '9f8e7d',
    behind: 3,
    ahead: 0,
    surface: { knowledge: 2, routing: 0, reference: 1, methodology: 0, panel: 1, other: 0 },
    fetch_error: '',
    config_error: '',
    last_error: '',
  }, overrides)
}

// 假 timer 服务：只记下注册的延迟与回调，由用例自己点火；不挂真实定时器，进程不会被滞留。
// 和真 timer 一样：到点触发后这条定时器自己就没了（entry.disposed 记 true），未触发的由卸载清理。
function makeFakeTimers() {
  const timeouts = []
  const intervals = []
  const record = (list) => (fn, ms) => {
    const entry = { fn: null, ms, disposed: false }
    entry.fn = async () => {
      entry.disposed = true
      return fn()
    }
    list.push(entry)
    return () => {
      entry.disposed = true
    }
  }
  return {
    timeouts,
    intervals,
    timeout: record(timeouts),
    interval: record(intervals),
    async fireTimer() {
      const entry = timeouts[0]
      if (entry) await entry.fn()
    },
  }
}

function readKbState() {
  try {
    return JSON.parse(readFileSync(KB_STATE, 'utf8'))
  } catch {
    return null
  }
}

// 写主检出的 .local/settings.json：调度（提醒检查开关 / 间隔）由 host 自己读这一份。
function writeKbSettings(sync) {
  mkdirSync(join(KB_REPO, '.local'), { recursive: true })
  writeFileSync(KB_SETTINGS, JSON.stringify({ schema: 'ascend-sleuth-settings/1', sync }, null, 2) + '\n', 'utf8')
}

function clearKbSettings() {
  rmSync(KB_SETTINGS, { force: true })
}

function kbSyncCalls(shell) {
  return shell.calls.filter((command) => command.includes('kb_sync.py')).length
}

function makeHarness(ctxExtra) {
  let route = null
  const effects = []
  const injected = []
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
  // timer 替身走可选注入：只有 harness 显式给了 ctxExtra.timer 才注册到注入上下文。
  const timerService = ctxExtra && ctxExtra.timer
  const timerCtx = timerService ? {
    timer: timerService,
    get(name) {
      return name === 'timer' ? timerService : undefined
    },
    effect(fn) {
      const cleanup = fn()
      if (typeof cleanup === 'function') effects.push(cleanup)
      return cleanup
    },
  } : null
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
    // 按 services 分支：webServer 给 webCtx；timer 有替身才回调；其余服务不回调（真宿主会等待）。
    inject(services, callback) {
      const names = Array.isArray(services) ? services : Object.keys(services || {})
      const fiber = {
        disposed: false,
        dispose() {
          fiber.disposed = true
        },
      }
      injected.push({ services: names, fiber })
      if (names.indexOf('webServer') >= 0) callback(webCtx)
      else if (names.indexOf('timer') >= 0 && timerCtx) callback(timerCtx)
      return fiber
    },
  }, {})
  return { ctx, webCtx, getRoute: () => route, effects, injected }
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

async function prProgress(harness, payload, rpcId) {
  return request(harness, {
    type: 'client-request', rpcId: rpcId || 'progress', method: 'copilot-pr-progress', payload,
  }, '/sleuth-copilot/copilot-pr-progress')
}

async function kbRpc(harness, method, payload, rpcId) {
  return request(harness, {
    type: 'client-request', rpcId: rpcId || method, method, payload: payload || {},
  }, '/sleuth-copilot/' + method)
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
// 逐条进度的假句柄单独装一份 harness；没 git 时那段跳过，这里留 null 给收尾清理。
let incHarness = null
let internalHarness = null
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
// 四层明细不再随 copilot-state 的薄行下发（80 单最坏会放大到数 MB）：
// 详情选中行时走 copilot-timeline 取 layers；薄行只留状态字段。
expect('读：薄行不带四层明细（体积回到状态字段）', row && row.extra
  && !Object.prototype.hasOwnProperty.call(row.extra, 'incidentEnv')
  && !Object.prototype.hasOwnProperty.call(row.extra, 'incident')
  && !Object.prototype.hasOwnProperty.call(row.extra, 'failureProcess')
  && !Object.prototype.hasOwnProperty.call(row.extra, 'upstream')
  && !Object.prototype.hasOwnProperty.call(row.extra, 'revisions'), JSON.stringify(row && Object.keys(row.extra || {})))
const originalSha = row.contentSha256

// 进度端点：还没有 check-all 在跑时 present=false、不报 done（面板不能据此永久停轮询）。
const noRunProgress = await prProgress(rw, { cwd: SANDBOX, sessionId: 'smoke-session' }, 'progress-none')
const noRunProgressValue = noRunProgress.envelope && noRunProgress.envelope.result && noRunProgress.envelope.result.value
expect('进度：没有 run 时 present=false、rows 为空、不报 done', noRunProgressValue
  && noRunProgressValue.present === false
  && Array.isArray(noRunProgressValue.rows) && noRunProgressValue.rows.length === 0
  && noRunProgressValue.done === false, JSON.stringify(noRunProgressValue))

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
expect('时间线：现场环境与现场条目', timelineValue && timelineValue.incidentEnv.includes('vllm-ascend')
  && Array.isArray(timelineValue.incident) && timelineValue.incident.length === 2
  && timelineValue.incident[0].at === '2026-09-08T15:20:00+08:00'
  && timelineValue.incident[0].what.includes('首个并发长 prompt')
  && timelineValue.incident[0].source === 'log'
  && timelineValue.incident[0].step === 1
  && Array.isArray(timelineValue.incident[0].evidence.files)
  && timelineValue.incident[1].source === 'field_test'
  && timelineValue.incidentTotal === 2, JSON.stringify(timelineValue && timelineValue.incident))
expect('时间线：故障过程窗口、时钟偏差与节点', timelineValue && timelineValue.failureProcess
  && timelineValue.failureProcess.window.to === '2026-09-08T15:29:00+08:00'
  && timelineValue.failureProcess.nodes.length === 1
  && timelineValue.failureProcess.nodes[0].quote.includes('WorkerProc hit an exception')
  && timelineValue.failureProcess.nodes[0].repeat.includes('每 ~1 s 一次')
  && timelineValue.failureProcess.nodes[0].evidence.line === 17, JSON.stringify(timelineValue && timelineValue.failureProcess))
expect('时间线：上游条目与来源', timelineValue && Array.isArray(timelineValue.upstream)
  && timelineValue.upstream[0].ref === '#13831'
  && timelineValue.upstream[0].source === 'commit'
  && timelineValue.upstreamTotal === 1, JSON.stringify(timelineValue && timelineValue.upstream))
expect('时间线：修订 changes 与原因', timelineValue && Array.isArray(timelineValue.revisions)
  && timelineValue.revisions[0].kind === 'fact_corrected'
  && timelineValue.revisions[0].changes[0].before.includes('自动恢复')
  && timelineValue.revisions[0].changes[0].after.includes('未恢复')
  && timelineValue.revisions[0].reason.includes('新证据')
  && timelineValue.revisionsTotal === 1, JSON.stringify(timelineValue && timelineValue.revisions))
const timelineBad = await request(rw, {
  type: 'client-request', rpcId: 'timeline-2', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: '../x.yaml' },
}, '/sleuth-copilot/copilot-timeline')
expect('时间线：非法文件名被拒', timelineBad.envelope.result.value.ok === false && timelineBad.envelope.result.value.code === 'E_SCHEMA')
// 详情按需取时只解析目标文件：目标坏了按 E_PARSE / E_LOAD 单给，兄弟文件坏了不参与解析。
writeFileSync(join(TRACES, 'broken-target.yaml'), 'session_id: [unclosed\n', 'utf8')
const brokenTarget = await request(rw, {
  type: 'client-request', rpcId: 'timeline-broken', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: 'broken-target.yaml' },
}, '/sleuth-copilot/copilot-timeline')
const brokenTargetValue = brokenTarget.envelope.result.value
expect('时间线：目标文件解析失败给 E_PARSE', brokenTargetValue && brokenTargetValue.ok === false
  && brokenTargetValue.code === 'E_PARSE', JSON.stringify(brokenTargetValue))
rmSync(join(TRACES, 'broken-target.yaml'))
writeFileSync(join(TRACES, 'bad-utf8.yaml'), Buffer.from([0xff, 0xfe, 0x00, 0x62]))
const badUtf8 = await request(rw, {
  type: 'client-request', rpcId: 'timeline-bad-utf8', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: 'bad-utf8.yaml' },
}, '/sleuth-copilot/copilot-timeline')
const badUtf8Value = badUtf8.envelope.result.value
expect('时间线：目标文件读不出给 E_LOAD', badUtf8Value && badUtf8Value.ok === false
  && badUtf8Value.code === 'E_LOAD', JSON.stringify(badUtf8Value))
rmSync(join(TRACES, 'bad-utf8.yaml'))
writeFileSync(join(TRACES, 'broken-sibling.yaml'), 'session_id: [unclosed\n', 'utf8')
const healthyTimeline = await request(rw, {
  type: 'client-request', rpcId: 'timeline-sibling', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: TRACE_FILE },
}, '/sleuth-copilot/copilot-timeline')
const healthyTimelineValue = healthyTimeline.envelope.result.value
expect('时间线：只读目标文件，坏兄弟文件不影响', healthyTimelineValue && healthyTimelineValue.ok === true
  && Array.isArray(healthyTimelineValue.timeline), JSON.stringify(healthyTimelineValue && healthyTimelineValue.code))
rmSync(join(TRACES, 'broken-sibling.yaml'))
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
  // 批量查合入：动作走 --check-all --json-lines；没有适配器时逐条记 unknown，返回部分失败而不是抛错。
  const checkAll = await prTarget(rw, {
    cwd: SANDBOX, sessionId: 'smoke-session', action: 'check-all',
  }, 'pr-check-all')
  const checkAllValue = checkAll.envelope.result.value
  expect('目标：check-all 走批量查询并报部分失败', checkAllValue && checkAllValue.ok === false
    && resultCode(checkAllValue) === 'E_CHECK_PARTIAL'
    && Array.isArray(checkAllValue.checked) && checkAllValue.checked.length === 1
    && checkAllValue.checked[0].draft === 'demo-draft', JSON.stringify(checkAllValue))
  const checkAllCommand = rwShell.calls.filter((command) => command.includes('--check-all')).pop() || ''
  expect('目标：check-all 用 --json-lines 取逐条输出', /--check-all/.test(checkAllCommand) && /--json-lines/.test(checkAllCommand), checkAllCommand)
  // fake shell 的句柄没有 readOutput：这条路径必须退化成只等 result()，且不产出增量行。
  const checkAllHandle = rwShell.handles.filter((handle) => String(handle.command || '').includes('--check-all')).pop()
  expect('进度：无 readOutput 的句柄走退化路径', checkAllHandle && typeof checkAllHandle.readOutput !== 'function',
    JSON.stringify(checkAllHandle && Object.keys(checkAllHandle)))
  const degradedProgress = await prProgress(rw, { cwd: SANDBOX, sessionId: 'smoke-session' }, 'progress-degraded')
  const degradedProgressValue = degradedProgress.envelope.result.value
  expect('进度：退化路径 done 后 present=true 且没有增量行', degradedProgressValue
    && degradedProgressValue.present === true
    && degradedProgressValue.done === true
    && Array.isArray(degradedProgressValue.rows) && degradedProgressValue.rows.length === 0,
  JSON.stringify(degradedProgressValue))

  // ── 逐条进度：句柄有 readOutput 时，row 行不等整批就进进度端点 ──────────────
  const incRows = [
    { type: 'row', draft: 'demo-draft', ok: true, state: 'merged', checked_at: '2026-11-05T10:41:12+08:00' },
    { type: 'row', draft: 'other-draft', ok: false, state: 'unknown', checked_at: '2026-11-05T10:41:13+08:00', error: 'E_NO_AUTH', message: '没配 token' },
  ]
  const incDone = {
    type: 'done', ok: false,
    error: { code: 'E_CHECK_PARTIAL', message: '有 PR 状态没查到（见 checked）' },
    checked: [
      { draft: 'demo-draft', ok: true, state: 'merged' },
      { draft: 'other-draft', ok: false, state: 'unknown', error: 'E_NO_AUTH' },
    ],
    ledger: { schema: 'groom-pr-state/v1', prs: {} },
    sha256: 'b'.repeat(64),
  }
  // 真实形状：stderr 以 `\n[stderr]\n…` 直接接在当前 stdout 文本之后。这里故意接在一条
  // 未完成的 row 半行之后——不截掉 stderr 段就会把这条 row 截坏。
  const secondLine = JSON.stringify(incRows[1])
  const incChunks = [
    JSON.stringify(incRows[0]) + '\n',
    secondLine.slice(0, 12) + '\n[stderr]\n适配器日志混进来也不该打断解析\n',
    secondLine.slice(12) + '\n',
  ]
  const incStdout = JSON.stringify(incRows[0]) + '\n' + secondLine + '\n'
    + JSON.stringify(incDone) + '\n'
  const incShell = makeIncrementalShell(incChunks, incStdout)
  const inc = makeHarness({ shell: incShell })
  incHarness = inc
  mod.apply(inc.ctx)
  const incPending = prTarget(inc, {
    cwd: SANDBOX, sessionId: 'smoke-incremental', action: 'check-all',
  }, 'pr-check-all-inc')
  // 主 RPC 还没返回时进度端点就该有行；done 之前的 done 是 false（轮询到出现行为止，防机器慢时 flaky）。
  let incMidValue = null
  const incMidDeadline = Date.now() + 3000
  while (Date.now() < incMidDeadline) {
    const incMid = await prProgress(inc, { cwd: SANDBOX, sessionId: 'smoke-incremental' }, 'progress-mid')
    incMidValue = incMid.envelope.result.value
    if (incMidValue && incMidValue.done === false
      && Array.isArray(incMidValue.rows) && incMidValue.rows.length >= 1) break
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  expect('进度：check-all 跑着时能应答且已有行', incMidValue
    && incMidValue.present === true
    && incMidValue.done === false
    && Array.isArray(incMidValue.rows) && incMidValue.rows.length >= 1, JSON.stringify(incMidValue))
  const incAll = await incPending
  const incAllValue = incAll.envelope.result.value
  expect('逐条进度：最终结果仍取 done 行', incAllValue && incAllValue.ok === false
    && resultCode(incAllValue) === 'E_CHECK_PARTIAL'
    && Array.isArray(incAllValue.checked) && incAllValue.checked.length === 2
    && incAllValue.sha256 === 'b'.repeat(64), JSON.stringify(incAllValue))
  const incAfter = await prProgress(inc, { cwd: SANDBOX, sessionId: 'smoke-incremental' }, 'progress-after')
  const incAfterValue = incAfter.envelope.result.value
  // stderr 接在半行之后：截掉 stderr 段后这条 row 仍能拼回；就算极端情况下少一条，
  // done 与最终结果（上面那条断言）也不能受影响。
  expect('进度：done 后 present=true、已有行正确（stderr 截断最多少一条 row）', incAfterValue
    && incAfterValue.present === true
    && incAfterValue.done === true
    && Array.isArray(incAfterValue.rows)
    && incAfterValue.rows.length >= 1 && incAfterValue.rows.length <= 2
    && incAfterValue.rows[0].draft === 'demo-draft'
    && incAfterValue.rows.every((item) => typeof item.draft === 'string' && item.draft !== ''),
  JSON.stringify(incAfterValue))
  // 同 key 再跑一次：新 run 覆盖旧 run，行数不累加。
  const incAgain = await prTarget(inc, {
    cwd: SANDBOX, sessionId: 'smoke-incremental', action: 'check-all',
  }, 'pr-check-all-inc-2')
  expect('进度：同 key 新 run 结果正常', incAgain.envelope.result.value
    && incAgain.envelope.result.value.ok === false, JSON.stringify(incAgain.envelope.result.value))
  const incAgainProgress = await prProgress(inc, { cwd: SANDBOX, sessionId: 'smoke-incremental' }, 'progress-again')
  const incAgainValue = incAgainProgress.envelope.result.value
  expect('进度：同 key 新 run 覆盖旧 run（行数不累加）', incAgainValue
    && incAgainValue.present === true
    && incAgainValue.done === true
    && incAgainValue.rows.length >= 1 && incAgainValue.rows.length <= 2,
  JSON.stringify(incAgainValue))

  // 未预期异常（E_INTERNAL）出现在已打 row 之后：脚本折成一行 compact JSON 时逐行可取；
  // 旧版本 / 别的路径如果是多行缩进 JSON，服务端要从最后一段行首 `{` 整段解析，不能退化成 E_OUTPUT。
  const internalStdout = JSON.stringify(incRows[0]) + '\n'
    + '{\n  "ok": false,\n  "error": {\n    "code": "E_INTERNAL",\n    "message": "RuntimeError: boom"\n  }\n}\n'
  const internalShell = makeIncrementalShell([], internalStdout)
  internalHarness = makeHarness({ shell: internalShell })
  mod.apply(internalHarness.ctx)
  const internal = await prTarget(internalHarness, {
    cwd: SANDBOX, sessionId: 'smoke-internal', action: 'check-all',
  }, 'pr-check-all-internal')
  const internalValue = internal.envelope.result.value
  expect('逐条进度：多行错误 JSON 兜底解析（不退化 E_OUTPUT）', internalValue
    && internalValue.ok === false
    && resultCode(internalValue) === 'E_INTERNAL'
    && /RuntimeError: boom/.test(String(internalValue.error && internalValue.error.message)),
  JSON.stringify(internalValue))
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

// 坏件单：客户端把解析错误带过来时，写入口直接说文件读不出来，不要报成「缺内容指纹」。
const brokenTrace = await transition(rw, {
    sessionId: 'smoke-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: '', traceError: 'YAML 解析失败', kind: 'reopen',
  }, 'write-broken-trace')
const brokenTraceValue = brokenTrace.envelope.result.value
expect('写：坏件单报 E_PARSE 而不是缺指纹', brokenTraceValue && brokenTraceValue.ok === false
  && brokenTraceValue.code === 'E_PARSE' && /读不出来/.test(brokenTraceValue.message), JSON.stringify(brokenTraceValue))

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
// 旧单（没有四层字段）：null = 字段不存在，[] = 字段存在但为空；不回填、不报错。
expect('读：旧单薄行不带四层字段', legacyRow && legacyRow.extra
  && !Object.prototype.hasOwnProperty.call(legacyRow.extra, 'incident')
  && !Object.prototype.hasOwnProperty.call(legacyRow.extra, 'upstream'), JSON.stringify(legacyRow && Object.keys(legacyRow.extra || {})))
const legacyTimelineRead = await request(rw, {
  type: 'client-request', rpcId: 'timeline-legacy', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: TRACE2_FILE },
}, '/sleuth-copilot/copilot-timeline')
const legacyTimelineValue = legacyTimelineRead.envelope && legacyTimelineRead.envelope.result
  && legacyTimelineRead.envelope.result.value
// `incident_timeline: null`（显式 null）与缺键（upstream_timeline）都按未记录给 null；
// `revisions: null` 给空列表——null 不是「查过但为空」。
expect('时间线：旧单 null / 缺键都按未记录', legacyTimelineValue && legacyTimelineValue.ok === true
  && legacyTimelineValue.incidentEnv === ''
  && legacyTimelineValue.incident === null && legacyTimelineValue.incidentTotal === 0
  && legacyTimelineValue.failureProcess === null
  && legacyTimelineValue.upstream === null && legacyTimelineValue.upstreamTotal === 0
  && Array.isArray(legacyTimelineValue.revisions) && legacyTimelineValue.revisions.length === 0
  && legacyTimelineValue.revisionsTotal === 0,
JSON.stringify(legacyTimelineValue && {
  incidentEnv: legacyTimelineValue.incidentEnv, incident: legacyTimelineValue.incident,
  incidentTotal: legacyTimelineValue.incidentTotal,
  failureProcess: legacyTimelineValue.failureProcess, upstream: legacyTimelineValue.upstream,
  upstreamTotal: legacyTimelineValue.upstreamTotal, revisions: legacyTimelineValue.revisions,
}))
// 修订超上限：append-only 无上限，读侧只留最近 24 条（尾部），总数不截断。
writeFileSync(join(TRACES, TRACE3_FILE), TRACE3_FIXTURE, 'utf8')
const manyRevRead = await request(rw, {
  type: 'client-request', rpcId: 'timeline-many-revisions', method: 'copilot-timeline',
  payload: { cwd: SANDBOX, tracesDir: TRACES, traceFile: TRACE3_FILE },
}, '/sleuth-copilot/copilot-timeline')
const manyRevValue = manyRevRead.envelope && manyRevRead.envelope.result
  && manyRevRead.envelope.result.value
expect('时间线：修订超上限只留最近 24 条、总数不截断', manyRevValue && manyRevValue.ok === true
  && Array.isArray(manyRevValue.revisions) && manyRevValue.revisions.length === 24
  && manyRevValue.revisionsTotal === 30
  && manyRevValue.revisions[0].reason === '第 7 次修订'
  && manyRevValue.revisions[23].reason === '第 30 次修订',
JSON.stringify(manyRevValue && {
  length: manyRevValue.revisions && manyRevValue.revisions.length,
  total: manyRevValue.revisionsTotal,
  first: manyRevValue.revisions && manyRevValue.revisions[0] && manyRevValue.revisions[0].reason,
  last: manyRevValue.revisions && manyRevValue.revisions[23] && manyRevValue.revisions[23].reason,
}))
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

// ── 写子进程的沙箱档位：跟随会话，不把完全权限降级 ──────────────────────────
// 旧写法把写子进程的档位写死成 workspace-write：完全权限的会话在 Windows 上写不进去
// （读子进程跟随会话档位、写子进程反而被降级），报出来却只有一句「没有写权限」。
{
  const wsShell = makeShell()
  const ws = makeHarness({
    shell: wsShell,
    sandboxPolicy: { resolve: () => ({ mode: 'workspace-write', workspaceRoot: SANDBOX, sessionId: 'ws-session' }) },
  })
  mod.apply(ws.ctx)
  const wsSha = createHash('sha256').update(readFileSync(join(TRACES, TRACE_FILE))).digest('hex')
  const wsWrite = await transition(ws, {
    sessionId: 'ws-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: wsSha, kind: 'reopen',
  }, 'write-workspace-policy')
  const wsWriteValue = wsWrite.envelope.result.value
  expect('写：工作区写会话照常写入', wsWriteValue && wsWriteValue.ok === true, JSON.stringify(wsWriteValue))
  const wsSpec = wsShell.specs.find((spec) => /trace_transition\.py/.test(String(spec.command || '')))
  expect('写：工作区写会话的写子进程收窄到写落点并带上会话号', !!wsSpec && wsSpec.sandboxPolicy
    && wsSpec.sandboxPolicy.mode === 'workspace-write'
    && wsSpec.sandboxPolicy.workspaceRoot === dirname(TRACES)
    && wsSpec.sandboxPolicy.sessionId === 'ws-session', JSON.stringify(wsSpec && wsSpec.sandboxPolicy))

  const fullShell = makeShell()
  const full = makeHarness({
    shell: fullShell,
    sessions: { get: () => ({ header: {} }) },
    sandboxPolicy: { resolve: () => ({ mode: 'danger-full-access', sessionId: 'full-access-session' }) },
  })
  mod.apply(full.ctx)
  const fullSha = createHash('sha256').update(readFileSync(join(TRACES, TRACE_FILE))).digest('hex')
  const fullWrite = await transition(full, {
    sessionId: 'full-access-session', cwd: SANDBOX, traceSessionId: TRACE_ID,
    tracesDir: TRACES, expectSha256: fullSha, kind: 'close', to: 'resolved', endingKind: 'root_cause',
  }, 'write-full-access')
  const fullWriteValue = fullWrite.envelope.result.value
  expect('写：完全权限会话照常写入', fullWriteValue && fullWriteValue.ok === true, JSON.stringify(fullWriteValue))
  const writeSpec = fullShell.specs.find((spec) => /trace_transition\.py/.test(String(spec.command || '')))
  expect('写：完全权限会话的写子进程不降级沙箱档位', !!writeSpec && writeSpec.sandboxPolicy
    && writeSpec.sandboxPolicy.mode === 'danger-full-access'
    && writeSpec.sandboxPolicy.sessionId === 'full-access-session',
  JSON.stringify(writeSpec && writeSpec.sandboxPolicy))

  // 台账写入（mark）只改本地台账，不查平台：用它看写子进程拿到的档位。
  const prBefore = fullShell.specs.length
  await prTarget(full, {
    sessionId: 'full-access-session', cwd: SANDBOX, action: 'mark',
    key: 'demo-draft', state: 'merged',
  }, 'pr-mark-full-access')
  const prSpec = fullShell.specs.slice(prBefore).find((spec) => /pr_status\.py/.test(String(spec.command || '')))
  expect('目标：完全权限会话写台账的沙箱档位不降级', !!prSpec && prSpec.sandboxPolicy
    && prSpec.sandboxPolicy.mode === 'danger-full-access', JSON.stringify(prSpec && prSpec.sandboxPolicy))
}

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
// 超时原文按调用点给：面板取数会读 traces/，这里保留那句线索（知识库检查不读 traces/，见 ⑥b2）。
expect('子进程超时：面板取数的原文带 traces/ 线索',
  timeoutValue && /^诊断状态取数超时（20 秒内没有返回；traces\/ 很大时可能偏慢）/.test(timeoutValue.message || ''),
  JSON.stringify(timeoutValue))
// 其余取数路径也按调用对象给原文，秒数各自对上（时间线/沉淀队列 20/30 秒、PR 台账 30 秒）。
const timeoutKinds = [
  ['轨迹时间线', 'copilot-timeline', {
    cwd: SANDBOX, tracesDir: TRACES, traceFile: TRACE_FILE,
  }, /^轨迹时间线读取超时（20 秒内没有返回）。$/],
  ['沉淀队列', 'copilot-sediment', {
    cwd: SANDBOX, sessionId: 'smoke-timeout',
  }, /^沉淀队列取数超时（30 秒内没有返回）。$/],
  ['PR 台账', 'copilot-pr-target', {
    cwd: SANDBOX, action: 'list',
  }, /^PR 台账读取超时（30 秒内没有返回）。$/],
]
for (const [label, method, payload, pattern] of timeoutKinds) {
  const resp = await request(timeoutHarness, {
    type: 'client-request', rpcId: 'timeout-' + method, method, payload,
  }, '/sleuth-copilot/' + method)
  const value = resp.envelope && resp.envelope.result && resp.envelope.result.value
  expect('子进程超时：' + label + '的原文按调用对象给',
    value && value.ok === false && value.code === 'E_TIMEOUT' && pattern.test(value.message || ''),
    JSON.stringify(value))
}

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

// ── 知识库更新提醒 ──────────────────────────────────────────────────────────
// 检查唯一入口是 scripts/kb_sync.py：每个用例换一份夹具 JSON，验证静默规则、同一远端
// 提交的去重与状态文件、受限档位的退化提示、连续失败上屏与按设置到期判断。
// 假 timer 由用例点火，不挂真实定时器（进程不会被定时器拖住）。
const kbHarnesses = []
let kbTimers = null
let kbTimerHarness = null

function newKbHarness(payload, timers) {
  const shell = makeKbShell()
  shell.setPayload(payload)
  const options = { shell }
  if (timers) options.timer = timers
  const harness = makeHarness(options)
  kbHarnesses.push(harness)
  mod.apply(harness.ctx)
  return { harness, shell, timers: timers || null }
}

{
  // timer 是可选的：导出只声明 connection，装定时器靠 ctx.inject(['timer'])。
  expect('知识库：inject 不带 timer（可选注入）',
    Array.isArray(mod.inject) && mod.inject.length === 1 && mod.inject[0] === 'connection',
    JSON.stringify(mod.inject))

  // ① 落后 3 个提交、含 1 处面板代码：启动检查跑完，copilot-state 带 kbNotice。
  const first = newKbHarness(kbPayload({}), makeFakeTimers())
  kbTimers = first.timers
  kbTimerHarness = first.harness
  expect('知识库：可选注入拿到 timer 替身',
    first.harness.injected.some((item) => item.services.indexOf('timer') >= 0),
    JSON.stringify(first.harness.injected.map((item) => item.services)))
  // 启动只排一次 3 秒首查；间隔检查不再用固定 interval。
  expect('知识库：启动排一次 3 秒首查、不用固定 interval',
    kbTimers.timeouts.length === 1 && kbTimers.timeouts[0].ms === 3000
    && kbTimers.intervals.length === 0,
    JSON.stringify({
      timeouts: kbTimers.timeouts.map((entry) => entry.ms),
      intervals: kbTimers.intervals.map((entry) => entry.ms),
    }))
  await kbTimers.fireTimer()
  const kbCommands = first.shell.calls.filter((command) => command.includes('kb_sync.py'))
  expect('知识库：检测走 kb_sync.py --check --json 并指定主检出',
    kbCommands.length === 1 && /--check/.test(kbCommands[0]) && !/--sync/.test(kbCommands[0])
    && /--json/.test(kbCommands[0])
    && kbCommands[0].includes(join(KB_REPO, 'scripts', 'kb_sync.py'))
    && kbCommands[0].includes("--root '" + KB_REPO + "'"),
    JSON.stringify(kbCommands))
  // 定时检查不带 --force：脚本的失败冷却与静默规则照旧。
  expect('知识库：定时检查的命令不带 --force',
    kbCommands.every((command) => !/(^|\s)--force(\s|$)/.test(command)), JSON.stringify(kbCommands))
  // 后台检查默认以完全权限跑：受限档（Windows 的 workspace-write）拿不到 git 凭据，
  // 检查会永远失败；面板可关掉，关掉后按部署默认档（见 ①b）。
  const kbSpec = first.shell.specs.filter((spec) => String(spec.command || '').includes('kb_sync.py')).pop()
  expect('知识库：后台检查默认以完全权限跑、根仍指主检出',
    kbSpec && kbSpec.sandboxPolicy && kbSpec.sandboxPolicy.mode === 'danger-full-access'
    && kbSpec.sandboxPolicy.workspaceRoot === KB_REPO,
    JSON.stringify(kbSpec && kbSpec.sandboxPolicy))
  // 默认 settings 缺省：检查后至多 60 秒重读设置，按「上次检查开始 + 间隔」判到期。
  expect('知识库：检查后至多 60 秒重读设置、按到期规则判下一次',
    kbTimers.timeouts.length === 2 && kbTimers.timeouts[1].ms === 60 * 1000,
    JSON.stringify(kbTimers.timeouts.map((entry) => entry.ms)))
  // 未到期（离上次检查开始还不足默认 30 分钟）：点火只重读设置、不起子进程。
  await kbTimers.timeouts[1].fn()
  expect('知识库：未到期时 60 秒轮询不起子进程、继续排下一次',
    first.shell.calls.filter((command) => command.includes('kb_sync.py')).length === kbCommands.length
    && kbTimers.timeouts.length === 3 && kbTimers.timeouts[2].ms === 60 * 1000,
    JSON.stringify({
      calls: first.shell.calls.filter((command) => command.includes('kb_sync.py')).length,
      timeouts: kbTimers.timeouts.map((entry) => entry.ms),
    }))
  // 时间前进 31 分钟（超过默认 30 分钟间隔）：下一次轮询按「上次检查开始 + 间隔」判到期。
  const realNowForInterval = Date.now
  let intervalClockShift = 0
  Date.now = () => realNowForInterval() + intervalClockShift
  try {
    intervalClockShift = 31 * 60 * 1000
    await kbTimers.timeouts[2].fn()
  } finally {
    Date.now = realNowForInterval
  }
  const commandsAfterInterval = first.shell.calls.filter((command) => command.includes('kb_sync.py'))
  expect('知识库：到期再跑一次检查并继续排下一次',
    commandsAfterInterval.length === kbCommands.length + 1
    && commandsAfterInterval.every((command) => /--check/.test(command) && /--json/.test(command))
    && kbTimers.timeouts.length === 4 && kbTimers.timeouts[3].ms === 60 * 1000,
    JSON.stringify({ calls: commandsAfterInterval.length, timeouts: kbTimers.timeouts.map((entry) => entry.ms) }))
  expect('知识库：不自己拼 git 命令',
    first.shell.calls.every((command) => !/(^|\s)git(\s|$)/.test(command)), JSON.stringify(first.shell.calls))
  // 没有 timer 能力的 harness（前面那些）完全不装定时器，也就没跑过后台检查。
  expect('知识库：没有 timer 服务时不跑后台检查',
    rwShell.calls.every((command) => !command.includes('kb_sync.py')))

  const stateFirst = (await kbRpc(first.harness, 'copilot-state', {
    sessionId: 'kb-session', cwd: SANDBOX,
  }, 'kb-state-1')).envelope.result.value
  const noticeFirst = stateFirst && stateFirst.kbNotice
  expect('知识库：落后 3 且 panel 1 时 copilot-state 带 kbNotice',
    noticeFirst && noticeFirst.rev === '9f8e7d' && noticeFirst.behind === 3
    && noticeFirst.panel === 1 && noticeFirst.knowledge === 2 && noticeFirst.reference === 1
    && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/.test(noticeFirst.checkedAt),
    JSON.stringify(noticeFirst))
  const fileFirst = readKbState()
  expect('知识库：状态文件按 schema 落盘',
    fileFirst && fileFirst.version === 1 && fileFirst.rev === '9f8e7d' && fileFirst.behind === 3
    && fileFirst.surface && fileFirst.surface.panel === 1 && fileFirst.surface.knowledge === 2
    && fileFirst.dismissedRev === '' && fileFirst.lastError === ''
    && typeof fileFirst.checkedAt === 'string' && fileFirst.checkedAt !== '',
    JSON.stringify(fileFirst))
  // 原子写：落点文件本身是完整 JSON，同目录不留 .tmp。
  const rawFirstState = readFileSync(KB_STATE, 'utf8')
  let parsedFirstState = null
  try {
    parsedFirstState = JSON.parse(rawFirstState)
  } catch {
    parsedFirstState = null
  }
  expect('知识库：状态文件是合法 JSON 且无 .tmp 残留',
    parsedFirstState !== null && parsedFirstState.rev === '9f8e7d'
    && !existsSync(KB_STATE + '.tmp')
    && readdirSync(join(KB_REPO, '.local')).every((name) => !name.endsWith('.tmp')),
    JSON.stringify({ parsed: parsedFirstState !== null, temp: existsSync(KB_STATE + '.tmp') }))

  const recheckFirst = (await kbRpc(first.harness, 'copilot-kb-recheck', {}, 'kb-recheck-1')).envelope.result.value
  expect('知识库：recheck 返回同一 notice',
    recheckFirst && recheckFirst.notice && recheckFirst.notice.rev === '9f8e7d'
    && recheckFirst.notice.behind === 3 && recheckFirst.error === '' && recheckFirst.reason === '',
    JSON.stringify(recheckFirst))
  const recheckAgain = (await kbRpc(first.harness, 'copilot-kb-recheck', {}, 'kb-recheck-2')).envelope.result.value
  expect('知识库：60 秒内重查不起新子进程',
    recheckAgain && recheckAgain.notice && recheckAgain.notice.rev === '9f8e7d'
    && first.shell.calls.filter((command) => command.includes('kb_sync.py')).length === 2,
    JSON.stringify(recheckAgain))

  // force 跳过 60 秒节流：浏览器半「去同步」后 30 秒复查必须真跑一次。
  const recheckForce = (await kbRpc(first.harness, 'copilot-kb-recheck', { force: true }, 'kb-recheck-force')).envelope.result.value
  const commandsAfterForce = first.shell.calls.filter((command) => command.includes('kb_sync.py'))
  expect('知识库：force 重查跳过节流并起新子进程、回同一 notice',
    recheckForce && recheckForce.notice && recheckForce.notice.rev === '9f8e7d'
    && recheckForce.notice.behind === 3 && commandsAfterForce.length === 3,
    JSON.stringify({ value: recheckForce, kbCalls: commandsAfterForce.length }))
  // force 要一路传到脚本 argv：不带 --force 时脚本在失败冷却内直接回 skipped，重试等于没试。
  expect('知识库：force 重查的命令带 --force',
    commandsAfterForce.length > 0
    && /(^|\s)--force(\s|$)/.test(commandsAfterForce[commandsAfterForce.length - 1])
    && commandsAfterForce.slice(0, -1).every((command) => !/(^|\s)--force(\s|$)/.test(command)),
    JSON.stringify(commandsAfterForce))

  // ①b 沙箱档位：默认/显式打开时以完全权限跑，忽略部署默认；关掉后按部署默认档：
  // 部署是完全权限时原样透传，受限档（workspace-write）时把工作区根收成主检出。
  clearKbSettings()
  writeKbSettings({ check_enabled: true, check_minutes: 30, check_full_access: true })
  const onShell = makeKbShell()
  onShell.setPayload(kbPayload({}))
  const onPolicy = makeHarness({ shell: onShell, sandboxPolicy: { resolve: () => ({ mode: 'workspace-write' }) } })
  kbHarnesses.push(onPolicy)
  mod.apply(onPolicy.ctx)
  await kbRpc(onPolicy, 'copilot-kb-recheck', { force: true }, 'kb-recheck-full-on')
  const onSpec = onShell.specs.filter((spec) => String(spec.command || '').includes('kb_sync.py')).pop()
  expect('知识库：开「后台检查用完全权限」时忽略部署默认档',
    onSpec && onSpec.sandboxPolicy && onSpec.sandboxPolicy.mode === 'danger-full-access'
    && onSpec.sandboxPolicy.workspaceRoot === KB_REPO,
    JSON.stringify(onSpec && onSpec.sandboxPolicy))

  writeKbSettings({ check_enabled: true, check_minutes: 30, check_full_access: false })
  const fullShell = makeKbShell()
  fullShell.setPayload(kbPayload({}))
  const full = makeHarness({ shell: fullShell, sandboxPolicy: { resolve: () => ({ mode: 'danger-full-access' }) } })
  kbHarnesses.push(full)
  mod.apply(full.ctx)
  await kbRpc(full, 'copilot-kb-recheck', { force: true }, 'kb-recheck-full')
  const fullSpec = fullShell.specs.filter((spec) => String(spec.command || '').includes('kb_sync.py')).pop()
  expect('知识库：关掉后部署默认完全权限时沙箱档位原样透传',
    fullSpec && fullSpec.sandboxPolicy && fullSpec.sandboxPolicy.mode === 'danger-full-access',
    JSON.stringify(fullSpec && fullSpec.sandboxPolicy))

  const restrictedShell = makeKbShell()
  restrictedShell.setPayload(kbPayload({}))
  const restricted = makeHarness({
    shell: restrictedShell,
    sandboxPolicy: { resolve: () => ({ mode: 'workspace-write', workspaceRoot: '/elsewhere' }) },
  })
  kbHarnesses.push(restricted)
  mod.apply(restricted.ctx)
  await kbRpc(restricted, 'copilot-kb-recheck', { force: true }, 'kb-recheck-restricted')
  const restrictedSpec = restrictedShell.specs
    .filter((spec) => String(spec.command || '').includes('kb_sync.py')).pop()
  expect('知识库：关掉后受限档把工作区根收成主检出',
    restrictedSpec && restrictedSpec.sandboxPolicy
    && restrictedSpec.sandboxPolicy.mode === 'workspace-write'
    && restrictedSpec.sandboxPolicy.workspaceRoot === KB_REPO,
    JSON.stringify(restrictedSpec && restrictedSpec.sandboxPolicy))
  clearKbSettings()

  // ①c 按 settings 调度：check_minutes=15 → 检查后按 60 秒轮询等到期。
  writeKbSettings({ check_enabled: true, check_minutes: 15 })
  const fifteen = newKbHarness(kbPayload({ remote_rev: 'abc1234', behind: 2 }), makeFakeTimers())
  await fifteen.timers.timeouts[0].fn()
  expect('知识库：check_minutes=15 时检查后按 60 秒轮询等到期',
    kbSyncCalls(fifteen.shell) === 1
    && fifteen.timers.timeouts.length === 2 && fifteen.timers.timeouts[1].ms === 60 * 1000,
    JSON.stringify({ calls: kbSyncCalls(fifteen.shell), timeouts: fifteen.timers.timeouts.map((entry) => entry.ms) }))
  // P2：间隔从 15 分钟改成 5 分钟，时间前进 10 分钟再点火那次 60 秒轮询。
  // 按新间隔已到期，最多 60 秒就起第二次检查，不再等旧间隔走完。
  writeKbSettings({ check_enabled: true, check_minutes: 5 })
  const realNowForReschedule = Date.now
  let rescheduleClockShift = 0
  Date.now = () => realNowForReschedule() + rescheduleClockShift
  try {
    rescheduleClockShift = 10 * 60 * 1000
    await fifteen.timers.timeouts[1].fn()
  } finally {
    Date.now = realNowForReschedule
  }
  expect('知识库：改间隔后 60 秒轮询按新间隔到期并起第二次检查',
    kbSyncCalls(fifteen.shell) === 2
    && fifteen.timers.timeouts.length === 3 && fifteen.timers.timeouts[2].ms === 60 * 1000,
    JSON.stringify({ calls: kbSyncCalls(fifteen.shell), timeouts: fifteen.timers.timeouts.map((entry) => entry.ms) }))
  clearKbSettings()

  // ①d check_enabled=false：不跑 kb_sync、60 秒后再读、提示置空；重开恢复检查。
  writeKbSettings({ check_enabled: false, check_minutes: 30 })
  const paused = newKbHarness(kbPayload({}), makeFakeTimers())
  await paused.timers.timeouts[0].fn()
  const pausedState = (await kbRpc(paused.harness, 'copilot-state', {
    sessionId: 'kb-paused', cwd: SANDBOX,
  }, 'kb-state-paused')).envelope.result.value
  expect('知识库：check_enabled=false 时首查不跑 kb_sync、60 秒后再读、notice 置空',
    kbSyncCalls(paused.shell) === 0
    && paused.timers.timeouts.length === 2 && paused.timers.timeouts[1].ms === 60 * 1000
    && pausedState && pausedState.kbNotice === null,
    JSON.stringify({
      calls: kbSyncCalls(paused.shell),
      timeouts: paused.timers.timeouts.map((entry) => entry.ms),
      notice: pausedState && pausedState.kbNotice,
    }))
  // 手动重查是用户主动动作，不看 check_enabled，仍立即跑。
  const manualWhilePaused = (await kbRpc(paused.harness, 'copilot-kb-recheck', {
    force: true,
  }, 'kb-recheck-paused-manual')).envelope.result.value
  expect('知识库：关着提醒时手动重查仍可立即跑',
    kbSyncCalls(paused.shell) === 1
    && manualWhilePaused && manualWhilePaused.notice && manualWhilePaused.notice.rev === '9f8e7d',
    JSON.stringify({ calls: kbSyncCalls(paused.shell), value: manualWhilePaused }))
  await paused.timers.timeouts[1].fn()
  const pausedAgain = (await kbRpc(paused.harness, 'copilot-state', {
    sessionId: 'kb-paused', cwd: SANDBOX,
  }, 'kb-state-paused-2')).envelope.result.value
  expect('知识库：关闭期间 60 秒轮询不跑子进程、提示收掉',
    kbSyncCalls(paused.shell) === 1
    && paused.timers.timeouts.length === 3 && paused.timers.timeouts[2].ms === 60 * 1000
    && pausedAgain && pausedAgain.kbNotice === null,
    JSON.stringify({ calls: kbSyncCalls(paused.shell), timeouts: paused.timers.timeouts.map((entry) => entry.ms) }))
  writeKbSettings({ check_enabled: true, check_minutes: 30 })
  await paused.timers.timeouts[2].fn()
  const reopened = (await kbRpc(paused.harness, 'copilot-state', {
    sessionId: 'kb-paused', cwd: SANDBOX,
  }, 'kb-state-reopened')).envelope.result.value
  expect('知识库：重新打开后不立即检查、按到期规则继续 60 秒轮询',
    kbSyncCalls(paused.shell) === 1
    && reopened && reopened.kbNotice === null
    && paused.timers.timeouts.length === 4 && paused.timers.timeouts[3].ms === 60 * 1000,
    JSON.stringify({
      calls: kbSyncCalls(paused.shell),
      notice: reopened && reopened.kbNotice,
      timeouts: paused.timers.timeouts.map((entry) => entry.ms),
    }))
  // 时间前进 31 分钟（超过 30 分钟间隔）：重新打开后到期即恢复检查，提示重新出现。
  const realNowForReopen = Date.now
  let reopenClockShift = 0
  Date.now = () => realNowForReopen() + reopenClockShift
  try {
    reopenClockShift = 31 * 60 * 1000
    await paused.timers.timeouts[3].fn()
  } finally {
    Date.now = realNowForReopen
  }
  const reopenedDue = (await kbRpc(paused.harness, 'copilot-state', {
    sessionId: 'kb-paused', cwd: SANDBOX,
  }, 'kb-state-reopened-due')).envelope.result.value
  expect('知识库：重新打开后到期即恢复检查',
    kbSyncCalls(paused.shell) === 2
    && reopenedDue && reopenedDue.kbNotice && reopenedDue.kbNotice.rev === '9f8e7d'
    && paused.timers.timeouts.length === 5 && paused.timers.timeouts[4].ms === 60 * 1000,
    JSON.stringify({
      calls: kbSyncCalls(paused.shell),
      notice: reopenedDue && reopenedDue.kbNotice,
      timeouts: paused.timers.timeouts.map((entry) => entry.ms),
    }))
  clearKbSettings()

  // ①e 手改设置写成字符串（"off"）也按关处理：与 scripts/kb_sync.py 的 _as_bool 同口径。
  writeKbSettings({ check_enabled: 'off', check_minutes: 30 })
  const stringOff = newKbHarness(kbPayload({}), makeFakeTimers())
  await stringOff.timers.timeouts[0].fn()
  expect('知识库：check_enabled 写成字符串 "off" 也按关处理',
    kbSyncCalls(stringOff.shell) === 0
    && stringOff.timers.timeouts.length === 2 && stringOff.timers.timeouts[1].ms === 60 * 1000,
    JSON.stringify({
      calls: kbSyncCalls(stringOff.shell),
      timeouts: stringOff.timers.timeouts.map((entry) => entry.ms),
    }))
  clearKbSettings()

  // ①f 退化提示：受限档位 fetch 被拒但只读探测成功。远端有新提交、落后数未知，
  // 仍然提示有更新；behind 给 null，改动面全 0（脚本拿不到）。
  const degradedPayload = kbPayload({
    remote_rev: 'feed777',
    behind: 'unknown',
    update_available: true,
    degraded: 'permission-denied',
    degraded_error: 'fetch 被沙箱拒绝（workspace-write）',
    surface: { knowledge: 0, routing: 0, reference: 0, methodology: 0, panel: 0, other: 0 },
    surface_known: false,
  })
  const degraded = newKbHarness(degradedPayload, false)
  const degradedValue = (await kbRpc(degraded.harness, 'copilot-kb-recheck', {}, 'kb-recheck-degraded')).envelope.result.value
  expect('知识库：退化 payload 出现 updateAvailable 提示且 behind 为 null',
    degradedValue && degradedValue.notice
    && degradedValue.notice.rev === 'feed777'
    && degradedValue.notice.behind === null
    && degradedValue.notice.updateAvailable === true
    && degradedValue.notice.degraded === 'permission-denied'
    && degradedValue.notice.panel === 0 && degradedValue.notice.knowledge === 0
    && degradedValue.notice.reference === 0,
    JSON.stringify(degradedValue))
  const degradedState = (await kbRpc(degraded.harness, 'copilot-state', {
    sessionId: 'kb-degraded', cwd: SANDBOX,
  }, 'kb-state-degraded')).envelope.result.value
  const fileDegraded = readKbState()
  expect('知识库：退化提示随 copilot-state 下发、状态文件记 degraded 与 updateAvailable',
    degradedState && degradedState.kbNotice && degradedState.kbNotice.rev === 'feed777'
    && degradedState.kbNotice.behind === null
    && fileDegraded && fileDegraded.rev === 'feed777'
    && fileDegraded.degraded === 'permission-denied' && fileDegraded.updateAvailable === true
    && fileDegraded.failures === 0,
    JSON.stringify({ notice: degradedState && degradedState.kbNotice, file: fileDegraded }))
  const degradedSynced = newKbHarness(kbPayload({
    remote_rev: 'feed888',
    behind: 0,
    degraded: 'permission-denied',
    update_available: false,
    surface: { knowledge: 0, routing: 0, reference: 0, methodology: 0, panel: 0, other: 0 },
    surface_known: false,
  }), false)
  const degradedSyncedValue = (await kbRpc(degradedSynced.harness, 'copilot-kb-recheck', {}, 'kb-recheck-degraded-synced')).envelope.result.value
  expect('知识库：update_available=false 的退化探测不提示（等同已同步）',
    degradedSyncedValue && degradedSyncedValue.notice === null, JSON.stringify(degradedSyncedValue))

  // ② 稍后：notice 置空，记录落盘；同一 rev 换个进程（新 harness）也不再提示。
  const dismissFirst = (await kbRpc(first.harness, 'copilot-kb-dismiss', {
    rev: '9f8e7d',
  }, 'kb-dismiss-1')).envelope.result.value
  expect('知识库：稍后返回记录的 rev 并报 saved:true',
    dismissFirst && dismissFirst.rev === '9f8e7d' && dismissFirst.saved === true,
    JSON.stringify(dismissFirst))
  const afterDismiss = (await kbRpc(first.harness, 'copilot-state', {
    sessionId: 'kb-session', cwd: SANDBOX,
  }, 'kb-state-2')).envelope.result.value
  expect('知识库：稍后后 notice 置空',
    afterDismiss && afterDismiss.kbNotice === null, JSON.stringify(afterDismiss && afterDismiss.kbNotice))
  const fileDismissed = readKbState()
  expect('知识库：dismissedRev 落盘',
    fileDismissed && fileDismissed.dismissedRev === '9f8e7d', JSON.stringify(fileDismissed))
  expect('知识库：recheck 读出落盘的稍后记录',
    (await kbRpc(first.harness, 'copilot-kb-recheck', {}, 'kb-recheck-3')).envelope.result.value.notice === null)

  const sameRev = newKbHarness(kbPayload({}), false)
  const sameRevValue = (await kbRpc(sameRev.harness, 'copilot-kb-recheck', {}, 'kb-recheck-same')).envelope.result.value
  expect('知识库：同一 rev 不再出现（稍后记录跨进程有效）',
    sameRevValue && sameRevValue.notice === null, JSON.stringify(sameRevValue))

  // ③ 换 rev 再出现。
  const newRev = newKbHarness(kbPayload({
    remote_rev: 'abc1234', behind: 2,
    surface: { knowledge: 1, routing: 0, reference: 0, methodology: 0, panel: 0, other: 0 },
  }), false)
  const newRevValue = (await kbRpc(newRev.harness, 'copilot-kb-recheck', {}, 'kb-recheck-new')).envelope.result.value
  expect('知识库：换 rev 再出现',
    newRevValue && newRevValue.notice && newRevValue.notice.rev === 'abc1234'
    && newRevValue.notice.behind === 2 && newRevValue.notice.panel === 0 && newRevValue.notice.knowledge === 1
    && newRevValue.notice.kind === 'knowledge',
    JSON.stringify(newRevValue && newRevValue.notice))

  // ④ behind 0：不提示，状态文件记 0。
  const synced = newKbHarness(kbPayload({ remote_rev: 'abc1234', behind: 0 }), false)
  const syncedValue = (await kbRpc(synced.harness, 'copilot-kb-recheck', {}, 'kb-recheck-synced')).envelope.result.value
  expect('知识库：behind 0 不出现', syncedValue && syncedValue.notice === null, JSON.stringify(syncedValue))
  const fileSynced = readKbState()
  expect('知识库：behind 0 落到状态文件',
    fileSynced && fileSynced.behind === 0 && fileSynced.lastError === '',
    JSON.stringify(fileSynced))

  // ⑤ 降级路径：脚本报 disabled 时静默（--check 正常不会给这个 reason，旧脚本/自动路径兜底）；
  // 离线部署同样静默；sync.enabled=false 不影响 --check 的提醒（enabled 只作为状态上报）。
  const disabled = newKbHarness(kbPayload({ remote_rev: 'c0ffee1', behind: 2 }), false)
  const disabledBefore = (await kbRpc(disabled.harness, 'copilot-kb-recheck', {}, 'kb-recheck-disabled-before')).envelope.result.value
  expect('知识库：disabled 降级用例先有提示',
    disabledBefore && disabledBefore.notice && disabledBefore.notice.rev === 'c0ffee1',
    JSON.stringify(disabledBefore && disabledBefore.notice))
  disabled.shell.setPayload(kbPayload({
    ok: false, reason: 'disabled', enabled: false, behind: 2, remote_rev: 'c0ffee1',
  }))
  const disabledValue = (await kbRpc(disabled.harness, 'copilot-kb-recheck', { force: true }, 'kb-recheck-disabled')).envelope.result.value
  const disabledState = (await kbRpc(disabled.harness, 'copilot-state', {
    sessionId: 'kb-disabled', cwd: SANDBOX,
  }, 'kb-state-disabled')).envelope.result.value
  const fileDisabled = readKbState()
  expect('知识库：脚本报 disabled 时静默、不算错误且 notice 变 null',
    disabledValue && disabledValue.notice === null && disabledValue.reason === 'disabled'
    && disabledValue.error === ''
    && disabledState && disabledState.kbNotice === null
    && fileDisabled && fileDisabled.lastError === '',
    JSON.stringify({ value: disabledValue, notice: disabledState && disabledState.kbNotice, file: fileDisabled }))

  // --check 不看 sync.enabled：脚本照常给 behind，host 不能把 enabled:false 当静默。
  const syncOff = newKbHarness(kbPayload({ enabled: false, remote_rev: 'e1e1e1', behind: 2 }), false)
  const syncOffValue = (await kbRpc(syncOff.harness, 'copilot-kb-recheck', {}, 'kb-recheck-sync-off')).envelope.result.value
  expect('知识库：sync.enabled=false 不影响提醒检查（有落后就提示）',
    syncOffValue && syncOffValue.notice && syncOffValue.notice.rev === 'e1e1e1'
    && syncOffValue.notice.behind === 2,
    JSON.stringify(syncOffValue))

  const offline = newKbHarness(kbPayload({
    ok: false, reason: 'offline', enabled: true, offline: true, behind: 1, remote_rev: 'def5678',
  }), false)
  const offlineValue = (await kbRpc(offline.harness, 'copilot-kb-recheck', {}, 'kb-recheck-offline')).envelope.result.value
  expect('知识库：离线部署时静默',
    offlineValue && offlineValue.notice === null && offlineValue.reason === 'offline', JSON.stringify(offlineValue))

  // ⑥ 失败保留提示：先成功一次（behind 3 / rev a11ce55），再注入网络失败。
  // 已显示的提示不清（网络抖动不该让仍然成立的落后数消失）、状态文件 rev/behind 保留、原文落 lastError。
  const failing = newKbHarness(kbPayload({ remote_rev: 'a11ce55', behind: 3 }), false)
  const seedValue = (await kbRpc(failing.harness, 'copilot-kb-recheck', {}, 'kb-recheck-seed')).envelope.result.value
  const fileSeed = readKbState()
  expect('知识库：失败前先成功一次（behind 3 / rev a11ce55）',
    seedValue && seedValue.notice && seedValue.notice.rev === 'a11ce55' && seedValue.notice.behind === 3
    && fileSeed && fileSeed.rev === 'a11ce55' && fileSeed.behind === 3,
    JSON.stringify({ value: seedValue, file: fileSeed }))
  failing.shell.setPayload(kbPayload({
    ok: false, reason: 'network', behind: 'unknown', remote_rev: null,
    fetch_error: 'fatal: unable to access https://example.invalid/x: Could not resolve host',
  }))
  const failedValue = (await kbRpc(failing.harness, 'copilot-kb-recheck', { force: true }, 'kb-recheck-failed')).envelope.result.value
  const failedState = (await kbRpc(failing.harness, 'copilot-state', {
    sessionId: 'kb-failed', cwd: SANDBOX,
  }, 'kb-state-failed')).envelope.result.value
  const fileFailed = readKbState()
  expect('知识库：网络失败时提示保留、原文落 lastError、上次 rev/behind 不变',
    failedValue && failedValue.notice && failedValue.notice.rev === 'a11ce55'
    && failedValue.notice.behind === 3
    && failedValue.reason === 'network'
    && /fatal: unable to access/.test(failedValue.error || '')
    && failedState && failedState.kbNotice && failedState.kbNotice.rev === 'a11ce55'
    && fileFailed && /fatal: unable to access/.test(fileFailed.lastError || '')
    && fileFailed.rev === 'a11ce55' && fileFailed.behind === 3,
    JSON.stringify({ value: failedValue, notice: failedState && failedState.kbNotice, file: fileFailed }))

  // ⑥b 连续失败上屏：未满 3 次仍静默；失败冷却里的跳过（doc.skipped）不计入连败；
  // 满 3 次或权限拒绝时 kbError 出现；成功一次后清空、failures 归零。
  const streak = newKbHarness(kbPayload({ remote_rev: 'bad0001', behind: 3 }), false)
  await kbRpc(streak.harness, 'copilot-kb-recheck', {}, 'kb-streak-seed')
  const networkFailure = kbPayload({
    ok: false, reason: 'network', behind: 'unknown', remote_rev: null,
    fetch_error: 'fatal: unable to access https://example.invalid/x: Could not resolve host',
  })
  streak.shell.setPayload(networkFailure)
  await kbRpc(streak.harness, 'copilot-kb-recheck', { force: true }, 'kb-streak-1')
  streak.shell.setPayload(kbPayload({
    ok: false, reason: 'cooldown', skipped: true, behind: 0, remote_rev: null,
  }))
  await kbRpc(streak.harness, 'copilot-kb-recheck', { force: true }, 'kb-streak-skipped')
  const afterSkipped = (await kbRpc(streak.harness, 'copilot-state', {
    sessionId: 'kb-streak', cwd: SANDBOX,
  }, 'kb-state-streak-skipped')).envelope.result.value
  const fileSkipped = readKbState()
  expect('知识库：失败冷却里的跳过不计入连败、未满 3 次不上屏',
    fileSkipped && fileSkipped.failures === 1
    && afterSkipped && afterSkipped.kbError === null,
    JSON.stringify({ file: fileSkipped, error: afterSkipped && afterSkipped.kbError }))
  streak.shell.setPayload(networkFailure)
  await kbRpc(streak.harness, 'copilot-kb-recheck', { force: true }, 'kb-streak-2')
  const afterTwo = (await kbRpc(streak.harness, 'copilot-state', {
    sessionId: 'kb-streak', cwd: SANDBOX,
  }, 'kb-state-streak-2')).envelope.result.value
  expect('知识库：连续失败 2 次仍静默',
    afterTwo && afterTwo.kbError === null
    && readKbState() && readKbState().failures === 2,
    JSON.stringify({ error: afterTwo && afterTwo.kbError, file: readKbState() }))
  await kbRpc(streak.harness, 'copilot-kb-recheck', { force: true }, 'kb-streak-3')
  const afterThree = (await kbRpc(streak.harness, 'copilot-state', {
    sessionId: 'kb-streak', cwd: SANDBOX,
  }, 'kb-state-streak-3')).envelope.result.value
  const fileThree = readKbState()
  expect('知识库：连续失败 3 次后 kbError 上屏',
    afterThree && afterThree.kbError
    && afterThree.kbError.reason === 'network'
    && /fatal: unable to access/.test(afterThree.kbError.message || '')
    && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/.test(afterThree.kbError.checkedAt || '')
    && fileThree && fileThree.failures === 3,
    JSON.stringify({ error: afterThree && afterThree.kbError, file: fileThree }))

  const permission = newKbHarness(kbPayload({ remote_rev: 'perm001', behind: 3 }), false)
  await kbRpc(permission.harness, 'copilot-kb-recheck', {}, 'kb-permission-seed')
  permission.shell.setPayload(kbPayload({
    ok: false, reason: 'permission-denied', behind: 0, remote_rev: 'perm001',
    fetch_error: 'fetch 被沙箱拒绝（workspace-write）',
  }))
  const permissionValue = (await kbRpc(permission.harness, 'copilot-kb-recheck', { force: true }, 'kb-permission-1')).envelope.result.value
  const permissionState = (await kbRpc(permission.harness, 'copilot-state', {
    sessionId: 'kb-permission', cwd: SANDBOX,
  }, 'kb-state-permission')).envelope.result.value
  expect('知识库：权限拒绝一次即出 kbError',
    permissionValue && permissionValue.kbError
    && permissionValue.kbError.reason === 'permission-denied'
    && permissionState && permissionState.kbError
    && permissionState.kbError.reason === 'permission-denied',
    JSON.stringify({ value: permissionValue && permissionValue.kbError, state: permissionState && permissionState.kbError }))
  permission.shell.setPayload(kbPayload({ remote_rev: 'perm001', behind: 2 }))
  const clearedValue = (await kbRpc(permission.harness, 'copilot-kb-recheck', { force: true }, 'kb-permission-2')).envelope.result.value
  const clearedState = (await kbRpc(permission.harness, 'copilot-state', {
    sessionId: 'kb-permission', cwd: SANDBOX,
  }, 'kb-state-permission-2')).envelope.result.value
  const fileCleared = readKbState()
  expect('知识库：成功检查后 kbError 清空、failures 归零',
    clearedValue && clearedValue.kbError === null
    && clearedState && clearedState.kbError === null
    && fileCleared && fileCleared.failures === 0,
    JSON.stringify({ value: clearedValue && clearedValue.kbError, state: clearedState && clearedState.kbError, file: fileCleared }))

  // ⑥b1 凭据失败（SSH 拿不到密钥 / known_hosts）：原因码按 credential 上报，状态条原文
  // 取 ssh 那行；内部取值不再以 `；credential` 的形式拼进用户可见的句子。
  const credential = newKbHarness(kbPayload({ remote_rev: 'cred001', behind: 3 }), false)
  await kbRpc(credential.harness, 'copilot-kb-recheck', {}, 'kb-credential-seed')
  credential.shell.setPayload(kbPayload({
    ok: false, reason: 'credential', behind: 'unknown', remote_rev: null,
    // 真实 `--check` 输出的形状：失败原文同时写在 fetch_error 与 last_error。
    fetch_error: 'Host key verification failed.', last_error: 'Host key verification failed.',
  }))
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await kbRpc(credential.harness, 'copilot-kb-recheck', { force: true }, 'kb-credential-' + attempt)
  }
  const credentialView = (await kbRpc(credential.harness, 'copilot-state', {
    sessionId: 'kb-credential', cwd: SANDBOX,
  }, 'kb-state-credential')).envelope.result.value
  expect('知识库：凭据失败按 credential 上报、原文取 ssh 那行且不重复',
    credentialView && credentialView.kbError
    && credentialView.kbError.reason === 'credential'
    && credentialView.kbError.message === 'Host key verification failed.'
    && credentialView.kbError.failures === 3,
    JSON.stringify({ error: credentialView && credentialView.kbError, file: readKbState() }))

  // ⑥b2 子进程超时：错误原文由调用点给——知识库检查只跑 git，不再套面板取数的 traces/ 猜测。
  const timeoutCheck = newKbHarness(kbPayload({ remote_rev: 'slow001', behind: 3 }), false)
  await kbRpc(timeoutCheck.harness, 'copilot-kb-recheck', {}, 'kb-timeout-seed')
  timeoutCheck.shell.setResult({
    exitCode: null, timedOut: true, aborted: false, stdout: { text: '' }, stderr: { text: '' },
  })
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await kbRpc(timeoutCheck.harness, 'copilot-kb-recheck', { force: true }, 'kb-timeout-' + attempt)
  }
  const timeoutView = (await kbRpc(timeoutCheck.harness, 'copilot-state', {
    sessionId: 'kb-timeout', cwd: SANDBOX,
  }, 'kb-state-timeout')).envelope.result.value
  expect('知识库：检查子进程超时的原文按检查对象给、不提 traces/',
    timeoutView && timeoutView.kbError
    && timeoutView.kbError.reason === 'E_TIMEOUT'
    && /^知识库检查超时（30 秒内没有返回/.test(timeoutView.kbError.message || '')
    && !/traces\//.test(timeoutView.kbError.message || ''),
    JSON.stringify({ error: timeoutView && timeoutView.kbError, file: readKbState() }))

  // ⑥b3 升级前的旧失败原文不原样上屏：状态文件里存着「数据脚本超时（可能 traces/ 很大）」，
  // 显示时丢掉原文、退化成失败次数兜底句，等下一次检查覆盖。
  writeFileSync(KB_STATE, JSON.stringify({
    version: 1,
    rev: 'old0001',
    behind: 0,
    surface: { knowledge: 0, routing: 0, reference: 0, methodology: 0, panel: 0, other: 0 },
    dismissedRev: '',
    checkedAt: '2026-11-10T06:56:14+08:00',
    lastError: '数据脚本超时（可能 traces/ 很大）。',
    degraded: '',
    updateAvailable: false,
    failures: 9,
  }, null, 2) + '\n', 'utf8')
  const legacyError = newKbHarness(kbPayload({ remote_rev: 'old0001', behind: 0 }), false)
  // kbDismiss 会等状态文件读完再落盘：用它把「启动读一次」这一步等到位。
  await kbRpc(legacyError.harness, 'copilot-kb-dismiss', { rev: 'old0001' }, 'kb-legacy-dismiss')
  const legacyState = (await kbRpc(legacyError.harness, 'copilot-state', {
    sessionId: 'kb-legacy', cwd: SANDBOX,
  }, 'kb-state-legacy')).envelope.result.value
  expect('知识库：升级前的旧超时句不再原样上屏、次数按状态文件给',
    legacyState && legacyState.kbError && legacyState.kbError.message === ''
    && legacyState.kbError.failures === 9
    && /^数据脚本超时（可能 traces\/ 很大）/.test((readKbState() || {}).lastError || ''),
    JSON.stringify({ error: legacyState && legacyState.kbError, file: readKbState() }))

  // ⑥c 关掉提醒检查也要收掉失败上屏与失败计数：只清内存不写盘的话，重启后仍会显示。
  // 关着期间的轮询不再重复写状态文件。
  const disabledAfterFailure = newKbHarness(kbPayload({ remote_rev: 'fail0001', behind: 3 }), makeFakeTimers())
  await disabledAfterFailure.timers.timeouts[0].fn()
  disabledAfterFailure.shell.setPayload(networkFailure)
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await kbRpc(disabledAfterFailure.harness, 'copilot-kb-recheck', { force: true }, 'kb-disabled-fail-' + attempt)
  }
  const beforeDisable = (await kbRpc(disabledAfterFailure.harness, 'copilot-state', {
    sessionId: 'kb-disabled-fail', cwd: SANDBOX,
  }, 'kb-state-disabled-fail-before')).envelope.result.value
  expect('知识库：关掉提醒前已连败 3 次、kbError 在屏',
    beforeDisable && beforeDisable.kbError && beforeDisable.kbError.reason === 'network'
    && readKbState() && readKbState().failures === 3,
    JSON.stringify({ error: beforeDisable && beforeDisable.kbError, file: readKbState() }))
  writeKbSettings({ check_enabled: false, check_minutes: 30 })
  await disabledAfterFailure.timers.timeouts[1].fn()
  const afterDisable = (await kbRpc(disabledAfterFailure.harness, 'copilot-state', {
    sessionId: 'kb-disabled-fail', cwd: SANDBOX,
  }, 'kb-state-disabled-fail-after')).envelope.result.value
  const fileAfterDisable = readKbState()
  expect('知识库：关掉提醒检查后 kbError 收掉、failures 与 lastError 归零',
    afterDisable && afterDisable.kbError === null
    && fileAfterDisable && fileAfterDisable.failures === 0 && fileAfterDisable.lastError === '',
    JSON.stringify({ error: afterDisable && afterDisable.kbError, file: fileAfterDisable }))
  // 状态文件是「先写临时文件再 rename」：每次写 mtime 都会变。关着时下一轮轮询不该再写。
  await new Promise((resolve) => setTimeout(resolve, 10))
  const mtimeAfterClear = statSync(KB_STATE).mtimeMs
  const callsAfterClear = kbSyncCalls(disabledAfterFailure.shell)
  await disabledAfterFailure.timers.timeouts[2].fn()
  const afterSecondPoll = (await kbRpc(disabledAfterFailure.harness, 'copilot-state', {
    sessionId: 'kb-disabled-fail', cwd: SANDBOX,
  }, 'kb-state-disabled-fail-poll')).envelope.result.value
  expect('知识库：关着提醒时后续轮询不跑子进程、不重复写状态文件',
    kbSyncCalls(disabledAfterFailure.shell) === callsAfterClear
    && afterSecondPoll && afterSecondPoll.kbError === null
    && statSync(KB_STATE).mtimeMs === mtimeAfterClear,
    JSON.stringify({
      calls: kbSyncCalls(disabledAfterFailure.shell),
      error: afterSecondPoll && afterSecondPoll.kbError,
      mtimeUnchanged: statSync(KB_STATE).mtimeMs === mtimeAfterClear,
    }))
  clearKbSettings()

  // ⑥d 手动重查要跳过脚本的失败冷却：普通检查脚本回 skipped，force 请求回真实结果。
  const cooldown = newKbHarness(kbPayload({
    ok: false, skipped: true, reason: 'network', behind: 'unknown', remote_rev: null,
    fetch_error: '失败冷却期内，脚本没有联网',
  }), false)
  cooldown.shell.setForcePayload(kbPayload({ remote_rev: 'warm001', behind: 2 }))
  const cooldownNormal = (await kbRpc(cooldown.harness, 'copilot-kb-recheck', {}, 'kb-cooldown-normal')).envelope.result.value
  const cooldownFile = readKbState()
  const cooldownForced = (await kbRpc(cooldown.harness, 'copilot-kb-recheck', { force: true }, 'kb-cooldown-forced')).envelope.result.value
  const cooldownCommands = cooldown.shell.calls.filter((command) => command.includes('kb_sync.py'))
  expect('知识库：手动重查把 --force 传给脚本、冷却内拿到真实结果',
    cooldownCommands.length === 2
    && !/(^|\s)--force(\s|$)/.test(cooldownCommands[0])
    && /(^|\s)--force(\s|$)/.test(cooldownCommands[1])
    && cooldownNormal && cooldownNormal.notice === null
    && cooldownFile && cooldownFile.failures === 0
    && cooldownForced && cooldownForced.notice && cooldownForced.notice.rev === 'warm001'
    && cooldownForced.notice.behind === 2,
    JSON.stringify({ commands: cooldownCommands, normal: cooldownNormal, forced: cooldownForced && cooldownForced.notice }))

  // ⑦ 启动不从状态文件恢复提示：文件里有上次成功的落后数，第一次检查前 kbNotice 仍是 null；
  // 检查完成后才出现。状态文件只恢复「稍后」记录与排查字段。
  const restoring = newKbHarness(kbPayload({ remote_rev: 'beef001', behind: 2 }), false)
  const restoringValue = (await kbRpc(restoring.harness, 'copilot-kb-recheck', {}, 'kb-recheck-seed-restore')).envelope.result.value
  expect('知识库：启动用例先成功一次（behind 2 / rev beef001）',
    restoringValue && restoringValue.notice && restoringValue.notice.rev === 'beef001'
    && readKbState() && readKbState().rev === 'beef001',
    JSON.stringify(restoringValue))
  const restored = newKbHarness(kbPayload({ remote_rev: 'beef001', behind: 2 }), false)
  let restoredNotice = null
  for (let attempt = 0; attempt < 25; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 20))
    const polled = (await kbRpc(restored.harness, 'copilot-state', {
      sessionId: 'kb-restore', cwd: SANDBOX,
    }, 'kb-state-restore')).envelope.result.value
    restoredNotice = polled ? polled.kbNotice : null
    if (restoredNotice) break
  }
  expect('知识库：启动后第一次检查前不提示（不恢复状态文件里的落后数）',
    restoredNotice === null && restored.shell.calls.every((command) => !command.includes('kb_sync.py')),
    JSON.stringify({ notice: restoredNotice, calls: restored.shell.calls }))
  const restoredCheck = (await kbRpc(restored.harness, 'copilot-kb-recheck', {}, 'kb-recheck-restore')).envelope.result.value
  expect('知识库：检查完成后才出现提示',
    restoredCheck && restoredCheck.notice && restoredCheck.notice.rev === 'beef001'
    && readKbState() && readKbState().rev === 'beef001',
    JSON.stringify(restoredCheck))

  restoring.shell.setPayload(kbPayload({
    ok: false, reason: 'disabled', enabled: false, behind: 2, remote_rev: 'beef001',
  }))
  const quietValue = (await kbRpc(restoring.harness, 'copilot-kb-recheck', { force: true }, 'kb-recheck-seed-quiet')).envelope.result.value
  const fileQuiet = readKbState()
  expect('知识库：disabled 降级时清提示并保留 rev/behind 供排查',
    quietValue && quietValue.notice === null
    && fileQuiet && fileQuiet.rev === 'beef001' && fileQuiet.behind === 2,
    JSON.stringify({ value: quietValue, file: fileQuiet }))
  // 新进程启动时状态文件里仍有 rev/behind，但提示已由 disabled 清掉：第一次检查前请求状态也不能闪提示。
  const silent = newKbHarness(kbPayload({ remote_rev: 'beef001', behind: 2 }), false)
  let silentNotice = null
  await new Promise((resolve) => setTimeout(resolve, 30))
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const polled = (await kbRpc(silent.harness, 'copilot-state', {
      sessionId: 'kb-silent', cwd: SANDBOX,
    }, 'kb-state-silent')).envelope.result.value
    silentNotice = polled ? polled.kbNotice : null
    if (silentNotice) break
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  expect('知识库：disabled 降级后重启不闪旧提示',
    silentNotice === null && silent.shell.calls.every((command) => !command.includes('kb_sync.py')),
    JSON.stringify({ notice: silentNotice, calls: silent.shell.calls }))

  // ⑧ 稍后写盘失败要能报且回滚：把临时根的 .local/ 占成普通文件，落盘必失败。
  // dismiss 回 saved:false、dismissedRev 回滚（不覆盖此前成功写入的记录）、提示保留。
  const dismissFail = newKbHarness(kbPayload({ remote_rev: '0ddba11', behind: 2 }), false)
  const dismissFailSeed = (await kbRpc(dismissFail.harness, 'copilot-kb-recheck', {}, 'kb-recheck-seed-dismissfail')).envelope.result.value
  expect('知识库：写失败用例先有提示',
    dismissFailSeed && dismissFailSeed.notice && dismissFailSeed.notice.rev === '0ddba11',
    JSON.stringify(dismissFailSeed && dismissFailSeed.notice))
  const stateBeforeFail = readKbState()
  const localPath = join(KB_REPO, '.local')
  rmSync(localPath, { recursive: true, force: true })
  writeFileSync(localPath, '占位：让状态文件写不进去\n', 'utf8')
  const failedDismiss = (await kbRpc(dismissFail.harness, 'copilot-kb-dismiss', {
    rev: '0ddba11',
  }, 'kb-dismiss-failed')).envelope.result.value
  const afterFailedDismiss = (await kbRpc(dismissFail.harness, 'copilot-state', {
    sessionId: 'kb-dismiss-fail', cwd: SANDBOX,
  }, 'kb-state-dismiss-fail')).envelope.result.value
  const stateWhileBroken = readKbState()
  // 还原 .local/ 再成功检查一次：内存里应已回滚到失败前的 dismissedRev，落盘后能读到。
  rmSync(localPath, { recursive: true, force: true })
  await kbRpc(dismissFail.harness, 'copilot-kb-recheck', { force: true }, 'kb-recheck-dismissfail-after')
  const stateAfterFail = readKbState()
  expect('知识库：稍后写盘失败回 saved:false、提示保留且 dismissedRev 回滚',
    failedDismiss && failedDismiss.rev === '0ddba11' && failedDismiss.saved === false
    && afterFailedDismiss && afterFailedDismiss.kbNotice && afterFailedDismiss.kbNotice.rev === '0ddba11'
    && stateBeforeFail && stateBeforeFail.dismissedRev !== '0ddba11'
    && stateWhileBroken === null
    && stateAfterFail && stateAfterFail.dismissedRev === stateBeforeFail.dismissedRev,
    JSON.stringify({
      value: failedDismiss,
      notice: afterFailedDismiss && afterFailedDismiss.kbNotice,
      before: stateBeforeFail && stateBeforeFail.dismissedRev,
      after: stateAfterFail && stateAfterFail.dismissedRev,
    }))

  // ⑨ panel 0：提示里的面板数字为 0，客户端据此不提「重启 DSH」。
  const noPanel = newKbHarness(kbPayload({
    remote_rev: 'feed123', behind: 1,
    surface: { knowledge: 1, routing: 0, reference: 0, methodology: 0, panel: 0, other: 0 },
  }), false)
  const noPanelValue = (await kbRpc(noPanel.harness, 'copilot-kb-recheck', {}, 'kb-recheck-nopanel')).envelope.result.value
  expect('知识库：surface.panel 0 时 notice.panel 0',
    noPanelValue && noPanelValue.notice && noPanelValue.notice.panel === 0
    && noPanelValue.notice.knowledge === 1, JSON.stringify(noPanelValue && noPanelValue.notice))

  // ⑩ 主检出解析：worktree 里的会话按主检出检查与落盘。
  const worktree = join(KB_SANDBOX, 'wt')
  mkdirSync(join(KB_REPO, '.git', 'worktrees', 'kb-wt'), { recursive: true })
  mkdirSync(worktree, { recursive: true })
  writeFileSync(join(worktree, '.git'), 'gitdir: ' + join(KB_REPO, '.git', 'worktrees', 'kb-wt') + '\n', 'utf8')
  const savedRoot = process.env.DSH_SLEUTH_KB_ROOT
  process.env.DSH_SLEUTH_KB_ROOT = worktree
  const fromWorktree = newKbHarness(kbPayload({ remote_rev: 'feed123', behind: 1 }), false)
  const worktreeValue = (await kbRpc(fromWorktree.harness, 'copilot-kb-recheck', {}, 'kb-recheck-wt')).envelope.result.value
  process.env.DSH_SLEUTH_KB_ROOT = savedRoot
  const worktreeCommand = fromWorktree.shell.calls.filter((command) => command.includes('kb_sync.py')).pop() || ''
  expect('知识库：worktree 会话按主检查重',
    worktreeValue && worktreeValue.notice
    && worktreeCommand.includes("--root '" + KB_REPO + "'")
    && !worktreeCommand.includes("--root '" + worktree + "'"),
    JSON.stringify({ value: worktreeValue, command: worktreeCommand }))

  // ⑪ 检出里没有 scripts/kb_sync.py：静默停用，不报错也不起子进程。
  process.env.DSH_SLEUTH_KB_ROOT = KB_SANDBOX
  const noScript = newKbHarness(kbPayload({}), false)
  const noScriptValue = (await kbRpc(noScript.harness, 'copilot-kb-recheck', {}, 'kb-recheck-noscript')).envelope.result.value
  process.env.DSH_SLEUTH_KB_ROOT = KB_REPO
  expect('知识库：检出缺脚本时静默停用',
    noScriptValue && noScriptValue.notice === null && noScriptValue.reason === 'unavailable'
    && noScript.shell.calls.every((command) => !command.includes('kb_sync.py')),
    JSON.stringify(noScriptValue))

  // ⑫ 本机 HEAD 变了（终端 pull / 面板「立即同步」/ 别的会话同步过）：旧快照失效，
  // 用 `--show`（只读本地、不联网）重算；落后归零就撤提示，不起 fetch。
  const headFile = join(KB_REPO, '.git', 'HEAD')
  const headRef = join(KB_REPO, '.git', 'refs', 'heads', 'main')
  mkdirSync(dirname(headRef), { recursive: true })
  writeFileSync(headFile, 'ref: refs/heads/main\n', 'utf8')
  writeFileSync(headRef, 'aaaa1111\n', 'utf8')
  const movedShell = makeKbShell()
  movedShell.setPayload(kbPayload({ remote_rev: 'cafe001', behind: 3 }))
  const movedTimers = makeFakeTimers()
  const moved = makeHarness({ shell: movedShell, timer: movedTimers })
  kbHarnesses.push(moved)
  mod.apply(moved.ctx)
  await movedTimers.fireTimer()
  const movedState = (await kbRpc(moved, 'copilot-state', {
    sessionId: 'kb-moved', cwd: SANDBOX,
  }, 'kb-state-moved-1')).envelope.result.value
  expect('知识库：HEAD 没变时不做本地重算',
    movedState && movedState.kbNotice && movedState.kbNotice.behind === 3
    && kbSyncCalls(movedShell) === 1,
    JSON.stringify({ notice: movedState && movedState.kbNotice, calls: movedShell.calls }))
  writeFileSync(headRef, 'bbbb2222\n', 'utf8')
  movedShell.setShowPayload(kbPayload({
    behind: 0, local_rev: 'bbbb2222', remote_rev: 'bbbb2222',
    surface: { knowledge: 0, routing: 0, reference: 0, methodology: 0, panel: 0, other: 0 },
  }))
  const movedCleared = (await kbRpc(moved, 'copilot-state', {
    sessionId: 'kb-moved', cwd: SANDBOX,
  }, 'kb-state-moved-2')).envelope.result.value
  const movedCommands = movedShell.calls.filter((command) => command.includes('kb_sync.py'))
  expect('知识库：本机 HEAD 变了用 --show 重算、不 fetch',
    movedCommands.length === 2 && /(^|\s)--show(\s|$)/.test(movedCommands[1])
    && !/--check|--sync|--merge/.test(movedCommands[1]),
    JSON.stringify(movedCommands))
  expect('知识库：重算后落后归零即撤提示',
    movedCleared && movedCleared.kbNotice === null,
    JSON.stringify(movedCleared && movedCleared.kbNotice))
  expect('知识库：重算结果落回状态文件',
    readKbState() && readKbState().behind === 0 && readKbState().rev === 'bbbb2222',
    JSON.stringify(readKbState()))
  // 清掉 HEAD 夹具：后面的用例照旧按「读不到 HEAD」跳过本地重算。
  rmSync(join(KB_REPO, '.git', 'refs'), { recursive: true, force: true })
  rmSync(headFile, { force: true })

  // ⑬ 文案按改动面分：只有面板代码说「面板代码落后」；只有 docs/scripts 等 other 面不提示。
  const panelOnly = newKbHarness(kbPayload({
    remote_rev: 'feed456', behind: 1,
    surface: { knowledge: 0, routing: 0, reference: 0, methodology: 0, panel: 2, other: 0 },
  }), false)
  const panelOnlyValue = (await kbRpc(panelOnly.harness, 'copilot-kb-recheck', {}, 'kb-recheck-panel-only')).envelope.result.value
  expect('知识库：只有面板代码时 kind=panel、不按知识库说',
    panelOnlyValue && panelOnlyValue.notice && panelOnlyValue.notice.kind === 'panel'
    && panelOnlyValue.notice.behind === 1 && panelOnlyValue.notice.knowledge === 0
    && panelOnlyValue.notice.panel === 0,
    JSON.stringify(panelOnlyValue && panelOnlyValue.notice))
  const docsOnly = newKbHarness(kbPayload({
    remote_rev: 'feed789', behind: 2,
    surface: { knowledge: 0, routing: 0, reference: 0, methodology: 0, panel: 0, other: 3 },
  }), false)
  const docsOnlyValue = (await kbRpc(docsOnly.harness, 'copilot-kb-recheck', {}, 'kb-recheck-docs-only')).envelope.result.value
  expect('知识库：只有 docs 等 other 面时不提示',
    docsOnlyValue && docsOnlyValue.notice === null, JSON.stringify(docsOnlyValue && docsOnlyValue.notice))
}

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

for (const harness of [rw, incHarness, internalHarness, ro, timeoutHarness, abortHarness, deniedHarness, truncatedHarness, noPolicyHarness, ...kbHarnesses].filter(Boolean)) {
  for (const cleanup of harness.effects) {
    try {
      cleanup()
    } catch {
      // 清理失败不影响退出码
    }
  }
}
expect('知识库：卸载时清掉排定的定时器',
  kbTimers !== null && kbTimers.timeouts.length === 4
  && kbTimers.timeouts.every((entry) => entry.disposed === true)
  && kbTimers.intervals.length === 0,
  JSON.stringify(kbTimers && { timeouts: kbTimers.timeouts.map((entry) => ({ ms: entry.ms, disposed: entry.disposed })) }))
expect('知识库：卸载时收回可选注入的 timer fiber',
  kbTimerHarness !== null
  && kbTimerHarness.injected.filter((item) => item.services.indexOf('timer') >= 0).length === 1
  && kbTimerHarness.injected.every((item) => item.services.indexOf('timer') < 0 || item.fiber.disposed === true),
  JSON.stringify(kbTimerHarness && kbTimerHarness.injected.map((item) => ({ services: item.services, disposed: item.fiber.disposed }))))
rmSync(SANDBOX, { recursive: true, force: true })
rmSync(KB_SANDBOX, { recursive: true, force: true })
delete process.env.DSH_SLEUTH_KB_ROOT

process.stdout.write('\n' + checks + ' 条断言，' + failures + ' 条失败\n')
process.exit(failures === 0 ? 0 : 1)
