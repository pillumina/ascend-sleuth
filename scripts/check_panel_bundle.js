#!/usr/bin/env node
// check_panel_bundle.js —— 面板包（dsh-sleuth-panels）的可加载性冒烟测试
//
// 与 build_panel_bundle.js --check 分工：那个管「产物 = 源文件」，这个管「产物能跑」。
// 用 stub 的 ctx / 服务**原样加载两个生成物**，断言：
//
//   host 半： import 成功 → apply() 不抛 → 注册一条 connection RPC 路由（channel 正确）
//            → 未知端点回 { ok:false, error.code:'not-found' } → 已知端点走到面板的处理函数
//            → 附带工具经 ctx.tools.register 注册 → 返回卸载函数且不抛
//   client 半：工厂产出插件 → exports.inject 含 slots → apply() 注册三个 conversation.view tab
//            （id / order 与面板源码一致：ascend-diagnose 20、ascend-metrics 21、ascend-evolve 22）
//
// 为什么值得有：面板包装进 profile 后，首个失败信号是「重启后 tab 不出现」，而那要用户重启
// 一次 DSH Desktop 才能看见——这个脚本把「代码能不能加载、能不能注册」提前到本地秒级。
//
// 还有一段 DSH 探针（装载前跑）：判定本机 DSH 支持哪条装载路，并核对常驻包依赖的三处接缝
// 还在不在——它们此前是靠试装试出来的（webServer 注入、styles.insert、authority）。
// 找不到已安装的 DSH 时如实跳过（CI 形态），不假装通过。
//
// 用法：
//   node scripts/check_panel_bundle.js                    产物 + 冒烟 + DSH 探针（自动找 DSH，找不到即跳过）
//   node scripts/check_panel_bundle.js --dsh-root <目录>   指定 DSH 安装处（如 <app>/resources/app.asar.unpacked）
//   node scripts/check_panel_bundle.js --selftest-dsh      用临时假 DSH 自测探针本身（不需要真 DSH）
//
// 退出码：0 全绿或如实跳过；1 产物/冒烟失败；2 DSH 接缝漂移

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

function makeHostCtx(record) {
  const ctx = {
    get(name) {
      record.gets.push(name)
      return undefined // fs / sessions / shell 都不给：面板必须自行降级而不是崩
    },
    tools: {
      register(definition) {
        record.tools.push(definition && definition.name)
        return () => {}
      },
    },
    connection: {
      rpc: {
        handle(channel, handler, options) {
          record.channel = channel
          record.handler = handler
          record.options = options
          return async () => {}
        },
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

async function checkHost() {
  process.stdout.write('host 半（' + BUNDLE + '/lib/index.js）\n')
  const mod = await import(pathToFileURL(path.join(repo, BUNDLE, 'lib/index.js')).href)

  check(mod.name === 'dsh-sleuth-panels', 'export name = dsh-sleuth-panels', String(mod.name))
  check(Array.isArray(mod.inject) && mod.inject.includes('connection') && mod.inject.includes('tools'),
    'inject 含 connection + tools', JSON.stringify(mod.inject))

  const record = { gets: [], tools: [], injects: [], channel: undefined, handler: undefined }
  const ctx = makeHostCtx(record)

  const dispose = mod.apply(ctx)
  check(record.channel === CHANNEL, '注册 RPC 路由 channel = ' + CHANNEL, String(record.channel))
  check(typeof record.handler === 'function', '路由 handler 是函数')
  check(record.injects.includes('webServer'), "路由注册在 ctx.inject(['webServer']) 内")
  check(record.options !== undefined && record.options.authority === 'trusted-host',
    '路由注册带 authority: trusted-host（与 dsh-ppt 一致）', JSON.stringify(record.options))
  check(record.tools.length === 1, '注册 1 个附带工具（ascend_trace_status）', JSON.stringify(record.tools))
  check(typeof dispose === 'function', 'apply() 返回卸载函数')

  // 未知端点：分发表要回我们约定的 not-found 信封（客户端 host.call 依赖它 → 抛错）
  const unknown = await record.handler('no-such-endpoint', {})
  check(unknown && unknown.ok === false && unknown.error && unknown.error.code === 'not-found',
    '未知端点回 not-found 信封', JSON.stringify(unknown))

  // 已知端点：fs 未注入 → 面板自身的降级分支（不该抛、也不该 500）
  const known = await record.handler('ascend-traces-list', { sessionId: 'x' })
  check(known && known.ok === true && known.value && known.value.ok === false,
    '已知端点走到面板处理函数并走 fs 缺失降级', JSON.stringify(known))

  // 卸载：不抛，且之后端点全部消失
  dispose()
  const afterDispose = await record.handler('ascend-traces-list', {})
  check(afterDispose && afterDispose.ok === false, '卸载后端点已摘除', JSON.stringify(afterDispose))
}

const REACT_STUB = {
  createElement: () => null,
  Fragment: 'Fragment',
  useState: (value) => [value, () => {}],
  useEffect: () => {},
  useMemo: (factory) => factory(),
  useCallback: (fn) => fn,
  useRef: (value) => ({ current: value }),
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
    register(options) {
      registrations.push(options)
      return () => {}
    },
  }
  const clientCtx = {
    get(name) { return name === 'slots' ? slots : undefined },
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

  if (typeof dispose === 'function') dispose()
  check(styleTags.length === 0, '卸载后样式标签清空', '标签数 ' + styleTags.length)
}

function fingerprint(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 12)
}

// 保真：产物里嵌的必须是源文件原文。
// 为什么单列一条：`build_panel_bundle.js --check` 只证明"产物 == 重新生成的产物"——
// 若生成器本身的嵌入逻辑吃掉了内容，两边会一起错、门照绿。这里直接拿源文件比对。
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

// ── DSH 探针：装载路判定 + 三处接缝 ──────────────────────────────────────────
//
// 常驻插件包把面板源码接到新版 DSH 上，靠的是三个外部假设：
//   ① connection RPC 的注册形态（HostConnectionRpc.handle(channel, handler, options)）
//   ② 该 handle 由 dsh-client-connection 实现，且要求调用方 fiber 注入 webServer
//   ③ client 沙箱给每个包注入 styles.insert(css) -> disposer
// 这三处任一变化，面板都要到「装完、重启、页面空白」才被发现。这里把它们读成断言，
// 顺便判本机 DSH 有没有模型侧的 cordis_define（有 = 热加载路，无 = 常驻插件包路）。

const DSH_SEAMS = [
  {
    id: 'rpc-handle-declared',
    rel: '@deepseek-ai/dsh-tool-cordis/lib/types/api-catalog.js',
    ok: (text) => /HostConnectionRpc[\s\S]{0,200}handle\(channel/.test(text),
    note: 'connection RPC 的注册接口（handle(channel, handler)）',
  },
  {
    id: 'rpc-handler-needs-webServer',
    rel: '@deepseek-ai/dsh-client-connection/lib/index.js',
    ok: (text) => text.includes('webServer.register('),
    note: "路由注册走宿主 webServer（所以调用方 fiber 必须注入 webServer：ctx.inject(['webServer'])）",
  },
  {
    id: 'styles-insert',
    rel: '@deepseek-ai/dsh-cordis-client-runner/lib/client.js',
    ok: (text) => text.includes('styles.insert(css'),
    note: 'client 沙箱注入的样式接口（styles.insert(css) -> disposer）',
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
  const files = {
    '@deepseek-ai/dsh-tool-cordis/lib/index.js': options.legacy
      ? "defineTool({ name: 'cordis_define' }); defineTool({ name: 'cordis_run' })"
      : "defineTool({ name: 'cordis_inspect_list' }); defineTool({ name: 'cordis_inspect_query' })",
    '@deepseek-ai/dsh-tool-cordis/lib/types/api-catalog.js':
      "export interface HostConnectionRpc { handle(channel: string, handler: ConnectionRpcHandler): () => Promise<void> }",
    '@deepseek-ai/dsh-client-connection/lib/index.js':
      "return owner.effect(() => owner.webServer.register(route), `client-connection: ${channel} rpc channel`)",
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

// 探针自测：三份临时假 DSH（现代 / 旧版 / 漂移）。不需要真 DSH，所以 CI 里也能跑。
function selftestDsh() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-probe-selftest-'))
  const cases = [
    { name: '现代（无 cordis_define）', legacy: false, omitStyles: false, route: 'bundle', drift: 0 },
    { name: '旧版（有 cordis_define）', legacy: true, omitStyles: false, route: 'hot-load', drift: 0 },
    { name: '漂移（去掉 styles.insert）', legacy: false, omitStyles: true, route: 'bundle', drift: 1 },
  ]
  let bad = 0
  try {
    for (const item of cases) {
      const root = path.join(base, item.name.replace(/[（）]/g, '-'))
      writeFakeDsh(root, item)
      const probe = probeDsh(root)
      const drift = probe.seams.filter((seam) => !seam.ok).length
      const ok = probe.route === item.route && drift === item.drift
      if (!ok) bad += 1
      process.stdout.write('  ' + (ok ? 'ok  ' : 'FAIL') + ' ' + item.name
        + '：route=' + probe.route + ' 漂移=' + drift
        + '（期望 route=' + item.route + ' 漂移=' + item.drift + '）\n')
    }
  } finally {
    fs.rmSync(base, { recursive: true, force: true })
  }
  if (bad > 0) {
    process.stderr.write('DSH 探针自测未通过：' + bad + ' 例\n')
    return 1
  }
  process.stdout.write('dsh-probe selftest ok（3 例：现代 / 旧版 / 漂移）\n')
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
