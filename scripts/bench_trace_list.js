#!/usr/bin/env node
// bench_trace_list.js —— 列表解析缓存的 I/O 侧对照（不进 CI，按需跑）
//
// 它量的是"每次刷新要读多少字节"：无缓存 = 枚举目录 + 读完所有 trace；
// 有缓存 = 枚举目录 + 只读版本变了的文件。**YAML 解析成本不计入**（本脚本没有
// 面板那套解析器），而缓存的全部意义正是让解析只发生在变更文件上，所以这里
// 用读取字节数近似下限；真实收益还要加上省掉的解析时间。
//
// 用法：
//   node scripts/bench_trace_list.js            # 默认 500 条
//   node scripts/bench_trace_list.js --count 50
// 退出码：0 正常；1 参数错误 / 临时目录不可写。

'use strict'

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

function parseArgs(argv) {
  const args = { count: 500 }
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--count' && argv[i + 1]) { args.count = Number(argv[i + 1]); i += 1 }
  }
  if (!Number.isFinite(args.count) || args.count <= 0) throw new Error('--count 需要正整数')
  return args
}

function ms(t0) { return Math.round((performance.now() - t0) * 10) / 10 }

function main() {
  const { count } = parseArgs(process.argv.slice(2))
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleu-bench-'))
  let totalBytes = 0
  try {
    // 合成 trace：约 20 KB/条（含一段内联证据），贴近真实规模
    const evidence = 'E'.repeat(16000)
    for (let i = 0; i < count; i += 1) {
      const id = String(i).padStart(5, '0')
      const body = [
        'session_id: bench-' + id,
        'status: ' + (i % 3 === 0 ? 'in_progress' : 'resolved'),
        'created_at: 2026-10-01T08:00:00Z',
        'updated_at: 2026-10-01T09:00:00Z',
        'summary: 合成压测数据，用于对照列表读取成本。',
        'trace:',
        '  - {role: user, step: 1, content: "bench", evidence: {inline: "' + evidence + '"}}',
        '  - {role: agent, step: 2, action: triage, output: "bench"}',
        '',
      ].join('\n')
      fs.writeFileSync(path.join(dir, 'bench-' + id + '.yaml'), body)
      totalBytes += Buffer.byteLength(body)
    }

    const names = fs.readdirSync(dir).filter(n => n.endsWith('.yaml'))

    // ① 无缓存：读完所有文件
    let t = performance.now()
    let readAll = 0
    for (const n of names) readAll += fs.readFileSync(path.join(dir, n), 'utf8').length
    const full = ms(t)

    // ② 有缓存（全部命中）：枚举 + 取版本（mtime+size），不读内容
    t = performance.now()
    let hits = 0
    for (const n of names) {
      const st = fs.statSync(path.join(dir, n))
      if (st.size > 0 && st.mtimeMs > 0) hits += 1
    }
    const cached = ms(t)

    // ③ 有缓存（只改 1 条）：枚举 + 只读那 1 条
    const changed = names[0]
    fs.appendFileSync(path.join(dir, changed), '# changed\n')
    t = performance.now()
    let readOne = 0
    for (const n of names) {
      const st = fs.statSync(path.join(dir, n))
      if (n === changed && st.size > 0) readOne += fs.readFileSync(path.join(dir, n), 'utf8').length
    }
    const oneChanged = ms(t)

    const mb = (n) => (n / 1024 / 1024).toFixed(2) + ' MB'
    console.log('trace 数量：' + count + '｜合成总大小：' + mb(totalBytes))
    console.log('  无缓存（读全部）      ' + full + ' ms｜读 ' + mb(readAll))
    console.log('  有缓存（全部命中）    ' + cached + ' ms｜读 0 MB（' + hits + ' 条命中版本）')
    console.log('  有缓存（改 1 条）     ' + oneChanged + ' ms｜读 ' + mb(readOne))
    console.log('说明：只量目录枚举与读取；YAML 解析只在"未命中"的文件上发生，本脚本不计入。')
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

try {
  main()
} catch (e) {
  console.error('bench 失败：' + String(e && e.message || e))
  process.exit(1)
}
