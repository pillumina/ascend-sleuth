#!/usr/bin/env node
// check_panel_bundle.js —— 面板包（dsh-sleuth-panels）的可加载性冒烟测试
//
// 与 build_panel_bundle.js --check 分工：那个管「产物 = 源文件」，这个管「产物能跑」。
// 用 stub 的 ctx / 服务**原样加载两个生成物**，断言：
//
//   host 半： import 成功 → apply() 不抛 → 在 webServer 上注册一条 prefix 路由（channel 正确）
//            → 用假 req/res 走一遍真实信封（{ type:'server-response', rpcId, result }）：
//              未知端点回 not-found、已知端点走到面板的处理函数、非 POST 回 405、端点回退
//            → 附带工具经 ctx.tools.register 注册（参数归一化成 DSL）→ 返回卸载函数且不抛
//            工具定义优先用真品校验：探到已安装 DSH 时用它的 defineTool（写法不对当场红）。
//   client 半：工厂产出插件 → exports.inject 含 slots → apply() 注册三个 conversation.view tab
//            （id / order 与面板源码一致：ascend-diagnose 20、ascend-metrics 21、ascend-evolve 22）
//            → 用 mock React（effect 同步跑、createElement 递归渲染函数组件）把三个 tab 的首屏
//              各渲染一次，断言 host.call 真的发出各自的端点、渲染期无异常。
//            真机那一次仍归 scripts/panel_rpc_probe.js（同一条线协议）。
//
// 为什么值得有：面板包装进 profile 后，首个失败信号是「重启后 tab 不出现」，而那要用户重启
// 一次 DSH Desktop 才能看见——这个脚本把「代码能不能加载、能不能注册」提前到本地秒级。
//
// 还有一段 DSH 探针（装载前跑）：判定本机 DSH 支持哪条装载路，并核对常驻包依赖的四条接缝
// 还在不在。找不到已安装的 DSH 时如实跳过（CI 形态），不假装通过。
//
// 用法：
//   node scripts/check_panel_bundle.js                    产物 + 冒烟 + DSH 探针（自动找 DSH，找不到即跳过）
//   node scripts/check_panel_bundle.js --dsh-root <目录>   指定 DSH 安装处（如 <app>/resources/app.asar.unpacked）
//   node scripts/check_panel_bundle.js --selftest-dsh      用临时假 DSH 自测探针本身（不需要真 DSH）
//
// 退出码：0 全绿或如实跳过；1 产物/冒烟失败，或 --dsh-root 指到的目录里没有 DSH 包；
//        2 DSH 接缝漂移

'use strict'

const fs = require('fs')
const path = require('path')
const os = require('os')
const crypto = require('crypto')
const { pathToFileURL } = require('node:url')
const { register } = require('node:module')

const repo = path.resolve(__dirname, '..')
const BUNDLE = 'dsh-plugins/dsh-sleuth-panels'
const CHANNEL = '/ascend-sleuth-panels'

// 面板清单与生成器一致：id 只用于日志，host/client 是唯一真源
const PANELS = [
  {
    id: 'ascend-panel',
    host: 'dsh-plugins/ascend-panel/panel-host.js',
    client: 'dsh-plugins/ascend-panel/panel-client.js',
  },
  {
    id: 'ev-panel',
    host: 'dsh-plugins/ev-panel/panel-host.js',
    client: 'dsh-plugins/ev-panel/panel-client.js',
  },
]

const failures = []
function check(ok, label, detail) {
  if (ok) {
    process.stdout.write('  ok   ' + label + '\n')
    return
  }
  failures.push(label + (detail ? ' —— ' + detail : ''))
  process.stdout.write('  FAIL ' + label + (detail ? ' —— ' + detail : '') + '\n')
}

// 生成物必须存在（缺了先跑生成器）
for (const rel of ['lib/index.js', 'lib/client.js']) {
  if (!fs.existsSync(path.join(repo, BUNDLE, rel))) {
    process.stderr.write('缺少产物 ' + BUNDLE + '/' + rel + '——先跑 node scripts/build_panel_bundle.js\n')
    process.exit(1)
  }
}

// 让生成物里的 `import { defineTool } from '@deepseek-ai/dsh-tools'` 在仓库里可解析
register(pathToFileURL(path.join(__dirname, 'fixtures', 'panel-bundle-stub-loader.mjs')).href)

// 假 shell：**故意只给 execute**（这个 DSH 的 shell 服务就是这个形状），
// 用来验适配层补的 `run → execute + result()` 桥；记录每条命令，好断言探测与脚本调用都发生过。
function makeFakeShell(record) {
  return {
    resolve(request) {
      return {
        command: request.command,
        workdir: request.workdir,
        stdoutMaxBytes: request.stdoutMaxBytes,
        sandboxPolicy: request.sandboxPolicy,
      }
    },
    async execute(spec) {
      record.shellCommands.push(String(spec.command))
      const command = String(spec.command)
      // 按命令给对应的"脚本输出"：验的是面板的取数与解析路径，不重算脚本内容
      let stdout = 'Python 3.13.0'
      if (/metrics_health\.py/.test(command)) {
        stdout = '{"gates":[{"id":"selftest","level":"ok","title":"自测判据","plain":"自测判据"}],'
          + '"findings":[{"level":"ok","face":"数据底座","text":"selftest finding","action":null,"plain":null}]}'
      } else if (/ev_board_data\.py/.test(command)) {
        stdout = '{"ideas":[],"by_surface":{},"skill_exec":{},"generated_at":"selftest"}'
      } else if (/evolution_health\.py/.test(command)) {
        stdout = '{"findings":[],"generated_at":"selftest"}'
      } else if (!/--version/.test(command)) {
        stdout = '{}'
      }
      return {
        status: 'exited',
        exitCode: 0,
        signal: null,
        async result() {
          return {
            exitCode: 0,
            signal: null,
            timedOut: false,
            aborted: false,
            timeoutMs: 1000,
            stdout: { text: stdout, truncated: false },
            stderr: { text: '', truncated: false },
          }
        },
      }
    },
  }
}

function makeHostCtx(record) {
  record.shellCommands = []
  record.shell = makeFakeShell(record)
  const ctx = {
    get(name) {
      record.gets.push(name)
      // fs 不给：面板必须自行降级而不是崩。
      // sessions 给一个带 cwd 的会话（工作区解析要它）；shell 只给 execute（见 makeFakeShell）；
      // connection 只给路由守卫要用的 requestRejection（放行）。
      if (name === 'connection') return { requestRejection: () => undefined }
      if (name === 'sessions') {
        return {
          get: () => ({ header: { cwd: repo } }),
          list: () => [{ header: { cwd: repo } }],
        }
      }
      if (name === 'shell') return record.shell
      return undefined
    },
    tools: {
      register(definition) {
        record.tools.push(definition && definition.name)
        record.toolDefinition = definition
        return () => {}
      },
    },
    webServer: {
      register(route) {
        record.route = route
        return async () => {}
      },
    },
    inject(deps, callback) {
      record.injects.push(deps.join(','))
      return callback(ctx)
    },
    effect(callback) {
      const disposer = callback()
      return typeof disposer === 'function' ? disposer : () => {}
    },
    on() { return () => {} },
  }
  return ctx
}

// 假 req/res：走一遍客户端真正会走的 HTTP 信封（POST <channel>/<endpoint>，body { rpcId, payload }）
function fakeRequest(url, body, method) {
  const encoded = Buffer.from(JSON.stringify(body), 'utf8')
  return {
    method: method === undefined ? 'POST' : method,
    url,
    async *[Symbol.asyncIterator]() {
      yield encoded
    },
  }
}

function fakeResponse() {
  return {
    statusCode: null,
    headers: null,
    setHeaders: null,
    body: '',
    setHeader(name, value) {
      this.setHeaders = Object.assign({}, this.setHeaders, { [name]: value })
      return this
    },
    writeHead(code, headers) {
      this.statusCode = code
      this.headers = headers === undefined ? null : headers
      return this
    },
    end(text) {
      this.body = text === undefined ? '' : String(text)
      return this
    },
  }
}

async function callRoute(route, endpoint, payload, method) {
  const res = fakeResponse()
  await route.handler(fakeRequest(CHANNEL + '/' + endpoint, { rpcId: 'r-test', payload }, method), res)
  let parsed = null
  try {
    parsed = JSON.parse(res.body)
  } catch (e) {
    parsed = null
  }
  return { res, parsed }
}

// URL 里拿不到端点时（路径不带 channel 前缀），回退用 body.method
async function callRouteByMethod(route, endpoint, payload) {
  const res = fakeResponse()
  await route.handler(fakeRequest('/not-our-prefix', { rpcId: 'r-method', method: endpoint, payload }), res)
  let parsed = null
  try {
    parsed = JSON.parse(res.body)
  } catch (e) {
    parsed = null
  }
  return { res, parsed }
}

// 三处名字必须对齐：package.json 的 name、cordis.patch.yml 插入行的 name、产物的 export name。
// 此前没有任何门读这两份清单——错过只会在"装上、重启、界面什么都没发生"时才暴露
// （插件管理器按 name 解析包，客户端产物按 id 认领）。
function checkNames(artifactName) {
  const pkg = JSON.parse(fs.readFileSync(path.join(repo, BUNDLE, 'package.json'), 'utf8'))
  const patch = fs.readFileSync(path.join(repo, BUNDLE, 'cordis.patch.yml'), 'utf8')
  const matched = /name:\s*'([^']+)'/.exec(patch)
  const patchName = matched === null ? null : matched[1]

  check(pkg.name === artifactName, 'package.json 的 name 与产物 export name 一致', String(pkg.name))
  check(patchName === artifactName, 'cordis.patch.yml 插入行的 name 与产物 export name 一致', String(patchName))
  check(pkg.exports !== undefined && pkg.exports['.'] === './lib/index.js' && pkg.exports['./client'] === './lib/client.js',
    'package.json 的 exports 指向两个产物', JSON.stringify(pkg.exports))
  check(pkg.dsh !== undefined && pkg.dsh.bundle !== undefined && pkg.dsh.bundle.patch === './cordis.patch.yml',
    'package.json 声明 dsh.bundle.patch', pkg.dsh === undefined ? '缺 dsh' : JSON.stringify(pkg.dsh.bundle))
  check(pkg.dsh !== undefined && pkg.dsh.client !== undefined && pkg.dsh.client.platform === 'web',
    "package.json 声明 dsh.client.platform = 'web'",
    pkg.dsh === undefined ? '缺 dsh' : JSON.stringify(pkg.dsh.client))
}

async function checkHost() {
  process.stdout.write('host 半（' + BUNDLE + '/lib/index.js）\n')

  // 探到已安装的 DSH 就用真品 defineTool 校验工具定义（找不到则用本地 stub，如实说明）
  const detected = detectDshRoot()
  if (detected.looksLikeDsh) {
    process.env.DSH_SLEUTH_TOOLS_ROOT = detected.root
    process.stdout.write('  工具定义用真品校验：' + detected.root + '\n')
  } else {
    process.stdout.write('  工具定义用本地 stub 校验（未找到已安装 DSH，这一项强度较弱）\n')
  }

  const mod = await import(pathToFileURL(path.join(repo, BUNDLE, 'lib/index.js')).href)

  check(mod.name === 'dsh-sleuth-panels', 'export name = dsh-sleuth-panels', String(mod.name))
  checkNames(mod.name)
  check(Array.isArray(mod.inject) && mod.inject.includes('connection') && mod.inject.includes('tools'),
    'inject 含 connection + tools', JSON.stringify(mod.inject))

  const record = { gets: [], tools: [], injects: [], route: undefined }
  const ctx = makeHostCtx(record)

  const dispose = mod.apply(ctx)
  check(record.injects.includes('webServer'), "路由注册在 ctx.inject(['webServer']) 内")
  check(record.route !== undefined && record.route.kind === 'prefix' && record.route.path === CHANNEL,
    '在 webServer 上注册 prefix 路由 ' + CHANNEL,
    record.route === undefined ? '未注册' : JSON.stringify({ kind: record.route.kind, path: record.route.path }))
  check(record.route !== undefined && typeof record.route.handler === 'function', '路由 handler 是函数')
  check(record.tools.length === 1 && record.tools[0] === 'ascend_trace_status',
    '注册 1 个附带工具（ascend_trace_status）', JSON.stringify(record.tools))
  const spec = record.toolDefinition === undefined ? undefined : record.toolDefinition.parameters
  check(spec !== undefined && spec.cwd !== undefined && spec.type === undefined,
    '工具参数已归一化成 DSL（字段名 → schema，不再是 JSON-Schema 包装）', JSON.stringify(spec))
  check(typeof dispose === 'function', 'apply() 返回卸载函数')

  // 未知端点：分发表要回 not-found 信封（客户端 rpc.call 依赖 result.ok/error）
  const unknown = await callRoute(record.route, 'no-such-endpoint', {})
  check(unknown.res.statusCode === 200
    && unknown.parsed !== null
    && unknown.parsed.type === 'server-response'
    && unknown.parsed.rpcId === 'r-test'
    && unknown.parsed.result.ok === false
    && unknown.parsed.result.error.code === 'not-found',
    '未知端点：200 + server-response 信封 + result.ok=false/not-found',
    JSON.stringify(unknown.parsed))

  // 已知端点：fs 未注入 → 面板自身的降级分支（不该抛、也不该 500）
  const known = await callRoute(record.route, 'ascend-traces-list', { sessionId: 'x' })
  check(known.res.statusCode === 200
    && known.parsed !== null
    && known.parsed.result.ok === true
    && known.parsed.result.value.ok === false,
    '已知端点：走到面板处理函数并走 fs 缺失降级', JSON.stringify(known.parsed))

  // shell 形状桥：这个 DSH 的 shell 只有 execute（返回句柄），面板写的是 run(spec) 并直接读
  // exitCode/stdout.text —— 适配层补的桥必须让这条端点真的跑起来（此前真机上它退化成
  // "未找到可用的 Python 3 解释器"）
  const verdict = await callRoute(record.route, 'ascend-metrics-verdict', { sessionId: 'x' })
  const verdictText = JSON.stringify(verdict.parsed)
  check(verdict.parsed !== null && verdict.parsed.result.ok === true
    && verdictText.indexOf('未找到可用的 Python 3 解释器') < 0,
    'shell 桥：ascend-metrics-verdict 在只有 execute 的服务上不再报"找不到 Python"',
    verdictText.slice(0, 200))
  check(record.shellCommands.some((c) => /--version/.test(c)) && record.shellCommands.some((c) => /metrics_health\.py/.test(c)),
    'shell 桥：解释器探测与脚本调用都真的发生过', JSON.stringify(record.shellCommands.slice(0, 3)))

  // 自演进那两个端点此前只有 client 侧覆盖（渲染时发出 RPC），host 侧的取数与解析没有断言
  const board = await callRoute(record.route, 'ev-board-load', { sessionId: 'x' })
  const boardText = JSON.stringify(board.parsed)
  check(board.parsed !== null && board.parsed.result.ok === true
    && boardText.indexOf('未找到可用的 Python 3 解释器') < 0,
    'shell 桥：ev-board-load 走通（ev_board_data.py 的输出被解析成 data）', boardText.slice(0, 200))
  check(record.shellCommands.some((c) => /ev_board_data\.py/.test(c)), 'shell 桥：ev_board_data.py 真被调用')

  const health = await callRoute(record.route, 'ev-health-load', { sessionId: 'x' })
  const healthText = JSON.stringify(health.parsed)
  check(health.parsed !== null && health.parsed.result.ok === true
    && healthText.indexOf('未找到可用的 Python 3 解释器') < 0,
    'shell 桥：ev-health-load 走通（evolution_health.py 的输出被解析成 data）', healthText.slice(0, 200))
  check(record.shellCommands.some((c) => /evolution_health\.py/.test(c)), 'shell 桥：evolution_health.py 真被调用')

  // 非 POST：405（与 dsh-ppt 的同名路由一致）
  const wrongMethod = await callRoute(record.route, 'ascend-traces-list', {}, 'GET')
  check(wrongMethod.res.statusCode === 405, '非 POST 回 405', String(wrongMethod.res.statusCode))

  // URL 里拿不到端点时回退 body.method（客户端两个都发，回退只为前缀匹配方式变化时兜底）
  const byMethod = await callRouteByMethod(record.route, 'ascend-traces-list', { sessionId: 'x' })
  check(byMethod.parsed !== null
    && byMethod.parsed.result.ok === true
    && byMethod.parsed.result.value.ok === false,
    '端点在 URL 缺失时回退 body.method', JSON.stringify(byMethod.parsed))

  // 卸载：端点从分发表里摘掉（路由本身由 webCtx.effect 收回），再请求即 not-found
  dispose()
  const afterDispose = await callRoute(record.route, 'ascend-traces-list', {})
  check(afterDispose.parsed !== null
    && afterDispose.parsed.result.ok === false
    && afterDispose.parsed.result.error.code === 'not-found',
    '卸载后端点已摘除', JSON.stringify(afterDispose.parsed))
}

// createElement 递归调用函数组件：面板注册的是薄包装（`props => createElement(TraceView, props)`），
// 不往下渲染就永远走不到内层组件的挂载 effect（也就不发那条首屏 RPC）。渲染期异常收集在
// renderErrors 里，由调用侧断言为空——别让内层报错被静默吞掉。
const renderErrors = []
const REACT_STUB = {
  createElement(type, props, ...children) {
    if (typeof type === 'function') {
      const merged = Object.assign({}, props)
      if (children.length === 1) merged.children = children[0]
      else if (children.length > 1) merged.children = children
      try {
        return type(merged)
      } catch (e) {
        renderErrors.push(String((e && e.stack) || e).split('\n').slice(0, 2).join(' | '))
        return null
      }
    }
    return null
  },
  Fragment: 'Fragment',
  useState: (value) => [value, () => {}],
  useReducer: (reducer, initial) => [initial, () => {}],
  // effect 同步跑：面板取数都在挂载 effect 里，跑一次就等于"首屏真的发了那条 RPC"
  useEffect: (fn) => {
    const cleanup = fn()
    return typeof cleanup === 'function' ? cleanup : () => {}
  },
  useLayoutEffect: (fn) => {
    const cleanup = fn()
    return typeof cleanup === 'function' ? cleanup : () => {}
  },
  useMemo: (factory) => factory(),
  useCallback: (fn) => fn,
  useRef: (value) => ({ current: value }),
  useContext: () => undefined,
  useSyncExternalStore: (subscribe, getSnapshot) => getSnapshot(),
  useId: () => 'selftest-id',
  useTransition: () => [false, (fn) => fn()],
  useDeferredValue: (value) => value,
  createContext: () => ({ Provider: 'Provider', Consumer: 'Consumer' }),
  memo: (component) => component,
  forwardRef: (component) => component,
  cloneElement: () => null,
  isValidElement: () => false,
  Children: { map: () => [] },
}

// 面板 apply 时 `styles.insert(PANEL_CSS)` 会建 <style> 标签，Node 里需要最小 document
const styleTags = []
function installDocumentStub() {
  global.document = {
    createElement() {
      return {
        dataset: {},
        textContent: '',
        remove() {
          const index = styleTags.indexOf(this)
          if (index >= 0) styleTags.splice(index, 1)
        },
      }
    },
    head: {
      append(tag) { styleTags.push(tag) },
    },
  }
}

async function checkClient() {
  process.stdout.write('client 半（' + BUNDLE + '/lib/client.js）\n')

  let entry = null
  global.window = { __ModuleLoader__: { load(value) { entry = value } } }
  installDocumentStub()

  await import(pathToFileURL(path.join(repo, BUNDLE, 'lib/client.js')).href)
  check(entry !== null && entry.id === 'dsh-sleuth-panels',
    'load({ id: dsh-sleuth-panels })', entry === null ? '工厂未注册' : String(entry.id))

  const requireStub = (specifier) => {
    if (specifier === 'react') return REACT_STUB
    throw new Error('生成物要求了未预期的依赖: ' + specifier)
  }
  const mod = entry.factory(requireStub)
  check(Array.isArray(mod.inject) && mod.inject.includes('slots'), 'inject 含 slots', JSON.stringify(mod.inject))

  const registrations = []
  const slots = {
    inject(name, factory) {
      factory()
      return () => {}
    },
    register(options, component) {
      registrations.push(Object.assign({ component }, options))
      return () => {}
    },
  }
  // 客户端那侧的 host.call → connection.rpc.call：记录每次调用，好断言首屏真的发了哪条 RPC
  const rpcCalls = []
  const connection = {
    rpc: {
      call(channel, endpoint, payload) {
        rpcCalls.push({ channel, endpoint, payload })
        return Promise.resolve({ ok: true, value: { ok: true, sessions: [] } })
      },
    },
  }
  const clientCtx = {
    get(name) {
      if (name === 'slots') return slots
      if (name === 'connection') return connection
      return undefined
    },
    inject(deps, callback) { return callback(clientCtx) },
    effect(callback) {
      const disposer = callback()
      return typeof disposer === 'function' ? disposer : () => {}
    },
    on() { return () => {} },
  }

  const dispose = mod.apply(clientCtx)

  const expected = [
    ['ascend-diagnose', 20],
    ['ascend-metrics', 21],
    ['ascend-evolve', 22],
  ]
  const seen = registrations.map(r => [r.id, r.order])
  check(JSON.stringify(seen) === JSON.stringify(expected),
    '注册三个 conversation.view tab（id + order）', JSON.stringify(seen))
  check(registrations.every(r => r.name === 'conversation.view'),
    '三个 tab 都注册在 conversation.view')
  check(styleTags.length >= 2, '两个面板都经 styles.insert 注入样式', '标签数 ' + styleTags.length)

  // 渲染三个 tab 的首屏组件（mock React 同步跑 effect）：这条覆盖此前为零的 client 侧 host.call →
  // connection.rpc.call 映射——面板源码不渲染组件就不发 RPC，所以只有真渲染才能验到它。
  const wantEndpoint = {
    'ascend-diagnose': 'ascend-traces-list',
    'ascend-metrics': 'ascend-metrics-verdict',
    'ascend-evolve': 'ev-board-load',
  }
  for (const item of registrations) {
    const label = item.id
    let threw = null
    try {
      if (typeof item.component === 'function') item.component({ sessionId: 'selftest' })
    } catch (e) {
      threw = String((e && e.message) || e)
    }
    check(threw === null, 'client 半 ' + label + ' 首屏组件渲染不抛', threw === null ? '' : threw)
  }
  for (const [id, endpoint] of Object.entries(wantEndpoint)) {
    const hit = rpcCalls.find(c => c.endpoint === endpoint)
    check(hit !== undefined && hit.channel === CHANNEL,
      'client 半 ' + id + ' 首屏经 host.call 发出 ' + endpoint,
      hit === undefined ? '未发出；已发出：' + JSON.stringify(rpcCalls.map(c => c.endpoint)) : JSON.stringify(hit.payload))
  }
  check(renderErrors.length === 0, '渲染期无异常（含被 createElement 递归调用的内层组件）',
    renderErrors.slice(0, 2).join(' ;; '))

  if (typeof dispose === 'function') dispose()
  check(styleTags.length === 0, '卸载后样式标签清空', '标签数 ' + styleTags.length)
}

function fingerprint(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 12)
}

// 保真：产物里嵌的必须是源文件原文。
// 为什么单列一条：`build_panel_bundle.js --check` 只证明"产物 == 重新生成的产物"——
// 若生成器本身的嵌入逻辑吃掉了内容，两边会一起错、门照绿。这里直接拿源文件比对。
// 强度如实标注：这是**必要非充分**——原文作为子串出现即可通过，它不证明"被执行的就是原文"
// （重复嵌入或放进死分支都能绿）。补足靠冒烟测试真的把产物跑起来。
function checkFidelity(artifactRel, half) {
  process.stdout.write('保真（' + artifactRel + ' ← 各面板 ' + half + ' 源文件）\n')
  const artifact = fs.readFileSync(path.join(repo, BUNDLE, artifactRel), 'utf8')

  for (const panel of PANELS) {
    const rel = panel[half]
    const raw = fs.readFileSync(path.join(repo, rel), 'utf8')
    // 生成器只去掉源文件末尾空白（文件末尾换行），比对时照同一条变换
    const body = raw.replace(/\s*$/, '')
    const label = panel.id + ' ' + half

    check(artifact.includes(body), label + ' 原文逐字嵌进产物（' + rel + '）')
    check(artifact.includes('sha256:' + fingerprint(raw)),
      label + ' 产物标记的源文件指纹与当前源文件一致')
  }
}

// ── DSH 探针：装载路判定 + 五条接缝 ──────────────────────────────────────────
//
// 常驻插件包把面板源码接到新版 DSH 上，靠的是五个外部契约（**都是生成物真正用到的**）：
//   ① webServer.register(route) 且 WebRouteKind 含 prefix —— RPC 挂在这条 prefix 路由上
//   ② connection.requestRejection(request) —— 路由处理函数用它挡未授权请求
//   ③ client 沙箱给每个包注入 styles.insert(css) -> disposer
//   ④ 页面产物格式 window.__ModuleLoader__.load({ id, factory })
//   ⑤ shell 的 resolve(request) + execute(spec) —— 面板写的是 shell.run(spec)，适配层映射到这两个
// 这五条任一变化，面板都要到「装完、重启、页面空白」才被发现。这里把它们读成断言，
// 顺便判本机 DSH 有没有模型侧的 cordis_define（有 = 热加载路，无 = 常驻插件包路）。
//
// 反面教材（首版踩过）：曾把断言挂在 `connection.rpc.handle` 上——那是适配层**明确不用**的
// 接口（它把 owner 绑在服务自身 ctx 上，注册即抛）。那样的断言在 DSH 真删掉该接口时会误红，
// 并把读者引向一个无需改动的文件。断言只盯自己用的契约。

const API_CATALOG = '@deepseek-ai/dsh-tool-cordis/lib/types/api-catalog.js'

const DSH_SEAMS = [
  {
    id: 'webServer-prefix-route',
    rel: API_CATALOG,
    // 生成物里类型声明是 JS 字符串，引号带转义（\'exact\' | \'prefix\'），所以用宽松匹配
    ok: (text) => text.includes('register(route: WebRoute)') && /exact.{0,8}\|.{0,8}prefix/.test(text),
    note: 'webServer 的 prefix 路由（面板包的 RPC 挂在它上面）',
  },
  {
    id: 'connection-requestRejection',
    rel: API_CATALOG,
    ok: (text) => text.includes('requestRejection(request: ConnectionTrustRequest)'),
    note: 'connection 的请求准入（路由处理函数用它挡未授权的请求）',
  },
  {
    id: 'styles-insert',
    rel: '@deepseek-ai/dsh-cordis-client-runner/lib/client.js',
    ok: (text) => text.includes('styles.insert(css'),
    note: 'client 沙箱注入的样式接口（styles.insert(css) -> disposer）',
  },
  {
    id: 'client-module-loader',
    rel: '@deepseek-ai/dsh-client-modules/lib/index.js',
    ok: (text) => text.includes('window.__ModuleLoader__'),
    note: '页面产物格式（window.__ModuleLoader__.load({ id, factory })）',
  },
  {
    id: 'shell-resolve-execute',
    rel: API_CATALOG,
    // 面板写的是 shell.run(spec)，本 DSH 只有 resolve + execute（句柄 + result()），适配层据此补桥；
    // 这条断言盯的是那两个方法还在（PTC 的 run(spec: PtcRunSpec) 是另一回事，不在此列）
    ok: (text) => text.includes('resolve(request: ShellExecRequest)') && text.includes('execute(spec: ShellExecSpec)'),
    note: 'shell 的 resolve + execute（面板的 run 由适配层映射到它们）',
  },
]

const DSH_ROUTE_FILE = '@deepseek-ai/dsh-tool-cordis/lib/index.js'

function readUnder(root, rel) {
  try {
    return fs.readFileSync(path.join(root, 'node_modules', rel), 'utf8')
  } catch (e) {
    return null
  }
}

function probeDsh(root) {
  const routeText = readUnder(root, DSH_ROUTE_FILE)
  const seams = DSH_SEAMS.map((seam) => {
    const text = readUnder(root, seam.rel)
    return { id: seam.id, note: seam.note, rel: seam.rel, present: text !== null, ok: text !== null && seam.ok(text) }
  })
  return {
    root,
    // 只有确实读到路线文件才敢判路；读不到就不给结论（见 looksLikeDsh）
    route: routeText === null ? null : (routeText.includes('cordis_define') ? 'hot-load' : 'bundle'),
    seams,
    looksLikeDsh: routeText !== null || seams.some((seam) => seam.present),
  }
}

// 自动找 DSH：① 显式环境变量；② 桌面版 patch 里带绝对 file:/// URL 指向 app.asar.unpacked；
// ③ profile 的 node_modules。都找不到就如实跳过（CI 形态没有 DSH）。
function detectDshRoot() {
  const tried = []
  const candidates = []
  if (process.env.DSH_DSH_ROOT) candidates.push(process.env.DSH_DSH_ROOT)

  const home = process.env.DSH_HOME
  if (home) {
    let names = []
    try {
      names = fs.readdirSync(home).filter((name) => name.endsWith('.yml') || name.endsWith('.yaml'))
    } catch (e) {
      names = []
    }
    for (const name of names) {
      let text = ''
      try {
        text = fs.readFileSync(path.join(home, name), 'utf8')
      } catch (e) {
        continue
      }
      // 路径里有 %20（Desktop 的 patch 就是这样写的）：先按原文匹配，再解码，别先解码
      // （先解码会把空格喂给 [^"'] 之外的空白类，匹配反而失败——实测踩过）
      const matched = /file:\/\/\/([^"']*?resources\/app\.asar\.unpacked)\//.exec(text)
      if (matched) candidates.push(matched[1].replace(/%20/g, ' '))
    }
  }
  if (process.env.DSH_PROFILE_DIR) candidates.push(path.join(process.env.DSH_PROFILE_DIR, 'node_modules'))

  for (const raw of candidates) {
    const root = path.resolve(raw)
    if (tried.indexOf(root) >= 0) continue
    tried.push(root)
    const probe = probeDsh(root)
    if (probe.looksLikeDsh) return probe
  }
  return { root: null, route: null, seams: [], looksLikeDsh: false, tried }
}

// 返回退出码：0 无漂移；2 有接缝漂移
function checkDsh(probe, explicit) {
  if (!probe.looksLikeDsh) {
    if (explicit) {
      process.stderr.write('指定的 DSH 目录里没有 @deepseek-ai 包：' + probe.root + '\n')
      return 1
    }
    process.stdout.write('DSH 探针：未找到已安装的 DSH（试过：' + (probe.tried || []).join('、') + '）——如实跳过\n')
    process.stdout.write('  要指定就传 --dsh-root <DSH 安装处，如 <app>/resources/app.asar.unpacked>\n')
    return 0
  }

  process.stdout.write('DSH 探针（' + probe.root + '）\n')
  process.stdout.write('  路线：' + (probe.route === 'hot-load'
    ? '热加载路（有 cordis_define / cordis_run）'
    : '常驻插件包路（无 cordis_define，走 plugin_manager install_bundle）') + '\n')

  let drift = 0
  for (const seam of probe.seams) {
    if (!seam.ok) drift += 1
    process.stdout.write('  ' + (seam.ok ? 'ok   ' : 'DRIFT') + ' ' + seam.id + ' —— ' + seam.note + '\n')
    if (!seam.ok) {
      process.stdout.write('        （读 ' + seam.rel + '：' + (seam.present ? '文件在，但断言不成立' : '文件缺失') + '）\n')
    }
  }
  if (drift > 0) {
    process.stderr.write('DSH 接缝漂移 ' + drift + ' 处：面板包依赖的外部契约变了，'
      + '先按上面点名的文件核对适配层（scripts/build_panel_bundle.js 的适配段）再装\n')
    return 2
  }
  return 0
}

function writeFakeDsh(root, options) {
  // webServer 与 requestRejection 两条接缝同住 api-catalog.js：要去掉前者，得只留后者
  const catalog = options.omitWebRoute
    ? "signature: 'requestRejection(request: ConnectionTrustRequest): ConnectionRequestRejection'\n"
      + "signature: 'resolve(request: ShellExecRequest): ShellExecSpec'\n"
      + "signature: 'execute(spec: ShellExecSpec): Promise<ShellExecution>'"
    : "signature: 'register(route: WebRoute): () => void'\n"
      + "signature: 'requestRejection(request: ConnectionTrustRequest): ConnectionRequestRejection'\n"
      + "signature: 'resolve(request: ShellExecRequest): ShellExecSpec'\n"
      + "signature: 'execute(spec: ShellExecSpec): Promise<ShellExecution>'\n"
      + "export interface WebRoute { kind: WebRouteKind; path: string; handler: (req, res) => void }\n"
      + "export type WebRouteKind = 'exact' | 'prefix'"
  const files = {
    '@deepseek-ai/dsh-tool-cordis/lib/index.js': options.legacy
      ? "defineTool({ name: 'cordis_define' }); defineTool({ name: 'cordis_run' })"
      : "defineTool({ name: 'cordis_inspect_list' }); defineTool({ name: 'cordis_inspect_query' })",
    '@deepseek-ai/dsh-tool-cordis/lib/types/api-catalog.js': catalog,
    '@deepseek-ai/dsh-client-modules/lib/index.js':
      'window.__ModuleLoader__={ create() {}, load(entry) { return entry } }',
  }
  if (!options.omitStyles) {
    files['@deepseek-ai/dsh-cordis-client-runner/lib/client.js'] = 'signatures: ["styles.insert(css: string): () => void"]'
  }
  for (const [rel, body] of Object.entries(files)) {
    const target = path.join(root, 'node_modules', rel)
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, body, 'utf8')
  }
}

// 探针自测：四份临时假 DSH（现代 / 旧版 / 去 styles.insert / 去 webServer 路由声明）。
// 不需要真 DSH，所以 CI 里也能跑。每份都断言路线判定与漂移条数，并打印是哪条接缝漂了。
function selftestDsh() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-probe-selftest-'))
  const cases = [
    { name: '现代（无 cordis_define）', legacy: false, route: 'bundle', drift: [] },
    { name: '旧版（有 cordis_define）', legacy: true, route: 'hot-load', drift: [] },
    { name: '漂移（去 styles.insert）', legacy: false, omitStyles: true, route: 'bundle', drift: ['styles-insert'] },
    { name: '漂移（去 webServer 路由声明）', legacy: false, omitWebRoute: true, route: 'bundle', drift: ['webServer-prefix-route'] },
  ]
  let bad = 0
  try {
    for (const item of cases) {
      const root = path.join(base, item.name.replace(/[（）]/g, '-'))
      writeFakeDsh(root, item)
      const probe = probeDsh(root)
      const missing = probe.seams.filter((seam) => !seam.ok).map((seam) => seam.id)
      const want = item.drift.slice().sort()
      const got = missing.slice().sort()
      const ok = probe.route === item.route && JSON.stringify(got) === JSON.stringify(want)
      if (!ok) bad += 1
      process.stdout.write('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + item.name
        + '：route=' + probe.route + ' 漂移=[' + got.join(',') + ']'
        + '（期望 route=' + item.route + ' 漂移=[' + want.join(',') + ']）\n')
    }
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
  if (bad > 0) {
    process.stderr.write('DSH 探针自测未通过：' + bad + ' 例\n')
    return 1
  }
  process.stdout.write('dsh-probe selftest ok（4 例：现代 / 旧版 / 去 styles.insert / 去 webServer 路由声明）\n')
  return 0
}

async function main() {
  if (process.argv.includes('--selftest-dsh')) {
    process.exit(selftestDsh())
  }

  await checkHost()
  await checkClient()
  checkFidelity('lib/index.js', 'host')
  checkFidelity('lib/client.js', 'client')

  if (failures.length > 0) {
    process.stderr.write('\n面板包冒烟测试未通过（' + failures.length + ' 项）：\n')
    for (const item of failures) process.stderr.write('  - ' + item + '\n')
    process.exit(1)
  }
  process.stdout.write('\n面板包冒烟测试通过\n')

  const rootFlag = process.argv.indexOf('--dsh-root')
  const explicitRoot = rootFlag >= 0 ? process.argv[rootFlag + 1] : undefined
  if (rootFlag >= 0 && explicitRoot === undefined) {
    process.stderr.write('--dsh-root 后面要给一个目录\n')
    process.exit(1)
  }
  const code = checkDsh(explicitRoot ? probeDsh(path.resolve(explicitRoot)) : detectDshRoot(), explicitRoot !== undefined)
  process.exit(code)
}

main().catch((error) => {
  process.stderr.write('冒烟测试异常: ' + String((error && error.stack) || error) + '\n')
  process.exit(1)
})
