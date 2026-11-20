// client 半测试：模块形态、两个注册面、纯组件的渲染文本与格式化工具。
// 用 vm + mock React，不依赖 DSH、不碰浏览器；视觉与交互仍要在真机看一眼。

import assert from 'node:assert/strict'
import test from 'node:test'
import vm from 'node:vm'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../lib/client.js', import.meta.url), 'utf8')
const listFixture = JSON.parse(readFileSync(new URL('./fixtures/list.json', import.meta.url), 'utf8'))
const detailFixture = JSON.parse(readFileSync(new URL('./fixtures/detail.json', import.meta.url), 'utf8'))

function makeReact() {
  return {
    createElement(type, props, ...children) {
      return { type, props: props || {}, children }
    },
    useState(value) { return [value, () => {}] },
    useEffect() {},
    useMemo(fn) { return fn() },
  }
}

function loadPlugin() {
  let definition = null
  const documentStub = {
    head: { appendChild() {} },
    createElement() {
      return {
        dataset: {},
        textContent: '',
        remove() {},
        setAttribute() {},
      }
    },
  }
  const context = vm.createContext({
    window: { __ModuleLoader__: { load(value) { definition = value } } },
    document: documentStub,
    console,
  })
  vm.runInContext(src, context, { filename: 'client.js' })
  assert.ok(definition, 'client.js 应调用 window.__ModuleLoader__.load')
  assert.equal(definition.id, 'dsh-rsi-observatory')
  const React = makeReact()
  const plugin = definition.factory((name) => {
    assert.equal(name, 'react')
    return React
  })
  assert.ok(plugin && typeof plugin === 'object')
  return { plugin, documentStub }
}

function render(node) {
  if (node === null || node === undefined || node === false) return []
  if (typeof node === 'string' || typeof node === 'number') return [String(node)]
  if (Array.isArray(node)) return node.flatMap(render)
  const props = Object.assign({}, node.props || {})
  if (node.children && node.children.length) {
    props.children = node.children.length === 1 ? node.children[0] : node.children
  }
  if (typeof node.type === 'function') return render(node.type(props))
  return render(node.children || [])
}

function textOf(node) {
  return render(node).join(' ')
}

test('模块形态与两个注册面', () => {
  const { plugin } = loadPlugin()
  assert.equal(plugin.name, 'dsh-rsi-observatory')
  assert.ok(plugin.inject.includes('slots'))
  assert.ok(plugin.inject.includes('connection'))

  const registered = []
  const slots = {
    inject(name, register) {
      const entry = register()
      registered.push({ name, entry })
      return () => {}
    },
    register(options, component) { return Object.assign({}, options, { component }) },
  }
  const ctx = {
    get(name) { return name === 'slots' ? slots : undefined },
    effect(fn) {
      const dispose = fn()
      return () => { if (typeof dispose === 'function') dispose() }
    },
  }
  const dispose = plugin.apply(ctx)
  assert.equal(typeof dispose, 'function')
  const main = registered.find((item) => item.name === 'main')
  const side = registered.find((item) => item.name === 'sidebar.panellist')
  assert.ok(main, '应注册 main 整页')
  assert.equal(main.entry.key, 'rsi-observatory')
  assert.equal(typeof main.entry.component, 'function')
  assert.ok(side, '应注册侧栏图标')
  assert.equal(side.entry.id, 'rsi-observatory')
  assert.equal(side.entry.order, 50)
  assert.equal(side.entry.label, '实验台')
  dispose()
})

test('判定与缺口的文案映射保留未知枚举原值', () => {
  const { plugin } = loadPlugin()
  const t = plugin.__test
  assert.equal(t.decisionLabel('accept'), '通过')
  assert.equal(t.decisionLabel('reject'), '拒绝')
  assert.equal(t.decisionLabel('insufficient'), '证据不足')
  assert.equal(t.decisionLabel(''), '未记录')
  assert.equal(t.decisionLabel('rejected'), 'rejected')
  assert.equal(t.decisionTone('accept'), 'ok')
  assert.equal(t.decisionTone('reject'), 'bad')
  assert.equal(t.decisionTone('weird'), 'muted')
  assert.equal(t.gapLabel('no_cost'), '缺成本')
  assert.equal(t.gapLabel('custom_gap'), 'custom_gap')
  assert.equal(t.formatScore(0.3333), '0.3333')
  assert.equal(t.formatScore(null), '—')
  assert.equal(t.pairedText({ b: 1, c: 0, n: 9 }), 'b 1 · c 0 · n 9')
  assert.equal(t.formatCost(detailFixture.conclusion), '980000 tok · 9 对')
  assert.equal(t.formatCost({}), '—')
  assert.equal(t.eventKinds(detailFixture.history).join(','), 'experiment')
})

test('空态给出数据源与刷新动作', () => {
  const { plugin } = loadPlugin()
  const text = textOf(plugin.__test.EmptyState({
    source: { backend: 'local', path: '/repo/.s2-replay/evolve/rsi-events.jsonl' },
    onRefresh() {},
  }))
  assert.match(text, /还没有实验记录/)
  assert.match(text, /local/)
  assert.match(text, /rsi-events\.jsonl/)
  assert.match(text, /刷新/)
})

test('错误态原样显示错误文本并给重试', () => {
  const { plugin } = loadPlugin()
  const text = textOf(plugin.__test.ErrorState({
    message: 'error: RecordError: invalid JSON in /x/rsi-events.jsonl line 2',
    onRefresh() {},
  }))
  assert.match(text, /取数失败/)
  assert.match(text, /invalid JSON/)
  assert.match(text, /重试/)
})

test('目录列表跑实验与提案两种模式', () => {
  const { plugin } = loadPlugin()
  const first = listFixture.experiments[0]
  const experiments = textOf(plugin.__test.CatalogList({
    mode: 'experiments', experiments: listFixture.experiments, proposals: [],
    selectedKey: first.eventId, onSelect() {},
  }))
  assert.match(experiments, new RegExp(first.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  assert.match(experiments, /证据不足|通过/)

  const proposals = textOf(plugin.__test.CatalogList({
    mode: 'proposals', experiments: [], proposals: listFixture.proposals,
    selectedKey: '', onSelect() {},
  }))
  assert.match(proposals, new RegExp(listFixture.proposals[0].proposalId))
})

test('阶段派生视图区分有记录与无记录，展开给字段名', () => {
  const { plugin } = loadPlugin()
  const stages = detailFixture.stages
  const closed = textOf(plugin.__test.StageTrack({ stages, openId: '', onToggle() {} }))
  assert.match(closed, /提案/)
  assert.match(closed, /评分/)
  assert.match(closed, /有记录/)
  assert.match(closed, /无记录/)

  const opened = textOf(plugin.__test.StageTrack({ stages, openId: 'propose', onToggle() {} }))
  assert.match(opened, /data\.proposal\.artifact/)
})

test('概览的摘要、判定与执行块', () => {
  const { plugin } = loadPlugin()
  const experiment = listFixture.experiments.find(
    (item) => item.eventId === detailFixture.experiment.eventId,
  )
  assert.ok(experiment, 'fixture 里应有 detail 对应的实验行')
  const summary = textOf(plugin.__test.SummaryStrip({
    experiment: {
      decision: experiment.decision, paired: experiment.paired,
      baselineScore: experiment.baselineScore, candidateScore: experiment.candidateScore,
      rolledBack: experiment.rolledBack,
    },
    conclusion: detailFixture.conclusion,
  }))
  assert.match(summary, /证据不足/)
  assert.match(summary, /9/)

  const decision = textOf(plugin.__test.DecisionPanel({
    experiment: {
      decision: experiment.decision, paired: experiment.paired,
      baselineScore: experiment.baselineScore, candidateScore: experiment.candidateScore,
    },
    conclusion: detailFixture.conclusion,
  }))
  assert.match(decision, /原因/)
  assert.match(decision, /9 条有效样本/)

  const rollout = textOf(plugin.__test.RolloutBlock({ rollout: detailFixture.rollout }))
  assert.match(rollout, /baseline 9/)
  assert.match(rollout, /逐样本成绩不在 RSIStore/)
})

test('提案面板给出改动文件、预期与回滚', () => {
  const { plugin } = loadPlugin()
  const text = textOf(plugin.__test.ProposalPanel({ proposal: detailFixture.proposal }))
  assert.match(text, /skills\/diagnose\/SKILL\.md/)
  assert.match(text, /预期/)
  assert.match(text, /回滚/)
  assert.match(text, /改动 diff/)
})

test('事件流按 kind 过滤并提示截断', () => {
  const { plugin } = loadPlugin()
  const history = detailFixture.history
  const all = textOf(plugin.__test.HistoryList({
    history, kind: 'all', openId: '', onKind() {}, onToggle() {},
  }))
  assert.match(all, /实验记录/)
  assert.match(all, /全部/)

  const filtered = textOf(plugin.__test.HistoryList({
    history, kind: 'decision', openId: '', onKind() {}, onToggle() {},
  }))
  assert.ok(!filtered.includes('实验记录'), '过滤后不应再出现 experiment 行')

  const opened = textOf(plugin.__test.HistoryList({
    history, kind: 'all', openId: history[0].eventId, onKind() {}, onToggle() {},
  }))
  assert.match(opened, /"rolled_back": true/)
})

test('缺口列表可读', () => {
  const { plugin } = loadPlugin()
  const text = textOf(plugin.__test.Gaps({ gaps: ['rolled_back', 'id_collision'] }))
  assert.match(text, /已回滚/)
  assert.match(text, /实验 id 复用/)
})
