    // ── 样式 ────────────────────────────────────────────────────────────────
    const CSS = [
      '.scp-root,.scp-pal,.scp-tool-btn{--scp-surface:#ffffff;--scp-surface-2:#f6f7f9;--scp-surface-3:#eceff4;--scp-border:#e5e8ee;--scp-border-strong:#d7dce5;--scp-text:#1a1f29;--scp-muted:#647082;--scp-faint:#98a2b3;--scp-accent:#3b63e0;--scp-accent-soft:#eef2fe;--scp-accent-line:#c9d5fb;--scp-on-accent:#ffffff;--scp-ok:#0e8a5f;--scp-ok-soft:#e7f6ef;--scp-warn:#b25e09;--scp-warn-soft:#fdf2e4;--scp-bad:#c42b1c;--scp-bad-soft:#fdecea;--scp-idle:#647082;--scp-shadow:0 1px 2px rgba(16,24,40,.04),0 12px 30px -20px rgba(16,24,40,.22);--scp-fs-cap:10.5px;--scp-fs-meta:11px;--scp-fs-label:11.5px;--scp-fs-sm:12px;--scp-fs-body:12.5px;--scp-fs-row:13px;--scp-fs-title:15px;--scp-fw-regular:400;--scp-fw-medium:500;--scp-fw-semi:600;--scp-fw-bold:650;--scp-lh-tight:1.35;--scp-lh-base:1.55;--scp-lh-prose:1.75;--scp-sp-1:4px;--scp-sp-2:8px;--scp-sp-3:12px;--scp-sp-4:16px;--scp-sp-5:20px;--scp-sp-6:24px;}',
      'body[data-ds-dark-theme] .scp-root,body[data-ds-dark-theme] .scp-pal,body[data-ds-dark-theme] .scp-tool-btn,[data-theme="dark"] .scp-root,[data-theme="dark"] .scp-pal,[data-theme="dark"] .scp-tool-btn{--scp-surface:#1c1f26;--scp-surface-2:#242832;--scp-surface-3:#2e333e;--scp-border:#2e3441;--scp-border-strong:#3d4553;--scp-text:#eaedf3;--scp-muted:#a6afbd;--scp-faint:#7a8494;--scp-accent:#8aa5ff;--scp-accent-soft:rgba(138,165,255,.14);--scp-accent-line:rgba(138,165,255,.3);--scp-on-accent:#10131a;--scp-ok:#45d08a;--scp-ok-soft:rgba(69,208,138,.12);--scp-warn:#f5b34a;--scp-warn-soft:rgba(245,179,74,.12);--scp-bad:#f0796e;--scp-bad-soft:rgba(240,121,110,.12);--scp-idle:#6f7886;--scp-shadow:0 1px 2px rgba(0,0,0,.4),0 16px 36px -20px rgba(0,0,0,.7);}',
      '.scp-root{position:relative;container-type:inline-size;width:calc(100% - 2 * var(--dsh-composer-side-clearance, 0px));max-width:var(--dsh-composer-card-max-width, 100%);margin:0 auto;box-sizing:border-box;font-family:inherit;color:var(--scp-text);--scp-tone:var(--scp-accent);}',
      // 浮层改成向下展开时会盖到输入卡上；状态条是输入卡前面的兄弟节点，抬一层才点得到。
      '.scp-root[data-popover-down="true"]{z-index:9;}',
      '.scp-root *,.scp-pal *{box-sizing:border-box;}',
      '.scp-handle-wrap{display:flex;justify-content:center;width:100%;}',
      '.scp-handle{display:inline-flex;align-items:center;gap:7px;max-width:min(72%,560px);height:22px;padding:0 10px;border-radius:999px;border:1px solid var(--scp-border);background:color-mix(in srgb,var(--scp-surface) 62%,transparent);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);color:var(--scp-muted);font:inherit;font-size:var(--scp-fs-meta);line-height:1;cursor:pointer;transition:background-color 160ms ease,color 160ms ease,border-color 160ms ease,opacity 360ms ease;}',
      '.scp-handle .scp-ring,.scp-handle .scp-chevron{transition:opacity 360ms ease;}',
      '.scp-handle[data-idle="true"] .scp-ring,.scp-handle[data-idle="true"] .scp-chevron{opacity:.45;}',
      '.scp-handle[data-idle="true"]:hover .scp-ring,.scp-handle[data-idle="true"]:hover .scp-chevron,.scp-handle[data-idle="true"]:focus-visible .scp-ring,.scp-handle[data-idle="true"]:focus-visible .scp-chevron{opacity:1;}',
      '.scp-handle:hover{background:var(--scp-surface-2);color:var(--scp-text);border-color:var(--scp-border-strong);}',
      '.scp-handle .scp-ring{width:7px;height:7px;}',
      '.scp-handle-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:var(--scp-fw-medium);color:var(--scp-text);}',
      '.scp-handle-meta{flex:none;font-variant-numeric:tabular-nums;color:var(--scp-muted);}',
      '.scp-handle-pending{flex:none;color:var(--scp-warn);font-weight:var(--scp-fw-semi);}',
      '.scp-handle .scp-chevron{opacity:.65;}',
      '.scp-surface{display:flex;flex-direction:column;gap:6px;padding:6px 10px;border:1px solid var(--scp-border);border-radius:12px;background:color-mix(in srgb, var(--scp-surface) 76%, transparent);transition:border-color 180ms ease,background-color 180ms ease;}',
      '.scp-root[data-mode="bound"] .scp-surface,.scp-root[data-mode="recent"] .scp-surface{padding:7px 10px;}',
      '.scp-root[data-live="true"] .scp-surface{border-color:color-mix(in srgb, var(--scp-tone) 22%, var(--scp-border));}',
      '.scp-head{display:flex;align-items:center;gap:6px;min-width:0;}',
      '.scp-ring{flex:none;width:8px;height:8px;border-radius:50%;background:var(--scp-tone);}',
      '.scp-root[data-live="true"] .scp-ring{animation:scp-pulse 2.8s ease-out infinite;}',
      '@keyframes scp-pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb, var(--scp-tone) 30%, transparent)}70%{box-shadow:0 0 0 6px transparent}100%{box-shadow:0 0 0 0 transparent}}',
      '.scp-scope{flex:none;display:inline-flex;align-items:center;gap:1px;padding:1px 3px;border:none;border-radius:6px;background:transparent;font:inherit;font-size:var(--scp-fs-cap);line-height:1.6;color:var(--scp-muted);cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-scope:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-scope svg{opacity:.7;}',
      '.scp-case{flex:1 1 auto;min-width:0;padding:0;border:none;background:transparent;font:inherit;font-size:13px;font-weight:600;line-height:1.55;letter-spacing:.005em;text-align:left;color:var(--scp-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;border-radius:6px;}',
      '.scp-case:hover{color:var(--scp-accent);}',
      '.scp-spacer{flex:1 1 auto;min-width:6px;}',
      '.scp-step{flex:none;font-size:var(--scp-fs-cap);font-variant-numeric:tabular-nums;color:var(--scp-muted);}',
      '.scp-foot{display:flex;align-items:center;gap:8px;min-width:0;padding:0 2px;overflow:hidden;}',
      '.scp-track{flex:none;display:inline-flex;align-items:center;gap:2px;}',
      '.scp-tick{width:7px;height:3px;border-radius:2px;background:var(--scp-surface-3);transition:background-color 180ms ease;}',
      '.scp-tick[data-state="done"]{background:color-mix(in srgb, var(--scp-tone) 32%, transparent);}',
      '.scp-tick[data-state="now"]{background:var(--scp-tone);}',
      '.scp-now{font-size:var(--scp-fs-meta);line-height:1.6;color:var(--scp-muted);margin-left:2px;font-variant-numeric:tabular-nums;}',
      '.scp-meta{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:var(--scp-fs-meta);line-height:1.6;color:var(--scp-muted);white-space:nowrap;}',
      '.scp-wait{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--scp-fs-sm);line-height:1.6;color:var(--scp-text);}',
      '.scp-wait b{font-weight:var(--scp-fw-semi);color:var(--scp-text);}',
      '.scp-wait-tag{color:var(--scp-muted);font-weight:var(--scp-fw-medium);}',
      '.scp-chips{flex:none;display:inline-flex;align-items:center;gap:5px;}',
      '.scp-chip{flex:none;font-size:var(--scp-fs-meta);line-height:1.6;padding:0 5px;border-radius:5px;white-space:nowrap;color:var(--scp-muted);background:var(--scp-surface-2);}',
      '.scp-chip[data-tone="brand"]{color:color-mix(in srgb,var(--scp-accent) 66%,var(--scp-text));background:var(--scp-accent-soft);}',
      '.scp-chip[data-tone="warn"]{color:color-mix(in srgb,var(--scp-warn) 66%,var(--scp-text));background:var(--scp-warn-soft);}',
      '.scp-chip[data-tone="success"]{color:color-mix(in srgb,var(--scp-ok) 66%,var(--scp-text));background:var(--scp-ok-soft);}',
      '.scp-chip[data-tone="error"]{color:color-mix(in srgb,var(--scp-bad) 66%,var(--scp-text));background:var(--scp-bad-soft);}',
      '.scp-badge{flex:none;font-size:var(--scp-fs-cap);line-height:1.6;font-weight:var(--scp-fw-semi);padding:1px 7px;border-radius:5px;color:color-mix(in srgb,var(--scp-tone) 66%,var(--scp-text));background:color-mix(in srgb, var(--scp-tone) 9%, transparent);}',
      '.scp-btn{font:inherit;font-size:var(--scp-fs-body);line-height:1.7;padding:3px 10px;border-radius:8px;border:1px solid var(--scp-border);background:var(--scp-surface);color:var(--scp-text);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}',
      '.scp-btn:hover{background:var(--scp-surface-2);border-color:var(--scp-border-strong);}',
      '.scp-btn:disabled{opacity:.45;cursor:not-allowed;}',
      '.scp-btn--primary{border:none;border-radius:999px;padding:5px 14px;background:var(--scp-accent);color:var(--scp-on-accent);font-weight:var(--scp-fw-semi);}',
      '.scp-btn--primary:hover{background:color-mix(in srgb, var(--scp-accent) 88%, var(--scp-text));}',
      '.scp-btn--quiet{border:none;background:transparent;border-radius:999px;padding:3px 9px;color:var(--scp-accent);font-weight:var(--scp-fw-semi);}',
      '.scp-btn--quiet:hover{background:var(--scp-accent-soft);color:var(--scp-accent);}',
      '.scp-btn--ghost{background:transparent;border-color:transparent;}',
      '.scp-btn--ghost:hover{background:var(--scp-surface-2);}',
      '.scp-icon{flex:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;padding:0;border:none;border-radius:7px;background:transparent;color:var(--scp-muted);cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-icon:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-icon:focus-visible,.scp-collapse:focus-visible,.scp-btn:focus-visible,.scp-tool-btn:focus-visible,.scp-case:focus-visible,.scp-scope:focus-visible,.scp-dock-sed-open:focus-visible,.scp-pal-row:focus-visible,.scp-filter-item:focus-visible,.scp-picker-row:focus-visible{outline:2px solid var(--scp-accent);outline-offset:2px;}',
      '.scp-icon svg{display:block;}',
      '.scp-pin[data-on="true"]{background:var(--scp-accent-soft);color:var(--scp-accent);}',
      '.scp-collapse{flex:none;display:inline-flex;align-items:center;gap:2px;height:24px;padding:0 4px;border:none;border-radius:7px;background:transparent;color:var(--scp-muted);font:inherit;font-size:var(--scp-fs-meta);line-height:1;cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-collapse:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-collapse .scp-chevron{opacity:.7;}',
      '.scp-collapse-text{display:none;}',
      '.scp-chevron{transition:transform 180ms ease;}',
      '.scp-chevron[data-open="true"]{transform:rotate(180deg);}',
      '.scp-empty-note{font-size:var(--scp-fs-meta);line-height:1.6;color:var(--scp-muted);}',
      '.scp-pal-notice{margin:0 0 8px;padding:6px 9px;border-radius:8px;border:1px solid color-mix(in srgb, var(--scp-warn) 30%, var(--scp-border));background:var(--scp-warn-soft);color:var(--scp-text);font-size:var(--scp-fs-label);line-height:1.6;display:flex;align-items:center;gap:10px;}',
      '.scp-pal-notice-text{flex:1 1 auto;min-width:0;}',
      '.scp-pal-notice .scp-btn{flex:none;height:24px;padding:0 10px;font-size:var(--scp-fs-label);}',
      '.scp-pal-error{display:flex;align-items:center;gap:10px;padding:18px 22px;color:var(--scp-muted);font-size:var(--scp-fs-body);line-height:1.7;border-top:1px solid var(--scp-border);border-bottom:1px solid var(--scp-border);}',
      '.scp-pal-error-title{flex:0 1 auto;min-width:0;text-align:center;}',
      '.scp-pal-error--center{flex-direction:column;justify-content:center;gap:var(--scp-sp-3);border:0;padding:var(--scp-sp-6);}',
      '.scp-hint{padding:2px 4px 0;font-size:var(--scp-fs-meta);line-height:1.6;color:var(--scp-muted);}',
      '.scp-picker{position:absolute;left:8px;bottom:calc(100% + 8px);z-index:45;width:340px;max-height:min(52vh,380px);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--scp-border-strong);border-radius:12px;background:var(--scp-surface);box-shadow:var(--scp-shadow);animation:scp-pop 150ms ease-out;}',
      '.scp-picker-head{padding:9px 10px;border-bottom:1px solid var(--scp-border);}',
      '.scp-picker-title{font-size:var(--scp-fs-label);line-height:1.7;color:var(--scp-muted);padding:0 2px 6px;}',
      '.scp-picker-search{width:100%;font:inherit;font-size:var(--scp-fs-body);line-height:1.6;padding:5px 9px;border-radius:8px;border:1px solid var(--scp-border);background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-picker-search:focus{outline:2px solid var(--scp-accent);outline-offset:0;}',
      '.scp-picker-list{overflow:auto;padding:6px;}',
      '.scp-picker-row{display:flex;align-items:center;gap:8px;width:100%;padding:7px 8px;border:none;border-radius:8px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 100ms ease;}',
      '.scp-picker-row:hover{background:var(--scp-surface-2);}',
      '.scp-picker-row[data-on="true"]{background:var(--scp-accent-soft);}',
      '.scp-picker-current{flex:none;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);line-height:1;padding:2px 6px;border-radius:4px;color:var(--scp-accent);background:var(--scp-accent-soft);}',
      '.scp-picker-foot-note{flex:1 1 auto;min-width:0;font-size:var(--scp-fs-label);line-height:1.6;color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.scp-picker-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:1px;}',
      '.scp-picker-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--scp-fs-body);font-weight:var(--scp-fw-semi);line-height:1.5;}',
      '.scp-picker-meta{font-size:var(--scp-fs-meta);line-height:1.5;color:var(--scp-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.scp-picker-foot{display:flex;align-items:center;gap:8px;padding:8px 10px;border-top:1px solid var(--scp-border);}',
      '.scp-picker-empty{padding:18px 10px;text-align:center;font-size:var(--scp-fs-label);color:var(--scp-muted);}',
      '.scp-menu{position:absolute;right:8px;bottom:calc(100% + 8px);z-index:50;width:302px;max-height:min(64vh,540px);display:flex;flex-direction:column;overflow:hidden;padding:6px;border:1px solid var(--scp-border-strong);border-radius:12px;background:var(--scp-surface);box-shadow:var(--scp-shadow);animation:scp-pop 150ms ease-out;}',
      '.scp-menu-scroll{flex:1 1 auto;min-height:0;overflow:auto;}',
      '.scp-menu-scroll[data-overflow="true"]{-webkit-mask-image:linear-gradient(180deg,transparent,#000 8px,#000 calc(100% - 12px),transparent);mask-image:linear-gradient(180deg,transparent,#000 8px,#000 calc(100% - 12px),transparent);}',
      '@keyframes scp-pop{from{opacity:0;transform:translateY(6px) scale(.99)}to{opacity:1;transform:none}}',
      '.scp-menu-head{display:flex;align-items:center;justify-content:space-between;padding:2px 6px 6px;}',
      '.scp-menu-title{font-size:var(--scp-fs-meta);line-height:1.7;color:var(--scp-muted);}',
      '.scp-menu-group{margin:4px 0 2px;padding:7px 7px 0;font-size:var(--scp-fs-meta);line-height:1.6;letter-spacing:.05em;color:var(--scp-muted);border-top:1px solid var(--scp-border);}',
      '.scp-menu-group:first-of-type{border-top:none;}',
      '.scp-menu-item{display:flex;width:100%;align-items:center;gap:8px;padding:7px 9px;border:none;border-radius:7px;background:transparent;color:var(--scp-text);font:inherit;font-size:var(--scp-fs-body);line-height:1.6;text-align:left;cursor:pointer;transition:background-color 100ms ease;}',
      '.scp-menu-item:hover{background:var(--scp-surface-2);}',
      '.scp-menu-item:disabled{opacity:.45;cursor:not-allowed;}',
      '.scp-menu-item[data-danger="true"]{color:var(--scp-bad);}',
      '.scp-form{display:flex;flex-direction:column;gap:9px;padding:4px 8px 8px;}',
      '.scp-field{display:flex;flex-direction:column;gap:4px;}',
      '.scp-field-label{font-size:var(--scp-fs-label);line-height:1.6;color:var(--scp-muted);}',
      '.scp-input,.scp-select,.scp-textarea{font:inherit;font-size:var(--scp-fs-body);line-height:1.6;padding:5px 9px;border-radius:8px;border:1px solid var(--scp-border);background:var(--scp-surface-2);color:var(--scp-text);width:100%;}',
      '.scp-input:focus,.scp-select:focus,.scp-textarea:focus{outline:2px solid var(--scp-accent);outline-offset:0;}',
      '.scp-textarea{resize:vertical;min-height:96px;}',
      '.scp-form-actions{display:flex;justify-content:flex-end;gap:6px;margin-top:4px;}',
      '.scp-form-error{font-size:var(--scp-fs-label);line-height:1.6;color:var(--scp-bad);}',
      '.scp-form-hint{font-size:var(--scp-fs-meta);line-height:1.6;color:var(--scp-muted);}',
      '.scp-preview{display:flex;flex-direction:column;gap:4px;padding:9px 10px;border-radius:10px;background:var(--scp-surface-2);border:1px solid var(--scp-border);}',
      '.scp-preview-label{font-size:var(--scp-fs-cap);letter-spacing:.04em;color:var(--scp-muted);}',
      '.scp-preview-text{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-meta);line-height:1.7;color:var(--scp-text);white-space:pre-wrap;overflow-wrap:anywhere;max-height:132px;overflow:auto;}',
      '.scp-root[data-pending="true"] .scp-ring{background:var(--scp-warn);}',
      '.scp-root[data-flash="true"] .scp-ring{animation:scp-flash 1.4s ease-out;}',
      '@keyframes scp-flash{0%{box-shadow:0 0 0 0 color-mix(in srgb, var(--scp-tone) 45%, transparent)}55%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}',
      '.scp-pal-list,.scp-pal-side,.scp-menu-scroll,.scp-actions-menu,.scp-cmd-list,.scp-prompt,.scp-report,.scp-modal-body,.scp-picker-list{scrollbar-width:thin;scrollbar-color:var(--scp-border-strong) transparent;}',
      '.scp-pal-list::-webkit-scrollbar,.scp-pal-side::-webkit-scrollbar,.scp-menu-scroll::-webkit-scrollbar,.scp-actions-menu::-webkit-scrollbar,.scp-cmd-list::-webkit-scrollbar,.scp-prompt::-webkit-scrollbar,.scp-report::-webkit-scrollbar,.scp-modal-body::-webkit-scrollbar,.scp-picker-list::-webkit-scrollbar{width:10px;height:10px;}',
      '.scp-pal-list::-webkit-scrollbar-thumb,.scp-pal-side::-webkit-scrollbar-thumb,.scp-menu-scroll::-webkit-scrollbar-thumb,.scp-actions-menu::-webkit-scrollbar-thumb,.scp-cmd-list::-webkit-scrollbar-thumb,.scp-prompt::-webkit-scrollbar-thumb,.scp-report::-webkit-scrollbar-thumb,.scp-modal-body::-webkit-scrollbar-thumb,.scp-picker-list::-webkit-scrollbar-thumb{background:var(--scp-border-strong);border-radius:999px;border:3px solid transparent;background-clip:content-box;}',
      '.scp-pal-list::-webkit-scrollbar-track,.scp-pal-side::-webkit-scrollbar-track,.scp-menu-scroll::-webkit-scrollbar-track,.scp-actions-menu::-webkit-scrollbar-track,.scp-cmd-list::-webkit-scrollbar-track,.scp-prompt::-webkit-scrollbar-track,.scp-report::-webkit-scrollbar-track,.scp-modal-body::-webkit-scrollbar-track,.scp-picker-list::-webkit-scrollbar-track{background:transparent;}',
      '.scp-tool-btn{position:relative;display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;padding:0;border:none;border-radius:8px;background:transparent;color:var(--scp-muted);cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-tool-btn:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-tool-btn[data-tone="brand"]{color:var(--scp-accent);}',
      '.scp-tool-btn[data-tone="success"]{color:var(--scp-ok);}',
      '.scp-tool-btn[data-tone="warn"]{color:var(--scp-warn);}',
      '.scp-tool-btn[data-tone="error"]{color:var(--scp-bad);}',
      '.scp-tool-badge{position:absolute;top:-2px;right:-3px;min-width:14px;height:14px;padding:0 4px;border-radius:999px;background:var(--scp-warn);color:var(--scp-on-accent);font-size:var(--scp-fs-cap);line-height:14px;text-align:center;font-weight:var(--scp-fw-semi);}',
      '.scp-pal-backdrop{position:fixed;inset:0;z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:9vh 18px 18px;background:rgba(20,26,38,.26);-webkit-backdrop-filter:blur(8px) saturate(1.04);backdrop-filter:blur(8px) saturate(1.04);}',
      'body[data-ds-dark-theme] .scp-pal-backdrop,[data-theme="dark"] .scp-pal-backdrop{background:rgba(0,0,0,.5);}',
      `/* ── 诊断工作台：排版、布局与控件 ─────────────────────────────────────
   字号七档：--scp-fs-cap 10.5 / meta 11 / label 11.5 / sm 12 / body 12.5 / row 13 / title 15；
   字重四档 400 / 500 / 600 / 650。间距集中在 4 / 8 / 12 / 16 / 20 / 24；
   圆角按控件 / 卡片 / 浮层 / 窗口四档 8 / 10 / 12 / 16。
   状态条共用的 .scp-case 仍是固定值；.scp-menu-note 与其余控件一样从 token 取值；间距档未重新洗牌。 */
.scp-pal{position:relative;display:flex;flex-direction:column;width:min(960px,94vw);max-height:78vh;overflow:hidden;border:1px solid var(--scp-border-strong);border-radius:16px;background:var(--scp-surface);color:var(--scp-text);box-shadow:var(--scp-shadow);outline:none;animation:scp-pop 190ms cubic-bezier(.2,.9,.3,1);
  --scp-ctl-h:32px;--scp-ctl-h-sm:28px;--scp-ctl-h-input:34px;--scp-ctl-r:8px;--scp-side-pad-x:24px;}
.scp-pal-top{display:flex;align-items:center;gap:var(--scp-sp-3);padding:var(--scp-sp-4) var(--scp-sp-5);border-bottom:1px solid var(--scp-border);}
.scp-pal-heading{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px;}
.scp-pal-title{font-size:var(--scp-fs-title);font-weight:var(--scp-fw-bold);line-height:var(--scp-lh-tight);letter-spacing:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-pal-sub{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-base);color:var(--scp-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-views{display:flex;gap:2px;padding:3px;border-radius:10px;background:var(--scp-surface-2);flex:none;}
.scp-view-tab{display:inline-flex;align-items:center;gap:5px;height:var(--scp-ctl-h-sm);padding:0 12px;border:0;background:transparent;font:inherit;font-size:var(--scp-fs-sm);font-weight:var(--scp-fw-medium);line-height:1;border-radius:7px;color:var(--scp-muted);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,color 120ms ease;}
.scp-view-tab:hover{color:var(--scp-text);}
.scp-view-tab[data-on="true"]{background:var(--scp-surface);color:var(--scp-text);font-weight:var(--scp-fw-semi);box-shadow:0 1px 2px rgba(16,24,40,.08);}
body[data-ds-dark-theme] .scp-view-tab[data-on="true"],[data-theme="dark"] .scp-view-tab[data-on="true"]{box-shadow:0 1px 2px rgba(0,0,0,.5);}
.scp-view-tab b{font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);color:var(--scp-muted);font-variant-numeric:tabular-nums;}
.scp-view-tab[data-on="true"] b{color:var(--scp-accent);}
.scp-pal .scp-icon{width:28px;height:28px;border-radius:8px;}
.scp-pal-main{display:flex;min-height:0;flex:1 1 auto;}
.scp-pal-main--empty{display:flex;align-items:center;justify-content:center;}
.scp-pal-main--empty .scp-pal-empty{flex:0 1 auto;}
.scp-pal-list{flex:0 0 clamp(300px,40%,400px);max-width:400px;min-width:280px;overflow:auto;padding:var(--scp-sp-3);border-right:1px solid var(--scp-border);}
.scp-search{display:flex;align-items:center;gap:6px;margin:0 0 var(--scp-sp-2);padding:0 10px;height:var(--scp-ctl-h-input);border:1px solid var(--scp-border);border-radius:8px;background:var(--scp-surface);}
.scp-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--scp-text);font:inherit;font-size:var(--scp-fs-body);line-height:1.5;}
.scp-search input::placeholder{color:var(--scp-faint);}
.scp-search .scp-kbd{flex:none;}
.scp-filters{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 var(--scp-sp-2);padding:0 2px;}
.scp-filter-item{display:inline-flex;align-items:center;gap:5px;height:var(--scp-ctl-h-sm);padding:0 10px;border:1px solid transparent;border-radius:999px;background:var(--scp-surface-2);font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:1;color:var(--scp-muted);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}
.scp-filter-item:hover{background:var(--scp-surface-3);color:var(--scp-text);}
.scp-filter-item[data-on="true"]{background:var(--scp-accent-soft);border-color:var(--scp-accent-line);color:var(--scp-accent);font-weight:var(--scp-fw-semi);}
.scp-filter-item b{font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);color:var(--scp-muted);font-variant-numeric:tabular-nums;}
.scp-filter-item[data-on="true"] b{color:var(--scp-accent);}
.scp-pal-row{position:relative;display:flex;align-items:center;gap:10px;width:100%;padding:10px 12px;border:none;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 120ms ease;}
.scp-pal-row:hover{background:var(--scp-surface-2);}
.scp-pal-row::before{content:"";position:absolute;left:4px;top:50%;width:2px;height:18px;margin-top:-9px;border-radius:1px;background:transparent;pointer-events:none;}
.scp-pal-row[data-on="true"]{background:var(--scp-accent-soft);}
.scp-pal-row[data-on="true"]::before{background:var(--scp-accent);}
.scp-pal-row[data-pending="true"]::before{background:var(--scp-warn);}
.scp-pal-row[data-on="true"][data-pending="true"]::before{background:var(--scp-warn);}
.scp-pal-row .scp-ring{width:8px;height:8px;}
.scp-pal-row-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:4px;}
.scp-pal-row-line{display:flex;align-items:baseline;gap:8px;min-width:0;}
.scp-pal-row-meta-main{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-pal-row-meta-main .scp-chip{margin-left:6px;height:16px;padding:0 5px;font-size:var(--scp-fs-cap);}
.scp-pal-row-time{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
.scp-pal-row-title{flex:1 1 auto;min-width:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:break-word;font-size:var(--scp-fs-row);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);color:var(--scp-text);}
.scp-pal-row-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);white-space:nowrap;}
.scp-pal-row-step{flex:none;font-size:var(--scp-fs-meta);font-weight:var(--scp-fw-medium);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
.scp-pal-side{flex:1 1 auto;min-width:0;overflow:auto;padding:var(--scp-sp-5) var(--scp-side-pad-x) 0;display:flex;flex-direction:column;background:var(--scp-surface-2);}
.scp-pal-side>*:not(.scp-pal-empty){flex:none;}
.scp-pal-side>.scp-callout{margin-top:var(--scp-sp-3);}
.scp-pal .scp-badge{display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:6px;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-semi);line-height:1;color:color-mix(in srgb,var(--scp-tone) 66%,var(--scp-text));background:color-mix(in srgb,var(--scp-tone) 12%,transparent);}
.scp-pal .scp-chip{display:inline-flex;align-items:center;height:22px;padding:0 9px;border:1px solid var(--scp-border);border-radius:6px;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:1;white-space:nowrap;color:var(--scp-muted);background:var(--scp-surface);}
.scp-pal .scp-chip[data-tone="brand"]{color:color-mix(in srgb,var(--scp-accent) 66%,var(--scp-text));background:var(--scp-accent-soft);border-color:var(--scp-accent-line);}
.scp-pal .scp-chip[data-tone="warn"]{color:color-mix(in srgb,var(--scp-warn) 66%,var(--scp-text));background:var(--scp-warn-soft);border-color:color-mix(in srgb,var(--scp-warn) 26%,var(--scp-border));}
.scp-pal .scp-chip[data-tone="success"]{color:color-mix(in srgb,var(--scp-ok) 66%,var(--scp-text));background:var(--scp-ok-soft);border-color:color-mix(in srgb,var(--scp-ok) 26%,var(--scp-border));}
.scp-pal .scp-chip[data-tone="error"]{color:color-mix(in srgb,var(--scp-bad) 66%,var(--scp-text));background:var(--scp-bad-soft);border-color:color-mix(in srgb,var(--scp-bad) 26%,var(--scp-border));}
.scp-pal .scp-step{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
/* 诊断详情抬头（识别行）：一行状态与身份 + 问题背景（可展开）。
   真机 trace 的 summary 首句常见一两百到七八百字，当标题放大加粗会占掉详情的大半屏；这里把它降到
   正文层级，只让错误码、路径、函数调用走等宽字，靠字符宽度差异而不是字重区分。 */
.scp-identity{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-width:0;}
.scp-pal-titlecase{display:block;margin:0 0 var(--scp-sp-2);font-size:var(--scp-fs-row);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);color:var(--scp-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-identity .scp-badge,.scp-identity .scp-chip{height:20px;padding:0 8px;border-radius:5px;font-size:var(--scp-fs-meta);line-height:1;}
.scp-identity-meta{margin-left:auto;flex:none;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);font-variant-numeric:tabular-nums;color:var(--scp-muted);white-space:nowrap;}
.scp-lede{margin:var(--scp-sp-3) 0 0;font-size:var(--scp-fs-row);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:break-word;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}
.scp-lede[data-open="true"]{display:block;}
.scp-icode{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:inherit;line-height:inherit;padding:1px 4px;border-radius:4px;background:var(--scp-surface-3);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-more{display:inline-flex;align-items:center;gap:4px;margin-top:var(--scp-sp-1);padding:0;border:0;background:transparent;font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-accent);cursor:pointer;}
.scp-more:hover{text-decoration:underline;text-underline-offset:2px;}
.scp-missing-lead{display:flex;align-items:baseline;gap:var(--scp-sp-2);}
.scp-missing-tag{flex:none;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);color:var(--scp-accent);}
.scp-missing-text{flex:1 1 auto;min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:break-word;}
.scp-callout{display:flex;flex-direction:column;gap:var(--scp-sp-1);padding:var(--scp-sp-3) var(--scp-sp-4);border-radius:10px;background:var(--scp-accent-soft);border:1px solid var(--scp-accent-line);}
.scp-callout-label{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);letter-spacing:0;color:var(--scp-accent);}
.scp-callout-text{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-section-label{margin:var(--scp-sp-5) 0 var(--scp-sp-2);font-size:var(--scp-fs-sm);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-tight);letter-spacing:.02em;color:var(--scp-muted);}
.scp-check,.scp-upstream,.scp-list-block,.scp-history{display:flex;flex-direction:column;gap:var(--scp-sp-2);padding:var(--scp-sp-3) var(--scp-sp-4);border-radius:10px;background:var(--scp-surface);border:1px solid color-mix(in srgb,var(--scp-border) 72%,transparent);}
.scp-list-block>.scp-section-label:first-child{margin-top:0;}
.scp-check-item{display:flex;align-items:center;gap:10px;min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);}
.scp-check-dot{flex:none;display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;border:1.5px solid var(--scp-border-strong);color:var(--scp-on-accent);font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);line-height:1;}
.scp-check-item[data-done="true"] .scp-check-dot{background:var(--scp-ok-soft);border-color:color-mix(in srgb,var(--scp-ok) 40%,var(--scp-border-strong));color:var(--scp-ok);}
.scp-check-item[data-done="true"] .scp-check-label{color:var(--scp-muted);font-weight:var(--scp-fw-regular);}
.scp-check-item[data-optional="true"] .scp-check-dot{border-style:dashed;}
.scp-check-item[data-na="true"] .scp-check-dot{opacity:.4;}
.scp-check-item[data-na="true"] .scp-check-label{color:var(--scp-muted);}
.scp-check-label{flex:none;font-weight:var(--scp-fw-medium);color:var(--scp-text);}
.scp-check-state{flex:none;font-size:var(--scp-fs-label);color:var(--scp-muted);}
.scp-check-item .scp-spacer{flex:1 1 auto;}
.scp-check-action{display:inline-flex;align-items:center;justify-content:center;flex:none;height:var(--scp-ctl-h-sm);padding:0 10px;border:1px solid var(--scp-border);border-radius:7px;background:var(--scp-surface);font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:1;color:var(--scp-text);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}
.scp-check-action:hover{background:var(--scp-surface-2);border-color:var(--scp-border-strong);color:var(--scp-text);}
.scp-check-action:disabled{opacity:.45;cursor:not-allowed;}
.scp-upstream-row{display:flex;align-items:center;gap:var(--scp-sp-2);flex-wrap:wrap;min-width:0;}
.scp-list-block>.scp-check-action,.scp-check>.scp-check-action,.scp-history>.scp-check-action{align-self:flex-start;}
.scp-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-muted);overflow-wrap:anywhere;}
.scp-material-row{display:flex;align-items:flex-start;gap:8px;font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);}
.scp-material-row::before{content:"·";flex:none;color:var(--scp-accent);font-weight:var(--scp-fw-bold);}
.scp-evidence-row,.scp-candidate{display:flex;align-items:center;gap:8px;min-width:0;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);}
.scp-evidence-path{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);color:var(--scp-muted);}
.scp-candidate-text{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--scp-text);}
.scp-report{margin:0;max-height:260px;overflow:auto;padding:var(--scp-sp-3) var(--scp-sp-4);border-radius:10px;background:var(--scp-surface-2);border:1px solid var(--scp-border);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);white-space:pre-wrap;overflow-wrap:anywhere;color:var(--scp-text);}
.scp-grid2{display:grid;grid-template-columns:1fr 1fr;gap:var(--scp-sp-3) var(--scp-sp-5);margin:0;padding:var(--scp-sp-4);border-radius:10px;background:var(--scp-surface);border:1px solid color-mix(in srgb,var(--scp-border) 72%,transparent);}
.scp-def{display:flex;flex-direction:column;gap:2px;min-width:0;}
.scp-def dt{margin:0;font-size:var(--scp-fs-meta);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-def dd{margin:0;font-size:var(--scp-fs-body);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-base);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-tl-row{display:grid;grid-template-columns:56px 1fr;gap:2px 12px;padding:var(--scp-sp-2) 0;border-top:1px solid var(--scp-border);}
.scp-tl-row:first-of-type{border-top:0;}
.scp-tl-step{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
.scp-tl-body{min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);}
.scp-tl-meta{font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-tl-reason{margin-top:2px;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-muted);}
/* 段头一行：标题 + 右侧计数 / 提示（现场条数、日志条数、上游条数）。 */
.scp-section-row{display:flex;align-items:baseline;gap:8px;margin:var(--scp-sp-5) 0 var(--scp-sp-2);min-width:0;}
.scp-section-row .scp-section-label{margin:0;}
.scp-section-note{margin-left:auto;flex:none;max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-faint);}
/* 现场故障时间线：时间两行（日期 / 时刻）+ 竖轨圆点 + 事实与来源片。 */
.scp-it{display:flex;flex-direction:column;padding:var(--scp-sp-1) var(--scp-sp-4);border-radius:10px;background:var(--scp-surface);border:1px solid color-mix(in srgb,var(--scp-border) 72%,transparent);}
.scp-it-env{padding:2px 2px 0;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-it-row{display:grid;grid-template-columns:86px 12px 1fr;column-gap:12px;padding:9px 0;min-width:0;}
.scp-it-time{display:flex;flex-direction:column;gap:1px;padding-top:1px;line-height:1.35;font-variant-numeric:tabular-nums;white-space:nowrap;}
.scp-it-date{font-size:var(--scp-fs-cap);letter-spacing:.02em;color:var(--scp-faint);}
.scp-it-hm{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-medium);color:var(--scp-text);}
.scp-it-hm[data-missing="true"]{font-size:var(--scp-fs-meta);font-weight:var(--scp-fw-regular);color:var(--scp-faint);}
.scp-it-unknown{font-size:var(--scp-fs-meta);color:var(--scp-faint);padding-top:2px;}
.scp-it-rail{position:relative;min-height:100%;}
.scp-it-dot{position:absolute;left:3px;top:6px;width:6px;height:6px;border-radius:50%;background:var(--scp-accent);box-shadow:0 0 0 3px var(--scp-surface);}
.scp-it-row[data-time="unknown"] .scp-it-dot{background:var(--scp-surface);border:1px solid var(--scp-border-strong);}
.scp-it-row:not(:last-child) .scp-it-rail::after{content:"";position:absolute;left:5px;top:16px;bottom:-18px;width:1px;background:color-mix(in srgb,var(--scp-border-strong) 82%,transparent);}
.scp-it-body{min-width:0;}
.scp-it-text{font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-it-meta{margin-top:3px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-it-src{display:inline-flex;align-items:center;height:18px;padding:0 6px;border-radius:5px;font-size:var(--scp-fs-cap);line-height:1;color:var(--scp-muted);background:var(--scp-surface-2);}
.scp-it-note{font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);color:var(--scp-muted);}
.scp-it-foot{margin:2px 0 0;padding:0 2px;font-size:var(--scp-fs-cap);line-height:var(--scp-lh-base);color:var(--scp-faint);}
/* 故障过程（日志）：默认收起；时钟偏差用 warn，节点 quote 与文件:行走等宽。 */
.scp-lp-clock{margin:0 0 2px;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-warn);}
.scp-lp-list{display:flex;flex-direction:column;padding-left:12px;border-left:1px solid color-mix(in srgb,var(--scp-border-strong) 60%,transparent);}
.scp-lp-row{display:grid;grid-template-columns:64px 1fr;column-gap:10px;padding:6px 0;min-width:0;}
.scp-lp-time{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);color:var(--scp-muted);white-space:nowrap;}
.scp-lp-body{min-width:0;}
.scp-lp-what{font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-lp-quote{margin-top:2px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-cap);line-height:1.6;color:var(--scp-faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-lp-meta{margin-top:2px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:var(--scp-fs-cap);line-height:1.6;color:var(--scp-muted);}
/* 上游与查证的时间线：>3 条折叠时保留前三条，展开不换段。 */
.scp-up-list{display:flex;flex-direction:column;gap:3px;padding-top:6px;border-top:1px solid var(--scp-border);}
.scp-up-row{display:grid;grid-template-columns:128px 1fr;column-gap:12px;min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);}
.scp-up-when{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);color:var(--scp-muted);white-space:nowrap;}
.scp-up-what{min-width:0;color:var(--scp-text);overflow-wrap:anywhere;}
.scp-up-note{font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);color:var(--scp-muted);}
.scp-history-row{display:flex;align-items:baseline;gap:8px;min-width:0;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);}
.scp-history-when{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
.scp-history-kind{flex:none;font-size:var(--scp-fs-cap);line-height:1.6;padding:1px 7px;border-radius:5px;background:var(--scp-surface-2);color:var(--scp-muted);font-weight:var(--scp-fw-medium);}
.scp-history-text{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--scp-text);}
.scp-history-note{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--scp-muted);}
.scp-actions{position:sticky;bottom:0;display:flex;flex-wrap:wrap;align-items:center;gap:var(--scp-sp-2);margin:var(--scp-sp-5) calc(-1 * var(--scp-side-pad-x)) 0;padding:var(--scp-sp-3) var(--scp-side-pad-x) var(--scp-sp-4);border-top:1px solid var(--scp-border);background:var(--scp-surface-2);box-shadow:0 -8px 16px -12px color-mix(in srgb,var(--scp-text) 24%,transparent);}
.scp-actions::before,.scp-sed-actions::before{content:"";position:absolute;left:0;right:0;top:-20px;height:20px;background:linear-gradient(to top,var(--scp-surface-2),transparent);pointer-events:none;}
.scp-actions-menu{position:absolute;right:calc(var(--scp-side-pad-x) + 4px);bottom:100px;z-index:7;width:min(340px,calc(100% - 32px));max-height:min(58vh,520px);display:flex;flex-direction:column;overflow:auto;padding:6px;border:1px solid var(--scp-border-strong);border-radius:12px;background:var(--scp-surface);box-shadow:var(--scp-shadow);outline:none;}
.scp-actions-menu .scp-menu-scroll{flex:1 1 auto;min-height:0;overflow:auto;}
.scp-cmd-group{padding:6px 10px 2px;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);letter-spacing:.04em;color:var(--scp-muted);}
.scp-pal .scp-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:var(--scp-ctl-h);padding:0 14px;border:1px solid var(--scp-border);border-radius:var(--scp-ctl-r);background:var(--scp-surface);color:var(--scp-text);font:inherit;font-size:var(--scp-fs-sm);font-weight:var(--scp-fw-medium);line-height:1;white-space:nowrap;cursor:pointer;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}
.scp-pal .scp-btn:hover{background:var(--scp-surface-2);border-color:var(--scp-border-strong);}
.scp-pal .scp-btn:disabled{opacity:.45;cursor:not-allowed;}
.scp-pal .scp-btn--primary{border-color:transparent;background:var(--scp-accent);color:var(--scp-on-accent);font-weight:var(--scp-fw-semi);}
.scp-pal .scp-btn--primary:hover{background:color-mix(in srgb,var(--scp-accent) 88%,var(--scp-text));border-color:transparent;}
.scp-pal .scp-btn--ghost{border-color:transparent;background:transparent;color:var(--scp-muted);}
.scp-pal .scp-btn--ghost:hover{background:var(--scp-surface-2);color:var(--scp-text);}
.scp-pal .scp-btn--quiet{border-color:transparent;background:transparent;color:var(--scp-accent);font-weight:var(--scp-fw-semi);padding:0 10px;}
.scp-pal .scp-btn--quiet:hover{background:var(--scp-accent-soft);color:var(--scp-accent);}
.scp-pal .scp-cmd-backdrop{position:absolute;inset:0;z-index:9;display:flex;justify-content:center;align-items:flex-start;padding-top:11vh;background:color-mix(in srgb,var(--scp-text) 12%,transparent);}
.scp-pal .scp-cmd{width:min(520px,calc(100% - 32px));max-height:58vh;display:flex;flex-direction:column;border:1px solid var(--scp-border-strong);border-radius:12px;background:var(--scp-surface);box-shadow:var(--scp-shadow);overflow:hidden;}
.scp-pal .scp-cmd:focus-within{border-color:var(--scp-accent);box-shadow:0 0 0 2px var(--scp-accent);}
.scp-pal .scp-cmd input{border:0;border-bottom:1px solid var(--scp-border);outline:none;padding:var(--scp-sp-3) var(--scp-sp-4);font:inherit;font-size:var(--scp-fs-row);background:transparent;color:var(--scp-text);}
.scp-pal .scp-cmd-where{padding:var(--scp-sp-2) var(--scp-sp-4) 0;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-pal[data-cmd="true"]>.scp-pal-foot{visibility:hidden;}
.scp-pal .scp-cmd-list{overflow:auto;padding:6px;}
.scp-pal .scp-cmd-item{display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;border:0;border-radius:var(--scp-ctl-r);background:transparent;color:var(--scp-text);font:inherit;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);text-align:left;cursor:pointer;}
.scp-pal .scp-cmd-item[data-on="true"]{background:var(--scp-accent-soft);color:var(--scp-accent);}
.scp-pal .scp-cmd-empty{padding:var(--scp-sp-3);font-size:var(--scp-fs-body);color:var(--scp-muted);}
.scp-pal .scp-input,.scp-pal .scp-select,.scp-pal .scp-textarea{font:inherit;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);padding:6px 10px;border-radius:var(--scp-ctl-r);border:1px solid var(--scp-border);background:var(--scp-surface-2);color:var(--scp-text);}
.scp-pal .scp-field-label{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-pal .scp-form-hint,.scp-pal .scp-form-error{font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);}
.scp-pal .scp-preview{display:flex;flex-direction:column;gap:var(--scp-sp-1);padding:var(--scp-sp-3);border-radius:var(--scp-ctl-r);background:var(--scp-surface-2);border:1px solid var(--scp-border);}
.scp-pal .scp-preview-label{font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);letter-spacing:.02em;color:var(--scp-muted);}
.scp-pal .scp-preview-text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);}
.scp-search:focus-within{border-color:var(--scp-accent);box-shadow:0 0 0 2px var(--scp-accent);}
.scp-link{border:0;background:transparent;padding:0;font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-accent);cursor:pointer;text-align:left;overflow-wrap:anywhere;}
.scp-link:hover{text-decoration:underline;}
.scp-pal-foot{display:flex;align-items:center;gap:var(--scp-sp-3);min-width:0;padding:10px var(--scp-sp-5);border-top:1px solid var(--scp-border);font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);background:var(--scp-surface);}
.scp-kbd{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 4px;border-radius:5px;border:1px solid var(--scp-border);background:var(--scp-surface-2);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-medium);color:var(--scp-muted);}
.scp-version{font-size:var(--scp-fs-cap);color:var(--scp-faint);font-variant-numeric:tabular-nums;}
.scp-pal-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--scp-sp-2);flex:1 1 auto;min-height:200px;padding:var(--scp-sp-6);color:var(--scp-muted);font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);text-align:center;}
.scp-menu-note{margin-left:auto;max-width:52%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--scp-fs-cap);line-height:1.6;color:var(--scp-warn);}
.scp-sr-only{position:absolute!important;width:1px!important;height:1px!important;margin:-1px!important;padding:0!important;border:0!important;overflow:hidden!important;clip-path:inset(50%)!important;white-space:nowrap!important;}
.scp-toast{position:absolute;left:50%;bottom:52px;transform:translateX(-50%);max-width:min(80%,520px);padding:7px 14px;border-radius:var(--scp-r-pill,999px);background:var(--scp-surface);border:1px solid var(--scp-border-strong);box-shadow:var(--scp-shadow);font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-text);white-space:normal;text-align:center;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;animation:scp-toast 170ms ease-out;}
@keyframes scp-toast{from{opacity:0;transform:translate(-50%,6px)}to{opacity:1;transform:translate(-50%,0)}}
.scp-skel{height:12px;border-radius:6px;background:linear-gradient(90deg,var(--scp-surface-2),color-mix(in srgb, var(--scp-surface-2) 30%, transparent),var(--scp-surface-2));background-size:200% 100%;animation:scp-shimmer 1.5s ease-in-out infinite;}
@keyframes scp-shimmer{from{background-position:120% 0}to{background-position:-80% 0}}
.scp-root[data-tone="brand"]{--scp-tone:var(--scp-accent);}
.scp-root[data-tone="success"]{--scp-tone:var(--scp-ok);}
.scp-root[data-tone="warn"]{--scp-tone:var(--scp-warn);}
.scp-root[data-tone="error"]{--scp-tone:var(--scp-bad);}
.scp-root[data-tone="idle"]{--scp-tone:var(--scp-idle);}
/* 按下反馈：主按钮与安静按钮保持自己的底色，其余按钮 / 行在按住时压暗一档。 */
.scp-btn:not(.scp-btn--primary):not(.scp-btn--quiet):not(.scp-btn--ghost):active{background:var(--scp-surface-3);border-color:var(--scp-border-strong);}
.scp-icon:active,.scp-collapse:active,.scp-scope:active,.scp-tool-btn:active,.scp-dock-sed-open:active,.scp-filter-item:active,.scp-view-tab:active{background:var(--scp-surface-3);}
.scp-pal-row:active,.scp-sed-row:active,.scp-menu-item:active:not(:disabled),.scp-picker-row:active,.scp-batch-item:active:not(:disabled){background:var(--scp-surface-3);}
.scp-pal button:focus-visible,.scp-view-tab:focus-visible,.scp-check-action:focus-visible,.scp-sed-row:focus-visible,.scp-cmd-item:focus-visible,.scp-pick:focus-visible,.scp-details-toggle:focus-visible,.scp-link:focus-visible{outline:2px solid var(--scp-accent);outline-offset:2px;}
.scp-pal ::selection{background:var(--scp-accent-line);}
@container (max-width: 720px){.scp-meta{display:none;}.scp-chips{flex-wrap:nowrap;}.scp-collapse-text{display:none;}}
@media (max-width: 900px){
  .scp-pal{--scp-side-pad-x:16px;}
  .scp-pal-main{flex-direction:column;}
  .scp-pal-list{flex:0 0 auto;max-width:none;min-width:0;max-height:38vh;border-right:none;border-bottom:1px solid var(--scp-border);}
  .scp-pal-side{flex:1 1 auto;min-height:0;padding-top:var(--scp-sp-4);}
  .scp-grid2{grid-template-columns:1fr;}
  .scp-pal-top{flex-wrap:wrap;gap:var(--scp-sp-2);}
  .scp-foot-hints{display:none;}
  .scp-pal-foot{gap:var(--scp-sp-2);}
  .scp-pal-foot .scp-foot-note{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
}
@media (max-width: 520px){.scp-pal-backdrop{padding:4vh 10px 10px;}.scp-pal{max-height:88vh;}.scp-picker{width:min(330px,calc(100vw - 32px));}}
`,
      `/* ── 沉淀队列（v1）──────────────────────────────────────────────── */
.scp-batch{display:flex;align-items:center;gap:var(--scp-sp-2);flex-wrap:wrap;padding:10px var(--scp-sp-5);border-bottom:1px solid var(--scp-border);background:var(--scp-surface);flex:none;min-width:0;}
.scp-batch-strong{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);white-space:nowrap;}
.scp-batch-chip{display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:5px;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);line-height:1;white-space:nowrap;}
.scp-batch-chip[data-tone="warn"]{background:var(--scp-warn-soft);color:color-mix(in srgb,var(--scp-warn) 66%,var(--scp-text));}
.scp-batch-chip[data-tone="accent"]{background:var(--scp-accent-soft);color:color-mix(in srgb,var(--scp-accent) 66%,var(--scp-text));}
.scp-batch-chip[data-tone="ok"]{background:var(--scp-ok-soft);color:color-mix(in srgb,var(--scp-ok) 66%,var(--scp-text));}
.scp-batch-chip[data-tone="bad"]{background:var(--scp-bad-soft);color:color-mix(in srgb,var(--scp-bad) 66%,var(--scp-text));}
.scp-batch-chip[data-tone="gray"]{background:var(--scp-surface-3);color:var(--scp-muted);}
.scp-batch-age{font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);white-space:nowrap;}
.scp-batch-age[data-over="true"]{color:var(--scp-bad);font-weight:var(--scp-fw-semi);}
.scp-sed-side{gap:0;padding:var(--scp-sp-5) var(--scp-side-pad-x) 0;}
.scp-sed-side>.scp-callout{margin-top:var(--scp-sp-3);}
.scp-sed-side>.scp-list-block{margin-top:var(--scp-sp-3);}
.scp-sed-side>.scp-sed-hint{margin-top:6px;}
.scp-sed-side>.scp-list-block>.scp-section-label{margin:0 0 var(--scp-sp-2);}
.scp-sed-group{display:flex;align-items:center;justify-content:space-between;padding:var(--scp-sp-3) 8px 6px;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);letter-spacing:.02em;color:var(--scp-muted);}
.scp-sed-row{position:relative;display:flex;gap:10px;width:100%;padding:10px 10px 10px 14px;border:0;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 120ms ease;}
.scp-sed-row:hover{background:var(--scp-surface-2);}
.scp-sed-row[data-on="true"]{background:var(--scp-accent-soft);}
.scp-sed-row::before{content:"";position:absolute;left:4px;top:50%;width:2px;height:18px;margin-top:-9px;border-radius:1px;background:transparent;pointer-events:none;}
.scp-sed-row[data-on="true"]::before{background:var(--scp-accent);}
.scp-sed-dot{width:6px;height:6px;border-radius:50%;margin-top:7px;flex:none;}
.scp-sed-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:3px;}
.scp-sed-line{display:flex;align-items:baseline;gap:8px;min-width:0;}
.scp-sed-title{flex:1 1 auto;min-width:0;font-size:var(--scp-fs-row);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-sed-age{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
.scp-sed-age[data-over="true"]{color:var(--scp-bad);font-weight:var(--scp-fw-semi);}
.scp-sed-meta{display:flex;align-items:center;gap:6px;min-width:0;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-sed-meta .scp-chip{height:20px;padding:0 7px;font-size:var(--scp-fs-cap);}
.scp-stepper{display:flex;padding:2px 0;}
.scp-sed-step{flex:1;position:relative;display:flex;flex-direction:column;align-items:center;gap:6px;min-width:0;}
.scp-sed-step:not(:last-child)::after{content:"";position:absolute;top:8px;left:50%;width:100%;height:2px;background:var(--scp-border);z-index:0;}
.scp-sed-step[data-state="done"]:not(:last-child)::after,.scp-sed-step[data-state="current"]:not(:last-child)::after{background:var(--scp-accent-line);}
.scp-sed-step-dot{width:16px;height:16px;border-radius:50%;border:2px solid var(--scp-border-strong);background:var(--scp-surface);z-index:1;display:flex;align-items:center;justify-content:center;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);color:transparent;}
.scp-sed-step[data-state="done"] .scp-sed-step-dot{background:var(--scp-ok);border-color:var(--scp-ok);color:var(--scp-on-accent);}
.scp-sed-step[data-state="current"] .scp-sed-step-dot{border-color:var(--scp-accent);background:var(--scp-accent-soft);box-shadow:0 0 0 3px var(--scp-accent-soft);}
.scp-sed-step[data-state="blocked"] .scp-sed-step-dot{border-color:var(--scp-bad);background:var(--scp-bad-soft);}
.scp-sed-step[data-state="unknown"] .scp-sed-step-dot{border-style:dashed;border-color:var(--scp-border-strong);background:var(--scp-surface-2);}
.scp-sed-step-label{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-tight);color:var(--scp-muted);text-align:center;white-space:nowrap;}
.scp-sed-step[data-state="done"] .scp-sed-step-label,.scp-sed-step[data-state="current"] .scp-sed-step-label{color:var(--scp-text);}
.scp-sed-step[data-state="current"] .scp-sed-step-label{font-weight:var(--scp-fw-semi);}
.scp-sed-step-note{font-size:var(--scp-fs-cap);line-height:var(--scp-lh-tight);color:var(--scp-muted);text-align:center;white-space:nowrap;}
.scp-sed-step-note[data-bad="true"]{color:var(--scp-bad);}
.scp-target-row{display:flex;align-items:center;gap:var(--scp-sp-2);padding:var(--scp-sp-2) var(--scp-sp-3);border:1px solid var(--scp-border);border-radius:10px;background:var(--scp-surface-2);font-size:var(--scp-fs-label);min-width:0;}
.scp-target-label{color:var(--scp-muted);flex:none;}
.scp-target-pill{display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 9px;border-radius:6px;background:var(--scp-surface);border:1px solid var(--scp-border-strong);font-weight:var(--scp-fw-semi);font-size:var(--scp-fs-label);color:var(--scp-text);white-space:nowrap;}
.scp-target-hint{color:var(--scp-muted);font-size:var(--scp-fs-meta);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-veil{position:absolute;inset:0;z-index:70;display:flex;align-items:center;justify-content:center;background:rgba(20,26,38,.38);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);}
body[data-ds-dark-theme] .scp-veil,[data-theme="dark"] .scp-veil{background:rgba(0,0,0,.55);}
body[data-ds-dark-theme] .scp-pal .scp-cmd-backdrop,[data-theme="dark"] .scp-pal .scp-cmd-backdrop{background:rgba(0,0,0,.45);}
.scp-modal{width:min(680px,calc(100% - 40px));max-height:74vh;display:flex;flex-direction:column;background:var(--scp-surface);border:1px solid var(--scp-border-strong);border-radius:16px;box-shadow:var(--scp-shadow);overflow:hidden;}
.scp-modal-top{display:flex;align-items:flex-start;gap:var(--scp-sp-3);padding:var(--scp-sp-4) var(--scp-sp-5) var(--scp-sp-3);border-bottom:1px solid var(--scp-border);}
.scp-modal-title{font-size:var(--scp-fs-title);font-weight:var(--scp-fw-bold);line-height:var(--scp-lh-tight);}
.scp-modal-sub{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-regular);color:var(--scp-muted);margin-top:3px;line-height:var(--scp-lh-base);}
.scp-modal-body{overflow:auto;padding:var(--scp-sp-3) var(--scp-sp-5);display:flex;flex-direction:column;gap:var(--scp-sp-3);}
.scp-modal-foot{display:flex;align-items:center;gap:var(--scp-sp-2);padding:var(--scp-sp-3) var(--scp-sp-5);border-top:1px solid var(--scp-border);}
.scp-prompt{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);white-space:pre-wrap;background:var(--scp-surface-2);border:1px solid var(--scp-border);border-radius:10px;padding:var(--scp-sp-3) var(--scp-sp-3);color:var(--scp-text);max-height:250px;overflow:auto;-webkit-mask-image:linear-gradient(to bottom,#000 88%,transparent);mask-image:linear-gradient(to bottom,#000 88%,transparent);}
.scp-prompt-cap{font-size:var(--scp-fs-cap);color:var(--scp-muted);margin-top:-5px;}
.scp-details-toggle{width:fit-content;border:0;background:transparent;color:var(--scp-accent);font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);padding:1px 0;cursor:pointer;}
.scp-details-toggle:hover{text-decoration:underline;}
.scp-warn-list{display:flex;flex-direction:column;gap:var(--scp-sp-1);font-size:var(--scp-fs-label);color:var(--scp-muted);line-height:var(--scp-lh-base);}
.scp-warn-list b{color:var(--scp-warn);font-weight:var(--scp-fw-semi);}
.scp-pick-list{display:flex;flex-direction:column;gap:var(--scp-sp-2);}
.scp-pick{display:flex;gap:var(--scp-sp-3);align-items:flex-start;padding:var(--scp-sp-3);border:1px solid var(--scp-border);border-radius:10px;background:var(--scp-surface);cursor:pointer;text-align:left;}
.scp-pick[data-on="true"]{background:var(--scp-accent-soft);border-color:var(--scp-accent-line);}
.scp-pick:disabled{opacity:.45;cursor:not-allowed;}
.scp-radio{width:14px;height:14px;border-radius:50%;border:2px solid var(--scp-border-strong);flex:none;margin-top:1px;}
.scp-pick[data-on="true"] .scp-radio{border-color:var(--scp-accent);background:var(--scp-accent);box-shadow:inset 0 0 0 3px var(--scp-accent-soft);}
.scp-pick-title{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-semi);display:flex;gap:6px;align-items:center;flex-wrap:wrap;}
.scp-pick-sub{font-size:var(--scp-fs-label);color:var(--scp-muted);margin-top:2px;line-height:var(--scp-lh-base);}
.scp-sed-table{width:100%;border-collapse:collapse;font-size:var(--scp-fs-label);}
.scp-sed-table th{text-align:left;font-weight:var(--scp-fw-semi);color:var(--scp-muted);font-size:var(--scp-fs-cap);letter-spacing:.02em;padding:0 6px 5px;border-bottom:1px solid var(--scp-border);}
.scp-sed-table td{padding:6px;border-bottom:1px solid color-mix(in srgb,var(--scp-border) 72%,transparent);vertical-align:top;}
.scp-sed-table tr:last-child td{border-bottom:0;}
.scp-sed-kv{display:flex;flex-direction:column;gap:6px;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);}
.scp-sed-kv-row{display:grid;grid-template-columns:64px 1fr;gap:var(--scp-sp-2);min-width:0;}
.scp-sed-kv-row dt{font-size:var(--scp-fs-label);color:var(--scp-muted);}
.scp-sed-kv-row dd{margin:0;color:var(--scp-text);overflow-wrap:anywhere;}
.scp-sed-link{display:block;margin-top:2px;color:var(--scp-accent);text-decoration:none;overflow-wrap:anywhere;word-break:break-all;}
.scp-sed-link:hover{text-decoration:underline;}
.scp-sed-actions{position:sticky;bottom:0;display:flex;align-items:center;gap:var(--scp-sp-2);flex-wrap:wrap;margin:var(--scp-sp-5) calc(-1 * var(--scp-side-pad-x)) 0;padding:var(--scp-sp-3) var(--scp-side-pad-x) var(--scp-sp-4);border-top:1px solid var(--scp-border);background:var(--scp-surface-2);box-shadow:0 -8px 16px -12px color-mix(in srgb,var(--scp-text) 24%,transparent);}
.scp-sed-hint{font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-muted);}
/* 最近完成落在宽 300–400px 的左列里：标题、状态、PR 链接、时间挤一行时，链接与时间会在中间断行
   （#482 被拆成两行、时间拆成日期与时刻）。改成两行：标题 + 时间；状态 + PR 链接。 */
.scp-sed-history{display:flex;flex-direction:column;gap:2px;width:100%;margin-top:10px;padding-top:var(--scp-sp-2);border-top:1px solid var(--scp-border);}
.scp-sed-history-row{display:flex;flex-direction:column;align-items:stretch;gap:2px;padding:4px 0;font-size:var(--scp-fs-label);color:var(--scp-muted);min-width:0;text-align:left;}
.scp-sed-history-row+.scp-sed-history-row{border-top:1px solid color-mix(in srgb,var(--scp-border) 60%,transparent);}
.scp-sed-history-line{display:flex;align-items:baseline;gap:var(--scp-sp-2);min-width:0;}
.scp-sed-history-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--scp-fs-sm);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-text);}
.scp-sed-history-time{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
.scp-sed-history-pr{flex:none;white-space:nowrap;}
.scp-dock-sed{display:flex;align-items:center;gap:7px;min-width:0;margin-top:1px;padding:5px 2px 0;border-top:1px solid var(--scp-border);font-size:var(--scp-fs-meta);}
.scp-dock-sed-dot{width:6px;height:6px;border-radius:50%;background:var(--scp-warn);flex:none;}
.scp-dock-sed-dot[data-tone="ok"]{background:var(--scp-ok);}
.scp-dock-sed-dot[data-tone="bad"]{background:var(--scp-bad);}
.scp-dock-sed-dot[data-tone="accent"]{background:var(--scp-accent);}
.scp-dock-sed-label{color:var(--scp-muted);flex:none;}
.scp-dock-sed-stage{color:var(--scp-text);font-weight:var(--scp-fw-semi);white-space:nowrap;}
.scp-dock-sed-sep{color:var(--scp-border-strong);flex:none;}
.scp-dock-sed-days{color:var(--scp-warn);font-weight:var(--scp-fw-bold);flex:none;font-variant-numeric:tabular-nums;}
.scp-dock-sed-next{color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
.scp-dock-sed-open{flex:none;border:0;background:var(--scp-accent-soft);color:var(--scp-accent);font:inherit;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);padding:2px 7px;border-radius:6px;cursor:pointer;}
/* 知识库落后提示：一行内联提示，不占诊断状态的位置；琥珀是「欠账」色，沿用 warn 变量。 */
.scp-kb-notice{display:flex;align-items:center;gap:6px;min-width:0;padding:0 2px;color:var(--scp-warn);font-size:var(--scp-fs-meta);line-height:1.6;}
.scp-kb-notice-dot{flex:none;width:5px;height:5px;border-radius:50%;background:var(--scp-warn);}
.scp-kb-notice-main{flex:0 1 auto;min-width:0;display:flex;align-items:baseline;gap:6px;overflow:hidden;}
.scp-kb-notice-text{font-weight:var(--scp-fw-semi);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-kb-notice-note{font-size:var(--scp-fs-cap);line-height:1.6;color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-kb-notice .scp-btn{flex:none;font-size:var(--scp-fs-meta);line-height:1.5;padding:0 4px;border:0;background:transparent;color:var(--scp-warn);font-weight:var(--scp-fw-semi);}
.scp-kb-notice .scp-kb-go:hover{background:var(--scp-warn-soft);}
.scp-kb-notice .scp-kb-later{color:var(--scp-muted);font-weight:var(--scp-fw-medium);}
.scp-kb-notice .scp-kb-later:hover{background:var(--scp-surface-2);color:var(--scp-text);}
/* 连败上屏：同样是一行内联提示，用错误色与「有更新」区分。 */
.scp-kb-error{display:flex;align-items:center;gap:6px;min-width:0;padding:0 2px;color:var(--scp-bad);font-size:var(--scp-fs-meta);line-height:1.6;}
.scp-kb-error-dot{flex:none;width:5px;height:5px;border-radius:50%;background:var(--scp-bad);}
.scp-kb-error-main{flex:1 1 auto;min-width:0;display:flex;}
.scp-kb-error-text{font-weight:var(--scp-fw-semi);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-kb-error .scp-btn{flex:none;font-size:var(--scp-fs-meta);line-height:1.5;padding:0 4px;border:0;background:transparent;color:var(--scp-bad);font-weight:var(--scp-fw-semi);}
.scp-kb-error .scp-btn:hover{background:var(--scp-bad-soft);}
@container (max-width: 720px){.scp-kb-notice,.scp-kb-error{flex-wrap:wrap;}.scp-kb-notice-note{display:none;}}
body[data-ds-dark-theme] .scp-actions,body[data-ds-dark-theme] .scp-sed-actions,[data-theme="dark"] .scp-actions,[data-theme="dark"] .scp-sed-actions{box-shadow:0 -8px 16px -12px rgba(0,0,0,.55);}
.scp-row-wrap{position:relative;display:flex;align-items:center;gap:2px;min-width:0;}
.scp-row-wrap>.scp-pal-row,.scp-row-wrap>.scp-sed-row{flex:1 1 auto;min-width:0;}
.scp-row-check{flex:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;margin-left:3px;padding:0;border:0;border-radius:6px;background:transparent;cursor:pointer;opacity:0;pointer-events:none;transition:opacity 120ms ease;}
/* 行前复选框覆在状态点的位置上：默认不占宽，悬停 / 选择态 / 已勾选时盖住状态点，行首不再留 24px 空槽。 */
.scp-row-wrap>.scp-row-check{position:absolute;left:6px;top:50%;transform:translateY(-50%);z-index:2;margin-left:0;}
/* 沉淀行的状态点贴行首（10px 内边距 + 7px 上边距 + 6px 圆点，中心在 20px），复选框跟着它对齐。 */
.scp-row-wrap--sed>.scp-row-check{top:8px;transform:none;}
.scp-row-wrap:hover .scp-row-check,.scp-row-wrap:focus-within .scp-row-check{opacity:1;pointer-events:auto;}
.scp-pal-list[data-selecting="true"] .scp-row-check{opacity:1;pointer-events:auto;}
.scp-row-check[aria-checked="true"]{opacity:1;pointer-events:auto;}
.scp-batch .scp-row-check{opacity:1;pointer-events:auto;}
.scp-row-check:hover{background:var(--scp-surface-2);}
.scp-select-toggle{margin-left:auto;flex:none;display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 8px;border:1px solid transparent;border-radius:7px;background:transparent;color:var(--scp-muted);font:inherit;font-size:var(--scp-fs-label);line-height:1;cursor:pointer;}
.scp-select-toggle:hover{background:var(--scp-surface-2);color:var(--scp-text);}
.scp-select-toggle::before{content:"";width:12px;height:12px;border:1.5px solid var(--scp-border-strong);border-radius:3px;background:var(--scp-surface);}
.scp-row-check-box{width:15px;height:15px;border:1.5px solid var(--scp-border-strong);border-radius:4px;background:var(--scp-surface);display:grid;place-items:center;font-size:10px;line-height:1;color:transparent;}
.scp-row-check[aria-checked="true"] .scp-row-check-box{background:var(--scp-accent);border-color:var(--scp-accent);color:var(--scp-on-accent);}
.scp-row-check[data-mixed="true"] .scp-row-check-box{border-color:var(--scp-accent);background:var(--scp-surface);position:relative;}
.scp-row-check[data-mixed="true"] .scp-row-check-box::after{content:"";width:7px;height:2px;border-radius:1px;background:var(--scp-accent);}
.scp-pal-row[data-sel="true"],.scp-sed-row[data-sel="true"]{background:var(--scp-surface-2);}
.scp-pal-row[data-on="true"][data-sel="true"],.scp-sed-row[data-on="true"][data-sel="true"]{background:var(--scp-accent-soft);}
.scp-batch{position:relative;display:flex;}
.scp-batch-line{display:flex;align-items:center;gap:var(--scp-sp-2);min-width:0;max-width:100%;flex-wrap:wrap;}
/* 动作组靠右；一行放得下时与左侧读数同一行，放不下才整组换到下一行。 */
.scp-batch-line + .scp-batch-line{margin-left:auto;}
.scp-batch-note{font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
.scp-batch-menu{position:absolute;right:var(--scp-sp-5);top:calc(100% - 2px);z-index:8;width:min(300px,calc(100% - 32px));padding:5px;border:1px solid var(--scp-border-strong);border-radius:12px;background:var(--scp-surface);box-shadow:var(--scp-shadow);}
.scp-batch-item{display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;border:0;border-radius:8px;background:transparent;color:var(--scp-text);font:inherit;font-size:var(--scp-fs-body);text-align:left;cursor:pointer;}
.scp-batch-item:hover{background:var(--scp-surface-2);}
.scp-batch-item:disabled{opacity:.45;cursor:not-allowed;}
.scp-batch-item-n{margin-left:auto;font-size:var(--scp-fs-cap);color:var(--scp-muted);font-variant-numeric:tabular-nums;}
.scp-batch-empty{padding:6px 9px;font-size:var(--scp-fs-meta);color:var(--scp-muted);line-height:var(--scp-lh-base);}
.scp-receipt{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:7px var(--scp-sp-5);border-bottom:1px solid var(--scp-border);background:var(--scp-surface-2);font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);flex:none;}
.scp-receipt-strong{color:var(--scp-text);font-weight:var(--scp-fw-medium);}
.scp-receipt .scp-btn{height:22px;padding:0 8px;font-size:var(--scp-fs-meta);}
@media (max-width:760px){.scp-batch{flex-wrap:wrap;gap:6px 8px;}.scp-batch .scp-spacer{display:none;}.scp-sed-step-label,.scp-sed-step-note{font-size:var(--scp-fs-cap);}.scp-target-row{flex-wrap:wrap;}}
/* 减少动态效果：过渡全部归零（含状态条、菜单、选择器、复选框）；静置淡出仍是瞬时变化。 */
@media (prefers-reduced-motion: reduce){.scp-handle,.scp-handle-title,.scp-handle-meta,.scp-ring,.scp-surface,.scp-scope,.scp-collapse,.scp-case,.scp-btn,.scp-icon,.scp-tick,.scp-pal-row,.scp-sed-row,.scp-chevron,.scp-check-action,.scp-filter-item,.scp-view-tab,.scp-menu-item,.scp-menu-note,.scp-tool-btn,.scp-picker-row,.scp-row-check,.scp-select-toggle,.scp-batch-item,.scp-dock-sed-open,.scp-pick{transition:none;}.scp-pal,.scp-menu,.scp-toast,.scp-picker,.scp-cmd,.scp-skel,.scp-ring{animation:none;}}`,
    ].join('\n')

