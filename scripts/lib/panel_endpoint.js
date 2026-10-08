'use strict'

// panel_endpoint.js —— 面板的几个脚本共用的取址、会话与 RPC 信封
//
// 为什么单独一份：装面板的脚本与验证面板的探针都要先知道 DSH 在哪个地址、token 是什么，
// 再换一份浏览器会话 cookie。桌面版的日志位置这部分尤其容易只改一处，所以收在这里。

const fs = require('fs')
const os = require('os')
const path = require('path')

// 找 harness.log：命令行与 Windows 桌面版在 $DSH_HOME 上一层的 logs/，
// macOS 桌面版在 ~/Library/Logs/<产品名>/ 下。
function defaultLogPath() {
  const home = process.env.DSH_HOME
  if (home !== undefined && home !== '') {
    const candidate = path.join(path.dirname(home), 'logs', 'harness.log')
    if (fs.existsSync(candidate)) return candidate
  }
  const appData = process.env.APPDATA
  if (appData !== undefined && appData !== '') {
    const candidate = path.join(appData, 'dsh-desktop', 'logs', 'harness.log')
    if (fs.existsSync(candidate)) return candidate
  }
  // 产品名随发行版变，且 ~/Library/Logs 下可能有别的产品也写同名文件：先试目录名带 dsh 的，
  // 再试真的含 `dsh web:` 行的，最后才按 mtime 兜底取最近写过的那个。
  const macLogs = path.join(os.homedir(), 'Library', 'Logs')
  if (fs.existsSync(macLogs)) {
    const candidates = fs.readdirSync(macLogs)
      .filter((name) => fs.existsSync(path.join(macLogs, name, 'harness.log')))
      .map((name) => path.join(macLogs, name, 'harness.log'))
      .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)
    const dshNamed = candidates.filter((one) => /dsh/i.test(path.dirname(one)))
    const hasTarget = (one) => readLogTarget(one) !== null
    const picked = dshNamed.find(hasTarget) || candidates.find(hasTarget) || dshNamed[0] || candidates[0]
    if (picked !== undefined) return picked
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

module.exports = { defaultLogPath, readLogTarget, resolveTarget, sessionCookie, rpcCall }
