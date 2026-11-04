// Sleuth Canvas —— host 半（ESM，单文件，无静态 import）。
//
// 职责（契约见 docs/CONTRACT.md §2）：
//   1. 用 sessions + fs 服务定位 ascend-sleuth 仓库根（traces/ 与 scripts/metrics_health.py）；
//   2. 读 traces/*.yaml（手写 YAML 子集解析），产出 list / detail 两个 RPC 的归一化数据；
//   3. detail 里附带 host 规则生成的 insights 与证据文件体量；
//   4. 注册一条 prefix HTTP 路由 /sleuth-canvas，承载两个端点。
//
// 数据来源是 ascend-sleuth 仓库（只读），本插件不写它、不起子进程、不联网。
//
// 来源说明：
//   · YAML 子集解析器移植自 ascend-sleuth 仓 dsh-plugins/ascend-panel/panel-host.js
//     （splitYamlLine / yamlScalar / flowStartIndex / flowBalance / readYamlMap /
//      readYamlValue / readYamlSeq / parseInlineMap 那一组，约 2197–2560 行）；
//     保留容错语义（丢弃行统计），只改写了导出方式与少量注释。
//   · RPC 路由适配层照抄 dsh-plugins/dsh-sleuth-panels/lib/index.js 末尾的 prefix route
//     （connection.requestRejection 鉴权、1 MiB 体上限、{type:'server-response',rpcId,result}）。
//   · 不移植面板的其余逻辑：本插件只读、不改 trace、不写缓存文件（摘要缓存在内存里）。

const CHANNEL = '/sleuth-canvas'
const MAX_BODY_BYTES = 1024 * 1024
const TRACE_FILE_RE = /^[A-Za-z0-9._-]+\.yaml$/

// ---- trace YAML 子集解析（移植自 panel-host.js，见文件头来源说明） ----------------
// 为什么不引库：常驻插件不允许静态 import 第三方包，Host 也没有 YAML 服务。
// trace 由 agent 手写，两种形态都要吃：内联 `- {role: agent, output: "…"}` 与块写法
// （`- role: agent` 换行缩进展开，长 output/reason/evidence.inline 用块标量 `>-`）。

function splitYamlLine(raw) {
  // 去注释（`#` 前有空白才算注释）+ 去行尾空白；引号内的 # / : 保持原样
  let out = ''
  let quote = null
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i]
    if (quote) { out += ch; if (ch === quote) quote = null; continue }
    if (ch === '"' || ch === "'") { quote = ch; out += ch; continue }
    if (ch === '#' && (i === 0 || /\s/.test(raw[i - 1]))) break
    out += ch
  }
  return out.replace(/\s+$/, '')
}

// 双引号串的转义按单遍扫描解（PyYAML 口径）。不要用链式 replace：
// 链式先换 `\n` 会把 `\\n`（字面反斜杠 + n）误当换行，`\\\\` 也会被多解一层。
function yamlUnescapeDouble(inner) {
  let out = ''
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i]
    if (ch !== '\\') { out += ch; continue }
    const next = inner[i + 1]
    if (next === undefined) { out += ch; continue }
    i++
    if (next === 'n') out += '\n'
    else if (next === 't') out += '\t'
    else if (next === 'r') out += '\r'
    else if (next === '"') out += '"'
    else if (next === '\\') out += '\\'
    else if (next === '/') out += '/'
    else out += '\\' + next   // 未知转义不猜：原样保留
  }
  return out
}

function yamlUnquote(s) {
  const t = String(s == null ? '' : s).trim()
  if (t.length >= 2 && (t[0] === '"' || t[0] === "'") && t[t.length - 1] === t[0]) {
    const inner = t.slice(1, -1)
    return t[0] === '"' ? yamlUnescapeDouble(inner) : inner.replace(/''/g, "'")
  }
  return t
}

function splitFlow(inner) {
  const parts = []
  let cur = ''
  let quote = null
  let depth = 0
  for (let i = 0; i < inner.length; i++) {
    const ch = inner[i]
    if (quote) { cur += ch; if (ch === quote) quote = null; continue }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue }
    if (ch === '[' || ch === '{') depth++
    if (ch === ']' || ch === '}') depth = Math.max(0, depth - 1)
    if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; continue }
    cur += ch
  }
  if (cur.trim() !== '') parts.push(cur)
  return parts
}

function yamlScalar(text) {
  const t = String(text == null ? '' : text).trim()
  if (t === '') return ''
  if (t[0] === '{') return parseInlineMap(t)
  if (t[0] === '[') {
    const inner = t.slice(1, t[t.length - 1] === ']' ? -1 : undefined)
    return splitFlow(inner).map(yamlScalar)
  }
  return yamlUnquote(t)
}

// 值是否以行内流集合开头（`{…}` / `[…]`）。判据要严：只有紧跟键冒号或序列 dash 的
// `{`/`[` 才是流集合；`summary: 文本里有 {` 里的花括号是标量内容，不能当作集合接下去。
function flowStartIndex(body) {
  let m = /^-[ \t]+([{[])/.exec(body)
  if (m) return m[0].length - 1
  m = /^[A-Za-z_][A-Za-z0-9_.-]*:[ \t]*([{[])/.exec(body)
  if (m) return m[0].length - 1
  if (body[0] === '{' || body[0] === '[') return 0
  return -1
}

// 从 from 起数括号深度；引号内的括号与 `\"` 转义不算（返回 0 表示已闭合）
function flowBalance(text, from) {
  let depth = 0
  let quote = null
  for (let i = from; i < text.length; i++) {
    const ch = text[i]
    if (quote) {
      if (ch === '\\' && quote === '"') { i++; continue }
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") { quote = ch; continue }
    if (ch === '{' || ch === '[') depth++
    else if (ch === '}' || ch === ']') { depth--; if (depth <= 0) return 0 }
  }
  return depth
}

// 解析器没收下的行（跳过或吞掉）。stats 由调用方给；不给就只算不报。
function markDropped(cursor, row, why) {
  if (!cursor.dropped || !row) return
  cursor.dropped.push({ line: row.line, body: row.body, why: why })
}

// 解析器没收下的行 → 交给页面的一行物证（没有就 null）。
// 为什么要它：解析器少读几条事件时界面上的步数是错的但看不出来；宁可说"可能不完整"。
function anomalyOf(stats) {
  const dropped = (stats && stats.dropped) || []
  const unbalanced = (stats && stats.unbalanced) || []
  if (!dropped.length && !unbalanced.length) return null
  return {
    dropped: dropped.length,
    firstLine: dropped.length ? (dropped[0].line || null) : (unbalanced[0] || null),
    sample: dropped.length ? String(dropped[0].body || '').slice(0, 80) : '',
    unbalancedFlow: unbalanced.length > 0,
  }
}

function parseYaml(text, stats) {
  // 先折算成"去注释 + 带缩进"的行表，再按缩进递归收结构
  const lines = String(text == null ? '' : text).replace(/^\uFEFF/, '').split(/\r?\n/)
  const rows = []
  // 块标量（`output: |` / `reason: >-`）正文里的 `#` 是内容，不是注释：YAML 的注释规则
  // 只在它没落在块标量正文里时成立。逐行去注释的 splitYamlLine 看不到自己在块标量里，
  // 于是这样的正文行被整行吃掉。所以先按缩进判一次块标量区间。
  let blockIndent = null
  const indentOf = (s) => /^[ \t]*/.exec(s)[0].length
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const inBlock = blockIndent !== null && (raw.trim() === '' || indentOf(raw) > blockIndent)
    const line = inBlock ? raw.replace(/\s+$/, '') : splitYamlLine(raw)
    if (!inBlock) {
      const head = line.trim()
      blockIndent = (/(^|[^\s]):\s*[|>][-+]?$/.test(head) || /^-\s*[|>][-+]?$/.test(head))
        ? indentOf(raw) : null
    }
    const body = line.trim()
    if (body === '' || body === '---') continue
    // 缩进只数 ASCII 空格与制表符。别写 `line.length - line.trimStart().length`：
    // `trimStart()` 连 U+00A0 / U+FEFF 一起吃掉，会把这类字符算成缩进。
    rows.push({ indent: /^[ \t]*/.exec(line)[0].length, body: body, raw: line, line: i + 1 })
  }
  // 行内流集合跨行：`- {role: user, step: 1,` + 续行是合法 YAML（长行被折行时就是这样，
  // PyYAML 照收 N 条），而逐行读会把续行整段跳过。这里把未闭合的流集合与后续行并成一行。
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    const from = flowStartIndex(row.body)
    if (from < 0) continue
    let depth = flowBalance(row.body, from)
    if (depth <= 0) continue
    let j = i + 1
    while (depth > 0 && j < rows.length) {
      row.body += ' ' + rows[j].body
      depth = flowBalance(row.body, from)
      j++
    }
    // 括号始终没闭合：这份文件不是合法 YAML（PyYAML 也会拒）。别把后续内容当它的内容吞掉，
    // 如实记一行，让页面说"可能不完整"。
    if (depth > 0 && stats) (stats.unbalanced = stats.unbalanced || []).push(row.line)
    rows.splice(i + 1, j - i - 1)
  }
  if (!rows.length) return {}
  if (stats && !stats.dropped) stats.dropped = []
  const cursor = { rows: rows, i: 0, dropped: (stats && stats.dropped) || [] }
  const doc = readYamlMap(cursor, rows[0].indent)
  for (const left of rows.slice(cursor.i)) markDropped(cursor, left, '解析器没读到')
  return doc
}

function readYamlMap(cursor, indent) {
  const obj = {}
  while (cursor.i < cursor.rows.length) {
    const row = cursor.rows[cursor.i]
    if (row.indent < indent) break
    if (row.indent > indent) { markDropped(cursor, row, '缩进比同层更深的散行'); cursor.i++; continue }
    // 键允许数字开头（生成物按周分组 `2026-W42: {…}`），与 PyYAML 对齐。
    const m = /^([A-Za-z_][A-Za-z0-9_.-]*|[0-9][^\s:]*):(?:\s+(.*))?$/.exec(row.body)
    if (!m) { markDropped(cursor, row, '既不是键值行、也不是序列项'); cursor.i++; continue }
    cursor.i++
    obj[m[1]] = readYamlValue(cursor, indent, m[2] === undefined ? '' : String(m[2]).trim())
  }
  return obj
}

function readYamlValue(cursor, indent, rest) {
  if (rest === '') {
    // 空值：下面有更深缩进 → 嵌套块（序列或映射）；否则空字符串
    if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
      const childIndent = cursor.rows[cursor.i].indent
      return /^-(?:\s|$)/.test(cursor.rows[cursor.i].body)
        ? readYamlSeq(cursor, childIndent)
        : readYamlMap(cursor, childIndent)
    }
    // 序列项与键同缩进：PyYAML 生成的 YAML 就是这个形状（`trace:` 下一行直接 `- role: …`）。
    if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent === indent
      && /^-(?:\s|$)/.test(cursor.rows[cursor.i].body)) return readYamlSeq(cursor, indent)
    return ''
  }
  if (/^[|>][-+]?$/.test(rest)) return readYamlBlockScalar(cursor, indent, rest)
  if (/^-(?:\s|$)/.test(rest)) return yamlScalar(rest.replace(/^-\s*/, ''))
  // 标量续行：值非空时，比本键更深的后续行只能是这个标量的续行。
  if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
    const parts = [rest]
    while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
      parts.push(cursor.rows[cursor.i].body)
      cursor.i++
    }
    return yamlScalar(parts.join('\n'))
  }
  return yamlScalar(rest)
}

function readYamlBlockScalar(cursor, indent, head) {
  // `|` 原样保留换行；`>` 折叠（连续非空行合空格、空行分段）——与 YAML 语义一致
  const literal = head[0] === '|'
  const collected = []
  while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
    collected.push(cursor.rows[cursor.i])
    cursor.i++
  }
  if (!collected.length) return ''
  let baseIndent = collected[0].indent
  for (const r of collected) if (r.indent < baseIndent) baseIndent = r.indent
  const lines = collected.map(r => r.raw.slice(baseIndent))
  if (literal) return lines.join('\n').replace(/\n+$/, '')
  const out = []
  let buf = []
  for (const ln of lines) {
    if (ln.trim() === '') {
      if (buf.length) { out.push(buf.join(' ')); buf = [] }
      out.push('')
    } else {
      buf.push(ln.trim())
    }
  }
  if (buf.length) out.push(buf.join(' '))
  return out.join('\n').replace(/\n+$/, '')
}

function readYamlSeq(cursor, indent) {
  const arr = []
  while (cursor.i < cursor.rows.length) {
    const row = cursor.rows[cursor.i]
    if (row.indent !== indent || !/^-(?:\s|$)/.test(row.body)) break
    const rest = row.body.replace(/^-\s*/, '')
    cursor.i++
    if (rest === '') {
      if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
        const childIndent = cursor.rows[cursor.i].indent
        arr.push(/^-(?:\s|$)/.test(cursor.rows[cursor.i].body)
          ? readYamlSeq(cursor, childIndent)
          : readYamlMap(cursor, childIndent))
      } else {
        arr.push('')
      }
      continue
    }
    if (/^[A-Za-z_][A-Za-z0-9_.-]*:(?:\s|$)/.test(rest)) {
      // 块映射项：dash 行上就是第一个键，其余键缩进更深——把 dash 行还原成同缩进的一行，
      // 与后续行一起按同一层解析（键缩进取实际值，2/4 空格两种写法都吃）
      let keyIndent = indent + 2
      for (let k = cursor.i; k < cursor.rows.length; k++) {
        if (cursor.rows[k].indent <= indent) break
        keyIndent = cursor.rows[k].indent
        break
      }
      const subRows = [{ indent: keyIndent, body: rest, raw: ' '.repeat(keyIndent) + rest, line: row.line }]
      while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
        subRows.push(cursor.rows[cursor.i])
        cursor.i++
      }
      // 子游标共用 dropped：这段收进来的行里若还有没人认领的，如实记下来而不是静默丢掉。
      const sub = { rows: subRows, i: 0, dropped: cursor.dropped }
      arr.push(readYamlMap(sub, keyIndent))
      for (const left of subRows.slice(sub.i)) markDropped(cursor, left, '在本事件内没有归属')
      continue
    }
    // 序列项是标量（普通标量 / 引号标量 / 行内集合）时的续行：比本层更深的后续行只能是
    // 这个标量的续行（YAML 里标量之后不能再跟映射）。不并进来值会被截断，且那几行会被
    // 算成"被丢弃的事件行"——tool_calls 里一条跨行的记录就够误报一次。
    const parts = [rest]
    while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
      parts.push(cursor.rows[cursor.i].body)
      cursor.i++
    }
    if (parts.length > 1) { arr.push(yamlScalar(parts.join('\n'))); continue }
    arr.push(rest[0] === '{' ? parseInlineMap(rest) : yamlScalar(rest))
  }
  return arr
}

function parseInlineMap(text) {
  const obj = {}
  let s = String(text || '').trim()
  if (s.startsWith('{')) s = s.slice(1)
  if (s.endsWith('}')) s = s.slice(0, -1)
  let i = 0
  while (i < s.length) {
    const km = /^\s*([a-zA-Z0-9_]+):\s*/.exec(s.slice(i))
    if (!km) break
    i += km[0].length
    const key = km[1]
    let val = ''
    let depth = 0
    if (s[i] === '"' || s[i] === "'") {
      // 引号内的逗号/花括号不算结构；`\"` 不结束字符串。收完再按 YAML 转义解。
      const quote = s[i]
      let inner = ''
      i++
      while (i < s.length) {
        const ch = s[i]
        if (quote === '"' && ch === '\\') {
          inner += ch + (s[i + 1] === undefined ? '' : s[i + 1])
          i += 2
          continue
        }
        if (ch === quote) { i++; break }
        inner += ch
        i++
      }
      obj[key] = yamlUnquote(quote + inner + quote)
      if (s[i] === ',') i++
      continue
    }
    while (i < s.length) {
      const ch = s[i]
      if (ch === '[' || ch === '{') depth++
      else if (ch === ']' || ch === '}') depth = Math.max(0, depth - 1)
      if (ch === ',' && depth === 0) break
      val += ch
      i++
    }
    // 嵌套的流集合要递归解析：`- {role: user, evidence: {inline: "…", files: […]}}`
    // 里 evidence 与 files 都是结构，不能留成字符串。
    const trimmed = val.trim()
    if (trimmed.startsWith('{')) obj[key] = parseInlineMap(trimmed)
    else if (trimmed.startsWith('[')) obj[key] = yamlScalar(trimmed)
    else obj[key] = yamlUnquote(trimmed)
    if (s[i] === ',') i++
  }
  return obj
}

// ---- 数据归一化（契约 §2.3 / §2.4） ------------------------------------------

const TRUNC_OUTPUT = 8000
const TRUNC_FIELD = 1200
const TRUNC_TOOL = 400
const TRUNC_INLINE = 4000

function cpLen(s) {
  if (!s) return 0
  let n = 0
  for (const _ of s) n++  // eslint-disable-line no-unused-vars
  return n
}

function truncateCp(s, limit) {
  const text = String(s == null ? '' : s)
  if (cpLen(text) <= limit) return text
  let out = ''
  let n = 0
  for (const ch of text) {
    if (n >= limit) break
    out += ch
    n++
  }
  return out
}

function strOrNull(value) {
  if (value === null || value === undefined) return null
  const s = String(value)
  return s.trim() === '' ? null : s
}

// 未识别成字符串/数字的标量（null / 空串 / 字面量 "null"）视为没有
function normalizeCase(value) {
  const s = strOrNull(value)
  if (s === null || s === 'null') return null
  return s
}

function numOrNull(value) {
  if (value === null || value === undefined) return null
  if (String(value).trim() === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function stringList(value) {
  if (value === null || value === undefined) return []
  const arr = Array.isArray(value) ? value : [value]
  const out = []
  for (const item of arr) {
    if (item === null || item === undefined) continue
    if (typeof item === 'object') {
      // trace 里 excluded_cases 可能是 `[{id: …, reason: …}]`。对外是字符串数组，
      // 取 id；没有 id 时退到 JSON（不丢信息）。
      const id = item.id !== undefined ? item.id : item.caseId
      out.push(id !== undefined && id !== null ? String(id) : JSON.stringify(item))
    } else {
      const s = String(item)
      if (s.trim() !== '') out.push(s)
    }
  }
  return out
}

function stringListTrunc(value, limit) {
  return stringList(value).map(x => truncateCp(x, limit))
}

function fieldValue(value) {
  if (value === null || value === undefined) return null
  if (Array.isArray(value)) {
    return value.map(item => {
      if (item === null || item === undefined) return null
      if (typeof item === 'object') return truncateCp(JSON.stringify(item), TRUNC_FIELD)
      return truncateCp(String(item), TRUNC_FIELD)
    })
  }
  if (typeof value === 'object') return truncateCp(JSON.stringify(value), TRUNC_FIELD)
  return truncateCp(String(value), TRUNC_FIELD)
}

// 读取沉淀状态——兼容三种写法：块映射（doc.sedimented 为对象）、内联流映射字符串、纯字符串。
// 对外形状按契约只给 {state, caseId}（trace 里还可能写 inbox_path，客户端不用它）。
function readSedimented(doc) {
  const raw = doc ? doc.sedimented : null
  if (raw && typeof raw === 'object') {
    return {
      state: strOrNull(raw.state),
      caseId: normalizeCase(raw.caseId !== undefined ? raw.caseId : raw.case_id),
    }
  }
  const s = String(raw || '').trim()
  if (!s) return { state: null, caseId: null }
  if (s.startsWith('{')) {
    const parsed = parseInlineMap(s)
    return {
      state: strOrNull(parsed.state),
      caseId: normalizeCase(parsed.caseId !== undefined ? parsed.caseId : parsed.case_id),
    }
  }
  return { state: s, caseId: null }
}

function readFeedback(doc) {
  const raw = doc ? doc.feedback : null
  if (raw && typeof raw === 'object') {
    return {
      case: normalizeCase(raw.case),
      outcome: strOrNull(raw.outcome),
    }
  }
  const s = String(raw || '').trim()
  return { case: null, outcome: s || null }
}

function actionOf(event) {
  if (!event || typeof event !== 'object') return null
  return strOrNull(event.action)
}

function isConclusionAction(action) {
  return action === 'hit' || action === 'miss' || action === 'output' || action === 'attribution'
}

function summarize(doc, file, meta) {
  const safeDoc = doc && typeof doc === 'object' ? doc : {}
  const trace = Array.isArray(safeDoc.trace) ? safeDoc.trace : []
  const stepSet = new Set()
  let hasConclusion = false
  for (const event of trace) {
    if (!event || typeof event !== 'object') continue
    const step = numOrNull(event.step)
    if (step !== null) stepSet.add(step)
    if (isConclusionAction(actionOf(event))) hasConclusion = true
  }
  const info = meta || {}
  return {
    file: file,
    id: normalizeCase(safeDoc.session_id) || String(file || '').replace(/\.yaml$/, ''),
    status: strOrNull(safeDoc.status),
    summary: strOrNull(safeDoc.summary),
    createdAt: strOrNull(safeDoc.created_at),
    updatedAt: strOrNull(safeDoc.updated_at),
    framework: strOrNull(safeDoc.detected_framework),
    platform: strOrNull(safeDoc.detected_platform),
    category: strOrNull(safeDoc.detected_category),
    resolvedAt: strOrNull(safeDoc.resolved_at),
    currentStep: numOrNull(safeDoc.current_step),
    // 产生这条 trace 的 DSH 会话号：画布的「打开会话」用它跳回会话；没有就为空，前端禁用该入口。
    harnessSession: strOrNull(safeDoc.harness_session),
    lastAction: strOrNull(safeDoc.last_action),
    activeCase: normalizeCase(safeDoc.active_case),
    sedimented: readSedimented(safeDoc),
    feedback: readFeedback(safeDoc),
    excludedCases: stringList(safeDoc.excluded_cases),
    eventCount: trace.length,
    stepCount: stepSet.size,
    hasConclusion: hasConclusion,
    sizeBytes: Number.isFinite(info.sizeBytes) ? info.sizeBytes : null,
    version: info.version === undefined || info.version === null ? null : String(info.version),
  }
}

// 事件里被提到顶层字段的键；其余都进 fields（契约 §2.5：未知字段原样保留）
const EVENT_CONSUMED_KEYS = new Set([
  'role', 'step', 'action', 'content', 'output', 'reason', 'note', 'purpose',
  'evidence', 'case', 'candidates', 'considered', 'excluded', 'refs', 'ref_id',
  'parallel_group', 'parallelGroup', 'tool_calls', 'toolCalls', 'sources',
  'primary', 'fallback', 'marked', 'result', 'confidence', 'check', 'verdict',
  'conclusion', 'idx',
])

function normalizeEvidence(raw) {
  if (raw === null || raw === undefined) return null
  if (typeof raw === 'string') {
    return { inline: truncateCp(raw, TRUNC_INLINE), inlineChars: cpLen(raw), files: [], sources: [], missing: null }
  }
  if (typeof raw !== 'object') return null
  const inlineRaw = raw.inline === null || raw.inline === undefined ? '' : String(raw.inline)
  return {
    inline: inlineRaw === '' ? null : truncateCp(inlineRaw, TRUNC_INLINE),
    inlineChars: cpLen(inlineRaw),
    files: stringList(raw.files),
    sources: stringList(raw.sources),
    // 契约里 missing 是字符串；trace 没写时给空串（fixtures 的形态），不编造内容。
    missing: raw.missing === null || raw.missing === undefined ? '' : String(raw.missing),
  }
}

function buildEvent(raw, idx) {
  if (!raw || typeof raw !== 'object') return null
  const role = strOrNull(raw.role)
  const action = actionOf(raw)
  const outputRaw = raw.output === null || raw.output === undefined ? '' : String(raw.output)
  const reasonRaw = raw.reason === null || raw.reason === undefined ? '' : String(raw.reason)
  const contentRaw = raw.content === null || raw.content === undefined ? '' : String(raw.content)
  const evidence = normalizeEvidence(raw.evidence)
  const verdict = {
    primary: strOrNull(raw.primary),
    fallback: strOrNull(raw.fallback),
    marked: strOrNull(raw.marked),
    result: strOrNull(raw.result),
    confidence: strOrNull(raw.confidence),
    check: strOrNull(raw.check),
    verdict: strOrNull(raw.verdict),
  }
  const refs = stringList(raw.refs)
  const refId = normalizeCase(raw.ref_id)
  if (refId !== null && refs.indexOf(refId) < 0) refs.push(refId)
  const sources = stringList(raw.sources)
  if (evidence) for (const src of evidence.sources) if (sources.indexOf(src) < 0) sources.push(src)
  const fields = {}
  for (const key of Object.keys(raw)) {
    // content 只属于 user 事件；agent 事件若写了它，按未知字段原样保留（不要丢）
    if (EVENT_CONSUMED_KEYS.has(key) && !(key === 'content' && role !== 'user')) continue
    fields[key] = fieldValue(raw[key])
  }
  return {
    idx: idx,
    step: numOrNull(raw.step),
    role: role,
    action: action,
    content: role === 'user' && contentRaw !== '' ? truncateCp(contentRaw, TRUNC_OUTPUT) : null,
    output: outputRaw === '' ? null : truncateCp(outputRaw, TRUNC_OUTPUT),
    reason: reasonRaw === '' ? null : truncateCp(reasonRaw, TRUNC_OUTPUT),
    note: strOrNull(raw.note),
    purpose: strOrNull(raw.purpose),
    evidence: evidence,
    case: normalizeCase(raw.case),
    candidates: stringList(raw.candidates),
    considered: stringList(raw.considered),
    excluded: stringList(raw.excluded),
    refs: refs,
    parallelGroup: strOrNull(raw.parallel_group !== undefined ? raw.parallel_group : raw.parallelGroup),
    verdict: verdict,
    toolCalls: stringListTrunc(raw.tool_calls !== undefined ? raw.tool_calls : raw.toolCalls, TRUNC_TOOL),
    sources: sources,
    fields: fields,
    chars: {
      output: cpLen(outputRaw),
      reason: cpLen(reasonRaw),
      content: cpLen(contentRaw),
    },
  }
}

function buildEvents(trace) {
  if (!Array.isArray(trace)) return []
  const out = []
  for (let i = 0; i < trace.length; i++) {
    const event = buildEvent(trace[i], i)
    if (event) out.push(event)
  }
  // idx 是事件在原始 trace 里的下标（客户端按它定位/回放）；空事件也占一个下标位。
  return out
}

function conclusionIndexOf(trace, events) {
  // 结论落点：最后一条 hit / miss / output / attribution（fixture 里就是 last of those）；
  // 显式 `conclusion: true` 的标记优先（老 trace 用写法约定，新 trace 可显式标）。
  let explicit = null
  for (let i = 0; i < (Array.isArray(trace) ? trace.length : 0); i++) {
    const raw = trace[i]
    if (raw && typeof raw === 'object' && raw.conclusion === true) explicit = i
  }
  if (explicit !== null) return explicit
  for (let i = events.length - 1; i >= 0; i--) {
    if (isConclusionAction(events[i].action)) return events[i].idx
  }
  return null
}

// ---- insights（契约 §2.4 末尾 1-9 条） ---------------------------------------

function collectEvidenceStats(events) {
  let inlineChars = 0
  let files = 0
  const missing = []
  for (const event of events) {
    if (!event.evidence) continue
    inlineChars += event.evidence.inlineChars || 0
    files += event.evidence.files.length
    if (event.evidence.missing && missing.indexOf(event.evidence.missing) < 0) missing.push(event.evidence.missing)
  }
  return { inlineChars: inlineChars, files: files, missing: missing }
}

function formatDateTime(iso) {
  const s = String(iso || '')
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(s)
  return m ? m[1] + ' ' + m[2] : s
}

function formatSpan(fromIso, toIso) {
  const from = Date.parse(String(fromIso || ''))
  const to = Date.parse(String(toIso || ''))
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return null
  const seconds = Math.round((to - from) / 1000)
  if (seconds < 60) return '不到 1 分钟'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return minutes + ' 分钟'
  const hours = Math.floor(minutes / 60)
  const restMin = minutes % 60
  if (hours < 24) return restMin ? hours + ' 小时 ' + restMin + ' 分' : hours + ' 小时'
  const days = Math.floor(hours / 24)
  const restHour = hours % 24
  return restHour ? days + ' 天 ' + restHour + ' 小时' : days + ' 天'
}

function buildInsights(input) {
  const summary = input.summary || {}
  const events = Array.isArray(input.events) ? input.events : []
  const insights = []

  // 1. 结论：hit → 命中 case；miss → 知识库未覆盖；否则仍在进行
  const hitEvents = events.filter(e => e.action === 'hit')
  const missEvents = events.filter(e => e.action === 'miss')
  const lastHit = hitEvents.length ? hitEvents[hitEvents.length - 1] : null
  const lastMiss = missEvents.length ? missEvents[missEvents.length - 1] : null
  if (lastHit) {
    const caseId = lastHit.case || summary.activeCase || ''
    let text = lastHit.output
      ? (caseId ? caseId + '：' + truncateCp(lastHit.output, 120) : truncateCp(lastHit.output, 140))
      : (caseId || '已命中 case')
    // 契约规则 1：命中 case + confidence。trace 的 hit 事件把 confidence 写在顶层
    // （样例 insights 没带它，但契约要求；confidence 是原值，照抄不折算）
    const confidence = lastHit.verdict ? lastHit.verdict.confidence : null
    if (confidence) text += '（confidence ' + confidence + '）'
    insights.push({ id: 'conclusion', tone: 'good', title: '结论 · 命中 case', text: text })
  } else if (lastMiss) {
    const text = lastMiss.output ? truncateCp(lastMiss.output, 140) : '知识库未覆盖'
    insights.push({ id: 'conclusion', tone: 'warn', title: '结论 · 知识库未覆盖', text: text })
  } else {
    const concluded = events.filter(e => e.action === 'output' || e.action === 'attribution')
    const last = concluded.length ? concluded[concluded.length - 1] : null
    if (last && last.output) {
      insights.push({ id: 'conclusion', tone: 'info', title: '结论 · 已输出', text: truncateCp(last.output, 140) })
    } else {
      insights.push({ id: 'conclusion', tone: 'neutral', title: '结论 · 仍在进行', text: '还没有命中或未覆盖结论' })
    }
  }

  // 2. 候选漏斗：quickly_check 条数、marked=excluded 数、hit 数
  const checks = events.filter(e => e.action === 'quickly_check')
  if (checks.length) {
    const excluded = checks.filter(e => e.verdict && e.verdict.marked === 'excluded').length
    const funnelText = '核验 ' + checks.length + ' 个 case，排除 ' + excluded + ' 个，'
      + (hitEvents.length ? '命中 ' + hitEvents.length + ' 个' : '无命中')
    insights.push({ id: 'funnel', tone: 'info', title: '候选漏斗', text: funnelText })
  }

  // 3. 并行：同一步事件数最多的一组
  const byStep = new Map()
  for (const event of events) {
    if (event.step === null) continue
    byStep.set(event.step, (byStep.get(event.step) || 0) + 1)
  }
  let bestStep = null
  let bestCount = 0
  for (const step of Array.from(byStep.keys()).sort((a, b) => a - b)) {
    const count = byStep.get(step)
    if (count > bestCount) { bestStep = step; bestCount = count }
  }
  if (bestStep !== null && bestCount >= 2) {
    insights.push({ id: 'parallel', tone: 'neutral', title: '并行展开', text: '第 ' + bestStep + ' 步一次展开 ' + bestCount + ' 个动作' })
  }

  // 4. 证据体量 + 缺证据
  const evidenceStats = collectEvidenceStats(events)
  if (evidenceStats.inlineChars > 0 || evidenceStats.files > 0) {
    const parts = []
    if (evidenceStats.inlineChars > 0) parts.push('内联证据 ' + evidenceStats.inlineChars + ' 字')
    if (evidenceStats.files > 0) parts.push(evidenceStats.files + ' 个文件')
    insights.push({ id: 'evidence', tone: 'info', title: '证据体量', text: parts.join('，') })
  }
  if (evidenceStats.missing.length) {
    insights.push({
      id: 'evidence-missing',
      tone: 'warn',
      title: '证据缺口',
      text: truncateCp(evidenceStats.missing.join('；'), 180),
    })
  }

  // 5. 工作量：tool_calls 条数、source_analysis 步数、reference_lookup 步数
  const toolCallCount = events.reduce((sum, e) => sum + e.toolCalls.length, 0)
  const sourceCount = events.filter(e => e.action === 'source_analysis').length
  const refLookupCount = events.filter(e => e.action === 'reference_lookup').length
  if (toolCallCount || sourceCount || refLookupCount) {
    const parts = []
    if (toolCallCount) parts.push(toolCallCount + ' 次工具调用')
    if (sourceCount) parts.push(sourceCount + ' 段源码分析')
    if (refLookupCount) parts.push(refLookupCount + ' 次先验查照')
    insights.push({ id: 'effort', tone: 'neutral', title: '工作量', text: parts.join('，') })
  }

  // 6. 时间：created_at → updated_at 跨度
  if (summary.createdAt && summary.updatedAt) {
    const span = formatSpan(summary.createdAt, summary.updatedAt)
    if (span !== null) {
      const from = formatDateTime(summary.createdAt)
      const to = formatDateTime(summary.updatedAt)
      const text = summary.createdAt === summary.updatedAt
        ? '创建与最近更新同一时刻（' + from + '），跨度不到 1 分钟'
        : '从 ' + from + ' 到 ' + to + '，跨度 ' + span
      insights.push({ id: 'time', tone: 'neutral', title: '时间跨度', text: text })
    }
  }

  // 7. 闭环：欠回报 / 尚未沉淀
  if (summary.feedback && summary.feedback.outcome === 'pending') {
    insights.push({ id: 'feedback', tone: 'warn', title: '欠回报', text: '已给建议，等待环境里确认是否生效' })
  }
  if (summary.sedimented && summary.sedimented.state === 'none') {
    insights.push({ id: 'sediment', tone: 'neutral', title: '尚未沉淀', text: '结论稳定后可走 /skill:to-postmortem 入库' })
  }

  // 8. 回退/续接
  const resumeEvents = events.filter(e => e.action === 'resume')
  if (resumeEvents.length) {
    const last = resumeEvents[resumeEvents.length - 1]
    const stepText = last.step !== null ? '第 ' + last.step + ' 步' : '此处'
    insights.push({ id: 'resume', tone: 'neutral', title: '续接', text: '诊断被打断后' + stepText + '续接' })
  }

  // 9. 风险：按原文子串判断（不推断）。只认这几种形态，避免把「非 data-loss」
  //    这类否定句当成风险：
  //      · data-loss-risk（连写）
  //      · severity 后紧跟 data-loss（中间只允许 : = 空格 引号 逗号）
  //      · 数据风险 / 先停 / 数据丢失
  //    匹配位置前 3 个字符内出现否定词（非 / 不是 / 并非 / 无 / not+空格）时不算。
  const RISK_PATTERNS = [
    { id: 'data-loss-risk', re: /data-loss-risk/gi },
    { id: 'severity-data-loss', re: /severity[\s:=,"']*data-loss/gi },
    { id: '数据风险', re: /数据风险/g },
    { id: '先停', re: /先停/g },
    { id: '数据丢失', re: /数据丢失/g },
  ]
  const NEGATIONS = ['非', '不是', '并非', '无']
  const negatedAt = (text, index) => {
    const before3 = text.slice(Math.max(0, index - 3), index)
    if (NEGATIONS.some((word) => before3.indexOf(word) >= 0)) return true
    // `not ` 占 4 个字符（n o t 空格），单独按 4 字符窗口判
    return text.slice(Math.max(0, index - 4), index).endsWith('not ')
  }
  const riskHits = []
  for (const event of events) {
    if (!event.output) continue
    for (const pattern of RISK_PATTERNS) {
      pattern.re.lastIndex = 0
      let match
      while ((match = pattern.re.exec(event.output)) !== null) {
        if (!negatedAt(event.output, match.index)) {
          if (!riskHits.some((hit) => hit.id === pattern.id)) {
            riskHits.push({ id: pattern.id, word: match[0], step: event.step, action: event.action })
          }
        }
        // 零宽匹配不会出现（每个 pattern 都至少吃一个字符），但保险起见推进一位
        if (match[0].length === 0) pattern.re.lastIndex++
      }
    }
  }
  if (riskHits.length) {
    const first = riskHits[0]
    const where = (first.step !== null ? '第 ' + first.step + ' 步' : '') + (first.action ? (first.step !== null ? ' ' : '') + first.action : '')
    const words = riskHits.map((hit) => truncateCp(hit.word.trim(), 40))
    insights.push({
      id: 'risk',
      tone: 'risk',
      title: '风险',
      text: '输出含「' + words.join('」「') + '」' + (where ? '（' + where + '）' : ''),
    })
  }

  return insights
}

// ---- 服务访问与数据目录解析（契约 §2.1） ---------------------------------------

function serviceGet(ctx, name) {
  try {
    return ctx.get(name)
  } catch (e) {
    return undefined
  }
}

function targetPath(target) {
  if (target === null || target === undefined) return ''
  if (typeof target === 'string') return target
  return String(target.displayPath || target.path || '')
}

function isNotFound(error) {
  if (!error) return false
  if (error.code === 'FS_NOT_FOUND' || error.code === 'ENOENT') return true
  return /not found|no such file|ENOENT/i.test(String(error.message || ''))
}

async function resolveSafe(fs, path, cwd) {
  try {
    return await fs.resolve(path, cwd === undefined ? {} : { cwd: cwd })
  } catch (e) {
    return null
  }
}

async function statSafe(fs, target) {
  try {
    const info = await fs.stat(target)
    return info || null
  } catch (e) {
    return null
  }
}

async function listDirSafe(fs, target) {
  try {
    const entries = await fs.listDir(target)
    return { entries: Array.isArray(entries) ? entries : [] }
  } catch (e) {
    return { error: e }
  }
}

function isFileInfo(info) {
  if (!info) return false
  return info.type === undefined || info.type === 'file' || info.type === 'symlink'
}

function sizeOfInfo(info) {
  if (!info) return null
  const candidates = [info.size, info.bytes, info.sizeBytes, info.sizeBytesUtf8]
  for (const value of candidates) if (typeof value === 'number' && Number.isFinite(value)) return value
  return null
}

async function readTextSafe(fs, target) {
  try {
    const text = await fs.readText(target)
    return { text: String(text === null || text === undefined ? '' : text) }
  } catch (e) {
    return { error: e }
  }
}

async function collectCwds(ctx, sessionId) {
  const cwds = []
  const push = (value) => {
    const s = value === null || value === undefined ? '' : String(value)
    if (s && cwds.indexOf(s) < 0) cwds.push(s)
  }
  const sessions = serviceGet(ctx, 'sessions')
  if (!sessions) return cwds
  if (sessionId) {
    try {
      const session = await sessions.get(String(sessionId))
      push(session && session.header ? session.header.cwd : undefined)
    } catch (e) { /* 会话拿不到就继续用列表 */ }
  }
  try {
    const list = await sessions.list()
    const arr = Array.isArray(list) ? list : (list && Array.isArray(list.sessions) ? list.sessions : [])
    for (const session of arr) push(session && session.header ? session.header.cwd : undefined)
  } catch (e) { /* 列表拿不到就用已收集的 */ }
  return cwds
}

// 向上找仓库根时最多看几级父目录（cwd 本身算第 0 级）。
const MAX_ANCESTOR_DEPTH = 6

// 纯字符串取父目录（host 半单文件、不引 node:path）。
function parentPath(value) {
  const s = String(value == null ? '' : value).replace(/[\\/]+$/, '')
  if (!s) return null
  const index = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'))
  if (index < 0) return null
  if (index === 0) return '/'
  const parent = s.slice(0, index)
  // Windows 盘根（`C:\a` → `C:`）再往上就没有意义了，返回 null 结束
  if (/^[A-Za-z]:$/.test(parent)) return null
  return parent
}

// cwd 本身 + 最多 MAX_ANCESTOR_DEPTH 级父目录（由近到远）。
function ancestorCandidates(cwd) {
  const out = []
  let current = String(cwd == null ? '' : cwd)
  if (!current) return out
  out.push(current)
  for (let depth = 1; depth <= MAX_ANCESTOR_DEPTH; depth++) {
    const parent = parentPath(current)
    if (!parent || parent === current || out.indexOf(parent) >= 0) break
    out.push(parent)
    current = parent
  }
  return out
}

// 在一个 cwd（或其父目录）里找仓库标记；找不到返回 null。
async function findMarkerRoot(fs, cwd) {
  for (const candidate of ancestorCandidates(cwd)) {
    const marker = await resolveSafe(fs, 'scripts/metrics_health.py', candidate)
    if (marker && isFileInfo(await statSafe(fs, marker))) return candidate
  }
  return null
}

// 在一个 cwd（或其父目录）里找可读的 traces/；找不到返回 null。
async function findTracesRoot(fs, cwd) {
  for (const candidate of ancestorCandidates(cwd)) {
    const traces = await resolveSafe(fs, 'traces', candidate)
    if (!traces) continue
    const listed = await listDirSafe(fs, traces)
    if (!listed.error) return candidate
  }
  return null
}

// 找 ascend-sleuth 仓库根：先按仓库标记（cwd 本身 + 至多 6 级父目录），
// 再退到 traces/ 可读；两层都是「先当前 cwd，再 sessions.list() 里的其它 cwd」。
async function resolveRepo(ctx, sessionId) {
  const fs = serviceGet(ctx, 'fs')
  if (!fs) return { repoPath: null, detected: false, warnings: ['fs 服务不可用：读不到 traces/'] }
  const cwds = await collectCwds(ctx, sessionId)
  if (!cwds.length) {
    const sessions = serviceGet(ctx, 'sessions')
    return {
      repoPath: null,
      detected: false,
      warnings: [sessions ? '当前会话没有工作目录信息：定位不到 ascend-sleuth 检出' : 'sessions 服务不可用：定位不到 ascend-sleuth 检出'],
    }
  }
  // 1. 仓库标记（含向上查找）
  for (const cwd of cwds) {
    const root = await findMarkerRoot(fs, cwd)
    if (root) return { repoPath: root, detected: true, warnings: [] }
  }
  // 2. 退一步：traces/ 可读的目录（含向上查找）
  for (const cwd of cwds) {
    const root = await findTracesRoot(fs, cwd)
    if (root) {
      return { repoPath: root, detected: true, warnings: ['未找到 scripts/metrics_health.py：按 traces/ 所在目录处理'] }
    }
  }
  return { repoPath: null, detected: false, warnings: ['没有 traces 目录：先跑一次诊断'] }
}

function sortSessions(sessions) {
  const ts = (value) => {
    const n = value ? Date.parse(String(value)) : NaN
    return Number.isFinite(n) ? n : null
  }
  sessions.sort((a, b) => {
    const au = ts(a.updatedAt)
    const bu = ts(b.updatedAt)
    if (au !== null || bu !== null) {
      if (au === null) return 1
      if (bu === null) return -1
      if (au !== bu) return bu - au
    }
    const ac = ts(a.createdAt)
    const bc = ts(b.createdAt)
    if (ac !== null || bc !== null) {
      if (ac === null) return 1
      if (bc === null) return -1
      if (ac !== bc) return bc - ac
    }
    return String(a.file).localeCompare(String(b.file))
  })
}

function localIso(date) {
  const pad = (n) => String(n).padStart(2, '0')
  const offset = -date.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const abs = Math.abs(offset)
  return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate())
    + 'T' + pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds())
    + sign + pad(Math.floor(abs / 60)) + ':' + pad(abs % 60)
}

function rpcError(code, message) {
  const error = new Error(message)
  error.code = code
  return error
}

// 把 evidence.files 里的相对路径换算成 {name, bytes}。读不到大小就给 null 并记 warning。
async function collectEvidenceFiles(ctx, repoPath, trace) {
  const fs = serviceGet(ctx, 'fs')
  const out = []
  const warnings = []
  const seen = new Set()
  if (!fs || !Array.isArray(trace)) return { files: out, warnings: warnings }
  for (const event of trace) {
    if (!event || typeof event !== 'object' || !event.evidence) continue
    for (const rel of stringList(event.evidence.files)) {
      const name = rel.split('/').pop() || rel
      if (seen.has(name)) continue
      seen.add(name)
      const target = await resolveSafe(fs, rel, repoPath)
      const info = target ? await statSafe(fs, target) : null
      if (!info || !isFileInfo(info)) {
        out.push({ name: name, bytes: null })
        warnings.push('证据文件不存在: ' + rel)
        continue
      }
      let bytes = sizeOfInfo(info)
      if (bytes === null && target) {
        const read = await readTextSafe(fs, target)
        if (!read.error) bytes = Buffer.byteLength(read.text, 'utf8')
      }
      out.push({ name: name, bytes: bytes })
    }
  }
  return { files: out, warnings: warnings }
}

function anomalyWarning(file, stats) {
  const anomaly = anomalyOf(stats)
  if (!anomaly) return null
  const parts = ['解析可能不完整: ' + file]
  if (anomaly.dropped) parts.push(anomaly.dropped + ' 行未识别' + (anomaly.firstLine ? '（首行 ' + anomaly.firstLine + '）' : ''))
  if (anomaly.unbalancedFlow) parts.push('存在未闭合的行内集合')
  return parts.join('，')
}

// 一份 trace 至少要解析出一个非空映射。空文件、根是序列、或行内集合没闭合的文件
// （PyYAML 会直接拒）都算解析失败：跳过它并记文件名，不拖垮整张列表。
function isUsableDoc(doc, stats) {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return false
  if (Object.keys(doc).length === 0) return false
  if (stats && Array.isArray(stats.unbalanced) && stats.unbalanced.length) return false
  return true
}

// ---- host 主对象 -----------------------------------------------------------

function createHost(ctx) {
  const summaryCache = new Map() // `${repoPath}\u0000${file}` → {version, item}

  async function collectTraces(repoPath, warnings) {
    const fs = serviceGet(ctx, 'fs')
    const tracesPath = repoPath + '/traces'
    const tracesTarget = await resolveSafe(fs, tracesPath)
    if (!tracesTarget) {
      warnings.push('没有 traces 目录：先跑一次诊断')
      return { entries: [], target: null, fs: fs }
    }
    const listed = await listDirSafe(fs, tracesTarget)
    if (listed.error) {
      warnings.push(isNotFound(listed.error)
        ? '没有 traces 目录：先跑一次诊断'
        : 'traces 目录不可读: ' + String((listed.error && listed.error.message) || listed.error))
      return { entries: [], target: tracesTarget, fs: fs }
    }
    return { entries: listed.entries, target: tracesTarget, fs: fs }
  }

  async function list(payload) {
    const sessionId = payload && payload.sessionId ? String(payload.sessionId) : undefined
    const generatedAt = localIso(new Date())
    const warnings = []
    const repo = await resolveRepo(ctx, sessionId)
    for (const warning of repo.warnings) warnings.push(warning)
    const result = {
      repo: { path: repo.repoPath, detected: !!repo.detected },
      generatedAt: generatedAt,
      warnings: warnings,
      sessions: [],
    }
    if (!repo.repoPath) return result

    const fs = serviceGet(ctx, 'fs')
    const collected = await collectTraces(repo.repoPath, warnings)
    const entries = collected.entries
    const repoPath = repo.repoPath
    const keep = new Set()
    for (const entry of entries) {
      const name = entry && entry.name ? String(entry.name) : ''
      if (!name || !name.endsWith('.yaml') || name.startsWith('.')) continue
      if (!TRACE_FILE_RE.test(name)) continue // 名字不合规的 trace 无法进 detail（安全约束），列表也不给
      keep.add(name)
      const version = entry.version === undefined || entry.version === null ? null : String(entry.version)
      const cacheKey = repoPath + '\u0000' + name
      const cached = summaryCache.get(cacheKey)
      if (cached && version !== null && cached.version === version) {
        result.sessions.push(cached.item)
        continue
      }
      const target = await resolveSafe(fs, name, tracesPathOf(repoPath))
      if (!target) { warnings.push('读不到 trace，已跳过: ' + name); continue }
      const read = await readTextSafe(fs, target)
      if (read.error) { warnings.push('读不到 trace，已跳过: ' + name); continue }
      try {
        const stats = {}
        const doc = parseYaml(read.text, stats)
        if (!isUsableDoc(doc, stats)) {
          warnings.push('解析失败，已跳过: ' + name)
          continue
        }
        let sizeBytes = typeof entry.size === 'number' && Number.isFinite(entry.size) ? entry.size : null
        if (sizeBytes === null) {
          const info = await statSafe(fs, target)
          sizeBytes = sizeOfInfo(info)
        }
        if (sizeBytes === null) sizeBytes = Buffer.byteLength(read.text, 'utf8')
        const item = summarize(doc, name, { sizeBytes: sizeBytes, version: version })
        summaryCache.set(cacheKey, { version: version, item: item })
        const warning = anomalyWarning(name, stats)
        if (warning) warnings.push(warning)
        result.sessions.push(item)
      } catch (e) {
        warnings.push('解析失败，已跳过: ' + name)
      }
    }
    // 剪掉已经不在目录里的 trace，避免缓存无限长
    const prefix = repoPath + '\u0000'
    for (const key of Array.from(summaryCache.keys())) {
      if (key.startsWith(prefix) && !keep.has(key.slice(prefix.length))) summaryCache.delete(key)
    }
    sortSessions(result.sessions)
    return result
  }

  function tracesPathOf(repoPath) {
    return repoPath + '/traces'
  }

  async function detail(payload) {
    const file = payload && payload.file !== undefined && payload.file !== null ? String(payload.file) : ''
    if (!TRACE_FILE_RE.test(file)) {
      throw rpcError('bad-request', 'file 参数必须是 traces/ 下的 .yaml 文件名')
    }
    const sessionId = payload && payload.sessionId ? String(payload.sessionId) : undefined
    const warnings = []
    const repo = await resolveRepo(ctx, sessionId)
    for (const warning of repo.warnings) warnings.push(warning)
    const empty = {
      file: file,
      session: null,
      summary: null,
      lastAction: null,
      excludedCases: [],
      activeCase: null,
      sedimented: { state: null, caseId: null },
      feedback: { case: null, outcome: null },
      conclusionIndex: null,
      insights: [],
      evidenceFiles: [],
      warnings: warnings,
      events: [],
    }
    if (!repo.repoPath) return empty

    const fs = serviceGet(ctx, 'fs')
    const target = await resolveSafe(fs, file, tracesPathOf(repo.repoPath))
    if (!target) throw rpcError('not-found', '读不到 trace: ' + file)
    const read = await readTextSafe(fs, target)
    if (read.error) {
      if (isNotFound(read.error)) throw rpcError('not-found', '读不到 trace: ' + file)
      throw rpcError('internal', '读 trace 失败: ' + String((read.error && read.error.message) || read.error))
    }
    const stats = {}
    const doc = parseYaml(read.text, stats)
    if (!isUsableDoc(doc, stats)) {
      throw rpcError('internal', 'trace 解析失败: ' + file)
    }
    // 找到 listDir 里的 version（拿不到就是 null，不影响内容）
    let version = null
    let sizeBytes = null
    const tracesTarget = await resolveSafe(fs, tracesPathOf(repo.repoPath))
    if (tracesTarget) {
      const listed = await listDirSafe(fs, tracesTarget)
      if (!listed.error) {
        for (const entry of listed.entries) {
          if (entry && String(entry.name) === file) {
            version = entry.version === undefined || entry.version === null ? null : String(entry.version)
            if (typeof entry.size === 'number' && Number.isFinite(entry.size)) sizeBytes = entry.size
            break
          }
        }
      }
    }
    if (sizeBytes === null) sizeBytes = Buffer.byteLength(read.text, 'utf8')
    const summary = summarize(doc, file, { sizeBytes: sizeBytes, version: version })
    const events = buildEvents(doc.trace)
    const conclusionIndex = conclusionIndexOf(doc.trace, events)
    const evidence = await collectEvidenceFiles(ctx, repo.repoPath, doc.trace)
    for (const warning of evidence.warnings) warnings.push(warning)
    const warning = anomalyWarning(file, stats)
    if (warning) warnings.push(warning)
    const insights = buildInsights({ summary: summary, events: events })
    return {
      file: file,
      session: summary,
      summary: summary.summary,
      lastAction: summary.lastAction,
      excludedCases: summary.excludedCases,
      activeCase: summary.activeCase,
      sedimented: summary.sedimented,
      feedback: summary.feedback,
      conclusionIndex: conclusionIndex,
      insights: insights,
      evidenceFiles: evidence.files,
      warnings: warnings,
      events: events,
    }
  }

  return { list: list, detail: detail }
}

// ---- 路由（照抄 dsh-sleuth-panels/lib/index.js 末尾的 prefix route 适配层） -----

export function apply(ctx) {
  const host = createHost(ctx)
  const handlers = new Map()
  handlers.set('list', (payload) => host.list(payload))
  handlers.set('detail', (payload) => host.detail(payload))

  if (typeof ctx.inject !== 'function') {
    console.error('[sleuth-canvas] ctx.inject 不可用，RPC 路由未注册')
    return () => { handlers.clear() }
  }

  // 一条 prefix HTTP 路由承载 list / detail 两个端点（模板见文件头来源说明）。
  const registerRoute = (webCtx) => {
    const dispose = webCtx.effect(() => webCtx.webServer.register({
      kind: 'prefix',
      path: CHANNEL,
      handler: async (req, res) => {
        if (req.method !== 'POST') {
          res.setHeader('Allow', 'POST')
          res.writeHead(405)
          res.end()
          return
        }
        // connection 服务缺席/不在本 ctx 时跳过鉴权（契约「缺失时优雅退化」）
        let rejection
        try {
          rejection = webCtx.get('connection')?.requestRejection?.(req)
        } catch (e) {
          rejection = undefined
        }
        if (rejection !== undefined) {
          res.writeHead(rejection)
          res.end(rejection === 401 ? 'unauthorized' : 'forbidden')
          return
        }
        const chunks = []
        let received = 0
        for await (const chunk of req) {
          received += chunk.length
          if (received > MAX_BODY_BYTES) {
            res.writeHead(413)
            res.end('payload too large')
            return
          }
          chunks.push(chunk)
        }
        let body
        try {
          body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        } catch (e) {
          res.writeHead(400)
          res.end('body is not JSON')
          return
        }
        const rawPath = new URL(req.url === undefined ? '/' : req.url, 'http://localhost').pathname
        const pathEndpoint = rawPath.startsWith(CHANNEL + '/') ? rawPath.slice(CHANNEL.length + 1) : ''
        // 端点优先取 URL；客户端也把端点写在 body.method 里，作为回退
        const endpoint = pathEndpoint !== '' ? pathEndpoint : (typeof body.method === 'string' ? body.method : '')
        const fn = handlers.get(endpoint)
        let result
        if (fn === undefined) {
          result = { ok: false, error: { code: 'not-found', message: '未知的 RPC 端点: ' + endpoint, details: {} } }
        } else {
          try {
            const payload = body === undefined || body.payload === undefined ? {} : body.payload
            result = { ok: true, value: await fn(payload) }
          } catch (e) {
            const code = e && e.code ? String(e.code) : 'internal'
            result = { ok: false, error: { code: code, message: String((e && e.message) || e), details: {} } }
          }
        }
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ type: 'server-response', rpcId: body === undefined ? undefined : body.rpcId, result }))
      },
    }), 'sleuth-canvas: ' + CHANNEL + ' rpc route')
    console.error('[sleuth-canvas] RPC 路由已注册: ' + CHANNEL)
    return dispose
  }

  try {
    ctx.inject(['webServer'], registerRoute)
  } catch (e) {
    console.error('[sleuth-canvas] webServer 服务不可用，RPC 路由未注册: ' + String((e && e.message) || e))
  }

  return () => { handlers.clear() }
}

// 测试入口：纯函数与读侧对象都从这里取，node 直跑 test/host.test.mjs。
export const __test = {
  CHANNEL: CHANNEL,
  MAX_BODY_BYTES: MAX_BODY_BYTES,
  TRACE_FILE_RE: TRACE_FILE_RE,
  // YAML
  parseYaml: parseYaml,
  splitYamlLine: splitYamlLine,
  yamlScalar: yamlScalar,
  yamlUnquote: yamlUnquote,
  parseInlineMap: parseInlineMap,
  flowStartIndex: flowStartIndex,
  flowBalance: flowBalance,
  readYamlMap: readYamlMap,
  readYamlValue: readYamlValue,
  readYamlSeq: readYamlSeq,
  anomalyOf: anomalyOf,
  isUsableDoc: isUsableDoc,
  // 归一化
  summarize: summarize,
  buildEvents: buildEvents,
  buildInsights: buildInsights,
  conclusionIndexOf: conclusionIndexOf,
  readSedimented: readSedimented,
  readFeedback: readFeedback,
  collectEvidenceStats: collectEvidenceStats,
  // host 对象
  createHost: createHost,
  resolveRepo: resolveRepo,
  parentPath: parentPath,
  ancestorCandidates: ancestorCandidates,
  findMarkerRoot: findMarkerRoot,
  findTracesRoot: findTracesRoot,
  // 常量
  MAX_ANCESTOR_DEPTH: MAX_ANCESTOR_DEPTH,
  TRUNC_OUTPUT: TRUNC_OUTPUT,
  TRUNC_INLINE: TRUNC_INLINE,
}
