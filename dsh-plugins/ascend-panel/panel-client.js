return {
  apply(ctx) {
    const slots = ctx.get('slots')
    if (slots === undefined) return
    // 动态客户端包内**没有全局定时器**（`setTimeout` 一调就抛「browser timer globals are unavailable
    // in dynamic packages」）。要延时只能走注入的 timer 服务（Client Service `timer`：
    // `timeout(cb, ms) -> disposer`）。这里用 ctx.get 而不是 `inject: ['timer']`：后者会让整个面板
    // 在该服务缺席时进入 waiting（一个"2 秒后清掉提示"的功能不该拖垮面板）；
    // 服务缺席时降级为"提示不复位"，绝不退回全局定时器。
    const timer = ctx.get('timer')

    const T = {
      bg: 'var(--dsw-alias-bg-layer-1)', bg2: 'var(--dsw-alias-bg-layer-2)',
      border: 'var(--dsw-alias-border-l1)', text: 'var(--dsw-alias-label-primary)',
      text2: 'var(--dsw-alias-label-secondary)', brand: 'var(--dsw-alias-brand-primary)',
      success: 'var(--dsw-alias-state-success-primary)', warn: 'var(--dsw-alias-state-warn-primary)',
      error: 'var(--dsw-alias-state-error-primary)',
    }

    // 面板统一色语（与 ev-panel 同一套角色，见 scripts/check_panel_tokens.py）：
    //   --c-*   文字色（深一档同色相，过 WCAG AA——本面板原先直接用亮色当文字，
    //           绿 2.28:1 / 琥珀 2.15:1 都不达标）
    //   --acc-* 装饰色（点/条/边框/渐变——大块面，两面板共用同一亮色）
    //   --btn-* 渐变按钮（白字，压深一档才过 AA）
    const PANEL_CSS = `
:root{
  /* ── 字体（2026-09 五轮）──────────────────────────────────────────────
     栈：system-ui 打头（各平台原生 UI 字体）→ Windows 现代 UI → 无衬线兜底。
     为什么这么排：面板要跟宿主界面同气，而 system-ui 在不同平台自动落到
     SF Pro / Segoe UI Variable / Noto Sans；中文字形交给系统的 PingFang / 微软雅黑 UI。
     不做 web font：网络字体在离线/内网环境会闪烁或失败，且中文子集动辄几 MB。 */
  --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI Variable Text","Segoe UI Variable","Segoe UI",system-ui,"PingFang SC","HarmonyOS Sans SC","Noto Sans SC","Microsoft YaHei UI","Microsoft YaHei",sans-serif;
  --font-mono:ui-monospace,SFMono-Regular,"SF Mono",Cascadia Mono,"Cascadia Code",Consolas,"Liberation Mono",monospace;
  --font-num:"SF Mono",ui-monospace,SFMono-Regular,Cascadia Mono,Consolas,monospace;

  /* ── 字号尺度（8 档，替代原先 9 档却只差 3.5px 的"无尺度"）───────────
     基准 14.5：面板信息密度高，而中文在 11–12px 下笔画会糊。
     用法：内联值只允许取这 8 档（回归闸门会拦新档位——实测加了两处新 UI 就漂到 9 档）。 */
  --t-md2:10.5px;     /* 徽章、角标 */
  --t-tiny:11.5px;    /* chip、时间戳、覆盖计数 */
  --t-sm:12.5px;      /* 密集行、注释、未展开的摘要 */
  --t-base:14.5px;    /* 正文、判据行、会话卡正文 */
  --t-md:13.5px;      /* 卡片正文/行主体（介于 sm 与 base 之间的密集正文） */
  --t-lg:15px;        /* 区块标题、卡片主标题 */
  --t-xl:16.5px;      /* 主数值（case/容量大数） */
  --t-2xl:18px;       /* 视图标题 */

  /* ── 行高：中文需要更松（1.5 会挤；西文 1.5 够，中文不够）────────── */
  --lh-tight:1.35;
  --lh-base:1.6;
  --lh-prose:1.75;

  --c-blue:#1d4ed8;--c-green:#15803d;--c-purple:#7c3aed;--c-amber:#92400e;--c-red:#b91c1c;--c-gray:#64748b;
  --acc-blue:#3b82f6;--acc-green:#22c55e;--acc-purple:#8b5cf6;--acc-amber:#f59e0b;--acc-red:#ef4444;--acc-gray:#9ca3af;
  --d-blue:#1d4ed8;--d-green:#15803d;--d-amber:#92400e;--d-red:#b91c1c;--d-purple:#6d28d9;
  --btn-blue-a:#2563eb;--btn-blue-b:#1d4ed8;--btn-green-a:#16a34a;--btn-green-b:#15803d;
  --btn-purple-a:#7c3aed;--btn-purple-b:#6d28d9;--btn-red-a:#dc2626;--btn-red-b:#b91c1c;
  --tint-blue:color-mix(in srgb, var(--d-blue) 9%, transparent);
  --tint-red:color-mix(in srgb, var(--d-red) 8%, transparent);
  --tint-amber:color-mix(in srgb, var(--d-amber) 9%, transparent);
  --tint-purple:color-mix(in srgb, var(--c-purple) 9%, transparent);
  --tint-green:color-mix(in srgb, var(--d-green) 9%, transparent);
  --surf:linear-gradient(rgba(15,23,42,.022),rgba(15,23,42,.022));
  --hair:color-mix(in srgb, var(--dsw-alias-label-primary) 9%, transparent);
  /* 现代观感的三件套：双层柔和阴影（近处紧、远处散）+ 圆角尺度 */
  --elev-1:0 1px 2px rgba(15,23,42,.04),0 1px 1px rgba(15,23,42,.03);
  --elev-2:0 1px 2px rgba(15,23,42,.05),0 4px 12px -6px rgba(15,23,42,.10);
  --r-sm:7px;--r-md:10px;--r-lg:13px}
body[data-ds-dark-theme] :root{--c-blue:#7db3fc;--c-green:#5cd68f;--c-purple:#b39bfb;--c-amber:#fbbf24;--c-red:#fb8a8a;--c-gray:#a8b0bd;
  --acc-blue:#60a5fa;--acc-green:#4ade80;--acc-purple:#a78bfa;--acc-amber:#fbbf24;--acc-red:#f87171;--acc-gray:#9ca3af;
  --d-blue:#7db3fc;--d-green:#5cd68f;--d-amber:#fbbf24;--d-red:#fb8a8a;--d-purple:#b39bfb;
  --tint-blue:color-mix(in srgb, var(--d-blue) 16%, transparent);
  --tint-red:color-mix(in srgb, var(--d-red) 15%, transparent);
  --tint-amber:color-mix(in srgb, var(--d-amber) 16%, transparent);
  --tint-purple:color-mix(in srgb, var(--d-purple) 16%, transparent);
  --tint-green:color-mix(in srgb, var(--d-green) 15%, transparent);
  --elev-1:0 1px 2px rgba(0,0,0,.30),0 1px 1px rgba(0,0,0,.20);
  --elev-2:0 1px 2px rgba(0,0,0,.35),0 6px 16px -8px rgba(0,0,0,.45);
  --surf:none}
/* 面板根：字体与排版的唯一落点（组件里不再各写各的 fontFamily） */
.sleu{font-family:var(--font-sans);font-size:var(--t-base);line-height:var(--lh-base);color:var(--dsw-alias-label-primary);
  font-feature-settings:"tnum" 1,"cv05" 1;font-optical-sizing:auto;letter-spacing:.006em;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
/* 数字一律等宽对齐（指标/容量/期号同列可比） */
.sleu-num{font-family:var(--font-num);font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;letter-spacing:-.01em}
.sleu-mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
/* 中英混排微调：中文行更高的 readability，标题收紧字距（现代排版惯例） */
.sleu-title{font-size:var(--t-lg);font-weight:650;letter-spacing:-.012em;line-height:var(--lh-tight)}
.sleu-prose{line-height:var(--lh-prose)}
@keyframes sleuRise{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
/* 交互反馈：hover/active 有分寸（现代观感来自"响应"而非"装饰"） */
.sleu-row{transition:background .14s cubic-bezier(.22,1,.36,1)}
.sleu-row:hover{background:var(--tint-blue)}
.sleu-row:active{background:color-mix(in srgb,var(--d-blue) 14%,transparent)}
.sleu-card{transition:box-shadow .18s cubic-bezier(.22,1,.36,1),border-color .18s cubic-bezier(.22,1,.36,1)}
.sleu-card:hover{box-shadow:var(--elev-2)}
.sleu-chip{transition:background .14s cubic-bezier(.22,1,.36,1),border-color .14s cubic-bezier(.22,1,.36,1)}
.sleu-chip:hover{border-color:var(--d-blue);color:var(--d-blue)}
/* 迷你趋势条（与 ev-panel 的 .ev-bars 同一套 CSS 条形原语，不用 SVG——两面板视觉语言一致） */
.sleu-bars{display:flex;align-items:flex-end;gap:2px;height:18px;flex-shrink:0}
.sleu-bar{width:5px;border-radius:2px 2px 1px 1px;background:var(--acc-blue);opacity:.9;transition:opacity .15s cubic-bezier(.22,1,.36,1),height .2s cubic-bezier(.22,1,.36,1)}
.sleu-bar.dim{background:var(--acc-gray);opacity:.45}
.sleu-bar.miss{background:transparent;border-bottom:1px dashed var(--dsw-alias-border-l1)}
.sleu-bars:hover .sleu-bar{opacity:1}
/* 轨迹时间轴：左侧刻度点 + 竖轨（"第几步"要能一眼数出来），滑过时刻度点亮 */
.sleu-tl-row{display:flex;gap:10px;align-items:stretch}
.sleu-tl-mk{width:14px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;padding-top:5px}
.sleu-tl-dot{width:7px;height:7px;border-radius:999px;background:var(--bd,var(--dsw-alias-border-l1));flex-shrink:0;transition:transform .16s cubic-bezier(.22,1,.36,1),background .16s}
.sleu-tl-rail{flex:1;width:1.5px;background:var(--dsw-alias-border-l1);margin-top:3px;border-radius:1px}
.sleu-tl-row:hover .sleu-tl-dot{transform:scale(1.35)}
.sleu-tl-row:hover .sleu-tl-rail{background:color-mix(in srgb,var(--d-blue) 35%,transparent)}
.sleu-fab{position:sticky;bottom:10px;margin-left:auto;width:34px;height:34px;border-radius:999px;border:1px solid var(--hair);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-secondary);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;line-height:1;box-shadow:var(--elev-2);transition:transform .16s cubic-bezier(.22,1,.36,1),color .16s}
.sleu-fab:hover{transform:translateY(-2px);color:var(--d-blue)}
@media (prefers-reduced-motion: reduce){*{animation-duration:.001ms !important;transition-duration:.001ms !important}}
`
    const tokenSheet = styles.insert(PANEL_CSS)

    const statusMeta = {
      resolved: { label: '已解决', color: 'var(--c-green)', acc: 'var(--acc-green)' },
      in_progress: { label: '进行中', color: 'var(--c-blue)', acc: 'var(--acc-blue)' },
      escalated: { label: '已升级', color: 'var(--c-amber)', acc: 'var(--acc-amber)' },
      unknown: { label: '未知', color: 'var(--c-gray)', acc: 'var(--acc-gray)' },
    }
    const RESUMEABLE = { in_progress: true, escalated: true }
    const sedMeta = {
      none: { label: '未沉淀', color: T.text2 },
      submitted: { label: '已提交待审', color: 'var(--c-blue)' },
      knowledge: { label: '已沉淀 · 知识库', color: 'var(--c-green)' },
      archived: { label: '已沉淀 · Tier3', color: 'var(--c-amber)' },
    }
    const kindMeta = {
      live: { label: 'live', color: 'var(--c-green)', acc: 'var(--acc-green)', note: '活诊断 · 参与趋势' },
      replay: { label: 'replay', color: 'var(--c-blue)', acc: 'var(--acc-blue)', note: '离线评估 · 不参与趋势' },
      example: { label: 'example', color: T.text2, acc: 'var(--acc-gray)', note: '示例' },
    }
    const METRIC_LABELS = {
      sessions_total: '诊断次数', tier2_hit: '知识库命中',
      misdiagnosis_rate: '误诊率', by_category_hit: '按类命中',
      routed_accuracy: '路由准确率', feedback_capture: '反馈捕获',
      trace_completeness: 'trace 完整性', vocab_compliance: '词表合规',
      reference: 'reference 引用', confidence_distribution: '置信度分布',
      attribution_ratio: '误诊归因比', tier3: '未命中兜底', reference_detail: 'reference 明细',
      semantic_validation_rate: '语义校验通过', pre_triage: '预分诊',
      candidate_recall: '候选覆盖', rank_distribution: '命中排名',
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
    // 提示态延时复位（"已复制"/"已打开"这类 2 秒提示）：走注入的 timer 服务，不用全局 setTimeout
    // （动态客户端包里没有它）。timer 缺席 → 只置位不复位，功能可用、不抛错。
    function flashState(setter, value, ms) {
      setter(value)
      if (timer && typeof timer.timeout === 'function') timer.timeout(() => setter(null), ms)
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

    // 指标值 → {text, num, rate}：变化对照用（rate = ok/total 或 hit/total 的比率）
    function metricValue(v) {
      if (v === null || v === undefined) return { text: '—', num: null, rate: null }
      if (typeof v === 'number') return { text: String(v), num: v, rate: null }
      if (typeof v !== 'object') return { text: String(v), num: null, rate: null }
      const keys = Object.keys(v)
      if (keys.includes('ok') && keys.includes('total') && typeof v.total === 'number') {
        return { text: v.ok + '/' + v.total, num: v.ok, rate: v.total > 0 ? v.ok / v.total : null }
      }
      if (keys.includes('hit') && keys.includes('total') && typeof v.total === 'number') {
        return { text: v.hit + '/' + v.total, num: v.hit, rate: v.total > 0 ? v.hit / v.total : null }
      }
      if (keys.includes('before') && keys.includes('after')) {
        return { text: v.before + ' → ' + v.after, num: v.after, rate: null }
      }
      return { text: fmtVal(v), num: null, rate: null }
    }

    // 两期对照：只保留"动了"的指标（新增 / 变化），这是"本期发生了什么"的答案
    function diffPeriods(prev, cur) {
      if (!cur) return { moved: [], same: 0, prevPeriod: null, curPeriod: null }
      const pm = (prev && prev.metrics) || {}
      const cm = cur.metrics || {}
      const moved = []
      let same = 0
      Object.keys(cm).forEach(k => {
        const a = k in pm ? metricValue(pm[k]) : null
        const b = metricValue(cm[k])
        const label = METRIC_LABELS[k] || k
        if (a === null) { moved.push({ key: k, label, kind: 'new', to: b.text }); return }
        // 数值可比值优先比数值；否则比显示文本
        const changed = (a.num !== null && b.num !== null) ? a.num !== b.num : a.text !== b.text
        if (changed) moved.push({ key: k, label, kind: 'change', from: a.text, to: b.text, delta: (a.num !== null && b.num !== null) ? b.num - a.num : null })
        else same++
      })
      // 上期有、本期没有的指标 = 本期不再采集
      Object.keys(pm).forEach(k => {
        if (!(k in cm)) moved.push({ key: k, label: METRIC_LABELS[k] || k, kind: 'gone', from: metricValue(pm[k]).text })
      })
      return { moved, same, prevPeriod: prev ? prev.period : null, curPeriod: cur.period }
    }

    const btnBase = { border: 'none', borderRadius: 7, padding: '4px 12px', fontSize: 11.5, fontWeight: 600, cursor: 'pointer', transition: 'all .15s', letterSpacing: '.01em' }
    const btnPrimary = { ...btnBase, background: 'linear-gradient(135deg,var(--btn-blue-a),var(--btn-blue-b))', color: '#fff', boxShadow: '0 1px 3px rgba(37,99,235,.3)' }
    const btnSuccess = { ...btnBase, background: 'linear-gradient(135deg,var(--btn-green-a),var(--btn-green-b))', color: '#fff', boxShadow: '0 1px 3px rgba(22,163,74,.3)' }
    const btnPurple = { ...btnBase, background: 'linear-gradient(135deg,var(--btn-purple-a),var(--btn-purple-b))', color: '#fff', boxShadow: '0 1px 3px rgba(124,58,237,.3)' }
    const btnGhost = { ...btnBase, background: 'transparent', border: '1px solid ' + T.border, color: T.text2 }
    // 与判据同语义的按钮（动作要与它所属的判据同色，否则读者还得再对一次）
    const btnRed = { ...btnBase, background: 'linear-gradient(135deg,#dc2626,#b91c1c)', color: '#fff', boxShadow: '0 1px 3px rgba(185,28,28,.28)' }
    const btnOutline = (c) => ({ ...btnBase, background: 'transparent', border: '1px solid ' + c, color: c })
    // 指标行上的小徽章（小样本 / 不可解读 / 超限）：同一形态，颜色按语义传
    // 用 --d-*（同色相深档）而不是直接拿 --acc-* 当文字色——后者在亮色下 2.15–2.28:1，
    // 既"尖锐"又不过 AA；深浅两套主题各自声明，面板不再各写各的色值。
    function tinyBadge(colorVar) {
      return { background: 'color-mix(in srgb, ' + colorVar + ' 12%, transparent)', color: colorVar, borderRadius: 4, padding: '1px 6px', fontSize: 10.5, fontWeight: 600, whiteSpace: 'nowrap', lineHeight: '15px' }
    }
    // 面板动效（与 ev-panel 同族）：120–260ms ease-out-quart；reduced-motion 下置 0 关闭
    const EASE = 'cubic-bezier(.22,1,.36,1)'
    const REDUCED = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false
    const DUR = REDUCED ? 0 : 1
    // 首屏区块依次浮现（EV 记的 M6：把"顺序"本身作为视觉信息）；reduced-motion 下不动
    function rise(i) {
      return DUR ? { animation: 'sleuRise .26s ' + EASE + ' both', animationDelay: (i * 40) + 'ms' } : {}
    }
    // 实心胶囊（结论性标签）；大块面用装饰色，文字用深档（AA）
    function pill(text, color) {
      return React.createElement('span', { style: { color: color, border: '1px solid ' + color, borderRadius: 999, padding: '1px 9px', fontSize: 11.5, fontWeight: 700, whiteSpace: 'nowrap' } }, text)
    }
    function Dot({ color, size }) {
      return React.createElement('span', { style: { width: size || 8, height: size || 8, borderRadius: 999, background: color, display: 'inline-block', flexShrink: 0 } })
    }
    function Chevron({ open, color }) {
      return React.createElement('span', { style: { width: 0, height: 0, borderLeft: '5px solid ' + (color || T.text2), borderTop: '5px solid transparent', borderBottom: '5px solid transparent', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .18s ease', display: 'inline-block', flexShrink: 0 } })
    }
    function SectionLabel({ children, color }) {
      return React.createElement('div', { style: { fontSize: 12.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.08em', color: color || T.text2, marginBottom: 4 } }, children)
    }
    // 指标行：value 可带"不可解读"标记——分母为 0 的指标不能安静地显示成 0
    // （gates.yaml 的 readability 判据，由 metrics_health.py 判定、host 透传到这里）。
    // 另有两类载荷：{ total, sub } 让大数当主角（容量），{ node } 承载徽章行。
    function MetricRow({ label, value, small, warn, unreadable, unreadableWhy, total, sub, node }) {
      const hasStruct = (total !== undefined && total !== null) || node !== undefined
      const body = hasStruct
        ? React.createElement('div', { style: { minWidth: 0 } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 7, flexWrap: 'wrap' } },
              React.createElement('span', { style: { color: T.text2, fontSize: 12.5 } }, label),
              total !== undefined && total !== null ? React.createElement('span', { style: { fontSize: 16.5, fontWeight: 700, fontFamily: 'var(--font-mono)', color: warn ? T.warn : T.text, letterSpacing: '-.01em' } }, total) : null,
              small ? React.createElement('span', { title: '样本量 <5', style: tinyBadge('var(--d-amber)') }, '小样本') : null,
              unreadable ? React.createElement('span', { title: unreadableWhy || '分母为 0：这个数不可解读', style: tinyBadge('var(--d-purple)') }, '不可解读') : null,
              warn && !unreadable ? React.createElement('span', { style: tinyBadge('var(--d-amber)') }, '超限') : null,
            ),
            sub ? React.createElement('div', { style: { color: T.text2, fontSize: 11.5, marginTop: 2, lineHeight: 1.45, wordBreak: 'break-word' } }, sub) : null,
            node || null,
          )
        : React.createElement(React.Fragment, null,
            React.createElement('span', { style: { color: T.text2, whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 5 } },
              label,
              small ? React.createElement('span', { title: '样本量 <5', style: tinyBadge('var(--d-amber)') }, '小样本') : null,
              unreadable ? React.createElement('span', { title: unreadableWhy || '分母为 0：这个数不可解读', style: tinyBadge('var(--d-purple)') }, '不可解读') : null,
            ),
            React.createElement('span', { style: { color: warn ? T.warn : (unreadable ? T.text2 : T.text), fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' } }, value),
          )
      return React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 8px', background: T.bg2, borderRadius: 7, fontSize: 13.5, alignItems: hasStruct ? 'center' : 'center', opacity: unreadable ? 0.72 : 1 } },
        hasStruct ? React.createElement('div', { style: { display: 'flex', gap: 9, alignItems: 'center', width: '100%' } }, React.createElement(Dot, { color: warn ? T.warn : (unreadable ? 'var(--acc-purple)' : 'var(--acc-green)') }), body) : body,
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
      const [openErr, setOpenErr] = React.useState(null)
      const [openVia, setOpenVia] = React.useState(null)
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
        setOpenErr(null)
        host.call('ascend-open-evidence', { sessionId: ownerSessionId || null, path: f })
          .then(r => {
            setOpening(null)
            if (r && r.opened) { setOpenVia(r.via ? String(r.via) : ''); flashState(setCopied, 'open:' + f, 3000) }
            // 静默失败等于"点了没反应"：把原因显出来（旧版这里直接 reset，用户只能猜）
            else setOpenErr((r && r.error) ? String(r.error) : '打开失败（无返回）')
          })
          .catch(e => { setOpening(null); setOpenErr('RPC 失败: ' + String(e && e.message || e)) })
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
              React.createElement('div', { style: { fontSize: 13.5, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.68 } }, steps.summary),
            ) : null,
            steps.refCount > 0 ? React.createElement('div', { style: { marginBottom: 10, fontSize: 12.5, color: T.text2, display: 'flex', alignItems: 'center', gap: 6 } },
              React.createElement(Dot, { color: 'var(--acc-purple)' }),
              '本次诊断使用 reference ' + steps.refCount + ' 次') : null,
            React.createElement('div', { style: { marginBottom: 10, padding: 8, border: '1px solid ' + T.border, borderRadius: 9, fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
              React.createElement('span', { style: { fontWeight: 600, color: T.text2 } }, '沉淀状态'),
              React.createElement('span', { style: { color: sedInfo.color, fontWeight: 600 } }, sedInfo.label),
              sedState === 'none' ? React.createElement('button', { onClick: () => { setSedCmd(!sedCmd); setCopied(null) }, style: btnPurple }, sedCmd ? '隐藏指令' : '沉淀此案例') : null,
              sedState === 'submitted' ? React.createElement(React.Fragment, null,
                React.createElement('button', { onClick: () => markSed('knowledge'), style: btnSuccess }, '已升 Tier 2'),
                React.createElement('button', { onClick: () => markSed('archived'), style: btnOutline(T.warn) }, '仅 Tier 3'),
              ) : null,
              sedState === 'archived' ? React.createElement('button', { onClick: () => markSed('knowledge'), style: btnOutline(T.success) }, '改标 Tier 2') : null,
            ),
            sedCmd && sedState === 'none' ? React.createElement('div', { style: { marginBottom: 10, background: 'color-mix(in srgb, ' + T.brand + ' 8%, transparent)', border: '1px solid ' + T.brand, borderRadius: 9, padding: 8, fontSize: 12.5 } },
              React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 } },
                React.createElement('span', { style: { color: T.brand, fontWeight: 600 } }, '粘贴到对话即可沉淀'),
                React.createElement('button', { onClick: () => doCopy('用 /skill:to-postmortem 沉淀 ' + s.sessionId + '（症状/根因/fix 在 traces/' + s.file + '，证据在 traces/evidence/）', 'sed'), style: copied === 'fail' ? { ...btnRed, background: 'var(--d-red)' } : btnPurple },
                  copied === 'sed' ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
              ),
              React.createElement('code', { style: { userSelect: 'all', background: T.bg, border: '1px solid ' + T.border, borderRadius: 6, padding: '5px 8px', display: 'block', fontSize: 12.5, fontFamily: 'var(--font-mono)' } },
                '用 /skill:to-postmortem 沉淀 ' + s.sessionId),
            ) : null,
            steps.list.map((st, i) => {
              const isUser = st.role === 'user'
              const isRef = st.action === 'reference_lookup'
              const ev = st.evidence
              const evOpenHere = evOpen === i
              const hasInline = !!(ev && ev.inline)
              const hasFiles = !!(ev && ev.files && ev.files.length)
              const hasMissing = !!(ev && ev.missing)
              const hasEv = hasInline || hasFiles || hasMissing
              // 刻度点颜色 = 这一步在流程里扮演什么角色：用户输入 / 参考层 / 有证据的 agent 步 / 普通步
              const dotColor = isUser ? 'var(--acc-blue)' : (isRef ? 'var(--acc-purple)' : (hasEv ? 'var(--acc-green)' : null))
              const last = i === steps.list.length - 1
              return React.createElement('div', { key: i, className: 'sleu-tl-row' },
                // 左侧：刻度点 + 竖轨（"第几步"能一眼数出来；最后一步不画轨）
                React.createElement('div', { className: 'sleu-tl-mk' },
                  React.createElement('span', { className: 'sleu-tl-dot', style: dotColor ? { background: dotColor } : undefined }),
                  last ? null : React.createElement('span', { className: 'sleu-tl-rail' }),
                ),
                React.createElement('div', { style: { flex: 1, minWidth: 0, paddingBottom: last ? 0 : 14 } },
                  React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 13.5, color: T.text2, flexWrap: 'wrap' } },
                    React.createElement('span', { style: { fontWeight: 700, color: isUser ? T.brand : T.text } }, isUser ? '用户' : 'Agent'),
                    st.step ? React.createElement('span', { className: 'sleu-num', style: { fontSize: 12.5 } }, '第 ' + st.step + ' 步') : null,
                    st.action ? React.createElement('span', { className: 'sleu-mono', style: { background: T.bg2, padding: '1px 7px', borderRadius: 5, fontSize: 11.5, color: T.text2 } }, st.action) : null,
                    isRef ? React.createElement('span', { className: 'sleu-chip', style: { background: 'var(--tint-purple)', color: 'var(--d-purple)', borderRadius: 999, padding: '1px 8px', fontSize: 11.5, fontWeight: 600 } }, '参考层') : null,
                    // 证据存在性**提到步骤行**：扫轨迹时先看哪几步带证据，不必逐个展开
                    hasEv ? React.createElement('span', { style: { display: 'flex', gap: 4, alignItems: 'center' } },
                      React.createElement('span', { style: tinyBadge('var(--d-green)') }, '证据' +
                        (hasInline ? ' ' + ev.inline.length + '字' : '') +
                        (hasFiles ? ' ' + ev.files.length + '文件' : '')),
                      hasMissing ? React.createElement('span', { style: tinyBadge('var(--d-amber)') }, '缺 ' + ev.missing) : null,
                    ) : null,
                  ),
                  st.output ? React.createElement('div', { style: { marginTop: 4, color: T.text, fontSize: 14.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.75 } }, st.output) : null,
                  st.reason ? React.createElement('div', { style: { marginTop: 3, color: T.text2, fontSize: 13.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontStyle: 'italic', lineHeight: 1.68 } },
                    '推理: ' + st.reason) : null,
                  st.content ? React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 14.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.75 } }, st.content) : null,
                  // 证据明细（可点开原文 / 打开文件）——存在性已在上面标了，这里给操作
                  ev ? React.createElement('div', { style: { marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, flexWrap: 'wrap' } },
                    ev.inline ? React.createElement('button', { type: 'button', onClick: () => setEvOpen(evOpenHere ? null : i), className: 'sleu-chip', style: btnGhost }, evOpenHere ? '收起原文' : '看原文') : null,
                    hasFiles ? React.createElement(React.Fragment, null,
                      React.createElement('span', { style: { color: T.text2 } }, '文件'),
                      ev.files.map(f => React.createElement('button', { key: f, type: 'button', onClick: () => openFile(f), title: f, className: 'sleu-chip', style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 999, padding: '1px 9px', fontSize: 11.5, cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' } },
                        opening === f ? '打开中…' : baseName(f)),
                    )) : null,
                    !hasInline && !hasFiles && hasMissing ? React.createElement('span', { style: { color: T.text2 } }, '这一步没有留证据') : null,
                  ) : null,
                  evOpenHere && ev.inline ? React.createElement('pre', { style: { marginTop: 6, background: T.bg2, border: '1px solid var(--hair)', borderRadius: 8, padding: 10, fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: T.text, lineHeight: 1.7, maxHeight: 320, overflowY: 'auto' } }, ev.inline) : null,
                ),
              )
            })
          )
        } else {
          body = React.createElement('div', { style: { color: T.text2, padding: 10 } }, steps && steps.error ? '加载失败: ' + steps.error : '无轨迹步骤')
        }
      }

      let kbTag = null
      if (s.activeCase) {
        // 徽章走统一形态（tinyBadge → --d-* 深档），亮/暗两套主题自动跟
        kbTag = s.activeCaseInKb
          ? React.createElement('span', { title: '该 case 已在 knowledge/ 中', style: tinyBadge('var(--d-green)') }, '库中已有')
          : React.createElement('span', { title: '该 case 未入库（新形态待沉淀）', style: tinyBadge('var(--d-amber)') }, '新形态')
      }

      // 状态左条：**扫列表时先看这一列**（进行中/已升级=要跟；已解决=可放过）
      const statusAccent = { resolved: 'var(--acc-green)', in_progress: 'var(--acc-blue)', escalated: 'var(--acc-amber)', unknown: 'var(--acc-gray)' }[s.status] || 'var(--acc-gray)'
      // 闭环指令：**4 种结局分开给**（2026-09 阶段一）。
      // 为什么（用户提的"完成最后一公里"）：旧面板只有「继续诊断」与「沉淀」，闭不了环——
      // 于是"fix 生效 / 没生效 / 我不跟了 / 转上游"四种真实结局在数据上无法落笔，
      // 而 `confidence` 只认第一种（只有 resolved 才 hits+=1）。
      // **为什么必须分开**：把"没走诊断、问题自己没了"混进 resolved 会虚高解决率；
      // 混进 not_resolved 会冤枉命中的 case（把"没测"记成"误诊"）。词表见 `trace-status.yaml`。
      // 本阶段只生成指令（用户粘贴到对话执行），不改面板写入路径——写入是阶段二。
      const closeCmds = []
      if (s.activeCase) {
        closeCmds.push({
          key: 'close-fix', label: '已解决 · fix 生效', tone: 'success',
          cmd: '闭环诊断 ' + s.sessionId + '：fix 已应用且验证生效（' + s.activeCase + ' 命中，'
            + '标 status: resolved + feedback{outcome: resolved}，写一条 feedback 事件）',
        })
        closeCmds.push({
          key: 'close-nofix', label: '没解决', tone: 'warn',
          cmd: '闭环诊断 ' + s.sessionId + '：' + s.activeCase + ' 的 fix 应用后没解决问题'
            + '（标 status: resolved + feedback{outcome: not_resolved}，写 feedback 事件，并按误诊归因判 case_error / execution_error）',
        })
      } else {
        closeCmds.push({
          key: 'close-fix', label: '已解决', tone: 'success',
          cmd: '闭环诊断 ' + s.sessionId + '：问题已解决（未命中知识库 case，所以不写 feedback——'
            + '标 status: resolved，并在 summary 里补一句最终怎么解决的）',
        })
      }
      closeCmds.push({
        key: 'close-archive', label: '不跟了', tone: 'ghost',
        cmd: '闭环诊断 ' + s.sessionId + '：不再跟进，且**不对 fix 是否有效下判断**'
          + '（问题自行消失 / 环境变更后不复现 —— 标 status: archived，不写 feedback 事件）',
      })
      closeCmds.push({
        key: 'close-escalate', label: '转上游', tone: 'ghost',
        cmd: '闭环诊断 ' + s.sessionId + '：本地无法定位，转上游/技术支持（标 status: escalated，不写 feedback 事件）',
      })
      if (!canResume) {
        closeCmds.push({
          key: 'reopen', label: '重新打开', tone: 'ghost',
          cmd: '把这个诊断重新打开：' + s.sessionId + '（status 改回 in_progress；若当时写过 feedback 事件，一并撤掉那条）',
        })
      }
      const toneStyle = (tone) => tone === 'success' ? btnSuccess : (tone === 'warn' ? btnRed : btnGhost)
      // 指令区形态（2026-09-12 改版，两个实测体验问题）：
      //  ① **按钮横排**：它们同属"选哪条指令"，旧版每条指令各占一行竖排（5 个按钮 + 5 行展开体），
      //     卡片被撑得很高、视觉碎；横排才看得出是一组，点开的内容只在下方一处展开。
      //  ② **卡片内不再重复提示**：旧版每张卡片都印一句「这一单结束了？（点一个 → 复制指令 → 粘到对话）」，
      //     同一句话重复 N 遍＝噪音；这条说明属于整个列表（列表工具栏/待跟进条已有一句），不在卡片里复读。
      const actions = []
      if (canResume) actions.push({
        key: 'rs', label: '继续诊断', style: btnPrimary, title: '生成续接指令',
        cmd: '用 /skill:resume-diagnosis 续接 ' + s.sessionId,
      })
      for (const c of closeCmds) actions.push({ key: c.key, label: c.label, style: toneStyle(c.tone), title: '生成闭环指令（复制后粘到对话执行）', cmd: c.cmd })
      const openedCmd = actions.filter(a => a.key === showCmd)[0] || null
      // 报告与沉淀候选入口（diagnose 步骤 6 的产出）：报告是人读件的落点，"待沉淀 N 条"让
      // "这单还能沉淀什么"在卡片上就看得见（trace 里存的是结构化候选，面板只报条数，
      // 正文留在报告与 trace 里——面板不做二次编辑）。
      const reportPath = s.reportFile ? 'traces/' + s.reportFile : null
      const docRow = (reportPath || s.sedimentCandidates)
        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
            reportPath ? React.createElement('button', {
              type: 'button', onClick: () => openFile(reportPath), title: reportPath,
              style: { background: 'transparent', border: '1px solid ' + T.brand, color: T.brand, borderRadius: 999, padding: '2px 11px', fontSize: 11.5, fontWeight: 600, cursor: 'pointer' },
            }, opening === reportPath ? '打开中…' : '打开报告') : null,
            // 开没开成都要看得见：成功给「已打开（via X）」，失败给原因。
            // 旧版成功无反馈、失败静默 → 用户只看到"点了没反应"。
            copied === 'open:' + reportPath ? React.createElement('span', { style: { color: T.success, fontSize: 11.5 } }, openVia ? '已打开（' + openVia + '）' : '已打开') : null,
            s.sedimentCandidates ? React.createElement('span', { style: tinyBadge('var(--d-purple)'), title: 'trace.sediment_candidates（与报告第 8 节同源）' }, '待沉淀 ' + s.sedimentCandidates + ' 条') : null,
            openErr ? React.createElement('span', { style: { color: T.warn, fontSize: 11.5 } }, openErr) : null,
          )
        : null
      // 展开的命令块只出现一次（谁被点开就显示谁），按钮本身用"未选中的淡一档"表达选中关系
      const actionArea = React.createElement('div', { style: { margin: '0 16px 12px', paddingTop: 10, borderTop: '1px dashed ' + T.border } },
        docRow,
        React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 8 } },
          actions.map(a => React.createElement('button', {
            key: a.key, type: 'button', title: a.title,
            onClick: () => { setShowCmd(showCmd === a.key ? null : a.key); setCopied(null) },
            style: openedCmd && openedCmd.key !== a.key ? { ...a.style, opacity: 0.62 } : a.style,
          }, a.label)),
        ),
        openedCmd ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 } },
          React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg, border: '1px solid var(--hair)', borderRadius: 6, padding: '5px 8px', fontSize: 12.5, fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: T.text } }, openedCmd.cmd),
          React.createElement('button', { type: 'button', onClick: () => doCopy(openedCmd.cmd, openedCmd.key), style: copied === 'fail' ? { ...btnRed, background: 'var(--d-red)' } : btnPrimary, title: '复制指令' },
            copied === openedCmd.key ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
        ) : null,
      )

      return React.createElement('div', { className: 'sleu-card', style: { background: T.bg, backgroundImage: 'var(--surf)', border: '1px solid var(--hair)', borderLeft: '3px solid ' + statusAccent, borderRadius: 12, marginBottom: 10, overflow: 'hidden', boxShadow: 'var(--elev-1)' } },
        React.createElement('button', {
          type: 'button', 'aria-expanded': !!open, onClick: toggle, className: 'sleu-row',
          style: { width: '100%', padding: '12px 16px', cursor: 'pointer', background: 'transparent', border: 'none', textAlign: 'left', color: T.text, font: 'inherit' },
        },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
            React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 5, color: meta.color, fontSize: 12.5, fontWeight: 600 } },
              React.createElement(Dot, { color: meta.color }),
              meta.label),
            React.createElement('span', { className: 'sleu-mono', style: { fontWeight: 700, fontSize: 14.5, letterSpacing: '.01em' } }, s.sessionId),
            kbTag,
            React.createElement('span', { style: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 } },
              rel ? React.createElement('span', { style: { color: T.text2, fontSize: 12.5 } }, '更新 ' + rel) : null,
              React.createElement(Chevron, { open: open }),
            ),
          ),
          // 副行：**收起态显示"这单在查什么"**——最后一步 Agent 的结论（host 已带 lastOutput，
          // 不需要额外 RPC）。旧版显示"框架 · 平台 · 类别"，那是标签不是信息：不点开不知道在查什么。
          // 展开态仍给完整的环境标签（那时读者需要细节）。
          React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 5, lineHeight: 1.6, display: 'flex', gap: 6, alignItems: 'baseline' } },
            !open && s.lastOutput
              ? React.createElement(React.Fragment, null,
                  React.createElement('span', { style: { color: T.text2, flexShrink: 0 } }, s.lastRole === 'user' ? '最后一步 · 用户' : '最后一步 · Agent'),
                  React.createElement('span', { title: s.lastOutput, style: { color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, s.lastOutput),
                )
              : React.createElement('span', null, [s.framework, s.platform, s.category].filter(Boolean).join(' · ') || '—'),
          ),
          s.activeCase ? React.createElement('div', { style: { marginTop: 5, fontSize: 13.5, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement('span', { style: { color: T.text2 } }, '定位'),
            React.createElement('code', { style: { background: 'color-mix(in srgb, ' + T.success + ' 10%, transparent)', color: T.success, padding: '1px 7px', borderRadius: 5, fontSize: 12.5, fontFamily: 'var(--font-mono)' } }, s.activeCase),
          ) : React.createElement('div', { style: { marginTop: 5, color: T.text2, fontSize: 12.5 } }, '未定位到知识库 case'),
          React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 4 } },
            '轨迹: ' + s.userSteps + ' 用户输入 / ' + s.agentSteps + ' agent 步骤'),
          s.feedbackPending ? React.createElement('div', { style: { color: T.warn, fontSize: 13.5, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: T.warn }),
            '结果还没回报（' + s.feedbackPending + '）——好在下面可以直接闭环') : null,
        ),
        // 状态指令区：续接（仅活跃会话） + 闭环四种结局；形态见上方 actionArea 注释
        actionArea,
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

      const base = { fontFamily: 'var(--font-sans)', fontSize: 'var(--t-base)', color: T.text }
      if (state.loading) return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20, color: T.text2 } }, '加载诊断状态…')
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

      // 空态：先说"为什么空"+"下一步做什么"（两句展开成变量，避免嵌套三元写错括号）
      const totalSessions = (r.sessions || []).length
      const emptyTitle = q ? '没有匹配的会话' : (totalSessions ? '当前筛选下没有会话' : '还没有诊断记录')
      const emptyHint = q ? '换个关键词，或点上面的「全部」清掉筛选'
        : '在对话里跑一次 /skill:diagnose，这里就会出现会话与完整轨迹'

      // 首屏要先回答"有什么在等我"——所以计数里把**待跟进**的两项单独提出来（进行中、待回报），
      // 而不是混在一串 "N 会话 · N 库中已有 …" 里让读者自己找
      const nFollow = nActive + nPending
      return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, gap: 10, flexWrap: 'wrap' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-blue)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 18, fontWeight: 700 } }, '诊断状态'),
          ),
          React.createElement('span', { title: badge, style: { fontSize: 12.5, color: T.text2, background: T.bg2, border: '1px solid var(--hair)', borderRadius: 999, padding: '3px 11px' } },
            nFollow ? (nFollow + ' 项待跟进') : ((r.sessions || []).length + ' 个会话')),
        ),
        // 待跟进提示：只在真有的时候出现，且给"下一步做什么"
        nFollow ? React.createElement('div', { style: { ...rise(0), display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '8px 12px', marginBottom: 10, background: 'var(--tint-amber)', border: '1px solid var(--hair)', borderRadius: 10, fontSize: 13.5, color: T.text } },
          React.createElement(Dot, { color: T.warn, size: 7 }),
          nActive ? React.createElement('span', null, nActive + ' 个诊断还没结束') : null,
          nActive && nPending ? React.createElement('span', { style: { color: T.text2 } }, '·') : null,
          nPending ? React.createElement('span', null, nPending + ' 个结果还没回报') : null,
          React.createElement('span', { style: { color: T.text2, marginLeft: 'auto', fontSize: 12.5 } }, '卡片里点按钮生成指令 → 复制 → 粘到对话执行'),
        ) : null,
        // 工具栏（筛选 + 搜索）**吸顶**：会话一多就得往下滚，工具不该滚走
        React.createElement('div', { style: { position: 'sticky', top: 0, zIndex: 2, paddingTop: 2, paddingBottom: 8, marginBottom: 4, background: T.bg, backgroundImage: 'var(--surf)' } },
          React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' } },
            kbChips.map(c => React.createElement('button', { key: c.id, type: 'button', onClick: () => setKbFilter(c.id), className: 'sleu-chip', style: c.id === kbFilter ? { ...btnPrimary, padding: '4px 13px', borderRadius: 999 } : { ...btnGhost, padding: '4px 13px', borderRadius: 999 } }, c.label)),
          ),
          React.createElement('div', { style: { position: 'relative' } },
            React.createElement('span', { style: { position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', width: 10, height: 10, borderRadius: 999, border: '1.5px solid ' + T.text2, display: 'block' } }),
            React.createElement('input', { placeholder: '搜索：会话号 / 状态 / 框架 / 平台 / 定位到的 case…', value: query, onChange: e => setQuery(e.target.value), style: { width: '100%', boxSizing: 'border-box', padding: '8px 11px 8px 30px', fontSize: 13.5, borderRadius: 9, border: '1px solid var(--hair)', background: T.bg, color: T.text, outline: 'none', transition: 'border-color .15s' } }),
          ),
        ),
        sessions.length > 20 ? React.createElement('button', {
          type: 'button', className: 'sleu-fab', title: '回到顶部（会话较多）',
          onClick: () => {
            // 面板的滚动容器可能是祖先节点而不是 window —— 从触发元素往上找第一个可滚的祖先
            try {
              const el = (typeof document !== 'undefined' && document.activeElement) || null
              let node = el
              while (node && node !== document.body) {
                const ov = getComputedStyle(node).overflowY
                if ((ov === 'auto' || ov === 'scroll') && node.scrollHeight > node.clientHeight + 4) {
                  node.scrollTo({ top: 0, behavior: 'smooth' }); return
                }
                node = node.parentElement
              }
              if (typeof window !== 'undefined' && window.scrollTo) window.scrollTo({ top: 0, behavior: 'smooth' })
            } catch (e) { /* 滚动不可用时静默（按钮本身无副作用） */ }
          },
        }, '↑') : null,
        sessions.length === 0
          ? React.createElement('div', { style: { color: T.text2, padding: '32px 16px', textAlign: 'center', fontSize: 13.5, lineHeight: 1.8 } },
              React.createElement('div', { style: { fontSize: 15, fontWeight: 600, color: T.text, marginBottom: 6 } }, emptyTitle),
              emptyHint)
          : React.createElement('div', null,
              sessions.map(s => React.createElement(SessionCard, { key: s.file, session: s, sessionId: sessionId })),
            ),
      )
    }

    // ============ 指标 tab ============
    // 存量体检：回答"库里什么不健康"。**容量口径不在这里**——它按判据逐格算，
    // 归在 CapacityLedger（判据逐格计；加总到 namespace 会让人看不出是哪一格爆了）。
    function HealthPanel({ health }) {
      if (!health) return null
      const c = health.cases || {}
      const r = health.references || {}
      const caseRows = []
      if (c.total) {
        const drift = (typeof c.diskTotal === 'number' && typeof c.declaredTotal === 'number') ? c.diskTotal - c.declaredTotal : 0
        caseRows.push(React.createElement(MetricRow, {
          key: 'ct', label: 'case 总数', value: c.total,
          sub: (c.indexGeneratedAt ? '索引生成于 ' + c.indexGeneratedAt : '索引无生成日期')
            + (drift ? ' · 磁盘 ' + c.diskTotal + ' 条，索引落后 ' + drift + ' 条 → 跑 build_index.py' : ''),
        }))
      }
      if (c.lowConfidence) caseRows.push(React.createElement(MetricRow, { key: 'lc', label: '低置信占比（评分 <0.5）', value: c.lowConfidence + ' / ' + c.total + ' (' + pct(c.lowConfidence, c.total) + ')', warn: (c.lowConfidence / c.total) > 0.4 }))
      if (c.byCategory && Object.keys(c.byCategory).length) {
        caseRows.push(React.createElement(MetricRow, { key: 'bc', label: 'category 分布', value: Object.keys(c.byCategory).map(k => (CATEGORY_LABELS[k] || k) + ' ' + c.byCategory[k]).join(' · ') }))
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

      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 12, overflow: 'hidden', boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('div', { style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-green)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '知识库健康'),
          ),
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 12px' } },
            React.createElement('div', null,
              React.createElement(SectionLabel, { color: T.success }, 'case'),
              caseRows,
            ),
            React.createElement('div', null,
              React.createElement(SectionLabel, { color: 'var(--d-purple)' }, 'reference'),
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
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 12, overflow: 'hidden', boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('div', { style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-purple)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '流程闭环'),
          ),
          rows,
        ),
      )
    }

    // ============ 本期 vs 上期变化对照（指标 tab 首屏） ============
    // 旧版把 7 期 × 10+ 指标全平铺成 label/value 网格，读者要自己找"哪一行和上期不一样"。
    // 这里把"变了的"提到最前：新增 / 变化 / 本期不再采集，不变的只报个数。
    function CompareStrip({ prev, cur, isUnreadable }) {
      const d = diffPeriods(prev, cur)
      if (!cur) return null
      const unread = isUnreadable || (() => false)
      const km = kindMeta[cur.kind] || kindMeta.example
      const META = {
        new: { label: '新增', color: 'var(--d-blue)' },
        change: { label: '变化', color: T.warn },
        gone: { label: '不再采集', color: T.text2 },
      }
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, padding: '11px 14px', marginBottom: 12, boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '本期变化'),
          React.createElement('span', { className: 'sleu-chip', style: { color: km.color, border: '1px solid ' + km.color, borderRadius: 999, padding: '1px 9px', fontSize: 11.5, fontWeight: 700 } }, km.label),
          React.createElement('span', { style: { fontFamily: 'var(--font-mono)', fontSize: 13.5, fontWeight: 700 } }, cur.period),
          d.prevPeriod
            ? React.createElement('span', { style: { fontSize: 12.5, color: T.text2 } }, '对比 ' + d.prevPeriod)
            : React.createElement('span', { style: { fontSize: 12.5, color: T.text2 } }, '无上一期可比'),
          React.createElement('span', { style: { marginLeft: 'auto', fontSize: 12.5, color: T.text2 } },
            d.moved.length ? d.moved.length + ' 项变动 · ' + d.same + ' 项持平' : '与上期完全一致'),
        ),
        d.moved.length
          ? React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
              d.moved.map(m => {
                const meta = META[m.kind] || META.change
                return React.createElement('div', { key: m.key, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', background: T.bg2, borderRadius: 7, fontSize: 12.5, flexWrap: 'wrap' } },
                  React.createElement('span', { style: { color: meta.color, fontWeight: 700, fontSize: 11.5, minWidth: 52 } }, meta.label),
                  React.createElement('span', { style: { color: T.text2, flex: '1 1 130px', minWidth: 0 } }, m.label),
                  unread(m.key) ? React.createElement('span', { title: unread(m.key) === true ? '分母为 0：这个数不可解读' : unread(m.key), style: tinyBadge('var(--d-purple)') }, '不可解读') : null,
                  React.createElement('span', { style: { fontFamily: 'var(--font-mono)', color: T.text } },
                    m.kind === 'change' ? (m.from + ' → ' + m.to) : (m.kind === 'new' ? m.to : m.from)),
                  m.delta !== null && m.delta !== undefined ? React.createElement('span', { style: { fontSize: 11.5, fontWeight: 700, color: m.delta > 0 ? T.success : (m.delta < 0 ? T.error : T.text2) } },
                    (m.delta > 0 ? '+' : '') + m.delta) : null,
                )
              }),
            )
          : React.createElement('div', { style: { fontSize: 12.5, color: T.text2 } }, '本期各指标与上一期逐项相同——没有新变化可读。'),
      )
    }

    // ============ 单期卡片（可折叠） ============
    // 卡头是 <button>（键盘可达 + aria-expanded），与 ev-panel 的 IdeaCard 同一约定
    function PeriodCard({ p, open, onToggle, isUnreadable }) {
      const unread = isUnreadable || (() => false)
      const km = kindMeta[p.kind] || kindMeta.example
      const metricKeys = Object.keys(p.metrics || {})
      const summary = metricKeys.slice(0, 3).map(k => (METRIC_LABELS[k] || k) + ' ' + metricValue(p.metrics[k]).text).join(' · ')
      const nUnread = metricKeys.filter(k => unread(k)).length
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 14, marginBottom: 10, overflow: 'hidden', boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('button', {
          type: 'button', 'aria-expanded': !!open, onClick: onToggle,
          style: { width: '100%', padding: open ? '12px 16px 8px' : '10px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', background: 'transparent', border: 'none', textAlign: 'left', color: T.text, font: 'inherit' },
        },
          React.createElement(Chevron, { open: open, color: km.color }),
          React.createElement('span', { className: 'sleu-chip', style: { color: km.color, border: '1px solid ' + km.color, borderRadius: 999, padding: '1px 10px', fontSize: 11.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em' } }, km.label),
          React.createElement('span', { style: { fontWeight: 700, fontSize: 13.5, fontFamily: 'var(--font-mono)' } }, p.period),
          p.recorded_at ? React.createElement('span', { style: { color: T.text2, fontSize: 12.5 } }, '记录 ' + p.recorded_at) : null,
          nUnread ? React.createElement('span', { title: '该期有 ' + nUnread + ' 项指标分母为 0（不可解读）', style: tinyBadge('var(--d-purple)') }, nUnread + ' 项不可解读') : null,
          !open && summary ? React.createElement('span', { style: { marginLeft: 'auto', color: T.text2, fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '55%' } }, summary) : null,
          open ? null : React.createElement('span', { style: { color: T.text2, fontSize: 12.5 } }, metricKeys.length + ' 项'),
        ),
        open ? React.createElement('div', { style: { padding: '0 16px 12px' } },
          km.note ? React.createElement('div', { style: { color: T.text2, fontSize: 12.5, marginBottom: 4, fontStyle: 'italic' } }, km.note) : null,
          p.title ? React.createElement('div', { style: { color: T.text, fontSize: 13.5, marginTop: 3, lineHeight: 1.65 } }, p.title) : null,
          p.source ? React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 3, wordBreak: 'break-word', lineHeight: 1.65 } }, '来源: ' + p.source) : null,
          metricKeys.length ? React.createElement('div', { style: { marginTop: 9, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 12px' } },
            metricKeys.map(k => {
              const v = p.metrics[k]
              const total = ratioTotal(v)
              const small = total !== null && total > 0 && total < 5
              return React.createElement(MetricRow, { key: k, label: METRIC_LABELS[k] || k, value: fmtVal(v), small: small, unreadable: !!unread(k), unreadableWhy: unread(k) === true ? null : unread(k) })
            }),
          ) : null,
          p.notes && p.notes.trim() ? React.createElement('div', { style: { marginTop: 9, padding: '7px 10px', background: 'color-mix(in srgb, ' + T.brand + ' 5%, transparent)', borderLeft: '3px solid ' + T.brand, borderRadius: 5, fontSize: 13.5, color: T.text2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.68 } },
            p.notes.trim()) : null,
        ) : null,
      )
    }

    // ============ 首屏：状态条 / 判决 / 闭环检验 / 容量台账 ============
    // 取向（对齐 ev-panel 的 FocusStrip）：首屏只回答**一个**问题——"现在有什么要我处理"。
    // 明细照旧在下面，但不再由读者自己去 20 行数字里筛。

    const iconFor = (level) => (level === 'fail' ? '✗' : level === 'warn' ? '!' : '✓')
    const colorFor = (level) => (level === 'fail' ? T.error : level === 'warn' ? T.warn : T.success)
    const dimFor = (level) => (level === 'fail' ? 'var(--acc-red)' : level === 'warn' ? 'var(--acc-amber)' : 'var(--acc-green)')

    // 判据阈值 → 可复制的那一下。判据本身在 gates.yaml / metrics_health.py，面板不重算，
    // 只把"该做什么"变成"粘到对话就能做"（panels 是只读可视化 + 指令生成器）。
    function commandFor(face, text) {
      const f = String(face || '')
      const t = String(text || '')
      if (/cell_|容量|超\s*(soft|hard)_cap/.test(f + t)) return { label: '拆格子', command: '用 /skill:knowledge-groom 处理容量越界格子（先跑 python3 scripts/capacity_health.py 看候选溢出率，再定 category 轴深化或 platform 轴拆分）' }
      if (/feedback|反馈/.test(f + t)) return { label: '补反馈', command: '回报 fix 结果：逐个确认 traces/ 中已定位 case 的 session（含 feedback_pending 的）fix 应用后是否解决，按 resolved / not_resolved / partial 写 feedback 事件' }
      if (/新鲜度|快照|超期/.test(f + t)) return { label: '追快照', command: 'python3 scripts/metrics_snapshot.py' }
      if (/索引|drift/.test(f + t)) return { label: '重建索引', command: 'python3 scripts/build_index.py' }
      return null
    }

    function verdictState(verdict, error) {
      if (error) return { level: 'warn', label: '体检不可用', color: T.warn, accent: 'var(--acc-amber)', note: error }
      if (!verdict) return { level: 'warn', label: '体检待载入', color: T.text2, accent: 'var(--acc-gray)', note: '体检结果尚未返回' }
      const cov = verdict.coverage || {}
      const v = verdict.check_verdict
      if (v === 'broken' || (cov.gates_total !== undefined && cov.gates_evaluated < cov.gates_total)) {
        return { level: 'broken', label: '体检器失效', color: T.error, accent: 'var(--acc-red)',
                 note: '有判据没被评估——"没有越界"这个结论不成立：' + ((verdict.broken || []).join('；') || '缺口未说明') }
      }
      if (verdict.fail_count > 0) {
        return { level: 'violations', label: verdict.fail_count + ' 项需处理', color: T.error, accent: 'var(--acc-red)',
                 note: '按 metrics/gates.yaml 判据检查，有 ' + verdict.fail_count + ' 项越界' }
      }
      return { level: 'clean', label: '闭环未见阻塞项', color: T.success, accent: 'var(--acc-green)',
               note: '判据全部评过且无越界' }
    }

    function StatusBar({ verdict, error }) {
      const f = (verdict && verdict.freshness) || {}
      const cur = (verdict && verdict.current) || {}
      const drift = verdict && verdict.drift
      const cells = (verdict && verdict.capacity_cells) || []
      const hot = cells.filter(c => c.soft || c.hard)
      const st = verdictState(verdict, error)
      const cov = (verdict && verdict.coverage) || {}
      const parts = []
      parts.push(React.createElement('span', { key: 's', style: { display: 'flex', alignItems: 'center', gap: 6 } },
        React.createElement(Dot, { color: T.brand }),
        React.createElement('span', { style: { fontWeight: 700, color: T.text } }, '最后核验快照'),
        React.createElement('span', { style: { fontFamily: 'var(--font-mono)' } }, String(verdict && verdict.last_live || '—')),
        f.live_age_days !== undefined && f.live_age_days !== null
          ? React.createElement('span', { style: { color: (f.live_limit_days && f.live_age_days > f.live_limit_days) ? T.warn : T.text2 } },
              f.live_age_days + ' 天前（阈值 ' + f.live_limit_days + ' 天）')
          : null,
      ))
      parts.push(React.createElement('span', { key: 'p', style: { color: T.text2 } }, 'live ' + (f.live_periods || 0) + ' 期 · 结构 ' + (f.structural_periods || 0) + ' 期'))
      if (cur.case_total !== undefined && cur.case_total !== null) {
        parts.push(React.createElement('span', { key: 'c', style: { color: T.text2 } }, 'case ' + cur.case_total + ' · ref ' + (cur.reference_total === null || cur.reference_total === undefined ? '—' : cur.reference_total)))
      }
      // 判据覆盖面：**有几条判据真的被评过**——"没报越界"与"没被检查"是两件事。
      // broken 态下说法必须与上面的横幅一致：不能说"3/3 全部被评估"又说"判据不完整"
      // （读者会以为其中一句在骗人）——实测就是这么自相矛盾的。
      if (st.level === 'broken') {
        const lackN = ((verdict && verdict.broken) || []).length
        parts.push(React.createElement('span', {
          key: 'g', title: st.note,
          style: { display: 'flex', alignItems: 'center', gap: 4, color: T.warn, fontWeight: 700 },
        }, '本轮有判据没跑' + (lackN ? '（' + lackN + ' 项）' : '')))
      } else if (cov.gates_total) {
        const partial = cov.gates_evaluated < cov.gates_total
        parts.push(React.createElement('span', {
          key: 'g', title: partial ? '有判据没被评估——这不是"通过"' : 'metrics/gates.yaml 里声明的判据全部被评估过',
          style: { display: 'flex', alignItems: 'center', gap: 4, color: partial ? T.error : T.text2, fontWeight: partial ? 700 : 400 },
        },
          '判据 ' + cov.gates_evaluated + '/' + cov.gates_total,
          cov.readability_total ? ' · 数字可信度 ' + cov.readability_evaluated + '/' + cov.readability_total : null,
        ))
      }
      // drift：索引声称的条数 ≠ 磁盘实际——面板读的是索引，索引陈了就显示旧数。必须显式说出来。
      if (drift && typeof drift.disk === 'number' && typeof drift.declared === 'number' && drift.disk !== drift.declared) {
        parts.push(React.createElement('span', { key: 'd', title: '面板读 knowledge/_index.yaml；它是生成物，落后于磁盘真实 case 文件数', style: { display: 'flex', alignItems: 'center', gap: 5, color: T.warn, fontWeight: 600 } },
          React.createElement(Dot, { color: T.warn, size: 6 }),
          '索引 ' + drift.declared + ' ≠ 磁盘 ' + drift.disk + '（差 ' + (drift.disk - drift.declared) + '）',
        ))
      }
      return React.createElement('div', { style: { ...rise(0), display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '7px 11px', marginBottom: 9, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 10, fontSize: 13.5, color: T.text2 } },
        ...parts,
        React.createElement('span', { title: st.note, style: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 } },
          pill(st.label, st.color),
          hot.length ? pill('容量越界 ' + hot.length + ' 格', T.error) : null,
        ),
      )
    }

    // 判决行：一行一条判据结论，展开是"证据 + 下一步 + 可复制指令"
    //
    // 版式（2026-09 四轮重排）：**单行流式**——图标与判据面标签跟正文在同一行内联，
    // 正文自然换行。旧版是三栏（图标+66px 标签列+正文），一句话被拆成三段、读起来断续，
    // 这正是"看着吃力"的一半来源；另一半是颜色用在四处（左边框+底纹+图标+徽标），下面也一并收敛。
    // 判决行：**收起态说人话，展开态留工程细节**（2026-09 七轮）。
    //
    // 为什么（用户反馈）：旧版直接把 `cell_soft_cap` / `feedback_capture_floor` /
    // `misdiagnosis_rate` 这些**代码里的名字**和对着实现说的句子端给读者
    //（"(framework × category) 格子条数超 soft_cap"）。判据的身份住在体检脚本那一侧，
    // 所以"人话版"由它随 findings 一起下发（`plain`），面板只渲染、不做启发式翻译。
    // 技术文案不丢：展开后作为「判据」证据行，维护者仍拿得到判据名去回查 gates.yaml。
    function VerdictRow({ row, copiedKey, onCopy }) {
      const [open, setOpen] = React.useState(false)
      const cmd = commandFor(row.face, row.text)
      const color = colorFor(row.level)
      const key = 'v-' + row.face + '-' + String(row.text).slice(0, 24)
      const faceLabel = String(row.face).replace(/^越界\s*/, '')
      const plain = row.plain || row.text        // 缺人话版时退回技术文案（诚实退化，不空着）
      return React.createElement('div', { style: { borderTop: '1px solid ' + T.border } },
        React.createElement('button', {
          type: 'button',
          'aria-expanded': open,
          onClick: () => setOpen(!open),
          className: 'sleu-row',
          style: { width: '100%', display: 'flex', alignItems: 'baseline', gap: 7, padding: '9px 12px', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left', color: T.text, font: 'inherit' },
        },
          React.createElement('span', { style: { color: color, fontWeight: 700, fontSize: 13.5, flexShrink: 0, lineHeight: '20px' } }, iconFor(row.level)),
          React.createElement('span', { className: 'sleu-chip', style: { fontSize: 11.5, color: T.text2, flexShrink: 0, lineHeight: '20px', border: '1px solid ' + T.border, borderRadius: 999, padding: '0 7px' } }, faceLabel),
          React.createElement('span', { style: { flex: 1, minWidth: 0, fontSize: 14.5, lineHeight: 1.65, wordBreak: 'break-word', color: T.text } }, plain),
          React.createElement(Chevron, { open: open, color: T.text2 }),
        ),
        open ? React.createElement('div', { style: { padding: '2px 12px 12px 30px', fontSize: 13.5, lineHeight: 1.65 } },
          // 判据证据行：技术文案（判据名 / 格子数 / 指标名）——给要回查配置的人
          React.createElement(SectionLabel, null, '判据出处'),
          React.createElement('div', { className: 'sleu-mono', style: { fontSize: 12.5, color: T.text2, lineHeight: 1.6, wordBreak: 'break-word' } }, row.text),
          row.action ? React.createElement('div', { style: { color: T.text, marginTop: 10 } },
            React.createElement(SectionLabel, null, '下一步动作'),
            row.action) : null,
          cmd ? React.createElement('div', { style: { marginTop: row.action ? 9 : 0 } },
            React.createElement(SectionLabel, null, '可复制指令'),
            React.createElement('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 6 } },
              React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 6, padding: '6px 8px', fontSize: 12.5, fontFamily: 'var(--font-mono)', wordBreak: 'break-word', lineHeight: 1.6, color: T.text } }, cmd.command),
              React.createElement('button', { type: 'button', onClick: () => onCopy(cmd.command, key), style: copiedKey === 'fail' ? { ...btnPurple, background: T.error } : btnRed }, copiedKey === key ? '已复制' : (copiedKey === 'fail' ? '失败' : cmd.label)),
            ),
          ) : null,
        ) : null,
      )
    }

    function VerdictCard({ verdict, error, copiedKey, onCopy }) {
      const findings = (verdict && verdict.findings) || []
      const fail = findings.filter(f => f.level === 'fail')
      const warn = findings.filter(f => f.level === 'warn')
      const okN = findings.filter(f => f.level === 'ok').length
      const shown = fail.concat(warn)
      const cmds = (verdict && verdict.candidate_commands) || []
      const head = error
        ? React.createElement('span', { style: { color: T.warn, fontSize: 12.5 } }, error)
        : (shown.length === 0
            ? React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 13.5, color: T.text2 } },
                React.createElement('span', { style: { color: T.success, fontWeight: 700 } }, '✓'),
                '本期无阻塞项 · ',
                // 配置文件名对读者没意义（那是维护者回查用的），收进 title；正文只说"检查了几条"
                React.createElement('span', { title: '判据与阈值定义在 metrics/gates.yaml（每一项都可展开回查）' },
                  '按 ' + findings.length + ' 条判据检查，全部通过'))
            : React.createElement('span', { style: { fontSize: 13.5, color: T.text2 } },
                React.createElement('span', { title: '判据与阈值定义在 metrics/gates.yaml（每一项都可展开回查）' },
                  '按 ' + findings.length + ' 条判据检查：'),
                React.createElement('b', { style: { color: T.error } }, ' ' + fail.length + ' 项需要处理'),
                ' · ',
                React.createElement('b', { style: { color: T.warn } }, warn.length + ' 项提示'),
                ' · ' + okN + ' 项正常'))
      return React.createElement('div', { className: 'sleu-card', style: { ...rise(0), border: '1px solid var(--hair)', borderTop: '2px solid ' + (error ? T.warn : (fail.length ? 'var(--acc-red)' : 'var(--acc-green)')), borderRadius: 12, background: T.bg, backgroundImage: 'var(--surf)', marginBottom: 10, overflow: 'hidden', boxShadow: 'var(--elev-1)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', flexWrap: 'wrap' } },
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '现在什么坏了'),
          head,
          error ? null : React.createElement('span', { style: { marginLeft: 'auto', color: T.text2, fontSize: 12.5 } }, '点开看证据与下一步'),
        ),
        shown.map((row, i) => React.createElement(VerdictRow, { key: i, row: row, copiedKey: copiedKey, onCopy: onCopy })),
        !error && shown.length === 0 && cmds.length ? React.createElement('div', { style: { padding: '8px 12px', background: T.bg2, borderTop: '1px solid ' + T.border } },
          React.createElement(SectionLabel, null, '可选动作'),
          React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
            cmds.map((c, i) => React.createElement('button', { key: i, type: 'button', title: c.why, onClick: () => onCopy(c.command, 'cand-' + i), style: copiedKey === 'cand-' + i ? btnSuccess : btnGhost }, copiedKey === 'cand-' + i ? '已复制' : c.label))),
        ) : null,
      )
    }

    // 闭环各腿：判据全貌（含正常项）收在折叠区——首屏只留"要处理的"，
    // 但"检了哪些腿、各腿什么状态"必须可查，否则读者不知道上面那张卡覆盖了什么。
    //
    // 版式（2026-09 四轮）：**用户先读到"哪几项没判"，技术细节收进折叠**。
    // 旧版把原始异常串（`PermissionError: [WinError 5] 拒绝访问。`）、覆盖率、以及
    // "含义：…**不等于**…"（星号还是字面量）一起平铺在首屏，读者先撞见一堆实现细节，
    // 才轮到"所以我要做什么"。诊断信息是给维护者的，不是给用户的。
    function BrokenDetector({ verdict, error }) {
      const [detailOpen, setDetailOpen] = React.useState(false)
      const st = verdictState(verdict, error)
      if (st.level !== 'broken') return null
      const cov = (verdict && verdict.coverage) || {}
      const items = (verdict && verdict.broken) || []
      // 从缺口文案里判"哪类判据没跑"，用用户能懂的话说；分类不出就退化为通用表述
      const lackCapacity = items.some(b => /容量|collect_structural|结构侧/.test(b))
      const lackRef = items.some(b => /reference|词条/.test(b))
      const what = []
      if (lackCapacity) what.push('容量越界（格子条数与上限）')
      if (lackRef) what.push('reference 词条数')
      const unimpl = items.filter(b => /没有评估实现|未被评估/.test(b)).length
      const headline = what.length
        ? what.join('、') + ' 这几项判据本轮没跑——所以下面没有它们的结论'
        : (unimpl ? '有 ' + unimpl + ' 条判据本轮没跑——所以下面没有它们的结论'
                  : '本轮有判据没跑——所以下面没有它们的结论')
      return React.createElement('div', { style: { ...rise(1), border: '1px solid var(--hair)', borderLeft: '2px solid ' + T.warn, borderRadius: 10, background: T.bg, padding: '10px 12px', marginBottom: 10 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } },
          React.createElement(Dot, { color: T.warn, size: 7 }),
          React.createElement('span', { style: { fontSize: 13.5, fontWeight: 700, color: T.text } }, '本轮判据不完整'),
          React.createElement('span', { style: { fontSize: 13.5, color: T.text, lineHeight: 1.6 } }, headline),
        ),
        React.createElement('div', { style: { marginTop: 6, fontSize: 13.5, color: T.text2, lineHeight: 1.65 } },
          '所以在这次检查里，',
          React.createElement('b', { style: { color: T.text } }, '「没有报出越界」不等于「没有越界」'),
          '——只是那几项没被判。其它判据的结论仍然有效。'),
        React.createElement('button', {
          type: 'button', 'aria-expanded': detailOpen,
          onClick: () => setDetailOpen(!detailOpen),
          style: { marginTop: 7, background: 'transparent', border: 'none', padding: 0, fontSize: 13.5, color: T.text2, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, font: 'inherit' },
        },
          React.createElement(Chevron, { open: detailOpen, color: T.text2 }),
          '为什么没跑 / 怎么复现',
        ),
        detailOpen ? React.createElement('div', { style: { marginTop: 6, paddingTop: 7, borderTop: '1px dashed ' + T.border, fontSize: 13.5, color: T.text2, lineHeight: 1.7 } },
          cov.gates_total ? React.createElement('div', null, '判据覆盖面：闸门 ' + cov.gates_evaluated + '/' + cov.gates_total
            + (cov.readability_total ? ' · 数字可信度 ' + cov.readability_evaluated + '/' + cov.readability_total : '')) : null,
          items.length ? React.createElement('div', { style: { marginTop: 4 } },
            items.map((b, i) => React.createElement('div', { key: i, style: { wordBreak: 'break-word' } }, '· ' + b))) : null,
          React.createElement('div', { style: { marginTop: 5 } },
            '复现：',
            React.createElement('code', { style: { userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 5, padding: '1px 6px', fontFamily: 'var(--font-mono)' } }, 'python3 scripts/metrics_health.py'),
            '　退出码 0 判据全评过且无越界 · 1 有判据被违反 · 2 有判据未被评估',
          ),
        ) : null,
      )
    }

    function CheckLedger({ verdict, error }) {
      const [open, setOpen] = React.useState(false)
      if (error || !verdict) return null
      const findings = verdict.findings || []
      const faces = []
      findings.forEach(f => { if (faces.indexOf(f.face) < 0) faces.push(f.face) })
      const nFail = findings.filter(f => f.level === 'fail').length
      const nWarn = findings.filter(f => f.level === 'warn').length
      return React.createElement('div', { style: { ...rise(1), marginBottom: 10 } },
        React.createElement('button', {
          type: 'button', 'aria-expanded': open, onClick: () => setOpen(!open),
          style: { width: '100%', display: 'flex', alignItems: 'center', gap: 7, padding: '6px 10px', background: 'transparent', border: '1px solid ' + T.border, borderRadius: 9, cursor: 'pointer', color: T.text2, fontSize: 13.5, font: 'inherit', transition: DUR ? 'border-color .15s ' + EASE : 'none' },
        },
          React.createElement(Chevron, { open: open, color: T.text2 }),
          React.createElement('span', { style: { fontWeight: 700, color: T.text } }, '闭环检验'),
          React.createElement('span', null, faces.join(' · ')),
          React.createElement('span', { style: { marginLeft: 'auto' } }, nFail + ' ✗ · ' + nWarn + ' ! · ' + findings.length + ' 项'),
        ),
        open ? React.createElement('div', { style: { marginTop: 7, padding: '8px 11px', background: T.bg, border: '1px solid ' + T.border, borderRadius: 9 } },
          findings.map((f, i) => React.createElement('div', { key: i, style: { display: 'flex', gap: 8, padding: '3px 0', fontSize: 13.5, lineHeight: 1.55, borderBottom: i === findings.length - 1 ? 'none' : '1px dashed ' + T.border } },
            React.createElement('span', { style: { color: colorFor(f.level), fontWeight: 700, width: 12, flexShrink: 0 } }, iconFor(f.level)),
            React.createElement('span', { style: { color: T.text2, minWidth: 62, flexShrink: 0 } }, f.face),
            React.createElement('span', { style: { flex: 1, minWidth: 0, color: T.text, wordBreak: 'break-word' } }, f.text),
          )),
          React.createElement('div', { style: { marginTop: 6, fontSize: 13.5, color: T.text2 } },
            '来源：scripts/metrics_health.py（判据 read metrics/gates.yaml）· 面板不重算阈值，只渲染这份结论。'),
        ) : null,
      )
    }

    // 历史趋势条：把"这一格从哪涨上来的"画出来。
    //
    // **为什么要做形状归一**（实测）：timeline 里的容量有三种写法——
    //   ① `{count, cap}` 字典（W37-live 起，`metrics_snapshot.py` 组装的结构侧）
    //   ② `"36/30"` 字符串（W35/W36-capacity，`build_index.py` 头注快照）
    //   ③ 整个 `capacity_by_ns` 缺席（诊断侧 live 快照不含结构指标）
    // 只认 ① 的话趋势永远只有 1 个点、什么也画不出来——而"容量从哪涨上来的"正是本轮要回答的。
    // 归一后不变量：**当前值以判决（体检器对磁盘现实的判定）为准**，历史只用来画走势。
    function normalizeCapacity(v) {
      if (typeof v === 'number') return { count: v, cap: null }
      if (typeof v === 'string') {
        const m = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(v)
        if (m) return { count: Number(m[1]), cap: Number(m[2]) }
        return null
      }
      if (v && typeof v === 'object' && typeof v.count === 'number') {
        return { count: v.count, cap: typeof v.cap === 'number' ? v.cap : null }
      }
      return null
    }
    function capacityAt(period, ns, cat, fallbackLabel) {
      const cb = period && period.metrics && period.metrics.capacity_by_ns
      if (!cb) return null
      const exact = normalizeCapacity(cb[ns] && cb[ns][cat])
      if (exact) return exact
      // 早期快照的键是 `inference/vllm-ascend`，而格子身份可能是 `inference/vllm-ascend/interrupt`
      // （叶子目录名 = category）——用 fallbackLabel 兼容，取不到就如实返回 null
      if (fallbackLabel && cb[fallbackLabel] !== undefined) return normalizeCapacity(cb[fallbackLabel])
      return null
    }
    function CapacityTrend({ periods, cell, color }) {
      const rows = []
      ;(periods || []).forEach(p => {
        if (!p || !p.metrics || !p.metrics.capacity_by_ns) return
        const at = capacityAt(p, cell.namespace, cell.category, cell.leaf || cell.category)
        if (at) rows.push({ period: p.period, count: at.count, cap: at.cap, kind: p.kind })
      })
      if (rows.length < 2) {
        return React.createElement('span', {
          title: rows.length ? '只有 1 期快照含该格数据（' + rows[0].period + '），趋势待积累' : '已有快照里没有该格数据',
          style: { color: T.text2, fontSize: 13.5, flexShrink: 0 },
        }, rows.length ? '趋势待积累' : '无历史')
      }
      const last = rows.slice(-6)
      const vals = last.map(r => r.count)
      const max = Math.max(...vals, 1)
      const delta = vals[vals.length - 1] - vals[0]
      const peakIdx = vals.indexOf(Math.max(...vals))
      const capLine = cell.cap || last[last.length - 1].cap || null
      return React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 } },
        React.createElement('span', { className: 'sleu-bars', title: last.map(r => r.period + ': ' + r.count + (r.cap ? '/' + r.cap : '')).join('\n') },
          last.map((r, i) => React.createElement('i', {
            key: i,
            className: 'sleu-bar' + ((capLine && vals[i] > capLine) ? '' : ' dim'),
            style: { height: Math.max(2, Math.round((vals[i] / max) * 18)) + 'px', background: (capLine && vals[i] > capLine) ? color : undefined },
          })),
        ),
        React.createElement('span', {
          style: { fontFamily: 'var(--font-mono)', fontSize: 13.5, color: delta > 0 ? T.warn : T.text2, flexShrink: 0 },
          title: '在已有 ' + rows.length + ' 期快照里的走势：'
            + rows.map(r => r.period + '=' + r.count).join(' → ')
            + '（起点 ' + last[0].period + '）',
        }, vals[0] + '→' + vals[vals.length - 1] + ' (' + (delta > 0 ? '+' : '') + delta + ')'),
      )
    }

    // 容量台账：逐格（framework × category）——判据逐格计，加总到 namespace 会让人看不出是哪一格爆了
    function CapacityLedger({ cells, gates, periods }) {
      if (!cells || !cells.length) return null
      const softCap = (gates || []).filter(g => g.id === 'cell_soft_cap').map(g => g.value)[0]
      const hardCap = (gates || []).filter(g => g.id === 'cell_hard_cap').map(g => g.value)[0]
      const hot = cells.filter(c => c.soft || c.hard)
      const coldest = cells.filter(c => !c.soft && !c.hard).slice(0, 3)
      const shown = hot.concat(coldest)
      return React.createElement('div', { className: 'sleu-card', style: { ...rise(1), border: '1px solid var(--hair)', borderRadius: 12, background: T.bg, backgroundImage: 'var(--surf)', marginBottom: 10, overflow: 'hidden', boxShadow: 'var(--elev-1)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', flexWrap: 'wrap' } },
          React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-amber)', display: 'inline-block' } }),
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '容量台账'),
          React.createElement('span', { style: { fontSize: 13.5, color: T.text2 } },
            '逐格 soft_cap=' + (softCap === undefined ? '—' : softCap) + (hardCap === undefined ? '' : ' / hard_cap=' + hardCap) + '（数值读 metrics/gates.yaml）'),
          hot.length ? React.createElement('span', { style: { marginLeft: 'auto' } }, pill(hot.length + ' 格越界', T.error)) 
                     : React.createElement('span', { style: { marginLeft: 'auto' } }, pill('全部格子正常', T.success)),
        ),
        React.createElement('div', { style: { padding: '0 12px 10px', display: 'flex', flexDirection: 'column', gap: 4 } },
          shown.map((c, i) => React.createElement(CapacityCell, { key: i, cell: c, periods: periods })),
          cells.length > shown.length
            ? React.createElement('div', { style: { fontSize: 13.5, color: T.text2, paddingTop: 2 } }, '其余 ' + (cells.length - shown.length) + ' 格正常（未展开）')
            : null,
        ),
      )
    }
    function CapacityCell({ cell, periods }) {
      const ratio = cell.cap > 0 ? cell.count / cell.cap : 0
      const over = cell.soft || cell.hard
      const color = cell.hard ? 'var(--acc-red)' : (cell.soft ? 'var(--acc-amber)' : 'var(--acc-green)')
      const dash = cell.cap > 0 ? Math.min(100, Math.round(ratio * 100)) : 0
      return React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 } },
        React.createElement('span', { style: { width: 6, height: 6, borderRadius: 999, background: color, flexShrink: 0 } }),
        React.createElement('span', { style: { flex: '1 1 128px', minWidth: 0, color: over ? T.text : T.text2, fontWeight: over ? 700 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)', fontSize: 12.5 } },
          cell.namespace + ' · ' + cell.category),
        React.createElement('span', { style: { width: 74, height: 5, borderRadius: 999, background: T.bg2, overflow: 'hidden', flexShrink: 0 } },
          React.createElement('span', { style: { display: 'block', width: dash + '%', height: '100%', background: color, transition: DUR ? 'width .3s ' + EASE : 'none' } })),
        React.createElement('span', { style: { width: 72, textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600, color: over ? color : T.text, flexShrink: 0 } },
          cell.count + '/' + cell.cap + (ratio > 1 ? ' ' + ratio.toFixed(1) + '×' : '')),
        React.createElement(CapacityTrend, { periods: periods, cell: cell, color: color }),
        cell.hard ? React.createElement('span', { style: tinyBadge('var(--d-red)') }, '硬上限') : (cell.soft ? React.createElement('span', { style: tinyBadge('var(--d-amber)') }, '超 soft') : null),
      )
    }

    function MetricsView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null })
      const [health, setHealth] = React.useState(null)
      const [proc, setProc] = React.useState(null)
      // 判决（闭环体检）：首屏的真正主角。缺它时如实报"体检不可用"，不假装一切正常。
      const [verdict, setVerdict] = React.useState(null)
      const [kindFilter, setKindFilter] = React.useState('live')
      const [calc, setCalc] = React.useState(null)
      const [showDataNote, setShowDataNote] = React.useState(false)
      const [fbCmd, setFbCmd] = React.useState(false)
      const [copied, setCopied] = React.useState(null)
      // 展开的期（默认只展开最近 2 个 live 期——"变了什么"优先，历史期收起来）
      const [openPeriods, setOpenPeriods] = React.useState(null)
      const [histOpen, setHistOpen] = React.useState(false)
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
        host.call('ascend-metrics-verdict', { sessionId: sessionId || null })
          .then(r => { if (alive) setVerdict(r && r.ok ? r.verdict : { __error: (r && r.error) || '体检无返回' }) })
          .catch(e => { if (alive) setVerdict({ __error: 'RPC 失败: ' + String(e && e.message || e) }) })
        return () => { alive = false }
      }, [sessionId])

      const base = { fontFamily: 'var(--font-sans)', fontSize: 'var(--t-base)', color: T.text }
      if (state.loading) return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20, color: T.text2 } }, '加载指标…')
      const r = state.data
      if (!r || !r.ok) return React.createElement('div', { style: { ...base, padding: 16, color: T.error } }, '无法读取 metrics/timeline.yaml: ' + (r && r.error || '未知错误'))

      const verdictErr = verdict && verdict.__error ? verdict.__error : null
      const vd = verdictErr ? null : verdict
      // 不可解读指标（gates.yaml 的 readability 判据，由 metrics_health.py 判定、host 透传）：
      // 分母为 0 的指标必须被标出来，绝不能安静地显示成 0——"没人回报"≠"没有误诊"。
      const unreadable = {}
      if (vd && vd.readability) {
        Object.keys(vd.readability).forEach(k => {
          if (vd.readability[k] && vd.readability[k].readable === false) unreadable[k] = vd.readability[k].why || true
        })
      }
      const isUnreadable = (key, metricName) => !!(unreadable[key] || unreadable[metricName])

      const periods = r.periods || []
      const liveCount = periods.filter(p => p.kind === 'live').length
      const order = { live: 0, replay: 1, example: 2 }
      const allShown = [...periods].sort((a, b) => (order[a.kind] ?? 3) - (order[b.kind] ?? 3))
      const shown = kindFilter === 'all' ? allShown : allShown.filter(p => p.kind === kindFilter)
      const filterChips = ['all', 'live', 'replay', 'example']
      const filterLabels = { all: '全部', live: 'live', replay: 'replay', example: 'example' }

      const lastLive = periods.filter(p => p.kind === 'live').slice(-1)[0] || null
      const livePeriods = periods.filter(p => p.kind === 'live')
      let feedbackAlert = null
      if (lastLive && lastLive.metrics) {
        const fb = lastLive.metrics.feedback_capture
        const hits = lastLive.metrics.tier2_hit
        if (fb && typeof fb === 'object' && (fb.resolved === 0 || fb.resolved === undefined) && (fb.not_resolved === 0 || fb.not_resolved === undefined) && (fb.partial === 0 || fb.partial === undefined) && hits > 0) {
          const fbCmdText = '回报 fix 结果：请逐个确认 traces/ 中已定位 case 的 session（含 feedback_pending 的）fix 应用后是否解决，按 resolved / not_resolved / partial 回报并写 feedback 事件（trace_metrics 据此更新误诊率/confidence）'
          feedbackAlert = React.createElement('div', { style: { marginBottom: 12, border: '1px solid ' + T.warn, borderRadius: 9, overflow: 'hidden' } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)' } },
              React.createElement(Dot, { color: T.warn }),
              React.createElement('span', { style: { fontSize: 13.5, fontWeight: 700, color: T.warn, whiteSpace: 'nowrap' } }, '本期快照的反馈捕获为 0'),
              React.createElement('span', { style: { fontSize: 13.5, color: T.text, flex: 1 } },
                hits + ' 次命中还没人回报结果——所以「误诊率」「误诊归因」标着不可解读（那不是 0，是没数据）'),
              React.createElement('button', { type: 'button', onClick: () => { setFbCmd(!fbCmd); setCopied(null) }, style: fbCmd ? btnPurple : btnGhost }, fbCmd ? '隐藏指令' : '回报'),
            ),
            fbCmd ? React.createElement('div', { style: { padding: '8px 12px', background: T.bg, borderTop: '1px solid ' + T.warn, fontSize: 12.5 } },
              React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 } },
                React.createElement('span', { style: { color: T.warn, fontWeight: 600 } }, '粘贴到对话即可触发回报'),
                React.createElement('button', { type: 'button', onClick: () => doCopy(fbCmdText, 'fb'), style: copied === 'fail' ? { ...btnRed, background: 'var(--d-red)' } : btnPurple },
                  copied === 'fb' ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
              ),
              React.createElement('code', { style: { userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 6, padding: '5px 8px', display: 'block', fontSize: 13.5, fontFamily: 'var(--font-mono)' } },
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

      return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 } },
          React.createElement('div', { style: { fontSize: 13.5, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-green)', display: 'inline-block' } }),
            'ascend-sleuth 指标'),
          React.createElement('span', { style: { fontSize: 13.5, color: T.text2, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 999, padding: '2px 10px' } },
            periods.length + ' 期 · live ' + liveCount),
        ),
        // ① 状态条：快照新鲜度 + 索引/磁盘 drift + 一句判读
        React.createElement(StatusBar, { verdict: vd, error: verdictErr }),
        // ② 判决：只列要处理的，附证据 + 下一步 + 可复制指令
        React.createElement(VerdictCard, { verdict: vd, error: verdictErr, copiedKey: copied, onCopy: doCopy }),
        // ③ 闭环检验（判据全貌，含正常项）+ 容量台账（**逐格**，与判据同口径）
        // ③ 体检器失效时，判决条的"处置"含义完全不同——单独说清，不让读者把
        // "没有结论"读成"没有问题"（这一条正是假绿的反面：宁可吵，不可静默）
        React.createElement(BrokenDetector, { verdict: vd, error: verdictErr }),
        React.createElement(CheckLedger, { verdict: vd, error: verdictErr }),
        React.createElement(CapacityLedger, { cells: vd && vd.capacity_cells, gates: vd && vd.gates, periods: periods }),
        // ④ 存量体检：回答"库里什么不健康"（与判决互补；容量口径不在两处各写一份）
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 12, alignItems: 'start' } },
          React.createElement(HealthPanel, { health: health }),
          React.createElement(ProcessPanel, { proc: proc }),
        ),
        feedbackAlert,
        // ⑤ 数据来源说明（早期 trace 缺事件的历史欠账）
        React.createElement('div', { style: { marginBottom: 10 } },
          React.createElement('button', { type: 'button', 'aria-expanded': showDataNote, onClick: () => setShowDataNote(!showDataNote), style: { background: 'transparent', border: 'none', padding: 0, fontSize: 13.5, color: T.text2, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, font: 'inherit' } },
            React.createElement(Chevron, { open: showDataNote, color: T.text2 }),
            '数据来源说明'),
          showDataNote ? React.createElement('div', { style: { marginTop: 6, padding: '8px 10px', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 8, fontSize: 13.5, color: T.text2, lineHeight: 1.6 } },
            '早期诊断（2026-08 前）未记录 feedback / attribution / tier3 / triage_semantic 事件，相关指标（反馈捕获、误诊归因、Tier3 兜底）为该缺失所致，非真实水平。新诊断起完整记录，欠账随新 trace 稀释。') : null,
        ),
        // ⑥ 趋势：本期 vs 上期差分（阈值语义在判决条里，这里只回答"动了什么"）
        React.createElement(CompareStrip, { prev: livePeriods.length >= 2 ? livePeriods[livePeriods.length - 2] : null, cur: livePeriods[livePeriods.length - 1] || null, isUnreadable: isUnreadable }),
        React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' } },
          filterChips.map(k => React.createElement('button', { key: k, type: 'button', onClick: () => setKindFilter(k), style: k === kindFilter ? { ...btnPrimary, padding: '3px 12px', borderRadius: 999 } : { ...btnGhost, padding: '3px 12px', borderRadius: 999 } }, filterLabels[k])),
        ),
        liveCount === 0 ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.border, borderRadius: 9, fontSize: 13.5, color: T.text2 } },
          '尚无 live 快照。首次活诊断后由 owner 追加（docs/metrics.md 汇总职责）。') : null,
        shown.length === 0 ? React.createElement('div', { style: { color: T.text2, padding: '24px 0', textAlign: 'center', fontSize: 12.5 } }, '无该类型快照')
          : React.createElement('div', null, (() => {
              // 默认展开：最近 2 个 live 期；历史期收进"历史快照"折叠区
              const recent = shown.slice(0, 2)
              const older = shown.slice(2)
              const isOpen = (p) => openPeriods === null ? recent.indexOf(p) >= 0 : !!openPeriods[p.period]
              const toggle = (p) => setOpenPeriods(Object.assign({}, openPeriods === null ? Object.fromEntries(recent.map(x => [x.period, true])) : openPeriods, { [p.period]: !isOpen(p) }))
              return React.createElement(React.Fragment, null,
                recent.map((p, i) => React.createElement(PeriodCard, { key: 'r' + i, p: p, open: isOpen(p), onToggle: () => toggle(p), isUnreadable: isUnreadable })),
                older.length ? React.createElement('div', null,
                  React.createElement('button', {
                    type: 'button', 'aria-expanded': histOpen,
                    onClick: () => setHistOpen(!histOpen),
                    style: { ...btnGhost, width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 6, marginBottom: histOpen ? 8 : 0 },
                  },
                    React.createElement(Chevron, { open: histOpen, color: T.text2 }),
                    '历史快照 ' + older.length + ' 期',
                    React.createElement('span', { style: { marginLeft: 'auto', color: T.text2, fontWeight: 400 } }, histOpen ? '收起' : '展开'),
                  ),
                  histOpen ? React.createElement('div', { style: { marginTop: 8 } },
                    older.map((p, i) => React.createElement(PeriodCard, { key: 'o' + i, p: p, open: isOpen(p), onToggle: () => toggle(p), isUnreadable: isUnreadable }))) : null,
                ) : null,
              )
            })()),
        React.createElement('div', { style: { marginTop: 14, paddingTop: 10, borderTop: '1px dashed ' + T.border, fontSize: 13.5, color: T.text2 } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' } },
            React.createElement('span', { style: { fontWeight: 700, color: T.text } }, '实时计算'),
            React.createElement('span', null, '运行 trace_metrics.py 计算当前指标（与 timeline 对照）'),
            React.createElement('button', { type: 'button', onClick: runCalc, disabled: !!(calc && calc.busy), style: { ...btnGhost, marginLeft: 'auto' } }, calc && calc.busy ? '计算中…' : '运行'),
          ),
          calc && !calc.busy && calc.data ? (
            calc.data.ok
              ? React.createElement('pre', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 9, padding: 10, fontSize: 13.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: T.text, maxHeight: 320, overflowY: 'auto', lineHeight: 1.65 } }, calc.data.output)
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