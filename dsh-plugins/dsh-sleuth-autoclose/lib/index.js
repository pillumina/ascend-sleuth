// dsh-sleuth-autoclose —— profile 级常驻插件：定时跑 groom_sweep。
//
// 边界：
//   - 只调 `scripts/groom_sweep.py`，不自己判断合入、不写 trace、不改知识。
//   - 不注册 tab、不 import Copilot、不改任何其他面板；面板读的是 sweep-log 与状态文件。
//   - DSH 关闭时不跑；手动收尾（Copilot 指令、groom 开场）不受本插件影响。
//   - 连续失败 MAX_FAILURES 次自动暂停，恢复需 `resume` 或显式 `resume: true`（避免每天刷同一错误）。
//   - 上次运行时间与暂停状态写 `.groom/autoclose-state.json`，启动时据此补跑，避免
//     「每天关掉 DSH、每次重启再等 24 小时」导致永远不跑。
//
// 安装即用：
//   - `repo` 不填时按「当前会话的检出 → 插件自身所在检出 → 进程 cwd」顺序自动发现；
//   - `python` 不填时依次探测 python3 / python / py -3；
//   - 默认启用、24 小时、启动补跑一次；用户不需要改配置。
//   - 卸载由 ctx.effect 的清理函数停掉两个定时器；进程不退出也不影响宿主。

import { execFile } from 'node:child_process'
import { access, mkdir, readFile, writeFile } from 'node:fs/promises'
import { basename, dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const MAX_FAILURES = 3
const STATE_FILE = 'autoclose-state.json'
const DEFAULT_MINUTES = 1440
const execFileAsync = promisify(execFile)

function clampMinutes(value) {
  const minutes = Number(value)
  if (!Number.isFinite(minutes) || minutes <= 0) return null
  return Math.max(1, Math.min(10080, Math.round(minutes)))
}

// 状态文件里的小时数是给人看的，必须能还原成分钟：1 分钟不能写成 0。
function hoursOf(minutes) {
  return Math.round((minutes / 60) * 10000) / 10000
}

async function usableFile(path) {
  try {
    await access(path)
    return true
  } catch {
    return false
  }
}

// Python 候选：Windows 上 python3 常是 Store 占位程序，python / py -3 才是真解释器。
// 这是宿主进程里的兜底探测；正式路径在 apply() 里通过 DSH shell 探测，
// 因为宿主能跑的解释器不一定能在沙箱里跑（面板的 resolvePython 同因）。
async function probePythonHost() {
  for (const [cmd, args] of [['python3', []], ['python', []], ['py', ['-3']]]) {
    try {
      const result = await execFileAsync(cmd,
        [...args, '-c', 'import sys, yaml; print(sys.version)'],
        { timeout: 5000, windowsHide: true })
      const text = `${result.stdout || ''}${result.stderr || ''}`
      if (/^3\./m.test(text)) return { cmd, args }
    } catch {
      // 候选不可执行：试下一个。
    }
  }
  return null
}

function infoOfConfigured(value) {
  const parts = String(value || '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return null
  return { cmd: parts[0], args: parts.slice(1) }
}

function commandOf(info) {
  return [info.cmd, ...info.args].join(' ')
}

// 主检出：worktree 的 `.git` 是文件，git-common-dir 指向主检出的 .git；
// 运行时件（inbox / traces）与 git 元数据都在主检出，shell 的写入根也应落在那里。
async function gitCommonRoot(dir) {
  try {
    const result = await execFileAsync('git', ['-C', dir, 'rev-parse', '--git-common-dir'],
      { timeout: 5000, windowsHide: true })
    const common = String(result.stdout || '').trim()
    if (!common) return dir
    const absolute = isAbsolute(common) ? common : resolve(dir, common)
    return basename(absolute) === '.git' ? dirname(absolute) : dir
  } catch {
    return dir
  }
}

async function looksLikeSleuthRoot(dir) {
  if (!dir) return false
  return usableFile(join(dir, 'scripts', 'groom_sweep.py'))
}

export const name = 'dsh-sleuth-autoclose'

export function apply(ctx, config = {}) {
  let repo = String(config.repo || '').trim()
  let repoSource = repo ? 'config' : ''
  let repoSession = null
  let mainRoot = ''
  let pythonInfo = null
  let resumeRequestFlag = false
  let runNowFlag = false
  let firstRunConfirmFlag = false
  let inboxPath = ''
  let statePath = ''
  let configPath = ''
  const timeoutMs = Math.max(60_000, Number(config.timeoutMs) || 600_000)
  let enabled = config.enabled !== false
  const configuredMinutes = clampMinutes(config.intervalMinutes)
  const configuredHours = Number(config.intervalHours)
  let intervalMinutes = configuredMinutes
    || (Number.isFinite(configuredHours) && configuredHours > 0
      ? Math.max(1, Math.min(10080, Math.round(configuredHours * 60)))
      : DEFAULT_MINUTES)

  const state = {
    enabled,
    repo,
    repoSource,
    python: '',
    intervalMinutes,
    intervalHours: hoursOf(intervalMinutes),
    lastRun: '',
    lastOk: null,
    lastSummary: '',
    lastFailure: null,
    failures: 0,
    paused: false,
    nextRun: '',
    needsRun: false,
    firstRunConfirmed: false,
    firstRunPending: false,
    preview: null,
  }

  // 配了 repo 时先放一个同步回退值，让 loadConfig/loadState 在启动微任务之前也能读到；
  // 异步解析到主检出后再换成共享 inbox。
  if (repo) setInbox(join(repo, 'postmortems', 'inbox'))

  function nextFrom(last) {
    const base = last ? Date.parse(last) : NaN
    const from = Number.isFinite(base) ? base : Date.now()
    return new Date(from + intervalMinutes * 60_000).toISOString()
  }

  function setInbox(path) {
    inboxPath = path
    statePath = path ? join(path, '.groom', STATE_FILE) : ''
    configPath = path ? join(path, '.groom', 'autoclose-config.json') : ''
  }

  async function resolveInbox() {
    const root = mainRoot || repo
    if (!root) return false
    // 先放主检出回退值：python 缺失时后续分支仍能读写状态与配置。
    if (!inboxPath) setInbox(join(root, 'postmortems', 'inbox'))
    if (!repo || !pythonInfo) return false
    const script = join(repo, 'scripts', 'shared_dir.py')
    if (!(await usableFile(script))) return false
    try {
      const result = await execFileAsync(pythonInfo.cmd,
        [...pythonInfo.args, script, 'inbox'],
        { cwd: repo, timeout: 15_000, windowsHide: true })
      const lines = String(result.stdout || '').trim().split(/\r?\n/).filter(Boolean)
      const resolved = lines.length ? lines[lines.length - 1].trim() : ''
      if (resolved && resolved !== inboxPath) {
        setInbox(resolved)
        return true
      }
    } catch {
      state.lastSummary = '共享 inbox 解析失败，回退到主检出'
    }
    return false
  }

  // 会话 cwd 最接近用户当前打开的检出；其次才是插件安装目录（link 安装时就是仓库）。
  async function discoverRepo(configured) {
    if (configured) return { repo: configured, source: 'config', session: null }
    const candidates = []
    const sessions = ctx.get('sessions')
    if (sessions && typeof sessions.list === 'function') {
      try {
        for (const session of sessions.list() || []) {
          const cwd = session && (session.header && session.header.cwd
            ? session.header.cwd : session.cwd)
          if (cwd) candidates.push({ path: String(cwd), source: 'session', session })
        }
      } catch {
        // 会话服务不可用时继续用后面的候选。
      }
    }
    try {
      candidates.push({
        path: resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..'),
        source: 'plugin',
      })
    } catch {
      // import.meta.url 解析失败：跳过。
    }
    candidates.push({ path: process.cwd(), source: 'cwd' })
    for (const item of candidates) {
      const main = await gitCommonRoot(item.path)
      if (await looksLikeSleuthRoot(main)) {
        return { repo: main, source: item.source, session: item.session || null }
      }
      if (main !== item.path && await looksLikeSleuthRoot(item.path)) {
        return { repo: item.path, source: item.source, session: item.session || null }
      }
    }
    return { repo: '', source: '', session: null }
  }

  let pythonProbeError = ''

  // 插件是 profile 级，但检出是从某个会话的 cwd 发现的；shell 档位取那个会话的档位，
  // 与面板的 readPolicy(session) 一致。没有会话时才退回部署默认。
  // 硬编码 workspace-write 会让「会话已是完全权限」的机器仍然被沙箱 ACL/完整性挡住。
  function policyFor(session) {
    const service = ctx.get('sandboxPolicy')
    if (!service || typeof service.resolve !== 'function') return null
    try {
      const policy = session ? service.resolve({ session }) : service.resolve()
      if (policy && typeof policy.mode === 'string') {
        if (policy.mode === 'workspace-write' && !policy.workspaceRoot) {
          return { ...policy, workspaceRoot: mainRoot || repo }
        }
        return policy
      }
    } catch {
      // 这个会话解析不了：试下一个。
    }
    return null
  }

  function deploymentPolicy() {
    if (repoSession) {
      const policy = policyFor(repoSession)
      if (policy) return policy
    }
    const sessions = ctx.get('sessions')
    if (sessions && typeof sessions.list === 'function') {
      try {
        for (const session of sessions.list() || []) {
          const cwd = session && (session.header && session.header.cwd
            ? session.header.cwd : session.cwd)
          if (!cwd) continue
          const policy = policyFor(session)
          if (policy) return policy
        }
      } catch {
        // 会话服务不可用：退回部署默认。
      }
    }
    const policy = policyFor(null)
    if (policy) return policy
    return { mode: 'workspace-write', workspaceRoot: mainRoot || repo }
  }

  async function probePython() {
    if (!repo) return null
    const shell = ctx.get('shell')
    const workdir = mainRoot || repo
    if (shell) {
      const policy = deploymentPolicy()
      for (const candidate of ['python3', 'python', 'py -3']) {
        try {
          const request = {
            command: candidate + ' -c "import sys, yaml; print(sys.version)"',
            workdir,
            stdoutMaxBytes: 4096,
            env: { PYTHONIOENCODING: 'utf-8' },
            sandboxPolicy: policy,
          }
          const spec = typeof shell.resolve === 'function' ? shell.resolve(request) : request
          let result
          if (typeof shell.run === 'function') result = await shell.run(spec)
          else if (typeof shell.execute === 'function') {
            const execution = await shell.execute(spec)
            result = typeof execution.result === 'function' ? await execution.result() : execution
          }
          const text = `${result?.stdout?.text || ''}${result?.stderr?.text || ''}`.trim()
          if (result && result.exitCode === 0 && /^3\./m.test(text)) {
            pythonProbeError = ''
            return infoOfConfigured(candidate)
          }
          pythonProbeError = `${candidate} 退出码 ${result?.exitCode}：${text.slice(0, 160) || '（无输出）'}`
        } catch (error) {
          pythonProbeError = `${candidate} 执行失败：${String(error?.message || error).slice(0, 160)}`
        }
      }
      return null
    }
    const host = await probePythonHost()
    if (host) pythonProbeError = ''
    return host
  }

  async function resolveRuntime() {
    let changed = false
    if (!repo && config.discover !== false) {
      const found = await discoverRepo(String(config.repo || '').trim())
      if (found.repo) {
        repo = found.repo
        repoSource = found.source
        repoSession = found.session || null
        state.repo = repo
        state.repoSource = repoSource
        changed = true
      }
    } else if (repo && !repoSource) {
      repoSource = 'config'
      state.repoSource = repoSource
    }
    if (repo && !mainRoot) mainRoot = await gitCommonRoot(repo)
    if (mainRoot && repo && mainRoot !== repo
        && inboxPath === join(repo, 'postmortems', 'inbox')) {
      // 配的是 worktree 时，回退值也要落到主检出的 inbox。
      setInbox(join(mainRoot, 'postmortems', 'inbox'))
      changed = true
    }
    if (!pythonInfo) {
      pythonInfo = infoOfConfigured(config.python) || await probePython()
      if (pythonInfo) {
        state.python = commandOf(pythonInfo)
        changed = true
      }
    }
    if (repo || mainRoot) {
      if (!inboxPath) setInbox(join(mainRoot || repo, 'postmortems', 'inbox'))
      if (repo && pythonInfo && await resolveInbox()) changed = true
    }
    return changed
  }

  async function loadConfig() {
    if (!configPath) return false
    try {
      const doc = JSON.parse(await readFile(configPath, 'utf8'))
      if (!doc || typeof doc !== 'object') return false
      // 只覆盖文件里明确写出的字段：面板只改间隔时，不能把开关一并改成默认开。
      const nextEnabled = typeof doc.enabled === 'boolean' ? doc.enabled : enabled
      const fileMinutes = clampMinutes(doc.intervalMinutes)
      const fileHours = Number(doc.intervalHours)
      const nextMinutes = fileMinutes
        || (Number.isFinite(fileHours) && fileHours > 0
          ? Math.max(1, Math.min(10080, Math.round(fileHours * 60)))
          : intervalMinutes)
      const changed = nextEnabled !== enabled || nextMinutes !== intervalMinutes
      enabled = nextEnabled
      intervalMinutes = nextMinutes
      state.enabled = enabled
      state.intervalMinutes = intervalMinutes
      state.intervalHours = hoursOf(intervalMinutes)
      // 面板的「恢复」写 resume: true；「立即运行一次」写 runNow: true；
      // 首跑确认写 confirmFirstRun: true。都是读过就删的一次性钥匙。
      let flagsChanged = false
      if (doc.resume === true) {
        resumeRequestFlag = true
        state.paused = false
        state.failures = 0
        state.needsRun = true
        delete doc.resume
        flagsChanged = true
      }
      if (doc.runNow === true) {
        runNowFlag = true
        delete doc.runNow
        flagsChanged = true
      }
      if (doc.confirmFirstRun === true) {
        firstRunConfirmFlag = true
        state.firstRunConfirmed = true
        state.firstRunPending = false
        state.preview = null
        state.needsRun = true
        delete doc.confirmFirstRun
        flagsChanged = true
      }
      if (flagsChanged) {
        try {
          await writeFile(configPath, JSON.stringify(doc, null, 2) + '\n')
        } catch {
          // 写不回去就只在内存里生效；下一轮再读到会再执行一次，幂等。
        }
      }
      return changed || resumeRequestFlag || runNowFlag || firstRunConfirmFlag
    } catch {
      // 没有配置文件：沿用插件配置。
      return false
    }
  }

  async function loadState() {
    if (!statePath) return
    try {
      const doc = JSON.parse(await readFile(statePath, 'utf8'))
      if (!doc || typeof doc !== 'object') return
      state.lastRun = String(doc.lastRun || '')
      state.lastOk = doc.lastOk === true ? true : (doc.lastOk === false ? false : null)
      state.lastSummary = String(doc.lastSummary || '')
      state.lastFailure = doc.lastFailure && typeof doc.lastFailure === 'object'
        ? doc.lastFailure : null
      state.failures = Number(doc.failures) || 0
      state.paused = doc.paused === true
      state.needsRun = doc.needsRun === true
      // 老版本状态没有首跑字段：已经跑过（有 lastRun）就按已确认处理，避免升级后
      // 突然把已有部署当成“首次安装”只出预览。新装没有状态文件，才走首跑预览。
      const legacyConfirmed = doc.firstRunConfirmed === undefined && !!doc.lastRun
      state.firstRunConfirmed = doc.firstRunConfirmed === true || legacyConfirmed
      state.firstRunPending = doc.firstRunPending === true
      state.preview = doc.preview && typeof doc.preview === 'object' ? doc.preview : null
      // 停用或暂停时文件里留下的 nextRun 不可信（可能是被暂停前写的），一律清掉。
      state.nextRun = (state.enabled && !state.paused)
        ? String(doc.nextRun || nextFrom(state.lastRun)) : ''
    } catch {
      // 首次运行没有状态文件。
    }
  }

  async function saveState() {
    if (!statePath) return
    // 停用或暂停时不留下次运行时间，否则面板会显示一个永远不会发生的计划。
    // 暂停分支覆盖 sweep 置 paused 后、scheduleNext 清空前退出宿主的竞态窗口。
    state.nextRun = state.enabled && !state.paused
      ? (state.nextRun || nextFrom(state.lastRun)) : ''
    try {
      await mkdir(dirname(statePath), { recursive: true })
      await writeFile(statePath, JSON.stringify(state, null, 2) + '\n', 'utf8')
    } catch {
      // 状态写不了不影响本轮收尾。
    }
  }

  function shellService() {
    return ctx.get('shell')
  }

  async function runShell(command) {
    const shell = shellService()
    if (shell === undefined) throw new Error('shell 服务不可用')
    const request = {
      command,
      // cwd 落在主检出：worktree 检出在沙箱根之外时，cwd 本身可能被拒；
      // `--repo` 仍显式指向要处理的检出，脚本从那里读、写共享 inbox。
      workdir: mainRoot || repo,
      timeoutMs,
      stdoutMaxBytes: 2 * 1024 * 1024,
      env: { PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      // 插件没有会话上下文，必须显式给沙箱策略；写入根用主检出，
      // 让 shared_dir.py 解析出的 inbox / traces 与临时 checkout 都落在可写范围内。
      sandboxPolicy: deploymentPolicy(),
    }
    // 与面板的 shell.run(shell.resolve({...})) 保持同一条通路；直接传裸 spec
    // 在部分 DSH 版本上不会补全请求字段，沙箱与命令都可能没按预期生效。
    const spec = typeof shell.resolve === 'function' ? shell.resolve(request) : request
    if (typeof shell.run === 'function') return shell.run(spec)
    if (typeof shell.execute === 'function') {
      const execution = await shell.execute(spec)
      return typeof execution.result === 'function' ? await execution.result() : execution
    }
    throw new Error('shell 服务既没有 run 也没有 execute')
  }

  function summarize(payload) {
    if (payload.note) return payload.note
    const items = Array.isArray(payload.results) ? payload.results : []
    const closed = items.filter((item) => item.status === 'closed').length
    const missing = items.filter((item) => item.status === 'missing-evidence').length
    const failed = items.filter((item) => item.status === 'failed'
      || item.status === 'cleanup-failed').length
    return `收尾 ${closed} · 缺合入信息 ${missing} · 失败 ${failed}`
  }

  // 失败不是只有一句 JSON 尾巴：优先取具体草稿的 status/reason，其次 cleanup，最后才是
  // shell stdout/stderr。状态里留 lastFailure，面板在 sweep-log 没写成功时也能显示原因。
  function failureOf(payload, result, text) {
    const items = Array.isArray(payload.results) ? payload.results : []
    const failed = items.find((item) => item
      && ['failed', 'cleanup-failed', 'error'].includes(String(item.status || '')))
    if (failed) {
      const drafts = Array.isArray(failed.drafts) && failed.drafts.length
        ? failed.drafts : [failed.draft]
      return {
        draft: String(drafts.find(Boolean) || ''),
        status: String(failed.status || 'failed'),
        reason: String(failed.reason || '').trim() || '收尾未完成',
        merge: String(failed.merge || ''),
        at: state.lastRun,
      }
    }
    const cleanup = payload.cleanup && typeof payload.cleanup === 'object' ? payload.cleanup : null
    if (cleanup && cleanup.ok === false) {
      const findings = Array.isArray(cleanup.findings) ? cleanup.findings : []
      const finding = findings.find((item) => item && item.severity === 'error') || findings[0] || null
      return {
        draft: '',
        status: 'cleanup-failed',
        reason: String(cleanup.error || (finding && finding.message) || '').trim() || '清理未完成',
        merge: '',
        at: state.lastRun,
      }
    }
    const error = payload.error && typeof payload.error === 'object' ? payload.error : {}
    const stderr = String(result?.stderr?.text || '').trim()
      .split(/\r?\n/).filter(Boolean).slice(-1)[0] || ''
    const denied = result?.sandbox && result.sandbox.denied ? '沙箱拒绝：' : ''
    const tail = String(text || '').trim().slice(-300)
    const reason = String(error.message || '').trim() || denied + stderr || tail || '运行未完成'
    return { draft: '', status: 'failed', reason: reason.slice(0, 300), merge: '', at: state.lastRun }
  }

  function failureSummary(failure) {
    const prefix = failure.status === 'cleanup-failed' ? '清理未完成' : '收尾失败'
    return `${prefix}${failure.draft ? `：${failure.draft}` : ''}：${failure.reason}`.slice(0, 320)
  }

  let sweeping = false

  async function sweep(options = {}) {
    if (!enabled) return { ok: false, skipped: true, reason: 'disabled' }
    // 面板的「立即运行一次」可以在暂停状态下强制执行一轮；它不改暂停状态。
    if (state.paused && !options.force) return { ok: false, skipped: true, reason: 'paused' }
    // 改间隔、周期触发、手动调用共用这一道在途保护：同一插件同时只跑一轮 sweep。
    if (sweeping) return { ok: false, skipped: true, reason: 'in-flight' }
    sweeping = true
    // 暂停中的「立即运行一次」只跑这一轮，成功也不能抹掉暂停时的连续失败计数；
    // 清零留给恢复调度/resume。
    const keepPausedCount = state.paused && options.force
    try {
      await resolveRuntime()
      if (!repo) {
        state.lastRun = new Date().toISOString()
        state.lastOk = false
        state.lastSummary = '未找到 ascend-sleuth 检出'
        state.lastFailure = {
          draft: '', status: 'no-repo', reason: state.lastSummary, merge: '', at: state.lastRun,
        }
        state.needsRun = true
        await saveState()
        return { ok: false, skipped: true, reason: 'no-repo' }
      }
      if (!pythonInfo) {
        state.lastRun = new Date().toISOString()
        state.lastOk = false
        state.lastSummary = pythonProbeError
          ? `未找到 Python 3：${pythonProbeError}`
          : '未找到 Python 3'
        state.lastFailure = {
          draft: '', status: 'no-python', reason: state.lastSummary, merge: '', at: state.lastRun,
        }
        state.needsRun = true
        await saveState()
        return { ok: false, skipped: true, reason: 'no-python' }
      }
      state.lastRun = new Date().toISOString()
      let payload = {}
      // 首次安装先 dry-run：只出计划，用户确认后下一次才带 --apply。
      const preview = state.firstRunConfirmed !== true
      try {
        const script = `${repo.replace(/[\\/]+$/, '')}/scripts/groom_sweep.py`
        const command = `${commandOf(pythonInfo)} "${script}" --repo "${repo}" --fetch --source plugin --json`
          + (preview ? '' : ' --apply')
        const result = await runShell(command)
        const text = String(result?.stdout?.text || '')
        try {
          payload = JSON.parse(text)
        } catch {
          payload = {}
        }
        if (preview) {
          const items = Array.isArray(payload.results) ? payload.results : []
          const readyItems = items.filter(item => item && item.status === 'ready')
          const ready = readyItems.map(item => {
            const drafts = Array.isArray(item.drafts) && item.drafts.length
              ? item.drafts : [item.draft]
            return { draft: drafts.find(Boolean) || '', merge: String(item.merge || '') }
          }).filter(item => item.draft)
          state.firstRunPending = true
          state.preview = {
            at: state.lastRun,
            apply: false,
            checked: Number(payload.checked) || 0,
            total: ready.length,
            ready,
            missing: items.filter(item => item && item.status === 'missing-evidence').length,
            already: items.filter(item => item && item.status === 'already-done').length,
          }
          state.lastOk = payload.ok === true
          if (state.lastOk) {
            state.lastFailure = null
            state.lastSummary = ready.length
              ? `首次预览：将处理 ${ready.length} 项，等待确认`
              : '首次预览：没有待处理项，等待确认'
          } else {
            const failure = failureOf(payload, result, text)
            state.lastFailure = failure
            state.lastSummary = failureSummary(failure)
          }
          state.failures = state.lastOk
            ? (keepPausedCount ? state.failures : 0)
            : state.failures + 1
          state.needsRun = false
        } else {
          state.firstRunPending = false
          state.preview = null
          state.firstRunConfirmed = true
          state.lastOk = payload.ok === true
          if (state.lastOk) {
            state.lastSummary = summarize(payload)
            state.lastFailure = null
          } else {
            const failure = failureOf(payload, result, text)
            state.lastFailure = failure
            state.lastSummary = failureSummary(failure)
          }
          state.failures = state.lastOk
            ? (keepPausedCount ? state.failures : 0)
            : state.failures + 1
          state.needsRun = false
        }
      } catch (error) {
        state.lastOk = false
        state.lastFailure = {
          draft: '', status: 'shell-error',
          reason: String(error?.message || error).slice(0, 300), merge: '', at: state.lastRun,
        }
        state.lastSummary = `运行失败：${state.lastFailure.reason}`
        state.failures += 1
        state.needsRun = false
      }
      if (state.failures >= MAX_FAILURES) state.paused = true
      // 周期运行后 nextRun 跟着走，面板不会停在首次计划时间。
      state.nextRun = new Date(Date.now() + intervalMinutes * 60_000).toISOString()
      await saveState()
      return { ok: state.lastOk === true, summary: state.lastSummary, failures: state.failures }
    } finally {
      sweeping = false
    }
  }

  // 恢复：清掉暂停与失败计数，重新安排执行并写回状态文件。
  async function resume() {
    state.paused = false
    state.failures = 0
    state.needsRun = false
    await resolveRuntime()
    scheduleNext()
    await saveState()
    return { paused: false, failures: 0, nextRun: state.nextRun }
  }

  function intervalMsValue() {
    return intervalMinutes * 60_000
  }

  let timer = null
  let timerKind = ''
  let disposed = false

  function clearTimer() {
    if (timer === null) return
    if (timerKind === 'interval') clearInterval(timer)
    else clearTimeout(timer)
    timer = null
    timerKind = ''
  }

  let scheduleToken = 0

  // 首次触发按持久化的上次运行时间算：23 小时前跑过，就在 1 小时后跑，
  // 不是从本次启动重新等 24 小时（否则两次实际相隔约 47 小时）。
  function scheduleNext() {
    clearTimer()
    if (disposed) return
    if (!enabled || state.paused) {
      state.nextRun = ''
      return
    }
    const token = ++scheduleToken
    const last = Date.parse(state.lastRun || '')
    const due = Number.isFinite(last) ? last + intervalMsValue() : Date.now()
    const delay = Math.max(0, due - Date.now())
    state.nextRun = new Date(Date.now() + delay).toISOString()
    timerKind = 'timeout'
    timer = setTimeout(async () => {
      await sweep()
      // 卸载发生在 sweep 进行中时，回调返回后不能再建 interval。
      if (disposed) return
      // 排期已被新的 scheduleNext 替换：旧回调不能再建一个周期定时器。
      if (token !== scheduleToken) return
      // sweep 期间被面板关掉或暂停：不再重建周期定时器。
      if (!enabled || state.paused) {
        state.nextRun = ''
        await saveState()
        return
      }
      timerKind = 'interval'
      timer = setInterval(sweep, intervalMsValue())
      state.nextRun = new Date(Date.now() + intervalMsValue()).toISOString()
      await saveState()
    }, delay)
  }

  // 面板改的是配置文件；插件每 30 秒看一次。repo / python 一开始没解析出来时，
  // 也在这里补发现：用户在启动后打开一个检出，最迟 30 秒就能接上。
  async function configTick() {
    const runtime = await resolveRuntime()
    const changed = await loadConfig()
    // 这三个都是一次性标志；先记住，再消费。
    // 恢复/确认/立即运行都不能等「runtime 刚解析出来」才补跑：暂停通常发生在刚失败之后，
    // 那时 runtime 已经是 false，等的就是 lastRun + 24 小时。
    const resume = resumeRequestFlag
    const runNow = runNowFlag
    const confirm = firstRunConfirmFlag
    if (resumeRequestFlag) resumeRequestFlag = false
    if (runNowFlag) runNowFlag = false
    if (firstRunConfirmFlag) firstRunConfirmFlag = false
    if (disposed) return
    if (resume || runNow || confirm || (runtime && state.needsRun)) {
      await sweep({ force: runNow })
      scheduleNext()
      await saveState()
      return
    }
    if (changed || runtime) {
      scheduleNext()
      await saveState()
    }
  }
  const configTimer = setInterval(configTick, 30_000)

  ctx.effect(() => () => {
    disposed = true
    clearInterval(configTimer)
    clearTimer()
  }, 'dsh-sleuth-autoclose: sweep timer')

  // 启动：先解析检出与解释器，再按上次运行时间安排首次执行。
  queueMicrotask(async () => {
    if (disposed) return
    await resolveRuntime()
    await loadConfig()
    await loadState()
    if (disposed) return
    state.enabled = enabled
    state.repo = repo
    state.repoSource = repoSource
    // `resume` 才是恢复暂停；`runOnStart` 只决定启动后是否立即跑一次。
    const startupRunNow = runNowFlag
    if (runNowFlag) runNowFlag = false
    if (firstRunConfirmFlag) {
      firstRunConfirmFlag = false
      state.firstRunConfirmed = true
      state.firstRunPending = false
      state.preview = null
      state.needsRun = true
    }
    if (config.resume === true || resumeRequestFlag) {
      state.paused = false
      state.failures = 0
      state.needsRun = true
      resumeRequestFlag = false
    }
    if (!enabled) {
      state.nextRun = ''
      await saveState()
      return
    }
    if (state.paused) {
      state.nextRun = ''
      await saveState()
      return
    }
    const last = Date.parse(state.lastRun || '')
    const due = !Number.isFinite(last) || Date.now() >= last + intervalMsValue()
    // runOnStart 是安装/启动补跑；checkOnStart:false 只给测试关掉「到期补跑」。
    if (config.runOnStart === true || state.needsRun || startupRunNow
        || (config.checkOnStart !== false && due)) await sweep({ force: startupRunNow })
    scheduleNext()
    await saveState()
  })

  return { sweep, state, loadState, loadConfig, saveState, resume, scheduleNext, configTick,
           isRunning: () => timer !== null }
}
