/* eslint-disable */
// dsh-sleuth-copilot —— 浏览器半：诊断交互层
//
// 四个面共用一份数据、一套动作与一条偏好：
//   1. conversation.input.dock    状态条（可收起，收起状态记住）
//   2. conversation.input.right   输入区工具条入口（带待回报角标）
//   3. shell.overlay              诊断总览（全库列表 + 键盘操作 + 改状态）
//   4. 共享的写入菜单与表单：收尾 / 重开 / 沉淀状态；回报结果生成指令（该轴暂无脚本写入口）
//
// 读：Host 半的 copilot-state（判据在 scripts/_trace_state.py）。
// 写：Host 半的 copilot-transition → scripts/trace_transition.py（校验 + CAS + 事件）。
// 浏览器这里不解析 YAML，也不自己判状态：显示与可选动作都跟着投影给出的字段走。

window.__ModuleLoader__.load({
  id: 'dsh-sleuth-copilot',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement

    const CHANNEL = '/sleuth-copilot'
    const NS = 'sleuth-copilot'
    // 与 package.json 的 version 一起改；页面上的版本串是判断装没装到新版的依据。
    const PLUGIN_VERSION = '0.7.1'
    const POLL_MS = 10000
    const PREFS_KEY = 'dsh-sleuth-copilot.prefs.v2'
    const FILTER_KEYS = ['all', 'open', 'pending', 'sediment']

    // ── 文案 ────────────────────────────────────────────────────────────────
    const ZH = {
      'region': '诊断状态条',
      'scope.bound': '本会话',
      'scope.recent': '最近一单',
      'scope.pinned': '已固定',
      'picker.title': '跟踪哪一单',
      'picker.search': '搜索标题或单号',
      'picker.empty': '没有匹配的诊断。',
      'picker.follow': '跟随会话（自动）',
      'picker.open': '打开诊断总览',
      'action.pin': '固定到状态条',
      'action.unpin': '取消固定',
      'hint.pinned': '状态条已固定到这一单。',
      'hint.unpinned': '状态条已恢复跟随本会话。',
      'title.empty': '诊断状态条',
      'title.error': '诊断状态条暂不可用',
      'action.start': '开始诊断',
      'action.resume': '续接诊断',
      'action.material': '贴材料继续',
      'action.sediment': '沉淀为 case',
      'action.feedback': '回报结果',
      'action.promote': '升格草稿',
      'action.retry': '重试',
      'action.refresh': '刷新',
      'action.expand': '展开状态条',
      'action.collapse': '收起状态条',
      'action.more': '更多操作',
      'action.ledger': '诊断总览',
      'action.copySummary': '复制结论摘要',
      'action.copyResume': '复制续接指令',
      'action.copySediment': '复制沉淀指令',
      'action.copyPromote': '复制升格指令',
      'action.copyFeedback': '复制回报指令',
      'action.openSession': '切到该诊断的会话',
      'action.closeMenu': '关闭菜单',
      'waiting': '在等',
      'waitingOn.user_material': '等现场材料',
      'waitingOn.user_feedback': '等现场回报',
      'waitingOn.sediment': '等沉淀',
      'waitingOn.upstream': '等上游',
      'waitingOn.ended': '已收尾',
      'steps': '第 {n}/{m} 步',
      'stepsShort': '{n}/{m}',
      'chip.miss': '知识库未覆盖',
      'chip.excluded': '已排除 {n} 条',
      'chip.hit': '命中 {id}',
      'chip.sediment': '可沉淀',
      'chip.feedback': '待回报',
      'chip.promote': '草稿待升格',
      'chip.review': '可复核',
      'chip.upstream': '等上游',
      'section.summary': '问题背景',
      'section.waiting': '现在在等',
      'section.track': '轨迹',
      'section.sediment': '知识沉淀',
      'label.steps': '进度',
      'label.events': '事件',
      'label.excluded': '已排除',
      'label.evidence': '证据',
      'label.missing': '缺口',
      'label.updated': '最近更新',
      'label.sediment': '沉淀',
      'label.feedback': '反馈',
      'label.severity': '严重级',
      'label.report': '人读报告',
      'label.hasReport': '有',
      'label.noReport': '无',
      'label.none': '未记录',
      'label.queue': '全库',
      'label.hit': '命中 case',
      'queue.open': '{n} 单进行中',
      'queue.pending': '{n} 单待回报',
      'queue.sediment': '{n} 单可沉淀',
      'empty.body': '本会话还没有诊断轨迹。跑一次 /skill:diagnose 后，这一行会显示本会话的第几步、在等什么、下一步做什么。',
      'empty.collapsed': '本会话还没有诊断轨迹',
      'empty.meaning': '数据来自检出里的 traces/；状态判据在 scripts/trace_state.py。',
      'error.reopen': '数据来自 traces/；判据在 scripts/trace_state.py。',
      'hint.draft': '已填入输入框，按 Enter 发送。',
      'hint.copied': '已复制。',
      'hint.copyFailed': '这个界面不允许写剪贴板，请手动选择文本。',
      'hint.noInput': '这个界面没有提供写入输入框的接口，指令已复制到剪贴板。',
      'hint.failed': '填入输入框失败：{message}',
      'hint.copiedFallback': '这个界面没有提供写入输入框的接口，指令已复制。',
      'menu.title': '操作',
      'group.instruct': '生成指令（填入输入框）',
      'group.settle': '回报与沉淀',
      'group.state': '改状态',
      'group.copy': '复制',
      'group.nav': '导航',
      'action.upstream': '查 case 上游状态',
      'action.reportDoc': '产出 / 修订定位报告',
      'action.handoff': '导出交接包',
      'action.review': '复核回报',
      'action.feedbackForm': '回报结果…',
      'action.sedimentState': '沉淀状态…',
      'form.result': '结果',
      'form.source': '来源',
      'form.note': '备注（现场看到什么）',
      'form.noteHint': '例如：按报告改完后继续跑 2 小时没再崩',
      'form.noNote': '未填',
      'form.preview': '将填入输入框',
      'form.fill': '填入输入框',
      'source.field': '现场验证',
      'source.vendor': '厂商答复',
      'section.overview': '概览',
      'section.background': '问题背景',

      'report.from_report': '按报告的修复解决',
      'report.other_way': '换别的方法解决',
      'report.partial': '部分解决',
      'report.none': '没解决',
      'close.resolved': '已定位（根因明确）',
      'close.escalated': '转交他人跟进',
      'close.archived': '不再跟进',
      'reopen': '重新打开',
      'sediment.none': '未沉淀',
      'sediment.submitted': '已交草稿',
      'sediment.knowledge': '已升格',
      'sediment.archived': '已归档',
      'ending.not_reproducible': '问题未复现',
      'ending.duplicate': '与已有单重复',
      'ending.no_diagnosis': '未走诊断',
      'ending.withdrawn': '主动撤回',
      'form.severity': '严重级',
      'form.fixEmitted': '是否给出了可执行的修复',
      'form.handedTo': '转交给',
      'form.handedToHint': '名字 · 团队，或厂商 / 技术支持 / issue 号',
      'form.duplicateOf': '与哪一单重复',
      'form.duplicateOfHint': 'case 编号或 issue 链接（case: 前缀）',
      'form.ending': '收尾方式',
      'form.state': '沉淀状态',
      'form.caseId': 'case 编号（可选）',
      'form.caseIdHint': '例如 VLLM-ASC-11312；升格后填',
      'form.yes': '是',
      'form.no': '否',
      'form.submit': '提交',
      'form.cancel': '取消',
      'form.busy': '正在写…',
      'write.disabled': '当前会话没有写权限',
      'write.done': '已记录：{from} → {to}',
      'write.doneSimple': '已记录',
      'write.doneSediment': '沉淀状态改为：{state}',
      'write.stateChanged': '这单在别处被改过，已刷新，请重试。',
      'write.failed': '写入失败：{message}',
      'write.requirements': '（缺：{fields}）',
      'palette.title': '诊断总览',
      'palette.filter.all': '全部',
      'palette.filter.open': '进行中',
      'palette.filter.pending': '待回报',
      'palette.filter.sediment': '可沉淀',
      'palette.empty': '没有符合条件的诊断。',
      'palette.loading': '正在读 traces/…',
      'palette.unavailable': '读不到 traces/：{message}',
      'palette.count': '共 {n} 单',
      'palette.hint': '↑↓ 选择 · Enter 主操作 · Esc 关闭',
      'palette.close': '关闭诊断总览',
      'tool.title': '诊断总览',
      'tool.pending': '{n} 单待回报',
      'none': '未记录',
    }
    const EN = {
      'region': 'Diagnosis status bar',
      'scope.bound': 'this session',
      'scope.recent': 'latest',
      'scope.pinned': 'pinned',
      'picker.title': 'Track which diagnosis',
      'picker.search': 'Search title or id',
      'picker.empty': 'No matching diagnosis.',
      'picker.follow': 'Follow the session (auto)',
      'picker.open': 'Open diagnosis overview',
      'action.pin': 'Pin to the status bar',
      'action.unpin': 'Unpin',
      'hint.pinned': 'The status bar is pinned to this diagnosis.',
      'hint.unpinned': 'The status bar follows the session again.',
      'title.empty': 'Diagnosis status bar',
      'title.error': 'Diagnosis status bar unavailable',
      'action.start': 'Start diagnosis',
      'action.resume': 'Resume',
      'action.material': 'Continue with logs',
      'action.sediment': 'Draft a case',
      'action.feedback': 'Report outcome',
      'action.promote': 'Promote draft',
      'action.retry': 'Retry',
      'action.refresh': 'Refresh',
      'action.expand': 'Expand status bar',
      'action.collapse': 'Collapse status bar',
      'action.more': 'More actions',
      'action.ledger': 'Diagnosis overview',
      'action.copySummary': 'Copy summary',
      'action.copyResume': 'Copy resume command',
      'action.copySediment': 'Copy sediment command',
      'action.copyPromote': 'Copy promote command',
      'action.copyFeedback': 'Copy outcome command',
      'action.openSession': 'Open the diagnosis session',
      'action.closeMenu': 'Close menu',
      'waiting': 'Waiting for',
      'waitingOn.user_material': 'field material',
      'waitingOn.user_feedback': 'field outcome',
      'waitingOn.sediment': 'sedimentation',
      'waitingOn.upstream': 'upstream',
      'waitingOn.ended': 'closed',
      'steps': 'Step {n}/{m}',
      'stepsShort': '{n}/{m}',
      'chip.miss': 'not in knowledge base',
      'chip.excluded': '{n} excluded',
      'chip.hit': 'Hit {id}',
      'chip.sediment': 'can sediment',
      'chip.feedback': 'outcome pending',
      'chip.promote': 'draft to promote',
      'chip.review': 'to review',
      'chip.upstream': 'waiting upstream',
      'section.summary': 'Background',
      'section.waiting': 'Waiting for',
      'section.track': 'Trace',
      'section.sediment': 'Knowledge',
      'label.steps': 'progress',
      'label.events': 'events',
      'label.excluded': 'excluded',
      'label.evidence': 'evidence',
      'label.missing': 'gap',
      'label.updated': 'updated',
      'label.sediment': 'sediment',
      'label.feedback': 'outcome',
      'label.severity': 'severity',
      'label.report': 'report',
      'label.hasReport': 'yes',
      'label.noReport': 'no',
      'label.none': 'not recorded',
      'label.queue': 'workspace',
      'label.hit': 'hit case',
      'queue.open': '{n} open',
      'queue.pending': '{n} pending outcome',
      'queue.sediment': '{n} to sediment',
      'empty.body': 'No diagnosis trace in this session yet. Run /skill:diagnose and this bar shows the step, what it waits for, and what comes next.',
      'empty.collapsed': 'No diagnosis trace in this session yet',
      'empty.meaning': 'Data comes from traces/; status rules live in scripts/trace_state.py.',
      'error.reopen': 'Data comes from traces/; rules live in scripts/trace_state.py.',
      'hint.draft': 'Inserted into the composer — press Enter to send.',
      'hint.copied': 'Copied.',
      'hint.copyFailed': 'Clipboard is unavailable here; select the text manually.',
      'hint.noInput': 'This page exposes no composer input; the instruction was copied instead.',
      'hint.failed': 'Could not write the composer: {message}',
      'hint.copiedFallback': 'This page exposes no composer input; the instruction was copied.',
      'menu.title': 'Actions',
      'group.instruct': 'Generate a command (fills the composer)',
      'group.settle': 'Outcome and sedimentation',
      'group.state': 'State',
      'group.copy': 'Copy',
      'group.nav': 'Navigate',
      'action.upstream': 'Check case upstream status',
      'action.reportDoc': 'Write / revise the report',
      'action.handoff': 'Export a handoff package',
      'action.review': 'Review the report',
      'action.feedbackForm': 'Report outcome…',
      'action.sedimentState': 'Sediment state…',
      'form.result': 'Result',
      'form.source': 'Source',
      'form.note': 'Note (what was observed)',
      'form.noteHint': 'e.g. ran 2 more hours after applying the fix without a crash',
      'form.noNote': 'not filled',
      'form.preview': 'Will fill into the composer',
      'form.fill': 'Fill the composer',
      'source.field': 'Field verification',
      'source.vendor': 'Vendor reply',
      'section.overview': 'Overview',
      'section.background': 'Background',

      'report.from_report': 'Fixed by the report',
      'report.other_way': 'Fixed another way',
      'report.partial': 'Partially fixed',
      'report.none': 'Not fixed',
      'close.resolved': 'Resolved (root cause known)',
      'close.escalated': 'Hand off',
      'close.archived': 'Stop following',
      'reopen': 'Reopen',
      'sediment.none': 'Not sedimented',
      'sediment.submitted': 'Draft submitted',
      'sediment.knowledge': 'Promoted',
      'sediment.archived': 'Archived',
      'ending.not_reproducible': 'Not reproducible',
      'ending.duplicate': 'Duplicate',
      'ending.no_diagnosis': 'No diagnosis',
      'ending.withdrawn': 'Withdrawn',
      'form.severity': 'Severity',
      'form.fixEmitted': 'Was an actionable fix given',
      'form.handedTo': 'Handed to',
      'form.handedToHint': 'Name · team, or vendor / support / issue',
      'form.duplicateOf': 'Duplicate of',
      'form.duplicateOfHint': 'Case id or issue link (case: prefix)',
      'form.ending': 'Ending',
      'form.state': 'Sediment state',
      'form.caseId': 'Case id (optional)',
      'form.caseIdHint': 'e.g. VLLM-ASC-11312, after promotion',
      'form.yes': 'Yes',
      'form.no': 'No',
      'form.submit': 'Submit',
      'form.cancel': 'Cancel',
      'form.busy': 'Writing…',
      'write.disabled': 'This session has no write access',
      'write.done': 'Recorded: {from} → {to}',
      'write.doneSimple': 'Recorded',
      'write.doneSediment': 'Sediment state set to {state}',
      'write.stateChanged': 'The trace changed elsewhere; refreshed, try again.',
      'write.failed': 'Write failed: {message}',
      'write.requirements': ' (missing: {fields})',
      'palette.title': 'Diagnosis overview',
      'palette.filter.all': 'All',
      'palette.filter.open': 'Open',
      'palette.filter.pending': 'Outcome pending',
      'palette.filter.sediment': 'To sediment',
      'palette.empty': 'No diagnosis matches.',
      'palette.loading': 'Reading traces/…',
      'palette.unavailable': 'Cannot read traces/: {message}',
      'palette.count': '{n} total',
      'palette.hint': '↑↓ select · Enter primary · Esc close',
      'palette.close': 'Close the diagnosis overview',
      'tool.title': 'Diagnosis overview',
      'tool.pending': '{n} pending outcomes',
      'none': 'not recorded',
    }
    const DICTS = { zh: ZH, en: EN }
    let translate = (key, params) => formatText(ZH[key] !== undefined ? ZH[key] : key, params)

    function formatText(text, params) {
      if (!params) return text
      return String(text).replace(/\{(\w+)\}/g, (match, name) => (
        Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
      ))
    }

    const tr = (key, params) => translate(key, params)

    // ── 样式 ────────────────────────────────────────────────────────────────
    const CSS = [
      '.scp-root,.scp-pal{--scp-surface:#ffffff;--scp-surface-2:#f6f7f9;--scp-surface-3:#eceff4;--scp-border:#e5e8ee;--scp-border-strong:#d7dce5;--scp-text:#1a1f29;--scp-muted:#647082;--scp-faint:#98a2b3;--scp-accent:#3b63e0;--scp-accent-soft:#eef2fe;--scp-accent-line:#c9d5fb;--scp-on-accent:#ffffff;--scp-ok:#0e8a5f;--scp-ok-soft:#e7f6ef;--scp-warn:#b25e09;--scp-warn-soft:#fdf2e4;--scp-bad:#c42b1c;--scp-bad-soft:#fdecea;--scp-idle:#98a2b3;--scp-shadow:0 1px 2px rgba(16,24,40,.04),0 12px 30px -20px rgba(16,24,40,.22);}',
      'body[data-ds-dark-theme] .scp-root,body[data-ds-dark-theme] .scp-pal,[data-theme="dark"] .scp-root,[data-theme="dark"] .scp-pal{--scp-surface:#1c1f26;--scp-surface-2:#242832;--scp-surface-3:#2e333e;--scp-border:#2e3441;--scp-border-strong:#3d4553;--scp-text:#eaedf3;--scp-muted:#a6afbd;--scp-faint:#7a8494;--scp-accent:#8aa5ff;--scp-accent-soft:rgba(138,165,255,.14);--scp-accent-line:rgba(138,165,255,.3);--scp-on-accent:#10131a;--scp-ok:#45d08a;--scp-ok-soft:rgba(69,208,138,.12);--scp-warn:#f5b34a;--scp-warn-soft:rgba(245,179,74,.12);--scp-bad:#f0796e;--scp-bad-soft:rgba(240,121,110,.12);--scp-idle:#6f7886;--scp-shadow:0 1px 2px rgba(0,0,0,.4),0 16px 36px -20px rgba(0,0,0,.7);}',
      '.scp-root{position:relative;container-type:inline-size;width:calc(100% - 2 * var(--dsh-composer-side-clearance, 0px));max-width:var(--dsh-composer-card-max-width, 100%);margin:0 auto;box-sizing:border-box;font-family:inherit;color:var(--scp-text);--scp-tone:var(--scp-accent);}',
      '.scp-root *,.scp-pal *{box-sizing:border-box;}',
      '.scp-handle-wrap{display:flex;justify-content:center;width:100%;}',
      '.scp-handle{display:inline-flex;align-items:center;gap:7px;max-width:min(72%,560px);height:22px;padding:0 10px;border-radius:999px;border:1px solid var(--scp-border);background:color-mix(in srgb,var(--scp-surface) 62%,transparent);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);color:var(--scp-muted);font:inherit;font-size:11px;line-height:1;cursor:pointer;transition:background-color 160ms ease,color 160ms ease,border-color 160ms ease,opacity 360ms ease;}',
      '.scp-handle[data-idle="true"]{opacity:.34;}',
      '.scp-handle[data-idle="true"]:hover,.scp-handle[data-idle="true"]:focus-visible{opacity:1;}',
      '.scp-handle:hover{background:var(--scp-surface-2);color:var(--scp-text);border-color:var(--scp-border-strong);}',
      '.scp-handle .scp-ring{width:7px;height:7px;}',
      '.scp-handle-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;color:var(--scp-text);}',
      '.scp-handle-meta{flex:none;font-variant-numeric:tabular-nums;color:var(--scp-muted);}',
      '.scp-handle-pending{flex:none;color:var(--scp-warn);font-weight:600;}',
      '.scp-handle .scp-chevron{opacity:.65;}',
      '.scp-surface{display:flex;flex-direction:column;gap:6px;padding:6px 10px;border:1px solid var(--scp-border);border-radius:12px;background:color-mix(in srgb, var(--scp-surface) 76%, transparent);transition:border-color 180ms ease,background-color 180ms ease;}',
      '.scp-root[data-mode="bound"] .scp-surface,.scp-root[data-mode="recent"] .scp-surface{padding:7px 10px;}',
      '.scp-root[data-live="true"] .scp-surface{border-color:color-mix(in srgb, var(--scp-tone) 22%, var(--scp-border));}',
      '.scp-head{display:flex;align-items:center;gap:8px;min-width:0;}',
      '.scp-ring{flex:none;width:8px;height:8px;border-radius:50%;background:var(--scp-tone);}',
      '.scp-root[data-live="true"] .scp-ring{animation:scp-pulse 2.8s ease-out infinite;}',
      '@keyframes scp-pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb, var(--scp-tone) 30%, transparent)}70%{box-shadow:0 0 0 6px transparent}100%{box-shadow:0 0 0 0 transparent}}',
      '.scp-scope{flex:none;display:inline-flex;align-items:center;gap:2px;padding:1px 5px;border:none;border-radius:6px;background:transparent;font:inherit;font-size:10.5px;line-height:1.6;color:var(--scp-muted);cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-scope:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-scope svg{opacity:.7;}',
      '.scp-case{flex:1 1 auto;min-width:0;padding:0;border:none;background:transparent;font:inherit;font-size:13px;font-weight:600;line-height:1.55;letter-spacing:.005em;text-align:left;color:var(--scp-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;border-radius:6px;}',
      '.scp-case:hover{color:var(--scp-accent);}',
      '.scp-status-text{flex:none;font-size:11px;line-height:1.6;color:var(--scp-muted);}',
      '.scp-season{flex:none;font-size:11px;color:var(--scp-faint);}',
      '.scp-spacer{flex:1 1 auto;min-width:6px;}',
      '.scp-step{flex:none;font-size:10.5px;font-variant-numeric:tabular-nums;color:var(--scp-muted);}',
      '.scp-foot{display:flex;align-items:center;gap:9px;min-width:0;padding:0 2px;}',
      '.scp-track{flex:none;display:inline-flex;align-items:center;gap:3px;}',
      '.scp-tick{width:11px;height:3px;border-radius:2px;background:var(--scp-surface-3);transition:background-color 180ms ease;}',
      '.scp-tick[data-state="done"]{background:color-mix(in srgb, var(--scp-tone) 32%, transparent);}',
      '.scp-tick[data-state="now"]{background:var(--scp-tone);}',
      '.scp-now{font-size:10.5px;line-height:1.6;color:var(--scp-faint);margin-left:3px;font-variant-numeric:tabular-nums;}',
      '.scp-meta{flex:none;font-size:11px;line-height:1.6;color:var(--scp-muted);white-space:nowrap;}',
      '.scp-wait{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11.5px;line-height:1.6;color:var(--scp-muted);}',
      '.scp-wait b{font-weight:500;color:var(--scp-text);}',
      '.scp-chips{flex:none;display:inline-flex;align-items:center;gap:5px;}',
      '.scp-chip{flex:none;font-size:10.5px;line-height:1.7;padding:0 6px;border-radius:5px;white-space:nowrap;color:var(--scp-muted);background:var(--scp-surface-2);}',
      '.scp-chip[data-tone="brand"]{color:var(--scp-accent);background:var(--scp-accent-soft);}',
      '.scp-chip[data-tone="warn"]{color:var(--scp-warn);background:var(--scp-warn-soft);}',
      '.scp-chip[data-tone="success"]{color:var(--scp-ok);background:var(--scp-ok-soft);}',
      '.scp-chip[data-tone="error"]{color:var(--scp-bad);background:var(--scp-bad-soft);}',
      '.scp-badge{flex:none;font-size:10.5px;line-height:1.6;font-weight:600;padding:1px 7px;border-radius:5px;color:var(--scp-tone);background:color-mix(in srgb, var(--scp-tone) 10%, transparent);}',
      '.scp-btn{font:inherit;font-size:12.5px;line-height:1.7;padding:3px 10px;border-radius:8px;border:1px solid var(--scp-border);background:var(--scp-surface);color:var(--scp-text);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}',
      '.scp-btn:hover{background:var(--scp-surface-2);border-color:var(--scp-border-strong);}',
      '.scp-btn:disabled{opacity:.45;cursor:not-allowed;}',
      '.scp-btn--primary{border:none;border-radius:999px;padding:5px 14px;background:var(--scp-accent);color:var(--scp-on-accent);font-weight:600;}',
      '.scp-btn--primary:hover{background:color-mix(in srgb, var(--scp-accent) 88%, var(--scp-text));}',
      '.scp-btn--quiet{border:none;background:transparent;border-radius:999px;padding:3px 9px;color:var(--scp-accent);font-weight:600;}',
      '.scp-btn--quiet:hover{background:var(--scp-accent-soft);color:var(--scp-accent);}',
      '.scp-btn--ghost{background:transparent;border-color:transparent;}',
      '.scp-btn--ghost:hover{background:var(--scp-surface-2);}',
      '.scp-icon{flex:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;padding:0;border:none;border-radius:7px;background:transparent;color:var(--scp-muted);cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-icon:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-icon:focus-visible,.scp-btn:focus-visible,.scp-tool-btn:focus-visible,.scp-case:focus-visible,.scp-scope:focus-visible,.scp-pal-row:focus-visible,.scp-filter-item:focus-visible,.scp-picker-row:focus-visible{outline:2px solid var(--scp-accent);outline-offset:2px;}',
      '.scp-icon svg{display:block;}',
      '.scp-chevron{transition:transform 180ms ease;}',
      '.scp-chevron[data-open="true"]{transform:rotate(180deg);}',
      '.scp-empty-note{font-size:11px;line-height:1.6;color:var(--scp-faint);}',
      '.scp-hint{padding:2px 4px 0;font-size:11px;line-height:1.6;color:var(--scp-muted);}',
      '.scp-picker{position:absolute;left:8px;bottom:calc(100% + 8px);z-index:45;width:340px;max-height:min(52vh,380px);display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--scp-border-strong);border-radius:14px;background:var(--scp-surface);box-shadow:var(--scp-shadow);animation:scp-pop 150ms ease-out;}',
      '.scp-picker-head{padding:9px 10px;border-bottom:1px solid var(--scp-border);}',
      '.scp-picker-title{font-size:11.5px;line-height:1.7;color:var(--scp-muted);padding:0 2px 6px;}',
      '.scp-picker-search{width:100%;font:inherit;font-size:12.5px;line-height:1.6;padding:5px 9px;border-radius:8px;border:1px solid var(--scp-border);background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-picker-search:focus{outline:2px solid var(--scp-accent-line);outline-offset:0;}',
      '.scp-picker-list{overflow:auto;padding:6px;}',
      '.scp-picker-row{display:flex;align-items:center;gap:8px;width:100%;padding:7px 8px;border:none;border-radius:8px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 100ms ease;}',
      '.scp-picker-row:hover{background:var(--scp-surface-2);}',
      '.scp-picker-row[data-on="true"]{background:var(--scp-accent-soft);}',
      '.scp-picker-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:1px;}',
      '.scp-picker-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;font-weight:550;line-height:1.5;}',
      '.scp-picker-meta{font-size:11px;line-height:1.5;color:var(--scp-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.scp-picker-foot{display:flex;align-items:center;gap:8px;padding:8px 10px;border-top:1px solid var(--scp-border);}',
      '.scp-picker-empty{padding:18px 10px;text-align:center;font-size:11.5px;color:var(--scp-faint);}',
      '.scp-menu{position:absolute;right:8px;bottom:calc(100% + 8px);z-index:50;width:302px;max-height:min(64vh,540px);overflow:auto;padding:6px;border:1px solid var(--scp-border-strong);border-radius:14px;background:var(--scp-surface);box-shadow:var(--scp-shadow);animation:scp-pop 150ms ease-out;}',
      '@keyframes scp-pop{from{opacity:0;transform:translateY(6px) scale(.99)}to{opacity:1;transform:none}}',
      '.scp-menu-head{display:flex;align-items:center;justify-content:space-between;padding:2px 6px 6px;}',
      '.scp-menu-title{font-size:11px;line-height:1.7;color:var(--scp-muted);}',
      '.scp-menu-group{margin:4px 0 2px;padding:7px 7px 0;font-size:11px;line-height:1.6;letter-spacing:.05em;color:var(--scp-faint);border-top:1px solid var(--scp-border);}',
      '.scp-menu-group:first-of-type{border-top:none;}',
      '.scp-menu-item{display:flex;width:100%;align-items:center;gap:8px;padding:7px 9px;border:none;border-radius:7px;background:transparent;color:var(--scp-text);font:inherit;font-size:12.5px;line-height:1.6;text-align:left;cursor:pointer;transition:background-color 100ms ease;}',
      '.scp-menu-item:hover{background:var(--scp-surface-2);}',
      '.scp-menu-item:disabled{opacity:.45;cursor:not-allowed;}',
      '.scp-form{display:flex;flex-direction:column;gap:9px;padding:4px 8px 8px;}',
      '.scp-field{display:flex;flex-direction:column;gap:4px;}',
      '.scp-field-label{font-size:11.5px;line-height:1.6;color:var(--scp-muted);}',
      '.scp-input,.scp-select,.scp-textarea{font:inherit;font-size:12.5px;line-height:1.6;padding:5px 9px;border-radius:8px;border:1px solid var(--scp-border);background:var(--scp-surface-2);color:var(--scp-text);width:100%;}',
      '.scp-input:focus,.scp-select:focus,.scp-textarea:focus{outline:2px solid var(--scp-accent-line);outline-offset:0;}',
      '.scp-textarea{resize:vertical;min-height:54px;}',
      '.scp-form-actions{display:flex;justify-content:flex-end;gap:6px;margin-top:4px;}',
      '.scp-form-error{font-size:11.5px;line-height:1.6;color:var(--scp-bad);}',
      '.scp-form-hint{font-size:11px;line-height:1.6;color:var(--scp-muted);}',
      '.scp-preview{display:flex;flex-direction:column;gap:4px;padding:9px 10px;border-radius:9px;background:var(--scp-surface-2);border:1px solid var(--scp-border);}',
      '.scp-preview-label{font-size:10.5px;letter-spacing:.04em;color:var(--scp-muted);}',
      '.scp-preview-text{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;line-height:1.7;color:var(--scp-text);white-space:pre-wrap;overflow-wrap:anywhere;max-height:132px;overflow:auto;}',
      '.scp-section-label{margin-top:2px;font-size:11px;line-height:1.6;letter-spacing:.04em;color:var(--scp-muted);}',
      '.scp-pal-list,.scp-pal-side,.scp-menu,.scp-picker-list{scrollbar-width:thin;scrollbar-color:var(--scp-border-strong) transparent;}',
      '.scp-pal-list::-webkit-scrollbar,.scp-pal-side::-webkit-scrollbar,.scp-menu::-webkit-scrollbar,.scp-picker-list::-webkit-scrollbar{width:10px;height:10px;}',
      '.scp-pal-list::-webkit-scrollbar-thumb,.scp-pal-side::-webkit-scrollbar-thumb,.scp-menu::-webkit-scrollbar-thumb,.scp-picker-list::-webkit-scrollbar-thumb{background:var(--scp-border-strong);border-radius:999px;border:3px solid transparent;background-clip:content-box;}',
      '.scp-pal-list::-webkit-scrollbar-track,.scp-pal-side::-webkit-scrollbar-track,.scp-menu::-webkit-scrollbar-track,.scp-picker-list::-webkit-scrollbar-track{background:transparent;}',
      '.scp-tool-btn{position:relative;display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;padding:0;border:none;border-radius:8px;background:transparent;color:var(--scp-muted);cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-tool-btn:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-tool-btn[data-tone="brand"]{color:var(--scp-accent);}',
      '.scp-tool-btn[data-tone="success"]{color:var(--scp-ok);}',
      '.scp-tool-btn[data-tone="warn"]{color:var(--scp-warn);}',
      '.scp-tool-btn[data-tone="error"]{color:var(--scp-bad);}',
      '.scp-tool-badge{position:absolute;top:-2px;right:-3px;min-width:14px;height:14px;padding:0 4px;border-radius:999px;background:var(--scp-warn);color:#ffffff;font-size:9.5px;line-height:14px;text-align:center;font-weight:600;}',
      '.scp-pal-backdrop{position:fixed;inset:0;z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:9vh 18px 18px;background:rgba(20,26,38,.26);-webkit-backdrop-filter:blur(8px) saturate(1.04);backdrop-filter:blur(8px) saturate(1.04);}',
      'body[data-ds-dark-theme] .scp-pal-backdrop,[data-theme="dark"] .scp-pal-backdrop{background:rgba(0,0,0,.5);}',
      '.scp-pal{position:relative;display:flex;flex-direction:column;width:min(900px,94vw);max-height:76vh;overflow:hidden;border:1px solid var(--scp-border-strong);border-radius:20px;background:var(--scp-surface);color:var(--scp-text);box-shadow:var(--scp-shadow);outline:none;animation:scp-pop 190ms cubic-bezier(.2,.9,.3,1);}',
      '.scp-pal-top{display:flex;align-items:center;gap:14px;padding:16px 20px;border-bottom:1px solid var(--scp-border);}',
      '.scp-pal-heading{display:flex;flex-direction:column;gap:2px;flex:1 1 auto;min-width:0;}',
      '.scp-pal-title{font-size:15px;font-weight:650;line-height:1.4;letter-spacing:.01em;}',
      '.scp-pal-sub{font-size:11.5px;line-height:1.5;color:var(--scp-muted);}',
      '.scp-filter{flex:none;display:flex;align-items:center;gap:2px;padding:3px;border-radius:999px;background:var(--scp-surface-2);}',
      '.scp-filter-item{border:none;background:transparent;font:inherit;font-size:12px;line-height:1.7;padding:4px 12px;border-radius:999px;color:var(--scp-muted);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,color 120ms ease,box-shadow 120ms ease;}',
      '.scp-filter-item:hover{color:var(--scp-text);}',
      '.scp-filter-item[data-on="true"]{background:var(--scp-surface);color:var(--scp-text);font-weight:600;box-shadow:0 1px 2px rgba(16,24,40,.1);}',
      '.scp-pal-main{display:flex;min-height:0;flex:1 1 auto;}',
      '.scp-pal-list{flex:0 0 44%;max-width:400px;min-width:280px;overflow:auto;padding:12px;border-right:1px solid var(--scp-border);}',
      '.scp-pal-row{display:flex;align-items:center;gap:11px;width:100%;padding:11px 12px;border:none;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 120ms ease;}',
      '.scp-pal-row:hover{background:var(--scp-surface-2);}',
      '.scp-pal-row[data-on="true"]{background:var(--scp-accent-soft);}',
      '.scp-pal-row-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:3px;}',
      '.scp-pal-row-line{display:flex;align-items:baseline;gap:8px;min-width:0;}',
      '.scp-pal-row-meta-main{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
      '.scp-pal-row-time{flex:none;font-variant-numeric:tabular-nums;color:var(--scp-faint);}',
      '.scp-menu-note{margin-left:auto;max-width:52%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10.5px;line-height:1.6;color:var(--scp-warn);}',
      '.scp-pal-row-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:550;line-height:1.5;}',
      '.scp-pal-row-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;font-size:11.5px;line-height:1.5;color:var(--scp-muted);white-space:nowrap;}',
      '.scp-pal-row-step{flex:none;font-size:11px;color:var(--scp-faint);font-variant-numeric:tabular-nums;}',
      '.scp-pal-side{flex:1 1 auto;min-width:0;overflow:auto;padding:22px 24px;display:flex;flex-direction:column;gap:16px;background:var(--scp-surface-2);}',
      '.scp-hero{display:flex;flex-direction:column;gap:7px;}',
      '.scp-hero-title{font-size:16px;font-weight:650;line-height:1.55;letter-spacing:.01em;overflow-wrap:anywhere;}',
      '.scp-hero-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px;}',
      '.scp-callout{display:flex;flex-direction:column;gap:3px;padding:11px 13px;border-radius:10px;background:var(--scp-accent-soft);border:1px solid var(--scp-accent-line);}',
      '.scp-callout-label{font-size:11px;letter-spacing:.05em;color:var(--scp-muted);}',
      '.scp-callout-text{font-size:13px;line-height:1.75;color:var(--scp-text);overflow-wrap:anywhere;}',
      '.scp-grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px 22px;margin:0;padding:16px 18px;border-radius:12px;background:var(--scp-surface);border:1px solid var(--scp-border);}',
      '.scp-def{display:flex;flex-direction:column;gap:2px;min-width:0;}',
      '.scp-def dt{margin:0;font-size:11px;line-height:1.6;color:var(--scp-muted);}',
      '.scp-def dd{margin:0;font-size:12.5px;line-height:1.65;color:var(--scp-text);overflow-wrap:anywhere;}',
      '.scp-p{margin:0;font-size:12.5px;line-height:1.8;color:var(--scp-text);overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}',
      '.scp-code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10.5px;color:var(--scp-muted);overflow-wrap:anywhere;}',
      '.scp-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:auto;padding-top:4px;}',
      '.scp-pal-foot{display:flex;align-items:center;gap:12px;padding:10px 20px;border-top:1px solid var(--scp-border);font-size:11.5px;line-height:1.6;color:var(--scp-muted);background:var(--scp-surface);}',
      '.scp-kbd{display:inline-flex;align-items:center;justify-content:center;min-width:16px;height:16px;padding:0 4px;border-radius:5px;border:1px solid var(--scp-border);background:var(--scp-surface-2);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9.5px;color:var(--scp-muted);}',
      '.scp-version{font-size:10.5px;color:var(--scp-faint);font-variant-numeric:tabular-nums;}',
      '.scp-toast{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);max-width:min(80%,520px);padding:7px 14px;border-radius:999px;background:var(--scp-surface);border:1px solid var(--scp-border-strong);box-shadow:var(--scp-shadow);font-size:11.5px;line-height:1.6;color:var(--scp-text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;animation:scp-toast 170ms ease-out;}',
      '@keyframes scp-toast{from{opacity:0;transform:translate(-50%,6px)}to{opacity:1;transform:translate(-50%,0)}}',
      '.scp-pal-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;flex:1 1 auto;min-height:200px;padding:24px;color:var(--scp-muted);font-size:12px;line-height:1.7;text-align:center;}',
      '.scp-skel{height:12px;border-radius:6px;background:linear-gradient(90deg,var(--scp-surface-2),color-mix(in srgb, var(--scp-surface-2) 30%, transparent),var(--scp-surface-2));background-size:200% 100%;animation:scp-shimmer 1.5s ease-in-out infinite;}',
      '@keyframes scp-shimmer{from{background-position:120% 0}to{background-position:-80% 0}}',
      '.scp-root[data-tone="brand"]{--scp-tone:var(--scp-accent);}',
      '.scp-root[data-tone="success"]{--scp-tone:var(--scp-ok);}',
      '.scp-root[data-tone="warn"]{--scp-tone:var(--scp-warn);}',
      '.scp-root[data-tone="error"]{--scp-tone:var(--scp-bad);}',
      '.scp-root[data-tone="idle"]{--scp-tone:var(--scp-idle);}',
      '@container (max-width: 720px){.scp-meta,.scp-chips{display:none;}.scp-case{font-size:12px;}.scp-status-text{display:none;}}',
      '@media (max-width: 760px){.scp-pal-main{flex-direction:column;}.scp-pal-list{flex:0 0 auto;max-width:none;min-width:0;max-height:38vh;border-right:none;border-bottom:1px solid var(--scp-border);}.scp-pal-side{flex:1 1 auto;min-height:0;}.scp-grid2{grid-template-columns:1fr;}.scp-pal-top{flex-wrap:wrap;gap:10px;}.scp-filter{order:3;flex-basis:100%;justify-content:flex-start;overflow:auto;}}',
      '@media (max-width: 520px){.scp-pal-backdrop{padding:4vh 10px 10px;}.scp-pal{max-height:88vh;}.scp-picker{width:min(330px,calc(100vw - 32px));}}',
      '@media (prefers-reduced-motion: reduce){.scp-handle{transition:none;}.scp-handle[data-idle="true"]{opacity:1;}.scp-ring{animation:none;}.scp-btn,.scp-icon,.scp-tick,.scp-pal-row,.scp-chevron{transition:none;}.scp-pal,.scp-menu,.scp-toast,.scp-picker{animation:none;}.scp-skel{animation:none;}}',
    ].join('\n')

    // ── 兜底中文名（词表缺项时用，正常路径由 scripts/_trace_state.py 给）──────
    const CATEGORY_LABEL = { interrupt: '中断', precision: '精度', performance: '性能' }
    const STATUS_LABEL = {
      in_progress: '进行中', resolved: '已定位', escalated: '已转交他人', archived: '不再跟进', unknown: '状态未记录',
    }
    const SED_LABEL = { none: '未沉淀', submitted: '已提交待升格', knowledge: '已升格', archived: '已归档' }
    const OUTCOME_LABEL = { pending: '待回报', resolved: '生效', not_resolved: '未生效', partial: '部分生效' }
    const SEVERITY_LABEL = { benign: '不影响服务', 'service-affecting': '影响服务', 'data-loss-risk': '数据丢失风险' }
    const REPORT_RESULT_KEYS = ['from_report', 'other_way', 'partial', 'none']
    const SEDIMENT_STATE_KEYS = ['none', 'submitted', 'knowledge', 'archived']
    const ARCHIVED_ENDING_KEYS = ['not_reproducible', 'duplicate', 'no_diagnosis', 'withdrawn']
    const TONE_VAR = {
      brand: 'var(--dsw-alias-brand-primary)',
      success: 'var(--dsw-alias-state-success-primary)',
      warn: 'var(--dsw-alias-state-warn-primary)',
      error: 'var(--dsw-alias-state-error-primary)',
      idle: 'var(--dsw-alias-state-idle-primary)',
    }
    const REPORT_OUTCOME_TEXT = {
      from_report: { label: '按报告的修复解决', outcome: 'resolved' },
      other_way: { label: '换别的方法解决', outcome: 'resolved' },
      partial: { label: '部分解决', outcome: 'partial' },
      none: { label: '没解决', outcome: 'not_resolved' },
    }

    // ── 偏好（记住上次的展开状态与筛选）────────────────────────────────────
    const DEFAULT_PREFS = { dockCollapsed: true, paletteFilter: 'all', pins: {} }
    function loadPrefs() {
      try {
        const raw = window.localStorage.getItem(PREFS_KEY)
        if (!raw) return Object.assign({}, DEFAULT_PREFS)
        const parsed = JSON.parse(raw)
        const prefs = Object.assign({}, DEFAULT_PREFS)
        if (parsed && typeof parsed.dockCollapsed === 'boolean') prefs.dockCollapsed = parsed.dockCollapsed
        if (parsed && FILTER_KEYS.indexOf(parsed.paletteFilter) >= 0) prefs.paletteFilter = parsed.paletteFilter
        if (parsed && parsed.pins && typeof parsed.pins === 'object' && !Array.isArray(parsed.pins)) {
          const pins = {}
          for (const [key, value] of Object.entries(parsed.pins)) {
            if (typeof value === 'string' && value && Object.keys(pins).length < 40) pins[String(key)] = value
          }
          prefs.pins = pins
        }
        return prefs
      } catch {
        return Object.assign({}, DEFAULT_PREFS)
      }
    }
    function savePrefs(patch) {
      store.prefs = Object.assign({}, store.prefs, patch)
      try {
        window.localStorage.setItem(PREFS_KEY, JSON.stringify(store.prefs))
      } catch {
        // 隐私模式或沙箱禁写 localStorage 时，本次会话内仍然生效
      }
      emit()
    }

    // 手动选择跟踪哪一单：per-session 的 pin，存在 prefs.pins 里；空串 = 跟随会话。
    function pinsOf() {
      return (store.prefs && store.prefs.pins) || {}
    }

    function pinnedIdFor(sessionId) {
      return sessionId ? (pinsOf()[sessionId] || '') : ''
    }

    function setPin(sessionId, traceId) {
      if (!sessionId) return
      const pins = Object.assign({}, pinsOf())
      if (traceId) pins[sessionId] = traceId
      else delete pins[sessionId]
      savePrefs({ pins })
    }

    // ── 共享 store（各面同一份数据与开关）──────────────────────────────────
    const store = {
      prefs: loadPrefs(),
      sessionId: '',
      cwd: '',
      phase: 'idle',
      data: null,
      message: '',
      paletteOpen: false,
      paletteSelect: '',
      version: 0,
      listeners: new Set(),
      timer: null,
      onFocus: null,
      seq: 0,
    }

    function emit() {
      store.version += 1
      store.listeners.forEach((listener) => {
        try {
          listener()
        } catch {
          // 单个订阅者出错不拖累其余
        }
      })
    }

    function useStore() {
      const [, force] = React.useState(0)
      React.useEffect(() => {
        const listener = () => force((value) => value + 1)
        store.listeners.add(listener)
        return () => {
          store.listeners.delete(listener)
        }
      }, [])
      return store
    }

    let rpcCall = async () => {
      throw new Error('connection 服务不可用')
    }

    async function refresh(force) {
      if (!store.sessionId) return
      const seq = store.seq + 1
      store.seq = seq
      try {
        const value = await rpcCall('copilot-state', {
          sessionId: store.sessionId,
          cwd: store.cwd,
          refresh: force === true,
        })
        if (seq !== store.seq) return
        store.data = value
        store.phase = 'ready'
        store.message = ''
        emit()
      } catch (error) {
        if (seq !== store.seq) return
        if (store.phase === 'ready') return
        store.phase = 'error'
        store.message = String((error && error.message) || error)
        emit()
      }
    }

    function startTimer() {
      if (store.timer) return
      store.timer = setInterval(() => {
        if (document.visibilityState === 'visible') refresh(false)
      }, POLL_MS)
      store.onFocus = () => {
        if (document.visibilityState === 'visible') refresh(false)
      }
      window.addEventListener('focus', store.onFocus)
    }

    function ensureSession(sessionId, cwd) {
      if (!sessionId) return
      if (store.sessionId !== sessionId || store.cwd !== cwd) {
        store.sessionId = sessionId
        store.cwd = cwd
        store.phase = 'loading'
        store.data = null
        store.message = ''
        emit()
        refresh(true)
      } else if (!store.data && store.phase !== 'loading') {
        refresh(false)
      }
      startTimer()
    }

    function setPaletteOpen(open, selectId) {
      const next = !!open
      const nextSelect = selectId === undefined ? store.paletteSelect : String(selectId || '')
      if (store.paletteOpen === next && (selectId === undefined || store.paletteSelect === nextSelect)) return
      store.paletteOpen = next
      store.paletteSelect = nextSelect
      emit()
    }

    function copyToClipboard(text) {
      const value = String(text || '')
      try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
          return navigator.clipboard.writeText(value).then(() => true, () => fallbackCopy(value))
        }
      } catch {
        // 落到 execCommand 兜底
      }
      return Promise.resolve(fallbackCopy(value))
    }

    function fallbackCopy(value) {
      try {
        const area = document.createElement('textarea')
        area.value = value
        area.setAttribute('readonly', '')
        area.style.position = 'fixed'
        area.style.opacity = '0'
        document.body.appendChild(area)
        area.select()
        const ok = typeof document.execCommand === 'function' ? document.execCommand('copy') : false
        area.remove()
        return !!ok
      } catch {
        return false
      }
    }

    // ── 数据与文案映射 ─────────────────────────────────────────────────────
    function statusMeta(vocab, value) {
      const list = (vocab && vocab.statuses) || []
      for (const item of list) {
        if (item && item.value === value) return item
      }
      const key = value || 'unknown'
      return { value: key, label: STATUS_LABEL[key] || tr('none') }
    }

    function vocabLabel(list, value, fallback) {
      for (const item of list || []) {
        if (item && item.value === value) return item.label || value
      }
      return (fallback && fallback[value]) || tr('none')
    }

    function toneOf(row) {
      if (!row) return 'idle'
      if (row.severity === 'data-loss-risk') return 'error'
      if (row.status === 'resolved') return 'success'
      if (row.status === 'in_progress') return 'brand'
      return 'idle'
    }

    function isPending(row) {
      return !!(row && row.feedback && row.feedback.outcome === 'pending')
    }

    function isOpen(row) {
      return !!(row && row.derived && row.derived.open)
    }

    function pickCwd(props) {
      const session = props && props.session
      if (session && typeof session === 'object') {
        for (const key of ['cwd', 'workspacePath', 'projectPath', 'path', 'dir', 'root']) {
          if (typeof session[key] === 'string' && session[key]) return session[key]
        }
      }
      return ''
    }

    function useSessionCwd(props, sessionId) {
      const useSessions = props && props.useSessions
      const fromStore = typeof useSessions === 'function'
        ? useSessions((snapshot) => {
          const row = snapshot && snapshot.byId && sessionId ? snapshot.byId[sessionId] : null
          return row && typeof row.cwd === 'string' ? row.cwd : ''
        })
        : ''
      return fromStore || pickCwd(props)
    }

    function useSessionSync(props) {
      const sessionId = props && props.sessionId ? String(props.sessionId) : ''
      const cwd = useSessionCwd(props, sessionId)
      React.useEffect(() => {
        if (!sessionId) return undefined
        ensureSession(sessionId, cwd)
        return undefined
      }, [sessionId, cwd])
      return { sessionId, cwd }
    }

    function formatTime(iso) {
      if (!iso) return ''
      const date = new Date(iso)
      if (Number.isNaN(date.getTime())) return String(iso)
      const pad = (n) => String(n).padStart(2, '0')
      return pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes())
    }

    function stepsText(extra) {
      const current = Number(extra && extra.currentStep) || 0
      const max = Number(extra && extra.maxSteps) || 6
      return tr('steps', { n: current > 0 ? current : '—', m: max })
    }

    function stepsShort(extra) {
      const current = Number(extra && extra.currentStep) || 0
      const max = Number(extra && extra.maxSteps) || 6
      return tr('stepsShort', { n: current > 0 ? current : '—', m: max })
    }

    // 案例标题：状态条与总览显示给人看的一句话；单号只进 tooltip 与详情。
    // 取 summary 第一句（到第一个句读），截断交给 CSS——不手写省略号，也不把内部单号当标题。
    function caseTitle(row) {
      const summary = String((row && row.summary) || '').trim()
      if (summary) {
        const first = summary.split(/[。；;!?！？\n]/)[0].trim()
        if (first) return first
        return summary
      }
      return String((row && row.activeCase) || (row && row.sessionId) || '')
    }

    // 身份标签：这单到底是什么——命中的 case、知识库覆盖与否、欠什么、排除了多少。
    function identityChips(row) {
      const derived = (row && row.derived) || {}
      const extra = (row && row.extra) || {}
      const chips = []
      if (row && row.activeCase) chips.push({ key: 'hit', tone: 'brand', text: tr('chip.hit', { id: row.activeCase }) })
      else if (derived.caseKind === 'none') chips.push({ key: 'miss', tone: 'idle', text: tr('chip.miss') })
      if (isPending(row)) chips.push({ key: 'feedback', tone: 'warn', text: tr('chip.feedback') })
      if (derived.needSed) chips.push({ key: 'sediment', tone: 'brand', text: tr('chip.sediment') })
      if (derived.needPromote) chips.push({ key: 'promote', tone: 'warn', text: tr('chip.promote') })
      if (derived.needReview) chips.push({ key: 'review', tone: 'brand', text: tr('chip.review') })
      if (extra.excludedCases && extra.excludedCases.length) {
        chips.push({ key: 'excluded', tone: 'idle', text: tr('chip.excluded', { n: extra.excludedCases.length }) })
      }
      return chips
    }

    function chipsFor(row) {
      const derived = row.derived || {}
      const extra = row.extra || {}
      const chips = []
      if (isPending(row)) chips.push({ key: 'feedback', tone: 'warn', text: tr('chip.feedback') })
      if (derived.needSed) chips.push({ key: 'sediment', tone: 'brand', text: tr('chip.sediment') })
      if (derived.needPromote) chips.push({ key: 'promote', tone: 'warn', text: tr('chip.promote') })
      if (derived.needReview) chips.push({ key: 'review', tone: 'brand', text: tr('chip.review') })
      if (derived.upstreamPending) chips.push({ key: 'upstream', tone: 'idle', text: tr('chip.upstream') })
      if (row.activeCase) chips.push({ key: 'hit', tone: 'brand', text: tr('chip.hit', { id: row.activeCase }) })
      if (extra.excludedCases && extra.excludedCases.length) {
        chips.push({ key: 'excluded', tone: 'idle', text: tr('chip.excluded', { n: extra.excludedCases.length }) })
      }
      return chips.slice(0, 4)
    }

    function traceSource(row) {
      return 'traces/' + String(row && row.file ? row.file : '')
    }

    function resumeDraft(row) {
      return '用 /skill:resume-diagnosis 续接 ' + row.sessionId + '（' + traceSource(row) + '）'
    }

    function materialDraft(row) {
      return '继续诊断 ' + row.sessionId + '，材料如下：\n'
    }

    function sedimentDraft(row) {
      return '用 /skill:to-postmortem 沉淀 ' + row.sessionId + '（来源 ' + traceSource(row) + '），先给我提取提纲，我确认后再落草稿'
    }

    function promoteDraft(row) {
      return '把 ' + row.sessionId + ' 的 case 草稿按升格流程转正（来源 ' + traceSource(row) + '）——先告诉我它属于 new_pattern 还是 variant_of，还缺哪些字段'
    }

    // 生成指令：对象、动作、字段、来源一次写全，粘进输入框后 agent 不需要再猜。
    // 上游查证不在插件里发网络请求：先判环境（doctor 的 gh 能力），再让 agent 跑幂等的查证脚本。
    function upstreamDraft(row, info) {
      const ready = !!(info && info.ready === true)
      const gap = !ready && info && info.reason ? '；本机当前读数：' + info.reason : ''
      return [
        '查 ' + row.activeCase + ' 的上游状态并幂等落账（只查上游，不续接诊断）。',
        '0) 先跑 python3 scripts/doctor.py --json 确认 gh 与网络可用' + gap + '；不可用就停并报缺口，不要猜。',
        '1) 读该案例的 upstream 锚点（repo / issue / pr）与 validation_record.last_verified。',
        '2) 先跑 python3 scripts/verify_upstream_outcomes.py --case ' + row.activeCase
          + ' --dry-run --json 看结论；确认要写回后再 --apply（脚本按结局签名幂等，同一结局不重复累加）。',
        '3) 只写上游结论：是否被上游确认 / 否定 / 仍未验证；不表达现场是否解决。',
        '4) 输出每个锚点当前状态、是否已写入、下一步动作。',
        '来源 ' + traceSource(row) + '。',
      ].join('\n')
    }

    function reportDraft(row) {
      return '为 ' + row.sessionId + ' 产出（或修订）人读定位报告 traces/' + row.sessionId
        + '.report.md，结构按 skills/diagnose/references/report-template.md。结论只抄 trace 已记录的内容，'
        + '缺证据的标注为推测（来源 ' + traceSource(row) + '）'
    }

    function handoffDraft(row) {
      return '把 ' + row.sessionId + ' 导出成交接包（python3 scripts/export_trace.py 的交接模式），供另一台机器接手；'
        + '先核对 traces/evidence 是否齐全（来源 ' + traceSource(row) + '）'
    }

    function reviewDraft(row) {
      return '复核 ' + row.sessionId + ' 的回报：判定是报告需修订、case 错还是执行错，并把结论写成 review 事件'
        + '（verdict: report_revision / case_error / execution_error；来源 ' + traceSource(row) + '）'
    }

    // 回报结果：把「来源 / 结果 / 备注」写成完整指令，并点明要写哪一条事件、哪个字段。
    function feedbackInstruction(row, values) {
      const resultKey = values && values.result ? values.result : 'from_report'
      const meta = REPORT_OUTCOME_TEXT[resultKey] || REPORT_OUTCOME_TEXT.from_report
      const source = values && values.source === 'vendor' ? 'vendor' : 'field'
      const note = String((values && values.note) || '').trim() || tr('form.noNote')
      const lines = [
        '回报 ' + row.sessionId + ' 的 fix 结果。',
        tr('form.source') + '：' + tr('source.' + source),
        tr('form.result') + '：' + meta.label,
        tr('form.note') + '：' + note,
      ]
      if (source === 'vendor') {
        lines.push('请据此在 ' + traceSource(row) + ' 里补一条 report 事件（source: vendor，result: ' + resultKey
          + '，note 用上一行）；厂商答复不写 feedback.outcome。')
      } else {
        lines.push('请据此在 ' + traceSource(row) + ' 里补一条 report 事件（source: field，result: ' + resultKey
          + '，note 用上一行），并把 feedback.outcome 写成 ' + meta.outcome + '。')
      }
      return lines.join('\n')
    }

    function summaryText(row, data) {
      const extra = row.extra || {}
      const status = statusMeta(data && data.vocab, row.status)
      const lines = []
      lines.push('诊断 ' + row.sessionId)
      lines.push('状态：' + status.label + ' · ' + stepsText(extra))
      const where = [extra.platform, extra.framework].filter(Boolean).join(' / ')
      if (where) lines.push('平台 / 框架：' + where)
      if (row.activeCase) lines.push('命中 case：' + row.activeCase)
      const excluded = (extra.excludedCases || [])
      if (excluded.length) lines.push('已排除：' + excluded.join('、'))
      const waiting = (row.derived && row.derived.waitingFor) || extra.evidenceMissing || ''
      if (waiting) lines.push('在等：' + waiting)
      if (row.summary) lines.push('结论：' + row.summary)
      lines.push('来源：' + traceSource(row))
      return lines.join('\n')
    }

    function primaryFor(row, bound) {
      if (isPending(row)) return { key: 'feedback', mode: 'form', form: 'feedback', label: tr('action.feedback') }
      if (row.derived && row.derived.needSed) return { key: 'sediment', mode: 'draft', label: tr('action.sediment'), text: sedimentDraft(row) }
      if (isOpen(row)) {
        return bound
          ? { key: 'material', mode: 'draft', label: tr('action.material'), text: materialDraft(row) }
          : { key: 'resume', mode: 'draft', label: tr('action.resume'), text: resumeDraft(row) }
      }
      return { key: 'copy', mode: 'copy', label: tr('action.copySummary'), text: summaryText(row) }
    }

    function filterRows(rows, filter) {
      if (filter === 'open') return rows.filter((row) => isOpen(row))
      if (filter === 'pending') return rows.filter((row) => isPending(row))
      if (filter === 'sediment') return rows.filter((row) => !!(row.derived && row.derived.needSed))
      return rows
    }

    // ── 图标 ────────────────────────────────────────────────────────────────
    function IconRefresh() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' },
        h('path', { d: 'M13.2 8a5.2 5.2 0 1 1-1.6-3.75' }),
        h('path', { d: 'M13.4 2.6v3.1h-3.1' }))
    }

    function IconChevron(props) {
      return h('svg', { className: 'scp-chevron', 'data-open': props.open ? 'true' : 'false', width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' },
        h('path', { d: 'M4 6.2 8 10.2l4-4' }))
    }

    function IconLedger() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' },
        h('path', { d: 'M3 4h10M3 8h10M3 12h6' }))
    }

    function IconMore() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'currentColor' },
        h('circle', { cx: 3.2, cy: 8, r: 1.2 }),
        h('circle', { cx: 8, cy: 8, r: 1.2 }),
        h('circle', { cx: 12.8, cy: 8, r: 1.2 }))
    }

    function IconClose() {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round' },
        h('path', { d: 'M4.5 4.5l7 7M11.5 4.5l-7 7' }))
    }

    function StepRail(props) {
      const current = Number(props.extra && props.extra.currentStep) || 0
      const max = Number(props.extra && props.extra.maxSteps) || 6
      return h('span', { className: 'scp-track', role: 'img', 'aria-label': stepsText(props.extra) },
        Array.from({ length: max }, (_, index) => h('span', {
          key: 'step-' + index,
          className: 'scp-tick',
          'data-state': index < current - 1 ? 'done' : (index === current - 1 ? 'now' : 'todo'),
        })),
        h('em', { className: 'scp-now' }, stepsShort(props.extra)))
    }

    // ── 写入：动作、表单与面板 ─────────────────────────────────────────────
    function writeDisabledReason(data) {
      const caps = (data && data.capabilities) || {}
      if (caps.canWrite) return ''
      return caps.reason || tr('write.disabled')
    }

    function transitionPayload(row, data, extra) {
      return Object.assign({
        sessionId: store.sessionId,
        cwd: store.cwd,
        traceSessionId: row.sessionId,
        tracesDir: (data && data.tracesDir) || '',
        expectSha256: row.contentSha256,
      }, extra || {})
    }

    function WriteForm(props) {
      const { form, row, onSubmit, onCancel, busy, error } = props
      const [values, setValues] = React.useState(() => {
        const initial = {}
        for (const field of form.fields) {
          if (field.value !== undefined) initial[field.name] = field.value
          else if (field.name === 'severity') initial[field.name] = row.severity || 'service-affecting'
          else if (field.name === 'fixEmitted') initial[field.name] = 'true'
          else if (field.name === 'state') initial[field.name] = (row.sedimented && row.sedimented.state) || 'none'
          else if (field.name === 'source') initial[field.name] = 'field'
          else if (field.name === 'result') initial[field.name] = 'from_report'
          else initial[field.name] = ''
        }
        return initial
      })
      function change(name, value) {
        setValues((prev) => Object.assign({}, prev, { [name]: value }))
      }
      function submit(event) {
        if (event) event.preventDefault()
        const missing = form.fields.filter((field) => field.required && !String(values[field.name] || '').trim())
        if (missing.length) return
        onSubmit(values)
      }
      const preview = typeof form.preview === 'function' ? form.preview(values) : ''
      return h('form', { className: 'scp-form', onSubmit: submit },
        form.fields.map((field) => {
          if (field.showWhen && !field.showWhen(values)) return null
          const label = h('span', { className: 'scp-field-label' }, field.label + (field.required ? ' *' : ''))
          if (field.type === 'select') {
            return h('label', { key: field.name, className: 'scp-field' }, label,
              h('select', {
                className: 'scp-select',
                value: values[field.name],
                onChange: (event) => change(field.name, event.target.value),
              }, field.options.map((option) => h('option', { key: String(option.value), value: option.value }, option.label))))
          }
          if (field.type === 'textarea') {
            return h('label', { key: field.name, className: 'scp-field' }, label,
              h('textarea', {
                className: 'scp-textarea',
                value: values[field.name],
                placeholder: field.placeholder || '',
                onChange: (event) => change(field.name, event.target.value),
              }))
          }
          return h('label', { key: field.name, className: 'scp-field' }, label,
            h('input', {
              className: 'scp-input',
              type: 'text',
              value: values[field.name],
              placeholder: field.placeholder || '',
              onChange: (event) => change(field.name, event.target.value),
            }),
            field.hint ? h('span', { className: 'scp-form-hint' }, field.hint) : null)
        }),
        preview ? h('div', { className: 'scp-preview' },
          h('span', { className: 'scp-preview-label' }, tr('form.preview')),
          h('pre', { className: 'scp-preview-text' }, preview)) : null,
        error ? h('div', { className: 'scp-form-error' }, error) : null,
        h('div', { className: 'scp-form-actions' },
          h('button', { type: 'button', className: 'scp-btn scp-btn--ghost', onClick: onCancel }, tr('form.cancel')),
          h('button', { type: 'submit', className: 'scp-btn scp-btn--primary', disabled: busy },
            busy ? tr('form.busy') : (form.submitLabel || tr('form.submit')))))
    }

    function WritePanel(props) {
      const { row, data, onClose, onDone, onFlash, onDraft, autoForm } = props
      const vocab = (data && data.vocab) || {}
      const canWrite = !!((data && data.capabilities && data.capabilities.canWrite))
      const disabledReason = writeDisabledReason(data)
      const derived = row.derived || {}
      const feedback = row.feedback || {}
      const extra = row.extra || {}
      const bound = !!(data && data.bound && data.bound.sessionId === row.sessionId)

      function feedbackForm() {
        return {
          kind: 'feedback',
          title: tr('action.feedback'),
          submitLabel: tr('form.fill'),
          fields: [
            {
              name: 'result', type: 'select', label: tr('form.result'),
              options: REPORT_RESULT_KEYS.map((key) => ({ value: key, label: tr('report.' + key) })),
              value: 'from_report',
            },
            {
              name: 'source', type: 'select', label: tr('form.source'),
              options: [
                { value: 'field', label: tr('source.field') },
                { value: 'vendor', label: tr('source.vendor') },
              ],
              value: 'field',
            },
            {
              name: 'note', type: 'textarea', label: tr('form.note'),
              placeholder: tr('form.noteHint'),
            },
          ],
          preview: (values) => feedbackInstruction(row, values),
        }
      }

      const [form, setForm] = React.useState(() => (autoForm === 'feedback' ? feedbackForm() : null))
      const [busy, setBusy] = React.useState(false)
      const [error, setError] = React.useState('')

      function finish(result, successText) {
        setBusy(false)
        if (result && result.ok) {
          if (successText) onFlash(successText)
          else if (result.from || result.to) {
            onFlash(tr('write.done', {
              from: STATUS_LABEL[result.from] || result.from || '—',
              to: STATUS_LABEL[result.to] || result.to || '—',
            }))
          } else onFlash(tr('write.doneSimple'))
          onDone()
          return
        }
        const code = result && result.code
        if (code === 'E_STATE_CHANGED') {
          setError(tr('write.stateChanged'))
          refresh(true)
          return
        }
        const requirements = result && Array.isArray(result.requirements) && result.requirements.length
          ? tr('write.requirements', { fields: result.requirements.join('、') })
          : ''
        setError(tr('write.failed', { message: ((result && result.message) || code || '未知错误') + requirements }))
      }

      function run(extraPayload, successText) {
        setBusy(true)
        setError('')
        const promise = rpcCall('copilot-transition', transitionPayload(row, data, extraPayload))
        Promise.resolve(promise).then((result) => finish(result, successText), (exception) => {
          setBusy(false)
          setError(tr('write.failed', { message: String((exception && exception.message) || exception) }))
        })
      }

      function fillAndClose(text) {
        onDraft(text)
        if (onClose) onClose()
      }

      function copyItem(item) {
        copyToClipboard(item.text).then((ok) => onFlash(ok ? tr('hint.copied') : tr('hint.copyFailed')))
      }

      function openForm(next) {
        setError('')
        setForm(next)
      }

      if (form) {
        return h('div', {},
          h('div', { className: 'scp-menu-head' },
            h('span', { className: 'scp-menu-title' }, form.title),
            h('button', { type: 'button', className: 'scp-icon', 'aria-label': tr('action.closeMenu'), onClick: () => setForm(null) }, IconClose())),
          h(WriteForm, {
            form,
            row,
            busy,
            error,
            onCancel: () => setForm(null),
            onSubmit: (values) => {
              if (form.kind === 'feedback') {
                fillAndClose(feedbackInstruction(row, values))
                return
              }
              if (form.kind === 'close:resolved') {
                run({
                  kind: 'close',
                  to: 'resolved',
                  endingKind: 'root_cause',
                  severity: values.severity,
                  fix_emitted: values.fixEmitted === 'true',
                })
              } else if (form.kind === 'close:escalated') {
                run({ kind: 'close', to: 'escalated', endingKind: 'handed_off', handedTo: values.handedTo })
              } else if (form.kind === 'close:archived') {
                run({ kind: 'close', to: 'archived', endingKind: values.ending, duplicateOf: values.duplicateOf })
              } else if (form.kind === 'sedimented') {
                run({ kind: 'sedimented', state: values.state, caseId: values.caseId },
                  tr('write.doneSediment', { state: tr('sediment.' + values.state) }))
              }
            },
          }))
      }

      const groups = []

      const instructItems = []
      if (isOpen(row)) {
        instructItems.push({
          key: 'resume',
          label: bound ? tr('action.material') : tr('action.resume'),
          onSelect: () => fillAndClose(bound ? materialDraft(row) : resumeDraft(row)),
        })
      }
      if (row.activeCase) {
        const upstream = (data && data.upstream) || {}
        instructItems.push({
          key: 'upstream',
          label: tr('action.upstream'),
          note: upstream.ready ? '' : (upstream.reason || ''),
          onSelect: () => fillAndClose(upstreamDraft(row, data && data.upstream)),
        })
      }
      instructItems.push({
        key: 'report',
        label: tr('action.reportDoc'),
        onSelect: () => fillAndClose(reportDraft(row)),
      })
      instructItems.push({
        key: 'handoff',
        label: tr('action.handoff'),
        onSelect: () => fillAndClose(handoffDraft(row)),
      })
      groups.push({ key: 'instruct', title: tr('group.instruct'), items: instructItems })

      const settleItems = []
      if (row.activeCase || feedback.case) {
        settleItems.push({
          key: 'feedback',
          label: tr('action.feedbackForm'),
          onSelect: () => openForm(feedbackForm()),
        })
      }
      if (derived.needSed) {
        settleItems.push({
          key: 'sediment',
          label: tr('action.sediment'),
          onSelect: () => fillAndClose(sedimentDraft(row)),
        })
      }
      if (derived.needPromote) {
        settleItems.push({
          key: 'promote',
          label: tr('action.promote'),
          onSelect: () => fillAndClose(promoteDraft(row)),
        })
      }
      if (derived.needReview) {
        settleItems.push({
          key: 'review',
          label: tr('action.review'),
          onSelect: () => fillAndClose(reviewDraft(row)),
        })
      }
      if (settleItems.length) groups.push({ key: 'settle', title: tr('group.settle'), items: settleItems })

      const stateItems = [
        {
          key: 'close:resolved', label: tr('close.resolved'), disabled: !canWrite,
          onSelect: () => openForm({
            kind: 'close:resolved',
            title: tr('close.resolved'),
            fields: [
              {
                name: 'severity', type: 'select', label: tr('form.severity'),
                options: (vocab.severities || []).map((item) => ({ value: item.value, label: item.label })),
              },
              {
                name: 'fixEmitted', type: 'select', label: tr('form.fixEmitted'),
                options: [{ value: 'true', label: tr('form.yes') }, { value: 'false', label: tr('form.no') }],
              },
            ],
          }),
        },
        {
          key: 'close:escalated', label: tr('close.escalated'), disabled: !canWrite,
          onSelect: () => openForm({
            kind: 'close:escalated',
            title: tr('close.escalated'),
            fields: [{ name: 'handedTo', type: 'text', label: tr('form.handedTo'), required: true, hint: tr('form.handedToHint') }],
          }),
        },
        {
          key: 'close:archived', label: tr('close.archived'), disabled: !canWrite,
          onSelect: () => openForm({
            kind: 'close:archived',
            title: tr('close.archived'),
            fields: [
              {
                name: 'ending', type: 'select', label: tr('form.ending'),
                options: ARCHIVED_ENDING_KEYS.map((key) => ({ value: key, label: tr('ending.' + key) })),
              },
              {
                name: 'duplicateOf', type: 'text', label: tr('form.duplicateOf'),
                hint: tr('form.duplicateOfHint'),
                showWhen: (values) => values.ending === 'duplicate',
              },
            ],
          }),
        },
      ]
      if (!isOpen(row)) {
        stateItems.push({
          key: 'reopen', label: tr('reopen'), disabled: !canWrite,
          onSelect: () => run({ kind: 'reopen' }),
        })
      }
      stateItems.push({
        key: 'sedimented', label: tr('action.sedimentState'), disabled: !canWrite,
        onSelect: () => openForm({
          kind: 'sedimented',
          title: tr('sediment.knowledge'),
          fields: [
            {
              name: 'state', type: 'select', label: tr('form.state'),
              options: SEDIMENT_STATE_KEYS.map((key) => ({ value: key, label: tr('sediment.' + key) })),
              value: 'submitted',
            },
            { name: 'caseId', type: 'text', label: tr('form.caseId'), hint: tr('form.caseIdHint') },
          ],
        }),
      })
      groups.push({ key: 'state', title: tr('group.state'), items: stateItems })

      groups.push({
        key: 'copy',
        title: tr('group.copy'),
        items: [{
          key: 'summary',
          label: tr('action.copySummary'),
          onSelect: () => copyItem({ text: summaryText(row, data) }),
        }],
      })

      const navItems = [
        {
          key: 'ledger',
          label: tr('action.ledger'),
          onSelect: () => {
            if (onClose) onClose()
            setPaletteOpen(true, row.sessionId)
          },
        },
        {
          key: 'refresh',
          label: tr('action.refresh'),
          onSelect: () => {
            if (onClose) onClose()
            refresh(true)
          },
        },
      ]
      if (row.harnessSession) {
        navItems.push({
          key: 'open-session',
          label: tr('action.openSession'),
          onSelect: () => {
            if (onClose) onClose()
            ctxOpenSession(row.harnessSession).then((result) => {
              if (!result.ok) onFlash(result.reason || '打不开这一单的会话')
            })
          },
        })
      }
      groups.push({ key: 'nav', title: tr('group.nav'), items: navItems })

      return h('div', {},
        h('div', { className: 'scp-menu-head' },
          h('span', { className: 'scp-menu-title' }, tr('menu.title')),
          h('button', { type: 'button', className: 'scp-icon', 'aria-label': tr('action.closeMenu'), onClick: onClose }, IconClose())),
        !canWrite ? h('div', { className: 'scp-form-hint', style: { padding: '0 6px 4px' } }, disabledReason) : null,
        groups.map((group) => h('div', { key: group.key },
          h('div', { className: 'scp-menu-group' }, group.title),
          group.items.map((item) => h('button', {
            key: item.key,
            type: 'button',
            className: 'scp-menu-item',
            disabled: !!item.disabled,
            title: item.disabled ? disabledReason : undefined,
            onClick: item.onSelect,
          }, item.label, item.note ? h('span', { className: 'scp-menu-note' }, item.note) : null)))),
        error ? h('div', { className: 'scp-form-error', style: { padding: '4px 6px' } }, error) : null)
    }

    // ── 面 1：状态条 ───────────────────────────────────────────────────────
    // 安静的一行：状态点 + 可点的跟踪范围 + 人读案例标题 + 状态 + 进度 + 一个主操作。
    // 默认收起（偏好可改），第二行（元信息 / 在等什么 / 身份标签）按需展开。
    // 左端的范围标签同时是选择器：可以把这一栏固定到任意一单，而不是只跟「最近一单」。
    function makeDock() {
      return function Dock(props) {
        const s = useStore()
        useSessionSync(props)
        const [menuOpen, setMenuOpen] = React.useState(false)
        const [menuForm, setMenuForm] = React.useState(null)
        const [pickerOpen, setPickerOpen] = React.useState(false)
        const [idle, setIdle] = React.useState(false)
        const idleTimer = React.useRef(null)
        const lastBump = React.useRef(0)
        const [query, setQuery] = React.useState('')
        const [hint, setHint] = React.useState('')
        const hintTimer = React.useRef(null)
        const inputRef = React.useRef(null)
        const rootRef = React.useRef(null)

        const flash = React.useCallback((text) => {
          setHint(text)
          if (hintTimer.current) clearTimeout(hintTimer.current)
          hintTimer.current = setTimeout(() => setHint(''), 4600)
        }, [])

        React.useEffect(() => () => {
          if (hintTimer.current) clearTimeout(hintTimer.current)
        }, [])

        // 收起态静置后淡出；鼠标移动、滚动、聚焦输入框时浮现。reduce-motion 下不淡出。
        const idleRef = React.useRef({ collapsed: false })
        idleRef.current.collapsed = s.prefs.dockCollapsed
        const bumpIdle = React.useCallback(() => {
          const now = Date.now()
          if (now - lastBump.current < 500) return
          lastBump.current = now
          setIdle(false)
          if (idleTimer.current) clearTimeout(idleTimer.current)
          idleTimer.current = setTimeout(() => {
            let reduced = false
            try {
              reduced = typeof window.matchMedia === 'function'
                && window.matchMedia('(prefers-reduced-motion: reduce)').matches
            } catch {
              reduced = false
            }
            if (!reduced && idleRef.current.collapsed) setIdle(true)
          }, 2800)
        }, [])

        React.useEffect(() => {
          if (!s.prefs.dockCollapsed) {
            setIdle(false)
            if (idleTimer.current) clearTimeout(idleTimer.current)
            return undefined
          }
          bumpIdle()
          const onMove = () => bumpIdle()
          const onScroll = () => bumpIdle()
          const onFocus = () => bumpIdle()
          document.addEventListener('pointermove', onMove, { passive: true })
          document.addEventListener('wheel', onScroll, { passive: true, capture: true })
          document.addEventListener('scroll', onScroll, { capture: true, passive: true })
          document.addEventListener('focusin', onFocus)
          return () => {
            document.removeEventListener('pointermove', onMove)
            document.removeEventListener('wheel', onScroll, { capture: true })
            document.removeEventListener('scroll', onScroll, { capture: true })
            document.removeEventListener('focusin', onFocus)
            if (idleTimer.current) clearTimeout(idleTimer.current)
          }
        }, [s.prefs.dockCollapsed, bumpIdle])

        React.useEffect(() => () => {
          if (idleTimer.current) clearTimeout(idleTimer.current)
        }, [])

        React.useEffect(() => {
          if (!pickerOpen) return undefined
          const node = inputRef.current
          if (node && typeof node.focus === 'function') node.focus()
          return undefined
        }, [pickerOpen])

        React.useEffect(() => {
          if (!menuOpen && !pickerOpen) return undefined
          const onDown = (event) => {
            const root = rootRef.current
            const inside = root && event.target && typeof root.contains === 'function'
              && (typeof Node === 'undefined' || event.target instanceof Node)
              && root.contains(event.target)
            if (inside) return
            setMenuOpen(false)
            setPickerOpen(false)
          }
          document.addEventListener('mousedown', onDown)
          return () => document.removeEventListener('mousedown', onDown)
        }, [menuOpen, pickerOpen])

        const collapsed = s.prefs.dockCollapsed
        const data = s.data

        function toggleCollapsed() {
          savePrefs({ dockCollapsed: !collapsed })
          setMenuOpen(false)
          setPickerOpen(false)
        }

        function fillDraft(text) {
          const inputActions = props && props.inputActions
          if (inputActions && typeof inputActions.setDraft === 'function') {
            try {
              inputActions.setDraft(text)
              flash(tr('hint.draft'))
              return
            } catch (error) {
              flash(tr('hint.failed', { message: String((error && error.message) || error) }))
              return
            }
          }
          copyToClipboard(text).then((ok) => flash(ok ? tr('hint.copiedFallback') : tr('hint.noInput')))
        }

        function copyAndFlash(text) {
          copyToClipboard(text).then((ok) => flash(ok ? tr('hint.copied') : tr('hint.copyFailed')))
        }

        if (s.phase === 'idle' || s.phase === 'loading') return null
        if (data && data.ok === false && data.code === 'E_NO_ROOT') return null

        const rootProps = {
          'data-version': PLUGIN_VERSION,
          role: 'region',
          'aria-label': tr('region'),
          title: tr('region') + ' v' + PLUGIN_VERSION,
        }

        function renderHandle(title, meta, pending) {
          return h('div', { className: 'scp-handle-wrap' },
            h('button', {
              type: 'button',
              className: 'scp-handle',
              'data-idle': idle ? 'true' : 'false',
              'aria-label': tr('action.expand'),
              title,
              onClick: toggleCollapsed,
            },
              h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
              h('span', { className: 'scp-handle-title' }, title),
              meta ? h('span', { className: 'scp-handle-meta' }, meta) : null,
              pending ? h('span', { className: 'scp-handle-pending' }, tr('chip.feedback')) : null,
              IconChevron({ open: false })))
        }

        const failed = s.phase === 'error' || (data && data.ok === false)
        if (failed) {
          const message = s.phase === 'error' ? s.message : (data && data.message ? data.message : tr('title.error'))
          if (collapsed) {
            return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'error', 'data-tone': 'error' }),
              renderHandle(tr('title.error'), null, false))
          }
          return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'error', 'data-tone': 'error' }),
            h('div', { className: 'scp-surface' },
              h('div', { className: 'scp-head' },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-badge' }, tr('title.error')),
                h('span', { className: 'scp-wait', title: message }, message),
                h('span', { className: 'scp-spacer' }),
                h('button', { type: 'button', className: 'scp-btn', onClick: () => refresh(true) }, tr('action.retry')))))
        }

        const allRows = (data.all || [])
        const pinnedId = pinnedIdFor(s.sessionId)
        const pinnedRow = pinnedId ? allRows.find((row) => row.sessionId === pinnedId) : null
        const primary = pinnedRow || data.bound || (data.recent && data.recent[0]) || null

        if (!primary) {
          if (collapsed) {
            return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'empty', 'data-tone': 'idle' }),
              renderHandle(tr('empty.collapsed'), null, false))
          }
          return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'empty', 'data-tone': 'idle' }),
            h('div', { className: 'scp-surface' },
              h('div', { className: 'scp-head' },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-case', style: { cursor: 'default', fontWeight: 500 } }, tr('empty.collapsed')),
                h('span', { className: 'scp-spacer' }),
                h('button', {
                  type: 'button',
                  className: 'scp-btn scp-btn--quiet',
                  onClick: () => fillDraft('/skill:diagnose '),
                }, tr('action.start')),
                h('button', {
                  type: 'button',
                  className: 'scp-icon',
                  'aria-label': collapsed ? tr('action.expand') : tr('action.collapse'),
                  title: collapsed ? tr('action.expand') : tr('action.collapse'),
                  onClick: toggleCollapsed,
                }, IconChevron({ open: !collapsed }))),
              collapsed ? null : h('div', { className: 'scp-foot' },
                h('span', { className: 'scp-empty-note' }, tr('empty.body')))))
        }

        const bound = !!data.bound && primary.sessionId === data.bound.sessionId
        const pinned = !!pinnedRow
        const tone = toneOf(primary)
        const status = statusMeta(data.vocab, primary.status)
        const extra = primary.extra || {}
        const derived = primary.derived || {}
        const waiting = derived.waitingFor || extra.evidenceMissing || ''
        const action = primaryFor(primary, bound)
        const chips = identityChips(primary).slice(0, 3)
        const metaBits = []
        if (extra.platform) metaBits.push(extra.platform)
        if (extra.framework) metaBits.push(extra.framework)
        if (extra.category) metaBits.push(CATEGORY_LABEL[extra.category] || extra.category)

        function runPrimary() {
          if (action.mode === 'draft') fillDraft(action.text)
          else if (action.mode === 'copy') copyAndFlash(action.text)
          else {
            setMenuForm(action.mode === 'form' ? (action.form || null) : null)
            setMenuOpen(true)
            setPickerOpen(false)
          }
        }

        function openOverview() {
          setPaletteOpen(true, primary.sessionId)
        }

        const pickerRows = allRows
          .filter((row) => {
            if (!query.trim()) return true
            const needle = query.trim().toLowerCase()
            return caseTitle(row).toLowerCase().includes(needle) || row.sessionId.toLowerCase().includes(needle)
          })
          .slice(0, 12)

        const picker = pickerOpen ? h('div', { className: 'scp-picker', role: 'dialog', 'aria-label': tr('picker.title') },
          h('div', { className: 'scp-picker-head' },
            h('div', { className: 'scp-picker-title' }, tr('picker.title')),
            h('input', {
              ref: inputRef,
              className: 'scp-picker-search',
              type: 'text',
              value: query,
              placeholder: tr('picker.search'),
              onChange: (event) => setQuery(event.target.value),
            })),
          h('div', { className: 'scp-picker-list' },
            pickerRows.length === 0
              ? h('div', { className: 'scp-picker-empty' }, tr('picker.empty'))
              : pickerRows.map((row) => {
                const active = row.sessionId === primary.sessionId
                return h('button', {
                  key: row.sessionId,
                  type: 'button',
                  className: 'scp-picker-row',
                  'data-on': active ? 'true' : 'false',
                  onClick: () => {
                    setPin(s.sessionId, row.sessionId)
                    setPickerOpen(false)
                    flash(tr('hint.pinned'))
                  },
                },
                  h('span', {
                    className: 'scp-ring',
                    'aria-hidden': 'true',
                    style: { background: TONE_VAR[toneOf(row)] || TONE_VAR.idle },
                  }),
                  h('span', { className: 'scp-picker-main' },
                    h('span', { className: 'scp-picker-name' }, caseTitle(row)),
                    h('span', { className: 'scp-picker-meta' },
                      statusMeta(data.vocab, row.status).label,
                      ' · ',
                      stepsShort(row.extra),
                      ' · ',
                      formatTime(row.updatedAt) || tr('none'))))
              })),
          h('div', { className: 'scp-picker-foot' },
            h('button', {
              type: 'button',
              className: 'scp-btn scp-btn--ghost',
              onClick: () => {
                setPin(s.sessionId, '')
                setPickerOpen(false)
                flash(tr('hint.unpinned'))
              },
            }, tr('picker.follow')),
            h('span', { className: 'scp-spacer' }),
            h('button', { type: 'button', className: 'scp-btn', onClick: () => { setPickerOpen(false); openOverview() } }, tr('picker.open')))) : null

        const menu = menuOpen ? h('div', { className: 'scp-menu', role: 'menu', 'aria-label': tr('menu.title') },
          h(WritePanel, {
            row: primary,
            data,
            autoForm: menuForm,
            onClose: () => { setMenuOpen(false); setMenuForm(null) },
            onDone: () => { setMenuOpen(false); setMenuForm(null); refresh(true) },
            onFlash: flash,
            onDraft: fillDraft,
          })) : null

        const scopeLabel = pinned ? tr('scope.pinned') : (bound ? tr('scope.bound') : tr('scope.recent'))

        if (collapsed) {
          return h('section', Object.assign({}, rootProps, {
            ref: rootRef,
            className: 'scp-root',
            'data-mode': pinned ? 'pinned' : (bound ? 'bound' : 'recent'),
            'data-tone': tone,
            'data-live': derived.open ? 'true' : 'false',
          }), renderHandle(caseTitle(primary), stepsShort(extra), isPending(primary)))
        }

        return h('section', Object.assign({}, rootProps, {
          ref: rootRef,
          className: 'scp-root',
          'data-mode': pinned ? 'pinned' : (bound ? 'bound' : 'recent'),
          'data-tone': tone,
          'data-live': derived.open ? 'true' : 'false',
        }),
          picker,
          menu,
          h('div', { className: 'scp-surface' },
            h('div', { className: 'scp-head' },
              h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
              h('button', {
                type: 'button',
                className: 'scp-scope',
                'aria-label': tr('picker.title'),
                title: tr('picker.title'),
                'aria-expanded': pickerOpen ? 'true' : 'false',
                onClick: () => { setPickerOpen((value) => !value); setMenuOpen(false) },
              }, scopeLabel, h('svg', { width: 8, height: 8, viewBox: '0 0 8 8', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.2, strokeLinecap: 'round' },
                h('path', { d: 'M1.6 3 4 5.4 6.4 3' }))),
              h('button', {
                type: 'button',
                className: 'scp-case',
                title: primary.summary || primary.sessionId,
                'aria-label': tr('action.ledger') + '：' + caseTitle(primary),
                onClick: openOverview,
              }, caseTitle(primary)),
              h('span', { className: 'scp-status-text' }, status.label),
              collapsed ? h('span', { className: 'scp-step' }, stepsShort(extra)) : null,
              h('span', { className: 'scp-spacer' }),
              h('button', { type: 'button', className: 'scp-btn scp-btn--quiet', onClick: runPrimary }, action.label),
              collapsed ? null : h('button', {
                type: 'button', className: 'scp-icon', title: tr('action.more'), 'aria-label': tr('action.more'),
                'aria-expanded': menuOpen ? 'true' : 'false',
                onClick: () => { setMenuForm(null); setMenuOpen((value) => !value); setPickerOpen(false) },
              }, IconMore()),
              h('button', {
                type: 'button', className: 'scp-icon',
                'aria-label': collapsed ? tr('action.expand') : tr('action.collapse'),
                title: collapsed ? tr('action.expand') : tr('action.collapse'),
                'aria-expanded': collapsed ? 'false' : 'true',
                onClick: toggleCollapsed,
              }, IconChevron({ open: !collapsed }))),
            collapsed ? null : h('div', { className: 'scp-foot' },
              StepRail({ extra }),
              metaBits.length ? h('span', { className: 'scp-meta' }, metaBits.join(' · ')) : null,
              h('span', { className: 'scp-wait', title: waiting }, waiting
                ? h('span', {}, tr('waiting') + '：', h('b', {}, waiting))
                : h('span', {}, tr('label.updated') + ' ' + (formatTime(primary.updatedAt) || tr('none')))),
              chips.length ? h('span', { className: 'scp-chips' }, chips.map((chip) => h('span', {
                key: chip.key, className: 'scp-chip', 'data-tone': chip.tone,
              }, chip.text))) : null)),
          hint ? h('div', { className: 'scp-hint', role: 'status' }, hint) : null)
      }
    }

    // ── 面 2：输入区工具条入口 ─────────────────────────────────────────────
    function ToolbarButton(props) {
      const s = useStore()
      useSessionSync(props)
      const data = s.data && s.data.ok !== false ? s.data : null
      const bound = data ? data.bound : null
      const pending = data && data.counts ? Number(data.counts.pendingFeedback) || 0 : 0
      const tone = bound ? toneOf(bound) : 'idle'
      const title = pending > 0 ? tr('tool.title') + ' · ' + tr('tool.pending', { n: pending }) : tr('tool.title')
      return h('button', {
        type: 'button',
        className: 'scp-tool-btn',
        'data-tone': tone,
        title,
        'aria-label': title,
        'data-version': PLUGIN_VERSION,
        onClick: () => setPaletteOpen(!s.paletteOpen),
      },
        h('svg', { width: 15, height: 15, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' },
          h('path', { d: 'M2.4 4.2h11.2M2.4 8h11.2M2.4 11.8h7' })),
        pending > 0 ? h('span', { className: 'scp-tool-badge' }, pending > 9 ? '9+' : String(pending)) : null)
    }

    // ── 面 3：诊断总览（浮层）─────────────────────────────────────────────
    function Palette() {
      const s = useStore()
      const data = s.data && s.data.ok !== false ? s.data : null
      const rows = data ? (data.all || []) : []
      const filter = s.prefs.paletteFilter
      const filtered = filterRows(rows, filter)
      const [selected, setSelected] = React.useState(0)
      const [menuOpen, setMenuOpen] = React.useState(false)
      const [menuForm, setMenuForm] = React.useState(null)
      const [toast, setToast] = React.useState('')
      const toastTimer = React.useRef(null)
      const panelRef = React.useRef(null)

      const flash = React.useCallback((text) => {
        setToast(text)
        if (toastTimer.current) clearTimeout(toastTimer.current)
        toastTimer.current = setTimeout(() => setToast(''), 4600)
      }, [])

      React.useEffect(() => () => {
        if (toastTimer.current) clearTimeout(toastTimer.current)
      }, [])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        if (!data) refresh(true)
      }, [s.paletteOpen, data])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        setMenuOpen(false)
        const position = filtered.findIndex((row) => row.sessionId === s.paletteSelect)
        setSelected(position >= 0 ? position : 0)
      }, [s.paletteOpen, s.paletteSelect, filter])

      React.useEffect(() => {
        if (selected > filtered.length - 1) setSelected(filtered.length > 0 ? filtered.length - 1 : 0)
      }, [filtered.length, selected])

      React.useEffect(() => {
        if (!s.paletteOpen) return undefined
        const node = panelRef.current
        if (node && typeof node.focus === 'function') node.focus()
        const onKey = (event) => {
          const target = event.target
          const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')
          if (event.key === 'Escape') {
            event.preventDefault()
            if (menuOpen) setMenuOpen(false)
            else setPaletteOpen(false)
            return
          }
          if (typing || menuOpen) return
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (!filtered.length) return
            event.preventDefault()
            setSelected((current) => {
              const next = event.key === 'ArrowDown' ? current + 1 : current - 1
              return Math.max(0, Math.min(next, filtered.length - 1))
            })
            return
          }
          if (event.key === 'Enter') {
            if (event.target && event.target.tagName === 'BUTTON') return
            const row = filtered[selected]
            if (!row) return
            event.preventDefault()
            runPrimary(row)
          }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [s.paletteOpen, filtered, selected, menuOpen])

      if (!s.paletteOpen) return null

      const row = filtered[selected] || null
      const counts = data && data.counts ? data.counts : {}
      const filterCounts = {
        all: rows.length,
        open: filterRows(rows, 'open').length,
        pending: filterRows(rows, 'pending').length,
        sediment: filterRows(rows, 'sediment').length,
      }

      function fillDraft(text) {
        const inputActions = findInputActions()
        if (inputActions && typeof inputActions.setDraft === 'function') {
          try {
            inputActions.setDraft(text)
            flash(tr('hint.draft'))
            setPaletteOpen(false)
            return
          } catch (error) {
            flash(tr('hint.failed', { message: String((error && error.message) || error) }))
            return
          }
        }
        copyToClipboard(text).then((ok) => flash(ok ? tr('hint.copiedFallback') : tr('hint.noInput')))
      }

      function copyAndFlash(text) {
        copyToClipboard(text).then((ok) => flash(ok ? tr('hint.copied') : tr('hint.copyFailed')))
      }

      function runPrimary(target) {
        if (!target) return
        const boundId = data && data.bound ? data.bound.sessionId : ''
        const action = primaryFor(target, target.sessionId === boundId)
        if (action.mode === 'draft') fillDraft(action.text)
        else if (action.mode === 'copy') copyAndFlash(action.text)
        else {
          setMenuForm(action.mode === 'form' ? (action.form || null) : null)
          setMenuOpen(true)
        }
      }

      function def(label, value, key) {
        return h('div', { className: 'scp-def', key: key || label },
          h('dt', {}, label),
          h('dd', {}, value))
      }

      const filterButtons = FILTER_KEYS.map((key) => h('button', {
        key,
        type: 'button',
        className: 'scp-filter-item',
        'data-on': filter === key ? 'true' : 'false',
        onClick: () => savePrefs({ paletteFilter: key }),
      }, tr('palette.filter.' + key) + ' ' + String(filterCounts[key] || 0)))

      const skeleton = Array.from({ length: 5 }, (_, index) => h('div', { key: 'skel-' + index, className: 'scp-pal-row' },
        h('span', { className: 'scp-ring', style: { background: 'var(--dsw-alias-bg-layer-2)', boxShadow: 'none' } }),
        h('span', { className: 'scp-pal-row-main' },
          h('span', { className: 'scp-skel', style: { width: '68%' } }),
          h('span', { className: 'scp-skel', style: { width: '42%', height: 9 } }))))

      const emptyMark = h('svg', {
        width: 40, height: 40, viewBox: '0 0 40 40', fill: 'none', stroke: 'currentColor',
        strokeWidth: 1.2, 'aria-hidden': 'true', opacity: 0.55,
      }, h('circle', { cx: 20, cy: 20, r: 13, strokeDasharray: '3 4' }),
        h('path', { d: 'M14 20h12M20 14v12', strokeLinecap: 'round' }))

      const list = h('div', { className: 'scp-pal-list', role: 'listbox', 'aria-label': tr('palette.title') },
        !data ? skeleton
          : filtered.length === 0 ? h('div', { className: 'scp-pal-empty' }, emptyMark, tr('palette.empty'))
            : filtered.map((item, index) => {
              const extra = item.extra || {}
              const metaPieces = []
              if (extra.platform) metaPieces.push(extra.platform)
              if (extra.framework) metaPieces.push(extra.framework)
              if (extra.excludedCases && extra.excludedCases.length) metaPieces.push(tr('chip.excluded', { n: extra.excludedCases.length }))
              return h('button', {
                key: item.sessionId,
                type: 'button',
                className: 'scp-pal-row',
                role: 'option',
                'aria-selected': index === selected ? 'true' : 'false',
                'data-on': index === selected ? 'true' : 'false',
                style: { '--scp-tone': TONE_VAR[toneOf(item)] || TONE_VAR.idle },
                onClick: () => { setSelected(index); setMenuOpen(false) },
                onDoubleClick: () => runPrimary(item),
              },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-pal-row-main' },
                  h('span', { className: 'scp-pal-row-line' },
                    h('span', { className: 'scp-pal-row-title', title: caseTitle(item) }, caseTitle(item)),
                    h('span', { className: 'scp-pal-row-step' }, stepsShort(extra))),
                  h('span', { className: 'scp-pal-row-meta' },
                    h('span', { className: 'scp-pal-row-meta-main' },
                      [statusMeta(data.vocab, item.status).label].concat(metaPieces).join(' · ')),
                    h('span', { className: 'scp-pal-row-time' }, formatTime(item.updatedAt) || tr('none')))))
            }))

      const waiting = row ? ((row.derived && row.derived.waitingFor) || (row.extra && row.extra.evidenceMissing) || '') : ''
      const extra = row ? (row.extra || {}) : {}
      const sideMeta = []
      if (extra.platform) sideMeta.push(extra.platform)
      if (extra.framework) sideMeta.push(extra.framework)
      if (extra.category) sideMeta.push(CATEGORY_LABEL[extra.category] || extra.category)

      const side = row
        ? menuOpen
          ? h(WritePanel, {
            row,
            data,
            autoForm: menuForm,
            onClose: () => { setMenuOpen(false); setMenuForm(null) },
            onDone: () => { setMenuOpen(false); setMenuForm(null); refresh(true) },
            onFlash: flash,
            onDraft: fillDraft,
          })
          : h('div', { className: 'scp-pal-side', style: { '--scp-tone': TONE_VAR[toneOf(row)] || TONE_VAR.brand } },
            h('div', { className: 'scp-hero' },
              h('div', { className: 'scp-hero-title' }, caseTitle(row)),
              h('div', { className: 'scp-hero-meta' },
                h('span', { className: 'scp-badge' }, statusMeta(data.vocab, row.status).label),
                h('span', { className: 'scp-step' }, stepsText(extra)),
                identityChips(row).slice(0, 3).map((chip) => h('span', {
                  key: chip.key, className: 'scp-chip', 'data-tone': chip.tone,
                }, chip.text)))),
            waiting ? h('div', { className: 'scp-callout' },
              h('span', { className: 'scp-callout-label' }, tr('section.waiting')),
              h('div', { className: 'scp-callout-text' }, waiting)) : null,
            h('div', { className: 'scp-section-label' }, tr('section.overview')),
            h('dl', { className: 'scp-grid2' },
              def(tr('label.steps'), stepsText(extra), 'steps'),
              def('平台 / 框架', sideMeta.length ? sideMeta.join(' · ') : tr('none'), 'meta'),
              def(tr('label.hit'), row.activeCase || tr('chip.miss'), 'hit'),
              def(tr('label.excluded'), String((extra.excludedCases || []).length) + ' 条', 'excluded'),
              def(tr('label.sediment'), vocabLabel((data.vocab || {}).sedimented, (row.sedimented || {}).state, SED_LABEL), 'sed'),
              def(tr('label.feedback'), row.feedback && row.feedback.outcome ? vocabLabel((data.vocab || {}).outcomes, row.feedback.outcome, OUTCOME_LABEL) : tr('none'), 'fb'),
              def(tr('label.updated'), formatTime(row.updatedAt) || tr('none'), 'updated'),
              def(tr('label.report'), extra.hasReport ? tr('label.hasReport') : tr('label.noReport'), 'report')),
            row.summary ? h('div', { className: 'scp-section-label' }, tr('section.background')) : null,
            row.summary ? h('p', { className: 'scp-p' }, row.summary) : null,
            h('div', { className: 'scp-actions' },
              h('button', {
                type: 'button',
                className: 'scp-btn scp-btn--primary',
                onClick: () => runPrimary(row),
              }, primaryFor(row, data.bound && row.sessionId === data.bound.sessionId).label),
              h('button', { type: 'button', className: 'scp-btn', onClick: () => copyAndFlash(summaryText(row, data)) }, tr('action.copySummary')),
              h('button', { type: 'button', className: 'scp-btn', onClick: () => copyAndFlash(resumeDraft(row)) }, tr('action.copyResume')),
              row.activeCase ? h('button', {
                type: 'button',
                className: 'scp-btn',
                onClick: () => fillDraft(upstreamDraft(row, data.upstream)),
              }, tr('action.upstream')) : null,
              store.sessionId ? h('button', {
                type: 'button',
                className: 'scp-btn',
                onClick: () => {
                  const isPinned = pinnedIdFor(store.sessionId) === row.sessionId
                  setPin(store.sessionId, isPinned ? '' : row.sessionId)
                  flash(isPinned ? tr('hint.unpinned') : tr('hint.pinned'))
                },
              }, pinnedIdFor(store.sessionId) === row.sessionId ? tr('action.unpin') : tr('action.pin')) : null,
              h('button', { type: 'button', className: 'scp-btn', onClick: () => setMenuOpen(true) }, tr('action.more'))))
        : h('div', { className: 'scp-pal-side' },
          h('div', { className: 'scp-pal-empty' },
            emptyMark,
            !data ? tr('palette.loading') : tr('palette.empty')))

      const subParts = [tr('palette.count', { n: rows.length })]
      if (Number(counts.pendingFeedback) > 0) subParts.push(tr('queue.pending', { n: Number(counts.pendingFeedback) }))

      return h('div', {
        className: 'scp-pal-backdrop',
        onMouseDown: (event) => {
          if (event.target === event.currentTarget) setPaletteOpen(false)
        },
      },
        h('div', {
          className: 'scp-pal',
          role: 'dialog',
          'aria-modal': 'true',
          'aria-label': tr('palette.title'),
          tabIndex: -1,
          ref: panelRef,
          'data-version': PLUGIN_VERSION,
        },
          h('div', { className: 'scp-pal-top' },
            h('div', { className: 'scp-pal-heading' },
              h('span', { className: 'scp-pal-title' }, tr('palette.title')),
              h('span', { className: 'scp-pal-sub' }, subParts.join(' · '))),
            h('span', { className: 'scp-spacer' }),
            h('div', { className: 'scp-filter', role: 'tablist', 'aria-label': tr('palette.title') }, filterButtons),
            h('button', {
              type: 'button', className: 'scp-icon', 'aria-label': tr('palette.close'), title: tr('palette.close'),
              onClick: () => setPaletteOpen(false),
            }, IconClose())),
          h('div', { className: 'scp-pal-main' }, list, side),
          h('div', { className: 'scp-pal-foot' },
            h('span', {},
              h('span', { className: 'scp-kbd' }, '↑'),
              h('span', { className: 'scp-kbd' }, '↓'),
              ' 选择 · ',
              h('span', { className: 'scp-kbd' }, 'Enter'),
              ' 主操作 · ',
              h('span', { className: 'scp-kbd' }, 'Esc'),
              ' 关闭'),
            h('span', { className: 'scp-spacer' }),
            h('span', {}, [
              tr('queue.open', { n: Number(counts.open) || 0 }),
              tr('queue.pending', { n: Number(counts.pendingFeedback) || 0 }),
              tr('queue.sediment', { n: Number(counts.toSediment) || 0 }),
            ].join(' · ')),
            h('span', { className: 'scp-version' }, 'v' + PLUGIN_VERSION)),
          toast ? h('span', { className: 'scp-toast', role: 'status' }, toast) : null))
    }

    // ── 打开其它会话（轨迹写了 harness_session 时可用）────────────────────
    let openSessionImpl = () => Promise.resolve({ ok: false, reason: '会话服务不可用' })
    function ctxOpenSession(id) {
      return openSessionImpl(id)
    }

    const surfaceInputs = []
    function findInputActions() {
      for (const surface of surfaceInputs) {
        if (surface && typeof surface.setDraft === 'function') return surface
      }
      return null
    }

    // ── 注册 ────────────────────────────────────────────────────────────────
    function registerLocale(ctx) {
      const locale = ctx.get('locale')
      if (locale === undefined || typeof locale.register !== 'function') return () => {}
      const disposers = []
      for (const [lang, dict] of Object.entries(DICTS)) {
        try {
          const dispose = locale.register(NS, lang, dict)
          if (typeof dispose === 'function') disposers.push(dispose)
        } catch {
          // 语言 id 不被这个版本接受时保留内置中文表
        }
      }
      try {
        const bound = locale.bind(NS)
        if (typeof bound === 'function') {
          translate = (key, params) => {
            let text
            try {
              text = bound(key)
            } catch {
              text = ''
            }
            return formatText(text || ZH[key] || key, params)
          }
        }
      } catch {
        // bind 失败就用内置中文表
      }
      return () => {
        for (const dispose of disposers) {
          try {
            dispose()
          } catch {
            // 卸载阶段清理失败不影响后续
          }
        }
      }
    }

    function insertStyles() {
      const tag = document.createElement('style')
      tag.setAttribute('data-dsh-sleuth-copilot', '1')
      tag.textContent = CSS
      document.head.appendChild(tag)
      return () => {
        try {
          tag.remove()
        } catch {
          // 页面卸载时 head 可能已被清空
        }
      }
    }

    function makeRpc(ctx) {
      const connection = ctx.get('connection')
      return async function rpc(endpoint, payload) {
        if (connection === undefined || connection.rpc === undefined || typeof connection.rpc.call !== 'function') {
          throw new Error('connection 服务不可用')
        }
        const outer = await connection.rpc.call(CHANNEL, String(endpoint), payload === undefined ? {} : payload)
        if (outer === undefined || outer.ok !== true) {
          const failure = outer && outer.error
          throw new Error(failure && failure.message ? failure.message : 'RPC 失败')
        }
        return outer.value
      }
    }

    function makeOpenSession(ctx) {
      return async function openSession(id) {
        const target = String(id || '')
        if (!target) return { ok: false, reason: '没有会话号' }
        const candidates = []
        try {
          const sessions = ctx.get('sessions')
          if (sessions) candidates.push(sessions)
        } catch {
          // 没有这个服务就只试下一个
        }
        try {
          const uiWorkspace = ctx.get('uiWorkspace')
          if (uiWorkspace) candidates.push(uiWorkspace)
        } catch {
          // 同上
        }
        for (const host of candidates) {
          for (const name of ['openSession', 'open', 'select', 'selectSession', 'show', 'activate']) {
            let fn
            try {
              fn = host[name]
            } catch {
              continue
            }
            if (typeof fn !== 'function') continue
            try {
              fn.call(host, target)
              return { ok: true }
            } catch (error) {
              const why = String((error && error.message) || error)
              if (!/unknown session|not listed|不存在/i.test(why)) continue
              try {
                if (candidates[0] && typeof candidates[0].refresh === 'function') await candidates[0].refresh()
              } catch {
                // 刷新失败就按原样报
              }
              try {
                fn.call(host, target)
                return { ok: true }
              } catch (second) {
                return { ok: false, reason: '拉过最新列表仍然没有这一条：' + String((second && second.message) || second) }
              }
            }
          }
        }
        return { ok: false, reason: '没有可用的打开会话接口' }
      }
    }

    function withInputActions(Component) {
      return function SurfaceWithInputs(props) {
        const inputActions = props && props.inputActions
        React.useEffect(() => {
          if (!inputActions) return undefined
          surfaceInputs.push(inputActions)
          return () => {
            const index = surfaceInputs.indexOf(inputActions)
            if (index >= 0) surfaceInputs.splice(index, 1)
          }
        }, [inputActions])
        return h(Component, props)
      }
    }

    return {
      // 显式声明用到的服务：cordis 只对声明过的服务名建键，未声明的 ctx.get 返回 undefined。
      // sessions / uiWorkspace 用于「切到该诊断的会话」，与面板包同一条契约。
      inject: ['connection', 'slots', 'sessions', 'uiWorkspace'],
      apply(ctx) {
        const slots = ctx.get('slots')
        if (slots === undefined) return
        rpcCall = makeRpc(ctx)
        openSessionImpl = makeOpenSession(ctx)
        ctx.effect(() => registerLocale(ctx), 'sleuth-copilot: locale')
        ctx.effect(() => insertStyles(), 'sleuth-copilot: styles')

        const Dock = withInputActions(makeDock())
        const Toolbar = withInputActions(ToolbarButton)

        ctx.effect(() => slots.inject('conversation.input.dock', () => slots.register({
          name: 'conversation.input.dock',
          id: 'sleuth-copilot',
          order: 55,
        }, Dock)), 'sleuth-copilot: input dock')

        ctx.effect(() => slots.inject('conversation.input.right', () => slots.register({
          name: 'conversation.input.right',
          id: 'sleuth-copilot-toolbar',
          order: 5,
        }, Toolbar)), 'sleuth-copilot: input toolbar')

        ctx.effect(() => slots.inject('shell.overlay', () => slots.register({
          name: 'shell.overlay',
          id: 'sleuth-copilot-palette',
          order: 60,
        }, Palette)), 'sleuth-copilot: palette')
      },
    }
  },
})
