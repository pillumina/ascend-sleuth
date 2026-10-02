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
// 用法：node scripts/check_panel_bundle.js

'use strict'

const fs = require('fs')
const path = require('path')
const { pathToFileURL } = require('node:url')
const { register } = require('node:module')

const repo = path.resolve(__dirname, '..')
const BUNDLE = 'dsh-plugins/dsh-sleuth-panels'
const CHANNEL = '/ascend-sleuth-panels'

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

async function main() {
  await checkHost()
  await checkClient()

  if (failures.length > 0) {
    process.stderr.write('\n面板包冒烟测试未通过（' + failures.length + ' 项）：\n')
    for (const item of failures) process.stderr.write('  - ' + item + '\n')
    process.exit(1)
  }
  process.stdout.write('\n面板包冒烟测试通过\n')
}

main().catch((error) => {
  process.stderr.write('冒烟测试异常: ' + String((error && error.stack) || error) + '\n')
  process.exit(1)
})
