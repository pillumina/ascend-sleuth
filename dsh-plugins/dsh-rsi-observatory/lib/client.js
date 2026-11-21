// dsh-rsi-observatory —— 浏览器半：RSI 实验台整页
//
// 席位：main 的 keyed 条目 rsi-observatory（整页）+ sidebar.panellist（左侧图标「实验台」）。
// 只读：全部数据来自 host 的 rsi-list / rsi-detail 两条 RPC；本文件不读文件、不解析 JSONL、
// 不写仓库。判定、阶段、缺口都由 scripts/rsi_observatory.py 派生，这里只做展示。
//
// 产物格式与 dsh-sleuth-copilot 相同：window.__ModuleLoader__.load({ id, factory })，
// 不引构建工具；改本文件后 bump package.json 的 version 并按原路重装。

window.__ModuleLoader__.load({
  id: 'dsh-rsi-observatory',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const CHANNEL = '/rsi-observatory'
    const PLUGIN_VERSION = '0.8.0'
    const PANEL_ID = 'rsi-observatory'
    const PANEL_LABEL = '自演进实验'

    const TABS = [
      { id: 'overview', label: '实验概览' },
      { id: 'proposal', label: '改动提案' },
      { id: 'events', label: '操作记录' },
    ]

    const DECISION_LABEL = {
      accept: '通过',
      reject: '拒绝',
      insufficient: '证据不足',
      unknown: '未知',
    }
    const DECISION_TONE = {
      accept: 'ok',
      reject: 'bad',
      insufficient: 'warn',
      unknown: 'muted',
    }
    const GAP_LABEL = {
      no_conclusion: '缺少结论',
      no_cost: '缺少成本数据',
      unknown_decision: '还没有结论',
      no_rollout: '缺少执行记录',
      rolled_back: '已回滚',
      id_collision: '实验编号重复',
    }
    const KIND_LABEL = {
      experiment: '实验',
      proposal: '提案',
      decision: '判定',
      rollout: '执行',
      archive: '归档',
    }
    const COPY = {
      loading: '正在读取实验记录…',
      emptyTitle: '还没有实验记录',
      emptyBody: '实验记录库里还没有数据。跑一次自演进实验后回到这里刷新。',
      emptySource: '数据源',
      retry: '重试',
      refresh: '刷新',
      readOnly: '只读浏览',
      experiments: '实验',
      proposals: '提案',
      noDetail: '从左侧选一条实验查看明细。',
      noProposal: '这条实验没有保存改动提案。',
      noEvents: '这条实验还没有操作记录。',
      noStageFields: '这个环节没有留下记录。',
      unknownTime: '时间未记录',
    }

    // ---- 纯展示工具（测试直接调用，不碰 DOM） ------------------------------------

    function decisionLabel(value) {
      const key = String(value || '')
      if (!key) return '未记录'
      return DECISION_LABEL[key] || key
    }

    function decisionTone(value) {
      return DECISION_TONE[String(value || '')] || 'muted'
    }

    function gapLabel(value) {
      return GAP_LABEL[String(value || '')] || String(value || '')
    }

    function formatScore(value) {
      if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
      return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
    }

    function compactNumber(value) {
      if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
      return new Intl.NumberFormat('zh-CN', {
        notation: 'compact', maximumFractionDigits: 1,
      }).format(value)
    }

    function formatDuration(ms) {
      if (typeof ms !== 'number' || !Number.isFinite(ms)) return '—'
      if (ms < 1000) return Math.round(ms) + ' 毫秒'
      const seconds = ms / 1000
      if (seconds < 60) return seconds.toFixed(seconds < 10 ? 1 : 0) + ' 秒'
      const minutes = seconds / 60
      if (minutes < 60) return minutes.toFixed(minutes < 10 ? 1 : 0) + ' 分钟'
      return (minutes / 60).toFixed(1) + ' 小时'
    }

    function formatCost(conclusion) {
      const cost = conclusion && conclusion.cost
      if (!cost || typeof cost !== 'object') return '—'
      const primary = conclusion.metrics && conclusion.metrics.cost_primary
      const item = (primary && cost[primary]) || cost.tokens
      if (item && typeof item === 'object') {
        const paired = typeof cost.paired === 'number' ? cost.paired : null
        const value = primary === 'time'
          ? formatDuration(item.candidate)
          : (primary === 'calls' ? compactNumber(item.candidate) + ' 次'
            : compactNumber(item.candidate) + ' 词元')
        return value + (paired !== null ? ' · ' + paired + ' 对样本' : '')
      }
      if (typeof cost === 'number') return String(cost)
      return '—'
    }

    function backendLabel(value) {
      return { local: '本地记录', memory: '内存记录' }[String(value || '')] || String(value || '未知来源')
    }

    function formatAt(value) {
      const text = String(value || '')
      if (!text) return COPY.unknownTime
      return text.replace('T', ' ').replace(/(\+|Z).*$/, '')
    }

    function pairedText(paired) {
      if (!paired || typeof paired !== 'object') return '—'
      return '候选胜 ' + String(paired.b) + ' · 对照胜 ' + String(paired.c)
        + ' · 样本 ' + String(paired.n)
    }

    function constraintLabel(name) {
      return { knowledge: '知识使用', source: '源码使用', tool: '工具使用' }[String(name)]
        || String(name)
    }

    function stageStateLabel(state) {
      return String(state) === 'recorded' || String(state) === 'evidence' ? '有记录' : '暂无记录'
    }

    function stageTone(stage) {
      const state = String((stage && stage.state) || '')
      return state === 'evidence' || state === 'recorded' ? 'ok' : 'muted'
    }

    function stageStateClass(stage) {
      return stageTone(stage) === 'ok' ? 'rsi-state-ok' : 'rsi-state-muted'
    }

    function stageSummary(stage) {
      const text = String((stage && stage.summary) || '')
      if (String(stage && stage.id) === 'gate') {
        const key = (text.match(/^(accept|reject|insufficient)\b/) || [])[1]
        return key ? decisionLabel(key) + ' · 结论详情见下方' : text
      }
      return text
    }

    function eventKinds(history) {
      const seen = []
      for (const row of history || []) {
        const kind = String((row && row.kind) || '')
        if (kind && seen.indexOf(kind) < 0) seen.push(kind)
      }
      return seen
    }

    // ---- 小组件 ----------------------------------------------------------------

    function Dot(props) {
      return h('span', { class: 'rsi-dot rsi-dot-' + String(props.tone || 'muted'), 'aria-hidden': 'true' })
    }

    function Chip(props) {
      return h('span', { class: 'rsi-chip' }, props.children)
    }

    function EmptyState(props) {
      const source = props && props.source
      return h('div', { class: 'rsi-empty' },
        h('div', { class: 'rsi-empty-title' }, COPY.emptyTitle),
        h('p', { class: 'rsi-text' }, COPY.emptyBody),
        source ? h('div', { class: 'rsi-source' },
          COPY.emptySource + '：' + String(source.backend || '') + ' · ' + String(source.path || source.base || ''),
        ) : null,
        h('div', { class: 'rsi-actions' },
          h('button', { class: 'rsi-btn', type: 'button', onClick: props && props.onRefresh }, COPY.refresh),
        ),
      )
    }

    function ErrorState(props) {
      const message = props && props.message ? String(props.message) : '未知错误'
      return h('div', { class: 'rsi-error', role: 'alert' },
        h('div', { class: 'rsi-error-title' }, '读取失败'),
        h('pre', { class: 'rsi-pre rsi-error-body' }, message),
        h('div', { class: 'rsi-actions' },
          h('button', { class: 'rsi-btn', type: 'button', onClick: props && props.onRefresh }, COPY.retry),
        ),
      )
    }

    function SourceBar(props) {
      const source = props && props.source
      const generatedAt = props && props.generatedAt
      return h('div', { class: 'rsi-source' },
        h('span', { class: 'rsi-badge' }, h(Dot, { tone: 'ok' }), COPY.readOnly),
        source ? h('span', null, '数据来源：' + backendLabel(source.backend) + ' · ' + String(source.path || source.base || '')) : null,
        generatedAt ? h('span', null, '读取于 ' + formatAt(generatedAt)) : null,
      )
    }

    function CatalogList(props) {
      const mode = props.mode
      const experiments = props.experiments || []
      const proposals = props.proposals || []
      const selectedKey = props.selectedKey || ''
      const onSelect = props.onSelect || function () {}
      const rows = mode === 'proposals'
        ? proposals.map(function (item) {
          const tone = decisionTone(item.decision)
          return h('li', { key: item.proposalId },
            h('button', {
              class: 'rsi-row', type: 'button',
              'aria-current': String(selectedKey) === String(item.proposalId) ? 'true' : 'false',
              onClick: function () { onSelect(String(item.proposalId || '')) },
            },
            h('span', { class: 'rsi-row-line' },
              h(Dot, { tone: tone }),
              h('span', { class: 'rsi-row-title' }, String(item.title || item.proposalId)),
            ),
            h('span', { class: 'rsi-row-meta' },
              String(item.proposalId),
              item.target ? ' · ' + String(item.target) : '',
              ' · ' + decisionLabel(item.decision),
            ),
            item.problem ? h('span', { class: 'rsi-row-problem' }, '问题：' + String(item.problem)) : null,
            h('span', { class: 'rsi-row-meta' }, '实验 ' + String((item.experimentIds || []).length) + ' 次 · ' + formatAt(item.at)),
            ),
          )
        })
        : experiments.map(function (item) {
          const tone = decisionTone(item.decision)
          return h('li', { key: item.eventId },
            h('button', {
              class: 'rsi-row', type: 'button',
              'aria-current': String(selectedKey) === String(item.eventId) ? 'true' : 'false',
              onClick: function () { onSelect(String(item.eventId || '')) },
            },
            h('span', { class: 'rsi-row-line' },
              h(Dot, { tone: tone }),
              h('span', { class: 'rsi-row-title' }, String(item.title || '(未命名实验)')),
            ),
            h('span', { class: 'rsi-row-meta' },
              String(item.proposalId || '—'),
              item.target ? ' · ' + String(item.target) : '',
              ' · ' + decisionLabel(item.decision),
            ),
            item.problem ? h('span', { class: 'rsi-row-problem' }, '问题：' + String(item.problem)) : null,
            h('span', { class: 'rsi-row-meta' }, formatAt(item.at)),
            ),
          )
        })
      if (!rows.length) {
        return h('div', { class: 'rsi-list-empty' },
          mode === 'proposals' ? '还没有提案快照（提案只在进入实验后才可见）。' : '还没有实验记录。')
      }
      return h('ul', { class: 'rsi-list', 'aria-label': mode === 'proposals' ? '提案列表' : '实验列表' }, rows)
    }

    function SummaryStrip(props) {
      const experiment = props.experiment || {}
      const conclusion = props.conclusion || {}
      const paired = experiment.paired
      const cells = [
        { key: '结论', value: decisionLabel(experiment.decision), tone: decisionTone(experiment.decision) },
        { key: '样本', value: paired ? String(paired.n) : '—', tone: 'muted' },
        { key: '成本', value: formatCost(conclusion), tone: 'muted' },
        { key: '回滚', value: experiment.rolledBack ? '是' : '否', tone: experiment.rolledBack ? 'warn' : 'muted' },
      ]
      return h('div', { class: 'rsi-strip' }, cells.map(function (cell) {
        return h('div', { class: 'rsi-strip-cell', key: cell.key },
          h('div', { class: 'rsi-k' }, cell.key),
          h('div', { class: 'rsi-v' }, h(Dot, { tone: cell.tone }), String(cell.value)),
        )
      }))
    }

    function StageTrack(props) {
      const stages = props.stages || []
      const openId = props.openId || ''
      const onToggle = props.onToggle || function () {}
      if (!stages.length) return h('div', { class: 'rsi-text' }, '没有环节记录。')
      return h('div', null,
        h('div', { class: 'rsi-section-head' },
          h('h3', { class: 'rsi-h3' }, '实验环节'),
          h('span', { class: 'rsi-hint' }, '按执行顺序排列；没有记录的环节会标为「暂无记录」'),
        ),
        h('ol', { class: 'rsi-stages' }, stages.map(function (stage, index) {
          const open = String(openId) === String(stage.id)
          return h('li', { key: stage.id, class: 'rsi-stage' },
            h('button', {
              class: 'rsi-stage-btn', type: 'button',
              'aria-expanded': open ? 'true' : 'false',
              onClick: function () { onToggle(open ? '' : String(stage.id)) },
            },
            h('span', { class: 'rsi-stage-index', 'aria-hidden': 'true' }, String(index + 1).padStart(2, '0')),
            h('span', { class: 'rsi-stage-copy' },
              h('span', { class: 'rsi-stage-label' }, String(stage.label || stage.id)),
              h('span', { class: 'rsi-stage-summary' }, stageSummary(stage)),
            ),
            h('span', { class: 'rsi-state-pill ' + stageStateClass(stage) },
              stageStateLabel(stage.state)),
            ),
            open ? h('div', { class: 'rsi-stage-body' },
              h('p', { class: 'rsi-text' }, String(stage.summary || '')),
              (stage.fields || []).length
                ? h('div', { class: 'rsi-code-list' }, stage.fields.map(function (field) {
                  return h('code', { key: field, class: 'rsi-code' }, field)
                }))
                : h('p', { class: 'rsi-hint' }, COPY.noStageFields),
            ) : null,
          )
        })),
      )
    }

    function verdictSentence(decision, conclusion) {
      const key = String(decision || '')
      const reason = String((conclusion && conclusion.reason) || '')
      if (key === 'accept') return '候选通过：质量没有变差，主成本下降达到要求。'
      if (key === 'reject') if (reason.includes('硬约束')) return '候选未通过：硬约束或回归检查没有通过。'
      if (key === 'reject') return '候选未通过：质量或成本没有达到门槛。'
      if (key === 'insufficient') return '证据不足：现有样本还不足以判断这条候选是否更好。'
      return '这条实验还没有结论。'
    }

    function reasonSentence(conclusion) {
      const reason = String((conclusion && conclusion.reason) || '')
      if (!reason) return '没有记录原因。'
      if (reason.startsWith('主指标非劣')) return '质量没有变差，主成本下降达到要求。'
      if (reason.includes('硬约束')) return '硬约束或回归检查没有通过，不能接受。'
      if (reason.startsWith('没有方向不一致')) return '没有成对差异，质量证据不足。'
      return reason
    }

    function DecisionPanel(props) {
      const conclusion = props.conclusion || {}
      const experiment = props.experiment || {}
      const gates = conclusion.metrics && conclusion.metrics.constraints
      const constraints = gates && typeof gates === 'object' ? gates : null
      const costDims = conclusion.metrics && conclusion.metrics.cost_dimensions
      const rows = [
        ['结论', decisionLabel(experiment.decision)],
        ['原因', reasonSentence(conclusion)],
        ['成对比较', pairedText(experiment.paired)],
        ['显著性', conclusion.p_value === undefined || conclusion.p_value === null ? '—' : String(conclusion.p_value)],
        ['判定阈值', conclusion.alpha_eff === undefined || conclusion.alpha_eff === null ? '—' : String(conclusion.alpha_eff)],
        ['平均分', '对照 ' + formatScore(experiment.baselineScore) + ' / 候选 ' + formatScore(experiment.candidateScore)],
        ['成本', formatCost(conclusion)],
      ]
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '结论'),
        h('p', { class: 'rsi-verdict-copy' }, verdictSentence(experiment.decision, conclusion)),
        h('details', { class: 'rsi-fold rsi-decision-details' },
          h('summary', null, '看判定细节'),
          h('dl', { class: 'rsi-kv' }, rows.map(function (row) {
            return h('div', { class: 'rsi-kv-row', key: row[0] },
              h('dt', null, row[0]), h('dd', null, row[1]))
          })),
          constraints ? h('div', { class: 'rsi-sub' },
            h('h4', { class: 'rsi-h4' }, '约束检查'),
            h('ul', { class: 'rsi-list-plain' }, Object.keys(constraints).map(function (name) {
              const item = constraints[name] || {}
              return h('li', { key: name },
                constraintLabel(name) + '：' + decisionLabel(item.decision)
                  + (item.paired !== undefined ? ' · ' + String(item.paired) + ' 对样本' : ''),
              )
            })),
          ) : null,
          costDims && typeof costDims === 'object' ? h('div', { class: 'rsi-sub' },
            h('h4', { class: 'rsi-h4' }, '成本明细'),
            h('ul', { class: 'rsi-list-plain' }, Object.keys(costDims).map(function (name) {
              const item = costDims[name] || {}
              const ratio = item.baseline ? (item.candidate / item.baseline) : null
              return h('li', { key: name },
                ({ tokens: '词元', elapsed_ms: '耗时', tool_calls: '工具调用', full_body_reads: '全文读取' }[name] || name)
                  + '：对照 ' + (name === 'elapsed_ms' ? formatDuration(item.baseline) : compactNumber(item.baseline))
                  + ' / 候选 ' + (name === 'elapsed_ms' ? formatDuration(item.candidate) : compactNumber(item.candidate))
                  + (ratio === null ? '' : ' · 比值 ' + ratio.toFixed(2)),
              )
            })),
          ) : null,
        ),
      )
    }

    function SampleScores(props) {
      const record = props.record || {}
      const baseline = record.baseline && record.baseline.per_sample
      const candidate = record.candidate && record.candidate.per_sample
      if (!baseline || !candidate) return null
      const ids = Object.keys(baseline)
      if (!ids.length) return null
      const context = {}
      for (const item of record.sample_context || []) {
        if (item && item.id) context[String(item.id)] = String(item.title || '')
      }
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '逐样本评分'),
        h('p', { class: 'rsi-explainer' },
          '对照是没有改技能的原流程，候选是改了技能后的流程。',
          '“正确”表示独立评审认为输出解决了样本问题；“变化”是候选相对对照的结果。',
        ),
        h('div', {
          class: 'rsi-table-wrap', tabIndex: 0, role: 'region',
          'aria-label': '逐样本评分表',
        },
          h('table', { class: 'rsi-table' },
            h('caption', { class: 'rsi-caption' }, '同一批样本在对照与候选下的结果'),
            h('thead', null, h('tr', null,
              h('th', { scope: 'col' }, '样本 / 问题'),
              h('th', { scope: 'col' }, '对照'),
              h('th', { scope: 'col' }, '候选'),
              h('th', { scope: 'col' }, '变化'),
            )),
            h('tbody', null, ids.map(function (id) {
              const delta = candidate[id] - baseline[id]
              const title = context[id]
              return h('tr', { key: id },
                h('th', { scope: 'row', class: 'rsi-sample-cell' },
                  h('span', { class: 'rsi-sample-id' }, String(id)),
                  title ? h('span', { class: 'rsi-sample-title' }, title) : null,
                ),
                h('td', null, baseline[id] === 1 ? '正确' : '错误'),
                h('td', null, candidate[id] === 1 ? '正确' : '错误'),
                h('td', { class: delta > 0 ? 'rsi-good' : (delta < 0 ? 'rsi-bad' : 'rsi-muted') },
                  delta > 0 ? '修好' : (delta < 0 ? '变差' : '不变')),
              )
            })),
          ),
        ),
      )
    }

    function RolloutBlock(props) {
      const rollout = props.rollout || {}
      const arms = rollout.arms && typeof rollout.arms === 'object' ? rollout.arms : {}
      const samples = Array.isArray(rollout.samples) ? rollout.samples : []
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '执行情况'),
        h('dl', { class: 'rsi-kv' },
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '执行组'),
            h('dd', null, '对照 ' + String(arms.baseline === undefined ? '—' : arms.baseline)
              + ' 条 / 候选 ' + String(arms.candidate === undefined ? '—' : arms.candidate) + ' 条')),
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '样本数'),
            h('dd', null, String(samples.length))),
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '工作区'),
            h('dd', null, String(rollout.workspace || '—'))),
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '已回滚'),
            h('dd', null, rollout.rolled_back ? '是' : '否')),
        ),
        samples.length ? h('p', { class: 'rsi-hint' }, '样本：' + samples.slice(0, 12).join(' · ')
          + (samples.length > 12 ? ' …' : '')) : null,
      )
    }

    function DiffBody(props) {
      const diff = String(props.diff || '')
      if (!diff) return null
      return h('div', { class: 'rsi-diff-lines' }, diff.split('\n').map(function (line, index) {
        const tone = line.startsWith('+++') || line.startsWith('---') ? 'meta'
          : line.startsWith('+') ? 'add'
            : line.startsWith('-') ? 'del'
              : line.startsWith('@@') ? 'hunk' : ''
        return h('span', { key: index, class: 'rsi-diff-line' + (tone ? ' rsi-diff-' + tone : '') },
          line || ' ')
      }))
    }

    function ProposalPanel(props) {
      const proposal = props.proposal || {}
      const artifact = proposal.artifact && typeof proposal.artifact === 'object' ? proposal.artifact : {}
      const files = Array.isArray(artifact.files) ? artifact.files : []
      const diff = typeof artifact.diff === 'string' ? artifact.diff : ''
      if (!proposal || Object.keys(proposal).length === 0) {
        return h('div', { class: 'rsi-empty' }, COPY.noProposal)
      }
      const rows = [
        ['提案编号', String(proposal.id || '—')],
        ['EV 卡', String((proposal.artifact && proposal.artifact.ev_card) || '未绑定')],
        ['目标对象', String(proposal.target || '—')],
        ['影响范围', String(proposal.component || '—')],
        ['改动类型', String(proposal.artifact_kind || '—')],
        ['状态', String(proposal.status || '—')],
        ['预期效果', String(proposal.expected || '—')],
        ['风险', String(proposal.risk || '—')],
        ['回滚方式', String(proposal.rollback || '—')],
        ['是否回滚', proposal.rolled_back ? '是' : '否'],
      ]
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '改动提案'),
        h('dl', { class: 'rsi-kv' }, rows.map(function (row) {
          return h('div', { class: 'rsi-kv-row', key: row[0] },
            h('dt', null, row[0]), h('dd', null, row[1]))
        })),
        files.length ? h('div', { class: 'rsi-sub' },
          h('h4', { class: 'rsi-h4' }, '改动文件'),
          h('div', { class: 'rsi-code-list' }, files.map(function (file) {
            return h('code', { key: String(file), class: 'rsi-code' }, String(file))
          })),
        ) : null,
        diff ? h('details', { class: 'rsi-fold', open: diff.split('\n').length <= 14 },
          h('summary', null,
            '改动内容',
            artifact.stats
              ? h('span', { class: 'rsi-hint' }, ' · ' + String(artifact.stats.files || files.length)
                + ' 个文件 · +' + String(artifact.stats.additions || 0)
                + ' / -' + String(artifact.stats.deletions || 0))
              : null,
          ),
          h('div', { class: 'rsi-diff-wrap' }, h(DiffBody, { diff: diff })),
        ) : null,
      )
    }

    function HistoryList(props) {
      const history = props.history || []
      const kind = props.kind || 'all'
      const openId = props.openId || ''
      const onToggle = props.onToggle || function () {}
      if (!history.length) return h('div', { class: 'rsi-empty' }, COPY.noEvents)
      const kinds = eventKinds(history)
      const visible = history.filter(function (row) { return kind === 'all' || String(row.kind) === kind })
      return h('div', null,
        h('div', { class: 'rsi-toolbar' },
          h('button', {
            class: 'rsi-fchip', type: 'button', 'aria-pressed': kind === 'all' ? 'true' : 'false',
            onClick: function () { props.onKind && props.onKind('all') },
          }, '全部'),
          kinds.map(function (name) {
            return h('button', {
              key: name, class: 'rsi-fchip', type: 'button',
              'aria-pressed': kind === name ? 'true' : 'false',
              onClick: function () { props.onKind && props.onKind(name) },
            }, KIND_LABEL[name] || name)
          }),
          h('span', { class: 'rsi-hint' }, String(visible.length) + ' 条'),
        ),
        h('ul', { class: 'rsi-events', 'aria-label': '操作记录' }, visible.map(function (row) {
          const id = String(row.eventId || '')
          const open = openId === id
          return h('li', { key: id || String(row.at), class: 'rsi-event' },
            h('button', {
              class: 'rsi-event-btn', type: 'button',
              'aria-expanded': open ? 'true' : 'false',
              onClick: function () { onToggle(open ? '' : id) },
            },
            h('span', { class: 'rsi-event-at' }, formatAt(row.at)),
            h('span', { class: 'rsi-event-kind' }, KIND_LABEL[String(row.kind)] || String(row.kind)),
            h('span', { class: 'rsi-event-sum' }, String(row.summary || '')),
            ),
            open ? h('div', { class: 'rsi-event-body' },
              row.truncated ? h('p', { class: 'rsi-hint' }, '内容超过 4KB，长字符串已截断。') : null,
              h('pre', { class: 'rsi-pre' }, JSON.stringify(row.data || {}, null, 2)),
            ) : null,
          )
        })),
      )
    }

    function Gaps(props) {
      const gaps = props.gaps || []
      if (!gaps.length) return null
      return h('div', { class: 'rsi-gaps' }, gaps.map(function (gap) {
        return h('span', { key: gap, class: 'rsi-gap' }, gapLabel(gap))
      }))
    }

    function DetailTabs(props) {
      const tab = props.tab
      const onTab = props.onTab
      return h('div', { class: 'rsi-tabs', role: 'tablist', 'aria-label': '实验视图' },
        TABS.map(function (item) {
          const selected = tab === item.id
          return h('button', {
            key: item.id, class: 'rsi-tab', type: 'button', role: 'tab',
            'aria-selected': selected ? 'true' : 'false',
            tabIndex: selected ? 0 : -1,
            onClick: function () { onTab(item.id) },
          }, item.label)
        }),
      )
    }

    // ---- 整页 ------------------------------------------------------------------

    function ProposalDetail(props) {
      const proposal = props.proposal || {}
      const linked = props.experiments || []
      const problem = linked.map(function (item) { return item.problem }).find(Boolean) || ''
      return h('div', null,
        h('div', { class: 'rsi-exp-head' },
          h('div', null,
            h('h2', { class: 'rsi-h2' }, String(proposal.title || '改动提案')),
            h('p', { class: 'rsi-meta' }, '提案编号 ' + String(proposal.proposalId || '—')
              + (proposal.component ? ' · ' + String(proposal.component) : '')),
          ),
          h('div', { class: 'rsi-verdict' }, '只读提案'),
        ),
        problem ? h('p', { class: 'rsi-problem-line' }, '要解决的问题：' + String(problem)) : null,
        h('p', { class: 'rsi-scope' },
          '提案 = 一条待验证的改动；实验 = 把提案放到真实样本上跑一次对照。'),
        h(ProposalPanel, { proposal: proposal }),
        h('div', { class: 'rsi-card' },
          h('h3', { class: 'rsi-h3' }, '关联实验'),
          linked.length ? h('div', { class: 'rsi-link-list' }, linked.map(function (item) {
            return h('button', {
              key: item.eventId, class: 'rsi-link-row', type: 'button',
              onClick: function () { props.onOpen(item.eventId) },
            },
            h('span', { class: 'rsi-link-title' }, String(item.title || item.problem || '未命名实验')),
            h('span', { class: 'rsi-link-meta' }, decisionLabel(item.decision)
              + ' · ' + formatAt(item.at)),
            )
          })) : h('p', { class: 'rsi-hint' }, '这条提案还没有关联实验。'),
        ),
      )
    }

    function Page(props) {
      const sessionId = props && props.sessionId ? String(props.sessionId) : ''
      const [phase, setPhase] = React.useState('loading')
      const [list, setList] = React.useState(null)
      const [error, setError] = React.useState('')
      const [mode, setMode] = React.useState('experiments')
      const [selectedKey, setSelectedKey] = React.useState('')
      const [tab, setTab] = React.useState('overview')
      const [detail, setDetail] = React.useState(null)
      const [detailPhase, setDetailPhase] = React.useState('idle')
      const [detailError, setDetailError] = React.useState('')
      const [refreshTick, setRefreshTick] = React.useState(0)
      const [openStage, setOpenStage] = React.useState('')
      const [openEvent, setOpenEvent] = React.useState('')
      const [eventKind, setEventKind] = React.useState('all')

      const rpc = React.useMemo(function () { return makeRpc() }, [])

      React.useEffect(function () {
        let alive = true
        setPhase('loading')
        setError('')
        rpc('rsi-list', { sessionId: sessionId, refresh: refreshTick > 0 })
          .then(function (data) {
            if (!alive) return
            setList(data)
            setPhase('ready')
            const first = data && data.experiments && data.experiments[0]
            if (first && first.eventId) {
              setSelectedKey(function (current) { return current || String(first.eventId) })
            }
          })
          .catch(function (failure) {
            if (!alive) return
            setPhase('error')
            setError(String((failure && failure.message) || failure))
          })
        return function () { alive = false }
      }, [sessionId, refreshTick])

      React.useEffect(function () {
        if (mode === 'proposals') {
          setDetailPhase('ready')
          return undefined
        }
        if (!selectedKey) {
          setDetail(null)
          setDetailPhase('idle')
          return undefined
        }
        let alive = true
        setDetailPhase('loading')
        setDetailError('')
        rpc('rsi-detail', { sessionId: sessionId, experimentId: selectedKey, refresh: refreshTick > 0 })
          .then(function (data) {
            if (!alive) return
            setDetail(data)
            setDetailPhase('ready')
          })
          .catch(function (failure) {
            if (!alive) return
            setDetailPhase('error')
            setDetailError(String((failure && failure.message) || failure))
          })
        return function () { alive = false }
      }, [selectedKey, sessionId, refreshTick, mode])

      function refresh() {
        setRefreshTick(function (value) { return value + 1 })
      }

      const source = list && list.source
      const experiments = (list && list.experiments) || []
      const proposals = (list && list.proposals) || []
      const counts = (list && list.counts) || {}

      if (phase === 'error') {
        return h('div', { class: 'rsi-page' }, h('div', { class: 'rsi-inner' },
          h('header', { class: 'rsi-head' },
            h('div', null,
              h('h1', { class: 'rsi-title' }, '自演进实验'),
              h('p', { class: 'rsi-sub' }, 'Ascend Sleuth · 自演进实验记录', ' · ', PLUGIN_VERSION),
            ),
          ),
          h(ErrorState, { message: error, onRefresh: refresh }),
        ))
      }

      const empty = phase === 'ready' && experiments.length === 0 && proposals.length === 0
      const active = experiments.find(function (item) { return String(item.eventId) === String(selectedKey) })
        || experiments[0]
      const activeProposal = proposals.find(function (item) { return String(item.proposalId) === String(selectedKey) })
        || proposals[0]
      const linkedExperiments = activeProposal
        ? experiments.filter(function (item) { return String(item.proposalId) === String(activeProposal.proposalId) })
        : []
      const conclusion = (detail && detail.conclusion) || {}
      const rollout = (detail && detail.rollout) || {}
      const record = (detail && detail.record) || {}
      const proposal = (detail && detail.proposal) || {}

      return h('div', { class: 'rsi-page' }, h('div', { class: 'rsi-inner' },
        h('header', { class: 'rsi-head' },
          h('div', null,
            h('h1', { class: 'rsi-title' }, '实验台'),
            h('p', { class: 'rsi-sub' }, 'Ascend Sleuth · RSI 实验记录', ' · ', PLUGIN_VERSION),
          ),
          h('div', { class: 'rsi-head-actions' },
            h(SourceBar, { source: source, generatedAt: list && list.generatedAt }),
            h('button', { class: 'rsi-btn', type: 'button', onClick: refresh }, COPY.refresh),
          ),
        ),
        empty ? h(EmptyState, { source: source, onRefresh: refresh }) : h('div', { class: 'rsi-body' },
          h('nav', { class: 'rsi-side', 'aria-label': '实验目录' },
            h('div', { class: 'rsi-mode' },
              h('button', {
                class: 'rsi-mode-btn', type: 'button',
                'aria-pressed': mode === 'experiments' ? 'true' : 'false',
                onClick: function () { setMode('experiments') },
              }, COPY.experiments + ' ' + String(counts.experiments || 0)),
              h('button', {
                class: 'rsi-mode-btn', type: 'button',
                'aria-pressed': mode === 'proposals' ? 'true' : 'false',
                onClick: function () { setMode('proposals') },
              }, COPY.proposals + ' ' + String(counts.proposals || 0)),
            ),
            h(CatalogList, {
              mode: mode, experiments: experiments, proposals: proposals,
              selectedKey: selectedKey,
              onSelect: function (key) {
                setSelectedKey(key)
                setTab('overview')
                setOpenEvent('')
              },
            }),
          ),
          h('main', { class: 'rsi-main' },
            phase === 'loading' ? h('div', { class: 'rsi-text' }, COPY.loading) : null,
            mode === 'proposals'
              ? (activeProposal
                ? h(ProposalDetail, {
                  proposal: activeProposal, experiments: linkedExperiments,
                  onOpen: function (eventId) { setMode('experiments'); setSelectedKey(eventId); setTab('overview') },
                })
                : h('div', { class: 'rsi-text' }, COPY.noProposal))
              : null,
            mode === 'experiments' && !active ? h('div', { class: 'rsi-text' }, COPY.noDetail) : null,
            mode === 'experiments' && active ? h('div', null,
              h('div', { class: 'rsi-exp-head' },
                h('div', null,
                  h('h2', { class: 'rsi-h2' }, String(active.title || '(未命名实验)')),
                  h('p', { class: 'rsi-meta' },
                    String(active.experimentId || '—'),
                    ' · ',
                    String(active.proposalId || '—'),
                    active.target ? ' · ' + String(active.target) : '',
                  ),
                ),
                h('div', { class: 'rsi-verdict' },
                  h(Dot, { tone: decisionTone(active.decision) }),
                  h('span', null, decisionLabel(active.decision)),
                  h('span', { class: 'rsi-hint' }, formatAt(active.at)),
                ),
              ),
              h('p', { class: 'rsi-scope' },
                '一次实验 = 一条候选改动，在同一批真实样本上与未改流程做对照。'),
              active.problem ? h('p', { class: 'rsi-problem-line' },
                '要解决的问题：' + String(active.problem)) : null,
              h(Gaps, { gaps: (detail && detail.gaps) || active.gaps || [] }),
              detailPhase === 'error'
                ? h(ErrorState, { message: detailError, onRefresh: refresh })
                : h('div', null,
                  h(DetailTabs, { tab: tab, onTab: setTab }),
                  detailPhase === 'loading' && !detail
                    ? h('div', { class: 'rsi-text' }, COPY.loading)
                    : h('section', { class: 'rsi-panel', role: 'tabpanel' },
                      tab === 'overview' ? h('div', null,
                        h(SummaryStrip, {
                          experiment: {
                            decision: active.decision,
                            paired: (detail && detail.experiment && detail.experiment.paired) || active.paired,
                            baselineScore: active.baselineScore,
                            candidateScore: active.candidateScore,
                            rolledBack: active.rolledBack,
                          },
                          conclusion: conclusion,
                        }),
                        h(StageTrack, {
                          stages: (detail && detail.stages) || [],
                          openId: openStage,
                          onToggle: setOpenStage,
                        }),
                        h(DecisionPanel, {
                          experiment: {
                            decision: active.decision,
                            paired: (detail && detail.experiment && detail.experiment.paired) || active.paired,
                            baselineScore: active.baselineScore,
                            candidateScore: active.candidateScore,
                          },
                          conclusion: conclusion,
                        }),
                        h(RolloutBlock, { rollout: rollout, record: record }),
                        h(SampleScores, { record: record }),
                      ) : null,
                      tab === 'proposal' ? h(ProposalPanel, { proposal: proposal }) : null,
                      tab === 'events' ? h(HistoryList, {
                        history: (detail && detail.history) || [],
                        kind: eventKind,
                        openId: openEvent,
                        onKind: setEventKind,
                        onToggle: setOpenEvent,
                      }) : null,
                    ),
                ),
            ) : null,
          ),
        ),
      ))
    }

    // ---- RPC 与装配 -------------------------------------------------------------

    let rpcCall = null

    function makeRpc() {
      return async function rpc(endpoint, payload) {
        if (typeof rpcCall === 'function') return rpcCall(endpoint, payload)
        throw new Error('connection 服务不可用')
      }
    }

    function rpcFromCtx(ctx) {
      const connection = ctx.get('connection')
      return async function call(endpoint, payload) {
        if (!connection || !connection.rpc || typeof connection.rpc.call !== 'function') {
          throw new Error('connection 服务不可用：拿不到 DSH 的 RPC 通道')
        }
        const outer = await connection.rpc.call(CHANNEL, String(endpoint), payload === undefined ? {} : payload)
        if (!outer || outer.ok !== true) {
          const failure = outer && outer.error
          throw new Error(failure && failure.message ? failure.message : 'RPC 失败')
        }
        return outer.value
      }
    }

    function Icon(props) {
      const size = props && typeof props.size === 'number' ? props.size : 18
      return h('svg', {
        viewBox: '0 0 24 24', width: size, height: size, fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.55, strokeLinecap: 'round',
        strokeLinejoin: 'round', 'aria-hidden': 'true',
      },
        h('rect', { x: 3.4, y: 3.4, width: 17.2, height: 17.2, rx: 5 }),
        h('path', { d: 'M7 15.2h10' }),
        h('path', { d: 'M7 11.4h6.4' }),
        h('path', { d: 'M7 7.6h4' }),
        h('circle', { cx: 16.6, cy: 7.6, r: 1.35, fill: 'currentColor', stroke: 'none' }),
      )
    }

    const CSS = `
      .rsi-page{height:100%;overflow:auto;box-sizing:border-box;container-type:inline-size;
        padding:0;background:
          radial-gradient(1100px 360px at 8% -8%, color-mix(in srgb,var(--rsi-run) 7%,transparent), transparent 72%),
          var(--dsw-alias-bg-layer-1);
        color:var(--dsw-alias-label-primary);
        font-family:var(--font-sans,ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif);
        --rsi-ok:#15803d;--rsi-bad:#b42318;--rsi-warn:#a16207;--rsi-run:#2563eb;--rsi-muted:#64748b;
        --rsi-border:color-mix(in srgb,currentColor 10%,transparent);
        --rsi-border-strong:color-mix(in srgb,currentColor 16%,transparent);
        --rsi-surface:color-mix(in srgb,var(--dsw-alias-bg-layer-2,#fff) 92%,transparent);
        --rsi-surface-raised:var(--dsw-alias-bg-layer-2,#fff);
        --rsi-shadow:0 12px 34px color-mix(in srgb,currentColor 7%,transparent);
        --rsi-radius:12px;--rsi-radius-sm:8px;--rsi-gap:14px;
        font-variant-numeric:tabular-nums}
      body[data-ds-dark-theme] .rsi-page{
        --rsi-ok:#6ee7a0;--rsi-bad:#fca5a5;--rsi-warn:#fcd34d;--rsi-run:#93c5fd;--rsi-muted:#a8b0bd;
        --rsi-border:color-mix(in srgb,#fff 13%,transparent);
        --rsi-border-strong:color-mix(in srgb,#fff 20%,transparent);
        --rsi-surface:color-mix(in srgb,#111827 88%,transparent);
        --rsi-surface-raised:#111827;
        --rsi-shadow:0 18px 44px rgba(0,0,0,.28)}
      .rsi-inner{max-width:1240px;margin:0 auto;padding:0 28px 48px;box-sizing:border-box}
      .rsi-head{position:sticky;top:0;z-index:10;display:flex;align-items:flex-end;
        justify-content:space-between;gap:18px;flex-wrap:wrap;padding:18px 0 14px;
        border-bottom:1px solid var(--rsi-border);
        background:color-mix(in srgb,var(--dsw-alias-bg-layer-1,#fff) 86%,transparent);
        backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
      .rsi-head-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
      .rsi-title{margin:0;font-size:22px;line-height:1.2;font-weight:700;letter-spacing:-.02em}
      .rsi-sub{margin:4px 0 0;font-size:12.5px;color:var(--dsw-alias-label-secondary)}
      .rsi-body{display:grid;grid-template-columns:286px minmax(0,1fr);gap:20px;margin-top:20px;align-items:start}
      .rsi-side{position:sticky;top:88px;min-width:0;border:1px solid var(--rsi-border);
        border-radius:var(--rsi-radius);padding:12px;background:var(--rsi-surface);box-shadow:var(--rsi-shadow)}
      .rsi-mode{display:flex;gap:4px;padding:3px;margin-bottom:10px;border-radius:999px;
        background:color-mix(in srgb,currentColor 5%,transparent)}
      .rsi-mode-btn{flex:1;min-height:30px;padding:4px 10px;border:0;border-radius:999px;background:none;
        color:var(--dsw-alias-label-secondary);font:inherit;font-size:12px;cursor:pointer}
      .rsi-mode-btn[aria-pressed="true"]{background:var(--rsi-surface-raised);color:var(--dsw-alias-label-primary);
        box-shadow:0 1px 3px color-mix(in srgb,currentColor 12%,transparent)}
      .rsi-list{list-style:none;margin:0;padding:0;max-height:calc(100vh - 190px);overflow:auto;overscroll-behavior:contain}
      .rsi-row{display:block;width:100%;text-align:left;border:0;border-radius:9px;background:none;
        padding:10px 10px 9px;cursor:pointer;color:inherit}
      .rsi-row:hover{background:color-mix(in srgb,currentColor 5%,transparent)}
      .rsi-row[aria-current="true"]{background:color-mix(in srgb,var(--rsi-run) 11%,transparent);
        box-shadow:inset 2px 0 0 var(--rsi-run)}
      .rsi-row-line{display:flex;align-items:center;gap:8px;min-width:0}
      .rsi-row-title{font-size:13px;font-weight:650;line-height:1.35;white-space:nowrap;overflow:hidden;
        text-overflow:ellipsis}
      .rsi-row-meta{display:block;margin-top:4px;font-size:11px;color:var(--dsw-alias-label-secondary);
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-row-problem{display:block;margin-top:4px;font-size:10.5px;line-height:1.4;
        color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-list-empty{padding:16px 8px;font-size:12px;color:var(--dsw-alias-label-secondary)}
      .rsi-main{min-width:0}
      .rsi-exp-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}
      .rsi-h2{margin:0;font-size:18px;line-height:1.35;font-weight:680;letter-spacing:-.015em}
      .rsi-meta{margin:5px 0 0;font-size:12px;color:var(--dsw-alias-label-secondary);word-break:break-word}
      .rsi-verdict{display:inline-flex;align-items:center;gap:7px;min-height:28px;padding:4px 10px;
        border:1px solid var(--rsi-border);border-radius:999px;font-size:12.5px;background:var(--rsi-surface)}
      .rsi-hint{font-size:11px;line-height:1.5;color:var(--dsw-alias-label-secondary)}
      .rsi-gaps{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 0}
      .rsi-gap{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--rsi-border);
        color:var(--rsi-warn);background:color-mix(in srgb,var(--rsi-warn) 7%,transparent)}
      .rsi-tabs{display:flex;gap:16px;margin:18px 0 0;border-bottom:1px solid var(--rsi-border)}
      .rsi-tab{appearance:none;border:0;border-bottom:2px solid transparent;background:none;
        padding:8px 2px 9px;font:inherit;font-size:13px;color:var(--dsw-alias-label-secondary);cursor:pointer}
      .rsi-tab[aria-selected="true"]{color:var(--dsw-alias-label-primary);
        border-bottom-color:var(--rsi-run);font-weight:650}
      .rsi-panel{padding:18px 0 0}
      .rsi-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:18px}
      .rsi-strip-cell{padding:12px 14px;border:1px solid var(--rsi-border);border-radius:10px;
        min-width:0;background:var(--rsi-surface)}
      .rsi-k{font-size:10.5px;letter-spacing:.04em;color:var(--dsw-alias-label-secondary)}
      .rsi-v{display:flex;align-items:center;gap:6px;margin-top:6px;font-size:15px;font-weight:650;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-section-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 0 8px}
      .rsi-h3{margin:0 0 10px;font-size:13px;font-weight:650;letter-spacing:0;color:var(--dsw-alias-label-primary)}
      .rsi-h4{margin:12px 0 6px;font-size:12px;font-weight:650}
      .rsi-verdict-copy{margin:0 0 10px;font-size:13px;line-height:1.6}
      .rsi-scope{margin:10px 0 0;font-size:11.5px;line-height:1.55;color:var(--dsw-alias-label-secondary)}
      .rsi-problem-line{margin:12px 0 0;padding:10px 12px;border-left:3px solid var(--rsi-warn);
        border-radius:0 8px 8px 0;background:color-mix(in srgb,var(--rsi-warn) 7%,transparent);
        font-size:12.5px;line-height:1.55}
      .rsi-link-list{display:grid;gap:6px}
      .rsi-link-row{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;
        padding:9px 10px;border:1px solid var(--rsi-border);border-radius:8px;background:var(--rsi-surface);
        color:inherit;font:inherit;text-align:left;cursor:pointer}
      .rsi-link-row:hover{background:color-mix(in srgb,currentColor 4%,transparent)}
      .rsi-link-title{font-size:12.5px;font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;
        white-space:nowrap}
      .rsi-link-meta{font-size:11px;color:var(--dsw-alias-label-secondary);white-space:nowrap}
      .rsi-decision-details{margin-top:4px}
      .rsi-stages{list-style:none;margin:0 0 18px;padding:0}
      .rsi-stage{position:relative}
      .rsi-stage:not(:last-child)::after{content:"";position:absolute;left:18px;top:38px;bottom:-2px;
        width:1px;background:var(--rsi-border)}
      .rsi-stage-btn{display:grid;grid-template-columns:30px minmax(0,1fr) auto;align-items:center;gap:11px;
        width:100%;border:0;border-radius:8px;background:none;padding:8px 4px;cursor:pointer;
        color:inherit;text-align:left}
      .rsi-stage-btn:hover{background:color-mix(in srgb,currentColor 4%,transparent)}
      .rsi-stage-index{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
        border-radius:50%;border:1px solid var(--rsi-border-strong);background:var(--rsi-surface);
        font-size:10px;color:var(--dsw-alias-label-secondary);position:relative;z-index:1}
      .rsi-stage-copy{display:flex;flex-direction:column;gap:2px;min-width:0}
      .rsi-stage-label{display:block;font-size:13px;font-weight:650;line-height:1.35}
      .rsi-stage-summary{display:block;margin-top:1px;font-size:11.5px;line-height:1.45;
        color:var(--dsw-alias-label-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-state-pill{font-size:10.5px;padding:2px 7px;border-radius:999px;border:1px solid var(--rsi-border);
        color:var(--dsw-alias-label-secondary);background:var(--rsi-surface);white-space:nowrap}
      .rsi-state-ok{color:var(--rsi-ok);border-color:color-mix(in srgb,var(--rsi-ok) 30%,transparent);
        background:color-mix(in srgb,var(--rsi-ok) 8%,transparent)}
      .rsi-state-muted{color:var(--rsi-muted)}
      .rsi-stage-body{padding:0 0 12px 41px}
      .rsi-card{border:1px solid var(--rsi-border);border-radius:var(--rsi-radius);padding:16px 18px;
        margin-bottom:14px;background:var(--rsi-surface);box-shadow:var(--rsi-shadow)}
      .rsi-kv{margin:0;display:grid;gap:8px}
      .rsi-kv-row{display:grid;grid-template-columns:104px minmax(0,1fr);gap:12px;font-size:12.5px;line-height:1.5}
      .rsi-kv-row dt{color:var(--dsw-alias-label-secondary)}
      .rsi-kv-row dd{margin:0;overflow-wrap:anywhere}
      .rsi-sub{margin-top:12px;padding-top:10px;border-top:1px solid var(--rsi-border)}
      .rsi-list-plain{margin:0;padding-left:18px;font-size:12.5px;line-height:1.6}
      .rsi-table-wrap{max-width:100%;overflow:auto;max-height:380px;border:1px solid var(--rsi-border);
        border-radius:10px;outline:none}
      .rsi-table-wrap:focus-visible{outline:2px solid var(--rsi-run);outline-offset:2px}
      .rsi-table{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px;min-width:460px}
      .rsi-caption{display:table-caption;width:100%;box-sizing:border-box;padding:10px 12px;text-align:left;
        font-size:11px;color:var(--dsw-alias-label-secondary);background:var(--rsi-surface);
        border-bottom:1px solid var(--rsi-border);white-space:normal}
      .rsi-table th,.rsi-table td{padding:8px 12px;border-bottom:1px solid var(--rsi-border);text-align:left}
      .rsi-table thead th{position:sticky;top:0;z-index:1;background:var(--rsi-surface-raised);
        color:var(--dsw-alias-label-secondary);font-weight:600}
      .rsi-table tbody th{font-weight:550;background:var(--rsi-surface)}
      .rsi-sample-cell{max-width:360px}
      .rsi-sample-id{display:block;font-weight:650}
      .rsi-sample-title{display:block;margin-top:2px;font-size:10.5px;line-height:1.35;font-weight:400;
        color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
      .rsi-explainer{margin:0 0 10px;font-size:11.5px;line-height:1.6;color:var(--dsw-alias-label-secondary)}
      .rsi-table tr:last-child th,.rsi-table tr:last-child td{border-bottom:0}
      .rsi-good{color:var(--rsi-ok);font-weight:600}
      .rsi-bad{color:var(--rsi-bad);font-weight:600}
      .rsi-muted{color:var(--rsi-muted)}
      .rsi-code-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
      .rsi-code{font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);font-size:11px;
        padding:2px 7px;border:1px solid var(--rsi-border);border-radius:5px;background:var(--rsi-surface)}
      .rsi-pre{margin:8px 0 0;padding:13px 14px;border:1px solid var(--rsi-border);border-radius:9px;
        font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);font-size:11.5px;
        line-height:1.65;white-space:pre-wrap;word-break:break-word;max-height:420px;overflow:auto;
        background:color-mix(in srgb,currentColor 3%,transparent)}
      .rsi-fold summary{cursor:pointer;font-size:12px;font-weight:600;color:var(--dsw-alias-label-primary)}
      .rsi-diff-wrap{margin-top:8px;border:1px solid var(--rsi-border);border-radius:9px;overflow:auto;
        max-height:360px;background:color-mix(in srgb,currentColor 3%,transparent)}
      .rsi-diff-lines{display:flex;flex-direction:column;min-width:max-content;
        font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);font-size:11.5px;line-height:1.6}
      .rsi-diff-line{padding:0 12px;white-space:pre}
      .rsi-diff-add{background:color-mix(in srgb,var(--rsi-ok) 12%,transparent);color:var(--rsi-ok)}
      .rsi-diff-del{background:color-mix(in srgb,var(--rsi-bad) 10%,transparent);color:var(--rsi-bad)}
      .rsi-diff-hunk{color:var(--rsi-run);background:color-mix(in srgb,var(--rsi-run) 7%,transparent)}
      .rsi-diff-meta{color:var(--dsw-alias-label-secondary)}
      .rsi-toolbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:10px}
      .rsi-fchip{border:1px solid var(--rsi-border);background:var(--rsi-surface);border-radius:999px;
        padding:3px 10px;font:inherit;font-size:11px;color:var(--dsw-alias-label-secondary);cursor:pointer}
      .rsi-fchip[aria-pressed="true"]{background:color-mix(in srgb,var(--rsi-run) 11%,transparent);
        color:var(--rsi-run);border-color:color-mix(in srgb,var(--rsi-run) 30%,transparent)}
      .rsi-events{list-style:none;margin:0;padding:0}
      .rsi-event{border-bottom:1px solid var(--rsi-border)}
      .rsi-event:last-child{border-bottom:0}
      .rsi-event-btn{display:grid;grid-template-columns:124px 66px minmax(0,1fr);gap:12px;width:100%;
        border:0;border-radius:7px;background:none;padding:9px 6px;cursor:pointer;
        text-align:left;color:inherit;font:inherit;font-size:12px}
      .rsi-event-btn:hover{background:color-mix(in srgb,currentColor 4%,transparent)}
      .rsi-event-at{font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);
        font-size:11px;color:var(--dsw-alias-label-secondary)}
      .rsi-event-kind{font-size:10.5px;color:var(--dsw-alias-label-secondary);text-align:left}
      .rsi-event-sum{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:550}
      .rsi-event-body{padding:0 6px 12px 202px}
      .rsi-text{margin:8px 0;font-size:12.5px;line-height:1.6;color:var(--dsw-alias-label-secondary)}
      .rsi-empty,.rsi-error{border:1px solid var(--rsi-border);border-radius:var(--rsi-radius);
        padding:26px;margin-top:18px;background:var(--rsi-surface);box-shadow:var(--rsi-shadow)}
      .rsi-empty-title,.rsi-error-title{font-size:15px;font-weight:680;margin-bottom:4px}
      .rsi-error-title{color:var(--rsi-bad)}
      .rsi-error-body{max-height:260px}
      .rsi-source{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:11px;
        color:var(--dsw-alias-label-secondary)}
      .rsi-badge{display:inline-flex;align-items:center;gap:5px}
      .rsi-dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--rsi-muted)}
      .rsi-dot-ok{background:var(--rsi-ok)} .rsi-dot-bad{background:var(--rsi-bad)}
      .rsi-dot-warn{background:var(--rsi-warn)} .rsi-dot-run{background:var(--rsi-run)}
      .rsi-dot-muted{background:var(--rsi-muted)}
      .rsi-actions{display:flex;gap:8px;margin-top:14px}
      .rsi-btn{border:1px solid var(--rsi-border);border-radius:8px;background:var(--rsi-surface);
        padding:6px 13px;font:inherit;font-size:12px;color:var(--dsw-alias-label-primary);cursor:pointer}
      .rsi-btn:hover{background:color-mix(in srgb,currentColor 6%,transparent)}
      .rsi-btn:focus-visible,.rsi-row:focus-visible,.rsi-tab:focus-visible,.rsi-stage-btn:focus-visible,
      .rsi-event-btn:focus-visible,.rsi-mode-btn:focus-visible,.rsi-fchip:focus-visible{
        outline:2px solid var(--rsi-run);outline-offset:2px}
      @container (max-width:860px){
        .rsi-body{grid-template-columns:1fr}
        .rsi-side{position:static;max-height:none}
        .rsi-list{max-height:240px;display:flex;gap:6px;overflow:auto;scroll-snap-type:x mandatory}
        .rsi-list li{min-width:230px;scroll-snap-align:start}
        .rsi-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
        .rsi-event-btn{grid-template-columns:104px 60px minmax(0,1fr)}
        .rsi-event-body{padding-left:6px}
      }
      @container (max-width:560px){
        .rsi-inner{padding:0 16px 36px}
        .rsi-head{padding:14px 0 12px}
        .rsi-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
        .rsi-table{display:block;width:100%;min-width:0}
        .rsi-caption{display:block;width:100%}
        .rsi-table thead{display:none}
        .rsi-table,.rsi-table tbody,.rsi-table tr,.rsi-table th,.rsi-table td{display:block}
        .rsi-table tr{border-bottom:1px solid var(--rsi-border);padding:9px 12px}
        .rsi-table tr:last-child{border-bottom:0}
        .rsi-table tbody th{background:none;padding:2px 0 6px;font-weight:650;max-width:none}
        .rsi-sample-title{white-space:normal}
        .rsi-table td{padding:2px 0;border:0;display:flex;justify-content:space-between;gap:12px}
        .rsi-table td::before{color:var(--dsw-alias-label-secondary);font-size:11px}
        .rsi-table td:nth-child(2)::before{content:"对照"}
        .rsi-table td:nth-child(3)::before{content:"候选"}
        .rsi-table td:nth-child(4)::before{content:"变化"}
        .rsi-stage-btn{grid-template-columns:28px minmax(0,1fr);align-items:start}
        .rsi-state-pill{grid-column:2;justify-self:start;margin-top:4px}
        .rsi-stage-copy{min-width:0}
        .rsi-stage-body{padding-left:39px}
        .rsi-event-btn{grid-template-columns:96px minmax(0,1fr)}
        .rsi-event-kind{grid-column:2;grid-row:2}
      }
      @container (max-width:420px){
        .rsi-strip{grid-template-columns:1fr}
      }
      @media (prefers-reduced-motion:no-preference){
        .rsi-row,.rsi-btn,.rsi-tab,.rsi-stage-btn,.rsi-event-btn,.rsi-fchip,.rsi-mode-btn{
          transition:background-color .16s ease,color .16s ease,border-color .16s ease}
      }
    `

    function insertStyles() {
      const tag = document.createElement('style')
      tag.dataset.rsiObservatory = 'true'
      tag.textContent = CSS
      document.head.appendChild(tag)
      return function dispose() { tag.remove() }
    }

    const plugin = {
      name: 'dsh-rsi-observatory',
      inject: ['slots', 'connection'],
      apply(ctx) {
        const slots = ctx.get('slots')
        if (slots === undefined) {
          console.error('[rsi-observatory] slots 服务不可用，界面不注册')
          return undefined
        }
        rpcCall = rpcFromCtx(ctx)
        const disposers = []
        try {
          disposers.push(ctx.effect(() => insertStyles(), 'rsi-observatory: styles'))
        } catch (error) {
          disposers.push(insertStyles())
        }
        try {
          disposers.push(ctx.effect(() => slots.inject('main', () => slots.register({
            name: 'main',
            key: PANEL_ID,
          }, Page)), 'rsi-observatory: main page'))
          disposers.push(ctx.effect(() => slots.inject('sidebar.panellist', () => slots.register({
            name: 'sidebar.panellist',
            id: PANEL_ID,
            order: 50,
            label: PANEL_LABEL,
          }, Icon)), 'rsi-observatory: sidebar icon'))
        } catch (error) {
          console.error('[rsi-observatory] 注册失败: ' + String((error && error.message) || error))
        }
        return function dispose() {
          for (const dispose of disposers) {
            try {
              if (typeof dispose === 'function') dispose()
            } catch (error) {
              // 一个卸不掉不阻塞其余
            }
          }
        }
      },
    }

    plugin.__test = {
      Page, ProposalDetail, CatalogList, EmptyState, ErrorState, SourceBar, SummaryStrip, StageTrack,
      DecisionPanel, RolloutBlock, SampleScores, ProposalPanel, HistoryList, Gaps, DetailTabs,
      decisionLabel, decisionTone, gapLabel, formatScore, formatCost, formatAt, pairedText,
      stageSummary, eventKinds,
    }

    return plugin
  },
})
