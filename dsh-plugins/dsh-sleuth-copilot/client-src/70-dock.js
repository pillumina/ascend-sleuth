    // ── 面 1：状态条 ───────────────────────────────────────────────────────
    // 安静的一行：状态点 + 可点的跟踪范围 + 人读案例标题 + 状态 + 进度 + 一个主操作。
    // 默认收起（偏好可改），第二行（元信息 / 在等什么 / 身份标签）按需展开。
    // 左端的范围标签同时是选择器：可以把这一栏固定到任意一单，而不是只跟「最近一单」。
    // 输入类元素：点进这里不收起状态条，否则收起让输入区上移，正在定位光标的点击会被带偏。
    function isEditableTarget(target) {
      if (!target) return false
      const tag = String(target.tagName || '').toUpperCase()
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
      return target.isContentEditable === true
    }

    // 浮层（菜单 / 选择器）的内联尺寸与方向：默认向上；上方放不下且下方更宽裕时向下。
    // 高度按可用空间收，避免被滚动容器裁掉或盖住状态条本身。
    function popoverPlacement(anchor, minHeight, maxHeight) {
      if (!anchor) return null
      const gap = 8
      const margin = 8
      const clipTop = Math.max(0, Number(anchor.clipTop) || 0)
      const spaceAbove = Math.max(0, anchor.top - clipTop - margin)
      const spaceBelow = Math.max(0, anchor.viewHeight - anchor.bottom - margin)
      const down = spaceAbove < minHeight && spaceBelow > spaceAbove
      const room = down ? spaceBelow : spaceAbove
      const height = Math.max(minHeight, Math.min(maxHeight, room))
      const style = { maxHeight: Math.round(height) }
      if (down) {
        style.top = 'calc(100% + ' + gap + 'px)'
        style.bottom = 'auto'
      } else {
        style.bottom = 'calc(100% + ' + gap + 'px)'
        style.top = 'auto'
      }
      return style
    }

    function makeDock() {
      return function Dock(props) {
        const s = useStore()
        useSessionSync(props)
        const [menuOpen, setMenuOpen] = React.useState(false)
        const [menuForm, setMenuForm] = React.useState(null)
        const [samplePop, setSamplePop] = React.useState(null)
        const [pickerOpen, setPickerOpen] = React.useState(false)
        const [idle, setIdle] = React.useState(false)
        const [flashStep, setFlashStep] = React.useState('')
        const idleTimer = React.useRef(null)
        const flashTimer = React.useRef(null)
        const stepRef = React.useRef({ id: '', step: 0 })
        const lastBump = React.useRef(0)
        const [query, setQuery] = React.useState('')
        const [hint, setHint] = React.useState('')
        const hintTimer = React.useRef(null)
        const inputRef = React.useRef(null)
        const rootRef = React.useRef(null)
        const handleRef = React.useRef(null)
        // 菜单/选择器刚被点击关闭的时刻：同一次手势不顺手收起状态条，过期自动失效
        const menuDismissedAtRef = React.useRef(0)
        // 这次手势是否起于状态条内部。必须在 mousedown（capture）时记：菜单项点击会把按钮
        // 从 DOM 里换掉，等 click 冒到 document 时 target 已 detached，contains(target) 为假，
        // 「点外部收起」就会把刚展开的表单一起收起——用户看到的是「点了没反应」。
        const gestureInsideRef = React.useRef(false)
        // 菜单/选择器按视口可用空间定位置：向上展开放不下时改向下并限高，避免被滚动容器
        // 裁掉、被应用顶栏盖住（被盖住的部分点不到）。
        const [anchor, setAnchor] = React.useState(null)
        // 键盘收起后把焦点放回收起态胶囊，别落回 body
        const restoreFocusRef = React.useRef(false)
        // 内层浮层（更多操作 / 选择器）关闭后把焦点还给触发它的按钮；展开时给第一个控件。
        const moreBtnRef = React.useRef(null)
        const scopeBtnRef = React.useRef(null)
        const menuWasOpenRef = React.useRef(false)
        const pickerWasOpenRef = React.useRef(false)
        const expandFocusRef = React.useRef(false)

        const flash = React.useCallback((text) => {
          setHint(text)
          announce(text)
          if (hintTimer.current) clearTimeout(hintTimer.current)
          hintTimer.current = setTimeout(() => setHint(''), 4600)
        }, [])

        React.useEffect(() => () => {
          if (hintTimer.current) clearTimeout(hintTimer.current)
        }, [])

        // 切会话时收起内层：旧菜单/表单纯属上一条单的状态，留着会在新单上重新弹出，
        // 提交时写到另一单。
        React.useEffect(() => {
          setMenuOpen(false)
          setMenuForm(null)
          setPickerOpen(false)
        }, [s.sessionId])

        // 收起态静置后淡出；鼠标移动、滚动、聚焦输入框时浮现。reduce-motion 下不淡出。
        const idleRef = React.useRef({ collapsed: false })
        idleRef.current.collapsed = s.prefs.dockCollapsed
        const bumpIdle = React.useCallback(() => {
          const now = Date.now()
          if (now - lastBump.current < 500) return
          lastBump.current = now
          setIdle(false)
          if (idleTimer.current) clearTimeout(idleTimer.current)
          idleTimer.current = setTimeout(() => {
            // 变淡只改 opacity，不属于「动效」；reduced-motion 只让 CSS 取消过渡
            // （变淡瞬间生效），不取消这件事本身。Windows 关闭「动画效果」时
            // Chromium 会报 prefers-reduced-motion: reduce，旧逻辑因此完全不淡出。
            if (idleRef.current.collapsed) setIdle(true)
          }, 2800)
        }, [])

        React.useEffect(() => {
          if (s.prefs.dockCollapsed) return undefined
          if (s.sediment.phase === 'idle') refreshSediment(false)
          return undefined
        }, [s.prefs.dockCollapsed, s.sediment.phase])

        React.useEffect(() => {
          if (!s.prefs.dockCollapsed) {
            setIdle(false)
            if (idleTimer.current) clearTimeout(idleTimer.current)
            return undefined
          }
          bumpIdle()
          const onMove = () => bumpIdle()
          const onScroll = () => bumpIdle()
          const onFocus = () => bumpIdle()
          document.addEventListener('pointermove', onMove, { passive: true })
          document.addEventListener('wheel', onScroll, { passive: true, capture: true })
          document.addEventListener('scroll', onScroll, { capture: true, passive: true })
          document.addEventListener('focusin', onFocus)
          return () => {
            document.removeEventListener('pointermove', onMove)
            document.removeEventListener('wheel', onScroll, { capture: true })
            document.removeEventListener('scroll', onScroll, { capture: true })
            document.removeEventListener('focusin', onFocus)
            if (idleTimer.current) clearTimeout(idleTimer.current)
          }
        }, [s.prefs.dockCollapsed, bumpIdle])

        React.useEffect(() => {
          ensureAnnouncementRegions()
        }, [])

        React.useEffect(() => () => {
          if (idleTimer.current) clearTimeout(idleTimer.current)
          if (flashTimer.current) clearTimeout(flashTimer.current)
          removeAnnouncementRegions()
        }, [])

        // 步骤前进时让状态点轻闪一次；只在同一单上比较，首屏不闪。
        React.useEffect(() => {
          const current = store.data && store.data.ok !== false ? store.data : null
          if (!current) return undefined
          const all = current.all || []
          const pinned = pinnedIdFor(store.sessionId)
          const picked = (pinned && all.find((row) => row.sessionId === pinned))
            || current.bound || (current.recent && current.recent[0]) || null
          if (!picked) return undefined
          const step = Number((picked.extra || {}).currentStep) || 0
          const previous = stepRef.current
          if (previous.id === picked.sessionId && previous.step > 0 && step > previous.step) {
            setFlashStep(previous.step + '→' + step)
            if (flashTimer.current) clearTimeout(flashTimer.current)
            flashTimer.current = setTimeout(() => setFlashStep(''), 1500)
          }
          stepRef.current = { id: picked.sessionId, step }
          return undefined
        }, [s.data, s.sessionId])

        // ⌘⇧D / Ctrl+Shift+D 打开诊断工作台；⌘⇧K / Ctrl+Shift+K 打开工作台并进入命令面板。
        // 命令面板那条为什么不带主键的 ⌘K：DSH 把 Primary+K 注册成「搜索会话」，宿主的分发器
        // 先跑并 preventDefault，下面的 defaultPrevented 守卫据此让路——留着主键等于点了没反应。
        React.useEffect(() => {
          const onKey = (event) => {
            // 宿主已经处理过的组合不再抢；状态条不该覆盖别的应用级快捷键。
            if (event.defaultPrevented) return
            const key = String(event.key || '').toLowerCase()
            const mod = event.metaKey || event.ctrlKey
            if (!mod) return
            if (key === 'k' && event.shiftKey) {
              // 工作台开着时这组键归工作台自己（切进命令面板），这里不重复处理。
              if (store.paletteOpen) return
              event.preventDefault()
              setMenuOpen(false)
              setPickerOpen(false)
              const current = store.data && store.data.ok !== false ? store.data : null
              if (!current) return
              const all = current.all || []
              const pinned = pinnedIdFor(store.sessionId)
              const picked = (pinned && all.find((row) => row.sessionId === pinned))
                || current.bound || (current.recent && current.recent[0]) || null
              commandRequested = true
              setPaletteOpen(true, picked ? picked.sessionId : '')
              return
            }
            if (key !== 'd' || !event.shiftKey) return
            event.preventDefault()
            const current = store.data && store.data.ok !== false ? store.data : null
            if (!current) return
            const all = current.all || []
            const pinned = pinnedIdFor(store.sessionId)
            const picked = (pinned && all.find((row) => row.sessionId === pinned))
              || current.bound || (current.recent && current.recent[0]) || null
            setPaletteOpen(true, picked ? picked.sessionId : '')
          }
          window.addEventListener('keydown', onKey)
          return () => window.removeEventListener('keydown', onKey)
        }, [])

        // 欠回报时把数量挂到页面标题前缀，切走再回来能看见；不弹窗。
        const pendingCount = s.data && s.data.counts ? Number(s.data.counts.pendingFeedback) || 0 : 0
        React.useEffect(() => {
          if (typeof document === 'undefined') return undefined
          const apply = () => {
            const current = String(document.title || '')
            const plain = current.replace(/^\[\d+\]\s*/, '')
            document.title = pendingCount > 0 ? '[' + pendingCount + '] ' + plain : plain
          }
          apply()
          let observer = null
          let selfMutated = false
          try {
            const node = typeof document.querySelector === 'function' ? document.querySelector('title') : null
            if (node && typeof MutationObserver !== 'undefined') {
              observer = new MutationObserver(() => {
                if (selfMutated) { selfMutated = false; return }
                selfMutated = true
                apply()
              })
              observer.observe(node, { childList: true, characterData: true, subtree: true })
            }
          } catch {
            observer = null
          }
          return () => {
            if (observer) observer.disconnect()
            // 只摘自己加的前缀，不写回捕获时的旧标题（期间可能已切过会话）。
            document.title = String(document.title || '').replace(/^\[\d+\]\s*/, '')
          }
        }, [pendingCount])

        React.useEffect(() => {
          if (!pickerOpen) return undefined
          const node = inputRef.current
          if (node && typeof node.focus === 'function') node.focus()
          return undefined
        }, [pickerOpen])

        React.useEffect(() => {
          if (!menuOpen && !pickerOpen) return undefined
          const onDown = (event) => {
            if (insideDock(event)) return
            // 先关菜单/选择器；同一次手势不顺手收起状态条（click 处理器看这个时刻）
            menuDismissedAtRef.current = Date.now()
            setMenuOpen(false)
            setPickerOpen(false)
          }
          document.addEventListener('mousedown', onDown)
          return () => document.removeEventListener('mousedown', onDown)
        }, [menuOpen, pickerOpen])

        // 菜单/选择器开合时量一次锚点，并在窗口尺寸、滚动变化时重算。
        // 量不到的宿主（没有布局的测试替身）保持 CSS 默认位置，不影响状态逻辑。
        React.useEffect(() => {
          if (!menuOpen && !pickerOpen) {
            setAnchor(null)
            return undefined
          }
          function measure() {
            const node = rootRef.current
            if (!node || typeof node.getBoundingClientRect !== 'function') return null
            let rect = null
            try { rect = node.getBoundingClientRect() } catch { rect = null }
            if (!rect) return null
            const view = typeof window !== 'undefined' ? window : {}
            const viewHeight = Number(view.innerHeight) || 0
            // 最近的可裁剪祖先（滚动容器 / overflow:hidden）上边界：浮层不能越过它，
            // 否则会被裁掉；被裁掉的部分既看不见也点不到。
            let clipTop = 0
            let parent = node.parentElement
            while (parent && parent !== document.body) {
              let style = null
              try {
                style = typeof view.getComputedStyle === 'function' ? view.getComputedStyle(parent) : null
              } catch { style = null }
              const overflowY = style ? String(style.overflowY || '') : ''
              if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'hidden') {
                let box = null
                try { box = parent.getBoundingClientRect() } catch { box = null }
                if (box && box.top > clipTop) clipTop = box.top
              }
              parent = parent.parentElement
            }
            return {
              top: Number(rect.top) || 0,
              bottom: Number(rect.bottom) || 0,
              clipTop,
              viewHeight,
            }
          }
          function update() {
            const next = measure()
            setAnchor((prev) => {
              if (prev === null && next === null) return prev
              if (prev && next
                && Math.abs(prev.top - next.top) < 1
                && Math.abs(prev.bottom - next.bottom) < 1
                && Math.abs(prev.clipTop - next.clipTop) < 1
                && Math.abs(prev.viewHeight - next.viewHeight) < 1) return prev
              return next
            })
          }
          update()
          let frame = 0
          const schedule = () => {
            if (frame) return
            const view = typeof window !== 'undefined' ? window : {}
            if (typeof view.requestAnimationFrame === 'function') {
              frame = view.requestAnimationFrame(() => { frame = 0; update() })
            } else {
              frame = setTimeout(() => { frame = 0; update() }, 32)
            }
          }
          const view = typeof window !== 'undefined' ? window : {}
          if (typeof view.addEventListener === 'function') view.addEventListener('resize', schedule)
          document.addEventListener('scroll', schedule, true)
          return () => {
            if (frame) {
              if (typeof view.cancelAnimationFrame === 'function') view.cancelAnimationFrame(frame)
              else clearTimeout(frame)
            }
            if (typeof view.removeEventListener === 'function') view.removeEventListener('resize', schedule)
            document.removeEventListener('scroll', schedule, true)
          }
        }, [menuOpen, pickerOpen])

        const collapsed = s.prefs.dockCollapsed
        const keepOpen = !!s.prefs.dockKeepOpen
        const data = s.data
        // 知识库落后提示：host 只在一轮检查有结果时带下来，字段缺失按「没有提示」处理。
        const kbNotice = data && data.ok !== false && data.kbNotice && typeof data.kbNotice === 'object'
          ? data.kbNotice
          : null
        // 受限档位下 fetch 被拒、退回只读探测：behind 为 null，界面不显示数字。
        const kbDegraded = !!kbNotice && kbNotice.behind === null
        const kbBehind = kbNotice ? Math.max(0, Number(kbNotice.behind) || 0) : 0
        const kbPanel = kbNotice ? Math.max(0, Number(kbNotice.panel) || 0) : 0
        // 只有面板代码的提交说「面板代码落后」；其余（含读不到改动面的旧状态）说知识库。
        const kbKind = kbNotice && kbNotice.kind === 'panel' ? 'panel' : 'knowledge'
        const kbTagKey = kbKind === 'panel' ? 'kb.panelCollapsed' : 'kb.collapsed'
        const kbWhen = kbNotice && !kbDegraded && kbNotice.checkedAt
          ? tr('kb.checked', { time: shortClock(String(kbNotice.checkedAt)) })
          : ''
        // 连败上屏：连续失败 3 次或权限拒绝时 host 才给 kbError；成功检查后随刷新消失。
        const kbError = data && data.ok !== false && data.kbError && typeof data.kbError === 'object'
          ? data.kbError
          : null

        function toggleCollapsed() {
          // 展开是新一轮交互：上一次「关菜单」的标记不该带到现在
          if (collapsed) menuDismissedAtRef.current = 0
          if (collapsed) expandFocusRef.current = true
          savePrefs({ dockCollapsed: !collapsed })
          setMenuOpen(false)
          setPickerOpen(false)
        }

        // 一个手势（mousedown → click）是否起于状态条内部。菜单项、选择器行点击会把自身
        // 从 DOM 里换掉，等 click 冒到 document 时 target 已 detached；只看 contains(target)
        // 会把这种点击误判成「点外部」并把状态条收起，刚展开的表单跟着一起消失。
        function insideDock(event) {
          const root = rootRef.current
          const target = event && event.target
          if (root && target && typeof root.contains === 'function' && root.contains(target)) return true
          const path = event && typeof event.composedPath === 'function' ? event.composedPath() : null
          return !!(path && root && path.indexOf(root) >= 0)
        }

        // 展开后点状态条外收起。点进可编辑区不收起：收起会让输入区上移，正在定位光标的点击会被带偏。
        // 开了「展开后常驻」就不自动收起，只有点「收起」或按 Esc 才收。
        // 状态条没渲染（取数中 / 无工作区）时不挂监听，否则点一下页面就把收起偏好写掉。
        const hidden = s.phase === 'idle' || s.phase === 'loading'
          || (data && data.ok === false && data.code === 'E_NO_ROOT')
        React.useEffect(() => {
          if (hidden || collapsed || keepOpen) return undefined
          const onClick = (event) => {
            // 本次手势起于状态条内部（含被点击后已卸载的菜单项）就不收起
            const fromInside = gestureInsideRef.current
            gestureInsideRef.current = false
            // 刚被点关闭的菜单或选择器：这一次手势只关内层，不收起状态条；标记只用一次
            const dismissedAt = menuDismissedAtRef.current
            if (dismissedAt && Date.now() - dismissedAt < 600) {
              menuDismissedAtRef.current = 0
              return
            }
            const target = event && event.target
            if (!target) return
            if (typeof Node !== 'undefined' && !(target instanceof Node)) return
            if (fromInside || insideDock(event)) return
            if (isEditableTarget(target)) return
            toggleCollapsed()
          }
          // 手势一开始就记下起点是否在状态条内，并清掉上一次的「关菜单」标记：
          // 右键与拖拽没有 click，标记不能留到下一次点击。
          const onDown = (event) => {
            menuDismissedAtRef.current = 0
            gestureInsideRef.current = insideDock(event)
          }
          // 收尾点击本身不能触发收起：展开那次 click 冒泡到 document 时，监听器可能刚落上
          const timer = setTimeout(() => document.addEventListener('click', onClick), 0)
          document.addEventListener('mousedown', onDown, true)
          return () => {
            clearTimeout(timer)
            gestureInsideRef.current = false
            document.removeEventListener('click', onClick)
            document.removeEventListener('mousedown', onDown, true)
          }
        }, [hidden, collapsed, keepOpen])

        React.useEffect(() => {
          if (!collapsed || !restoreFocusRef.current) return
          restoreFocusRef.current = false
          const node = handleRef.current
          if (node && typeof node.focus === 'function') node.focus()
        }, [collapsed])

        // 展开方向：胶囊被卸载后焦点会回 body，落到展开态的第一个控件（范围标签）。
        React.useEffect(() => {
          if (collapsed || !expandFocusRef.current) return
          expandFocusRef.current = false
          const node = scopeBtnRef.current
          if (node && typeof node.focus === 'function') { try { node.focus() } catch { /* 替身无焦点 API */ } }
        }, [collapsed])

        // 内层浮层关闭：把焦点还给触发按钮，用户的 Tab 起点不丢。
        React.useEffect(() => {
          if (menuWasOpenRef.current && !menuOpen) {
            const node = moreBtnRef.current
            if (node && typeof node.focus === 'function') { try { node.focus() } catch { /* 同上 */ } }
          }
          menuWasOpenRef.current = menuOpen
        }, [menuOpen])
        React.useEffect(() => {
          if (pickerWasOpenRef.current && !pickerOpen) {
            const node = scopeBtnRef.current
            if (node && typeof node.focus === 'function') { try { node.focus() } catch { /* 同上 */ } }
          }
          pickerWasOpenRef.current = pickerOpen
        }, [pickerOpen])

        // 焦点在状态条内时 Esc 收起；菜单或选择器开着就先关内层。
        function onRootKeyDown(event) {
          if (!event || event.key !== 'Escape') return
          const stop = typeof event.preventDefault === 'function' ? () => event.preventDefault() : () => {}
          if (menuOpen) {
            stop()
            setMenuOpen(false)
            setMenuForm(null)
            return
          }
          if (pickerOpen) {
            stop()
            setPickerOpen(false)
            return
          }
          if (collapsed) return
          stop()
          restoreFocusRef.current = true
          toggleCollapsed()
        }

        function fillDraft(text) {
          const inputActions = props && props.inputActions
          if (inputActions && typeof inputActions.setDraft === 'function') {
            try {
              inputActions.setDraft(text)
              store.sedimentForceNext = true
              flash(tr('hint.draft'))
              return
            } catch (error) {
              flash(tr('hint.failed', { message: String((error && error.message) || error) }))
              return
            }
          }
          copyToClipboard(text).then((ok) => flash(ok ? tr('hint.copiedFallback') : tr('hint.noInput')))
        }

        function copyAndFlash(text) {
          copyToClipboard(text).then((ok) => flash(ok ? tr('hint.copied') : tr('hint.copyFailed')))
        }

        if (s.phase === 'idle' || s.phase === 'loading') return null
        if (data && data.ok === false && data.code === 'E_NO_ROOT') return null

        const rootProps = {
          'data-version': PLUGIN_VERSION,
          role: 'region',
          'aria-label': tr('region'),
          title: tr('region') + ' v' + PLUGIN_VERSION,
        }

        function renderHandle(title, meta, pending) {
          return h('div', { className: 'scp-handle-wrap' },
            h('button', {
              ref: handleRef,
              type: 'button',
              className: 'scp-handle',
              'data-idle': idle ? 'true' : 'false',
              'aria-label': tr('action.expand') + '：' + title + (meta ? '，' + meta : '') + (pending ? '，' + tr('chip.feedback') : ''),
              title,
              onClick: toggleCollapsed,
            },
              h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
              h('span', { className: 'scp-handle-title' }, title),
              meta ? h('span', { className: 'scp-handle-meta' }, meta) : null,
              pending ? h('span', { className: 'scp-handle-pending' }, tr('chip.feedback')) : null,
              IconChevron({ open: false })))
        }

        // 展开态的两个控制：「展开后常驻」开关与带文字的收起按钮（窄容器只留箭头）。
        function renderKeepOpen() {
          return h('button', {
            type: 'button',
            className: 'scp-icon scp-pin',
            'data-on': keepOpen ? 'true' : 'false',
            'aria-pressed': keepOpen ? 'true' : 'false',
            'aria-label': tr('action.keepOpen'),
            title: keepOpen ? tr('action.keepOpenOff') : tr('action.keepOpen'),
            onClick: () => {
              savePrefs({ dockKeepOpen: !keepOpen })
              flash(keepOpen ? tr('hint.keepOff') : tr('hint.keepOn'))
            },
          }, IconPin({ on: keepOpen }))
        }

        function renderCollapse() {
          return h('button', {
            type: 'button',
            className: 'scp-collapse',
            'aria-label': tr('action.collapse'),
            title: tr('action.collapse'),
            onClick: toggleCollapsed,
          },
            h('span', { className: 'scp-collapse-text' }, tr('action.collapseShort')),
            IconChevron({ open: true }))
        }

        // 「去同步」：切到 Ascend Sleuth 整页，再尽力点开该页的「知识库」标签，最后挂复查。
        // 切页的后续动作在插件闭包里（见 openKbTab / scheduleKbRecheck）：这次点击会卸载状态条，
        // 动作不能绑在组件生命周期上。拿不到 layout 服务时只 flash 一句装面板的指引，不抛。
        function goSync() {
          let switched = false
          try {
            switched = selectPanelImpl('ascend-sleuth-console') === true
          } catch {
            switched = false
          }
          if (!switched) flash(tr('kb.missing'))
          openKbTab()
          scheduleKbRecheck(0)
        }

        // 「稍后」：写进本地状态文件成功后才收起提示行。
        // 写失败时保留行并说明原因，否则重开页面还会提示同一版，读者会以为上次点没生效。
        function dismissKbNotice() {
          if (!kbNotice) return
          const rev = String(kbNotice.rev || '')
          rpcCall('copilot-kb-dismiss', { rev }).then((value) => {
            // host 写不进状态文件时回 saved:false（这次只记在内存里），不能收起行。
            if (value && value.saved === false) {
              flash(tr('kb.laterFailed'))
              return
            }
            // 先作废在飞的 10 秒刷新响应，再清本地状态：旧响应会把刚收起的行又贴回来。
            store.seq += 1
            if (store.data) store.data.kbNotice = null
            emit()
            flash(tr('kb.laterDone'))
          }, () => {
            // RPC 抛错是连不上后台，和「落盘失败」不是一回事，分开说。
            flash(tr('kb.laterUnavailable'))
          })
        }

        function renderKbNotice() {
          if (!kbNotice) return null
          return h('div', { className: 'scp-kb-notice', role: 'group', 'aria-label': tr('kb.collapsed'), title: kbPanel > 0 ? tr('kb.panel') : undefined },
            h('span', { className: 'scp-kb-notice-dot', 'aria-hidden': 'true' }),
            h('span', { className: 'scp-kb-notice-main' },
              h('span', { className: 'scp-kb-notice-text' },
                kbDegraded ? tr('kb.degraded')
                  : tr(kbKind === 'panel' ? 'kb.panelBehind' : 'kb.behind', { n: kbBehind })
                    + (kbWhen ? ' ' + kbWhen : '')),
              kbPanel > 0 ? h('span', { className: 'scp-kb-notice-note' }, tr('kb.panel')) : null),
            h('span', { className: 'scp-spacer' }),
            h('button', {
              type: 'button',
              className: 'scp-btn scp-kb-go',
              onClick: goSync,
            }, tr('kb.go')),
            h('button', {
              type: 'button',
              className: 'scp-btn scp-btn--ghost scp-kb-later',
              onClick: dismissKbNotice,
            }, tr('kb.later')))
        }

        // 连败原因：取失败原文的第一行，超长截断；没有原文时按原因码给一句话。
        function kbErrorText(error) {
          const raw = String((error && error.message) || '').trim()
            .split(/\r?\n/)
            .map((item) => item.trim())
            .filter(Boolean)[0] || ''
          if (raw) return raw.length > 80 ? raw.slice(0, 79) + '…' : raw
          const reason = String((error && error.reason) || '')
          if (reason === 'permission-denied' || reason === 'E_PERM') return tr('kb.errorDenied')
          // 没有失败原文时按失败次数给一句（状态文件里可能是升级前的连败计数，不写死 3）。
          const failures = Number(error && error.failures)
          if (Number.isInteger(failures) && failures > 0) return tr('kb.errorFailedCount', { n: failures })
          return tr('kb.errorFailed')
        }

        // 「重试」：强制让 host 立刻再检查一次，再拉一次状态；成功后 kbError 随新数据清空。
        function retryKbCheck() {
          rpcCall('copilot-kb-recheck', { force: true })
            .then(() => refresh(true))
            .catch(() => {
              // 连不上后台时保留这一行，等下一轮定时检查。
            })
        }

        function renderKbError() {
          if (!kbError) return null
          const line = tr('kb.error', {
            time: formatTime(kbError.checkedAt) || tr('none'),
            reason: kbErrorText(kbError),
          })
          return h('div', { className: 'scp-kb-error', role: 'group', title: line },
            h('span', { className: 'scp-kb-error-dot', 'aria-hidden': 'true' }),
            h('span', { className: 'scp-kb-error-main' },
              h('span', { className: 'scp-kb-error-text' }, line)),
            h('span', { className: 'scp-spacer' }),
            h('button', {
              type: 'button',
              className: 'scp-btn scp-kb-go',
              onClick: goSync,
            }, tr('kb.go')),
            h('button', {
              type: 'button',
              className: 'scp-btn scp-btn--ghost scp-kb-retry',
              onClick: retryKbCheck,
            }, tr('action.retry')))
        }

        const failed = s.phase === 'error' || (data && data.ok === false)
        if (failed) {
          const message = s.phase === 'error' ? s.message : (data && data.message ? data.message : tr('title.error'))
          if (collapsed) {
            return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'error', 'data-tone': 'error' }),
              renderHandle(tr('title.error'), null, false))
          }
          return h('section', Object.assign({}, rootProps, { ref: rootRef, className: 'scp-root', 'data-mode': 'error', 'data-tone': 'error', onKeyDown: onRootKeyDown }),
            h('div', { className: 'scp-surface' },
              h('div', { className: 'scp-head' },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-badge' }, tr('title.error')),
                h('span', { className: 'scp-wait', title: message }, message),
                h('span', { className: 'scp-spacer' }),
                h('button', { type: 'button', className: 'scp-btn', onClick: () => refresh(true) }, tr('action.retry')),
                renderKeepOpen(),
                renderCollapse())))
        }

        const allRows = (data.all || [])
        const pinnedId = pinnedIdFor(s.sessionId)
        const pinnedRow = pinnedId ? allRows.find((row) => row.sessionId === pinnedId) : null
        const primary = pinnedRow || data.bound || (data.recent && data.recent[0]) || null

        if (!primary) {
          if (collapsed) {
            return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'empty', 'data-tone': 'idle' }),
              renderHandle(tr('empty.collapsed'), kbNotice ? tr(kbTagKey) : null, false))
          }
          return h('section', Object.assign({}, rootProps, { ref: rootRef, className: 'scp-root', 'data-mode': 'empty', 'data-tone': 'idle', onKeyDown: onRootKeyDown }),
            h('div', { className: 'scp-surface' },
              h('div', { className: 'scp-head' },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-case', style: { cursor: 'default', fontWeight: 500 } }, tr('empty.collapsed')),
                h('span', { className: 'scp-spacer' }),
                h('button', {
                  type: 'button',
                  className: 'scp-btn scp-btn--quiet',
                  onClick: () => fillDraft('/diagnose '),
                }, tr('action.start')),
                renderKeepOpen(),
                renderCollapse()),
              renderKbNotice(),
              renderKbError(),
              collapsed ? null : h('div', { className: 'scp-foot' },
                h('span', { className: 'scp-empty-note' }, tr('empty.body')))),
            // 这个分支也要挂 hint：没有诊断单时点「去同步 / 稍后」的结果得看得见。
            hint ? h('div', { className: 'scp-hint' }, hint) : null)
        }

        const bound = !!data.bound && primary.sessionId === data.bound.sessionId
        const pinned = !!pinnedRow
        const tone = toneOf(primary)
        const status = statusMeta(data.vocab, primary.status)
        const extra = primary.extra || {}
        const derived = primary.derived || {}
        const waiting = derived.waitingFor || extra.evidenceMissing || ''
        const action = primaryFor(primary, bound)
        const chips = identityChips(primary, (sample) => setSamplePop(sample)).filter((chip) => chip.key !== 'excluded').slice(0, 3)
        if (s.stale) chips.push({ key: 'stale', tone: 'warn', text: tr('chip.stale') })
        const metaBits = []
        if (status && status.label) metaBits.push(status.label)
        if (extra.platform) metaBits.push(extra.platform)
        if (extra.framework) metaBits.push(extra.framework)
        if (extra.category) metaBits.push(CATEGORY_LABEL[extra.category] || extra.category)

        const sedimentDrafts = (s.sediment.data && s.sediment.data.drafts) || []
        const sedDraft = sedimentDrafts.find((item) => item && item.source && item.source.sessionId === primary.sessionId) || null
        const traceSed = primary.sedimented && primary.sedimented.state ? primary.sedimented.state : 'none'
        const sedimentRow = (!collapsed && (sedDraft || traceSed === 'submitted'))
          ? h('div', { className: 'scp-dock-sed', role: 'group', 'aria-label': tr('palette.sedimentTitle') },
            h('span', {
              className: 'scp-dock-sed-dot',
              'data-tone': sedDraft ? (sedDraft.stageTone || 'gray') : 'warn',
              'aria-hidden': 'true',
            }),
            h('span', { className: 'scp-dock-sed-label' }, tr('palette.view.sediment')),
            h('span', { className: 'scp-dock-sed-stage' }, sedDraft ? sedDraft.stage : tr('sediment.dock.missingDraft')),
            sedDraft && sedDraft.ageDays !== null && sedDraft.ageDays !== undefined
              ? h('span', { className: 'scp-dock-sed-days' }, tr('sediment.age', { n: sedDraft.ageDays }))
              : null,
            sedDraft && sedDraft.next && sedDraft.next.label
              ? h('span', { className: 'scp-dock-sed-next' }, tr('sediment.batch.next') + '：' + sedDraft.next.label)
              : null,
            h('span', { className: 'scp-spacer' }),
            h('button', {
              type: 'button',
              className: 'scp-dock-sed-open',
              onClick: () => openSediment(sedDraft ? sedDraft.key : ''),
            }, tr('sediment.open') + ' ›'))
          : null

        function runPrimary() {
          if (action.mode === 'draft') fillDraft(action.text)
          else if (action.mode === 'copy') copyAndFlash(action.text)
          else {
            setMenuForm(action.mode === 'form' ? (action.form || null) : null)
            setMenuOpen(true)
            setPickerOpen(false)
          }
        }

        function openOverview() {
          setPaletteOpen(true, primary.sessionId, 'diagnosis')
        }

        const pickerRows = allRows
          .filter((row) => {
            if (!query.trim()) return true
            const needle = query.trim().toLowerCase()
            return caseTitle(row).toLowerCase().includes(needle) || row.sessionId.toLowerCase().includes(needle)
          })
          .slice(0, 12)

        const menuStyle = menuOpen ? popoverPlacement(anchor, 200, 540) : null
        const pickerStyle = pickerOpen ? popoverPlacement(anchor, 160, 380) : null
        const popoverDown = !!((menuStyle && menuStyle.top) || (pickerStyle && pickerStyle.top))

        const scopeLabel = pinned ? tr('scope.pinned')
          : (bound ? ((data.bound && data.bound.boundBy === 'resume') ? tr('scope.boundResume') : tr('scope.bound')) : tr('scope.recent'))

        const picker = pickerOpen ? h('div', {
          className: 'scp-picker',
          role: 'dialog',
          'aria-label': tr('picker.title'),
          style: pickerStyle || undefined,
        },
          h('div', { className: 'scp-picker-head' },
            h('div', { className: 'scp-picker-title' }, tr('picker.title')),
            h('input', {
              ref: inputRef,
              className: 'scp-picker-search',
              type: 'text',
              value: query,
              'aria-label': tr('picker.search'),
              placeholder: tr('picker.search'),
              onChange: (event) => setQuery(event.target.value),
            })),
          h('div', { className: 'scp-picker-list' },
            pickerRows.length === 0
              ? h('div', { className: 'scp-picker-empty' }, tr('picker.empty'))
              : pickerRows.map((row) => {
                const active = row.sessionId === primary.sessionId
                return h('button', {
                  key: row.sessionId,
                  type: 'button',
                  className: 'scp-picker-row',
                  'data-on': active ? 'true' : 'false',
                  'aria-current': active ? 'true' : 'false',
                  onClick: () => {
                    setPin(s.sessionId, row.sessionId)
                    setPickerOpen(false)
                    flash(tr('hint.pinned'))
                  },
                },
                  h('span', {
                    className: 'scp-ring',
                    'aria-hidden': 'true',
                    style: { background: TONE_VAR[toneOf(row)] || TONE_VAR.idle },
                  }),
                  active ? h('span', { className: 'scp-picker-current' }, tr('picker.current')) : null,
                  h('span', { className: 'scp-picker-main' },
                    h('span', { className: 'scp-picker-name' }, caseTitle(row)),
                    h('span', { className: 'scp-picker-meta' },
                      statusMeta(data.vocab, row.status).label,
                      ' · ',
                      stepsShort(row.extra),
                      ' · ',
                      formatTime(row.updatedAt) || tr('none'))))
              })),
          h('div', { className: 'scp-picker-foot' },
            pinned ? null : h('span', { className: 'scp-picker-foot-note' }, tr('picker.current') + '：' + scopeLabel),
            pinned ? h('button', {
              type: 'button',
              className: 'scp-btn scp-btn--ghost',
              onClick: () => {
                setPin(s.sessionId, '')
                setPickerOpen(false)
                flash(tr('hint.unpinned'))
              },
            }, tr('picker.followOff')) : h('span', { className: 'scp-spacer' }),
            h('span', { className: 'scp-spacer' }),
            h('button', { type: 'button', className: 'scp-btn', onClick: () => { setPickerOpen(false); openOverview() } }, tr('picker.open')))) : null

        const menu = menuOpen ? h('div', {
          className: 'scp-menu',
          // 表单态里只有 form / 输入 / 普通按钮；继续用 menu 角色会让读屏按菜单模式导航。
          role: menuForm ? 'dialog' : 'menu',
          'aria-label': tr('menu.title'),
          style: menuStyle || undefined,
        },
          h(WritePanel, {
            row: primary,
            data,
            autoForm: menuForm,
            onClose: () => { setMenuOpen(false); setMenuForm(null) },
            onDone: () => { setMenuOpen(false); setMenuForm(null); refresh(true) },
            onFlash: flash,
            onDraft: fillDraft,
          })) : null


        if (collapsed) {
          return h('section', Object.assign({}, rootProps, {
            ref: rootRef,
            className: 'scp-root',
            'data-mode': pinned ? 'pinned' : (bound ? 'bound' : 'recent'),
            'data-tone': tone,
            'data-live': derived.open ? 'true' : 'false',
            'data-pending': isPending(primary) ? 'true' : 'false',
            'data-flash': flashStep ? 'true' : 'false',
          }), renderHandle(
            caseTitle(primary),
            (flashStep || stepsShort(extra)) + (s.stale ? ' · ' + tr('chip.stale') : '')
              + (kbNotice ? ' · ' + tr(kbTagKey) : ''),
            isPending(primary)))
        }

        return h('section', Object.assign({}, rootProps, {
          ref: rootRef,
          className: 'scp-root',
          'data-mode': pinned ? 'pinned' : (bound ? 'bound' : 'recent'),
          'data-tone': tone,
          'data-live': derived.open ? 'true' : 'false',
          'data-pending': isPending(primary) ? 'true' : 'false',
          'data-flash': flashStep ? 'true' : 'false',
          'data-popover-down': popoverDown ? 'true' : 'false',
          onKeyDown: onRootKeyDown,
        }),
          picker,
          menu,
          h('div', { className: 'scp-surface' },
            h('div', { className: 'scp-head' },
              h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
              h('button', {
                type: 'button',
                className: 'scp-scope',
                ref: scopeBtnRef,
                'aria-label': tr('picker.title') + '：' + scopeLabel,
                title: tr('picker.title'),
                'aria-expanded': pickerOpen ? 'true' : 'false',
                onClick: () => { setPickerOpen((value) => !value); setMenuOpen(false) },
              }, scopeLabel, h('svg', { width: 8, height: 8, viewBox: '0 0 8 8', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.2, strokeLinecap: 'round' },
                h('path', { d: 'M1.6 3 4 5.4 6.4 3' }))),
              h('button', {
                type: 'button',
                className: 'scp-case',
                title: primary.summary || primary.sessionId,
                'aria-label': tr('action.ledger') + '：' + caseTitle(primary),
                onClick: openOverview,
              }, caseTitle(primary)),
              collapsed ? h('span', { className: 'scp-step' }, flashStep ? '第 ' + flashStep + ' 步' : stepsShort(extra)) : null,
              h('span', { className: 'scp-spacer' }),
              h('button', { type: 'button', className: 'scp-btn scp-btn--quiet', onClick: runPrimary }, action.label),
              collapsed ? null : h('button', {
                type: 'button', className: 'scp-icon', title: tr('action.more'), 'aria-label': tr('action.more'),
                ref: moreBtnRef,
                'aria-haspopup': menuForm ? 'dialog' : 'menu',
                'aria-expanded': menuOpen ? 'true' : 'false',
                onClick: () => { setMenuForm(null); setMenuOpen((value) => !value); setPickerOpen(false) },
              }, IconMore()),
              renderKeepOpen(),
              renderCollapse()),
            renderKbNotice(),
            renderKbError(),
            collapsed ? null : h('div', { className: 'scp-foot' },
              StepRail({ extra }),
              metaBits.length ? h('span', { className: 'scp-meta', title: metaBits.join(' · ') }, metaBits.join(' · ')) : null,
              h('span', { className: 'scp-wait', title: waiting }, waiting
                ? [h('span', { key: 'tag', className: 'scp-wait-tag' }, tr('waiting') + '：'), h('b', { key: 'text' }, waiting)]
                : h('span', { className: 'scp-wait-tag' }, tr('label.updated') + ' ' + (formatTime(primary.updatedAt) || tr('none')))),
              chips.length ? h('span', { className: 'scp-chips' }, chips.map((chip) => h('span', {
                key: chip.key, className: 'scp-chip', 'data-tone': chip.tone,
                title: chip.title || undefined,
                onClick: chip.onSelect,
                style: chip.onSelect ? { cursor: 'pointer' } : undefined,
              }, chip.text))) : null),
            sedimentRow),
          samplePop ? h('div', {
            className: 'scp-menu scp-sample-pop', role: 'dialog',
            'aria-label': tr('sample.pop.title'), style: { width: '360px' },
          },
            h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 6px 8px' } },
              h('b', null, tr('sample.pop.title')), h('span', { className: 'scp-spacer' }),
              h('button', {
                type: 'button', className: 'scp-btn scp-btn--quiet',
                onClick: () => setSamplePop(null),
              }, tr('sample.pop.close'))),
            h('div', { className: 'scp-kv' }, tr('sample.pop.state') + '：' + tr('chip.sample.' + samplePop.state)),
            samplePop.id ? h('div', { className: 'scp-kv' }, 'ID：' + samplePop.id) : null,
            samplePop.reasons && samplePop.reasons.length
              ? h('div', { className: 'scp-kv' }, tr('sample.pop.reasons') + '：' + samplePop.reasons.join('、')) : null,
            samplePop.duplicates && samplePop.duplicates.length
              ? h('div', { className: 'scp-kv' }, tr('sample.pop.duplicates') + '：' + samplePop.duplicates.join('、')) : null,
            h('div', { className: 'scp-upstream-row' },
              h('button', {
                type: 'button', className: 'scp-check-action',
                onClick: () => copyToClipboard('python3 scripts/evolve.py sample status --id ' + samplePop.id),
              }, tr('sample.pop.copy')))) : null,
          hint ? h('div', { className: 'scp-hint' }, hint) : null)
      }
    }

