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
//
// 退出码：0 = 查完（缺少包、缺少命令行都只是状态，不是错误）；2 = 找不到 DSH_HOME 或定不到
//        profile（这时才需要人指定，别硬猜）。

'use strict'

const fs = require('fs')
const path = require('path')
const { defaultLogPath, readLogTarget } = require('./lib/panel_endpoint')
const {
  PANEL_PACKAGES,
  resolveDshHome,
  resolveActiveProfile,
  resolveDshCli,
  isValidProfileName,
  packageStatus,
  readJson,
} = require('./lib/panel_desktop')

function parseArgs(argv) {
  const args = { json: false, dshHome: null, profile: null, dsh: null, help: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--json') { args.json = true } else if (flag === '--dsh-home') { args.dshHome = value; i += 1 } else if (flag === '--profile') { args.profile = value; i += 1 } else if (flag === '--dsh') { args.dsh = value; i += 1 } else if (flag === '--help' || flag === '-h') { args.help = true }
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
  const logPath = defaultLogPath()
  const webTarget = logPath === null ? null : readLogTarget(logPath)
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
    webTarget: webTarget === null ? null : { base: webTarget.base, source: logPath },
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
  if (cli.command === null) {
    out.push('dsh 命令行 未找到（试过：' + cli.tried.join('、') + '）')
    out.push('          → 路由三走不了；日志里有带 token 的地址就走路由四，否则路由五（插件页粘贴）')
  } else {
    out.push('dsh 命令行 ' + cli.label + '（来源：' + cli.source + '）')
  }
  if (webTarget === null) {
    out.push('日志地址 取不到（日志：' + (logPath === null ? '没找到 harness.log' : logPath) + '）→ 路由四不可用')
  } else {
    out.push('日志地址 ' + webTarget.base + '（日志：' + logPath + '）')
    out.push('          → 日志里有带 token 的地址，路由四可试；先跑 node scripts/panel_rpc_probe.js 确认实例还在')
  }
  out.push('')
  for (const status of packages) out.push(...describePackage(status))
  out.push('')
  out.push('host 半是否已在本会话加载：看会话工具清单里有没有 ascend_trace_status（脚本看不到工具清单）。')
  out.push('选路：有 dsh 命令行 → 路由三；没有但日志里有带 token 的地址 → 路由四；都没有 → 路由五。')
  out.push('快照安装的包用插件页更新，不要用路由三的 link 覆盖。')
  process.stdout.write(out.join('\n') + '\n')
  return 0
}

process.exitCode = main(process.argv.slice(2))
