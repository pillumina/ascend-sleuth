'use strict'

// panel_endpoint.js —— 面板的几个脚本共用的取址、会话与 RPC 信封
//
// 为什么单独一份：装面板的脚本与验证面板的探针都要先知道 DSH 在哪个地址、token 是什么，
// 再换一份浏览器会话 cookie。桌面版与命令行版的日志位置不同，所以收在这里。

const fs = require('fs')
const os = require('os')
const path = require('path')

// 找 harness.log：命令行与 Windows 桌面版在 $DSH_HOME 上一层的 logs/，
// macOS 桌面版在 ~/Library/Logs/<产品名>/ 下。
//
// 一台机器上可能同时跑着两个 DSH 实例（各自 DSH_HOME、各自监听地址）；日志里那行属于哪个
// 实例，只有和本会话地址比过才知道。DSH 会话里注入了 DSH_WEB_URL（不带 token）：有它时只认
// 地址一致的那份日志；取不到就报「取不到」，不拿另一个实例的地址去装包。
function sessionBase(env) {
  const source = env === undefined ? process.env : env
  const raw = source.DSH_WEB_URL
  if (typeof raw !== 'string' || raw === '') return null
  try {
    const url = new URL(raw)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
    return url.origin
  } catch (e) {
    return null
  }
}

function isLoopbackHost(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
}

// 同一个实例：协议与主机端口一致；回环地址的几种写法算同一台机器（DSH_WEB_URL 与日志行
// 可能一处写 localhost、一处写 127.0.0.1）。
function sameInstance(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false
  try {
    const one = new URL(a)
    const two = new URL(b)
    if (one.protocol !== two.protocol) return false
    if (one.host === two.host) return true
    return one.port === two.port && isLoopbackHost(one.hostname) && isLoopbackHost(two.hostname)
  } catch (e) {
    return false
  }
}

function mtimeOf(file) {
  try {
    return fs.statSync(file).mtimeMs
  } catch (e) {
    return 0
  }
}

// 候选日志按优先级排好：$DSH_HOME 上一层的最先，其次 APPDATA，再 Linux 的 ~/.config，
// 最后 macOS 的 ~/Library/Logs。macOS 那批目录名带 dsh 的排前面（产品名随发行版变），
// 其余的按最近写过排。
function logCandidates(env) {
  const source = env === undefined ? process.env : env
  const homeDir = typeof source.HOME === 'string' && source.HOME !== '' ? source.HOME : os.homedir()
  const list = []
  const home = source.DSH_HOME
  if (home !== undefined && home !== '') list.push(path.join(path.dirname(home), 'logs', 'harness.log'))
  if (source.APPDATA !== undefined && source.APPDATA !== '') list.push(path.join(source.APPDATA, 'dsh-desktop', 'logs', 'harness.log'))
  if (process.platform === 'linux') list.push(path.join(homeDir, '.config', 'dsh-desktop', 'logs', 'harness.log'))
  if (process.platform === 'darwin') {
    const macLogs = path.join(homeDir, 'Library', 'Logs')
    if (fs.existsSync(macLogs)) {
      let names = []
      try {
        names = fs.readdirSync(macLogs)
      } catch (e) {
        names = []
      }
      const found = names
        .map((name) => path.join(macLogs, name, 'harness.log'))
        .filter((file) => fs.existsSync(file))
        .sort((a, b) => mtimeOf(b) - mtimeOf(a))
      const dshNamed = found.filter((one) => /dsh/i.test(path.dirname(one)))
      list.push(...dshNamed, ...found.filter((one) => !dshNamed.includes(one)))
    }
  }
  return list.filter((file) => fs.existsSync(file))
}

function webUrlDeclared(env) {
  const source = env === undefined ? process.env : env
  return typeof source.DSH_WEB_URL === 'string' && source.DSH_WEB_URL !== ''
}

function defaultLogPath(env) {
  const wanted = sessionBase(env)
  const candidates = logCandidates(env)
  if (wanted === null) {
    // DSH_WEB_URL 给了却解析不出地址：无法核对归属，不拿最近写过的日志去猜。
    if (webUrlDeclared(env)) return null
    const hasTarget = (one) => readLogTarget(one) !== null
    return candidates.find(hasTarget) || candidates[0] || null
  }
  const matched = candidates.find((one) => {
    const target = readLogTarget(one)
    return target !== null && sameInstance(target.base, wanted)
  })
  return matched === undefined ? null : matched
}

// 属于别的实例的日志地址：解释"为什么取不到"，也让调用方不去拿它装包。只给地址，不给 token。
function foreignLogTargets(env) {
  const wanted = sessionBase(env)
  if (wanted === null) return []
  const list = []
  for (const one of logCandidates(env)) {
    const target = readLogTarget(one)
    if (target === null || sameInstance(target.base, wanted)) continue
    list.push({ path: one, base: target.base })
  }
  return list
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

// args 认 --url / --token / --log 三个（值为 null 表示没传）
function resolveTarget(args) {
  if (args.url !== null && args.token !== null) {
    return { base: args.url.replace(/\/$/, ''), token: args.token, source: '命令行' }
  }
  const logPath = args.log !== null ? args.log : defaultLogPath()
  const fromLog = readLogTarget(logPath)
  if (fromLog === null) return null
  return Object.assign(fromLog, { source: logPath })
}

// 取不到地址时逐条说明原因（纯函数，便于自测）：本会话实例是谁、哪些日志属于别的实例、
// 是有日志却没 `dsh web:` 行、还是一份日志都没有。
function describeNoTarget(parts) {
  const lines = []
  const wanted = parts.instanceBase === undefined ? null : parts.instanceBase
  const candidates = parts.candidates === undefined ? [] : parts.candidates
  const foreign = parts.foreign === undefined ? [] : parts.foreign
  const explicit = typeof parts.logPath === 'string' && parts.logPath !== ''
  const invalidUrl = typeof parts.webUrl === 'string' && parts.webUrl !== '' && wanted === null
  if (invalidUrl) {
    // 地址给了却解析不出：归属无从核对，不再按环境去猜别的日志；显式 --log 的点名照报。
    lines.push('DSH_WEB_URL 不是合法地址，无法核对日志归属')
  } else if (wanted !== null) {
    lines.push('本会话实例 ' + wanted)
  }
  if (explicit) {
    // 显式传了 --log：只对这个文件下结论，不去猜别的日志。
    lines.push(fs.existsSync(parts.logPath)
      ? '日志 ' + parts.logPath + ' 里没有 `dsh web:` 行'
      : '日志 ' + parts.logPath + ' 不存在')
    return lines
  }
  if (invalidUrl) return lines
  if (foreign.length > 0) {
    for (const one of foreign) lines.push('日志 ' + one.path + ' 里是另一个实例的 ' + one.base + '，不采用')
  } else if (candidates.length === 0) {
    lines.push('没找到 harness.log')
  } else {
    lines.push('日志 ' + candidates[0] + ' 里没有 `dsh web:` 行')
  }
  return lines
}

function noTargetLines(env, logPath) {
  const source = env === undefined ? process.env : env
  const explicit = typeof logPath === 'string' && logPath !== ''
  return describeNoTarget({
    webUrl: source.DSH_WEB_URL,
    instanceBase: sessionBase(source),
    candidates: explicit ? [] : logCandidates(source),
    foreign: explicit ? [] : foreignLogTargets(source),
    logPath: explicit ? logPath : undefined,
  })
}

// 用地址栏那条带 token 的地址换一次浏览器会话 cookie（页面也是这么进门的）
async function sessionCookie(base, token) {
  const response = await fetch(base + '/?token=' + encodeURIComponent(token), { redirect: 'manual' })
  const setCookie = response.headers.getSetCookie === undefined ? [] : response.headers.getSetCookie()
  return {
    status: response.status,
    cookie: setCookie.length === 0 ? null : setCookie.map((one) => one.split(';')[0]).join('; '),
  }
}

// Connection 的一元 RPC：POST <base><channel>/<endpoint>，body 是
// { type: 'client-request', rpcId, method, payload }，应答 { type: 'server-response', rpcId, result }。
// 面板那条通道（/ascend-sleuth-panels）与 API Gateway 那条通道（/api）共用这个形状，
// 差别只在 payload：面板自己定义，Gateway 固定要 { args }。
function envelope(endpoint, payload) {
  return { type: 'client-request', rpcId: 'panel-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8), method: endpoint, payload }
}

async function rpcCall(channel, endpoint, payload, base, cookie) {
  const message = envelope(endpoint, payload)
  const response = await fetch(base + channel + '/' + endpoint, {
    method: 'POST',
    headers: Object.assign({ 'content-type': 'application/json' }, cookie === null ? {} : { cookie }),
    body: JSON.stringify(message),
  })
  const text = await response.text()
  let parsed = null
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    parsed = null
  }
  return { status: response.status, rpcId: message.rpcId, envelope: parsed, text }
}

// ── 不带 token 的 host 半判定 ───────────────────────────────────────────────
//
// 面板包的 host 半把自己注册成一条 prefix 路由；handler 第一件事是判方法，不是 POST 就回 405
// 并设 `Allow: POST`，判完方法才判鉴权（回 401/403）。所以没有 token 也能判这条路由在不在：
//   · `GET <base><channel>/__probe__` → 405 且 Allow 含 POST：路由在，host 半已加载；
//   · `GET <base>/__dsh_probe_unknown__` → 404：对照，证明 404 才是「没这个路径」。
// 未注册 prefix 的 POST 也会得到 405，但那是静态层的通用 405，`Allow` 是 `GET, HEAD`；handler
// 写的 `Allow: POST` 只在路由注册后出现，两条一起看不会把「静态层挡方法」当成「路由在」。
//
// 这一层证明的是「host 半加载了、路由在、鉴权门在」。端点能不能取到数据、加载的是不是这一版，
// 都不在这一层——那要么带 token 打 RPC，要么起临时实例。

async function statusOf(base, path, method, body) {
  const url = base + path
  const options = method === 'POST'
    ? { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }
    : { method }
  const response = await fetch(url, options)
  // 读掉响应体：不读会在 Windows 上留下未收干的连接，进程退出时偶发 libuv 断言。
  await response.arrayBuffer()
  const allow = response.headers.get('allow')
  return { status: response.status, allow: allow === null ? '' : allow }
}

async function probeHostHalf(base, channel) {
  const root = base.replace(/\/$/, '')
  const control = await statusOf(root, '/__dsh_probe_unknown__', 'GET')
  const route = await statusOf(root, channel + '/__probe__', 'GET')
  // 方法闸放行后才是鉴权闸：回 401（或 403）说明 handler 真的跑到了鉴权这一步。
  const auth = route.status === 405
    ? await statusOf(root, channel + '/__probe__', 'POST', { type: 'client-request', rpcId: 'host-probe', method: '__probe__', payload: {} })
    : null
  return {
    control,
    route,
    auth,
    // 只有对照正常、路由回 405 且 Allow 是 POST，才算路由注册过。
    registered: control.status === 404 && route.status === 405 && route.allow.toLowerCase() === 'post',
    absent: control.status === 404 && route.status === 404,
  }
}

module.exports = {
  sessionBase,
  sameInstance,
  logCandidates,
  defaultLogPath,
  foreignLogTargets,
  readLogTarget,
  resolveTarget,
  describeNoTarget,
  noTargetLines,
  sessionCookie,
  rpcCall,
  probeHostHalf,
}
