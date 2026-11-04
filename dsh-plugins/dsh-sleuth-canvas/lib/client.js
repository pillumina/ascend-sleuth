/* eslint-disable */
// 生成物 —— 勿手改。由 `node build.mjs` 从 client-src/*.js 拼出：
//   05-util.js
//   06-theme.js
//   10-engine.js
//   20-model.js
//   30-page.js
//   40-css.js
//   90-plugin.js
// 校验：`node build.mjs --check`。
// 契约：docs/CONTRACT.md §1。
window.__ModuleLoader__.load({
  id: "dsh-sleuth-canvas",
  factory(require) {
    const React = require('react')
    const SC = { React, h: React.createElement, version: "0.2.1" }

// ─── client-src/05-util.js ───
;(function (SC) {
// 纯函数工具：格式、缓动、文本切分、复制。不碰 DOM（复制除外，且只在调用时碰）。

SC.util = (function () {
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

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n)
  }

  function parseTime(iso) {
    if (!iso) return null
    const ms = Date.parse(String(iso))
    return Number.isFinite(ms) ? ms : null
  }

  function formatRelative(iso, nowMs) {
    const ms = parseTime(iso)
    if (ms === null) return ''
    const now = typeof nowMs === 'number' ? nowMs : Date.now()
    const diff = now - ms
    if (diff < 0) return '刚刚'
    const minute = 60 * 1000
    if (diff < minute) return '刚刚'
    if (diff < 60 * minute) return Math.floor(diff / minute) + ' 分钟前'
    if (diff < 24 * 60 * minute) return Math.floor(diff / (60 * minute)) + ' 小时前'
    if (diff < 30 * 24 * 60 * minute) return Math.floor(diff / (24 * 60 * minute)) + ' 天前'
    const d = new Date(ms)
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
  }

  function formatSpan(fromIso, toIso) {
    const from = parseTime(fromIso)
    const to = parseTime(toIso)
    if (from === null || to === null || to < from) return ''
    const seconds = Math.round((to - from) / 1000)
    if (seconds < 60) return seconds + ' 秒'
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    if (minutes < 60) return rest ? minutes + ' 分 ' + rest + ' 秒' : minutes + ' 分钟'
    const hours = Math.floor(minutes / 60)
    const restMin = minutes % 60
    return restMin ? hours + ' 小时 ' + restMin + ' 分' : hours + ' 小时'
  }

  function formatNumber(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
    return new Intl.NumberFormat('zh-CN').format(Number(value))
  }

  function compactNumber(value) {
    const n = Number(value)
    if (!Number.isFinite(n)) return '—'
    if (n >= 100000000) return (n / 100000000).toFixed(1).replace(/\.0$/, '') + ' 亿'
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + ' 万'
    return String(n)
  }

  function formatBytes(value) {
    const n = Number(value)
    if (!Number.isFinite(n)) return '—'
    if (n < 1024) return n + ' B'
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB'
    return (n / 1024 / 1024).toFixed(1) + ' MB'
  }

  // 按“显示字符”截断（中文与 emoji 都算 1 个），超出补省略号。
  function chars(text) {
    return Array.from(String(text === null || text === undefined ? '' : text))
  }

  function truncate(text, max) {
    const list = chars(text)
    if (list.length <= max) return list.join('')
    return list.slice(0, Math.max(0, max - 1)).join('') + '…'
  }

  // 取第一句（句号/分号/换行/问号/感叹号），不超 max 字。
  function firstSentence(text, max) {
    const raw = String(text === null || text === undefined ? '' : text).replace(/\s+/g, ' ').trim()
    if (!raw) return ''
    const cut = raw.search(/[。；;！!？?\n]/)
    const head = cut >= 0 ? raw.slice(0, cut + 1) : raw
    return truncate(head, max)
  }

  function firstLine(text, max) {
    const raw = String(text === null || text === undefined ? '' : text)
    const line = raw.split(/\r?\n/).map((s) => s.trim()).find(Boolean) || ''
    return truncate(line, max)
  }

  // 长文本分段：先按空行/换行切，再给超长段落按标点找落点。段落 ≤ 200 字。
  function paragraphs(text, max) {
    const limit = max || 200
    const raw = String(text === null || text === undefined ? '' : text).replace(/\r\n/g, '\n')
    const blocks = raw.split(/\n{2,}/).flatMap((block) => block.split(/\n(?=\s*[^\s])/))
    const out = []
    for (const block of blocks) {
      const value = block.trim()
      if (!value) continue
      let rest = value
      while (chars(rest).length > limit) {
        const window = chars(rest).slice(0, limit).join('')
        let cut = -1
        for (const mark of ['。', '；', '！', '？', '，', '、', ' ']) {
          const at = window.lastIndexOf(mark)
          if (at > limit * 0.4) { cut = at + 1; break }
        }
        if (cut < 0) cut = limit
        out.push(chars(rest).slice(0, cut).join('').trim())
        rest = rest.slice(cut).trim()
      }
      if (rest) out.push(rest)
    }
    return out
  }

  // 状态语义：只描述“这单在哪一步”，不是“该不该你做事”。
  function statusTone(status) {
    const value = String(status === null || status === undefined ? '' : status)
    if (value === 'in_progress' || value === 'running') {
      return { key: 'live', label: '进行中', tone: 'route' }
    }
    if (value === 'resolved') return { key: 'done', label: '已定位', tone: 'hit' }
    if (value === 'false_positive' || value === 'invalid') return { key: 'idle', label: '不成立', tone: 'miss' }
    return { key: 'other', label: value || '未记录', tone: 'feedback' }
  }

  function debounce(fn, wait) {
    let timer = 0
    return function debounced() {
      const args = arguments
      const self = this
      if (timer) clearTimeout(timer)
      timer = setTimeout(function () {
        timer = 0
        fn.apply(self, args)
      }, wait)
    }
  }

  function copyText(text) {
    const value = String(text === null || text === undefined ? '' : text)
    if (!value) return Promise.resolve(false)
    try {
      if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(value).then(function () { return true }).catch(function () { return false })
      }
    } catch (e) { /* 落到下面 */ }
    try {
      const area = document.createElement('textarea')
      area.value = value
      area.setAttribute('readonly', 'true')
      area.style.position = 'fixed'
      area.style.opacity = '0'
      document.body.appendChild(area)
      area.select()
      const ok = document.execCommand('copy')
      area.remove()
      return Promise.resolve(ok)
    } catch (e) {
      return Promise.resolve(false)
    }
  }

  return {
    clamp: clamp,
    lerp: lerp,
    easeOutCubic: easeOutCubic,
    easeInOutCubic: easeInOutCubic,
    parseTime: parseTime,
    formatRelative: formatRelative,
    formatSpan: formatSpan,
    formatNumber: formatNumber,
    compactNumber: compactNumber,
    formatBytes: formatBytes,
    chars: chars,
    truncate: truncate,
    firstSentence: firstSentence,
    firstLine: firstLine,
    paragraphs: paragraphs,
    statusTone: statusTone,
    debounce: debounce,
    copyText: copyText,
  }
})()
})(SC)

// ─── client-src/06-theme.js ───
;(function (SC) {
// 主题：把宿主 --dsw-alias-* 令牌解析成画布能直接用的具体颜色。
//
// 画布不能等 CSS 生效再取色，也不该每帧调 getComputedStyle（很贵）。做法：
//   1. 用 1×1 canvas 把任意 CSS 颜色（oklch / color() / rgb / hex）解析成 rgba；
//   2. 结果缓存 2 秒，主题属性变化时立刻失效；
//   3. 语义色在暗色下统一提亮 6%、降饱和 6%，保证深底上不脏。

SC.theme = (function () {
  // 语义色（亮色基准）。键名与 canvas-src 的 actions 家族一致。
  const TONES = {
    intake: '#D9902F',
    route: '#4A7DFF',
    index: '#2AA7B8',
    check: '#8A6CF0',
    book: '#3C9A78',
    code: '#E07A3F',
    hit: '#3FA46A',
    miss: '#6E7C93',
    flag: '#C9A227',
    feedback: '#7C8698',
    warn: '#D9822B',
    risk: '#D65454',
  }

  const FALLBACK = {
    base: '#ffffff',
    layer1: '#f7f8fa',
    layer2: '#eef0f4',
    overlay: '#ffffff',
    borderL1: '#e3e6ec',
    borderL2: '#cfd4dd',
    brand: '#4a7dff',
    text: '#101318',
    text2: '#5b6472',
  }

  let probe = null
  let cached = null
  let cachedAt = 0
  let listening = false

  function probeContext() {
    if (probe) return probe
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    probe = canvas.getContext('2d', { willReadFrequently: true })
    return probe
  }

  const parsedColors = new Map()

  function parseColor(input) {
    const value = String(input === null || input === undefined ? '' : input).trim()
    if (!value) return null
    if (parsedColors.has(value)) return parsedColors.get(value)
    let rgb = null
    try {
      const ctx = probeContext()
      ctx.clearRect(0, 0, 1, 1)
      ctx.fillStyle = '#000000'
      ctx.fillStyle = value
      const normalized = String(ctx.fillStyle)
      ctx.fillStyle = normalized
      ctx.fillRect(0, 0, 1, 1)
      const data = ctx.getImageData(0, 0, 1, 1).data
      rgb = { r: data[0], g: data[1], b: data[2], a: data[3] / 255 }
    } catch (error) {
      rgb = null
    }
    parsedColors.set(value, rgb)
    return rgb
  }

  function toRgba(rgb, alpha) {
    if (!rgb) return 'rgba(0,0,0,0)'
    const a = alpha === undefined ? (rgb.a === undefined ? 1 : rgb.a) : alpha
    return 'rgba(' + Math.round(rgb.r) + ',' + Math.round(rgb.g) + ',' + Math.round(rgb.b) + ',' + a + ')'
  }

  function alpha(input, value) {
    if (input === null || input === undefined) return 'rgba(0,0,0,' + value + ')'
    const fast = /^#([0-9a-f]{6})$/i.exec(String(input).trim())
    if (fast) {
      const n = parseInt(fast[1], 16)
      return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + value + ')'
    }
    return toRgba(parseColor(input), value)
  }

  function rgbToHex(rgb) {
    const to = (n) => {
      const v = Math.max(0, Math.min(255, Math.round(n)))
      return v < 16 ? '0' + v.toString(16) : v.toString(16)
    }
    return '#' + to(rgb.r) + to(rgb.g) + to(rgb.b)
  }

  function rgbToHsl(rgb) {
    const r = rgb.r / 255
    const g = rgb.g / 255
    const b = rgb.b / 255
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    const l = (max + min) / 2
    if (max === min) return { h: 0, s: 0, l: l }
    const d = max - min
    const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
    let h
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0)
    else if (max === g) h = (b - r) / d + 2
    else h = (r - g) / d + 4
    return { h: h / 6, s: s, l: l }
  }

  function hslToHex(hsl) {
    const hue2rgb = (p, q, t) => {
      let x = t
      if (x < 0) x += 1
      if (x > 1) x -= 1
      if (x < 1 / 6) return p + (q - p) * 6 * x
      if (x < 1 / 2) return q
      if (x < 2 / 3) return p + (q - p) * (2 / 3 - x) * 6
      return p
    }
    let { h, s, l } = hsl
    s = Math.max(0, Math.min(1, s))
    l = Math.max(0.06, Math.min(0.94, l))
    let r
    let g
    let b
    if (s === 0) {
      r = g = b = l
    } else {
      const q = l < 0.5 ? l * (1 + s) : l + s - l * s
      const p = 2 * l - q
      r = hue2rgb(p, q, h + 1 / 3)
      g = hue2rgb(p, q, h)
      b = hue2rgb(p, q, h - 1 / 3)
    }
    return rgbToHex({ r: r * 255, g: g * 255, b: b * 255 })
  }

  function adjust(input, deltaLightness, deltaSaturation) {
    const rgb = parseColor(input)
    if (!rgb) return String(input)
    const hsl = rgbToHsl(rgb)
    return hslToHex({
      h: hsl.h,
      s: hsl.s + (deltaSaturation || 0),
      l: hsl.l + (deltaLightness || 0),
    })
  }

  function mix(from, to, t) {
    const a = parseColor(from)
    const b = parseColor(to)
    if (!a || !b) return toRgba(a || b, 1)
    return toRgba({
      r: a.r + (b.r - a.r) * t,
      g: a.g + (b.g - a.g) * t,
      b: a.b + (b.b - a.b) * t,
    }, 1)
  }

  function relativeLuminance(rgb) {
    if (!rgb) return 0.5
    const channel = (v) => {
      const c = v / 255
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * channel(rgb.r) + 0.7152 * channel(rgb.g) + 0.0722 * channel(rgb.b)
  }

  function readVar(name) {
    try {
      const style = getComputedStyle(document.documentElement)
      const value = style.getPropertyValue(name).trim()
      if (value) return value
    } catch (error) { /* 交回兜底 */ }
    return ''
  }

  function ensureListeners() {
    if (listening) return
    listening = true
    const invalidate = () => { cached = null }
    try {
      if (typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(invalidate)
        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['class', 'style', 'data-theme', 'data-mode', 'lang', 'data-ds-dark-theme'],
        })
        observer.observe(document.body || document.documentElement, {
          attributes: true,
          attributeFilter: ['class', 'style', 'data-ds-dark-theme'],
        })
      }
    } catch (error) { /* 无 MutationObserver 也不影响取色 */ }
    try {
      const media = window.matchMedia('(prefers-color-scheme: dark)')
      if (media && typeof media.addEventListener === 'function') media.addEventListener('change', invalidate)
    } catch (error) { /* 忽略 */ }
  }

  function buildPalette() {
    ensureListeners()
    const colorOf = (raw, fallback) => parseColor(raw) || parseColor(fallback) || { r: 255, g: 255, b: 255, a: 1 }
    const token = {
      base: readVar('--dsw-alias-bg-base') || FALLBACK.base,
      layer1: readVar('--dsw-alias-bg-layer-1') || FALLBACK.layer1,
      layer2: readVar('--dsw-alias-bg-layer-2') || FALLBACK.layer2,
      overlay: readVar('--dsw-alias-bg-overlay') || FALLBACK.overlay,
      borderL1: readVar('--dsw-alias-border-l1') || FALLBACK.borderL1,
      borderL2: readVar('--dsw-alias-border-l2') || FALLBACK.borderL2,
      brand: readVar('--dsw-alias-brand-primary') || FALLBACK.brand,
      text: readVar('--dsw-alias-label-primary') || FALLBACK.text,
      text2: readVar('--dsw-alias-label-secondary') || FALLBACK.text2,
    }
    // 暗色判定：宿主面板用 body[data-ds-dark-theme] 标暗色；先认它，认不到再按背景亮度判。
    let darkAttr = false
    try {
      darkAttr = Boolean(document.body && typeof document.body.hasAttribute === 'function' && document.body.hasAttribute('data-ds-dark-theme'))
    } catch (error) { darkAttr = false }
    const surfaceRgb = parseColor(token.base) || parseColor(FALLBACK.base)
    const mode = darkAttr || relativeLuminance(surfaceRgb) < 0.45 ? 'dark' : 'light'
    const delta = mode === 'dark' ? 0.055 : 0
    const satDelta = mode === 'dark' ? -0.05 : 0
    const tones = {}
    for (const key of Object.keys(TONES)) tones[key] = adjust(TONES[key], delta, satDelta)
    const textRgb = parseColor(token.text)
    const text2Rgb = parseColor(token.text2)
    const palette = {
      mode: mode,
      surface: toRgba(surfaceRgb, 1),
      surfaceAlt: toRgba(colorOf(token.layer1, FALLBACK.layer1), 1),
      surfaceDeep: toRgba(colorOf(token.layer2, FALLBACK.layer2), 1),
      overlay: toRgba(colorOf(token.overlay, FALLBACK.overlay), 1),
      border: toRgba(colorOf(token.borderL1, FALLBACK.borderL1), 1),
      borderStrong: toRgba(colorOf(token.borderL2, FALLBACK.borderL2), 1),
      text: toRgba(textRgb || colorOf(FALLBACK.text, FALLBACK.text), 1),
      text2: toRgba(text2Rgb || colorOf(FALLBACK.text2, FALLBACK.text2), 1),
      text3: toRgba(text2Rgb || colorOf(FALLBACK.text2, FALLBACK.text2), 0.62),
      accent: toRgba(colorOf(token.brand, FALLBACK.brand), 1),
      accentHex: rgbToHex(colorOf(token.brand, FALLBACK.brand)),
      grid: alpha(token.borderL1, mode === 'dark' ? 0.42 : 0.55),
      edge: alpha(token.borderL2, mode === 'dark' ? 0.9 : 0.8),
      nodeBgTop: toRgba(colorOf(token.layer1, FALLBACK.layer1), 1),
      nodeBgBottom: mix(colorOf(token.layer1, FALLBACK.layer1) && token.layer1 || FALLBACK.layer1, token.base || FALLBACK.base, 0.55),
      shadow: mode === 'dark' ? 'rgba(0,0,0,0.5)' : 'rgba(20,30,50,0.16)',
      glow: mode === 'dark' ? 0.5 : 0.28,
      tones: tones,
      tone: function (key) {
        return tones[key] || tones.feedback
      },
      alpha: alpha,
      mix: mix,
      adjust: adjust,
      toRgba: toRgba,
      parse: parseColor,
      hsl: rgbToHsl,
      hex: rgbToHex,
    }
    return palette
  }

  function currentPalette() {
    const now = Date.now()
    if (cached !== null && now - cachedAt < 2000) return cached
    cached = buildPalette()
    cachedAt = now
    return cached
  }

  function invalidate() {
    cached = null
  }

  return {
    TONES: TONES,
    currentPalette: currentPalette,
    invalidate: invalidate,
    alpha: alpha,
    mix: mix,
    adjust: adjust,
    parse: parseColor,
    toRgba: toRgba,
  }
})()
})(SC)

// ─── client-src/10-engine.js ───
;(function (SC) {
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
})(SC)

// ─── client-src/20-model.js ───
;(function (SC) {
// 页面数据映射：trace 事件 → 画布图（columns/nodes/edges）+ 检查器分区 + 页头统计。
//
// 这一层只有纯函数，不碰 DOM、不碰 React；颜色给的是亮色基准，页面用
// SC.theme.currentPalette().tones 覆盖（暗色提亮由主题模块做）。分类表见 docs/DESIGN.md §3。

SC.model = (function () {
  const U = SC.util

  // DESIGN §2.2 亮色基准。页面会以 palette.tones 的同名键覆盖。
  const TONES = {
    intake: '#D9902F',
    route: '#4A7DFF',
    index: '#2AA7B8',
    check: '#8A6CF0',
    book: '#3C9A78',
    code: '#E07A3F',
    hit: '#3FA46A',
    miss: '#6E7C93',
    flag: '#C9A227',
    feedback: '#7C8698',
    warn: '#D9822B',
    risk: '#D65454',
  }

  // 家族名：图例与列标签用中文，action 名保留原值。
  const TONE_LABELS = {
    intake: '现场',
    route: '分诊',
    index: '检索',
    check: '核验',
    book: '先验',
    code: '源码',
    hit: '命中',
    miss: '未覆盖',
    flag: '归因',
    feedback: '收尾',
    warn: '警示',
    risk: '风险',
  }

  // DESIGN §3 动作分类表。`intake` 是 user 事件（action 为 null）的伪动作，
  // `unknown` 是任何未登记 action 的兜底（家族 feedback / glyph dot / 标题取原值）。
  const ACTIONS = {
    intake: { family: 'intake', tone: 'intake', glyph: 'intake', label: '现场', emphasis: 'normal' },
    triage: { family: 'route', tone: 'route', glyph: 'route', label: '分诊', emphasis: 'normal' },
    triage_semantic: { family: 'route', tone: 'route', glyph: 'route', label: '语义分诊', emphasis: 'normal' },
    load_index: { family: 'index', tone: 'index', glyph: 'index', label: '检索', emphasis: 'normal' },
    quickly_check: { family: 'check', tone: 'check', glyph: 'check', label: '核验', emphasis: 'normal' },
    tier3: { family: 'check', tone: 'check', glyph: 'cross', label: 'Tier 3', emphasis: 'normal' },
    reference_lookup: { family: 'book', tone: 'book', glyph: 'book', label: '查先验', emphasis: 'normal' },
    source_analysis: { family: 'code', tone: 'code', glyph: 'code', label: '源码分析', emphasis: 'normal' },
    hit: { family: 'hit', tone: 'hit', glyph: 'hit', label: '命中', emphasis: 'conclusion' },
    miss: { family: 'miss', tone: 'miss', glyph: 'miss', label: '未覆盖', emphasis: 'conclusion' },
    attribution: { family: 'flag', tone: 'flag', glyph: 'flag', label: '归因', emphasis: 'normal' },
    output: { family: 'flag', tone: 'flag', glyph: 'doc', label: '输出结论', emphasis: 'conclusion' },
    resume: { family: 'feedback', tone: 'feedback', glyph: 'loop', label: '续接', emphasis: 'normal' },
    report: { family: 'feedback', tone: 'feedback', glyph: 'doc', label: '报告', emphasis: 'normal' },
    feedback: { family: 'feedback', tone: 'feedback', glyph: 'feedback', label: '回报', emphasis: 'normal' },
    unknown: { family: 'feedback', tone: 'feedback', glyph: 'dot', label: '动作', emphasis: 'normal' },
  }

  // 每条 action 的 meta 第二段（“step N · 这里”）。
  const VERBS = {
    intake: '用户',
    triage: '分诊',
    triage_semantic: '语义分诊',
    load_index: '检索',
    quickly_check: '核验',
    tier3: 'Tier 3',
    reference_lookup: '先验查照',
    source_analysis: '源码',
    hit: '命中',
    miss: '未覆盖',
    attribution: '归因',
    output: '结论',
    resume: '续接',
    report: '报告',
    feedback: '回报',
    unknown: '事件',
  }

  // 已经被节点三元组/分区消费掉的 fields 键，不让它们再在“其余字段”里重复出现。
  const CONSUMED_FIELDS = {
    branch: 1, category: 1, routed: 1, namespace: 1, namespaces: 1, rationale: 1,
    n_cases: 1, n_candidates_selected: 1, reference: 1, layer: 1, selected_step: 1,
    component: 1, repo: 1, ref: 1, files: 1, files_read: 1, followup: 1, level: 1,
    outcome: 1, shard: 1, platform: 1, ref_id: 1,
  }

  function text(value) {
    return value === null || value === undefined ? '' : String(value)
  }

  function arr(value) {
    if (Array.isArray(value)) return value
    if (value === null || value === undefined || value === '') return []
    return [value]
  }

  function isNum(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
  }

  function eventChars(ev) {
    if (!ev) return 0
    const chars = ev.chars || {}
    const total = Number(chars.output || 0) + Number(chars.reason || 0) + Number(chars.content || 0)
    if (total > 0) return total
    return text(ev.output).length + text(ev.reason).length + text(ev.content).length
  }

  function charLabel(count) {
    const n = Math.max(0, Math.round(Number(count) || 0))
    if (n >= 10000) return U.compactNumber(n) + '字符'
    return U.formatNumber(n) + ' 字'
  }

  function shorten(value, max) {
    return U.truncate(text(value).replace(/\s+/g, ' ').trim(), max)
  }

  function firstLineOf(ev, max) {
    return U.firstSentence(text(ev && ev.output) || text(ev && ev.content) || text(ev && ev.reason), max)
  }

  // 把 action 解析成分类表条目；action 为 null 且 role=user 视为现场输入。
  function resolve(action, role) {
    if (action === null || action === undefined || action === '') {
      if (role === 'user') return { key: 'intake', entry: ACTIONS.intake }
      return { key: 'unknown', entry: ACTIONS.unknown }
    }
    const key = String(action)
    if (Object.prototype.hasOwnProperty.call(ACTIONS, key) && key !== 'unknown') {
      return { key: key, entry: ACTIONS[key] }
    }
    return { key: key, entry: ACTIONS.unknown }
  }

  function roleLabel(ev) {
    if (!ev) return ''
    if (ev.role === 'user') return '用户'
    if (ev.role === 'agent') return '分析'
    return text(ev.role)
  }

  function badge(label, tone) {
    return { text: text(label), tone: tone || 'neutral' }
  }

  function valuesOf(list) {
    return arr(list).map(text).filter(Boolean)
  }

  // 节点三元组 + badges：DESIGN §3 的每一行。
  function describeEvent(ev, detail) {
    const resolved = resolve(ev && ev.action, ev && ev.role)
    const entry = resolved.entry
    const fields = (ev && ev.fields) || {}
    const step = ev && ev.step !== null && ev.step !== undefined ? ev.step : '?'
    const verb = VERBS[resolved.key] || '事件'
    const badges = []
    let title = ''
    let subtitle = ''
    let meta = 'step ' + step + ' · ' + verb

    switch (resolved.key) {
      case 'intake': {
        title = '现场输入'
        subtitle = U.firstSentence(text(ev && ev.content), 60)
        meta = 'step ' + step + ' · 用户'
        const evidence = (ev && ev.evidence) || {}
        const inlineChars = Number(evidence.inlineChars || 0) || text(evidence.inline).length
        const bodyChars = inlineChars || Number((ev && ev.chars && ev.chars.content) || 0)
        if (bodyChars > 0) badges.push(badge('证据 ' + charLabel(bodyChars), 'neutral'))
        if (valuesOf(evidence.files).length) badges.push(badge(valuesOf(evidence.files).length + ' 文件', 'neutral'))
        if (valuesOf(evidence.sources).length) badges.push(badge(valuesOf(evidence.sources).length + ' 链接', 'neutral'))
        break
      }
      case 'triage': {
        const branch = text(fields.branch)
        title = branch ? '分诊 → ' + branch : '分诊'
        subtitle = text(fields.category) || firstLineOf(ev, 64)
        const routed = valuesOf(fields.routed)
        meta = 'step ' + step + (routed.length ? ' · 路由 ' + routed.join('、') : ' · 分诊')
        break
      }
      case 'triage_semantic': {
        const namespace = text(fields.namespace) || valuesOf(fields.namespaces)[0] || ''
        title = namespace ? '语义分诊 → ' + namespace : '语义分诊'
        subtitle = U.firstSentence(text(fields.rationale) || text(ev.output) || text(ev.reason), 64)
        meta = 'step ' + step + ' · 语义分诊'
        break
      }
      case 'load_index': {
        title = '检索候选'
        const nCases = text(fields.n_cases)
        const namespaces = valuesOf(fields.namespaces).join('、')
        const parts = []
        if (nCases) parts.push(nCases + ' 条 case')
        if (namespaces) parts.push(namespaces)
        subtitle = parts.length ? parts.join(' · ') : U.firstSentence(text(ev.reason), 64)
        meta = 'step ' + step + ' · 检索'
        if (isNum(fields.n_candidates_selected)) {
          badges.push(badge(Number(fields.n_candidates_selected) + ' 候选', 'neutral'))
        }
        break
      }
      case 'quickly_check': {
        const caseId = text(ev && ev.case) || text(fields.case)
        title = caseId ? '核验 ' + caseId : '核验候选'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 核验'
        const verdict = (ev && ev.verdict) || {}
        if (text(verdict.primary)) {
          badges.push(badge('primary ' + text(verdict.primary), verdict.primary === 'pass' ? 'hit' : verdict.primary === 'fail' ? 'miss' : 'warn'))
        }
        if (text(verdict.fallback)) {
          badges.push(badge('fallback ' + text(verdict.fallback), verdict.fallback === 'pass' ? 'hit' : verdict.fallback === 'fail' ? 'miss' : 'warn'))
        }
        if (text(verdict.marked)) badges.push(badge('marked ' + text(verdict.marked), 'warn'))
        break
      }
      case 'tier3': {
        title = '深度回退'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · Tier 3'
        break
      }
      case 'reference_lookup': {
        title = '查先验'
        const reference = text(fields.reference)
        subtitle = [text(ev && ev.purpose), reference].filter(Boolean).join(' · ') || firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 先验查照'
        if (isNum(fields.layer)) badges.push(badge('第 ' + text(fields.layer) + ' 层', 'neutral'))
        break
      }
      case 'source_analysis': {
        title = '源码分析'
        const repo = text(fields.repo)
        const ref = text(fields.ref)
        const files = valuesOf(fields.files).length || valuesOf(fields.files_read).length
        const head = [repo, ref].filter(Boolean).join('@')
        const parts = []
        if (head) parts.push(head)
        if (files) parts.push(files + ' 个文件')
        subtitle = parts.length ? parts.join(' · ') : firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 源码'
        const tools = valuesOf(ev && ev.toolCalls).length
        if (tools) badges.push(badge(tools + ' 次工具调用', 'neutral'))
        break
      }
      case 'hit': {
        const caseId = text(ev && ev.case) || text(fields.case)
        title = caseId ? '命中 ' + caseId : '命中 case'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 命中'
        const confidence = text((ev && ev.verdict && ev.verdict.confidence) || fields.confidence)
        if (confidence) badges.push(badge('置信 ' + confidence, 'hit'))
        break
      }
      case 'miss': {
        title = '知识库未覆盖'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 未覆盖'
        const excluded = (detail && detail.excludedCases) || []
        if (excluded.length) badges.push(badge('排除 ' + excluded.length + ' 个候选', 'miss'))
        break
      }
      case 'attribution': {
        const component = text(fields.component)
        title = component ? '归因 · ' + component : '归因'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 归因'
        const verdictValue = text((ev && ev.verdict && ev.verdict.verdict) || fields.verdict)
        if (verdictValue) badges.push(badge(verdictValue, 'warn'))
        break
      }
      case 'output': {
        title = '给出结论'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 结论'
        break
      }
      case 'resume': {
        title = '续接诊断'
        subtitle = firstLineOf(ev, 64) || '从这里继续'
        meta = 'step ' + step + ' · 续接'
        break
      }
      case 'report': {
        title = '写报告'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 报告'
        break
      }
      case 'feedback': {
        const outcome = text(fields.outcome) || text(detail && detail.feedback && detail.feedback.outcome)
        title = outcome ? '回报结果 · ' + outcome : '回报结果'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 回报'
        if ((ev && ev.case) || (detail && detail.feedback && detail.feedback.case)) {
          badges.push(badge(text(ev && ev.case) || text(detail.feedback.case), 'hit'))
        }
        break
      }
      default: {
        title = shorten(ev && ev.action, 18) || '未标注动作'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · ' + shorten(ev && ev.action, 12)
        break
      }
    }

    return {
      key: resolved.key,
      family: entry.family,
      tone: entry.tone,
      glyph: entry.glyph,
      label: entry.label,
      emphasis: entry.emphasis,
      title: title,
      subtitle: subtitle,
      meta: meta,
      badges: badges,
      roleLabel: roleLabel(ev),
    }
  }

  function stepOf(ev, fallback) {
    if (!ev) return fallback
    if (ev.step === null || ev.step === undefined || ev.step === '') return fallback
    return ev.step
  }

  // detail → graph。columns 按 step 首次出现顺序；nodes 保持事件顺序；edges 为时间主链
  // （同列相邻节点也走这条链，引擎据 node.col 判断画竖向导引）。
  function buildGraph(detail, opts) {
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    const tones = (opts && opts.tones) || TONES
    const columns = []
    const nodes = []
    const edges = []
    const byStep = Object.create(null)
    let lastStep = null
    // host 的 conclusionIndex 是事件 idx；这里换算成数组位置，节点/选中都用位置作身份。
    let conclusionPos = null
    if (detail && detail.conclusionIndex !== null && detail.conclusionIndex !== undefined) {
      const at = events.findIndex(function (ev) { return ev && ev.idx === detail.conclusionIndex })
      conclusionPos = at >= 0 ? at : null
    }

    for (let i = 0; i < events.length; i += 1) {
      const ev = events[i] || {}
      const step = stepOf(ev, lastStep === null ? 1 : lastStep)
      lastStep = step
      let column = byStep[step]
      if (!column) {
        column = { col: columns.length, step: step, label: '', count: 0, accent: tones.intake, parallel: false, firstIdx: i }
        byStep[step] = column
        columns.push(column)
      }
      const described = describeEvent(ev, detail)
      const accent = tones[described.tone] || TONES[described.tone] || TONES.feedback
      const emphasis = described.emphasis === 'conclusion' || conclusionPos === i ? 'conclusion' : 'normal'
      if (!column.label) {
        column.label = described.label || TONE_LABELS[described.tone] || ''
        column.accent = accent
      }
      column.count += 1
      column.parallel = column.count > 1
      nodes.push({
        idx: i,
        col: column.col,
        lane: column.count - 1,
        role: text(ev.role),
        accent: accent,
        tone: described.tone,
        family: described.family,
        glyph: described.glyph,
        label: described.label,
        step: step,
        title: described.title,
        subtitle: described.subtitle,
        meta: described.meta,
        badges: described.badges,
        emphasis: emphasis,
      })
      if (i > 0) {
        edges.push({ from: i - 1, to: i, kind: 'main' })
      }
    }

    return {
      columns: columns,
      nodes: nodes,
      edges: edges,
      meta: {
        stepCount: columns.length,
        eventCount: nodes.length,
        conclusionIndex: conclusionPos,
      },
    }
  }

  // 把亮色基准换成当前主题色（暗色由主题模块提亮）。
  function applyTones(graph, tones) {
    if (!graph || !tones) return graph
    const columns = graph.columns.map(function (column) {
      return Object.assign({}, column, { accent: tones[columnTone(column, graph)] || column.accent })
    })
    const nodes = graph.nodes.map(function (node) {
      return Object.assign({}, node, { accent: tones[node.tone] || node.accent })
    })
    return Object.assign({}, graph, { columns: columns, nodes: nodes })
  }

  // 列 accent 取该列第一个节点的家族。
  function columnTone(column, graph) {
    const node = graph.nodes.find(function (item) { return item.col === column.col })
    return node ? node.tone : 'feedback'
  }

  function verdictEntries(verdict) {
    const labels = {
      primary: '主检查',
      fallback: '备用检查',
      marked: '标记',
      result: '结果',
      confidence: '置信度',
      check: '判据',
      verdict: '判决',
    }
    const entries = []
    for (const key of ['check', 'primary', 'fallback', 'marked', 'result', 'confidence', 'verdict']) {
      const value = verdict && verdict[key]
      if (value === null || value === undefined || value === '') continue
      entries.push({ key: key, label: labels[key], value: text(value), tone: key === 'marked' && String(value) !== 'excluded' ? 'warn' : 'neutral' })
    }
    return entries
  }

  function formatFieldValue(value) {
    if (value === null || value === undefined) return '—'
    if (Array.isArray(value)) return value.map(text).join('、')
    if (typeof value === 'object') {
      try { return JSON.stringify(value) } catch (error) { return text(value) }
    }
    return text(value)
  }

  function fieldsOf(ev) {
    const fields = (ev && ev.fields) || {}
    const entries = []
    for (const key of Object.keys(fields)) {
      if (CONSUMED_FIELDS[key]) continue
      entries.push({ key: key, label: key, value: formatFieldValue(fields[key]) })
    }
    return entries
  }

  // 选中节点的检查器数据。section.kind 决定页面怎么画：
  // prose / kv / evidence / chips / tools / fields。
  function buildInspector(detail, idx, graphOpt) {
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    if (!events.length || idx === null || idx === undefined || idx < 0 || idx >= events.length) return null
    const ev = events[idx] || {}
    const graph = graphOpt || buildGraph(detail)
    const node = graph.nodes[idx] || null
    const described = node ? { title: node.title, label: node.label, tone: node.tone, family: node.family, glyph: node.glyph, emphasis: node.emphasis } : describeEvent(ev, detail)
    const column = graph.columns.find(function (item) { return item.col === (node ? node.col : 0) })
    const stepCount = graph.columns.length
    const sections = []

    const what = text(ev.output) || text(ev.content)
    if (what) {
      sections.push({ key: 'what', title: '做了什么', kind: 'prose', paragraphs: U.paragraphs(what, 200), collapsed: false })
    }
    const why = text(ev.reason) || text(ev.note) || text(ev.purpose)
    if (why) {
      sections.push({ key: 'why', title: '为什么', kind: 'prose', paragraphs: U.paragraphs(why, 200), collapsed: false })
    }

    if (ev.action === 'quickly_check' || ev.action === 'hit') {
      const entries = verdictEntries(ev.verdict)
      if (entries.length) sections.push({ key: 'verdict', title: '判据', kind: 'kv', entries: entries, collapsed: false })
    }

    const evidence = ev.evidence || null
    if (evidence) {
      const inline = text(evidence.inline)
      const files = valuesOf(evidence.files)
      const sources = valuesOf(evidence.sources).concat(valuesOf(ev.sources)).filter(function (item, at, list) { return list.indexOf(item) === at })
      const missing = text(evidence.missing)
      if (inline || files.length || sources.length || missing) {
        sections.push({
          key: 'evidence',
          title: '现场证据',
          kind: 'evidence',
          inline: inline ? { text: inline, chars: Number(evidence.inlineChars || 0) || U.chars(inline).length } : null,
          files: files,
          sources: sources,
          missing: missing,
          collapsed: true,
        })
      }
    }

    const chipGroups = []
    const caseId = text(ev.case)
    if (caseId) chipGroups.push({ label: 'case', values: [caseId], tone: 'hit' })
    for (const key of ['candidates', 'considered', 'excluded', 'refs']) {
      const values = valuesOf(ev[key])
      if (values.length) chipGroups.push({ label: key, values: values, tone: key === 'excluded' ? 'miss' : key === 'refs' ? 'book' : 'neutral' })
    }
    if (chipGroups.length) sections.push({ key: 'related', title: '关联', kind: 'chips', groups: chipGroups, collapsed: true })

    const tools = valuesOf(ev.toolCalls)
    if (tools.length) sections.push({ key: 'tools', title: '工具调用', kind: 'tools', items: tools, collapsed: true })

    const fieldEntries = fieldsOf(ev)
    if (fieldEntries.length) sections.push({ key: 'fields', title: '其余字段', kind: 'fields', entries: fieldEntries, collapsed: true })

    const parallel = column && column.count > 1 ? { count: column.count, sameStep: true, group: text(ev.parallelGroup) || null } : null
    return {
      idx: idx,
      total: events.length,
      step: ev.step !== null && ev.step !== undefined ? ev.step : '?',
      stepCount: stepCount,
      role: text(ev.role),
      roleLabel: roleLabel(ev),
      family: described.family,
      tone: described.tone,
      glyph: described.glyph,
      label: described.label,
      title: described.title,
      emphasis: described.emphasis,
      parallel: parallel,
      sections: sections,
      fields: (ev && ev.fields) || {},
      prev: idx > 0 ? idx - 1 : null,
      next: idx < events.length - 1 ? idx + 1 : null,
    }
  }

  function insightTone(value) {
    const allowed = { info: 1, good: 1, warn: 1, risk: 1, neutral: 1 }
    return allowed[value] ? value : 'neutral'
  }

  // 未选中时的概览：insights + 家族图例 + 数据来源脚注。
  function buildOverview(detail, graphOpt) {
    const graph = graphOpt || buildGraph(detail)
    const insights = Array.isArray(detail && detail.insights) ? detail.insights.map(function (item) {
      return {
        id: text(item && item.id),
        tone: insightTone(item && item.tone),
        title: text(item && item.title),
        text: text(item && item.text),
      }
    }).filter(function (item) { return item.title || item.text }) : []

    const seen = Object.create(null)
    const legend = []
    for (const node of graph.nodes) {
      if (seen[node.tone]) {
        seen[node.tone].count += 1
        continue
      }
      seen[node.tone] = { tone: node.tone, label: TONE_LABELS[node.tone] || node.label, count: 1 }
      legend.push(seen[node.tone])
    }
    const file = text(detail && detail.file) || text(detail && detail.session && detail.session.file)
    return {
      insights: insights,
      legend: legend,
      warnings: Array.isArray(detail && detail.warnings) ? detail.warnings.map(text).filter(Boolean) : [],
      footnote: '数据来自 traces/' + (file || '（未知文件）') + ' · 只读',
      steps: graph.columns.length,
      events: graph.nodes.length,
      conclusionIndex: graph.meta ? graph.meta.conclusionIndex : null,
    }
  }

  // 页头 chips 与数量。数量能算就算，不写“多个”。
  function deriveStats(detail) {
    const session = (detail && detail.session) || {}
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    const steps = (function () {
      const seen = Object.create(null)
      let count = 0
      for (const ev of events) {
        const key = text(ev && ev.step)
        if (key && !seen[key]) { seen[key] = true; count += 1 }
      }
      return count
    })()
    const stepCount = isNum(session.stepCount) ? Number(session.stepCount) : (steps || null)
    const eventCount = events.length || (isNum(session.eventCount) ? Number(session.eventCount) : 0)
    const status = U.statusTone(session.status)
    const chips = []
    chips.push({ key: 'status', label: '状态', value: status.label, tone: status.tone, dot: true })
    if (session.framework) chips.push({ key: 'framework', label: '框架', value: text(session.framework), tone: 'book' })
    if (session.platform) chips.push({ key: 'platform', label: '平台', value: text(session.platform), tone: 'index' })
    if (session.category) chips.push({ key: 'category', label: '类别', value: text(session.category), tone: 'check' })
    return {
      status: status,
      chips: chips,
      framework: text(session.framework) || null,
      platform: text(session.platform) || null,
      category: text(session.category) || null,
      stepCount: stepCount,
      eventCount: eventCount,
      currentStep: isNum(session.currentStep) ? Number(session.currentStep) : null,
      hasConclusion: !!session.hasConclusion,
      harnessSession: text(session.harnessSession) || null,
      activeCase: text((detail && detail.activeCase) || session.activeCase) || null,
      file: text((detail && detail.file) || session.file) || null,
      summary: text((detail && detail.summary) || session.summary) || '',
      lastAction: text((detail && detail.lastAction) || session.lastAction) || '',
      createdAt: session.createdAt || null,
      updatedAt: session.updatedAt || null,
      relativeUpdated: U.formatRelative(session.updatedAt),
      span: U.formatSpan(session.createdAt, session.updatedAt),
      excludedCount: ((detail && detail.excludedCases) || session.excludedCases || []).length,
      sedimented: (detail && detail.sedimented) || session.sedimented || null,
      feedback: (detail && detail.feedback) || session.feedback || null,
    }
  }

  // 列表卡片的一行元信息：框架 · 平台 · N 步 · 排除 N。
  function sessionMeta(session) {
    const parts = []
    if (session && session.framework) parts.push(text(session.framework))
    if (session && session.platform) parts.push(text(session.platform))
    if (isNum(session && session.stepCount)) parts.push(Number(session.stepCount) + ' 步')
    const excluded = session && Array.isArray(session.excludedCases) ? session.excludedCases.length : 0
    if (excluded) parts.push('排除 ' + excluded)
    return parts
  }

  // ── 结论卡、列表视图、导出摘要：给页面的三个派生视图，纯函数便于测试 ─────────────

  // 结论动作 → 卡片文案。未命中 case 时不编造结论，只说"还没写结论"。
  const CONCLUSION_ACTIONS = {
    hit: { tone: 'hit', label: '命中 case' },
    miss: { tone: 'miss', label: '知识库未覆盖' },
    output: { tone: 'flag', label: '给出结论' },
    attribution: { tone: 'flag', label: '归因' },
  }

  const RISK_RE = /data-loss-risk|数据风险|先停|数据丢失/g
  const RISK_NEGATIONS = ['非', '不是', '并非', '无', '没有', '不含', '未发现', '零']

  function hasRiskText(value) {
    const raw = text(value)
    if (!raw) return false
    RISK_RE.lastIndex = 0
    let matched = RISK_RE.exec(raw)
    while (matched) {
      const before = raw.slice(Math.max(0, matched.index - 4), matched.index)
      if (!RISK_NEGATIONS.some(function (word) { return before.indexOf(word) >= 0 })) return true
      matched = RISK_RE.exec(raw)
    }
    return false
  }

  // 结论卡：读 detail.conclusionIndex（事件 idx），返回画布节点位置与可读文案。
  function buildConclusion(detail, graph) {
    if (!detail) return null
    const events = Array.isArray(detail.events) ? detail.events : []
    const nodes = graph && Array.isArray(graph.nodes) ? graph.nodes : []
    const pos = graph && graph.meta && graph.meta.conclusionIndex !== null && graph.meta.conclusionIndex !== undefined
      ? Number(graph.meta.conclusionIndex)
      : null
    const event = pos !== null && events[pos] ? events[pos] : null
    const node = pos !== null && nodes[pos] ? nodes[pos] : null
    const action = text(event && event.action)
    const spec = CONCLUSION_ACTIONS[action] || null
    const tone = spec ? spec.tone : (node ? node.tone : 'feedback')
    const caseId = text(event && event.case)
    let label = spec ? spec.label : '结论未记录'
    let title = ''
    if (action === 'hit') title = caseId ? '命中 ' + caseId : '命中'
    else if (action === 'miss') title = '知识库未覆盖'
    else if (action === 'output') title = '给出结论'
    else if (action === 'attribution') title = caseId ? '归因 · ' + caseId : '归因'
    else title = '还没写结论'
    const body = event
      ? U.firstSentence(text(event.output) || text(event.reason) || text(event.content), 150)
      : U.firstSentence(text(detail.lastAction) || '这份 trace 还没写结论事件', 120)
    const badges = []
    const verdict = (event && event.verdict) || {}
    if (text(verdict.confidence)) badges.push(badge('置信 ' + text(verdict.confidence), 'neutral'))
    const feedback = detail.feedback || {}
    if (text(feedback.outcome) === 'pending') badges.push(badge('待回报', 'warn'))
    else if (text(feedback.outcome) === 'resolved') badges.push(badge('已回报', 'hit'))
    const sedimented = detail.sedimented || {}
    const sedState = text(sedimented.state)
    if (sedState === 'knowledge') badges.push(badge('已沉淀' + (text(sedimented.caseId) ? ' ' + text(sedimented.caseId) : ''), 'book'))
    else if (sedState === 'inbox') badges.push(badge('已交草稿', 'book'))
    const riskText = [event && event.output, event && event.reason, detail.lastAction].map(text).join('\n')
    if (hasRiskText(riskText)) badges.push(badge('风险 · 先停', 'risk'))
    return {
      idx: node ? node.idx : null,
      step: node ? node.step : null,
      tone: tone,
      label: label,
      title: title,
      text: body,
      badges: badges,
      empty: event === null || action === '',
      action: action,
      caseId: caseId || null,
    }
  }

  // 列表视图：每个事件一行，与画布节点共享选中下标（数组位置）。
  function buildTableRows(detail, graph) {
    if (!detail || !Array.isArray(detail.events)) return []
    const nodes = graph && Array.isArray(graph.nodes) ? graph.nodes : []
    return detail.events.map(function (ev, i) {
      const node = nodes[i] || null
      const described = describeEvent(ev, detail)
      const verdict = (ev && ev.verdict) || {}
      const marks = []
      if (text(ev.case)) marks.push(text(ev.case))
      if (text(verdict.primary)) marks.push('主检查 ' + text(verdict.primary))
      if (text(verdict.fallback)) marks.push('备检查 ' + text(verdict.fallback))
      if (text(verdict.marked)) marks.push('marked ' + text(verdict.marked))
      const evidence = (ev && ev.evidence) || {}
      const inlineChars = Number(evidence.inlineChars || 0) || text(evidence.inline).length
      if (inlineChars > 0) marks.push('证据 ' + charLabel(inlineChars))
      if (Array.isArray(ev.toolCalls) && ev.toolCalls.length) marks.push(ev.toolCalls.length + ' 次调用')
      if (Array.isArray(ev.sources) && ev.sources.length) marks.push(ev.sources.length + ' 来源')
      return {
        idx: i,
        step: node ? node.step : (ev.step === null || ev.step === undefined ? '?' : ev.step),
        role: text(ev.role),
        roleLabel: roleLabel(ev),
        action: node ? node.label : (described.label || '事件'),
        title: node ? node.title : described.title,
        subtitle: node ? (node.subtitle || '') : described.subtitle,
        tone: node ? node.tone : (described.tone || 'feedback'),
        glyph: node ? node.glyph : described.glyph,
        emphasis: node ? node.emphasis : described.emphasis,
        marks: marks,
      }
    })
  }

  // 导出摘要：一段可粘贴的 Markdown，覆盖结论、洞察与过程。
  function buildExportText(detail, graph) {
    if (!detail) return ''
    const session = detail.session || {}
    const conclusion = buildConclusion(detail, graph)
    const rows = buildTableRows(detail, graph)
    const lines = []
    lines.push('# 诊断旅程 · ' + (text(session.id) || text(detail.file) || '未命名'))
    const meta = []
    if (text(session.status)) meta.push('状态 ' + text(session.status))
    if (text(session.framework)) meta.push('框架 ' + text(session.framework))
    if (text(session.platform)) meta.push('平台 ' + text(session.platform))
    if (text(session.category)) meta.push('类别 ' + text(session.category))
    if (isNum(session.stepCount)) meta.push(Number(session.stepCount) + ' 步')
    if (isNum(session.eventCount)) meta.push(Number(session.eventCount) + ' 个事件')
    if (meta.length) lines.push('- ' + meta.join(' · '))
    const span = U.formatSpan(session.createdAt, session.updatedAt)
    if (span) lines.push('- 跨度 ' + span + (text(session.updatedAt) ? '（更新于 ' + U.formatRelative(session.updatedAt) + '）' : ''))
    if (conclusion) {
      const tags = conclusion.badges.map(function (item) { return item.text }).filter(Boolean)
      lines.push('')
      lines.push('## 结论 · ' + conclusion.title + (tags.length ? '（' + tags.join(' · ') + '）' : ''))
      if (conclusion.text) lines.push(conclusion.text)
    }
    const insights = Array.isArray(detail.insights) ? detail.insights : []
    if (insights.length) {
      lines.push('')
      lines.push('## 洞察')
      for (const insight of insights) {
        lines.push('- ' + text(insight.title) + '：' + text(insight.text))
      }
    }
    if (rows.length) {
      lines.push('')
      lines.push('## 过程')
      for (const row of rows) {
        const tail = (row.subtitle || row.title || '').slice(0, 80)
        lines.push('- S' + row.step + ' · ' + row.action + ' · ' + row.roleLabel + (tail ? ' · ' + tail : ''))
      }
    }
    lines.push('')
    lines.push('来源：traces/' + (text(detail.file) || '') + ' · 只读')
    return lines.join('\n')
  }

  return {
    TONES: TONES,
    TONE_LABELS: TONE_LABELS,
    ACTIONS: ACTIONS,
    VERBS: VERBS,
    resolve: resolve,
    describeEvent: describeEvent,
    buildGraph: buildGraph,
    applyTones: applyTones,
    buildInspector: buildInspector,
    buildOverview: buildOverview,
    buildConclusion: buildConclusion,
    buildTableRows: buildTableRows,
    buildExportText: buildExportText,
    hasRiskText: hasRiskText,
    deriveStats: deriveStats,
    sessionMeta: sessionMeta,
    eventChars: eventChars,
    charLabel: charLabel,
    roleLabel: roleLabel,
  }
})()
})(SC)

// ─── client-src/30-page.js ───
;(function (SC) {
// 页面：页头 + 三栏（会话列表 264 / 画布 flex / 检查器 336）+ 回放条 + tooltip + 空/加载/错误态。
//
// 只做 DOM 与状态编排：数据来自 SC.host.call('list'|'detail')，画布像素交给 SC.createEngine，
// 颜色/字体/格式工具分别来自 SC.theme / SC.model / SC.util。React 从 SC.React 取。

SC.CanvasPage = (function () {
  const U = SC.util
  const clamp = U.clamp

  // ── 线性图标（24×24，stroke 1.6）─────────────────────────────────────────────
  const ICONS = {
    refresh: [['path', { d: 'M20 11.2a8.2 8.2 0 1 1-2.4-5.8' }], ['path', { d: 'M20.2 4.4v5.2h-5.2' }]],
    search: [['circle', { cx: 10.8, cy: 10.8, r: 6.3 }], ['path', { d: 'M15.4 15.4 20 20' }]],
    play: [['path', { d: 'M8.6 5.8v12.4l10.2-6.2z', fill: 'currentColor', stroke: 'none' }]],
    pause: [
      ['rect', { x: 7.6, y: 5.8, width: 3.2, height: 12.4, rx: 1.2, fill: 'currentColor', stroke: 'none' }],
      ['rect', { x: 13.2, y: 5.8, width: 3.2, height: 12.4, rx: 1.2, fill: 'currentColor', stroke: 'none' }],
    ],
    close: [['path', { d: 'M6.5 6.5 17.5 17.5' }], ['path', { d: 'M17.5 6.5 6.5 17.5' }]],
    chevron: [['path', { d: 'M8 10.5 12 14.5 16 10.5' }]],
    'chevron-up': [['path', { d: 'M8 13.5 12 9.5 16 13.5' }]],
    plus: [['path', { d: 'M12 6v12' }], ['path', { d: 'M6 12h12' }]],
    minus: [['path', { d: 'M6 12h12' }]],
    fit: [
      ['path', { d: 'M9 4.5H5.5V8' }], ['path', { d: 'M15 4.5h3.5V8' }],
      ['path', { d: 'M9 19.5H5.5V16' }], ['path', { d: 'M15 19.5h3.5V16' }],
    ],
    open: [['path', { d: 'M13 5h6v6' }], ['path', { d: 'M19 5 10.5 13.5' }], ['path', { d: 'M18.4 14.2v4.2a1.8 1.8 0 0 1-1.8 1.8H5.4a1.8 1.8 0 0 1-1.8-1.8V7.2a1.8 1.8 0 0 1 1.8-1.8h4.2' }]],
    download: [['path', { d: 'M12 4.5v10' }], ['path', { d: 'M7.5 10.5 12 15l4.5-4.5' }], ['path', { d: 'M5 19.5h14' }]],
    table: [['rect', { x: 4, y: 5, width: 16, height: 14, rx: 2 }], ['path', { d: 'M4 10h16' }], ['path', { d: 'M4 14.5h16' }], ['path', { d: 'M9.5 5v14' }]],
    canvas: [['rect', { x: 4, y: 5, width: 16, height: 14, rx: 2 }], ['path', { d: 'M8 15.5 11 11l2.6 3.4 2.1-2.5 2.3 3.6' }]],
    copy: [
      ['rect', { x: 8.4, y: 8.4, width: 10.6, height: 10.6, rx: 2.2 }],
      ['path', { d: 'M15.8 8.4V6.6A2.6 2.6 0 0 0 13.2 4H6.6A2.6 2.6 0 0 0 4 6.6v6.6a2.6 2.6 0 0 0 2.6 2.6h1.8' }],
    ],
    'arrow-left': [['path', { d: 'M14.5 6 8.5 12l6 6' }]],
    'arrow-right': [['path', { d: 'M9.5 6 15.5 12l-6 6' }]],
    list: [['path', { d: 'M5 7h14' }], ['path', { d: 'M5 12h14' }], ['path', { d: 'M5 17h10' }]],
    insight: [['path', { d: 'M12 4.5 13.8 10.2 19.5 12 13.8 13.8 12 19.5 10.2 13.8 4.5 12 10.2 10.2z' }]],
    warning: [
      ['path', { d: 'M12 4.6 21 19.5H3z' }],
      ['path', { d: 'M12 9.6v4.5' }],
      ['circle', { cx: 12, cy: 16.8, r: 0.9, fill: 'currentColor', stroke: 'none' }],
    ],
    intake: [
      ['path', { d: 'M12 4.5v9' }], ['path', { d: 'M8.5 9.8 12 13.3l3.5-3.5' }],
      ['path', { d: 'M5 14.5v3A2 2 0 0 0 7 19.5h10a2 2 0 0 0 2-2v-3' }],
    ],
    route: [
      ['path', { d: 'M5 6.5h3.6a2 2 0 0 1 1.6.9L13 12l-2.8 4.6a2 2 0 0 1-1.6.9H5' }],
      ['path', { d: 'M13 12h6' }],
      ['circle', { cx: 20.6, cy: 12, r: 1.2, fill: 'currentColor', stroke: 'none' }],
    ],
    index: [
      ['rect', { x: 5, y: 4.6, width: 14, height: 4, rx: 1.3 }],
      ['rect', { x: 5, y: 10, width: 14, height: 4, rx: 1.3 }],
      ['rect', { x: 5, y: 15.4, width: 14, height: 4, rx: 1.3 }],
    ],
    check: [['circle', { cx: 12, cy: 12, r: 7.5 }], ['path', { d: 'M8.4 12.2 11 14.8 15.7 9.4' }]],
    cross: [
      ['circle', { cx: 12, cy: 12, r: 7.5 }],
      ['path', { d: 'M9.3 9.3l5.4 5.4' }], ['path', { d: 'M14.7 9.3l-5.4 5.4' }],
    ],
    book: [
      ['path', { d: 'M4.5 6.2c2.6-1 5.2-1 7.5.7v12c-2.3-1.7-4.9-1.7-7.5-.7z' }],
      ['path', { d: 'M19.5 6.2c-2.6-1-5.2-1-7.5.7v12c2.3-1.7 4.9-1.7 7.5-.7z' }],
    ],
    code: [
      ['path', { d: 'M9 8.5 5.5 12 9 15.5' }], ['path', { d: 'M15 8.5 18.5 12 15 15.5' }],
      ['path', { d: 'M13.2 6.6 10.8 17.4' }],
    ],
    hit: [
      ['circle', { cx: 12, cy: 12, r: 7.4 }], ['circle', { cx: 12, cy: 12, r: 3.4 }],
      ['circle', { cx: 12, cy: 12, r: 0.9, fill: 'currentColor', stroke: 'none' }],
    ],
    miss: [['circle', { cx: 12, cy: 12, r: 7.4 }], ['path', { d: 'M8.2 15.8 15.8 8.2' }]],
    flag: [
      ['path', { d: 'M6.5 20V4.8' }],
      ['path', { d: 'M6.5 5.2h10.4l-1.7 3.5 1.7 3.5H6.5' }],
    ],
    doc: [
      ['rect', { x: 6, y: 4.5, width: 12, height: 15, rx: 2 }],
      ['path', { d: 'M9 9h6' }], ['path', { d: 'M9 12.5h6' }], ['path', { d: 'M9 16h3.5' }],
    ],
    loop: [['path', { d: 'M5.4 11.6a6.7 6.7 0 1 1 2 4.8' }], ['path', { d: 'M5.4 7.2v4.6h4.6' }]],
    feedback: [
      ['path', { d: 'M5 6.8A2.3 2.3 0 0 1 7.3 4.5h9.4A2.3 2.3 0 0 1 19 6.8v6.4a2.3 2.3 0 0 1-2.3 2.3H11l-4.2 3.6v-3.6H7.3A2.3 2.3 0 0 1 5 13.2z' }],
    ],
    dot: [['circle', { cx: 12, cy: 12, r: 3.2, fill: 'currentColor', stroke: 'none' }]],
  }

  function Icon(props) {
    const name = props.name || 'dot'
    const size = props.size || 16
    const parts = ICONS[name] || ICONS.dot
    return SC.h(
      'svg',
      {
        viewBox: '0 0 24 24',
        width: size,
        height: size,
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.6,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        className: props.className || '',
        'aria-hidden': 'true',
      },
      parts.map(function (part, i) {
        const attrs = Object.assign({}, part[1], { key: i })
        return SC.h(part[0], attrs)
      }),
    )
  }

  // 页头标记：与 package icon.svg 同形（圆角方框 + 一条旅程曲线 + 三个节点）。
  function Mark(props) {
    const size = props.size || 26
    return SC.h(
      'svg',
      { viewBox: '0 0 64 64', width: size, height: size, fill: 'none', 'aria-hidden': 'true', className: 'sc-mark' },
      SC.h(
        'defs',
        null,
        SC.h(
          'linearGradient',
          { id: 'sc-mark-grad', x1: 10, y1: 8, x2: 54, y2: 56, gradientUnits: 'userSpaceOnUse' },
          SC.h('stop', { stopColor: '#4A7DFF' }),
          SC.h('stop', { offset: 1, stopColor: '#2AA7B8' }),
        ),
      ),
      SC.h('rect', { x: 4, y: 4, width: 56, height: 56, rx: 16, fill: 'url(#sc-mark-grad)', opacity: 0.14 }),
      SC.h('rect', { x: 4, y: 4, width: 56, height: 56, rx: 16, stroke: 'url(#sc-mark-grad)', strokeWidth: 2.4, opacity: 0.55 }),
      SC.h('path', { d: 'M17 43.5c7.5 0 7.5-11.5 15-11.5s7.5 9.5 15 9.5', stroke: 'url(#sc-mark-grad)', strokeWidth: 2.6, strokeLinecap: 'round', opacity: 0.9 }),
      SC.h('circle', { cx: 17, cy: 43.5, r: 4.4, fill: '#D9902F' }),
      SC.h('circle', { cx: 32, cy: 32, r: 4.4, fill: '#8A6CF0' }),
      SC.h('circle', { cx: 47, cy: 41.5, r: 4.4, fill: '#3FA46A' }),
    )
  }

  // ── 小工具 ─────────────────────────────────────────────────────────────────
  const GLYPH_ICONS = {
    intake: 'intake', route: 'route', index: 'index', check: 'check', cross: 'cross',
    book: 'book', code: 'code', hit: 'hit', miss: 'miss', flag: 'flag', doc: 'doc',
    loop: 'loop', feedback: 'feedback', dot: 'dot',
  }

  const INSIGHT_TONES = { info: 'route', good: 'hit', warn: 'warn', risk: 'risk', neutral: 'feedback' }

  function reducedMotion() {
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    } catch (error) {
      return false
    }
  }

  function errorText(error) {
    if (!error) return '未知错误'
    if (typeof error === 'string') return error
    return String(error.message || error.error || error)
  }

  function toneMap() {
    try {
      const palette = SC.theme && SC.theme.currentPalette ? SC.theme.currentPalette() : null
      return (palette && palette.tones) || SC.model.TONES
    } catch (error) {
      return SC.model.TONES
    }
  }

  function sortSessions(sessions, key) {
    const list = sessions.slice()
    const updated = function (session) {
      const ms = U.parseTime(session && session.updatedAt)
      return ms === null ? -Infinity : ms
    }
    const byUpdated = function (a, b) {
      const gap = updated(b) - updated(a)
      if (gap) return gap
      return String(b && b.id).localeCompare(String(a && a.id))
    }
    if (key === 'steps') {
      list.sort(function (a, b) {
        const gap = (Number(b && b.stepCount) || 0) - (Number(a && a.stepCount) || 0)
        return gap || byUpdated(a, b)
      })
      return list
    }
    list.sort(byUpdated)
    return list
  }

  function matchesQuery(session, query) {
    if (!query) return true
    const needle = query.toLowerCase()
    const haystack = [
      session && session.id,
      session && session.summary,
      session && session.framework,
      session && session.platform,
      session && session.category,
      session && session.activeCase,
      session && session.lastAction,
    ].map(function (value) { return String(value === null || value === undefined ? '' : value).toLowerCase() }).join('\n')
    return haystack.indexOf(needle) >= 0
  }

  function sectionOpen(section, expanded) {
    if (!section) return false
    if (section.collapsed) return !!expanded[section.key]
    return expanded[section.key] !== false
  }

  // ── 纯展示组件 ─────────────────────────────────────────────────────────────
  function Skeleton() {
    return SC.h(
      'div',
      { className: 'sc-loading' },
      SC.h(
        'header',
        { className: 'sc-header' },
        SC.h(
          'div',
          { className: 'sc-brand' },
          SC.h('div', { className: 'sc-skel sc-skel-mark' }),
          SC.h('div', { className: 'sc-titles' }, SC.h('div', { className: 'sc-skel sc-skel-title' }), SC.h('div', { className: 'sc-skel sc-skel-sub' })),
        ),
        SC.h('div', { className: 'sc-skel sc-skel-chips' }),
      ),
      SC.h(
        'div',
        { className: 'sc-body' },
        SC.h(
          'aside',
          { className: 'sc-list' },
          SC.h('div', { className: 'sc-skel sc-skel-search' }),
          [0, 1, 2, 3].map(function (i) {
            return SC.h('div', { className: 'sc-skel sc-skel-card', key: i })
          }),
        ),
        SC.h('section', { className: 'sc-stage' }, SC.h('div', { className: 'sc-skel sc-skel-canvas' })),
        SC.h(
          'aside',
          { className: 'sc-inspector' },
          SC.h('div', { className: 'sc-skel sc-skel-line is-wide' }),
          SC.h('div', { className: 'sc-skel sc-skel-line' }),
          SC.h('div', { className: 'sc-skel sc-skel-line is-short' }),
          SC.h('div', { className: 'sc-skel sc-skel-line is-wide' }),
          SC.h('div', { className: 'sc-skel sc-skel-line' }),
        ),
      ),
    )
  }

  function EmptyCard(props) {
    return SC.h(
      'div',
      { className: 'sc-empty-card' + (props.tone ? ' is-' + props.tone : '') },
      props.icon ? SC.h('div', { className: 'sc-empty-icon' }, props.icon) : null,
      SC.h('div', { className: 'sc-empty-title' }, props.title),
      props.text ? SC.h('p', { className: 'sc-empty-text' }, props.text) : null,
      props.children || null,
    )
  }

  function EmptyState(props) {
    const warnings = props.warnings || []
    const repo = props.repo
    return SC.h(
      'div',
      { className: 'sc-state-screen' },
      SC.h(
        EmptyCard,
        {
          icon: SC.h(Mark, { size: 42 }),
          title: '还没有诊断记录',
          text: warnings.length ? warnings[0] : 'traces/ 目录里没有 YAML。先跑一次诊断，再回来看这张画布。',
        },
        repo && repo.detected
          ? SC.h('div', { className: 'sc-state-path' }, SC.h('code', null, repo.path))
          : SC.h('div', { className: 'sc-state-path is-warn' }, '没找到 ascend-sleuth 仓库：在会话里打开该项目后刷新。'),
        SC.h(
          'div',
          { className: 'sc-command' },
          SC.h('code', null, '/skill:diagnose'),
          SC.h(
            'button',
            { type: 'button', className: 'sc-btn sc-btn-ghost', onClick: function () { props.onCopy('/skill:diagnose', 'command') } },
            SC.h(Icon, { name: 'copy', size: 13 }),
            props.copied === 'command' ? '已复制' : '复制',
          ),
        ),
        SC.h(
          'div',
          { className: 'sc-empty-actions' },
          SC.h('button', { type: 'button', className: 'sc-btn sc-btn-primary', onClick: props.onRetry }, '重新读取'),
        ),
      ),
    )
  }

  function ErrorState(props) {
    return SC.h(
      'div',
      { className: 'sc-state-screen' },
      SC.h(
        EmptyCard,
        { icon: SC.h(Icon, { name: 'warning', size: 28 }), title: '读取失败', text: props.message, tone: 'error' },
        props.hint ? SC.h('div', { className: 'sc-state-hint' }, props.hint) : null,
        SC.h(
          'div',
          { className: 'sc-empty-actions' },
          SC.h('button', { type: 'button', className: 'sc-btn sc-btn-primary', onClick: props.onRetry }, '重试'),
          SC.h(
            'button',
            { type: 'button', className: 'sc-btn sc-btn-ghost', onClick: function () { props.onCopy(props.message, 'error') } },
            SC.h(Icon, { name: 'copy', size: 13 }),
            props.copied === 'error' ? '已复制' : '复制错误原文',
          ),
        ),
      ),
    )
  }

  function Chip(props) {
    const value = String(props.value || '')
    return SC.h(
      'span',
      { className: 'sc-chip', title: props.title || value, style: { '--tone': 'var(--sc-' + (props.tone || 'feedback') + ')' } },
      props.dot ? SC.h('span', { className: 'sc-chip-dot' }) : null,
      props.label ? SC.h('span', { className: 'sc-chip-key' }, props.label) : null,
      SC.h('span', { className: 'sc-chip-value' }, value),
    )
  }

  // 本地偏好：只存三件与界面有关的小事（上次看的那单、快捷键提示是否关过、画布/列表视图）。
  // 都包在 try/catch 里：隐私模式或宿主禁用 localStorage 时退化为不记忆，不影响渲染。
  const STORE = {
    session: 'dsh-sleuth-canvas:last-session',
    hint: 'dsh-sleuth-canvas:hint-dismissed',
    view: 'dsh-sleuth-canvas:view',
  }

  function storeGet(key) {
    try { return window.localStorage.getItem(key) } catch (error) { return null }
  }

  function storeSet(key, value) {
    try {
      if (value === null) window.localStorage.removeItem(key)
      else window.localStorage.setItem(key, String(value))
    } catch (error) { /* 禁用存储时不记忆 */ }
  }

  function pngName(file) {
    const base = String(file || 'sleuth-canvas').replace(/\.yaml$/i, '').replace(/[^A-Za-z0-9._-]+/g, '-')
    return 'sleuth-canvas-' + base + '.png'
  }

  // ── 页面组件 ───────────────────────────────────────────────────────────────
  function CanvasPage(props) {
    const React = SC.React
    const useState = React.useState
    const useEffect = React.useEffect
    const useRef = React.useRef
    const useMemo = React.useMemo
    const useCallback = React.useCallback
    const sessionId = props && props.sessionId

    const [phase, setPhase] = useState('loading')
    const [listData, setListData] = useState(null)
    const [listError, setListError] = useState(null)
    const [refreshing, setRefreshing] = useState(false)
    const [activeFile, setActiveFile] = useState(null)
    const [detail, setDetail] = useState(null)
    const [detailPhase, setDetailPhase] = useState('idle')
    const [detailError, setDetailError] = useState(null)
    const [refreshTick, setRefreshTick] = useState(0)

    const [query, setQuery] = useState('')
    const [sortKey, setSortKey] = useState('updated')
    const [selected, setSelected] = useState(null)
    const [hovered, setHovered] = useState(null)
    const [tooltip, setTooltip] = useState(null)
    const [replay, setReplay] = useState({ active: false, playing: false, index: 0, speed: 1 })
    const [expanded, setExpanded] = useState({})
    const [inlineOpen, setInlineOpen] = useState(false)
    const [summaryOpen, setSummaryOpen] = useState(false)
    const [listOpen, setListOpen] = useState(false)
    const [inspectorOpen, setInspectorOpen] = useState(false)
    const [legendOpen, setLegendOpen] = useState(true)
    const [copied, setCopied] = useState('')
    const [view, setView] = useState(function () { return storeGet(STORE.view) === 'table' ? 'table' : 'canvas' })
    const [hintOpen, setHintOpen] = useState(function () { return storeGet(STORE.hint) !== '1' })
    const [exportOpen, setExportOpen] = useState(false)
    const [notice, setNotice] = useState('')

    const rootRef = useRef(null)
    const canvasRef = useRef(null)
    const inspBodyRef = useRef(null)
    const wrapRef = useRef(null)
    const engineRef = useRef(null)
    const fileRef = useRef(null)
    const sessionIdRef = useRef(sessionId)
    const listDataRef = useRef(null)
    const detailRef = useRef(null)
    const graphRef = useRef(null)
    const listReq = useRef(0)
    const detailReq = useRef(0)
    const handlersRef = useRef({ select: null, hover: null })
    const actionsRef = useRef({})
    const copiedTimer = useRef(0)
    const noticeTimer = useRef(0)
    const exportRef = useRef(null)
    const tooltipLast = useRef(null)

    listDataRef.current = listData
    detailRef.current = detail
    sessionIdRef.current = sessionId

    const tones = useMemo(toneMap, [detail])
    const graph = useMemo(function () {
      if (!detail) return null
      const raw = SC.model.buildGraph(detail)
      return SC.model.applyTones(raw, tones)
    }, [detail, tones])
    graphRef.current = graph
    const stats = useMemo(function () { return detail ? SC.model.deriveStats(detail) : null }, [detail])
    const overview = useMemo(function () { return detail ? SC.model.buildOverview(detail, graph) : null }, [detail, graph])
    const inspectorIdx = replay.active ? replay.index : selected
    const inspector = useMemo(function () {
      if (!detail || inspectorIdx === null || inspectorIdx === undefined) return null
      return SC.model.buildInspector(detail, inspectorIdx, graph)
    }, [detail, inspectorIdx, graph])
    const selectedNode = graph && selected !== null && selected !== undefined ? graph.nodes[selected] || null : null
    const hoveredNode = graph && hovered !== null && hovered !== undefined ? graph.nodes[hovered] || null : null
    const sessions = listData && Array.isArray(listData.sessions) ? listData.sessions : []
    const filtered = useMemo(function () {
      return sortSessions(sessions.filter(function (session) { return matchesQuery(session, query) }), sortKey)
    }, [sessions, query, sortKey])
    const activeSession = sessions.find(function (session) { return session.file === activeFile }) || null
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    const conclusion = useMemo(function () { return detail ? SC.model.buildConclusion(detail, graph) : null }, [detail, graph])
    const tableRows = useMemo(function () { return detail ? SC.model.buildTableRows(detail, graph) : [] }, [detail, graph])

    // ── 取数 ────────────────────────────────────────────────────────────────
    const loadList = useCallback(function (options) {
      const opts = options || {}
      const seq = ++listReq.current
      setRefreshing(!!opts.refresh)
      setListError(null)
      const host = SC.host
      if (!host || typeof host.call !== 'function') {
        setPhase('error')
        setListError(new Error('host RPC 未装配：拿不到 list / detail 数据'))
        setRefreshing(false)
        return
      }
      if (!opts.keepPhase) setPhase(function (prev) { return prev === 'ready' || prev === 'empty' ? prev : 'loading' })
      host.call('list', { sessionId: sessionIdRef.current }).then(function (data) {
        if (seq !== listReq.current) return
        const next = data && Array.isArray(data.sessions) ? data.sessions : []
        setListData(data || null)
        if (!next.length) {
          fileRef.current = null
          setActiveFile(null)
          setDetail(null)
          setDetailPhase('idle')
          setPhase('empty')
          return
        }
        const keep = next.find(function (session) { return session.file === fileRef.current })
        const remembered = storeGet(STORE.session)
        const saved = remembered ? next.find(function (session) { return session.file === remembered }) : null
        const pick = keep || saved || sortSessions(next, 'updated')[0]
        fileRef.current = pick.file
        storeSet(STORE.session, pick.file)
        setActiveFile(pick.file)
        setPhase('ready')
      }).catch(function (error) {
        if (seq !== listReq.current) return
        const failure = error instanceof Error ? error : new Error(errorText(error))
        setListError(failure)
        setPhase(function (prev) { return listDataRef.current ? prev : 'error' })
      }).then(function () {
        if (seq === listReq.current) setRefreshing(false)
      })
    }, [])

    useEffect(function () { loadList({}) }, [loadList])

    useEffect(function () {
      if (!activeFile) return undefined
      const seq = ++detailReq.current
      setDetailPhase('loading')
      setDetailError(null)
      const host = SC.host
      if (!host || typeof host.call !== 'function') {
        setDetailPhase('error')
        setDetailError(new Error('host RPC 未装配：拿不到 detail 数据'))
        return undefined
      }
      host.call('detail', { sessionId: sessionIdRef.current, file: activeFile }).then(function (data) {
        if (seq !== detailReq.current) return
        setDetail(data || null)
        setDetailPhase('ready')
        setSelected(null)
        setHovered(null)
        setReplay({ active: false, playing: false, index: 0, speed: 1 })
        setExpanded({})
        setInlineOpen(false)
        setSummaryOpen(false)
        setInspectorOpen(false)
      }).catch(function (error) {
        if (seq !== detailReq.current) return
        setDetail(null)
        setDetailPhase('error')
        setDetailError(error instanceof Error ? error : new Error(errorText(error)))
      })
      return undefined
    }, [activeFile, refreshTick])

    // ── 引擎装配（只建一次；回调走 ref，避免重建）───────────────────────────
    useEffect(function () {
      const canvas = canvasRef.current
      if (!canvas || typeof SC.createEngine !== 'function') return undefined
      let engine = null
      try {
        engine = SC.createEngine({
          canvas: canvas,
          palette: function () {
            try {
              return SC.theme && SC.theme.currentPalette ? SC.theme.currentPalette() : null
            } catch (error) {
              return null
            }
          },
          reducedMotion: reducedMotion(),
          onSelect: function (idx) {
            const handler = handlersRef.current.select
            if (handler) handler(idx)
          },
          onHover: function (idx) {
            const handler = handlersRef.current.hover
            if (handler) handler(idx)
          },
        })
      } catch (error) {
        console.error('[sleuth-canvas] 画布引擎初始化失败: ' + errorText(error))
      }
      engineRef.current = engine
      if (engine && graphRef.current) applyGraph(engine, graphRef.current)
      return function () {
        engineRef.current = null
        if (engine && typeof engine.destroy === 'function') {
          try { engine.destroy() } catch (error) { /* 卸载失败不阻塞页面 */ }
        }
      }
    }, [phase])

    function applyGraph(engine, nextGraph) {
      try {
        engine.setGraph(nextGraph)
        engine.setSelected(null)
        engine.setReplay(false)
        engine.setReplayFocus(null)
      } catch (error) {
        console.error('[sleuth-canvas] 设置画布图失败: ' + errorText(error))
      }
    }

    useEffect(function () {
      const engine = engineRef.current
      if (!engine || !graph) return
      applyGraph(engine, graph)
    }, [graph])

    // ── 状态 ↔ 引擎 ─────────────────────────────────────────────────────────
    function setEngineSelected(value) {
      const engine = engineRef.current
      if (engine && typeof engine.setSelected === 'function') {
        try { engine.setSelected(value) } catch (error) { /* 引擎未就绪 */ }
      }
    }

    useEffect(function () { setEngineSelected(selected) }, [selected])

    useEffect(function () {
      const engine = engineRef.current
      if (engine && typeof engine.setHovered === 'function') {
        try { engine.setHovered(hovered) } catch (error) { /* 引擎未就绪 */ }
      }
    }, [hovered])

    useEffect(function () {
      const engine = engineRef.current
      if (!engine) return
      try {
        if (typeof engine.setReplay === 'function') engine.setReplay(!!replay.active)
        if (typeof engine.setReplayFocus === 'function') engine.setReplayFocus(replay.active ? replay.index : null)
      } catch (error) { /* 引擎未就绪 */ }
    }, [replay.active])

    useEffect(function () {
      if (!replay.active) return
      const engine = engineRef.current
      if (!engine) return
      try {
        if (typeof engine.setReplayFocus === 'function') engine.setReplayFocus(replay.index)
        if (typeof engine.flyTo === 'function') engine.flyTo(replay.index, { duration: reducedMotion() ? 0 : 320 })
      } catch (error) { /* 引擎未就绪 */ }
    }, [replay.active, replay.index])

    // 回放节拍：每个节点停留 = clamp(900 + 字符数×6, 1400, 4200) / speed。
    useEffect(function () {
      if (!replay.active || !replay.playing || !detail) return undefined
      if (!events.length) return undefined
      const ev = events[replay.index] || {}
      const duration = clamp(900 + SC.model.eventChars(ev) * 6, 1400, 4200) / (replay.speed || 1)
      const timer = setTimeout(function () {
        setReplay(function (prev) {
          if (!prev.active || !prev.playing) return prev
          if (prev.index >= events.length - 1) return Object.assign({}, prev, { playing: false })
          return Object.assign({}, prev, { index: prev.index + 1 })
        })
      }, Math.max(120, duration))
      return function () { clearTimeout(timer) }
    }, [replay.active, replay.playing, replay.index, replay.speed, detail])

    // 选中/回放切节点时，检查器回到顶部（长文节点从“做了什么”读起）。
    useEffect(function () {
      const body = inspBodyRef.current
      if (body) body.scrollTop = 0
    }, [inspectorIdx])

    // hover tooltip：位置来自 engine.nodeRect(idx)，while-loop 跟随相机。
    useEffect(function () {
      if (hovered === null || hovered === undefined) {
        setTooltip(null)
        tooltipLast.current = null
        return undefined
      }
      const engine = engineRef.current
      const wrap = wrapRef.current
      if (!engine || typeof engine.nodeRect !== 'function' || !wrap) return undefined
      let raf = 0
      function tick() {
        let rect = null
        try { rect = engine.nodeRect(hovered) } catch (error) { rect = null }
        if (rect && rect.w) {
          const width = Math.min(288, Math.max(180, wrap.clientWidth - 24))
          const half = width / 2
          const x = clamp(rect.x + rect.w / 2, half + 12, wrap.clientWidth - half - 12)
          const below = rect.y < 96
          const y = below ? rect.y + rect.h + 10 : rect.y - 10
          const last = tooltipLast.current
          if (!last || Math.abs(last.x - x) > 0.8 || Math.abs(last.y - y) > 0.8 || last.below !== below) {
            tooltipLast.current = { x: x, y: y, below: below }
            setTooltip({ x: x, y: y, below: below })
          }
        }
        raf = requestAnimationFrame(tick)
      }
      raf = requestAnimationFrame(tick)
      return function () {
        if (raf) cancelAnimationFrame(raf)
      }
    }, [hovered])

    // ── 动作 ────────────────────────────────────────────────────────────────
    function stopReplay() {
      setReplay(function (prev) { return Object.assign({}, prev, { active: false, playing: false }) })
    }

    function selectIndex(idx) {
      if (idx === null || idx === undefined) {
        setSelected(null)
        setInspectorOpen(false)
        return
      }
      if (replay.active) stopReplay()
      setSelected(idx)
      setExpanded({})
      setInlineOpen(false)
      setInspectorOpen(true)
    }

    function hoverIndex(idx) {
      setHovered(idx === undefined ? null : idx)
    }

    useEffect(function () {
      handlersRef.current.select = selectIndex
      handlersRef.current.hover = hoverIndex
    })

    function fit() {
      const engine = engineRef.current
      if (engine && typeof engine.fit === 'function') {
        try { engine.fit({ animate: !reducedMotion() }) } catch (error) { /* 引擎未就绪 */ }
      }
    }

    function zoom(factor) {
      const engine = engineRef.current
      if (engine && typeof engine.zoomBy === 'function') {
        try { engine.zoomBy(factor) } catch (error) { /* 引擎未就绪 */ }
      }
    }

    function locate(idx) {
      if (idx === null || idx === undefined) return
      if (replay.active) stopReplay()
      setSelected(idx)
      setExpanded({})
      setInspectorOpen(true)
      const engine = engineRef.current
      if (engine && typeof engine.flyTo === 'function') {
        try { engine.flyTo(idx, { duration: reducedMotion() ? 0 : 320 }) } catch (error) { /* 引擎未就绪 */ }
      }
    }

    function stepNode(delta) {
      if (!detail) return
      const total = events.length
      if (!total) return
      if (replay.active) {
        setReplay(function (prev) {
          return Object.assign({}, prev, { index: clamp(prev.index + delta, 0, total - 1), playing: false })
        })
        return
      }
      const current = selected === null || selected === undefined ? (delta > 0 ? -1 : total) : selected
      selectIndex(clamp(current + delta, 0, total - 1))
    }

    function toggleReplay() {
      if (!detail || !events.length) return
      const total = events.length
      if (!replay.active) {
        // 回放聚光与手动选中是两种读法：开始回放先收起手动选中，退出后不留悬空选中。
        setSelected(null)
        setInspectorOpen(false)
        setReplay({ active: true, playing: true, index: 0, speed: replay.speed })
        return
      }
      if (!replay.playing && replay.index >= total - 1) {
        setReplay(Object.assign({}, replay, { playing: true, index: 0 }))
        return
      }
      setReplay(Object.assign({}, replay, { playing: !replay.playing }))
    }

    function jumpReplay(index) {
      if (!detail || !events.length) return
      const target = clamp(index, 0, events.length - 1)
      if (!replay.active) {
        setSelected(null)
        setInspectorOpen(false)
      }
      setReplay(Object.assign({}, replay, { active: true, playing: false, index: target }))
    }

    function refresh() {
      loadList({ refresh: true, keepPhase: true })
      setRefreshTick(function (value) { return value + 1 })
    }

    function openSession(session) {
      if (!session || !session.file) return
      setListOpen(false)
      if (session.file === fileRef.current) return
      if (replay.active) stopReplay()
      setSelected(null)
      setHovered(null)
      setInspectorOpen(false)
      fileRef.current = session.file
      storeSet(STORE.session, session.file)
      setActiveFile(session.file)
    }

    function copy(value, key) {
      const content = String(value === null || value === undefined ? '' : value)
      if (!content) return
      Promise.resolve(U.copyText(content)).then(function (ok) {
        if (!ok) return
        setCopied(key || content)
        if (copiedTimer.current) clearTimeout(copiedTimer.current)
        copiedTimer.current = setTimeout(function () { setCopied('') }, 1600)
      })
    }

    function showNotice(text) {
      const value = String(text === null || text === undefined ? '' : text)
      if (!value) return
      setNotice(value)
      if (noticeTimer.current) clearTimeout(noticeTimer.current)
      noticeTimer.current = setTimeout(function () { setNotice('') }, 2600)
    }

    function dismissHint() {
      setHintOpen(false)
      storeSet(STORE.hint, '1')
    }

    function toggleView() {
      setView(function (prev) {
        const next = prev === 'table' ? 'canvas' : 'table'
        storeSet(STORE.view, next)
        return next
      })
      setExportOpen(false)
    }

    function selectConclusion() {
      if (!conclusion || conclusion.idx === null || conclusion.idx === undefined) return
      setView('canvas')
      storeSet(STORE.view, 'canvas')
      locate(conclusion.idx)
    }

    function openConversation() {
      const target = stats && stats.harnessSession ? String(stats.harnessSession) : ''
      if (!target) {
        showNotice('这条 trace 没有 harness_session，挂不到 DSH 会话上')
        return
      }
      const opener = SC.openSession
      if (typeof opener !== 'function') {
        showNotice('当前界面没有提供打开会话的接口')
        return
      }
      Promise.resolve(opener(target)).then(function () {
        showNotice('已切到会话 ' + target.slice(0, 12))
      }).catch(function (error) {
        showNotice('打开会话失败：' + errorText(error))
      })
    }

    function exportPng() {
      const engine = engineRef.current
      if (!engine || typeof engine.exportImage !== 'function') {
        showNotice('画布还没渲染好，稍后再试')
        return
      }
      try {
        const url = engine.exportImage()
        if (!url) {
          showNotice('画布还没渲染好，稍后再试')
          return
        }
        const name = pngName(activeFile)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = name
        anchor.style.display = 'none'
        document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
        showNotice('已导出 PNG（' + name + '）')
      } catch (error) {
        showNotice('导出 PNG 失败：' + errorText(error))
      }
      setExportOpen(false)
    }

    function copySummary() {
      if (!detail) return
      const text = SC.model.buildExportText(detail, graph)
      Promise.resolve(U.copyText(text)).then(function (ok) {
        showNotice(ok ? '已复制旅程摘要' : '复制失败：剪贴板不可用')
      })
      setExportOpen(false)
    }

    useEffect(function () {
      return function () {
        if (copiedTimer.current) clearTimeout(copiedTimer.current)
        if (noticeTimer.current) clearTimeout(noticeTimer.current)
      }
    }, [])

    // 导出菜单：点面板外关闭；Esc 由键盘处理统一关。
    useEffect(function () {
      if (!exportOpen) return undefined
      if (typeof document === 'undefined' || !document || typeof document.addEventListener !== 'function') return undefined
      function onDown(event) {
        const node = exportRef.current
        if (node && event && event.target && typeof node.contains === 'function' && node.contains(event.target)) return
        setExportOpen(false)
      }
      document.addEventListener('pointerdown', onDown)
      return function () { document.removeEventListener('pointerdown', onDown) }
    }, [exportOpen])

    // 视图切回画布时容器从 display:none 恢复；effect 在 DOM 提交后跑，直接让引擎按当前尺寸重算。
    useEffect(function () {
      if (view !== 'canvas') return undefined
      const engine = engineRef.current
      if (!engine) return undefined
      try { if (typeof engine.resize === 'function') engine.resize() } catch (error) { /* 引擎未就绪 */ }
      return undefined
    }, [view])

    actionsRef.current = {
      stopReplay: stopReplay,
      toggleReplay: toggleReplay,
      stepNode: stepNode,
      fit: fit,
      zoom: zoom,
      setListOpen: setListOpen,
      selected: selected,
      replay: replay,
      detail: detail,
      listOpen: listOpen,
      view: view,
      toggleView: toggleView,
      setExportOpen: setExportOpen,
      dismissHint: dismissHint,
    }

    // 键盘：空格播放/暂停、←/→ 上/下一个事件、f 适配、+/- 缩放、Esc 取消。
    useEffect(function () {
      function onKeyDown(event) {
        const target = event.target
        const tag = target && target.tagName ? String(target.tagName).toLowerCase() : ''
        const editing = tag === 'input' || tag === 'textarea' || tag === 'select' || (target && target.isContentEditable)
        if (event.key === 'Escape') {
          if (editing) {
            if (target && typeof target.blur === 'function') target.blur()
            return
          }
          const actions = actionsRef.current
          if (actions.setExportOpen) actions.setExportOpen(false)
          if (actions.replay && actions.replay.active) { actions.stopReplay(); setInspectorOpen(false); return }
          if (actions.selected !== null && actions.selected !== undefined) { selectIndex(null); return }
          if (actions.listOpen) actions.setListOpen(false)
          return
        }
        if (editing || event.metaKey || event.ctrlKey || event.altKey) return
        // 只接管落在本页内的按键：页面挂在 main，别抢侧栏/输入区的快捷键。
        const root = rootRef.current
        if (
          root &&
          target &&
          typeof target.nodeType === 'number' &&
          target !== document.body &&
          target !== document.documentElement &&
          typeof root.contains === 'function' &&
          !root.contains(target)
        ) return
        const actions = actionsRef.current
        if (!actions.detail) return
        if (event.key === ' ') {
          event.preventDefault()
          actions.toggleReplay()
          return
        }
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault()
          actions.stepNode(event.key === 'ArrowRight' ? 1 : -1)
          return
        }
        const key = String(event.key || '').toLowerCase()
        if (key === 'f') { event.preventDefault(); actions.fit(); return }
        if (key === '+' || key === '=') { event.preventDefault(); actions.zoom(1.2); return }
        if (key === '-') { event.preventDefault(); actions.zoom(1 / 1.2); return }
        if (key === 't') { event.preventDefault(); actions.toggleView(); return }
      }
      window.addEventListener('keydown', onKeyDown)
      return function () { window.removeEventListener('keydown', onKeyDown) }
    }, [])

    // ── 渲染 ────────────────────────────────────────────────────────────────
    function renderChips() {
      if (stats && stats.chips.length) {
        return stats.chips.map(function (chip) {
          return SC.h(Chip, { key: chip.key, label: chip.label, value: chip.value, tone: chip.tone, dot: chip.dot })
        })
      }
      if (listData) {
        const chips = []
        if (activeSession && activeSession.framework) chips.push({ key: 'framework', label: '框架', value: activeSession.framework, tone: 'book' })
        if (activeSession && activeSession.platform) chips.push({ key: 'platform', label: '平台', value: activeSession.platform, tone: 'index' })
        if (activeSession && activeSession.category) chips.push({ key: 'category', label: '类别', value: activeSession.category, tone: 'check' })
        return chips.map(function (chip) { return SC.h(Chip, { key: chip.key, label: chip.label, value: chip.value, tone: chip.tone }) })
      }
      return null
    }

    function renderHeader() {
      const summary = (stats && stats.summary) || (activeSession && activeSession.summary) || ''
      const expandable = summary.length > 110
      return SC.h(
        'header',
        { className: 'sc-header' },
        SC.h(
          'div',
          { className: 'sc-brand' },
          SC.h(Mark, { size: 26 }),
          SC.h(
            'div',
            { className: 'sc-titles' },
            SC.h('div', { className: 'sc-title' }, '诊断画布'),
            SC.h('div', { className: 'sc-sub' }, 'Sleuth Canvas · 离线渲染'),
          ),
        ),
        SC.h(
          'div',
          { className: 'sc-head-right' },
          SC.h('div', { className: 'sc-chips' }, renderChips()),
          SC.h(
            'div',
            { className: 'sc-head-actions' },
            SC.h(
              'button',
              {
                type: 'button',
                className: 'sc-btn sc-btn-icon',
                onClick: openConversation,
                disabled: !(stats && stats.harnessSession),
                title: stats && stats.harnessSession ? '回到产生这条 trace 的 DSH 会话' : '这条 trace 没有 harness_session，挂不到会话上',
                'aria-label': '打开会话',
              },
              SC.h(Icon, { name: 'open', size: 15 }),
              SC.h('span', { className: 'sc-btn-text' }, '打开会话'),
            ),
            SC.h(
              'div',
              { className: 'sc-export', ref: exportRef },
              SC.h(
                'button',
                {
                  type: 'button',
                  className: 'sc-btn sc-btn-icon' + (exportOpen ? ' is-on' : ''),
                  onClick: function () { setExportOpen(function (value) { return !value }) },
                  title: '导出画布或摘要',
                  'aria-haspopup': 'menu',
                  'aria-expanded': exportOpen ? 'true' : 'false',
                },
                SC.h(Icon, { name: 'download', size: 15 }),
                SC.h('span', { className: 'sc-btn-text' }, '导出'),
              ),
              exportOpen
                ? SC.h(
                  'div',
                  { className: 'sc-export-menu', role: 'menu' },
                  SC.h('button', { type: 'button', role: 'menuitem', className: 'sc-export-item', onClick: exportPng, disabled: !detail }, SC.h(Icon, { name: 'download', size: 14 }), '导出 PNG（当前视图）'),
                  SC.h('button', { type: 'button', role: 'menuitem', className: 'sc-export-item', onClick: copySummary, disabled: !detail }, SC.h(Icon, { name: 'copy', size: 14 }), '复制旅程摘要'),
                )
                : null,
            ),
            SC.h(
              'button',
              {
                type: 'button',
                className: 'sc-btn sc-refresh' + (refreshing ? ' is-busy' : ''),
                onClick: refresh,
                disabled: refreshing,
                title: '重新读取 traces/',
              },
              SC.h(Icon, { name: 'refresh', size: 15, className: refreshing ? 'sc-spin' : '' }),
              SC.h('span', { className: 'sc-btn-text' }, '刷新'),
            ),
          ),
        ),
        summary
          ? SC.h(
            'div',
            { className: 'sc-summary' },
            SC.h('span', { className: 'sc-summary-bar' }),
            SC.h(
              'p',
              {
                className: 'sc-summary-text' + (summaryOpen ? ' is-open' : ''),
                title: summaryOpen ? '收起摘要' : '展开摘要',
                onClick: expandable ? function () { setSummaryOpen(function (value) { return !value }) } : undefined,
              },
              summary,
            ),
            expandable
              ? SC.h(
                'button',
                { type: 'button', className: 'sc-summary-toggle', onClick: function () { setSummaryOpen(function (value) { return !value }) } },
                summaryOpen ? '收起' : '展开',
              )
              : null,
          )
          : null,
        renderConclusion(),
      )
    }

    function renderConclusion() {
      if (!conclusion) return null
      const clickable = conclusion.idx !== null && conclusion.idx !== undefined
      const tone = 'var(--sc-' + conclusion.tone + ')'
      return SC.h(
        'div',
        {
          className: 'sc-conclusion' + (clickable ? ' is-clickable' : '') + (conclusion.empty ? ' is-empty' : ''),
          style: { '--tone': tone },
          role: clickable ? 'button' : undefined,
          tabIndex: clickable ? 0 : undefined,
          onClick: clickable ? selectConclusion : undefined,
          onKeyDown: clickable
            ? function (event) {
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectConclusion() }
            }
            : undefined,
          'aria-label': clickable ? '结论：' + conclusion.title + '，点击定位到结论节点' : '结论：' + conclusion.title,
        },
        SC.h('span', { className: 'sc-conclusion-bar' }),
        SC.h('span', { className: 'sc-conclusion-label' }, conclusion.label),
        SC.h(
          'div',
          { className: 'sc-conclusion-main' },
          SC.h('div', { className: 'sc-conclusion-title', title: conclusion.title }, conclusion.title),
          conclusion.text ? SC.h('div', { className: 'sc-conclusion-text', title: conclusion.text }, conclusion.text) : null,
        ),
        conclusion.badges.length
          ? SC.h(
            'div',
            { className: 'sc-conclusion-badges' },
            conclusion.badges.map(function (item, i) {
              return SC.h('span', { className: 'sc-badge sc-badge-' + (item.tone || 'neutral'), key: i }, item.text)
            }),
          )
          : null,
        clickable ? SC.h('span', { className: 'sc-conclusion-go' }, '定位 →') : null,
      )
    }

    function renderSessionCard(session) {
      const tone = U.statusTone(session && session.status)
      const active = session.file === activeFile
      const meta = SC.model.sessionMeta(session)
      return SC.h(
        'button',
        {
          type: 'button',
          key: session.file || session.id,
          className: 'sc-session' + (active ? ' is-active' : ''),
          onClick: function () { openSession(session) },
          title: session.id,
          'aria-pressed': active ? 'true' : 'false',
        },
        SC.h(
          'span',
          { className: 'sc-session-top' },
          SC.h('span', { className: 'sc-status-dot', style: { '--dot': 'var(--sc-' + tone.tone + ')' } }),
          SC.h('span', { className: 'sc-session-id' }, session.id || session.file || '（未命名）'),
          SC.h('span', { className: 'sc-session-time' }, U.formatRelative(session.updatedAt) || '—'),
          SC.h('span', { className: 'sc-session-open' }, '打开 →'),
        ),
        SC.h('span', { className: 'sc-session-summary', title: session.summary || '' }, session.summary || '没有摘要'),
        SC.h(
          'span',
          { className: 'sc-session-meta' },
          meta.map(function (part, i) { return SC.h('span', { className: 'sc-mini-chip', key: i }, part) }),
          session.file === activeFile && session.currentStep !== null && session.currentStep !== undefined
            ? SC.h('span', { className: 'sc-mini-chip is-accent' }, '第 ' + session.currentStep + ' 步')
            : null,
        ),
      )
    }

    function renderRail() {
      return SC.h(
        'div',
        { className: 'sc-list-rail' },
        SC.h(
          'button',
          { type: 'button', className: 'sc-rail-btn', onClick: function () { setListOpen(true) }, title: '展开诊断记录', 'aria-label': '展开诊断记录' },
          SC.h(Icon, { name: 'list', size: 16 }),
        ),
        filtered.map(function (session) {
          const tone = U.statusTone(session && session.status)
          return SC.h(
            'button',
            {
              type: 'button',
              key: 'rail-' + (session.file || session.id),
              className: 'sc-rail-dot' + (session.file === activeFile ? ' is-active' : ''),
              onClick: function () { openSession(session) },
              title: (session.id || '') + ' · ' + tone.label,
              'aria-label': (session.id || '') + ' · ' + tone.label,
            },
            SC.h('span', { className: 'sc-status-dot', style: { '--dot': 'var(--sc-' + tone.tone + ')' } }),
          )
        }),
      )
    }

    function renderList() {
      const warnings = listData && Array.isArray(listData.warnings) ? listData.warnings : []
      const repo = listData && listData.repo
      return SC.h(
        'aside',
        { className: 'sc-list' },
        renderRail(),
        SC.h(
          'div',
          { className: 'sc-list-main' },
          SC.h(
          'div',
          { className: 'sc-list-head' },
          SC.h(
            'button',
            {
              type: 'button',
              className: 'sc-list-toggle',
              onClick: function () { setListOpen(function (value) { return !value }) },
              title: listOpen ? '收起列表' : '展开列表',
              'aria-label': listOpen ? '收起列表' : '展开列表',
            },
            SC.h(Icon, { name: listOpen ? 'close' : 'list', size: 15 }),
          ),
          SC.h(
            'div',
            { className: 'sc-list-title' },
            '诊断记录 · ',
            SC.h('span', { className: 'sc-list-count' }, String(sessions.length)),
          ),
          SC.h(
            'div',
            { className: 'sc-sort', role: 'group', 'aria-label': '排序' },
            SC.h(
              'button',
              {
                type: 'button',
                className: 'sc-sort-btn' + (sortKey === 'updated' ? ' is-on' : ''),
                onClick: function () { setSortKey('updated') },
                title: '按更新时间倒序',
              },
              '更新时间',
            ),
            SC.h(
              'button',
              {
                type: 'button',
                className: 'sc-sort-btn' + (sortKey === 'steps' ? ' is-on' : ''),
                onClick: function () { setSortKey('steps') },
                title: '按步骤数倒序',
              },
              '步骤数',
            ),
          ),
        ),
        SC.h(
          'div',
          { className: 'sc-search' },
          SC.h(Icon, { name: 'search', size: 14 }),
          SC.h('input', {
            type: 'search',
            className: 'sc-search-input',
            value: query,
            placeholder: '搜索会话 / 框架 / 结论',
            'aria-label': '搜索会话',
            onChange: function (event) { setQuery(event.target.value) },
            onKeyDown: function (event) {
              if (event.key === 'Escape') {
                setQuery('')
                event.currentTarget.blur()
              }
            },
          }),
          query
            ? SC.h(
              'button',
              { type: 'button', className: 'sc-search-clear', onClick: function () { setQuery('') }, title: '清空搜索' },
              SC.h(Icon, { name: 'close', size: 12 }),
            )
            : null,
        ),
        listError
          ? SC.h(
            'div',
            { className: 'sc-warns' },
            SC.h('div', { className: 'sc-warn-row' }, SC.h(Icon, { name: 'warning', size: 13 }), SC.h('span', null, '列表读取失败：' + errorText(listError))),
          )
          : null,
        warnings.length
          ? SC.h(
            'div',
            { className: 'sc-warns' },
            warnings.slice(0, 3).map(function (warning, i) {
              return SC.h('div', { className: 'sc-warn-row', key: i }, SC.h(Icon, { name: 'warning', size: 13 }), SC.h('span', null, warning))
            }),
          )
          : null,
        SC.h(
          'div',
          { className: 'sc-list-body' },
          filtered.length
            ? filtered.map(renderSessionCard)
            : SC.h(
              'div',
              { className: 'sc-list-empty' },
              query ? '没有匹配的会话。' : '还没有诊断记录。',
              query ? SC.h('button', { type: 'button', className: 'sc-link-btn', onClick: function () { setQuery('') } }, '清空搜索') : null,
            ),
        ),
        SC.h(
          'div',
          { className: 'sc-list-foot' },
          repo && repo.detected
            ? SC.h('span', { className: 'sc-repo', title: repo.path }, 'traces/ · 只读')
            : SC.h('span', { className: 'sc-repo is-warn' }, '未找到 ascend-sleuth 仓库'),
          listData && listData.generatedAt
            ? SC.h('span', { className: 'sc-gen' }, '读取于 ' + U.formatRelative(listData.generatedAt))
            : null,
          ),
        ),
      )
    }

    function nowStepLabel() {
      if (replay.active) return '↺'
      if (selectedNode && selectedNode.step !== undefined) return 'S' + selectedNode.step
      if (stats && stats.stepCount) return 'S' + (stats.currentStep || stats.stepCount)
      return 'S·'
    }

    function nowText() {
      if (replay.active) return '回放 ' + (replay.index + 1) + ' / ' + events.length
      if (selectedNode) return '当前被选中：' + (selectedNode.label ? selectedNode.label + ' · ' : '') + selectedNode.title
      if (detailPhase === 'loading') return '读取 trace…'
      if (detailPhase === 'error') return '读取失败'
      if (phase === 'empty') return '还没有诊断记录'
      return '点任一节点看细节，滚轮缩放，双击适配'
    }

    function renderReplay() {
      if (!events.length) return null
      const total = events.length
      if (!replay.active) {
        return SC.h(
          'div',
          { className: 'sc-replay is-idle' },
          SC.h(
            'button',
            { type: 'button', className: 'sc-replay-start', onClick: toggleReplay, title: '按事件顺序回放（空格）' },
            SC.h(Icon, { name: 'play', size: 13 }),
            SC.h('span', null, '回放'),
            SC.h('span', { className: 'sc-replay-total' }, total + ' 个事件'),
          ),
        )
      }
      const progress = total <= 1 ? 100 : (replay.index / (total - 1)) * 100
      const ticks = graph ? graph.columns.map(function (column) {
        return {
          step: column.step,
          label: column.label,
          first: column.firstIdx,
          left: total <= 1 ? 0 : (column.firstIdx / (total - 1)) * 100,
        }
      }) : []
      return SC.h(
        'div',
        { className: 'sc-replay is-active' },
        SC.h(
          'button',
          {
            type: 'button',
            className: 'sc-replay-play',
            onClick: function () { setReplay(function (prev) { return Object.assign({}, prev, { playing: !prev.playing }) }) },
            title: replay.playing ? '暂停（空格）' : '播放（空格）',
            'aria-label': replay.playing ? '暂停回放' : '播放回放',
          },
          SC.h(Icon, { name: replay.playing ? 'pause' : 'play', size: 16 }),
        ),
        SC.h(
          'div',
          {
            className: 'sc-replay-track',
            role: 'slider',
            tabIndex: 0,
            'aria-label': '回放进度',
            'aria-valuemin': 1,
            'aria-valuemax': total,
            'aria-valuenow': replay.index + 1,
            onClick: function (event) {
              const rect = event.currentTarget.getBoundingClientRect()
              const ratio = rect.width ? clamp((event.clientX - rect.left) / rect.width, 0, 1) : 0
              jumpReplay(Math.round(ratio * (total - 1)))
            },
            onKeyDown: function (event) {
              if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault()
                event.stopPropagation()
                jumpReplay(replay.index + (event.key === 'ArrowRight' ? 1 : -1))
              }
            },
          },
          SC.h('div', { className: 'sc-replay-fill', style: { width: progress + '%' } }),
          ticks.map(function (tick) {
            return SC.h(
              'button',
              {
                type: 'button',
                key: 'tick-' + tick.step,
                className: 'sc-replay-tick' + (tick.first <= replay.index ? ' is-past' : ''),
                style: { left: tick.left + '%' },
                title: '第 ' + tick.step + ' 步 · ' + tick.label,
                onClick: function (event) { event.stopPropagation(); jumpReplay(tick.first) },
              },
              SC.h('span', { className: 'sc-replay-tick-label' }, 'S' + tick.step),
            )
          }),
        ),
        SC.h('div', { className: 'sc-replay-count' }, (replay.index + 1) + ' / ' + total),
        SC.h(
          'div',
          { className: 'sc-replay-speed', role: 'group', 'aria-label': '回放速度' },
          [0.5, 1, 2].map(function (speed) {
            return SC.h(
              'button',
              {
                type: 'button',
                key: speed,
                className: 'sc-replay-speed-btn' + (replay.speed === speed ? ' is-on' : ''),
                onClick: function () { setReplay(function (prev) { return Object.assign({}, prev, { speed: speed }) }) },
                title: speed + ' 倍速',
              },
              speed + '×',
            )
          }),
        ),
        SC.h(
          'button',
          { type: 'button', className: 'sc-replay-close', onClick: stopReplay, title: '退出回放（Esc）', 'aria-label': '退出回放' },
          SC.h(Icon, { name: 'close', size: 13 }),
        ),
      )
    }

    // 图例：与回放条、快捷键提示同处底部停靠区，由 .sc-canvas-dock 排布。
    function renderLegend() {
      if (!overview || !overview.legend.length) return null
      return SC.h(
        'div',
        { className: 'sc-legend' + (legendOpen ? ' is-open' : '') },
        SC.h(
          'button',
          { type: 'button', className: 'sc-legend-toggle', onClick: function () { setLegendOpen(function (value) { return !value }) }, title: legendOpen ? '收起图例' : '展开图例' },
          SC.h(Icon, { name: 'list', size: 12 }),
          SC.h('span', null, '图例'),
          SC.h(Icon, { name: legendOpen ? 'chevron-up' : 'chevron', size: 11 }),
        ),
        legendOpen
          ? SC.h(
            'div',
            { className: 'sc-legend-items' },
            overview.legend.map(function (item) {
              return SC.h(
                'span',
                { className: 'sc-legend-item', key: item.tone },
                SC.h('span', { className: 'sc-dot', style: { '--dot': 'var(--sc-' + item.tone + ')' } }),
                SC.h('span', null, item.label),
                SC.h('span', { className: 'sc-legend-count' }, String(item.count)),
              )
            }),
          )
          : null,
      )
    }

    function renderCanvasEmpty() {
      const repo = listData && listData.repo
      const warnings = (listData && listData.warnings) || []
      const noSessions = phase === 'empty'
      const noEvents = !noSessions && detail && (!detail.events || !detail.events.length)
      return SC.h(
        'div',
        { className: 'sc-stage-overlay' },
        SC.h(
          EmptyCard,
          {
            icon: SC.h(Mark, { size: 36 }),
            title: noSessions ? '还没有诊断记录' : noEvents ? '这次诊断没有事件记录' : '正在读取 trace…',
            text: noSessions
              ? (warnings.length ? warnings[0] : 'traces/ 目录里没有 YAML。先跑一次诊断，再回来看这张画布。')
              : noEvents
                ? 'trace 文件里没有可渲染的事件。刷新一下，或换一单诊断。'
                : '稍等，正在解析 trace。',
          },
          noSessions
            ? SC.h(
              'div',
              { className: 'sc-command' },
              SC.h('code', null, '/skill:diagnose'),
              SC.h(
                'button',
                { type: 'button', className: 'sc-btn sc-btn-ghost', onClick: function () { copy('/skill:diagnose', 'command') } },
                SC.h(Icon, { name: 'copy', size: 13 }),
                copied === 'command' ? '已复制' : '复制',
              ),
            )
            : null,
          noSessions && repo && repo.detected ? SC.h('div', { className: 'sc-state-path' }, SC.h('code', null, repo.path)) : null,
          SC.h(
            'div',
            { className: 'sc-empty-actions' },
            SC.h('button', { type: 'button', className: 'sc-btn sc-btn-primary', onClick: refresh }, '重新读取'),
          ),
        ),
      )
    }

    function renderCanvasError() {
      return SC.h(
        'div',
        { className: 'sc-stage-overlay' },
        SC.h(
          EmptyCard,
          { icon: SC.h(Icon, { name: 'warning', size: 26 }), title: '读取失败', text: errorText(detailError), tone: 'error' },
          SC.h(
            'div',
            { className: 'sc-empty-actions' },
            SC.h('button', { type: 'button', className: 'sc-btn sc-btn-primary', onClick: refresh }, '重试'),
            SC.h(
              'button',
              { type: 'button', className: 'sc-btn sc-btn-ghost', onClick: function () { copy(errorText(detailError), 'error') } },
              SC.h(Icon, { name: 'copy', size: 13 }),
              copied === 'error' ? '已复制' : '复制错误原文',
            ),
          ),
        ),
      )
    }

    function renderStageLoading() {
      return SC.h(
        'div',
        { className: 'sc-stage-loading' },
        SC.h('div', { className: 'sc-skel sc-skel-float' }),
        SC.h('div', { className: 'sc-stage-loading-text' }, '读取 trace…'),
      )
    }

    function renderTable() {
      const stepCount = graph && graph.columns ? graph.columns.length : 0
      return SC.h(
        'div',
        { className: 'sc-table-wrap' },
        SC.h(
          'div',
          { className: 'sc-table-head' },
          SC.h('div', { className: 'sc-table-title' }, '事件列表'),
          SC.h('div', { className: 'sc-table-meta' }, tableRows.length + ' 个事件 · ' + stepCount + ' 步 · 点一行定位到画布节点'),
          SC.h('button', { type: 'button', className: 'sc-btn sc-btn-ghost', onClick: toggleView }, SC.h(Icon, { name: 'canvas', size: 14 }), '回到画布'),
        ),
        SC.h(
          'div',
          { className: 'sc-table-scroll' },
          SC.h(
            'div',
            { className: 'sc-table', role: 'table', 'aria-label': '诊断事件列表', 'aria-rowcount': String(tableRows.length) },
            SC.h(
              'div',
              { className: 'sc-tr sc-thead', role: 'row' },
              ['步骤', '角色', '动作', '摘要', '标记'].map(function (label, i) {
                return SC.h('span', { key: i, role: 'columnheader', className: 'sc-th' }, label)
              }),
            ),
            tableRows.map(function (row) {
              const active = selected === row.idx
              return SC.h(
                'div',
                {
                  key: row.idx,
                  role: 'row',
                  tabIndex: 0,
                  'aria-selected': active ? 'true' : 'false',
                  className: 'sc-tr sc-trow' + (active ? ' is-active' : '') + (row.emphasis === 'conclusion' ? ' is-conclusion' : ''),
                  style: { '--tone': 'var(--sc-' + row.tone + ')' },
                  onClick: function () { locate(row.idx) },
                  onKeyDown: function (event) {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); locate(row.idx) }
                  },
                },
                SC.h('span', { role: 'cell', className: 'sc-td sc-td-step' }, 'S' + row.step),
                SC.h('span', { role: 'cell', className: 'sc-td sc-td-role' }, row.roleLabel),
                SC.h('span', { role: 'cell', className: 'sc-td sc-td-action' }, row.action),
                SC.h(
                  'div',
                  { role: 'cell', className: 'sc-td sc-td-main' },
                  SC.h('div', { className: 'sc-td-title', title: row.title }, row.title),
                  row.subtitle ? SC.h('div', { className: 'sc-td-sub', title: row.subtitle }, row.subtitle) : null,
                ),
                SC.h(
                  'div',
                  { role: 'cell', className: 'sc-td sc-td-marks' },
                  row.marks.map(function (mark, i) { return SC.h('span', { key: i, className: 'sc-mark' }, mark) }),
                ),
              )
            }),
          ),
        ),
      )
    }

    function renderHint() {
      if (!hintOpen) return null
      return SC.h(
        'div',
        { className: 'sc-hint', role: 'note' },
        SC.h('span', { className: 'sc-hint-text' }, '滚轮缩放 · 拖拽平移 · f 适配 · ←/→ 逐个事件 · t 列表视图'),
        SC.h('button', { type: 'button', className: 'sc-hint-close', onClick: dismissHint, title: '关闭提示', 'aria-label': '关闭快捷键提示' }, SC.h(Icon, { name: 'close', size: 12 })),
      )
    }

    function renderCanvas() {
      const showEmpty = phase === 'empty' || (detailPhase === 'ready' && detail && (!detail.events || !detail.events.length))
      return SC.h(
        'section',
        { className: 'sc-stage' },
        SC.h(
          'div',
          { className: 'sc-canvas-wrap' + (view === 'table' ? ' is-hidden' : ''), ref: wrapRef },
          SC.h('canvas', { className: 'sc-canvas', ref: canvasRef, 'aria-label': '诊断旅程画布' }),
          SC.h(
            'div',
            { className: 'sc-canvas-top' },
            SC.h(
              'div',
              { className: 'sc-canvas-top-row' },
              SC.h(
                'div',
                { className: 'sc-top-id', title: activeFile || '' },
                SC.h('span', {
                  className: 'sc-top-dot',
                  style: { '--dot': 'var(--sc-' + ((stats && stats.status && stats.status.tone) || 'hit') + ')' },
                }),
                SC.h(
                  'span',
                  { className: 'sc-top-name' },
                  (detail && detail.session && detail.session.id) || activeFile || (phase === 'empty' ? '没有 traces' : '—'),
                ),
              ),
              detail
                ? SC.h(
                  'div',
                  { className: 'sc-top-actions' },
                  SC.h(
                    'button',
                    { type: 'button', className: 'sc-top-btn', onClick: toggleView, title: view === 'table' ? '回到画布视图（t）' : '切到事件列表视图（t）' },
                    SC.h(Icon, { name: view === 'table' ? 'canvas' : 'table', size: 14 }),
                    view === 'table' ? '画布' : '列表',
                  ),
                  SC.h(
                    'button',
                    { type: 'button', className: 'sc-top-btn sc-insp-toggle', onClick: function () { setInspectorOpen(function (value) { return !value }) }, title: '洞察检查器' },
                    SC.h(Icon, { name: 'insight', size: 14 }),
                    '洞察',
                  ),
                )
                : null,
            ),
            detail
              ? SC.h(
                'div',
                { className: 'sc-canvas-summary' },
                SC.h('p', { className: 'sc-canvas-summary-text' }, ((stats && stats.summary) || '').slice(0, 240) || '这次诊断没有摘要'),
              )
              : null,
            SC.h(
              'div',
              { className: 'sc-now' },
              SC.h('span', { className: 'sc-now-step' }, nowStepLabel()),
              SC.h('span', { className: 'sc-now-text' }, nowText()),
            ),
          ),
          view === 'canvas' && hoveredNode && tooltip
            ? SC.h(
              'div',
              {
                className: 'sc-tooltip' + (tooltip.below ? ' is-below' : ''),
                style: { left: tooltip.x + 'px', top: tooltip.y + 'px' },
              },
              SC.h('div', { className: 'sc-tooltip-title' }, hoveredNode.title),
              hoveredNode.subtitle
                ? SC.h('div', { className: 'sc-tooltip-sub' }, hoveredNode.subtitle)
                : SC.h('div', { className: 'sc-tooltip-sub' }, hoveredNode.meta),
              SC.h('div', { className: 'sc-tooltip-meta' }, hoveredNode.meta),
            )
            : null,
          view === 'canvas' && detail
            ? SC.h(
              'div',
              { className: 'sc-zoom' },
              SC.h('button', { type: 'button', className: 'sc-zoom-btn', onClick: function () { zoom(1.2) }, title: '放大（+）', 'aria-label': '放大' }, SC.h(Icon, { name: 'plus', size: 15 })),
              SC.h('button', { type: 'button', className: 'sc-zoom-btn', onClick: function () { zoom(1 / 1.2) }, title: '缩小（-）', 'aria-label': '缩小' }, SC.h(Icon, { name: 'minus', size: 15 })),
              SC.h('button', { type: 'button', className: 'sc-zoom-btn', onClick: fit, title: '适配（f）', 'aria-label': '适配视图' }, SC.h(Icon, { name: 'fit', size: 15 })),
            )
            : null,
          // 底部停靠区：快捷键提示与图例是一列（提示在上、图例贴底），回放条占右侧剩余宽度。
          // 三者由同一个 grid 排布，不再是各自绝对定位在同一个左下角。
          view === 'canvas'
            ? SC.h(
              'div',
              { className: 'sc-canvas-dock' },
              SC.h(
                'div',
                { className: 'sc-dock-side' },
                detail && !showEmpty && !replay.active ? renderHint() : null,
                renderLegend(),
              ),
              SC.h('div', { className: 'sc-dock-main' }, renderReplay()),
            )
            : null,
          view === 'table' && detail && !showEmpty ? renderTable() : null,
          showEmpty ? renderCanvasEmpty() : null,
          detailPhase === 'error' ? renderCanvasError() : null,
          detailPhase === 'loading' ? renderStageLoading() : null,
        ),
      )
    }

    function toggleSection(section) {
      const open = sectionOpen(section, expanded)
      setExpanded(function (prev) {
        const next = Object.assign({}, prev)
        next[section.key] = !open
        return next
      })
    }

    function renderSectionBody(section) {
      if (section.kind === 'prose') {
        return SC.h('div', { className: 'sc-sec-body' }, (section.paragraphs || []).map(function (paragraph, i) {
          return SC.h('p', { className: 'sc-p', key: i }, paragraph)
        }))
      }
      if (section.kind === 'kv') {
        return SC.h('div', { className: 'sc-sec-body sc-kv' }, (section.entries || []).map(function (entry) {
          return SC.h(
            'div',
            { className: 'sc-kv-row', key: entry.key },
            SC.h('span', { className: 'sc-kv-key' }, entry.label || entry.key),
            SC.h('span', { className: 'sc-kv-val' + (entry.tone === 'warn' ? ' is-warn' : ''), title: entry.value }, entry.value),
          )
        }))
      }
      if (section.kind === 'evidence') {
        const inline = section.inline
        return SC.h(
          'div',
          { className: 'sc-sec-body' },
          inline
            ? SC.h(
              'div',
              { className: 'sc-evidence' },
              SC.h('div', { className: 'sc-evidence-label' }, '内联证据', SC.h('span', { className: 'sc-evidence-count' }, U.formatNumber(inline.chars) + ' 字')),
              SC.h('p', { className: 'sc-p sc-evidence-inline' }, inlineOpen ? inline.text : U.truncate(inline.text, 260)),
              SC.h(
                'button',
                { type: 'button', className: 'sc-inline-fold', onClick: function () { setInlineOpen(function (value) { return !value }) } },
                inlineOpen ? '收起' : '展开 ' + U.formatNumber(inline.chars) + ' 字',
              ),
            )
            : null,
          (section.files || []).length
            ? SC.h(
              'div',
              { className: 'sc-files' },
              (section.files || []).map(function (file) {
                return SC.h(
                  'div',
                  { className: 'sc-filerow', key: file },
                  SC.h('code', { className: 'sc-file', title: file }, file),
                  SC.h(
                    'button',
                    { type: 'button', className: 'sc-copy-btn', onClick: function () { copy(file, 'file:' + file) }, title: '复制路径' },
                    copied === 'file:' + file ? '已复制' : '复制',
                  ),
                )
              }),
            )
            : null,
          (section.sources || []).length
            ? SC.h(
              'div',
              { className: 'sc-files' },
              (section.sources || []).map(function (source) {
                return SC.h(
                  'div',
                  { className: 'sc-filerow', key: source },
                  SC.h('code', { className: 'sc-file', title: source }, source),
                  SC.h(
                    'button',
                    { type: 'button', className: 'sc-copy-btn', onClick: function () { copy(source, 'src:' + source) }, title: '复制链接' },
                    copied === 'src:' + source ? '已复制' : '复制',
                  ),
                )
              }),
            )
            : null,
          section.missing
            ? SC.h('div', { className: 'sc-missing' }, SC.h(Icon, { name: 'warning', size: 13 }), SC.h('span', null, '缺少证据：' + section.missing))
            : null,
        )
      }
      if (section.kind === 'chips') {
        return SC.h(
          'div',
          { className: 'sc-sec-body sc-chipgroups' },
          (section.groups || []).map(function (group) {
            return SC.h(
              'div',
              { className: 'sc-chipgroup', key: group.label },
              SC.h('div', { className: 'sc-chipgroup-label' }, group.label),
              SC.h(
                'div',
                { className: 'sc-chipgroup-values' },
                (group.values || []).map(function (value, i) {
                  return SC.h(
                    'button',
                    {
                      type: 'button',
                      key: i,
                      className: 'sc-value-chip',
                      style: { '--tone': 'var(--sc-' + (group.tone || 'feedback') + ')' },
                      title: value + '（点击复制）',
                      onClick: function () { copy(value, 'chip:' + value) },
                    },
                    SC.h('span', { className: 'sc-value-chip-text' }, U.truncate(value, 120)),
                    copied === 'chip:' + value ? SC.h('span', { className: 'sc-value-chip-copied' }, '已复制') : null,
                  )
                }),
              ),
            )
          }),
        )
      }
      if (section.kind === 'tools') {
        return SC.h(
          'div',
          { className: 'sc-sec-body sc-tools' },
          (section.items || []).map(function (item, i) {
            return SC.h(
              'div',
              { className: 'sc-tool', key: i },
              SC.h('span', { className: 'sc-tool-n' }, String(i + 1)),
              SC.h('code', { className: 'sc-tool-text' }, item),
              SC.h(
                'button',
                { type: 'button', className: 'sc-copy-btn', onClick: function () { copy(item, 'tool:' + i) }, title: '复制' },
                copied === 'tool:' + i ? '已复制' : '复制',
              ),
            )
          }),
        )
      }
      if (section.kind === 'fields') {
        return SC.h(
          'div',
          { className: 'sc-sec-body sc-kv' },
          (section.entries || []).map(function (entry) {
            return SC.h(
              'div',
              { className: 'sc-kv-row', key: entry.key },
              SC.h('span', { className: 'sc-kv-key' }, entry.label || entry.key),
              SC.h('span', { className: 'sc-kv-val', title: entry.value }, entry.value),
            )
          }),
        )
      }
      return null
    }

    function renderSection(section) {
      const open = sectionOpen(section, expanded)
      return SC.h(
        'section',
        { className: 'sc-sec' + (open ? ' is-open' : ''), key: section.key },
        SC.h(
          'button',
          { type: 'button', className: 'sc-sec-toggle', onClick: function () { toggleSection(section) }, 'aria-expanded': open ? 'true' : 'false' },
          SC.h('span', { className: 'sc-sec-title' }, section.title),
          section.kind === 'fields' && section.entries ? SC.h('span', { className: 'sc-sec-count' }, String(section.entries.length)) : null,
          SC.h(Icon, { name: open ? 'chevron-up' : 'chevron', size: 12, className: 'sc-sec-chev' }),
        ),
        open ? renderSectionBody(section) : null,
      )
    }

    function renderNodeInspector(data) {
      const iconName = GLYPH_ICONS[data.glyph] || 'dot'
      return SC.h(
        'div',
        { className: 'sc-insp-body', ref: inspBodyRef, key: 'node-' + data.idx },
        SC.h(
          'div',
          { className: 'sc-insp-header' },
          SC.h(
            'span',
            { className: 'sc-avatar', style: { '--tone': 'var(--sc-' + data.tone + ')' } },
            SC.h('span', { className: 'sc-avatar-inner' }, SC.h(Icon, { name: iconName, size: 18 })),
          ),
          SC.h(
            'div',
            { className: 'sc-insp-headtext' },
            SC.h('div', { className: 'sc-insp-kicker' }, (data.label || '节点') + (data.emphasis === 'conclusion' ? ' · 结论' : '')),
            SC.h('div', { className: 'sc-insp-title' }, data.title),
            SC.h(
              'div',
              { className: 'sc-insp-meta' },
              'step ' + data.step + ' · ' + data.roleLabel,
              data.parallel ? ' · 并行 ' + data.parallel.count + ' 个动作' : '',
              replay.active ? ' · 回放中' : '',
            ),
          ),
        ),
        (data.sections || []).map(renderSection),
        SC.h(
          'div',
          { className: 'sc-insp-foot' },
          SC.h(
            'button',
            { type: 'button', className: 'sc-btn sc-btn-ghost', disabled: data.prev === null, onClick: function () { selectIndex(data.prev) } },
            SC.h(Icon, { name: 'arrow-left', size: 13 }),
            '上一节点',
          ),
          SC.h(
            'button',
            { type: 'button', className: 'sc-btn sc-btn-ghost', disabled: data.next === null, onClick: function () { selectIndex(data.next) } },
            '下一节点',
            SC.h(Icon, { name: 'arrow-right', size: 13 }),
          ),
          SC.h(
            'button',
            { type: 'button', className: 'sc-btn sc-btn-ghost sc-locate', onClick: function () { locate(data.idx) } },
            SC.h(Icon, { name: 'fit', size: 13 }),
            '定位到画布',
          ),
        ),
      )
    }

    function renderOverview() {
      const insights = overview ? overview.insights : []
      return SC.h(
        'div',
        { className: 'sc-insp-body sc-overview', ref: inspBodyRef, key: 'overview' },
        SC.h('div', { className: 'sc-overview-lead' }, '按顺序读，或点任一节点看细节。'),
        insights.length
          ? SC.h(
            'div',
            { className: 'sc-insights' },
            insights.map(function (insight) {
              return SC.h(
                'div',
                { className: 'sc-insight', key: insight.id || insight.title },
                SC.h('span', { className: 'sc-insight-dot', style: { '--dot': 'var(--sc-' + (INSIGHT_TONES[insight.tone] || 'feedback') + ')' } }),
                SC.h(
                  'div',
                  { className: 'sc-insight-body' },
                  SC.h('div', { className: 'sc-insight-title' }, insight.title),
                  SC.h('div', { className: 'sc-insight-text' }, insight.text),
                ),
              )
            }),
          )
          : SC.h('div', { className: 'sc-insp-empty' }, phase === 'empty' ? '还没有诊断记录，先跑一次诊断。' : 'host 没有给出洞察。'),
        overview && overview.legend.length
          ? SC.h(
            'div',
            { className: 'sc-overview-legend' },
            SC.h('div', { className: 'sc-overview-sep' }),
            SC.h('div', { className: 'sc-kicker' }, '图例'),
            overview.legend.map(function (item) {
              return SC.h(
                'div',
                { className: 'sc-legend-row', key: item.tone },
                SC.h('span', { className: 'sc-dot', style: { '--dot': 'var(--sc-' + item.tone + ')' } }),
                SC.h('span', { className: 'sc-legend-row-label' }, item.label),
                SC.h('span', { className: 'sc-legend-row-count' }, String(item.count)),
              )
            }),
          )
          : null,
        overview && overview.warnings.length
          ? SC.h(
            'div',
            { className: 'sc-warns' },
            overview.warnings.map(function (warning, i) {
              return SC.h('div', { className: 'sc-warn-row', key: i }, SC.h(Icon, { name: 'warning', size: 13 }), SC.h('span', null, warning))
            }),
          )
          : null,
        SC.h('div', { className: 'sc-footnote' }, (overview ? overview.footnote : '数据来自 traces/ · 只读') + ' · v' + (SC.version || '?')),
      )
    }

    function renderInspector() {
      return SC.h(
        'aside',
        { className: 'sc-inspector' },
        SC.h(
          'div',
          { className: 'sc-insp-headbar' },
          SC.h('div', { className: 'sc-insp-kicker' }, inspector ? '节点详情' : '旅程读法'),
          SC.h(
            'button',
            {
              type: 'button',
              className: 'sc-insp-close',
              onClick: function () {
                setInspectorOpen(false)
                setSelected(null)
                stopReplay()
              },
              title: '关闭检查器',
              'aria-label': '关闭检查器',
            },
            SC.h(Icon, { name: 'close', size: 14 }),
          ),
        ),
        detailPhase === 'loading' && !detail
          ? SC.h(
            'div',
            { className: 'sc-insp-body' },
            SC.h('div', { className: 'sc-skel sc-skel-line is-wide' }),
            SC.h('div', { className: 'sc-skel sc-skel-line' }),
            SC.h('div', { className: 'sc-skel sc-skel-line is-short' }),
          )
          : detailPhase === 'error'
            ? SC.h(
              'div',
              { className: 'sc-insp-body' },
              SC.h('div', { className: 'sc-insp-empty' }, 'detail 读取失败：' + errorText(detailError)),
              SC.h('div', { className: 'sc-empty-actions' }, SC.h('button', { type: 'button', className: 'sc-btn sc-btn-primary', onClick: refresh }, '重试')),
            )
            : inspector
              ? renderNodeInspector(inspector)
              : renderOverview(),
      )
    }

    if (!listData && phase === 'loading') {
      return SC.h('div', { className: 'sc-root', ref: rootRef, 'data-phase': phase }, SC.h(Skeleton))
    }
    if (!listData && phase === 'error') {
      return SC.h(
        'div',
        { className: 'sc-root', ref: rootRef, 'data-phase': phase },
        renderHeader(),
        SC.h(ErrorState, {
          message: errorText(listError),
          hint: '确认 ascend-sleuth 仓库可读、traces/ 存在，然后重试。',
          copied: copied,
          onRetry: refresh,
          onCopy: copy,
        }),
      )
    }

    return SC.h(
      'div',
      {
        className: 'sc-root',
        ref: rootRef,
        tabIndex: -1,
        'data-phase': phase,
        'data-inspector': inspectorIdx !== null && inspectorIdx !== undefined || inspectorOpen ? 'open' : 'closed',
        'data-list': listOpen ? 'open' : 'closed',
        'data-replay': replay.active ? 'on' : 'off',
      },
      renderHeader(),
      SC.h('div', { className: 'sc-body' }, renderList(), renderCanvas(), renderInspector()),
      SC.h('div', { className: 'sc-notice' + (notice ? ' is-on' : ''), role: 'status', 'aria-live': 'polite' }, notice),
      SC.h('div', { className: 'sc-sr-only', 'aria-live': 'polite' }, copied ? '已复制' : ''),
    )
  }

  return CanvasPage
})()
})(SC)

// ─── client-src/40-css.js ───
;(function (SC) {
// 页面样式：三栏布局 + 玻璃悬浮件 + 状态/加载动效。颜色只用宿主 --dsw-alias-* 令牌
// 与自定义 --sc-* 语义色；动效只有三档时长；容器查询做窄屏降级。

SC.css = `
.sc-root{
  --sc-font:ui-sans-serif,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  --sc-mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sc-surface:var(--dsw-alias-bg-base,#ffffff);
  --sc-layer1:var(--dsw-alias-bg-layer-1,#f7f8fa);
  --sc-layer2:var(--dsw-alias-bg-layer-2,#eef0f4);
  --sc-overlay:var(--dsw-alias-bg-overlay,#ffffff);
  --sc-text:var(--dsw-alias-label-primary,#101318);
  --sc-text2:var(--dsw-alias-label-secondary,#5b6472);
  --sc-text3:color-mix(in srgb, var(--sc-text2) 64%, transparent);
  --sc-line:color-mix(in srgb, var(--sc-text) 9%, transparent);
  --sc-line-strong:color-mix(in srgb, var(--sc-text) 16%, transparent);
  --sc-accent:var(--dsw-alias-brand-primary,#4a7dff);
  --sc-accent-soft:color-mix(in srgb, var(--sc-accent) 12%, transparent);
  --sc-on-accent:#ffffff;
  --sc-intake:#D9902F;--sc-route:#4A7DFF;--sc-index:#2AA7B8;--sc-check:#8A6CF0;
  --sc-book:#3C9A78;--sc-code:#E07A3F;--sc-hit:#3FA46A;--sc-miss:#6E7C93;
  --sc-flag:#C9A227;--sc-feedback:#7C8698;--sc-warn:#D9822B;--sc-risk:#D65454;
  --sc-r-sm:6px;--sc-r-md:10px;--sc-r-lg:14px;--sc-r-pill:999px;
  --sc-space-1:4px;--sc-space-2:6px;--sc-space-3:8px;--sc-space-4:12px;--sc-space-5:16px;--sc-space-6:24px;
  --sc-fs-lg:20px;--sc-fs-md:13.5px;--sc-fs-base:13px;--sc-fs-sm:12.5px;
  --sc-fs-xs:11.5px;--sc-fs-2xs:10.5px;--sc-fs-3xs:10px;
  --sc-lh-body:1.65;
  --sc-m-fast:120ms;--sc-m-base:180ms;--sc-m-slow:320ms;
  --sc-ease:cubic-bezier(.22,.61,.36,1);
  --sc-shadow-float:0 18px 48px -28px color-mix(in srgb, var(--sc-text) 52%, transparent);
  height:100%;min-height:0;display:flex;flex-direction:column;overflow:hidden;
  container-type:inline-size;
  background:
    radial-gradient(90% 60% at 50% -10%, color-mix(in srgb, var(--sc-accent) 5%, transparent), transparent 68%),
    var(--sc-surface);
  color:var(--sc-text);
  font-family:var(--sc-font);font-size:var(--sc-fs-base);line-height:var(--sc-lh-body);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
.sc-root *,.sc-root *::before,.sc-root *::after{box-sizing:border-box}
.sc-root :focus-visible{outline:2px solid color-mix(in srgb, var(--sc-accent) 55%, transparent);outline-offset:2px}
.sc-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* ── 深色：色相不变，明度 +6%、饱和度 -6%（与主题模块同一规则）────────── */
body[data-ds-dark-theme] .sc-root,
[data-ds-dark-theme] .sc-root,
html[data-theme="dark"] .sc-root,
html[data-mode="dark"] .sc-root{
  --sc-intake:#E2A046;--sc-route:#6E9BFF;--sc-index:#45B9C9;--sc-check:#A48DF5;
  --sc-book:#4FB58E;--sc-code:#E99563;--sc-hit:#55BE82;--sc-miss:#8B94A3;
  --sc-flag:#D7B13F;--sc-feedback:#969DA8;--sc-warn:#E2954E;--sc-risk:#E27272;
  --sc-shadow-float:0 22px 60px -28px rgba(0,0,0,.62);
}

/* ── 页头 ─────────────────────────────────────────────────────────────── */
.sc-header{
  flex-shrink:0;display:grid;grid-template-columns:minmax(0,1fr) auto;
  grid-template-areas:"brand right" "summary summary" "conclusion conclusion";
  column-gap:16px;row-gap:6px;padding:11px 16px 9px;
  border-bottom:1px solid var(--sc-line);
  background:linear-gradient(180deg, color-mix(in srgb, var(--sc-layer1) 62%, var(--sc-surface)), var(--sc-surface));
}
.sc-brand{grid-area:brand;display:flex;align-items:center;gap:10px;min-width:0}
.sc-mark{flex-shrink:0;display:block}
.sc-titles{min-width:0}
.sc-title{font-size:var(--sc-fs-lg);font-weight:650;letter-spacing:.2px;line-height:1.2;color:var(--sc-text)}
.sc-sub{margin-top:2px;font-size:var(--sc-fs-xs);color:var(--sc-text2);letter-spacing:.2px;line-height:1.3}
.sc-head-right{grid-area:right;display:flex;align-items:center;gap:10px;min-width:0}
.sc-chips{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end;min-width:0}
.sc-chip{
  display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 9px;max-width:238px;
  border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);
  background:color-mix(in srgb, var(--sc-layer2) 68%, transparent);
  font-size:var(--sc-fs-xs);color:var(--sc-text2);white-space:nowrap;
}
.sc-chip-dot{width:6px;height:6px;border-radius:50%;background:var(--tone,var(--sc-feedback));flex-shrink:0;
  box-shadow:0 0 0 3px color-mix(in srgb, var(--tone,var(--sc-feedback)) 14%, transparent)}
.sc-chip-key{font-size:10.5px;letter-spacing:.3px;color:var(--sc-text3)}
.sc-chip-value{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sc-text)}
.sc-summary{grid-area:summary;display:flex;align-items:flex-start;gap:10px;min-width:0}
.sc-summary-bar{width:3px;border-radius:2px;align-self:stretch;min-height:16px;background:var(--sc-accent);opacity:.8;flex-shrink:0}
.sc-summary-text{
  margin:0;flex:1;min-width:0;font-size:12px;line-height:1.65;color:var(--sc-text2);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  cursor:pointer;overflow-wrap:anywhere;
}
.sc-summary-text.is-open{display:block;-webkit-line-clamp:unset;overflow:visible}
.sc-summary-toggle{
  appearance:none;border:0;background:transparent;padding:1px 0;flex-shrink:0;
  font:inherit;font-size:11px;color:var(--sc-accent);cursor:pointer;white-space:nowrap;
  transition:opacity var(--sc-m-fast) var(--sc-ease);
}
.sc-summary-toggle:hover{opacity:.78}

/* ── 按钮 ─────────────────────────────────────────────────────────────── */
.sc-btn{
  appearance:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;
  height:28px;padding:0 11px;border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer1) 72%, transparent);
  color:var(--sc-text2);font:inherit;font-size:12px;cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease),
    border-color var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-btn:hover{color:var(--sc-text);border-color:var(--sc-line-strong);background:color-mix(in srgb, var(--sc-layer2) 78%, transparent)}
.sc-btn:active{transform:translateY(.5px)}
.sc-btn:disabled{opacity:.45;cursor:default;transform:none}
.sc-btn-primary{background:var(--sc-accent);border-color:transparent;color:var(--sc-on-accent);font-weight:550}
.sc-btn-primary:hover{background:var(--sc-accent);border-color:transparent;color:var(--sc-on-accent);filter:brightness(1.06)}
.sc-btn-ghost{background:transparent}
.sc-refresh{height:28px;padding:0 10px}
.sc-refresh.is-busy .sc-spin{animation:sc-spin 900ms linear infinite}
.sc-spin{animation:sc-spin 900ms linear infinite;transform-origin:50% 50%}
.sc-btn-text{font-size:12px}
.sc-link-btn{
  appearance:none;border:0;background:transparent;padding:0;margin-left:6px;
  font:inherit;font-size:11.5px;color:var(--sc-accent);cursor:pointer;
}

/* ── 三栏骨架 ─────────────────────────────────────────────────────────── */
.sc-body{position:relative;flex:1;min-height:0;display:grid;grid-template-columns:264px minmax(0,1fr) 336px}

/* ── 左：会话列表 ─────────────────────────────────────────────────────── */
.sc-list{
  position:relative;display:flex;flex-direction:column;min-height:0;min-width:0;
  border-right:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 52%, var(--sc-surface));
}
.sc-list-rail{display:none}
.sc-list-main{display:flex;flex-direction:column;min-height:0;flex:1}
.sc-list-head{display:flex;align-items:center;gap:8px;padding:12px 14px 7px;flex-shrink:0}
.sc-list-toggle{display:none;appearance:none;border:1px solid var(--sc-line);border-radius:8px;background:transparent;
  color:var(--sc-text2);width:28px;height:28px;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0}
.sc-list-title{font-size:var(--sc-fs-md);font-weight:650;color:var(--sc-text);white-space:nowrap;letter-spacing:.1px}
.sc-list-count{font-family:var(--sc-mono);font-size:11px;font-weight:400;color:var(--sc-text2)}
.sc-sort{margin-left:auto;display:flex;gap:1px;padding:2px;border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer2) 60%, transparent)}
.sc-sort-btn{
  appearance:none;border:0;background:transparent;font:inherit;font-size:10.5px;color:var(--sc-text3);
  padding:3px 6px;border-radius:6px;cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-sort-btn:hover{color:var(--sc-text2)}
.sc-sort-btn.is-on{background:var(--sc-surface);color:var(--sc-text);box-shadow:0 1px 2px color-mix(in srgb, var(--sc-text) 10%, transparent)}
.sc-search{
  margin:3px 12px 8px;display:flex;align-items:center;gap:7px;height:32px;padding:0 9px;flex-shrink:0;
  border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-surface) 78%, transparent);color:var(--sc-text3);
  transition:border-color var(--sc-m-fast) var(--sc-ease),box-shadow var(--sc-m-fast) var(--sc-ease);
}
.sc-search:focus-within{
  border-color:color-mix(in srgb, var(--sc-accent) 45%, transparent);
  box-shadow:0 0 0 3px var(--sc-accent-soft);
}
.sc-search-input{
  flex:1;min-width:0;border:0;outline:none;background:transparent;
  font:inherit;font-size:12.5px;color:var(--sc-text);
}
.sc-search-input::placeholder{color:var(--sc-text3)}
.sc-search-input::-webkit-search-cancel-button{display:none}
.sc-search-clear{appearance:none;border:0;background:transparent;color:var(--sc-text3);cursor:pointer;
  width:18px;height:18px;display:flex;align-items:center;justify-content:center;border-radius:4px}
.sc-search-clear:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 8%, transparent)}
.sc-warns{padding:0 13px 8px;display:flex;flex-direction:column;gap:5px;flex-shrink:0}
.sc-warn-row{display:flex;gap:6px;align-items:flex-start;font-size:11px;line-height:1.5;color:var(--sc-warn);overflow-wrap:anywhere}
.sc-warn-row svg{flex-shrink:0;margin-top:2px}
.sc-list-body{flex:1;min-height:0;overflow:auto;padding:2px 10px 12px;display:flex;flex-direction:column;gap:8px;overscroll-behavior:contain}
.sc-list-body::-webkit-scrollbar,.sc-insp-body::-webkit-scrollbar,.sc-evidence-inline::-webkit-scrollbar{width:8px;height:8px}
.sc-list-body::-webkit-scrollbar-thumb,.sc-insp-body::-webkit-scrollbar-thumb,.sc-evidence-inline::-webkit-scrollbar-thumb{
  background:color-mix(in srgb, var(--sc-text) 16%, transparent);border-radius:999px;border:2px solid transparent;background-clip:padding-box}
.sc-list-body::-webkit-scrollbar-track,.sc-insp-body::-webkit-scrollbar-track{background:transparent}
.sc-list-empty{
  margin:12px 4px;padding:18px 12px;border:1px dashed var(--sc-line-strong);border-radius:var(--sc-r-md);
  text-align:center;font-size:12px;line-height:1.65;color:var(--sc-text2);
}
.sc-list-foot{
  flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:8px 14px;border-top:1px solid var(--sc-line);
  font-size:10.5px;color:var(--sc-text3);white-space:nowrap;
}
.sc-repo{overflow:hidden;text-overflow:ellipsis;font-family:var(--sc-mono);font-size:10px}
.sc-repo.is-warn{font-family:var(--sc-font);color:var(--sc-warn)}
.sc-gen{overflow:hidden;text-overflow:ellipsis}

/* 会话卡片 */
.sc-session{
  appearance:none;position:relative;display:block;width:100%;text-align:left;font:inherit;color:var(--sc-text);
  content-visibility:auto;contain-intrinsic-size:auto 96px;
  padding:10px 11px 9px 13px;border:1px solid var(--sc-line);border-radius:12px;background:var(--sc-surface);
  cursor:pointer;overflow:hidden;
  transition:background-color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-session::before{
  content:"";position:absolute;left:0;top:11px;bottom:11px;width:2px;border-radius:2px;
  background:transparent;transition:background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-session:hover{background:color-mix(in srgb, var(--sc-layer2) 62%, var(--sc-surface));border-color:var(--sc-line-strong)}
.sc-session:active{transform:scale(.997)}
.sc-session.is-active{background:color-mix(in srgb, var(--sc-layer2) 82%, var(--sc-surface));
  border-color:color-mix(in srgb, var(--sc-accent) 30%, transparent)}
.sc-session.is-active::before{background:var(--sc-accent)}
.sc-session-top{display:flex;align-items:center;gap:7px;min-width:0}
.sc-status-dot{width:7px;height:7px;border-radius:50%;background:var(--dot,var(--sc-feedback));flex-shrink:0;
  box-shadow:0 0 0 3px color-mix(in srgb, var(--dot,var(--sc-feedback)) 13%, transparent)}
.sc-session-id{
  flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-family:var(--sc-mono);font-size:10.5px;letter-spacing:-.1px;line-height:1.4;color:var(--sc-text);
}
.sc-session-time{font-size:10.5px;color:var(--sc-text2);white-space:nowrap;font-variant-numeric:tabular-nums;flex-shrink:0}
.sc-session-open{display:none;font-size:10.5px;color:var(--sc-accent);white-space:nowrap;flex-shrink:0}
.sc-session:hover .sc-session-time,.sc-session:focus-visible .sc-session-time{display:none}
.sc-session:hover .sc-session-open,.sc-session:focus-visible .sc-session-open{display:inline}
.sc-session-summary{
  margin-top:5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  font-size:var(--sc-fs-xs);line-height:1.58;color:var(--sc-text2);overflow-wrap:anywhere;
}
.sc-session-meta{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px;align-items:center;min-width:0}
.sc-mini-chip{
  max-width:156px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  padding:3px 6px;border:1px solid var(--sc-line);border-radius:5px;
  background:color-mix(in srgb, var(--sc-layer2) 52%, transparent);
  font-size:10.5px;line-height:1;color:var(--sc-text2);
}
.sc-mini-chip.is-accent{color:var(--sc-accent);border-color:color-mix(in srgb, var(--sc-accent) 28%, transparent)}

/* ── 中：画布 ─────────────────────────────────────────────────────────── */
.sc-stage{
  position:relative;min-width:0;min-height:0;overflow:hidden;
  background:
    radial-gradient(72% 58% at 50% 42%, color-mix(in srgb, var(--sc-accent) 5%, transparent), transparent 72%),
    var(--sc-surface);
}
.sc-canvas-wrap{position:absolute;inset:0;overflow:hidden;container-type:size;container-name:sc-canvas}
.sc-canvas-wrap.is-hidden{display:none}
.sc-canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;cursor:grab}
.sc-canvas:active{cursor:grabbing}

/* 顶部悬浮：会话 + 当前状态 */
.sc-canvas-top{
  position:absolute;left:14px;top:14px;z-index:4;max-width:min(560px,calc(100% - 96px));
  display:flex;flex-direction:column;gap:7px;padding:10px 12px;border-radius:12px;
  border:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 82%, transparent);
  -webkit-backdrop-filter:blur(14px) saturate(1.1);backdrop-filter:blur(14px) saturate(1.1);
  box-shadow:0 10px 30px -24px color-mix(in srgb, var(--sc-text) 60%, transparent);
}
.sc-canvas-top-row{display:flex;align-items:center;gap:8px;min-width:0}
.sc-top-id{display:flex;align-items:center;gap:7px;min-width:0;flex:1}
.sc-top-dot{width:6px;height:6px;border-radius:50%;background:var(--dot,var(--sc-hit));flex-shrink:0;
  box-shadow:0 0 0 3px color-mix(in srgb, var(--dot,var(--sc-hit)) 14%, transparent)}
.sc-top-name{font-family:var(--sc-mono);font-size:10.5px;line-height:1.4;color:var(--sc-text2);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-top-btn{
  appearance:none;display:none;align-items:center;gap:5px;height:24px;padding:0 8px;
  border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);background:transparent;
  font:inherit;font-size:11px;color:var(--sc-text2);cursor:pointer;flex-shrink:0;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-top-btn:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-layer2) 70%, transparent)}
.sc-canvas-summary{min-width:0}
.sc-canvas-summary-text{
  margin:0;font-size:11.5px;line-height:1.55;color:var(--sc-text2);overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}
.sc-now{
  display:inline-flex;align-items:center;gap:8px;align-self:flex-start;max-width:100%;
  padding:3px 9px 3px 4px;border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);
  background:color-mix(in srgb, var(--sc-layer2) 52%, transparent);
}
.sc-now-step{
  display:inline-flex;align-items:center;justify-content:center;min-width:25px;height:20px;padding:0 5px;
  border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);background:var(--sc-surface);
  font-family:var(--sc-mono);font-size:10px;color:var(--sc-text);flex-shrink:0;
}
.sc-now-text{min-width:0;font-size:11.5px;color:var(--sc-text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* tooltip */
.sc-tooltip{
  position:absolute;z-index:6;transform:translate(-50%,-100%);min-width:172px;max-width:288px;
  padding:9px 11px;border-radius:var(--sc-r-md);border:1px solid var(--sc-line-strong);
  background:color-mix(in srgb, var(--sc-layer1) 94%, transparent);
  -webkit-backdrop-filter:blur(12px) saturate(1.1);backdrop-filter:blur(12px) saturate(1.1);
  box-shadow:var(--sc-shadow-float);pointer-events:none;
}
.sc-tooltip.is-below{transform:translate(-50%,0)}
.sc-tooltip-title{font-size:12.5px;font-weight:600;line-height:1.4;color:var(--sc-text);overflow-wrap:anywhere}
.sc-tooltip-sub{margin-top:3px;font-size:11px;line-height:1.5;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-tooltip-meta{margin-top:5px;font-family:var(--sc-mono);font-size:10px;line-height:1.4;color:var(--sc-text3);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* 底部停靠区：快捷键提示 / 图例 / 回放条共用一条排版，不再各自绝对定位到同一个左下角。
   右侧留出迷你地图的宽度（168 宽 + 16 右边距 + 30 空隙 = 214px），回放条不会盖住它。 */
.sc-canvas-dock{
  position:absolute;left:0;right:0;bottom:0;z-index:5;
  display:grid;grid-template-columns:auto minmax(0,1fr);align-items:end;
  gap:10px;padding:0 214px 14px 14px;pointer-events:none;
}
/* 停靠区只让真正的控件接收指针事件：格子本身透明，不能挡住画布拖拽与点选。 */
.sc-canvas-dock,.sc-dock-side,.sc-dock-main{pointer-events:none}
.sc-canvas-dock .sc-hint,.sc-canvas-dock .sc-legend,.sc-canvas-dock .sc-replay{pointer-events:auto}
.sc-dock-side{display:flex;flex-direction:column;align-items:flex-start;gap:6px;min-width:0;max-width:min(360px,52cqw)}
.sc-dock-main{display:flex;justify-content:center;min-width:0}

/* 图例 */
.sc-legend{
  display:flex;flex-direction:column;gap:5px;max-width:100%;min-width:0;
  padding:7px 9px;border:1px solid var(--sc-line);border-radius:var(--sc-r-md);
  background:color-mix(in srgb, var(--sc-layer1) 76%, transparent);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
}
.sc-legend-toggle{
  appearance:none;border:0;background:transparent;display:flex;align-items:center;gap:6px;
  height:16px;padding:0;font:inherit;font-size:10.5px;letter-spacing:.4px;color:var(--sc-text2);
  cursor:pointer;
}
.sc-legend-toggle:hover{color:var(--sc-text)}
.sc-legend-items{display:flex;flex-wrap:wrap;gap:5px 11px;max-width:100%}
.sc-legend-item{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:var(--sc-text2);white-space:nowrap}
.sc-legend-count{font-family:var(--sc-mono);font-size:10px;color:var(--sc-text3)}
.sc-dot{width:7px;height:7px;border-radius:50%;background:var(--dot,var(--sc-feedback));flex-shrink:0}

/* 缩放按钮（迷你地图在引擎画的右下角，DOM 按钮排在它上面） */
.sc-zoom{position:absolute;right:14px;bottom:148px;z-index:3;display:flex;flex-direction:column;gap:6px}
.sc-zoom-btn{
  width:32px;height:32px;border:1px solid var(--sc-line);border-radius:50%;
  background:color-mix(in srgb, var(--sc-layer1) 82%, transparent);
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  color:var(--sc-text2);display:flex;align-items:center;justify-content:center;cursor:pointer;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-zoom-btn:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-layer2) 82%, transparent);transform:translateY(-1px)}

/* 回放条 */
.sc-replay{
  display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:var(--sc-r-pill);
  border:1px solid var(--sc-line-strong);
  background:color-mix(in srgb, var(--sc-layer1) 84%, transparent);
  -webkit-backdrop-filter:blur(16px) saturate(1.15);backdrop-filter:blur(16px) saturate(1.15);
  box-shadow:var(--sc-shadow-float);max-width:100%;min-width:0;
}
.sc-replay.is-idle{padding:5px 7px}
/* 活动态占满主格：不拉伸时轨道只剩 min-width，刻度文字会互压。600 够「340 轨道 + 固定控件」。 */
.sc-replay.is-active{width:100%;max-width:600px}
.sc-replay-start{
  appearance:none;border:0;display:flex;align-items:center;gap:7px;
  padding:6px 12px 6px 10px;border-radius:var(--sc-r-pill);
  background:var(--sc-accent);color:var(--sc-on-accent);font:inherit;font-size:12px;font-weight:600;cursor:pointer;
  transition:filter var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-start:hover{filter:brightness(1.07);transform:translateY(-1px)}
.sc-replay-total{font-size:10.5px;font-weight:400;opacity:.82}
.sc-replay-play{
  width:34px;height:34px;border:0;border-radius:50%;flex-shrink:0;
  background:var(--sc-accent);color:var(--sc-on-accent);display:flex;align-items:center;justify-content:center;cursor:pointer;
  transition:filter var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-play:hover{filter:brightness(1.07)}
.sc-replay-track{
  position:relative;flex:1 1 clamp(150px,26cqw,340px);min-width:76px;max-width:340px;height:22px;
  border-radius:var(--sc-r-pill);background:color-mix(in srgb, var(--sc-text) 8%, transparent);cursor:pointer;
}
.sc-replay-fill{
  position:absolute;left:0;top:0;bottom:0;border-radius:var(--sc-r-pill);
  background:linear-gradient(90deg, color-mix(in srgb, var(--sc-accent) 24%, transparent), color-mix(in srgb, var(--sc-accent) 46%, transparent));
  transition:width var(--sc-m-base) var(--sc-ease);
}
.sc-replay-tick{
  position:absolute;top:50%;transform:translate(-50%,-50%);
  appearance:none;border:0;background:transparent;padding:0;cursor:pointer;
  display:flex;flex-direction:column;align-items:center;gap:1px;color:var(--sc-text3);
}
.sc-replay-tick::before{
  content:"";display:block;width:2px;height:9px;border-radius:1px;
  background:color-mix(in srgb, var(--sc-text) 30%, transparent);
  transition:background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-tick.is-past::before{background:color-mix(in srgb, var(--sc-accent) 75%, transparent)}
.sc-replay-tick-label{
  position:absolute;top:13px;font-family:var(--sc-mono);font-size:8.5px;line-height:1;
  white-space:nowrap;opacity:0;transition:opacity var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-tick:hover .sc-replay-tick-label,.sc-replay-tick.is-past .sc-replay-tick-label{opacity:1}
.sc-replay-count{font-family:var(--sc-mono);font-size:10.5px;color:var(--sc-text2);min-width:52px;text-align:center;
  font-variant-numeric:tabular-nums;flex-shrink:0}
.sc-replay-speed{display:flex;gap:1px;padding:2px;border-radius:var(--sc-r-pill);
  background:color-mix(in srgb, var(--sc-text) 7%, transparent);flex-shrink:0}
.sc-replay-speed-btn{
  appearance:none;border:0;background:transparent;font:inherit;font-size:10.5px;color:var(--sc-text2);
  padding:3px 7px;border-radius:var(--sc-r-pill);cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-speed-btn.is-on{background:var(--sc-surface);color:var(--sc-text);box-shadow:0 1px 2px color-mix(in srgb, var(--sc-text) 12%, transparent)}
.sc-replay-close{
  width:24px;height:24px;border:0;border-radius:50%;background:transparent;color:var(--sc-text2);
  display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-close:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 8%, transparent)}

/* 画布空态 / 错误态 / 读取态 */
.sc-stage-overlay{
  position:absolute;inset:0;z-index:5;display:flex;align-items:center;justify-content:center;padding:24px;
  background:color-mix(in srgb, var(--sc-surface) 62%, transparent);
  -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
}
.sc-empty-card{
  width:min(432px,100%);padding:22px 22px 18px;border:1px solid var(--sc-line);border-radius:16px;
  background:var(--sc-layer1);box-shadow:0 26px 70px -34px color-mix(in srgb, var(--sc-text) 48%, transparent);
  display:flex;flex-direction:column;align-items:flex-start;gap:10px;
}
.sc-empty-icon{color:var(--sc-text2);display:flex;align-items:center;justify-content:center}
.sc-empty-card.is-error .sc-empty-icon{color:var(--sc-warn)}
.sc-empty-title{font-size:15px;font-weight:650;line-height:1.4;color:var(--sc-text)}
.sc-empty-text{margin:0;font-size:12px;line-height:1.68;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-empty-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.sc-state-path{font-family:var(--sc-mono);font-size:11px;line-height:1.55;color:var(--sc-text3);overflow-wrap:anywhere}
.sc-state-path.is-warn{font-family:var(--sc-font);color:var(--sc-warn)}
.sc-state-hint{font-size:11.5px;line-height:1.6;color:var(--sc-text3)}
.sc-command{
  display:flex;align-items:center;gap:6px;padding:5px 6px 5px 10px;max-width:100%;
  border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer2) 52%, transparent);
  font-family:var(--sc-mono);font-size:11.5px;color:var(--sc-text);
}
.sc-command code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-state-screen{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;padding:28px;overflow:auto}
.sc-stage-loading{
  position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;
  color:var(--sc-text2);font-size:11.5px;pointer-events:none;
}

/* ── 右：检查器 ───────────────────────────────────────────────────────── */
.sc-inspector{
  position:relative;display:flex;flex-direction:column;min-height:0;min-width:0;
  border-left:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 44%, var(--sc-surface));
  overflow:hidden;
}
.sc-insp-headbar{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px 7px}
.sc-insp-kicker{font-size:10.5px;font-weight:550;letter-spacing:.5px;color:var(--sc-text3)}
.sc-insp-close{
  display:none;appearance:none;border:1px solid var(--sc-line);border-radius:50%;
  width:26px;height:26px;background:transparent;color:var(--sc-text2);
  align-items:center;justify-content:center;cursor:pointer;
}
.sc-insp-close:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 8%, transparent)}
.sc-insp-body{
  flex:1;min-height:0;overflow:auto;padding:0 14px 18px;
  display:flex;flex-direction:column;gap:12px;overscroll-behavior:contain;
  animation:sc-fade-in var(--sc-m-base) var(--sc-ease) both;
}
.sc-overview{min-width:0}
.sc-overview-lead{font-size:12px;line-height:1.65;color:var(--sc-text2);margin-top:-2px}
.sc-insp-header{display:flex;align-items:flex-start;gap:10px;padding:2px 0}
.sc-avatar{
  width:40px;height:40px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;color:var(--tone,var(--sc-feedback));
  background:color-mix(in srgb, var(--tone,var(--sc-feedback)) 16%, transparent);
  border:1px solid color-mix(in srgb, var(--tone,var(--sc-feedback)) 26%, transparent);
}
.sc-avatar-inner{display:flex}
.sc-insp-headtext{flex:1;min-width:0}
.sc-insp-title{font-size:var(--sc-fs-md);font-weight:650;line-height:1.45;color:var(--sc-text);overflow-wrap:anywhere}
.sc-insp-meta{margin-top:3px;font-family:var(--sc-mono);font-size:10.5px;line-height:1.55;color:var(--sc-text3);overflow-wrap:anywhere}
.sc-insights{display:flex;flex-direction:column;gap:9px}
.sc-insight{display:flex;align-items:flex-start;gap:8px}
.sc-insight-dot{width:7px;height:7px;border-radius:50%;margin-top:5px;flex-shrink:0;
  background:var(--dot,var(--sc-feedback));
  box-shadow:0 0 0 3px color-mix(in srgb, var(--dot,var(--sc-feedback)) 12%, transparent)}
.sc-insight-body{min-width:0}
.sc-insight-title{font-size:var(--sc-fs-xs);font-weight:600;line-height:1.5;color:var(--sc-text)}
.sc-insight-text{margin-top:2px;font-size:12px;line-height:1.66;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-insp-empty{padding:6px 0;font-size:12px;line-height:1.65;color:var(--sc-text2)}
.sc-overview-sep{height:1px;background:var(--sc-line);margin:2px 0 10px}
.sc-overview-legend{display:flex;flex-direction:column;gap:6px}
.sc-kicker{font-size:10.5px;font-weight:550;letter-spacing:.4px;color:var(--sc-text3)}
.sc-legend-row{display:flex;align-items:center;gap:7px;font-size:11.5px;color:var(--sc-text2)}
.sc-legend-row-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-legend-row-count{font-family:var(--sc-mono);font-size:10.5px;color:var(--sc-text3)}
.sc-footnote{margin-top:auto;padding-top:10px;border-top:1px solid var(--sc-line);
  font-size:10.5px;line-height:1.55;color:var(--sc-text3);overflow-wrap:anywhere}

/* 检查器分区 */
.sc-sec{border-top:1px solid var(--sc-line);padding-top:1px}
.sc-sec-toggle{
  appearance:none;border:0;background:transparent;width:100%;display:flex;align-items:center;gap:8px;
  padding:8px 0 7px;font:inherit;font-size:var(--sc-fs-sm);font-weight:600;color:var(--sc-text);
  cursor:pointer;text-align:left;
}
.sc-sec-toggle:hover{color:var(--sc-text)}
.sc-sec-title{flex:1;min-width:0}
.sc-sec-count{font-family:var(--sc-mono);font-size:10px;font-weight:400;color:var(--sc-text3)}
.sc-sec-chev{flex-shrink:0;color:var(--sc-text3);transition:color var(--sc-m-fast) var(--sc-ease)}
.sc-sec-toggle:hover .sc-sec-chev{color:var(--sc-text2)}
.sc-sec-body{padding:0 0 10px;animation:sc-fade-in var(--sc-m-fast) var(--sc-ease) both}
.sc-p{margin:0 0 8px;font-size:12px;line-height:1.72;color:var(--sc-text2);overflow-wrap:anywhere;white-space:pre-wrap}
.sc-p:last-child{margin-bottom:0}
.sc-kv{display:flex;flex-direction:column;gap:6px}
.sc-kv-row{display:grid;grid-template-columns:88px minmax(0,1fr);gap:8px;align-items:start}
.sc-kv-key{font-family:var(--sc-mono);font-size:10.5px;line-height:1.65;color:var(--sc-text3);overflow-wrap:anywhere}
.sc-kv-val{min-width:0;font-size:11.5px;line-height:1.65;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-kv-val.is-warn{color:var(--sc-warn)}
.sc-evidence{min-width:0}
.sc-evidence-label{display:flex;align-items:center;justify-content:space-between;gap:8px;
  font-size:10.5px;color:var(--sc-text3);margin-bottom:5px}
.sc-evidence-count{font-family:var(--sc-mono)}
.sc-evidence-inline{
  margin:0;padding:8px 10px;max-height:220px;overflow:auto;
  border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer2) 45%, transparent);
  font-family:var(--sc-mono);font-size:10.5px;line-height:1.66;color:var(--sc-text2);
  overflow-wrap:anywhere;
}
.sc-inline-fold{
  appearance:none;border:0;background:transparent;padding:4px 0 0;
  font:inherit;font-size:10.5px;color:var(--sc-accent);cursor:pointer;
}
.sc-inline-fold:hover{opacity:.8}
.sc-files{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.sc-filerow{display:flex;align-items:flex-start;gap:6px;min-width:0}
.sc-file{flex:1;min-width:0;font-family:var(--sc-mono);font-size:10.5px;line-height:1.6;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-copy-btn{
  appearance:none;flex-shrink:0;border:1px solid var(--sc-line);border-radius:5px;background:transparent;
  padding:2px 6px;font:inherit;font-size:10px;line-height:1.4;color:var(--sc-text3);cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-copy-btn:hover{color:var(--sc-text);border-color:var(--sc-line-strong);background:color-mix(in srgb, var(--sc-text) 6%, transparent)}
.sc-missing{display:flex;align-items:flex-start;gap:6px;margin-top:8px;
  font-size:11px;line-height:1.6;color:var(--sc-warn);overflow-wrap:anywhere}
.sc-missing svg{flex-shrink:0;margin-top:2px}
.sc-chipgroups{display:flex;flex-direction:column;gap:9px}
.sc-chipgroup{min-width:0}
.sc-chipgroup-label{font-family:var(--sc-mono);font-size:10px;line-height:1.4;color:var(--sc-text3);margin-bottom:4px}
.sc-chipgroup-values{display:flex;flex-wrap:wrap;gap:5px}
.sc-value-chip{
  appearance:none;display:inline-flex;align-items:center;gap:5px;max-width:100%;
  padding:3px 7px;border:1px solid color-mix(in srgb, var(--tone,var(--sc-feedback)) 30%, transparent);
  border-radius:6px;background:color-mix(in srgb, var(--tone,var(--sc-feedback)) 9%, transparent);
  font-family:var(--sc-mono);font-size:10.5px;line-height:1.45;color:var(--sc-text);cursor:pointer;
  transition:background-color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease);
}
.sc-value-chip:hover{background:color-mix(in srgb, var(--tone,var(--sc-feedback)) 15%, transparent);
  border-color:color-mix(in srgb, var(--tone,var(--sc-feedback)) 46%, transparent)}
.sc-value-chip-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:230px}
.sc-value-chip-copied{font-family:var(--sc-font);font-size:10px;color:var(--tone,var(--sc-feedback))}
.sc-tools{display:flex;flex-direction:column;gap:5px}
.sc-tool{display:flex;align-items:flex-start;gap:7px}
.sc-tool-n{min-width:14px;padding-top:1px;text-align:right;font-family:var(--sc-mono);font-size:10px;color:var(--sc-text3)}
.sc-tool-text{flex:1;min-width:0;font-family:var(--sc-mono);font-size:10.5px;line-height:1.62;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-insp-foot{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px;padding-top:10px;border-top:1px solid var(--sc-line)}
.sc-insp-foot .sc-btn{flex:1;min-width:0;padding:0 8px;font-size:11px}
.sc-insp-foot .sc-locate{flex-basis:100%}

/* ── 骨架 / 加载 ──────────────────────────────────────────────────────── */
.sc-loading{height:100%;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.sc-skel{
  background:linear-gradient(90deg,
    color-mix(in srgb, var(--sc-text) 7%, transparent) 0%,
    color-mix(in srgb, var(--sc-text) 13%, transparent) 50%,
    color-mix(in srgb, var(--sc-text) 7%, transparent) 100%);
  background-size:200% 100%;animation:sc-shimmer 1.4s linear infinite;border-radius:8px;
}
.sc-skel-mark{width:26px;height:26px;border-radius:8px;flex-shrink:0}
.sc-skel-title{width:118px;height:18px}
.sc-skel-sub{width:148px;height:11px;margin-top:6px}
.sc-skel-chips{width:280px;height:26px;border-radius:var(--sc-r-pill);margin-left:auto}
.sc-skel-search{height:32px;margin:14px 14px 10px}
.sc-skel-card{height:92px;margin:0 12px 8px;flex-shrink:0}
.sc-skel-canvas{position:absolute;inset:16px;border-radius:var(--sc-r-lg)}
.sc-skel-line{height:12px;margin:14px 14px 0}
.sc-skel-line.is-wide{width:70%}
.sc-skel-line.is-short{width:45%}
.sc-skel-float{width:200px;height:84px;border-radius:var(--sc-r-lg)}
.sc-stage-loading-text{font-size:11px;letter-spacing:.3px}

/* ── 窄容器降级（容器查询，不监听 window 宽度）────────────────────────── */
@container (max-width:1080px){
  .sc-body{grid-template-columns:264px minmax(0,1fr)}
  .sc-inspector{
    position:absolute;left:12px;right:12px;bottom:12px;max-height:56%;z-index:12;display:none;
    border:1px solid var(--sc-line-strong);border-left-width:1px;border-radius:var(--sc-r-lg);
    background:color-mix(in srgb, var(--sc-layer1) 94%, transparent);
    -webkit-backdrop-filter:blur(18px) saturate(1.1);backdrop-filter:blur(18px) saturate(1.1);
    box-shadow:0 26px 74px -30px color-mix(in srgb, var(--sc-text) 55%, transparent);
  }
  .sc-root[data-inspector="open"] .sc-inspector{display:flex}
  .sc-inspector .sc-insp-close{display:flex}
  .sc-top-btn.sc-insp-toggle{display:inline-flex}
  .sc-insp-headbar{padding:10px 14px 6px}
  .sc-insp-body{padding:0 14px 12px}
}
@container (max-width:900px){
  .sc-body{grid-template-columns:56px minmax(0,1fr)}
  .sc-list{align-items:center;padding-top:10px}
  .sc-list-main{display:none}
  .sc-list-rail{
    display:flex;flex-direction:column;align-items:center;gap:7px;padding-bottom:12px;width:100%;
    flex:1;min-height:0;overflow-y:auto;scrollbar-width:none;
  }
  .sc-list-rail::-webkit-scrollbar{display:none}
  .sc-rail-btn{
    appearance:none;width:34px;height:34px;border:1px solid var(--sc-line);border-radius:9px;
    background:color-mix(in srgb, var(--sc-layer2) 55%, transparent);color:var(--sc-text2);
    display:flex;align-items:center;justify-content:center;cursor:pointer;
    transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
  }
  .sc-rail-btn:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-layer2) 85%, transparent)}
  .sc-rail-dot{
    appearance:none;width:34px;height:30px;border:1px solid transparent;border-radius:9px;
    background:transparent;display:flex;align-items:center;justify-content:center;cursor:pointer;
    transition:background-color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease);
  }
  .sc-rail-dot:hover{background:color-mix(in srgb, var(--sc-layer2) 65%, transparent)}
  .sc-rail-dot.is-active{border-color:color-mix(in srgb, var(--sc-accent) 32%, transparent);background:color-mix(in srgb, var(--sc-layer2) 82%, transparent)}
  .sc-rail-dot .sc-status-dot{width:8px;height:8px}
  .sc-root[data-list="open"] .sc-list{position:absolute;left:0;top:0;bottom:0;width:272px;z-index:14;align-items:stretch;
    padding-top:0;background:color-mix(in srgb, var(--sc-layer1) 96%, transparent);
    -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
    box-shadow:0 26px 74px -30px color-mix(in srgb, var(--sc-text) 55%, transparent);border-right:1px solid var(--sc-line-strong)}
  .sc-root[data-list="open"] .sc-list-rail{display:none}
  .sc-root[data-list="open"] .sc-list-main{display:flex}
  .sc-root[data-list="open"] .sc-list-toggle{display:flex}
  .sc-skel-chips{width:180px}
}
@container (max-width:720px){
  .sc-header{padding:9px 12px 8px;column-gap:10px}
  .sc-title{font-size:17px}
  .sc-sub{display:none}
  .sc-chips .sc-chip-key{display:none}
  .sc-chips .sc-chip{padding:0 8px;max-width:150px}
  .sc-summary-text{-webkit-line-clamp:2}
  .sc-canvas-top{left:10px;top:10px;max-width:calc(100% - 20px);padding:8px 10px}
  .sc-canvas-summary{display:none}
  .sc-zoom{right:10px;bottom:132px}
  .sc-canvas-dock{padding:0 214px 10px 10px}
  .sc-replay{gap:7px;padding:6px 8px}
  .sc-replay-count{min-width:44px;font-size:10px}
  .sc-replay-tick-label{display:none}
  .sc-inspector{left:8px;right:8px;bottom:8px;max-height:62%}
  .sc-insp-foot .sc-btn{font-size:10.5px}
  .sc-empty-card{padding:18px}
}
@container (max-width:560px){
  .sc-chip:nth-child(n+3){display:none}
  .sc-summary-toggle{display:none}
  .sc-replay-count{display:none}
}

/* ── 画布底部停靠区：按画布尺寸降级（容器名 sc-canvas，尺寸取 .sc-canvas-wrap）── */
/* 一排要放下「图例 360 + 回放条」；画布 ≤1100 时横向装不下，改成两行（提示/图例在上、回放条贴底），
   回放条才能拿到足够宽的进度轨道。 */
@container sc-canvas (max-width:1100px){
  .sc-canvas-dock{grid-template-columns:minmax(0,1fr);gap:8px}
  .sc-dock-side{max-width:min(360px,100%)}
}
@container sc-canvas (max-width:620px){
  .sc-replay-speed{display:none}
}
/* 迷你地图在画布宽 <560 时不画（引擎 MINIMAP_MIN_W），右侧那 214px 留白可以收回。
   边界写 559 是保守取值：引擎按取整后的宽度判（Math.round），宁可多留白也不让回放条压到迷你地图。 */
@container sc-canvas (max-width:559px){
  .sc-canvas-dock{padding-right:10px}
}
/* 画布太矮时缩放钮会顶出画布上沿（底部 132px + 108px 高），摘掉它。 */
@container sc-canvas (max-height:240px){
  .sc-zoom{display:none}
}


/* ── 结论卡 / 导出菜单 / 列表视图 / 快捷键提示 / 操作反馈 ─────────────── */
.sc-root{position:relative}
.sc-head-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
.sc-btn-icon{padding:0 9px}
.sc-btn-icon.is-on{color:var(--sc-text);border-color:var(--sc-line-strong);background:color-mix(in srgb, var(--sc-layer2) 82%, transparent)}
.sc-export{position:relative;display:flex}
.sc-export-menu{
  position:absolute;right:0;top:calc(100% + 8px);z-index:24;min-width:212px;padding:5px;
  display:flex;flex-direction:column;gap:2px;border-radius:10px;border:1px solid var(--sc-line);
  background:var(--sc-overlay);box-shadow:var(--sc-shadow-float);
  animation:sc-fade-in var(--sc-m-base) var(--sc-ease) both;
}
.sc-export-item{
  appearance:none;display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;
  border:0;border-radius:7px;background:transparent;color:var(--sc-text);font:inherit;font-size:12px;
  text-align:left;cursor:pointer;white-space:nowrap;
  transition:background-color var(--sc-m-fast) var(--sc-ease),color var(--sc-m-fast) var(--sc-ease);
}
.sc-export-item:hover{background:color-mix(in srgb, var(--sc-layer2) 82%, transparent)}
.sc-export-item:disabled{opacity:.45;cursor:default}
.sc-export-item svg{color:var(--sc-text2);flex-shrink:0}

.sc-conclusion{
  grid-area:conclusion;display:flex;align-items:center;gap:10px;min-width:0;margin-top:7px;
  padding:7px 10px 7px 0;border:1px solid color-mix(in srgb, var(--tone) 30%, var(--sc-line));
  border-radius:10px;background:color-mix(in srgb, var(--tone) 7%, var(--sc-surface));
  cursor:default;transition:border-color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-conclusion.is-clickable{cursor:pointer}
.sc-conclusion.is-clickable:hover{background:color-mix(in srgb, var(--tone) 12%, var(--sc-surface));border-color:color-mix(in srgb, var(--tone) 48%, var(--sc-line))}
.sc-conclusion.is-clickable:focus-visible{outline:2px solid color-mix(in srgb, var(--tone) 55%, transparent);outline-offset:2px}
.sc-conclusion.is-empty{opacity:.88}
.sc-conclusion-bar{width:3px;align-self:stretch;border-radius:0 3px 3px 0;background:var(--tone);flex-shrink:0}
.sc-conclusion-label{flex-shrink:0;font-size:10.5px;font-weight:650;letter-spacing:.3px;color:var(--tone);white-space:nowrap}
.sc-conclusion-main{flex:1;min-width:0;display:flex;align-items:baseline;gap:10px}
.sc-conclusion-title{flex-shrink:0;font-size:12.5px;font-weight:600;color:var(--sc-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46%}
.sc-conclusion-text{min-width:0;font-size:11.5px;color:var(--sc-text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-conclusion-badges{display:flex;align-items:center;gap:4px;flex-shrink:0}
.sc-conclusion-go{flex-shrink:0;font-size:11px;color:var(--tone);white-space:nowrap}
.sc-badge{
  display:inline-flex;align-items:center;height:18px;padding:0 7px;border-radius:999px;
  border:1px solid var(--sc-line);font-size:10.5px;line-height:1;color:var(--sc-text2);white-space:nowrap;
  background:color-mix(in srgb, var(--sc-layer1) 72%, transparent);
}
.sc-badge-hit{color:var(--sc-hit);border-color:color-mix(in srgb, var(--sc-hit) 34%, transparent);background:color-mix(in srgb, var(--sc-hit) 10%, transparent)}
.sc-badge-warn{color:var(--sc-warn);border-color:color-mix(in srgb, var(--sc-warn) 34%, transparent);background:color-mix(in srgb, var(--sc-warn) 10%, transparent)}
.sc-badge-book{color:var(--sc-book);border-color:color-mix(in srgb, var(--sc-book) 34%, transparent);background:color-mix(in srgb, var(--sc-book) 10%, transparent)}
.sc-badge-risk{color:var(--sc-risk);border-color:color-mix(in srgb, var(--sc-risk) 40%, transparent);background:color-mix(in srgb, var(--sc-risk) 11%, transparent)}
.sc-badge-neutral{color:var(--sc-text2)}

.sc-top-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
.sc-table-wrap{position:absolute;inset:0;z-index:7;display:flex;flex-direction:column;background:var(--sc-surface)}
.sc-table-head{flex-shrink:0;display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid var(--sc-line);background:linear-gradient(180deg,color-mix(in srgb,var(--sc-layer1) 70%,var(--sc-surface)),var(--sc-surface))}
.sc-table-title{font-size:13px;font-weight:650;flex-shrink:0}
.sc-table-meta{min-width:0;font-size:11.5px;color:var(--sc-text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-table-head .sc-btn{margin-left:auto;flex-shrink:0}
.sc-table-scroll{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain}
.sc-table{min-width:660px;display:flex;flex-direction:column}
.sc-tr{display:grid;grid-template-columns:54px 52px 104px minmax(220px,1fr) minmax(120px,220px);gap:12px;align-items:start;padding:8px 14px;border-bottom:1px solid var(--sc-line);font-size:12px}
.sc-thead{position:sticky;top:0;z-index:2;background:color-mix(in srgb, var(--sc-layer1) 94%, transparent);font-size:10.5px;color:var(--sc-text3);letter-spacing:.3px;padding-top:7px;padding-bottom:7px}
.sc-th{font-weight:600;white-space:nowrap}
.sc-trow{cursor:pointer;color:var(--sc-text);transition:background-color var(--sc-m-fast) var(--sc-ease)}
.sc-trow:hover{background:color-mix(in srgb, var(--sc-layer2) 62%, transparent)}
.sc-trow.is-active{background:color-mix(in srgb, var(--tone) 11%, var(--sc-surface));box-shadow:inset 3px 0 0 var(--tone)}
.sc-trow.is-conclusion .sc-td-title{font-weight:650}
.sc-trow:focus-visible{outline:2px solid color-mix(in srgb, var(--sc-accent) 55%, transparent);outline-offset:-2px}
.sc-td{min-width:0;color:var(--sc-text2)}
.sc-td-step{font-family:var(--sc-mono);font-size:11px;color:var(--sc-text3)}
.sc-td-role{font-size:11px}
.sc-td-action{font-size:11.5px;font-weight:550;color:var(--sc-text)}
.sc-td-title{font-size:12.5px;font-weight:600;color:var(--sc-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-td-sub{margin-top:2px;font-size:11px;color:var(--sc-text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-td-marks{display:flex;flex-wrap:wrap;gap:4px}
.sc-mark{font-size:10.5px;padding:1px 6px;border-radius:999px;border:1px solid var(--sc-line);color:var(--sc-text2);white-space:nowrap;background:color-mix(in srgb, var(--sc-layer1) 65%, transparent)}

.sc-hint{
  display:flex;align-items:flex-start;gap:8px;max-width:100%;min-width:0;
  padding:6px 8px 6px 11px;border-radius:10px;border:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 84%, transparent);
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  font-size:11px;color:var(--sc-text2);animation:sc-fade-in var(--sc-m-slow) var(--sc-ease) both;
}
.sc-hint-text{
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;overflow-wrap:anywhere;line-height:1.5;
}
.sc-hint-close{appearance:none;border:0;background:transparent;color:var(--sc-text3);width:16px;height:16px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0}
.sc-hint-close:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 10%, transparent)}

.sc-notice{
  position:absolute;left:50%;bottom:76px;z-index:40;max-width:min(560px,calc(100% - 32px));
  transform:translate(-50%,8px);padding:8px 14px;border-radius:999px;border:1px solid var(--sc-line);
  background:var(--sc-overlay);box-shadow:var(--sc-shadow-float);font-size:12px;color:var(--sc-text);
  opacity:0;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  transition:opacity var(--sc-m-base) var(--sc-ease),transform var(--sc-m-base) var(--sc-ease);
}
.sc-notice.is-on{opacity:1;transform:translate(-50%,0)}

@container (max-width:900px){
  .sc-head-actions .sc-btn-text{display:none}
  .sc-head-actions .sc-btn-icon{padding:0 8px}
  .sc-conclusion-text{display:none}
}
@container (max-width:720px){
  .sc-conclusion-badges{display:none}
}

/* ── 动效 ─────────────────────────────────────────────────────────────── */
@keyframes sc-fade-in{from{opacity:0}to{opacity:1}}
@keyframes sc-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
@keyframes sc-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}

@media (prefers-reduced-motion: reduce){
  .sc-root *,.sc-root *::before,.sc-root *::after{
    animation-duration:0ms !important;animation-iteration-count:1 !important;
    transition-duration:0ms !important;scroll-behavior:auto !important;
  }
  .sc-skel{animation:none;background:color-mix(in srgb, var(--sc-text) 9%, transparent)}
  .sc-insp-body,.sc-sec-body{animation:none}
}
`
})(SC)

// ─── client-src/90-plugin.js ───
;(function (SC) {
// 插件装配：styles 注入、host RPC 适配、两个注册面（主区整页 + 左栏图标）。
//
// 常驻插件包的 client 半没有动态沙箱的 `host` / `styles` 全局，这里按同样的语义补：
//   SC.host.call(endpoint, payload)  → connection.rpc.call('/sleuth-canvas', endpoint, payload)
//   apply 里插入 <style>，卸载时移除。

  const CHANNEL = '/sleuth-canvas'
  const PANEL_ID = 'sleuth-canvas'
  const PANEL_LABEL = '诊断画布'

  // 打开 DSH 会话：sessions.open(id) 由宿主界面负责切主区；客户端列表里没有这个 id 时会抛，
  // 页面把错误变成一条可见提示，不做静默失败。
  function makeSessionOpener(ctx) {
    return function openSession(id) {
      if (!id) return Promise.reject(new Error('这条 trace 没有 harness_session，找不到对应的 DSH 会话'))
      let sessions = null
      try { sessions = ctx.get('sessions') } catch (error) { sessions = null }
      if (!sessions || typeof sessions.open !== 'function') {
        return Promise.reject(new Error('sessions 服务不可用：当前界面打不开会话'))
      }
      try {
        return Promise.resolve(sessions.open(String(id)))
      } catch (error) {
        return Promise.reject(error)
      }
    }
  }

  function makeHost(ctx) {
    const connection = ctx.get('connection')
    return {
      call(endpoint, payload) {
        if (!connection || !connection.rpc || typeof connection.rpc.call !== 'function') {
          return Promise.reject(new Error('connection 服务不可用：拿不到 DSH 的 RPC 通道'))
        }
        return connection.rpc
          .call(CHANNEL, String(endpoint), payload === undefined ? {} : payload)
          .then(function (outer) {
            if (!outer || outer.ok !== true) {
              const failure = outer && outer.error
              throw new Error(failure && failure.message ? failure.message : 'RPC 失败')
            }
            return outer.value
          })
      },
    }
  }

  // 与 package 的 icon.svg 同形的侧栏图标：圆角方框里一条旅程曲线 + 三个节点。
  function CanvasIcon(props) {
    const size = props && typeof props.size === 'number' ? props.size : 18
    return SC.h(
      'svg',
      {
        viewBox: '0 0 24 24',
        width: size,
        height: size,
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.55,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
      },
      SC.h('rect', { x: 3.4, y: 3.4, width: 17.2, height: 17.2, rx: 5 }),
      SC.h('path', { d: 'M6.4 16.2c3.2 0 3.2-6.4 6.4-6.4s3.2 4.6 6.4 4.6' }),
      SC.h('circle', { cx: 6.4, cy: 16.2, r: 1.25, fill: 'currentColor', stroke: 'none' }),
      SC.h('circle', { cx: 12.8, cy: 9.8, r: 1.25, fill: 'currentColor', stroke: 'none' }),
      SC.h('circle', { cx: 19.2, cy: 14.4, r: 1.25, fill: 'currentColor', stroke: 'none' }),
    )
  }

  SC.CanvasIcon = CanvasIcon

  SC.plugin = {
    name: 'dsh-sleuth-canvas',
    inject: ['slots', 'connection', 'sessions'],
    apply(ctx) {
      const slots = ctx.get('slots')
      if (slots === undefined) {
        console.error('[sleuth-canvas] slots 服务不可用，界面不注册')
        return
      }
      SC.host = makeHost(ctx)
      SC.openSession = makeSessionOpener(ctx)

      const disposers = []
      try {
        const styleTag = document.createElement('style')
        styleTag.dataset.sleuthCanvas = 'true'
        styleTag.textContent = String(SC.css || '')
        document.head.appendChild(styleTag)
        disposers.push(function () { styleTag.remove() })
      } catch (error) {
        console.error('[sleuth-canvas] 样式注入失败: ' + String((error && error.message) || error))
      }

      try {
        disposers.push(slots.inject('main', function () {
          return slots.register({ name: 'main', key: PANEL_ID }, SC.CanvasPage)
        }))
        disposers.push(slots.inject('sidebar.panellist', function () {
          return slots.register({
            name: 'sidebar.panellist',
            id: PANEL_ID,
            order: 40,
            label: PANEL_LABEL,
          }, CanvasIcon)
        }))
      } catch (error) {
        console.error('[sleuth-canvas] 注册失败: ' + String((error && error.message) || error))
      }

      return function dispose() {
        for (const dispose of disposers) {
          try {
            if (typeof dispose === 'function') dispose()
          } catch (error) { /* 一个卸不掉不阻塞其余 */ }
        }
      }
    },
  }
})(SC)

    if (SC.plugin === undefined || typeof SC.plugin.apply !== 'function') {
      throw new Error('sleuth-canvas: client-src 没有装配出 SC.plugin.apply')
    }
    return SC.plugin
  },
})
