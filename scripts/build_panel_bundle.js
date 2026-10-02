#!/usr/bin/env node
// build_panel_bundle.js —— 把面板的**动态插件源码**拼成 DSH **常驻插件包**的两个产物
//
// 为什么需要它：新版 DSH 删掉了模型侧的 `cordis_define` / `cordis_run`（源码检出 0.1.5-rc.1
// 还有、装着的 0.1.7-rc.2 只剩两个只读检查工具），面板不能再靠运行时热加载；新版支持的是
// **常驻插件包**——`package.json` 声明 `dsh.bundle.patch`，用插件管理器的 install_bundle 装进
// profile，装一次、每个会话都在、重启不丢。
//
// 面板源码是动态插件方言：文件是函数体 `return { apply(ctx) {...} }`，靠沙箱给的 `harness`
// （host 半）与 `host`（client 半）通信。**旧 DSH 仍走热加载读同一份文件**，所以这里不改面板
// 源码一个字，而是把原文嵌进常驻插件，并补一层薄适配：
//
//   host 半： harness.handle(name, fn)        → ctx.connection.rpc.handle(CHANNEL, 分发表)
//            harness.registerTool(ctx, tool)  → ctx.tools.register(tool)
//            harness.defineTool               → 从 dsh 安装处解析的 @deepseek-ai/dsh-tools
//                                               （桌面端注册了 @deepseek-ai/* 模块回退，
//                                                symlink 装的 profile 插件能直接 import）
//   client 半：host.call(name, args)          → ctx.get('connection').rpc.call(CHANNEL, name, args)
//
// 生成物进 git（与 knowledge/_index、triage-tree.yaml 同一约定：生成物随 PR 走），
// 一致性由 `--check` 把关——源文件改了没重跑生成器即红。
//
// 用法：
//   node scripts/build_panel_bundle.js           生成/覆盖两个产物
//   node scripts/build_panel_bundle.js --check    只校验（CI 用；不一致则退出码 1）

'use strict'

const fs = require('fs')
const path = require('path')
const crypto = require('crypto')

const repo = path.resolve(__dirname, '..')

// 包目录名 = 插件行 name；一个包带两个面板（tab id 不同，互不冲突）
const BUNDLE_DIR = 'dsh-plugins/dsh-sleuth-panels'
const BUNDLE_NAME = 'dsh-sleuth-panels'
const CHANNEL = '/ascend-sleuth-panels'

// 面板清单：id 只用于日志前缀；host/client 是动态方言的源文件（唯一真源）
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

function readSource(rel) {
  return fs.readFileSync(path.join(repo, rel), 'utf8')
}

function fingerprint(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 12)
}

function provenance(rel, text) {
  return '// ---- ' + rel + ' (sha256:' + fingerprint(text) + ') 原文开始 ----'
}

const PROVENANCE_END = '// ---- 原文结束 ----'

// ── host 半产物：常驻 Cordis 插件（ESM） ──────────────────────────────────────
function renderHost() {
  const sources = PANELS.map(p => ({ id: p.id, rel: p.host, text: readSource(p.host) }))

  const header = [
    '/* eslint-disable */',
    '// 生成物 —— 勿手改。由 `node scripts/build_panel_bundle.js` 从下列源文件拼出：',
    ...sources.map(s => '//   ' + s.rel + '  (sha256:' + fingerprint(s.text) + ')'),
    '// 校验：`node scripts/build_panel_bundle.js --check`（源文件改了没重跑生成器即红）。',
    '//',
    '// 面板源码是动态插件方言（文件是函数体，靠沙箱提供的 harness 通信）；这里原文嵌入常驻',
    '// 插件，并补一层适配：harness.handle → connection RPC 路由分发表、harness.registerTool →',
    '// ctx.tools.register、harness.defineTool → dsh 自带 @deepseek-ai/dsh-tools。',
    '',
  ].join('\n')

  const panels = sources.map(s => [
    '  {',
    "    id: '" + s.id + "',",
    '    build(harness) {',
    '      return (function () {',
    provenance(s.rel, s.text),
    s.text.replace(/\s*$/, ''),
    PROVENANCE_END,
    '      })()',
    '    },',
    '  },',
  ].join('\n')).join('\n')

  return header + [
    "import { defineTool } from '@deepseek-ai/dsh-tools'",
    '',
    "const CHANNEL = '" + CHANNEL + "'",
    '// 单次请求体上限（面板的 RPC 都是小 JSON；上限只为挡住失控请求）',
    'const MAX_BODY_BYTES = 1024 * 1024',
    '',
    '// 适配层：把动态插件方言的 harness 接到常驻插件 API 上。',
    '//',
    '// defineTool 有一处方言差异：动态沙箱的 harness.defineTool 会把 parameters 归一化',
    '//（JSON-Schema 包装 { type:"object", properties:{…}, required:[…] } → DSL { 字段: schema, required: true }），',
    '// 常驻包拿到的 dsh 自带 defineTool 只认 DSL。面板源码用的是包装写法，这里补这一步；',
    '// 缺了它参数校验会抛 unsupported JSON schema: parameters.type must be a value schema object，',
    '// 而那次抛在面板自身的 try/catch 之外，整个 host 半挂不上去（实测：RPC 全部没注册）。',
    'function toParameterSpec(parameters) {',
    '  if (parameters === undefined || parameters === null) return {}',
    '  const isWrapper = parameters.type !== undefined || parameters.properties !== undefined',
    '  if (!isWrapper) return parameters',
    '  const required = Array.isArray(parameters.required) ? parameters.required : []',
    '  const properties = parameters.properties || {}',
    '  const spec = {}',
    '  for (const [key, schema] of Object.entries(properties)) {',
    '    const field = Object.assign({}, schema)',
    '    if (required.indexOf(key) >= 0) field.required = true',
    '    spec[key] = field',
    '  }',
    '  return spec',
    '}',
    '',
    'function makeHarness(ctx, handlers) {',
    '  return {',
    '    defineTool(options) {',
    '      return defineTool(Object.assign({}, options, { parameters: toParameterSpec(options.parameters) }))',
    '    },',
    '    registerTool(_ctx, tool) { return ctx.tools.register(tool) },',
    '    handle(endpoint, fn) {',
    '      const key = String(endpoint)',
    '      handlers.set(key, fn)',
    '      return () => { handlers.delete(key) }',
    '    },',
    '  }',
    '}',
    '',
    'const PANELS = [',
    panels,
    ']',
    '',
    "export const name = '" + BUNDLE_NAME + "'",
    "export const inject = ['connection', 'tools']",
    '',
    'export function apply(ctx) {',
    '  const handlers = new Map()',
    '  const harness = makeHarness(ctx, handlers)',
    '',
    '  // 一条 HTTP 路由承载两个面板的所有 RPC（端点名不冲突：ascend-* / ev-*）。',
    '  //',
    '  // 为什么不用 ctx.connection.rpc.handle：它的实现是',
    '  //   get rpc() { const owner = this.ctx; return { handle: (…) => this.register(owner, …) } }',
    '  // owner 绑的是 connection 服务自己的 ctx，注册时读 owner.webServer → 报',
    '  // cannot get property "webServer" without inject（实测；in-app 的 dsh-ppt 也把这一步',
    '  // 包在 try/catch 里，真正干活的是它自己注册的 webServer 路由）。',
    '  // 客户端 connection.rpc.call 会 POST <channel>/<endpoint>，body 为',
    "  // { type: 'client-request', rpcId, method, payload }（method 是端点名，URL 里也带一份），",
    "  // 应答 { type: 'server-response', rpcId, result }，其中 result 就是下面的 { ok, value } |",
    '  // { ok: false, error } 信封（客户端会逐个校验这三个字段）。',
    "  ctx.inject(['webServer'], (webCtx) => {",
    '    webCtx.effect(() => webCtx.webServer.register({',
    "      kind: 'prefix',",
    '      path: CHANNEL,',
    '      handler: async (req, res) => {',
    "        if (req.method !== 'POST') {",
    "          res.setHeader('Allow', 'POST')",
    '          res.writeHead(405)',
    '          res.end()',
    '          return',
    '        }',
    "        const rejection = webCtx.get('connection')?.requestRejection?.(req)",
    '        if (rejection !== undefined) {',
    '          res.writeHead(rejection)',
    "          res.end(rejection === 401 ? 'unauthorized' : 'forbidden')",
    '          return',
    '        }',
    '        const chunks = []',
    '        let received = 0',
    '        for await (const chunk of req) {',
    '          received += chunk.length',
    '          if (received > MAX_BODY_BYTES) {',
    '            res.writeHead(413)',
    "            res.end('payload too large')",
    '            return',
    '          }',
    '          chunks.push(chunk)',
    '        }',
    '        let body',
    '        try {',
    "          body = JSON.parse(Buffer.concat(chunks).toString('utf8'))",
    '        } catch (e) {',
    '          res.writeHead(400)',
    "          res.end('body is not JSON')",
    '          return',
    '        }',
    "        const rawPath = new URL(req.url === undefined ? '/' : req.url, 'http://localhost').pathname",
    "        const pathEndpoint = rawPath.startsWith(CHANNEL + '/') ? rawPath.slice(CHANNEL.length + 1) : ''",
    '        // 端点优先取 URL；客户端也把端点写在 body.method 里，作为回退（前缀匹配方式变了也不至丢端点）',
    "        const endpoint = pathEndpoint !== '' ? pathEndpoint : (typeof body.method === 'string' ? body.method : '')",
    '        const fn = handlers.get(endpoint)',
    '        let result',
    '        if (fn === undefined) {',
    "          result = { ok: false, error: { code: 'not-found', message: '未知的 RPC 端点: ' + endpoint, details: {} } }",
    '        } else {',
    '          try {',
    '            const payload = body === undefined || body.payload === undefined ? {} : body.payload',
    '            result = { ok: true, value: await fn(payload) }',
    '          } catch (e) {',
    "            result = { ok: false, error: { code: 'internal', message: String((e && e.message) || e), details: {} } }",
    '          }',
    '        }',
    "        res.writeHead(200, { 'Content-Type': 'application/json' })",
    "        res.end(JSON.stringify({ type: 'server-response', rpcId: body === undefined ? undefined : body.rpcId, result }))",
    '      },',
    "    }), 'dsh-sleuth-panels: ' + CHANNEL + ' rpc route')",
    "    console.error('[dsh-sleuth-panels] RPC 路由已注册: ' + CHANNEL)",
    '  })',
    '',
    '  const disposers = []',
    '  for (const panel of PANELS) {',
    '    try {',
    '      const plugin = panel.build(harness)',
    '      const dispose = plugin.apply(ctx)',
    '      if (typeof dispose === \'function\') disposers.push(dispose)',
    '    } catch (e) {',
    "      console.error('[dsh-sleuth-panels] ' + panel.id + ' host 半挂载失败: ' + String((e && e.message) || e))",
    '    }',
    '  }',
    '',
    '  return () => {',
    '    for (const dispose of disposers) {',
    '      try { dispose() } catch (e) { /* 一个面板卸载失败不阻塞其余 */ }',
    '    }',
    '    handlers.clear()',
    '  }',
    '}',
    '',
  ].join('\n')
}

// ── client 半产物：页面的模块表产物（window.__ModuleLoader__.load） ────────────
function renderClient() {
  const sources = PANELS.map(p => ({ id: p.id, rel: p.client, text: readSource(p.client) }))

  const header = [
    '/* eslint-disable */',
    '// 生成物 —— 勿手改。由 `node scripts/build_panel_bundle.js` 从下列源文件拼出：',
    ...sources.map(s => '//   ' + s.rel + '  (sha256:' + fingerprint(s.text) + ')'),
    '// 校验：`node scripts/build_panel_bundle.js --check`。',
    '//',
    '// 面板源码是动态插件方言（靠沙箱提供的 host 通信）；这里原文嵌入页面产物，并补一层适配：',
    "// host.call(name, args) → ctx.get('connection').rpc.call(CHANNEL, name, args)。",
    '// React 由页面的模块表提供（与宿主同一份，不重复安装）。',
    '',
  ].join('\n')

  const panels = sources.map(s => [
    '    {',
    "      id: '" + s.id + "',",
    '      build(host, styles) {',
    '        return (function () {',
    provenance(s.rel, s.text),
    s.text.replace(/\s*$/, ''),
    PROVENANCE_END,
    '        })()',
    '      },',
    '    },',
  ].join('\n')).join('\n')

  return header + [
    'window.__ModuleLoader__.load({',
    "  id: '" + BUNDLE_NAME + "',",
    '  factory: (require) => {',
    '    const module = { exports: {} }',
    '    const exports = module.exports',
    '    Object.defineProperty(exports, Symbol.toStringTag, { value: \'Module\' })',
    '',
    "    const React = require('react')",
    '',
    "    const CHANNEL = '" + CHANNEL + "'",
    '',
    '    // 适配层：动态插件方言的 host.call 接到 connection RPC 上',
    '    function makeHost(ctx) {',
    "      const connection = ctx.get('connection')",
    '      return {',
    '        call(endpoint, payload, signal) {',
    "          if (connection === undefined || connection.rpc === undefined) {",
    "            return Promise.reject(new Error('connection 服务不可用'))",
    '          }',
    '          return connection.rpc',
    '            .call(CHANNEL, String(endpoint), payload === undefined ? {} : payload, signal)',
    '            .then((outer) => {',
    '              if (outer === undefined || outer.ok !== true) {',
    "                const failure = outer && outer.error",
    '                throw new Error(failure && failure.message ? failure.message : \'RPC 失败\')',
    '              }',
    '              return outer.value',
    '            })',
    '        },',
    '      }',
    '    }',
    '',
    '    // 动态客户端沙箱还给每个包注入 `styles.insert(css) -> disposer`（自建 <style> 标签，',
    '    // 随包卸载一起清）。常驻包没有这层，这里照它的语义补一个，否则面板 apply 一上来',
    "    // `styles.insert(PANEL_CSS)` 就 ReferenceError（冒烟测试抓到过）。",
    '    function makeStyles() {',
    '      const tags = new Set()',
    '      return {',
    '        insert(css) {',
    "          if (typeof css !== 'string') throw new Error('styles.insert(css) needs a CSS string')",
    "          const tag = document.createElement('style')",
    "          tag.dataset.dshSleuthPanels = 'true'",
    '          tag.textContent = css',
    '          document.head.append(tag)',
    '          tags.add(tag)',
    '          return () => { tags.delete(tag); tag.remove() }',
    '        },',
    '        dispose() { for (const tag of tags) tag.remove(); tags.clear() },',
    '      }',
    '    }',
    '',
    '    const PANELS = [',
    panels,
    '    ]',
    '',
    "    exports.name = '" + BUNDLE_NAME + "'",
    "    exports.inject = ['slots', 'connection']",
    '    exports.apply = function apply(ctx) {',
    '      const host = makeHost(ctx)',
    '      const styles = makeStyles()',
    '      const disposers = []',
    '      for (const panel of PANELS) {',
    '        try {',
    '          const plugin = panel.build(host, styles)',
    '          const dispose = plugin.apply(ctx)',
    "          if (typeof dispose === 'function') disposers.push(dispose)",
    '        } catch (e) {',
    "          console.error('[dsh-sleuth-panels] ' + panel.id + ' client 半挂载失败: ' + String((e && e.message) || e))",
    '        }',
    '      }',
    '      return () => {',
    '        for (const dispose of disposers) {',
    '          try { dispose() } catch (e) { /* 一个面板卸载失败不阻塞其余 */ }',
    '        }',
    '        styles.dispose()',
    '      }',
    '    }',
    '',
    '    return module.exports',
    '  },',
    '})',
    '',
  ].join('\n')
}

const ARTIFACTS = [
  { rel: BUNDLE_DIR + '/lib/index.js', render: renderHost },
  { rel: BUNDLE_DIR + '/lib/client.js', render: renderClient },
]

function main() {
  const check = process.argv.includes('--check')
  const stale = []

  for (const artifact of ARTIFACTS) {
    const target = path.join(repo, artifact.rel)
    const next = artifact.render()
    const current = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : null

    if (check) {
      if (current !== next) {
        stale.push(artifact.rel + (current === null ? '（缺失）' : '（与源文件不一致）'))
      }
      continue
    }

    if (current === next) {
      process.stdout.write('unchanged  ' + artifact.rel + '\n')
      continue
    }
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, next, 'utf8')
    process.stdout.write('wrote      ' + artifact.rel + '  (' + next.length + ' bytes)\n')
  }

  if (!check) return

  if (stale.length > 0) {
    process.stderr.write('面板包产物与源文件不一致（跑 `node scripts/build_panel_bundle.js` 重新生成）：\n')
    for (const rel of stale) process.stderr.write('  - ' + rel + '\n')
    process.exit(1)
  }
  process.stdout.write('面板包产物与源文件一致\n')
}

main()
