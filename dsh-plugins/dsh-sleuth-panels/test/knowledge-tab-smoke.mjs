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
function optionsOf(tree) {
  const out = []
  walk(tree, el => { if (el.type === 'option') out.push(textOf(el)) })
  return out
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
      sync: { remote: 'origin', branch: 'main', enabled: true, auto_merge: true },
      target: { remote: 'origin', base: 'main' },
    } },
    sync: { ok: true, state: 'ok', error: null, data: {
      remote: 'origin', branch: 'main',
      local_rev: '1a2b3c', remote_rev: '9f8e7d',
      behind: 12, ahead: 0, skipped: false,
      last_checked: minutesAgo(3), last_reason: '',
      enabled: true, offline: false, offline_source: '', reason: '',
      same_repo: true,
      config: { auto_check: true, auto_merge: true, source: 'personal', path: '.local/settings.json' },
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
    '三个 tab 的入口都在（指标 / 自演进 / 知识库）', text.slice(0, 120))
  check(text.indexOf('本机版本') >= 0 && text.indexOf('v1a2b3c') >= 0, '本机版本读数', text.slice(0, 200))
  check(text.indexOf('远端版本') >= 0 && text.indexOf('v9f8e7d') >= 0, '远端版本读数')
  check(text.indexOf('落后') >= 0 && text.indexOf('12') >= 0 && text.indexOf('个提交') >= 0, '落后提交数与单位')
  check(text.indexOf('上次核对') >= 0 && /3 分钟前/.test(text), '上次核对按相对时间给', text.slice(0, 240))
  check(text.indexOf('本次合并会把') >= 0 && text.indexOf('knowledge/') >= 0 && text.indexOf('skills/') >= 0,
    '落后时提示合并范围与生效时点')
  check(text.indexOf('同步源') >= 0, '同步源卡片在')
  const opts = optionsOf(tree)
  check(opts.some(t => t.indexOf('origin · github.com') >= 0), '远端下拉列出名字与 host', JSON.stringify(opts).slice(0, 200))
  check(text.indexOf('上次使用：') >= 0, '同步源给「上次使用」')
  check(text.indexOf('自动检查更新') >= 0 && text.indexOf('自动合并') >= 0, '两个开关都在')
  check(text.indexOf('来源：个人设置') >= 0, '开关来源标「个人设置」')
  check(switchByLabel(tree, '自动检查更新') && switchByLabel(tree, '自动检查更新').props['aria-checked'] === 'true',
    '自动检查更新默认开（aria-checked=true）')
  check(text.indexOf('.local/settings.json') >= 0 && text.indexOf('修改下次开单生效') >= 0, '页脚给配置路径与生效时点')
  check(text.indexOf('打开本页不联网') >= 0, '页脚说明打开本页不联网')

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
    '保存带上两个开关的当前值', JSON.stringify(saveCall && saveCall.payload))
  check(!!saveCall && saveCall.payload.expectSha256 === SETTINGS_SHA,
    '保存带上设置指纹（CAS）', JSON.stringify(saveCall && saveCall.payload))
  check(textOf(saved).indexOf('.local/settings.json') >= 0, '保存后仍显示配置落点')

  clickButton(saved, '立即同步')
  await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  check(calls.some(c => c.endpoint === 'ascend-kb-sync-merge'), '点「立即同步」发 ascend-kb-sync-merge',
    JSON.stringify(calls.map(c => c.endpoint)))
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
  const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => payload })
  const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('这个远端不是同一个仓，未自动合并') >= 0,
    '同源校验不一致时给一行说明', text.slice(0, 240))
  check(text.indexOf('未知错误') < 0, '同源校验不一致不写「未知错误」')
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
    check(switchesOf(tree).every(el => el.props.disabled === true), '离线时两个开关都禁用')
  }
  const disabled = showPayload()
  disabled.sync.state = 'disabled'
  disabled.sync.error = { code: 'E_DISABLED', message: '同步已关闭（个人设置）' }
  disabled.sync.data.enabled = false
  disabled.sync.data.reason = 'disabled'
  disabled.sync.data.config = { auto_check: false, auto_merge: true, source: 'personal' }
  {
    const { runtime, main } = await bootClient({ 'ascend-kb-sync-show': () => disabled })
    const tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
    const text = textOf(tree)
    check(text.indexOf('已关闭（个人设置）') >= 0, '个人设置关闭时给「已关闭」状态', text.slice(0, 200))
    check(switchByLabel(tree, '自动检查更新').props['aria-checked'] === 'false', '关闭时开关显示关闭')
    check(!findButton(tree, '立即同步'), '已关闭时不给「立即同步」（脚本会拒绝手动同步）')
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
    'ascend-kb-sync-merge': () => ({ ok: true, merged: true, merged_rev: '9f8e7d', previous_rev: '1a2b3c', behind: 12 }),
  })
  let tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  clickButton(tree, '立即同步')
  tree = await runtime.render(main.component, { view: 'knowledge', sessionId: 's1' })
  const text = textOf(tree)
  check(text.indexOf('已同步到 v9f8e7d') >= 0, '成功提示给到目标版本', text.slice(0, 240))
  check(text.indexOf('原 v1a2b3c') >= 0 && text.indexOf('落后 12 个提交') >= 0, '成功提示给到原版本与差数')
  check(text.indexOf('git reset --hard ORIG_HEAD') >= 0, '成功提示给回滚命令')

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
  check(textOf(t5).indexOf('没有自动合并：配置远端与 origin 不同源') >= 0,
    '同源校验不一致时不给合并，并写清原因', textOf(t5).slice(0, 240))

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
  surface: { knowledge: 3, references: 1 },
  merge: 'none', skipped: false, config: 'file',
  same_repo: true,
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
    sync: { remote: 'origin', branch: 'main', enabled: true, auto_merge: true },
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
  }, overrides || {})
  return (command) => {
    // `pr_status --list-targets` 也带 --json，先判更长的那个。
    if (/pr_status\.py --list-targets/.test(command)) return map['pr_status --list-targets'](command)
    if (/pr_status\.py --set-sync/.test(command)) return map['pr_status --set-sync'](command)
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
  check(!!value && value.sync.data.enabled === true && value.sync.data.offline === false
    && value.sync.data.reason === '' && value.sync.data.same_repo === true,
    'show：enabled / offline / reason / same_repo 按脚本字段带出',
    JSON.stringify(value && value.sync.data).slice(0, 260))
  check(!!value && value.sync.data.config && value.sync.data.config.auto_check === true
    && value.sync.data.config.auto_merge === true && value.sync.data.config.source === 'personal',
    'show：两个开关取自设置文件的 sync 段', JSON.stringify(value && value.sync.data.config))
  check(!!value && value.settings_sha256 === SETTINGS_SHA, 'show：带出设置指纹（保存时做 CAS）')
  check(!!value && value.targets.ok === true && value.targets.data.remotes.length === 1
    && value.targets.data.remotes[0].host === 'github.com',
    'show：远端清单带名字与 host', JSON.stringify(value && value.targets).slice(0, 200))

  const merged = await host.call('ascend-kb-sync-merge', { sessionId: 's1' })
  const mergedValue = valueOf(merged)
  check(!!mergedValue && mergedValue.ok === true && mergedValue.merged === true
    && mergedValue.merged_rev === '9f8e7d' && mergedValue.previous_rev === '1a2b3c' && mergedValue.behind === 12,
    'merge：成功结果带目标版本、原版本与差数', JSON.stringify(mergedValue))

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
  check(saveCmd.indexOf('--expect-sha256 ' + SETTINGS_SHA) >= 0, 'save：带上 CAS 指纹', saveCmd)
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
