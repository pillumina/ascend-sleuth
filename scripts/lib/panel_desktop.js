'use strict'

// panel_desktop.js —— 桌面版 DSH 的本地事实：DSH_HOME、当前 profile、dsh 命令行、包登记
//
// 为什么单独一份：`preload-panel` 的现状快检与临时实例验证都要先回答同一组问题，而这三个值
// 都不能靠"默认路径"猜：
//   · DSH_HOME 由宿主决定（桌面版是 <userData>/harness，独立命令行是 ~/.dsh）；
//   · profile 名随发行版变（desktop / web 都见过，桌面版还另有一个 safe-mode）；
//   · dsh 命令行在桌面版里不进 PATH，位置随安装盘与发行版变。
// 这三件事读错一处，后面的登记判断与验证都会对着错目录做。所以集中在这里，两个脚本共用。

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawn, spawnSync } = require('node:child_process')

const REPO = path.resolve(__dirname, '..', '..')

// 默认装的两个包。spec 是仓库内目录，artifacts 是必须存在的产物（缺了说明生成器没跑）。
const PANEL_PACKAGES = [
  {
    name: 'dsh-sleuth-panels',
    spec: 'dsh-plugins/dsh-sleuth-panels',
    artifacts: ['lib/index.js', 'lib/client.js'],
  },
  {
    name: 'dsh-sleuth-vllm-kb',
    spec: 'dsh-plugins/dsh-sleuth-vllm-kb',
    artifacts: ['index.js', 'client.js'],
  },
]

function repoRoot() {
  return REPO
}

function stripBom(text) {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
}

function readText(file) {
  try {
    return fs.readFileSync(file, 'utf8')
  } catch (e) {
    return null
  }
}

function readJson(file) {
  const text = readText(file)
  if (text === null) return null
  try {
    return JSON.parse(stripBom(text))
  } catch (e) {
    return null
  }
}

function isDirectory(target) {
  try {
    return fs.statSync(target).isDirectory()
  } catch (e) {
    return false
  }
}

function unique(list) {
  const seen = new Set()
  return list.filter((item) => {
    if (item === undefined || item === null || item === '' || seen.has(item)) return false
    seen.add(item)
    return true
  })
}

// ── DSH_HOME ─────────────────────────────────────────────────────────────────

// 桌面版把 DSH_HOME 放在 Electron 的 userData 下（如 <userData>/harness）；
// 独立命令行默认 ~/.dsh。DSH 会话内 DSH_HOME 已注入，优先用它。
// Electron 的 userData 目录名随发行版变（产品名）。已知的几种都试，最后才落到独立命令行的 ~/.dsh。
const USERDATA_DIR_NAMES = ['dsh-desktop', 'DSH Desktop', 'DeepSeek Harness', 'DeepSeek Harness Desktop', 'deepseek-harness']

function desktopHomes() {
  const home = os.homedir()
  const bases = []
  if (process.platform === 'win32') {
    if (process.env.APPDATA) bases.push(process.env.APPDATA)
  } else if (process.platform === 'darwin') {
    bases.push(path.join(home, 'Library', 'Application Support'))
  } else {
    bases.push(path.join(home, '.config'))
  }
  const list = []
  for (const base of bases) {
    for (const name of USERDATA_DIR_NAMES) list.push(path.join(base, name, 'harness'))
  }
  return list
}

function dshHomeCandidates() {
  const list = []
  if (process.env.DSH_HOME) list.push(process.env.DSH_HOME)
  list.push(...desktopHomes())
  list.push(path.join(os.homedir(), '.dsh'))
  return unique(list)
}

function resolveDshHome(explicit) {
  const tried = []
  if (explicit) {
    const home = path.resolve(explicit)
    tried.push(home)
    if (isDirectory(path.join(home, 'profiles'))) return { home, source: '命令行', tried }
    return { home: null, source: null, tried }
  }
  for (const home of dshHomeCandidates()) {
    const source = home === process.env.DSH_HOME ? 'DSH_HOME' : '默认位置'
    tried.push(home)
    if (isDirectory(path.join(home, 'profiles'))) return { home, source, tried }
  }
  return { home: null, source: null, tried }
}

// ── 当前 profile ─────────────────────────────────────────────────────────────

// 桌面版把自己的启动信息写进 harness.log：`[desktop] profile <名字>` 与 `[desktop] launch requested (...)`。
// 日志位置随平台变；都找不到时按 profiles 目录猜（只有一份非 safe-mode 时就是它）。
function desktopLogCandidates() {
  const home = os.homedir()
  const list = []
  if (process.platform === 'win32') {
    for (const base of [process.env.APPDATA, process.env.LOCALAPPDATA]) {
      if (!base) continue
      for (const name of [...USERDATA_DIR_NAMES, path.join('@deepseek-ai', 'dsh-desktop')]) {
        list.push(path.join(base, name, 'logs', 'harness.log'))
      }
    }
  } else if (process.platform === 'darwin') {
    const logs = path.join(home, 'Library', 'Logs')
    if (isDirectory(logs)) {
      let names = []
      try {
        names = fs.readdirSync(logs)
      } catch (e) {
        names = []
      }
      for (const name of names) {
        list.push(path.join(logs, name, 'harness.log'))
      }
      // 目录名带 dsh 的优先（产品名随发行版变）
      list.sort((a, b) => Number(/dsh/i.test(path.dirname(b))) - Number(/dsh/i.test(path.dirname(a))))
    }
  } else {
    list.push(path.join(home, '.config', 'dsh-desktop', 'logs', 'harness.log'))
  }
  return unique(list.filter((file) => fs.existsSync(file)))
}

// 日志里同时有 `[desktop] profile web` 和 `[desktop] profile maintenance frozen: ...` 两类行；
// 只认 profiles 目录里真实存在的名字，从最后一条往前找，避免把 "maintenance" 当 profile。
function profileFromLog(home) {
  const names = listProfiles(home)
  for (const log of desktopLogCandidates()) {
    const text = readText(log)
    if (text === null) continue
    const matches = [...text.matchAll(/\[desktop\] profile (\S+)/g)]
    for (let i = matches.length - 1; i >= 0; i -= 1) {
      const name = matches[i][1]
      if (name !== 'desktop-safe-mode' && names.includes(name)) return { profile: name, source: log }
    }
  }
  return null
}

function listProfiles(home) {
  let names = []
  try {
    names = fs.readdirSync(path.join(home, 'profiles'))
  } catch (e) {
    return []
  }
  return names.filter((name) => {
    if (name.startsWith('.') || name === 'node_modules' || name.endsWith('-safe-mode')) return false
    return isDirectory(path.join(home, 'profiles', name))
  })
}

// 与 CLI 的 profile 名校验同一套：名字直接拼进 profiles 目录，带分隔符或不许的名字会指到别处。
function isValidProfileName(name) {
  return typeof name === 'string' && name !== '' && !name.includes('/') && !name.includes('\\')
    && name !== '.' && name !== '..' && name !== 'node_modules'
}

function resolveActiveProfile(home, explicit) {
  if (explicit) return { profile: explicit, source: '命令行', candidates: listProfiles(home) }
  if (isValidProfileName(process.env.DSH_PROFILE)) {
    return { profile: process.env.DSH_PROFILE, source: 'DSH_PROFILE', candidates: listProfiles(home) }
  }
  if (process.env.DSH_PROFILE_DIR && isValidProfileName(path.basename(process.env.DSH_PROFILE_DIR))) {
    return { profile: path.basename(process.env.DSH_PROFILE_DIR), source: 'DSH_PROFILE_DIR', candidates: listProfiles(home) }
  }
  const fromLog = profileFromLog(home)
  if (fromLog !== null) return { profile: fromLog.profile, source: fromLog.source, candidates: listProfiles(home) }
  const candidates = listProfiles(home)
  if (candidates.length === 1) return { profile: candidates[0], source: 'profiles 目录（只有一份）', candidates }
  for (const preferred of ['desktop', 'web', 'dsh-desktop']) {
    if (candidates.includes(preferred)) return { profile: preferred, source: 'profiles 目录（按名字取）', candidates }
  }
  return { profile: null, source: null, candidates }
}

// ── dsh 命令行 ──────────────────────────────────────────────────────────────

const CLI_RELATIVE = path.join('resources', 'runtime', 'cli', 'bin')

function cliFromInstallDir(dir) {
  const base = path.join(dir, CLI_RELATIVE)
  const names = process.platform === 'win32' ? ['dsh.cmd', 'dsh.exe', 'dsh'] : ['dsh']
  for (const name of names) {
    const candidate = path.join(base, name)
    if (fs.existsSync(candidate)) return candidate
  }
  return null
}

function windowsInstallDirs() {
  const dirs = []
  const probe = spawnSync('powershell.exe', [
    '-NoProfile', '-NonInteractive', '-Command',
    "$p = Get-Process | Where-Object { $_.Path -and ($_.ProcessName -like '*DeepSeek*' -or $_.ProcessName -like '*DSH*') } | Select-Object -First 1 -ExpandProperty Path; if ($p) { $p }",
  ], { encoding: 'utf8', timeout: 10000, windowsHide: true })
  const exe = (probe.stdout || '').trim().split(/\r?\n/)[0]
  if (exe && fs.existsSync(exe)) dirs.push(path.dirname(exe))
  if (process.env.LOCALAPPDATA) dirs.push(path.join(process.env.LOCALAPPDATA, 'Programs', 'DeepSeek Harness'))
  for (const base of [process.env.ProgramFiles, process.env['ProgramFiles(x86)']]) {
    if (base) dirs.push(path.join(base, 'DeepSeek Harness'))
  }
  return unique(dirs)
}

// 官方与社区发行版的应用名不同，且可能装到 ~/Applications；扫名字含 dsh / deepseek 的 .app，
// 再兜底已知名字。CLI 是否存在由后续探针判定，不靠应用名认发行版。
function macAppDirs() {
  const home = os.homedir()
  const listed = []
  for (const root of ['/Applications', path.join(home, 'Applications')]) {
    let names = []
    try {
      names = fs.readdirSync(root)
    } catch (e) {
      continue
    }
    for (const name of names) {
      if (!name.endsWith('.app')) continue
      // 用词边界，避免 HandShaker 这类名字里的 dSh 被当成 DSH
      if (!/\b(?:dsh|deepseek)\b/i.test(name.slice(0, -4))) continue
      listed.push(path.join(root, name))
    }
  }
  return unique([
    ...listed,
    '/Applications/DSH Desktop.app',
    '/Applications/DeepSeek Harness.app',
    path.join(home, 'Applications', 'DSH Desktop.app'),
    path.join(home, 'Applications', 'DeepSeek Harness.app'),
  ])
}

function fromPathEnv() {
  const command = process.platform === 'win32' ? 'where' : 'which'
  const names = process.platform === 'win32' ? ['dsh.cmd', 'dsh.exe', 'dsh'] : ['dsh']
  for (const name of names) {
    const result = spawnSync(command, [name], { encoding: 'utf8', timeout: 10000 })
    if (result.status !== 0) continue
    const first = (result.stdout || '').trim().split(/\r?\n/)[0]
    if (first && fs.existsSync(first)) return first
  }
  return null
}

// `--dsh` 也可以指向一个 .js：用当前 node 跑它（自测与开发检出用）。
function normalizeCliFile(raw, source) {
  const file = path.resolve(raw)
  if (!fs.existsSync(file)) return null
  if (/\.(c|m)?js$/i.test(file)) {
    return { command: process.execPath, prefixArgs: [file], label: file, source }
  }
  return { command: file, prefixArgs: [], label: file, source }
}

function resolveDshCli(explicit) {
  const tried = []
  if (explicit) {
    const cli = normalizeCliFile(explicit, '命令行')
    if (cli !== null) return Object.assign(cli, { tried: [explicit] })
    return { command: null, prefixArgs: [], label: null, source: null, tried: [explicit] }
  }
  if (process.env.DSH_CLI) {
    const cli = normalizeCliFile(process.env.DSH_CLI, 'DSH_CLI')
    if (cli !== null) return Object.assign(cli, { tried: [process.env.DSH_CLI] })
  }
  // 安装目录优先于 PATH：桌面版必须用它自己那份 CLI（模块闭包与安装处一致）；机器上另装了
  // 独立 dsh 时，PATH 上那份的闭包可能与桌面 profile 不匹配。没有安装目录 CLI 才落到 PATH。
  const dirs = process.platform === 'win32' ? windowsInstallDirs() : process.platform === 'darwin' ? macAppDirs() : []
  for (const dir of dirs) {
    const candidate = cliFromInstallDir(dir)
    tried.push(path.join(dir, CLI_RELATIVE, process.platform === 'win32' ? 'dsh.cmd' : 'dsh'))
    if (candidate !== null) {
      const cli = normalizeCliFile(candidate, '安装目录')
      if (cli !== null) return Object.assign(cli, { tried })
    }
  }
  const onPath = fromPathEnv()
  tried.push('PATH 上的 dsh')
  if (onPath !== null) {
    const cli = normalizeCliFile(onPath, 'PATH')
    if (cli !== null) return Object.assign(cli, { tried })
  }
  return { command: null, prefixArgs: [], label: null, source: null, tried }
}

// Windows 的 dsh.cmd 是批处理 shim：不经 shell 直接 spawn 会 ENOENT。
function needsShell(cli) {
  return process.platform === 'win32' && /\.(cmd|bat)$/i.test(cli.command)
}

function cliArgs(cli, args) {
  return [...(cli.prefixArgs || []), ...args]
}

// .cmd 的路径可能带空格（Program Files / DeepSeek Harness）：Node 的 shell:true 会把
// 整条命令再包一层引号，命令本身必须先带引号，cmd 去掉外层后才认得这是一个可执行路径。
function shellCommand(cli) {
  return needsShell(cli) ? '"' + cli.command + '"' : cli.command
}

function spawnCli(cli, args, options) {
  return spawn(shellCommand(cli), cliArgs(cli, args), Object.assign({}, options, {
    shell: needsShell(cli) ? true : (options && options.shell),
  }))
}

function spawnCliSync(cli, args, options) {
  return spawnSync(shellCommand(cli), cliArgs(cli, args), Object.assign({}, options, {
    shell: needsShell(cli) ? true : (options && options.shell),
  }))
}

// ── profile 与包登记 ────────────────────────────────────────────────────────

function profileDir(home, profile) {
  return path.join(home, 'profiles', profile)
}

function readProfileManifest(home, profile) {
  const dir = profileDir(home, profile)
  const file = path.join(dir, 'package.json')
  const manifest = readJson(file)
  if (manifest === null) {
    return { dir, file, manifest: null, error: fs.existsSync(file) ? 'package.json 解析失败' : 'package.json 不存在' }
  }
  return { dir, file, manifest, error: null }
}

function packageRegistration(manifest, name) {
  const deps = manifest && manifest.dependencies ? manifest.dependencies : {}
  const overrides = manifest && manifest.pnpm && manifest.pnpm.overrides ? manifest.pnpm.overrides : {}
  const bundles = manifest && manifest.dsh && manifest.dsh.profile && Array.isArray(manifest.dsh.profile.bundles)
    ? manifest.dsh.profile.bundles
    : []
  const plugins = manifest && manifest.dsh && manifest.dsh.desktop && manifest.dsh.desktop.generationProjection
    && manifest.dsh.desktop.generationProjection.plugins
    ? manifest.dsh.desktop.generationProjection.plugins
    : {}
  return {
    dependency: typeof deps[name] === 'string' ? deps[name] : null,
    override: typeof overrides[name] === 'string' ? overrides[name] : null,
    bundle: bundles.includes(name),
    bundles,
    generation: plugins[name] && typeof plugins[name].visibleVersion === 'string' ? plugins[name].visibleVersion : null,
  }
}

function repoPackage(name) {
  const item = PANEL_PACKAGES.find((entry) => entry.name === name)
  if (item === undefined) return null
  const dir = path.join(REPO, item.spec)
  const manifest = readJson(path.join(dir, 'package.json'))
  const version = manifest && typeof manifest.version === 'string' ? manifest.version : null
  const missing = item.artifacts.filter((rel) => !fs.existsSync(path.join(dir, rel)))
  return { name, dir, version, missing }
}

// 安装方式是三种之一：link（路由三）、快照（插件页 / 插件管理器，带 override 或 generationProjection）、
// 未登记。快照的实际加载版本以 generationProjection 或 override 目录名为准。
function installKind(reg) {
  if (reg.dependency === null && reg.generation === null && reg.override === null) return '未登记'
  if (reg.override !== null || reg.generation !== null) return '快照'
  if (reg.dependency !== null && reg.dependency.startsWith('link:')) return 'link'
  return '版本'
}

function packageStatus(home, profile, name) {
  const read = readProfileManifest(home, profile)
  if (read.manifest === null) return { name, error: read.error, dir: read.dir }
  const reg = packageRegistration(read.manifest, name)
  return Object.assign({ name, dir: read.dir, error: null }, reg, {
    kind: installKind(reg),
    installedVersion: reg.generation !== null ? reg.generation : (reg.dependency !== null && !reg.dependency.startsWith('link:') ? reg.dependency : null),
    repo: repoPackage(name),
  })
}

// 读文本里最后一个带 token 的 `dsh web:` 地址（临时实例的 stdout 与桌面版 harness.log 同形）。
function readWebLine(text) {
  const matches = [...text.matchAll(/dsh web:\s*(https?:\/\/[^\s?]+)\/?\?token=([^\s]+)/g)]
  if (matches.length === 0) return null
  const last = matches[matches.length - 1]
  return { base: last[1].replace(/\/$/, ''), token: last[2] }
}

module.exports = {
  PANEL_PACKAGES,
  REPO,
  repoRoot,
  stripBom,
  readJson,
  dshHomeCandidates,
  resolveDshHome,
  desktopLogCandidates,
  resolveActiveProfile,
  isValidProfileName,
  listProfiles,
  resolveDshCli,
  normalizeCliFile,
  needsShell,
  spawnCli,
  spawnCliSync,
  profileDir,
  readProfileManifest,
  packageRegistration,
  packageStatus,
  repoPackage,
  installKind,
  readWebLine,
}
