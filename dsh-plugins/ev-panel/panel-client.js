// ev-panel client —— 自演进看板（conversation.view 第三个 tab「自演进」）
// 数据经 host.call('ev-board-load') 从 scripts/ev_board_data.py 汇总。
// 纯 React.createElement，无 JSX/TS。主题用 --dsw-alias-* CSS 变量（与 ascend-panel 一致）。
return {
  apply(ctx) {
    const slots = ctx.get('slots')
    if (slots === undefined) return

    const T = {
      bg: 'var(--dsw-alias-bg-layer-1)', bg2: 'var(--dsw-alias-bg-layer-2)',
      border: 'var(--dsw-alias-border-l1)', text: 'var(--dsw-alias-label-primary)',
      text2: 'var(--dsw-alias-label-secondary)', brand: 'var(--dsw-alias-brand-primary)',
      success: 'var(--dsw-alias-state-success-primary)', warn: 'var(--dsw-alias-state-warn-primary)',
      error: 'var(--dsw-alias-state-error-primary)',
    }
    // EV 卡状态机（pipeline §7 v3 词表）→ 展示标签/颜色
    const STATUS_META = {
      candidate: { label: '候选', color: '#8b5cf6' },
      proposed: { label: '已提议', color: '#6366f1' },
      in_experiment: { label: '实验中', color: '#3b82f6' },
      pending_merge: { label: '待合入', color: '#f59e0b' },
      adopted: { label: '已采纳', color: '#22c55e' },
      validated: { label: '已验证', color: '#10b981' },
      rolled_back: { label: '已回滚', color: '#ef4444' },
      superseded: { label: '被替代', color: '#9ca3af' },
      rejected: { label: '已否决', color: '#6b7280' },
    }
    const LAYER_LABELS = { L1: '内容', L2: '流程', L3: '机制' }
    const AUTH_COLORS = { auto: '#22c55e', review: '#3b82f6', dual: '#ef4444' }
    const CAT_LABELS = { interrupt: '中断', precision: '精度', performance: '性能' }

    function relTime(iso) {
      if (!iso) return null
      const t = new Date(String(iso)).getTime()
      if (isNaN(t)) return null
      const diff = Math.max(0, Date.now() - t)
      const m = Math.floor(diff / 60000)
      if (m < 1) return '刚刚'
      if (m < 60) return m + ' 分钟前'
      const h = Math.floor(m / 60)
      return h < 24 ? h + ' 小时前' : Math.floor(h / 24) + ' 天前'
    }
    function pct(a, b) {
      if (!b) return '—'
      return Math.round((a / b) * 100) + '%'
    }

    function fmtSignals(idea) {
      const sigs = idea.source_signals || []
      if (!sigs.length) return []
      return sigs.map(s => (s && s.signal) || 'signal')
    }

    // ============ 卡流水（状态机分组看板） ============
    function IdeaBoard({ ideas }) {
      const groups = Object.keys(STATUS_META).map(st => ({
        st, meta: STATUS_META[st], items: ideas.filter(i => (i.status || 'candidate') === st),
      })).filter(g => g.items.length || ['candidate', 'adopted', 'validated'].includes(g.st))
      return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
        groups.map(g => g.items.length === 0 ? null : React.createElement('div', { key: g.st, style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 12, padding: '8px 10px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 } },
            React.createElement('span', { style: { width: 8, height: 8, borderRadius: 4, background: g.meta.color } }),
            React.createElement('span', { style: { fontWeight: 700, fontSize: 12, color: T.text } }, g.meta.label),
            React.createElement('span', { style: { fontSize: 11, color: T.text2 } }, g.items.length + ' 张'),
          ),
          g.items.map(c => React.createElement('div', { key: c.id, style: { background: T.bg2, border: '1px solid ' + T.border, borderRadius: 9, padding: '7px 9px', marginBottom: 5 } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
              React.createElement('span', { style: { fontFamily: 'ui-monospace,monospace', fontSize: 11, fontWeight: 700, color: T.brand } }, c.id),
              React.createElement('span', { style: { fontSize: 10, padding: '1px 7px', borderRadius: 999, border: '1px solid ' + T.border, color: T.text2 } }, LAYER_LABELS[c.layer] || c.layer),
              React.createElement('span', { style: { fontSize: 10, padding: '1px 7px', borderRadius: 999, color: '#fff', background: AUTH_COLORS[c.authorization] || '#6b7280' } }, (c.authorization || '').toUpperCase()),
              c.risk === 'high' ? React.createElement('span', { style: { fontSize: 10, padding: '1px 7px', borderRadius: 999, background: 'color-mix(in srgb, ' + T.error + ' 15%, transparent)', color: T.error } }, 'HIGH') : null,
              React.createElement('span', { style: { marginLeft: 'auto', fontSize: 10, color: T.text2 } }, c.created_at ? relTime(c.created_at) : ''),
            ),
            React.createElement('div', { style: { marginTop: 4, fontSize: 12, color: T.text, lineHeight: 1.45 } }, c.title),
            fmtSignals(c).length ? React.createElement('div', { style: { marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' } },
              fmtSignals(c).map(s => React.createElement('span', { key: s, style: { fontSize: 10, fontFamily: 'ui-monospace,monospace', padding: '1px 7px', borderRadius: 999, background: 'color-mix(in srgb, ' + T.brand + ' 8%, transparent)', color: T.brand } }, s))) : null,
            c.predicted_effect ? React.createElement('div', { style: { marginTop: 4, fontSize: 11, color: T.text2 } },
              '预期：' + ((c.predicted_effect.metric || '') + ' ' + (c.predicted_effect.from || '') + ' → ' + (c.predicted_effect.to || '')).slice(0, 110)) : null,
            c.decisions && c.decisions.length ? React.createElement('div', { style: { marginTop: 4, fontSize: 10, color: T.text2 } },
              'decisions ' + c.decisions.length + ' 条 · ' + c.decisions[c.decisions.length - 1].conclusion.slice(0, 70)) : null,
          )),
        )),
      )
    }

    // ============ 容量热力格 ============
    function CapacityGrid({ capacity }) {
      const nss = Object.keys(capacity || {})
      if (!nss.length) return React.createElement(EmptyBox, { text: '容量数据未生成（build_index 头注缺失）' })
      return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
        nss.map(ns => {
          const cells = capacity[ns]
          const cats = Object.keys(cells)
          return React.createElement('div', { key: ns },
            React.createElement('div', { style: { fontSize: 11, fontWeight: 700, color: T.text, marginBottom: 4, fontFamily: 'ui-monospace,monospace' } }, ns),
            React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
              cats.map(cat => {
                const cell = cells[cat]
                const over = cell.count > cell.cap
                const ratio = cell.cap ? cell.count / cell.cap : 0
                const barColor = over ? T.error : ratio > 0.8 ? T.warn : T.success
                return React.createElement('div', { key: cat, title: (CAT_LABELS[cat] || cat) + ' ' + cell.count + '/' + cell.cap, style: { flex: '1 1 130px', background: T.bg2, border: '1px solid ' + (over ? T.error : T.border), borderRadius: 9, padding: '6px 8px' } },
                  React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
                    React.createElement('span', { style: { fontSize: 11, color: T.text } }, CAT_LABELS[cat] || cat),
                    React.createElement('span', { style: { fontSize: 11, fontWeight: 700, color: over ? T.error : T.text } }, cell.count + '/' + cell.cap),
                  ),
                  React.createElement('div', { style: { marginTop: 4, height: 4, background: 'color-mix(in srgb, ' + T.border + ' 40%, transparent)', borderRadius: 2, overflow: 'hidden' } },
                    React.createElement('div', { style: { width: Math.min(100, ratio * 100) + '%', height: '100%', background: barColor, borderRadius: 2 } }),
                  ),
                  over ? React.createElement('div', { style: { fontSize: 10, color: T.error, marginTop: 3 } }, '超 soft_cap，建议拆分') : null,
                )
              }),
            ),
          )
        }),
      )
    }

    // ============ 台账 / S2 归因 ============
    function TallyView({ tally, s2Attrib }) {
      const hasTally = tally && tally.length
      const hasS2 = s2Attrib && s2Attrib.length
      return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
        React.createElement(Section, { title: '组件失败台账（mis 侧）' },
          hasTally
            ? tally.map(c => React.createElement('div', { key: c.id, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px dashed ' + T.border } },
              React.createElement('span', { style: { fontFamily: 'ui-monospace,monospace', fontSize: 11, color: T.text } }, c.id),
              React.createElement('span', { style: { fontSize: 11, color: T.error, fontWeight: 700 } }, 'mis=' + c.misdiagnoses),
              React.createElement('span', { style: { fontSize: 10, color: T.text2, marginLeft: 'auto' } }, (c.source_traces || []).length + ' 来源'),
            ))
            : React.createElement(EmptyBox, { text: '台账无数据——mis 源待积累（S1 反馈或 S2 replay 路由 miss）' }),
        ),
        React.createElement(Section, { title: 'S2 replay 路由归因（S1 无关）' },
          hasS2
            ? s2Attrib.map((a, i) => React.createElement('div', { key: i, style: { fontSize: 11, color: T.text, padding: '3px 0' } },
              '#' + a.issue + ' → ' + a.component + '：' + (a.note || '') ))
            : React.createElement(EmptyBox, { text: '暂无路由归因（跑 s2_replay --collect 后产生）' }),
        ),
      )
    }

    // ============ Timeline 趋势 ============
    function TimelineTrend({ timeline }) {
      const live = (timeline || []).filter(p => p.kind === 'live')
      const rows = (live.length ? live : timeline || []).slice(-6)
      if (!rows.length) return React.createElement(EmptyBox, { text: 'timeline 无数据' })
      const metric = 'routed_accuracy'
      return React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
        rows.map(p => {
          const v = p[metric]
          return React.createElement('div', { key: p.period, style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 } },
            React.createElement('span', { style: { fontFamily: 'ui-monospace,monospace', color: T.text2, width: 76 } }, p.period),
            React.createElement('span', { style: { color: T.text, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, p.title || ''),
            v !== undefined ? React.createElement('span', { style: { fontWeight: 700, color: T.brand } }, String(v)) : React.createElement('span', { style: { color: T.text2 } }, '—'),
          )
        }),
        React.createElement('div', { style: { fontSize: 10, color: T.text2 } },
          (live.length ? 'live 期趋势' : 'replay/示例参考（live 期不足，不参与趋势）') + ' · 字段 routed_accuracy'),
      )
    }

    // ============ 布局辅助 ============
    function Section({ title, children }) {
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, padding: '10px 12px', boxShadow: '0 1px 2px rgba(0,0,0,.04)' } },
        React.createElement('div', { style: { fontSize: 12, fontWeight: 700, color: T.text, marginBottom: 7 } }, title),
        children,
      )
    }
    function EmptyBox({ text }) {
      return React.createElement('div', { style: { fontSize: 11, color: T.text2, padding: '10px 0' } }, text)
    }

    // ============ 主视图 ============
    function BoardView(props) {
      const sessionId = props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null, error: null })
      const load = React.useCallback(() => {
        setState({ loading: true, data: null, error: null })
        host.call('ev-board-load', { sessionId: sessionId }).then(r => {
          if (r && r.ok) setState({ loading: false, data: r.data, error: null })
          else setState({ loading: false, data: null, error: (r && r.error) || '读取失败' })
        }).catch(e => setState({ loading: false, data: null, error: String(e && e.message || e) }))
      }, [sessionId])

      React.useEffect(() => { load() }, [load])

      return React.createElement('div', { style: { padding: 6 } },
        state.loading ? React.createElement('div', { style: { color: T.text2, fontSize: 12, padding: 20, textAlign: 'center' } }, '加载自演进数据…') :
        state.error ? React.createElement('div', { style: { color: T.error, fontSize: 12, padding: 16 } }, '数据加载失败：' + state.error) :
        React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
            React.createElement('span', { style: { fontSize: 13, fontWeight: 800, color: T.text } }, '自演进看板'),
            React.createElement('span', { style: { fontSize: 11, color: T.text2 } }, 'EV 卡 ' + (state.data.idea_count || 0) + ' · 状态分布 ' + JSON.stringify(state.data.status_count || {})),
            React.createElement('button', { onClick: load, style: { marginLeft: 'auto', background: 'transparent', border: '1px solid ' + T.border, color: T.text2, borderRadius: 999, padding: '2px 12px', fontSize: 11, cursor: 'pointer' } }, '刷新'),
          ),
          React.createElement(Section, { title: 'Idea 卡状态机（candidate → … → validated/rolled_back）' },
            (state.data.ideas || []).length
              ? React.createElement(IdeaBoard, { ideas: state.data.ideas })
              : React.createElement(EmptyBox, { text: '暂无 EV 卡——evolve-check 伴随评估或深度轮产出后出现' }),
          ),
          React.createElement(Section, { title: '知识库容量（_index 头注，soft_cap=30）' },
            React.createElement(CapacityGrid, { capacity: state.data.capacity }),
          ),
          React.createElement(Section, { title: '流程演进信号（台账 / S2 归因）' },
            React.createElement(TallyView, { tally: state.data.tally, s2Attrib: state.data.s2_attrib }),
          ),
          React.createElement(Section, { title: '指标趋势（timeline）' },
            React.createElement(TimelineTrend, { timeline: state.data.timeline }),
          ),
        ),
      )
    }

    slots.inject('conversation.view', () => slots.register(
      { name: 'conversation.view', id: 'ascend-evolve', order: 22, label: '自演进' },
      (props) => React.createElement(BoardView, props),
    ))
  },
}
