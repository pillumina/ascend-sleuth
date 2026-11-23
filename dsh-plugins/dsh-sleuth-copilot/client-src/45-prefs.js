    // ── 偏好（记住上次的展开状态、常驻与筛选）──────────────────────────────
    const DEFAULT_PREFS = { dockCollapsed: true, dockKeepOpen: false, paletteFilter: 'all', pins: {} }
    function loadPrefs() {
      try {
        const raw = window.localStorage.getItem(PREFS_KEY)
        if (!raw) return Object.assign({}, DEFAULT_PREFS)
        const parsed = JSON.parse(raw)
        const prefs = Object.assign({}, DEFAULT_PREFS)
        if (parsed && typeof parsed.dockCollapsed === 'boolean') prefs.dockCollapsed = parsed.dockCollapsed
        if (parsed && typeof parsed.dockKeepOpen === 'boolean') prefs.dockKeepOpen = parsed.dockKeepOpen
        if (parsed && FILTER_KEYS.indexOf(parsed.paletteFilter) >= 0) prefs.paletteFilter = parsed.paletteFilter
        if (parsed && parsed.pins && typeof parsed.pins === 'object' && !Array.isArray(parsed.pins)) {
          const pins = {}
          for (const [key, value] of Object.entries(parsed.pins)) {
            if (typeof value === 'string' && value && Object.keys(pins).length < 40) pins[String(key)] = value
          }
          prefs.pins = pins
        }
        return prefs
      } catch {
        return Object.assign({}, DEFAULT_PREFS)
      }
    }
    function savePrefs(patch) {
      store.prefs = Object.assign({}, store.prefs, patch)
      try {
        window.localStorage.setItem(PREFS_KEY, JSON.stringify(store.prefs))
      } catch {
        // 隐私模式或沙箱禁写 localStorage 时，本次会话内仍然生效
      }
      emit()
    }

    // 手动选择跟踪哪一单：per-session 的 pin，存在 prefs.pins 里；空串 = 跟随会话。
    function pinsOf() {
      return (store.prefs && store.prefs.pins) || {}
    }

    function pinnedIdFor(sessionId) {
      return sessionId ? (pinsOf()[sessionId] || '') : ''
    }

    function setPin(sessionId, traceId) {
      if (!sessionId) return
      const pins = Object.assign({}, pinsOf())
      if (traceId) pins[sessionId] = traceId
      else delete pins[sessionId]
      savePrefs({ pins })
    }

