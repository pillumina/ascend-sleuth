    // ── 共享 store（各面同一份数据与开关）──────────────────────────────────
    let commandRequested = false

    const store = {
      prefs: loadPrefs(),
      sessionId: '',
      cwd: '',
      phase: 'idle',
      data: null,
      message: '',
      stale: false,
      lastOkAt: 0,
      staleMessage: '',
      paletteOpen: false,
      paletteSelect: '',
      paletteView: 'diagnosis',
      sedimentSelectKey: '',
      sediment: { phase: 'idle', data: null, message: '', at: 0 },
      sedimentSeq: 0,
      // 填过指令之后，下一次打开队列强制刷新一次：指令在会话里执行、面板收不到通知，
      // 60 秒去重会让读者回来时还看到执行前的旧行（例如刚撤销的草稿还在）。
      sedimentForceNext: false,
      // 查合入的逐条进度：active 时把已到达的行就地写进 sediment.drafts；
      // 整批结束 refreshSediment(true) 会覆盖为权威快照，然后清空。
      checkRun: null,
      // 这一轮查合入的停轮询句柄：切会话 / 插件卸载时要能打断在飞的轮询。
      checkStop: null,
      version: 0,
      listeners: new Set(),
      timer: null,
      onFocus: null,
      seq: 0,
    }

    function emit() {
      store.version += 1
      store.listeners.forEach((listener) => {
        try {
          listener()
        } catch {
          // 单个订阅者出错不拖累其余
        }
      })
    }

    function useStore() {
      const [, force] = React.useState(0)
      React.useEffect(() => {
        const listener = () => force((value) => value + 1)
        store.listeners.add(listener)
        return () => {
          store.listeners.delete(listener)
        }
      }, [])
      return store
    }

    let rpcCall = async () => {
      throw new Error('connection 服务不可用')
    }

    async function refresh(force) {
      if (!store.sessionId) return
      const seq = store.seq + 1
      store.seq = seq
      try {
        const value = await rpcCall('copilot-state', {
          sessionId: store.sessionId,
          cwd: store.cwd,
          refresh: force === true,
        })
        if (seq !== store.seq) return
        store.data = value
        store.phase = 'ready'
        store.message = ''
        store.stale = false
        store.lastOkAt = Date.now()
        store.staleMessage = ''
        emit()
      } catch (error) {
        if (seq !== store.seq) return
        const message = String((error && error.message) || error)
        if (store.phase === 'ready') {
          // 首屏成功过：保留旧数据，但标出来源已取不到，不能让界面显示成实时状态。
          store.stale = true
          store.staleMessage = message
          emit()
          return
        }
        store.phase = 'error'
        store.message = message
        emit()
      }
    }

    // 「去同步」的两个后续动作放在插件闭包而不是状态条组件里：点「去同步」会把会话输入区
    // 连同状态条一起卸载（整页切换），组件一卸载，挂在 ref 上的轮询与复查定时器就全被清掉，
    // 复查不跑、知识库标签也点不到。提示是全局的，不随会话走，所以只在插件卸载时清。
    let kbRecheckTimer = null
    let kbTabTimer = null

    function clearKbTimers() {
      if (kbRecheckTimer) {
        clearTimeout(kbRecheckTimer)
        kbRecheckTimer = null
      }
      if (kbTabTimer) {
        clearTimeout(kbTabTimer)
        kbTabTimer = null
      }
    }

    // 切到整页后不一定落在「知识库」子页：按可见标签名找，1.5 秒内轮询等页面挂载。
    // 没有 querySelectorAll 的宿主（测试替身）直接跳过这一层。
    function openKbTab() {
      if (typeof document === 'undefined' || typeof document.querySelectorAll !== 'function') return
      if (kbTabTimer) clearTimeout(kbTabTimer)
      const startedAt = Date.now()
      function tick() {
        kbTabTimer = null
        let tabs = null
        try {
          tabs = document.querySelectorAll('[role="tab"]')
        } catch {
          tabs = null
        }
        if (tabs && typeof tabs.length === 'number') {
          for (let index = 0; index < tabs.length; index += 1) {
            const tab = tabs[index]
            if (!tab) continue
            let label = ''
            try {
              label = String(tab.textContent || '').trim()
            } catch {
              label = ''
            }
            if (label !== '知识库') continue
            let inside = false
            try {
              inside = typeof tab.closest === 'function' && !!tab.closest('.sleu-console')
            } catch {
              inside = false
            }
            if (!inside) continue
            try {
              if (typeof tab.click === 'function') tab.click()
            } catch {
              // 点不开就停在整页，读者自己点标签
            }
            return
          }
        }
        if (Date.now() - startedAt >= KB_TAB_OPEN_WAIT_MS) return
        kbTabTimer = setTimeout(tick, KB_TAB_OPEN_POLL_MS)
      }
      tick()
    }

    // 同步要时间：隔 30 秒复查一次，还落后再隔 60 秒复查（共约 90 秒）。
    // 每次刷新后提示行还在才挂下一次（同步完则行消失、不再定时）。
    function scheduleKbRecheck(attempt) {
      if (kbRecheckTimer) {
        clearTimeout(kbRecheckTimer)
        kbRecheckTimer = null
      }
      const delay = KB_RECHECK_DELAYS_MS[attempt]
      if (delay === undefined) return
      kbRecheckTimer = setTimeout(() => {
        kbRecheckTimer = null
        Promise.resolve()
          .then(() => rpcCall('copilot-kb-recheck', { force: true }))
          .then(() => refresh(true))
          .then(() => {
            if (!store.data || !store.data.kbNotice) return
            scheduleKbRecheck(attempt + 1)
          })
          .catch(() => {
            // 这里只兜 RPC 抛错：不改提示行，等下一轮定时检查。
            // host 业务失败不抛错，它按静默规则回空，随后的 refresh 可能把行清掉。
          })
      }, delay)
    }

    // 沉淀队列：按需读取。展开状态条或打开沉淀视图时才跑（groom_status 要读 git 与 inbox，
    // 不能塞进 10 秒轮询）。保留上一次数据，刷新时只切 phase，不闪空。
    async function refreshSediment(force) {
      if (!store.cwd) return
      const now = Date.now()
      const forceNext = store.sedimentForceNext === true
      if (!force && !forceNext && store.sediment.phase === 'ready' && now - store.sediment.at < 60000) return
      store.sedimentForceNext = false
      const seq = store.sedimentSeq + 1
      store.sedimentSeq = seq
      store.sediment = Object.assign({}, store.sediment, {
        phase: store.sediment.data ? 'refreshing' : 'loading',
        message: '',
      })
      emit()
      try {
        const value = await rpcCall('copilot-sediment', {
          cwd: store.cwd,
          sessionId: store.sessionId,
        })
        if (seq !== store.sedimentSeq) return
        store.sediment = {
          phase: value && value.ok !== false ? 'ready' : 'error',
          data: value,
          message: value && value.ok === false ? String(value.message || '') : '',
          at: Date.now(),
        }
        emit()
      } catch (error) {
        if (seq !== store.sedimentSeq) return
        store.sediment = {
          phase: 'error',
          data: store.sediment.data,
          message: String((error && error.message) || error),
          at: Date.now(),
        }
        emit()
      }
    }

    // 查合入逐条进度：批次开始时建一条记录（记下本轮要查的草稿与总数），轮询到的 row
    // 就地写进 sediment.drafts 对应草稿的 pr.state/pr.checkedAt，并 emit 让行立即重画。
    // 整批结束会 refreshSediment(true) 覆盖为权威快照，所以这里只做乐观更新。
    function beginCheckRun(drafts) {
      const targets = {}
      let total = 0
      const list = Array.isArray(drafts) ? drafts : []
      // 与 pr_status.py 的 CHECKABLE 一致：只有待合入 / 未确认会被查，终态不查。
      list.forEach((draft) => {
        if (!draft || !draft.key || !draft.pr) return
        const state = String(draft.pr.state || '')
        if (state !== 'open' && state !== 'unknown') return
        targets[draft.key] = true
        total += 1
      })
      store.checkRun = { active: true, seen: 0, total, targets, states: {} }
      emit()
    }

    function applyCheckProgress(rows, run) {
      // run 是本轮句柄：切会话 / 新一轮开始后，在飞的旧轮询不能再 patch 已刷新的快照。
      if (!run || run !== store.checkRun || !run.active || !Array.isArray(rows) || !rows.length) return
      const data = store.sediment && store.sediment.data
      const drafts = data && Array.isArray(data.drafts) ? data.drafts : []
      if (!drafts.length) return
      let patched = false
      const nextDrafts = drafts.map((draft) => {
        if (!draft || !draft.key) return draft
        const row = rows.find((item) => item && item.draft === draft.key)
        if (!row) return draft
        const known = run.states[draft.key]
        if (known && known.state === String(row.state || '') && known.ok === (row.ok !== false)
          && known.error === String(row.error || '')) return draft
        // 分子只数本轮名单里的草稿，避免出现 n > m。
        if (!known && run.targets && run.targets[draft.key] === true) run.seen += 1
        run.states[draft.key] = {
          ok: row.ok !== false,
          state: String(row.state || 'unknown'),
          error: row.error ? String(row.error) : '',
          message: row.message ? String(row.message) : '',
          checkedAt: String(row.checked_at || ''),
        }
        patched = true
        const pr = draft.pr || {}
        return Object.assign({}, draft, {
          pr: Object.assign({}, pr, {
            state: String(row.state || pr.state || 'unknown'),
            checkedAt: String(row.checked_at || pr.checkedAt || ''),
            ...(row.ok !== false ? { source: 'platform' } : {}),
          }),
        })
      })
      if (!patched) return
      announceCheckProgress(run)
      store.sediment = Object.assign({}, store.sediment, {
        data: Object.assign({}, data, { drafts: nextDrafts }),
      })
      emit()
    }

    function endCheckRun() {
      store.checkRun = null
      emit()
    }

    function setPaletteView(view) {
      const next = view === 'sediment' ? 'sediment' : 'diagnosis'
      if (store.paletteView === next) return
      store.paletteView = next
      emit()
    }

    function openSediment(key) {
      store.sedimentSelectKey = key ? String(key) : ''
      setPaletteOpen(true, '', 'sediment')
    }

    function startTimer() {
      if (store.timer) return
      store.timer = setInterval(() => {
        if (document.visibilityState === 'visible') refresh(false)
      }, POLL_MS)
      store.onFocus = () => {
        if (document.visibilityState === 'visible') refresh(false)
      }
      window.addEventListener('focus', store.onFocus)
    }

    // 插件被禁用或热重载时停掉轮询与 focus 监听：apply 没有清理时，
    // 卸载后仍每 10 秒发一次 copilot-state。
    function stopTimer() {
      if (store.timer) {
        clearInterval(store.timer)
        store.timer = 0
      }
      if (store.onFocus) {
        window.removeEventListener('focus', store.onFocus)
        store.onFocus = null
      }
      // 插件卸载时在飞的查合入轮询也要停，否则它还会继续发进度请求。
      if (typeof store.checkStop === 'function') {
        store.checkStop()
        store.checkStop = null
      }
    }

    function ensureSession(sessionId, cwd) {
      if (!sessionId) return
      if (store.sessionId !== sessionId || store.cwd !== cwd) {
        store.sessionId = sessionId
        store.cwd = cwd
        store.phase = 'loading'
        store.data = null
        store.message = ''
        store.stale = false
        store.staleMessage = ''
        store.sediment = { phase: 'idle', data: null, message: '', at: 0 }
        store.sedimentSeq += 1
        // 切会话：上一轮的轮询与进度都不属于这一单，先停再清。
        if (typeof store.checkStop === 'function') {
          store.checkStop()
          store.checkStop = null
        }
        store.checkRun = null
        emit()
        refresh(true)
      } else if (!store.data && store.phase !== 'loading') {
        refresh(false)
      }
      startTimer()
    }

    function setPaletteOpen(open, selectId, view) {
      const next = !!open
      const nextSelect = selectId === undefined ? store.paletteSelect : String(selectId || '')
      const nextView = view === undefined ? store.paletteView : String(view || 'diagnosis')
      if (store.paletteOpen === next && (selectId === undefined || store.paletteSelect === nextSelect)
        && (view === undefined || store.paletteView === nextView)) return
      store.paletteOpen = next
      store.paletteSelect = nextSelect
      store.paletteView = nextView
      emit()
    }

    function copyToClipboard(text) {
      const value = String(text || '')
      try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          return navigator.clipboard.writeText(value).then(() => true, () => fallbackCopy(value))
        }
      } catch {
        // 落到 execCommand 兜底
      }
      return Promise.resolve(fallbackCopy(value))
    }

    function fallbackCopy(value) {
      try {
        const area = document.createElement('textarea')
        area.value = value
        area.setAttribute('readonly', '')
        area.style.position = 'fixed'
        area.style.opacity = '0'
        document.body.appendChild(area)
        area.select()
        const ok = typeof document.execCommand === 'function' ? document.execCommand('copy') : false
        area.remove()
        return !!ok
      } catch {
        return false
      }
    }

