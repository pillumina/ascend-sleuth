// 产物形态与注册面测试：不启动浏览器，验证 lib/client.js 这个“页面产物”本身。
//
// 覆盖：
//   1. `window.__ModuleLoader__.load({ id, factory })` 的 id 等于包名；
//   2. factory 只 require('react')，返回的插件对象带 inject/apply；
//   3. apply 注入 <style>，并在 main / sidebar.panellist 两个座位注册（id、order、label 对齐）；
//   4. 产物里没有 ESM import/export（模块加载器不接受）。
//
// 运行：node test/artifact.test.mjs
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import vm from 'node:vm'
import assert from 'node:assert/strict'

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'))
const code = readFileSync(path.join(root, 'lib', 'client.js'), 'utf8')

assert.match(code, /window\.__ModuleLoader__\.load\(/, '产物必须通过 __ModuleLoader__ 注册')
assert.doesNotMatch(code, /^\s*(import|export)\s/m, '页面产物不能含 ESM import/export')

let loaded = null
const styles = []
const fakeElement = () => ({
  tagName: '',
  dataset: {},
  style: {},
  setAttribute() {},
  remove() {},
  appendChild() {},
  getContext() {
    return {
      fillStyle: '#ffffff',
      clearRect() {},
      fillRect() {},
      getImageData() { return { data: new Uint8ClampedArray([255, 255, 255, 255]) } },
    }
  },
})

const fakeDocument = {
  documentElement: fakeElement(),
  head: { appendChild(el) { styles.push(el) } },
  body: { appendChild() {} },
  createElement() { return fakeElement() },
}

const React = {
  createElement(...args) { return { args } },
  useState(initial) { return [initial, () => {}] },
  useEffect() {},
  useRef(value) { return { current: value } },
  useMemo(fn) { return fn() },
  useCallback(fn) { return fn },
}

const sandbox = {
  console,
  window: {
    __ModuleLoader__: { load(definition) { loaded = definition } },
    matchMedia() { return { matches: false, addEventListener() {} } },
  },
  document: fakeDocument,
  navigator: { clipboard: { writeText: async () => {} } },
  getComputedStyle() { return { getPropertyValue() { return '#ffffff' } } },
  requestAnimationFrame() { return 0 },
  cancelAnimationFrame() {},
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  performance,
  Intl,
  Date,
  Math,
  JSON,
  Number,
  String,
  Object,
  Array,
  Map,
  Set,
  Promise,
  Error,
  MutationObserver: class { observe() {} disconnect() {} },
}
sandbox.globalThis = sandbox
vm.runInNewContext(code, sandbox)

assert.ok(loaded, '页面产物没有调用 __ModuleLoader__.load')
assert.equal(loaded.id, pkg.name, '产物 id 必须等于包名')

const plugin = loaded.factory((name) => {
  assert.equal(name, 'react', '页面产物只应 require("react")，实际: ' + name)
  return React
})
assert.equal(typeof plugin.apply, 'function', '插件对象必须有 apply')
assert.ok(Array.isArray(plugin.inject), '插件对象必须声明 inject')
assert.ok(plugin.inject.includes('slots'), 'inject 必须含 slots')
assert.ok(plugin.inject.includes('connection'), 'inject 必须含 connection')

const registrations = []
const injected = []
const slots = {
  inject(owner, install) {
    injected.push(owner)
    install()
    return () => {}
  },
  register(definition, component) {
    registrations.push({ definition, component })
    return () => {}
  },
}
const connection = { rpc: { call: async () => ({ ok: true, value: {} }) } }
const ctx = {
  get(name) {
    if (name === 'slots') return slots
    if (name === 'connection') return connection
    return undefined
  },
}
const dispose = plugin.apply(ctx)
assert.equal(typeof dispose, 'function', 'apply 必须返回 disposer')

assert.deepEqual(injected, ['main', 'sidebar.panellist'], '应注册 main 与 sidebar.panellist 两个座位')

const main = registrations.find((r) => r.definition.name === 'main')
assert.ok(main, '缺少 main 注册')
assert.equal(main.definition.key, 'sleuth-canvas')

const side = registrations.find((r) => r.definition.name === 'sidebar.panellist')
assert.ok(side, '缺少 sidebar.panellist 注册')
assert.equal(side.definition.id, 'sleuth-canvas')
assert.equal(side.definition.order, 40)
assert.equal(side.definition.label, '诊断画布')
assert.equal(typeof side.component, 'function', '侧栏图标必须是 React 组件')

assert.equal(styles.length, 1, 'apply 应注入一份样式表')
assert.ok(String(styles[0].textContent).length > 0, '样式表不能为空')

dispose()
assert.equal(typeof ctx.get('slots'), 'object')

console.log('artifact.test.mjs: ok (' + registrations.length + ' registrations, ' + String(styles[0].textContent).length + ' css chars)')
