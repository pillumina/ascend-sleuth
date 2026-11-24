    // ── 面 3：诊断工作台（浮层）─────────────────────────────────────────────
    function Palette() {
      const s = useStore()
      const data = s.data && s.data.ok !== false ? s.data : null
      const rows = data ? (data.all || []) : []
      const canWrite = !!((s.data && s.data.capabilities && s.data.capabilities.canWrite))
      const filter = s.prefs.paletteFilter
      const [selected, setSelected] = React.useState(0)
      // 选中项按 sessionId 记住，10 秒刷新重排后仍停在同一条单上；只按数组下标存，
      // 别处更新一单就会静默换到另一单，动作会落到读者没在看的那条上。
      const selectedIdRef = React.useRef('')
      function selectIndex(next) {
        const row = visibleRows[next]
        selectedIdRef.current = row ? row.sessionId : ''
        setSelected(next)
      }
      const [searchText, setSearchText] = React.useState('')
      // 详情抬头「展开全文」按单号记：换单回到收起，不继承上一单的展开态。
      const [ledeOpenId, setLedeOpenId] = React.useState('')
      const [sedLedeOpenKey, setSedLedeOpenKey] = React.useState('')
      const [menuOpen, setMenuOpen] = React.useState(false)
      const [menuForm, setMenuForm] = React.useState(null)
      const [cmdOpen, setCmdOpen] = React.useState(false)
      const [cmdQuery, setCmdQuery] = React.useState('')
      const [cmdIndex, setCmdIndex] = React.useState(0)
      const [timelineState, setTimelineState] = React.useState({ open: false, loading: false, items: [], error: '' })
      // 故障过程（日志）默认收起，按单号记住展开态；上游时间线超过 3 条才折叠，同样按单号记。
      const [processOpenId, setProcessOpenId] = React.useState('')
      const [upstreamOpenId, setUpstreamOpenId] = React.useState('')
      const [toast, setToast] = React.useState('')
      const [reportState, setReportState] = React.useState({ open: false, loading: false, text: '', error: '' })
      const reportToken = React.useRef(0)
      const selectedRowRef = React.useRef('')
      const [undoBusy, setUndoBusy] = React.useState(false)
      const [sedSel, setSedSel] = React.useState(0)
      const [sedFilter, setSedFilter] = React.useState('all')
      const [promptKind, setPromptKind] = React.useState('')
      const [promptDetailsOpen, setPromptDetailsOpen] = React.useState(false)
      // 写记录失败时的兜底指令：与普通指令预览同一个弹层，正文由失败上下文生成。
      const [promptFallback, setPromptFallback] = React.useState(null)
      // 批量沉淀指令在弹层打开时冻结：后台每 10 秒刷新会重算 filtered，不能让名单在读者看的时候变。
      const [batchSed, setBatchSed] = React.useState(null)
      const [targetOpen, setTargetOpen] = React.useState(false)
      const [manualOpen, setManualOpen] = React.useState(false)
      const [targetResume, setTargetResume] = React.useState('')
      const [targetScope, setTargetScope] = React.useState('')
      const [targetRemote, setTargetRemote] = React.useState('')
      const [targetBase, setTargetBase] = React.useState('')
      const [targetBusy, setTargetBusy] = React.useState(false)
      const [checkBusy, setCheckBusy] = React.useState('')
      // 多选：选择集按稳定 id 记（诊断 sessionId / 沉淀草稿 key），每个视图各一份。
      // 只活在面板打开期间，不写 localStorage：队列会变，隔天恢复一批「已选」等于给过期范围。
      const [sel, setSel] = React.useState({ diagnosis: [], sediment: [] })
      const [selAnchor, setSelAnchor] = React.useState({ diagnosis: -1, sediment: -1 })
      // 选择撤销栈：只收选择集本身与当时的筛选/搜索词，最多 5 步；切视图清空（两边的 id 不同域）。
      const [selHist, setSelHist] = React.useState([])
      const [onlySel, setOnlySel] = React.useState({ diagnosis: false, sediment: false })
      // 显式选择态：默认不显示行前复选框（悬停才露），点「选择」或有勾选后全部露出。
      const [selecting, setSelecting] = React.useState({ diagnosis: false, sediment: false })
      const [batchMenu, setBatchMenu] = React.useState(false)
      // 动作回执：prompt = 指令类（只写「已填入，未确认发送」）；write = 面板自己写记录，可反写。
      const [receipt, setReceipt] = React.useState(null)
      const [receiptAsk, setReceiptAsk] = React.useState(false)
      // 所选范围的批次指令由 host 按 key 现算；加载中不让旧的全量指令先闪一下。
      const [scopedPrompt, setScopedPrompt] = React.useState(null)
      const promptRef = React.useRef(null)
      const promptToken = React.useRef(0)
      const targetRef = React.useRef(null)
      const manualRef = React.useRef(null)
      const cmdRef = React.useRef(null)
      const moreBtnRef = React.useRef(null)
      const menuWasOpenRef = React.useRef(false)
      const modalReturnRef = React.useRef(null)
      const toastTimer = React.useRef(null)
      const panelRef = React.useRef(null)
      const actionMenuRef = React.useRef(null)
      const diagTabRef = React.useRef(null)
      const sedTabRef = React.useRef(null)
      React.useEffect(() => {
        if (!menuOpen) return undefined
        const el = actionMenuRef.current
        if (el && typeof el.focus === 'function') {
          try { el.focus() } catch { /* 替身渲染没有焦点 API */ }
        }
        // 浮层是浮在详情上的，没有遮罩：点浮层外要收起；触发器自己的 mousedown 跳过，
        // 否则「再点一次更多操作」会先被这里关掉、又被 click 重新打开。
        const onDown = (event) => {
          const menu = actionMenuRef.current
          const target = event && event.target
          if (menu && target && typeof menu.contains === 'function' && menu.contains(target)) return
          const path = event && typeof event.composedPath === 'function' ? event.composedPath() : null
          if (path && path.some((node) => node && typeof node.getAttribute === 'function' && node.getAttribute('data-more-button') === 'true')) return
          setMenuOpen(false)
          setMenuForm(null)
        }
        document.addEventListener('mousedown', onDown, true)
        return () => document.removeEventListener('mousedown', onDown, true)
      }, [menuOpen])

      // 批次动作菜单：点浮层外收起。点了菜单项自己会收起，不再等这一下。
      React.useEffect(() => {
        if (!batchMenu) return undefined
        const onDown = (event) => {
          const path = event && typeof event.composedPath === 'function' ? event.composedPath() : []
          if (path.some((node) => node && typeof node.getAttribute === 'function'
            && node.getAttribute('data-batch-menu') === 'true')) return
          setBatchMenu(false)
        }
        document.addEventListener('mousedown', onDown, true)
        return () => document.removeEventListener('mousedown', onDown, true)
      }, [batchMenu])
      const searchRef = React.useRef(null)
      const listRef = React.useRef(null)
      const cmdInputRef = React.useRef(null)
      const timelineToken = React.useRef(0)
      const commandsRef = React.useRef([])
      const filtered = filterRows(rows, filter).filter((item) => matchesQuery(item, searchText))
      // 诊断视图批量沉淀的范围 = 当前筛选（含搜索词）；单条与批量共用这一份名单。
      // 批量沉淀不再绑「可沉淀」筛选：范围是当前筛选里被标为可沉淀的单（与筛选的定义一致）。
      // 筛选仍是一个视图，不是动作入口的前提；没被标候选的单仍可勾选后按 trace 起草。
      const diagSedentable = filtered.filter((item) => item && item.sessionId
        && !!(item.derived && item.derived.needSed))

      const view = s.paletteView === 'sediment' ? 'sediment' : 'diagnosis'
      const sedDoc = s.sediment && s.sediment.data && s.sediment.data.ok !== false ? s.sediment.data : null
      const sedPhase = s.sediment ? s.sediment.phase : 'idle'
      const sedDrafts = sedDoc && Array.isArray(sedDoc.drafts) ? sedDoc.drafts : []
      // 查合入的逐条进度（见 beginCheckRun）：行内状态与批次条 n/m 都读这一份。
      const checkRun = s.checkRun
      const sedCounts = sedDoc && sedDoc.counts ? sedDoc.counts : {}
      const sedTargetDoc = sedDoc && sedDoc.target ? sedDoc.target : null
      const sedTarget = sedTargetDoc && sedTargetDoc.target ? sedTargetDoc.target : sedTargetDoc
      const sedRemotes = sedTargetDoc && Array.isArray(sedTargetDoc.remotes)
        ? sedTargetDoc.remotes
        : (sedTarget && Array.isArray(sedTarget.remotes) ? sedTarget.remotes : [])
      const sedTargetLabel = sedTarget && sedTarget.remote
        ? [sedTarget.remote, sedTarget.base,
          sedTarget.platformName || (sedTargetDoc && sedTargetDoc.platformName) || sedTarget.platform].filter(Boolean).join(' · ')
        : ''
      const sedTargetHint = sedTargetLabel
        ? tr('sediment.pushTarget', { label: sedTargetLabel })
        : tr('sediment.noTarget')
      const sedQuery = String(searchText || '').trim().toLowerCase()
      const sedFiltered = sedDrafts.filter((draft) => {
        if (!sedQuery) return true
        const hay = [draft.title, draft.key, draft.caseId, draft.decision, draft.novelty, draft.stage]
          .filter(Boolean).join(' ').toLowerCase()
        return hay.indexOf(sedQuery) >= 0
      }).filter((draft) => {
        if (sedFilter === 'decision') return ['unassessed', 'need_decision'].indexOf(draft.state) >= 0
        if (sedFilter === 'pr') return draft.state === 'decided'
        if (sedFilter === 'check') return draft.state === 'pr_open' || draft.state === 'pr_merged'
        if (sedFilter === 'rerun') return draft.state === 'need_rerun'
        return true
      })
      const sedRank = { groom: 0, pr: 1, check: 2, other: 3 }
      const sedSorted = sedFiltered.slice().sort((a, b) => {
        const ga = Object.prototype.hasOwnProperty.call(sedRank, sedGroupOf(a)) ? sedRank[sedGroupOf(a)] : 9
        const gb = Object.prototype.hasOwnProperty.call(sedRank, sedGroupOf(b)) ? sedRank[sedGroupOf(b)] : 9
        if (ga !== gb) return ga - gb
        const aa = a.ageDays === null || a.ageDays === undefined ? -1 : Number(a.ageDays)
        const ab = b.ageDays === null || b.ageDays === undefined ? -1 : Number(b.ageDays)
        return ab - aa
      })
      const sedPick = sedSorted[Math.max(0, Math.min(sedSel, sedSorted.length - 1))] || null

