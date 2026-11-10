// 知识库 tab 冒烟（开发用，不进安装产物）：不启浏览器，用最小 React 替身把整页的
// 知识库子页跑一遍，再用假 cordis ctx 装起 lib/index.js 直接发 RPC。
//
// 跑法：node dsh-plugins/dsh-sleuth-panels/test/knowledge-tab-smoke.mjs
//
// 它证明不了真实页面的排版与点击：
//   客户端：默认态 / 落后态 / 开关关闭 / 空态（无远端）/ 失败态（超时、非检出、
//           脚本缺失、远端列表读不到）/ 离线授权与已关闭 / 从未核对 / 未拉取 / 合并结果三种 /
//           保存与同步发出的 RPC 与参数 / 有未保存改动时的按钮态；
//   宿主半：三条 ascend-kb-sync-* 端点的 JSON 形状（对齐 scripts/kb_sync.py 与
//           scripts/pr_status.py 的真实输出）、失败分类、缺脚本与缺配置的降级。
// 真机渲染仍要人看。

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = join(HERE, '..')
const CLIENT_URL = pathToFileURL(join(ROOT, 'lib', 'client.js')).href
const HOST_URL = pathToFileURL(join(ROOT, 'lib', 'index.js')).href
const CHANNEL = '/ascend-sleuth-panels'

const failures = []
let passed = 0
function check(ok, label, detail) {
  if (ok) {
    passed += 1
    process.stdout.write('  ok   ' + label + '\n')
    return
  }
  failures.push(label + (detail ? ' —— ' + detail : ''))
  process.stdout.write('  FAIL ' + label + (detail ? ' —— ' + detail : '') + '\n')
}
function section(title) { process.stdout.write('\n' + title + '\n') }

// ── 最小 React 替身 ─────────────────────────────────────────────────────────
// 与 scripts/panel_render_check.js 的 mock 同一套约定：组件函数被 createElement 直接调用，
// hooks 按调用位置存在全局槽里（够跑"首屏 → 取数 → 数据态"这一条路径，不是 React 语义）。
function makeRuntime() {
  let hookIdx = 0
  const hookState = []
  const depState = []
  let effectQueue = []
  let dirty = false

  const React = {
    createElement(type, props, ...children) {
      if (typeof type === 'function') {
        const merged = Object.assign({}, props || {})
        if (children.length === 1) merged.children = children[0]
        else if (children.length > 1) merged.children = children
        return type(merged)
      }
      return { $$el: true, type, props: Object.assign({}, props || {}, {
        children: children.length === 1 ? children[0] : children,
      }) }
    },
    Fragment: 'Fragment',
    memo: (component) => component,
    useState(initial) {
      const i = hookIdx++
      if (!(i in hookState)) hookState[i] = typeof initial === 'function' ? initial() : initial
      return [hookState[i], (next) => {
        hookState[i] = typeof next === 'function' ? next(hookState[i]) : next
        dirty = true
      }]
    },
    useEffect(fn, deps) {
      const i = hookIdx++
      const prev = depState[i]
      const same = prev && Array.isArray(deps) && deps.length === prev.length
        && deps.every((d, k) => Object.is(d, prev[k]))
      if (same) return
      depState[i] = deps
      effectQueue.push(fn)
    },
    useCallback(fn, deps) {
      const i = hookIdx++
      const prev = depState[i]
      if (prev && prev.fn && Array.isArray(deps) && deps.length === prev.deps.length
        && deps.every((d, k) => Object.is(d, prev.deps[k]))) return prev.fn
      depState[i] = { fn, deps }
      return fn
    },
  }

  const tick = () => new Promise((resolve) => setImmediate(resolve))

  async function render(component, props, rounds = 10) {
    let tree = null
    for (let r = 0; r < rounds; r++) {
      hookIdx = 0
      effectQueue = []
      dirty = false
      tree = component(props)
      const queue = effectQueue.slice()
      for (const fn of queue) fn()
      await tick()
      await tick()
      if (queue.length === 0 && !dirty) break
    }
    // 最后一轮只渲染、不跑 effect：把最后一次 setState 落进树里。
    hookIdx = 0
    effectQueue = []
    tree = component(props)
    return tree
  }

  return { React, render }
}

function walk(node, visit) {
  if (node === null || node === undefined || typeof node !== 'object') return
  if (Array.isArray(node)) { node.forEach(n => walk(n, visit)); return }
  if (node.$$el) {
    visit(node)
    walk(node.props.children, visit)
  }
}
function textOf(node) {
  const out = []
  const push = (n) => {
    if (n === null || n === undefined || n === false || n === true) return
    if (Array.isArray(n)) { n.forEach(push); return }
    if (typeof n === 'string' || typeof n === 'number') { out.push(String(n)); return }
    if (n.$$el) push(n.props.children)
  }
  push(node)
  return out.join('\n')
}
function collectButtons(tree) {
  const out = []
  walk(tree, el => { if (el.type === 'button') out.push(el) })
  return out
}
function findButton(tree, needle) {
  return collectButtons(tree).filter(el => typeof el.props.onClick === 'function'
    && textOf(el).indexOf(needle) >= 0)[0] || null
}
function clickButton(tree, needle) {
  const hit = findButton(tree, needle)
  if (!hit) throw new Error('点不到「' + needle + '」；可点的有：'
    + JSON.stringify(collectButtons(tree).map(b => textOf(b).slice(0, 20))))
  hit.props.onClick({ preventDefault() {}, stopPropagation() {} })
}
function switchesOf(tree) {
  const out = []
  walk(tree, el => { if (el.type === 'button' && el.props.role === 'switch') out.push(el) })
  return out
}
function switchByLabel(tree, label) {
  return switchesOf(tree).filter(el => el.props['aria-label'] === label)[0] || null
}
function selectByLabel(tree, label) {
  return selectsOf(tree).filter(el => el.props['aria-label'] === label)[0] || null
}
function optionsOf(tree) {
  const out = []
  walk(tree, el => { if (el.type === 'option') out.push(textOf(el)) })
  return out
}
function selectsOf(tree) {
  const out = []
  walk(tree, el => { if (el.type === 'select') out.push(el) })
  return out
}
function findByProp(tree, prop, value) {
  let hit = null
  walk(tree, el => { if (el.props && String(el.props[prop]) === String(value)) hit = el })
  return hit
}
function hasClass(tree, cls) {
  let hit = false
  walk(tree, el => {
    if (el.props && typeof el.props.className === 'string' && el.props.className.split(/\s+/).includes(cls)) hit = true
  })
  return hit
}

// ── 客户端：装配整页并渲染知识库子页 ────────────────────────────────────────
const styleTags = []
const moduleDefs = []
globalThis.window = {
  __ModuleLoader__: { load: (def) => moduleDefs.push(def) },
  matchMedia: undefined,
}
globalThis.document = {
  createElement: () => ({ dataset: {}, style: {}, textContent: '', remove() {}, setAttribute() {} }),
  head: { append(tag) { styleTags.push(tag) } },
  body: { appendChild() {}, removeChild() {} },
  execCommand: () => true,
  addEventListener() {},
  removeEventListener() {},
  getElementById: () => null,
  querySelector: () => null,
}

let importSeq = 0

async function bootClient(handlers) {
  const runtime = makeRuntime()
  const registrations = []
  const calls = []
  const slots = {
    inject(name, factory) { factory(); return () => {} },
    register(options, component) { registrations.push({ options, component }); return () => {} },
  }
  const connection = {
    rpc: {
      call(channel, endpoint, payload) {
        calls.push({ channel, endpoint, payload })
        const fn = handlers[endpoint]
        return Promise.resolve({ ok: true, value: fn ? fn(payload) : { ok: true } })
      },
    },
  }
  const sessions = {
    get: () => ({ header: { cwd: ROOT } }),
    list: () => [{ header: { cwd: ROOT } }],
  }
  const ctx = {
    get(name) {
      if (name === 'slots') return slots
      if (name === 'styles') return { insert: () => () => {} }
      if (name === 'connection') return connection
      if (name === 'sessions') return sessions
      return undefined
    },
    effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} },
    inject(deps, callback) { return callback(ctx) },
    on() { return () => {} },
  }

  await import(CLIENT_URL + '?case=' + (importSeq += 1))
  const def = moduleDefs[moduleDefs.length - 1]
  const mod = def.factory((name) => {
    if (name === 'react') return runtime.React
    throw new Error('不知名的模块：' + name)
  })
  mod.apply(ctx)
  const main = registrations.filter(r => r.options && r.options.name === 'main')[0]
  if (!main) throw new Error('整页没注册 main 席位')
  return { runtime, main, calls }
}

const minutesAgo = (n) => new Date(Date.now() - n * 60000).toISOString()
const SETTINGS_SHA = 'a'.repeat(64)

// 读端形状对齐 `scripts/kb_sync.py --show --json` + `scripts/pr_status.py --json` +
// `scripts/pr_status.py --list-targets --json`：面板把三段合进一条 RPC 的返回。
function showPayload(over) {
  const base = {
    ok: true,
    cwd: '/repo',
    config_path: '.local/settings.json',
    settings_sha256: SETTINGS_SHA,
    settings: { ok: true, data: {
      config: 'file', problem: '', path: '.local/settings.json', sha256: SETTINGS_SHA,
      sync: { remote: 'origin', branch: 'main', enabled: true, auto_merge: true, check_enabled: true, check_minutes: 30, check_full_access: true },
      target: { remote: 'origin', base: 'main' },
    } },
    sync: { ok: true, state: 'ok', error: null, data: {
      remote: 'origin', branch: 'main',
      local_rev: '1a2b3c', remote_rev: '9f8e7d',
      behind: 12, ahead: 0, skipped: false,
      surface: { knowledge: 3, routing: 0, reference: 1, methodology: 0, panel: 2, other: 0 },
      last_checked: minutesAgo(3), last_reason: '',
      enabled: true, offline: false, offline_source: '', reason: '',
      same_repo: true,
      identity_remote: 'origin', identity_url: 'git@github.com:org/repo.git',
      identity_explicit: false, identity_resolved: true,
      config: { auto_check: true, auto_merge: true, check_enabled: true, check_full_access: true, check_minutes: 30, source: 'personal', path: '.local/settings.json' },
    } },
    targets: { ok: true, data: {
      remotes: [
        { name: 'origin', url: 'git@github.com:org/repo.git', host: 'github.com', base: 'main', last_used: minutesAgo(90) },
        { name: 'gitcode', url: 'git@gitcode.com:org/repo.git', host: 'gitcode.com', base: 'main', last_used: '' },
      ],
      target: { remote: 'origin', base: 'main' },
      recommendation: { remote: 'origin', base: 'main', reason: '上次选择的目标' },
    } },
  }
  return Object.assign(base, over || {})
}

section('[知识库 · 客户端] 默认态（落后 12）')
{
  const { runtime, main, calls } = await bootClient({ 'ascend-kb-sync-show': () => showPayload() })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  const showCall = calls.filter(c => c.endpoint === 'ascend-kb-sync-show')[0]
  check(!!showCall && showCall.channel === CHANNEL, '打开知识库子页发 ascend-kb-sync-show', JSON.stringify(calls.map(c => c.endpoint)))
  check(text.indexOf('知识库') >= 0 && text.indexOf('指标') >= 0 && text.indexOf('自演进') >= 0,
    '三个 tab 的入口都在（知识库 / 指标 / 自演进）', text.slice(0, 120))
  check(text.indexOf('本机版本') >= 0 && text.indexOf('v1a2b3c') >= 0, '本机版本读数', text.slice(0, 200))
  check(text.indexOf('远端版本') >= 0 && text.indexOf('v9f8e7d') >= 0, '远端版本读数')
  check(text.indexOf('落后') >= 0 && text.indexOf('12') >= 0 && text.indexOf('个提交') >= 0, '落后提交数与单位')
  check(text.indexOf('上次核对') >= 0 && /3 分钟前/.test(text), '上次核对按相对时间给', text.slice(0, 240))
  check(text.indexOf('本次合并会把') >= 0 && text.indexOf('knowledge/') >= 0 && text.indexOf('skills/') >= 0,
    '落后时提示合并范围与生效时点')
  check(text.indexOf('面板代码也会更新：重启 DSH 后生效') >= 0,
    '落后时若带面板代码，提示要重启 DSH', text.slice(0, 320))
  check(text.indexOf('同步源') >= 0, '同步源卡片在')
  const opts = optionsOf(tree)
  check(opts.some(t => t.indexOf('origin · github.com') >= 0), '远端下拉列出名字与 host', JSON.stringify(opts).slice(0, 200))
  check(text.indexOf('上次使用：') >= 0, '同步源给「上次使用」')
  check(text.indexOf('自动检查更新') >= 0 && text.indexOf('自动合并') >= 0 && text.indexOf('提醒检查') >= 0
    && text.indexOf('后台检查用完全权限') >= 0 && text.indexOf('检查间隔') >= 0,
    '四个开关与检查间隔都在')
  check(text.indexOf('来源：个人设置') >= 0, '开关来源标「个人设置」')
  check(switchByLabel(tree, '自动检查更新') && switchByLabel(tree, '自动检查更新').props['aria-checked'] === 'true',
    '自动检查更新默认开（aria-checked=true）')
  check(switchByLabel(tree, '提醒检查') && switchByLabel(tree, '提醒检查').props['aria-checked'] === 'true',
    '提醒检查默认开（aria-checked=true）')
  check(switchByLabel(tree, '后台检查用完全权限')
    && switchByLabel(tree, '后台检查用完全权限').props['aria-checked'] === 'true',
    '后台检查用完全权限默认开（aria-checked=true）')
  check(selectByLabel(tree, '检查间隔') && selectByLabel(tree, '检查间隔').props.value === '30',
    '检查间隔默认 30 分钟')
  check(text.indexOf('.local/settings.json') >= 0 && text.indexOf('修改下次开单生效') >= 0, '页脚给配置路径与生效时点')
  check(text.indexOf('打开本页不联网') >= 0, '页脚说明打开本页不联网')
  // 归属仓：页脚常驻一行，默认 origin 未显式配置时标「默认」。
  check(text.indexOf('归属仓：origin（git@github.com:org/repo.git） · 默认') >= 0,
    '页脚常驻归属仓一行（名字 + 地址 + 默认）', text.slice(-320))
  check(!!findButton(tree, '修改'), '归属仓行给「修改」入口')
  clickButton(tree, '修改')
  const identityOpen = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const idSelect = selectsOf(identityOpen).filter(el => el.props['aria-label'] === '归属仓远端')[0]
  check(!!idSelect && optionsOf(identityOpen).some(t => t.indexOf('gitcode · gitcode.com') >= 0),
    '「修改」在同排展开远端下拉（名字 · host）', JSON.stringify(optionsOf(identityOpen)))
  check(!!findButton(identityOpen, '设为归属仓'), '展开后给「设为归属仓」按钮')

  // 保存：没有改动时禁用；改一个开关后可用，并把草稿与 CAS 指纹原样发出去。
  const saveBefore = findButton(tree, '保存')
  check(!!saveBefore && saveBefore.props.disabled === true, '没有改动时「保存」禁用')
  switchByLabel(tree, '自动检查更新').props.onClick()
  const afterToggle = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  check(textOf(afterToggle).indexOf('有未保存的改动') >= 0, '改动后提示未保存')
  const saveAfter = findButton(afterToggle, '保存')
  check(!!saveAfter && saveAfter.props.disabled === false, '有改动时「保存」可用')
  clickButton(afterToggle, '保存')
  const saved = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const saveCall = calls.filter(c => c.endpoint === 'ascend-kb-sync-save').pop()
  check(!!saveCall, '点「保存」发 ascend-kb-sync-save')
  check(!!saveCall && saveCall.payload.remote === 'origin' && saveCall.payload.branch === 'main',
    '保存带上远端与分支', JSON.stringify(saveCall && saveCall.payload))
  check(!!saveCall && saveCall.payload.autoCheck === false && saveCall.payload.autoMerge === true,
    '保存带上自动检查更新与自动合并的当前值', JSON.stringify(saveCall && saveCall.payload))
  check(!!saveCall && saveCall.payload.checkEnabled === true && saveCall.payload.checkMinutes === 30,
    '保存带上提醒检查与检查间隔的当前值', JSON.stringify(saveCall && saveCall.payload))
  check(!!saveCall && saveCall.payload.checkFullAccess === true,
    '保存带上后台检查用完全权限的当前值', JSON.stringify(saveCall && saveCall.payload))
  check(!!saveCall && saveCall.payload.expectSha256 === SETTINGS_SHA,
    '保存带上设置指纹（CAS）', JSON.stringify(saveCall && saveCall.payload))
  check(textOf(saved).indexOf('.local/settings.json') >= 0, '保存后仍显示配置落点')

  clickButton(saved, '立即同步')
  await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  check(calls.some(c => c.endpoint === 'ascend-kb-sync-merge'), '点「立即同步」发 ascend-kb-sync-merge',
    JSON.stringify(calls.map(c => c.endpoint)))
}

section('[知识库 · 客户端] 提醒检查开关与检查间隔')
{
  // 间隔从 config 读回（60），关掉提醒检查后下拉禁用；保存 payload 带这两个字段。
  const payload = showPayload()
  payload.sync.data.config = {
    auto_check: true, auto_merge: true, check_enabled: true, check_minutes: 60,
    source: 'personal', path: '.local/settings.json',
  }
  const { runtime, main, calls } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  let tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const checkSwitch = switchByLabel(tree, '提醒检查')
  check(!!checkSwitch && checkSwitch.props['aria-checked'] === 'true', '提醒检查按 config 回读为开',
    JSON.stringify(checkSwitch && checkSwitch.props))
  const interval = selectByLabel(tree, '检查间隔')
  check(!!interval && interval.props.value === '60' && interval.props.disabled === false,
    '检查间隔按 config 回读 60 分钟且可改', JSON.stringify(interval && interval.props))
  const minuteOpts = optionsOf(tree)
  check(minuteOpts.some(t => t.indexOf('15 分钟') >= 0) && minuteOpts.some(t => t.indexOf('30 分钟') >= 0)
    && minuteOpts.some(t => t.indexOf('60 分钟') >= 0) && minuteOpts.some(t => t.indexOf('120 分钟') >= 0),
    '检查间隔下拉给 15/30/60/120', JSON.stringify(minuteOpts))

  // 改间隔 → dirty；保存带 120。
  interval.props.onChange({ target: { value: '120' } })
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  check(textOf(tree).indexOf('有未保存的改动') >= 0, '改检查间隔后提示未保存')
  check(selectByLabel(tree, '检查间隔').props.value === '120', '检查间隔草稿更新为 120')
  clickButton(tree, '保存')
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  let saveCall = calls.filter(c => c.endpoint === 'ascend-kb-sync-save').pop()
  check(!!saveCall && saveCall.payload.checkEnabled === true && saveCall.payload.checkMinutes === 120,
    '保存 payload 带提醒检查打开与 120 分钟', JSON.stringify(saveCall && saveCall.payload))

  // 关掉提醒检查 → 间隔下拉禁用；保存 payload checkEnabled=false。
  switchByLabel(tree, '提醒检查').props.onClick()
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  check(switchByLabel(tree, '提醒检查').props['aria-checked'] === 'false', '提醒检查可关（aria-checked=false）')
  check(selectByLabel(tree, '检查间隔').props.disabled === true, '提醒检查关闭时间隔下拉禁用')
  clickButton(tree, '保存')
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  saveCall = calls.filter(c => c.endpoint === 'ascend-kb-sync-save').pop()
  check(!!saveCall && saveCall.payload.checkEnabled === false && saveCall.payload.checkMinutes === 120,
    '保存 payload 带提醒检查关闭', JSON.stringify(saveCall && saveCall.payload))
}

{
  // 设置里是下拉之外的整数（命令行写的 45）：照实显示并放进选项，不静默改成 30。
  const payload = showPayload()
  payload.sync.data.config = {
    auto_check: true, auto_merge: true, check_enabled: true, check_minutes: 45,
    source: 'personal', path: '.local/settings.json',
  }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  check(selectByLabel(tree, '检查间隔').props.value === '45', '非预设间隔照实显示为 45')
  check(optionsOf(tree).some(t => t.indexOf('45 分钟') >= 0), '非预设间隔放进下拉选项', JSON.stringify(optionsOf(tree)))
}

section('[知识库 · 客户端] 已是最新 / 开关关闭')
{
  const payload = showPayload()
  payload.sync.data.behind = 0
  payload.sync.data.config = { auto_check: false, auto_merge: true, source: 'personal' }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('本机与远端一致') >= 0, '落后 0 时给「一致」提示', text.slice(0, 200))
  check(switchByLabel(tree, '自动检查更新').props['aria-checked'] === 'false', '开关关闭时 aria-checked=false')
  check(switchByLabel(tree, '自动合并').props['aria-checked'] === 'true', '另一个开关保持打开')
}

section('[知识库 · 客户端] 同源校验：不是同一个仓')
{
  const payload = showPayload()
  payload.sync.data.same_repo = false
  const { runtime, main, calls } = await bootClient({
    'ascend-kb-sync-show': () => payload,
    'ascend-kb-sync-identity': () => ({ ok: true, identity: { remote: 'origin' }, sha256: SETTINGS_SHA }),
  })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('同步源与归属仓不同源') >= 0, '同源校验不一致时给一行说明', text.slice(0, 240))
  check((text.match(/同步源与归属仓不同源/g) || []).length === 1,
    '同源校验不一致只出一条提示（不再叠第二条）', text.slice(0, 320))
  check(text.indexOf('这个远端不是同一个仓') < 0, '不再有第二条重复提示')
  check(text.indexOf('把同步源设为归属仓，或把同步源换到与归属仓同源的远端。') >= 0,
    '提示里给一句可执行的下一步')
  check(!!findButton(tree, '把 origin 设为归属仓'), '提示里给「把 origin 设为归属仓」按钮')
  check(text.indexOf('归属仓：origin（git@github.com:org/repo.git） · 默认') >= 0,
    '页脚常驻归属仓一行仍读事实')
  check(text.indexOf('与同步源不同源') >= 0, '页脚这行标出与同步源不同源')
  check(text.indexOf('未知错误') < 0, '同源校验不一致不写「未知错误」')

  clickButton(tree, '把 origin 设为归属仓')
  const afterSet = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const idCall = calls.filter(c => c.endpoint === 'ascend-kb-sync-identity').pop()
  check(!!idCall && idCall.payload.remote === 'origin' && idCall.payload.expectSha256 === SETTINGS_SHA,
    '按钮发 ascend-kb-sync-identity，带上远端与 CAS 指纹', JSON.stringify(idCall && idCall.payload))
  check(textOf(afterSet).indexOf('已把 origin 设为归属仓。') >= 0, '设置成功后给一条成功提示')
}

section('[知识库 · 客户端] 归属仓解析不到')
{
  // `--show` 的读端形状：ok=true、same_repo=null，identity_explicit=true 且 identity_resolved=false
  // （reason identity-unresolved 只在合并结果里出现）。
  const payload = showPayload()
  payload.sync.data.same_repo = null
  payload.sync.data.identity_remote = 'gitcode'
  payload.sync.data.identity_url = ''
  payload.sync.data.identity_explicit = true
  payload.sync.data.identity_resolved = false
  const { runtime, main, calls } = await bootClient({
    'ascend-kb-sync-show': () => payload,
    'ascend-kb-sync-identity': () => ({ ok: true, identity: { remote: 'origin' }, sha256: SETTINGS_SHA }),
  })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('归属仓解析不到，未自动合并') >= 0, '解析不到给一句原因', text.slice(0, 240))
  check(text.indexOf('改回 origin（默认），或把该远端补回来。') >= 0, '解析不到给可执行的下一步')
  check(!!findButton(tree, '改回 origin'), '解析不到给「改回 origin」按钮')
  check(text.indexOf('归属仓：gitcode（git@gitcode.com:org/repo.git）') >= 0
    && text.indexOf('解析不到') >= 0, '页脚归属仓一行标出解析不到', text.slice(-260))
  clickButton(tree, '改回 origin')
  await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const idCall = calls.filter(c => c.endpoint === 'ascend-kb-sync-identity').pop()
  check(!!idCall && idCall.payload.remote === 'origin', '「改回 origin」走同一个设置端点',
    JSON.stringify(idCall && idCall.payload))
}

section('[知识库 · 客户端] 默认 origin 不存在：不误报解析不到')
{
  // 单远端检出（同步源叫 gitcode，没有 origin）：默认 origin 解析不到但未显式配置，
  // 后端按设计放行合并；面板不能报「归属仓解析不到，未自动合并」。
  const payload = showPayload()
  payload.sync.data.remote = 'gitcode'
  payload.sync.data.same_repo = null
  payload.sync.data.identity_remote = 'origin'
  payload.sync.data.identity_url = ''
  payload.sync.data.identity_explicit = false
  payload.sync.data.identity_resolved = false
  payload.sync.data.behind = 0
  payload.targets.data.remotes = [
    { name: 'gitcode', url: 'git@gitcode.com:org/repo.git', host: 'gitcode.com', base: 'main', last_used: '' },
  ]
  payload.targets.data.target = { remote: 'gitcode', base: 'main' }
  payload.targets.data.recommendation = { remote: 'gitcode', base: 'main', reason: '上次选择的目标' }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('归属仓解析不到') < 0, '默认 origin 解析不到不报身份异常', text.slice(0, 260))
  check(!findButton(tree, '改回 origin'), '默认 origin 解析不到不给「改回 origin」')
  check(text.indexOf('解析不到') < 0, '页脚不标「解析不到」', text.slice(-260))
  check(text.indexOf('归属仓：origin（地址未知） · 默认') >= 0,
    '页脚仍如实写默认归属仓（地址未知）', text.slice(-260))
  check(text.indexOf('本机与远端一致') >= 0, '其余状态照常显示', text.slice(0, 200))
}

section('[知识库 · 客户端] 同步进行中：保留页面，不换骨架屏')
{
  let resolveMerge = null
  const mergePromise = new Promise((resolve) => { resolveMerge = resolve })
  const { runtime, main } = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => mergePromise,
  })
  let tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(tree, '立即同步')
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const busyText = textOf(tree)
  check(busyText.indexOf('读取本机状态') < 0, '同步进行中不显示骨架屏', busyText.slice(0, 200))
  check(busyText.indexOf('本机版本') >= 0 && busyText.indexOf('v1a2b3c') >= 0,
    '同步进行中已有读数还在', busyText.slice(0, 240))
  check(busyText.indexOf('同步中') >= 0, '进行中按钮文案为「同步中」', busyText.slice(-320))
  check(hasClass(tree, 'sleu-kb-spin'), '进行中按钮带 spinner', JSON.stringify(collectButtons(tree).map(b => textOf(b).slice(0, 20))))
  check(!!findByProp(tree, 'aria-busy', 'true'), '进行中整块标 aria-busy')
  check(switchByLabel(tree, '自动检查更新').props.disabled === true, '进行中禁用开关')
  check(selectsOf(tree).every(el => el.props.disabled === true), '进行中禁用下拉')
  check(!!findButton(tree, '保存') && findButton(tree, '保存').props.disabled === true, '进行中禁用保存')
  check(!findButton(tree, '设为归属仓'), '进行中不展开归属仓设置')

  resolveMerge({ ok: true, merged: false, reason_code: '', reason_text: '' })
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const doneText = textOf(tree)
  check(doneText.indexOf('已经是最新，没有要合并的提交') >= 0, '动作结束后结果提示落到页面上',
    doneText.slice(0, 240))
  check(doneText.indexOf('v1a2b3c') >= 0 && doneText.indexOf('读取本机状态') < 0,
    '动作后的刷新不再闪骨架屏')
}

section('[知识库 · 客户端] 空态：没有远端')
{
  const payload = showPayload()
  payload.targets = { ok: true, data: { remotes: [], target: null, recommendation: null } }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('本机没有配置远端') >= 0, '无远端时给一句说明', text.slice(0, 200))
  check(text.indexOf('git remote add origin') >= 0, '无远端时给可复制的命令')
  check(text.indexOf('同步源无处可选') >= 0, '不再显示假的同步源')
  check(text.indexOf('未知错误') < 0, '不写「未知错误」')
}

section('[知识库 · 客户端] 失败态：超时 / 非检出 / 脚本缺失')
{
  for (const item of [
    { code: 'E_TIMEOUT', want: '请求超时' },
    { code: 'E_NOT_GIT', want: '当前目录不是 git 检出' },
    { code: 'E_NO_SCRIPT', want: '本机检出里没有同步脚本' },
  ]) {
    const payload = showPayload()
    payload.sync = { ok: false, code: item.code, message: '原值不该直接上屏', detail: 'raw detail' }
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf(item.want) >= 0, item.code + ' → 「' + item.want + '」', text.slice(0, 200))
    check(text.indexOf('未知错误') < 0, item.code + ' 不写「未知错误」')
    check(text.indexOf('raw detail') >= 0, item.code + ' 原文保留在 detail 行')
  check(!!findButton(tree, '重试'), item.code + ' 给「重试」入口')
  }
}

section('[知识库 · 客户端] 失败态：远端列表读不到')
{
  const payload = showPayload()
  payload.targets = { ok: false, code: 'E_NO_SCRIPT', message: '脚本 scripts/pr_status.py 不存在' }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('读不到远端列表') >= 0, '远端列表失败时说明这一段的缺口', text.slice(0, 200))
  check(text.indexOf('本机没有配置远端') < 0, '远端列表失败不冒充「没有远端」')
  check(text.indexOf('同步源') >= 0, '同步源卡片仍在（其余读数不受影响）')
}

section('[知识库 · 客户端] 状态：离线授权 / 已关闭 / 从未核对 / 未拉取')
{
  const offline = showPayload()
  offline.sync.state = 'offline'
  offline.sync.error = { code: 'E_OFFLINE', message: '离线部署（deployment.yaml）' }
  offline.sync.data.offline = true
  offline.sync.data.offline_source = 'deployment.yaml'
  offline.sync.data.reason = 'offline'
  {
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => offline })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf('离线部署（deployment.yaml）') >= 0, '离线部署给一句状态', text.slice(0, 200))
    check(text.indexOf('来源：部署声明（offline）') >= 0, '开关来源标「部署声明（offline）」')
    check(switchesOf(tree).every(el => el.props.disabled === true), '离线时三个开关都禁用')
  }
  const disabled = showPayload()
  disabled.sync.state = 'disabled'
  disabled.sync.error = { code: 'E_DISABLED', message: '同步已关闭（个人设置）' }
  disabled.sync.data.enabled = false
  disabled.sync.data.reason = 'disabled'
  disabled.sync.data.config = { auto_check: false, auto_merge: true, check_enabled: true, check_minutes: 30, source: 'personal' }
  {
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => disabled })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf('已关闭（个人设置）') >= 0, '个人设置关闭时给「已关闭」状态', text.slice(0, 200))
    check(switchByLabel(tree, '自动检查更新').props['aria-checked'] === 'false', '关闭时开关显示关闭')
    // 「自动检查更新」只管自动路径：手动同步走 --merge --force，不受它拦。
    check(!!findButton(tree, '立即同步'), '已关闭仍给「立即同步」（手动同步不受这个开关影响）')
    check(text.indexOf('后台提醒检查与「立即同步」不受这个开关影响') >= 0,
      '已关闭时说明提醒检查与手动同步不受影响', text.slice(0, 320))
  }
  const never = showPayload()
  never.sync.data.last_checked = null
  never.sync.data.behind = null
  {
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => never })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf('从未核对') >= 0, '从未核对时如实显示')
    check(text.indexOf('还没有核对过远端') >= 0, '从未核对时给下一步')
  }
  const unreadable = showPayload()
  unreadable.sync.data.behind = null
  unreadable.sync.data.last_checked = minutesAgo(5)
  {
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => unreadable })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf('读不到落后的提交数') >= 0, '落后数读不出时明说读不出', text.slice(0, 200))
    check(text.indexOf('读不出') >= 0, '数值格写「读不出」而不是 0')
  }
  const unfetched = showPayload()
  unfetched.sync.state = 'unfetched'
  unfetched.sync.data.remote_rev = ''
  unfetched.sync.data.behind = null
  unfetched.sync.data.last_checked = null
  {
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => unfetched })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf('远端分支还没拉取过（origin/main）') >= 0, '还没拉取过远端时给一句状态', text.slice(0, 200))
  }
}

section('[知识库 · 客户端] 同步结果：成功 / 未自动合并 / 失败')
{
  const { runtime, main } = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({ ok: true, merged: true, merged_rev: '9f8e7d', previous_rev: '1a2b3c', behind: 12,
      surface: { knowledge: 3, routing: 0, reference: 1, methodology: 0, panel: 2, other: 0 } }),
  })
  let tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(tree, '立即同步')
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('已同步到 v9f8e7d') >= 0, '成功提示给到目标版本', text.slice(0, 240))
  check(text.indexOf('原 v1a2b3c') >= 0 && text.indexOf('落后 12 个提交') >= 0, '成功提示给到原版本与差数')
  check(text.indexOf('git reset --hard ORIG_HEAD') >= 0, '成功提示给回滚命令')
  check(text.indexOf('面板代码也更新了：重启 DSH 后生效') >= 0,
    '同步带进面板代码时，成功提示说清要重启 DSH', text.slice(0, 320))

  const notMerged = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({
      ok: true, merged: false, reason_code: 'E_AUTO_MERGE_OFF', reason_text: '自动合并已关闭',
    }),
  })
  let t2 = await notMerged.runtime.render(notMerged.main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(t2, '立即同步')
  t2 = await notMerged.runtime.render(notMerged.main.component, { view: 'knowledge', sessionId: 's1' })
  check(textOf(t2).indexOf('没有自动合并：自动合并已关闭') >= 0, '未自动合并时把原因写出来',
    textOf(t2).slice(0, 240))

  const sameRepoMerge = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({
      ok: true, merged: false, reason_code: 'E_SAME_REPO', reason_text: '配置远端与 origin 不同源',
    }),
  })
  let t5 = await sameRepoMerge.runtime.render(sameRepoMerge.main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(t5, '立即同步')
  t5 = await sameRepoMerge.runtime.render(sameRepoMerge.main.component, { view: 'knowledge', sessionId: 's1' })
  check(textOf(t5).indexOf('同步源与归属仓不同源，未自动合并') >= 0,
    '同源校验不一致时不给合并，并写清原因', textOf(t5).slice(0, 240))
  check(!!findButton(t5, '把 origin 设为归属仓'), '同源校验不一致的提示带「设为归属仓」按钮')

  const nothing = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({ ok: true, merged: false, reason_code: '', reason_text: '' }),
  })
  let t4 = await nothing.runtime.render(nothing.main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(t4, '立即同步')
  t4 = await nothing.runtime.render(nothing.main.component, { view: 'knowledge', sessionId: 's1' })
  check(textOf(t4).indexOf('已经是最新，没有要合并的提交') >= 0, '没有可合并的提交时给「已经是最新」',
    textOf(t4).slice(0, 240))

  const failed = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({ ok: false, code: 'E_TIMEOUT', detail: 'stderr 原文' }),
  })
  let t3 = await failed.runtime.render(failed.main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(t3, '立即同步')
  t3 = await failed.runtime.render(failed.main.component, { view: 'knowledge', sessionId: 's1' })
  const failText = textOf(t3)
  check(failText.indexOf('同步失败：请求超时') >= 0, '同步失败按原因给中文', failText.slice(0, 240))
  check(failText.indexOf('stderr 原文') >= 0, '同步失败保留脚本原文')
  check(failText.indexOf('未知错误') < 0, '同步失败不写「未知错误」')
}

section('[知识库 · 客户端] 失败态：网络原因与 git 原始输出')
{
  const failed = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({
      ok: false, code: 'E_NETWORK', message: '连不上远端（网络或代理）',
      detail: "fatal: unable to access 'https://github.com/org/repo.git/': "
        + 'Failed to connect to 127.0.0.1 port 7897: Connection refused',
    }),
  })
  let tree = await failed.runtime.render(failed.main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(tree, '立即同步')
  tree = await failed.runtime.render(failed.main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('同步失败：连不上远端') >= 0, '网络失败按原因给中文', text.slice(0, 240))
  check(text.indexOf('Failed to connect to 127.0.0.1 port 7897') >= 0,
    '网络失败显示 git 原始输出', text.slice(0, 360))
  check(text.indexOf('检查网络与代理') >= 0, '网络失败给可执行动作', text.slice(0, 360))

  // 旧脚本被失败缓存挡下：没重试，不是同步失败。
  const cached = await bootClient({
    'ascend-kb-sync-show': () => showPayload(),
    'ascend-kb-sync-merge': () => ({
      ok: false, code: 'E_SKIPPED', message: '10 分钟内的失败还在缓存里，本次没有重试',
      detail: 'fatal: 上一次的失败',
    }),
  })
  let cachedTree = await cached.runtime.render(cached.main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(cachedTree, '立即同步')
  cachedTree = await cached.runtime.render(cached.main.component, { view: 'knowledge', sessionId: 's1' })
  const cachedText = textOf(cachedTree)
  check(cachedText.indexOf('本次没有重试') >= 0, '缓存跳过时说明本次没有重试', cachedText.slice(0, 240))
  check(cachedText.indexOf('同步失败：') < 0, '缓存跳过不报同步失败', cachedText.slice(0, 240))
  check(cachedText.indexOf('fatal: 上一次的失败') >= 0, '缓存跳过仍带上次的原始输出', cachedText.slice(0, 360))
}

section('[知识库 · 客户端] 上次同步失败：重新打开本页仍显示原因')
{
  const payload = showPayload()
  payload.sync.data.last_reason = 'network'
  payload.sync.data.last_error = "fatal: unable to access 'https://github.com/org/repo.git/': "
    + 'Failed to connect to 127.0.0.1 port 7897: Connection refused'
  payload.sync.data.last_failure = { code: 'E_NETWORK', message: '连不上远端（网络或代理）' }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('上次同步失败：连不上远端') >= 0, '失败原因重新打开也显示', text.slice(0, 260))
  check(text.indexOf('Failed to connect to 127.0.0.1 port 7897') >= 0,
    '失败 banner 带 git 原始输出', text.slice(0, 400))
}

section('[知识库 · 客户端] 后台检查失败：与同步失败分开说，给真实原因')
{
  const payload = showPayload()
  payload.sync.data.last_reason = 'credential'
  payload.sync.data.last_error = 'Host key verification failed.'
  payload.sync.data.last_source = 'check'
  payload.sync.data.last_failure = { code: 'E_CREDENTIAL', message: '拿不到 git 凭据（SSH 密钥或 known_hosts 读不到）' }
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('上次后台检查失败：拿不到 git 凭据') >= 0, '后台检查失败不冒充「同步失败」', text.slice(0, 260))
  check(text.indexOf('Host key verification failed.') >= 0, '失败 banner 带 ssh 自己的原因行', text.slice(0, 420))
  check(text.indexOf('python3 scripts/kb_sync.py --merge --force') >= 0,
    '拿不到凭据时给终端核对命令', text.slice(0, 520))
}

section('[知识库 · 客户端] 提醒检查已关闭：后台检查失败只留一句说明')
{
  const payload = showPayload()
  payload.sync.data.last_reason = 'credential'
  payload.sync.data.last_error = 'Host key verification failed.'
  payload.sync.data.last_source = 'check'
  payload.sync.data.last_failure = { code: 'E_CREDENTIAL', message: '拿不到 git 凭据（SSH 密钥或 known_hosts 读不到）' }
  payload.sync.data.config = Object.assign({}, payload.sync.data.config, { check_enabled: false })
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('提醒检查已关闭，上次后台检查失败') >= 0,
    '关掉提醒检查后不再用失败横幅，改为一句说明', text.slice(0, 300))
}

section('[知识库 · 客户端] 凭据失败：提示按「后台检查用完全权限」分流')
{
  const base = () => {
    const payload = showPayload()
    payload.sync.data.last_reason = 'credential'
    payload.sync.data.last_error = 'Host key verification failed.'
    payload.sync.data.last_source = 'check'
    payload.sync.data.last_failure = { code: 'E_CREDENTIAL', message: '拿不到 git 凭据（SSH 主机密钥校验失败或密钥不可用，或 https 认证失败）' }
    return payload
  }
  const offPayload = base()
  offPayload.sync.data.config = Object.assign({}, offPayload.sync.data.config, { check_full_access: false })
  const off = await bootClient({ 'ascend-kb-sync-show': () => offPayload })
  const offTree = await off.runtime.render(off.main.component, { view: 'knowledge', sessionId: 's1' })
  const offText = textOf(offTree)
  check(offText.indexOf('后台检查没开完全权限') >= 0 && offText.indexOf('「后台检查用完全权限」') >= 0,
    '没开完全权限时，提示指到开关', offText.slice(0, 620))

  const onPayload = base()
  const on = await bootClient({ 'ascend-kb-sync-show': () => onPayload })
  const onTree = await on.runtime.render(on.main.component, { view: 'knowledge', sessionId: 's1' })
  const onText = textOf(onTree)
  check(onText.indexOf('当前设置已用完全权限') >= 0 && onText.indexOf('复核 git 凭据') >= 0
    && onText.indexOf('上次失败可能发生在打开开关之前') >= 0,
    '已用完全权限仍失败时，提示去终端复核凭据并说明可能是旧失败', onText.slice(0, 680))
}

// ── 宿主半：用假 ctx 装 lib/index.js，直接走 RPC ────────────────────────────
function makeShell(plan) {
  const commands = []
  return {
    commands,
    resolve: (spec) => spec,
    run: async (spec) => {
      const command = String((spec && spec.command) || '')
      commands.push(command)
      if (/--version/.test(command)) {
        return { exitCode: 0, stdout: { text: 'Python 3.13.0' }, stderr: { text: '' }, timedOut: false }
      }
      return plan(command)
    },
  }
}
const okStdout = (text) => ({ exitCode: 0, stdout: { text }, stderr: { text: '' }, timedOut: false })
const failStdout = (exitCode, stderr, timedOut) => ({
  exitCode, stdout: { text: '' }, stderr: { text: stderr }, timedOut: !!timedOut,
})

async function bootHost(plan) {
  const mod = await import(HOST_URL + '?host=' + (importSeq += 1))
  const shell = makeShell(plan)
  const record = { route: null }
  const sessions = {
    get: () => ({ header: { cwd: ROOT } }),
    list: () => [{ header: { cwd: ROOT } }],
  }
  const ctx = {
    get(name) {
      if (name === 'connection') return { requestRejection: () => undefined }
      if (name === 'sessions') return sessions
      if (name === 'shell') return shell
      return undefined
    },
    tools: { register() { return () => {} } },
    webServer: { register(route) { record.route = route; return async () => {} } },
    inject(deps, callback) { return callback(ctx) },
    effect(fn) { const d = fn(); return typeof d === 'function' ? d : () => {} },
    on() { return () => {} },
  }
  mod.apply(ctx)
  return { call: (endpoint, payload) => callRoute(record.route, endpoint, payload), shell }
}

function callRoute(route, endpoint, payload) {
  return new Promise((resolve, reject) => {
    const body = Buffer.from(JSON.stringify({
      type: 'client-request', rpcId: 'r-smoke', method: endpoint, payload: payload || {},
    }))
    const req = {
      method: 'POST',
      url: CHANNEL + '/' + endpoint,
      async *[Symbol.asyncIterator]() { yield body },
    }
    const res = {
      statusCode: 0,
      headers: {},
      setHeader() {},
      writeHead(code) { this.statusCode = code },
      end(text) {
        let parsed = null
        try { parsed = JSON.parse(String(text)) } catch (e) { parsed = null }
        resolve({ statusCode: this.statusCode || 200, parsed })
      },
    }
    Promise.resolve(route.handler(req, res)).catch(reject)
  })
}
function valueOf(out) {
  return out && out.parsed && out.parsed.result ? out.parsed.result.value : undefined
}

// 形状对齐脚本真实输出（字段名以 scripts/kb_sync.py 与 scripts/pr_status.py 为准）。
// 三个状态字段是脚本的真实取值：enabled（开关）、offline（部署声明）、reason（本次结果）；
// same_repo 是同源校验结果。`last_checked` 是面板从 last_ok_at / attempted_at 映射出的读数，
// 只出现在上面 showPayload() 的 sync.data 里，不是 `--show --json` 的原始字段。
const showDoc = {
  ok: true,
  enabled: true,
  offline: false,
  reason: '',
  remote: 'origin', branch: 'main',
  local_rev: '1a2b3c', remote_rev: '9f8e7d',
  behind: 12, ahead: 0,
  surface: { knowledge: 3, reference: 1, methodology: 0, panel: 2 },
  merge: 'none', skipped: false, config: 'file',
  same_repo: true,
  identity_remote: 'origin', identity_url: 'git@github.com:org/repo.git',
  identity_explicit: false, identity_resolved: true,
  local_rev_before: '1a2b3c', behind_before: 12,
  last_ok_at: '2026-11-04T14:30:00+08:00', attempted_at: '2026-11-04T14:30:00+08:00',
  last_reason: '', config_error: '',
}
const settingsDoc = {
  ok: true,
  ledger: {},
  sha256: null,
  settings: {
    path: '.local/settings.json', config: 'file', problem: '',
    sync: { remote: 'origin', branch: 'main', enabled: true, auto_merge: true, check_enabled: false, check_minutes: 15, check_full_access: false },
    target: { remote: 'origin', base: 'main' },
  },
  settings_sha256: SETTINGS_SHA,
}
const targetsDoc = {
  ok: true,
  target: { remote: 'origin', base: 'main' },
  remotes: [
    { name: 'origin', url: 'git@github.com:org/repo.git', host: 'github.com', base: 'main', last_used: '2026-11-04T13:00:00+08:00' },
  ],
  recommendation: { remote: 'origin', base: 'main', reason: '上次选择的目标' },
  sha256: null,
}

function defaultPlan(overrides) {
  const map = Object.assign({
    'kb_sync --show': () => okStdout(JSON.stringify(showDoc)),
    'pr_status --json': () => okStdout(JSON.stringify(settingsDoc)),
    'pr_status --list-targets': () => okStdout(JSON.stringify(targetsDoc)),
    'kb_sync --merge': () => okStdout(JSON.stringify({
      ok: true, merge: 'ff-only', local_rev: '9f8e7d', local_rev_before: '1a2b3c',
      behind_before: 12, behind: 0, reason: '',
    })),
    'pr_status --set-sync': () => okStdout(JSON.stringify({
      ok: true, sync: { remote: 'origin', branch: 'main', enabled: true, auto_merge: true },
      config: 'file', config_problem: '', settings: '.local/settings.json', sha256: 'b'.repeat(64),
    })),
    'pr_status --set-identity': () => okStdout(JSON.stringify({
      ok: true,
      identity: { remote: 'gitcode', url: 'git@gitcode.com:org/repo.git', explicit: true, resolved: true },
      sha256: 'c'.repeat(64),
    })),
  }, overrides || {})
  return (command) => {
    // `pr_status --list-targets` 也带 --json，先判更长的那个。
    if (/pr_status\.py --list-targets/.test(command)) return map['pr_status --list-targets'](command)
    if (/pr_status\.py --set-sync/.test(command)) return map['pr_status --set-sync'](command)
    if (/pr_status\.py --set-identity/.test(command)) return map['pr_status --set-identity'](command)
    if (/pr_status\.py --json/.test(command)) return map['pr_status --json'](command)
    if (/kb_sync\.py --show/.test(command)) return map['kb_sync --show'](command)
    if (/kb_sync\.py --merge/.test(command)) return map['kb_sync --merge'](command)
    return failStdout(1, 'unexpected command: ' + command)
  }
}

section('[知识库 · host] 正常读取')
{
  const host = await bootHost(defaultPlan())
  const shown = await host.call('ascend-kb-sync-show', { sessionId: 's1' })
  const value = valueOf(shown)
  check(shown.parsed && shown.parsed.result.ok === true, 'show：RPC 信封 ok')
  check(!!value && value.ok === true && value.sync.ok === true && value.sync.state === 'ok',
    'show：同步段读到且状态为 ok', JSON.stringify(value && value.sync).slice(0, 200))
  check(!!value && value.sync.data.local_rev === '1a2b3c' && value.sync.data.remote_rev === '9f8e7d'
    && value.sync.data.behind === 12 && value.sync.data.last_checked === showDoc.last_ok_at,
    'show：四个读数的原值都带出来', JSON.stringify(value && value.sync.data).slice(0, 260))
  check(!!value && value.sync.data.surface && Number(value.sync.data.surface.panel) === 2,
    'show：改动面带出 panel 计数（面板据此预告要重启 DSH）',
    JSON.stringify(value && value.sync.data.surface))
  check(!!value && value.sync.data.enabled === true && value.sync.data.offline === false
    && value.sync.data.reason === '' && value.sync.data.same_repo === true,
    'show：enabled / offline / reason / same_repo 按脚本字段带出',
    JSON.stringify(value && value.sync.data).slice(0, 260))
  check(!!value && value.sync.data.identity_remote === 'origin'
    && value.sync.data.identity_url === 'git@github.com:org/repo.git'
    && value.sync.data.identity_explicit === false && value.sync.data.identity_resolved === true,
    'show：归属仓四项原样带出（不改名）', JSON.stringify(value && value.sync.data).slice(0, 320))
  check(!!value && value.sync.data.identity_remote
    && value.sync.data.identity_explicit === false, 'show：默认 origin 标为未显式配置（面板显示「默认」）')
  check(!!value && value.sync.data.config && value.sync.data.config.auto_check === true
    && value.sync.data.config.auto_merge === true && value.sync.data.config.source === 'personal',
    'show：自动检查更新与自动合并取自设置文件的 sync 段', JSON.stringify(value && value.sync.data.config))
  check(!!value && value.sync.data.config && value.sync.data.config.check_enabled === false
    && value.sync.data.config.check_minutes === 15 && value.sync.data.config.check_full_access === false,
    'show：提醒检查、间隔与后台检查权限取自设置文件的 sync 段',
    JSON.stringify(value && value.sync.data.config))
  check(!!value && value.settings_sha256 === SETTINGS_SHA, 'show：带出设置指纹（保存时做 CAS）')
  check(!!value && value.targets.ok === true && value.targets.data.remotes.length === 1
    && value.targets.data.remotes[0].host === 'github.com',
    'show：远端清单带名字与 host', JSON.stringify(value && value.targets).slice(0, 200))

  const merged = await host.call('ascend-kb-sync-merge', { sessionId: 's1' })
  const mergedValue = valueOf(merged)
  check(!!mergedValue && mergedValue.ok === true && mergedValue.merged === true
    && mergedValue.merged_rev === '9f8e7d' && mergedValue.previous_rev === '1a2b3c' && mergedValue.behind === 12,
    'merge：成功结果带目标版本、原版本与差数', JSON.stringify(mergedValue))
  const mergeCmd = host.shell.commands.filter(c => /kb_sync\.py --merge/.test(c)).pop() || ''
  check(mergeCmd.indexOf('--force') >= 0, 'merge：手动同步带 --force（失败缓存只挡自动同步）', mergeCmd)

  // 上一次 fetch 失败过：重新打开本页也要带出原因与 git 原始输出（不能只靠点击那一下的 flash）。
  const prevFailedShow = Object.assign({}, showDoc, {
    last_reason: 'network',
    last_error: "fatal: unable to access 'https://github.com/org/repo.git/': Connection refused",
  })
  const prevFailedHost = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(prevFailedShow)) }))
  const prevFailedValue = valueOf(await prevFailedHost.call('ascend-kb-sync-show', { sessionId: 's1' }))
  check(!!prevFailedValue && prevFailedValue.sync.ok === true
    && prevFailedValue.sync.data.last_failure
    && prevFailedValue.sync.data.last_failure.code === 'E_NETWORK',
    'show：上次失败带上原因码', JSON.stringify(prevFailedValue && prevFailedValue.sync.data).slice(0, 240))
  check(!!prevFailedValue && String(prevFailedValue.sync.data.last_error || '').indexOf('Connection refused') >= 0,
    'show：上次失败带上 git 原始输出', JSON.stringify(prevFailedValue && prevFailedValue.sync.data).slice(0, 240))

  // 凭据类失败 + 来源是后台检查：面板把 reason 映射成 E_CREDENTIAL、带出来源，
  // 这样客户端才说得清「后台检查失败」而不是「同步失败」。
  const credentialShow = Object.assign({}, showDoc, {
    last_reason: 'credential',
    last_source: 'check',
    last_error: 'Host key verification failed.',
  })
  const credentialHost = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(credentialShow)) }))
  const credentialValue = valueOf(await credentialHost.call('ascend-kb-sync-show', { sessionId: 's1' }))
  check(!!credentialValue && credentialValue.sync.ok === true
    && credentialValue.sync.data.last_failure
    && credentialValue.sync.data.last_failure.code === 'E_CREDENTIAL',
    'show：credential 原因映射成 E_CREDENTIAL', JSON.stringify(credentialValue && credentialValue.sync.data).slice(0, 260))
  check(!!credentialValue && credentialValue.sync.data.last_source === 'check',
    'show：带出上次尝试的来源（check）', JSON.stringify(credentialValue && credentialValue.sync.data).slice(0, 260))

  const saved = await host.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', branch: 'main', autoCheck: false, autoMerge: true,
    expectSha256: SETTINGS_SHA,
  })
  const savedValue = valueOf(saved)
  check(!!savedValue && savedValue.ok === true && savedValue.config_path === '.local/settings.json',
    'save：返回配置落点', JSON.stringify(savedValue))
  const saveCmd = host.shell.commands.filter(c => /--set-sync/.test(c))[0] || ''
  check(saveCmd.indexOf('--remote origin') >= 0 && saveCmd.indexOf('--branch main') >= 0,
    'save：把远端与分支原样传给脚本', saveCmd)
  check(saveCmd.indexOf('--disable') >= 0 && saveCmd.indexOf('--auto-merge on') >= 0,
    'save：自动检查更新关 → --disable，自动合并开 → --auto-merge on', saveCmd)
  check(saveCmd.indexOf('--check-full-access') < 0,
    'save：没传该开关时不带参数（保留文件现值）', saveCmd)
  const savedLimited = valueOf(await host.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', branch: 'main', autoCheck: true, autoMerge: true,
    checkEnabled: true, checkFullAccess: false, checkMinutes: 30, expectSha256: SETTINGS_SHA,
  }))
  check(!!savedLimited && savedLimited.ok === true && savedLimited.saved
    && savedLimited.saved.check_full_access === false,
    'save：关闭后台检查用完全权限时按 off 传并回带', JSON.stringify(savedLimited))
  const limitedCmds = host.shell.commands.filter(c => /--set-sync/.test(c))
  check(limitedCmds[limitedCmds.length - 1].indexOf('--check-full-access off') >= 0,
    'save：checkFullAccess=false → --check-full-access off',
    limitedCmds[limitedCmds.length - 1])
  check(saveCmd.indexOf('--expect-sha256 ' + SETTINGS_SHA) >= 0, 'save：带上 CAS 指纹', saveCmd)
  // 没传提醒检查参数时按缺省（开 / 30 分钟）写进 argv 与 saved。
  check(!!savedValue && savedValue.saved && savedValue.saved.check_reminders === true
    && savedValue.saved.check_minutes === 30,
    'save：返回 saved 带提醒检查缺省值（开 / 30 分钟）', JSON.stringify(savedValue && savedValue.saved))
  check(saveCmd.indexOf('--check-reminders on') >= 0 && saveCmd.indexOf('--check-minutes 30') >= 0,
    'save：argv 带 --check-reminders on 与 --check-minutes 30', saveCmd)
}

section('[知识库 · host] 保存提醒检查设置')
{
  const host = await bootHost(defaultPlan())
  const out = valueOf(await host.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', branch: 'main', autoCheck: true, autoMerge: true,
    checkEnabled: false, checkMinutes: 15, expectSha256: SETTINGS_SHA,
  }))
  const cmd = host.shell.commands.filter(c => /--set-sync/.test(c)).pop() || ''
  check(!!out && out.ok === true && out.saved && out.saved.check_reminders === false
    && out.saved.check_minutes === 15, 'save：返回 saved 带关闭与 15 分钟', JSON.stringify(out && out.saved))
  check(cmd.indexOf('--check-reminders off') >= 0 && cmd.indexOf('--check-minutes 15') >= 0,
    'save：argv 带 --check-reminders off 与 --check-minutes 15', cmd)

  // 间隔越界夹到 5..720；非整数按 30。
  const lowHost = await bootHost(defaultPlan())
  const low = valueOf(await lowHost.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', checkMinutes: 1,
  }))
  const lowCmd = lowHost.shell.commands.filter(c => /--set-sync/.test(c)).pop() || ''
  check(!!low && low.saved && low.saved.check_minutes === 5 && lowCmd.indexOf('--check-minutes 5') >= 0,
    'save：间隔低于 5 分钟夹到 5', lowCmd)

  const highHost = await bootHost(defaultPlan())
  const high = valueOf(await highHost.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', checkMinutes: 9999,
  }))
  const highCmd = highHost.shell.commands.filter(c => /--set-sync/.test(c)).pop() || ''
  check(!!high && high.saved && high.saved.check_minutes === 720 && highCmd.indexOf('--check-minutes 720') >= 0,
    'save：间隔高于 720 分钟夹到 720', highCmd)

  const badHost = await bootHost(defaultPlan())
  const bad = valueOf(await badHost.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', checkMinutes: 'abc',
  }))
  check(!!bad && bad.saved && bad.saved.check_minutes === 30, 'save：非整数间隔按 30',
    JSON.stringify(bad && bad.saved))
}

section('[知识库 · host] 设归属仓端点')
{
  const host = await bootHost(defaultPlan())
  const out = valueOf(await host.call('ascend-kb-sync-identity', {
    sessionId: 's1', remote: 'gitcode', expectSha256: SETTINGS_SHA,
  }))
  check(!!out && out.ok === true && out.identity && out.identity.remote === 'gitcode'
    && out.identity.resolved === true && out.sha256 === 'c'.repeat(64),
    '设归属仓：返回 identity 与指纹', JSON.stringify(out).slice(0, 240))
  const cmd = host.shell.commands.filter(c => /--set-identity/.test(c))[0] || ''
  check(cmd.indexOf('--remote gitcode') >= 0 && cmd.indexOf('--expect-sha256 ' + SETTINGS_SHA) >= 0,
    '设归属仓：把远端与 CAS 指纹原样传给脚本', cmd)
  check(cmd.indexOf('--json') >= 0, '设归属仓：照样要 JSON 输出', cmd)

  const noRemote = valueOf(await host.call('ascend-kb-sync-identity', { sessionId: 's1' }))
  check(!!noRemote && noRemote.ok === false && noRemote.code === 'E_ARGS',
    '设归属仓：没给远端 → E_ARGS，不起子进程', JSON.stringify(noRemote))
  const unsafe = valueOf(await host.call('ascend-kb-sync-identity', { sessionId: 's1', remote: 'git code' }))
  check(!!unsafe && unsafe.ok === false && unsafe.code === 'E_ARGS',
    '设归属仓：远端名含空白 → E_ARGS', JSON.stringify(unsafe))
  const badSha = valueOf(await host.call('ascend-kb-sync-identity', {
    sessionId: 's1', remote: 'origin', expectSha256: 'not-a-sha',
  }))
  check(!!badSha && badSha.ok === false && badSha.code === 'E_ARGS',
    '设归属仓：指纹不是 64 位十六进制 → E_ARGS', JSON.stringify(badSha))
  check(host.shell.commands.filter(c => /--set-identity/.test(c)).length === 1,
    '参数不合法的三次调用都没有真的起子进程')

  const legacy = await bootHost(defaultPlan({
    'pr_status --set-identity': () => failStdout(2, 'error: unrecognized arguments: --set-identity'),
  }))
  const legacyValue = valueOf(await legacy.call('ascend-kb-sync-identity', { sessionId: 's1', remote: 'origin' }))
  check(!!legacyValue && legacyValue.ok === false && legacyValue.code === 'E_UNSUPPORTED',
    '旧脚本不认 --set-identity：归到 E_UNSUPPORTED', JSON.stringify(legacyValue))

  // 远端不存在：脚本用非 0 退出 + JSON 信封报 E_ARGS（_arg_fail），信封里的码要认。
  const missing = await bootHost(defaultPlan({
    'pr_status --set-identity': () => ({
      exitCode: 2, stderr: { text: '' }, timedOut: false,
      stdout: { text: JSON.stringify({ ok: false, error: { code: 'E_ARGS', message: '远端不存在：team' } }) },
    }),
  }))
  const missingValue = valueOf(await missing.call('ascend-kb-sync-identity', { sessionId: 's1', remote: 'team' }))
  check(!!missingValue && missingValue.ok === false && missingValue.code === 'E_ARGS'
    && String(missingValue.message || '').indexOf('远端不存在') >= 0,
    '设归属仓：远端不存在 → E_ARGS（读脚本的 JSON 信封，不猜成脚本报错）', JSON.stringify(missingValue))
}

section('[知识库 · host] 降级：缺配置 / 缺脚本 / 非 git 检出')
{
  const noConfig = Object.assign({}, showDoc, { config: 'default' })
  const noConfigSettings = Object.assign({}, settingsDoc, {
    settings: Object.assign({}, settingsDoc.settings, { config: 'default', problem: '没有 .local/settings.json' }),
  })
  const host = await bootHost(defaultPlan({
    'kb_sync --show': () => okStdout(JSON.stringify(noConfig)),
    'pr_status --json': () => okStdout(JSON.stringify(noConfigSettings)),
  }))
  const shown = await host.call('ascend-kb-sync-show', {})
  const value = valueOf(shown)
  check(!!value && value.ok === true && value.sync.ok === true && value.sync.data.config
    && value.sync.data.config.source === 'default',
    '缺配置：同步段仍读得到，开关来源标 default', JSON.stringify(value && value.sync).slice(0, 240))

  const missing = await bootHost(defaultPlan({
    'kb_sync --show': () => failStdout(2, "python3: can't open file '/repo/scripts/kb_sync.py': [Errno 2] No such file or directory"),
  }))
  const missingValue = valueOf(await missing.call('ascend-kb-sync-show', {}))
  check(!!missingValue && missingValue.sync.ok === false && missingValue.sync.code === 'E_NO_SCRIPT',
    '缺脚本：同步段给 E_NO_SCRIPT（不是整页失败）', JSON.stringify(missingValue && missingValue.sync))
  check(!!missingValue && missingValue.targets.ok === true, '缺脚本：远端清单仍然读得到')
  check(!!missingValue && missingValue.sync.data === undefined, '缺脚本：不编造读数')
  check(!!missingValue && String(missingValue.sync.message || '').indexOf('不存在') >= 0,
    '缺脚本：说明是脚本不存在', JSON.stringify(missingValue && missingValue.sync))

  const notGit = Object.assign({}, showDoc, {
    ok: false, reason: 'not-a-repo', local_rev: 'unknown', remote_rev: null, behind: 'unknown',
  })
  const notGitHost = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(notGit)) }))
  const gitValue = valueOf(await notGitHost.call('ascend-kb-sync-show', {}))
  check(!!gitValue && gitValue.sync.ok === false && gitValue.sync.code === 'E_NOT_GIT',
    '非检出：归到 E_NOT_GIT', JSON.stringify(gitValue && gitValue.sync))
}

section('[知识库 · host] 状态与失败分类')
{
  // `--show` 在关闭 / 离线 / 未拉取 / 没有配置远端时回 ok=false，但本机读数仍在。
  // 关闭与离线读 enabled / offline 两个真实字段，不靠 reason 猜。
  const disabled = Object.assign({}, showDoc, { ok: false, enabled: false, reason: 'disabled' })
  {
    const host = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(disabled)) }))
    const value = valueOf(await host.call('ascend-kb-sync-show', {}))
    check(!!value && value.sync.ok === true && value.sync.state === 'disabled'
      && value.sync.data.enabled === false && value.sync.data.local_rev === '1a2b3c',
      '关闭：enabled=false → state=disabled 且保留本机读数', JSON.stringify(value && value.sync).slice(0, 200))
  }
  const offline = Object.assign({}, showDoc, { ok: false, enabled: true, offline: true, reason: 'offline' })
  {
    const host = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(offline)) }))
    const value = valueOf(await host.call('ascend-kb-sync-show', {}))
    check(!!value && value.sync.ok === true && value.sync.state === 'offline'
      && value.sync.data.offline === true && value.sync.data.enabled === true,
      '离线：offline=true → state=offline 且保留本机读数', JSON.stringify(value && value.sync).slice(0, 200))
  }
  const unfetched = Object.assign({}, showDoc, {
    ok: false, reason: '', remote_rev: null, behind: 'unknown',
  })
  {
    const host = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(unfetched)) }))
    const value = valueOf(await host.call('ascend-kb-sync-show', {}))
    check(!!value && value.sync.ok === true && value.sync.state === 'unfetched',
      '未拉取：state=unfetched（不是失败）', JSON.stringify(value && value.sync).slice(0, 200))
  }
  const noRemote = Object.assign({}, showDoc, { ok: false, enabled: true, reason: '', remote: '', remote_rev: null })
  {
    const host = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(noRemote)) }))
    const value = valueOf(await host.call('ascend-kb-sync-show', {}))
    check(!!value && value.sync.ok === true && value.sync.state === 'no-remote',
      '没有配置远端：state=no-remote', JSON.stringify(value && value.sync).slice(0, 200))
  }
  const otherRepo = Object.assign({}, showDoc, { same_repo: false })
  {
    const host = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout(JSON.stringify(otherRepo)) }))
    const value = valueOf(await host.call('ascend-kb-sync-show', {}))
    check(!!value && value.sync.ok === true && value.sync.data.same_repo === false,
      '同源校验不一致：same_repo=false 原样带出', JSON.stringify(value && value.sync).slice(0, 200))
  }

  const dirtyMerge = Object.assign({}, showDoc, { ok: false, reason: 'dirty' })
  const host = await bootHost(defaultPlan({
    'kb_sync --merge': () => okStdout(JSON.stringify(dirtyMerge)),
  }))
  const dirtyValue = valueOf(await host.call('ascend-kb-sync-merge', {}))
  check(!!dirtyValue && dirtyValue.ok === false && dirtyValue.code === 'E_DIRTY',
    '工作区不干净：归到 E_DIRTY', JSON.stringify(dirtyValue))

  const sameRepoMerge = Object.assign({}, showDoc, { ok: true, merge: 'none', reason: 'same-repo' })
  {
    const host = await bootHost(defaultPlan({
      'kb_sync --merge': () => okStdout(JSON.stringify(sameRepoMerge)),
    }))
    const value = valueOf(await host.call('ascend-kb-sync-merge', {}))
    check(!!value && value.ok === true && value.merged === false && value.reason_code === 'E_SAME_REPO',
      '同源校验不一致：合并被拦下，归到 E_SAME_REPO', JSON.stringify(value))
  }

  const identityMerge = Object.assign({}, showDoc, { ok: false, reason: 'identity-unresolved' })
  {
    const host = await bootHost(defaultPlan({
      'kb_sync --merge': () => okStdout(JSON.stringify(identityMerge)),
    }))
    const value = valueOf(await host.call('ascend-kb-sync-merge', {}))
    check(!!value && value.ok === false && value.code === 'E_IDENTITY',
      '归属仓解析不到：归到 E_IDENTITY', JSON.stringify(value))
  }

  const unsupported = await bootHost(defaultPlan({
    'pr_status --set-sync': () => failStdout(2, 'error: unrecognized arguments: --set-sync'),
  }))
  const unsupportedValue = valueOf(await unsupported.call('ascend-kb-sync-save', {
    sessionId: 's1', remote: 'origin', branch: 'main', autoCheck: true, autoMerge: true,
  }))
  check(!!unsupportedValue && unsupportedValue.ok === false && unsupportedValue.code === 'E_UNSUPPORTED',
    '脚本没有 --set-sync：归到 E_UNSUPPORTED', JSON.stringify(unsupportedValue))

  const badOutput = await bootHost(defaultPlan({ 'kb_sync --show': () => okStdout('this is not json') }))
  const badValue = valueOf(await badOutput.call('ascend-kb-sync-show', {}))
  check(!!badValue && badValue.sync.ok === false && badValue.sync.code === 'E_BAD_OUTPUT',
    '输出非 JSON：归到 E_BAD_OUTPUT', JSON.stringify(badValue && badValue.sync))

  // 所有失败分支的文案里都不允许出现「未知错误」。
  const messages = [dirtyValue, unsupportedValue, badValue && badValue.sync]
    .map(v => String((v && (v.message || v.code)) || ''))
  check(messages.every(m => m.indexOf('未知错误') < 0), '失败文案里没有「未知错误」', JSON.stringify(messages))
}

section('[知识库 · host] 合并失败：网络原因 / 缓存跳过 / 旧脚本兼容')
{
  const netFail = {
    ok: false, reason: 'network', skipped: false,
    fetch_error: "fatal: unable to access 'https://github.com/org/repo.git/': "
      + 'Failed to connect to 127.0.0.1 port 7897: Connection refused',
  }
  const failedHost = await bootHost(defaultPlan({ 'kb_sync --merge': () => okStdout(JSON.stringify(netFail)) }))
  const failedValue = valueOf(await failedHost.call('ascend-kb-sync-merge', { sessionId: 's1' }))
  check(!!failedValue && failedValue.ok === false && failedValue.code === 'E_NETWORK',
    '网络失败归到 E_NETWORK', JSON.stringify(failedValue))
  check(!!failedValue && String(failedValue.detail || '').indexOf('Failed to connect') >= 0,
    '网络失败把 git 原始输出带到面板', JSON.stringify(failedValue))

  const cached = { ok: false, skipped: true, reason: 'network', fetch_error: 'fatal: 旧失败' }
  const cachedHost = await bootHost(defaultPlan({ 'kb_sync --merge': () => okStdout(JSON.stringify(cached)) }))
  const cachedValue = valueOf(await cachedHost.call('ascend-kb-sync-merge', { sessionId: 's1' }))
  check(!!cachedValue && cachedValue.ok === false && cachedValue.code === 'E_SKIPPED',
    '被缓存挡下时说「本次没有重试」，不报同步失败', JSON.stringify(cachedValue))

  // 旧检出的脚本不认 --force：退回不带它再跑一次，不把版本错位当同步失败。
  let mergeCalls = 0
  const legacyPlan = defaultPlan()
  const legacyHost = await bootHost((command) => {
    if (/kb_sync\.py --merge/.test(command)) {
      mergeCalls += 1
      if (mergeCalls === 1) return failStdout(2, 'error: unrecognized arguments: --force')
      return okStdout(JSON.stringify({
        ok: true, merge: 'ff-only', local_rev: '9f8e7d', local_rev_before: '1a2b3c',
        behind_before: 12, behind: 0, reason: '',
      }))
    }
    return legacyPlan(command)
  })
  const legacyValue = valueOf(await legacyHost.call('ascend-kb-sync-merge', { sessionId: 's1' }))
  check(!!legacyValue && legacyValue.ok === true && legacyValue.merged === true,
    '旧脚本不认 --force：退回不带它再跑，结果仍算成功', JSON.stringify(legacyValue))
  const legacyCmds = legacyHost.shell.commands.filter(c => /kb_sync\.py --merge/.test(c))
  check(legacyCmds.length === 2 && legacyCmds[1].indexOf('--force') < 0,
    '兼容退回只补一次不带 --force 的重试', JSON.stringify(legacyCmds))

  // 退回后仍然失败 / 仍被缓存挡下：结局照样要正确，不当成功。
  // 旧脚本（b92b199）失败时只有 reason `exit-<n>`、没有 fetch_error，这里照它的真实形状构造。
  const legacyFailHost = await bootHost((command) => {
    if (/kb_sync\.py --merge/.test(command)) {
      if (command.indexOf('--force') >= 0) return failStdout(2, 'error: unrecognized arguments: --force')
      return okStdout(JSON.stringify({ ok: false, reason: 'exit-128', skipped: false }))
    }
    return defaultPlan()(command)
  })
  const legacyFailValue = valueOf(await legacyFailHost.call('ascend-kb-sync-merge', { sessionId: 's1' }))
  check(!!legacyFailValue && legacyFailValue.ok === false && legacyFailValue.code === 'E_FETCH'
    && !legacyFailValue.detail,
    '旧脚本退回后仍失败：按 E_FETCH 报，不编造原文', JSON.stringify(legacyFailValue))

  const legacySkipHost = await bootHost((command) => {
    if (/kb_sync\.py --merge/.test(command)) {
      if (command.indexOf('--force') >= 0) return failStdout(2, 'error: unrecognized arguments: --force')
      return okStdout(JSON.stringify({ ok: false, skipped: true, reason: 'exit-128' }))
    }
    return defaultPlan()(command)
  })
  const legacySkipValue = valueOf(await legacySkipHost.call('ascend-kb-sync-merge', { sessionId: 's1' }))
  check(!!legacySkipValue && legacySkipValue.ok === false && legacySkipValue.code === 'E_SKIPPED'
    && !legacySkipValue.detail,
    '旧脚本退回后仍被缓存挡下：归到 E_SKIPPED，但不编造原文', JSON.stringify(legacySkipValue))
}

// ── 收尾 ────────────────────────────────────────────────────────────────────
// 断言里用到的产物必须真的存在（防止只测了源码、没测装进 profile 的那份）。
readFileSync(join(ROOT, 'lib', 'index.js'), 'utf8')
readFileSync(join(ROOT, 'lib', 'client.js'), 'utf8')

process.stdout.write('\n通过 ' + passed + ' 条，失败 ' + failures.length + ' 条\n')
if (failures.length) {
  for (const f of failures) process.stderr.write('FAIL ' + f + '\n')
  process.exit(1)
}
process.stdout.write('知识库 tab 冒烟通过\n')
