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
  addEventListener() {},
  removeEventListener() {},
  execCommand: () => true,
}
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: {
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

// ── 最小 React 替身（按组件实例记录 hook，支持 deps） ──────────────────────
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
    return {
      type: node.type,
      props: node.props,
      children: (node.children || []).map((child, index) => renderNode(child, path + ':' + index)),
    }
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
  expect('最近一单：版本串 0.10.1', view.nodes.some((node) => node.props && node.props['data-version'] === '0.10.1'))
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
  const t = await mount('closed')
  click(findToolbar(t.view()))
  const view = await t.settle()
  click(findButton(view, '查 case 上游状态'))
  await t.settle()
  expect('上游：prompt 带已知锚点与上次查证', t.lastDraft().includes('vllm-ascend#15903') && t.lastDraft().includes('2026-W36'), t.lastDraft())
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
  expect('空态：开始诊断填入指令', t.lastDraft() === '/skill:diagnose ')
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
  expect('回报表单：生成完整指令', draft.includes('回报 ' + ID) && draft.includes('feedback.outcome 写成 resolved') && draft.includes('按报告改完后继续跑 2 小时没再崩'), draft)
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
  // 时间按本地时区渲染：本地断言不能钉死小时（CI 跑在 UTC），只钉「日期 + 时分」的完整形状。
  expect('台账：列表时间完整显示', /09-08 \d{2}:\d{2}/.test(view.text), view.text.slice(0, 500))
  pressKey('Enter')
  const afterEnter = await t.settle()
  expect('台账：Enter 打开回报表单', afterEnter.text.includes('将填入输入框'), afterEnter.text.slice(0, 400))
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

process.stdout.write('\n' + checks + ' 条断言，' + failures + ' 条失败\n')
process.exit(failures === 0 ? 0 : 1)
