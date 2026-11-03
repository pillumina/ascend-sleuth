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
