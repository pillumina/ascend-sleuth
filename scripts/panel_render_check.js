// 离线渲染校验：用 mock React + 真实数据跑面板客户端，确认
//  1) 渲染不抛异常
//  2) 关键信息（决策链全文、变化对照、缺口提示）确实出现在输出里
// 不是替代浏览器验证，是把"渲染逻辑 + 数据契约"这一层先钉死。
const fs = require('fs')
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
  expect('① 要处理的：报出预测实测记录 ' + nMv + ' 笔', new RegExp('预测实测记录[\\s\\S]{0,12}?' + nMv + '\\s*笔').test(ev.text), ev.text.slice(0, 200))
  if (nMv === 0) {
    expect('实测 0 笔时明说"一次都没被复现过"（不静默）', /一次都没有被复现过/.test(ev.text))
  } else {
    const MV_LABEL = { PASS: '符合', FAIL: '被证伪', ERROR: '判不了' }
    const expectParts = Object.keys(mv).filter(k => MV_LABEL[k]).map(k => MV_LABEL[k] + ' ' + mv[k])
    expect('实测分布按三态渲染（' + expectParts.join(' · ') + '）',
      expectParts.every(t => ev.text.includes(t)), expectParts.join('/'))
    expect('点明"被证伪"是拒绝域存在的唯一证据', /拒绝域存在的唯一证据/.test(ev.text))
  }

  // ---- ② 触及面（这批补在哪一层）：确定性派生的读数 ----
  expect('② 这批补在哪一层：区块存在', ev.text.includes('② 这批补在哪一层'))
  const surfaces = Object.keys(board.stats.by_surface || {})
  expect('② 触及面：全部 ' + surfaces.length + ' 个轴都已渲染',
    surfaces.every(s => ev.text.includes(s)), surfaces.join('、'))
  expect('② 触及面：标注"改动落在哪一层"而非"变好了多少"',
    /改动落在机器的哪一层/.test(ev.text) && /变好了多少/.test(ev.text))
  // 诚实退化：能力轴不可解读时必须明说，不得画趋势线称"稳定"
  expect('② 触及面：能力轴标注不可解读（不是"稳定"）', /不可解读/.test(ev.text) && !/能力轴[^。]{0,20}稳定/.test(ev.text))
  expect('② 触及面：标注归因依据强度（弱归因不当作改动落点）', /归因依据强度/.test(ev.text))
  // 两条**已在本仓库另一面板踩过**的文案缺陷，这里一并钉住（同类缺陷复发 ≥2 次才进 CI 的口径）：
  // ① Markdown 星号当强调写进渲染文本 → 面板原样显示字面量（诊断面板已修过一次）；
  // ② 内部标识符（metric/dimension id）泄漏到人读文案里。
  // ①的范围要收紧到**面板自己的文案**（新增区块的源码），不查整页渲染文本：整页里带历史数据原文
  // （实测 exec-log 的 decision_reason 里就有 `**有**`），用渲染文本判会把数据误判成文案缺陷——
  // 与上面 v1 状态词"查声明不查整页"是同一条教训。
  const newCopyBlocks = evSrc.slice(evSrc.indexOf('function measureLine'),
    evSrc.indexOf('// ============ 主视图 ============'))
  expect('判决/触及面文案不含字面 Markdown 星号（数据里的星号不算）', !/\*\*/.test(newCopyBlocks),
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
  expect('④ 卡片抽屉：收起态标出这是 diff 日志', /④ 卡片（diff 日志）/.test(ev.text))
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
    expect('采纳率 100% 旁点明"是症状不是成绩"', /不是成绩/.test(ev.text), ev.text.slice(0, 200))
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
  expect('timeline sparkline', /routed_accuracy/.test(ev.text))
  expect('空区块不占位（tally 空 → 一行说明）', /暂无归因事件/.test(ev.text))
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
    expect('退化分支给出补救指引', /内容流程收尾应先落一条 exec-log/.test(ev.text))
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
    expect('判决拿不到时其余区块照常渲染（一次失败不牵连另一块）', /② 这批补在哪一层/.test(noHealth.text))
    expect('判决拿不到时不静默（卡区/触及面仍在，读者仍能判读）', /④ 卡片（diff 日志）/.test(noHealth.text))
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
    expect('体检器失效：报出"结论不可用"与未评估条数',
      /结论不可用/.test(br.text) && /判据\s*0\/7\s*条已评估/.test(br.text), br.text.slice(0, 160))
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
    const drawerToggle = handlers.find(h => String(h.text).includes('④ 卡片（diff 日志）'))
    expect('抽屉可点开（④ 卡片（diff 日志））', !!drawerToggle)
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
    // 收起态摘要取该期前 3 项指标（replay 期含「路由准确率」，live 期含「诊断 session 数」）
    expect('期卡收起态带指标摘要', /路由准确率 \d+\/\d+/.test(mtAll) || /诊断 session 数 \d+/.test(mtAll),
      (mtAll.match(/路由准确率[^\n]{0,20}/) || [])[0])
    expect('收起态标注项数（N 项）', /\d+ 项/.test(mtAll))
  }
  expect('知识库健康保留', mt.includes('知识库健康'))
  expect('流程闭环保留', mt.includes('流程闭环'))
  expect('实时计算保留', mt.includes('实时计算'))
  expect('默认收起期卡数量少于总期数（避免平铺）', (mt.match(/项$/gm) || []).length <= periods.length)

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
  const idxText = fs.readFileSync(path.join(repo, 'knowledge/_index.yaml'), 'utf8')
  // 不能带 '#' 前缀锚：真实头注是「生成日期：2026-09-10    case 总数：158」——'#' 与 'case'
  // 之间隔着日期，带 '#' 的正则永远匹配不到（实测：这条断言曾算出 NaN）
  const declared = Number((/case 总数：\s*(\d+)/.exec(idxText) || [])[1])
  const diskCount = JSON.parse(pyRun(['-c', `
import json, pathlib
n = 0
for p in pathlib.Path('knowledge').rglob('*.yaml'):
    if p.name.startswith('_'): continue
    if '_index' in p.parts: continue
    n += 1
print(json.dumps(n))
`], { cwd: repo, env: PY_ENV }).toString())
  expect('索引头注声明条数可解析（' + declared + '）', Number.isFinite(declared) && declared > 0)
  expect('磁盘 case 文件数可扫描（' + diskCount + '）', diskCount > 0)

  // —— 渲染：判决条 / 不可解读 / 容量台账 ——
  const healthCases = {
    total: declared, lowConfidence: 12, byCategory: { interrupt: 30, performance: 10, precision: 12 },
    byCell: cells.slice(0, 4), indexGeneratedAt: '2026-09-10', declaredTotal: declared, diskTotal: diskCount,
  }
  const hostWithVerdict = (method, args) => {
    if (method === 'ascend-metrics-verdict') return { ok: true, verdict: Object.assign({}, verdict, {
      drift: { declared: declared, disk: diskCount, generatedAt: '2026-09-10' },
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
    // 沉淀候选**展开即列出明细**（只给一个数字读者无从判断"为啥是 3 条"）
    {
      expect('detail 数据把沉淀候选带回客户端', /sedimentCandidates: r && r\.sedimentCandidates/.test(ascSrc))
      expect('面板列出候选明细（kind + 摘要 + 建议 skill）',
        /cands\.map\(\(c, i\)/.test(ascSrc) && /c\.suggestedSkill/.test(ascSrc) && /沉淀候选（/.test(ascSrc))
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
  }

  // —— 指令区形态（2026-09-12 改版）：按钮横排 + 卡片内不复读提示 ——
  {
    expect('指令区：按钮为横向 flex 换行（竖排会撑高卡片）', /display: 'flex', flexWrap: 'wrap', gap: 8/.test(ascSrc))
    expect('指令区：卡片内不再逐卡复读提示文案', !/['"]这一单结束了/.test(ascSrc) && !/['"]这单已闭环\.要更正/.test(ascSrc))
    expect('指令区：展开的命令块只有一处（点谁显示谁）', (ascSrc.match(/openedCmd \? React\.createElement/g) || []).length === 1)
  }

  // —— 人读定位报告与沉淀候选的入口（diagnose 步骤 6 产出）——
  {
    const hostSrc = fs.readFileSync(path.join(repo, 'dsh-plugins/ascend-panel/panel-host.js'), 'utf8')
    expect('host 从 trace 读 report_file 与 sediment_candidates',
      /reportFile: doc\.report_file/.test(hostSrc) && /sedimentCandidates: Array\.isArray\(doc\.sediment_candidates\)/.test(hostSrc))
    expect('client 给「打开报告」入口（复用证据打开通路，不新造 RPC）',
      /'traces\/' \+ s\.reportFile/.test(ascSrc) && /打开报告/.test(ascSrc))
    expect('client 显示待沉淀条数', /待沉淀 ' \+ s\.sedimentCandidates/.test(ascSrc))
    expect('面板不写入报告内容（只读入口）', !/ascend-write-report/.test(ascSrc) && !/ascend-write-report/.test(hostSrc))
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
    expect('client 打开成功有反馈（已打开）', /'已打开'/.test(ascSrc))
    expect('client 打开失败显原因', /打开失败（无返回）/.test(ascSrc))
  }

  console.log('\n' + (failures.length ? '失败 ' + failures.length + ' 项: ' + failures.join(' | ') : '全部通过'))
  process.exit(failures.length ? 1 : 0)
}

main().catch(e => { console.error('harness 崩溃:', e); process.exit(2) })
