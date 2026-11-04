// 画布引擎的离线自测：用 node:vm 单独求值 client-src/10-engine.js，
// 只给最小 SC / window / document 桩，验证布局数学、常量、glyph 清单与 API 形状。
//
//   node test/engine.test.mjs
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import vm from 'node:vm'

const here = path.dirname(fileURLToPath(import.meta.url))
const source = readFileSync(path.join(here, '..', 'client-src', '10-engine.js'), 'utf8')

// ── 测试脚手架 ────────────────────────────────────────────────────────────────
let passed = 0
const failures = []

function test(name, fn) {
  try {
    fn()
    passed += 1
    console.log('ok   ' + name)
  } catch (error) {
    failures.push({ name, error })
    console.log('FAIL ' + name)
    console.log('     ' + String((error && error.stack) || error).split('\n').join('\n     '))
  }
}

function assert(cond, message) {
  if (!cond) throw new Error(message || 'assertion failed')
}

function equal(actual, expected, message) {
  if (actual !== expected) {
    throw new Error((message || 'not equal') + ': expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(actual))
  }
}

function approx(actual, expected, message, tolerance) {
  const tol = tolerance === undefined ? 1e-6 : tolerance
  if (!Number.isFinite(actual) || Math.abs(actual - expected) > tol) {
    throw new Error((message || 'not approximately equal') + ': expected ' + expected + ' ±' + tol + ', got ' + actual)
  }
}

function deepEqual(actual, expected, message) {
  const a = JSON.stringify(actual)
  const b = JSON.stringify(expected)
  if (a !== b) throw new Error((message || 'deep not equal') + ':\n  actual   ' + a + '\n  expected ' + b)
}

function makeContext(counter) {
  const gradientFactory = () => ({ addColorStop() {} })
  const base = {
    measureText: (text) => ({ width: String(text).length * 7 }),
    createLinearGradient: gradientFactory,
    createRadialGradient: gradientFactory,
    // 每帧绘制开头都会 setTransform；计数等于实际重绘次数。
    setTransform: () => { if (counter) counter.draws += 1 },
  }
  return new Proxy(base, {
    get(target, key) {
      if (key in target) return target[key]
      if (typeof key === 'symbol') return undefined
      return function noop() {}
    },
    set(target, key, value) {
      target[key] = value
      return true
    },
  })
}

function makeCanvas(width, height, counter) {
  const ctx = makeContext(counter)
  const listeners = new Map()
  return {
    width: 0,
    height: 0,
    clientWidth: width,
    clientHeight: height,
    style: { touchAction: '' },
    parentElement: null,
    __ctx: ctx,
    __listeners: listeners,
    getContext: () => ctx,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: width, bottom: height, width, height }),
    addEventListener: (type, fn) => { listeners.set(type, fn) },
    removeEventListener: (type) => { listeners.delete(type) },
    setPointerCapture() {},
    releasePointerCapture() {},
  }
}

function makePalette() {
  const tones = {
    intake: '#D9902F', route: '#4A7DFF', index: '#2AA7B8', check: '#8A6CF0',
    book: '#3C9A78', code: '#E07A3F', hit: '#3FA46A', miss: '#6E7C93',
    flag: '#C9A227', feedback: '#7C8698', warn: '#D9822B', risk: '#D65454',
    neutral: '#6E7C93', spark: '#C9A227',
  }
  return {
    mode: 'light',
    surface: '#ffffff',
    surfaceAlt: '#f7f8fa',
    surfaceDeep: '#eef0f4',
    overlay: '#ffffff',
    border: '#e3e6ec',
    borderStrong: '#cfd4dd',
    text: '#101318',
    text2: '#5b6472',
    text3: 'rgba(91,100,114,0.62)',
    grid: 'rgba(227,230,236,0.55)',
    edge: 'rgba(207,212,221,0.8)',
    accent: '#4a7dff',
    accentHex: '#4a7dff',
    nodeBgTop: '#f7f8fa',
    nodeBgBottom: '#fbfcfd',
    shadow: 'rgba(20,30,50,0.16)',
    glow: 0.28,
    introBg: '#ffffff',
    tones,
    alpha: (color, a) => 'rgba(0,0,0,' + a + ')',
  }
}

function makeSandbox(options) {
  const opts = options || {}
  const sandbox = {
    SC: {},
    console,
    document: {
      hidden: false,
      addEventListener() {},
      removeEventListener() {},
      createElement() {
        return {
          width: 0,
          height: 0,
          getContext: () => ({ fillStyle: '', fillRect() {}, drawImage() {} }),
          toDataURL: () => 'data:image/png;base64,AAAA',
        }
      },
    },
    window: {
      devicePixelRatio: opts.dpr === undefined ? 2 : opts.dpr,
      addEventListener() {},
      removeEventListener() {},
      matchMedia: () => ({ matches: false, addEventListener() {} }),
    },
    performance: { now: () => Date.now() },
    requestAnimationFrame: (cb) => {
      sandbox.__raf = cb
      sandbox.__rafId = (sandbox.__rafId || 0) + 1
      return sandbox.__rafId
    },
    cancelAnimationFrame: () => { sandbox.__raf = null },
  }
  return sandbox
}

function loadEngine(options) {
  const sandbox = makeSandbox(options)
  const context = vm.createContext(sandbox)
  vm.runInContext(source, context, { filename: 'client-src/10-engine.js' })
  return sandbox
}

const sandbox = loadEngine()
const SC = sandbox.SC
const internals = SC.engineInternals
const LAYOUT = internals.LAYOUT

function flushFrame(context, step) {
  const cb = context.__raf
  if (typeof cb !== 'function') return false
  context.__raf = null
  cb(Date.now() + (step || 0) * 16)
  return true
}

function graphOf(nodes, edges, columns) {
  return {
    columns: columns || [],
    nodes: nodes.map((node, i) => Object.assign({ idx: i, col: 0, lane: i, accent: '#4A7DFF', glyph: 'dot', title: 't' + i, subtitle: 's', meta: 'step 1 · x', badges: [], emphasis: 'normal' }, node)),
    edges: edges || [],
  }
}

// ── 常量与清单 ────────────────────────────────────────────────────────────────
test('engineInternals 暴露 layout 与契约常量', () => {
  assert(typeof internals.layout === 'function', 'layout 应是函数')
  equal(LAYOUT.NODE_W, 236)
  equal(LAYOUT.NODE_H, 84)
  equal(LAYOUT.NODE_H_CONCLUSION, 92)
  equal(LAYOUT.COL_GAP, 88)
  equal(LAYOUT.ROW_GAP, 18)
  equal(LAYOUT.PAD_X, 120)
  equal(LAYOUT.PAD_Y, 110)
  equal(LAYOUT.ZOOM_MIN, 0.35)
  equal(LAYOUT.ZOOM_MAX, 2.2)
})

test('glyph 清单覆盖契约 §3.3 的 16 个键', () => {
  const expected = ['intake', 'route', 'index', 'check', 'spark', 'book', 'code', 'hit', 'miss', 'flag', 'doc', 'loop', 'resume', 'feedback', 'cross', 'dot']
  deepEqual(internals.glyphKeys, expected)
})

test('文件是纯脚本函数体：没有 import/export', () => {
  assert(!/^\s*(import|export)\s/m.test(source), 'client-src 产物不能有 ESM 语法')
})

// ── 布局纯函数 ────────────────────────────────────────────────────────────────
test('空图返回空数组（null 也安全）', () => {
  deepEqual(internals.layout({ columns: [], nodes: [], edges: [] }), [])
  deepEqual(internals.layout(null), [])
  deepEqual(internals.layout({}), [])
})

test('单列两节点：水平居左、垂直以中轴居中、间距 102', () => {
  const rects = internals.layout(graphOf([
    { col: 0, lane: 0 },
    { col: 0, lane: 1 },
  ]))
  equal(rects.length, 2)
  equal(rects[0].x, LAYOUT.PAD_X)
  equal(rects[1].x, LAYOUT.PAD_X)
  equal(rects[0].w, LAYOUT.NODE_W)
  equal(rects[0].h, LAYOUT.NODE_H)
  equal(rects[0].y, LAYOUT.PAD_Y)
  equal(rects[1].y, LAYOUT.PAD_Y + LAYOUT.NODE_H + LAYOUT.ROW_GAP)
  // 两节点中轴 = PAD_Y + 列高/2；lane 0/1 关于它对称。
  const center0 = rects[0].y + rects[0].h / 2
  const center1 = rects[1].y + rects[1].h / 2
  approx(center0, LAYOUT.PAD_Y + LAYOUT.NODE_H / 2)
  approx(center1 - center0, LAYOUT.NODE_H + LAYOUT.ROW_GAP)
  approx((center0 + center1) / 2, LAYOUT.PAD_Y + (2 * LAYOUT.NODE_H + LAYOUT.ROW_GAP) / 2)
})

test('多列：x 每列递进 NODE_W + COL_GAP', () => {
  const rects = internals.layout(graphOf([
    { col: 0, lane: 0 },
    { col: 1, lane: 0 },
    { col: 2, lane: 0 },
  ]))
  equal(rects[0].x, LAYOUT.PAD_X)
  equal(rects[1].x, LAYOUT.PAD_X + LAYOUT.NODE_W + LAYOUT.COL_GAP)
  equal(rects[2].x, LAYOUT.PAD_X + 2 * (LAYOUT.NODE_W + LAYOUT.COL_GAP))
  // 同高列共享中轴：单节点列放大节点也垂直居中。
  approx(rects[0].y + rects[0].h / 2, rects[2].y + rects[2].h / 2)
})

test('并行列 lane 对称，短列与长列共用中轴', () => {
  const rects = internals.layout(graphOf([
    { col: 0, lane: 0 },
    { col: 0, lane: 1 },
    { col: 0, lane: 2 },
    { col: 1, lane: 0 },
    { col: 1, lane: 1 },
  ]))
  const c0 = rects[0].y + rects[0].h / 2
  const c1 = rects[1].y + rects[1].h / 2
  const c2 = rects[2].y + rects[2].h / 2
  approx(c1 - c0, LAYOUT.NODE_H + LAYOUT.ROW_GAP)
  approx(c2 - c1, LAYOUT.NODE_H + LAYOUT.ROW_GAP)
  approx(c1, c0 + (c2 - c0) / 2, 'lane 1 应是 lane 0/2 的中点')
  // 长列 3 个节点决定最大列高：centerY = PAD_Y + 288/2。
  approx(c1, LAYOUT.PAD_Y + (3 * LAYOUT.NODE_H + 2 * LAYOUT.ROW_GAP) / 2)
  // 短列 2 节点围绕同一个 centerY 对称。
  const d0 = rects[3].y + rects[3].h / 2
  const d1 = rects[4].y + rects[4].h / 2
  approx((d0 + d1) / 2, c1)
  approx(d1 - d0, LAYOUT.NODE_H + LAYOUT.ROW_GAP)
})

test('emphasis conclusion 高 92，仍以 lane 中心线居中', () => {
  const rects = internals.layout(graphOf([
    { col: 0, lane: 0, emphasis: 'conclusion' },
  ]))
  equal(rects[0].h, LAYOUT.NODE_H_CONCLUSION)
  equal(rects[0].w, LAYOUT.NODE_W)
  approx(rects[0].y + rects[0].h / 2, LAYOUT.PAD_Y + LAYOUT.NODE_H / 2)
  // 与相邻普通节点共享 lane 中轴，不会被拉偏。
  const mixed = internals.layout(graphOf([
    { col: 0, lane: 0, emphasis: 'conclusion' },
    { col: 0, lane: 1 },
  ]))
  approx(mixed[0].y + mixed[0].h / 2, LAYOUT.PAD_Y + LAYOUT.NODE_H / 2)
  approx(mixed[1].y + mixed[1].h / 2, mixed[0].y + mixed[0].h / 2 + LAYOUT.NODE_H + LAYOUT.ROW_GAP)
})

test('布局无副作用且确定性：同样输入两次结果一致、不改 graph', () => {
  const graph = graphOf([
    { col: 0, lane: 0 },
    { col: 0, lane: 1 },
    { col: 1, lane: 0, emphasis: 'conclusion' },
  ], [{ from: 0, to: 1, kind: 'main' }])
  const before = JSON.stringify(graph)
  const first = internals.layout(graph)
  const second = internals.layout(graph)
  deepEqual(second, first)
  equal(JSON.stringify(graph), before, 'layout 不应修改入参')
})

test('缺省 lane 按列内出现顺序补位', () => {
  const rects = internals.layout({
    columns: [],
    nodes: [
      { idx: 0, col: 0, accent: '#4A7DFF' },
      { idx: 1, col: 0, accent: '#4A7DFF' },
    ],
    edges: [],
  })
  equal(rects[0].x, LAYOUT.PAD_X)
  equal(rects[0].y, LAYOUT.PAD_Y)
  equal(rects[1].y, LAYOUT.PAD_Y + LAYOUT.NODE_H + LAYOUT.ROW_GAP)
})

test('layout 位置按下标（node.idx）落位', () => {
  const rects = internals.layout({
    columns: [],
    nodes: [
      { idx: 1, col: 0, lane: 0 },
      { idx: 0, col: 0, lane: 1 },
    ],
    edges: [],
  })
  // first 节点 idx=1 → 落在 lane 0 的位置；第二个节点 idx=0 → 落在 lane 1 的位置。
  equal(rects[1].y, LAYOUT.PAD_Y)
  equal(rects[0].y, LAYOUT.PAD_Y + LAYOUT.NODE_H + LAYOUT.ROW_GAP)
})

// ── createEngine API 冒烟 ────────────────────────────────────────────────────
test('createEngine 返回契约 §3 的全部方法', () => {
  const canvas = makeCanvas(900, 640)
  const engine = SC.createEngine({ canvas, palette: () => makePalette() })
  const names = ['setGraph', 'setSelected', 'setHovered', 'setReplay', 'setReplayFocus', 'flyTo', 'fit', 'zoomBy', 'resize', 'nodeRect', 'exportImage', 'destroy']
  for (const name of names) equal(typeof engine[name], 'function', '缺少方法 ' + name)
  equal(engine.nodeRect(0), null, '没有图时 nodeRect 返回 null')
  engine.destroy()
  engine.destroy()
})

test('exportImage：无尺寸画布时 null；有图时返回 PNG dataURL（不引用作用域外变量）', () => {
  const emptyCanvas = makeCanvas(0, 0)
  const emptyEngine = SC.createEngine({ canvas: emptyCanvas, palette: () => makePalette() })
  emptyCanvas.width = 0
  equal(emptyEngine.exportImage(), null, '画布没有尺寸时返回 null')
  emptyEngine.destroy()
  const canvas = makeCanvas(800, 600)
  const engine = SC.createEngine({ canvas, palette: () => makePalette() })
  engine.setGraph(graphOf([{ idx: 0, step: 1, title: '现场', subtitle: 's', meta: 'step 1 · 现场' }]))
  const url = engine.exportImage()
  assert(typeof url === 'string' && url.startsWith('data:image/png;base64,'), '导出应返回 PNG dataURL，实际: ' + String(url))
  engine.destroy()
  equal(engine.exportImage(), null, 'destroy 后返回 null')
})

test('缺少 palette 时明确抛错，而不是画成默认色', () => {
  const canvas = makeCanvas(300, 200)
  let threw = false
  try {
    SC.createEngine({ canvas })
  } catch (error) {
    threw = true
  }
  assert(threw, '未提供 palette 应抛错')
})

test('setGraph 自动 fit：DPR、画布尺寸、nodeRect 屏幕坐标正确', () => {
  const context = loadEngine()
  const engine = context.SC.createEngine({ canvas: makeCanvas(900, 640), palette: () => makePalette(), reducedMotion: true })
  const graph = graphOf([
    { col: 0, lane: 0 },
    { col: 0, lane: 1 },
  ], [{ from: 0, to: 1, kind: 'main' }])
  engine.setGraph(graph)
  engine.fit({ animate: false })
  const rect = engine.nodeRect(0)
  assert(rect, 'nodeRect(0) 应有值')
  approx(rect.w / LAYOUT.NODE_W, rect.h / LAYOUT.NODE_H, '宽高应同倍缩放')
  assert(rect.w > 0 && rect.w <= LAYOUT.NODE_W * 2.2, '缩放应落在契约范围内')
  // fit 后两列内容水平居中：单列图的中点应在画布中点附近。
  approx(rect.x + rect.w / 2, 450, '单列图应水平居中', 2)
  engine.destroy()
  engine.resize()
  equal(engine.nodeRect(0), null, 'destroy 后 nodeRect 返回 null')
})

test('交互方法、选中/聚光/相机与帧循环不抛错，destroy 清理 rAF', () => {
  const context = loadEngine()
  const canvas = makeCanvas(900, 640)
  const engine = context.SC.createEngine({
    canvas,
    palette: () => makePalette(),
    onSelect: () => {},
    onHover: () => {},
  })
  const graph = graphOf([
    { col: 0, lane: 0 },
    { col: 1, lane: 0, emphasis: 'conclusion' },
    { col: 1, lane: 1 },
  ], [{ from: 0, to: 1, kind: 'main' }, { from: 1, to: 2, kind: 'return' }], [
    { col: 0, step: 1, label: '现场', count: 1, accent: '#D9902F', parallel: false },
    { col: 1, step: 2, label: '核验', count: 2, accent: '#8A6CF0', parallel: true },
  ])
  engine.setGraph(graph)
  engine.setSelected(1)
  engine.setHovered(0)
  engine.setReplay(true)
  engine.setReplayFocus(1)
  engine.flyTo(2, { duration: 5 })
  engine.zoomBy(1.2)
  engine.fit({ animate: true })
  engine.resize()
  // 手动推进几帧，覆盖绘制路径（假 ctx 全为 no-op）。
  let frames = 0
  for (let i = 0; i < 6; i += 1) {
    if (flushFrame(context, i)) frames += 1
  }
  assert(frames > 0, 'rAF 循环应已启动')
  assert(context.__raf !== null && typeof context.__raf === 'function', '循环应保持单 rAF 链')
  engine.setReplay(false)
  engine.setSelected(null)
  engine.destroy()
  equal(context.__raf, null, 'destroy 后不再有排队的 rAF')
  equal(canvas.__listeners.size, 0, 'destroy 后事件监听应全部移除')
})

test('reducedMotion 下 setGraph 用初始相机、fit 瞬时切总览', () => {
  const context = loadEngine()
  const engine = context.SC.createEngine({
    canvas: makeCanvas(640, 480),
    palette: () => makePalette(),
    reducedMotion: true,
  })
  // 两列图在 640px 宽下 fitZoom≈0.75 < 0.8，初始相机应贴第一列（56px, 0.82）。
  engine.setGraph(graphOf([{ col: 0, lane: 0 }, { col: 1, lane: 0 }]))
  const rect = engine.nodeRect(0)
  assert(rect && rect.w > 0, '静止模式应立即得到屏幕矩形')
  approx(rect.w / 236, 0.82, '初始缩放应为 0.82', 0.001)
  approx(rect.x, 56, '第一列距画布左边 56px', 1)
  // fit 仍保持「整图适配」语义：缩小到看全，且瞬时生效。
  engine.fit({ animate: true })
  const fitRect = engine.nodeRect(0)
  assert(fitRect.w / 236 < 0.8, 'fit 后应进入整图倍率')
  assert(fitRect.x >= 0, 'fit 后第一列不应跑到画布左侧外')
  engine.destroy()
})

test('真实窄画布 620×760：多列图初始 0.82 贴第一列，fit 才能看全', () => {
  const context = loadEngine()
  const canvas = makeCanvas(620, 760)
  const engine = context.SC.createEngine({ canvas, palette: () => makePalette(), reducedMotion: true })
  const nodes = []
  for (let col = 0; col < 6; col += 1) {
    nodes.push({ col: col, lane: 0 })
    nodes.push({ col: col, lane: 1 })
  }
  engine.setGraph(graphOf(nodes))
  const first = engine.nodeRect(0)
  approx(first.w / 236, internals.RENDER.INITIAL_ZOOM, '窄画布初始缩放应为 0.82', 0.001)
  approx(first.x, internals.RENDER.INITIAL_LEFT_PADDING, '第一列左边距应为 56px', 2)
  const last = engine.nodeRect(nodes.length - 1)
  assert(last.x + last.w > 620, '初始相机只保证第一列可读，其余列应在视口外（可拖拽）')
  approx((first.y + first.h / 2), 380, '整图垂直居中', 80)

  engine.fit({ animate: false })
  const fitFirst = engine.nodeRect(0)
  const fitLast = engine.nodeRect(nodes.length - 1)
  assert(fitFirst.w / 236 < 0.5, 'fit 应缩到总览倍率（< 0.5）')
  assert(fitFirst.x >= 0 && fitLast.x + fitLast.w <= 620.5, 'fit 后整图应落在视口内')
  // 总览态会走低倍率紧凑块绘制路径，推进几帧确认不抛错。
  let frames = 0
  for (let i = 0; i < 3; i += 1) if (flushFrame(context, i)) frames += 1
  assert(frames > 0, '总览态帧循环应继续')
  engine.destroy()
})

test('宽画布 + 多列图：fitZoom < 0.8 时初始相机同样是 0.82', () => {
  const context = loadEngine()
  const engine = context.SC.createEngine({ canvas: makeCanvas(1400, 820), palette: () => makePalette(), reducedMotion: true })
  const nodes = []
  for (let col = 0; col < 6; col += 1) {
    nodes.push({ col: col, lane: 0 })
    nodes.push({ col: col, lane: 1 })
  }
  engine.setGraph(graphOf(nodes))
  const first = engine.nodeRect(0)
  approx(first.w / 236, 0.82, '宽画布上 6 列图 fitZoom≈0.64，初始相机仍应是 0.82', 0.001)
  approx(first.x, 56, '第一列仍贴左边 56px', 2)
  const last = engine.nodeRect(nodes.length - 1)
  assert(last.x > 1000, '最后一列应在视口右侧更远处（靠拖拽/迷你地图漫游）')
  // fit 后总览倍率约 (1400-112)/2000 = 0.64，整图可见。
  engine.fit({ animate: false })
  const fitFirst = engine.nodeRect(0)
  const fitLast = engine.nodeRect(nodes.length - 1)
  approx(fitFirst.w / 236, (1400 - internals.RENDER.FIT_PADDING * 2) / 2000, 'fit 应为整图适配倍率', 0.01)
  assert(fitFirst.x >= 0 && fitLast.x + fitLast.w <= 1400.5, 'fit 后整图应落在视口内')
  engine.destroy()
})

test('小图在宽画布上仍直接整图 fit（fitZoom >= 0.8）', () => {
  const context = loadEngine()
  const engine = context.SC.createEngine({ canvas: makeCanvas(1000, 760), palette: () => makePalette(), reducedMotion: true })
  engine.setGraph(graphOf([{ col: 0, lane: 0 }, { col: 1, lane: 0 }]))
  const a = engine.nodeRect(0)
  const b = engine.nodeRect(1)
  approx(a.w / 236, 0.82, '两列图 fitZoom≈1.07 >= 0.8，应走整图 fit（上限 1.2）', 0.4)
  assert(a.w / 236 >= 0.8, '小图初始倍率不应低于 fit 阈值')
  approx((a.x + a.w / 2 + b.x + b.w / 2) / 2, 500, '小图应水平居中', 3)
  engine.destroy()
})

test('低倍率 / 迷你地图判定常量可导出', () => {
  const render = internals.RENDER
  equal(render.INITIAL_ZOOM, 0.82)
  equal(render.INITIAL_FIT_ZOOM, 0.8)
  equal(render.LOD_ZOOM, 0.62)
  equal(render.MINIMAP_MIN_W, 560)
  equal(render.MINIMAP_MIN_H, 360)
  equal(internals.isCompactZoom(0.5), true)
  equal(internals.isCompactZoom(0.62), false)
  equal(internals.isCompactZoom(0.9), false)
  equal(internals.canShowMinimap(620, 760), true)
  equal(internals.canShowMinimap(519, 760), false)
  equal(internals.canShowMinimap(620, 359), false)
})

test('点击命中节点回调 onSelect(idx)，点击空白回调 onSelect(null)', () => {
  const context = loadEngine()
  const canvas = makeCanvas(900, 640)
  const selected = []
  const hoveredList = []
  const engine = context.SC.createEngine({
    canvas,
    palette: () => makePalette(),
    reducedMotion: true,
    onSelect: (idx) => selected.push(idx),
    onHover: (idx) => hoveredList.push(idx),
  })
  engine.setGraph(graphOf([{ col: 0, lane: 0 }, { col: 1, lane: 0 }], [{ from: 0, to: 1, kind: 'main' }]))
  engine.fit({ animate: false })
  const rect = engine.nodeRect(0)
  const inside = { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2 }
  const down = canvas.__listeners.get('pointerdown')
  const move = canvas.__listeners.get('pointermove')
  const up = canvas.__listeners.get('pointerup')
  assert(down && move && up, 'pointer 监听应已挂上')
  move({ clientX: inside.x, clientY: inside.y, pointerId: 1, pointerType: 'mouse', button: 0 })
  deepEqual(hoveredList, [0], 'hover 进入节点应回调 0')
  down({ clientX: inside.x, clientY: inside.y, pointerId: 1, pointerType: 'mouse', button: 0 })
  up({ clientX: inside.x, clientY: inside.y, pointerId: 1, pointerType: 'mouse', button: 0 })
  deepEqual(selected, [0], '点击节点应回调 0')
  down({ clientX: 4, clientY: 4, pointerId: 2, pointerType: 'mouse', button: 0 })
  up({ clientX: 4, clientY: 4, pointerId: 2, pointerType: 'mouse', button: 0 })
  deepEqual(selected, [0, null], '点击空白应回调 null')
  engine.destroy()
})

test('nodeRect 越界下标返回 null；setSelected 越界不抛错', () => {
  const context = loadEngine()
  const engine = context.SC.createEngine({ canvas: makeCanvas(600, 400), palette: () => makePalette(), reducedMotion: true })
  engine.setGraph(graphOf([{ col: 0, lane: 0 }]))
  equal(engine.nodeRect(3), null)
  equal(engine.nodeRect(-1), null)
  engine.setSelected(9)
  engine.setHovered(9)
  engine.setReplayFocus(9)
  engine.destroy()
})

test('畸形 graph（空节点、越界边、null）不抛错，帧循环继续', () => {
  const context = loadEngine()
  const engine = context.SC.createEngine({ canvas: makeCanvas(800, 600), palette: () => makePalette() })
  engine.setGraph(null)
  engine.setGraph({ columns: null, nodes: null, edges: null })
  engine.setGraph({ nodes: [{}], edges: [{ from: 0, to: 99, kind: 'main' }, { from: -1, to: 0 }] })
  engine.fit()
  let frames = 0
  for (let i = 0; i < 4; i += 1) if (flushFrame(context, i)) frames += 1
  assert(frames > 0, '畸形图下帧循环应继续')
  engine.destroy()
})

test('无动画时降频重绘，粒子阶段才按帧推进（单 rAF 链）', () => {
  // reducedMotion：没有粒子/入场，静止后只在 dirty 或降频节拍上重绘。
  const still = { draws: 0 }
  const contextA = loadEngine()
  const engineA = contextA.SC.createEngine({
    canvas: makeCanvas(800, 600, still),
    palette: () => makePalette(),
    reducedMotion: true,
  })
  engineA.setGraph(graphOf([{ col: 0, lane: 0 }, { col: 1, lane: 0 }], [{ from: 0, to: 1, kind: 'main' }]))
  for (let i = 0; i < 20; i += 1) flushFrame(contextA, i)
  assert(still.draws >= 1, '至少应有首次绘制')
  assert(still.draws <= 4, '静止场景不应每帧重绘，实际 ' + still.draws + ' 次')
  engineA.destroy()

  // 正常模式：粒子和入场动画让画面保持活跃，帧数应明显更多。
  const live = { draws: 0 }
  const contextB = loadEngine()
  const engineB = contextB.SC.createEngine({
    canvas: makeCanvas(800, 600, live),
    palette: () => makePalette(),
    reducedMotion: false,
  })
  engineB.setGraph(graphOf([{ col: 0, lane: 0 }, { col: 1, lane: 0 }], [{ from: 0, to: 1, kind: 'main' }]))
  for (let i = 0; i < 20; i += 1) flushFrame(contextB, i)
  assert(live.draws >= 10, '动画期应按帧推进，实际 ' + live.draws + ' 次')
  engineB.destroy()
})

test('拖拽平移 / 滚轮缩放 / 迷你地图拖拽都能改相机且不抛错', () => {
  const context = loadEngine()
  const canvas = makeCanvas(900, 640)
  const engine = context.SC.createEngine({ canvas, palette: () => makePalette(), reducedMotion: false })
  engine.setGraph(graphOf([{ col: 0, lane: 0 }, { col: 0, lane: 1 }], [{ from: 0, to: 1, kind: 'main' }]))
  engine.fit({ animate: false })
  for (let i = 0; i < 4; i += 1) flushFrame(context, i)
  const listeners = canvas.__listeners
  const down = listeners.get('pointerdown')
  const move = listeners.get('pointermove')
  const up = listeners.get('pointerup')
  const wheel = listeners.get('wheel')
  assert(down && move && up && wheel, 'pointer/wheel 监听应已挂上')

  // 拖拽平移：屏幕位移应等量映射到 nodeRect.x/y。
  const before = engine.nodeRect(0)
  down({ clientX: 300, clientY: 90, pointerId: 7, pointerType: 'mouse', button: 0 })
  move({ clientX: 340, clientY: 115, pointerId: 7, pointerType: 'mouse', button: 0 })
  up({ clientX: 340, clientY: 115, pointerId: 7, pointerType: 'mouse', button: 0 })
  const afterDrag = engine.nodeRect(0)
  approx(afterDrag.x - before.x, 40, '拖拽 40px 应平移 40px', 1.5)
  approx(afterDrag.y - before.y, 25, '拖拽 25px 应平移 25px', 1.5)

  // 滚轮以指针为锚缩放：推进若干帧后节点应被放大。
  let prevented = 0
  wheel({ clientX: 450, clientY: 320, deltaY: -120, deltaMode: 0, preventDefault: () => { prevented += 1 } })
  equal(prevented, 1, '滚轮应 preventDefault')
  for (let i = 0; i < 24; i += 1) flushFrame(context, 10 + i)
  const afterWheel = engine.nodeRect(0)
  assert(afterWheel.w > afterDrag.w * 1.05, '滚轮上滚应放大节点（' + afterDrag.w.toFixed(1) + ' → ' + afterWheel.w.toFixed(1) + '）')

  // 迷你地图：面板在右下角，点击面板中心应移动视口并结束拖拽。
  const panelCenter = { x: 900 - 168 / 2 - 16, y: 640 - 112 / 2 - 16 }
  const beforeMini = engine.nodeRect(0)
  down({ clientX: panelCenter.x, clientY: panelCenter.y, pointerId: 8, pointerType: 'mouse', button: 0 })
  move({ clientX: panelCenter.x + 10, clientY: panelCenter.y - 8, pointerId: 8, pointerType: 'mouse', button: 0 })
  up({ clientX: panelCenter.x + 10, clientY: panelCenter.y - 8, pointerId: 8, pointerType: 'mouse', button: 0 })
  const afterMini = engine.nodeRect(0)
  assert(afterMini, '迷你地图操作后 nodeRect 仍有效')
  assert(Math.abs(afterMini.x - beforeMini.x) > 0.5 || Math.abs(afterMini.y - beforeMini.y) > 0.5, '迷你地图应改变视口')
  engine.destroy()
})

// ── 汇总 ──────────────────────────────────────────────────────────────────────
console.log('')
if (failures.length) {
  console.log(failures.length + ' failed, ' + passed + ' passed')
  process.exit(1)
}
console.log(passed + ' passed')
