// 页面数据映射：trace 事件 → 画布图（columns/nodes/edges）+ 检查器分区 + 页头统计。
//
// 这一层只有纯函数，不碰 DOM、不碰 React；颜色给的是亮色基准，页面用
// SC.theme.currentPalette().tones 覆盖（暗色提亮由主题模块做）。分类表见 docs/DESIGN.md §3。

SC.model = (function () {
  const U = SC.util

  // DESIGN §2.2 亮色基准。页面会以 palette.tones 的同名键覆盖。
  const TONES = {
    intake: '#D9902F',
    route: '#4A7DFF',
    index: '#2AA7B8',
    check: '#8A6CF0',
    book: '#3C9A78',
    code: '#E07A3F',
    hit: '#3FA46A',
    miss: '#6E7C93',
    flag: '#C9A227',
    feedback: '#7C8698',
    warn: '#D9822B',
    risk: '#D65454',
  }

  // 家族名：图例与列标签用中文，action 名保留原值。
  const TONE_LABELS = {
    intake: '现场',
    route: '分诊',
    index: '检索',
    check: '核验',
    book: '先验',
    code: '源码',
    hit: '命中',
    miss: '未覆盖',
    flag: '归因',
    feedback: '收尾',
    warn: '警示',
    risk: '风险',
  }

  // DESIGN §3 动作分类表。`intake` 是 user 事件（action 为 null）的伪动作，
  // `unknown` 是任何未登记 action 的兜底（家族 feedback / glyph dot / 标题取原值）。
  const ACTIONS = {
    intake: { family: 'intake', tone: 'intake', glyph: 'intake', label: '现场', emphasis: 'normal' },
    triage: { family: 'route', tone: 'route', glyph: 'route', label: '分诊', emphasis: 'normal' },
    triage_semantic: { family: 'route', tone: 'route', glyph: 'route', label: '语义分诊', emphasis: 'normal' },
    load_index: { family: 'index', tone: 'index', glyph: 'index', label: '检索', emphasis: 'normal' },
    quickly_check: { family: 'check', tone: 'check', glyph: 'check', label: '核验', emphasis: 'normal' },
    tier3: { family: 'check', tone: 'check', glyph: 'cross', label: 'Tier 3', emphasis: 'normal' },
    reference_lookup: { family: 'book', tone: 'book', glyph: 'book', label: '查先验', emphasis: 'normal' },
    source_analysis: { family: 'code', tone: 'code', glyph: 'code', label: '源码分析', emphasis: 'normal' },
    hit: { family: 'hit', tone: 'hit', glyph: 'hit', label: '命中', emphasis: 'conclusion' },
    miss: { family: 'miss', tone: 'miss', glyph: 'miss', label: '未覆盖', emphasis: 'conclusion' },
    attribution: { family: 'flag', tone: 'flag', glyph: 'flag', label: '归因', emphasis: 'normal' },
    output: { family: 'flag', tone: 'flag', glyph: 'doc', label: '输出结论', emphasis: 'conclusion' },
    resume: { family: 'feedback', tone: 'feedback', glyph: 'loop', label: '续接', emphasis: 'normal' },
    report: { family: 'feedback', tone: 'feedback', glyph: 'doc', label: '报告', emphasis: 'normal' },
    feedback: { family: 'feedback', tone: 'feedback', glyph: 'feedback', label: '回报', emphasis: 'normal' },
    unknown: { family: 'feedback', tone: 'feedback', glyph: 'dot', label: '动作', emphasis: 'normal' },
  }

  // 每条 action 的 meta 第二段（“step N · 这里”）。
  const VERBS = {
    intake: '用户',
    triage: '分诊',
    triage_semantic: '语义分诊',
    load_index: '检索',
    quickly_check: '核验',
    tier3: 'Tier 3',
    reference_lookup: '先验查照',
    source_analysis: '源码',
    hit: '命中',
    miss: '未覆盖',
    attribution: '归因',
    output: '结论',
    resume: '续接',
    report: '报告',
    feedback: '回报',
    unknown: '事件',
  }

  // 已经被节点三元组/分区消费掉的 fields 键，不让它们再在“其余字段”里重复出现。
  const CONSUMED_FIELDS = {
    branch: 1, category: 1, routed: 1, namespace: 1, namespaces: 1, rationale: 1,
    n_cases: 1, n_candidates_selected: 1, reference: 1, layer: 1, selected_step: 1,
    component: 1, repo: 1, ref: 1, files: 1, files_read: 1, followup: 1, level: 1,
    outcome: 1, shard: 1, platform: 1, ref_id: 1,
  }

  function text(value) {
    return value === null || value === undefined ? '' : String(value)
  }

  function arr(value) {
    if (Array.isArray(value)) return value
    if (value === null || value === undefined || value === '') return []
    return [value]
  }

  function isNum(value) {
    return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
  }

  function eventChars(ev) {
    if (!ev) return 0
    const chars = ev.chars || {}
    const total = Number(chars.output || 0) + Number(chars.reason || 0) + Number(chars.content || 0)
    if (total > 0) return total
    return text(ev.output).length + text(ev.reason).length + text(ev.content).length
  }

  function charLabel(count) {
    const n = Math.max(0, Math.round(Number(count) || 0))
    if (n >= 10000) return U.compactNumber(n) + '字符'
    return U.formatNumber(n) + ' 字'
  }

  function shorten(value, max) {
    return U.truncate(text(value).replace(/\s+/g, ' ').trim(), max)
  }

  function firstLineOf(ev, max) {
    return U.firstSentence(text(ev && ev.output) || text(ev && ev.content) || text(ev && ev.reason), max)
  }

  // 把 action 解析成分类表条目；action 为 null 且 role=user 视为现场输入。
  function resolve(action, role) {
    if (action === null || action === undefined || action === '') {
      if (role === 'user') return { key: 'intake', entry: ACTIONS.intake }
      return { key: 'unknown', entry: ACTIONS.unknown }
    }
    const key = String(action)
    if (Object.prototype.hasOwnProperty.call(ACTIONS, key) && key !== 'unknown') {
      return { key: key, entry: ACTIONS[key] }
    }
    return { key: key, entry: ACTIONS.unknown }
  }

  function roleLabel(ev) {
    if (!ev) return ''
    if (ev.role === 'user') return '用户'
    if (ev.role === 'agent') return '分析'
    return text(ev.role)
  }

  function badge(label, tone) {
    return { text: text(label), tone: tone || 'neutral' }
  }

  function valuesOf(list) {
    return arr(list).map(text).filter(Boolean)
  }

  // 节点三元组 + badges：DESIGN §3 的每一行。
  function describeEvent(ev, detail) {
    const resolved = resolve(ev && ev.action, ev && ev.role)
    const entry = resolved.entry
    const fields = (ev && ev.fields) || {}
    const step = ev && ev.step !== null && ev.step !== undefined ? ev.step : '?'
    const verb = VERBS[resolved.key] || '事件'
    const badges = []
    let title = ''
    let subtitle = ''
    let meta = 'step ' + step + ' · ' + verb

    switch (resolved.key) {
      case 'intake': {
        title = '现场输入'
        subtitle = U.firstSentence(text(ev && ev.content), 60)
        meta = 'step ' + step + ' · 用户'
        const evidence = (ev && ev.evidence) || {}
        const inlineChars = Number(evidence.inlineChars || 0) || text(evidence.inline).length
        const bodyChars = inlineChars || Number((ev && ev.chars && ev.chars.content) || 0)
        if (bodyChars > 0) badges.push(badge('证据 ' + charLabel(bodyChars), 'neutral'))
        if (valuesOf(evidence.files).length) badges.push(badge(valuesOf(evidence.files).length + ' 文件', 'neutral'))
        if (valuesOf(evidence.sources).length) badges.push(badge(valuesOf(evidence.sources).length + ' 链接', 'neutral'))
        break
      }
      case 'triage': {
        const branch = text(fields.branch)
        title = branch ? '分诊 → ' + branch : '分诊'
        subtitle = text(fields.category) || firstLineOf(ev, 64)
        const routed = valuesOf(fields.routed)
        meta = 'step ' + step + (routed.length ? ' · 路由 ' + routed.join('、') : ' · 分诊')
        break
      }
      case 'triage_semantic': {
        const namespace = text(fields.namespace) || valuesOf(fields.namespaces)[0] || ''
        title = namespace ? '语义分诊 → ' + namespace : '语义分诊'
        subtitle = U.firstSentence(text(fields.rationale) || text(ev.output) || text(ev.reason), 64)
        meta = 'step ' + step + ' · 语义分诊'
        break
      }
      case 'load_index': {
        title = '检索候选'
        const nCases = text(fields.n_cases)
        const namespaces = valuesOf(fields.namespaces).join('、')
        const parts = []
        if (nCases) parts.push(nCases + ' 条 case')
        if (namespaces) parts.push(namespaces)
        subtitle = parts.length ? parts.join(' · ') : U.firstSentence(text(ev.reason), 64)
        meta = 'step ' + step + ' · 检索'
        if (isNum(fields.n_candidates_selected)) {
          badges.push(badge(Number(fields.n_candidates_selected) + ' 候选', 'neutral'))
        }
        break
      }
      case 'quickly_check': {
        const caseId = text(ev && ev.case) || text(fields.case)
        title = caseId ? '核验 ' + caseId : '核验候选'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 核验'
        const verdict = (ev && ev.verdict) || {}
        if (text(verdict.primary)) {
          badges.push(badge('primary ' + text(verdict.primary), verdict.primary === 'pass' ? 'hit' : verdict.primary === 'fail' ? 'miss' : 'warn'))
        }
        if (text(verdict.fallback)) {
          badges.push(badge('fallback ' + text(verdict.fallback), verdict.fallback === 'pass' ? 'hit' : verdict.fallback === 'fail' ? 'miss' : 'warn'))
        }
        if (text(verdict.marked)) badges.push(badge('marked ' + text(verdict.marked), 'warn'))
        break
      }
      case 'tier3': {
        title = '深度回退'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · Tier 3'
        break
      }
      case 'reference_lookup': {
        title = '查先验'
        const reference = text(fields.reference)
        subtitle = [text(ev && ev.purpose), reference].filter(Boolean).join(' · ') || firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 先验查照'
        if (isNum(fields.layer)) badges.push(badge('第 ' + text(fields.layer) + ' 层', 'neutral'))
        break
      }
      case 'source_analysis': {
        title = '源码分析'
        const repo = text(fields.repo)
        const ref = text(fields.ref)
        const files = valuesOf(fields.files).length || valuesOf(fields.files_read).length
        const head = [repo, ref].filter(Boolean).join('@')
        const parts = []
        if (head) parts.push(head)
        if (files) parts.push(files + ' 个文件')
        subtitle = parts.length ? parts.join(' · ') : firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 源码'
        const tools = valuesOf(ev && ev.toolCalls).length
        if (tools) badges.push(badge(tools + ' 次工具调用', 'neutral'))
        break
      }
      case 'hit': {
        const caseId = text(ev && ev.case) || text(fields.case)
        title = caseId ? '命中 ' + caseId : '命中 case'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 命中'
        const confidence = text((ev && ev.verdict && ev.verdict.confidence) || fields.confidence)
        if (confidence) badges.push(badge('置信 ' + confidence, 'hit'))
        break
      }
      case 'miss': {
        title = '知识库未覆盖'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 未覆盖'
        const excluded = (detail && detail.excludedCases) || []
        if (excluded.length) badges.push(badge('排除 ' + excluded.length + ' 个候选', 'miss'))
        break
      }
      case 'attribution': {
        const component = text(fields.component)
        title = component ? '归因 · ' + component : '归因'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 归因'
        const verdictValue = text((ev && ev.verdict && ev.verdict.verdict) || fields.verdict)
        if (verdictValue) badges.push(badge(verdictValue, 'warn'))
        break
      }
      case 'output': {
        title = '给出结论'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 结论'
        break
      }
      case 'resume': {
        title = '续接诊断'
        subtitle = firstLineOf(ev, 64) || '从这里继续'
        meta = 'step ' + step + ' · 续接'
        break
      }
      case 'report': {
        title = '写报告'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 报告'
        break
      }
      case 'feedback': {
        const outcome = text(fields.outcome) || text(detail && detail.feedback && detail.feedback.outcome)
        title = outcome ? '回报结果 · ' + outcome : '回报结果'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · 回报'
        if ((ev && ev.case) || (detail && detail.feedback && detail.feedback.case)) {
          badges.push(badge(text(ev && ev.case) || text(detail.feedback.case), 'hit'))
        }
        break
      }
      default: {
        title = shorten(ev && ev.action, 18) || '未标注动作'
        subtitle = firstLineOf(ev, 64)
        meta = 'step ' + step + ' · ' + shorten(ev && ev.action, 12)
        break
      }
    }

    return {
      key: resolved.key,
      family: entry.family,
      tone: entry.tone,
      glyph: entry.glyph,
      label: entry.label,
      emphasis: entry.emphasis,
      title: title,
      subtitle: subtitle,
      meta: meta,
      badges: badges,
      roleLabel: roleLabel(ev),
    }
  }

  function stepOf(ev, fallback) {
    if (!ev) return fallback
    if (ev.step === null || ev.step === undefined || ev.step === '') return fallback
    return ev.step
  }

  // detail → graph。columns 按 step 首次出现顺序；nodes 保持事件顺序；edges 为时间主链
  // （同列相邻节点也走这条链，引擎据 node.col 判断画竖向导引）。
  function buildGraph(detail, opts) {
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    const tones = (opts && opts.tones) || TONES
    const columns = []
    const nodes = []
    const edges = []
    const byStep = Object.create(null)
    let lastStep = null
    // host 的 conclusionIndex 是事件 idx；这里换算成数组位置，节点/选中都用位置作身份。
    let conclusionPos = null
    if (detail && detail.conclusionIndex !== null && detail.conclusionIndex !== undefined) {
      const at = events.findIndex(function (ev) { return ev && ev.idx === detail.conclusionIndex })
      conclusionPos = at >= 0 ? at : null
    }

    for (let i = 0; i < events.length; i += 1) {
      const ev = events[i] || {}
      const step = stepOf(ev, lastStep === null ? 1 : lastStep)
      lastStep = step
      let column = byStep[step]
      if (!column) {
        column = { col: columns.length, step: step, label: '', count: 0, accent: tones.intake, parallel: false, firstIdx: i }
        byStep[step] = column
        columns.push(column)
      }
      const described = describeEvent(ev, detail)
      const accent = tones[described.tone] || TONES[described.tone] || TONES.feedback
      const emphasis = described.emphasis === 'conclusion' || conclusionPos === i ? 'conclusion' : 'normal'
      if (!column.label) {
        column.label = described.label || TONE_LABELS[described.tone] || ''
        column.accent = accent
      }
      column.count += 1
      column.parallel = column.count > 1
      nodes.push({
        idx: i,
        col: column.col,
        lane: column.count - 1,
        role: text(ev.role),
        accent: accent,
        tone: described.tone,
        family: described.family,
        glyph: described.glyph,
        label: described.label,
        step: step,
        title: described.title,
        subtitle: described.subtitle,
        meta: described.meta,
        badges: described.badges,
        emphasis: emphasis,
      })
      if (i > 0) {
        edges.push({ from: i - 1, to: i, kind: 'main' })
      }
    }

    return {
      columns: columns,
      nodes: nodes,
      edges: edges,
      meta: {
        stepCount: columns.length,
        eventCount: nodes.length,
        conclusionIndex: conclusionPos,
      },
    }
  }

  // 把亮色基准换成当前主题色（暗色由主题模块提亮）。
  function applyTones(graph, tones) {
    if (!graph || !tones) return graph
    const columns = graph.columns.map(function (column) {
      return Object.assign({}, column, { accent: tones[columnTone(column, graph)] || column.accent })
    })
    const nodes = graph.nodes.map(function (node) {
      return Object.assign({}, node, { accent: tones[node.tone] || node.accent })
    })
    return Object.assign({}, graph, { columns: columns, nodes: nodes })
  }

  // 列 accent 取该列第一个节点的家族。
  function columnTone(column, graph) {
    const node = graph.nodes.find(function (item) { return item.col === column.col })
    return node ? node.tone : 'feedback'
  }

  function verdictEntries(verdict) {
    const labels = {
      primary: '主检查',
      fallback: '备用检查',
      marked: '标记',
      result: '结果',
      confidence: '置信度',
      check: '判据',
      verdict: '判决',
    }
    const entries = []
    for (const key of ['check', 'primary', 'fallback', 'marked', 'result', 'confidence', 'verdict']) {
      const value = verdict && verdict[key]
      if (value === null || value === undefined || value === '') continue
      entries.push({ key: key, label: labels[key], value: text(value), tone: key === 'marked' && String(value) !== 'excluded' ? 'warn' : 'neutral' })
    }
    return entries
  }

  function formatFieldValue(value) {
    if (value === null || value === undefined) return '—'
    if (Array.isArray(value)) return value.map(text).join('、')
    if (typeof value === 'object') {
      try { return JSON.stringify(value) } catch (error) { return text(value) }
    }
    return text(value)
  }

  function fieldsOf(ev) {
    const fields = (ev && ev.fields) || {}
    const entries = []
    for (const key of Object.keys(fields)) {
      if (CONSUMED_FIELDS[key]) continue
      entries.push({ key: key, label: key, value: formatFieldValue(fields[key]) })
    }
    return entries
  }

  // 选中节点的检查器数据。section.kind 决定页面怎么画：
  // prose / kv / evidence / chips / tools / fields。
  function buildInspector(detail, idx, graphOpt) {
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    if (!events.length || idx === null || idx === undefined || idx < 0 || idx >= events.length) return null
    const ev = events[idx] || {}
    const graph = graphOpt || buildGraph(detail)
    const node = graph.nodes[idx] || null
    const described = node ? { title: node.title, label: node.label, tone: node.tone, family: node.family, glyph: node.glyph, emphasis: node.emphasis } : describeEvent(ev, detail)
    const column = graph.columns.find(function (item) { return item.col === (node ? node.col : 0) })
    const stepCount = graph.columns.length
    const sections = []

    const what = text(ev.output) || text(ev.content)
    if (what) {
      sections.push({ key: 'what', title: '做了什么', kind: 'prose', paragraphs: U.paragraphs(what, 200), collapsed: false })
    }
    const why = text(ev.reason) || text(ev.note) || text(ev.purpose)
    if (why) {
      sections.push({ key: 'why', title: '为什么', kind: 'prose', paragraphs: U.paragraphs(why, 200), collapsed: false })
    }

    if (ev.action === 'quickly_check' || ev.action === 'hit') {
      const entries = verdictEntries(ev.verdict)
      if (entries.length) sections.push({ key: 'verdict', title: '判据', kind: 'kv', entries: entries, collapsed: false })
    }

    const evidence = ev.evidence || null
    if (evidence) {
      const inline = text(evidence.inline)
      const files = valuesOf(evidence.files)
      const sources = valuesOf(evidence.sources).concat(valuesOf(ev.sources)).filter(function (item, at, list) { return list.indexOf(item) === at })
      const missing = text(evidence.missing)
      if (inline || files.length || sources.length || missing) {
        sections.push({
          key: 'evidence',
          title: '现场证据',
          kind: 'evidence',
          inline: inline ? { text: inline, chars: Number(evidence.inlineChars || 0) || U.chars(inline).length } : null,
          files: files,
          sources: sources,
          missing: missing,
          collapsed: true,
        })
      }
    }

    const chipGroups = []
    const caseId = text(ev.case)
    if (caseId) chipGroups.push({ label: 'case', values: [caseId], tone: 'hit' })
    for (const key of ['candidates', 'considered', 'excluded', 'refs']) {
      const values = valuesOf(ev[key])
      if (values.length) chipGroups.push({ label: key, values: values, tone: key === 'excluded' ? 'miss' : key === 'refs' ? 'book' : 'neutral' })
    }
    if (chipGroups.length) sections.push({ key: 'related', title: '关联', kind: 'chips', groups: chipGroups, collapsed: true })

    const tools = valuesOf(ev.toolCalls)
    if (tools.length) sections.push({ key: 'tools', title: '工具调用', kind: 'tools', items: tools, collapsed: true })

    const fieldEntries = fieldsOf(ev)
    if (fieldEntries.length) sections.push({ key: 'fields', title: '其余字段', kind: 'fields', entries: fieldEntries, collapsed: true })

    const parallel = column && column.count > 1 ? { count: column.count, sameStep: true, group: text(ev.parallelGroup) || null } : null
    return {
      idx: idx,
      total: events.length,
      step: ev.step !== null && ev.step !== undefined ? ev.step : '?',
      stepCount: stepCount,
      role: text(ev.role),
      roleLabel: roleLabel(ev),
      family: described.family,
      tone: described.tone,
      glyph: described.glyph,
      label: described.label,
      title: described.title,
      emphasis: described.emphasis,
      parallel: parallel,
      sections: sections,
      fields: (ev && ev.fields) || {},
      prev: idx > 0 ? idx - 1 : null,
      next: idx < events.length - 1 ? idx + 1 : null,
    }
  }

  function insightTone(value) {
    const allowed = { info: 1, good: 1, warn: 1, risk: 1, neutral: 1 }
    return allowed[value] ? value : 'neutral'
  }

  // 未选中时的概览：insights + 家族图例 + 数据来源脚注。
  function buildOverview(detail, graphOpt) {
    const graph = graphOpt || buildGraph(detail)
    const insights = Array.isArray(detail && detail.insights) ? detail.insights.map(function (item) {
      return {
        id: text(item && item.id),
        tone: insightTone(item && item.tone),
        title: text(item && item.title),
        text: text(item && item.text),
      }
    }).filter(function (item) { return item.title || item.text }) : []

    const seen = Object.create(null)
    const legend = []
    for (const node of graph.nodes) {
      if (seen[node.tone]) {
        seen[node.tone].count += 1
        continue
      }
      seen[node.tone] = { tone: node.tone, label: TONE_LABELS[node.tone] || node.label, count: 1 }
      legend.push(seen[node.tone])
    }
    const file = text(detail && detail.file) || text(detail && detail.session && detail.session.file)
    return {
      insights: insights,
      legend: legend,
      warnings: Array.isArray(detail && detail.warnings) ? detail.warnings.map(text).filter(Boolean) : [],
      footnote: '数据来自 traces/' + (file || '（未知文件）') + ' · 只读',
      steps: graph.columns.length,
      events: graph.nodes.length,
      conclusionIndex: graph.meta ? graph.meta.conclusionIndex : null,
    }
  }

  // 页头 chips 与数量。数量能算就算，不写“多个”。
  function deriveStats(detail) {
    const session = (detail && detail.session) || {}
    const events = detail && Array.isArray(detail.events) ? detail.events : []
    const steps = (function () {
      const seen = Object.create(null)
      let count = 0
      for (const ev of events) {
        const key = text(ev && ev.step)
        if (key && !seen[key]) { seen[key] = true; count += 1 }
      }
      return count
    })()
    const stepCount = isNum(session.stepCount) ? Number(session.stepCount) : (steps || null)
    const eventCount = events.length || (isNum(session.eventCount) ? Number(session.eventCount) : 0)
    const status = U.statusTone(session.status)
    const chips = []
    chips.push({ key: 'status', label: '状态', value: status.label, tone: status.tone, dot: true })
    if (session.framework) chips.push({ key: 'framework', label: '框架', value: text(session.framework), tone: 'book' })
    if (session.platform) chips.push({ key: 'platform', label: '平台', value: text(session.platform), tone: 'index' })
    if (session.category) chips.push({ key: 'category', label: '类别', value: text(session.category), tone: 'check' })
    return {
      status: status,
      chips: chips,
      framework: text(session.framework) || null,
      platform: text(session.platform) || null,
      category: text(session.category) || null,
      stepCount: stepCount,
      eventCount: eventCount,
      currentStep: isNum(session.currentStep) ? Number(session.currentStep) : null,
      hasConclusion: !!session.hasConclusion,
      activeCase: text((detail && detail.activeCase) || session.activeCase) || null,
      file: text((detail && detail.file) || session.file) || null,
      summary: text((detail && detail.summary) || session.summary) || '',
      lastAction: text((detail && detail.lastAction) || session.lastAction) || '',
      createdAt: session.createdAt || null,
      updatedAt: session.updatedAt || null,
      relativeUpdated: U.formatRelative(session.updatedAt),
      span: U.formatSpan(session.createdAt, session.updatedAt),
      excludedCount: ((detail && detail.excludedCases) || session.excludedCases || []).length,
      sedimented: (detail && detail.sedimented) || session.sedimented || null,
      feedback: (detail && detail.feedback) || session.feedback || null,
    }
  }

  // 列表卡片的一行元信息：框架 · 平台 · N 步 · 排除 N。
  function sessionMeta(session) {
    const parts = []
    if (session && session.framework) parts.push(text(session.framework))
    if (session && session.platform) parts.push(text(session.platform))
    if (isNum(session && session.stepCount)) parts.push(Number(session.stepCount) + ' 步')
    const excluded = session && Array.isArray(session.excludedCases) ? session.excludedCases.length : 0
    if (excluded) parts.push('排除 ' + excluded)
    return parts
  }

  return {
    TONES: TONES,
    TONE_LABELS: TONE_LABELS,
    ACTIONS: ACTIONS,
    VERBS: VERBS,
    resolve: resolve,
    describeEvent: describeEvent,
    buildGraph: buildGraph,
    applyTones: applyTones,
    buildInspector: buildInspector,
    buildOverview: buildOverview,
    deriveStats: deriveStats,
    sessionMeta: sessionMeta,
    eventChars: eventChars,
    charLabel: charLabel,
    roleLabel: roleLabel,
  }
})()
