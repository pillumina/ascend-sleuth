/* eslint-disable */
// dsh-sleuth-copilot —— Host 半：一条 RPC 路由 + 一次受控的 Python 取数。
//
// 读：状态判据在 scripts/_trace_state.py（仓库里唯一的一份），这里不解析 YAML、不判状态。
// 写：状态修改一律经 scripts/trace_transition.py（校验 + CAS + 事件），这里只负责拼参数、
// 判定本会话有没有写权限、把脚本的 JSON 原样交回浏览器半。

import { fileURLToPath } from 'node:url'
import { basename, dirname, join } from 'node:path'
import { readFile, stat, writeFile, unlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const PKG_DIR = dirname(HERE)
const CHANNEL = '/sleuth-copilot'
const MAX_BODY_BYTES = 256 * 1024
// 浏览器半每 10 秒静默刷一次；这个窗口把同一瞬间的重复请求并成一次取数。
const CACHE_TTL_MS = 4000
const PY_TIMEOUT_MS = 20000

export const name = 'dsh-sleuth-copilot'
export const inject = ['connection']

// 解释器只探测一次：Python 3 的启动器在 Windows 上可能是 python3（商店空壳）/ python / py -3。
let pythonCmd

function shq(value) {
  return '"' + String(value).replace(/(["\\$`])/g, '\\$1') + '"'
}

function tailLines(text, limit) {
  return String(text || '').trim().split(/\r?\n/).filter(Boolean).slice(-limit).join('\n')
}

export function apply(ctx) {
  const cache = new Map()
  const inflight = new Map()

  ctx.effect(() => () => {
    cache.clear()
    inflight.clear()
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

  // 上游查证依赖 gh CLI 与登录态（doctor 的 gh 检查同一件事）。探一次缓存 5 分钟：
  // 状态 RPC 每 10 秒轮询，不能每次都起两个子进程。
  let upstreamCache = { at: 0, value: null, inflight: null }
  async function upstreamReadiness(root) {
    const now = Date.now()
    if (upstreamCache.value && now - upstreamCache.at < 5 * 60 * 1000) return upstreamCache.value
    if (upstreamCache.inflight) return upstreamCache.inflight
    const pending = (async () => {
      let value = { ready: false, reason: '未检测到 gh CLI' }
      try {
        const version = await runShell(resolveSpec({
          command: 'gh --version', workdir: root, timeoutMs: 4000, stdoutMaxBytes: 4096,
        }))
        if (!version || version.exitCode !== 0) {
          value = { ready: false, reason: '未安装 gh CLI（查上游 issue / PR 需要它）' }
        } else {
          const auth = await runShell(resolveSpec({
            command: 'gh auth status', workdir: root, timeoutMs: 6000, stdoutMaxBytes: 8192,
          }))
          value = auth && auth.exitCode === 0
            ? { ready: true, reason: '' }
            : { ready: false, reason: 'gh 未登录（gh auth login）' }
        }
      } catch (error) {
        value = { ready: false, reason: '环境检测失败：' + String((error && error.message) || error) }
      }
      upstreamCache = { at: Date.now(), value, inflight: null }
      return value
    })()
    upstreamCache.inflight = pending
    return pending
  }

  async function resolvePython(workdir) {
    if (pythonCmd !== undefined) return pythonCmd
    for (const candidate of ['python3', 'python', 'py -3']) {
      try {
        const result = await runShell(resolveSpec({
          command: candidate + ' --version',
          workdir,
          stdoutMaxBytes: 4096,
        }))
        const output = [result?.stdout?.text, result?.stderr?.text]
          .filter((text) => typeof text === 'string')
          .join('\n')
        if (result && result.exitCode === 0 && /Python 3\./.test(output)) {
          pythonCmd = candidate
          return candidate
        }
      } catch {
        // 候选不可执行就试下一个；失败不进缓存，环境修好后下一次自愈。
      }
    }
    return null
  }

  // 本会话的沙箱档位：只读档位下不发起任何写入。服务缺失时按「未限制」处理，与面板一致。
  async function resolvePolicy(sessionId) {
    try {
      const policySvc = ctx.get('sandboxPolicy')
      if (policySvc === undefined || typeof policySvc.resolve !== 'function') return undefined
      const sessions = ctx.get('sessions')
      let session = null
      try {
        session = sessions && typeof sessions.get === 'function' && sessionId ? sessions.get(sessionId) : null
      } catch {
        session = null
      }
      const policy = session ? policySvc.resolve({ session }) : policySvc.resolve()
      return policy && typeof policy.mode === 'string' ? policy : undefined
    } catch {
      return undefined
    }
  }

  async function canWriteIn(sessionId) {
    const policy = await resolvePolicy(sessionId)
    return !(policy && policy.mode === 'read-only')
  }

  // 只在这个会话的工作区确实是 ascend-sleuth 检出时才显示状态条：别的项目的会话里不该
  // 出现一条读全库诊断的记录带。拿不到会话工作区（cwd 为空）时也隐藏，不从包所在位置猜——
  // link 安装时包就在仓库里，按包目录回退会让没有 cwd 的会话也显示出来。
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

  async function computeState(sessionId, cwd) {
    const root = await resolveRepoRoot(cwd)
    if (root === null) {
      return {
        ok: false,
        code: 'E_NO_ROOT',
        message: '当前会话的工作区不是 ascend-sleuth 检出（找不到 scripts/_trace_state.py），状态条不显示。',
        cwd: typeof cwd === 'string' ? cwd : '',
      }
    }
    const python = await resolvePython(root)
    if (python === null) {
      return {
        ok: false,
        code: 'E_NO_PYTHON',
        message: '没找到可用的 Python 3（已试 python3 / python / py -3）——数据面是 '
          + 'scripts/trace_state.py，装好 Python 3 并确保在 PATH 里，然后点刷新。',
        repoRoot: root,
      }
    }
    const script = join(PKG_DIR, 'lib', 'copilot_state.py')
    if (!(await isFile(script))) {
      return { ok: false, code: 'E_NO_HELPER', message: '装进来的包缺少 lib/copilot_state.py：' + script }
    }
    const canWrite = await canWriteIn(sessionId)
    const argv = [python, shq(script), '--root', shq(root)]
    if (typeof sessionId === 'string' && sessionId) argv.push('--session', shq(sessionId))
    if (canWrite) argv.push('--can-write', '--write-root', shq(root))

    let result
    try {
      result = await runShell(resolveSpec({
        command: argv.join(' '),
        workdir: root,
        timeoutMs: PY_TIMEOUT_MS,
        stdoutMaxBytes: 1024 * 1024,
        env: { PYTHONIOENCODING: 'utf-8' },
      }))
    } catch (error) {
      return {
        ok: false,
        code: 'E_SPAWN',
        message: '数据脚本执行失败：' + String(error && error.message ? error.message : error),
        repoRoot: root,
      }
    }

    const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
    const stderr = result && result.stderr && typeof result.stderr.text === 'string' ? result.stderr.text : ''
    if (result && result.timedOut) {
      return { ok: false, code: 'E_TIMEOUT', message: '数据脚本超时（20s）——traces/ 很大时可能偏慢。', repoRoot: root }
    }
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
        message: '数据脚本输出不是合法 JSON：' + String(error && error.message ? error.message : error),
        repoRoot: root,
      }
    }
    if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) {
      return { ok: false, code: 'E_SHAPE', message: '数据脚本输出不是对象。', repoRoot: root }
    }
    doc.repoRoot = root
    doc.upstream = await upstreamReadiness(root)
    return doc
  }

  function transitionFailure(code, message) {
    return { ok: false, code, message }
  }

  function validTraceId(value) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/.test(String(value || ''))
  }

  // traces 目录由浏览器半从状态里带回来（主检出那份）。只接受绝对路径且末级目录叫 traces，
  // 用于两处：写状态的沙箱根、读人读报告的文件目录。
  async function normalizeTracesDir(payload) {
    if (typeof payload.tracesDir !== 'string' || !payload.tracesDir) return ''
    const candidate = payload.tracesDir
    if (!candidate.startsWith('/') && !/^[A-Za-z]:[\\/]/.test(candidate)) return ''
    try {
      if ((await stat(join(candidate, '.'))).isDirectory() && basename(candidate) === 'traces') return candidate
    } catch {
      // 目录不在就退回调用的默认解析
    }
    return ''
  }

  // 读人读报告：只读、限大小，路径由「检出根 + traces/<id>.report.md」拼出，单号先过白名单。
  const MAX_REPORT_BYTES = 512 * 1024
  async function readReport(payload) {
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const traceId = String(payload.traceSessionId || '')
    if (!validTraceId(traceId)) return { ok: false, code: 'E_SCHEMA', message: '诊断单号不合法' }
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const tracesDir = (await normalizeTracesDir(payload)) || join(root, 'traces')
    // 状态里带回的报告位置（顶层 report_file 优先）；只接受 traces/ 下的一层文件名。
    let name = traceId + '.report.md'
    const requested = typeof payload.reportFile === 'string' ? payload.reportFile.trim() : ''
    if (requested) {
      const normalized = requested.replace(/\\/g, '/').replace(/^\.\//, '')
      const stripped = normalized.replace(/^traces\//, '')
      if (!stripped || stripped.indexOf('..') >= 0 || /[\\/]/.test(stripped)) {
        return { ok: false, code: 'E_SCHEMA', message: '报告文件名不合法' }
      }
      name = stripped
    }
    const file = join(tracesDir, name)
    try {
      const info = await stat(file)
      if (!info.isFile()) return { ok: false, code: 'E_NOT_FOUND', message: '这单还没有人读报告' }
      if (info.size > MAX_REPORT_BYTES) {
        return { ok: false, code: 'E_TOO_LARGE', message: '报告超过 512 KiB，请在编辑器里看 traces/' + traceId + '.report.md' }
      }
      const text = await readFile(file, 'utf8')
      return { ok: true, text, file: 'traces/' + name, bytes: info.size }
    } catch {
      return { ok: false, code: 'E_NOT_FOUND', message: '这单还没有人读报告' }
    }
  }

  // 单条轨迹的步骤时间线：只读、懒加载；Python 侧只摘录已有事件。
  async function readTimeline(payload) {
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const traceFile = String(payload.traceFile || '')
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.yaml$/.test(traceFile)) {
      return { ok: false, code: 'E_SCHEMA', message: '轨迹文件名不合法' }
    }
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const python = await resolvePython(root)
    if (python === null) return { ok: false, code: 'E_NO_PYTHON', message: '没找到可用的 Python 3' }
    const script = join(PKG_DIR, 'lib', 'copilot_state.py')
    if (!(await isFile(script))) return { ok: false, code: 'E_NO_HELPER', message: '装进来的包缺少 lib/copilot_state.py' }
    const tracesDir = await normalizeTracesDir(payload)
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
      }))
    } catch (error) {
      return { ok: false, code: 'E_SPAWN', message: '数据脚本执行失败：' + String((error && error.message) || error) }
    }
    const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
    const trimmed = stdout.trim()
    if (result && result.timedOut) return { ok: false, code: 'E_TIMEOUT', message: '读步骤时间线超时。' }
    if (!trimmed.startsWith('{')) return { ok: false, code: 'E_OUTPUT', message: '数据脚本没有产出 JSON（exit ' + String(result ? result.exitCode : '?') + '）' }
    try {
      return JSON.parse(trimmed)
    } catch (error) {
      return { ok: false, code: 'E_JSON', message: '数据脚本输出不是合法 JSON：' + String((error && error.message) || error) }
    }
  }

  // 状态写入。参数走临时 JSON 文件（summary / handed_to 常含空格、引号与中文，拼命令行会被改写），
  // 与面板同一条路径；脚本自己删除参数文件，这里再兜底清一次。
  async function applyTransition(payload) {
    const sessionId = typeof payload.sessionId === 'string' ? payload.sessionId : ''
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const traceId = String(payload.traceSessionId || '')
    const expectSha = String(payload.expectSha256 || '')
    const kind = String(payload.kind || '')
    if (!validTraceId(traceId)) return transitionFailure('E_SCHEMA', '诊断单号不合法')
    if (!/^[0-9a-f]{64}$/.test(expectSha)) {
      return transitionFailure('E_SCHEMA', '缺内容指纹，请刷新列表后重试')
    }
    if (!(await canWriteIn(sessionId))) {
      return transitionFailure('E_PERM', '当前会话是只读档位，改不了状态')
    }
    const root = await resolveRepoRoot(cwd)
    if (root === null) return transitionFailure('E_NO_ROOT', '当前工作区不是 ascend-sleuth 检出')
    const python = await resolvePython(root)
    if (python === null) return transitionFailure('E_NO_PYTHON', '没找到可用的 Python 3')

    // 写调用的沙箱根取 traces 的父目录（主检出），这样在 worktree 里开的会话也能写到锚在主检出的 traces/。
    const tracesDir = await normalizeTracesDir(payload)
    const writeRoot = tracesDir ? dirname(tracesDir) : root

    const body = {}
    const extraArgs = []
    if (kind === 'sedimented') {
      const state = String(payload.state || '')
      if (!/^(none|submitted|knowledge|archived)$/.test(state)) {
        return transitionFailure('E_SCHEMA', '沉淀状态不在词表里')
      }
      extraArgs.push('--field', 'sedimented', '--state', state)
      if (payload.caseId) extraArgs.push('--case-id', shq(String(payload.caseId)))
      if (payload.inboxPath) extraArgs.push('--inbox-path', shq(String(payload.inboxPath)))
    } else if (kind === 'reopen') {
      body.reopen = true
    } else if (kind === 'close') {
      const to = String(payload.to || '')
      if (!/^(resolved|escalated|archived)$/.test(to)) return transitionFailure('E_SCHEMA', '目标状态不合法')
      body.to = to
      if (payload.endingKind) body.kind = String(payload.endingKind)
      if (payload.handedTo) body.handed_to = String(payload.handedTo)
      if (payload.duplicateOf) body.duplicate_of = String(payload.duplicateOf)
      for (const key of ['summary', 'severity', 'fix_emitted']) {
        if (payload[key] !== undefined && payload[key] !== null) body[key] = payload[key]
      }
    } else {
      return transitionFailure('E_SCHEMA', '未知的写入类型：' + kind)
    }

    const payloadFile = join(tmpdir(), 'sleuth-copilot-' + process.pid + '-' + Date.now() + '-'
      + Math.random().toString(36).slice(2, 8) + '.json')
    try {
      await writeFile(payloadFile, JSON.stringify(body), 'utf8')
    } catch (error) {
      return transitionFailure('E_IO', '写参数文件失败：' + String((error && error.message) || error))
    }

    const script = join(root, 'scripts', 'trace_transition.py')
    const argv = [python, shq(script), shq(traceId),
      '--root', shq(root), '--by', 'user', '--source', 'panel', '--json',
      '--expect-sha256', shq(expectSha), ...extraArgs,
      '--payload-file', shq(payloadFile)]
    if (tracesDir) argv.push('--traces', shq(tracesDir))
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
      await unlink(payloadFile).catch(() => {})
      return transitionFailure('E_IO', '写状态脚本执行失败：' + String((error && error.message) || error))
    }
    await unlink(payloadFile).catch(() => {})

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
  }

  // ── 沉淀队列与提 PR 目标：按需读取，不进 10 秒轮询 ─────────────────────
  async function runJsonHelper(root, python, script, args, timeoutMs) {
    let result
    try {
      result = await runShell(resolveSpec({
        command: [python, shq(script), ...args].join(' '),
        workdir: root,
        timeoutMs,
        stdoutMaxBytes: 2 * 1024 * 1024,
        env: { PYTHONIOENCODING: 'utf-8' },
      }))
    } catch (error) {
      return { ok: false, code: 'E_SPAWN', message: '数据脚本执行失败：' + String((error && error.message) || error) }
    }
    const stdout = result && result.stdout && typeof result.stdout.text === 'string' ? result.stdout.text : ''
    const stderr = result && result.stderr && typeof result.stderr.text === 'string' ? result.stderr.text : ''
    if (result && result.timedOut) return { ok: false, code: 'E_TIMEOUT', message: '数据脚本超时。' }
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
      return { ok: false, code: 'E_JSON', message: '脚本输出不是合法 JSON：' + String((error && error.message) || error) }
    }
  }

  async function computeSediment(cwd) {
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const python = await resolvePython(root)
    if (python === null) return { ok: false, code: 'E_NO_PYTHON', message: '没找到可用的 Python 3' }
    const script = join(PKG_DIR, 'lib', 'sediment_state.py')
    if (!(await isFile(script))) return { ok: false, code: 'E_NO_HELPER', message: '装进来的包缺少 lib/sediment_state.py' }
    const args = ['--root', shq(root), '--json']
    const doc = await runJsonHelper(root, python, script, args, 30000)
    doc.repoRoot = root
    return doc
  }

  function validDraftKey(value) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$/.test(String(value || ''))
  }

  async function prTarget(payload) {
    const cwd = typeof payload.cwd === 'string' ? payload.cwd : ''
    const root = await resolveRepoRoot(cwd)
    if (root === null) return { ok: false, code: 'E_NO_ROOT', message: '当前工作区不是 ascend-sleuth 检出' }
    const python = await resolvePython(root)
    if (python === null) return { ok: false, code: 'E_NO_PYTHON', message: '没找到可用的 Python 3' }
    const script = join(root, 'scripts', 'pr_status.py')
    if (!(await isFile(script))) return { ok: false, code: 'E_NO_HELPER', message: '检出里缺少 scripts/pr_status.py' }
    const action = String(payload.action || 'list')
    const argv = ['--root', shq(root)]
    if (action === 'list') {
      argv.push('--list-targets', '--json')
    } else if (action === 'check') {
      if (!validDraftKey(payload.key)) return { ok: false, code: 'E_SCHEMA', message: '草稿 key 不合法' }
      if (!(await canWriteIn(payload.sessionId))) return { ok: false, code: 'E_PERM', message: '当前会话是只读档位，不能更新 PR 台账' }
      argv.push('--check', '--draft', shq(String(payload.key)), '--json')
    } else if (action === 'mark') {
      if (!validDraftKey(payload.key)) return { ok: false, code: 'E_SCHEMA', message: '草稿 key 不合法' }
      if (!['open', 'merged', 'closed', 'unknown'].includes(String(payload.state || ''))) {
        return { ok: false, code: 'E_SCHEMA', message: 'PR 状态不合法' }
      }
      if (!(await canWriteIn(payload.sessionId))) return { ok: false, code: 'E_PERM', message: '当前会话是只读档位，不能更新 PR 台账' }
      argv.push('--mark', '--draft', shq(String(payload.key)), '--state', shq(String(payload.state)))
    } else if (action === 'set-target') {
      const remote = String(payload.remote || '')
      const base = String(payload.base || '')
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/.test(remote)) return { ok: false, code: 'E_SCHEMA', message: 'remote 名不合法' }
      if (!/^[A-Za-z0-9][A-Za-z0-9._/-]{0,120}$/.test(base)) return { ok: false, code: 'E_SCHEMA', message: 'base 分支不合法' }
      if (!(await canWriteIn(payload.sessionId))) return { ok: false, code: 'E_PERM', message: '当前会话是只读档位，不能保存 PR 目标' }
      argv.push('--set-target', '--remote', shq(remote), '--base', shq(base))
      if (typeof payload.note === 'string' && payload.note) argv.push('--note', shq(payload.note.slice(0, 200)))
      if (payload.labels && typeof payload.labels === 'object') argv.push('--labels', shq(JSON.stringify(payload.labels)))
      argv.push('--json')
    } else {
      return { ok: false, code: 'E_SCHEMA', message: '未知的 PR 目标动作：' + action }
    }
    return runJsonHelper(root, python, script, argv, 30000)
  }

  function stateFor(sessionId, cwd, refresh) {
    const key = String(sessionId || '') + '\u0000' + String(cwd || '')
    const now = Date.now()
    const cached = cache.get(key)
    if (!refresh && cached !== undefined && now - cached.at < CACHE_TTL_MS) return Promise.resolve(cached.value)
    if (inflight.has(key)) return inflight.get(key)
    const pending = computeState(sessionId, cwd)
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
                value: await computeSediment(typeof payload.cwd === 'string' ? payload.cwd : ''),
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
              error: { code: 'internal', message: String((error && error.message) || error), details: {} },
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
