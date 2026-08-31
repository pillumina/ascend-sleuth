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
    const statusMeta = {
      resolved: { label: '已解决', color: '#22c55e' },
      in_progress: { label: '进行中', color: '#3b82f6' },
      escalated: { label: '已升级', color: '#f59e0b' },
      unknown: { label: '未知', color: '#9ca3af' },
    }
    const RESUMEABLE = { in_progress: true, escalated: true }
    const sedMeta = {
      none: { label: '未沉淀', color: T.text2 },
      submitted: { label: '已提交待审', color: T.brand },
      knowledge: { label: '已沉淀 · 知识库', color: T.success },
      archived: { label: '已沉淀 · Tier3', color: T.warn },
    }
    const kindMeta = {
      live: { label: 'live', color: T.success, note: '活诊断 · 参与趋势' },
      replay: { label: 'replay', color: '#3b82f6', note: '离线评估 · 不参与趋势' },
      example: { label: 'example', color: T.text2, note: '示例' },
    }
    const METRIC_LABELS = {
      sessions_total: '诊断 session 数', tier2_hit: 'Tier 2 命中',
      misdiagnosis_rate: '误诊率', by_category_hit: '按类命中',
      routed_accuracy: '路由准确率', feedback_capture: '反馈捕获',
      trace_completeness: 'trace 完整性', vocab_compliance: '词表合规',
      reference: 'reference 引用', confidence_distribution: '置信度分布',
      attribution_ratio: '误诊归因比', tier3: 'Tier 3 兜底', reference_detail: 'reference 明细',
      semantic_validation_rate: '语义校验通过', pre_triage: '预分诊',
      candidate_recall: '候选召回', rank_distribution: '命中排名',
      cross_replay_rank1: '交叉回放 rank1', golden_suite: '黄金套件',
      capacity_by_ns: '容量（按命名空间）', case_total: 'case 总数', reference_total: 'reference 总数',
    }
    const CATEGORY_LABELS = { interrupt: 'interrupt', precision: 'precision', performance: 'performance' }

    function copyText(text) {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(() => true).catch(() => fallbackCopy(text))
      }
      return Promise.resolve(fallbackCopy(text))
    }
    function fallbackCopy(text) {
      try {
        const ta = document.createElement('textarea')
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
        document.body.appendChild(ta); ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        return ok
      } catch (e) { return false }
    }
    function relTime(iso) {
      if (!iso) return null
      const t = new Date(iso).getTime()
      if (isNaN(t)) return null
      const diff = Math.max(0, Date.now() - t)
      const m = Math.floor(diff / 60000)
      if (m < 1) return '刚刚'
      if (m < 60) return m + ' 分钟前'
      const h = Math.floor(m / 60)
      if (h < 24) return h + ' 小时前'
      const d = Math.floor(h / 24)
      return d + ' 天前'
    }
    function fmtVal(v) {
      if (v === null || v === undefined) return '—'
      if (typeof v === 'number' || typeof v === 'string') return String(v)
      if (typeof v !== 'object') return String(v)
      const keys = Object.keys(v)
      if (keys.length === 2 && keys.includes('ok') && keys.includes('total')) return v.ok + '/' + v.total
      if (keys.length === 2 && keys.includes('hit') && keys.includes('total')) return v.hit + '/' + v.total
      if (keys.length === 2 && keys.includes('low') && keys.includes('total')) return '低置信 ' + v.low + '/' + v.total
      if (keys.length === 2 && keys.includes('hits') && keys.includes('refs')) return '总命中 ' + v.hits + ' · ref ' + v.refs
      return keys.map(k => k + ' ' + fmtVal(v[k])).join(' · ')
    }
    function ratioTotal(v) {
      if (!v || typeof v !== 'object') return null
      const keys = Object.keys(v)
      if (!((keys.includes('ok') && keys.includes('total')) || (keys.includes('hit') && keys.includes('total')))) return null
      const t = v.total
      return typeof t === 'number' ? t : null
    }
    function pct(a, b) { return b > 0 ? Math.round(a / b * 100) + '%' : '—' }

    const btnBase = { border: 'none', borderRadius: 7, padding: '4px 12px', fontSize: 11, fontWeight: 600, cursor: 'pointer', transition: 'all .15s', letterSpacing: '.01em' }
    const btnPrimary = { ...btnBase, background: 'linear-gradient(135deg,#3b82f6,#2563eb)', color: '#fff', boxShadow: '0 1px 3px rgba(37,99,235,.3)' }
    const btnSuccess = { ...btnBase, background: 'linear-gradient(135deg,#22c55e,#16a34a)', color: '#fff', boxShadow: '0 1px 3px rgba(22,163,74,.3)' }
    const btnPurple = { ...btnBase, background: 'linear-gradient(135deg,#8b5cf6,#7c3aed)', color: '#fff', boxShadow: '0 1px 3px rgba(124,58,237,.3)' }
    const btnGhost = { ...btnBase, background: 'transparent', border: '1px solid ' + T.border, color: T.text2 }
    const btnOutline = (c) => ({ ...btnBase, background: 'transparent', border: '1px solid ' + c, color: c })
    function Dot({ color, size }) {
      return React.createElement('span', { style: { width: size || 8, height: size || 8, borderRadius: 999, background: color, display: 'inline-block', flexShrink: 0 } })
    }
    function Chevron({ open, color }) {
      return React.createElement('span', { style: { width: 0, height: 0, borderLeft: '5px solid ' + (color || T.text2), borderTop: '5px solid transparent', borderBottom: '5px solid transparent', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .18s ease', display: 'inline-block', flexShrink: 0 } })
    }
    function SectionLabel({ children, color }) {
      return React.createElement('div', { style: { fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: color || T.text2, marginBottom: 4 } }, children)
    }
    function MetricRow({ label, value, small, warn }) {
      return React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 8px', background: T.bg2, borderRadius: 7, fontSize: 11, alignItems: 'center' } },
        React.createElement('span', { style: { color: T.text2, whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 5 } },
          label,
          small ? React.createElement('span', { title: '样本量 <5', style: { background: 'color-mix(in srgb, ' + T.warn + ' 14%, transparent)', color: T.warn, borderRadius: 4, padding: '0 5px', fontSize: 9, fontWeight: 600 } }, '小样本') : null,
        ),
        React.createElement('span', { style: { color: warn ? T.warn : T.text, fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' } }, value),
      )
    }

    // ============ 诊断 tab ============
    function SessionCard(props) {
      const s = props.session
      const ownerSessionId = props.sessionId
      const [open, setOpen] = React.useState(false)
      const [steps, setSteps] = React.useState(null)
      const [showCmd, setShowCmd] = React.useState(false)
      const [copied, setCopied] = React.useState(null)
      const [evOpen, setEvOpen] = React.useState(null)
      const [opening, setOpening] = React.useState(null)
      const [sedCmd, setSedCmd] = React.useState(false)
      const meta = statusMeta[s.status] || statusMeta.unknown
      const canResume = RESUMEABLE[s.status]

      function toggle() {
        if (open) { setOpen(false); setSteps(null); setEvOpen(null); return }
        setOpen(true)
        setSteps({ loading: true })
        host.call('ascend-traces-detail', { sessionId: ownerSessionId || null, traceFile: s.file })
          .then(r => setSteps({ loading: false, list: r && r.ok ? r.steps : [], summary: r && r.summary, refCount: r && r.refCount, sedimented: r && r.sedimented, error: r && r.error }))
          .catch(e => setSteps({ loading: false, list: [], error: 'RPC 失败: ' + String(e && e.message || e) }))
      }
      function doCopy(txt, key) { copyText(txt).then(ok => setCopied(ok ? key : 'fail')) }
      function openFile(f) {
        setOpening(f)
        host.call('ascend-open-evidence', { sessionId: ownerSessionId || null, path: f })
          .then(r => { setOpening(null); if (r && r.opened) { setCopied('open:' + f); setTimeout(() => setCopied(null), 2000) } })
          .catch(() => setOpening(null))
      }
      function baseName(f) { return String(f).split('/').pop() }
      function markSed(state) {
        host.call('ascend-update-sedimented', { sessionId: ownerSessionId || null, traceFile: s.file, state, caseId: s.sessionId })
          .then(r => { if (r && r.ok) { setSteps(prev => prev ? { ...prev, sedimented: { state } } : prev) } })
      }

      const rel = relTime(s.updatedAt || s.createdAt)
      const sed = steps && steps.sedimented
      const sedState = sed && sed.state ? sed.state : 'none'
      const sedInfo = sedMeta[sedState] || sedMeta.none
      let body = null
      if (open) {
        if (steps && steps.loading) body = React.createElement('div', { style: { color: T.text2, padding: 10 } }, '加载轨迹…')
        else if (steps && steps.list && steps.list.length) {
          body = React.createElement('div', null,
            steps.summary ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.brand + ' 6%, transparent)', border: '1px solid ' + T.border, borderRadius: 9 } },
              React.createElement(SectionLabel, { color: T.brand }, '问题背景'),
              React.createElement('div', { style: { fontSize: 12, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55 } }, steps.summary),
            ) : null,
            steps.refCount > 0 ? React.createElement('div', { style: { marginBottom: 10, fontSize: 11, color: T.text2, display: 'flex', alignItems: 'center', gap: 6 } },
              React.createElement(Dot, { color: '#8b5cf6' }),
              '本次诊断使用 reference ' + steps.refCount + ' 次') : null,
            React.createElement('div', { style: { marginBottom: 10, padding: 8, border: '1px solid ' + T.border, borderRadius: 9, fontSize: 11, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
              React.createElement('span', { style: { fontWeight: 600, color: T.text2 } }, '沉淀状态'),
              React.createElement('span', { style: { color: sedInfo.color, fontWeight: 600 } }, sedInfo.label),
              sedState === 'none' ? React.createElement('button', { onClick: () => { setSedCmd(!sedCmd); setCopied(null) }, style: btnPurple }, sedCmd ? '隐藏指令' : '沉淀此案例') : null,
              sedState === 'submitted' ? React.createElement(React.Fragment, null,
                React.createElement('button', { onClick: () => markSed('knowledge'), style: btnSuccess }, '已升 Tier 2'),
                React.createElement('button', { onClick: () => markSed('archived'), style: btnOutline(T.warn) }, '仅 Tier 3'),
              ) : null,
              sedState === 'archived' ? React.createElement('button', { onClick: () => markSed('knowledge'), style: btnOutline(T.success) }, '改标 Tier 2') : null,
            ),
            sedCmd && sedState === 'none' ? React.createElement('div', { style: { marginBottom: 10, background: 'color-mix(in srgb, ' + T.brand + ' 8%, transparent)', border: '1px solid ' + T.brand, borderRadius: 9, padding: 8, fontSize: 11 } },
              React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 } },
                React.createElement('span', { style: { color: T.brand, fontWeight: 600 } }, '粘贴到对话即可沉淀'),
                React.createElement('button', { onClick: () => doCopy('用 /skill:to-postmortem 沉淀 ' + s.sessionId + '（症状/根因/fix 在 traces/' + s.file + '，证据在 traces/evidence/）', 'sed'), style: copied === 'fail' ? { ...btnPurple, background: '#ef4444' } : btnPurple },
                  copied === 'sed' ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
              ),
              React.createElement('code', { style: { userSelect: 'all', background: T.bg, border: '1px solid ' + T.border, borderRadius: 6, padding: '5px 8px', display: 'block', fontSize: 11, fontFamily: 'ui-monospace,monospace' } },
                '用 /skill:to-postmortem 沉淀 ' + s.sessionId),
            ) : null,
            steps.list.map((st, i) => {
              const isUser = st.role === 'user'
              const isRef = st.action === 'reference_lookup'
              const ev = st.evidence
              const evOpenHere = evOpen === i
              return React.createElement('div', { key: i, style: { padding: '8px 0 8px 12px', borderLeft: '2px solid ' + (isUser ? T.brand : (isRef ? '#8b5cf6' : T.border)), marginBottom: 3 } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: T.text2, flexWrap: 'wrap' } },
                  React.createElement('span', { style: { fontWeight: 700, color: isUser ? T.brand : T.text } }, isUser ? '用户' : 'Agent'),
                  st.step ? React.createElement('span', { style: { color: T.text2 } }, 'step ' + st.step) : null,
                  st.action ? React.createElement('span', { style: { background: T.bg2, padding: '0 6px', borderRadius: 4, fontFamily: 'ui-monospace,monospace', fontSize: 10, color: T.text2 } }, st.action) : null,
                  isRef ? React.createElement('span', { style: { background: '#8b5cf6', color: '#fff', borderRadius: 999, padding: '0 7px', fontSize: 9, fontWeight: 600 } }, '参考层') : null,
                ),
                st.output ? React.createElement('div', { style: { marginTop: 3, color: T.text, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55 } }, st.output) : null,
                st.reason ? React.createElement('div', { style: { marginTop: 2, color: T.text2, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontStyle: 'italic', lineHeight: 1.5 } },
                  '推理: ' + st.reason) : null,
                st.content ? React.createElement('div', { style: { marginTop: 3, color: T.text2, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55 } }, st.content) : null,
                ev ? React.createElement('div', { style: { marginTop: 4 } },
                  React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, flexWrap: 'wrap' } },
                    React.createElement('span', { style: { color: T.brand, fontWeight: 600 } }, '证据'),
                    ev.inline ? React.createElement('button', { onClick: () => setEvOpen(evOpenHere ? null : i), style: btnGhost }, evOpenHere ? '收起原文' : '原文 ' + ev.inline.length + '字') : null,
                    ev.files && ev.files.length ? React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 4 } },
                      '文件:',
                      ev.files.map(f => React.createElement('button', { key: f, onClick: () => openFile(f), title: f, style: { background: 'transparent', border: 'none', padding: 0, fontSize: 11, cursor: 'pointer', color: T.brand, textDecoration: 'underline', textUnderlineOffset: 2, fontFamily: 'ui-monospace,monospace' } },
                        opening === f ? '打开中…' : baseName(f)),
                    )) : null,
                    ev.missing ? React.createElement('span', { style: { color: T.warn } }, '缺: ' + ev.missing) : null,
                  ),
                  evOpenHere && ev.inline ? React.createElement('pre', { style: { marginTop: 5, background: T.bg, border: '1px solid ' + T.border, borderRadius: 7, padding: 8, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: T.text, lineHeight: 1.5 } }, ev.inline) : null,
                ) : null,
              )
            })
          )
        } else {
          body = React.createElement('div', { style: { color: T.text2, padding: 10 } }, steps && steps.error ? '加载失败: ' + steps.error : '无轨迹步骤')
        }
      }

      let kbTag = null
      if (s.activeCase) {
        kbTag = s.activeCaseInKb
          ? React.createElement('span', { title: '该 case 已在 knowledge/ 中', style: { background: 'color-mix(in srgb, ' + T.success + ' 12%, transparent)', color: T.success, borderRadius: 6, padding: '1px 8px', fontSize: 10, fontWeight: 600, letterSpacing: '.02em' } }, '库中已有')
          : React.createElement('span', { title: '该 case 未入库（新形态待沉淀）', style: { background: 'color-mix(in srgb, ' + T.warn + ' 12%, transparent)', color: T.warn, borderRadius: 6, padding: '1px 8px', fontSize: 10, fontWeight: 600, letterSpacing: '.02em' } }, '新形态')
      }

      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 10, overflow: 'hidden', boxShadow: '0 1px 2px rgba(0,0,0,.04)', transition: 'box-shadow .2s' } },
        React.createElement('div', { onClick: toggle, style: { padding: '12px 16px', cursor: 'pointer' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
            React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 5, color: meta.color, fontSize: 11, fontWeight: 600 } },
              React.createElement(Dot, { color: meta.color }),
              meta.label),
            React.createElement('span', { style: { fontWeight: 700, fontSize: 13, fontFamily: 'ui-monospace,monospace', letterSpacing: '.01em' } }, s.sessionId),
            kbTag,
            React.createElement('span', { style: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 } },
              rel ? React.createElement('span', { style: { color: T.text2, fontSize: 11 } }, '更新 ' + rel) : null,
              React.createElement(Chevron, { open: open }),
            ),
          ),
          React.createElement('div', { style: { color: T.text2, fontSize: 12, marginTop: 4 } },
            [s.framework, s.platform, s.category].filter(Boolean).join(' · ') || '—'),
          s.activeCase ? React.createElement('div', { style: { marginTop: 5, fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement('span', { style: { color: T.text2 } }, '定位'),
            React.createElement('code', { style: { background: 'color-mix(in srgb, ' + T.success + ' 10%, transparent)', color: T.success, padding: '1px 7px', borderRadius: 5, fontSize: 11, fontFamily: 'ui-monospace,monospace' } }, s.activeCase),
          ) : React.createElement('div', { style: { marginTop: 5, color: T.text2, fontSize: 12 } }, '未定位到知识库 case'),
          React.createElement('div', { style: { color: T.text2, fontSize: 12, marginTop: 4 } },
            '轨迹: ' + s.userSteps + ' 用户输入 / ' + s.agentSteps + ' agent 步骤'),
          s.feedbackPending ? React.createElement('div', { style: { color: T.warn, fontSize: 12, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: T.warn }),
            'feedback_pending: ' + s.feedbackPending) : null,
        ),
        canResume ? React.createElement('div', { style: { margin: '0 16px 12px', paddingTop: 9, borderTop: '1px dashed ' + T.border, display: 'flex', alignItems: 'center', gap: 8 } },
          React.createElement('button', { onClick: () => { setShowCmd(!showCmd); setCopied(null) }, style: btnPrimary }, showCmd ? '隐藏指令' : '继续诊断'),
          showCmd ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flex: 1 } },
            React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg, border: '1px solid ' + T.border, borderRadius: 6, padding: '5px 8px', fontSize: 11, fontFamily: 'ui-monospace,monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: T.text } },
              '用 /skill:resume-diagnosis 续接 ' + s.sessionId),
            React.createElement('button', { onClick: () => doCopy('用 /skill:resume-diagnosis 续接 ' + s.sessionId, 'rs'), style: copied === 'fail' ? { ...btnSuccess, background: '#ef4444' } : btnSuccess, title: '复制指令' },
              copied === 'rs' ? '已复制' : '复制'),
          ) : null,
        ) : null,
        body ? React.createElement('div', { style: { padding: '12px 16px', borderTop: '1px solid ' + T.border, background: T.bg2 } }, body) : null,
      )
    }

    function TraceView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null })
      const [query, setQuery] = React.useState('')
      const [kbFilter, setKbFilter] = React.useState('all')
      React.useEffect(() => {
        let alive = true
        host.call('ascend-traces-list', { sessionId: sessionId || null })
          .then(r => { if (alive) setState({ loading: false, data: r }) })
          .catch(() => { if (alive) setState({ loading: false, data: { ok: false, error: 'Host RPC 失败' } }) })
        return () => { alive = false }
      }, [sessionId])

      const base = { fontFamily: 'system-ui,-apple-system,sans-serif', fontSize: 13, color: T.text }
      if (state.loading) return React.createElement('div', { style: { ...base, padding: 16, color: T.text2 } }, '加载诊断状态…')
      const r = state.data
      if (!r || !r.ok) return React.createElement('div', { style: { ...base, padding: 16, color: T.error } }, '无法读取 traces/: ' + (r && r.error || '未知错误'))

      let sessions = r.sessions || []
      const nActive = sessions.filter(s => s.status === 'in_progress').length
      const nPending = sessions.filter(s => s.feedbackPending).length
      const nInKb = sessions.filter(s => s.activeCase && s.activeCaseInKb).length
      const nNew = sessions.filter(s => s.activeCase && !s.activeCaseInKb).length
      const q = query.trim().toLowerCase()
      if (q) {
        sessions = sessions.filter(s =>
          (s.sessionId || '').toLowerCase().includes(q) ||
          (s.status || '').toLowerCase().includes(q) ||
          (s.framework || '').toLowerCase().includes(q) ||
          (s.platform || '').toLowerCase().includes(q) ||
          (s.category || '').toLowerCase().includes(q) ||
          (s.activeCase || '').toLowerCase().includes(q)
        )
      }
      if (kbFilter === 'kb') sessions = sessions.filter(s => s.activeCase && s.activeCaseInKb)
      if (kbFilter === 'new') sessions = sessions.filter(s => s.activeCase && !s.activeCaseInKb)
      if (kbFilter === 'miss') sessions = sessions.filter(s => !s.activeCase)
      const badge = [
        (r.sessions || []).length + ' 会话',
        nInKb ? nInKb + ' 库中已有' : null,
        nNew ? nNew + ' 新形态' : null,
        nActive ? nActive + ' 进行中' : null,
      ].filter(Boolean).join(' · ')
      const kbChips = [
        { id: 'all', label: '全部' },
        { id: 'kb', label: '库中已有' },
        { id: 'new', label: '新形态' },
        { id: 'miss', label: '未定位' },
      ]

      return React.createElement('div', { style: { ...base, padding: 16 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 } },
          React.createElement('div', { style: { fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8, letterSpacing: '.01em' } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'linear-gradient(180deg,#3b82f6,#8b5cf6)', display: 'inline-block' } }),
            'ascend-sleuth 诊断状态'),
          React.createElement('span', { style: { fontSize: 11, color: T.text2, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 999, padding: '2px 10px' } }, badge),
        ),
        React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' } },
          kbChips.map(c => React.createElement('button', { key: c.id, onClick: () => setKbFilter(c.id), style: c.id === kbFilter ? { ...btnPrimary, padding: '3px 12px', borderRadius: 999 } : { ...btnGhost, padding: '3px 12px', borderRadius: 999 } }, c.label)),
        ),
        React.createElement('div', { style: { marginBottom: 10, position: 'relative' } },
          React.createElement('span', { style: { position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', width: 10, height: 10, borderRadius: 999, border: '1.5px solid ' + T.text2, display: 'block' } }),
          React.createElement('input', { placeholder: '搜索 session / 状态 / 框架 / 定位 case…', value: query, onChange: e => setQuery(e.target.value), style: { width: '100%', boxSizing: 'border-box', padding: '7px 10px 7px 28px', fontSize: 12, borderRadius: 8, border: '1px solid ' + T.border, background: T.bg, color: T.text, outline: 'none', transition: 'border-color .15s' } }),
        ),
        sessions.length === 0
          ? React.createElement('div', { style: { color: T.text2, padding: '28px 0', textAlign: 'center', fontSize: 12 } }, q ? '无匹配会话' : 'traces/ 无诊断会话——运行 /skill:diagnose 开始')
          : React.createElement('div', null,
              sessions.map(s => React.createElement(SessionCard, { key: s.file, session: s, sessionId: sessionId })),
            ),
      )
    }

    // ============ 指标 tab ============
    function HealthPanel({ health }) {
      if (!health) return null
      const c = health.cases || {}
      const r = health.references || {}
      const caseRows = []
      if (c.total) caseRows.push(React.createElement(MetricRow, { key: 'ct', label: 'case 总数', value: c.total }))
      if (c.lowConfidence) caseRows.push(React.createElement(MetricRow, { key: 'lc', label: '低置信占比（score<0.5）', value: c.lowConfidence + ' / ' + c.total + ' (' + pct(c.lowConfidence, c.total) + ')', warn: (c.lowConfidence / c.total) > 0.4 }))
      if (c.byCategory && Object.keys(c.byCategory).length) {
        caseRows.push(React.createElement(MetricRow, { key: 'bc', label: 'category 分布', value: Object.keys(c.byCategory).map(k => (CATEGORY_LABELS[k] || k) + ' ' + c.byCategory[k]).join(' · ') }))
      }
      if (c.byNamespace && Object.keys(c.byNamespace).length) {
        Object.keys(c.byNamespace).forEach(ns => {
          const cell = c.byNamespace[ns]
          const over = cell.total > 30
          caseRows.push(React.createElement(MetricRow, { key: 'bn-' + ns, label: '容量 ' + ns.split('/').pop(), value: cell.total + '/30' + (over ? ' 超限' : ''), warn: over }))
        })
      }
      const refRows = []
      if (r.total) refRows.push(React.createElement(MetricRow, { key: 'rt', label: 'reference 总数', value: r.total }))
      if (r.draftCount !== undefined) refRows.push(React.createElement(MetricRow, { key: 'rd', label: '未审草稿（draft）', value: r.draftCount + ' / ' + r.total, warn: r.draftCount > 0 }))
      if (r.staleCount !== undefined) refRows.push(React.createElement(MetricRow, { key: 'rs', label: '过期未核（>90天）', value: r.staleCount, warn: r.staleCount > 0 }))
      if (r.byType && Object.keys(r.byType).length) {
        const top = Object.keys(r.byType).slice(0, 4)
        refRows.push(React.createElement(MetricRow, { key: 'rtp', label: 'type 分布（前 4）', value: top.map(t => t + ' ' + r.byType[t]).join(' · ') }))
      }
      if (r.caseDerivedCount !== undefined) refRows.push(React.createElement(MetricRow, { key: 'rcd', label: 'case 提炼（有来源）', value: r.caseDerivedCount + ' / ' + r.total }))

      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 12, overflow: 'hidden', boxShadow: '0 1px 2px rgba(0,0,0,.04)' } },
        React.createElement('div', { style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'linear-gradient(180deg,#22c55e,#3b82f6)', display: 'inline-block' } }),
            React.createElement('span', { style: { fontSize: 13, fontWeight: 700 } }, '知识库健康'),
          ),
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 12px' } },
            React.createElement('div', null,
              React.createElement(SectionLabel, { color: T.success }, 'case'),
              caseRows,
            ),
            React.createElement('div', null,
              React.createElement(SectionLabel, { color: '#8b5cf6' }, 'reference'),
              refRows,
            ),
          ),
        ),
      )
    }

    function ProcessPanel({ proc }) {
      if (!proc) return null
      const rows = []
      if (proc.total !== undefined) {
        const funnel = '诊断 ' + proc.total + ' → 沉淀 ' + proc.submitted + ' → 转正 ' + proc.promoted
        const funnelWarn = proc.submitted > 0 && proc.promoted === 0
        rows.push(React.createElement(MetricRow, { key: 'pf', label: '沉淀漏斗', value: funnel, warn: funnelWarn, small: proc.total < 5 }))
      }
      if (proc.inProgress !== undefined) {
        const resumeWarn = proc.inProgress > 0 && proc.resumed === 0
        rows.push(React.createElement(MetricRow, { key: 'pr', label: '中断续接', value: '进行中 ' + proc.inProgress + ' · 已续接 ' + proc.resumed, warn: resumeWarn }))
      }
      if (proc.refSessions !== undefined) {
        rows.push(React.createElement(MetricRow, { key: 'prl', label: 'reference 参与', value: proc.refSessions + ' / ' + proc.total + ' session', small: proc.total < 5 }))
      }
      if (!rows.length) return null
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 12, overflow: 'hidden', boxShadow: '0 1px 2px rgba(0,0,0,.04)' } },
        React.createElement('div', { style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'linear-gradient(180deg,#8b5cf6,#3b82f6)', display: 'inline-block' } }),
            React.createElement('span', { style: { fontSize: 13, fontWeight: 700 } }, '流程闭环'),
          ),
          rows,
        ),
      )
    }

    function MetricsView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null })
      const [health, setHealth] = React.useState(null)
      const [proc, setProc] = React.useState(null)
      const [kindFilter, setKindFilter] = React.useState('live')
      const [calc, setCalc] = React.useState(null)
      const [infoOpen, setInfoOpen] = React.useState(false)
      const [fbCmd, setFbCmd] = React.useState(false)
      const [copied, setCopied] = React.useState(null)
      React.useEffect(() => {
        let alive = true
        host.call('ascend-metrics-load', { sessionId: sessionId || null })
          .then(r => { if (alive) setState({ loading: false, data: r }) })
          .catch(() => { if (alive) setState({ loading: false, data: { ok: false, error: 'Host RPC 失败' } }) })
        host.call('ascend-kb-health', { sessionId: sessionId || null })
          .then(r => { if (alive) setHealth(r && r.ok ? r : null) })
          .catch(() => { if (alive) setHealth(null) })
        host.call('ascend-process-health', { sessionId: sessionId || null })
          .then(r => { if (alive) setProc(r && r.ok ? r : null) })
          .catch(() => { if (alive) setProc(null) })
        return () => { alive = false }
      }, [sessionId])

      const base = { fontFamily: 'system-ui,-apple-system,sans-serif', fontSize: 13, color: T.text }
      if (state.loading) return React.createElement('div', { style: { ...base, padding: 16, color: T.text2 } }, '加载指标…')
      const r = state.data
      if (!r || !r.ok) return React.createElement('div', { style: { ...base, padding: 16, color: T.error } }, '无法读取 metrics/timeline.yaml: ' + (r && r.error || '未知错误'))

      const periods = r.periods || []
      const liveCount = periods.filter(p => p.kind === 'live').length
      const order = { live: 0, replay: 1, example: 2 }
      const allShown = [...periods].sort((a, b) => (order[a.kind] ?? 3) - (order[b.kind] ?? 3))
      const shown = kindFilter === 'all' ? allShown : allShown.filter(p => p.kind === kindFilter)
      const filterChips = ['all', 'live', 'replay', 'example']
      const filterLabels = { all: '全部', live: 'live', replay: 'replay', example: 'example' }

      const lastLive = periods.filter(p => p.kind === 'live').slice(-1)[0] || null
      let feedbackAlert = null
      if (lastLive && lastLive.metrics) {
        const fb = lastLive.metrics.feedback_capture
        const hits = lastLive.metrics.tier2_hit
        if (fb && typeof fb === 'object' && (fb.resolved === 0 || fb.resolved === undefined) && (fb.not_resolved === 0 || fb.not_resolved === undefined) && (fb.partial === 0 || fb.partial === undefined) && hits > 0) {
          const fbCmdText = '回报 fix 结果：请逐个确认 traces/ 中已定位 case 的 session（含 feedback_pending 的）fix 应用后是否解决，按 resolved / not_resolved / partial 回报并写 feedback 事件（trace_metrics 据此更新误诊率/confidence）'
          feedbackAlert = React.createElement('div', { style: { marginBottom: 12, border: '1px solid ' + T.warn, borderRadius: 9, overflow: 'hidden' } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)' } },
              React.createElement(Dot, { color: T.warn }),
              React.createElement('span', { style: { fontSize: 11, fontWeight: 700, color: T.warn, whiteSpace: 'nowrap' } }, '反馈未回报'),
              React.createElement('span', { style: { fontSize: 11, color: T.text, flex: 1 } },
                hits + ' 个 Tier 2 命中未回报 fix 结果，confidence 与误诊归因无法更新'),
              React.createElement('button', { onClick: () => { setFbCmd(!fbCmd); setCopied(null) }, style: fbCmd ? btnPurple : btnGhost }, fbCmd ? '隐藏指令' : '回报'),
            ),
            fbCmd ? React.createElement('div', { style: { padding: '8px 12px', background: T.bg, borderTop: '1px solid ' + T.warn, fontSize: 11 } },
              React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 } },
                React.createElement('span', { style: { color: T.warn, fontWeight: 600 } }, '粘贴到对话即可触发回报'),
                React.createElement('button', { onClick: () => doCopy(fbCmdText, 'fb'), style: copied === 'fail' ? { ...btnPurple, background: '#ef4444' } : btnPurple },
                  copied === 'fb' ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
              ),
              React.createElement('code', { style: { userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 6, padding: '5px 8px', display: 'block', fontSize: 11, fontFamily: 'ui-monospace,monospace' } },
                fbCmdText),
            ) : null,
          )
        }
      }

      function doCopy(txt, key) { copyText(txt).then(ok => setCopied(ok ? key : 'fail')) }

      function runCalc() {
        setCalc({ busy: true })
        host.call('ascend-metrics-live', { sessionId: sessionId || null })
          .then(rr => setCalc({ busy: false, data: rr }))
          .catch(e => setCalc({ busy: false, data: { ok: false, error: 'RPC 失败: ' + String(e && e.message || e) } }))
      }

      const hasTraceDebt = proc && proc.total > 0

      return React.createElement('div', { style: { ...base, padding: 16 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 } },
          React.createElement('div', { style: { fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'linear-gradient(180deg,#22c55e,#3b82f6)', display: 'inline-block' } }),
            'ascend-sleuth 指标'),
          React.createElement('span', { style: { fontSize: 11, color: T.text2, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 999, padding: '2px 10px' } },
            periods.length + ' 期 · live ' + liveCount),
        ),
        hasTraceDebt ? React.createElement('div', { style: { marginBottom: 10 } },
          React.createElement('button', { onClick: () => setInfoOpen(!infoOpen), style: { background: 'transparent', border: 'none', padding: 0, fontSize: 10, color: T.text2, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 } },
            React.createElement(Chevron, { open: infoOpen, color: T.text2 }),
            '数据说明',
          ),
          infoOpen ? React.createElement('div', { style: { marginTop: 6, padding: '8px 10px', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 8, fontSize: 10, color: T.text2, lineHeight: 1.6 } },
            '早期诊断（2026-08 前）未记录 feedback / attribution / tier3 / triage_semantic 事件，相关指标（反馈捕获、误诊归因、Tier3 兜底）为该缺失所致，非真实水平。新诊断起完整记录，欠账随新 trace 稀释。',
          ) : null,
        ) : null,
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 12, alignItems: 'start' } },
          React.createElement(HealthPanel, { health: health }),
          React.createElement(ProcessPanel, { proc: proc }),
        ),
        feedbackAlert,
        React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' } },
          filterChips.map(k => React.createElement('button', { key: k, onClick: () => setKindFilter(k), style: k === kindFilter ? { ...btnPrimary, padding: '3px 12px', borderRadius: 999 } : { ...btnGhost, padding: '3px 12px', borderRadius: 999 } }, filterLabels[k])),
        ),
        liveCount === 0 ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.border, borderRadius: 9, fontSize: 12, color: T.text2 } },
          '尚无 live 快照。首次活诊断后由 owner 追加（docs/metrics.md 汇总职责）。') : null,
        shown.length === 0 ? React.createElement('div', { style: { color: T.text2, padding: '24px 0', textAlign: 'center', fontSize: 12 } }, '无该类型快照')
          : React.createElement('div', null, shown.map((p, i) => {
            const km = kindMeta[p.kind] || kindMeta.example
            const metricKeys = Object.keys(p.metrics || {})
            return React.createElement('div', { key: p.period + '-' + i, style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 10, overflow: 'hidden', boxShadow: '0 1px 2px rgba(0,0,0,.04)' } },
              React.createElement('div', { style: { padding: '12px 16px' } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
                  React.createElement('span', { style: { color: km.color, border: '1px solid ' + km.color, borderRadius: 999, padding: '1px 10px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em' } }, km.label),
                  React.createElement('span', { style: { fontWeight: 700, fontSize: 13, fontFamily: 'ui-monospace,monospace' } }, p.period),
                  p.recorded_at ? React.createElement('span', { style: { color: T.text2, fontSize: 11 } }, '记录 ' + p.recorded_at) : null,
                ),
                km.note ? React.createElement('div', { style: { color: T.text2, fontSize: 10, marginTop: 3, fontStyle: 'italic' } }, km.note) : null,
                p.title ? React.createElement('div', { style: { color: T.text, fontSize: 12, marginTop: 5, lineHeight: 1.5 } }, p.title) : null,
                p.source ? React.createElement('div', { style: { color: T.text2, fontSize: 11, marginTop: 3, wordBreak: 'break-word', lineHeight: 1.5 } }, '来源: ' + p.source) : null,
                metricKeys.length ? React.createElement('div', { style: { marginTop: 9, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 12px' } },
                  metricKeys.map(k => {
                    const v = p.metrics[k]
                    const total = ratioTotal(v)
                    const small = total !== null && total > 0 && total < 5
                    return React.createElement(MetricRow, { key: k, label: METRIC_LABELS[k] || k, value: fmtVal(v), small: small })
                  }),
                ) : null,
                p.notes && p.notes.trim() ? React.createElement('div', { style: { marginTop: 9, padding: '7px 10px', background: 'color-mix(in srgb, ' + T.brand + ' 5%, transparent)', borderLeft: '3px solid ' + T.brand, borderRadius: 5, fontSize: 11, color: T.text2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.55 } },
                  p.notes.trim()) : null,
              ),
            )
          })),
        React.createElement('div', { style: { marginTop: 14, paddingTop: 10, borderTop: '1px dashed ' + T.border, fontSize: 11, color: T.text2 } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 } },
            React.createElement('span', { style: { fontWeight: 700, color: T.text } }, '实时计算'),
            React.createElement('span', null, '运行 trace_metrics.py 计算当前指标（与 timeline 对照）'),
            React.createElement('button', { onClick: runCalc, disabled: !!(calc && calc.busy), style: { ...btnGhost, marginLeft: 'auto' } }, calc && calc.busy ? '计算中…' : '运行'),
          ),
          calc && !calc.busy && calc.data ? (
            calc.data.ok
              ? React.createElement('pre', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 9, padding: 10, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: T.text, maxHeight: 320, overflowY: 'auto', lineHeight: 1.5 } }, calc.data.output)
              : React.createElement('div', { style: { color: T.error } }, calc.data.error || '计算失败')
          ) : null,
        ),
      )
    }

    slots.inject('conversation.view', () => slots.register(
      { name: 'conversation.view', id: 'ascend-diagnose', order: 20, label: '诊断' },
      (props) => React.createElement(TraceView, props),
    ))
    slots.inject('conversation.view', () => slots.register(
      { name: 'conversation.view', id: 'ascend-metrics', order: 21, label: '指标' },
      (props) => React.createElement(MetricsView, props),
    ))
  },
}