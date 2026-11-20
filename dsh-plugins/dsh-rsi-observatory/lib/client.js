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
    const PLUGIN_VERSION = '0.1.0'
    const PANEL_ID = 'rsi-observatory'
    const PANEL_LABEL = '实验台'

    const TABS = [
      { id: 'overview', label: '概览' },
      { id: 'proposal', label: '提案' },
      { id: 'events', label: '事件' },
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
      no_conclusion: '缺结论',
      no_cost: '缺成本',
      unknown_decision: '无判定',
      no_rollout: '缺执行记录',
      rolled_back: '已回滚',
      id_collision: '实验 id 复用',
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
      emptyBody: 'RSIStore 里还没有 experiment 事件。跑一次实验（experiment flow 或 experiment record）后回到这里刷新。',
      emptySource: '数据源',
      retry: '重试',
      refresh: '刷新',
      readOnly: '只读',
      experiments: '实验',
      proposals: '提案',
      noDetail: '选一条实验看明细。',
      noProposal: '这条事件里没有提案快照。',
      noEvents: '这条实验没有 history。',
      noStageFields: '这个阶段没有写进 store。',
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
      return value.toFixed(4)
    }

    function formatCost(conclusion) {
      const cost = conclusion && conclusion.cost
      if (!cost || typeof cost !== 'object') return '—'
      const tokens = cost.tokens
      if (tokens && typeof tokens === 'object') {
        const paired = typeof cost.paired === 'number' ? cost.paired : null
        return String(tokens.candidate) + ' tok' + (paired !== null ? ' · ' + paired + ' 对' : '')
      }
      if (typeof cost === 'number') return String(cost)
      return '—'
    }

    function formatAt(value) {
      const text = String(value || '')
      if (!text) return COPY.unknownTime
      return text.replace('T', ' ').replace(/(\+|Z).*$/, '')
    }

    function pairedText(paired) {
      if (!paired || typeof paired !== 'object') return '—'
      return 'b ' + String(paired.b) + ' · c ' + String(paired.c) + ' · n ' + String(paired.n)
    }

    function stageTone(stage) {
      return stage && stage.state === 'evidence' ? 'ok' : 'muted'
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
        h('div', { class: 'rsi-error-title' }, '取数失败'),
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
        source ? h('span', null, '数据源：' + String(source.backend || '') + ' · ' + String(source.path || source.base || '')) : null,
        generatedAt ? h('span', null, '生成于 ' + formatAt(generatedAt)) : null,
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
              'aria-current': String(selectedKey) === String(item.eventId) ? 'true' : 'false',
              onClick: function () { onSelect(String(item.eventId || '')) },
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
        { key: '判定', value: decisionLabel(experiment.decision), tone: decisionTone(experiment.decision) },
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
      if (!stages.length) return h('div', { class: 'rsi-text' }, '没有阶段记录。')
      return h('div', null,
        h('div', { class: 'rsi-section-head' },
          h('h3', { class: 'rsi-h3' }, '阶段'),
          h('span', { class: 'rsi-hint' }, '派生视图：有记录 = store 事件里能找到对应字段；不是时间线'),
        ),
        h('ol', { class: 'rsi-stages' }, stages.map(function (stage) {
          const open = String(openId) === String(stage.id)
          return h('li', { key: stage.id, class: 'rsi-stage' },
            h('button', {
              class: 'rsi-stage-btn', type: 'button',
              'aria-expanded': open ? 'true' : 'false',
              onClick: function () { onToggle(open ? '' : String(stage.id)) },
            },
            h(Dot, { tone: stageTone(stage) }),
            h('span', { class: 'rsi-stage-label' }, String(stage.label || stage.id)),
            h('span', { class: 'rsi-stage-state' }, stage.state === 'evidence' ? '有记录' : '无记录'),
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

    function DecisionPanel(props) {
      const conclusion = props.conclusion || {}
      const experiment = props.experiment || {}
      const gates = conclusion.metrics && conclusion.metrics.constraints
      const constraints = gates && typeof gates === 'object' ? gates : null
      const rows = [
        ['判定', decisionLabel(experiment.decision)],
        ['原因', String(conclusion.reason || '—')],
        ['配对', pairedText(experiment.paired)],
        ['p 值', conclusion.p_value === undefined || conclusion.p_value === null ? '—' : String(conclusion.p_value)],
        ['alpha_eff', conclusion.alpha_eff === undefined || conclusion.alpha_eff === null ? '—' : String(conclusion.alpha_eff)],
        ['均分', 'baseline ' + formatScore(experiment.baselineScore) + ' / candidate ' + formatScore(experiment.candidateScore)],
        ['成本', formatCost(conclusion)],
      ]
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '判定'),
        h('dl', { class: 'rsi-kv' }, rows.map(function (row) {
          return h('div', { class: 'rsi-kv-row', key: row[0] },
            h('dt', null, row[0]), h('dd', null, row[1]))
        })),
        constraints ? h('div', { class: 'rsi-sub' },
          h('h4', { class: 'rsi-h4' }, '约束检查'),
          h('ul', { class: 'rsi-list-plain' }, Object.keys(constraints).map(function (name) {
            const item = constraints[name] || {}
            return h('li', { key: name },
              String(name) + '：' + String(item.decision || '—')
                + (item.paired !== undefined ? ' · ' + String(item.paired) + ' 对' : ''),
            )
          })),
        ) : null,
      )
    }

    function RolloutBlock(props) {
      const rollout = props.rollout || {}
      const arms = rollout.arms && typeof rollout.arms === 'object' ? rollout.arms : {}
      const samples = Array.isArray(rollout.samples) ? rollout.samples : []
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '执行与回滚'),
        h('dl', { class: 'rsi-kv' },
          h('div', { class: 'rsi-kv-row' }, h('dt', null, 'arms'),
            h('dd', null, 'baseline ' + String(arms.baseline === undefined ? '—' : arms.baseline)
              + ' / candidate ' + String(arms.candidate === undefined ? '—' : arms.candidate))),
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '样本数'),
            h('dd', null, String(samples.length))),
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '工作区'),
            h('dd', null, String(rollout.workspace || '—'))),
          h('div', { class: 'rsi-kv-row' }, h('dt', null, '已回滚'),
            h('dd', null, rollout.rolled_back ? '是' : '否')),
        ),
        samples.length ? h('p', { class: 'rsi-hint' }, '样本：' + samples.slice(0, 12).join(' · ')
          + (samples.length > 12 ? ' …' : '')) : null,
        h('p', { class: 'rsi-hint' }, '逐样本成绩不在 RSIStore 事件里，这里只列样本编号与 arms 计数。'),
      )
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
        ['提案', String(proposal.id || '—')],
        ['target', String(proposal.target || '—')],
        ['范围', String(proposal.component || '—')],
        ['改动类型', String(proposal.artifact_kind || '—')],
        ['状态', String(proposal.status || '—')],
        ['预期', String(proposal.expected || '—')],
        ['风险', String(proposal.risk || '—')],
        ['回滚', String(proposal.rollback || '—')],
        ['已回滚', proposal.rolled_back ? '是' : '否'],
      ]
      return h('div', { class: 'rsi-card' },
        h('h3', { class: 'rsi-h3' }, '提案'),
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
        diff ? h('details', { class: 'rsi-fold' },
          h('summary', null, '改动 diff'),
          h('pre', { class: 'rsi-pre' }, diff),
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
        h('ul', { class: 'rsi-events', 'aria-label': '事件流' }, visible.map(function (row) {
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
      }, [selectedKey, sessionId, refreshTick])

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
              h('h1', { class: 'rsi-title' }, '实验台'),
              h('p', { class: 'rsi-sub' }, 'Ascend Sleuth · RSI 实验记录', ' · ', PLUGIN_VERSION),
            ),
          ),
          h(ErrorState, { message: error, onRefresh: refresh }),
        ))
      }

      const empty = phase === 'ready' && experiments.length === 0 && proposals.length === 0
      const active = experiments.find(function (item) { return String(item.eventId) === String(selectedKey) })
        || experiments[0]
      const conclusion = (detail && detail.conclusion) || {}
      const rollout = (detail && detail.rollout) || {}
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
            !active ? h('div', { class: 'rsi-text' }, COPY.noDetail) : h('div', null,
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
                        h(RolloutBlock, { rollout: rollout }),
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
            ),
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
        padding:0;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);
        font-family:var(--font-sans,ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif);
        --rsi-ok:#15803d;--rsi-bad:#b91c1c;--rsi-warn:#92400e;--rsi-run:#1d4ed8;--rsi-muted:#64748b;
        --rsi-hair:color-mix(in srgb,currentColor 12%,transparent);
        --rsi-surf:var(--dsw-alias-bg-layer-2,transparent)}
      body[data-ds-dark-theme] .rsi-page{
        --rsi-ok:#5cd68f;--rsi-bad:#fb8a8a;--rsi-warn:#fbbf24;--rsi-run:#7db3fc;--rsi-muted:#a8b0bd;
        --rsi-hair:color-mix(in srgb,#fff 14%,transparent)}
      .rsi-inner{max-width:1240px;margin:0 auto;padding:18px 20px 40px;box-sizing:border-box}
      .rsi-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap}
      .rsi-head-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
      .rsi-title{margin:0;font-size:20px;font-weight:700;letter-spacing:.2px}
      .rsi-sub{margin:3px 0 0;font-size:12px;color:var(--dsw-alias-label-secondary)}
      .rsi-body{display:grid;grid-template-columns:264px minmax(0,1fr);gap:18px;margin-top:16px;align-items:start}
      .rsi-side{min-width:0;border:1px solid var(--rsi-hair);border-radius:10px;padding:10px;background:var(--rsi-surf)}
      .rsi-mode{display:flex;gap:6px;margin-bottom:8px}
      .rsi-mode-btn{flex:1;padding:5px 8px;border:1px solid transparent;border-radius:999px;background:none;
        color:var(--dsw-alias-label-secondary);font-size:12px;cursor:pointer}
      .rsi-mode-btn[aria-pressed="true"]{background:var(--dsw-alias-bg-layer-3,color-mix(in srgb,currentColor 8%,transparent));
        color:var(--dsw-alias-label-primary);border-color:var(--rsi-hair)}
      .rsi-list{list-style:none;margin:0;padding:0;max-height:62vh;overflow:auto}
      .rsi-row{display:block;width:100%;text-align:left;border:0;border-radius:7px;background:none;
        padding:8px 9px;cursor:pointer;color:inherit}
      .rsi-row:hover{background:color-mix(in srgb,currentColor 6%,transparent)}
      .rsi-row[aria-current="true"]{background:color-mix(in srgb,currentColor 9%,transparent);
        box-shadow:inset 2px 0 0 var(--dsw-alias-brand-primary,var(--rsi-run))}
      .rsi-row-line{display:flex;align-items:center;gap:7px;min-width:0}
      .rsi-row-title{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-row-meta{display:block;margin-top:3px;font-size:11px;color:var(--dsw-alias-label-secondary);
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-list-empty{padding:14px 8px;font-size:12px;color:var(--dsw-alias-label-secondary)}
      .rsi-main{min-width:0}
      .rsi-exp-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap}
      .rsi-h2{margin:0;font-size:16px;font-weight:650;letter-spacing:-.01em}
      .rsi-meta{margin:4px 0 0;font-size:12px;color:var(--dsw-alias-label-secondary);word-break:break-all}
      .rsi-verdict{display:flex;align-items:center;gap:7px;font-size:13px}
      .rsi-hint{font-size:11px;color:var(--dsw-alias-label-secondary)}
      .rsi-gaps{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 0}
      .rsi-gap{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--rsi-hair);
        color:var(--rsi-warn)}
      .rsi-tabs{display:flex;gap:14px;margin:14px 0 0;border-bottom:1px solid var(--rsi-hair)}
      .rsi-tab{appearance:none;border:0;border-bottom:2px solid transparent;background:none;
        padding:7px 2px;font-size:13px;color:var(--dsw-alias-label-secondary);cursor:pointer}
      .rsi-tab[aria-selected="true"]{color:var(--dsw-alias-label-primary);
        border-bottom-color:var(--dsw-alias-brand-primary,var(--rsi-run));font-weight:600}
      .rsi-panel{padding:14px 0 0}
      .rsi-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--rsi-hair);
        border-radius:9px;overflow:hidden;margin-bottom:16px}
      .rsi-strip-cell{padding:10px 12px;border-left:1px solid var(--rsi-hair);min-width:0}
      .rsi-strip-cell:first-child{border-left:0}
      .rsi-k{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--dsw-alias-label-secondary)}
      .rsi-v{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:13px;font-weight:600;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-section-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin:0 0 6px}
      .rsi-h3{margin:0 0 8px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
        color:var(--dsw-alias-label-secondary);font-weight:600}
      .rsi-h4{margin:10px 0 5px;font-size:12px;font-weight:600}
      .rsi-stages{list-style:none;margin:0 0 16px;padding:0;border-top:1px solid var(--rsi-hair)}
      .rsi-stage{border-bottom:1px solid var(--rsi-hair)}
      .rsi-stage-btn{display:grid;grid-template-columns:10px minmax(0,1fr) auto;align-items:center;gap:9px;
        width:100%;border:0;background:none;padding:9px 2px;cursor:pointer;color:inherit;text-align:left}
      .rsi-stage-btn:hover{background:color-mix(in srgb,currentColor 5%,transparent)}
      .rsi-stage-label{font-size:13px;font-weight:600}
      .rsi-stage-state{font-size:11px;color:var(--dsw-alias-label-secondary)}
      .rsi-stage-body{padding:2px 0 10px 19px}
      .rsi-card{border:1px solid var(--rsi-hair);border-radius:9px;padding:12px 14px;margin-bottom:12px}
      .rsi-kv{margin:0;display:grid;gap:6px}
      .rsi-kv-row{display:grid;grid-template-columns:96px minmax(0,1fr);gap:10px;font-size:12.5px}
      .rsi-kv-row dt{color:var(--dsw-alias-label-secondary)}
      .rsi-kv-row dd{margin:0;overflow-wrap:anywhere}
      .rsi-sub{margin-top:8px}
      .rsi-list-plain{margin:0;padding-left:18px;font-size:12.5px}
      .rsi-code-list{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}
      .rsi-code{font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);font-size:11px;
        padding:1px 6px;border:1px solid var(--rsi-hair);border-radius:4px}
      .rsi-pre{margin:8px 0 0;padding:10px 12px;border:1px solid var(--rsi-hair);border-radius:7px;
        font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);font-size:11.5px;
        line-height:1.6;white-space:pre-wrap;word-break:break-word;max-height:420px;overflow:auto;
        background:color-mix(in srgb,currentColor 4%,transparent)}
      .rsi-fold summary{cursor:pointer;font-size:12px;color:var(--dsw-alias-label-secondary)}
      .rsi-toolbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:8px}
      .rsi-fchip{border:1px solid var(--rsi-hair);background:none;border-radius:999px;padding:2px 9px;
        font-size:11px;color:var(--dsw-alias-label-secondary);cursor:pointer}
      .rsi-fchip[aria-pressed="true"]{background:color-mix(in srgb,currentColor 9%,transparent);
        color:var(--dsw-alias-label-primary)}
      .rsi-events{list-style:none;margin:0;padding:0}
      .rsi-event{border-bottom:1px solid var(--rsi-hair)}
      .rsi-event-btn{display:grid;grid-template-columns:132px 54px minmax(0,1fr);gap:10px;width:100%;
        border:0;background:none;padding:7px 2px;cursor:pointer;text-align:left;color:inherit;font-size:12px}
      .rsi-event-btn:hover{background:color-mix(in srgb,currentColor 5%,transparent)}
      .rsi-event-at{font-family:var(--font-mono,ui-monospace,Menlo,Consolas,monospace);
        font-size:11px;color:var(--dsw-alias-label-secondary)}
      .rsi-event-kind{font-size:10.5px;color:var(--dsw-alias-label-secondary)}
      .rsi-event-sum{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rsi-event-body{padding:2px 0 10px}
      .rsi-text{margin:8px 0;font-size:12.5px;color:var(--dsw-alias-label-secondary)}
      .rsi-empty,.rsi-error{border:1px solid var(--rsi-hair);border-radius:9px;padding:22px;margin-top:16px}
      .rsi-empty-title,.rsi-error-title{font-size:14px;font-weight:650;margin-bottom:4px}
      .rsi-error-title{color:var(--rsi-bad)}
      .rsi-error-body{max-height:260px}
      .rsi-source{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:11px;
        color:var(--dsw-alias-label-secondary)}
      .rsi-badge{display:inline-flex;align-items:center;gap:5px}
      .rsi-dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--rsi-muted)}
      .rsi-dot-ok{background:var(--rsi-ok)} .rsi-dot-bad{background:var(--rsi-bad)}
      .rsi-dot-warn{background:var(--rsi-warn)} .rsi-dot-run{background:var(--rsi-run)}
      .rsi-dot-muted{background:var(--rsi-muted)}
      .rsi-actions{display:flex;gap:8px;margin-top:12px}
      .rsi-btn{border:1px solid var(--rsi-hair);border-radius:7px;background:none;padding:5px 12px;
        font-size:12px;color:var(--dsw-alias-label-primary);cursor:pointer}
      .rsi-btn:hover{background:color-mix(in srgb,currentColor 7%,transparent)}
      .rsi-btn:focus-visible,.rsi-row:focus-visible,.rsi-tab:focus-visible,.rsi-stage-btn:focus-visible,
      .rsi-event-btn:focus-visible,.rsi-mode-btn:focus-visible,.rsi-fchip:focus-visible{
        outline:2px solid var(--dsw-alias-brand-primary,var(--rsi-run));outline-offset:2px}
      @container (max-width:860px){
        .rsi-body{grid-template-columns:1fr}
        .rsi-list{max-height:220px;display:flex;gap:6px;overflow:auto}
        .rsi-list li{min-width:220px}
        .rsi-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
        .rsi-strip-cell:nth-child(3){border-left:0;border-top:1px solid var(--rsi-hair)}
        .rsi-strip-cell:nth-child(4){border-top:1px solid var(--rsi-hair)}
        .rsi-event-btn{grid-template-columns:104px 48px minmax(0,1fr)}
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
      Page, CatalogList, EmptyState, ErrorState, SourceBar, SummaryStrip, StageTrack,
      DecisionPanel, RolloutBlock, ProposalPanel, HistoryList, Gaps, DetailTabs,
      decisionLabel, decisionTone, gapLabel, formatScore, formatCost, formatAt, pairedText,
      eventKinds,
    }

    return plugin
  },
})
