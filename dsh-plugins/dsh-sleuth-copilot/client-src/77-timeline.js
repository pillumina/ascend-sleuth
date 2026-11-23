      // ── 三段时间线 + 修订（选中即取；面板第四层诊断步骤来自 trace 的步骤列表）────────
      // 明细来自 copilot-timeline 的 layers：null 与缺键都按「未记录」，[] 是「查过但为空」；
      // 加载中 / 读取失败在「现场故障时间线」段里单独给一行，其余三段等数据到了再渲染。
      const rowLayerKey = row ? String(row.sessionId || '') + '|' + String(row.updatedAt || '') : ''
      const layerData = layersState.data && layersState.key === rowLayerKey ? layersState.data : null
      const layersError = row && layersState.key === rowLayerKey ? layersState.error : ''
      const layersLoading = Boolean(row) && !layerData && !layersError
      const incidentEnv = layerData ? String(layerData.incidentEnv || '') : ''
      const incidentItems = layerData ? layerData.incident : null
      const failureProcess = layerData ? layerData.failureProcess : null
      const upstreamTimeline = layerData ? layerData.upstream : null
      const revisions = layerData ? layerData.revisions : []
      const incidentTotal = layerData ? layerData.incidentTotal : 0
      const upstreamTotal = layerData ? layerData.upstreamTotal : 0
      const revisionsTotal = layerData ? layerData.revisionsTotal : 0
      const history = row ? historyEntries(row, data, revisions) : []
      const processOpen = Boolean(row) && processOpenId === row.sessionId
      const upstreamOpen = Boolean(row) && upstreamOpenId === row.sessionId
      const retryLayers = () => {
        layersCacheRef.current.delete(rowLayerKey)
        setLayersRetry(layersRetry + 1)
      }
      // 被修订改过的条目 id：现场条目据此加「已更正」片；删除动作（removed:<id>）不在此列。
      const correctedTargets = new Set()
      revisions.forEach((revision) => {
        const changes = revision && Array.isArray(revision.changes) ? revision.changes : []
        changes.forEach((change) => {
          const target = String((change && change.target) || '')
          if (target && target.indexOf('removed:') !== 0) correctedTargets.add(target)
        })
      })

      // 现场故障时间线：默认展开。加载中 / 读取失败各给一行；日期只有与上一条已知日期
      // 不同才写（同日不再重复），时点未知与只有日期各有自己的写法。
      const incidentBlock = (() => {
        if (!row) return null
        let noteText = ''
        let body
        let showFoot = false
        if (layersLoading) {
          body = h('div', { className: 'scp-mono' }, tr('layers.loading'))
        } else if (layersError) {
          body = h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-form-error' }, tr('layers.failed', { message: layersError })),
            h('button', { type: 'button', className: 'scp-check-action', onClick: retryLayers }, tr('action.retry')))
        } else {
          showFoot = true
          const items = incidentItems || []
          const unknownCount = items.filter((item) => !stampParts(item && item.at)).length
          const dateOnlyCount = items.filter((item) => {
            const parts = stampParts(item && item.at)
            return Boolean(parts) && !parts.time
          }).length
          const notePieces = []
          if (incidentItems === null) {
            notePieces.push(tr('incident.legacyTitle'))
          } else {
            notePieces.push(tr('incident.count', { n: incidentTotal }))
            if (unknownCount) notePieces.push(tr('incident.unknownCount', { n: unknownCount }))
            if (dateOnlyCount) notePieces.push(tr('incident.noTimeCount', { n: dateOnlyCount }))
            // 截断不藏：条数写总数，另加一句「显示前 N 条」。
            if (incidentTotal > items.length) notePieces.push(tr('truncated.showFirst', { n: items.length }))
          }
          noteText = notePieces.join(' · ')
          const envNode = incidentEnv
            ? h('div', { className: 'scp-it-env' }, tr('incident.env'), inlineTokens(incidentEnv))
            : null
          let lastDate = null
          body = incidentItems === null
            ? h('div', { className: 'scp-list-block' },
              envNode,
              h('div', { className: 'scp-upstream-row' },
                h('span', { className: 'scp-chip', 'data-tone': 'warn' }, tr('incident.legacyChip')),
                h('span', { className: 'scp-check-state' }, tr('incident.legacy'))),
              h('div', { className: 'scp-it-note' }, tr('incident.legacyNote')))
            : !items.length
              ? h('div', { className: 'scp-list-block' },
                envNode,
                h('div', { className: 'scp-it-note' }, tr('incident.empty'), ' · ', tr('incident.emptyNote')))
              : h('div', { className: 'scp-it' },
                envNode,
                items.map((item, index) => {
                  const parts = stampParts(item && item.at)
                  // 同日只写一次日期：与上一条已知日期相同就不重复，只有日期没有时刻也照此去重。
                  const showDate = Boolean(parts) && parts.date !== lastDate
                  if (parts) lastDate = parts.date
                  const evidence = (item && item.evidence) || {}
                  const files = Array.isArray(evidence.files) ? evidence.files : []
                  const line = evidence.line
                  const corrected = correctedTargets.has(String((item && item.id) || ''))
                  return h('div', {
                    key: 'incident-' + index,
                    className: 'scp-it-row',
                    'data-time': parts ? (parts.time ? 'known' : 'date') : 'unknown',
                  },
                    h('div', { className: 'scp-it-time' },
                      parts
                        ? [
                          showDate ? h('span', { key: 'date', className: 'scp-it-date' }, parts.date) : null,
                          h('span', {
                            key: 'time',
                            className: 'scp-it-hm',
                            'data-missing': parts.time ? 'false' : 'true',
                          }, parts.time || tr('incident.dateOnly')),
                        ]
                        : h('span', { className: 'scp-it-unknown' }, tr('incident.unknown'))),
                    h('div', { className: 'scp-it-rail', 'aria-hidden': 'true' }, h('span', { className: 'scp-it-dot' })),
                    h('div', { className: 'scp-it-body' },
                      h('div', { className: 'scp-it-text' }, inlineTokens((item && item.what) || '')),
                      h('div', { className: 'scp-it-meta' },
                        item && item.source
                          ? h('span', { key: 'source', className: 'scp-it-src' }, timelineSourceLabel(item.source))
                          : null,
                        corrected
                          ? h('span', { key: 'corrected', className: 'scp-chip', 'data-tone': 'warn' }, tr('incident.corrected'))
                          : null,
                        item && item.atNote ? h('span', { key: 'at-note' }, inlineTokens(item.atNote)) : null,
                        files.map((filePath, fileIndex) => h('button', {
                          key: 'evidence-' + fileIndex,
                          type: 'button',
                          className: 'scp-link',
                          title: line ? String(filePath) + ':' + line : String(filePath),
                          onClick: () => copyAndFlash(line ? String(filePath) + ':' + line : String(filePath)),
                        }, fileLineLabel(filePath, line))))))
                }))
        }
        return h('div', { key: 'incident' },
          h('div', { className: 'scp-section-row' },
            h('div', { className: 'scp-section-label' }, tr('section.incident')),
            noteText ? h('div', { className: 'scp-section-note' }, noteText) : null),
          body,
          showFoot ? h('p', { className: 'scp-it-foot' }, tr('incident.foot')) : null)
      })()

      // 故障过程（日志）：默认收起；段头给条数，有 clock_note 时提示日志时间与墙钟不一致。
      const processBlock = (() => {
        if (!row || !failureProcess) return null
        const nodes = Array.isArray(failureProcess.nodes) ? failureProcess.nodes : []
        const windowValue = failureProcess.window || null
        const windowRange = windowValue
          ? [windowValue.from, windowValue.to].filter(Boolean).join(' – ')
          : ''
        const notePieces = [tr('failureProcess.count', { n: nodes.length })]
        if (failureProcess.clockNote) notePieces.push(tr('failureProcess.clockOff'))
        return h('div', { key: 'failure-process' },
          h('div', { className: 'scp-section-row' },
            h('div', { className: 'scp-section-label' }, tr('section.failureProcess')),
            h('div', { className: 'scp-section-note' }, notePieces.join(' · '))),
          h('div', { className: 'scp-list-block' },
            h('div', { className: 'scp-upstream-row' },
              h('button', {
                type: 'button',
                className: 'scp-check-action',
                onClick: () => setProcessOpenId(processOpen ? '' : row.sessionId),
              }, processOpen ? tr('action.collapseProcess') : tr('action.expandProcess')),
              h('span', { className: 'scp-check-state' }, windowRange
                ? tr('failureProcess.window', { range: windowRange })
                : tr('failureProcess.windowUnknown'))),
            processOpen && failureProcess.clockNote
              ? h('div', { className: 'scp-lp-clock' }, failureProcess.clockNote)
              : null,
            processOpen
              ? h('div', { className: 'scp-lp-list' }, nodes.map((node, index) => {
                const parts = stampParts(node && node.at)
                const evidence = (node && node.evidence) || {}
                const filePath = evidence.file ? String(evidence.file) : ''
                const line = evidence.line
                return h('div', { key: 'log-node-' + index, className: 'scp-lp-row' },
                  h('div', { className: 'scp-lp-time' }, parts ? (parts.time || parts.date) : tr('incident.unknown')),
                  h('div', { className: 'scp-lp-body' },
                    h('div', { className: 'scp-lp-what' }, inlineTokens((node && node.what) || '')),
                    node && node.quote ? h('div', { className: 'scp-lp-quote', title: node.quote }, node.quote) : null,
                    h('div', { className: 'scp-lp-meta' },
                      node && node.repeat ? h('span', { key: 'repeat' }, inlineTokens(node.repeat)) : null,
                      filePath ? h('button', {
                        key: 'evidence',
                        type: 'button',
                        className: 'scp-link',
                        title: line ? filePath + ':' + line : filePath,
                        onClick: () => copyAndFlash(line ? filePath + ':' + line : filePath),
                      }, fileLineLabel(filePath, line)) : null)))
              }))
              : null,
            processOpen ? h('p', { className: 'scp-it-foot' }, tr('failureProcess.foot')) : null))
      })()

      // 上游与查证：现有状态行（锚点 / 查证 / 查上游按钮）+ 上游时间线。
      // 默认 >3 条折叠；upstream 为 null 时只显示状态行（有 case 才出现）。
      const upstreamBlock = (() => {
        if (!row) return null
        if (!row.activeCase && upstreamTimeline === null) return null
        const upstreamRows = upstreamTimeline || []
        const visibleRows = upstreamOpen ? upstreamRows : upstreamRows.slice(0, 3)
        const hiddenCount = Math.max(upstreamRows.length - visibleRows.length, 0)
        const notePieces = []
        if (upstreamTimeline !== null) {
          notePieces.push(tr('upstream.fixCount', { n: upstreamTotal }))
          // 截断不藏：段头写总数，另加一句「显示前 N 条」。
          if (upstreamTotal > upstreamRows.length) notePieces.push(tr('truncated.showFirst', { n: upstreamRows.length }))
        }
        notePieces.push(tr('upstream.note'))
        const timelineNode = upstreamTimeline === null
          ? null
          : (upstreamRows.length
            ? h('div', { key: 'upstream-list', className: 'scp-up-list' },
              visibleRows.map((item, index) => {
                const files = item && item.evidence && Array.isArray(item.evidence.files)
                  ? item.evidence.files : []
                return h('div', { key: 'upstream-row-' + index, className: 'scp-up-row' },
                  h('span', { className: 'scp-up-when' }, stampText(item && item.at)),
                  h('span', { className: 'scp-up-what' },
                    inlineTokens((item && item.what) || ''),
                    item && item.ref ? h('span', { key: 'ref', className: 'scp-chip' }, item.ref) : null,
                    item && item.source
                      ? h('span', { key: 'source', className: 'scp-it-src' }, timelineSourceLabel(item.source))
                      : null,
                    files.map((filePath, fileIndex) => h('button', {
                      key: 'evidence-' + fileIndex,
                      type: 'button',
                      className: 'scp-link',
                      title: String(filePath),
                      onClick: () => copyAndFlash(String(filePath)),
                    }, fileLabel(filePath)))))
              }))
            : h('div', { key: 'upstream-none', className: 'scp-up-note' }, tr('upstream.noFix')))
        const toggleNode = upstreamTimeline !== null && (hiddenCount > 0 || upstreamOpen)
          ? h('div', { key: 'upstream-toggle', className: 'scp-upstream-row' },
            h('button', {
              type: 'button',
              className: 'scp-check-action',
              onClick: () => setUpstreamOpenId(upstreamOpen ? '' : row.sessionId),
            }, upstreamOpen ? tr('upstream.collapse') : tr('upstream.expand', { n: hiddenCount })))
          : null
        return h('div', { key: 'upstream' },
          h('div', { className: 'scp-section-row' },
            h('div', { className: 'scp-section-label' }, tr('section.upstream')),
            h('div', { className: 'scp-section-note' }, notePieces.join(' · '))),
          h('div', { className: 'scp-upstream' },
            row.activeCase
              ? h('div', { className: 'scp-upstream-row' },
                h('span', { className: 'scp-check-label' }, tr('upstream.anchors')),
                upstream && upstream.anchors && upstream.anchors.length
                  ? upstream.anchors.map((anchor) => h('span', { key: anchor, className: 'scp-chip' }, anchor))
                  : h('span', { className: 'scp-mono' }, tr('upstream.none')))
              : null,
            row.activeCase && upstream && upstream.lastVerified
              ? h('div', { className: 'scp-upstream-row' },
                h('span', { className: 'scp-check-state' }, tr('upstream.lastVerified') + '：' + upstream.lastVerified),
                upstream.verificationSource
                  ? h('span', { className: 'scp-check-state' }, tr('upstream.source') + '：' + upstream.verificationSource)
                  : null)
              : null,
            row.activeCase
              ? h('div', { className: 'scp-upstream-row' },
                h('span', { className: 'scp-chip' }, data.upstream && data.upstream.ready ? tr('upstream.ready') : tr('upstream.notReady')),
                h('button', {
                  type: 'button',
                  className: 'scp-check-action',
                  onClick: () => fillDraft(upstreamDraft(row, data.upstream)),
                }, tr('action.upstream')))
              : null,
            timelineNode,
            toggleNode))
      })()

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
        ? h('div', { className: 'scp-pal-side', style: { '--scp-tone': TONE_VAR[toneOf(row)] || TONE_VAR.brand } },
            h('div', { className: 'scp-pal-titlecase', title: caseTitle(row) }, caseTitle(row)),
            h('div', { className: 'scp-identity' },
              h('span', { className: 'scp-badge' }, statusMeta(data.vocab, row.status).label),
              identityChips(row).slice(0, 3).map((chip) => h('span', {
                key: chip.key, className: 'scp-chip', 'data-tone': chip.tone,
                title: chip.title || undefined,
              }, chip.text)),
              revisionsTotal
                ? h('span', {
                  key: 'revisions',
                  className: 'scp-chip',
                  'data-tone': 'warn',
                  title: revisionsTotal > revisions.length
                    ? tr('truncated.showFirst', { n: revisions.length })
                    : undefined,
                }, tr('chip.revisions', { n: revisionsTotal }))
                : null,
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
            (waiting || showMaterials) ? h('div', { key: 'missing' },
              h('div', { className: 'scp-section-label' }, tr('section.missing')),
              h('div', { className: 'scp-list-block' },
                waiting ? h('div', { className: 'scp-missing-lead' },
                  h('span', { className: 'scp-missing-tag' }, tr('label.waiting')),
                  h('span', { className: 'scp-missing-text' }, inlineTokens(waiting))) : null,
                materials.length
                  ? materials.map((item, index) => h('div', { key: 'mat-' + index, className: 'scp-material-row' }, item))
                  : h('div', { className: 'scp-mono' }, tr('materials.none')),
                h('div', { className: 'scp-upstream-row' },
                  h('button', {
                    type: 'button', className: 'scp-check-action',
                    onClick: () => copyAndFlash(materialText(row)),
                  }, tr('action.copyMaterials')),
                  h('button', {
                    type: 'button', className: 'scp-check-action',
                    onClick: () => fillDraft(materialResumeDraft(row)),
                  }, tr('action.materialResume'))))) : null,
            diagSedBlock,
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
            incidentBlock,
            processBlock,
            upstreamBlock,
            h('div', { className: 'scp-section-label' }, tr('section.evidence')),
            h('div', { className: 'scp-list-block' },
              evidenceList.length ? evidenceList.map((filePath) => h('div', { key: filePath, className: 'scp-evidence-row' },
                h('span', { className: 'scp-evidence-path', title: filePath }, filePath),
                h('button', { type: 'button', className: 'scp-check-action', onClick: () => copyPathAndFlash(filePath, flash) }, tr('action.copyPath'))))
                : h('div', { className: 'scp-mono' }, tr('evidence.none')),
              candidateList.length ? candidateList.map((candidate, index) => {
                const produced = String(candidate.status || '') === 'produced'
                return h('div', { key: 'cand-' + index, className: 'scp-candidate' },
                  h('span', { className: 'scp-chip' }, candidate.kind || 'case'),
                  h('span', { className: 'scp-candidate-text', title: candidate.summary }, candidate.summary || tr('none')),
                  produced
                    ? h('span', { className: 'scp-check-state' }, tr('label.produced') + (candidate.refId ? ' · ' + candidate.refId : ''))
                    : h('button', {
                      type: 'button', className: 'scp-check-action',
                      onClick: () => candidateAction(row, candidate),
                    }, tr('action.sedimentGeneric')))
              })
                : h('div', { className: 'scp-mono' }, tr('candidates.none')),
              h('div', { className: 'scp-upstream-row' },
                h('button', {
                  type: 'button', className: 'scp-check-action',
                  onClick: () => toggleReport(row),
                }, reportState.open ? tr('action.hideReport') : tr('action.viewReport')),
                h('span', { className: 'scp-check-state' }, extra.hasReport ? tr('label.hasReport') : tr('report.none'))),
              reportState.open
                ? (reportState.loading ? h('div', { className: 'scp-mono' }, tr('report.loading'))
                  : reportState.error ? h('div', { className: 'scp-form-error', role: 'alert' }, reportState.error)
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
                  : timelineState.error ? h('div', { className: 'scp-form-error', role: 'alert' }, timelineState.error)
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
                h('span', { className: 'scp-history-kind' }, item.label || tr('history.' + item.kind)),
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
            (() => {
              const rowAction = primaryFor(row, data.bound && row.sessionId === data.bound.sessionId)
              return h('div', { className: 'scp-actions' },
                h('button', {
                  type: 'button',
                  className: rowAction.key === 'copy' ? 'scp-btn' : 'scp-btn scp-btn--primary',
                  onClick: () => runPrimary(row),
                }, rowAction.label),
                rowAction.key === 'copy' ? null : h('button', { type: 'button', className: 'scp-btn', onClick: () => copyAndFlash(summaryText(row, data)) }, tr('action.copySummary')),
                h('button', {
                  type: 'button', className: 'scp-btn scp-btn--ghost',
                  ref: moreBtnRef,
                  'aria-haspopup': 'dialog', 'aria-expanded': menuOpen ? 'true' : 'false',
                  'data-more-button': 'true',
                  onClick: () => {
                    if (menuOpen) {
                      setMenuOpen(false)
                      setMenuForm(null)
                    } else {
                      setMenuOpen(true)
                    }
                  },
                }, tr('action.more')))
            })())
        : (data && filtered.length === 0 ? null : h('div', { className: 'scp-pal-side' },
          h('div', { className: 'scp-pal-empty' },
            emptyMark,
            !data ? tr('palette.loading') : tr('palette.emptyFiltered'))))

      const actionMenu = menuOpen && row && !loadFailed && view === 'diagnosis'
        ? h('div', { className: 'scp-actions-menu', role: 'dialog', 'aria-label': tr('menu.title'), ref: actionMenuRef, tabIndex: -1 },
          h(WritePanel, {
            row,
            data,
            autoForm: menuForm,
            onClose: () => { setMenuOpen(false); setMenuForm(null) },
            onDone: () => { setMenuOpen(false); setMenuForm(null); refresh(true) },
            onFlash: flash,
            onDraft: fillDraft,
          }))
        : null

