#!/usr/bin/env node
// session_cost.mjs —— 从 DSH 会话日志里读**真实账单**（提供方 usage），不是估算。
//
// 为什么用 Node 而不是 Python：DSH 的会话日志是 session.jsonl.zstd，且是**多帧** zstd
// （一个文件由成百上千个独立帧拼接）。Node ≥ 22.15 / 24 自带 zlib.zstdDecompressSync；
// Python 标准库没有 zstd，需要额外依赖——本仓 scripts/ 一贯零依赖，所以这一件用 .mjs
// （与 panel_render_check.js / check_loader_idempotency.js 同例）。
// ⚠️ 多帧陷阱：zstdDecompressSync 只解**第一帧**就返回，于是一个 1.1MB 的日志会"成功"
// 解出 188 字节的会话头——看起来正常，实则丢了全部对话。本脚本按帧魔数切帧逐帧解，
// 解不动就把边界往后并（防止魔数恰好出现在压缩载荷里）。
//
// 量的东西（提供方返回的计费用量，落在 assistant/message.usage 与流式 usage chunk 上）：
//   uncachedInput / cacheRead / cacheWrite / output（其中 reasoning）。
// 同一 (turn, step) 会同时出现流式与定稿两份，按**定稿优先**去重，避免重复计数。
//
// 逐步归因（--steps）：轨迹里本来就有 tool/call 与 tool/result，本脚本把「这一步多花了多少
//   上下文」与「这一步调了什么工具、返回多大」对齐——没有这一列，读者只知道某一步变大了，
//   不知道大在哪。工具返回大小按 content 里的文本字节数算（估算，不是计费）。
//
// 用途：给 skill/内容流程的收尾提供 measured 口径的数字——exec-log 的
// `--tokens N --cost-source measured` 就该填这里读出来的值，而不是估算。
//
// 用法：
//   node scripts/session_cost.mjs                       # 当前会话（$DSH_SESSION_JSONL）
//   node scripts/session_cost.mjs --session <id>       # 按会话 id 在 $DSH_HOME/sessions 下找
//   node scripts/session_cost.mjs --file <path.jsonl.zstd>
//   node scripts/session_cost.mjs --all [--workspace <子串>]   # 逐会话汇总（回填历史账单）
//   node scripts/session_cost.mjs --steps              # 逐步表：上下文增量 × 工具与返回大小
//   加 --json 输出机器可读结果。

import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { zstdDecompressSync } from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

function arg(name, fallback = undefined) {
  const i = process.argv.indexOf(`--${name}`)
  if (i === -1) return fallback
  const next = process.argv[i + 1]
  return next && !next.startsWith('--') ? next : true
}

/** 多帧 zstd → 完整文本。只有从 start 解到某个边界的整段成功时才推进 start。 */
function readSessionLog(file) {
  const buf = readFileSync(file)
  if (buf.subarray(0, 4).compare(MAGIC) !== 0) return buf.toString('utf8') // 已是明文
  let start = 0
  let out = ''
  let frames = 0
  let i = buf.indexOf(MAGIC, 4)
  while (i !== -1) {
    try {
      out += zstdDecompressSync(buf.subarray(start, i)).toString('utf8')
      frames++
      start = i
    } catch { /* 载荷里恰好出现魔数：不推进 start，继续找下一个边界 */ }
    i = buf.indexOf(MAGIC, i + 4)
  }
  out += zstdDecompressSync(buf.subarray(start)).toString('utf8')
  frames++
  return out
}

function usageOf(event) {
  const d = event.data ?? {}
  if (event.type === 'assistant/message' && d.usage) return { usage: d.usage, kind: 'final', d }
  if (event.type === 'assistant/chunk' && d.chunk?.type === 'usage') return { usage: d.chunk.usage, kind: 'stream', d }
  return null
}

// 工具返回进入上下文的文本字节数（估算）：content 里 tool-result 块的嵌套文本 + 其他块的 text。
function resultBytes(message) {
  let n = 0
  const blocks = message?.content ?? []
  for (const b of blocks) {
    if (b?.type === 'tool-result') {
      for (const c of b.content ?? []) n += typeof c?.text === 'string' ? c.text.length : 0
    } else if (typeof b?.text === 'string') {
      n += b.text.length
    }
  }
  return n
}

function summarize(file) {
  const text = readSessionLog(file)
  const attempts = new Map()
  const calls = new Map()   // callId -> 该次调用的记录
  const steps = new Map()   // "turn/step" -> { calls: [...], resultBytes }
  const stepOf = (turn, step) => {
    const k = `${turn}/${step}`
    if (!steps.has(k)) steps.set(k, { calls: [], resultBytes: 0 })
    return steps.get(k)
  }
  let provider = '-', model = '-', bad = 0, lines = 0
  const turns = new Map()
  for (const line of text.split('\n')) {
    if (!line) continue
    lines++
    let event
    try { event = JSON.parse(line) } catch { bad++; continue }
    if (event.type === 'tool/call') {
      const d = event.data ?? {}
      const rec = { name: d.name ?? '?', argBytes: (d.arguments ?? '').length, outBytes: 0 }
      calls.set(d.callId, rec)
      stepOf(d.turn, d.step).calls.push(rec)
      continue
    }
    if (event.type === 'tool/result') {
      const d = event.data ?? {}
      const n = resultBytes(d.message)
      const rec = calls.get(d.callId)
      if (rec) rec.outBytes = n
      stepOf(d.turn, d.step).resultBytes += n
      continue
    }
    const hit = usageOf(event)
    if (!hit) continue
    const { usage, kind, d } = hit
    const src = d.message?.source ?? {}
    if (src.provider) provider = src.provider
    if (src.model) model = src.model
    const key = `${d.turn}/${d.step}`
    const prev = attempts.get(key)
    if (prev && prev.kind === 'final' && kind === 'stream') continue // 定稿优先
    const row = {
      turn: d.turn, step: d.step, kind,
      input: usage.inputTokens ?? 0, output: usage.outputTokens ?? 0,
      cacheRead: usage.cacheReadTokens ?? 0, cacheWrite: usage.cacheWriteTokens ?? 0,
      reasoning: usage.reasoningTokens ?? 0,
    }
    attempts.set(key, row)
  }
  const rows = [...attempts.values()].sort((a, b) => (a.turn - b.turn) || (a.step - b.step))
  for (const r of rows) {
    const st = steps.get(`${r.turn}/${r.step}`)
    r.tools = st ? st.calls : []
    r.resultBytes = st ? st.resultBytes : 0
    r.prompt = r.input + r.cacheRead + r.cacheWrite
  }
  const sum = k => rows.reduce((t, r) => t + r[k], 0)
  const promptOf = r => r.input + r.cacheRead + r.cacheWrite
  for (const r of rows) {
    const t = turns.get(r.turn) ?? { turn: r.turn, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, steps: 0 }
    t.input += r.input; t.output += r.output; t.cacheRead += r.cacheRead; t.cacheWrite += r.cacheWrite; t.steps++
    turns.set(r.turn, t)
  }
  const totals = {
    uncachedInput: sum('input'), cacheRead: sum('cacheRead'), cacheWrite: sum('cacheWrite'),
    output: sum('output'), reasoning: sum('reasoning'),
  }
  totals.inputSide = totals.uncachedInput + totals.cacheRead + totals.cacheWrite
  totals.billed = totals.inputSide + totals.output
  return {
    file, lines, bad, provider, model,
    attempts: rows.length,
    peakPrompt: rows.length ? Math.max(...rows.map(promptOf)) : 0,
    finalPrompt: rows.length ? promptOf(rows[rows.length - 1]) : 0,
    totals,
    turns: [...turns.values()],
    steps: rows.map(r => ({
      turn: r.turn, step: r.step, prompt: r.prompt, uncached: r.input, output: r.output,
      resultBytes: r.resultBytes,
      tools: r.tools.map(t => ({ name: t.name, outBytes: t.outBytes })),
    })),
    top: [...rows].sort((a, b) => promptOf(b) - promptOf(a)).slice(0, 5)
      .map(r => ({ ...r, prompt: promptOf(r) })),
  }
}

function findSession(id) {
  const dshHome = process.env.DSH_HOME || join(homedir(), '.dsh')
  const roots = [join(dshHome, 'sessions')]
  for (const root of roots) {
    if (!existsSync(root)) continue
    for (const ws of readdirSync(root)) {
      const dir = join(root, ws, id)
      const f = join(dir, 'session.jsonl.zstd')
      if (existsSync(f)) return f
    }
  }
  return null
}

function allSessions(workspaceFilter) {
  const dshHome = process.env.DSH_HOME || join(homedir(), '.dsh')
  const root = join(dshHome, 'sessions')
  const out = []
  if (!existsSync(root)) return out
  for (const ws of readdirSync(root)) {
    if (workspaceFilter && !ws.includes(workspaceFilter)) continue
    const wsDir = join(root, ws)
    if (!statSync(wsDir).isDirectory()) continue
    for (const id of readdirSync(wsDir)) {
      const f = join(wsDir, id, 'session.jsonl.zstd')
      if (existsSync(f)) out.push({ workspace: ws, id, file: f })
    }
  }
  return out
}

const json = process.argv.includes('--json')
const fmt = n => n.toLocaleString('en-US')

if (process.argv.includes('--all')) {
  const list = allSessions(String(arg('workspace', '') || ''))
  const rows = list.map(s => ({ ...s, summary: summarize(s.file) }))
  if (json) { console.log(JSON.stringify(rows.map(r => ({ workspace: r.workspace, id: r.id, ...r.summary })), null, 1)); process.exit(0) }
  console.log(`${rows.length} 个会话（DSH_HOME/sessions）`)
  console.log('workspace                              session                    attempts      uncachedIn      cacheRead       output     billed')
  let t = { uncachedInput: 0, cacheRead: 0, cacheWrite: 0, output: 0, billed: 0 }
  for (const r of rows) {
    const s = r.summary.totals
    for (const k of Object.keys(t)) t[k] += s[k] ?? 0
    console.log(`${r.workspace.padEnd(38)} ${r.id.slice(-12).padEnd(26)} ${String(s && r.summary.attempts).padStart(8)} ${fmt(s.uncachedInput).padStart(15)} ${fmt(s.cacheRead).padStart(14)} ${fmt(s.output).padStart(12)} ${fmt(s.billed).padStart(12)}`)
  }
  console.log(`${'合计'.padEnd(38)} ${''.padEnd(26)} ${''.padStart(8)} ${fmt(t.uncachedInput).padStart(15)} ${fmt(t.cacheRead).padStart(14)} ${fmt(t.output).padStart(12)} ${fmt(t.billed).padStart(12)}`)
  process.exit(0)
}

const explicit = arg('file')
const sessionId = arg('session')
const file = explicit && explicit !== true ? String(explicit)
  : sessionId && sessionId !== true ? findSession(String(sessionId))
    : process.env.DSH_SESSION_JSONL
if (!file || !existsSync(file)) {
  console.error(`找不到会话日志（--file / --session / $DSH_SESSION_JSONL 都没给对）：${file ?? '(none)'}`)
  process.exit(2)
}

const s = summarize(file)
if (json) { console.log(JSON.stringify(s, null, 1)); process.exit(0) }

console.log(`file: ${s.file}`)
console.log(`provider/model: ${s.provider} / ${s.model}`)
console.log(`events=${s.lines} unparsable=${s.bad} billed attempts=${s.attempts}`)
console.log('')
console.log('turn  steps      uncachedIn      cacheRead     cacheWrite       output')
for (const t of s.turns) {
  console.log(`${String(t.turn).padStart(4)} ${String(t.steps).padStart(6)} ${fmt(t.input).padStart(15)} ${fmt(t.cacheRead).padStart(14)} ${fmt(t.cacheWrite).padStart(13)} ${fmt(t.output).padStart(12)}`)
}
console.log('')
console.log(`TOTAL uncachedInput=${fmt(s.totals.uncachedInput)}  cacheRead=${fmt(s.totals.cacheRead)}  cacheWrite=${fmt(s.totals.cacheWrite)}  output=${fmt(s.totals.output)} (reasoning ${fmt(s.totals.reasoning)})`)
console.log(`INPUT SIDE=${fmt(s.totals.inputSide)}  BILLED=${fmt(s.totals.billed)}  cache-read share=${(100 * s.totals.cacheRead / (s.totals.inputSide || 1)).toFixed(1)}%`)
console.log(`final prompt=${fmt(s.finalPrompt)}  peak prompt=${fmt(s.peakPrompt)}`)
const toolBrief = r => r.tools.length
  ? r.tools.map(t => `${t.name}${t.outBytes ? '(' + fmt(t.outBytes) + 'B)' : ''}`).join(' + ')
  : '-'
console.log('')
console.log('top 5 steps by prompt size:')
for (const r of s.top) {
  console.log(`  turn ${r.turn} step ${r.step}: prompt=${fmt(r.prompt)} (uncached ${fmt(r.input)} + cacheRead ${fmt(r.cacheRead)}) out=${fmt(r.output)}  工具=${toolBrief(r)}`)
}
if (process.argv.includes('--steps')) {
  console.log('')
  console.log('逐步表（prompt=该步上下文规模；uncached=新进上下文；返回=工具返回的文本字节，估算）')
  console.log(`  ${'turn'.padStart(4)} ${'step'.padStart(4)} ${'prompt'.padStart(12)} ${'uncached'.padStart(12)} ${'返回'.padStart(11)}  工具`)
  for (const r of s.steps) {
    console.log(`  ${String(r.turn).padStart(4)} ${String(r.step).padStart(4)} ${fmt(r.prompt).padStart(12)} ${fmt(r.uncached).padStart(12)} ${fmt(r.resultBytes).padStart(11)}  ${r.tools.map(t => t.name).join(' + ') || '-'}`)
  }
}
