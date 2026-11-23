      // ── 沉淀视图的渲染件 ────────────────────────────────────────────────
      // 有选择时，提 PR / groom / 收尾的指令按所选 key 现算（host 只收窄指令名单）。
      // 旧版本 host 不认 promptKeys 时会退回整批指令，所以这里在正文里也写清名单来源。
      function openPrompt(kind, resume, scope) {
        const k = String(kind || '')
        if (k !== 'groom' && k !== 'pr' && k !== 'check' && k !== 'close') return
        // 单条动作只对焦点行，整批动作对整份队列，只有从所选范围进来的才按 key 收窄（scope 参数）。
        const wantScope = scope === 'single' || scope === 'whole'
          ? scope
          : (selectedCount ? 'selected' : 'whole')
        if (k === 'pr' && !sedTargetLabel) {
          openTarget('pr', wantScope)
          return
        }
        setPromptKind(k)
        setPromptFallback(null)
        setPromptDetailsOpen(false)
        setBatchSed(null)
        setMenuOpen(false)
        const scopedKinds = { pr: true, groom: true, close: true }
        const keys = wantScope === 'selected' && scopedKinds[k]
          ? selDraftRows.map((draft) => String(draft.key || '')).filter(Boolean)
          : []
        promptToken.current += 1
        if (!keys.length) {
          setScopedPrompt(null)
          return
        }
        const token = promptToken.current
        setScopedPrompt({ kind: k, loading: true, error: '', prompts: null })
        rpcCall('copilot-sediment', {
          cwd: s.cwd, sessionId: s.sessionId, promptKeys: keys,
        }).then((doc) => {
          if (token !== promptToken.current) return
          if (!doc || doc.ok === false) {
            setScopedPrompt({ kind: k, loading: false, error: (doc && doc.message) || '', prompts: null })
            return
          }
          setScopedPrompt({ kind: k, loading: false, error: '', prompts: doc.prompts || {} })
        }, (error) => {
          if (token !== promptToken.current) return
          setScopedPrompt({ kind: k, loading: false, error: String((error && error.message) || error), prompts: null })
        })
      }

      // 写记录被系统拒绝时的指令弹层：复用指令预览这一个面（复制 / 填入输入框），
      // 正文由失败上下文生成。点了才填进输入框，不自动发送，也不覆盖读者正在写的内容。
      function openPromptFallback(head, text, sub, rows) {
        if (!text) return
        setPromptFallback({
          head: String(head || ''), text: String(text), sub: String(sub || ''),
          rows: Array.isArray(rows) ? rows : null,
        })
        setPromptKind('fallback')
        setPromptDetailsOpen(false)
        setBatchSed(null)
        setMenuOpen(false)
      }

      function closePrompt() {
        promptToken.current += 1
        setPromptKind('')
        setPromptFallback(null)
        setBatchSed(null)
      }

      // 批量沉淀：名单在打开弹层时冻结（未选时 = 当前筛选，含搜索词；已选时 = 所选）。
      function openBatchSediment(rowsOverride) {
        const list = Array.isArray(rowsOverride) ? rowsOverride : diagSedentable
        if (!list.length) return
        const query = String(searchText || '').trim()
        const bySelection = Array.isArray(rowsOverride)
        setBatchSed({
          text: sedimentBatchDraft(list, {
            query: bySelection ? '' : query,
            total: bySelection ? list.length : filterRows(rows, 'sediment').length,
            selection: bySelection,
          }),
          count: list.length,
          query,
          selection: bySelection,
          rows: list,
        })
        setPromptKind('sedimentBatch')
        setPromptDetailsOpen(false)
        setMenuOpen(false)
      }

      // 批量撤销：只生成指令，名单冻结在点开这一刻（未选 = 当前筛选；已选 = 所选）。
      // 一份都不手改命令：想撤哪几份，先在列表里勾出来。
      function openBatchUndo(rowsOverride) {
        const list = Array.isArray(rowsOverride) ? rowsOverride : sedUndoRows
        const keys = list.map((draft) => String(draft.key || '')).filter(Boolean)
        if (!keys.length) return
        // key 来自 inbox 文件名；常规字符直接写，出现空格或引号时按 shell 单引号转义。
        const quote = (key) => (/^[A-Za-z0-9._-]+$/.test(key)
          ? key
          : "'" + key.replace(/'/g, "'\\''") + "'")
        const args = keys.map((key) => '--draft-key ' + quote(key)).join(' ')
        const shortTitle = (title) => {
          const text = String(title || '').trim()
          return text.length > 40 ? text.slice(0, 40) + '…' : text
        }
        const names = list.map((draft) => {
          const title = shortTitle(draft.title)
          return String(draft.key || '') + (title ? '（' + title + '）' : '')
        }).join('；')
        const bySelection = Array.isArray(rowsOverride)
        const filterDef = sedFilterDefs.find((item) => item.key === sedFilter)
        const scope = bySelection
          ? ['所选 ' + keys.length + ' 份']
          : ['筛选「' + (filterDef ? filterDef.label : sedFilter) + '」']
        const query = String(searchText || '').trim()
        if (!bySelection && query) scope.push('搜索「' + query + '」')
        const text = '撤销本批沉淀：' + keys.length + ' 份（范围：' + scope.join(' + ') + '）。\n'
          + '本批名单：' + names + '\n'
          + '先看计划（只读）：\npython3 scripts/sediment_undo.py ' + args + '\n'
          + '确认后执行：\npython3 scripts/sediment_undo.py ' + args + ' --apply\n'
          + '脚本逐份处理；被拒的会跳过并报原因，不要绕过。撤销还原沉淀状态，不改诊断状态；'
          + 'PR 已关闭的行会一并清掉本地 PR 记录（PR 本身不动），撤销前先在平台上确认这些 PR 仍关闭；'
          + '要回到进行中，在诊断面板用「重新打开」。'
        openPromptFallback(tr('sediment.undo.batchTitle'), text, tr('sediment.undo.batchSub'), list)
      }

      function openTarget(resume, scope) {
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
        setTargetScope(scope === 'single' || scope === 'selected' ? scope : 'whole')
        setTargetOpen(true)
        closePrompt()
      }

      // 记录版本：list 侧返回的 sha256，写动作带上做 CAS；还没有记录时为空、不带令牌。
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
              // 记录没写进去时带 CAS 令牌；写配置失败时记录已经写过，旧令牌只会先撞 E_CAS。
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
          if (resume) openPrompt(resume, undefined, targetScope)
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
        if (resume && sedTargetLabel) openPrompt(resume, undefined, targetScope)
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
            // 失败也可能已经写了记录（查不到时写 unknown + checked_at），刷新把行里的状态与时间对齐。
            await refreshSediment(true)
            // 刷新期间切了会话：旧 key 的兜底弹层不能弹在新会话上。
            if (store.sessionId !== runSession) return
            const writeKind = prWriteFailureKind(result)
            if (writeKind) {
              // 平台结果拿到了、记录没写进去：给一条能填进输入框的指令交给会话 agent 写。
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

      // 写本地文件被拒绝时该给哪一层指令：'file' = 文件/权限层拒绝（写记录、写配置），
      // 'policy' = 会话档位或沙箱可写面的判断（命令在会话 shell 里通常能过）。
      // 记录损坏也是 E_LEDGER，不能当作写失败去生成写指令。
      function prWriteFailureKind(result) {
        const code = failureCode(result)
        if (code === 'E_PERM') return 'policy'
        if (code === 'E_SETTINGS') return 'file'
        const message = String((result && (result.message || (result.error && result.error.message))) || '')
        if (code === 'E_LEDGER') {
          if (result && result.write_failed === true) return 'file'
          // 旧版脚本没有 write_failed 标记，按它当时的两句写失败原文认（旧版写「台账写不进去」，
          // 新版写「记录写不进去」，两种都要认，否则新面板配旧检出时兜底指令不出现）。
          return /台账写不进去|记录写不进去|配置写不进去|写锁不可用/.test(message) ? 'file' : ''
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

      // 记录 CAS 令牌跟着兜底命令走：面板手里有 sha 时带上，恢复动作不绕开 CAS。
      // 写配置失败不带：那一路记录已经写过，旧令牌会先撞 E_CAS。
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

      async function checkAllPrs(scopeDrafts) {
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (checkBusy) return
        const scoped = Array.isArray(scopeDrafts)
        const drafts = scoped ? scopeDrafts : sedDrafts
        setCheckBusy('__all__')
        beginCheckRun(drafts)
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
            keys: drafts.map((draft) => String(draft.key || '')).filter(Boolean),
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
            // 部分失败是查询类问题、记录已经写进去了；整体写失败才给指令。
            if (store.sessionId !== runSession) return
            const writeKind = !partial ? prWriteFailureKind(result) : ''
            if (writeKind) {
              const states = (Array.isArray(result.checked) ? result.checked : [])
                .filter((item) => item && item.ok !== false
                  && PR_STATE_KEYS.indexOf(String(item.state || '')) >= 0)
                .map((item) => String(item.draft || '') + ' ' + tr('sediment.prState.' + String(item.state)))
              const command = 'python3 scripts/pr_status.py --root . --check-all'
                + (scoped ? drafts.map((draft) => ' --only-draft ' + String(draft.key || '')).join('') : '')
              openPromptFallback(tr('sediment.primary.checkAll'), prWriteFallbackText(
                message, command,
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

      // 人工兜底：平台一直查不到时，按人确认写记录（source=manual）。只写本地记录，
      // 下一次「查合入状态」仍以平台结果为准。
      async function markState(key, state) {
        const nextState = String(state || '')
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (!key || checkBusy || PR_STATE_KEYS.indexOf(nextState) < 0) return
        const draft = sedDrafts.find((item) => item && item.key === key) || null
        const prevState = draft && draft.pr && draft.pr.state ? String(draft.pr.state) : 'unknown'
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
              // 手动改状态与查合入写同一份记录：写不进时也给指令，不让读者对着不可写的文件重试。
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
          setReceiptAsk(false)
          setReceipt({
            kind: 'write',
            view: 'sediment',
            key,
            label: tr('sediment.prState.' + nextState),
            prev: prevState,
            at: Date.now(),
          })
          flash(tr('sediment.manualDone', { state: tr('sediment.prState.' + nextState) }))
        } catch (error) {
          flash(String((error && error.message) || error))
        } finally {
          setCheckBusy('')
        }
      }

      // 反写记录：只对面板自己写过的动作成立。旧状态是写之前记下的，写入再走一次 CAS，
      // 记录被别的进程改过就报冲突、不覆盖。撤销成功后回执改成「已恢复」，不再给撤销。
      async function undoMark() {
        if (!receipt || receipt.kind !== 'write' || receipt.undone) return
        if (!canWrite) { flash(tr('write.disabled')); return }
        if (checkBusy) return
        const target = receipt
        setCheckBusy(target.key)
        try {
          const result = await rpcCall('copilot-pr-target', {
            action: 'mark', cwd: s.cwd, sessionId: s.sessionId, key: target.key,
            state: target.prev, expectSha256: ledgerSha(),
          })
          if (!result || result.ok === false) {
            const reason = (result && (result.message || (result.error && result.error.message))) || ''
            flash(tr('sel.receiptRestoreFailed', { reason: reason || tr('sediment.checkError.unknown') }))
            if (failureCode(result) === 'E_CAS') await refreshSediment(true)
            return
          }
          await refreshSediment(true)
          setReceipt(Object.assign({}, target, { undone: true }))
          flash(tr('sel.receiptRestored', { state: tr('sediment.prState.' + target.prev) }))
        } catch (error) {
          flash(tr('sel.receiptRestoreFailed', { reason: String((error && error.message) || error) }))
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
        openPrompt(kind, undefined, 'single')
      }

      const sedDecidedRows = sedDrafts.filter((draft) => draft.state === 'decided')
      // 批量撤销的范围 = 当前列表（筛选与搜索词）里可撤销的行；单份用详情里的按钮。
      const sedUndoRows = sedSorted.filter((draft) => draft && draft.undo && draft.undo.available)
      const sedDecided = Number(sedCounts.decided) || 0
      const sedOldest = Number(sedCounts.oldestDays) || sedDrafts.reduce((max, draft) => {
        const age = draft.ageDays === null || draft.ageDays === undefined ? -1 : Number(draft.ageDays)
        return age > max ? age : max
      }, 0)
      const sedPrimaryKind = sedDoc && sedDoc.primary ? String(sedDoc.primary.kind || 'none') : 'none'
      // 批次条的主操作跟当前筛选：切到「待合入」时，主按钮换成查合入（只剩已合入行时换成收尾）；
      // 否则混合队列里「继续 groom」会一直占着主按钮，PR 那一侧的动作没有入口。
      // 这里只换按钮位置，两个动作的作用域仍是整批。
      const sedBatchKind = sedFilter === 'check'
        ? ((Number(sedCounts.prOpen) || 0) > 0
          ? 'check'
          : ((Number(sedCounts.prMerged) || 0) > 0 ? 'close' : sedPrimaryKind))
        : sedPrimaryKind
      // 批次条的「查合入」查的是整批，详情里的查单条；两处标签分开写，免得读者分不清作用域。
      const sedPrimaryLabel = sedBatchKind === 'check'
        ? tr('sediment.primary.checkAll')
        : (sedBatchKind === 'close' && sedPrimaryKind !== 'close'
          ? tr('sediment.primary.closeBatch')
          : (sedDoc && sedDoc.primary && sedDoc.primary.label
            ? String(sedDoc.primary.label)
            : tr('sediment.batch.none')))
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

