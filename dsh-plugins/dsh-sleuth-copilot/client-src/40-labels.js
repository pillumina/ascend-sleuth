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
      brand: 'var(--scp-accent)',
      success: 'var(--scp-ok)',
      warn: 'var(--scp-warn)',
      error: 'var(--scp-bad)',
      idle: 'var(--scp-idle)',
    }
    const REPORT_OUTCOME_TEXT = {
      from_report: { label: '按报告的修复解决', outcome: 'resolved' },
      other_way: { label: '换别的方法解决', outcome: 'resolved' },
      partial: { label: '部分解决', outcome: 'partial' },
      none: { label: '没解决', outcome: 'not_resolved' },
    }

