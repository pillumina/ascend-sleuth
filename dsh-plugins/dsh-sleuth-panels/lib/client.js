/* eslint-disable */
// 生成物 —— 勿手改。由 `node scripts/build_panel_bundle.js` 从下列源文件拼出：
//   dsh-plugins/ascend-panel/panel-client.js  (sha256:7288cb42199b)
//   dsh-plugins/ev-panel/panel-client.js  (sha256:9e836d4c1993)
// 校验：`node scripts/build_panel_bundle.js --check`。
//
// 面板源码是动态插件方言（靠沙箱提供的 host 通信）；这里原文嵌入页面产物，并补一层适配：
// host.call(name, args) → ctx.get('connection').rpc.call(CHANNEL, name, args)。
// React 由页面的模块表提供（与宿主同一份，不重复安装）。
window.__ModuleLoader__.load({
  id: 'dsh-sleuth-panels',
  factory: (require) => {
    const module = { exports: {} }
    const exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    const React = require('react')

    const CHANNEL = '/ascend-sleuth-panels'

    // 适配层：动态插件方言的 host.call 接到 connection RPC 上
    function makeHost(ctx) {
      const connection = ctx.get('connection')
      return {
        call(endpoint, payload, signal) {
          if (connection === undefined || connection.rpc === undefined) {
            return Promise.reject(new Error('connection 服务不可用'))
          }
          return connection.rpc
            .call(CHANNEL, String(endpoint), payload === undefined ? {} : payload, signal)
            .then((outer) => {
              if (outer === undefined || outer.ok !== true) {
                const failure = outer && outer.error
                throw new Error(failure && failure.message ? failure.message : 'RPC 失败')
              }
              return outer.value
            })
        },
      }
    }

    // 动态客户端沙箱还给每个包注入 `styles.insert(css) -> disposer`（自建 <style> 标签，
    // 随包卸载一起清）。常驻包没有这层，这里照它的语义补一个，否则面板 apply 一上来
    // `styles.insert(PANEL_CSS)` 就 ReferenceError（冒烟测试抓到过）。
    function makeStyles() {
      const tags = new Set()
      return {
        insert(css) {
          if (typeof css !== 'string') throw new Error('styles.insert(css) needs a CSS string')
          const tag = document.createElement('style')
          tag.dataset.dshSleuthPanels = 'true'
          tag.textContent = css
          document.head.append(tag)
          tags.add(tag)
          return () => { tags.delete(tag); tag.remove() }
        },
        dispose() { for (const tag of tags) tag.remove(); tags.clear() },
      }
    }

    const PANELS = [
    {
      id: 'ascend-panel',
      build(host, styles) {
        return (function () {
// ---- dsh-plugins/ascend-panel/panel-client.js (sha256:7288cb42199b) 原文开始 ----
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
    // 诊断轨迹的人读语言：内部 action 名（triage / quickly_check / load_full / miss …）是回放与归因
    // 的词表，不是阅读语言——人读视图给中文标签，原词留在 title 里供维护者回查。
    const STEP_LABELS = {
      triage: '路由分类', triage_semantic: '语义兜底路由', load_index: '读候选索引', quickly_check: '候选核验',
      load_full: '读候选正文', run_check: '逐条验证', hit: '命中', miss: '候选全未命中', tier3: '历史案例检索',
      reference_lookup: '取先验知识', procedure_follow: '按流程排查', source_analysis: '源码分析',
      attribution: '误诊归因', resume: '续接', report: '产出/修订报告', feedback: '回报结果',
    }
    // **记录维护类**动作（产出报告 / 续接 / 回报 / 归因）回答的是"记录被改了什么"，不是"问题查到哪了"。
    // 实测反馈：展开后"带了很多和问题无关的记录"——人读视图默认收起它们，完整轨迹里仍可见。
    const PROC_ACTIONS = { report: true, resume: true, feedback: true, attribution: true }
    // 先验引用的**消费点**（trace 的 `reference_lookup.purpose`，词表见 diagnosis-trace.md）：
    // 它回答"为什么要查这条"，是判断检索是否对路的一半信息，所以给人读名而不是原词。
    const PURPOSE_LABELS = {
      collect: '采集面', signature: '签名触发', fix: '修复依据', background: '背景', procedure: '流程',
    }
    // 先验引用的**三态**（trace 的 `reference_lookup.outcome`）：命中 / 查了没命中 / 没查（并写了理由）。
    // 三态是这块界面的主角——"查了没命中"与"根本没查"在纯列表里同形，而它们指向完全不同的改进动作
    // （前者是知识库覆盖缺口，后者是流程执行问题）。
    const REF_OUTCOME = {
      hit: { label: '命中', color: 'var(--d-green)' },
      miss: { label: '未命中', color: 'var(--d-amber)' },
      skipped: { label: '未查', color: 'var(--c-gray)' },
    }
    // 外部资料链接的短标签：域名 + 最后一段路径（全 URL 在 title 里，点击打开）。
    // 为什么不一整条铺开：github 的 issue 链接有 60+ 字符，三四个就把一行撑爆，而读者要认的
    // 恰恰是"哪个站、哪一条"这两件事。
    function shortUrl(u) {
      const s = String(u).replace(/^https?:\/\//i, '')
      const seg = s.split('/').filter(Boolean)
      if (seg.length <= 1) return s.slice(0, 34)
      return (seg[0] + '/…/' + seg[seg.length - 1]).slice(0, 36)
    }
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
      stop_reasons: '停止原因分布', stop_reason_unrecorded: '停止原因未记录',
      parallel_group_events: '同批并发标记', considered_candidates_events: '候选全集事件',
      trace_record_violations: '记录字段违规', trace_record_violations_total: '记录字段违规数',
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
    // 面板不是 Markdown 渲染器：期次 notes 与来源是**数据**（metrics/timeline.d/*.yaml），
    // 里面允许写强调标记，但铺到屏幕上就是字面星号（实测 2026-W37-live 的 notes 里有
    // `本期两条指标不可解读` 被两个星号包着，面板上原样显示）。显示前去掉强调标记与反引号，
    // 数据文件里仍保留原文。这条同时是两个面板共用的"无字面星号"契约的落点。
    function plainNote(s) { return String(s || '').replace(/\*\*/g, '').replace(/`/g, '') }
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
    // 交接包的三个意图（与 `export_trace.py` / `import_trace.py` 的词表一致）与体积格式化。
    // 意图标签是**给人读的**：接收侧第一屏据此知道上家期待什么（继续定位 / 复核结论 / 转上游）。
    const HANDOFF_INTENTS = [
      { id: 'continue', label: '继续定位', why: '上家没定完，交给另一台机器接着查（更多材料在那台机器上）' },
      { id: 'verify', label: '复核结论', why: '上家已给结论，交给另一台机器对照更全的现场核对' },
      { id: 'escalate', label: '转上游', why: '本地无法定位，转上游/技术支持跟进' },
    ]
    const HANDOFF_INTENT_LABEL = { continue: '继续定位', verify: '复核结论', escalate: '转上游' }
    // 体量数字取不到时**如实说"未知"，不报 0 B**：0 B 读起来是"空文件"，会让读者以为导出失败
    // （实测踩过：host 给的字段名与这里读的对不上，结果行列印 "zip 0 B + md 0 B"，而文件是好的）。
    function humanKB(n) {
      const v = Number(n)
      if (!Number.isFinite(v)) return '未知'
      if (v >= 1024 * 1024) return (v / 1024 / 1024).toFixed(1) + ' MB'
      if (v >= 1024) return (v / 1024).toFixed(0) + ' KB'
      return v + ' B'
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
    // ---- 定位报告：在面板里读（只读渲染 + 复制）----
    // 为什么要这一块：报告是这单**要交付出去**的东西（发客户 / 回贴上游），而旧面板只有
    // 「打开报告」——落到外部编辑器，36KB 的报告要么自己翻 TL;DR、要么全选复制。
    // 解析只做块级粗分（标题 / 列表 / 表格 / 代码块 / 段落），表格按原文等宽呈现：
    // 渲染得比原文更整齐，会让读者以为内容也被规整过。
    function mdBlocks(text) {
      const lines = String(text || '').split(/\r?\n/)
      const blocks = []
      const isUl = (s) => /^\s*([-*+]|\d+\.)\s+/.test(s)
      let i = 0
      while (i < lines.length) {
        const line = lines[i]
        if (!line.trim()) { i++; continue }
        if (/^\s*```/.test(line)) {
          const buf = []
          i++
          while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++ }
          i++
          blocks.push({ kind: 'code', text: buf.join('\n') })
          continue
        }
        const h = /^(#{1,6})\s+(.*)$/.exec(line)
        if (h) { blocks.push({ kind: 'h', level: h[1].length, text: h[2].trim() }); i++; continue }
        if (/^\s*\|/.test(line)) {
          const buf = []
          while (i < lines.length && /^\s*\|/.test(lines[i])) { buf.push(lines[i].replace(/\s+$/, '')); i++ }
          blocks.push({ kind: 'table', text: buf.join('\n') })
          continue
        }
        if (isUl(line)) {
          const items = []
          while (i < lines.length && isUl(lines[i])) { items.push(lines[i].trim()); i++ }
          blocks.push({ kind: 'ul', items: items })
          continue
        }
        const buf = []
        while (i < lines.length && lines[i].trim() && !/^#{1,6}\s/.test(lines[i])
          && !/^\s*\|/.test(lines[i]) && !/^\s*```/.test(lines[i]) && !isUl(lines[i])) { buf.push(lines[i]); i++ }
        blocks.push({ kind: 'p', text: buf.join('\n') })
      }
      return blocks
    }

    function mdBlockLen(b) {
      if (b.kind === 'ul') return b.items.join('\n').length
      return String(b.text || '').length
    }

    function mdNode(b, key) {
      const mono = { fontFamily: 'var(--font-mono)', fontSize: 12.5, background: T.bg, border: '1px solid ' + T.border, borderRadius: 8, padding: '8px 10px', color: T.text, lineHeight: 1.6, margin: '6px 0' }
      if (b.kind === 'h') {
        return React.createElement('div', { key: key, style: { fontWeight: 700, fontSize: b.level <= 2 ? 15 : 14.5, color: T.text, margin: b.level <= 2 ? '12px 0 6px' : '8px 0 4px', paddingBottom: b.level === 2 ? 4 : 0, borderBottom: b.level === 2 ? '1px solid var(--hair)' : 'none' } }, b.text)
      }
      if (b.kind === 'code') return React.createElement('pre', { key: key, style: { ...mono, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflowY: 'auto' } }, b.text)
      if (b.kind === 'table') return React.createElement('pre', { key: key, style: { ...mono, whiteSpace: 'pre', overflowX: 'auto' } }, b.text)
      if (b.kind === 'ul') {
        return React.createElement('div', { key: key, style: { margin: '4px 0 4px 2px' } },
          b.items.map((it, j) => React.createElement('div', { key: j, style: { display: 'flex', gap: 6, fontSize: 13.5, lineHeight: 1.75, color: T.text } },
            React.createElement('span', { style: { color: T.text2, flexShrink: 0 } }, '·'),
            React.createElement('span', { style: { minWidth: 0, wordBreak: 'break-word' } }, it.replace(/^\s*([-*+]|\d+\.)\s+/, '')))))
      }
      return React.createElement('div', { key: key, style: { fontSize: 13.5, lineHeight: 1.75, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0' } }, b.text)
    }

    // 单节渲染上限（字符）：报告最长的一节可达上万字，全铺开会把卡片撑到没法读。
    // 超限时**如实说"还有 N 块没渲染"并指向打开文件**，不静默截断。
    const REPORT_SECTION_MAX = 24000

    function ReportViewer({ state, path, onOpen, opening, section, setSection }) {
      const [copied, setCopied] = React.useState(null)
      if (!state) return null
      if (state.loading) return React.createElement('div', { style: { marginBottom: 10, color: T.text2, fontSize: 13.5 } }, '读取报告…')
      if (state.error) return React.createElement('div', { style: { marginBottom: 10, color: T.warn, fontSize: 13.5 } }, '报告读不到：' + state.error)
      const blocks = mdBlocks(state.text)
      const heads = []
      blocks.forEach((b, i) => { if (b.kind === 'h' && b.level === 2) heads.push({ i: i, text: b.text }) })
      const headEnd = heads.length ? heads[0].i : blocks.length
      const tldr = heads.filter(h => /TL;DR|摘要|结论/i.test(h.text))[0]
      const defaultSec = tldr ? tldr.i : (heads.length ? heads[0].i : -1)
      const secStart = section === null || section === undefined ? defaultSec : section
      let body = blocks.slice(0, headEnd)
      if (secStart >= 0) {
        const idx = heads.findIndex(h => h.i === secStart)
        if (idx >= 0) {
          const to = (idx + 1 < heads.length) ? heads[idx + 1].i : blocks.length
          body = body.concat(blocks.slice(secStart, to))
        }
      }
      let used = 0
      let cut = body.length
      for (let i = 0; i < body.length; i++) {
        used += mdBlockLen(body[i])
        if (used > REPORT_SECTION_MAX) { cut = i; break }
      }
      const shownBlocks = body.slice(0, cut)
      const hidden = body.length - shownBlocks.length
      return React.createElement('div', { style: { marginBottom: 12, border: '1px solid ' + T.border, borderRadius: 9, background: T.bg, overflow: 'hidden' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: T.bg2, borderBottom: '1px solid ' + T.border, flexWrap: 'wrap' } },
          React.createElement('span', { style: { fontWeight: 700, fontSize: 13.5, color: T.text } }, '定位报告'),
          React.createElement('span', { title: path, className: 'sleu-mono', style: { color: T.text2, fontSize: 11.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 } }, path),
          React.createElement('span', { style: { color: T.text2, fontSize: 11.5 } }, state.chars + ' 字' + (state.truncated ? '（已截断，看全文请打开文件）' : '')),
          React.createElement('button', { type: 'button', onClick: () => copyText(state.text).then(ok => setCopied(ok ? 'y' : 'n')), style: copied === 'y' ? btnSuccess : btnGhost, title: '复制报告全文（Markdown），可直接发给客户或回贴上游' }, copied === 'y' ? '已复制全文' : '复制全文'),
          React.createElement('button', { type: 'button', onClick: onOpen, style: btnGhost }, opening ? '打开中…' : '打开文件'),
        ),
        heads.length ? React.createElement('div', { style: { display: 'flex', gap: 5, flexWrap: 'wrap', padding: '8px 10px 0' } },
          heads.map(h => React.createElement('button', {
            key: h.i, type: 'button', onClick: () => setSection(h.i),
            style: (h.i === secStart) ? { ...btnPrimary, padding: '2px 9px', borderRadius: 999, fontSize: 11.5 } : { ...btnGhost, padding: '2px 9px', borderRadius: 999, fontSize: 11.5 },
          }, h.text)),
        ) : null,
        React.createElement('div', { style: { padding: '4px 12px 12px', maxHeight: 620, overflowY: 'auto' } },
          shownBlocks.map((b, i) => mdNode(b, i)),
          hidden > 0 ? React.createElement('div', { style: { marginTop: 6, color: T.text2, fontSize: 12.5 } }, '本节还有 ' + hidden + ' 块未渲染（超单节显示上限）——看全文请用「打开文件」。') : null,
        ),
      )
    }

    // 反馈轴的分型（host 的 `feedbackKind`）：'case' = 给了可应用 fix、等回报；'no-case' =
    // 没命中 case，等的是现场补材料。"等现场补材料"不是债，它属于"在查"那一轴——把它算进
    // "等回报"会让一个还在多轮里的会话看起来像"有个 fix 等验证"。
    // 缺该字段的老 host 输出按旧口径退化（有 feedbackPending 就当等回报），避免静默丢一桶。
    function fbKindOf(s) {
      if (!s) return null
      if (s.feedbackKind !== undefined) return s.feedbackKind
      return s.feedbackPending ? 'case' : null
    }

    // `active_case` 的分型（host 的 `activeCaseKind`）：'case' = 真定位到某个 case（库里已有，
    // 或库里还没有但形态是新的）；'placeholder' = 没命中时被写进这个字段的占位/说明串，
    // 不是 case id。缺该字段的老 host 按旧口径退化（有值就当 case）。
    // 为什么要分：占位串当 case 显示，读者会以为"定位到了 pending-investigation 这个 case"，
    // 面板还会照它生成"该 case 的 fix 生效了吗"的指令——`feedback.case` 上踩过同一个坑。
    function caseKindOf(s) {
      if (!s) return null
      if (s.activeCaseKind !== undefined) return s.activeCaseKind
      return s.activeCase ? 'case' : null
    }

    // 解析异常的一句话（host 的 `parseAnomaly`）。卡面只给"结论 + 行号"，成因与怎么办放 README——
    // 面板读者只看界面，卡上多一句解释就把列表读成文档（实测反馈：这类说明性文字被点过两次）。
    function anomalyText(a) {
      if (!a) return null
      const at = a.firstLine ? '（第 ' + a.firstLine + ' 行起）' : ''
      if (a.dropped) return '轨迹可能不完整：还有 ' + a.dropped + ' 行没被解析' + at
      return '轨迹可能不完整：有一处结构没闭合' + at
    }

    function SessionCard(props) {
      const s = props.session
      const ownerSessionId = props.sessionId
      const [open, setOpen] = React.useState(false)
      const [steps, setSteps] = React.useState(null)
      const [showCmd, setShowCmd] = React.useState(false)
      const [copied, setCopied] = React.useState(null)
      const [evOpen, setEvOpen] = React.useState(null)
      const [tcOpen, setTcOpen] = React.useState(null)   // 关联面：展开哪一步的工具调用清单
      const [opening, setOpening] = React.useState(null)
      // 打开反馈按**目标**记：谁被点，明细就显示在谁旁边（不再只落在卡头那一行）
      const [openErr, setOpenErr] = React.useState(null)    // {at, msg}
      const [openDone, setOpenDone] = React.useState(null)  // {at, via}
      // 沉淀区的**唯一展开位**：值是命令行的 key（'case' / 'cand:<候选下标>'），null = 展开位收起。
      // 与指令区同一条纪律：点谁显示谁，展开体只有一处（多候选时不铺一屏命令）。
      const [sedCmd, setSedCmd] = React.useState(null)
      const [fullTrace, setFullTrace] = React.useState(false)   // 人读视图（默认）⇄ 完整轨迹
      const [showAllSteps, setShowAllSteps] = React.useState(false)   // 轨迹区：前 8 步 ⇄ 全部步
      // 报告在面板里读（只读）：报告是交付物，读它不该先落进外部编辑器
      const [reportOpen, setReportOpen] = React.useState(false)
      const [report, setReport] = React.useState(null)
      const [reportSec, setReportSec] = React.useState(null)
      // 交接包（跨机）：把这一单交到另一台机器继续——外网定位到一半、大日志在内网时的通路。
      // 意图默认"继续定位"：得先选一下才导出，是为了让接收侧第一屏就知道上家期待什么。
      const [handoffIntent, setHandoffIntent] = React.useState('continue')
      const [handoff, setHandoff] = React.useState(null)   // {busy} | {ok, …} | {error}
      const meta = statusMeta[s.status] || statusMeta.unknown
      const canResume = RESUMEABLE[s.status]
      // 定位结论：host 标 `isConclusion`（显式 `conclusion: true`，或"人读视图可见末条是 hit"这条约定）。
      // 这里算它在**可见列表**里的位置——host 给的是原始下标，人读视图先过滤过记录维护动作，
      // 直接拿原下标会错位（这是"两个索引混用"的经典坑，故用对象身份找而不是比下标）。
      const conclusionStep = (steps && steps.list) ? (steps.list.find(st => st && st.isConclusion) || null) : null
      const conclusionAt = (steps && steps.list && conclusionStep) ? steps.list.indexOf(conclusionStep) : -1
      const shownIdx = (steps && steps.list) ? (function () {
        const all = steps.list
        const shown = fullTrace ? all : all.filter(st => !PROC_ACTIONS[st.action])
        const hidden = all.length - shown.length
        const at = (conclusionStep && shown.indexOf(conclusionStep) >= 0) ? shown.indexOf(conclusionStep) : -1
        return { all: all, shown: shown, hidden: hidden, at: at }
      })() : { all: [], shown: [], hidden: 0, at: -1 }
      // 人读视图里结论**不重复出现在轨迹末尾**（它已在上面的结论块里），只留一个回指；
      // 完整轨迹保留原事件，回放时结论仍是轨迹的一部分。
      const timeline = (!fullTrace && shownIdx.at >= 0)
        ? shownIdx.shown.filter((st, i) => i !== shownIdx.at)
        : shownIdx.shown
      // host 报的解析异常（轨迹里有没有没被读出来的行）。缺字段的老 host 按"没有异常"退化。
      const anomaly = (steps && steps.parseAnomaly) ? steps.parseAnomaly : null
      // 没有结论时给一行说明，而不是让卡片默默以某个过程步骤收尾：读者要能分辨
      // "诊断还没收尾"与"这单本身没有结论"。resolved 的单不提示（已闭环，结论在 out 口述里）。
      const noConclusionHint = (steps && steps.list && steps.list.length && s.status !== 'resolved')
        ? React.createElement('div', { style: { marginTop: 12, padding: 8, border: '1px solid ' + T.border, borderRadius: 9, fontSize: 12.5, color: T.text2 } },
            '本单还没有定位结论（轨迹末条是过程记录）。点「看完整轨迹」看全部事件，或等诊断收尾时补一条结论。')
        : null

      function toggle() {
        if (open) { setOpen(false); setSteps(null); setEvOpen(null); setTcOpen(null); return }
        setOpen(true)
        setSteps({ loading: true })
        host.call('ascend-traces-detail', { sessionId: ownerSessionId || null, traceFile: s.file })
          .then(r => setSteps({ loading: false, list: r && r.ok ? r.steps : [], summary: r && r.summary, refCount: r && r.refCount, sedimented: r && r.sedimented, sedimentCandidates: r && r.sedimentCandidates, conclusionIndex: r && typeof r.conclusionIndex === 'number' ? r.conclusionIndex : -1, parseAnomaly: r && r.parseAnomaly, error: r && r.error }))
          .catch(e => setSteps({ loading: false, list: [], error: 'RPC 失败: ' + String(e && e.message || e) }))
      }
      function doCopy(txt, key) { copyText(txt).then(ok => setCopied(ok ? key : 'fail')) }
      function openFile(f) {
        setOpening(f)
        setOpenErr(null)
        host.call('ascend-open-evidence', { sessionId: ownerSessionId || null, path: f })
          .then(r => {
            setOpening(null)
            // 成功也要看得见（3 秒后自动复位）：打了浏览器但面板一声不吭，读者同样会判成"没反应"
            if (r && r.opened) flashState(setOpenDone, { at: f, via: r.via ? String(r.via) : '' }, 3000)
            // 静默失败等于"点了没反应"：把原因显出来（旧版这里直接 reset，用户只能猜）。
            // **原因带上是哪个目标**：不然它只能渲染在卡头那一行，而点击发生在轨迹里。
            else setOpenErr({ at: f, msg: (r && r.error) ? String(r.error) : '打开失败（无返回）' })
          })
          .catch(e => { setOpening(null); setOpenErr({ at: f, msg: 'RPC 失败: ' + String(e && e.message || e) }) })
      }
      // 打开状态的**就地**呈现：chip 文案按目标切，明细紧跟在它旁边（见 openNote）。
      // 为什么必须就地：旧版把结果只渲染在卡头的 docRow 上，而证据文件与资料链接都在展开后的
      // 轨迹里——点完那一行什么都不变，读者只会说"点了没反应"（与 2026-09 修报告入口时同一个坑）。
      function openLabel(f, fallback) {
        if (opening === f) return '打开中…'
        if (openErr && openErr.at === f) return '打不开'
        // **不说"已打开"**：host 只证明了"URL 交给了浏览器"（退出码 0），它无法验证浏览器
        // 是否到前台、是否真显示了那一页。实测：从 DSH 的 shell 打开时浏览器不到前台，
        // 读者看到的是"面板说打开了、屏幕上什么都没有"。措辞只讲证据支持的那一半，
        // 另一半用「复制链接」兜住（不依赖浏览器焦点）。
        if (openDone && openDone.at === f) return '已交给浏览器'
        return fallback
      }
      function openNote(f) {
        const copyBtn = React.createElement('button', {
          type: 'button', className: 'sleu-chip', title: f,
          onClick: () => doCopy(f, 'link:' + f),
          style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 999, padding: '0 8px', fontSize: 11.5, cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' },
        }, copied === 'link:' + f ? '已复制' : '复制链接')
        if (openErr && openErr.at === f) {
          return React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', minWidth: 0 } },
            React.createElement('span', { style: { color: T.warn, fontSize: 11.5 } }, openErr.msg), copyBtn)
        }
        if (openDone && openDone.at === f) {
          return React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement('span', { style: { color: T.success, fontSize: 11.5 } },
              openDone.via ? '已交给浏览器（' + openDone.via + '）' : '已交给浏览器'), copyBtn)
        }
        return null
      }
      function baseName(f) { return String(f).split('/').pop() }
      // 报告入口：点「看报告」= 展开卡片 + 取报告正文（一次取，之后只切章节）
      function toggleReport() {
        if (reportOpen) { setReportOpen(false); return }
        setReportOpen(true)
        if (!open) toggle()
        if (!report) {
          setReport({ loading: true })
          host.call('ascend-read-report', { sessionId: ownerSessionId || null, traceFile: s.file })
            .then(rr => setReport(rr && rr.ok
              ? { text: rr.text, path: rr.path, chars: rr.chars, truncated: rr.truncated }
              : { error: (rr && rr.error) || '无返回' }))
            .catch(e => setReport({ error: 'RPC 失败: ' + String(e && e.message || e) }))
        }
      }
      function markSed(state) {
        host.call('ascend-update-sedimented', { sessionId: ownerSessionId || null, traceFile: s.file, state, caseId: s.sessionId })
          .then(r => { if (r && r.ok) { setSteps(prev => prev ? { ...prev, sedimented: { state } } : prev) } })
      }
      // 导出交接包：面板里唯一的"直接干活"入口（其余按钮只生成一条待复制的指令）。
      // 它只读 trace 与证据、落一个 traces/exports/ 下的运行时件，不改知识库也不改 trace。
      function doExportHandoff() {
        setHandoff({ busy: true })
        host.call('ascend-export-trace', {
          sessionId: ownerSessionId || null, traceFile: s.file, intent: handoffIntent,
        })
          .then(r => setHandoff(r && r.ok ? Object.assign({ ok: true }, r) : { error: (r && r.error) || '无返回' }))
          .catch(e => setHandoff({ error: 'RPC 失败: ' + String(e && e.message || e) }))
      }

      const rel = relTime(s.updatedAt || s.createdAt)
      const sed = steps && steps.sedimented
      const sedState = sed && sed.state ? sed.state : 'none'
      const sedInfo = sedMeta[sedState] || sedMeta.none
      // —— 沉淀候选：**case 与先验候选分家**（2026-09 重做）——
      // 为什么分（实测误读）：`sediment_candidates` 里 `kind: reference` 是先验知识候选，走
      // to-reference，与 case 的沉淀状态**互不影响**——case 沉淀（to-postmortem → groom）不产出
      // reference 词条。旧版把「引用计数 + case 沉淀状态 + 两类候选」挤在一个块里，读者读成
      // "reference 也跟着沉淀了"。
      // 分家后两段各带自己的入口；**面板只产指令、不产内容**——候选摘要只是引子，口径（范围/归类）
      // 在对话里由 to-reference 的 grill 对齐，那是它唯一的入口，所以这里没有编辑器。
      const cands = (steps && steps.sedimentCandidates) ? steps.sedimentCandidates : []
      const refCands = cands.filter(c => c.kind === 'reference')
      const caseCands = cands.filter(c => c.kind && c.kind !== 'reference')
      const sedLabel = (text, tip) => React.createElement('span',
        { title: tip || '', style: { color: T.text2, fontSize: 12.5, minWidth: 52, flexShrink: 0 } }, text)
      // 候选行：kind 徽标 + 一句话（超长省略，全文在 title）；只有先验候选带独立入口。
      // key 用候选在 cands 里的**原下标**，避免过滤后错位。
      const candRow = (c, ci, withAction) => {
        const key = 'cand:' + ci
        return React.createElement('div', { key: key, style: { display: 'flex', alignItems: 'center', gap: 6, marginLeft: 60, marginTop: 5, minWidth: 0 } },
          React.createElement('span', { style: tinyBadge(c.kind === 'reference' ? 'var(--d-purple)' : 'var(--d-green)') }, c.kind || '?'),
          React.createElement('span', { title: c.summary || '', style: { flex: 1, minWidth: 0, color: T.text, fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, c.summary || '(无摘要)'),
          withAction ? React.createElement('button', {
            type: 'button',
            onClick: () => { setSedCmd(sedCmd === key ? null : key); setCopied(null) },
            style: btnGhost,
            title: '生成 to-reference 指令：复制后粘到对话。范围不对就在对话里改——先验词条的口径在那一步对齐',
          }, sedCmd === key ? '隐藏指令' : '沉淀此条') : null,
        )
      }
      // 命令文本：case 走 to-postmortem，先验候选走 to-reference（把候选摘要当引子、trace 当出处）。
      // **先验候选不给 trace 路径当输入**——to-reference 没有"读 trace"这种输入模式，它的入口是
      // 内联内容 + 出处说明，所以这条指令必须把摘要原样带上。
      const sedCmdText = (function () {
        if (sedCmd === 'case') {
          return '用 /skill:to-postmortem 沉淀 ' + s.sessionId
            + '（症状/根因/fix 在 traces/' + s.file + '，证据在 traces/evidence/）'
        }
        const m = /^cand:(\d+)$/.exec(String(sedCmd || ''))
        const c = m ? cands[Number(m[1])] : null
        if (!c) return null
        return '用 /skill:to-reference 沉淀一条 reference：' + (c.summary || '(候选摘要见 trace)')
          + '（来源：traces/' + s.file + '，本单定位过程见该 trace）'
      })()
      const reportPath = s.reportFile ? 'traces/' + s.reportFile : null
      // 报告块：卡片展开时置顶（它是"这单的结论"，轨迹是过程记录）
      const reportBlock = reportOpen
        ? React.createElement(ReportViewer, {
            state: report, path: reportPath, opening: opening === reportPath,
            onOpen: () => openFile(reportPath), section: reportSec, setSection: setReportSec,
          })
        : null
      let body = null
      if (open) {
        if (steps && steps.loading) body = React.createElement('div', null, reportBlock, React.createElement('div', { style: { color: T.text2, padding: 10 } }, '加载轨迹…'))
        else if (steps && steps.list && steps.list.length) {
          body = React.createElement('div', null,
            reportBlock,
            steps.summary ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.brand + ' 6%, transparent)', border: '1px solid ' + T.border, borderRadius: 9 } },
              React.createElement(SectionLabel, { color: T.brand }, '问题背景'),
              React.createElement('div', { style: { fontSize: 13.5, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.68 } }, steps.summary),
            ) : null,
            // —— 沉淀区：case 与先验候选**分家**（2026-09 重做，修两个实测误读）——
            // ① 引用计数不再贴在这里：`reference N 次` 是"用了几次"，与"沉淀了几条"无关，
            //    贴在沉淀块正上方正是误读的来源；它已移到轨迹标题行（那里才是它的出处）。
            // ② 两段各带自己的入口：case 段给 to-postmortem 指令，先验段每条给 to-reference 指令。
            React.createElement('div', { style: { marginBottom: 10, border: '1px solid ' + T.border, borderRadius: 9, background: T.bg, overflow: 'hidden' } },
              React.createElement('div', { style: { padding: '8px 10px' } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
                  sedLabel('本单沉淀'),
                  React.createElement('span', { style: { color: sedInfo.color, fontWeight: 600, fontSize: 12.5 } }, sedInfo.label),
                  sedState === 'none' ? React.createElement('button', {
                    type: 'button', onClick: () => { setSedCmd(sedCmd === 'case' ? null : 'case'); setCopied(null) },
                    style: btnPurple, title: '生成 to-postmortem 指令：复制后粘到对话',
                  }, sedCmd === 'case' ? '隐藏指令' : '沉淀此案例') : null,
                  sedState === 'submitted' ? React.createElement(React.Fragment, null,
                    React.createElement('button', { onClick: () => markSed('knowledge'), style: btnSuccess }, '已升 Tier 2'),
                    React.createElement('button', { onClick: () => markSed('archived'), style: btnOutline(T.warn) }, '仅 Tier 3'),
                  ) : null,
                  sedState === 'archived' ? React.createElement('button', { onClick: () => markSed('knowledge'), style: btnOutline(T.success) }, '改标 Tier 2') : null,
                ),
                caseCands.map(c => candRow(c, cands.indexOf(c), false)),
              ),
              refCands.length ? React.createElement('div', { style: { borderTop: '1px solid ' + T.border, padding: '8px 10px' } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
                  sedLabel('先验候选',
                    '这些候选沉淀的是先验知识（走 to-reference），与上面本单 case 的沉淀状态互不影响'),
                ),
                refCands.map(c => candRow(c, cands.indexOf(c), true)),
              ) : null,
              sedCmdText ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, padding: '0 10px 9px' } },
                React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 6, padding: '5px 8px', fontSize: 12.5, fontFamily: 'var(--font-mono)', color: T.text, wordBreak: 'break-word', lineHeight: '18px' } },
                  sedCmdText),
                React.createElement('button', { onClick: () => doCopy(sedCmdText, 'sed'), style: copied === 'fail' ? { ...btnRed, background: 'var(--d-red)' } : btnPurple },
                  copied === 'sed' ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
              ) : null,
            ),
            // 轨迹区：**人读视图（默认）** 只给"问题查到哪了"——记录维护类动作收起、推理不铺开、
            // action 用中文标签；「看完整轨迹」回到逐条原始事件（回放/归因用）。
            // 收尾：结论块排在轨迹**之后**——卡片从现象读到过程、以定位结论落底，
            // 读者的落点在结尾而不是开头；轨迹本身末条也是结论（人读视图里不重复渲染，见 timeline）。
            (function () {
              const all = shownIdx.all
              const shown = timeline
              // 收起条数取 **shownIdx.hidden（被 PROC_ACTIONS 过滤掉的条数）**，不是 all − timeline：
              // 人读视图还会把结论那条从列表里去掉（它在下方单独成块），用差值会把它算成
              // "已收起 1 条记录维护动作"——那句话是假的，而读者会拿它推断"藏了什么"。
              const hidden = shownIdx.hidden
              // 步数多时**默认只铺前 8 步**：读者要的是"查到哪了"，而 30 步的 trace 全铺开是一屏
              // 读不完的过程记录（实测反馈："带了很多和问题无关的记录"——同一病因，上一轮修的是
              // 记录维护类动作与 reason）。折叠只影响列表：结论块在轨迹之后单独一块，不受它影响。
              const STEP_PREVIEW = 8
              const visible = showAllSteps ? shown : shown.slice(0, STEP_PREVIEW)
              const moreSteps = shown.length - visible.length
              return React.createElement('div', null,
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
                  React.createElement('span', { style: { fontSize: 12.5, color: T.text2 } },
                    fullTrace
                      ? '完整轨迹（' + all.length + ' 条原始事件，含推理与记录维护动作）'
                      : ('诊断轨迹：' + shown.length + ' 步' + (anomaly ? '（可能不完整）' : '')
                        + (hidden ? '（已收起 ' + hidden + ' 条记录维护动作）' : ''))),
                  // 引用计数归这里：它是 trace 事件的统计（reference_lookup 的条数），
                  // 与卡上任何一块"沉淀"都不是一回事——放沉淀块旁边会被读成"reference 也沉淀了"。
                  steps.refCount > 0 ? React.createElement('span', {
                    title: 'trace 里取用先验知识的次数（reference_lookup 事件条数）——这是"用了几次"，不是"沉淀了几条"',
                    style: { display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5, color: T.text2 },
                  },
                    React.createElement(Dot, { color: 'var(--acc-purple)' }),
                    '先验引用 ' + steps.refCount + ' 次') : null,
                  React.createElement('button', { type: 'button', className: 'sleu-chip', onClick: () => setFullTrace(!fullTrace), style: btnGhost },
                    fullTrace ? '只看诊断' : '看完整轨迹'),
                ),
                // 轨迹解析没收下的行：**必须说出来**。少了事件而看不出来是最坏的一种——
                // 读者会按上面那行"诊断轨迹：N 步"当成事实（实测症状：文件里 9 条、面板上 1 条，
                // 文件本身完全正常）。这里给出成因与行号，让读者能自己去核对那几行。
                anomaly ? React.createElement('div', { style: { marginBottom: 8, padding: '7px 10px', background: 'color-mix(in srgb, ' + T.warn + ' 10%, transparent)', border: '1px solid color-mix(in srgb, ' + T.warn + ' 45%, transparent)', borderRadius: 9, fontSize: 12.5, color: T.text, lineHeight: 1.65 } },
                  anomalyText(anomaly) + '。请核对这几行的缩进与引号。') : null,
                // 渲染上限：单步 output/reason 各可到 3000 字、证据原文另有上限，一条长轨迹全铺开
                // 会把卡片撑到没法读，所以列表自己滚（与报告区同一手法：maxHeight + overflowY）。
                // 短轨迹够不到上限，不会长出滚动条。
                React.createElement('div', { style: { maxHeight: 620, overflowY: 'auto' } },
                visible.map((st, i) => {
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
                  // 竖轨连的是"下一步"：后面还有没铺开的步时，最后一条可见步也要留轨（否则看起来像到头了）
                  const last = i === visible.length - 1 && moreSteps === 0
                  // —— 关联面：这一步"用到/查到了什么外部东西" ——
                  // 与「证据」分开：证据是现场材料（日志/文件），关联是外部知识（KB case / 先验词条 /
                  // 外部资料）。四类各一行、标签定宽，扫读时标签列能对齐；颜色按类型分，
                  // 且**只有真能点的才画成可点**（带边框 + 品牌色）——不可点的画成可点是最坏的误导。
                  const refOutcome = (st.action === 'reference_lookup' && st.outcome) ? REF_OUTCOME[st.outcome] : null
                  const tcOpenHere = tcOpen === i
                  const assocRows = []
                  // 只读 chip 用**填充式**（与 tinyBadge 同一配方：12% 底 + 同色字），可点的用**描边式**
                  // （透明底 + 链接色 + pointer）。这不是装饰：两类 chip 挨着出现，形状一样而一个能点
                  // 一个不能点，是读者最容易踩的误导——"填的是标签、描的是能点的"是一眼可分的规则。
                  const assocChip = (text, colorVar, title) => React.createElement('span', {
                    key: text, title: title || '',
                    style: { background: 'color-mix(in srgb, ' + colorVar + ' 12%, transparent)', color: colorVar, borderRadius: 5, padding: '1px 7px', fontSize: 11.5, fontFamily: 'var(--font-mono)', fontWeight: 600, whiteSpace: 'nowrap' },
                  }, text)
                  const assocRow = (key, label, children) => React.createElement('div', {
                    key: key, style: { display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap', marginTop: 5 },
                  },
                    React.createElement('span', { style: { color: T.text2, fontSize: 11.5, minWidth: 28, flexShrink: 0 } }, label),
                    children)
                  const capped = (arr, n) => ({ head: arr.slice(0, n), rest: arr.length - n })
                  if (st.caseId) {
                    assocRows.push(assocRow('case', 'case',
                      assocChip(st.caseId, 'var(--d-green)', '这一步核验/读到的那条 case')))
                  }
                  if (st.candidates && st.candidates.length) {
                    const c = capped(st.candidates, 6)
                    assocRows.push(assocRow('cand', '候选',
                      c.head.map(x => assocChip(x, T.text2, '本轮载入的候选 case'))
                        .concat(c.rest > 0 ? [React.createElement('span', { key: 'more', style: { color: T.text2, fontSize: 11.5 } }, '等 ' + c.rest + ' 条')] : [])))
                  }
                  if (st.refs && st.refs.length) {
                    assocRows.push(assocRow('refs', '先验',
                      (PURPOSE_LABELS[st.purpose]
                        ? [React.createElement('span', { key: 'p', style: { color: T.text2, fontSize: 11.5 } }, PURPOSE_LABELS[st.purpose])]
                        : []).concat(st.refs.map(r => assocChip(r, 'var(--d-purple)', '本轮取用的先验词条 id（可在 references/ 里按它回查）')))))
                  }
                  // 甄别理由：**这一行是全块最值钱的**——它区分"命中"与"有用"
                  // （实测例："命中但判为不同族：越界 vs 超时的 errorStr 不同"）。
                  if (st.note) {
                    assocRows.push(React.createElement('div', { key: 'note', style: { display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 5 } },
                      React.createElement('span', { style: { color: T.text2, fontSize: 11.5, minWidth: 28, flexShrink: 0 } }, '甄别'),
                      React.createElement('span', { style: { flex: 1, minWidth: 0, color: T.text2, fontSize: 12.5, lineHeight: 1.65, wordBreak: 'break-word' } }, st.note)))
                  }
                  if (st.sources && st.sources.length) {
                    assocRows.push(assocRow('src', '资料',
                      st.sources.map(u => React.createElement('button', {
                        key: u, type: 'button', onClick: () => openFile(u), title: u, className: 'sleu-chip',
                        style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 999, padding: '1px 9px', fontSize: 11.5, cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' },
                      }, openLabel(u, shortUrl(u)))).concat([openNote(st.sources[0]) || null].filter(Boolean))))
                  }
                  if (st.toolCalls && st.toolCalls.length) {
                    assocRows.push(React.createElement('div', { key: 'tc', style: { marginTop: 5, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
                      React.createElement('span', { style: { color: T.text2, fontSize: 11.5, minWidth: 28, flexShrink: 0 } }, '调用'),
                      React.createElement('button', { type: 'button', className: 'sleu-chip', onClick: () => setTcOpen(tcOpenHere ? null : i), style: btnGhost },
                        tcOpenHere ? '收起' : '看 ' + st.toolCalls.length + ' 条命令'),
                      tcOpenHere ? st.toolCalls.map((c, k) => React.createElement('div', { key: k, style: { flexBasis: '100%', color: T.text2, fontSize: 11.5, fontFamily: 'var(--font-mono)', lineHeight: 1.6, wordBreak: 'break-word' } }, '· ' + c)) : null))
                  }
                  const assocBlock = assocRows.length
                    ? React.createElement('div', { style: { marginTop: 2, paddingLeft: 9, borderLeft: '2px solid var(--hair)' } }, assocRows)
                    : null
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
                        st.action ? (fullTrace
                          ? React.createElement('span', { className: 'sleu-mono', style: { background: T.bg2, padding: '1px 7px', borderRadius: 5, fontSize: 11.5, color: T.text2 } }, st.action)
                          : React.createElement('span', { title: st.action, style: { background: T.bg2, padding: '1px 7px', borderRadius: 5, fontSize: 11.5, color: T.text2 } }, STEP_LABELS[st.action] || st.action)) : null,
                        isRef ? React.createElement('span', { className: 'sleu-chip', style: { background: 'var(--tint-purple)', color: 'var(--d-purple)', borderRadius: 999, padding: '1px 8px', fontSize: 11.5, fontWeight: 600 } }, '参考层') : null,
                        // 先验引用的三态徽标：**只挂参考层步骤**——feedback 事件也带 `outcome`
                        // （resolved/pending），那是"回报结果"，挂成"命中/未命中"会读反。
                        // 位置紧跟「参考层」：读作"参考层 · 命中"。
                        refOutcome ? React.createElement('span', {
                          title: 'trace 的 reference_lookup.outcome：命中 = 查到并用于本次推理；'
                            + '未命中 = 查了但没有相关词条（记的是知识库覆盖缺口）；未查 = 没查，理由见本步',
                          style: tinyBadge(refOutcome.color),
                        }, refOutcome.label) : null,
                        // 关联面的**存在性**提到步骤行：扫轨迹时先看哪几步带了候选/外部资料，
                        // 不必逐个展开（长 output 会把下方的行推到折叠线下）。
                        // 徽标**用行的名字、不发明伞形词**：曾叫「关联 N」「外部 N」，两个都含糊——
                        // "关联"没说清关联什么；"外部"更错（先验词条就在库里，凭什么叫外部）。
                        // 参考层步骤已有「参考层 + 三态」，不重复给徽标；候选与资料才需要计数。
                        st.candidates && st.candidates.length ? React.createElement('span', {
                          title: '本步载入了 ' + st.candidates.length + ' 条候选 case（明细在本步下方）——"看过但没选"的那一面',
                          style: tinyBadge('var(--c-gray)'),
                        }, '候选 ' + st.candidates.length) : null,
                        st.sources && st.sources.length ? React.createElement('span', {
                          title: '本步查到 ' + st.sources.length + ' 条外部资料（知识库以外的链接，明细在本步下方可点开）',
                          style: tinyBadge('var(--d-blue)'),
                        }, '资料 ' + st.sources.length) : null,
                    // 证据存在性**提到步骤行**：扫轨迹时先看哪几步带证据，不必逐个展开
                    hasEv ? React.createElement('span', { style: { display: 'flex', gap: 4, alignItems: 'center' } },
                      // 字数读 **inlineChars（原文长度）**：inline 已被 host 切片，直接量它会说"3000 字"，
                      // 而原文可能长得多——徽标是读者判断"要不要点开看"的依据，不能说小。
                      React.createElement('span', { style: tinyBadge('var(--d-green)') }, '证据' +
                        (hasInline ? ' ' + (ev.inlineChars || ev.inline.length) + '字' : '') +
                        (hasFiles ? ' ' + ev.files.length + '文件' : '')),
                      hasMissing ? React.createElement('span', { style: tinyBadge('var(--d-amber)') }, '缺 ' + ev.missing) : null,
                    ) : null,
                  ),
                  st.output ? React.createElement('div', { style: { marginTop: 4, color: T.text, fontSize: 14.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.75 } }, st.output) : null,
                  // 推理（决策依据）只在完整轨迹里铺开：它写给回放与误诊归因，不是给人读的叙述
                  // （实测：18 步的 trace 里 reason 占 2800 字，是展开后"很多无关记录"的主体）。
                  fullTrace && st.reason ? React.createElement('div', { style: { marginTop: 3, color: T.text2, fontSize: 13.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontStyle: 'italic', lineHeight: 1.68 } },
                    '推理: ' + st.reason) : null,
                  st.content ? React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 14.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.75 } }, st.content) : null,
                  // 关联面排在证据之前：读序是"这一步说了什么 → 用了什么外部东西 → 留下了什么现场材料"
                  assocBlock,
                  // 证据明细（可点开原文 / 打开文件）——存在性已在上面标了，这里给操作
                  ev ? React.createElement('div', { style: { marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, flexWrap: 'wrap' } },
                    ev.inline ? React.createElement('button', { type: 'button', onClick: () => setEvOpen(evOpenHere ? null : i), className: 'sleu-chip', style: btnGhost }, evOpenHere ? '收起原文' : '看原文') : null,
                    hasFiles ? React.createElement(React.Fragment, null,
                      React.createElement('span', { style: { color: T.text2 } }, '文件'),
                      ev.files.map(f => React.createElement('button', { key: f, type: 'button', onClick: () => openFile(f), title: f, className: 'sleu-chip', style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 999, padding: '1px 9px', fontSize: 11.5, cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' } },
                        openLabel(f, baseName(f)))),
                      openNote(ev.files[0]),
                    ) : null,
                    !hasInline && !hasFiles && hasMissing ? React.createElement('span', { style: { color: T.text2 } }, '这一步没有留证据') : null,
                  ) : null,
                  evOpenHere && ev.inline ? React.createElement('pre', { style: { marginTop: 6, background: T.bg2, border: '1px solid var(--hair)', borderRadius: 8, padding: 10, fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: T.text, lineHeight: 1.7, maxHeight: 320, overflowY: 'auto' } }, ev.inline) : null,
                  // 原文超长时**如实说**：徽标上的"证据 N 字"读的是原文长度（host 给 inlineChars），
                  // 而这里显示的是截断后的前 N 字——不说出来就成了静默截断（与报告区同一条纪律）。
                  evOpenHere && ev.inline && ev.inlineChars > ev.inline.length
                    ? React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 11.5 } },
                        '原文 ' + ev.inlineChars + ' 字，此处显示前 ' + ev.inline.length + ' 字' + (hasFiles ? '——完整原文见上方证据文件' : ''))
                    : null,
                  ),
                )
                })
                ),
                shown.length > STEP_PREVIEW ? React.createElement('div', { style: { marginTop: 8, display: 'flex', justifyContent: 'center' } },
                  React.createElement('button', { type: 'button', className: 'sleu-chip', onClick: () => setShowAllSteps(!showAllSteps), style: btnGhost },
                    showAllSteps ? '收起，只看前 ' + STEP_PREVIEW + ' 步' : '展开剩余 ' + moreSteps + ' 步')) : null,
              )
            })(),
            // —— 定位结论落底 —— //
            // 读者要的是"最后定在哪"；它排在轨迹之后，卡片以结论收尾。轨迹末条本身也是结论
            // （trace 里就能读到），人读视图里不重复渲染那条，只在完整轨迹保留原事件。
            conclusionStep ? React.createElement('div', { style: { marginTop: 12, padding: 10, background: 'color-mix(in srgb, var(--acc-green) 7%, transparent)', border: '1px solid var(--acc-green)', borderRadius: 9 } },
              React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5, flexWrap: 'wrap' } },
                React.createElement(SectionLabel, { color: 'var(--c-green)' }, '定位结论'),
                conclusionStep.step ? React.createElement('span', { className: 'sleu-num', style: { fontSize: 12.5 } }, '第 ' + conclusionStep.step + ' 步') : null,
                React.createElement('span', { style: { fontSize: 12.5, color: T.text2 } }, '轨迹末条'),
              ),
              React.createElement('div', { style: { fontSize: 14.5, color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.75 } }, conclusionStep.output || conclusionStep.content || '(该步没有 output)'),
              React.createElement('div', { style: { marginTop: 6, fontSize: 12.5, color: T.text2 } },
                fullTrace
                  ? '上方完整轨迹里保留了这条事件的原位置。'
                  : '上方轨迹略去了这条（同一段不读两遍）；「看完整轨迹」里它在原位置。'),
            ) : (noConclusionHint),
          )
        } else {
          body = React.createElement('div', null, reportBlock,
            React.createElement('div', { style: { color: T.text2, padding: 10 } }, steps && steps.error ? '加载失败: ' + steps.error : '无轨迹步骤'))
        }
      }

      let kbTag = null
      if (caseKindOf(s) === 'case') {
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
      // 占位串走「没命中」那一支：没有 case 可回写 confidence，指令里也不能出现占位串当 case 名
      if (caseKindOf(s) === 'case') {
        closeCmds.push({
          key: 'close-fix', label: '已解决 · fix 生效', tone: 'success',
          cmd: '闭环诊断 ' + s.sessionId + '：fix 已应用且验证生效（' + s.activeCase + ' 命中）。'
            + '标 status: resolved + feedback{outcome: resolved}，写一条 feedback 事件。',
        })
        closeCmds.push({
          key: 'close-nofix', label: '没解决', tone: 'warn',
          cmd: '闭环诊断 ' + s.sessionId + '：' + s.activeCase + ' 的 fix 应用后没解决问题。'
            + '标 status: resolved + feedback{outcome: not_resolved}，写一条 feedback 事件。'
            + '误诊归因按 trace 判定是 case_error 还是 execution_error。',
        })
      } else {
        closeCmds.push({
          key: 'close-fix', label: '已解决', tone: 'success',
          // 无命中单的结果**不走反馈轴**（没有 case 可回写 confidence）：结果记在 status 与 summary。
          // 同时要把遗留的 `feedback.outcome: pending` 清掉——否则"状态已结、反馈轴仍挂 pending"，
          // 面板与 resume 都会把它读成一个还在等的回报（实测这两轴就是这么打架的）。
          cmd: '闭环诊断 ' + s.sessionId + '：问题已解决。未命中知识库 case，因此不写 feedback；'
            + '标 status: resolved，并在 summary 里补一句最终怎么解决的；'
            + '若 trace 里还留着 feedback.outcome: pending（无命中单留下的占位），一并清掉。',
        })
      }
      closeCmds.push({
        key: 'close-archive', label: '不跟了', tone: 'ghost',
        cmd: '闭环诊断 ' + s.sessionId + '：不再跟进，也不判断 fix 是否有效'
          + '（问题自行消失，或环境变更后不再复现。标 status: archived，不写 feedback 事件）',
      })
      closeCmds.push({
        key: 'close-escalate', label: '转上游', tone: 'ghost',
        cmd: '闭环诊断 ' + s.sessionId + '：本地无法定位，转上游或技术支持。'
          + '标 status: escalated，不写 feedback 事件。',
      })
      if (!canResume) {
        closeCmds.push({
          key: 'reopen', label: '重新打开', tone: 'ghost',
          cmd: '把这个诊断重新打开：' + s.sessionId + '。'
          + 'status 改回 in_progress；若当时写过 feedback 事件，一并撤掉那条。',
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
      // 报告入口（diagnose 步骤 6 的产出）。**沉淀候选的明细不在这里**——它归展开态的沉淀区
      // （case 与先验候选分家、各带入口，见上方「沉淀区」）：候选与"本单沉淀状态"是同一件事的两面，
      // 拆到卡头下方与卡体深处两处，读者接不上各自的入口（旧版就是这么散的）。
      const docRow = (reportPath || s.sedimentCandidates)
        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
            reportPath ? React.createElement('button', {
              type: 'button', onClick: toggleReport, title: '在面板里读报告：TL;DR / 依据链 / 修复方案，可一键复制全文',
              style: { background: reportOpen ? 'color-mix(in srgb, ' + T.brand + ' 10%, transparent)' : 'transparent', border: '1px solid ' + T.border, color: T.text, borderRadius: 999, padding: '2px 11px', fontSize: 11.5, fontWeight: 600, cursor: 'pointer' },
            }, reportOpen ? '收起报告' : '看报告') : null,
            reportPath ? React.createElement('button', {
              type: 'button', onClick: () => openFile(reportPath), title: reportPath,
              style: { background: 'transparent', border: '1px solid ' + T.brand, color: T.brand, borderRadius: 999, padding: '2px 11px', fontSize: 11.5, fontWeight: 600, cursor: 'pointer' },
            }, opening === reportPath ? '打开中…' : '打开报告') : null,
            // 入口是**靠同名规则**找到的（trace 里没记 `report_file`）就说出来：报告明明落在
            // traces/ 里而卡片上什么都不给，读者只会以为"面板读不到报告"（实测反馈）。
            s.reportSource === 'name' ? React.createElement('span', { title: 'trace 里没有 report_file；这份报告是按 <trace 同名>.report.md 的规则找的', style: { color: T.text2, fontSize: 11.5 } },
              '（trace 未记报告名，按同名规则找到）') : null,
            // 开没开成都要看得见：成功给「已打开（via X）」，失败给原因。
            // 旧版成功无反馈、失败静默 → 用户只看到"点了没反应"。
            reportPath ? openNote(reportPath) : null,
            // 收起态只报条数（明细在展开态的沉淀区）。措辞是「建议」不是「待沉淀」：
            // 它既不是债务、也不一定会被做——尤其先验候选，要不要沉淀由人判断（诊断抛出的只是建议）。
            s.sedimentCandidates ? React.createElement('span', { style: tinyBadge('var(--d-purple)'), title: 'trace.sediment_candidates（与报告第 8 节同源）：含本单 case 与先验知识两类候选，明细见展开后的沉淀区' }, '沉淀建议 ' + s.sedimentCandidates + ' 条') : null,

          )
        : null
      // ---- 交接包：把这一单交到另一台机器（外网定位到一半、真正的大日志在内网）----
      // 这一行与别的按钮组形态不同：那几个是"选一条指令 → 复制 → 粘到对话"，本行是**直接动作**
      // （点了就导出）。理由：导出只读 trace 与证据、落一个 traces/exports/ 下的运行时件，
      // 不改知识库也不改 trace，删掉目录即撤销——不需要经 agent 的语义判断，多绕两步只是摩擦。
      // 意图必须先选：它会写进交接单，决定接收侧第一屏问什么。
      const handoffRow = React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
        React.createElement('span', { style: { color: T.text2, fontSize: 11.5 } }, '交给另一台机器：'),
        HANDOFF_INTENTS.map(it => React.createElement('button', {
          key: it.id, type: 'button', title: it.why, onClick: () => setHandoffIntent(it.id),
          style: handoffIntent === it.id
            ? { ...btnPrimary, padding: '2px 9px', borderRadius: 999, fontSize: 11.5 }
            : { ...btnGhost, padding: '2px 9px', borderRadius: 999, fontSize: 11.5 },
        }, it.label)),
        React.createElement('button', {
          type: 'button', onClick: doExportHandoff, disabled: !!(handoff && handoff.busy),
          title: '导出交接包（zip + 单文件 md）到 traces/exports/——拷到另一台机器后用 '
            + 'python3 scripts/import_trace.py <包> 接手',
          style: (handoff && handoff.busy)
            ? { ...btnOutline(T.brand), opacity: 0.6, cursor: 'default' }
            : btnOutline(T.brand),
        }, (handoff && handoff.busy) ? '导出中…' : '导出交接包'),
        handoff && handoff.ok ? React.createElement('button', {
          type: 'button', onClick: () => openFile(handoff.dirRel || 'traces/exports'), title: handoff.dir,
          style: { background: 'transparent', border: '1px solid ' + T.border, color: T.text2, borderRadius: 999, padding: '2px 9px', fontSize: 11.5, cursor: 'pointer' },
        }, '打开目录') : null,
        handoff && handoff.ok ? React.createElement('span', { style: { color: T.success, fontSize: 11.5 } },
          '已导出 zip ' + humanKB(handoff.zipBytes)
          + (handoff.md ? ' + md ' + humanKB(handoff.mdBytes) : '')
          + '｜' + handoff.files + ' 个文件'
          + ((handoff.omitted && handoff.omitted.length) ? '｜未纳入 ' + handoff.omitted.length + ' 个（体积上限）' : '')
          + ((handoff.needs && handoff.needs.length) ? '｜带 ' + handoff.needs.length + ' 条待补材料' : '')) : null,
        // 包内含原始现场证据：**标出来，不代替脱敏**——真正的闸门在数据通道上，不在面板上
        handoff && handoff.ok && handoff.redaction && handoff.redaction.state === 'raw-evidence'
          ? React.createElement('span', {
              style: tinyBadge('var(--d-amber)'),
              title: '交接单 redaction.state=raw-evidence：包内含原始现场证据（日志/配置原样）。'
                + '导出不做脱敏；外发前按你们的数据通道规则处理。',
            }, '含原始证据') : null,
        handoff && handoff.error ? React.createElement('span', { style: { color: T.warn, fontSize: 11.5 } }, handoff.error) : null,
      )
      // 展开的命令块只出现一次（谁被点开就显示谁），按钮本身用"未选中的淡一档"表达选中关系
      const actionArea = React.createElement('div', { style: { margin: '0 16px 12px', paddingTop: 10, borderTop: '1px dashed ' + T.border } },
        docRow,
        handoffRow,
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
            // 外来单（从另一台机器接手来的）：标在收起来的卡片上，因为"这单不是本机开的"
            // 会影响怎么读它的状态——比如知识库版本不一致时，候选集可能与 trace 记的对不上。
            // 依据是 traces/handoff/<sid>.yaml（import_trace.py 落位时留档）；host 读不到就不给这个标记。
            s.handoff ? React.createElement('span', {
              style: tinyBadge('var(--d-blue)'),
              title: '这一单是从另一台机器接手来的（traces/handoff/' + s.sessionId + '.yaml）：'
                + '来源主机 ' + (s.handoff.host || '未记')
                + ' · 交接意图 ' + (HANDOFF_INTENT_LABEL[s.handoff.intent] || '未记')
                + (s.handoff.importedAt ? ' · 接手于 ' + String(s.handoff.importedAt).slice(0, 19).replace('T', ' ') : '')
                + (s.handoff.renamedFrom ? ' · 本机已有同名单，落位时改名为 ' + s.sessionId : '')
                + (s.handoff.kbRevMatch === false ? ' · 接手时本机知识库版本与上家不一致' : '')
                + (s.handoff.needs ? ' · 上家留了 ' + s.handoff.needs + ' 条待补材料' : ''),
            }, '外来 · ' + (s.handoff.host ? String(s.handoff.host).split('.')[0] : '别机')) : null,
            React.createElement('span', { style: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 } },
              rel ? React.createElement('span', { style: { color: T.text2, fontSize: 12.5 } }, '更新 ' + rel) : null,
              React.createElement(Chevron, { open: open }),
            ),
          ),
          // 副行：**收起态显示"这单在查什么"**——取 trace 的问题背景段（host 带的 summarySnippet）。
          // 旧版显示"最后一步 · Agent" + 最后一个事件的 output，读者看不懂：最后一个事件常常是
          // 产出报告 / 续接 / 回报这类**记录维护**动作（实测反馈："最后一步……让人看不懂也觉得很奇怪"），
          // 它回答的是"记录被改了什么"，不是"这单在查什么"。没有背景段才退回最后一个事件的输出。
          React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 5, lineHeight: 1.6, display: 'flex', gap: 6, alignItems: 'baseline' } },
            !open && (s.summarySnippet || s.lastOutput)
              ? React.createElement(React.Fragment, null,
                  React.createElement('span', { style: { color: T.text2, flexShrink: 0 } }, s.summarySnippet ? '背景' : '末条记录'),
                  React.createElement('span', { title: s.summarySnippet || s.lastOutput, style: { color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, s.summarySnippet || s.lastOutput),
                )
              : React.createElement('span', null, [s.framework, s.platform, s.category].filter(Boolean).join(' · ') || '—'),
          ),
          caseKindOf(s) === 'case' ? React.createElement('div', { style: { marginTop: 5, fontSize: 13.5, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement('span', { style: { color: T.text2 } }, '定位'),
            React.createElement('code', { style: { background: 'color-mix(in srgb, ' + T.success + ' 10%, transparent)', color: T.success, padding: '1px 7px', borderRadius: 5, fontSize: 12.5, fontFamily: 'var(--font-mono)' } }, s.activeCase),
          ) : React.createElement('div', { style: { marginTop: 5, fontSize: 12.5, display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' } },
            React.createElement('span', { style: { color: T.text2 } }, '未定位到知识库 case'),
            // trace 里写了占位串就把它原样摆出来（不摆，读者会以为面板漏读了字段），但**卡面不解释**：
            // 那句"这是什么、不是什么"是给改 trace 的人看的，放 tooltip 与 README。判据在
            // panel_render_check：占位串只出原值，不出内部说法（占位串 / case id / 字段名）。
            caseKindOf(s) === 'placeholder' ? React.createElement('span', { title: 'trace 里记的定位值（不是知识库里的 case）', className: 'sleu-mono', style: { color: T.text2, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.activeCase) : null,
          ),
          React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 4 } },
            '轨迹: ' + s.userSteps + ' 用户输入 / ' + s.agentSteps + ' agent 步骤'),
          // 步数由同一份解析结果算出：解析少了就得说，否则"1 用户输入"看起来像这单只有一步。
          s.parseAnomaly ? React.createElement('div', { style: { color: T.warn, fontSize: 13.5, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: T.warn }),
            anomalyText(s.parseAnomaly)) : null,
          // 两条轴的**话术分开**：有可应用 fix 才叫"结果待回报"；没命中 case 的单等的是材料，
          // 而"等什么"trace 里已经写着（最近一条 `evidence.missing`，退到 `last_action`）——
          // 直接把它显示出来，读者不用展开轨迹去猜。这一类用中性色：它不是债。
          fbKindOf(s) === 'case' ? React.createElement('div', { style: { color: T.warn, fontSize: 13.5, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: T.warn }),
            '结果待回报：' + (s.feedbackCase || (caseKindOf(s) === 'case' ? s.activeCase : '') || '命中 case') + '（下方可生成回报指令）') : null,
          fbKindOf(s) === 'no-case' ? React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 4, display: 'flex', alignItems: 'baseline', gap: 6 } },
            React.createElement('span', { style: { flexShrink: 0 } }, '等现场补材料：'),
            React.createElement('span', { title: s.waitingFor || '', style: { color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } },
              s.waitingFor ? (s.waitingFor.length > 60 ? s.waitingFor.slice(0, 60) + '…' : s.waitingFor) : '本次诊断缺的材料（见轨迹里的「缺」标记）'),
          ) : null,
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
      // 待跟进**三类互斥**（此前重复计数：`status: in_progress` 的定义含"结论已给但用户在跟进"，
      // 于是"已给 fix 等回报"的单同时落进旧的 nActive 与 nPending，1 单显示成 2 项待跟进）：
      //   在查   = in_progress、**没有** pending 回报、且回报不是已生效 —— 诊断还没结论（含等用户补材料）→ 续接
      //   等回报 = 有 pending 回报（不论 status）—— 已给结论/方案等着验证 → 追问结果
      //   该闭环 = 回报已 resolved 但 status 还停在 in_progress —— 验证过了、状态没更新 → 标闭环
      // 三者之和 = 面板徽章的"待跟进"数（不再有重复计入的项；三条条件互斥，见下面各自的谓词）。
      const isClosedButOpen = s => s.status === 'in_progress' && s.feedback === 'resolved'
      const nLooking = sessions.filter(s => s.status === 'in_progress' && fbKindOf(s) !== 'case' && !isClosedButOpen(s)).length
      const nAwaiting = sessions.filter(s => fbKindOf(s) === 'case').length
      const nClose = sessions.filter(isClosedButOpen).length
      // 计数按 caseKindOf 算：占位串那一类归「未定位」，不该被算成"新形态待沉淀"
      const nInKb = sessions.filter(s => caseKindOf(s) === 'case' && s.activeCaseInKb).length
      const nNew = sessions.filter(s => caseKindOf(s) === 'case' && !s.activeCaseInKb).length
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
      if (kbFilter === 'kb') sessions = sessions.filter(s => caseKindOf(s) === 'case' && s.activeCaseInKb)
      if (kbFilter === 'new') sessions = sessions.filter(s => caseKindOf(s) === 'case' && !s.activeCaseInKb)
      if (kbFilter === 'miss') sessions = sessions.filter(s => caseKindOf(s) !== 'case')
      // 待跟进三类见上方计数处注释（互斥）；徽章与横幅都用这三个数
      const badge = [
        (r.sessions || []).length + ' 会话',
        nInKb ? nInKb + ' 库中已有' : null,
        nNew ? nNew + ' 新形态' : null,
        nLooking ? nLooking + ' 在查' : null,
        nAwaiting ? nAwaiting + ' 等回报' : null,
        nClose ? nClose + ' 该闭环' : null,
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
      const nFollow = nLooking + nAwaiting + nClose
      return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, gap: 10, flexWrap: 'wrap' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-blue)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 18, fontWeight: 700 } }, '诊断状态'),
          ),
          React.createElement('span', { title: badge, style: { fontSize: 12.5, color: T.text2, background: T.bg2, border: '1px solid var(--hair)', borderRadius: 999, padding: '3px 11px' } },
            nFollow ? (nFollow + ' 项待跟进') : ((r.sessions || []).length + ' 个会话')),
        ),
        // 待跟进提示：只在真有的时候出现，且给"下一步做什么"。
        // 三类各自对应一个动作（续接 / 追问结果 / 标闭环），所以分开说；末尾一句点明这是两条轴，
        // 免得读者把"在查"与"等回报"读成同一件事的两句话。
        nFollow ? React.createElement('div', { style: { ...rise(0), display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '8px 12px', marginBottom: 10, background: 'var(--tint-amber)', border: '1px solid var(--hair)', borderRadius: 10, fontSize: 13.5, color: T.text } },
          React.createElement(Dot, { color: T.warn, size: 7 }),
          nLooking ? React.createElement('span', null, nLooking + ' 个在查') : null,
          nLooking && (nAwaiting || nClose) ? React.createElement('span', { style: { color: T.text2 } }, '·') : null,
          nAwaiting ? React.createElement('span', null, nAwaiting + ' 个等回报') : null,
          nAwaiting && nClose ? React.createElement('span', { style: { color: T.text2 } }, '·') : null,
          nClose ? React.createElement('span', null, nClose + ' 个该闭环') : null,
          React.createElement('span', { style: { color: T.text2, marginLeft: 'auto', fontSize: 12.5 } }, '在查=诊断没结论（含等现场补材料）；等回报=结论已给、fix 没验证｜卡片里点按钮生成指令 → 复制 → 粘到对话执行'),
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
      // 索引头注里不再写日期与条数（数字一进 git 就会在并发合并时撞行/漂移，改成现算：
      // scripts/index_counts.py）。所以这里不再有"索引生成于 X"可显；改显**索引条目数 vs 磁盘**，
      // 两者不等才是真要处理的事（索引丢了条目 → 跑 build_index.py）。
      if (c.error) {
        // 用 total（不是 value）走"带结构"那条渲染分支：MetricRow 只在带 total/node 时才渲染 sub，
        // 用 value 的话原因会被静静丢掉——那正好又是"读不到和少一块长得一样"。
        caseRows.push(React.createElement(MetricRow, {
          key: 'cerr', label: '知识库统计', total: '读不到', warn: true,
          sub: '原因：' + String(c.error) + ' · 手工复现：python3 scripts/index_counts.py',
        }))
      } else if (c.total) {
        const drift = (typeof c.diskTotal === 'number' && typeof c.declaredTotal === 'number') ? c.diskTotal - c.declaredTotal : 0
        caseRows.push(React.createElement(MetricRow, {
          key: 'ct', label: 'case 总数', value: c.total,
          sub: '磁盘 ' + c.diskTotal + ' 条'
            + (drift ? '，索引落后 ' + drift + ' 条 → 跑 build_index.py' : '，索引与磁盘一致'),
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
          p.title ? React.createElement('div', { style: { color: T.text, fontSize: 13.5, marginTop: 3, lineHeight: 1.65 } }, plainNote(p.title)) : null,
          p.source ? React.createElement('div', { style: { color: T.text2, fontSize: 13.5, marginTop: 3, wordBreak: 'break-word', lineHeight: 1.65 } }, '来源: ' + plainNote(p.source)) : null,
          metricKeys.length ? React.createElement('div', { style: { marginTop: 9, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 12px' } },
            metricKeys.map(k => {
              const v = p.metrics[k]
              const total = ratioTotal(v)
              const small = total !== null && total > 0 && total < 5
              return React.createElement(MetricRow, { key: k, label: METRIC_LABELS[k] || k, value: fmtVal(v), small: small, unreadable: !!unread(k), unreadableWhy: unread(k) === true ? null : unread(k) })
            }),
          ) : null,
          p.notes && p.notes.trim() ? React.createElement('div', { style: { marginTop: 9, padding: '7px 10px', background: 'color-mix(in srgb, ' + T.brand + ' 5%, transparent)', borderLeft: '3px solid ' + T.brand, borderRadius: 5, fontSize: 13.5, color: T.text2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.68 } },
            plainNote(p.notes)) : null,
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
      if (/cell_|容量|读入/.test(f + t)) return { label: '看读入成本', command: 'python3 scripts/index_read_cost.py —— 看是哪一格贵、贵在多少 token；要省先看行宽/字段（scripts/build_index.py 的读侧视图），再评估按平台轴切分。' }
      if (/feedback|反馈/.test(f + t)) return { label: '补反馈', command: '回报 fix 结果：逐个确认 traces/ 中已定位 case 的 session（含 feedback.outcome: pending 的）fix 应用后是否解决。按 resolved / not_resolved / partial 写 feedback 事件。' }
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

    function StatusBar({ verdict, error, onRefresh, refreshing }) {
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
          // 重跑入口：**体检结果在 30 秒窗口内复用**（切走再切回不重跑 Python），窗口过期自动重跑。
          // 这一行必须说清窗口的存在——否则读者会把复用结果读成实时（原则十）。
          React.createElement('button', {
            type: 'button', onClick: onRefresh, disabled: !!refreshing,
            title: '体检跑 scripts/metrics_health.py（约 1 秒）。结果在 30 秒内复用上次的，'
              + '切走再切回不重跑；点此绕过窗口立即重跑',
            style: refreshing ? { ...btnGhost, opacity: .6, cursor: 'default' } : btnGhost,
          }, refreshing ? '体检中…' : '重新体检'),
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

    function VerdictCard({ verdict, error, pending, copiedKey, onCopy }) {
      const findings = (verdict && verdict.findings) || []
      const fail = findings.filter(f => f.level === 'fail')
      const warn = findings.filter(f => f.level === 'warn')
      const okN = findings.filter(f => f.level === 'ok').length
      const shown = fail.concat(warn)
      const cmds = (verdict && verdict.candidate_commands) || []
      // 加载窗口内**不能说"没问题"**：判决 RPC 要 spawn Python，而 timeline 是文件读，
      // 两者之间有真实的一段窗口（实测首屏先出现下面那句话）。旧版在这段窗口里走
      // `shown.length === 0` 分支，于是打印绿勾「本期无阻塞项 · 按 0 条判据检查，全部通过」
      // ——"按 0 条判据检查"本身就是结论不可用的证据，却被渲染成通过。这与本面板
      // 反复修掉的假绿是同一类：**没被检查 ≠ 没越界**。
      const head = error
        ? React.createElement('span', { style: { color: T.warn, fontSize: 12.5 } }, error)
        : (pending
            ? React.createElement('span', { style: { fontSize: 13.5, color: T.text2 } }, '体检结果读取中…（结论未到之前，这里不显示"无阻塞项"）')
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
                ' · ' + okN + ' 项正常')))
      return React.createElement('div', { className: 'sleu-card', style: { ...rise(0), border: '1px solid var(--hair)', borderTop: '2px solid ' + ((error || pending) ? T.border : (fail.length ? 'var(--acc-red)' : 'var(--acc-green)')), borderRadius: 12, background: T.bg, backgroundImage: 'var(--surf)', marginBottom: 10, overflow: 'hidden', boxShadow: 'var(--elev-1)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', flexWrap: 'wrap' } },
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '现在什么坏了'),
          head,
          (error || pending) ? null : React.createElement('span', { style: { marginLeft: 'auto', color: T.text2, fontSize: 12.5 } }, '点开看证据与下一步'),
        ),
        shown.map((row, i) => React.createElement(VerdictRow, { key: i, row: row, copiedKey: copiedKey, onCopy: onCopy })),
        !error && !pending && shown.length === 0 && cmds.length ? React.createElement('div', { style: { padding: '8px 12px', background: T.bg2, borderTop: '1px solid ' + T.border } },
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
    //   ① `{count, tok}` 字典（2026-09-29 起带读入成本；此前是 `{count, cap}`）
    //   ② `"36/30"` 字符串（W35/W36-capacity，`build_index.py` 头注快照）
    //   ③ 整个 `capacity_by_ns` 缺席（诊断侧 live 快照不含结构指标）
    // 只认 ① 的话趋势永远只有 1 个点、什么也画不出来——而"容量从哪涨上来的"正是本轮要回答的。
    // 归一后不变量：**当前值以判决（体检器对磁盘现实的判定）为准**，历史只用来画走势。
    function normalizeCapacity(v) {
      if (typeof v === 'number') return { count: v, cap: null, tok: null }
      if (typeof v === 'string') {
        const m = /^\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(v)
        if (m) return { count: Number(m[1]), cap: Number(m[2]), tok: null }
        return null
      }
      if (v && typeof v === 'object' && typeof v.count === 'number') {
        return { count: v.count, cap: typeof v.cap === 'number' ? v.cap : null,
                 tok: typeof v.tok === 'number' ? v.tok : null }
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
      const softTok = (gates || []).filter(g => g.id === 'cell_read_soft_tok').map(g => g.value)[0]
      const hardTok = (gates || []).filter(g => g.id === 'cell_read_hard_tok').map(g => g.value)[0]
      const hot = cells.filter(c => c.soft || c.hard)
      const coldest = cells.filter(c => !c.soft && !c.hard).slice(0, 3)
      const shown = hot.concat(coldest)
      return React.createElement('div', { className: 'sleu-card', style: { ...rise(1), border: '1px solid var(--hair)', borderRadius: 12, background: T.bg, backgroundImage: 'var(--surf)', marginBottom: 10, overflow: 'hidden', boxShadow: 'var(--elev-1)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', flexWrap: 'wrap' } },
          React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-amber)', display: 'inline-block' } }),
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 15, fontWeight: 700 } }, '容量台账'),
          React.createElement('span', { style: { fontSize: 13.5, color: T.text2 } },
            '逐格：查一次问题要读进来多少字（评估线 ' + (softTok === undefined ? '—' : softTok)
            + (hardTok === undefined ? '' : ' / 硬线 ' + hardTok) + '，数值读 metrics/gates.yaml）'),
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
      // 判据量是**读入 token**（软线 8000 / 硬线 20000，来自 gates.yaml）；条数退成括号里的观察值。
      const cap = cell.hard_tok || cell.soft_tok || 0
      const ratio = cap > 0 && cell.tok != null ? cell.tok / cap : 0
      const over = cell.soft || cell.hard
      const color = cell.hard ? 'var(--acc-red)' : (cell.soft ? 'var(--acc-amber)' : 'var(--acc-green)')
      const dash = cap > 0 ? Math.min(100, Math.round(ratio * 100)) : 0
      return React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 } },
        React.createElement('span', { style: { width: 6, height: 6, borderRadius: 999, background: color, flexShrink: 0 } }),
        React.createElement('span', { style: { flex: '1 1 128px', minWidth: 0, color: over ? T.text : T.text2, fontWeight: over ? 700 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)', fontSize: 12.5 } },
          cell.namespace + ' · ' + cell.category),
        React.createElement('span', { style: { width: 74, height: 5, borderRadius: 999, background: T.bg2, overflow: 'hidden', flexShrink: 0 } },
          React.createElement('span', { style: { display: 'block', width: dash + '%', height: '100%', background: color, transition: DUR ? 'width .3s ' + EASE : 'none' } })),
        React.createElement('span', { style: { width: 72, textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600, color: over ? color : T.text, flexShrink: 0 } },
          cell.tok != null ? cell.tok + ' tok' : '—',
          React.createElement('span', { style: { color: T.text2, fontWeight: 400 } }, '（' + cell.count + ' 条）')),
        React.createElement(CapacityTrend, { periods: periods, cell: cell, color: color }),
        cell.hard ? React.createElement('span', { style: tinyBadge('var(--d-red)') }, '超硬线') : (cell.soft ? React.createElement('span', { style: tinyBadge('var(--d-amber)') }, '超评估线') : null),
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
      // 体检中：只在**显式重跑**时为真（首屏那次由 verdict 为 null 表达"读取中"，见 verdictPending）
      const [verdictBusy, setVerdictBusy] = React.useState(false)
      // 重跑体检：`refresh: true` 让 host 绕过复用窗口（窗口内切走再切回不重跑，见 panel-host.js）。
      // 原先读者没有任何出口——host 按 cwd 永久缓存，改了脚本或数据也只能重载插件。
      const refreshVerdict = () => {
        setVerdictBusy(true)
        setVerdict(null)
        host.call('ascend-metrics-verdict', { sessionId: sessionId || null, refresh: true })
          .then(r => setVerdict(r && r.ok ? r.verdict : { __error: (r && r.error) || '体检无返回' }))
          .catch(e => setVerdict({ __error: 'RPC 失败: ' + String(e && e.message || e) }))
          .then(() => setVerdictBusy(false))
      }
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
      // timeline 读不到时**不再整页早退**：判决、知识库健康、实时计算都不经过 timeline
      // （host 侧就是这么分的），早退等于把"能用的一半"也一起藏了——旧实现如此，并且
      // host 的提示文案还写着"闭环判决仍然可用"，界面与承诺相反。
      const timelineError = (!r || !r.ok) ? ((r && r.error) || '未知错误') : null
      const timelineUnparsed = !timelineError && !!(r && r.integrity === 'unparsed')
      // 判决与 timeline 是两条独立 RPC；verdict 仍为 null 表示"还没回来"，不是"没问题"。
      const verdictPending = verdict === null

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

      const periods = (!timelineError && r && Array.isArray(r.periods)) ? r.periods : []
      const liveCount = periods.filter(p => p.kind === 'live').length
      const order = { live: 0, replay: 1, example: 2 }
      // 期次新旧：**以期号里的周序为主、recorded_at 为辅**。只用 recorded_at 会有并列：
      // 实测 2026-W35-live1 与 2026-W36-live2 的 recorded_at 都是 2026-08-31（早期补录），
      // 并列时稳定排序保留文件顺序，于是"最新两期"里混进 W35（比 W36 旧一周）。
      const weekKey = (p) => {
        const w = /(\d{4})-W(\d{2})/.exec(String((p && p.period) || ''))
        return w ? Number(w[1]) * 100 + Number(w[2]) : -1
      }
      const dateKey = (p) => {
        const ra = /^(\d{4})-(\d{2})-(\d{2})/.exec(String((p && p.recorded_at) || ''))
        return ra ? Number(ra[1] + ra[2] + ra[3]) : -1
      }
      const newer = (a, b) => (weekKey(a) - weekKey(b)) || (dateKey(a) - dateKey(b))
        || String(a && a.period).localeCompare(String(b && b.period))
      // 展示顺序：kind 优先（live 在前），同 kind 内**按时间倒序**——默认展开的两期必须是
      // 最新的两期。旧实现只按 kind 排（稳定排序保留文件顺序 = 最旧在前），于是
      // `recent = shown.slice(0, 2)` 展开的是最老的两期，最新一期反被收进「历史快照」，
      // 而正上方「本期变化」讲的正是那一期（实测 2026-W37-live 被折叠、趋势条从最旧起步）。
      const allShown = [...periods].sort((a, b) =>
        ((order[a.kind] ?? 3) - (order[b.kind] ?? 3)) || newer(b, a))
      const shown = kindFilter === 'all' ? allShown : allShown.filter(p => p.kind === kindFilter)
      const filterChips = ['all', 'live', 'replay', 'example']
      const filterLabels = { all: '全部', live: 'live', replay: 'replay', example: 'example' }

      // live 期按时间升序：`lastLive`（判新鲜度）与「本期变化」都依赖"哪个最新"，
      // 不依赖文件里的先后（生成物的顺序是构建产物，不是契约）。
      const livePeriods = periods.filter(p => p.kind === 'live').slice().sort((a, b) => newer(a, b))
      const lastLive = livePeriods.length ? livePeriods[livePeriods.length - 1] : null
      let feedbackAlert = null
      if (lastLive && lastLive.metrics) {
        const fb = lastLive.metrics.feedback_capture
        const hits = lastLive.metrics.tier2_hit
        if (fb && typeof fb === 'object' && (fb.resolved === 0 || fb.resolved === undefined) && (fb.not_resolved === 0 || fb.not_resolved === undefined) && (fb.partial === 0 || fb.partial === undefined) && hits > 0) {
          const fbCmdText = '回报 fix 结果：请逐个确认 traces/ 中已定位 case 的 session（含 feedback.outcome: pending 的）fix 应用后是否解决。按 resolved / not_resolved / partial 回报并写 feedback 事件；trace_metrics 据此更新误诊率与 confidence。'
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

      // timeline 的三种结局分开渲染：**读不到** / **解析不出期次** / 正常。
      // 中间那一态是本轮实测出来的缺口：解析器与文件结构不符时，旧实现拿到空数组，
      // 于是显示「尚无 live 快照」——文件里 3 期 live 摆着，面板说没有。数据在、结论假，
      // 与"没报越界"被读成"没越界"属同一类，所以这里也单独给一句不可解读声明。
      const timelineWarnCard = (title, body, command) => React.createElement('div', { style: { marginBottom: 10, padding: '9px 11px', background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.warn, borderRadius: 9, fontSize: 13.5, color: T.text, lineHeight: 1.65 } },
        React.createElement('div', { style: { fontWeight: 700, color: T.warn, marginBottom: 3 } }, title),
        React.createElement('div', { style: { color: T.text } }, body),
        command ? React.createElement('code', { style: { display: 'block', marginTop: 6, userSelect: 'all', background: T.bg, border: '1px solid var(--hair)', borderRadius: 6, padding: '5px 8px', fontSize: 12.5, fontFamily: 'var(--font-mono)' } }, command) : null,
      )
      const periodCards = shown.length === 0
        ? React.createElement('div', { style: { color: T.text2, padding: '24px 0', textAlign: 'center', fontSize: 12.5 } }, '无该类型快照')
        : React.createElement('div', null, (() => {
            // 默认展开：最近 2 期；历史期收进"历史快照"折叠区（顺序见 allShown 的注释）
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
          })())
      const timelineBlock = timelineError
        ? timelineWarnCard(
            '期次与趋势不可读',
            'metrics/timeline.yaml 读不到：' + timelineError + '。上面的判决与下面的实时计算不经过它，仍按各自的数据源显示。',
            null)
        : (timelineUnparsed
            ? timelineWarnCard(
                '期次一条都没解析出来，这不是"没有数据"',
                'metrics/timeline.yaml 里声明了 periods，面板的解析器却一期都没读出来。所以「本期变化」「历史快照」「容量趋势条」这一块不可解读，不要把它读成"没有期次"。',
                'python3 scripts/build_timeline.py --check')
            : React.createElement(React.Fragment, null,
                // 本期 vs 上期差分（阈值语义在判决条里，这里只回答"动了什么"）
                React.createElement(CompareStrip, { prev: livePeriods.length >= 2 ? livePeriods[livePeriods.length - 2] : null, cur: livePeriods[livePeriods.length - 1] || null, isUnreadable: isUnreadable }),
                React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' } },
                  filterChips.map(k => React.createElement('button', { key: k, type: 'button', onClick: () => setKindFilter(k), style: k === kindFilter ? { ...btnPrimary, padding: '3px 12px', borderRadius: 999 } : { ...btnGhost, padding: '3px 12px', borderRadius: 999 } }, filterLabels[k])),
                ),
                liveCount === 0 ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.border, borderRadius: 9, fontSize: 13.5, color: T.text2 } },
                  '尚无 live 快照。首次活诊断后由 owner 追加（docs/guide/metrics.md 汇总职责）。') : null,
                periodCards))

      return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 } },
          React.createElement('div', { style: { fontSize: 13.5, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 4, background: 'var(--acc-green)', display: 'inline-block' } }),
            'ascend-sleuth 指标'),
          React.createElement('span', { style: { fontSize: 13.5, color: T.text2, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 999, padding: '2px 10px' } },
            timelineError ? '期次不可读'
              : (timelineUnparsed ? '期次解析失败'
                : (periods.length + ' 期 · live ' + liveCount))),
        ),
        // ① 状态条：快照新鲜度 + 索引/磁盘 drift + 一句判读
        React.createElement(StatusBar, { verdict: vd, error: verdictErr, onRefresh: refreshVerdict, refreshing: verdictBusy }),
        // ② 判决：只列要处理的，附证据 + 下一步 + 可复制指令
        React.createElement(VerdictCard, { verdict: vd, error: verdictErr, pending: verdictPending, copiedKey: copied, onCopy: doCopy }),
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
            '2026-08 之前的诊断没有记录四类事件：feedback、attribution、tier3、triage_semantic；'
            + '因此反馈捕获、误诊归因、Tier3 兜底三项指标偏低，不代表真实水平。',
            React.createElement('br', null),
            '新诊断已完整记录，这三项指标会随新 trace 累积逐步回到真实水平。') : null,
        ),
        // ⑥ 趋势：本期 vs 上期差分 + 期卡（timeline 不可读 / 解析不出期次时**分开说清**）
        timelineBlock,
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
// ---- 原文结束 ----
        })()
      },
    },
    {
      id: 'ev-panel',
      build(host, styles) {
        return (function () {
// ---- dsh-plugins/ev-panel/panel-client.js (sha256:9e836d4c1993) 原文开始 ----
// ev-panel client —— 自演进看板（conversation.view 第三个 tab「自演进」）
// 数据经 host.call('ev-board-load') 从 scripts/ev_board_data.py 汇总；
// 单卡全文经 host.call('ev-idea-detail') 点开时才拉（列表页只带摘要）。
// 纯 React.createElement，无 JSX/TS。主题用 --dsw-alias-* CSS 变量（与 ascend-panel 一致）。
//
// 设计取向（2026-09 重做）：
//   ① 信息架构：待办/待审优先（现在该看哪张卡）→ 可展开决策流（到底是什么、改了什么）
//      → 自演进度量（而不是"一共几张卡"）。已采纳且无缺口的卡收进归档，不刷屏。
//   ② 视觉：**精密仪器感**——发丝线分隔、等宽数字对齐、克制的状态色、紧凑的竖向节奏。
//      样式走 styles.insert(css) 的 class 体系（内联 style 做不到 hover/focus/过渡），
//      颜色一律用主题变量 + color-mix 派生，亮/暗两套主题都不崩。
//   ③ 动效：120-200ms ease-out 的微交互（hover 抬升、展开淡入、chevron 旋转、
//      首屏分段浮现），尊重 prefers-reduced-motion。
return {
  apply(ctx) {
    const slots = ctx.get('slots')
    if (slots === undefined) return

    const mono = 'ui-monospace,SFMono-Regular,Menlo,monospace'

    // EV 卡状态词表 v5 —— 以 scripts/verify_proposals.py 的 VALID_STATUS 为准。
    // 旧版的 candidate/proposed/pending_merge/adopted/rolled_back 是 v1 词表，v5 下永不出现；
    // rejected/superseded 反而是合法终态却被漏渲染。这里只列真实存在的四个状态。
    const STATUS_META = {
      in_experiment: { label: '实验中', color: 'var(--c-blue)', fill: 'var(--fill-blue)', acc: 'var(--acc-blue)', hint: '已产出卡片，正在执行与验证' },
      validated: { label: '已采纳', color: 'var(--c-green)', fill: 'var(--fill-green)', acc: 'var(--acc-green)', hint: '验证通过，改动保留' },
      rejected: { label: '未采纳', color: 'var(--c-gray)', fill: 'var(--fill-gray)', acc: 'var(--acc-gray)', hint: '验证未通过，改动未保留' },
      superseded: { label: '已替代', color: 'var(--c-gray)', fill: 'var(--fill-gray)', acc: 'var(--acc-gray)', hint: '改由后续卡片接手' },
    }
    const LAYER_LABELS = { L1: '内容', L2: '流程', L3: '机制' }
    const AUTH_META = {
      auto: { label: 'auto', color: 'var(--c-green)', hint: '低风险且可回退，自动合入' },
      review: { label: 'review', color: 'var(--c-blue)', hint: '中等风险，人工审阅 PR' },
      dual: { label: 'dual', color: 'var(--c-red)', hint: '高风险，需双人签核' },
    }
    const METHOD_LABELS = {
      golden_replay: 'golden 回放', metrics_compare: '指标对照',
      issue_replay: 'S2 issue 回放', scan_review: '扫描 + 人审',
    }
    const DEC_TYPE = {
      proposal: { label: '提案', color: 'var(--c-purple)', acc: 'var(--acc-purple)' },
      action: { label: '执行', color: 'var(--c-blue)', acc: 'var(--acc-blue)' },
      eval: { label: '验证', color: 'var(--c-amber)', acc: 'var(--acc-amber)' },
      decision: { label: '判断', color: 'var(--c-green)', acc: 'var(--acc-green)' },
    }
    const GAP_META = {
      no_decision: { label: '缺决策', color: 'var(--c-red)' },
      no_cost: { label: '缺成本', color: 'var(--c-amber)' },
      status_lag: { label: '状态滞后', color: 'var(--c-amber)' },
      stale: { label: '超期未闭合', color: 'var(--c-red)' },
    }

    // ============ 样式表（class 体系） ============
    // 内联 style 无法表达 hover/focus/transition/keyframes，所以视觉层集中在这里。
    // 变量：--b/--b2/--bd 为表面与边框；状态色直接用主题 state token。
    const CSS = `
.ev-root{
  --b:var(--dsw-alias-bg-layer-1);--b2:var(--dsw-alias-bg-layer-2);
  --bd:var(--dsw-alias-border-l1);--bd2:var(--dsw-alias-border-l2);
  --tx:var(--dsw-alias-label-primary);--tx2:var(--dsw-alias-label-secondary);
  --br:var(--dsw-alias-brand-primary);
  --ok:var(--dsw-alias-state-success-primary);
  --wn:var(--dsw-alias-state-warn-primary);
  --er:var(--dsw-alias-state-error-primary);
  --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
  /* 亮色主题下 bg-layer-1 与 -2 是同一个白（design-platform.css），纯靠底色分层会
     完全失效；用一层极淡的叠加色当"表面"变量，暗色主题下置空。 */
  --surf:rgba(15,17,21,.028);
  /* 亮色下 border-l1 只有 4% 黑，发丝线几乎不可见——补一档可见的分隔线。 */
  --hair:color-mix(in srgb,var(--tx) 9%,transparent);
  /* 面板统一色语（与 ascend-panel 同一套角色，见 scripts/check_panel_tokens.py）：
       --c-*    文字色（需过 WCAG AA，所以用深一档的同色相）
       --acc-*  装饰色（点/条/边框/渐变——大块面，用面板共用的亮色）
     亮色下 bg-layer-1 与 -2 是同一个白，靠 --surf 叠加层分层；--hair 补可见发丝线。 */
  --c-blue:#1d4ed8; --c-green:#15803d; --c-purple:#7c3aed;
  --c-amber:#92400e; --c-red:#b91c1c; --c-gray:#64748b;
  --acc-blue:#3b82f6; --acc-green:#22c55e; --acc-purple:#8b5cf6;
  --acc-amber:#f59e0b; --acc-red:#ef4444; --acc-gray:#9ca3af;
  /* 实心徽标底：深到白字过 AA（原色 #3b82f6 配白字只有 3.68:1） */
  --fill-blue:#1d4ed8; --fill-green:#15803d; --fill-purple:#6d28d9;
  --fill-amber:#b45309; --fill-red:#b91c1c; --fill-gray:#475569;
  --link:var(--c-blue);
  --tint:9%;
  /* ── 字号尺度（与「指标」面板同一套 8 档；2026-09 补）───────────────────
     为什么要补：本面板原先**没有尺度**，17 个散落的 font-size（8.5–17px）各自为政，
     最小的 8.5px 给了趋势的期间标签——中文在这个尺寸下笔画会糊成一团，是本面板
     "字小、看不懂"的直接原因。同一套档位也让两个面板读起来像同一个产品
     （色语已经在 check_panel_tokens 里统一，排版的道理相同）。
     基准 14.5：面板信息密度高，而中文在 11–12px 下会糊（指标面板实测过）。
     用法：内联值只允许取这 8 档（回归闸门会拦新档位）。 */
  --t-md2:10.5px;     /* 徽章、角标 */
  --t-tiny:11.5px;    /* chip、时间戳、计数 */
  --t-sm:12.5px;      /* 密集行、注释、摘要 */
  --t-md:13.5px;      /* 行主体（密集正文） */
  --t-base:14.5px;    /* 正文、判据行、卡正文 */
  --t-lg:15px;        /* 区块标题、卡片主标题 */
  --t-xl:16.5px;      /* 主数值 */
  --t-2xl:18px;       /* 视图标题 */
  /* ── 行高：中文需要更松（1.5 会挤）────────────────────────────── */
  --lh-tight:1.35;
  --lh-base:1.6;
  --lh-prose:1.75;
  padding:10px 12px 18px;display:flex;flex-direction:column;gap:10px;
  color:var(--tx);font-size:var(--t-base);line-height:var(--lh-base);
  -webkit-font-smoothing:antialiased;
}
/* 主题判定跟随 DSH 的机制（body[data-ds-dark-theme]），不用 prefers-color-scheme：
   系统主题与 DSH 主题可以不一致，用系统偏好判断会在"暗系统 + 亮 DSH"时错配。 */
body[data-ds-dark-theme] .ev-root{--surf:transparent;--hair:var(--bd);
  /* 暗色：文字色反相为亮而饱和的色值；装饰色提亮一档保持同一色相 */
  --c-blue:#7db3fc; --c-green:#5cd68f; --c-purple:#b39bfb;
  --c-amber:#fbbf24; --c-red:#fb8a8a; --c-gray:#a8b0bd;
  --acc-blue:#60a5fa; --acc-green:#4ade80; --acc-purple:#a78bfa;
  --acc-amber:#fbbf24; --acc-red:#f87171; --acc-gray:#9ca3af;
  --fill-blue:#7db3fc; --fill-green:#5cd68f; --fill-purple:#b39bfb;
  --fill-amber:#fbbf24; --fill-red:#fb8a8a; --fill-gray:#a8b0bd;
  --link:var(--c-blue)}
/* 暗色下实心徽标用"浅底深字"：白字配浅色底只有 2:1，深字才过 AA */
body[data-ds-dark-theme] .ev-pill.solid{background:var(--pc);border-color:var(--pc);color:#111318}
body[data-ds-dark-theme] .ev-btn.on{background:var(--br);border-color:var(--br);color:#111318}
.ev-root *,.ev-root *::before,.ev-root *::after{box-sizing:border-box}
.ev-root ::selection{background:color-mix(in srgb,var(--br) 24%,transparent)}

/* —— 段落浮现（首屏分段进场）—— */
.ev-rise{animation:ev-rise .34s cubic-bezier(.22,1,.36,1) both}
.ev-rise:nth-child(1){animation-delay:0ms}
.ev-rise:nth-child(2){animation-delay:45ms}
.ev-rise:nth-child(3){animation-delay:90ms}
.ev-rise:nth-child(4){animation-delay:135ms}
.ev-rise:nth-child(5){animation-delay:180ms}
.ev-rise:nth-child(6){animation-delay:225ms}
@keyframes ev-rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* —— 顶栏 —— */
.ev-top{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;padding-bottom:2px}
.ev-mark{width:8px;height:16px;border-radius:4px;flex-shrink:0;
  background:linear-gradient(180deg,var(--acc-blue),var(--acc-purple))}
.ev-title{font-size:var(--t-base);font-weight:700;letter-spacing:-.01em}
.ev-meta{font-size:var(--t-tiny);color:var(--tx2);font-variant-numeric:tabular-nums}
.ev-meta b{color:var(--tx);font-weight:650}

/* —— 区块 —— */
.ev-sec{background-color:var(--b);background-image:linear-gradient(var(--surf),var(--surf));
  border:1px solid var(--hair);border-radius:12px;
  padding:11px 13px;box-shadow:0 1px 2px rgba(0,0,0,.035)}
.ev-sec-hd{display:flex;align-items:center;gap:8px;margin-bottom:9px}
.ev-sec-hd.has-body{margin-bottom:9px}
.ev-sec-t{font-size:var(--t-md);font-weight:680;letter-spacing:.005em}
.ev-sec-r{margin-left:auto;font-size:var(--t-tiny);color:var(--tx2);font-variant-numeric:tabular-nums}
.ev-label{font-size:var(--t-md2);font-weight:700;letter-spacing:.09em;text-transform:uppercase;
  color:var(--tx2);margin-bottom:5px}

/* —— 按钮 —— */
.ev-btn{font:inherit;font-size:var(--t-sm);font-weight:600;cursor:pointer;
  border:1px solid var(--hair);background:transparent;color:var(--tx2);
  border-radius:7px;padding:3px 11px;letter-spacing:.01em;
  transition:color .14s ease,border-color .14s ease,background-color .14s ease,transform .14s ease}
.ev-btn:hover{color:var(--tx);border-color:var(--bd2);
  background:color-mix(in srgb,var(--tx) 5%,transparent)}
.ev-btn:active{transform:translateY(.5px)}
.ev-btn:focus-visible{outline:2px solid var(--br);outline-offset:2px}
.ev-btn.on{background:color-mix(in srgb,var(--br) 72%,#000);
  border-color:color-mix(in srgb,var(--br) 72%,#000);color:#fff}
.ev-btn.on:hover{background:color-mix(in srgb,var(--br) 60%,#000);
  border-color:color-mix(in srgb,var(--br) 60%,#000);color:#fff}
.ev-btn.on:focus-visible{outline-color:color-mix(in srgb,var(--br) 55%,transparent)}
.ev-btn .n{font-variant-numeric:tabular-nums;opacity:.75;margin-left:4px;font-weight:500}
.ev-btn.wide{width:100%;text-align:left;display:flex;align-items:center;gap:7px;padding:6px 11px}
.ev-btn.wide .ev-sec-r{margin-left:auto}

/* —— 待办条 —— */
.ev-stats{display:flex;gap:16px;flex-wrap:wrap;margin-top:9px;font-size:var(--t-tiny);color:var(--tx2)}
.ev-stats b{color:var(--tx);font-weight:680;font-variant-numeric:tabular-nums}

/* —— 状态点 —— */
.ev-dot{width:7px;height:7px;border-radius:999px;background:var(--dc);flex-shrink:0;display:inline-block}
.ev-dot.pulse{animation:ev-pulse 2.2s ease-in-out infinite}
@keyframes ev-pulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--dc) 45%,transparent)}
  50%{box-shadow:0 0 0 3.5px color-mix(in srgb,var(--dc) 0%,transparent)}}

/* —— 徽标 —— */
.ev-pill{font-size:var(--t-tiny);line-height:var(--lh-prose);padding:0 7px;border-radius:999px;white-space:nowrap;
  flex-shrink:0;letter-spacing:.01em;font-weight:550;
  color:var(--pc);background:color-mix(in srgb,var(--pc) var(--tint),transparent);
  border:1px solid color-mix(in srgb,var(--pc) 26%,transparent)}
.ev-pill.solid{color:#fff;background:var(--pc);border-color:var(--pc)}

/* —— 筛选行 —— */
.ev-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}

/* —— 卡 —— */
.ev-card{background-color:var(--b2);background-image:linear-gradient(var(--surf),var(--surf));border:1px solid var(--hair);border-radius:10px;
  margin-bottom:6px;overflow:hidden;
  transition:border-color .16s ease,box-shadow .16s ease}
.ev-card:hover{border-color:var(--bd2);box-shadow:0 2px 10px rgba(0,0,0,.05)}
.ev-card.gap{border-color:color-mix(in srgb,var(--wn) 38%,transparent)}
.ev-card.gap:hover{border-color:color-mix(in srgb,var(--wn) 60%,transparent)}
.ev-card.open{border-color:color-mix(in srgb,var(--sc) 40%,transparent)}
.ev-head{display:block;width:100%;text-align:left;font:inherit;color:inherit;background:none;
  border:0;padding:9px 11px;cursor:pointer;
  transition:background-color .14s ease}
.ev-head:hover{background:color-mix(in srgb,var(--tx) 3.5%,transparent)}
.ev-head:focus-visible{outline:2px solid var(--br);outline-offset:-2px}
.ev-hrow{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.ev-id{font-family:var(--mono);font-size:var(--t-sm);font-weight:700;color:var(--link);letter-spacing:-.01em}
.ev-age{margin-left:auto;font-size:var(--t-tiny);color:var(--tx2);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.ev-ctitle{margin-top:5px;font-size:var(--t-md);font-weight:600;line-height:var(--lh-base);color:var(--tx)}
.ev-csum{margin-top:4px;font-size:var(--t-sm);color:var(--tx2);line-height:var(--lh-base);
  overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.ev-csum .t{font-weight:700}
.ev-csum .c{font-family:var(--mono);margin-left:6px;opacity:.85}
.ev-chev{width:0;height:0;border-left:5px solid var(--cc,var(--tx2));
  border-top:4.5px solid transparent;border-bottom:4.5px solid transparent;
  transform:rotate(0deg);transition:transform .2s cubic-bezier(.22,1,.36,1);flex-shrink:0}
.ev-chev.open{transform:rotate(90deg)}

/* 展开体：grid-rows 过渡（不动画 height，避免 layout 抖动） */
.ev-bodywrap{display:grid;grid-template-rows:0fr;
  transition:grid-template-rows .2s cubic-bezier(.22,1,.36,1)}
.ev-bodywrap.open{grid-template-rows:1fr}
.ev-body{overflow:hidden}
.ev-bodyin{border-top:1px solid var(--bd);padding:11px 12px 13px;
  display:flex;flex-direction:column;gap:12px;
  opacity:0;transform:translateY(-3px);
  transition:opacity .22s ease,transform .26s cubic-bezier(.22,1,.36,1)}
.ev-bodywrap.open .ev-bodyin{opacity:1;transform:none;transition-delay:.06s}

.ev-txt{font-size:var(--t-md);line-height:var(--lh-prose);color:var(--tx);white-space:pre-wrap;word-break:break-word}
.ev-effect{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;font-size:var(--t-md)}
.ev-effect .m{font-weight:680}
.ev-effect .from{color:var(--tx2);font-family:var(--mono);font-size:var(--t-sm)}
.ev-effect .arrow{color:var(--tx2);margin:0 1px}
.ev-effect .to{color:var(--ok);font-weight:700;font-family:var(--mono);font-size:var(--t-sm)}
.ev-kv{font-size:var(--t-sm);line-height:var(--lh-base);color:var(--tx)}
.ev-kv .k{color:var(--tx2)}
.ev-box{background-color:var(--b);background-image:linear-gradient(var(--surf),var(--surf));border:1px solid var(--hair);border-radius:9px;
  padding:9px 11px;display:flex;flex-direction:column;gap:6px}

/* 信号 */
.ev-sig{margin-bottom:8px}
.ev-sig:last-child{margin-bottom:0}
.ev-sigrow{display:flex;align-items:flex-start;gap:7px}
.ev-sigev{font-size:var(--t-sm);line-height:var(--lh-base);color:var(--tx);flex:1;min-width:0}
.ev-traj{margin-top:4px;padding-left:9px;border-left:1px solid var(--hair)}
.ev-traj div{font-size:var(--t-tiny);color:var(--tx2);font-family:var(--mono);line-height:var(--lh-prose);word-break:break-all}

/* 决策链：发丝轨 + 阶段点 */
.ev-chain{display:flex;flex-direction:column}
.ev-dec{display:flex;gap:10px;padding-bottom:11px}
.ev-dec:last-child{padding-bottom:0}
.ev-rail{display:flex;flex-direction:column;align-items:center;width:9px;flex-shrink:0}
.ev-rail i{width:6px;height:6px;border-radius:999px;background:var(--dc);margin-top:5px;
  flex-shrink:0;box-shadow:0 0 0 2.5px color-mix(in srgb,var(--dc) 14%,transparent)}
.ev-rail s{flex:1;width:1px;background:var(--hair);margin-top:4px}
.ev-decbody{flex:1;min-width:0}
.ev-dechd{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.ev-decwho{font-size:var(--t-sm);color:var(--tx2)}
.ev-decwhen{font-size:var(--t-tiny);color:var(--tx2);font-family:var(--mono);font-variant-numeric:tabular-nums}
.ev-decct{margin-top:4px;font-size:var(--t-md);line-height:var(--lh-prose);color:var(--tx);
  white-space:pre-wrap;word-break:break-word}

.ev-skel{display:flex;flex-direction:column;gap:9px;padding:2px 0}
.ev-skel-line{height:10px;border-radius:4px;
  background:linear-gradient(90deg,color-mix(in srgb,var(--hair) 60%,transparent) 25%,
    color-mix(in srgb,var(--hair) 120%,transparent) 37%,
    color-mix(in srgb,var(--hair) 60%,transparent) 63%);
  background-size:400% 100%;animation:ev-shimmer 1.1s ease-in-out infinite}
@keyframes ev-shimmer{0%{background-position:100% 0}100%{background-position:0 0}}

/* —— 进度量 —— */
.ev-grid2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
@media (max-width:520px){.ev-grid2{grid-template-columns:minmax(0,1fr)}}
.ev-bar{height:3px;border-radius:2px;margin-top:4px;overflow:hidden;
  background:color-mix(in srgb,var(--bd) 55%,transparent)}
.ev-bar i{display:block;height:100%;border-radius:2px;background:var(--dc);
  transition:width .4s cubic-bezier(.22,1,.36,1)}
.ev-krow{display:flex;justify-content:space-between;gap:8px;font-size:var(--t-sm);padding:2.5px 0}
.ev-krow .k{color:var(--tx2);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev-krow .v{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--tx);flex-shrink:0}
.ev-note{font-size:var(--t-tiny);color:var(--tx2);margin-top:7px;line-height:var(--lh-base)}

/* —— 趋势（旧 sparkline 的 .ev-bar* 已随 2026-09 重写删除；现用 .ev-trend/.ev-tbar）—— */
.ev-empty{font-size:var(--t-sm);color:var(--tx2);padding:6px 0;line-height:var(--lh-base)}
.ev-err{font-size:var(--t-sm);color:var(--er);line-height:var(--lh-base)}

/* ---- 判决面（2026-09 新增）：首屏只放要动作的 ---- */
.ev-verdict{display:flex;align-items:center;gap:9px;flex-wrap:wrap;
  padding:9px 12px;border-radius:9px;background-image:var(--surf);
  border:1px solid var(--hair)}
.ev-verdict-t{font-size:var(--t-md);font-weight:650;color:var(--tx)}
.ev-verdict-s{font-size:var(--t-tiny);color:var(--tx2);font-variant-numeric:tabular-nums}
.ev-num{font-size:var(--t-tiny);color:var(--tx2);font-variant-numeric:tabular-nums}

/* ---- 指标趋势（2026-09 重写：一行一期，含量与分母与变化量）---- */
.ev-trend{margin-top:2px}
.ev-thead,.ev-trow{display:grid;gap:8px;align-items:center}
.ev-thead{padding-bottom:4px;border-bottom:1px solid var(--hair)}
.ev-thead > span{font-size:var(--t-tiny);color:var(--tx2);font-weight:600}
.ev-trow{padding:5px 0;border-bottom:1px dashed var(--bd)}
.ev-trow:last-child{border-bottom:0}
.ev-tper{font-size:var(--t-sm);color:var(--tx2);font-family:var(--mono);white-space:nowrap}
.ev-tc{display:flex;align-items:center;gap:7px;min-width:0}
.ev-tbar{flex:1;min-width:16px;height:8px;border-radius:4px;background:var(--bd);overflow:hidden}
.ev-tbar i{display:block;height:100%;border-radius:4px}
.ev-tnum{font-size:var(--t-sm);color:var(--tx);font-family:var(--mono);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.ev-tdl{font-size:var(--t-tiny);color:var(--tx2);font-family:var(--mono);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.ev-tdl.up{color:var(--c-green)}
.ev-tdl.down{color:var(--c-red)}
.ev-find{display:flex;gap:9px;align-items:flex-start;padding:8px 0;
  border-bottom:1px dashed var(--bd)}
.ev-find:last-child{border-bottom:0}
.ev-find-hd{display:flex;gap:7px;align-items:baseline;flex-wrap:wrap}
.ev-find-t{font-size:var(--t-sm);font-weight:640;color:var(--tx)}
.ev-find-r{font-size:var(--t-tiny);color:var(--tx2);font-family:var(--mono);
  font-variant-numeric:tabular-nums}
.ev-find-act{font-size:var(--t-tiny);color:var(--tx2);line-height:var(--lh-prose);margin-top:3px}
.ev-find-act b{color:var(--tx);font-weight:600}
.ev-surf{margin-top:2px}
.ev-surf-row{display:grid;grid-template-columns:64px 1fr auto;gap:8px;
  align-items:center;padding:3px 0}
.ev-surf-k{font-size:var(--t-sm);color:var(--tx)}
.ev-surf-track{height:9px;border-radius:5px;background:var(--bd);overflow:hidden;
  display:flex}
.ev-surf-track i{display:block;height:100%;opacity:.42}
.ev-surf-track i.now{opacity:1}
.ev-surf-v{font-size:var(--t-tiny);color:var(--tx2);font-family:var(--mono);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.ev-caveat{font-size:var(--t-tiny);color:var(--tx2);line-height:var(--lh-prose);margin-top:7px;
  padding-left:9px;border-left:2px solid var(--hair)}
.ev-caveat b{color:var(--tx);font-weight:600}
.ev-drawer-hd{display:flex;align-items:center;gap:8px;width:100%;
  background:none;border:0;padding:7px 8px;border-radius:8px;cursor:pointer;
  color:var(--tx);font:inherit;text-align:left}
.ev-drawer-hd:hover{background-image:var(--surf)}
.ev-drawer-hd:focus-visible{outline:2px solid var(--acc-blue);outline-offset:1px}
.ev-drawer-bd{margin-top:6px}

/* ---- 判决面颜色角色（只用既有 12 角色，不新增——check_panel_tokens 要求两面板角色集一致） ---- */
.ev-verdict.ok{border-color:color-mix(in srgb,var(--acc-green) 34%,transparent)}
.ev-verdict.warn{border-color:color-mix(in srgb,var(--acc-amber) 38%,transparent)}
.ev-verdict.bad{border-color:color-mix(in srgb,var(--acc-red) 38%,transparent)}
.ev-verdict.broken{border-color:color-mix(in srgb,var(--acc-purple) 40%,transparent)}

@media (prefers-reduced-motion:reduce){
  .ev-rise,.ev-dot.pulse{animation:none!important}
  .ev-root *{transition-duration:.01ms!important}
}
`
    const cssDisposer = styles.insert(CSS)

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
    function fmtTokens(n) {
      if (n === null || n === undefined) return '—'
      if (n >= 1000) return (Math.round(n / 100) / 10) + 'k'
      return String(n)
    }
    function copyText(text) {
      if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(() => true).catch(() => false)
      }
      return Promise.resolve(false)
    }

    // ============ 基础件 ============
    function Dot({ color, pulse, size }) {
      return React.createElement('span', {
        className: 'ev-dot' + (pulse ? ' pulse' : ''),
        style: { '--dc': color, width: size, height: size },
      })
    }
    function Pill({ color, fill, children, title, solid }) {
      // solid：底色用 fill（深到白字过 AA），边框/文字色语义不变
      return React.createElement('span', {
        className: 'ev-pill' + (solid ? ' solid' : ''),
        title: title || undefined,
        style: { '--pc': solid ? (fill || color) : color },
      }, children)
    }
    function Chevron({ open, color }) {
      return React.createElement('span', {
        className: 'ev-chev' + (open ? ' open' : ''),
        style: { '--cc': color },
      })
    }
    function SectionLabel({ children, color }) {
      return React.createElement('div', {
        className: 'ev-label',
        style: color ? { color } : undefined,
      }, children)
    }
    function EmptyBox({ text }) {
      return React.createElement('div', { className: 'ev-empty' }, text)
    }
    function Section({ title, right, children, className }) {
      return React.createElement('div', { className: 'ev-sec' + (className ? ' ' + className : '') },
        React.createElement('div', { className: 'ev-sec-hd' },
          React.createElement('span', { className: 'ev-sec-t' }, title),
          right ? React.createElement('span', { className: 'ev-sec-r' }, right) : null,
        ),
        children,
      )
    }

    // ============ ② 可展开决策流 ============
    function DecisionChain({ decisions }) {
      if (!decisions || !decisions.length) return React.createElement(EmptyBox, { text: '无决策记录' })
      return React.createElement('div', { className: 'ev-chain' },
        decisions.map((d, i) => {
          const tm = DEC_TYPE[d.type] || { label: d.type || '—', color: 'var(--tx2)' }
          return React.createElement('div', { key: i, className: 'ev-dec' },
            React.createElement('div', { className: 'ev-rail' },
              React.createElement('i', { style: { '--dc': tm.acc || tm.color } }),
              i < decisions.length - 1 ? React.createElement('s', null) : null,
            ),
            React.createElement('div', { className: 'ev-decbody' },
              React.createElement('div', { className: 'ev-dechd' },
                React.createElement(Pill, { color: tm.color }, tm.label),
                React.createElement('span', { className: 'ev-decwho' }, d.who || '—'),
                d.when ? React.createElement('span', { className: 'ev-decwhen' }, String(d.when)) : null,
              ),
              React.createElement('div', { className: 'ev-decct' }, d.conclusion || ''),
            ),
          )
        }),
      )
    }

    // memo：展开/收起只影响一张卡，但父级 setState 会让 36 张卡全部重渲染
    // （实测展开时 319 个 DOM 节点全部重算，是卡顿主因之一）。
    // React.memo 不在 Builtin 声明里（只保证 createElement/useState/useEffect），
    // 所以留兜底：拿不到就退化成普通组件，功能不受影响。
    const memoize = typeof React.memo === 'function' ? React.memo : (fn => fn)
    const IdeaCard = memoize(function IdeaCard({ idea, sessionId }) {
      const [open, setOpen] = React.useState(false)
      const [detail, setDetail] = React.useState(null)
      const [loading, setLoading] = React.useState(false)
      const meta = STATUS_META[idea.status] || { label: idea.status || '未知', color: 'var(--tx2)', hint: '' }
      const auth = AUTH_META[idea.authorization] || { label: idea.authorization || '—', color: 'var(--tx2)' }
      const gaps = idea.gaps || []
      const cost = idea.actual_cost && idea.actual_cost.tokens !== undefined && idea.actual_cost.tokens !== null
        ? idea.actual_cost.tokens : null
      const costSource = idea.actual_cost && idea.actual_cost.source
      const lastDec = idea.decisions && idea.decisions.length ? idea.decisions[idea.decisions.length - 1] : null

      // 决策链全文按需拉取：列表页只带 60 字摘要。
      // 悬停就预取——点开时数据已就绪，避免"展开 → 等 RPC → 内容插入"的二次跳动
      // （实测首开有一次 49.9ms 帧尖峰，就来自首帧插入整块内容）。
      function fetchDetail() {
        if (detail !== null || loading) return
        setLoading(true)
        host.call('ev-idea-detail', { sessionId: sessionId || null, ideaId: idea.id })
          .then(r => { setLoading(false); setDetail(r && r.ok ? r.idea : { __error__: (r && r.error) || '读取失败' }) })
          .catch(e => { setLoading(false); setDetail({ __error__: 'RPC 失败: ' + String(e && e.message || e) }) })
      }

      function toggle() {
        if (open) { setOpen(false); return }
        setOpen(true)
        fetchDetail()
      }

      // 收起态：一行看懂"哪张卡、什么状态、在做什么"
      const head = React.createElement('button', {
        type: 'button', className: 'ev-head', onClick: toggle,
        onPointerEnter: fetchDetail, onFocus: fetchDetail,
        'aria-expanded': open ? 'true' : 'false',
      },
        React.createElement('div', { className: 'ev-hrow' },
          React.createElement(Chevron, { open: open, color: meta.color }),
          React.createElement('span', { className: 'ev-id' }, idea.id),
          React.createElement(Pill, { color: meta.color, fill: meta.fill, solid: true, title: meta.hint }, meta.label),
          React.createElement(Pill, { color: 'var(--tx2)' }, LAYER_LABELS[idea.layer] || idea.layer || '—'),
          React.createElement(Pill, { color: auth.color, title: auth.hint }, auth.label),
          idea.risk === 'high' ? React.createElement(Pill, { color: 'var(--c-red)' }, 'HIGH') : null,
          gaps.map(g => React.createElement(Pill, { key: g.kind, color: (GAP_META[g.kind] || {}).color || 'var(--wn)', title: g.text }, (GAP_META[g.kind] || {}).label || g.kind)),
          idea.pr_refs && idea.pr_refs.length ? React.createElement(Pill, { color: 'var(--c-purple)', title: '决策链里提到的 PR/issue 号' }, 'PR #' + idea.pr_refs.join(' #')) : null,
          React.createElement('span', { className: 'ev-age' },
            idea.days_open !== null && idea.days_open !== undefined ? idea.days_open + ' 天前' : (relTime(idea.created_at) || '')),
        ),
        React.createElement('div', { className: 'ev-ctitle' }, idea.title),
        // 收起态也给一行"结论摘要"：不展开也知道这张卡最后判了什么
        lastDec ? React.createElement('div', { className: 'ev-csum' },
          React.createElement('span', { className: 't', style: { color: 'var(--c-' + ((lastDec.type === 'proposal') ? 'purple' : lastDec.type === 'action' ? 'blue' : lastDec.type === 'eval' ? 'amber' : 'green') + ')' } },
            (DEC_TYPE[lastDec.type] || {}).label || '—'),
          ' · ',
          lastDec.summary,
          lastDec.length > 60 ? '…' : '',
          React.createElement('span', { className: 'c' }, '共 ' + idea.decisions.length + ' 条'),
        ) : null,
      )

      const d = detail && !detail.__error__ ? detail : null
      const body = React.createElement('div', { className: 'ev-body' },
        React.createElement('div', { className: 'ev-bodyin' },
          // 占位块：让 grid 展开有个稳定目标高度，detail 到达时不再二次跳高
          loading ? React.createElement('div', { className: 'ev-skel' },
            React.createElement('div', { className: 'ev-skel-line', style: { width: '42%' } }),
            React.createElement('div', { className: 'ev-skel-line', style: { width: '88%' } }),
            React.createElement('div', { className: 'ev-skel-line', style: { width: '74%' } }),
          ) : null,
          detail && detail.__error__ ? React.createElement('div', { className: 'ev-err' }, '读取失败：' + detail.__error__) : null,
          // —— 假设与预期：回答"想改什么、预期什么效果"
          (d && d.hypothesis) ? React.createElement('div', null,
            React.createElement(SectionLabel, { color: 'var(--c-purple)' }, '假设'),
            React.createElement('div', { className: 'ev-txt' }, d.hypothesis),
          ) : null,
          (d && d.predicted_effect) ? React.createElement('div', null,
            React.createElement(SectionLabel, { color: 'var(--c-blue)' }, '预期效果'),
            React.createElement('div', { className: 'ev-effect' },
              React.createElement('span', { className: 'm' }, d.predicted_effect.metric || ''),
              React.createElement('span', { className: 'from' }, String(d.predicted_effect.from === undefined ? '—' : d.predicted_effect.from)),
              React.createElement('span', { className: 'arrow' }, '→'),
              React.createElement('span', { className: 'to' }, String(d.predicted_effect.to === undefined ? '—' : d.predicted_effect.to)),
            ),
          ) : null,
          // —— 验证与门控：回答"凭什么说它成了"
          (d && (d.validation || d.gate)) ? React.createElement('div', { className: 'ev-box' },
            React.createElement('div', { className: 'ev-hrow' },
              React.createElement(SectionLabel, null, '验证'),
              d.validation && d.validation.method ? React.createElement(Pill, { color: 'var(--c-amber)' }, METHOD_LABELS[d.validation.method] || d.validation.method) : null,
              cost !== null ? React.createElement(Pill, { color: 'var(--tx2)', title: 'actual_cost' }, '成本 ' + fmtTokens(cost) + ' tok' + (costSource ? ' · ' + costSource : '')) : null,
            ),
            d.validation && d.validation.success_criteria ? React.createElement('div', { className: 'ev-kv' },
              React.createElement('span', { className: 'k' }, '成功判据：'), d.validation.success_criteria) : null,
            d.validation && d.validation.baseline ? React.createElement('div', { className: 'ev-kv' },
              React.createElement('span', { className: 'k' }, '基线：'), d.validation.baseline) : null,
            d.gate ? React.createElement('div', { className: 'ev-kv' },
              React.createElement('span', { className: 'k' }, '门控：'), typeof d.gate === 'string' ? d.gate : (d.gate.condition || JSON.stringify(d.gate))) : null,
            d.validation && d.validation.rollback ? React.createElement('div', { className: 'ev-kv' },
              React.createElement('span', { className: 'k' }, '回滚：'), d.validation.rollback) : null,
          ) : null,
          // —— 触发信号：回答"为什么会有这张卡"
          (d && d.source_signals && d.source_signals.length) ? React.createElement('div', null,
            React.createElement(SectionLabel, { color: 'var(--br)' }, '触发信号'),
            d.source_signals.map((s, i) => React.createElement('div', { key: i, className: 'ev-sig' },
              React.createElement('div', { className: 'ev-sigrow' },
                React.createElement(Pill, { color: 'var(--br)' }, s.signal || 'signal'),
                React.createElement('span', { className: 'ev-sigev' }, s.evidence || ''),
              ),
              (s.trajectory || []).length ? React.createElement('div', { className: 'ev-traj' },
                s.trajectory.map((t, j) => React.createElement('div', { key: j }, t))) : null,
            )),
          ) : null,
          // —— 决策链：核心，回答"到底是什么、改了什么"
          React.createElement('div', null,
            React.createElement('div', { className: 'ev-hrow', style: { marginBottom: 7 } },
              React.createElement(SectionLabel, null, '决策链'),
              React.createElement('span', { style: { fontSize:'var(--t-tiny)', color: 'var(--tx2)' } }, '只追加不修改——提案 → 执行 → 验证 → 判断'),
            ),
            d ? React.createElement(DecisionChain, { decisions: d.decisions })
              : (idea.decisions || []).map((x, i) => React.createElement('div', { key: i, className: 'ev-kv' }, x.summary + (x.length > 60 ? '…' : ''))),
          ),
          // —— 元信息
          (d && (d.principle_refs || []).length) ? React.createElement('div', { style: { fontSize:'var(--t-tiny)', color: 'var(--tx2)' } },
            '设计原则：', d.principle_refs.map(n => '原则' + n).join(' · '),
            d.file ? React.createElement('span', { style: { marginLeft: 8, fontFamily: mono } }, d.file) : null,
          ) : null,
        ),
      )

      return React.createElement('div', {
        className: 'ev-card' + (gaps.length ? ' gap' : '') + (open ? ' open' : ''),
        style: { '--sc': meta.color },
      },
        head,
        React.createElement('div', { className: 'ev-bodywrap' + (open ? ' open' : '') }, body),
      )
    })

    function DecisionFeed({ ideas, sessionId, filter, setFilter, archivedOpen, setArchivedOpen }) {
      const live = ideas.filter(c => c.status === 'in_experiment')
      const gaps = ideas.filter(c => (c.gaps || []).length)
      const adopted = ideas.filter(c => c.status === 'validated')
        .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))

      const filters = [
        { id: 'focus', label: '待办优先', n: live.length + gaps.length },
        { id: 'exp', label: '实验中', n: live.length },
        { id: 'gap', label: '审计缺口', n: gaps.length },
        { id: 'adopted', label: '已采纳', n: adopted.length },
        { id: 'all', label: '全部', n: ideas.length },
      ]
      let shown = ideas
      if (filter === 'focus') shown = ideas.filter(c => c.status === 'in_experiment' || (c.gaps || []).length)
      if (filter === 'exp') shown = live
      if (filter === 'gap') shown = gaps
      if (filter === 'adopted') shown = adopted
      shown = shown.slice().sort((a, b) => {
        const rank = c => (c.status === 'in_experiment' ? 0 : (c.gaps || []).length ? 1 : 2)
        const dr = rank(a) - rank(b)
        return dr !== 0 ? dr : String(b.created_at || '').localeCompare(String(a.created_at || ''))
      })
      // 归档折叠：已采纳且无缺口的卡默认收进"归档"，避免只增不减的墙
      const isArchived = c => c.status === 'validated' && !(c.gaps || []).length
      const archived = shown.filter(isArchived)
      const primary = shown.filter(c => !isArchived(c))

      return React.createElement(Section, {
        title: '决策流',
        right: shown.length + ' 张',
      },
        React.createElement('div', { className: 'ev-chips' },
          filters.map(f => React.createElement('button', {
            key: f.id, type: 'button', onClick: () => setFilter(f.id),
            className: 'ev-btn' + (f.id === filter ? ' on' : ''),
          }, f.label, f.n ? React.createElement('span', { className: 'n' }, f.n) : null)),
        ),
        shown.length === 0
          ? React.createElement(EmptyBox, { text: filter === 'focus' ? '无待办卡（没有实验中的卡，也没有审计缺口）' : '该筛选下没有卡片' })
          : React.createElement('div', null,
              primary.map(c => React.createElement(IdeaCard, { key: c.id, idea: c, sessionId: sessionId })),
              archived.length ? React.createElement('div', null,
                React.createElement('button', {
                  type: 'button', onClick: () => setArchivedOpen(!archivedOpen),
                  className: 'ev-btn wide',
                },
                  React.createElement(Chevron, { open: archivedOpen, color: 'var(--tx2)' }),
                  '归档 · 已采纳且无缺口 ' + archived.length + ' 张',
                  React.createElement('span', { className: 'ev-sec-r' }, archivedOpen ? '收起' : '展开'),
                ),
                archivedOpen
                  ? React.createElement('div', { style: { marginTop: 7 } },
                      archived.map(c => React.createElement(IdeaCard, { key: c.id, idea: c, sessionId: sessionId })))
                  : null,
              ) : null,
            ),
      )
    }

    // ============ ③ 自演进度量 ============
    function StatsPanel({ stats }) {
      if (!stats) return null
      const byMethod = stats.by_method || {}
      const bySignal = stats.by_signal || {}
      const signals = Object.keys(bySignal).sort((a, b) => bySignal[b] - bySignal[a]).slice(0, 6)
      const statuses = Object.keys(stats.by_status || {})
      return React.createElement(Section, { title: '自演进度量' },
        React.createElement('div', { className: 'ev-grid2' },
          React.createElement('div', null,
            React.createElement(SectionLabel, { color: 'var(--c-green)' }, '状态分布（v5 词表）'),
            statuses.map(st => {
              const m = STATUS_META[st] || { label: st, color: 'var(--tx2)' }
              const n = stats.by_status[st]
              const ratio = stats.total ? n / stats.total : 0
              return React.createElement('div', { key: st, style: { marginBottom: 7 } },
                React.createElement('div', { className: 'ev-krow' },
                  React.createElement('span', { className: 'k', style: { display: 'flex', alignItems: 'center', gap: 6 } },
                    React.createElement(Dot, { color: m.acc || m.color }), m.label),
                  React.createElement('span', { className: 'v' }, n),
                ),
                React.createElement('div', { className: 'ev-bar' },
                  React.createElement('i', { style: { '--dc': m.acc || m.color, width: (ratio * 100) + '%' } })),
              )
            }),
            React.createElement('div', { className: 'ev-note' },
              '采纳率 ', React.createElement('b', { style: { color: 'var(--tx)' } }, stats.adoption_rate === null ? '—' : Math.round(stats.adoption_rate * 100) + '%'),
              '（只在终态卡上计算，实验中的卡未判决，不计入分母）。',
              React.createElement('b', { style: { color: 'var(--c-amber)' } }, '采纳率 100% 表示没有否决记录'),
              '：终态卡中不采纳 0 张、换方向 0 张，该项见「① 要处理的」。'),
          ),
          React.createElement('div', null,
            React.createElement(SectionLabel, { color: 'var(--c-amber)' }, '验证方式分布'),
            Object.keys(byMethod).sort((a, b) => byMethod[b] - byMethod[a]).map(k => React.createElement('div', { key: k, className: 'ev-krow' },
              React.createElement('span', { className: 'k' }, METHOD_LABELS[k] || k),
              React.createElement('span', { className: 'v' }, byMethod[k]))),
            React.createElement('div', { style: { marginTop: 10 } },
              React.createElement(SectionLabel, { color: 'var(--br)' }, '信号来源（前 6）'),
              signals.map(k => React.createElement('div', { key: k, className: 'ev-krow' },
                React.createElement('span', { className: 'k', style: { fontFamily: mono } }, k),
                React.createElement('span', { className: 'v' }, bySignal[k]))),
            ),
          ),
        ),
      )
    }

    // ============ 指标趋势 ============
    // 2026-09 重写（旧版为什么看不懂，三条实测原因）：
    //   ① **分母丢了**：collect_timeline 把 {ok,total} 压成 ok，于是三期 live 的
    //      「3/3」渲染成三根等高的柱子加一个孤零零的「3」——比例没有分母不可解读
    //      （metrics.md 的口径纪律：比例类务必连同分母解读）。数据面已修，这里消费分母。
    //   ② **没有说话的部分**：只有一组柱，没有刻度、没有变化量、没有说明哪个读数在动。
    //   ③ **期间标签 8.5px**：中文在这个尺寸下认不出（已并入 --t-* 档位，现为 --t-sm）。
    // 现在的形态是一行一期 × 一列一指标，逐格给「含量与分母」与「相对上期的变化量」；
    // 恒定或分母过小时用一行注记明说，不靠柱高差暗示趋势（原则十）。
    const TREND_METRICS = [
      { key: 'routed_accuracy', label: '路由准确率', acc: 'var(--acc-blue)' },
      { key: 'tier2_hit', label: 'Tier2 命中', acc: 'var(--acc-green)' },
      { key: 'sessions_total', label: '会话数', acc: 'var(--acc-purple)', delta: true },
    ]

    function ratioText(v) {
      if (!v || v.ok === null || v.ok === undefined) return '—'
      return (v.total === null || v.total === undefined) ? String(v.ok) : v.ok + '/' + v.total
    }
    function ratioPct(v) {
      if (!v || !v.total) return null
      return Math.max(0, Math.min(1, v.ok / v.total))
    }

    function TimelineTrend({ timeline }) {
      const all = timeline || []
      const live = all.filter(p => p.kind === 'live')
      const rows = (live.length ? live : all).slice(-8)
      if (!rows.length) return React.createElement(Section, { title: '指标趋势' },
        React.createElement(EmptyBox, { text: 'timeline 无数据（跑一次周批生成快照：python3 scripts/metrics_snapshot.py）' }))

      // 一行一期，逐指标给出「读数（含分母）+ 相对上期的变化量」。
      // 恒定与样本不足用注记明说，不靠图上的高度差暗示趋势（原则十）。
      const cols = TREND_METRICS.filter(m => rows.some(r => r[m.key] !== undefined))
      if (!cols.length) return React.createElement(Section, { title: '指标趋势' },
        React.createElement(EmptyBox, { text: '近期快照缺路由准确率、Tier2 命中与会话数三项，无法成表' }))
      const grid = { gridTemplateColumns: 'auto repeat(' + cols.length + ',minmax(0,1fr))' }
      const maxOf = key => Math.max(1, ...rows.map(r => {
        const v = r[key]
        if (v && typeof v === 'object') return v.total || v.ok || 0
        return typeof v === 'number' ? v : 0
      }))
      const textOf = (key, v) => {
        if (v && typeof v === 'object') return ratioText(v)
        return typeof v === 'number' ? String(v) : '—'
      }
      const pctOf = (key, v) => {
        if (v && typeof v === 'object') return ratioPct(v)
        if (typeof v === 'number') return Math.max(0, Math.min(1, v / maxOf(key)))
        return null
      }

      // 注记：把"能不能读出趋势"这件事直接写在图上，而不是留给读者猜
      const notes = []
      cols.filter(c => c.key !== 'sessions_total').forEach(c => {
        const texts = rows.map(r => textOf(c.key, r[c.key]))
        const present = texts.filter(t => t !== '—')
        if (present.length > 1 && present.every(t => t === present[0])) {
          notes.push(c.label + ' 各期恒为 ' + present[0])
        }
      })
      const sess = rows.map(r => r.sessions_total).filter(v => typeof v === 'number')
      if (sess.length > 1) notes.push('会话数 ' + sess.join(' → '))
      const smallDen = rows.some(r => r.routed_accuracy && r.routed_accuracy.total
        && r.routed_accuracy.total < 10)
      if (smallDen) notes.push('路由准确率的分母小于 10，跨期波动不可解读')
      const fcs = rows.map(r => r.feedback_capture_total).filter(v => typeof v === 'number')
      if (fcs.length && fcs.every(v => v === 0)) {
        notes.push('反馈捕获各期均为 0，故命中率/误诊率没有分母（不可解读）')
      }
      const constantOnly = cols.every(c => c.key === 'sessions_total'
        || rows.map(r => textOf(c.key, r[c.key])).every(t => t === textOf(c.key, rows[0][c.key])))

      return React.createElement(Section, {
        title: '指标趋势',
        right: (live.length ? 'live 期 ' + rows.length + ' 期' : 'replay/示例参考（live 期不足）'),
      },
        React.createElement('div', { className: 'ev-trend' },
          React.createElement('div', { className: 'ev-thead', style: grid },
            React.createElement('span', null, '期间'),
            cols.map(c => React.createElement('span', { key: c.key }, c.label)),
          ),
          rows.map((p, i) => {
            const prev = i > 0 ? rows[i - 1] : null
            return React.createElement('div', { key: String(p.period) + i, className: 'ev-trow', style: grid },
              React.createElement('span', {
                className: 'ev-tper',
                title: String(p.period) + ' · ' + (p.title || ''),
              }, String(p.period || '').replace(/^2026-/, '')),
              cols.map(c => {
                const v = p[c.key]
                const pct = pctOf(c.key, v)
                const cur = typeof v === 'number' ? v : null
                const pre = prev && typeof prev[c.key] === 'number' ? prev[c.key] : null
                const delta = (c.delta && cur !== null && pre !== null) ? cur - pre : null
                return React.createElement('div', { key: c.key, className: 'ev-tc' },
                  React.createElement('span', { className: 'ev-tbar' },
                    React.createElement('i', {
                      style: {
                        width: (pct === null ? 0 : Math.max(4, pct * 100)) + '%',
                        background: pct === null ? 'var(--bd)' : c.acc,
                      },
                    })),
                  React.createElement('span', { className: 'ev-tnum' }, textOf(c.key, v)),
                  delta !== null && delta !== 0
                    ? React.createElement('span', {
                        className: 'ev-tdl ' + (delta > 0 ? 'up' : 'down'),
                      }, (delta > 0 ? '+' : '') + delta)
                    : null,
                )
              }),
            )
          }),
        ),
        notes.length
          ? React.createElement('div', { className: 'ev-note', style: { marginTop: 7 } },
              (constantOnly
                ? '注：表中读数各期没有变化，无法据此判断趋势——'
                : '注：') + notes.join('；') + '。')
          : null,
      )
    }

    // ============ 容量（与「指标」tab 有重叠，此处只报压力） ============
    function CapacitySummary({ capacity }) {
      const nss = Object.keys(capacity || {})
      if (!nss.length) return React.createElement(Section, { title: '知识库容量' }, React.createElement(EmptyBox, { text: '容量数据未生成（build_index 头注缺失）' }))
      const rows = []
      nss.forEach(ns => {
        const cells = capacity[ns] || {}
        Object.keys(cells).forEach(cat => {
          const cell = cells[cat]
          // 判据量是**查一次问题要读进来多少字**（token），阈值在 metrics/gates.yaml；
          // 条数只作观察值。这里不重算阈值——面板拿不到 gates.yaml，只按"有没有值"排序，
          // 越线的判定与文案由「指标」tab 的体检判决给出（两处必须说同一件事：都按 token）。
          rows.push({ ns, cat, ...cell, tok: typeof cell.tok === 'number' ? cell.tok : null })
        })
      })
      rows.sort((a, b) => (b.tok || 0) - (a.tok || 0))
      // 「需要看的」= 有读入成本的格子（按成本从高到低）；阈值判定归体检，此处不猜线。
      const near = rows.filter(r => r.tok != null).slice(0, 3)
      return React.createElement(Section, {
        title: '知识库容量',
        right: rows.length + ' 格 · 逐格读入成本与越线判定见「指标」tab',
      },
        near.length
          ? React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
              near.map(r => React.createElement(Pill, {
                key: r.ns + r.cat, color: 'var(--c-amber)',
                title: r.ns + ' · ' + r.cat + '：' + r.count + ' 条，查一次读进来约 ' + r.tok + ' tok',
              }, r.ns.split('/').pop() + ' · ' + r.cat + ' ' + r.count + ' 条 / ' + r.tok + ' tok')))
          : React.createElement(EmptyBox, { text: '读入成本未生成（先跑 python3 scripts/build_index.py 与 index_read_cost.py）' }),
      )
    }

    // ============ 流程演进信号（无数据不占位） ============
    function TallySection({ tally, s2Attrib }) {
      const hasTally = tally && tally.length
      const hasS2 = s2Attrib && s2Attrib.length
      if (!hasTally && !hasS2) {
        return React.createElement(Section, { title: '流程演进信号' },
          React.createElement('div', { className: 'ev-empty' },
            '尚无归因事件（需 S1 反馈归因或 S2 replay 路由未命中累积后产生）。'),
        )
      }
      return React.createElement(Section, { title: '流程演进信号' },
        hasTally ? React.createElement('div', { style: { marginBottom: hasS2 ? 9 : 0 } },
          React.createElement(SectionLabel, null, '归因事件（按需聚合）'),
          tally.map(c => React.createElement('div', { key: c.id, className: 'ev-krow', style: { borderBottom: '1px dashed var(--bd)' } },
            React.createElement('span', { className: 'k', style: { fontFamily: mono, color: 'var(--tx)' } }, c.id),
            React.createElement('span', { className: 'v', style: { color: 'var(--c-red)', fontWeight: 700 } }, 'mis=' + c.misdiagnoses),
            React.createElement('span', { className: 'k', style: { marginLeft: 'auto' } }, (c.traces || c.source_traces || []).length + ' 来源'),
          ))) : null,
        hasS2 ? React.createElement('div', null,
          React.createElement(SectionLabel, null, 'S2 replay 路由归因'),
          s2Attrib.map((a, i) => React.createElement('div', { key: i, className: 'ev-kv', style: { padding: '3px 0' } },
            '#' + a.issue + ' → ' + a.component + '：' + (a.note || '')))) : null,
      )
    }

    // ============ ④ 执行现场（exec-log：evolve-check 到底跑没跑） ============
    // 2026-09-10 审计发现的盲区：exec-log 先前只有 evolve-check 第 1 步读它，面板与 metrics
    // 都不看——于是"收尾跑了但无演进信号"与"根本没跑"在数据上完全不可区分。这一格把现场
    // 端到人眼前（无信号收尾也落记录，所以它同样可见）。
    // 同日的第二个修正：exec-log 原先写在**各 worktree 的检出内**且是 .gitignore 件，而
    // 代理都按仓库纪律在 worktree 里干活 → 代理落的记录这份面板（读用户会话 cwd）根本读不到，
    // 这一格常年空着。现在改为主检出共享件（同一克隆所有 worktree 共写共读）。
    function ExecLogSection({ execLog }) {
      if (!execLog) return null
      const note = execLog.note || '同一克隆共享（主检出 metrics/）'
      if (!execLog.present) {
        return React.createElement(Section, { title: '执行现场（exec-log）', right: '同一克隆共享' },
          React.createElement('div', { className: 'ev-empty' },
            '无执行记录（' + (execLog.state === 'missing' ? '尚无任何收尾记录'
              : execLog.state === 'unavailable' ? execLog.note : '记录文件解析失败') + '）。'
            + '内容流程收尾时应写入一条 exec-log，evolve-check 才能读到本轮现场。'),
          React.createElement('div', { className: 'ev-note', style: { marginTop: 6 } }, note))
      }
      const rows = execLog.recent || []
      const runs = execLog.evolve_check_runs || 0
      const silent = execLog.evolve_check_no_signal || 0
      return React.createElement(Section, {
        title: '执行现场（exec-log）',
        right: '共 ' + (execLog.total || 0) + ' 条',
      },
        React.createElement('div', { className: 'ev-krow' },
          React.createElement('span', { className: 'k', style: { display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: runs ? 'var(--c-green)' : 'var(--c-amber)' }),
            'evolve-check 收尾'),
          React.createElement('span', { className: 'v' }, runs + ' 次' + (silent ? '（其中无信号 ' + silent + '）' : '')),
        ),
        runs ? null : React.createElement('div', { className: 'ev-note', style: { color: 'var(--c-amber)' } },
          'exec-log 中没有 evolve-check 的收尾记录。缺少这条记录时，'
          + '"运行但无演进信号"与"未运行"无法区分。内容流程收尾应写入一条（见 skills/evolve-check）。'),
        React.createElement('div', { style: { marginTop: 8 } },
          React.createElement(SectionLabel, { color: 'var(--br)' }, '最近执行（尾部 ' + rows.length + ' 条）'),
          rows.map(r => React.createElement('div', {
            key: String(r.seq), className: 'ev-kv', style: { padding: '3px 0', borderBottom: '1px dashed var(--bd)' },
          },
            React.createElement('span', { style: { fontFamily: mono, color: 'var(--tx)' } },
              '[' + r.seq + '] ' + r.skill),
            React.createElement('span', { style: { marginLeft: 8, color: 'var(--tx2)' } },
              String(r.at || '').replace('T', ' ').slice(0, 16)),
            r.products && r.products.length
              ? React.createElement('span', { style: { marginLeft: 8 } }, '→ ' + r.products.join('、'))
              : null,
            r.decision_reason
              ? React.createElement('span', { style: { marginLeft: 8, color: 'var(--tx2)' } },
                  '（' + String(r.decision_reason).slice(0, 46) + '）')
              : null,
          )),
        ),
        React.createElement('div', { className: 'ev-note', style: { marginTop: 6 } }, note
          + '。内容流程（issue-ingest / to-reference / to-postmortem / knowledge-groom）与 evolve-check '
          + '各自收尾各写一条，无演进信号时也写。本记录跨克隆与跨机不聚合，'
          + '跨机口径需用 `--summary` 的汇总值写入 metrics/timeline.yaml'),
      )
    }

    // ============ 判决面（2026-09 新增）：首屏只放要动作的 ============
    // 为什么重排：旧首屏是"状态分组 + 卡片平铺"，实测退化成一堵只增不减的墙——56/57 validated、
    // 0 rejected、采纳率 100%，于是任何聚合读数都是常数，人读不出信息、也不再读。而人的注意力
    // 是硬预算（原则九）：一批几十张卡的决策链合计约数万字，远超"批级人审"的带宽。所以正确的
    // 分工是**判决层上屏、卡降为按需展开的 diff 日志**（与「指标」tab 的 VerdictCard 同形）。
    // 判决由 scripts/evolution_health.py 算（判据在 proposals/gates.yaml），面板只渲染不重算。
    const VERDICT_META = {
      clean: { label: '本期无阻塞项', color: 'var(--c-green)', acc: 'var(--acc-green)', cls: 'ok' },
      violations: { label: '有判据被违反', color: 'var(--c-amber)', acc: 'var(--acc-amber)', cls: 'warn' },
      broken: { label: '体检器失效', color: 'var(--c-purple)', acc: 'var(--acc-purple)', cls: 'broken' },
    }

    // 预测实测记录：`ev_measure.py --run` 的执行次数与结果分布。这一层原先没有观测面
    // （`--run` 只往 stdout 打印），于是"卡片写了判据命令、但从未执行"在数据上不可区分。
    // 记录文件在 metrics/ev-measure-log.yaml（同一克隆共享，只追加）。
    const MEASURE_LABEL = { PASS: '符合', FAIL: '被证伪', ERROR: '无法判定' }
    const LEDGER_LABEL = { ok: '正常', missing: '尚无记录文件', unparsable: '记录文件解析失败',
      unavailable: '路径解析不可用' }
    function measureLine(health) {
      const ro = (health && health.readouts) || {}
      const mv = ro.measure_by_verdict || {}
      const runs = ro.measure_runs || 0
      const ledger = LEDGER_LABEL[(ro.measure_ledger || {}).state] || '状态未知'
      if (!runs) {
        const pending = ro.runnable_cards || 0
        return React.createElement('div', { className: 'ev-note', style: { marginTop: 8 } },
          '预测实测记录：0 次执行（' + pending + ' 张卡片写了判据命令）',
          React.createElement('br', null),
          '执行方式：python3 scripts/ev_measure.py <卡号> --run；执行次数与结果会记入 '
          + 'metrics/ev-measure-log.yaml。')
      }
      const parts = ['PASS', 'FAIL', 'ERROR'].filter(k => mv[k]).map(k => MEASURE_LABEL[k] + ' ' + mv[k])
      return React.createElement('div', { className: 'ev-note', style: { marginTop: 8 } },
        '预测实测记录：', React.createElement('b', { style: { color: 'var(--tx)' } }, runs + ' 次执行'),
        '（', parts.join(' · '), '）。记录文件：', ledger,
        React.createElement('br', null),
        '「被证伪」表示卡片写下的判据命令不再成立，需按卡片结论重新评估或回退改动。')
    }

    function HealthPanel({ health }) {
      if (!health) return null
      const cov = health.coverage || {}
      const findings = health.findings || []
      const fails = findings.filter(f => f.level === 'fail')
      const others = findings.filter(f => f.level !== 'fail')
      const vm = VERDICT_META[health.check_verdict] || VERDICT_META.violations
      const unreadable = Object.keys(health.readability || {})
        .filter(k => health.readability[k] && health.readability[k].readable === false)
        .map(k => health.readability[k].label || k)
      const broken = (health.broken || []).concat(health.errors || [])

      const verdict = React.createElement('div', { className: 'ev-verdict ' + vm.cls },
        React.createElement(Dot, { color: vm.acc, pulse: health.check_verdict !== 'clean' }),
        React.createElement('span', { className: 'ev-verdict-t' }, vm.label),
        React.createElement('span', null, fails.length
          ? React.createElement('b', { style: { color: vm.color } }, fails.length + ' 项要处理')
          : '0 项要处理'),
        React.createElement('span', { className: 'ev-verdict-s' },
          '判据 ', (cov.gates_evaluated || 0) + '/' + (cov.gates_total || 0), ' 条已评估'),
        unreadable.length
          ? React.createElement(Pill, { color: 'var(--c-amber)', fill: 'var(--fill-amber)' },
              '读数不可解读：' + unreadable.join('、'))
          : null,
        broken.length
          ? React.createElement(Pill, { color: 'var(--c-purple)', fill: 'var(--fill-purple)' },
              broken.length + ' 条判据未评估，结论不成立')
          : null,
      )

      const row = f => React.createElement('div', { key: f.id || f.title, className: 'ev-find' },
        React.createElement(Dot, { color: f.level === 'fail' ? 'var(--acc-amber)' : 'var(--acc-gray)' }),
        React.createElement('div', { style: { flex: 1, minWidth: 0 } },
          React.createElement('div', { className: 'ev-find-hd' },
            React.createElement('span', { className: 'ev-find-t' }, f.title),
            f.reading ? React.createElement('span', { className: 'ev-find-r' }, f.reading) : null,
          ),
          f.action ? React.createElement('div', { className: 'ev-find-act' },
            React.createElement('b', null, '→ '), f.action) : null,
        ),
      )

      return React.createElement('div', null,
        verdict,
        React.createElement('div', { style: { marginTop: 8 } },
          React.createElement(Section, {
            title: '① 要处理的',
            right: fails.length + ' 项' + (others.length ? '，另 ' + others.length + ' 项供参考' : ''),
          },
            fails.length
              ? fails.map(row)
              : React.createElement('div', { className: 'ev-empty' },
                  '本期无判据越界。读数是否可用见上方结论条：判据未全部评估时结论不成立。'),
            others.length ? others.map(row) : null,
            broken.length ? React.createElement('div', { className: 'ev-note', style: { marginTop: 8, color: 'var(--c-purple)' } },
              '体检器问题：' + broken.join('；')) : null,
            measureLine(health),
          ),
        ),
      )
    }

    // ============ ② 改动落在哪一层（按卡片正文的仓库路径归类） ============
    const SURFACE_META = {
      '判断更准': { acc: 'var(--acc-blue)', hint: '知识内容与检索路由（triage-tree.yaml / knowledge / references）' },
      '闸门更硬': { acc: 'var(--acc-purple)', hint: 'CI 校验与评测资产（eval / verify_* / gates）' },
      '看得见': { acc: 'var(--acc-green)', hint: '脚本、面板与观测记录（scripts / dsh-plugins / traces）' },
      '走得顺': { acc: 'var(--acc-amber)', hint: 'skill 流程与文档（skills / docs）' },
      '未归因': { acc: 'var(--acc-gray)', hint: '卡片正文未出现仓库路径，无法归类' },
    }

    function SurfacePanel({ stats }) {
      if (!stats) return null
      const cum = stats.by_surface || {}
      const rec = stats.by_surface_recent || {}
      const win = stats.surface_window_days || 7
      const order = ['判断更准', '闸门更硬', '看得见', '走得顺', '未归因']
      const keys = order.filter(k => (cum[k] || 0) + (rec[k] || 0) > 0)
        .concat(Object.keys(cum).filter(k => order.indexOf(k) < 0))
      // 没有卡片时整个区块 return null 会让编号从 ① 跳到 ③，读者会以为是渲染故障；
      // 因此改为给出空态说明，与其余区块的处理一致。
      if (!keys.length) {
        return React.createElement(Section, { title: '② 改动落在哪一层' },
          React.createElement('div', { className: 'ev-empty' },
            '暂无卡片，因此没有这一层读数（本表按 proposals/ideas/ 下卡片正文出现的仓库路径统计）。'))
      }
      const max = Math.max(1, ...keys.map(k => cum[k] || 0))
      const basis = stats.by_basis_field || {}
      const BASIS_LABEL = {
        action: '改动说明', title: '卡片标题', hypothesis: '假设',
        success_criteria: '成功判据', trajectory: '证据引用', 'card-text': '全文兜底',
      }
      const top = stats.top_signal
      return React.createElement(Section, {
        title: '② 改动落在哪一层',
        right: '近 ' + win + ' 天 ' + (Object.keys(rec).reduce((a, k) => a + rec[k], 0))
          + ' 张 · 累计 ' + (stats.total || 0) + ' 张',
      },
        React.createElement('div', { className: 'ev-surf' },
          keys.map(k => {
            const acc = (SURFACE_META[k] || {}).acc || 'var(--acc-gray)'
            const c = cum[k] || 0
            const now = rec[k] || 0
            const prev = Math.max(0, c - now)
            return React.createElement('div', { key: k, className: 'ev-surf-row', title: (SURFACE_META[k] || {}).hint || '' },
              React.createElement('span', { className: 'ev-surf-k' },
                React.createElement(Dot, { color: acc }), ' ' + k),
              React.createElement('div', { className: 'ev-surf-track' },
                React.createElement('i', { style: { '--dc': acc, background: acc, width: (prev / max * 100) + '%' } }),
                React.createElement('i', { className: 'now', style: { '--dc': acc, background: acc, width: (now / max * 100) + '%' } }),
              ),
              React.createElement('span', { className: 'ev-surf-v' }, now + ' / ' + c),
            )
          }),
        ),
        React.createElement('div', { className: 'ev-caveat' },
          '说明：本表按卡片正文出现的仓库路径归类，表示改动落在哪一层，不表示改善幅度。',
          React.createElement('br', null),
          '改善幅度属能力轴，当前无数据：现场反馈捕获为 0，命中率与误诊率都没有分母。',
        ),
        Object.keys(basis).length
          ? React.createElement('div', { className: 'ev-note', style: { marginTop: 6 } },
              '归类依据：' + Object.keys(basis).sort((a, b) => basis[b] - basis[a])
                .map(k => (BASIS_LABEL[k] || k) + ' ' + basis[k] + ' 张').join(' · ')
              + '（依据取自「证据引用」或「全文兜底」时，可能不是实际改动位置）')
          : null,
        top
          ? React.createElement('div', { className: 'ev-note' },
              '触发信号：本期最多的是 ', React.createElement('b', { style: { color: 'var(--tx)' } }, top.signal),
              '（', top.cards, ' 张，占 ', Math.round((stats.top_signal_share || 0) * 100), '%，',
              top.first, ' 至 ', top.last, '）')
          : null,
      )
    }

    // ============ 卡区抽屉：默认收起（判决上屏、卡按需） ============
    function CardDrawer({ ideas, sessionId }) {
      const [open, setOpen] = React.useState(false)
      const [filter, setFilter] = React.useState('focus')
      const [archivedOpen, setArchivedOpen] = React.useState(false)
      const gaps = ideas.filter(c => (c.gaps || []).length).length
      const live = ideas.filter(c => c.status === 'in_experiment').length
      return React.createElement('div', null,
        React.createElement('button', {
          type: 'button', className: 'ev-drawer-hd', 'aria-expanded': open,
          onClick: () => setOpen(!open),
        },
          React.createElement(Chevron, { open: open, color: 'var(--tx2)' }),
          React.createElement('span', { className: 'ev-sec-t' }, '④ 卡片档案'),
          React.createElement('span', { className: 'ev-num' },
            ideas.length + ' 张 · 实验中 ' + live + ' · 审计缺口 ' + gaps
            + ' · 已采纳且无缺口 ' + ideas.filter(c => c.status === 'validated' && !(c.gaps || []).length).length),
          React.createElement('span', { className: 'ev-sec-r' }, open ? '收起' : '展开'),
        ),
        open
          ? React.createElement('div', { className: 'ev-drawer-bd' },
              React.createElement(DecisionFeed, {
                ideas: ideas, sessionId: sessionId, filter: filter, setFilter: setFilter,
                archivedOpen: archivedOpen, setArchivedOpen: setArchivedOpen,
              }))
          : null,
      )
    }

    // ============ 主视图 ============
    function BoardView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null, error: null })
      const [health, setHealth] = React.useState(null)

      // 判决与数据分两次拉：判决来自 evolution_health.py（与「指标」tab 拉 metrics_health 同形），
      // 一次失败不影响另一块——判决拿不到时如实缺省，不拿卡数冒充判决。
      // `force`：host 侧结果在 30 秒窗口内复用（切走再切回不重跑脚本），
      // 「刷新」按钮走 force=true 显式绕过窗口；首屏那次不强制。
      const load = React.useCallback((force) => {
        const refresh = force === true
        setState({ loading: true, data: null, error: null })
        setHealth(null)
        host.call('ev-board-load', { sessionId: sessionId, refresh: refresh }).then(r => {
          if (r && r.ok) setState({ loading: false, data: r.data, error: null })
          else setState({ loading: false, data: null, error: (r && r.error) || '读取失败' })
        }).catch(e => setState({ loading: false, data: null, error: String(e && e.message || e) }))
        host.call('ev-health-load', { sessionId: sessionId, refresh: refresh }).then(r => {
          if (r && r.ok) setHealth(r.data)
        }).catch(() => {})
      }, [sessionId])

      React.useEffect(() => { load(false) }, [load])

      if (state.loading) return React.createElement('div', { className: 'ev-root' },
        React.createElement('div', { className: 'ev-empty', style: { textAlign: 'center', padding: 24 } }, '加载自演进数据…'))
      if (state.error) return React.createElement('div', { className: 'ev-root' },
        React.createElement('div', { className: 'ev-err', style: { padding: 14 } }, '数据加载失败：' + state.error))

      const data = state.data || {}
      const ideas = data.ideas || []

      return React.createElement('div', { className: 'ev-root' },
        React.createElement('div', { className: 'ev-top ev-rise' },
          React.createElement('span', { className: 'ev-mark' }),
          React.createElement('span', { className: 'ev-title' }, '自演进 · 体检'),
          React.createElement('span', { className: 'ev-meta' },
            'EV 卡 ', React.createElement('b', null, data.idea_count || 0), ' 张 · 数据 ',
            (data.generated_at || '').replace('T', ' ')),
          React.createElement('button', {
            type: 'button', className: 'ev-btn', onClick: () => load(true), style: { marginLeft: 'auto' },
            title: '重跑 scripts/ev_board_data.py 与 evolution_health.py。数据在 30 秒内复用上次结果'
              + '（切走再切回不重跑），点此绕过窗口立即重跑',
          }, '刷新'),
        ),
        // ① 判决（要处理的）+ 结论条
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(HealthPanel, { health: health })),
        // ② 这批补在哪一层（触及面，确定性派生）
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(SurfacePanel, { stats: data.stats })),
        // ③ 现场：演进到底在不在跑
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(ExecLogSection, { execLog: data.skill_exec })),
        // ④ 卡片：默认收起（判决上屏、卡按需展开为 diff 日志）
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(CardDrawer, { ideas: ideas, sessionId: sessionId })),
        // 明细（按需往下看）
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(StatsPanel, { stats: data.stats })),
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(TimelineTrend, { timeline: data.timeline })),
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(CapacitySummary, { capacity: data.capacity })),
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(TallySection, { tally: data.tally, s2Attrib: data.s2_attrib })),
      )
    }

    ctx.effect(() => () => { if (cssDisposer) cssDisposer() })

    slots.inject('conversation.view', () => slots.register(
      { name: 'conversation.view', id: 'ascend-evolve', order: 22, label: '自演进' },
      (props) => React.createElement(BoardView, props),
    ))
  },
}
// ---- 原文结束 ----
        })()
      },
    },
    ]

    exports.name = 'dsh-sleuth-panels'
    exports.inject = ['slots', 'connection']
    exports.apply = function apply(ctx) {
      const host = makeHost(ctx)
      const styles = makeStyles()
      const disposers = []
      for (const panel of PANELS) {
        try {
          const plugin = panel.build(host, styles)
          const dispose = plugin.apply(ctx)
          if (typeof dispose === 'function') disposers.push(dispose)
        } catch (e) {
          console.error('[dsh-sleuth-panels] ' + panel.id + ' client 半挂载失败: ' + String((e && e.message) || e))
        }
      }
      return () => {
        for (const dispose of disposers) {
          try { dispose() } catch (e) { /* 一个面板卸载失败不阻塞其余 */ }
        }
        styles.dispose()
      }
    }

    return module.exports
  },
})
