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
//   node scripts/panel_rpc_probe.js                     # 自动从 Desktop 的 harness.log 取 url 与 token
//   node scripts/panel_rpc_probe.js --url <base> --token <token>
//   node scripts/panel_rpc_probe.js --endpoint ascend-metrics-verdict --payload '{"sessionId":"…"}'
//   node scripts/panel_rpc_probe.js --log <harness.log 路径>
//   node scripts/panel_rpc_probe.js --selftest          # 自带假服务器自测本脚本（不需要 DSH）
//
// 退出码：0 拿到 result.ok=true；2 路由没在服务或未授权（多半是 host 半没加载、还没重启）；
//        1 其他失败（信封不合法、面板侧降级、处理函数报错）

'use strict'

const fs = require('fs')
const http = require('node:http')
const os = require('os')
const path = require('path')

const CHANNEL = '/ascend-sleuth-panels'
const DEFAULT_ENDPOINT = 'ascend-traces-list'

function parseArgs(argv) {
  const args = { endpoint: DEFAULT_ENDPOINT, payload: null, url: null, token: null, log: null, quiet: false }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--endpoint') { args.endpoint = value; i += 1 } else if (flag === '--payload') { args.payload = value; i += 1 } else if (flag === '--url') { args.url = value; i += 1 } else if (flag === '--token') { args.token = value; i += 1 } else if (flag === '--log') { args.log = value; i += 1 } else if (flag === '--quiet') { args.quiet = true } else if (flag === '--help' || flag === '-h') { args.help = true }
  }
  return args
}

function defaultLogPath() {
  const home = process.env.DSH_HOME
  if (home !== undefined && home !== '') {
    // DSH_HOME 是 …/harness；命令行与 Windows 桌面版的日志在它的上一层 logs/
    const candidate = path.join(path.dirname(home), 'logs', 'harness.log')
    if (fs.existsSync(candidate)) return candidate
  }
  const appData = process.env.APPDATA
  if (appData !== undefined && appData !== '') {
    const candidate = path.join(appData, 'dsh-desktop', 'logs', 'harness.log')
    if (fs.existsSync(candidate)) return candidate
  }
  // macOS 桌面版把日志写在 ~/Library/Logs/<产品名>/harness.log，不在 Application Support 下；
  // 产品名随发行版变，所以按目录扫，取最近写过的那个。
  const macLogs = path.join(os.homedir(), 'Library', 'Logs')
  if (fs.existsSync(macLogs)) {
    const found = fs.readdirSync(macLogs)
      .filter((name) => fs.existsSync(path.join(macLogs, name, 'harness.log')))
      .map((name) => path.join(macLogs, name, 'harness.log'))
      .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)
    if (found.length > 0) return found[0]
  }
  return null
}

// 从 harness.log 里取最后一条 `dsh web: http://host:port/?token=…`
function readLogTarget(logPath) {
  if (logPath === null) return null
  let text = ''
  try {
    text = fs.readFileSync(logPath, 'utf8')
  } catch (e) {
    return null
  }
  const matches = [...text.matchAll(/dsh web:\s*(https?:\/\/[^\s?]+)\/?\?token=([^\s]+)/g)]
  if (matches.length === 0) return null
  const last = matches[matches.length - 1]
  return { base: last[1].replace(/\/$/, ''), token: last[2] }
}

function resolveTarget(args) {
  if (args.url !== null && args.token !== null) {
    return { base: args.url.replace(/\/$/, ''), token: args.token, source: '命令行' }
  }
  const fromLog = readLogTarget(args.log !== null ? args.log : defaultLogPath())
  if (fromLog === null) return null
  return Object.assign(fromLog, { source: 'harness.log' })
}

async function runProbe(args, io) {
  const say = io.quiet ? () => {} : io.say
  const warn = io.quiet ? () => {} : io.warn

  if (args.help === true) {
    say('用法见本文件头部注释。\n')
    return 0
  }

  const target = resolveTarget(args)
  if (target === null) {
    say('探针：拿不到 DSH 的地址与 token（harness.log 里没有 `dsh web:` 行）——如实跳过\n')
    say('  可显式传 --url <base> --token <token>，或 --log <harness.log 路径>\n')
    return 0
  }
  say('探针目标：' + target.base + '（取自 ' + target.source + '）\n')

  // ① 换一次浏览器会话 cookie（页面也是这么进门的）
  let cookie = null
  try {
    const indexResponse = await fetch(target.base + '/?token=' + encodeURIComponent(target.token), { redirect: 'manual' })
    const setCookie = indexResponse.headers.getSetCookie === undefined ? [] : indexResponse.headers.getSetCookie()
    if (setCookie.length > 0) cookie = setCookie.map((one) => one.split(';')[0]).join('; ')
    say('  索引页 HTTP ' + indexResponse.status + (cookie === null ? '（未拿到 cookie）' : '（已拿到会话 cookie）') + '\n')
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
  const rpcId = 'probe-' + Date.now()
  const message = { type: 'client-request', rpcId, method: args.endpoint, payload }

  let response
  try {
    response = await fetch(target.base + CHANNEL + '/' + args.endpoint, {
      method: 'POST',
      headers: Object.assign({ 'content-type': 'application/json' }, cookie === null ? {} : { cookie }),
      body: JSON.stringify(message),
    })
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
    warn('未授权（HTTP ' + response.status + '）：token 过期或 cookie 没换成\n')
    return 2
  }
  if (!response.ok) {
    warn('HTTP ' + response.status + '：' + (await response.text()).slice(0, 200) + '\n')
    return 1
  }

  let envelope
  try {
    envelope = await response.json()
  } catch (e) {
    warn('应答不是 JSON\n')
    return 1
  }
  if (envelope === null || typeof envelope !== 'object' || envelope.type !== 'server-response' || typeof envelope.rpcId !== 'string') {
    warn('信封不合法（要 { type: "server-response", rpcId, result }）：' + JSON.stringify(envelope).slice(0, 200) + '\n')
    return 1
  }
  if (envelope.rpcId !== rpcId) {
    warn('rpcId 不匹配：发出 ' + rpcId + '，收到 ' + envelope.rpcId + '\n')
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

// 自测：起一个最小的假服务器，把三条判定各走一遍（不需要 DSH，所以 CI 里也能跑）
function startFakeServer() {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url === undefined ? '/' : req.url, 'http://127.0.0.1')
    if (req.method === 'GET' && url.pathname === '/') {
      res.writeHead(303, { 'set-cookie': 'dsh-probe-selftest=1; Path=/' })
      res.end()
      return
    }
    if (req.method !== 'POST' || !url.pathname.startsWith(CHANNEL + '/')) {
      res.writeHead(405)
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

async function selftest() {
  const quiet = { quiet: true, say: () => {}, warn: () => {} }
  const { server, port } = await startFakeServer()
  const base = 'http://127.0.0.1:' + port
  const cases = [
    { name: '正常应答', endpoint: 'ascend-traces-list', want: 0 },
    { name: '信封不合法', endpoint: 'bad-envelope', want: 1 },
    { name: '处理函数报错', endpoint: 'boom', want: 1 },
    { name: '面板侧降级', endpoint: 'degraded', want: 1 },
    { name: '路由没在服务', url: base + '/not-our-prefix', want: 2 },
  ]
  let bad = 0
  try {
    for (const item of cases) {
      const args = Object.assign(parseArgs([]), {
        endpoint: item.endpoint === undefined ? DEFAULT_ENDPOINT : item.endpoint,
        url: item.url === undefined ? base : item.url,
        token: 'selftest-token',
        payload: '{"sessionId":"selftest"}',
      })
      const got = await runProbe(args, quiet)
      const ok = got === item.want
      if (!ok) bad += 1
      process.stdout.write('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + item.name + '：exit=' + got + '（期望 ' + item.want + '）\n')
    }
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
  if (bad > 0) {
    process.stderr.write('panel-rpc-probe 自测未通过：' + bad + ' 例\n')
    return 1
  }
  process.stdout.write('panel-rpc-probe selftest ok（5 例：正常 / 信封 / 报错 / 降级 / 路由不在）\n')
  return 0
}

async function main() {
  const argv = process.argv.slice(2)
  if (argv.includes('--selftest')) return selftest()
  return runProbe(parseArgs(argv), { say: (text) => process.stdout.write(text), warn: (text) => process.stderr.write(text) })
}

// 不用 process.exit：fetch 的连接句柄还在收尾时硬退，Windows 上会撞 libuv 断言
// （Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)）。设 exitCode 让事件循环自然收干。
main().then((code) => { process.exitCode = code }).catch((error) => {
  process.stderr.write('探针异常：' + String((error && error.stack) || error) + '\n')
  process.exitCode = 1
})
