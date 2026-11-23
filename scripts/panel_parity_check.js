#!/usr/bin/env node
'use strict'
// panel_parity_check.js —— 面板 host 侧公共逻辑的一致性检查
//
// 为什么需要它：四个插件各有一份"找 Python 解释器"（resolvePython），两个插件各有一份
// YAML 子集解析器，两个插件各有一份"主检出在哪"（mainCheckout）。它们没有共享模块——
// 常驻插件包各自独立安装，旧热加载路径又直接读源文件。没有检查时，改一处漏一处不会报错，
// 只会在某台机器上表现为"面板找不到 Python"或"worktree 路径读错"。
//
// 检查分三层：
//   1. 静态：四份 Python 桥都保留同一组候选解释器与探测语义；两份主检出解析都保留
//      `.git` 目录/文件两种形态。
//   2. 源码：两份 YAML 子集解析器的同名函数逐字一致（去注释与空白后比较）。
//   3. 行为：用同一组输入跑两份 parseInlineMap（引号转义、嵌套映射、流序列），并与
//      索引行的 Python 解析共用一份 fixture——这是跨语言、不能靠源码比较的那一段。
//
// 强度如实写在这里：静态检查证明"关键分支还在"，不证明行为等价；行为只覆盖
// parseInlineMap 与索引行两条接缝。其余函数靠源码比较（比静态强、比行为弱）。

const fs = require('fs')
const path = require('path')
const assert = require('assert')

const ROOT = path.resolve(__dirname, '..')
const failures = []

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8')
}

function check(name, ok, detail) {
  if (!ok) failures.push({ name, detail: detail || '' })
}

// ---- 1. 静态：Python 桥与主检出 ----

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    if (name === 'node_modules' || name === 'test') continue
    const full = path.join(dir, name)
    const stat = fs.statSync(full)
    if (stat.isDirectory()) walk(full, out)
    else if (name.endsWith('.js') || name.endsWith('.mjs')) {
      out.push(path.relative(ROOT, full).split(path.sep).join('/'))
    }
  }
  return out
}

const ALL_JS = walk(path.join(ROOT, 'dsh-plugins')).sort()
const isSource = (rel) => !rel.startsWith('dsh-plugins/dsh-sleuth-panels/lib/')
  && !rel.startsWith('dsh-plugins/dsh-sleuth-canvas/lib/')
const PY_BRIDGE_FILES = ALL_JS.filter((rel) => isSource(rel)
  && /function\s+resolvePython\s*\(/.test(read(rel)))
const MAIN_CHECKOUT_FILES = ALL_JS.filter((rel) => isSource(rel)
  && /function\s+mainCheckout/.test(read(rel)))

for (const rel of PY_BRIDGE_FILES) {
  const text = read(rel)
  check(`${rel}: resolvePython 存在`, /function\s+resolvePython\s*\(/.test(text))
  check(`${rel}: 候选解释器一致`, text.includes("['python3', 'python', 'py -3']"))
  check(`${rel}: 用 --version 探测`, text.includes('--version'))
  check(`${rel}: 认 Python 3.x`, text.includes('Python 3'))
  if (/function\s+looksLikeSpawnFailure/.test(text)) {
    check(`${rel}: spawn 失败判定存在`, /function\s+looksLikeSpawnFailure/.test(text))
  }
}

for (const rel of MAIN_CHECKOUT_FILES) {
  const text = read(rel)
  check(`${rel}: 认 .git 目录形态`, /isDirectory/.test(text))
  check(`${rel}: 认 .git 文件形态`, text.includes('gitdir:'))
  check(`${rel}: 解析 worktrees 路径`, text.includes('worktrees'))
}

// ---- 2. 源码：两份 YAML 子集解析器同名函数一致 ----

const PARSER_FILES = ALL_JS.filter((rel) => isSource(rel)
  && /function\s+parseYaml\s*\(/.test(read(rel)))

const PARSER_FUNCS = [
  'splitYamlLine', 'yamlUnescapeDouble', 'yamlUnquote', 'splitFlow', 'yamlScalar',
  'flowStartIndex', 'flowBalance', 'parseYaml', 'readYamlMap', 'readYamlValue',
  'readYamlBlockScalar', 'readYamlSeq',
]

function sliceToNextFunction(text, name) {
  const m = new RegExp(`^([ \\t]*)(?:async\\s+)?function\\s+${name}\\s*\\(`, 'm').exec(text)
  if (!m) return null
  const indent = m[1]
  const rest = text.slice(m.index + m[0].length)
  const next = new RegExp(`^${indent}(?:async\\s+)?function\\s+`, 'm').exec(rest)
  if (!next) return null
  return text.slice(m.index, m.index + m[0].length + next.index)
}

function sliceByBraces(text, name) {
  const m = new RegExp(`function\\s+${name}\\s*\\(`).exec(text)
  if (!m) return null
  const start = m.index
  let i = text.indexOf('{', m.index + m[0].length)
  if (i < 0) return null
  let depth = 0
  let quote = null
  let escaped = false
  for (; i < text.length; i += 1) {
    const ch = text[i]
    if (quote) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue }
    if (ch === '{') depth += 1
    if (ch === '}') {
      depth -= 1
      if (depth === 0) return text.slice(start, i + 1)
    }
  }
  return null
}

function normalize(src) {
  return String(src || '')
    .replace(/\/\/[^\n]*/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\s+/g, '')
}

const parserTexts = PARSER_FILES.map(read)
for (const name of PARSER_FUNCS) {
  const bodies = parserTexts.map((text) => {
    const sliced = sliceToNextFunction(text, name)
    return normalize(sliced || sliceByBraces(text, name))
  })
  check(`YAML 子集: ${name} 全部源文件一致`,
        bodies.length >= 2 && bodies.every((body) => body && body === bodies[0]),
        '发现式列出的源文件里，同名函数正文不同')
}

// ---- 3. 行为：parseInlineMap 与索引行 ----

function sliceUntil(text, name, marker) {
  const m = new RegExp(`function\\s+${name}\\s*\\(`).exec(text)
  if (!m) return null
  const end = text.indexOf(marker, m.index)
  if (end < 0) return null
  return text.slice(m.index, end).trim()
}

const INLINE_END = {
  panel: 'const tool = harness.defineTool(',
  canvas: '// ---- 数据归一化',
}

function inlineMapParser(text, key) {
  const names = ['yamlUnescapeDouble', 'yamlUnquote', 'splitFlow', 'yamlScalar']
  const parts = names.map((name) => sliceToNextFunction(text, name) || sliceByBraces(text, name))
  parts.push(sliceUntil(text, 'parseInlineMap', INLINE_END[key]))
  if (parts.some((p) => !p)) return null
  // eslint-disable-next-line no-new-func
  return new Function(`${parts.join('\n')}\nreturn parseInlineMap;`)()
}

const panelRel = PARSER_FILES.find((rel) => rel.includes('ascend-panel/panel-host.js'))
const canvasRel = PARSER_FILES.find((rel) => rel.includes('dsh-sleuth-canvas/host/index.js'))
check('YAML 子集: 找到面板与 canvas 源文件', Boolean(panelRel && canvasRel))

const INLINE_FIXTURE = '{ title: "line\\nnext", nested: { x: 1, ys: [1, 2] }, quote: "say \\"hi\\"" }'
const parsers = [panelRel ? inlineMapParser(read(panelRel), 'panel') : null,
  canvasRel ? inlineMapParser(read(canvasRel), 'canvas') : null]
check('YAML 子集: parseInlineMap 可加载', parsers.every(Boolean))
if (parsers.every(Boolean)) {
  const panel = parsers[0](INLINE_FIXTURE)
  const canvas = parsers[1](INLINE_FIXTURE)
  try {
    assert.deepStrictEqual(panel, canvas)
  } catch (e) {
    failures.push({ name: 'YAML 子集: 两份 parseInlineMap 行为一致', detail: e.message })
  }
  check('YAML 子集: 双引号转义按单遍解', panel.title === 'line\nnext', JSON.stringify(panel.title))
  check('YAML 子集: 嵌套映射递归解析', panel.nested && panel.nested.x === '1',
        JSON.stringify(panel.nested))
  check('YAML 子集: 流序列递归解析', Array.isArray(panel.nested && panel.nested.ys),
        JSON.stringify(panel.nested && panel.nested.ys))
  check('YAML 子集: 引号内转义引号', panel.quote === 'say "hi"', JSON.stringify(panel.quote))
}

function panelFlowParser(text) {
  const names = ['yamlUnescapeDouble', 'yamlUnquote', 'splitFlow', 'yamlScalar']
  const parts = names.map((name) => sliceToNextFunction(text, name) || sliceByBraces(text, name))
  parts.push(sliceUntil(text, 'parseInlineMap', INLINE_END.panel))
  const flow = sliceToNextFunction(text, 'parseFlowValue')
  if (parts.some((p) => !p) || !flow) return null
  // eslint-disable-next-line no-new-func
  return new Function(`${parts.join('\n')}\n${flow}\nreturn parseFlowValue;`)()
}

const panelHost = panelRel ? read(panelRel) : ''
const flowParser = panelFlowParser(panelHost)
check('YAML 子集: parseFlowValue 可加载', Boolean(flowParser))
if (flowParser) {
  const flow = flowParser('{a: {b: "x\\ny"}, c: [1, 2]}')
  check('YAML 子集: 嵌套映射不变成 [object Object]',
        Boolean(flow.a) && flow.a.b === 'x\ny', JSON.stringify(flow))
  check('YAML 子集: 流序列保留数组与数字', Array.isArray(flow.c) && flow.c[0] === 1,
        JSON.stringify(flow))
}

const parseListRowSrc = sliceToNextFunction(panelHost, 'parseListRow')
check('索引行: parseListRow 可定位', Boolean(parseListRowSrc))
if (parseListRowSrc) {
  const listFields = /const LIST_FIELDS = new Set\(\[[\s\S]*?\]\)/.exec(panelHost)
  // eslint-disable-next-line no-new-func
  const parseListRow = new Function(
    `${listFields ? listFields[0] : ''}\n${parseListRowSrc}\nreturn parseListRow;`)()
  const line = read('tests/fixtures/index-row.list').trim()
  const expected = JSON.parse(read('tests/fixtures/index-row.expected.json'))
  try {
    assert.deepStrictEqual(parseListRow(line), expected)
    check('索引行: JS 与 fixture 一致', true)
  } catch (e) {
    check('索引行: JS 与 fixture 一致', false, e.message)
  }
}

// ---- 结果 ----

if (failures.length) {
  for (const f of failures) {
    console.error(`✗ ${f.name}${f.detail ? ' :: ' + f.detail : ''}`)
  }
  console.error(`\npanel parity: ${failures.length} 处不一致`)
  process.exitCode = 1
} else {
  console.log(`panel parity: OK（${PY_BRIDGE_FILES.length} 个 Python 桥 / `
    + `${MAIN_CHECKOUT_FILES.length} 个主检出解析 / ${PARSER_FUNCS.length} 个 YAML 子集函数 / 1 条索引行）`)
}
