    // ── 图标 ────────────────────────────────────────────────────────────────
    function IconRefresh() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' },
        h('path', { d: 'M13.2 8a5.2 5.2 0 1 1-1.6-3.75' }),
        h('path', { d: 'M13.4 2.6v3.1h-3.1' }))
    }

    function IconChevron(props) {
      return h('svg', { className: 'scp-chevron', 'data-open': props.open ? 'true' : 'false', width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' },
        h('path', { d: 'M4 6.2 8 10.2l4-4' }))
    }

    function IconLedger() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' },
        h('path', { d: 'M3 4h10M3 8h10M3 12h6' }))
    }

    function IconMore() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'currentColor' },
        h('circle', { cx: 3.2, cy: 8, r: 1.2 }),
        h('circle', { cx: 8, cy: 8, r: 1.2 }),
        h('circle', { cx: 12.8, cy: 8, r: 1.2 }))
    }

    function IconClose() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' },
        h('path', { d: 'M4.5 4.5l7 7M11.5 4.5l-7 7' }))
    }

    function IconPin(props) {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: props && props.on ? 'currentColor' : 'none', stroke: 'currentColor', strokeWidth: 1.4, strokeLinecap: 'round', strokeLinejoin: 'round' },
        h('path', { d: 'M6 2.2h4l-.5 3.1 2 2v1.2H4.5V7.3l2-2L6 2.2z' }),
        h('path', { d: 'M8 8.7v5.1', fill: 'none' }))
    }

