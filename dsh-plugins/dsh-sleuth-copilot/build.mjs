#!/usr/bin/env node
// 把 client-src/*.js 按文件名排序拼成 lib/client.js。
//
// client-src 里每个文件是 factory 函数体的一段原文，文件之间共享同一层词法作用域；
// 拼接逐字进行：不加分隔行、不改缩进，切片可以跨语法结构（不要单独执行）。
// 产物必须与拆分前逐字节一致：`cmp /tmp/copilot-client-before.js lib/client.js`。
//
//   node build.mjs          生成 lib/client.js
//   node build.mjs --check  只校验产物是否最新（不一致 exit 1）
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.join(root, 'client-src')
const outFile = path.join(root, 'lib', 'client.js')
const pkg = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'))

const files = (await readdir(srcDir)).filter((name) => name.endsWith('.js')).sort()
if (files.length === 0) {
  console.error('client-src/ 里没有 .js 文件')
  process.exit(1)
}

const HEADER = `/* eslint-disable */
// dsh-sleuth-copilot —— 浏览器半：诊断交互层
//
// 四个面共用一份数据、一套动作与一条偏好：
//   1. conversation.input.dock    状态条（可收起，收起状态记住）
//   2. conversation.input.right   输入区工具条入口（带待回报角标）
//   3. shell.overlay              诊断工作台（全库列表 + 键盘操作 + 改状态）
//   4. 共享的写入菜单与表单：收尾 / 重开 / 沉淀状态；回报结果生成指令（该轴暂无脚本写入口）
//
// 读：Host 半的 copilot-state（判据在 scripts/_trace_state.py）。
// 写：Host 半的 copilot-transition → scripts/trace_transition.py（校验 + CAS + 事件）。
// 浏览器这里不解析 YAML，也不自己判状态：显示与可选动作都跟着投影给出的字段走。

window.__ModuleLoader__.load({
  id: '${pkg.name}',
  factory: (require) => {
`

const FOOTER = `  },
})
`

const chunks = []
for (const name of files) {
  const content = await readFile(path.join(srcDir, name), 'utf8')
  if (/^\s*(import|export)\s/m.test(content)) {
    console.error(`client-src/${name} 里出现 import/export：产物是函数体方言，不允许 ESM 语法`)
    process.exit(1)
  }
  chunks.push(content)
}

const artifact = HEADER + chunks.join('') + FOOTER
const previous = await readFile(outFile, 'utf8').catch(() => null)
if (process.argv.includes('--check')) {
  if (previous === artifact) {
    console.log('lib/client.js up to date (' + files.length + ' slices, ' + Buffer.byteLength(artifact) + ' bytes)')
    process.exit(0)
  }
  console.error('lib/client.js 与 client-src 不一致：跑 node build.mjs')
  process.exit(1)
}

await writeFile(outFile, artifact)
console.log('wrote lib/client.js (' + files.length + ' slices, ' + Buffer.byteLength(artifact) + ' bytes)')
