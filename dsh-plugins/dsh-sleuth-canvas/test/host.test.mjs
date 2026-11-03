// host 半测试：node 直跑（`node test/host.test.mjs`），不依赖 DSH 运行时。
//
// 数据来源：把 fixtures/trace-samples/ 复制进临时目录、补 scripts/metrics_health.py 标记，
// 得到一个自包含的假 ascend-sleuth 仓库；不读本机任何真实检出。边界情况另建临时目录。
// 断言来源：
//   · fixtures/*.json —— 由 fixtures/build-fixtures.py 用 host 归一化生成（契约样例）；
//   · docs/CONTRACT.md —— §2.2 YAML 能力、§2.3/§2.4 字段、§2.4 insights 1-9、§2.5 健壮性。
// 样例覆盖的文案逐字对齐；契约里样例未覆盖的规则（4/5/6/8/9 的风险/缺口/续接等）在
// 独立的 insights 单元测试里断言。

import test, { after } from 'node:test'
import assert from 'node:assert/strict'
import fsp from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'

import { apply, __test } from '../host/index.js'

const FIXTURES = path.resolve(import.meta.dirname, '..', 'fixtures')
const CHANNEL = __test.CHANNEL

// ---- 假 fs：语义照 CONTRACT §2（resolve/readText/listDir/stat + version 令牌） --------

function makeRealFs(options = {}) {
  const counters = { resolve: 0, readText: 0, listDir: 0, stat: 0 }
  const versionOverride = options.versionOverride || new Map()
  const readErrors = options.readErrors || new Set()
  const target = (p) => ({ path: p, displayPath: p })
  const fs = {
    counters,
    versionOverride,
    async resolve(p, opts) {
      counters.resolve++
      const cwd = opts && opts.cwd ? opts.cwd : process.cwd()
      return target(path.isAbsolute(p) ? path.normalize(p) : path.resolve(cwd, p))
    },
    async readText(t) {
      counters.readText++
      const name = path.basename(t.displayPath)
      if (readErrors.has(name)) {
        const error = new Error('read failed: ' + name)
        error.code = 'EACCES'
        throw error
      }
      return fsp.readFile(t.displayPath, 'utf8')
    },
    async listDir(t) {
      counters.listDir++
      const entries = await fsp.readdir(t.displayPath, { withFileTypes: true })
      const out = []
      for (const entry of entries) {
        const full = path.join(t.displayPath, entry.name)
        let version = null
        let size = null
        try {
          const info = await fsp.stat(full)
          version = versionOverride.has(entry.name) ? versionOverride.get(entry.name) : String(info.mtimeMs)
          size = info.size
        } catch {}
        out.push({ name: entry.name, type: entry.isDirectory() ? 'directory' : 'file', version, size })
      }
      return out
    },
    async stat(t) {
      counters.stat++
      try {
        const info = await fsp.stat(t.displayPath)
        return {
          type: info.isDirectory() ? 'directory' : 'file',
          size: info.size,
          mtimeMs: info.mtimeMs,
          displayPath: t.displayPath,
        }
      } catch {
        const error = new Error('not found: ' + t.displayPath)
        error.code = 'FS_NOT_FOUND'
        throw error
      }
    },
  }
  return fs
}

function makeCtx(services) {
  return {
    get(name) {
      return services[name]
    },
    inject(names, callback) {
      callback({
        get(name) {
          return services[name]
        },
        effect(fn) {
          return fn()
        },
        webServer: services.webServer,
      })
    },
  }
}

function makeSessions(cwds) {
  const list = cwds.map((cwd) => ({ header: { cwd } }))
  return {
    async list() {
      return list
    },
    async get(sessionId) {
      if (sessionId === 'missing') return undefined
      return list[0]
    },
  }
}

function makeHost({ cwds = [FIXTURE_REPO], fs = makeRealFs(), sessions } = {}) {
  return __test.createHost(makeCtx({ fs, sessions: sessions || makeSessions(cwds) }))
}

// ---- 临时 fixture 目录 ------------------------------------------------------

const tempDirs = []
async function makeTempRepo(files) {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'sleuth-canvas-'))
  tempDirs.push(root)
  for (const [relative, content] of Object.entries(files)) {
    const full = path.join(root, relative)
    await fsp.mkdir(path.dirname(full), { recursive: true })
    await fsp.writeFile(full, content, 'utf8')
  }
  return root
}

// 自包含假仓库：fixtures/trace-samples/ → <tmp>/traces/，再补一个仓库标记文件。
// 测试只读它，不碰本机任何真实 ascend-sleuth 检出。
const FIXTURE_REPO = await (async () => {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), 'sleuth-canvas-fixture-'))
  tempDirs.push(root)
  await fsp.cp(path.join(FIXTURES, 'trace-samples'), path.join(root, 'traces'), { recursive: true })
  await fsp.mkdir(path.join(root, 'scripts'), { recursive: true })
  await fsp.writeFile(path.join(root, 'scripts', 'metrics_health.py'), '# marker\n', 'utf8')
  return root
})()

after(async () => {
  for (const dir of tempDirs) await fsp.rm(dir, { recursive: true, force: true })
})

// ---- YAML 子集解析（CONTRACT §2.2） -----------------------------------------

test('YAML：块映射/序列、行内流集合（含跨行）、引号转义、块标量、注释、BOM', () => {
  const text = [
    '\uFEFFsession_id: "2026-01-01-demo"',
    'status: in_progress   # 行尾注释',
    'trace:',
    '  - {role: user, step: 1,',
    '     content: "第一行\\n第二行",',
    '     evidence: {inline: "x # 不是注释", files: ["a/b.log"], sources: ["https://x"]}}',
    '  - role: agent',
    '    step: 2',
    '    output: |-',
    '      # 这一行在块标量正文里，是内容',
    '      retCode=0x31 [vector core exception]',
    "    note: '单引号里的 # 保留'",
  ].join('\n')
  const stats = {}
  const doc = __test.parseYaml(text, stats)
  assert.equal(doc.session_id, '2026-01-01-demo')
  assert.equal(doc.status, 'in_progress')
  assert.equal(__test.anomalyOf(stats), null)
  assert.equal(doc.trace.length, 2)
  assert.equal(doc.trace[0].role, 'user')
  assert.equal(doc.trace[0].step, '1')
  assert.equal(doc.trace[0].content, '第一行\n第二行')
  // 行内流集合里的嵌套集合要解析成结构，而不是字符串
  assert.deepEqual(doc.trace[0].evidence.files, ['a/b.log'])
  assert.deepEqual(doc.trace[0].evidence.sources, ['https://x'])
  assert.equal(doc.trace[0].evidence.inline, 'x # 不是注释')
  assert.equal(doc.trace[1].output, '# 这一行在块标量正文里，是内容\nretCode=0x31 [vector core exception]')
  assert.equal(doc.trace[1].note, '单引号里的 # 保留')
})

test('YAML：双引号转义与 PyYAML 同口径（反斜杠成对解，不把 \\\\n 当换行）', () => {
  const doc = __test.parseYaml('a: "\\\\bhang\\\\b"\nb: "line1\\nline2"\nc: "quote \\"x\\""\n')
  assert.equal(doc.a, '\\bhang\\b')
  assert.equal(doc.b, 'line1\nline2')
  assert.equal(doc.c, 'quote "x"')
})

test('YAML：空文件/坏文件不抛错，未闭合的行内集合如实记进 stats', () => {
  assert.deepEqual(__test.parseYaml('', {}), {})
  assert.deepEqual(__test.parseYaml('   \n\n', {}), {})
  const stats = {}
  const doc = __test.parseYaml('trace: [a, b\n', stats)
  assert.notEqual(__test.anomalyOf(stats), null)
  assert.equal(__test.isUsableDoc(doc, stats), false)
})

test('YAML：块标量 >- 折叠、数字/布尔/null 原样', () => {
  const doc = __test.parseYaml([
    'output: >-',
    '  第一段',
    '  第二段',
    '',
    '  第三段',
    'n_cases: 83',
    'ok: true',
    'nothing: null',
  ].join('\n'))
  // 移植版解析器在收行表时丢弃空行（与上游 panel-host.js 同语义）：折叠标量的空行不保留分段
  assert.equal(doc.output, '第一段 第二段 第三段')
  assert.equal(doc.n_cases, '83')
  assert.equal(doc.ok, 'true')
  assert.equal(doc.nothing, 'null')
})

// ---- fixtures：list（CONTRACT §2.3） ---------------------------------------

test('list：三个会话与契约样例逐字段对齐（version 令牌随文件系统变化，单独断言）', async () => {
  const host = makeHost()
  const result = await host.list({ sessionId: 'sess-1' })
  const fixture = JSON.parse(await fsp.readFile(path.join(FIXTURES, 'list-sample.json'), 'utf8'))

  assert.equal(result.repo.detected, true)
  assert.equal(result.repo.path, FIXTURE_REPO)
  assert.deepEqual(result.warnings, [])
  assert.match(result.generatedAt, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/)
  assert.equal(result.sessions.length, fixture.sessions.length)

  for (let i = 0; i < fixture.sessions.length; i++) {
    const ours = result.sessions[i]
    const want = fixture.sessions[i]
    assert.deepEqual(Object.keys(ours).sort(), Object.keys(want).sort(), 'SessionSummary 字段集合')
    for (const key of Object.keys(want)) {
      if (key === 'version') {
        // 样例的 version 是固定占位 null；真值来自 fs.listDir 的版本令牌，每次检出都不同
        assert.equal(ours.version === null || typeof ours.version === 'string', true)
        continue
      }
      assert.deepEqual(ours[key], want[key], key + '（会话 ' + i + '）')
    }
  }

  // 三个会话的关键字段逐项钉住（不只靠样例，避免样例与实现同源时断言失效）
  const byId = new Map(result.sessions.map((session) => [session.id, session]))
  assert.deepEqual(result.sessions.map((s) => s.id), [
    '2026-01-04-demo-a2-resume-report',
    '2026-01-03-demo-a3-kv-load-stall',
    '2026-01-02-demo-a3-w8a8-garble',
  ], '按 updatedAt 倒序')
  assert.equal(byId.get('2026-01-02-demo-a3-w8a8-garble').status, 'resolved')
  assert.equal(byId.get('2026-01-02-demo-a3-w8a8-garble').feedback.outcome, 'resolved')
  assert.deepEqual(byId.get('2026-01-02-demo-a3-w8a8-garble').sedimented, { state: 'knowledge', caseId: 'VLLM-ASC-9001' })
  assert.deepEqual(byId.get('2026-01-02-demo-a3-w8a8-garble').excludedCases, ['VLLM-ASC-9002', 'VLLM-ASC-9003'])
  assert.equal(byId.get('2026-01-03-demo-a3-kv-load-stall').eventCount, 12)
  assert.equal(byId.get('2026-01-03-demo-a3-kv-load-stall').stepCount, 5)
  assert.equal(byId.get('2026-01-03-demo-a3-kv-load-stall').hasConclusion, true)
  assert.equal(byId.get('2026-01-04-demo-a2-resume-report').stepCount, 12)
  assert.deepEqual(byId.get('2026-01-04-demo-a2-resume-report').feedback, { case: 'VLLM-ASC-9002', outcome: 'pending' })
  assert.deepEqual(byId.get('2026-01-04-demo-a2-resume-report').sedimented, { state: 'inbox', caseId: 'VLLM-ASC-9002' })
})

test('list：按 listDir version 缓存摘要，版本变化才重读那一份', async () => {
  const fs = makeRealFs()
  const host = makeHost({ fs })
  await host.list()
  assert.equal(fs.counters.readText, 3)
  fs.counters.readText = 0
  const second = await host.list()
  assert.equal(second.sessions.length, 3)
  assert.equal(fs.counters.readText, 0, '第二次列表命中缓存，不再读文件')

  // 只让一个文件的版本令牌变化 → 只重读它
  fs.versionOverride.set('2026-01-03-demo-a3-kv-load-stall.yaml', 'v-changed')
  const third = await host.list()
  assert.equal(third.sessions.length, 3)
  assert.equal(fs.counters.readText, 1)
})

test('list：traces 目录不存在 → 空列表 + 一条可读 warning；无会话 → detected:false；无 fs 退化', async () => {
  const repo = await makeTempRepo({ 'scripts/metrics_health.py': '# marker\n' })
  const hostMissingTraces = makeHost({ cwds: [repo] })
  const result = await hostMissingTraces.list()
  assert.equal(result.repo.detected, true)
  assert.equal(result.repo.path, repo)
  assert.deepEqual(result.sessions, [])
  assert.deepEqual(result.warnings, ['没有 traces 目录：先跑一次诊断'])

  const emptySessions = { async list() { return [] }, async get() { return undefined } }
  const hostNoCwd = makeHost({ sessions: emptySessions })
  const noCwd = await hostNoCwd.list()
  assert.equal(noCwd.repo.detected, false)
  assert.equal(noCwd.repo.path, null)
  assert.deepEqual(noCwd.sessions, [])
  assert.equal(noCwd.warnings.length, 1)
  assert.match(noCwd.warnings[0], /工作目录|sessions/)

  const hostNoFs = __test.createHost(makeCtx({ sessions: makeSessions([repo]) }))
  const noFs = await hostNoFs.list()
  assert.deepEqual(noFs.sessions, [])
  assert.match(noFs.warnings[0], /fs 服务不可用/)

  // 没有仓库标记、但 traces/ 可读：按 traces 所在目录处理并给 warning
  const bareRepo = await makeTempRepo({ 'traces/x.yaml': 'session_id: "x"\n' })
  const bare = await makeHost({ cwds: [bareRepo] }).list()
  assert.equal(bare.repo.detected, true)
  assert.equal(bare.repo.path, bareRepo)
  assert.match(bare.warnings[0], /metrics_health\.py/)
  assert.equal(bare.sessions.length, 1)
})

test('list：session cwd 是仓库子目录时向上找到仓库根（最多 6 级）', async () => {
  const repo = await makeTempRepo({
    'scripts/metrics_health.py': '# marker\n',
    'traces/2026-01-03-up.yaml': 'session_id: "2026-01-03-up"\ntrace:\n  - {role: user, step: 1}\n',
  })
  const nested = path.join(repo, 'sub', 'dir')
  await fsp.mkdir(nested, { recursive: true })

  const fromChild = await makeHost({ cwds: [nested] }).list()
  assert.equal(fromChild.repo.detected, true)
  assert.equal(fromChild.repo.path, repo)
  assert.equal(fromChild.sessions.length, 1)

  // 超过 6 级父目录就不找了（构造一个标记在 8 级以外的树）
  const deepRoot = await makeTempRepo({ 'scripts/metrics_health.py': '# marker\n' })
  const deep = path.join(deepRoot, 'a', 'b', 'c', 'd', 'e', 'f', 'g')
  await fsp.mkdir(deep, { recursive: true })
  const tooDeep = await makeHost({ cwds: [deep] }).list()
  assert.equal(tooDeep.repo.detected, false)
  assert.deepEqual(tooDeep.warnings, ['没有 traces 目录：先跑一次诊断'])
})

test('parentPath / ancestorCandidates：纯字符串取父目录，向上最多 6 级', () => {
  assert.equal(__test.parentPath('/a/b/c'), '/a/b')
  assert.equal(__test.parentPath('/a/b/c/'), '/a/b')
  assert.equal(__test.parentPath('/a'), '/')
  assert.equal(__test.parentPath('/'), null)
  assert.equal(__test.parentPath('a/b'), 'a')
  assert.deepEqual(__test.ancestorCandidates('/r/sub/dir'), ['/r/sub/dir', '/r/sub', '/r', '/'])
  const deep = __test.ancestorCandidates('/r/a/b/c/d/e/f/g')
  assert.equal(deep.length, 1 + __test.MAX_ANCESTOR_DEPTH)
  assert.equal(deep[deep.length - 1], '/r/a')
})

test('list：坏 YAML 单文件被跳过并记文件名，不拖垮其余会话；不合规文件名不进列表', async () => {
  const good = [
    'session_id: "2026-01-02-good"',
    'status: in_progress',
    'created_at: "2026-01-02T10:00:00+08:00"',
    'updated_at: "2026-01-02T10:05:00+08:00"',
    'trace:',
    '  - {role: user, step: 1, content: "现场"}',
    '  - {role: agent, step: 2, action: miss, output: "未覆盖"}',
  ].join('\n')
  const repo = await makeTempRepo({
    'scripts/metrics_health.py': '# marker\n',
    'traces/2026-01-02-good.yaml': good,
    'traces/2026-01-01-broken.yaml': 'trace: [unclosed\n',
    'traces/not-a-trace.txt': 'ignored\n',
    'traces/bad name.yaml': good,
  })
  const host = makeHost({ cwds: [repo] })
  const result = await host.list()
  assert.equal(result.sessions.length, 1)
  assert.equal(result.sessions[0].id, '2026-01-02-good')
  assert.equal(result.sessions[0].eventCount, 2)
  assert.equal(result.sessions[0].stepCount, 2)
  assert.equal(result.sessions[0].hasConclusion, true)
  assert.ok(result.warnings.includes('解析失败，已跳过: 2026-01-01-broken.yaml'))
  assert.equal(result.warnings.some((w) => w.includes('bad name.yaml')), false, '不合规文件名不报错也不列出')

  // 读失败的文件同样跳过（不拖垮列表）
  const fs = makeRealFs({ readErrors: new Set(['2026-01-02-good.yaml']) })
  const readFail = await makeHost({ cwds: [repo], fs }).list()
  assert.deepEqual(readFail.sessions, [])
  assert.ok(readFail.warnings.some((w) => w.includes('2026-01-02-good.yaml')))

  // 同一个坏文件走 detail：如实报错，而不是给一份空事件假装成功
  await assert.rejects(
    () => makeHost({ cwds: [repo] }).detail({ file: '2026-01-01-broken.yaml' }),
    (error) => error.code === 'internal' && /解析失败/.test(error.message),
  )
})

// ---- fixtures：detail（CONTRACT §2.4） --------------------------------------

const DETAIL_CASES = [
  '2026-01-02-demo-a3-w8a8-garble',
  '2026-01-03-demo-a3-kv-load-stall',
  '2026-01-04-demo-a2-resume-report',
]

// 样例由 host 自己归一化生成，逐字比较会与实现同源；这里另钉一组手写期望，
// 覆盖 insights 规则 1-9 在合成数据上的实际输出（含风险、续接、欠回报）。
const EXPECTED_INSIGHTS = {
  '2026-01-02-demo-a3-w8a8-garble': {
    ids: ['conclusion', 'funnel', 'parallel', 'evidence', 'evidence-missing', 'effort', 'time'],
    texts: {
      funnel: '核验 7 个 case，排除 2 个，命中 1 个',
      parallel: '第 4 步一次展开 7 个动作',
      evidence: '内联证据 151 字，2 个文件',
      'evidence-missing': '缺首轮乱码的完整 token id 序列、模型权重 hash、CANN 版本',
      effort: '1 次先验查照',
      time: '从 2026-01-02 09:12 到 2026-01-02 11:48，跨度 2 小时 36 分',
    },
  },
  '2026-01-03-demo-a3-kv-load-stall': {
    ids: ['conclusion', 'funnel', 'parallel', 'evidence', 'evidence-missing', 'effort', 'time', 'feedback', 'sediment', 'risk'],
    texts: {
      funnel: '核验 6 个 case，排除 2 个，无命中',
      parallel: '第 4 步一次展开 7 个动作',
      evidence: '内联证据 193 字，1 个文件',
      effort: '5 次工具调用，1 段源码分析',
      time: '从 2026-01-03 14:05 到 2026-01-03 16:22，跨度 2 小时 17 分',
      risk: '输出含「先停」「数据丢失」（第 5 步 miss）',
    },
  },
  '2026-01-04-demo-a2-resume-report': {
    ids: ['conclusion', 'funnel', 'evidence', 'evidence-missing', 'effort', 'time', 'feedback', 'resume'],
    texts: {
      funnel: '核验 1 个 case，排除 0 个，命中 1 个',
      evidence: '内联证据 130 字，2 个文件',
      effort: '3 次工具调用，1 段源码分析，1 次先验查照',
      time: '从 2026-01-04 09:10 到 2026-01-05 10:35，跨度 1 天 1 小时',
      resume: '诊断被打断后第 11 步续接',
    },
  },
}

// 三份合成 trace 里命中的 case 与结论落点
const EXPECTED_CONCLUSION = {
  '2026-01-02-demo-a3-w8a8-garble': { index: 13, action: 'output', caseId: 'REF-QUANT-9001', confidence: /（confidence 0\.62）$/ },
  '2026-01-03-demo-a3-kv-load-stall': { index: 11, action: 'miss', caseId: null, confidence: null },
  '2026-01-04-demo-a2-resume-report': { index: 9, action: 'attribution', caseId: 'REF-CACHE-0004', confidence: /（confidence 0\.6）$/ },
}

for (const name of DETAIL_CASES) {
  test('detail：' + name + ' 与契约样例对齐（事件逐字段、insights 文案、证据文件）', async () => {
    const host = makeHost()
    const detail = await host.detail({ sessionId: 'sess-1', file: name + '.yaml' })
    const fixture = JSON.parse(await fsp.readFile(path.join(FIXTURES, 'detail-' + name + '.json'), 'utf8'))

    assert.deepEqual(Object.keys(detail).sort(), Object.keys(fixture).sort())
    assert.deepEqual(detail.warnings, [])
    assert.equal(detail.file, fixture.file)
    assert.equal(detail.summary, fixture.summary)
    assert.equal(detail.lastAction, fixture.lastAction)
    assert.equal(detail.activeCase, fixture.activeCase)
    assert.equal(detail.conclusionIndex, fixture.conclusionIndex)
    assert.deepEqual(detail.feedback, fixture.feedback)
    assert.deepEqual(detail.sedimented, fixture.sedimented)
    assert.deepEqual(detail.evidenceFiles, fixture.evidenceFiles)
    for (const key of ['status', 'summary', 'createdAt', 'updatedAt', 'framework', 'platform', 'category',
      'resolvedAt', 'currentStep', 'lastAction', 'activeCase', 'sedimented', 'feedback', 'eventCount',
      'stepCount', 'hasConclusion', 'sizeBytes']) {
      assert.deepEqual(detail.session[key], fixture.session[key], 'session.' + key)
    }

    // 事件：客户端不再二次解析 YAML，所以事件必须逐字段与样例一致
    assert.deepEqual(detail.events, fixture.events)

    // insights：与样例逐字一致，并额外钉住手写期望
    assert.deepEqual(detail.insights, fixture.insights)
    const expected = EXPECTED_INSIGHTS[name]
    assert.deepEqual(detail.insights.map((x) => x.id), expected.ids, 'insight id 序列')
    const oursById = new Map(detail.insights.map((x) => [x.id, x]))
    for (const [id, text] of Object.entries(expected.texts)) {
      assert.equal(oursById.get(id).text, text, id + '.text')
    }

    // 结论落点与 case：三份合成 trace 里分别是输出、未覆盖、归因
    const conclusion = EXPECTED_CONCLUSION[name]
    assert.equal(detail.conclusionIndex, conclusion.index)
    assert.equal(detail.events[conclusion.index].action, conclusion.action)
    if (conclusion.caseId) {
      assert.ok(oursById.get('conclusion').text.startsWith(conclusion.caseId + '：'))
      assert.match(oursById.get('conclusion').text, conclusion.confidence)
    } else {
      assert.equal(oursById.get('conclusion').tone, 'warn')
      assert.equal(oursById.get('conclusion').title, '结论 · 知识库未覆盖')
    }
  })
}

test('detail：结论落点 = 最后一条 hit/miss/output/attribution；显式 conclusion 标记优先', async () => {
  const host = makeHost()
  const miss = await host.detail({ file: '2026-01-03-demo-a3-kv-load-stall.yaml' })
  assert.equal(miss.conclusionIndex, 11)
  assert.equal(miss.events[miss.conclusionIndex].action, 'miss')

  const resume = await host.detail({ file: '2026-01-04-demo-a2-resume-report.yaml' })
  assert.equal(resume.conclusionIndex, 9)
  assert.equal(resume.events[resume.conclusionIndex].action, 'attribution')

  const trace = [
    { role: 'user', step: 1, content: '现场' },
    { role: 'agent', step: 2, action: 'hit', output: 'a' },
    { role: 'agent', step: 3, action: 'feedback', output: 'b', conclusion: true },
  ]
  assert.equal(__test.conclusionIndexOf(trace, __test.buildEvents(trace)), 2)
  assert.equal(__test.conclusionIndexOf([], []), null)
})

test('detail：file 参数只允许 traces/ 下的 .yaml 文件名（路径穿越被拒）', async () => {
  const fs = makeRealFs()
  const host = makeHost({ fs })
  const readsBefore = fs.counters.readText
  const bad = [
    '../2026-01-03-demo-a3-kv-load-stall.yaml',
    'traces/2026-01-03-demo-a3-kv-load-stall.yaml',
    '/etc/passwd.yaml',
    'a/../b.yaml',
    'x.txt',
    'x.yaml/../y',
    '',
    '..',
  ]
  for (const file of bad) {
    await assert.rejects(() => host.detail({ file }), (error) => error.code === 'bad-request', '应拒: ' + JSON.stringify(file))
  }
  assert.equal(fs.counters.readText, readsBefore, '非法 file 不触发读文件')
  await assert.rejects(() => host.detail({ file: 'nope-123.yaml' }), (error) => error.code === 'not-found')
})

test('detail：没有仓库时返回空 detail + warning，而不是抛错', async () => {
  const emptySessions = { async list() { return [] }, async get() { return undefined } }
  const detail = await makeHost({ sessions: emptySessions }).detail({ file: '2026-01-01-x.yaml' })
  assert.equal(detail.session, null)
  assert.deepEqual(detail.events, [])
  assert.deepEqual(detail.evidenceFiles, [])
  assert.equal(detail.warnings.length, 1)
})

test('detail：证据文件缺失时名字仍列出、bytes=null，并给 warning', async () => {
  const repo = await makeTempRepo({
    'scripts/metrics_health.py': '# marker\n',
    'traces/t.yaml': [
      'session_id: "t"',
      'trace:',
      '  - {role: user, step: 1, content: "x", evidence: {files: ["traces/evidence/t/a.log"]}}',
    ].join('\n'),
  })
  const detail = await makeHost({ cwds: [repo] }).detail({ file: 't.yaml' })
  assert.deepEqual(detail.evidenceFiles, [{ name: 'a.log', bytes: null }])
  assert.ok(detail.warnings.some((w) => w.includes('traces/evidence/t/a.log')))
})

// ---- 归一化边界（CONTRACT §2.4 事件字段与截断） -----------------------------

test('事件归一化：截断上限、未知字段进 fields、证据缺省值', () => {
  const long = '字'.repeat(9000)
  const trace = [{
    role: 'user',
    step: 1,
    content: long,
    evidence: { inline: '证'.repeat(5000), files: ['a/b.log'], missing: '' },
  }, {
    role: 'agent',
    step: 2,
    action: 'source_analysis',
    output: long,
    reason: '理'.repeat(9000),
    tool_calls: ['x'.repeat(500)],
    custom_key: '自'.repeat(2000),
    custom_list: ['a', 1, true],
    unknown_bool: true,
    sources: ['https://a'],
    evidence: { sources: ['https://b'] },
  }]
  const events = __test.buildEvents(trace)
  assert.equal(events.length, 2)
  assert.equal(events[0].content.length, 8000)
  assert.equal(events[0].chars.content, 9000)
  assert.equal(events[0].evidence.inline.length, 4000)
  assert.equal(events[0].evidence.inlineChars, 5000)
  assert.deepEqual(events[0].evidence.files, ['a/b.log'])
  assert.equal(events[0].evidence.missing, '')
  assert.equal(events[1].output.length, 8000)
  assert.equal(events[1].chars.output, 9000)
  assert.equal(events[1].chars.reason, 9000)
  assert.equal(events[1].toolCalls[0].length, 400)
  assert.equal(events[1].fields.custom_key.length, 1200)
  assert.deepEqual(events[1].fields.custom_list, ['a', '1', 'true'])
  assert.equal(events[1].fields.unknown_bool, 'true')
  // 顶层 sources 与 evidence.sources 合并去重
  assert.deepEqual(events[1].sources, ['https://a', 'https://b'])
  // 未知 action 原值保留；verdict 恒有六项 + attribution 用 verdict 原值
  const unknown = __test.buildEvents([{ role: 'agent', step: 3, action: 'brand_new_action' }])[0]
  assert.equal(unknown.action, 'brand_new_action')
  assert.deepEqual(Object.keys(unknown.verdict), ['primary', 'fallback', 'marked', 'result', 'confidence', 'check', 'verdict'])
})

test('summary：stepCount / eventCount / hasConclusion 与排除单归一化', () => {
  const doc = __test.parseYaml([
    'session_id: "demo"',
    'status: in_progress',
    'excluded_cases: [{id: VLLM-ASC-1, reason: "版本不符"}, VLLM-ASC-2]',
    'active_case: "null"',
    'resolved_at: ""',
    'feedback:',
    '  case: ""',
    '  outcome: pending',
    'sedimented: {state: none, case_id: ""}',
    'trace:',
    '  - {role: user, step: 1}',
    '  - {role: agent, step: 2, action: quickly_check}',
    '  - {role: agent, step: 2, action: foo}',
  ].join('\n'))
  const summary = __test.summarize(doc, 'demo.yaml', { sizeBytes: 10, version: '7' })
  assert.equal(summary.id, 'demo')
  assert.equal(summary.activeCase, null)
  assert.equal(summary.resolvedAt, null)
  assert.deepEqual(summary.excludedCases, ['VLLM-ASC-1', 'VLLM-ASC-2'])
  assert.deepEqual(summary.sedimented, { state: 'none', caseId: null })
  assert.deepEqual(summary.feedback, { case: null, outcome: 'pending' })
  assert.equal(summary.eventCount, 3)
  assert.equal(summary.stepCount, 2)
  assert.equal(summary.hasConclusion, false)
  assert.equal(summary.sizeBytes, 10)
  assert.equal(summary.version, '7')
})

test('excludedCases：块写法 `- id: X` 的单元素字典归一成 id', () => {
  const doc = __test.parseYaml([
    'session_id: "demo-block"',
    'excluded_cases:',
    '  - id: VLLM-ASC-9010',
    '    reason: "garble 形态匹配，但 compat <=0.20.2 版本不符；软排除"',
    '  - VLLM-ASC-2',
    'trace:',
    '  - {role: user, step: 1}',
  ].join('\n'))
  const summary = __test.summarize(doc, 'demo-block.yaml', {})
  // 单元素字典取 id，不把整段 dict 拼进列表；纯字符串项原样保留
  assert.deepEqual(summary.excludedCases, ['VLLM-ASC-9010', 'VLLM-ASC-2'])
  assert.equal(summary.excludedCases.length, 2)
})

// ---- insights 规则 1-9（CONTRACT §2.4） ------------------------------------

const BASE_SUMMARY = {
  createdAt: null,
  updatedAt: null,
  activeCase: null,
  feedback: { case: null, outcome: null },
  sedimented: { state: null, caseId: null },
  status: 'in_progress',
}

function insightsOf(trace, summaryPatch = {}) {
  const summary = Object.assign({}, BASE_SUMMARY, summaryPatch)
  const events = __test.buildEvents(trace)
  const byId = new Map(__test.buildInsights({ summary, events }).map((x) => [x.id, x]))
  return byId
}

test('insights 规则 1：命中 / 未覆盖 / 仍在进行（命中带 confidence）', () => {
  const hit = insightsOf([
    { role: 'user', step: 1, content: '现场' },
    { role: 'agent', step: 2, action: 'hit', case: 'VLLM-ASC-9005', confidence: 0.45, output: '根因确认'.repeat(40) },
  ])
  assert.equal(hit.get('conclusion').tone, 'good')
  assert.equal(hit.get('conclusion').title, '结论 · 命中 case')
  assert.ok(hit.get('conclusion').text.startsWith('VLLM-ASC-9005：'))
  assert.match(hit.get('conclusion').text, /（confidence 0\.45）$/)
  // case 前缀 + 120 字输出 + confidence 后缀
  assert.ok(hit.get('conclusion').text.length <= 147 + 20)

  // 没有写 confidence 时不编造后缀
  const noConfidence = insightsOf([{ role: 'agent', step: 2, action: 'hit', case: 'X', output: 'y' }])
  assert.equal(noConfidence.get('conclusion').text, 'X：y')

  const miss = insightsOf([{ role: 'agent', step: 2, action: 'miss', output: '知识库未覆盖'.repeat(30) }])
  assert.equal(miss.get('conclusion').tone, 'warn')
  assert.equal(miss.get('conclusion').title, '结论 · 知识库未覆盖')
  assert.ok(miss.get('conclusion').text.length <= 140)

  const pending = insightsOf([{ role: 'user', step: 1, content: '现场' }])
  assert.equal(pending.get('conclusion').title, '结论 · 仍在进行')
})

test('insights 规则 2-3：候选漏斗与并行展开（数据不足跳过）', () => {
  const byId = insightsOf([
    { role: 'agent', step: 4, action: 'quickly_check', case: 'A', marked: 'excluded' },
    { role: 'agent', step: 4, action: 'quickly_check', case: 'B' },
    { role: 'agent', step: 4, action: 'hit', case: 'B', output: 'x' },
    { role: 'agent', step: 4, action: 'tier3', output: 'y' },
    { role: 'agent', step: 5, action: 'source_analysis', output: 'z' },
  ])
  assert.equal(byId.get('funnel').text, '核验 2 个 case，排除 1 个，命中 1 个')
  assert.equal(byId.get('parallel').text, '第 4 步一次展开 4 个动作')
  const single = insightsOf([{ role: 'agent', step: 1, action: 'triage', output: 'x' }])
  assert.equal(single.has('funnel'), false)
  assert.equal(single.has('parallel'), false)
})

test('insights 规则 4-5：证据体量、缺证据、工作量（含 reference_lookup）', () => {
  const byId = insightsOf([
    {
      role: 'user',
      step: 1,
      content: 'x',
      evidence: { inline: '证'.repeat(100), files: ['a.log'], missing: '缺 device plog' },
    },
    { role: 'agent', step: 2, action: 'source_analysis', tool_calls: ['call-1', 'call-2'] },
    { role: 'agent', step: 3, action: 'reference_lookup', ref_id: 'ref-1' },
  ])
  assert.equal(byId.get('evidence').text, '内联证据 100 字，1 个文件')
  assert.equal(byId.get('evidence-missing').tone, 'warn')
  assert.match(byId.get('evidence-missing').text, /缺 device plog/)
  assert.equal(byId.get('effort').text, '2 次工具调用，1 段源码分析，1 次先验查照')
  const noEvidence = insightsOf([{ role: 'agent', step: 1, action: 'triage', output: 'x' }])
  assert.equal(noEvidence.has('evidence'), false)
  assert.equal(noEvidence.has('evidence-missing'), false)
})

test('insights 规则 6-7：时间跨度与闭环（欠回报 / 尚未沉淀）', () => {
  const same = insightsOf([], {
    createdAt: '2026-01-01T10:00:00+08:00',
    updatedAt: '2026-01-01T10:00:00+08:00',
    feedback: { case: 'X', outcome: 'pending' },
    sedimented: { state: 'none', caseId: null },
  })
  assert.equal(same.get('time').text, '创建与最近更新同一时刻（2026-01-01 10:00），跨度不到 1 分钟')
  assert.equal(same.get('feedback').tone, 'warn')
  assert.equal(same.get('sediment').title, '尚未沉淀')

  const span = insightsOf([], {
    createdAt: '2026-01-01T10:00:00+08:00',
    updatedAt: '2026-01-02T13:07:00+08:00',
  })
  assert.equal(span.get('time').text, '从 2026-01-01 10:00 到 2026-01-02 13:07，跨度 1 天 3 小时')

  const noTime = insightsOf([], {
    feedback: { case: null, outcome: 'resolved' },
    sedimented: { state: 'knowledge', caseId: 'X' },
  })
  assert.equal(noTime.has('time'), false)
  assert.equal(noTime.has('feedback'), false)
  assert.equal(noTime.has('sediment'), false)
})

test('insights 规则 8：续接', () => {
  const byId = insightsOf([
    { role: 'agent', step: 7, action: 'resume', output: '续接' },
  ])
  assert.equal(byId.get('resume').text, '诊断被打断后第 7 步续接')
  const clean = insightsOf([{ role: 'agent', step: 1, action: 'hit', output: '普通结论' }])
  assert.equal(clean.has('resume'), false)
})

test('insights 规则 9：风险只认指定形态，否定句不误报', () => {
  const riskOf = (output) => insightsOf([{ role: 'agent', step: 6, action: 'miss', output }]).get('risk')

  // 真风险：四种形态都命中
  const byWord = riskOf('高危：先停训练并保留现场')
  assert.equal(byWord.tone, 'risk')
  assert.match(byWord.text, /先停/)
  assert.match(riskOf('severity=data-loss-risk（vendor kernel 缺陷）').text, /data-loss-risk/)
  assert.match(riskOf('severity: "data-loss"，需停训练').text, /severity: "data-loss/)
  assert.match(riskOf('存在数据风险，建议保留现场').text, /数据风险/)
  assert.match(riskOf('可能造成数据丢失').text, /数据丢失/)

  // 否定句不产风险条（含本次要修的实际形态「非 data-loss」）
  assert.equal(riskOf('severity=service-affecting（非 data-loss）、建议沉淀新 case'), undefined)
  assert.equal(riskOf('并非 data-loss-risk，只是性能退化'), undefined)
  assert.equal(riskOf('不是数据风险，可继续观察'), undefined)
  assert.equal(riskOf('无数据风险'), undefined)
  assert.equal(riskOf('not data-loss-risk'), undefined)

  // 单独的 data-loss 不再是触发形态（必须是 data-loss-risk，或 severity 紧邻 data-loss 的写法）
  assert.equal(riskOf('本次不是 data-loss 场景，data-loss 风险另行评估'), undefined)
  assert.equal(riskOf('本次 data-loss 风险另行评估'), undefined)

  // 普通结论不产风险条
  assert.equal(insightsOf([{ role: 'agent', step: 1, action: 'hit', output: '普通结论' }]).has('risk'), false)
})

// ---- RPC 路由（CONTRACT §2 末尾） ------------------------------------------

function makeRequest({ method = 'POST', url = CHANNEL + '/list', payload, body, chunks } = {}) {
  const list = chunks || [Buffer.from(JSON.stringify(
    body === undefined ? { rpcId: 'r1', payload: payload || {} } : body,
  ))]
  return {
    method,
    url,
    async *[Symbol.asyncIterator]() {
      for (const chunk of list) yield chunk
    },
  }
}

function makeResponse() {
  const state = { status: null, headers: {}, body: '' }
  return {
    state,
    setHeader(name, value) {
      state.headers[name.toLowerCase()] = value
    },
    writeHead(status, headers) {
      state.status = status
      for (const [name, value] of Object.entries(headers || {})) state.headers[name.toLowerCase()] = value
    },
    end(body) {
      state.body = body === undefined ? '' : String(body)
    },
    json() {
      return JSON.parse(state.body)
    },
  }
}

async function callRoute(handler, request) {
  const response = makeResponse()
  await handler(request, response)
  return response
}

function applyForRoute(services) {
  const all = Object.assign({}, services)
  all.webServer = {
    register(options) {
      all.__route = options
      return () => {}
    },
  }
  const disposer = apply(makeCtx(all))
  assert.equal(typeof disposer, 'function')
  assert.ok(all.__route, 'webServer.register 被调用')
  assert.equal(all.__route.kind, 'prefix')
  assert.equal(all.__route.path, CHANNEL)
  return all.__route.handler
}

test('RPC：list/detail 正常返回 {type:server-response, rpcId, result:{ok,value}}', async () => {
  const handler = applyForRoute({
    fs: makeRealFs(),
    sessions: makeSessions([FIXTURE_REPO]),
    connection: { requestRejection: () => undefined },
  })

  const listResponse = await callRoute(handler, makeRequest({ payload: { sessionId: 'sess-1' } }))
  assert.equal(listResponse.state.status, 200)
  assert.match(listResponse.state.headers['content-type'], /application\/json/)
  const listBody = listResponse.json()
  assert.equal(listBody.type, 'server-response')
  assert.equal(listBody.rpcId, 'r1')
  assert.equal(listBody.result.ok, true)
  assert.equal(listBody.result.value.sessions.length, 3)

  const detailResponse = await callRoute(handler, makeRequest({
    url: CHANNEL + '/detail',
    payload: { file: '2026-01-02-demo-a3-w8a8-garble.yaml' },
  }))
  const detailBody = detailResponse.json()
  assert.equal(detailBody.result.ok, true)
  assert.equal(detailBody.result.value.events.length, 15)
  assert.equal(detailBody.result.value.conclusionIndex, 13)

  // 端点也接受 body.method（前缀匹配方式变了也不丢端点）
  const fallback = await callRoute(handler, makeRequest({ url: CHANNEL, body: { rpcId: 'r2', method: 'list', payload: {} } }))
  assert.equal(fallback.json().result.ok, true)
  assert.equal(fallback.json().rpcId, 'r2')

  // 非法 file → ok:false, code bad-request
  const bad = await callRoute(handler, makeRequest({ url: CHANNEL + '/detail', payload: { file: '../x.yaml' } }))
  assert.equal(bad.state.status, 200)
  assert.equal(bad.json().result.ok, false)
  assert.equal(bad.json().result.error.code, 'bad-request')

  // 未知端点
  const unknown = await callRoute(handler, makeRequest({ url: CHANNEL + '/nope' }))
  assert.equal(unknown.json().result.ok, false)
  assert.equal(unknown.json().result.error.code, 'not-found')
})

test('RPC：方法/鉴权/体积/JSON 错误分别给 405/401/413/400', async () => {
  const rejectHandler = applyForRoute({
    fs: makeRealFs(),
    sessions: makeSessions([FIXTURE_REPO]),
    connection: { requestRejection: () => 401 },
  })
  const unauthorized = await callRoute(rejectHandler, makeRequest({}))
  assert.equal(unauthorized.state.status, 401)
  assert.equal(unauthorized.state.body, 'unauthorized')

  const handler = applyForRoute({
    fs: makeRealFs(),
    sessions: makeSessions([FIXTURE_REPO]),
    connection: { requestRejection: () => undefined },
  })
  const notAllowed = await callRoute(handler, makeRequest({ method: 'GET' }))
  assert.equal(notAllowed.state.status, 405)
  assert.equal(notAllowed.state.headers.allow, 'POST')

  const tooLarge = await callRoute(handler, makeRequest({ chunks: [Buffer.alloc(700 * 1024), Buffer.alloc(700 * 1024)] }))
  assert.equal(tooLarge.state.status, 413)

  const notJson = await callRoute(handler, makeRequest({ chunks: [Buffer.from('not json')] }))
  assert.equal(notJson.state.status, 400)
})

test('RPC：apply 可加载可卸载；没有 inject 时只打日志不抛', () => {
  const disposeNoInject = apply({ get: () => undefined })
  assert.equal(typeof disposeNoInject, 'function')
  disposeNoInject()

  const registered = []
  const ctx = {
    get: (name) => (name === 'fs' ? makeRealFs() : name === 'sessions' ? makeSessions([]) : undefined),
    inject(names, callback) {
      callback({
        get: (name) => (name === 'webServer' ? { register: (options) => { registered.push(options); return () => {} } } : undefined),
        effect: (fn) => fn(),
        webServer: { register: (options) => { registered.push(options); return () => {} } },
      })
    },
  }
  const dispose = apply(ctx)
  assert.equal(registered.length, 1)
  dispose()
})

test('导出形态：host 是 ESM 单文件，apply 是函数，__test 暴露纯函数', async () => {
  assert.equal(typeof apply, 'function')
  assert.equal(typeof __test.parseYaml, 'function')
  assert.equal(typeof __test.createHost, 'function')
  assert.equal(typeof __test.buildInsights, 'function')
  assert.equal(__test.TRACE_FILE_RE.test('a-b_c.1.yaml'), true)
  assert.equal(__test.TRACE_FILE_RE.test('../a.yaml'), false)
  assert.equal(__test.TRACE_FILE_RE.test('a.yaml/../b'), false)
})
