    // ── 面 2：输入区工具条入口 ─────────────────────────────────────────────
    function ToolbarButton(props) {
      const s = useStore()
      useSessionSync(props)
      if (s.data && s.data.ok === false && s.data.code === 'E_NO_ROOT') return null
      const data = s.data && s.data.ok !== false ? s.data : null
      const bound = data ? data.bound : null
      const pending = data && data.counts ? Number(data.counts.pendingFeedback) || 0 : 0
      const tone = bound ? toneOf(bound) : 'idle'
      const title = [tr('tool.title'), pending > 0 ? tr('tool.pending', { n: pending }) : '', shortcutOpenLabel()]
        .filter(Boolean).join(' · ')
      return h('button', {
        type: 'button',
        className: 'scp-tool-btn',
        'data-tone': tone,
        title,
        'aria-label': title,
        'data-version': PLUGIN_VERSION,
        onClick: () => setPaletteOpen(!s.paletteOpen),
      },
        h('svg', { width: 15, height: 15, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' },
          h('path', { d: 'M2.4 4.2h11.2M2.4 8h11.2M2.4 11.8h7' })),
        pending > 0 ? h('span', { className: 'scp-tool-badge' }, pending > 9 ? '9+' : String(pending)) : null)
    }

