#!/usr/bin/env node
// check_loader_idempotency.js —— 校验 panel_from_file 的"重复调用=重载"匹配规则
//
// 背景：loader（dsh-plugins/loader/panel-from-file.js）是动态 Cordis 插件，代码是
// 函数体、不能 import，所以这里用**规则副本**做单元测试，并额外断言 loader 源文件里
// 仍有对应标记——两者一起保证"测试测的规则 = loader 实际用的规则"（防漂移）。
//
// 为什么规则本身要测：DSH 的 define(kind: 'existing') 只允许追加到**当前 session 拥有**
// 的插件（cordis-host-runner: found.sessionId !== request.sessionId 即抛错），所以
// 归属过滤写错会导致"想重载却抛错"或"明明有插件却新建"。
//
// 用法：node scripts/check_loader_idempotency.js   全绿退出码 0

const fs = require('fs')
const path = require('path')

const repo = path.resolve(__dirname, '..')
const LOADER = path.join(repo, 'dsh-plugins/loader/panel-from-file.js')

// —— loader 里的规则副本（与 findExisting 保持一致）——
function findExisting(rows, agentId, idPrefix) {
  if (idPrefix === undefined) return undefined
  const prefix = String(idPrefix)
  const mine = (rows || []).filter(r => r && r.agentId === agentId)
  return mine.find(r => r.pluginId === prefix)
    || mine.find(r => String(r.pluginId).replace(/-\d+$/, '') === prefix)
    || mine.find(r => String(r.pluginId).startsWith(prefix + '-'))
}

const fails = []
function expect(name, cond, extra) {
  if (cond) console.log('  ✓ ' + name)
  else { console.log('  ✗ ' + name + (extra ? ' :: ' + extra : '')); fails.push(name) }
}

const rows = [
  { pluginId: 'evbd-10', agentId: 'sess-A', currentPackageId: 'pkg-16' },
  { pluginId: 'sleu-11', agentId: 'sess-A', currentPackageId: 'pkg-15' },
  { pluginId: 'evbd-3', agentId: 'sess-OLD', currentPackageId: 'pkg-1' },   // 旧 session 遗留
  { pluginId: 'ldr-12', agentId: 'sess-OLD' },                             // 失败、无 current
]

console.log('[匹配规则]')
expect('同 session 同前缀命中', findExisting(rows, 'sess-A', 'evbd')?.pluginId === 'evbd-10')
expect('不同前缀不误命中', findExisting(rows, 'sess-A', 'sleu')?.pluginId === 'sleu-11')
expect('无关前缀返回 undefined', findExisting(rows, 'sess-A', 'zzzz') === undefined)
expect('跨 session 的插件不被认领（否则 define 会抛归属错误）',
  findExisting(rows, 'sess-NEW', 'evbd') === undefined)
expect('idPrefix 省略时不查找', findExisting(rows, 'sess-A', undefined) === undefined)
expect('精确 id 优先于前缀匹配',
  findExisting([{ pluginId: 'evbd', agentId: 'sess-A' }, { pluginId: 'evbd-10', agentId: 'sess-A' }], 'sess-A', 'evbd')?.pluginId === 'evbd')
expect('带数字后缀的旧写法也能命中', findExisting([{ pluginId: 'evbd-99', agentId: 'sess-A' }], 'sess-A', 'evbd')?.pluginId === 'evbd-99')

console.log('\n[loader 源文件仍含对应实现]')
const src = fs.readFileSync(LOADER, 'utf8')
expect('findExisting 存在', /function findExisting\(/.test(src))
expect('归属过滤按 agentId', /r\.agentId === agentId/.test(src))
expect('三段匹配（精确 / 去后缀 / 前缀）',
  /r\.pluginId === prefix/.test(src) && /replace\(\/-\\d\+\$\/, ''\) === prefix/.test(src) && /startsWith\(prefix \+ '-'\)/.test(src))
expect('同前缀重复调用走 existing 分支', /const existing = args\.pluginId === undefined \? findExisting\(/.test(src))
expect('mode 自动推导（有 currentPackageId 才 update）', /row\.currentPackageId !== undefined \? 'update' : 'run'/.test(src))
expect('返回 reused 标记', /reused: targetPluginId !== undefined/.test(src))
expect('工具重名不抛错（工具注册是进程全局的，第二份 loader 应降级）',
  /already registered/.test(src) && /本次跳过注册/.test(src))

console.log('\n' + (fails.length ? '失败 ' + fails.length + ' 项: ' + fails.join(' | ') : '全部通过'))
process.exit(fails.length ? 1 : 0)
