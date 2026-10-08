#!/usr/bin/env node
// panel_install.js —— 不经 GUI，按插件页走的那条 Remote 通道把面板包装进 profile
//
// 为什么需要它：桌面版的 DSH 把插件管理器的模型工具那行写成 disabled: true，模型侧就没有
// plugin_manager 可调；但侧栏「插件」页用的仍是同一个 pluginManager 服务，它经由 Connection
// 的 /api 通道暴露，信封与面板那条通道相同（`{ type: 'client-request', rpcId, method, payload }`），
// 只有 payload 固定为 `{ args }`。于是取到地址与 token 之后，模型侧也能自己装，
// 不必让人去插件页粘贴路径。
//
// 用法：
//   node scripts/panel_install.js                  # 装面板包并使能（先 inspect，已装则补使能）
//   node scripts/panel_install.js --check          # 只读：列出本包的安装与使能状态
//   node scripts/panel_install.js --remove         # 卸载
//   node scripts/panel_install.js --spec <spec>    # 换包：绝对路径 / 包名 / git 地址 / tarball
//   node scripts/panel_install.js --url <base> --token <token>   # 不自动找地址
//   node scripts/panel_install.js --log <harness.log 路径>
//   node scripts/panel_install.js --selftest       # 自带假服务器自测本脚本（不需要 DSH）
//
// 退出码：0 装好并使能（或 --check/--remove 成功）；2 拿不到 DSH 的地址与 token，或 /api
//        没有认领这个端点（多半是这一版 DSH 没有 API Gateway）、未授权；
//        1 其他失败（spec 被拒、安装返回 failed、应答不合法）

'use strict'

const fs = require('fs')
const http = require('node:http')
const path = require('path')
const { resolveTarget, sessionCookie, rpcCall } = require('./lib/panel_endpoint')

const API_CHANNEL = '/api'
const DEFAULT_SPEC = path.resolve(__dirname, '..', 'dsh-plugins', 'dsh-sleuth-panels')

function parseArgs(argv) {
  const args = { spec: DEFAULT_SPEC, check: false, remove: false, url: null, token: null, log: null, quiet: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--spec') { args.spec = value; i += 1 } else if (flag === '--url') { args.url = value; i += 1 } else if (flag === '--token') { args.token = value; i += 1 } else if (flag === '--log') { args.log = value; i += 1 } else if (flag === '--check') { args.check = true } else if (flag === '--remove') { args.remove = true } else if (flag === '--quiet') { args.quiet = true } else if (flag === '--help' || flag === '-h') { args.help = true }
  }
  return args
}

// 路径形式的 spec 能本地读包名；包名/git/tarball 形式交给 inspect 回答
function localPackageName(spec) {
  if (!path.isAbsolute(spec)) return null
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(spec, 'package.json'), 'utf8'))
    return typeof manifest.name === 'string' && manifest.name !== '' ? manifest.name : null
  } catch (e) {
    return null
  }
}

// 打一次 API Gateway 的一元 Remote：payload 固定 { args }
async function apiCall(endpoint, args, target, cookie) {
  const response = await rpcCall(API_CHANNEL, endpoint, { args }, target.base, cookie)
  const envelope = response.envelope
  const valid = envelope !== null && typeof envelope === 'object' && envelope.type === 'server-response' && envelope.rpcId === response.rpcId && typeof envelope.result === 'object' && envelope.result !== null
  return { status: response.status, text: response.text, envelope: valid ? envelope : null }
}

// 一次调用的三种收场：端点在不在、业务认不认、结果是什么
function classify(callResult) {
  if (callResult.status === 404 || callResult.status === 405) return { unreachable: true }
  if (callResult.status === 401 || callResult.status === 403) return { unauthorized: true }
  if (callResult.status !== 200 || callResult.envelope === null) return { malformed: true }
  if (callResult.envelope.result.ok !== true) return { failure: callResult.envelope.result.error === undefined ? {} : callResult.envelope.result.error }
  return { value: callResult.envelope.result.value }
}

async function openTarget(args, io) {
  const target = resolveTarget(args)
  if (target === null) {
    io.say('安装：拿不到 DSH 的地址与 token（日志里没有 `dsh web:` 行）\n')
    io.say('  可显式传 --url <base> --token <token>，或 --log <harness.log 路径>\n')
    return null
  }
  io.say('安装目标：' + target.base + '（地址取自 ' + target.source + '）\n')
  const session = await sessionCookie(target.base, target.token)
  io.say('  索引页 HTTP ' + session.status + (session.cookie === null ? '（未拿到 cookie）' : '（已拿到会话 cookie）') + '\n')
  return { base: target.base, cookie: session.cookie }
}

function describeGuard(guard, io, endpoint) {
  if (guard.unreachable === true) {
    io.warn('  /api 没认领 ' + endpoint + '（HTTP 404）：这一版 DSH 的 API Gateway 没在服务这个端点\n')
    return 2
  }
  if (guard.unauthorized === true) {
    io.warn('  未授权：token 过期或 cookie 没换成\n')
    return 2
  }
  if (guard.malformed === true) {
    io.warn('  应答不合法（要 { type: "server-response", rpcId, result }）\n')
    return 1
  }
  io.warn('  ' + endpoint + ' 返回失败：' + String(guard.failure.code) + ' ' + String(guard.failure.message) + '\n')
  return 1
}

async function ensureEnabled(name, target, io) {
  const call = await apiCall('pluginManager/setBundleEnabled', { name: name, enabled: true }, target, target.cookie === undefined ? null : target.cookie)
  const guard = classify(call)
  if (guard.value === undefined) return describeGuard(guard, io, 'pluginManager/setBundleEnabled')
  const change = guard.value
  io.say('  已装，使能结果：changed=' + change.changed + ' application=' + change.application + '\n')
  return change.application === 'failed' || change.application === 'cancelled' ? 1 : 0
}

async function runInstall(args, io) {
  const say = io.quiet ? () => {} : io.say
  const warn = io.quiet ? () => {} : io.warn
  if (args.help === true) {
    say('用法见本文件头部注释。\n')
    return 0
  }

  let target
  try {
    target = await openTarget(args, io)
  } catch (e) {
    warn('拿索引页失败：' + String((e && e.message) || e) + '\n')
    return 1
  }
  if (target === null) return 2

  const call = await apiCall('pluginManager/inspect', { spec: args.spec }, target, target.cookie)
  const guard = classify(call)
  if (guard.value === undefined) return describeGuard(guard, io, 'pluginManager/inspect')
  const inspection = guard.value

  if (args.check === true) {
    const listed = classify(await apiCall('pluginManager/listBundles', {}, target, target.cookie))
    if (listed.value === undefined) return describeGuard(listed, io, 'pluginManager/listBundles')
    const name = inspection.status === 'accepted' && inspection.name !== undefined ? inspection.name : localPackageName(args.spec)
    const rows = (Array.isArray(listed.value) ? listed.value : []).filter((one) => name === null || one.name === name)
    if (rows.length === 0) {
      say('  没有装：' + (name === null ? String(args.spec) : name) + '\n')
      return 1
    }
    for (const row of rows) {
      say('  ' + row.name + ' ' + String(row.version) + '：installed=' + row.installed + ' enabled=' + row.enabled + ' removable=' + row.removable + '\n')
    }
    return 0
  }

  if (args.remove === true) {
    const name = inspection.status === 'accepted' && inspection.name !== undefined ? inspection.name : localPackageName(args.spec)
    if (name === null) {
      warn('  --remove 要知道包名，而 ' + String(args.spec) + ' 不是能读到 package.json 的本地路径\n')
      return 1
    }
    const removed = classify(await apiCall('pluginManager/removeBundle', { name: name }, target, target.cookie))
    if (removed.value === undefined) return describeGuard(removed, io, 'pluginManager/removeBundle')
    say('  卸载结果：changed=' + removed.value.changed + ' application=' + removed.value.application + '\n')
    return removed.value.application === 'failed' || removed.value.application === 'cancelled' ? 1 : 0
  }

  if (inspection.status === 'refused') {
    if (inspection.problem !== 'already-installed') {
      warn('  这个 spec 被拒：' + String(inspection.problem) + ' ' + String(inspection.reason) + '\n')
      return 1
    }
    const name = localPackageName(args.spec)
    if (name === null) {
      warn('  已装，但 spec 不是本地路径，读不到包名，无法确认使能状态\n')
      return 1
    }
    return ensureEnabled(name, target, io)
  }

  if (inspection.bundle === false) {
    warn('  这个包没有 bundle 补丁（package.json 的 dsh.bundle.patch），装上不会带来面板 tab\n')
  }
  const installed = classify(await apiCall('pluginManager/installBundle', { spec: args.spec, options: { enabled: true } }, target, target.cookie))
  if (installed.value === undefined) return describeGuard(installed, io, 'pluginManager/installBundle')
  const change = installed.value
  say('  安装结果：stage=' + change.stage + ' target=' + change.target + ' changed=' + change.changed + ' application=' + change.application + '\n')
  for (const warning of Array.isArray(change.warnings) ? change.warnings : []) say('  警告：' + String(warning) + '\n')
  if (change.application === 'failed' || change.application === 'cancelled') {
    warn('  安装没成功：' + JSON.stringify(change.error) + '\n')
    return 1
  }
  say('  下一步：node scripts/panel_rpc_probe.js 验面板通道，再刷新页面看 tab\n')
  return 0
}

// 自测：假服务器只做这几件事，把四条判定各走一遍（不需要 DSH，所以 CI 里也能跑）
function startFakeServer(specPaths) {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url === undefined ? '/' : req.url, 'http://127.0.0.1')
    if (req.method === 'GET' && url.pathname === '/') {
      res.writeHead(303, { 'set-cookie': 'dsh-install-selftest=1; Path=/' })
      res.end()
      return
    }
    if (req.method !== 'POST' || !url.pathname.startsWith('/api/')) {
      res.writeHead(404)
      res.end('not found')
      return
    }
    const endpoint = url.pathname.slice('/api/'.length)
    let raw = ''
    req.on('data', (chunk) => { raw += chunk })
    req.on('end', () => {
      const body = JSON.parse(raw)
      const args = body.payload.args === undefined ? {} : body.payload.args
      const spec = typeof args.spec === 'string' ? args.spec : ''
      const reply = (result) => {
        res.writeHead(200, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ type: 'server-response', rpcId: body.rpcId, result }))
      }
      if (spec === specPaths.unclaimed) {
        res.writeHead(404)
        res.end('not found')
        return
      }
      if (endpoint === 'pluginManager/inspect') {
        if (spec === specPaths.failing) reply({ ok: true, value: { status: 'accepted', kind: 'path', name: 'selftest-bundle', bundle: true, registry: null } })
        else if (spec === specPaths.already) reply({ ok: true, value: { status: 'refused', problem: 'already-installed', reason: 'selftest 已装' } })
        else if (spec === specPaths.refused) reply({ ok: true, value: { status: 'refused', problem: 'not-a-package', reason: 'selftest 故意拒' } })
        else reply({ ok: true, value: { status: 'accepted', kind: 'path', name: 'selftest-bundle', bundle: true, registry: null } })
        return
      }
      if (endpoint === 'pluginManager/installBundle') {
        if (spec === specPaths.failing) reply({ ok: true, value: { stage: 'install', target: spec, enabled: true, changed: true, application: 'failed', error: { code: 'invalid-spec', diagnostic: 'selftest 故意失败' }, warnings: [] } })
        else reply({ ok: true, value: { stage: 'install', target: spec, enabled: true, changed: true, application: 'applied', warnings: [] } })
        return
      }
      if (endpoint === 'pluginManager/setBundleEnabled') {
        reply({ ok: true, value: { stage: 'enable', target: args.name, enabled: true, changed: false, application: 'applied', warnings: [] } })
        return
      }
      if (endpoint === 'pluginManager/listBundles') {
        reply({ ok: true, value: [{ name: 'selftest-bundle', version: '1.0.0', enabled: true, installed: true, removable: true }] })
        return
      }
      if (endpoint === 'pluginManager/removeBundle') {
        reply({ ok: true, value: { stage: 'remove', target: args.name, changed: true, application: 'applied', warnings: [] } })
        return
      }
      res.writeHead(404)
      res.end('not found')
    })
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }))
  })
}

async function selftest() {
  const quiet = { quiet: true, say: () => {}, warn: () => {} }
  const dir = fs.mkdtempSync(path.join(require('os').tmpdir(), 'panel-install-selftest-'))
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'selftest-bundle', version: '1.0.0' }))
  const specPaths = {
    accepted: dir,
    already: dir,
    refused: path.join(dir, 'refused'),
    failing: path.join(dir, 'failing'),
    unclaimed: path.join(dir, 'unclaimed'),
  }
  const { server, port } = await startFakeServer(specPaths)
  const base = 'http://127.0.0.1:' + port
  const cases = [
    { name: '正常安装', spec: specPaths.accepted, want: 0 },
    { name: '已装则补使能', spec: specPaths.already, want: 0 },
    { name: 'spec 被拒', spec: specPaths.refused, want: 1 },
    { name: '安装返回 failed', spec: specPaths.failing, want: 1 },
    { name: '--check 读到状态', spec: specPaths.accepted, check: true, want: 0 },
    { name: '--remove 卸载', spec: specPaths.accepted, remove: true, want: 0 },
    { name: 'api 没认领端点', spec: specPaths.unclaimed, want: 2 },
    { name: '拿不到地址', spec: specPaths.accepted, noTarget: true, want: 2 },
  ]
  let bad = 0
  try {
    for (const item of cases) {
      const args = Object.assign(parseArgs([]), {
        spec: item.spec,
        check: item.check === true,
        remove: item.remove === true,
        url: item.noTarget === true ? null : base,
        token: item.noTarget === true ? null : 'selftest-token',
        log: item.noTarget === true ? path.join(dir, 'no-such-harness.log') : null,
      })
      const got = await runInstall(args, quiet)
      const ok = got === item.want
      if (!ok) bad += 1
      process.stdout.write('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + item.name + '：exit=' + got + '（期望 ' + item.want + '）\n')
    }
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
  if (bad > 0) {
    process.stderr.write('panel-install 自测未通过：' + bad + ' 例\n')
    return 1
  }
  process.stdout.write('panel-install selftest ok（8 例：安装 / 已装使能 / spec 被拒 / 安装失败 / 查状态 / 卸载 / 端点没认领 / 拿不到地址）\n')
  return 0
}

async function main() {
  const argv = process.argv.slice(2)
  if (argv.includes('--selftest')) return selftest()
  return runInstall(parseArgs(argv), { say: (text) => process.stdout.write(text), warn: (text) => process.stderr.write(text) })
}

// 不用 process.exit：fetch 的连接句柄还在收尾时硬退，Windows 上会撞 libuv 断言
main().then((code) => { process.exitCode = code }).catch((error) => {
  process.stderr.write('安装脚本异常：' + String((error && error.stack) || error) + '\n')
  process.exitCode = 1
})
