#!/usr/bin/env node
// panel_rpc_probe.js —— 不经 GUI，按客户端的线协议打一条面板 RPC
//
// 为什么需要它：面板包装进 profile 之后，"到底通没通"此前只有两个观察点——host 半的日志
// （看不出数据取没取到），或让人点开 tab 再看界面（要人配合）。这个探针按页面真实走的那条路
// 打一次：POST <base>/<channel>/<endpoint>，body 是客户端那套信封
// `{ type: 'client-request', rpcId, method, payload }`，应答 `{ type: 'server-response', rpcId, result }`，
// result 为 `{ ok, value }` 或 `{ ok: false, error: { code, message, details } }`。
//
// 它能证明的：host 半挂上了、路由在、会话工作区解析得出、面板处理函数与数据源跑通。
// 它不能证明的：React 那一层的渲染与排版（那只有看页面）。
//
// 用法：
//   node scripts/panel_rpc_probe.js                     # 有 token 打一条 RPC；没有就退到 host 半判定
//   node scripts/panel_rpc_probe.js --url <base> --token <token>
//   node scripts/panel_rpc_probe.js --endpoint ascend-metrics-verdict --payload '{"sessionId":"…"}'
//   node scripts/panel_rpc_probe.js --log <harness.log 路径>
//   node scripts/panel_rpc_probe.js --host-only         # 只验 host 半，不打 RPC
//   node scripts/panel_rpc_probe.js --selftest          # 自带假服务器自测本脚本（不需要 DSH）
//
// 桌面版把带 token 的地址写进自己接管的管道、不落磁盘时，探针取不到 token。这时它拿会话里的
// DSH_WEB_URL（不带 token）做一遍 host 半判定：注册过的 prefix 路由对 GET 回 405 且 Allow: POST，
// 未注册的回 404，对照一条未知路径的 404 可判路由在不在（实现在 lib/panel_endpoint.js）。
//
// 退出码：0 拿到 result.ok=true；3 没有 token，只证到 host 半（路由在、鉴权门在），端点与取数
//        没验；2 拿不到地址与 token，或 host 半没加载（路由没注册），或带 token 时未授权／路由
//        没在服务；1 其他失败（连不上、信封不合法、面板侧降级、处理函数报错）

'use strict'

const http = require('node:http')
const { sessionBase, resolveTarget, noTargetLines, sessionCookie, rpcCall, probeHostHalf } = require('./lib/panel_endpoint')

const CHANNEL = '/ascend-sleuth-panels'
const DEFAULT_ENDPOINT = 'ascend-traces-list'

function parseArgs(argv) {
  const args = { endpoint: DEFAULT_ENDPOINT, payload: null, url: null, token: null, log: null, quiet: false, hostOnly: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--endpoint') { args.endpoint = value; i += 1 } else if (flag === '--payload') { args.payload = value; i += 1 } else if (flag === '--url') { args.url = value; i += 1 } else if (flag === '--token') { args.token = value; i += 1 } else if (flag === '--log') { args.log = value; i += 1 } else if (flag === '--host-only') { args.hostOnly = true } else if (flag === '--quiet') { args.quiet = true } else if (flag === '--help' || flag === '-h') { args.help = true }
  }
  return args
}

async function runProbe(args, io) {
  const say = io.quiet ? () => {} : io.say
  const warn = io.quiet ? () => {} : io.warn

  if (args.help === true) {
    say('用法见本文件头部注释。\n')
    return 0
  }

  const target = resolveTarget(args)
  if (target !== null && args.hostOnly !== true) return runRpc(args, target, say, warn)

  // 没有 token 时也要能判 host 半：地址不必从日志里取，会话里的 DSH_WEB_URL 就是。
  const explicit = args.url === null ? null : args.url.replace(/\/$/, '')
  const base = target !== null ? target.base : (explicit !== null ? explicit : sessionBase())
  if (base === null) {
    say('探针：拿不到 DSH 的地址与 token\n')
    for (const line of noTargetLines(process.env, args.log)) say('  ' + line + '\n')
    say('  可显式传 --url <base> --token <token>，或 --log <harness.log 路径>\n')
    return 2
  }
  return runHostHalf(base, target, say, warn)
}

// 不带 token 的一层：只判 host 半加载没加载。它回答不了「端点能不能取数」与「是不是这一版」，
// 所以单独给退出码 3，不与 0（RPC 通了）混在一起。
async function runHostHalf(base, target, say, warn) {
  say('探针：只验 host 半（端点与取数不验）\n')
  say('  目标 ' + base + '（地址取自 ' + (target === null ? 'DSH_WEB_URL' : target.source) + '）\n')

  let probe
  try {
    probe = await probeHostHalf(base, CHANNEL)
  } catch (e) {
    warn('连不上 ' + base + '：' + String((e && e.message) || e) + '\n')
    return 1
  }

  const pad = (text) => text + ' '.repeat(Math.max(1, 39 - text.length))
  say('  对照  ' + pad('GET /__dsh_probe_unknown__') + 'HTTP ' + probe.control.status + '\n')
  say('  路由  ' + pad('GET ' + CHANNEL + '/__probe__') + 'HTTP ' + probe.route.status
    + (probe.route.allow === '' ? '' : '（Allow: ' + probe.route.allow + '）') + '\n')
  if (probe.auth !== null) say('  鉴权  ' + pad('POST ' + CHANNEL + '/__probe__') + 'HTTP ' + probe.auth.status + '\n')

  if (probe.registered) {
    say('  结论：host 半已加载，' + CHANNEL + ' 路由在'
      + (probe.auth !== null && probe.auth.status === 401 ? '，鉴权门在（请求没带会话 cookie）' : '') + '\n')
    say('  没验的：这条端点能不能取数、加载的是不是这一版。要验得带 token，或跑 verify_panel_desktop.js\n')
    return 3
  }
  if (probe.absent) {
    warn('  结论：host 半没加载（' + CHANNEL + ' 路由没注册，未知路径才回 404）\n')
    warn('  多半是面板包刚装或刚换版本，重启 DSH 才会加载新的模块 generation\n')
    return 2
  }
  warn('  结论：判不了（对照 HTTP ' + probe.control.status + '，路由 HTTP ' + probe.route.status + '）\n')
  warn('  期望对照 404、路由 405 且 Allow: POST；别的组合说明这个地址不是 DSH 的 web 服务\n')
  return 1
}

async function runRpc(args, target, say, warn) {
  say('探针目标：' + target.base + '（地址取自 ' + target.source + '）\n')

  // ① 换一次浏览器会话 cookie（页面也是这么进门的）
  let cookie = null
  try {
    const session = await sessionCookie(target.base, target.token)
    cookie = session.cookie
    say('  索引页 HTTP ' + session.status + (cookie === null ? '（未拿到 cookie）' : '（已拿到会话 cookie）') + '\n')
  } catch (e) {
    warn('拿索引页失败：' + String((e && e.message) || e) + '\n')
    return 1
  }

  // ② 按客户端线协议打一条 RPC
  let payload
  try {
    payload = args.payload === null
      ? { sessionId: process.env.DSH_SESSION_ID === undefined ? null : process.env.DSH_SESSION_ID }
      : JSON.parse(args.payload)
  } catch (e) {
    warn('--payload 不是合法 JSON：' + String((e && e.message) || e) + '\n')
    return 1
  }

  let response
  try {
    response = await rpcCall(CHANNEL, args.endpoint, payload, target.base, cookie)
  } catch (e) {
    warn('RPC 请求失败：' + String((e && e.message) || e) + '\n')
    return 1
  }

  if (response.status === 404 || response.status === 405) {
    warn('路由没在服务（HTTP ' + response.status + '）：' + CHANNEL + '\n')
    warn('  多半是 host 半没加载——面板包刚装或刚换版本时，要重启 DSH 才会加载新的模块 generation\n')
    return 2
  }
  if (response.status === 401 || response.status === 403) {
    warn('未授权（HTTP ' + response.status + '）：' + (response.status === 403 ? 'host 不在信任列表\n' : 'token 过期或 cookie 没换成\n'))
    return 2
  }
  if (response.status !== 200) {
    warn('HTTP ' + response.status + '：' + response.text.slice(0, 200) + '\n')
    return 1
  }

  const envelope = response.envelope
  if (envelope === null || typeof envelope !== 'object' || envelope.type !== 'server-response' || typeof envelope.rpcId !== 'string') {
    warn('信封不合法（要 { type: "server-response", rpcId, result }）：' + JSON.stringify(envelope).slice(0, 200) + '\n')
    return 1
  }
  if (envelope.rpcId !== response.rpcId) {
    warn('rpcId 不匹配：发出 ' + response.rpcId + '，收到 ' + envelope.rpcId + '\n')
    return 1
  }
  const result = envelope.result
  if (result === null || typeof result !== 'object') {
    warn('result 不是对象\n')
    return 1
  }
  if (result.ok !== true) {
    const error = result.error === undefined ? {} : result.error
    warn('端点 ' + args.endpoint + ' 返回失败：' + String(error.code) + ' ' + String(error.message) + '\n')
    return 1
  }

  const value = result.value === undefined ? null : result.value
  say('  端点 ' + args.endpoint + '：result.ok=true\n')
  if (value !== null && typeof value === 'object' && value.ok === false) {
    // 面板自身的降级信封：RPC 通了，但这一项功能自己说不可用（例如缺 fs/shell、缺工作区）
    warn('  面板侧降级：' + String(value.error) + '\n')
    return 1
  }
  say('  value：' + JSON.stringify(value).slice(0, 400) + '\n')
  if (value !== null && Array.isArray(value.sessions)) {
    say('  读到 ' + value.sessions.length + ' 个诊断会话：'
      + value.sessions.map((one) => one.sessionId + '[' + one.status + ']').join(', ') + '\n')
  }
  return 0
}

// 自测：起两个最小假服务器（一个假装 prefix 路由在，一个什么都不认），把八条判定各走一遍
// （不需要 DSH，所以 CI 里也能跑）
function startFakeServer() {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url === undefined ? '/' : req.url, 'http://127.0.0.1')
    if (req.method === 'GET' && url.pathname === '/') {
      res.writeHead(303, { 'set-cookie': 'dsh-probe-selftest=1; Path=/' })
      res.end()
      return
    }
    // 真宿主的行为：prefix 路由的 handler 先判方法（405 + Allow: POST），再判鉴权（401）。
    if (req.method === 'GET' && url.pathname.startsWith(CHANNEL)) {
      res.writeHead(405, { allow: 'POST' })
      res.end()
      return
    }
    if (req.method === 'POST' && url.pathname.startsWith(CHANNEL + '/') && req.headers.cookie === undefined) {
      res.writeHead(401)
      res.end('unauthorized')
      return
    }
    if (req.method !== 'POST' || !url.pathname.startsWith(CHANNEL + '/')) {
      // 真宿主：未知路径 GET 回 404、POST 回 405（对照那条 404 就是靠这个形状）。
      res.writeHead(req.method === 'POST' ? 405 : 404)
      res.end()
      return
    }
    const endpoint = url.pathname.slice(CHANNEL.length + 1)
    let raw = ''
    req.on('data', (chunk) => { raw += chunk })
    req.on('end', () => {
      let body = null
      try {
        body = JSON.parse(raw)
      } catch (e) {
        res.writeHead(400)
        res.end('body is not JSON')
        return
      }
      const reply = (result) => {
        res.writeHead(200, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ type: 'server-response', rpcId: body.rpcId, result }))
      }
      if (endpoint === 'bad-envelope') {
        res.writeHead(200, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ nope: true }))
        return
      }
      if (endpoint === 'boom') {
        reply({ ok: false, error: { code: 'internal', message: 'selftest 故意失败', details: {} } })
        return
      }
      if (endpoint === 'degraded') {
        reply({ ok: true, value: { ok: false, error: '面板侧降级（自测）' } })
        return
      }
      reply({
        ok: true,
        value: {
          ok: true,
          sessions: [
            { sessionId: 'selftest-a', status: 'resolved' },
            { sessionId: 'selftest-b', status: 'pending' },
          ],
        },
      })
    })
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }))
  })
}

// 一个什么都不认的服务器：拿来当「host 半没加载」的对照（所有路径都回 404）。
function startBareServer() {
  const server = http.createServer((req, res) => {
    res.writeHead(404)
    res.end()
  })
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }))
  })
}

async function selftest() {
  const quiet = { quiet: true, say: () => {}, warn: () => {} }
  const { server, port } = await startFakeServer()
  const bare = await startBareServer()
  const base = 'http://127.0.0.1:' + port
  const bareBase = 'http://127.0.0.1:' + bare.port
  const cases = [
    { name: '正常应答', endpoint: 'ascend-traces-list', want: 0 },
    { name: '信封不合法', endpoint: 'bad-envelope', want: 1 },
    { name: '处理函数报错', endpoint: 'boom', want: 1 },
    { name: '面板侧降级', endpoint: 'degraded', want: 1 },
    { name: '路由没在服务', url: base + '/not-our-prefix', want: 2 },
    { name: '只验 host 半：路由在', url: base, hostOnly: true, want: 3 },
    { name: '只验 host 半：路由没注册', url: bareBase, hostOnly: true, want: 2 },
  ]
  let bad = 0
  try {
    for (const item of cases) {
      const args = Object.assign(parseArgs([]), {
        endpoint: item.endpoint === undefined ? DEFAULT_ENDPOINT : item.endpoint,
        url: item.url === undefined ? base : item.url,
        token: 'selftest-token',
        payload: '{"sessionId":"selftest"}',
        hostOnly: item.hostOnly === true,
      })
      const got = await runProbe(args, quiet)
      const ok = got === item.want
      if (!ok) bad += 1
      process.stdout.write('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + item.name + '：exit=' + got + '（期望 ' + item.want + '）\n')
    }

    // 桌面版的实际入口：没有 --url/--token，地址来自会话的 DSH_WEB_URL。
    const saved = process.env.DSH_WEB_URL
    process.env.DSH_WEB_URL = base
    let fallback
    try {
      fallback = await runProbe(Object.assign(parseArgs([]), { log: 'dsh-probe-selftest-no-such.log' }), quiet)
    } finally {
      if (saved === undefined) delete process.env.DSH_WEB_URL
      else process.env.DSH_WEB_URL = saved
    }
    const fallbackOk = fallback === 3
    if (!fallbackOk) bad += 1
    process.stdout.write('  ' + (fallbackOk ? 'ok  ' : 'FAIL') + ' 没 token 时从 DSH_WEB_URL 退到 host 半：exit=' + fallback + '（期望 3）\n')
  } finally {
    await new Promise((resolve) => server.close(resolve))
    await new Promise((resolve) => bare.server.close(resolve))
  }
  if (bad > 0) {
    process.stderr.write('panel-rpc-probe 自测未通过：' + bad + ' 例\n')
    return 1
  }
  process.stdout.write('panel-rpc-probe selftest ok（8 例：正常 / 信封 / 报错 / 降级 / 路由不在 / host 半在 / host 半不在 / 无 token 退路）\n')
  return 0
}

async function main() {
  const argv = process.argv.slice(2)
  if (argv.includes('--selftest')) return selftest()
  const args = parseArgs(argv)
  return runProbe(args, { quiet: args.quiet === true, say: (text) => process.stdout.write(text), warn: (text) => process.stderr.write(text) })
}

// 不用 process.exit：fetch 的连接句柄还在收尾时硬退，Windows 上会撞 libuv 断言
// （Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)）。设 exitCode 让事件循环自然收干。
main().then((code) => { process.exitCode = code }).catch((error) => {
  process.stderr.write('探针异常：' + String((error && error.stack) || error) + '\n')
  process.exitCode = 1
})
