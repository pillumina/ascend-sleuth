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

    // 核对时刻：当天只给 HH:MM，隔天带日期——提示行放不下完整时间。
    function shortClock(iso) {
      if (!iso) return ''
      const date = new Date(iso)
      if (Number.isNaN(date.getTime())) return String(iso)
      const pad = (n) => String(n).padStart(2, '0')
      const now = new Date()
      const sameDay = date.getFullYear() === now.getFullYear()
        && date.getMonth() === now.getMonth() && date.getDate() === now.getDate()
      const clock = pad(date.getHours()) + ':' + pad(date.getMinutes())
      return sameDay ? clock : pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + clock
    }

    function stepsText(extra) {
      const current = Number(extra && extra.currentStep) || 0
      const max = Number(extra && extra.maxSteps) || 6
      // 超过诊断流程的步数（续接、报告修订会把步号继续往上记）：分母不再表示进度，只报步号。
      if (current > max) return tr('stepsOver', { n: current })
      return tr('steps', { n: current > 0 ? current : '—', m: max })
    }

    function stepsShort(extra) {
      const current = Number(extra && extra.currentStep) || 0
      const max = Number(extra && extra.maxSteps) || 6
      if (current > max) return tr('stepsOver', { n: current })
      return tr('stepsShort', { n: current > 0 ? current : '—', m: max })
    }

    // 现场时间线的时间写到材料给到的那一级：日期必有、时刻可能缺。解析不出就是 null，
    // 由调用方渲染成「时点未知」；不换算时区、不补精度。
    function stampParts(at) {
      if (!at) return null
      const match = /^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?/.exec(String(at))
      if (!match) return null
      return { date: match[1], time: match[2] || '' }
    }

    function stampText(at) {
      const parts = stampParts(at)
      if (!parts) return tr('incident.unknown')
      return parts.time ? parts.date + ' ' + parts.time : parts.date
    }

    // 证据按钮只写文件名（+ 行号），完整路径进 title 与剪贴板；长路径不撑开一行。
    function fileLabel(path) {
      const text = String(path || '')
      const parts = text.split('/')
      return parts[parts.length - 1] || text
    }

    function fileLineLabel(path, line) {
      const label = fileLabel(path)
      return line ? label + ':' + line : label
    }

    function timelineSourceLabel(source) {
      const value = String(source || '')
      if (!value) return ''
      const key = 'timelineSource.' + value
      const label = tr(key)
      return label === key ? value : label
    }

    function revisionKindLabel(kind) {
      const value = String(kind || '')
      if (!value) return ''
      const key = 'revision.kind.' + value
      const label = tr(key)
      return label === key ? value : label
    }

    function revisionTargetLabel(target) {
      const value = String(target || '')
      if (value.indexOf('removed:') === 0) return tr('revision.removed', { id: value.slice(8) })
      return value
    }

    // 修订行正文：每条 change 写「目标：旧值 → 新值」；删除条目没有新值，只写旧值。
    function revisionText(revision) {
      const changes = revision && Array.isArray(revision.changes) ? revision.changes : []
      return changes.map((change) => {
        const target = revisionTargetLabel(change && change.target)
        const before = String((change && change.before) || '') || tr('label.none')
        const removed = String((change && change.target) || '').indexOf('removed:') === 0
        if (removed) return target + '：' + before
        const after = String((change && change.after) || '') || tr('label.none')
        return target + '：' + before + ' → ' + after
      }).join('；')
    }

    // 选中行的三段时间线 + 修订（copilot-timeline 的 layers）：null 与缺键都按「未记录」，
    // [] 才是「查过但为空」；*Total 是截断前的条数，段头用它并写明「显示前 N 条」。
    function normalizeTimelineLayers(value) {
      const doc = value && typeof value === 'object' ? value : {}
      const listOrNull = (item) => {
        if (item === null || item === undefined) return null
        return Array.isArray(item) ? item : null
      }
      const countOf = (item, total) => {
        const number = Number(total)
        if (Number.isFinite(number) && number >= 0) return number
        return Array.isArray(item) ? item.length : 0
      }
      return {
        incidentEnv: String(doc.incidentEnv || ''),
        incident: listOrNull(doc.incident),
        incidentTotal: countOf(doc.incident, doc.incidentTotal),
        failureProcess: doc.failureProcess && typeof doc.failureProcess === 'object' ? doc.failureProcess : null,
        upstream: listOrNull(doc.upstream),
        upstreamTotal: countOf(doc.upstream, doc.upstreamTotal),
        revisions: Array.isArray(doc.revisions) ? doc.revisions : [],
        revisionsTotal: countOf(doc.revisions, doc.revisionsTotal),
      }
    }

    // 案例标题：状态条与总览显示给人看的一句话；单号只进 tooltip 与详情。
    // 案例标题：状态条与工作台显示给人看的一句话；单号只进 tooltip 与详情。
    // 取 summary 第一句（到第一个句读），截断交给 CSS——不手写省略号，也不把内部单号当标题。
    function caseTitle(row) {
      const summary = String((row && row.summary) || '').trim()
      if (summary) {
        const first = summary.split(/[。；;!?！？\n]/)[0].trim()
        // trace 的 summary 常以「现象：」这类字段名开头；它是数据里的标签，不是标题的一部分。
        const unlabeled = first.replace(/^(现网现象|现象|问题|背景|症状)\s*[：:]\s*/, '').trim()
        if (unlabeled) return unlabeled
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
    function identityChips(row, onSample) {
      const derived = (row && row.derived) || {}
      const extra = (row && row.extra) || {}
      const chips = []
      if (row && row.activeCase) chips.push({ key: 'hit', tone: 'brand', text: tr('chip.hit', { id: row.activeCase }) })
      else if (derived.caseKind === 'none') chips.push({ key: 'miss', tone: 'idle', text: tr('chip.miss') })
      const sample = extra.sample || (row && row.sample)
      if (sample && sample.state) {
        const tone = sample.state === 'ready' ? 'brand'
          : sample.state === 'absorbed' ? 'idle' : 'warn'
        chips.push({
          key: 'sample', tone, text: tr('chip.sample.' + sample.state),
          title: [sample.id, ...(sample.reasons || []), ...(sample.duplicates || [])].filter(Boolean).join(' · '),
          onSelect: onSample ? () => onSample(sample) : undefined,
        })
      }
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
      if (extra.sample && extra.sample.state) {
        const sample = extra.sample
        const tone = sample.state === 'ready' ? 'brand'
          : sample.state === 'absorbed' ? 'idle' : 'warn'
        chips.push({
          key: 'sample', tone, text: tr('chip.sample.' + sample.state),
          title: [sample.id, ...(sample.reasons || []), ...(sample.duplicates || [])].filter(Boolean).join(' · '),
        })
      }
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

    function sampleDraft(row) {
      return '用 /eval-ingest 从 ' + traceSource(row) + ' 生成候选评测样本，'
        + '先跑 sample new --from trace --dry-run --json 看状态与查重；'
        + '不要自动 active，等我确认根因与修复。'
    }

    function sampleBatchDraft(rows) {
      const list = (rows || []).filter((item) => item && item.file)
      const lines = list.map((item) => '- ' + traceSource(item)
        + '（' + String(item.sessionId || '') + '）').join('\n')
      return '用 /eval-ingest 批量从以下已闭环 trace 生成候选评测样本：\n' + lines + '\n'
        + '逐条先跑 sample new --from trace --dry-run --json；汇总完整性与查重后给我确认；'
        + '不要自动 active，等我确认根因与修复。'
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

    // 批量沉淀：未选时范围是当前筛选；已选时范围是选择集。
    // 名单以界面为准；分组与「还有哪些单」先问只读脚本，避免面板投影与脚本判据不一致时漏单或重复起草。
    function sedimentBatchDraft(rows, meta) {
      const ids = (rows || []).map((row) => row && row.sessionId).filter(Boolean)
      if (!ids.length) return ''
      const options = meta || {}
      const bySelection = options.selection === true
      const query = String(options.query || '').trim()
      const scope = query ? '（含搜索词「' + query + '」）' : ''
      const total = Number(options.total) || ids.length
      const totalText = query && total > ids.length ? '；该筛选全量 ' + total + ' 单' : ''
      const scopeText = bySelection
        ? '范围 = 诊断工作台所选的 ' + ids.length + ' 单'
        : '范围 = 诊断工作台「可沉淀」筛选当前列出的 ' + ids.length + ' 单' + scope + totalText
      return '用 /to-postmortem 批量沉淀这些 session：' + ids.join('、') + '\n'
        + scopeText + '；trace 在 traces/<session>.yaml。\n'
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

    // 写入历史：transitions / reports / reviews / revisions 合成一条时间线，只展示最近几条。
    function historyEntries(row, data, revisions) {
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
      // 修订记录：类别、before → after、改的原因都在一行里；正文走 revisionText。
      const revisionList = Array.isArray(revisions) ? revisions : []
      for (const item of revisionList) {
        if (!item || typeof item !== 'object') continue
        entries.push({
          kind: 'revision',
          // 类别列写修订的种类（事实更正 / 结论翻转 …），不回落到笼统的「修订」。
          label: revisionKindLabel(item.kind) || tr('history.revision'),
          at: String(item.at || ''),
          text: revisionText(item),
          note: String(item.reason || ''),
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

