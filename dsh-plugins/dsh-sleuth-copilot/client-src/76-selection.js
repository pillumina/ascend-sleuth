      // ── 选择集 ────────────────────────────────────────────────────────────
      // 选择集只认 id；刷新、重排、切筛选都不改它，只按 id 重新对应行。
      // 对不上行的 id 单独计数（「已不在队列」），不从选择集里静默删掉。
      const selIds = sel[view] || []
      const selSet = new Set(selIds)
      const idOfRow = (item) => (view === 'diagnosis'
        ? String((item && item.sessionId) || '')
        : String((item && item.key) || ''))
      const allRowsOfView = view === 'diagnosis' ? rows : sedDrafts
      const rowById = new Map()
      allRowsOfView.forEach((item) => {
        const id = idOfRow(item)
        if (id) rowById.set(id, item)
      })
      const selRows = selIds.map((id) => rowById.get(id)).filter(Boolean)
      const visibleBase = view === 'diagnosis' ? filtered : sedSorted
      const visibleRows = onlySel[view]
        ? visibleBase.filter((item) => selSet.has(idOfRow(item)))
        : visibleBase
      const selVisibleRows = visibleBase.filter((item) => selSet.has(idOfRow(item)))
      const invalidSel = selIds.filter((id) => !rowById.has(id))
      const outsideSel = selRows.length - selVisibleRows.length
      const selectedCount = selIds.length
      const selectedValid = selRows.length
      const onlySelOn = !!onlySel[view]
      const selectingOn = !!selecting[view] || selectedCount > 0
      const setSelectingFor = (value) => setSelecting((current) => (
        current[view] === value ? current : Object.assign({}, current, { [view]: value })
      ))
      // 当前可见列表里被选中的条数 / 全部条数：全选复选框的勾、半选与全选比较都用这一对。
      const visibleSelected = visibleRows.filter((item) => selSet.has(idOfRow(item))).length

      // 快照记下筛选与搜索词：撤销选择时一起回去，否则恢复出来的选中项在屏上看不见。
      function selSnapshot() {
        return { view, ids: selIds.slice(), filter, search: searchText, sedFilter }
      }
      function commitSel(next) {
        setSelHist((hist) => hist.concat([selSnapshot()]).slice(-5))
        setSel((current) => Object.assign({}, current, { [view]: next }))
      }
      function toggleRowSelection(item, index, mode) {
        const id = idOfRow(item)
        if (!id) return
        setSelectingFor(true)
        if (mode === 'range') {
          const anchor = selAnchor[view]
          const from = anchor >= 0 && anchor < visibleRows.length ? anchor : index
          const lo = Math.min(from, index)
          const hi = Math.max(from, index)
          const rangeIds = visibleRows.slice(lo, hi + 1).map(idOfRow).filter(Boolean)
          const anchorId = visibleRows[from] ? idOfRow(visibleRows[from]) : ''
          const remove = anchorId ? selSet.has(anchorId) : false
          const next = remove
            ? selIds.filter((value) => rangeIds.indexOf(value) < 0)
            : Array.from(new Set(selIds.concat(rangeIds)))
          commitSel(next)
          setSelAnchor((current) => Object.assign({}, current, { [view]: index }))
          return
        }
        const next = selSet.has(id)
          ? selIds.filter((value) => value !== id)
          : selIds.concat([id])
        commitSel(next)
        setSelAnchor((current) => Object.assign({}, current, { [view]: index }))
      }
      function selectAllVisible() {
        const ids = visibleBase.map(idOfRow).filter(Boolean)
        const allOn = ids.length > 0 && ids.every((id) => selSet.has(id))
        setSelectingFor(true)
        commitSel(allOn ? [] : ids)
        if (allOn && onlySel[view]) setOnlySel((current) => Object.assign({}, current, { [view]: false }))
      }
      // 清空选择同时退出选择态：行前复选框回到悬停才露的默认形态。
      function clearSelection() {
        if (selIds.length) commitSel([])
        setOnlySel((current) => Object.assign({}, current, { [view]: false }))
        setSelectingFor(false)
      }
      function enterSelection() {
        setSelectingFor(true)
      }
      // 整批条上的勾选只管这条批次的动作对象（如可沉淀的 n 单），不是「当前筛选全部行」。
      function toggleBatchSelection(list) {
        const ids = (list || []).map(idOfRow).filter(Boolean)
        if (!ids.length) return
        const allOn = ids.every((id) => selSet.has(id))
        setSelectingFor(true)
        commitSel(allOn
          ? selIds.filter((id) => ids.indexOf(id) < 0)
          : Array.from(new Set(selIds.concat(ids))))
      }
      function exitSelection() {
        clearSelection()
      }
      function removeInvalidSelection() {
        if (!invalidSel.length) return
        commitSel(selIds.filter((id) => rowById.has(id)))
      }
      // 撤销一步选择：恢复选择集与当时的筛选 / 搜索词。最多 5 步，取完就停。
      function undoSel() {
        if (!selHist.length) return
        const last = selHist[selHist.length - 1]
        setSelHist((hist) => hist.slice(0, -1))
        setSel((current) => Object.assign({}, current, { [last.view]: last.ids }))
        if (last.ids.length) {
          setSelecting((current) => Object.assign({}, current, { [last.view]: true }))
        }
        if (last.view === view) {
          setSearchText(last.search || '')
          if (view === 'sediment') setSedFilter(last.sedFilter || 'all')
          else savePrefs({ paletteFilter: FILTER_KEYS.indexOf(last.filter) >= 0 ? last.filter : 'all' })
        }
        flash(tr('sel.count', { n: last.ids.length }))
      }

      // 同一 PR 常覆盖多份草稿（一批决定提一个 PR）。查合入按 PR 合并查询后，
      // 列表行与详情要能看出「这几行是同一个 PR」，否则读者会以为每行各查一次。
      // 键与 `scripts/pr_status.py` 的 `_check_group_key` 同一套归一：repo 转小写、
      // number 转字符串、url 去尾斜杠；脚本按该键并组查一次，界面按该键计份数。
      const sedPrKey = (draft) => {
        const pr = draft && draft.pr
        if (!pr) return ''
        const repo = String(pr.repo || '').trim().toLowerCase()
        const number = pr.number === null || pr.number === undefined ? '' : String(pr.number).trim()
        const url = String(pr.url || '').trim().replace(/\/+$/, '')
        if (url) return 'url|' + url + '|' + repo + '|' + number
        const platform = String(pr.platform || '').trim()
        return 'no-url|' + platform + '|' + repo + '|' + number
      }
      const sedPrCounts = (() => {
        const counts = {}
        sedDrafts.forEach((draft) => {
          const key = sedPrKey(draft)
          if (key) counts[key] = (counts[key] || 0) + 1
        })
        return counts
      })()

      const flash = React.useCallback((text) => {
        setToast(text)
        announce(text)
        if (toastTimer.current) clearTimeout(toastTimer.current)
        toastTimer.current = setTimeout(() => setToast(''), 4600)
      }, [])

      React.useEffect(() => () => {
        if (toastTimer.current) clearTimeout(toastTimer.current)
      }, [])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        if (!data) refresh(true)
      }, [s.paletteOpen, data])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        // 诊断视图也要读一次：右列的「沉淀进度」需要当前单对应的草稿。
        // refreshSediment 自己按 60 秒去重；这里只避免在 loading/refreshing 时重入。
        // 失败后不自动重试：否则 error → loading → error 会无限起子进程，等读者点「刷新」。
        if (sedPhase !== 'loading' && sedPhase !== 'refreshing' && sedPhase !== 'error') refreshSediment(false)
      }, [s.paletteOpen, sedPhase])

      React.useEffect(() => {
        setMenuOpen(false)
        setMenuForm(null)
        setCmdOpen(false)
        setPromptKind('')
        setPromptFallback(null)
        setManualOpen(false)
        // 换会话等于换一批单：选择集与回执都不跟着走。
        setSel({ diagnosis: [], sediment: [] })
        setSelHist([])
        setOnlySel({ diagnosis: false, sediment: false })
        setSelecting({ diagnosis: false, sediment: false })
        setReceipt(null)
        setReceiptAsk(false)
        setBatchMenu(false)
        setScopedPrompt(null)
      }, [s.sessionId])

      React.useEffect(() => {
        setSedSel(0)
        setPromptKind('')
        setPromptFallback(null)
        setPromptDetailsOpen(false)
        setTargetOpen(false)
        setManualOpen(false)
      }, [view, sedFilter])

      React.useEffect(() => {
        setSearchText('')
        setSedSel(0)
        setSelHist([])
        setBatchMenu(false)
        setScopedPrompt(null)
      }, [view])

      // 连选锚点记的是可见列表的下标；筛选或搜索变了，旧下标指到另一行，先清掉。
      React.useEffect(() => {
        setSelAnchor((current) => Object.assign({}, current, { [view]: -1 }))
      }, [view, filter, searchText, sedFilter])

      React.useEffect(() => {
        if (view !== 'sediment') return
        if (sedSel > visibleRows.length - 1) setSedSel(visibleRows.length > 0 ? visibleRows.length - 1 : 0)
      }, [view, visibleRows.length, sedSel])

      React.useEffect(() => {
        if (!s.paletteOpen || view !== 'sediment') return
        const key = s.sedimentSelectKey
        if (!key) return
        const index = visibleRows.findIndex((draft) => draft.key === key)
        if (index < 0 && sedFilter !== 'all') {
          setSedFilter('all')
          return
        }
        if (index >= 0 && index !== sedSel) setSedSel(index)
      }, [s.paletteOpen, s.sedimentSelectKey, view, visibleRows.length, sedFilter])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        setMenuOpen(false)
        const position = visibleRows.findIndex((row) => row.sessionId === s.paletteSelect)
        selectIndex(position >= 0 ? position : 0)
      }, [s.paletteOpen, s.paletteSelect, filter])

      // 重排后按 sessionId 找回同一条；行不在了才退回边界。
      React.useEffect(() => {
        const id = selectedIdRef.current
        if (id) {
          const index = visibleRows.findIndex((row) => row.sessionId === id)
          if (index >= 0) {
            if (index !== selected) setSelected(index)
            return
          }
        }
        if (selected > visibleRows.length - 1) setSelected(visibleRows.length > 0 ? visibleRows.length - 1 : 0)
      }, [visibleRows, selected])

      // 键盘选中变化时把行滚进可视区：列表比一屏长，选中项在屏外时回车执行的是看不见的行。
      React.useEffect(() => {
        if (!s.paletteOpen) return
        const host = listRef.current
        if (!host || typeof host.querySelector !== 'function') return
        const node = host.querySelector('.scp-pal-row[data-on="true"]')
        if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'nearest' })
      }, [selected, s.paletteOpen])

      React.useEffect(() => {
        reportToken.current += 1
        timelineToken.current += 1
        setReportState({ open: false, loading: false, text: '', error: '' })
        setTimelineState({ open: false, loading: false, items: [], error: '' })
        setUndoBusy(false)
      }, [selected, filter, searchText, s.paletteOpen])

      React.useEffect(() => {
        if (s.paletteOpen) return
        commandRequested = false
        setCmdOpen(false)
        setCmdQuery('')
        setCmdIndex(0)
        setSearchText('')
        setMenuOpen(false)
        setPromptKind('')
        setPromptFallback(null)
        setBatchSed(null)
        setPromptDetailsOpen(false)
        setTargetOpen(false)
        setTargetResume('')
        setManualOpen(false)
        setCheckBusy('')
        setSel({ diagnosis: [], sediment: [] })
        setSelHist([])
        setOnlySel({ diagnosis: false, sediment: false })
        setSelecting({ diagnosis: false, sediment: false })
        // 回执不随面板关闭清掉：填完指令面板会自己收起，读者再打开时要能看到刚才那批并撤回。
        setReceiptAsk(false)
        setBatchMenu(false)
        setScopedPrompt(null)
      }, [s.paletteOpen])

      React.useEffect(() => {
        if (!promptKind) return
        const node = promptRef.current
        if (node && typeof node.focus === 'function') node.focus()
      }, [promptKind])

      React.useEffect(() => {
        if (!targetOpen) return
        const node = targetRef.current
        if (node && typeof node.focus === 'function') node.focus()
      }, [targetOpen])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        if (commandRequested) {
          commandRequested = false
          setCmdOpen(true)
          setCmdQuery('')
          setCmdIndex(0)
        }
      }, [s.paletteOpen])

      React.useEffect(() => {
        if (cmdOpen) {
          const node = cmdInputRef.current
          if (node && typeof node.focus === 'function') node.focus()
        }
      }, [cmdOpen])

      // 关闭浮层后把焦点还给打开它的按钮，不要落回 body。
      React.useEffect(() => {
        if (!s.paletteOpen) return undefined
        const previous = typeof document !== 'undefined' ? document.activeElement : null
        return () => {
          if (previous && previous.isConnected && typeof previous.focus === 'function') previous.focus()
        }
      }, [s.paletteOpen])

      // 内层浮层（指令 / 推送目标 / 手动改状态）关闭后把焦点还给打开它的按钮。
      const anyModalOpen = !!promptKind || targetOpen || manualOpen
      React.useEffect(() => {
        if (anyModalOpen) {
          modalReturnRef.current = typeof document !== 'undefined' ? document.activeElement : null
          return
        }
        const node = modalReturnRef.current
        modalReturnRef.current = null
        if (node && node.isConnected && typeof node.focus === 'function') { try { node.focus() } catch { /* 同上 */ } }
      }, [anyModalOpen])

      // 「更多操作」关闭后焦点回到触发按钮（打开时焦点已移进浮层）。
      React.useEffect(() => {
        if (menuWasOpenRef.current && !menuOpen) {
          const node = moreBtnRef.current
          if (node && node.isConnected && typeof node.focus === 'function') { try { node.focus() } catch { /* 同上 */ } }
        }
        menuWasOpenRef.current = menuOpen
      }, [menuOpen])

      React.useEffect(() => {
        if (!s.paletteOpen) return undefined
        const node = panelRef.current
        if (node && typeof node.focus === 'function') node.focus()
        const onKey = (event) => {
          const target = event.target
          const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')
          // Tab 在浮层内环绕：aria-modal=true 时焦点不该跑到遮罩下面。
          if (event.key === 'Tab') {
            // 最上层弹层里环绕：指令 / 目标 / 手动 / 命令面板盖在列表上时，Tab 不能落到背景。
            const root = promptRef.current || targetRef.current || manualRef.current || cmdRef.current || panelRef.current
            if (root && typeof root.querySelectorAll === 'function') {
              const focusables = Array.from(root.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'))
                .filter((item) => item && item.offsetParent !== null)
              if (focusables.length) {
                event.preventDefault()
                const current = focusables.indexOf(document.activeElement)
                const next = event.shiftKey
                  ? (current <= 0 ? focusables.length - 1 : current - 1)
                  : (current === focusables.length - 1 ? 0 : current + 1)
                const node = focusables[next]
                if (node && typeof node.focus === 'function') node.focus()
                return
              }
            }
          }
          if ((event.metaKey || event.ctrlKey) && event.shiftKey && String(event.key || '').toLowerCase() === 'k') {
            event.preventDefault()
            if (view === 'sediment') return
            // 指令 / 推送目标 / 手动改状态的弹层盖在命令面板之上：这时开面板只会开在遮罩下面。
            if (promptKind || targetOpen || manualOpen) return
            setMenuOpen(false)
            setMenuForm(null)
            setCmdOpen(true)
            setCmdQuery('')
            setCmdIndex(0)
            return
          }
          if (cmdOpen) {
            const items = commandsRef.current || []
            if (event.key === 'Escape') {
              event.preventDefault()
              setCmdOpen(false)
              return
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault()
              if (!items.length) return
              setCmdIndex((current) => {
                const next = event.key === 'ArrowDown' ? current + 1 : current - 1
                return Math.max(0, Math.min(next, items.length - 1))
              })
              return
            }
            if (event.key === 'Enter') {
              event.preventDefault()
              const item = items[cmdIndex]
              if (item && typeof item.run === 'function') {
                setCmdOpen(false)
                item.run()
              }
            }
            return
          }
          if (view === 'sediment') return
          // 批量沉淀弹层开着时，键盘只服务弹层：Esc 关弹层，Enter 不能穿透到背后的列表主操作。
          if (promptKind) {
            if (event.key === 'Escape') {
              event.preventDefault()
              closePrompt()
            }
            return
          }
          // 多选键：空格勾选焦点行，Cmd/Ctrl+A 全选当前筛选，Cmd/Ctrl+Z 撤销一步选择。
          const metaKey = event.metaKey || event.ctrlKey
          if (metaKey && !typing && (event.key === 'z' || event.key === 'Z')) {
            event.preventDefault()
            undoSel()
            return
          }
          if (metaKey && !typing && (event.key === 'a' || event.key === 'A')) {
            event.preventDefault()
            selectAllVisible()
            return
          }
          if (event.key === ' ' && !typing && !menuOpen) {
            const spaceTarget = event.target
            const onRow = spaceTarget && spaceTarget.tagName === 'BUTTON'
              && typeof spaceTarget.className === 'string'
              && /(^|\s)scp-(pal|sed)-row(\s|$)/.test(spaceTarget.className)
            if (!(spaceTarget && spaceTarget.tagName === 'BUTTON') || onRow) {
              const pick = visibleRows[selected]
              if (pick) {
                event.preventDefault()
                toggleRowSelection(pick, selected, event.shiftKey ? 'range' : 'toggle')
              }
              return
            }
          }
          if (event.key === '/' && !typing && !menuOpen) {
            event.preventDefault()
            if (searchRef.current && typeof searchRef.current.focus === 'function') searchRef.current.focus()
            return
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            if (batchMenu) { setBatchMenu(false); return }
            if (menuOpen) { setMenuOpen(false); return }
            if (selectedCount) { clearSelection(); return }
            if (selectingOn) { exitSelection(); return }
            setPaletteOpen(false)
            return
          }
          if (typing || menuOpen) return
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (!visibleRows.length) return
            event.preventDefault()
            const next = event.key === 'ArrowDown' ? selected + 1 : selected - 1
            selectIndex(Math.max(0, Math.min(next, visibleRows.length - 1)))
            return
          }
          if (event.key === 'Enter') {
            const row = visibleRows[selected]
            if (!row) return
            // 焦点只在普通按钮/输入框上时不抢回车；行按钮与列表容器上按回车都执行主操作。
            const target = event.target
            const onRow = target && typeof target.className === 'string'
              && target.className.split(/\s+/).indexOf('scp-pal-row') >= 0
            if (target && target.tagName === 'BUTTON' && !onRow) return
            event.preventDefault()
            runPrimary(row)
          }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [s.paletteOpen, visibleRows, selected, menuOpen, cmdOpen, cmdQuery, cmdIndex, promptKind,
        selectedCount, batchMenu, onlySelOn, selectingOn])

      React.useEffect(() => {
        if (!s.paletteOpen || view !== 'sediment') return undefined
        const onKey = (event) => {
          const target = event.target
          const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')
          if (cmdOpen) return
          if (promptKind) {
            if (event.key === 'Escape') {
              event.preventDefault()
              closePrompt()
            }
            return
          }
          if (targetOpen) {
            if (event.key === 'Escape') {
              event.preventDefault()
              setTargetOpen(false)
            }
            return
          }
          if (manualOpen) {
            if (event.key === 'Escape') {
              event.preventDefault()
              setManualOpen(false)
            }
            return
          }
          const metaKey = event.metaKey || event.ctrlKey
          if (metaKey && !typing && (event.key === 'z' || event.key === 'Z')) {
            event.preventDefault()
            undoSel()
            return
          }
          if (metaKey && !typing && (event.key === 'a' || event.key === 'A')) {
            event.preventDefault()
            selectAllVisible()
            return
          }
          if (event.key === ' ' && !typing) {
            const spaceTarget = event.target
            const onRow = spaceTarget && spaceTarget.tagName === 'BUTTON'
              && typeof spaceTarget.className === 'string'
              && /(^|\s)scp-(pal|sed)-row(\s|$)/.test(spaceTarget.className)
            if (!(spaceTarget && spaceTarget.tagName === 'BUTTON') || onRow) {
              const pick = visibleRows[sedSel]
              if (pick) {
                event.preventDefault()
                toggleRowSelection(pick, sedSel, event.shiftKey ? 'range' : 'toggle')
              }
              return
            }
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            if (batchMenu) { setBatchMenu(false); return }
            if (selectedCount) { clearSelection(); return }
            if (selectingOn) { exitSelection(); return }
            setPaletteOpen(false)
            return
          }
          if (event.key === '/' && !typing) {
            event.preventDefault()
            if (searchRef.current && typeof searchRef.current.focus === 'function') searchRef.current.focus()
            return
          }
          if (typing) return
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (!visibleRows.length) return
            event.preventDefault()
            const next = event.key === 'ArrowDown' ? sedSel + 1 : sedSel - 1
            setSedSel(Math.max(0, Math.min(next, visibleRows.length - 1)))
            return
          }
          if (event.key === 'Enter') {
            if (event.target && event.target.tagName === 'BUTTON') return
            const pick = visibleRows[sedSel]
            if (!pick) return
            event.preventDefault()
            runSedNext(pick)
          }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [s.paletteOpen, view, visibleRows.length, sedSel, promptKind, targetOpen, manualOpen, cmdOpen,
        selectedCount, batchMenu, onlySelOn, selectingOn])

      // 详情抬头的三个钩子必须放在任何提前 return 之前：工作台关着时 Palette 提前返回，打开后
      // 又多出这三个钩子，React 会报「hook 数量与上次渲染不一致」，整个 shell.overlay 槽位崩掉，
      // 表现就是点「诊断工作台」没有反应。依赖值都从已声明的 state 现算，不依赖后面才赋值的局部变量。
      const ledeRow = visibleRows[selected] || null
      const ledeText = ledeRow ? (String(ledeRow.summary || '').trim() || caseTitle(ledeRow)) : ''
      const ledeOpen = Boolean(ledeRow) && ledeOpenId === ledeRow.sessionId
      const ledeRef = React.useRef(null)
      const [ledeOverflow, setLedeOverflow] = React.useState(false)
      React.useEffect(() => {
        const el = ledeRef.current
        if (!el || typeof el.scrollHeight !== 'number' || !(el.clientHeight > 0)) {
          setLedeOverflow(Boolean(ledeText) && ledeText.length > LEDE_TOGGLE_MIN)
          return
        }
        setLedeOverflow(ledeOpen || el.scrollHeight > el.clientHeight + 1)
      }, [ledeRow ? ledeRow.sessionId : '', ledeText, ledeOpen])

      // 选中行的三段时间线 + 修订：选中即取（同一 sessionId + updatedAt 命中缓存，10 秒轮询不重复拉）；
      // 步骤列表仍由「展开步骤」按需取，两者互不替代。
      const [layersState, setLayersState] = React.useState({ key: '', loading: false, error: '', data: null })
      const [layersRetry, setLayersRetry] = React.useState(0)
      const layersCacheRef = React.useRef(new Map())
      const layersToken = React.useRef(0)
      const layersKey = s.paletteOpen && view === 'diagnosis' && ledeRow
        ? String(ledeRow.sessionId || '') + '|' + String(ledeRow.updatedAt || '')
        : ''
      React.useEffect(() => {
        // 换行 / 关面板都让上一单的在途响应作废：token 先自增，命中缓存也要作废，
        // 否则旧请求晚到会把上一单的时间线写进这一单的状态。
        layersToken.current += 1
        const token = layersToken.current
        // 只在诊断视图取：沉淀视图的选中行不是诊断单，不用起这一次子进程。
        if (!s.paletteOpen || view !== 'diagnosis' || !ledeRow) return
        const key = layersKey
        const cached = layersCacheRef.current.get(key)
        if (cached) {
          setLayersState({ key, loading: false, error: '', data: cached })
          return
        }
        const target = ledeRow
        setLayersState({ key, loading: true, error: '', data: null })
        // 去抖：连按方向键时先清掉上一个 timer，只让停留的那一单起子进程。
        const timer = setTimeout(() => {
          if (layersToken.current !== token) return
          rpcCall('copilot-timeline', {
            cwd: store.cwd,
            tracesDir: data && data.tracesDir,
            sessionId: store.sessionId,
            traceFile: target.file,
          }).then((res) => {
            if (layersToken.current !== token) return
            if (res && res.ok) {
              const layers = normalizeTimelineLayers(res)
              layersCacheRef.current.set(key, layers)
              setLayersState({ key, loading: false, error: '', data: layers })
            } else {
              setLayersState({ key, loading: false, error: (res && res.message) || tr('layers.failedShort'), data: null })
            }
          }, (error) => {
            if (layersToken.current !== token) return
            setLayersState({ key, loading: false, error: String((error && error.message) || error), data: null })
          })
        }, LAYERS_DEBOUNCE_MS)
        return () => clearTimeout(timer)
      }, [s.paletteOpen, view, layersKey, layersRetry])

      // 沉淀详情抬头同样按「识别行 + 正文背景」渲染：与诊断详情共用一套样式与展开逻辑，
      // 只把正文换成草稿标题（标题就是来源 trace 的 summary 首句）。
      const sedPickKey = sedPick ? String(sedPick.key || '') : ''
      const sedPickTitle = sedPick ? String(sedPick.title || sedPick.key || '') : ''
      const sedLedeOpen = Boolean(sedPickKey) && sedLedeOpenKey === sedPickKey
      const sedLedeRef = React.useRef(null)
      const [sedLedeOverflow, setSedLedeOverflow] = React.useState(false)
      React.useEffect(() => {
        const el = sedLedeRef.current
        if (!el || typeof el.scrollHeight !== 'number' || !(el.clientHeight > 0)) {
          setSedLedeOverflow(Boolean(sedPickTitle) && sedPickTitle.length > LEDE_TOGGLE_MIN)
          return
        }
        setSedLedeOverflow(sedLedeOpen || el.scrollHeight > el.clientHeight + 1)
      }, [view, sedPickKey, sedPickTitle, sedLedeOpen])

      if (!s.paletteOpen) return null
      if (s.data && s.data.ok === false && s.data.code === 'E_NO_ROOT') return null

      const loadFailed = !data && (s.phase === 'error' || !!(s.data && s.data.ok === false))
      const loading = !data && !loadFailed
      const row = visibleRows[selected] || null
      selectedRowRef.current = row ? row.sessionId : ''
      const counts = data && data.counts ? data.counts : {}
      const filterCounts = {
        all: rows.length,
        open: filterRows(rows, 'open').length,
        pending: filterRows(rows, 'pending').length,
        sediment: filterRows(rows, 'sediment').length,
      }

      function fillDraft(text, meta) {
        const inputActions = findInputActions()
        if (inputActions && typeof inputActions.setDraft === 'function') {
          try {
            inputActions.setDraft(text)
            store.sedimentForceNext = true
            if (meta && meta.receipt) notePromptReceipt(meta.receipt.action, meta.receipt.rows)
            flash(tr('hint.draft'))
            setPaletteOpen(false)
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

      function runPrimary(target) {
        if (!target) return
        const boundId = data && data.bound ? data.bound.sessionId : ''
        const action = primaryFor(target, target.sessionId === boundId)
        if (action.mode === 'draft') fillDraft(action.text)
        else if (action.mode === 'copy') copyAndFlash(action.text)
        else {
          setMenuForm(action.mode === 'form' ? (action.form || null) : null)
          setMenuOpen(true)
        }
      }

      function toggleReport(target) {
        if (!target) return
        if (reportState.open) {
          reportToken.current += 1
          setReportState({ open: false, loading: false, text: '', error: '' })
          return
        }
        const wanted = target.sessionId
        const token = reportToken.current + 1
        reportToken.current = token
        const apply = (next) => {
          if (reportToken.current !== token || selectedRowRef.current !== wanted) return
          setReportState(next)
        }
        setReportState({ open: true, loading: true, text: '', error: '' })
        rpcCall('copilot-report', {
          cwd: store.cwd,
          tracesDir: data && data.tracesDir,
          traceSessionId: wanted,
          traceFile: target.file || '',
          reportFile: target.reportFile || (target.extra && target.extra.reportFile) || '',
        }).then((res) => {
          if (res && res.ok) {
            apply({ open: true, loading: false, text: String(res.text || ''), error: '' })
            if (reportToken.current === token) flash(tr('hint.reportOpen'))
          } else {
            apply({ open: true, loading: false, text: '', error: (res && res.message) || tr('report.none') })
          }
        }, (error) => {
          apply({ open: true, loading: false, text: '', error: String((error && error.message) || error) })
        })
      }

      function undoClose(target) {
        if (!target || undoBusy) return
        setUndoBusy(true)
        rpcCall('copilot-transition', transitionPayload(target, data, { kind: 'reopen' }))
          .then((res) => {
            setUndoBusy(false)
            if (res && res.ok) {
              flash(tr('hint.reopened'))
              refresh(true)
            } else {
              flash(tr('write.failed', { message: (res && res.message) || '' }))
            }
          }, (error) => {
            setUndoBusy(false)
            flash(tr('write.failed', { message: String((error && error.message) || error) }))
          })
      }

      function checklistAction(target, item) {
          if (!item || !item.kind) return
        if (item.kind === 'report') fillDraft(reportDraft(target))
        else if (item.kind === 'feedback') { setMenuForm('feedback'); setMenuOpen(true) }
        else if (item.kind === 'sediment') fillDraft(sedimentDraft(target))
        else if (item.kind === 'handoff') fillDraft(handoffDraft(target))
      }

      function candidateAction(target, candidate) {
        if (candidate && String(candidate.status || '') === 'produced') return
        const summary = String((candidate && candidate.summary) || '')
        const evidence = String((candidate && candidate.evidence) || '')
        if (candidate && candidate.kind === 'reference') fillDraft(referenceDraft(target, summary, evidence))
        else if (candidate && candidate.kind === 'triage') fillDraft(triageDraft(target, summary))
        else fillDraft(sedimentDraft(target))
      }

      function toggleTimeline(target) {
        if (!target) return
        if (timelineState.open) {
          timelineToken.current += 1
          setTimelineState({ open: false, loading: false, items: [], error: '' })
          return
        }
        const token = timelineToken.current + 1
        timelineToken.current = token
        setTimelineState({ open: true, loading: true, items: [], error: '' })
        rpcCall('copilot-timeline', {
          cwd: store.cwd,
          tracesDir: data && data.tracesDir,
          sessionId: store.sessionId,
          traceFile: target.file,
        }).then((res) => {
          if (timelineToken.current !== token || selectedRowRef.current !== target.sessionId) return
          if (res && res.ok) {
            setTimelineState({ open: true, loading: false, items: Array.isArray(res.timeline) ? res.timeline : [], error: '' })
          } else {
            setTimelineState({ open: true, loading: false, items: [], error: (res && res.message) || tr('timeline.none') })
          }
        }, (error) => {
          if (timelineToken.current !== token || selectedRowRef.current !== target.sessionId) return
          setTimelineState({ open: true, loading: false, items: [], error: String((error && error.message) || error) })
        })
      }

      function commandItemsFor(target) {
        if (!target) return []
        const items = []
        const primary = primaryFor(target, data && data.bound && target.sessionId === data.bound.sessionId)
        items.push({ group: 'primary', label: tr('command.primary') + '：' + primary.label, run: () => runPrimary(target) })
        items.push({ group: 'copy', label: tr('action.copySummary'), run: () => copyAndFlash(summaryText(target, data)) })
        items.push({ group: 'copy', label: tr('copy.issue'), run: () => copyAndFlash(issueText(target)) })
        items.push({ group: 'view', label: tr('action.viewReport'), run: () => toggleReport(target) })
        if (target.activeCase) items.push({ group: 'view', label: tr('action.upstream'), run: () => fillDraft(upstreamDraft(target, data.upstream)) })
        items.push({ group: 'view', label: tr('action.loadTimeline'), run: () => toggleTimeline(target) })
        if ((target.activeCase || isPending(target)) && primary.key !== 'feedback') {
          items.push({ group: 'action', label: tr('action.feedback'), run: () => { setMenuForm('feedback'); setMenuOpen(true) } })
        }
        if (canStartSediment(target)) {
          items.push({ group: 'action', label: tr('action.sediment'), run: () => fillDraft(sedimentDraft(target)) })
        }
        items.push({ group: 'nav', label: tr('action.refresh'), run: () => { refresh(true); flash(tr('hint.refreshed')) } })
        items.push({ group: 'nav', label: tr('palette.close'), run: () => setPaletteOpen(false) })
        return items
      }

      function def(label, value, key) {
        return h('div', { className: 'scp-def', key: key || label },
          h('dt', {}, label),
          h('dd', {}, value))
      }

      const filterButtons = FILTER_KEYS.map((key) => h('button', {
        key,
        type: 'button',
        className: 'scp-filter-item',
        'data-on': filter === key ? 'true' : 'false',
        'aria-pressed': filter === key ? 'true' : 'false',
        onClick: () => savePrefs({ paletteFilter: key }),
      }, tr('palette.filter.' + key), h('b', {}, data ? String(filterCounts[key] || 0) : '—')))

      // 首屏不铺满复选框：给一个小入口，点开才把行前的框全部露出来（触屏没有悬停）。
      const selectToggle = h('button', {
        type: 'button', className: 'scp-select-toggle', title: tr('sel.enterHint'),
        'aria-pressed': selectingOn ? 'true' : 'false',
        onClick: enterSelection,
      }, tr('sel.enter'))

      const skeleton = Array.from({ length: 5 }, (_, index) => h('div', { key: 'skel-' + index, className: 'scp-pal-row' },
        h('span', { className: 'scp-ring', style: { background: 'var(--dsw-alias-bg-layer-2)', boxShadow: 'none' } }),
        h('span', { className: 'scp-pal-row-main' },
          h('span', { className: 'scp-skel', style: { width: '68%' } }),
          h('span', { className: 'scp-skel', style: { width: '42%', height: 9 } }))))

      const emptyMark = h('svg', {
        width: 40, height: 40, viewBox: '0 0 40 40', fill: 'none', stroke: 'currentColor',
          strokeWidth: 1.2, 'aria-hidden': 'true', opacity: 0.35,
      }, h('circle', { cx: 20, cy: 20, r: 13, strokeDasharray: '3 4' }),
        h('path', { d: 'M14 20h12M20 14v12', strokeLinecap: 'round' }))

      const list = h('div', {
        ref: listRef, className: 'scp-pal-list', role: 'region',
        'aria-label': tr('palette.title'), 'data-selecting': selectingOn ? 'true' : 'false',
      },
        h('div', { className: 'scp-search' },
          h('input', {
            ref: searchRef, type: 'search', value: searchText,
            placeholder: tr('search.placeholder'), 'aria-label': tr('search.placeholder'),
            onChange: (event) => { setSearchText(event.target.value); selectIndex(0) },
            onKeyDown: (event) => { if (event.key === 'Escape') { setSearchText(''); event.stopPropagation() } },
          }),
          h('span', { className: 'scp-kbd' }, '/')),
        h('div', { className: 'scp-filters', role: 'group', 'aria-label': tr('palette.filterLabel') },
          filterButtons, selectingOn ? null : selectToggle),
        !data ? skeleton
          : visibleRows.length === 0 ? h('div', { className: 'scp-pal-empty' }, emptyMark, tr('palette.emptyFiltered'),
            h('button', {
              type: 'button', className: 'scp-btn',
              onClick: () => { setSearchText(''); savePrefs({ paletteFilter: 'all' }); selectIndex(0) },
            }, tr('palette.clearFilters')))
            : visibleRows.map((item, index) => {
              const extra = item.extra || {}
              const metaPieces = []
              if (extra.platform) metaPieces.push(extra.platform)
              if (extra.framework) metaPieces.push(extra.framework)
              const id = String(item.sessionId || '')
              const checked = selSet.has(id)
              return h('div', { key: id, className: 'scp-row-wrap' },
                h('button', {
                  key: 'check',
                  type: 'button',
                  className: 'scp-row-check',
                  role: 'checkbox',
                  'aria-checked': checked ? 'true' : 'false',
                  'aria-label': tr('sel.check', { title: caseTitle(item) }),
                  tabIndex: -1,
                  onClick: (event) => {
                    const e = event || {}
                    if (typeof e.stopPropagation === 'function') e.stopPropagation()
                    toggleRowSelection(item, index, e.shiftKey ? 'range' : 'toggle')
                  },
                }, h('span', { className: 'scp-row-check-box', 'aria-hidden': 'true' }, checked ? '✓' : '')),
                h('button', {
                  key: 'row',
                  type: 'button',
                  className: 'scp-pal-row',
                  'aria-current': index === selected ? 'true' : 'false',
                  'data-pending': isPending(item) ? 'true' : 'false',
                  'data-on': index === selected ? 'true' : 'false',
                  'data-sel': checked ? 'true' : 'false',
                  onFocus: () => { if (selected !== index) selectIndex(index) },
                  style: { '--scp-tone': TONE_VAR[toneOf(item)] || TONE_VAR.idle },
                  onClick: (event) => {
                    const e = event || {}
                    if (e.shiftKey) toggleRowSelection(item, index, 'range')
                    else if (e.metaKey || e.ctrlKey) toggleRowSelection(item, index, 'toggle')
                    selectIndex(index)
                    setMenuOpen(false)
                  },
                  onDoubleClick: () => runPrimary(item),
                },
                  h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                  h('span', { className: 'scp-pal-row-main' },
                    h('span', { className: 'scp-pal-row-line' },
                      h('span', { className: 'scp-pal-row-title', title: caseTitle(item) }, caseTitle(item)),
                      h('span', { className: 'scp-pal-row-step' }, stepsShort(extra))),
                    h('span', { className: 'scp-pal-row-meta' },
                      h('span', { className: 'scp-pal-row-meta-main' },
                        [statusMeta(data.vocab, item.status).label].concat(metaPieces).join(' · '),
                        isPending(item) ? h('span', { key: 'pending', className: 'scp-chip', 'data-tone': 'warn' }, tr('chip.feedback')) : null),
                      h('span', { className: 'scp-pal-row-time' }, formatTime(item.updatedAt) || tr('none'))))))
            }))

      const waiting = row ? ((row.derived && row.derived.waitingFor) || (row.extra && row.extra.evidenceMissing) || '') : ''
      const extra = row ? (row.extra || {}) : {}
      const sideMeta = []
      if (extra.platform) sideMeta.push(extra.platform)
      if (extra.framework) sideMeta.push(extra.framework)
      if (extra.category) sideMeta.push(CATEGORY_LABEL[extra.category] || extra.category)
      const materials = row ? ((extra.missingMaterials) || []) : []
      const showMaterials = Boolean(row) && (materials.length > 0
        || Boolean(row && row.derived && row.derived.waitingOn === 'user_material' && waiting))
      const commandItems = commandItemsFor(row)
      const cmdNeedle = cmdQuery.trim().toLowerCase()
      const commandList = cmdNeedle
        ? commandItems.filter((item) => item.label.toLowerCase().includes(cmdNeedle))
        : commandItems
      commandsRef.current = commandList
      const checklist = row && shouldShowChecklist(row) ? checklistFor(row, data) : []
      const upstream = row && row.derived ? (row.derived.upstream || null) : null
      const evidenceList = row ? (extra.evidenceList || []) : []
      const candidateList = row ? (extra.sedimentCandidateList || []) : []
      const closeInfo = row ? lastClose(row) : null
      const originSession = row ? (row.harnessSession || '') : ''
      const resumedSessions = row ? (row.resumeSessions || []).filter((sid) => sid && sid !== originSession) : []
      const currentSession = store.sessionId || ''

