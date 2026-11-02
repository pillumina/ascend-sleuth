#!/usr/bin/env node
// panel_status.js —— 面板现状一次查清（只读）
//
// 为什么需要它：在跑 preload-panel 的装载路之前，模型要同时知道三件事——DSH_HOME 在哪、当前
// profile 叫什么、两个包登记成什么样。这三件事各有多个可能的默认值（桌面版与命令行的 home 不同、
// profile 名随发行版变、dsh 命令行不在 PATH 上），逐个猜会来回多轮，且很容易对着错目录判断
// "没装"。本脚本把这三件事一次读全，并给出"实际加载的是哪一份、和仓库差在哪"。
//
// 用法：
//   node scripts/panel_status.js                  # 人读输出
//   node scripts/panel_status.js --json           # 机器读（给后续脚本）
//   node scripts/panel_status.js --profile web    # 不自动判 profile
//   node scripts/panel_status.js --dsh-home <dir> # 不自动找 DSH_HOME
//   node scripts/panel_status.js --dsh <path>     # 指定 dsh 命令行（也可传 .js，用当前 node 跑）
//   node scripts/panel_status.js --selftest       # 自带夹具自测本脚本（不需要 DSH）
//
// 退出码：0 = 查完（缺少包、缺少命令行都只是状态，不是错误）；2 = 找不到 DSH_HOME 或定不到
//        profile（这时才需要人指定，别硬猜）。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('node:child_process')
const { defaultLogPath, readLogTarget, sessionBase, sameInstance, foreignLogTargets, logCandidates, describeNoTarget } = require('./lib/panel_endpoint')
const {
  PANEL_PACKAGES,
  resolveDshHome,
  resolveActiveProfile,
  resolveDshCli,
  cliFromInstallDir,
  isValidProfileName,
  packageStatus,
  readJson,
} = require('./lib/panel_desktop')

function parseArgs(argv) {
  const args = { json: false, dshHome: null, profile: null, dsh: null, help: false, selftest: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--json') { args.json = true } else if (flag === '--dsh-home') { args.dshHome = value; i += 1 } else if (flag === '--profile') { args.profile = value; i += 1 } else if (flag === '--dsh') { args.dsh = value; i += 1 } else if (flag === '--selftest') { args.selftest = true } else if (flag === '--help' || flag === '-h') { args.help = true }
  }
  return args
}

function versionFromOverride(spec) {
  if (spec === null) return null
  const matched = /\+v?(\d+\.\d+\.\d+[^+/\\]*)\+/.exec(spec)
  return matched === null ? null : matched[1]
}

function describePackage(status) {
  const lines = []
  if (status.error !== null) {
    lines.push('  ' + status.name + '：读不到 profile 的 package.json（' + status.error + '）')
    return lines
  }
  lines.push('  ' + status.name)
  lines.push('    登记：' + (status.dependency === null ? 'dependencies 里没有' : 'dependencies = ' + status.dependency))
  if (status.override !== null) lines.push('    pnpm.overrides = ' + status.override + '（快照安装实际加载这一份）')
  if (status.generation !== null) lines.push('    generationProjection.visibleVersion = ' + status.generation)
  lines.push('    dsh.profile.bundles：' + (status.bundle ? '有（启动时会加载）' : '没有（只写依赖不会加载）'))
  const repo = status.repo
  if (repo === null) {
    lines.push('    仓库版本：读不到包（' + status.name + '）')
  } else {
    const artifacts = repo.missing.length === 0 ? '产物齐全' : '产物缺 ' + repo.missing.join('、')
    lines.push('    仓库版本：' + (repo.version === null ? '读不到' : repo.version) + '，' + artifacts)
  }
  const installed = status.installedVersion !== null ? status.installedVersion : versionFromOverride(status.override)
  if (status.kind === '未登记') {
    lines.push(status.bundle
      ? '    结论：登记不完整（bundles 里有一项，但 dependencies 与快照记录都没有）'
      : '    结论：未装')
  } else if (!status.bundle) {
    lines.push('    结论：登记不完整（缺 dsh.profile.bundles 一项）')
  } else if (status.kind === 'link') {
    lines.push('    结论：link 安装（路由三），加载的是 ' + status.dependency.slice('link:'.length))
  } else if (status.kind === '快照') {
    lines.push('    结论：快照安装' + (installed === null ? '' : ' ' + installed) + '（插件页 / 插件管理器），实际加载快照那一份')
  } else {
    lines.push('    结论：按版本安装' + (installed === null ? '' : ' ' + installed))
  }
  if (repo !== null && repo.version !== null && installed !== null && installed !== repo.version) {
    lines.push('    与仓库不同：仓库 ' + repo.version + '，实际 ' + installed)
  }
  return lines
}

function main(argv) {
  const args = parseArgs(argv)
  if (args.help === true) {
    process.stdout.write('用法见本文件头部注释。\n')
    return 0
  }

  const home = resolveDshHome(args.dshHome)
  if (home.home === null) {
    process.stderr.write('找不到 DSH_HOME（试过：' + home.tried.join('、') + '）\n')
    process.stderr.write('  传 --dsh-home <目录> 指定；桌面版通常在 <userData>/harness，独立命令行在 ~/.dsh\n')
    return 2
  }
  const active = resolveActiveProfile(home.home, args.profile)
  if (active.profile === null || !isValidProfileName(active.profile)) {
    process.stderr.write('定不到当前 profile（' + home.home + '/profiles 下有：' + (active.candidates.join('、') || '无') + '）\n')
    process.stderr.write('  传 --profile <名字> 指定\n')
    return 2
  }
  const activeDir = path.join(home.home, 'profiles', active.profile)
  let activeDirOk = false
  try {
    activeDirOk = fs.statSync(activeDir).isDirectory()
  } catch (e) {
    activeDirOk = false
  }
  if (!activeDirOk) {
    process.stderr.write('profile ' + active.profile + ' 不存在：' + activeDir + '\n')
    process.stderr.write('  同目录下有的 profile：' + (active.candidates.join('、') || '无') + '；传 --profile <名字> 指定\n')
    return 2
  }

  const cli = resolveDshCli(args.dsh)
  // 桌面版能不能走路由四，看日志里有没有带 token 的 `dsh web:` 行；只报地址，不打印 token。
  // 同一台机器上可能还跑着别的实例，所以只认与本会话地址（DSH_WEB_URL）一致的那份日志。
  const logPath = defaultLogPath()
  const webTarget = logPath === null ? null : readLogTarget(logPath)
  const instanceBase = sessionBase()
  const foreign = foreignLogTargets()
  const packages = PANEL_PACKAGES.map((item) => packageStatus(home.home, active.profile, item.name))
  const profileRead = readJson(path.join(home.home, 'profiles', active.profile, 'package.json'))
  const desktopHint = profileRead !== null && profileRead.dsh !== undefined && profileRead.dsh.desktop !== undefined

  const report = {
    repo: path.resolve(__dirname, '..'),
    dshHome: home.home,
    dshHomeSource: home.source,
    profile: active.profile,
    profileSource: active.source,
    profiles: active.candidates,
    profileDir: activeDir,
    desktopProfile: desktopHint,
    cli,
    sessionBase: instanceBase,
    webTarget: webTarget === null ? null : { base: webTarget.base, source: logPath },
    foreignLogs: foreign,
    packages,
  }

  if (args.json) {
    process.stdout.write(JSON.stringify(report, null, 2) + '\n')
    return 0
  }

  const out = []
  out.push('DSH_HOME  ' + home.home + '（来源：' + home.source + '）')
  out.push('profile   ' + active.profile + '（来源：' + active.source + '；目录 ' + report.profileDir + '）')
  if (active.candidates.length > 1) out.push('          同目录下另有 profile：' + active.candidates.filter((name) => name !== active.profile).join('、'))
  if (typeof active.source === 'string' && /harness\.log$/.test(active.source)) {
    out.push('          （profile 取自日志；机器上有多个实例时可能属于另一个实例，可用 --profile <名字> 指定）')
  }
  const routeThree = cli.command !== null
  if (routeThree) {
    out.push('dsh 命令行 ' + cli.label + '（来源：' + cli.source + '）')
  } else {
    out.push('dsh 命令行 未找到（试过：' + cli.tried.join('、') + '）')
    out.push('          → 路由三走不了')
  }
  if (webTarget === null) {
    out.push('日志地址 取不到')
    for (const line of describeNoTarget({
      webUrl: process.env.DSH_WEB_URL,
      instanceBase,
      candidates: logCandidates(),
      foreign,
    })) out.push('          ' + line)
    const routeFour = foreign.length > 0 ? '路由四不能用于本实例' : '路由四不可用'
    out.push('          → ' + routeFour + '；' + (routeThree ? '用路由三（安装目录自带的命令行）' : '用路由五（插件页粘贴）'))
  } else {
    out.push('日志地址 ' + webTarget.base + '（日志：' + logPath + '）')
    out.push(instanceBase === null
      ? '          → 日志里有带 token 的地址（会话外无法核对归属），路由四可试；先跑 node scripts/panel_rpc_probe.js 确认实例还在'
      : '          → 属于本实例的带 token 地址，路由四可试；先跑 node scripts/panel_rpc_probe.js 确认实例还在')
  }
  out.push('')
  for (const status of packages) out.push(...describePackage(status))
  out.push('')
  out.push('host 半是否已在本会话加载：看会话工具清单里有没有 ascend_trace_status（脚本看不到工具清单）。')
  out.push('选路：有 dsh 命令行 → 路由三；没有但日志里有本实例的带 token 地址 → 路由四；都没有 → 路由五。')
  out.push('快照安装的包用插件页更新，不要用路由三的 link 覆盖。')
  process.stdout.write(out.join('\n') + '\n')
  return 0
}

// 自测：三条判据各走一遍——应用包内的命令行相对位置（期望写成字面量，不用被测函数反推）、
// 日志地址必须属于本会话实例、取不到地址时给的原因与下一步。夹具都在临时目录里，不需要真 DSH。
function selftest() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'panel-status-selftest-'))
  let failures = 0
  const judge = (name, ok) => {
    failures += ok ? 0 : 1
    process.stdout.write('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + name + '\n')
  }
  try {
    const cliName = process.platform === 'win32' ? 'dsh.cmd' : 'dsh'
    const expected = process.platform === 'darwin'
      ? path.join('Contents', 'Resources', 'runtime', 'cli', 'bin')
      : path.join('resources', 'runtime', 'cli', 'bin')
    const app = path.join(base, 'App.app')
    const cliFile = path.join(app, expected, cliName)
    fs.mkdirSync(path.dirname(cliFile), { recursive: true })
    fs.writeFileSync(cliFile, '', 'utf8')
    judge('命令行位置：' + expected + ' 下能找到 dsh', cliFromInstallDir(app) === cliFile)
    if (process.platform === 'darwin') {
      const wrong = path.join(base, 'Wrong.app')
      const wrongFile = path.join(wrong, 'resources', 'runtime', 'cli', 'bin', 'dsh')
      fs.mkdirSync(path.dirname(wrongFile), { recursive: true })
      fs.writeFileSync(wrongFile, '', 'utf8')
      judge('命令行位置：缺 Contents 的路径不当命令行', cliFromInstallDir(wrong) === null)
    }

    // 本机日志（~/Library/Logs、~/.config）不许混进断言：HOME 与 APPDATA 都指向空目录。
    const emptyHome = path.join(base, 'empty-home')
    fs.mkdirSync(emptyHome, { recursive: true })
    const isolated = { HOME: emptyHome, APPDATA: path.join(base, 'empty-appdata') }
    const stage = path.join(base, 'h1')
    const dshHome = path.join(stage, 'home')
    fs.mkdirSync(path.join(dshHome, 'profiles', 'desktop'), { recursive: true })
    fs.writeFileSync(path.join(dshHome, 'profiles', 'desktop', 'package.json'), JSON.stringify({
      name: 'dsh-profile-desktop',
      dsh: { profile: { bundles: [] } },
    }), 'utf8')
    fs.mkdirSync(path.join(stage, 'logs'), { recursive: true })
    const logFile = path.join(stage, 'logs', 'harness.log')
    fs.writeFileSync(logFile, 'dsh web: http://127.0.0.1:41001/?token=selftest-token\n', 'utf8')

    const same = Object.assign({}, isolated, { DSH_HOME: dshHome, DSH_WEB_URL: 'http://127.0.0.1:41001' })
    judge('日志地址：与本会话实例一致时取到', defaultLogPath(same) === logFile)
    const other = Object.assign({}, isolated, { DSH_HOME: dshHome, DSH_WEB_URL: 'http://127.0.0.1:41002' })
    judge('日志地址：属于另一个实例时取不到', defaultLogPath(other) === null)
    judge('日志地址：另一个实例被点名', foreignLogTargets(other).some((one) => one.base === 'http://127.0.0.1:41001'))

    // 非法地址：解析不出实例时不能拿日志去猜
    judge('日志地址：DSH_WEB_URL 非法时不猜', defaultLogPath(Object.assign({}, isolated, { DSH_HOME: dshHome, DSH_WEB_URL: 'http://' })) === null)

    // 取不到地址时的原因：各形状分开说
    const noLogs = describeNoTarget({ webUrl: 'http://127.0.0.1:41002', instanceBase: 'http://127.0.0.1:41002', candidates: [], foreign: [] })
    judge('原因：一份日志都没有时说「没找到 harness.log」', noLogs.some((line) => line.includes('没找到 harness.log')))
    const noLine = describeNoTarget({ webUrl: 'http://127.0.0.1:41002', instanceBase: 'http://127.0.0.1:41002', candidates: [logFile], foreign: [] })
    judge('原因：日志在但没有 dsh web 行分开说', noLine.some((line) => line.includes('没有 `dsh web:` 行')))
    const foreignLines = describeNoTarget({ webUrl: 'http://127.0.0.1:41002', instanceBase: 'http://127.0.0.1:41002', candidates: [logFile], foreign: [{ path: logFile, base: 'http://127.0.0.1:41001' }] })
    judge('原因：别的实例的地址标「不采用」', foreignLines.some((line) => line.includes('不采用')))
    const badUrl = describeNoTarget({ webUrl: 'http://', instanceBase: null, candidates: [logFile], foreign: [], logPath: undefined })
    judge('原因：DSH_WEB_URL 非法时说无法核对归属', badUrl.some((line) => line.includes('不是合法地址')))
    judge('原因：DSH_WEB_URL 非法时不再对日志下结论', badUrl.length === 1)
    const missingLog = path.join(base, 'no-such.log')
    const explicitMissing = describeNoTarget({ webUrl: '', instanceBase: null, logPath: missingLog })
    judge('原因：显式 --log 不存在时说「不存在」', explicitMissing.some((line) => line.includes('不存在')))
    const plainLog = path.join(base, 'plain.log')
    fs.writeFileSync(plainLog, 'booting\n', 'utf8')
    const explicitPlain = describeNoTarget({ webUrl: '', instanceBase: null, logPath: plainLog })
    judge('原因：显式 --log 在但没有 dsh web 行', explicitPlain.some((line) => line.includes('没有 `dsh web:` 行')))
    const explicitBadUrl = describeNoTarget({ webUrl: 'http://', instanceBase: null, logPath: plainLog })
    judge('原因：显式 --log 与非法地址同时出现时两件都说',
      explicitBadUrl.some((line) => line.includes('不是合法地址')) && explicitBadUrl.some((line) => line.includes('没有 `dsh web:` 行')))
    judge('地址归属：回环别名算同一实例', sameInstance('http://localhost:41001', 'http://127.0.0.1:41001'))
    judge('地址归属：端口不同不算同一实例', !sameInstance('http://127.0.0.1:41001', 'http://127.0.0.1:41002'))

    // 回归：显式 --log 的安装脚本不能让「日志里没有 dsh web 行」退化成「没找到 harness.log」
    const installEnv = Object.assign({}, process.env, isolated, { DSH_HOME: dshHome })
    delete installEnv.DSH_WEB_URL
    const installer = spawnSync(process.execPath, [path.join(__dirname, 'panel_install.js'), '--log', plainLog], { encoding: 'utf8', env: installEnv })
    const installText = (installer.stdout || '') + (installer.stderr || '')
    judge('显式 --log：安装脚本报「没有 `dsh web:` 行」而不是「没找到 harness.log」', /没有 `dsh web:` 行/.test(installText) && !/没找到 harness\.log/.test(installText))

    const child = spawnSync(process.execPath, [path.join(__dirname, 'panel_status.js')], {
      encoding: 'utf8',
      env: Object.assign({}, process.env, isolated, { DSH_HOME: dshHome, DSH_PROFILE: 'desktop', DSH_WEB_URL: 'http://127.0.0.1:41002' }),
    })
    const text = (child.stdout || '') + (child.stderr || '')
    judge('人读输出：退出 0', child.status === 0)
    judge('人读输出：报本会话实例与被排除的地址', text.includes('http://127.0.0.1:41002') && text.includes('http://127.0.0.1:41001'))
    judge('人读输出：说明路由四不能用于本实例', /路由四不能用于本实例/.test(text))
    const routeLine = text.split('\n').find((line) => /→ 路由四(不能用于本实例|不可用)/.test(line)) || ''
    judge('人读输出：取不到地址的下一步与有没有命令行一致', !text.includes('路由三走不了') || routeLine.includes('用路由五'))
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
  if (failures > 0) {
    process.stderr.write('现状快检自测未通过：' + failures + ' 例\n')
    return 1
  }
  process.stdout.write('现状快检自测通过（命令行位置 / 日志归属 / 取不到时的原因 / 人读输出）\n')
  return 0
}

function run(argv) {
  const args = parseArgs(argv)
  if (args.selftest) return selftest()
  return main(argv)
}

process.exitCode = run(process.argv.slice(2))
