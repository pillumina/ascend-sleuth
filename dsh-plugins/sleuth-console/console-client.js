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

    // 顺序即 tab 顺序，第一项是打开整页时的默认子页。
    const VIEWS = [
      { id: 'knowledge', label: '知识库' },
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

      /* ── 知识库子页 ─────────────────────────────────────────────────────
         四块：读数、状态提示条、同步源、四个开关与检查间隔。配色沿用两个面板的角色
         （--c-* 文字 / --tint-* 大块底 / --hair 描边），不新增色值。 */
      .sleu-kb{padding-top:14px}
      .sleu-kb-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
      .sleu-kb-stat{padding:12px 14px;border:1px solid var(--hair);border-radius:var(--r-md);
        background:var(--dsw-alias-bg-layer-1);box-shadow:var(--elev-1)}
      .sleu-kb-k{font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-v{margin-top:5px;font-family:var(--font-mono);font-size:var(--t-xl);font-weight:650;
        letter-spacing:-.01em;font-variant-numeric:tabular-nums}
      .sleu-kb-v.is-warn{color:var(--c-amber)}
      .sleu-kb-v.is-ok{color:var(--c-green)}
      .sleu-kb-v.is-muted{color:var(--dsw-alias-label-secondary);font-size:var(--t-lg)}
      .sleu-kb-v-unit{margin-left:4px;font-family:var(--font-sans);font-size:var(--t-tiny);
        font-weight:400;color:var(--dsw-alias-label-secondary)}
      .sleu-kb-note{margin-top:3px;font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-banner{display:flex;align-items:flex-start;gap:9px;margin-top:12px;padding:10px 12px;
        border:1px solid var(--hair);border-radius:var(--r-sm);font-size:var(--t-sm);
        line-height:var(--lh-base);color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-2)}
      .sleu-kb-banner.is-warn{background:var(--tint-amber);border-color:color-mix(in srgb,var(--acc-amber) 34%,transparent);color:var(--c-amber)}
      .sleu-kb-banner.is-ok{background:var(--tint-green);border-color:color-mix(in srgb,var(--acc-green) 34%,transparent);color:var(--c-green)}
      .sleu-kb-banner.is-err{background:var(--tint-red);border-color:color-mix(in srgb,var(--acc-red) 34%,transparent);color:var(--c-red)}
      .sleu-kb-bmain{min-width:0;flex:1}
      .sleu-kb-bdot{width:7px;height:7px;margin-top:5px;flex:0 0 auto;border-radius:var(--r-pill);background:currentColor}
      .sleu-kb-bhint{margin-top:3px;font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-bdetail{margin-top:5px;font-family:var(--font-mono);font-size:var(--t-tiny);
        color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere;white-space:pre-wrap}
      .sleu-kb-bact{flex:0 0 auto}
      .sleu-kb-cmd{display:inline-block;margin-top:5px;padding:2px 6px;border:1px solid var(--hair);
        border-radius:var(--r-xs);background:var(--dsw-alias-bg-layer-1);font-family:var(--font-mono);
        font-size:var(--t-tiny);color:var(--dsw-alias-label-primary);overflow-wrap:anywhere}
      .sleu-kb-card{margin-top:12px;padding:14px 16px;border:1px solid var(--hair);
        border-radius:var(--r-md);background:var(--dsw-alias-bg-layer-1);box-shadow:var(--elev-1)}
      .sleu-kb-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}
      .sleu-kb-card-t{font-size:var(--t-lg);font-weight:700;color:var(--dsw-alias-label-primary)}
      .sleu-kb-card-sub{margin-top:2px;font-size:var(--t-sm);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-row{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-top:12px}
      .sleu-kb-field{display:flex;flex-direction:column;gap:4px;min-width:0}
      .sleu-kb-field>label{font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-select{appearance:none;min-width:150px;max-width:100%;padding:6px 10px;
        border:1px solid var(--hair);border-radius:var(--r-sm);background:var(--dsw-alias-bg-layer-2);
        color:var(--dsw-alias-label-primary);font:inherit;font-size:var(--t-md)}
      .sleu-kb-select:disabled{opacity:.55;cursor:not-allowed}
      .sleu-kb-hint{font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary);padding-bottom:7px}
      .sleu-kb-dirty{margin-top:10px;font-size:var(--t-tiny);color:var(--c-amber)}
      .sleu-kb-empty{padding:12px 0 2px;font-size:var(--t-md);color:var(--dsw-alias-label-secondary);
        line-height:var(--lh-prose)}
      .sleu-kb-switch-row{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:12px 0;
        border-top:1px solid var(--hair)}
      .sleu-kb-switch-row:first-child{padding-top:0;border-top:0}
      .sleu-kb-switch-main{min-width:0}
      .sleu-kb-switch-t{font-size:var(--t-md);font-weight:600;color:var(--dsw-alias-label-primary)}
      .sleu-kb-switch-d{margin-top:4px;max-width:620px;font-size:var(--t-sm);
        color:var(--dsw-alias-label-secondary);line-height:var(--lh-base)}
      .sleu-kb-switch-src{margin-top:5px;font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-switch{position:relative;flex:0 0 auto;width:38px;height:22px;margin-top:2px;padding:0;
        border:1px solid var(--hair);border-radius:var(--r-pill);background:var(--dsw-alias-bg-layer-2);
        cursor:pointer;transition:background-color var(--m-fast) var(--e-out),border-color var(--m-fast) var(--e-out)}
      .sleu-kb-switch::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;
        border-radius:var(--r-pill);background:#fff;box-shadow:var(--elev-1);
        transition:transform var(--m-fast) var(--e-out)}
      .sleu-kb-switch[aria-checked="true"]{background:var(--acc-blue);border-color:var(--acc-blue)}
      .sleu-kb-switch[aria-checked="true"]::after{transform:translateX(16px)}
      .sleu-kb-switch:disabled{opacity:.5;cursor:not-allowed}
      .sleu-kb-foot{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px;
        font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-code{padding:1px 6px;border:1px solid var(--hair);border-radius:var(--r-xs);
        background:var(--dsw-alias-bg-layer-2);font-family:var(--font-mono);font-size:var(--t-tiny)}
      /* 页脚常驻的归属仓行：只读时是一行事实，点「修改」在同排展开远端下拉。 */
      .sleu-kb-idrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px;
        font-size:var(--t-tiny);color:var(--dsw-alias-label-secondary)}
      .sleu-kb-id{overflow-wrap:anywhere}
      .sleu-kb-idrow.is-warn .sleu-kb-id{color:var(--c-amber)}
      .sleu-kb-spin{display:inline-block;width:10px;height:10px;margin-right:6px;box-sizing:border-box;
        border:1.5px solid currentColor;border-right-color:transparent;border-radius:var(--r-pill);
        vertical-align:-1px;animation:sleu-kb-rot .9s linear infinite}
      @keyframes sleu-kb-rot{to{transform:rotate(360deg)}}
      .sleu-kb-skel{height:52px;border-radius:var(--r-md)}
      @media (prefers-reduced-motion: reduce){
        .sleu-console,.sleu-console *{transition-duration:.001ms !important;animation-duration:.001ms !important;animation-delay:0ms !important}
      }
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

    // ── 知识库子页 ────────────────────────────────────────────────────────────
    //
    // 读数全部由 host 的 `ascend-kb-sync-*` 端点给：脚本产出，面板不读文件、不碰 git。
    // 打开本页只跑 `--show`（读本机状态，不 fetch 远端）；点「立即同步」才跑 `--merge`。
    // 失败按原因给一句中文（无远端 / 超时 / 非检出 / 工作区不干净……），内部错误码不上屏。
    const KB_SETTINGS_PATH = '.local/settings.json'
    const KB_REASON = {
      E_NO_SCRIPT: '本机检出里没有同步脚本 scripts/kb_sync.py',
      E_NOT_GIT: '当前目录不是 git 检出',
      E_NO_REMOTE: '本机没有这个远端',
      E_NETWORK: '连不上远端',
      E_CREDENTIAL: '拿不到 git 凭据（SSH 主机密钥校验失败或密钥不可用，或 https 认证失败）',
      E_TIMEOUT: '请求超时',
      E_DIRTY: '工作区有未提交改动',
      E_NOT_FF: '本地提交不能快进',
      E_WORKTREE: '当前在 worktree 里',
      E_PERM: '当前会话不能写仓库',
      E_UNSUPPORTED: '本机脚本还不支持这个操作',
      E_BAD_OUTPUT: '脚本输出不是 JSON',
      E_NO_CWD: '解析不到仓库目录',
      E_SHELL: 'shell 服务不可用',
      E_PYTHON: '找不到 Python 3 解释器',
      E_ARGS: '远端或分支名不完整',
      E_LOCK: '远端的引用锁被占用',
      E_DISABLED: '同步已关闭（个人设置）',
      E_OFFLINE: '离线部署',
      E_BRANCH: '当前不在配置分支上',
      E_MERGE_IN_PROGRESS: '上一次合并还没结束',
      E_AUTO_MERGE_OFF: '自动合并已关闭',
      E_SAME_REPO: '同步源与归属仓不同源',
      E_IDENTITY: '归属仓解析不到，未自动合并',
      E_FETCH: '拉取失败',
      E_CAS: '设置文件刚被改过，刷新后重试',
      E_SCRIPT: '本机脚本报错',
    }
    function kbReasonOf(r) {
      if (!r) return '本机脚本报错'
      const key = String(r.code || r.reason_code || '')
      if (KB_REASON[key]) return KB_REASON[key]
      const msg = String(r.message || r.reason || '').trim()
      if (msg) return msg.replace(/[。！？]$/, '')
      return '本机脚本报错'
    }
    // 失败后给一条能立刻做的动作。只对"读者能处理"的原因给，其余只说原因。
    function kbHintFor(code) {
      if (code === 'E_NO_SCRIPT') return '先更新检出；脚本到位后重开本页。'
      if (code === 'E_NOT_GIT') return '在仓库根目录打开面板。'
      if (code === 'E_PYTHON') return '装好 Python 3，并确保在 PATH 里。'
      if (code === 'E_TIMEOUT') return '检查网络与 git 凭据后重试。'
      if (code === 'E_NETWORK') return '检查网络与代理；修好后点「立即同步」重试。'
      if (code === 'E_FETCH') return '检查网络与 git 凭据；修好后点「立即同步」重试。'
      if (code === 'E_CREDENTIAL') {
        return '检查 git 凭据（SSH 密钥、known_hosts）；后台检查可在下方打开「后台检查用完全权限」。'
      }
      if (code === 'E_SKIPPED') return '过一会儿再点「立即同步」。'
      if (code === 'E_NO_REMOTE') return '在仓库根目录执行 git remote add <名字> <地址>，再刷新本页。'
      if (code === 'E_DIRTY') return '先提交或 git stash，再点「立即同步」。'
      if (code === 'E_NOT_FF') return '本地提交不能快进；处理后再同步。'
      if (code === 'E_WORKTREE') return '在 worktree 里不自动合并；回主检出再试。'
      if (code === 'E_SAME_REPO') return '把同步源设为归属仓，或把同步源换到与归属仓同源的远端。'
      if (code === 'E_IDENTITY') return '改回 origin（默认），或把该远端补回来。'
      return ''
    }
    function kbShortRev(v) {
      const s = String(v || '').trim()
      if (!s) return ''
      return s.length > 9 ? s.slice(0, 7) : s
    }
    function kbPad(n) { return String(n).padStart(2, '0') }
    // 「上次核对」与「上次使用」共用：当天与昨天带时刻，更早给日期。
    function kbStamp(value) {
      if (!value) return ''
      const t = new Date(value).getTime()
      if (isNaN(t)) return ''
      const d = new Date(t)
      const hm = kbPad(d.getHours()) + ':' + kbPad(d.getMinutes())
      const now = new Date()
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
      if (t >= today) return '今天 ' + hm
      if (t >= today - 86400000) return '昨天 ' + hm
      return d.getFullYear() + '-' + kbPad(d.getMonth() + 1) + '-' + kbPad(d.getDate())
    }
    // 距离上一次核对多久。超过 7 天转日期：'93 天前' 读不出是哪一天。
    function kbAgo(value) {
      if (!value) return ''
      const t = new Date(value).getTime()
      if (isNaN(t)) return ''
      const diff = Math.max(0, Date.now() - t)
      const m = Math.floor(diff / 60000)
      if (m < 1) return '刚刚'
      if (m < 60) return m + ' 分钟前'
      const h = Math.floor(m / 60)
      if (h < 24) return h + ' 小时前'
      const d = Math.floor(h / 24)
      if (d > 7) return kbStamp(value)
      return d + ' 天前'
    }
    // 检查间隔的可选项（分钟）：默认 30。设置里是别的整数（命令行写的）时照实显示，
    // 不静默换成 30——那会让下次保存把读者的设置改掉。
    const KB_CHECK_MINUTES = [15, 30, 60, 120]
    function kbCheckMinutesOf(value) {
      const n = Number(value)
      return Number.isInteger(n) && n >= 5 && n <= 720 ? n : 30
    }
    // 草稿：界面上的选择与开关。配置没读到就按"都没开"显示，不假装是默认值；
    // 提醒检查例外：脚本的缺省是开，缺字段时按生效值显示为开。
    function kbDraftOf(payload) {
      const sync = payload && payload.sync && payload.sync.ok === true ? payload.sync.data : null
      const targets = payload && payload.targets && payload.targets.ok === true ? payload.targets.data : null
      const cfg = sync && sync.config ? sync.config : null
      const rec = targets && targets.recommendation ? targets.recommendation : null
      const target = targets && targets.target ? targets.target : null
      const remote = (sync && sync.remote) || (cfg && cfg.remote) || (rec && rec.remote)
        || (target && target.remote) || ''
      const branch = (sync && sync.branch) || (cfg && cfg.branch) || (rec && rec.base)
        || (target && target.base) || ''
      return {
        remote: String(remote || ''),
        branch: String(branch || ''),
        autoCheck: !!(cfg && cfg.auto_check),
        autoMerge: !!(cfg && cfg.auto_merge),
        checkEnabled: !(cfg && cfg.check_enabled === false),
        // 后台检查默认以完全权限跑；缺字段按默认（开），不把旧设置读成受限档。
        checkFullAccess: !(cfg && cfg.check_full_access === false),
        checkMinutes: kbCheckMinutesOf(cfg && cfg.check_minutes),
      }
    }
    // 合并/保存的结果 → 一条提示。成功要给到"到了哪一版、从哪一版来、差多少"。
    function kbMergeFlash(r) {
      // 旧脚本被失败缓存挡下：这次没有 fetch，不是同步失败，用提示而不是错误。
      if (r && r.ok !== true && r.code === 'E_SKIPPED') {
        return { kind: 'warn', code: 'E_SKIPPED', text: '上次失败还在 10 分钟缓存里，本次没有重试。',
          hint: kbHintFor('E_SKIPPED'), detail: r.detail ? String(r.detail) : '' }
      }
      if (!r || r.ok !== true) {
        return { kind: 'err', code: (r && r.code) || '', text: '同步失败：' + kbReasonOf(r) + '。',
          hint: kbHintFor(r && r.code), detail: r && r.detail ? String(r.detail) : '' }
      }
      if (r.merged === false) {
        const why = r.reason_text ? String(r.reason_text).replace(/[。！？]$/, '') : kbReasonOf({ code: r.reason_code })
        if (!r.reason_code && !r.reason_text) {
          return { kind: 'ok', code: '', text: '已经是最新，没有要合并的提交。' }
        }
        return { kind: 'warn', code: r.reason_code ? String(r.reason_code) : '',
          text: '没有自动合并：' + why + '。',
          hint: '处理工作区或本地提交后，再点「立即同步」。' }
      }
      const to = kbShortRev(r.merged_rev)
      const from = kbShortRev(r.previous_rev)
      const behind = typeof r.behind === 'number' ? r.behind : null
      let text = '已同步'
      if (to) text += '到 v' + to
      if (from || behind !== null) {
        const inner = []
        if (from) inner.push('原 v' + from)
        if (behind !== null) inner.push('落后 ' + behind + ' 个提交')
        text += '（' + inner.join('，') + '）'
      }
      text += '。知识立即生效；流程文件下次会话生效。'
      // 面板代码也是这份检出的一部分：同步带进来时，正在运行的旧面板要重启 DSH 才换。
      // 从插件页装的那一份不是仓库副本，重启不会换版本，要先重装。
      if (r.surface && Number(r.surface.panel) > 0) text += '面板代码也更新了：重启 DSH 后生效；从插件页装的要先重装再重启。'
      return { kind: 'ok', code: '', text: text, hint: '回滚：git reset --hard ORIG_HEAD' }
    }

    const KB_BTN = {
      border: '1px solid var(--hair)', borderRadius: 'var(--r-sm)', padding: '5px 12px',
      font: 'inherit', fontSize: 'var(--t-tiny)', fontWeight: 600, cursor: 'pointer',
      background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
      transition: 'background-color var(--m-fast) var(--e-out),border-color var(--m-fast) var(--e-out)',
    }
    const KB_BTN_PRIMARY = Object.assign({}, KB_BTN, {
      border: '1px solid transparent', fontWeight: 700,
      background: 'linear-gradient(135deg,var(--btn-blue-a),var(--btn-blue-b))',
      color: '#fff', boxShadow: '0 1px 3px rgba(37,99,235,.3)',
    })

    function KbStat(props) {
      return React.createElement('div', { className: 'sleu-kb-stat' },
        React.createElement('div', { className: 'sleu-kb-k' }, props.label),
        React.createElement('div', { className: 'sleu-kb-v' + (props.tone ? ' is-' + props.tone : '') },
          props.value,
          props.unit ? React.createElement('span', { className: 'sleu-kb-v-unit' }, props.unit) : null),
        props.note ? React.createElement('div', { className: 'sleu-kb-note' }, props.note) : null,
      )
    }

    function KbBanner(props) {
      return React.createElement('div', { className: 'sleu-kb-banner is-' + (props.kind || 'muted'), role: 'status' },
        React.createElement('span', { className: 'sleu-kb-bdot', 'aria-hidden': 'true' }),
        React.createElement('div', { className: 'sleu-kb-bmain' },
          React.createElement('div', null, props.text),
          props.hint ? React.createElement('div', { className: 'sleu-kb-bhint' }, props.hint) : null,
          props.cmd ? React.createElement('code', { className: 'sleu-kb-cmd' }, props.cmd) : null,
          props.detail ? React.createElement('div', { className: 'sleu-kb-bdetail' }, props.detail) : null,
        ),
        props.action ? React.createElement('div', { className: 'sleu-kb-bact' }, props.action) : null,
      )
    }

    // 开关用 button + role=switch：与上下文的按钮同一套键盘行为，不引入新的表单控件。
    function KbSwitch(props) {
      const checked = !!props.checked
      return React.createElement('button', {
        type: 'button',
        role: 'switch',
        'aria-checked': checked ? 'true' : 'false',
        'aria-label': props.label,
        disabled: !!props.disabled,
        className: 'sleu-kb-switch',
        onClick: () => { if (!props.disabled && typeof props.onChange === 'function') props.onChange(!checked) },
      })
    }

    function KnowledgeView(props) {
      const sessionId = props && props.sessionId ? String(props.sessionId) : null
      const [status, setStatus] = React.useState(null)
      const [loading, setLoading] = React.useState(true)
      const [loadError, setLoadError] = React.useState(null)
      const [draft, setDraft] = React.useState(null)
      const [dirty, setDirty] = React.useState(false)
      const [busy, setBusy] = React.useState('')
      const [flash, setFlash] = React.useState(null)
      const [identityEdit, setIdentityEdit] = React.useState(false)
      const [identityPick, setIdentityPick] = React.useState('')

      // 首屏挂载才显示骨架屏；动作之后的刷新都走 silent：保留已有读数、结果提示与卡片，
      // 原地换新。同步进行中也不换骨架屏——按钮与 aria-busy 表达"正在做"。
      const adopt = React.useCallback((payload, keepDraft) => {
        setStatus(payload)
        setDraft((prev) => (keepDraft && prev ? prev : kbDraftOf(payload)))
        setDirty((prev) => (keepDraft ? prev : false))
      }, [])
      const load = React.useCallback((silent) => {
        if (!silent) setLoading(true)
        host.call('ascend-kb-sync-show', { sessionId })
          .then((payload) => { adopt(payload, !!silent); setLoading(false); setLoadError(null) })
          .catch((e) => {
            // 静默刷新失败不清空页面：手上那份读数比空白更有用。
            if (!silent) { setLoadError(String((e && e.message) || e)); setLoading(false) }
          })
      }, [sessionId, adopt])
      React.useEffect(() => { load() }, [load])

      const sync = status && status.sync ? status.sync : null
      const data = sync && sync.ok === true ? sync.data : null
      const syncState = sync && sync.ok === true ? String(sync.state || 'ok') : ''
      const syncError = sync && sync.ok === true && sync.error ? sync.error : null
      const targetsPart = status && status.targets ? status.targets : null
      const targets = targetsPart && targetsPart.ok === true ? targetsPart.data : null
      const remotes = targets && Array.isArray(targets.remotes) ? targets.remotes : []
      // 三个状态读脚本的真实字段：offline / enabled / same_repo。关闭与离线是两回事，
      // 前者是个人设置，后者是部署声明；同源校验不一致时脚本不自动合并，页面只说这一行。
      const offline = !!(data && data.offline)
      const disabled = !!(data && data.enabled === false)
      const sameRepoMismatch = !!(data && data.same_repo === false)
      const config = data && data.config ? data.config : null
      const cfgSource = offline
        ? '部署声明（offline）'
        : (config ? (config.source === 'default' ? '默认值（未写入 .local/settings.json）' : '个人设置') : '未读到配置')
      // 归属仓：脚本给 identity_* 四项。旧脚本没有这四项时如实说读不到，不拿同步源冒充。
      const identityRemote = data ? String(data.identity_remote || '') : ''
      const identityUrl = data ? String(data.identity_url || '') : ''
      const identityExplicit = !!(data && data.identity_explicit === true)
      const identityResolved = data && data.identity_resolved === false
        ? false
        : (data && data.identity_resolved === true ? true : null)
      const identityRemoteObj = remotes.filter(r => r && r.name === identityRemote)[0] || null
      const identityWhere = identityUrl || (identityRemoteObj
        ? String(identityRemoteObj.url || identityRemoteObj.host || '') : '')
      // 只有**显式配置**的归属仓解析不到才算异常：默认 origin 在本机不存在（单远端检出）时
      // 后端按设计放行合并，identity_resolved 同样是 false，不能误报成「未自动合并」。
      const identityUnresolved = (identityExplicit && identityResolved === false)
        || !!(syncState === 'error' && syncError && syncError.code === 'E_IDENTITY')
      const identityIssue = sameRepoMismatch || identityUnresolved
      const syncRemoteForIdentity = (data && data.remote) || (draft && draft.remote) || ''

      function doMerge() {
        if (busy) return
        setBusy('merge')
        setFlash(null)
        host.call('ascend-kb-sync-merge', { sessionId })
          .then((r) => { setBusy(''); setFlash(kbMergeFlash(r)); load(true) })
          .catch((e) => {
            setBusy('')
            setFlash({ kind: 'err', text: '同步失败：调用不到同步端点。', detail: String((e && e.message) || e) })
          })
      }
      function doSave() {
        if (busy || !draft) return
        setBusy('save')
        setFlash(null)
        host.call('ascend-kb-sync-save', {
          sessionId: sessionId,
          remote: draft.remote,
          branch: draft.branch,
          autoCheck: !!draft.autoCheck,
          autoMerge: !!draft.autoMerge,
          checkEnabled: !!draft.checkEnabled,
          checkFullAccess: !!draft.checkFullAccess,
          checkMinutes: kbCheckMinutesOf(draft.checkMinutes),
          expectSha256: status && status.settings_sha256 ? String(status.settings_sha256) : '',
        })
          .then((r) => {
            setBusy('')
            if (!r || r.ok !== true) {
              setFlash({ kind: 'err', text: '保存失败：' + kbReasonOf(r) + '。', hint: kbHintFor(r && r.code),
                detail: r && r.detail ? String(r.detail) : '' })
              return
            }
            setFlash({ kind: 'ok', text: '已保存到 ' + KB_SETTINGS_PATH + '。修改下次开单生效。' })
            setDirty(false)
            load(true)
          })
          .catch((e) => {
            setBusy('')
            setFlash({ kind: 'err', text: '保存失败：调用不到保存端点。', detail: String((e && e.message) || e) })
          })
      }
      // 写归属仓：页脚「修改」与两条不一致提示共用的动作，走 `ascend-kb-sync-identity`。
      function doIdentity(target) {
        const name = String(target || '').trim()
        if (busy) return
        if (!name) {
          setFlash({ kind: 'err', text: '没有选远端，无法设为归属仓。' })
          return
        }
        setBusy('identity')
        setFlash(null)
        host.call('ascend-kb-sync-identity', {
          sessionId: sessionId,
          remote: name,
          expectSha256: status && status.settings_sha256 ? String(status.settings_sha256) : '',
        })
          .then((r) => {
            setBusy('')
            if (!r || r.ok !== true) {
              setFlash({ kind: 'err', text: '没能设为归属仓：' + kbReasonOf(r) + '。',
                hint: kbHintFor(r && r.code),
                // 参数错误的原文是中文说明（如「远端不存在」），比脚本输出信封更好读；其余保留原文。
                detail: r && r.detail
                  ? (r.code === 'E_ARGS' && r.message ? String(r.message) : String(r.detail))
                  : '' })
              return
            }
            setIdentityEdit(false)
            setFlash({ kind: 'ok', text: '已把 ' + name + ' 设为归属仓。' })
            load(true)
          })
          .catch((e) => {
            setBusy('')
            setFlash({ kind: 'err', text: '没能设为归属仓：调用不到设置端点。',
              detail: String((e && e.message) || e) })
          })
      }
      // 同源分歧只出一条提示：原因 + 一句下一步 + 按钮。「改回 origin」是解析不到时的出口。
      function identityPrompt(kind) {
        const reset = kind === 'reset'
        const target = reset ? 'origin' : syncRemoteForIdentity
        return {
          kind: 'warn',
          code: reset ? 'E_IDENTITY' : 'E_SAME_REPO',
          text: reset ? '归属仓解析不到，未自动合并。' : '同步源与归属仓不同源，未自动合并。',
          hint: reset ? '改回 origin（默认），或把该远端补回来。'
            : '把同步源设为归属仓，或把同步源换到与归属仓同源的远端。',
          action: target ? React.createElement('button', {
            type: 'button', style: KB_BTN, disabled: !!busy, onClick: () => doIdentity(target),
          }, busy === 'identity' ? '设置中' : (reset ? '改回 origin' : '把 ' + target + ' 设为归属仓')) : null,
        }
      }
      function setRemote(name) {
        const picked = remotes.filter(r => r && r.name === name)[0]
        setDraft(Object.assign({}, draft, { remote: name, branch: (picked && picked.base) || (draft && draft.branch) || '' }))
        setDirty(true)
      }
      function setBranch(name) {
        setDraft(Object.assign({}, draft, { branch: name }))
        setDirty(true)
      }
      function setSwitch(key, value) {
        setDraft(Object.assign({}, draft, { [key]: value }))
        setDirty(true)
      }
      function setCheckMinutes(value) {
        setDraft(Object.assign({}, draft, { checkMinutes: kbCheckMinutesOf(value) }))
        setDirty(true)
      }

      if (loading) {
        return React.createElement('div', { className: 'sleu-kb' },
          React.createElement('div', { className: 'sleu-kb-grid' },
            React.createElement('div', { key: 's1', className: 'sleu-kb-skel sleu-skel' }),
            React.createElement('div', { key: 's2', className: 'sleu-kb-skel sleu-skel' }),
            React.createElement('div', { key: 's3', className: 'sleu-kb-skel sleu-skel' }),
            React.createElement('div', { key: 's4', className: 'sleu-kb-skel sleu-skel' })),
          React.createElement('div', { className: 'sleu-kb-hint', style: { paddingTop: 12 } }, '读取本机状态……'))
      }

      const syncAction = (kind) => React.createElement('button', {
        type: 'button',
        style: kind === 'primary' ? KB_BTN_PRIMARY : KB_BTN,
        disabled: !!busy,
        onClick: doMerge,
      }, busy === 'merge'
        ? [React.createElement('span', { key: 'spin', className: 'sleu-kb-spin', 'aria-hidden': 'true' }), '同步中']
        : '立即同步')

      // 一块状态区（四个状态共用）：提示条只换样式与文案，动作位放「立即同步」。
      // 动作位单独算：同步可做时任何一条提示都带着它，做完一次动作不必先关掉提示才能再做。
      let banner = null
      if (flash) {
        // 同源分歧只出一条：结果提示若是这类原因，直接换成带按钮的那条，不再另起一行。
        banner = flash.code === 'E_SAME_REPO' ? identityPrompt('same')
          : (flash.code === 'E_IDENTITY' ? identityPrompt('reset') : Object.assign({}, flash))
      } else if (loadError) {
        banner = { kind: 'err', text: '读取失败：' + loadError + '。',
          hint: '检查本页所在目录是不是仓库根，再刷新本页。' }
      } else if (status && status.ok === false) {
        banner = { kind: 'err', text: '读取失败：' + kbReasonOf(status) + '。',
          hint: kbHintFor(status.code), detail: status.detail ? String(status.detail) : '' }
      } else if (!sync) {
        banner = null
      } else if (sync.ok !== true) {
        banner = { kind: 'err', text: '读不到同步状态：' + kbReasonOf(sync) + '。',
          hint: kbHintFor(sync.code), detail: sync.detail ? String(sync.detail) : '' }
      } else if (syncState === 'offline' || offline) {
        banner = { kind: 'muted', text: '离线部署（' + (data.offline_source || 'deployment.yaml') + '）：不检查更新，也不合并。诊断照常。' }
      } else if (syncState === 'disabled' || disabled) {
        // 「自动检查更新」只管开单自动拉取 / 自动合并；后台提醒检查与手动同步不受它影响。
        banner = { kind: 'muted', text: '已关闭（个人设置）：开单时不自动拉取，也不自动合并。',
          hint: '后台提醒检查与「立即同步」不受这个开关影响。' }
      } else if (syncState === 'error') {
        const errCode = syncError && syncError.code
        banner = errCode === 'E_SAME_REPO' ? identityPrompt('same')
          : (errCode === 'E_IDENTITY' ? identityPrompt('reset')
            : { kind: 'err', text: '同步失败：' + kbReasonOf(syncError) + '。',
              hint: kbHintFor(syncError && syncError.code) })
      } else if (sameRepoMismatch) {
        banner = identityPrompt('same')
      } else if (identityUnresolved) {
        // 显式配置的归属仓解析不到：打开本页就该看到可操作的出口，不能只等点同步后才报。
        banner = identityPrompt('reset')
      } else if (syncState === 'no-remote') {
        banner = remotes.length
          ? { kind: 'muted', text: '还没有配置同步源。选一个远端后点「保存」。' }
          : { kind: 'warn', text: '本机没有配置远端。同步源无处可选。',
            hint: '添加远端后刷新本页。', cmd: 'git remote add origin <地址>' }
      } else if (syncState === 'unfetched') {
        banner = { kind: 'muted', text: '远端分支还没拉取过（' + (data.remote || '?') + '/' + (data.branch || '?') + '）。',
          hint: '点「立即同步」拉一次远端，再按配置合并。' }
      } else if (data.last_failure) {
        // 上一次 fetch 失败过（脚本从状态文件读出）：重新打开本页也显示原因与 git 原始输出。
        // 失败的来源也可能是后台提醒检查（kb_sync 记 `last_source: check`）：那不是用户的
        // 同步失败，标题要分开说。提醒检查关掉后这条不再用失败横幅催人，只留一句说明。
        const fromCheck = data.last_source === 'check'
        const checkOff = fromCheck && draft && draft.checkEnabled === false
        if (checkOff) {
          banner = { kind: 'muted',
            text: '提醒检查已关闭，上次后台检查失败：' + kbReasonOf(data.last_failure) + '。',
            detail: data.last_error ? String(data.last_error) : '' }
        } else {
          // 凭据类失败的下一步取决于开关：没开完全权限就先指到开关；开了还失败说明凭据本身
          // 有问题，指到终端复核。
          const credentialHint = fromCheck && data.last_failure.code === 'E_CREDENTIAL'
            ? (draft && draft.checkFullAccess === false
              ? '后台检查没开完全权限，受限档位里拿不到凭据；可在下方打开「后台检查用完全权限」，或去终端跑 python3 scripts/kb_sync.py --merge --force。'
              : '当前设置已用完全权限；上次失败可能发生在打开开关之前，先去终端跑 python3 scripts/kb_sync.py --merge --force 复核 git 凭据。')
            : (fromCheck ? (kbHintFor(data.last_failure.code) || '点「立即同步」重试。') : '点「立即同步」重试。')
          banner = { kind: 'warn',
            text: (fromCheck ? '上次后台检查失败：' : '上次同步失败：') + kbReasonOf(data.last_failure) + '。',
            hint: credentialHint,
            detail: data.last_error ? String(data.last_error) : '' }
        }
      } else if (!targetsPart || targetsPart.ok !== true) {
        banner = { kind: 'err', text: '读不到远端列表：' + kbReasonOf(targets || {}) + '。',
          hint: kbHintFor(targetsPart && targetsPart.code), detail: targetsPart && targetsPart.detail ? String(targetsPart.detail) : '' }
      } else if (!remotes.length) {
        banner = { kind: 'warn', text: '本机没有配置远端。同步源无处可选。',
          hint: '添加远端后刷新本页。', cmd: 'git remote add origin <地址>' }
      } else if (!data.last_checked) {
        banner = { kind: 'muted', text: '还没有核对过远端。',
          hint: '点「立即同步」拉一次远端，再按配置合并。' }
      } else if (data.behind === null) {
        banner = { kind: 'muted', text: '读不到落后的提交数（git rev-list 没有给出数字）。',
          hint: '稍后再点「立即同步」重试。' }
      } else if (typeof data.behind === 'number' && data.behind > 0) {
        // 改动面的计数来自 kb_sync 的 --show：本次合并会带进来的目录。面板代码在 dsh-plugins/ 下，
        // 它更新时旧面板要重启才换，所以在合并前就把这一步说清楚。
        const panelIncoming = !!(data.surface && Number(data.surface.panel) > 0)
        banner = {
          kind: 'warn',
          text: '落后 ' + data.behind + ' 个提交。本次合并会把 knowledge/、references/ 与 skills/ 一起更新；知识立即生效，流程文件下次会话生效。'
            + (panelIncoming ? '面板代码也会更新：重启 DSH 后生效；从插件页装的要先重装。' : ''),
        }
      } else {
        banner = { kind: 'ok', text: '本机与远端一致。' }
      }
      // 手动同步走 `--merge --force`，不受「自动检查更新」（sync.enabled）拦：关着也给按钮。
      const canSync = !offline && remotes.length > 0 && sync && sync.ok === true
      // 同步进行中也保留这颗按钮（文案变「同步中」+ spinner，禁用），页面不换骨架屏。
      if (banner && !banner.action && canSync) {
        banner.action = syncAction('quiet')
      } else if (banner && !banner.action && banner.kind === 'err' && !busy) {
        banner.action = React.createElement('button', {
          type: 'button', style: KB_BTN, onClick: () => load(),
        }, '重试')
      }
      const bannerNode = banner ? KbBanner(banner) : null

      const remoteValue = draft ? draft.remote : ''
      const remoteOptions = remotes.map(r => React.createElement('option', { key: 'r-' + r.name, value: r.name },
        r.name + (r.host ? ' · ' + r.host : '') + (r.last_used ? ' · 上次使用 ' + kbStamp(r.last_used) : '')))
      if (remoteValue && !remotes.some(r => r && r.name === remoteValue)) {
        remoteOptions.unshift(React.createElement('option', { key: 'r-stale', value: remoteValue },
          remoteValue + ' · 本机没有这个远端'))
      }
      const selected = remotes.filter(r => r && r.name === remoteValue)[0] || null
      const branches = []
      if (selected && selected.base) branches.push(selected.base)
      if (draft && draft.branch) branches.push(draft.branch)
      if (targets && targets.target && targets.target.base) branches.push(targets.target.base)
      const branchList = branches.filter((b, i) => b && branches.indexOf(b) === i)
      const lastUsed = selected && selected.last_used ? kbStamp(selected.last_used) : ''
      const canSave = !offline && remotes.length > 0 && !!draft && !!draft.remote && !busy

      const sourceCard = React.createElement('div', { className: 'sleu-kb-card' },
        React.createElement('div', { className: 'sleu-kb-card-head' },
          React.createElement('div', null,
            React.createElement('div', { className: 'sleu-kb-card-t' }, '同步源'),
            React.createElement('div', { className: 'sleu-kb-card-sub' }, '这个远端会 merge 进本机检出。列事实，不预设用途。')),
          React.createElement('button', {
            type: 'button',
            style: Object.assign({}, KB_BTN, (!canSave || !dirty) ? { opacity: 0.55, cursor: 'not-allowed' } : {}),
            disabled: !canSave || !dirty,
            onClick: doSave,
          }, busy === 'save' ? '保存中' : '保存')),
        remotes.length === 0
          ? React.createElement('div', { className: 'sleu-kb-empty' },
            offline
              ? '离线部署：不读同步源。'
              : (!targetsPart || targetsPart.ok !== true)
                ? '读不到远端列表。先修好 scripts/pr_status.py 的调用，再刷新本页。'
                : '本机没有配置远端。先在仓库根目录执行 git remote add <名字> <地址>，再刷新本页。')
          : React.createElement('div', { className: 'sleu-kb-row' },
            React.createElement('div', { className: 'sleu-kb-field' },
              React.createElement('label', { htmlFor: 'sleu-kb-remote' }, '远端'),
              React.createElement('select', {
                id: 'sleu-kb-remote',
                className: 'sleu-kb-select',
                'aria-label': '同步源远端',
                value: remoteValue,
                disabled: offline || !!busy,
                onChange: (e) => setRemote(e.target.value),
              }, remoteOptions)),
            React.createElement('div', { className: 'sleu-kb-field' },
              React.createElement('label', { htmlFor: 'sleu-kb-branch' }, '分支'),
              React.createElement('select', {
                id: 'sleu-kb-branch',
                className: 'sleu-kb-select',
                'aria-label': '同步源分支',
                value: draft ? draft.branch : '',
                disabled: offline || !!busy || branchList.length === 0,
                onChange: (e) => setBranch(e.target.value),
              }, branchList.length
                ? branchList.map(b => React.createElement('option', { key: 'b-' + b, value: b }, b))
                : React.createElement('option', { value: '' }, '远端没给分支'))),
            lastUsed ? React.createElement('div', { className: 'sleu-kb-hint' }, '上次使用：' + lastUsed) : null),
        dirty ? React.createElement('div', { className: 'sleu-kb-dirty' },
          '有未保存的改动。点「保存」写进 ' + KB_SETTINGS_PATH + '。') : null,
      )

      const switchRow = (title, desc, key) => React.createElement('div', { className: 'sleu-kb-switch-row', key: key },
        React.createElement('div', { className: 'sleu-kb-switch-main' },
          React.createElement('div', { className: 'sleu-kb-switch-t' }, title),
          React.createElement('div', { className: 'sleu-kb-switch-d' }, desc),
          React.createElement('div', { className: 'sleu-kb-switch-src' }, '来源：' + cfgSource)),
        React.createElement(KbSwitch, {
          label: title,
          checked: !!(draft && draft[key]),
          disabled: offline || !draft || !!busy,
          onChange: (v) => setSwitch(key, v),
        }))

      const checkChoices = KB_CHECK_MINUTES.slice()
      if (draft && checkChoices.indexOf(draft.checkMinutes) < 0) checkChoices.push(draft.checkMinutes)
      const switches = React.createElement('div', { className: 'sleu-kb-card' },
        switchRow('自动检查更新', '诊断开单时 fetch 一次，并按配置自动合并。关闭后开单不自动拉取、不自动合并；不影响「提醒检查」与「立即同步」。', 'autoCheck'),
        switchRow('自动合并', '仅当工作区干净、当前在配置分支上、且可快进时合并。不满足只提示，不 rebase。', 'autoMerge'),
        switchRow('提醒检查', '后台定期检查知识库是否落后，落后时在诊断状态条提示。关闭后后台不再检查、不再提示；不影响开单自动拉取与「立即同步」。', 'checkEnabled'),
        switchRow('后台检查用完全权限', '后台提醒检查默认以完全权限跑 scripts/kb_sync.py --check（只 fetch、不改检出），不经过 DSH 沙箱。关闭后按 DSH 部署默认的权限模式跑；受限权限模式可能拿不到 git 凭据。只影响这一条检查。', 'checkFullAccess'),
        React.createElement('div', { className: 'sleu-kb-switch-row', key: 'checkMinutes' },
          React.createElement('div', { className: 'sleu-kb-switch-main' },
            React.createElement('div', { className: 'sleu-kb-switch-t' }, '检查间隔'),
            React.createElement('div', { className: 'sleu-kb-switch-d' }, '「提醒检查」打开时按这个间隔检查一次。'),
            React.createElement('div', { className: 'sleu-kb-switch-src' }, '来源：' + cfgSource)),
          React.createElement('select', {
            className: 'sleu-kb-select',
            'aria-label': '检查间隔',
            value: draft ? String(draft.checkMinutes) : '30',
            disabled: offline || !draft || !!busy || !(draft && draft.checkEnabled),
            onChange: (e) => setCheckMinutes(e.target.value),
          }, checkChoices.map(n => React.createElement('option', { key: 'm-' + n, value: String(n) }, n + ' 分钟')))),
      )

      // 页脚常驻的归属仓一行：读事实；「修改」在同排展开远端下拉，写入走新端点。
      // 与同步源不一致时这行用警示色，但不再复制一条带按钮的提示（提示条只留一条）。
      let identityText = '归属仓：读不到'
      if (data) {
        if (identityRemote) {
          identityText = '归属仓：' + identityRemote + '（' + (identityWhere || '地址未知') + '）'
            + (identityExplicit ? '' : ' · 默认')
        } else {
          identityText = '归属仓：读不到（同步脚本还没给这一项）'
        }
        if (identityUnresolved) identityText += ' · 解析不到'
        else if (sameRepoMismatch) identityText += ' · 与同步源不同源'
      }
      const identityOptions = remotes.map(r => React.createElement('option',
        { key: 'ident-' + r.name, value: r.name }, r.name + (r.host ? ' · ' + r.host : '')))
      const identityRow = React.createElement('div', {
        className: 'sleu-kb-idrow' + (identityIssue ? ' is-warn' : ''),
      },
        React.createElement('span', { className: 'sleu-kb-id' }, identityText),
        data ? React.createElement('button', {
          type: 'button', style: KB_BTN, disabled: !!busy,
          onClick: () => {
            if (identityEdit) { setIdentityEdit(false); return }
            setIdentityPick(identityRemote || (remotes[0] && remotes[0].name) || '')
            setIdentityEdit(true)
          },
        }, identityEdit ? '收起' : '修改') : null,
        identityEdit && remotes.length
          ? React.createElement('select', {
            className: 'sleu-kb-select',
            'aria-label': '归属仓远端',
            value: identityPick,
            disabled: !!busy,
            onChange: (e) => setIdentityPick(e.target.value),
          }, identityOptions)
          : null,
        identityEdit && remotes.length
          ? React.createElement('button', {
            type: 'button', style: KB_BTN, disabled: !!busy || !identityPick,
            onClick: () => doIdentity(identityPick),
          }, busy === 'identity' ? '设置中' : '设为归属仓')
          : null,
        identityEdit && !remotes.length
          ? React.createElement('span', { className: 'sleu-kb-hint' }, '没有可选的远端。')
          : null,
      )

      const behindKnown = data && typeof data.behind === 'number'
      const behindTone = !behindKnown ? 'muted' : (data.behind > 0 ? 'warn' : 'ok')
      const behindNote = data && typeof data.skipped === 'number' && data.skipped > 0
        ? '另有 ' + data.skipped + ' 个提交跳过'
        : ''
      const localRev = data && data.local_rev ? data.local_rev : ''
      const remoteRev = data && data.remote_rev ? data.remote_rev : ''
      const lastChecked = data && data.last_checked ? data.last_checked : ''

      return React.createElement('div', { className: 'sleu-kb', 'aria-busy': busy ? 'true' : 'false' },
        React.createElement('div', { className: 'sleu-kb-grid' },
          React.createElement(KbStat, { key: 'local', label: '本机版本',
            value: localRev ? 'v' + kbShortRev(localRev) : '未记录',
            tone: localRev ? '' : 'muted' }),
          React.createElement(KbStat, { key: 'remote', label: '远端版本',
            value: remoteRev ? 'v' + kbShortRev(remoteRev) : (offline ? '不检查' : '未核对'),
            tone: remoteRev ? '' : 'muted' }),
          React.createElement(KbStat, { key: 'behind', label: '落后',
            value: behindKnown ? String(data.behind) : (lastChecked ? '读不出' : '未核对'),
            unit: behindKnown ? '个提交' : '',
            tone: behindTone,
            note: behindNote }),
          React.createElement(KbStat, { key: 'checked', label: '上次核对',
            value: lastChecked ? kbAgo(lastChecked) : '从未核对',
            tone: lastChecked ? '' : 'muted' })),
        bannerNode,
        sourceCard,
        switches,
        identityRow,
        React.createElement('div', { className: 'sleu-kb-foot' },
          React.createElement('span', null, '配置'),
          React.createElement('code', { className: 'sleu-kb-code' }, KB_SETTINGS_PATH),
          React.createElement('span', null, '·'),
          React.createElement('span', null, '修改下次开单生效'),
          React.createElement('span', { style: { marginLeft: 'auto' } }, '打开本页不联网；「立即同步」才请求')),
      )
    }

    // 视图由本页自己登记：整页是唯一持有它的地方，不像指标/自演进那样由面板登记。
    SLEUTH_VIEWS.knowledge = (props) => React.createElement(KnowledgeView, props)

    function ConsolePage(props) {
      const requested = props && VIEWS.some(item => item.id === props.view) ? props.view : VIEWS[0].id
      const [active, setActive] = React.useState(requested)
      const view = SLEUTH_VIEWS[active]
      return React.createElement('div', { className: 'sleu-console' },
        React.createElement('div', { className: 'sleu-console-inner' },
          React.createElement('div', { className: 'sleu-console-head' },
            React.createElement('div', null,
              React.createElement('div', { className: 'sleu-console-title' }, PANEL_LABEL),
              React.createElement('div', { className: 'sleu-console-sub' }, '知识库同步 · 全库读数与判据判决 · 自演进'),
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
