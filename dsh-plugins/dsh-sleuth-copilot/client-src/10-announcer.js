    // ── 读屏播报（常驻 live region）────────────────────────────────────────
    // 读屏只在「容器已存在、内容发生变化」时播报；节点带着文字一起创建时常常不播。
    // 因此在 body 上放两个常驻容器（polite / assertive），所有结果与错误都写它们；
    // 视觉上的提示行 / toast 仍按原样出现和消失。
    const ANN_POLITE_ID = 'dsh-sleuth-copilot-status'
    function announcerNode() {
      let node = typeof document.getElementById === 'function' ? document.getElementById(ANN_POLITE_ID) : null
      if (node) return node
      node = document.createElement('div')
      node.id = ANN_POLITE_ID
      node.className = 'scp-sr-only'
      node.setAttribute('role', 'status')
      node.setAttribute('aria-live', 'polite')
      node.setAttribute('aria-atomic', 'true')
      if (!document.body || typeof document.body.appendChild !== 'function') return null
      document.body.appendChild(node)
      return node
    }
    // 区域要在第一条消息之前就存在，否则读屏不播报；状态条挂载时就把它建好。
    function ensureAnnouncementRegions() {
      if (typeof document === 'undefined') return
      try { announcerNode() } catch { /* 替身渲染环境没有可用 DOM */ }
    }
    // 插件卸载时把容器清掉：样式表已卸载，留着带文字的节点会变成页面底部的可见文字。
    function removeAnnouncementRegions() {
      if (typeof document === 'undefined') return
      try {
        const node = typeof document.getElementById === 'function' ? document.getElementById(ANN_POLITE_ID) : null
        if (node && node.parentNode && typeof node.parentNode.removeChild === 'function') node.parentNode.removeChild(node)
      } catch { /* 忽略 */ }
    }
    function announce(text) {
      const value = String(text || '').trim()
      if (!value || typeof document === 'undefined') return
      try {
        const node = announcerNode()
        if (!node) return
        // 同一句话连续出现（连点两次复制）时先清空，否则读屏认为内容没变。
        node.textContent = ''
        const write = () => { node.textContent = value }
        if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(write)
        else write()
      } catch { /* 替身渲染环境没有可用 DOM，忽略 */ }
    }
    // 查合入的进度（n/m）每 500ms 变一次：播报节流到 3 秒，避免读屏刷屏。
    let lastCheckAnnounceAt = 0
    // 同一角色可能同时存在两份表单（状态条菜单与工作台菜单），字段 id 不能只按表单 kind 生成。
    let formSeq = 0
    function announceCheckProgress(run) {
      if (!run || !run.total) return
      const now = Date.now()
      if (now - lastCheckAnnounceAt < 3000) return
      lastCheckAnnounceAt = now
      announce(tr('sediment.checkingProgress', { n: Math.min(run.seen, run.total), m: run.total }))
    }

