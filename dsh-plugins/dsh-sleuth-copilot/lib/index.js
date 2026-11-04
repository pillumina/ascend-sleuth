/* eslint-disable */
// dsh-sleuth-copilot —— Host 半：一条 RPC 路由 + 一次受控的 Python 取数。
//
// 读：状态判据在 scripts/_trace_state.py（仓库里唯一的一份），这里不解析 YAML、不判状态。
// 写：状态修改一律经 scripts/trace_transition.py（校验 + CAS + 事件），这里只负责拼参数、
// 判定本会话有没有写权限、把脚本的 JSON 原样交回浏览器半。
//
// 路径与沙箱的两条边界都在这一层收口：
//   · traces 目录只认「本会话检出的 traces/」与「主检出的 traces/」两种，realpath 后比对；
//     客户端带回的路径只是候选，不因为它是绝对路径就当写沙箱根。
//   · 子进程都带会话档位（sandboxPolicy.resolve）：只读脚本跟随会话档位，写脚本用
//     workspace-write + 落点所在的检出根；解析不到档位时按只读处理，不假装可写。

import { fileURLToPath } from 'node:url'
import { dirname, join, sep } from 'node:path'
import { readFile, realpath, stat, writeFile, unlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const PKG_DIR = dirname(HERE)
const CHANNEL = '/sleuth-copilot'
const MAX_BODY_BYTES = 256 * 1024
// 浏览器半每 10 秒静默刷一次；这个窗口把同一瞬间的重复请求并成一次取数。
const CACHE_TTL_MS = 4000
const PY_TIMEOUT_MS = 20000
const PY_PROBE_TIMEOUT_MS = 4000
// 解释器探测失败只记很短一段：环境修好后下一次刷新就该自愈，但不至于让 10 秒轮询每轮都起三个子进程。
const PY_NEGATIVE_TTL_MS = 30000
// gh 就绪是「本机能力」：正常结果缓存 5 分钟；负结果只缓存 30 秒（刚装好 / 刚登录时不必等 5 分钟）。
const UPSTREAM_OK_TTL_MS = 5 * 60 * 1000
const UPSTREAM_BAD_TTL_MS = 30 * 1000
const MAX_REPORT_BYTES = 512 * 1024

export const name = 'dsh-sleuth-copilot'
export const inject = ['connection']

// 解释器只探测一次：Python 3 的启动器在 Windows 上可能是 python3（商店空壳）/ python / py -3。
let pythonCmd
let pythonProblem = ''
let pythonProbe = { at: 0, ok: false }

// 命令行参数转义。POSIX sh 用单引号最稳（`$`、反引号、反斜杠都不展开）；
// PowerShell 5.1（DSH 在 Windows 上的 shell）同样把单引号当字面量，内部单引号写两遍。
// 双引号写法在 PowerShell 里会被 `$` / 反引号展开，是原来的注入面。
function shq(value) {
  const text = String(value)
  if (process.platform === 'win32') return "'" + text.replace(/'/g, "''") + "'"
  return "'" + text.replace(/'/g, "'\\''") + "'"
}

function tailLines(text, limit) {
  return String(text || '').trim().split(/\r?\n/).filter(Boolean).slice(-limit).join('\n')
}

function errorText(error) {
  return String((error && error.message) || error)
}

function isAbsolutePath(value) {
  const text = String(value || '')
  return text.startsWith('/') || /^[A-Za-z]:[\\/]/.test(text) || text.startsWith('\\\\')
}

// 子进程起不来的方言：Windows 上是受限令牌沙箱的 runner 失败，退出码是 NTSTATUS
// （0xC0000142 进程初始化失败），或 runner 自己以 127 退出并在 stderr 报 windows-acl-run。
// 这类失败与"机器没装某样东西"是两回事，必须分开说，否则读者会被引去装包。
function looksLikeSpawnFailure(exitCode, text) {
  const code = Number(exitCode)
  if (Number.isFinite(code) && code < 0) return true
  if (Number.isFinite(code) && code >= 0xC0000000) return true
  if (code === 127 && /windows-acl-run|sandbox/i.test(String(text || ''))) return true
  return false
}

// 子进程结果的四种非正常收场，各给一个专码：调用方按 code 给一句人话，不靠解析 stderr。
// 退出码不在这里判：写脚本业务失败时也以非 0 退出，但它会照常吐出 JSON。
function resultFailure(result) {
  if (!result || typeof result !== 'object') return null
  if (result.timedOut) {
    return { code: 'E_TIMEOUT', message: '数据脚本超时（可能 traces/ 很大）。' }
  }
  if (result.aborted) {
    return { code: 'E_ABORT', message: '数据脚本被中止（会话或任务被中断）。' }
  }
  const sandbox = result.sandbox
  if (sandbox && sandbox.denied) {
    const mode = sandbox.mode ? 'mode=' + String(sandbox.mode) : 'mode 未知'
    const enforcement = sandbox.enforcement ? '，enforcement=' + String(sandbox.enforcement) : ''
    return {
      code: 'E_PERM',
      message: '沙箱拒绝了这次调用（' + mode + enforcement + '）：会话档位或可写根不覆盖这次读写。',
    }
  }
  if (result.stdout && (result.stdout.truncated === true || result.stdout.truncated === 'true')) {
    return { code: 'E_TRUNCATED', message: '子进程输出超过上限被截断，读到的 JSON 可能不完整。' }
  }
  return null
}

export function apply(ctx) {
  const cache = new Map()
  const inflight = new Map()
  const upstreamCache = new Map()

  ctx.effect(() => () => {
    cache.clear()
    inflight.clear()
    upstreamCache.clear()
  }, 'dsh-sleuth-copilot: state cache')

  function shellService() {
    return ctx.get('shell')
  }

  async function runShell(spec) {
    const shell = shellService()
    if (shell === undefined) throw new Error('shell 服务不可用')
    // 旧形态的服务直接有 run；当前 DSH 是 execute(spec) → 句柄，完成信息在 result() 上。
    if (typeof shell.run === 'function') return shell.run(spec)
    if (typeof shell.execute === 'function') {
      const execution = await shell.execute(spec)
      return typeof execution.result === 'function' ? await execution.result() : execution
    }
    throw new Error('shell 服务既没有 run 也没有 execute')
  }

  function resolveSpec(request) {
    const shell = shellService()
    if (shell === undefined || typeof shell.resolve !== 'function') {
      throw new Error('shell 服务不可用')
    }
    return shell.resolve(request)
  }

  async function isFile(path) {
    try {
      const info = await stat(path)
      return info.isFile()
    } catch {
      return false
    }
  }

  async function isDirectory(path) {
    try {
      const info = await stat(path)
      return info.isDirectory()
    } catch {
      return false
    }
  }

  async function realPathOrEmpty(path) {
    try {
      return await realpath(path)
    } catch {
      return ''
    }
  }

  // ── 会话沙箱档位 ───────────────────────────────────────────────────────────
  // 档位由 sandbox-policy 服务解析（显式授予 > 会话最后一条 sandbox/mode 事件 > 部署默认）。
  async function resolvePolicy(sessionId) {
    const policySvc = ctx.get('sandboxPolicy')
    if (!policySvc || typeof policySvc.resolve !== 'function') return undefined
    let session = null
    try {
      const sessions = ctx.get('sessions')
      session = sessions && typeof sessions.get === 'function' && sessionId ? sessions.get(sessionId) : null
    } catch {
      session = null
    }
    try {
      const policy = session ? policySvc.resolve({ session }) : policySvc.resolve()
      return policy && typeof policy.mode === 'string' ? policy : undefined
    } catch {
      return undefined
    }
  }

  // 写权限 = 档位解析得出且不是只读。解析不出时不写：把「服务缺席」当成「未限制」会让
  // 写请求在部署默认沙箱里失败，或者更糟——在没有沙箱的机器上以比会话预期更宽的权限落盘。
  async function writeCaps(sessionId) {
    const policy = await resolvePolicy(sessionId)
    if (policy === undefined) {
      return {
        canWrite: false,
        policy: undefined,
        reasonCode: 'E_POLICY',
        reason: '解析不到本会话的沙箱档位，写操作按只读拒绝（读不受影响）',
      }
    }
    if (policy.mode === 'read-only') {
      return { canWrite: false, policy, reasonCode: 'E_PERM', reason: '当前会话是只读档位，不能写 traces/' }
    }
    return { canWrite: true, policy, reasonCode: '', reason: '' }
  }

  // ── 上游查证就绪：gh CLI 与登录态 ─────────────────────────────────────────
  // 状态 RPC 每 10 秒轮询，不能每次都起两个子进程。缓存按检出根分键；refresh=true 清掉再探。
  async function upstreamReadiness(root, refresh, policy) {
    const key = String(root || '')
    const now = Date.now()
    const cached = upstreamCache.get(key)
    if (cached && cached.inflight) return cached.inflight
    if (!refresh && cached && cached.value) {
      const ttl = cached.value.ready ? UPSTREAM_OK_TTL_MS : UPSTREAM_BAD_TTL_MS
      if (now - cached.at < ttl) return cached.value
    }
    const pending = (async () => {
      let value = { ready: false, reason: '未检测到 gh CLI' }
      const readSpec = (command, timeoutMs, stdoutMaxBytes) => resolveSpec({
        command,
        workdir: root,
        timeoutMs,
        stdoutMaxBytes,
        ...(policy ? { sandboxPolicy: policy } : {}),
      })
      try {
        const version = await runShell(readSpec('gh --version', 4000, 4096))
        const versionOut = [version?.stdout?.text, version?.stderr?.text]
          .filter((text) => typeof text === 'string')
          .join('\n')
        if (!version || version.exitCode !== 0) {
          value = looksLikeSpawnFailure(version && version.exitCode, versionOut)
            ? { ready: false, reason: 'gh 探测的子进程起不来（沙箱或 runner 拒绝）：查上游需要能起子进程的会话档位' }
            : { ready: false, reason: '未安装 gh CLI（查上游 issue / PR 需要它）' }
        } else {
          const auth = await runShell(readSpec('gh auth status', 6000, 8192))
          value = auth && auth.exitCode === 0
            ? { ready: true, reason: '' }
            : { ready: false, reason: 'gh 未登录（gh auth login）' }
        }
      } catch (error) {
        value = { ready: false, reason: '环境检测失败：' + errorText(error) }
      }
      upstreamCache.set(key, { at: Date.now(), value, inflight: null })
      return value
    })()
    upstreamCache.set(key, { at: cached ? cached.at : 0, value: cached ? cached.value : null, inflight: pending })
    return pending
  }

  // ── Python 解释器探测 ─────────────────────────────────────────────────────
  // 正结果缓存到进程结束；负结果短 TTL（环境修好后自愈），并记下这次为什么失败，
  // 让界面能区分「没装 Python」与「子进程被沙箱挡在启动前」。
  async function resolvePython(workdir, policy) {
    if (pythonCmd !== undefined) return pythonCmd
    const now = Date.now()
    if (!pythonProbe.ok && pythonProbe.at && now - pythonProbe.at < PY_NEGATIVE_TTL_MS) return null
    let lastProblem = ''
    for (const candidate of ['python3', 'python', 'py -3']) {
      let result
      try {
        result = await runShell(resolveSpec({
          command: candidate + ' --version',
          workdir,
          timeoutMs: PY_PROBE_TIMEOUT_MS,
          stdoutMaxBytes: 4096,
          ...(policy ? { sandboxPolicy: policy } : {}),
        }))
      } catch (error) {
        lastProblem = candidate + ' 起不来：' + errorText(error)
        continue
      }
      if (result && result.timedOut) {
        lastProblem = candidate + ' 探测超时（' + PY_PROBE_TIMEOUT_MS + 'ms）'
        continue
      }
      if (result && result.sandbox && result.sandbox.denied) {
        lastProblem = candidate + ' 被沙箱拒绝（mode=' + String(result.sandbox.mode || '?') + '）'
        continue
      }
      const output = [result?.stdout?.text, result?.stderr?.text]
        .filter((text) => typeof text === 'string')
        .join('\n')
      if (result && result.exitCode === 0 && /Python 3\./.test(output)) {
        pythonCmd = candidate
        pythonProblem = ''
        pythonProbe = { at: Date.now(), ok: true }
        return candidate
      }
      lastProblem = looksLikeSpawnFailure(result && result.exitCode, output)
        ? candidate + ' 的子进程被沙箱或 runner 挡在启动前（exit ' + String(result && result.exitCode) + '）'
        : candidate + ' 不可用'
    }
    pythonProblem = lastProblem
    pythonProbe = { at: Date.now(), ok: false }
    return null
  }

  function noPythonMessage() {
    return '没找到可用的 Python 3（已试 python3 / python / py -3）。数据面脚本是 '
      + 'scripts/_trace_state.py 与插件里的 lib/copilot_state.py；装好 Python 3 并确保在 PATH 里，然后点刷新。'
      + (pythonProblem ? '（探测情况：' + pythonProblem + '）' : '')
  }

  // ── 检出与 traces/ 解析 ───────────────────────────────────────────────────
  async function resolveRepoRoot(cwd) {
    if (typeof cwd !== 'string' || !cwd) return null
    let dir = cwd
    for (let index = 0; index < 12; index += 1) {
      if (await isFile(join(dir, 'scripts', '_trace_state.py'))) return dir
      const parent = dirname(dir)
      if (parent === dir || parent === '') break
      dir = parent
    }
    return null
  }

  // 主检出解析：判据与 scripts/exec_log_path.py 的 main_checkout() 同一条（git 的 common dir
  // 的父目录）。这里不跑 git 子进程，按 `.git` 的两种形态直接推：
  //   · `.git` 是目录 → 该检出就是主检出；
  //   · `.git` 是文件 → 内容是 `gitdir: <主检出>/.git/worktrees/<名>`，父目录是主检出。
  // 认不出的形态返回 null，调用方退回会话自己的检出，不猜。
  const MAIN_CHECKOUT_CACHE = new Map()
  async function mainCheckoutOf(dir) {
    if (typeof dir !== 'string' || !dir) return null
    if (MAIN_CHECKOUT_CACHE.has(dir)) return MAIN_CHECKOUT_CACHE.get(dir)
    let found = null
    let current = dir
    for (let depth = 0; depth < 8; depth += 1) {
      let info = null
      try {
        info = await stat(join(current, '.git'))
      } catch {
        info = null
      }
      if (info !== null) {
        if (info.isDirectory()) {
          found = current
          break
        }
        let text = ''
        try {
          text = await readFile(join(current, '.git'), 'utf8')
        } catch {
          text = ''
        }
        const match = /^\s*gitdir:\s*(.+?)\s*$/m.exec(text)
        if (match) {
          const gitDir = match[1].replace(/\\/g, '/').replace(/\/+$/, '')
          const parts = /^(.*)\/\.git(?:\/.*)?$/.exec(gitDir)
          if (parts) {
            const parent = parts[1]
            if ((await isDirectory(join(parent, '.git'))) || (await isDirectory(join(parent, 'metrics')))) {
              found = parent
            }
          }
        }
        break
      }
      const parent = dirname(current)
      if (parent === current || parent === '') break
      current = parent
    }
    MAIN_CHECKOUT_CACHE.set(dir, found)
    return found
  }

  async function mainRootOf(root) {
    return (await mainCheckoutOf(root)) || root
  }

  // traces/ 的合法落点只有两种（都是 realpath 之后比对）：
  //   ① 本会话检出自己的 traces/（主检出里开会话时两者是同一个目录）；
  //   ② worktree 会话落到主检出的 traces/（运行时件锚主检出，见 CLAUDE.md 的多 agent 约束）。
  // 客户端带回的 tracesDir 只是候选，不在这个集合里就拒，不拿它当写沙箱根。
  async function canonicalTracesCandidates(root) {
    const candidates = []
    const own = await realPathOrEmpty(join(root, 'traces'))
    if (own) candidates.push(own)
    const main = await mainCheckoutOf(root)
    if (main && main !== root) {
      const mainTraces = await realPathOrEmpty(join(main, 'traces'))
      if (mainTraces && candidates.indexOf(mainTraces) < 0) candidates.push(mainTraces)
    }
    return candidates
  }

  // 省略 tracesDir 时的默认落点：主检出那一份（worktree 里读写的都是它）。
  async function defaultTracesDir(root) {
    const main = await mainRootOf(root)
    const real = await realPathOrEmpty(join(main, 'traces'))
    return { dir: real, writeRoot: real ? dirname(real) : main }
  }

  // 校验客户端给的 tracesDir；给了就必须是上面两个合法落点之一。返回 {dir, writeRoot} 或 {error}。
  async function resolveTracesDir(payload, root) {
    const requested = typeof payload.tracesDir === 'string' ? payload.tracesDir.trim() : ''
    if (!requested) return defaultTracesDir(root)
    if (!isAbsolutePath(requested)) {
      return { error: { code: 'E_SCHEMA', message: 'traces 目录必须是绝对路径' } }
    }
    const real = await realPathOrEmpty(requested)
    if (!real) {
      return { error: { code: 'E_NOT_FOUND', message: 'traces 目录不存在：' + requested } }
    }
    const candidates = await canonicalTracesCandidates(root)
    if (candidates.indexOf(real) < 0) {
      return {
        error: {
          code: 'E_SCHEMA',
          message: 'traces 目录不在本会话的检出里（只接受本会话检出的 traces/ 或主检出的 traces/）',
        },
      }
    }
    return { dir: real, writeRoot: dirname(real) }
  }

  // ── 状态读取 ───────────────────────────────────────────────────────────────
  async function computeState(sessionId, cwd, refresh) {
    const root = await resolveRepoRoot(cwd)
    if (root === null) {
      return {
        ok: false,
        code: 'E_NO_ROOT',
        message: '当前会话的工作区不是 ascend-sleuth 检出（找不到 scripts/_trace_state.py），状态条不显示。',
        cwd: typeof cwd === 'string' ? cwd : '',
      }
    }
    const caps = await writeCaps(sessionId)
    const python = await resolvePython(root, caps.policy)
    if (python === null) {
      return { ok: false, code: 'E_NO_PYTHON', message: noPythonMessage(), repoRoot: root }
    }
    const script = join(PKG_DIR, 'lib', 'copilot_state.py')
    if (!(await isFile(script))) {
      return { ok: false, code: 'E_NO_HELPER', message: '装进来的包缺少 lib/copilot_state.py：' + script }
    }
    const writeRoot = await mainRootOf(root)
    const argv = [python, shq(script), '--root', shq(root)]
    if (typeof sessionId === 'string' && sessionId) argv.push('--session', shq(sessionId))
    if (caps.canWrite) {
      argv.push('--can-write', '--write-root', shq(writeRoot))
    } else if (caps.reasonCode) {
      // 不可写的原因带进能力位：只读档位（E_PERM）与档位解析不出（E_POLICY）给界面的说明不同。
      argv.push('--write-reason-code', shq(caps.reasonCode), '--write-reason', shq(caps.reason))
    }

    let result
    try {
      result = await runShell(resolveSpec({
        command: argv.join(' '),
        workdir: root,
        timeoutMs: PY_TIMEOUT_MS,
        stdoutMaxBytes: 1024 * 1024,
        env: { PYTHONIOENCODING: 'utf-8' },
        ...(caps.policy ? { sandboxPolicy: caps.policy } : {}),
      }))
    } catch (error) {
      return {
        ok: false,
        code: 'E_SPAWN',
        message: '数据脚本执行失败：' + errorText(error),
        repoRoot: root,
      }
    }

    const failure = resultFailure(result)
    if (failure) return { ok: false, code: failure.code, message: failure.message, repoRoot: root }
    const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
    const stderr = result && result.stderr && typeof result.stderr.text === 'string' ? result.stderr.text : ''
    const trimmed = stdout.trim()
    if (!trimmed.startsWith('{')) {
      return {
        ok: false,
        code: 'E_OUTPUT',
        message: '数据脚本没有产出 JSON（exit ' + String(result ? result.exitCode : '?') + '）',
        detail: (stderr.trim() || trimmed).slice(-1200),
        repoRoot: root,
      }
    }
    let doc
    try {
      doc = JSON.parse(trimmed)
    } catch (error) {
      return {
        ok: false,
        code: 'E_JSON',
        message: '数据脚本输出不是合法 JSON：' + errorText(error),
        repoRoot: root,
      }
    }
    if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) {
      return { ok: false, code: 'E_SHAPE', message: '数据脚本输出不是对象。', repoRoot: root }
    }
    doc.repoRoot = root
    doc.upstream = await upstreamReadiness(root, refresh === true, caps.policy)
    return doc
  }

  function transitionFailure(code, message) {
    return { ok: false, code, message }
  }

  const TRACE_FILE_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.yaml$/

  function validTraceId(value) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/.test(String(value || ''))
  }

  function validTraceFile(value) {
    return TRACE_FILE_RE.test(String(value || ''))
  }

  function traceFileStem(value) {
    return String(value || '').replace(/\.yaml$/, '')
  }

  // 报告名归一：trace 里可能写成 `traces/x.report.md`、`traces\sub\x.report.md`、
  // `C:/repo/traces/x.report.md`，统一剥成 traces/ 内的相对路径（可为子目录）。
  function normalizeReportName(value) {
    const text = String(value == null ? '' : value).trim().replace(/\\/g, '/').replace(/^\.\//, '')
    if (!text) return ''
    const match = /(?:^|\/)traces\/(.+)$/.exec(text)
    return match ? match[1] : text
  }

  // traces/ 内的相对路径：允许子目录（traces/exports/x.md），拒绝绝对路径、盘符与 `..`。
  function relativeReportPath(value) {
    const name = normalizeReportName(value)
    if (!name || isAbsolutePath(name) || /^[A-Za-z]:/.test(name)) return ''
    const segments = name.split('/')
    for (const segment of segments) {
      if (!segment || segment === '.' || segment === '..') return ''
    }
    return segments.join('/')
  }

  // 读人读报告：只读、限大小，路径由「canonical traces + traces/ 内的相对名」拼出，
  // realpath 后还要确认没跑出 traces/（挡住经由符号链接的越界）。
  async function readReport(payload) {
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const traceId = String(payload.traceSessionId || '')
    const traceFile = String(payload.traceFile || '')
    if (!validTraceId(traceId) && !validTraceFile(traceFile)) {
      return { ok: false, code: 'E_SCHEMA', message: '诊断单号不合法' }
    }
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const traces = await resolveTracesDir(payload, root)
    if (traces.error) return { ok: false, ...traces.error }
    const tracesDir = traces.dir || join(await mainRootOf(root), 'traces')
    // 状态里带回的报告位置优先；否则按「文件名与 trace 同名」兜底。
    let requested = typeof payload.reportFile === 'string' ? payload.reportFile.trim() : ''
    if (!requested && traceFile) requested = traceFileStem(traceFile) + '.report.md'
    if (!requested) requested = traceId + '.report.md'
    const name = relativeReportPath(requested)
    if (!name) return { ok: false, code: 'E_SCHEMA', message: '报告文件名不合法' }
    const file = join(tracesDir, name)
    const real = await realPathOrEmpty(file)
    if (!real) return { ok: false, code: 'E_NOT_FOUND', message: '这单还没有人读报告' }
    const base = await realPathOrEmpty(tracesDir)
    if (base && real !== base && real.indexOf(base + sep) !== 0) {
      return { ok: false, code: 'E_SCHEMA', message: '报告不在 traces/ 目录内' }
    }
    try {
      const info = await stat(real)
      if (!info.isFile()) return { ok: false, code: 'E_NOT_FOUND', message: '这单还没有人读报告' }
      if (info.size > MAX_REPORT_BYTES) {
        return {
          ok: false,
          code: 'E_TOO_LARGE',
          message: '报告超过 512 KiB，请在编辑器里看 traces/' + name,
        }
      }
      const text = await readFile(real, 'utf8')
      return { ok: true, text, file: 'traces/' + name, bytes: info.size }
    } catch {
      return { ok: false, code: 'E_NOT_FOUND', message: '这单还没有人读报告' }
    }
  }

  // 单条轨迹的步骤时间线：只读、懒加载；Python 侧只摘录已有事件。
  async function readTimeline(payload) {
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const traceFile = String(payload.traceFile || '')
    if (!validTraceFile(traceFile)) {
      return { ok: false, code: 'E_SCHEMA', message: '轨迹文件名不合法' }
    }
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const policy = await resolvePolicy(payload.sessionId)
    const python = await resolvePython(root, policy)
    if (python === null) return { ok: false, code: 'E_NO_PYTHON', message: noPythonMessage() }
    const script = join(PKG_DIR, 'lib', 'copilot_state.py')
    if (!(await isFile(script))) return { ok: false, code: 'E_NO_HELPER', message: '装进来的包缺少 lib/copilot_state.py' }
    let tracesDir = ''
    if (typeof payload.tracesDir === 'string' && payload.tracesDir.trim()) {
      const traces = await resolveTracesDir(payload, root)
      if (traces.error) return { ok: false, ...traces.error }
      tracesDir = traces.dir
    }
    const argv = [python, shq(script), '--root', shq(root)]
    if (tracesDir) argv.push('--traces', shq(tracesDir))
    argv.push('--timeline', shq(traceFile))
    let result
    try {
      result = await runShell(resolveSpec({
        command: argv.join(' '),
        workdir: root,
        timeoutMs: PY_TIMEOUT_MS,
        stdoutMaxBytes: 1024 * 1024,
        env: { PYTHONIOENCODING: 'utf-8' },
        ...(policy ? { sandboxPolicy: policy } : {}),
      }))
    } catch (error) {
      return { ok: false, code: 'E_SPAWN', message: '数据脚本执行失败：' + errorText(error) }
    }
    const failure = resultFailure(result)
    if (failure) return { ok: false, code: failure.code, message: failure.message }
    const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
    const trimmed = stdout.trim()
    if (!trimmed.startsWith('{')) {
      return { ok: false, code: 'E_OUTPUT', message: '数据脚本没有产出 JSON（exit ' + String(result ? result.exitCode : '?') + '）' }
    }
    try {
      return JSON.parse(trimmed)
    } catch (error) {
      return { ok: false, code: 'E_JSON', message: '数据脚本输出不是合法 JSON：' + errorText(error) }
    }
  }

  // ── 状态写入 ───────────────────────────────────────────────────────────────
  // 参数走临时 JSON 文件（summary / handed_to 常含空格、引号与中文，拼命令行会被改写）。
  // 文件权限 0600；无论脚本成功、失败还是抛异常，finally 里都会删掉。
  async function applyTransition(payload) {
    const sessionId = typeof payload.sessionId === 'string' ? payload.sessionId : ''
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const traceId = String(payload.traceSessionId || '')
    const traceFile = String(payload.traceFile || '')
    const expectSha = String(payload.expectSha256 || '')
    const kind = String(payload.kind || '')
    // 写路径按轨迹文件名取（trace 的 session_id 与文件名可以不同，文件名才是磁盘上的落点；
    // 只按 sessionId 拼名会给这类单新建一个文件）。没给文件名时才退回单号。
    let sid = traceId
    if (traceFile) {
      if (!validTraceFile(traceFile)) return transitionFailure('E_SCHEMA', '轨迹文件名不合法')
      sid = traceFileStem(traceFile)
    }
    if (!validTraceId(sid)) return transitionFailure('E_SCHEMA', '诊断单号不合法')
    if (typeof payload.traceError === 'string' && payload.traceError.trim()) {
      return transitionFailure('E_PARSE', '这一单的 trace 读不出来，先修文件再改状态：' + payload.traceError.trim())
    }
    if (!/^[0-9a-f]{64}$/.test(expectSha)) {
      return transitionFailure('E_SCHEMA', '缺内容指纹，请刷新列表后重试')
    }
    const caps = await writeCaps(sessionId)
    if (!caps.canWrite) return transitionFailure(caps.reasonCode || 'E_PERM', caps.reason)
    const root = await resolveRepoRoot(cwd)
    if (root === null) return transitionFailure('E_NO_ROOT', '当前工作区不是 ascend-sleuth 检出')
    const python = await resolvePython(root, caps.policy)
    if (python === null) return transitionFailure('E_NO_PYTHON', noPythonMessage())
    const traces = await resolveTracesDir(payload, root)
    if (traces.error) return transitionFailure(traces.error.code, traces.error.message)
    const writeRoot = traces.writeRoot || (await mainRootOf(root))
    // 客户端显式给了 tracesDir 才转给脚本；没给时让脚本按主检出解析（那是唯一权威的判据），
    // host 只把同一个默认落点用作写沙箱根——两处不一致时宁可被沙箱拒绝，也不写到别处。
    const tracesExplicit = typeof payload.tracesDir === 'string' && payload.tracesDir.trim() !== ''

    const body = {}
    const extraArgs = []
    if (kind === 'sedimented') {
      const state = String(payload.state || '')
      if (!state) return transitionFailure('E_SCHEMA', '需要一个沉淀状态', ['sedimented.state'])
      // 合法值交给 trace_transition.py 按 trace-status.yaml 判，host 不再抄一份词表。
      extraArgs.push('--field', 'sedimented', '--state', shq(state))
      if (payload.caseId) {
        const caseId = String(payload.caseId)
        if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,120}$/.test(caseId)) {
          return transitionFailure('E_SCHEMA', 'case 编号不合法')
        }
        extraArgs.push('--case-id', shq(caseId))
      }
      if (payload.inboxPath) extraArgs.push('--inbox-path', shq(String(payload.inboxPath)))
    } else if (kind === 'reopen') {
      body.reopen = true
    } else if (kind === 'close') {
      const to = String(payload.to || '')
      if (!to) return transitionFailure('E_SCHEMA', '目标状态不合法')
      // 目标状态是否在词表里由脚本校验；host 只保证参数非空。
      body.to = to
      if (payload.endingKind) body.kind = String(payload.endingKind)
      if (payload.handedTo) body.handed_to = String(payload.handedTo)
      if (payload.duplicateOf) body.duplicate_of = String(payload.duplicateOf)
      for (const key of ['summary', 'severity', 'fix_emitted']) {
        if (payload[key] !== undefined && payload[key] !== null) body[key] = payload[key]
      }
    } else if (kind === 'correct-ending') {
      // 终态单改收尾方式：`to` 是新目标状态（可与当前状态相同），脚本按 --correct-ending 走。
      const to = String(payload.to || '')
      if (!to) return transitionFailure('E_SCHEMA', '目标状态不合法')
      body.to = to
      if (payload.endingKind) body.kind = String(payload.endingKind)
      if (payload.handedTo) body.handed_to = String(payload.handedTo)
      if (payload.duplicateOf) body.duplicate_of = String(payload.duplicateOf)
      if (payload.note !== undefined && payload.note !== null) body.note = String(payload.note)
      for (const key of ['summary', 'severity', 'fix_emitted']) {
        if (payload[key] !== undefined && payload[key] !== null) body[key] = payload[key]
      }
      extraArgs.push('--correct-ending')
    } else if (kind === 'backfill-ending') {
      // 已收尾但缺收尾方式：只补写 ending，不改状态。
      const endingKind = String(payload.endingKind || '')
      if (!endingKind) return transitionFailure('E_SCHEMA', '补记收尾方式需要指定收尾方式')
      body.kind = endingKind
      if (payload.handedTo) body.handed_to = String(payload.handedTo)
      if (payload.duplicateOf) body.duplicate_of = String(payload.duplicateOf)
      if (payload.note !== undefined && payload.note !== null) body.note = String(payload.note)
      extraArgs.push('--backfill-ending')
    } else {
      return transitionFailure('E_SCHEMA', '未知的写入类型：' + kind)
    }

    const payloadFile = join(tmpdir(), 'sleuth-copilot-' + process.pid + '-' + Date.now() + '-'
      + Math.random().toString(36).slice(2, 8) + '.json')
    try {
      await writeFile(payloadFile, JSON.stringify(body), { encoding: 'utf8', mode: 0o600 })
    } catch (error) {
      return transitionFailure('E_IO', '写参数文件失败：' + errorText(error))
    }

    try {
      const script = join(root, 'scripts', 'trace_transition.py')
      const argv = [python, shq(script), shq(sid),
        '--root', shq(root), '--by', 'user', '--source', 'panel', '--json',
        '--expect-sha256', shq(expectSha), ...extraArgs,
        '--payload-file', shq(payloadFile)]
      if (tracesExplicit && traces.dir) argv.push('--traces', shq(traces.dir))
      const schemeVersion = typeof payload.schemeVersion === 'string' ? payload.schemeVersion.trim() : ''
      if (schemeVersion) argv.push('--scheme-version', shq(schemeVersion))
      let result
      try {
        result = await runShell(resolveSpec({
          command: argv.join(' '),
          workdir: root,
          timeoutMs: 60000,
          stdoutMaxBytes: 262144,
          env: { PYTHONIOENCODING: 'utf-8' },
          sandboxPolicy: { mode: 'workspace-write', workspaceRoot: writeRoot },
        }))
      } catch (error) {
        return transitionFailure('E_IO', '写状态脚本执行失败：' + errorText(error))
      }
      const failure = resultFailure(result)
      if (failure) return transitionFailure(failure.code, failure.message)
      const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text.trim() : ''
      const stderr = result && result.stderr && typeof result.stderr.text === 'string' ? result.stderr.text : ''
      if (stdout.startsWith('{')) {
        try {
          return JSON.parse(stdout)
        } catch {
          // 落到下面统一的错误分支
        }
      }
      const tail = tailLines(stderr || stdout, 4)
      return {
        ok: false,
        code: 'E_IO',
        message: '写状态脚本没有返回 JSON（exit ' + String(result ? result.exitCode : '?') + '）'
          + (tail ? '：' + tail : ''),
      }
    } finally {
      await unlink(payloadFile).catch(() => {})
    }
  }

  // ── 沉淀队列与提 PR 目标：按需读取，不进 10 秒轮询 ─────────────────────
  async function runJsonHelper(root, python, script, args, timeoutMs, policy) {
    let result
    try {
      result = await runShell(resolveSpec({
        command: [python, shq(script), ...args].join(' '),
        workdir: root,
        timeoutMs,
        stdoutMaxBytes: 2 * 1024 * 1024,
        env: { PYTHONIOENCODING: 'utf-8' },
        ...(policy ? { sandboxPolicy: policy } : {}),
      }))
    } catch (error) {
      return { ok: false, code: 'E_SPAWN', message: '数据脚本执行失败：' + errorText(error) }
    }
    const failure = resultFailure(result)
    if (failure) return { ok: false, code: failure.code, message: failure.message }
    const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
    const stderr = result && result.stderr && typeof result.stderr.text === 'string' ? result.stderr.text : ''
    const trimmed = stdout.trim()
    if (!trimmed.startsWith('{')) {
      return {
        ok: false,
        code: 'E_OUTPUT',
        message: '数据脚本没有产出 JSON（exit ' + String(result ? result.exitCode : '?') + '）',
        detail: (stderr.trim() || trimmed).slice(-1200),
      }
    }
    try {
      const doc = JSON.parse(trimmed)
      return doc && typeof doc === 'object' && !Array.isArray(doc) ? doc : { ok: false, code: 'E_SHAPE', message: '脚本输出不是对象' }
    } catch (error) {
      return { ok: false, code: 'E_JSON', message: '脚本输出不是合法 JSON：' + errorText(error) }
    }
  }

  async function computeSediment(cwd, sessionId) {
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const policy = await resolvePolicy(sessionId)
    const python = await resolvePython(root, policy)
    if (python === null) return { ok: false, code: 'E_NO_PYTHON', message: noPythonMessage() }
    const script = join(PKG_DIR, 'lib', 'sediment_state.py')
    if (!(await isFile(script))) return { ok: false, code: 'E_NO_HELPER', message: '装进来的包缺少 lib/sediment_state.py' }
    const args = ['--root', shq(root), '--json']
    const doc = await runJsonHelper(root, python, script, args, 30000, policy)
    doc.repoRoot = root
    return doc
  }

  function validDraftKey(value) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/.test(String(value || ''))
  }

  // PR 台账写在共享 inbox（主检出侧），写动作的沙箱根取主检出。
  async function prTarget(payload) {
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const policy = await resolvePolicy(payload.sessionId)
    const python = await resolvePython(root, policy)
    if (python === null) return { ok: false, code: 'E_NO_PYTHON', message: noPythonMessage() }
    const script = join(root, 'scripts', 'pr_status.py')
    if (!(await isFile(script))) return { ok: false, code: 'E_NO_HELPER', message: '检出里缺少 scripts/pr_status.py' }
    const action = String(payload.action || 'list')
    const rootArgs = ['--root', shq(root)]
    if (action === 'list') {
      // 一次调用就带出台账指纹（pr_status.py 的 list-targets 返回 sha256，台账不存在为 null）：
      // 写动作的 CAS 令牌由客户端从这里取，不再单起一次 --status。
      return runJsonHelper(root, python, script, [...rootArgs, '--list-targets', '--json'], 30000, policy)
    }
    const caps = await writeCaps(payload.sessionId)
    if (!caps.canWrite) return { ok: false, code: caps.reasonCode || 'E_PERM', message: caps.reason }
    const mainRoot = await mainRootOf(root)
    const writePolicy = { mode: 'workspace-write', workspaceRoot: mainRoot }
    const expectSha = typeof payload.expectSha256 === 'string' ? payload.expectSha256.trim() : ''
    if (expectSha && !/^[0-9a-f]{64}$/.test(expectSha)) {
      return { ok: false, code: 'E_SCHEMA', message: '台账内容指纹格式不对，请刷新沉淀队列后重试' }
    }
    const casArgs = expectSha ? ['--expect-sha256', shq(expectSha)] : []
    const argv = [...rootArgs]
    if (action === 'check') {
      if (!validDraftKey(payload.key)) return { ok: false, code: 'E_SCHEMA', message: '草稿 key 不合法' }
      // pr_status.py 的 --check 在平台查询前消费 --expect-sha256：旧令牌直接回 E_CAS 且不写盘。
      argv.push('--check', '--draft', shq(String(payload.key)), '--json', ...casArgs)
    } else if (action === 'mark') {
      if (!validDraftKey(payload.key)) return { ok: false, code: 'E_SCHEMA', message: '草稿 key 不合法' }
      if (!['open', 'merged', 'closed', 'unknown'].includes(String(payload.state || ''))) {
        return { ok: false, code: 'E_SCHEMA', message: 'PR 状态不合法' }
      }
      argv.push('--mark', '--draft', shq(String(payload.key)), '--state', shq(String(payload.state)), ...casArgs)
    } else if (action === 'set-target') {
      const remote = String(payload.remote || '')
      const base = String(payload.base || '')
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/.test(remote)) return { ok: false, code: 'E_SCHEMA', message: 'remote 名不合法' }
      if (!/^[A-Za-z0-9][A-Za-z0-9._/-]{0,120}$/.test(base)) return { ok: false, code: 'E_SCHEMA', message: 'base 分支不合法' }
      argv.push('--set-target', '--remote', shq(remote), '--base', shq(base))
      if (typeof payload.note === 'string' && payload.note) argv.push('--note', shq(payload.note.slice(0, 200)))
      if (payload.labels && typeof payload.labels === 'object') argv.push('--labels', shq(JSON.stringify(payload.labels)))
      argv.push('--json', ...casArgs)
    } else {
      return { ok: false, code: 'E_SCHEMA', message: '未知的 PR 目标动作：' + action }
    }
    return runJsonHelper(root, python, script, argv, 30000, writePolicy)
  }

  function stateFor(sessionId, cwd, refresh) {
    const key = String(sessionId || '') + '\u0000' + String(cwd || '')
    const now = Date.now()
    const cached = cache.get(key)
    if (!refresh && cached !== undefined && now - cached.at < CACHE_TTL_MS) return Promise.resolve(cached.value)
    if (inflight.has(key)) return inflight.get(key)
    const pending = computeState(sessionId, cwd, refresh)
      .then((value) => {
        cache.set(key, { at: Date.now(), value })
        return value
      })
      .finally(() => inflight.delete(key))
    inflight.set(key, pending)
    return pending
  }

  ctx.inject(['webServer'], (webCtx) => {
    webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: CHANNEL,
      handler: async (req, res) => {
        if (req.method !== 'POST') {
          res.setHeader('Allow', 'POST')
          res.writeHead(405)
          res.end()
          return
        }
        const rejection = webCtx.get('connection')?.requestRejection?.(req)
        if (rejection !== undefined) {
          res.writeHead(rejection)
          res.end(rejection === 401 ? 'unauthorized' : 'forbidden')
          return
        }
        const chunks = []
        let received = 0
        for await (const chunk of req) {
          received += chunk.length
          if (received > MAX_BODY_BYTES) {
            res.writeHead(413)
            res.end('payload too large')
            return
          }
          chunks.push(chunk)
        }
        let body
        try {
          body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        } catch {
          res.writeHead(400)
          res.end('body is not JSON')
          return
        }
        const rawPath = new URL(req.url === undefined ? '/' : req.url, 'http://localhost').pathname
        const pathEndpoint = rawPath.startsWith(CHANNEL + '/') ? rawPath.slice(CHANNEL.length + 1) : ''
        const endpoint = pathEndpoint !== '' ? pathEndpoint : (typeof body?.method === 'string' ? body.method : '')
        const payload = body !== undefined && body.payload !== undefined ? body.payload : {}
        let result
        if (endpoint !== 'copilot-state' && endpoint !== 'copilot-transition' && endpoint !== 'copilot-report'
          && endpoint !== 'copilot-timeline' && endpoint !== 'copilot-sediment' && endpoint !== 'copilot-pr-target') {
          result = { ok: false, error: { code: 'not-found', message: '未知的 RPC 端点: ' + endpoint, details: {} } }
        } else {
          try {
            if (endpoint === 'copilot-transition') {
              // 写操作不缓存：每次都是真实一次子进程。
              const value = await applyTransition(payload)
              cache.clear()
              result = { ok: true, value }
            } else if (endpoint === 'copilot-report') {
              result = { ok: true, value: await readReport(payload) }
            } else if (endpoint === 'copilot-timeline') {
              result = { ok: true, value: await readTimeline(payload) }
            } else if (endpoint === 'copilot-sediment') {
              result = {
                ok: true,
                value: await computeSediment(
                  typeof payload.cwd === 'string' ? payload.cwd : '',
                  typeof payload.sessionId === 'string' ? payload.sessionId : '',
                ),
              }
            } else if (endpoint === 'copilot-pr-target') {
              result = { ok: true, value: await prTarget(payload) }
            } else {
              result = {
                ok: true,
                value: await stateFor(
                  typeof payload.sessionId === 'string' ? payload.sessionId : '',
                  typeof payload.cwd === 'string' ? payload.cwd : '',
                  payload.refresh === true,
                ),
              }
            }
          } catch (error) {
            result = {
              ok: false,
              error: { code: 'internal', message: errorText(error), details: {} },
            }
          }
        }
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ type: 'server-response', rpcId: body?.rpcId, result }))
      },
    }), 'dsh-sleuth-copilot: ' + CHANNEL + ' rpc route')
    console.error('[dsh-sleuth-copilot] RPC 路由已注册: ' + CHANNEL)
  })
}
