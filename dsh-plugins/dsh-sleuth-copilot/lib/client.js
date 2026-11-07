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
    const PLUGIN_VERSION = '0.17.0'
    const POLL_MS = 10000
    // 查合入的逐条进度：主 RPC 在跑时每 500 ms 问一次进度端点；连续 3 次失败就静默停轮询，
    // 不打断整批（最终结果仍以主 RPC 为准）。
    const PR_PROGRESS_POLL_MS = 500
    const PR_PROGRESS_MAX_FAILURES = 3
    const PREFS_KEY = 'dsh-sleuth-copilot.prefs.v2'
    const FILTER_KEYS = ['all', 'open', 'pending', 'sediment']
    // PR 台账允许的状态（与 scripts/pr_status.py 的 STATES 一致）。
    const PR_STATE_KEYS = ['open', 'merged', 'closed', 'unknown']
    // 详情抬头默认收起成四行；「展开全文」优先看实际溢出（scrollHeight > clientHeight）。
    // 离线渲染没有布局引擎，拿不到尺寸时退回这个字数近似：四行在 400–510px 列宽下约 110–150 字，
    // 取小值，宁可多给一个入口也不把内容藏起来。
    const LEDE_TOGGLE_MIN = 110

    // ── 文案 ────────────────────────────────────────────────────────────────
    const ZH = {
      'region': '诊断状态条',
      'scope.bound': '本会话',
      'scope.boundResume': '本会话（续接）',
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
      'action.collapseShort': '收起',
      'action.keepOpen': '展开后常驻',
      'action.keepOpenOff': '取消常驻',
      'hint.keepOn': '状态条展开后常驻：点状态条外不再收起。',
      'hint.keepOff': '状态条不再常驻：点状态条外收起。',
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
      'chip.reportReview': '报告待复核',
      'chip.upstream': '等上游',
      'chip.stale': '数据可能过期',
      'title.noSummary': '（未写摘要）',
      'chip.pinned': '已固定',
      'section.summary': '问题背景',
      'label.waiting': '在等',
      'lede.expand': '展开全文',
      'lede.collapse': '收起全文',
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
      'empty.body': '本会话还没有诊断轨迹。跑一次 /diagnose 后，这一行会显示本会话的第几步、在等什么、下一步做什么。',
      'empty.collapsed': '本会话还没有诊断轨迹',
      'empty.meaning': '数据来自检出里的 traces/；状态判据在 scripts/_trace_state.py。',
      'error.reopen': '数据来自 traces/；判据在 scripts/_trace_state.py。',
      'hint.draft': '已填入输入框，按 Enter 发送。',
      'hint.copied': '已复制。',
      'hint.copiedIssue': 'issue 文本已复制。',
      'hint.copyFailed': '这个界面不允许写剪贴板，请手动选择文本。',
      'hint.stale': '状态取不到最新数据，显示的是上次成功读取的内容；点「刷新」重试。',
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
      'action.correctEnding': '改收尾方式',
      'action.backfillEnding': '补记收尾方式',
      'form.target': '改成',
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
      'section.upstream': '上游查证',
      'section.sessions': '会话归属',
      'sessions.origin': '原始会话',
      'sessions.resumed': '续接会话',
      'sessions.current': '当前会话',
      'sessions.missing': '未记会话号（trace 的 harness_session 为空）',
      'sessions.hint': '跨机或旧环境的会话可能切不过去；归属仍保留。',
      'action.copyLinkCommand': '复制补写命令',
      'action.openOrigin': '切到原始会话',
      'action.openResumed': '切到上次续接会话',
      'hint.sessionOpened': '已切到该会话。',
      'hint.sessionRemote': '这个会话不在本机（旧环境或交接包），只能看归属。',
      'hint.sessionService': '当前界面没有切会话的接口。',
      'hint.sessionNoId': '没有会话号，补写后再试。',
      'section.materials': '在等材料',
      'section.timeline': '步骤时间线',
      'materials.hint': '来自 trace 的缺失记录；拿到后贴回会话，或带着这份清单续接。',
      'action.copyMaterials': '复制清单',
      'action.materialResume': '填入续接指令',
      'action.loadTimeline': '展开步骤',
      'action.hideTimeline': '收起步骤',
      'timeline.loading': '正在读步骤…',
      'timeline.none': '这条轨迹还没有步骤记录。',
      'timeline.role.user': '用户',
      'timeline.role.agent': '助手',
      'timeline.role.resume': '续接',
      'copy.issue': '复制为 issue 文本',
      'search.placeholder': '搜索单号 / case / 关键词',
      'cmd.placeholder': '输入命令…',
      'cmd.hint': '↑↓ 选择 · Enter 执行 · Esc 关闭',
      'cmd.empty': '没有匹配的命令',
      'command.primary': '主操作',
      'hint.refreshed': '已刷新。',
      'section.checklist': '收尾清单',
      'section.evidence': '证据与沉淀',
      'section.history': '写入历史',
      'check.report': '人读报告',
      'check.feedback': '回报结果',
      'check.sediment': '沉淀',
      'check.handoff': '交接包',
      'check.actionReport': '生成报告指令',
      'check.actionFeedback': '填回报指令',
      'check.actionSediment': '填沉淀指令',
      'check.actionHandoff': '填交接指令',
      'state.done': '完成',
      'state.pending': '待办',
      'state.na': '不需要',
      'state.optional': '可随时导出',
      'action.viewReport': '看报告',
      'action.hideReport': '收起报告',
      'action.copyPath': '复制路径',
      'action.undoClose': '撤销上次收尾',
      'action.sedimentGeneric': '生成沉淀指令',
      'upstream.anchors': '锚点',
      'upstream.lastVerified': '上次查证',
      'upstream.source': '依据',
      'upstream.none': '这单没有上游锚点',
      'upstream.ready': 'gh 已就绪',
      'upstream.notReady': '环境未就绪',
      'history.none': '还没有写入记录',
      'history.transition': '状态',
      'history.report': '回报',
      'history.review': '复核',
      'report.loading': '正在读报告…',
      'report.none': '这单还没有人读报告。',
      'evidence.none': '本次没记证据文件',
      'candidates.none': '没有沉淀候选',
      'shortcut.open': '{keys} 打开总览',
      'hint.undo': '重新打开；只清掉收尾方式（ending），收尾时间与停止原因保留。',
      'hint.reopened': '已撤销上一次收尾。',
      'hint.readonly': '当前会话是只读档位，改不了状态。',
      'hint.copyPath': '路径已复制。',
      'hint.reportOpen': '报告已打开。',

      'report.from_report': '按报告的修复解决',
      'report.other_way': '换别的方法解决',
      'report.partial': '部分解决',
      'report.resultNone': '没解决',
      'close.resolved': '已定位（根因明确）',
      'close.escalated': '转交他人跟进',
      'close.archived': '不再跟进',
      'reopen': '重新打开',
      'sediment.none': '未沉淀',
      'sediment.submitted': '已交草稿',
      'sediment.noteNoCandidate': '未标候选，按 trace 起草',
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
      'form.duplicateOfHint': '写成 case:<编号> 或 session:<单号>，脚本只认这两种前缀',
      'form.ending': '收尾方式',
      'form.summary': '问题背景（写回收尾记录）',
      'form.summaryHint': '一句话说清问题与结论；收尾会把它写进 trace 顶层 summary',
      'form.state': '沉淀状态',
      'form.caseId': 'case 编号（可选）',
      'form.caseIdHint': '例如 VLLM-ASC-11312；升格后填',
      'form.yes': '是',
      'form.no': '否',
      'form.submit': '提交',
      'form.cancel': '取消',
      'form.busy': '正在写…',
      'form.required': '请先填：{fields}',
      'form.pick': '请选择',
      'form.feedbackFirst': '这单命中 case 但还没有现场回报：先去「回报结果」，再回来收尾。',
      'write.disabled': '当前会话没有写权限',
      'write.done': '已记录：{from} → {to}',
      'write.doneSimple': '已记录',
      'write.doneSediment': '沉淀状态改为：{state}',
      'write.stateChanged': '这单在别处被改过，已刷新，请重试。',
      'write.failed': '写入失败：{message}',
      'write.requirements': '（缺：{fields}）',
      'write.permissionHint': '面板写不进这一单（沙箱或文件权限拒绝）。可以生成一条指令，交给会话里的 agent 用脚本写；不会自动发送。',
      'write.permissionRetry': '生成指令（填入输入框）',
      'palette.title': '诊断总览',
      'palette.filterLabel': '筛选',
      'palette.filter.all': '全部',
      'palette.filter.open': '进行中',
      'palette.filter.pending': '待回报',
      'palette.filter.sediment': '可沉淀',
      'palette.empty': '没有符合条件的诊断。',
      'palette.loading': '正在读 traces/…',
      'palette.unavailable': '读不到 traces/：{message}',
      'palette.count': '共 {n} 单',
      'palette.close': '关闭诊断总览',
      'tool.title': '诊断总览',
      'tool.pending': '{n} 单待回报',
      // ── 沉淀队列（v1）──────────────────────────────────────────────
      'palette.view.diagnosis': '诊断',
      'palette.view.sediment': '沉淀',
      'palette.sedimentTitle': '沉淀队列',
      'sediment.loading': '正在读 inbox 与评估状态…',
      'sediment.refreshing': '刷新中…',
      'sediment.error': '读不到沉淀队列：{message}',
      'sediment.empty': '队列已清空',
      'sediment.emptyHint': '诊断收尾时点「沉淀为 case」，草稿会进入这里等周批。',
      'sediment.goDiagnosis': '去诊断',
      'sediment.history': '最近完成',
      'sediment.target.pick': '有多个远端，先选一个',
      'sediment.primary.prBatch': '生成提 PR 指令（本批 {n} 份）',
      'sediment.prState.open': '待合入',
      'sediment.prState.merged': '已合入',
      'sediment.prState.closed': '已关闭',
      'sediment.prState.unknown': '未确认',
      'sediment.prSource.platform': '平台查询',
      'sediment.prSource.manual': '手动确认',
      'sediment.prSource.ledger': '台账',
      'sediment.detail.lastChecked': '上次查证',
      'sediment.detail.closedDraft': '草稿不在 inbox；这条记录来自收尾日志（close-log）或 PR 台账。',
      'sediment.checkFailed': '查合入没有全部成功；查不到的行记为「未确认」，也可以手动改状态。',
      'sediment.checkFailedWith': '查合入没有全部成功；查不到的行记为「未确认」，也可以手动改状态（原因：{reason}）。',
      'sediment.checkDoneOne': '查合入完成：{pr} · {state}',
      'sediment.checkFailedOne': '查合入没成功；也可以手动改状态（原因：{reason}）。',
      'sediment.checkDone': '查合入完成：{n} 条已更新',
      'sediment.checkNone': '没有待查的 PR',
      'sediment.undo.action': '撤销沉淀',
      'sediment.undo.title': '撤销这次沉淀',
      'sediment.undo.sub': '面板不删草稿。这条指令填进输入框，由会话里的 agent 执行。',
      'sediment.undo.hint': '草稿还在 inbox、没有 PR 记录、来源 trace 没升格时才能撤销',
      'sediment.manualState': '手动改状态',
      'sediment.manualTitle': '手动改 PR 状态',
      'sediment.prompt.sub': '预览将填入输入框的指令',
      'sediment.manualSub': '平台查不到时按人工确认写 PR 台账，来源记为「手动确认」；下次查合入仍以平台结果为准。',
      'sediment.manualDone': 'PR 状态已手动记为：{state}',
      'sediment.primary.checkAll': '查全部合入状态',
      'sediment.checking': '查合入中',
      'sediment.checkingProgress': '查合入中 {n}/{m}',
      'sediment.pushTarget': '推送目标 {label}',
      'sediment.checkError.E_NO_ADAPTER': '没有适配器',
      'sediment.checkError.E_NO_AUTH': '没配 token',
      'sediment.checkError.E_FETCH': '查询失败',
      'sediment.checkError.E_PLATFORM': '平台适配器不可用',
      'sediment.checkError.E_NOT_FOUND': '台账里没有这条 PR',
      'sediment.checkError.E_LEDGER': '台账写入失败',
      'sediment.checkError.unknown': '未知原因',
      'sediment.prompt.fallbackTitle': '写不进台账时的指令',
      'sediment.fallback.targetTitle': '写推送目标时的指令',
      'sediment.fallback.sub': '面板写不进本地文件；这条指令填进输入框后交给会话里的 agent 执行，不会自动发送。',
      'sediment.fallback.checked': '平台已经查到：{state}；这次没写进 PR 台账。',
      'sediment.fallback.checkedMany': '平台已经查到 {n} 条：{list}；这次没写进 PR 台账。',
      'sediment.fallback.ledgerLede': '面板没把结果写进 PR 台账。',
      'sediment.fallback.settingsLede': '面板没把推送目标写进本地配置。',
      'sediment.fallback.policyLede': '面板的子进程被拒绝。',
      'sediment.fallback.reason': '原因：{reason}',
      'sediment.fallback.command': '请在仓库根目录执行：',
      'sediment.fallback.ledger': 'PR 台账：{path}',
      'sediment.fallback.settings': '配置文件：{path}',
      'sediment.fallback.repairFile': '这条命令也报权限错误时，先确认没有残留的 python 进程，再删掉该文件旁的 .lock 文件重试。',
      'sediment.fallback.repairFileAcl': '仍不行就看它的只读属性与访问控制列表（ACL）。',
      'sediment.fallback.repairPolicy': '这是会话权限模式或沙箱允许写的范围，不是文件本身；同样的命令在可写的会话 shell 里通常能过，若也报权限错误再按文件权限排查。',
      'sediment.history.archived': '已归档',
      'sediment.assessedUnknown': '未评估',
      'sediment.detail.assessmentCleared': '评估状态文件已清理',
      'sediment.filter.all': '全部',
      'sediment.filter.decision': '待决定',
      'sediment.filter.pr': '待提 PR',
      'sediment.filter.check': '待合入',
      'sediment.filter.rerun': '需重跑',
      'sediment.group.groom': '待继续 groom',
      'sediment.group.pr': '待提 PR',
      'sediment.group.check': '待合入与收尾',
      'sediment.group.other': '其它',
      'sediment.age': '{n} 天',
      'sediment.ageUnknown': '时间未记录',
      'sediment.overdue': '超过 14 天建议线',
      'sediment.batch.total': '{n} 条事项',
      'sediment.batch.oldest': '最老 {n} 天',
      'sediment.batch.none': '没有下一步',
      'diag.batch.count': '可沉淀 {n} 单',
      'diag.batch.scope': '范围 = 当前筛选（含搜索词）',
      'diag.batch.fill': '生成批量沉淀指令',
      'diag.batch.sub': '范围 = 当前筛选的 {n} 单；只生成指令，不直接写 trace',
      'diag.batch.flow': '流程：先按 sediment_batch.py --json 分组与复核，再逐单起草、逐单回写。',
      'diag.batch.boundary': '边界：只写 sedimented 与 updated_at，不改 status、不改 feedback.outcome，也不改知识库。',
      'diag.batch.search': '含搜索词「{q}」',
      'diag.batch.readonly': '只读档位：指令可复制到可写会话执行，回写会被拒绝。',
      'sediment.primary.groom': '继续 groom',
      'sediment.primary.pr': '生成提 PR 指令',
      'sediment.primary.check': '查合入状态',
      'sediment.primary.close': '生成收尾指令',
      'sediment.secondary.pr': '提 PR（{n}）',
      'sediment.target': '目标',
      'sediment.targetChange': '换',
      'sediment.targetNone': '还没有选目标',
      'sediment.targetHint': '已记住上次选择；远端用途不做预设',
      'sediment.prompt.flow': '流程：按 skill 第 5 步执行；界面只给批次与边界。',
      'sediment.prompt.boundary': '边界：先落盘并跑升格检查；recheck 不通过就停；合入前不要跑 close / cleanup。',
      'sediment.prompt.details': '展开命令细节（按平台）',
      'sediment.prompt.collapse': '收起命令细节',
      'sediment.prompt.copy': '复制',
      'sediment.prompt.fill': '填入输入框',
      'sediment.prompt.cancel': '取消',
      'sediment.prompt.default': '默认短指令；命令细节可展开。',
      'sediment.prompt.empty': '没有可生成的指令。',
      'sediment.detail.assessment': '评估',
      'sediment.detail.progress': '沉淀进度',
      'sediment.detail.openQueue': '打开沉淀队列',
      'sediment.detail.decision': '人决定',
      'sediment.detail.decisionValue': '决定',
      'sediment.batch.next': '下一步',
      'sediment.dock.missingDraft': '已交草稿 · 未找到草稿',
      'sediment.detail.promotion': '落点与 PR',
      'sediment.detail.source': '来源诊断',
      'sediment.detail.suggestion': '建议',
      'sediment.detail.rationale': '依据',
      'sediment.detail.assessed': '评估版本',
      'sediment.detail.review': '复核项',
      'sediment.detail.candidate': '候选',
      'sediment.detail.noDecision': '还没有人决定',
      'sediment.detail.noPr': '未记录',
      'sediment.detail.landingPending': '合入后落库',
      'sediment.detail.pr': 'PR',
      'sediment.detail.case': 'case',
      'sediment.table.draft': '草稿',
      'sediment.table.decision': '决定',
      'sediment.detail.postmortem': 'postmortem',
      'sediment.detail.stale': '需重跑：{reason}',
      'sediment.detail.target': '比较基准',
      'sediment.detail.targetWarnings': '目标提示',
      'sediment.targetState.ref_missing': '目标基准不可用',
      'sediment.targetState.target_behind': '目标落后',
      'sediment.targetState.not_comparable': '无法比较',
      'sediment.targetState.ref_changed': '目标已变',
      'sediment.detail.mismatch.stale_trace': 'trace 停在已交草稿，但知识库已有 case；生成回写指令。',
      'sediment.detail.mismatch.missing_draft': 'trace 说已交草稿，但 inbox 与 .done 都找不到。',
      'sediment.detail.mismatch.missing_case': 'trace 说已升格，但知识库里没有这条 case。',
      'sediment.detail.mismatch.draft_left_behind': 'trace 说已升格，但草稿还在 inbox：升格后没有出队。',
      'sediment.detail.writeback': '生成回写指令',
      'sediment.detail.closeDraft': '生成收尾指令',
      'sediment.target.title': '提 PR 到哪个远端？',
      'sediment.target.sub': '不同部署的远端用途不同；系统只列事实，选择会记住。',
      'sediment.target.base': 'base 分支',
      'sediment.target.save': '保存并生成指令',
      'sediment.target.noAdapter': '无适配器',
      'sediment.target.token': '需配 token',
      'sediment.target.required': '先选 PR 目标',
      'sediment.target.empty': '没有可选的远端。',
      'sediment.refresh': '刷新',
      'sediment.open': '打开沉淀队列',
      'sediment.stepper.draft': '草稿已交',
      'sediment.stepper.assessed': '已评估',
      'sediment.stepper.decided': '已决定',
      'sediment.stepper.pr': '已提 PR',
      'sediment.stepper.promoted': '已升格',
      'sediment.stepper.unknown': '未记录',
      'sediment.stepper.pending': '待处理',
      'sediment.check': '查合入状态',
      'sediment.check.readonly': '只读档位：生成查证指令',
      'sediment.markMerged': '标记已合入',
      'sediment.noTarget': '推送目标未设置',
      'sediment.targetNote': '远端用途不做预设',
      'none': '未记录',
    }
    const EN = {
      'region': 'Diagnosis status bar',
      'scope.bound': 'this session',
      'scope.boundResume': 'this session (resumed)',
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
      'action.collapseShort': 'Collapse',
      'action.keepOpen': 'Keep expanded',
      'action.keepOpenOff': 'Stop keeping expanded',
      'hint.keepOn': 'Status bar stays expanded: clicking outside no longer collapses it.',
      'hint.keepOff': 'Status bar no longer stays expanded: clicking outside collapses it.',
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
      'chip.reportReview': 'report to review',
      'chip.upstream': 'waiting upstream',
      'chip.stale': 'data may be stale',
      'title.noSummary': '(no summary)',
      'chip.pinned': 'Pinned',
      'section.summary': 'Background',
      'label.waiting': 'Waiting',
      'lede.expand': 'Show full text',
      'lede.collapse': 'Show less',
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
      'empty.body': 'No diagnosis trace in this session yet. Run /diagnose and this bar shows the step, what it waits for, and what comes next.',
      'empty.collapsed': 'No diagnosis trace in this session yet',
      'empty.meaning': 'Data comes from traces/; status rules live in scripts/_trace_state.py.',
      'error.reopen': 'Data comes from traces/; rules live in scripts/_trace_state.py.',
      'hint.draft': 'Inserted into the composer — press Enter to send.',
      'hint.copied': 'Copied.',
      'hint.copiedIssue': 'Issue text copied.',
      'hint.copyFailed': 'Clipboard is unavailable here; select the text manually.',
      'hint.stale': 'Cannot read fresh state; showing the last successful read. Use Refresh to retry.',
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
      'action.review': 'Review the outcome',
      'action.feedbackForm': 'Report outcome…',
      'action.sedimentState': 'Sediment state…',
      'action.correctEnding': 'Correct the ending',
      'action.backfillEnding': 'Backfill the ending',
      'form.target': 'Change to',
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
      'section.upstream': 'Upstream',
      'section.sessions': 'Session attribution',
      'sessions.origin': 'Origin session',
      'sessions.resumed': 'Resumed in',
      'sessions.current': 'current session',
      'sessions.missing': 'No session id (harness_session is empty)',
      'sessions.hint': 'A session from another machine or an old environment may not open; its attribution stays.',
      'action.copyLinkCommand': 'Copy write-back command',
      'action.openOrigin': 'Open origin session',
      'action.openResumed': 'Open the last resumed session',
      'hint.sessionOpened': 'Switched to that session.',
      'hint.sessionRemote': 'That session is not on this machine (old environment or handoff package); only its attribution is available.',
      'hint.sessionService': 'This interface has no session-switch hook.',
      'hint.sessionNoId': 'No session id; write one back and retry.',
      'section.materials': 'Waiting for material',
      'section.timeline': 'Step timeline',
      'materials.hint': 'Recorded gaps from the trace; paste the missing pieces back, or resume with this list.',
      'action.copyMaterials': 'Copy list',
      'action.materialResume': 'Fill resume command',
      'action.loadTimeline': 'Show steps',
      'action.hideTimeline': 'Hide steps',
      'timeline.loading': 'Reading steps…',
      'timeline.none': 'No step records yet.',
      'timeline.role.user': 'user',
      'timeline.role.agent': 'assistant',
      'timeline.role.resume': 'resume',
      'copy.issue': 'Copy as issue text',
      'search.placeholder': 'Search id / case / keyword',
      'cmd.placeholder': 'Type a command…',
      'cmd.hint': '↑↓ select · Enter run · Esc close',
      'cmd.empty': 'No matching command',
      'command.primary': 'Primary',
      'hint.refreshed': 'Refreshed.',
      'section.checklist': 'Close-out checklist',
      'section.evidence': 'Evidence and candidates',
      'section.history': 'Write history',
      'check.report': 'Report',
      'check.feedback': 'Outcome',
      'check.sediment': 'Sediment',
      'check.handoff': 'Handoff package',
      'check.actionReport': 'Generate report command',
      'check.actionFeedback': 'Fill outcome command',
      'check.actionSediment': 'Fill sediment command',
      'check.actionHandoff': 'Fill handoff command',
      'state.done': 'done',
      'state.pending': 'pending',
      'state.na': 'not needed',
      'state.optional': 'export anytime',
      'action.viewReport': 'View report',
      'action.hideReport': 'Hide report',
      'action.copyPath': 'Copy path',
      'action.undoClose': 'Undo the last close',
      'action.sedimentGeneric': 'Generate sediment command',
      'upstream.anchors': 'Anchors',
      'upstream.lastVerified': 'Last verified',
      'upstream.source': 'Basis',
      'upstream.none': 'No upstream anchor',
      'upstream.ready': 'gh ready',
      'upstream.notReady': 'environment not ready',
      'history.none': 'No write history yet',
      'history.transition': 'status',
      'history.report': 'outcome',
      'history.review': 'review',
      'report.loading': 'Reading the report…',
      'report.none': 'No report yet.',
      'evidence.none': 'No evidence files recorded',
      'candidates.none': 'No sediment candidates',
      'shortcut.open': '{keys} opens the overview',
      'hint.undo': 'Reopened; only the closing kind (ending) is cleared; the close time and stop reason stay.',
      'hint.reopened': 'The last close was undone.',
      'hint.readonly': 'This session is read-only; state cannot be changed.',
      'hint.copyPath': 'Path copied.',
      'hint.reportOpen': 'Report opened.',

      'report.from_report': 'Fixed by the report',
      'report.other_way': 'Fixed another way',
      'report.partial': 'Partially fixed',
      'report.resultNone': 'Not fixed',
      'close.resolved': 'Resolved (root cause known)',
      'close.escalated': 'Hand off',
      'close.archived': 'Stop following',
      'reopen': 'Reopen',
      'sediment.none': 'Not sedimented',
      'sediment.submitted': 'Draft submitted',
      'sediment.noteNoCandidate': 'No candidates recorded; draft from the trace',
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
      'form.duplicateOfHint': 'Use case:<id> or session:<session id>; the script accepts only these prefixes',
      'form.ending': 'Ending',
      'form.summary': 'Problem summary (written to the close record)',
      'form.summaryHint': 'One line with the problem and conclusion; the close writes it to the top-level summary',
      'form.state': 'Sediment state',
      'form.caseId': 'Case id (optional)',
      'form.caseIdHint': 'e.g. VLLM-ASC-11312, after promotion',
      'form.yes': 'Yes',
      'form.no': 'No',
      'form.submit': 'Submit',
      'form.cancel': 'Cancel',
      'form.busy': 'Writing…',
      'form.required': 'Fill first: {fields}',
      'form.pick': 'Select…',
      'form.feedbackFirst': 'This case is a KB hit without a field outcome yet: report the outcome first, then close.',
      'write.disabled': 'This session has no write access',
      'write.done': 'Recorded: {from} → {to}',
      'write.doneSimple': 'Recorded',
      'write.doneSediment': 'Sediment state set to {state}',
      'write.stateChanged': 'The trace changed elsewhere; refreshed, try again.',
      'write.failed': 'Write failed: {message}',
      'write.requirements': ' (missing: {fields})',
      'write.permissionHint': 'The panel cannot write this trace (refused by the sandbox or file permissions). Generate a command so the agent in this session can write it with the script; nothing is sent automatically.',
      'write.permissionRetry': 'Generate a command (fill input)',
      'palette.title': 'Diagnosis overview',
      'palette.filterLabel': 'Filter',
      'palette.filter.all': 'All',
      'palette.filter.open': 'Open',
      'palette.filter.pending': 'Outcome pending',
      'palette.filter.sediment': 'To sediment',
      'palette.empty': 'No diagnosis matches.',
      'palette.loading': 'Reading traces/…',
      'palette.unavailable': 'Cannot read traces/: {message}',
      'palette.count': '{n} total',
      'palette.close': 'Close the diagnosis overview',
      'tool.title': 'Diagnosis overview',
      'tool.pending': '{n} pending outcomes',
      // ── Sediment queue (v1) ────────────────────────────────────────
      'palette.view.diagnosis': 'Diagnosis',
      'palette.view.sediment': 'Sediment',
      'palette.sedimentTitle': 'Sediment queue',
      'sediment.loading': 'Reading inbox and assessments…',
      'sediment.refreshing': 'Refreshing…',
      'sediment.error': 'Cannot read the sediment queue: {message}',
      'sediment.empty': 'Queue is clear',
      'sediment.emptyHint': 'Use "Draft a case" at diagnosis wrap-up; drafts wait here for the weekly batch.',
      'sediment.goDiagnosis': 'Go to diagnosis',
      'sediment.history': 'Recently completed',
      'sediment.target.pick': 'Multiple remotes; choose one first',
      'sediment.primary.prBatch': 'Generate PR prompt ({n} drafts)',
      'sediment.prState.open': 'Awaiting merge',
      'sediment.prState.merged': 'Merged',
      'sediment.prState.closed': 'Closed',
      'sediment.prState.unknown': 'Unconfirmed',
      'sediment.prSource.platform': 'platform check',
      'sediment.prSource.manual': 'manual',
      'sediment.prSource.ledger': 'ledger',
      'sediment.detail.lastChecked': 'last checked',
      'sediment.detail.closedDraft': 'Draft is not in the inbox; this row comes from close-log or the PR ledger.',
      'sediment.checkFailed': 'Merge check did not complete. Rows that could not be checked are marked unconfirmed; you can also set the state manually.',
      'sediment.checkFailedWith': 'Merge check did not complete. Rows that could not be checked are marked unconfirmed; you can also set the state manually (reason: {reason}).',
      'sediment.checkDoneOne': 'Merge check done: {pr} · {state}',
      'sediment.checkFailedOne': 'Merge check failed; you can also set the state manually (reason: {reason}).',
      'sediment.checkDone': 'Merge check done: {n} updated',
      'sediment.checkNone': 'No PRs to check',
      'sediment.undo.action': 'Undo sediment',
      'sediment.undo.title': 'Undo this sediment',
      'sediment.undo.sub': 'The panel does not delete drafts. Fill this instruction into the composer and the agent in this session will run it.',
      'sediment.undo.hint': 'Only available while the draft is still in the inbox, has no PR, and its trace is not promoted',
      'sediment.manualState': 'Set state manually',
      'sediment.manualTitle': 'Set PR state manually',
      'sediment.prompt.sub': 'Preview of the prompt to fill the composer',
      'sediment.manualSub': 'Records a human-confirmed state when the platform check fails. The source is stored as manual; the next check still uses the platform.',
      'sediment.manualDone': 'PR state recorded manually as {state}',
      'sediment.primary.checkAll': 'Check all merge states',
      'sediment.checking': 'Checking',
      'sediment.checkingProgress': 'Checking merge states {n}/{m}',
      'sediment.pushTarget': 'Push target {label}',
      'sediment.checkError.E_NO_ADAPTER': 'no adapter',
      'sediment.checkError.E_NO_AUTH': 'no token',
      'sediment.checkError.E_FETCH': 'fetch failed',
      'sediment.checkError.E_PLATFORM': 'platform adapter unavailable',
      'sediment.checkError.E_NOT_FOUND': 'no PR ledger entry',
      'sediment.checkError.E_LEDGER': 'ledger write failed',
      'sediment.checkError.unknown': 'unknown reason',
      'sediment.prompt.fallbackTitle': 'Command for a refused ledger write',
      'sediment.fallback.targetTitle': 'Command for a refused target write',
      'sediment.fallback.sub': 'The panel cannot write the local file; fill this command into the composer so the agent in this session can run it. Nothing is sent automatically.',
      'sediment.fallback.checked': 'The platform reported: {state}; this check was not written to the PR ledger.',
      'sediment.fallback.checkedMany': 'The platform reported {n} states: {list}; this check was not written to the PR ledger.',
      'sediment.fallback.ledgerLede': 'The panel did not write the result to the PR ledger.',
      'sediment.fallback.settingsLede': 'The panel did not write the push target to the local config.',
      'sediment.fallback.policyLede': 'The panel write subprocess was refused.',
      'sediment.fallback.reason': 'Reason: {reason}',
      'sediment.fallback.command': 'Run this from the repo root:',
      'sediment.fallback.ledger': 'PR ledger: {path}',
      'sediment.fallback.settings': 'Config file: {path}',
      'sediment.fallback.repairFile': 'If the command also reports a permission error, first check for a leftover python process, then delete the .lock file next to it and retry.',
      'sediment.fallback.repairFileAcl': 'If it still fails, inspect its read-only attribute and access control list (ACL).',
      'sediment.fallback.repairPolicy': 'This is a session permission mode or sandbox writable-range decision, not the file itself; the same command usually works in a writable session shell. If it also reports a permission error, then inspect the file permissions.',
      'sediment.history.archived': 'archived',
      'sediment.assessedUnknown': 'not assessed',
      'sediment.detail.assessmentCleared': 'assessment file cleared',
      'sediment.filter.all': 'All',
      'sediment.filter.decision': 'To decide',
      'sediment.filter.pr': 'To PR',
      'sediment.filter.check': 'Awaiting merge',
      'sediment.filter.rerun': 'Rerun',
      'sediment.group.groom': 'Continue groom',
      'sediment.group.pr': 'To open PR',
      'sediment.group.check': 'Merge and close',
      'sediment.group.other': 'Other',
      'sediment.age': '{n}d',
      'sediment.ageUnknown': 'time unknown',
      'sediment.overdue': 'past the 14-day line',
      'sediment.batch.total': '{n} items',
      'sediment.batch.oldest': 'oldest {n}d',
      'sediment.batch.none': 'nothing next',
      'diag.batch.count': '{n} to sediment',
      'diag.batch.scope': 'scope = current filter (including search)',
      'diag.batch.fill': 'Generate batch sediment prompt',
      'diag.batch.sub': 'Scope = {n} sessions under the current filter; generates an instruction, writes no trace',
      'diag.batch.flow': 'Flow: group and re-check with sediment_batch.py --json, then draft and write back per session.',
      'diag.batch.boundary': 'Boundary: only sedimented and updated_at change; status, feedback.outcome, and the knowledge base stay untouched.',
      'diag.batch.search': 'search: {q}',
      'diag.batch.readonly': 'Read-only: copy the instruction to a writable session; write-back is rejected here.',
      'sediment.primary.groom': 'Continue groom',
      'sediment.primary.pr': 'Generate PR prompt',
      'sediment.primary.check': 'Check merge status',
      'sediment.primary.close': 'Generate close prompt',
      'sediment.secondary.pr': 'Open PR ({n})',
      'sediment.target': 'Target',
      'sediment.targetChange': 'Change',
      'sediment.targetNone': 'No target yet',
      'sediment.targetHint': 'Remembered from last time; remote roles are not assumed',
      'sediment.prompt.flow': 'Flow: follow step 5 of the skill; the UI only supplies the batch and the boundary.',
      'sediment.prompt.boundary': 'Boundary: land the draft and run the gate first; stop if recheck fails; do not run close / cleanup before merge.',
      'sediment.prompt.details': 'Show command details (by platform)',
      'sediment.prompt.collapse': 'Hide command details',
      'sediment.prompt.copy': 'Copy',
      'sediment.prompt.fill': 'Fill composer',
      'sediment.prompt.cancel': 'Cancel',
      'sediment.prompt.default': 'Short prompt by default; details can expand.',
      'sediment.prompt.empty': 'No prompt available.',
      'sediment.detail.assessment': 'Assessment',
      'sediment.detail.progress': 'Sediment progress',
      'sediment.detail.openQueue': 'Open sediment queue',
      'sediment.detail.decision': 'Human decision',
      'sediment.detail.decisionValue': 'Decision',
      'sediment.batch.next': 'next',
      'sediment.dock.missingDraft': 'draft submitted, not found',
      'sediment.detail.promotion': 'Landing and PR',
      'sediment.detail.source': 'Source diagnosis',
      'sediment.detail.suggestion': 'Suggestion',
      'sediment.detail.rationale': 'Why',
      'sediment.detail.assessed': 'Assessed at',
      'sediment.detail.review': 'Review flags',
      'sediment.detail.candidate': 'Candidate',
      'sediment.detail.noDecision': 'No decision yet',
      'sediment.detail.noPr': 'Not recorded',
      'sediment.detail.landingPending': 'lands on merge',
      'sediment.detail.pr': 'PR',
      'sediment.detail.case': 'case',
      'sediment.table.draft': 'Draft',
      'sediment.table.decision': 'Decision',
      'sediment.detail.postmortem': 'postmortem',
      'sediment.detail.stale': 'Rerun needed: {reason}',
      'sediment.detail.target': 'Compare target',
      'sediment.detail.targetWarnings': 'Target hints',
      'sediment.targetState.ref_missing': 'target ref unavailable',
      'sediment.targetState.target_behind': 'target behind',
      'sediment.targetState.not_comparable': 'not comparable',
      'sediment.targetState.ref_changed': 'target changed',
      'sediment.detail.mismatch.stale_trace': 'The trace still says draft submitted, but the case is in the knowledge base. Generate a writeback prompt.',
      'sediment.detail.mismatch.missing_draft': 'The trace says a draft was submitted, but it is not in inbox or .done.',
      'sediment.detail.mismatch.missing_case': 'The trace says promoted, but the case is not in the knowledge base.',
      'sediment.detail.mismatch.draft_left_behind': 'The trace says promoted, but the draft is still in inbox: it was not queued out.',
      'sediment.detail.writeback': 'Generate writeback prompt',
      'sediment.detail.closeDraft': 'Generate close prompt',
      'sediment.target.title': 'Which remote should the PR go to?',
      'sediment.target.sub': 'Remotes differ by deployment; this lists facts only and remembers the choice.',
      'sediment.target.base': 'base branch',
      'sediment.target.save': 'Save and generate',
      'sediment.target.noAdapter': 'No adapter',
      'sediment.target.token': 'token needed',
      'sediment.target.required': 'Choose a PR target first',
      'sediment.target.empty': 'No remotes available.',
      'sediment.refresh': 'Refresh',
      'sediment.open': 'Open sediment queue',
      'sediment.stepper.draft': 'Draft',
      'sediment.stepper.assessed': 'Assessed',
      'sediment.stepper.decided': 'Decided',
      'sediment.stepper.pr': 'PR',
      'sediment.stepper.promoted': 'Promoted',
      'sediment.stepper.unknown': 'not recorded',
      'sediment.stepper.pending': 'to do',
      'sediment.check': 'Check merge',
      'sediment.check.readonly': 'Read-only: generate a check prompt',
      'sediment.markMerged': 'Mark merged',
      'sediment.noTarget': 'Push target not set',
      'sediment.targetNote': 'Remote roles are not assumed',
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

    // 快捷键提示跟平台走：macOS 用 ⌘ / ⇧，其他平台用 Ctrl / Shift。键盘处理本身两种都收
    // （metaKey || ctrlKey），这里只决定显示文案，避免 Windows / Linux 上显示 ⌘。
    function isMacPlatform() {
      try {
        const nav = typeof navigator !== 'undefined' ? navigator : null
        const data = nav && nav.userAgentData && nav.userAgentData.platform
        const text = String(data || (nav && nav.platform) || (nav && nav.userAgent) || '')
        return /mac|iphone|ipad|ipod/i.test(text)
      } catch (error) {
        return false
      }
    }

    function shortcutKeys(name) {
      const mac = isMacPlatform()
      if (name === 'open') return mac ? '⌘⇧D' : 'Ctrl+Shift+D'
      return mac ? '⌘K' : 'Ctrl+K'
    }

    function shortcutOpenLabel() {
      return tr('shortcut.open', { keys: shortcutKeys('open') })
    }

    // ── 样式 ────────────────────────────────────────────────────────────────
    const CSS = [
      '.scp-root,.scp-pal{--scp-surface:#ffffff;--scp-surface-2:#f6f7f9;--scp-surface-3:#eceff4;--scp-border:#e5e8ee;--scp-border-strong:#d7dce5;--scp-text:#1a1f29;--scp-muted:#647082;--scp-faint:#98a2b3;--scp-accent:#3b63e0;--scp-accent-soft:#eef2fe;--scp-accent-line:#c9d5fb;--scp-on-accent:#ffffff;--scp-ok:#0e8a5f;--scp-ok-soft:#e7f6ef;--scp-warn:#b25e09;--scp-warn-soft:#fdf2e4;--scp-bad:#c42b1c;--scp-bad-soft:#fdecea;--scp-idle:#98a2b3;--scp-shadow:0 1px 2px rgba(16,24,40,.04),0 12px 30px -20px rgba(16,24,40,.22);}',
      'body[data-ds-dark-theme] .scp-root,body[data-ds-dark-theme] .scp-pal,[data-theme="dark"] .scp-root,[data-theme="dark"] .scp-pal{--scp-surface:#1c1f26;--scp-surface-2:#242832;--scp-surface-3:#2e333e;--scp-border:#2e3441;--scp-border-strong:#3d4553;--scp-text:#eaedf3;--scp-muted:#a6afbd;--scp-faint:#7a8494;--scp-accent:#8aa5ff;--scp-accent-soft:rgba(138,165,255,.14);--scp-accent-line:rgba(138,165,255,.3);--scp-on-accent:#10131a;--scp-ok:#45d08a;--scp-ok-soft:rgba(69,208,138,.12);--scp-warn:#f5b34a;--scp-warn-soft:rgba(245,179,74,.12);--scp-bad:#f0796e;--scp-bad-soft:rgba(240,121,110,.12);--scp-idle:#6f7886;--scp-shadow:0 1px 2px rgba(0,0,0,.4),0 16px 36px -20px rgba(0,0,0,.7);}',
      '.scp-root{position:relative;container-type:inline-size;width:calc(100% - 2 * var(--dsh-composer-side-clearance, 0px));max-width:var(--dsh-composer-card-max-width, 100%);margin:0 auto;box-sizing:border-box;font-family:inherit;color:var(--scp-text);--scp-tone:var(--scp-accent);}',
      // 浮层改成向下展开时会盖到输入卡上；状态条是输入卡前面的兄弟节点，抬一层才点得到。
      '.scp-root[data-popover-down="true"]{z-index:9;}',
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
      '.scp-foot{display:flex;align-items:center;gap:9px;min-width:0;padding:0 2px;overflow:hidden;}',
      '.scp-track{flex:none;display:inline-flex;align-items:center;gap:3px;}',
      '.scp-tick{width:11px;height:3px;border-radius:2px;background:var(--scp-surface-3);transition:background-color 180ms ease;}',
      '.scp-tick[data-state="done"]{background:color-mix(in srgb, var(--scp-tone) 32%, transparent);}',
      '.scp-tick[data-state="now"]{background:var(--scp-tone);}',
      '.scp-now{font-size:10.5px;line-height:1.6;color:var(--scp-faint);margin-left:3px;font-variant-numeric:tabular-nums;}',
      '.scp-meta{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;font-size:11px;line-height:1.6;color:var(--scp-muted);white-space:nowrap;}',
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
      '.scp-icon:focus-visible,.scp-collapse:focus-visible,.scp-btn:focus-visible,.scp-tool-btn:focus-visible,.scp-case:focus-visible,.scp-scope:focus-visible,.scp-pal-row:focus-visible,.scp-filter-item:focus-visible,.scp-picker-row:focus-visible{outline:2px solid var(--scp-accent);outline-offset:2px;}',
      '.scp-icon svg{display:block;}',
      '.scp-pin[data-on="true"]{background:var(--scp-accent-soft);color:var(--scp-accent);}',
      '.scp-collapse{flex:none;display:inline-flex;align-items:center;gap:2px;height:24px;padding:0 6px;border:none;border-radius:7px;background:transparent;color:var(--scp-muted);font:inherit;font-size:11px;line-height:1;cursor:pointer;transition:background-color 120ms ease,color 120ms ease;}',
      '.scp-collapse:hover{background:var(--scp-surface-2);color:var(--scp-text);}',
      '.scp-collapse .scp-chevron{opacity:.7;}',
      '.scp-chevron{transition:transform 180ms ease;}',
      '.scp-chevron[data-open="true"]{transform:rotate(180deg);}',
      '.scp-empty-note{font-size:11px;line-height:1.6;color:var(--scp-faint);}',
      '.scp-pal-notice{margin:0 0 8px;padding:6px 9px;border-radius:8px;border:1px solid color-mix(in srgb, var(--scp-warn) 30%, var(--scp-border));background:var(--scp-warn-soft);color:var(--scp-text);font-size:11.5px;line-height:1.6;}',
      '.scp-pal-error{display:flex;align-items:center;gap:10px;padding:18px 22px;color:var(--scp-muted);font-size:12.5px;line-height:1.7;border-top:1px solid var(--scp-border);border-bottom:1px solid var(--scp-border);}',
      '.scp-pal-error-title{flex:1 1 auto;min-width:0;}',
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
      '.scp-root[data-pending="true"] .scp-ring{background:var(--scp-warn);}',
      '.scp-root[data-flash="true"] .scp-ring{animation:scp-flash 1.4s ease-out;}',
      '@keyframes scp-flash{0%{box-shadow:0 0 0 0 color-mix(in srgb, var(--scp-tone) 45%, transparent)}55%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}',
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
      `/* ── 诊断总览：排版、布局与控件 ─────────────────────────────────────
   新控件的字号取八档：--scp-fs-cap 10.5 / meta 11 / label 11.5 / sm 12 /
   body 12.5 / row 13 / title 15 / hero 16.5；字重取四档 400 / 500 / 600 / 650。
   间距集中在 4 / 8 / 12 / 16 / 20 / 24；圆角按控件、卡片、窗口分三档。
   状态条共用的 .scp-menu-note / .scp-case 仍是固定值；间距与圆角沿用既有档位，未逐项 token 化。 */
.scp-pal{position:relative;display:flex;flex-direction:column;width:min(960px,94vw);max-height:78vh;overflow:hidden;border:1px solid var(--scp-border-strong);border-radius:18px;background:var(--scp-surface);color:var(--scp-text);box-shadow:var(--scp-shadow);outline:none;animation:scp-pop 190ms cubic-bezier(.2,.9,.3,1);
  --scp-fs-cap:10.5px;--scp-fs-meta:11px;--scp-fs-label:11.5px;--scp-fs-sm:12px;--scp-fs-body:12.5px;--scp-fs-row:13px;--scp-fs-title:15px;
  --scp-fw-regular:400;--scp-fw-medium:500;--scp-fw-semi:600;--scp-fw-bold:650;
  --scp-lh-tight:1.35;--scp-lh-base:1.55;--scp-lh-prose:1.75;
  --scp-sp-1:4px;--scp-sp-2:8px;--scp-sp-3:12px;--scp-sp-4:16px;--scp-sp-5:20px;--scp-sp-6:24px;
  --scp-ctl-h:32px;--scp-ctl-h-sm:28px;--scp-ctl-h-input:34px;--scp-ctl-r:8px;--scp-side-pad-x:24px;}
.scp-pal-top{display:flex;align-items:center;gap:var(--scp-sp-3);padding:var(--scp-sp-4) var(--scp-sp-5);border-bottom:1px solid var(--scp-border);}
.scp-pal-heading{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:2px;}
.scp-pal-title{font-size:var(--scp-fs-title);font-weight:var(--scp-fw-bold);line-height:var(--scp-lh-tight);letter-spacing:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-pal-sub{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-base);color:var(--scp-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-views{display:flex;gap:2px;padding:3px;border-radius:10px;background:var(--scp-surface-2);flex:none;}
.scp-view-tab{display:inline-flex;align-items:center;gap:5px;height:var(--scp-ctl-h-sm);padding:0 12px;border:0;background:transparent;font:inherit;font-size:var(--scp-fs-sm);font-weight:var(--scp-fw-medium);line-height:1;border-radius:7px;color:var(--scp-muted);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,color 120ms ease;}
.scp-view-tab:hover{color:var(--scp-text);}
.scp-view-tab[data-on="true"]{background:var(--scp-surface);color:var(--scp-text);font-weight:var(--scp-fw-semi);box-shadow:0 1px 2px rgba(16,24,40,.08);}
.scp-view-tab b{font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);color:var(--scp-faint);font-variant-numeric:tabular-nums;}
.scp-view-tab[data-on="true"] b{color:var(--scp-accent);}
.scp-pal .scp-icon{width:28px;height:28px;border-radius:8px;}
.scp-pal-main{display:flex;min-height:0;flex:1 1 auto;}
.scp-pal-list{flex:0 0 42%;max-width:400px;min-width:290px;overflow:auto;padding:var(--scp-sp-3);border-right:1px solid var(--scp-border);}
.scp-search{display:flex;align-items:center;gap:6px;margin:0 0 var(--scp-sp-2);padding:0 10px;height:var(--scp-ctl-h-input);border:1px solid var(--scp-border);border-radius:9px;background:var(--scp-surface);}
.scp-search input{flex:1;min-width:0;border:0;outline:none;background:transparent;color:var(--scp-text);font:inherit;font-size:var(--scp-fs-body);line-height:1.5;}
.scp-search input::placeholder{color:var(--scp-faint);}
.scp-search .scp-kbd{flex:none;}
.scp-filters{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 var(--scp-sp-2);padding:0 2px;}
.scp-filter-item{display:inline-flex;align-items:center;gap:5px;height:var(--scp-ctl-h-sm);padding:0 10px;border:1px solid transparent;border-radius:999px;background:var(--scp-surface-2);font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:1;color:var(--scp-muted);cursor:pointer;white-space:nowrap;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}
.scp-filter-item:hover{background:var(--scp-surface-3);color:var(--scp-text);}
.scp-filter-item[data-on="true"]{background:var(--scp-accent-soft);border-color:var(--scp-accent-line);color:var(--scp-accent);font-weight:var(--scp-fw-semi);}
.scp-filter-item b{font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);color:var(--scp-faint);font-variant-numeric:tabular-nums;}
.scp-filter-item[data-on="true"] b{color:var(--scp-accent);}
.scp-pal-row{display:flex;align-items:center;gap:10px;width:100%;padding:10px 12px;border:none;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 120ms ease;}
.scp-pal-row:hover{background:var(--scp-surface-2);}
.scp-pal-row[data-on="true"]{background:var(--scp-accent-soft);}
.scp-pal-row .scp-ring{width:8px;height:8px;}
.scp-pal-row-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:4px;}
.scp-pal-row-line{display:flex;align-items:baseline;gap:8px;min-width:0;}
.scp-pal-row-meta-main{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-pal-row-time{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-faint);}
.scp-pal-row-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--scp-fs-row);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);color:var(--scp-text);}
.scp-pal-row-meta{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);white-space:nowrap;}
.scp-pal-row-step{flex:none;font-size:var(--scp-fs-meta);font-weight:var(--scp-fw-medium);font-variant-numeric:tabular-nums;color:var(--scp-faint);}
.scp-pal-side{flex:1 1 auto;min-width:0;overflow:auto;padding:var(--scp-sp-5) var(--scp-side-pad-x) 0;display:flex;flex-direction:column;background:var(--scp-surface-2);}
.scp-pal-side>*:not(.scp-pal-empty){flex:none;}
.scp-pal-side>.scp-callout{margin-top:var(--scp-sp-3);}
.scp-pal .scp-badge{display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:6px;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-semi);line-height:1;color:var(--scp-tone);background:color-mix(in srgb,var(--scp-tone) 12%,transparent);}
.scp-pal .scp-chip{display:inline-flex;align-items:center;height:22px;padding:0 9px;border:1px solid var(--scp-border);border-radius:6px;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:1;white-space:nowrap;color:var(--scp-muted);background:var(--scp-surface);}
.scp-pal .scp-chip[data-tone="brand"]{color:var(--scp-accent);background:var(--scp-accent-soft);border-color:var(--scp-accent-line);}
.scp-pal .scp-chip[data-tone="warn"]{color:var(--scp-warn);background:var(--scp-warn-soft);border-color:color-mix(in srgb,var(--scp-warn) 26%,var(--scp-border));}
.scp-pal .scp-chip[data-tone="success"]{color:var(--scp-ok);background:var(--scp-ok-soft);border-color:color-mix(in srgb,var(--scp-ok) 26%,var(--scp-border));}
.scp-pal .scp-chip[data-tone="error"]{color:var(--scp-bad);background:var(--scp-bad-soft);border-color:color-mix(in srgb,var(--scp-bad) 26%,var(--scp-border));}
.scp-pal .scp-step{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);font-variant-numeric:tabular-nums;color:var(--scp-muted);}
/* 诊断详情抬头（识别行）：一行状态与身份 + 问题背景（可展开）。
   真机 trace 的 summary 首句常见一两百到七八百字，当标题放大加粗会占掉详情的大半屏；这里把它降到
   正文层级，只让错误码、路径、函数调用走等宽字，靠字符宽度差异而不是字重区分。 */
.scp-identity{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-width:0;}
.scp-identity .scp-badge,.scp-identity .scp-chip{height:20px;padding:0 8px;border-radius:5px;font-size:var(--scp-fs-meta);line-height:1;}
.scp-identity-meta{margin-left:auto;flex:none;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);font-variant-numeric:tabular-nums;color:var(--scp-faint);white-space:nowrap;}
.scp-lede{margin:var(--scp-sp-3) 0 0;font-size:var(--scp-fs-row);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:break-word;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}
.scp-lede[data-open="true"]{display:block;}
.scp-icode{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:1;padding:1.5px 4px;border-radius:4px;background:var(--scp-surface-3);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-more{display:inline-flex;align-items:center;gap:4px;margin-top:var(--scp-sp-1);padding:0;border:0;background:transparent;font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-accent);cursor:pointer;}
.scp-more:hover{text-decoration:underline;text-underline-offset:2px;}
.scp-waitline{display:flex;align-items:baseline;gap:8px;margin-top:var(--scp-sp-3);padding:var(--scp-sp-2) 10px;border-radius:8px;background:var(--scp-accent-soft);}
.scp-waitline-tag{flex:none;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);letter-spacing:.04em;line-height:var(--scp-lh-base);color:var(--scp-accent);}
.scp-waitline-text{flex:1 1 auto;min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:break-word;}
.scp-callout{display:flex;flex-direction:column;gap:var(--scp-sp-1);padding:var(--scp-sp-3) var(--scp-sp-4);border-radius:10px;background:var(--scp-accent-soft);border:1px solid var(--scp-accent-line);}
.scp-callout-label{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);letter-spacing:0;color:var(--scp-accent);}
.scp-callout-text{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-regular);line-height:var(--scp-lh-prose);color:var(--scp-text);overflow-wrap:anywhere;}
.scp-section-label{margin:var(--scp-sp-5) 0 var(--scp-sp-2);font-size:var(--scp-fs-label);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-tight);letter-spacing:.02em;color:var(--scp-muted);}
.scp-check,.scp-upstream,.scp-list-block,.scp-history{display:flex;flex-direction:column;gap:var(--scp-sp-2);padding:var(--scp-sp-3) var(--scp-sp-4);border-radius:10px;background:var(--scp-surface);border:1px solid color-mix(in srgb,var(--scp-border) 72%,transparent);}
.scp-list-block>.scp-section-label:first-child{margin-top:0;}
.scp-check-item{display:flex;align-items:center;gap:10px;min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);}
.scp-check-dot{flex:none;display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;border:1.5px solid var(--scp-border-strong);color:var(--scp-on-accent);font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);line-height:1;}
.scp-check-item[data-done="true"] .scp-check-dot{background:var(--scp-ok);border-color:var(--scp-ok);}
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
.scp-tl-step{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);font-variant-numeric:tabular-nums;color:var(--scp-faint);}
.scp-tl-body{min-width:0;font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);color:var(--scp-text);}
.scp-tl-meta{font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-tl-reason{margin-top:2px;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-faint);}
.scp-history-row{display:flex;align-items:baseline;gap:8px;min-width:0;font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);}
.scp-history-when{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-faint);}
.scp-history-kind{flex:none;font-size:var(--scp-fs-cap);line-height:1.6;padding:1px 7px;border-radius:5px;background:var(--scp-surface-2);color:var(--scp-muted);font-weight:var(--scp-fw-medium);}
.scp-history-text{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--scp-text);}
.scp-history-note{flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--scp-faint);}
.scp-actions{position:sticky;bottom:0;display:flex;flex-wrap:wrap;align-items:center;gap:var(--scp-sp-2);margin:var(--scp-sp-5) calc(-1 * var(--scp-side-pad-x)) 0;padding:var(--scp-sp-3) var(--scp-side-pad-x) var(--scp-sp-4);border-top:1px solid var(--scp-border);background:var(--scp-surface-2);box-shadow:0 -8px 16px -12px color-mix(in srgb,var(--scp-text) 24%,transparent);}
.scp-pal .scp-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:var(--scp-ctl-h);padding:0 14px;border:1px solid var(--scp-border);border-radius:var(--scp-ctl-r);background:var(--scp-surface);color:var(--scp-text);font:inherit;font-size:var(--scp-fs-sm);font-weight:var(--scp-fw-medium);line-height:1;white-space:nowrap;cursor:pointer;transition:background-color 120ms ease,border-color 120ms ease,color 120ms ease;}
.scp-pal .scp-btn:hover{background:var(--scp-surface-2);border-color:var(--scp-border-strong);}
.scp-pal .scp-btn:disabled{opacity:.45;cursor:not-allowed;}
.scp-pal .scp-btn--primary{border-color:transparent;background:var(--scp-accent);color:var(--scp-on-accent);font-weight:var(--scp-fw-semi);}
.scp-pal .scp-btn--primary:hover{background:color-mix(in srgb,var(--scp-accent) 88%,var(--scp-text));border-color:transparent;}
.scp-pal .scp-btn--ghost{border-color:transparent;background:transparent;color:var(--scp-muted);}
.scp-pal .scp-btn--ghost:hover{background:var(--scp-surface-2);color:var(--scp-text);}
.scp-pal .scp-btn--quiet{border-color:transparent;background:transparent;color:var(--scp-accent);font-weight:var(--scp-fw-semi);padding:0 10px;}
.scp-pal .scp-btn--quiet:hover{background:var(--scp-accent-soft);color:var(--scp-accent);}
.scp-pal .scp-cmd-backdrop{position:absolute;inset:0;z-index:4;display:flex;justify-content:center;align-items:flex-start;padding-top:11vh;background:color-mix(in srgb,var(--scp-text) 12%,transparent);}
.scp-pal .scp-cmd{width:min(520px,calc(100% - 32px));max-height:58vh;display:flex;flex-direction:column;border:1px solid var(--scp-border-strong);border-radius:12px;background:var(--scp-surface);box-shadow:var(--scp-shadow);overflow:hidden;}
.scp-pal .scp-cmd:focus-within{border-color:var(--scp-accent-line);box-shadow:0 0 0 2px var(--scp-accent-line);}
.scp-pal .scp-cmd input{border:0;border-bottom:1px solid var(--scp-border);outline:none;padding:var(--scp-sp-3) var(--scp-sp-4);font:inherit;font-size:var(--scp-fs-row);background:transparent;color:var(--scp-text);}
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
.scp-search:focus-within{border-color:var(--scp-accent-line);box-shadow:0 0 0 2px var(--scp-accent-line);}
.scp-write-side{padding-bottom:var(--scp-sp-5);}
.scp-write-side .scp-menu-head{display:flex;align-items:center;justify-content:space-between;gap:var(--scp-sp-2);padding:0 0 var(--scp-sp-2);border-bottom:1px solid var(--scp-border);}
.scp-write-side .scp-menu-title{font-size:var(--scp-fs-title);font-weight:var(--scp-fw-bold);line-height:var(--scp-lh-tight);color:var(--scp-text);}
.scp-write-side .scp-menu-group{margin:var(--scp-sp-3) 0 0;padding:var(--scp-sp-3) 2px 0;border-top:1px solid var(--scp-border);font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);letter-spacing:.02em;color:var(--scp-faint);}
.scp-write-side .scp-menu-item{display:flex;align-items:center;gap:var(--scp-sp-2);width:100%;padding:8px 10px;border:none;border-radius:8px;background:transparent;color:var(--scp-text);font:inherit;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);text-align:left;cursor:pointer;transition:background-color 120ms ease;}
.scp-write-side .scp-menu-item:hover{background:var(--scp-surface);}
.scp-write-side .scp-menu-item:disabled{opacity:.45;cursor:not-allowed;}
.scp-write-side .scp-form{padding:0;}
.scp-write-side .scp-form-actions{justify-content:flex-start;padding-top:var(--scp-sp-2);}
.scp-link{border:0;background:transparent;padding:0;font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);line-height:var(--scp-lh-base);color:var(--scp-accent);cursor:pointer;text-align:left;overflow-wrap:anywhere;}
.scp-link:hover{text-decoration:underline;}
.scp-pal-foot{display:flex;align-items:center;gap:var(--scp-sp-3);min-width:0;padding:10px var(--scp-sp-5);border-top:1px solid var(--scp-border);font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-muted);background:var(--scp-surface);}
.scp-kbd{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;padding:0 4px;border-radius:5px;border:1px solid var(--scp-border);background:var(--scp-surface-2);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-medium);color:var(--scp-muted);}
.scp-version{font-size:var(--scp-fs-cap);color:var(--scp-faint);font-variant-numeric:tabular-nums;}
.scp-pal-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:var(--scp-sp-2);flex:1 1 auto;min-height:200px;padding:var(--scp-sp-6);color:var(--scp-muted);font-size:var(--scp-fs-body);line-height:var(--scp-lh-prose);text-align:center;}
.scp-menu-note{margin-left:auto;max-width:52%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10.5px;line-height:1.6;color:var(--scp-warn);}
.scp-toast{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);max-width:min(80%,520px);padding:7px 14px;border-radius:var(--scp-r-pill,999px);background:var(--scp-surface);border:1px solid var(--scp-border-strong);box-shadow:var(--scp-shadow);font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-text);white-space:normal;text-align:center;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere;animation:scp-toast 170ms ease-out;}
@keyframes scp-toast{from{opacity:0;transform:translate(-50%,6px)}to{opacity:1;transform:translate(-50%,0)}}
.scp-skel{height:12px;border-radius:6px;background:linear-gradient(90deg,var(--scp-surface-2),color-mix(in srgb, var(--scp-surface-2) 30%, transparent),var(--scp-surface-2));background-size:200% 100%;animation:scp-shimmer 1.5s ease-in-out infinite;}
@keyframes scp-shimmer{from{background-position:120% 0}to{background-position:-80% 0}}
.scp-root[data-tone="brand"]{--scp-tone:var(--scp-accent);}
.scp-root[data-tone="success"]{--scp-tone:var(--scp-ok);}
.scp-root[data-tone="warn"]{--scp-tone:var(--scp-warn);}
.scp-root[data-tone="error"]{--scp-tone:var(--scp-bad);}
.scp-root[data-tone="idle"]{--scp-tone:var(--scp-idle);}
.scp-pal button:focus-visible,.scp-view-tab:focus-visible,.scp-check-action:focus-visible,.scp-sed-row:focus-visible,.scp-cmd-item:focus-visible,.scp-pick:focus-visible,.scp-details-toggle:focus-visible,.scp-link:focus-visible{outline:2px solid var(--scp-accent);outline-offset:2px;}
.scp-pal ::selection{background:var(--scp-accent-line);}
@container (max-width: 720px){.scp-meta,.scp-chips{display:none;}.scp-case{font-size:12px;}.scp-status-text{display:none;}.scp-collapse-text{display:none;}}
@media (max-width: 760px){
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
@media (prefers-reduced-motion: reduce){.scp-handle{transition:none;}.scp-ring{animation:none;}.scp-btn,.scp-icon,.scp-tick,.scp-pal-row,.scp-sed-row,.scp-chevron,.scp-check-action,.scp-filter-item,.scp-view-tab,.scp-write-side .scp-menu-item{transition:none;}.scp-pal,.scp-menu,.scp-toast,.scp-picker{animation:none;}.scp-skel{animation:none;}}`,
      `/* ── 沉淀队列（v1）──────────────────────────────────────────────── */
.scp-batch{display:flex;align-items:center;gap:var(--scp-sp-2);padding:10px var(--scp-sp-5);border-bottom:1px solid var(--scp-border);background:var(--scp-surface);flex:none;min-width:0;}
.scp-batch-strong{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);white-space:nowrap;}
.scp-batch-chip{display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:5px;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);line-height:1;white-space:nowrap;}
.scp-batch-chip[data-tone="warn"]{background:var(--scp-warn-soft);color:var(--scp-warn);}
.scp-batch-chip[data-tone="accent"]{background:var(--scp-accent-soft);color:var(--scp-accent);}
.scp-batch-chip[data-tone="ok"]{background:var(--scp-ok-soft);color:var(--scp-ok);}
.scp-batch-chip[data-tone="bad"]{background:var(--scp-bad-soft);color:var(--scp-bad);}
.scp-batch-chip[data-tone="gray"]{background:var(--scp-surface-3);color:var(--scp-muted);}
.scp-batch-age{font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-faint);white-space:nowrap;}
.scp-batch-age[data-over="true"]{color:var(--scp-bad);font-weight:var(--scp-fw-semi);}
.scp-sed-side{gap:0;padding:var(--scp-sp-5) var(--scp-side-pad-x) 0;}
.scp-sed-side>.scp-callout{margin-top:var(--scp-sp-3);}
.scp-sed-side>.scp-list-block{margin-top:var(--scp-sp-3);}
.scp-sed-side>.scp-sed-hint{margin-top:6px;}
.scp-sed-side>.scp-list-block>.scp-section-label{margin:0 0 var(--scp-sp-2);}
.scp-sed-group{display:flex;align-items:center;justify-content:space-between;padding:var(--scp-sp-3) 8px 6px;font-size:var(--scp-fs-cap);font-weight:var(--scp-fw-semi);letter-spacing:.02em;color:var(--scp-faint);}
.scp-sed-row{display:flex;gap:10px;width:100%;padding:10px;border:0;border-radius:10px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;transition:background-color 120ms ease;}
.scp-sed-row:hover{background:var(--scp-surface-2);}
.scp-sed-row[data-on="true"]{background:var(--scp-accent-soft);}
.scp-sed-dot{width:6px;height:6px;border-radius:50%;margin-top:7px;flex:none;}
.scp-sed-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:3px;}
.scp-sed-line{display:flex;align-items:baseline;gap:8px;min-width:0;}
.scp-sed-title{flex:1 1 auto;min-width:0;font-size:var(--scp-fs-row);font-weight:var(--scp-fw-semi);line-height:var(--scp-lh-base);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.scp-sed-age{flex:none;font-size:var(--scp-fs-meta);font-variant-numeric:tabular-nums;color:var(--scp-faint);}
.scp-sed-age[data-over="true"]{color:var(--scp-bad);font-weight:var(--scp-fw-semi);}
.scp-sed-meta{display:flex;align-items:center;gap:6px;min-width:0;font-size:var(--scp-fs-meta);line-height:var(--scp-lh-base);color:var(--scp-faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
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
.scp-sed-step-note{font-size:var(--scp-fs-cap);line-height:var(--scp-lh-tight);color:var(--scp-faint);text-align:center;white-space:nowrap;}
.scp-sed-step-note[data-bad="true"]{color:var(--scp-bad);}
.scp-target-row{display:flex;align-items:center;gap:var(--scp-sp-2);padding:var(--scp-sp-2) var(--scp-sp-3);border:1px solid var(--scp-border);border-radius:10px;background:var(--scp-surface-2);font-size:var(--scp-fs-label);min-width:0;}
.scp-target-label{color:var(--scp-faint);flex:none;}
.scp-target-pill{display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 9px;border-radius:6px;background:var(--scp-surface);border:1px solid var(--scp-border-strong);font-weight:var(--scp-fw-semi);font-size:var(--scp-fs-label);color:var(--scp-text);white-space:nowrap;}
.scp-target-hint{color:var(--scp-muted);font-size:var(--scp-fs-meta);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.scp-veil{position:absolute;inset:0;z-index:70;display:flex;align-items:center;justify-content:center;background:rgba(20,26,38,.38);-webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);}
body[data-ds-dark-theme] .scp-veil,[data-theme="dark"] .scp-veil{background:rgba(0,0,0,.55);}
.scp-modal{width:min(680px,calc(100% - 40px));max-height:74vh;display:flex;flex-direction:column;background:var(--scp-surface);border:1px solid var(--scp-border-strong);border-radius:16px;box-shadow:var(--scp-shadow);overflow:hidden;}
.scp-modal-top{display:flex;align-items:flex-start;gap:var(--scp-sp-3);padding:var(--scp-sp-4) var(--scp-sp-5) var(--scp-sp-3);border-bottom:1px solid var(--scp-border);}
.scp-modal-title{font-size:var(--scp-fs-title);font-weight:var(--scp-fw-bold);line-height:var(--scp-lh-tight);}
.scp-modal-sub{font-size:var(--scp-fs-label);font-weight:var(--scp-fw-regular);color:var(--scp-muted);margin-top:3px;line-height:var(--scp-lh-base);}
.scp-modal-body{overflow:auto;padding:var(--scp-sp-3) var(--scp-sp-5);display:flex;flex-direction:column;gap:var(--scp-sp-3);}
.scp-modal-foot{display:flex;align-items:center;gap:var(--scp-sp-2);padding:var(--scp-sp-3) var(--scp-sp-5);border-top:1px solid var(--scp-border);}
.scp-prompt{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--scp-fs-label);line-height:var(--scp-lh-prose);white-space:pre-wrap;background:var(--scp-surface-2);border:1px solid var(--scp-border);border-radius:9px;padding:var(--scp-sp-3) var(--scp-sp-3);color:var(--scp-text);max-height:250px;overflow:auto;-webkit-mask-image:linear-gradient(to bottom,#000 88%,transparent);mask-image:linear-gradient(to bottom,#000 88%,transparent);}
.scp-prompt-cap{font-size:var(--scp-fs-cap);color:var(--scp-faint);margin-top:-5px;}
.scp-details-toggle{width:fit-content;border:0;background:transparent;color:var(--scp-accent);font:inherit;font-size:var(--scp-fs-label);font-weight:var(--scp-fw-medium);padding:1px 0;cursor:pointer;}
.scp-details-toggle:hover{text-decoration:underline;}
.scp-warn-list{display:flex;flex-direction:column;gap:var(--scp-sp-1);font-size:var(--scp-fs-label);color:var(--scp-muted);line-height:var(--scp-lh-base);}
.scp-warn-list b{color:var(--scp-warn);font-weight:var(--scp-fw-semi);}
.scp-pick-list{display:flex;flex-direction:column;gap:var(--scp-sp-2);}
.scp-pick{display:flex;gap:var(--scp-sp-3);align-items:flex-start;padding:var(--scp-sp-3);border:1px solid var(--scp-border);border-radius:10px;background:var(--scp-surface);cursor:pointer;text-align:left;}
.scp-pick[data-on="true"]{background:var(--scp-accent-soft);border-color:var(--scp-accent-line);}
.scp-pick:disabled{opacity:.55;cursor:not-allowed;}
.scp-radio{width:14px;height:14px;border-radius:50%;border:2px solid var(--scp-border-strong);flex:none;margin-top:1px;}
.scp-pick[data-on="true"] .scp-radio{border-color:var(--scp-accent);background:var(--scp-accent);box-shadow:inset 0 0 0 3px var(--scp-accent-soft);}
.scp-pick-title{font-size:var(--scp-fs-body);font-weight:var(--scp-fw-semi);display:flex;gap:6px;align-items:center;flex-wrap:wrap;}
.scp-pick-sub{font-size:var(--scp-fs-label);color:var(--scp-muted);margin-top:2px;line-height:var(--scp-lh-base);}
.scp-sed-table{width:100%;border-collapse:collapse;font-size:var(--scp-fs-label);}
.scp-sed-table th{text-align:left;font-weight:var(--scp-fw-semi);color:var(--scp-faint);font-size:var(--scp-fs-cap);letter-spacing:.02em;padding:0 6px 5px;border-bottom:1px solid var(--scp-border);}
.scp-sed-table td{padding:6px;border-bottom:1px solid color-mix(in srgb,var(--scp-border) 60%,transparent);vertical-align:top;}
.scp-sed-table tr:last-child td{border-bottom:0;}
.scp-sed-kv{display:flex;flex-direction:column;gap:6px;font-size:var(--scp-fs-body);line-height:var(--scp-lh-base);}
.scp-sed-kv-row{display:grid;grid-template-columns:64px 1fr;gap:var(--scp-sp-2);min-width:0;}
.scp-sed-kv-row dt{font-size:var(--scp-fs-label);color:var(--scp-muted);}
.scp-sed-kv-row dd{margin:0;color:var(--scp-text);overflow-wrap:anywhere;}
.scp-sed-actions{position:sticky;bottom:0;display:flex;align-items:center;gap:var(--scp-sp-2);flex-wrap:wrap;margin:var(--scp-sp-5) calc(-1 * var(--scp-side-pad-x)) 0;padding:var(--scp-sp-3) var(--scp-side-pad-x) var(--scp-sp-4);border-top:1px solid var(--scp-border);background:var(--scp-surface-2);box-shadow:0 -8px 16px -12px color-mix(in srgb,var(--scp-text) 24%,transparent);}
.scp-sed-hint{font-size:var(--scp-fs-label);line-height:var(--scp-lh-base);color:var(--scp-muted);}
.scp-sed-history{display:flex;flex-direction:column;gap:6px;width:100%;margin-top:10px;padding-top:var(--scp-sp-2);border-top:1px solid var(--scp-border);}
.scp-sed-history-row{display:flex;align-items:center;gap:var(--scp-sp-2);font-size:var(--scp-fs-label);color:var(--scp-muted);min-width:0;}
.scp-sed-history-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--scp-text);}
.scp-dock-sed{display:flex;align-items:center;gap:7px;min-width:0;margin-top:1px;padding:5px 2px 0;border-top:1px solid var(--scp-border);font-size:11px;}
.scp-dock-sed-dot{width:6px;height:6px;border-radius:50%;background:var(--scp-warn);flex:none;}
.scp-dock-sed-dot[data-tone="ok"]{background:var(--scp-ok);}
.scp-dock-sed-dot[data-tone="bad"]{background:var(--scp-bad);}
.scp-dock-sed-dot[data-tone="accent"]{background:var(--scp-accent);}
.scp-dock-sed-label{color:var(--scp-faint);flex:none;}
.scp-dock-sed-stage{color:var(--scp-text);font-weight:550;white-space:nowrap;}
.scp-dock-sed-sep{color:var(--scp-border-strong);flex:none;}
.scp-dock-sed-days{color:var(--scp-warn);font-weight:650;flex:none;font-variant-numeric:tabular-nums;}
.scp-dock-sed-next{color:var(--scp-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;}
.scp-dock-sed-open{flex:none;border:0;background:var(--scp-accent-soft);color:var(--scp-accent);font:inherit;font-size:10.5px;font-weight:600;padding:2px 7px;border-radius:6px;cursor:pointer;}
body[data-ds-dark-theme] .scp-actions,body[data-ds-dark-theme] .scp-sed-actions,[data-theme="dark"] .scp-actions,[data-theme="dark"] .scp-sed-actions{box-shadow:0 -8px 16px -12px rgba(0,0,0,.55);}
@media (max-width:760px){.scp-batch{flex-wrap:wrap;gap:6px 8px;}.scp-batch .scp-spacer{display:none;}.scp-sed-step-label,.scp-sed-step-note{font-size:var(--scp-fs-cap);}.scp-target-row{flex-wrap:wrap;}}`,
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

    // ── 偏好（记住上次的展开状态、常驻与筛选）──────────────────────────────
    const DEFAULT_PREFS = { dockCollapsed: true, dockKeepOpen: false, paletteFilter: 'all', pins: {} }
    function loadPrefs() {
      try {
        const raw = window.localStorage.getItem(PREFS_KEY)
        if (!raw) return Object.assign({}, DEFAULT_PREFS)
        const parsed = JSON.parse(raw)
        const prefs = Object.assign({}, DEFAULT_PREFS)
        if (parsed && typeof parsed.dockCollapsed === 'boolean') prefs.dockCollapsed = parsed.dockCollapsed
        if (parsed && typeof parsed.dockKeepOpen === 'boolean') prefs.dockKeepOpen = parsed.dockKeepOpen
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
    let commandRequested = false

    const store = {
      prefs: loadPrefs(),
      sessionId: '',
      cwd: '',
      phase: 'idle',
      data: null,
      message: '',
      stale: false,
      staleMessage: '',
      paletteOpen: false,
      paletteSelect: '',
      paletteView: 'diagnosis',
      sedimentSelectKey: '',
      sediment: { phase: 'idle', data: null, message: '', at: 0 },
      sedimentSeq: 0,
      // 填过指令之后，下一次打开队列强制刷新一次：指令在会话里执行、面板收不到通知，
      // 60 秒去重会让读者回来时还看到执行前的旧行（例如刚撤销的草稿还在）。
      sedimentForceNext: false,
      // 查合入的逐条进度：active 时把已到达的行就地写进 sediment.drafts；
      // 整批结束 refreshSediment(true) 会覆盖为权威快照，然后清空。
      checkRun: null,
      // 这一轮查合入的停轮询句柄：切会话 / 插件卸载时要能打断在飞的轮询。
      checkStop: null,
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
        store.stale = false
        store.staleMessage = ''
        emit()
      } catch (error) {
        if (seq !== store.seq) return
        const message = String((error && error.message) || error)
        if (store.phase === 'ready') {
          // 首屏成功过：保留旧数据，但标出来源已取不到，不能让界面显示成实时状态。
          store.stale = true
          store.staleMessage = message
          emit()
          return
        }
        store.phase = 'error'
        store.message = message
        emit()
      }
    }

    // 沉淀队列：按需读取。展开状态条或打开沉淀视图时才跑（groom_status 要读 git 与 inbox，
    // 不能塞进 10 秒轮询）。保留上一次数据，刷新时只切 phase，不闪空。
    async function refreshSediment(force) {
      if (!store.cwd) return
      const now = Date.now()
      const forceNext = store.sedimentForceNext === true
      if (!force && !forceNext && store.sediment.phase === 'ready' && now - store.sediment.at < 60000) return
      store.sedimentForceNext = false
      const seq = store.sedimentSeq + 1
      store.sedimentSeq = seq
      store.sediment = Object.assign({}, store.sediment, {
        phase: store.sediment.data ? 'refreshing' : 'loading',
        message: '',
      })
      emit()
      try {
        const value = await rpcCall('copilot-sediment', {
          cwd: store.cwd,
          sessionId: store.sessionId,
        })
        if (seq !== store.sedimentSeq) return
        store.sediment = {
          phase: value && value.ok !== false ? 'ready' : 'error',
          data: value,
          message: value && value.ok === false ? String(value.message || '') : '',
          at: Date.now(),
        }
        emit()
      } catch (error) {
        if (seq !== store.sedimentSeq) return
        store.sediment = {
          phase: 'error',
          data: store.sediment.data,
          message: String((error && error.message) || error),
          at: Date.now(),
        }
        emit()
      }
    }

    // 查合入逐条进度：批次开始时建一条记录（记下本轮要查的草稿与总数），轮询到的 row
    // 就地写进 sediment.drafts 对应草稿的 pr.state/pr.checkedAt，并 emit 让行立即重画。
    // 整批结束会 refreshSediment(true) 覆盖为权威快照，所以这里只做乐观更新。
    function beginCheckRun(drafts) {
      const targets = {}
      let total = 0
      const list = Array.isArray(drafts) ? drafts : []
      // 与 pr_status.py 的 CHECKABLE 一致：只有待合入 / 未确认会被查，终态不查。
      list.forEach((draft) => {
        if (!draft || !draft.key || !draft.pr) return
        const state = String(draft.pr.state || '')
        if (state !== 'open' && state !== 'unknown') return
        targets[draft.key] = true
        total += 1
      })
      store.checkRun = { active: true, seen: 0, total, targets, states: {} }
      emit()
    }

    function applyCheckProgress(rows, run) {
      // run 是本轮句柄：切会话 / 新一轮开始后，在飞的旧轮询不能再 patch 已刷新的快照。
      if (!run || run !== store.checkRun || !run.active || !Array.isArray(rows) || !rows.length) return
      const data = store.sediment && store.sediment.data
      const drafts = data && Array.isArray(data.drafts) ? data.drafts : []
      if (!drafts.length) return
      let patched = false
      const nextDrafts = drafts.map((draft) => {
        if (!draft || !draft.key) return draft
        const row = rows.find((item) => item && item.draft === draft.key)
        if (!row) return draft
        const known = run.states[draft.key]
        if (known && known.state === String(row.state || '') && known.ok === (row.ok !== false)
          && known.error === String(row.error || '')) return draft
        // 分子只数本轮名单里的草稿，避免出现 n > m。
        if (!known && run.targets && run.targets[draft.key] === true) run.seen += 1
        run.states[draft.key] = {
          ok: row.ok !== false,
          state: String(row.state || 'unknown'),
          error: row.error ? String(row.error) : '',
          message: row.message ? String(row.message) : '',
          checkedAt: String(row.checked_at || ''),
        }
        patched = true
        const pr = draft.pr || {}
        return Object.assign({}, draft, {
          pr: Object.assign({}, pr, {
            state: String(row.state || pr.state || 'unknown'),
            checkedAt: String(row.checked_at || pr.checkedAt || ''),
            ...(row.ok !== false ? { source: 'platform' } : {}),
          }),
        })
      })
      if (!patched) return
      store.sediment = Object.assign({}, store.sediment, {
        data: Object.assign({}, data, { drafts: nextDrafts }),
      })
      emit()
    }

    function endCheckRun() {
      store.checkRun = null
      emit()
    }

    function setPaletteView(view) {
      const next = view === 'sediment' ? 'sediment' : 'diagnosis'
      if (store.paletteView === next) return
      store.paletteView = next
      emit()
    }

    function openSediment(key) {
      store.sedimentSelectKey = key ? String(key) : ''
      setPaletteOpen(true, '', 'sediment')
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

    // 插件被禁用或热重载时停掉轮询与 focus 监听：apply 没有清理时，
    // 卸载后仍每 10 秒发一次 copilot-state。
    function stopTimer() {
      if (store.timer) {
        clearInterval(store.timer)
        store.timer = 0
      }
      if (store.onFocus) {
        window.removeEventListener('focus', store.onFocus)
        store.onFocus = null
      }
      // 插件卸载时在飞的查合入轮询也要停，否则它还会继续发进度请求。
      if (typeof store.checkStop === 'function') {
        store.checkStop()
        store.checkStop = null
      }
    }

    function ensureSession(sessionId, cwd) {
      if (!sessionId) return
      if (store.sessionId !== sessionId || store.cwd !== cwd) {
        store.sessionId = sessionId
        store.cwd = cwd
        store.phase = 'loading'
        store.data = null
        store.message = ''
        store.stale = false
        store.staleMessage = ''
        store.sediment = { phase: 'idle', data: null, message: '', at: 0 }
        store.sedimentSeq += 1
        // 切会话：上一轮的轮询与进度都不属于这一单，先停再清。
        if (typeof store.checkStop === 'function') {
          store.checkStop()
          store.checkStop = null
        }
        store.checkRun = null
        emit()
        refresh(true)
      } else if (!store.data && store.phase !== 'loading') {
        refresh(false)
      }
      startTimer()
    }

    function setPaletteOpen(open, selectId, view) {
      const next = !!open
      const nextSelect = selectId === undefined ? store.paletteSelect : String(selectId || '')
      const nextView = view === undefined ? store.paletteView : String(view || 'diagnosis')
      if (store.paletteOpen === next && (selectId === undefined || store.paletteSelect === nextSelect)
        && (view === undefined || store.paletteView === nextView)) return
      store.paletteOpen = next
      store.paletteSelect = nextSelect
      store.paletteView = nextView
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
      if (row && row.activeCase) return String(row.activeCase)
      return tr('title.noSummary')
    }

    // 摘要里混着路径、错误码与函数调用：与中文同字体时读者要自己挑。只标「看得出是机器
    // 标识」的片段——带回括号的调用（带点号或不带点号都算）、已知扩展名的文件（可带行号，
    // 扩展名后要求词边界，避免把 data.jsonl 拆成 data.json + l）、十六进制、五位以上数字、
    // 以 Error / Exception 结尾的类名。其余原样留作正文，不猜语义、不改文本。
    const INLINE_CODE_RE = /([A-Za-z_][\w.$-]*\([^()\n]*\))|([\w./-]+\.(?:py|log|yaml|yml|json|txt|md|sh)(?![A-Za-z0-9_])(?!\.[A-Za-z0-9_])(?::\d+)?)|(0x[0-9a-fA-F]+)|(\b\d{5,}\b)|(\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b)/g
    function inlineTokens(text) {
      const value = String(text || '')
      if (!value) return value
      const parts = []
      let last = 0
      let match
      INLINE_CODE_RE.lastIndex = 0
      while ((match = INLINE_CODE_RE.exec(value))) {
        if (match.index > last) parts.push(value.slice(last, match.index))
        parts.push(h('code', { key: 'ic-' + match.index, className: 'scp-icode' }, match[0]))
        last = match.index + match[0].length
      }
      if (!parts.length) return value
      if (last < value.length) parts.push(value.slice(last))
      return parts
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
      if (derived.needReportReview) chips.push({ key: 'reportReview', tone: 'warn', text: tr('chip.reportReview') })
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
      if (derived.needReportReview) chips.push({ key: 'reportReview', tone: 'warn', text: tr('chip.reportReview') })
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
      return '用 /resume-diagnosis 续接 ' + row.sessionId + '（' + traceSource(row) + '）'
    }

    function materialDraft(row) {
      return '用 /resume-diagnosis 续接 ' + row.sessionId + '（' + traceSource(row) + '），材料如下：\n'
    }

    function sedimentDraft(row) {
      return '用 /to-postmortem 沉淀 ' + row.sessionId + '（来源 ' + traceSource(row) + '）'
    }

    // 能不能起沉淀：看「这单还没沉淀、有内容、不是已有 case 覆盖的单」，不看 agent 有没有
    // 写 case 候选。候选是建议不是入口前提；没有候选的单一样要能起草。
    function canStartSediment(row) {
      if (!row) return false
      const sedState = String((row.sedimented && row.sedimented.state) || 'none')
      if (sedState !== 'none') return false
      const derived = row.derived || {}
      if (derived.skeleton) return false
      if (derived.activeCaseInKb) return false
      return true
    }

    // 批量沉淀：把当前筛选里的可沉淀单一次交给 to-postmortem。
    // 名单以界面筛选为准；分组与「还有哪些单」先问只读脚本，避免面板投影与脚本判据不一致时漏单或重复起草。
    function sedimentBatchDraft(rows, meta) {
      const ids = (rows || []).map((row) => row && row.sessionId).filter(Boolean)
      if (!ids.length) return ''
      const query = String((meta && meta.query) || '').trim()
      const scope = query ? '（含搜索词「' + query + '」）' : ''
      const total = Number(meta && meta.total) || ids.length
      const totalText = query && total > ids.length ? '；该筛选全量 ' + total + ' 单' : ''
      return '用 /to-postmortem 批量沉淀这些 session：' + ids.join('、') + '\n'
        + '范围 = 诊断总览「可沉淀」筛选当前列出的 ' + ids.length + ' 单' + scope + totalText
        + '；trace 在 traces/<session>.yaml。\n'
        + '先跑 python3 scripts/sediment_batch.py --json 核对分组与证据：名单外、或名单内被判「已沉淀 / 没素材」的，'
        + '先报原因，不一起沉淀；每个 session 各成一条草稿（不按组合并）；来源 trace 逐单回写 sedimented.state: submitted，'
        + '只写 sedimented 与 updated_at，不改 status、不改 feedback.outcome。'
    }

    function promoteDraft(row) {
      return '用 /knowledge-groom 处理 ' + row.sessionId + ' 的沉淀草稿'
        + '（草稿在共享 inbox，用 python3 scripts/shared_dir.py inbox 定位；来源 ' + traceSource(row) + '）。'
        + '先给我分诊复核结论（new_pattern / variant_of / covered_by）与缺字段，等我决定后再升格；'
        + '升格前过 python3 scripts/verify_case_draft.py --gate'
    }

    // 生成指令：对象、动作、字段、来源一次写全，粘进输入框后 agent 不需要再猜。
    // 上游查证不在插件里发网络请求：先判环境（doctor 的 gh 能力），再让 agent 跑幂等的查证脚本。
    function upstreamDraft(row, info) {
      const ready = !!(info && info.ready === true)
      const gap = !ready && info && info.reason ? '；本机当前读数：' + info.reason : ''
      const upstream = (row.derived && row.derived.upstream) || null
      const anchors = upstream && Array.isArray(upstream.anchors) ? upstream.anchors.filter(Boolean) : []
      const known = anchors.length ? '；已知锚点：' + anchors.join('、') : ''
      const verified = upstream && upstream.lastVerified
        ? '；上次查证：' + upstream.lastVerified
          + (upstream.verificationSource ? '；来源验证档：' + upstream.verificationSource : '')
        : ''
      return [
        '查 ' + row.activeCase + ' 的上游状态（只查上游，不续接诊断；来源 ' + traceSource(row) + '）。',
        '1) 先跑 python3 scripts/doctor.py --json 确认 gh 已安装并登录' + gap
          + '；不可用就停并报缺口，不要猜。网络是否可用以第 2 步的「不可查证」结局为准。',
        '2) 跑 python3 scripts/verify_upstream_outcomes.py --case ' + row.activeCase
          + ' --dry-run --json 看结论' + known + verified + '。',
        '3) 把结论给我，我确认后再 --apply；写回是知识库改动，走 PR，不要直接改 main。',
        '4) 按四种结局各说一句：上游确认 / 上游否定 / 未验证 / 不可查证；不表达现场是否解决。',
      ].join('\n')
    }

    function reportDraft(row) {
      const reportFile = row.reportFile || (row.extra && row.extra.reportFile) || ('traces/' + row.sessionId + '.report.md')
      return '为 ' + row.sessionId + ' 产出（或修订）人读定位报告 ' + reportFile
        + '：结构按 skills/diagnose/references/report-template.md 的 0–10 节，读者不重读 trace 也能复述结论与依据；'
        + '结论逐条指回 trace 的事件或证据文件，没证据的标「推测」；修订在同一份文件里追加「修订记录」。'
        + '写完跑 python3 scripts/report_lint.py ' + reportFile
        + '（来源 ' + traceSource(row) + '）'
    }

    function handoffDraft(row) {
      return '把 ' + row.sessionId + ' 导出成交接包供另一台机器接手：python3 scripts/export_trace.py '
        + row.sessionId + ' --intent <continue|verify|escalate>。'
        + '导出前核对 traces/evidence 是否齐全；导出后把包路径与未纳入 / 未内联清单报给我'
        + '（来源 ' + traceSource(row) + '）'
    }

    function reviewDraft(row) {
      return '复核 ' + row.sessionId + ' 的回报：读 ' + traceSource(row) + ' 的最新一条 reports 记录与报告，'
        + '判定是报告需修订（report_revision）、case 错（case_error）还是执行错（execution_error），'
        + '在 trace 的 reviews 里追加一条 {at: <当前时间>, by: agent, verdict: <verdict>, note: <一句依据>}，并刷新顶层 updated_at。'
        + 'report_revision 据此修订报告（同一份文件，追加修订记录）；case_error / execution_error 只落 verdict，改知识库或改 skill 不在这里做'
    }

    // 回报结果：把「来源 / 结果 / 备注」写成完整指令，并点明要写哪一条事件、哪个字段。
    function feedbackInstruction(row, values, vocab) {
      const resultKey = values && values.result ? values.result : 'from_report'
      const fromVocab = ((vocab && vocab.reportResults) || []).find((item) => item && item.value === resultKey)
      const meta = fromVocab && fromVocab.outcome
        ? { label: fromVocab.label, outcome: fromVocab.outcome }
        : (REPORT_OUTCOME_TEXT[resultKey] || REPORT_OUTCOME_TEXT.from_report)
      const source = values && values.source === 'vendor' ? 'vendor' : 'field'
      const note = String((values && values.note) || '').trim() || tr('form.noNote')
      const lines = [
        '回报 ' + row.sessionId + ' 的 fix 结果。',
        tr('form.source') + '：' + tr('source.' + source),
        tr('form.result') + '：' + meta.label,
        tr('form.note') + '：' + note,
      ]
      if (source === 'vendor') {
        lines.push('请据此在 ' + traceSource(row) + ' 顶层的 reports 里追加一条 '
          + '{at: <当前时间>, by: user, source: vendor, result: ' + resultKey + ', note: <上面「备注」那句>}，'
          + '并刷新顶层 updated_at；厂商答复不写 feedback.outcome。不要改 status。')
      } else {
        lines.push('请据此在 ' + traceSource(row) + ' 顶层的 reports 里追加一条 '
          + '{at: <当前时间>, by: user, source: field, result: ' + resultKey + ', note: <上面「备注」那句>}，'
          + '并把 feedback.outcome 改成 ' + meta.outcome + '（feedback.confirmed_at 写当前时间；feedback.case 保持原值），'
          + '刷新顶层 updated_at。不要改 status。')
      }
      return lines.join('\n')
    }

    const REVIEW_LABELS = {
      report_revision: '只修订报告描述',
      case_error: '判知识条目错',
      execution_error: '判执行错',
    }

    // 最近一次收尾：只有「当前已是终态、最后一条转移也是收尾」时才给撤销入口。
    function lastClose(row) {
      const transitions = Array.isArray(row.transitions) ? row.transitions : []
      const last = transitions.length ? transitions[transitions.length - 1] : null
      if (!last || typeof last !== 'object') return null
      const to = String(last.to || '')
      if (['resolved', 'escalated', 'archived'].indexOf(to) < 0) return null
      if (['resolved', 'escalated', 'archived'].indexOf(String(row.status || '')) < 0) return null
      return last
    }

    // 收尾清单：只在接近收尾时出现；每项的完成态都来自已有字段，不新增判断。
    function checklistFor(row, data) {
      const extra = row.extra || {}
      const derived = row.derived || {}
      const feedback = row.feedback || {}
      const sedState = String((row.sedimented || {}).state || 'none')
      const hasCase = !!row.activeCase || derived.caseKind === 'case'
      const candidateList = Array.isArray(extra.sedimentCandidateList) ? extra.sedimentCandidateList : []
      const reportEvents = Array.isArray(row.reports) ? row.reports.filter((item) => item && typeof item === 'object') : []
      // 快路不写报告、也不写沉淀候选（skills/diagnose 的报告事件说明）。用这两个现成事实判断
      // 「这单该不该有报告」，避免给快路单永远挂一条待办。
      const expectsReport = !!extra.hasReport || candidateList.length > 0
        || Number(extra.sedimentCandidates || 0) > 0 || reportEvents.length > 0
      let reportItem
      if (extra.hasReport) {
        reportItem = { key: 'report', label: tr('check.report'), done: true, state: tr('state.done'), action: '', kind: 'report' }
      } else if (expectsReport) {
        reportItem = { key: 'report', label: tr('check.report'), done: false, state: tr('state.pending'), action: tr('check.actionReport'), kind: 'report' }
      } else {
        reportItem = { key: 'report', label: tr('check.report'), done: false, na: true, state: tr('state.na'), action: '', kind: 'report' }
      }
      const items = [reportItem]
      if (hasCase || isPending(row)) {
        const outcome = String(feedback.outcome || '')
        const done = ['resolved', 'not_resolved', 'partial'].indexOf(outcome) >= 0
        items.push({
          key: 'feedback',
          label: tr('check.feedback'),
          done,
          state: done ? vocabLabel((data.vocab || {}).outcomes, outcome, OUTCOME_LABEL) : tr('state.pending'),
          action: done ? '' : tr('check.actionFeedback'),
          kind: 'feedback',
        })
      } else {
        items.push({ key: 'feedback', label: tr('check.feedback'), done: true, state: tr('state.na'), action: '', kind: '' })
      }
      const sedDone = sedState !== 'none'
      const sedReady = !sedDone && canStartSediment(row)
      items.push({
        key: 'sediment',
        label: tr('check.sediment'),
        done: sedDone,
        state: sedDone ? vocabLabel((data.vocab || {}).sedimented, sedState, SED_LABEL) : (sedReady ? tr('state.pending') : tr('state.na')),
        action: sedReady ? tr('check.actionSediment') : '',
        kind: 'sediment',
      })
      items.push({
        key: 'handoff',
        label: tr('check.handoff'),
        done: false,
        optional: true,
        state: tr('state.optional'),
        action: tr('check.actionHandoff'),
        kind: 'handoff',
      })
      return items
    }

    function shouldShowChecklist(row) {
      const derived = row.derived || {}
      const sedState = String((row.sedimented || {}).state || 'none')
      return !isOpen(row) || isPending(row) || !!derived.needSed || !!derived.needPromote || !!derived.needReview || sedState !== 'none'
    }

    // 写入历史：transitions / reports / reviews 合成一条时间线，只展示最近几条。
    function historyEntries(row, data) {
      const entries = []
      for (const item of Array.isArray(row.transitions) ? row.transitions : []) {
        if (!item || typeof item !== 'object') continue
        entries.push({
          kind: 'transition',
          at: String(item.at || ''),
          text: (STATUS_LABEL[item.from] || item.from || '?') + ' → ' + (STATUS_LABEL[item.to] || item.to || '?'),
          note: String(item.note || '') || (item.folded ? '折叠了 ' + item.folded + ' 条更早记录' : ''),
        })
      }
      for (const item of Array.isArray(row.reports) ? row.reports : []) {
        if (!item || typeof item !== 'object') continue
        const result = REPORT_OUTCOME_TEXT[item.result] ? REPORT_OUTCOME_TEXT[item.result].label : String(item.result || '')
        entries.push({
          kind: 'report',
          at: String(item.at || ''),
          text: (item.source === 'vendor' ? tr('source.vendor') : tr('source.field')) + ' · ' + result,
          note: String(item.note || ''),
        })
      }
      for (const item of Array.isArray(row.reviews) ? row.reviews : []) {
        if (!item || typeof item !== 'object') continue
        entries.push({
          kind: 'review',
          at: String(item.at || ''),
          text: REVIEW_LABELS[item.verdict] || String(item.verdict || ''),
          note: String(item.note || ''),
        })
      }
      entries.sort((left, right) => String(right.at).localeCompare(String(left.at)))
      return entries.slice(0, 6)
    }

    function referenceDraft(row, summary, evidence) {
      const evidenceText = String(evidence || '').trim()
        || ('trace 的 sediment_candidates（kind: reference）里的 evidence')
      return '用 /to-reference 把 ' + row.sessionId + ' 的 reference 候选整理成词条：' + summary
        + '。证据取 ' + evidenceText + '；来源类型、出处与适用边界先跟我确认'
        + '（来源 ' + traceSource(row) + '）'
    }

    function triageDraft(row, summary) {
      // 性质文件固定三份；诊断分类就是性质时直接点名，免得 agent 再猜（猜错会把词写进别的性质）。
      const natureFile = {
        interrupt: '10-interrupt.yaml', precision: '20-precision.yaml', performance: '30-performance.yaml',
      }[(row.extra || {}).category]
      const target = natureFile ? 'triage-tree.d/' + natureFile : 'triage-tree.d/<interrupt|precision|performance>.yaml'
      return '把 ' + row.sessionId + ' 的 triage 候选补进 ' + target + ' 的 symptoms：' + summary
        + '。性质与症状组先跟我确认；新文件要在 00-protocol.md 的 sources: 登记，改完跑 '
        + 'python3 scripts/build_triage_tree.py --check-sources，并按部署纪律重建聚合（有主干 job 就只改源文件，没有就本地重建）；'
        + '不手改生成物 triage-tree.yaml（来源 ' + traceSource(row) + '）'
    }

    function copyPathAndFlash(path, flash) {
      copyToClipboard(path).then((ok) => flash(ok ? tr('hint.copyPath') : tr('hint.copyFailed')))
    }

    function materialText(row) {
      const extra = row.extra || {}
      const items = Array.isArray(extra.missingMaterials) ? extra.missingMaterials : []
      const files = Array.isArray(extra.evidenceList) ? extra.evidenceList : []
      const lines = []
      lines.push('这单还缺以下材料（按 trace 记录）：')
      if (items.length) items.forEach((item) => lines.push('- ' + item))
      else lines.push('- ' + (extra.evidenceMissing || '（trace 未写具体缺什么）'))
      if (files.length) {
        lines.push('')
        lines.push('已有证据：')
        files.forEach((file) => lines.push('- ' + file))
      }
      lines.push('')
      lines.push('单号：' + row.sessionId + '（' + traceSource(row) + '）')
      return lines.join('\n')
    }

    function materialResumeDraft(row) {
      const extra = row.extra || {}
      const items = Array.isArray(extra.missingMaterials) ? extra.missingMaterials : []
      return resumeDraft(row) + '\n\n这单还缺这些材料（按 trace 记录），我先补：'
        + (items.length ? '\n' + items.map((item) => '- ' + item).join('\n') : extra.evidenceMissing || '')
    }

    function issueTitle(row) {
      const summary = String(row.summary || '').trim()
      const first = summary.split(/[。；;]/)[0] || row.sessionId
      if (first.length <= 80) return first
      const window = first.slice(0, 80)
      const cut = Math.max(window.lastIndexOf('，'), window.lastIndexOf('、'), window.lastIndexOf('：'), window.lastIndexOf(' '))
      return cut >= 30 ? first.slice(0, cut) + '…' : first.slice(0, 78) + '……'
    }

    // 给 issue / 群聊的纯文本：只抄 trace 已有事实，不补写结论，不加建议段落。
    function issueText(row) {
      const extra = row.extra || {}
      const lines = []
      lines.push('标题：' + issueTitle(row))
      lines.push('')
      lines.push('现象：')
      lines.push(String(row.summary || '').trim() || '（trace 未写 summary）')
      const env = []
      if (extra.platform) env.push('平台 ' + extra.platform)
      if (extra.framework) env.push('框架 ' + extra.framework)
      if (extra.category) env.push('性质 ' + (CATEGORY_LABEL[extra.category] || extra.category))
      if (row.severity) env.push('严重级 ' + (SEVERITY_LABEL[row.severity] || row.severity))
      if (env.length) {
        lines.push('')
        lines.push('环境：')
        lines.push(env.join('；'))
      }
      if (row.activeCase) {
        lines.push('')
        lines.push('相关 case：' + row.activeCase)
      }
      const files = Array.isArray(extra.evidenceList) ? extra.evidenceList : []
      if (files.length) {
        lines.push('')
        lines.push('证据：')
        files.forEach((file) => lines.push('- ' + file))
      }
      // 只在已收尾时抄结论；进行中的助手输出常含内部待办，不往外发。
      if (['resolved', 'escalated', 'archived'].indexOf(row.status) >= 0 && extra.lastOutput) {
        lines.push('')
        lines.push('结论：')
        lines.push(extra.lastOutput)
      }
      lines.push('')
      lines.push('单号：' + row.sessionId + '（' + traceSource(row) + '）')
      return lines.join('\n')
    }

    function matchesQuery(row, query) {
      const needle = String(query || '').trim().toLowerCase()
      if (!needle) return true
      const extra = row.extra || {}
      const parts = [
        row.sessionId, row.summary, row.activeCase, extra.platform, extra.framework,
        extra.lastAction, extra.lastOutput,
      ]
      if (Array.isArray(extra.excludedCases)) parts.push(extra.excludedCases.join(' '))
      if (Array.isArray(extra.evidenceList)) parts.push(extra.evidenceList.join(' '))
      return parts.filter(Boolean).join('\n').toLowerCase().includes(needle)
    }

    function timelineRoleLabel(role) {
      if (role === 'user') return tr('timeline.role.user')
      if (role === 'resume') return tr('timeline.role.resume')
      return tr('timeline.role.agent')
    }

    function timelineActionLabel(action) {
      const labels = {
        triage: '路由', triage_semantic: '语义路由', load_index: '读索引', load_full: '读候选全文',
        quickly_check: '校验候选', tier3: '深挖候选', reference_lookup: '查先验', external_lookup: '查外部',
        run_check: '跑检查', report: '产出报告', resume: '续接', feedback: '回报',
        attribution: '归因', procedure_follow: '按流程', hit: '命中', miss: '未命中',
        output: '输出', source_analysis: '源码分析',
      }
      return labels[action] || action || ''
    }

    function sessionLinkCommand(row) {
      return 'python3 scripts/link_harness_sessions.py --trace ' + row.file
        + ' --session-id "$DSH_SESSION_ID" --apply'
    }

    function openSessionWithFlash(id, flash) {
      if (!id) {
        flash(tr('hint.sessionNoId'))
        return
      }
      const report = (result) => {
        if (result && result.ok) return flash(tr('hint.sessionOpened'))
        const reason = String((result && result.reason) || '')
        if (/没有会话号/.test(reason)) return flash(tr('hint.sessionNoId'))
        if (/没有可用的打开会话接口|会话服务不可用/.test(reason)) return flash(tr('hint.sessionService'))
        return flash(tr('hint.sessionRemote'))
      }
      ctxOpenSession(id).then(report, (error) => {
        report({ ok: false, reason: String((error && error.message) || error) })
      })
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

    function IconPin(props) {
      return h('svg', { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': 'true', fill: props && props.on ? 'currentColor' : 'none', stroke: 'currentColor', strokeWidth: 1.4, strokeLinecap: 'round', strokeLinejoin: 'round' },
        h('path', { d: 'M6 2.2h4l-.5 3.1 2 2v1.2H4.5V7.3l2-2L6 2.2z' }),
        h('path', { d: 'M8 8.7v5.1', fill: 'none' }))
    }

    // ── 沉淀队列的小工具（只排版，不判状态；状态来自 sediment_state.py）──────
    const SED_CHIP_TONE = { warn: 'warn', bad: 'error', accent: 'brand', ok: 'success', gray: '' }
    const SED_DOT = { warn: 'var(--scp-warn)', bad: 'var(--scp-bad)', accent: 'var(--scp-accent)', ok: 'var(--scp-ok)', gray: 'var(--scp-faint)' }

    function sedGroupOf(draft) {
      const state = String((draft && draft.state) || '')
      if (state === 'decided') return 'pr'
      if (state === 'pr_closed') return 'groom'
      if (state === 'pr_open' || state === 'pr_merged') return 'check'
      if (state === 'pr_closed' || state === 'orphan' || state === 'done' || state === 'deferred' || state === 'rejected') return 'other'
      return 'groom'
    }

    function sedAgeText(draft) {
      const age = draft && draft.ageDays
      if (age === null || age === undefined || Number.isNaN(Number(age))) return tr('sediment.ageUnknown')
      return tr('sediment.age', { n: Number(age) })
    }

    // 五步轨：每一步只回答「做到了没」，证据由 sediment_state.py 拼好。
    function sedSteps(draft) {
      const state = String((draft && draft.state) || '')
      const novelty = draft && draft.novelty
      const decisionValid = Boolean(draft && draft.decisionValid)
      const pr = draft && draft.pr
      const rerun = state === 'need_rerun'
      const assessed = Boolean(draft && (draft.assessed || novelty))
      const prState = pr ? String(pr.state || 'unknown') : ''
      // 「已升格」只认 trace/队列的 done；promotion.casePath 可能只是 variant/covered 的候选 case，
      // 不能拿它当本次升格已完成。
      const promoted = state === 'done'
      const created = draft && draft.createdAt ? formatTime(draft.createdAt) : ''
      const assessedNote = (draft && draft.assessedShort) ? draft.assessedShort : (assessed && draft.confidence ? String(draft.confidence) : '')
      return [
        { key: 'draft', label: tr('sediment.stepper.draft'), state: 'done', note: created },
        { key: 'assessed', label: tr('sediment.stepper.assessed'), state: rerun ? 'blocked' : (assessed ? 'done' : (state === 'unassessed' ? 'current' : 'unknown')), note: assessedNote },
        { key: 'decided', label: tr('sediment.stepper.decided'), state: decisionValid ? 'done' : (state === 'need_decision' ? 'current' : 'unknown'), note: decisionValid && draft.decision ? String(draft.decision) : '' },
        { key: 'pr', label: tr('sediment.stepper.pr'), state: pr ? 'done' : (state === 'decided' ? 'current' : 'unknown'), note: pr && pr.number ? '#' + pr.number : '' },
        { key: 'promoted', label: tr('sediment.stepper.promoted'), state: promoted ? 'done' : (prState === 'merged' ? 'current' : 'unknown'), note: prState === 'merged' && !promoted ? tr('sediment.stepper.pending') : '' },
      ]
    }

    function sedPrimaryKey(draft) {
      const next = draft && draft.next ? String(draft.next.kind || '') : ''
      return ['groom', 'pr', 'check', 'close', 'restore'].indexOf(next) >= 0 ? next : ''
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
        // 文件名以轨迹自己的 file 为准：session_id 与文件名 stem 不一致时，
        // 用 sessionId 拼名会去写/读另一个文件。
        traceFile: row.file || (row.sessionId + '.yaml'),
        tracesDir: (data && data.tracesDir) || '',
        schemeVersion: (data && data.schemeVersion) || '',
        expectSha256: row.contentSha256,
        traceError: row.error ? String(row.error) : '',
      }, extra || {})
    }

    // trace_transition.py 的 positional 是**单号 stem**（脚本自己按 `<单号>.yaml` 拼路径），
    // 不是文件名：把 `x.yaml` 当 positional 传进去，脚本会去找 `x.yaml.yaml` 并报 E_NOT_FOUND。
    function traceStemOf(row) {
      const name = String((row && row.file) || (row && row.sessionId) || '')
      const base = name.replace(/\\/g, '/').split('/').pop() || ''
      return base.replace(/\.ya?ml$/i, '')
    }

    // UTF-8 文本 → base64 单行 ASCII。给 `--payload-base64` 用：换行、引号与中文都不经过
    // shell 的引号规则，bash / zsh / PowerShell / cmd 粘贴结果一致。
    function base64Utf8(text) {
      const bytes = new TextEncoder().encode(String(text))
      let binary = ''
      for (const byte of bytes) binary += String.fromCharCode(byte)
      return btoa(binary)
    }

    // 面板写不进这一单（沙箱或文件权限拒绝）时，会话里的 shell 往往仍能写。生成一条
    // 可直接执行的指令：写哪份 trace、改成什么、CAS 指纹、要填的字段一次交代全。
    // 字段走 --payload-base64（脚本为「复制到任意终端」留的通道），会改变校验路径的
    // 标志留在命令行。只填进输入框，不自动发送。
    function writeFallbackDraft(row, payload, message) {
      const p = payload || {}
      const target = String(p.to || '')
      let statusText
      if (p.kind === 'reopen') statusText = '进行中（in_progress）'
      else if (p.kind === 'sedimented') statusText = '不改状态，只改沉淀状态'
      else if (p.kind === 'backfill-ending') statusText = '不改状态，只补记收尾方式'
      else statusText = (STATUS_LABEL[target] || target || '未指定') + '（' + target + '）'
      const fields = []
      const addField = (name, value) => {
        if (value === undefined || value === null || value === '') return
        fields.push(name + '=' + (typeof value === 'string' ? JSON.stringify(value) : String(value)))
      }
      addField('summary', p.summary)
      addField('severity', p.severity)
      if (p.fix_emitted === true || p.fix_emitted === false) addField('fix_emitted', p.fix_emitted ? 'true' : 'false')
      addField('ending.kind', p.endingKind)
      addField('ending.handed_to', p.handedTo)
      addField('ending.duplicate_of', p.duplicateOf)
      if (p.kind === 'sedimented') {
        addField('sedimented.state', p.state)
        addField('sedimented.case_id', p.caseId)
      }
      // payload 的键名按 trace_transition.py 的 --payload-base64 映射来：`kind` 是收尾方式，
      // 动作类型由命令行标志表达。`handed_to` / `duplicate_of` 是脚本认识的写法。
      const body = {}
      const flags = []
      const addEnding = () => {
        if (p.endingKind) body.kind = String(p.endingKind)
        if (p.handedTo) body.handed_to = String(p.handedTo)
        if (p.duplicateOf) body.duplicate_of = String(p.duplicateOf)
      }
      if (p.kind === 'reopen') {
        body.reopen = true
      } else if (p.kind === 'sedimented') {
        flags.push('--field sedimented')
        if (p.state) flags.push('--state ' + String(p.state))
        if (p.caseId) flags.push('--case-id ' + String(p.caseId))
      } else if (p.kind === 'backfill-ending') {
        flags.push('--backfill-ending')
        addEnding()
      } else {
        if (p.kind === 'correct-ending') flags.push('--correct-ending')
        body.to = target
        addEnding()
        if (p.summary !== undefined) body.summary = String(p.summary)
        if (p.severity !== undefined) body.severity = String(p.severity)
        if (p.fix_emitted === true || p.fix_emitted === false) body.fix_emitted = p.fix_emitted
      }
      const sha = String(row.contentSha256 || '')
      const stem = traceStemOf(row)
      const token = base64Utf8(JSON.stringify(body))
      const lines = [
        '面板写不进这一单（文件操作被系统拒绝）。请代我把它写进 trace。',
        'trace 文件：' + traceSource(row),
        '目标状态：' + statusText,
        '--expect-sha256：' + sha,
      ]
      if (fields.length) lines.push('要填的字段：' + fields.join('；'))
      lines.push('面板记录的原因：' + String(message || ''))
      lines.push('复制到工作区根目录执行：')
      lines.push('python3 scripts/trace_transition.py ' + stem
        + ' --by user --source panel --json --payload-base64 ' + token
        + ' --expect-sha256 ' + sha
        + (flags.length ? ' ' + flags.join(' ') : ''))
      lines.push('--payload-base64 是脚本给「复制到任意终端」用的参数：单行 ASCII，bash / zsh / PowerShell / cmd 都能粘。')
      lines.push('旧指纹会被 CAS 拦下：先刷新这一单再重填。')
      return lines.join('\n')
    }

    function WriteForm(props) {
      const { form, row, onSubmit, onCancel, busy, error } = props
      const [values, setValues] = React.useState(() => {
        const initial = {}
        for (const field of form.fields) {
          if (field.value !== undefined) initial[field.name] = field.value
          else if (field.type === 'select' && !field.emptyValue && Array.isArray(field.options) && field.options.length) {
            // 下拉框必须落一个真值：浏览器会把空 value 显示成第一项，但状态里仍是空串，
            // 提交时该字段就不会进 payload（归档收尾因此缺 ending.kind）。
            initial[field.name] = String(field.options[0].value === undefined ? '' : field.options[0].value)
          } else if (field.name === 'severity') initial[field.name] = row.severity || ''
          else if (field.name === 'fixEmitted') {
            // 取 trace 现有值；没有记录才回落到 true。默认值会写回收尾记录，
            // 把 fix_emitted 从 false 翻成 true 会改变「等上游」的判定。
            const recorded = row.extra && row.extra.fixEmitted
            initial[field.name] = recorded === true || recorded === false ? String(recorded) : ''
          }
          else if (field.name === 'state') initial[field.name] = (row.sedimented && row.sedimented.state) || 'none'
          else if (field.name === 'source') initial[field.name] = 'field'
          else if (field.name === 'result') initial[field.name] = 'from_report'
          else initial[field.name] = ''
        }
        return initial
      })
      // 必填项缺值：给一行说明，不要按了提交像没反应。
      const [localError, setLocalError] = React.useState('')
      function change(name, value) {
        if (localError) setLocalError('')
        setValues((prev) => Object.assign({}, prev, { [name]: value }))
      }
      function submit(event) {
        if (event) event.preventDefault()
        const missing = form.fields.filter((field) => field.required
          && (!field.showWhen || field.showWhen(values))
          && !String(values[field.name] || '').trim())
        if (missing.length) {
          setLocalError(tr('form.required', { fields: missing.map((field) => field.label).join('、') }))
          return
        }
        setLocalError('')
        onSubmit(values)
      }
      const preview = typeof form.preview === 'function' ? form.preview(values) : ''
      // 打开表单后焦点落在第一个可见输入位：否则旧按钮被卸载、焦点回 body，
      // 状态条上的 Esc 收不到，键盘用户要 Tab 从页首重走。
      const firstVisible = form.fields.find((field) => !field.showWhen || field.showWhen(values)) || null
      return h('form', { className: 'scp-form', onSubmit: submit },
        form.note ? h('div', { className: 'scp-form-hint' }, form.note) : null,
        form.fields.map((field) => {
          if (field.showWhen && !field.showWhen(values)) return null
          const label = h('span', { className: 'scp-field-label' }, field.label + (field.required ? ' *' : ''))
          if (field.type === 'select') {
            return h('label', { key: field.name, className: 'scp-field' }, label,
              h('select', {
                className: 'scp-select',
                autoFocus: field === firstVisible,
                value: values[field.name],
                onChange: (event) => change(field.name, event.target.value),
              },
                field.emptyValue && String(field.placeholder || '')
                  ? h('option', { value: '' }, field.placeholder)
                  : null,
                field.options.map((option) => h('option', { key: String(option.value), value: option.value }, option.label))))
          }
          if (field.type === 'textarea') {
            return h('label', { key: field.name, className: 'scp-field' }, label,
              h('textarea', {
                className: 'scp-textarea',
                autoFocus: field === firstVisible,
                value: values[field.name],
                placeholder: field.placeholder || '',
                onChange: (event) => change(field.name, event.target.value),
              }))
          }
          return h('label', { key: field.name, className: 'scp-field' }, label,
            h('input', {
              className: 'scp-input',
              type: 'text',
              autoFocus: field === firstVisible,
              value: values[field.name],
              placeholder: field.placeholder || '',
              onChange: (event) => change(field.name, event.target.value),
            }),
            field.hint ? h('span', { className: 'scp-form-hint' }, field.hint) : null)
        }),
        preview ? h('div', { className: 'scp-preview' },
          h('span', { className: 'scp-preview-label' }, tr('form.preview')),
          h('pre', { className: 'scp-preview-text' }, preview)) : null,
        error || localError ? h('div', { className: 'scp-form-error' }, error || localError) : null,
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
      // 表单打开时冻结内容指纹：菜单可能开着很久，期间 trace 被别的 agent / 面板改过。
      // 用提交那一刻的新指纹做 CAS 会把屏幕上的旧值直接盖上去；用打开时的指纹，
      // 冲突会返回 E_STATE_CHANGED，读者刷新后重填。
      const expectAtOpen = React.useRef(row.contentSha256)
      // 上一次提交的写入参数：权限类失败时据此生成兜底指令（不靠回读表单状态）。
      const attemptRef = React.useRef(null)
      const [fallback, setFallback] = React.useState('')

      function feedbackForm() {
        return {
          kind: 'feedback',
          title: tr('action.feedback'),
          submitLabel: tr('form.fill'),
          fields: [
            {
              name: 'result', type: 'select', label: tr('form.result'),
              options: reportResultOptions(),
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
          preview: (values) => feedbackInstruction(row, values, vocab),
        }
      }

      // 选项都优先取投影里的词表（trace-status.yaml 是唯一来源）；没有该段时用常量兜底。
      function sedimentStateOptions() {
        const list = Array.isArray(vocab.sedimented) ? vocab.sedimented : []
        if (list.length) return list.map((item) => ({ value: String(item.value), label: String(item.label || item.value) }))
        return SEDIMENT_STATE_KEYS.map((key) => ({ value: key, label: tr('sediment.' + key) }))
      }
      function reportResultOptions() {
        const list = Array.isArray(vocab.reportResults) ? vocab.reportResults : []
        if (list.length) return list.map((item) => ({ value: String(item.value), label: String(item.label || item.value) }))
        return REPORT_RESULT_KEYS.map((key) => ({ value: key, label: tr(key === 'none' ? 'report.resultNone' : 'report.' + key) }))
      }
      function archivedEndingOptions() {
        const list = Array.isArray(vocab.endings)
          ? vocab.endings.filter((item) => Array.isArray(item.statuses) && item.statuses.indexOf('archived') >= 0)
          : []
        if (list.length) return list.map((item) => ({ value: String(item.value), label: String(item.label || item.value) }))
        return ARCHIVED_ENDING_KEYS.map((key) => ({ value: key, label: tr('ending.' + key) }))
      }

      // 收尾方式的附加必填：转交要填人，重复要填被重复的单。两个都按当前选择显示，
      // 校验走下面的 required + showWhen。
      function endingExtraFields() {
        return [
          {
            name: 'handedTo', type: 'text', label: tr('form.handedTo'), required: true,
            hint: tr('form.handedToHint'), showWhen: (values) => values.ending === 'handed_off',
          },
          {
            name: 'duplicateOf', type: 'text', label: tr('form.duplicateOf'), required: true,
            hint: tr('form.duplicateOfHint'), showWhen: (values) => values.ending === 'duplicate',
          },
        ]
      }

      function endingOptions(choices) {
        return (Array.isArray(choices) ? choices : []).map((item) => ({
          value: String(item.value), label: String(item.label || item.value),
        }))
      }

      // 改收尾方式：目标状态由投影的 actions.targets 给出，字段按该目标的 fillable 拼；
      // 换状态时脚本会先写一条「重新打开」再收尾，历史可回放。
      function correctEndingForm(target) {
        const fields = [
          {
            name: 'ending', type: 'select', label: tr('form.ending'), required: true,
            options: endingOptions(target.endingChoices),
          },
          {
            name: 'summary', type: 'textarea', label: tr('form.summary'), required: true,
            value: row.summary || '', placeholder: tr('form.summaryHint'),
          },
        ]
        const fillable = Array.isArray(target.fillable) ? target.fillable : []
        if (fillable.indexOf('severity') >= 0) {
          fields.push({
            name: 'severity', type: 'select', label: tr('form.severity'), required: true,
            emptyValue: true, placeholder: tr('form.pick'),
            options: (vocab.severities || []).map((item) => ({ value: item.value, label: item.label })),
          })
        }
        if (fillable.indexOf('fix_emitted') >= 0) {
          fields.push({
            name: 'fixEmitted', type: 'select', label: tr('form.fixEmitted'), required: true,
            emptyValue: true, placeholder: tr('form.pick'),
            options: [{ value: 'true', label: tr('form.yes') }, { value: 'false', label: tr('form.no') }],
          })
        }
        fields.push(...endingExtraFields())
        return {
          kind: 'correct-ending',
          to: String(target.to || ''),
          title: tr('action.correctEnding') + '：' + String(target.label || target.to || ''),
          fields,
        }
      }

      // 补记收尾方式：只写当前状态的收尾方式，不动状态与收尾时间。
      function backfillEndingForm(action) {
        const fields = [
          {
            name: 'ending', type: 'select', label: tr('form.ending'), required: true,
            options: endingOptions(action.endingChoices),
          },
          ...endingExtraFields(),
        ]
        return { kind: 'backfill-ending', title: tr('action.backfillEnding'), fields }
      }

      const [form, setForm] = React.useState(() => (autoForm === 'feedback' ? feedbackForm() : null))
      const [busy, setBusy] = React.useState(false)
      const [error, setError] = React.useState('')

      function finish(result, successText) {
        setBusy(false)
        setFallback('')
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
        // 权限类失败：面板写不进去，但会话里的 shell 可能仍能写。给「生成指令」入口，
        // 不自动发送、不把错误当成不可修复。
        if (code === 'E_PERM') {
          setFallback(writeFallbackDraft(row, attemptRef.current, result && result.message))
        }
        const scriptMessage = String((result && result.message) || '')
        // 脚本的文件级拒绝已经带路径与系统原因：直接显示，避免「写入失败：文件操作被系统拒绝：」叠加。
        if (code === 'E_PERM' && scriptMessage.indexOf('文件操作被系统拒绝') === 0) {
          setError(scriptMessage)
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
        setFallback('')
        attemptRef.current = extraPayload || null
        const payload = Object.assign({}, extraPayload || {})
        if (form && expectAtOpen.current) payload.expectSha256 = expectAtOpen.current
        const promise = rpcCall('copilot-transition', transitionPayload(row, data, payload))
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
        copyToClipboard(item.text).then((ok) => onFlash(ok ? (item.message || tr('hint.copied')) : tr('hint.copyFailed')))
      }

      function openForm(next) {
        setError('')
        setFallback('')
        setForm(next)
      }

      // 权限类失败后的兜底：指令先填进输入框，读者自己按 Enter 发送。
      function fallbackBlock() {
        if (!fallback) return null
        return h('div', {
          className: 'scp-fallback',
          style: { display: 'flex', flexDirection: 'column', gap: '6px', padding: '6px' },
        },
          h('div', { className: 'scp-form-hint' }, tr('write.permissionHint')),
          h('button', {
            type: 'button',
            className: 'scp-btn scp-btn--ghost',
            onClick: () => fillAndClose(fallback),
          }, tr('write.permissionRetry')))
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
                fillAndClose(feedbackInstruction(row, values, vocab))
                return
              }
              if (form.kind === 'close:resolved') {
                run({
                  kind: 'close',
                  to: 'resolved',
                  endingKind: 'root_cause',
                  summary: values.summary,
                  severity: values.severity,
                  fix_emitted: values.fixEmitted === 'true',
                })
              } else if (form.kind === 'close:escalated') {
                run({ kind: 'close', to: 'escalated', endingKind: 'handed_off', handedTo: values.handedTo, summary: values.summary })
              } else if (form.kind === 'close:archived') {
                run({ kind: 'close', to: 'archived', endingKind: values.ending, duplicateOf: values.duplicateOf, summary: values.summary })
              } else if (form.kind === 'correct-ending') {
                run({
                  kind: 'correct-ending',
                  to: form.to,
                  endingKind: values.ending,
                  handedTo: values.handedTo,
                  duplicateOf: values.duplicateOf,
                  summary: values.summary,
                  severity: values.severity,
                  fix_emitted: values.fixEmitted === undefined ? undefined : values.fixEmitted === 'true',
                })
              } else if (form.kind === 'backfill-ending') {
                run({
                  kind: 'backfill-ending',
                  endingKind: values.ending,
                  handedTo: values.handedTo,
                  duplicateOf: values.duplicateOf,
                })
              } else if (form.kind === 'sedimented') {
                run({ kind: 'sedimented', state: values.state, caseId: values.caseId },
                  tr('write.doneSediment', { state: tr('sediment.' + values.state) }))
              }
            },
          }),
          fallbackBlock())
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
      if (canStartSediment(row)) {
        settleItems.push({
          key: 'sediment',
          label: tr('action.sediment'),
          note: derived.needSed ? '' : tr('sediment.noteNoCandidate'),
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
      if (derived.needReportReview) {
        settleItems.push({
          key: 'review',
          label: tr('action.review'),
          onSelect: () => fillAndClose(reviewDraft(row)),
        })
      }
      if (settleItems.length) groups.push({ key: 'settle', title: tr('group.settle'), items: settleItems })

      // 收尾三项只对还开着的单出现：终态单再点会被 trace_transition.py 解释成
      // correct-ending，静默重写收尾方式与 severity / fix_emitted。改收尾方式另有入口，
      // 当前版本先不给，避免误写。
      const stateItems = []
      if (isOpen(row)) stateItems.push(
        {
          key: 'close:resolved', label: tr('close.resolved'), disabled: !canWrite,
          onSelect: () => openForm({
            kind: 'close:resolved',
            title: tr('close.resolved'),
            note: (row.activeCase || derived.caseKind === 'case') && !String(feedback.outcome || '').trim()
              ? tr('form.feedbackFirst') : '',
            fields: [
              { name: 'summary', type: 'textarea', label: tr('form.summary'), required: true, value: row.summary || '', placeholder: tr('form.summaryHint') },
              {
                name: 'severity', type: 'select', label: tr('form.severity'), required: true,
                emptyValue: true, placeholder: tr('form.pick'),
                options: (vocab.severities || []).map((item) => ({ value: item.value, label: item.label })),
              },
              {
                name: 'fixEmitted', type: 'select', label: tr('form.fixEmitted'), required: true,
                emptyValue: true, placeholder: tr('form.pick'),
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
            fields: [
              { name: 'summary', type: 'textarea', label: tr('form.summary'), required: true, value: row.summary || '', placeholder: tr('form.summaryHint') },
              { name: 'handedTo', type: 'text', label: tr('form.handedTo'), required: true, hint: tr('form.handedToHint') },
            ],
          }),
        },
        {
          key: 'close:archived', label: tr('close.archived'), disabled: !canWrite,
          onSelect: () => openForm({
            kind: 'close:archived',
            title: tr('close.archived'),
            fields: [
              { name: 'summary', type: 'textarea', label: tr('form.summary'), required: true, value: row.summary || '', placeholder: tr('form.summaryHint') },
              {
                name: 'ending', type: 'select', label: tr('form.ending'), required: true,
                options: archivedEndingOptions(),
              },
              {
                name: 'duplicateOf', type: 'text', label: tr('form.duplicateOf'), required: true,
                hint: tr('form.duplicateOfHint'),
                showWhen: (values) => values.ending === 'duplicate',
              },
            ],
          }),
        },
      )
      if (!isOpen(row)) {
        stateItems.push({
          key: 'reopen', label: tr('reopen'), disabled: !canWrite,
          onSelect: () => run({ kind: 'reopen' }),
        })
        // 终态单的「改收尾方式 / 补记收尾方式」：动作与可选目标都来自投影的 actions，
        // 不在界面里重算状态机；没有 actions 的旧投影就不显示。
        const rowActions = Array.isArray(row.actions) ? row.actions : []
        const correct = rowActions.find((item) => item && item.id === 'correct-ending')
        if (correct && Array.isArray(correct.targets)) {
          for (const target of correct.targets) {
            if (!Array.isArray(target.endingChoices) || !target.endingChoices.length) continue
            stateItems.push({
              key: 'correct:' + String(target.to || ''),
              label: tr('action.correctEnding') + '：' + String(target.label || target.to || ''),
              disabled: !canWrite,
              onSelect: () => openForm(correctEndingForm(target)),
            })
          }
        }
        const backfill = rowActions.find((item) => item && item.id === 'backfill-ending')
        if (backfill && Array.isArray(backfill.endingChoices) && backfill.endingChoices.length) {
          stateItems.push({
            key: 'backfill', label: tr('action.backfillEnding'), disabled: !canWrite,
            onSelect: () => openForm(backfillEndingForm(backfill)),
          })
        }
      }
      stateItems.push({
        key: 'sedimented', label: tr('action.sedimentState'), disabled: !canWrite,
        onSelect: () => openForm({
          kind: 'sedimented',
          title: tr('form.state'),
          fields: [
            {
              name: 'state', type: 'select', label: tr('form.state'),
              options: sedimentStateOptions(),
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
        }, {
          key: 'issue',
          label: tr('copy.issue'),
          onSelect: () => copyItem({ text: issueText(row), message: tr('hint.copiedIssue') }),
        }, {
          key: 'resume-copy',
          label: tr('action.copyResume'),
          onSelect: () => copyItem({ text: resumeDraft(row) }),
        }],
      })

      const navItems = []
      if (store.sessionId) {
        navItems.push({
          key: 'pin',
          label: pinnedIdFor(store.sessionId) === row.sessionId ? tr('action.unpin') : tr('action.pin'),
          onSelect: () => {
            const isPinned = pinnedIdFor(store.sessionId) === row.sessionId
            setPin(store.sessionId, isPinned ? '' : row.sessionId)
            onFlash(isPinned ? tr('hint.unpinned') : tr('hint.pinned'))
            if (onClose) onClose()
          },
        })
      }
      navItems.push(
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
      )
      if (row.harnessSession) {
        navItems.push({
          key: 'open-origin',
          label: tr('action.openOrigin'),
          onSelect: () => { if (onClose) onClose(); openSessionWithFlash(row.harnessSession, onFlash) },
        })
      }
      const resumedSessions = (row.resumeSessions || []).filter((sid) => sid && sid !== store.sessionId)
      if (resumedSessions.length) {
        navItems.push({
          key: 'open-resumed',
          label: tr('action.openResumed'),
          onSelect: () => { if (onClose) onClose(); openSessionWithFlash(resumedSessions[resumedSessions.length - 1], onFlash) },
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
            role: 'menuitem',
            className: 'scp-menu-item',
            disabled: !!item.disabled,
            title: item.disabled ? disabledReason : undefined,
            onClick: item.onSelect,
          }, item.label, item.note ? h('span', { className: 'scp-menu-note' }, item.note) : null)))),
        error ? h('div', { className: 'scp-form-error', style: { padding: '4px 6px' } }, error) : null,
        fallbackBlock())
    }

    // ── 面 1：状态条 ───────────────────────────────────────────────────────
    // 安静的一行：状态点 + 可点的跟踪范围 + 人读案例标题 + 状态 + 进度 + 一个主操作。
    // 默认收起（偏好可改），第二行（元信息 / 在等什么 / 身份标签）按需展开。
    // 左端的范围标签同时是选择器：可以把这一栏固定到任意一单，而不是只跟「最近一单」。
    // 输入类元素：点进这里不收起状态条，否则收起让输入区上移，正在定位光标的点击会被带偏。
    function isEditableTarget(target) {
      if (!target) return false
      const tag = String(target.tagName || '').toUpperCase()
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
      return target.isContentEditable === true
    }

    // 浮层（菜单 / 选择器）的内联尺寸与方向：默认向上；上方放不下且下方更宽裕时向下。
    // 高度按可用空间收，避免被滚动容器裁掉或盖住状态条本身。
    function popoverPlacement(anchor, minHeight, maxHeight) {
      if (!anchor) return null
      const gap = 8
      const margin = 8
      const clipTop = Math.max(0, Number(anchor.clipTop) || 0)
      const spaceAbove = Math.max(0, anchor.top - clipTop - margin)
      const spaceBelow = Math.max(0, anchor.viewHeight - anchor.bottom - margin)
      const down = spaceAbove < minHeight && spaceBelow > spaceAbove
      const room = down ? spaceBelow : spaceAbove
      const height = Math.max(minHeight, Math.min(maxHeight, room))
      const style = { maxHeight: Math.round(height) }
      if (down) {
        style.top = 'calc(100% + ' + gap + 'px)'
        style.bottom = 'auto'
      } else {
        style.bottom = 'calc(100% + ' + gap + 'px)'
        style.top = 'auto'
      }
      return style
    }

    function makeDock() {
      return function Dock(props) {
        const s = useStore()
        useSessionSync(props)
        const [menuOpen, setMenuOpen] = React.useState(false)
        const [menuForm, setMenuForm] = React.useState(null)
        const [pickerOpen, setPickerOpen] = React.useState(false)
        const [idle, setIdle] = React.useState(false)
        const [flashStep, setFlashStep] = React.useState('')
        const idleTimer = React.useRef(null)
        const flashTimer = React.useRef(null)
        const stepRef = React.useRef({ id: '', step: 0 })
        const lastBump = React.useRef(0)
        const [query, setQuery] = React.useState('')
        const [hint, setHint] = React.useState('')
        const hintTimer = React.useRef(null)
        const inputRef = React.useRef(null)
        const rootRef = React.useRef(null)
        const handleRef = React.useRef(null)
        // 菜单/选择器刚被点击关闭的时刻：同一次手势不顺手收起状态条，过期自动失效
        const menuDismissedAtRef = React.useRef(0)
        // 这次手势是否起于状态条内部。必须在 mousedown（capture）时记：菜单项点击会把按钮
        // 从 DOM 里换掉，等 click 冒到 document 时 target 已 detached，contains(target) 为假，
        // 「点外部收起」就会把刚展开的表单一起收起——用户看到的是「点了没反应」。
        const gestureInsideRef = React.useRef(false)
        // 菜单/选择器按视口可用空间定位置：向上展开放不下时改向下并限高，避免被滚动容器
        // 裁掉、被应用顶栏盖住（被盖住的部分点不到）。
        const [anchor, setAnchor] = React.useState(null)
        // 键盘收起后把焦点放回收起态胶囊，别落回 body
        const restoreFocusRef = React.useRef(false)

        const flash = React.useCallback((text) => {
          setHint(text)
          if (hintTimer.current) clearTimeout(hintTimer.current)
          hintTimer.current = setTimeout(() => setHint(''), 4600)
        }, [])

        React.useEffect(() => () => {
          if (hintTimer.current) clearTimeout(hintTimer.current)
        }, [])

        // 切会话时收起内层：旧菜单/表单纯属上一条单的状态，留着会在新单上重新弹出，
        // 提交时写到另一单。
        React.useEffect(() => {
          setMenuOpen(false)
          setMenuForm(null)
          setPickerOpen(false)
        }, [s.sessionId])

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
            // 变淡只改 opacity，不属于「动效」；reduced-motion 只让 CSS 取消过渡
            // （变淡瞬间生效），不取消这件事本身。Windows 关闭「动画效果」时
            // Chromium 会报 prefers-reduced-motion: reduce，旧逻辑因此完全不淡出。
            if (idleRef.current.collapsed) setIdle(true)
          }, 2800)
        }, [])

        React.useEffect(() => {
          if (s.prefs.dockCollapsed) return undefined
          if (s.sediment.phase === 'idle') refreshSediment(false)
          return undefined
        }, [s.prefs.dockCollapsed, s.sediment.phase])

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
          if (flashTimer.current) clearTimeout(flashTimer.current)
        }, [])

        // 步骤前进时让状态点轻闪一次；只在同一单上比较，首屏不闪。
        React.useEffect(() => {
          const current = store.data && store.data.ok !== false ? store.data : null
          if (!current) return undefined
          const all = current.all || []
          const pinned = pinnedIdFor(store.sessionId)
          const picked = (pinned && all.find((row) => row.sessionId === pinned))
            || current.bound || (current.recent && current.recent[0]) || null
          if (!picked) return undefined
          const step = Number((picked.extra || {}).currentStep) || 0
          const previous = stepRef.current
          if (previous.id === picked.sessionId && previous.step > 0 && step > previous.step) {
            setFlashStep(previous.step + '→' + step)
            if (flashTimer.current) clearTimeout(flashTimer.current)
            flashTimer.current = setTimeout(() => setFlashStep(''), 1500)
          }
          stepRef.current = { id: picked.sessionId, step }
          return undefined
        }, [s.data, s.sessionId])

        // ⌘⇧D / Ctrl+Shift+D 打开诊断总览；⌘K / Ctrl+K 打开总览并进入命令面板。
        React.useEffect(() => {
          const onKey = (event) => {
            const key = String(event.key || '').toLowerCase()
            const mod = event.metaKey || event.ctrlKey
            if (!mod) return
            if (key === 'k') {
              event.preventDefault()
              const current = store.data && store.data.ok !== false ? store.data : null
              if (!current) return
              const all = current.all || []
              const pinned = pinnedIdFor(store.sessionId)
              const picked = (pinned && all.find((row) => row.sessionId === pinned))
                || current.bound || (current.recent && current.recent[0]) || null
              commandRequested = true
              setPaletteOpen(true, picked ? picked.sessionId : '')
              return
            }
            if (key !== 'd' || !event.shiftKey) return
            event.preventDefault()
            const current = store.data && store.data.ok !== false ? store.data : null
            if (!current) return
            const all = current.all || []
            const pinned = pinnedIdFor(store.sessionId)
            const picked = (pinned && all.find((row) => row.sessionId === pinned))
              || current.bound || (current.recent && current.recent[0]) || null
            setPaletteOpen(true, picked ? picked.sessionId : '')
          }
          window.addEventListener('keydown', onKey)
          return () => window.removeEventListener('keydown', onKey)
        }, [])

        // 欠回报时把数量挂到页面标题前缀，切走再回来能看见；不弹窗。
        const pendingCount = s.data && s.data.counts ? Number(s.data.counts.pendingFeedback) || 0 : 0
        React.useEffect(() => {
          if (typeof document === 'undefined') return undefined
          const apply = () => {
            const current = String(document.title || '')
            const plain = current.replace(/^\[\d+\]\s*/, '')
            document.title = pendingCount > 0 ? '[' + pendingCount + '] ' + plain : plain
          }
          apply()
          let observer = null
          let selfMutated = false
          try {
            const node = typeof document.querySelector === 'function' ? document.querySelector('title') : null
            if (node && typeof MutationObserver !== 'undefined') {
              observer = new MutationObserver(() => {
                if (selfMutated) { selfMutated = false; return }
                selfMutated = true
                apply()
              })
              observer.observe(node, { childList: true, characterData: true, subtree: true })
            }
          } catch {
            observer = null
          }
          return () => {
            if (observer) observer.disconnect()
            // 只摘自己加的前缀，不写回捕获时的旧标题（期间可能已切过会话）。
            document.title = String(document.title || '').replace(/^\[\d+\]\s*/, '')
          }
        }, [pendingCount])

        React.useEffect(() => {
          if (!pickerOpen) return undefined
          const node = inputRef.current
          if (node && typeof node.focus === 'function') node.focus()
          return undefined
        }, [pickerOpen])

        React.useEffect(() => {
          if (!menuOpen && !pickerOpen) return undefined
          const onDown = (event) => {
            if (insideDock(event)) return
            // 先关菜单/选择器；同一次手势不顺手收起状态条（click 处理器看这个时刻）
            menuDismissedAtRef.current = Date.now()
            setMenuOpen(false)
            setPickerOpen(false)
          }
          document.addEventListener('mousedown', onDown)
          return () => document.removeEventListener('mousedown', onDown)
        }, [menuOpen, pickerOpen])

        // 菜单/选择器开合时量一次锚点，并在窗口尺寸、滚动变化时重算。
        // 量不到的宿主（没有布局的测试替身）保持 CSS 默认位置，不影响状态逻辑。
        React.useEffect(() => {
          if (!menuOpen && !pickerOpen) {
            setAnchor(null)
            return undefined
          }
          function measure() {
            const node = rootRef.current
            if (!node || typeof node.getBoundingClientRect !== 'function') return null
            let rect = null
            try { rect = node.getBoundingClientRect() } catch { rect = null }
            if (!rect) return null
            const view = typeof window !== 'undefined' ? window : {}
            const viewHeight = Number(view.innerHeight) || 0
            // 最近的可裁剪祖先（滚动容器 / overflow:hidden）上边界：浮层不能越过它，
            // 否则会被裁掉；被裁掉的部分既看不见也点不到。
            let clipTop = 0
            let parent = node.parentElement
            while (parent && parent !== document.body) {
              let style = null
              try {
                style = typeof view.getComputedStyle === 'function' ? view.getComputedStyle(parent) : null
              } catch { style = null }
              const overflowY = style ? String(style.overflowY || '') : ''
              if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'hidden') {
                let box = null
                try { box = parent.getBoundingClientRect() } catch { box = null }
                if (box && box.top > clipTop) clipTop = box.top
              }
              parent = parent.parentElement
            }
            return {
              top: Number(rect.top) || 0,
              bottom: Number(rect.bottom) || 0,
              clipTop,
              viewHeight,
            }
          }
          function update() {
            const next = measure()
            setAnchor((prev) => {
              if (prev === null && next === null) return prev
              if (prev && next
                && Math.abs(prev.top - next.top) < 1
                && Math.abs(prev.bottom - next.bottom) < 1
                && Math.abs(prev.clipTop - next.clipTop) < 1
                && Math.abs(prev.viewHeight - next.viewHeight) < 1) return prev
              return next
            })
          }
          update()
          let frame = 0
          const schedule = () => {
            if (frame) return
            const view = typeof window !== 'undefined' ? window : {}
            if (typeof view.requestAnimationFrame === 'function') {
              frame = view.requestAnimationFrame(() => { frame = 0; update() })
            } else {
              frame = setTimeout(() => { frame = 0; update() }, 32)
            }
          }
          const view = typeof window !== 'undefined' ? window : {}
          if (typeof view.addEventListener === 'function') view.addEventListener('resize', schedule)
          document.addEventListener('scroll', schedule, true)
          return () => {
            if (frame) {
              if (typeof view.cancelAnimationFrame === 'function') view.cancelAnimationFrame(frame)
              else clearTimeout(frame)
            }
            if (typeof view.removeEventListener === 'function') view.removeEventListener('resize', schedule)
            document.removeEventListener('scroll', schedule, true)
          }
        }, [menuOpen, pickerOpen])

        const collapsed = s.prefs.dockCollapsed
        const keepOpen = !!s.prefs.dockKeepOpen
        const data = s.data

        function toggleCollapsed() {
          // 展开是新一轮交互：上一次「关菜单」的标记不该带到现在
          if (collapsed) menuDismissedAtRef.current = 0
          savePrefs({ dockCollapsed: !collapsed })
          setMenuOpen(false)
          setPickerOpen(false)
        }

        // 一个手势（mousedown → click）是否起于状态条内部。菜单项、选择器行点击会把自身
        // 从 DOM 里换掉，等 click 冒到 document 时 target 已 detached；只看 contains(target)
        // 会把这种点击误判成「点外部」并把状态条收起，刚展开的表单跟着一起消失。
        function insideDock(event) {
          const root = rootRef.current
          const target = event && event.target
          if (root && target && typeof root.contains === 'function' && root.contains(target)) return true
          const path = event && typeof event.composedPath === 'function' ? event.composedPath() : null
          return !!(path && root && path.indexOf(root) >= 0)
        }

        // 展开后点状态条外收起。点进可编辑区不收起：收起会让输入区上移，正在定位光标的点击会被带偏。
        // 开了「展开后常驻」就不自动收起，只有点「收起」或按 Esc 才收。
        // 状态条没渲染（取数中 / 无工作区）时不挂监听，否则点一下页面就把收起偏好写掉。
        const hidden = s.phase === 'idle' || s.phase === 'loading'
          || (data && data.ok === false && data.code === 'E_NO_ROOT')
        React.useEffect(() => {
          if (hidden || collapsed || keepOpen) return undefined
          const onClick = (event) => {
            // 本次手势起于状态条内部（含被点击后已卸载的菜单项）就不收起
            const fromInside = gestureInsideRef.current
            gestureInsideRef.current = false
            // 刚被点关闭的菜单或选择器：这一次手势只关内层，不收起状态条；标记只用一次
            const dismissedAt = menuDismissedAtRef.current
            if (dismissedAt && Date.now() - dismissedAt < 600) {
              menuDismissedAtRef.current = 0
              return
            }
            const target = event && event.target
            if (!target) return
            if (typeof Node !== 'undefined' && !(target instanceof Node)) return
            if (fromInside || insideDock(event)) return
            if (isEditableTarget(target)) return
            toggleCollapsed()
          }
          // 手势一开始就记下起点是否在状态条内，并清掉上一次的「关菜单」标记：
          // 右键与拖拽没有 click，标记不能留到下一次点击。
          const onDown = (event) => {
            menuDismissedAtRef.current = 0
            gestureInsideRef.current = insideDock(event)
          }
          // 收尾点击本身不能触发收起：展开那次 click 冒泡到 document 时，监听器可能刚落上
          const timer = setTimeout(() => document.addEventListener('click', onClick), 0)
          document.addEventListener('mousedown', onDown, true)
          return () => {
            clearTimeout(timer)
            gestureInsideRef.current = false
            document.removeEventListener('click', onClick)
            document.removeEventListener('mousedown', onDown, true)
          }
        }, [hidden, collapsed, keepOpen])

        React.useEffect(() => {
          if (!collapsed || !restoreFocusRef.current) return
          restoreFocusRef.current = false
          const node = handleRef.current
          if (node && typeof node.focus === 'function') node.focus()
        }, [collapsed])

        // 焦点在状态条内时 Esc 收起；菜单或选择器开着就先关内层。
        function onRootKeyDown(event) {
          if (!event || event.key !== 'Escape') return
          const stop = typeof event.preventDefault === 'function' ? () => event.preventDefault() : () => {}
          if (menuOpen) {
            stop()
            setMenuOpen(false)
            setMenuForm(null)
            return
          }
          if (pickerOpen) {
            stop()
            setPickerOpen(false)
            return
          }
          if (collapsed) return
          stop()
          restoreFocusRef.current = true
          toggleCollapsed()
        }

        function fillDraft(text) {
          const inputActions = props && props.inputActions
          if (inputActions && typeof inputActions.setDraft === 'function') {
            try {
              inputActions.setDraft(text)
              store.sedimentForceNext = true
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
              ref: handleRef,
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

        // 展开态的两个控制：「展开后常驻」开关与带文字的收起按钮（窄容器只留箭头）。
        function renderKeepOpen() {
          return h('button', {
            type: 'button',
            className: 'scp-icon scp-pin',
            'data-on': keepOpen ? 'true' : 'false',
            'aria-pressed': keepOpen ? 'true' : 'false',
            'aria-label': tr('action.keepOpen'),
            title: keepOpen ? tr('action.keepOpenOff') : tr('action.keepOpen'),
            onClick: () => {
              savePrefs({ dockKeepOpen: !keepOpen })
              flash(keepOpen ? tr('hint.keepOff') : tr('hint.keepOn'))
            },
          }, IconPin({ on: keepOpen }))
        }

        function renderCollapse() {
          return h('button', {
            type: 'button',
            className: 'scp-collapse',
            'aria-label': tr('action.collapse'),
            title: tr('action.collapse'),
            onClick: toggleCollapsed,
          },
            h('span', { className: 'scp-collapse-text' }, tr('action.collapseShort')),
            IconChevron({ open: true }))
        }

        const failed = s.phase === 'error' || (data && data.ok === false)
        if (failed) {
          const message = s.phase === 'error' ? s.message : (data && data.message ? data.message : tr('title.error'))
          if (collapsed) {
            return h('section', Object.assign({}, rootProps, { className: 'scp-root', 'data-mode': 'error', 'data-tone': 'error' }),
              renderHandle(tr('title.error'), null, false))
          }
          return h('section', Object.assign({}, rootProps, { ref: rootRef, className: 'scp-root', 'data-mode': 'error', 'data-tone': 'error', onKeyDown: onRootKeyDown }),
            h('div', { className: 'scp-surface' },
              h('div', { className: 'scp-head' },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-badge' }, tr('title.error')),
                h('span', { className: 'scp-wait', title: message }, message),
                h('span', { className: 'scp-spacer' }),
                h('button', { type: 'button', className: 'scp-btn', onClick: () => refresh(true) }, tr('action.retry')),
                renderKeepOpen(),
                renderCollapse())))
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
          return h('section', Object.assign({}, rootProps, { ref: rootRef, className: 'scp-root', 'data-mode': 'empty', 'data-tone': 'idle', onKeyDown: onRootKeyDown }),
            h('div', { className: 'scp-surface' },
              h('div', { className: 'scp-head' },
                h('span', { className: 'scp-ring', 'aria-hidden': 'true' }),
                h('span', { className: 'scp-case', style: { cursor: 'default', fontWeight: 500 } }, tr('empty.collapsed')),
                h('span', { className: 'scp-spacer' }),
                h('button', {
                  type: 'button',
                  className: 'scp-btn scp-btn--quiet',
                  onClick: () => fillDraft('/diagnose '),
                }, tr('action.start')),
                renderKeepOpen(),
                renderCollapse()),
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
        if (s.stale) chips.push({ key: 'stale', tone: 'warn', text: tr('chip.stale') })
        const metaBits = []
        if (extra.platform) metaBits.push(extra.platform)
        if (extra.framework) metaBits.push(extra.framework)
        if (extra.category) metaBits.push(CATEGORY_LABEL[extra.category] || extra.category)

        const sedimentDrafts = (s.sediment.data && s.sediment.data.drafts) || []
        const sedDraft = sedimentDrafts.find((item) => item && item.source && item.source.sessionId === primary.sessionId) || null
        const traceSed = primary.sedimented && primary.sedimented.state ? primary.sedimented.state : 'none'
        const sedimentRow = (!collapsed && (sedDraft || traceSed === 'submitted'))
          ? h('div', { className: 'scp-dock-sed', role: 'group', 'aria-label': tr('palette.sedimentTitle') },
            h('span', {
              className: 'scp-dock-sed-dot',
              'data-tone': sedDraft ? (sedDraft.stageTone || 'gray') : 'warn',
              'aria-hidden': 'true',
            }),
            h('span', { className: 'scp-dock-sed-label' }, tr('palette.view.sediment')),
            h('span', { className: 'scp-dock-sed-stage' }, sedDraft ? sedDraft.stage : tr('sediment.dock.missingDraft')),
            sedDraft && sedDraft.ageDays !== null && sedDraft.ageDays !== undefined
              ? h('span', { className: 'scp-dock-sed-days' }, tr('sediment.age', { n: sedDraft.ageDays }))
              : null,
            sedDraft && sedDraft.next && sedDraft.next.label
              ? h('span', { className: 'scp-dock-sed-next' }, tr('sediment.batch.next') + '：' + sedDraft.next.label)
              : null,
            h('span', { className: 'scp-spacer' }),
            h('button', {
              type: 'button',
              className: 'scp-dock-sed-open',
              onClick: () => openSediment(sedDraft ? sedDraft.key : ''),
            }, tr('sediment.open') + ' ›'))
          : null

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
          setPaletteOpen(true, primary.sessionId, 'diagnosis')
        }

        const pickerRows = allRows
          .filter((row) => {
            if (!query.trim()) return true
            const needle = query.trim().toLowerCase()
            return caseTitle(row).toLowerCase().includes(needle) || row.sessionId.toLowerCase().includes(needle)
          })
          .slice(0, 12)

        const menuStyle = menuOpen ? popoverPlacement(anchor, 200, 540) : null
        const pickerStyle = pickerOpen ? popoverPlacement(anchor, 160, 380) : null
        const popoverDown = !!((menuStyle && menuStyle.top) || (pickerStyle && pickerStyle.top))

        const picker = pickerOpen ? h('div', {
          className: 'scp-picker',
          role: 'dialog',
          'aria-label': tr('picker.title'),
          style: pickerStyle || undefined,
        },
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

        const menu = menuOpen ? h('div', {
          className: 'scp-menu',
          role: 'menu',
          'aria-label': tr('menu.title'),
          style: menuStyle || undefined,
        },
          h(WritePanel, {
            row: primary,
            data,
            autoForm: menuForm,
            onClose: () => { setMenuOpen(false); setMenuForm(null) },
            onDone: () => { setMenuOpen(false); setMenuForm(null); refresh(true) },
            onFlash: flash,
            onDraft: fillDraft,
          })) : null

        const scopeLabel = pinned ? tr('scope.pinned')
          : (bound ? ((data.bound && data.bound.boundBy === 'resume') ? tr('scope.boundResume') : tr('scope.bound')) : tr('scope.recent'))

        if (collapsed) {
          return h('section', Object.assign({}, rootProps, {
            ref: rootRef,
            className: 'scp-root',
            'data-mode': pinned ? 'pinned' : (bound ? 'bound' : 'recent'),
            'data-tone': tone,
            'data-live': derived.open ? 'true' : 'false',
            'data-pending': isPending(primary) ? 'true' : 'false',
            'data-flash': flashStep ? 'true' : 'false',
          }), renderHandle(
            caseTitle(primary),
            (flashStep || stepsShort(extra)) + (s.stale ? ' · ' + tr('chip.stale') : ''),
            isPending(primary)))
        }

        return h('section', Object.assign({}, rootProps, {
          ref: rootRef,
          className: 'scp-root',
          'data-mode': pinned ? 'pinned' : (bound ? 'bound' : 'recent'),
          'data-tone': tone,
          'data-live': derived.open ? 'true' : 'false',
          'data-pending': isPending(primary) ? 'true' : 'false',
          'data-flash': flashStep ? 'true' : 'false',
          'data-popover-down': popoverDown ? 'true' : 'false',
          onKeyDown: onRootKeyDown,
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
              collapsed ? h('span', { className: 'scp-step' }, flashStep ? '第 ' + flashStep + ' 步' : stepsShort(extra)) : null,
              h('span', { className: 'scp-spacer' }),
              h('button', { type: 'button', className: 'scp-btn scp-btn--quiet', onClick: runPrimary }, action.label),
              collapsed ? null : h('button', {
                type: 'button', className: 'scp-icon', title: tr('action.more'), 'aria-label': tr('action.more'),
                'aria-haspopup': 'menu',
                'aria-expanded': menuOpen ? 'true' : 'false',
                onClick: () => { setMenuForm(null); setMenuOpen((value) => !value); setPickerOpen(false) },
              }, IconMore()),
              renderKeepOpen(),
              renderCollapse()),
            collapsed ? null : h('div', { className: 'scp-foot' },
              StepRail({ extra }),
              metaBits.length ? h('span', { className: 'scp-meta', title: metaBits.join(' · ') }, metaBits.join(' · ')) : null,
              h('span', { className: 'scp-wait', title: waiting }, waiting
                ? h('span', {}, tr('waiting') + '：', h('b', {}, waiting))
                : h('span', {}, tr('label.updated') + ' ' + (formatTime(primary.updatedAt) || tr('none')))),
              chips.length ? h('span', { className: 'scp-chips' }, chips.map((chip) => h('span', {
                key: chip.key, className: 'scp-chip', 'data-tone': chip.tone,
              }, chip.text))) : null),
            sedimentRow),
          hint ? h('div', { className: 'scp-hint', role: 'status' }, hint) : null)
      }
    }

    // ── 面 2：输入区工具条入口 ─────────────────────────────────────────────
    function ToolbarButton(props) {
      const s = useStore()
      useSessionSync(props)
      if (s.data && s.data.ok === false && s.data.code === 'E_NO_ROOT') return null
      const data = s.data && s.data.ok !== false ? s.data : null
      const bound = data ? data.bound : null
      const pending = data && data.counts ? Number(data.counts.pendingFeedback) || 0 : 0
      const tone = bound ? toneOf(bound) : 'idle'
      const title = [tr('tool.title'), pending > 0 ? tr('tool.pending', { n: pending }) : '', shortcutOpenLabel()]
        .filter(Boolean).join(' · ')
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
      const canWrite = !!((s.data && s.data.capabilities && s.data.capabilities.canWrite))
      const filter = s.prefs.paletteFilter
      const [selected, setSelected] = React.useState(0)
      // 选中项按 sessionId 记住，10 秒刷新重排后仍停在同一条单上；只按数组下标存，
      // 别处更新一单就会静默换到另一单，动作会落到读者没在看的那条上。
      const selectedIdRef = React.useRef('')
      function selectIndex(next) {
        const row = filtered[next]
        selectedIdRef.current = row ? row.sessionId : ''
        setSelected(next)
      }
      const [searchText, setSearchText] = React.useState('')
      // 详情抬头「展开全文」按单号记：换单回到收起，不继承上一单的展开态。
      const [ledeOpenId, setLedeOpenId] = React.useState('')
      const [sedLedeOpenKey, setSedLedeOpenKey] = React.useState('')
      const [menuOpen, setMenuOpen] = React.useState(false)
      const [menuForm, setMenuForm] = React.useState(null)
      const [cmdOpen, setCmdOpen] = React.useState(false)
      const [cmdQuery, setCmdQuery] = React.useState('')
      const [cmdIndex, setCmdIndex] = React.useState(0)
      const [timelineState, setTimelineState] = React.useState({ open: false, loading: false, items: [], error: '' })
      const [toast, setToast] = React.useState('')
      const [reportState, setReportState] = React.useState({ open: false, loading: false, text: '', error: '' })
      const reportToken = React.useRef(0)
      const selectedRowRef = React.useRef('')
      const [undoBusy, setUndoBusy] = React.useState(false)
      const [sedSel, setSedSel] = React.useState(0)
      const [sedFilter, setSedFilter] = React.useState('all')
      const [promptKind, setPromptKind] = React.useState('')
      const [promptDetailsOpen, setPromptDetailsOpen] = React.useState(false)
      // 写台账失败时的兜底指令：与普通指令预览同一个弹层，正文由失败上下文生成。
      const [promptFallback, setPromptFallback] = React.useState(null)
      // 批量沉淀指令在弹层打开时冻结：后台每 10 秒刷新会重算 filtered，不能让名单在读者看的时候变。
      const [batchSed, setBatchSed] = React.useState(null)
      const [targetOpen, setTargetOpen] = React.useState(false)
      const [manualOpen, setManualOpen] = React.useState(false)
      const [targetResume, setTargetResume] = React.useState('')
      const [targetRemote, setTargetRemote] = React.useState('')
      const [targetBase, setTargetBase] = React.useState('')
      const [targetBusy, setTargetBusy] = React.useState(false)
      const [checkBusy, setCheckBusy] = React.useState('')
      const promptRef = React.useRef(null)
      const targetRef = React.useRef(null)
      const toastTimer = React.useRef(null)
      const panelRef = React.useRef(null)
      const searchRef = React.useRef(null)
      const listRef = React.useRef(null)
      const cmdInputRef = React.useRef(null)
      const timelineToken = React.useRef(0)
      const commandsRef = React.useRef([])
      const filtered = filterRows(rows, filter).filter((item) => matchesQuery(item, searchText))
      // 诊断视图批量沉淀的范围 = 当前筛选（含搜索词）；单条与批量共用这一份名单。
      const diagSedRows = filter === 'sediment' ? filtered.filter((item) => item && item.sessionId) : []

      const view = s.paletteView === 'sediment' ? 'sediment' : 'diagnosis'
      const sedDoc = s.sediment && s.sediment.data && s.sediment.data.ok !== false ? s.sediment.data : null
      const sedPhase = s.sediment ? s.sediment.phase : 'idle'
      const sedDrafts = sedDoc && Array.isArray(sedDoc.drafts) ? sedDoc.drafts : []
      // 查合入的逐条进度（见 beginCheckRun）：行内状态与批次条 n/m 都读这一份。
      const checkRun = s.checkRun
      const sedCounts = sedDoc && sedDoc.counts ? sedDoc.counts : {}
      const sedTargetDoc = sedDoc && sedDoc.target ? sedDoc.target : null
      const sedTarget = sedTargetDoc && sedTargetDoc.target ? sedTargetDoc.target : sedTargetDoc
      const sedRemotes = sedTargetDoc && Array.isArray(sedTargetDoc.remotes)
        ? sedTargetDoc.remotes
        : (sedTarget && Array.isArray(sedTarget.remotes) ? sedTarget.remotes : [])
      const sedTargetLabel = sedTarget && sedTarget.remote
        ? [sedTarget.remote, sedTarget.base,
          sedTarget.platformName || (sedTargetDoc && sedTargetDoc.platformName) || sedTarget.platform].filter(Boolean).join(' · ')
        : ''
      const sedTargetHint = sedTargetLabel
        ? tr('sediment.pushTarget', { label: sedTargetLabel })
        : tr('sediment.noTarget')
      const sedQuery = String(searchText || '').trim().toLowerCase()
      const sedFiltered = sedDrafts.filter((draft) => {
        if (!sedQuery) return true
        const hay = [draft.title, draft.key, draft.caseId, draft.decision, draft.novelty, draft.stage]
          .filter(Boolean).join(' ').toLowerCase()
        return hay.indexOf(sedQuery) >= 0
      }).filter((draft) => {
        if (sedFilter === 'decision') return ['unassessed', 'need_decision'].indexOf(draft.state) >= 0
        if (sedFilter === 'pr') return draft.state === 'decided'
        if (sedFilter === 'check') return draft.state === 'pr_open' || draft.state === 'pr_merged'
        if (sedFilter === 'rerun') return draft.state === 'need_rerun'
        return true
      })
      const sedRank = { groom: 0, pr: 1, check: 2, other: 3 }
      const sedSorted = sedFiltered.slice().sort((a, b) => {
        const ga = Object.prototype.hasOwnProperty.call(sedRank, sedGroupOf(a)) ? sedRank[sedGroupOf(a)] : 9
        const gb = Object.prototype.hasOwnProperty.call(sedRank, sedGroupOf(b)) ? sedRank[sedGroupOf(b)] : 9
        if (ga !== gb) return ga - gb
        const aa = a.ageDays === null || a.ageDays === undefined ? -1 : Number(a.ageDays)
        const ab = b.ageDays === null || b.ageDays === undefined ? -1 : Number(b.ageDays)
        return ab - aa
      })
      const sedPick = sedSorted[Math.max(0, Math.min(sedSel, sedSorted.length - 1))] || null

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
        // 诊断视图也要读一次：右列的「沉淀进度」需要当前单对应的草稿。
        // refreshSediment 自己按 60 秒去重；这里只避免在 loading/refreshing 时重入。
        // 失败后不自动重试：否则 error → loading → error 会无限起子进程，等读者点「刷新」。
        if (sedPhase !== 'loading' && sedPhase !== 'refreshing' && sedPhase !== 'error') refreshSediment(false)
      }, [s.paletteOpen, sedPhase])

      React.useEffect(() => {
        setMenuOpen(false)
        setMenuForm(null)
        setCmdOpen(false)
        setPromptKind('')
        setPromptFallback(null)
        setManualOpen(false)
      }, [s.sessionId])

      React.useEffect(() => {
        setSedSel(0)
        setPromptKind('')
        setPromptFallback(null)
        setPromptDetailsOpen(false)
        setTargetOpen(false)
        setManualOpen(false)
      }, [view, sedFilter])

      React.useEffect(() => {
        setSearchText('')
        setSedSel(0)
      }, [view])

      React.useEffect(() => {
        if (sedSel > sedSorted.length - 1) setSedSel(sedSorted.length > 0 ? sedSorted.length - 1 : 0)
      }, [sedSorted.length, sedSel])

      React.useEffect(() => {
        if (!s.paletteOpen || view !== 'sediment') return
        const key = s.sedimentSelectKey
        if (!key) return
        const index = sedSorted.findIndex((draft) => draft.key === key)
        if (index < 0 && sedFilter !== 'all') {
          setSedFilter('all')
          return
        }
        if (index >= 0 && index !== sedSel) setSedSel(index)
      }, [s.paletteOpen, s.sedimentSelectKey, view, sedSorted.length, sedFilter])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        setMenuOpen(false)
        const position = filtered.findIndex((row) => row.sessionId === s.paletteSelect)
        selectIndex(position >= 0 ? position : 0)
      }, [s.paletteOpen, s.paletteSelect, filter])

      // 重排后按 sessionId 找回同一条；行不在了才退回边界。
      React.useEffect(() => {
        const id = selectedIdRef.current
        if (id) {
          const index = filtered.findIndex((row) => row.sessionId === id)
          if (index >= 0) {
            if (index !== selected) setSelected(index)
            return
          }
        }
        if (selected > filtered.length - 1) setSelected(filtered.length > 0 ? filtered.length - 1 : 0)
      }, [filtered, selected])

      // 键盘选中变化时把行滚进可视区：列表比一屏长，选中项在屏外时回车执行的是看不见的行。
      React.useEffect(() => {
        if (!s.paletteOpen) return
        const host = listRef.current
        if (!host || typeof host.querySelector !== 'function') return
        const node = host.querySelector('.scp-pal-row[data-on="true"]')
        if (node && typeof node.scrollIntoView === 'function') node.scrollIntoView({ block: 'nearest' })
      }, [selected, s.paletteOpen])

      React.useEffect(() => {
        reportToken.current += 1
        timelineToken.current += 1
        setReportState({ open: false, loading: false, text: '', error: '' })
        setTimelineState({ open: false, loading: false, items: [], error: '' })
        setUndoBusy(false)
      }, [selected, filter, searchText, s.paletteOpen])

      React.useEffect(() => {
        if (s.paletteOpen) return
        commandRequested = false
        setCmdOpen(false)
        setCmdQuery('')
        setCmdIndex(0)
        setSearchText('')
        setMenuOpen(false)
        setPromptKind('')
        setPromptFallback(null)
        setBatchSed(null)
        setPromptDetailsOpen(false)
        setTargetOpen(false)
        setTargetResume('')
        setManualOpen(false)
        setCheckBusy('')
      }, [s.paletteOpen])

      React.useEffect(() => {
        if (!promptKind) return
        const node = promptRef.current
        if (node && typeof node.focus === 'function') node.focus()
      }, [promptKind])

      React.useEffect(() => {
        if (!targetOpen) return
        const node = targetRef.current
        if (node && typeof node.focus === 'function') node.focus()
      }, [targetOpen])

      React.useEffect(() => {
        if (!s.paletteOpen) return
        if (commandRequested) {
          commandRequested = false
          setCmdOpen(true)
          setCmdQuery('')
          setCmdIndex(0)
        }
      }, [s.paletteOpen])

      React.useEffect(() => {
        if (cmdOpen) {
          const node = cmdInputRef.current
          if (node && typeof node.focus === 'function') node.focus()
        }
      }, [cmdOpen])

      // 关闭浮层后把焦点还给打开它的按钮，不要落回 body。
      React.useEffect(() => {
        if (!s.paletteOpen) return undefined
        const previous = typeof document !== 'undefined' ? document.activeElement : null
        return () => {
          if (previous && previous.isConnected && typeof previous.focus === 'function') previous.focus()
        }
      }, [s.paletteOpen])

      React.useEffect(() => {
        if (!s.paletteOpen) return undefined
        const node = panelRef.current
        if (node && typeof node.focus === 'function') node.focus()
        const onKey = (event) => {
          const target = event.target
          const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')
          // Tab 在浮层内环绕：aria-modal=true 时焦点不该跑到遮罩下面。
          if (event.key === 'Tab' && !cmdOpen && !promptKind) {
            const root = panelRef.current
            if (root && typeof root.querySelectorAll === 'function') {
              const focusables = Array.from(root.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'))
                .filter((item) => item && item.offsetParent !== null)
              if (focusables.length) {
                event.preventDefault()
                const current = focusables.indexOf(document.activeElement)
                const next = event.shiftKey
                  ? (current <= 0 ? focusables.length - 1 : current - 1)
                  : (current === focusables.length - 1 ? 0 : current + 1)
                const node = focusables[next]
                if (node && typeof node.focus === 'function') node.focus()
                return
              }
            }
          }
          if ((event.metaKey || event.ctrlKey) && String(event.key || '').toLowerCase() === 'k') {
            event.preventDefault()
            if (view === 'sediment') return
            setCmdOpen(true)
            setCmdQuery('')
            setCmdIndex(0)
            return
          }
          if (cmdOpen) {
            const items = commandsRef.current || []
            if (event.key === 'Escape') {
              event.preventDefault()
              setCmdOpen(false)
              return
            }
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault()
              if (!items.length) return
              setCmdIndex((current) => {
                const next = event.key === 'ArrowDown' ? current + 1 : current - 1
                return Math.max(0, Math.min(next, items.length - 1))
              })
              return
            }
            if (event.key === 'Enter') {
              event.preventDefault()
              const item = items[cmdIndex]
              if (item && typeof item.run === 'function') {
                setCmdOpen(false)
                item.run()
              }
            }
            return
          }
          if (view === 'sediment') return
          // 批量沉淀弹层开着时，键盘只服务弹层：Esc 关弹层，Enter 不能穿透到背后的列表主操作。
          if (promptKind) {
            if (event.key === 'Escape') {
              event.preventDefault()
              closePrompt()
            }
            return
          }
          if (event.key === '/' && !typing && !menuOpen) {
            event.preventDefault()
            if (searchRef.current && typeof searchRef.current.focus === 'function') searchRef.current.focus()
            return
          }
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
            const next = event.key === 'ArrowDown' ? selected + 1 : selected - 1
            selectIndex(Math.max(0, Math.min(next, filtered.length - 1)))
            return
          }
          if (event.key === 'Enter') {
            const row = filtered[selected]
            if (!row) return
            // 焦点只在普通按钮/输入框上时不抢回车；行按钮与列表容器上按回车都执行主操作。
            const target = event.target
            const onRow = target && typeof target.className === 'string'
              && target.className.split(/\s+/).indexOf('scp-pal-row') >= 0
            if (target && target.tagName === 'BUTTON' && !onRow) return
            event.preventDefault()
            runPrimary(row)
          }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [s.paletteOpen, filtered, selected, menuOpen, cmdOpen, cmdQuery, cmdIndex, promptKind])

      React.useEffect(() => {
        if (!s.paletteOpen || view !== 'sediment') return undefined
        const onKey = (event) => {
          const target = event.target
          const typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '')
          if (cmdOpen) return
          if (promptKind) {
            if (event.key === 'Escape') {
              event.preventDefault()
              closePrompt()
            }
            return
          }
          if (targetOpen) {
            if (event.key === 'Escape') {
              event.preventDefault()
              setTargetOpen(false)
            }
            return
          }
          if (manualOpen) {
            if (event.key === 'Escape') {
              event.preventDefault()
              setManualOpen(false)
            }
            return
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            setPaletteOpen(false)
            return
          }
          if (event.key === '/' && !typing) {
            event.preventDefault()
            if (searchRef.current && typeof searchRef.current.focus === 'function') searchRef.current.focus()
            return
          }
          if (typing) return
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (!sedSorted.length) return
            event.preventDefault()
            setSedSel((current) => {
              const next = event.key === 'ArrowDown' ? current + 1 : current - 1
              return Math.max(0, Math.min(next, sedSorted.length - 1))
            })
            return
          }
          if (event.key === 'Enter') {
            if (event.target && event.target.tagName === 'BUTTON') return
            const pick = sedSorted[sedSel]
            if (!pick) return
            event.preventDefault()
            runSedNext(pick)
          }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
      }, [s.paletteOpen, view, sedSorted.length, sedSel, promptKind, targetOpen, manualOpen, cmdOpen])

      // 详情抬头的三个钩子必须放在任何提前 return 之前：总览关着时 Palette 提前返回，打开后
      // 又多出这三个钩子，React 会报「hook 数量与上次渲染不一致」，整个 shell.overlay 槽位崩掉，
      // 表现就是点「诊断总览」没有反应。依赖值都从已声明的 state 现算，不依赖后面才赋值的局部变量。
      const ledeRow = filtered[selected] || null
      const ledeText = ledeRow ? (String(ledeRow.summary || '').trim() || caseTitle(ledeRow)) : ''
      const ledeOpen = Boolean(ledeRow) && ledeOpenId === ledeRow.sessionId
      const ledeRef = React.useRef(null)
      const [ledeOverflow, setLedeOverflow] = React.useState(false)
      React.useEffect(() => {
        const el = ledeRef.current
        if (!el || typeof el.scrollHeight !== 'number' || !(el.clientHeight > 0)) {
          setLedeOverflow(Boolean(ledeText) && ledeText.length > LEDE_TOGGLE_MIN)
          return
        }
        setLedeOverflow(ledeOpen || el.scrollHeight > el.clientHeight + 1)
      }, [ledeRow ? ledeRow.sessionId : '', ledeText, ledeOpen])

      // 沉淀详情抬头同样按「识别行 + 正文背景」渲染：与诊断详情共用一套样式与展开逻辑，
      // 只把正文换成草稿标题（标题就是来源 trace 的 summary 首句）。
      const sedPickKey = sedPick ? String(sedPick.key || '') : ''
      const sedPickTitle = sedPick ? String(sedPick.title || sedPick.key || '') : ''
      const sedLedeOpen = Boolean(sedPickKey) && sedLedeOpenKey === sedPickKey
      const sedLedeRef = React.useRef(null)
      const [sedLedeOverflow, setSedLedeOverflow] = React.useState(false)
      React.useEffect(() => {
        const el = sedLedeRef.current
        if (!el || typeof el.scrollHeight !== 'number' || !(el.clientHeight > 0)) {
          setSedLedeOverflow(Boolean(sedPickTitle) && sedPickTitle.length > LEDE_TOGGLE_MIN)
          return
        }
        setSedLedeOverflow(sedLedeOpen || el.scrollHeight > el.clientHeight + 1)
      }, [view, sedPickKey, sedPickTitle, sedLedeOpen])

      if (!s.paletteOpen) return null
      if (s.data && s.data.ok === false && s.data.code === 'E_NO_ROOT') return null

      const loadFailed = !data && (s.phase === 'error' || !!(s.data && s.data.ok === false))
      const row = filtered[selected] || null
      selectedRowRef.current = row ? row.sessionId : ''
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
            store.sedimentForceNext = true
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

      function toggleReport(target) {
        if (!target) return
        if (reportState.open) {
          reportToken.current += 1
          setReportState({ open: false, loading: false, text: '', error: '' })
          return
        }
        const wanted = target.sessionId
        const token = reportToken.current + 1
        reportToken.current = token
        const apply = (next) => {
          if (reportToken.current !== token || selectedRowRef.current !== wanted) return
          setReportState(next)
        }
        setReportState({ open: true, loading: true, text: '', error: '' })
        rpcCall('copilot-report', {
          cwd: store.cwd,
          tracesDir: data && data.tracesDir,
          traceSessionId: wanted,
          traceFile: target.file || '',
          reportFile: target.reportFile || (target.extra && target.extra.reportFile) || '',
        }).then((res) => {
          if (res && res.ok) {
            apply({ open: true, loading: false, text: String(res.text || ''), error: '' })
            if (reportToken.current === token) flash(tr('hint.reportOpen'))
          } else {
            apply({ open: true, loading: false, text: '', error: (res && res.message) || tr('report.none') })
          }
        }, (error) => {
          apply({ open: true, loading: false, text: '', error: String((error && error.message) || error) })
        })
      }

      function undoClose(target) {
        if (!target || undoBusy) return
        setUndoBusy(true)
        rpcCall('copilot-transition', transitionPayload(target, data, { kind: 'reopen' }))
          .then((res) => {
            setUndoBusy(false)
            if (res && res.ok) {
              flash(tr('hint.reopened'))
              refresh(true)
            } else {
              flash(tr('write.failed', { message: (res && res.message) || '' }))
            }
          }, (error) => {
            setUndoBusy(false)
            flash(tr('write.failed', { message: String((error && error.message) || error) }))
          })
      }

      function checklistAction(target, item) {
        if (!item || !item.kind) return
        if (item.kind === 'report') fillDraft(reportDraft(target))
        else if (item.kind === 'feedback') { setMenuForm('feedback'); setMenuOpen(true) }
        else if (item.kind === 'sediment') fillDraft(sedimentDraft(target))
        else if (item.kind === 'handoff') fillDraft(handoffDraft(target))
      }

      function candidateAction(target, candidate) {
        const summary = String((candidate && candidate.summary) || '')
        const evidence = String((candidate && candidate.evidence) || '')
        if (candidate && candidate.kind === 'reference') fillDraft(referenceDraft(target, summary, evidence))
        else if (candidate && candidate.kind === 'triage') fillDraft(triageDraft(target, summary))
        else fillDraft(sedimentDraft(target))
      }

      function toggleTimeline(target) {
        if (!target) return
        if (timelineState.open) {
          timelineToken.current += 1
          setTimelineState({ open: false, loading: false, items: [], error: '' })
          return
        }
        const token = timelineToken.current + 1
        timelineToken.current = token
        setTimelineState({ open: true, loading: true, items: [], error: '' })
        rpcCall('copilot-timeline', {
          cwd: store.cwd,
          tracesDir: data && data.tracesDir,
          sessionId: store.sessionId,
          traceFile: target.file,
        }).then((res) => {
          if (timelineToken.current !== token || selectedRowRef.current !== target.sessionId) return
          if (res && res.ok) {
            setTimelineState({ open: true, loading: false, items: Array.isArray(res.timeline) ? res.timeline : [], error: '' })
          } else {
            setTimelineState({ open: true, loading: false, items: [], error: (res && res.message) || tr('timeline.none') })
          }
        }, (error) => {
          if (timelineToken.current !== token || selectedRowRef.current !== target.sessionId) return
          setTimelineState({ open: true, loading: false, items: [], error: String((error && error.message) || error) })
        })
      }

      function commandItemsFor(target) {
        if (!target) return []
        const items = []
        const primary = primaryFor(target, data && data.bound && target.sessionId === data.bound.sessionId)
        items.push({ label: tr('command.primary') + '：' + primary.label, run: () => runPrimary(target) })
        items.push({ label: tr('action.copySummary'), run: () => copyAndFlash(summaryText(target, data)) })
        items.push({ label: tr('copy.issue'), run: () => copyAndFlash(issueText(target)) })
        items.push({ label: tr('action.viewReport'), run: () => toggleReport(target) })
        if (target.activeCase) items.push({ label: tr('action.upstream'), run: () => fillDraft(upstreamDraft(target, data.upstream)) })
        if (target.activeCase || isPending(target)) {
          items.push({ label: tr('action.feedback'), run: () => { setMenuForm('feedback'); setMenuOpen(true) } })
        }
        if (canStartSediment(target)) {
          items.push({ label: tr('action.sediment'), run: () => fillDraft(sedimentDraft(target)) })
        }
        items.push({ label: tr('action.loadTimeline'), run: () => toggleTimeline(target) })
        items.push({ label: tr('action.refresh'), run: () => { refresh(true); flash(tr('hint.refreshed')) } })
        items.push({ label: tr('palette.close'), run: () => setPaletteOpen(false) })
        return items
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
      }, tr('palette.filter.' + key), h('b', {}, String(filterCounts[key] || 0))))

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

      const list = h('div', { ref: listRef, className: 'scp-pal-list', role: 'region', 'aria-label': tr('palette.title') },
        h('div', { className: 'scp-search' },
          h('input', {
            ref: searchRef, type: 'search', value: searchText,
            placeholder: tr('search.placeholder'), 'aria-label': tr('search.placeholder'),
            onChange: (event) => { setSearchText(event.target.value); selectIndex(0) },
            onKeyDown: (event) => { if (event.key === 'Escape') { setSearchText(''); event.stopPropagation() } },
          }),
          h('span', { className: 'scp-kbd' }, '/')),
        h('div', { className: 'scp-filters', role: 'group', 'aria-label': tr('palette.filterLabel') }, filterButtons),
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
                'aria-current': index === selected ? 'true' : 'false',
                'data-on': index === selected ? 'true' : 'false',
                style: { '--scp-tone': TONE_VAR[toneOf(item)] || TONE_VAR.idle },
                onClick: () => { selectIndex(index); setMenuOpen(false) },
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
      const materials = row ? ((extra.missingMaterials) || []) : []
      const showMaterials = Boolean(row) && (materials.length > 0
        || Boolean(row && row.derived && row.derived.waitingOn === 'user_material' && waiting))
      const commandItems = commandItemsFor(row)
      const cmdNeedle = cmdQuery.trim().toLowerCase()
      const commandList = cmdNeedle
        ? commandItems.filter((item) => item.label.toLowerCase().includes(cmdNeedle))
        : commandItems
      commandsRef.current = commandList
      const checklist = row && shouldShowChecklist(row) ? checklistFor(row, data) : []
      const upstream = row && row.derived ? (row.derived.upstream || null) : null
      const evidenceList = row ? (extra.evidenceList || []) : []
      const candidateList = row ? (extra.sedimentCandidateList || []) : []
      const history = row ? historyEntries(row, data) : []
      const closeInfo = row ? lastClose(row) : null
      const originSession = row ? (row.harnessSession || '') : ''
      const resumedSessions = row ? (row.resumeSessions || []).filter((sid) => sid && sid !== originSession) : []
      const currentSession = store.sessionId || ''

      const diagSed = row
        ? (sedDrafts.find((draft) => draft && draft.source && draft.source.sessionId === row.sessionId) || null)
        : null
      const diagSedBlock = (() => {
        if (!row) return null
        const traceState = row.sedimented && row.sedimented.state ? String(row.sedimented.state) : 'none'
        if (!diagSed && traceState !== 'submitted' && traceState !== 'knowledge' && traceState !== 'archived') return null
        const children = [h('div', { key: 'label', className: 'scp-section-label' }, tr('sediment.detail.progress'))]
        if (diagSed) {
          const steps = sedSteps(diagSed)
          const mismatch = diagSed.source && diagSed.source.mismatch ? String(diagSed.source.mismatch) : 'none'
          children.push(h('div', { key: 'block', className: 'scp-list-block' },
            h('div', { className: 'scp-stepper' }, steps.map((step) => h('div', { key: step.key, className: 'scp-sed-step', 'data-state': step.state },
              h('span', { className: 'scp-sed-step-dot', 'aria-hidden': 'true' }, '✓'),
              h('span', { className: 'scp-sed-step-label' }, step.label),
              step.note ? h('span', { className: 'scp-sed-step-note', 'data-bad': step.state === 'blocked' ? 'true' : 'false' }, step.note) : null))),
            mismatch !== 'none' ? h('div', {
              className: 'scp-callout',
              style: { background: 'var(--scp-warn-soft)', borderColor: 'color-mix(in srgb, var(--scp-warn) 26%, var(--scp-border))' },
            },
              h('span', { className: 'scp-callout-label' }, tr('sediment.detail.source')),
              h('div', { className: 'scp-callout-text' }, tr('sediment.detail.mismatch.' + mismatch)),
              diagSed.writeback ? h('button', {
                type: 'button', className: 'scp-check-action', style: { alignSelf: 'flex-start' },
                onClick: () => fillDraft(diagSed.writeback),
              }, tr(mismatch === 'draft_left_behind' ? 'sediment.detail.closeDraft' : 'sediment.detail.writeback')) : null) : null,
            h('div', { className: 'scp-upstream-row' },
              h('button', {
                type: 'button', className: 'scp-check-action',
                onClick: () => openSediment(diagSed.key),
              }, tr('sediment.detail.openQueue')))))
        } else if (traceState === 'submitted') {
          children.push(h('div', { key: 'block', className: 'scp-list-block' },
            h('div', { className: 'scp-check-state' }, tr('sediment.dock.missingDraft')),
            h('div', { className: 'scp-upstream-row' },
              h('button', {
                type: 'button', className: 'scp-check-action',
                onClick: () => openSediment(''),
              }, tr('sediment.detail.openQueue')))))
        } else {
          const vocab = (data && data.vocab && data.vocab.sedimented) || []
          const item = vocab.find((entry) => entry.value === traceState)
          const label = item ? item.label : traceState
          const caseId = row.sedimented && row.sedimented.case_id ? String(row.sedimented.case_id) : ''
          children.push(h('div', { key: 'block', className: 'scp-list-block' },
            h('div', { className: 'scp-check-state' }, label + (caseId ? ' · ' + caseId : ''))))
        }
        return h('div', { key: 'sediment-progress' }, children)
      })()

      const side = row
        ? menuOpen
          ? h('div', { className: 'scp-pal-side scp-write-side' }, h(WritePanel, {
            row,
            data,
            autoForm: menuForm,
            onClose: () => { setMenuOpen(false); setMenuForm(null) },
            onDone: () => { setMenuOpen(false); setMenuForm(null); refresh(true) },
            onFlash: flash,
            onDraft: fillDraft,
          }))
          : h('div', { className: 'scp-pal-side', style: { '--scp-tone': TONE_VAR[toneOf(row)] || TONE_VAR.brand } },
            h('div', { className: 'scp-identity' },
              h('span', { className: 'scp-badge' }, statusMeta(data.vocab, row.status).label),
              identityChips(row).slice(0, 3).map((chip) => h('span', {
                key: chip.key, className: 'scp-chip', 'data-tone': chip.tone,
              }, chip.text)),
              store.sessionId && pinnedIdFor(store.sessionId) === row.sessionId
                ? h('span', { key: 'pinned', className: 'scp-chip', 'data-tone': 'brand' }, tr('chip.pinned'))
                : null,
              h('span', { className: 'scp-identity-meta' }, [stepsText(extra), formatTime(row.updatedAt)].filter(Boolean).join(' · '))),
            ledeText ? h('p', {
              className: 'scp-lede',
              ref: ledeRef,
              'data-open': ledeOpen ? 'true' : 'false',
              title: ledeText,
            }, inlineTokens(ledeText)) : null,
            ledeOverflow ? h('button', {
              type: 'button', className: 'scp-more',
              'aria-expanded': ledeOpen ? 'true' : 'false',
              onClick: () => setLedeOpenId(ledeOpen ? '' : row.sessionId),
            }, ledeOpen ? tr('lede.collapse') : tr('lede.expand')) : null,
            waiting ? h('div', { className: 'scp-waitline' },
              h('span', { className: 'scp-waitline-tag' }, tr('label.waiting')),
              h('span', { className: 'scp-waitline-text' }, inlineTokens(waiting))) : null,
            diagSedBlock,
            showMaterials ? h('div', { className: 'scp-section-label' }, tr('section.materials')) : null,
            showMaterials ? h('div', { className: 'scp-list-block' },
              h('div', { className: 'scp-check-state' }, tr('materials.hint')),
              materials.length
                ? materials.map((item, index) => h('div', { key: 'mat-' + index, className: 'scp-material-row' }, item))
                : h('div', { className: 'scp-mono' }, waiting),
              h('div', { className: 'scp-upstream-row' },
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => copyAndFlash(materialText(row)),
                }, tr('action.copyMaterials')),
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => fillDraft(materialResumeDraft(row)),
                }, tr('action.materialResume')))) : null,
            checklist.length ? h('div', { className: 'scp-section-label' }, tr('section.checklist')) : null,
            checklist.length ? h('div', { className: 'scp-check' }, checklist.map((item) => h('div', {
              key: item.key,
              className: 'scp-check-item',
              'data-done': item.done ? 'true' : 'false',
              'data-na': item.na ? 'true' : 'false',
              'data-optional': item.optional ? 'true' : 'false',
            },
              h('span', { className: 'scp-check-dot', 'aria-hidden': 'true' }, item.done ? '✓' : ''),
              h('span', { className: 'scp-check-label' }, item.label),
              h('span', { className: 'scp-check-state' }, item.state),
              h('span', { className: 'scp-spacer' }),
              item.action ? h('button', {
                type: 'button', className: 'scp-check-action',
                onClick: () => checklistAction(row, item),
              }, item.action) : null))) : null,
            row.activeCase ? h('div', {},
              h('div', { className: 'scp-section-label' }, tr('section.upstream')),
              h('div', { className: 'scp-upstream' },
                h('div', { className: 'scp-upstream-row' },
                  h('span', { className: 'scp-check-label' }, tr('upstream.anchors')),
                  upstream && upstream.anchors && upstream.anchors.length
                    ? upstream.anchors.map((anchor) => h('span', { key: anchor, className: 'scp-chip' }, anchor))
                    : h('span', { className: 'scp-mono' }, tr('upstream.none'))),
                upstream && upstream.lastVerified ? h('div', { className: 'scp-upstream-row' },
                  h('span', { className: 'scp-check-state' }, tr('upstream.lastVerified') + '：' + upstream.lastVerified),
                  upstream.verificationSource ? h('span', { className: 'scp-check-state' }, tr('upstream.source') + '：' + upstream.verificationSource) : null) : null,
                h('div', { className: 'scp-upstream-row' },
                  h('span', { className: 'scp-chip' }, data.upstream && data.upstream.ready ? tr('upstream.ready') : tr('upstream.notReady')),
                  h('button', {
                    type: 'button', className: 'scp-check-action',
                    onClick: () => fillDraft(upstreamDraft(row, data.upstream)),
                  }, tr('action.upstream'))))) : null,
            h('div', { className: 'scp-section-label' }, tr('section.sessions')),
            h('div', { className: 'scp-list-block' },
              originSession
                ? h('div', { className: 'scp-upstream-row' },
                  h('span', { className: 'scp-check-label' }, tr('sessions.origin')),
                  h('span', { className: 'scp-mono' }, originSession),
                  originSession === currentSession ? h('span', { className: 'scp-chip' }, tr('sessions.current')) : null,
                  originSession === currentSession ? null : h('button', {
                    type: 'button', className: 'scp-check-action',
                    onClick: () => openSessionWithFlash(originSession, flash),
                  }, tr('action.openOrigin')))
                : h('div', { className: 'scp-mono' }, tr('sessions.missing')),
              resumedSessions.length
                ? h('div', { className: 'scp-upstream-row' },
                  h('span', { className: 'scp-check-label' }, tr('sessions.resumed')),
                  resumedSessions.map((sid) => h('span', {
                    key: sid, className: 'scp-chip', 'data-tone': sid === currentSession ? 'brand' : '',
                  }, sid + (sid === currentSession ? '（' + tr('sessions.current') + '）' : ''))),
                  resumedSessions[resumedSessions.length - 1] === currentSession ? null : h('button', {
                    type: 'button', className: 'scp-check-action',
                    onClick: () => openSessionWithFlash(resumedSessions[resumedSessions.length - 1], flash),
                  }, tr('action.openResumed')))
                : null,
              !originSession
                ? h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => copyAndFlash(sessionLinkCommand(row)),
                }, tr('action.copyLinkCommand'))
                : null,
              h('div', { className: 'scp-check-state' }, tr('sessions.hint'))),
            h('div', { className: 'scp-section-label' }, tr('section.evidence')),
            h('div', { className: 'scp-list-block' },
              evidenceList.length ? evidenceList.map((filePath) => h('div', { key: filePath, className: 'scp-evidence-row' },
                h('span', { className: 'scp-evidence-path', title: filePath }, filePath),
                h('button', { type: 'button', className: 'scp-check-action', onClick: () => copyPathAndFlash(filePath, flash) }, tr('action.copyPath'))))
                : h('div', { className: 'scp-mono' }, tr('evidence.none')),
              candidateList.length ? candidateList.map((candidate, index) => h('div', { key: 'cand-' + index, className: 'scp-candidate' },
                h('span', { className: 'scp-chip' }, candidate.kind || 'case'),
                h('span', { className: 'scp-candidate-text', title: candidate.summary }, candidate.summary || tr('none')),
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => candidateAction(row, candidate),
                }, tr('action.sedimentGeneric'))))
                : h('div', { className: 'scp-mono' }, tr('candidates.none')),
              h('div', { className: 'scp-upstream-row' },
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => toggleReport(row),
                }, reportState.open ? tr('action.hideReport') : tr('action.viewReport')),
                h('span', { className: 'scp-check-state' }, extra.hasReport ? tr('label.hasReport') : tr('report.none'))),
              reportState.open
                ? (reportState.loading ? h('div', { className: 'scp-mono' }, tr('report.loading'))
                  : reportState.error ? h('div', { className: 'scp-form-error' }, reportState.error)
                    : h('pre', { className: 'scp-report' }, reportState.text))
                : null),
            h('div', { className: 'scp-section-label' }, tr('section.timeline')),
            h('div', { className: 'scp-list-block' },
              h('div', { className: 'scp-upstream-row' },
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => toggleTimeline(row),
                }, timelineState.open ? tr('action.hideTimeline') : tr('action.loadTimeline')),
                timelineState.open && !timelineState.loading && !timelineState.error && timelineState.items.length
                  ? h('span', { className: 'scp-check-state' }, String(timelineState.items.length))
                  : null),
              timelineState.open
                ? (timelineState.loading ? h('div', { className: 'scp-mono' }, tr('timeline.loading'))
                  : timelineState.error ? h('div', { className: 'scp-form-error' }, timelineState.error)
                    : timelineState.items.length
                      ? timelineState.items.map((entry, index) => h('div', { key: 'tl-' + index, className: 'scp-tl-row' },
                        h('span', { className: 'scp-tl-step' }, entry.step ? '第 ' + entry.step + ' 步' : '—'),
                        h('div', { className: 'scp-tl-body' },
                          h('div', { className: 'scp-tl-meta' },
                            timelineRoleLabel(entry.role),
                            entry.action ? ' · ' + timelineActionLabel(entry.action) : ''),
                          h('div', {}, entry.output || entry.content || ''),
                          entry.reason ? h('div', { className: 'scp-tl-reason' }, entry.reason) : null,
                          entry.evidenceFiles && entry.evidenceFiles.length
                            ? h('div', { className: 'scp-tl-meta' }, entry.evidenceFiles.join('、'))
                            : null)))
                      : h('div', { className: 'scp-mono' }, tr('timeline.none')))
                : null),
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
            h('div', { className: 'scp-section-label' }, tr('section.history')),
            h('div', { className: 'scp-history' },
              history.length ? history.map((item, index) => h('div', { key: 'h-' + index, className: 'scp-history-row' },
                h('span', { className: 'scp-history-when' }, formatTime(item.at) || tr('none')),
                h('span', { className: 'scp-history-kind' }, tr('history.' + item.kind)),
                h('span', { className: 'scp-history-text', title: item.text }, item.text),
                item.note ? h('span', { className: 'scp-history-note', title: item.note }, item.note) : null))
                : h('div', { className: 'scp-mono' }, tr('history.none')),
              closeInfo ? h('div', { className: 'scp-upstream-row' },
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  disabled: undoBusy || !(data.capabilities && data.capabilities.canWrite),
                  title: data.capabilities && data.capabilities.canWrite ? tr('hint.undo') : tr('hint.readonly'),
                  onClick: () => undoClose(row),
                }, tr('action.undoClose'))) : null),
            h('div', { className: 'scp-actions' },
              h('button', {
                type: 'button',
                className: 'scp-btn scp-btn--primary',
                onClick: () => runPrimary(row),
              }, primaryFor(row, data.bound && row.sessionId === data.bound.sessionId).label),
              h('button', { type: 'button', className: 'scp-btn', onClick: () => copyAndFlash(summaryText(row, data)) }, tr('action.copySummary')),
              h('button', { type: 'button', className: 'scp-btn scp-btn--ghost', onClick: () => setMenuOpen(true) }, tr('action.more'))))
        : h('div', { className: 'scp-pal-side' },
          h('div', { className: 'scp-pal-empty' },
            emptyMark,
            !data ? tr('palette.loading') : tr('palette.empty')))

      // ── 沉淀视图的渲染件 ────────────────────────────────────────────────
      function openPrompt(kind, resume) {
        const k = String(kind || '')
        if (k !== 'groom' && k !== 'pr' && k !== 'check' && k !== 'close') return
        if (k === 'pr' && !sedTargetLabel) {
          openTarget('pr')
          return
        }
        setPromptKind(k)
        setPromptFallback(null)
        setPromptDetailsOpen(false)
        setBatchSed(null)
        setMenuOpen(false)
      }

      // 写台账被系统拒绝时的指令弹层：复用指令预览这一个面（复制 / 填入输入框），
      // 正文由失败上下文生成。点了才填进输入框，不自动发送，也不覆盖读者正在写的内容。
      function openPromptFallback(head, text, sub) {
        if (!text) return
        setPromptFallback({ head: String(head || ''), text: String(text), sub: String(sub || '') })
        setPromptKind('fallback')
        setPromptDetailsOpen(false)
        setBatchSed(null)
        setMenuOpen(false)
      }

      function closePrompt() {
        setPromptKind('')
        setPromptFallback(null)
        setBatchSed(null)
      }

      // 批量沉淀：名单在打开弹层时冻结（范围 = 当前筛选，含搜索词），预览后由读者决定填入还是复制。
      function openBatchSediment() {
        if (!diagSedRows.length) return
        const query = String(searchText || '').trim()
        setBatchSed({
          text: sedimentBatchDraft(diagSedRows, { query, total: filterRows(rows, 'sediment').length }),
          count: diagSedRows.length,
          query,
        })
        setPromptKind('sedimentBatch')
        setPromptDetailsOpen(false)
        setMenuOpen(false)
      }

      function openTarget(resume) {
        const remotes = sedRemotes
        const savedName = sedTarget && sedTarget.remote ? String(sedTarget.remote) : ''
        const recName = sedTargetDoc && sedTargetDoc.recommendation && sedTargetDoc.recommendation.remote
          ? String(sedTargetDoc.recommendation.remote) : ''
        const current = (savedName && remotes.find((item) => item.name === savedName))
          || (recName && remotes.find((item) => item.name === recName))
          || (remotes.length === 1 ? remotes[0] : null)
        const base = (savedName && current && current.name === savedName && (current.base || sedTarget.base))
          || (sedTargetDoc && sedTargetDoc.recommendation && sedTargetDoc.recommendation.base)
          || (current && current.base) || 'main'
        setTargetRemote(current ? current.name : '')
        setTargetBase(String(base))
        setTargetResume(String(resume || ''))
        setTargetOpen(true)
        closePrompt()
      }

      // 台账版本：list 侧返回的 sha256，写动作带上做 CAS；还没有台账时为空、不带令牌。
      function ledgerSha() {
        const doc = sedDoc && sedDoc.target ? sedDoc.target : null
        return doc && typeof doc.sha256 === 'string' ? doc.sha256 : ''
      }

      async function saveTarget() {
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (!targetRemote || targetBusy) return
        setTargetBusy(true)
        try {
          const result = await rpcCall('copilot-pr-target', {
            action: 'set-target',
            cwd: s.cwd,
            sessionId: s.sessionId,
            remote: targetRemote,
            base: targetBase,
            expectSha256: ledgerSha(),
          })
          if (!result || result.ok === false) {
            const message = result && (result.message || (result.error && result.error.message))
            const writeKind = prWriteFailureKind(result)
            if (writeKind) {
              // 台账没写进去时带 CAS 令牌；写配置失败时台账已经写过，旧令牌只会先撞 E_CAS。
              const target = failureCode(result) === 'E_SETTINGS' ? 'settings' : 'ledger'
              setTargetOpen(false)
              openPromptFallback(tr('sediment.fallback.targetTitle'), prWriteFallbackText(
                message,
                'python3 scripts/pr_status.py --root . --set-target --remote ' + targetRemote
                + ' --base ' + targetBase + (target === 'ledger' ? ledgerCasArg() : ''),
                { kind: writeKind, target }))
              return
            }
            flash(message || tr('sediment.target.required'))
            if (failureCode(result) === 'E_CAS') await refreshSediment(true)
            return
          }
          setTargetOpen(false)
          const resume = targetResume
          setTargetResume('')
          await refreshSediment(true)
          if (resume) {
            setPromptKind(resume)
            setPromptDetailsOpen(false)
          }
        } catch (error) {
          flash(String((error && error.message) || error))
        } finally {
          setTargetBusy(false)
        }
      }

      function closeTarget() {
        const resume = targetResume
        setTargetOpen(false)
        setTargetResume('')
        if (resume && sedTargetLabel) {
          setPromptKind(resume)
          setPromptDetailsOpen(false)
        }
      }

      async function checkPr(key) {
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (!key || checkBusy) return
        const runSession = store.sessionId
        setCheckBusy(key)
        try {
          const result = await rpcCall('copilot-pr-target', {
            action: 'check', cwd: s.cwd, sessionId: s.sessionId, key, expectSha256: ledgerSha(),
          })
          if (!result || result.ok === false) {
            const message = result && (result.message || (result.error && result.error.message))
            // 失败也可能已经写了台账（查不到时写 unknown + checked_at），刷新把行里的状态与时间对齐。
            await refreshSediment(true)
            // 刷新期间切了会话：旧 key 的兜底弹层不能弹在新会话上。
            if (store.sessionId !== runSession) return
            const writeKind = prWriteFailureKind(result)
            if (writeKind) {
              // 平台结果拿到了、台账没写进去：给一条能填进输入框的指令交给会话 agent 写。
              const state = result && PR_STATE_KEYS.indexOf(String(result.state || '')) >= 0
                ? tr('sediment.prState.' + String(result.state)) : ''
              openPromptFallback(tr('sediment.primary.check'), prWriteFallbackText(
                message,
                'python3 scripts/pr_status.py --root . --check --draft ' + key + ledgerCasArg(),
                { kind: writeKind, checkedStates: state ? [state] : [] }))
              return
            }
            flash(tr('sediment.checkFailedOne', { reason: message || tr('sediment.checkError.unknown') }))
            return
          }
          await refreshSediment(true)
          const draft = sedDrafts.find((item) => item && item.key === key) || null
          const prNo = draft && draft.pr && draft.pr.number ? '#' + draft.pr.number : key
          const state = result && PR_STATE_KEYS.indexOf(String(result.state || '')) >= 0
            ? String(result.state) : 'unknown'
          flash(tr('sediment.checkDoneOne', { pr: prNo, state: tr('sediment.prState.' + state) }))
        } catch (error) {
          flash(String((error && error.message) || error))
        } finally {
          setCheckBusy('')
        }
      }

      // pr_status.py 的失败载荷把 code 放在 error.code（_fail 的形状）；个别调用给的是顶层 code。
      // 两处都读，否则「没配 token」这类原因在生产会被丢掉（存储的失败形状见 host-smoke 的 resultCode）。
      function failureCode(result) {
        if (!result || typeof result !== 'object') return ''
        if (typeof result.code === 'string' && result.code) return result.code
        if (result.error && typeof result.error.code === 'string') return result.error.code
        return ''
      }

      // 写本地文件被拒绝时该给哪一层指令：'file' = 文件/权限层拒绝（写台账、写配置），
      // 'policy' = 会话档位或沙箱可写面的判断（命令在会话 shell 里通常能过）。
      // 读坏台账也是 E_LEDGER，不能当作写失败去生成写指令。
      function prWriteFailureKind(result) {
        const code = failureCode(result)
        if (code === 'E_PERM') return 'policy'
        if (code === 'E_SETTINGS') return 'file'
        const message = String((result && (result.message || (result.error && result.error.message))) || '')
        if (code === 'E_LEDGER') {
          if (result && result.write_failed === true) return 'file'
          // 旧版脚本没有 write_failed 标记，按它当时的两句写失败原文认。
          return /台账写不进去|配置写不进去|写锁不可用/.test(message) ? 'file' : ''
        }
        if (code !== 'E_INTERNAL') return ''
        // 面板与脚本版本错配：旧脚本把系统拒绝落成 E_INTERNAL 的裸异常。
        return /PermissionError|WinError (5|32)\b|Errno (13|1)\b|Access is denied|Operation not permitted|拒绝访问/.test(message) ? 'file' : ''
      }

      // 兜底指令正文：查到的状态、写的是哪份文件、哪条命令、命令也失败时查什么。
      // 参数 opts：kind（file / policy）、target（ledger / settings）、checkedStates（人读的状态名）。
      function prWriteFallbackText(message, command, opts) {
        const options = opts || {}
        const lines = []
        const checked = Array.isArray(options.checkedStates) ? options.checkedStates.filter(Boolean) : []
        if (checked.length === 1) lines.push(tr('sediment.fallback.checked', { state: checked[0] }))
        else if (checked.length > 1) {
          // 大批次不把整串状态塞进弹层：最多列 5 条，其余用省略号。
          const list = checked.slice(0, 5).join('、') + (checked.length > 5 ? '…' : '')
          lines.push(tr('sediment.fallback.checkedMany', { n: checked.length, list }))
        }
        if (options.kind === 'policy') lines.push(tr('sediment.fallback.policyLede'))
        else if (options.target === 'settings') lines.push(tr('sediment.fallback.settingsLede'))
        else lines.push(tr('sediment.fallback.ledgerLede'))
        lines.push(tr('sediment.fallback.reason', {
          reason: String(message || tr('sediment.checkError.unknown')),
        }))
        lines.push(tr('sediment.fallback.command'))
        lines.push(String(command || ''))
        if (options.target === 'settings') {
          lines.push(tr('sediment.fallback.settings', { path: '.local/settings.json' }))
        } else {
          lines.push(tr('sediment.fallback.ledger', { path: 'postmortems/inbox/.groom/pr-state.json' }))
        }
        if (options.kind === 'policy') lines.push(tr('sediment.fallback.repairPolicy'))
        else {
          lines.push(tr('sediment.fallback.repairFile'))
          lines.push(tr('sediment.fallback.repairFileAcl'))
        }
        return lines.join('\n')
      }

      // 台账 CAS 令牌跟着兜底命令走：面板手里有 sha 时带上，恢复动作不绕开 CAS。
      // 写配置失败不带：那一路台账已经写过，旧令牌会先撞 E_CAS。
      function ledgerCasArg() {
        const sha = ledgerSha()
        return sha ? ' --expect-sha256 ' + sha : ''
      }

      function checkErrorText(code) {
        const key = String(code || 'unknown')
        const text = tr('sediment.checkError.' + key)
        if (text !== 'sediment.checkError.' + key) return text
        const generic = tr('sediment.checkError.unknown')
        return key && key !== 'unknown' ? generic + '（' + key + '）' : generic
      }

      async function checkAllPrs() {
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (checkBusy) return
        setCheckBusy('__all__')
        beginCheckRun(sedDrafts)
        const run = store.checkRun
        const runSession = store.sessionId
        const runCwd = store.cwd
        let timer = 0
        let stopped = false
        let polling = false
        let failures = 0
        const stopPoll = () => {
          if (stopped) return
          stopped = true
          if (timer) {
            clearInterval(timer)
            timer = 0
          }
          if (store.checkStop === stopPoll) store.checkStop = null
        }
        // 切会话 / 卸载时由 store.checkStop 打断在飞的轮询。
        store.checkStop = stopPoll
        // 轮询异常只降级：连续几次失败就安静停下，整批仍以主 RPC 为准。
        const poll = async () => {
          if (stopped || polling) return
          polling = true
          try {
            const value = await rpcCall('copilot-pr-progress', {
              cwd: runCwd, sessionId: runSession,
            })
            // await 期间主 RPC 可能已 settle、或已切会话：旧响应不能再 patch 新快照。
            if (stopped || store.checkRun !== run) return
            failures = 0
            // present=false：本轮 check-all 还没落地（服务端慢 resolve 阶段），既不应用也不停。
            if (!value || value.present !== true) return
            if (Array.isArray(value.rows)) applyCheckProgress(value.rows, run)
            if (value.done === true) stopPoll()
          } catch {
            failures += 1
            if (failures >= PR_PROGRESS_MAX_FAILURES) stopPoll()
          } finally {
            polling = false
          }
        }
        try {
          // 先把主 RPC 发出去，再起轮询：不 await 之后才开始轮询，否则进度永远晚一步。
          const pending = rpcCall('copilot-pr-target', {
            action: 'check-all', cwd: runCwd, sessionId: runSession,
          })
          timer = setInterval(() => { poll() }, PR_PROGRESS_POLL_MS)
          let result
          try {
            result = await pending
          } catch (error) {
            stopPoll()
            if (store.sessionId !== runSession) return
            await refreshSediment(true)
            flash(String((error && error.message) || error))
            return
          }
          // 先停轮询再刷新，避免刷新写回的行被后到的进度覆写、状态闪回。
          stopPoll()
          if (store.sessionId !== runSession) return
          await refreshSediment(true)
          if (!result || result.ok === false) {
            const partial = failureCode(result) === 'E_CHECK_PARTIAL'
            const failed = result && Array.isArray(result.checked)
              ? result.checked.filter((item) => item && item.ok === false) : []
            const codes = Array.from(new Set(failed.map((item) => String(item.error || 'unknown'))))
            const reason = codes.map(checkErrorText).filter(Boolean).join('、')
            const message = result && (result.message || (result.error && result.error.message))
            // 部分失败是查询类问题、台账已经写进去了；整体写失败才给指令。
            if (store.sessionId !== runSession) return
            const writeKind = !partial ? prWriteFailureKind(result) : ''
            if (writeKind) {
              const states = (Array.isArray(result.checked) ? result.checked : [])
                .filter((item) => item && item.ok !== false
                  && PR_STATE_KEYS.indexOf(String(item.state || '')) >= 0)
                .map((item) => String(item.draft || '') + ' ' + tr('sediment.prState.' + String(item.state)))
              openPromptFallback(tr('sediment.primary.checkAll'), prWriteFallbackText(
                message, 'python3 scripts/pr_status.py --root . --check-all',
                { kind: writeKind, checkedStates: states }))
              return
            }
            flash(partial
              ? (reason ? tr('sediment.checkFailedWith', { reason }) : tr('sediment.checkFailed'))
              : (message || tr('sediment.checkFailed')))
            return
          }
          const checked = result && Array.isArray(result.checked) ? result.checked : []
          flash(checked.length
            ? tr('sediment.checkDone', { n: checked.length })
            : tr('sediment.checkNone'))
        } finally {
          stopPoll()
          endCheckRun()
          setCheckBusy('')
        }
      }

      // 人工兜底：平台一直查不到时，按人确认写台账（source=manual）。只写本地台账，
      // 下一次「查合入状态」仍以平台结果为准。
      async function markState(key, state) {
        const nextState = String(state || '')
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (!key || checkBusy || PR_STATE_KEYS.indexOf(nextState) < 0) return
        setCheckBusy(key)
        try {
          const result = await rpcCall('copilot-pr-target', {
            action: 'mark', cwd: s.cwd, sessionId: s.sessionId, key, state: nextState,
            expectSha256: ledgerSha(),
          })
          if (!result || result.ok === false) {
            const message = result && (result.message || (result.error && result.error.message))
            const writeKind = prWriteFailureKind(result)
            if (writeKind) {
              // 手动改状态与查合入写同一份台账：写不进时也给指令，不让读者对着不可写的文件重试。
              setManualOpen(false)
              openPromptFallback(tr('sediment.manualState'), prWriteFallbackText(
                message,
                'python3 scripts/pr_status.py --root . --mark --draft ' + key + ' --state '
                + nextState + ledgerCasArg(),
                { kind: writeKind }))
              return
            }
            flash(message || tr('sediment.error', { message: '' }))
            if (failureCode(result) === 'E_CAS') await refreshSediment(true)
            return
          }
          await refreshSediment(true)
          setManualOpen(false)
          flash(tr('sediment.manualDone', { state: tr('sediment.prState.' + nextState) }))
        } catch (error) {
          flash(String((error && error.message) || error))
        } finally {
          setCheckBusy('')
        }
      }

      function markMerged(key) {
        return markState(key, 'merged')
      }

      function runSedNext(draft) {
        const kind = sedPrimaryKey(draft)
        if (!kind) return
        if (kind === 'restore') {
          const text = String((draft && draft.restore) || '')
          if (text) fillDraft(text)
          else flash(tr('sediment.prompt.empty'))
          return
        }
        // 单条查合入与批次一致：有写权限就地查，不弹指令层。
        if (kind === 'check' && canWrite) {
          checkPr(draft.key)
          return
        }
        openPrompt(kind)
      }

      const sedDecidedRows = sedDrafts.filter((draft) => draft.state === 'decided')
      const sedDecided = Number(sedCounts.decided) || 0
      const sedOldest = Number(sedCounts.oldestDays) || sedDrafts.reduce((max, draft) => {
        const age = draft.ageDays === null || draft.ageDays === undefined ? -1 : Number(draft.ageDays)
        return age > max ? age : max
      }, 0)
      const sedPrimaryKind = sedDoc && sedDoc.primary ? String(sedDoc.primary.kind || 'none') : 'none'
      // 批次条的「查合入」查的是整批，详情里的查单条；两处标签分开写，免得读者分不清作用域。
      const sedPrimaryLabel = sedPrimaryKind === 'check'
        ? tr('sediment.primary.checkAll')
        : (sedDoc && sedDoc.primary && sedDoc.primary.label
          ? String(sedDoc.primary.label)
          : tr('sediment.batch.none'))
      const sedUnassessed = Number(sedCounts.unassessed) || 0
      const sedNeedDecision = Number(sedCounts.needDecision) || 0
      const sedNeedRerun = Number(sedCounts.needRerun) || 0
      const sedPrOpen = Number(sedCounts.prOpen) || 0
      const sedPrMerged = Number(sedCounts.prMerged) || 0
      const sedFilterDefs = [
        { key: 'all', label: tr('sediment.filter.all'), n: sedDrafts.length },
        { key: 'decision', label: tr('sediment.filter.decision'), n: sedUnassessed + sedNeedDecision },
        { key: 'pr', label: tr('sediment.filter.pr'), n: sedDecided },
        { key: 'check', label: tr('sediment.filter.check'), n: sedPrOpen + sedPrMerged },
        { key: 'rerun', label: tr('sediment.filter.rerun'), n: sedNeedRerun },
      ]

      const runSedPrimary = () => {
        if (sedPrimaryKind === 'none') return
        if (sedPrimaryKind === 'restore') {
          const text = String((sedDoc && sedDoc.prompts && sedDoc.prompts.restore) || '')
          if (text) fillDraft(text)
          else flash(tr('sediment.prompt.empty'))
          return
        }
        // 查合入不再生成指令：有写权限时直接查平台并回写台账，结果回到行里。
        if (sedPrimaryKind === 'check' && canWrite) {
          checkAllPrs()
          return
        }
        openPrompt(sedPrimaryKind)
      }

      const sedBatch = view === 'sediment' ? h('div', { className: 'scp-batch' },
        h('span', { className: 'scp-batch-strong' }, tr('sediment.batch.total', { n: sedDrafts.length })),
        sedUnassessed + sedNeedDecision > 0
          ? h('span', { className: 'scp-batch-chip', 'data-tone': 'warn' }, String(sedUnassessed + sedNeedDecision) + ' ' + tr('sediment.filter.decision'))
          : null,
        sedDecided > 0
          ? h('span', { className: 'scp-batch-chip', 'data-tone': 'accent' }, String(sedDecided) + ' ' + tr('sediment.filter.pr'))
          : null,
        sedPrOpen + sedPrMerged > 0
          ? h('span', { className: 'scp-batch-chip', 'data-tone': 'ok' }, String(sedPrOpen + sedPrMerged) + ' ' + tr('sediment.filter.check'))
          : null,
        sedNeedRerun > 0
          ? h('span', { className: 'scp-batch-chip', 'data-tone': 'bad' }, String(sedNeedRerun) + ' ' + tr('sediment.filter.rerun'))
          : null,
        sedOldest > 0
          ? h('span', { className: 'scp-batch-age', 'data-over': sedOldest > 14 ? 'true' : 'false' }, tr('sediment.batch.oldest', { n: sedOldest }))
          : null,
        h('span', { className: 'scp-spacer' }),
        sedDecided > 0 && sedPrimaryKind !== 'pr'
          ? h('button', {
            type: 'button', className: 'scp-btn',
            onClick: () => openPrompt('pr'),
          }, tr('sediment.secondary.pr', { n: sedDecided }))
          : null,
        h('button', {
          type: 'button',
          className: 'scp-btn scp-btn--primary',
          disabled: sedPrimaryKind === 'none' || checkBusy === '__all__',
          onClick: runSedPrimary,
        }, checkBusy === '__all__'
          ? (checkRun && checkRun.active && checkRun.total > 0
            ? tr('sediment.checkingProgress', {
              n: Math.min(checkRun.seen, checkRun.total),
              m: checkRun.total,
            })
            : tr('sediment.refreshing'))
          : sedPrimaryLabel)) : null

      // 诊断视图的批量沉淀：只在「可沉淀」筛选下出现，范围就是当前筛选（含搜索词）。
      // 只生成指令、不写 trace 与知识库；单条动作仍在右列详情里。
      const diagBatch = view === 'diagnosis' && diagSedRows.length ? h('div', {
        className: 'scp-batch', 'data-kind': 'sediment-batch', role: 'group', 'aria-label': tr('diag.batch.fill'),
      },
        h('span', { className: 'scp-batch-strong' }, tr('diag.batch.count', { n: diagSedRows.length })),
        h('span', { className: 'scp-batch-age' }, tr('diag.batch.scope')),
        searchText.trim() ? h('span', { className: 'scp-batch-chip', 'data-tone': 'gray' }, tr('diag.batch.search', { q: searchText.trim() })) : null,
        data && data.capabilities && data.capabilities.canWrite === false
          ? h('span', { className: 'scp-batch-chip', 'data-tone': 'warn' }, tr('diag.batch.readonly'))
          : null,
        h('span', { className: 'scp-spacer' }),
        h('button', {
          type: 'button',
          className: 'scp-btn scp-btn--primary',
          onClick: openBatchSediment,
        }, tr('diag.batch.fill'))) : null

      const sedHistory = sedDoc && Array.isArray(sedDoc.history) ? sedDoc.history.slice(0, 5) : []
      const sedListInner = !sedDoc
        ? (sedPhase === 'error'
          ? h('div', { className: 'scp-pal-empty' },
            h('span', {}, tr('sediment.error', { message: s.sediment.message || '' })),
            h('button', { type: 'button', className: 'scp-btn', onClick: () => refreshSediment(true) }, tr('sediment.refresh')))
          : Array.from({ length: 4 }, (_, index) => h('div', { key: 'sed-skel-' + index, className: 'scp-pal-row' },
            h('span', { className: 'scp-ring', style: { background: 'var(--scp-surface-3)' } }),
            h('span', { className: 'scp-pal-row-main' },
              h('span', { className: 'scp-skel', style: { width: '70%' } }),
              h('span', { className: 'scp-skel', style: { width: '44%', height: 9 } })))))
        : sedDrafts.length === 0
          ? h('div', { className: 'scp-pal-empty' },
            h('span', {}, tr('sediment.empty')),
            h('span', {}, tr('sediment.emptyHint')),
            h('button', {
              type: 'button', className: 'scp-btn', onClick: () => setPaletteView('diagnosis'),
            }, tr('sediment.goDiagnosis')),
            sedHistory.length
              ? h('div', { className: 'scp-sed-history' },
                h('div', { className: 'scp-section-label' }, tr('sediment.history')),
                sedHistory.map((item) => h('div', { key: item.key, className: 'scp-sed-history-row' },
                  h('span', { className: 'scp-sed-history-title' }, item.title || item.key),
                  h('span', { className: 'scp-chip' }, item.state === 'knowledge' ? tr('sediment.stepper.promoted') : tr('sediment.history.archived')),
                  item.pr && item.pr.url && /^https?:\/\//i.test(String(item.pr.url))
                    ? h('a', {
                      className: 'scp-link', href: String(item.pr.url), target: '_blank',
                      rel: 'noopener noreferrer', title: String(item.pr.url),
                    }, (item.pr.number ? '#' + item.pr.number : tr('sediment.detail.pr')) + ' ↗')
                    : null,
                  item.at ? h('span', { className: 'scp-sed-hint' }, formatTime(item.at) || item.at) : null)))
              : null)
          : sedSorted.length === 0
            ? h('div', { className: 'scp-pal-empty' }, tr('palette.empty'))
            : (() => {
              const order = ['groom', 'pr', 'check', 'other']
              const labels = {
                groom: tr('sediment.group.groom'),
                pr: tr('sediment.group.pr'),
                check: tr('sediment.group.check'),
                other: tr('sediment.group.other'),
              }
              const grouped = {}
              sedSorted.forEach((draft, index) => {
                const group = sedGroupOf(draft)
                if (!grouped[group]) grouped[group] = []
                grouped[group].push({ draft, index })
              })
              return order.filter((group) => grouped[group] && grouped[group].length).map((group) => h('div', { key: 'sed-group-' + group },
                h('div', { className: 'scp-sed-group' },
                  h('span', {}, labels[group]),
                  h('span', {}, String(grouped[group].length))),
                grouped[group].map(({ draft, index }) => {
                  const age = draft.ageDays
                  // 查合入进行中：已到的行显示状态或失败原因，还没到的标「查询中」。
                  const runState = checkRun && checkRun.states ? checkRun.states[draft.key] : null
                  const runPending = !runState && checkRun && checkRun.active
                    && checkRun.targets && checkRun.targets[draft.key] === true
                  return h('button', {
                    key: draft.key,
                    type: 'button',
                    className: 'scp-sed-row',
                    'data-on': index === sedSel ? 'true' : 'false',
                    onClick: () => setSedSel(index),
                    onDoubleClick: () => runSedNext(draft),
                    onKeyDown: (event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        runSedNext(draft)
                      }
                    },
                  },
                    h('span', { className: 'scp-sed-dot', 'aria-hidden': 'true', style: { background: SED_DOT[draft.stageTone] || SED_DOT.gray } }),
                    h('span', { className: 'scp-sed-main' },
                      h('span', { className: 'scp-sed-line' },
                        h('span', { className: 'scp-sed-title', title: draft.title || draft.key }, draft.title || draft.key),
                        h('span', { className: 'scp-sed-age', 'data-over': age !== null && age !== undefined && Number(age) > 14 ? 'true' : 'false' }, sedAgeText(draft))),
                      h('span', { className: 'scp-sed-meta' },
                        // 有进度行时不再显示旧阶段 chip（否则「已提 PR · 合入未确认」与「已合入」并排）。
                        runState
                          ? null
                          : h('span', { className: 'scp-chip', 'data-tone': SED_CHIP_TONE[draft.stageTone] || 'none' }, draft.stage || draft.state),
                        draft.pr && draft.pr.number
                          ? h('span', { className: 'scp-chip' }, '#' + draft.pr.number)
                          : null,
                        runState
                          ? h('span', {
                            className: 'scp-chip',
                            'data-tone': runState.ok ? 'ok' : 'bad',
                            title: runState.ok ? (runState.checkedAt || '') : (runState.message || ''),
                          }, runState.ok
                            ? tr('sediment.prState.' + runState.state)
                            : checkErrorText(runState.error))
                          : (runPending
                            ? h('span', { className: 'scp-chip', 'data-tone': 'accent' }, tr('sediment.checking'))
                            : null),
                        draft.decision
                          ? h('span', {}, draft.decision)
                          : (draft.novelty ? h('span', {}, draft.novelty + (draft.confidence ? ' · ' + draft.confidence : '')) : null),
                        draft.source && draft.source.sessionId
                          ? h('span', {}, draft.source.sessionId)
                          : null)))
                })))
            })()

      const sedList = h('div', { className: 'scp-pal-list', role: 'region', 'aria-label': tr('palette.sedimentTitle') },
        h('div', { className: 'scp-search' },
          h('input', {
            ref: searchRef, type: 'search', value: searchText,
            placeholder: tr('search.placeholder'), 'aria-label': tr('search.placeholder'),
            onChange: (event) => { setSearchText(event.target.value); setSedSel(0) },
            onKeyDown: (event) => { if (event.key === 'Escape') { setSearchText(''); event.stopPropagation() } },
          }),
          h('span', { className: 'scp-kbd' }, '/')),
        h('div', { className: 'scp-filters', role: 'group', 'aria-label': tr('palette.filterLabel') },
          sedFilterDefs.map((item) => h('button', {
            key: item.key,
            type: 'button',
            className: 'scp-filter-item',
            'data-on': sedFilter === item.key ? 'true' : 'false',
            onClick: () => setSedFilter(item.key),
          }, item.label, h('b', {}, String(item.n))))),
        sedListInner)

      const sedStepsOf = sedPick ? sedSteps(sedPick) : []
      const sedMismatch = sedPick && sedPick.source ? String(sedPick.source.mismatch || 'none') : 'none'
      const sedMismatchKey = 'sediment.detail.mismatch.' + sedMismatch
      const sedNextKind = sedPick ? sedPrimaryKey(sedPick) : ''
      const sedNextLabel = sedPick && sedPick.next && sedPick.next.label
        ? (sedNextKind === 'pr' && sedDecided > 1
          ? tr('sediment.primary.prBatch', { n: sedDecided })
          : String(sedPick.next.label))
        : tr('sediment.batch.none')
      const sedSideInner = !sedPick
        ? h('div', { className: 'scp-pal-empty' },
          h('span', {}, sedDoc ? tr('sediment.empty') : tr('palette.loading')))
        : (() => {
          const blocks = []
          blocks.push(h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-stepper' },
              sedStepsOf.map((step) => h('div', { key: step.key, className: 'scp-sed-step', 'data-state': step.state },
                h('span', { className: 'scp-sed-step-dot', 'aria-hidden': 'true' }, '✓'),
                h('span', { className: 'scp-sed-step-label' }, step.label),
                step.note ? h('span', { className: 'scp-sed-step-note', 'data-bad': step.state === 'blocked' ? 'true' : 'false' }, step.note) : null)))))
          const assessmentRows = [
            h('div', { key: 'suggestion', className: 'scp-sed-kv-row' },
              h('dt', {}, tr('sediment.detail.suggestion')),
              h('dd', {}, [sedPick.novelty || '-', sedPick.confidence || '', sedPick.candidate ? '(' + sedPick.candidate + ')' : ''].filter(Boolean).join(' '))),
          ]
          if (sedPick.rationale) {
            assessmentRows.push(h('div', { key: 'rationale', className: 'scp-sed-kv-row' },
              h('dt', {}, tr('sediment.detail.rationale')), h('dd', {}, sedPick.rationale)))
          }
          if (sedPick.reviewReasons && sedPick.reviewReasons.length) {
            assessmentRows.push(h('div', { key: 'review', className: 'scp-sed-kv-row' },
              h('dt', {}, tr('sediment.detail.review')), h('dd', {}, sedPick.reviewReasons.join('；'))))
          }
          assessmentRows.push(h('div', { key: 'assessed', className: 'scp-sed-kv-row' },
            h('dt', {}, tr('sediment.detail.assessed')),
            h('dd', {}, sedPick.assessedShort || (sedPick.closedDraft && sedPick.assessed && sedPick.assessmentCleared
              ? tr('sediment.detail.assessmentCleared') : tr('sediment.assessedUnknown')))))
          blocks.push(h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-section-label' }, tr('sediment.detail.assessment')),
            h('div', { className: 'scp-sed-kv' }, assessmentRows)))

          const decisionRows = []
          if (sedPick.decisionValid) {
            decisionRows.push(h('div', { key: 'decision', className: 'scp-sed-kv-row' },
              h('dt', {}, tr('sediment.detail.decisionValue')), h('dd', {}, sedPick.decision || '-')))
            if (sedPick.decisionBy) {
              decisionRows.push(h('div', { key: 'by', className: 'scp-sed-kv-row' },
                h('dt', {}, ''), h('dd', {}, sedPick.decisionBy + (sedPick.decisionAt ? ' · ' + sedPick.decisionAt : ''))))
            }
          }
          blocks.push(h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-section-label' }, tr('sediment.detail.decision')),
            decisionRows.length
              ? h('div', { className: 'scp-sed-kv' }, decisionRows)
              : h('div', { className: 'scp-sed-hint' }, tr('sediment.detail.noDecision'))))

          const prPending = sedPick.pr && (sedPick.pr.state === 'open' || sedPick.pr.state === 'unknown')
          const landed = sedPick.state === 'done' || (sedPick.pr && sedPick.pr.state === 'merged')
          const landing = landed
            ? ((sedPick.promotion && (sedPick.promotion.casePath || sedPick.promotion.postmortemPath)) || tr('sediment.detail.noPr'))
            : ((sedPick.promotion && sedPick.promotion.caseId)
              ? tr('sediment.detail.candidate') + ' ' + sedPick.promotion.caseId + ' · '
                + (prPending ? tr('sediment.detail.landingPending') : tr('sediment.detail.noPr'))
              : tr('sediment.detail.noPr'))
          const prStateLabel = tr('sediment.prState.' + ((sedPick.pr && sedPick.pr.state) || 'unknown'))
          const prSourceLabel = tr('sediment.prSource.' + ((sedPick.pr && sedPick.pr.source) || 'ledger'))
          const prChecked = sedPick.pr && sedPick.pr.checkedAt
            ? tr('sediment.detail.lastChecked') + ' ' + (formatTime(sedPick.pr.checkedAt) || sedPick.pr.checkedAt)
            : ''
          const prText = sedPick.pr
            ? '#' + sedPick.pr.number + ' · ' + prStateLabel + ' · ' + prSourceLabel
              + (sedPick.pr.url ? ' · ' + sedPick.pr.url : '') + (prChecked ? ' · ' + prChecked : '')
            : tr('sediment.detail.noPr')
          blocks.push(h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-section-label' }, tr('sediment.detail.promotion')),
            h('div', { className: 'scp-sed-kv' },
              h('div', { className: 'scp-sed-kv-row' }, h('dt', {}, tr('sediment.detail.case')), h('dd', {}, landing)),
              h('div', { className: 'scp-sed-kv-row' }, h('dt', {}, tr('sediment.detail.pr')), h('dd', {}, prText)))))

          const prRowBusy = checkBusy === sedPick.key || checkBusy === '__all__'
          const prActionButtons = sedPick.pr ? [
            h('button', {
              key: 'check', type: 'button', className: 'scp-btn',
              disabled: prRowBusy,
              // 只读档位不写台账，但可以生成查证指令；与批次条和 Enter 的行为一致。
              title: canWrite ? undefined : tr('sediment.check.readonly'),
              onClick: () => { if (canWrite) checkPr(sedPick.key); else openPrompt('check') },
            }, checkBusy === sedPick.key ? tr('sediment.refreshing') : tr('sediment.check')),
            sedPick.pr.state !== 'merged'
              ? h('button', {
                key: 'mark', type: 'button', className: 'scp-btn',
                disabled: prRowBusy || !canWrite,
                title: canWrite ? undefined : writeDisabledReason(s.data),
                onClick: () => markMerged(sedPick.key),
              }, tr('sediment.markMerged'))
              : null,
            h('button', {
              key: 'manual', type: 'button', className: 'scp-btn scp-btn--ghost',
              disabled: prRowBusy || !canWrite,
              title: canWrite ? undefined : writeDisabledReason(s.data),
              onClick: () => setManualOpen(true),
            }, tr('sediment.manualState')),
          ] : []
          // 查合入这一个动作只给一个入口：next 是 check 时由上面 PR 行的「查合入状态」承担，
          // 这里是整批动作，批次条另有一个「查全部合入状态」。
          const showNextAction = !(sedNextKind === 'check' && sedPick.pr)
          blocks.push(h('div', { className: 'scp-sed-actions' },
            showNextAction ? h('button', {
              type: 'button', className: 'scp-btn', disabled: !sedNextKind,
              onClick: () => runSedNext(sedPick),
            }, sedNextLabel) : null,
            ...prActionButtons,
            h('button', { type: 'button', className: 'scp-btn', onClick: () => refreshSediment(true) }, tr('sediment.refresh')),
            // 撤销只生成指令、面板不删草稿：点开先看计划，读者点了才填进输入框。
            sedPick.undo && sedPick.undo.available && sedPick.undo.prompt
              ? h('button', {
                type: 'button', className: 'scp-btn scp-btn--ghost',
                title: tr('sediment.undo.hint'),
                onClick: () => openPromptFallback(
                  tr('sediment.undo.title'), sedPick.undo.prompt, tr('sediment.undo.sub')),
              }, tr('sediment.undo.action'))
              : null,
            // 推送目标只在要开 PR 时才有意义；已有 PR 的行不再用「推送目标未设置」暗示没有 PR。
            sedNextKind === 'pr'
              ? h('span', { className: 'scp-sed-hint' }, sedTargetHint)
              : null))

          const head = []
          // 抬头与诊断详情一致：一行识别信息 + 正文层的问题背景，不把首句放大加粗。
          // 来源诊断显示 trace 单号，跳的是它记的 harness 会话号；两个值不同，单号不在会话列表里。
          const sedSourceTrace = sedPick.source ? String(sedPick.source.sessionId || '') : ''
          const sedSourceSession = sedPick.source ? String(sedPick.source.harnessSession || '') : ''
          head.push(h('div', { key: 'identity', className: 'scp-identity' },
            h('span', { className: 'scp-badge', 'data-tone': SED_CHIP_TONE[sedPick.stageTone] || 'none' }, sedPick.stage || sedPick.state),
            sedPick.novelty ? h('span', { className: 'scp-chip' }, sedPick.novelty + (sedPick.confidence ? ' · ' + sedPick.confidence : '')) : null,
            sedSourceTrace
              ? (sedSourceSession
                ? h('button', {
                  type: 'button', className: 'scp-link',
                  title: sedSourceSession,
                  onClick: () => openSessionWithFlash(sedSourceSession, flash),
                }, sedSourceTrace + ' ↗')
                : h('span', { className: 'scp-mono', title: tr('sessions.missing') }, sedSourceTrace))
              : null,
            h('span', { className: 'scp-identity-meta' }, sedAgeText(sedPick))))
          head.push(h('p', {
            key: 'lede',
            className: 'scp-lede',
            ref: sedLedeRef,
            'data-open': sedLedeOpen ? 'true' : 'false',
            title: sedPickTitle,
          }, inlineTokens(sedPickTitle)))
          if (sedLedeOverflow) {
            head.push(h('button', {
              type: 'button', className: 'scp-more',
              'aria-expanded': sedLedeOpen ? 'true' : 'false',
              onClick: () => setSedLedeOpenKey(sedLedeOpen ? '' : String(sedPick.key || '')),
            }, sedLedeOpen ? tr('lede.collapse') : tr('lede.expand')))
          }
          if (sedPick.ageDays !== null && sedPick.ageDays !== undefined && Number(sedPick.ageDays) > 14) {
            head.push(h('div', { key: 'overdue', className: 'scp-sed-hint' },
              tr('sediment.overdue') + ' · ' + tr('sediment.batch.oldest', { n: sedPick.ageDays })))
          }
          if (sedPick.closedDraft) {
            head.push(h('div', { key: 'closed', className: 'scp-sed-hint' }, tr('sediment.detail.closedDraft')))
          }
          const sedTargetState = sedPick.targetState && sedPick.targetState !== 'ok'
            ? tr('sediment.targetState.' + sedPick.targetState) : ''
          const sedTargetRef = String(sedPick.targetRef || sedPick.targetShort || '')
          if (sedTargetRef || sedTargetState) {
            head.push(h('div', { key: 'target', className: 'scp-sed-hint' },
              tr('sediment.detail.target') + '：' + (sedTargetRef || '—')
              + (sedTargetState ? ' · ' + sedTargetState : '')))
          }
          if ((sedPick.targetWarnings || []).length) {
            head.push(h('div', { key: 'targetWarnings', className: 'scp-callout', style: { background: 'var(--scp-warn-soft)', borderColor: 'color-mix(in srgb, var(--scp-warn) 26%, var(--scp-border))' } },
              h('span', { className: 'scp-callout-label' }, tr('sediment.detail.targetWarnings')),
              h('span', { className: 'scp-callout-text' }, sedPick.targetWarnings.join('；'))))
          }
          if (sedPick.stale) {
            head.push(h('div', { key: 'stale', className: 'scp-callout', style: { background: 'var(--scp-bad-soft)', borderColor: 'color-mix(in srgb, var(--scp-bad) 26%, var(--scp-border))' } },
              h('span', { className: 'scp-callout-label' }, tr('sediment.stepper.assessed')),
              h('span', { className: 'scp-callout-text' }, (sedPick.staleReasons || []).join('；'))))
          }
          if (sedMismatch !== 'none') {
            head.push(h('div', { key: 'mismatch', className: 'scp-callout', style: { background: 'var(--scp-warn-soft)', borderColor: 'color-mix(in srgb, var(--scp-warn) 26%, var(--scp-border))' } },
              h('span', { className: 'scp-callout-label' }, tr('sediment.detail.source')),
              h('span', { className: 'scp-callout-text' }, tr(sedMismatchKey)),
              sedPick.writeback ? h('button', {
                type: 'button', className: 'scp-btn', style: { alignSelf: 'flex-start' },
                onClick: () => fillDraft(sedPick.writeback),
              }, tr('sediment.detail.writeback')) : null))
          }
          return h('div', {
            className: 'scp-pal-side scp-sed-side',
            style: { '--scp-tone': SED_DOT[sedPick.stageTone] || SED_DOT.gray },
          }, head.concat(blocks))
        })()

      const sedSide = view === 'sediment' ? sedSideInner : side

      // 提 PR / groom / 查状态 / 收尾的指令预览（诊断视图的批量沉淀共用这个弹层）
      const promptTitle = {
        groom: tr('sediment.primary.groom'),
        pr: tr('sediment.primary.pr'),
        check: tr('sediment.primary.check'),
        close: tr('sediment.primary.close'),
        sedimentBatch: tr('diag.batch.fill'),
        fallback: (promptFallback && promptFallback.head) || tr('sediment.prompt.fallbackTitle'),
      }
      const isBatchPrompt = promptKind === 'sedimentBatch' && !!batchSed
      const isFallbackPrompt = promptKind === 'fallback' && !!promptFallback
      const promptText = isBatchPrompt
        ? String(batchSed.text || '')
        : (isFallbackPrompt
          ? String(promptFallback.text || '')
          : (promptKind && sedDoc && sedDoc.prompts ? String(sedDoc.prompts[promptKind] || '') : ''))
      const promptDetail = isBatchPrompt || isFallbackPrompt
        ? ''
        : (promptKind && sedDoc && sedDoc.prompts ? String(sedDoc.prompts[promptKind + 'Detail'] || '') : '')
      const promptDecided = sedDrafts.filter((draft) => draft.state === 'decided')
      const promptModal = promptKind ? h('div', {
        className: 'scp-veil',
        onMouseDown: (event) => { if (event.target === event.currentTarget) closePrompt() },
      },
        h('div', { className: 'scp-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': promptTitle[promptKind] || promptKind, tabIndex: -1, ref: promptRef },
          h('div', { className: 'scp-modal-top' },
            h('div', { style: { flex: '1 1 auto', minWidth: 0 } },
              h('div', { className: 'scp-modal-title' }, promptTitle[promptKind] || promptKind),
              h('div', { className: 'scp-modal-sub' }, isBatchPrompt
                ? tr('diag.batch.sub', { n: batchSed.count || 0 })
                : (isFallbackPrompt
                  ? ((promptFallback && promptFallback.sub) || tr('sediment.fallback.sub'))
                  : (promptKind === 'pr' ? (sedTargetLabel || tr('sediment.noTarget')) : tr('sediment.prompt.sub'))))),
            h('button', { type: 'button', className: 'scp-icon', 'aria-label': tr('sediment.prompt.cancel'), onClick: closePrompt }, IconClose())),
          h('div', { className: 'scp-modal-body' },
            promptKind === 'pr'
              ? h('div', { className: 'scp-target-row' },
                h('span', { className: 'scp-target-label' }, tr('sediment.target')),
                h('span', { className: 'scp-target-pill' }, sedTargetLabel || tr('sediment.targetNone')),
                h('button', { type: 'button', className: 'scp-btn scp-btn--quiet', onClick: () => openTarget('pr') }, tr('sediment.targetChange')),
                h('span', { className: 'scp-target-hint' }, tr('sediment.targetHint')))
              : null,
            promptKind === 'pr' && promptDecided.length
              ? h('table', { className: 'scp-sed-table' },
                h('thead', {}, h('tr', {}, h('th', {}, tr('sediment.table.draft')), h('th', {}, tr('sediment.table.decision')), h('th', {}, tr('sediment.detail.promotion')))),
                h('tbody', {}, promptDecided.map((draft) => h('tr', { key: draft.key },
                  h('td', {}, draft.key),
                  h('td', {}, draft.decision || '-'),
                  h('td', {}, (draft.promotion && (draft.promotion.caseId || draft.promotion.casePath)) || '-')))))
              : null,
            isFallbackPrompt
              ? null
              : h('div', { className: 'scp-warn-list' },
                isBatchPrompt ? h('div', {}, tr('diag.batch.flow')) : h('div', {}, tr('sediment.prompt.flow')),
                isBatchPrompt ? h('div', {}, tr('diag.batch.boundary')) : h('div', {}, tr('sediment.prompt.boundary'))),
            promptText
              ? h('div', { className: 'scp-prompt' }, promptText)
              : h('div', { className: 'scp-sed-hint' }, tr('sediment.prompt.empty')),
            promptText && !isBatchPrompt && !isFallbackPrompt
              ? h('div', { className: 'scp-prompt-cap' }, tr('sediment.prompt.default')) : null,
            promptDetail
              ? h('button', { type: 'button', className: 'scp-details-toggle', onClick: () => setPromptDetailsOpen((value) => !value) },
                promptDetailsOpen ? tr('sediment.prompt.collapse') : tr('sediment.prompt.details'))
              : null,
            promptDetail && promptDetailsOpen ? h('div', { className: 'scp-prompt' }, promptDetail) : null),
          h('div', { className: 'scp-modal-foot' },
            h('span', { className: 'scp-spacer' }),
            h('button', { type: 'button', className: 'scp-btn scp-btn--ghost', onClick: closePrompt }, tr('sediment.prompt.cancel')),
            h('button', {
              type: 'button', className: 'scp-btn', disabled: !promptText,
              onClick: () => copyAndFlash(promptText),
            }, tr('sediment.prompt.copy')),
            h('button', {
              type: 'button', className: 'scp-btn scp-btn--primary', disabled: !promptText,
              onClick: () => { if (promptText) { closePrompt(); fillDraft(promptText) } },
            }, tr('sediment.prompt.fill'))))) : null

      // 目标选择（第一次提 PR 时出现）
      const remotes = sedRemotes
      const targetModal = targetOpen ? h('div', {
        className: 'scp-veil',
        onMouseDown: (event) => { if (event.target === event.currentTarget) closeTarget() },
      },
        h('div', { className: 'scp-modal', style: { width: 'min(640px, calc(100% - 40px))' }, role: 'dialog', 'aria-modal': 'true', 'aria-label': tr('sediment.target.title'), tabIndex: -1, ref: targetRef },
          h('div', { className: 'scp-modal-top' },
            h('div', { style: { flex: '1 1 auto', minWidth: 0 } },
              h('div', { className: 'scp-modal-title' }, tr('sediment.target.title')),
              h('div', { className: 'scp-modal-sub' }, tr('sediment.target.sub'))),
            h('button', { type: 'button', className: 'scp-icon', 'aria-label': tr('sediment.prompt.cancel'), onClick: () => closeTarget() }, IconClose())),
          h('div', { className: 'scp-modal-body' },
            remotes.length === 0
              ? h('div', { className: 'scp-pal-empty' }, tr('sediment.target.empty'))
              : h('div', { className: 'scp-pick-list' }, remotes.map((item) => {
                const name = String(item.name || '')
                const platform = String(item.platform_name || item.platformName || item.platform || '')
                const hasAdapter = item.has_adapter !== false && Boolean(item.platform || platform)
                const tokenReady = item.token_ready !== false
                return h('button', {
                  key: name,
                  type: 'button',
                  className: 'scp-pick',
                  'data-on': targetRemote === name ? 'true' : 'false',
                  onClick: () => {
                    setTargetRemote(name)
                    if (item.base) setTargetBase(String(item.base))
                  },
                },
                  h('span', { className: 'scp-radio', 'aria-hidden': 'true' }),
                  h('span', { style: { flex: '1 1 auto', minWidth: 0 } },
                    h('span', { className: 'scp-pick-title' },
                      name,
                      hasAdapter
                        ? h('span', { className: 'scp-chip', 'data-tone': 'brand' }, platform || tr('sediment.target.noAdapter'))
                        : h('span', { className: 'scp-chip' }, tr('sediment.target.noAdapter')),
                      hasAdapter && !tokenReady ? h('span', { className: 'scp-chip', 'data-tone': 'warn' }, tr('sediment.target.token')) : null),
                    h('span', { className: 'scp-pick-sub' }, [item.url, item.base, item.last_used, item.note].filter(Boolean).join(' · '))))
              })),
            remotes.length > 1 && !targetRemote
              ? h('div', { className: 'scp-sed-hint' }, tr('sediment.target.pick'))
              : null,
            h('div', { className: 'scp-target-row' },
              h('span', { className: 'scp-target-label' }, tr('sediment.target.base')),
              h('input', {
                className: 'scp-input', style: { width: '180px' }, type: 'text',
                value: targetBase, onChange: (event) => setTargetBase(event.target.value),
              }),
              h('span', { className: 'scp-target-hint' }, tr('sediment.targetNote')))),
          h('div', { className: 'scp-modal-foot' },
            h('span', { className: 'scp-sed-hint' }, tr('sediment.targetNote')),
            h('span', { className: 'scp-spacer' }),
            h('button', { type: 'button', className: 'scp-btn scp-btn--ghost', onClick: () => closeTarget() }, tr('sediment.prompt.cancel')),
            h('button', {
              type: 'button', className: 'scp-btn scp-btn--primary',
              disabled: !targetRemote || targetBusy || !canWrite,
              title: canWrite ? undefined : writeDisabledReason(s.data),
              onClick: saveTarget,
            }, targetBusy ? tr('sediment.refreshing') : tr('sediment.target.save'))))) : null

      // 人工兜底：平台一直查不到时，按人确认把 PR 状态写进本地台账（source=manual）。
      const manualModal = manualOpen && sedPick ? h('div', {
        className: 'scp-veil',
        onMouseDown: (event) => { if (event.target === event.currentTarget) setManualOpen(false) },
      },
        h('div', {
          className: 'scp-modal', style: { width: 'min(520px, calc(100% - 40px))' },
          role: 'dialog', 'aria-modal': 'true', 'aria-label': tr('sediment.manualTitle'), tabIndex: -1,
        },
          h('div', { className: 'scp-modal-top' },
            h('div', { style: { flex: '1 1 auto', minWidth: 0 } },
              h('div', { className: 'scp-modal-title' }, tr('sediment.manualTitle')),
              h('div', { className: 'scp-modal-sub' }, tr('sediment.manualSub'))),
            h('button', {
              type: 'button', className: 'scp-icon', 'aria-label': tr('sediment.prompt.cancel'),
              onClick: () => setManualOpen(false),
            }, IconClose())),
          h('div', { className: 'scp-modal-body' },
            h('div', { className: 'scp-sed-hint' },
              (sedPick.pr && sedPick.pr.number ? '#' + sedPick.pr.number + ' · ' : '') + String(sedPick.key || '')),
            h('div', { className: 'scp-pick-list' }, PR_STATE_KEYS.map((state) => h('button', {
              key: state,
              type: 'button',
              className: 'scp-pick',
              'data-on': ((sedPick.pr && sedPick.pr.state) || 'unknown') === state ? 'true' : 'false',
              disabled: checkBusy === sedPick.key || checkBusy === '__all__' || !canWrite,
              onClick: () => markState(sedPick.key, state),
            },
              h('span', { className: 'scp-radio', 'aria-hidden': 'true' }),
              h('span', { style: { flex: '1 1 auto', minWidth: 0 } },
                h('span', { className: 'scp-pick-title' }, tr('sediment.prState.' + state))))))),
          h('div', { className: 'scp-modal-foot' },
            h('span', { className: 'scp-spacer' }),
            h('button', {
              type: 'button', className: 'scp-btn scp-btn--ghost',
              onClick: () => setManualOpen(false),
            }, tr('sediment.prompt.cancel'))))) : null

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
              h('span', { className: 'scp-pal-title' }, view === 'sediment' ? tr('palette.sedimentTitle') : tr('palette.title')),
              h('span', { className: 'scp-pal-sub' }, view === 'sediment'
                ? [tr('sediment.batch.total', { n: sedDrafts.length }), sedTargetHint].join(' · ')
                : subParts.join(' · '))),
            h('div', { className: 'scp-views', role: 'tablist', 'aria-label': tr('palette.title') },
              h('button', {
                type: 'button', role: 'tab',
                className: 'scp-view-tab',
                'aria-selected': view === 'diagnosis' ? 'true' : 'false',
                'data-on': view === 'diagnosis' ? 'true' : 'false',
                onClick: () => setPaletteView('diagnosis'),
              }, tr('palette.view.diagnosis'), h('b', {}, String(rows.length))),
              h('button', {
                type: 'button', role: 'tab',
                className: 'scp-view-tab',
                'aria-selected': view === 'sediment' ? 'true' : 'false',
                'data-on': view === 'sediment' ? 'true' : 'false',
                onClick: () => setPaletteView('sediment'),
              }, tr('palette.view.sediment'), h('b', {}, String(sedDrafts.length)))),
            h('button', {
              type: 'button', className: 'scp-icon', 'aria-label': tr('palette.close'), title: tr('palette.close'),
              onClick: () => setPaletteOpen(false),
            }, IconClose())),
          s.stale ? h('div', { className: 'scp-pal-notice', role: 'status', title: s.staleMessage || '' },
            tr('hint.stale')) : null,
          loadFailed ? h('div', { className: 'scp-pal-error' },
            h('div', { className: 'scp-pal-error-title' }, tr('palette.unavailable', { message: (s.data && s.data.message) || s.message || '' })),
            h('button', { type: 'button', className: 'scp-btn', onClick: () => refresh(true) }, tr('action.retry'))) : null,
          loadFailed ? null : sedBatch,
          loadFailed ? null : diagBatch,
          loadFailed ? null : h('div', { className: 'scp-pal-main' }, view === 'sediment' ? sedList : list, view === 'sediment' ? sedSide : side),
          h('div', { className: 'scp-pal-foot' },
            h('span', { className: 'scp-foot-hints' },
              h('span', { className: 'scp-kbd' }, '↑'),
              h('span', { className: 'scp-kbd' }, '↓'),
              ' 选择 · ',
              h('span', { className: 'scp-kbd' }, 'Enter'),
              ' 主操作 · ',
              h('span', { className: 'scp-kbd' }, '/'),
              ' 搜索 · ',
              view === 'diagnosis' ? h('span', { className: 'scp-kbd' }, shortcutKeys('command')) : null,
              view === 'diagnosis' ? ' 命令 · ' : null,
              h('span', { className: 'scp-kbd' }, 'Esc'),
              ' 关闭'),
            h('span', { className: 'scp-spacer' }),
            h('span', { className: 'scp-foot-note' }, view === 'sediment'
              ? sedTargetHint
              : [
                tr('queue.open', { n: Number(counts.open) || 0 }),
                tr('queue.pending', { n: Number(counts.pendingFeedback) || 0 }),
                tr('queue.sediment', { n: Number(counts.toSediment) || 0 }),
              ].join(' · ')),
            h('span', { className: 'scp-version' }, 'v' + PLUGIN_VERSION)),
          promptModal,
          targetModal,
          manualModal,
          cmdOpen ? h('div', {
            className: 'scp-cmd-backdrop',
            onMouseDown: (event) => { if (event.target === event.currentTarget) setCmdOpen(false) },
          },
            h('div', { className: 'scp-cmd', role: 'dialog', 'aria-modal': 'true', 'aria-label': tr('cmd.placeholder') },
              h('input', {
                ref: cmdInputRef, value: cmdQuery, placeholder: tr('cmd.placeholder'),
                role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'scp-cmd-list',
                'aria-activedescendant': 'scp-cmd-' + cmdIndex,
                'aria-label': tr('cmd.placeholder'),
                onChange: (event) => { setCmdQuery(event.target.value); setCmdIndex(0) },
              }),
              h('div', { className: 'scp-cmd-list', role: 'listbox', id: 'scp-cmd-list' },
                commandList.length
                  ? commandList.map((item, index) => h('button', {
                    key: 'cmd-' + index, type: 'button', className: 'scp-cmd-item',
                    role: 'option', id: 'scp-cmd-' + index,
                    'aria-selected': index === cmdIndex ? 'true' : 'false',
                    'data-on': index === cmdIndex ? 'true' : 'false',
                    onMouseEnter: () => setCmdIndex(index),
                    onClick: () => { setCmdOpen(false); item.run() },
                  }, item.label))
                  : h('div', { className: 'scp-cmd-empty' }, tr('cmd.empty'))),
              h('div', { className: 'scp-pal-foot' }, h('span', {}, tr('cmd.hint'))))) : null,
          toast ? h('span', { className: 'scp-toast', role: 'status', title: toast }, toast) : null))
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
      // 「切到该诊断的会话」必须有 sessions；uiWorkspace 只是后备，继续用 ctx.get 探测——
      // 声明一个旧发行版没有的服务会让整条状态条一直等它，代价高于收益。
      inject: ['connection', 'slots', 'sessions'],
      apply(ctx) {
        const slots = ctx.get('slots')
        if (slots === undefined) return
        rpcCall = makeRpc(ctx)
        openSessionImpl = makeOpenSession(ctx)
        ctx.effect(() => registerLocale(ctx), 'sleuth-copilot: locale')
        ctx.effect(() => stopTimer, 'sleuth-copilot: poll timer')
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
