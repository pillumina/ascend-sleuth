#!/usr/bin/env node
// panel_rpc_probe.js —— 不经 GUI，按客户端的线协议打一条面板 RPC
//
// 为什么需要它：面板包装进 profile 之后，"到底通没通"此前只有两个观察点——host 半的日志，
// 或让人点开 tab 再看界面。前者看不出数据取没取到，后者要人配合。这个探针按页面真实走的
// 那条路打一次：POST <base>/<channel>/<endpoint>，body 是客户端那套信封
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
//
// 退出码：0 拿到 result.ok=true；2 路由不通或未授权（多半是 host 半没加载、还没重启）；
//        1 其他失败（信封不合法、处理函数报错）

'use strict'

const fs = require('fs')
const os = require('os')
const path = require('path')

const CHANNEL = '/ascend-sleuth-panels'
const DEFAULT_ENDPOINT = 'ascend-traces-list'

function parseArgs(argv) {
  const args = { endpoint: DEFAULT_ENDPOINT, payload: null, url: null, token: null, log: null }
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i]
    const value = argv[i + 1]
    if (flag === '--endpoint') { args.endpoint = value; i += 1 } else if (flag === '--payload') { args.payload = value; i += 1 } else if (flag === '--url') { args.url = value; i += 1 } else if (flag === '--token') { args.token = value; i += 1 } else if (flag === '--log') { args.log = value; i += 1 } else if (flag === '--help' || flag === '-h') { args.help = true }
  }
  return args
}

function defaultLogPath() {
  const home = process.env.DSH_HOME
  if (home !== undefined && home !== '') {
    // DSH_HOME 是 …/harness；Desktop 的日志在它的上一层 logs/
    const candidate = path.join(path.dirname(home), 'logs', 'harness.log')
    if (fs.existsSync(candidate)) return candidate
  }
  const appData = process.env.APPDATA
  if (appData !== undefined && appData !== '') {
    const candidate = path.join(appData, 'dsh-desktop', 'logs', 'harness.log')
    if (fs.existsSync(candidate)) return candidate
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

async function resolveTarget(args) {
  if (args.url !== null && args.token !== null) return { base: args.url.replace(/\/$/, ''), token: args.token, source: '命令行' }
  const fromLog = readLogTarget(args.log !== null ? args.log : defaultLogPath())
  if (fromLog === null) return null
  return Object.assign(fromLog, { source: 'harness.log' })
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  if (args.help === true) {
    process.stdout.write('用法见本文件头部注释。\n')
    return 0
  }

  const target = await resolveTarget(args)
  if (target === null) {
    process.stdout.write('探针：拿不到 DSH 的地址与 token（harness.log 里没有 `dsh web:` 行）——如实跳过\n')
    process.stdout.write('  可显式传 --url <base> --token <token>，或 --log <harness.log 路径>\n')
    return 0
  }
  process.stdout.write('探针目标：' + target.base + '（取自 ' + target.source + '）\n')

  // ① 换一次浏览器会话 cookie（页面也是这么进门的）
  let cookie = null
  try {
    const indexResponse = await fetch(target.base + '/?token=' + encodeURIComponent(target.token), { redirect: 'manual' })
    const setCookie = indexResponse.headers.getSetCookie === undefined ? [] : indexResponse.headers.getSetCookie()
    if (setCookie.length > 0) cookie = setCookie.map((one) => one.split(';')[0]).join('; ')
    process.stdout.write('  索引页 HTTP ' + indexResponse.status + (cookie === null ? '（未拿到 cookie）' : '（已拿到会话 cookie）') + '\n')
  } catch (e) {
    process.stderr.write('拿索引页失败：' + String((e && e.message) || e) + '\n')
    return 1
  }

  // ② 按客户端线协议打一条 RPC
  const payload = args.payload === null
    ? { sessionId: process.env.DSH_SESSION_ID === undefined ? null : process.env.DSH_SESSION_ID }
    : JSON.parse(args.payload)
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
    process.stderr.write('RPC 请求失败：' + String((e && e.message) || e) + '\n')
    return 1
  }

  if (response.status === 404 || response.status === 405) {
    process.stderr.write('路由没在服务（HTTP ' + response.status + '）：' + CHANNEL + '\n')
    process.stderr.write('  多半是 host 半没加载——面板包刚装或刚换版本时，要重启 DSH 才会加载新的模块 generation\n')
    return 2
  }
  if (response.status === 401 || response.status === 403) {
    process.stderr.write('未授权（HTTP ' + response.status + '）：token 过期或 cookie 没换成\n')
    return 2
  }
  if (!response.ok) {
    process.stderr.write('HTTP ' + response.status + '：' + (await response.text()).slice(0, 200) + '\n')
    return 1
  }

  let envelope
  try {
    envelope = await response.json()
  } catch (e) {
    process.stderr.write('应答不是 JSON\n')
    return 1
  }
  if (envelope === null || typeof envelope !== 'object' || envelope.type !== 'server-response' || typeof envelope.rpcId !== 'string') {
    process.stderr.write('信封不合法（要 { type: "server-response", rpcId, result }）：' + JSON.stringify(envelope).slice(0, 200) + '\n')
    return 1
  }
  if (envelope.rpcId !== rpcId) {
    process.stderr.write('rpcId 不匹配：发出 ' + rpcId + '，收到 ' + envelope.rpcId + '\n')
    return 1
  }
  const result = envelope.result
  if (result === null || typeof result !== 'object') {
    process.stderr.write('result 不是对象\n')
    return 1
  }
  if (result.ok !== true) {
    const error = result.error === undefined ? {} : result.error
    process.stderr.write('端点 ' + args.endpoint + ' 返回失败：' + String(error.code) + ' ' + String(error.message) + '\n')
    return 1
  }

  const value = result.value === undefined ? null : result.value
  process.stdout.write('  端点 ' + args.endpoint + '：result.ok=true\n')
  if (value !== null && typeof value === 'object' && value.ok === false) {
    // 面板自身的降级信封：RPC 通了，但这一项功能自己说不可用（例如缺 fs/shell、缺工作区）
    process.stderr.write('  面板侧降级：' + String(value.error) + '\n')
    return 1
  }
  process.stdout.write('  value：' + JSON.stringify(value).slice(0, 400) + '\n')
  if (value !== null && Array.isArray(value.sessions)) {
    process.stdout.write('  读到 ' + value.sessions.length + ' 个诊断会话：'
      + value.sessions.map((one) => one.sessionId + '[' + one.status + ']').join(', ') + '\n')
  }
  return 0
}

// 不用 process.exit：fetch 的连接句柄还在收尾时硬退，Windows 上会撞 libuv 断言
// （Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)）。设 exitCode 让事件循环自然收干。
main().then((code) => { process.exitCode = code }).catch((error) => {
  process.stderr.write('探针异常：' + String((error && error.stack) || error) + '\n')
  process.exitCode = 1
})
