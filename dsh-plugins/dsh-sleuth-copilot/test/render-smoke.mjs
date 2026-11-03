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

function pressKey(key) {
  for (const fn of Array.from(keyHandlers)) {
    fn({ key, target: { tagName: 'DIV' }, preventDefault() {} })
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
    extra: {
      currentStep: 5, maxSteps: 6, eventCount: 7, userSteps: 1, agentSteps: 6,
      platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
      excludedCases: ['VLLM-ASC-7993', 'VLLM-ASC-9887', 'VLLM-ASC-10500'],
      evidenceFiles: 1, evidenceMissing: '缺 device-side plog', hasReport: false,
    },
    harnessSession: '',
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
      },
      extra: {
        currentStep: 6, maxSteps: 6, eventCount: 9, userSteps: 1, agentSteps: 8,
        platform: 'A3-910C', category: 'interrupt', framework: 'vllm-ascend',
        excludedCases: [], evidenceFiles: 1, evidenceMissing: '', hasReport: true,
      },
    })
    return {
      ok: true, tracesDir: '/repo/traces', bound: null, recent: [row], all: [row, second],
      counts: { open: 1, pendingFeedback: 1, toSediment: 1 }, vocab: VOCAB, capabilities: CAPS,
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
  expect('注册：inject 声明了 sessions / uiWorkspace',
    Array.isArray(t.inject) && ['sessions', 'uiWorkspace'].every((name) => t.inject.includes(name)), JSON.stringify(t.inject))
  expect('最近一单：标出「最近一单」', view.text.includes('最近一单'), view.text.slice(0, 160))
  expect('最近一单：显示状态名', view.text.includes('进行中'))
  expect('最近一单：显示人读案例标题', view.text.includes('vllm-ascend GLM-5.3 在 A3 跑推理时 MoE routing TopK 触发 vector core exception'))
  expect('最近一单：单号不占标题位', !view.text.includes(ID), view.text.slice(0, 400))
  expect('最近一单：显示在等什么', view.text.includes('缺 device-side plog'))
  expect('最近一单：进度轨显示 5/6', view.text.includes('5/6'))
  expect('最近一单：主按钮是回报结果', !!findButton(view, '回报结果'))
  expect('最近一单：显示身份标签（知识库未覆盖）', view.text.includes('知识库未覆盖'))
  expect('最近一单：显示已排除条数', view.text.includes('已排除 3 条'))
  expect('最近一单：版本串 0.7.1', view.nodes.some((node) => node.props && node.props['data-version'] === '0.7.1'))
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
