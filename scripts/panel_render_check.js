// 离线渲染校验：用 mock React + 真实数据跑面板客户端，确认
//  1) 渲染不抛异常
//  2) 关键信息（决策链全文、变化对照、缺口提示）确实出现在输出里
// 不是替代浏览器验证，是把"渲染逻辑 + 数据契约"这一层先钉死。
const fs = require('fs')
const os = require('os')
const path = require('path')
const { execFileSync } = require('child_process')

const repo = path.resolve(__dirname, '..')

// ---- Python 解释器解析（Windows 兼容）----
// 与 dsh-plugins/*/panel-host.js 的同名解析同源：Windows 上 `python3` 常不存在
// （python.org 安装器装的是 python.exe + py.exe 启动器；PATH 里 Store 的「应用执行
// 别名」占位程序既不返回 0 也不打印版本）。逐个候选探测，取第一个 exit 0 且打印
// Python 3.x 的；结果在本次进程内缓存。
function resolvePython() {
  for (const [cmd, prefix] of [['python3', []], ['python', []], ['py', ['-3']]]) {
    try {
      const out = execFileSync(cmd, [...prefix, '--version'], { encoding: 'utf-8' })
      if (/Python 3\./.test(out)) return { cmd, prefix }
    } catch (e) {
      // 候选不可执行（含 9009 占位程序）→ 试下一个
    }
  }
  return null
}
const PY = resolvePython()
if (!PY) {
  console.error('未找到可用的 Python 3 解释器（已试 python3 / python / py -3）——'
    + 'scripts/panel_render_check.js 要用它跑 scripts/ev_board_data.py 与读 metrics/timeline.yaml')
  process.exit(2)
}
const pyRun = (args, opts) => execFileSync(PY.cmd, [...PY.prefix, ...args], opts)

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
// 子进程一律带上 UTF-8 环境（Windows 兼容）：这几个调用要把中文数据（周期 notes、卡片
// 标题…）经 stdout 传回来，而 Windows 上子进程 Python 的 stdout 默认按 locale 编码
// （中文系统 = cp936）——字节是 GBK、这边按 UTF-8 解码 → 中文全变乱码。症状很隐蔽：
// 渲染不报错，只是文案烂掉，于是"按其内容做的断言"无理由失败（实测正是它让
// 「期卡收起态带指标摘要」在 Windows 上失败，而 Linux 上通过）。
const PY_ENV = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' }
const board = JSON.parse(pyRun(['scripts/ev_board_data.py'], { cwd: repo, maxBuffer: 32 * 1024 * 1024, env: PY_ENV }).toString())
const detailCache = {}
function detailOf(id) {
  if (!detailCache[id]) {
    detailCache[id] = JSON.parse(pyRun(['scripts/ev_board_data.py', '--detail', id], { cwd: repo, maxBuffer: 32 * 1024 * 1024, env: PY_ENV }).toString())
  }
  return detailCache[id]
}
const periods = JSON.parse(pyRun(['-c', `
import yaml, json
d = yaml.safe_load(open('metrics/timeline.yaml', encoding='utf-8'))
print(json.dumps(d['periods'], ensure_ascii=False, default=str))
`], { cwd: repo, env: PY_ENV }).toString())

// 演进判决（面板首屏的判决层）。**允许非零退出**：evolution_health.py 的退出码是结论
// （0 全评过无越界 / 1 有违反 / 2 有判据没被评估），像 metrics_health 一样——有违反时它
// 退 1 但 stdout 仍是完整 JSON。execFileSync 在非零退出时抛异常，异常对象上带 stdout，
// 所以这里取 stdout 而不是把非零当成"跑不起来"（那会把"有违反"误读成"体检器坏了"）。
function pyRunAllowFail(args, opts) {
  try { return pyRun(args, opts).toString() } catch (e) { return String((e && e.stdout) || '') }
}
const health = JSON.parse(pyRunAllowFail(['scripts/evolution_health.py', '--json'],
  { cwd: repo, maxBuffer: 16 * 1024 * 1024, env: PY_ENV }))

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
    if (method === 'ev-health-load') return { ok: true, data: health }
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

  // 首屏预览：把渲染出来的首屏文本原样打出来（`PANEL_DEBUG=1`）。
  // 为什么值得有：本门是"渲染没坏"的离线闸门，而首屏的**信息取舍**（放什么、收什么）
  // 只有把文本铺开才能复核——评审改版时不必开浏览器就能读出"人的第一屏是什么"。
  // 去掉 «cls:...» 标记并压掉空行，输出即近似人读顺序。
  if (process.env.PANEL_DEBUG) {
    console.log('\n----- ev-panel 首屏预览（收起态） -----')
    console.log(ev.text.replace(/«cls:[a-z0-9-]+»/g, '').replace(/\n{2,}/g, '\n'))
    console.log('----- 预览结束 -----\n')
  }

  // ---- 判决面（2026-09 新增）：首屏必须是判决，不是卡墙 ----
  // 断言的期望值从真实 health JSON 推导，不硬编码判据名/数字——判据会随阈值校准增删。
  const nFails = (health.findings || []).filter(f => f.level === 'fail').length
  const VERDICT_LABEL = { clean: '本期无阻塞项', violations: '有判据被违反', broken: '体检器失效' }[health.check_verdict]
  expect('判决条：结论用语（' + health.check_verdict + '）', ev.text.includes(VERDICT_LABEL), ev.text.slice(0, 160))
  expect('判决条：报出要处理项数 ' + nFails, new RegExp(nFails + '\\s*项要处理').test(ev.text))
  const covTxt = (health.coverage.gates_evaluated || 0) + '/' + (health.coverage.gates_total || 0)
  expect('判决条：报出判据覆盖面 ' + covTxt + '（"没报越界"与"没被检查"分开）',
    new RegExp('判据\\s*' + covTxt.replace('/', '\\/') + '\\s*条已评估').test(ev.text), ev.text.slice(0, 200))
  expect('① 要处理的：区块存在', ev.text.includes('① 要处理的'))
  // 每条 fail 判据的标题都应上屏（逐条从 health 推导，不硬编码）
  const missingFindings = (health.findings || []).filter(f => f.level === 'fail' && !ev.text.includes(f.title))
  expect('① 要处理的：全部 ' + nFails + ' 条判据标题都已渲染', missingFindings.length === 0,
    missingFindings.map(f => f.title).join('、'))
  // 动作必须跟着判据走（只报病不给下一步 = 又是一句无法动作的散文）
  const failWithAction = (health.findings || []).find(f => f.level === 'fail' && f.action)
  if (failWithAction) {
    expect('① 要处理的：给出下一步动作', ev.text.includes(failWithAction.action.slice(0, 40)),
      failWithAction.action.slice(0, 60))
  }
  expect('① 要处理的：不把 0 项渲染成"没问题"（明示覆盖面才是结论）',
    nFails > 0 || /没有需要动作的判据/.test(ev.text))
  // 预测实测记录：唯一真实的负反馈读数（0 笔时必须明说"一次都没被复现过"，不静默）
  const nMv = (health.readouts && health.readouts.measure_runs) || 0
  const mv = (health.readouts && health.readouts.measure_by_verdict) || {}
  expect('① 要处理的：报出预测实测记录 ' + nMv + ' 次执行', new RegExp('预测实测记录[\\s\\S]{0,12}?' + nMv + '\\s*次执行').test(ev.text), ev.text.slice(0, 200))
  if (nMv === 0) {
    expect('实测 0 次时明说 0 次并给执行方式（不静默）', /预测实测记录：0 次执行/.test(ev.text) && /ev_measure\.py/.test(ev.text))
  } else {
    const MV_LABEL = { PASS: '符合', FAIL: '被证伪', ERROR: '判不了' }
    const expectParts = Object.keys(mv).filter(k => MV_LABEL[k]).map(k => MV_LABEL[k] + ' ' + mv[k])
    expect('实测分布按三态渲染（' + expectParts.join(' · ') + '）',
      expectParts.every(t => ev.text.includes(t)), expectParts.join('/'))
    expect('说明「被证伪」的含义与后续动作', /被证伪[\s\S]{0,30}不再成立/.test(ev.text))
  }

  // ---- ② 触及面（这批补在哪一层）：确定性派生的读数 ----
  expect('② 改动落在哪一层：区块存在', ev.text.includes('② 改动落在哪一层'))
  const surfaces = Object.keys(board.stats.by_surface || {})
  expect('② 触及面：全部 ' + surfaces.length + ' 个轴都已渲染',
    surfaces.every(s => ev.text.includes(s)), surfaces.join('、'))
  expect('② 触及面：说明本表表示层次、不表示改善幅度',
    /表示改动落在哪一层，不表示改善幅度/.test(ev.text))
  // 诚实退化：能力轴不可解读时必须明说，不得画趋势线称"稳定"
  expect('② 触及面：能力轴标注不可解读（不是"稳定"）', /不可解读/.test(ev.text) && !/能力轴[^。]{0,20}稳定/.test(ev.text))
  expect('② 触及面：标注归类依据字段（并说明依据较弱时的局限）',
    /归类依据/.test(ev.text) && /可能不是实际改动位置/.test(ev.text))
  // 两条**已在本仓库另一面板踩过**的文案缺陷，这里一并钉住（同类缺陷复发 ≥2 次才进 CI 的口径）：
  // ① Markdown 星号当强调写进渲染文本 → 面板原样显示字面量（诊断面板已修过一次）；
  // ② 内部标识符（metric/dimension id）泄漏到人读文案里。
  // ①的范围要收紧到**面板自己的文案**（新增区块的源码，且剥掉注释），不查整页渲染文本：
  //    - 整页里带历史数据原文（实测 exec-log 的 decision_reason 里就有 `**有**`），用渲染文本判
  //      会把数据误判成文案缺陷——与上面 v1 状态词"查声明不查整页"是同一条教训；
  //    - 源码里的**代码注释**不参与渲染，注释里用 `**` 强调是正常的（实测：本行加了
  //      "0 张卡时**不静默消失**"的注释就把这条断言判红了）。
  const newCopyBlocks = evSrc.slice(evSrc.indexOf('function measureLine'),
    evSrc.indexOf('// ============ 主视图 ============'))
    .split('\n')
    .map(l => l.replace(/\s*\/\/.*$/, ''))
    .filter(l => l.trim())
    .join('\n')
  expect('判决/触及面文案不含字面 Markdown 星号（数据与注释里的不算）', !/\*\*/.test(newCopyBlocks),
    (newCopyBlocks.match(/.{0,24}\*\*.{0,24}/) || [])[0])
  expect('不把内部指标 id 端给人看（readability 用人读名）',
    !/capability_readout/.test(ev.text) && /读数不可解读|判断更准/.test(ev.text))
  const unattributed = (board.stats.by_surface || {})['未归因'] || 0
  if (unattributed === 0) expect('② 触及面：0 张未归因时不渲染该行（不占位）', !/未归因[^，。]{0,10}\d/.test(ev.text))

  // ---- ③ 现场 ----
  const nEvRuns = (board.skill_exec && board.skill_exec.evolve_check_runs) || 0
  expect('③ 现场：抽屉头报出实验中 ' + nExp, new RegExp('实验中[\\s\\S]{0,60}?' + nExp).test(ev.text))
  expect('③ 现场：抽屉头报出审计缺口 ' + nGap, new RegExp('审计缺口[\\s\\S]{0,60}?' + nGap).test(ev.text))

  // ---- ④ 卡片抽屉：默认收起（判决上屏、卡按需） ----
  // 这一条是本次重排的核心行为：旧版首屏直接平铺卡墙（实测退化成一堵只增不减的墙）。
  expect('④ 卡片抽屉：默认收起（首屏不渲染任何卡）', !/«cls:ev-card/.test(ev.text))
  expect('④ 卡片抽屉：收起态标出这是卡片档案', /④ 卡片档案/.test(ev.text))
  expect('④ 卡片抽屉：收起态不泄露完整决策链', !/三项验证均通过/.test(ev.text))
  expect('v5 状态词「实验中」', ev.text.includes('实验中'))
  expect('v5 状态词「已采纳」', ev.text.includes('已采纳'))  // v1 词表检查**查声明、不查整页渲染文本**：整页里会带历史数据原文（exec-log 的
  // decision_reason、卡的结论摘要），里面的"候选"是数据不是 UI 状态词——用渲染文本判会把
  // 数据误判成词表回归（2026-09-10 合并后在带 exec-log 的检出上实测假失败：命中来自
  // '拉取 17 / 候选 9 / 评估通过 1' 这条历史记录）。v1 词表当年是 v1 状态机的产物，
  // 因此正确的判据是"状态词声明里没有 v1 词"，加上 v5 词确有渲染（上面两条）。
  const statusVocab = evSrc.slice(evSrc.indexOf('const STATUS_META'), evSrc.indexOf('const AUTH_META'))
  expect('STATUS_META 声明里无 v1 状态词', statusVocab.length > 0 && !/pending_merge|已提议|候选/.test(statusVocab),
    (statusVocab.match(/pending_merge|已提议|候选/) || [])[0])
  // 缺口 pill 与卡级计数的数据驱动断言：卡现在收在抽屉里，所以"渲染没渲染"必须**展开后**断言
  // （见下面「展开单卡」节）。这里只断言收起态不空转、有缺口时抽屉头仍报出计数。
  if (nGap > 0) {
    expect('缺口卡在抽屉头计数里可见（' + (board.stats.gap_cards || []).join('、') + '）',
      (board.stats.gap_cards || []).some(id => ev.text.includes(id)) || new RegExp('审计缺口[\\s\\S]{0,20}?' + nGap).test(ev.text))
  }
  expect('自演进度量：采纳率', /采纳率/.test(ev.text))
  // 采纳率不再是"成绩"读数：终态卡从未出现否决时，它必须在旁边点明这是症状（原则十）
  if ((board.stats.negative_terminal || 0) === 0 && (board.stats.terminal_count || 0) > 0) {
    expect('采纳率 100% 旁点明其含义（没有否决记录）', /没有否决记录/.test(ev.text), ev.text.slice(0, 200))
  }
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
  expect('timeline 趋势区块存在', /指标趋势/.test(ev.text))
  // 趋势的可读性契约（2026-09 重写后新增，起因是实测看不懂）：
  // ① 比例必须带分母——旧实现把 {ok,total} 压成 ok，三期 "3/3" 渲染成三根等高的柱 + 一个 "3"；
  // ② 会话数那列要有变化量（+N），否则"哪个读数在动"要靠人对比；
  // ③ 读数恒定时要用注记明说"趋势不可读"，不靠柱高差暗示趋势（原则十）。
  const liveRows = periods.filter(p => p.kind === 'live').slice(-6)
  const raWithDen = liveRows.filter(p => p.metrics && p.metrics.routed_accuracy
    && p.metrics.routed_accuracy.total)
  if (raWithDen.length) {
    const raTxt = raWithDen[0].metrics.routed_accuracy
    expect('趋势：比例带分母（' + raTxt.ok + '/' + raTxt.total + '）', ev.text.includes(raTxt.ok + '/' + raTxt.total), ev.text.slice(0, 200))
  }
  const sessCol = liveRows.map(p => p.metrics && p.metrics.sessions_total).filter(v => typeof v === 'number')
  if (sessCol.length > 1) {
    expect('趋势：会话数列渲染', sessCol.every(v => new RegExp('\\b' + v + '\\b').test(ev.text)), sessCol.join(','))
    const anyDelta = sessCol.some((v, i) => i > 0 && v !== sessCol[i - 1])
    if (anyDelta) expect('趋势：给出相对上期的变化量（+N/-N）', /[+]\d|−\d/.test(ev.text) || /\+\d/.test(ev.text))
  }
  expect('趋势：读数恒定/分母过小时用注记明说', /无法据此判断趋势|不可解读/.test(ev.text))
  // 排版契约：与「指标」面板共用同一套 8 档字号（本面板原先 17 个散值、最小 8.5px =
  // "字小 + 中文糊"的直接原因）。断言查**源码**，这样新增档位会在离线闸门被拦下。
  const tDecl = {}
  ;(evSrc.match(/--t-[a-z0-9]+:\s*[0-9.]+px/g) || []).forEach(d => {
    const kv = d.split(':'); tDecl[kv[0].trim()] = parseFloat(kv[1])
  })
  expect('排版：声明 8 档字号', Object.keys(tDecl).length === 8, Object.keys(tDecl).join(','))
  expect('排版：无硬编码 font-size（一律走 --t-*）', !/font-size:\s*[0-9.]+px/.test(evSrc))
  expect('排版：无内联 fontSize 字面量', !/fontSize:\s*'?[0-9.]+/.test(evSrc))
  const tVals = Object.keys(tDecl).map(k => tDecl[k])
  expect('排版：最小档 ≥ 10（原 8.5 中文会糊）', Math.min(...tVals) >= 10, String(Math.min(...tVals)))
  expect('排版：基准档 ≥ 14（原 12）', (tDecl['--t-base'] || 0) >= 14, String(tDecl['--t-base']))
  expect('排版：中文基准行高 ≥ 1.6', /--lh-base:1\.6/.test(evSrc))
  expect('排版：与「指标」面板同档位值域（两面板同一套刻度）',
    tDecl['--t-base'] === 14.5 && tDecl['--t-tiny'] === 11.5 && tDecl['--t-sm'] === 12.5)
  // 空态断言必须**跟着数据走**：tally 为空（干净检出）时应出现一行说明；tally 有非零计数
  // （工作检出里已有真实归因）时应渲染表格、且**不该**再出现空态文案。写死成"永远期待空态"
  // 会让这条断言只在干净检出里成立——本地复跑必红，红的原因却不是回归（实测代价：
  // 端到端演练因此常年一红，7 张以演练为判据的卡跟着一直 FAIL）。
  const tallyRows = (board && board.tally) || []
  const tallyHasSignal = tallyRows.some(r => (r.trace_mis || 0) > 0 || (r.s2_candidate || 0) > 0)
  if (tallyHasSignal) {
    expect('tally 有归因 → 渲染表格、不出现空态文案',
      !/尚无归因事件/.test(ev.text) && tallyRows.some(r => ev.text.includes(r.id)))
  } else {
    expect('空区块不占位（tally 空 → 一行说明）', /尚无归因事件/.test(ev.text))
  }
  expect('收起态不泄露完整决策链（长文本仅在展开后）', !/三项验证均通过/.test(ev.text))
  // 默认筛选是「待办优先」：只出实验中的卡 + 有缺口的卡，不含无缺口的已采纳卡。
  // 注意判据已变：卡收在默认收起的抽屉里，所以"已采纳无缺口卡不在首屏"要**展开抽屉后**才成立
  // （下面的「展开单卡」节断言）。首屏只断言"一张卡都不渲染"。
  if (validatedNoGap) {
    expect('首屏不出现任何卡（含已采纳无缺口卡 ' + validatedNoGap.id + '）', !ev.text.includes(validatedNoGap.id))
  }

  // —— 样式层（styles.insert 注入的 class 体系）——
  const css = cssChunks.join('\n')
  expect('注入了样式表', css.length > 500, css.length + ' 字符')
  expect('样式表含 hover 态', /:hover/.test(css))
  expect('样式表含 focus-visible（键盘可达）', /:focus-visible/.test(css))
  expect('样式表含 reduced-motion 兜底', /prefers-reduced-motion/.test(css))
  expect('样式表用主题变量而非硬编码底色', /--dsw-alias-bg-layer-1/.test(css) && /--dsw-alias-label-primary/.test(css))
  expect('展开用 grid-template-rows 过渡（不动画 height）', /grid-template-rows/.test(css))
  expect('等宽数字对齐（tabular-nums）', /tabular-nums/.test(css))
  // 首屏无卡时（无实验中的卡 + 无缺口）这里没有卡片可查——改到"展开单卡"节断言（那边会先开抽屉）
  expect('渲染用 class 而非全内联（判决面）', /«cls:ev-verdict/.test(ev.text) && /«cls:ev-find/.test(ev.text))
  // 判决面的视觉契约：结论条按状态取色（ok/warn/broken 三态各自成类）
  expect('结论条三态配色类存在', /\.ev-verdict\.ok/.test(css) && /\.ev-verdict\.warn/.test(css) && /\.ev-verdict\.broken/.test(css))
  expect('触及面条用两段（累计暗 / 本期亮）表示增量', /\.ev-surf-track i\.now/.test(css))
  expect('诚实退化注记用引用线样式', /\.ev-caveat/.test(css))
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
  // exec-log 现在是**同一克隆共享**的运行时件（主检出 metrics/，跨 worktree 共写共读）；
  // 无 git 的检出（如本仓库的演练沙箱）退化为检出内路径。两种状态都断言，
  // 不依赖"本机碰巧有没有记录"。
  const SHARE_RE = /同一克隆共享|检出内/
  expect('执行现场区块出现', ev.text.includes('执行现场（exec-log）'))
  if (board.skill_exec && board.skill_exec.present) {
    expect('执行现场：报出 evolve-check 收尾次数', /evolve-check 收尾/.test(ev.text))
    expect('执行现场：标注共享范围（防读成全系统）', SHARE_RE.test(ev.text))
  } else {
    expect('无 exec-log 时走退化分支（不是空白也不是假数据）', /无执行记录/.test(ev.text))
    // 断言必须跟着文案走：这行文案在"面板文案去 AI 味"那轮被重写过，而断言留在旧措辞上，
    // 一年多没人发现——因为这条分支只在**没有 exec-log** 的检出里跑，开发机上（有记录）永远
    // 走不到。实测（2026-09-14）：CI 形态的干净检出（`git archive HEAD`，无 traces/、无 exec-log）
    // 里整套检查会红，且只红这一条。
    expect('退化分支给出补救指引', /内容流程收尾时应写入一条 exec-log/.test(ev.text),
      ev.text.slice(0, 200))
    expect('退化分支标注共享范围', SHARE_RE.test(ev.text))
  }
  // 合成数据分支：present + 有 evolve-check 记录（含无信号）→ 渲染运行次数与无信号计数
  {
    const synthetic = Object.assign({}, board, {
      skill_exec: {
        present: true, state: 'ok',
        note: '/repo/metrics/skill-exec-log.yaml（同一克隆共享（主检出 metrics/；所有 worktree 共写共读））',
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
      if (method === 'ev-health-load') return { ok: true, data: health }
      if (method === 'ev-idea-detail') return detailOf(args.ideaId)
      return { ok: false, error: 'unknown ' + method }
    }
    const syn = await renderAsync(evSrc, { sessionId: 'sess-1' }, synHost)
    expect('执行现场（有记录）：收尾 2 次 · 无信号 1', /evolve-check 收尾[\s\S]{0,40}?2 次[\s\S]{0,30}?无信号 1/.test(syn.text), syn.text.slice(syn.text.indexOf('执行现场（exec-log）'), syn.text.indexOf('执行现场（exec-log）') + 160))
    expect('执行现场（有记录）：列出最近执行（含无信号那条）', syn.text.includes('收尾无演进信号'))
    expect('执行现场（有记录）：show 卡产出', syn.text.includes('EV-2026-044'))
    // present 但一次 evolve-check 都没跑 → 琥珀色告警（这正是修前的真实状态）
    const syn2 = Object.assign({}, synthetic, { skill_exec: Object.assign({}, synthetic.skill_exec, { evolve_check_runs: 0, evolve_check_no_signal: 0 }) })
    const syn2r = await renderAsync(evSrc, { sessionId: 'sess-1' }, (m, a) => m === 'ev-board-load' ? { ok: true, data: syn2 } : (m === 'ev-health-load' ? { ok: true, data: health } : detailOf(a && a.ideaId)))
    expect('执行现场：零运行时报「无法区分跑了无信号与没跑」', /无法区分/.test(syn2r.text))
  }

  // ---- 判决层失效时的诚实退化：health 拿不到 → 不拿卡数冒充判决 ----
  {
    const noHealth = await renderAsync(evSrc, { sessionId: 'sess-1' },
      (m, a) => m === 'ev-board-load' ? { ok: true, data: board } : (m === 'ev-health-load' ? { ok: false, error: '体检器不可用' } : detailOf(a && a.ideaId)))
    expect('判决拿不到时不冒充判决（不渲染结论条）', !/«cls:ev-verdict»/.test(noHealth.text))
    expect('判决拿不到时其余区块照常渲染（一次失败不牵连另一块）', /② 改动落在哪一层/.test(noHealth.text))
    expect('判决拿不到时不静默（卡区/触及面仍在，读者仍能判读）', /④ 卡片档案/.test(noHealth.text))
  }
  // ---- 体检器失效（exit 2 语义）必须上屏，而不是"没报越界" ----
  {
    const brokenHealth = Object.assign({}, health, {
      check_verdict: 'broken', broken: ['判据 ghost_gate 声明了 dimension=x，但实现面里没有它'],
      coverage: Object.assign({}, health.coverage, { gates_evaluated: 0, gates_total: 7 }),
    })
    const br = await renderAsync(evSrc, { sessionId: 'sess-1' },
      (m, a) => m === 'ev-board-load' ? { ok: true, data: board } : (m === 'ev-health-load' ? { ok: true, data: brokenHealth } : detailOf(a && a.ideaId)))
    expect('体检器失效：结论条标「体检器失效」而不是"未见阻塞项"',
      /体检器失效/.test(br.text) && !/本期无阻塞项/.test(br.text))
    expect('体检器失效：报出结论不成立与未评估条数',
      /结论不成立/.test(br.text) && /判据\s*0\/7\s*条已评估/.test(br.text), br.text.slice(0, 160))
  }

  // ================= ev-panel 退化路径（无条件跑，不依赖本机碰巧缺什么）=================
  // 为什么单开一节：上面那条"无 exec-log 时走退化分支"是**条件断言**——本机 exec-log 与
  // timeline 都在，于是它永远走 `present` 分支，退化路径一次都没被执行过；rehearse 的沙箱
  // 又会把 metrics/ 一并复制，同样命中正常分支。实测由用户提问才发现这个盲区。
  // 现在用 fixture 根（真脚本 + 真渲染）把每种"缺件"都跑一遍。
  console.log('\n[ev-panel 退化路径 · 缺件时不崩且如实说]')
  {
    const fixtureCases = [
      { case: 'no-exec-log', label: '无 exec-log（有 metrics/ 有卡有判据）' },
      { case: 'no-metrics', label: '无 metrics/（timeline/实测记录全缺）' },
      { case: 'empty-cards', label: '无卡（proposals/ideas 为空）' },
      { case: 'no-gates', label: '无判据文件' },
      { case: 'broken-gates', label: '判据文件语法坏掉' },
    ]
    const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'evdeg-'))
    for (const fc of fixtureCases) {
      const root = path.join(fixtureRoot, fc.case)
      pyRun(['scripts/fixtures/make_degraded_evolve_root.py', '--repo', repo, '--out', root,
        '--case', fc.case], { cwd: repo, env: PY_ENV, stdio: 'pipe' })
      // ① 数据面：必须 exit 0 且输出可解析的 JSON（脚本崩了面板就只能白屏）
      let degraded = null
      let healthDeg = null
      try {
        degraded = JSON.parse(pyRun(['scripts/ev_board_data.py', '--root', root],
          { cwd: repo, maxBuffer: 16 * 1024 * 1024, env: PY_ENV }).toString())
      } catch (e) {
        degraded = { __crash: String((e && e.stderr || e)).slice(0, 200) }
      }
      try {
        healthDeg = JSON.parse(pyRunAllowFail(['scripts/evolution_health.py', '--json', '--root', root],
          { cwd: repo, maxBuffer: 16 * 1024 * 1024, env: PY_ENV }))
      } catch (e) {
        healthDeg = { __crash: String((e && e.stderr || e)).slice(0, 200) }
      }
      expect(fc.label + ' · 数据脚本不崩且输出 JSON',
        !degraded.__crash && typeof degraded.idea_count === 'number', degraded.__crash)
      expect(fc.label + ' · 判决脚本不崩且输出 JSON',
        !healthDeg.__crash && !!healthDeg.check_verdict, healthDeg.__crash)

      // ② 缺件的具体退化口径（哪些字段必须如实说 missing，而不是编 0 冒充）
      if (fc.case === 'no-exec-log' || fc.case === 'no-metrics') {
        expect(fc.label + ' · skill_exec 如实报 missing（不编 0 冒充"跑了但无信号"）',
          degraded.skill_exec && degraded.skill_exec.present === false
          && degraded.skill_exec.state === 'missing', JSON.stringify(degraded.skill_exec && degraded.skill_exec.state))
        expect(fc.label + ' · 实测记录如实报 missing',
          degraded.measure_runs && degraded.measure_runs.state === 'missing',
          JSON.stringify(degraded.measure_runs && degraded.measure_runs.state))
      }
      if (fc.case === 'empty-cards') {
        expect(fc.label + ' · 卡数为 0 且触及面为空', degraded.idea_count === 0
          && Object.keys(degraded.stats.by_surface || {}).length === 0)
      }
      if (fc.case === 'no-gates' || fc.case === 'broken-gates') {
        expect(fc.label + ' · 判决如实报 broken（不报 clean）', healthDeg.check_verdict === 'broken',
          healthDeg.check_verdict)
        expect(fc.label + ' · 点名是判据文件的问题',
          JSON.stringify(healthDeg.errors || []).includes('gates.yaml'),
          JSON.stringify(healthDeg.errors || []).slice(0, 120))
      }

      // ③ 渲染面：真客户端 + 该退化数据，必须渲染出人话且不抛
      let rendered = null
      let renderErr = null
      try {
        rendered = await renderAsync(evSrc, { sessionId: 'sess-1' },
          (m) => m === 'ev-board-load' ? { ok: true, data: degraded }
            : (m === 'ev-health-load' ? { ok: true, data: healthDeg } : { ok: false, error: 'n/a' }))
      } catch (e) {
        renderErr = String(e && e.message || e)
      }
      expect(fc.label + ' · 渲染不抛异常', !renderErr, renderErr)
      const t = rendered ? rendered.text : ''
      expect(fc.label + ' · 四个区块编号齐全（缺件不静默消失）',
        /① 要处理的/.test(t) && /② 改动落在哪一层/.test(t)
        && /执行现场（exec-log）/.test(t) && /④ 卡片档案/.test(t), t.slice(0, 160))
      if (fc.case === 'no-exec-log' || fc.case === 'no-metrics') {
        expect(fc.label + ' · 执行现场走退化分支并给补救指引',
          /无执行记录/.test(t) && /写入一条 exec-log/.test(t), t.slice(0, 200))
        expect(fc.label + ' · 退化分支仍标注共享范围（防读成全系统）', SHARE_RE.test(t))
      }
      if (fc.case === 'empty-cards') {
        expect(fc.label + ' · 触及面说明无读数原因（不画空图）',
          /暂无卡片，因此没有这一层读数/.test(t), t.slice(0, 220))
        expect(fc.label + ' · 卡区报 0 张而不是隐藏', /④ 卡片档案/.test(t) && /0 张/.test(t))
      }
      if (fc.case === 'no-gates' || fc.case === 'broken-gates') {
        expect(fc.label + ' · 结论条标「体检器失效」而非"未见阻塞项"',
          /体检器失效/.test(t) && !/本期无阻塞项/.test(t), t.slice(0, 200))
        expect(fc.label + ' · 报出结论不成立', /结论不成立/.test(t), t.slice(0, 220))
      }
    }
    fs.rmSync(fixtureRoot, { recursive: true, force: true })
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
    // 第一跳：开卡片抽屉（2026-09 重排后卡默认收在「④ 卡片（diff 日志）」里）。
    // 这是首屏判决化的直接后果：不先开抽屉就点不到任何卡——而旧版这里能点到，正是因为
    // 旧版把卡墙直接平铺在首屏（本次要修的就是那个形态）。
    let handlers = []
    tree.forEach(t => collectHandlers(t, handlers))
    const drawerToggle = handlers.find(h => String(h.text).includes('④ 卡片档案'))
    expect('抽屉可点开（④ 卡片档案）', !!drawerToggle)
    if (drawerToggle) drawerToggle.fn({})
    tree = await pump(4)
    // 真实点击：点第一张卡的头部（onClick 挂在收起态的可点区域上）
    // 卡头特征：文本以卡 id 开头且含"共 N 条"（决策计数）；顶部筛选条不含
    const isCardHead = h => /EV-2026-0\d\d/.test(h.text) && /共 \d+ 条/.test(h.text) && !/审计缺口|最近采纳/.test(h.text)
    handlers = []
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
  // 期号/数值一律从真实数据推导——原先钉死 "live2 vs live1" 与 "7 → 11"，
  // 新增一期 live 快照（W37）后三条断言全部失真（同类第 N 次：断言钉死在可变数据上）。
  const livePeriods = periods.filter(p => p.kind === 'live')
  const cur = livePeriods[livePeriods.length - 1]
  const prev = livePeriods[livePeriods.length - 2]
  if (cur && prev) {
    expect('对照标注最新两期 live（' + prev.period + ' vs ' + cur.period + '）',
      mt.includes(cur.period) && mt.includes('对比 ' + prev.period), mt.slice(mt.indexOf('本期变化'), mt.indexOf('本期变化') + 200))
    const curV = (cur.metrics || {}).sessions_total, prevV = (prev.metrics || {}).sessions_total
    if (typeof curV === 'number' && typeof prevV === 'number' && curV !== prevV) {
      // 断言只钉"数值对照已渲染"，**不钉标签文案**——标签是给人看的，会随文案优化调整
      //（实测踩过：把"诊断 session 数"改成"诊断次数"就让这条断言假失败）
      expect('变化项 sessions_total ' + prevV + ' → ' + curV,
        new RegExp(prevV + ' → ' + curV).test(mt),
        (mt.match(new RegExp('[^\\n]{0,40}' + prevV + ' → ' + curV)) || [])[0])
    }
  } else {
    expect('live 期不足两期时不渲染对照（诚实退化）', !/对比/.test(mt))
  }
  expect('新增项标注「新增」', /新增/.test(mt))
  expect('持平项计数', /项持平/.test(mt))
  // 默认 live 筛选：只有最近 2 期展开，更早的收进「历史快照」折叠——期数 ≤2 时不该有折叠
  if (livePeriods.length > 2) expect('live 筛选：超过 2 期才出现历史折叠', /历史快照 \d+ 期/.test(mt))
  else expect('live 筛选：期数不足 2 期以上，无历史折叠', !/历史快照 \d+ 期/.test(mt))
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
    // 期卡要有读数（分子与分母一起给）。**不钉指标名**：默认展开的是最新两期，而"最新两期里
    // 有哪些指标"会随新快照变——旧断言钉的是当时恰好被展开的最旧一期里的"路由准确率 3/3"，
    // 一旦默认展开的期次修正为最新两期，它就假失败（实测）。
    expect('期卡带指标读数（分子/分母一起给）', /\d+\/\d+/.test(mtAll),
      (mtAll.match(/[^\n]{0,14}\d+\/\d+[^\n]{0,10}/) || [])[0])
    expect('收起态标注项数（N 项）', /\d+ 项/.test(mtAll))
  }
  expect('知识库健康保留', mt.includes('知识库健康'))
  expect('流程闭环保留', mt.includes('流程闭环'))
  expect('实时计算保留', mt.includes('实时计算'))
  expect('默认收起期卡数量少于总期数（避免平铺）', (mt.match(/项$/gm) || []).length <= periods.length)

  // ================= 指标 tab · 数据源的三种结局（2026-09-13 补）=================
  // 为什么单开这一节：上面所有指标断言都把 periods **从 Python 直接喂给客户端**，不经过 host 的
  // parseTimeline——于是"解析器与真实文件结构不符"这条能一路漏到用户面前：实测 `metrics/timeline.yaml`
  // 里有 8 期（含 3 期 live），host 解析出 0 期，面板因此显示「尚无 live 快照」并把最新一期折进
  // 「历史快照」。数据在、结论假，正是这块面板反复修的那类缺陷，而当时的 364 条断言一条都盖不到它
  // （喂的是 Python 解析结果，等于绕过了被怀疑的那一层）。第一条断言就是"解析器与权威口径逐条对齐"。
  console.log('\n[ascend-panel 指标 · 数据源三态]')
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    const from = hostSrc.indexOf('function parseFlowValue')
    const to = hostSrc.indexOf('async function loadTimeline')
    expect('host timeline 解析器可抽出（parseFlowValue → loadTimeline 区块存在）', from > 0 && to > from)
    const tl = new Function(hostSrc.slice(from, to) + '\nreturn { parseTimeline: parseTimeline };')()
    const tlText = fs.readFileSync(path.join(repo, 'metrics/timeline.yaml'), 'utf8')
    const jsPeriods = tl.parseTimeline(tlText)
    expect('真实 timeline.yaml：解析出 ' + jsPeriods.length + ' 期（Python 口径 ' + periods.length + ' 期）',
      jsPeriods.length === periods.length && jsPeriods.length > 0,
      'js=' + jsPeriods.length + ' py=' + periods.length)
    expect('真实 timeline.yaml：期号与 kind 逐条一致（不是只读出壳子）',
      jsPeriods.length === periods.length && jsPeriods.every((p, i) => p.period === periods[i].period && p.kind === periods[i].kind),
      jsPeriods.map(p => String(p.period) + '/' + String(p.kind)).join(',') + ' | ' + periods.map(p => String(p.period) + '/' + String(p.kind)).join(','))
    const jsM = jsPeriods.map(p => Object.keys(p.metrics || {}).length)
    const pyM = periods.map(p => Object.keys(p.metrics || {}).length)
    expect('真实 timeline.yaml：每期指标键数一致', JSON.stringify(jsM) === JSON.stringify(pyM), jsM.join(',') + ' | ' + pyM.join(','))
    expect('真实 timeline.yaml：live 期被认出来（≥1 期）', jsPeriods.filter(p => p.kind === 'live').length >= 1)
    expect('真实 timeline.yaml：notes 也读到了（期卡展开要显示）', jsPeriods.some(p => String(p.notes || '').trim().length > 0))

    // 加载窗口：判决 RPC 未返回时**不能说"没问题"**。窗口真实存在——timeline 是文件读，
    // 判决要 spawn Python；旧实现在这段窗口里按"0 条 findings"走绿分支，打印
    // 「本期无阻塞项 · 按 0 条判据检查，全部通过」（"按 0 条判据检查"本身是结论不可用）。
    const pendingHost = (m, a) => m === 'ascend-metrics-verdict' ? new Promise(() => {}) : ascHost(m, a)
    const pend = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, pendingHost)).text
    expect('判决未返回：不显示「本期无阻塞项」', !pend.includes('本期无阻塞项'),
      pend.slice(Math.max(0, pend.indexOf('现在什么坏了')), Math.max(0, pend.indexOf('现在什么坏了')) + 140))
    expect('判决未返回：不显示「全部通过」', !pend.includes('全部通过'))
    expect('判决未返回：如实说"读取中 / 待载入"', /读取中|体检待载入/.test(pend))
    expect('判决未返回：结论未到就不给状态色（源码里 pending 与 error 同走中性边）', /\(error \|\| pending\) \? T\.border/.test(ascSrc))

    // timeline 读不到：判决与实时计算**照常**（旧实现一行早退把整页藏了，与 host 自己的提示相反）
    const noTl = (m, a) => m === 'ascend-metrics-load' ? { ok: false, error: 'timeline.yaml 不可读: 缺文件' } : ascHost(m, a)
    const nt = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, noTl)).text
    expect('timeline 读不到：明说期次不可读', nt.includes('期次与趋势不可读'), nt.slice(0, 120))
    expect('timeline 读不到：判决卡仍在（不整页早退）', nt.includes('现在什么坏了'))
    expect('timeline 读不到：实时计算仍在（host 的承诺与界面一致）', nt.includes('实时计算'))
    expect('timeline 读不到：不谎称「尚无 live 快照」', !nt.includes('尚无 live 快照'))
    expect('timeline 读不到：头部计数如实（不是 0 期 · live 0）', nt.includes('期次不可读'))

    // 解析不出期次（结构与解析器不符）：必须与"没有数据"分开说
    const unparsed = (m, a) => m === 'ascend-metrics-load' ? { ok: true, periods: [], integrity: 'unparsed' } : ascHost(m, a)
    const up = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, unparsed)).text
    expect('期次解析不出：说清"不是没有数据"', /一条都没解析出来/.test(up) && /不是"没有数据"/.test(up), up.slice(0, 160))
    expect('期次解析不出：不显示「尚无 live 快照」', !up.includes('尚无 live 快照'))
    expect('期次解析不出：给可复现命令', /build_timeline\.py --check/.test(up))
    expect('期次解析不出：头部计数如实', up.includes('期次解析失败'))

    // 默认展开"最新的两期"（旧实现展开的是最旧两期，最新一期被折进历史）
    {
      const sorted = periods.filter(p => p.kind === 'live').slice()
        .sort((a, b) => {
          const wk = (p) => { const w = /(\d{4})-W(\d{2})/.exec(String(p.period)); return w ? Number(w[1]) * 100 + Number(w[2]) : -1 }
          return wk(a) - wk(b) || String(a.recorded_at || '').localeCompare(String(b.recorded_at || ''))
        })
      const clean = (s) => String(s || '').replace(/\*\*/g, '').replace(/`/g, '').trim()
      const newest = sorted.length ? clean(sorted[sorted.length - 1].notes).slice(0, 24) : ''
      const oldest = sorted.length ? clean(sorted[0].notes).slice(0, 24) : ''
      if (newest && oldest && newest !== oldest) {
        expect('默认展开的是最新两期：最新一期 notes 可见（' + sorted[sorted.length - 1].period + '）', mt.includes(newest))
        expect('默认展开的是最新两期：最旧一期收在历史折叠里（' + sorted[0].period + '）', !mt.includes(oldest))
        expect('历史折叠报出被收起几期', /历史快照 \d+ 期/.test(mt))
      } else {
        expect('默认展开顺序：样本没有可比 notes，跳过（如实标注）', true)
      }
    }
    // 期卡上的数据文案不得把 Markdown 语法端上屏（notes 是数据，里面有 `**重点**` 这类强调）
    expect('期卡数据文案去掉字面 Markdown 星号与反引号（面板不是渲染器）',
      /function plainNote\(s\)/.test(ascSrc) && /plainNote\(p\.notes\)/.test(ascSrc))
    const w37 = periods.filter(p => String(p.notes || '').includes('**'))[0]
    if (w37) {
      const shown = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, ascHost)).text
      expect('真实 notes 里的强调标记不再上屏（' + w37.period + '）', !/\*\*/.test(shown))
    }
  }

  // ================= 指标 tab · 闭环判决（2026-09 重做） =================
  // 这一节钉住的是"聚焦"这件事本身：判据读 gates.yaml（面板不重算）、
  // 分母为 0 的指标被标成不可解读（不是 0）、容量按**格子**比（不是加总到 namespace）、
  // 以及面板读的数据源陈旧时如实报 drift。
  console.log('\n[ascend-panel 指标 · 闭环判决]')
  const gatesDoc = JSON.parse(pyRun(['-c', `
import yaml, json
d = yaml.safe_load(open('metrics/gates.yaml', encoding='utf-8'))
print(json.dumps({
  'gates': d.get('gates') or [],
  'readability': d.get('readability') or [],
  'freshness': d.get('freshness') or {},
}, ensure_ascii=False))
`], { cwd: repo, env: PY_ENV }).toString())
  const verdict = JSON.parse(pyRun(['scripts/metrics_health.py', '--json'], { cwd: repo, maxBuffer: 16 * 1024 * 1024, env: PY_ENV }).toString())
  const cells = verdict.capacity_cells || []
  const hot = cells.filter(c => c.soft || c.hard)
  const softVal = (verdict.gates || []).filter(g => g.id === 'cell_soft_cap').map(g => g.value)[0]
  const hardVal = (verdict.gates || []).filter(g => g.id === 'cell_hard_cap').map(g => g.value)[0]

  // —— 数据契约：体检脚本必须把面板要用的东西都给全（缺一项面板就会静默少一块）——
  expect('体检 JSON 含 gates（阈值只在 gates.yaml 一处）', Array.isArray(verdict.gates) && verdict.gates.length > 0)
  expect('体检 JSON 含 readability 判定', verdict.readability && typeof verdict.readability === 'object')
  expect('体检 JSON 含 capacity_cells（逐格）', cells.length > 0, '格数 ' + cells.length)
  expect('体检 JSON 含 freshness', !!(verdict.freshness && typeof verdict.freshness === 'object'))
  expect('体检 JSON 含 candidate_commands', Array.isArray(verdict.candidate_commands) && verdict.candidate_commands.length > 0)

  // —— 判据强度：面板报的越界格 == 按 gates.yaml 阈值独立算出的越界格（口径一份）——
  const expectSoft = cells.filter(c => (verdict.gates || []).some(g => g.dimension === 'capacity_cell'
    && ((g.op === '>' && c.count > g.value) || (g.op === '>=' && c.count >= g.value))))
  expect('容量越界格数与判据一致（面板 ' + hot.length + ' == 独立计算 ' + expectSoft.length + '）', hot.length === expectSoft.length)
  expect('hard_cap 那格被判成硬越界', hot.every(c => (c.count >= hardVal) === !!c.hard), JSON.stringify(hot.slice(0, 2)))
  expect('soft_cap 阈值来自 gates.yaml（' + softVal + '）', softVal === 30)

  // —— `--check` 的三态：0 判据全评过且无越界 / 1 有判据被违反 / 2 有判据未被评估 ——
  // 为什么必须测 2：修前 `--check` 只用"有没有 ✗"映射 0/1，于是**"体检器坏了"与"本期确实
  // 没有违规"不可区分**；实测过两回假绿——漏解包让容量判据恒不触发、gates.yaml 解析失败
  // 被 `except: return {}` 吞掉后体检器照样报 clean。这一节用夹具造出"判据不可评估"，
  // 钉住它必须报 2 而不是 0。
  {
    const os = require('os')
    const { execFileSync } = require('child_process')
    const tmpBase = fs.mkdtempSync(path.join(os.tmpdir(), 'sleu-broken-'))
    const runCase = (caseName) => {
      const out = path.join(tmpBase, caseName)
      execFileSync(PY.cmd, [...PY.prefix, 'scripts/fixtures/make_broken_metrics_root.py',
        '--repo', repo, '--out', out, '--case', caseName], { cwd: repo, env: PY_ENV, stdio: 'pipe' })
      let exit = 0
      let stdout = ''
      try {
        stdout = pyRun(['scripts/metrics_health.py', '--json', '--check', '--root', out],
          { cwd: repo, env: PY_ENV, maxBuffer: 16 * 1024 * 1024 }).toString()
      } catch (e) {
        exit = e.status === undefined ? -1 : e.status
        stdout = (e.stdout || '').toString()
      }
      let doc = null
      try { doc = JSON.parse(stdout) } catch (e) { doc = null }
      return { exit, doc }
    }
    const a = runCase('A')
    expect('判据被声明但没实现 → --check exit 2（不是 0）', a.exit === 2, 'exit=' + a.exit)
    expect('  且 verdict=broken、coverage 报出缺口',
      !!a.doc && a.doc.check_verdict === 'broken' && a.doc.coverage.gates_evaluated < a.doc.coverage.gates_total,
      a.doc ? a.doc.coverage.gates_evaluated + '/' + a.doc.coverage.gates_total : '无 JSON')
    expect('  且点名是哪条判据没实现',
      !!a.doc && (a.doc.broken || []).some(b => /brand_new_gate|not_implemented_dim/.test(b)),
      a.doc ? JSON.stringify(a.doc.broken).slice(0, 120) : '')
    const b = runCase('broken_config')
    expect('判据文件语法坏掉 → --check exit 2 且不得报 clean', b.exit === 2 && !!b.doc && b.doc.check_verdict !== 'clean',
      b.doc ? 'exit=' + b.exit + ' verdict=' + b.doc.check_verdict : 'exit=' + b.exit)
    expect('  且说清是"配置读不动"而不是"没有越界"',
      !!b.doc && (b.doc.broken || []).some(x => /gates\.yaml/.test(x)), b.doc ? JSON.stringify(b.doc.broken).slice(0, 140) : '')
    fs.rmSync(tmpBase, { recursive: true, force: true })
  }
  expect('真实数据下 verdict=violations 且判据全部评过（3/3）',
    verdict.check_verdict === 'violations' && verdict.coverage.gates_evaluated === verdict.coverage.gates_total,
    verdict.check_verdict + ' ' + verdict.coverage.gates_evaluated + '/' + verdict.coverage.gates_total)
  expect('真实数据下 --check exit 1（有越界、判据都评过）', (() => {
    try { pyRun(['scripts/metrics_health.py', '--check'], { cwd: repo, env: PY_ENV, stdio: 'pipe' }); return false }
    catch (e) { return e.status === 1 }
  })())

  // —— drift：面板读的是生成物索引，必须能与磁盘对照 ——
  // 数的是**索引里真实列出的条目**（不是头注里的一个数字）：头注那几个数已经拿掉了——它们进 git
  // 就会在两人并发合并时撞行或漂移（现算：scripts/index_counts.py）。数条目反而更准：
  // 索引丢了一条，这里就少一条。
  const idxText = fs.readFileSync(path.join(repo, 'knowledge/_index.yaml'), 'utf8')
  const declared = idxText.split(/\r?\n/).filter(l => /^- id:\s*\S/.test(l.trim())).length
  const diskCount = JSON.parse(pyRun(['-c', `
import json, pathlib
n = 0
for p in pathlib.Path('knowledge').rglob('*.yaml'):
    if p.name.startswith('_'): continue
    if '_index' in p.parts: continue
    n += 1
print(json.dumps(n))
`], { cwd: repo, env: PY_ENV }).toString())
  expect('索引里列出的条目数可数（' + declared + '）', Number.isFinite(declared) && declared > 0)
  expect('磁盘 case 文件数可扫描（' + diskCount + '）', diskCount > 0)

  // —— 渲染：判决条 / 不可解读 / 容量台账 ——
  const healthCases = {
    total: declared, lowConfidence: 12, byCategory: { interrupt: 30, performance: 10, precision: 12 },
    byCell: cells.slice(0, 4), liveTotal: declared, declaredTotal: declared, diskTotal: diskCount,
  }
  const hostWithVerdict = (method, args) => {
    if (method === 'ascend-metrics-verdict') return { ok: true, verdict: Object.assign({}, verdict, {
      drift: { declared: declared, disk: diskCount },
      // 三态取真实体检的输出（真实数据是 violations/exit 1）；drift 由 host 现算，这里补上
      check_verdict: verdict.check_verdict || 'violations',
      coverage: verdict.coverage || { gates_total: 3, gates_evaluated: 3 },
    }) }
    if (method === 'ascend-kb-health') return { ok: true, cases: healthCases, references: { total: 95, draftCount: 0, staleCount: 2, byType: { tool: 20 } } }
    return ascHost(method, args)
  }
  const asc2 = await renderAsync(ascSrc, { sessionId: 'sess-1' }, hostWithVerdict)
  const vt = asc2.text
  expect('首屏出现「现在什么坏了」判决条', vt.includes('现在什么坏了'))
  expect('判决条给出判据项数', new RegExp('已检[\\s\\S]{0,12}' + (verdict.findings || []).length + '[\\s\\S]{0,6}项判据').test(vt) || /项越界/.test(vt), vt.slice(vt.indexOf('现在什么坏了'), vt.indexOf('现在什么坏了') + 200))
  // 结论行：每条 ✗/! 判据的文案（取体检的真实输出，不硬编码）
  const failFindings = (verdict.findings || []).filter(f => f.level === 'fail')
  expect('失败判据 ' + failFindings.length + ' 条渲染（结论行）', failFindings.length > 0)
  // 收起态渲染的是**人话版**（plain），技术文案（判据名/格子数/指标名）移到展开区。
  // 为什么改（2026-09 七轮，用户反馈）：旧版把 `cell_soft_cap` / `feedback_capture_floor` /
  // `misdiagnosis_rate` 这些代码里的名字直接端给读者，句子也是对着实现说的。
  const withPlain = failFindings.filter(f => f.plain)
  expect('体检脚本为每条失败判据提供人话版（' + withPlain.length + '/' + failFindings.length + '）',
    failFindings.length > 0 && withPlain.length === failFindings.length,
    failFindings.filter(f => !f.plain).map(f => f.face).join(','))
  if (withPlain.length) {
    expect('首屏出现人话版结论', vt.includes(String(withPlain[0].plain).slice(0, 24)),
      String(withPlain[0].plain).slice(0, 48))
  }
  // 人话版里不得残留实现标识符（用户不该看见判据名/指标名）
  const leaky = withPlain.filter(f => /cell_(soft|hard)_cap|feedback_capture_floor|misdiagnosis_rate|attribution_ratio|soft_cap|hard_cap/.test(String(f.plain)))
  expect('人话版不含实现标识符（判据名/指标名）', leaky.length === 0,
    leaky.map(f => String(f.plain).slice(0, 60)).join(' | '))
  // 收起态不暴露判据名（技术文案只在展开区）
  expect('收起态不直接显示判据名（cell_soft_cap 等）',
    !/\bcell_soft_cap\b|\bfeedback_capture_floor\b/.test(vt),
    (vt.match(/cell_soft_cap|feedback_capture_floor/g) || []).join(','))
  if (hot.length) {
    const h = hot.sort((a, b) => b.count - a.count)[0]
    expect('容量越界在首屏可见：' + h.namespace + ' · ' + h.category + ' = ' + h.count + '/' + h.cap,
      vt.includes(h.namespace + ' · ' + h.category) && vt.includes(h.count + '/' + h.cap),
      (vt.match(/\d+\/\d+/g) || []).slice(0, 8).join(','))
  }
  expect('容量台账标出「逐格」口径', vt.includes('逐格'))
  // 不可解读：gates.yaml 的 readability 里判成不可解读的指标，行上必须带标记（不能安静显示成 0）
  const unreadMetrics = Object.keys(verdict.readability || {}).filter(k => verdict.readability[k] && verdict.readability[k].readable === false)
  if (unreadMetrics.length) {
    expect('不可解读指标被标记（' + unreadMetrics.join(', ') + '）', vt.includes('不可解读'))
    expect('不可解读说明可查（title 带原因）', /«title:[^»]{10,}»/.test(vt), (vt.match(/«title:[^»]{0,60}»/g) || [])[0])
    expect('误诊率在本期指标里出现且带标记',
      new RegExp('误诊率[\\s\\S]{0,120}?不可解读').test(vt) || new RegExp('不可解读[\\s\\S]{0,120}?误诊率').test(vt))
  } else {
    expect('无可解读性违规时不渲染「不可解读」标记', !vt.includes('不可解读'))
  }
  expect('反馈捕获为 0 时点明「不可解读」（不是 0）', !unreadMetrics.length || /不是 0/.test(vt))
  // drift：两个方向都测，不依赖"本机此刻索引恰好陈旧"（那是会腐烂的假设——
  // 一旦重跑 build_index.py，索引与磁盘相等，只测"不等"的断言就永久失效）
  if (diskCount !== declared) {
    expect('索引≠磁盘时报 drift（索引 ' + declared + ' ≠ 磁盘 ' + diskCount + '）', vt.includes('索引 ' + declared + ' ≠ 磁盘 ' + diskCount), (vt.match(/索引 \d+ ≠ 磁盘 \d+/g) || []).join(','))
  } else {
    // 合成一次不一致，确认 drift 逻辑本身能渲染（而不是只在特定检出上碰巧成立）
    const driftHost = (method, args) => {
      if (method === 'ascend-kb-health') return { ok: true, cases: Object.assign({}, healthCases, { diskTotal: declared + 7 }), references: {} }
      if (method === 'ascend-metrics-verdict') return { ok: true, verdict: Object.assign({}, verdict, { drift: { declared: declared, disk: declared + 7 } }) }
      return hostWithVerdict(method, args)
    }
    const ascDrift = await renderAsync(ascSrc, { sessionId: 'sess-1' }, driftHost)
    expect('索引=磁盘时不渲染 drift 告警', !/索引 \d+ ≠ 磁盘 \d+/.test(vt))
    expect('合成不一致时报 drift（索引 ' + declared + ' ≠ 磁盘 ' + (declared + 7) + '）',
      ascDrift.text.includes('索引 ' + declared + ' ≠ 磁盘 ' + (declared + 7)), (ascDrift.text.match(/索引 \d+ ≠ 磁盘 \d+/g) || []).join(','))
  }
  expect('闭环检验折叠区可查（判据全貌）', vt.includes('闭环检验'))
  expect('标注判据来源（gates.yaml）', vt.includes('gates.yaml'))
  // 判据覆盖面：状态条要报"评过几条"——"没报越界"与"没被检查"是两件事
  expect('状态条报判据覆盖面（' + (verdict.coverage || {}).gates_evaluated + '/' + (verdict.coverage || {}).gates_total + '）',
    new RegExp('判据 ' + (verdict.coverage || {}).gates_evaluated + '/' + (verdict.coverage || {}).gates_total).test(vt),
    (vt.match(/判据 \d+\/\d+/g) || []).join(','))
  // 历史趋势条：容量是唯一有多个数据点的通道——**数据有三种形状**（{count,cap} 字典 /
  // "36/30" 字符串 / 整块缺席），断言按同一口径独立重算，避免"只认一种形状→永远画不出来"
  const normCap = (v) => {
    if (typeof v === 'number') return { count: v }
    if (typeof v === 'string') { const m = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(v); return m ? { count: Number(m[1]) } : null }
    if (v && typeof v === 'object' && typeof v.count === 'number') return { count: v.count }
    return null
  }
  const capPoints = (ns, cat) => {
    const out = []
    periods.forEach(p => {
      const cb = p.metrics && p.metrics.capacity_by_ns
      if (!cb) return
      const at = normCap(cb[ns] && cb[ns][cat]) || normCap(cb[cat])
      if (at) out.push({ period: p.period, count: at.count })
    })
    return out
  }
  const withSeries = cells.filter(c => capPoints(c.namespace, c.category).length >= 2)
  if (withSeries.length) {
    const sample = withSeries[0]
    const pts = capPoints(sample.namespace, sample.category)
    expect('容量趋势条渲染（' + withSeries.length + ' 格有 ≥2 期数据，用三种形状归一）', /«cls:sleu-bar/.test(vt),
      '例：' + sample.namespace + '·' + sample.category + ' ' + pts.map(x => x.count).join('→'))
    const delta = pts[pts.length - 1].count - pts[0].count
    expect('趋势条标出走势与净增量（' + pts[0].count + '→' + pts[pts.length - 1].count + ' (' + (delta > 0 ? '+' : '') + delta + ')）',
      vt.includes(pts[0].count + '→' + pts[pts.length - 1].count + ' (' + (delta > 0 ? '+' : '') + delta + ')'),
      (vt.match(/\d+→\d+ \([+-]\d+\)/g) || []).slice(0, 4).join(' | '))
  } else {
    expect('无 ≥2 期同口径数据时不画趋势条（诚实退化）', !/«cls:sleu-bar/.test(vt))
  }
  // 收起态**不该**摊开动作正文（否则又变成一屏文字）；但必须给出"点开有下一步"的指路，
  // 并且真给出可点区域（下一节用真实点击验证）。动作正文与指令在展开态断言。
  expect('判决条提示「点开看证据与下一步」', vt.includes('点开看证据与下一步'))
  expect('收起态不摊开动作正文（下一步动作标题只在展开后出现）', !vt.includes('下一步动作'))

  // —— 点开一条判决行：应给出证据与可复制指令 ——
  {
    const registrations = []
    const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
    const host = { call: (m, a) => Promise.resolve(hostWithVerdict(m, a)) }
    const stylesGlobal = { insert(css) { cssChunks.push(css); return () => {} } }
    const plugin = new Function('React', 'host', 'styles', 'return (function(){' + ascSrc + '})()')(React, host, stylesGlobal)
    plugin.apply(ctx)
    const renderTree = () => { effectQueue = []; hookIdx = 0; const o = []; registrations.forEach(r => o.push(r.c({ sessionId: 'sess-1' }))); return o }
    const textOf = t => { const o = []; flatten(t, o); return o.join('\n') }
    const pump = async (rounds) => {
      let tree = null
      for (let i = 0; i < rounds; i++) {
        tree = renderTree()
        effectQueue.slice().forEach(f => f())
        await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
      }
      return tree
    }
    let tree = await pump(6)
    const hs = []
    tree.forEach(t => collectHandlers(t, hs))
    // 判决行 = 可点区域里含**人话版**结论的那一个（收起态渲染 plain，技术文案在展开区）
    const want = failFindings.length ? String(failFindings[0].plain || failFindings[0].text).slice(0, 24) : null
    const row = want ? hs.find(h => String(h.text).includes(want)) : null
    let clicked = 0
    if (row) { row.fn({}); clicked = 1 }
    tree = await pump(5)
    const dt = textOf(tree)
    expect('点开判决行（' + clicked + ' 次）', clicked === 1, want || 'no fail finding')
    if (clicked) {
      expect('展开后给出「下一步动作」', dt.includes('下一步动作'))
      expect('展开后给出「可复制指令」', dt.includes('可复制指令'))
      // 展开区必须能回查判据：技术文案（判据名/格子数/指标名）在这里出现
      expect('展开后给出判据出处（可回查配置）', dt.includes('判据出处'))
      expect('展开后出现技术文案（判据名/指标名）',
        failFindings.some(f => dt.includes(String(f.text).slice(0, 30))),
        String(failFindings[0] && failFindings[0].text).slice(0, 50))
      expect('展开后指令含真实脚本/技能名（可执行，不是空话）', /scripts\/|skill:/.test(dt))
      expect('展开后给出判据动作原文（来自 gates.yaml action）',
        failFindings.some(f => f.action && dt.includes(String(f.action).slice(0, 20))))
    }
  }

  // —— 体检器失效态：三态里的"broken"必须有独立的处置含义 ——
  // 修前只看"有没有 ✗"，"体检器坏了"与"本期没事"都是 exit 0；面板上也只显示一句"闭环未见阻塞项"。
  {
    const brokenHost = (method, args) => {
      if (method === 'ascend-metrics-verdict') return { ok: true, verdict: {
        findings: [], fail_count: 0, last_live: '2026-W37-live',
        freshness: { live_age_days: 1, live_limit_days: 7, live_periods: 3, structural_periods: 4 },
        gates: verdict.gates, readability: {}, capacity_cells: [], candidate_commands: [],
        current: { case_total: declared, reference_total: 130 },
        drift: { declared: declared, disk: diskCount },
        exit_code: 2, check_verdict: 'broken',
        broken: ['闸门 brand_new_gate（dimension=not_implemented_dim）没有评估实现——这条判据不会被检查'],
        coverage: { gates_total: 4, gates_evaluated: 3, readability_total: 2, readability_evaluated: 2 },
      } }
      if (method === 'ascend-kb-health') return { ok: true, cases: healthCases, references: {} }
      return ascHost(method, args)
    }
    const bt = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, brokenHost)).text
    expect('体检器失效：状态条标「体检器失效」', bt.includes('体检器失效'))
    expect('体检器失效：不显示「闭环未见阻塞项」（不把"没结论"读成"没问题"）', !bt.includes('闭环未见阻塞项'))
    expect('体检器失效：说清"没报越界 ≠ 没有越界"', /不等于/.test(bt), bt.slice(bt.indexOf('本轮判据不完整'), bt.indexOf('本轮判据不完整') + 220))
    // 版式契约（用户视角）：首屏先说"哪几项没跑 + 所以结论怎样"，
    // **工程诊断默认不端出来**——原始异常串/覆盖率/复现命令收在「为什么没跑 / 怎么复现」折叠里。
    // 旧版把 `PermissionError: [WinError 5] 拒绝访问。`、覆盖率与"含义：…**不等于**…"（星号还是
    // 字面量）一起平铺，读者先撞见实现细节才轮到"我要做什么"——这是"看着吃力"的来源之一。
    expect('体检器失效：先说"哪几项没跑"（用户语）', /这几项判据本轮没跑|本轮没跑/.test(bt))
    expect('体检器失效：收起态不暴露原始异常串', !/PermissionError|Traceback|WinError/.test(bt))
    expect('体检器失效：收起态不摊开三态退出码语义', !/判据全评过且无越界 · 1 有判据被违反/.test(bt))
    expect('体检器失效：提供折叠入口「为什么没跑 / 怎么复现」', bt.includes('为什么没跑 / 怎么复现'))
    // 状态条的说法必须与横幅一致：不能说"判据 3/3 全部被评估"又说"判据不完整"
    // （实测就是这么自相矛盾的——读者会以为其中一句在骗人）
    expect('体检器失效：状态条改说「本轮有判据没跑」（不与横幅矛盾）', /本轮有判据没跑/.test(bt))
    expect('体检器失效：状态条不再同时宣称「判据 3/3」', !/判据 3\/3/.test(bt), (bt.match(/判据 \d+\/\d+/g) || []).join(','))
    expect('体检器失效：文案里不残留 Markdown 星号（会渲染成字面量）', !/\*\*/.test(bt), (bt.match(/\*\*[^*]{0,20}/) || [])[0])
    // 展开折叠后：诊断信息与复现命令应当都在
    {
      const registrations = []
      const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
      const host = { call: (m, a) => Promise.resolve(brokenHost(m, a)) }
      const plugin = new Function('React', 'host', 'styles', 'return (function(){' + ascSrc + '})()')(React, host, { insert: () => () => {} })
      plugin.apply(ctx)
      const renderTree = () => { effectQueue = []; hookIdx = 0; const o = []; registrations.forEach(r => o.push(r.c({ sessionId: 'sess-1' }))); return o }
      const textOf = t => { const o = []; flatten(t, o); return o.join('\n') }
      const pump = async (rounds) => {
        let tree = null
        for (let i = 0; i < rounds; i++) {
          tree = renderTree()
          effectQueue.slice().forEach(f => f())
          await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
        }
        return tree
      }
      let tree = await pump(6)
      const hs = []
      tree.forEach(t => collectHandlers(t, hs))
      const toggle = hs.find(h => String(h.text).includes('为什么没跑'))
      let clicked = 0
      if (toggle) { toggle.fn({}); clicked = 1 }
      tree = await pump(4)
      const dt = textOf(tree)
      expect('展开「为什么没跑 / 怎么复现」（' + clicked + ' 次）', clicked === 1)
      if (clicked) {
        expect('展开后：点名哪条判据没被评估', dt.includes('brand_new_gate'))
        expect('展开后：给出复现命令', dt.includes('scripts/metrics_health.py'))
        expect('展开后：说明三态退出码语义', /0 判据全评过且无越界 · 1 有判据被违反 · 2 有判据未被评估/.test(dt))
      }
    }
  }

  // —— host 侧：体检失败时的自诊断与上下文守卫 ——
  // 这几条是 2026-09-11 实测事故的直接产物：`resolveCwd()` 拿不到工作区时返回 undefined，
  // `shell.resolve({workdir: undefined})` 不报错，于是命令在别的目录下执行、Python 报错，
  // 而面板用 `slice(0,400)` 把 traceback 的头截下来——**连异常类型都被截掉**，无从定位。
  // 手法：从**真实源文件**里抽出 runMetricsHealth 与 shellFail 的函数体，配桩运行（不复制逻辑，
  // 改了源文件这里就跟着变；逻辑一复制，断言就退化成"我自己跟自己对"）。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    // 抽取器：本文件里这些函数都嵌在 apply() 内，缩进 4 空格；函数结束 = 一行恰为 `    }`。
    // 不用花括号配平：函数体里有字符串/正则里的花括号与中文注释，配平不可靠（实测截出过半截代码）。
    const grab = (name) => {
      const lines = hostSrc.split(/\r?\n/)
      const startIdx = lines.findIndex(l => /^    (async )?function /.test(l) && l.indexOf('function ' + name) > 0)
      if (startIdx < 0) return null
      for (let i = startIdx + 1; i < lines.length; i++) {
        if (lines[i] === '    }') return lines.slice(startIdx, i + 1).join('\n')
      }
      return null
    }
    const fnSrc = [grab('shellFail'), grab('runMetricsHealth')].filter(Boolean).join('\n')
    expect('能从 host 源文件抽出 runMetricsHealth + shellFail', !!grab('shellFail') && !!grab('runMetricsHealth'))

    const build = async (shellStub) => {
      // 抽出来的函数体里有 await → 必须包在 async 函数里（new Function 体本身不是 async）。
      // 注意：这样 factory(...) 返回的是 **Promise**，必须 await（踩过：直接取属性拿到空对象）
      const factory = new Function('shell', 'resolvePython',
        'return (async () => {\n' + fnSrc + '\nreturn { runMetricsHealth, shellFail }\n})()')
      return await factory(shellStub, async () => 'python')
    }

    // ① 没有工作区：必须**不发起命令**并说清缺口
    {
      let calls = 0
      const mod = await build({ resolve: (x) => x, run: async () => { calls++; return { exitCode: 0, stdout: { text: '' }, stderr: { text: '' } } } })
      const r = await mod.runMetricsHealth(undefined)
      expect('无工作区：如实报"拿不到会话工作区"', r.ok === false && /拿不到会话工作区/.test(r.error), String(r.error).slice(0, 80))
      expect('无工作区：不发起注定失败的命令（0 次 shell 调用）', calls === 0, 'calls=' + calls)
      expect('无工作区：给出手工复现路径', r.ok === false && /scripts\/metrics_health\.py/.test(r.error))
    }
    // ② 脚本报错：必须带执行上下文与 stderr **尾部**（traceback 的结论在最后几行）
    {
      const longTrace = ['Traceback (most recent call last):']
        .concat(Array.from({ length: 40 }, (_, i) => '  line ' + i + ' in some_frame  # 填充，把异常类型挤出头部'))
        .concat(['PermissionError: [WinError 5] Access is denied'])
        .join('\n')
      const mod = await build({
        resolve: (x) => x,
        run: async () => ({ exitCode: 1, timedOut: false, stdout: { text: '' }, stderr: { text: longTrace } }),
      })
      const r = await mod.runMetricsHealth('E:/projects/ascend-sleuth')
      expect('脚本报错：保留 traceback 尾部（异常类型可见）', r.ok === false && /PermissionError/.test(r.error), String(r.error).slice(-90))
      expect('脚本报错：带上执行上下文（解释器/工作目录/命令/退出码）',
        r.ok === false && /解释器 python/.test(r.error) && r.error.includes('E:/projects/ascend-sleuth')
        && /--json/.test(r.error) && /exit 1/.test(r.error), String(r.error).slice(0, 160))
      expect('脚本报错：错误串收敛为有限行数（不把整页撑爆）',
        r.ok === false && r.error.split('\n').length <= 8, 'lines=' + String(r.error).split('\n').length)
      expect('脚本报错：结构化字段可供上层判读（py/cwd/exitCode/stderrTail）',
        r.py === 'python' && r.cwd === 'E:/projects/ascend-sleuth' && r.exitCode === 1 && /PermissionError/.test(r.stderrTail))
    }
    // ③ 正常输出：仍然解析成 verdict
    {
      const mod = await build({
        resolve: (x) => x,
        run: async () => ({ exitCode: 0, timedOut: false, stdout: { text: JSON.stringify(verdict) }, stderr: { text: '' } }),
      })
      const r = await mod.runMetricsHealth('E:/projects/ascend-sleuth')
      expect('正常输出：解析为 verdict（不因加了防御而破坏正路）', r.ok === true && !!r.verdict && r.verdict.check_verdict === verdict.check_verdict)
    }
  }

  // —— 体检脚本在受限执行环境下的两条路径（管道被拒）——
  // 实测事故（验收当天）：面板里体检报 `PermissionError: [WinError 5] 拒绝访问。`——
  // `collect_structural` 内部用 `subprocess.run(capture_output=True)` 跑 verify_references.py，
  // 而受限环境里**管道创建**被拒 → 异常冒到模块级 → 整轮体检崩掉，连容量越界都一起没了。
  // 修法：管道被拒时回退到**文件重定向**（同样拿到输出），连回退也不成才如实报降级。
  // 两个场景都要钉住——只测"降级不崩"会漏掉"其实能跑通"这个更好的结局。
  {
    const runCase = (patchCode) => JSON.parse(pyRun(['-c', `
import sys, subprocess, json, io, contextlib
sys.path.insert(0, 'scripts')
${patchCode}
import metrics_health as MH
buf = io.StringIO()
sys.argv = ['metrics_health.py', '--json']
with contextlib.redirect_stdout(buf):
    rc = MH.main()
out = buf.getvalue()
doc = None
try:
    doc = json.loads(out[out.index('{'):out.rindex('}') + 1])
except Exception:
    pass
print(json.dumps({
    'rc': rc,
    'verdict': (doc or {}).get('check_verdict'),
    'cells': len((doc or {}).get('capacity_cells') or []),
    'broken': (doc or {}).get('broken') or [],
    'has_json': doc is not None,
}))
`], { cwd: repo, env: PY_ENV, maxBuffer: 16 * 1024 * 1024 }).toString())

    // A. 管道被拒，但文件重定向可用 → 必须**无损**（容量判据照常评估，不降级）
    const A = runCase(`_orig = subprocess.run
def guarded(*a, **k):
    if k.get('capture_output'):
        raise PermissionError('[WinError 5] Access is denied (simulated pipe denial)')
    return _orig(*a, **k)
subprocess.run = guarded`)
    expect('管道被拒：回退到文件重定向后仍产出 JSON', A.has_json === true)
    expect('管道被拒：容量判据**不降级**（格子数 > 0）', A.cells > 0, 'cells=' + A.cells)
    expect('管道被拒：结论照常可用（verdict=' + A.verdict + '，非 broken）', A.verdict !== 'broken', 'broken=' + JSON.stringify(A.broken).slice(0, 120))
    expect('管道被拒：不误报"结构侧采集失败"', !A.broken.some(b => /结构侧采集失败/.test(b)))

    // B. 连文件重定向也失败 → 必须降级且**如实说**，而不是崩掉整轮
    const B = runCase(`_orig = subprocess.run
def guarded(*a, **k):
    if k.get('capture_output'):
        raise PermissionError('[WinError 5] Access is denied (simulated pipe denial)')
    return _orig(*a, **k)
subprocess.run = guarded
def no_fallback(*a, **k):
    raise PermissionError('[WinError 5] Access is denied (simulated fallback denial)')
import metrics_snapshot as _MS
_MS._run_no_pipe = no_fallback`)
    expect('连回退也失败：仍产出 JSON（不崩）', B.has_json === true)
    expect('连回退也失败：如实报「结构侧采集失败」并说明容量判据未被评估',
      B.broken.some(b => /verify_references.*失败|结构侧/.test(b) && /词条数取不到|未被评估/.test(b)), JSON.stringify(B.broken).slice(0, 160))
    expect('连回退也失败：verdict=broken（不可判定，不是"没事"）', B.verdict === 'broken', 'verdict=' + B.verdict)
  }

  // —— 排版契约（2026-09 六轮）——
  // 用户反馈"字体小、看着累"。实测原状：字号有 9 档却只差 3.5px（9.5→13）、正文 11–12px、
  // 中文 line-height 只有 1.5。这几条断言把"字体栈走 token、字号有尺度、中文行高够松"钉住，
  // 防止后续又漂回"每处各写各的"。
  {
    const typo = ascSrc
    const fams = [...new Set([...typo.matchAll(/fontFamily: '([^']+)'/g)].map(m => m[1]))]
    expect('字体栈走 token（不再内联 system-ui 字面量）',
      fams.every(f => f.startsWith('var(--font-')), fams.join(' | '))
    expect('声明了 sans / mono / num 三套字体 token',
      /--font-sans:/.test(typo) && /--font-mono:/.test(typo) && /--font-num:/.test(typo))
    const sizes = [...new Set([...typo.matchAll(/fontSize: ([\d.]+)/g)].map(m => Number(m[1])))]
    expect('字号档位 ≤ 8 档（原 9 档只差 3.5px = 无尺度）', sizes.length <= 8, sizes.sort((a, b) => a - b).join(' '))
    // token 与内联必须**同一集合**：否则声明的尺度是摆设，实现里另有一套
    //（实测：加会话卡状态条与卡片标题时各塞了一个新值，档位从 8 漂到 9）
    const tokenSizes = [...new Set([...typo.matchAll(/--t-[a-z0-9]+:\s*([\d.]+)px/g)].map(m => Number(m[1])))]
    const sameSet = JSON.stringify(sizes.slice().sort((a, b) => a - b)) === JSON.stringify(tokenSizes.slice().sort((a, b) => a - b))
    expect('内联字号集合 == --t-* 声明集合（尺度不是摆设）', sameSet,
      '内联: ' + sizes.join(',') + ' | token: ' + tokenSizes.join(','))
    expect('最小 UI 字号 ≥ 10（原 9.5 太小）', Math.min(...sizes) >= 10, 'min=' + Math.min(...sizes))
    expect('基准字号 ≥ 14（原 13，中文在 11–12px 会糊）', sizes.some(s => s >= 14), sizes.join(' '))
    expect('声明了语义字号 token（--t-*）', /--t-base:/.test(typo) && /--t-tiny:/.test(typo) && /--t-2xl:/.test(typo))
    expect('中文行高 ≥ 1.6（原 1.5 偏挤）',
      /--lh-prose:1\.[678]/.test(typo) && /--lh-base:1\.[6-9]/.test(typo))
    expect('数字用等宽对齐（tabular-nums）', /font-variant-numeric:tabular-nums/.test(typo) || /"tnum" 1/.test(typo))
    expect('面板根挂 .sleu（字体与排版的唯一落点）', /className: 'sleu'/.test(typo))
    // 现代观感的三件套：分层阴影 / 圆角尺度 / 交互反馈
    expect('阴影分层为 token（--elev-1/2）', /--elev-1:/.test(typo) && /--elev-2:/.test(typo))
    expect('圆角尺度为 token（--r-sm/md/lg）', /--r-sm:/.test(typo) && /--r-md:/.test(typo))
    expect('交互反馈走 class（行 hover / 卡抬升 / chip）',
      /\.sleu-row:hover/.test(typo) && /\.sleu-card:hover/.test(typo) && /\.sleu-chip:hover/.test(typo))
    expect('prefers-reduced-motion 兜底仍在', /prefers-reduced-motion/.test(typo))
  }

  // —— 诊断 tab：轨迹时间轴 / 卡片摘要 / 回到顶部（2026-09 八轮）——
  // 这三条都是"少点一次"的收益，用合成会话数据断言（真实 traces/ 在本机不存在）。
  {
    const rpcCalls = []
    const mkSession = (i, over) => Object.assign({
      sessionId: 'sess-' + String(i).padStart(3, '0'),
      file: 'sess-' + i + '.yaml',
      status: i % 3 === 0 ? 'in_progress' : (i % 3 === 1 ? 'resolved' : 'escalated'),
      framework: 'vllm-ascend', platform: 'A2-910B', category: 'interrupt',
      activeCase: i % 4 === 0 ? 'VLLM-ASCEND-OOM' : null,
      activeCaseInKb: i % 8 === 0,
      feedbackPending: i % 5 === 0 ? 'pending' : null,
      // 收起态副标题优先用问题背景段；偶数单给背景、奇数单不给（验证回退到"末条记录"）
      summarySnippet: i % 2 === 0 ? '问题背景：第 ' + i + ' 单的服务启动失败，在 profile_run 阶段崩掉' : null,
      userSteps: 2, agentSteps: 4,
      lastRole: 'agent',
      lastOutput: '定位到 device OOM：batch size 超过 910B 显存，建议降到 8 并开 NPU 内存碎片整理（这是第 ' + i + ' 单的结论摘要）',
      updatedAt: new Date(Date.now() - i * 3600 * 1000).toISOString(),
    }, over)
    const manySessions = Array.from({ length: 23 }, (_, k) => mkSession(k + 1))
    // host 的 traceDetail 返回 {ok, steps: [...], summary, refCount, sedimented}
    // —— steps 是**数组**（曾被自己的 mock 写成 {list:[...]}，导致展开后什么都没渲染）
    const stepsPayload = {
      ok: true, summary: '问题背景：训练第 200 步后 OOM',
      refCount: 1, sedimented: null,
      steps: [
        { role: 'user', content: '训练到 200 步就 OOM 了，日志如下…' },
        { role: 'agent', step: 1, action: 'grep_error_signature', output: '命中 E10001 device OOM',
          reason: '签名匹配到内存类中断', evidence: { inline: 'E10001: device out of memory\n'.repeat(40), files: ['traces/evidence/s1/log.txt'], missing: null } },
        { role: 'agent', step: 2, action: 'reference_lookup', output: '参考层给出显存核算表', evidence: { inline: null, files: [], missing: '缺少 max_split_size 配置' } },
        { role: 'agent', step: 3, action: 'deliver_fix', output: '建议 batch size 8 + 开启内存碎片整理', evidence: null },
      ],
    }
    const diagHost = (method, args) => {
      rpcCalls.push(method + (args && args.traceFile ? ':' + args.traceFile : ''))
      if (method === 'ascend-traces-list') return { ok: true, sessions: manySessions }
      if (method === 'ascend-traces-detail') return stepsPayload
      if (method === 'ascend-open-evidence') return { opened: true }
      return { ok: false, error: 'unknown ' + method }
    }
    const dg = await renderAsync(ascSrc, { sessionId: 'sess-1' }, diagHost)
    const dt = dg.text
    // ② 卡片摘要：收起态要回答"这单在查什么"——优先问题背景段；没有背景段才退回末条记录。
    //    旧版写「最后一步 · Agent」+ 最后事件的 output：最后一个事件常常是产出报告/续接这类
    //    **记录维护**动作，读者看不懂（实测反馈："最后一步……让人看不懂也觉得很奇怪"）。
    expect('诊断 tab：收起态优先显示问题背景（不是"最后一步"）', /背景/.test(dt) && /问题背景：第 2 单/.test(dt))
    expect('诊断 tab：无背景段时退回末条记录，且不再叫「最后一步」', /末条记录/.test(dt) && /定位到 device OOM/.test(dt) && !/最后一步/.test(dt))
    expect('诊断 tab：收起态不再只给环境标签（框架/平台/类别仍在展开态）',
      !/vllm-ascend · A2-910B · interrupt[\s\S]{0,40}背景/.test(dt))
    // ④ 回到顶部：会话 > 20 才出现
    expect('诊断 tab：会话 >20 时出现「回到顶部」按钮（23 个会话）', /«title:回到顶部/.test(dt))
    // 闭环指令（阶段一）：四种结局分开给，且命令里带上正确的状态词与 feedback outcome
    expect('诊断 tab：活跃会话给「继续诊断」', dt.includes('继续诊断'))
    expect('诊断 tab：给「已解决 · fix 生效」', dt.includes('已解决 · fix 生效'))
    expect('诊断 tab：给「没解决」（不把失败藏起来）', dt.includes('没解决'))
    expect('诊断 tab：给「不跟了」（archived，不下 fix 判断）', dt.includes('不跟了'))
    expect('诊断 tab：给「转上游」（escalated）', dt.includes('转上游'))
    expect('诊断 tab：闭环提示写清状态词与 outcome',
      /status: resolved \+ feedback\{outcome: resolved\}/.test(ascSrc) && /outcome: not_resolved/.test(ascSrc) && /status: archived/.test(ascSrc))
    // 词表是数据：面板引用的状态/结局必须都在 trace-status.yaml 里
    {
      const vocab = fs.readFileSync(path.join(repo, 'trace-status.yaml'), 'utf8')
      const declared = [...vocab.matchAll(/^\s+- value: ([a-z_]+)/gm)].map(m => m[1])
      expect('trace-status.yaml 声明 status 词表（含 archived）',
        declared.includes('in_progress') && declared.includes('resolved') && declared.includes('escalated') && declared.includes('archived'))
      expect('trace-status.yaml 声明 outcome 词表（含 pending）',
        declared.includes('pending') && declared.includes('not_resolved') && declared.includes('partial'))
      expect('面板引用的状态词都在词表里',
        ['in_progress', 'resolved', 'escalated', 'archived'].every(v => declared.includes(v)))
      expect('词表标注"未回报不计 hit/误诊"（pending → counts_as: none）', /counts_as: none/.test(vocab))
    }
    {
      const few = Array.from({ length: 5 }, (_, k) => mkSession(k + 1))
      const dg2 = await renderAsync(ascSrc, { sessionId: 'sess-1' },
        (m, a) => (m === 'ascend-traces-list' ? { ok: true, sessions: few } : diagHost(m, a)))
      expect('诊断 tab：会话 ≤20 时不出现「回到顶部」（不占位）', !/«title:回到顶部/.test(dg2.text))
    }
    // 待跟进三类**互斥**（回归：曾把"结论已给等回报"同时算进"进行中"和"待回报"，1 单显示 2 项）
    {
      const follow = [
        mkSession(1, { status: 'in_progress', feedbackPending: null, feedback: null }),          // 在查
        mkSession(2, { status: 'in_progress', feedbackPending: 'pending', feedback: null }),     // 等回报（旧口径会双算）
        mkSession(3, { status: 'in_progress', feedbackPending: null, feedback: 'resolved' }),    // 该闭环
        mkSession(4, { status: 'resolved', feedbackPending: null, feedback: 'resolved' }),       // 闭环，不计
      ]
      const dg3 = await renderAsync(ascSrc, { sessionId: 'sess-1' },
        (m, a) => (m === 'ascend-traces-list' ? { ok: true, sessions: follow } : diagHost(m, a)))
      expect('待跟进三类各自计数（1 在查 / 1 等回报 / 1 该闭环）',
        /1 个在查/.test(dg3.text) && /1 个等回报/.test(dg3.text) && /1 个该闭环/.test(dg3.text), dg3.text.slice(0, 200))
      expect('待跟进徽章 = 三类之和（3，不是把等回报双算成 4）',
        /3 项待跟进/.test(dg3.text) && !/4 项待跟进/.test(dg3.text), dg3.text.slice(0, 160))
      expect('横幅点明两条轴（在查=诊断没结论；等回报=结论已给、fix 没验证）',
        /在查=诊断没结论/.test(dg3.text) && /等回报=结论已给/.test(dg3.text))
      expect('不再出现旧的合并措辞（"个诊断还没结束"/"个结果还没回报"）',
        !/个诊断还没结束/.test(dg3.text) && !/个结果还没回报/.test(dg3.text))
    }
    // —— 反馈轴分型（2026-09-13 补）——
    // `feedback.case` 允许写占位串 `pending-investigation`（表示**没命中 case、只给了建议**，
    // 定义见 diagnosis_state.yaml.example）。占位串**不是 case id**：读成后者会让面板说
    // 「结果待回报：pending-investigation」（像有个 fix 等验证），把一个还在多轮里的单报成债；
    // 也会让 resume 去回写一个不存在的 case 的 confidence。这一节钉住"两种取值分开处理"。
    {
      const mix = [
        mkSession(1, { status: 'in_progress', feedbackKind: 'no-case', feedbackPending: 'pending-investigation',
          waitingFor: '缺镜像摘要与容器内 HCCL_* 全量值（现场回填中）' }),
        mkSession(2, { status: 'in_progress', feedbackKind: 'case', feedbackPending: 'VLLM-ASC-1234',
          feedbackCase: 'VLLM-ASC-1234', waitingFor: null }),
      ]
      const dg4 = await renderAsync(ascSrc, { sessionId: 'sess-1' },
        (m, a) => (m === 'ascend-traces-list' ? { ok: true, sessions: mix } : diagHost(m, a)))
      expect('分型后仍各占一桶（1 在查 / 1 等回报）',
        /1 个在查/.test(dg4.text) && /1 个等回报/.test(dg4.text), dg4.text.slice(0, 220))
      expect('首屏说明点出"在查含等现场补材料"',
        /在查=诊断没结论（含等现场补材料）/.test(dg4.text))
      // 单卡断言分两次渲染：一次只放占位串单、一次只放真实 case 单——两张卡同屏时
      // "结果待回报"本来就该出现（那是另一张卡的），全局否定断言会假失败
      const onlyNoCase = await renderAsync(ascSrc, { sessionId: 'sess-1' },
        (m, a) => (m === 'ascend-traces-list' ? { ok: true, sessions: [mix[0]] } : diagHost(m, a)))
      const onlyCase = await renderAsync(ascSrc, { sessionId: 'sess-1' },
        (m, a) => (m === 'ascend-traces-list' ? { ok: true, sessions: [mix[1]] } : diagHost(m, a)))
      expect('占位串单显示「等现场补材料」并说出等什么',
        /等现场补材料/.test(onlyNoCase.text) && /缺镜像摘要/.test(onlyNoCase.text), onlyNoCase.text.slice(0, 200))
      expect('占位串单不显示「结果待回报」（占位串不是 case id）', !/结果待回报/.test(onlyNoCase.text))
      expect('占位串单只算「在查」，不算「等回报」',
        /1 个在查/.test(onlyNoCase.text) && !/个等回报/.test(onlyNoCase.text))
      expect('真实 case 单才显示「结果待回报：<case>」', /结果待回报：VLLM-ASC-1234/.test(onlyCase.text))
      expect('真实 case 单只算「等回报」', /1 个等回报/.test(onlyCase.text) && !/个在查/.test(onlyCase.text))
      const hostSrc2 = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
      expect('host 把占位串判成 no-case（不当 case id）',
        /cs !== 'pending-investigation'/.test(hostSrc2) && /'no-case'/.test(hostSrc2))
      expect('host 给出「在等什么」（最近一条 evidence.missing，退到 last_action）',
        /waitingFor: \(function \(\)/.test(hostSrc2) && /ev\.missing/.test(hostSrc2) && /doc\.last_action/.test(hostSrc2))
      expect('无命中单结案时清掉遗留的 feedback.outcome: pending（不出现两轴打架）',
        /feedback\.outcome: pending（无命中单留下的占位），一并清掉/.test(ascSrc))
      // 读取端与写入端一起钉：只改面板会在下一批 trace 上重新长出同一个混用
      const resumeMd = fs.readFileSync(path.join(repo, 'skills/resume-diagnosis/SKILL.md'), 'utf8')
      expect('resume 按 feedback.case 的两种取值分支',
        /真实 case id/.test(resumeMd) && /占位串 `pending-investigation`/.test(resumeMd))
      expect('占位串分支不回写 confidence，且明确不是终态',
        /不要求回写 confidence/.test(resumeMd) && /不是终态/.test(resumeMd))
      const procMd = fs.readFileSync(path.join(repo, 'skills/diagnose/references/diagnosis-procedure.md'), 'utf8')
      expect('diagnose 写明未命中时的 case 填占位串（不是 case id）',
        /未命中但给了建议 → 占位串/.test(procMd))
    }
    // 沉淀候选**展开即列出明细**（只给一个数字读者无从判断"为啥是 3 条"），
    // 且 **case 与先验候选分家**（2026-09 重做，起因是实测误读）。
    {
      expect('detail 数据把沉淀候选带回客户端', /sedimentCandidates: r && r\.sedimentCandidates/.test(ascSrc))
      expect('面板列出候选明细（kind 徽标 + 一句摘要，全文在 title）',
        /candRow\(c, cands\.indexOf\(c\)/.test(ascSrc) && /tinyBadge\(c\.kind === 'reference'/.test(ascSrc)
        && /c\.summary \|\| '\(无摘要\)'/.test(ascSrc))
      expect('case 与先验候选分家：两段各有自己的标签与入口（不挤在一个"沉淀状态"块里）',
        /const refCands = cands\.filter\(c => c\.kind === 'reference'\)/.test(ascSrc)
        && /sedLabel\('本单沉淀'\)/.test(ascSrc) && /sedLabel\('先验候选'/.test(ascSrc)
        && /caseCands\.map\(c => candRow/.test(ascSrc) && /refCands\.map\(c => candRow/.test(ascSrc))
      expect('先验候选可执行：每条给独立入口（不是只读文本）',
        /'沉淀此条'/.test(ascSrc))
      // 指令形态：先验候选**不带 trace 路径当输入**——to-reference 没有"读 trace"这种输入模式，
      // 它的入口是内联内容 + 出处说明，所以摘要必须原样带上。
      expect('先验候选的指令走 to-reference，且把候选摘要当引子、trace 当出处',
        /用 \/skill:to-reference 沉淀一条 reference：/.test(ascSrc) && /来源：traces\//.test(ascSrc))
      // 误读的直接来源：引用计数（用了几次）贴在沉淀块正上方，读者读成"reference 也沉淀了"。
      expect('引用计数移出沉淀区（改挂轨迹标题行，措辞点明"用了几次"）',
        !/本次诊断使用 reference/.test(ascSrc) && /'先验引用 ' \+ steps\.refCount \+ ' 次'/.test(ascSrc)
        && /不是"沉淀了几条"/.test(ascSrc))
      // 面板只产指令、不产内容：口径（范围/归类）在对话里由 to-reference 的 grill 对齐。
      // 断言"没有编辑入口"，防止后来有人把候选摘要做成可编辑字段（那会与 grill 后的实际产出分叉）。
      expect('沉淀候选没有编辑入口（面板产指令，内容归对话与 skill）',
        !/ascend-update-candidate/.test(ascSrc))
    }
    // —— 报告进面板：只读渲染 + 复制全文（2026-09-13 补）——
    // 之前面板只有「打开报告」（落到外部编辑器）：36KB 的报告要交给客户/回贴上游，得自己翻文件找
    // TL;DR，或全选复制。这里钉三件事：点得开（RPC 真被调用）、**只渲染所选那一节**（不是把
    // 36KB 全铺开）、能复制全文。
    {
      const reportMd = [
        '# 定位报告：sess-1 启动失败',
        '',
        '## 1 TL;DR',
        '',
        '- 现象：profile_run 崩溃',
        '- 先动什么：换更新的构建复跑',
        '',
        '## 3 依据链',
        '',
        '| # | 结论 | 证据 |',
        '|---|---|---|',
        '| V1 | 该构建已脱离分支 | gh api compare |',
        '',
        '## 6 下一步',
        '',
        '1. 复跑',
      ].join('\n')
      const reportCalls = []
      const rpHost = (m, a) => {
        if (m === 'ascend-read-report') {
          reportCalls.push(a)
          return { ok: true, path: 'traces/sess-1.report.md', text: reportMd, chars: reportMd.length, truncated: false }
        }
        if (m === 'ascend-traces-list') return { ok: true, sessions: [mkSession(1, { reportFile: 'sess-1.report.md' })] }
        return diagHost(m, a)
      }
      hookIdx = 0; hookState = []; depState = []; effectQueue = []
      const registrations = []
      const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
      const host = { call: (m, a) => Promise.resolve(rpHost(m, a)) }
      const plugin = new Function('React', 'host', 'styles', 'return (function(){' + ascSrc + '})()')(React, host, { insert: () => () => {} })
      plugin.apply(ctx)
      // 只渲染诊断 tab：mock 的 useState 槽位是全局的，两个 tab 一起渲染会串槽
      // （实测：MetricsView 拿到诊断 tab 的槽位 → state 为 null 直接崩）
      const renderTree = () => { effectQueue = []; hookIdx = 0; const o = []; registrations.filter(r => r.o.id === 'ascend-diagnose').forEach(r => o.push(r.c({ sessionId: 'sess-1' }))); return o }
      const textOf = t => { const o = []; flatten(t, o); return o.join('\n') }
      const pump = async (rounds) => {
        let tree = null
        for (let i = 0; i < rounds; i++) {
          tree = renderTree()
          effectQueue.slice().forEach(f => f())
          await new Promise(r => setImmediate(r))
          await new Promise(r => setImmediate(r))
        }
        return tree
      }
      let tree = await pump(4)
      let texts = textOf(tree)
      expect('报告入口在收起态的卡片上就有（「看报告」）', /看报告/.test(texts), texts.slice(0, 200))
      const hs = []
      tree.forEach(t => collectHandlers(t, hs))
      // 按钮的 flatten 文本会把 title 一并收集，所以按"以标签结尾"匹配（不按全等）
      const btn = hs.filter(h => /看报告$/.test(h.text.trim()))[0]
      expect('报告入口可点', !!btn)
      if (btn) {
        btn.fn({})
        tree = await pump(5)
        texts = textOf(tree)
        expect('点击后真的取了报告（read-report 被调用 ' + reportCalls.length + ' 次）', reportCalls.length === 1)
        expect('报告给章节跳转与「复制全文」', /TL;DR/.test(texts) && /复制全文/.test(texts))
        expect('报告仍给「打开文件」（长报告要能落到外部）', /打开文件/.test(texts))
        expect('报告默认停在 TL;DR 节（正文里先给结论）', /现象：profile_run 崩溃/.test(texts))
        expect('只渲染所选那一节（依据链正文不上屏，避免把整份报告铺开）', !/该构建已脱离分支/.test(texts))
        expect('报告是只读入口（没有写入报告的 RPC）', !/ascend-write-report/.test(ascSrc))
      }
    }
    // —— 交接包：把这一单交到另一台机器（外网定位到一半、大日志在内网）——
    // 这一行与卡片上其余按钮形态不同：那几个是"选一条指令 → 复制 → 粘到对话"，本行是**直接动作**
    // （面板调脚本）。所以这里钉的是：意图真的被带进 RPC、结果如实回报（体量/未纳入/含原始证据）、
    // 外来单在**收起态**就标出来、以及"打开目录"走的是仓库内相对路径（openEvidence 拒绝对路径）。
    {
      const hoCalls = []
      const openedPaths = []
      const hoHost = (m, a) => {
        if (m === 'ascend-export-trace') {
          hoCalls.push(a)
          // **照脚本的真实输出形状给**（snake_case）：早先这里图省事写成 camelCase，于是
          // client 读 `handoff.zipBytes` 而真 host 只吐 `zip_bytes` 的错配被"假 host"掩盖了，
          // 断言绿着放过了线上那个 "zip 0 B + md 0 B"。
          return {
            ok: true, session_id: 'sess-2', intent: (a && a.intent) || 'continue',
            dir: '/repo/traces/exports',
            zip: '/repo/traces/exports/handoff-sess-2.zip', zip_bytes: 201704,
            md: '/repo/traces/exports/handoff-sess-2.md', md_bytes: 72813,
            files: 9, total_bytes: 2737616,
            omitted: [{ path: 'evidence/sess-2/huge.bin', bytes: 99999999, reason: '超过单文件上限 20 MB' }],
            needs: ['缺 device 侧日志', '等回报 fix 结果'],
            redaction: { state: 'raw-evidence', notes: ['包内含原始现场证据'] },
            warnings: ['trace 缺 kb_rev 字段'],
          }
        }
        if (m === 'ascend-open-evidence') { openedPaths.push(a); return { opened: true, via: 'macos-open' } }
        if (m === 'ascend-traces-list') {
          return { ok: true, sessions: [
            // 外来单：host 从 traces/handoff/<sid>.yaml 读到的溯源
            mkSession(2, { handoff: { host: 'outer-node-01.corp', intent: 'continue', exportedAt: '2026-01-02T09:00:00+08:00', importedAt: '2026-01-02T09:30:00+08:00', renamedFrom: null, kbRevMatch: false, needs: 2 } }),
            mkSession(4),
          ] }
        }
        return diagHost(m, a)
      }
      const hg = await renderAsync(ascSrc, { sessionId: 'sess-1' }, hoHost)
      expect('交接包：外来单在收起态就标「外来」并给出源主机（短名）', /外来 · outer-node-01/.test(hg.text), hg.text.slice(0, 240))
      expect('交接包：普通单不标外来（标记宁缺勿造）', (hg.text.match(/外来 ·/g) || []).length === 1)

      // 运行时的导出链路**在 host 侧驱动**，不靠模拟点击：mock React 的 hook 槽是全局顺序计数，
      // 点开卡片后多次重渲染会错位、展开态读不回来（同一限制在轨迹时间轴那段已如实记过）。
      // host 侧这套驱动更强：命令怎么拼、stdout 怎么取 JSON、退出后的错误怎么上屏，都在真代码里跑。
      {
        const seen = []
        const fakeShell = {
          resolve: (spec) => spec,
          run: async (spec) => {
            const cmd = String(spec && spec.command || '')
            // 解释器探活（resolvePython 先跑 `<py> --version`）必须给真版本串，否则测到的是"没有 Python"那条路
            if (/--version$/.test(cmd)) {
              return { exitCode: 0, timedOut: false, aborted: false, stdout: { text: 'Python 3.11.9\n' }, stderr: { text: '' } }
            }
            seen.push(spec)
            return { exitCode: 0, timedOut: false, aborted: false, stdout: { text: fakeShell.reply }, stderr: { text: '' } }
          },
          reply: '',
        }
        // 就地驱动 host 源码（`loadHost`/`driveHost` 在本文件更靠后的作用域里，这段先用不了它们）
        const hostSrc2 = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
        const drive = (svc) => {
          const regs = {}
          const ctx = { get: (n) => n === 'fs' ? svc.fs : n === 'shell' ? svc.shell : n === 'sessions' ? svc.sessions : undefined }
          const harness = { handle: (name, fn) => { regs[name] = fn; return () => {} }, defineTool: (o) => o, registerTool: () => () => {} }
          const plugin = new Function('harness', 'console', hostSrc2)(harness, { error: () => {}, log: () => {} })
          if (plugin && typeof plugin.apply === 'function') plugin.apply(ctx)
          return { regs }
        }
        const svc = {
          shell: fakeShell, fs: undefined,
          sessions: { list: () => [{ header: { cwd: '/repo' } }], get: () => ({ header: { cwd: '/repo' } }) },
        }
        const dh = drive(svc)
        fakeShell.reply = JSON.stringify({
          ok: true, session_id: 'sess-2', intent: 'escalate', dir: '/repo/traces/exports',
          // 照脚本真实输出形状（snake_case）——写成 camelCase 就等于用"假 host"掩盖字段名错配
          zip: '/repo/traces/exports/handoff-sess-2.zip', zip_bytes: 201704,
          md: '/repo/traces/exports/handoff-sess-2.md', md_bytes: 72813, files: 9,
          total_bytes: 2737616,
          omitted: [{ path: 'evidence/sess-2/huge.bin', bytes: 1, reason: 'x' }],
          needs: ['缺 device 侧日志'], redaction: { state: 'raw-evidence' },
        })
        const r1 = await dh.regs['ascend-export-trace']({ sessionId: 's', traceFile: 'sess-2.yaml', intent: 'escalate' })
        const cmd = seen.length ? String(seen[0].command) : ''
        expect('交接包 host：以检出为工作目录跑导出脚本（相对路径才解析得到）',
          /scripts\/export_trace\.py traces\/sess-2\.yaml/.test(cmd) && seen[0].workdir === '/repo', cmd)
        expect('交接包 host：意图进命令行（且只在白名单内）', /--intent escalate/.test(cmd), cmd)
        expect('交接包 host：要 JSON 结果（面板按 JSON 渲染，不解析人读行）', /--json/.test(cmd), cmd)
        expect('交接包 host：把脚本结果带给面板，并换成仓库内相对路径给「打开目录」',
          r1 && r1.ok && r1.dirRel === 'traces/exports', JSON.stringify(r1 && { dirRel: r1.dirRel }))
        expect('交接包 host：脚本的 zip_bytes/md_bytes 收口成面板读的 zipBytes/mdBytes（否则结果行报假体量）',
          r1 && r1.zipBytes === 201704 && r1.mdBytes === 72813 && r1.totalBytes === 2737616,
          JSON.stringify(r1 && { zipBytes: r1.zipBytes, mdBytes: r1.mdBytes }))
        // 成对断言：**client 读的键，host 必须都给**。这条才是那个 bug 该被拦住的地方——
        // 早先的断言把错误的字段名写进了源码正则，等于把 bug 钉死。局部状态（ok/busy/error）
        // 是 client 自己造的，不在 RPC 契约里，排除。
        {
          const stateKeys = Array.from(new Set(
            (ascSrc.match(/(?<!s\.)\bhandoff\.(\w+)/g) || []).map(x => x.replace('handoff.', ''))))
            .filter(k => ['ok', 'busy', 'error'].indexOf(k) < 0)
          const missing = stateKeys.filter(k => !(k in (r1 || {})))
          expect('交接包：client 读的 ' + stateKeys.length + ' 个字段 host 全都给（缺一即红）',
            stateKeys.length >= 6 && missing.length === 0, '缺：' + missing.join(','))
          // 会话列表上那个外来标记（s.handoff.X）读的键，host 的 readHandoffNote 也必须都给
          const markerKeys = Array.from(new Set(
            (ascSrc.match(/s\.handoff\.(\w+)/g) || []).map(x => x.replace('s.handoff.', ''))))
          const hostSrc3 = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
          const i = hostSrc3.indexOf('async function readHandoffNote')
          const noteBody = i < 0 ? '' : hostSrc3.slice(i, hostSrc3.indexOf('\n    }', i))
          const missMarker = markerKeys.filter(k => noteBody.indexOf(k + ':') < 0)
          expect('交接包：外来标记读的 ' + markerKeys.length + ' 个字段 host 的 readHandoffNote 都给',
            markerKeys.length >= 4 && missMarker.length === 0, '缺：' + missMarker.join(','))
        }
        expect('交接包 host：顺带给出手工复现命令（Python 缺失时读者有出路）',
          r1 && /python3 scripts\/export_trace\.py/.test(String(r1.manual)), String(r1 && r1.manual))

        // 沙箱：写权限的根必须显式给成会话工作区。不给的话 shell 的默认根是 DSH 自己的检出，
        // 子进程写仓库里任何路径都只报一句 EPERM（实测：导出交接包全失败，而文件权限一切正常）。
        expect('交接包 host：导出子进程带沙箱写权限，根=会话工作区（否则被拒写）',
          !!(seen[0] && seen[0].sandboxPolicy)
          && seen[0].sandboxPolicy.mode === 'workspace-write'
          && seen[0].sandboxPolicy.workspaceRoot === '/repo',
          JSON.stringify(seen[0] && seen[0].sandboxPolicy))
        {
          const denyShell = {
            resolve: (spec) => spec,
            run: async (spec) => (/--version$/.test(String(spec && spec.command || ''))
              ? { exitCode: 0, timedOut: false, aborted: false, stdout: { text: 'Python 3.11.9\n' }, stderr: { text: '' } }
              : { exitCode: 1, timedOut: false, aborted: false, stdout: { text: '' }, stderr: { text: 'PermissionError: [Errno 1] Operation not permitted' },
                  sandbox: { mode: 'workspace-write', denied: true, enforcement: 'full' } }),
          }
          const rDeny = await drive({ shell: denyShell, fs: undefined, sessions: svc.sessions })
            .regs['ascend-export-trace']({ sessionId: 's', traceFile: 'sess-2.yaml', intent: 'continue' })
          expect('交接包 host：沙箱拒绝时点明是沙箱干的（不是让读者去猜 EPERM）',
            rDeny.ok === false && /沙箱/.test(String(rDeny.error)) && /手工复现/.test(String(rDeny.error)),
            String(rDeny && rDeny.error))
        }

        // 非法文件名不拼进命令行（面板自己的列表里拿到的值也要卡一道）
        seen.length = 0
        const rBad = await dh.regs['ascend-export-trace']({ sessionId: 's', traceFile: '../evil.yaml; rm -rf /' })
        expect('交接包 host：非法 trace 文件名拒绝拼命令', rBad.ok === false && seen.length === 0, JSON.stringify(rBad))

        // 脚本失败：把末几行错误带出来，不静默
        fakeShell.reply = ''
        const rFail = await (async () => {
          const sh = {
            resolve: (s) => s,
            run: async (spec) => (/--version$/.test(String(spec && spec.command || ''))
              ? { exitCode: 0, timedOut: false, aborted: false, stdout: { text: 'Python 3.11.9\n' }, stderr: { text: '' } }
              : { exitCode: 1, timedOut: false, aborted: false, stdout: { text: '' }, stderr: { text: 'Traceback\nValueError: boom' } }),
          }
          const d2 = drive({ shell: sh, fs: undefined, sessions: svc.sessions })
          return d2.regs['ascend-export-trace']({ sessionId: 's', traceFile: 'sess-2.yaml' })
        })()
        expect('交接包 host：脚本没给 JSON 时如实报错（并把最后几行带出来）',
          rFail.ok === false && /ValueError: boom/.test(String(rFail.error)), String(rFail && rFail.error))
        const rNoShell = await drive({ shell: undefined, fs: undefined, sessions: svc.sessions })
          .regs['ascend-export-trace']({ sessionId: 's', traceFile: 'sess-2.yaml' })
        expect('交接包 host：shell 不可用时给原因与手工复现命令（不假装成功）',
          rNoShell.ok === false && /shell/.test(String(rNoShell.error)) && /手工复现/.test(String(rNoShell.error)),
          String(rNoShell && rNoShell.error))
      }
      // 结构断言：运行时读不回来的那部分（措辞与形态）钉在源文件上
      expect('交接包：意图词表与脚本一致（continue/verify/escalate 三值）',
        /const HANDOFF_INTENTS = \[/.test(ascSrc) && /id: 'continue', label: '继续定位'/.test(ascSrc)
        && /id: 'verify', label: '复核结论'/.test(ascSrc) && /id: 'escalate', label: '转上游'/.test(ascSrc))
      expect('交接包：意图默认「继续定位」（不默认成会误导接收侧的值）',
        /const \[handoffIntent, setHandoffIntent\] = React\.useState\('continue'\)/.test(ascSrc))
      expect('交接包：导出中禁用按钮（防重复点击导出多份）', /disabled: !!\(handoff && handoff\.busy\)/.test(ascSrc))
      expect('交接包：失败时把错误显出来（不静默）', /handoff && handoff\.error \?/.test(ascSrc))
      expect('交接包：体量取不到时说「未知」而不是 0 B（0 B 读起来像空包）',
        /!Number\.isFinite\(v\)\) return '未知'/.test(ascSrc))
      expect('交接包：按钮说明里给出接收侧的那条命令', /import_trace\.py/.test(ascSrc))
      const hoBlock = ascSrc.slice(ascSrc.indexOf('// ---- 交接包'), ascSrc.indexOf('const actionArea'))
      expect('交接包：注明它是"直接动作"（与"生成指令"类按钮的分工）', /直接动作/.test(hoBlock), 'slice=' + hoBlock.length)
      {
        // 按**调用点邻接**判，不按全文计数：脚本名在错误提示与注释里也出现（手工复现那句就写着
        // scripts/export_trace.py），按计数判会得出"15 处调用"这种假数字。
        const countPolicy = (src) => {
          const lines = src.split(/\r?\n/)
          let sites = 0
          let ok = 0
          for (let i = 0; i < lines.length; i++) {
            // 两个面板都是 `command: py + '…'` 这个形状（ev-panel 拼的是变量 scriptName）
            if (!/command: py \+/.test(lines[i])) continue
            sites++
            for (let j = i + 1; j < Math.min(i + 10, lines.length); j++) {
              if (/sandboxPolicy: \{ mode: 'workspace-write', workspaceRoot: cwd \}/.test(lines[j])) { ok++; break }
              if (/^\s*\}\)\)?\s*$/.test(lines[j])) break   // shell.resolve({...}) 调用结束
            }
          }
          return { sites: sites, ok: ok }
        }
        const asc = countPolicy(fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8'))
        expect('沙箱策略：诊断面板每个跑脚本的调用点都带写权限根（' + asc.ok + '/' + asc.sites + '）',
          asc.sites >= 3 && asc.ok === asc.sites, JSON.stringify(asc))
        const ev = countPolicy(fs.readFileSync(path.join(repo, 'dsh-plugins/ev-panel/panel-host.js'), 'utf8'))
        expect('沙箱策略：自演进面板的 runScript 也带（同类陷阱不在别的面板重演）',
          ev.sites >= 1 && ev.ok === ev.sites, JSON.stringify(ev))
      }
      expect('交接包：结果里回报体量、未纳入数、待补材料条数',
        /humanKB\(handoff\.zipBytes\)/.test(hoBlock) && /未纳入 /.test(hoBlock) && /待补材料/.test(hoBlock))
      expect('交接包：含原始证据只做标记（写明导出不脱敏、闸门在数据通道）',
        /含原始证据/.test(hoBlock) && /导出不做脱敏/.test(hoBlock))
      // 把共享的 mock hook 槽复位：它按调用顺序计数，别把污染带给后面的用例（下面还有几段共用）
      hookIdx = 0; hookState = []; depState = []; effectQueue = []
    }
    // 展开视图分两档：人读视图（默认）只给"问题查到哪了"，完整轨迹才是原始事件（回放/归因用）
    {
      const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
      expect('收起态副标题的原料来自 host 的 summarySnippet', /summarySnippet: doc\.summary/.test(hostSrc))
      expect('人读视图默认开（完整轨迹要手动切）', /const \[fullTrace, setFullTrace\] = React\.useState\(false\)/.test(ascSrc))
      expect('记录维护类动作默认收起（report/resume/feedback/attribution）',
        /const PROC_ACTIONS = \{ report: true, resume: true, feedback: true, attribution: true \}/.test(ascSrc)
        && /all\.filter\(st => !PROC_ACTIONS\[st\.action\]\)/.test(ascSrc))
      expect('推理文本只在完整轨迹里铺开（人读视图不铺 reason）', /fullTrace && st\.reason \?/.test(ascSrc))
      expect('人读视图给中文动作标签（原词留 title 供回查）',
        /STEP_LABELS\[st\.action\] \|\| st\.action/.test(ascSrc) && /triage: '路由分类'/.test(ascSrc))
      expect('两种视图可切换（看完整轨迹 / 只看诊断）', /'看完整轨迹'/.test(ascSrc) && /'只看诊断'/.test(ascSrc))
      expect('措辞专业化（不再出现"好在下面可以直接闭环"）',
        !/好在下面可以直接闭环/.test(ascSrc) && /结果待回报：/.test(ascSrc))
    }
    // ① 轨迹时间轴：展开一张会话卡后应有刻度点/竖轨，且证据存在性提到步骤行
    {
      const registrations = []
      const ctx = { get: n => n === 'slots' ? { inject: (s, cb) => cb(), register: (o, c) => registrations.push({ o, c }) } : undefined, effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} }, on() { return () => {} } }
      const plugin = new Function('React', 'host', 'styles', 'return (function(){' + ascSrc + '})()')(React, { call: (m, a) => Promise.resolve(diagHost(m, a)) }, { insert: () => () => {} })
      plugin.apply(ctx)
      const renderTree = () => { effectQueue = []; hookIdx = 0; const o = []; registrations.forEach(r => o.push(r.c({ sessionId: 'sess-1' }))); return o }
      const textOf = t => { const o = []; flatten(t, o); return o.join('\n') }
      const pump = async (rounds) => {
        let tree = null
        for (let i = 0; i < rounds; i++) {
          tree = renderTree()
          effectQueue.slice().forEach(f => f())
          await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
        }
        return tree
      }
      let tree = await pump(5)
      const hs = []
      tree.forEach(t => collectHandlers(t, hs))
      const card = hs.find(h => String(h.text).includes('sess-001'))
      let clicked = 0
      if (card) { card.fn({}); clicked = 1 }
      tree = await pump(6)
      const et = textOf(tree)
      expect('诊断 tab：展开会话卡（' + clicked + ' 次）', clicked === 1, card ? '' : '未找到 sess-001 卡头')
      if (clicked) {
        // **限制（如实标注）**：mock React 的 hook 槽是全局顺序计数，点开卡片触发的
        // setState/subscribe 链在多次重渲染后槽位会错位，展开态内容读不回来
        // （实测：detail RPC 未被调用、`steps.list` 读不到）。所以时间轴的断言不靠模拟点击，
        // 而是**对源文件断言结构**——它拦得住"改回旧的 borderLeft 竖线"这类回归，
        // 拦不住纯运行时的渲染错误（那一层由浏览器验证兜）。
        const needMarkup = [
          ["时间轴刻度点 class", /className: 'sleu-tl-dot'/],
          ["时间轴竖轨 class（最后一步不画）", /last \? null : React\.createElement\('span', \{ className: 'sleu-tl-rail'/],
          ["刻度点按角色着色（用户/参考层/有证据）", /const dotColor = isUser \? 'var\(--acc-blue\)'/],
          ["步骤用「第 N 步」", /'第 ' \+ st\.step \+ ' 步'/],
          ["证据存在性提到步骤行", /tinyBadge\('var\(--d-green\)'\) \}, '证据'/],
          ["缺证据标出缺口", /tinyBadge\('var\(--d-amber\)'\) \}, '缺 '/],
          ["参考层步骤有标记", /'参考层'/],
          ["证据原文可展开（无 RPC 即渲染）", /evOpenHere \? '收起原文' : '看原文'/],
        ]
        for (const [label, re] of needMarkup) expect('轨迹时间轴：' + label, re.test(ascSrc))
        // 静态渲染层能确认的：展开态仍给出环境标签（与收起态摘要互补）
        expect('诊断 tab：展开态给完整环境标签（框架/平台/类别）', /vllm-ascend · A2-910B · interrupt/.test(et) || /轨迹: 2 用户输入/.test(et))
      }
    }
  }

  // —— 体检不可用时如实退化为一条可执行提示，而不是"一切正常" ——
  {
    const errHost = (method, args) => {
      if (method === 'ascend-metrics-verdict') return { ok: false, error: '未找到可用的 Python 3 解释器（已试 python3 / python / py -3）——体检跑的是 scripts/metrics_health.py' }
      return hostWithVerdict(method, args)
    }
    const ascErr = await renderAsync(ascSrc, { sessionId: 'sess-1' }, errHost)
    expect('体检不可用：如实报错（不假装闭环正常）', /体检不可用|未找到可用的 Python/.test(ascErr.text), ascErr.text.slice(ascErr.text.indexOf('ascend-sleuth 指标'), ascErr.text.indexOf('ascend-sleuth 指标') + 240))
    expect('体检不可用：不显示"闭环未见阻塞项"', !ascErr.text.includes('闭环未见阻塞项'))
  }

  // —— 契约：client 调的 RPC 必须与 host 声明的成对（跨版本混搭是"加载成功、点开报错"的经典坑）——
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    const names = []
    const re = /host\.call\(\s*'([^']+)'/g
    let m
    while ((m = re.exec(ascSrc)) !== null) if (names.indexOf(m[1]) < 0) names.push(m[1])
    expect('client 调用了 ' + names.length + ' 个 RPC', names.length >= 5)
    const missing = names.filter(n => hostSrc.indexOf("'" + n + "'") < 0)
    expect('每个 client RPC 都有 host 声明', missing.length === 0, '缺: ' + missing.join(','))
    const handled = []
    const re2 = /harness\.handle\(\s*'([^']+)'/g
    while ((m = re2.exec(hostSrc)) !== null) if (handled.indexOf(m[1]) < 0) handled.push(m[1])
    const unused = handled.filter(n => ascSrc.indexOf("'" + n + "'") < 0)
    expect('host 没有 client 不用的 RPC', unused.length === 0, '未用: ' + unused.join(','))
  }

  // —— 面板不得重算判据（阈值只在 gates.yaml 一处）——
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    expect('host 不再把容量加总到 namespace（旧口径 byNamespace 已移除）', !/byNamespace/.test(hostSrc))
    expect('host 不再内联 soft_cap 数值做判断', !/>\s*30\b/.test(hostSrc) && !/count\s*>\s*30/.test(hostSrc))
    expect('host 走 metrics_health.py（判据一处）', /metrics_health\.py --json/.test(hostSrc))
    expect('client 渲染 gates.yaml 的阈值而非写死', /gates\.yaml/.test(ascSrc))
  }


  // —— 契约：trace 的两种写法（内联 / 块）都必须解析出事件内容 ——
  // 为什么单列这一条：会话列表与轨迹都过 host 的 YAML 子集解析器，而**本脚本喂的是合成 steps**，
  // 不经过它——于是"块写法 trace 解析后 output/content/evidence 全丢"能一路漏到用户面前
  // （2026-09-12 实测：真实 trace 16 个事件解析成 32 条、role 全对但 output 0 条，
  //  面板表现是"agent 回答都是空的"）。**判据必须看"事件里有没有 output/content"，
  //  不能看步数**——role 在 dash 行上，计数恰好还是对的。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    const from = hostSrc.indexOf('function parseEvidence(')
    const to = hostSrc.indexOf('const tool = harness.defineTool')
    expect('host 解析器可抽出（parseEvidence → defineTool 区块存在）', from > 0 && to > from)
    const parser = new Function(hostSrc.slice(from, to) + '\nreturn { parseYaml: parseYaml, parseEvidence: parseEvidence };')()
    const blockForm = [
      'session_id: "s"',
      'status: in_progress',
      'excluded_cases: [A-1, B-2]',
      'trace:',
      '  - role: user',
      '    step: 1',
      '    content: "拉不起来"',
      '    evidence:',
      '      inline: >-',
      '        第一行',
      '        第二行',
      '      files: ["traces/evidence/s/log.txt"]',
      '      missing: 缺 CANN 版本',
      '  - role: agent',
      '    step: 2',
      '    action: triage',
      '    output: >-',
      '      判为推理中断类',
      '    reason: 症状是启动失败',
      '    tool_calls:',
      '      - "gh api x: 拿到事实"',
      '      - "raw y: 拿到事实"',
    ].join('\n')
    const inlineForm = [
      'session_id: "s2"',
      'trace:',
      '  - {role: user, step: 1, content: "起不来", evidence: {inline: "ERR 507015", files: ["a.log"], sources: ["https://x"], missing: "缺环境"}}',
      '  - {role: agent, step: 2, action: hit, case: VLLM-ASC-1, output: "命中", reason: "签名吻合"}',
    ].join('\n')
    const bd = parser.parseYaml(blockForm)
    const bt = Array.isArray(bd.trace) ? bd.trace : []
    const idoc = parser.parseYaml(inlineForm)
    const it = Array.isArray(idoc.trace) ? idoc.trace : []
    expect('trace 块写法：事件数=2（嵌套列表不当成事件）', bt.length === 2, '实得 ' + bt.length)
    expect('trace 块写法：agent 事件带 output（旧实现在这里为空）', !!(bt[1] && bt[1].output), JSON.stringify(bt[1] || null))
    expect('trace 块写法：agent 事件带 reason / action', !!(bt[1] && bt[1].reason && bt[1].action === 'triage'))
    expect('trace 块写法：块标量按折叠语义合行',
      !!(bt[0] && /第一行 第二行/.test(String((bt[0].evidence || {}).inline || ''))),
      JSON.stringify((bt[0] || {}).evidence || null))
    expect('trace 块写法：evidence.files 解析为数组 / missing 保留',
      !!(bt[0] && Array.isArray(bt[0].evidence.files) && bt[0].evidence.files.length === 1 && bt[0].evidence.missing))
    expect('trace 块写法：顶层流式序列 excluded_cases', Array.isArray(bd.excluded_cases) && bd.excluded_cases.length === 2)
    expect('trace 内联写法：事件数=2 且 output/content 都在（不能为改块写法而弄坏老形态）',
      it.length === 2 && !!(it[1] && it[1].output) && !!(it[0] && it[0].content),
      JSON.stringify(it[1] || null))
    expect('trace 内联写法：evidence.files 是数组（不是带方括号的字符串）',
      (() => { const ev = parser.parseEvidence(it[0] && it[0].evidence); return !!(ev && Array.isArray(ev.files) && ev.files[0] === 'a.log' && ev.inline === 'ERR 507015' && ev.sources[0] === 'https://x' && ev.missing === '缺环境') })(),
      JSON.stringify(parser.parseEvidence(it[0] && it[0].evidence)))
    expect('trace 块写法：parseEvidence 也吃对象形态（块写法给的是映射，不是字符串）',
      (() => { const ev = parser.parseEvidence(bt[0] && bt[0].evidence); return !!(ev && Array.isArray(ev.files) && ev.files.length === 1 && ev.missing === '缺 CANN 版本') })(),
      JSON.stringify(parser.parseEvidence(bt[0] && bt[0].evidence)))

    // —— 定位结论的落点（2026-09-13）——
    // 为什么要测：人读视图会收起 report/resume/feedback/attribution 四类记录维护动作，
    // 而真实 trace 的末条**常常是** report/feedback——于是"结论在哪"不能用"文件里最后一个事件"算，
    // 必须取"人读视图的可见末条"。判错的表现是：卡片通篇没有落点（读者读完不知道定在哪），
    // 或把报告生成当结论。这条判据在 host 里，纯函数可验，故按逻辑测而不是只断言字符串。
    {
      const fromC = hostSrc.indexOf('const HOST_PROC_ACTIONS')
      const toC = hostSrc.indexOf('const tool = harness.defineTool')
      expect('结论文案块可抽出（HOST_PROC_ACTIONS → defineTool 区块存在）', fromC > 0 && toC > fromC)
      const hostMod = new Function(hostSrc.slice(fromC, toC) + '\nreturn { HOST_PROC_ACTIONS: HOST_PROC_ACTIONS, traceDetail: traceDetail };')()
      expect('host 侧记录维护类动作与 client 同值（report/resume/feedback/attribution）',
        JSON.stringify(hostMod.HOST_PROC_ACTIONS) === JSON.stringify({ report: true, resume: true, feedback: true, attribution: true }),
        JSON.stringify(hostMod.HOST_PROC_ACTIONS))
      // 只取结论判定那一段（traceDetail 要 fs 才能跑端到端，这里取纯逻辑）
      const hv = hostSrc.indexOf('const conclusionIndex = (function () {')
      const he = hostSrc.indexOf('})()', hv)
      const conclusionOf = new Function('trace', 'HOST_PROC_ACTIONS', hostSrc.slice(hv, he + 4) + '\nreturn conclusionIndex;')
      const T = arr => arr.map((a, i) => ({ step: 1, action: a, output: 'x' + i }))
      expect('结论落点：显式 conclusion: true 认得出',
        conclusionOf([{ step: 1, action: 'miss', output: 'a' }, { step: 2, action: 'hit', conclusion: true, output: 'b' }], hostMod.HOST_PROC_ACTIONS) === 1)
      expect('结论落点：末条是 report 时取它前面的 hit（真实 trace 的常见形态：hit → report → feedback）',
        conclusionOf(T(['triage', 'miss', 'hit', 'report', 'feedback']), hostMod.HOST_PROC_ACTIONS) === 2)
      expect('结论落点：前面出现过的 hit 不算，只有可见末条算',
        conclusionOf(T(['hit', 'miss', 'report']), hostMod.HOST_PROC_ACTIONS) === -1)
      expect('结论落点：末条是 report 且没有 hit → -1（不把报告生成当结论）',
        conclusionOf(T(['triage', 'source_analysis', 'report']), hostMod.HOST_PROC_ACTIONS) === -1)
      expect('结论落点：空 trace → -1（不崩）', conclusionOf([], hostMod.HOST_PROC_ACTIONS) === -1)
      // 结构断言：结论块在**轨迹之后**（读者的落点在结尾），且人读视图不重复渲染该步
      expect('结论块排在轨迹之后（卡片以结论收尾，不是开头）',
        /定位结论[\s\S]*\}\)\(\),\s*\n\s*\/\/ —— 定位结论落底 —— \/\//.test(ascSrc))
      expect('人读视图从轨迹里去掉结论那条（同一段不读两遍），完整轨迹保留',
        /const timeline = \(!fullTrace && shownIdx\.at >= 0\)/.test(ascSrc))
      expect('结论按对象身份定位（不混用过滤前后下标）',
        /shown\.indexOf\(conclusionStep\)/.test(ascSrc) && /steps\.list\.indexOf\(conclusionStep\)/.test(ascSrc))
      expect('没有结论时给一行说明（读者能分辨"还没收尾"与"这单没有结论"）',
        /本单还没有定位结论/.test(ascSrc))
    }
  }

  // —— 解析器与权威口径（PyYAML）逐条一致 + 没收下的行必须报出来 ——
  // 为什么单列这一条：面板的 trace 解析器是**自己写的 YAML 子集**（动态插件不许 import，
  // Host 也没有 YAML 服务），而读同一份 trace 的脚本全用 PyYAML（`trace_metrics.py` /
  // `settle_trace_feedback.py` / `replay_trace.py`）。两者不一致的表现是**文件正常、面板少
  // 事件、界面上没有任何提示**——2026-09-14 实测：一份 9 条事件的 trace 在面板上只剩第一条
  // （行内集合被折行，`- {role: user, step: 1,` 的续行既不是新键也不是新 dash，序列到此为止）。
  // 同一类缺陷在 `metrics/timeline.yaml` 上已发生过一次（真实文件解析出 0 期）。所以判据不写
  // "能不能解析"，而是拿 PyYAML 当权威口径逐条比：事件数、每条的角色/步号/动作，以及
  // output/content/evidence 的有无；再加一条"解析器没收下的行必须作为异常报出来"。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    const from = hostSrc.indexOf('function readSedimented(')
    const to = hostSrc.indexOf('const tool = harness.defineTool')
    expect('host 解析器与异常出口可抽出（readSedimented → defineTool 区块存在）', from > 0 && to > from)
    const parser = new Function(hostSrc.slice(from, to)
      + '\nreturn { parseYaml: parseYaml, anomalyOf: anomalyOf };')()
    const panelOf = (text) => {
      const stats = {}
      const doc = parser.parseYaml(text, stats)
      const trace = Array.isArray(doc.trace) ? doc.trace : []
      return {
        rows: trace.map(t => ({
          role: t && t.role !== undefined ? String(t.role) : null,
          step: t && t.step !== undefined && t.step !== '' ? String(t.step) : null,
          action: t && t.action !== undefined ? String(t.action) : null,
          output: !!(t && t.output), content: !!(t && t.content), evidence: !!(t && t.evidence),
        })),
        anomaly: parser.anomalyOf(stats),
      }
    }
    // 同一套取法喂给 PyYAML——两边取同一批字段，比的才是解析结果本身。
    // PyYAML 也拒的形状（夹具自己写错、或本来就是非法 YAML）返回 null，由调用方分开处理。
    const pyOf = (text) => {
      try {
        return JSON.parse(execFileSync(PY.cmd, [...PY.prefix, '-c', `
import yaml, json, sys
doc = yaml.safe_load(sys.stdin.read()) or {}
trace = doc.get('trace') or []
def s(v): return None if v is None else str(v)
print(json.dumps([{'role': s(t.get('role')), 'step': s(t.get('step')), 'action': s(t.get('action')),
                   'output': bool(t.get('output')), 'content': bool(t.get('content')),
                   'evidence': bool(t.get('evidence'))} for t in trace], ensure_ascii=False))
`], { input: text, encoding: 'utf8' }).toString())
      } catch (e) {
        return null
      }
    }

    const userBlock = ['  - role: user', '    step: 1', '    content: "起不来"',
      '    evidence:', '      inline: "ERR 507015"', '      files: ["a.log"]']
    const agentBlock = ['  - role: agent', '    step: 2', '    action: hit', '    output: "命中"']
    const shapes = [
      ['块写法（2 空格缩进）', ['session_id: "s"', 'trace:', ...userBlock, ...agentBlock].join('\n')],
      ['块写法（dash 4 空格 / 键 6 空格）', ['session_id: "s"', 'trace:',
        '    - role: user', '      step: 1', '      content: "起不来"',
        '    - role: agent', '      step: 2', '      action: hit', '      output: "命中"'].join('\n')],
      ['内联写法（一行一事件）', ['session_id: "s"', 'trace:',
        '  - {role: user, step: 1, content: "起不来", evidence: {inline: "ERR 507015", files: ["a.log"]}}',
        '  - {role: agent, step: 2, action: hit, output: "命中"}'].join('\n')],
      // 折行的行内集合：合法 YAML，PyYAML 收 N 条。旧实现只读出第一条 → 面板上"只有第一步"。
      ['折行的行内映射', ['session_id: "s"', 'trace:',
        '  - {role: user, step: 1,',
        '     content: "起不来",',
        '     evidence: {inline: "ERR 507015", files: ["a.log"]}}',
        '  - {role: agent, step: 2,',
        '     action: hit, output: "命中"}'].join('\n')],
      ['折行的行内序列', ['session_id: "s"', 'trace: [{role: user, step: 1, content: "起不来"},',
        '  {role: agent, step: 2, action: hit, output: "命中"}]'].join('\n')],
      // PyYAML 自己生成的形状：序列项与键同缩进（`trace:` 下一行就是 `- role:`）
      ['序列项与键同缩进', ['session_id: "s"', 'trace:',
        '- role: user', '  step: 1', '  content: "起不来"',
        '- role: agent', '  step: 2', '  action: hit', '  output: "命中"'].join('\n')],
      ['文件带 BOM 且首行不是注释', '\uFEFF' + ['session_id: "s"', 'trace:', ...userBlock, ...agentBlock].join('\n')],
      ['CRLF + BOM', ('\uFEFF' + ['session_id: "s"', 'trace:', ...userBlock, ...agentBlock].join('\n')).replace(/\n/g, '\r\n')],
      ['块标量 output（>- / |）', ['session_id: "s"', 'trace:', ...userBlock.slice(0, 3),
        '  - role: agent', '    step: 2', '    action: hit', '    output: >-', '      第一行', '      第二行',
        '    reason: |', '      依据一行'].join('\n')],
      ['多行普通标量（含以 - 开头的行）', ['session_id: "s"', 'trace:', ...userBlock.slice(0, 3),
        '  - role: agent', '    step: 2', '    action: hit', '    output: 结论',
        '      - 检查项 1', '      - 检查项 2'].join('\n')],
      ['dash 单独一行、映射另起', ['session_id: "s"', 'trace:', ...userBlock, '  -',
        '    role: agent', '    step: 2', '    action: hit', '    output: "命中"'].join('\n')],
      // 序列项本身是标量时的跨行写法（`tool_calls` 里一条长记录折行就会长这样）：
      // 续行既不是新项、也不是映射的键，旧实现把它整段丢掉，而它还会被算成"被丢弃的事件行"。
      ['序列项是跨行标量（引号）', ['session_id: "s"', 'trace:', ...userBlock,
        '    tool_calls:', '      - "gh api x: 事实"', '      - "另一条', '        续行"',
        ...agentBlock].join('\n')],
      ['序列项是跨行标量（普通）', ['session_id: "s"', 'trace:', ...userBlock,
        '    tool_calls:', '      - 第一条', '        第二条', ...agentBlock].join('\n')],
    ]
    let shapeDiff = 0
    for (const [name, text] of shapes) {
      const mine = panelOf(text)
      const want = pyOf(text)
      if (want === null) {   // 夹具自己不是合法 YAML：这条判据失效，必须红（别让它冒充通过）
        shapeDiff++
        expect('夹具是合法 YAML（PyYAML 收）：' + name, false, 'PyYAML 拒了这份夹具')
        continue
      }
      const same = JSON.stringify(mine.rows) === JSON.stringify(want)
      if (!same) shapeDiff++
      expect('解析口径与 PyYAML 一致：' + name, same,
        '\n    面板: ' + JSON.stringify(mine.rows) + '\n    PyYAML: ' + JSON.stringify(want))
      expect('合法 YAML 不报异常：' + name, mine.anomaly === null, JSON.stringify(mine.anomaly))
    }
    expect('形状夹具全部与 PyYAML 一致（' + shapes.length + ' 种）', shapeDiff === 0, '不一致 ' + shapeDiff + ' 种')

    // 反方向：结构坏的 trace 不许静默少事件——必须报出异常（行号 + 行数）
    const brokenIndent = ['session_id: "s"', 'trace:',
      '  - role: user', '    step: 1', '    content: "起不来"',
      '   - role: agent', '     step: 2', '     output: "命中"'].join('\n')
    const brokenFlow = ['session_id: "s"', 'trace:', '  - {role: user, step: 1, content: "起不来"'].join('\n')
    const bi = panelOf(brokenIndent)
    const bf = panelOf(brokenFlow)
    expect('缩进错乱：解析少事件时给出异常（不许静默）',
      !!(bi.anomaly && bi.anomaly.dropped > 0 && bi.anomaly.firstLine > 0), JSON.stringify(bi.anomaly))
    expect('行内集合没闭合：给出异常', !!(bf.anomaly && bf.anomaly.unbalancedFlow), JSON.stringify(bf.anomaly))

    // 上屏通路：host 把异常放进 RPC 结果、client 把它渲染出来（两边都钉，缺一边等于没有）
    expect('host：traces-detail 与 traces-list 都带解析异常字段',
      /parseAnomaly: anomalyOf\(stats\)/.test(hostSrc)
      && (hostSrc.match(/parseAnomaly: anomalyOf\(stats\)/g) || []).length === 2)
    expect('host：异常带上行号与行数（读者要能自己去核对那几行）',
      /firstLine:/.test(hostSrc) && /dropped: dropped\.length/.test(hostSrc))
    expect('client：诊断轨迹那行在异常时标「可能不完整」', /（可能不完整）/.test(ascSrc))
    expect('client：异常给出行号与一个动作（请核对缩进与引号）',
      /function anomalyText\(a\)/.test(ascSrc) && /第 ' \+ a\.firstLine \+ ' 行起/.test(ascSrc)
      && /请核对这几行的缩进与引号/.test(ascSrc))
    expect('client：会话列表的步数行同样报异常（"1 用户输入"不许看起来像真的）',
      /anomalyText\(s\.parseAnomaly\)/.test(ascSrc))

    // 渲染层实测（不是只断言源码里有那句话）：异常至少要在**收起态**就说出来——展开态靠点击，
    // mock 的 hook 槽位读不回展开内容（同"展开单卡"一节记的限制）。
    {
      const base = {
        file: 'sess-anom.yaml', status: 'in_progress', framework: 'vllm-ascend',
        platform: 'A2-910B', category: 'interrupt', activeCase: null, activeCaseInKb: false,
        feedbackPending: null, summarySnippet: '问题背景：服务启动失败', userSteps: 1, agentSteps: 0,
        lastRole: 'user', lastOutput: null, updatedAt: new Date().toISOString(),
      }
      const withAnomaly = Object.assign({}, base, {
        sessionId: 'sess-anom',
        parseAnomaly: { dropped: 3, firstLine: 8, sample: '- role: agent', unbalancedFlow: false },
      })
      const without = Object.assign({}, base, { sessionId: 'sess-clean', file: 'sess-clean.yaml', parseAnomaly: null })
      const anomHost = (m) => m === 'ascend-traces-list'
        ? { ok: true, sessions: [withAnomaly, without] }
        : { ok: true, steps: [], summary: null }
      const anomText = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, anomHost)).text
      const hits = (anomText.match(/轨迹可能不完整/g) || []).length
      expect('收起态就报异常，且只报那一张卡（另一张不误报）', hits === 1, '出现 ' + hits + ' 次')
      expect('异常带上行数与行号（读者能去核对那几行）',
        /还有 3 行没被解析（第 8 行起）/.test(anomText), anomText.slice(0, 200))
      expect('异常只给"结论 + 行号 + 一个动作"，不把成因解释摊在卡上',
        !/面板按 YAML 结构读|不在下面的步数里|发回来核对/.test(anomText), anomText.slice(0, 200))
    }

    // 真实 trace（主检出那一份，`scripts/shared_dir.py traces` 是它的解析入口；CI 里没有这个
    // 目录——运行时件不进 git——此时只跑形状夹具，如实说明跳过了什么）
    const tracesDir = (() => {
      try {
        const out = pyRun(['scripts/shared_dir.py', 'traces'], { cwd: repo, env: PY_ENV }).toString().trim().split('\n')
        return out[out.length - 1].trim()
      } catch (e) { return null }
    })()
    const realFiles = tracesDir && fs.existsSync(tracesDir)
      ? fs.readdirSync(tracesDir).filter(f => f.endsWith('.yaml')).sort()
      : []
    if (!realFiles.length) {
      console.log('  · 真实 trace 对照：跳过（本检出的 traces/ 里没有 .yaml）')
    }
    let realDiff = 0
    for (const f of realFiles) {
      const text = fs.readFileSync(path.join(tracesDir, f), 'utf8')
      const mine = panelOf(text)
      const same = JSON.stringify(mine.rows) === JSON.stringify(pyOf(text))
      const clean = mine.anomaly === null
      if (!same || !clean) realDiff++
      else continue
      expect('真实 trace 与 PyYAML 一致且无异常：' + f, false,
        '一致=' + same + ' 异常=' + JSON.stringify(mine.anomaly))
    }
    if (realFiles.length) {
      expect('真实 trace 逐份与 PyYAML 一致（' + realFiles.length + ' 份）', realDiff === 0, '不符 ' + realDiff + ' 份')
    }
  }

  // —— 指令区形态（2026-09-12 改版）：按钮横排 + 卡片内不复读提示 ——
  {
    expect('指令区：按钮为横向 flex 换行（竖排会撑高卡片）', /display: 'flex', flexWrap: 'wrap', gap: 8/.test(ascSrc))
    expect('指令区：卡片内不再逐卡复读提示文案', !/['"]这一单结束了/.test(ascSrc) && !/['"]这单已闭环\.要更正/.test(ascSrc))
    expect('指令区：展开的命令块只有一处（点谁显示谁）', (ascSrc.match(/openedCmd \? React\.createElement/g) || []).length === 1)
    // 沉淀区同一条纪律：多候选时也只有一个展开位（铺一屏命令等于没折叠）
    expect('沉淀区：展开的命令行同样只有一处（多候选也点谁显示谁）',
      (ascSrc.match(/sedCmdText \? React\.createElement/g) || []).length === 1)
  }

  // —— 长输入不把卡片撑爆（2026-09 重做）：轨迹默认只铺前 8 步 + 列表自带渲染上限 + 证据切片 ——
  // 为什么单列这一条：实测最大的 trace 32 事件 / 22KB、单步 output 上限 3000 字，全铺开是一屏
  // 读不完的过程记录（"打开慢"其实是"读不动"）；而 evidence.inline 此前**没有上限**——一次 issue
  // 粘贴就能塞进几万字。两处都要有上限，且**截断必须说出来**（不静默截断是本仓库的既有纪律：
  // 报告区超限时说"还有 N 块未渲染"）。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    expect('host：证据原文有渲染上限（与 output/reason 同口径 3000 字）',
      /const INLINE_MAX = 3000/.test(hostSrc))
    // 关键的一半：切片之外**必须给出原文长度**。徽标读的是它——只说 3000 会把 4 万字的原文说小，
    // 而徽标正是读者决定"要不要点开看"的依据。
    expect('host：切片同时给出原文长度（inlineChars），两种证据写法都要给',
      (hostSrc.match(/inlineChars = /g) || []).length === 2)
    expect('client：证据徽标读原文长度而不是被切片后的长度',
      /\(ev\.inlineChars \|\| ev\.inline\.length\)/.test(ascSrc))
    expect('client：原文被截断时如实说（不静默截断）',
      /此处显示前 ' \+ ev\.inline\.length \+ ' 字'/.test(ascSrc))
    expect('client：轨迹默认只铺前 8 步',
      /const STEP_PREVIEW = 8/.test(ascSrc) && /showAllSteps \? shown : shown\.slice\(0, STEP_PREVIEW\)/.test(ascSrc))
    expect('client：展开/收起是一处开关（不是两个各自为政的按钮）',
      /'展开剩余 ' \+ moreSteps \+ ' 步'/.test(ascSrc) && /'收起，只看前 ' \+ STEP_PREVIEW \+ ' 步'/.test(ascSrc))
    expect('client：轨迹列表自带渲染上限（与报告区同手法）', /maxHeight: 620, overflowY: 'auto'/.test(ascSrc))
    // 折叠不能把"还有下一步"画成终点：竖轨连的是下一步，后面还有没铺开的步时最后一条可见步也要留轨
    expect('client：折叠时竖轨留到边界（不把折叠点画成轨迹终点）',
      /const last = i === visible\.length - 1 && moreSteps === 0/.test(ascSrc))
  }

  // —— 关联面：这一步用到/查到了什么外部东西（2026-09-17）——
  // 为什么单列：这些字段（ref_ids/outcome/note/case/candidates/sources/tool_calls）**trace 里一直在写**，
  // 而 host 的 traceDetail 只提 7 个字段，全被丢掉——于是"这单关联了哪些 case / 哪些 reference /
  // 查了哪些外部资料"只能去翻 YAML。判据分两半：host 提得出来（真跑解析器）+ client 画得出来。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    expect('host：关联面字段都在 traceDetail 的映射里',
      /caseId: eventStr\(/.test(hostSrc) && /candidates: eventList\(/.test(hostSrc)
      && /refs: eventList\(/.test(hostSrc) && /purpose: eventStr\(/.test(hostSrc)
      && /outcome: eventStr\(/.test(hostSrc) && /note: eventStr\(/.test(hostSrc)
      && /toolCalls: eventList\(/.test(hostSrc))
    // schema 漂移：旧 trace 写单数 `ref_id`，新 trace 写数组 `ref_ids`——只吃一种，最丰富的那份读不出来
    expect('host：先验引用两种写法都吃（ref_id 单数 / ref_ids 数组）',
      /t\.ref_ids !== undefined \? t\.ref_ids : t\.ref_id/.test(hostSrc))
    // 外部链接有两种位置：user 事件在 evidence.sources，agent 事件在顶层 sources。
    // 只吃前者等于 **agent 查到的资料一条都看不到**（实测：gh issue view / web_fetch 走后者）。
    expect('host：外部链接两种位置都吃（顶层 sources + evidence.sources）且去重',
      /const top = eventList\(t && t\.sources\)/.test(hostSrc) && /ev\.sources\) \? ev\.sources : \[\]/.test(hostSrc)
      && /a\.indexOf\(u\) === k/.test(hostSrc))
    // 真跑一遍解析器 + 提取逻辑（不复制逻辑：直接抽 host 的函数体）
    {
      const from = hostSrc.indexOf('function eventList(')
      const to = hostSrc.indexOf('async function traceDetail(')
      expect('host：事件字段提取器可抽出（eventList → traceDetail 区块存在）', from > 0 && to > from)
      const m = new Function(hostSrc.slice(from, to)
        + '\nreturn { eventList: eventList, eventStr: eventStr };')()
      expect('eventList：数组原样、单值成单元素、空值给空数组',
        JSON.stringify(m.eventList(['a', 'b'])) === '["a","b"]' && JSON.stringify(m.eventList('x')) === '["x"]'
        && m.eventList(null).length === 0 && m.eventList('').length === 0 && m.eventList(undefined).length === 0)
      expect('eventList：行内写法（`[a, b]` 字符串）也展开',
        JSON.stringify(m.eventList('[a, b]')) === '["a","b"]'
        && JSON.stringify(m.eventList('["a", "b"]')) === '["a","b"]')
      expect('eventStr：空值给 null（不是空串——空串会让"没有"与"写了空"同形）',
        m.eventStr('') === null && m.eventStr(null) === null && m.eventStr('x') === 'x')
    }
    // client 渲染：四类节点 + 三态徽标 + 甄别理由
    expect('client：先验三态徽标**只挂参考层步骤**（feedback 的 outcome 是回报结果，挂成命中会读反）',
      /const refOutcome = \(st\.action === 'reference_lookup' && st\.outcome\) \? REF_OUTCOME\[st\.outcome\] : null/.test(ascSrc))
    expect('client：三态词表给中文名（命中 / 未命中 / 未查）',
      /hit: \{ label: '命中'/.test(ascSrc) && /miss: \{ label: '未命中'/.test(ascSrc) && /skipped: \{ label: '未查'/.test(ascSrc))
    expect('client：四类节点各一行（case / 候选 / 先验 / 资料）',
      /assocRow\('case', 'case'/.test(ascSrc) && /assocRow\('cand', '候选'/.test(ascSrc)
      && /assocRow\('refs', '先验'/.test(ascSrc) && /assocRow\('src', '资料'/.test(ascSrc))
    // "甄别"是全块最值钱的一行：它把"命中"与"有用"分开（实测例：命中但判为不同族）
    expect('client：甄别理由单独成行（区分"命中"与"有用"）', /'甄别'/.test(ascSrc) && /st\.note/.test(ascSrc))
    expect('client：消费点给人读名（签名触发 / 修复依据 …）而不是原词',
      /const PURPOSE_LABELS = \{/.test(ascSrc) && /signature: '签名触发'/.test(ascSrc))
    // 可点性必须诚实：能点的才画成可点（边框 + 品牌色），不可点的是灰底只读 chip
    expect('client：外部链接可点（走同一条打开通路）', /onClick: \(\) => openFile\(u\)/.test(ascSrc))
    expect('client：链接标签是"域名 + 末段"（全 URL 在 title，三四个就把一行撑爆）',
      /function shortUrl\(u\)/.test(ascSrc) && /seg\[0\] \+ '\/…\/' \+ seg\[seg\.length - 1\]/.test(ascSrc))
    // 打开反馈必须落在**点击处**：成功与失败都按目标就地显示。
    // 实测踩过（用户报"资料链接点了没反应"）：反馈只渲染在卡头的 docRow 上，而证据文件与资料链接
    // 都在展开后的轨迹里——点完那一行什么都不变，成功与失败同形。这与 2026-09 修报告入口时同一个坑
    // （当时的注释就写着"静默失败等于点了没反应"），所以这次把"按目标就地显示"钉成判据。
    expect('client：打开反馈按目标就地显示（chip 文案 + 明细都在点击处）',
      /function openLabel\(f, fallback\)/.test(ascSrc) && /function openNote\(f\)/.test(ascSrc)
      && /openLabel\(u, shortUrl\(u\)\)/.test(ascSrc) && /openLabel\(f, baseName\(f\)\)/.test(ascSrc)
      && /setOpenErr\(\{ at: f, msg:/.test(ascSrc) && /setOpenDone, \{ at: f, via:/.test(ascSrc))
    expect('client：成功也是反馈（打了浏览器而面板不吭声，读者同样判成"没反应"）',
      /'已交给浏览器'/.test(ascSrc) && /'打不开'/.test(ascSrc))
    // 措辞只讲证据支持的那一半：host 只证明了"URL 交给了浏览器"（退出码 0），验证不了浏览器
    // 有没有到前台。实测（用户报"显示已打开但没打开"）：从 DSH 的 shell 打开时浏览器不到前台——
    // 本地 http 探针证明 URL 确实被浏览器取走了，而屏幕上什么都没有。所以不许写"已打开"。
    expect('client：不用"已打开"这种面板验证不了的措辞（只说"已交给浏览器"）',
      !/'已打开'/.test(ascSrc))
    // 另一半用「复制链接」兜住：它不依赖浏览器焦点，是这条反馈里真正能兑现"拿到资料"的动作
    expect('client：反馈里带「复制链接」（不依赖浏览器焦点的兜底）',
      /'link:' \+ f/.test(ascSrc) && /'复制链接'/.test(ascSrc))
    // 徽标**用行的名字、不发明伞形词**：曾叫「关联 N」「外部 N」，两个都含糊——
    // "关联"没说清关联什么；"外部"更错（先验词条就在库里）。所以只给候选/资料两个计数，
    // 参考层步骤已由「参考层 + 三态」覆盖，不重复给。
    expect('client：徽标用行的名字（候选 N / 资料 N），不用「关联/外部」这类伞形词',
      /'候选 ' \+ st\.candidates\.length/.test(ascSrc) && /'资料 ' \+ st\.sources\.length/.test(ascSrc)
      && !/'关联 ' \+/.test(ascSrc) && !/外部条数/.test(ascSrc))
  }

  // —— 打开通路：外部 URL 与仓库内文件走同一条，但 URL **不能拼 cwd** ——
  // 实测风险：openEvidence 原先无条件 `cwd + '/' + path`，把 https://… 拼成本地路径去找文件——
  // 表现为"点了链接没反应"。所以先分流再各自校验；仓库内相对路径的守卫（拒绝对路径与 ..）保持。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    const regs = {}
    const seen = []
    const shell = {
      resolve: (x) => x,
      run: async (spec) => {
        seen.push(String(spec.command))
        return { exitCode: 0, timedOut: false, aborted: false, stdout: { text: '' }, stderr: { text: '' } }
      },
    }
    const ctx = { get: (n) => n === 'fs' ? undefined : n === 'shell' ? shell : n === 'sessions' ? { get: () => ({ header: { cwd: '/repo' } }), list: () => [{ header: { cwd: '/repo' } }] } : undefined }
    const harness = { handle: (name, fn) => { regs[name] = fn; return () => {} }, defineTool: (o) => o, registerTool: () => () => {} }
    new Function('harness', 'console', hostSrc)(harness, { error: () => {}, log: () => {} }).apply(ctx)
    const U = 'https://github.com/vllm-project/vllm-ascend/issues/4914'
    // isTab: 每种方言试一次后成功即返回，所以只跑第一条
    seen.length = 0
    const rUrl = await regs['ascend-open-evidence']({ sessionId: 's', path: U })
    expect('打开外部链接：不拼 cwd（把 URL 当本地路径就永远点不开）',
      rUrl && rUrl.opened === true && seen.length === 1 && seen[0].indexOf(U) >= 0 && seen[0].indexOf('/repo/https') < 0,
      JSON.stringify(seen))
    seen.length = 0
    const rFile = await regs['ascend-open-evidence']({ sessionId: 's', path: 'traces/evidence/x.log' })
    expect('打开仓库内文件：仍按 cwd 拼相对路径（原有行为不变）',
      rFile && rFile.opened === true && seen[0].indexOf('/repo/traces/evidence/x.log') >= 0, JSON.stringify(seen))
    seen.length = 0
    const rAbs = await regs['ascend-open-evidence']({ sessionId: 's', path: '/etc/passwd' })
    expect('打开仓库外绝对路径：仍然拒绝（URL 分流没有把这道守卫放开）',
      rAbs && rAbs.opened === false && seen.length === 0, JSON.stringify({ r: rAbs, seen: seen }))
    const rDot = await regs['ascend-open-evidence']({ sessionId: 's', path: '../../etc/passwd' })
    expect('打开 .. 路径：仍然拒绝', rDot && rDot.opened === false && seen.length === 0, JSON.stringify(rDot))
  }

  // —— 人读定位报告与沉淀候选的入口（diagnose 步骤 6 产出）——
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    // 报告名的两种来源都要认（见 reportFileOf）。为什么这条判据从"断言某一行写法"改成"跑函数"：
    // 实测缺陷（2026-09-14）正是"只读顶层 `report_file`"——而写作文档给的是 report 事件内写法，
    // 于是报告落在 traces/ 里、卡片上却没有入口。断言源码里有没有某个字段名拦不住这类偏差。
    const fromR = hostSrc.indexOf('const PLACEHOLDER_CASE')
    const toR = hostSrc.indexOf('async function listTraces(')
    expect('host 的报告名/占位串判定可抽出（占位串词表 + 两个判定函数 → listTraces 区块存在）', fromR > 0 && toR > fromR)
    const helpers = new Function(hostSrc.slice(fromR, toR)
      + '\nreturn { reportFileOf: reportFileOf, activeCaseKindOf: activeCaseKindOf, normalizeReportName: normalizeReportName };')()
    const files = new Set(['s.yaml', 's.report.md', 'other.report.md'])
    const r1 = helpers.reportFileOf({ report_file: 'x.report.md' }, files, 's.yaml')
    expect('报告名：顶层 report_file 优先', !!r1 && r1.name === 'x.report.md' && r1.source === 'trace', JSON.stringify(r1))
    const r2 = helpers.reportFileOf({ trace: [{ action: 'report', report_file: 'in-event.report.md' }] }, files, 's.yaml')
    expect('报告名：只有 report 事件里记了也算（写作文档给的就是这种写法）',
      !!r2 && r2.name === 'in-event.report.md' && r2.source === 'trace', JSON.stringify(r2))
    const r3 = helpers.reportFileOf({ session_id: 's' }, files, 's.yaml')
    expect('报告名：两处都没记 → 退到同名规则（报告确实在 traces/ 里就给入口）',
      !!r3 && r3.name === 's.report.md' && r3.source === 'name', JSON.stringify(r3))
    const r4 = helpers.reportFileOf({ session_id: 's' }, new Set(['s.yaml']), 's.yaml')
    expect('报告名：同名文件不存在 → 不给入口（不编一个读不到的名字）', r4 === null, JSON.stringify(r4))
    // 归一：契约是文件名，但 trace 里常写成带目录的路径，而面板读/开报告时统一在 traces/ 下拼路径
    // ——不归一就会拼成 traces/traces/…（实测症状：点「打开报告」找的是 …\ascend-sleuth\traces\traces\…）
    const norm = helpers.normalizeReportName
    expect('报告名归一：带目录的四种写法都还原成文件名',
      norm('traces/x.report.md') === 'x.report.md'
      && norm('traces\\x.report.md') === 'x.report.md'
      && norm('./traces/x.report.md') === 'x.report.md'
      && norm('C:/repo/ascend-sleuth/traces/x.report.md') === 'x.report.md', JSON.stringify([
        norm('traces/x.report.md'), norm('traces\\x.report.md'), norm('./traces/x.report.md'),
        norm('C:/repo/ascend-sleuth/traces/x.report.md')]))
    expect('报告名归一：文件名原样、别的目录不擅自改写、空值给 null',
      norm('x.report.md') === 'x.report.md' && norm('reports/x.md') === 'reports/x.md'
      && norm('') === null && norm(null) === null)
    const r5 = helpers.reportFileOf({ trace: [{ action: 'report', report_file: 'traces/in-event.report.md' }] }, files, 's.yaml')
    expect('报告名：事件里写了带 traces/ 前缀的路径也归一（读得到才算数）',
      !!r5 && r5.name === 'in-event.report.md', JSON.stringify(r5))
    expect('占位串判定：pending-investigation 系（含带说明的写法）都不算 case',
      helpers.activeCaseKindOf('pending-investigation') === 'placeholder'
      && helpers.activeCaseKindOf('pending-investigation (upstream #14728)') === 'placeholder'
      && helpers.activeCaseKindOf('pending_investigation') === 'placeholder')
    expect('占位串判定：真实 case id 仍算 case，空值算没有',
      helpers.activeCaseKindOf('VLLM-ASC-12989') === 'case'
      && helpers.activeCaseKindOf(null) === null && helpers.activeCaseKindOf('') === null
      && helpers.activeCaseKindOf('null') === null)
    expect('host 从 trace 读 report_file 与 sediment_candidates',
      /reportFileOf\(doc, fileNames, ent\.name\)/.test(hostSrc)
      && /sedimentCandidates: Array\.isArray\(doc\.sediment_candidates\)/.test(hostSrc))
    expect('读报告与列表用同一个报告名口径（否则"入口指向 A、点开读 B"）',
      (hostSrc.match(/reportFileOf\(/g) || []).length >= 3)
    expect('client 给「打开报告」入口（复用证据打开通路，不新造 RPC）',
      /'traces\/' \+ s\.reportFile/.test(ascSrc) && /打开报告/.test(ascSrc))
    expect('client 说明入口是"按同名规则找到"的（trace 未记报告名时不许闷着）',
      /s\.reportSource === 'name'/.test(ascSrc) && /按同名规则找到/.test(ascSrc))
    expect('client 显示沉淀建议条数（措辞是"建议"不是"待沉淀"——它不是债务）',
      /沉淀建议 ' \+ s\.sedimentCandidates/.test(ascSrc))
    expect('面板不写入报告内容（只读入口）', !/ascend-write-report/.test(ascSrc) && !/ascend-write-report/.test(hostSrc))

    // 渲染层实测（收起态即可见）：三种卡片各一张——占位串单、真 case 单、报告靠同名规则找到的单
    {
      const base = {
        file: 's.yaml', status: 'escalated', framework: 'vllm-ascend', platform: 'A2-910B',
        category: 'interrupt', activeCaseInKb: false, feedbackPending: null,
        summarySnippet: '问题背景：服务启动失败', userSteps: 2, agentSteps: 4,
        lastRole: 'agent', lastOutput: null, updatedAt: new Date().toISOString(),
      }
      const placeholder = Object.assign({}, base, {
        sessionId: 's-ph', activeCase: 'pending-investigation (upstream #14728)', activeCaseKind: 'placeholder',
      })
      const realCase = Object.assign({}, base, {
        sessionId: 's-case', activeCase: 'VLLM-ASC-12989', activeCaseKind: 'case', activeCaseInKb: true,
      })
      const withReport = Object.assign({}, base, {
        sessionId: 's-rep', activeCase: null, activeCaseKind: null,
        reportFile: 's-rep.report.md', reportSource: 'name',
      })
      const host = (m) => m === 'ascend-traces-list'
        ? { ok: true, sessions: [placeholder, realCase, withReport] }
        : { ok: true, steps: [], summary: null }
      const ct = (await renderAsync(ascSrc, { sessionId: 'sess-1' }, host)).text
      const lines = ct.split('\n').map(x => x.trim())
      expect('占位串不当 case 显示：两张无命中单都给「未定位到知识库 case」，不给「定位」',
        lines.filter(x => x === '未定位到知识库 case').length === 2 && lines.filter(x => x === '定位').length === 1,
        '未定位=' + lines.filter(x => x === '未定位到知识库 case').length + ' 定位=' + lines.filter(x => x === '定位').length)
      expect('占位串把原值摆出来（不摆读者以为面板漏读了字段）',
        /pending-investigation \(upstream #14728\)/.test(ct), ct.slice(0, 240))
      // 卡面**不解释**：说明文字（占位串 / case id / 字段名）只进 tooltip 与 README。
      // 为什么单钉一条：这类"给改 trace 的人看的解释"被摊到卡上过两次，列表被读成文档。
      expect('卡面不出内部说法（占位串 / case id / 字段名）',
        !/占位串/.test(ct) && !/case id/.test(ct) && !/active_case/.test(ct), ct.slice(0, 300))
      expect('原值的解释放在 tooltip 里（hover 可查）',
        /«title:trace 里记的定位值（不是知识库里的 case）»/.test(ct))
      expect('报告入口：有报告的那张卡给「看报告」「打开报告」，没有的不给',
        (ct.match(/看报告/g) || []).length === 1 && (ct.match(/打开报告/g) || []).length === 1,
        '看报告=' + (ct.match(/看报告/g) || []).length)
      expect('报告名来自同名规则时说明来源（trace 未记报告名不许闷着）',
        /按同名规则找到/.test(ct) && /s-rep\.report\.md/.test(ct))
      expect('「打开报告」给的是单层 traces/ 路径（拼两层会打开不存在的文件）',
        /«title:traces\/s-rep\.report\.md»/.test(ct) && !/traces\/traces\//.test(ct),
        (ct.match(/«title:[^»]*»/g) || []).join(' '))
    }
  }

  // —— 词表口径：反馈债读 feedback.outcome（新口径）+ 兼容旧 trace 的 feedback_pending ——
  // 踩坑（实测）：词表从 `feedback_pending` 改成 `feedback.outcome: pending` 之后，**写侧改了、
  // 读侧没跟**——面板 host 仍只读旧字段，于是"待回报"从会话列表上静默消失：人以为没有债，
  // 实际是没人报结果。所以这里把"新口径必须读、旧件必须仍能读"两侧都钉住。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    const mhSrc = fs.readFileSync(path.join(repo, 'scripts/metrics_health.py'), 'utf8')
    expect('host 读新口径 feedback.outcome === pending',
      /String\(fb\.outcome \|\| ''\) === 'pending'/.test(hostSrc))
    expect('host 兼容旧 trace 的 feedback_pending（历史件仍要显示待回报）',
      /doc\.feedback_pending/.test(hostSrc))
    expect('面板补反馈指令指向新口径而非旧字段名',
      /feedback\.outcome: pending/.test(ascSrc) && !/含 feedback_pending 的/.test(ascSrc))
    expect('metrics_health 的补反馈指令同样用新口径',
      /含 feedback\.outcome: pending 的/.test(mhSrc) && !/含 feedback_pending 的/.test(mhSrc))
  }

  // —— 动态包的运行环境契约：客户端包内没有浏览器定时器全局 ——
  // 实测踩过：面板里一处 `setTimeout` 让用户点「打开报告」直接拿到
  // "RPC 失败: setTimeout is not available in a dynamic client half"。延时只能走注入的
  // Client Service `timer`（timeout(cb, ms) → disposer）。判据看**调用点**（带括号），
  // 注释里提到这个词不算违规。
  {
    const timerCall = /setTimeout\s*\(|setInterval\s*\(|requestAnimationFrame\s*\(|setImmediate\s*\(/
    expect('client 无全局定时器调用点（动态客户端包不提供）', !timerCall.test(ascSrc))
    expect('延时复位走注入的 timer 服务', /ctx\.get\('timer'\)/.test(ascSrc) && /timer\.timeout\(/.test(ascSrc))
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    expect('host 无定时器调用点（面板不靠轮询）', !timerCall.test(hostSrc))
  }

  // —— 打开文件必须跨 shell 方言（DSH 在 Windows 上把 ctx.shell 接到 PowerShell，不是 bash）——
  // 实测踩过：`(open X || xdg-open X) >/dev/null 2>&1 &` 在 PowerShell 5.1 是语法错误，
  // 被后台重定向吞掉 → 用户点「打开报告」完全没反应。判据：不出现 bash-only 的 `||` 链、
  // 有 PowerShell/macOS/Linux/Windows 四条尝试、成功与失败都有反馈。
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    // 判据看**代码**：注释里为说明"旧实现错在哪"会引用 bash-only 写法，那不算违规。
    const hostCode = hostSrc.split('\n').filter(l => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
    expect('host 不用 bash-only 的 `||` 打开链（PowerShell 下是语法错误）',
      !/xdg-open[^\n]*\|\|/.test(hostCode) && !/\(open [^\n]*\|\|/.test(hostCode))
    expect('host 打开尝试跨方言（Start-Process / open / xdg-open / explorer）',
      /Start-Process -FilePath/.test(hostSrc) && /'open ' \+ q/.test(hostSrc)
      && /'xdg-open ' \+ q/.test(hostSrc) && /explorer\.exe ' \+ q/.test(hostSrc))
    expect('host 打开结果按 exit code 判定并回报 via', /via: a\.via/.test(hostSrc) && /okCodes/.test(hostSrc))
    expect('client 打开成功有反馈（措辞只说"已交给浏览器"）', /'已交给浏览器'/.test(ascSrc))
    expect('client 打开失败显原因', /打开失败（无返回）/.test(ascSrc))
  }

  // ================= 面板共通约定（跨两个面板的机械检查）=================
  // 规范与理由见 dsh-plugins/README.md「文案规范」。八条里只有这一条同时满足
  // 检查准入三条件：① 机械可查 ② 后果确定（星号会原样渲染成字符、且会被复制进指令）
  // ③ 复发 ≥2 次（ev-panel 一次、ascend-panel 一次，都是实测发现的）。其余七条是判断性
  // 规范，对照规范表人审——不为"AI 味"造硬门，那是假装硬化（原则六）。
  console.log('\n[面板共通约定 · 文案]')
  {
    const PANEL_SOURCES = [
      'dsh-plugins/ev-panel/panel-client.js', 'dsh-plugins/ev-panel/panel-host.js',
      'dsh-plugins/ascend-panel/panel-client.js', 'dsh-plugins/ascend-panel/panel-host.js',
    ]
    // 抽取"人读文案里的字面星号"：跳过注释与 CSS 模板块，且要求同一字符串里有中文
    // （否则会把正则字面量、`'**'` 这类代码里的星号误判成文案缺陷）。
    function literalAsterisks(text) {
      const hits = []
      let inCss = false
      text.split('\n').forEach((line, idx) => {
        if (/const CSS = `/.test(line)) inCss = true
        if (inCss) {
          if (line.trimEnd().endsWith('`') && !/const CSS = `/.test(line)) inCss = false
          return
        }
        const code = line.replace(/\/\/.*$/, '').replace(/\/\*.*?\*\//g, '')
        if (/^\s*\*/.test(code)) return
        for (const m of code.matchAll(/'([^'\\\n]*)'|"([^"\\\n]*)"/g)) {
          const s = m[1] !== undefined ? m[1] : m[2]
          if (s && /\*\*/.test(s) && /[\u4e00-\u9fff]/.test(s)) {
            hits.push((idx + 1) + ': ' + s.slice(0, 70))
          }
        }
      })
      return hits
    }
    for (const rel of PANEL_SOURCES) {
      const bad = literalAsterisks(fs.readFileSync(path.join(repo, rel), 'utf8'))
      expect('人读文案无字面 Markdown 星号 · ' + rel.split('/')[1] + '/' + path.basename(rel),
        bad.length === 0, bad.join(' | '))
    }
    // 文案规范只有一个权威处：**共用条目**归 docs/spec/writing-norms.md，面板 README 只保留自己的
    // 定制条款。原先这里钉的是"面板 README 里恰好有 8 行编号表"——那是规范合并进唯一权威处
    // （并拆成 15 个共用条目 + 各面定制条款）**之后恒红的旧断言**：断言钉的是它当年的载体形态，
    // 不是不变量。现在钉不变量本身：权威处存在且被本文件指向、权威处非空、定制条款成条。
    const sharedReadme = path.join(repo, 'dsh-plugins/README.md')
    expect('面板共通约定有唯一权威处（dsh-plugins/README.md）', fs.existsSync(sharedReadme))
    const sharedText = fs.existsSync(sharedReadme) ? fs.readFileSync(sharedReadme, 'utf8') : ''
    const normsDoc = path.join(repo, 'docs/spec/writing-norms.md')
    expect('文案共用条目归唯一权威处（docs/spec/writing-norms.md 存在且被面板约定指向）',
      fs.existsSync(normsDoc) && /docs\/spec\/writing-norms\.md/.test(sharedText))
    const normRows = fs.existsSync(normsDoc)
      ? (fs.readFileSync(normsDoc, 'utf8').match(/^\| \d+ \|/gm) || []).length : 0
    expect('唯一权威处确有条目表（指向的不是空文件）', normRows >= 10, String(normRows))
    const customClauses = (sharedText.match(/^\d+\.\s+\*\*/gm) || []).length
    expect('面板自己的定制条款成条（共用条目不在此复制）', customClauses >= 3, String(customClauses))
    for (const rel of ['dsh-plugins/ev-panel/README.md', 'dsh-plugins/ascend-panel/README.md']) {
      const t = fs.readFileSync(path.join(repo, rel), 'utf8')
      expect('「' + rel.split('/')[1] + '」README 指向共通约定（不在面板内各自维护一套）',
        /\.\.\/README\.md/.test(t), t.slice(0, 80))
    }
  }

  // ================= ev-panel host 失败路径 =================
  // 为什么单开一节（这一节是补 EV-2026-059 里如实记下的未覆盖缺口）：ev-panel 此前只测了
  // "判决 RPC 失败"这一种失败，而 host 的另外几条失败路径——拿不到工作区 / shell 服务缺失 /
  // Python 解释器缺失 / 脚本抛错（管道被拒等）/ 输出非 JSON——**没有任何断言**。它们与
  // "缺文件"（上一节已覆盖）成因不同：那些是"文件不在"，这些是"RPC 直接失败"，把它当成
  // 已覆盖就是假绿。手法与 ascend-panel 的 host 自诊断同：**从真实源文件抽出函数体**配桩运行，
  // 逻辑不复制（复制了断言就退化成"我自己跟自己对"）。
  console.log('\n[ev-panel host 失败路径 · 不崩且说清缺口]')
  {
    const evHostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ev-panel/panel-host.js'), 'utf8')
    const grabEv = (name) => {
      const lines = evHostSrc.split(/\r?\n/)
      const startIdx = lines.findIndex(l => /^    (async )?function /.test(l) && l.indexOf('function ' + name) > 0)
      if (startIdx < 0) return null
      for (let i = startIdx + 1; i < lines.length; i++) {
        if (lines[i] === '    }') return lines.slice(startIdx, i + 1).join('\n')
      }
      return null
    }
    expect('能从 ev-panel host 源文件抽出 resolveCwd / resolvePython / runScript',
      !!grabEv('resolveCwd') && !!grabEv('resolvePython') && !!grabEv('runScript'))
    const evFnSrc = [grabEv('resolveCwd'), 'let pythonCmd', grabEv('resolvePython'), grabEv('runScript')].join('\n')
    const buildEv = async (shell, sessions) => {
      const factory = new Function('shell', 'sessions',
        'return (async () => {\n' + evFnSrc + '\nreturn { runScript }\n})()')
      return await factory(shell, sessions)
    }
    const SESS = { get: () => ({ header: { cwd: 'E:/projects/ascend-sleuth' } }) }
    const okShell = (runImpl) => ({ resolve: (x) => x, run: runImpl })
    const pyOk = async (spec) => (/--version/.test(spec.command)
      ? { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' } }
      : await runImplRef(spec))

    // ① 拿不到工作区：不发起任何命令，并说清缺口（"无工作区还去跑命令"= 制造一条假报错）
    {
      let calls = 0
      const mod = await buildEv(okShell(async () => { calls++; return { exitCode: 0, stdout: { text: '{}' }, stderr: { text: '' } } }), undefined)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('无工作区：如实报「无法解析工作区」', r.ok === false && /无法解析工作区/.test(r.error), String(r.error).slice(0, 80))
      expect('无工作区：0 次 shell 调用（不发起注定失败的命令）', calls === 0, 'calls=' + calls)
    }
    // ② shell 服务缺失：报「shell 不可用」（不是静默返回空数据）
    {
      const mod = await buildEv(undefined, SESS)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('shell 不可用：如实报错（不假装成功）', r.ok === false && /shell 不可用/.test(r.error), String(r.error).slice(0, 80))
    }
    // ③ Python 解释器缺失：三个候选都探测过，报出候选与脚本名，且**不执行数据脚本**
    {
      const commands = []
      const mod = await buildEv(okShell(async (spec) => {
        commands.push(spec.command)
        return { exitCode: 1, stdout: { text: '' }, stderr: { text: 'command not found' } }
      }), SESS)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('解释器缺失：探测了 3 个候选', commands.filter(c => /--version/.test(c)).length === 3, commands.join(' | '))
      expect('解释器缺失：报出候选与所需脚本名',
        r.ok === false && /python3 \/ python \/ py -3/.test(r.error) && /ev_board_data\.py/.test(r.error), String(r.error).slice(0, 120))
      expect('解释器缺失：未执行数据脚本（只探测解释器）',
        !commands.some(c => /ev_board_data\.py/.test(c)), commands.join(' | '))
    }
    // ④ 脚本抛错（受限环境不允许创建管道 → EPERM）：必须说清脚本、工作目录、手工复现，并点明"与数据无关"
    {
      const mod = await buildEv(okShell(async (spec) => {
        if (/--version/.test(spec.command)) return { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' } }
        throw new Error('spawn EPERM')
      }), SESS)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('脚本抛错：如实报错且保留原因', r.ok === false && /EPERM/.test(r.error), String(r.error).slice(0, 90))
      expect('脚本抛错：点名脚本与工作目录', /ev_board_data\.py/.test(r.error) && /E:\/projects\/ascend-sleuth/.test(r.error), String(r.error).slice(0, 160))
      expect('脚本抛错：给出手工复现命令（可复制）', /手工复现/.test(r.error) && /python3? scripts\/ev_board_data\.py/.test(r.error), String(r.error).slice(0, 200))
      expect('脚本抛错：点明"执行环境"而非读者去查数据', /与数据无关/.test(r.error))
    }
    // ⑤ 脚本失败但 stderr 有内容：保留 stderr（截断到有限长度）；pyyaml 缺失给安装提示
    {
      const mod = await buildEv(okShell(async (spec) => (/--version/.test(spec.command)
        ? { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' } }
        : { exitCode: 1, stdout: { text: '' }, stderr: { text: 'x'.repeat(2000) + '\nModuleNotFoundError: No module named yaml' } })), SESS)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('脚本失败：如实报错且长度收敛（不把整页撑爆）', r.ok === false && r.error.length <= 800, 'len=' + String(r.error).length)
      const mod2 = await buildEv(okShell(async (spec) => (/--version/.test(spec.command)
        ? { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' } }
        : { exitCode: 1, stdout: { text: '' }, stderr: { text: "ModuleNotFoundError: No module named 'yaml'" } })), SESS)
      const r2 = await mod2.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('缺 PyYAML：给出安装提示（不是一句原始 traceback）', /pip install pyyaml/.test(r2.error), String(r2.error).slice(0, 120))
    }
    // ⑥ 输出非 JSON：报出脚本名与解析错误
    {
      const mod = await buildEv(okShell(async (spec) => (/--version/.test(spec.command)
        ? { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' } }
        : { exitCode: 0, stdout: { text: '这不是 JSON' }, stderr: { text: '' } })), SESS)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('输出非 JSON：报出脚本名 + 解析错误', r.ok === false && /ev_board_data\.py 输出非 JSON/.test(r.error), String(r.error).slice(0, 120))
    }
    // ⑦ 正常路径不因加了防御而破：合法 JSON → ok:true
    {
      const mod = await buildEv(okShell(async (spec) => (/--version/.test(spec.command)
        ? { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' } }
        : { exitCode: 0, stdout: { text: JSON.stringify({ ok: true, idea_count: 3 }) }, stderr: { text: '' } })), SESS)
      const r = await mod.runScript('sess-1', 'scripts/ev_board_data.py', null)
      expect('正常输出：仍解析为 JSON（正路未被防御破坏）', r.ok === true && r.data && r.data.idea_count === 3)
    }
  }

  // ================= 面板 host 服务缺失 · 只降级依赖它的功能 =================
  // 为什么单开一节：两个 host 原先都在 apply() 第一行写 `if (fs === undefined) return`——
  // **fs 一缺席，整个插件什么都不注册**（RPC 全没、tab 点开即死）。而 ev-panel 的 host
  // 根本不用 fs（数据全由 shell 跑脚本产出），ascend-panel 的指标 tab 那两项也不用 fs
  // （`loadMetricsVerdict` / `runLiveMetrics` 全程无 fs 调用，已按函数逐段核对）。
  // 失败形态是"挂载了却什么都没贡献"：面板不报错，只是什么都没发生——最难查的一类。
  console.log('\n[面板 host 服务缺失 · 只降级依赖它的功能]')
  {
    const loadHost = (rel) => fs.readFileSync(path.join(repo, rel), 'utf8')
    const codeOf = (src) => src.split(/\r?\n/).filter(l => !/^\s*\/\//.test(l)).join('\n')
    // 用最小 ctx/harness 驱动真 apply()（不复制逻辑）
    const driveHost = (src, svc) => {
      const regs = {}
      const ctx = { get: (n) => n === 'fs' ? svc.fs : n === 'shell' ? svc.shell : n === 'sessions' ? svc.sessions : undefined }
      const harness = {
        handle: (name, fn) => { regs[name] = fn; return () => {} },
        // ascend-panel 会 harness.defineTool({...}) 再 registerTool(ctx, tool)：
        // 桩只需把声明原样返回（真 registerTool 重名抛错一事，由 host 自己的 try/catch 兜住）
        defineTool: (opts) => opts,
        registerTool: () => () => {},
      }
      // 这两个 host 文件的形态是「return { apply(ctx) {...} }」——**先取插件对象再调 apply**；
      // 直接把源码当函数体执行只会拿到插件对象、apply 从不运行（踩过：RPC 一个都没注册）。
      const plugin = new Function('harness', 'console', src)(harness, { error: () => {}, log: () => {} })
      const disposer = plugin && typeof plugin.apply === 'function' ? plugin.apply(ctx) : undefined
      return { regs, disposer }
    }
    const NO_SVC = { fs: undefined, shell: undefined, sessions: undefined }

    // ① ev-panel：fs 缺失时照样注册（它不用 fs），退化逐调用发生在 session/shell 侧
    {
      const evSrc = loadHost('dsh-plugins/ev-panel/panel-host.js')
      const d = driveHost(evSrc, NO_SVC)
      expect('ev-panel：fs 缺失时仍注册两个 RPC（不再整插件早退）',
        !!d.regs['ev-board-load'] && !!d.regs['ev-health-load'], Object.keys(d.regs).join(','))
      expect('ev-panel：fs 缺失时仍注册单卡详情 RPC', !!d.regs['ev-idea-detail'])
      expect('ev-panel：返回可用的 disposer（不是 undefined）', typeof d.disposer === 'function')
      const r = await d.regs['ev-board-load']({})
      expect('ev-panel：fs 缺失时调用给出明确错误而非静默成功',
        r && r.ok === false && /无法解析工作区/.test(r.error), String(r && r.error).slice(0, 90))
      expect('ev-panel：代码里无 fs 调用（守卫本就不该存在，防被照抄回来）', !/\bfs\./.test(codeOf(evSrc)))
      expect('ev-panel：代码里无「fs 缺失就整插件 return」', !/if \(fs === undefined\) return/.test(codeOf(evSrc)))
    }

    // ② ascend-panel：fs 缺失时仍注册全部 RPC；依赖 fs 的七个给明确错误，不依赖的四个不受影响
    {
      const ascHostSrc = loadHost('dsh-plugins/ascend-panel/panel-host.js')
      const d = driveHost(ascHostSrc, NO_SVC)
      const needFsRpcs = ['ascend-traces-list', 'ascend-traces-detail', 'ascend-update-sedimented',
        'ascend-metrics-load', 'ascend-read-report', 'ascend-kb-health', 'ascend-process-health']
      const noFsRpcs = ['ascend-open-evidence', 'ascend-metrics-verdict', 'ascend-metrics-live',
        'ascend-export-trace']
      expect('ascend-panel：fs 缺失时仍注册全部 11 个 RPC',
        Object.keys(d.regs).length === 11, Object.keys(d.regs).join(','))
      expect('ascend-panel：返回可用的 disposer', typeof d.disposer === 'function')
      expect('ascend-panel：导出交接包的 RPC 已注册（fs 缺失不影响它）', !!d.regs['ascend-export-trace'])
      for (const rpc of needFsRpcs) {
        const r = await d.regs[rpc]({})
        expect('ascend-panel：' + rpc + ' 在 fs 缺失时报「需要 fs 服务」并指出指标 tab 仍可用',
          r && r.ok === false && /需要 fs 服务/.test(r.error) && /仍然可用/.test(r.error),
          String(r && r.error).slice(0, 110))
      }
      for (const rpc of noFsRpcs) {
        const r = await d.regs[rpc]({})
        expect('ascend-panel：' + rpc + ' 不因 fs 缺失被拦（走的不是 fs 分支）',
          !(r && r.ok === false && /需要 fs 服务/.test(r.error)), String(r && r.error).slice(0, 110))
      }
      const guarded = (ascHostSrc.match(/if \(!fs\) return needFs\(\)/g) || []).length
      expect('ascend-panel：恰好 7 个 handler 带 fs 守卫（放错位置即被这条抓住）', guarded === 7, 'guarded=' + guarded)
      expect('ascend-panel：代码里无「fs 缺失就整插件 return」',
        !/if \(fs === undefined\) return/.test(codeOf(ascHostSrc)))
    }
  }

  // ================= 面板结果复用窗口 · 窗口内复用 / refresh 绕过 / 失败也能强制重跑 =================
  //
  // 为什么单开一节：两个面板的取数都要起 Python 子进程（体检 0.68s、看板 0.36s、演进体检 0.32s），
  // 而"切走 tab 再切回"会重新挂载组件、重新发起同一条 RPC。加缓存的收益是切回不再等，
  // 代价是"面板显示的可能不是此刻的现实"——所以三件事必须一起钉住，缺一条都会退化成
  // 假绿或另一种坑：①窗口内复用（不重跑脚本，收益成立）；②refresh 显式绕过（读者有出口）；
  // ③**失败结果同样可强制重跑**（把体检不可用缓存住却不给重试，读者就只能干等窗口过期）。
  // 手法：用真实 host 源文件 + 桩 shell 跑（不复制缓存逻辑），只数目标脚本起了几次进程。
  console.log('\n[面板结果复用窗口 · 复用 / refresh 绕过 / 失败可重试]')
  {
    const mkFs = () => ({
      resolve: async (p, opts) => path.resolve((opts && opts.cwd) || repo, p),
      readText: async (t) => fs.readFileSync(t, 'utf8'),
      listDir: async (t) => fs.readdirSync(t, { withFileTypes: true }).map(e => ({
        name: e.name, type: e.isDirectory() ? 'directory' : 'file', target: path.join(t, e.name),
      })),
      processPath: (t) => t,
    })
    const mkSessions = (cwd) => ({ get: () => ({ header: { cwd: cwd } }), list: () => [{ header: { cwd: cwd } }] })
    // 脚本桩：只回答"解释器探测"与四个真脚本；`fail` 控制脚本侧退出码与 stderr
    const mkShell = (counter, fail) => ({
      resolve: (x) => x,
      run: async (spec) => {
        const cmd = String(spec && spec.command || '')
        if (/--version/.test(cmd)) {
          return { exitCode: 0, stdout: { text: 'Python 3.11.0' }, stderr: { text: '' } }
        }
        for (const key of Object.keys(counter)) {
          if (cmd.includes(key)) {
            counter[key]++
            if (fail) return { exitCode: 1, timedOut: false, stdout: { text: '' }, stderr: { text: 'stub: script failed' } }
            const payload = key.includes('metrics_health')
              ? { gates: {}, findings: [], capacity_cells: [], freshness: {}, readability: {}, coverage: {} }
              : { check_verdict: 'clean', findings: [], errors: [] }
            return { exitCode: 0, timedOut: false, stdout: { text: JSON.stringify(payload) }, stderr: { text: '' } }
          }
        }
        return { exitCode: 1, timedOut: false, stdout: { text: '' }, stderr: { text: 'stub: unexpected command ' + cmd } }
      },
    })
    const bootPanel = (rel, cwd, counter, fail) => {
      // 与上一节同一套 driveHost/loadHost 手法：真 apply()、桩服务
      const loadHost = (p) => fs.readFileSync(path.join(repo, p), 'utf8')
      const regs = {}
      const ctx = { get: (n) => n === 'fs' ? mkFs() : n === 'shell' ? mkShell(counter, fail) : n === 'sessions' ? mkSessions(cwd) : undefined }
      const harness = {
        handle: (name, fn) => { regs[name] = fn; return () => {} },
        defineTool: (opts) => opts,
        registerTool: () => () => {},
      }
      const plugin = new Function('harness', 'console', loadHost(rel))(harness, { error: () => {}, log: () => {} })
      plugin.apply(ctx)
      return regs
    }
    const CWD = repo

    {
      const counter = { 'metrics_health.py': 0 }
      const regs = bootPanel('dsh-plugins/ascend-panel/panel-host.js', CWD, counter, false)
      const call = (args) => regs['ascend-metrics-verdict'](args)
      const r1 = await call({})
      expect('ascend-panel 判决 · 首次调用真的跑脚本', counter['metrics_health.py'] === 1 && r1 && r1.ok === true,
        'spawns=' + counter['metrics_health.py'] + ' ok=' + (r1 && r1.ok))
      await call({})
      expect('ascend-panel 判决 · 窗口内再调不重跑脚本（切走再切回不再等 Python）',
        counter['metrics_health.py'] === 1, 'spawns=' + counter['metrics_health.py'])
      await call({ refresh: true })
      expect('ascend-panel 判决 · refresh:true 绕过窗口强制重跑（读者有出口）',
        counter['metrics_health.py'] === 2, 'spawns=' + counter['metrics_health.py'])
      await call({})
      expect('ascend-panel 判决 · 强制重跑后的结果重新进入窗口（不每次都跑）',
        counter['metrics_health.py'] === 2, 'spawns=' + counter['metrics_health.py'])
    }

    {
      // 失败结果：按窗口返回，且 refresh 能立刻重试（不是"坏了就锁死 30 秒"）
      const counter = { 'metrics_health.py': 0 }
      const regs = bootPanel('dsh-plugins/ascend-panel/panel-host.js', CWD, counter, true)
      const call = (args) => regs['ascend-metrics-verdict'](args)
      const r1 = await call({})
      expect('ascend-panel 判决 · 体检失败时如实返回失败（不伪装成通过）', r1 && r1.ok === false, JSON.stringify(r1).slice(0, 90))
      await call({})
      expect('ascend-panel 判决 · 失败结果同样按窗口复用（不反复起注定失败的进程）',
        counter['metrics_health.py'] === 1, 'spawns=' + counter['metrics_health.py'])
      await call({ refresh: true })
      expect('ascend-panel 判决 · 失败也能 refresh 立刻重试（不被窗口锁死）',
        counter['metrics_health.py'] === 2, 'spawns=' + counter['metrics_health.py'])
    }

    {
      const counter = { 'ev_board_data.py': 0, 'evolution_health.py': 0 }
      const regs = bootPanel('dsh-plugins/ev-panel/panel-host.js', CWD, counter, false)
      const board = (args) => regs['ev-board-load'](args)
      const health = (args) => regs['ev-health-load'](args)
      await board({ sessionId: 'sess-1' })
      await health({ sessionId: 'sess-1' })
      expect('ev-panel · 两个 RPC 各跑各自的脚本（缓存不串台）',
        counter['ev_board_data.py'] === 1 && counter['evolution_health.py'] === 1,
        JSON.stringify(counter))
      await board({ sessionId: 'sess-1' })
      await health({ sessionId: 'sess-1' })
      expect('ev-panel · 窗口内再调不重跑（切走再切回不再等 Python）',
        counter['ev_board_data.py'] === 1 && counter['evolution_health.py'] === 1, JSON.stringify(counter))
      await board({ sessionId: 'sess-1', refresh: true })
      await health({ sessionId: 'sess-1', refresh: true })
      expect('ev-panel · refresh:true 两条都绕过窗口强制重跑',
        counter['ev_board_data.py'] === 2 && counter['evolution_health.py'] === 2, JSON.stringify(counter))
    }

    // 客户端侧：刷新入口必须真的带上 refresh:true（不然按钮点了还是吃缓存，等于没出口）
    // 注意：直接调 comp() 前必须把 hookIdx 归零——renderAsync 每轮都归零，不归零就会读到别的
    // useState 槽位，组件停在 loading 分支、按钮"不存在"（踩过一次，症状像"按钮没渲染"）。
    const treeOf = (reg) => { hookIdx = 0; effectQueue = []; return reg.comp({ sessionId: 'sess-1' }) }
    {
      const seen = []
      const hostImpl = (m, a) => {
        seen.push({ m: m, a: a })
        if (m === 'ev-board-load') return { ok: true, data: board }
        if (m === 'ev-health-load') return { ok: true, data: { check_verdict: 'clean', findings: [] } }
        return { ok: false, error: 'n/a' }
      }
      const rendered = await renderAsync(evSrc, { sessionId: 'sess-1' }, hostImpl)
      const hs = []
      collectHandlers(treeOf(rendered.regs[0]), hs)
      const btn = hs.find(h => String(h.text).includes('刷新'))
      expect('ev-panel 客户端 · 找到「刷新」按钮（找不到=渲染停在加载态）', !!btn,
        rendered.text.slice(0, 100))
      // 首次挂载那次必须**不带** refresh（否则切 tab 就每次都起 Python，缓存白加）
      const first = seen.find(s => s.m === 'ev-board-load')
      expect('ev-panel 客户端 · 首屏那次不强制刷新（窗口复用才有意义）',
        !!first && !(first.a && first.a.refresh === true), JSON.stringify(first && first.a))
      let clicked = 0
      if (btn) { btn.fn({}); clicked = 1 }
      await new Promise(r => setImmediate(r))
      const forced = seen.filter(s => s.m === 'ev-board-load' && s.a && s.a.refresh === true)
      expect('ev-panel 客户端 · 点「刷新」带 refresh:true（按钮真的绕过窗口）',
        clicked === 1 && forced.length === 1, 'clicked=' + clicked + ' forced=' + forced.length)
    }

    {
      const seen = []
      const hostImpl = (m, a) => {
        seen.push({ m: m, a: a })
        return hostWithVerdict(m, a)
      }
      const rendered = await renderAsync(ascSrc, { sessionId: 'sess-1' }, hostImpl)
      expect('ascend-panel 客户端 · 状态条出现「重新体检」入口', /重新体检/.test(rendered.text))
      expect('ascend-panel 客户端 · 入口说明复用窗口（不把复用说成实时）',
        /30 秒内复用/.test(rendered.text), rendered.text.match(/«title:[^»]*»/g) ? '' : rendered.text.slice(0, 120))
      const metricsReg = rendered.regs.find(r => r.opts && r.opts.id === 'ascend-metrics')
      const hs = []
      if (metricsReg) collectHandlers(treeOf(metricsReg), hs)
      const btn = hs.find(h => String(h.text).includes('重新体检'))
      const first = seen.find(s => s.m === 'ascend-metrics-verdict')
      expect('ascend-panel 客户端 · 首屏那次不强制刷新',
        !!first && !(first.a && first.a.refresh === true), JSON.stringify(first && first.a))
      let clicked = 0
      if (btn) { btn.fn({}); clicked = 1 }
      await new Promise(r => setImmediate(r))
      const forced = seen.filter(s => s.m === 'ascend-metrics-verdict' && s.a && s.a.refresh === true)
      expect('ascend-panel 客户端 · 点「重新体检」带 refresh:true',
        clicked === 1 && forced.length === 1, 'clicked=' + clicked + ' forced=' + forced.length)
    }

    // 窗口数值只在 host（机器落点），client 的说明照它写。
    // 这条断言的作用是：只改 host、忘了改面向读者的说明时变成红——否则文案会安静地说错窗口，
    // 读者按错的窗口推断"这结论有多新"（原则十：复用不能读成实时）。
    {
      const ttlOf = (rel, re) => {
        const m = re.exec(fs.readFileSync(path.join(repo, rel), 'utf8'))
        return m ? Number(m[1]) : NaN
      }
      const ascTtl = ttlOf('dsh-plugins/ascend-panel/panel-host.js', /VERDICT_TTL_MS = (\d+)/)
      const evTtl = ttlOf('dsh-plugins/ev-panel/panel-host.js', /CACHE_TTL_MS = (\d+)/)
      expect('两个面板的复用窗口都从 host 源文件读得到（不散在面向读者的文案里）',
        Number.isFinite(ascTtl) && Number.isFinite(evTtl), 'asc=' + ascTtl + ' ev=' + evTtl)
      expect('两个面板的复用窗口同值（跨面板契约）', ascTtl === evTtl, 'asc=' + ascTtl + ' ev=' + evTtl)
      const secs = String(ascTtl / 1000)
      for (const [rel, name] of [['dsh-plugins/ascend-panel/panel-client.js', 'ascend-panel'],
        ['dsh-plugins/ev-panel/panel-client.js', 'ev-panel']]) {
        const t = fs.readFileSync(path.join(repo, rel), 'utf8')
        expect(name + ' client 的刷新说明与 host 窗口同值（' + secs + ' 秒内复用）',
          t.includes(secs + ' 秒内复用'), 'host=' + secs + ' 秒')
      }
    }
  }

  console.log('\n' + (failures.length ? '失败 ' + failures.length + ' 项: ' + failures.join(' | ') : '全部通过'))
  process.exit(failures.length ? 1 : 0)
}

main().catch(e => { console.error('harness 崩溃:', e); process.exit(2) })
