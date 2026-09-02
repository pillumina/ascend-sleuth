// ev-panel host —— 自演进看板数据服务（EV 卡 / 容量 / 台账归因 / timeline）
// 用法：cordis_define kind:new → code.host 用本文件全文；code.client 用 panel-client.js 全文。
// host 侧通过 shell 跑 scripts/ev_board_data.py 汇总 JSON（确定性逻辑在脚本，遵循原则二）。
return {
  apply(ctx) {
    const fs = ctx.get('fs')
    if (fs === undefined) return
    const sessions = ctx.get('sessions')
    const shell = ctx.get('shell')

    function resolveCwd(sessionId) {
      if (sessions && sessionId) {
        const s = sessions.get(sessionId)
        if (s && s.header && s.header.cwd) return s.header.cwd
      }
      return undefined
    }

    async function loadBoard(sessionId) {
      const cwd = resolveCwd(sessionId)
      if (!cwd) return { ok: false, error: '无法解析工作区' }
      if (!shell) return { ok: false, error: 'shell 不可用' }
      try {
        const spec = shell.resolve({
          command: 'python3 scripts/ev_board_data.py',
          workdir: cwd,
          stdoutMaxBytes: 65536,
        })
        const r = await shell.run(spec)
        const stdout = r && r.stdout && typeof r.stdout.text === 'string' ? r.stdout.text : ''
        if (!stdout.trim()) {
          const err = r && typeof r.stderr === 'string' ? r.stderr : 'ev_board_data.py 无输出'
          return { ok: false, error: String(err).slice(0, 800) }
        }
        let data = null
        try {
          data = JSON.parse(stdout)
        } catch (e) {
          return { ok: false, error: 'ev_board_data.py 输出非 JSON: ' + String(e && e.message || e) }
        }
        return { ok: true, data }
      } catch (e) {
        return { ok: false, error: '看板数据读取失败: ' + String(e && e.message || e) }
      }
    }

    const handleDisposer = harness.handle('ev-board-load', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      return loadBoard(sessionId)
    })

    return () => {
      if (handleDisposer) handleDisposer()
    }
  },
}
