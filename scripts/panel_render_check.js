// 离线渲染校验：用 mock React + 真实数据跑面板客户端，确认
//  1) 渲染不抛异常
//  2) 关键信息（决策链全文、变化对照、缺口提示）确实出现在输出里
// 不是替代浏览器验证，是把"渲染逻辑 + 数据契约"这一层先钉死。
const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const repo = path.resolve(__dirname, '..')

// ---- mock React ----
function flatten(node, out) {
  if (node === null || node === undefined || node === false || node === true) return
  if (Array.isArray(node)) { node.forEach(n => flatten(n, out)); return }
  if (typeof node === 'string' || typeof node === 'number') { out.push(String(node)); return }
  if (typeof node === 'object' && node.__el) {
    const p = node.props || {}
    if (p.title) out.push('«title:' + p.title + '»')
    if (p.placeholder) out.push('«ph:' + p.placeholder + '»')
    if (p.className) out.push('«cls:' + p.className + '»')
    flatten(p.children, out)
  }
}
let hookIdx = 0
let hookState = []
let effectQueue = []
let cssChunks = []
// effect/callback 的 deps 记账单独一份，避免与 useState 的 slot 混用
let depState = []

// 遍历元素树收集 onClick —— 模拟真实点击（比篡改 hook 状态可信）
function collectHandlers(node, out) {
  if (node === null || node === undefined || typeof node !== 'object') return
  if (Array.isArray(node)) { node.forEach(n => collectHandlers(n, out)); return }
  if (node.__el) {
    if (typeof node.props.onClick === 'function') {
      const o = []
      flatten(node, o)
      out.push({ fn: node.props.onClick, text: o.join(' ') })
    }
    collectHandlers(node.props.children, out)
  }
}
const React = {
  createElement(type, props, ...children) {
    if (typeof type === 'function') {
      const merged = Object.assign({}, props || {})
      if (children.length === 1) merged.children = children[0]
      else if (children.length > 1) merged.children = children
      return type(merged)
    }
    return { __el: true, type, props: Object.assign({}, props || {}, { children: children.length === 1 ? children[0] : children }) }
  },
  Fragment: 'Fragment',
  useState(init) {
    const i = hookIdx++
    if (!(i in hookState)) hookState[i] = typeof init === 'function' ? init() : init
    return [hookState[i], (v) => { hookState[i] = typeof v === 'function' ? v(hookState[i]) : v }]
  },
  // useEffect 同样按 deps 去重：真实 React 只在 deps 变化时重跑；
  // 每次都跑会让 load() 无限触发（把面板"照出"假故障，白白浪费调试时间）
  memo(fn) { return fn },
  useEffect(fn, deps) {
    const i = hookIdx++
    const prev = depState[i]
    const same = prev && Array.isArray(deps) && deps.length === prev.length
      && deps.every((d, k) => Object.is(d, prev[k]))
    if (same) return
    depState[i] = deps
    effectQueue.push(fn)
  },
  // useCallback 必须按 deps 记忆化：否则每次渲染都返回新函数，
  // useEffect(..., [load]) 会无限重跑（真实 React 不会，mock 会——曾把面板"照出"假故障）
  useCallback(fn, deps) {
    const i = hookIdx++
    const prev = depState[i]
    if (prev && prev.fn && Array.isArray(deps) && deps.length === prev.deps.length
        && deps.every((d, k) => Object.is(d, prev.deps[k]))) return prev.fn
    depState[i] = { fn, deps }
    return fn
  },
}

async function renderAsync(clientSrc, slotProps, hostImpl, { settle = 8 } = {}) {
  hookIdx = 0; hookState = []; depState = []; effectQueue = []; cssChunks = []
  const registrations = []
  const ctx = {
    get(name) {
      if (name === 'slots') return {
        inject(slot, cb) { cb() },
        register(opts, comp) { registrations.push({ opts, comp }) },
      }
      if (name === 'styles') return { insert(css) { cssChunks.push(css); return () => {} } }
      return undefined
    },
    effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} },
    on() { return () => {} },
  }
  const host = { call: (m, a) => Promise.resolve(hostImpl(m, a)) }
  const stylesGlobal = { insert(css) { cssChunks.push(css); return () => {} } }
  const plugin = new Function('React', 'host', 'styles', 'return (function(){' + clientSrc + '})()')(React, host, stylesGlobal)
  plugin.apply(ctx)
  if (!registrations.length) throw new Error('未注册任何 slot')
  let out = []
  for (let round = 0; round < settle; round++) {
    effectQueue = []
    hookIdx = 0
    out = []
    registrations.forEach(r => flatten(r.comp(slotProps), out))
    const effects = effectQueue.slice()
    if (!effects.length) break
    effects.forEach(fn => fn())
    await new Promise(res => setImmediate(res))
    await new Promise(res => setImmediate(res))
  }
  return { text: out.join('\n'), regs: registrations }
}

// ---- 真实数据 ----
const board = JSON.parse(execFileSync('python3', ['scripts/ev_board_data.py'], { cwd: repo, maxBuffer: 32 * 1024 * 1024 }).toString())
const detailCache = {}
function detailOf(id) {
  if (!detailCache[id]) {
    detailCache[id] = JSON.parse(execFileSync('python3', ['scripts/ev_board_data.py', '--detail', id], { cwd: repo, maxBuffer: 32 * 1024 * 1024 }).toString())
  }
  return detailCache[id]
}
const periods = JSON.parse(execFileSync('python3', ['-c', `
import yaml, json
d = yaml.safe_load(open('metrics/timeline.yaml', encoding='utf-8'))
print(json.dumps(d['periods'], ensure_ascii=False, default=str))
`], { cwd: repo }).toString())

const failures = []
function expect(name, cond, extra) {
  if (cond) console.log('  ✓ ' + name)
  else { console.log('  ✗ ' + name + (extra ? ' :: ' + String(extra).slice(0, 160) : '')); failures.push(name) }
}

async function main() {
  // ================= 自演进面板 =================
  console.log('\n[ev-panel 自演进 · 列表页]')
  const evSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ev-panel/panel-client.js'), 'utf8')
  const evHost = (method, args) => {
    if (method === 'ev-board-load') return { ok: true, data: board }
    if (method === 'ev-idea-detail') return detailOf(args.ideaId)
    return { ok: false, error: 'unknown ' + method }
  }
  const ev = await renderAsync(evSrc, { sessionId: 'sess-1' }, evHost)
  expect('渲染无异常', true)
  expect('注册 tab「自演进」', ev.regs[0].opts.label === '自演进' && ev.regs[0].opts.id === 'ascend-evolve')
  // 期望值一律从真实数据推导，不硬编码计数/卡号——硬编码会随卡库增长腐烂
  // （2026-09-10 实测：全卡闭合后 "实验中 5 / 审计缺口 3 / EV-2026-034" 全部失真，
  //  且首屏无卡导致后面的点击用例找不到目标而崩溃）
  const nExp = (board.stats && board.stats.by_status && board.stats.by_status.in_experiment) || 0
  const nGap = (board.stats && board.stats.gap_count) || 0
  const nIdeas = board.idea_count
  const validatedNoGap = (board.ideas || []).find(c => c.status === 'validated' && !(c.gaps || []).length)
  expect('标题含卡数（来自数据 ' + nIdeas + '）', new RegExp('EV 卡[\\s\\S]{0,6}' + nIdeas + '[\\s\\S]{0,6}张').test(ev.text), ev.text.slice(0, 120))
  expect('待办条：实验中 ' + nExp, new RegExp('实验中[\\s\\S]{0,60}?' + nExp).test(ev.text))
  expect('待办条：审计缺口 ' + nGap, new RegExp('审计缺口[\\s\\S]{0,60}?' + nGap).test(ev.text))
  expect('v5 状态词「实验中」', ev.text.includes('实验中'))
  expect('v5 状态词「已采纳」', ev.text.includes('已采纳'))
  // v1 词表检查**查声明、不查整页渲染文本**：整页里会带历史数据原文（exec-log 的
  // decision_reason、卡的结论摘要），里面的"候选"是数据不是 UI 状态词——用渲染文本判会把
  // 数据误判成词表回归（2026-09-10 合并后在带 exec-log 的检出上实测假失败：命中来自
  // '拉取 17 / 候选 9 / 评估通过 1' 这条历史记录）。v1 词表当年是 v1 状态机的产物，
  // 因此正确的判据是"状态词声明里没有 v1 词"，加上 v5 词确有渲染（上面两条）。
  const statusVocab = evSrc.slice(evSrc.indexOf('const STATUS_META'), evSrc.indexOf('const AUTH_META'))
  expect('STATUS_META 声明里无 v1 状态词', statusVocab.length > 0 && !/pending_merge|已提议|候选/.test(statusVocab),
    (statusVocab.match(/pending_merge|已提议|候选/) || [])[0])
  // 缺口 pill 只在真有缺口卡时出现（数据驱动；无缺口时不该硬渲染关键词）
  // 首屏三态（数据驱动，别把"无缺口"当成"无卡"——演练场里就有 in_experiment 卡）
  if (nGap > 0) {
    expect('缺口 pill「缺成本」或「状态滞后」', /缺成本|状态滞后/.test(ev.text))
    expect('缺口卡 id 出现', (board.stats.gap_cards || []).some(id => ev.text.includes(id)))
  } else if (nExp > 0) {
    expect('有实验中的卡时首屏出卡（' + nExp + ' 张）', /«cls:ev-card/.test(ev.text))
  } else {
    expect('无待办卡时首屏明示「无待办卡」', ev.text.includes('无待办卡'))
  }
  // 用 ev-card class 判"首屏有没有卡"，不要用 "共 N 条" 这类文案——执行现场区块也有"共 N 条"
  // （2026-09-10 演练场实测：文案匹配把 exec-log 区块的计数误当成卡片，断言假失败）
  if (nExp + nGap > 0) expect('有待办卡时首屏出卡', /«cls:ev-card/.test(ev.text))
  else expect('无待办卡时首屏不渲染卡（不空转）', !/«cls:ev-card/.test(ev.text))
  expect('自演进度量：采纳率', /采纳率/.test(ev.text))
  expect('自演进度量：验证方式分布', /验证方式分布/.test(ev.text) && /S2 issue 回放/.test(ev.text))
  expect('信号来源分布', /信号来源/.test(ev.text))
  // 容量压力：从真实容量表里取最紧的那一格做断言（不硬编码 84/30）
  const capCells = []
  Object.keys(board.capacity || {}).forEach(ns => Object.keys(board.capacity[ns] || {}).forEach(cat => {
    const c = board.capacity[ns][cat]
    capCells.push({ label: c.count + '/' + c.cap, ratio: c.cap ? c.count / c.cap : 0 })
  }))
  const tightest = capCells.sort((a, b) => b.ratio - a.ratio)[0]
  if (tightest && tightest.ratio > 0.8) expect('容量压力出现最紧格子 ' + tightest.label, ev.text.includes(tightest.label), (ev.text.match(/\d+\/30/g) || []).join(','))
  expect('timeline sparkline', /routed_accuracy/.test(ev.text))
  expect('空区块不占位（tally 空 → 一行说明）', /暂无归因事件/.test(ev.text))
  expect('收起态不泄露完整决策链（长文本仅在展开后）', !/三项验证均通过/.test(ev.text))
  // 默认筛选是「待办优先」：只出实验中的卡 + 有缺口的卡，不含无缺口的已采纳卡
  if (validatedNoGap) expect('待办优先筛选：已采纳无缺口卡（' + validatedNoGap.id + '）不出现在首屏', !ev.text.includes(validatedNoGap.id))

  // —— 样式层（styles.insert 注入的 class 体系）——
  const css = cssChunks.join('\n')
  expect('注入了样式表', css.length > 500, css.length + ' 字符')
  expect('样式表含 hover 态', /:hover/.test(css))
  expect('样式表含 focus-visible（键盘可达）', /:focus-visible/.test(css))
  expect('样式表含 reduced-motion 兜底', /prefers-reduced-motion/.test(css))
  expect('样式表用主题变量而非硬编码底色', /--dsw-alias-bg-layer-1/.test(css) && /--dsw-alias-label-primary/.test(css))
  expect('展开用 grid-template-rows 过渡（不动画 height）', /grid-template-rows/.test(css))
  expect('等宽数字对齐（tabular-nums）', /tabular-nums/.test(css))
  // 首屏无卡时（无实验中的卡 + 无缺口）这里没有卡片可查——改到"展开单卡"节断言（那边必有卡）
  if (nExp + nGap > 0) expect('渲染用 class 而非全内联', /«cls:ev-card/.test(ev.text) && /«cls:ev-head/.test(ev.text))
  expect('亮色分层：表面叠加层 --surf', /--surf:rgba/.test(css) && /linear-gradient\(var\(--surf\)/.test(css))
  expect('发丝线变量 --hair（亮色下 border-l1 只有 4% 不可见）', /--hair:color-mix/.test(css))
  expect('主题判定跟随 DSH（body[data-ds-dark-theme]）而非 prefers-color-scheme',
    /body\[data-ds-dark-theme\]/.test(css) && !/@media\s*\(prefers-color-scheme/.test(css))
  // 手选色值（不再"品牌色混黑"——那会把饱和度一起压掉，面板因此发暗沉）
  expect('语义色阶：ink 手选色值', /--c-blue:#1d4ed8/.test(css) && /--c-amber:#92400e/.test(css))
  expect('语义色阶：实心底独立于 ink', /--fill-blue:#1d4ed8/.test(css))
  expect('暗色反相为亮而饱和的色值', /--c-blue:#7db3fc/.test(css))
  expect('徽标底色浓度独立可调', /--tint:9%/.test(css))
  expect('装饰色与诊断面板同值（--acc-blue #3b82f6）', /--acc-blue:#3b82f6/.test(css))
  expect('文字色与装饰色分离（--c-blue 深档 / --acc-blue 亮色）', /--c-blue:#1d4ed8/.test(css) && /--acc-blue:#3b82f6/.test(css))
  expect('标题色标与诊断面板同渐变', /linear-gradient\(180deg,var\(--acc-blue\),var\(--acc-purple\)\)/.test(css))
  expect('展开时先占位（避免二次跳高）', /ev-skel/.test(css) && /ev-skel-line/.test(css))
  expect('悬停预取（点开即就绪）', /onPointerEnter/.test(fs.readFileSync(path.join(repo, 'dsh-plugins/ev-panel/panel-client.js'), 'utf8')))
  expect('暗色实心徽标用浅底深字（白字配浅底只有 2:1）', /data-ds-dark-theme\]\s*\.ev-pill\.solid\{[^}]*color:#111318/.test(css))
  expect('卡号用可读链接色 --link', /--link:/.test(css) && /\.ev-id\{[^}]*var\(--link\)/.test(css))

  // —— 执行现场（exec-log）：2026-09-10 新增区块，两种状态都要能渲染 ——
  // 本工作区的 exec-log 是 .gitignore 本地件，通常不存在 → 走退化分支；这里两个分支都断言，
  // 不依赖"本机碰巧有没有记录"。
  expect('执行现场区块出现', ev.text.includes('执行现场（exec-log）'))
  if (board.skill_exec && board.skill_exec.present) {
    expect('执行现场：报出 evolve-check 收尾次数', /evolve-check 收尾/.test(ev.text))
    expect('执行现场：本地件标注（防读成全系统）', /跨 worktree\/克隆不聚合/.test(ev.text))
  } else {
    expect('无 exec-log 时走退化分支（不是空白也不是假数据）', /无执行记录/.test(ev.text))
    expect('退化分支给出补救指引', /内容流程收尾应先落一条 exec-log/.test(ev.text))
    expect('退化分支标注本地件口径', /跨 worktree\/克隆不聚合/.test(ev.text))
  }
  // 合成数据分支：present + 有 evolve-check 记录（含无信号）→ 渲染运行次数与无信号计数
  {
    const synthetic = Object.assign({}, board, {
      skill_exec: {
        present: true, state: 'ok', note: '本地件：跨 worktree/克隆不聚合（.gitignore 运行时件）',
        total: 3, by_skill: { 'to-reference': 1, 'evolve-check': 2 },
        evolve_check_runs: 2, evolve_check_no_signal: 1,
        last_evolve_check: { seq: 3, skill: 'evolve-check', at: '2026-09-10T17:20:00', source: 'to-reference', products: ['EV-2026-044(validated)'], decision_reason: 'T3 信号 → 产卡 EV-2026-044' },
        recent: [
          { seq: 1, skill: 'to-reference', at: '2026-09-10T17:10:00', source: 'to-reference', products: ['msprof-x(active)'], decision_reason: '归纳 3 case' },
          { seq: 2, skill: 'evolve-check', at: '2026-09-10T17:15:00', source: 'to-reference', products: [], decision_reason: '收尾无演进信号' },
          { seq: 3, skill: 'evolve-check', at: '2026-09-10T17:20:00', source: 'to-reference', products: ['EV-2026-044(validated)'], decision_reason: 'T3 信号 → 产卡 EV-2026-044' },
        ],
      },
    })
    const synHost = (method, args) => {
      if (method === 'ev-board-load') return { ok: true, data: synthetic }
      if (method === 'ev-idea-detail') return detailOf(args.ideaId)
      return { ok: false, error: 'unknown ' + method }
    }
    const syn = await renderAsync(evSrc, { sessionId: 'sess-1' }, synHost)
    expect('执行现场（有记录）：收尾 2 次 · 无信号 1', /evolve-check 收尾[\s\S]{0,40}?2 次[\s\S]{0,30}?无信号 1/.test(syn.text), syn.text.slice(syn.text.indexOf('执行现场（exec-log）'), syn.text.indexOf('执行现场（exec-log）') + 160))
    expect('执行现场（有记录）：列出最近执行（含无信号那条）', syn.text.includes('收尾无演进信号'))
    expect('执行现场（有记录）：show 卡产出', syn.text.includes('EV-2026-044'))
    // present 但一次 evolve-check 都没跑 → 琥珀色告警（这正是修前的真实状态）
    const syn2 = Object.assign({}, synthetic, { skill_exec: Object.assign({}, synthetic.skill_exec, { evolve_check_runs: 0, evolve_check_no_signal: 0 }) })
    const syn2r = await renderAsync(evSrc, { sessionId: 'sess-1' }, (m, a) => m === 'ev-board-load' ? { ok: true, data: syn2 } : detailOf(a && a.ideaId))
    expect('执行现场：零运行时报「无法区分跑了无信号与没跑」', /无法区分/.test(syn2r.text))
  }

  // ================= 展开单卡 =================
  console.log('\n[ev-panel 展开单卡 · 决策链全文]')
  // 手法：渲染到数据就位 → 把所有 boolean hook（卡展开态）置 true → 再走完整异步循环
  // （展开会触发 ev-idea-detail RPC，必须等它 flush 后才能看到全文）
  hookIdx = 0; hookState = []; depState = []; effectQueue = []; cssChunks = []
  {
    const registrations = []
    const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
    let calls = []
    const host = { call: (m, a) => { calls.push(m + (a && a.ideaId ? ':' + a.ideaId : '')); return Promise.resolve(evHost(m, a)) } }
    const stylesGlobal = { insert(css) { cssChunks.push(css); return () => {} } }
    const plugin = new Function('React', 'host', 'styles', 'return (function(){' + evSrc + '})()')(React, host, stylesGlobal)
    plugin.apply(ctx)
    const renderTree = () => {
      effectQueue = []; hookIdx = 0
      const o = []
      registrations.forEach(r => { o.push(r.c({ sessionId: 'sess-1' })) })
      return o
    }
    const textOf = (tree) => { const o = []; flatten(tree, o); return o.join('\n') }
    // 关键：即使 effect 队列已空也要继续转——点开卡会发起 detail RPC，
    // 它的 setState 发生在之后的微任务里，必须再渲染一次才看得到全文。
    const pump = async (rounds) => {
      let tree = null
      for (let i = 0; i < rounds; i++) {
        tree = renderTree()
        const eff = effectQueue.slice()
        eff.forEach(f => f())
        await new Promise(r => setImmediate(r))
        await new Promise(r => setImmediate(r))
      }
      return tree
    }
    let tree = await pump(5)
    // 真实点击：点第一张卡的头部（onClick 挂在收起态的可点区域上）
    // 卡头特征：文本以卡 id 开头且含"共 N 条"（决策计数）；顶部筛选条不含
    const isCardHead = h => /EV-2026-0\d\d/.test(h.text) && /共 \d+ 条/.test(h.text) && !/审计缺口|最近采纳/.test(h.text)
    let handlers = []
    tree.forEach(t => collectHandlers(t, handlers))
    // 首屏「待办优先」在"无实验中的卡 + 无缺口"时是空的（全卡闭合后的真实状态）。
    // 这时先点「全部」筛选，保证有可点目标——否则用例会点不到卡并连带崩溃
    // （2026-09-10 实测：硬编码目标 + 空首屏 = 用例本身成了故障源）。
    if (!handlers.some(isCardHead)) {
      // 注意：flatten 把 «cls:...» 标记插在文本最前面，所以只能 contains 匹配，不能用 startsWith/^
      const allChip = handlers.find(h => String(h.text).includes('全部'))
      if (allChip) {
        allChip.fn({})
        tree = await pump(4)
        handlers = []
        tree.forEach(t => collectHandlers(t, handlers))
        console.log('  [debug] 首屏无待办卡 → 已切到「全部」筛选')
      }
    }
    if (!handlers.some(isCardHead)) {
      // 「全部」视图里若所有卡都"已采纳且无缺口"，它们收在「归档」折叠里（只增不减的墙的解法），
      // 得先展开才有点得着的卡头
      const archiveToggle = handlers.find(h => String(h.text).includes('归档'))
      if (archiveToggle) {
        archiveToggle.fn({})
        tree = await pump(4)
        handlers = []
        tree.forEach(t => collectHandlers(t, handlers))
        console.log('  [debug] 卡都在「归档」折叠里 → 已展开')
      }
    }
    const target = handlers.find(isCardHead)
    let clicked = 0
    if (target) { target.fn({}); clicked = 1 }
    console.log('  [debug] 可点区域', handlers.length, '个；点击目标首 40 字:', target ? target.text.slice(0, 40) : '未找到')
    tree = await pump(6)
    const text = textOf(tree)
    console.log('  [debug] 点击处理器数:', handlers.length, '| 实际点击:', clicked)
    if (process.env.PANEL_DEBUG) {
      console.log('  [debug] 含假设:', text.includes('假设'), '| 含门控:', text.includes('门控'), '| 含回滚:', text.includes('回滚'))
      const i = text.indexOf('EV-2026-03')
      console.log('  [debug] 展开片段:', JSON.stringify(text.slice(i, i + 700)))
    }
    expect('模拟点击生效（' + clicked + ' 次）', clicked === 1)
    expect('渲染用 class 而非全内联（展开态）', /«cls:ev-card/.test(text) && /«cls:ev-head/.test(text))
    expect('展开后出现「假设」节', text.includes('假设'))
    expect('展开后出现「预期效果」节', text.includes('预期效果'))
    expect('展开后出现「验证」节与成功判据', text.includes('成功判据'))
    expect('展开后出现「决策链」节', text.includes('决策链'))
    expect('展开后出现「触发信号」节', text.includes('触发信号'))
    expect('展开后出现判断/验证阶段标签', /判断/.test(text) && /验证/.test(text))
    expect('展开后出现 validation.rollback（回滚）', /回滚/.test(text))
    expect('展开后出现门控条件', /门控/.test(text))
    // 全文 vs 旧版截断：被点开那张卡的最长 conclusion 应完整出现在渲染文本里
    const shownId = target ? (target.text.match(/EV-\d{4}-\d{3}/) || [])[0] : null
    const decs = (detailOf(shownId).idea.decisions || []).map(d => d.conclusion || '')
    const longest = Math.max(0, ...decs.map(d => d.length))
    const longestText = decs.find(d => d.length === longest) || ''
    expect('被展开卡 ' + shownId + ' 最长 conclusion ' + longest + ' 字', longest > 70)
    expect('该 conclusion 完整出现在渲染文本中（未截断）', longestText && text.includes(longestText.trim().slice(0, Math.min(120, longestText.length))))
  }

  // ================= 指标面板 =================
  console.log('\n[ascend-panel 指标 tab]')
  const ascSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-client.js'), 'utf8')
  const ascHost = (method) => {
    if (method === 'ascend-traces-list') return { ok: true, sessions: [] }
    if (method === 'ascend-metrics-load') return { ok: true, periods }
    if (method === 'ascend-kb-health') return { ok: true, cases: { total: 52, lowConfidence: 12, byCategory: { interrupt: 30, performance: 10, precision: 12 }, byNamespace: { 'inference/vllm-ascend': { total: 46 } } }, references: { total: 95, draftCount: 0, staleCount: 2, byType: { tool: 20, fact: 30 } } }
    if (method === 'ascend-process-health') return { ok: true, total: 11, submitted: 5, promoted: 3, inProgress: 2, resumed: 1, refSessions: 4 }
    return { ok: false, error: 'unknown ' + method }
  }
  const asc = await renderAsync(ascSrc, { sessionId: 'sess-1' }, ascHost)
  expect('渲染无异常', true)
  expect('注册两个 tab', asc.regs.length === 2)
  expect('诊断 tab id', asc.regs[0].opts.id === 'ascend-diagnose')
  expect('指标 tab id', asc.regs[1].opts.id === 'ascend-metrics')

  hookIdx = 0; hookState = []; depState = []; effectQueue = []; cssChunks = []
  let mt = ''
  {
    const registrations = []
    const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
    const host = { call: (m, a) => Promise.resolve(ascHost(m, a)) }
    const stylesGlobal = { insert(css) { cssChunks.push(css); return () => {} } }
    const plugin = new Function('React', 'host', 'styles', 'return (function(){' + ascSrc + '})()')(React, host, stylesGlobal)
    plugin.apply(ctx)
    let out = []
    for (let round = 0; round < 6; round++) {
      effectQueue = []; hookIdx = 0; out = []
      registrations.forEach(r => flatten(r.c({ sessionId: 'sess-1' }), out))
      const eff = effectQueue.slice(); if (!eff.length) break
      eff.forEach(f => f()); await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
    }
    effectQueue = []; hookIdx = 0; out = []
    registrations.forEach(r => flatten(r.c({ sessionId: 'sess-1' }), out))
    mt = out.join('\n')
  }
  expect('「本期变化」区块存在', mt.includes('本期变化'))
  expect('对照标注 live2 vs live1', /2026-W36-live2/.test(mt) && /对比 2026-W35-live1/.test(mt))
  expect('变化项 sessions_total 7 → 11', /诊断 session 数[\s\S]{0,50}7 → 11/.test(mt), (mt.match(/诊断 session 数[\s\S]{0,60}/) || [])[0])
  expect('新增项标注「新增」', /新增/.test(mt))
  expect('持平项计数', /项持平/.test(mt))
  // 默认 live 筛选只有 2 期（全部展开，无历史可折叠）——切到「全部」才该出现折叠
  expect('live 筛选：无历史折叠（期数不足）', !/历史快照 \d+ 期/.test(mt))
  {
    // 切「全部」筛选，再看折叠与收起态摘要
    hookIdx = 0; hookState = []; depState = []; effectQueue = []; cssChunks = []
    const registrations = []
    const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
    const host = { call: (m, a) => Promise.resolve(ascHost(m, a)) }
    const stylesGlobal = { insert(css) { cssChunks.push(css); return () => {} } }
    const plugin = new Function('React', 'host', 'styles', 'return (function(){' + ascSrc + '})()')(React, host, stylesGlobal)
    plugin.apply(ctx)
    const renderTree = () => {
      effectQueue = []; hookIdx = 0
      const o = []
      registrations.forEach(r => o.push(r.c({ sessionId: 'sess-1' })))
      return o
    }
    const textOf = t => { const o = []; flatten(t, o); return o.join('\n') }
    let tree = null
    for (let i = 0; i < 5; i++) {
      tree = renderTree()
      effectQueue.slice().forEach(f => f())
      await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
    }
    const hs = []
    tree.forEach(t => collectHandlers(t, hs))
    // 注意：诊断 tab 的 kbFilter 也有「全部」——取最后一个（指标 tab 的 kindFilter 在后面）
    const allBtn = hs.filter(h => h.text.trim() === '全部').pop()
    if (allBtn) allBtn.fn({})
    for (let i = 0; i < 4; i++) {
      tree = renderTree()
      effectQueue.slice().forEach(f => f())
      await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
    }
    const mtAll = textOf(tree)
    expect('切「全部」后出现历史快照折叠', /历史快照 \d+ 期/.test(mtAll), mtAll.match(/历史快照[^\n]{0,20}/))
    // 收起态摘要取该期前 3 项指标（replay 期含「路由准确率」，live 期含「诊断 session 数」）
    expect('期卡收起态带指标摘要', /路由准确率 \d+\/\d+/.test(mtAll) || /诊断 session 数 \d+/.test(mtAll),
      (mtAll.match(/路由准确率[^\n]{0,20}/) || [])[0])
    expect('收起态标注项数（N 项）', /\d+ 项/.test(mtAll))
  }
  expect('知识库健康保留', mt.includes('知识库健康'))
  expect('流程闭环保留', mt.includes('流程闭环'))
  expect('实时计算保留', mt.includes('实时计算'))
  expect('默认收起期卡数量少于总期数（避免平铺）', (mt.match(/项$/gm) || []).length <= periods.length)

  console.log('\n' + (failures.length ? '失败 ' + failures.length + ' 项: ' + failures.join(' | ') : '全部通过'))
  process.exit(failures.length ? 1 : 0)
}

main().catch(e => { console.error('harness 崩溃:', e); process.exit(2) })
