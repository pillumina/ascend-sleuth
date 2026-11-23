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
      const formSeqRef = React.useRef(0)
      if (!formSeqRef.current) formSeqRef.current = ++formSeq
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
          const fieldId = 'scp-field-' + formSeqRef.current + '-' + field.name
          const hintId = fieldId + '-hint'
          if (field.type === 'select') {
            return h('label', { key: field.name, className: 'scp-field' }, label,
              h('select', {
                className: 'scp-select',
                id: fieldId,
                required: field.required ? true : undefined,
                'aria-describedby': field.hint ? hintId : undefined,
                autoFocus: field === firstVisible,
                value: values[field.name],
                onChange: (event) => change(field.name, event.target.value),
              },
                field.emptyValue && String(field.placeholder || '')
                  ? h('option', { value: '' }, field.placeholder)
                  : null,
                field.options.map((option) => h('option', { key: String(option.value), value: option.value }, option.label))),
              field.hint ? h('span', { className: 'scp-form-hint', id: hintId }, field.hint) : null)
          }
          if (field.type === 'textarea') {
            return h('label', { key: field.name, className: 'scp-field' }, label,
              h('textarea', {
                className: 'scp-textarea',
                id: fieldId,
                required: field.required ? true : undefined,
                'aria-describedby': field.hint ? hintId : undefined,
                rows: field.rows || undefined,
                autoFocus: field === firstVisible,
                value: values[field.name],
                placeholder: field.placeholder || '',
                onChange: (event) => change(field.name, event.target.value),
              }),
              field.hint ? h('span', { className: 'scp-form-hint', id: hintId }, field.hint) : null)
          }
          return h('label', { key: field.name, className: 'scp-field' }, label,
            h('input', {
              className: 'scp-input',
              type: 'text',
              id: fieldId,
              required: field.required ? true : undefined,
              'aria-describedby': field.hint ? hintId : undefined,
              autoFocus: field === firstVisible,
              value: values[field.name],
              placeholder: field.placeholder || '',
              onChange: (event) => change(field.name, event.target.value),
            }),
            field.hint ? h('span', { className: 'scp-form-hint', id: hintId }, field.hint) : null)
        }),
        preview ? h('div', { className: 'scp-preview' },
          h('span', { className: 'scp-preview-label' }, tr('form.preview')),
          h('pre', { className: 'scp-preview-text' }, preview)) : null,
        error || localError ? h('div', { className: 'scp-form-error', role: 'alert' }, error || localError) : null,
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
      const menuScrollRef = React.useRef(null)
      const [menuOverflow, setMenuOverflow] = React.useState(false)
      // 菜单内容超高时才给上下渐隐；是否超高按真实布局量，不按条目数猜（替身渲染拿不到尺寸时保持 false）。
      React.useEffect(() => {
        const el = menuScrollRef.current
        if (!el || typeof el.scrollHeight !== 'number' || !(el.clientHeight > 0)) return
        const next = el.scrollHeight > el.clientHeight + 1
        setMenuOverflow((prev) => (prev === next ? prev : next))
      })
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
            name: 'summary', type: 'textarea', rows: 6, label: tr('form.summary'), required: true,
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
            h('button', {
              type: 'button', className: 'scp-icon', 'aria-label': tr('action.closeMenu'),
              onClick: () => { if (onClose) onClose(); else setForm(null) },
            }, IconClose())),
          h(WriteForm, {
            form,
            row,
            busy,
            error,
            // 取消与右上关闭键同一语义：收起整个浮层。旧行为是退回「更多操作」列表，读者要点两次才关得掉。
            onCancel: () => { if (onClose) onClose(); else setForm(null) },
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
      if (row && ['resolved', 'escalated', 'archived'].includes(row.status)) {
        instructItems.push({
          key: 'sample',
          label: tr('action.addEval'),
          note: tr('action.addEvalNote'),
          onSelect: () => fillAndClose(sampleDraft(row)),
        })
      }
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
              { name: 'summary', type: 'textarea', rows: 6, label: tr('form.summary'), required: true, value: row.summary || '', placeholder: tr('form.summaryHint') },
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
              { name: 'summary', type: 'textarea', rows: 6, label: tr('form.summary'), required: true, value: row.summary || '', placeholder: tr('form.summaryHint') },
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
              { name: 'summary', type: 'textarea', rows: 6, label: tr('form.summary'), required: true, value: row.summary || '', placeholder: tr('form.summaryHint') },
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

      const copyItems = [{
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
      }]
      groups.push({ key: 'copy', title: tr('group.copy'), items: copyItems })

      const navItems = []
      const frequentItems = [{
        key: 'refresh',
        label: tr('action.refresh'),
        onSelect: () => {
          if (onClose) onClose()
          refresh(true)
        },
      }, {
        key: 'ledger',
        label: tr('action.ledger'),
        onSelect: () => {
          if (onClose) onClose()
          setPaletteOpen(true, row.sessionId)
        },
      }]
      groups.unshift({ key: 'frequent', title: tr('group.frequent'), items: frequentItems })
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
      if (navItems.length) groups.push({ key: 'nav', title: tr('group.nav'), items: navItems })

      return h('div', { className: 'scp-menu-scroll', ref: menuScrollRef, 'data-overflow': menuOverflow ? 'true' : 'false' },
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
            'data-danger': item.key === 'close:archived' ? 'true' : undefined,
            disabled: !!item.disabled,
            title: item.disabled ? disabledReason : undefined,
            onClick: item.onSelect,
          }, item.label, item.note ? h('span', { className: 'scp-menu-note' }, item.note) : null)))),
        error ? h('div', { className: 'scp-form-error', role: 'alert', style: { padding: '4px 6px' } }, error) : null,
        fallbackBlock())
    }

