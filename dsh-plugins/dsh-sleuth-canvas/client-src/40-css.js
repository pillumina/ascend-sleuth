// 页面样式：三栏布局 + 玻璃悬浮件 + 状态/加载动效。颜色只用宿主 --dsw-alias-* 令牌
// 与自定义 --sc-* 语义色；动效只有三档时长；容器查询做窄屏降级。

SC.css = `
.sc-root{
  --sc-font:ui-sans-serif,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  --sc-mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sc-surface:var(--dsw-alias-bg-base,#ffffff);
  --sc-layer1:var(--dsw-alias-bg-layer-1,#f7f8fa);
  --sc-layer2:var(--dsw-alias-bg-layer-2,#eef0f4);
  --sc-overlay:var(--dsw-alias-bg-overlay,#ffffff);
  --sc-text:var(--dsw-alias-label-primary,#101318);
  --sc-text2:var(--dsw-alias-label-secondary,#5b6472);
  --sc-text3:color-mix(in srgb, var(--sc-text2) 64%, transparent);
  --sc-line:color-mix(in srgb, var(--sc-text) 9%, transparent);
  --sc-line-strong:color-mix(in srgb, var(--sc-text) 16%, transparent);
  --sc-accent:var(--dsw-alias-brand-primary,#4a7dff);
  --sc-accent-soft:color-mix(in srgb, var(--sc-accent) 12%, transparent);
  --sc-on-accent:#ffffff;
  --sc-intake:#D9902F;--sc-route:#4A7DFF;--sc-index:#2AA7B8;--sc-check:#8A6CF0;
  --sc-book:#3C9A78;--sc-code:#E07A3F;--sc-hit:#3FA46A;--sc-miss:#6E7C93;
  --sc-flag:#C9A227;--sc-feedback:#7C8698;--sc-warn:#D9822B;--sc-risk:#D65454;
  --sc-r-sm:6px;--sc-r-md:10px;--sc-r-lg:14px;--sc-r-pill:999px;
  --sc-space-1:4px;--sc-space-2:6px;--sc-space-3:8px;--sc-space-4:12px;--sc-space-5:16px;--sc-space-6:24px;
  --sc-fs-lg:20px;--sc-fs-md:13.5px;--sc-fs-base:13px;--sc-fs-sm:12.5px;
  --sc-fs-xs:11.5px;--sc-fs-2xs:10.5px;--sc-fs-3xs:10px;
  --sc-lh-body:1.65;
  --sc-m-fast:120ms;--sc-m-base:180ms;--sc-m-slow:320ms;
  --sc-ease:cubic-bezier(.22,.61,.36,1);
  --sc-shadow-float:0 18px 48px -28px color-mix(in srgb, var(--sc-text) 52%, transparent);
  height:100%;min-height:0;display:flex;flex-direction:column;overflow:hidden;
  container-type:inline-size;
  background:
    radial-gradient(90% 60% at 50% -10%, color-mix(in srgb, var(--sc-accent) 5%, transparent), transparent 68%),
    var(--sc-surface);
  color:var(--sc-text);
  font-family:var(--sc-font);font-size:var(--sc-fs-base);line-height:var(--sc-lh-body);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
.sc-root *,.sc-root *::before,.sc-root *::after{box-sizing:border-box}
.sc-root :focus-visible{outline:2px solid color-mix(in srgb, var(--sc-accent) 55%, transparent);outline-offset:2px}
.sc-sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}

/* ── 深色：色相不变，明度 +6%、饱和度 -6%（与主题模块同一规则）────────── */
body[data-ds-dark-theme] .sc-root,
[data-ds-dark-theme] .sc-root,
html[data-theme="dark"] .sc-root,
html[data-mode="dark"] .sc-root{
  --sc-intake:#E2A046;--sc-route:#6E9BFF;--sc-index:#45B9C9;--sc-check:#A48DF5;
  --sc-book:#4FB58E;--sc-code:#E99563;--sc-hit:#55BE82;--sc-miss:#8B94A3;
  --sc-flag:#D7B13F;--sc-feedback:#969DA8;--sc-warn:#E2954E;--sc-risk:#E27272;
  --sc-shadow-float:0 22px 60px -28px rgba(0,0,0,.62);
}

/* ── 页头 ─────────────────────────────────────────────────────────────── */
.sc-header{
  flex-shrink:0;display:grid;grid-template-columns:minmax(0,1fr) auto;
  grid-template-areas:"brand right" "summary summary" "conclusion conclusion";
  column-gap:16px;row-gap:6px;padding:11px 16px 9px;
  border-bottom:1px solid var(--sc-line);
  background:linear-gradient(180deg, color-mix(in srgb, var(--sc-layer1) 62%, var(--sc-surface)), var(--sc-surface));
}
.sc-brand{grid-area:brand;display:flex;align-items:center;gap:10px;min-width:0}
.sc-mark{flex-shrink:0;display:block}
.sc-titles{min-width:0}
.sc-title{font-size:var(--sc-fs-lg);font-weight:650;letter-spacing:.2px;line-height:1.2;color:var(--sc-text)}
.sc-sub{margin-top:2px;font-size:var(--sc-fs-xs);color:var(--sc-text2);letter-spacing:.2px;line-height:1.3}
.sc-head-right{grid-area:right;display:flex;align-items:center;gap:10px;min-width:0}
.sc-chips{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:flex-end;min-width:0}
.sc-chip{
  display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 9px;max-width:238px;
  border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);
  background:color-mix(in srgb, var(--sc-layer2) 68%, transparent);
  font-size:var(--sc-fs-xs);color:var(--sc-text2);white-space:nowrap;
}
.sc-chip-dot{width:6px;height:6px;border-radius:50%;background:var(--tone,var(--sc-feedback));flex-shrink:0;
  box-shadow:0 0 0 3px color-mix(in srgb, var(--tone,var(--sc-feedback)) 14%, transparent)}
.sc-chip-key{font-size:10.5px;letter-spacing:.3px;color:var(--sc-text3)}
.sc-chip-value{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--sc-text)}
.sc-summary{grid-area:summary;display:flex;align-items:flex-start;gap:10px;min-width:0}
.sc-summary-bar{width:3px;border-radius:2px;align-self:stretch;min-height:16px;background:var(--sc-accent);opacity:.8;flex-shrink:0}
.sc-summary-text{
  margin:0;flex:1;min-width:0;font-size:12px;line-height:1.65;color:var(--sc-text2);
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  cursor:pointer;overflow-wrap:anywhere;
}
.sc-summary-text.is-open{display:block;-webkit-line-clamp:unset;overflow:visible}
.sc-summary-toggle{
  appearance:none;border:0;background:transparent;padding:1px 0;flex-shrink:0;
  font:inherit;font-size:11px;color:var(--sc-accent);cursor:pointer;white-space:nowrap;
  transition:opacity var(--sc-m-fast) var(--sc-ease);
}
.sc-summary-toggle:hover{opacity:.78}

/* ── 按钮 ─────────────────────────────────────────────────────────────── */
.sc-btn{
  appearance:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;
  height:28px;padding:0 11px;border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer1) 72%, transparent);
  color:var(--sc-text2);font:inherit;font-size:12px;cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease),
    border-color var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-btn:hover{color:var(--sc-text);border-color:var(--sc-line-strong);background:color-mix(in srgb, var(--sc-layer2) 78%, transparent)}
.sc-btn:active{transform:translateY(.5px)}
.sc-btn:disabled{opacity:.45;cursor:default;transform:none}
.sc-btn-primary{background:var(--sc-accent);border-color:transparent;color:var(--sc-on-accent);font-weight:550}
.sc-btn-primary:hover{background:var(--sc-accent);border-color:transparent;color:var(--sc-on-accent);filter:brightness(1.06)}
.sc-btn-ghost{background:transparent}
.sc-refresh{height:28px;padding:0 10px}
.sc-refresh.is-busy .sc-spin{animation:sc-spin 900ms linear infinite}
.sc-spin{animation:sc-spin 900ms linear infinite;transform-origin:50% 50%}
.sc-btn-text{font-size:12px}
.sc-link-btn{
  appearance:none;border:0;background:transparent;padding:0;margin-left:6px;
  font:inherit;font-size:11.5px;color:var(--sc-accent);cursor:pointer;
}

/* ── 三栏骨架 ─────────────────────────────────────────────────────────── */
.sc-body{position:relative;flex:1;min-height:0;display:grid;grid-template-columns:264px minmax(0,1fr) 336px}

/* ── 左：会话列表 ─────────────────────────────────────────────────────── */
.sc-list{
  position:relative;display:flex;flex-direction:column;min-height:0;min-width:0;
  border-right:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 52%, var(--sc-surface));
}
.sc-list-rail{display:none}
.sc-list-main{display:flex;flex-direction:column;min-height:0;flex:1}
.sc-list-head{display:flex;align-items:center;gap:8px;padding:12px 14px 7px;flex-shrink:0}
.sc-list-toggle{display:none;appearance:none;border:1px solid var(--sc-line);border-radius:8px;background:transparent;
  color:var(--sc-text2);width:28px;height:28px;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0}
.sc-list-title{font-size:var(--sc-fs-md);font-weight:650;color:var(--sc-text);white-space:nowrap;letter-spacing:.1px}
.sc-list-count{font-family:var(--sc-mono);font-size:11px;font-weight:400;color:var(--sc-text2)}
.sc-sort{margin-left:auto;display:flex;gap:1px;padding:2px;border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer2) 60%, transparent)}
.sc-sort-btn{
  appearance:none;border:0;background:transparent;font:inherit;font-size:10.5px;color:var(--sc-text3);
  padding:3px 6px;border-radius:6px;cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-sort-btn:hover{color:var(--sc-text2)}
.sc-sort-btn.is-on{background:var(--sc-surface);color:var(--sc-text);box-shadow:0 1px 2px color-mix(in srgb, var(--sc-text) 10%, transparent)}
.sc-search{
  margin:3px 12px 8px;display:flex;align-items:center;gap:7px;height:32px;padding:0 9px;flex-shrink:0;
  border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-surface) 78%, transparent);color:var(--sc-text3);
  transition:border-color var(--sc-m-fast) var(--sc-ease),box-shadow var(--sc-m-fast) var(--sc-ease);
}
.sc-search:focus-within{
  border-color:color-mix(in srgb, var(--sc-accent) 45%, transparent);
  box-shadow:0 0 0 3px var(--sc-accent-soft);
}
.sc-search-input{
  flex:1;min-width:0;border:0;outline:none;background:transparent;
  font:inherit;font-size:12.5px;color:var(--sc-text);
}
.sc-search-input::placeholder{color:var(--sc-text3)}
.sc-search-input::-webkit-search-cancel-button{display:none}
.sc-search-clear{appearance:none;border:0;background:transparent;color:var(--sc-text3);cursor:pointer;
  width:18px;height:18px;display:flex;align-items:center;justify-content:center;border-radius:4px}
.sc-search-clear:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 8%, transparent)}
.sc-warns{padding:0 13px 8px;display:flex;flex-direction:column;gap:5px;flex-shrink:0}
.sc-warn-row{display:flex;gap:6px;align-items:flex-start;font-size:11px;line-height:1.5;color:var(--sc-warn);overflow-wrap:anywhere}
.sc-warn-row svg{flex-shrink:0;margin-top:2px}
.sc-list-body{flex:1;min-height:0;overflow:auto;padding:2px 10px 12px;display:flex;flex-direction:column;gap:8px;overscroll-behavior:contain}
.sc-list-body::-webkit-scrollbar,.sc-insp-body::-webkit-scrollbar,.sc-evidence-inline::-webkit-scrollbar{width:8px;height:8px}
.sc-list-body::-webkit-scrollbar-thumb,.sc-insp-body::-webkit-scrollbar-thumb,.sc-evidence-inline::-webkit-scrollbar-thumb{
  background:color-mix(in srgb, var(--sc-text) 16%, transparent);border-radius:999px;border:2px solid transparent;background-clip:padding-box}
.sc-list-body::-webkit-scrollbar-track,.sc-insp-body::-webkit-scrollbar-track{background:transparent}
.sc-list-empty{
  margin:12px 4px;padding:18px 12px;border:1px dashed var(--sc-line-strong);border-radius:var(--sc-r-md);
  text-align:center;font-size:12px;line-height:1.65;color:var(--sc-text2);
}
.sc-list-foot{
  flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:8px 14px;border-top:1px solid var(--sc-line);
  font-size:10.5px;color:var(--sc-text3);white-space:nowrap;
}
.sc-repo{overflow:hidden;text-overflow:ellipsis;font-family:var(--sc-mono);font-size:10px}
.sc-repo.is-warn{font-family:var(--sc-font);color:var(--sc-warn)}
.sc-gen{overflow:hidden;text-overflow:ellipsis}

/* 会话卡片 */
.sc-session{
  appearance:none;position:relative;display:block;width:100%;text-align:left;font:inherit;color:var(--sc-text);
  content-visibility:auto;contain-intrinsic-size:auto 96px;
  padding:10px 11px 9px 13px;border:1px solid var(--sc-line);border-radius:12px;background:var(--sc-surface);
  cursor:pointer;overflow:hidden;
  transition:background-color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-session::before{
  content:"";position:absolute;left:0;top:11px;bottom:11px;width:2px;border-radius:2px;
  background:transparent;transition:background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-session:hover{background:color-mix(in srgb, var(--sc-layer2) 62%, var(--sc-surface));border-color:var(--sc-line-strong)}
.sc-session:active{transform:scale(.997)}
.sc-session.is-active{background:color-mix(in srgb, var(--sc-layer2) 82%, var(--sc-surface));
  border-color:color-mix(in srgb, var(--sc-accent) 30%, transparent)}
.sc-session.is-active::before{background:var(--sc-accent)}
.sc-session-top{display:flex;align-items:center;gap:7px;min-width:0}
.sc-status-dot{width:7px;height:7px;border-radius:50%;background:var(--dot,var(--sc-feedback));flex-shrink:0;
  box-shadow:0 0 0 3px color-mix(in srgb, var(--dot,var(--sc-feedback)) 13%, transparent)}
.sc-session-id{
  flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-family:var(--sc-mono);font-size:10.5px;letter-spacing:-.1px;line-height:1.4;color:var(--sc-text);
}
.sc-session-time{font-size:10.5px;color:var(--sc-text2);white-space:nowrap;font-variant-numeric:tabular-nums;flex-shrink:0}
.sc-session-open{display:none;font-size:10.5px;color:var(--sc-accent);white-space:nowrap;flex-shrink:0}
.sc-session:hover .sc-session-time,.sc-session:focus-visible .sc-session-time{display:none}
.sc-session:hover .sc-session-open,.sc-session:focus-visible .sc-session-open{display:inline}
.sc-session-summary{
  margin-top:5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  font-size:var(--sc-fs-xs);line-height:1.58;color:var(--sc-text2);overflow-wrap:anywhere;
}
.sc-session-meta{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px;align-items:center;min-width:0}
.sc-mini-chip{
  max-width:156px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  padding:3px 6px;border:1px solid var(--sc-line);border-radius:5px;
  background:color-mix(in srgb, var(--sc-layer2) 52%, transparent);
  font-size:10.5px;line-height:1;color:var(--sc-text2);
}
.sc-mini-chip.is-accent{color:var(--sc-accent);border-color:color-mix(in srgb, var(--sc-accent) 28%, transparent)}

/* ── 中：画布 ─────────────────────────────────────────────────────────── */
.sc-stage{
  position:relative;min-width:0;min-height:0;overflow:hidden;
  background:
    radial-gradient(72% 58% at 50% 42%, color-mix(in srgb, var(--sc-accent) 5%, transparent), transparent 72%),
    var(--sc-surface);
}
.sc-canvas-wrap{position:absolute;inset:0;overflow:hidden;container-type:size;container-name:sc-canvas}
.sc-canvas-wrap.is-hidden{display:none}
.sc-canvas{position:absolute;inset:0;width:100%;height:100%;display:block;touch-action:none;cursor:grab}
.sc-canvas:active{cursor:grabbing}

/* 顶部悬浮：会话 + 当前状态 */
.sc-canvas-top{
  position:absolute;left:14px;top:14px;z-index:4;max-width:min(560px,calc(100% - 96px));
  display:flex;flex-direction:column;gap:7px;padding:10px 12px;border-radius:12px;
  border:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 82%, transparent);
  -webkit-backdrop-filter:blur(14px) saturate(1.1);backdrop-filter:blur(14px) saturate(1.1);
  box-shadow:0 10px 30px -24px color-mix(in srgb, var(--sc-text) 60%, transparent);
}
.sc-canvas-top-row{display:flex;align-items:center;gap:8px;min-width:0}
.sc-top-id{display:flex;align-items:center;gap:7px;min-width:0;flex:1}
.sc-top-dot{width:6px;height:6px;border-radius:50%;background:var(--dot,var(--sc-hit));flex-shrink:0;
  box-shadow:0 0 0 3px color-mix(in srgb, var(--dot,var(--sc-hit)) 14%, transparent)}
.sc-top-name{font-family:var(--sc-mono);font-size:10.5px;line-height:1.4;color:var(--sc-text2);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-top-btn{
  appearance:none;display:none;align-items:center;gap:5px;height:24px;padding:0 8px;
  border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);background:transparent;
  font:inherit;font-size:11px;color:var(--sc-text2);cursor:pointer;flex-shrink:0;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-top-btn:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-layer2) 70%, transparent)}
.sc-canvas-summary{min-width:0}
.sc-canvas-summary-text{
  margin:0;font-size:11.5px;line-height:1.55;color:var(--sc-text2);overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}
.sc-now{
  display:inline-flex;align-items:center;gap:8px;align-self:flex-start;max-width:100%;
  padding:3px 9px 3px 4px;border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);
  background:color-mix(in srgb, var(--sc-layer2) 52%, transparent);
}
.sc-now-step{
  display:inline-flex;align-items:center;justify-content:center;min-width:25px;height:20px;padding:0 5px;
  border:1px solid var(--sc-line);border-radius:var(--sc-r-pill);background:var(--sc-surface);
  font-family:var(--sc-mono);font-size:10px;color:var(--sc-text);flex-shrink:0;
}
.sc-now-text{min-width:0;font-size:11.5px;color:var(--sc-text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* tooltip */
.sc-tooltip{
  position:absolute;z-index:6;transform:translate(-50%,-100%);min-width:172px;max-width:288px;
  padding:9px 11px;border-radius:var(--sc-r-md);border:1px solid var(--sc-line-strong);
  background:color-mix(in srgb, var(--sc-layer1) 94%, transparent);
  -webkit-backdrop-filter:blur(12px) saturate(1.1);backdrop-filter:blur(12px) saturate(1.1);
  box-shadow:var(--sc-shadow-float);pointer-events:none;
}
.sc-tooltip.is-below{transform:translate(-50%,0)}
.sc-tooltip-title{font-size:12.5px;font-weight:600;line-height:1.4;color:var(--sc-text);overflow-wrap:anywhere}
.sc-tooltip-sub{margin-top:3px;font-size:11px;line-height:1.5;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-tooltip-meta{margin-top:5px;font-family:var(--sc-mono);font-size:10px;line-height:1.4;color:var(--sc-text3);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* 底部停靠区：快捷键提示 / 图例 / 回放条共用一条排版，不再各自绝对定位到同一个左下角。
   右侧留出迷你地图的宽度（168 宽 + 16 右边距 + 30 空隙 = 214px），回放条不会盖住它。 */
.sc-canvas-dock{
  position:absolute;left:0;right:0;bottom:0;z-index:5;
  display:grid;grid-template-columns:auto minmax(0,1fr);align-items:end;
  gap:10px;padding:0 214px 14px 14px;pointer-events:none;
}
/* 停靠区只让真正的控件接收指针事件：格子本身透明，不能挡住画布拖拽与点选。 */
.sc-canvas-dock,.sc-dock-side,.sc-dock-main{pointer-events:none}
.sc-canvas-dock .sc-hint,.sc-canvas-dock .sc-legend,.sc-canvas-dock .sc-replay{pointer-events:auto}
.sc-dock-side{display:flex;flex-direction:column;align-items:flex-start;gap:6px;min-width:0;max-width:min(360px,52cqw)}
.sc-dock-main{display:flex;justify-content:center;min-width:0}

/* 图例 */
.sc-legend{
  display:flex;flex-direction:column;gap:5px;max-width:100%;min-width:0;
  padding:7px 9px;border:1px solid var(--sc-line);border-radius:var(--sc-r-md);
  background:color-mix(in srgb, var(--sc-layer1) 76%, transparent);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
}
.sc-legend-toggle{
  appearance:none;border:0;background:transparent;display:flex;align-items:center;gap:6px;
  height:16px;padding:0;font:inherit;font-size:10.5px;letter-spacing:.4px;color:var(--sc-text2);
  cursor:pointer;
}
.sc-legend-toggle:hover{color:var(--sc-text)}
.sc-legend-items{display:flex;flex-wrap:wrap;gap:5px 11px;max-width:100%}
.sc-legend-item{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;color:var(--sc-text2);white-space:nowrap}
.sc-legend-count{font-family:var(--sc-mono);font-size:10px;color:var(--sc-text3)}
.sc-dot{width:7px;height:7px;border-radius:50%;background:var(--dot,var(--sc-feedback));flex-shrink:0}

/* 缩放按钮（迷你地图在引擎画的右下角，DOM 按钮排在它上面） */
.sc-zoom{position:absolute;right:14px;bottom:148px;z-index:3;display:flex;flex-direction:column;gap:6px}
.sc-zoom-btn{
  width:32px;height:32px;border:1px solid var(--sc-line);border-radius:50%;
  background:color-mix(in srgb, var(--sc-layer1) 82%, transparent);
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  color:var(--sc-text2);display:flex;align-items:center;justify-content:center;cursor:pointer;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-zoom-btn:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-layer2) 82%, transparent);transform:translateY(-1px)}

/* 回放条 */
.sc-replay{
  display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:var(--sc-r-pill);
  border:1px solid var(--sc-line-strong);
  background:color-mix(in srgb, var(--sc-layer1) 84%, transparent);
  -webkit-backdrop-filter:blur(16px) saturate(1.15);backdrop-filter:blur(16px) saturate(1.15);
  box-shadow:var(--sc-shadow-float);max-width:100%;min-width:0;
}
.sc-replay.is-idle{padding:5px 7px}
/* 活动态占满主格：不拉伸时轨道只剩 min-width，刻度文字会互压。600 够「340 轨道 + 固定控件」。 */
.sc-replay.is-active{width:100%;max-width:600px}
.sc-replay-start{
  appearance:none;border:0;display:flex;align-items:center;gap:7px;
  padding:6px 12px 6px 10px;border-radius:var(--sc-r-pill);
  background:var(--sc-accent);color:var(--sc-on-accent);font:inherit;font-size:12px;font-weight:600;cursor:pointer;
  transition:filter var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-start:hover{filter:brightness(1.07);transform:translateY(-1px)}
.sc-replay-total{font-size:10.5px;font-weight:400;opacity:.82}
.sc-replay-play{
  width:34px;height:34px;border:0;border-radius:50%;flex-shrink:0;
  background:var(--sc-accent);color:var(--sc-on-accent);display:flex;align-items:center;justify-content:center;cursor:pointer;
  transition:filter var(--sc-m-fast) var(--sc-ease),transform var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-play:hover{filter:brightness(1.07)}
.sc-replay-track{
  position:relative;flex:1 1 clamp(150px,26cqw,340px);min-width:76px;max-width:340px;height:22px;
  border-radius:var(--sc-r-pill);background:color-mix(in srgb, var(--sc-text) 8%, transparent);cursor:pointer;
}
.sc-replay-fill{
  position:absolute;left:0;top:0;bottom:0;border-radius:var(--sc-r-pill);
  background:linear-gradient(90deg, color-mix(in srgb, var(--sc-accent) 24%, transparent), color-mix(in srgb, var(--sc-accent) 46%, transparent));
  transition:width var(--sc-m-base) var(--sc-ease);
}
.sc-replay-tick{
  position:absolute;top:50%;transform:translate(-50%,-50%);
  appearance:none;border:0;background:transparent;padding:0;cursor:pointer;
  display:flex;flex-direction:column;align-items:center;gap:1px;color:var(--sc-text3);
}
.sc-replay-tick::before{
  content:"";display:block;width:2px;height:9px;border-radius:1px;
  background:color-mix(in srgb, var(--sc-text) 30%, transparent);
  transition:background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-tick.is-past::before{background:color-mix(in srgb, var(--sc-accent) 75%, transparent)}
.sc-replay-tick-label{
  position:absolute;top:13px;font-family:var(--sc-mono);font-size:8.5px;line-height:1;
  white-space:nowrap;opacity:0;transition:opacity var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-tick:hover .sc-replay-tick-label,.sc-replay-tick.is-past .sc-replay-tick-label{opacity:1}
.sc-replay-count{font-family:var(--sc-mono);font-size:10.5px;color:var(--sc-text2);min-width:52px;text-align:center;
  font-variant-numeric:tabular-nums;flex-shrink:0}
.sc-replay-speed{display:flex;gap:1px;padding:2px;border-radius:var(--sc-r-pill);
  background:color-mix(in srgb, var(--sc-text) 7%, transparent);flex-shrink:0}
.sc-replay-speed-btn{
  appearance:none;border:0;background:transparent;font:inherit;font-size:10.5px;color:var(--sc-text2);
  padding:3px 7px;border-radius:var(--sc-r-pill);cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-speed-btn.is-on{background:var(--sc-surface);color:var(--sc-text);box-shadow:0 1px 2px color-mix(in srgb, var(--sc-text) 12%, transparent)}
.sc-replay-close{
  width:24px;height:24px;border:0;border-radius:50%;background:transparent;color:var(--sc-text2);
  display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;
  transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-replay-close:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 8%, transparent)}

/* 画布空态 / 错误态 / 读取态 */
.sc-stage-overlay{
  position:absolute;inset:0;z-index:5;display:flex;align-items:center;justify-content:center;padding:24px;
  background:color-mix(in srgb, var(--sc-surface) 62%, transparent);
  -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
}
.sc-empty-card{
  width:min(432px,100%);padding:22px 22px 18px;border:1px solid var(--sc-line);border-radius:16px;
  background:var(--sc-layer1);box-shadow:0 26px 70px -34px color-mix(in srgb, var(--sc-text) 48%, transparent);
  display:flex;flex-direction:column;align-items:flex-start;gap:10px;
}
.sc-empty-icon{color:var(--sc-text2);display:flex;align-items:center;justify-content:center}
.sc-empty-card.is-error .sc-empty-icon{color:var(--sc-warn)}
.sc-empty-title{font-size:15px;font-weight:650;line-height:1.4;color:var(--sc-text)}
.sc-empty-text{margin:0;font-size:12px;line-height:1.68;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-empty-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.sc-state-path{font-family:var(--sc-mono);font-size:11px;line-height:1.55;color:var(--sc-text3);overflow-wrap:anywhere}
.sc-state-path.is-warn{font-family:var(--sc-font);color:var(--sc-warn)}
.sc-state-hint{font-size:11.5px;line-height:1.6;color:var(--sc-text3)}
.sc-command{
  display:flex;align-items:center;gap:6px;padding:5px 6px 5px 10px;max-width:100%;
  border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer2) 52%, transparent);
  font-family:var(--sc-mono);font-size:11.5px;color:var(--sc-text);
}
.sc-command code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-state-screen{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;padding:28px;overflow:auto}
.sc-stage-loading{
  position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;
  color:var(--sc-text2);font-size:11.5px;pointer-events:none;
}

/* ── 右：检查器 ───────────────────────────────────────────────────────── */
.sc-inspector{
  position:relative;display:flex;flex-direction:column;min-height:0;min-width:0;
  border-left:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 44%, var(--sc-surface));
  overflow:hidden;
}
.sc-insp-headbar{flex-shrink:0;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px 7px}
.sc-insp-kicker{font-size:10.5px;font-weight:550;letter-spacing:.5px;color:var(--sc-text3)}
.sc-insp-close{
  display:none;appearance:none;border:1px solid var(--sc-line);border-radius:50%;
  width:26px;height:26px;background:transparent;color:var(--sc-text2);
  align-items:center;justify-content:center;cursor:pointer;
}
.sc-insp-close:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 8%, transparent)}
.sc-insp-body{
  flex:1;min-height:0;overflow:auto;padding:0 14px 18px;
  display:flex;flex-direction:column;gap:12px;overscroll-behavior:contain;
  animation:sc-fade-in var(--sc-m-base) var(--sc-ease) both;
}
.sc-overview{min-width:0}
.sc-overview-lead{font-size:12px;line-height:1.65;color:var(--sc-text2);margin-top:-2px}
.sc-insp-header{display:flex;align-items:flex-start;gap:10px;padding:2px 0}
.sc-avatar{
  width:40px;height:40px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;color:var(--tone,var(--sc-feedback));
  background:color-mix(in srgb, var(--tone,var(--sc-feedback)) 16%, transparent);
  border:1px solid color-mix(in srgb, var(--tone,var(--sc-feedback)) 26%, transparent);
}
.sc-avatar-inner{display:flex}
.sc-insp-headtext{flex:1;min-width:0}
.sc-insp-title{font-size:var(--sc-fs-md);font-weight:650;line-height:1.45;color:var(--sc-text);overflow-wrap:anywhere}
.sc-insp-meta{margin-top:3px;font-family:var(--sc-mono);font-size:10.5px;line-height:1.55;color:var(--sc-text3);overflow-wrap:anywhere}
.sc-insights{display:flex;flex-direction:column;gap:9px}
.sc-insight{display:flex;align-items:flex-start;gap:8px}
.sc-insight-dot{width:7px;height:7px;border-radius:50%;margin-top:5px;flex-shrink:0;
  background:var(--dot,var(--sc-feedback));
  box-shadow:0 0 0 3px color-mix(in srgb, var(--dot,var(--sc-feedback)) 12%, transparent)}
.sc-insight-body{min-width:0}
.sc-insight-title{font-size:var(--sc-fs-xs);font-weight:600;line-height:1.5;color:var(--sc-text)}
.sc-insight-text{margin-top:2px;font-size:12px;line-height:1.66;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-insp-empty{padding:6px 0;font-size:12px;line-height:1.65;color:var(--sc-text2)}
.sc-overview-sep{height:1px;background:var(--sc-line);margin:2px 0 10px}
.sc-overview-legend{display:flex;flex-direction:column;gap:6px}
.sc-kicker{font-size:10.5px;font-weight:550;letter-spacing:.4px;color:var(--sc-text3)}
.sc-legend-row{display:flex;align-items:center;gap:7px;font-size:11.5px;color:var(--sc-text2)}
.sc-legend-row-label{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-legend-row-count{font-family:var(--sc-mono);font-size:10.5px;color:var(--sc-text3)}
.sc-footnote{margin-top:auto;padding-top:10px;border-top:1px solid var(--sc-line);
  font-size:10.5px;line-height:1.55;color:var(--sc-text3);overflow-wrap:anywhere}

/* 检查器分区 */
.sc-sec{border-top:1px solid var(--sc-line);padding-top:1px}
.sc-sec-toggle{
  appearance:none;border:0;background:transparent;width:100%;display:flex;align-items:center;gap:8px;
  padding:8px 0 7px;font:inherit;font-size:var(--sc-fs-sm);font-weight:600;color:var(--sc-text);
  cursor:pointer;text-align:left;
}
.sc-sec-toggle:hover{color:var(--sc-text)}
.sc-sec-title{flex:1;min-width:0}
.sc-sec-count{font-family:var(--sc-mono);font-size:10px;font-weight:400;color:var(--sc-text3)}
.sc-sec-chev{flex-shrink:0;color:var(--sc-text3);transition:color var(--sc-m-fast) var(--sc-ease)}
.sc-sec-toggle:hover .sc-sec-chev{color:var(--sc-text2)}
.sc-sec-body{padding:0 0 10px;animation:sc-fade-in var(--sc-m-fast) var(--sc-ease) both}
.sc-p{margin:0 0 8px;font-size:12px;line-height:1.72;color:var(--sc-text2);overflow-wrap:anywhere;white-space:pre-wrap}
.sc-p:last-child{margin-bottom:0}
.sc-kv{display:flex;flex-direction:column;gap:6px}
.sc-kv-row{display:grid;grid-template-columns:88px minmax(0,1fr);gap:8px;align-items:start}
.sc-kv-key{font-family:var(--sc-mono);font-size:10.5px;line-height:1.65;color:var(--sc-text3);overflow-wrap:anywhere}
.sc-kv-val{min-width:0;font-size:11.5px;line-height:1.65;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-kv-val.is-warn{color:var(--sc-warn)}
.sc-evidence{min-width:0}
.sc-evidence-label{display:flex;align-items:center;justify-content:space-between;gap:8px;
  font-size:10.5px;color:var(--sc-text3);margin-bottom:5px}
.sc-evidence-count{font-family:var(--sc-mono)}
.sc-evidence-inline{
  margin:0;padding:8px 10px;max-height:220px;overflow:auto;
  border:1px solid var(--sc-line);border-radius:8px;
  background:color-mix(in srgb, var(--sc-layer2) 45%, transparent);
  font-family:var(--sc-mono);font-size:10.5px;line-height:1.66;color:var(--sc-text2);
  overflow-wrap:anywhere;
}
.sc-inline-fold{
  appearance:none;border:0;background:transparent;padding:4px 0 0;
  font:inherit;font-size:10.5px;color:var(--sc-accent);cursor:pointer;
}
.sc-inline-fold:hover{opacity:.8}
.sc-files{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.sc-filerow{display:flex;align-items:flex-start;gap:6px;min-width:0}
.sc-file{flex:1;min-width:0;font-family:var(--sc-mono);font-size:10.5px;line-height:1.6;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-copy-btn{
  appearance:none;flex-shrink:0;border:1px solid var(--sc-line);border-radius:5px;background:transparent;
  padding:2px 6px;font:inherit;font-size:10px;line-height:1.4;color:var(--sc-text3);cursor:pointer;white-space:nowrap;
  transition:color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-copy-btn:hover{color:var(--sc-text);border-color:var(--sc-line-strong);background:color-mix(in srgb, var(--sc-text) 6%, transparent)}
.sc-missing{display:flex;align-items:flex-start;gap:6px;margin-top:8px;
  font-size:11px;line-height:1.6;color:var(--sc-warn);overflow-wrap:anywhere}
.sc-missing svg{flex-shrink:0;margin-top:2px}
.sc-chipgroups{display:flex;flex-direction:column;gap:9px}
.sc-chipgroup{min-width:0}
.sc-chipgroup-label{font-family:var(--sc-mono);font-size:10px;line-height:1.4;color:var(--sc-text3);margin-bottom:4px}
.sc-chipgroup-values{display:flex;flex-wrap:wrap;gap:5px}
.sc-value-chip{
  appearance:none;display:inline-flex;align-items:center;gap:5px;max-width:100%;
  padding:3px 7px;border:1px solid color-mix(in srgb, var(--tone,var(--sc-feedback)) 30%, transparent);
  border-radius:6px;background:color-mix(in srgb, var(--tone,var(--sc-feedback)) 9%, transparent);
  font-family:var(--sc-mono);font-size:10.5px;line-height:1.45;color:var(--sc-text);cursor:pointer;
  transition:background-color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease);
}
.sc-value-chip:hover{background:color-mix(in srgb, var(--tone,var(--sc-feedback)) 15%, transparent);
  border-color:color-mix(in srgb, var(--tone,var(--sc-feedback)) 46%, transparent)}
.sc-value-chip-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:230px}
.sc-value-chip-copied{font-family:var(--sc-font);font-size:10px;color:var(--tone,var(--sc-feedback))}
.sc-tools{display:flex;flex-direction:column;gap:5px}
.sc-tool{display:flex;align-items:flex-start;gap:7px}
.sc-tool-n{min-width:14px;padding-top:1px;text-align:right;font-family:var(--sc-mono);font-size:10px;color:var(--sc-text3)}
.sc-tool-text{flex:1;min-width:0;font-family:var(--sc-mono);font-size:10.5px;line-height:1.62;color:var(--sc-text2);overflow-wrap:anywhere}
.sc-insp-foot{display:flex;flex-wrap:wrap;gap:6px;margin-top:2px;padding-top:10px;border-top:1px solid var(--sc-line)}
.sc-insp-foot .sc-btn{flex:1;min-width:0;padding:0 8px;font-size:11px}
.sc-insp-foot .sc-locate{flex-basis:100%}

/* ── 骨架 / 加载 ──────────────────────────────────────────────────────── */
.sc-loading{height:100%;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.sc-skel{
  background:linear-gradient(90deg,
    color-mix(in srgb, var(--sc-text) 7%, transparent) 0%,
    color-mix(in srgb, var(--sc-text) 13%, transparent) 50%,
    color-mix(in srgb, var(--sc-text) 7%, transparent) 100%);
  background-size:200% 100%;animation:sc-shimmer 1.4s linear infinite;border-radius:8px;
}
.sc-skel-mark{width:26px;height:26px;border-radius:8px;flex-shrink:0}
.sc-skel-title{width:118px;height:18px}
.sc-skel-sub{width:148px;height:11px;margin-top:6px}
.sc-skel-chips{width:280px;height:26px;border-radius:var(--sc-r-pill);margin-left:auto}
.sc-skel-search{height:32px;margin:14px 14px 10px}
.sc-skel-card{height:92px;margin:0 12px 8px;flex-shrink:0}
.sc-skel-canvas{position:absolute;inset:16px;border-radius:var(--sc-r-lg)}
.sc-skel-line{height:12px;margin:14px 14px 0}
.sc-skel-line.is-wide{width:70%}
.sc-skel-line.is-short{width:45%}
.sc-skel-float{width:200px;height:84px;border-radius:var(--sc-r-lg)}
.sc-stage-loading-text{font-size:11px;letter-spacing:.3px}

/* ── 窄容器降级（容器查询，不监听 window 宽度）────────────────────────── */
@container (max-width:1080px){
  .sc-body{grid-template-columns:264px minmax(0,1fr)}
  .sc-inspector{
    position:absolute;left:12px;right:12px;bottom:12px;max-height:56%;z-index:12;display:none;
    border:1px solid var(--sc-line-strong);border-left-width:1px;border-radius:var(--sc-r-lg);
    background:color-mix(in srgb, var(--sc-layer1) 94%, transparent);
    -webkit-backdrop-filter:blur(18px) saturate(1.1);backdrop-filter:blur(18px) saturate(1.1);
    box-shadow:0 26px 74px -30px color-mix(in srgb, var(--sc-text) 55%, transparent);
  }
  .sc-root[data-inspector="open"] .sc-inspector{display:flex}
  .sc-inspector .sc-insp-close{display:flex}
  .sc-top-btn.sc-insp-toggle{display:inline-flex}
  .sc-insp-headbar{padding:10px 14px 6px}
  .sc-insp-body{padding:0 14px 12px}
}
@container (max-width:900px){
  .sc-body{grid-template-columns:56px minmax(0,1fr)}
  .sc-list{align-items:center;padding-top:10px}
  .sc-list-main{display:none}
  .sc-list-rail{
    display:flex;flex-direction:column;align-items:center;gap:7px;padding-bottom:12px;width:100%;
    flex:1;min-height:0;overflow-y:auto;scrollbar-width:none;
  }
  .sc-list-rail::-webkit-scrollbar{display:none}
  .sc-rail-btn{
    appearance:none;width:34px;height:34px;border:1px solid var(--sc-line);border-radius:9px;
    background:color-mix(in srgb, var(--sc-layer2) 55%, transparent);color:var(--sc-text2);
    display:flex;align-items:center;justify-content:center;cursor:pointer;
    transition:color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
  }
  .sc-rail-btn:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-layer2) 85%, transparent)}
  .sc-rail-dot{
    appearance:none;width:34px;height:30px;border:1px solid transparent;border-radius:9px;
    background:transparent;display:flex;align-items:center;justify-content:center;cursor:pointer;
    transition:background-color var(--sc-m-fast) var(--sc-ease),border-color var(--sc-m-fast) var(--sc-ease);
  }
  .sc-rail-dot:hover{background:color-mix(in srgb, var(--sc-layer2) 65%, transparent)}
  .sc-rail-dot.is-active{border-color:color-mix(in srgb, var(--sc-accent) 32%, transparent);background:color-mix(in srgb, var(--sc-layer2) 82%, transparent)}
  .sc-rail-dot .sc-status-dot{width:8px;height:8px}
  .sc-root[data-list="open"] .sc-list{position:absolute;left:0;top:0;bottom:0;width:272px;z-index:14;align-items:stretch;
    padding-top:0;background:color-mix(in srgb, var(--sc-layer1) 96%, transparent);
    -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
    box-shadow:0 26px 74px -30px color-mix(in srgb, var(--sc-text) 55%, transparent);border-right:1px solid var(--sc-line-strong)}
  .sc-root[data-list="open"] .sc-list-rail{display:none}
  .sc-root[data-list="open"] .sc-list-main{display:flex}
  .sc-root[data-list="open"] .sc-list-toggle{display:flex}
  .sc-skel-chips{width:180px}
}
@container (max-width:720px){
  .sc-header{padding:9px 12px 8px;column-gap:10px}
  .sc-title{font-size:17px}
  .sc-sub{display:none}
  .sc-chips .sc-chip-key{display:none}
  .sc-chips .sc-chip{padding:0 8px;max-width:150px}
  .sc-summary-text{-webkit-line-clamp:2}
  .sc-canvas-top{left:10px;top:10px;max-width:calc(100% - 20px);padding:8px 10px}
  .sc-canvas-summary{display:none}
  .sc-zoom{right:10px;bottom:132px}
  .sc-canvas-dock{padding:0 214px 10px 10px}
  .sc-replay{gap:7px;padding:6px 8px}
  .sc-replay-count{min-width:44px;font-size:10px}
  .sc-replay-tick-label{display:none}
  .sc-inspector{left:8px;right:8px;bottom:8px;max-height:62%}
  .sc-insp-foot .sc-btn{font-size:10.5px}
  .sc-empty-card{padding:18px}
}
@container (max-width:560px){
  .sc-chip:nth-child(n+3){display:none}
  .sc-summary-toggle{display:none}
  .sc-replay-count{display:none}
}

/* ── 画布底部停靠区：按画布尺寸降级（容器名 sc-canvas，尺寸取 .sc-canvas-wrap）── */
/* 一排要放下「图例 360 + 回放条」；画布 ≤1100 时横向装不下，改成两行（提示/图例在上、回放条贴底），
   回放条才能拿到足够宽的进度轨道。 */
@container sc-canvas (max-width:1100px){
  .sc-canvas-dock{grid-template-columns:minmax(0,1fr);gap:8px}
  .sc-dock-side{max-width:min(360px,100%)}
}
@container sc-canvas (max-width:620px){
  .sc-replay-speed{display:none}
}
/* 迷你地图在画布宽 <560 时不画（引擎 MINIMAP_MIN_W），右侧那 214px 留白可以收回。
   边界写 559 是保守取值：引擎按取整后的宽度判（Math.round），宁可多留白也不让回放条压到迷你地图。 */
@container sc-canvas (max-width:559px){
  .sc-canvas-dock{padding-right:10px}
}
/* 画布太矮时缩放钮会顶出画布上沿：宽画布 bottom 是 148px、窄画布 132px，取大的算 148 + 108 = 256。 */
@container sc-canvas (max-height:256px){
  .sc-zoom{display:none}
}


/* ── 结论卡 / 导出菜单 / 列表视图 / 快捷键提示 / 操作反馈 ─────────────── */
.sc-root{position:relative}
.sc-head-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
.sc-btn-icon{padding:0 9px}
.sc-btn-icon.is-on{color:var(--sc-text);border-color:var(--sc-line-strong);background:color-mix(in srgb, var(--sc-layer2) 82%, transparent)}
.sc-export{position:relative;display:flex}
.sc-export-menu{
  position:absolute;right:0;top:calc(100% + 8px);z-index:24;min-width:212px;padding:5px;
  display:flex;flex-direction:column;gap:2px;border-radius:10px;border:1px solid var(--sc-line);
  background:var(--sc-overlay);box-shadow:var(--sc-shadow-float);
  animation:sc-fade-in var(--sc-m-base) var(--sc-ease) both;
}
.sc-export-item{
  appearance:none;display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;
  border:0;border-radius:7px;background:transparent;color:var(--sc-text);font:inherit;font-size:12px;
  text-align:left;cursor:pointer;white-space:nowrap;
  transition:background-color var(--sc-m-fast) var(--sc-ease),color var(--sc-m-fast) var(--sc-ease);
}
.sc-export-item:hover{background:color-mix(in srgb, var(--sc-layer2) 82%, transparent)}
.sc-export-item:disabled{opacity:.45;cursor:default}
.sc-export-item svg{color:var(--sc-text2);flex-shrink:0}

.sc-conclusion{
  grid-area:conclusion;display:flex;align-items:center;gap:10px;min-width:0;margin-top:7px;
  padding:7px 10px 7px 0;border:1px solid color-mix(in srgb, var(--tone) 30%, var(--sc-line));
  border-radius:10px;background:color-mix(in srgb, var(--tone) 7%, var(--sc-surface));
  cursor:default;transition:border-color var(--sc-m-fast) var(--sc-ease),background-color var(--sc-m-fast) var(--sc-ease);
}
.sc-conclusion.is-clickable{cursor:pointer}
.sc-conclusion.is-clickable:hover{background:color-mix(in srgb, var(--tone) 12%, var(--sc-surface));border-color:color-mix(in srgb, var(--tone) 48%, var(--sc-line))}
.sc-conclusion.is-clickable:focus-visible{outline:2px solid color-mix(in srgb, var(--tone) 55%, transparent);outline-offset:2px}
.sc-conclusion.is-empty{opacity:.88}
.sc-conclusion-bar{width:3px;align-self:stretch;border-radius:0 3px 3px 0;background:var(--tone);flex-shrink:0}
.sc-conclusion-label{flex-shrink:0;font-size:10.5px;font-weight:650;letter-spacing:.3px;color:var(--tone);white-space:nowrap}
.sc-conclusion-main{flex:1;min-width:0;display:flex;align-items:baseline;gap:10px}
.sc-conclusion-title{flex-shrink:0;font-size:12.5px;font-weight:600;color:var(--sc-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46%}
.sc-conclusion-text{min-width:0;font-size:11.5px;color:var(--sc-text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-conclusion-badges{display:flex;align-items:center;gap:4px;flex-shrink:0}
.sc-conclusion-go{flex-shrink:0;font-size:11px;color:var(--tone);white-space:nowrap}
.sc-badge{
  display:inline-flex;align-items:center;height:18px;padding:0 7px;border-radius:999px;
  border:1px solid var(--sc-line);font-size:10.5px;line-height:1;color:var(--sc-text2);white-space:nowrap;
  background:color-mix(in srgb, var(--sc-layer1) 72%, transparent);
}
.sc-badge-hit{color:var(--sc-hit);border-color:color-mix(in srgb, var(--sc-hit) 34%, transparent);background:color-mix(in srgb, var(--sc-hit) 10%, transparent)}
.sc-badge-warn{color:var(--sc-warn);border-color:color-mix(in srgb, var(--sc-warn) 34%, transparent);background:color-mix(in srgb, var(--sc-warn) 10%, transparent)}
.sc-badge-book{color:var(--sc-book);border-color:color-mix(in srgb, var(--sc-book) 34%, transparent);background:color-mix(in srgb, var(--sc-book) 10%, transparent)}
.sc-badge-risk{color:var(--sc-risk);border-color:color-mix(in srgb, var(--sc-risk) 40%, transparent);background:color-mix(in srgb, var(--sc-risk) 11%, transparent)}
.sc-badge-neutral{color:var(--sc-text2)}

.sc-top-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
.sc-table-wrap{position:absolute;inset:0;z-index:7;display:flex;flex-direction:column;background:var(--sc-surface)}
.sc-table-head{flex-shrink:0;display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid var(--sc-line);background:linear-gradient(180deg,color-mix(in srgb,var(--sc-layer1) 70%,var(--sc-surface)),var(--sc-surface))}
.sc-table-title{font-size:13px;font-weight:650;flex-shrink:0}
.sc-table-meta{min-width:0;font-size:11.5px;color:var(--sc-text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-table-head .sc-btn{margin-left:auto;flex-shrink:0}
.sc-table-scroll{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain}
.sc-table{min-width:660px;display:flex;flex-direction:column}
.sc-tr{display:grid;grid-template-columns:54px 52px 104px minmax(220px,1fr) minmax(120px,220px);gap:12px;align-items:start;padding:8px 14px;border-bottom:1px solid var(--sc-line);font-size:12px}
.sc-thead{position:sticky;top:0;z-index:2;background:color-mix(in srgb, var(--sc-layer1) 94%, transparent);font-size:10.5px;color:var(--sc-text3);letter-spacing:.3px;padding-top:7px;padding-bottom:7px}
.sc-th{font-weight:600;white-space:nowrap}
.sc-trow{cursor:pointer;color:var(--sc-text);transition:background-color var(--sc-m-fast) var(--sc-ease)}
.sc-trow:hover{background:color-mix(in srgb, var(--sc-layer2) 62%, transparent)}
.sc-trow.is-active{background:color-mix(in srgb, var(--tone) 11%, var(--sc-surface));box-shadow:inset 3px 0 0 var(--tone)}
.sc-trow.is-conclusion .sc-td-title{font-weight:650}
.sc-trow:focus-visible{outline:2px solid color-mix(in srgb, var(--sc-accent) 55%, transparent);outline-offset:-2px}
.sc-td{min-width:0;color:var(--sc-text2)}
.sc-td-step{font-family:var(--sc-mono);font-size:11px;color:var(--sc-text3)}
.sc-td-role{font-size:11px}
.sc-td-action{font-size:11.5px;font-weight:550;color:var(--sc-text)}
.sc-td-title{font-size:12.5px;font-weight:600;color:var(--sc-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-td-sub{margin-top:2px;font-size:11px;color:var(--sc-text3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-td-marks{display:flex;flex-wrap:wrap;gap:4px}
.sc-mark{font-size:10.5px;padding:1px 6px;border-radius:999px;border:1px solid var(--sc-line);color:var(--sc-text2);white-space:nowrap;background:color-mix(in srgb, var(--sc-layer1) 65%, transparent)}

.sc-hint{
  display:flex;align-items:flex-start;gap:8px;max-width:100%;min-width:0;
  padding:6px 8px 6px 11px;border-radius:10px;border:1px solid var(--sc-line);
  background:color-mix(in srgb, var(--sc-layer1) 84%, transparent);
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
  font-size:11px;color:var(--sc-text2);animation:sc-fade-in var(--sc-m-slow) var(--sc-ease) both;
}
.sc-hint-text{
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;overflow-wrap:anywhere;line-height:1.5;
}
.sc-hint-close{appearance:none;border:0;background:transparent;color:var(--sc-text3);width:16px;height:16px;display:flex;align-items:center;justify-content:center;border-radius:50%;cursor:pointer;flex-shrink:0}
.sc-hint-close:hover{color:var(--sc-text);background:color-mix(in srgb, var(--sc-text) 10%, transparent)}

.sc-notice{
  position:absolute;left:50%;bottom:76px;z-index:40;max-width:min(560px,calc(100% - 32px));
  transform:translate(-50%,8px);padding:8px 14px;border-radius:999px;border:1px solid var(--sc-line);
  background:var(--sc-overlay);box-shadow:var(--sc-shadow-float);font-size:12px;color:var(--sc-text);
  opacity:0;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  transition:opacity var(--sc-m-base) var(--sc-ease),transform var(--sc-m-base) var(--sc-ease);
}
.sc-notice.is-on{opacity:1;transform:translate(-50%,0)}

@container (max-width:900px){
  .sc-head-actions .sc-btn-text{display:none}
  .sc-head-actions .sc-btn-icon{padding:0 8px}
  .sc-conclusion-text{display:none}
}
@container (max-width:720px){
  .sc-conclusion-badges{display:none}
}

/* ── 动效 ─────────────────────────────────────────────────────────────── */
@keyframes sc-fade-in{from{opacity:0}to{opacity:1}}
@keyframes sc-shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
@keyframes sc-spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}

@media (prefers-reduced-motion: reduce){
  .sc-root *,.sc-root *::before,.sc-root *::after{
    animation-duration:0ms !important;animation-iteration-count:1 !important;
    transition-duration:0ms !important;scroll-behavior:auto !important;
  }
  .sc-skel{animation:none;background:color-mix(in srgb, var(--sc-text) 9%, transparent)}
  .sc-insp-body,.sc-sec-body{animation:none}
}
`
