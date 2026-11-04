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
          view === 'canvas' && overview && overview.legend.length
            ? SC.h(
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
          view === 'canvas' ? renderReplay() : null,
          view === 'table' && detail && !showEmpty ? renderTable() : null,
          view === 'canvas' && detail && !showEmpty && !replay.active ? renderHint() : null,
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
