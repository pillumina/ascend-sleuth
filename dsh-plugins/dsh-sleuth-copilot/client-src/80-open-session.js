    // ── 打开其它会话（轨迹写了 harness_session 时可用）────────────────────
    let openSessionImpl = () => Promise.resolve({ ok: false, reason: '会话服务不可用' })
    function ctxOpenSession(id) {
      return openSessionImpl(id)
    }

