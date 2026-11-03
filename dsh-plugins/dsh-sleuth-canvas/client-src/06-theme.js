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
