    // ── 沉淀队列的小工具（只排版，不判状态；状态来自 sediment_state.py）──────
    const SED_CHIP_TONE = { warn: 'warn', bad: 'error', accent: 'brand', ok: 'success', gray: '' }
    const SED_DOT = { warn: 'var(--scp-warn)', bad: 'var(--scp-bad)', accent: 'var(--scp-accent)', ok: 'var(--scp-ok)', gray: 'var(--scp-muted)' }

    function sedGroupOf(draft) {
      const state = String((draft && draft.state) || '')
      if (state === 'decided') return 'pr'
      if (state === 'pr_closed') return 'groom'
      if (state === 'pr_open' || state === 'pr_merged') return 'check'
      if (state === 'pr_closed' || state === 'orphan' || state === 'done' || state === 'deferred' || state === 'rejected') return 'other'
      return 'groom'
    }

    // 决策枚举是记录里的机器值，展开视图里给人看时换成中文；未知值原样保留。
    function sedDecisionLabel(value) {
      const key = String(value || '')
      if (!key) return tr('label.none')
      const text = tr('sediment.decisionValue.' + key)
      return text && text !== 'sediment.decisionValue.' + key ? text : key
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
        { key: 'decided', label: tr('sediment.stepper.decided'), state: decisionValid ? 'done' : (state === 'need_decision' ? 'current' : 'unknown'), note: decisionValid && draft.decision ? sedDecisionLabel(draft.decision) : '' },
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

