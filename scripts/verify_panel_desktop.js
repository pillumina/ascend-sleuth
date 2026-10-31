#!/usr/bin/env node
// verify_panel_desktop.js —— 桌面版的"无 token 验证"：临时 profile + 临时实例，一条命令跑完
//
// 为什么需要它：桌面版不一定把 `dsh web:` 地址与 token 交给磁盘（Windows 上尤其如此），
// `panel_install.js` 与 `panel_rpc_probe.js` 取不到地址，就没法判面板 host 半到底挂没挂。
// 办法是在系统临时目录建一个临时 DSH_HOME，复制一份 profile 到临时名字，用安装目录自带的 dsh
// 起一个只为验证的实例：它自己打印带 token 的地址，跑完就停。整个过程有十来步，手工做要来回
// 粘贴很多轮，且有两个坑：
//
//   · 临时 profile 的目录名必须与 --profile 参数完全一致。CLI 按名字到
//     <DSH_HOME>/profiles/<名字>/ 找目录，名字差一个字就报 `profile "xxx" does not exist`；
//   · 改 package.json 的 name 要用无 BOM 的 UTF-8 写回。Windows PowerShell 的
//     Set-Content -Encoding UTF8 会写 BOM，JSON.parse 直接报 Unexpected token。
//
// 本脚本把这两个坑封在实现里，人只需要跑一条命令。
//
// 用法：
//   node scripts/verify_panel_desktop.js                     # 自动找 DSH_HOME / profile / dsh
//   node scripts/verify_panel_desktop.js --profile web       # 指定 profile
//   node scripts/verify_panel_desktop.js --dsh <路径>        # 指定 dsh（也可传 .js，用当前 node 跑）
//   node scripts/verify_panel_desktop.js --dsh-home <目录>   # 指定 DSH_HOME
//   node scripts/verify_panel_desktop.js --timeout 180       # 等实例启动的秒数（默认 120）
//   node scripts/verify_panel_desktop.js --keep              # 保留临时 DSH_HOME 现场（排查用）
//   node scripts/verify_panel_desktop.js --full              # 临时 profile 用配置层完整副本（复现与其它插件的交互）
//   node scripts/verify_panel_desktop.js --selftest          # 自带假 dsh 自测本脚本（不需要 DSH）
//
// 临时 profile 默认是最小组合（base + web-app + 已登记的包，profile 级与 home 级 patch 都置空）：
// 它只验证"这个包在当前安装里能不能加载、RPC 与页面在不在"，不会把 profile 里其它插件的全局锁 /
// 端口 / 状态带进来（同机再起一个实例时，那些插件会互相抢锁，整棵树的启动会被它们拖死）。要复现
// "与其它插件同场"的问题加 --full，用配置层完整副本（仍只复制配置文件，不复制 node_modules，只做
// 联接）。临时 DSH_HOME 建在系统临时目录，验证实例的日志、缓存、sessions 都落在那里，跑完整个删掉。
//
// 判据（全部满足才 0）：
//   0. 已登记的包都进了 dsh.profile.bundles（只写依赖没进 bundles 的，启动不会加载，算失败）；
//   1. profile 里至少登记了面板包或 vllm-kb 其中一个；
//   2. `dsh --profile <临时名> --dump-config` 退出 0，且每个已登记的包都有一段 `# == <包名>`；
//   3. 临时实例打印 `dsh web:` 地址；
//   4. 页面清单里有每个已登记包的 `<包名>/client.js`；
//   5. 面板包已登记时，`ascend-traces-list` 这条 RPC 回 result.ok=true。
//
// 退出码：0 = 全通；1 = 有一条判据失败（输出里点名是哪一步，含"依赖有、bundles 没有"的登记
//        不完整）；2 = 前置缺失（找不到 DSH_HOME、profile、dsh 命令行，profile 不是 web 形态
//        （--full 跳过这条），或 profile 里两个包都没登记）——这时转路由四/五，不要反复试。

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')
const {
  PANEL_PACKAGES,
  resolveDshHome,
  resolveActiveProfile,
  resolveDshCli,
  isValidProfileName,
  spawnCli,
  spawnCliSync,
  readProfileManifest,
  packageRegistration,
  readWebLine,
  stripBom,
} = require('./lib/panel_desktop')
const { sessionCookie, rpcCall } = require('./lib/panel_endpoint')

const COPY_FILES = ['package.json', 'cordis.patch.yml', 'cordis.yml', 'pnpm-workspace.yaml', '.npmrc']
const RPC_CHANNEL = '/ascend-sleuth-panels'
const RPC_ENDPOINT = 'ascend-traces-list'
const PANEL_NAME = 'dsh-sleuth-panels'

function parseArgs(argv) {
  const args = { profile: null, dsh: null, dshHome: null, timeout: 120, keep: false, full: false, selftest: false, help: false, quiet: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--profile') { args.profile = value; i += 1 } else if (flag === '--dsh') { args.dsh = value; i += 1 } else if (flag === '--dsh-home') { args.dshHome = value; i += 1 } else if (flag === '--timeout') { args.timeout = Number(value); i += 1 } else if (flag === '--keep') { args.keep = true } else if (flag === '--full') { args.full = true } else if (flag === '--selftest') { args.selftest = true } else if (flag === '--quiet') { args.quiet = true } else if (flag === '--help' || flag === '-h') { args.help = true }
  }
  return args
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)
}

function makeIo(quiet) {
  return {
    say: quiet ? () => {} : (line) => process.stdout.write(line + '\n'),
    warn: quiet ? () => {} : (line) => process.stderr.write(line + '\n'),
  }
}

function tempProfileName() {
  return 'panel-verify-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8)
}

// 在系统临时目录建一个临时 DSH_HOME，把源 profile 复制成里面的临时 profile。package.json 的
// name 必须与目录名一致（CLI 按名字找目录）；写回用 fs.writeFileSync 的默认 UTF-8（无 BOM），
// BOM 在读取时先剥掉。
//
// 默认写最小组合：只留 base + web-app + 已登记的包，profile 级与 home 级 patch 都置空。目的是一次
// 只验证一个包能不能在当前安装里加载。--full 时按原 profile 的配置层完整复制（含用户 patch 层与
// 全部 bundles），用来复现"与其它插件同场"的问题；代价是其它插件的全局锁与端口会让第二个实例起不来。
function copyProfile(home, profile, expected, full) {
  const source = path.join(home, 'profiles', profile)
  const sourceManifest = JSON.parse(stripBom(fs.readFileSync(path.join(source, 'package.json'), 'utf8')))
  const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-panel-verify-'))
  try {
    const name = tempProfileName()
    const target = path.join(tempHome, 'profiles', name)
    fs.mkdirSync(target, { recursive: true })

    // 设置文件不是 profile 的一部分，但 web app 启动会读它；复制一份，别把模型的默认配置丢掉。
    const settings = path.join(home, 'settings.yaml')
    if (fs.existsSync(settings)) fs.copyFileSync(settings, path.join(tempHome, 'settings.yaml'))

    if (full) {
      for (const file of COPY_FILES) {
        const from = path.join(source, file)
        if (!fs.existsSync(from)) continue
        const to = path.join(target, file)
        if (file === 'package.json') {
          sourceManifest.name = 'dsh-profile-' + name
          fs.writeFileSync(to, JSON.stringify(sourceManifest, null, 2) + '\n', 'utf8')
        } else {
          fs.writeFileSync(to, stripBom(fs.readFileSync(from, 'utf8')), 'utf8')
        }
      }
      const homePatch = path.join(home, 'cordis.patch.yml')
      if (fs.existsSync(homePatch)) fs.writeFileSync(path.join(tempHome, 'cordis.patch.yml'), stripBom(fs.readFileSync(homePatch, 'utf8')), 'utf8')
    } else {
      const sourceBundles = sourceManifest.dsh && sourceManifest.dsh.profile && Array.isArray(sourceManifest.dsh.profile.bundles)
        ? sourceManifest.dsh.profile.bundles
        : []
      const baseBundles = sourceBundles.filter((item) => item === '@deepseek-ai/dsh-base' || item === '@deepseek-ai/dsh-web-app')
      const bundles = []
      for (const item of [...baseBundles, ...expected]) {
        if (!bundles.includes(item)) bundles.push(item)
      }
      const manifest = {
        name: 'dsh-profile-' + name,
        private: true,
        dependencies: sourceManifest.dependencies || {},
        dsh: { profile: { bundles, patchReload: 'startup' } },
      }
      fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8')
      fs.writeFileSync(path.join(target, 'cordis.patch.yml'), '[]\n', 'utf8')
      fs.writeFileSync(path.join(target, 'cordis.yml'), '[]\n', 'utf8')
      const workspace = path.join(source, 'pnpm-workspace.yaml')
      if (fs.existsSync(workspace)) fs.writeFileSync(path.join(target, 'pnpm-workspace.yaml'), stripBom(fs.readFileSync(workspace, 'utf8')), 'utf8')
    }
    if (!fs.existsSync(path.join(target, 'package.json'))) {
      throw new Error('源 profile 没有 package.json：' + source)
    }
    let linked = false
    let linkNote = ''
    const sourceModules = path.join(source, 'node_modules')
    if (fs.existsSync(sourceModules)) {
      const link = path.join(target, 'node_modules')
      try {
        if (process.platform === 'win32') fs.symlinkSync(sourceModules, link, 'junction')
        else fs.symlinkSync(sourceModules, link, 'dir')
        linked = true
      } catch (e) {
        linkNote = String((e && e.message) || e)
      }
    } else {
      linkNote = '源 profile 没有 node_modules'
    }
    return { name, dir: target, home: tempHome, source, linked, linkNote, full }
  } catch (e) {
    try {
      fs.rmSync(tempHome, { recursive: true, force: true })
    } catch (cleanupError) {
      // 清理失败不掩盖原始错误
    }
    throw e
  }
}

function removeTempHome(tempHome, dir) {
  // 只删本脚本创建的临时目录；目录名被别人改掉或参数传错时宁可不删。
  if (!path.basename(tempHome).startsWith('dsh-panel-verify-') || !path.basename(dir).startsWith('panel-verify-')) {
    throw new Error('拒绝删除非临时目录：' + tempHome + ' / ' + dir)
  }
  const link = path.join(dir, 'node_modules')
  try {
    if (fs.lstatSync(link).isSymbolicLink()) fs.unlinkSync(link)
  } catch (e) {
    // 不存在或已经断开：继续删目录
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      fs.rmSync(tempHome, { recursive: true, force: true })
      return
    } catch (e) {
      if (attempt === 2) throw e
      sleepSync(500)
    }
  }
}

function collect(child, buffer) {
  const append = (chunk) => {
    const text = chunk.toString('utf8')
    buffer.text += text
    if (buffer.text.length > 400000) buffer.text = buffer.text.slice(-200000)
  }
  if (child.stdout) child.stdout.on('data', append)
  if (child.stderr) child.stderr.on('data', append)
}

async function stopChild(child) {
  if (child === undefined || child === null || child.exitCode !== null) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
  } else {
    try {
      child.kill('SIGTERM')
    } catch (e) {
      // 已经退出
    }
  }
  const deadline = Date.now() + 5000
  while (child.exitCode === null && Date.now() < deadline) await sleep(100)
  if (child.exitCode === null) {
    try {
      child.kill('SIGKILL')
    } catch (e) {
      // 已经退出
    }
  }
}

function waitForWebLine(buffer, child, timeoutMs) {
  return new Promise((resolve) => {
    const started = Date.now()
    const tick = () => {
      const found = readWebLine(buffer.text)
      if (found !== null) return resolve({ found })
      if (buffer.spawnError !== null) return resolve({ spawnError: true })
      if (child.exitCode !== null) return resolve({ exited: true })
      if (Date.now() - started > timeoutMs) return resolve({ timedOut: true })
      setTimeout(tick, 250)
    }
    tick()
  })
}

function tail(text, lines) {
  const all = text.trimEnd().split(/\r?\n/)
  return all.slice(Math.max(0, all.length - lines)).join('\n')
}

// 启动失败时真正的线索（哪个插件没激活、缺哪个包）常被后面的堆栈挤到 tail 之外；先抽出来。
function failureSummary(text) {
  const pattern = /startup failed|Failed plugins|failed to import|did not activate|Cannot find package|plugin failures|ERR_MODULE_NOT_FOUND|failed to activate/i
  return text.split(/\r?\n/).filter((line) => pattern.test(line)).slice(-8).join('\n')
}

function warnFailure(io, text, tailLines) {
  const summary = failureSummary(text)
  if (summary !== '') io.warn(summary)
  io.warn(tail(text, tailLines))
}

async function checkPage(base, cookie, names, io) {
  const response = await fetch(base + '/', { headers: cookie === null ? {} : { cookie } })
  const text = await response.text()
  const missing = names.filter((name) => !text.includes(name + '/client.js'))
  io.say('  页面清单 HTTP ' + response.status + '，' + (missing.length === 0 ? '两个包的 client.js 都在' : '缺 ' + missing.join('、') + ' 的 client.js'))
  return { ok: response.status === 200 && missing.length === 0, missing }
}

async function runVerification(options, io) {
  const timeoutMs = Math.max(5, Number(options.timeout) || 120) * 1000
  const home = resolveDshHome(options.dshHome)
  if (home.home === null) {
    io.warn('找不到 DSH_HOME（试过：' + home.tried.join('、') + '）；传 --dsh-home 指定。')
    return 2
  }
  const active = resolveActiveProfile(home.home, options.profile)
  if (active.profile === null || !isValidProfileName(active.profile)) {
    io.warn('定不到 profile（' + home.home + '/profiles 下有：' + (active.candidates.join('、') || '无') + '）；传 --profile 指定。')
    return 2
  }
  const cli = resolveDshCli(options.dsh)
  if (cli.command === null) {
    io.warn('找不到 dsh 命令行（试过：' + cli.tried.join('、') + '）。')
    io.warn('桌面版没带命令行时，先看日志地址能不能走路由四；拿不到再走路由五（插件页粘贴）。')
    return 2
  }
  const read = readProfileManifest(home.home, active.profile)
  if (read.manifest === null) {
    io.warn('读不到 profile ' + active.profile + ' 的 package.json（' + read.error + '）。')
    return 2
  }
  const sourceBundles = read.manifest.dsh && read.manifest.dsh.profile && Array.isArray(read.manifest.dsh.profile.bundles)
    ? read.manifest.dsh.profile.bundles
    : []
  if (options.full !== true && (!sourceBundles.includes('@deepseek-ai/dsh-base') || !sourceBundles.includes('@deepseek-ai/dsh-web-app'))) {
    io.warn('profile ' + active.profile + ' 不是 web 形态（dsh.profile.bundles 里缺 @deepseek-ai/dsh-base 或 '
      + '@deepseek-ai/dsh-web-app），最小组合起不来；这个脚本只验桌面版的 web profile。')
    return 2
  }
  const registered = PANEL_PACKAGES
    .map((item) => ({ name: item.name, reg: packageRegistration(read.manifest, item.name) }))
    .filter((item) => item.reg.bundle || item.reg.dependency !== null)
  if (registered.length === 0) {
    io.warn('profile ' + active.profile + ' 里两个包都没登记（dependencies 与 dsh.profile.bundles 都空）。')
    io.warn('先按路由三/四/五装，再回来验证。')
    return 2
  }
  // 只写依赖、没进 bundles 的包启动时不会加载；这时临时 profile 会替它补齐 bundles，写出假绿，
  // 所以先报出来并停下，等人补登记。
  const incomplete = registered.filter((item) => !item.reg.bundle)
  if (incomplete.length > 0) {
    io.warn('登记不完整：' + incomplete.map((item) => item.name).join('、')
      + ' 在 dependencies 里，但不在 dsh.profile.bundles；重启也不会加载。先按路由三补登记。')
    return 1
  }
  const expected = registered.map((item) => item.name)
  io.say('DSH_HOME  ' + home.home)
  io.say('profile   ' + active.profile + '（源目录 ' + read.dir + '）')
  io.say('dsh       ' + cli.label)
  io.say('要验证的包：' + expected.join('、'))

  let temp = null
  let child = null
  const buffer = { text: '', spawnError: null }
  try {
    temp = copyProfile(home.home, active.profile, expected, options.full === true)
    // 临时实例用临时 DSH_HOME：日志、缓存、sessions 不会写进真实 home，home 级 patch 也不叠加；
    // 会话里继承的 DSH_PROFILE / DSH_PROFILE_DIR / DSH_WEB_URL 指回真实实例，一并清掉。
    const childEnv = Object.assign({}, process.env, options.env || {}, { DSH_HOME: temp.home })
    for (const key of ['DSH_PROFILE', 'DSH_PROFILE_DIR', 'DSH_WEB_URL', 'DSH_SESSION_ID', 'DSH_SHELL', 'NODE_COMPILE_CACHE']) delete childEnv[key]
    io.say('临时 DSH_HOME：' + temp.home)
    io.say('  profile ' + temp.name + '（' + (temp.full ? '配置层完整副本' : '最小组合 base + web-app + 已登记的包') + '；node_modules ' + (temp.linked ? '已联接' : '未联接：' + temp.linkNote) + '）')

    const dumped = spawnCliSync(cli, ['--profile', temp.name, '--dump-config'], {
      cwd: path.resolve(__dirname, '..'),
      env: childEnv,
      encoding: 'utf8',
      timeout: Math.max(60000, timeoutMs),
    })
    const dumpText = (dumped.stdout || '') + (dumped.stderr || '')
    const missingSections = expected.filter((name) => !dumpText.includes('# == ' + name))
    if (dumped.status !== 0 || missingSections.length > 0) {
      io.warn('dump-config ' + (dumped.status === 0 ? '退出 0，但缺 ' + missingSections.join('、') + ' 的层' : '退出 ' + dumped.status))
      warnFailure(io, dumpText, 12)
      return 1
    }
    io.say('dump-config   ok（' + expected.length + ' 个包的层都在）')

    child = spawnCli(cli, ['--profile', temp.name, '--no-open', '--host', '127.0.0.1', '--port', '0'], {
      cwd: path.resolve(__dirname, '..'),
      env: childEnv,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    child.on('error', (e) => { buffer.spawnError = String((e && e.message) || e) })
    collect(child, buffer)
    const waited = await waitForWebLine(buffer, child, timeoutMs)
    if (waited.found === undefined) {
      io.warn(waited.spawnError ? '临时实例没起来：' + buffer.spawnError
        : waited.exited ? '临时实例启动后退出了（没打印 dsh web: 地址）'
          : '等实例打印 dsh web: 地址超时（' + Math.round(timeoutMs / 1000) + ' 秒）')
      warnFailure(io, buffer.text, 15)
      return 1
    }
    io.say('实例地址   ' + waited.found.base)

    const session = await sessionCookie(waited.found.base, waited.found.token)
    if (session.cookie === null) {
      io.warn('索引页 HTTP ' + session.status + '，没拿到会话 cookie')
      return 1
    }
    io.say('会话 cookie ok（索引页 HTTP ' + session.status + '）')

    const page = await checkPage(waited.found.base, session.cookie, expected, io)
    if (!page.ok) return 1

    if (expected.includes(PANEL_NAME)) {
      const response = await rpcCall(RPC_CHANNEL, RPC_ENDPOINT, { sessionId: null }, waited.found.base, session.cookie)
      const result = response.envelope && response.envelope.result ? response.envelope.result : null
      if (response.status !== 200 || result === null || result.ok !== true) {
        io.warn('RPC ' + RPC_CHANNEL + '/' + RPC_ENDPOINT + ' 不通：HTTP ' + response.status + '，'
          + (result === null ? '应答不是合法信封' : 'result.ok=' + String(result.ok)))
        return 1
      }
      io.say('RPC          ok（' + RPC_ENDPOINT + ' 回 result.ok=true）')
    }

    io.say('全部通过：临时 profile 能拼出配置，host 半注册了 RPC，页面会加载两个包的浏览器半。')
    return 0
  } catch (e) {
    io.warn('验证异常：' + String((e && e.stack) || e))
    return 1
  } finally {
    await stopChild(child)
    if (temp !== null) {
      if (options.keep) {
        io.say('保留临时 DSH_HOME：' + temp.home + '（--keep；验证完请手动删掉）')
      } else {
        try {
          removeTempHome(temp.home, temp.dir)
        } catch (e) {
          io.warn('临时 DSH_HOME 没删干净：' + temp.home + '（' + String((e && e.message) || e) + '）')
        }
      }
    }
  }
}

// ── 自测：用假 dsh 跑完整流程，不需要真 DSH ────────────────────────────────

const FAKE_CLI = String.raw`'use strict'
const http = require('http')
const argv = process.argv.slice(2)
if (argv.includes('--dump-config')) {
  const lines = ['# == dsh-sleuth-panels', '- id: fake-panel', '# == dsh-sleuth-vllm-kb', '- id: fake-vllm']
  if (process.env.FAKE_CLI_DUMP_MODE === 'missing-vllm') {
    console.log(lines.slice(0, 2).join('\n'))
    process.exit(0)
  }
  console.log(lines.join('\n'))
  process.exit(0)
}
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (req.method === 'GET' && url.pathname === '/' && url.searchParams.has('token')) {
    if (url.searchParams.get('token') !== 'selftest-token') { res.writeHead(403); res.end(); return }
    res.writeHead(303, { 'set-cookie': 'dsh_session=selftest; Path=/', location: '/' })
    res.end()
    return
  }
  if (req.method === 'GET' && url.pathname === '/') {
    res.writeHead(200, { 'content-type': 'text/html' })
    res.end('<script src="/plugins/dsh-sleuth-panels/client.js"></script><script src="/plugins/dsh-sleuth-vllm-kb/client.js"></script>')
    return
  }
  if (req.method === 'POST' && url.pathname === '/ascend-sleuth-panels/ascend-traces-list') {
    let body = ''
    req.on('data', (chunk) => { body += chunk })
    req.on('end', () => {
      const message = JSON.parse(body)
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ type: 'server-response', rpcId: message.rpcId, result: { ok: true, sessions: [] } }))
    })
    return
  }
  res.writeHead(404)
  res.end()
})
server.listen(0, '127.0.0.1', () => {
  console.log('dsh web: http://127.0.0.1:' + server.address().port + '/?token=selftest-token')
})
`

function writeFakeHome(base) {
  const home = path.join(base, 'home')
  const profile = path.join(home, 'profiles', 'demo')
  fs.mkdirSync(path.join(profile, 'node_modules'), { recursive: true })
  // 故意带 BOM：自测同时验证"读入时剥 BOM、写回无 BOM"
  const manifest = {
    name: 'dsh-profile-demo',
    dependencies: { 'dsh-sleuth-panels': 'link:/tmp/fake-panels', 'dsh-sleuth-vllm-kb': 'link:/tmp/fake-vllm' },
    dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app', 'dsh-sleuth-panels', 'dsh-sleuth-vllm-kb'], patchReload: 'live' } },
  }
  fs.writeFileSync(path.join(profile, 'package.json'), '\ufeff' + JSON.stringify(manifest, null, 2) + '\n', 'utf8')
  fs.writeFileSync(path.join(profile, 'cordis.patch.yml'), '[]\n', 'utf8')
  return { home, profile }
}

async function selftest() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'panel-verify-selftest-'))
  const fake = path.join(base, 'fake-dsh.js')
  fs.writeFileSync(fake, FAKE_CLI, 'utf8')
  const quiet = makeIo(true)
  const leftoverDirs = () => fs.readdirSync(os.tmpdir()).filter((name) => name.startsWith('dsh-panel-verify-')).length
  const leftoversBefore = leftoverDirs()
  let failures = 0
  try {
    const { home } = writeFakeHome(base)
    const ok = await runVerification({ dshHome: home, profile: 'demo', dsh: fake, timeout: 20, keep: false }, quiet)
    const okPass = ok === 0
    failures += okPass ? 0 : 1
    process.stdout.write('  ' + (okPass ? 'ok  ' : 'FAIL') + ' 正常路径：' + (okPass ? '退出 0' : '退出 ' + ok) + '\n')

    // 坏 dump：缺 vllm-kb 的层 → 必须在 dump 这一步失败，且不能把实例起起来
    const bad = await runVerification({ dshHome: home, profile: 'demo', dsh: fake, timeout: 20, env: { FAKE_CLI_DUMP_MODE: 'missing-vllm' } }, quiet)
    const badPass = bad === 1
    failures += badPass ? 0 : 1
    process.stdout.write('  ' + (badPass ? 'ok  ' : 'FAIL') + ' 缺层路径：' + (badPass ? '退出 1' : '退出 ' + bad) + '\n')

    // profile 里没登记任何包 → 前置缺失 2
    const empty = path.join(base, 'empty-home')
    fs.mkdirSync(path.join(empty, 'profiles', 'demo'), { recursive: true })
    fs.writeFileSync(path.join(empty, 'profiles', 'demo', 'package.json'), JSON.stringify({ name: 'dsh-profile-demo', dsh: { profile: { bundles: [] } } }), 'utf8')
    const missing = await runVerification({ dshHome: empty, profile: 'demo', dsh: fake, timeout: 20 }, quiet)
    const missingPass = missing === 2
    failures += missingPass ? 0 : 1
    process.stdout.write('  ' + (missingPass ? 'ok  ' : 'FAIL') + ' 未登记路径：' + (missingPass ? '退出 2' : '退出 ' + missing) + '\n')

    // 只写依赖、没进 bundles → 登记不完整，必须在起实例前停下（否则最小 profile 会替它补万全）
    const partial = path.join(base, 'partial-home')
    fs.mkdirSync(path.join(partial, 'profiles', 'demo'), { recursive: true })
    fs.writeFileSync(path.join(partial, 'profiles', 'demo', 'package.json'), JSON.stringify({
      name: 'dsh-profile-demo',
      dependencies: { 'dsh-sleuth-panels': 'link:/tmp/fake-panels' },
      dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'] } },
    }), 'utf8')
    const incomplete = await runVerification({ dshHome: partial, profile: 'demo', dsh: fake, timeout: 20 }, quiet)
    const incompletePass = incomplete === 1
    failures += incompletePass ? 0 : 1
    process.stdout.write('  ' + (incompletePass ? 'ok  ' : 'FAIL') + ' 登记不完整路径：' + (incompletePass ? '退出 1' : '退出 ' + incomplete) + '\n')
    const leftoversAfter = leftoverDirs()
    const leftoversPass = leftoversAfter === leftoversBefore
    failures += leftoversPass ? 0 : 1
    process.stdout.write('  ' + (leftoversPass ? 'ok  ' : 'FAIL') + ' 临时 DSH_HOME 清理：'
      + (leftoversPass ? '无残留' : '残留 ' + (leftoversAfter - leftoversBefore) + ' 个') + '\n')
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
  if (failures > 0) {
    process.stderr.write('验证脚本自测未通过：' + failures + ' 例\n')
    return 1
  }
  process.stdout.write('验证脚本自测通过（4 例 + 清理断言：正常 / 缺层 / 未登记 / 登记不完整）\n')
  return 0
}

async function main(argv) {
  const args = parseArgs(argv)
  if (args.help === true) {
    process.stdout.write('用法见本文件头部注释。\n')
    return 0
  }
  if (args.selftest) return selftest()
  return runVerification(args, makeIo(args.quiet))
}

main(process.argv.slice(2)).then((code) => {
  process.exitCode = code
}).catch((error) => {
  process.stderr.write('验证脚本异常：' + String((error && error.stack) || error) + '\n')
  process.exitCode = 1
})
