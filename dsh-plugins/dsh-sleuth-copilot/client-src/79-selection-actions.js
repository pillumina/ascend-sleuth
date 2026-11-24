      // ── 所选范围的动作 ────────────────────────────────────────────────────
      // 动作按所选行的下一步计数；主操作取条数最多的那一个（并列时 PR 优先），
      // 不按固定顺序：否则选了一行 groom 就会把三行 PR 的主操作抢走。
      const selDiagRows = view === 'diagnosis' ? selRows : []
      const selDiagSed = selDiagRows.filter((item) => canStartSediment(item))
      const selDiagSample = selDiagRows.filter((item) => item
        && ['resolved', 'escalated', 'archived'].includes(item.status))
      const selDraftRows = view === 'sediment' ? selRows : []
      const selUndoRows = selDraftRows.filter((item) => item && item.undo && item.undo.available)
      const selKindRows = (kind) => selDraftRows.filter((item) => sedPrimaryKey(item) === kind)
      const selPrRows = selKindRows('pr')
      const selGroomRows = selKindRows('groom')
      const selCloseRows = selKindRows('close')
      const selRestoreRows = selKindRows('restore')
      const selCheckRows = selKindRows('check')
      const selPrimary = (() => {
        const candidates = [
          ['pr', selPrRows], ['check', selCheckRows], ['close', selCloseRows],
          ['restore', selRestoreRows], ['groom', selGroomRows],
        ]
        let best = null
        candidates.forEach(([kind, rowsOfKind]) => {
          if (rowsOfKind.length && (!best || rowsOfKind.length > best.rows.length)) {
            best = { kind, rows: rowsOfKind }
          }
        })
        return best
      })()
      const staleBlocked = Boolean(s.stale)

      function copySelList() {
        if (!selRows.length) { flash(tr('sel.copyEmpty')); return }
        const lines = selRows.map((item) => (view === 'diagnosis'
          ? String(item.sessionId || '') + ' · ' + caseTitle(item)
          : String(item.key || '') + ' · ' + String(item.title || '')))
        copyToClipboard(lines.join('\n')).then((ok) => flash(ok
          ? tr('sel.copyDone', { n: lines.length })
          : tr('hint.copyFailed')))
      }

      function runSelAction(kind) {
        if (kind === 'sediment') {
          if (staleBlocked) { flash(tr('sel.stale')); return }
          if (selDiagSed.length) openBatchSediment(selDiagSed)
          else copySelList()
          return
        }
        if (kind === 'sample') {
          if (selDiagSample.length) fillDraft(sampleBatchDraft(selDiagSample))
          else copySelList()
          return
        }
        if (kind === 'copy') { copySelList(); return }
        if (kind === 'invalid') { removeInvalidSelection(); return }
        if (kind === 'undo') {
          if (staleBlocked) { flash(tr('sel.stale')); return }
          openBatchUndo(selUndoRows)
          return
        }
        if (kind === 'check') {
          if (staleBlocked) { flash(tr('sel.stale')); return }
          // 按所选查会回写记录；只读档位下不生成整批指令冒充所选范围。
          if (canWrite) checkAllPrs(selCheckRows)
          else flash(tr('sel.writeReadonly'))
          return
        }
        if (kind === 'restore') {
          const text = selRestoreRows.map((item) => String(item.restore || '')).filter(Boolean).join('\n\n')
          if (text) fillDraft(text)
          else flash(tr('sediment.prompt.empty'))
          return
        }
        if (staleBlocked) { flash(tr('sel.stale')); return }
        openPrompt(kind, undefined, 'selected')
      }

      function runSelPrimary() {
        if (view === 'diagnosis') {
          if (staleBlocked && selDiagSed.length) { flash(tr('sel.stale')); return }
          if (selDiagSed.length) runSelAction('sediment')
          else if (selDiagSample.length) runSelAction('sample')
          else runSelAction('copy')
          return
        }
        if (!selPrimary) { copySelList(); return }
        runSelAction(selPrimary.kind)
      }

      function selPrimaryLabel() {
        if (view === 'diagnosis') {
          if (selDiagSed.length) return tr('sel.sedimentSelected', { n: selDiagSed.length })
          if (selDiagSample.length) return tr('sel.sampleSelected', { n: selDiagSample.length })
          return tr('sel.copyList')
        }
        if (!selPrimary) return tr('sel.copyList')
        const n = selPrimary.rows.length
        if (selPrimary.kind === 'pr') return tr('sel.prSelected', { n })
        if (selPrimary.kind === 'check') return tr('sel.checkSelected', { n })
        if (selPrimary.kind === 'close') return tr('sel.closeSelected', { n })
        if (selPrimary.kind === 'restore') return tr('sel.restoreSelected', { n })
        return tr('sel.groomSelected', { n })
      }

      const batchMenuItems = []
      if (view === 'diagnosis') {
        if (selDiagSed.length) {
          batchMenuItems.push({ key: 'sediment', label: tr('sel.sedimentSelected', { n: selDiagSed.length }), run: () => runSelAction('sediment') })
        }
        if (selDiagSample.length) {
          batchMenuItems.push({ key: 'sample', label: tr('sel.sampleSelected', { n: selDiagSample.length }), run: () => runSelAction('sample') })
        }
        batchMenuItems.push({ key: 'copy', label: tr('sel.copyList'), run: () => runSelAction('copy') })
      } else {
        const add = (kind, rowsOfKind, label) => {
          if (!rowsOfKind.length) return
          if (selPrimary && selPrimary.kind === kind) return
          batchMenuItems.push({ key: kind, label, run: () => runSelAction(kind) })
        }
        add('pr', selPrRows, tr('sel.prSelected', { n: selPrRows.length }))
        add('groom', selGroomRows, tr('sel.groomSelected', { n: selGroomRows.length }))
        add('check', selCheckRows, tr('sel.checkSelected', { n: selCheckRows.length }))
        add('close', selCloseRows, tr('sel.closeSelected', { n: selCloseRows.length }))
        add('restore', selRestoreRows, tr('sel.restoreSelected', { n: selRestoreRows.length }))
        if (selUndoRows.length) {
          batchMenuItems.push({ key: 'undo', label: tr('sel.undoSelected', { n: selUndoRows.length }), run: () => runSelAction('undo') })
        }
        batchMenuItems.push({ key: 'copy', label: tr('sel.copyList'), run: () => runSelAction('copy') })
      }
      if (invalidSel.length) {
        batchMenuItems.push({ key: 'invalid', label: tr('sel.removeInvalid'), run: () => runSelAction('invalid') })
      }

      // 回执里的「清空输入框」：面板只经 setDraft 写输入框，读不到里面现在是什么，
      // 所以先问一次；输入框在别的会话时不做假动作。
      function clearFilled() {
        const inputActions = findInputActions()
        if (!inputActions || typeof inputActions.setDraft !== 'function') {
          flash(tr('hint.noInput'))
          return
        }
        try {
          inputActions.setDraft('')
          store.sedimentForceNext = true
          setReceiptAsk(false)
          setReceipt(null)
          flash(tr('sel.receiptCleared'))
        } catch (error) {
          flash(tr('hint.failed', { message: String((error && error.message) || error) }))
        }
      }

      function copyReceiptLines() {
        if (!receipt || !receipt.lines) { flash(tr('sel.copyEmpty')); return }
        copyToClipboard(receipt.lines).then((ok) => flash(ok
          ? tr('sel.copyDone', { n: receipt.count || 0 })
          : tr('hint.copyFailed')))
      }

      // 批次指令填入后记一条回执：只写面板看得见的事（填了几份、什么时候、是否发送）。
      function notePromptReceipt(action, rowsList) {
        const lines = (rowsList || []).map((item) => (view === 'diagnosis'
          ? String(item.sessionId || '') + ' · ' + caseTitle(item)
          : String(item.key || '') + ' · ' + String(item.title || '')))
        setReceipt({
          kind: 'prompt',
          view,
          action,
          count: (rowsList || []).length,
          lines: lines.join('\n'),
          at: Date.now(),
        })
        setReceiptAsk(false)
      }

      const runSedPrimary = () => {
        if (sedBatchKind === 'none') return
        if (sedBatchKind === 'restore') {
          const text = String((sedDoc && sedDoc.prompts && sedDoc.prompts.restore) || '')
          if (text) fillDraft(text)
          else flash(tr('sediment.prompt.empty'))
          return
        }
        // 查合入不再生成指令：有写权限时直接查平台并回写记录，结果回到行里。
        if (sedBatchKind === 'check') {
          if (canWrite) checkAllPrs()
          else openPrompt('check', undefined, 'whole')
          return
        }
        if (sedBatchKind === 'close') {
          openPrompt('close', undefined, 'whole')
          return
        }
        openPrompt(sedPrimaryKind, undefined, 'whole')
      }

      // 混合队列在「待合入」以外的筛选下也留住查合入入口：主按钮会被 groom 占着。
      const sedCheckSecondary = sedPrOpen > 0 && sedBatchKind !== 'check'
        ? h('button', {
          type: 'button', className: 'scp-btn',
          title: tr('sediment.secondary.checkHint'),
          onClick: () => { if (canWrite) checkAllPrs(); else openPrompt('check', undefined, 'whole') },
        }, tr('sediment.primary.checkAll'))
        : null

      const allChecked = visibleRows.length > 0 && visibleSelected === visibleRows.length
      const someChecked = visibleSelected > 0 && !allChecked
      const batchSelectControl = (list) => {
        const ids = (list || []).map(idOfRow).filter(Boolean)
        const all = ids.length > 0 && ids.every((id) => selSet.has(id))
        const some = !all && ids.some((id) => selSet.has(id))
        return h('button', {
          type: 'button', className: 'scp-row-check', role: 'checkbox',
          'aria-checked': all ? 'true' : (some ? 'mixed' : 'false'),
          'data-mixed': some ? 'true' : 'false',
          'aria-label': tr('sel.allBatch', { n: ids.length }),
          tabIndex: -1,
          onClick: () => toggleBatchSelection(list),
        }, h('span', { className: 'scp-row-check-box', 'aria-hidden': 'true' }, all ? '✓' : ''))
      }

      const selectAllControl = h('button', {
        type: 'button',
        className: 'scp-row-check',
        role: 'checkbox',
        'aria-checked': allChecked ? 'true' : (someChecked ? 'mixed' : 'false'),
        'data-mixed': someChecked ? 'true' : 'false',
        'aria-label': tr('sel.all', { n: visibleRows.length }),
        tabIndex: -1,
        onClick: selectAllVisible,
      }, h('span', { className: 'scp-row-check-box', 'aria-hidden': 'true' }, allChecked ? '✓' : ''))

      const selChips = []
      if (outsideSel > 0) {
        selChips.push(h('span', { key: 'outside', className: 'scp-batch-chip', 'data-tone': 'gray' }, tr('sel.outside', { n: outsideSel })))
      }
      if (invalidSel.length) {
        selChips.push(h('span', { key: 'invalid', className: 'scp-batch-chip', 'data-tone': 'bad' }, tr('sel.invalid', { n: invalidSel.length })))
      }

      const receiptMine = receipt && (receipt.view || 'sediment') === view
      const receiptBar = receiptMine ? h('div', { className: 'scp-receipt' },
        h('span', { className: 'scp-receipt-strong' }, receipt.kind === 'write'
          ? (receipt.undone
            ? tr('sel.receiptRestored', { state: tr('sediment.prState.' + receipt.prev) })
            : tr('sel.receiptWrite', { label: receipt.label }))
          : tr('sel.receiptPrompt', { action: receipt.action, n: receipt.count })),
        receipt.kind === 'prompt'
          ? h('span', { className: 'scp-chip', 'data-tone': 'warn' }, tr('sel.receiptUnsent'))
          : null,
        h('span', { className: 'scp-spacer' }),
        receipt.kind === 'write' && !receipt.undone
          ? h('button', {
            type: 'button', className: 'scp-btn', disabled: checkBusy === receipt.key,
            onClick: undoMark,
          }, tr('sel.receiptUndo'))
          : null,
        receipt.kind === 'prompt'
          ? (receiptAsk
            ? h('span', { key: 'ask', className: 'scp-batch-note' }, tr('sel.receiptClearAsk'))
            : null)
          : null,
        receipt.kind === 'prompt'
          ? (receiptAsk
            ? h('button', { key: 'yes', type: 'button', className: 'scp-btn', onClick: clearFilled }, tr('sel.receiptClearYes'))
            : h('button', { key: 'clear', type: 'button', className: 'scp-btn', onClick: () => setReceiptAsk(true) }, tr('sel.receiptClear')))
          : null,
        receipt.kind === 'prompt' && receiptAsk
          ? h('button', { key: 'no', type: 'button', className: 'scp-btn scp-btn--ghost', onClick: () => setReceiptAsk(false) }, tr('sediment.prompt.cancel'))
          : null,
        receipt.kind === 'prompt'
          ? h('button', { type: 'button', className: 'scp-btn scp-btn--ghost', onClick: copyReceiptLines }, tr('sel.receiptCopy'))
          : null,
        h('button', {
          type: 'button', className: 'scp-btn scp-btn--ghost', 'aria-label': tr('sel.receiptDismiss'),
          onClick: () => { setReceipt(null); setReceiptAsk(false) },
        }, '×')) : null

      const batchMenuEl = batchMenu ? h('div', { className: 'scp-batch-menu', 'data-batch-menu': 'true' },
        batchMenuItems.length
          ? batchMenuItems.map((item) => h('button', {
            key: item.key, type: 'button', className: 'scp-batch-item',
            onClick: () => { setBatchMenu(false); item.run() },
          }, item.label))
          : h('div', { className: 'scp-batch-empty' }, tr('sel.menuEmpty'))) : null

      const primaryBlocked = staleBlocked && (view === 'sediment' || selDiagSed.length > 0)
      const checkingLabel = checkBusy === '__all__' && checkRun && checkRun.active && checkRun.total > 0
        ? tr('sel.checkingSelected', { n: Math.min(checkRun.seen, checkRun.total), m: checkRun.total })
        : ''
      // 选择态分两档：已勾选（给范围与动作）与刚进入（给全选 / 退出，不摆一个按不动的主按钮）。
      const noSelectionYet = selectedCount === 0
      const selBar = h('div', {
        className: 'scp-batch', 'data-kind': 'selection', role: 'group',
        'aria-label': noSelectionYet ? tr('sel.emptyTitle') : tr('sel.count', { n: selectedCount }),
      },
        h('div', { className: 'scp-batch-line' },
          noSelectionYet ? null : selectAllControl,
          h('span', { className: 'scp-batch-strong' },
            noSelectionYet ? tr('sel.emptyTitle') : tr('sel.count', { n: selectedCount })),
          h('span', { className: 'scp-batch-note' },
            noSelectionYet ? tr('sel.emptyHint') : tr('sel.inFilter', { n: selVisibleRows.length })),
          noSelectionYet ? null : selChips),
        h('div', { className: 'scp-batch-line' },
          noSelectionYet
            ? h('button', {
              type: 'button', className: 'scp-btn', onClick: selectAllVisible,
            }, tr('sel.allVisible'))
            : h('button', {
              type: 'button', className: 'scp-btn scp-btn--ghost',
              onClick: () => setOnlySel((current) => Object.assign({}, current, { [view]: !current[view] })),
            }, onlySelOn ? tr('sel.showAll') : tr('sel.only')),
          staleBlocked
            ? h('span', { className: 'scp-batch-note', style: { color: 'var(--scp-warn)' } }, tr('sel.stale'))
            : null,
          h('span', { className: 'scp-spacer' }),
          noSelectionYet
            ? h('button', {
              type: 'button', className: 'scp-btn scp-btn--ghost', onClick: clearSelection,
            }, tr('sel.exit'))
            : h('button', {
              type: 'button', className: 'scp-btn scp-btn--primary',
              disabled: primaryBlocked || checkBusy === '__all__',
              onClick: runSelPrimary,
            }, checkingLabel || selPrimaryLabel()),
          noSelectionYet
            ? null
            : h('button', {
              type: 'button', className: 'scp-btn', 'data-batch-menu': 'true',
              onClick: () => setBatchMenu((value) => !value),
            }, tr('sel.more') + ' ▾'),
          noSelectionYet ? null : batchMenuEl))

      const sedWholeBatch = h('div', { className: 'scp-batch' },
        h('div', { className: 'scp-batch-line' },
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
            : null),
        h('div', { className: 'scp-batch-line' },
          h('span', { className: 'scp-spacer' }),
          sedDecided > 0 && sedBatchKind !== 'pr'
            ? h('button', {
              type: 'button', className: 'scp-btn',
              onClick: () => openPrompt('pr', undefined, 'whole'),
            }, tr('sediment.secondary.pr', { n: sedDecided }))
            : null,
          sedCheckSecondary,
          h('button', {
            type: 'button',
            className: 'scp-btn scp-btn--primary',
            disabled: sedBatchKind === 'none' || checkBusy === '__all__',
            onClick: runSedPrimary,
          }, checkBusy === '__all__'
            ? (checkRun && checkRun.active && checkRun.total > 0
              ? tr('sediment.checkingProgress', {
                n: Math.min(checkRun.seen, checkRun.total),
                m: checkRun.total,
              })
              : tr('sediment.refreshing'))
            : sedPrimaryLabel),
          sedUndoRows.length >= 2
            ? h('button', {
              type: 'button', className: 'scp-btn scp-btn--ghost',
              title: tr('sediment.undo.batchHint'),
              onClick: () => openBatchUndo(),
            }, tr('sediment.undo.batchAction', { n: sedUndoRows.length }))
            : null))

      // 诊断视图的批量沉淀：未选时范围是当前筛选里能起沉淀的单（任何筛选都出现，不再绑「可沉淀」）；
      // 已选时范围是选择集，主操作写「沉淀所选 n 单」。都只生成指令，不写 trace 与知识库。
      const diagWholeBatch = diagSedentable.length ? h('div', {
        className: 'scp-batch', 'data-kind': 'sediment-batch', role: 'group', 'aria-label': tr('diag.batch.fill'),
      },
        h('div', { className: 'scp-batch-line' },
          batchSelectControl(diagSedentable),
          h('span', { className: 'scp-batch-strong' }, tr('diag.batch.count', { n: diagSedentable.length })),
          h('span', { className: 'scp-batch-chip', 'data-tone': 'gray' }, tr('sel.scopeAll')),
          h('span', { className: 'scp-batch-age' }, tr('diag.batch.scope')),
          searchText.trim() ? h('span', { className: 'scp-batch-chip', 'data-tone': 'gray' }, tr('diag.batch.search', { q: searchText.trim() })) : null,
          data && data.capabilities && data.capabilities.canWrite === false
            ? h('span', { className: 'scp-batch-chip', 'data-tone': 'warn' }, tr('diag.batch.readonly'))
            : null),
        h('div', { className: 'scp-batch-line' },
          h('span', { className: 'scp-spacer' }),
          h('button', {
            type: 'button',
            className: 'scp-btn scp-btn--primary',
            onClick: () => openBatchSediment(),
          }, tr('diag.batch.fillCount', { n: diagSedentable.length })))) : null

      const selActive = selectedCount > 0 || selectingOn
      const sedBatch = view === 'sediment' ? (selActive ? selBar : sedWholeBatch) : null
      const diagBatch = view === 'diagnosis' ? (selActive ? selBar : diagWholeBatch) : null

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
                  h('span', { className: 'scp-sed-history-line' },
                    h('span', { className: 'scp-sed-history-title', title: item.title || item.key }, item.title || item.key),
                    item.at ? h('span', { className: 'scp-sed-history-time' }, formatTime(item.at) || item.at) : null),
                  h('span', { className: 'scp-sed-meta' },
                    h('span', { className: 'scp-chip' }, item.state === 'knowledge' ? tr('sediment.stepper.promoted') : tr('sediment.history.archived')),
                    item.pr && item.pr.url && /^https?:\/\//i.test(String(item.pr.url))
                      ? h('a', {
                        className: 'scp-link scp-sed-history-pr', href: String(item.pr.url), target: '_blank',
                        rel: 'noopener noreferrer', title: String(item.pr.url),
                      }, (item.pr.number ? '#' + item.pr.number : tr('sediment.detail.pr')) + ' ↗')
                      : null))))
              : null)
          : visibleRows.length === 0
            ? h('div', { className: 'scp-pal-empty' }, tr('sediment.emptyFiltered'))
            : (() => {
              const order = ['groom', 'pr', 'check', 'other']
              const labels = {
                groom: tr('sediment.group.groom'),
                pr: tr('sediment.group.pr'),
                check: tr('sediment.group.check'),
                other: tr('sediment.group.other'),
              }
              const grouped = {}
              visibleRows.forEach((draft, index) => {
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
                  const prShared = draft.pr ? (sedPrCounts[sedPrKey(draft)] || 0) : 0
                  const checked = selSet.has(String(draft.key || ''))
                  // 查合入进行中：已到的行显示状态或失败原因，还没到的标「查询中」。
                  const runState = checkRun && checkRun.states ? checkRun.states[draft.key] : null
                  const runPending = !runState && checkRun && checkRun.active
                    && checkRun.targets && checkRun.targets[draft.key] === true
                  const rowButton = h('button', {
                    key: 'row',
                    type: 'button',
                    className: 'scp-sed-row',
                    'data-on': index === sedSel ? 'true' : 'false',
                    'data-sel': checked ? 'true' : 'false',
                    onFocus: () => { if (sedSel !== index) setSedSel(index) },
                    onClick: (event) => {
                      const e = event || {}
                      if (e.shiftKey) toggleRowSelection(draft, index, 'range')
                      else if (e.metaKey || e.ctrlKey) toggleRowSelection(draft, index, 'toggle')
                      setSedSel(index)
                    },
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
                        // 待合入 / 已关闭的行遇到评估过期：阶段仍跟平台状态，过期只在行内提示。
                        // 已合入的行不给：下一步是收尾，过期没有对应动作。
                        (draft.state === 'pr_open' || draft.state === 'pr_closed') && draft.stale
                          ? h('span', {
                            className: 'scp-chip',
                            'data-tone': 'warn',
                            title: (draft.staleReasons || []).join('；'),
                          }, tr('sediment.row.stale'))
                          : null,
                        draft.pr && draft.pr.number
                          ? h('span', { className: 'scp-chip' }, '#' + draft.pr.number)
                          : null,
                        prShared > 1
                          ? h('span', { className: 'scp-chip', title: tr('sediment.prSharedHint', { n: prShared }) }, tr('sediment.prShared', { n: prShared }))
                          : null,
                        runState
                          ? h('span', {
                            className: 'scp-chip',
                            'data-tone': runState.ok ? 'success' : 'error',
                            title: runState.ok ? (runState.checkedAt || '') : (runState.message || ''),
                          }, runState.ok
                            ? tr('sediment.prState.' + runState.state)
                            : checkErrorText(runState.error))
                          : (runPending
                            ? h('span', { className: 'scp-chip', 'data-tone': 'brand' }, tr('sediment.checking'))
                            : null),
                        draft.decision
                          ? h('span', {}, sedDecisionLabel(draft.decision))
                          : (draft.novelty ? h('span', {}, sedDecisionLabel(draft.novelty) + (draft.confidence ? ' · ' + draft.confidence : '')) : null),
                        draft.source && draft.source.sessionId
                          ? h('span', {}, draft.source.sessionId)
                          : null)))
                  return h('div', { key: draft.key, className: 'scp-row-wrap scp-row-wrap--sed' },
                    h('button', {
                      key: 'check',
                      type: 'button',
                      className: 'scp-row-check',
                      role: 'checkbox',
                      'aria-checked': checked ? 'true' : 'false',
                      'aria-label': tr('sel.check', { title: draft.title || draft.key }),
                      tabIndex: -1,
                      onClick: (event) => {
                        const e = event || {}
                        if (typeof e.stopPropagation === 'function') e.stopPropagation()
                        toggleRowSelection(draft, index, e.shiftKey ? 'range' : 'toggle')
                      },
                    }, h('span', { className: 'scp-row-check-box', 'aria-hidden': 'true' }, checked ? '✓' : '')),
                    rowButton)
                })))
            })()

      const sedList = h('div', {
        className: 'scp-pal-list', role: 'region',
        'aria-label': tr('palette.sedimentTitle'), 'data-selecting': selectingOn ? 'true' : 'false',
      },
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
          }, item.label, h('b', {}, String(item.n)))), selectingOn ? null : selectToggle),
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
        ? (sedDoc && sedSorted.length === 0 ? null : h('div', { className: 'scp-pal-empty' },
          h('span', {}, sedDoc ? tr('sediment.empty') : tr('palette.loading'))))
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
              h('dd', {}, [sedPick.novelty ? sedDecisionLabel(sedPick.novelty) : tr('label.none'), sedPick.confidence || '', sedPick.candidate ? '(' + sedPick.candidate + ')' : ''].filter(Boolean).join(' '))),
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
              h('dt', {}, tr('sediment.detail.decisionValue')), h('dd', {}, sedDecisionLabel(sedPick.decision))))
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
            ? ['#' + sedPick.pr.number, prStateLabel, prSourceLabel, prChecked].filter(Boolean).join(' · ')
            : tr('sediment.detail.noPr')
          const prUrl = sedPick.pr && sedPick.pr.url ? String(sedPick.pr.url) : ''
          const prSharedCount = sedPick.pr ? (sedPrCounts[sedPrKey(sedPick)] || 0) : 0
          blocks.push(h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-section-label' }, tr('sediment.detail.promotion')),
            h('div', { className: 'scp-sed-kv' },
              h('div', { className: 'scp-sed-kv-row' }, h('dt', {}, tr('sediment.detail.case')), h('dd', {}, landing)),
              h('div', { className: 'scp-sed-kv-row' }, h('dt', {}, tr('sediment.detail.pr')),
                h('dd', {}, prText,
                  prUrl ? h('a', { className: 'scp-sed-link', href: prUrl, target: '_blank', rel: 'noopener noreferrer' }, prUrl) : null,
                  prSharedCount > 1
                    ? h('span', { className: 'scp-sed-hint' }, tr('sediment.detail.prShared', { n: prSharedCount }))
                    : null)))))

          const prRowBusy = checkBusy === sedPick.key || checkBusy === '__all__'
          const prActionButtons = sedPick.pr ? [
            h('button', {
              key: 'check', type: 'button', className: 'scp-btn',
              disabled: prRowBusy,
              // 只读档位不写记录，但可以生成查证指令；与批次条和 Enter 的行为一致。
              title: canWrite ? undefined : tr('sediment.check.readonly'),
              onClick: () => { if (canWrite) checkPr(sedPick.key); else openPrompt('check', undefined, 'single') },
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
          head.push(h('div', { key: 'title', className: 'scp-pal-titlecase', title: sedPick.title || sedPick.key }, sedPick.title || sedPick.key))
          // 抬头与诊断详情一致：一行识别信息 + 正文层的问题背景，不把首句放大加粗。
          // 来源诊断显示 trace 单号，跳的是它记的 harness 会话号；两个值不同，单号不在会话列表里。
          const sedSourceTrace = sedPick.source ? String(sedPick.source.sessionId || '') : ''
          const sedSourceSession = sedPick.source ? String(sedPick.source.harnessSession || '') : ''
          head.push(h('div', { key: 'identity', className: 'scp-identity' },
            h('span', { className: 'scp-badge', 'data-tone': SED_CHIP_TONE[sedPick.stageTone] || 'none' }, sedPick.stage || sedPick.state),
            sedPick.novelty ? h('span', { className: 'scp-chip' }, sedDecisionLabel(sedPick.novelty) + (sedPick.confidence ? ' · ' + sedPick.confidence : '')) : null,
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
          if (sedPick.prBroken) {
            head.push(h('div', { key: 'prBroken', className: 'scp-sed-hint' }, tr('sediment.detail.prBroken')))
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
            // PR 行标「评估过期」，原因后补一句合入前复核怎么办；需要重跑的行（含批准失效）
            // 阶段已经是「需重跑」，标签沿用「已评估」，具体原因由文字给出。
            const staleReasonsText = (sedPick.staleReasons || []).join('；')
            const stalePrState = sedPick.state === 'pr_open' || sedPick.state === 'pr_closed'
            const staleText = sedPick.state === 'pr_open'
              ? [staleReasonsText, tr('sediment.detail.stalePrNote')].filter(Boolean).join('；')
              : staleReasonsText
            head.push(h('div', { key: 'stale', className: 'scp-callout', style: { background: 'var(--scp-bad-soft)', borderColor: 'color-mix(in srgb, var(--scp-bad) 26%, var(--scp-border))' } },
              h('span', { className: 'scp-callout-label' }, tr(stalePrState ? 'sediment.detail.staleLabel' : 'sediment.stepper.assessed')),
              h('span', { className: 'scp-callout-text' }, staleText)))
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
      const scopedActive = !!(scopedPrompt && scopedPrompt.kind === promptKind)
      const promptText = isBatchPrompt
        ? String(batchSed.text || '')
        : (isFallbackPrompt
          ? String(promptFallback.text || '')
          : (promptKind && (scopedActive
            ? (scopedPrompt.prompts && scopedPrompt.prompts[promptKind] ? String(scopedPrompt.prompts[promptKind]) : '')
            : (sedDoc && sedDoc.prompts ? String(sedDoc.prompts[promptKind] || '') : ''))))
      const promptDetail = isBatchPrompt || isFallbackPrompt
        ? ''
        : (promptKind && (scopedActive
          ? (scopedPrompt.prompts && scopedPrompt.prompts[promptKind + 'Detail'] ? String(scopedPrompt.prompts[promptKind + 'Detail']) : '')
          : (sedDoc && sedDoc.prompts ? String(sedDoc.prompts[promptKind + 'Detail'] || '') : '')))

      function promptFillMeta() {
        if (isBatchPrompt && batchSed && batchSed.rows) {
          return { receipt: { action: tr('sel.sedimentSelected', { n: batchSed.rows.length }), rows: batchSed.rows } }
        }
        if (isFallbackPrompt && promptFallback && promptFallback.rows) {
          return { receipt: { action: promptFallback.head || tr('sediment.undo.batchTitle'), rows: promptFallback.rows } }
        }
        if (scopedActive && selDraftRows.length) {
          return { receipt: { action: promptTitle[promptKind] || promptKind, rows: selDraftRows } }
        }
        return undefined
      }
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
                ? tr(batchSed.selection ? 'diag.batch.subSelected' : 'diag.batch.sub', { n: batchSed.count || 0 })
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
            scopedActive && scopedPrompt.loading
              ? h('div', { className: 'scp-sed-hint' }, tr('sel.scopedLoading'))
              : null,
            scopedActive && scopedPrompt.error
              ? h('div', { className: 'scp-form-error', role: 'alert' }, tr('sel.scopedFailed', { reason: scopedPrompt.error }))
              : null,
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
              type: 'button', className: 'scp-btn scp-btn--primary',
              disabled: !promptText || (scopedActive && scopedPrompt.loading),
              onClick: () => { if (promptText) { const meta = promptFillMeta(); closePrompt(); fillDraft(promptText, meta) } },
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
                  'aria-pressed': targetRemote === name ? 'true' : 'false',
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
                'aria-label': tr('sediment.target.base'),
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

      // 人工兜底：平台一直查不到时，按人确认把 PR 状态写进本地记录（source=manual）。
      const manualModal = manualOpen && sedPick ? h('div', {
        className: 'scp-veil',
        onMouseDown: (event) => { if (event.target === event.currentTarget) setManualOpen(false) },
      },
        h('div', {
          className: 'scp-modal', style: { width: 'min(520px, calc(100% - 40px))' },
          role: 'dialog', 'aria-modal': 'true', 'aria-label': tr('sediment.manualTitle'), tabIndex: -1, ref: manualRef,
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
              'aria-pressed': ((sedPick.pr && sedPick.pr.state) || 'unknown') === state ? 'true' : 'false',
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

      const subParts = loadFailed
        ? [tr('palette.loadFailed')]
        : loading
          ? [tr('palette.reading')]
          : [tr('palette.count', { n: rows.length })]
      if (data && Number(counts.pendingFeedback) > 0) subParts.push(tr('queue.pending', { n: Number(counts.pendingFeedback) }))

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
          'data-cmd': cmdOpen ? 'true' : 'false',
        },
          h('div', { className: 'scp-pal-top' },
            h('div', { className: 'scp-pal-heading' },
              h('span', { className: 'scp-pal-title' }, view === 'sediment' ? tr('palette.sedimentTitle') : tr('palette.title')),
              h('span', { className: 'scp-pal-sub' }, view === 'sediment'
                ? [tr('sediment.batch.total', { n: sedDrafts.length }), sedTargetHint].join(' · ')
                : subParts.join(' · '))),
            h('div', {
              className: 'scp-views', role: 'tablist', 'aria-label': tr('palette.title'),
              onKeyDown: (event) => {
                if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
                event.preventDefault()
                const next = view === 'diagnosis' ? 'sediment' : 'diagnosis'
                setMenuOpen(false); setMenuForm(null); setPaletteView(next)
                const node = next === 'diagnosis' ? diagTabRef.current : sedTabRef.current
                if (node && typeof node.focus === 'function') { try { node.focus() } catch { /* 同上 */ } }
              },
            },
              h('button', {
                type: 'button', role: 'tab', ref: diagTabRef,
                id: 'scp-tab-diagnosis', 'aria-controls': 'scp-pal-panel',
                tabIndex: view === 'diagnosis' ? 0 : -1,
                className: 'scp-view-tab',
                'aria-selected': view === 'diagnosis' ? 'true' : 'false',
                'data-on': view === 'diagnosis' ? 'true' : 'false',
                onClick: () => { setMenuOpen(false); setMenuForm(null); setPaletteView('diagnosis') },
              }, tr('palette.view.diagnosis'), h('b', {}, loadFailed ? '—' : loading ? '…' : String(rows.length))),
              h('button', {
                type: 'button', role: 'tab', ref: sedTabRef,
                id: 'scp-tab-sediment', 'aria-controls': 'scp-pal-panel',
                tabIndex: view === 'sediment' ? 0 : -1,
                className: 'scp-view-tab',
                'aria-selected': view === 'sediment' ? 'true' : 'false',
                'data-on': view === 'sediment' ? 'true' : 'false',
                onClick: () => { setMenuOpen(false); setMenuForm(null); setPaletteView('sediment') },
              }, tr('palette.view.sediment'), h('b', {}, String(sedDrafts.length)))),
            h('button', {
              type: 'button', className: 'scp-icon', 'aria-label': tr('palette.close'), title: tr('palette.close'),
              onClick: () => setPaletteOpen(false),
            }, IconClose())),
          s.stale ? h('div', { className: 'scp-pal-notice', role: 'status', title: s.staleMessage || '' },
            h('span', { className: 'scp-pal-notice-text' }, tr('hint.stale', { time: formatTime(store.lastOkAt) || tr('none') })),
            h('button', { type: 'button', className: 'scp-btn scp-btn--ghost', onClick: () => refresh(true) }, tr('action.refresh'))) : null,
          loadFailed ? null : sedBatch,
          loadFailed ? null : diagBatch,
          loadFailed ? null : receiptBar,
          loadFailed
            ? h('div', {
              className: 'scp-pal-main scp-pal-main--empty',
              id: 'scp-pal-panel', role: 'tabpanel', 'aria-labelledby': view === 'sediment' ? 'scp-tab-sediment' : 'scp-tab-diagnosis',
            },
              h('div', { className: 'scp-pal-error scp-pal-error--center' },
                h('div', { className: 'scp-pal-error-title' }, tr('palette.unavailable', { message: (s.data && s.data.message) || s.message || '' })),
                h('button', { type: 'button', className: 'scp-btn', onClick: () => refresh(true) }, tr('action.retry'))))
            : data && view === 'diagnosis' && rows.length === 0
              ? h('div', {
                className: 'scp-pal-main scp-pal-main--empty',
                id: 'scp-pal-panel', role: 'tabpanel', 'aria-labelledby': view === 'sediment' ? 'scp-tab-sediment' : 'scp-tab-diagnosis',
              },
                h('div', { className: 'scp-pal-empty' }, emptyMark, tr('palette.emptyAll'),
                  h('button', { type: 'button', className: 'scp-btn', onClick: () => refresh(true) }, tr('action.refresh'))))
              : h('div', {
                className: 'scp-pal-main',
                id: 'scp-pal-panel', role: 'tabpanel', 'aria-labelledby': view === 'sediment' ? 'scp-tab-sediment' : 'scp-tab-diagnosis',
              }, view === 'sediment' ? sedList : list, view === 'sediment' ? sedSide : side),
          h('div', { className: 'scp-pal-foot' },
            loadFailed ? null : h('span', { className: 'scp-foot-hints' },
              h('span', { className: 'scp-kbd' }, '↑'),
              h('span', { className: 'scp-kbd' }, '↓'),
              ' 选择 · ',
              h('span', { className: 'scp-kbd' }, 'Enter'),
              ' 主操作 · ',
              h('span', { className: 'scp-kbd' }, '/'),
              ' 搜索 · ',
              view === 'diagnosis' ? h('span', { className: 'scp-kbd' }, shortcutKeys('command')) : null,
              view === 'diagnosis' ? ' 命令 · ' : null,
              selectedCount ? h('span', { className: 'scp-kbd' }, 'Cmd/Ctrl+Z') : null,
              selectedCount ? ' 撤销选择 · ' : null,
              selectingOn && !selectedCount ? h('span', { className: 'scp-kbd' }, 'Space') : null,
              selectingOn && !selectedCount ? ' 勾选 · ' : null,
              h('span', { className: 'scp-kbd' }, 'Esc'),
              selectedCount ? ' 清空选择' : (selectingOn ? ' 退出选择' : ' 关闭')),
            h('span', { className: 'scp-spacer' }),
            view === 'sediment' ? h('span', { className: 'scp-foot-note' }, sedTargetHint) : null,
            h('span', { className: 'scp-version' }, 'v' + PLUGIN_VERSION)),
          actionMenu,
          promptModal,
          targetModal,
          manualModal,
          cmdOpen ? h('div', {
            className: 'scp-cmd-backdrop',
            onMouseDown: (event) => { if (event.target === event.currentTarget) setCmdOpen(false) },
          },
            h('div', { className: 'scp-cmd', role: 'dialog', 'aria-modal': 'true', 'aria-label': tr('cmd.placeholder'), ref: cmdRef },
              h('div', { className: 'scp-cmd-where' }, tr('cmd.where') + (row ? caseTitle(row) : '')),
              h('input', {
                ref: cmdInputRef, value: cmdQuery, placeholder: tr('cmd.placeholder'),
                role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'scp-cmd-list',
                'aria-activedescendant': 'scp-cmd-' + cmdIndex,
                'aria-label': tr('cmd.placeholder'),
                onChange: (event) => { setCmdQuery(event.target.value); setCmdIndex(0) },
              }),
              h('div', { className: 'scp-cmd-list', role: 'listbox', id: 'scp-cmd-list' },
                commandList.length
                  ? commandList.flatMap((item, index) => {
                    const rows = []
                    if (index === 0 || commandList[index - 1].group !== item.group) {
                      rows.push(h('div', { key: 'grp-' + item.group, className: 'scp-cmd-group', role: 'presentation' }, tr('cmd.group.' + item.group)))
                    }
                    rows.push(h('button', {
                      key: 'cmd-' + index, type: 'button', className: 'scp-cmd-item',
                      role: 'option', id: 'scp-cmd-' + index,
                      'aria-selected': index === cmdIndex ? 'true' : 'false',
                      'data-on': index === cmdIndex ? 'true' : 'false',
                      onMouseEnter: () => setCmdIndex(index),
                      onClick: () => { setCmdOpen(false); item.run() },
                    }, item.label))
                    return rows
                  })
                  : h('div', { className: 'scp-cmd-empty' }, tr('cmd.empty'))),
              h('div', { className: 'scp-pal-foot' }, h('span', {}, tr('cmd.hint'))))) : null,
          toast ? h('span', { className: 'scp-toast', title: toast }, toast) : null))
    }

