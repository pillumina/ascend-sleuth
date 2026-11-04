// 画布引擎（纯 canvas，不碰 React）。契约 docs/CONTRACT.md §3，视觉 docs/DESIGN.md §2/§4.3/§5。
//
// 坐标口径：世界坐标原点在左上、无旋转；screen = world * zoom + pan（pan 单位 CSS px）。
// 颜色只取自 opts.palette()（SC.theme.currentPalette），本文件不写主题色；glyph 只是路径数据。
// 求值阶段不碰 DOM：所有 window/document 访问都在 createEngine 之后或绘制时发生。
//
// 两个宿主尺寸相关的策略（真实画布只有约 580–1000 CSS px 宽）：
//   1. setGraph 的初始相机不整图 fit：fitZoom < 0.8 时用 0.82 贴住第一列，只有小图才一眼看全；
//      fit()/双击仍保持整图适配语义（作为显式总览入口，允许缩到低于滚轮下限）。
//   2. zoom < LOD_ZOOM 时节点改画紧凑块（色条+图标+家族短标签+step 数字，按 1/zoom 反缩放），
//      列头同理；0.62–0.8 仍是完整卡。
//   3. 画布小于 560×360 时不画迷你地图，避免压住内容。

const FONT_STACK = 'ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'
const MONO_STACK = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace'

const F_TITLE = '600 13px ' + FONT_STACK
const F_SUB = '11.5px ' + FONT_STACK
const F_META = '10.5px ' + FONT_STACK
const F_STEP = '600 10px ' + MONO_STACK
const F_BADGE = '600 10px ' + FONT_STACK
const F_HEAD = '600 12.5px ' + FONT_STACK
const F_HEAD_NUM = '600 11px ' + MONO_STACK
const F_CHIP = '600 10px ' + MONO_STACK
const F_EMPTY_TITLE = '600 14px ' + FONT_STACK
const F_EMPTY_SUB = '11.5px ' + FONT_STACK

// 布局常量：与契约 §3.1 逐字一致，engine.test.mjs 会断言。
const NODE_W = 236
const NODE_H = 84
const NODE_H_CONCLUSION = 92
const COL_GAP = 88
const ROW_GAP = 18
const PAD_X = 120
const PAD_Y = 110

const ZOOM_MIN = 0.35
const ZOOM_MAX = 2.2
// fit 的缩放上限：整图适配时不让两个节点的图被放到 2 倍大，留出呼吸空间。
const FIT_MAX_ZOOM = 1.2
// 总览允许比交互缩放下限更小：620px 宽看 6 列图需要 ~0.25，否则「看全」做不到。
// 滚轮仍受 ZOOM_MIN 约束，但从 fit 的小倍率往回滚时不会跳大。
const FIT_MIN_ZOOM = 0.18
const FIT_PADDING = 56

// 真实宿主里画布只有约 580–1000 CSS px（侧栏 + 264 列表 + 336 检查器之后），
// 6 列图整图 fit 后 zoom 只有 0.27–0.49，字会缩到 3–6px。所以：
// 初始相机保证第一列可读（0.82），只有小图才直接看全；低于 LOD_ZOOM 改画紧凑块。
const INITIAL_ZOOM = 0.82
const INITIAL_FIT_ZOOM = 0.8
const LOD_ZOOM = 0.62
const INITIAL_LEFT_PADDING = 56
// 窄画布上迷你地图会盖住内容（页面底部缩放钮又在它上方），小于这个尺寸就自动隐藏。
const MINIMAP_MIN_W = 560
const MINIMAP_MIN_H = 360

const GRID_SPACING = 26
const DIM_ALPHA = 0.22
const MINIMAP_W = 168
const MINIMAP_H = 112
const MINIMAP_MARGIN = 16
// 空闲时半透明，指针进入迷你地图才完全显现：减少它压住列尾卡片的观感。
const MINIMAP_IDLE_ALPHA = 0.55
const MINIMAP_PAD = 10
const PARTICLE_PERIOD = 3200
const IDLE_AFTER = 6000
const IDLE_FPS_MS = 33

// ── glyph：24×24 线性图标，stroke 1.7/1.8，无填充。每个 op 是 ['M'|'L'|'C'|'Q'|'Z'|'arc', ...坐标]。
const GLYPHS = {
  intake: [
    ['M', 4, 13.5], ['L', 4, 19], ['L', 20, 19], ['L', 20, 13.5],
    ['M', 12, 3.5], ['L', 12, 14],
    ['M', 8.2, 10.2], ['L', 12, 14], ['L', 15.8, 10.2],
  ],
  route: [
    ['M', 4, 12], ['L', 9.6, 12],
    ['M', 9.6, 5.6], ['L', 9.6, 18.4],
    ['M', 9.6, 5.6], ['L', 18.6, 5.6],
    ['M', 9.6, 18.4], ['L', 18.6, 18.4],
    ['M', 15.4, 3], ['L', 18.6, 5.6], ['L', 15.4, 8.2],
    ['M', 15.4, 15.8], ['L', 18.6, 18.4], ['L', 15.4, 21],
  ],
  index: [
    ['M', 12, 3.4], ['L', 20.6, 8], ['L', 12, 12.6], ['L', 3.4, 8], ['Z'],
    ['M', 3.4, 12], ['L', 12, 16.6], ['L', 20.6, 12],
    ['M', 3.4, 16], ['L', 12, 20.6], ['L', 20.6, 16],
  ],
  check: [
    ['arc', 12, 12, 8.5, 0, Math.PI * 2],
    ['M', 7.9, 12.4], ['L', 10.9, 15.3], ['L', 16.2, 9.4],
  ],
  spark: [
    ['M', 12, 2.8],
    ['Q', 13.1, 9.4, 21.2, 12],
    ['Q', 13.1, 14.6, 12, 21.2],
    ['Q', 10.9, 14.6, 2.8, 12],
    ['Q', 10.9, 9.4, 12, 2.8],
    ['Z'],
  ],
  book: [
    ['M', 12, 6.2], ['C', 9.4, 4.3, 6, 4.1, 4, 5.4], ['L', 4, 18.9],
    ['C', 6, 17.6, 9.4, 17.8, 12, 19.7],
    ['C', 14.6, 17.8, 18, 17.6, 20, 18.9], ['L', 20, 5.4],
    ['C', 18, 4.1, 14.6, 4.3, 12, 6.2], ['Z'],
    ['M', 12, 6.2], ['L', 12, 19.7],
  ],
  code: [
    ['M', 9.2, 7], ['L', 4.2, 12], ['L', 9.2, 17],
    ['M', 14.8, 7], ['L', 19.8, 12], ['L', 14.8, 17],
  ],
  hit: [
    ['arc', 12, 12, 8.4, 0, Math.PI * 2],
    ['arc', 12, 12, 4.4, 0, Math.PI * 2],
    ['arc', 12, 12, 1.1, 0, Math.PI * 2],
  ],
  miss: [
    ['arc', 12, 12, 8.4, 0, Math.PI * 2],
    ['M', 6.2, 17.8], ['L', 17.8, 6.2],
  ],
  flag: [
    ['M', 6.2, 20.5], ['L', 6.2, 3.8],
    ['M', 6.2, 4.6], ['C', 9.2, 3.1, 12.6, 6.3, 18, 4.4],
    ['L', 18, 12.2], ['C', 12.6, 14.1, 9.2, 10.9, 6.2, 12.4],
  ],
  doc: [
    ['M', 7, 3.5], ['L', 14, 3.5], ['L', 18.5, 8], ['L', 18.5, 20.5],
    ['L', 7, 20.5], ['Z'],
    ['M', 14, 3.5], ['L', 14, 8], ['L', 18.5, 8],
    ['M', 9.6, 12.4], ['L', 15.9, 12.4],
    ['M', 9.6, 16], ['L', 15.9, 16],
  ],
  loop: [
    ['M', 18.8, 8.6], ['C', 18.8, 5.2, 15.9, 2.8, 12.3, 2.8],
    ['C', 8.7, 2.8, 5.8, 5.2, 5.8, 8.6], ['L', 5.8, 19.8],
    ['M', 2.9, 16.9], ['L', 5.8, 19.8], ['L', 8.7, 16.9],
  ],
  resume: [
    ['M', 8.6, 5.8], ['L', 18.2, 12], ['L', 8.6, 18.2], ['Z'],
  ],
  feedback: [
    ['M', 5, 7.4], ['Q', 5, 5.6, 6.8, 5.6], ['L', 17.2, 5.6],
    ['Q', 19, 5.6, 19, 7.4], ['L', 19, 13.6], ['Q', 19, 15.4, 17.2, 15.4],
    ['L', 11, 15.4], ['L', 7.2, 19.2], ['L', 7.2, 15.4],
    ['L', 6.8, 15.4], ['Q', 5, 15.4, 5, 13.6], ['Z'],
  ],
  cross: [
    ['M', 6.8, 6.8], ['L', 17.2, 17.2],
    ['M', 17.2, 6.8], ['L', 6.8, 17.2],
  ],
  dot: [
    ['arc', 12, 12, 4.6, 0, Math.PI * 2],
  ],
}

const GLYPH_KEYS = Object.keys(GLYPHS)

// 低倍率紧凑块的家族短标签：优先用页面给的 node.label，没给时按 glyph 兜底。
const GLYPH_LABELS = {
  intake: '现场',
  route: '分诊',
  index: '检索',
  check: '核验',
  cross: '排除',
  book: '先验',
  code: '源码',
  hit: '命中',
  miss: '未覆盖',
  flag: '归因',
  doc: '输出',
  loop: '续接',
  resume: '续接',
  feedback: '回报',
  spark: '结论',
  dot: '事件',
}

// ── 纯数学工具 ────────────────────────────────────────────────────────────────
function clamp(value, min, max) {
  return value < min ? min : value > max ? max : value
}

function lerp(from, to, t) {
  return from + (to - from) * t
}

function easeOutCubic(t) {
  const p = 1 - t
  return 1 - p * p * p
}

function cubicAxis(t, p1, p2) {
  const u = 1 - t
  return 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t
}

// cubic-bezier(.22,.61,.36,1)：按 x 二分反解参数再取 y。相机移动要“能被肉眼跟踪”，所以不用近似曲线。
function cubicBezierEase(x1, y1, x2, y2) {
  return function (x) {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let lo = 0
    let hi = 1
    let t = x
    for (let i = 0; i < 12; i += 1) {
      const xt = cubicAxis(t, x1, x2)
      if (Math.abs(xt - x) < 0.00005) break
      if (xt < x) lo = t
      else hi = t
      t = (lo + hi) / 2
    }
    return cubicAxis(t, y1, y2)
  }
}

const EASE_CAMERA = cubicBezierEase(0.22, 0.61, 0.36, 1)

// ── 布局（纯函数，可离线断言；无 DOM、无副作用）──────────────────────────────
// 契约 §3.1：x 是列内水平中心，y 是节点垂直中心；返回给渲染与 nodeRect 用的是左上角矩形。
function layout(graph) {
  const nodes = (graph && Array.isArray(graph.nodes)) ? graph.nodes : []
  const total = nodes.length
  if (total === 0) return []

  const info = []
  const colCounts = Object.create(null)
  for (let i = 0; i < total; i += 1) {
    const node = nodes[i] || {}
    const col = Number.isFinite(node.col) && node.col >= 0 ? Math.floor(node.col) : 0
    info.push({ col: col, lane: node.lane })
    colCounts[col] = (colCounts[col] || 0) + 1
  }
  // lane 缺省时按该列出现顺序补位，保证同一份 graph 每次算出的位置一致。
  const nextLane = Object.create(null)
  for (let i = 0; i < total; i += 1) {
    const item = info[i]
    const used = nextLane[item.col] || 0
    const lane = Number.isFinite(item.lane) && item.lane >= 0 ? Math.floor(item.lane) : used
    item.lane = lane
    nextLane[item.col] = Math.max(used, lane + 1)
  }

  let maxHeight = 0
  for (const key of Object.keys(colCounts)) {
    const count = colCounts[key]
    maxHeight = Math.max(maxHeight, count * NODE_H + (count - 1) * ROW_GAP)
  }
  const centerY = PAD_Y + maxHeight / 2

  const out = new Array(total)
  for (let i = 0; i < total; i += 1) {
    const node = nodes[i] || {}
    const item = info[i]
    const count = colCounts[item.col]
    const h = node.emphasis === 'conclusion' ? NODE_H_CONCLUSION : NODE_H
    const laneCenter = centerY + (item.lane - (count - 1) / 2) * (NODE_H + ROW_GAP)
    const rect = {
      x: PAD_X + item.col * (NODE_W + COL_GAP),
      y: laneCenter - h / 2,
      w: NODE_W,
      h: h,
    }
    // 节点 idx 即画布对外的身份（edges / nodeRect / 回调都用它）；异常时退回数组下标。
    const idx = Number.isFinite(node.idx) && node.idx >= 0 && node.idx < total ? Math.floor(node.idx) : i
    out[idx] = rect
  }
  return out
}

SC.engineInternals = {
  LAYOUT: {
    NODE_W: NODE_W,
    NODE_H: NODE_H,
    NODE_H_CONCLUSION: NODE_H_CONCLUSION,
    COL_GAP: COL_GAP,
    ROW_GAP: ROW_GAP,
    PAD_X: PAD_X,
    PAD_Y: PAD_Y,
    ZOOM_MIN: ZOOM_MIN,
    ZOOM_MAX: ZOOM_MAX,
  },
  layout: layout,
  glyphKeys: GLYPH_KEYS,
  RENDER: {
    INITIAL_ZOOM: INITIAL_ZOOM,
    INITIAL_FIT_ZOOM: INITIAL_FIT_ZOOM,
    INITIAL_LEFT_PADDING: INITIAL_LEFT_PADDING,
    LOD_ZOOM: LOD_ZOOM,
    MINIMAP_MIN_W: MINIMAP_MIN_W,
    MINIMAP_MIN_H: MINIMAP_MIN_H,
    FIT_PADDING: FIT_PADDING,
    FIT_MAX_ZOOM: FIT_MAX_ZOOM,
    FIT_MIN_ZOOM: FIT_MIN_ZOOM,
  },
  // 供页面/测试核对低倍率与迷你地图退化阈值，渲染内部用的是同一批常量。
  isCompactZoom: function isCompactZoom(zoom) {
    return Number.isFinite(zoom) && zoom < LOD_ZOOM
  },
  canShowMinimap: function canShowMinimap(width, height) {
    return width >= MINIMAP_MIN_W && height >= MINIMAP_MIN_H
  },
}

// ── 绘制基础件 ────────────────────────────────────────────────────────────────
function strokeGlyph(ctx, key, cx, cy, size, color) {
  const ops = GLYPHS[key] || GLYPHS.dot
  const scale = size / 24
  ctx.save()
  ctx.translate(cx, cy)
  ctx.scale(scale, scale)
  ctx.strokeStyle = color
  // 24 单位空间里的 1.8 会随 size 缩放成视觉一致的细线。
  ctx.lineWidth = 1.8
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  for (let i = 0; i < ops.length; i += 1) {
    const op = ops[i]
    switch (op[0]) {
      case 'M': ctx.moveTo(op[1], op[2]); break
      case 'L': ctx.lineTo(op[1], op[2]); break
      case 'C': ctx.bezierCurveTo(op[1], op[2], op[3], op[4], op[5], op[6]); break
      case 'Q': ctx.quadraticCurveTo(op[1], op[2], op[3], op[4]); break
      case 'Z': ctx.closePath(); break
      case 'arc':
        ctx.moveTo(op[1] + op[3], op[2])
        ctx.arc(op[1], op[2], op[3], op[4], op[5])
        break
      default: break
    }
  }
  ctx.stroke()
  ctx.restore()
}

function roundRectPath(ctx, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2))
  ctx.beginPath()
  if (typeof ctx.roundRect === 'function') {
    ctx.roundRect(x, y, w, h, radius)
    return
  }
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + w, y, x + w, y + h, radius)
  ctx.arcTo(x + w, y + h, x, y + h, radius)
  ctx.arcTo(x, y + h, x, y, radius)
  ctx.arcTo(x, y, x + w, y, radius)
  ctx.closePath()
}

function pointInRect(px, py, rect) {
  return px >= rect.x && py >= rect.y && px <= rect.x + rect.w && py <= rect.y + rect.h
}

function sampleCubic(sx, sy, c1x, c1y, c2x, c2y, ex, ey, steps) {
  const points = []
  const cum = [0]
  let total = 0
  let prevX = 0
  let prevY = 0
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps
    const mt = 1 - t
    const a = mt * mt * mt
    const b = 3 * mt * mt * t
    const c = 3 * mt * t * t
    const d = t * t * t
    const x = a * sx + b * c1x + c * c2x + d * ex
    const y = a * sy + b * c1y + c * c2y + d * ey
    if (i > 0) {
      total += Math.hypot(x - prevX, y - prevY)
      cum.push(total)
    }
    points.push({ x: x, y: y })
    prevX = x
    prevY = y
  }
  return { points: points, cum: cum, length: total }
}

// ── 引擎 ──────────────────────────────────────────────────────────────────────
SC.createEngine = function createEngine(opts) {
  const o = opts || {}
  const canvas = o.canvas
  if (!canvas || typeof canvas.getContext !== 'function') {
    throw new Error('sleuth-canvas engine: 需要 opts.canvas（HTMLCanvasElement）')
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('sleuth-canvas engine: canvas 不支持 2d 上下文')

  function nowMs() {
    if (typeof performance !== 'undefined' && performance && typeof performance.now === 'function') {
      return performance.now()
    }
    return Date.now()
  }

  function getPalette() {
    if (typeof o.palette === 'function') {
      const p = o.palette()
      if (p) return p
    } else if (o.palette && typeof o.palette === 'object') {
      // 契约要求传函数；传对象也接受，免得误用时整块画布黑掉。
      return o.palette
    }
    if (SC.theme && typeof SC.theme.currentPalette === 'function') return SC.theme.currentPalette()
    return null
  }

  const firstPalette = getPalette()
  if (!firstPalette) {
    throw new Error('sleuth-canvas engine: opts.palette() 没有返回调色板（SC.theme.currentPalette）')
  }

  function prefersReduced() {
    return !!o.reducedMotion
  }

  // 主题模块每 2s 会换一个新的 palette 对象（内容可能完全一样）。用签名字符串判断
  // 是否真的换了主题，避免无意义的模型/渐变重建；也防调用方每次返回新对象。
  function paletteSignature(p) {
    const tones = p.tones || {}
    const toneValues = []
    for (const key of Object.keys(tones)) toneValues.push(key + ':' + tones[key])
    return [
      p.mode, p.surface, p.surfaceAlt, p.overlay, p.border, p.borderStrong,
      p.text, p.text2, p.text3, p.grid, p.edge, p.accent,
      p.nodeBgTop, p.nodeBgBottom, p.shadow, p.glow, p.introBg || '',
    ].join('|') + '|' + toneValues.join(',')
  }

  let dead = false
  let palette = firstPalette
  let paletteSig = paletteSignature(firstPalette)
  let cssW = 0
  let cssH = 0
  let dpr = 1
  let rafId = 0
  let lastFrameAt = 0
  let lastDrawAt = 0
  let dirty = true
  let lastInteraction = 0

  let graph = { columns: [], nodes: [], edges: [] }
  let model = null
  let outgoing = null
  let hovered = null
  let selected = null
  let replay = false
  let replayFocus = null
  let focusPulseAt = -1e9

  const camera = { x: 0, y: 0, zoom: 1 }
  const camTarget = { x: 0, y: 0, zoom: 1 }
  let camAnim = null
  let camSmoothing = false
  let pendingFit = false
  let pendingInitial = false

  let spotlight = 0
  let spotlightTarget = 0
  const hoverLevels = new Map()
  let relevance = { model: null, focus: -2, nodes: null }

  let dragging = null
  let miniDrag = false
  let pointerScreen = null
  let prevTouchAction = ''
  let ro = null
  let winResizeBound = false

  const callbacks = {
    select: typeof o.onSelect === 'function' ? o.onSelect : null,
    hover: typeof o.onHover === 'function' ? o.onHover : null,
  }

  function touch() {
    dirty = true
    lastInteraction = nowMs()
  }

  function emitSelect(idx) {
    if (!callbacks.select) return
    try {
      callbacks.select(idx)
    } catch (error) {
      if (typeof console !== 'undefined') console.error('[sleuth-canvas] onSelect 抛错', error)
    }
  }

  function emitHover(idx) {
    if (!callbacks.hover) return
    try {
      callbacks.hover(idx)
    } catch (error) {
      if (typeof console !== 'undefined') console.error('[sleuth-canvas] onHover 抛错', error)
    }
  }

  // ── 尺寸 / 相机 ─────────────────────────────────────────────────────────────
  function readBox() {
    let w = 0
    let h = 0
    try {
      const rect = canvas.getBoundingClientRect()
      w = rect.width
      h = rect.height
    } catch (error) { /* 退化到 clientWidth */ }
    if ((!w || !h) && canvas.parentElement) {
      try {
        const parentRect = canvas.parentElement.getBoundingClientRect()
        w = w || parentRect.width
        h = h || parentRect.height
      } catch (error) { /* 忽略 */ }
    }
    if (!w && canvas.clientWidth) w = canvas.clientWidth
    if (!h && canvas.clientHeight) h = canvas.clientHeight
    return { w: Math.max(1, Math.round(w || 0)), h: Math.max(1, Math.round(h || 0)) }
  }

  function resize() {
    if (dead) return
    const box = readBox()
    const nextDpr = clamp((typeof window !== 'undefined' && window.devicePixelRatio) || 1, 1, 3)
    const changed = box.w !== cssW || box.h !== cssH || nextDpr !== dpr
    cssW = box.w
    cssH = box.h
    dpr = nextDpr
    const pw = Math.max(1, Math.round(cssW * dpr))
    const ph = Math.max(1, Math.round(cssH * dpr))
    if (canvas.width !== pw) canvas.width = pw
    if (canvas.height !== ph) canvas.height = ph
    try { ctx.setTransform(dpr, 0, 0, dpr, 0, 0) } catch (error) { /* 个例实现 */ }
    if (changed) {
      if (pendingInitial) {
        pendingInitial = false
        applyInitialCamera(false)
      } else if (pendingFit) {
        pendingFit = false
        computeFit(false)
      }
      touch()
    }
  }

  // 相机别让整张图拖出视野：内容至少留 margin 在视口内。
  function clampCamera(cam) {
    if (!model || !model.bounds) return
    const b = model.bounds
    const margin = 90
    const z = cam.zoom
    const minX = margin - b.maxX * z
    const maxX = cssW - margin - b.minX * z
    const minY = margin - b.maxY * z
    const maxY = cssH - margin - b.minY * z
    cam.x = minX <= maxX ? clamp(cam.x, minX, maxX) : (minX + maxX) / 2
    cam.y = minY <= maxY ? clamp(cam.y, minY, maxY) : (minY + maxY) / 2
  }

  function animateCameraTo(to, duration) {
    camTarget.x = to.x
    camTarget.y = to.y
    camTarget.zoom = to.zoom
    clampCamera(camTarget)
    if (!duration || prefersReduced() || cssW <= 1 || cssH <= 1) {
      camAnim = null
      camSmoothing = false
      camera.x = camTarget.x
      camera.y = camTarget.y
      camera.zoom = camTarget.zoom
      touch()
      return
    }
    camAnim = {
      at: nowMs(),
      dur: duration,
      from: { x: camera.x, y: camera.y, zoom: camera.zoom },
      to: { x: camTarget.x, y: camTarget.y, zoom: camTarget.zoom },
    }
    camSmoothing = false
    touch()
  }

  function updateCamera(t, dt) {
    if (camAnim) {
      const k = clamp((t - camAnim.at) / Math.max(1, camAnim.dur), 0, 1)
      const e = EASE_CAMERA(k)
      camera.x = lerp(camAnim.from.x, camAnim.to.x, e)
      camera.y = lerp(camAnim.from.y, camAnim.to.y, e)
      camera.zoom = lerp(camAnim.from.zoom, camAnim.to.zoom, e)
      if (k >= 1) camAnim = null
      return
    }
    if (!camSmoothing) return
    const k = 1 - Math.exp(-dt / 85)
    camera.x += (camTarget.x - camera.x) * k
    camera.y += (camTarget.y - camera.y) * k
    camera.zoom += (camTarget.zoom - camera.zoom) * k
    if (Math.abs(camTarget.x - camera.x) < 0.4 && Math.abs(camTarget.y - camera.y) < 0.4 &&
      Math.abs(camTarget.zoom - camera.zoom) < 0.0015) {
      camera.x = camTarget.x
      camera.y = camTarget.y
      camera.zoom = camTarget.zoom
      camSmoothing = false
    }
  }

  // 整图适配的目标相机（纯计算，不落地）。fit()/双击仍走这里。
  function fitCameraTarget() {
    if (!model || !model.nodes.length || !model.bounds) return null
    if (cssW <= 1 || cssH <= 1) return null
    const b = model.bounds
    const bw = Math.max(1, b.maxX - b.minX)
    const bh = Math.max(1, b.maxY - b.minY)
    const zoom = clamp(Math.min((cssW - FIT_PADDING * 2) / bw, (cssH - FIT_PADDING * 2) / bh), FIT_MIN_ZOOM, FIT_MAX_ZOOM)
    const cx = (b.minX + b.maxX) / 2
    const cy = (b.minY + b.maxY) / 2
    return { x: cssW / 2 - cx * zoom, y: cssH / 2 - cy * zoom, zoom: zoom }
  }

  function computeFit(animate) {
    if (!model || !model.nodes.length || !model.bounds) return
    if (cssW <= 1 || cssH <= 1) {
      pendingFit = true
      return
    }
    pendingFit = false
    const target = fitCameraTarget()
    if (!target) return
    animateCameraTo(target, animate ? 260 : 0)
  }

  // setGraph 的初始相机：小图直接整图 fit；大图不给总览（字会糊成 3–6px），
  // 而是 0.82 倍贴住第一列，其余靠拖拽/迷你地图/回放漫游。
  function initialCameraTarget() {
    const fit = fitCameraTarget()
    if (!fit) return null
    if (fit.zoom >= INITIAL_FIT_ZOOM) return fit
    let firstLeft = Infinity
    for (const node of model.nodes) {
      if (node && node.rect.x < firstLeft) firstLeft = node.rect.x
    }
    if (!Number.isFinite(firstLeft)) return fit
    const b = model.bounds
    const zoom = INITIAL_ZOOM
    const target = {
      x: INITIAL_LEFT_PADDING - firstLeft * zoom,
      y: cssH / 2 - ((b.minY + b.maxY) / 2) * zoom,
      zoom: zoom,
    }
    clampCamera(target)
    return target
  }

  function applyInitialCamera(animate) {
    if (!model || !model.nodes.length || !model.bounds) return
    if (cssW <= 1 || cssH <= 1) {
      pendingInitial = true
      return
    }
    pendingInitial = false
    const target = initialCameraTarget()
    if (!target) return
    animateCameraTo(target, animate ? 260 : 0)
  }

  function zoomAt(px, py, factor) {
    if (!Number.isFinite(factor) || factor <= 0) return
    const baseZoom = camTarget.zoom
    // 从 fit 的小倍率（< ZOOM_MIN）往回滚时下限跟随当前值，避免「一滚反而放大」。
    const nextZoom = clamp(baseZoom * factor, Math.min(ZOOM_MIN, baseZoom), ZOOM_MAX)
    if (Math.abs(nextZoom - baseZoom) < 1e-6) return
    // 指针锚定：缩放前后指针下的世界坐标不变。
    const wx = (px - camTarget.x) / baseZoom
    const wy = (py - camTarget.y) / baseZoom
    camTarget.x = px - wx * nextZoom
    camTarget.y = py - wy * nextZoom
    camTarget.zoom = nextZoom
    clampCamera(camTarget)
    camAnim = null
    camSmoothing = true
    touch()
  }

  // ── 模型构建（布局 + 字体截断 + 渐变色缓存）────────────────────────────────
  function toneColor(p, key, fallback) {
    const tones = p.tones || {}
    if (key && tones[key]) return tones[key]
    return fallback
  }

  function measure(text, font) {
    ctx.font = font
    try {
      return ctx.measureText(String(text)).width
    } catch (error) {
      return 0
    }
  }

  function fitText(text, maxWidth, font) {
    const value = String(text === null || text === undefined ? '' : text)
    if (!value || !Number.isFinite(maxWidth) || maxWidth <= 0) return ''
    if (measure(value, font) <= maxWidth) return value
    const chars = Array.from(value)
    const dots = '…'
    const dotsWidth = measure(dots, font)
    let lo = 0
    let hi = chars.length
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2)
      if (measure(chars.slice(0, mid).join(''), font) + dotsWidth <= maxWidth) lo = mid
      else hi = mid - 1
    }
    if (lo <= 0) return dots
    return chars.slice(0, lo).join('').replace(/[\s·，,、:：;；]+$/, '') + dots
  }

  function buildNodeMeta(p, node, idx, rect, col) {
    const accent = typeof node.accent === 'string' && node.accent ? node.accent : toneColor(p, 'feedback', p.text2)
    const glyph = node.glyph && GLYPHS[node.glyph] ? node.glyph : 'dot'
    const contentW = NODE_W - 32
    const titleX = rect.x + 47

    const rawMeta = String(node.meta === null || node.meta === undefined ? '' : node.meta)
    const stepMatch = /\bstep\s*(\d+)/i.exec(rawMeta)
    const stepLabel = stepMatch ? 'S' + stepMatch[1] : ''
    const stepNumber = stepMatch ? String(Number(stepMatch[1])) : ''
    // LOD 紧凑块的短标签：优先页面给的 label（20-model 的家族中文名），否则按 glyph 兜底。
    const rawLabel = typeof node.label === 'string' && node.label
      ? node.label
      : (GLYPH_LABELS[glyph] || '')
    const labelChars = Array.from(rawLabel)
    let lodLabel = (labelChars.length > 3 ? labelChars.slice(0, 2) : labelChars).join('')
    if (!lodLabel) lodLabel = Array.from(String(node.title || '')).slice(0, 2).join('')
    const metaText = stepMatch ? rawMeta.replace(/^\s*step\s*\d+\s*[·:：-]?\s*/i, '') : rawMeta
    const stepWidth = stepLabel ? measure(stepLabel, F_STEP) + 2 : 0
    const titleMax = rect.x + NODE_W - 14 - stepWidth - 8 - titleX
    const titleFit = fitText(node.title, titleMax, F_TITLE)
    const subtitleFit = fitText(node.subtitle, contentW, F_SUB)

    let badges = []
    if (Array.isArray(node.badges) && node.badges.length) {
      for (let i = 0; i < node.badges.length; i += 1) {
        const badge = node.badges[i] || {}
        const text = String(badge.text === null || badge.text === undefined ? '' : badge.text)
        if (!text) continue
        const tone = badge.tone === 'neutral' ? null : badge.tone
        const color = toneColor(p, tone, p.text2)
        const w = measure(text, F_BADGE) + 14
        badges.push({
          text: text,
          color: color,
          bg: p.alpha(color, 0.13),
          border: p.alpha(color, 0.3),
          w: w,
        })
      }
    }
    let badgeW = 0
    for (const badge of badges) badgeW += badge.w + 5
    if (badges.length) badgeW -= 5 // 最后不留尾 gap
    // 第三行要么放 badges、要么放 meta：84px 高的卡片没有第二行的余地，
    // 有 badges 时优先展示判决/证据量（标题与 step 已覆盖 meta 的信息）。
    while (badges.length && badgeW > contentW) {
      badgeW -= badges.pop().w + 5
    }
    const metaFit = badges.length ? '' : fitText(metaText, contentW, F_META)
    let badgeX = rect.x + 16
    for (const badge of badges) {
      badge.x = badgeX
      badgeX += badge.w + 5
    }

    const cardGrad = ctx.createLinearGradient(0, rect.y, 0, rect.y + rect.h)
    cardGrad.addColorStop(0, p.nodeBgTop)
    cardGrad.addColorStop(1, p.nodeBgBottom)
    const glowRadius = Math.max(rect.w, rect.h) * 0.62
    const glowGrad = ctx.createRadialGradient(
      rect.x + rect.w / 2, rect.y + rect.h / 2, 6,
      rect.x + rect.w / 2, rect.y + rect.h / 2, glowRadius,
    )
    glowGrad.addColorStop(0, p.alpha(accent, 0.22))
    glowGrad.addColorStop(0.5, p.alpha(accent, 0.06))
    glowGrad.addColorStop(1, p.alpha(accent, 0))

    return {
      idx: idx,
      rect: rect,
      col: col,
      role: node.role === 'user' ? 'user' : 'agent',
      accent: accent,
      glyph: glyph,
      title: titleFit,
      subtitle: subtitleFit,
      meta: metaFit,
      stepLabel: stepLabel,
      stepNumber: stepNumber,
      lodLabel: lodLabel,
      badges: badges,
      badgeW: badgeW,
      cardGrad: cardGrad,
      glowGrad: glowGrad,
      glowRadius: glowRadius,
      tint: node.emphasis === 'conclusion' ? p.alpha(accent, 0.05) : null,
      bar: p.alpha(accent, 0.92),
      borderBase: p.alpha(accent, 0.22),
      borderHover: p.alpha(accent, 0.5),
      borderSelected: p.alpha(accent, 0.85),
      iconBg: p.alpha(accent, 0.16),
      iconRing: p.alpha(accent, 0.3),
      iconColor: accent,
      delay: 0,
    }
  }

  function buildEdge(p, fromMeta, toMeta, kind, index, delay) {
    const s = fromMeta.rect
    const t = toMeta.rect
    let sx
    let sy
    let c1x
    let c1y
    let c2x
    let c2y
    let ex
    let ey
    let vertical = false
    if (fromMeta.col === toMeta.col) {
      // 同一 step 的相邻事件：页面会发同列边，画成竖向串珠（上一张卡底边中点 → 下一张卡顶边中点）。
      vertical = true
      const down = (t.y + t.h / 2) >= (s.y + s.h / 2)
      sx = s.x + s.w / 2
      sy = down ? s.y + s.h : s.y
      ex = t.x + t.w / 2
      ey = down ? t.y : t.y + t.h
      const mid = (sy + ey) / 2
      c1x = sx
      c1y = mid
      c2x = ex
      c2y = mid
    } else if (t.x + t.w / 2 < s.x + s.w / 2) {
      // 回指明：从两张卡的下方绕回，对应“回环/复述”这类反向关系。
      sx = s.x + s.w / 2
      sy = s.y + s.h
      ex = t.x + t.w / 2
      ey = t.y + t.h
      const base = Math.max(sy, ey) + 54
      c1x = sx
      c1y = base
      c2x = ex
      c2y = base
    } else {
      sx = s.x + s.w
      sy = s.y + s.h / 2
      ex = t.x
      ey = t.y + t.h / 2
      const dx = ex - sx
      const cp = Math.max(36, dx * 0.5)
      c1x = sx + cp
      c1y = sy
      c2x = ex - cp
      c2y = ey
    }
    const sampled = sampleCubic(sx, sy, c1x, c1y, c2x, c2y, ex, ey, 40)
    const gradBase = ctx.createLinearGradient(sx, sy, ex, ey)
    gradBase.addColorStop(0, p.alpha(fromMeta.accent, kind === 'return' ? 0.24 : 0.35))
    gradBase.addColorStop(1, p.alpha(toMeta.accent, kind === 'return' ? 0.14 : 0.2))
    const gradHot = ctx.createLinearGradient(sx, sy, ex, ey)
    gradHot.addColorStop(0, p.alpha(fromMeta.accent, 0.85))
    gradHot.addColorStop(1, p.alpha(toMeta.accent, 0.55))
    return {
      from: fromMeta.idx,
      to: toMeta.idx,
      kind: kind,
      sx: sx, sy: sy, c1x: c1x, c1y: c1y, c2x: c2x, c2y: c2y, ex: ex, ey: ey,
      points: sampled.points,
      cum: sampled.cum,
      length: sampled.length,
      gradBase: gradBase,
      gradHot: gradHot,
      particle: p.alpha(toMeta.accent, 0.5),
      dotFrom: p.alpha(fromMeta.accent, 0.6),
      dotTo: p.alpha(toMeta.accent, 0.6),
      vertical: vertical,
      phase: (index * 0.37 + 0.13) % 1,
      delay: delay,
    }
  }

  function buildModel(g, p) {
    const list = Array.isArray(g.nodes) ? g.nodes : []
    const rects = layout(g)
    const nodes = new Array(list.length)
    const colMap = new Map()
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity

    for (let i = 0; i < list.length; i += 1) {
      const node = list[i] || {}
      const idx = Number.isFinite(node.idx) && node.idx >= 0 && node.idx < list.length ? Math.floor(node.idx) : i
      const rect = rects[idx]
      if (!rect) continue
      const col = Number.isFinite(node.col) && node.col >= 0 ? Math.floor(node.col) : 0
      nodes[idx] = buildNodeMeta(p, node, idx, rect, col)
      if (!colMap.has(col)) colMap.set(col, [])
      colMap.get(col).push(idx)
      minX = Math.min(minX, rect.x)
      minY = Math.min(minY, rect.y)
      maxX = Math.max(maxX, rect.x + rect.w)
      maxY = Math.max(maxY, rect.y + rect.h)
    }

    const cols = Array.from(colMap.keys()).sort(function (a, b) { return a - b })
    const colRank = new Map()
    for (let i = 0; i < cols.length; i += 1) colRank.set(cols[i], i)
    const headerY = minY - 44
    const descByCol = new Map()
    const rawColumns = Array.isArray(g.columns) ? g.columns : []
    for (let i = 0; i < rawColumns.length; i += 1) {
      const desc = rawColumns[i] || {}
      if (Number.isFinite(desc.col)) descByCol.set(Math.floor(desc.col), desc)
    }

    const headers = []
    for (let i = 0; i < cols.length; i += 1) {
      const col = cols[i]
      const rank = colRank.get(col)
      const idxs = colMap.get(col).filter(function (idx) { return !!nodes[idx] })
      const desc = descByCol.get(col) || {}
      const firstNode = nodes[idxs[0]]
      const accent = typeof desc.accent === 'string' && desc.accent
        ? desc.accent
        : (firstNode ? firstNode.accent : p.accent)
      const step = Number.isFinite(desc.step) ? desc.step : col + 1
      const label = typeof desc.label === 'string' ? desc.label : ''
      const parallel = !!desc.parallel
      const count = Number.isFinite(desc.count) && desc.count > 0 ? Math.floor(desc.count) : idxs.length
      const labelW = label ? measure(label, F_HEAD) : 0
      const chipText = parallel ? '×' + count : ''
      const chipW = chipText ? measure(chipText, F_CHIP) + 14 : 0
      const badgeDiameter = 22
      let groupW = badgeDiameter
      if (labelW) groupW += 8 + labelW
      if (chipW) groupW += 8 + chipW
      const centerX = PAD_X + col * (NODE_W + COL_GAP) + NODE_W / 2
      let bottom = -Infinity
      for (const idx of idxs) bottom = Math.max(bottom, nodes[idx].rect.y + nodes[idx].rect.h)
      headers.push({
        col: col,
        cx: centerX,
        cy: headerY,
        left: centerX - groupW / 2,
        groupW: groupW,
        badgeR: badgeDiameter / 2,
        step: step,
        label: label,
        labelW: labelW,
        chipText: chipText,
        chipW: chipW,
        accent: accent,
        idxs: idxs,
        bottom: bottom + 26,
        delay: Math.min(rank * 60, 300),
      })
    }

    const rawEdges = Array.isArray(g.edges) ? g.edges : []
    const edgeStagger = rawEdges.length > 1 ? Math.min(24, 300 / (rawEdges.length - 1)) : 0
    const edges = []
    for (let i = 0; i < rawEdges.length; i += 1) {
      const edge = rawEdges[i] || {}
      const from = Number.isFinite(edge.from) ? Math.floor(edge.from) : -1
      const to = Number.isFinite(edge.to) ? Math.floor(edge.to) : -1
      const fromMeta = nodes[from]
      const toMeta = nodes[to]
      if (!fromMeta || !toMeta) continue
      const kind = edge.kind === 'return' ? 'return' : 'main'
      edges.push(buildEdge(p, fromMeta, toMeta, kind, edges.length, 400 + i * edgeStagger))
    }
    // 页面把同一 step 的相邻事件也连成边（DESIGN §4.3 的竖向串珠）：
    // 这些对交给边自己画，drawBeads 不再重复补一根。
    const connectorPairs = new Set()
    for (const edge of edges) {
      if (edge.vertical) connectorPairs.add(edge.from < edge.to ? edge.from + ':' + edge.to : edge.to + ':' + edge.from)
    }

    // 入场时间表：列头 60ms 递进、节点按列 70ms 递进、边最后生长，总长压到 900ms 内。
    let enterEnd = 0
    for (const header of headers) header.delay = Math.min(header.delay, 900 - 200)
    for (const node of nodes) {
      if (!node) continue
      const rank = colRank.get(node.col) || 0
      // 同列多节点按 lane 再错开 24ms：整列不要像一堵墙同时跳出来。
      const siblings = colMap.get(node.col) || []
      const laneRank = Math.max(0, siblings.indexOf(node.idx))
      node.delay = Math.min(60 + Math.min(rank * 70, 360) + Math.min(72, laneRank * 24), 900 - 260)
      enterEnd = Math.max(enterEnd, node.delay + 260)
    }
    for (const header of headers) enterEnd = Math.max(enterEnd, header.delay + 200)
    for (const edge of edges) enterEnd = Math.max(enterEnd, edge.delay + 240)

    const bounds = nodes.some(Boolean)
      ? {
          minX: minX - 72,
          maxX: maxX + 72,
          minY: headerY - 26,
          maxY: maxY + 36,
        }
      : null

    return {
      rects: rects,
      nodes: nodes,
      headers: headers,
      edges: edges,
      bounds: bounds,
      headerY: headerY,
      minNodeY: minY,
      connectorPairs: connectorPairs,
      enterAt: -1e9,
      enterTotal: clamp(Math.max(520, enterEnd), 520, 900),
    }
  }

  // ── 聚光相关性 ──────────────────────────────────────────────────────────────
  function focusIndex() {
    // replayFocus 只在回放模式下生效：退出回放后焦点回到普通选中，避免残留聚光。
    if (replay && replayFocus !== null && replayFocus !== undefined) return replayFocus
    return selected === null || selected === undefined ? -1 : selected
  }

  function ensureRelevance() {
    const focus = focusIndex()
    if (relevance.model === model && relevance.focus === focus) return
    const set = new Set()
    if (focus >= 0 && model) {
      set.add(focus)
      for (const edge of model.edges) {
        if (!edge) continue
        if (edge.from === focus) set.add(edge.to)
        if (edge.to === focus) set.add(edge.from)
      }
      const focusNode = model.nodes[focus]
      if (focusNode) {
        for (const other of model.nodes) {
          if (other && other.col === focusNode.col) set.add(other.idx)
        }
      }
    }
    relevance = { model: model, focus: focus, nodes: focus >= 0 ? set : null }
  }

  function isRelevant(idx) {
    return !relevance.nodes || relevance.nodes.has(idx)
  }

  function edgeState(edge) {
    if (hovered !== null && (edge.from === hovered || edge.to === hovered)) return 'hot'
    const focus = focusIndex()
    if (focus >= 0 && (edge.from === focus || edge.to === focus)) return 'hot'
    if (isRelevant(edge.from) && isRelevant(edge.to)) return 'warm'
    return 'normal'
  }

  // ── 渲染 ────────────────────────────────────────────────────────────────────
  function enterProgress(t, enterAt, delay, duration) {
    if (enterAt <= -1e8) return 1
    return clamp((t - enterAt - delay) / duration, 0, 1)
  }

  function hoverValue(idx) {
    const entry = hoverLevels.get(idx)
    return entry ? entry.value : 0
  }

  function updateHover(dt) {
    if (hoverLevels.size === 0) return
    const step = prefersReduced() ? 1 : dt / 140
    hoverLevels.forEach(function (entry, idx) {
      const target = idx === hovered ? 1 : 0
      entry.value += clamp(target - entry.value, -step, step)
      if (target === 0 && entry.value < 0.02) hoverLevels.delete(idx)
    })
  }

  function updateSpotlight(dt) {
    if (prefersReduced()) {
      spotlight = spotlightTarget
      return
    }
    spotlight += clamp(spotlightTarget - spotlight, -dt / 220, dt / 220)
  }

  function focusPulse(t) {
    if (prefersReduced()) return 0.5
    const elapsed = t - focusPulseAt
    if (elapsed >= 1100) return 0.45
    if (elapsed < 0) return 0.45
    const k = elapsed / 1100
    // 两次脉冲（周期 550ms），随后降到常驻亮度。
    const wave = Math.abs(Math.sin((elapsed / 550) * Math.PI))
    return 0.35 + 0.55 * wave * (1 - k)
  }

  function drawGrid(p) {
    const ox = ((camera.x % GRID_SPACING) + GRID_SPACING) % GRID_SPACING
    const oy = ((camera.y % GRID_SPACING) + GRID_SPACING) % GRID_SPACING
    const size = 1.6
    ctx.fillStyle = p.grid
    for (let x = ox - GRID_SPACING; x <= cssW + GRID_SPACING; x += GRID_SPACING) {
      for (let y = oy - GRID_SPACING; y <= cssH + GRID_SPACING; y += GRID_SPACING) {
        ctx.fillRect(x - size / 2, y - size / 2, size, size)
      }
    }
  }

  function drawVignette(p) {
    const radius = Math.max(cssW, cssH) * 0.72
    const grad = ctx.createRadialGradient(cssW * 0.5, cssH * 0.42, 0, cssW * 0.5, cssH * 0.42, radius)
    grad.addColorStop(0, p.alpha(p.accent, p.mode === 'dark' ? 0.06 : 0.028))
    grad.addColorStop(0.55, p.alpha(p.accent, p.mode === 'dark' ? 0.02 : 0.008))
    grad.addColorStop(1, p.alpha(p.accent, 0))
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, cssW, cssH)
    // 底部渐晕：主题模块若提供 introBg 就轻轻压一层，让回放条/图例有落点。
    if (typeof p.introBg === 'string') {
      const bottom = ctx.createLinearGradient(0, cssH - 160, 0, cssH)
      bottom.addColorStop(0, p.alpha(p.introBg, 0))
      bottom.addColorStop(1, p.alpha(p.introBg, 0.55))
      ctx.fillStyle = bottom
      ctx.fillRect(0, cssH - 160, cssW, 160)
    }
  }

  function drawEmpty(p) {
    const cx = cssW / 2
    const cy = cssH / 2
    ctx.save()
    ctx.globalAlpha = 1
    ctx.setLineDash([4, 6])
    ctx.strokeStyle = p.alpha(p.accent, 0.35)
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(cx, cy - 44, 26, 0, Math.PI * 2)
    ctx.stroke()
    ctx.setLineDash([])
    strokeGlyph(ctx, 'spark', cx, cy - 44, 22, p.alpha(p.accent, 0.55))
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.font = F_EMPTY_TITLE
    ctx.fillStyle = p.text2
    ctx.fillText('没有可绘制的轨迹', cx, cy + 6)
    const sub = measure('选择左侧会话，或先跑一次诊断', F_EMPTY_SUB) > cssW - 40
      ? '选择左侧会话查看诊断路径'
      : '选择左侧会话，或先跑一次诊断'
    ctx.font = F_EMPTY_SUB
    ctx.fillStyle = p.text3
    ctx.fillText(sub, cx, cy + 28)
    ctx.textAlign = 'left'
    ctx.restore()
  }

  // 列头在正常倍率与低倍率下的两套几何：低倍率把字号/圆标/间距按 1/zoom 反缩放，
  // 并把列头抬到节点上方约 28 屏幕 px（正常倍率是 44 世界 px，阈值处过渡连续）。
  function headerGeom(m, header, allowChip) {
    if (camera.zoom >= LOD_ZOOM) {
      return {
        compact: false,
        cy: header.cy,
        left: header.left,
        badgeR: header.badgeR,
        labelText: header.label,
        showChip: !!header.chipText,
        labelW: header.labelW,
        chipW: header.chipW,
        labelFont: F_HEAD,
        chipFont: F_CHIP,
        numFont: F_HEAD_NUM,
        pillH: 16,
        gap: 8,
        slide: 6,
        unit: 1,
      }
    }
    const inv = 1 / camera.zoom
    const badgeR = 9 * inv
    const gap = 4 * inv
    const labelFont = '600 ' + (11 * inv) + 'px ' + FONT_STACK
    let labelText = header.label
    let labelW = labelText ? measure(labelText, labelFont) : 0
    const chipFont = '600 ' + (9 * inv) + 'px ' + MONO_STACK
    let showChip = !!header.chipText && allowChip !== false
    let chipW = showChip ? measure(header.chipText, chipFont) + 8 * inv : 0
    let groupW = badgeR * 2
    if (labelW) groupW += gap + labelW
    if (showChip) groupW += gap + chipW
    // 列间距是 324 世界 px。低倍率下字号被反缩放，一行列头可能比列还宽：
    // 先丢 ×N chip，再截短 label，保证相邻列头不叠在一起。
    const columnSpacing = NODE_W + COL_GAP
    if (showChip && groupW + 8 * inv > columnSpacing) {
      showChip = false
      chipW = 0
      groupW = badgeR * 2 + (labelW ? gap + labelW : 0)
    }
    if (labelW && groupW + 6 * inv > columnSpacing) {
      const available = columnSpacing - 6 * inv - badgeR * 2 - gap
      labelText = available > 0 ? fitText(header.label, available, labelFont) : ''
      labelW = labelText ? measure(labelText, labelFont) : 0
      groupW = badgeR * 2 + (labelW ? gap + labelW : 0)
    }
    return {
      compact: true,
      cy: m.minNodeY - 28 * inv,
      left: header.cx - groupW / 2,
      badgeR: badgeR,
      labelText: labelText,
      showChip: showChip,
      labelW: labelW,
      chipW: chipW,
      labelFont: labelFont,
      chipFont: chipFont,
      numFont: '600 ' + (10 * inv) + 'px ' + MONO_STACK,
      pillH: 13 * inv,
      gap: gap,
      slide: 6 * inv,
      unit: inv,
    }
  }

  function drawGuides(m, t, alphaScale) {
    for (const header of m.headers) {
      const prog = enterProgress(t, m.enterAt, header.delay, 200)
      if (prog <= 0) continue
      const geom = headerGeom(m, header)
      const inv = geom.unit
      const spotDim = header.idxs.some(isRelevant) ? 1 : 1 - spotlight * (1 - 0.45)
      ctx.save()
      ctx.globalAlpha = easeOutCubic(prog) * alphaScale * spotDim
      ctx.strokeStyle = palette.alpha(header.accent, 0.2)
      ctx.lineWidth = 1 * inv
      ctx.setLineDash([4 * inv, 7 * inv])
      ctx.beginPath()
      ctx.moveTo(header.cx, geom.cy + geom.badgeR + 2 * inv)
      ctx.lineTo(header.cx, header.bottom)
      ctx.stroke()
      ctx.restore()
    }
    ctx.setLineDash([])
  }

  function drawBeads(m, t, alphaScale) {
    const compact = camera.zoom < LOD_ZOOM
    const inv = compact ? 1 / camera.zoom : 1
    for (const header of m.headers) {
      const prog = enterProgress(t, m.enterAt, header.delay, 200)
      if (prog <= 0) continue
      const idxs = header.idxs.slice().sort(function (a, b) {
        return m.nodes[a].rect.y - m.nodes[b].rect.y
      })
      for (let i = 0; i + 1 < idxs.length; i += 1) {
        const a = m.nodes[idxs[i]].rect
        const b = m.nodes[idxs[i + 1]].rect
        const pairKey = idxs[i] < idxs[i + 1] ? idxs[i] + ':' + idxs[i + 1] : idxs[i + 1] + ':' + idxs[i]
        if (m.connectorPairs.has(pairKey)) continue
        const y1 = a.y + a.h + 2 * inv
        const y2 = b.y - 2 * inv
        if (y2 <= y1) continue
        const dim = (isRelevant(idxs[i]) && isRelevant(idxs[i + 1])) ? 1 : 1 - spotlight * (1 - DIM_ALPHA)
        ctx.save()
        ctx.globalAlpha = easeOutCubic(prog) * alphaScale * dim
        ctx.strokeStyle = palette.alpha(header.accent, 0.2)
        ctx.lineWidth = 1 * inv
        ctx.beginPath()
        ctx.moveTo(header.cx, y1)
        ctx.lineTo(header.cx, y2)
        ctx.stroke()
        // 一颗珠子，避免整条竖线只有线没有节奏。
        ctx.fillStyle = palette.alpha(header.accent, 0.45)
        ctx.beginPath()
        ctx.arc(header.cx, (y1 + y2) / 2, 1.6 * inv, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
      }
    }
  }

  function drawHeaders(m, t, alphaScale) {
    const compact = camera.zoom < LOD_ZOOM
    // 低倍率下列头字号是反缩放的，×N chip 可能放不下。统一显示或统一隐藏，
    // 避免同一行列头「有的有 ×N、有的没有」看起来像数据不一致。
    let chipsAllowed = true
    if (compact) {
      const inv = 1 / camera.zoom
      const badgeR = 9 * inv
      const gap = 4 * inv
      const labelFont = '600 ' + (11 * inv) + 'px ' + FONT_STACK
      const chipFont = '600 ' + (9 * inv) + 'px ' + MONO_STACK
      for (const header of m.headers) {
        if (!header.chipText) continue
        const labelW = header.label ? measure(header.label, labelFont) : 0
        const chipW = measure(header.chipText, chipFont) + 8 * inv
        let groupW = badgeR * 2 + (labelW ? gap + labelW : 0) + gap + chipW
        if (groupW + 8 * inv > NODE_W + COL_GAP) {
          chipsAllowed = false
          break
        }
      }
    }
    for (const header of m.headers) {
      const prog = enterProgress(t, m.enterAt, header.delay, 200)
      if (prog <= 0) continue
      const ease = easeOutCubic(prog)
      const geom = headerGeom(m, header, chipsAllowed)
      const inv = geom.unit
      const spotDim = header.idxs.some(isRelevant) ? 1 : 1 - spotlight * (1 - 0.45)
      ctx.save()
      ctx.globalAlpha = ease * alphaScale * spotDim
      ctx.translate(0, (1 - ease) * -geom.slide)

      const badgeCx = geom.left + geom.badgeR
      ctx.beginPath()
      ctx.arc(badgeCx, geom.cy, geom.badgeR, 0, Math.PI * 2)
      ctx.fillStyle = palette.alpha(header.accent, 0.14)
      ctx.fill()
      ctx.strokeStyle = palette.alpha(header.accent, 0.55)
      ctx.lineWidth = 1 * inv
      ctx.stroke()
      ctx.font = geom.numFont
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = header.accent
      ctx.fillText(String(header.step), badgeCx, geom.cy + 0.5 * inv)

      let cursor = geom.left + geom.badgeR * 2
      if (geom.labelW && geom.labelText) {
        cursor += geom.gap
        ctx.font = geom.labelFont
        ctx.textAlign = 'left'
        ctx.fillStyle = palette.text
        ctx.fillText(geom.labelText, cursor, geom.cy + 0.5 * inv)
        cursor += geom.labelW
      }
      if (geom.showChip && geom.chipW) {
        cursor += geom.gap
        roundRectPath(ctx, cursor, geom.cy - geom.pillH / 2, geom.chipW, geom.pillH, geom.pillH / 2)
        ctx.fillStyle = palette.alpha(header.accent, 0.1)
        ctx.fill()
        ctx.strokeStyle = palette.alpha(header.accent, 0.3)
        ctx.lineWidth = 1 * inv
        ctx.stroke()
        ctx.font = geom.chipFont
        ctx.textAlign = 'center'
        ctx.fillStyle = palette.alpha(header.accent, 0.95)
        ctx.fillText(header.chipText, cursor + geom.chipW / 2, geom.cy + 0.5 * inv)
      }
      ctx.restore()
    }
    ctx.textAlign = 'left'
  }

  function strokePartial(edge, progress) {
    const target = edge.length * progress
    const points = edge.points
    const cum = edge.cum
    ctx.beginPath()
    ctx.moveTo(points[0].x, points[0].y)
    for (let i = 1; i < points.length; i += 1) {
      if (cum[i] <= target) {
        ctx.lineTo(points[i].x, points[i].y)
      } else {
        const prevCum = cum[i - 1]
        const segment = cum[i] - prevCum
        const f = segment > 0 ? (target - prevCum) / segment : 0
        ctx.lineTo(
          points[i - 1].x + (points[i].x - points[i - 1].x) * f,
          points[i - 1].y + (points[i].y - points[i - 1].y) * f,
        )
        break
      }
    }
    ctx.stroke()
  }

  function pointAt(edge, t) {
    const target = edge.length * clamp(t, 0, 1)
    const cum = edge.cum
    let lo = 0
    let hi = cum.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (cum[mid] < target) lo = mid + 1
      else hi = mid
    }
    const i = Math.max(1, lo)
    const segment = cum[i] - cum[i - 1]
    const f = segment > 0 ? clamp((target - cum[i - 1]) / segment, 0, 1) : 0
    const a = edge.points[i - 1]
    const b = edge.points[i]
    return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f }
  }

  function drawEdges(m, t, alphaScale, outgoingFrame) {
    for (const edge of m.edges) {
      const prog = enterProgress(t, m.enterAt, edge.delay, 240)
      if (prog <= 0) continue
      const state = edgeState(edge)
      const dim = state === 'normal' ? 1 - spotlight * (1 - DIM_ALPHA) : 1
      const inv = 1 / camera.zoom
      const baseWidth = edge.vertical
        ? (state === 'hot' ? 1.8 : 1.2)
        : (state === 'hot' ? 2.2 : (edge.kind === 'return' ? 1.3 : 1.6))
      ctx.save()
      ctx.globalAlpha = easeOutCubic(prog) * alphaScale * dim
      ctx.strokeStyle = state === 'hot' ? edge.gradHot : edge.gradBase
      // 线宽保持至少 ~0.9 屏幕 px：总览（zoom 0.24）时 1.6 世界 px 只剩 0.38px，边会消失。
      ctx.lineWidth = Math.max(baseWidth, (state === 'hot' ? 1.2 : 0.9) * inv)
      ctx.lineCap = 'round'
      ctx.setLineDash(edge.kind === 'return' ? [5.5 * inv, 5.5 * inv] : [])
      if (prog < 1) {
        strokePartial(edge, easeOutCubic(prog))
      } else {
        ctx.beginPath()
        ctx.moveTo(edge.sx, edge.sy)
        ctx.bezierCurveTo(edge.c1x, edge.c1y, edge.c2x, edge.c2y, edge.ex, edge.ey)
        ctx.stroke()
        if (edge.vertical) {
          // 串珠两端的小圆点：让“上一张卡 → 下一张卡”的读法更明确。
          const dotR = Math.max(1.5, 1.3 * inv)
          ctx.fillStyle = edge.dotFrom
          ctx.beginPath()
          ctx.arc(edge.sx, edge.sy, dotR, 0, Math.PI * 2)
          ctx.fill()
          ctx.fillStyle = edge.dotTo
          ctx.beginPath()
          ctx.arc(edge.ex, edge.ey, dotR, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      ctx.restore()
    }
    ctx.setLineDash([])
  }

  function drawParticles(m, t, alphaScale, outgoingFrame) {
    if (outgoingFrame || prefersReduced()) return
    // 空闲一段时间后冻结粒子：既省电，也让静止画面不再有东西在动。
    if (t - lastInteraction > IDLE_AFTER) return
    const scale = 1 / camera.zoom
    for (const edge of m.edges) {
      if (edge.kind !== 'main' || edge.vertical) continue
      if (enterProgress(t, m.enterAt, edge.delay, 240) < 1) continue
      const local = ((t - m.enterAt) / PARTICLE_PERIOD + edge.phase) % 1
      const fade = Math.sin(Math.PI * local)
      if (fade <= 0.02) continue
      const state = edgeState(edge)
      const dim = state === 'normal' ? 1 - spotlight * (1 - DIM_ALPHA) : 1
      const point = pointAt(edge, local)
      const dotR = 1.1 * scale
      ctx.save()
      ctx.globalAlpha = 0.14 * fade * dim * alphaScale
      ctx.fillStyle = edge.particle
      ctx.beginPath()
      ctx.arc(point.x, point.y, dotR * 2.6, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalAlpha = 0.5 * fade * dim * alphaScale
      ctx.beginPath()
      ctx.arc(point.x, point.y, dotR, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }
  }

  // 选中光晕单独先画一遍：卡片随后覆盖在上面，光晕不会糊到相邻节点上。
  function drawFocusGlow(m, t, alphaScale) {
    const focus = focusIndex()
    if (focus < 0) return
    const node = m.nodes[focus]
    if (!node) return
    const prog = enterProgress(t, m.enterAt, node.delay, 260)
    if (prog <= 0) return
    const ease = easeOutCubic(prog)
    const dim = isRelevant(focus) ? 1 : 1 - spotlight * (1 - DIM_ALPHA)
    const alpha = ease * alphaScale * dim
    if (alpha <= 0.01) return
    const hover = hoverValue(focus)
    const lift = hover * 1.5
    const rect = node.rect
    const cx = rect.x + rect.w / 2
    const cy = rect.y + rect.h / 2 - lift
    const scale = 0.94 + 0.06 * ease
    const pulse = focusPulse(t)
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(scale, scale)
    ctx.translate(-cx, -cy)
    ctx.globalAlpha = alpha * (0.35 + 0.65 * pulse)
    if (camera.zoom < LOD_ZOOM) {
      // 低倍率下缓存的光晕按世界尺寸会缩得太小，改用屏幕恒定半径重新算一个。
      const inv = 1 / camera.zoom
      const radius = 38 * inv
      const glow = ctx.createRadialGradient(cx, cy, 2 * inv, cx, cy, radius)
      glow.addColorStop(0, palette.alpha(node.accent, 0.3))
      glow.addColorStop(1, palette.alpha(node.accent, 0))
      ctx.fillStyle = glow
      ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2)
    } else {
      ctx.fillStyle = node.glowGrad
      ctx.fillRect(cx - node.glowRadius, cy - node.glowRadius, node.glowRadius * 2, node.glowRadius * 2)
    }
    ctx.restore()
  }

  // 正常倍率：完整卡（标题/副文/meta 或 badges）。
  function drawNodeFull(node, lift, alpha, hover, isFocus, ease) {
    const rect = node.rect
    const cx = rect.x + rect.w / 2
    const cy = rect.y + rect.h / 2 - lift
    const scale = 0.94 + 0.06 * ease

    ctx.save()
    // 入场缩放以卡片中心为原点；hover 上浮只动 y，不放大。
    ctx.translate(cx, cy)
    ctx.scale(scale, scale)
    ctx.translate(-cx, -cy)
    ctx.globalAlpha = alpha

    const y = rect.y - lift
    roundRectPath(ctx, rect.x, y, rect.w, rect.h, 14)
    if (hover > 0.02 || isFocus) {
      ctx.shadowColor = palette.shadow
      ctx.shadowBlur = isFocus ? 18 : 8 + 6 * hover
      ctx.shadowOffsetY = isFocus ? 5 : 2
    }
    ctx.fillStyle = node.cardGrad
    ctx.fill()
    ctx.shadowColor = 'transparent'
    ctx.shadowBlur = 0
    ctx.shadowOffsetY = 0
    if (node.tint) {
      ctx.fillStyle = node.tint
      ctx.fill()
    }

    // 左侧 3px 色条（宽度正好落在卡片左侧的直边上，不压圆角）。
    roundRectPath(ctx, rect.x + 1, y + 9, 3, rect.h - 18, 1.5)
    ctx.fillStyle = node.bar
    ctx.fill()

    ctx.beginPath()
    ctx.arc(rect.x + 26, y + 24, 12, 0, Math.PI * 2)
    ctx.fillStyle = node.iconBg
    ctx.fill()
    ctx.strokeStyle = node.iconRing
    ctx.lineWidth = 1
    ctx.stroke()
    strokeGlyph(ctx, node.glyph, rect.x + 26, y + 24, 15, node.iconColor)

    ctx.textBaseline = 'middle'
    ctx.font = F_TITLE
    ctx.fillStyle = palette.text
    ctx.textAlign = 'left'
    ctx.fillText(node.title, rect.x + 47, y + 24)

    if (node.stepLabel) {
      ctx.font = F_STEP
      ctx.fillStyle = palette.text3
      ctx.textAlign = 'right'
      ctx.fillText(node.stepLabel, rect.x + rect.w - 14, y + 23)
      ctx.textAlign = 'left'
    }

    if (node.subtitle) {
      ctx.font = F_SUB
      ctx.fillStyle = palette.text2
      ctx.fillText(node.subtitle, rect.x + 16, y + 44)
    }

    const bottomCenter = y + rect.h - 18
    if (node.meta) {
      ctx.font = F_META
      ctx.fillStyle = palette.text3
      ctx.fillText(node.meta, rect.x + 16, bottomCenter)
    }
    for (const badge of node.badges) {
      roundRectPath(ctx, badge.x, bottomCenter - 8, badge.w, 16, 8)
      ctx.fillStyle = badge.bg
      ctx.fill()
      ctx.strokeStyle = badge.border
      ctx.lineWidth = 1
      ctx.stroke()
      ctx.font = F_BADGE
      ctx.textAlign = 'center'
      ctx.fillStyle = badge.color
      ctx.fillText(badge.text, badge.x + badge.w / 2, bottomCenter + 0.5)
      ctx.textAlign = 'left'
    }

    roundRectPath(ctx, rect.x + 0.75, y + 0.75, rect.w - 1.5, rect.h - 1.5, 13.5)
    ctx.strokeStyle = isFocus ? node.borderSelected : (hover > 0.05 ? node.borderHover : node.borderBase)
    ctx.lineWidth = isFocus ? 1.5 : 1
    ctx.stroke()

    ctx.restore()
  }

  // 低倍率（< LOD_ZOOM）：不画缩小后的糊字，改画「紧凑块」——
  // 圆角块 + accent 色条 + 图标 + 家族短标签 + step 数字；字号/图标/描边按 1/zoom 反缩放，
  // 这样总览时它们仍是屏幕上的 10–11px，像一张有标注的地图。
  function drawNodeCompact(node, lift, alpha, hover, isFocus, ease) {
    const z = camera.zoom
    const inv = 1 / z
    const rect = node.rect
    const screenW = rect.w * z
    const screenH = rect.h * z
    const y = rect.y - lift
    const cx = rect.x + rect.w / 2
    const cy = rect.y + rect.h / 2 - lift
    const scale = 0.94 + 0.06 * ease

    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(scale, scale)
    ctx.translate(-cx, -cy)
    ctx.globalAlpha = alpha

    const screenRadius = Math.min(9, screenH * 0.32, screenW * 0.2)
    const radius = Math.max(1, screenRadius) * inv
    roundRectPath(ctx, rect.x, y, rect.w, rect.h, radius)
    ctx.fillStyle = node.cardGrad
    ctx.fill()
    if (node.tint) {
      ctx.fillStyle = node.tint
      ctx.fill()
    }

    const barW = Math.max(1.5, Math.min(3, screenH * 0.22)) * inv
    roundRectPath(ctx, rect.x + 1.5 * inv, y + 5 * inv, barW, rect.h - 10 * inv, barW / 2)
    ctx.fillStyle = node.bar
    ctx.fill()

    let cursor = rect.x + 7 * inv
    // 极窄的块（fit 总览里约 56px 宽）放不下图标，只留色条 + 标签 + step。
    const showIcon = screenW >= 88 && screenH >= 26
    if (showIcon) {
      const iconDiameter = Math.min(20, screenH - 10)
      const iconR = (iconDiameter / 2) * inv
      const iconCx = cursor + iconR
      ctx.beginPath()
      ctx.arc(iconCx, cy, iconR, 0, Math.PI * 2)
      ctx.fillStyle = node.iconBg
      ctx.fill()
      ctx.strokeStyle = node.iconRing
      ctx.lineWidth = 1 * inv
      ctx.stroke()
      strokeGlyph(ctx, node.glyph, iconCx, cy, Math.max(8, iconDiameter * 0.62) * inv, node.iconColor)
      cursor += iconDiameter * inv + 5 * inv
    }

    ctx.textBaseline = 'middle'
    let stepWidth = 0
    if (node.stepNumber) {
      const stepFont = '600 ' + (10 * inv) + 'px ' + MONO_STACK
      stepWidth = measure(node.stepNumber, stepFont) + 6 * inv
      ctx.font = stepFont
      ctx.fillStyle = palette.text3
      ctx.textAlign = 'right'
      ctx.fillText(node.stepNumber, rect.x + rect.w - 7 * inv, cy + 0.5 * inv)
      ctx.textAlign = 'left'
    }

    const labelMax = rect.w - (cursor - rect.x) - stepWidth - 2 * inv
    if (node.lodLabel && labelMax > 8 * inv) {
      const labelFont = '600 ' + (11 * inv) + 'px ' + FONT_STACK
      ctx.font = labelFont
      ctx.fillStyle = palette.text
      const label = fitText(node.lodLabel, labelMax, labelFont)
      ctx.fillText(label, cursor, cy + 0.5 * inv)
    }

    roundRectPath(ctx, rect.x + 0.5 * inv, y + 0.5 * inv, rect.w - inv, rect.h - inv, radius)
    ctx.strokeStyle = isFocus ? node.borderSelected : (hover > 0.05 ? node.borderHover : node.borderBase)
    ctx.lineWidth = (isFocus ? 1.5 : hover > 0.05 ? 1.1 : 0.8) * inv
    ctx.stroke()

    ctx.restore()
  }

  function drawNodes(m, t, alphaScale) {
    const focus = focusIndex()
    drawFocusGlow(m, t, alphaScale)
    const compact = camera.zoom < LOD_ZOOM
    for (let i = 0; i < m.nodes.length; i += 1) {
      const node = m.nodes[i]
      if (!node) continue
      const prog = enterProgress(t, m.enterAt, node.delay, 260)
      if (prog <= 0) continue
      const ease = easeOutCubic(prog)
      const dim = isRelevant(node.idx) ? 1 : 1 - spotlight * (1 - DIM_ALPHA)
      const alpha = ease * alphaScale * dim
      if (alpha <= 0.01) continue
      const hover = hoverValue(node.idx)
      const lift = hover * 1.5
      const isFocus = node.idx === focus
      if (compact) drawNodeCompact(node, lift, alpha, hover, isFocus, ease)
      else drawNodeFull(node, lift, alpha, hover, isFocus, ease)
    }
  }

  function drawModel(m, t, alphaScale, outgoingFrame) {
    if (!m || !m.nodes.length) return
    drawGuides(m, t, alphaScale)
    drawBeads(m, t, alphaScale)
    drawEdges(m, t, alphaScale, outgoingFrame)
    drawParticles(m, t, alphaScale, outgoingFrame)
    drawNodes(m, t, alphaScale)
    drawHeaders(m, t, alphaScale)
  }

  function minimapFits() {
    return cssW >= MINIMAP_MIN_W && cssH >= MINIMAP_MIN_H
  }

  function minimapPanel() {
    if (!model || !model.nodes.length) return null
    // 窄画布下迷你地图会压住节点，直接不画（页面底部缩放钮仍可用）。
    if (!minimapFits()) return null
    const x = cssW - MINIMAP_W - MINIMAP_MARGIN
    const y = cssH - MINIMAP_H - MINIMAP_MARGIN
    if (x < 8 || y < 8) return null
    return {
      x: x,
      y: y,
      w: MINIMAP_W,
      h: MINIMAP_H,
      inner: {
        x: x + MINIMAP_PAD,
        y: y + MINIMAP_PAD,
        w: MINIMAP_W - MINIMAP_PAD * 2,
        h: MINIMAP_H - MINIMAP_PAD * 2,
      },
    }
  }

  function minimapMap(panel) {
    const b = model.bounds
    const bw = Math.max(1, b.maxX - b.minX)
    const bh = Math.max(1, b.maxY - b.minY)
    const scale = Math.min(panel.inner.w / bw, panel.inner.h / bh)
    return {
      scale: scale,
      ox: panel.inner.x + (panel.inner.w - bw * scale) / 2,
      oy: panel.inner.y + (panel.inner.h - bh * scale) / 2,
    }
  }

  function drawMinimap(p) {
    const panel = minimapPanel()
    if (!panel) return
    const b = model.bounds
    const map = minimapMap(panel)

    const pointer = pointerScreen
    const overPanel = pointer !== null && pointer !== undefined
      && pointInRect(pointer.x, pointer.y, panel)
    ctx.save()
    ctx.globalAlpha = overPanel ? 0.98 : MINIMAP_IDLE_ALPHA
    roundRectPath(ctx, panel.x, panel.y, panel.w, panel.h, 12)
    ctx.fillStyle = p.overlay
    ctx.fill()
    ctx.strokeStyle = p.border
    ctx.lineWidth = 1
    ctx.stroke()

    roundRectPath(ctx, panel.x + 1, panel.y + 1, panel.w - 2, panel.h - 2, 11)
    ctx.clip()

    const focus = focusIndex()
    for (let i = 0; i < model.nodes.length; i += 1) {
      const node = model.nodes[i]
      if (!node) continue
      const rel = isRelevant(node.idx)
      const dim = rel ? 1 : 1 - spotlight * (1 - DIM_ALPHA)
      const rect = node.rect
      const x = map.ox + (rect.x - b.minX) * map.scale
      const y = map.oy + (rect.y - b.minY) * map.scale
      const w = Math.max(2.5, rect.w * map.scale)
      const h = Math.max(2, rect.h * map.scale)
      ctx.fillStyle = p.alpha(node.accent, (node.idx === focus ? 0.95 : 0.62) * dim)
      ctx.fillRect(x, y, w, h)
    }

    // 当前视口框：映射到缩略图，边缘超出面板时贴边收缩。
    const worldLeft = -camera.x / camera.zoom
    const worldTop = -camera.y / camera.zoom
    const worldW = cssW / camera.zoom
    const worldH = cssH / camera.zoom
    let vx = map.ox + (worldLeft - b.minX) * map.scale
    let vy = map.oy + (worldTop - b.minY) * map.scale
    let vw = worldW * map.scale
    let vh = worldH * map.scale
    const right = panel.inner.x + panel.inner.w
    const bottom = panel.inner.y + panel.inner.h
    if (vx < panel.inner.x) {
      const cut = panel.inner.x - vx
      vx = panel.inner.x
      vw -= cut
    }
    if (vy < panel.inner.y) {
      const cut = panel.inner.y - vy
      vy = panel.inner.y
      vh -= cut
    }
    if (vx + vw > right) vw = right - vx
    if (vy + vh > bottom) vh = bottom - vy
    vw = Math.max(6, vw)
    vh = Math.max(6, vh)
    roundRectPath(ctx, vx, vy, vw, vh, 3)
    ctx.fillStyle = p.alpha(p.accent, 0.08)
    ctx.fill()
    ctx.strokeStyle = p.alpha(p.accent, 0.85)
    ctx.lineWidth = 1.2
    ctx.stroke()
    ctx.restore()
  }

  function draw(t, dt) {
    const p = palette
    if (!p) return
    updateHover(dt)
    updateSpotlight(dt)
    updateCamera(t, dt)

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cssW, cssH)
    ctx.fillStyle = p.surface
    ctx.fillRect(0, 0, cssW, cssH)
    drawGrid(p)
    drawVignette(p)

    if (!model || !model.nodes.length) {
      drawEmpty(p)
      return
    }
    ensureRelevance()

    ctx.save()
    ctx.translate(camera.x, camera.y)
    ctx.scale(camera.zoom, camera.zoom)
    if (outgoing) {
      const progress = clamp((t - outgoing.at) / outgoing.dur, 0, 1)
      if (progress >= 1) outgoing = null
      else drawModel(outgoing.model, t, 1 - progress, true)
    }
    drawModel(model, t, 1, false)
    ctx.restore()

    drawMinimap(p)
  }

  // ── 循环 ────────────────────────────────────────────────────────────────────
  function isActive(t) {
    if (model && !prefersReduced() && t - lastInteraction <= IDLE_AFTER) return true
    if (outgoing) return true
    if (model && t - model.enterAt < model.enterTotal) return true
    if (camAnim) return true
    if (camSmoothing &&
      (Math.abs(camTarget.x - camera.x) >= 0.4 || Math.abs(camTarget.y - camera.y) >= 0.4 ||
        Math.abs(camTarget.zoom - camera.zoom) >= 0.0015)) return true
    if (spotlight !== spotlightTarget) return true
    if (focusIndex() >= 0 && t - focusPulseAt < 1100) return true
    if (hoverLevels.size) {
      let moving = false
      hoverLevels.forEach(function (entry, idx) {
        if (Math.abs(entry.value - (idx === hovered ? 1 : 0)) > 0.01) moving = true
      })
      if (moving) return true
    }
    return false
  }

  function frame(ts) {
    if (dead) return
    rafId = requestAnimationFrame(frame)
    const t = typeof ts === 'number' ? ts : nowMs()
    if (typeof document !== 'undefined' && document && document.hidden) {
      lastFrameAt = t
      return
    }

    // 主题切换：颜色真的变了才重算着色缓存，且不重播入场动画。
    const nextPalette = getPalette()
    if (nextPalette) {
      palette = nextPalette
      const nextSig = paletteSignature(nextPalette)
      if (nextSig !== paletteSig) {
        paletteSig = nextSig
        if (model) {
          const enterAt = model.enterAt
          model = buildModel(graph, palette)
          model.enterAt = enterAt
        }
        if (outgoing) {
          const oldEnter = outgoing.model.enterAt
          outgoing.model = buildModel(outgoing.graph, palette)
          outgoing.model.enterAt = oldEnter
        }
        dirty = true
      }
    }

    const dt = lastFrameAt ? Math.min(64, t - lastFrameAt) : 16
    lastFrameAt = t
    const active = isActive(t)
    if (!active) {
      // 空闲降频到 30fps；完全静止时再放宽到“有变化才画”。
      if (t - lastDrawAt < IDLE_FPS_MS - 1) return
      if (!dirty && t - lastDrawAt < 2000) return
    }
    try {
      draw(t, dt)
    } catch (error) {
      if (typeof console !== 'undefined') console.error('[sleuth-canvas] 画布绘制失败', error)
    }
    lastDrawAt = t
    dirty = false
  }

  function startLoop() {
    if (dead || rafId) return
    if (typeof requestAnimationFrame !== 'function') return
    lastFrameAt = 0
    rafId = requestAnimationFrame(frame)
  }

  function stopLoop() {
    if (rafId && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(rafId)
    rafId = 0
  }

  // ── 交互 ────────────────────────────────────────────────────────────────────
  function localPoint(ev) {
    try {
      const rect = canvas.getBoundingClientRect()
      return { x: ev.clientX - rect.left, y: ev.clientY - rect.top }
    } catch (error) {
      return { x: ev.clientX, y: ev.clientY }
    }
  }

  function screenToWorld(px, py) {
    return { x: (px - camera.x) / camera.zoom, y: (py - camera.y) / camera.zoom }
  }

  function hitTest(px, py) {
    if (!model) return null
    const world = screenToWorld(px, py)
    for (let i = model.nodes.length - 1; i >= 0; i -= 1) {
      const node = model.nodes[i]
      if (!node) continue
      if (pointInRect(world.x, world.y, node.rect)) return node.idx
    }
    return null
  }

  function panelHit(px, py) {
    const panel = minimapPanel()
    if (!panel) return null
    return pointInRect(px, py, panel) ? panel : null
  }

  function minimapToWorld(panel, px, py) {
    const map = minimapMap(panel)
    const b = model.bounds
    const clampedX = clamp(px, panel.inner.x, panel.inner.x + panel.inner.w)
    const clampedY = clamp(py, panel.inner.y, panel.inner.y + panel.inner.h)
    return {
      x: b.minX + (clampedX - map.ox) / map.scale,
      y: b.minY + (clampedY - map.oy) / map.scale,
    }
  }

  function moveViewportFromMinimap(px, py) {
    const panel = minimapPanel()
    if (!panel) return
    const world = minimapToWorld(panel, px, py)
    camAnim = null
    camSmoothing = false
    camera.x = cssW / 2 - world.x * camera.zoom
    camera.y = cssH / 2 - world.y * camera.zoom
    clampCamera(camera)
    camTarget.x = camera.x
    camTarget.y = camera.y
    camTarget.zoom = camera.zoom
    touch()
  }

  function setHoveredInternal(idx) {
    if (idx !== hovered) {
      hovered = idx
      if (idx !== null && !hoverLevels.has(idx)) hoverLevels.set(idx, { value: 0 })
      emitHover(idx)
      touch()
    }
  }

  function updateHoverFromPoint(px, py) {
    if (!model) return
    const panel = panelHit(px, py)
    if (panel) {
      setHoveredInternal(null)
      if (canvas.style) canvas.style.cursor = 'pointer'
      return
    }
    const idx = hitTest(px, py)
    setHoveredInternal(idx)
    if (canvas.style) canvas.style.cursor = idx === null ? 'default' : 'pointer'
  }

  function onPointerDown(ev) {
    if (dead) return
    if (ev.pointerType === 'mouse' && ev.button !== 0) return
    const point = localPoint(ev)
    const panel = panelHit(point.x, point.y)
    if (panel) {
      miniDrag = true
      try { canvas.setPointerCapture(ev.pointerId) } catch (error) { /* 不支持捕获时仍可用移出画布结束 */ }
      moveViewportFromMinimap(point.x, point.y)
      return
    }
    dragging = {
      id: ev.pointerId,
      x0: point.x,
      y0: point.y,
      panX: camera.x,
      panY: camera.y,
      moved: false,
    }
    try { canvas.setPointerCapture(ev.pointerId) } catch (error) { /* 同上 */ }
    if (canvas.style) canvas.style.cursor = 'grabbing'
    touch()
  }

  function onPointerMove(ev) {
    if (dead) return
    const point = localPoint(ev)
    pointerScreen = point
    if (miniDrag) {
      moveViewportFromMinimap(point.x, point.y)
      return
    }
    if (dragging && (dragging.id === undefined || ev.pointerId === dragging.id)) {
      const dx = point.x - dragging.x0
      const dy = point.y - dragging.y0
      if (!dragging.moved && Math.abs(dx) + Math.abs(dy) > 3) dragging.moved = true
      if (dragging.moved) {
        camAnim = null
        camSmoothing = false
        camera.x = dragging.panX + dx
        camera.y = dragging.panY + dy
        clampCamera(camera)
        camTarget.x = camera.x
        camTarget.y = camera.y
        camTarget.zoom = camera.zoom
        touch()
      }
      return
    }
    updateHoverFromPoint(point.x, point.y)
  }

  function onPointerUp(ev) {
    if (dead) return
    if (miniDrag) {
      miniDrag = false
      try { canvas.releasePointerCapture(ev.pointerId) } catch (error) { /* 忽略 */ }
      touch()
      return
    }
    if (!dragging) return
    const drag = dragging
    dragging = null
    try { canvas.releasePointerCapture(ev.pointerId) } catch (error) { /* 忽略 */ }
    const point = localPoint(ev)
    if (!drag.moved) {
      const idx = hitTest(point.x, point.y)
      selected = idx
      focusPulseAt = nowMs()
      spotlightTarget = focusIndex() >= 0 ? 1 : 0
      if (selected !== null && !hoverLevels.has(selected)) hoverLevels.set(selected, { value: 0 })
      emitSelect(idx)
      touch()
    }
    updateHoverFromPoint(point.x, point.y)
    if (canvas.style && !hovered) canvas.style.cursor = 'default'
  }

  function onPointerCancel(ev) {
    miniDrag = false
    dragging = null
    try { canvas.releasePointerCapture(ev.pointerId) } catch (error) { /* 忽略 */ }
    if (canvas.style) canvas.style.cursor = 'default'
    touch()
  }

  function onPointerLeave() {
    if (dragging || miniDrag) return
    pointerScreen = null
    if (hovered !== null) setHoveredInternal(null)
    if (canvas.style) canvas.style.cursor = 'default'
    touch()
  }

  function onWheel(ev) {
    if (dead) return
    ev.preventDefault()
    const point = localPoint(ev)
    let delta = ev.deltaY
    if (ev.deltaMode === 1) delta *= 16
    else if (ev.deltaMode === 2) delta *= cssH
    const factor = Math.exp(-delta * 0.0016)
    zoomAt(point.x, point.y, factor)
  }

  function onDoubleClick(ev) {
    if (dead) return
    const point = localPoint(ev)
    if (panelHit(point.x, point.y)) return
    computeFit(true)
  }

  function onVisibilityChange() {
    if (typeof document !== 'undefined' && document && document.hidden) stopLoop()
    else {
      startLoop()
      touch()
    }
  }

  function onWindowResize() {
    resize()
  }

  // ── 对外 API ────────────────────────────────────────────────────────────────
  function setGraph(next) {
    if (dead) return
    const g = next && typeof next === 'object' ? next : {}
    const normalized = {
      columns: Array.isArray(g.columns) ? g.columns : [],
      nodes: Array.isArray(g.nodes) ? g.nodes : [],
      edges: Array.isArray(g.edges) ? g.edges : [],
    }
    const prevGraph = graph
    if (model && model.nodes.length && !prefersReduced()) {
      outgoing = { model: model, graph: prevGraph, at: nowMs(), dur: 120 }
    } else {
      outgoing = null
    }
    graph = normalized
    model = buildModel(graph, palette)
    model.enterAt = prefersReduced() || !graph.nodes.length ? -1e9 : nowMs()
    // 换单后旧选中/聚光点可能越界，清掉而不是留一个指向不存在节点的光晕。
    if (selected !== null && !graph.nodes[selected]) selected = null
    if (replayFocus !== null && !graph.nodes[replayFocus]) replayFocus = null
    hoverLevels.clear()
    hovered = null
    focusPulseAt = -1e9
    spotlight = 0
    spotlightTarget = focusIndex() >= 0 ? 1 : 0
    ensureRelevance()
    pendingFit = false
    applyInitialCamera(true)
    touch()
  }

  function setSelected(idx) {
    if (dead) return
    const nextIdx = Number.isFinite(idx) && idx >= 0 && graph.nodes[idx] ? idx : null
    if (nextIdx === selected) return
    selected = nextIdx
    focusPulseAt = nowMs()
    spotlightTarget = focusIndex() >= 0 ? 1 : 0
    ensureRelevance()
    touch()
  }

  function setHovered(idx) {
    if (dead) return
    const nextIdx = Number.isFinite(idx) && idx >= 0 && graph.nodes[idx] ? idx : null
    setHoveredInternal(nextIdx)
  }

  function setReplay(active) {
    if (dead) return
    replay = !!active
    spotlightTarget = focusIndex() >= 0 ? 1 : 0
    ensureRelevance()
    touch()
  }

  function setReplayFocus(idx) {
    if (dead) return
    const nextIdx = Number.isFinite(idx) && idx >= 0 && graph.nodes[idx] ? idx : null
    replayFocus = nextIdx
    focusPulseAt = nowMs()
    spotlightTarget = focusIndex() >= 0 ? 1 : 0
    ensureRelevance()
    touch()
  }

  function flyTo(idx, options) {
    if (dead || !model) return
    const rect = model.rects[idx]
    if (!rect) return
    const zoom = camTarget.zoom
    const duration = options && Number.isFinite(options.duration) ? options.duration : 320
    const cx = rect.x + rect.w / 2
    const cy = rect.y + rect.h / 2
    animateCameraTo({ x: cssW / 2 - cx * zoom, y: cssH / 2 - cy * zoom, zoom: zoom }, duration)
  }

  function fit(options) {
    if (dead) return
    const animate = !(options && options.animate === false)
    computeFit(animate)
  }

  function zoomBy(factor) {
    if (dead) return
    zoomAt(cssW / 2, cssH / 2, factor)
  }

  function nodeRect(idx) {
    if (dead || !model) return null
    const rect = model.rects[idx]
    if (!rect) return null
    return {
      x: rect.x * camera.zoom + camera.x,
      y: rect.y * camera.zoom + camera.y,
      w: rect.w * camera.zoom,
      h: rect.h * camera.zoom,
    }
  }

  // 导出当前视图：把画布像素合成到带主题底色的新画布，返回 dataURL。页面只负责下载。
  function exportImage() {
    if (dead || !canvas || !canvas.width || !canvas.height) return null
    const copyCanvas = document.createElement('canvas')
    copyCanvas.width = canvas.width
    copyCanvas.height = canvas.height
    const context = copyCanvas.getContext('2d')
    if (!context) return null
    const p = palette
    context.fillStyle = p.surface
    context.fillRect(0, 0, copyCanvas.width, copyCanvas.height)
    context.drawImage(canvas, 0, 0)
    return copyCanvas.toDataURL('image/png')
  }

  function destroy() {
    if (dead) return
    dead = true
    stopLoop()
    if (ro) {
      try { ro.disconnect() } catch (error) { /* 忽略 */ }
      ro = null
    }
    canvas.removeEventListener('pointerdown', onPointerDown)
    canvas.removeEventListener('pointermove', onPointerMove)
    canvas.removeEventListener('pointerup', onPointerUp)
    canvas.removeEventListener('pointercancel', onPointerCancel)
    canvas.removeEventListener('pointerleave', onPointerLeave)
    canvas.removeEventListener('wheel', onWheel)
    canvas.removeEventListener('dblclick', onDoubleClick)
    if (typeof document !== 'undefined' && document && document.removeEventListener) {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
    if (winResizeBound && typeof window !== 'undefined' && window.removeEventListener) {
      window.removeEventListener('resize', onWindowResize)
      winResizeBound = false
    }
    try { canvas.style.touchAction = prevTouchAction } catch (error) { /* 忽略 */ }
    try { ctx.clearRect(0, 0, cssW, cssH) } catch (error) { /* 忽略 */ }
    model = null
    outgoing = null
    graph = { columns: [], nodes: [], edges: [] }
    hoverLevels.clear()
  }

  // ── 初始化 ──────────────────────────────────────────────────────────────────
  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('pointermove', onPointerMove)
  canvas.addEventListener('pointerup', onPointerUp)
  canvas.addEventListener('pointercancel', onPointerCancel)
  canvas.addEventListener('pointerleave', onPointerLeave)
  canvas.addEventListener('wheel', onWheel, { passive: false })
  canvas.addEventListener('dblclick', onDoubleClick)

  try {
    prevTouchAction = canvas.style.touchAction || ''
    canvas.style.touchAction = 'none'
  } catch (error) { /* 无 style 的环境忽略 */ }

  if (typeof document !== 'undefined' && document && document.addEventListener) {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }
  if (typeof ResizeObserver === 'function') {
    try {
      ro = new ResizeObserver(function () { resize() })
      ro.observe(canvas.parentElement || canvas)
    } catch (error) {
      ro = null
    }
  }
  if (!ro && typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('resize', onWindowResize)
    winResizeBound = true
  }

  resize()
  startLoop()

  return {
    setGraph: setGraph,
    setSelected: setSelected,
    setHovered: setHovered,
    setReplay: setReplay,
    setReplayFocus: setReplayFocus,
    flyTo: flyTo,
    fit: fit,
    zoomBy: zoomBy,
    resize: resize,
    nodeRect: nodeRect,
    exportImage: exportImage,
    destroy: destroy,
  }
}
