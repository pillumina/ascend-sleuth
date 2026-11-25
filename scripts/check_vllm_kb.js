#!/usr/bin/env node
// vllm-kb 接入插件的离线自测：打桩，不需要 DSH，也不需要内网实例。
//
// 覆盖：插件入口接线（index.js 可加载、无 @deepseek-ai/dsh-tools 时回退 defineTool 能注册工具）、
// 配置归一化与读写、repo#编号 → source_id、四个能力的请求形状（打一台进程内假服务）、
// 输出截断、错误映射（HTTP 4xx/5xx）、可用性三态与缓存、无端点时的降级、
// 探测路由用请求带来的地址（页面改了还没保存也能测）、兜底命令行入口能跑。
//
// 跑法：node scripts/check_vllm_kb.js（CI 的 panel-checks 里跑这一条）

import { execFileSync } from 'node:child_process'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const core = await import(new URL('../dsh-plugins/dsh-sleuth-vllm-kb/lib/core.js', import.meta.url).href)

let failures = 0
const queue = []
function check(name, fn) {
  queue.push([name, fn])
}
async function runChecks() {
  for (const [name, fn] of queue) {
    try {
      const result = await fn()
      if (result === false) throw new Error('返回 false')
      console.log(`  ✓ ${name}`)
    } catch (error) {
      failures += 1
      console.log(`  ✗ ${name}\n      ${String((error && error.message) || error)}`)
    }
  }
}
function eq(actual, expected, label) {
  const a = JSON.stringify(actual)
  const b = JSON.stringify(expected)
  if (a !== b) throw new Error(`${label || '不相等'}：期望 ${b}，实际 ${a}`)
}
function ok(value, label) {
  if (!value) throw new Error(label || '断言失败')
}

// 只钉这次修的那一类：必填标记必须以字段名数组出现在 object 上，不能留在字段自己的节点里。
// ctx.tools.register 收的完整子集比这条检查宽，也比它严（这条检查不复制那份判据——复制一份会
// 在安装版改规则时静默漂移，真出子集问题仍由注册时报错暴露）。
function assertRequiredOnlyOnObjects(schema, path) {
  ok(schema !== null && typeof schema === 'object' && !Array.isArray(schema), `${path} 应是 schema 对象`)
  if (Object.hasOwn(schema, 'required')) {
    ok(schema.type === 'object', `${path}.required 只能出现在 object 上（这里 type 是 ${String(schema.type)}）`)
    ok(Array.isArray(schema.required) && schema.required.every((key) => typeof key === 'string'), `${path}.required 应是字段名数组`)
  }
  for (const [key, child] of Object.entries(schema.properties || {})) assertRequiredOnlyOnObjects(child, `${path}.properties.${key}`)
  if (schema.items !== undefined) assertRequiredOnlyOnObjects(schema.items, `${path}.items`)
  for (const [index, branch] of (schema.oneOf || []).entries()) assertRequiredOnlyOnObjects(branch, `${path}.oneOf[${index}]`)
}

console.log('[0] 插件入口接线（index.js：顶层动态 import + dsh-tools 回退）')
// index.js 曾静态 import '@deepseek-ai/dsh-tools'：包被 link 装进 profile 时从仓库真实路径解析，
// 到不了 DSH 安装处的 node_modules，整个插件树加载失败（实测报错 Cannot find package）。
// 下面两条钉住接线：① 模块能加载；② 无 dsh-tools 可解析时（CI 检出即此形态）回退实现
// 能注册出可用的工具对象。回归成静态 import，本段直接红。
check('index.js 可加载，注册元齐全', async () => {
  const entry = await import(new URL('../dsh-plugins/dsh-sleuth-vllm-kb/index.js', import.meta.url).href)
  eq(entry.name, 'kb-evidence')
  ok(Array.isArray(entry.inject) && entry.inject.includes('tools'), 'inject 应含 tools')
  ok(typeof entry.apply === 'function', 'apply 应是函数')
  return true
})
check('无 dsh-tools 可解析时回退 defineTool 注册三个工具（tools 模式）', async () => {
  const entry = await import(new URL('../dsh-plugins/dsh-sleuth-vllm-kb/index.js', import.meta.url).href)
  const tools = []
  await entry.apply({ tools: { register: (tool) => tools.push(tool) } }, { mode: 'tools' })
  eq(tools.map((tool) => tool.name).join(','), 'vllm_kb_code,vllm_kb_fix,vllm_kb_doc')
  ok(tools.every((tool) => typeof tool.execute === 'function' && tool.output && tool.output.schema), '每个工具都应带 execute 与 output.schema')
  return true
})
// 回退实现曾把 DSL（`ok: { type: 'boolean', required: true }`）原样当 JSON Schema 交给注册：
// 必填标记留在 boolean 字段上，注册时报 unsupported JSON schema: schema.properties.ok.required
// is not supported on type "boolean"，vllm-kb-tools 条目不激活。参数根当时也没有 type: 'object'。
check('回退路径交出的参数与输出把 required 放在 object 上（tools 与 ocr 两种模式）', async () => {
  const entry = await import(new URL('../dsh-plugins/dsh-sleuth-vllm-kb/index.js', import.meta.url).href)
  const expected = {
    tools: { vllm_kb_code: ['query'], vllm_kb_fix: ['target'], vllm_kb_doc: [] },
    ocr: { vllm_kb_ocr: ['path'] },
  }
  for (const mode of Object.keys(expected)) {
    const tools = []
    await entry.apply({ tools: { register: (tool) => tools.push(tool) } }, { mode })
    eq(tools.map((tool) => tool.name).join(','), Object.keys(expected[mode]).join(','), `${mode} 模式注册的工具`)
    for (const tool of tools) {
      assertRequiredOnlyOnObjects(tool.output.schema, `${tool.name}.output.schema`)
      eq(tool.output.schema.required, ['ok'], `${tool.name}.output.schema.required`)
      eq(tool.parameters.type, 'object', `${tool.name}.parameters.type`)
      eq(tool.parameters.required || [], expected[mode][tool.name], `${tool.name}.parameters.required`)
      assertRequiredOnlyOnObjects(tool.parameters, `${tool.name}.parameters`)
    }
  }
  return true
})

console.log('[1] 配置归一化')
check('缺字段走默认值', () => {
  const config = core.normalizeConfig(null)
  eq(config.endpoints, [])
  eq(config.active, '')
  eq(config.probe_timeout_ms, 1000)
  eq(config.probe_ttl_ms, 30000)
  eq(config.request_timeout_ms, 15000)
})
check('丢掉没有地址的端点，label 回落为地址，地址去尾斜杠', () => {
  const config = core.normalizeConfig({
    endpoints: [
      { id: 'a', label: '内网', base_url: 'http://h:8000/' },
      { id: 'b', base_url: '   ' },
      { base_url: 'http://x:1' },
    ],
    active: 'b',
  })
  eq(config.endpoints.length, 2)
  eq(config.endpoints[0].base_url, 'http://h:8000')
  eq(config.endpoints[1].label, 'http://x:1')
  eq(config.active, config.endpoints[0].id)
})
check('非法超时走默认', () => {
  const config = core.normalizeConfig({ probe_timeout_ms: -1, request_timeout_ms: 'x' })
  eq(config.probe_timeout_ms, 1000)
  eq(config.request_timeout_ms, 15000)
})

console.log('[2] repo#编号 → source_id')
check('vllm-ascend 走官方仓名', () => eq(core.resolveSourceId('vllm-ascend#8938'), 'github:vllm-project-vllm-ascend:issue:8938'))
check('vllm 走官方仓名', () => eq(core.resolveSourceId('vllm#50241'), 'github:vllm-project-vllm:issue:50241'))
check('完整 source_id 原样透传', () => eq(core.resolveSourceId('github:a-b:issue:1'), 'github:a-b:issue:1'))
check('没有 # 时原样返回', () => eq(core.resolveSourceId('pdf:manual'), 'pdf:manual'))

const workdir = await mkdtemp(join(tmpdir(), 'vllm-kb-'))
process.env.KB_EVIDENCE_CONFIG = join(workdir, 'vllm-kb.json')

console.log('[3] 配置读写')
check('文件不存在时给默认值且不报错', async () => {
  const saved = process.env.KB_EVIDENCE_CONFIG
  process.env.KB_EVIDENCE_CONFIG = join(workdir, 'fresh', 'vllm-kb.json')
  try {
    const { config, error } = await core.readConfig()
    ok(error === null, `不该有错误：${error}`)
    eq(config.endpoints, [])
  } finally {
    process.env.KB_EVIDENCE_CONFIG = saved
  }
  return true
})
await core.writeConfig(core.normalizeConfig({
  endpoints: [{ id: 'ep-1', label: '假服务', base_url: 'http://127.0.0.1:1' }],
}))
check('写回后读到的就是写下的', async () => {
  const { config } = await core.readConfig()
  eq(config.endpoints.length, 1)
  eq(config.active, 'ep-1')
  return true
})

// ---- 进程内假服务：按 vllm-kb 的只读接口回放 ---------------------------
const seen = []
const server = createServer((req, res) => {
  let body = ''
  req.on('data', (chunk) => { body += chunk })
  req.on('end', () => {
    const url = new URL(req.url, 'http://localhost')
    seen.push({ method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), body: body ? JSON.parse(body) : null })
    const json = (status, payload) => {
      res.writeHead(status, { 'content-type': 'application/json' })
      res.end(JSON.stringify(payload))
    }
    if (url.pathname === '/health') return json(200, { status: 'ok', embedding: 'ok', ocr: { status: 'configured' } })
    if (url.pathname === '/code/search') {
      if (JSON.parse(body || '{}').keyword === 'boom') return json(503, { error: 'down' })
      return json(200, { hits: [{ version: '0.23.0', path: 'vllm_ascend/x.py', line: 12 }] })
    }
    if (url.pathname === '/graph/chain') return json(200, { found: true, issue_id: url.searchParams.get('doc') })
    if (url.pathname.startsWith('/doc/')) return json(200, { title: 'HCCL 命令参考', content: 'x'.repeat(9000) })
    if (url.pathname === '/tags/match') return json(200, { docs: [{ id: 'D-1', title: '超时排查' }] })
    if (url.pathname === '/ocr') return json(200, { text: 'error: timeout', signatures: ['timeout'] })
    return json(404, { error: 'not found' })
  })
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`

async function withConfig(extra = {}) {
  await core.writeConfig(core.normalizeConfig(Object.assign({
    endpoints: [{ id: 'ep-1', label: '假服务', base_url: base }],
    active: 'ep-1',
    probe_timeout_ms: 500,
    request_timeout_ms: 3000,
  }, extra)))
}

console.log('[4] 可用性')
check('没有端点 → not-configured', async () => {
  await core.writeConfig(core.normalizeConfig({}))
  const result = await core.availability(core.normalizeConfig({}), core.createProbeCache())
  eq(result.reason, 'not-configured')
  return true
})
check('探不通 → unreachable', async () => {
  const config = core.normalizeConfig({ endpoints: [{ id: 'e', base_url: 'http://127.0.0.1:1' }], probe_timeout_ms: 100 })
  const result = await core.availability(config, core.createProbeCache())
  eq(result.reason, 'unreachable')
  return true
})
check('探得通 → ok，且 TTL 内不再探第二次', async () => {
  const config = core.normalizeConfig({
    endpoints: [{ id: 'e', label: 'L', base_url: base }],
    probe_timeout_ms: 500,
    probe_ttl_ms: 5000,
  })
  let calls = 0
  const probeImpl = async (url, timeout) => { calls += 1; return core.probe(url, timeout) }
  const cache = core.createProbeCache()
  eq((await core.availability(config, cache, probeImpl)).ok, true)
  eq((await core.availability(config, cache, probeImpl)).ok, true)
  eq(calls, 1, '第二次应命中缓存')
  return true
})

console.log('[5] 四个能力的请求形状')
check('code：参数映射到 /code/search 的 body', async () => {
  await withConfig()
  seen.length = 0
  const result = await core.lookup('code', { query: 'fill_(-1)', version: '0.23.0', in_file: 'x.py', per_version: true, repo: 'img:glm5.2', kind: 'msg' }, { cache: core.createProbeCache() })
  eq(result.ok, true)
  const hit = seen.find((one) => one.path === '/code/search')
  eq(hit.method, 'POST')
  eq(hit.body.keyword, 'fill_(-1)')
  eq(hit.body.limit, 10)
  eq(hit.body.version, '0.23.0')
  eq(hit.body.path, 'x.py')
  eq(hit.body.per_version, true)
  eq(hit.body.repo, 'img:glm5.2')
  eq(hit.body.kind, 'msg')
  return true
})
check('fix：repo#编号 变成 source_id 并进 query', async () => {
  await withConfig()
  const result = await core.lookup('fix', { target: 'vllm-ascend#8938' }, { cache: core.createProbeCache() })
  eq(result.ok, true)
  const hit = seen.filter((one) => one.path === '/graph/chain').pop()
  eq(hit.query.doc, 'github:vllm-project-vllm-ascend:issue:8938')
  return true
})
check('doc：query 走 /tags/match，doc_id 走 /doc/{id}', async () => {
  await withConfig()
  await core.lookup('doc', { query: 'HCCL 超时' }, { cache: core.createProbeCache() })
  eq(seen.filter((one) => one.path === '/tags/match').pop().body, { text: 'HCCL 超时' })
  const long = await core.lookup('doc', { doc_id: 'D-1' }, { cache: core.createProbeCache() })
  eq(long.truncated, true, '整篇应被截断')
  ok(long.content.length >= core.CONTENT_LIMIT, '截断后仍应有正文')
  // 截断之后允许再加一句判读备注（body 为空时补的那句），所以上限放宽一点
  ok(long.content.length <= core.CONTENT_LIMIT + 300, `截断后不该超太多：${long.content.length}`)
  return true
})
check('doc：两个参数都没给 → bad-argument，不发请求', async () => {
  await withConfig()
  const business = () => seen.filter((one) => one.path !== '/health').length
  const before = business()
  const result = await core.lookup('doc', {}, { cache: core.createProbeCache() })
  eq(result.reason, 'bad-argument')
  eq(business(), before, '不该发业务请求')
  return true
})
check('ocr：本地图片 base64 进 body', async () => {
  await withConfig()
  const image = join(workdir, 'shot.png')
  await writeFile(image, Buffer.from('fake-image-bytes'))
  const result = await core.lookup('ocr', { path: image }, { cache: core.createProbeCache() })
  eq(result.ok, true)
  const hit = seen.filter((one) => one.path === '/ocr').pop()
  eq(hit.body.image, Buffer.from('fake-image-bytes').toString('base64'))
  return true
})
check('ocr：读不到图片 → file-missing，不发业务请求', async () => {
  await withConfig()
  const business = () => seen.filter((one) => one.path !== '/health').length
  const before = business()
  const result = await core.lookup('ocr', { path: join(workdir, 'absent.png') }, { cache: core.createProbeCache() })
  eq(result.reason, 'file-missing')
  eq(business(), before)
  return true
})

console.log('[6] 错误与降级')
check('HTTP 5xx 映射成 http-503（不抛异常）', async () => {
  await withConfig()
  const result = await core.lookup('code', { query: 'boom' }, { cache: core.createProbeCache() })
  eq(result.ok, false)
  eq(result.reason, 'http-503')
  return true
})
check('端点不可达时 lookup 直接给 unreachable，不进业务请求', async () => {
  await withConfig({ endpoints: [{ id: 'e', label: '不可达', base_url: 'http://127.0.0.1:1' }], probe_timeout_ms: 100 })
  const before = seen.length
  const result = await core.lookup('code', { query: 'x' }, { cache: core.createProbeCache() })
  eq(result.reason, 'unreachable')
  eq(seen.length, before, '不该发出业务请求')
  return true
})

console.log('[7] 配置路由（鉴权 / 解析 / 探测 / 404）')
check('没有自定义头 → 403（GET 与 POST 都拒）', async () => {
  const get = await core.handleApiRequest({ method: 'GET', pathname: '/config', headers: {} })
  eq(get.status, 403)
  const post = await core.handleApiRequest({ method: 'POST', pathname: '/config', headers: {}, body: '{}' })
  eq(post.status, 403)
  return true
})
check('带头 GET /config → 200 且返回当前配置', async () => {
  const out = await core.handleApiRequest({ method: 'GET', pathname: '/config', headers: { 'x-vllm-kb': '1' } })
  eq(out.status, 200)
  ok(out.payload.config && Array.isArray(out.payload.config.endpoints), '应返回 config')
  return true
})
check('带头 POST /config → 写回并清缓存', async () => {
  let saved = null
  let cleared = false
  const out = await core.handleApiRequest(
    { method: 'POST', pathname: '/config', headers: { 'x-vllm-kb': '1' }, body: JSON.stringify({ endpoints: [{ label: 'A', base_url: 'http://a:1' }] }) },
    { writeConfig: async (next) => { saved = next }, readConfig: async () => ({ config: core.normalizeConfig(null), error: null }), cache: { clear: () => { cleared = true } } },
  )
  eq(out.status, 200)
  eq(saved.endpoints.length, 1)
  eq(cleared, true, '写配置应清探测缓存')
  return true
})
check('非法 JSON → 400，不是 500', async () => {
  const out = await core.handleApiRequest({ method: 'POST', pathname: '/config', headers: { 'x-vllm-kb': '1' }, body: '{bad' })
  eq(out.status, 400)
  return true
})
check('没有端点时 POST /probe → 200 且 ok:false', async () => {
  const out = await core.handleApiRequest(
    { method: 'POST', pathname: '/probe', headers: { 'x-vllm-kb': '1' }, body: '{}' },
    { readConfig: async () => ({ config: core.normalizeConfig(null), error: null }) },
  )
  eq(out.status, 200)
  eq(out.payload.ok, false)
  return true
})
check('页面上的地址没保存也能探：用请求里的 base_url 与超时', async () => {
  const sent = []
  const config = core.normalizeConfig({ endpoints: [{ id: 'ep-1', label: '旧', base_url: 'http://old:8000' }], probe_timeout_ms: 1000 })
  const out = await core.handleApiRequest(
    { method: 'POST', pathname: '/probe', headers: { 'x-vllm-kb': '1' }, body: JSON.stringify({ endpoint_id: 'ep-1', base_url: 'http://new:9000/', probe_timeout_ms: 250 }) },
    { readConfig: async () => ({ config, error: null }), probe: async (url, timeoutMs) => { sent.push([url, timeoutMs]); return { ok: true, status: 200, elapsed_ms: 3 } } },
  )
  eq(sent, [['http://new:9000', 250]], '应探页面上的地址与超时，不是配置文件里那条')
  eq(out.payload.ok, true)
  eq(out.payload.base_url, 'http://new:9000')
  eq(out.payload.saved, false, '这个地址还没保存')
  return true
})
check('没保存的地址不写探测缓存（工具侧可用性不该跟着变）', async () => {
  const written = []
  const config = core.normalizeConfig({ endpoints: [{ id: 'ep-1', label: '旧', base_url: 'http://old:8000' }] })
  await core.handleApiRequest(
    { method: 'POST', pathname: '/probe', headers: { 'x-vllm-kb': '1' }, body: JSON.stringify({ endpoint_id: 'ep-1', base_url: 'http://new:9000' }) },
    { readConfig: async () => ({ config, error: null }), probe: async () => ({ ok: true, status: 200, elapsed_ms: 1 }), cache: { set: (id, value) => written.push([id, value]) } },
  )
  eq(written.length, 0)
  return true
})
check('探的就是已保存的地址 → 照旧写缓存', async () => {
  const written = []
  const config = core.normalizeConfig({ endpoints: [{ id: 'ep-1', label: '现行', base_url: 'http://old:8000' }] })
  const out = await core.handleApiRequest(
    { method: 'POST', pathname: '/probe', headers: { 'x-vllm-kb': '1' }, body: JSON.stringify({ endpoint_id: 'ep-1', base_url: 'http://old:8000' }) },
    { readConfig: async () => ({ config, error: null }), probe: async () => ({ ok: true, status: 200, elapsed_ms: 2 }), cache: { set: (id, value) => written.push([id, value]) } },
  )
  eq(written.length, 1)
  eq(written[0][0], 'ep-1')
  eq(out.payload.saved, true)
  return true
})
check('地址还没填 → 明确说没填，不发请求', async () => {
  let called = false
  const out = await core.handleApiRequest(
    { method: 'POST', pathname: '/probe', headers: { 'x-vllm-kb': '1' }, body: JSON.stringify({ endpoint_id: 'ep-new', base_url: '   ' }) },
    { readConfig: async () => ({ config: core.normalizeConfig(null), error: null }), probe: async () => { called = true; return { ok: true } } },
  )
  eq(called, false)
  eq(out.payload.ok, false)
  ok(/还没有地址/.test(out.payload.detail), 'detail 应说明还没地址')
  return true
})
check('未知路径 → 404', async () => {
  const out = await core.handleApiRequest({ method: 'GET', pathname: '/nope', headers: { 'x-vllm-kb': '1' } })
  eq(out.status, 404)
  return true
})

console.log('[8] 命令行入口（scripts/vllm_kb_config.mjs）')
// 设置页渲染不出来时的兜底：它 import 的是插件里的 core.js，路径写错就整条命令不能用。
const cliPath = fileURLToPath(new URL('../scripts/vllm_kb_config.mjs', import.meta.url))
function cli(dir, args) {
  const env = Object.assign({}, process.env, { KB_EVIDENCE_CONFIG: join(dir, 'vllm-kb.json') })
  return execFileSync(process.execPath, [cliPath].concat(args), { env, encoding: 'utf8' })
}
check('show 能跑起来并打印配置（模块路径没断）', () => {
  const out = cli(join(workdir, 'cli-show'), ['show'])
  ok(out.includes('"endpoints"'), 'show 应打印配置 JSON')
  ok(out.includes('还没有端点'), '空配置应提示怎么加')
  return true
})
check('add-endpoint 写进去，show 读得回来', () => {
  const dir = join(workdir, 'cli-add')
  cli(dir, ['add-endpoint', '本地', 'http://127.0.0.1:8000'])
  const out = cli(dir, ['show'])
  ok(out.includes('"label": "本地"'), '应读回端点名称')
  ok(out.includes('http://127.0.0.1:8000'), '应读回端点地址')
  return true
})
check('remove 删掉后回到空配置', () => {
  const dir = join(workdir, 'cli-remove')
  cli(dir, ['add-endpoint', '本地', 'http://127.0.0.1:8000'])
  cli(dir, ['remove', '本地'])
  ok(cli(dir, ['show']).includes('还没有端点'), '删掉后应是空配置')
  return true
})

await runChecks()

server.close()
await rm(workdir, { recursive: true, force: true })
delete process.env.KB_EVIDENCE_CONFIG

console.log('')
if (failures > 0) {
  console.log(`vllm-kb 接入自测失败：${failures}/${queue.length} 项`)
  process.exit(1)
}
console.log(`vllm-kb 接入自测通过：${queue.length} 项（全部打桩，不需要 DSH 与内网实例）`)
