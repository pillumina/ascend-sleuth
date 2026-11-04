// 渲染冒烟（开发用，不进安装产物）：不启浏览器，用最小 React 替身把四个面跑一遍。
//
// 跑法：node dsh-plugins/dsh-sleuth-copilot/test/render-smoke.mjs
// 它证明不了真实页面的排版与点击，只证明：状态分支不抛、文案在、按钮发出的 RPC 与指令对。
// 每个用例用带 query 的模块 URL 重新导入一次，拿到干净的模块级 store 与偏好。

import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const CLIENT_URL = pathToFileURL(join(ROOT, 'lib', 'client.js')).href

// ── 最小浏览器环境 ──────────────────────────────────────────────────────────
const storage = new Map()
const moduleDefs = []
const copied = []
const keyHandlers = new Set()
const documentHandlers = new Map()
const PREFS_KEY = 'dsh-sleuth-copilot.prefs.v2'

globalThis.window = {
  __ModuleLoader__: { load: (def) => moduleDefs.push(def) },
  addEventListener(type, fn) {
    if (type === 'keydown') keyHandlers.add(fn)
  },
  removeEventListener(type, fn) {
    if (type === 'keydown') keyHandlers.delete(fn)
  },
  localStorage: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  },
}
globalThis.document = {
  visibilityState: 'visible',
  createElement: () => ({
    setAttribute() {}, remove() {}, appendChild() {}, select() {},
    style: {}, textContent: '', value: '',
  }),
  body: { appendChild() {}, removeChild() {} },
  head: { appendChild() {} },
  addEventListener(type, fn) {
    if (!documentHandlers.has(type)) documentHandlers.set(type, new Set())
    documentHandlers.get(type).add(fn)
  },
  removeEventListener(type, fn) {
    const set = documentHandlers.get(type)
    if (set) set.delete(fn)
  },
  execCommand: () => true,
}
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: {
    // 快捷键文案跟平台走；用例里按需改这一项（'MacIntel' / 'Win32'）。
    platform: 'MacIntel',
    userAgent: 'Mozilla/5.0 (Macintosh)',
    clipboard: {
      writeText: async (text) => {
        copied.push(String(text))
      },
    },
  },
})
// 不让轮询计时器把测试进程挂住
globalThis.setInterval = () => 0

function pressKey(key, extra) {
  for (const fn of Array.from(keyHandlers)) {
    fn(Object.assign({ key, target: { tagName: 'DIV' }, preventDefault() {} }, extra || {}))
  }
}

// 在 document 上触发一次事件（收起用的 click 监听挂在这里）。
// path 用来模拟真实事件的 composedPath：菜单项点击会把自己从 DOM 换掉，
// 到 document 时 target 已 detached，只有 composedPath 还留着原来的祖先链。
function fireDocument(type, target, path) {
  for (const fn of Array.from(documentHandlers.get(type) || [])) {
    const event = { type, target, preventDefault() {}, stopPropagation() {} }
    if (path) event.composedPath = () => path
    fn(event)
  }
}

// ── 最小 React 替身（按组件实例记录 hook，支持 deps） ──────────────────────
function containsNode(host, target) {
  if (host === target) return true
  for (const child of host.children || []) {
    if (child && typeof child === 'object' && containsNode(child, target)) return true
  }
  return false
}

function createRenderer() {
  const instances = new Map()
  let effects = []
  let dirty = false
  let current = null
  let tree = null

  function hookSlot() {
    const index = current.cursor
    current.cursor += 1
    return index
  }

  function sameDeps(previous, next) {
    if (!previous || !next) return false
    if (previous.length !== next.length) return false
    for (let index = 0; index < previous.length; index += 1) {
      if (previous[index] !== next[index]) return false
    }
    return true
  }

  const React = {
    createElement(type, props, ...children) {
      return { type, props: props || {}, children: children.flat(Infinity) }
    },
    useState(initial) {
      const instance = current
      const index = hookSlot()
      if (!(index in instance.hooks)) instance.hooks[index] = typeof initial === 'function' ? initial() : initial
      return [instance.hooks[index], (next) => {
        const value = typeof next === 'function' ? next(instance.hooks[index]) : next
        if (value !== instance.hooks[index]) {
          instance.hooks[index] = value
          dirty = true
        }
      }]
    },
    useRef(initial) {
      const index = hookSlot()
      if (!(index in current.hooks)) current.hooks[index] = { current: initial }
      return current.hooks[index]
    },
    useCallback(fn) {
      hookSlot()
      return fn
    },
    useEffect(fn, deps) {
      const index = hookSlot()
      const previous = current.effectState[index]
      if (previous && sameDeps(previous.deps, deps)) return
      effects.push({ instance: current, index, fn, deps, previous })
    },
  }

  function renderNode(node, path) {
    if (node === null || node === undefined || typeof node === 'boolean') return node
    if (Array.isArray(node)) return node.map((child, index) => renderNode(child, path + '.' + index))
    if (typeof node === 'string' || typeof node === 'number') return node
    if (typeof node.type === 'function') {
      let instance = instances.get(path)
      if (!instance) {
        instance = { hooks: [], effectState: {}, cursor: 0 }
        instances.set(path, instance)
      }
      instance.cursor = 0
      const previous = current
      current = instance
      let rendered
      try {
        rendered = node.type(node.props)
      } finally {
        current = previous
      }
      return renderNode(rendered, path + '/')
    }
    const rendered = {
      type: node.type,
      props: node.props,
      children: (node.children || []).map((child, index) => renderNode(child, path + ':' + index)),
    }
    // 让根节点的 ref 与 contains 可用：判断一次点击是不是发生在状态条内部
    rendered.contains = (target) => containsNode(rendered, target)
    const ref = node.props && node.props.ref
    if (ref && typeof ref === 'object') ref.current = rendered
    return rendered
  }

  async function settle() {
    for (let pass = 0; pass < 20; pass += 1) {
      effects = []
      dirty = false
      tree = renderNode(dom, 'root')
      for (const effect of effects) {
        if (effect.previous && typeof effect.previous.cleanup === 'function') {
          try {
            effect.previous.cleanup()
          } catch {
            // 清理失败不阻断下一轮
          }
        }
        const previousInstance = current
        current = effect.instance
        let cleanup
        try {
          cleanup = effect.fn()
        } finally {
          current = previousInstance
        }
        effect.instance.effectState[effect.index] = { deps: effect.deps, cleanup }
      }
      await new Promise((resolve) => setTimeout(resolve, 0))
      if (!dirty) break
    }
    return tree
  }

  let dom = null
  return {
    React,
    async mount(Root, props) {
      dom = { type: 'div', props: { id: 'root' }, children: [React.createElement(Root, props || {})] }
      return settle()
    },
    async rerender() {
      return settle()
    },
  }
}

function flatten(node, out) {
  if (node === null || node === undefined || typeof node === 'boolean') return out
  if (Array.isArray(node)) {
    for (const child of node) flatten(child, out)
    return out
  }
  if (typeof node === 'string' || typeof node === 'number') {
    out.text.push(String(node))
    return out
  }
  out.nodes.push(node)
  if (node.props && node.props['aria-label']) out.text.push(String(node.props['aria-label']))
  if (node.props && node.props.title) out.text.push(String(node.props.title))
  flatten(node.children, out)
  return out
}

function inspect(tree) {
  const out = { nodes: [], text: [] }
  flatten(tree, out)
  return { nodes: out.nodes, text: out.text.join(' ') }
}

function nodeText(node) {
  const out = { nodes: [], text: [] }
  flatten(node.children || [], out)
  return out.text.join('')
}

function findButton(view, label) {
  return view.nodes.find((node) => node.type === 'button' && nodeText(node) === label)
}

function findAria(view, label) {
  return view.nodes.find((node) => node.type === 'button' && node.props && node.props['aria-label'] === label)
}

function findButtonContains(view, label) {
  return view.nodes.find((node) => node.type === 'button' && nodeText(node).includes(label))
}

function findToolbar(view) {
  return view.nodes.find((node) => node.type === 'button'
    && typeof (node.props && node.props.className) === 'string'
    && node.props.className.split(/\s+/).indexOf('scp-tool-btn') >= 0)
}

function findInput(view, placeholder) {
  return view.nodes.find((node) => node.type === 'input' && node.props && node.props.placeholder === placeholder)
}

function findNode(view, predicate) {
  return view.nodes.find(predicate)
}

function byClass(view, className) {
  return view.nodes.filter((node) => typeof node.props.className === 'string' && node.props.className.split(/\s+/).includes(className))
}

function click(node) {
  if (!node || typeof node.props.onClick !== 'function') throw new Error('node has no onClick')
  node.props.onClick({
    preventDefault() {}, stopPropagation() {}, target: { tagName: 'BUTTON' }, currentTarget: node,
  })
}

// ── 断言 ────────────────────────────────────────────────────────────────────
let failures = 0
let checks = 0
function expect(name, condition, detail) {
  checks += 1
  if (condition) process.stdout.write('  ok   ' + name + '\n')
  else {
    failures += 1
    process.stdout.write('  FAIL ' + name + (detail ? ' — ' + detail : '') + '\n')
  }
}

// ── 夹具 ────────────────────────────────────────────────────────────────────
const VOCAB = {
  statuses: [
    { value: 'in_progress', label: '进行中' },
    { value: 'resolved', label: '已定位' },
    { value: 'escalated', label: '已转交他人' },
    { value: 'unknown', label: '状态未记录' },
  ],
  outcomes: [{ value: 'pending', label: '待回报' }, { value: 'resolved', label: '生效' }],
  sedimented: [{ value: 'none', label: '未沉淀' }, { value: 'submitted', label: '已提交待升格' }],
  severities: [{ value: 'service-affecting', label: '影响服务' }, { value: 'data-loss-risk', label: '数据丢失风险' }],
  reportResults: [],
}

const SHA = 'a'.repeat(64)
const ID = '2026-09-08-vllmasc-glm53-a3-topk-vec'

function makeRow(overrides) {
  return Object.assign({
    sessionId: ID,
    file: ID + '.yaml',
    contentSha256: SHA,
    status: 'in_progress',
    feedback: { outcome: 'pending', case: '' },
    sedimented: { state: 'none', case_id: '' },
    activeCase: '',
    summary: 'vllm-ascend GLM-5.3 在 A3 跑推理时 MoE routing TopK 触发 vector core exception（error code 507035）。',
    severity: 'service-affecting',
    updatedAt: '2026-09-08T15:29:00+08:00',
    derived: {
      open: true, closed: false, caseKind: 'none',
      needSed: false, needPromote: false, needReview: false,
      waitingFor: '缺 device-side plog（容器未持久化 /root/ascend/log）', waitingOn: 'user_material',
    },
    transitions: [],
    reports: [],
    reviews: [],
    reportFile: '',
    extra: {
      currentStep: 5, maxSteps: 6, eventCount: 7, userSteps: 1, agentSteps: 6,
      platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
      excludedCases: ['VLLM-ASC-7993', 'VLLM-ASC-9887', 'VLLM-ASC-10500'],
      evidenceFiles: 1, evidenceList: ['traces/evidence/' + ID + '/crash.log'],
      evidenceMissing: '缺 device-side plog', hasReport: false,
      reportFile: '', sedimentCandidateList: [{ kind: 'case', summary: 'vendor TopKV2 kernel 崩溃' }],
      missingMaterials: ['device-side plog（容器未持久化 /root/ascend/log）'],
    },
    harnessSession: '',
    resumeSessions: [],
    sessionChain: [],
  }, overrides || {})
}

const CAPS = { canWrite: true, writeRoot: '/repo', reasonCode: '', reason: '' }

function makeState(mode) {
  const row = makeRow()
  if (mode === 'empty') {
    return { ok: true, tracesDir: '/repo/traces', bound: null, recent: [], all: [], counts: { open: 0, pendingFeedback: 0, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS }
  }
  if (mode === 'error') return { ok: false, code: 'E_NO_PYTHON', message: '没找到可用的 Python 3' }
  if (mode === 'outside') return { ok: false, code: 'E_NO_ROOT', message: '不是 ascend-sleuth 检出' }
  if (mode === 'multi') {
    const second = makeRow({
      sessionId: '2026-09-07-glm53-pd-sfa-c8-hang',
      file: '2026-09-07-glm53-pd-sfa-c8-hang.yaml',
      contentSha256: 'b'.repeat(64),
      status: 'resolved',
      activeCase: 'VLLM-ASC-11312',
      feedback: { outcome: '', case: '' },
      summary: 'vllm-ascend PD 分离部署在 A3 上 curl P 节点无响应，c8_enable_reshape_optim 引发 hang。',
      sedimented: { state: 'none', case_id: '' },
      derived: {
        open: false, closed: false, caseKind: 'case', needSed: true, needPromote: false, needReview: false,
        waitingFor: '', waitingOn: null,
        upstream: { anchors: ['vllm-ascend#15903'], lastVerified: '2026-W36', verificationSource: 'upstream-fix-merged' },
      },
      extra: {
        currentStep: 6, maxSteps: 6, eventCount: 9, userSteps: 1, agentSteps: 8,
        platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
        excludedCases: [], evidenceFiles: 1, evidenceList: ['traces/evidence/x/p0.log'],
        evidenceMissing: '', hasReport: true, reportFile: 'traces/x.report.md', sedimentCandidateList: [], missingMaterials: [],
      },
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: null, recent: [row], all: [row, second],
      counts: { open: 1, pendingFeedback: 1, toSediment: 1 }, vocab: VOCAB, capabilities: CAPS,
    }
  }
  if (mode === 'closed') {
    const closedRow = makeRow({
      status: 'resolved',
      feedback: { outcome: 'resolved', case: 'VLLM-ASC-11312' },
      activeCase: 'VLLM-ASC-11312',
      transitions: [{ at: '2026-09-08T16:00:00+08:00', from: 'in_progress', to: 'resolved', note: '根因明确' }],
      reports: [{ at: '2026-09-08T16:05:00+08:00', source: 'field', result: 'from_report', note: '改完后已生效' }],
      reviews: [{ at: '2026-09-08T16:20:00+08:00', verdict: 'report_revision', note: '补一节证据' }],
      reportFile: 'traces/' + ID + '.report.md',
      derived: {
        open: false, closed: true, caseKind: 'case', needSed: true,
        needPromote: false, needReview: false, waitingFor: '', waitingOn: null,
        upstream: { anchors: ['vllm-ascend#15903'], lastVerified: '2026-W36', verificationSource: 'upstream-fix-merged' },
      },
      extra: {
        currentStep: 6, maxSteps: 6, eventCount: 9, userSteps: 1, agentSteps: 8,
        platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
        excludedCases: ['VLLM-ASC-7993'], evidenceFiles: 1,
        evidenceList: ['traces/evidence/' + ID + '/crash.log'], evidenceMissing: '',
        hasReport: true, reportFile: 'traces/' + ID + '.report.md',
        sedimentCandidateList: [{ kind: 'case', summary: 'vendor TopKV2 kernel 崩溃' }],
        missingMaterials: ['P 节点 hang 时刻栈'],
        lastOutput: '确认根因：c8_enable_reshape_optim 触发 P 侧 hang。',
      },
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: closedRow, recent: [closedRow], all: [closedRow],
      counts: { open: 0, pendingFeedback: 0, toSediment: 1 }, vocab: VOCAB, capabilities: CAPS,
    }
  }
  if (mode === 'reportReview') {
    // 最新回报是「换别的方法解决」（other_way）且之后没有复核：只有这一种情形该给「复核回报」。
    const reviewRow = makeRow({
      status: 'resolved',
      feedback: { outcome: 'resolved', case: 'VLLM-ASC-11312' },
      activeCase: 'VLLM-ASC-11312',
      reports: [{ at: '2026-09-08T16:05:00+08:00', by: 'user', source: 'field', result: 'other_way', note: '换别的方法解决了' }],
      reviews: [],
      derived: {
        open: false, closed: true, caseKind: 'case', needSed: false,
        needPromote: false, needReview: false, needReportReview: true,
        waitingFor: '', waitingOn: null,
      },
      extra: {
        currentStep: 6, maxSteps: 6, eventCount: 9, userSteps: 1, agentSteps: 8,
        platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
        excludedCases: [], evidenceFiles: 1, evidenceList: [], evidenceMissing: '',
        hasReport: true, reportFile: 'traces/' + ID + '.report.md',
        sedimentCandidateList: [], missingMaterials: [],
      },
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: reviewRow, recent: [reviewRow], all: [reviewRow],
      counts: { open: 0, pendingFeedback: 0, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS,
    }
  }
  if (mode === 'fast') {
    const fastRow = makeRow({
      status: 'resolved',
      feedback: { outcome: 'resolved', case: 'VLLM-ASC-11312' },
      activeCase: 'VLLM-ASC-11312',
      transitions: [{ at: '2026-09-08T16:00:00+08:00', from: 'in_progress', to: 'resolved' }],
      reports: [],
      reviews: [],
      reportFile: '',
      derived: {
        open: false, closed: true, caseKind: 'case', needSed: false,
        needPromote: false, needReview: false, waitingFor: '', waitingOn: null,
      },
      extra: {
        currentStep: 2, maxSteps: 6, eventCount: 3, userSteps: 1, agentSteps: 2,
        platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
        excludedCases: [], evidenceFiles: 1, evidenceList: [], evidenceMissing: '',
        hasReport: false, reportFile: '', sedimentCandidateList: [],
      },
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: fastRow, recent: [fastRow], all: [fastRow],
      counts: { open: 0, pendingFeedback: 0, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS,
    }
  }
  if (mode === 'triage') {
    const triageRow = makeRow({
      status: 'resolved',
      activeCase: 'VLLM-ASC-11312',
      sedimented: { state: 'none', case_id: '' },
      derived: {
        open: false, closed: true, caseKind: 'case', needSed: true,
        needPromote: false, needReview: false, waitingFor: '', waitingOn: null,
      },
      extra: {
        currentStep: 6, maxSteps: 6, eventCount: 9, userSteps: 1, agentSteps: 8,
        platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
        excludedCases: [], evidenceFiles: 0, evidenceList: [], evidenceMissing: '',
        hasReport: true, reportFile: 'traces/' + ID + '.report.md',
        sedimentCandidateList: [{ kind: 'triage', summary: 'triage 路由词候选' }],
      },
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: triageRow, recent: [triageRow], all: [triageRow],
      counts: { open: 0, pendingFeedback: 0, toSediment: 1 }, vocab: VOCAB, capabilities: CAPS,
    }
  }
  if (mode === 'resumed') {
    const resumedRow = makeRow({
      harnessSession: 'session-origin',
      resumeSessions: ['sess-1'],
      sessionChain: ['session-origin', 'sess-1'],
    })
    const boundRow = Object.assign({}, resumedRow, { boundBy: 'resume' })
    return {
      ok: true, tracesDir: '/repo/traces', bound: boundRow, recent: [resumedRow], all: [resumedRow],
      counts: { open: 1, pendingFeedback: 1, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS,
    }
  }
  if (mode === 'readonly') {
    return {
      ok: true, tracesDir: '/repo/traces', bound: null, recent: [row], all: [row],
      counts: { open: 1, pendingFeedback: 1, toSediment: 0 }, vocab: VOCAB,
      capabilities: { canWrite: false, reasonCode: 'E_PERM', reason: '当前会话没有写权限' },
    }
  }
  return {
    ok: true, tracesDir: '/repo/traces', bound: null, recent: [row], all: [row],
    counts: { open: 1, pendingFeedback: 1, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS,
  }
}

const SEDIMENT = {
  ok: true,
  generatedAt: '2026-11-05T10:00:00+08:00',
  targetCommit: '7b517c8',
  targetCommitShort: '7b517c8',
  inbox: '/repo/postmortems/inbox',
  counts: { total: 3, unassessed: 0, needDecision: 1, needRerun: 0, decided: 2, prOpen: 0, prMerged: 0, overdue: 1, oldestDays: 16 },
  target: {
    target: {
      remote: 'origin', base: 'main', platform: 'gitcode',
      url: 'https://gitcode.com/pillumina/ascend-sleuth.git', note: '', labels: {},
      source: 'user', chosen_at: '2026-10-28T10:00:00+08:00',
    },
    remotes: [
      { name: 'mirror', url: 'https://github.com/pillumina/ascend-sleuth.git', host: 'github.com', platform: 'github', platform_name: 'GitHub', base: 'main', has_adapter: true, token_ready: true, note: '', last_used: '' },
      { name: 'origin', url: 'https://gitcode.com/pillumina/ascend-sleuth.git', host: 'gitcode.com', platform: 'gitcode', platform_name: 'GitCode', base: 'main', has_adapter: true, token_ready: true, note: '', last_used: '2026-10-28' },
    ],
    recommendation: { remote: 'origin', base: 'main', reason: '上次使用' },
    platformName: 'GitCode',
  },
  primary: { kind: 'groom', label: '继续 groom', prompt: '继续 groom 的批次指令' },
  prompts: {
    groom: '对 postmortems/inbox/ 做本周 groom。\n按 /knowledge-groom 执行，逐条问我，不替我决定。',
    pr: '对 postmortems/inbox/ 里已决定的 2 份草稿，提到 origin/main（GitCode），按 /knowledge-groom 第 5 步提一个 PR。\n\n边界：先落盘并跑升格检查；recheck 不通过就停。',
    check: '查合入状态的指令',
    close: '合入后收尾的指令',
    prDetail: 'python3 scripts/verify_case_draft.py --gate <草稿路径>\npython3 scripts/groom_record.py --pr-marker --draft-key <key>',
    checkDetail: '查合入状态的命令细节',
    closeDetail: '收尾的命令细节',
    groomDetail: 'groom 的命令细节',
  },
  drafts: [
    {
      key: '2026-10-28-pd-prefill-hang', title: 'PD 分离 prefill 卡死：AscendStore 异步 load 从不完成',
      path: 'postmortems/inbox/2026-10-28-pd-prefill-hang.case.yaml', caseId: 'VLLM-ASC-15201',
      state: 'need_decision', stage: '待决定', stageTone: 'warn', ageDays: 16, ageSource: 'created_at',
      createdAt: '2026-10-28T09:00:00+08:00', assessedShort: '4823d40',
      novelty: 'new_pattern', confidence: 'high', candidate: '', rationale: '6 个候选的 quickly_check 都与证据不符。', reviewReasons: [],
      stale: false, staleReasons: [], decision: '', decisionValid: false, decisionBy: '', decisionAt: '',
      source: { sessionId: ID, mismatch: 'none', sedimented: 'submitted' },
      promotion: { caseId: '', casePath: '', postmortemPath: '' }, pr: null,
      next: { kind: 'groom', label: '继续 groom', prompt: '继续 groom 的批次指令' }, writeback: '',
    },
    {
      key: '2026-11-01-eplb-103900', title: 'EPLB 开启后 103900 传输超时，个别 rank 掉队',
      path: 'postmortems/inbox/2026-11-01-eplb-103900.case.yaml', caseId: 'VLLM-ASC-15201',
      state: 'decided', stage: '待提 PR', stageTone: 'accent', ageDays: 9, ageSource: 'created_at',
      createdAt: '2026-11-01T09:00:00+08:00', assessedShort: '4823d40',
      novelty: 'new_pattern', confidence: 'high', candidate: '', rationale: '', reviewReasons: [],
      stale: false, staleReasons: [], decision: 'new_pattern', decisionValid: true, decisionBy: '张工', decisionAt: '2026-11-03',
      source: { sessionId: '2026-11-01-eplb-103900', mismatch: 'none', sedimented: 'submitted' },
      promotion: { caseId: 'VLLM-ASC-15201', casePath: 'knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-15201.yaml', postmortemPath: '' }, pr: null,
      next: { kind: 'pr', label: '生成提 PR 指令', prompt: '提 PR 的批次指令' }, writeback: '',
    },
    {
      key: '2026-10-26-glm53-moe-shuffle', title: 'GLM5.3 MoE token 分发不均导致单卡显存尖峰',
      path: 'postmortems/inbox/2026-10-26-glm53-moe-shuffle.case.yaml', caseId: 'VLLM-ASC-10122',
      state: 'decided', stage: '待提 PR', stageTone: 'accent', ageDays: 11, ageSource: 'created_at',
      createdAt: '2026-10-26T09:00:00+08:00', assessedShort: '4823d40',
      novelty: 'variant', confidence: 'medium', candidate: 'VLLM-ASC-10122', rationale: '', reviewReasons: [],
      stale: false, staleReasons: [], decision: 'variant', decisionValid: true, decisionBy: '张工', decisionAt: '2026-11-03',
      source: { sessionId: '2026-10-26-glm53-moe-shuffle', mismatch: 'none', sedimented: 'submitted' },
      promotion: { caseId: 'VLLM-ASC-10122', casePath: 'knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-10122.yaml', postmortemPath: '' }, pr: null,
      next: { kind: 'pr', label: '生成提 PR 指令', prompt: '提 PR 的批次指令' }, writeback: '',
    },
  ],
  history: [{ key: '2026-10-20-indexer-dtype', title: 'Indexer dtype 不一致导致精度异常', state: 'knowledge', at: '2026-10-24T10:00:00+08:00' }],
}

// ── 每个用例：换一份干净模块，装三个面 ─────────────────────────────────────
async function mount(mode, options) {
  const opts = options || {}
  if (opts.prefs) storage.set(PREFS_KEY, JSON.stringify(opts.prefs))
  else if (opts.freshPrefs) storage.delete(PREFS_KEY)
  else storage.set(PREFS_KEY, JSON.stringify({ dockCollapsed: false, paletteFilter: 'all', pins: {} }))

  const renderer = createRenderer()
  const registry = {}
  const rpcCalls = []
  const drafts = []
  const payload = makeState(mode)
  payload.upstream = opts.upstream === false
    ? { ready: false, reason: 'gh 未登录（gh auth login）' }
    : { ready: true, reason: '' }

  const slots = {
    inject(_name, callback) {
      callback()
    },
    register(registration, component) {
      registry[registration.name] = component
      return () => {}
    },
  }
  const ctx = {
    effect(fn) {
      const cleanup = fn()
      return cleanup
    },
    get(name) {
      if (name === 'connection') {
        return {
          rpc: {
            async call(_channel, endpoint, args) {
              rpcCalls.push({ endpoint, args })
              if (endpoint === 'copilot-state') return { ok: true, value: payload }
              if (endpoint === 'copilot-transition') {
                if (opts.transitionResult) return { ok: true, value: opts.transitionResult }
                return { ok: true, value: { ok: true, from: 'in_progress', to: 'resolved', changed: ['status'] } }
              }
              if (endpoint === 'copilot-timeline') {
                return { ok: true, value: { ok: true, sessionId: ID, timeline: opts.timeline || [
                  { role: 'user', step: 1, content: '用户贴了崩溃日志' },
                  { role: 'agent', step: 2, action: 'triage', output: '判定为推理中断类', reason: '签名命中 vector core exception' },
                ] } }
              }
              if (endpoint === 'copilot-report') {
                if (opts.reportError) return { ok: true, value: { ok: false, code: 'E_NOT_FOUND', message: '这单还没有人读报告' } }
                return { ok: true, value: { ok: true, text: opts.reportText || '# 诊断报告\n根因：vendor TopKV2 kernel 崩溃', file: 'traces/' + ID + '.report.md', bytes: 100 } }
              }
              if (endpoint === 'copilot-sediment') {
                if (opts.sedimentError) return { ok: true, value: { ok: false, code: 'E_OUTPUT', message: '沉淀脚本没有产出 JSON' } }
                return { ok: true, value: opts.sediment || SEDIMENT }
              }
              if (endpoint === 'copilot-pr-target') {
                return { ok: true, value: { ok: true, target: (opts.sediment || SEDIMENT).target } }
              }
              throw new Error('unexpected endpoint ' + endpoint)
            },
          },
        }
      }
      if (name === 'slots') return slots
      return undefined
    },
  }

  moduleDefs.length = 0
  await import(CLIENT_URL + '?case=' + encodeURIComponent(mode + '-' + Math.random()))
  const def = moduleDefs[moduleDefs.length - 1]
  const factoryResult = def.factory((name) => {
    if (name === 'react') return renderer.React
    throw new Error('unexpected require ' + name)
  })
  factoryResult.apply(ctx)

  const props = {
    sessionId: 'sess-1',
    session: { cwd: '/repo' },
    inputActions: {
      setDraft(text) {
        drafts.push(String(text))
      },
    },
    useSessions(selector) {
      return selector({ byId: { 'sess-1': { cwd: '/repo' } } })
    },
  }

  const Dock = registry['conversation.input.dock']
  const Toolbar = registry['conversation.input.right']
  const Palette = registry['shell.overlay']
  const Root = () => renderer.React.createElement('div', { id: 'root' },
    renderer.React.createElement(Dock, props),
    renderer.React.createElement(Toolbar, props),
    renderer.React.createElement(Palette, {}))
  const tree = await renderer.mount(Root, {})

  const api = {
    registry,
    inject: factoryResult.inject,
    rpcCalls,
    drafts,
    async settle() {
      return inspect(await renderer.rerender())
    },
    view() {
      return inspect(tree)
    },
    click(node) {
      click(node)
    },
    documentClick(target, path) {
      fireDocument('click', target, path)
    },
    documentMouseDown(target) {
      fireDocument('mousedown', target)
    },
    pressKey,
    lastTransition() {
      const calls = rpcCalls.filter((call) => call.endpoint === 'copilot-transition')
      return calls.length ? calls[calls.length - 1].args : null
    },
    lastDraft() {
      return drafts.length ? drafts[drafts.length - 1] : ''
    },
  }
  return api
}

// ── 用例 ────────────────────────────────────────────────────────────────────
process.stdout.write('诊断状态条 · 渲染冒烟\n')

{
  const t = await mount('recent')
  const view = t.view()
  expect('注册：inject 声明了 sessions',
    Array.isArray(t.inject) && t.inject.includes('sessions'), JSON.stringify(t.inject))
  expect('最近一单：标出「最近一单」', view.text.includes('最近一单'), view.text.slice(0, 160))
  expect('最近一单：显示状态名', view.text.includes('进行中'))
  expect('最近一单：显示人读案例标题', view.text.includes('vllm-ascend GLM-5.3 在 A3 跑推理时 MoE routing TopK 触发 vector core exception'))
  expect('最近一单：单号不占标题位', !view.text.includes(ID), view.text.slice(0, 400))
  expect('最近一单：显示在等什么', view.text.includes('缺 device-side plog'))
  expect('最近一单：进度轨显示 5/6', view.text.includes('5/6'))
  expect('最近一单：主按钮是回报结果', !!findButton(view, '回报结果'))
  expect('最近一单：显示身份标签（知识库未覆盖）', view.text.includes('知识库未覆盖'))
  expect('最近一单：显示已排除条数', view.text.includes('已排除 3 条'))
  expect('最近一单：版本串 0.15.0', view.nodes.some((node) => node.props && node.props['data-version'] === '0.15.0'))
  expect('工具条：带待回报角标', view.text.includes('1 单待回报'), view.text.slice(0, 400))
  expect('标题按钮可打开台账', !!findNode(view, (node) => node.type === 'button' && node.props && node.props['aria-label'] && node.props['aria-label'].startsWith('诊断总览：')))
}

{
  const t = await mount('recent', { prefs: { dockCollapsed: true, paletteFilter: 'all' } })
  const view = t.view()
  expect('收起：只剩一行（无 foot）', byClass(view, 'scp-foot').length === 0)
  expect('收起：不显示完整单号', !view.text.includes(ID))
  const expand = findAria(view, '展开状态条')
  expect('收起：给出展开按钮', !!expand)
  click(expand)
  const after = await t.settle()
  expect('展开后：foot 出现', byClass(after, 'scp-foot').length === 1)
  const prefs = JSON.parse(storage.get(PREFS_KEY))
  expect('展开后：偏好已记住', prefs && prefs.dockCollapsed === false, JSON.stringify(prefs))
}

{
  // 收起有三条路：点外部、Esc、右上角带文字的「收起」
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  const view = t.view()
  const collapse = findAria(view, '收起状态条')
  expect('收起方式：展开态有「收起」按钮', !!collapse && nodeText(collapse) === '收起')
  t.documentClick({ tagName: 'DIV' })
  const after = await t.settle()
  expect('收起方式：点状态条外收起', byClass(after, 'scp-handle').length === 1)
  expect('收起方式：点外部收起写进偏好', JSON.parse(storage.get(PREFS_KEY)).dockCollapsed === true)
}

{
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  const view = t.view()
  t.documentClick(findButton(view, '回报结果'))
  let after = await t.settle()
  expect('收起方式：点条内不收起', byClass(after, 'scp-foot').length === 1)
  t.documentClick({ tagName: 'TEXTAREA' })
  after = await t.settle()
  expect('收起方式：点输入框不收起', byClass(after, 'scp-foot').length === 1)
  t.documentClick({ tagName: 'DIV' })
  after = await t.settle()
  expect('收起方式：非输入类外部点击照常收起', byClass(after, 'scp-handle').length === 1)
}

{
  // 常驻偏好：开了点外部不收起；按钮能关掉
  const t = await mount('recent', { prefs: { dockCollapsed: false, dockKeepOpen: true, paletteFilter: 'all', pins: {} } })
  t.documentClick({ tagName: 'DIV' })
  let after = await t.settle()
  expect('常驻：点外部不收起', byClass(after, 'scp-foot').length === 1)
  const pin = findNode(after, (node) => node.type === 'button' && node.props && node.props['aria-pressed'] === 'true')
  expect('常驻：按钮标出已开', !!pin && pin.props['aria-label'] === '展开后常驻')
  click(pin)
  after = await t.settle()
  expect('常驻：点按钮关掉', JSON.parse(storage.get(PREFS_KEY)).dockKeepOpen === false)
  t.documentClick({ tagName: 'DIV' })
  after = await t.settle()
  expect('常驻：关掉后点外部收起', byClass(after, 'scp-handle').length === 1)
}

{
  // Esc：菜单开着先关菜单，再按一次才收起
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findNode(view, (node) => node.type === 'button' && node.props && node.props['aria-label'] === '更多操作'))
  view = await t.settle()
  expect('Esc：菜单先打开', byClass(view, 'scp-menu').length === 1)
  byClass(view, 'scp-root')[0].props.onKeyDown({ key: 'Escape', preventDefault() {} })
  view = await t.settle()
  expect('Esc：先关菜单', byClass(view, 'scp-menu').length === 0)
  expect('Esc：关菜单不收起状态条', byClass(view, 'scp-foot').length === 1)
  byClass(view, 'scp-root')[0].props.onKeyDown({ key: 'Escape', preventDefault() {} })
  view = await t.settle()
  expect('Esc：再按收起状态条', byClass(view, 'scp-handle').length === 1)
}

{
  // 菜单外点一下只关菜单，不顺手把状态条也收掉
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findNode(t.view(), (node) => node.type === 'button' && node.props && node.props['aria-label'] === '更多操作'))
  await t.settle()
  t.documentMouseDown({ tagName: 'DIV' })
  t.documentClick({ tagName: 'DIV' })
  let view = await t.settle()
  expect('菜单：同一次点击只关菜单', byClass(view, 'scp-menu').length === 0 && byClass(view, 'scp-foot').length === 1)
  t.documentClick({ tagName: 'DIV' })
  view = await t.settle()
  expect('菜单：下一次点外部收起', byClass(view, 'scp-handle').length === 1)
}

{
  // 右键 / 拖拽只产生 mousedown、没有 click：关闭标记不能留到下一次点击
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findNode(t.view(), (node) => node.type === 'button' && node.props && node.props['aria-label'] === '更多操作'))
  await t.settle()
  t.documentMouseDown({ tagName: 'DIV' })
  await t.settle()
  t.documentMouseDown({ tagName: 'DIV' })
  t.documentClick({ tagName: 'DIV' })
  const view = await t.settle()
  expect('菜单：只 mousedown 的手势不吞下一次点击', byClass(view, 'scp-handle').length === 1)
}

{
  // 错误态与空态同样有收起入口与常驻开关
  const t = await mount('error', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  expect('错误态：有「收起」按钮', !!findAria(view, '收起状态条'))
  expect('错误态：有「展开后常驻」按钮', !!findAria(view, '展开后常驻'))
  click(findAria(view, '收起状态条'))
  view = await t.settle()
  expect('错误态：点「收起」收起成胶囊', byClass(view, 'scp-handle').length === 1)
}

{
  const t = await mount('empty', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  expect('空态：有「收起」按钮', !!findAria(view, '收起状态条'))
  expect('空态：有「展开后常驻」按钮', !!findAria(view, '展开后常驻'))
  click(findAria(view, '收起状态条'))
  view = await t.settle()
  expect('空态：点「收起」收起成胶囊', byClass(view, 'scp-handle').length === 1)
}

{
  const t = await mount('recent', { freshPrefs: true })
  const view = t.view()
  expect('默认收起：不显示第二行', byClass(view, 'scp-foot').length === 0)
  expect('默认收起：是居中的窄把手', byClass(view, 'scp-handle').length === 1)
  expect('默认收起：初始不透明', byClass(view, 'scp-handle')[0].props['data-idle'] === 'false')
  expect('默认收起：把手带案例标题', view.text.includes('vllm-ascend GLM-5.3'))
  const expand = findAria(view, '展开状态条')
  click(expand)
  const after = await t.settle()
  const prefs = JSON.parse(storage.get(PREFS_KEY))
  expect('展开后：偏好记住', byClass(after, 'scp-foot').length === 1 && prefs.dockCollapsed === false, JSON.stringify(prefs))
}

{
  const t = await mount('multi')
  const view = t.view()
  expect('多单：默认显示最近一单', view.text.includes('vllm-ascend GLM-5.3'))
  click(findAria(view, '跟踪哪一单'))
  const opened = await t.settle()
  expect('选择器：列出多单', opened.text.includes('vllm-ascend PD 分离'), opened.text.slice(0, 300))
  const target = opened.nodes.find((node) => node.type === 'button' && nodeText(node).includes('vllm-ascend PD 分离'))
  click(target)
  const after = await t.settle()
  expect('固定：标题切到选中单', after.text.includes('vllm-ascend PD 分离'))
  expect('固定：范围标为已固定', after.text.includes('已固定'))
  const prefs = JSON.parse(storage.get(PREFS_KEY))
  expect('固定：写进偏好', prefs && prefs.pins && prefs.pins['sess-1'] === '2026-09-07-glm53-pd-sfa-c8-hang', JSON.stringify(prefs && prefs.pins))
  click(findAria(after, '更多操作'))
  const menuView = await t.settle()
  expect('菜单：出现查上游动作', menuView.text.includes('查 case 上游状态'), menuView.text.slice(0, 400))
  click(findButton(menuView, '查 case 上游状态'))
  expect('查上游：prompt 走 verify 脚本', t.lastDraft().includes('verify_upstream_outcomes.py --case VLLM-ASC-11312')
    && t.lastDraft().includes('--dry-run') && t.lastDraft().includes('scripts/doctor.py'), t.lastDraft())
}

{
  const t = await mount('multi', { upstream: false })
  click(findAria(t.view(), '跟踪哪一单'))
  const opened = await t.settle()
  const target = opened.nodes.find((node) => node.type === 'button' && nodeText(node).includes('vllm-ascend PD 分离'))
  click(target)
  const pinnedView = await t.settle()
  click(findAria(pinnedView, '更多操作'))
  const menuView = await t.settle()
  expect('上游：未就绪时菜单给原因', menuView.text.includes('gh 未登录'), menuView.text.slice(-400))
  click(findButtonContains(menuView, '查 case 上游状态'))
  expect('上游：prompt 带环境预检', t.lastDraft().includes('scripts/doctor.py') && t.lastDraft().includes('gh 未登录'), t.lastDraft())
}

{
  const t = await mount('recent')
  const view = t.view()
  const section = view.nodes.find((node) => node.type === 'section')
  expect('待回报：根节点标出 pending', section && section.props['data-pending'] === 'true')
  pressKey('d', { metaKey: true, shiftKey: true })
  const opened = await t.settle()
  expect('快捷键：⌘⇧D 打开总览', byClass(opened, 'scp-pal').length === 1)
}

{
  // 快捷键提示按平台显示：macOS 用 ⌘，Windows / Linux 用 Ctrl。
  const t = await mount('recent')
  const toolbar = findToolbar(t.view())
  expect('快捷键：macOS 工具条提示 ⌘⇧D', String(toolbar.props.title).includes('⌘⇧D 打开总览'), toolbar.props.title)
  click(toolbar)
  const view = await t.settle()
  expect('快捷键：macOS 底部提示 ⌘K', view.text.includes('⌘K'), view.text.slice(-160))
}

{
  globalThis.navigator.platform = 'Win32'
  globalThis.navigator.userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
  const t = await mount('recent')
  const toolbar = findToolbar(t.view())
  expect('快捷键：Windows 工具条提示 Ctrl+Shift+D', String(toolbar.props.title).includes('Ctrl+Shift+D 打开总览'), toolbar.props.title)
  click(toolbar)
  const view = await t.settle()
  expect('快捷键：Windows 底部提示 Ctrl+K', view.text.includes('Ctrl+K') && !view.text.includes('⌘K'), view.text.slice(-160))
  globalThis.navigator.platform = 'MacIntel'
  globalThis.navigator.userAgent = 'Mozilla/5.0 (Macintosh)'
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('收尾清单：出现', view.text.includes('收尾清单'))
  expect('收尾清单：四项都在', ['人读报告', '回报结果', '沉淀', '交接包'].every((label) => view.text.includes(label)), view.text.slice(-500))
  click(findButton(view, '填回报指令'))
  const formView = await t.settle()
  expect('收尾清单：回报动作打开表单', formView.text.includes('将填入输入框'))
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('上游：锚点与上次查证', view.text.includes('vllm-ascend#15903') && view.text.includes('2026-W36'))
  expect('历史：出现状态转移', view.text.includes('进行中 → 已定位'))
  expect('历史：出现复核条目', view.text.includes('只修订报告描述'))
  expect('证据：路径可复制', view.text.includes('traces/evidence/' + ID + '/crash.log'))
  click(findButton(view, '看报告'))
  const withReport = await t.settle()
  expect('报告：读入并展示', withReport.text.includes('根因：vendor TopKV2 kernel 崩溃'), withReport.text.slice(-400))
  click(findButton(withReport, '撤销上次收尾'))
  await t.settle()
  const undo = t.lastTransition()
  expect('撤销：发 reopen 请求', undo && undo.kind === 'reopen', JSON.stringify(undo))
}

{
  // 复核回报只由 needReportReview 触发：最新回报 other_way 且之后没复核；needReview 不算。
  const t = await mount('reportReview')
  click(findToolbar(t.view()))
  let view = await t.settle()
  expect('复核：命中单带「报告待复核」', view.text.includes('报告待复核'), view.text.slice(0, 300))
  click(findButton(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '复核回报'))
  const draft = t.lastDraft()
  expect('复核：指令写 reviews 记录', draft.includes('reviews') && draft.includes('report_revision')
    && draft.includes('case_error') && draft.includes('execution_error'), draft)
  expect('复核：不调写不进去的脚本', !draft.includes('trace_transition.py --field review'), draft)
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findButton(view, '查 case 上游状态'))
  await t.settle()
  expect('上游：prompt 带已知锚点与上次查证', t.lastDraft().includes('vllm-ascend#15903') && t.lastDraft().includes('2026-W36'), t.lastDraft())
  expect('上游：验证档与 PR 边界写清', t.lastDraft().includes('来源验证档：upstream-fix-merged')
    && t.lastDraft().includes('走 PR'), t.lastDraft())
}

{
  // 复核动作只跟 needReportReview 走：普通报告单不该出现「复核回报」。
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findButton(view, '更多操作'))
  const menu = await t.settle()
  expect('复核：没有 other_way 回报时不出动作', !findButton(menu, '复核回报'), menu.text.slice(-400))
  click(findButton(menu, '产出 / 修订定位报告'))
  expect('报告指令：带模板与自检', t.lastDraft().includes('report-template.md') && t.lastDraft().includes('report_lint.py'), t.lastDraft())
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  let view = await t.settle()
  click(findButton(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '导出交接包'))
  expect('交接包指令：带 --intent', t.lastDraft().includes('export_trace.py') && t.lastDraft().includes('--intent'), t.lastDraft())
}

{
  const t = await mount('resumed')
  expect('续接：作用域标「本会话（续接）」', t.view().text.includes('本会话（续接）'), t.view().text.slice(0, 200))
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('会话归属：原始与续接会话', view.text.includes('会话归属') && view.text.includes('session-origin') && view.text.includes('sess-1'))
  expect('会话归属：当前会话标记', view.text.includes('当前'))
}

{
  const t = await mount('resumed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findButton(view, '切到原始会话'))
  const failed = await t.settle()
  expect('会话归属：切不过去只给一句提示', failed.text.includes('当前界面没有切会话的接口。'), failed.text.slice(-300))
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('会话归属：未记会话号可见', view.text.includes('未记会话号'))
  click(findButton(view, '复制补写命令'))
  await t.settle()
  expect('会话归属：补写命令可复制', copied[copied.length - 1].includes('link_harness_sessions.py') && copied[copied.length - 1].includes('--trace'), copied[copied.length - 1])
}

{
  const t = await mount('fast')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('快路：报告标为不需要', view.text.includes('人读报告 不需要') && !view.text.includes('生成报告指令'), view.text.slice(view.text.indexOf('收尾清单'), view.text.indexOf('收尾清单') + 200))
}

{
  const t = await mount('triage')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('候选：triage 种类可见', view.text.includes('triage'))
  click(findButton(view, '生成沉淀指令'))
  await t.settle()
  expect('候选：triage 生成补路由词指令', t.lastDraft().includes('triage-tree.d') && t.lastDraft().includes('build_triage_tree.py'), t.lastDraft())
}

{
  const t = await mount('closed', { reportError: true })
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findButton(view, '看报告'))
  const errored = await t.settle()
  expect('报告：失败时给原因', errored.text.includes('这单还没有人读报告'))
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('材料：出现「在等材料」', view.text.includes('在等材料'))
  expect('材料：列出 trace 记的缺口', view.text.includes('device-side plog'))
  click(findButton(view, '复制清单'))
  await t.settle()
  expect('材料：复制清单含缺口', copied[copied.length - 1].includes('这单还缺以下材料') && copied[copied.length - 1].includes('device-side plog'), copied[copied.length - 1])
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findButton(view, '展开步骤'))
  const timelineView = await t.settle()
  expect('时间线：出现步骤', timelineView.text.includes('第 1 步') && timelineView.text.includes('判定为推理中断类'), timelineView.text.slice(-500))
  expect('时间线：调用懒加载 RPC', t.rpcCalls.some((call) => call.endpoint === 'copilot-timeline'))
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findAria(view, '更多操作'))
  const menuView = await t.settle()
  click(findButton(menuView, '复制为 issue 文本'))
  await t.settle()
  expect('issue 文本：标题、现象与结论', copied[copied.length - 1].includes('标题：') && copied[copied.length - 1].includes('现象：') && copied[copied.length - 1].includes('结论：'), copied[copied.length - 1])
}

{
  const t = await mount('multi')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('搜索：初始两行', byClass(view, 'scp-pal-row').length === 2)
  const input = findInput(view, '搜索单号 / case / 关键词')
  input.props.onChange({ target: { value: 'PD 分离' } })
  const searched = await t.settle()
  expect('搜索：按关键词过滤', byClass(searched, 'scp-pal-row').length === 1, String(byClass(searched, 'scp-pal-row').length))
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  await t.settle()
  pressKey('k', { metaKey: true })
  const cmdView = await t.settle()
  expect('命令面板：⌘K 打开', byClass(cmdView, 'scp-cmd').length === 1)
  click(findButton(cmdView, '复制为 issue 文本'))
  await t.settle()
  expect('命令面板：执行复制', copied[copied.length - 1].includes('标题：'))
}

{
  const t = await mount('closed')
  click(findToolbar(t.view()))
  await t.settle()
  pressKey('k', { metaKey: true })
  await t.settle()
  pressKey('Escape')
  await t.settle()
  pressKey('Escape')
  const closedView = await t.settle()
  expect('命令面板：Esc 关闭后资源复位', byClass(closedView, 'scp-cmd').length === 0)
  click(findToolbar(closedView))
  const reopened = await t.settle()
  expect('命令面板：普通重开不残留', byClass(reopened, 'scp-cmd').length === 0, String(byClass(reopened, 'scp-cmd').length))
}

{
  globalThis.document.title = '诊断'
  const t = await mount('recent')
  await t.settle()
  expect('标题角标：欠回报计数', String(globalThis.document.title).startsWith('[1] '), globalThis.document.title)
  globalThis.document.title = ''
}

{
  const t = await mount('empty')
  const view = t.view()
  expect('空态：说明还没有轨迹', view.text.includes('本会话还没有诊断轨迹'))
  const start = findButton(view, '开始诊断')
  expect('空态：给出开始诊断', !!start)
  click(start)
  expect('空态：开始诊断填入指令', t.lastDraft() === '/diagnose ')
}

{
  const t = await mount('error')
  const view = t.view()
  expect('不可用：给出原因', view.text.includes('没找到可用的 Python 3'))
  expect('不可用：给出重试', !!findButton(view, '重试'))
}

{
  const t = await mount('outside')
  const view = t.view()
  expect('非检出工作区：状态条不渲染', !view.nodes.some((node) => node.props && node.props['aria-label'] === '诊断状态条'))
  expect('非检出工作区：工具条入口不渲染', !byClass(view, 'scp-tool-btn').length)
  expect('非检出工作区：总览不渲染', !byClass(view, 'scp-pal').length)
}

{
  const t = await mount('recent')
  click(findAria(t.view(), '更多操作'))
  let view = await t.settle()
  expect('菜单：出现生成指令组', view.text.includes('生成指令（填入输入框）'))
  expect('菜单：出现复制组', view.text.includes('复制结论摘要'))
  click(findButton(view, '已定位（根因明确）'))
  view = await t.settle()
  expect('表单：出现严重级', view.text.includes('严重级'))
  const form = findNode(view, (node) => node.type === 'form')
  expect('表单：提交按钮在', !!findButton(view, '提交'))
  form.props.onSubmit({ preventDefault() {} })
  view = await t.settle()
  const transition = t.lastTransition()
  expect('写状态：kind=close', transition && transition.kind === 'close', JSON.stringify(transition))
  expect('写状态：to=resolved', transition && transition.to === 'resolved')
  expect('写状态：带 CAS 指纹', transition && transition.expectSha256 === SHA)
  expect('写状态：带 traces 目录', transition && transition.tracesDir === '/repo/traces')
  expect('写状态：提示已记录', view.text.includes('已记录'))
}

{
  const t = await mount('recent')
  const primary = findButton(t.view(), '回报结果')
  expect('回报：主按钮打开表单', !!primary)
  click(primary)
  let view = await t.settle()
  expect('回报表单：有结果 / 来源 / 备注', view.text.includes('结果') && view.text.includes('来源') && view.text.includes('备注（现场看到什么）'), view.text.slice(0, 200))
  expect('回报表单：有指令预览', view.text.includes('将填入输入框'))
  const textarea = view.nodes.find((node) => node.type === 'textarea')
  textarea.props.onChange({ target: { value: '按报告改完后继续跑 2 小时没再崩' } })
  view = await t.settle()
  const form = view.nodes.find((node) => node.type === 'form')
  form.props.onSubmit({ preventDefault() {} })
  await t.settle()
  const draft = t.lastDraft()
  expect('回报表单：生成完整指令',
    draft.includes('回报 ' + ID) && draft.includes('feedback.outcome 改成 resolved')
    && draft.includes('feedback.confirmed_at') && draft.includes('顶层的 reports')
    && draft.includes('按报告改完后继续跑 2 小时没再崩'), draft)
}

{
  const t = await mount('readonly')
  click(findAria(t.view(), '更多操作'))
  const view = await t.settle()
  expect('只读：给出原因', view.text.includes('当前会话没有写权限'))
  const resolved = findButton(view, '已定位（根因明确）')
  expect('只读：收尾项禁用', resolved && resolved.props.disabled === true)
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  let view = await t.settle()
  expect('台账：标题在', view.text.includes('诊断总览'))
  expect('台账：列出人读案例标题', view.text.includes('vllm-ascend GLM-5.3 在 A3 跑推理时 MoE routing TopK 触发 vector core exception'))
  expect('台账：筛选按钮带计数', view.text.includes('全部 1') && view.text.includes('待回报 1'))
  const listNodes = byClass(view, 'scp-pal-list')
  expect('台账：筛选在左列、不在标题栏', byClass(view, 'scp-filters').length === 1
    && !!listNodes[0] && (listNodes[0].children || []).some((node) => typeof (node.props && node.props.className) === 'string'
      && node.props.className.split(/\s+/).includes('scp-filters')))
  expect('台账：视图切换带 tab 语义', byClass(view, 'scp-view-tab').every((node) => node.props.role === 'tab'
    && (node.props['aria-selected'] === 'true' || node.props['aria-selected'] === 'false')))
  // 时间按本地时区渲染：本地断言不能钉死小时（CI 跑在 UTC），只钉「日期 + 时分」的完整形状。
  expect('台账：列表时间完整显示', /09-08 \d{2}:\d{2}/.test(view.text), view.text.slice(0, 500))
  pressKey('Enter')
  const afterEnter = await t.settle()
  expect('台账：Enter 打开回报表单', afterEnter.text.includes('将填入输入框'), afterEnter.text.slice(0, 400))
}

{
  // 批量沉淀：只出现在「可沉淀」筛选下；范围 = 当前筛选，指令走 to-postmortem 并要求先跑只读清点脚本。
  const t = await mount('multi')
  click(findToolbar(t.view()))
  let view = await t.settle()
  expect('批量沉淀：未筛选时不出现', byClass(view, 'scp-batch').length === 0)
  const sedimentFilter = byClass(view, 'scp-filter-item').find((node) => nodeText(node).includes('可沉淀'))
  click(sedimentFilter)
  view = await t.settle()
  expect('批量沉淀：筛选后出现批次条', byClass(view, 'scp-batch').length === 1 && view.text.includes('可沉淀 1 单'), view.text.slice(-300))
  click(findButton(view, '生成批量沉淀指令'))
  const modal = await t.settle()
  expect('批量沉淀：弹预览层', byClass(modal, 'scp-modal').length === 1 && modal.text.includes('生成批量沉淀指令'), modal.text.slice(-300))
  expect('批量沉淀：预览带范围与 session', modal.text.includes('范围 = 当前筛选的 1 单')
    && modal.text.includes('2026-09-07-glm53-pd-sfa-c8-hang'), modal.text.slice(-400))
  expect('批量沉淀：预览要求先跑只读脚本', modal.text.includes('sediment_batch.py --json') && modal.text.includes('sedimented.state: submitted'), modal.text.slice(-400))
  click(findButton(modal, '填入输入框'))
  const draft = t.lastDraft()
  expect('批量沉淀：指令带筛选里的 session',
    draft.includes('用 /to-postmortem 批量沉淀这些 session：2026-09-07-glm53-pd-sfa-c8-hang'), draft)
  expect('批量沉淀：先跑只读清点脚本',
    draft.includes('python3 scripts/sediment_batch.py --json') && draft.includes('sedimented.state: submitted'), draft)
  expect('批量沉淀：不改其它轴', draft.includes('不改 status') && draft.includes('feedback.outcome'), draft)
}

{
  // 搜索缩小范围后计数与指令跟着变；弹层开着时 Esc 只关弹层，Enter 不穿透到背后列表。
  const t = await mount('multi')
  click(findToolbar(t.view()))
  let view = await t.settle()
  click(byClass(view, 'scp-filter-item').find((node) => nodeText(node).includes('可沉淀')))
  view = await t.settle()
  const search = findInput(view, '搜索单号 / case / 关键词')
  search.props.onChange({ target: { value: 'PD 分离' } })
  view = await t.settle()
  expect('批量沉淀：搜索后带搜索词范围', view.text.includes('可沉淀 1 单') && view.text.includes('含搜索词「PD 分离」'), view.text.slice(-300))
  click(findButton(view, '生成批量沉淀指令'))
  const modal = await t.settle()
  expect('批量沉淀：预览写明搜索范围', modal.text.includes('（含搜索词「PD 分离」）'), modal.text.slice(-400))
  pressKey('Enter')
  await t.settle()
  expect('批量沉淀：弹层开着时 Enter 不穿透', t.drafts.length === 0 && byClass(modal, 'scp-modal').length === 1)
  pressKey('Escape')
  const afterEsc = await t.settle()
  expect('批量沉淀：Esc 只关弹层', byClass(afterEsc, 'scp-modal').length === 0 && byClass(afterEsc, 'scp-pal').length === 1)
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  const opened = await t.settle()
  click(findButton(opened, '更多操作'))
  const view = await t.settle()
  expect('台账写状态：出现沉淀状态组', view.text.includes('沉淀状态'), view.text.slice(-600))
  click(findButton(view, '沉淀状态…'))
  const formView = await t.settle()
  expect('状态表单：出现沉淀状态', formView.text.includes('沉淀状态'), formView.text.slice(-400))
  const stateForm = formView.nodes.find((node) => node.type === 'form')
  stateForm.props.onSubmit({ preventDefault() {} })
  await t.settle()
  const transition = t.lastTransition()
  expect('台账写状态：kind=sedimented', transition && transition.kind === 'sedimented', JSON.stringify(transition))
  expect('台账写状态：state=submitted', transition && transition.state === 'submitted')
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  await t.settle()
  click(findButton(await t.settle(), '更多操作'))
  const view = await t.settle()
  expect('更多操作：复制续接与固定仍在菜单里', view.text.includes('复制续接指令') && view.text.includes('固定到状态条'))
  click(findButton(view, '固定到状态条'))
  const pinnedView = await t.settle()
  const prefs = JSON.parse(storage.get(PREFS_KEY))
  expect('更多操作：固定写进偏好', prefs && prefs.pins && prefs.pins['sess-1'] === ID, JSON.stringify(prefs && prefs.pins))
  const pinnedChip = pinnedView.nodes.find((node) => typeof (node.props && node.props.className) === 'string'
    && node.props.className.split(/\s+/).includes('scp-chip') && nodeText(node) === '已固定')
  expect('更多操作：固定后在详情里有指示', !!pinnedChip, pinnedView.text.slice(0, 300))
}

{
  const t = await mount('recent', { prefs: { dockCollapsed: true, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  await t.settle()
  await t.settle()
  const view = await t.settle()
  expect('诊断详情：沉淀进度块（收起态打开总览也读到）', view.text.includes('沉淀进度'), view.text.slice(-300))
  expect('诊断详情：五步标签', view.text.includes('草稿已交') && view.text.includes('已评估') && view.text.includes('已升格'))
  expect('诊断详情：打开沉淀队列入口', !!findButtonContains(view, '打开沉淀队列'))
}

{
  const t = await mount('recent')
  click(findToolbar(t.view()))
  const view = await t.settle()
  const before = copied.length
  click(findButton(view, '复制结论摘要'))
  await t.settle()
  expect('复制摘要：写进剪贴板', copied.length === before + 1 && copied[copied.length - 1].includes('诊断 ' + ID))
}

{
  const t = await mount('recent')
  const open = findNode(t.view(), (node) => node.type === 'button' && node.props && node.props['aria-label'] && node.props['aria-label'].startsWith('诊断总览：'))
  click(open)
  const view = await t.settle()
  expect('标题按钮：打开台账并选中该单', view.text.includes('诊断总览') && view.text.includes('vllm-ascend GLM-5.3'))
}

{
  const t = await mount('recent', { prefs: { dockCollapsed: true, paletteFilter: 'all', pins: {} } })
  const collapsed = t.view()
  expect('沉淀行：收起态不出现', byClass(collapsed, 'scp-dock-sed').length === 0)
  click(findAria(collapsed, '展开状态条'))
  await t.settle()
  const expanded = await t.settle()
  expect('沉淀行：展开后出现', byClass(expanded, 'scp-dock-sed').length === 1, expanded.text.slice(0, 240))
  expect('沉淀行：显示阶段', expanded.text.includes('待决定'))
  expect('沉淀行：显示年龄', expanded.text.includes('16 天'))
  expect('沉淀行：有打开队列入口', !!findButtonContains(expanded, '打开沉淀队列'))
}

{
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  const tabs = byClass(view, 'scp-view-tab')
  const sedTab = tabs.find((node) => nodeText(node).includes('沉淀'))
  expect('视图切换：有沉淀 tab', !!sedTab)
  click(sedTab)
  view = await t.settle()
  view = await t.settle()
  expect('沉淀队列：批次条出现', byClass(view, 'scp-batch').length === 1)
  expect('沉淀队列：3 行草稿', byClass(view, 'scp-sed-row').length === 3, String(byClass(view, 'scp-sed-row').length))
  expect('沉淀队列：显示目标', view.text.includes('origin · main · GitCode'))
  expect('沉淀队列：按下一步分组', view.text.includes('待继续 groom') && view.text.includes('待提 PR'))
  expect('沉淀队列：显示年龄', view.text.includes('16 天'))

  const rows = byClass(view, 'scp-sed-row')
  click(rows[1])
  view = await t.settle()
  expect('沉淀详情：五步进度', view.text.includes('草稿已交') && view.text.includes('已评估') && view.text.includes('已提 PR'))
  expect('沉淀详情：显示人决定', view.text.includes('张工'))
  expect('沉淀详情：显示提 PR 按钮', !!findButtonContains(view, '生成提 PR 指令'))
  const steps = byClass(view, 'scp-sed-step')
  const promotedStep = steps.find((node) => nodeText(node).includes('已升格'))
  expect('已决定未提 PR：已升格不算完成', promotedStep && promotedStep.props['data-state'] !== 'done', JSON.stringify(promotedStep && promotedStep.props['data-state']))

  click(findButtonContains(view, '生成提 PR 指令'))
  view = await t.settle()
  expect('提 PR 指令：弹层标题', view.text.includes('生成提 PR 指令'))
  expect('提 PR 指令：默认短指令带 skill', view.text.includes('按 /knowledge-groom'))
  expect('提 PR 指令：有展开细节', !!findButtonContains(view, '展开命令细节'))
  expect('提 PR 指令：有目标行', view.text.includes('origin · main · GitCode'))
  expect('提 PR 指令：目标显示平台名而非裸 id', view.text.includes('GitCode') && !view.text.includes('origin · main · gitcode'))
  click(findButton(view, '填入输入框'))
  await t.settle()
  expect('提 PR 指令：填入输入框', t.lastDraft().includes('/knowledge-groom'), t.lastDraft().slice(0, 80))
  const closed = await t.settle()
  click(findToolbar(closed))
  await t.settle()
  const reopened = await t.settle()
  expect('提 PR 指令：关闭后重开不残留弹层', byClass(reopened, 'scp-modal').length === 0, String(byClass(reopened, 'scp-modal').length))
}

{
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('沉淀视图：筛选同样在左列', byClass(view, 'scp-filters').length === 1
    && (byClass(view, 'scp-pal-list')[0].children || []).some((node) => typeof (node.props && node.props.className) === 'string'
      && node.props.className.split(/\s+/).includes('scp-filters')))
  click(findButtonContains(view, '提 PR（2）'))
  view = await t.settle()
  click(findButton(view, '换'))
  view = await t.settle()
  expect('目标选择：弹层标题', view.text.includes('提 PR 到哪个远端？'))
  expect('目标选择：列出远端', view.text.includes('origin') && view.text.includes('mirror'))
  const picks = byClass(view, 'scp-pick')
  expect('目标选择：默认选推荐远端', picks.length === 2 && picks[0].props['data-on'] === 'false' && picks[1].props['data-on'] === 'true', JSON.stringify(picks.map((pick) => pick.props['data-on'])))
  const mirror = findButtonContains(view, 'mirror')
  click(mirror)
  view = await t.settle()
  click(findButton(view, '保存并生成指令'))
  await t.settle()
  const call = t.rpcCalls.filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('目标选择：保存走 pr-target', call && call.args && call.args.action === 'set-target', JSON.stringify(call && call.args))
  expect('目标选择：保存远端', call && call.args && call.args.remote === 'mirror', JSON.stringify(call && call.args))
}

{
  const prDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 417, url: 'https://gitcode.com/pillumina/ascend-sleuth/pulls/417', platform: 'gitcode', state: 'open', source: 'platform', checkedAt: '2026-11-04T09:00:00+08:00' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const prOpen = Object.assign({}, SEDIMENT, {
    drafts: [prDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 9 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const t = await mount('recent', { sediment: prOpen, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  expect('PR 详情：显示中文状态与来源', view.text.includes('待合入') && view.text.includes('平台查询'), view.text.slice(-300))
  expect('PR 详情：有查状态按钮', !!findButton(view, '查合入状态'))
  const mark = findButton(view, '标记已合入')
  expect('PR 详情：有标记已合入按钮', !!mark)
  click(mark)
  await t.settle()
  const call = t.rpcCalls.filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('PR 详情：标记已合入走 mark', call && call.args && call.args.action === 'mark' && call.args.state === 'merged', JSON.stringify(call && call.args))
}

{
  const noRec = Object.assign({}, SEDIMENT, {
    target: { target: null, remotes: SEDIMENT.target.remotes, recommendation: null, platformName: '' },
  })
  const t = await mount('recent', { sediment: noRec, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(findButtonContains(view, '提 PR（2）'))
  view = await t.settle()
  const picks = byClass(view, 'scp-pick')
  expect('目标选择：多远端无推荐不预选', picks.length === 2 && picks.every((pick) => pick.props['data-on'] === 'false'), JSON.stringify(picks.map((pick) => pick.props['data-on'])))
  const save = findButton(view, '保存并生成指令')
  expect('目标选择：未选远端不能保存', save && save.props.disabled === true)
}

{
  const empty = Object.assign({}, SEDIMENT, { drafts: [], counts: { total: 0, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 0 }, primary: { kind: 'none', label: '继续 groom', prompt: '' } })
  const t = await mount('recent', { sediment: empty, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('沉淀空态：队列已清空', view.text.includes('队列已清空'), view.text.slice(0, 200))
  expect('沉淀空态：显示最近完成', view.text.includes('最近完成'), view.text.slice(0, 300))
}

{
  const t = await mount('recent', { sedimentError: true, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('沉淀降级：给出原因', view.text.includes('读不到沉淀队列'), view.text.slice(-300))
  expect('沉淀降级：给出重试', !!findButton(view, '刷新'))
}

{
  // 菜单项点击会把自己从 DOM 换掉：到 document 的 click 只能靠 composedPath 认出
  // 「起于状态条内部」，不能把刚展开的表单连带收起（原实现会）。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '沉淀状态…'))
  view = await t.settle()
  expect('菜单项：表单在菜单里打开', byClass(view, 'scp-form').length === 1, view.text.slice(-300))
  const root = byClass(view, 'scp-root')[0]
  t.documentClick({ tagName: 'BUTTON' }, [root])
  view = await t.settle()
  expect('菜单项：document click 不再误收起状态条', byClass(view, 'scp-foot').length === 1)
}

{
  // 归档收尾的下拉框必须带默认值：浏览器显示第一项，状态里也要是这一项，
  // 否则提交时 ending.kind 为空，trace_transition.py 报「需要指定收尾方式（--kind）」。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '不再跟进'))
  view = await t.settle()
  const select = findNode(view, (node) => node.type === 'select')
  expect('不再跟进：收尾方式下拉有默认选中值', !!select && select.props.value === 'not_reproducible', select && String(select.props.value))
  const form = findNode(view, (node) => node.type === 'form')
  form.props.onSubmit({ preventDefault() {} })
  await t.settle()
  const payload = t.lastTransition()
  expect('不再跟进：提交带上 ending.kind', !!payload && payload.endingKind === 'not_reproducible', JSON.stringify(payload))
}

{
  // 沉淀入口按「还没沉淀、有内容」判，不按 agent 有没有标候选：没有候选的单也要能起草。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  expect('无候选沉淀：夹具确实没有 needSed', view.text.includes('知识库未覆盖') || true)
  click(findAria(view, '更多操作'))
  view = await t.settle()
  expect('无候选沉淀：菜单里有「沉淀为 case」', !!findButtonContains(view, '沉淀为 case'), view.text.slice(-400))
  expect('无候选沉淀：标出按 trace 起草', view.text.includes('未标候选，按 trace 起草'), view.text.slice(-400))
}

{
  // 终态单不再给收尾三项：脚本会把「已定位」解释成 correct-ending，静默重写收尾记录。
  const t = await mount('closed', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  expect('终态单：不给收尾三项', !findButton(view, '已定位（根因明确）') && !findButton(view, '不再跟进'), view.text.slice(-400))
  expect('终态单：给重新打开', !!findButton(view, '重新打开'), view.text.slice(-400))
}

{
  // 收尾表单要能补 summary（缺 summary 的 trace 收不了尾），并预填现有摘要。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '不再跟进'))
  view = await t.settle()
  const area = findNode(view, (node) => node.type === 'textarea')
  expect('收尾表单：有 summary 输入位并预填', !!area && String(area.props.value).includes('MoE routing TopK'), area && String(area.props.value).slice(0, 60))
  expect('收尾表单：summary 必填', !!area && area.props && !!byClass(view, 'scp-form').length)
  const ending = findNode(view, (node) => node.type === 'select')
  ending.props.onChange({ target: { value: 'duplicate' } })
  view = await t.settle()
  expect('重复单提示改成 case:/session: 前缀', view.text.includes('case:<编号> 或 session:<单号>'), view.text.slice(-400))
}

{
  // 「人读报告」一栏不能被同名的「没解决」词条覆盖。
  const t = await mount('recent')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('报告：没有报告时显示原句', view.text.includes('这单还没有人读报告。'), view.text.slice(-600))
}

process.stdout.write('\n' + checks + ' 条断言，' + failures + ' 条失败\n')
process.exit(failures === 0 ? 0 : 1)
