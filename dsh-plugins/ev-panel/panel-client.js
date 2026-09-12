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
              ' —— 只在终态卡上算（实验中未判决，不进分母）。',
              React.createElement('b', { style: { color: 'var(--c-amber)' } },
                '注意：这个数高不是成绩，是症状'),
              '——终态卡里一次「不采纳/换方向」都没有，说明拒绝域为空（见「① 要处理的」第 1 条）。'),
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
        React.createElement(EmptyBox, { text: '近期快照里没有可画趋势的指标（routed_accuracy / tier2_hit / sessions_total 均缺）' }))
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
                ? '注：可画的读数在各期没有变化，趋势不可读——'
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
            '无执行记录（' + (execLog.state === 'missing' ? '还没有任何收尾记录'
              : execLog.state === 'unavailable' ? execLog.note : '解析失败或 records 为空') + '）——'
            + '这是正常退化路径：内容流程收尾应先落一条 exec-log，evolve-check 才读得到本轮现场。'),
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
          React.createElement('span', { className: 'v' }, runs + ' 次' + (runs ? '（其中无信号 ' + silent + '）' : '')),
        ),
        runs ? null : React.createElement('div', { className: 'ev-note', style: { color: 'var(--c-amber)' } },
          'exec-log 里没有 evolve-check 收尾记录——无法区分"跑了无信号"与"没跑"；'
          + '内容流程收尾应落一条（skills/evolve-check 第 4 步）。'),
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
          + '；内容流程（issue-ingest / to-reference / to-postmortem / knowledge-groom）收尾落一条，'
          + 'evolve-check 收尾也落一条（含"无信号"）。跨克隆/跨机不聚合——那要走 `--summary` 的'
          + '聚合值进 metrics/timeline.yaml'),
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

    // 预测实测记录：**系统里唯一真实的负反馈读数**。为什么单独给一行：这一层修前完全不可见
    // （`ev_measure.py --run` 只往 stdout 打印），于是"9 张卡写了可复现判据、一次没测过"
    // 在数据上不可区分；而"被证伪"是唯一能证明拒绝域存在的证据。记录在
    // metrics/ev-measure-log.yaml（同一克隆共享，append-only）。
    const MEASURE_LABEL = { PASS: '符合', FAIL: '被证伪', ERROR: '判不了' }
    function measureLine(health) {
      const ro = (health && health.readouts) || {}
      const mv = ro.measure_by_verdict || {}
      const runs = ro.measure_runs || 0
      if (!runs) {
        return React.createElement('div', { className: 'ev-note', style: { marginTop: 8 } },
          '预测实测记录：0 笔——写了可复现判据的卡里，',
          React.createElement('b', { style: { color: 'var(--c-amber)' } }, '一次都没有被复现过'),
          '。"声明了"与"测过"是两件事；跑一次：python3 scripts/ev_measure.py <卡号> --run')
      }
      const parts = ['PASS', 'FAIL', 'ERROR'].filter(k => mv[k]).map(k => MEASURE_LABEL[k] + ' ' + mv[k])
      return React.createElement('div', { className: 'ev-note', style: { marginTop: 8 } },
        '预测实测记录：', React.createElement('b', { style: { color: 'var(--tx)' } }, runs + ' 笔'),
        '（', parts.join(' · '), '）——这是系统里唯一真实的负反馈读数；',
        '「被证伪」是拒绝域存在的唯一证据。记录：', ro.measure_ledger ? ro.measure_ledger.state : '—')
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
              '结论不可用：' + broken.length + ' 条判据没被评估')
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
            right: fails.length + ' 项' + (others.length ? ' · 另 ' + others.length + ' 项如实标注' : ''),
          },
            fails.length
              ? fails.map(row)
              : React.createElement('div', { className: 'ev-empty' },
                  '本期没有需要动作的判据——这不等于"没问题"：先看上面的判据覆盖面，'
                  + '"没报越界"与"没被检查"是两件事。'),
            others.length ? others.map(row) : null,
            broken.length ? React.createElement('div', { className: 'ev-note', style: { marginTop: 8, color: 'var(--c-purple)' } },
              '体检器自身：' + broken.join('；')) : null,
            measureLine(health),
          ),
        ),
      )
    }

    // ============ ② 这批补在哪一层（触及面，确定性派生） ============
    const SURFACE_META = {
      '判断更准': { acc: 'var(--acc-blue)', hint: '路由 / 候选排序 / 知识内容——直接作用于判断' },
      '闸门更硬': { acc: 'var(--acc-purple)', hint: 'CI / 校验器 / 评测——把规则搬进可观测失败的一侧' },
      '看得见': { acc: 'var(--acc-green)', hint: '脚本 / 面板 / 观测面——让后面能判' },
      '走得顺': { acc: 'var(--acc-amber)', hint: '流程 / 文档 / 卡片机制本身' },
      '未归因': { acc: 'var(--acc-gray)', hint: '卡文本里扫不到仓库路径（如实标注，不猜）' },
    }

    function SurfacePanel({ stats }) {
      if (!stats) return null
      const cum = stats.by_surface || {}
      const rec = stats.by_surface_recent || {}
      const win = stats.surface_window_days || 7
      const order = ['判断更准', '闸门更硬', '看得见', '走得顺', '未归因']
      const keys = order.filter(k => (cum[k] || 0) + (rec[k] || 0) > 0)
        .concat(Object.keys(cum).filter(k => order.indexOf(k) < 0))
      // 0 张卡时**不静默消失**：整个区块 return null 会让编号从 ① 跳到 ③，读者以为是渲染坏了。
      // 如实说明"没有可归因的卡"，与其余区块的退化口径一致。
      if (!keys.length) {
        return React.createElement(Section, { title: '② 这批补在哪一层' },
          React.createElement('div', { className: 'ev-empty' },
            '暂无可归因的卡（proposals/ideas/ 为空或尚未产出卡片）——触及面由卡里写下的仓库路径派生，'
            + '没有卡就没有这一层读数。'))
      }
      const max = Math.max(1, ...keys.map(k => cum[k] || 0))
      const basis = stats.surface_basis_strength || {}
      const top = stats.top_signal
      return React.createElement(Section, {
        title: '② 这批补在哪一层',
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
          React.createElement('b', null, '轴记的是「改动落在机器的哪一层」'),
          '——不是"变好了多少"，也不是作者想优化什么。轴由卡里已写下的仓库路径',
          React.createElement('b', null, '确定性派生'),
          '（不让 agent 自己声明，免得学会写能通过的标签）；依据来自改动自述时最硬，来自证据引用时'
          + '只是线索。',
          React.createElement('br', null),
          React.createElement('b', null, '变好多少属能力轴，当前不可解读'),
          '：现场反馈捕获为 0，命中率/误诊率/校准都没有分母。此处不画趋势线称"稳定"（原则十）。',
        ),
        Object.keys(basis).length
          ? React.createElement('div', { className: 'ev-note', style: { marginTop: 6 } },
              '归因依据强度：' + Object.keys(basis).sort((a, b) => basis[b] - basis[a])
                .map(k => k + ' ' + basis[k]).join(' · ')
              + '（强 = 改动自述；弱 = 取自证据引用，未必是改动落点）')
          : null,
        top
          ? React.createElement('div', { className: 'ev-note' },
              '信号集中度：最高信号 ', React.createElement('b', { style: { color: 'var(--tx)' } }, top.signal),
              ' ', top.cards, ' 张（占 ', Math.round((stats.top_signal_share || 0) * 100), '%）· ',
              top.first, '→', top.last, '——29 种信号均匀分布时每种约 2%')
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
          React.createElement('span', { className: 'ev-sec-t' }, '④ 卡片（diff 日志）'),
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
      const load = React.useCallback(() => {
        setState({ loading: true, data: null, error: null })
        setHealth(null)
        host.call('ev-board-load', { sessionId: sessionId }).then(r => {
          if (r && r.ok) setState({ loading: false, data: r.data, error: null })
          else setState({ loading: false, data: null, error: (r && r.error) || '读取失败' })
        }).catch(e => setState({ loading: false, data: null, error: String(e && e.message || e) }))
        host.call('ev-health-load', { sessionId: sessionId }).then(r => {
          if (r && r.ok) setHealth(r.data)
        }).catch(() => {})
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
          React.createElement('span', { className: 'ev-title' }, '自演进 · 体检'),
          React.createElement('span', { className: 'ev-meta' },
            'EV 卡 ', React.createElement('b', null, data.idea_count || 0), ' 张 · 数据 ',
            (data.generated_at || '').replace('T', ' ')),
          React.createElement('button', {
            type: 'button', className: 'ev-btn', onClick: load, style: { marginLeft: 'auto' },
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
