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
      in_experiment: { label: '实验中', color: 'var(--c-blue)', fill: 'var(--fill-blue)', acc: 'var(--acc-blue)', hint: '产卡即执行——agent 正在改并验证' },
      validated: { label: '已采纳', color: 'var(--c-green)', fill: 'var(--fill-green)', acc: 'var(--acc-green)', hint: 'eval 验证 solid，改动保留' },
      rejected: { label: '未采纳', color: 'var(--c-gray)', fill: 'var(--fill-gray)', acc: 'var(--acc-gray)', hint: '试了不行——诚实实验记录' },
      superseded: { label: '已替代', color: 'var(--c-gray)', fill: 'var(--fill-gray)', acc: 'var(--acc-gray)', hint: '换方向，被新卡取代' },
    }
    const LAYER_LABELS = { L1: '内容', L2: '流程', L3: '机制' }
    const AUTH_META = {
      auto: { label: 'auto', color: 'var(--c-green)', hint: '低风险可逆，agent 自动合入' },
      review: { label: 'review', color: 'var(--c-blue)', hint: '中风险，人审 PR' },
      dual: { label: 'dual', color: 'var(--c-red)', hint: '高风险，双人签核' },
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
  padding:10px 12px 18px;display:flex;flex-direction:column;gap:10px;
  color:var(--tx);font-size:12px;line-height:1.5;
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
.ev-title{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.ev-meta{font-size:10.5px;color:var(--tx2);font-variant-numeric:tabular-nums}
.ev-meta b{color:var(--tx);font-weight:650}

/* —— 区块 —— */
.ev-sec{background-color:var(--b);background-image:linear-gradient(var(--surf),var(--surf));
  border:1px solid var(--hair);border-radius:12px;
  padding:11px 13px;box-shadow:0 1px 2px rgba(0,0,0,.035)}
.ev-sec-hd{display:flex;align-items:center;gap:8px;margin-bottom:9px}
.ev-sec-hd.has-body{margin-bottom:9px}
.ev-sec-t{font-size:12px;font-weight:680;letter-spacing:.005em}
.ev-sec-r{margin-left:auto;font-size:10px;color:var(--tx2);font-variant-numeric:tabular-nums}
.ev-label{font-size:9.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
  color:var(--tx2);margin-bottom:5px}

/* —— 按钮 —— */
.ev-btn{font:inherit;font-size:11px;font-weight:600;cursor:pointer;
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
.ev-focus{display:flex;gap:8px;flex-wrap:wrap}
.ev-fcard{flex:1 1 152px;min-width:0;text-align:left;cursor:pointer;font:inherit;color:inherit;
  background-color:var(--b);background-image:linear-gradient(var(--surf),var(--surf));border:1px solid var(--hair);border-radius:11px;padding:9px 11px;
  display:flex;flex-direction:column;gap:4px;
  transition:border-color .16s ease,background-color .16s ease,transform .16s cubic-bezier(.22,1,.36,1),box-shadow .16s ease}
.ev-fcard:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.07);
  border-color:var(--bd2);background:color-mix(in srgb,var(--tx) 3%,var(--b))}
.ev-fcard:focus-visible{outline:2px solid var(--br);outline-offset:2px}
.ev-fcard.live{border-color:color-mix(in srgb,var(--fc-acc,var(--fc)) 42%,transparent)}
.ev-fcard.live:hover{border-color:color-mix(in srgb,var(--fc-acc,var(--fc)) 70%,transparent)}
.ev-frow{display:flex;align-items:center;gap:6px}
.ev-flabel{font-size:11px;color:var(--tx2);letter-spacing:.01em}
.ev-fnum{margin-left:auto;font-size:17px;font-weight:800;line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em;
  color:var(--fc,var(--tx2))}
.ev-fnote{font-size:10px;color:var(--tx2);font-family:var(--mono);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev-stats{display:flex;gap:16px;flex-wrap:wrap;margin-top:9px;font-size:10.5px;color:var(--tx2)}
.ev-stats b{color:var(--tx);font-weight:680;font-variant-numeric:tabular-nums}

/* —— 状态点 —— */
.ev-dot{width:7px;height:7px;border-radius:999px;background:var(--dc);flex-shrink:0;display:inline-block}
.ev-dot.pulse{animation:ev-pulse 2.2s ease-in-out infinite}
@keyframes ev-pulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--dc) 45%,transparent)}
  50%{box-shadow:0 0 0 3.5px color-mix(in srgb,var(--dc) 0%,transparent)}}

/* —— 徽标 —— */
.ev-pill{font-size:10px;line-height:1.7;padding:0 7px;border-radius:999px;white-space:nowrap;
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
.ev-id{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--link);letter-spacing:-.01em}
.ev-age{margin-left:auto;font-size:10px;color:var(--tx2);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.ev-ctitle{margin-top:5px;font-size:12.5px;font-weight:600;line-height:1.5;color:var(--tx)}
.ev-csum{margin-top:4px;font-size:11px;color:var(--tx2);line-height:1.55;
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

.ev-txt{font-size:12px;line-height:1.65;color:var(--tx);white-space:pre-wrap;word-break:break-word}
.ev-effect{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;font-size:12px}
.ev-effect .m{font-weight:680}
.ev-effect .from{color:var(--tx2);font-family:var(--mono);font-size:11px}
.ev-effect .arrow{color:var(--tx2);margin:0 1px}
.ev-effect .to{color:var(--ok);font-weight:700;font-family:var(--mono);font-size:11.5px}
.ev-kv{font-size:11px;line-height:1.6;color:var(--tx)}
.ev-kv .k{color:var(--tx2)}
.ev-box{background-color:var(--b);background-image:linear-gradient(var(--surf),var(--surf));border:1px solid var(--hair);border-radius:9px;
  padding:9px 11px;display:flex;flex-direction:column;gap:6px}

/* 信号 */
.ev-sig{margin-bottom:8px}
.ev-sig:last-child{margin-bottom:0}
.ev-sigrow{display:flex;align-items:flex-start;gap:7px}
.ev-sigev{font-size:11px;line-height:1.6;color:var(--tx);flex:1;min-width:0}
.ev-traj{margin-top:4px;padding-left:9px;border-left:1px solid var(--hair)}
.ev-traj div{font-size:10px;color:var(--tx2);font-family:var(--mono);line-height:1.65;word-break:break-all}

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
.ev-decwho{font-size:11px;color:var(--tx2)}
.ev-decwhen{font-size:10px;color:var(--tx2);font-family:var(--mono);font-variant-numeric:tabular-nums}
.ev-decct{margin-top:4px;font-size:12px;line-height:1.68;color:var(--tx);
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
.ev-krow{display:flex;justify-content:space-between;gap:8px;font-size:11px;padding:2.5px 0}
.ev-krow .k{color:var(--tx2);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev-krow .v{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--tx);flex-shrink:0}
.ev-note{font-size:10px;color:var(--tx2);margin-top:7px;line-height:1.6}

/* —— 趋势 —— */
.ev-bars{display:flex;align-items:flex-end;gap:6px;height:60px;padding:2px 0 0}
.ev-barcol{flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;gap:4px}
.ev-barv{font-size:9px;font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--c-blue)}
.ev-barcol i{width:100%;border-radius:3px 3px 2px 2px;
  background:linear-gradient(180deg,var(--acc-blue),color-mix(in srgb,var(--acc-blue) 45%,transparent));
  transition:height .45s cubic-bezier(.22,1,.36,1),opacity .2s ease}
.ev-barcol.dim i{opacity:.42}
.ev-barcol:hover i{opacity:1}
.ev-barx{font-size:8.5px;color:var(--tx2);font-family:var(--mono);
  max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev-empty{font-size:11px;color:var(--tx2);padding:6px 0;line-height:1.6}
.ev-err{font-size:11px;color:var(--er);line-height:1.6}

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

    // ============ ① 待办/待审优先条 ============
    // 首屏回答"现在该看哪张卡"：实验中的卡（agent 正在动）+ 审计缺口 + 最近采纳。
    function FocusStrip({ stats, ideas, onFocus }) {
      const inExp = ideas.filter(c => c.status === 'in_experiment')
      const gaps = ideas.filter(c => (c.gaps || []).length)
      const recent = ideas.filter(c => c.status === 'validated')
        .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
        .slice(0, 3)
      const cards = [
        {
          key: 'exp', color: 'var(--c-blue)', acc: 'var(--acc-blue)', label: '实验中', n: inExp.length,
          note: inExp.length ? inExp.map(c => c.id).slice(0, 3).join(' · ') : '无',
          hint: 'agent 正在改并验证——产卡即执行，无需你审批；点开看它在改什么',
        },
        {
          key: 'gap', color: gaps.length ? 'var(--c-amber)' : 'var(--c-green)', acc: gaps.length ? 'var(--acc-amber)' : 'var(--acc-green)', label: '审计缺口', n: gaps.length,
          note: gaps.length ? gaps.map(c => c.id).slice(0, 3).join(' · ') : '无',
          hint: '机制要求与卡实际字段不符（缺成本/状态滞后/缺决策）——该补的是机制推进，不是人审',
        },
        {
          key: 'recent', color: 'var(--c-green)', acc: 'var(--acc-green)', label: '最近采纳', n: recent.length,
          note: recent.length ? recent.map(c => c.id).slice(0, 3).join(' · ') : '无',
          hint: '最近 3 张已采纳的卡——点开看系统学到了什么',
        },
      ]
      const adoption = stats && stats.adoption_rate !== null && stats.adoption_rate !== undefined
        ? Math.round(stats.adoption_rate * 100) + '%' : '—'
      return React.createElement('div', null,
        React.createElement('div', { className: 'ev-focus' },
          cards.map(c => React.createElement('button', {
            key: c.key, type: 'button', onClick: () => onFocus(c.key), title: c.hint,
            className: 'ev-fcard' + (c.n ? ' live' : ''),
            style: { '--fc': c.color, '--fc-acc': c.acc || c.color },
          },
            React.createElement('div', { className: 'ev-frow' },
              React.createElement(Dot, { color: c.acc || c.color, pulse: c.key === 'exp' && c.n > 0 }),
              React.createElement('span', { className: 'ev-flabel' }, c.label),
              React.createElement('span', { className: 'ev-fnum' }, c.n),
            ),
            React.createElement('div', { className: 'ev-fnote' }, c.note),
          )),
        ),
        React.createElement('div', { className: 'ev-stats' },
          React.createElement('span', null, '采纳率 ', React.createElement('b', null, adoption), '（终态卡 ', (stats && stats.terminal_count) || 0, ' 张）'),
          stats && stats.cost_median !== null && stats.cost_median !== undefined
            ? React.createElement('span', null, '单卡成本中位 ', React.createElement('b', null, fmtTokens(stats.cost_median)), ' tok · 累计 ', fmtTokens(stats.cost_total), '（', stats.cost_cards, ' 张有记账）')
            : null,
          stats && stats.oldest_open_days !== null && stats.oldest_open_days !== undefined
            ? React.createElement('span', null, '最久未闭合 ', React.createElement('b', null, stats.oldest_open_days + ' 天'))
            : null,
        ),
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
              React.createElement('span', { style: { fontSize: 10, color: 'var(--tx2)' } }, '只追加不修改——提案 → 执行 → 验证 → 判断'),
            ),
            d ? React.createElement(DecisionChain, { decisions: d.decisions })
              : (idea.decisions || []).map((x, i) => React.createElement('div', { key: i, className: 'ev-kv' }, x.summary + (x.length > 60 ? '…' : ''))),
          ),
          // —— 元信息
          (d && (d.principle_refs || []).length) ? React.createElement('div', { style: { fontSize: 10, color: 'var(--tx2)' } },
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
          ? React.createElement(EmptyBox, { text: filter === 'focus' ? '无待办卡——没有实验中的卡，也没有审计缺口' : '该筛选下无卡' })
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
              ' —— 只在终态卡上算（实验中未判决，不进分母）'),
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

    // ============ 指标趋势（routed_accuracy） ============
    function TimelineTrend({ timeline }) {
      const all = timeline || []
      const live = all.filter(p => p.kind === 'live')
      const rows = (live.length ? live : all).slice(-8)
      if (!rows.length) return React.createElement(Section, { title: '指标趋势' }, React.createElement(EmptyBox, { text: 'timeline 无数据' }))
      const vals = rows.map(p => (typeof p.routed_accuracy === 'number' ? p.routed_accuracy : null))
      const nums = vals.filter(v => v !== null)
      const max = nums.length ? Math.max(...nums) : 1
      const min = nums.length ? Math.min(...nums) : 0
      const span = max - min || 1
      return React.createElement(Section, {
        title: '指标趋势',
        right: (live.length ? 'live 期' : 'replay/示例参考（live 期不足）') + ' · routed_accuracy',
      },
        React.createElement('div', { className: 'ev-bars' },
          rows.map((p, i) => {
            const v = vals[i]
            const h = v === null ? 4 : 10 + Math.round(((v - min) / span) * 42)
            return React.createElement('div', {
              key: p.period + i,
              className: 'ev-barcol' + (p.kind === 'live' ? '' : ' dim'),
              title: p.period + ' · ' + (p.title || '') + ' · ' + (v === null ? '无值' : v),
            },
              React.createElement('span', { className: 'ev-barv', style: v === null ? { color: 'var(--tx2)' } : undefined },
                v === null ? '—' : v),
              React.createElement('i', { style: { height: h, background: v === null ? 'var(--bd)' : undefined } }),
              React.createElement('span', { className: 'ev-barx' }, String(p.period || '').replace(/^2026-/, '')),
            )
          }),
        ),
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
          const ratio = cell.cap ? cell.count / cell.cap : 0
          rows.push({ ns, cat, ...cell, ratio })
        })
      })
      rows.sort((a, b) => b.ratio - a.ratio)
      const over = rows.filter(r => r.count > r.cap)
      const near = rows.filter(r => r.count <= r.cap && r.ratio > 0.8)
      return React.createElement(Section, {
        title: '知识库容量',
        right: rows.length + ' 格 · 明细见「指标」tab',
      },
        (over.length || near.length)
          ? React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
              over.concat(near).map(r => React.createElement(Pill, {
                key: r.ns + r.cat, color: r.count > r.cap ? 'var(--c-red)' : 'var(--c-amber)',
                title: r.ns + ' · ' + r.cat + ' ' + r.count + '/' + r.cap,
              }, r.ns.split('/').pop() + ' · ' + r.cat + ' ' + r.count + '/' + r.cap)))
          : React.createElement(EmptyBox, { text: '所有格子均在 soft_cap 的 80% 以下，无压力' }),
      )
    }

    // ============ 流程演进信号（无数据不占位） ============
    function TallySection({ tally, s2Attrib }) {
      const hasTally = tally && tally.length
      const hasS2 = s2Attrib && s2Attrib.length
      if (!hasTally && !hasS2) {
        return React.createElement(Section, { title: '流程演进信号' },
          React.createElement('div', { className: 'ev-empty' },
            '暂无归因事件——S1 反馈归因或 S2 replay 路由 miss 积累后出现。'),
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

    // ============ 主视图 ============
    function BoardView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null, error: null })
      const [filter, setFilter] = React.useState('focus')
      const [archivedOpen, setArchivedOpen] = React.useState(false)

      const load = React.useCallback(() => {
        setState({ loading: true, data: null, error: null })
        host.call('ev-board-load', { sessionId: sessionId }).then(r => {
          if (r && r.ok) setState({ loading: false, data: r.data, error: null })
          else setState({ loading: false, data: null, error: (r && r.error) || '读取失败' })
        }).catch(e => setState({ loading: false, data: null, error: String(e && e.message || e) }))
      }, [sessionId])

      React.useEffect(() => { load() }, [load])

      if (state.loading) return React.createElement('div', { className: 'ev-root' },
        React.createElement('div', { className: 'ev-empty', style: { textAlign: 'center', padding: 24 } }, '加载自演进数据…'))
      if (state.error) return React.createElement('div', { className: 'ev-root' },
        React.createElement('div', { className: 'ev-err', style: { padding: 14 } }, '数据加载失败：' + state.error))

      const data = state.data || {}
      const ideas = data.ideas || []

      return React.createElement('div', { className: 'ev-root' },
        React.createElement('div', { className: 'ev-top ev-rise' },
          React.createElement('span', { className: 'ev-mark' }),
          React.createElement('span', { className: 'ev-title' }, '自演进看板'),
          React.createElement('span', { className: 'ev-meta' },
            'EV 卡 ', React.createElement('b', null, data.idea_count || 0), ' 张 · 数据 ',
            (data.generated_at || '').replace('T', ' ')),
          React.createElement('button', {
            type: 'button', className: 'ev-btn', onClick: load, style: { marginLeft: 'auto' },
          }, '刷新'),
        ),
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(FocusStrip, {
            stats: data.stats, ideas: ideas,
            onFocus: (key) => { setFilter(key === 'exp' ? 'exp' : key === 'gap' ? 'gap' : 'adopted') },
          }),
        ),
        React.createElement('div', { className: 'ev-rise' },
          React.createElement(DecisionFeed, {
            ideas: ideas, sessionId: sessionId, filter: filter, setFilter: setFilter,
            archivedOpen: archivedOpen, setArchivedOpen: setArchivedOpen,
          }),
        ),
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
