#!/usr/bin/env node
// 把 client-src/*.js 拼成 lib/client.js。
//
// 每个 client-src 文件是“纯脚本函数体”，build 时原文包进 (function (SC) { … })(SC)，
// 文件之间只通过 SC 通信。产物结构见 docs/CONTRACT.md §1。
//
//   node build.mjs          生成 lib/client.js
//   node build.mjs --check  只校验产物是否最新（不一致 exit 1）
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises'
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

const chunks = []
for (const name of files) {
  const content = await readFile(path.join(srcDir, name), 'utf8')
  if (/^\s*(import|export)\s/m.test(content)) {
    console.error(`client-src/${name} 里出现 import/export：产物是函数体方言，不允许 ESM 语法`)
    process.exit(1)
  }
  chunks.push(
    `\n// ─── client-src/${name} ───\n;(function (SC) {\n${content.replace(/\s+$/, '')}\n})(SC)\n`,
  )
}

const banner = `/* eslint-disable */
// 生成物 —— 勿手改。由 \`node build.mjs\` 从 client-src/*.js 拼出：
//   ${files.join('\n//   ')}
// 校验：\`node build.mjs --check\`。
// 契约：docs/CONTRACT.md §1。
`
const artifact = `${banner}window.__ModuleLoader__.load({
  id: ${JSON.stringify(pkg.name)},
  factory(require) {
    const React = require('react')
    const SC = { React, h: React.createElement, version: ${JSON.stringify(pkg.version)} }
${chunks.join('')}
    if (SC.plugin === undefined || typeof SC.plugin.apply !== 'function') {
      throw new Error('sleuth-canvas: client-src 没有装配出 SC.plugin.apply')
    }
    return SC.plugin
  },
})
`

const previous = await readFile(outFile, 'utf8').catch(() => null)
if (process.argv.includes('--check')) {
  if (previous === artifact) {
    console.log('lib/client.js up to date (' + files.length + ' modules, ' + artifact.length + ' bytes)')
    process.exit(0)
  }
  console.error('lib/client.js 与 client-src 不一致：跑 node build.mjs')
  process.exit(1)
}

await mkdir(path.dirname(outFile), { recursive: true })
await writeFile(outFile, artifact)
console.log('wrote lib/client.js (' + files.length + ' modules, ' + artifact.length + ' bytes)')
