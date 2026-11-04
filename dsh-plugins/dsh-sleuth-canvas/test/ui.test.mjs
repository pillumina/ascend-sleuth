// 页面三件套的单元测试：用 vm + fake SC 单独求值 20-model.js / 30-page.js / 40-css.js，
// 不依赖 DSH、不碰 DOM。运行：node test/ui.test.mjs

import assert from 'node:assert/strict'
import test from 'node:test'
import vm from 'node:vm'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const read = (name) => readFile(path.join(root, name), 'utf8')

const [utilSrc, modelSrc, pageSrc, cssSrc, detailRaw, detailAltRaw, listRaw] = await Promise.all([
  read('client-src/05-util.js'),
  read('client-src/20-model.js'),
  read('client-src/30-page.js'),
  read('client-src/40-css.js'),
  read('fixtures/detail-sample.json'),
  read('fixtures/detail-2026-01-04-demo-a2-resume-report.json'),
  read('fixtures/list-sample.json'),
])

const detail = JSON.parse(detailRaw)
const plain = (value) => JSON.parse(JSON.stringify(value))
const detailAlt = JSON.parse(detailAltRaw)
const listSample = JSON.parse(listRaw)

function makeSC() {
  const SC = {}
  const context = vm.createContext({ SC, console })
  vm.runInContext(utilSrc, context, { filename: '05-util.js' })
  assert.equal(typeof SC.util, 'object', '05-util.js 应挂出 SC.util')
  vm.runInContext(modelSrc, context, { filename: '20-model.js' })
  assert.equal(typeof SC.model, 'object', '20-model.js 应挂出 SC.model')
  return { SC, context }
}

const { SC, context } = makeSC()
const model = SC.model

const ACTION_SPEC = {
  intake: { family: 'intake', tone: 'intake', glyph: 'intake', label: '现场', emphasis: 'normal' },
  triage: { family: 'route', tone: 'route', glyph: 'route', label: '分诊', emphasis: 'normal' },
  triage_semantic: { family: 'route', tone: 'route', glyph: 'route', label: '语义分诊', emphasis: 'normal' },
  load_index: { family: 'index', tone: 'index', glyph: 'index', label: '检索', emphasis: 'normal' },
  quickly_check: { family: 'check', tone: 'check', glyph: 'check', label: '核验', emphasis: 'normal' },
  tier3: { family: 'check', tone: 'check', glyph: 'cross', label: 'Tier 3', emphasis: 'normal' },
  reference_lookup: { family: 'book', tone: 'book', glyph: 'book', label: '查先验', emphasis: 'normal' },
  source_analysis: { family: 'code', tone: 'code', glyph: 'code', label: '源码分析', emphasis: 'normal' },
  hit: { family: 'hit', tone: 'hit', glyph: 'hit', label: '命中', emphasis: 'conclusion' },
  miss: { family: 'miss', tone: 'miss', glyph: 'miss', label: '未覆盖', emphasis: 'conclusion' },
  attribution: { family: 'flag', tone: 'flag', glyph: 'flag', label: '归因', emphasis: 'normal' },
  output: { family: 'flag', tone: 'flag', glyph: 'doc', label: '输出结论', emphasis: 'conclusion' },
  resume: { family: 'feedback', tone: 'feedback', glyph: 'loop', label: '续接', emphasis: 'normal' },
  report: { family: 'feedback', tone: 'feedback', glyph: 'doc', label: '报告', emphasis: 'normal' },
  feedback: { family: 'feedback', tone: 'feedback', glyph: 'feedback', label: '回报', emphasis: 'normal' },
  unknown: { family: 'feedback', tone: 'feedback', glyph: 'dot', label: '动作', emphasis: 'normal' },
}

const GLYPHS = [
  'intake', 'route', 'index', 'check', 'spark', 'book', 'code', 'hit', 'miss',
  'flag', 'doc', 'loop', 'resume', 'feedback', 'cross', 'dot',
]

function walkStrings(value, out) {
  if (typeof value === 'string') out.push(value)
  else if (Array.isArray(value)) for (const item of value) walkStrings(item, out)
  else if (value && typeof value === 'object') for (const key of Object.keys(value)) walkStrings(value[key], out)
  return out
}

test('动作分类表覆盖 DESIGN §3（含 user 事件与 unknown 兜底）', () => {
  for (const [key, spec] of Object.entries(ACTION_SPEC)) {
    const entry = model.ACTIONS[key]
    assert.ok(entry, '缺少 action: ' + key)
    assert.equal(entry.family, spec.family, key + ' 家族')
    assert.equal(entry.tone, spec.tone, key + ' 色彩')
    assert.equal(entry.glyph, spec.glyph, key + ' glyph')
    assert.equal(entry.label, spec.label, key + ' 中文标签')
    assert.equal(entry.emphasis, spec.emphasis, key + ' emphasis')
    assert.ok(GLYPHS.includes(entry.glyph), key + ' 使用了契约外 glyph: ' + entry.glyph)
    assert.ok(model.TONES[entry.tone], key + ' 色彩不在调色板里: ' + entry.tone)
  }
})

test('未知 action 落到 feedback / dot，标题保留原值', () => {
  const resolved = model.resolve('weird_action')
  assert.equal(resolved.key, 'weird_action')
  assert.equal(resolved.entry, model.ACTIONS.unknown)

  const described = model.describeEvent({ action: 'weird_action', role: 'agent', step: 2, output: '出现了一个未登记动作。', fields: {} }, detail)
  assert.equal(described.family, 'feedback')
  assert.equal(described.glyph, 'dot')
  assert.equal(described.label, '动作')
  assert.equal(described.title, 'weird_action')
  assert.ok(described.subtitle.startsWith('出现了一个未登记动作'))
  assert.ok(described.meta.includes('step 2'))

  const graph = model.buildGraph({ events: [{ idx: 0, step: 1, role: 'agent', action: 'weird_action', output: 'x' }] })
  assert.equal(graph.nodes[0].glyph, 'dot')
  assert.equal(graph.nodes[0].title, 'weird_action')

  const inspector = model.buildInspector(
    { file: 'fake.yaml', events: [{ idx: 0, step: 1, role: 'agent', action: 'weird_action', output: 'x' }] },
    0,
    graph,
  )
  assert.equal(inspector.title, 'weird_action')
  assert.equal(inspector.sections[0].key, 'what')
})

test('user 事件映射为现场输入（含证据 badges）', () => {
  const ev = detail.events[0]
  const described = model.describeEvent(ev, detail)
  assert.equal(described.family, 'intake')
  assert.equal(described.glyph, 'intake')
  assert.equal(described.title, '现场输入')
  assert.ok(described.subtitle.length > 0)
  assert.ok(described.subtitle.length <= 60)
  assert.equal(described.meta, 'step 1 · 用户')
  const texts = described.badges.map((badge) => badge.text)
  assert.ok(texts.includes('证据 151 字'), 'badges: ' + JSON.stringify(texts))
  assert.ok(texts.includes('2 文件'), 'badges: ' + JSON.stringify(texts))
  assert.ok(texts.includes('1 链接'), 'badges: ' + JSON.stringify(texts))
})

test('triage / load_index / quickly_check 三元组与 verdict badges 符合表', () => {
  const triage = model.describeEvent(detail.events[1], detail)
  assert.equal(triage.title, '分诊 → inference_precision')
  assert.equal(triage.subtitle, 'precision')
  assert.equal(triage.meta, 'step 2 · 路由 inference/vllm-ascend/')

  const loadIndex = model.describeEvent(detail.events[2], detail)
  assert.equal(loadIndex.title, '检索候选')
  assert.equal(loadIndex.subtitle, '41 条 case · inference/vllm-ascend/')
  assert.deepEqual(plain(loadIndex.badges.map((badge) => badge.text)), ['6 候选'])

  const fail = model.describeEvent(detail.events[4], detail)
  assert.equal(fail.title, '核验 VLLM-ASC-9003')
  assert.equal(fail.meta, 'step 4 · 核验')
  assert.deepEqual(plain(fail.badges.map((badge) => badge.text)), ['primary fail', 'fallback pass'])
  assert.equal(fail.badges[0].tone, 'miss')

  const excluded = model.describeEvent(detail.events[3], detail)
  assert.ok(excluded.badges.some((badge) => badge.text === 'marked excluded'))
  assert.ok(excluded.subtitle.length <= 64)
})

test('triage_semantic / hit / attribution / resume 映射（第二份 fixture）', () => {
  const semantic = model.describeEvent(detailAlt.events[5], detailAlt)
  assert.ok(semantic.title.startsWith('语义分诊 → inference/vllm-ascend/'))
  assert.ok(semantic.subtitle.includes('主症状'))

  const hit = model.describeEvent(detailAlt.events[8], detailAlt)
  assert.ok(hit.title.startsWith('命中 '))
  assert.equal(hit.emphasis, 'conclusion')
  assert.ok(hit.badges.some((badge) => badge.text === '置信 0.6'))

  const attribution = model.describeEvent(detailAlt.events[9], detailAlt)
  assert.ok(attribution.title.startsWith('归因 · skill:diagnose'))
  assert.ok(attribution.badges.some((badge) => badge.text === 'execution_error'))

  const resume = model.describeEvent(detailAlt.events[10], detailAlt)
  assert.equal(resume.title, '续接诊断')
  assert.equal(resume.glyph, 'loop')

  const graph = model.buildGraph(detailAlt)
  assert.equal(graph.columns.length, 12)
  assert.equal(graph.nodes.length, 12)
  assert.equal(graph.edges.length, 11)
})

test('buildGraph 与 fixtures/detail-sample.json 一致', () => {
  const graph = model.buildGraph(detail)
  assert.deepEqual(plain(graph.columns.map((column) => column.step)), [1, 2, 3, 4, 5, 6])
  assert.deepEqual(plain(graph.columns.map((column) => column.count)), [1, 1, 1, 7, 3, 2])
  assert.deepEqual(plain(graph.columns.map((column) => column.parallel)), [false, false, false, true, true, true])
  assert.deepEqual(plain(graph.columns.map((column) => column.label)), ['现场', '分诊', '检索', '核验', '查先验', '输出结论'])

  assert.equal(graph.nodes.length, detail.events.length)
  assert.deepEqual(plain(graph.nodes.map((node) => node.col)), [0, 1, 2, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 5, 5])
  assert.deepEqual(
    plain(graph.nodes.filter((node) => node.step === 4).map((node) => node.lane)),
    [0, 1, 2, 3, 4, 5, 6],
  )

  for (const [i, node] of graph.nodes.entries()) {
    assert.equal(node.idx, i)
    assert.equal(typeof node.role, 'string')
    assert.equal(typeof node.accent, 'string')
    assert.ok(node.accent.startsWith('#'))
    assert.equal(typeof node.title, 'string')
    assert.ok(node.title.length > 0)
    assert.equal(typeof node.subtitle, 'string')
    assert.equal(typeof node.meta, 'string')
    assert.ok(Array.isArray(node.badges))
    assert.ok(node.emphasis === 'normal' || node.emphasis === 'conclusion')
    assert.equal(node.accent, model.TONES[node.tone], '节点 ' + i + ' accent 应为家族基准色')
  }

  assert.equal(graph.edges.length, graph.nodes.length - 1)
  graph.edges.forEach((edge, i) => {
    assert.equal(edge.from, i)
    assert.equal(edge.to, i + 1)
    assert.equal(edge.kind, 'main')
  })

  assert.equal(graph.nodes[11].emphasis, 'conclusion', 'hit 应为结论节点')
  assert.equal(graph.nodes[13].emphasis, 'conclusion', 'output / conclusionIndex 应为结论节点')
  assert.equal(graph.nodes[3].emphasis, 'normal')
})

test('空 trace / 缺字段不抛错', () => {
  for (const input of [null, undefined, {}, { events: [] }, { events: null }]) {
    const graph = model.buildGraph(input)
    assert.deepEqual(plain(graph.columns), [])
    assert.deepEqual(plain(graph.nodes), [])
    assert.deepEqual(plain(graph.edges), [])
    assert.equal(graph.meta.eventCount, 0)
  }
  const stats = model.deriveStats({})
  assert.equal(stats.stepCount, null)
  assert.equal(stats.eventCount, 0)
  assert.equal(stats.chips[0].value, '未记录')
  assert.equal(model.buildInspector({ events: [] }, 0), null)
  assert.equal(model.buildInspector({ events: [{ idx: 0 }] }, 3), null)
  assert.equal(model.buildOverview({ events: [] }).insights.length, 0)
})

test('buildInspector：做了什么 / 为什么 / 判据 / 现场证据 / 关联 / 其余字段', () => {
  const quick = model.buildInspector(detail, 4)
  assert.equal(quick.title, '核验 VLLM-ASC-9003')
  assert.equal(quick.step, 4)
  assert.equal(quick.roleLabel, '分析')
  assert.equal(quick.total, 15)
  assert.equal(quick.prev, 3)
  assert.equal(quick.next, 5)
  assert.equal(quick.parallel.count, 7)
  const keys = quick.sections.map((section) => section.key)
  assert.ok(keys.includes('what'), 'sections: ' + keys.join(','))
  assert.ok(keys.includes('why'), 'sections: ' + keys.join(','))
  assert.ok(keys.includes('verdict'), 'sections: ' + keys.join(','))
  const verdict = quick.sections.find((section) => section.key === 'verdict')
  assert.ok(verdict.entries.some((entry) => entry.key === 'primary' && entry.value === 'fail'))
  const why = quick.sections.find((section) => section.key === 'why')
  assert.ok(why.paragraphs.length > 0)
  assert.ok(why.paragraphs.every((paragraph) => Array.from(paragraph).length <= 200))

  const intake = model.buildInspector(detail, 0)
  const evidence = intake.sections.find((section) => section.key === 'evidence')
  assert.ok(evidence, '用户事件应有现场证据分区')
  assert.equal(evidence.inline.chars, 151)
  assert.deepEqual(plain(evidence.files), [
    'traces/evidence/2026-01-02-demo-a3-w8a8-garble/startup.cfg',
    'traces/evidence/2026-01-02-demo-a3-w8a8-garble/sample-output.txt',
  ])
  assert.equal(evidence.collapsed, true)
  assert.ok(evidence.missing.includes('CANN 版本'))
  assert.ok(intake.sections.every((section) => !section.paragraphs || section.paragraphs.every((p) => Array.from(p).length <= 200)))

  const feedback = model.buildInspector(detail, 14)
  assert.equal(feedback.title, '回报结果 · resolved')
  const related = feedback.sections.find((section) => section.key === 'related')
  assert.ok(related.groups.some((group) => group.label === 'case' && group.values[0] === 'VLLM-ASC-9001'))

  const source = model.buildInspector(detailAlt, 6)
  assert.equal(source.title, '源码分析')
  assert.ok(!source.sections.some((section) => section.key === 'fields'), 'repo/ref/files 已被三元组消费，不应重复进其余字段')
  const tools = source.sections.find((section) => section.key === 'tools')
  assert.ok(tools, '续接夹具的 source_analysis 有 3 条 toolCalls')
  assert.equal(tools.items.length, 3)
})

test('deriveStats / buildOverview / sessionMeta 数量现算', () => {
  const stats = model.deriveStats(detail)
  assert.equal(stats.status.label, '已定位')
  assert.equal(stats.status.tone, 'hit')
  assert.deepEqual(plain(stats.chips.map((chip) => chip.key)), ['status', 'framework', 'platform', 'category'])
  assert.equal(stats.stepCount, 6)
  assert.equal(stats.eventCount, 15)
  assert.equal(stats.framework, 'vllm-ascend')
  assert.equal(stats.platform, 'A3-910C')
  assert.equal(stats.category, 'precision')
  assert.equal(stats.hasConclusion, true)
  assert.equal(stats.excludedCount, 2)
  assert.ok(stats.relativeUpdated.length > 0)

  const graph = model.buildGraph(detail)
  const overview = model.buildOverview(detail, graph)
  assert.equal(overview.insights.length, 7)
  assert.ok(overview.insights.every((insight) => ['info', 'good', 'warn', 'risk', 'neutral'].includes(insight.tone)))
  assert.equal(overview.legend.reduce((sum, item) => sum + item.count, 0), 15)
  assert.ok(overview.footnote.includes('traces/2026-01-02-demo-a3-w8a8-garble.yaml'))
  assert.ok(overview.footnote.includes('只读'))

  const meta = model.sessionMeta(detail.session)
  assert.ok(meta.includes('vllm-ascend'))
  assert.ok(meta.includes('A3-910C'))
  assert.ok(meta.includes('6 步'))
  assert.ok(meta.includes('排除 2'))
})

test('applyTones 用主题色覆盖节点与列 accent', () => {
  const graph = model.buildGraph(detail)
  const tones = Object.assign({}, model.TONES, { check: '#123456' })
  const themed = model.applyTones(graph, tones)
  assert.equal(themed.nodes[3].accent, '#123456')
  assert.equal(themed.columns[3].accent, '#123456', '列 accent 取该列第一个节点的家族色')
  assert.equal(themed.nodes[0].accent, tones.intake)
  assert.notEqual(themed, graph)
  assert.equal(graph.nodes[3].accent, model.TONES.check, '不应改动原图')
})

test('生成的文案遵守 DESIGN §6：中文、数量现算、无禁用词、无“多个”', () => {
  const graph = model.buildGraph(detail)
  const inspector = model.buildInspector(detail, 9)
  const overview = model.buildOverview(detail, graph)
  const strings = walkStrings([graph.nodes, graph.columns, inspector, overview, model.deriveStats(detail)], [])
  const banned = /首先|其次|值得注意的是|总而言之|多个|若干/
  for (const value of strings) assert.ok(!banned.test(value), '文案里出现禁用词: ' + value)
})

test('页面 / 模型产物是纯脚本函数体，页面不画 canvas 像素', () => {
  for (const [name, source] of [['20-model.js', modelSrc], ['30-page.js', pageSrc]]) {
    assert.ok(!/^\s*(import|export)\s/m.test(source), name + ' 不能有 import/export')
    assert.ok(!/\brequire\s*\(/.test(source), name + ' 不能有 require()')
    assert.ok(!/^\s*(import|export)\s/m.test(source))
  }
  assert.ok(!/getContext\s*\(/.test(pageSrc), '页面不直接操作 canvas 2d context')
  assert.match(pageSrc, /SC\.host/)
  assert.match(pageSrc, /host\.call\('list'/)
  assert.match(pageSrc, /host\.call\('detail'/)
  assert.match(pageSrc, /SC\.createEngine/)
  assert.match(pageSrc, /SC\.theme\.currentPalette/)
  assert.match(pageSrc, /SC\.model\.buildGraph/)
  assert.ok(!/\bdocument\.(querySelector|getElementById)/.test(pageSrc))
})

test('页面组件求值后挂出 SC.CanvasPage 函数', () => {
  const pageContext = vm.createContext({ SC, console, window: {}, document: {} })
  vm.runInContext(pageSrc, pageContext, { filename: '30-page.js' })
  assert.equal(typeof SC.CanvasPage, 'function')
})

test('40-css.js 契约：调色板 / 容器查询 / 动效三档 / 无 transition: all', () => {
  const cssSC = {}
  const cssContext = vm.createContext({ SC: cssSC, console })
  vm.runInContext(cssSrc, cssContext, { filename: '40-css.js' })
  const css = cssSC.css
  assert.equal(typeof css, 'string')
  assert.ok(css.length > 4000)

  for (const tone of Object.keys(model.TONES)) {
    assert.ok(css.includes('--sc-' + tone + ':'), '缺少语义色 --sc-' + tone)
  }
  assert.ok(css.includes('--sc-space-1:4px'))
  assert.ok(css.includes('--sc-fs-lg:20px'))
  assert.ok(css.includes('--sc-m-fast:120ms'))
  assert.ok(css.includes('--sc-m-base:180ms'))
  assert.ok(css.includes('--sc-m-slow:320ms'))
  assert.match(css, /--sc-font:/)
  assert.match(css, /--sc-mono:/)
  assert.match(css, /container-type:inline-size/)
  assert.match(css, /@container \(max-width:1080px\)/)
  assert.match(css, /@container \(max-width:900px\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
  assert.ok(css.includes('var(--dsw-alias-bg-base'))
  assert.ok(!/transition\s*:\s*all/.test(css), '禁止 transition: all')
  assert.ok(!/transition\s*:\s*all\s/.test(css))

  for (const hook of ['.sc-root{', '.sc-header', '.sc-list', '.sc-stage', '.sc-inspector', '.sc-replay', '.sc-tooltip', '.sc-skel', '.sc-session', '.sc-zoom', '.sc-legend', '.sc-empty-card']) {
    assert.ok(css.includes(hook), '缺少样式: ' + hook)
  }
})

test('底部停靠区：图例 / 提示 / 回放条由同一容器排布，不再各自绝对定位', () => {
  const cssSC = {}
  vm.runInContext(cssSrc, vm.createContext({ SC: cssSC, console }), { filename: '40-css.js' })
  const css = cssSC.css
  // 按选择器取**全部**同名规则：只在第一条上做断言时，末尾再追加一条覆盖规则就能绕过。
  function rules(selector) {
    const out = []
    let from = 0
    let start = css.indexOf(selector + '{', from)
    assert.ok(start >= 0, '缺少样式: ' + selector)
    while (start >= 0) {
      out.push(css.slice(start, css.indexOf('}', start) + 1))
      from = start + 1
      start = css.indexOf(selector + '{', from)
    }
    return out
  }
  function rule(selector) {
    return rules(selector)[0]
  }

  assert.match(rule('.sc-canvas-dock'), /position:absolute/, '停靠区是画布内唯一的底部定位容器')
  assert.match(rule('.sc-canvas-wrap'), /container-type:size/, '覆盖件按画布宽高降级，需要画布自己的容器查询')
  assert.match(rule('.sc-canvas-wrap'), /container-name:sc-canvas/)
  for (const selector of ['.sc-legend', '.sc-hint', '.sc-replay']) {
    for (const body of rules(selector)) {
      assert.doesNotMatch(body, /position:absolute/, selector + ' 应由 .sc-canvas-dock 排布：各自绝对定位正是重叠的成因')
      assert.doesNotMatch(body, /(^|[;{])\s*(left|top|right|bottom)\s*:/, selector + ' 不应再声明定位边：改成停靠区子项后由 grid 排布')
    }
  }
  // 活动态必须占满停靠区主格：不拉伸时轨道会塌到 min-width，刻度文字互压。
  assert.match(rule('.sc-replay.is-active'), /width:100%/, '回放活动态要占满主格')
  const narrow = css.slice(css.indexOf('@container sc-canvas'))
  assert.ok(narrow.length > 0, '应有按画布宽度（容器名 sc-canvas）的降级规则')
  assert.match(narrow, /sc-canvas-dock/, '窄画布下降级的是停靠区本身')
  assert.match(narrow, /max-height:240px/, '画布太矮时要摘掉会顶出上沿的缩放钮')
})

test('fixtures 形状自检：buildGraph 不吃未定义字段', () => {
  const graph = model.buildGraph(detail)
  assert.deepEqual(plain(graph.meta), { stepCount: 6, eventCount: 15, conclusionIndex: 13 })
  assert.ok(context.SC.model === model)
})

// ── 结论卡 / 列表视图 / 导出摘要（纯函数）──────────────────────────────────────

function fixtureGraph(data) {
  return model.applyTones(model.buildGraph(data), model.TONES)
}

test('buildConclusion：output 结论 + 回报/沉淀徽标；缺结论时如实说没写', () => {
  const graph = fixtureGraph(detail)
  const card = model.buildConclusion(detail, graph)
  assert.equal(card.label, '给出结论')
  assert.equal(card.idx, graph.meta.conclusionIndex, '卡片指向画布上的结论节点')
  assert.ok(card.text.length > 0, '结论卡应有正文')
  const badges = card.badges.map((item) => item.text).join('|')
  assert.match(badges, /已回报/)
  assert.match(badges, /已沉淀 VLLM-ASC-9001/)
  assert.equal(card.empty, false)

  const hit = { events: [{ idx: 0, action: 'hit', case: 'VLLM-ASC-9999', output: '签名一致，根因相同', verdict: { confidence: '0.62' } }], conclusionIndex: 0, feedback: { outcome: 'pending' }, sedimented: { state: 'none' }, lastAction: '' }
  const hitCard = model.buildConclusion(hit, fixtureGraph(hit))
  assert.equal(hitCard.label, '命中 case')
  assert.equal(hitCard.title, '命中 VLLM-ASC-9999')
  assert.equal(hitCard.badges.map((item) => item.text).join('|'), '置信 0.62|待回报')

  const miss = { events: [{ idx: 0, action: 'miss', output: '知识库未覆盖' }], conclusionIndex: 0, feedback: {}, sedimented: {}, lastAction: '' }
  assert.equal(model.buildConclusion(miss, fixtureGraph(miss)).label, '知识库未覆盖')

  const empty = { events: [{ idx: 0, action: 'triage', output: 'x' }], conclusionIndex: null, feedback: {}, sedimented: {}, lastAction: '还在定位' }
  const emptyCard = model.buildConclusion(empty, fixtureGraph(empty))
  assert.equal(emptyCard.empty, true)
  assert.equal(emptyCard.label, '结论未记录')
  assert.match(emptyCard.text, /还在定位/)
})

test('结论卡的风险词识别不把「非 data-loss」当风险', () => {
  assert.equal(model.hasRiskText('输出：非 data-loss，可以继续'), false)
  assert.equal(model.hasRiskText('并非数据风险'), false)
  assert.equal(model.hasRiskText('没有 data-loss-risk，可继续'), false)
  assert.equal(model.hasRiskText('不含数据风险'), false)
  assert.equal(model.hasRiskText('未发现数据丢失'), false)
  assert.equal(model.hasRiskText('零数据风险'), false)
  assert.equal(model.hasRiskText('severity: data-loss-risk'), true)
  assert.equal(model.hasRiskText('建议先停训练保留现场'), true)
  const risk = { events: [{ idx: 0, action: 'miss', output: '数据风险，先停' }], conclusionIndex: 0, feedback: {}, sedimented: {}, lastAction: '' }
  assert.ok(model.buildConclusion(risk, fixtureGraph(risk)).badges.some((item) => /风险/.test(item.text)))
})

test('buildTableRows：与事件一一对应，标记含 case / verdict / 证据', () => {
  const graph = fixtureGraph(detail)
  const rows = model.buildTableRows(detail, graph)
  assert.equal(rows.length, detail.events.length)
  assert.deepEqual(rows.map((row) => row.idx), detail.events.map((_, i) => i))
  const checkRow = rows.find((row) => /核验/.test(row.action))
  assert.ok(checkRow, '应有核验行')
  assert.ok(checkRow.marks.some((mark) => /VLLM-ASC-/.test(mark)), '核验行应带 case 标记')
  assert.equal(rows[0].roleLabel, '用户')
})

test('buildExportText：Markdown 摘要含结论 / 洞察 / 过程 / 来源', () => {
  const text = model.buildExportText(detail, fixtureGraph(detail))
  assert.match(text, /^# 诊断旅程 · 2026-01-02-demo-a3-w8a8-garble/)
  assert.match(text, /## 结论 · 给出结论/)
  assert.match(text, /## 洞察/)
  assert.match(text, /## 过程/)
  assert.match(text, /来源：traces\/2026-01-02-demo-a3-w8a8-garble\.yaml · 只读/)
  assert.ok(text.split('\n').length > 15)
})

// ── 页面渲染冒烟：迷你 React（hooks + effect + ref）驱动真实组件树 ──────────────
function createMiniHarness(SC, pageContext) {
  const cells = { states: [], refs: [], memos: [], callbacks: [], effects: [] }
  let cursor = 0
  let pending = false
  const windowStub = pageContext.window
  const listeners = Object.create(null)
  windowStub.matchMedia = function () { return { matches: false, addEventListener: function () {} } }
  windowStub.addEventListener = function (type, handler) { (listeners[type] = listeners[type] || []).push(handler) }
  windowStub.removeEventListener = function (type, handler) {
    listeners[type] = (listeners[type] || []).filter(function (item) { return item !== handler })
  }
  pageContext.setTimeout = setTimeout
  pageContext.clearTimeout = clearTimeout
  pageContext.performance = { now: function () { return Date.now() } }
  pageContext.requestAnimationFrame = function () { return 0 }
  pageContext.cancelAnimationFrame = function () {}

  function sameDeps(a, b) {
    if (!a || !b || a.length !== b.length) return false
    for (let i = 0; i < a.length; i += 1) if (!Object.is(a[i], b[i])) return false
    return true
  }

  function mockNode() {
    return {
      style: {},
      scrollTop: 0,
      clientWidth: 720,
      clientHeight: 480,
      getBoundingClientRect: function () { return { left: 0, top: 0, width: 720, height: 480 } },
      addEventListener: function () {},
      removeEventListener: function () {},
    }
  }

  const React = {
    createElement: function (type, props) {
      const children = Array.prototype.slice.call(arguments, 2)
      return { type: type, props: props || {}, children: children }
    },
    useState: function (init) {
      const i = cursor
      cursor += 1
      if (!(i in cells.states)) cells.states[i] = typeof init === 'function' ? init() : init
      return [cells.states[i], function (next) {
        const prev = cells.states[i]
        const value = typeof next === 'function' ? next(prev) : next
        if (!Object.is(value, prev)) {
          cells.states[i] = value
          pending = true
        }
      }]
    },
    useRef: function (init) {
      const i = cursor
      cursor += 1
      if (!(i in cells.refs)) cells.refs[i] = { current: init }
      return cells.refs[i]
    },
    useMemo: function (fn, deps) {
      const i = cursor
      cursor += 1
      const cell = cells.memos[i]
      if (!cell || !sameDeps(cell.deps, deps)) cells.memos[i] = { deps: deps, value: fn() }
      return cells.memos[i].value
    },
    useCallback: function (fn, deps) {
      const i = cursor
      cursor += 1
      const cell = cells.callbacks[i]
      if (!cell || !sameDeps(cell.deps, deps)) cells.callbacks[i] = { deps: deps, fn: fn }
      return cells.callbacks[i].fn
    },
    useEffect: function (fn, deps) {
      const i = cursor
      cursor += 1
      const cell = cells.effects[i] || {}
      cell.fn = fn
      cell.deps = deps
      cells.effects[i] = cell
      return undefined
    },
  }

  function resolveNode(el, hostNodes) {
    if (el === null || el === undefined || el === false || el === true) return null
    if (typeof el === 'string' || typeof el === 'number') return String(el)
    if (Array.isArray(el)) return el.map(function (item) { return resolveNode(item, hostNodes) }).filter(function (item) { return item !== null })
    if (typeof el.type === 'function') return resolveNode(el.type(el.props), hostNodes)
    if (typeof el.type !== 'string') return null
    hostNodes.push(el)
    if (el.props && el.props.ref && typeof el.props.ref === 'object' && !el.props.ref.current) {
      el.props.ref.current = mockNode()
    }
    el.children = (el.children || []).map(function (child) { return resolveNode(child, hostNodes) }).filter(function (child) { return child !== null })
    return el
  }

  function flushEffects() {
    for (const cell of cells.effects) {
      if (!cell || typeof cell.fn !== 'function') continue
      if (cell.deps !== undefined && cell.prevDeps !== undefined && sameDeps(cell.deps, cell.prevDeps)) continue
      if (cell.prevDeps !== undefined && typeof cell.cleanup === 'function') {
        try { cell.cleanup() } catch (error) { /* 清理失败不阻塞 */ }
        cell.cleanup = null
      }
      cell.prevDeps = cell.deps
      const cleanup = cell.fn()
      if (typeof cleanup === 'function') cell.cleanup = cleanup
    }
  }

  function renderOnce(props) {
    cursor = 0
    const hostNodes = []
    const tree = resolveNode(React.createElement(SC.CanvasPage, props), hostNodes)
    flushEffects()
    return tree
  }

  async function settle(props) {
    let tree = null
    for (let i = 0; i < 40; i += 1) {
      pending = false
      tree = renderOnce(props)
      await Promise.resolve()
      await new Promise(function (resolve) { setTimeout(resolve, 0) })
      if (!pending) return tree
    }
    throw new Error('页面渲染未收敛（state 更新超过 40 轮）')
  }

  function findAll(tree, className) {
    const out = []
    ;(function walk(node) {
      if (node === null || typeof node !== 'object') return
      if (Array.isArray(node)) { node.forEach(walk); return }
      const cls = node.props && typeof node.props.className === 'string' ? node.props.className : ''
      if (cls.split(/\s+/).includes(className)) out.push(node)
      ;(node.children || []).forEach(walk)
    })(tree)
    return out
  }

  function textOf(node) {
    if (node === null || node === undefined) return ''
    if (typeof node === 'string') return node
    if (Array.isArray(node)) return node.map(textOf).join(' ')
    return (node.children || []).map(textOf).join(' ')
  }

  function dispatch(type, event) {
    for (const handler of listeners[type] || []) handler(event)
  }

  function findByProp(tree, prop, value) {
    const out = []
    ;(function walk(node) {
      if (node === null || typeof node !== 'object') return
      if (Array.isArray(node)) { node.forEach(walk); return }
      if (node.props && node.props[prop] === value) out.push(node)
      ;(node.children || []).forEach(walk)
    })(tree)
    return out
  }

  return { React: React, settle: settle, findAll: findAll, findByProp: findByProp, textOf: textOf, dispatch: dispatch, listeners: listeners }
}

test('页面渲染冒烟：list → detail → 选中 → 回放 → Esc 全流程可用', async () => {
  const pageSC = { util: SC.util, model: SC.model }
  pageSC.theme = { currentPalette: function () { return { tones: SC.model.TONES } } }
  const hosts = []
  pageSC.host = {
    call: function (endpoint) {
      hosts.push(endpoint)
      return endpoint === 'list' ? Promise.resolve(listSample) : Promise.resolve(detail)
    },
  }
  const openedSessions = []
  pageSC.openSession = function (id) { openedSessions.push(id); return Promise.resolve() }
  const downloads = []
  const engineCalls = []
  let engineOptions = null
  pageSC.createEngine = function (options) {
    engineOptions = options
    return {
      lastGraph: null,
      setGraph: function (graph) { engineCalls.push(['setGraph', graph]); this.lastGraph = graph },
      setSelected: function (value) { engineCalls.push(['setSelected', value]) },
      setHovered: function (value) { engineCalls.push(['setHovered', value]) },
      setReplay: function (value) { engineCalls.push(['setReplay', value]) },
      setReplayFocus: function (value) { engineCalls.push(['setReplayFocus', value]) },
      flyTo: function (value) { engineCalls.push(['flyTo', value]) },
      fit: function () { engineCalls.push(['fit']) },
      zoomBy: function (value) { engineCalls.push(['zoomBy', value]) },
      resize: function () { engineCalls.push(['resize']) },
      nodeRect: function () { return null },
      exportImage: function () { return 'data:image/png;base64,AAAA' },
      destroy: function () { engineCalls.push(['destroy']) },
    }
  }

  const context = vm.createContext({
    SC: pageSC,
    console: console,
    window: {},
    document: {
      createElement: function (tag) {
        return {
          tag: tag,
          style: {},
          href: '',
          download: '',
          click: function () { downloads.push({ tag: tag, href: this.href, download: this.download }) },
          remove: function () {},
        }
      },
      body: { appendChild: function () {} },
      addEventListener: function () {},
      removeEventListener: function () {},
    },
  })
  vm.runInContext(utilSrc, context, { filename: '05-util.js' })
  vm.runInContext(modelSrc, context, { filename: '20-model.js' })
  vm.runInContext(pageSrc, context, { filename: '30-page.js' })
  const harness = createMiniHarness(pageSC, context)
  pageSC.React = harness.React
  pageSC.h = harness.React.createElement

  const tree = await harness.settle({ sessionId: 'session-1' })
  assert.ok(hosts.includes('list') && hosts.includes('detail'), '应调用 list 与 detail：' + hosts.join(','))
  assert.equal(harness.findAll(tree, 'sc-root').length, 1)
  assert.equal(harness.findAll(tree, 'sc-session').length, 3, '左侧应渲染 3 张会话卡')
  assert.equal(harness.findAll(tree, 'sc-session')[0].props['aria-pressed'], 'true', '默认选中更新时间最新的一单')
  assert.equal(harness.findAll(tree, 'sc-insight').length, detail.insights.length)
  assert.equal(harness.findAll(tree, 'sc-legend-item').length, 8, '图例按家族去重：现场/分诊/检索/核验/先验/命中/归因/收尾')
  assert.equal(harness.findAll(tree, 'sc-replay').length, 1)
  // 三个底部覆盖件必须挂在同一个停靠区里，各占一格；分开绝对定位就会重新叠在一起。
  const dock = harness.findAll(tree, 'sc-canvas-dock')[0]
  assert.ok(dock, '画布应有底部停靠区')
  const dockSide = harness.findAll(dock, 'sc-dock-side')[0]
  const dockMain = harness.findAll(dock, 'sc-dock-main')[0]
  assert.ok(dockSide && dockMain, '停靠区应有左格（提示 + 图例）与主格（回放条）')
  assert.equal(harness.findAll(dockSide, 'sc-legend').length, 1, '图例在左格')
  assert.equal(harness.findAll(dockSide, 'sc-hint').length, 1, '快捷键提示在左格')
  assert.equal(harness.findAll(dockMain, 'sc-replay').length, 1, '回放条在主格')
  assert.ok(harness.textOf(tree).includes('vllm-ascend'))
  assert.ok(harness.textOf(tree).includes('已定位'))
  assert.ok(harness.textOf(tree).includes('诊断画布'))
  assert.equal(harness.findAll(tree, 'sc-conclusion').length, 1, '页头应有结论卡')
  assert.ok(harness.textOf(tree).includes('给出结论'))
  assert.ok(harness.textOf(tree).includes('已沉淀 VLLM-ASC-9001'))

  // 打开会话：按钮使用 trace 的 harness_session
  const openButton = harness.findByProp(tree, 'aria-label', '打开会话')[0]
  assert.ok(openButton, '应有打开会话按钮')
  openButton.props.onClick()
  const openedTree = await harness.settle({ sessionId: 'session-1' })
  assert.deepEqual(openedSessions, ['demo-harness-9001'])
  assert.ok(harness.textOf(openedTree).includes('已切到会话'), '成功回跳应有可见反馈')

  // 导出菜单：点导出按钮展开两项
  const exportButton = harness.findByProp(tree, 'aria-haspopup', 'menu')[0]
  assert.ok(exportButton, '应有导出菜单入口')
  exportButton.props.onClick()
  const menuTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(harness.findAll(menuTree, 'sc-export-item').length, 2)
  const pngItem = harness.findAll(menuTree, 'sc-export-item')[0]
  pngItem.props.onClick()
  const exportedTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(downloads.length, 1, '应触发一次下载')
  assert.equal(downloads[0].download, 'sleuth-canvas-2026-01-04-demo-a2-resume-report.png', '文件名用当前选中的 trace')
  assert.ok(harness.textOf(exportedTree).includes('已导出 PNG'), '导出后应有可见反馈')

  // 't' 切事件列表：行数 = 事件数，点行定位回画布节点
  harness.dispatch('keydown', { key: 't', target: { tagName: 'CANVAS' }, preventDefault: function () {} })
  const tableTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(harness.findAll(tableTree, 'sc-table').length, 1, '应切到事件列表视图')
  assert.equal(harness.findAll(tableTree, 'sc-trow').length, detail.events.length)
  const firstRow = harness.findAll(tableTree, 'sc-trow')[0]
  firstRow.props.onClick()
  const rowTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(harness.findAll(rowTree, 'sc-root')[0].props['data-inspector'], 'open')
  assert.ok(engineCalls.some(function (call) { return call[0] === 'setSelected' && call[1] === 0 }))
  // 回到画布视图
  harness.dispatch('keydown', { key: 't', target: { tagName: 'CANVAS' }, preventDefault: function () {} })
  const backTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(harness.findAll(backTree, 'sc-table').length, 0)
  assert.ok(engineCalls.some(function (call) { return call[0] === 'resize' }), '切回画布应让引擎按新尺寸重算')

  const graph = engineCalls.filter(function (call) { return call[0] === 'setGraph' }).pop()[1]
  assert.equal(graph.nodes.length, 15)
  assert.equal(graph.columns.length, 6)
  assert.equal(engineOptions.reducedMotion, false)

  // 引擎点击节点 → 选中态 + 检查器切到节点详情
  engineOptions.onSelect(3)
  const selectedTree = await harness.settle({ sessionId: 'session-1' })
  assert.ok(harness.textOf(selectedTree).includes('核验 VLLM-ASC-9002'))
  assert.ok(harness.textOf(selectedTree).includes('做了什么'))
  assert.ok(engineCalls.some(function (call) { return call[0] === 'setSelected' && call[1] === 3 }))
  assert.equal(harness.findAll(selectedTree, 'sc-root')[0].props['data-inspector'], 'open')

  // 空格开始回放 → 回放条 + 相机/聚光跟随；Esc 退出
  harness.dispatch('keydown', { key: ' ', target: { tagName: 'CANVAS' }, preventDefault: function () {} })
  const replayTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(harness.findAll(replayTree, 'sc-replay')[0].props.className.includes('is-active'), true)
  assert.ok(harness.textOf(replayTree).includes('回放 1 / 15'))
  assert.ok(engineCalls.some(function (call) { return call[0] === 'setReplay' && call[1] === true }))
  assert.ok(engineCalls.some(function (call) { return call[0] === 'setReplayFocus' && call[1] === 0 }))
  assert.ok(engineCalls.some(function (call) { return call[0] === 'flyTo' && call[1] === 0 }))

  harness.dispatch('keydown', { key: 'Escape', target: { tagName: 'CANVAS' }, preventDefault: function () {} })
  const stoppedTree = await harness.settle({ sessionId: 'session-1' })
  assert.equal(harness.findAll(stoppedTree, 'sc-replay')[0].props.className.includes('is-idle'), true)
  assert.ok(engineCalls.some(function (call) { return call[0] === 'setReplay' && call[1] === false }))
  assert.equal(harness.findAll(stoppedTree, 'sc-root')[0].props['data-inspector'], 'closed')
})
