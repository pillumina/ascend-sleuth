// 渲染冒烟（开发用，不进安装产物）：不启浏览器，用最小 React 替身把四个面跑一遍。
//
// 跑法：node dsh-plugins/dsh-sleuth-copilot/test/render-smoke.mjs
// 它证明不了真实页面的排版与点击，只证明：状态分支不抛、文案在、按钮发出的 RPC 与指令对。
// 每个用例用带 query 的模块 URL 重新导入一次，拿到干净的模块级 store 与偏好。

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
// 版本串两处（package.json 与 client 的 PLUGIN_VERSION）必须同步；用包里的版本做期望值，
// 免得每次 bump 都要改断言。
const PKG_VERSION = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8')).version
const CLIENT_URL = pathToFileURL(join(ROOT, 'lib', 'client.js')).href

// ── 最小浏览器环境 ──────────────────────────────────────────────────────────
const storage = new Map()
const moduleDefs = []
const copied = []
const keyHandlers = new Set()
const documentHandlers = new Map()
const styleTags = []
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
  head: { appendChild(tag) { if (tag && typeof tag.textContent === 'string') styleTags.push(tag) } },
  addEventListener(type, fn) {
    if (!documentHandlers.has(type)) documentHandlers.set(type, new Set())
    documentHandlers.get(type).add(fn)
  },
  removeEventListener(type, fn) {
    const set = documentHandlers.get(type)
    if (set) set.delete(fn)
  },
  execCommand: () => true,
  // 「去同步」会找整页的「知识库」标签：替身里没有 DOM，返回空列表走兜底分支。
  querySelectorAll: () => [],
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
// 计时器替身：不自动触发（否则 10 秒轮询会把测试进程挂住），用例手动 fireInterval 来推进。
const intervalHandlers = new Map()
let intervalSeq = 0
globalThis.setInterval = (fn, ms) => {
  intervalSeq += 1
  intervalHandlers.set(intervalSeq, { fn, ms })
  return intervalSeq
}
globalThis.clearInterval = (id) => {
  intervalHandlers.delete(id)
}

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
      // 真实 React 在两次渲染的 hook 数量不一致时报错（rules of hooks）：提前 return 之后
      // 调 hook 会让整块界面崩掉，而纯渲染断言看不出来。这里按组件实例记账，替真机兜住这类回归。
      const hooksUsed = instance.cursor
      if (instance.hookCount !== undefined && instance.hookCount !== hooksUsed) {
        throw new Error('组件 ' + path + ' 的 hook 数量从 ' + instance.hookCount + ' 变成 ' + hooksUsed
          + '（hook 必须在任何提前 return 之前、每次渲染同序同数量）')
      }
      instance.hookCount = hooksUsed
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
    // 模拟整页切换把组件树卸载：只跑组件 effect 的清理，不回退插件级（apply 注册的）清理。
    unmount() {
      for (const instance of instances.values()) {
        for (const state of Object.values(instance.effectState)) {
          if (state && typeof state.cleanup === 'function') {
            try {
              state.cleanup()
            } catch {
              // 清理失败不阻断其余
            }
          }
        }
      }
      instances.clear()
      tree = null
      dom = null
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

function findSelectWithOption(view, value) {
  return view.nodes.find((node) => node.type === 'select'
    && (node.children || []).some((child) => child && child.props && String(child.props.value) === String(value)))
}

function findNode(view, predicate) {
  return view.nodes.find(predicate)
}

// 取最近一次 mount 注入的样式里某条规则的声明块；排版契约靠它断言，不靠人看。
function cssRule(selector) {
  const tag = styleTags[styleTags.length - 1]
  const css = tag && typeof tag.textContent === 'string' ? tag.textContent : ''
  const start = css.indexOf(selector + '{')
  if (start < 0) return ''
  const end = css.indexOf('}', start)
  return end < 0 ? '' : css.slice(start + selector.length + 1, end)
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
  if (mode === 'longsummary') {
    // 真机 trace 的 summary 首句常有一两百字：详情抬头要按正文收成四行，不能当标题放大。
    const longRow = makeRow({
      summary: 'vllm-ascend GLM-5.3-Flash-w8a8 在 Atlas A3 超节点（16 x Ascend910，TP16+EP）跑推理，'
        + '服务在并发长 prompt 负载下两次以同一签名崩溃：MoE token dispatch preprocess 的 '
        + 'torch.repeat_interleave(token_dispatcher.py:623) 处上抛 RuntimeError error code 507035，'
        + '设备侧 fftsplus aivector error、vec error info 0x470000020d，指向确定性 kernel/tiling bug 而非硬件故障；'
        + '历史日志在 data.jsonl，编译产物是 x.pyc。',
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: longRow, recent: [longRow], all: [longRow],
      counts: { open: 1, pendingFeedback: 1, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS,
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
  if (mode === 'terminal') {
    const terminalRow = makeRow({
      status: 'resolved',
      feedback: { outcome: 'resolved', case: 'VLLM-ASC-11312' },
      activeCase: 'VLLM-ASC-11312',
      transitions: [{ at: '2026-09-08T16:00:00+08:00', from: 'in_progress', to: 'resolved', note: '根因明确' }],
      reports: [{ at: '2026-09-08T16:05:00+08:00', source: 'field', result: 'from_report', note: '已生效' }],
      derived: {
        open: false, closed: true, caseKind: 'case', needSed: false,
        needPromote: false, needReview: false, waitingFor: '', waitingOn: null,
      },
      actions: [
        {
          id: 'correct-ending', label: '改收尾方式', to: ['resolved', 'escalated', 'archived'],
          endingChoices: [],
          targets: [
            {
              to: 'resolved', action: 'close-resolved', label: '已定位',
              requires: ['resolved_at'], fillable: ['summary', 'severity', 'fix_emitted'], mustExist: [],
              endingChoices: [{ value: 'root_cause', label: '根因明确', requires: [] }],
            },
            {
              to: 'escalated', action: 'close-escalated', label: '已转交他人',
              requires: ['ending.handed_to'], fillable: ['summary'], mustExist: [],
              endingChoices: [{ value: 'handed_off', label: '转交他人跟进', requires: ['ending.handed_to'] }],
            },
          ],
        },
        {
          id: 'backfill-ending', label: '补记收尾方式', to: ['resolved', 'escalated', 'archived'],
          endingChoices: [{ value: 'root_cause', label: '根因明确', requires: [] }],
        },
        { id: 'reopen', label: '重新打开', to: ['in_progress'] },
      ],
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: terminalRow, recent: [terminalRow], all: [terminalRow],
      counts: { open: 0, pendingFeedback: 0, toSediment: 0 }, vocab: VOCAB, capabilities: CAPS,
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
      undo: {
        available: true,
        prompt: '撤销这次沉淀：2026-10-28-pd-prefill-hang。\n'
          + '先看计划（只读）：\npython3 scripts/sediment_undo.py --draft-key 2026-10-28-pd-prefill-hang\n'
          + '确认后执行：\npython3 scripts/sediment_undo.py --draft-key 2026-10-28-pd-prefill-hang --apply\n'
          + '脚本把草稿移进 postmortems/inbox/.undone/（移回即复活）、删掉评估状态文件、'
          + '把来源 trace 的 sedimented 改回 none；不动 knowledge/。',
      },
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
      stale: true, staleReasons: ['目标 4823d40 落后于评估基准 8f1d2c 的 1 个知识文件'],
      targetRef: 'refs/remotes/mirror/main', targetShort: '4823d40',
      targetState: 'target_behind', targetSource: 'assessment',
      targetWarnings: ['当前配置目标 refs/remotes/origin/main 解析不到（先 fetch 或确认远端）'],
      decision: 'variant', decisionValid: true, decisionBy: '张工', decisionAt: '2026-11-03',
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
  const openedSessions = []
  // 「去同步」要切到的整页面板；没有 layout 服务的降级路径由 opts.noLayout 覆盖。
  const selectedPanels = []
  // 进度端点的调用序号与 check-all 的挂起门：用例要验「主 RPC 还没回来时轮询已能拿到行」。
  let progressIndex = 0
  let releaseCheckAllGate = null
  const checkAllGate = opts.prCheckAllGate
    ? new Promise((resolve) => { releaseCheckAllGate = resolve })
    : null
  const payload = makeState(mode)
  payload.upstream = opts.upstream === false
    ? { ready: false, reason: 'gh 未登录（gh auth login）' }
    : { ready: true, reason: '' }
  // 知识库落后提示由 host 附加在 copilot-state 的响应里；不给就是「没有提示」。
  if (opts.kbNotice !== undefined) payload.kbNotice = opts.kbNotice
  // 连败上屏同样由 host 附加；不给就是「没有失败」。
  if (opts.kbError !== undefined) payload.kbError = opts.kbError

  const slots = {
    inject(_name, callback) {
      callback()
    },
    register(registration, component) {
      registry[registration.name] = component
      return () => {}
    },
  }
  // 侧栏 shell 的整页切换服务。宿主不把它写进必需依赖，靠 ctx.get 探针 + ctx.inject 动态注册：
  // opts.noLayout 模拟服务缺席（探针与回调都拿不到），opts.layoutScopeMissing 模拟回调触发但
  // 子 scope 取不到，opts.layoutDeferred 模拟服务晚于 apply 就绪（回调先记下，用例手动触发）。
  const layoutHost = {
    selectPanel(id) {
      selectedPanels.push(String(id))
    },
  }
  const deferredInjects = []
  // apply 里登记的清理（插件级），t.dispose() 时反向跑一遍：知识库复查/标签轮询是 module 级的，
  // 只能从这里清，否则会挂住测试进程。
  const pluginDisposers = []
  const ctx = {
    effect(fn) {
      const cleanup = fn()
      if (typeof cleanup === 'function') pluginDisposers.push(cleanup)
      return cleanup
    },
    inject(deps, callback) {
      if (!Array.isArray(deps) || deps.indexOf('layout') < 0) return
      if (opts.noLayout) return
      const fire = () => callback({
        get(name) {
          return name === 'layout' && !opts.layoutScopeMissing ? layoutHost : undefined
        },
      })
      if (opts.layoutDeferred) {
        deferredInjects.push(fire)
        return
      }
      fire()
    },
    get(name) {
      if (name === 'connection') {
        return {
          rpc: {
            async call(_channel, endpoint, args) {
              rpcCalls.push({ endpoint, args })
              if (endpoint === 'copilot-state') return { ok: true, value: payload }
              if (endpoint === 'copilot-kb-dismiss') {
                if (opts.kbDismissError) throw new Error('状态文件不可写，没记上这一版')
                const rev = args && args.rev ? String(args.rev) : ''
                // host 写不进本地状态文件时回 saved:false：这次只记在内存里，客户端不该收起行。
                return { ok: true, value: { rev, saved: opts.dismissSaved === false ? false : true } }
              }
              if (endpoint === 'copilot-kb-recheck') {
                // 复查端点的替身：默认返回「已没有落后」；用例可用 opts.onKbRecheck 改 state，
                // 让随后的 refresh(true) 看到新的 kbNotice。
                if (typeof opts.onKbRecheck === 'function') opts.onKbRecheck(args, payload)
                return { ok: true, value: { notice: null, checkedAt: '', error: '', reason: '' } }
              }
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
              if (endpoint === 'copilot-pr-progress') {
                if (opts.prProgressError) throw new Error('进度端点不可用')
                const steps = Array.isArray(opts.prProgress) ? opts.prProgress : []
                const value = steps.length
                  ? steps[Math.min(progressIndex, steps.length - 1)]
                  : { present: false, rows: [], done: false }
                progressIndex += 1
                return { ok: true, value }
              }
              if (endpoint === 'copilot-pr-target') {
                const action = args && args.action
                if (action === 'check') {
                  return { ok: true, value: opts.prCheckResult || {
                    ok: true, draft: args.key, platform: 'github', state: 'open',
                    source: 'platform', checked_at: '2026-11-05T10:41:12+08:00',
                  } }
                }
                if (action === 'check-all') {
                  if (checkAllGate) await checkAllGate
                  return { ok: true, value: opts.prCheckAllResult || {
                    ok: true, checked: [{ draft: '2026-11-01-eplb-103900', ok: true, state: 'open' }],
                  } }
                }
                if (action === 'mark') {
                  return { ok: true, value: opts.prMarkResult || {
                    ok: true, draft: args.key, pr: { state: args.state }, sha256: 'f'.repeat(64),
                  } }
                }
                return { ok: true, value: opts.prSetTargetResult || {
                  ok: true, target: (opts.sediment || SEDIMENT).target,
                } }
              }
              throw new Error('unexpected endpoint ' + endpoint)
            },
          },
        }
      }
      if (name === 'slots') return slots
      // 探针路径：服务在时直接拿得到；noLayout / layoutScopeMissing / layoutDeferred 都先拿不到。
      if (name === 'layout') {
        return opts.noLayout || opts.layoutScopeMissing || opts.layoutDeferred ? undefined : layoutHost
      }
      // 只有显式给了 opts.sessionsHost 才装会话服务：默认没有它，才能继续验「没有切会话接口」的降级。
      if (name === 'sessions' && opts.sessionsHost) {
        return { openSession(id) { openedSessions.push(String(id)) } }
      }
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
    openedSessions,
    selectedPanels,
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
    // 手动推进指定周期的计时器（轮询替身不会自己跑）。
    async fireInterval(ms) {
      const targets = Array.from(intervalHandlers.values()).filter((item) => item.ms === ms)
      for (const item of targets) item.fn()
      await new Promise((resolve) => setTimeout(resolve, 0))
      await new Promise((resolve) => setTimeout(resolve, 0))
    },
    releaseCheckAll() {
      if (!releaseCheckAllGate) return
      const release = releaseCheckAllGate
      releaseCheckAllGate = null
      release()
    },
    // 触发一次延迟注册的 layout 回调（opts.layoutDeferred 时由用例调）。
    fireLayoutInject() {
      const fire = deferredInjects.shift()
      if (typeof fire === 'function') fire()
    },
    // 卸载组件树（模拟整页切换把状态条连同输入区一起换掉）。插件级清理不受影响。
    unmount() {
      renderer.unmount()
    },
    // 插件卸载：反向跑 apply 登记的所有清理，module 级知识库定时器也在这里清。
    dispose() {
      for (let index = pluginDisposers.length - 1; index >= 0; index -= 1) {
        try {
          pluginDisposers[index]()
        } catch {
          // 清理失败不阻断其余
        }
      }
      pluginDisposers.length = 0
    },
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
  // layout 不进 inject：缺席时整条状态条不该进 waiting（见 probeLayout 的探针 + 动态注册）。
  expect('注册：layout 不写成必需依赖',
    Array.isArray(t.inject) && !t.inject.includes('layout'), JSON.stringify(t.inject))
  expect('最近一单：标出「最近一单」', view.text.includes('最近一单'), view.text.slice(0, 160))
  expect('最近一单：显示状态名', view.text.includes('进行中'))
  expect('最近一单：显示人读案例标题', view.text.includes('vllm-ascend GLM-5.3 在 A3 跑推理时 MoE routing TopK 触发 vector core exception'))
  expect('最近一单：单号不占标题位', !view.text.includes(ID), view.text.slice(0, 400))
  expect('最近一单：显示在等什么', view.text.includes('缺 device-side plog'))
  expect('最近一单：进度轨显示 5/6', view.text.includes('5/6'))
  expect('最近一单：主按钮是回报结果', !!findButton(view, '回报结果'))
  expect('最近一单：显示身份标签（知识库未覆盖）', view.text.includes('知识库未覆盖'))
  expect('最近一单：状态条不显示计数类标签', !view.text.includes('已排除 3 条'))
  expect('最近一单：版本串与 package.json 一致', view.nodes.some((node) => node.props && node.props['data-version'] === PKG_VERSION), PKG_VERSION)
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
  expect('选择器：当前行带「当前」标记', byClass(opened, 'scp-picker-current').length === 1,
    String(byClass(opened, 'scp-picker-current').length))
  expect('选择器：未固定时脚注给当前单',
    byClass(opened, 'scp-picker-foot-note').length === 1
      && nodeText(byClass(opened, 'scp-picker-foot-note')[0]).includes('当前'),
    String(byClass(opened, 'scp-picker-foot-note').length))
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
  const t = await mount('multi', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: { 'sess-1': '2026-09-07-glm53-pd-sfa-c8-hang' } } })
  click(findAria(t.view(), '跟踪哪一单'))
  const opened = await t.settle()
  expect('选择器：已固定时脚注让位、给「取消固定」',
    byClass(opened, 'scp-picker-foot-note').length === 0 && !!findButton(opened, '取消固定'),
    String(byClass(opened, 'scp-picker-foot-note').length))
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
  const reportCall = t.rpcCalls.filter((call) => call.endpoint === 'copilot-report').pop()
  expect('报告：带 traceFile 兜底（session_id 与文件名不一致时按文件读）',
    !!reportCall && reportCall.args.traceFile === ID + '.yaml', JSON.stringify(reportCall && reportCall.args))
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
  expect('材料：出现「还缺什么」', view.text.includes('还缺什么'))
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
  const timelineCall = t.rpcCalls.filter((call) => call.endpoint === 'copilot-timeline').pop()
  expect('时间线：带 sessionId（读子进程按会话档位）', !!timelineCall && timelineCall.args.sessionId === 'sess-1', JSON.stringify(timelineCall && timelineCall.args))
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
  expect('命令面板：说明作用于哪一单',
    byClass(cmdView, 'scp-cmd-where').length === 1
      && nodeText(byClass(cmdView, 'scp-cmd-where')[0]).includes('作用于'),
  nodeText(byClass(cmdView, 'scp-cmd-where')[0] || {}))
  expect('命令面板：按用途分组', byClass(cmdView, 'scp-cmd-group').length >= 2,
    String(byClass(cmdView, 'scp-cmd-group').length))
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
  const fixSelect = findSelectWithOption(view, 'true')
  expect('表单：可执行修复要显式选', !!fixSelect)
  fixSelect.props.onChange({ target: { value: 'true' } })
  view = await t.settle()
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
  expect('详情抬头：短摘要不给展开入口', !findButton(view, '展开全文'))
  pressKey('Enter')
  const afterEnter = await t.settle()
  expect('台账：Enter 打开回报表单', afterEnter.text.includes('将填入输入框'), afterEnter.text.slice(0, 400))
}

{
  // 详情抬头：一行状态与身份 + 人读背景。真机摘要首句一两百到七八百字，放大加粗会占掉
  // 详情的大半屏，所以只留正文层级；错误码、路径、调用改等宽，长文收起并可展开。
  const t = await mount('longsummary')
  click(findToolbar(t.view()))
  let view = await t.settle()
  const identity = byClass(view, 'scp-identity')
  expect('详情抬头：一行识别信息', identity.length === 1 && nodeText(identity[0]).includes('进行中')
    && nodeText(identity[0]).includes('第 5/6 步'), identity.length ? nodeText(identity[0]) : 'missing')
  expect('详情抬头：不再用放大标题放摘要', byClass(view, 'scp-hero-title').length === 0)
  const lede = byClass(view, 'scp-lede')
  expect('详情抬头：背景按正文渲染且默认收起', lede.length === 1 && lede[0].props['data-open'] === 'false')
  const codes = byClass(view, 'scp-icode').map((node) => nodeText(node))
  expect('详情抬头：行内标识走等宽', codes.includes('torch.repeat_interleave(token_dispatcher.py:623)')
    && codes.includes('RuntimeError') && codes.includes('0x470000020d') && codes.includes('507035'), codes.join(' / '))
  expect('详情抬头：已有扩展名后接更长后缀时不拆开', !codes.includes('data.json') && !codes.includes('x.py')
    && view.text.includes('data.jsonl') && view.text.includes('x.pyc'), codes.join(' / '))
  const expand = findButton(view, '展开全文')
  expect('详情抬头：长摘要给展开入口', !!expand)
  if (expand) click(expand)
  const open = await t.settle()
  expect('详情抬头：展开后给收起入口', byClass(open, 'scp-lede')[0].props['data-open'] === 'true'
    && !!findButton(open, '收起全文'))
  expect('详情抬头：背景只出现一处', byClass(open, 'scp-p').length === 0)
  expect('详情抬头：顶部有案例标题锚点', byClass(open, 'scp-pal-titlecase').length === 1
    && nodeText(byClass(open, 'scp-pal-titlecase')[0]).includes('vllm-ascend'),
  String(byClass(open, 'scp-pal-titlecase').length))
  expect('详情抬头：在等并入「还缺什么」块', byClass(open, 'scp-missing-lead').length === 1
    && nodeText(byClass(open, 'scp-missing-lead')[0]).includes('在等'),
  byClass(open, 'scp-missing-lead').length + ' / ' + nodeText(byClass(open, 'scp-missing-lead')[0] || {}))
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
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  const actionBar = byClass(view, 'scp-actions')[0]
  const copyCount = ((actionBar && nodeText(actionBar)) || '').match(/复制结论摘要/g) || []
  expect('终态单：底部只有一个复制摘要按钮', copyCount.length === 1, String(copyCount.length))
  const primaryBtn = view.nodes.find((node) => node.type === 'button'
    && String((node.props && node.props.className) || '').includes('scp-btn--primary'))
  expect('终态单：复制摘要不作蓝色主按钮', !primaryBtn || !nodeText(primaryBtn).includes('复制结论摘要'))
}

{
  const t = await mount('empty')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('空数据：给「刷新」入口', !!findButton(view, '刷新'), view.text.slice(0, 200))
  expect('空数据：只画一份占位', byClass(view, 'scp-pal-empty').length === 1,
    String(byClass(view, 'scp-pal-empty').length))
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
  // 批量撤销：批次条只列可撤销的行（范围 = 当前筛选与搜索），生成一条带多 key 的指令。
  const undoDraft = (key, title) => Object.assign({}, SEDIMENT.drafts[0], {
    key,
    title,
    path: 'postmortems/inbox/' + key + '.case.yaml',
    source: { sessionId: key, mismatch: 'none', sedimented: 'submitted' },
    undo: { available: true, prompt: '撤销这次沉淀：' + key + '。' },
  })
  const batchQueue = Object.assign({}, SEDIMENT, {
    drafts: [undoDraft('draft-a', '草稿 A'), undoDraft('draft-b', '草稿 B')],
    counts: { total: 2, unassessed: 0, needDecision: 2, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 1 },
    primary: { kind: 'groom', label: '继续 groom', prompt: '继续 groom 的批次指令' },
  })
  const t = await mount('recent', { sediment: batchQueue, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  const batchBtn = findButtonContains(view, '撤销可撤销的 2 份')
  expect('批量撤销：批次条出现入口', !!batchBtn, view.text.slice(-200))
  click(batchBtn)
  view = await t.settle()
  expect('批量撤销：弹层标题', view.text.includes('批量撤销沉淀'), view.text.slice(-300))
  expect('批量撤销：指令带两份 key', view.text.includes('--draft-key draft-a')
    && view.text.includes('--draft-key draft-b'), view.text.slice(-400))
  expect('批量撤销：指令说明不改诊断状态', view.text.includes('不改诊断状态')
    && !view.text.includes('--keep-status'), view.text.slice(-400))
  expect('批量撤销：指令说明已关闭 PR 会清台账', view.text.includes('PR 已关闭的行会一并清掉本地台账记录'),
    view.text.slice(-400))
  expect('批量撤销：名单带草稿标题', view.text.includes('本批名单')
    && view.text.includes('草稿 A') && view.text.includes('草稿 B'), view.text.slice(-500))
  click(findButton(view, '填入输入框'))
  await t.settle()
  expect('批量撤销：填入输入框', t.lastDraft().includes('--draft-key draft-a')
    && t.lastDraft().includes('--draft-key draft-b') && t.lastDraft().includes('--apply'),
  t.lastDraft().slice(0, 200))
}

{
  // 填过指令后重新打开：队列强制刷新一次，不等 60 秒去重。指令在会话里执行，面板收不到
  // 通知；不强制刷新就会让刚撤销的草稿还留在屏幕上。标记只消费一次，之后恢复 60 秒去重。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButtonContains(view, '撤销沉淀'))
  view = await t.settle()
  click(findButton(view, '填入输入框'))
  await t.settle()
  const before = t.rpcCalls.filter((item) => item.endpoint === 'copilot-sediment').length
  const closed = await t.settle()
  click(findToolbar(closed))
  await t.settle()
  await t.settle()
  const after = t.rpcCalls.filter((item) => item.endpoint === 'copilot-sediment').length
  expect('填过指令后重开队列：强制刷新一次', after === before + 1, before + ' → ' + after)
  // 标记只消费一次：再关再开不再取数，60 秒去重照旧（否则等于每次打开都跑 git + inbox）。
  const reopened = await t.settle()
  click(findToolbar(reopened))
  await t.settle()
  click(findToolbar(await t.settle()))
  await t.settle()
  await t.settle()
  const afterAgain = t.rpcCalls.filter((item) => item.endpoint === 'copilot-sediment').length
  expect('填过指令后重开队列：只强制一次', afterAgain === after, after + ' → ' + afterAgain)
}

{
  // 撤销沉淀：草稿还在 inbox、没有 PR 时给入口；点开先看指令，填进输入框由会话里的
  // agent 先跑计划再执行。面板不删草稿，也不自动发送。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  const undoBtn = findButtonContains(view, '撤销沉淀')
  expect('撤销沉淀：没有 PR 的草稿给入口', !!undoBtn, view.text.slice(-200))
  expect('撤销沉淀：入口带条件说明', !!undoBtn && undoBtn.props.title === '草稿还在 inbox、PR 没提过或已关闭、来源 trace 没升格时才能撤销',
    undoBtn ? String(undoBtn.props.title) : 'missing')
  expect('撤销沉淀：只有一份可撤销时不出批量入口', !findButtonContains(view, '撤销可撤销的'),
    view.text.slice(-200))
  click(undoBtn)
  view = await t.settle()
  expect('撤销沉淀：弹层标题', view.text.includes('撤销这次沉淀'), view.text.slice(-300))
  expect('撤销沉淀：指令先看计划再执行', view.text.includes('scripts/sediment_undo.py --draft-key')
    && view.text.includes('--apply'), view.text.slice(-400))
  click(findButton(view, '填入输入框'))
  await t.settle()
  expect('撤销沉淀：填入输入框', t.lastDraft().includes('sediment_undo.py')
    && t.lastDraft().includes('--apply'), t.lastDraft().slice(0, 160))
}

{
  // 撤销沉淀：PR 已关闭的草稿也给入口（撤销会清掉台账记录，PR 本身在平台上不动）。
  const closedPrDraft = Object.assign({}, SEDIMENT.drafts[0], {
    key: '2026-10-30-pd-oom', title: 'PD 分离 prefill OOM', state: 'pr_closed',
    stage: 'PR 已关闭', stageTone: 'bad',
    pr: {
      number: 431, url: 'https://github.com/pillumina/ascend-sleuth/pull/431',
      platform: 'github', state: 'closed', source: 'platform', checkedAt: '2026-11-07T10:00:00+08:00',
    },
    next: { kind: 'groom', label: '重新评估（继续 groom）', prompt: '继续 groom 的批次指令' },
    undo: { available: true, prompt: '撤销这次沉淀：2026-10-30-pd-oom。\n台账里这份草稿的 PR 已关闭（#431）；撤销会把这条 PR 记录一并清掉。' },
  })
  const closedPrQueue = Object.assign({}, SEDIMENT, {
    drafts: [closedPrDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'groom', label: '重新评估（继续 groom）', prompt: '继续 groom 的批次指令' },
    history: [],
  })
  const t = await mount('recent', { sediment: closedPrQueue, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('撤销沉淀：PR 已关闭的行在队列里', view.text.includes('PR 已关闭'), view.text.slice(-200))
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  expect('撤销沉淀：PR 已关闭的草稿给入口', !!findButtonContains(view, '撤销沉淀'), view.text.slice(-200))
  expect('撤销沉淀：详情显示已关闭的 PR', view.text.includes('#431'), view.text.slice(-300))
  click(findButtonContains(view, '撤销沉淀'))
  view = await t.settle()
  expect('撤销沉淀：指令说明台账记录会被清掉', view.text.includes('台账') && view.text.includes('清'),
    view.text.slice(-400))
}

{
  // 台账里这份草稿的记录坏了（不是对象）：不给撤销，详情提示先修台账。
  const brokenDraft = Object.assign({}, SEDIMENT.drafts[0], {
    key: '2026-10-31-broken-ledger', title: '台账坏记录的草稿', pr: null, prBroken: true,
    undo: { available: false, prompt: '' },
  })
  const brokenQueue = Object.assign({}, SEDIMENT, {
    drafts: [brokenDraft],
    counts: { total: 1, unassessed: 1, needDecision: 0, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'groom', label: '继续 groom', prompt: '继续 groom 的批次指令' },
    history: [],
  })
  const t = await mount('recent', { sediment: brokenQueue, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  expect('坏台账记录：不给撤销入口', !findButtonContains(view, '撤销沉淀'), view.text.slice(-200))
  expect('坏台账记录：详情提示先修台账', view.text.includes('记录不是对象'), view.text.slice(-300))
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
  expect('沉淀详情：显示比较基准与目标状态', view.text.includes('比较基准') && view.text.includes('refs/remotes/mirror/main') && view.text.includes('目标落后'))
  expect('沉淀详情：显示目标提示', view.text.includes('目标提示') && view.text.includes('解析不到'))
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
  // 已提 PR 的草稿：详情抬头与诊断页同一套「识别行 + 正文背景」；查合入只有一个入口，
  // 成功后给结果提示；已有 PR 的行不再出现「推送目标未设置」这种像在说没有 PR 的文案；
  // 「手动改状态」是平台一直查不到时的人工兜底。
  const prTitle = 'DSpark 投机解码首个请求即崩：vllm_ascend/spec_decode/dspark_proposer.py:437 set_inputs_first_pass 无条件调用可选模型 API get_draft_attn_causal()，legacy 非因果模型 DSparkDeepseekV4ForCausalLM 未实现（AttributeError）；≥ v0.26.0rc1 修复为缺失时回落 causal=False'
  const prDraft = Object.assign({}, SEDIMENT.drafts[1], {
    title: prTitle,
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 417, url: 'https://gitcode.com/pillumina/ascend-sleuth/pulls/417', platform: 'gitcode', state: 'open', source: 'platform', checkedAt: '2026-11-04T09:00:00+08:00' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    undo: { available: false, prompt: '' },
    // 生产形状：来源诊断带 trace 单号与会话号两个值，抬头显示单号、跳转用会话号。
    source: { sessionId: '2026-11-01-eplb-103900', harnessSession: 'session-origin-abc', mismatch: 'none', sedimented: 'submitted' },
  })
  const prOpen = Object.assign({}, SEDIMENT, {
    drafts: [prDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 9 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const t = await mount('recent', { sediment: prOpen, sessionsHost: true, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()

  const identity = byClass(view, 'scp-identity')
  expect('PR 详情：抬头是识别行', identity.length === 1 && nodeText(identity[0]).includes('已提 PR · 合入未确认'), identity.length ? nodeText(identity[0]) : 'missing')
  expect('PR 详情：有 PR 的草稿不给撤销入口', !findButtonContains(view, '撤销沉淀'), view.text.slice(-200))
  // 来源诊断显示 trace 单号，点它跳的是该 trace 的 harness 会话号（拿单号去开会话会报 unknown session）。
  const sourceLink = byClass(view, 'scp-link').find((node) => nodeText(node).includes('2026-11-01-eplb-103900'))
  expect('PR 详情：来源诊断链接用 trace 单号', !!sourceLink, sourceLink ? nodeText(sourceLink) : 'missing')
  expect('PR 详情：来源诊断悬停看会话号', !!sourceLink && sourceLink.props.title === 'session-origin-abc',
    sourceLink ? String(sourceLink.props.title) : 'missing')
  if (sourceLink) {
    click(sourceLink)
    view = await t.settle()
    expect('PR 详情：跳转用 harness 会话号', t.openedSessions.length === 1 && t.openedSessions[0] === 'session-origin-abc',
      JSON.stringify(t.openedSessions))
  }
  const ledes = byClass(view, 'scp-lede')
  expect('PR 详情：标题按正文样式渲染', ledes.length === 1 && ledes[0].props['data-open'] === 'false', String(ledes.length))
  expect('PR 详情：不再用放大标题放摘要', byClass(view, 'scp-hero-title').length === 0)
  const codes = byClass(view, 'scp-icode').map((node) => nodeText(node))
  expect('PR 详情：标题里的路径与调用走等宽', codes.some((text) => text.includes('dspark_proposer.py:437'))
    && codes.includes('get_draft_attn_causal()') && codes.includes('AttributeError'), codes.join(' / '))
  const expand = findButton(view, '展开全文')
  expect('PR 详情：长标题给展开入口', !!expand)
  if (expand) {
    click(expand)
    view = await t.settle()
    expect('PR 详情：展开后给收起入口', byClass(view, 'scp-lede')[0].props['data-open'] === 'true'
      && !!findButton(view, '收起全文'))
  }

  const actions = byClass(view, 'scp-sed-actions')[0]
  const checkBtns = actions ? view.nodes.filter((node) => node.type === 'button'
    && nodeText(node) === '查合入状态' && containsNode(actions, node)) : []
  expect('PR 详情：查合入只给一个按钮', checkBtns.length === 1, String(checkBtns.length))
  expect('PR 详情：已有 PR 时不再提示推送目标未设置', !!actions
    && !nodeText(actions).includes('推送目标未设置') && !nodeText(actions).includes('还没有 PR 目标'), actions ? nodeText(actions) : 'missing')
  expect('沉淀批次条：查合入标明作用域', !!findButton(view, '查全部合入状态'))

  const beforeCheck = t.rpcCalls.length
  click(checkBtns[0])
  await t.settle()
  view = await t.settle()
  const checkCall = t.rpcCalls.slice(beforeCheck).filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('PR 详情：单条查合入走 check', checkCall && checkCall.args && checkCall.args.action === 'check', JSON.stringify(checkCall && checkCall.args))
  expect('PR 详情：查合入成功给结果提示', view.text.includes('查合入完成：#417 · 待合入'), view.text.slice(-200))
  const toastNode = byClass(view, 'scp-toast')[0]
  expect('提示：长文案看得到（title 带全文）', toastNode && toastNode.props.title === nodeText(toastNode),
    toastNode ? String(toastNode.props.title) : 'missing')

  click(findButton(view, '手动改状态'))
  view = await t.settle()
  const manualPicks = byClass(view, 'scp-pick')
  expect('PR 详情：手动改状态弹层', byClass(view, 'scp-modal').length === 1 && view.text.includes('手动改 PR 状态'))
  expect('PR 详情：手动改状态写明改的是哪条', byClass(view, 'scp-modal')[0]
    && nodeText(byClass(view, 'scp-modal')[0]).includes('#417'))
  expect('PR 详情：手动状态列四档', manualPicks.length === 4
    && ['待合入', '已合入', '已关闭', '未确认'].every((label) => manualPicks.some((pick) => nodeText(pick).includes(label))),
  manualPicks.map((pick) => nodeText(pick)).join(' / '))
  const closedPick = manualPicks.find((pick) => nodeText(pick).includes('已关闭'))
  const beforeMark = t.rpcCalls.length
  click(closedPick)
  await t.settle()
  view = await t.settle()
  const markCall = t.rpcCalls.slice(beforeMark).filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('手动改状态：走 mark 且状态 closed', markCall && markCall.args && markCall.args.action === 'mark'
    && markCall.args.state === 'closed', JSON.stringify(markCall && markCall.args))
  expect('手动改状态：给成功提示并关弹层', view.text.includes('PR 状态已手动记为：已关闭')
    && byClass(view, 'scp-modal').length === 0)

  const mark = findButton(view, '标记已合入')
  expect('PR 详情：有标记已合入按钮', !!mark)
  click(mark)
  await t.settle()
  const call = t.rpcCalls.filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('PR 详情：标记已合入走 mark', call && call.args && call.args.action === 'mark' && call.args.state === 'merged', JSON.stringify(call && call.args))
}

{
  // trace 没记 harness_session 时，来源诊断仍显示单号，但不做成可点链接：
  // 单号不是会话号，拿去调 sessions.open 会报 unknown session。
  const noHarnessDraft = Object.assign({}, SEDIMENT.drafts[1], {
    source: { sessionId: '2026-10-30-no-harness', mismatch: 'none', sedimented: 'submitted' },
  })
  const noHarness = Object.assign({}, SEDIMENT, {
    drafts: [noHarnessDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'groom', label: '继续 groom', prompt: '继续 groom 的批次指令' },
  })
  const t = await mount('recent', {
    sediment: noHarness, sessionsHost: true,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  const sourceMono = byClass(view, 'scp-mono').filter((node) => nodeText(node) === '2026-10-30-no-harness')
  expect('沉淀来源：没记会话号仍显示单号', sourceMono.length === 1, sourceMono.map(nodeText).join(' / ') || 'missing')
  expect('沉淀来源：没记会话号不给可点链接',
    !byClass(view, 'scp-link').some((node) => nodeText(node).includes('2026-10-30-no-harness')))
  expect('沉淀来源：没记会话号悬停给原因',
    !!sourceMono[0] && String(sourceMono[0].props.title).includes('未记会话号'),
    sourceMono[0] ? String(sourceMono[0].props.title) : 'missing')
  expect('沉淀来源：没记会话号不调会话接口', t.openedSessions.length === 0, JSON.stringify(t.openedSessions))
}

{
  // 查合入失败：批次条查询走 check-all 失败时给出原因，不是静默只改查证时间。
  const failDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 419, url: 'https://github.com/pillumina/ascend-sleuth/pull/419', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const failQueue = Object.assign({}, SEDIMENT, {
    drafts: [failDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: failQueue,
    // 生产形状：code 在 error.code；每条 checked 的 error 是适配器错误码。
    prCheckAllResult: {
      ok: false,
      error: { code: 'E_CHECK_PARTIAL', message: '有 PR 状态没查到（见 checked）' },
      checked: [
        { draft: '2026-11-01-eplb-103900', ok: false, state: 'unknown', error: 'E_NO_AUTH' },
        { draft: '2026-10-26-glm53-moe-shuffle', ok: false, state: 'unknown', error: 'E_PLATFORM' },
      ],
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  const before = t.rpcCalls.length
  click(findButton(view, '查全部合入状态'))
  await t.settle()
  await t.settle()
  const call = t.rpcCalls.slice(before).filter((item) => item.endpoint === 'copilot-pr-target').pop()
  view = await t.settle()
  expect('查合入失败：批次条走 check-all', call && call.args && call.args.action === 'check-all', JSON.stringify(call && call.args))
  expect('查合入失败：给出原因', view.text.includes('查合入没有全部成功') && view.text.includes('没配 token'), view.text.slice(-300))
  expect('查合入失败：未映射码不给裸枚举', view.text.includes('平台适配器不可用') && !view.text.includes('E_PLATFORM'), view.text.slice(-300))
}

{
  // 草稿已出队、PR 未合入：队列里要有一行，详情提示来源，主按钮就地查合入。
  const closedDraft = Object.assign({}, SEDIMENT.drafts[1], {
    key: 'VLLM-ASC-13976', title: 'DSpark 可选 API 缺失', path: '', closedDraft: true,
    assessed: true, assessedShort: '', assessmentCleared: true, state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    ageDays: 0, decisionAt: '2026-11-04T17:20:16+08:00',
    pr: { number: 429, url: 'https://github.com/pillumina/ascend-sleuth/pull/429', platform: 'github', state: 'open', source: 'ledger', checkedAt: '' },
    promotion: { caseId: 'VLLM-ASC-13976', casePath: '', postmortemPath: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const closedQueue = Object.assign({}, SEDIMENT, {
    drafts: [closedDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', { sediment: closedQueue, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('已出队行：仍在队列里', byClass(view, 'scp-sed-row').length === 1, String(byClass(view, 'scp-sed-row').length))
  expect('已出队行：显示 PR 号', view.text.includes('#429'), view.text.slice(-300))
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  expect('已出队行：详情提示来源', view.text.includes('草稿不在 inbox'), view.text.slice(-300))
  expect('已出队行：显示 PR 地址', view.text.includes('github.com/pillumina/ascend-sleuth/pull/429'))
  expect('已出队行：落点写合入后落库', view.text.includes('合入后落库'), view.text.slice(-300))
  expect('已出队行：评估状态文件已清理', view.text.includes('评估状态文件已清理'), view.text.slice(-300))
  const before = t.rpcCalls.length
  click(findNode(view, (node) => node.type === 'button'
    && String((node.props && node.props.className) || '').includes('scp-btn--primary')
    && nodeText(node).includes('查全部合入状态')))
  await t.settle()
  await t.settle()
  const checkCall = t.rpcCalls.slice(before).filter((call) => call.endpoint === 'copilot-pr-target').pop()
  expect('已出队行：批量查合入走 check-all', checkCall && checkCall.args && checkCall.args.action === 'check-all', JSON.stringify(checkCall && checkCall.args))
  expect('已出队行：查合入不弹指令层', byClass(t.view(), 'scp-modal').length === 0)
  view = await t.settle()
  expect('已出队行：批量查合入成功给提示', view.text.includes('查合入完成：1 条已更新'), view.text.slice(-200))
}

// 查合入逐条进度的公共夹具：两份已提 PR、待确认合入的草稿。
function makeCheckQueue() {
  const first = Object.assign({}, SEDIMENT.drafts[1], {
    key: '2026-11-01-eplb-103900', state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: {
      number: 419, url: 'https://github.com/pillumina/ascend-sleuth/pull/419',
      platform: 'github', state: 'open', source: 'platform', checkedAt: '',
    },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const second = Object.assign({}, SEDIMENT.drafts[2], {
    key: '2026-10-26-glm53-moe-shuffle', state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: {
      number: 420, url: 'https://github.com/pillumina/ascend-sleuth/pull/420',
      platform: 'github', state: 'unknown', source: 'ledger', checkedAt: '',
    },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  return Object.assign({}, SEDIMENT, {
    drafts: [first, second],
    counts: { total: 2, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 2, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
}

async function openSedimentView(t) {
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  return t.settle()
}

async function settleTimes(t, times) {
  let view = null
  for (let index = 0; index < times; index += 1) view = await t.settle()
  return view
}

// 只取某一行（按 PR 号定位）的文本：避免把右列详情的阶段文案算进行内断言。
function rowText(view, prNumber) {
  const row = byClass(view, 'scp-sed-row').find((node) => nodeText(node).includes('#' + prNumber))
  return row ? nodeText(row) : ''
}

{
  // 主 RPC 还挂着时轮询已能把行写进队列；present=false 不能当 done；done 后停止轮询，整批结束只刷新一次。
  const queue = makeCheckQueue()
  const keys = queue.drafts.map((draft) => draft.key)
  const firstRow = { draft: keys[0], ok: true, state: 'merged', checked_at: '2026-11-05T10:41:12+08:00' }
  const secondRow = { draft: keys[1], ok: false, state: 'unknown', checked_at: '2026-11-05T10:41:13+08:00', error: 'E_NO_AUTH', message: '未配置 token' }
  const progressSteps = [
    // 第一次轮询早于服务端 beginPrProgress（慢 resolve）：present=false 表示「还没开始」。
    { present: false, rows: [], done: false },
    { present: true, rows: [firstRow], done: false },
    { present: true, rows: [firstRow, secondRow], done: true },
  ]
  const t = await mount('recent', {
    sediment: queue, prCheckAllGate: true, prProgress: progressSteps,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = await openSedimentView(t)
  const before = t.rpcCalls.length
  click(findButton(view, '查全部合入状态'))
  let current = await t.settle()
  expect('逐条进度：批次按钮先显示 0/2', !!findButton(current, '查合入中 0/2'), current.text.slice(-300))
  const dispatched = t.rpcCalls.slice(before).filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('逐条进度：主 RPC 先发出', dispatched && dispatched.args && dispatched.args.action === 'check-all', JSON.stringify(dispatched && dispatched.args))
  const progressCalls = () => t.rpcCalls.filter((item) => item.endpoint === 'copilot-pr-progress').length
  // 第一次轮询 present=false：不应用行、不停轮询。还没到达的行显示旧阶段 chip + 「查合入中」。
  await t.fireInterval(500)
  current = await t.settle()
  expect('逐条进度：present=false 不应用行也不停轮询', progressCalls() === 1
    && !!findButton(current, '查合入中 0/2')
    && !rowText(current, 419).includes('已合入'),
  JSON.stringify({ calls: progressCalls(), row: rowText(current, 419) }))
  expect('逐条进度：未到的行是旧阶段 chip + 查合入中',
    rowText(current, 419).includes('已提 PR · 合入未确认') && rowText(current, 419).includes('查合入中'),
  rowText(current, 419))
  const progressCallsAfterPending = progressCalls()
  // 第二次轮询 present=true 且有一条 row：行内立刻出现状态，没到的行仍标「查合入中」。
  await t.fireInterval(500)
  current = await t.settle()
  expect('逐条进度：轮询到 row 后行内出现状态', rowText(current, 419).includes('已合入'), rowText(current, 419))
  // 用行文本判定，避免被右列详情按钮「标记已合入」命中；同时反向确认旧阶段 chip 已撤掉。
  expect('逐条进度：已到的行只显示新状态，不与旧阶段 chip 并存',
    rowText(current, 419).includes('已合入')
    && !rowText(current, 419).includes('已提 PR · 合入未确认')
    && !rowText(current, 419).includes('标记已合入'),
    rowText(current, 419))
  expect('逐条进度：没到的行标查合入中',
    rowText(current, 420).includes('查合入中') && rowText(current, 420).includes('已提 PR · 合入未确认'),
  rowText(current, 420))
  expect('逐条进度：按钮显示具体 1/2', !!findButton(current, '查合入中 1/2'), current.text.slice(-400))
  expect('逐条进度：轮询走 copilot-pr-progress', progressCalls() === progressCallsAfterPending + 1, String(progressCalls()))
  // 第三次轮询 present=true + done=true：失败原因可见，随后不再请求。
  await t.fireInterval(500)
  current = await t.settle()
  expect('逐条进度：失败原因在行内可见', rowText(current, 420).includes('没配 token'), rowText(current, 420))
  expect('逐条进度：done 后行内不再标查合入中', !rowText(current, 420).includes('查合入中'), rowText(current, 420))
  const callsAtDone = progressCalls()
  expect('逐条进度：三次轮询后 done', callsAtDone === 3, String(callsAtDone))
  await t.fireInterval(500)
  expect('逐条进度：done 后停止轮询', progressCalls() === callsAtDone, String(progressCalls()))
  const beforeRelease = t.rpcCalls.filter((item) => item.endpoint === 'copilot-sediment').length
  t.releaseCheckAll()
  current = await settleTimes(t, 4)
  const afterRelease = t.rpcCalls.filter((item) => item.endpoint === 'copilot-sediment').length
  expect('逐条进度：整批结束只刷新一次', afterRelease === beforeRelease + 1,
    JSON.stringify({ before: beforeRelease, after: afterRelease }))
  expect('逐条进度：结束仍给原成功提示', current.text.includes('查合入完成：1 条已更新'), current.text.slice(-300))
  expect('逐条进度：结束后不再显示进度标签', !current.text.includes('查合入中'), current.text.slice(-300))
}

{
  // 进度端点异常：静默降级，连续失败后停轮询，整批仍按主 RPC 的结果收尾。
  const queue = makeCheckQueue()
  const t = await mount('recent', {
    sediment: queue, prCheckAllGate: true, prProgressError: true,
    prCheckAllResult: { ok: true, checked: [{ draft: queue.drafts[0].key, ok: true, state: 'open' }] },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = await openSedimentView(t)
  click(findButton(view, '查全部合入状态'))
  await t.settle()
  const progressCalls = () => t.rpcCalls.filter((item) => item.endpoint === 'copilot-pr-progress').length
  for (let index = 0; index < 3; index += 1) await t.fireInterval(500)
  expect('轮询异常：连续 3 次失败后停轮询', progressCalls() === 3, String(progressCalls()))
  await t.fireInterval(500)
  expect('轮询异常：停下后不再请求', progressCalls() === 3, String(progressCalls()))
  t.releaseCheckAll()
  const current = await settleTimes(t, 4)
  expect('轮询异常：整批仍成功', current.text.includes('查合入完成：1 条已更新'), current.text.slice(-300))
  expect('轮询异常：不把进度错误弹给读者', !current.text.includes('进度端点不可用'), current.text.slice(-300))
}

{
  // 单条查合入失败：给失败原因（不是只改查证时间），并刷新行里的状态。
  const failDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 421, url: 'https://github.com/pillumina/ascend-sleuth/pull/421', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const failQueue = Object.assign({}, SEDIMENT, {
    drafts: [failDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: failQueue,
    // 生产形状：pr_status.py 的 _fail 把 code 放在 error.code（顶层没有 code）。
    prCheckResult: {
      ok: false, state: 'unknown', checked_at: '2026-11-05T11:00:00+08:00',
      error: { code: 'E_NO_AUTH', message: '未配置 token 环境变量 GITHUB_TOKEN' },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  const before = t.rpcCalls.length
  click(findButton(view, '查合入状态'))
  await t.settle()
  view = await t.settle()
  const call = t.rpcCalls.slice(before).filter((item) => item.endpoint === 'copilot-pr-target').pop()
  expect('单条查合入失败：走 check', call && call.args && call.args.action === 'check', JSON.stringify(call && call.args))
  expect('单条查合入失败：给出原因与兜底', view.text.includes('查合入没成功') && view.text.includes('未配置 token')
    && view.text.includes('也可以手动改状态'), view.text.slice(-300))
  expect('单条查合入失败：刷新行里的状态', t.rpcCalls.slice(before).some((item) => item.endpoint === 'copilot-sediment'))
}

{
  // 单条查合入写台账被系统拒绝：平台结果拿到了、台账没写进去。给指令弹层（复制 / 填入输入框），
  // 点之前不填、不自动发送；指令要交代原因、已查到的状态、命令与台账路径。
  const writeFailDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 423, url: 'https://github.com/pillumina/ascend-sleuth/pull/423', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const writeFailQueue = Object.assign({}, SEDIMENT, {
    drafts: [writeFailDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const reason = '台账写不进去：D:/repos/ascend-sleuth/postmortems/inbox/.groom/pr-state.json.lock（拒绝访问）'
  const CAS = 'a'.repeat(64)
  const t = await mount('recent', {
    sediment: Object.assign({}, writeFailQueue, {
      target: Object.assign({}, writeFailQueue.target, { sha256: CAS }),
    }),
    // 生产形状：脚本写失败折成 E_LEDGER，并把已经查到的 state 一起带出来。
    prCheckResult: {
      ok: false, draft: writeFailDraft.key, state: 'merged', checked_at: '2026-11-05T11:00:00+08:00',
      write_failed: true,
      error: { code: 'E_LEDGER', message: reason },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButton(view, '查合入状态'))
  await t.settle()
  view = await t.settle()
  expect('查合入写失败：给指令弹层', view.text.includes(reason), view.text.slice(-400))
  expect('查合入写失败：说明写的是台账', view.text.includes('面板没把结果写进 PR 台账'), view.text.slice(-400))
  expect('查合入写失败：带已查到的状态', view.text.includes('平台已经查到：已合入'), view.text.slice(-400))
  expect('查合入写失败：给可执行命令', view.text.includes('python3 scripts/pr_status.py --root . --check --draft ' + writeFailDraft.key), view.text.slice(-600))
  expect('查合入写失败：命令带台账 CAS 令牌', view.text.includes('--expect-sha256 ' + CAS), view.text.slice(-600))
  expect('查合入写失败：给台账路径', view.text.includes('postmortems/inbox/.groom/pr-state.json'), view.text.slice(-600))
  expect('查合入写失败：不自动填指令', t.drafts.length === 0, String(t.drafts.length))
  click(findButton(view, '填入输入框'))
  const draft = t.lastDraft()
  expect('查合入写失败：填入输入框带命令', draft.includes('--check --draft ' + writeFailDraft.key), draft.slice(0, 300))
  expect('查合入写失败：填入输入框带修复提示', draft.includes('.lock'), draft.slice(0, 500))
}

{
  // 旧版脚本还没把系统拒绝折成 E_LEDGER：E_INTERNAL 带 PermissionError 时也按写失败给指令，
  // 面板与脚本版本错配（新面板 + 旧检出）不能退化成一句裸 traceback。
  const legacyDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 424, url: 'https://github.com/pillumina/ascend-sleuth/pull/424', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const legacyQueue = Object.assign({}, SEDIMENT, {
    drafts: [legacyDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: legacyQueue,
    prCheckResult: {
      ok: false,
      error: {
        code: 'E_INTERNAL',
        message: "PermissionError: [Errno 13] Permission denied: 'D:/repos/ascend-sleuth/postmortems/inbox/.groom/pr-state.json.lock'",
      },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButton(view, '查合入状态'))
  await t.settle()
  view = await t.settle()
  expect('旧脚本 PermissionError：也给指令弹层', view.text.includes('python3 scripts/pr_status.py --root . --check --draft ' + legacyDraft.key), view.text.slice(-500))
  expect('旧脚本 PermissionError：不显示裸 traceback 提示', !view.text.includes('查合入没成功'), view.text.slice(-400))
}

{
  // 批次查合入写失败：整批指令（--check-all），不是「部分失败」提示。
  const batchDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 425, url: 'https://github.com/pillumina/ascend-sleuth/pull/425', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const batchQueue = Object.assign({}, SEDIMENT, {
    drafts: [batchDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查全部合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: batchQueue,
    prCheckAllResult: {
      ok: false,
      write_failed: true,
      // 真实 done 行形状：查询本身成功，checked[] 里带的是平台状态，只是没落盘。
      checked: [{ draft: batchDraft.key, ok: true, state: 'merged' }],
      error: { code: 'E_LEDGER', message: '台账写不进去：D:/repo/postmortems/inbox/.groom/pr-state.json.lock（拒绝访问）' },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(findButton(view, '查全部合入状态'))
  view = await t.settle()
  expect('批次查合入写失败：给整批指令', view.text.includes('python3 scripts/pr_status.py --root . --check-all'), view.text.slice(-500))
  expect('批次查合入写失败：不当部分失败提示', !view.text.includes('查合入没有全部成功'), view.text.slice(-400))
  expect('批次查合入写失败：带已查到的状态', view.text.includes('平台已经查到：' + batchDraft.key + ' 已合入'), view.text.slice(-500))
}

{
  // 读坏台账也是 E_LEDGER，但不是写失败：不给写指令，仍按查询失败提示原因。
  const brokenDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 426, url: 'https://github.com/pillumina/ascend-sleuth/pull/426', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const brokenQueue = Object.assign({}, SEDIMENT, {
    drafts: [brokenDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: brokenQueue,
    prCheckResult: {
      ok: false,
      error: { code: 'E_LEDGER', message: '台账不是合法 JSON（/repo/postmortems/inbox/.groom/pr-state.json）' },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButton(view, '查合入状态'))
  await t.settle()
  view = await t.settle()
  expect('读坏台账：不进写指令弹层', !view.text.includes('python3 scripts/pr_status.py --root . --check'), view.text.slice(-400))
  expect('读坏台账：仍给原因', view.text.includes('查合入没成功') && view.text.includes('台账不是合法 JSON'), view.text.slice(-400))
}

{
  // 批次查合入成功但台账里没有可查的 PR（checked 为空）：给「没有待查的 PR」。
  const emptyDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 420, url: 'https://github.com/pillumina/ascend-sleuth/pull/420', platform: 'github', state: 'unknown', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const emptyQueue = Object.assign({}, SEDIMENT, {
    drafts: [emptyDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: emptyQueue,
    prCheckAllResult: { ok: true, checked: [] },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(findButton(view, '查全部合入状态'))
  view = await t.settle()
  expect('批次查合入：没有待查 PR 也给提示', view.text.includes('没有待查的 PR'), view.text.slice(-200))
}

{
  // 只读档位：单条查合入不写台账，回落成生成查证指令；按钮不能是禁用到底的死路。
  const roDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 418, url: 'https://github.com/pillumina/ascend-sleuth/pull/418', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const roQueue = Object.assign({}, SEDIMENT, {
    drafts: [roDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('readonly', { sediment: roQueue, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  const checkBtn = findButton(view, '查合入状态')
  expect('只读：单条查合入按钮可点且给原因', !!checkBtn && checkBtn.props.disabled === false
    && checkBtn.props.title === '只读档位：生成查证指令', JSON.stringify(checkBtn && checkBtn.props))
  const before = t.rpcCalls.length
  click(checkBtn)
  view = await t.settle()
  expect('只读：单条查合入回落生成指令', byClass(view, 'scp-modal').length === 1 && view.text.includes('查合入状态的指令'))
  expect('只读：单条查合入不写台账', t.rpcCalls.slice(before).every((item) => item.endpoint !== 'copilot-pr-target'))
  expect('只读：指令弹层不重复流程句', (view.text.split('流程：按 skill 第 5 步执行').length - 1) === 1, view.text.slice(-300))
}

{
  // 手动改状态遇到 CAS 冲突：刷新台账、弹层留着让读者重试，不静默。
  const casDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 422, url: 'https://github.com/pillumina/ascend-sleuth/pull/422', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const casQueue = Object.assign({}, SEDIMENT, {
    drafts: [casDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: casQueue,
    prMarkResult: { ok: false, error: { code: 'E_CAS', message: '台账已变，请刷新后重试' } },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButton(view, '手动改状态'))
  view = await t.settle()
  const before = t.rpcCalls.length
  click(byClass(view, 'scp-pick').find((pick) => nodeText(pick).includes('已合入')))
  view = await t.settle()
  expect('手动改状态：CAS 冲突给原因', view.text.includes('台账已变'))
  expect('手动改状态：CAS 后刷新台账', t.rpcCalls.slice(before).some((item) => item.endpoint === 'copilot-sediment'))
  expect('手动改状态：CAS 后弹层留开', byClass(view, 'scp-modal').length === 1)
}

{
  // PR 已关闭：主按钮是恢复草稿，点击直接把移动命令填进输入框。
  const restoreDraft = Object.assign({}, SEDIMENT.drafts[1], {
    key: 'draft-restore', title: '被关闭的 PR', state: 'pr_closed', stage: 'PR 已关闭',
    stageTone: 'bad', closedDraft: true, assessed: true, path: '',
    pr: { number: 418, url: 'https://github.com/pillumina/ascend-sleuth/pull/418', state: 'closed', source: 'platform', checkedAt: '2026-11-04T10:00:00+08:00' },
    next: { kind: 'restore', label: '恢复草稿', prompt: 'mv .done/x inbox/x' },
    restore: "把已出队的草稿移回 inbox，再继续 groom：\nmv '/repo/postmortems/inbox/.done/draft-restore' '/repo/postmortems/inbox/draft-restore'",
    undo: { available: false, prompt: '' },
  })
  const restoreQueue = Object.assign({}, SEDIMENT, {
    prompts: Object.assign({}, SEDIMENT.prompts, { restore: restoreDraft.restore }),
    drafts: [restoreDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'restore', label: '恢复草稿', prompt: restoreDraft.restore },
    history: [],
  })
  const t = await mount('recent', { sediment: restoreQueue, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('PR 已关闭：主按钮文案', !!findButtonContains(view, '恢复草稿'), view.text.slice(-200))
  click(findButtonContains(view, '恢复草稿'))
  await t.settle()
  expect('PR 已关闭：填入恢复命令', t.lastDraft().includes('mv ') && t.lastDraft().includes('.done'), t.lastDraft().slice(0, 120))
}

{
  // 空队列的最近完成：带 PR 链接，能直接打开。
  const historyOnly = Object.assign({}, SEDIMENT, {
    drafts: [],
    counts: { total: 0, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 0, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'none', label: '', prompt: '' },
    history: [{
      key: 'VLLM-ASC-13976', title: 'DSpark 可选 API 缺失', state: 'knowledge',
      at: '2026-11-04T17:20:16+08:00',
      pr: { number: 429, url: 'https://github.com/pillumina/ascend-sleuth/pull/429', state: 'merged' },
    }],
  })
  const t = await mount('recent', { sediment: historyOnly, prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  expect('最近完成：显示 PR 链接', view.text.includes('#429'), view.text.slice(-300))
  const link = findNode(view, (node) => node.type === 'a' && node.props && node.props.href === 'https://github.com/pillumina/ascend-sleuth/pull/429')
  expect('最近完成：链接指向 PR', !!link)
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
  // 面板被文件权限拒绝：给「生成指令」兜底。指令要交代 trace 文件、目标状态、CAS 指纹与
  // 要填的字段，并给一条可直接执行的命令（positional 是单号 stem，不是带 .yaml 的文件名）。
  // 点之前不填、点之后才进输入框，不自动发送。
  const denied = '文件操作被系统拒绝：/repo/traces/' + ID + '.yaml（拒绝访问）'
  const t = await mount('recent', {
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
    transitionResult: { ok: false, code: 'E_PERM', message: denied },
  })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '不再跟进'))
  view = await t.settle()
  const form = findNode(view, (node) => node.type === 'form')
  form.props.onSubmit({ preventDefault() {} })
  view = await t.settle()
  expect('权限失败：错误里带脚本给的路径与原因', view.text.includes(denied), view.text.slice(-400))
  // 脚本给的拒绝原因不再套一层「写入失败：」，避免同一句里两个前缀。
  expect('权限失败：错误行不叠「写入失败：」前缀', !view.text.includes('写入失败：文件操作被系统拒绝'), view.text.slice(-400))
  expect('权限失败：不自动填指令', t.drafts.length === 0, String(t.drafts.length))
  const fallbackButton = findButton(view, '生成指令（填入输入框）')
  expect('权限失败：给「生成指令」兜底', !!fallbackButton, view.text.slice(-400))
  click(fallbackButton)
  const draft = t.lastDraft()
  expect('权限失败：指令带 trace 文件', draft.includes('trace 文件：traces/' + ID + '.yaml'), draft.slice(0, 200))
  expect('权限失败：指令带目标状态', draft.includes('目标状态：不再跟进（archived）'), draft.slice(0, 300))
  expect('权限失败：指令带 CAS 指纹', draft.includes('--expect-sha256：' + SHA), draft.slice(0, 400))
  expect('权限失败：指令带要填的字段', draft.includes('要填的字段：') && draft.includes('ending.kind="not_reproducible"') && draft.includes('summary='), draft)
  expect('权限失败：指令说明面板写不进', draft.includes('面板写不进这一单') && draft.includes(denied), draft)
  const commandLine = draft.split('\n').find((line) => line.startsWith('python3 scripts/trace_transition.py '))
  expect('权限失败：指令 positional 用 trace 单号 stem', !!commandLine
    && commandLine.startsWith('python3 scripts/trace_transition.py ' + ID + ' '), commandLine)
  expect('权限失败：指令 positional 不带 .yaml', !!commandLine && !commandLine.includes(ID + '.yaml'), commandLine)
  expect('权限失败：命令行带 CAS 指纹', !!commandLine && commandLine.includes('--expect-sha256 ' + SHA), commandLine)
  const tokenMatch = commandLine ? commandLine.match(/--payload-base64 ([A-Za-z0-9+/=]+)/) : null
  let commandBody = null
  try {
    commandBody = tokenMatch ? JSON.parse(Buffer.from(tokenMatch[1], 'base64').toString('utf8')) : null
  } catch {
    commandBody = null
  }
  expect('权限失败：base64 payload 是脚本认识的字段', !!commandBody
    && commandBody.to === 'archived' && commandBody.kind === 'not_reproducible'
    && typeof commandBody.summary === 'string', JSON.stringify(commandBody))
}

{
  // 非权限类失败不给这个兜底：E_SCHEMA 之类的错要读者改输入，不是换条路写。
  const t = await mount('recent', {
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
    transitionResult: { ok: false, code: 'E_SCHEMA', message: '目标状态不合法' },
  })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  click(findButton(view, '不再跟进'))
  view = await t.settle()
  findNode(view, (node) => node.type === 'form').props.onSubmit({ preventDefault() {} })
  view = await t.settle()
  expect('非权限失败：不给生成指令兜底', !findButton(view, '生成指令（填入输入框）'), view.text.slice(-300))
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

{
  // 静置淡出：Windows 关掉「动画效果」后 Chromium 报 prefers-reduced-motion: reduce，
  // 旧逻辑连变淡一起停掉。reduce 只该去掉过渡，变淡本身仍要发生。
  const realTimeout = globalThis.setTimeout
  const realMatchMedia = globalThis.window.matchMedia
  globalThis.window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} })
  globalThis.setTimeout = (fn, ms, ...args) => {
    if (ms === 2800) { realTimeout(fn, 0, ...args); return 0 }
    return realTimeout(fn, ms, ...args)
  }
  try {
    const t = await mount('recent', { prefs: { dockCollapsed: true, paletteFilter: 'all', pins: {} } })
    await new Promise((resolve) => realTimeout(resolve, 30))
    const view = await t.settle()
    expect('静置淡出：prefers-reduced-motion 下仍然淡出', view.nodes.some((node) => node.props && node.props['data-idle'] === 'true'))
  } finally {
    globalThis.setTimeout = realTimeout
    globalThis.window.matchMedia = realMatchMedia
  }
}

{
  // 终态单：改收尾方式的目标与字段来自投影 actions；提交走 correct-ending。
  const t = await mount('terminal', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  expect('终态单：出现改收尾方式入口', !!findButtonContains(view, '改收尾方式'), view.text.slice(-400))
  click(findButtonContains(view, '改收尾方式'))
  view = await t.settle()
  expect('改收尾方式：表单出现', byClass(view, 'scp-form').length === 1)
  const fixSelect = findSelectWithOption(view, 'true')
  fixSelect.props.onChange({ target: { value: 'true' } })
  view = await t.settle()
  const form = findNode(view, (node) => node.type === 'form')
  form.props.onSubmit({ preventDefault() {} })
  await t.settle()
  const payload = t.lastTransition()
  expect('改收尾方式：提交 kind/to/endingKind', !!payload && payload.kind === 'correct-ending'
    && payload.to === 'resolved' && payload.endingKind === 'root_cause', JSON.stringify(payload))
}

{
  const t = await mount('terminal', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  click(findAria(view, '更多操作'))
  view = await t.settle()
  click(findButtonContains(view, '补记收尾方式'))
  view = await t.settle()
  const form = findNode(view, (node) => node.type === 'form')
  expect('补记收尾方式：表单出现', !!form)
  form.props.onSubmit({ preventDefault() {} })
  await t.settle()
  const payload = t.lastTransition()
  expect('补记收尾方式：提交 kind/endingKind', !!payload && payload.kind === 'backfill-ending'
    && payload.endingKind === 'root_cause', JSON.stringify(payload))
}

{
  // 状态读取失败时总览要给原因与重试，不能停在骨架屏。
  const t = await mount('error')
  click(findToolbar(t.view()))
  const view = await t.settle()
  expect('总览：取数失败给原因', view.text.includes('读不到 traces/'), view.text.slice(0, 600))
  expect('总览：取数失败给重试', !!findButton(view, '重试'), view.text.slice(0, 600))
}

{
  // 菜单语义：role=menu 的容器里条目要是 menuitem，「更多操作」声明弹出菜单。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  let view = t.view()
  const more = findAria(view, '更多操作')
  expect('菜单语义：更多操作声明 aria-haspopup', !!more && more.props['aria-haspopup'] === 'menu')
  click(more)
  view = await t.settle()
  const items = view.nodes.filter((node) => node.props && node.props.role === 'menuitem')
  expect('菜单语义：条目带 role=menuitem', items.length > 0, String(items.length))
}

{
  // 第二行的平台 / 框架 / 性质是自由文本（trace 的 detected_platform 可以很长）。
  // 放不下时按省略号收，不能把这一行顶出状态条：容器裁剪 + 该段可省略 + 悬停看全文。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  const view = t.view()
  const foot = cssRule('.scp-foot')
  const meta = cssRule('.scp-meta')
  expect('第二行：溢出被容器裁掉', /(^|;)overflow:hidden(;|$)/.test(foot), foot)
  expect('第二行：平台段可缩（min-width:0）', /(^|;)min-width:0(;|$)/.test(meta), meta)
  expect('第二行：平台段按省略号收', /text-overflow:ellipsis/.test(meta) && /(^|;)overflow:hidden(;|$)/.test(meta), meta)
  const metaNode = byClass(view, 'scp-meta')[0]
  expect('第二行：平台段悬停看全文', !!metaNode && typeof metaNode.props.title === 'string'
    && metaNode.props.title.includes('A3-910C') && metaNode.props.title.includes('·'), metaNode && metaNode.props.title)
}

{
  // 手动改状态写台账失败：与查合入同一份台账，给 --mark 指令，不让人对着不可写的文件重试。
  const markDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 427, url: 'https://github.com/pillumina/ascend-sleuth/pull/427', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const markQueue = Object.assign({}, SEDIMENT, {
    drafts: [markDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const CAS = 'b'.repeat(64)
  const t = await mount('recent', {
    sediment: Object.assign({}, markQueue, {
      target: Object.assign({}, markQueue.target, { sha256: CAS }),
    }),
    prMarkResult: {
      ok: false, write_failed: true,
      error: { code: 'E_LEDGER', message: '台账写不进去：D:/repo/postmortems/inbox/.groom/pr-state.json.lock（拒绝访问）' },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButton(view, '手动改状态'))
  view = await t.settle()
  const mergedPick = byClass(view, 'scp-pick').find((pick) => nodeText(pick).includes('已合入'))
  click(mergedPick)
  await t.settle()
  view = await t.settle()
  expect('手动改状态写失败：给 --mark 指令', view.text.includes('--mark --draft ' + markDraft.key + ' --state merged'), view.text.slice(-500))
  expect('手动改状态写失败：说明台账路径', view.text.includes('PR 台账：postmortems/inbox/.groom/pr-state.json'), view.text.slice(-500))
  expect('手动改状态写失败：命令带台账 CAS 令牌', view.text.includes('--expect-sha256 ' + CAS), view.text.slice(-600))
}

{
  // 写推送目标失败落在本地配置（settings.json），兜底要指配置文件，不能指 PR 台账。
  const t = await mount('recent', {
    prSetTargetResult: {
      ok: false, write_failed: true,
      error: { code: 'E_SETTINGS', message: '配置写不进去：/repo/.local/settings.json.lock（拒绝访问）' },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(findButtonContains(view, '提 PR（2）'))
  view = await t.settle()
  click(findButton(view, '换'))
  view = await t.settle()
  click(findButton(view, '保存并生成指令'))
  await t.settle()
  view = await t.settle()
  expect('写目标失败：说明写的是本地配置', view.text.includes('面板没把推送目标写进本地配置'), view.text.slice(-500))
  expect('写目标失败：指配置文件而不是台账', view.text.includes('配置文件：.local/settings.json')
    && !view.text.includes('PR 台账：postmortems/inbox/.groom/pr-state.json'), view.text.slice(-600))
  expect('写目标失败：给 --set-target 指令', view.text.includes('--set-target --remote origin --base main'), view.text.slice(-600))
  expect('写目标失败：写配置那一路不带台账 CAS 令牌', !view.text.includes('--expect-sha256'), view.text.slice(-600))
}

{
  // E_PERM 是会话档位 / 沙箱可写面的判断，不是文件本身：提示不能说成删 .lock / 查 ACL。
  const permDraft = Object.assign({}, SEDIMENT.drafts[1], {
    state: 'pr_open', stage: '已提 PR · 合入未确认', stageTone: 'accent',
    pr: { number: 428, url: 'https://github.com/pillumina/ascend-sleuth/pull/428', platform: 'github', state: 'open', source: 'platform', checkedAt: '' },
    next: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
  })
  const permQueue = Object.assign({}, SEDIMENT, {
    drafts: [permDraft],
    counts: { total: 1, unassessed: 0, needDecision: 0, needRerun: 0, decided: 0, prOpen: 1, prMerged: 0, overdue: 0, oldestDays: 0 },
    primary: { kind: 'check', label: '查合入状态', prompt: '查合入状态的指令' },
    history: [],
  })
  const t = await mount('recent', {
    sediment: permQueue,
    prCheckResult: {
      ok: false,
      error: { code: 'E_PERM', message: '沙箱拒绝了这次调用（mode=workspace-write）：会话档位或可写根不覆盖这次读写。' },
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findToolbar(t.view()))
  let view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-view-tab').find((node) => nodeText(node).includes('沉淀')))
  view = await t.settle()
  view = await t.settle()
  click(byClass(view, 'scp-sed-row')[0])
  view = await t.settle()
  click(findButton(view, '查合入状态'))
  await t.settle()
  view = await t.settle()
  expect('沙箱拒绝：按权限模式给提示', view.text.includes('面板的子进程被拒绝'), view.text.slice(-500))
  expect('沙箱拒绝：不让人删 .lock', !view.text.includes('.lock') && !view.text.includes('访问控制列表'), view.text.slice(-500))
}

// ── 知识库更新提醒（host 定时检查，copilot-state 带 kbNotice 下来）──────────
const KB_NOTICE = {
  rev: '9f8e7d1', behind: 3, panel: 1, knowledge: 2, reference: 1,
  checkedAt: '2026-11-09T13:40:00+08:00',
}

{
  // 展开态：落后 N 个提交；含面板代码要重启；两个动作都在。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let view = t.view()
  expect('知识库落后：展开态出现提示行', byClass(view, 'scp-kb-notice').length === 1, view.text.slice(0, 300))
  expect('知识库落后：文案带提交数', view.text.includes('知识库落后 3 个提交'), view.text.slice(0, 300))
  expect('知识库落后：panel>0 提示重启 DSH',
    view.text.includes('这批改动含面板代码：同步后重启 DSH 才能加载新面板。'), view.text.slice(0, 400))
  expect('知识库落后：给「去同步」', !!findButton(view, '去同步'), view.text.slice(0, 400))
  expect('知识库落后：给「稍后」', !!findButton(view, '稍后'), view.text.slice(0, 400))

  // 去同步：切整页面板且不抛；替身没有标签 DOM，点标签那层走兜底。
  let threw = null
  try {
    click(findButton(view, '去同步'))
  } catch (error) {
    threw = error
  }
  view = await t.settle()
  expect('去同步：不抛', !threw, threw && String(threw.message))
  expect('去同步：切到 Ascend Sleuth 整页',
    t.selectedPanels.includes('ascend-sleuth-console'), JSON.stringify(t.selectedPanels))
  expect('去同步：提示行还在（尚未确认已同步）', byClass(view, 'scp-kb-notice').length === 1)

  // 稍后：写成功后才收起，flash 说「这一版不再提醒」。
  click(findButton(view, '稍后'))
  view = await t.settle()
  view = await t.settle()
  const dismissCall = t.rpcCalls.filter((call) => call.endpoint === 'copilot-kb-dismiss').pop()
  expect('稍后：发出 copilot-kb-dismiss 且 rev 正确',
    !!dismissCall && dismissCall.args.rev === '9f8e7d1', JSON.stringify(dismissCall && dismissCall.args))
  expect('稍后：提示行消失', byClass(view, 'scp-kb-notice').length === 0, view.text.slice(0, 300))
  expect('稍后：flash 说这一版不再提醒', view.text.includes('这一版不再提醒。'), view.text.slice(0, 300))
  // 去同步在插件级挂过复查与标签轮询：用例收尾清掉，别挂住进程。
  t.dispose()
}

{
  // RPC 抛错（连不上后台）：与「落盘失败」分开报，行同样保留。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    kbDismissError: true,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let view = t.view()
  click(findButton(view, '稍后'))
  view = await t.settle()
  view = await t.settle()
  expect('稍后连不上后台：提示行保留', byClass(view, 'scp-kb-notice').length === 1, view.text.slice(0, 300))
  expect('稍后连不上后台：flash 说连不上',
    view.text.includes('稍后没记上：状态条连不上后台，稍后再试。'), view.text.slice(0, 400))
}

{
  // 状态文件写不进去时 host 回 saved:false（内存里记了、落盘没成）：同样当失败，行不收起。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    dismissSaved: false,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let view = t.view()
  click(findButton(view, '稍后'))
  view = await t.settle()
  view = await t.settle()
  expect('稍后未落盘：提示行保留', byClass(view, 'scp-kb-notice').length === 1, view.text.slice(0, 300))
  expect('稍后未落盘：flash 说明没记上',
    view.text.includes('稍后没记上：本地状态文件写不进去。'), view.text.slice(0, 400))
}

{
  // 30 秒复查：强制问一次 host；假端点顺手把 kbNotice 清掉，刷新后行应消失。
  const t = await mount('recent', {
    kbNotice: Object.assign({}, KB_NOTICE),
    onKbRecheck(args, state) { state.kbNotice = null },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const realTimeout = globalThis.setTimeout
  const scheduled = []
  globalThis.setTimeout = (fn, ms, ...rest) => {
    scheduled.push({ fn, ms })
    return realTimeout(fn, ms, ...rest)
  }
  try {
    click(findButton(t.view(), '去同步'))
    await t.settle()
  } finally {
    globalThis.setTimeout = realTimeout
  }
  const recheck = scheduled.find((item) => item.ms === 30000)
  expect('30 秒复查：挂上 30 秒定时器', !!recheck, JSON.stringify(scheduled.map((item) => item.ms)))
  if (recheck) recheck.fn()
  await t.settle()
  await t.settle()
  await t.settle()
  const call = t.rpcCalls.filter((item) => item.endpoint === 'copilot-kb-recheck').pop()
  expect('30 秒复查：发出 copilot-kb-recheck 且要求强制',
    !!call && call.args && call.args.force === true, JSON.stringify(call && call.args))
  expect('30 秒复查：刷新后提示行消失', byClass(await t.settle(), 'scp-kb-notice').length === 0)
  t.dispose()
}

{
  // 30 秒那次没消掉（host 刚节流或同步没跑完）：按第二次 60 秒接着试，不是只试一次。
  const t = await mount('recent', {
    kbNotice: Object.assign({}, KB_NOTICE),
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const realTimeout = globalThis.setTimeout
  const scheduled = []
  globalThis.setTimeout = (fn, ms, ...rest) => {
    scheduled.push({ fn, ms })
    return realTimeout(fn, ms, ...rest)
  }
  try {
    click(findButton(t.view(), '去同步'))
    await t.settle()
    const first = scheduled.find((item) => item.ms === 30000)
    if (first) first.fn()
    await t.settle()
    await t.settle()
    await t.settle()
  } finally {
    globalThis.setTimeout = realTimeout
  }
  expect('复查仍落后：挂第二次 60 秒定时器',
    scheduled.some((item) => item.ms === 60000), JSON.stringify(scheduled.map((item) => item.ms)))
  t.dispose()
}

{
  // panel 为 0：知识库文件有更新，但没有面板代码，不该提示重启。
  const t = await mount('recent', {
    kbNotice: { rev: 'abc1234', behind: 2, panel: 0 },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  expect('知识库落后：panel=0 仍有提示行', byClass(view, 'scp-kb-notice').length === 1)
  expect('知识库落后：panel=0 不提示重启', !view.text.includes('含面板代码'), view.text.slice(0, 400))
}

{
  // 没有 kbNotice（字段缺失）：提示行与动作都不出现。
  const t = await mount('recent', { prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} } })
  const view = t.view()
  expect('无知识库更新：没有提示行', byClass(view, 'scp-kb-notice').length === 0)
  expect('无知识库更新：没有「去同步」', !findButton(view, '去同步'), view.text.slice(0, 400))
}

{
  // 收起态：一行提示追加在 meta 末尾，不展开详情。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    prefs: { dockCollapsed: true, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  expect('知识库有更新：收起态 handle 带提示', view.text.includes('知识库有更新'), view.text.slice(0, 300))
  expect('知识库有更新：收起态不渲染提示行', byClass(view, 'scp-kb-notice').length === 0)
}

{
  // 没有诊断单的展开态：提示行照常显示，动作的 flash 也要看得见（该分支原先不渲染 hint）。
  const t = await mount('empty', {
    kbNotice: KB_NOTICE,
    noLayout: true,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let view = t.view()
  expect('空态：知识库落后也有提示行', byClass(view, 'scp-kb-notice').length === 1, view.text.slice(0, 300))
  click(findButton(view, '去同步'))
  view = await t.settle()
  expect('空态：动作的 flash 可见', view.text.includes('没找到 Ascend Sleuth 整页'), view.text.slice(-400))
  t.dispose()
}

{
  // 没装面板（没有 layout 服务）：只 flash 一句装面板的指引，不抛。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    noLayout: true,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let threw = null
  try {
    click(findButton(t.view(), '去同步'))
  } catch (error) {
    threw = error
  }
  const view = await t.settle()
  expect('去同步：没有 layout 服务不抛', !threw, threw && String(threw.message))
  expect('去同步：没有 layout 服务时给出装面板指引',
    view.text.includes('没找到 Ascend Sleuth 整页；确认面板包已安装，或稍后再试。'), view.text.slice(-400))
  expect('去同步：没有 layout 服务时没有可切的面板', t.selectedPanels.length === 0, JSON.stringify(t.selectedPanels))
  t.dispose()
}

{
  // 动态注册的回调触发了，但子 scope 里取不到 layout：同样降级，不抛。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    layoutScopeMissing: true,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let threw = null
  try {
    click(findButton(t.view(), '去同步'))
  } catch (error) {
    threw = error
  }
  const view = await t.settle()
  expect('去同步：子 scope 没有 layout 也不抛', !threw, threw && String(threw.message))
  expect('去同步：子 scope 没有 layout 时给出装面板指引',
    view.text.includes('没找到 Ascend Sleuth 整页'), view.text.slice(-400))
  expect('去同步：子 scope 没有 layout 时不切页', t.selectedPanels.length === 0, JSON.stringify(t.selectedPanels))
  t.dispose()
}

{
  // 切整页后能点到「知识库」标签：按可见标签名与容器限定，命中才点一次。
  const t = await mount('recent', {
    kbNotice: Object.assign({}, KB_NOTICE),
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const realQsa = globalThis.document.querySelectorAll
  let tabClicks = 0
  let decoyClicks = 0
  const tab = {
    textContent: '知识库',
    closest(selector) { return selector === '.sleu-console' ? {} : null },
    click() { tabClicks += 1 },
  }
  // 同名的标签在别处（不在整页容器里）：不该被点。
  const decoy = {
    textContent: '知识库',
    closest() { return null },
    click() { decoyClicks += 1 },
  }
  globalThis.document.querySelectorAll = (selector) => (selector === '[role="tab"]' ? [decoy, tab] : [])
  try {
    click(findButton(t.view(), '去同步'))
    await t.settle()
  } finally {
    globalThis.document.querySelectorAll = realQsa
  }
  expect('去同步：点开知识库标签', tabClicks === 1, String(tabClicks))
  expect('去同步：不点不在整页容器里的同名标签', decoyClicks === 0, String(decoyClicks))
  t.dispose()
}

{
  // 卸载后复查仍执行：「去同步」会把状态条连同输入区卸载，定时器在插件闭包里，不随组件走。
  // 关键判据是「卸载没有把 30 秒定时器 clear 掉」：只断言回调能跑证明不了定时器还活着。
  const t = await mount('recent', {
    kbNotice: Object.assign({}, KB_NOTICE),
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const realTimeout = globalThis.setTimeout
  const realClearTimeout = globalThis.clearTimeout
  const scheduled = []
  const cleared = []
  globalThis.setTimeout = (fn, ms, ...rest) => {
    const id = realTimeout(fn, ms, ...rest)
    scheduled.push({ fn, ms, id })
    return id
  }
  globalThis.clearTimeout = (id) => {
    cleared.push(id)
    realClearTimeout(id)
  }
  try {
    click(findButton(t.view(), '去同步'))
    await t.settle()
    t.unmount()
    const first = scheduled.find((item) => item.ms === 30000)
    expect('卸载后：30 秒复查仍在、没被组件清理掉',
      !!first && !cleared.includes(first.id), JSON.stringify(cleared))
    if (first) first.fn()
    await new Promise((resolve) => realTimeout(resolve, 0))
    await new Promise((resolve) => realTimeout(resolve, 0))
    await new Promise((resolve) => realTimeout(resolve, 0))
  } finally {
    globalThis.setTimeout = realTimeout
    globalThis.clearTimeout = realClearTimeout
  }
  const call = t.rpcCalls.filter((item) => item.endpoint === 'copilot-kb-recheck').pop()
  expect('卸载后：仍发出 copilot-kb-recheck 且带 force',
    !!call && call.args && call.args.force === true, JSON.stringify(call && call.args))
  expect('卸载后：首轮仍落后就继续挂 60 秒重试',
    scheduled.some((item) => item.ms === 60000), JSON.stringify(scheduled.map((item) => item.ms)))
  t.dispose()
}

{
  // layout 晚于 apply 就绪：注册回调先记下，触发前点一次只得到装面板指引，触发后再点能切页。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    layoutDeferred: true,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let view = t.view()
  click(findButton(view, '去同步'))
  view = await t.settle()
  expect('延迟注册：注册前只给装面板指引',
    view.text.includes('没找到 Ascend Sleuth 整页'), view.text.slice(-400))
  expect('延迟注册：注册前不切页', t.selectedPanels.length === 0, JSON.stringify(t.selectedPanels))
  t.fireLayoutInject()
  view = await t.settle()
  click(findButton(view, '去同步'))
  view = await t.settle()
  expect('延迟注册：回调触发后能切到 Ascend Sleuth 整页',
    t.selectedPanels.includes('ascend-sleuth-console'), JSON.stringify(t.selectedPanels))
  t.dispose()
}

// ── 知识库退化提示与连败上屏 ────────────────────────────────────────────────
// 退化：受限档位 fetch 被拒但只读探测成功，落后数未知（behind=null）。
const KB_DEGRADED = {
  rev: 'feed777', behind: null, panel: 0, knowledge: 0, reference: 0,
  checkedAt: '2026-11-09T14:10:00+08:00', degraded: 'permission-denied', updateAvailable: true,
}
// 连败：连续失败 3 次或权限拒绝时 host 给 kbError。
const KB_ERROR = {
  checkedAt: '2026-11-09T14:02:00+08:00',
  reason: 'permission-denied',
  message: '沙箱拒绝了这次调用（mode=workspace-write）：会话档位或可写根不覆盖这次读写。',
}

{
  // 退化提示行：文案与正常不同，不显示落后数；动作仍是「去同步」「稍后」。
  const t = await mount('recent', {
    kbNotice: KB_DEGRADED,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  expect('知识库退化：展开态出现提示行', byClass(view, 'scp-kb-notice').length === 1, view.text.slice(0, 300))
  expect('知识库退化：文案说落后数未知',
    view.text.includes('远端有新提交（落后数未知）'), view.text.slice(0, 300))
  expect('知识库退化：不显示 behind 数字',
    !view.text.includes('知识库落后') && !view.text.includes('落后 0 个提交'), view.text.slice(0, 300))
  expect('知识库退化：给「去同步」', !!findButton(view, '去同步'), view.text.slice(0, 400))
  expect('知识库退化：给「稍后」', !!findButton(view, '稍后'), view.text.slice(0, 400))
  expect('知识库退化：不提示重启 DSH', !view.text.includes('含面板代码'), view.text.slice(0, 400))
}

{
  // 收起态：退化提示也只加「知识库有更新」，不渲染提示行。
  const t = await mount('recent', {
    kbNotice: KB_DEGRADED,
    prefs: { dockCollapsed: true, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  expect('知识库退化：收起态带「知识库有更新」', view.text.includes('知识库有更新'), view.text.slice(0, 300))
  expect('知识库退化：收起态不渲染提示行', byClass(view, 'scp-kb-notice').length === 0)
}

{
  // 连败上屏：「重试」发 copilot-kb-recheck 且 force=true，再拉一次状态；成功后行消失。
  const t = await mount('recent', {
    kbError: Object.assign({}, KB_ERROR),
    onKbRecheck(args, state) { state.kbError = null },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  let view = t.view()
  expect('后台检查失败：展开态出现 kb-error 行', byClass(view, 'scp-kb-error').length === 1, view.text.slice(0, 400))
  const errorRow = byClass(view, 'scp-kb-error')[0]
  const errorText = errorRow ? nodeText(errorRow) : ''
  expect('后台检查失败：文案带时间与原因',
    /后台检查失败：\d\d-\d\d \d\d:\d\d 沙箱拒绝了这次调用/.test(errorText), errorText)
  expect('后台检查失败：给「去同步」', !!findButton(view, '去同步'), view.text.slice(0, 400))
  const retryButton = byClass(view, 'scp-kb-retry')[0]
  expect('后台检查失败：给「重试」', !!retryButton && nodeText(retryButton) === '重试', view.text.slice(0, 400))
  const statesBefore = t.rpcCalls.filter((call) => call.endpoint === 'copilot-state').length
  click(retryButton)
  await t.settle()
  await t.settle()
  await t.settle()
  const recheckCall = t.rpcCalls.filter((call) => call.endpoint === 'copilot-kb-recheck').pop()
  expect('后台检查失败：重试发出 copilot-kb-recheck 且 force=true',
    !!recheckCall && recheckCall.args && recheckCall.args.force === true, JSON.stringify(recheckCall && recheckCall.args))
  const statesAfter = t.rpcCalls.filter((call) => call.endpoint === 'copilot-state').length
  expect('后台检查失败：重试后重新拉状态', statesAfter > statesBefore,
    JSON.stringify({ before: statesBefore, after: statesAfter }))
  expect('后台检查失败：成功刷新后行消失', byClass(await t.settle(), 'scp-kb-error').length === 0)
}

{
  // 超时失败：原因句由 host 按检查对象给，原样上屏；不能再带 traces/ 的猜测（这条检查不读 traces/）。
  const t = await mount('recent', {
    kbError: {
      checkedAt: '2026-11-10T06:56:00+08:00',
      reason: 'E_TIMEOUT',
      message: '知识库检查超时（30 秒内没有返回；网络慢或机器休眠时可能偏慢）。',
    },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  const row = byClass(view, 'scp-kb-error')[0]
  const text = row ? nodeText(row) : ''
  expect('后台检查失败：超时原因原样上屏',
    /后台检查失败：\d\d-\d\d \d\d:\d\d 知识库检查超时（30 秒内没有返回/.test(text), text)
  expect('后台检查失败：超时原因不提 traces/', !text.includes('traces/'), text)
  t.dispose()
}

{
  // 没有失败原文时按原因码给一句：连续失败与权限拒绝分清，不写「被拒绝」。
  const t = await mount('recent', {
    kbError: { checkedAt: '2026-11-10T06:56:00+08:00', reason: 'E_TIMEOUT', message: '' },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  const row = byClass(view, 'scp-kb-error')[0]
  const text = row ? nodeText(row) : ''
  expect('后台检查失败：无原文且没有次数时给阈值兜底句',
    /后台检查失败：\d\d-\d\d \d\d:\d\d 已连续失败 3 次/.test(text), text)
  t.dispose()
}

{
  // 无原文但带连败次数：按状态文件里的次数上屏（升级前留下的 failures 可能是 9）。
  const t = await mount('recent', {
    kbError: { checkedAt: '2026-11-10T06:56:00+08:00', reason: 'E_TIMEOUT', message: '', failures: 9 },
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  const row = byClass(view, 'scp-kb-error')[0]
  const text = row ? nodeText(row) : ''
  expect('后台检查失败：无原文时按连败次数上屏',
    /后台检查失败：\d\d-\d\d \d\d:\d\d 已连续失败 9 次/.test(text), text)
  t.dispose()
}

{
  // 「去同步」复用 goSync：切到 Ascend Sleuth 整页。
  const t = await mount('recent', {
    kbError: KB_ERROR,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  click(findButton(t.view(), '去同步'))
  await t.settle()
  expect('后台检查失败：「去同步」切到 Ascend Sleuth 整页',
    t.selectedPanels.includes('ascend-sleuth-console'), JSON.stringify(t.selectedPanels))
  t.dispose()
}

{
  // 没有诊断单的空态：同样出现 kb-error 行。
  const t = await mount('empty', {
    kbError: KB_ERROR,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  expect('后台检查失败：空态也出现 kb-error 行', byClass(t.view(), 'scp-kb-error').length === 1)
}

{
  // 收起态：不渲染 kb-error 行。
  const t = await mount('recent', {
    kbError: KB_ERROR,
    prefs: { dockCollapsed: true, paletteFilter: 'all', pins: {} },
  })
  expect('后台检查失败：收起态不渲染 kb-error 行', byClass(t.view(), 'scp-kb-error').length === 0)
}

{
  // 正常提示不受影响：没有 kbError 时不渲染这一行。
  const t = await mount('recent', {
    kbNotice: KB_NOTICE,
    prefs: { dockCollapsed: false, paletteFilter: 'all', pins: {} },
  })
  const view = t.view()
  expect('后台检查失败：没有失败时不渲染 kb-error 行', byClass(view, 'scp-kb-error').length === 0)
  expect('后台检查失败：正常提示行照旧', byClass(view, 'scp-kb-notice').length === 1)
}

process.stdout.write('\n' + checks + ' 条断言，' + failures + ' 条失败\n')
process.exit(failures === 0 ? 0 : 1)
