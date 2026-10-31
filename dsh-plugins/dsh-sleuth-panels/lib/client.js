/* eslint-disable */
// 生成物 —— 勿手改。由 `node scripts/build_panel_bundle.js` 从下列源文件拼出：
//   dsh-plugins/ascend-panel/panel-client.js  (sha256:c22b075ac0d6)
//   dsh-plugins/ev-panel/panel-client.js  (sha256:f684735469ce)
//   dsh-plugins/sleuth-console/console-client.js  (sha256:119062e6c579)
// 校验：`node scripts/build_panel_bundle.js --check`。
//
// 面板源码是动态插件方言（靠沙箱提供的 host 通信）；这里原文嵌入页面产物，并补一层适配：
// host.call(name, args) → ctx.get('connection').rpc.call(CHANNEL, name, args)。
// React 由页面的模块表提供（与宿主同一份，不重复安装）。
//
// SLEUTH_VIEWS 是三个源文件之间的登记表：两个面板把视图写进去，sleuth-console 的整页
// 按 id 取来渲染。动态热加载路径没有这个对象，面板因此退回 conversation.view 的 tab。
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

    // 面板视图登记表（见文件头）：面板 apply 时写入，sleuth-console 的整页读取。
    const SLEUTH_VIEWS = {}

    const PANELS = [
    {
      id: 'ascend-panel',
      build(host, styles) {
        return (function () {
// ---- dsh-plugins/ascend-panel/panel-client.js (sha256:c22b075ac0d6) 原文开始 ----
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
    // 搜索防抖的待执行句柄：新按键先撤掉上一次，避免"清空后旧的定时器又把词写回来"。
    let queryTimerDispose = null

    // —— 切到一个 DSH 会话（卡片上的「打开会话」与侧栏「诊断记录」共用）——
    // 服务怎么取：cordis 的服务要声明进 inject 才建键（第一版没声明，拿到的是空）。
    // 声明后拿到了**对象**，但它不是文档里那个 `{ open }` 面——所以这里不再对方法名做假设：
    // 接受任何对象，按候选方法名依次试，谁成功用谁；都不成才把对象上的方法名列出来。
    // 这份"实测优先"的写法是被两轮无效排查逼出来的：先声明、再猜方法名，比继续读文档快。
    let sessionsRef
    function noteSessions(v) {
      if (v && typeof v === 'object' && sessionsRef === undefined) sessionsRef = v
      return sessionsRef
    }
    try { noteSessions(ctx.sessions) } catch (e) { /* 未声明时可能抛，忽略 */ }
    try { noteSessions(ctx.get('sessions')) } catch (e) { /* 同上 */ }
    let injectCbFired = '未触发'
    try {
      if (typeof ctx.inject === 'function') {
        ctx.inject(['sessions'], (scope) => {
          injectCbFired = '已触发'
          try { noteSessions(scope.get('sessions')) } catch (e) { /* 子 fiber 也没有就继续走探针 */ }
          try { noteSessions(scope.sessions) } catch (e) { /* 同上 */ }
        })
      }
    } catch (e) { injectCbFired = '注册抛：' + String((e && e.message) || e) }

    // 一个对象上可调用的方法名（含原型链，最多 4 层）——报错时用来替代"再读一遍文档"。
    function methodNamesOf(o) {
      const out = []
      let cur = o
      let depth = 0
      while (cur && cur !== Object.prototype && depth < 4) {
        for (const k of Object.getOwnPropertyNames(cur)) {
          if (out.indexOf(k) >= 0) continue
          try { if (typeof o[k] === 'function') out.push(k) } catch (e) { /* getter 抛就算了 */ }
        }
        cur = Object.getPrototypeOf(cur)
        depth += 1
      }
      return out
    }

    // 切会话的方法名候选：文档里叫 `open`，实测的那一版不是；其余是同义常见写法。
    const OPEN_METHODS = ['open', 'openSession', 'select', 'selectSession', 'show', 'activate', 'focus', 'switchTo']
    // 状态词表（来自 host 的投影）。面板不自己维护标签：有它就用它，没有才退回旧常量
    // （旧常量是迁移期的兜底，面板接线完成后删除）。
    let VOCAB_CACHE = null

    function sessionsProbe() {
      const names = ['sessions', 'connection', 'slots', 'workspaces', 'uiWorkspace', 'conversation', 'remote']
      const seen = []
      for (const n of names) {
        try {
          const v = ctx.get(n)
          seen.push(n + (v === undefined ? '=空' : '=' + typeof v))
        } catch (e) {
          seen.push(n + '=抛')
        }
      }
      const describe = (label, obj) => {
        if (!obj) return label + '=（空）'
        const fns = methodNamesOf(obj)
        if (fns.length) return label + ' 方法：' + fns.slice(0, 16).join('、')
        let keys = []
        try { keys = Object.keys(obj).slice(0, 12) } catch (e) { keys = [] }
        return label + ' 无方法；字段：' + (keys.length ? keys.join('、') : '（连字段都没有）')
      }
      let uiWs
      try { uiWs = ctx.get('uiWorkspace') } catch (e) { uiWs = undefined }
      // 读 `sessions.open` 本身会不会抛：cordis 对"没声明/未激活"的服务是**抛**而不是返回空，
      // 这一条能把"方法不存在"和"服务对我们不可见"分开。
      let openRead = '（没有对象）'
      if (sessionsRef) {
        try {
          openRead = typeof sessionsRef.open === 'function' ? '函数' : '空'
        } catch (e) {
          openRead = '抛：' + String((e && e.message) || e)
        }
      }
      return '实测：' + seen.join('、')
        + '；sessions.open 读取=' + openRead
        + '；ctx.inject 回调=' + injectCbFired
        + '；' + describe('sessions', sessionsRef) + '；' + describe('uiWorkspace', uiWs)
    }

    function sessionsService() {
      if (sessionsRef !== undefined) return sessionsRef
      try { noteSessions(ctx.get('sessions')) } catch (e) { /* 未声明 */ }
      try { noteSessions(ctx.sessions) } catch (e) { /* 同上 */ }
      return sessionsRef
    }

    // `sessions.open(id)` 对**不在客户端列表里**的 id 会抛（`sessions.select: unknown session …`）。
    // traces/ 里有从别的机器接手的单（`import_trace.py` 落位的那批），那些会话在本机不存在，
    // 所以这里把结果收成对象：调用方按结果给一句人话，不让异常从 React 事件里甩出去变成
    // "点了没反应"。第二枪先拉一次 Host 权威列表再开——列表是快照，久未活动的会话可能还没进来
    // （`refresh()` 是客户端服务已有的公开方法，见 sessions 服务面）。
    async function openSession(id) {
      const sessions = sessionsService()
      if (sessions === undefined) {
        return { ok: false, reason: '插件没拿到会话服务。' + sessionsProbe() }
      }
      const target = String(id)
      // 候选：在两个可能承载"切会话"的服务上，按候选方法名依次试（谁成功用谁）。
      const hosts = [['sessions', sessions]]
      try {
        const uiWs = ctx.get('uiWorkspace')
        if (uiWs) hosts.push(['uiWorkspace', uiWs])
      } catch (e) { /* 没有这个服务就只试 sessions */ }
      const tried = []
      for (const [hostName, host] of hosts) {
        for (const name of OPEN_METHODS) {
          let fn
          try { fn = host[name] } catch (e) { continue }
          if (typeof fn !== 'function') continue
          tried.push(hostName + '.' + name)
          try {
            fn.call(host, target)
            return { ok: true }
          } catch (first) {
            const why = String((first && first.message) || first)
            // "不在列表里"这一类值得刷新后在同一方法上再试一次；其它异常继续试下一个名字。
            if (!/unknown session|not listed|不存在/i.test(why)) continue
            try { if (typeof sessions.refresh === 'function') await sessions.refresh() } catch (e) { /* 刷新失败就按原样报 */ }
            try {
              fn.call(host, target)
              return { ok: true }
            } catch (second) {
              return { ok: false, reason: '拉过最新列表仍然没有这一条（外来单或已归档）：' + String((second && second.message) || second) }
            }
          }
        }
      }
      return { ok: false, reason: '试过 ' + (tried.length ? tried.join(' / ') : '（没有可用的打开方法）') + ' 都没打开。' + sessionsProbe() }
    }

    // —— 诊断记录浮层：侧栏页脚的入口与全帧浮层是两个独立注册，靠这个小 store 同步开关 ——
    // 两处落在不同的 React 树里（页脚在侧栏列内，浮层在帧级图层），不能用 props 传开关；
    // 也不能用全局定时器或全局事件（动态包沙箱没有它们）。订阅者各持一份本地 state。
    const ledger = { open: false, listeners: new Set() }
    function setLedgerOpen(next) {
      const v = !!next
      if (ledger.open === v) return
      ledger.open = v
      ledger.listeners.forEach(fn => { try { fn(v) } catch (e) { /* 单个订阅者出错不拖累其余 */ } })
    }
    function useLedgerOpen() {
      const [open, setOpen] = React.useState(ledger.open)
      React.useEffect(() => {
        const fn = v => setOpen(v)
        ledger.listeners.add(fn)
        // 订阅建立之前开关可能已经变过（先点入口、后挂浮层），所以补读一次当前值。
        setOpen(ledger.open)
        return () => { ledger.listeners.delete(fn) }
      }, [])
      return open
    }

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
  --btn-blue-a:#2563eb;--btn-blue-b:#1d4ed8;--btn-green-a:#15803d;--btn-green-b:#166534;
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
  --r-xs:5px;--r-sm:7px;--r-md:9px;--r-lg:12px;--r-pill:999px;
  /* 动效：三档时长 + 一条 ease-out；新增动效只用这三个时长 */
  --m-fast:120ms;--m-base:160ms;--m-slow:220ms;--e-out:cubic-bezier(.22,1,.36,1);
  --hair-strong:color-mix(in srgb, var(--dsw-alias-label-primary) 16%, transparent)}
body[data-ds-dark-theme] .sleu{--c-blue:#7db3fc;--c-green:#5cd68f;--c-purple:#b39bfb;--c-amber:#fbbf24;--c-red:#fb8a8a;--c-gray:#a8b0bd;
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
.sleu{--row-cols:92px minmax(0,1fr) 112px 54px 68px 78px 16px;font-family:var(--font-sans);font-size:var(--t-base);line-height:var(--lh-base);color:var(--dsw-alias-label-primary);
  font-feature-settings:"tnum" 1,"cv05" 1;font-optical-sizing:auto;letter-spacing:.006em}
.sleu button,.sleu input{font-family:inherit}
/* 数字一律等宽对齐（指标/容量/期号同列可比） */
.sleu-num{font-family:var(--font-mono);font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1;letter-spacing:-.01em}
.sleu-mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
/* 中英混排微调：中文行更高的 readability，标题收紧字距（现代排版惯例） */
.sleu-title{font-size:var(--t-lg);font-weight:700;letter-spacing:-.012em;line-height:var(--lh-tight)}
.sleu-prose{line-height:var(--lh-prose)}
@keyframes sleuRise{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
/* 交互反馈：hover/active 有分寸（现代观感来自"响应"而非"装饰"） */
.sleu-row{background:transparent;transition:background-color var(--m-fast) var(--e-out)}
.sleu-row:hover{background:var(--tint-blue)}
.sleu-row:active{background:color-mix(in srgb,var(--d-blue) 14%,transparent)}
.sleu-card{box-shadow:var(--elev-1);transition:box-shadow var(--m-slow) var(--e-out),border-color var(--m-base) var(--e-out)}
.sleu-card:hover{box-shadow:var(--elev-2)}
.sleu-chip{background:transparent;border:1px solid var(--hair);color:var(--dsw-alias-label-secondary);border-radius:var(--r-pill);padding:4px 12px;font-size:var(--t-sm);line-height:var(--lh-base);cursor:pointer;transition:background-color var(--m-fast) var(--e-out),border-color var(--m-fast) var(--e-out),color var(--m-fast) var(--e-out)}
.sleu-chip:hover{border-color:var(--d-blue);color:var(--d-blue);background:var(--tint-blue)}
.sleu-chip:active{background:color-mix(in srgb,var(--d-blue) 16%,transparent)}
.sleu-chip[aria-pressed="true"]{background:color-mix(in srgb,var(--d-blue) 12%,transparent);border-color:var(--d-blue);color:var(--d-blue);font-weight:600}
.sleu-chip:active{transform:scale(.97)}
.sleu-menu-panel{animation:sleuMenu var(--m-fast) var(--e-out)}
@keyframes sleuMenu{from{opacity:0;transform:translateY(-2px)}to{opacity:1;transform:none}}
.sleu-fold[open]>.sleu-fold-body{animation:sleuFade var(--m-base) var(--e-out)}
.sleu-list{container-type:inline-size}
.sleu-expanded{display:grid;grid-template-columns:minmax(0,1fr) 240px;align-items:start}
.sleu-band{grid-column:1 / -1;min-width:0;padding:0 16px}
.sleu-main{grid-column:1;padding:12px 16px;border-top:1px solid var(--hair);background:var(--dsw-alias-bg-layer-2);min-width:0;content-visibility:auto;contain-intrinsic-size:auto 640px}
.sleu-rail{grid-column:2;padding:12px 16px 14px 0;border-top:1px solid var(--hair);position:sticky;top:8px;align-self:start;min-width:0}
@container (max-width: 760px){
  .sleu-expanded{grid-template-columns:minmax(0,1fr)}
  .sleu-rail{grid-column:1;position:static;padding:12px 16px}
}
@container (max-width: 700px){
  .sleu-list{--row-cols:92px minmax(0,1fr) 112px 16px}
  .sleu-c-events,.sleu-c-ms,.sleu-c-tok{display:none}
}
@container (max-width: 560px){
  .sleu-list{--row-cols:84px minmax(0,1fr) 16px}
  .sleu-c-fw{display:none}
}
.sleu :focus-visible{outline:2px solid var(--d-blue);outline-offset:2px}
.sleu input:focus-visible{outline-offset:1px}
.sleu-skel{background:linear-gradient(90deg,var(--hair) 0%,color-mix(in srgb,var(--dsw-alias-label-primary) 5%,transparent) 50%,var(--hair) 100%);background-size:200% 100%;animation:sleuShimmer 1.4s linear infinite;border-radius:var(--r-xs)}
@keyframes sleuShimmer{from{background-position:200% 0}to{background-position:-200% 0}}
.sleu-open{animation:sleuFade var(--m-base) var(--e-out)}
@keyframes sleuFade{from{opacity:0}to{opacity:1}}
/* 迷你趋势条（与 ev-panel 的 .ev-bars 同一套 CSS 条形原语，不用 SVG——两面板视觉语言一致） */
.sleu-bars{display:flex;align-items:flex-end;gap:2px;height:18px;flex-shrink:0}
.sleu-bar{width:5px;border-radius:2px 2px 1px 1px;background:var(--acc-blue);opacity:.9;transition:opacity var(--m-base) var(--e-out),height var(--m-slow) var(--e-out)}
.sleu-bar.dim{background:var(--acc-gray);opacity:.45}
.sleu-bar.miss{background:transparent;border-bottom:1px dashed var(--dsw-alias-border-l1)}
.sleu-bars:hover .sleu-bar{opacity:1}
/* 轨迹时间轴：左侧刻度点 + 竖轨（"第几步"要能一眼数出来），滑过时刻度点亮 */
.sleu-tl-row{display:flex;gap:10px;align-items:stretch}
.sleu-tl-mk{width:14px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;padding-top:5px}
.sleu-tl-dot{width:7px;height:7px;border-radius:999px;background:var(--bd,var(--dsw-alias-border-l1));flex-shrink:0;transition:transform var(--m-base) var(--e-out),background var(--m-base) var(--e-out)}
.sleu-tl-rail{flex:1;width:1.5px;background:var(--dsw-alias-border-l1);margin-top:3px;border-radius:1px}
.sleu-tl-row:hover .sleu-tl-dot{transform:scale(1.35)}
.sleu-tl-row:hover .sleu-tl-rail{background:color-mix(in srgb,var(--d-blue) 35%,transparent)}
.sleu-fab{position:fixed;right:18px;bottom:18px;z-index:3;width:34px;height:34px;border-radius:999px;border:1px solid var(--hair);background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-secondary);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;line-height:1;box-shadow:var(--elev-2);transition:transform var(--m-base) var(--e-out),color var(--m-base) var(--e-out)}
.sleu-fab:hover{transform:translateY(-2px);color:var(--d-blue)}
.sleu details>summary{list-style:none;cursor:pointer}.sleu details>summary::-webkit-details-marker{display:none}
.sleu-fold{border:1px solid var(--hair);border-radius:var(--r-md);background:var(--dsw-alias-bg-layer-1);margin-bottom:10px;overflow:hidden}
.sleu-fold>summary{display:flex;align-items:center;gap:8px;padding:8px 10px;font-size:var(--t-sm);font-weight:600;color:var(--dsw-alias-label-primary);transition:background-color var(--m-fast) var(--e-out)}
.sleu-fold>summary::before{content:'▸';color:var(--dsw-alias-label-secondary);transition:transform var(--m-base) var(--e-out);display:inline-block}
.sleu-fold[open]>summary::before{transform:rotate(90deg)}
.sleu-fold>summary:hover{background:var(--tint-blue)}
.sleu-fold[open]>summary{border-bottom:1px solid var(--hair);background:var(--dsw-alias-bg-layer-2)}
.sleu-fold-body{padding:8px 10px}
.sleu-fold-compact{border:none;background:transparent;margin:6px 0}
.sleu-fold-compact>summary{display:inline-flex;padding:2px 9px;font-size:var(--t-tiny);font-weight:600;color:var(--d-blue);border:1px solid var(--hair);border-radius:var(--r-pill)}
.sleu-fold-compact[open]>summary{border-color:var(--d-blue);background:var(--tint-blue)}
.sleu-fold-compact .sleu-fold-body{padding:6px 0 0}
.sleu-fold-body>div:first-child>.sleu-block:first-child,.sleu-fold-body>.sleu{margin-top:0}
/* 诊断记录浮层：侧栏页脚的入口 + 帧级浮层本体。浮层落在 shell.overlay 那一层（点击穿透），
   所以根节点自己把 pointer-events 打开；卡片用 fixed 定位，不挤动下方任何列。 */
.sleu-ledger-backdrop{position:fixed;inset:0;z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:8vh 16px 24px;background:color-mix(in srgb, var(--dsw-alias-label-primary) 22%, transparent);pointer-events:auto}
.sleu-ledger-card{display:flex;flex-direction:column;width:min(780px,100%);max-height:76vh;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--hair);border-radius:var(--r-lg);box-shadow:0 18px 48px color-mix(in srgb, var(--dsw-alias-label-primary) 24%, transparent);overflow:hidden}
.sleu-ledger-head{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--hair);flex-wrap:wrap}
.sleu-ledger-body{overflow:auto;padding:4px 0}
.sleu-ledger-row{display:grid;grid-template-columns:72px minmax(0,1.4fr) minmax(0,1.6fr) auto auto;gap:10px;align-items:center;width:100%;padding:9px 14px;border:none;background:transparent;color:var(--dsw-alias-label-primary);text-align:left;cursor:pointer;font:inherit;transition:background-color var(--m-fast) var(--e-out)}
.sleu-ledger-row:hover{background:var(--tint-blue)}
.sleu-ledger-row:focus-visible{outline:2px solid var(--d-blue);outline-offset:-2px}
.sleu-ledger-sid{font-family:var(--font-mono);font-size:var(--t-tiny);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sleu-ledger-sum{font-size:var(--t-sm);color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sleu-ledger-empty{padding:26px 16px;text-align:center;color:var(--dsw-alias-label-secondary);font-size:var(--t-md);line-height:var(--lh-prose)}
.sleu-ledger-foot{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:8px 14px;border-top:1px solid var(--hair);font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
.sleu-ledger-chips{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:8px 14px;border-bottom:1px solid var(--hair)}
.sleu-ledger-chip{padding:2px 10px;border-radius:var(--r-pill);border:1px solid var(--hair);background:transparent;color:var(--dsw-alias-label-secondary);font:inherit;font-size:var(--t-tiny);cursor:pointer;transition:background-color var(--m-fast) var(--e-out),border-color var(--m-fast) var(--e-out)}
.sleu-ledger-chip:hover{background:var(--tint-blue)}
.sleu-ledger-chip[aria-pressed='true']{border-color:var(--d-blue);color:var(--d-blue);background:var(--tint-blue);font-weight:600}
.sleu-ledger-hint{margin-left:auto;color:var(--dsw-alias-label-secondary);font-size:var(--t-tiny);white-space:nowrap}
.sleu-ledger-row.is-active{background:var(--tint-blue);box-shadow:inset 2px 0 0 var(--d-blue)}
@media (prefers-reduced-motion: reduce){.sleu,.sleu *{animation-duration:.001ms !important;animation-delay:0ms !important;transition-duration:.001ms !important}}
/* 会话行的「待回报」标记（L2 行首空心点 + L1 悬停卡一行）。
   为什么是空心点：侧栏自己的状态点是实心（运行中/完成/未读），空心与它区分开——这是
   "欠账"，不是"会话在跑"。颜色用 amber（需处理，不是错误）。 */
/* 行首记号：一格里只画一个形状。形状=记号种类（缺环 vs 菱形），颜色=同一件事的强弱，
   不靠颜色单独区分（色弱读者要能只凭形状认出来）。8px 是能在侧栏 280px 宽度里不糊的下限。 */
.sleu-row-dot{display:inline-block;width:8px;height:8px;border-radius:999px;border:1.5px solid var(--acc-amber);border-right-color:transparent;transform:rotate(-45deg);box-sizing:border-box;vertical-align:middle}
.sleu-row-gem{display:inline-block;width:7px;height:7px;background:var(--acc-purple);border-radius:1px;transform:rotate(45deg);vertical-align:middle}
/* 悬停卡很窄：标题一行（欠多久）、细节一行（自哪天 + 等什么），超长换行不截字 */
.sleu-hover-mark{display:flex;flex-direction:column;gap:1px;margin-top:3px;font-size:var(--t-sm);line-height:var(--lh-base)}
.sleu-hover-title{color:var(--c-amber);font-weight:600}
.sleu-hover-detail{color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.sleu-hover-axis{color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
`
    const tokenSheet = styles.insert(PANEL_CSS)

    const statusMeta = {
      // `resolved` 的含义是"已收尾（根因定位明确）"，不是"fix 生效"——后者由 feedback.outcome
      // 单独记（词表见 trace-status.yaml）。徽标写「已定位」，与 trace-status.yaml 的 label 一致：
      // 写「已解决」会让读者把"诊断结束"读成"这个客户已经好了"。
      resolved: { label: '已定位', color: 'var(--c-green)', acc: 'var(--acc-green)' },
      in_progress: { label: '进行中', color: 'var(--c-blue)', acc: 'var(--acc-blue)' },
      escalated: { label: '已转上游', color: 'var(--c-amber)', acc: 'var(--acc-amber)' },
      // 「不跟了」写的就是 archived（词表在仓库根 trace-status.yaml）。缺这一项，面板会把它显示成
      // 灰色的「未知」——用户自己标的结局看不出来，等于没记。
      archived: { label: '不再跟进', color: 'var(--c-gray)', acc: 'var(--acc-gray)' },
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
      external_lookup: '外部查证',
    }
    // 外部查证的**能力面**（trace 的 `external_lookup.capability`）：说清这一次查的是什么证据。
    // 与 reference 的 purpose 是两回事，不要合成一张表。
    const CAPABILITY_LABELS = {
      'versioned-code': '按版本查源码', 'upstream-fix': '查修复链',
      'manual-doc': '读手册原文', 'image-to-text': '截图转文字',
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
    // 构建时注入的面板包版本（`scripts/build_panel_bundle.js` 把占位符换成 package.json 的 version）。
    // 为什么要有：面板是「装进 profile 的常驻插件 + 浏览器按 rev 缓存」两层，改完看不到新版时
    // 无法区分"装的还是旧包"与"浏览器缓存了旧 bundle"。有这个串，一眼就能判。
    const PANEL_VERSION = '0.8.2'

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
      // 界面用中文；原值（live/replay/example）留在 note 与 tooltip 里——读者不需要先认英文
      live: { label: '活诊断', color: 'var(--c-green)', acc: 'var(--acc-green)', note: '活诊断 · 参与趋势（kind: live）' },
      replay: { label: '离线回放', color: 'var(--c-blue)', acc: 'var(--acc-blue)', note: '离线评估 · 不参与趋势（kind: replay）' },
      example: { label: '示例', color: T.text2, acc: 'var(--acc-gray)', note: '示例（kind: example）' },
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
    // 人读时间：列表右上一行显示 MM-DD HH:mm（本地时区），完整时间放 title。
    function fmtTime(iso) {
      if (!iso) return null
      const d = new Date(iso)
      if (isNaN(d.getTime())) return null
      const p = n => String(n).padStart(2, '0')
      return (d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
    }
    // 诊断窗口的起止是 epoch 毫秒（轨迹的 created_at 归一成毫秒后的值），这里单独给一个入口，
    // 不把毫秒转成 ISO 字符串再解析一遍。
    function fmtEpoch(ms) {
      if (typeof ms !== 'number' || !isFinite(ms)) return null
      const d = new Date(ms)
      if (isNaN(d.getTime())) return null
      const p = n => String(n).padStart(2, '0')
      return (d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
    }
    function fmtTimeFull(iso) {
      if (!iso) return null
      const d = new Date(iso)
      if (isNaN(d.getTime())) return null
      const p = n => String(n).padStart(2, '0')
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes())
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
      // 超过 7 天转绝对日期：'93 天前' 读不出是哪一期（GitHub / Geist 的同一约定）。
      if (d > 7) { const dt = new Date(t); return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0') }
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

    // 「升了是好还是坏」：{ok,total} 形状的指标里，`ok` 是好事还是坏事不同。
    // misdiagnosis_rate 的 ok 就是误诊数（分子），升了是坏事；tier2_hit 升了是好事。
    // 没有这张表，面板只能按"数值涨了就绿"，误诊从 0 涨到 1 会被画成绿色的 +1。
    const METRIC_UP = {
      misdiagnosis_rate: 'bad', attribution_ratio: 'bad',
      tier2_hit: 'good', routed_accuracy: 'good', feedback_capture: 'good',
      sessions_total: 'neutral', sediment_total: 'good',
    }
    function metricDirection(key, delta) {
      if (!delta) return 'flat'
      const up = METRIC_UP[key] || 'neutral'
      if (up === 'neutral') return 'neutral'
      return (delta > 0) === (up === 'good') ? 'good' : 'bad'
    }

    // 两期对照：比**比率**而不是分子。3/3 → 3/5 是变了（准确率掉），
    // 只比分子会把它们判成"完全一致"（两个都是 3）——静默漏报。
    // 只保留"动了"的指标（新增 / 变化），这是"本期发生了什么"的答案
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
        // 有比率就比率；没有比率才退到数值；再退到显示文本
        const ar = a.rate, br = b.rate
        const an = a.num, bn = b.num
        let changed, delta = null
        if (ar !== null && ar !== undefined && br !== null && br !== undefined) {
          changed = Math.abs(br - ar) > 1e-9
          delta = br - ar
        } else if (an !== null && bn !== null) {
          changed = an !== bn
          delta = bn - an
        } else {
          changed = a.text !== b.text
        }
        if (changed) moved.push({ key: k, label, kind: 'change', from: a.text, to: b.text, delta,
                                  direction: metricDirection(k, delta) })
        else same++
      })
      // 上期有、本期没有的指标 = 本期不再采集
      Object.keys(pm).forEach(k => {
        if (!(k in cm)) moved.push({ key: k, label: METRIC_LABELS[k] || k, kind: 'gone', from: metricValue(pm[k]).text })
      })
      return { moved, same, prevPeriod: prev ? prev.period : null, curPeriod: cur.period }
    }

    const btnBase = { border: 'none', borderRadius: 'var(--r-sm)', padding: '4px 12px', fontSize: 'var(--t-tiny)', fontWeight: 600, cursor: 'pointer', transition: 'background-color var(--m-fast) var(--e-out),border-color var(--m-fast) var(--e-out),color var(--m-fast) var(--e-out)' }
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
      return { background: 'color-mix(in srgb, ' + colorVar + ' 8%, transparent)', color: colorVar, borderRadius: 'var(--r-xs)', padding: '1px 6px', fontSize: 'var(--t-tiny)', fontWeight: 600, whiteSpace: 'nowrap', lineHeight: 'var(--lh-base)' }
    }
    // 面板动效（与 ev-panel 同族）：120–260ms ease-out-quart；reduced-motion 下置 0 关闭
    const EASE = 'cubic-bezier(.22,1,.36,1)'
    const REDUCED = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false
    const DUR = REDUCED ? 0 : 1
    // 首屏区块依次浮现：把读的顺序本身作为视觉信息（递减的延时让读者先看到第一条）；
    // reduced-motion 下不动。
    function rise(i) {
      return DUR ? { animation: 'sleuRise .26s ' + EASE + ' both', animationDelay: (i * 40) + 'ms' } : {}
    }
    // 实心胶囊（结论性标签）；大块面用装饰色，文字用深档（AA）
    function pill(text, color) {
      return React.createElement('span', { style: { color: color, border: '1px solid ' + color, borderRadius: 'var(--r-pill)', padding: '1px 9px', fontSize: 'var(--t-tiny)', fontWeight: 700, whiteSpace: 'nowrap' } }, text)
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
    // hollow：状态是「未知」时用空心点——「用户标了不跟了」与「这条记录没写状态」不能在列表里同形。
    function Dot({ color, size, hollow }) {
      return React.createElement('span', { style: { width: size || 8, height: size || 8, borderRadius: 'var(--r-pill)', background: hollow ? 'transparent' : color, border: hollow ? '1.5px solid ' + color : 'none', boxSizing: 'border-box', display: 'inline-block', flexShrink: 0 } })
    }
    function Chevron({ open, color }) {
      return React.createElement('span', { style: { width: 0, height: 0, borderLeft: '5px solid ' + (color || T.text2), borderTop: '5px solid transparent', borderBottom: '5px solid transparent', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform var(--m-base) var(--e-out)', display: 'inline-block', flexShrink: 0 } })
    }
    function SectionLabel({ children, color }) {
      return React.createElement('div', { style: { fontSize: 'var(--t-tiny)', fontWeight: 700, color: color || T.text2, marginBottom: 4 } }, children)
    }
    // 指标行：value 可带"不可解读"标记——分母为 0 的指标不能安静地显示成 0
    // （gates.yaml 的 readability 判据，由 metrics_health.py 判定、host 透传到这里）。
    // 另有两类载荷：{ total, sub } 让大数当主角（容量），{ node } 承载徽章行。
    // 指标强度档徽标：回答「这个数怎么来的」。只标**弱或近似**的两档，以及没声明的：
    //   `自报` = agent 自己记的判断（弱观测，只作趋势与异常信号，不当验收证据）
    //   `代理` = 用可计算的量代替真量（例如跨运行的分位用各运行分位的加权均值）
    //   `确定性` / `人工` 不标——满屏标签会让读的人不再看它们，而这两档没有"别同权"的风险。
    function StrengthBadge(strength) {
      if (strength === '自报') return React.createElement('span', { title: '这个数由 agent 自报，属弱观测：可作趋势与异常信号，不当验收证据', style: tinyBadge('var(--d-gray)') }, '自报')
      if (strength === '代理') return React.createElement('span', { title: '这个数用可计算的量代替真量（近似），看量级不看小数位', style: tinyBadge('var(--d-gray)') }, '代理')
      // 没有强度档就**不挂徽标**。原先这里给每一行挂一个「未声明强度」，而知识库健康 / 流程闭环
      // 那些计数行（案例数、漏斗）本来就不参与强度体系——满屏的"未声明"只是噪声，
      // 读者会以为面板坏了。真正缺声明的情形在期卡顶部汇总一次（见 metrics tab 的缺口提示）。
      return null
    }
    function MetricRow({ label, value, small, warn, unreadable, unreadableWhy, total, sub, node, strength }) {
      const hasStruct = (total !== undefined && total !== null) || node !== undefined
      const body = hasStruct
        ? React.createElement('div', { style: { minWidth: 0 } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 7, flexWrap: 'wrap' } },
              React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-sm)' } }, label),
              total !== undefined && total !== null ? React.createElement('span', { style: { fontSize: 'var(--t-xl)', fontWeight: 700, fontFamily: 'var(--font-mono)', color: warn ? T.warn : T.text, letterSpacing: '-.01em' } }, total) : null,
              small ? React.createElement('span', { title: '样本量 <5', style: tinyBadge('var(--d-gray)') }, '小样本') : null,
              unreadable ? React.createElement('span', { title: unreadableWhy || '分母为 0：这个数不可解读', style: tinyBadge('var(--d-gray)') }, '不可解读') : null,
              warn && !unreadable ? React.createElement('span', { style: tinyBadge('var(--d-red)') }, '超限') : null,
              StrengthBadge(strength),
            ),
            sub ? React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-tiny)', marginTop: 2, lineHeight: 'var(--lh-base)', wordBreak: 'break-word' } }, sub) : null,
            node || null,
          )
        : React.createElement(React.Fragment, null,
            React.createElement('span', { style: { color: T.text2, whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 5 } },
              label,
              small ? React.createElement('span', { title: '样本量 <5', style: tinyBadge('var(--d-gray)') }, '小样本') : null,
              unreadable ? React.createElement('span', { title: unreadableWhy || '分母为 0：这个数不可解读', style: tinyBadge('var(--d-gray)') }, '不可解读') : null,
              StrengthBadge(strength),
            ),
            React.createElement('span', { style: { color: warn ? T.warn : (unreadable ? T.text2 : T.text), fontWeight: 600, textAlign: 'right', wordBreak: 'break-word' } }, value),
          )
      return React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 8px', background: T.bg2, borderRadius: 'var(--r-sm)', fontSize: 'var(--t-md)', alignItems: hasStruct ? 'center' : 'center', opacity: unreadable ? 0.72 : 1 } },
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
      const mono = { fontFamily: 'var(--font-mono)', fontSize: 'var(--t-sm)', background: T.bg, border: '1px solid ' + T.border, borderRadius: 'var(--r-sm)', padding: '8px 10px', color: T.text, lineHeight: 'var(--lh-base)', margin: '6px 0' }
      if (b.kind === 'h') {
        return React.createElement('div', { key: key, style: { fontWeight: 700, fontSize: b.level <= 2 ? 'var(--t-lg)' : 'var(--t-base)', color: T.text, margin: b.level <= 2 ? '12px 0 6px' : '8px 0 4px', paddingBottom: b.level === 2 ? 4 : 0, borderBottom: b.level === 2 ? '1px solid var(--hair)' : 'none' } }, b.text)
      }
      if (b.kind === 'code') return React.createElement('pre', { key: key, style: { ...mono, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflowY: 'auto' } }, b.text)
      if (b.kind === 'table') {
        // 源文里的 | 表格没有 padding，中英双宽再错一层——按 cell 切开用 grid 排，才对得齐。
        const rows = String(b.text || '').split('\n').map(l => l.trim()).filter(Boolean)
          .map(l => l.replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, '|')))
          .filter(cells => !cells.every(c => /^:?-{2,}:?$/.test(c) || c === ''))
        if (!rows.length) return null
        const cols = Math.max.apply(null, rows.map(r => r.length))
        return React.createElement('div', { key: key, style: { display: 'grid', gridTemplateColumns: 'repeat(' + cols + ',minmax(0,1fr))', border: '1px solid var(--hair)', borderRadius: 'var(--r-sm)', overflow: 'hidden', margin: '6px 0' } },
          rows.map((cells, ri) => React.createElement('div', { key: ri, style: { display: 'contents' } },
            cells.concat(Array(Math.max(0, cols - cells.length)).fill('')).map((c, ci) => React.createElement('div', {
              key: ci,
              style: { padding: '5px 8px', fontSize: 'var(--t-sm)', lineHeight: 'var(--lh-base)', borderTop: ri === 0 ? 'none' : '1px solid var(--hair)', background: ri === 0 ? T.bg2 : 'transparent', fontWeight: ri === 0 ? 700 : 400, color: ri === 0 ? T.text2 : T.text, wordBreak: 'break-word', minWidth: 0 },
            }, c)))))
      }
      if (b.kind === 'ul') {
        return React.createElement('div', { key: key, style: { margin: '4px 0 4px 2px' } },
          b.items.map((it, j) => React.createElement('div', { key: j, style: { display: 'flex', gap: 6, fontSize: 'var(--t-md)', lineHeight: 'var(--lh-base)', color: T.text } },
            React.createElement('span', { style: { color: T.text2, flexShrink: 0 } }, '·'),
            React.createElement('span', { style: { minWidth: 0, wordBreak: 'break-word' } }, it.replace(/^\s*([-*+]|\d+\.)\s+/, '')))))
      }
      return React.createElement('div', { key: key, style: { fontSize: 'var(--t-md)', lineHeight: 'var(--lh-base)', color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '4px 0' } }, b.text)
    }

    // 单节渲染上限（字符）：报告最长的一节可达上万字，全铺开会把卡片撑到没法读。
    // 超限时**如实说"还有 N 块没渲染"并指向打开文件**，不静默截断。
    const REPORT_SECTION_MAX = 24000

    function ReportViewer({ state, path, onOpen, opening, section, setSection }) {
      const [copied, setCopied] = React.useState(null)
      if (!state) return null
      if (state.loading) return React.createElement('div', { style: { marginBottom: 10 } },
        [0, 1, 2].map(i => React.createElement('div', { key: i, className: 'sleu-skel', style: { height: 18, marginBottom: 6 } })))
      if (state.error) return React.createElement('div', { style: { marginBottom: 10, color: T.warn, fontSize: 'var(--t-md)' } }, '报告读不到：' + state.error)
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
      return React.createElement('div', { style: { marginBottom: 12, border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', background: T.bg, overflow: 'hidden' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: T.bg2, borderBottom: '1px solid ' + T.border, flexWrap: 'wrap' } },
          React.createElement('span', { style: { fontWeight: 700, fontSize: 'var(--t-md)', color: T.text } }, '定位报告'),
          React.createElement('span', { title: path, className: 'sleu-mono', style: { color: T.text2, fontSize: 'var(--t-tiny)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 } }, path),
          React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)' } }, state.chars + ' 字' + (state.truncated ? '（已截断，看全文请打开文件）' : '')),
          React.createElement('button', { type: 'button', onClick: () => copyText(state.text).then(ok => setCopied(ok ? 'y' : 'n')), style: copied === 'y' ? btnSuccess : btnGhost, title: '复制报告全文（Markdown），可直接发给客户或回贴上游' }, copied === 'y' ? '已复制全文' : (copied === 'n' ? '复制失败' : '复制全文')),
          React.createElement('button', { type: 'button', onClick: onOpen, style: btnGhost }, opening ? '打开中…' : '打开文件'),
        ),
        heads.length ? React.createElement('div', { style: { display: 'flex', gap: 5, flexWrap: 'wrap', padding: '8px 10px 0' } },
          heads.map(h => React.createElement('button', {
            key: h.i, type: 'button', onClick: () => setSection(h.i),
            style: (h.i === secStart) ? { ...btnPrimary, padding: '2px 9px', borderRadius: 'var(--r-pill)', fontSize: 'var(--t-tiny)' } : { ...btnGhost, padding: '2px 9px', borderRadius: 'var(--r-pill)', fontSize: 'var(--t-tiny)' },
          }, h.text)),
        ) : null,
        React.createElement('div', { style: { padding: '4px 12px 12px', maxHeight: 620, overflowY: 'auto' } },
          shownBlocks.map((b, i) => mdNode(b, i)),
          hidden > 0 ? React.createElement('div', { style: { marginTop: 6, color: T.text2, fontSize: 'var(--t-sm)' } }, '本节还有 ' + hidden + ' 块未渲染（超单节显示上限）——看全文请用「打开文件」。') : null,
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

    // —— 三条状态轴（会话列表的筛选/徽标/批量入口共用一份判据）——
    // 三条轴各有名字，不互相借（词表见仓库根 `trace-status.yaml`）：
    //   诊断收尾 `status`（还管不管这单）｜诊断闭环（能不能升格）｜知识沉淀 `sedimented.state`。
    // 「待闭环」以前同时指后两条轴，筛选出来的到底是哪一类债，读者分不清。
    // 三条轴不是互不相干：无命中单的闭环就落在收尾轴上（它没有 case 可写反馈）。
    //
    // 诊断闭环的判据与 `scripts/verify_case_draft.py` 的升格闸门是同一口径——两处各自实现，
    // 改一处必须同步另一处，否则面板说"已闭环"、groom 却拦（或反过来）：
    //   - 命中单看 `feedback.outcome: resolved`；
    //   - 无命中单看 `status: resolved` **且没有显式 outcome**——outcome 有值就表示
    //     "明确未闭环"或"还没回报"，status 不能覆盖它（闸门就是这么判的）。
    function sedStateOf(s) {
      return (s && s.sedimented && s.sedimented.state) ? String(s.sedimented.state) : 'none'
    }
    // 诊断收尾轴：还在管这单（in_progress / 未知）。escalated 与 archived 都是终态，不算未收尾。
    function isOpenOf(s) {
      if (!s) return false
      const st = String(s.status || 'unknown')
      return st === 'in_progress' || st === 'unknown'
    }
    function isClosedOf(s) {
      if (!s) return false
      const outcome = String(s.feedback || '')
      // 与闸门同一顺序：先认 outcome: resolved（命中单的正常闭环；无命中单理论上不写，
      // 但交接包里可能出现，闸门对这类也放行）；再认无命中单的 status: resolved。
      if (outcome === 'resolved') return true
      if (caseKindOf(s) === 'case') return false
      return s.status === 'resolved' && !outcome
    }
    // 「根因已经形成可复用结论」只认一种证据：`sediment_candidates` 里至少有一条 `kind: case`。
    // 为什么不是"有报告"：每一步深度诊断都会产出报告，报告里完全可以是"未定位、转上游"；
    // 也不是"有候选"：`reference` / `triage` 候选记的是知识库覆盖缺口与路由词
    // （实测 `2026-09-14-telechat-cq-alloc-dev5` 有 2 条候选、全是 reference，根因并未定）。
    function hasCaseCandidateOf(s) {
      return !!(s && (s.caseCandidates || 0) > 0)
    }
    // 空记录：条目录到了，但没有任何内容——没有一轮对话、没有背景、没有报告、没有候选。
    // 这类不是"待办"，它要么补一次诊断、要么直接标 archived，占着待办只会让人反复点开它。
    function isSkeletonOf(s) {
      if (!s) return false
      if ((s.userSteps || 0) + (s.agentSteps || 0) > 0) return false
      return !(s.summarySnippet || s.reportFile || s.sedimentCandidates || s.caseCandidates)
    }
    // 待沉淀：有 case 候选、还没沉淀，且命中的 case 不在库里（库中已有的再沉淀会被判 covered_by）。
    function needSedOf(s) {
      if (sedStateOf(s) !== 'none' || !s || s.activeCaseInKb) return false
      return hasCaseCandidateOf(s)
    }
    // 待复核：手里有材料（报告，或只有 reference / triage 候选），但没有 case 候选。
    // 动作是读一眼：根因定了就补一条 case 候选，没定就继续查或标收尾/转上游。
    function needReviewOf(s) {
      if (sedStateOf(s) !== 'none' || !s || s.activeCaseInKb) return false
      if (hasCaseCandidateOf(s)) return false
      return !!(s.reportFile || s.sedimentCandidates)
    }
    // 未收尾：诊断还挂着，且既没有可沉淀结论、也没有待复核材料、也不是空壳、草稿也还没交。
    // 最后一条容易漏：草稿已交的单本身就"还挂着"，不排掉的话它会同时进「未收尾」与「已交草稿」，
    // 两屏的数字就不能相加了。
    function needWorkOf(s) {
      if (!isOpenOf(s) || isSkeletonOf(s)) return false
      return !needSedOf(s) && !needReviewOf(s) && !isSubmittedOf(s)
    }
    // 草稿已交到 inbox（等知识整理）。**这是全部 submitted**，含来源诊断已收尾的正常在途单——
    // 只认"来源未收尾"的话，已收尾但还没整理的那批在界面上完全没有出口。
    function isSubmittedOf(s) {
      return sedStateOf(s) === 'submitted'
    }
    // 其中会被升格前的检查拦下的：草稿已交、但来源诊断还没收尾 → 需要人先补闭环证据或改状态。
    function needPromoteOf(s) {
      return isSubmittedOf(s) && !isClosedOf(s)
    }

    // —— 「价值优先」的唯一一份判据（诊断 tab 的排序与侧栏「诊断记录」共用）——
    // 只看 trace 已有的字段，不新增口径，每一档都指到本仓已有的一条轴：
    //   5 已沉淀（`sedimented.state` 有值）——知识库里留下了东西，最值得复用
    //   4 命中且库里已有（`activeCaseInKb`）——能直接拿来对照
    //   3 命中但库里还没有（新形态）——先看，可能值得沉淀
    //   2 有 fix 且回报已生效（`feedback: resolved`）——结论被现场验证过
    //   1 已定位（`status: resolved`）——有根因，但库里没有对应案例
    //   0 其余（在查 / 转上游 / 不再跟进 / 空记录）
    // 同档按最后更新时间倒序：同档之间没有更强的次序理由，别拿拍脑袋的第二判据凑。
    // 这一句同时出现在三个位置（诊断 tab 的下拉说明、诊断记录的下拉说明、诊断记录的页脚），
    // 只维护这一份。
    const VALUE_ORDER_TEXT = '已沉淀 ＞ 库中已有案例 ＞ 新形态 ＞ fix 已生效 ＞ 已定位 ＞ 其余，同档按最后更新时间倒序'
    function valueRankOf(s) {
      if (sedStateOf(s) !== 'none') return 5
      if (caseKindOf(s) === 'case') return s.activeCaseInKb ? 4 : 3
      if (String(s.feedback || '') === 'resolved') return 2
      if (s.status === 'resolved') return 1
      return 0
    }
    function updatedTsOf(s) {
      const raw = s.updatedAt || s.createdAt
      const t = raw ? new Date(raw).getTime() : NaN
      return isNaN(t) ? 0 : t
    }
    // 开始时间：诊断记录「按时间」排的是**最后更新时间**（行尾那一列就是它，列不降序会被读成
    // 排序坏了），同刻并列才退到开始时间——与 host 判"何时开始诊断"用的是同一条字段。
    function createdTsOf(s) {
      const raw = s.createdAt || s.updatedAt
      const t = raw ? new Date(raw).getTime() : NaN
      return isNaN(t) ? 0 : t
    }

    // 解析异常的一句话（host 的 `parseAnomaly`）。卡面只给"结论 + 行号"，成因与怎么办放 README——
    // 面板读者只看界面，卡上多一句解释就把列表读成文档（实测反馈：这类说明性文字被点过两次）。
    function anomalyText(a) {
      if (!a) return null
      const at = a.firstLine ? '（第 ' + a.firstLine + ' 行起）' : ''
      if (a.dropped) return '轨迹可能不完整：还有 ' + a.dropped + ' 行没被解析' + at
      return '轨迹可能不完整：有一处结构没闭合' + at
    }

    // ── 单次诊断的五块（设计文档 3.7 的表）─────────────────────────────────────
    // 结论 / 各步 / 检索 / 成本 / 本次没记。数据来自两处：轨迹（`traces/<会话>.yaml`，只读）
    // 与单次诊断的本机明细（`metrics/entry-activity.local/<会话>.yaml`，不进 git，只在产生它的
    // 那台机器上）。明细读不到时**不回退到轨迹自行求和**：该显示数据的地方显示缺件与重建命令。
    //
    // 两条硬规则逐块适用（设计文档第 4 节）：没有数据的格子写「本次没记」、缺分母的读数写
    // 「不可解读」，都不写 0。
    const NOT_RECORDED = '本次没记'
    const UNREADABLE = '不可解读'
    // 结论强度档（设计文档 3.1 的取值表）。原值照抄，中文含义给在旁边。
    // `self-report` 指来源会话自证：这条结论由来源会话自己回报，与确定性读数不同权，
    // 所以在界面上单独挂「自证」徽标，不混进其余五档一起读。
    const STRENGTH_LABELS = {
      'upstream-fix-merged': '上游修复已合入',
      'upstream-official-doc': '上游官方文档',
      'upstream-maintainer-confirmed': '上游维护者确认',
      'engineer-report': '工程师回报',
      'investigation': '源码分析或现场推理',
      'self-report': '来源会话自证',
    }
    // 四类 token 与读入账的四个分项（字段名与 scripts/index_read_cost.py 的分项同名）
    const TOKEN_LABELS = [
      ['uncached', '未缓存输入'],
      ['cache_read', '缓存读'],
      ['cache_write', '缓存写'],
      ['out', '输出'],
    ]
    const ACCT_LABELS = [
      ['class_view', '类视图'],
      ['fallback_view', '兜底视图'],
      ['reference_layer', '先验层'],
      ['candidates_full', '阶段二候选全文'],
    ]
    // 千分位：四位数以上的量加分隔（编号与版本号不加——那些走等宽原文，不过这个函数）
    function thousands(n) {
      if (typeof n !== 'number' || !isFinite(n)) return null
      return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    }
    function msText(ms) {
      if (typeof ms !== 'number' || !isFinite(ms)) return null
      if (ms >= 1000) return (ms / 1000).toFixed(1) + ' s'
      return ms + ' ms'
    }
    // 两列读数的取值域说明：窗口内 / 旧格式（只有本会话累计）/ 没有数据。三种情形分开写，
    // 因为「两单的本会话累计一样」正是读者会把它们读成一样贵的那种错。
    function costScopeTitle(cost, base) {
      if (!cost) return base + '：本机明细没有这一单的记录'
      if (cost.scope === 'window') return base
      if (cost.scope === 'session') {
        return base + '：本机明细是旧格式（只记本会话累计），看不出这一单；打开这一单会自动重建'
          + '（轨迹缺 created_at 时补不出来）'
      }
      return base + '：会话日志未关联'
    }
    // 数据格：值为 null 表示读端拿不到这一格 → 写「本次没记」，不写 0。
    // `missingText` 分两档：没有数据（默认「本次没记」）与**读数有值但读端算不出来**
    // （「不可解读」）。两者不能同形，也不能都写成 0。
    function Cell({ label, value, note, tone, mono, missingText }) {
      const missing = value === null || value === undefined || value === ''
      return React.createElement('div', { style: { minWidth: 0, padding: '3px 0' } },
        React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-tiny)' } }, label),
        React.createElement('div', {
          style: {
            fontSize: 'var(--t-md)', lineHeight: 'var(--lh-base)', wordBreak: 'break-word',
            color: missing ? (missingText === UNREADABLE ? 'var(--d-purple)' : T.text2) : (tone === 'warn' ? T.warn : T.text),
            fontFamily: mono && !missing ? 'var(--font-mono)' : 'inherit',
          },
        }, missing ? (missingText || NOT_RECORDED) : value),
        note ? React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-tiny)', lineHeight: 'var(--lh-base)' } }, note) : null,
      )
    }
    // 五块与累计面板共用的块壳：一行块标题 + 可换行的说明 + 内容
    function Block({ title, accent, right, children }) {
      return React.createElement('div', { style: { marginTop: 10, border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', background: T.bg, overflow: 'hidden' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: T.bg2, flexWrap: 'wrap' } },
          React.createElement('span', { style: { width: 3, height: 13, borderRadius: 2, background: accent || 'var(--acc-blue)', display: 'inline-block' } }),
          React.createElement('span', { style: { fontWeight: 700, fontSize: 'var(--t-md)' } }, title),
          right || null,
        ),
        React.createElement('div', { style: { padding: '6px 10px 9px' } }, children),
      )
    }
    // 统一的折叠块：标题条 + 箭头 + 可选提示。此前各处的"可展开"只是一枚 chip，
    // 读不出它是开关；套娃（details 里再 details）也来自各块各自加壳。
    function Fold({ title, hint, children, compact }) {
      return React.createElement('details', { className: compact ? 'sleu-fold sleu-fold-compact' : 'sleu-fold' },
        React.createElement('summary', null,
          React.createElement('span', null, title),
          hint ? React.createElement('span', { style: { color: T.text2, fontWeight: 400, fontSize: 'var(--t-tiny)' } }, hint) : null),
        React.createElement('div', { className: 'sleu-fold-body' }, children))
    }
    function LineRow({ label, children, title }) {
      return React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 7, marginTop: 4, minWidth: 0 } },
        React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)', minWidth: 64, flexShrink: 0, whiteSpace: 'nowrap' } }, label),
        React.createElement('span', { title: title || '', style: { flex: 1, minWidth: 0, fontSize: 'var(--t-sm)', lineHeight: 'var(--lh-base)', wordBreak: 'break-word', color: T.text } }, children),
      )
    }
    // 缺件卡：读不到生成物/记录时**只报缺哪个文件与重建命令**，不拿别的数据顶上。
    function MissingProduct({ what, path, rebuild, detail, note }) {
      return React.createElement('div', { style: { padding: '8px 10px', background: 'var(--tint-amber)', border: '1px solid ' + T.warn, borderRadius: 'var(--r-sm)', fontSize: 'var(--t-sm)', lineHeight: 'var(--lh-base)', color: T.text } },
        React.createElement('div', { style: { fontWeight: 700, color: T.warn } }, what + '读不到，这一块不可解读'),
        path ? React.createElement('div', { style: { marginTop: 3, color: T.text2 } }, '缺的是：', React.createElement('code', { className: 'sleu-mono', style: { userSelect: 'all' } }, path)) : null,
        detail ? React.createElement('div', { style: { marginTop: 3, color: T.text2 } }, detail) : null,
        rebuild ? React.createElement('code', { style: { display: 'block', marginTop: 5, userSelect: 'all', background: T.bg, border: '1px solid var(--hair)', borderRadius: 'var(--r-xs)', padding: '4px 7px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)', wordBreak: 'break-all' } }, rebuild) : null,
        React.createElement('div', { style: { marginTop: 3, color: T.text2, fontSize: 'var(--t-tiny)' } },
          note || '面板不解析源文件自行求和：这条读数只从生成物读。'),
      )
    }
    // 检索那一块的事实。展开 / 载入正文 / 排除是同一批候选的三个状态，各有出处，不合成一个数：
    //   · 展开     = `considered_candidates`（筛选时看过的候选，含没取全文的），老 trace 只有
    //                `candidates` 时也并进来（那时它同时代表"看过"）
    //   · 载入正文 = `load_full` 的 `candidates`（读了正文的那些）
    //   · 排除     = `excluded_cases` 与 `miss` 的 `excluded_cases`
    // 先验按 id 记三态（命中 / 未命中 / 未查）与消费点（purpose）。
    function retrievalOf(list) {
      const considered = []
      const loaded = []
      const excluded = []
      const refs = {}
      let hitCase = null
      const add = (arr, ids) => { for (const id of (ids || [])) if (id && arr.indexOf(id) < 0) arr.push(id) }
      for (const st of (list || [])) {
        if (!st) continue
        add(considered, st.considered)
        add(considered, st.candidates)
        if (st.action === 'load_full') add(loaded, st.candidates)
        add(excluded, st.excluded)
        if (st.action === 'hit' && st.caseId) hitCase = hitCase || st.caseId
        if (st.action === 'reference_lookup') {
          for (const rid of (st.refs || [])) {
            const r = refs[rid] || (refs[rid] = { id: rid, hit: 0, miss: 0, skipped: 0, purposes: {} })
            if (st.outcome === 'hit' || st.outcome === 'miss' || st.outcome === 'skipped') r[st.outcome]++
            if (st.purpose) r.purposes[st.purpose] = (r.purposes[st.purpose] || 0) + 1
          }
        }
      }
      return {
        considered: considered, loaded: loaded, excluded: excluded,
        refs: Object.keys(refs).sort().map(k => refs[k]), hitCase: hitCase,
      }
    }
    // 各步：步骤名、同批并行的分组、返工标记。
    // 返工的判据只有一条（写在界面上）：同一动作在本单出现多次。并行按事件里的 `parallel_group`：
    // 同一个值 = 同时展开的那几个动作。
    //
    // **每步的成本占比这一格不填。** 会话日志里的工具耗时按 harness 的 `step`（每轮助手消息一个）
    // 计数，轨迹的 `step` 是诊断流程自己的编号，两套编号不同源——按 step 关联出来的"每步耗时"
    // 会把耗时挂到别的动作上，比留空更坏。分步成本在指标清单里也还是蓝图项（缺产出方）。
    function stepsOf(list) {
      const byAction = {}
      const order = []
      for (const st of (list || [])) {
        if (!st || !st.action) continue
        const a = byAction[st.action] || (byAction[st.action] = { action: st.action, n: 0, groups: [] })
        if (order.indexOf(st.action) < 0) order.push(st.action)
        a.n++
        if (st.parallelGroup && a.groups.indexOf(st.parallelGroup) < 0) a.groups.push(st.parallelGroup)
      }
      return order.map(k => ({ action: byAction[k].action, count: byAction[k].n, groups: byAction[k].groups, rework: byAction[k].n > 1 }))
    }

    // 收起态一行的列宽：列头与每一行共用这一份，改一处就同时改两边（分开写必然错位）。
    // 列宽：状态 92 / 会话 1fr / 框架·平台 118 / 事件 58 / 耗时 58 / token 58 / 箭头 16。
    // 固定列合计 400（旧 502），窄面板下 1fr 不再被压成 0；火花线列已移出列表。
    const ROW_COLS = 'var(--row-cols)'

    // 指标带：展开区最上面那一条，横贯整行。
    // 为什么横着铺而不放侧栏：六步成本天生是横向比较（哪一步最高），竖排要上下扫；
    // 表格行展开刚好给了一整行的宽度，侧栏会把它压成缩略图。
    // 指标带 = 三张图，替代原来的四段文字：
    //   ① 六步耗时柱（缺数据的步画虚线空框，不当天花板）② 检索漏斗 ③ token 堆叠条
    // 为什么要图：四段文字里三段的数字本来就是同一批，读者要在脑子里做对比；图把对比直接画出来。
    // 问题背景：trace 的 summary 是一段长文本。直接铺开来是一堵墙，折行又不分段更难看。
    // 这里按句号切段逐段排版，默认只露前 3 行，点开看全文——折叠只影响可见高度，
    // **文字始终是全的**（不是截断）。
    function SummaryText(props) {
      const raw = String(props.text || '')
      const [open, setOpen] = React.useState(false)
      if (!raw) return null
      const parts = []
      let buf = ''
      for (const ch of raw) {
        buf += ch
        if ('。；！\n'.indexOf(ch) >= 0 && buf.trim().length >= 24) { parts.push(buf.trim()); buf = '' }
      }
      if (buf.trim()) parts.push(buf.trim())
      const long = parts.length > 2 || raw.length > 220
      return React.createElement('div', null,
        React.createElement('div', { style: { display: 'grid', gap: 6, maxHeight: (!open && long) ? 78 : 'none', overflow: 'hidden' } },
          parts.map((t, i) => React.createElement('p', {
            key: i, style: { margin: 0, fontSize: 'var(--t-md)', lineHeight: 'var(--lh-base)', color: T.text, wordBreak: 'break-word' },
          }, t))),
        long ? React.createElement('button', {
          type: 'button', onClick: () => setOpen(!open),
          style: { marginTop: 6, padding: 0, background: 'none', border: 'none', cursor: 'pointer', fontSize: 'var(--t-tiny)', color: T.brand, fontWeight: 600 },
        }, open ? '收起' : ('展开全文（共 ' + raw.length + ' 字）')) : null)
    }

    // 指标带 = 三张图，替代原来的四段文字：
    //   ① 六步耗时柱（只有步名与秒数，构成放 tooltip）② 检索路径（四个计数用箭头串起来 + 一句人话结论）
    //   ③ token 四类堆叠条。
    // 排版的取舍：柱下一行只留「步 n 名称」与秒数——一行塞三件事读者就得逐格扫；要更多靠 tooltip。
    function MetricsBand(props) {
      const rec = props.rec || null
      const retr = props.retr || {}
      const STEP_SHORT = { 1: '路由', 2: '键触发', 3: '候选验证', 4: '探询', 5: '深度排查', 6: '结论' }
      const cost = (rec && Array.isArray(rec.stepCost)) ? rec.stepCost : []
      const byStep = {}
      for (const r of cost) byStep[r.step] = r
      const maxMs = Math.max(1, ...cost.map(r => r.ms || 0))
      const total = cost.reduce((a, r) => a + (r.ms || 0), 0)
      const worst = cost.slice().sort((a, b) => (b.ms || 0) - (a.ms || 0))[0]
      const head = (label, note) => React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 8, minWidth: 0 } },
        React.createElement('span', { style: { fontSize: 'var(--t-md2)', color: T.text2, whiteSpace: 'nowrap' } }, label),
        note ? React.createElement('span', { title: note, style: { fontSize: 'var(--t-tiny)', color: T.text2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 } }, note) : null)

      const bars = React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, alignItems: 'end', height: 78 } },
        [1, 2, 3, 4, 5, 6].map(n => {
          const r = byStep[n]
          // 有这一步但没记耗时 → null（虚线 + 「—」）。**不能 `|| 0`**：那是把"没测到"画成"0 秒"。
          const ms = (r && typeof r.ms === 'number') ? r.ms : null
          const h = ms ? Math.max(4, Math.round(ms / maxMs * 100)) : 0
          const t = (r && r.tokens) || {}
          const tok = (t.uncached || 0) + (t.cache_read || 0) + (t.out || 0)
          const tip = ms === null
            ? STEP_SHORT[n] + '：这一步在轨迹里没有事件，本次没记'
            : STEP_SHORT[n] + '\n耗时 ' + msText(ms) + '（窗口内工具调用之和，不含模型思考）'
              + '\n调用 ' + ((r && r.calls) || 0) + ' 次' + (tok ? '\ntoken ' + thousands(tok) : '')
              + ((r && r.tools && r.tools.length) ? '\n工具 ' + r.tools.slice(0, 6).join(' / ') : '')
          return React.createElement('div', { key: n, title: tip, style: { display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%', gap: 4 } },
            React.createElement('div', { style: { height: '100%', display: 'flex', alignItems: 'flex-end', borderRadius: 'var(--r-xs)', overflow: 'hidden',
              background: ms === null ? 'transparent' : 'color-mix(in srgb, ' + T.warn + ' 10%, transparent)',
              border: ms === null ? '1px dashed ' + T.border : 'none' } },
              ms ? React.createElement('i', { style: { display: 'block', width: '100%', height: h + '%', background: 'var(--acc-amber, ' + T.warn + ')', borderRadius: 'var(--r-xs)' } }) : null),
            React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 3, minWidth: 0 } },
              React.createElement('span', { title: STEP_SHORT[n], style: { fontSize: 'var(--t-md2)', color: T.text2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, n + ' ' + STEP_SHORT[n]),
              React.createElement('span', { className: 'sleu-num', style: { marginLeft: 'auto', fontSize: 'var(--t-md2)', color: T.text, whiteSpace: 'nowrap' } }, ms === null ? '—' : msText(ms))))
        }))

      // 检索路径：光画三根条读者不知道在比什么（2 → 2 → 0 尤其费解）。计数 + 箭头 + 一句人话结论，缺一不可。
      const cand = (retr.considered || []).length
      const loaded = (retr.loaded || []).length
      const excluded = (retr.excluded || []).length
      const hit = retr.hitCase ? 1 : 0
      const chip = (label, v, tone) => React.createElement('div', { key: label, style: { display: 'grid', gap: 2, minWidth: 0 } },
        React.createElement('span', { style: { fontSize: 'var(--t-md2)', color: T.text2, whiteSpace: 'nowrap' } }, label),
        React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-lg)', color: tone || T.text, lineHeight: 1.1 } }, String(v)))
      const arrow = (k) => React.createElement('span', { key: k, style: { color: T.text2, fontSize: 'var(--t-sm)', alignSelf: 'end', paddingBottom: 2 } }, '›')
      const verdict = hit
        ? '命中 1 条案例，按它的修复建议走'
        : (cand ? (cand + ' 条候选全部排除 → 转流程深挖') : '轨迹里没有候选记录')
      const funnel = React.createElement('div', null,
        React.createElement('div', { style: { display: 'flex', gap: 6, alignItems: 'flex-end', flexWrap: 'wrap' } },
          chip('候选', cand), arrow('a1'), chip('取全文', loaded), arrow('a2'), chip('排除', excluded), arrow('a3'),
          chip('命中', hit, hit ? 'var(--acc-green, ' + T.success + ')' : T.text2)),
        React.createElement('div', { style: { marginTop: 8, fontSize: 'var(--t-tiny)', color: T.text2, lineHeight: 'var(--lh-base)' } }, verdict))

      // token 条与成本块的四个格同源：诊断窗口内为准；旧格式的明细退到本会话累计并在标题里写明。
      const tkWin = (rec && rec.costWindow && rec.costWindow.tokens) ? rec.costWindow.tokens : null
      const tk = tkWin || ((rec && rec.tokens) ? rec.tokens : null)
      const sum = tk ? (tk.uncached || 0) + (tk.cache_read || 0) + (tk.cache_write || 0) + (tk.out || 0) : 0
      const seg = (v, c) => React.createElement('i', { style: { display: 'block', height: '100%', width: (sum ? v / sum * 100 : 0) + '%', background: c } })
      const tokCell = (label, v, c) => React.createElement('div', { key: label, style: { display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 } },
        React.createElement('i', { style: { width: 7, height: 7, borderRadius: 2, background: c, flex: '0 0 auto' } }),
        React.createElement('span', { style: { fontSize: 'var(--t-md2)', color: T.text2, whiteSpace: 'nowrap' } }, label),
        React.createElement('span', { className: 'sleu-num', style: { marginLeft: 'auto', fontSize: 'var(--t-md2)', color: T.text, whiteSpace: 'nowrap' } }, thousands(v)))

      return React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1.25fr 1fr .95fr', gap: 24, padding: '2px 0 14px', borderBottom: '1px solid ' + T.border } },
        React.createElement('div', { style: { minWidth: 0 } },
          head('每步耗时', total ? ('合计 ' + msText(total) + (worst && worst.ms ? ' · 最长是 ' + worst.step + ' ' + STEP_SHORT[worst.step] : '')) : (rec ? '' : '本机明细未生成')),
          bars,
          React.createElement('div', { style: { marginTop: 8, fontSize: 'var(--t-md2)', color: T.text2, lineHeight: 'var(--lh-base)' } },
            '窗口内工具调用之和，不含模型思考；悬停看每步的次数、token 与工具'),
          // 按工具拆开：只给一个总数，读者判断不出"这几秒该裁哪个动作"。
          // 默认收起——它是"要继续查"时才展开的那一层，不占首屏。
          (function () {
            const rows = []
            for (const r of cost) {
              if (r.windowTruncated) { rows.push([r.step, '收尾段未记（轨迹没有结束标记）', null]); continue }
              for (const t of (r.byTool || [])) if (t.ms || t.pending) rows.push([r.step, t.tool, t, r])
            }
            if (!rows.length) return null
            return React.createElement(Fold, { compact: true, title: '按工具拆开', hint: '每一步的分工具耗时' },
              React.createElement('div', { style: { display: 'grid', gap: 2 } },
                rows.map(([step, label, t, r], i) => React.createElement('div', { key: i, style: { display: 'grid', gridTemplateColumns: '26px 1fr auto', gap: 8, alignItems: 'baseline', fontSize: 'var(--t-md2)' } },
                  React.createElement('span', { style: { color: T.text2 } }, '步 ' + step),
                  React.createElement('span', { title: label, style: { color: T.text2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, label),
                  React.createElement('span', { className: 'sleu-num', style: { color: T.text, whiteSpace: 'nowrap' } },
                    t ? ((t.ms || 0) + ' ms · ' + t.calls + ' 次' + (t.pending ? ' · ' + t.pending + ' 未返回' : '')) : '')))))
          })()),
        React.createElement('div', { style: { minWidth: 0 } }, head('检索路径', ''), funnel),
        React.createElement('div', { style: { minWidth: 0 } },
          head(tkWin ? 'token（诊断窗口内）' : (tk ? 'token（整条会话）' : 'token'), sum ? thousands(sum) : ''),
          React.createElement('div', { style: { display: 'flex', height: 14, borderRadius: 2, overflow: 'hidden', background: 'var(--hair)' } },
            seg(tk ? tk.cache_read : 0, 'var(--acc-amber, ' + T.warn + ')'),
            seg(tk ? tk.uncached : 0, T.brand),
            seg(tk ? tk.cache_write : 0, 'var(--d-purple, #7c3aed)'),
            seg(tk ? tk.out : 0, 'var(--acc-red, ' + T.error + ')')),
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 14px', marginTop: 8 } },
            tokCell('缓存读', tk ? tk.cache_read : 0, 'var(--acc-amber, ' + T.warn + ')'),
            tokCell('未缓存', tk ? tk.uncached : 0, T.brand),
            tokCell('缓存写', tk ? tk.cache_write : 0, 'var(--d-purple, #7c3aed)'),
            tokCell('输出', tk ? tk.out : 0, 'var(--acc-red, ' + T.error + ')'))))
    }

    const SessionCard = React.memo(function SessionCardInner(props) {
      const s = props.session
      const ownerSessionId = props.sessionId
      const onRebuilt = props.onRebuilt
      // 批量闭环多选：只在「待升格」筛选下出现（勾选只在那一屏有意义）。
      const selectable = !!props.selectable
      const selected = !!props.selected
      const onToggleFile = props.onToggleFile
      const [open, setOpen] = React.useState(false)
      const [steps, setSteps] = React.useState(null)
      const [detailAt, setDetailAt] = React.useState(0)   // 最近一次取到轨迹的时间（缓存新鲜度）
      const [showCmd, setShowCmd] = React.useState(false)
      // 动作组（收尾 / 交接包）同一时刻只开一个，且**在按钮行下方**展开：
      // 早先把它们做成行内 <details>，展开时同一行的兄弟按钮会被挤走（实测反馈）。
      const [menuOpen, setMenuOpen] = React.useState(null)
      const [copied, setCopied] = React.useState(null)
      const [copyFailKey, setCopyFailKey] = React.useState(null)
      const [evOpen, setEvOpen] = React.useState(null)
      const [tcOpen, setTcOpen] = React.useState(null)   // 关联面：展开哪一步的工具调用清单
      const [opening, setOpening] = React.useState(null)
      // 「打开会话」失败的那句话（成功会切走，不需要回显）
      const [navErr, setNavErr] = React.useState(null)
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
      // 本机明细重建（成本窗口）：旧格式明细没有 cost.window，打开卡片时自动重建一次；
      // 按钮可手动重试。`rebuildTried` 记「这一单已经自动试过」，防止失败后无限重试。
      const [rebuild, setRebuild] = React.useState(null)       // {state:'running'|'done'|'error', msg}
      const [rebuildTried, setRebuildTried] = React.useState(null)
      const vocabStatus = (VOCAB_CACHE && Array.isArray(VOCAB_CACHE.statuses))
        ? VOCAB_CACHE.statuses.filter(x => x.value === s.status)[0] : null
      const meta = (s.state && s.state.displayTone)
        ? { label: vocabStatus ? vocabStatus.label : String(s.status || '状态未记录'),
            color: s.state.displayTone.color, acc: s.state.displayTone.accent }
        : (statusMeta[s.status] || statusMeta.unknown)
      const canResume = vocabStatus ? !!vocabStatus.resumable : !!RESUMEABLE[s.status]
      const st = s.state || null
      const [stEdit, setStEdit] = React.useState({ action: '', kind: '', handed: '', dup: '', msg: '' })
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
      // 有结论步时不再提示：原先只看 status，结论步存在也照喊"还没有定位结论"。
      const noConclusionHint = (steps && steps.list && steps.list.length && shownIdx.at < 0 && s.status !== 'resolved')
        ? React.createElement('div', { style: { marginTop: 12, padding: 8, border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', fontSize: 'var(--t-sm)', color: T.text2 } },
            '本单还没有定位结论（轨迹末条是过程记录）。点「看完整轨迹」看全部事件，或等诊断收尾时补一条结论。')
        : null

      // 取轨迹详情。quiet = true 时**不显示骨架**：收起再展开先用上次结果渲染，再后台刷新，
      // 避免每次展开都"骨架闪一下 → 长高一次"（一次点击两段跳，实测反馈）。
      function loadDetail(quiet) {
        if (!quiet) setSteps({ loading: true })
        host.call('ascend-traces-detail', { sessionId: ownerSessionId || null, traceFile: s.file })
          .then(r => {
            setDetailAt(Date.now())
            setSteps({ loading: false, list: r && r.ok ? r.steps : [], summary: r && r.summary, refCount: r && r.refCount, sedimented: r && r.sedimented, sedimentCandidates: r && r.sedimentCandidates, conclusionIndex: r && typeof r.conclusionIndex === 'number' ? r.conclusionIndex : -1, parseAnomaly: r && r.parseAnomaly, record: r && r.record, recordPath: r && r.recordPath, recordRebuild: r && r.recordRebuild, recordMissing: r && r.recordMissing, recordError: r && r.recordError, recordMissingProduct: r && r.recordMissingProduct, caseMeta: r && r.caseMeta, sedimentMeta: r && r.sedimentMeta, stopReason: r && r.stopReason, error: r && r.error })
            // 旧格式明细（有本会话累计、没有 cost.window）→ 自动重建一次，读者不必记命令。
            // 只重建「打开的这一单」：全量重建要跑几十秒（单会话实测 ≈4 s），不适合在加载时做。
            const rec = r && r.ok ? r.record : null
            if (rec && rec.tokens && !rec.costWindow && rebuildTried !== s.sessionId) {
              setRebuildTried(s.sessionId)
              doRebuild(true)
            }
          })
          .catch(e => setSteps({ loading: false, list: [], error: 'RPC 失败: ' + String(e && e.message || e) }))
      }
      // 重建本机明细：只写 gitignored 的 metrics/entry-activity.local/（host 侧走 --local-only），
      // 不写周增量行、不动共享游标。成功后重新取详情——窗口那一栏就齐了。
      function doRebuild(auto) {
        setRebuild({ state: 'running', msg: auto ? '正在自动重建本机明细…' : '正在重建本机明细…' })
        host.call('ascend-rebuild-local', { sessionId: s.sessionId })
          .then(r => {
            if (r && r.ok) {
              setRebuild({ state: 'done', msg: '本机明细已重建' })
              loadDetail(true)
              // 列表的耗时 / token 两列也读这份明细：重建后重取，别让它们停在上一次的值
              if (typeof onRebuilt === 'function') onRebuilt()
            } else {
              setRebuild({ state: 'error', msg: (r && r.error) ? String(r.error) : '重建失败（无返回）', manual: r && r.manual })
            }
          })
          .catch(e => setRebuild({ state: 'error', msg: 'RPC 失败: ' + String(e && e.message || e) }))
      }
      function toggle() {
        // 收起时**保留** steps：下次展开直接用缓存渲染，再后台刷新（见 loadDetail 的 quiet）。
        if (open) { setOpen(false); setEvOpen(null); setTcOpen(null); return }
        setOpen(true)
        // 缓存 60 秒内不重取：每次展开都发 RPC，回来的 setSteps 正好落在动画中途，
        // 整棵展开子树重渲染一次——这是"点开一顿"的主要来源。
        const cached = !!(steps && steps.list)
        const fresh = cached && (Date.now() - detailAt < 60000)
        if (fresh) return
        if (!cached) { loadDetail(false); return }
        // 过期缓存：先让动画跑完（180ms）再后台刷新，避免中途重渲染。
        if (timer && typeof timer.timeout === 'function') timer.timeout(() => loadDetail(true), 200)
        else loadDetail(true)
      }
      // 复制反馈：按目标记失败（不再把任意一处失败渲染成全局 'fail'），2 秒后自己复位。
      function doCopy(txt, key) {
        copyText(txt).then(ok => {
          setCopied(ok ? key : null)
          setCopyFailKey(ok ? null : key)
          if (timer && typeof timer.timeout === 'function') timer.timeout(() => { setCopied(null); setCopyFailKey(null) }, 2000)
        })
      }
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
          style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 'var(--r-pill)', padding: '0 8px', fontSize: 'var(--t-tiny)', cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' },
        }, copied === 'link:' + f ? '已复制' : '复制链接')
        if (openErr && openErr.at === f) {
          return React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', minWidth: 0 } },
            React.createElement('span', { style: { color: T.warn, fontSize: 'var(--t-tiny)' } }, openErr.msg), copyBtn)
        }
        if (openDone && openDone.at === f) {
          return React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement('span', { style: { color: T.success, fontSize: 'var(--t-tiny)' } },
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
        { title: tip || '', style: { color: T.text2, fontSize: 'var(--t-sm)', minWidth: 52, flexShrink: 0 } }, text)
      // 候选行：kind 徽标 + 一句话（超长省略，全文在 title）；只有先验候选带独立入口。
      // key 用候选在 cands 里的**原下标**，避免过滤后错位。
      const candRow = (c, ci, withAction) => {
        const key = 'cand:' + ci
        return React.createElement('div', { key: key, style: { display: 'flex', alignItems: 'center', gap: 6, marginLeft: 60, marginTop: 5, minWidth: 0 } },
          React.createElement('span', { style: tinyBadge(c.kind === 'reference' ? 'var(--d-purple)' : 'var(--d-green)') }, c.kind || '?'),
          React.createElement('span', { title: c.summary || '', style: { flex: 1, minWidth: 0, color: T.text, fontSize: 'var(--t-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, c.summary || '(无摘要)'),
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
      // ── 单次诊断的五块（设计文档 3.7）────────────────────────────────────────
      // 五块都在展开态：结论（会话号 / 最终状态 / 结论强度档 / 根因 / 命中案例与分数 /
      // 沉淀到哪个案例 / 回报状态）、各步、检索、成本、本次没记。
      // 轨迹给的是过程事实，本机明细（metrics/entry-activity.local/<会话>.yaml）给的是成本、
      // 强度档与每步耗时；明细读不到时缺件的那几格写「本次没记」并给重建命令。
      const d5Rec = (steps && steps.record) ? steps.record : null
      const d5Retr = retrievalOf(steps && steps.list)
      const d5StepRows = stepsOf(steps && steps.list)
      // 两个 id 分开存：`hit` 事件命中的案例（阶段一）与 `active_case`（最终定位）不是同一件事，
      // 同格显示会让读者在"上面写没命中、下面却有 id"之间对不上。
      const d5HitCaseId = (d5Rec && d5Rec.hitCase) || d5Retr.hitCase || null
      const d5FinalCaseId = (caseKindOf(s) === 'case' ? s.activeCase : null) || null
      const d5SedId = (d5Rec && d5Rec.sedimented && d5Rec.sedimented.caseId) || (sed && (sed.caseId || sed.case_id)) || null
      const d5SedState = (d5Rec && d5Rec.sedimented && d5Rec.sedimented.state) || sedState || null
      const d5FbOutcome = (d5Rec && d5Rec.feedback && d5Rec.feedback.outcome) || s.feedback || null
      // 占位串 `pending-investigation` 不是 case id：挂成"回报状态 pending（pending-investigation）"
      // 会让读者以为有个 fix 等着验证（卡片收起态与 resume 都按同一口径处理过）
      const d5FbCase = s.feedbackCase
        || ((d5Rec && d5Rec.feedback && d5Rec.feedback.case && d5Rec.feedback.case !== 'pending-investigation')
          ? d5Rec.feedback.case : null)
      const d5RootCause = (function () {
        // 根因一句话：取定位结论那条事件的正文首句（它就是要交付的结论本身）。
        // 没有结论事件时不拿别的字段顶替，写「本次没记」。
        const txt = conclusionStep ? String(conclusionStep.output || conclusionStep.content || '') : ''
        const line = txt.split(/\r?\n/).map(x => x.trim()).filter(Boolean)[0] || ''
        if (!line) return null
        return line.length > 120 ? line.slice(0, 120) + '…' : line
      })()
      const d5StrengthLabel = d5Rec && d5Rec.strength ? (STRENGTH_LABELS[d5Rec.strength] || d5Rec.strength) : null
      const d5MetaOf = (m) => (m && m.score !== null && m.score !== undefined) ? '分数 ' + m.score : null
      const d5Conclusion = React.createElement(Block, {
        title: '本次结论', accent: 'var(--acc-green)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, '数据来自轨迹与本机明细'),
      },
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
          React.createElement(Cell, { label: '会话号', value: s.sessionId, mono: true }),
          React.createElement(Cell, { label: '最终状态', value: (statusMeta[s.status] || statusMeta.unknown).label + '（' + s.status + '）' }),
          React.createElement(Cell, {
            label: '结论强度档',
            value: d5Rec && d5Rec.strength ? d5StrengthLabel + '（' + d5Rec.strength + '）' : null,
            note: d5Rec && d5Rec.strength === 'self-report' ? '自证：这条结论由来源会话自己回报，与确定性读数不同权' : null,
          }),
          React.createElement(Cell, { label: '回报状态', value: d5FbOutcome ? (d5FbOutcome + (d5FbCase ? '（' + d5FbCase + '）' : '')) : null }),
        ),
        // 自证单独一个徽标：它不能和确定性读数混着读（同一句话在结论块的注里也写了一次）
        d5Rec && d5Rec.strength === 'self-report' ? React.createElement('div', { style: { marginTop: 5 } },
          React.createElement('span', { style: tinyBadge('var(--d-purple)'), title: '结论强度档的 self-report：来源会话自证，与确定性读数不同权' }, '自证')) : null,
        React.createElement(LineRow, { label: '根因' }, d5RootCause || (conclusionStep ? NOT_RECORDED : '还没有结论事件（这单没收尾）')),
        // 阶段一命中与最终定位是两件事（命中 A 最终沉淀成 B 是真实情形），所以分两行写，
        // 不要挤成一格——读者会拿"命中"判知识覆盖，混着写会判错。
        React.createElement(LineRow, { label: '命中案例（hit）', title: steps && steps.caseMeta && steps.caseMeta.title },
          d5HitCaseId
            ? React.createElement(React.Fragment, null,
                React.createElement('code', { className: 'sleu-mono', style: { color: T.success } }, d5HitCaseId),
                d5HitCaseId === d5FinalCaseId && steps && steps.caseMeta && steps.caseMeta.title ? ' ' + steps.caseMeta.title : '',
                d5HitCaseId === d5FinalCaseId && d5MetaOf(steps && steps.caseMeta) ? '（' + d5MetaOf(steps.caseMeta) + '）' : '')
            : React.createElement('span', { style: { color: T.text2 } }, '本单没有命中案例')),
        React.createElement(LineRow, { label: '最终定位', title: 'trace 的 active_case：这一单最后定位到的案例，可能与阶段一命中的不是同一条' },
          d5FinalCaseId
            ? React.createElement('code', { className: 'sleu-mono', style: { color: T.text2 } }, d5FinalCaseId)
            : React.createElement('span', { style: { color: T.text2 } }, '没有对应案例')),
        React.createElement(LineRow, { label: '沉淀到', title: steps && steps.sedimentMeta && steps.sedimentMeta.title },
          d5SedId
            ? React.createElement(React.Fragment, null,
                React.createElement('code', { className: 'sleu-mono', style: { color: T.text2 } }, d5SedId),
                '（' + ((sedMeta[d5SedState || sedState] || sedMeta.none).label) + '）',
                steps && steps.sedimentMeta && steps.sedimentMeta.title ? ' ' + steps.sedimentMeta.title : '',
                d5MetaOf(steps && steps.sedimentMeta) ? '（' + d5MetaOf(steps.sedimentMeta) + '）' : '')
            : React.createElement('span', { style: { color: T.text2 } }, (sedMeta[d5SedState || sedState] || sedMeta.none).label)),
        React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 'var(--t-tiny)' } },
          '分数由 scripts/score_entries.py 现算并写进索引生成物（记录计数与冷启动先验合成），案例文件里没有这一项。'),
      )
      const d5Steps = React.createElement(Block, {
        title: '各步', accent: 'var(--acc-blue)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, '按轨迹里的动作聚合'),
      },
        d5StepRows.length
          ? React.createElement('div', null, d5StepRows.map(r => React.createElement('div', {
              key: r.action,
              style: { display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4, flexWrap: 'wrap' },
            },
              React.createElement('span', { title: r.action, style: { fontSize: 'var(--t-sm)', fontWeight: 600, minWidth: 96 } }, STEP_LABELS[r.action] || r.action),
              React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-sm)', color: T.text2, minWidth: 44 } }, r.count + ' 次'),
              React.createElement('span', { style: { fontSize: 'var(--t-sm)', color: T.text2, minWidth: 96 } }, '耗时占比：' + NOT_RECORDED),
              r.groups.length ? React.createElement('span', { style: tinyBadge('var(--d-blue)'), title: '同批并行标记（trace 的 parallel_group）：同一个值表示这几个动作是一起展开的' }, '同批 ' + r.groups.join('/')) : null,
              r.rework ? React.createElement('span', { style: tinyBadge('var(--d-amber)'), title: '返工标记：同一个动作在本单出现多次（判据只有这一条）' }, '重复 ' + r.count + ' 次') : null,
            )))
          : React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-sm)' } }, '轨迹里没有带动作名的事件'),
        React.createElement('div', { style: { marginTop: 5, color: T.text2, fontSize: 'var(--t-tiny)', lineHeight: 'var(--lh-base)' } },
          '同批并行按事件的 parallel_group 分组；返工标记按"同一动作在本单出现多次"判。'
          + '每步的耗时占比这一格没有产出方：会话日志里的工具耗时按 harness 的 step 计数，与轨迹的 step 不是同一套编号，'
          + '两者直接关联会把耗时挂到别的步骤上。'),
      )
      const d5RefTotal = d5Retr.refs.reduce((a, r) => a + r.hit + r.miss + r.skipped, 0)
      // 候选事件是否出现过：一次都没有时，"展开 0 条"与"这份轨迹不记候选"长得一样，
      // 所以整块改说"轨迹里没有候选事件"，不逐格写 0。
      // 只算**真的写了候选清单**的事件：`load_index` / `miss` 事件常常只记命名空间或理由、
      // 不列候选，把它们算作"有候选事件"会让"展开 0 条"看起来像一次读了零个候选。
      const d5HasCandEvents = (steps && steps.list ? steps.list : []).some(st => st && (
        (st.candidates && st.candidates.length) || (st.considered && st.considered.length)
        || (st.excluded && st.excluded.length)))
      const d5Retrieval = React.createElement(React.Fragment, null,
        d5HasCandEvents
          ? React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
              React.createElement(Cell, { label: '展开候选', value: d5Retr.considered.length ? d5Retr.considered.length + ' 条' : '0 条' }),
              React.createElement(Cell, { label: '载入正文', value: d5Retr.loaded.length ? d5Retr.loaded.length + ' 条' : '0 条' }),
              React.createElement(Cell, { label: '排除', value: d5Retr.excluded.length ? d5Retr.excluded.length + ' 条' : '0 条' }),
              React.createElement(Cell, { label: '命中（hit 事件）', value: d5HitCaseId, mono: true, missingText: '没有命中' }),
              React.createElement(Cell, { label: '最终定位', value: d5FinalCaseId, mono: true, missingText: '没有对应案例' }),
            )
          : React.createElement(LineRow, { label: '候选' }, React.createElement('span', { style: { color: T.text2 } }, '轨迹里没有候选清单（没有 candidates / considered_candidates / excluded_cases 记录）')),
        d5Retr.excluded.length ? React.createElement(LineRow, { label: '被排除的' },
          d5Retr.excluded.map(id => React.createElement('code', { key: id, className: 'sleu-mono', style: { marginRight: 8, color: T.text2 } }, id))) : null,
        d5RefTotal
          ? React.createElement(LineRow, { label: '先验三态' },
              d5Retr.refs.map(r => React.createElement('span', { key: r.id, style: { marginRight: 10 } },
                React.createElement('code', { className: 'sleu-mono', style: { color: 'var(--d-purple)' } }, r.id),
                ' 命中 ' + r.hit + ' / 未命中 ' + r.miss + ' / 未查 ' + r.skipped)))
          : React.createElement(LineRow, { label: '先验三态' }, React.createElement('span', { style: { color: T.text2 } }, NOT_RECORDED + '：本单没有 reference_lookup 事件')),
        d5RefTotal ? React.createElement(LineRow, { label: '消费点' },
          (function () {
            const p = {}
            for (const r of d5Retr.refs) for (const k of Object.keys(r.purposes)) p[k] = (p[k] || 0) + r.purposes[k]
            const keys = Object.keys(p)
            return keys.length ? keys.map(k => (PURPOSE_LABELS[k] || k) + ' ' + p[k]).join(' · ') : NOT_RECORDED
          })()) : null,
        React.createElement('div', { style: { marginTop: 5, color: T.text2, fontSize: 'var(--t-tiny)', lineHeight: 'var(--lh-base)' } },
          '展开 = 筛选时看过的候选（considered_candidates）；载入正文 = load_full 取过全文的候选；'
          + '排除 = excluded_cases。三者是同一批候选的三个状态。'),
      )
      // 成本：只报诊断窗口内的数。旧格式的明细只有本会话累计——同一段对话里做过两单时
      // 两份累计一模一样，把那种数当单次成本显示，读者会得出「两次诊断一样贵」的错结论。
      const d5Win = d5Rec && d5Rec.costWindow ? d5Rec.costWindow : null
      const d5TokSession = d5Rec && d5Rec.tokens ? d5Rec.tokens : null
      const d5Tok = d5Win && d5Win.tokens ? d5Win.tokens : null
      // 旧格式的明细没有窗口：四个 token 格退到本会话累计，并在下面一行写明
      const d5TokShown = d5Tok || d5TokSession
      const d5Acct = d5Rec && d5Rec.indexRead ? d5Rec.indexRead : null
      const d5Slowest = d5Win ? d5Win.slowest : (d5Rec && d5Rec.toolSlowest ? d5Rec.toolSlowest : null)
      const d5WinSpan = (d5Win && typeof d5Win.from === 'number' && typeof d5Win.to === 'number')
        ? (fmtEpoch(d5Win.from) + ' → ' + fmtEpoch(d5Win.to)) : null
      const d5Ms = (v) => (typeof v === 'number' ? msText(v) : NOT_RECORDED)
      const d5TokTotal = (d5TokSession || d5Tok)
        ? ((d5TokSession || d5Tok).uncached || 0) + ((d5TokSession || d5Tok).cache_read || 0)
          + ((d5TokSession || d5Tok).cache_write || 0) + ((d5TokSession || d5Tok).out || 0)
        : null
      const d5Cost = React.createElement(React.Fragment, null,
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
          TOKEN_LABELS.map(pair => React.createElement(Cell, {
            key: pair[0], label: pair[1],
            value: d5TokShown && d5TokShown[pair[0]] !== null && d5TokShown[pair[0]] !== undefined ? thousands(d5TokShown[pair[0]]) : null,
            mono: true,
          })),
        ),
        React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 'var(--t-tiny)', lineHeight: 'var(--lh-base)' } },
          d5Win
            ? ('上面四个 token 数是诊断窗口' + (d5WinSpan ? ' ' + d5WinSpan + ' ' : ' ') + '内的用量。'
                + '左边界取轨迹的 created_at，这一单若在它之前已经开始动作，那部分不计入；'
                + '右边界' + (d5Win.truncated ? '取 updated_at（这单没写 ended_at），之后可能还有诊断之外的活' : '取 ended_at')
                + '。所以这是下限，不是完整成本。')
            : (d5TokSession
                ? '上面四个 token 数是本会话累计：本机明细是旧格式，没有按诊断窗口切，看不出这一单花了多少。'
                  + '打开这一单会自动重建一次；仍失败时见下面「本机明细」一行给出的原因。'
                : '')),
        React.createElement(LineRow, { label: '工具耗时' },
          d5Win
            ? ('总计 ' + (d5Win.msComplete === false ? '≥ ' : '') + d5Ms(d5Win.ms)
                + '（' + (d5Win.calls === null ? '?' : d5Win.calls) + ' 次调用'
                + (d5Win.failures ? '，失败 ' + d5Win.failures + ' 次' : '')
                + (d5Win.pending ? '，' + d5Win.pending + ' 次没返回' : '') + '）')
            : (d5Rec
                ? (d5Rec.toolTotalMs !== null
                    ? ('本会话累计 ' + msText(d5Rec.toolTotalMs) + '（' + d5Rec.toolCallCount + ' 次调用）——不是这一单')
                    : NOT_RECORDED + '：会话日志未关联，逐次耗时不在轨迹里')
                : NOT_RECORDED)),
        (d5Win && d5Win.outsideCalls)
          ? React.createElement(LineRow, { label: '窗口外' },
              d5Win.outsideCalls + ' 次调用 / ' + d5Ms(d5Win.outsideMs || 0) + '，不在本单窗口内，不计入本单')
          : null,
        (d5Win && d5Win.longCalls)
          ? React.createElement(LineRow, { label: '长调用' },
              d5Win.longCalls + ' 次墙钟超过 ' + Math.round((d5Win.longThresholdMs || 600000) / 60000) + ' 分钟，合计 ' + d5Ms(d5Win.longMs || 0)
              + '——多半是机器休眠或应用关着，不是工具真跑了这么久')
          : null,
        d5Slowest ? React.createElement(LineRow, { label: '最慢一次' },
          msText(d5Slowest.ms) + ' · ' + (d5Slowest.tool || '工具名未记') + (d5Slowest.args ? ' · ' + d5Slowest.args : '')) : null,
        (d5Win && d5TokSession)
          ? React.createElement(LineRow, { label: '本会话累计（对照）' },
              '工具耗时 ' + d5Ms(d5Rec.toolTotalMs) + '（' + d5Rec.toolCallCount + ' 次调用）· 四类 token ' + thousands(d5TokTotal || 0)
              + '，含同一会话里的其它工作')
          : null,
        // 旧格式明细：打开卡片时已自动重建一次；这里给按钮重试，并把失败原因就地显示。
        ((d5Rec && d5TokSession && !d5Win) || rebuild)
          ? React.createElement(LineRow, { label: '本机明细' },
              React.createElement('span', { style: { display: 'inline-flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' } },
                React.createElement('span', { style: { color: rebuild && rebuild.state === 'error' ? T.error : T.text2 } },
                  rebuild ? rebuild.msg : '旧格式（没有诊断窗口），打开时会自动重建一次'),
                (rebuild && rebuild.state === 'running') ? null
                  : React.createElement('button', {
                      onClick: () => doRebuild(false),
                      style: btnGhost,
                      title: '只重建本机明细（运行时数据，不入 git；不写周增量行、不动游标）',
                    }, rebuild && rebuild.state === 'error' ? '重试'
                      : (rebuild && rebuild.state === 'done' ? '再重建一次' : '重建这一单的本机明细')),
                (rebuild && rebuild.state === 'error' && rebuild.manual
                  && String(rebuild.msg || '').indexOf(rebuild.manual) < 0)
                  ? React.createElement('code', { className: 'sleu-mono', style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, rebuild.manual)
                  : null))
          : null,
        React.createElement('div', { style: { marginTop: 6, color: T.text2, fontSize: 'var(--t-tiny)' } }, '一次诊断的读入账（按视图现算，四个分项）'),
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
          ACCT_LABELS.map(pair => React.createElement(Cell, {
            key: pair[0], label: pair[1],
            value: d5Acct && d5Acct[pair[0]] !== null && d5Acct[pair[0]] !== undefined ? thousands(d5Acct[pair[0]]) + ' 字' : null,
            mono: true,
          })),
        ),
      )
      const d5Missing = (steps && steps.recordMissing) ? steps.recordMissing.slice() : []
      const d5NotRecorded = React.createElement(Block, {
        title: '本次没记', accent: 'var(--acc-gray)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } },
          d5Missing.length ? d5Missing.length + ' 项没有数据'
            : ((steps && steps.recordMissingProduct) ? '明细整份未生成' : '没有缺项')),
      },
        steps && steps.recordMissingProduct
          ? React.createElement(MissingProduct, {
              what: '单次诊断记录（' + ((steps && steps.recordPath) || 'metrics/entry-activity.local/<会话>.yaml') + '）',
              path: steps.recordPath, rebuild: steps.recordRebuild, detail: steps.recordError,
              note: '面板不从轨迹替这份明细推成本与结论强度档：那两项只能由汇总脚本写进明细。',
            })
          : null,
        (steps && steps.recordMissingProduct)
          ? React.createElement('div', null, [
              '结论强度档（strength）',
              '四类 token 与逐次工具调用耗时（cost.tokens / tool_calls）',
              '一次诊断的读入账（cost.index_read_tok）',
            ].map((m, i) => React.createElement('div', {
              key: i, style: { fontSize: 'var(--t-sm)', color: T.text2, lineHeight: 'var(--lh-base)', marginTop: 3 },
            }, '· ' + m + '：只在单次诊断记录里，明细未生成时读不到')))
          : (d5Missing.length
              ? React.createElement('div', null, d5Missing.map((m, i) => React.createElement('div', {
                  key: i, style: { fontSize: 'var(--t-sm)', color: T.text2, lineHeight: 'var(--lh-base)', marginTop: 3 },
                }, '· ' + m)))
              : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2 } }, '这一单该记的字段都有数据。')),
        React.createElement('div', { style: { marginTop: 5, color: T.text2, fontSize: 'var(--t-tiny)', lineHeight: 'var(--lh-base)' } },
          '读数有值但读端算不出来的归「不可解读」，不列在这里。'),
      )

      // 检索明细：图上只有三个数，具体候选 id / 被排除的 / 先验三态与消费点在这里，默认收起。

      // 指标带 = 三张图（六步柱 / 检索漏斗 / token 条）。它替代了原来「各步」「检索」两块文字：
      // 那两块的信息被图吸收，重复才是密度高的根源。
      const band = (open && steps && steps.list && steps.list.length)
        ? React.createElement(MetricsBand, { rec: steps.record || null, retr: d5Retr })
        : null
      let body = null
      if (open) {
        if (steps && steps.loading) body = React.createElement('div', { style: { padding: 10 } }, reportBlock,
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 12 } },
            [0, 1, 2, 3].map(i => React.createElement('div', { key: i, className: 'sleu-skel', style: { height: 34 } }))),
          [0, 1, 2].map(i => React.createElement('div', { key: 's' + i, className: 'sleu-skel', style: { height: 28, marginBottom: 8 } })))
        else if (steps && steps.list && steps.list.length) {
          body = React.createElement('div', null,
            steps.summary ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.brand + ' 6%, transparent)', border: '1px solid ' + T.border, borderRadius: 'var(--r-md)' } },
              React.createElement(SectionLabel, { color: T.brand }, '问题背景'),
              React.createElement(SummaryText, { text: steps.summary }),
            ) : null,
            d5Conclusion,
            // 「各步」与指标带的六步柱是同一批数：柱图已经画了耗时与调用，再铺一遍只会互相矛盾
            // （旧版每行还写「耗时占比：本次没记」，紧接上方写着合计 10.0s）。
            // 「检索」保留，但折成明细——图给的是 展开→载入→命中 三个数，这里给的是具体 id 与先验三态。
            // 检索明细与成本沉成可展开块：这两块是回查用的，不该占首屏。
            React.createElement(Fold, { title: '检索明细', hint: '候选 id / 被排除的 / 先验三态与消费点' }, d5Retrieval),
            React.createElement(Fold, { title: '成本与 token', hint: d5Rec ? '四类 token、读入账、最慢一次' : '本机明细未生成' }, d5Cost),
            // —— 沉淀区：case 与先验候选**分家**（2026-09 重做，修两个实测误读）——
            // ① 引用计数不再贴在这里：`reference N 次` 是"用了几次"，与"沉淀了几条"无关，
            //    贴在沉淀块正上方正是误读的来源；它已移到轨迹标题行（那里才是它的出处）。
            // ② 两段各带自己的入口：case 段给 to-postmortem 指令，先验段每条给 to-reference 指令。
            React.createElement('div', { style: { marginBottom: 10, border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', background: T.bg, overflow: 'hidden' } },
              React.createElement('div', { style: { padding: '8px 10px' } },
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
                  sedLabel('本单沉淀'),
                  React.createElement('span', { style: { color: sedInfo.color, fontWeight: 600, fontSize: 'var(--t-sm)' } }, sedInfo.label),
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
                React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 'var(--r-xs)', padding: '5px 8px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)', color: T.text, wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } },
                  sedCmdText),
                React.createElement('button', { onClick: () => doCopy(sedCmdText, 'sed'), style: copyFailKey === 'sed' ? btnRed : btnPurple },
                  copied === 'sed' ? '已复制' : (copyFailKey === 'sed' ? '失败' : '复制')),
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
              const STEP_PREVIEW = 3
              const visible = showAllSteps ? shown : shown.slice(0, STEP_PREVIEW)
              const moreSteps = shown.length - visible.length
              return React.createElement('div', null,
                React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
                  React.createElement('span', { style: { fontSize: 'var(--t-sm)', color: T.text2 } },
                    fullTrace
                      ? '完整轨迹（' + all.length + ' 条原始事件，含推理与记录维护动作）'
                      : ('诊断轨迹：' + shown.length + ' 步' + (anomaly ? '（可能不完整）' : '')
                        + (hidden ? '（已收起 ' + hidden + ' 条记录维护动作）' : ''))),
                  // 引用计数归这里：它是 trace 事件的统计（reference_lookup 的条数），
                  // 与卡上任何一块"沉淀"都不是一回事——放沉淀块旁边会被读成"reference 也沉淀了"。
                  steps.refCount > 0 ? React.createElement('span', {
                    title: 'trace 里取用先验知识的次数（reference_lookup 事件条数）——这是"用了几次"，不是"沉淀了几条"',
                    style: { display: 'flex', alignItems: 'center', gap: 4, fontSize: 'var(--t-tiny)', color: T.text2 },
                  },
                    React.createElement(Dot, { color: 'var(--acc-purple)' }),
                    '先验引用 ' + steps.refCount + ' 次') : null,
                  React.createElement('button', { type: 'button', className: 'sleu-chip', onClick: () => setFullTrace(!fullTrace), style: btnGhost },
                    fullTrace ? '只看诊断' : '看完整轨迹'),
                ),
                // 轨迹解析没收下的行：**必须说出来**。少了事件而看不出来是最坏的一种——
                // 读者会按上面那行"诊断轨迹：N 步"当成事实（实测症状：文件里 9 条、面板上 1 条，
                // 文件本身完全正常）。这里给出成因与行号，让读者能自己去核对那几行。
                anomaly ? React.createElement('div', { style: { marginBottom: 8, padding: '7px 10px', background: 'color-mix(in srgb, ' + T.warn + ' 10%, transparent)', border: '1px solid color-mix(in srgb, ' + T.warn + ' 45%, transparent)', borderRadius: 'var(--r-md)', fontSize: 'var(--t-sm)', color: T.text, lineHeight: 'var(--lh-base)' } },
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
                    style: { background: 'color-mix(in srgb, ' + colorVar + ' 12%, transparent)', color: colorVar, borderRadius: 'var(--r-xs)', padding: '1px 7px', fontSize: 'var(--t-tiny)', fontFamily: 'var(--font-mono)', fontWeight: 600, whiteSpace: 'nowrap' },
                  }, text)
                  const assocRow = (key, label, children) => React.createElement('div', {
                    key: key, style: { display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap', marginTop: 5 },
                  },
                    React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)', minWidth: 28, flexShrink: 0 } }, label),
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
                        .concat(c.rest > 0 ? [React.createElement('span', { key: 'more', style: { color: T.text2, fontSize: 'var(--t-tiny)' } }, '等 ' + c.rest + ' 条')] : [])))
                  }
                  if (st.action === 'external_lookup') {
                    const capLabel = CAPABILITY_LABELS[st.capability] || st.capability || '外部查证'
                    const outLabel = st.outcome ? ((REF_OUTCOME[st.outcome] || {}).label || st.outcome) : '未记结果'
                    assocRows.push(assocRow('ext', '外部', [
                      assocChip(capLabel, 'var(--d-purple)', '外部查证的能力面（trace 的 capability）'),
                      assocChip('结果：' + outLabel, 'var(--d-gray, var(--c-gray))', 'trace 的 external_lookup.outcome：命中 / 查了没命中 / 没查（并写了理由）'),
                    ]))
                  }
                  if (st.refs && st.refs.length) {
                    assocRows.push(assocRow('refs', '先验',
                      (PURPOSE_LABELS[st.purpose]
                        ? [React.createElement('span', { key: 'p', style: { color: T.text2, fontSize: 'var(--t-tiny)' } }, PURPOSE_LABELS[st.purpose])]
                        : []).concat(st.refs.map(r => assocChip(r, 'var(--d-purple)', '本轮取用的先验词条 id（可在 references/ 里按它回查）')))))
                  }
                  // 甄别理由：**这一行是全块最值钱的**——它区分"命中"与"有用"
                  // （实测例："命中但判为不同族：越界 vs 超时的 errorStr 不同"）。
                  if (st.note) {
                    assocRows.push(React.createElement('div', { key: 'note', style: { display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 5 } },
                      React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)', minWidth: 28, flexShrink: 0 } }, '甄别'),
                      React.createElement('span', { style: { flex: 1, minWidth: 0, color: T.text2, fontSize: 'var(--t-sm)', lineHeight: 'var(--lh-base)', wordBreak: 'break-word' } }, st.note)))
                  }
                  if (st.sources && st.sources.length) {
                    assocRows.push(assocRow('src', '资料',
                      st.sources.map(u => React.createElement('button', {
                        key: u, type: 'button', onClick: () => openFile(u), title: u, className: 'sleu-chip',
                        style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 'var(--r-pill)', padding: '1px 9px', fontSize: 'var(--t-tiny)', cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' },
                      }, openLabel(u, shortUrl(u)))).concat([openNote(st.sources[0]) || null].filter(Boolean))))
                  }
                  if (st.toolCalls && st.toolCalls.length) {
                    assocRows.push(React.createElement('div', { key: 'tc', style: { marginTop: 5, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
                      React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)', minWidth: 28, flexShrink: 0 } }, '调用'),
                      React.createElement('button', { type: 'button', className: 'sleu-chip', onClick: () => setTcOpen(tcOpenHere ? null : i), style: btnGhost },
                        tcOpenHere ? '收起' : '看 ' + st.toolCalls.length + ' 条命令'),
                      tcOpenHere ? st.toolCalls.map((c, k) => React.createElement('div', { key: k, style: { flexBasis: '100%', color: T.text2, fontSize: 'var(--t-tiny)', fontFamily: 'var(--font-mono)', lineHeight: 'var(--lh-base)', wordBreak: 'break-word' } }, '· ' + c)) : null))
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
                      React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 'var(--t-md)', color: T.text2, flexWrap: 'wrap' } },
                        React.createElement('span', { style: { fontWeight: 700, color: isUser ? T.brand : T.text } }, isUser ? '用户' : 'Agent'),
                        st.step ? React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-sm)' } }, '第 ' + st.step + ' 步') : null,
                        st.action ? (fullTrace
                          ? React.createElement('span', { className: 'sleu-mono', style: { background: T.bg2, padding: '1px 7px', borderRadius: 'var(--r-xs)', fontSize: 'var(--t-tiny)', color: T.text2 } }, st.action)
                          : React.createElement('span', { title: st.action, style: { background: T.bg2, padding: '1px 7px', borderRadius: 'var(--r-xs)', fontSize: 'var(--t-tiny)', color: T.text2 } }, STEP_LABELS[st.action] || st.action)) : null,
                        isRef ? React.createElement('span', { className: 'sleu-chip', style: { background: 'var(--tint-purple)', color: 'var(--d-purple)', borderRadius: 'var(--r-pill)', padding: '1px 8px', fontSize: 'var(--t-tiny)', fontWeight: 600 } }, '参考层') : null,
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
                  // 判据结果徽标：quickly_check / run_check 的 pass|fail|conflict（或 verdict/check）
                  (function () {
                    const raw = st.result || st.verdict || st.check
                    if (!raw) return null
                    const v = String(raw).toLowerCase()
                    const color = v.indexOf('pass') === 0 || v === 'hit' || v === 'present' ? 'var(--d-green)'
                      : v.indexOf('conflict') === 0 || v === 'unknown' ? 'var(--d-amber)'
                        : v.indexOf('fail') === 0 || v === 'absent' ? 'var(--d-red, var(--d-amber))' : 'var(--c-gray)'
                    return React.createElement('span', { key: 'res', style: { display: 'inline-block', marginTop: 6, marginRight: 6, background: 'color-mix(in srgb, ' + color + ' 12%, transparent)', color: color, borderRadius: 'var(--r-xs)', padding: '1px 8px', fontSize: 'var(--t-tiny)', fontWeight: 600 } }, String(raw))
                  })(),
                  st.output ? React.createElement('div', { style: { marginTop: 4, color: T.text, fontSize: 'var(--t-base)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } }, st.output) : null,
                  // 推理（决策依据）只在完整轨迹里铺开：它写给回放与误诊归因，不是给人读的叙述
                  // （实测：18 步的 trace 里 reason 占 2800 字，是展开后"很多无关记录"的主体）。
                  fullTrace && st.reason ? React.createElement('div', { style: { marginTop: 3, color: T.text2, fontSize: 'var(--t-md)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', borderLeft: '2px solid var(--hair)', paddingLeft: 8, lineHeight: 'var(--lh-base)' } },
                    '推理: ' + st.reason) : null,
                  st.content ? React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 'var(--t-base)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } }, st.content) : null,
                  // 关联面排在证据之前：读序是"这一步说了什么 → 用了什么外部东西 → 留下了什么现场材料"
                  assocBlock,
                  // 证据明细（可点开原文 / 打开文件）——存在性已在上面标了，这里给操作
                  ev ? React.createElement('div', { style: { marginTop: 6, display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--t-sm)', flexWrap: 'wrap' } },
                    ev.inline ? React.createElement('button', { type: 'button', onClick: () => setEvOpen(evOpenHere ? null : i), className: 'sleu-chip', style: btnGhost }, evOpenHere ? '收起原文' : '看原文') : null,
                    hasFiles ? React.createElement(React.Fragment, null,
                      React.createElement('span', { style: { color: T.text2 } }, '文件'),
                      ev.files.map(f => React.createElement('button', { key: f, type: 'button', onClick: () => openFile(f), title: f, className: 'sleu-chip', style: { background: 'transparent', border: '1px solid ' + T.border, borderRadius: 'var(--r-pill)', padding: '1px 9px', fontSize: 'var(--t-tiny)', cursor: 'pointer', color: T.brand, fontFamily: 'var(--font-mono)' } },
                        openLabel(f, baseName(f)))),
                      openNote(ev.files[0]),
                    ) : null,
                    !hasInline && !hasFiles && hasMissing ? React.createElement('span', { style: { color: T.text2 } }, '这一步没有留证据') : null,
                  ) : null,
                  evOpenHere && ev.inline ? React.createElement('pre', { style: { marginTop: 6, background: T.bg2, border: '1px solid var(--hair)', borderRadius: 'var(--r-sm)', padding: 10, fontSize: 'var(--t-sm)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: T.text, lineHeight: 'var(--lh-base)', maxHeight: 320, overflowY: 'auto' } }, ev.inline) : null,
                  // 原文超长时**如实说**：徽标上的"证据 N 字"读的是原文长度（host 给 inlineChars），
                  // 而这里显示的是截断后的前 N 字——不说出来就成了静默截断（与报告区同一条纪律）。
                  evOpenHere && ev.inline && ev.inlineChars > ev.inline.length
                    ? React.createElement('div', { style: { marginTop: 4, color: T.text2, fontSize: 'var(--t-tiny)' } },
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
            // 默认收起：根因在上方结论块已有一处。
            // 读者要的是"最后定在哪"；它排在轨迹之后，卡片以结论收尾。轨迹末条本身也是结论
            // （trace 里就能读到），人读视图里不重复渲染那条，只在完整轨迹保留原事件。
            conclusionStep ? React.createElement(Fold, { title: '定位结论（完整）', hint: '根因在上方结论块已有一处' },
              React.createElement('div', { style: { padding: 10, background: 'color-mix(in srgb, var(--acc-green) 7%, transparent)', border: '1px solid var(--acc-green)', borderRadius: 'var(--r-md)' } },
              React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5, flexWrap: 'wrap' } },
                React.createElement(SectionLabel, { color: 'var(--c-green)' }, '定位结论'),
                conclusionStep.step ? React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-sm)' } }, '第 ' + conclusionStep.step + ' 步') : null,
                React.createElement('span', { style: { fontSize: 'var(--t-sm)', color: T.text2 } }, '轨迹末条'),
              ),
              React.createElement('div', { style: { fontSize: 'var(--t-base)', color: T.text, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } }, conclusionStep.output || conclusionStep.content || '(该步没有 output)'),
              React.createElement('div', { style: { marginTop: 6, fontSize: 'var(--t-sm)', color: T.text2 } },
                fullTrace
                  ? '上方完整轨迹里保留了这条事件的原位置。'
                  : '上方轨迹略去了这条（同一段不读两遍）；「看完整轨迹」里它在原位置。'),
              ),
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
          : React.createElement('span', { title: '该 case 未入库（新形态待沉淀）', style: tinyBadge('var(--d-purple)') }, '新形态')
      }

      // 状态左条：**扫列表时先看这一列**（进行中/已转上游=要跟；已定位=可放过）
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
          key: 'close-fix', label: '已定位（有结论）', tone: 'success',
          // 无命中单的结果**不走反馈轴**（没有 case 可回写 confidence）：结果记在 status 与 summary。
          // 同时要把遗留的 `feedback.outcome: pending` 清掉——否则"状态已结、反馈轴仍挂 pending"，
          // 面板与 resume 都会把它读成一个还在等的回报（实测这两轴就是这么打架的）。
          cmd: '闭环诊断 ' + s.sessionId + '：诊断已收尾、根因定位明确。未命中知识库 case，因此不写 feedback；'
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
      for (const c of closeCmds) actions.push({ key: c.key, label: c.label, style: toneStyle(c.tone), title: '生成收尾指令（复制后粘到对话执行）', cmd: c.cmd })
      const openedCmd = actions.filter(a => a.key === showCmd)[0] || null
      // 报告入口（diagnose 步骤 6 的产出）。**沉淀候选的明细不在这里**——它归展开态的沉淀区
      // （case 与先验候选分家、各带入口，见上方「沉淀区」）：候选与"本单沉淀状态"是同一件事的两面，
      // 拆到卡头下方与卡体深处两处，读者接不上各自的入口（旧版就是这么散的）。
      const docRow = (reportPath || s.sedimentCandidates)
        ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
            // 两个入口的词必须不同：一个在面板里读（TL;DR / 依据链 / 一键复制全文），
            // 一个把那**份文件**交给默认应用打开。旧的「看报告 / 打开报告」四个字里只差两个、
            // 且都以"报告"结尾，实测被读成同一个动作；「读正文」「用系统应用打开」又被读成
            // 术语（"正文"指什么、"系统应用"是什么）。现在两个词分指两样东西：报告 / 报告文件。
            reportPath ? React.createElement('button', {
              type: 'button', onClick: toggleReport, title: '在面板里看这份报告：TL;DR / 依据链 / 修复方案，可一键复制全文',
              style: { background: reportOpen ? 'color-mix(in srgb, ' + T.brand + ' 10%, transparent)' : 'transparent', border: '1px solid ' + T.border, color: T.text, borderRadius: 'var(--r-pill)', padding: '2px 11px', fontSize: 'var(--t-tiny)', fontWeight: 600, cursor: 'pointer' },
            }, reportOpen ? '收起报告' : '看报告') : null,
            reportPath ? React.createElement('button', {
              type: 'button', onClick: () => openFile(reportPath), title: '用默认应用打开这份报告文件（.md）：' + reportPath,
              style: { background: 'transparent', border: '1px solid ' + T.brand, color: T.brand, borderRadius: 'var(--r-pill)', padding: '2px 11px', fontSize: 'var(--t-tiny)', fontWeight: 600, cursor: 'pointer' },
            }, opening === reportPath ? '打开中…' : '打开报告文件') : null,
            // 入口是**靠同名规则**找到的（trace 里没记 `report_file`）就说出来：报告明明落在
            // traces/ 里而卡片上什么都不给，读者只会以为"面板读不到报告"（实测反馈）。
            s.reportSource === 'name' ? React.createElement('span', { title: 'trace 里没有 report_file；这份报告是按 <trace 同名>.report.md 的规则找的', style: { color: T.text2, fontSize: 'var(--t-tiny)' } },
              '（trace 未记报告名，按同名规则找到）') : null,
            // 开没开成都要看得见：成功给「已打开（via X）」，失败给原因。
            // 旧版成功无反馈、失败静默 → 用户只看到"点了没反应"。
            reportPath ? openNote(reportPath) : null,
            // 收起态只报条数（明细在展开态的沉淀区）。措辞是「建议」不是「待沉淀」：
            // 它既不是债务、也不一定会被做——尤其先验候选，要不要沉淀由人判断（诊断抛出的只是建议）。
            s.sedimentCandidates ? React.createElement('span', { style: tinyBadge('var(--d-purple)'), title: 'trace.sediment_candidates（与报告第 8 节同源）：含本单 case 与先验知识两类候选，明细见展开后的沉淀区' }, '沉淀建议 ' + s.sedimentCandidates + ' 条') : null,

          )
        : null
      // ---- 动作区：主操作常驻，收尾与交接收进 <details> ----
      // 为什么要收：12 个可点区域平铺时，主操作（看报告 / 继续诊断）被淹没，卡片也被撑到
      // 200px 以上。收进可展开组之后，收起态只留一行；展开后仍是同一批按钮、同一段指令。
      const menuBtn = (key, label, title) => React.createElement('button', {
        type: 'button', title: title, 'aria-expanded': menuOpen === key ? 'true' : 'false',
        onClick: () => setMenuOpen(menuOpen === key ? null : key),
        style: { ...btnGhost, padding: '2px 10px' },
      }, label + (menuOpen === key ? ' ▴' : ' ▾'))
      // ---- 交接包：把这一单交到另一台机器（外网定位到一半、真正的大日志在内网）----
      // 与"生成指令"类按钮分工不同：它是**直接动作**（点了就导出），所以收进可展开组；
      // 结果（体量 / 未纳入 / 待补材料 / 含原始证据）仍逐项回报，外发前由人按数据通道规则处理。
      const handoffRow = React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
        HANDOFF_INTENTS.map(it => React.createElement('button', {
          key: it.id, type: 'button', title: it.why, onClick: () => setHandoffIntent(it.id),
          style: handoffIntent === it.id
            ? { ...btnPrimary, padding: '2px 9px', borderRadius: 'var(--r-pill)', fontSize: 'var(--t-tiny)' }
            : { ...btnGhost, padding: '2px 9px', borderRadius: 'var(--r-pill)', fontSize: 'var(--t-tiny)' },
        }, it.label)),
        React.createElement('button', {
          type: 'button', onClick: doExportHandoff, disabled: !!(handoff && handoff.busy),
          title: '导出交接包（zip + 单文件 md）到 traces/exports/；该目录写不进去时改道到检出内的 '
            + '.handoff/，结果行会写明落在哪。拷到另一台机器后用 python3 scripts/import_trace.py <包> 接手',
          style: (handoff && handoff.busy)
            ? { ...btnOutline(T.brand), opacity: 0.6, cursor: 'default' }
            : btnOutline(T.brand),
        }, (handoff && handoff.busy) ? '导出中…' : '导出交接包'),
        // 只有落点在会话工作区内时才有仓库内相对路径；没有就不给这个按钮——
        // 退回 'traces/exports' 会在改道后指向一个没有包的目录
        handoff && handoff.ok && handoff.dirRel ? React.createElement('button', {
          type: 'button', onClick: () => openFile(handoff.dirRel), title: handoff.dir,
          style: { background: 'transparent', border: '1px solid ' + T.border, color: T.text2, borderRadius: 'var(--r-pill)', padding: '2px 9px', fontSize: 'var(--t-tiny)', cursor: 'pointer' },
        }, '打开目录') : null,
        handoff && handoff.ok ? React.createElement('span', { style: { color: 'var(--c-green)', fontSize: 'var(--t-tiny)' } },
          '已导出 zip ' + humanKB(handoff.zipBytes)
          + (handoff.md ? ' + md ' + humanKB(handoff.mdBytes) : '')
          + '｜' + handoff.files + ' 个文件'
          + ((handoff.omitted && handoff.omitted.length) ? '｜未纳入 ' + handoff.omitted.length + ' 个（体积上限）' : '')
          + ((handoff.needs && handoff.needs.length) ? '｜带 ' + handoff.needs.length + ' 条待补材料' : '')) : null,
        // 导出目录改道：写权限不覆盖 traces/exports 时脚本改道到检出内的 .handoff/。
        // 必须说清"本想去哪、实际落在哪"——不说的话读者会去 traces/exports 找，找不到就当成导出失败。
        handoff && handoff.ok && handoff.fallback ? React.createElement('span', {
          style: { color: 'var(--c-amber)', fontSize: 'var(--t-tiny)' },
          title: '脚本先试 ' + String(handoff.fallback.requested || 'traces/exports') + '，写不进去后改道到 '
            + String(handoff.fallback.dir || '.handoff') + '（同一检出内）。'
            + '接收侧只认包内容与交接单，不认目录名。',
        }, '导出目录改道：' + String(handoff.fallback.reason || '写权限被拒')
          + '；本次落在 ' + String(handoff.dirRel || handoff.fallback.dir || '.handoff')) : null,
        // 包内含原始现场证据：**标出来，不代替脱敏**——真正的闸门在数据通道上，不在面板上
        handoff && handoff.ok && handoff.redaction && handoff.redaction.state === 'raw-evidence'
          ? React.createElement('span', {
              style: tinyBadge('var(--d-amber)'),
              title: '交接单 redaction.state=raw-evidence：包内含原始现场证据（日志/配置原样）。'
                + '导出不做脱敏；外发前按你们的数据通道规则处理。',
            }, '含原始证据') : null,
        handoff && handoff.error ? React.createElement('span', { style: { color: 'var(--c-amber)', fontSize: 'var(--t-tiny)' } }, handoff.error) : null,
      )
      const cmdButton = (a) => React.createElement('button', {
        key: a.key, type: 'button', title: a.title,
        onClick: () => { setShowCmd(showCmd === a.key ? null : a.key); setCopied(null); setMenuOpen(null) },
        style: { ...a.style, padding: '2px 10px' },
      }, a.label)
      const resumeAction = actions.filter(a => a.key === 'rs')[0] || null
      const closeActions = actions.filter(a => a.key !== 'rs')
      // 「打开会话」：从诊断记录里直接切到这一单的会话，不必回左侧列表里按会话号找。
      // **只能用 `harness_session`**：`session_id` 是诊断自己起的名字（形如
      // `<日期>-<issue 号>-<短名>`），DSH 的会话号是 `session-<uuid>`，两者不是一回事——
      // 拿名字去 open 每一次都会抛（实测：第一版用错号，20 单全点不动，就是这一条）。
      // 没记会话号的老单不给按钮：给一个点了必失败的按钮比不给更坏。
      // 它是**切走**的动作（点了就离开面板），所以成功不需要回显；失败要说话——
      // 外来单（import_trace.py 接手的那批）在本机没有这个会话，静默会被读成"面板坏了"。
      const harnessSession = s.harnessSession ? String(s.harnessSession) : ''
      const isCurrentSession = !!(harnessSession && props.currentSession && String(props.currentSession) === harnessSession)
      const navBtn = isCurrentSession
        ? React.createElement('span', {
            title: '这一单就是你当前打开的会话——不必再跳',
            style: { color: T.text2, fontSize: 'var(--t-tiny)', border: '1px dashed ' + T.border, borderRadius: 'var(--r-pill)', padding: '2px 10px' },
          }, '当前会话')
        : harnessSession
        ? React.createElement('button', {
            type: 'button', title: '切到这条诊断的会话（' + harnessSession + '）',
            onClick: () => {
              openSession(harnessSession).then(res => setNavErr(res.ok ? null : res.reason))
            },
            style: { background: 'transparent', border: '1px solid ' + T.brand, color: T.brand, borderRadius: 'var(--r-pill)', padding: '2px 11px', fontSize: 'var(--t-tiny)', fontWeight: 600, cursor: 'pointer' },
          }, '打开会话')
        : React.createElement('span', {
            title: '这单的轨迹顶层没有 harness_session，定位不到 DSH 会话（session_id 是诊断自己起的名字，'
              + '不是 DSH 的会话号）。可能是建会话时漏写，也可能是那次写入该字段之前的单——面板看不出是哪种，'
              + '只说事实。补法（已知本会话号时秒级）：'
              + 'python3 scripts/link_harness_sessions.py --trace ' + String(s.file || '') + ' --session-id "$DSH_SESSION_ID" --apply',
            style: { color: T.text2, fontSize: 'var(--t-tiny)', border: '1px dashed ' + T.border, borderRadius: 'var(--r-pill)', padding: '2px 10px' },
          }, '未记会话号')
      // 展开的命令块只出现一次（谁被点开就显示谁）；选中关系靠"命令块在最下方"表达，
      // 不再用 opacity 压未选中的按钮——那会把白字压到 2.07:1（AA 要求 4.5）。
      const stActions = (st && Array.isArray(st.actions)) ? st.actions : []
      const stAct = stEdit.action ? stActions.filter(a => a.id === stEdit.action)[0] : null
      const stKinds = stAct ? (stAct.endingChoices || []).map(c => c.value) : []
      const submitState = () => {
        if (!stAct) { setStEdit(v => ({ ...v, msg: '先选一个动作' })); return }
        const payload = {}
        if (stEdit.kind) payload['ending.kind'] = stEdit.kind
        if (stEdit.handed) payload['ending.handed_to'] = stEdit.handed
        if (stEdit.dup) payload['ending.duplicate_of'] = stEdit.dup
        setStEdit(v => ({ ...v, msg: '写入中…' }))
        host.call('ascend-trace-transition', {
          sessionId: s.sessionId, action: stAct.id, payload,
          expectSha256: (st && st.contentSha256) || '',
        }).then(r => {
          setStEdit(v => ({ ...v, msg: (r && r.ok)
            ? ('已记录：' + String(r.from || '') + ' → ' + String(r.to || '') + '，刷新后列表生效')
            : ('失败：' + String((r && (r.message || r.code)) || '未知错误')) }))
        }).catch(e => setStEdit(v => ({ ...v, msg: '失败：' + String(e && e.message || e) })))
      }
      const stPanel = st ? React.createElement('div', { className: 'sleu-menu-panel', style: { display: menuOpen === 'state' ? 'flex' : 'none', flexDirection: 'column', alignItems: 'stretch', gap: 6, marginTop: 8, padding: '8px 10px', border: '1px solid var(--hair)', borderRadius: 'var(--r-md)', background: T.bg2 } },
        React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } },
          '直接写入这一单的状态：经脚本校验并追加一条转移记录；没有写权限时会提示改用复制命令。'),
        stActions.length ? React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
          stActions.map(a => React.createElement('button', {
            key: a.id, type: 'button',
            onClick: () => setStEdit({ action: a.id, kind: (a.endingChoices && a.endingChoices[0] && a.endingChoices[0].value) || '', handed: '', dup: '', msg: '' }),
            style: stEdit.action === a.id ? btnPrimary : btnGhost,
          }, a.label))) : React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, '这一单当前没有可执行的动作。'),
        stAct ? React.createElement('div', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' } },
          stKinds.length ? React.createElement('select', {
            value: stEdit.kind, onChange: e => setStEdit(v => ({ ...v, kind: e.target.value })),
            style: { font: 'inherit', fontSize: 'var(--t-sm)', padding: '4px 6px', borderRadius: 'var(--r-sm)', border: '1px solid var(--hair)', background: T.bg },
          }, stKinds.map(k => React.createElement('option', { key: k, value: k },
            ((VOCAB_CACHE && VOCAB_CACHE.endings) || []).reduce((acc, e2) => e2.value === k ? e2.label : acc, k)))) : null,
          (stEdit.kind === 'handed_off') ? React.createElement('input', {
            placeholder: '转交给（名字 · 团队 / issue 号）', value: stEdit.handed,
            onChange: e => setStEdit(v => ({ ...v, handed: e.target.value })),
            style: { font: 'inherit', fontSize: 'var(--t-sm)', padding: '4px 6px', borderRadius: 'var(--r-sm)', border: '1px solid var(--hair)', background: T.bg, minWidth: 200 },
          }) : null,
          (stEdit.kind === 'duplicate') ? React.createElement('input', {
            placeholder: 'case:<id> 或 session:<id>', value: stEdit.dup,
            onChange: e => setStEdit(v => ({ ...v, dup: e.target.value })),
            style: { font: 'inherit', fontSize: 'var(--t-sm)', padding: '4px 6px', borderRadius: 'var(--r-sm)', border: '1px solid var(--hair)', background: T.bg, minWidth: 220 },
          }) : null,
          React.createElement('button', { type: 'button', onClick: submitState, style: btnPrimary }, '确认收尾')) : null,
        stEdit.msg ? React.createElement('div', { role: 'status', 'aria-live': 'polite', style: { fontSize: 'var(--t-tiny)', color: stEdit.msg.indexOf('失败') === 0 ? T.error : T.text2 } }, stEdit.msg) : null,
        (st.provenance && st.provenance.at) ? React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } },
          '最近记录：' + String(st.provenance.at).slice(5, 16).replace('T', ' ') + (st.provenance.byLabel ? ' · ' + st.provenance.byLabel : '')) : null,
      ) : null
      const actionArea = React.createElement('div', { style: { margin: '0 16px', padding: '10px 0 14px', borderTop: '1px solid var(--hair)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
          navBtn,
          navErr ? React.createElement('span', { style: { color: 'var(--c-amber)', fontSize: 'var(--t-tiny)' } }, navErr) : null,
          docRow,
          resumeAction ? cmdButton(resumeAction) : null,
          closeActions.length ? menuBtn('close', '收尾', '生成收尾指令（复制后粘到对话执行）') : null,
          stActions.length ? menuBtn('state', '直接收尾', '在面板里写入状态（经脚本校验，留转移记录）') : null,
          menuBtn('handoff', '交接包', '导出交接包到 traces/exports/，或接手另一台机器上的单'),
        ),
        // 动作组的展开区：固定在按钮行**下方**，同一时刻只有一块；按钮行本身不动。
        // 两个组都常驻 DOM、用 display 切换：不参与布局（没有位置偏移），也不占 Tab 序
        // （display:none 的元素不可聚焦）。
        React.createElement('div', { className: 'sleu-menu-panel', style: { display: menuOpen === 'close' ? 'flex' : 'none', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginTop: 8, padding: '8px 10px', border: '1px solid var(--hair)', borderRadius: 'var(--r-md)', background: T.bg2 } },
          closeActions.map(cmdButton)),
        React.createElement('div', { className: 'sleu-menu-panel', style: { display: menuOpen === 'handoff' ? 'flex' : 'none', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginTop: 8, padding: '8px 10px', border: '1px solid var(--hair)', borderRadius: 'var(--r-md)', background: T.bg2 } },
          handoffRow),
        stPanel,
        openedCmd ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 } },
          React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg2, border: '1px solid var(--hair)', borderRadius: 'var(--r-sm)', padding: '5px 8px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: T.text } }, openedCmd.cmd),
          React.createElement('button', { type: 'button', onClick: () => doCopy(openedCmd.cmd, openedCmd.key), style: copyFailKey === openedCmd.key ? btnRed : btnPrimary, title: '复制指令' },
            copied === openedCmd.key ? '已复制' : (copyFailKey === openedCmd.key ? '失败' : '复制')),
        ) : null,
      )
      return React.createElement('div', { className: 'sleu-card', style: { background: T.bg, backgroundImage: 'var(--surf)', border: '1px solid var(--hair)', borderLeft: '3px solid ' + statusAccent, borderRadius: 'var(--r-lg)', marginBottom: 10 } },
        // 勾选框在整行按钮**外面**：整行是一个 button，把 checkbox 嵌进去是嵌套交互元素，
        // 键盘与事件都会打架。它只在「待升格」筛选下渲染。
        selectable ? React.createElement('label', { style: { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px 0', fontSize: 'var(--t-sm)', color: T.text2, cursor: 'pointer' } },
          React.createElement('input', { type: 'checkbox', checked: selected, onChange: () => onToggleFile(s.file) }),
          '选中用于批量标已解决') : null,
        React.createElement('button', {
          type: 'button', 'aria-expanded': !!open, onClick: toggle, className: 'sleu-row',
          style: { width: '100%', padding: '12px 16px 0', cursor: 'pointer', border: 'none', textAlign: 'left', color: T.text, font: 'inherit' },
        },
          // 一行读完：状态 / 会话 / 框架·平台 / 事件数 / 耗时 / token / 箭头。
          // 列宽与上方的列头共用 ROW_COLS，否则表格读起来是错位的。
          React.createElement('div', { style: { display: 'grid', gridTemplateColumns: ROW_COLS, alignItems: 'center', gap: 10, width: '100%' } },
            React.createElement('span', { title: meta.label, style: { display: 'flex', alignItems: 'center', gap: 6, color: meta.color, fontSize: 'var(--t-sm)', fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } },
              React.createElement(Dot, { color: meta.color, hollow: s.status === 'unknown' }),
              meta.label),
            React.createElement('span', { className: 'sleu-mono', title: s.sessionId, style: { fontWeight: 500, fontSize: 'var(--t-tiny)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.sessionId),
            React.createElement('span', { className: 'sleu-c-fw', title: [s.framework, s.platform, s.category].filter(Boolean).join(' · '), style: { color: T.text2, fontSize: 'var(--t-tiny)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } },
              [s.framework, s.platform].filter(Boolean).join(' · ') || '—'),
            React.createElement('span', { title: '用户事件 / Agent 事件', className: 'sleu-num sleu-c-events', style: { color: T.text2, fontSize: 'var(--t-tiny)', textAlign: 'right', whiteSpace: 'nowrap', minWidth: 0 } },
              s.userSteps + ' / ' + s.agentSteps),
            // 两列只读诊断窗口内的数。旧格式的明细只有本会话累计（同会话做过两单时两单一样），
            // 那种明细不显示数字——写「—」并在 title 里给重跑命令，读数才不会把两单说成一样贵。
            React.createElement('span', {
              title: costScopeTitle(s.cost, '工具调用累计耗时（诊断窗口内）'),
              className: 'sleu-num sleu-c-ms', style: { color: T.text2, fontSize: 'var(--t-tiny)', textAlign: 'right', whiteSpace: 'nowrap', minWidth: 0 } },
              (s.cost && s.cost.scope === 'window' && typeof s.cost.ms === 'number') ? msText(s.cost.ms) : '—'),
            React.createElement('span', {
              title: costScopeTitle(s.cost, '工具调用累计 token（诊断窗口内）'),
              className: 'sleu-num sleu-c-tok', style: { color: T.text2, fontSize: 'var(--t-tiny)', textAlign: 'right', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 } },
              (s.cost && s.cost.scope === 'window' && typeof s.cost.tok === 'number') ? thousands(s.cost.tok) : '—'),
            React.createElement('span', { style: { display: 'flex', justifyContent: 'flex-end' } }, React.createElement(Chevron, { open: open })),
          ),
          // 第二行：一句"这单在查什么" + 外来标记 + 更新时间。收起态只留这些，其余细节在展开态。
          React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4, flexWrap: 'wrap', minWidth: 0 } },
            kbTag,
            // 定位并入这一行：命中时给「定位 <id>」，没命中时给一句灰字（占位串原样带上）。
            // 此前它单独占一行，而多数单都是"没有对应案例"，等于用一整行说"没有"。
            caseKindOf(s) === 'case'
              ? React.createElement('span', { className: 'sleu-mono', title: '定位到的知识库 case', style: Object.assign(tinyBadge('var(--d-green)'), { fontSize: 'var(--t-tiny)' }) }, '定位 ' + s.activeCase)
              : React.createElement('span', { style: { display: 'inline-flex', alignItems: 'baseline', gap: 5, minWidth: 0, color: T.text2, fontSize: 'var(--t-tiny)' } },
                  '没有对应案例',
                  // 占位串原样摆出（不摆，读者会以为面板漏读了字段）；解释只在 title 与 README。
                  caseKindOf(s) === 'placeholder' ? React.createElement('span', { title: 'trace 里记的定位值（不是知识库里的 case）', className: 'sleu-mono', style: { maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: 0.8 } }, s.activeCase) : null),
            // 「待沉淀」「待升格」两条待办的徽标（判据与升格闸门同源）。
            // 它们此前只有展开卡片才看得见——会话一多就成了看不见的积压。
            (st && st.ending && st.ending.kind && st.ending.kind !== 'root_cause') ? React.createElement('span', {
              title: '本单的收尾方式（写入 trace 的 ending.kind）', style: tinyBadge('var(--d-amber)'),
            }, ((VOCAB_CACHE && VOCAB_CACHE.endings) || []).reduce((acc, e2) => e2.value === st.ending.kind ? e2.label : acc, st.ending.kind)) : null,
            (st && st.provenance && st.provenance.at) ? React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)' } },
              '记录于 ' + String(st.provenance.at).slice(5, 16).replace('T', ' ') + (st.provenance.byLabel ? ' · ' + st.provenance.byLabel : '')) : null,
            needSedOf(s) ? React.createElement('span', {
              title: '有 case 类沉淀候选（= 根因已形成可复用结论）、还没沉淀'
                + (isClosedOf(s) ? '' : '；诊断尚未标收尾')
                + '——在「待沉淀」筛选里可一次生成批量沉淀命令',
              style: tinyBadge('var(--d-purple)'),
            }, (isClosedOf(s) ? '已收尾 · ' : '有结论 · ') + '待沉淀') : null,
            needReviewOf(s) ? React.createElement('span', {
              title: '有报告或只有 reference / triage 候选，没有 case 类候选：根因可能还没定。'
                + '在「待复核」筛选里，读一眼报告——定了就补一条 case 候选，没定就继续查或标收尾/转上游',
              style: tinyBadge('var(--d-amber)'),
            }, '待复核') : null,
            // 严重级：只有非 benign 才出徽标——benign 是常态，人人挂一个等于没有信号。
            // data-loss-risk 的语义是"先停"，不是"打补丁"，所以文案直接写动作。
            (s.severity === 'data-loss-risk')
              ? React.createElement('span', { title: '根因属数据丢失风险：先停训练/推理、保留现场、通知 owner，不在这里打补丁',
                  style: tinyBadge('var(--d-red)') }, '数据风险 · 先停') : null,
            (s.severity === 'service-affecting')
              ? React.createElement('span', { title: '修这条会中断服务或有副作用（例如需要重启）：给 fix 时要一并说明',
                  style: tinyBadge('var(--d-amber)') }, '影响服务') : null,
            // 有没有给出 fix：没给的单（等上游、只定位）与"给了规避方案"读起来是两件事。
            (s.fixEmitted === true)
              ? React.createElement('span', { title: '本次诊断给出了可执行的修复或规避方案', style: tinyBadge('var(--d-green)') }, '已给 fix') : null,
            (s.fixEmitted === false)
              ? React.createElement('span', { title: '本次诊断没有给出可执行的修复（常见于等上游修复、或只定位到根因）',
                  style: tinyBadge('var(--d-gray)') }, '未给 fix') : null,
            // fix 验证结果（现场回报）：pending 由「等回报」那条承载，这里只标已有结论的三种。
            (String(s.feedback || '') === 'resolved')
              ? React.createElement('span', { title: '工程师回报：这个 fix 在自己的环境里生效了', style: tinyBadge('var(--d-green)') }, 'fix 已验证') : null,
            (String(s.feedback || '') === 'not_resolved')
              ? React.createElement('span', { title: '工程师回报：fix 应用后没解决问题——按误诊归因处理', style: tinyBadge('var(--d-red)') }, 'fix 未生效') : null,
            (String(s.feedback || '') === 'partial')
              ? React.createElement('span', { title: '工程师回报：症状缓解但没根治', style: tinyBadge('var(--d-amber)') }, '部分生效') : null,
            isSkeletonOf(s) ? React.createElement('span', {
              title: '这条记录里没有任何内容：没有一轮对话、没有背景、没有报告，也没有沉淀候选。'
                + '要么补一次诊断，要么直接标「不跟了」',
              style: tinyBadge('var(--d-gray)'),
            }, '空记录') : null,
            needPromoteOf(s) ? React.createElement('span', { title: '草稿已交到 inbox，但来源诊断还没收尾——升格前的检查会拦；在「已交草稿」筛选里可勾选后批量标收尾', style: tinyBadge('var(--d-amber)') }, '未收尾 · 待升格') : null,
            (isSubmittedOf(s) && !needPromoteOf(s)) ? React.createElement('span', { title: '草稿已交到 inbox，等知识整理排期升格；没有卡住的地方', style: tinyBadge('var(--d-purple)') }, '已交草稿 · 等整理') : null,
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
            (s.createdAt || rel) ? React.createElement('span', { style: { marginLeft: 'auto', display: 'flex', gap: 8, color: T.text2, fontSize: 'var(--t-tiny)', whiteSpace: 'nowrap' } },
              s.createdAt ? React.createElement('span', { title: '诊断开始：' + (fmtTimeFull(s.createdAt) || s.createdAt) }, '开始 ' + fmtTime(s.createdAt)) : null,
              rel ? React.createElement('span', { title: s.updatedAt ? '最后更新：' + (fmtTimeFull(s.updatedAt) || s.updatedAt) : null }, '更新 ' + rel) : null,
            ) : null,
          ),
          // 副行：**收起态显示"这单在查什么"**——取 trace 的问题背景段（host 带的 summarySnippet）。
          // 旧版显示"最后一步 · Agent" + 最后一个事件的 output，读者看不懂：最后一个事件常常是
          // 产出报告 / 续接 / 回报这类**记录维护**动作（实测反馈："最后一步……让人看不懂也觉得很奇怪"），
          // 它回答的是"记录被改了什么"，不是"这单在查什么"。没有背景段才退回最后一个事件的输出。
          React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-sm)', marginTop: 4, lineHeight: 'var(--lh-base)', display: 'flex', gap: 6, alignItems: 'baseline', minWidth: 0 } },
            !open && (s.summarySnippet || s.lastOutput)
              ? React.createElement(React.Fragment, null,
                  React.createElement('span', { style: { color: T.text2, flexShrink: 0 } }, s.summarySnippet ? '背景' : '末条记录'),
                  React.createElement('span', { title: s.summarySnippet || s.lastOutput, style: { color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, s.summarySnippet || s.lastOutput),
                )
              : React.createElement('span', null, [s.framework, s.platform, s.category].filter(Boolean).join(' · ') || '—'),
          ),
          (s.excludedCount || s.sedimentCandidates)
            ? React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-tiny)', marginTop: 3, display: 'flex', gap: 12, flexWrap: 'wrap' } },
                s.excludedCount ? React.createElement('span', null, '排除 ' + s.excludedCount + ' 条') : null,
                s.sedimentCandidates ? React.createElement('span', null, '沉淀建议 ' + s.sedimentCandidates + ' 条') : null)
            : null,
          // 步数由同一份解析结果算出：解析少了就得说，否则"1 用户输入"看起来像这单只有一步。
          s.parseAnomaly ? React.createElement('div', { style: { color: T.warn, fontSize: 'var(--t-md)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: T.warn }),
            anomalyText(s.parseAnomaly)) : null,
          // 两条轴的**话术分开**：有可应用 fix 才叫"结果待回报"；没命中 case 的单等的是材料，
          // 而"等什么"trace 里已经写着（最近一条 `evidence.missing`，退到 `last_action`）——
          // 直接把它显示出来，读者不用展开轨迹去猜。这一类用中性色：它不是债。
          fbKindOf(s) === 'case' ? React.createElement('div', { style: { color: T.warn, fontSize: 'var(--t-md)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 } },
            React.createElement(Dot, { color: T.warn }),
            '结果待回报：' + (s.feedbackCase || (caseKindOf(s) === 'case' ? s.activeCase : '') || '命中 case') + '（下方可生成回报指令）') : null,
          fbKindOf(s) === 'no-case' ? React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-md)', marginTop: 4, display: 'flex', alignItems: 'baseline', gap: 6 } },
            React.createElement('span', { style: { flexShrink: 0 } }, '等现场补材料：'),
            React.createElement('span', { title: s.waitingFor || '', style: { color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } },
              s.waitingFor ? (s.waitingFor.length > 60 ? s.waitingFor.slice(0, 60) + '…' : s.waitingFor) : '本次诊断缺的材料（见轨迹里的「缺」标记）'),
          ) : null,
        ),
        // 收起态：指令区（报告入口 + 续接/闭环 + 交接包）就地留在表头下面——
        // 报告入口藏进展开态，读者会以为面板读不到报告（这条是实测反馈定的，不能省）。
        // 展开态：指标带横贯一行，下面是「正文 | 操作栏」两栏，指令区挪进右侧操作栏，正文更宽。
        open ? null : actionArea,
        open
          ? React.createElement('div', { className: 'sleu-open sleu-expanded' },
              React.createElement('div', { className: 'sleu-band' }, band),
              body ? React.createElement('div', { className: 'sleu-main' }, body) : null,
              React.createElement('div', { className: 'sleu-rail' },
                reportBlock,
                actionArea,
                // 会话块：这单对应哪个 harness 会话、用的是哪个知识库版本、花了多少——维护者接手时要看。
                (function () {
                  const rec = (steps && steps.record) || null
                  if (!rec) return null
                  // 键值行：短值同行右对齐；长值（会话号、版本号）改成「标签一行、原值一行」，
                  // 并在原值上断词。早先一行 `space-between` + nowrap 会在 232px 栏里把标签挤成两行，
                  // 值又被省略号截掉——两样都读不到。
                  const kv = (k, v) => {
                    const text = v === null || v === undefined || v === '' ? NOT_RECORDED : String(v)
                    const stacked = text.length > 18
                    return React.createElement('div', { style: { padding: '2px 0', fontSize: 'var(--t-tiny)', display: stacked ? 'block' : 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' } },
                      React.createElement('span', { style: { color: T.text2, flexShrink: 0, whiteSpace: 'nowrap' } }, k),
                      React.createElement('span', { className: 'sleu-mono', title: text, style: { color: T.text, minWidth: 0, display: stacked ? 'block' : 'inline-block', marginTop: stacked ? 1 : 0, textAlign: stacked ? 'left' : 'right', overflowWrap: 'anywhere', wordBreak: 'break-word' } }, text))
                  }
                  return React.createElement('div', { style: { marginTop: 8, padding: '8px 10px', border: '1px solid ' + T.border, borderRadius: 'var(--r-sm)' } },
                    React.createElement('div', { style: { fontSize: 'var(--t-md2)', color: T.text2, marginBottom: 4 } }, '会话'),
                    kv('开始时间', fmtTimeFull(s.createdAt) || NOT_RECORDED),
                    kv('harness 会话', rec.harnessSession || NOT_RECORDED),
                    kv('知识库版本', rec.kbRev || NOT_RECORDED),
                    // 这两行是**整条会话**的账（成本块报的是诊断窗口内的那一份）：同会话做过两单时
                    // 两单在这里一样，是对照用的量，不是这一单的成本。
                    kv('本会话工具耗时', rec.toolTotalMs ? msText(rec.toolTotalMs) : NOT_RECORDED),
                    kv('本会话调用次数', rec.toolCallCount ? String(rec.toolCallCount) : NOT_RECORDED),
                    kv('停止原因', rec.outcome && rec.outcome.stopReason ? String(rec.outcome.stopReason) : NOT_RECORDED))
                })(),
                // 数据缺口：给维护者判断"这份记录能不能进聚合"。读者不该被它挡一屏——
                // 收成计数徽标，点开才列明细；没有缺口就整块不出现。
                (function () {
                  if (!steps) return null
                  const miss = steps.recordMissing || []
                  if (!miss.length) return null
                  return React.createElement(Fold, { title: '数据缺口 ' + miss.length + ' 项', hint: '影响这份记录能不能进聚合' }, d5NotRecorded)
                })(),
              ),
            )
          : null,
      )
        })

    function TraceView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null })
      const [query, setQuery] = React.useState('')
      const [queryInput, setQueryInput] = React.useState('')
      const [kbFilter, setKbFilter] = React.useState('all')
      // 待升格筛选下的多选（file → true）；批量闭环只对勾中的单生成一条命令。
      const [sel, setSel] = React.useState({})
      // 批量指令的唯一展开位（'sed' / 'close'），与卡片内指令区同一条纪律：点谁显示谁。
      const [batchCmd, setBatchCmd] = React.useState(null)
      const [batchCopied, setBatchCopied] = React.useState(null)
      const [reloadAt, setReloadAt] = React.useState(0)
      // 勾选回调做成稳定引用：配合 SessionCard 的 memo，勾一张只重渲染一张。
      const toggleSel = React.useCallback((file) => {
        setSel(prev => {
          const n = Object.assign({}, prev)
          if (n[file]) delete n[file]
          else n[file] = true
          return n
        })
      }, [])
      const [timeRange, setTimeRange] = React.useState('all')
      // 列表排序：'time' 用 host 给的顺序（按诊断开始时间倒序，见 panel-host.js 的 listTraces），
      // 'value' 见下方 valueRankOf
      const [sortBy, setSortBy] = React.useState('time')
      // 切筛选就清空勾选与展开的批量指令：勾选只在「待升格」这一屏里有意义，
      // 带着上一屏的选择去点批量闭环，最容易把没看过的单一起标掉。
      React.useEffect(() => { setSel({}); setBatchCmd(null); setBatchCopied(null) }, [kbFilter])
      React.useEffect(() => {
        let alive = true
        host.call('ascend-traces-list', { sessionId: sessionId || null })
          .then(r => { if (alive) setState({ loading: false, data: r }) })
          .catch(() => { if (alive) setState({ loading: false, data: { ok: false, error: 'Host RPC 失败' } }) })
        return () => { alive = false }
      }, [sessionId, reloadAt])

      const base = { fontFamily: 'var(--font-sans)', fontSize: 'var(--t-base)', color: T.text }
      if (state.loading) return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 } },
          React.createElement('span', { style: { width: 8, height: 16, borderRadius: 'var(--r-xs)', background: 'var(--acc-blue)', display: 'inline-block' } }),
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-2xl)', fontWeight: 700 } }, '诊断状态')),
        React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 12 } },
          [64, 84, 74, 84, 78, 78].map((w, i) => React.createElement('span', { key: i, className: 'sleu-skel', style: { width: w, height: 26 } }))),
        [0, 1, 2, 3].map(i => React.createElement('div', { key: 'r' + i, className: 'sleu-skel', style: { height: 46, marginBottom: 8 } })))
      const r = state.data
      if (r && r.vocab) VOCAB_CACHE = r.vocab
      if (!r || !r.ok) {
        // 与诊断记录面板同一个句式：缺什么 + 下一步。旧版只有一行裸红字（`无法读取 traces/: …`），
        // 读者既不知道"这一层只读 traces/"也不知道该跑什么命令。
        return React.createElement('div', { className: 'sleu-ledger-empty', style: { ...base, color: T.error } },
          '读不到诊断记录：' + String((r && r.error) || '未知错误')
          + '。这一层只读 traces/；目录不在时先在仓库里跑一次诊断（/skill:diagnose）后刷新。')
      }

      let sessions = r.sessions || []
      // 待跟进**三类互斥**（此前重复计数：`status: in_progress` 的定义含"结论已给但用户在跟进"，
      // 于是"已给 fix 等回报"的单同时落进旧的 nActive 与 nPending，1 单显示成 2 项待跟进）：
      //   在查     = in_progress、**没有** pending 回报、且回报不是已生效 —— 诊断还没结论（含等用户补材料）→ 续接
      //   等回报   = 有 pending 回报（不论 status）—— 已给结论/方案等着验证 → 追问结果
      //   待标收尾 = 回报已 resolved 但 status 还停在 in_progress —— 验证过了、状态没更新 → 改 status
      // 三者之和 = 面板徽章的"待跟进"数（不再有重复计入的项；三条条件互斥，见下面各自的谓词）。
      const isClosedButOpen = s => s.status === 'in_progress' && s.feedback === 'resolved'
      const isLookingOf = s => s.status === 'in_progress' && fbKindOf(s) !== 'case' && !isClosedButOpen(s)
      const isAwaitingOf = s => fbKindOf(s) === 'case'
      const nLooking = sessions.filter(isLookingOf).length
      const nAwaiting = sessions.filter(isAwaitingOf).length
      const nClose = sessions.filter(isClosedButOpen).length
      // 计数按 caseKindOf 算：占位串那一类归「无对应案例」，不该被算成"新形态待沉淀"
      const nInKb = sessions.filter(s => caseKindOf(s) === 'case' && s.activeCaseInKb).length
      const nNew = sessions.filter(s => caseKindOf(s) === 'case' && !s.activeCaseInKb).length
      // 三条状态轴各自的待办（判据见 isOpenOf / isClosedOf / needSedOf / needPromoteOf）：
      //   未收尾 = 诊断还挂着，且既没有可沉淀结论、也没有待复核材料、也不是空壳——动作是继续查；
      //   待沉淀 = 有 kind=case 的沉淀候选（根因已形成可复用结论）、还没沉淀、命中的 case 不在库里
      //            （库中已有的再沉淀只会被 groom 判 covered_by）；动作是生成沉淀命令；
      //   待复核 = 有报告或只有 reference / triage 候选、没有 case 候选——动作是读一眼报告，
      //            根因定了补一条 case 候选，没定就继续查或标收尾；
      //   空记录 = 连一轮对话都没有——它不占筛选，只在列表上挂一个「空记录」徽标；
      //   待升格 = 草稿已提交、但来源诊断还没闭环——升格闸门会拦，与"诊断收尾"是两件事。
      const nOpen = sessions.filter(needWorkOf).length
      const nNeedSed = sessions.filter(needSedOf).length
      const nNeedReview = sessions.filter(needReviewOf).length
      const nSubmitted = sessions.filter(isSubmittedOf).length
      const nNeedPromote = sessions.filter(needPromoteOf).length
      const q = query.trim().toLowerCase()
      if (q) {
        sessions = sessions.filter(s =>
          (s.sessionId || '').toLowerCase().includes(q) ||
          (s.status || '').toLowerCase().includes(q) ||
          (s.framework || '').toLowerCase().includes(q) ||
          (s.platform || '').toLowerCase().includes(q) ||
          (s.category || '').toLowerCase().includes(q) ||
          (s.activeCase || '').toLowerCase().includes(q) ||
          // 工程师的第一动作是搜症状（报错词、算子名、平台）。问题背景就是那句话，
          // 它在副行显示却搜不到时，人会读成"没有同类案例"。
          (s.summarySnippet || '').toLowerCase().includes(q) ||
          (s.waitingFor || '').toLowerCase().includes(q) ||
          (s.lastOutput || '').toLowerCase().includes(q) ||
          // 收尾与沉淀状态也要能搜：它们是列表上的一等状态，不是只写在展开卡里的一句话。
          ((isOpenOf(s) ? '未闭环 ' : '') +
           (needSedOf(s) ? '待沉淀 有结论 ' + (isClosedOf(s) ? '已闭环 已收尾' : '未收尾') + ' ' : '') +
           (needReviewOf(s) ? '待复核 ' : '') +
           (isSkeletonOf(s) ? '空记录 ' : '') +
           (isSubmittedOf(s) ? '已交草稿 已沉淀 ' + (needPromoteOf(s) ? '待升格 未收尾 ' : '等整理 ') : '') +
           (sedStateOf(s) === 'submitted' ? '已沉淀' : '')).includes(q)
        )
      }
      if (kbFilter === 'kb') sessions = sessions.filter(s => caseKindOf(s) === 'case' && s.activeCaseInKb)
      if (kbFilter === 'new') sessions = sessions.filter(s => caseKindOf(s) === 'case' && !s.activeCaseInKb)
      if (kbFilter === 'miss') sessions = sessions.filter(s => caseKindOf(s) !== 'case')
      if (kbFilter === 'open') sessions = sessions.filter(needWorkOf)
      if (kbFilter === 'need-review') sessions = sessions.filter(needReviewOf)
      if (kbFilter === 'running') sessions = sessions.filter(isLookingOf)
      if (kbFilter === 'awaiting') sessions = sessions.filter(isAwaitingOf)
      if (kbFilter === 'close-pending') sessions = sessions.filter(isClosedButOpen)
      if (kbFilter === 'need-sed') sessions = sessions.filter(needSedOf)
      if (kbFilter === 'need-promote') sessions = sessions.filter(isSubmittedOf)
      // 按诊断开始时间过滤（`created_at`）：只留窗口内的单；没记开始时间的单不猜，直接排除。
      if (timeRange !== 'all') {
        const cut = Date.now() - Number(timeRange) * 86400000
        sessions = sessions.filter(s => {
          const t = s.createdAt ? new Date(s.createdAt).getTime() : NaN
          return !isNaN(t) && t >= cut
        })
      }
      // 「价值优先」：会话攒多以后，按时间排会把"值得先看的那几单"埋在最底下。
      // 判据（`valueRankOf` / `updatedTsOf`）放在 apply 作用域里与侧栏「诊断记录」共用一份——
      // 两处各写一份就会漂移，读者会得到两套"价值"。
      if (sortBy === 'value') {
        sessions = sessions.slice().sort((a, b) => valueRankOf(b) - valueRankOf(a) || updatedTsOf(b) - updatedTsOf(a))
      }
      // 待跟进三类见上方计数处注释（互斥）；徽章与横幅都用这三个数
      const badge = [
        (r.sessions || []).length + ' 会话',
        nInKb ? nInKb + ' 库中已有' : null,
        nNew ? nNew + ' 新形态' : null,
        nLooking ? nLooking + ' 在查' : null,
        nAwaiting ? nAwaiting + ' 等回报' : null,
        nClose ? nClose + ' 待标收尾' : null,
        nNeedSed ? nNeedSed + ' 待沉淀' : null,
        nNeedReview ? nNeedReview + ' 待复核' : null,
        nSubmitted ? nSubmitted + ' 已交草稿' : null,
      ].filter(Boolean).join(' · ')
      // 说明放 title：这几个词只有在点开时才需要，常驻在筛选条上会把一行 chip 读成文档。
      const kbChips = [
        { id: 'all', label: '全部' },
        { id: 'kb', label: '库中已有', title: '命中的 case 已在 knowledge/ 里' },
        { id: 'new', label: '新形态', title: '命中了某个 case，但库里还没有它' },
        { id: 'miss', label: '无对应案例', title: '知识库里没有这单对应的案例（未命中）' },
        { id: 'open', label: '未收尾' + (nOpen ? ' ' + nOpen : ''), title: '诊断还挂着，且没有可沉淀结论、没有待复核材料、也不是空壳——动作是继续查' },
        { id: 'need-sed', label: '待沉淀' + (nNeedSed ? ' ' + nNeedSed : ''), title: '有 case 类沉淀候选（= 根因已形成可复用结论）、还没沉淀，且命中的 case 不在库里——按这一屏一次生成批量沉淀命令' },
        { id: 'need-review', label: '待复核' + (nNeedReview ? ' ' + nNeedReview : ''), title: '有报告或只有 reference / triage 候选，没有 case 类候选：根因可能还没定。读一眼报告，定了补一条 case 候选，没定就继续查或标收尾' },
        { id: 'need-promote', label: '已交草稿' + (nSubmitted ? ' ' + nSubmitted : ''), title: '草稿已经交到 inbox、等知识整理（含来源诊断还没收尾的那批——它们在升格前会被检查拦下）' },
      ]

      // 空态：先说"这一屏为什么空"，再说下一步。筛选为空与"还没有任何诊断"是两件事——
      // 前者通常是这一类已经处理完，统一写"去跑一次 diagnose"会被读成数据没生成。
      const totalSessions = (r.sessions || []).length
      const FILTER_LABEL = { all: '全部', kb: '库中已有', new: '新形态', miss: '无对应案例', open: '未收尾', running: '在查', awaiting: '等回报', 'close-pending': '待标收尾', 'need-sed': '待沉淀', 'need-review': '待复核', 'need-promote': '已交草稿' }
      const EMPTY_HINT = {
        kb: '没有命中过知识库 case 的诊断。',
        new: '没有"命中 case、但库里还没有"的诊断。',
        miss: '没有"知识库里找不到对应案例"的诊断。',
        open: '没有需要继续查的单：还挂着的诊断都已产出结论、待复核材料，或草稿已交。',
        running: '没有还在查的单。',
        awaiting: '没有等回报的单。',
        'close-pending': '没有回报已生效、状态还没更新的单。',
        'need-sed': '没有可沉淀的单：有 case 类沉淀候选的诊断都已经沉淀过了。',
        'need-review': '没有待复核的单：有报告或 reference 候选、但还没产出 case 候选的诊断都复核过了。',
        'need-promote': '没有已交到 inbox 的草稿。做完沉淀（草稿进 inbox）后会出现在这里，等知识整理排期升格。',
      }
      const emptyTitle = q ? '没有匹配的会话'
        : (!totalSessions ? '还没有诊断记录'
          : (timeRange !== 'all' ? '该时间范围内没有会话'
            : ('「' + (FILTER_LABEL[kbFilter] || '当前筛选') + '」下没有会话')))
      const emptyHint = q ? '换个关键词，或点「全部」清掉筛选'
        : (!totalSessions ? '在对话里跑一次 /skill:diagnose，这里就会出现会话与完整轨迹'
          : (timeRange !== 'all' ? '放宽时间范围，或点「全部」清掉筛选。'
            : (EMPTY_HINT[kbFilter] || '点「全部」查看所有诊断。')))

      // 首屏要先回答"有什么在等我"——所以计数里把**待跟进**的两项单独提出来（进行中、待回报），
      // 而不是混在一串 "N 会话 · N 库中已有 …" 里让读者自己找
      const nFollow = nLooking + nAwaiting + nClose
      // 批量入口：面板只生成指令（与单卡一致），不直接写 trace。
      //  - 待沉淀：按筛选结果一次生成 to-postmortem 批量命令（每单各成一条草稿）；
      //  - 待升格：勾选后生成一条批量闭环命令，且只允许"已解决 · fix 生效"这一种结局
      //    （多结局混批会虚高解决率：置信度只认 resolved）。
      const batchBar = (function () {
        if (kbFilter === 'need-sed') {
          const ids = sessions.map(s => s.sessionId).filter(Boolean)
          if (!ids.length) return null
          const text = '用 /skill:to-postmortem 批量沉淀这些 session：' + ids.join('、')
            + '（trace 在 traces/<session>.yaml；每个 session 各成一条草稿，来源 trace 回写 sedimented.state: submitted）'
          return React.createElement('div', { style: { marginBottom: 8, padding: '8px 10px', border: '1px solid var(--hair)', borderRadius: 'var(--r-md)', background: T.bg2 } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
              React.createElement('span', { style: { fontSize: 'var(--t-sm)', color: T.text2 }, title: '范围 = 当前筛选（含搜索词）' }, '已闭环未沉淀 ' + ids.length + ' 单'),
              React.createElement('button', { type: 'button', style: batchCmd === 'sed' ? btnPurple : btnGhost, onClick: () => { setBatchCmd(batchCmd === 'sed' ? null : 'sed'); setBatchCopied(null) } },
                batchCmd === 'sed' ? '隐藏指令' : '批量沉淀这 ' + ids.length + ' 单'),
            ),
            batchCmd === 'sed' ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 } },
              React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg, border: '1px solid var(--hair)', borderRadius: 'var(--r-xs)', padding: '5px 8px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)', color: T.text, wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } }, text),
              React.createElement('button', { type: 'button', style: batchCopied === 'fail' ? btnRed : btnPurple, onClick: () => copyText(text).then(ok => setBatchCopied(ok ? 'sed' : 'fail')) },
                batchCopied === 'sed' ? '已复制' : (batchCopied === 'fail' ? '失败' : '复制')),
            ) : null,
          )
        }
        if (kbFilter === 'need-promote') {
          // 这一屏收全部已交草稿；批量标收尾只对"来源诊断还没收尾"的那些有意义
          // （已收尾的草稿没有要补的闭环证据，勾它们只会把状态再写一遍）。
          const submitted = sessions
          const list = submitted.filter(needPromoteOf)
          const drafts = (r && r.inboxDrafts) || []
          // 草稿在 inbox、但没有任何 trace 回写沉淀状态时，这一屏仍要说话——那正是"看不见的队列"。
          if (!submitted.length && !drafts.length) return null
          const chosen = list.filter(s => sel[s.file])
          const ids = chosen.map(s => s.sessionId).filter(Boolean)
          const text = '批量闭环以下 ' + ids.length + ' 单，结局都是「已解决 · fix 生效」：' + ids.join('、')
            + '。逐单：有命中 case 的标 status: resolved + feedback{outcome: resolved} 并写一条 feedback 事件；'
            + '未命中 case 的只标 status: resolved，不写 feedback；若 trace 里还留着 feedback.outcome（旧数据），一并清掉。'
          const allSelected = list.length > 0 && list.every(s => sel[s.file])
          return React.createElement('div', { style: { marginBottom: 8, padding: '8px 10px', border: '1px solid var(--hair)', borderRadius: 'var(--r-md)', background: T.bg2 } },
            React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginBottom: list.length ? 8 : 0 } },
              '已交草稿 ' + submitted.length + ' 单'
              + (list.length ? '，其中 ' + list.length + ' 单来源诊断还没收尾（升格前的检查会拦）' : '，都不卡：等知识整理排期升格')),
            drafts.length ? React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2, marginBottom: list.length ? 6 : 0 } },
              'inbox 里另有 ' + drafts.length + ' 份草稿没有对应的诊断记录（不是从某次诊断沉淀来的，或 source_session 回写漏了）：'
              + drafts.slice(0, 4).join('、') + (drafts.length > 4 ? ' 等' : '')) : null,
            list.length ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
              React.createElement('button', { type: 'button', style: btnGhost, onClick: () => { const n = {}; if (!allSelected) list.forEach(s => { n[s.file] = true }); setSel(n) } },
                allSelected ? '取消全选' : '全选这 ' + list.length + ' 单'),
              React.createElement('button', { type: 'button', disabled: !ids.length, style: !ids.length ? { ...btnGhost, opacity: 0.5, cursor: 'default' } : btnGhost, onClick: () => { if (!ids.length) return; setBatchCmd(batchCmd === 'close' ? null : 'close'); setBatchCopied(null) } },
                '批量标已解决' + (ids.length ? '（已选 ' + ids.length + ' 单）' : '')),
            ) : null,
            list.length ? React.createElement('div', { style: { marginTop: 4, fontSize: 'var(--t-tiny)', color: T.text2 } },
              '只勾真的验证过 fix 生效的单——批量标 resolved 会写进条目使用记录；没验证的先别勾。') : null,
            batchCmd === 'close' && ids.length ? React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 6, marginTop: 8 } },
              React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg, border: '1px solid var(--hair)', borderRadius: 'var(--r-xs)', padding: '5px 8px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)', color: T.text, wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } }, text),
              React.createElement('button', { type: 'button', style: batchCopied === 'fail' ? btnRed : btnPurple, onClick: () => copyText(text).then(ok => setBatchCopied(ok ? 'close' : 'fail')) },
                batchCopied === 'close' ? '已复制' : (batchCopied === 'fail' ? '失败' : '复制')),
            ) : null,
          )
        }
        return null
      })()

      // 横幅上的三个数各自可点：看到「2 个等回报」的第一反应是哪些单，不该再回头找筛选。
      const followChip = (n, label, id) => React.createElement('button', {
        type: 'button', 'aria-pressed': kbFilter === id ? 'true' : 'false', onClick: () => setKbFilter(kbFilter === id ? 'all' : id),
        title: '只看这一类', style: { ...btnGhost, padding: '1px 9px', borderRadius: 'var(--r-pill)' },
      }, n + ' 个' + label)
      return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, gap: 10, flexWrap: 'wrap' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 'var(--r-xs)', background: 'var(--acc-blue)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-2xl)', fontWeight: 700 } }, '诊断状态'),
          ),
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('button', { type: 'button', title: '重新读取 traces/——复制闭环指令去对话执行后，回来点这里', onClick: () => setReloadAt(n => n + 1), style: { ...btnGhost, padding: '3px 10px' } }, '刷新'),
            React.createElement('span', { title: badge + (typeof r.elapsedMs === 'number' ? ' · 列表耗时 ' + r.elapsedMs + ' ms（解析 ' + (r.parsed || 0) + ' 条 / 命中缓存 ' + (r.cached || 0) + ' 条' + (r.skipped ? ' / 跳过 ' + r.skipped + ' 条' : '') + '）' : ''), style: { fontSize: 'var(--t-sm)', color: T.text2, background: T.bg2, border: '1px solid var(--hair)', borderRadius: 'var(--r-pill)', padding: '3px 11px' } },
              nFollow ? (nFollow + ' 项待跟进') : ((r.sessions || []).length + ' 个会话')),
          ),
        ),
        // 待跟进提示：只在真有的时候出现，且给"下一步做什么"。
        // 三类各自对应一个动作（续接 / 追问结果 / 改 status），所以分开说；末尾一句点明这是两条轴，
        // 免得读者把"在查"与"等回报"读成同一件事的两句话。
        nFollow ? React.createElement('div', { style: { ...rise(0), display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '8px 12px', marginBottom: 10, background: 'var(--tint-amber)', border: '1px solid var(--hair)', borderRadius: 'var(--r-md)', fontSize: 'var(--t-md)', color: T.text } },
          React.createElement(Dot, { color: T.warn, size: 7 }),
          nLooking ? followChip(nLooking, '在查', 'running') : null,
          nLooking && (nAwaiting || nClose) ? React.createElement('span', { style: { color: T.text2 } }, '·') : null,
          nAwaiting ? followChip(nAwaiting, '等回报', 'awaiting') : null,
          nAwaiting && nClose ? React.createElement('span', { style: { color: T.text2 } }, '·') : null,
          nClose ? followChip(nClose, '待标收尾', 'close-pending') : null,
          React.createElement('span', { style: { color: T.text2, marginLeft: 'auto', fontSize: 'var(--t-sm)' } },
            '在查=诊断没结论（含等现场补材料）；等回报=结论已给、fix 没验证；待标收尾=回报已生效、状态还停在进行中｜卡片里点按钮生成指令 → 复制 → 粘到对话执行'),
          React.createElement('span', { className: 'sleu-mono', title: '面板包版本：与 dsh-plugins/dsh-sleuth-panels/package.json 一致。看到的不是这个版本 = 装的还是旧包，或浏览器缓存了旧 bundle', style: { color: T.text2, fontSize: 'var(--t-md2)', opacity: 0.75 } }, PANEL_VERSION),
        ) : null,
        // 工具栏（筛选 + 搜索 + 列头）**吸顶**：会话一多就得往下滚，工具与列头都不该滚走。
        // 列头进吸顶容器后，滚到任意位置都知道每列是什么（此前列头随列表一起滚掉）。
        React.createElement('div', { style: { position: 'sticky', top: 0, zIndex: 2, padding: '2px 0 8px', marginBottom: 4, background: T.bg, borderBottom: '1px solid var(--hair-strong)' } },
          React.createElement('div', { style: { display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' } },
            // 从横幅切进来的三类（在查/等回报/待标收尾）不在 chip 列表里，补一个可退出的当前项，
            // 否则切进去后整行没有任何一个 aria-pressed，读者不知道现在在看哪一类。
            ['running', 'awaiting', 'close-pending'].indexOf(kbFilter) >= 0
              ? React.createElement('button', {
                  type: 'button', className: 'sleu-chip', 'aria-pressed': 'true', title: '点一下回到全部',
                  onClick: () => setKbFilter('all'),
                }, (FILTER_LABEL[kbFilter] || '当前') + ' ×')
              : null,
            kbChips.map(c => React.createElement('button', {
              key: c.id, type: 'button', title: c.title || null, 'aria-pressed': c.id === kbFilter ? 'true' : 'false',
              onClick: () => setKbFilter(c.id), className: 'sleu-chip',
            }, c.label)),
          ),
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' } },
            React.createElement('div', { style: { position: 'relative', flex: 1, minWidth: 0 } },
              React.createElement('span', { 'aria-hidden': 'true', style: { position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', width: 10, height: 10, borderRadius: 'var(--r-pill)', border: '1.5px solid ' + T.text2, display: 'block' } }),
              React.createElement('input', {
                placeholder: '搜索会话号 / 状态 / 框架 / 背景', 'aria-label': '筛选会话', value: queryInput,
                // 输入框立刻回显，过滤延后 120ms：会话多时每个按键都重排列表会掉帧。
                onChange: e => {
                  const v = e.target.value
                  setQueryInput(v)
                  if (timer && typeof timer.timeout === 'function') {
                    if (typeof queryTimerDispose === 'function') queryTimerDispose()
                    queryTimerDispose = timer.timeout(() => setQuery(v), 120)
                  } else setQuery(v)
                },
                onKeyDown: e => { if (e.key === 'Escape') { if (typeof queryTimerDispose === 'function') queryTimerDispose(); setQueryInput(''); setQuery('') } },
                title: '可搜：会话号、状态、框架、平台、类别、定位到的 case、问题背景、待沉淀 / 待复核 / 已交草稿',
                style: { width: '100%', boxSizing: 'border-box', padding: '8px 30px 8px 30px', fontSize: 'var(--t-sm)', borderRadius: 'var(--r-md)', border: '1px solid var(--hair)', background: T.bg, color: T.text, transition: 'border-color var(--m-fast) var(--e-out)' },
              }),
              query ? React.createElement('button', {
                type: 'button', 'aria-label': '清空搜索', onClick: () => { if (typeof queryTimerDispose === 'function') queryTimerDispose(); setQueryInput(''); setQuery('') },
                style: { position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', border: 'none', background: 'transparent', color: T.text2, cursor: 'pointer', fontSize: 'var(--t-md)', lineHeight: 1, padding: '4px 6px' },
              }, '×') : null,
            ),
            React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)', whiteSpace: 'nowrap' } },
              q ? (sessions.length + ' / ' + totalSessions + ' 单') : (totalSessions + ' 单')),
            React.createElement('select', {
              value: timeRange, 'aria-label': '按诊断开始时间筛选',
              title: '按诊断开始时间（created_at）筛选',
              onChange: e => setTimeRange(e.target.value),
              style: { padding: '7px 8px', fontSize: 'var(--t-tiny)', borderRadius: 'var(--r-md)', border: '1px solid var(--hair)', background: T.bg, color: T.text, cursor: 'pointer' },
            }, [['all', '全部时间'], ['7', '近 7 天'], ['30', '近 30 天'], ['90', '近 90 天']].map(p => React.createElement('option', { key: p[0], value: p[0] }, p[1]))),
            // 排序与时间筛选并排：两个都是"这一屏看什么"的开关，分开摆会被当成两套设置。
            React.createElement('select', {
              value: sortBy, 'aria-label': '会话排序',
              title: '按时间 = 按诊断开始时间（created_at）倒序（默认）；按价值 = ' + VALUE_ORDER_TEXT,
              onChange: e => setSortBy(e.target.value),
              style: { padding: '7px 8px', fontSize: 'var(--t-tiny)', borderRadius: 'var(--r-md)', border: '1px solid var(--hair)', background: T.bg, color: T.text, cursor: 'pointer' },
            }, [['time', '排序：按时间'], ['value', '排序：按价值']].map(p => React.createElement('option', { key: p[0], value: p[0] }, p[1]))),
          ),
          batchBar,
          sessions.length ? React.createElement('div', { style: { display: 'grid', gridTemplateColumns: ROW_COLS, gap: 10, padding: '8px 16px 4px', marginTop: 4 } },
            ['状态', '会话', '框架 · 平台', '事件', '耗时', 'token', ''].map((h, i) =>
              React.createElement('span', {
                key: i,
                className: ['', '', 'sleu-c-fw', 'sleu-c-events', 'sleu-c-ms', 'sleu-c-tok', ''][i],
                title: i === 3 ? '斜杠左边是用户贴材料的条数，右边是 Agent 记录动作的条数' : (i === 5 ? '工具调用累计 token' : null),
                style: { fontSize: 'var(--t-tiny)', color: T.text2,
                         textAlign: (i >= 3 && i <= 5) ? 'right' : 'left', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' },
              }, h))) : null,
        ),
        sessions.length > 20 ? React.createElement('button', {
          type: 'button', className: 'sleu-fab', title: '回到顶部（会话较多）', 'aria-label': '回到顶部',
          onClick: () => {
            const behavior = REDUCED ? 'auto' : 'smooth'
            // 面板的滚动容器可能是祖先节点而不是 window —— 从触发元素往上找第一个可滚的祖先
            try {
              const el = (typeof document !== 'undefined' && document.activeElement) || null
              let node = el
              while (node && node !== document.body) {
                const ov = getComputedStyle(node).overflowY
                if ((ov === 'auto' || ov === 'scroll') && node.scrollHeight > node.clientHeight + 4) {
                  node.scrollTo({ top: 0, behavior: behavior }); return
                }
                node = node.parentElement
              }
              if (typeof window !== 'undefined' && window.scrollTo) window.scrollTo({ top: 0, behavior: behavior })
            } catch (e) { /* 滚动不可用时静默（按钮本身无副作用） */ }
          },
        }, '↑') : null,
        sessions.length === 0
          ? React.createElement('div', { style: { color: T.text2, padding: '32px 16px', textAlign: 'center', fontSize: 'var(--t-md)', lineHeight: 'var(--lh-prose)' } },
              React.createElement('div', { style: { fontSize: 'var(--t-lg)', fontWeight: 600, color: T.text, marginBottom: 6 } }, emptyTitle),
              emptyHint)
          : React.createElement('div', { className: 'sleu-list' },
              sessions.map(s => React.createElement(SessionCard, {
                key: s.file, session: s, sessionId: sessionId,
                // 当前会话号：卡片据此把「打开会话」换成「当前会话」，避免一个点了没反应的按钮。
                currentSession: (function () {
                  const sn = sessionListSnapshot()
                  return sn && sn.current ? String(sn.current) : ''
                })(),
                selectable: kbFilter === 'need-promote',
                selected: !!sel[s.file],
                onToggleFile: toggleSel,
                // 重建本机明细之后重取列表：否则列表两列还停在「—」，要等用户手动刷新才变
                onRebuilt: () => setReloadAt(n => n + 1),
              })),
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
      // 阈值与告警线都从数据里读（`metrics/gates.yaml` 的 health 段，host 一并带下来）。
      // 读不到时 host 给兜底值并把 thresholdsFrom 标成 builtin——这里在标题上写明，
      // 不让读者把兜底值当成"库里声明的线"。
      const th = (health && health.thresholds) || null
      const thBuiltin = !!(health && health.thresholdsFrom === 'builtin')
      const thNote = thBuiltin ? '；阈值来自内置兜底（gates.yaml 的 health 段没读到）' : ''
      if (c.lowConfidence) caseRows.push(React.createElement(MetricRow, { key: 'lc',
        label: '低置信占比（评分 <' + (th ? th.case_low_confidence_score : '0.5') + '）',
        value: c.lowConfidence + ' / ' + c.total + ' (' + pct(c.lowConfidence, c.total) + ')',
        title: '低置信占比超过 ' + (th ? th.case_low_confidence_alert_ratio : '0.4') + ' 会告警' + thNote,
        warn: (c.lowConfidence / c.total) > (th ? th.case_low_confidence_alert_ratio : 0.4) }))
      if (c.byCategory && Object.keys(c.byCategory).length) {
        caseRows.push(React.createElement(MetricRow, { key: 'bc', label: 'category 分布', value: Object.keys(c.byCategory).map(k => (CATEGORY_LABELS[k] || k) + ' ' + c.byCategory[k]).join(' · ') }))
      }
      const refRows = []
      if (r.total) refRows.push(React.createElement(MetricRow, { key: 'rt', label: 'reference 总数', value: r.total }))
      if (r.draftCount !== undefined) refRows.push(React.createElement(MetricRow, { key: 'rd', label: '未审草稿（draft）', value: r.draftCount + ' / ' + r.total, warn: r.draftCount > 0 }))
      if (r.staleCount !== undefined) refRows.push(React.createElement(MetricRow, { key: 'rs',
        label: '过期未核（>' + (th ? th.reference_stale_days : '90') + ' 天）',
        title: '先验的 last_verified 超过 ' + (th ? th.reference_stale_days : '90') + ' 天算过期' + thNote,
        value: r.staleCount, warn: r.staleCount > 0 }))
      if (r.byType && Object.keys(r.byType).length) {
        const top = Object.keys(r.byType).slice(0, 4)
        refRows.push(React.createElement(MetricRow, { key: 'rtp', label: 'type 分布（前 4）', value: top.map(t => t + ' ' + r.byType[t]).join(' · ') }))
      }
      if (r.caseDerivedCount !== undefined) refRows.push(React.createElement(MetricRow, { key: 'rcd', label: 'case 提炼（有来源）', value: r.caseDerivedCount + ' / ' + r.total }))

      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 'var(--r-lg)', marginBottom: 12, overflow: 'hidden', boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('div', { style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 'var(--r-xs)', background: 'var(--acc-green)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-lg)', fontWeight: 700 } }, '知识库健康'),
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
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 'var(--r-lg)', marginBottom: 12, overflow: 'hidden', boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('div', { style: { padding: '12px 14px' } },
          React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 'var(--r-xs)', background: 'var(--acc-purple)', display: 'inline-block' } }),
            React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-lg)', fontWeight: 700 } }, '流程闭环'),
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
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 'var(--r-lg)', padding: '11px 14px', marginBottom: 12, boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' } },
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-lg)', fontWeight: 700 } }, '本期变化'),
          React.createElement('span', { className: 'sleu-chip', style: { color: km.color, border: '1px solid ' + km.color, borderRadius: 'var(--r-pill)', padding: '1px 9px', fontSize: 'var(--t-tiny)', fontWeight: 700 } }, km.label),
          React.createElement('span', { style: { fontFamily: 'var(--font-mono)', fontSize: 'var(--t-md)', fontWeight: 700 } }, cur.period),
          d.prevPeriod
            ? React.createElement('span', { style: { fontSize: 'var(--t-sm)', color: T.text2 } }, '对比 ' + d.prevPeriod)
            : React.createElement('span', { style: { fontSize: 'var(--t-sm)', color: T.text2 } }, '无上一期可比'),
          React.createElement('span', { style: { marginLeft: 'auto', fontSize: 'var(--t-sm)', color: T.text2 } },
            d.moved.length ? d.moved.length + ' 项变动 · ' + d.same + ' 项持平' : '与上期完全一致'),
        ),
        d.moved.length
          ? React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
              d.moved.map(m => {
                const meta = META[m.kind] || META.change
                return React.createElement('div', { key: m.key, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', background: T.bg2, borderRadius: 'var(--r-sm)', fontSize: 'var(--t-sm)', flexWrap: 'wrap' } },
                  React.createElement('span', { style: { color: meta.color, fontWeight: 700, fontSize: 'var(--t-tiny)', minWidth: 52 } }, meta.label),
                  React.createElement('span', { style: { color: T.text2, flex: '1 1 130px', minWidth: 0 } }, m.label),
                  unread(m.key) ? React.createElement('span', { title: unread(m.key) === true ? '分母为 0：这个数不可解读' : unread(m.key), style: tinyBadge('var(--d-purple)') }, '不可解读') : null,
                  React.createElement('span', { style: { fontFamily: 'var(--font-mono)', color: T.text } },
                    m.kind === 'change' ? (m.from + ' → ' + m.to) : (m.kind === 'new' ? m.to : m.from)),
                  m.delta !== null && m.delta !== undefined ? React.createElement('span', { style: { fontSize: 'var(--t-tiny)', fontWeight: 700,
                    color: m.direction === 'bad' ? T.error : (m.direction === 'good' ? T.success : T.text2) } },
                    (m.rate ? ((m.delta > 0 ? '+' : '') + (m.delta * 100).toFixed(0) + '%') : ((m.delta > 0 ? '+' : '') + m.delta))) : null,
                )
              }),
            )
          : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2 } }, '本期各指标与上一期逐项相同——没有新变化可读。'),
      )
    }

    // ============ 单期卡片（可折叠） ============
    // 卡头是 <button>（键盘可达 + aria-expanded），与 ev-panel 的 IdeaCard 同一约定
    function PeriodCard({ p, open, onToggle, isUnreadable, strengthOf }) {
      const unread = isUnreadable || (() => false)
      const km = kindMeta[p.kind] || kindMeta.example
      const metricKeys = Object.keys(p.metrics || {})
      // 收起态摘要取**最该先看的几个**，不是文件里前三个键（那是字段顺序，不是重要性）。
      // 误诊率与反馈捕获是"这周质量如何"的直接答案，原来恰好都不在里面。
      const PRIORITY = ['misdiagnosis_rate', 'feedback_capture', 'tier2_hit', 'sessions_total', 'routed_accuracy', 'sediment_total']
      const ordered = PRIORITY.filter(k => k in (p.metrics || {}))
        .concat(metricKeys.filter(k => PRIORITY.indexOf(k) < 0))
      const summary = ordered.slice(0, 4).map(k => (METRIC_LABELS[k] || k) + ' ' + metricValue(p.metrics[k]).text).join(' · ')
      const nUnread = metricKeys.filter(k => unread(k)).length
      return React.createElement('div', { style: { background: T.bg, border: '1px solid ' + T.border, borderRadius: 'var(--r-lg)', marginBottom: 10, overflow: 'hidden', boxShadow: '0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)' } },
        React.createElement('button', {
          type: 'button', 'aria-expanded': !!open, onClick: onToggle,
          style: { width: '100%', padding: open ? '12px 16px 8px' : '10px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', background: 'transparent', border: 'none', textAlign: 'left', color: T.text, font: 'inherit' },
        },
          React.createElement(Chevron, { open: open, color: km.color }),
          React.createElement('span', { className: 'sleu-chip', style: { color: km.color, border: '1px solid ' + km.color, borderRadius: 'var(--r-pill)', padding: '1px 10px', fontSize: 'var(--t-tiny)', fontWeight: 700, letterSpacing: '.04em' } }, km.label),
          React.createElement('span', { style: { fontWeight: 700, fontSize: 'var(--t-md)', fontFamily: 'var(--font-mono)' } }, p.period),
          p.recorded_at ? React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-sm)' } }, '记录 ' + p.recorded_at) : null,
          nUnread ? React.createElement('span', { title: '该期有 ' + nUnread + ' 项指标分母为 0（不可解读）', style: tinyBadge('var(--d-purple)') }, nUnread + ' 项不可解读') : null,
          !open && summary ? React.createElement('span', { title: summary, style: { marginLeft: 'auto', color: T.text2, fontSize: 'var(--t-md)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '55%' } }, summary) : null,
          open ? null : React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-sm)' } }, metricKeys.length + ' 项'),
        ),
        open ? React.createElement('div', { style: { padding: '0 16px 12px' } },
          km.note ? React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-sm)', marginBottom: 4, borderLeft: '2px solid var(--hair)', paddingLeft: 8 } }, km.note) : null,
          p.title ? React.createElement('div', { style: { color: T.text, fontSize: 'var(--t-md)', marginTop: 3, lineHeight: 'var(--lh-base)' } }, plainNote(p.title)) : null,
          p.source ? React.createElement('div', { style: { color: T.text2, fontSize: 'var(--t-md)', marginTop: 3, wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } }, '来源: ' + plainNote(p.source)) : null,
          metricKeys.length ? React.createElement('div', { style: { marginTop: 9, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 12px' } },
            metricKeys.map(k => {
              const v = p.metrics[k]
              const total = ratioTotal(v)
              const small = total !== null && total > 0 && total < 5
              return React.createElement(MetricRow, { key: k, label: METRIC_LABELS[k] || k, value: fmtVal(v), small: small, unreadable: !!unread(k), unreadableWhy: unread(k) === true ? null : unread(k), strength: (strengthOf || {})[k] || null })
            }),
          ) : null,
          p.notes && p.notes.trim() ? React.createElement('div', { style: { marginTop: 9, padding: '7px 10px', background: 'color-mix(in srgb, ' + T.brand + ' 5%, transparent)', borderLeft: '3px solid ' + T.brand, borderRadius: 'var(--r-xs)', fontSize: 'var(--t-md)', color: T.text2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 'var(--lh-base)' } },
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
      if (!verdict) return { level: 'warn', label: '体检读取中', color: T.text2, accent: 'var(--acc-gray)', note: '体检结果尚未返回' }
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
      return React.createElement('div', { style: { ...rise(0), display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '7px 11px', marginBottom: 9, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', fontSize: 'var(--t-md)', color: T.text2 } },
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
          style: { width: '100%', display: 'flex', alignItems: 'baseline', gap: 7, padding: '9px 12px', border: 'none', cursor: 'pointer', textAlign: 'left', color: T.text, font: 'inherit' },
        },
          React.createElement('span', { style: { color: color, fontWeight: 700, fontSize: 'var(--t-md)', flexShrink: 0, lineHeight: '20px' } }, iconFor(row.level)),
          React.createElement('span', { className: 'sleu-chip', style: { fontSize: 'var(--t-tiny)', color: T.text2, flexShrink: 0, lineHeight: '20px', border: '1px solid ' + T.border, borderRadius: 'var(--r-pill)', padding: '0 7px' } }, faceLabel),
          React.createElement('span', { style: { flex: 1, minWidth: 0, fontSize: 'var(--t-base)', lineHeight: 'var(--lh-base)', wordBreak: 'break-word', color: T.text } }, plain),
          React.createElement(Chevron, { open: open, color: T.text2 }),
        ),
        open ? React.createElement('div', { style: { padding: '2px 12px 12px 30px', fontSize: 'var(--t-md)', lineHeight: 'var(--lh-base)' } },
          // 判据证据行：技术文案（判据名 / 格子数 / 指标名）——给要回查配置的人
          React.createElement(SectionLabel, null, '判据出处'),
          React.createElement('div', { className: 'sleu-mono', style: { fontSize: 'var(--t-sm)', color: T.text2, lineHeight: 'var(--lh-base)', wordBreak: 'break-word' } }, row.text),
          row.action ? React.createElement('div', { style: { color: T.text, marginTop: 10 } },
            React.createElement(SectionLabel, null, '下一步动作'),
            row.action) : null,
          cmd ? React.createElement('div', { style: { marginTop: row.action ? 9 : 0 } },
            React.createElement(SectionLabel, null, '可复制指令'),
            React.createElement('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 6 } },
              React.createElement('code', { style: { flex: 1, userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 'var(--r-xs)', padding: '6px 8px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)', wordBreak: 'break-word', lineHeight: 'var(--lh-base)', color: T.text } }, cmd.command),
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
        ? React.createElement('span', { style: { color: T.warn, fontSize: 'var(--t-sm)' } }, error)
        : (pending
            ? React.createElement('span', { style: { fontSize: 'var(--t-md)', color: T.text2 } }, '体检结果读取中…（结论未到之前，这里不显示"无阻塞项"）')
            : (shown.length === 0
            ? React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 'var(--t-md)', color: T.text2 } },
                React.createElement('span', { style: { color: T.success, fontWeight: 700 } }, '✓'),
                '本期无阻塞项 · ',
                // 配置文件名对读者没意义（那是维护者回查用的），收进 title；正文只说"检查了几条"
                React.createElement('span', { title: '判据与阈值定义在 metrics/gates.yaml（每一项都可展开回查）' },
                  '按 ' + findings.length + ' 条判据检查，全部通过'))
            : React.createElement('span', { style: { fontSize: 'var(--t-md)', color: T.text2 } },
                React.createElement('span', { title: '判据与阈值定义在 metrics/gates.yaml（每一项都可展开回查）' },
                  '按 ' + findings.length + ' 条判据检查：'),
                React.createElement('b', { style: { color: T.error } }, ' ' + fail.length + ' 项需要处理'),
                ' · ',
                React.createElement('b', { style: { color: T.warn } }, warn.length + ' 项提示'),
                ' · ' + okN + ' 项正常')))
      return React.createElement('div', { className: 'sleu-card', style: { ...rise(0), border: '1px solid var(--hair)', borderTop: '2px solid ' + ((error || pending) ? T.border : (fail.length ? 'var(--acc-red)' : 'var(--acc-green)')), borderRadius: 'var(--r-lg)', background: T.bg, backgroundImage: 'var(--surf)', marginBottom: 8, overflow: 'hidden' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', flexWrap: 'wrap' } },
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-lg)', fontWeight: 700 } }, '现在什么坏了'),
          head,
          (error || pending) ? null : React.createElement('span', { style: { marginLeft: 'auto', color: T.text2, fontSize: 'var(--t-sm)' } }, '点开看证据与下一步'),
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
      return React.createElement('div', { style: { ...rise(1), border: '1px solid var(--hair)', borderLeft: '2px solid ' + T.warn, borderRadius: 'var(--r-md)', background: T.bg, padding: '10px 12px', marginBottom: 10 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } },
          React.createElement(Dot, { color: T.warn, size: 7 }),
          React.createElement('span', { style: { fontSize: 'var(--t-md)', fontWeight: 700, color: T.text } }, '本轮判据不完整'),
          React.createElement('span', { style: { fontSize: 'var(--t-md)', color: T.text, lineHeight: 'var(--lh-base)' } }, headline),
        ),
        React.createElement('div', { style: { marginTop: 6, fontSize: 'var(--t-md)', color: T.text2, lineHeight: 'var(--lh-base)' } },
          '所以在这次检查里，',
          React.createElement('b', { style: { color: T.text } }, '「没有报出越界」不等于「没有越界」'),
          '——只是那几项没被判。其它判据的结论仍然有效。'),
        React.createElement('button', {
          type: 'button', 'aria-expanded': detailOpen,
          onClick: () => setDetailOpen(!detailOpen),
          style: { marginTop: 7, background: 'transparent', border: 'none', padding: 0, fontSize: 'var(--t-md)', color: T.text2, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, font: 'inherit' },
        },
          React.createElement(Chevron, { open: detailOpen, color: T.text2 }),
          '为什么没跑 / 怎么复现',
        ),
        detailOpen ? React.createElement('div', { style: { marginTop: 6, paddingTop: 7, borderTop: '1px dashed ' + T.border, fontSize: 'var(--t-md)', color: T.text2, lineHeight: 'var(--lh-base)' } },
          cov.gates_total ? React.createElement('div', null, '判据覆盖面：闸门 ' + cov.gates_evaluated + '/' + cov.gates_total
            + (cov.readability_total ? ' · 数字可信度 ' + cov.readability_evaluated + '/' + cov.readability_total : '')) : null,
          items.length ? React.createElement('div', { style: { marginTop: 4 } },
            items.map((b, i) => React.createElement('div', { key: i, style: { wordBreak: 'break-word' } }, '· ' + b))) : null,
          React.createElement('div', { style: { marginTop: 5 } },
            '复现：',
            React.createElement('code', { style: { userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 'var(--r-xs)', padding: '1px 6px', fontFamily: 'var(--font-mono)' } }, 'python3 scripts/metrics_health.py'),
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
          style: { width: '100%', display: 'flex', alignItems: 'center', gap: 7, padding: '6px 10px', background: 'transparent', border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', cursor: 'pointer', color: T.text2, fontSize: 'var(--t-md)', font: 'inherit', transition: DUR ? 'border-color .15s ' + EASE : 'none' },
        },
          React.createElement(Chevron, { open: open, color: T.text2 }),
          React.createElement('span', { style: { fontWeight: 700, color: T.text } }, '闭环检验'),
          React.createElement('span', null, faces.join(' · ')),
          React.createElement('span', { style: { marginLeft: 'auto' } }, nFail + ' ✗ · ' + nWarn + ' ! · ' + findings.length + ' 项'),
        ),
        open ? React.createElement('div', { style: { marginTop: 7, padding: '8px 11px', background: T.bg, border: '1px solid ' + T.border, borderRadius: 'var(--r-md)' } },
          findings.map((f, i) => React.createElement('div', { key: i, style: { display: 'flex', gap: 8, padding: '3px 0', fontSize: 'var(--t-md)', lineHeight: 'var(--lh-base)', borderBottom: i === findings.length - 1 ? 'none' : '1px dashed ' + T.border } },
            React.createElement('span', { style: { color: colorFor(f.level), fontWeight: 700, width: 12, flexShrink: 0 } }, iconFor(f.level)),
            React.createElement('span', { style: { color: T.text2, minWidth: 62, flexShrink: 0 } }, f.face),
            React.createElement('span', { style: { flex: 1, minWidth: 0, color: T.text, wordBreak: 'break-word' } }, f.text),
          )),
          React.createElement('div', { style: { marginTop: 6, fontSize: 'var(--t-md)', color: T.text2 } },
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
          style: { color: T.text2, fontSize: 'var(--t-md)', flexShrink: 0 },
        }, rows.length ? '趋势待积累' : '无历史')
      }
      const last = rows.slice(-6)
      const vals = last.map(r => r.count)
      const max = Math.max(...vals, 1)
      const delta = vals[vals.length - 1] - vals[0]
      const peakIdx = vals.indexOf(Math.max(...vals))
      // 这根微条画的是**条数**，而判据量是**token**——同一行两个单位会被读成"和主数字比"。
      // 条数线已退役（gates.yaml 的 cell_read_* 说明），所以这里**不按它上色**，
      // 只作"这条路在不在长"的观察，标题里写明它是条数。
      return React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 } },
        React.createElement('span', { className: 'sleu-bars', title: '条数趋势（仅观察，不参与判据；判据按 token，见左边的数）\n' + last.map(r => r.period + ': ' + r.count + ' 条').join('\n') },
          last.map((r, i) => React.createElement('i', {
            key: i,
            className: 'sleu-bar dim',
            style: { height: Math.max(2, Math.round((vals[i] / max) * 18)) + 'px' },
          })),
        ),
        React.createElement('span', {
          style: { fontFamily: 'var(--font-mono)', fontSize: 'var(--t-md)', color: delta > 0 ? T.warn : T.text2, flexShrink: 0 },
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
      return React.createElement('div', { className: 'sleu-card', style: { ...rise(1), border: '1px solid var(--hair)', borderRadius: 'var(--r-lg)', background: T.bg, backgroundImage: 'var(--surf)', marginBottom: 8, overflow: 'hidden' } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', flexWrap: 'wrap' } },
          React.createElement('span', { style: { width: 8, height: 16, borderRadius: 'var(--r-xs)', background: 'var(--acc-amber)', display: 'inline-block' } }),
          React.createElement('span', { className: 'sleu-title', style: { fontSize: 'var(--t-lg)', fontWeight: 700 } }, '容量台账'),
          React.createElement('span', { style: { fontSize: 'var(--t-md)', color: T.text2 } },
            '逐格：查一次问题要读进来多少 token（评估线 ' + (softTok === undefined ? '—' : softTok)
            + (hardTok === undefined ? '' : ' / 硬线 ' + hardTok) + '，数值读 metrics/gates.yaml）'),
          hot.length ? React.createElement('span', { style: { marginLeft: 'auto' } }, pill(hot.length + ' 格越界', T.error)) 
                     : React.createElement('span', { style: { marginLeft: 'auto' } }, pill('全部格子正常', T.success)),
        ),
        React.createElement('div', { style: { padding: '0 12px 10px', display: 'flex', flexDirection: 'column', gap: 4 } },
          shown.map((c, i) => React.createElement(CapacityCell, { key: i, cell: c, periods: periods })),
          cells.length > shown.length
            ? React.createElement('div', { style: { fontSize: 'var(--t-md)', color: T.text2, paddingTop: 2 } }, '其余 ' + (cells.length - shown.length) + ' 格正常（未展开）')
            : null,
        ),
      )
    }
    function CapacityCell({ cell, periods }) {
      // 判据量是**读入 token**（软线 8000 / 硬线 20000，来自 gates.yaml）；条数退成括号里的观察值。
      // 进度条的分母取**硬线**，所以 40% 的条可能已经挂了「超评估线」的徽标（软线在 40% 处）——
      // 读者会以为徽标错了。两条线都在条上画刻度，徽标才和条对得上。
      const cap = cell.hard_tok || cell.soft_tok || 0
      const ratio = cap > 0 && cell.tok != null ? cell.tok / cap : 0
      const softPct = cap > 0 && cell.soft_tok ? Math.min(100, Math.round(cell.soft_tok / cap * 100)) : null
      const over = cell.soft || cell.hard
      const color = cell.hard ? 'var(--acc-red)' : (cell.soft ? 'var(--acc-amber)' : 'var(--acc-green)')
      const dash = cap > 0 ? Math.min(100, Math.round(ratio * 100)) : 0
      return React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--t-sm)' } },
        React.createElement('span', { style: { width: 6, height: 6, borderRadius: 'var(--r-pill)', background: color, flexShrink: 0 } }),
        React.createElement('span', { title: cell.namespace + ' · ' + cell.category, style: { flex: '1 1 128px', minWidth: 0, color: over ? T.text : T.text2, fontWeight: over ? 700 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)', fontSize: 'var(--t-sm)' } },
          cell.namespace + ' · ' + cell.category),
        React.createElement('span', { title: '分母是硬线 ' + (cell.hard_tok || '—') + ' tok；竖线是软线 ' + (cell.soft_tok || '—') + ' tok', style: { position: 'relative', width: 74, height: 5, borderRadius: 'var(--r-pill)', background: T.bg2, overflow: 'hidden', flexShrink: 0 } },
          React.createElement('span', { style: { display: 'block', width: dash + '%', height: '100%', background: color, transition: DUR ? 'width .3s ' + EASE : 'none' } }),
          softPct ? React.createElement('span', { style: { position: 'absolute', left: softPct + '%', top: 0, bottom: 0, width: 1, background: 'var(--acc-amber)', opacity: 0.9 } }) : null),
        React.createElement('span', { style: { width: 72, textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600, color: over ? color : T.text, flexShrink: 0 } },
          cell.tok != null ? cell.tok + ' tok' : '—',
          React.createElement('span', { style: { color: T.text2, fontWeight: 400 } }, '（' + cell.count + ' 条）')),
        React.createElement(CapacityTrend, { periods: periods, cell: cell, color: color }),
        cell.hard ? React.createElement('span', { style: tinyBadge('var(--d-red)') }, '超硬线') : (cell.soft ? React.createElement('span', { style: tinyBadge('var(--d-amber)') }, '超评估线') : null),
      )
    }

    // ============ 累计读数的面板（设计文档 3.7 的第二张表）============
    // 首屏先答四个问题：覆盖了哪些会话、哪个读数不可解读、哪些条目在变差、本期该做什么。
    // 数据只有两个入口：生成物 `metrics/entry-activity/<部署>.yaml`（条目使用的读入口）与体检判决
    // （`metrics_health.py --json`）。读不到生成物时**只报缺件与重建命令**，不去解析源文件
    // `metrics/entry-activity.d/*.yaml` 自行求和。
    function EntryActivityBoard({ ea, health, verdict, onCopy, copied }) {
      if (!ea) return null
      const refTitles = (health && health.references && health.references.titles) || null
      const caseTotal = (health && health.cases && typeof health.cases.total === 'number') ? health.cases.total : null
      const copyBtn = (text, key) => React.createElement('button', {
        type: 'button', onClick: () => onCopy(text, key),
        style: { background: 'transparent', border: '1px solid ' + T.border, color: T.text2, borderRadius: 'var(--r-pill)', padding: '0 8px', fontSize: 'var(--t-tiny)', cursor: 'pointer', flexShrink: 0 },
      }, copied === key ? '已复制' : '复制')
      if (!ea.ok) {
        return React.createElement(Block, { title: '累计读数', accent: 'var(--acc-amber)' },
          React.createElement(MissingProduct, {
            what: '条目使用记录的生成物（' + ea.dir + '/<部署>.yaml）',
            path: (ea.files && ea.files.length ? ea.dir + '/' + ea.files.join('、') : ea.dir + '/<部署>.yaml'),
            rebuild: ea.rebuild, detail: ea.error,
          }))
      }
      // —— ① 覆盖 ——
      const wk = ea.weeks.length ? ea.weeks[ea.weeks.length - 1] : null
      const cover = React.createElement(Block, {
        title: '累计读数', accent: 'var(--acc-blue)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, ea.file || ''),
      },
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
          React.createElement(Cell, { label: '部署', value: ea.covered.deployment, mono: true }),
          React.createElement(Cell, { label: '期号', value: ea.weeks.length ? ea.weeks.join('、') : null, note: ea.weeks.length ? '共 ' + ea.weeks.length + ' 期' : '生成物没记期号' }),
          React.createElement(Cell, { label: '记录运行次数', value: ea.covered.runs !== null ? thousands(ea.covered.runs) + ' 次' : null }),
          React.createElement(Cell, { label: '检出', value: ea.covered.checkouts.length ? ea.covered.checkouts.join('、') : null, mono: true }),
          React.createElement(Cell, { label: '本机明细', value: ea.localDetailCount !== null ? thousands(ea.localDetailCount) + ' 份' : null, note: '每份 = 一次诊断（与上面的运行次数不是一个量）' }),
          React.createElement(Cell, { label: '全库案例', value: caseTotal !== null ? thousands(caseTotal) + ' 条' : null, note: '读侧视图里的条目数，用作零选中的分母' }),
        ))
      // —— ② 不可解读：缺分母的读数（不写 0）——
      const unread = []
      const rd = (verdict && verdict.readability) || {}
      for (const k of Object.keys(rd)) {
        if (rd[k] && rd[k].readable === false) unread.push({ label: rd[k].label || k, why: rd[k].why || '分母为 0' })
      }
      if (!verdict) unread.push({ label: '缺分母的读数', why: '体检判决不可用或还没回来：哪条读数缺分母、缺的是哪个，这一步判不了' })
      if (!ea.weeks.length) unread.push({ label: '本期增量', why: '生成物里没有任何期号，读不出"本期"' })
      if (caseTotal === null) unread.push({ label: '长期零选中的分母', why: '知识库读侧视图读不到（knowledge/_index/*.list），全库案例数取不到' })
      if (ea.caseMetaError) unread.push({ label: '条目标题', why: ea.caseMetaError + '：标题与分数读不到，排行仍按 id 与计数显示' })
      // —— ④ 两张榜的数据 ——
      const metaOf = (id) => (ea.caseMeta && ea.caseMeta[id]) ? ea.caseMeta[id] : null
      const titleOf = (id) => {
        const m = metaOf(id)
        if (m && m.title) return m.title
        if (refTitles && refTitles[id]) return refTitles[id]
        return null
      }
      const nText = (v) => (v === null || v === undefined) ? NOT_RECORDED : String(v)
      const caseCounts = (c) => '选中 ' + nText(c.selected) + ' · 读正文 ' + nText(c.loaded) + ' · 解决 ' + nText(c.resolved)
        + ' · 误诊 ' + nText(c.misdiagnosed) + ' · 自证 ' + nText(c.selfResolved) + ' · 排除 ' + nText(c.excluded)
      const refCounts = (r) => '查询 ' + nText(r.lookups) + ' · 命中 ' + nText(r.hit) + ' · 未命中 ' + nText(r.miss) + ' · 未查 ' + nText(r.skipped)
      const weeklyCases = []
      const weeklyRefs = []
      if (wk) {
        for (const c of ea.cases) {
          if (c.baseline) continue
          const w = c.byWeek[wk] || {}
          const cw = {
            id: c.id, title: titleOf(c.id), baseline: c.baseline,
            selected: w.selected === undefined ? 0 : w.selected, loaded: w.loaded === undefined ? 0 : w.loaded,
            resolved: w.resolved === undefined ? 0 : w.resolved, misdiagnosed: w.misdiagnosed === undefined ? 0 : w.misdiagnosed,
            selfResolved: w.selfResolved === undefined ? 0 : w.selfResolved, excluded: w.excluded === undefined ? 0 : w.excluded,
          }
          const sum = (cw.selected || 0) + (cw.loaded || 0) + (cw.resolved || 0) + (cw.misdiagnosed || 0) + (cw.excluded || 0)
          if (sum > 0) weeklyCases.push(cw)
        }
        for (const r of ea.references) {
          const w = r.byWeek[wk] || {}
          const rw = {
            id: r.id, title: titleOf(r.id),
            lookups: w.lookups === undefined ? 0 : w.lookups, hit: w.hit === undefined ? 0 : w.hit,
            miss: w.miss === undefined ? 0 : w.miss, skipped: w.skipped === undefined ? 0 : w.skipped,
            lastWeek: r.lastWeek,
          }
          if ((rw.lookups || 0) + (rw.hit || 0) + (rw.miss || 0) > 0) weeklyRefs.push(rw)
        }
        weeklyCases.sort((a, b) => (b.selected + b.excluded) - (a.selected + a.excluded))
        weeklyRefs.sort((a, b) => b.lookups - a.lookups)
      }
      const cumCases = ea.cases.slice()
        .sort((a, b) => (b.selected || 0) - (a.selected || 0) || String(a.id).localeCompare(String(b.id)))
        .map(c => Object.assign({}, c, { title: titleOf(c.id) }))
      const cumRefs = ea.references.slice()
        .sort((a, b) => (b.lookups || 0) - (a.lookups || 0) || String(a.id).localeCompare(String(b.id)))
        .map(r => Object.assign({}, r, { title: titleOf(r.id) }))
      // 样本量：案例按选中次数、先验按查询次数。小于 5 的标「小样本」——计数照读，比率不要读。
      const sampleOf = (x, kind) => kind === 'ref'
        ? (x.lookups || 0)
        : (x.selected === null || x.selected === undefined ? 0 : x.selected) + (x.resolved || 0) + (x.misdiagnosed || 0)
      // 「最后」列：案例行读 last_hit，先验行读 recent 里最近一次运行所处的周。
      // 两条"没有值"的原因要分开说——「还没有解决或误诊的记录」是**真实状态**，
      // 「本次没记」是生成物没写下这一格；写成一个词会让读者以为后者也只是"还没有"。
      const lastTextOf = (x, kind) => {
        const v = kind === 'case' ? x.lastHit : x.lastWeek
        if (v) return v
        if (kind === 'case') {
          return ((x.resolved || 0) + (x.misdiagnosed || 0)) > 0 ? NOT_RECORDED : '还没有解决或误诊的记录'
        }
        return (x.lookups || 0) > 0 ? NOT_RECORDED : '还没有查询记录'
      }
      const rankRow = (x, kind, cumulative) => {
        const small = cumulative && sampleOf(x, kind) > 0 && sampleOf(x, kind) < 5
        return React.createElement('div', { key: kind + ':' + x.id, style: { display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0', borderTop: '1px solid var(--hair)', flexWrap: 'wrap', minWidth: 0 } },
          React.createElement('code', { className: 'sleu-mono', style: { fontSize: 'var(--t-sm)', flexShrink: 0, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }, title: x.id }, x.id),
          React.createElement('span', { style: { flex: '1 1 140px', minWidth: 0, fontSize: 'var(--t-sm)', color: T.text2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, title: x.title || '' }, x.title || '（标题未读到）'),
          x.baseline ? React.createElement('span', { style: tinyBadge('var(--d-gray)'), title: '这一行的计数来自搬运行（kind: baseline），不计入本期增量' }, '基线') : null,
          small ? React.createElement('span', { style: tinyBadge('var(--d-amber)'), title: '这一条的样本量小于 5：计数可以读，比率不要读' }, '小样本') : null,
          React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-sm)', color: T.text } }, kind === 'case' ? caseCounts(x) : refCounts(x)),
          cumulative ? React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2, flexShrink: 0 } },
            '最后 ' + lastTextOf(x, kind)) : null,
        )
      }
      // 一张表 + 本期/累计双列（评审建议的形态 1）。
      // 为什么改：四张榜平铺时，"本期 vs 累计"要跨两段比对；而且只有一周记录时两段内容几乎相同。
      // 并成一张表后，同一行内直接看到"这周用了几次 / 历史上用了多少次"。
      // 三条约束来自评审：① 没有回报就不写 0，写「无人回报」；② 本期为 0 而累计 > 0 的行标出来；
      // ③ 并列时不假装有名次，只按累计降序 + id，并写明"并列"。
      const TIE = (rows, key) => {
        const seen = {}
        for (const r of rows) { const v = r[key] || 0; if (v > 0) seen[v] = (seen[v] || 0) + 1 }
        return Object.keys(seen).some(v => seen[v] > 1)
      }
      const weekCaseMap = {}
      for (const w of weeklyCases) weekCaseMap[w.id] = w
      const weekRefMap = {}
      for (const w of weeklyRefs) weekRefMap[w.id] = w
      const anyFeedback = ea.cases.some(c => (c.resolved || 0) + (c.misdiagnosed || 0) > 0)
      const cell = (v, opts) => React.createElement('span', {
        className: 'sleu-num',
        style: { textAlign: 'right', fontSize: 'var(--t-tiny)', color: (opts && opts.dim) ? T.text2 : T.text, whiteSpace: 'nowrap' },
      }, v)
      const headRow = (cols) => React.createElement('div', { style: { display: 'grid', gridTemplateColumns: cols.map(c => c.w).join(' '), gap: 8, padding: '0 0 4px', borderBottom: '1px solid ' + T.border } },
        cols.map(c => React.createElement('span', { key: c.k, style: { fontSize: 'var(--t-md2)', color: T.text2, textAlign: c.r ? 'right' : 'left' } }, c.k)))
      const caseCols = [{ k: '条目', w: 'minmax(0,1fr)' }, { k: '本期', w: '42px', r: 1 }, { k: '累计', w: '42px', r: 1 },
        { k: anyFeedback ? '解决' : '回报', w: anyFeedback ? '42px' : '58px', r: 1 },
        { k: anyFeedback ? '误诊' : '', w: anyFeedback ? '42px' : '0px', r: 1 },
        { k: '排除', w: '42px', r: 1 }, { k: '最后', w: '62px', r: 1 }]
      const refCols = [{ k: '先验条目', w: 'minmax(0,1fr)' }, { k: '本期', w: '42px', r: 1 }, { k: '累计', w: '42px', r: 1 },
        { k: '命中', w: '42px', r: 1 }, { k: '未命中', w: '48px', r: 1 }, { k: '未查', w: '42px', r: 1 }, { k: '最后', w: '62px', r: 1 }]
      const mergedRow = (x, kind) => {
        const isRef = kind === 'ref'
        const w = isRef ? weekRefMap[x.id] : weekCaseMap[x.id]
        const now = isRef ? ((w && w.lookups) || 0) : ((w && w.selected) || 0)
        const cum = isRef ? (x.lookups || 0) : (x.selected || 0)
        const cols = isRef ? refCols : caseCols
        const title = x.title || ''
        return React.createElement('div', { key: x.id, style: { display: 'grid', gridTemplateColumns: cols.map(c => c.w).join(' '), gap: 8, padding: '3px 0', borderBottom: '1px solid ' + T.bg2, alignItems: 'baseline' } },
          React.createElement('span', { title: title, style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
            React.createElement('code', { className: 'sleu-mono', style: { fontSize: 'var(--t-tiny)', color: T.text } }, x.id),
            title ? React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2, marginLeft: 6 } }, title.slice(0, 42)) : null),
          cell(now || (cum ? '—' : '0'), { dim: !now }),
          cell(cum),
          ...(isRef
            ? [cell(x.hit || 0), cell(x.miss || 0), cell(x.skipped || 0)]
            : (anyFeedback
                ? [cell(x.resolved || 0), cell(x.misdiagnosed || 0)]
                : [React.createElement('span', { key: 'fb', style: { textAlign: 'right', fontSize: 'var(--t-md2)', color: T.text2, whiteSpace: 'nowrap' } }, '无人回报'), null])),
          cell(isRef ? (x.lastWeek || '—') : (x.lastHit || '—'), { dim: true }))
      }
      const section = (label, kind, rows, cols) => React.createElement('div', { style: { marginTop: 8 } },
        React.createElement('div', { style: { fontSize: 'var(--t-sm)', fontWeight: 600, marginBottom: 3 } }, label),
        rows.length
          ? React.createElement('div', null, headRow(cols), rows.slice(0, 12).map(x => mergedRow(x, kind)),
              rows.length > 12 ? React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2, marginTop: 3 } }, '另有 ' + (rows.length - 12) + ' 条未列出（按累计降序）') : null)
          : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3 } }, NOT_RECORDED + '：这一期没有任何条目被用到'))
      const usage = React.createElement(Block, {
        title: '条目使用', accent: 'var(--acc-green)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } },
          wk ? ('「本期」= ' + wk + ' · 「累计」= 全部期') : '生成物没有期号'),
      },
        wk ? null : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3 } }, UNREADABLE + '：生成物没有期号，本期列不可读'),
        section('案例' + (TIE(cumCases, 'selected') ? '（按累计选中降序；并列的按 id，不代表名次）' : ''), 'case', cumCases, caseCols),
        section('先验' + (TIE(cumRefs, 'lookups') ? '（按累计查询降序；并列的按 id，不代表名次）' : ''), 'ref', cumRefs, refCols),
        React.createElement('div', { style: { marginTop: 5, color: T.text2, fontSize: 'var(--t-tiny)', lineHeight: 'var(--lh-base)' } },
          anyFeedback
            ? '「解决 / 误诊」由现场回报派生；「排除」是被候选过滤丢掉，与「被使用」是两件事。'
            : '「解决 / 误诊」这一列本期没有任何回报，所以写「无人回报」而不是 0——0 会被读成"用了但没用"。'),
      )
      // —— ⑤ 长期零选中（不据此退休）——
      const neverSelected = ea.cases.filter(c => c.selected === 0 && !c.baseline)
      const neverIds = neverSelected.slice(0, 8).map(c => c.id)
      const baselineRows = ea.cases.filter(c => c.baseline).length
      const zeroBlock = React.createElement(Block, { title: '长期零选中', accent: 'var(--acc-gray)' },
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
          React.createElement(Cell, {
            label: '本期与跨期都没被选中的案例',
            value: caseTotal !== null ? thousands(neverSelected.length) + ' 条' : null,
            note: caseTotal !== null ? (caseTotal ? '分母 ' + thousands(caseTotal) + ' 条（全库案例）' : null) : null,
          }),
          React.createElement(Cell, { label: '生成物的 cold（另一口径）', value: ea.coldCases !== null ? thousands(ea.coldCases) + ' 条' : null, note: '按有没有非搬运行记录算，与上面的集合不同' }),
          React.createElement(Cell, { label: '从未被查过的先验', value: ea.coldNeverLookedUp.length ? thousands(ea.coldNeverLookedUp.length) + ' 条' : null }),
          React.createElement(Cell, { label: '只有搬运行的案例', value: baselineRows ? thousands(baselineRows) + ' 条' : '0 条', note: '它们的计数来自搬运行，不参与"有没有被选中"的判断' }),
        ),
        neverIds.length ? React.createElement(LineRow, { label: '举例' },
          neverIds.map(id => React.createElement('code', { key: id, className: 'sleu-mono', style: { marginRight: 8, color: T.text2 } }, id))
          .concat(neverSelected.length > neverIds.length ? [React.createElement('span', { key: 'more', style: { color: T.text2 } }, '等 ' + neverSelected.length + ' 条')] : [])) : null,
        React.createElement('div', { style: { marginTop: 5, fontSize: 'var(--t-sm)', color: T.warn, lineHeight: 'var(--lh-base)' } },
          '不据此退休：零选中只说明这一期没有被用到，先查症状词面与标签是否覆盖，再决定动不动条目。'),
      )
      // —— ⑥ 过程动作成本（按工具；生成物只有按工具的分位，逐次明细在本机）——
      // 过程动作成本：**按 p90 排**（回答"哪个动作最费时间"），并把「等人的 / 等后台任务」
      // 单列出去——ask_user_question 的 p50 是十几分钟，混进来会把模型动作全压成 0。
      const WAIT_TOOLS = { ask_user_question: '等人回答', job_output: '等后台任务', job_kill: '等后台任务' }
      const allTools = ea.tools.slice()
      const actTools = allTools.filter(t => !WAIT_TOOLS[t.name])
        .sort((a, b) => (b.p90 || b.p50 || 0) - (a.p90 || a.p50 || 0))
      const waitTools = allTools.filter(t => WAIT_TOOLS[t.name])
        .sort((a, b) => (b.p90 || b.p50 || 0) - (a.p90 || a.p50 || 0))
      const maxP90 = Math.max(1, ...actTools.map(t => t.p90 || t.p50 || 0))
      // 异常值：p90 超过一小时的多半是"并行调用被拉长"或"等了很久"，不是工具本身慢。
      // 标出来而不是照原值印，否则读者会把 11.2 h 当成"读文件要 11 小时"。
      const OUTLIER = 60 * 60 * 1000
      const toolLine = (t, isWait) => React.createElement('div', {
        key: t.name, style: { display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 62px 96px 76px', gap: 8, alignItems: 'center', padding: '3px 0', borderTop: '1px solid var(--hair)' },
      },
        React.createElement('div', { style: { minWidth: 0, display: 'flex', gap: 6, alignItems: 'baseline' } },
          React.createElement('code', { title: t.name, className: 'sleu-mono', style: { fontSize: 'var(--t-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, t.name),
          isWait ? React.createElement('span', { style: { fontSize: 'var(--t-md2)', color: T.text2, whiteSpace: 'nowrap' } }, WAIT_TOOLS[t.name]) : null),
        React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-tiny)', textAlign: 'right', color: T.text2 } }, nText(t.calls) + ' 次'),
        React.createElement('div', { style: { height: 8, background: 'var(--hair)', borderRadius: 2, overflow: 'hidden' } },
          React.createElement('i', { style: { display: 'block', height: '100%', width: Math.max(2, Math.round((t.p90 || t.p50 || 0) / maxP90 * 100)) + '%', background: isWait ? 'var(--acc-amber, ' + T.warn + ')' : 'var(--acc-purple, #7c3aed)', opacity: 0.8 } })),
        React.createElement('span', { className: 'sleu-num', style: { fontSize: 'var(--t-tiny)', textAlign: 'right', color: (t.p90 || 0) > OUTLIER ? T.warn : T.text } },
          'p90 ' + (msText(t.p90) || NOT_RECORDED) + ((t.p90 || 0) > OUTLIER ? ' ⚠' : '')))
      const toolsBlock = React.createElement(Block, {
        title: '过程动作成本', accent: 'var(--acc-purple)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, '按 p90 排（越靠上越费时间）'),
      },
        actTools.length
          ? React.createElement('div', null, actTools.slice(0, 8).map(t => toolLine(t, false)))
          : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3 } },
              NOT_RECORDED + '：生成物的 tools 段是空的（本机没有可汇总的逐次工具调用明细）'),
        waitTools.length ? React.createElement('div', { style: { marginTop: 8 } },
          React.createElement('div', { style: { fontSize: 'var(--t-md2)', letterSpacing: '.1em', color: T.text2, marginBottom: 2 } }, '等人的 / 等后台任务（不与上面比）'),
          waitTools.map(t => toolLine(t, true))) : null,
        React.createElement('div', { style: { marginTop: 6, color: T.text2, fontSize: 'var(--t-md2)', lineHeight: 'var(--lh-base)' } },
          'p50 / p90 是跨运行按调用次数加权的均值，量级读数。带 ⚠ 的 p90 超过一小时——多半是并行调用被拉长或等了很久，不是工具本身慢。'))
      // —— ⑦ 变差的读数（读数 · 阈值或对照 · 一条动作）——
      const fails = (verdict && Array.isArray(verdict.findings) ? verdict.findings : []).filter(f => f.level === 'fail')
      const worseBlock = React.createElement(Block, {
        title: '变差的读数', accent: 'var(--acc-amber)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, fails.length ? fails.length + ' 条越界或退化' : '本期没有越界'),
      },
        fails.length
          ? React.createElement('div', null, fails.map((f, i) => React.createElement('div', {
              key: i, style: { padding: '5px 0', borderTop: i ? '1px solid var(--hair)' : 'none' },
            },
              React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text, lineHeight: 'var(--lh-base)' } }, f.plain || f.text),
              f.plain && f.text && f.plain !== f.text ? React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2, marginTop: 2, lineHeight: 'var(--lh-base)' } }, '读数：' + f.text) : null,
              React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3, display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' } },
                React.createElement('span', { style: { color: T.warn, flexShrink: 0 } }, '动作'),
                React.createElement('span', { style: { flex: '1 1 200px', minWidth: 0, wordBreak: 'break-word' } }, f.action || '（判据没给动作，分母补上后这一项才算得出来）'),
                f.action ? copyBtn(f.action, 'ea-worse:' + i) : null,
              ),
            )))
          : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3 } },
              '体检判决里没有 fail 项。这一格只说"没报越界"，判据覆盖面见上面的「需处理」。'),
      )
      // —— ⑧ 本期该做（三到五条；凑不满就照实少写，不补凑数条目）——
      const todos = []
      for (const f of fails) if (f.action && todos.indexOf(f.action) < 0) todos.push(f.action)
      const cc = (verdict && Array.isArray(verdict.candidate_commands)) ? verdict.candidate_commands : []
      for (const c of cc) {
        const t = (c.label ? c.label + '：' : '') + (c.command || '')
        if (t && todos.indexOf(t) < 0) todos.push(t)
      }
      const todoTop = todos.slice(0, 5)
      const todoBlock = React.createElement(Block, {
        title: '本期该做', accent: 'var(--acc-red)',
        right: React.createElement('span', { style: { fontSize: 'var(--t-tiny)', color: T.text2 } }, todoTop.length ? todoTop.length + ' 条' : '无'),
      },
        todoTop.length
          ? React.createElement('div', null, todoTop.map((t, i) => React.createElement('div', {
              key: i, style: { display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4, minWidth: 0 },
            },
              React.createElement('span', { className: 'sleu-num', style: { color: T.text2, fontSize: 'var(--t-sm)', flexShrink: 0 } }, (i + 1) + '.'),
              React.createElement('span', { style: { flex: 1, minWidth: 0, fontSize: 'var(--t-sm)', lineHeight: 'var(--lh-base)', wordBreak: 'break-word' } }, t),
              copyBtn(t, 'ea-todo:' + i),
            )))
          : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3 } }, '没有要做的：判决没有越界，也没有候补命令。'),
        todos.length > todoTop.length
          ? React.createElement('div', { style: { marginTop: 4, fontSize: 'var(--t-tiny)', color: T.text2 } }, '另 ' + (todos.length - todoTop.length) + ' 条在判决区，未重复列出。')
          : null,
      )
      // —— ③ 需处理：条数与判据评估进度（"没报越界"与"没被检查"分开）——
      const cov = (verdict && verdict.coverage) || {}
      const needBlock = React.createElement(Block, { title: '需处理', accent: 'var(--acc-blue)' },
        React.createElement('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '2px 14px' } },
          React.createElement(Cell, {
            label: '待处理',
            value: verdict ? (fails.length ? fails.length + ' 项越界或退化' : '0 项越界') : null,
            missingText: UNREADABLE, note: verdict ? null : '体检判决不可用或还没回来',
          }),
          React.createElement(Cell, {
            label: '判据评估进度',
            value: (cov.gates_total !== undefined && cov.gates_total !== null) ? (cov.gates_evaluated + ' / ' + cov.gates_total + ' 条判据已评估') : null,
            missingText: UNREADABLE,
          }),
          React.createElement(Cell, {
            label: '可解读性',
            value: (cov.readability_total !== undefined && cov.readability_total !== null) ? (cov.readability_evaluated + ' / ' + cov.readability_total + ' 条已判') : null,
            missingText: UNREADABLE,
          }),
        ))
      const unreadableBlock = React.createElement(Block, { title: '不可解读', accent: 'var(--acc-purple)' },
        unread.length
          ? React.createElement('div', null, unread.map((u, i) => React.createElement('div', { key: i, style: { marginTop: i ? 5 : 2, minWidth: 0 } },
              React.createElement('div', { style: { fontSize: 'var(--t-sm)', fontWeight: 600 } }, u.label),
              React.createElement('div', { style: { fontSize: 'var(--t-tiny)', color: T.text2, lineHeight: 'var(--lh-base)', marginTop: 1 } }, '缺的分母或来源：' + u.why),
            )))
          : React.createElement('div', { style: { fontSize: 'var(--t-sm)', color: T.text2, marginTop: 3 } }, '这一期没有缺分母的读数。'),
        React.createElement('div', { style: { marginTop: 5, fontSize: 'var(--t-tiny)', color: T.text2, lineHeight: 'var(--lh-base)' } },
          '不可解读 ≠ 0：没有数据与"读数是 0"是两件事。样本量小于 5 的条目在榜上标「小样本」。'))
      return React.createElement('div', { style: { marginBottom: 12 } },
        // 「变差的读数」与「本期该做」不再单独出块：判决里已经逐条给了判据、处置与可复制指令，
        // 同一批 fail 在四处各说一遍是这一屏最大的重复来源（评审逐行列了四处行号）。
        cover, unreadableBlock, needBlock, usage, zeroBlock, toolsBlock)
    }


    function MetricsView(props) {
      const sessionId = props && props.sessionId
      const [state, setState] = React.useState({ loading: true, data: null })
      const [health, setHealth] = React.useState(null)
      const [proc, setProc] = React.useState(null)
      // 判决（闭环体检）：首屏的真正主角。缺它时如实报"体检不可用"，不假装一切正常。
      const [verdict, setVerdict] = React.useState(null)
      const [kindFilter, setKindFilter] = React.useState('live')
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
      if (state.loading) return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        [0, 1, 2].map(i => React.createElement('div', { key: i, className: 'sleu-skel', style: { height: i === 0 ? 40 : 64, marginBottom: 10 } })))
      const r = state.data
      // timeline 读不到时**不再整页早退**：判决、知识库健康、累计读数都不经过 timeline
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
      // 指标强度档（3.6 的最后一问「这个数怎么来的」）：随 timeline 一并从 gates.yaml 带下来。
      // 取不到就是空表——那时不挂强度徽标（不默认成确定性），并在期卡顶部汇总一次缺口。
      const strengthOf = (!timelineError && r && r.metricStrength && typeof r.metricStrength === 'object') ? r.metricStrength : {}
      // 强度缺口的**唯一**提示位：把没在 gates.yaml 里声明强度的指标名字列一次。
      // 逐行挂徽标时它会被读成"面板坏了"（知识库健康那些计数行根本不参与强度体系）。
      const strengthMissing = (function () {
        const seen = {}
        for (const p of periods) for (const k of Object.keys(p.metrics || {})) {
          if (!(k in (typeof strengthOf === 'object' && strengthOf ? strengthOf : {}))) seen[k] = 1
        }
        return Object.keys(seen)
      })()
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
      // 筛选用中文：kindMeta 里已经备好了 label，别把 live/replay/example 原文甩给读者
      const filterLabels = { all: '全部', live: kindMeta.live.label, replay: kindMeta.replay.label, example: kindMeta.example.label }

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
          feedbackAlert = React.createElement('div', { style: { marginBottom: 12, border: '1px solid ' + T.warn, borderRadius: 'var(--r-md)', overflow: 'hidden' } },
            React.createElement('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)' } },
              React.createElement(Dot, { color: T.warn }),
              React.createElement('span', { style: { fontSize: 'var(--t-md)', fontWeight: 700, color: T.warn, whiteSpace: 'nowrap' } }, '本期快照的反馈捕获为 0'),
              React.createElement('span', { style: { fontSize: 'var(--t-md)', color: T.text, flex: 1 } },
                hits + ' 次命中还没人回报结果——所以「误诊率」「误诊归因」标着不可解读（那不是 0，是没数据）'),
              React.createElement('button', { type: 'button', onClick: () => { setFbCmd(!fbCmd); setCopied(null) }, style: fbCmd ? btnPurple : btnGhost }, fbCmd ? '隐藏指令' : '回报'),
            ),
            fbCmd ? React.createElement('div', { style: { padding: '8px 12px', background: T.bg, borderTop: '1px solid ' + T.warn, fontSize: 'var(--t-sm)' } },
              React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 } },
                React.createElement('span', { style: { color: T.warn, fontWeight: 600 } }, '粘贴到对话即可触发回报'),
                React.createElement('button', { type: 'button', onClick: () => doCopy(fbCmdText, 'fb'), style: copied === 'fail' ? { ...btnRed, background: 'var(--d-red)' } : btnPurple },
                  copied === 'fb' ? '已复制' : (copied === 'fail' ? '失败' : '复制')),
              ),
              React.createElement('code', { style: { userSelect: 'all', background: T.bg2, border: '1px solid ' + T.border, borderRadius: 'var(--r-xs)', padding: '5px 8px', display: 'block', fontSize: 'var(--t-md)', fontFamily: 'var(--font-mono)' } },
                fbCmdText),
            ) : null,
          )
        }
      }

      // 复制反馈：2 秒后自己复位（指标 tab 只有一处复制入口，失败仍用 'fail' 标记）。
      function doCopy(txt, key) {
        copyText(txt).then(ok => {
          setCopied(ok ? key : 'fail')
          if (timer && typeof timer.timeout === 'function') timer.timeout(() => setCopied(null), 2000)
        })
      }

      // timeline 的三种结局分开渲染：**读不到** / **解析不出期次** / 正常。
      // 中间那一态是本轮实测出来的缺口：解析器与文件结构不符时，旧实现拿到空数组，
      // 于是显示「尚无 live 快照」——文件里 3 期 live 摆着，面板说没有。数据在、结论假，
      // 与"没报越界"被读成"没越界"属同一类，所以这里也单独给一句不可解读声明。
      const timelineWarnCard = (title, body, command) => React.createElement('div', { style: { marginBottom: 10, padding: '9px 11px', background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.warn, borderRadius: 'var(--r-md)', fontSize: 'var(--t-md)', color: T.text, lineHeight: 'var(--lh-base)' } },
        React.createElement('div', { style: { fontWeight: 700, color: T.warn, marginBottom: 3 } }, title),
        React.createElement('div', { style: { color: T.text } }, body),
        command ? React.createElement('code', { style: { display: 'block', marginTop: 6, userSelect: 'all', background: T.bg, border: '1px solid var(--hair)', borderRadius: 'var(--r-xs)', padding: '5px 8px', fontSize: 'var(--t-sm)', fontFamily: 'var(--font-mono)' } }, command) : null,
      )
      const periodCards = shown.length === 0
        ? React.createElement('div', { style: { color: T.text2, padding: '24px 0', textAlign: 'center', fontSize: 'var(--t-sm)' } }, '无该类型快照')
        : React.createElement('div', null, (() => {
            // 默认展开：最近 2 期；历史期收进"历史快照"折叠区（顺序见 allShown 的注释）
            const recent = shown.slice(0, 2)
            const older = shown.slice(2)
            const isOpen = (p) => openPeriods === null ? recent.indexOf(p) >= 0 : !!openPeriods[p.period]
            const toggle = (p) => setOpenPeriods(Object.assign({}, openPeriods === null ? Object.fromEntries(recent.map(x => [x.period, true])) : openPeriods, { [p.period]: !isOpen(p) }))
            return React.createElement(React.Fragment, null,
              recent.map((p, i) => React.createElement(PeriodCard, { key: 'r' + i, p: p, open: isOpen(p), onToggle: () => toggle(p), isUnreadable: isUnreadable, strengthOf: strengthOf })),
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
                  older.map((p, i) => React.createElement(PeriodCard, { key: 'o' + i, p: p, open: isOpen(p), onToggle: () => toggle(p), isUnreadable: isUnreadable, strengthOf: strengthOf }))) : null,
              ) : null,
            )
          })())
      const timelineBlock = timelineError
        ? timelineWarnCard(
            '期次与趋势不可读',
            'metrics/timeline.yaml 读不到：' + timelineError + '。上面的判决与累计读数不经过它，仍按各自的数据源显示。',
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
                  filterChips.map(k => React.createElement('button', { key: k, type: 'button', onClick: () => setKindFilter(k), style: k === kindFilter ? { ...btnPrimary, padding: '3px 12px', borderRadius: 'var(--r-pill)' } : { ...btnGhost, padding: '3px 12px', borderRadius: 'var(--r-pill)' } }, filterLabels[k])),
                ),
                liveCount === 0 ? React.createElement('div', { style: { marginBottom: 10, padding: 10, background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', fontSize: 'var(--t-md)', color: T.text2 } },
                  '尚无 live 快照。首次活诊断后由 owner 追加（docs/guide/metrics.md 汇总职责）。') : null,
                // 强度缺口只在这里说一次（不再逐行挂「未声明强度」）
                strengthMissing.length ? React.createElement('div', { style: { marginBottom: 10, padding: '8px 10px', background: 'color-mix(in srgb, ' + T.warn + ' 8%, transparent)', border: '1px solid ' + T.border, borderRadius: 'var(--r-md)', fontSize: 'var(--t-sm)', color: T.text2, lineHeight: 'var(--lh-base)' } },
                  '有 ' + strengthMissing.length + ' 个指标没在 metrics/gates.yaml 里声明强度档，它们的数不标徽标（不默认成确定性）：',
                  React.createElement('span', { className: 'sleu-mono', style: { marginLeft: 4 } }, strengthMissing.slice(0, 8).join('、') + (strengthMissing.length > 8 ? ' 等' : ''))) : null,
                periodCards))

      return React.createElement('div', { className: 'sleu', style: { ...base, padding: 20 } },
        React.createElement('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 } },
          React.createElement('div', { style: { fontSize: 'var(--t-md)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 } },
            React.createElement('span', { style: { width: 8, height: 16, borderRadius: 'var(--r-xs)', background: 'var(--acc-green)', display: 'inline-block' } }),
            'ascend-sleuth 指标'),
          React.createElement('span', { style: { fontSize: 'var(--t-md)', color: T.text2, background: T.bg2, border: '1px solid ' + T.border, borderRadius: 'var(--r-pill)', padding: '2px 10px' } },
            timelineError ? '期次不可读'
              : (timelineUnparsed ? '期次解析失败'
                : (periods.length + ' 期 · live ' + liveCount))),
        ),
        // ① 状态条：快照新鲜度 + 索引/磁盘 drift + 一句判读
        React.createElement(StatusBar, { verdict: vd, error: verdictErr, onRefresh: refreshVerdict, refreshing: verdictBusy }),
        // ①' 判决：**首屏第一块落到动作**。它原来排在四张榜之后，读者要滚过一整屏读数
        // 才看到"这周该做什么"；而它是全屏唯一带可复制指令的块。
        React.createElement(VerdictCard, { verdict: vd, error: verdictErr, pending: verdictPending, copiedKey: copied, onCopy: doCopy }),
        // ② 累计读数（条目使用记录）：读数与明细。判决已经给出"该做什么"，这里是"凭什么"。
        // 生成物读不到时只报缺件与重建命令（不解析源文件自行求和）。
        React.createElement(EntryActivityBoard, {
          ea: (r && r.entryActivity) || null, health: health, verdict: vd,
          onCopy: doCopy, copied: copied,
        }),
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
        // ⑥ 趋势：本期 vs 上期差分 + 期卡（timeline 不可读 / 解析不出期次时**分开说清**）
        timelineBlock,
      )
    }


    // ── 会话行的「待回报」标记：L2 行首空心点 + L1 悬停卡一行 ──────────────────────
    //
    // 数据只有一条瘦 RPC（`ascend-session-marks`）：哪几个会话欠回报、欠了多久、命中哪个 case。
    // 侧栏每行都渲染这两个组件，所以取数**必须共享**：模块级一份状态 + 一处在途请求，
    // N 行只读同一次结果。逐行发请求会把 RPC 打成筛子（几百行），这是设计约束不是优化。
    //
    // 刷新：首次挂载取一次，30 秒内复用（与面板的复用窗口同一量级）；过期后下一次挂载再取。
    // 取不到时**保留上一次结果**：清空会把"读不到"显示成"没有欠账"。
    const MARK_TTL_MS = 30000
    const markState = { at: 0, marks: Object.create(null) }
    const markWaiters = new Set()
    let markRequest = null

    function refreshMarks(force) {
      const fresh = !force && markState.at > 0 && (Date.now() - markState.at) < MARK_TTL_MS
      if (fresh) return Promise.resolve()
      if (markRequest !== null) return markRequest
      markRequest = host.call('ascend-session-marks', {})
        .then((r) => {
          if (r && r.ok && Array.isArray(r.marks)) {
            const next = Object.create(null)
            for (const m of r.marks) if (m && m.sessionId) next[String(m.sessionId)] = m
            markState.marks = next
          }
          markState.at = Date.now()
          for (const fn of markWaiters) { try { fn() } catch (e) { /* 一个订阅者失败不阻塞其余 */ } }
          markWaiters.clear()
        })
        .catch(() => {
          markState.at = Date.now()
          markWaiters.clear()
        })
        .then(() => { markRequest = null })
      return markRequest
    }

    // 一行一个订阅：挂载时同步读共享状态，取数回来后由 markWaiters 通知重渲染。
    // 没有全局定时器（动态沙箱不提供），所以刷新只发生在挂载与明确调用处。
    function useTraceMark(sessionId) {
      const [mark, setMark] = React.useState(null)
      React.useEffect(() => {
        let alive = true
        const sync = () => { if (alive) setMark(markState.marks[String(sessionId)] || null) }
        markWaiters.add(sync)
        sync()
        refreshMarks(false)
        return () => { alive = false; markWaiters.delete(sync) }
      }, [sessionId])
      return mark
    }

    // 记号的文案片段。悬停卡很窄（侧栏 280px 里的一张卡），所以不用一整句：
    // 一行说"该不该管"，一行说起算日与命中，第三行只在两轴并存时说明它们不矛盾。
    const STATUS_LABEL = { resolved: '已定位', in_progress: '进行中', escalated: '已转上游', archived: '不再跟进', unknown: '状态未记' }
    function markBits(mark) {
      if (!mark) return null
      const t = mark.since ? new Date(mark.since).getTime() : NaN
      const valid = !isNaN(t)
      let debt = '欠账天数未记录'
      let since = '起算日未记录'
      if (valid) {
        const d = new Date(t)
        const p = n => String(n).padStart(2, '0')
        debt = '欠 ' + Math.max(0, Math.floor((Date.now() - t) / 86400000)) + ' 天'
        since = '自 ' + p(d.getMonth() + 1) + '-' + p(d.getDate())
      }
      const hit = mark.kind === 'case' && mark.caseId ? '命中 ' + mark.caseId : '未命中 case'
      const pending = mark.mark === 'pending'
      // 标题：待回报给"欠多久"（要人做的动作），可复用给"是什么"（能拿来用的东西）
      const title = pending ? '待回报 · ' + debt : '知识库可复用'
      let detail = since + ' · ' + hit
      if (!pending) {
        const bits2 = []
        if (mark.caseId) bits2.push('命中 ' + mark.caseId + '（库中已有）')
        if (mark.sedimented) bits2.push('已沉淀')
        detail = bits2.length ? bits2.join(' · ') : '知识库里有可复用的条目'
      }
      // 第三行只在"已收尾但还欠回报"时出现：这正是读者会读成矛盾的组合。
      const axis = (pending && mark.status === 'resolved')
        ? '诊断状态 ' + (STATUS_LABEL[mark.status] || mark.status) + '（收尾与回报是两条轴）'
        : ''
      return { pending: pending, title: title, detail: detail, axis: axis, debt: debt, since: since, hit: hit }
    }

    // L1：悬停卡里的两到三行（悬停 800ms 后出现；侧栏自己的卡已有标题与时间，这里只加欠账/可复用）
    function TraceRowHover(props) {
      const mark = useTraceMark(props && props.sessionId)
      if (!mark) return null
      const bits = markBits(mark)
      return React.createElement('div', { className: 'sleu-hover-mark' },
        React.createElement('div', { className: 'sleu-hover-title' }, bits.title),
        React.createElement('div', { className: 'sleu-hover-detail' }, bits.detail),
        bits.axis ? React.createElement('div', { className: 'sleu-hover-axis' }, bits.axis) : null,
      )
    }

    // L2：行首记号。两种形状——缺环（待回报，等人）与实心菱形（知识库可复用，值得点开），
    // 靠形状与颜色**双通道**区分。DSH 只在"空闲且已读"的行渲染这个位置（运行中/未读先让给
    // 它的状态点），所以这是尽力而为的标记，不是每行都有的徽标。
    function TraceRowLeading(props) {
      const mark = useTraceMark(props && props.sessionId)
      if (!mark) return null
      const bits = markBits(mark)
      const label = [bits.title, bits.detail, bits.axis].filter(Boolean).join(' · ')
      return React.createElement('span', {
        className: bits.pending ? 'sleu-row-dot' : 'sleu-row-gem',
        role: 'img',
        'aria-label': label,
        title: label,
      })
    }

    // 会话 tab 只留「诊断」：它读的是这一单的轨迹。

    // ============ 侧栏「诊断记录」（页脚入口 + 帧级浮层）============
    // 为什么是这两处而不是会话列表本身：侧栏的会话行没有插件槽位，能注册的只有
    // 「整个浏览区」（`sidebar.workspaces`，注册进去 = 接管自带列表）。所以走
    // `sidebar.footer.action`（附加一个入口，不占自带那一格）+ `shell.overlay`
    // （帧级浮层，点击穿透的附加层，无自带 occupant）。会话本身用 `sessions.open` 切过去。
    function LedgerEntryButton(props) {
      const wide = !!(props && props.wide)
      const open = useLedgerOpen()
      return React.createElement('button', {
        type: 'button',
        title: '诊断记录：列出本工作区的诊断会话，可按时间或按价值排序，点一行直接切过去',
        'aria-label': '诊断记录', 'aria-expanded': open ? 'true' : 'false',
        onClick: () => setLedgerOpen(!ledger.open),
        style: {
          display: 'flex', alignItems: 'center', justifyContent: wide ? 'flex-start' : 'center',
          gap: 8, width: wide ? '100%' : 32, height: 32, padding: wide ? '0 10px' : 0,
          boxSizing: 'border-box', border: '1px solid ' + T.border, borderRadius: 'var(--r-md)',
          background: open ? 'color-mix(in srgb, ' + T.brand + ' 12%, transparent)' : 'transparent',
          color: T.text, font: 'inherit', fontSize: 'var(--t-sm)', cursor: 'pointer',
          transition: 'background-color var(--m-fast) var(--e-out)',
        },
      },
        React.createElement('span', { 'aria-hidden': 'true', style: { fontSize: 'var(--t-md)', lineHeight: 1 } }, '☰'),
        wide ? React.createElement('span', null, '诊断记录') : null)
    }

    // 回报债的天数：起算日优先用 trace 的 `feedback_pending_since`（skill 写的），
    // 没有再退到更新时间。两个都没有就说「天数未记录」——写 0 会被读成"今天刚欠下"。
    function ledgerDebtText(s) {
      const raw = (s && (s.feedbackPendingSince || s.updatedAt || s.createdAt)) || ''
      const t = raw ? new Date(raw).getTime() : NaN
      if (isNaN(t)) return '天数未记录'
      return '欠 ' + Math.max(0, Math.floor((Date.now() - t) / 86400000)) + ' 天'
    }

    // 诊断记录面板（点侧栏底部「诊断记录」弹出来的那张卡）。数据走与「诊断」tab 同一条 RPC
    // （`ascend-traces-list`）；「按价值」用的 `valueRankOf` 与「诊断」tab 是同一份——两处各算
    // 一份就会给出两套"价值"。「按时间」按行尾那一列（最后更新时间）倒序：时间列不降序会被读成
    // 排序坏了（这张卡曾只有价值序，最新开工的两单因为没有结论落在最底一档），所以默认按时间。
    // 用 `updatedAt` 当主键与 host 的取舍不同（`panel-host.js` 的 listTraces 按 `created_at` 排，
    // 因为那一列承担"何时开始诊断"的语义，而 `updated_at` 由 agent 手填、写错就会改次序）；这里
    // 排序与行尾显示的是同一个字段，两者不一致才是缺陷。
    // 这里是**只读 + 导航**：不写 trace、不生成指令，指令仍然在「诊断」tab 里。
    //
    // 键盘按一等用法设计：打开即聚焦搜索框，↑↓ 选行、Enter 打开、Esc 关闭、Tab 在卡内循环。
    // 用它的人在做"批量翻"——一条条鼠标点开再关掉，比键盘慢一个数量级。
    const LEDGER_FILTERS = [
      { id: 'all', label: '全部', test: () => true },
      { id: 'pending', label: '待回报', test: s => !!s.feedbackPending },
      { id: 'reusable', label: '可复用', test: s => sedStateOf(s) !== 'none' || !!s.activeCaseInKb },
      { id: 'open', label: '未收尾', test: s => isOpenOf(s) },
      { id: 'recent', label: '近 30 天',
        // 这一格按开始时间算（与列表默认的"最后更新时间"不是同一列），所以给一句 tooltip。
        title: '按开始时间（created_at）算：最近 30 天开工的单',
        test: s => {
          const t = new Date(s.createdAt || s.updatedAt || 0).getTime()
          return !isNaN(t) && (Date.now() - t) <= 30 * 86400000
        } },
    ]

    // 会话列表快照：面板要标出"你已经在这一条里"（否则点一行没反应，读起来像坏了），
    // 底部计数则回答"还有多少会话根本没有诊断记录"。服务不在时返回 null，两边都只说能说的。
    function sessionListSnapshot() {
      try {
        const svc = sessionsService()
        if (!svc || !svc.list || typeof svc.list.getSnapshot !== 'function') return null
        return svc.list.getSnapshot() || null
      } catch (e) {
        return null
      }
    }

    function LedgerPanel() {
      const open = useLedgerOpen()
      const [state, setState] = React.useState({ loading: false, data: null })
      const [q, setQ] = React.useState('')
      const [navMsg, setNavMsg] = React.useState(null)
      const [filter, setFilter] = React.useState('all')
      const [sortBy, setSortBy] = React.useState('time')
      const [active, setActive] = React.useState(0)
      const snap = sessionListSnapshot()
      const currentId = snap && snap.current ? String(snap.current) : ''
      const workspaceTotal = snap && Array.isArray(snap.ids) ? snap.ids.length : null

      React.useEffect(() => {
        if (!open) return undefined
        let alive = true
        // 刷新时保留手上那份（切走再切回不必空一屏）；`prev` 仍然防一手——
        // 首帧之外没人保证它是本组件写进去的对象。
        setState(prev => ({ loading: true, data: (prev && prev.data) || null }))
        host.call('ascend-traces-list', { sessionId: null })
          .then(res => {
            if (alive) setState({ loading: false, data: res })
          })
          .catch(() => {
            if (alive) setState({ loading: false, data: { ok: false, error: 'Host RPC 失败' } })
          })
        return () => { alive = false }
      }, [open])

      // 读到什么就当什么：面板渲染检查用共享 hook 槽的 mock，这里拿到的值可能来自别的组件
      // （真实 React 不会），不该因此把整个面板拖崩。
      const st = (state && typeof state === 'object') ? state : { loading: true, data: null }
      const qText = typeof q === 'string' ? q : ''
      const r = st.data
      const all = (r && r.ok && Array.isArray(r.sessions)) ? r.sessions : []
      const KW_LIMIT = 40
      const kw = qText.trim().toLowerCase()
      const searched = kw
        ? all.filter(s => [s.sessionId, s.summarySnippet, s.activeCase, s.framework, s.platform, s.status]
            .filter(Boolean).join(' ').toLowerCase().includes(kw))
        : all
      const activeFilter = LEDGER_FILTERS.filter(f => f.id === filter)[0] || LEDGER_FILTERS[0]
      const filtered = filter === 'all' ? searched : searched.filter(activeFilter.test)
      const sorted = filtered.slice().sort(sortBy === 'value'
        ? (a, b) => valueRankOf(b) - valueRankOf(a) || updatedTsOf(b) - updatedTsOf(a)
        : (a, b) => updatedTsOf(b) - updatedTsOf(a) || createdTsOf(b) - createdTsOf(a))
      const shown = sorted.slice(0, KW_LIMIT)
      const counts = {}
      for (const f of LEDGER_FILTERS) counts[f.id] = f.id === 'all' ? searched.length : searched.filter(f.test).length

      const close = () => { setNavMsg(null); setLedgerOpen(false) }
      const openRow = row => {
        if (!row) return
        const target = row.harnessSession ? String(row.harnessSession) : ''
        if (currentId && target && target === currentId) {
          setNavMsg('你已经在这一条会话里了')
          return
        }
        if (!target) {
          setNavMsg('这单的轨迹顶层没有 harness_session，定位不到会话（session_id 不是 DSH 会话号）。'
            + '可能是建会话时漏写，也可能是旧单；补法：'
            + 'python3 scripts/link_harness_sessions.py --trace ' + String(row.file || '') + ' --session-id "$DSH_SESSION_ID" --apply')
          return
        }
        openSession(target).then(res => {
          if (res.ok) close()
          else setNavMsg(res.reason)
        })
      }

      // 键盘：Esc 关、↑↓ 选、Enter 开、Tab 在卡内循环。没有键盘出口的模态会把键盘用户困住，
      // 而这里的主要用法本来就是键盘。
      React.useEffect(() => {
        if (!open || typeof document === 'undefined') return undefined
        const search = document.querySelector('[data-ledger-search]')
        if (search && typeof search.focus === 'function') search.focus()
        const onKey = e => {
          // 焦点在 <select> 里时，方向键与 Enter 是它自己的用法（换选项、展开列表）；抢过来会
          // 变成"移动行高亮 / 打开行"，读者会以为面板在乱跳。**Tab 除外**：它由下面那段焦点环
          // 接管，否则从这道下拉 Shift+Tab 出去会把焦点带到 aria-modal 卡片外的页面上。
          const tag = e && e.target && e.target.tagName ? String(e.target.tagName).toLowerCase() : ''
          if (e.key === 'Escape') { e.preventDefault(); setNavMsg(null); setLedgerOpen(false); return }
          if (tag === 'select' && e.key !== 'Tab') return
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            const step = e.key === 'ArrowDown' ? 1 : -1
            setActive(i => Math.max(0, Math.min(shown.length - 1, (typeof i === 'number' ? i : 0) + step)))
            return
          }
          if (e.key === 'Enter') {
            e.preventDefault()
            openRow(shown[typeof active === 'number' ? active : 0])
            return
          }
          if (e.key !== 'Tab') return
          const card = document.querySelector('[data-ledger-card]')
          if (!card || typeof card.querySelectorAll !== 'function') return
          // `select` 必须在圈里：排序开关是卡片里唯一的下拉，漏了它，纯键盘用户切不了排序。
          const focusables = card.querySelectorAll('button, input, select, [tabindex]:not([tabindex="-1"])')
          if (!focusables.length) return
          const first = focusables[0]
          const last = focusables[focusables.length - 1]
          const here = document.activeElement
          if (e.shiftKey && here === first) { e.preventDefault(); last.focus() }
          else if (!e.shiftKey && here === last) { e.preventDefault(); first.focus() }
        }
        document.addEventListener('keydown', onKey)
        return () => { document.removeEventListener('keydown', onKey) }
      }, [open, active, shown])

      // 选中的行滚进视野（键盘翻页时不能让高亮跑到卡外）。
      React.useEffect(() => {
        if (!open || typeof document === 'undefined') return undefined
        const el = document.querySelector('[data-ledger-row="' + String(active) + '"]')
        if (el && typeof el.scrollIntoView === 'function') {
          try { el.scrollIntoView({ block: 'nearest' }) } catch (e) { /* 老浏览器不支持对象参数就跳过 */ }
        }
        return undefined
      }, [open, active])

      if (!open) return null
      return React.createElement('div', {
        className: 'sleu sleu-ledger-backdrop',
        // 点遮罩关闭：只在遮罩自身被点中时触发，卡片内部的点击不会冒泡成关闭。
        onMouseDown: e => { if (e.target === e.currentTarget) close() },
      },
        React.createElement('div', { className: 'sleu-ledger-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': '诊断记录', 'data-ledger-card': 'true' },
          React.createElement('div', { className: 'sleu-ledger-head' },
            React.createElement('span', { style: { fontSize: 'var(--t-lg)', fontWeight: 700 } }, '诊断记录'),
            React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)' } },
              (r && r.ok)
                ? (all.length + ' 条诊断记录' + (workspaceTotal === null ? '' : ' · 本工作区 ' + workspaceTotal + ' 个会话'))
                : '读不到诊断记录'),
            // 排序与搜索并排：两个都是"这一屏怎么读"的开关，分开摆会被当成两套设置。
            React.createElement('select', {
              value: sortBy, 'aria-label': '诊断记录排序', 'data-ledger-sort': 'true',
              title: sortBy === 'value'
                ? '按价值：' + VALUE_ORDER_TEXT
                : '按时间：行尾那一列（最后更新时间）倒序',
              onChange: e => { setSortBy(e.target.value); setActive(0) },
              style: { marginLeft: 'auto', padding: '5px 8px', fontSize: 'var(--t-tiny)', borderRadius: 'var(--r-md)', border: '1px solid var(--hair)', background: T.bg, color: T.text, cursor: 'pointer' },
            }, [['time', '排序：按时间'], ['value', '排序：按价值']].map(p => React.createElement('option', { key: p[0], value: p[0] }, p[1]))),
            React.createElement('input', {
              value: qText, placeholder: '过滤会话号 / 背景 / 案例', 'aria-label': '过滤诊断记录', 'data-ledger-search': 'true',
              onChange: e => { setQ(e.target.value); setActive(0) },
              style: { width: 190, padding: '6px 9px', fontSize: 'var(--t-sm)', borderRadius: 'var(--r-md)', border: '1px solid var(--hair)', background: T.bg, color: T.text },
            }),
            React.createElement('button', {
              type: 'button', onClick: close, title: '关闭（Esc）', 'aria-label': '关闭诊断记录',
              style: { border: 'none', background: 'transparent', color: T.text2, cursor: 'pointer', fontSize: 'var(--t-lg)', lineHeight: 1, padding: '2px 6px' },
            }, '×'),
          ),
          // 五个筛选：计数按搜索后的集合算，所以"待回报 3"始终和旁边的"全部 12"同一口径。
          React.createElement('div', { className: 'sleu-ledger-chips' },
            LEDGER_FILTERS.map(f => React.createElement('button', {
              key: f.id, type: 'button', className: 'sleu-ledger-chip', title: f.title || null,
              'aria-pressed': f.id === filter ? 'true' : 'false',
              onClick: () => { setFilter(f.id); setActive(0) },
            }, f.label + (counts[f.id] ? ' ' + counts[f.id] : ''))),
            React.createElement('span', { className: 'sleu-ledger-hint' }, '↑↓ 选行 · Enter 打开 · Esc 关闭'),
          ),
          navMsg ? React.createElement('div', { style: { padding: '6px 14px', color: 'var(--c-amber)', fontSize: 'var(--t-tiny)' } }, navMsg) : null,
          st.loading && !r ? React.createElement('div', { className: 'sleu-ledger-empty' }, '正在读诊断记录…')
            : (!r || !r.ok)
              ? React.createElement('div', { className: 'sleu-ledger-empty' },
                  '读不到诊断记录：' + String((r && r.error) || 'Host RPC 失败')
                  + '。这一层只读 traces/；目录不在时先在仓库里跑一次诊断。')
              : !all.length
                ? React.createElement('div', { className: 'sleu-ledger-empty' },
                    '这个工作区还没有诊断记录。跑一次 /skill:diagnose 之后会出现在这里。')
                : React.createElement('div', { className: 'sleu-ledger-body' },
                    shown.length
                      ? shown.map((s, i) => {
                          const meta = statusMeta[String(s.status || 'unknown')] || statusMeta.unknown
                          const hit = caseKindOf(s) === 'case'
                          const isCurrent = !!(currentId && s.harnessSession && String(s.harnessSession) === currentId)
                          const isActive = i === (typeof active === 'number' ? active : 0)
                          return React.createElement('button', {
                            key: s.file || s.sessionId, type: 'button',
                            className: 'sleu-ledger-row' + (isActive ? ' is-active' : ''),
                            'data-ledger-row': String(i),
                            'aria-selected': isActive ? 'true' : 'false',
                            onMouseEnter: () => setActive(i),
                            title: s.harnessSession
                              ? (isCurrent ? '你已经在这一条会话里' : '切到会话 ' + String(s.harnessSession))
                              : '这单没记 harness_session，点一下会说明补法',
                            onClick: () => openRow(s),
                          },
                            React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6, color: meta.color, fontSize: 'var(--t-sm)', fontWeight: 700, whiteSpace: 'nowrap' } },
                              React.createElement(Dot, { color: meta.color, hollow: s.status === 'unknown' }), meta.label),
                            React.createElement('span', { className: 'sleu-ledger-sid', title: String(s.sessionId || '') }, String(s.sessionId || '—')),
                            React.createElement('span', { className: 'sleu-ledger-sum', title: s.summarySnippet || s.lastOutput || '' },
                              s.summarySnippet || s.lastOutput || '（没有背景段）'),
                            React.createElement('span', { style: { display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end', whiteSpace: 'nowrap' } },
                              hit ? React.createElement('span', { style: Object.assign(tinyBadge(s.activeCaseInKb ? 'var(--d-green)' : 'var(--d-amber)'), { fontSize: 'var(--t-tiny)' }),
                                title: s.activeCaseInKb ? '命中的案例知识库里已有（可直接对照）' : '命中了案例，但知识库里还没有它（新形态，值得先看）',
                              }, String(s.activeCase) + (s.activeCaseInKb ? '' : ' · 新形态')) : null,
                              s.feedbackPending ? React.createElement('span', {
                                style: Object.assign(tinyBadge('var(--d-amber)'), { fontSize: 'var(--t-tiny)' }),
                                title: '轨迹里 feedback.outcome 还是 pending：给了 fix，现场还没回报是否生效。'
                                  + '它与收尾状态（status）是两条独立的轴——已定位表示这次诊断已收尾，'
                                  + '待回报表示那个 fix 还没被验证。侧栏行首的琥珀色缺环就是这一条。',
                              }, '待回报 · ' + ledgerDebtText(s)) : null,
                              sedStateOf(s) !== 'none' ? React.createElement('span', { style: Object.assign(tinyBadge('var(--d-purple)'), { fontSize: 'var(--t-tiny)' }) }, '已沉淀') : null,
                              isCurrent ? React.createElement('span', { style: Object.assign(tinyBadge('var(--d-blue)'), { fontSize: 'var(--t-tiny)' }) }, '当前') : null,
                              React.createElement('span', { style: { color: T.text2, fontSize: 'var(--t-tiny)' } }, relTime(s.updatedAt || s.createdAt) || '—')),
                            React.createElement('span', { 'aria-hidden': 'true', style: { color: T.text2, fontSize: 'var(--t-md)' } }, '→'))
                        })
                      : React.createElement('div', { className: 'sleu-ledger-empty' },
                          kw ? '没有匹配「' + qText.trim() + '」的会话。' : '「' + activeFilter.label + '」下没有会话。'),
                  ),
          React.createElement('div', { className: 'sleu-ledger-foot' },
            React.createElement('span', null, sortBy === 'value'
              ? '排序：' + VALUE_ORDER_TEXT + '。'
              : '排序：按最后更新时间倒序，行尾那一列就是这个时间。'),
            React.createElement('span', null, '只读 traces/，写操作仍在「诊断」tab 里生成指令。'),
            sorted.length > KW_LIMIT ? React.createElement('span', null, '当前只列前 ' + KW_LIMIT + ' 条，搜索或筛选可收窄。') : null),
        ),
      )
    }


    slots.inject('conversation.view', () => slots.register(
      { name: 'conversation.view', id: 'ascend-diagnose', order: 20, label: '诊断' },
      (props) => React.createElement(TraceView, props),
    ))
    // 指标读的是全库（metrics/ 与判据），与当前会话无关，所以常驻包把它交给整页「Ascend Sleuth」
    // （dsh-plugins/sleuth-console）：没有会话也能打开，会话里不再多一个只显示全库数据的 tab。
    // 动态热加载路径没有整页容器（SLEUTH_VIEWS 不存在），退回原来的 conversation.view tab。
    if (typeof SLEUTH_VIEWS !== 'undefined' && SLEUTH_VIEWS !== null) {
      SLEUTH_VIEWS.metrics = (props) => React.createElement(MetricsView, props)
    } else {
      slots.inject('conversation.view', () => slots.register(
        { name: 'conversation.view', id: 'ascend-metrics', order: 21, label: '指标' },
        (props) => React.createElement(MetricsView, props),
      ))
    }

    // 侧栏两个座位：行首小点（只在空闲已读的行出现）与悬停卡一行。都只读。
    slots.inject('sidebar.session.row.leading', () => slots.register(
      { name: 'sidebar.session.row.leading', id: 'ascend-pending' },
      (props) => React.createElement(TraceRowLeading, props),
    ))
    slots.inject('sidebar.session.row.hover', () => slots.register(
      { name: 'sidebar.session.row.hover', id: 'ascend-pending' },
      (props) => React.createElement(TraceRowHover, props),
    ))
    // 侧栏页脚：诊断记录入口。它是**附加**项（新 id 落在自带项旁边，不替换任何一格）；
    // 侧栏收起时只剩图标（`wide: false`）。
    slots.inject('sidebar.footer.action', () => slots.register(
      { name: 'sidebar.footer.action', id: 'sleu-ledger-entry', order: 30, label: '诊断记录' },
      (props) => React.createElement(LedgerEntryButton, props),
    ))
    // 帧级浮层：诊断记录本体。`shell.overlay` 是点击穿透的附加层，所以浮层自己打开 pointer-events。
    slots.inject('shell.overlay', () => slots.register(
      { name: 'shell.overlay', id: 'sleu-ledger-overlay', order: 40, label: '诊断记录' },
      () => React.createElement(LedgerPanel),
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
// ---- dsh-plugins/ev-panel/panel-client.js (sha256:f684735469ce) 原文开始 ----
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

    // 自演进看板读的是全库的卡与体检判决，与当前会话无关：常驻包把它交给整页「Ascend Sleuth」
    // （dsh-plugins/sleuth-console）；动态热加载路径没有整页容器，退回 conversation.view tab。
    if (typeof SLEUTH_VIEWS !== 'undefined' && SLEUTH_VIEWS !== null) {
      SLEUTH_VIEWS.evolve = (props) => React.createElement(BoardView, props)
    } else {
      slots.inject('conversation.view', () => slots.register(
        { name: 'conversation.view', id: 'ascend-evolve', order: 22, label: '自演进' },
        (props) => React.createElement(BoardView, props),
      ))
    }
  },
}
// ---- 原文结束 ----
        })()
      },
    },
    {
      id: 'sleuth-console',
      build(host, styles) {
        return (function () {
// ---- dsh-plugins/sleuth-console/console-client.js (sha256:119062e6c579) 原文开始 ----
// sleuth-console/console-client.js —— 常驻包里的整页「Ascend Sleuth」（client-only）
//
// 为什么单有这一页：指标与自演进读的是**全库**（`metrics/`、`proposals/`、`knowledge/`），
// 与当前会话无关。挂在 `conversation.view` 上等于"必须先开一单诊断才能看库"，而且每个会话
// 各记一份"停在哪个全局页"。整页挂在 `main` + `sidebar.panellist`：左侧多一个图标，没有会话
// 也能打开；会话里只留「诊断」一个 tab。
//
// 两个子页的组件不在这里。两个面板 apply 时把视图登记进 `SLEUTH_VIEWS`（常驻包的生成器在
// 包里建这个对象）；动态热加载路径没有它，面板会退回 `conversation.view`，这一页也就不挂载。
//
// 只读边界不变：只渲染 RPC 读到的数据 + 给可复制指令，不做决策、不写仓库。

return {
  apply(ctx) {
    // 动态热加载路径没有整页容器：安静退出，面板自己注册 tab。
    if (typeof SLEUTH_VIEWS === 'undefined' || SLEUTH_VIEWS === null) return
    const slots = ctx.get('slots')
    if (slots === undefined) return

    const PANEL_ID = 'ascend-sleuth-console'
    const PANEL_LABEL = 'Ascend Sleuth'

    const VIEWS = [
      { id: 'metrics', label: '指标' },
      { id: 'evolve', label: '自演进' },
    ]

    const styleHost = typeof styles !== 'undefined' && styles !== null ? styles : ctx.get('styles')
    const CSS = `
      .sleu-console{height:100%;box-sizing:border-box;overflow:auto;padding:18px 0 40px;
        font-family:var(--font-sans);color:var(--dsw-alias-label-primary);
        background:var(--dsw-alias-bg-layer-1)}
      .sleu-console-inner{max-width:1180px;margin:0 auto;padding:0 20px}
      .sleu-console-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap}
      .sleu-console-title{font-size:var(--t-2xl);font-weight:700;letter-spacing:.2px}
      .sleu-console-sub{margin-top:3px;font-size:var(--t-sm);color:var(--dsw-alias-label-secondary)}
      .sleu-console-tabs{display:flex;gap:18px;margin-top:14px;border-bottom:1px solid var(--hair)}
      .sleu-console-tab{appearance:none;border:0;border-bottom:2px solid transparent;background:none;
        padding:6px 2px 9px;font:inherit;font-size:var(--t-md);color:var(--dsw-alias-label-secondary);
        cursor:pointer;transition:color .16s ease,border-color .16s ease}
      .sleu-console-tab:hover{color:var(--dsw-alias-label-primary)}
      .sleu-console-tab[data-on="1"]{color:var(--dsw-alias-label-primary);font-weight:600;border-bottom-color:var(--acc-blue)}
      .sleu-console-tab:focus-visible{outline:none;border-radius:var(--r-xs);
        box-shadow:0 0 0 3px color-mix(in srgb, var(--acc-blue) 22%, transparent)}
      .sleu-console-body{padding-top:2px}
      .sleu-console-empty{padding:20px 0;font-size:var(--t-md);color:var(--dsw-alias-label-secondary)}
    `
    let cssDisposer = null
    if (styleHost !== undefined && styleHost !== null && typeof styleHost.insert === 'function') {
      cssDisposer = styleHost.insert(CSS)
    }

    // 图标与 dsh-plugins/sleuth-console/icon.svg 同形（render_check 会逐条比对 path 数据）：
    // 方框取芯片的形，里面一条体检读数线——读的是全库健康，不是某一单的轨迹。
    function ConsoleIcon(props) {
      const size = props && typeof props.size === 'number' ? props.size : 18
      return React.createElement('svg', {
        viewBox: '0 0 24 24', width: size, height: size, fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round',
        'aria-hidden': 'true',
      },
        React.createElement('rect', { x: 3.6, y: 3.6, width: 16.8, height: 16.8, rx: 5 }),
        React.createElement('path', { d: 'M6.4 12h2.1l1.5-3.1 2.3 6.2 1.5-3.1h3.8' }),
      )
    }

    function ConsolePage(props) {
      const requested = props && (props.view === 'metrics' || props.view === 'evolve') ? props.view : 'metrics'
      const [active, setActive] = React.useState(requested)
      const view = SLEUTH_VIEWS[active]
      return React.createElement('div', { className: 'sleu-console' },
        React.createElement('div', { className: 'sleu-console-inner' },
          React.createElement('div', { className: 'sleu-console-head' },
            React.createElement('div', null,
              React.createElement('div', { className: 'sleu-console-title' }, PANEL_LABEL),
              React.createElement('div', { className: 'sleu-console-sub' }, '全库读数 · 判据判决 · 自演进'),
            ),
          ),
          React.createElement('div', { className: 'sleu-console-tabs', role: 'tablist' },
            VIEWS.map(item => React.createElement('button', {
              key: item.id,
              type: 'button',
              role: 'tab',
              'aria-selected': active === item.id ? 'true' : 'false',
              'data-on': active === item.id ? '1' : '0',
              className: 'sleu-console-tab',
              onClick: () => setActive(item.id),
            }, item.label)),
          ),
          React.createElement('div', { className: 'sleu-console-body' },
            view
              ? React.createElement(view, { sessionId: props && props.sessionId })
              : React.createElement('div', { className: 'sleu-console-empty' },
                '这个子页没接上：面板源码没登记视图（重装常驻包或重启 DSH Desktop）。'),
          ),
        ),
      )
    }

    const disposers = []
    disposers.push(slots.inject('main', () => slots.register({
      name: 'main',
      key: PANEL_ID,
    }, ConsolePage)))
    disposers.push(slots.inject('sidebar.panellist', () => slots.register({
      name: 'sidebar.panellist',
      id: PANEL_ID,
      order: 30,
      label: PANEL_LABEL,
    }, ConsoleIcon)))

    if (cssDisposer !== undefined && cssDisposer !== null) disposers.push(cssDisposer)

    return () => {
      for (const dispose of disposers) {
        try {
          if (typeof dispose === 'function') dispose()
        } catch (e) { /* 一个卸载失败不阻塞其余 */ }
      }
    }
  },
}
// ---- 原文结束 ----
        })()
      },
    },
    ]

    exports.name = 'dsh-sleuth-panels'
    exports.inject = ['slots', 'connection', 'sessions']
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
