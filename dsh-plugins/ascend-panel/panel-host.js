return {
  apply(ctx) {
    const fs = ctx.get('fs')
    if (fs === undefined) return
    const sessions = ctx.get('sessions')
    const shell = ctx.get('shell')

    // 工作区解析。**三处消费者的共同前提**：面板读 traces/ knowledge/ metrics/ scripts/ 全靠它。
    //
    // 兜底理由（2026-09-11 实测）：`sessions.get(sessionId)` 可能拿不到 header.cwd（会话标识形态变化、
    // 或面板 tab 所在会话与数据所在检出不是同一个），此时返回 undefined 会让 shell 命令在**别的目录**
    // 下执行——`python scripts/metrics_health.py` 于是找不到文件，只在面板上留下一截截断的 traceback。
    // 所以退一步：扫一遍已知会话，取第一个带 cwd 的（`ascend_trace_status` 工具一直这么做）。
    function pickCwdFromSessions() {
      if (!sessions || typeof sessions.list !== 'function') return undefined
      try {
        const all = sessions.list() || []
        for (const s of all) {
          if (s && s.header && s.header.cwd) return s.header.cwd
        }
      } catch (e) {
        return undefined
      }
      return undefined
    }
    function resolveCwd(sessionId) {
      if (sessions && sessionId) {
        let s = null
        try { s = sessions.get(sessionId) } catch (e) { s = null }
        if (s && s.header && s.header.cwd) return s.header.cwd
      }
      return pickCwdFromSessions()
    }

    async function openEvidence(sessionId, path) {
      if (!path) return { opened: false, error: '缺路径' }
      const cwd = resolveCwd(sessionId)
      if (!cwd) return { opened: false, error: '无法解析工作区' }
      const p = String(path)
      if (p.startsWith('/') || p.includes('..')) return { opened: false, error: '拒绝非仓库路径' }
      if (p.indexOf("'") >= 0 || p.indexOf('"') >= 0) return { opened: false, error: '路径含引号，拒绝拼命令' }
      if (!shell) return { opened: false, error: 'shell 不可用' }
      const full = cwd + '/' + p
      const q = "'" + full.replace(/'/g, "''") + "'"
      // **不能假设 shell 是 bash**：DSH 在 Windows 上把 `ctx.shell` 接到 **PowerShell 5.1**（实测）。
      // 旧实现写的是 `(open X || xdg-open X) >/dev/null 2>&1 &`——`||` 在 PowerShell 5.1 是语法错误，
      // 整条命令直接失败且被 `>/dev/null 2>&1 &` 吞掉（exit 0），于是用户点「打开报告」**什么都没发生**。
      // 现在按"最可能的方言在前、失败即下一个"的顺序试，用 exit code 判定，并把结果与试过的方式回报给面板。
      const attempts = [
        { via: 'powershell', cmd: 'Start-Process -FilePath ' + q },
        { via: 'macos-open', cmd: 'open ' + q },
        { via: 'xdg-open', cmd: 'xdg-open ' + q },
        { via: 'explorer', cmd: 'explorer.exe ' + q, okCodes: [0, 1] },   // explorer.exe 成功时也常返回 1
      ]
      const tried = []
      for (const a of attempts) {
        try {
          const r = await shell.run(shell.resolve({ command: a.cmd, timeoutMs: 5000 }))
          tried.push(a.via + '=' + (r.exitCode === null ? 'null' : r.exitCode))
          const okCodes = a.okCodes || [0]
          if (!r.timedOut && !r.aborted && okCodes.indexOf(r.exitCode) >= 0) {
            return { opened: true, via: a.via }
          }
        } catch (e) {
          tried.push(a.via + '=err')
        }
      }
      return { opened: false, error: '四种打开方式都不行（' + tried.join(' ') + '）' }
    }

    async function updateSedimented(sessionId, traceFile, state, caseId) {
      const cwd = resolveCwd(sessionId)
      if (!cwd || !traceFile) return { ok: false, error: '缺参数' }
      const allowed = { submitted: 1, knowledge: 1, archived: 1 }
      if (!allowed[state]) return { ok: false, error: '非法状态' }
      try {
        const target = await fs.resolve('traces/' + traceFile, { cwd })
        const text = await fs.readText(target)
        const lines = text.split('\n')
        // 写回 schema 的块映射形式（与 diagnosis_state.yaml.example 一致；读取端兼容块/内联/字符串）
        const block = ['sedimented:', '  state: ' + state, '  case_id: "' + (caseId || '') + '"', '  inbox_path: ""']
        const out = []
        let replaced = false
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i]
          const indent = line.length - line.trimStart().length
          if (!replaced && indent === 0 && /^sedimented:/.test(line.trim())) {
            out.push(...block)
            replaced = true
            // 跳过原 sedimented 块的缩进子行（避免残留成游离顶层键）
            let j = i + 1
            while (j < lines.length && lines[j].trim() !== '' && (lines[j].length - lines[j].trimStart().length) > 0) j++
            i = j - 1
            continue
          }
          out.push(line)
        }
        if (!replaced) out.push(...block)
        await fs.writeText(target, out.join('\n'))
        return { ok: true }
      } catch (e) {
        return { ok: false, error: '更新失败: ' + String(e && e.message || e) }
      }
    }

    async function loadKbCaseIds(cwd) {
      try {
        const target = await fs.resolve('knowledge/_index.yaml', { cwd })
        const text = await fs.readText(target)
        const ids = new Set()
        for (const line of text.split(/\r?\n/)) {
          const m = /^- id:\s*([A-Za-z0-9_-]+)/.exec(line.trim())
          if (m) ids.add(m[1])
        }
        return ids
      } catch (e) {
        return null
      }
    }

    // —— 索引头注解析：容量**逐格**（framework × category）+ 声明总数 ——
    // 原先 loadHealth 把格子加总到 namespace 再比 /30，于是 vllm-ascend 显示 114/30，
    // 读者推不出"interrupt 是唯一爆掉的格子"。判据（gates.yaml）逐格计，面板就必须逐格显。
    function parseIdxHeader(text) {
      const head = text.split(/\r?\n/).filter(l => l.startsWith('#')).join('\n')
      const totalM = /case 总数：\s*(\d+)/.exec(head)
      const genM = /生成日期：\s*(\d{4}-\d{2}-\d{2})/.exec(head)
      const cells = []
      const re = /^#\s*容量\(([^)]+)\):\s*(.+)$/gm
      let m
      while ((m = re.exec(head)) !== null) {
        const ns = m[1].trim()
        for (const part of m[2].split(',')) {
          const cm = /^\s*([a-zA-Z_]+)\s*=\s*(\d+)\/(\d+)\s*$/.exec(part)
          if (cm) cells.push({ namespace: ns, category: cm[1], count: Number(cm[2]), cap: Number(cm[3]) })
        }
      }
      return { caseTotal: totalM ? Number(totalM[1]) : null, generatedAt: genM ? genM[1] : null, cells: cells }
    }
    // 磁盘上的 case 文件数——与索引头注对照，索引陈旧时立刻可见（面板读的是索引，不是磁盘）
    async function countCaseFiles(cwd) {
      let n = 0
      async function walk(dirTarget, isRoot, depth) {
        if (depth > 6) return
        let entries = []
        try { entries = await fs.listDir(dirTarget) } catch (e) { return }
        for (const ent of entries) {
          if (ent.type === 'directory') {
            if (isRoot && ent.name.startsWith('_')) continue
            await walk(ent.target, false, depth + 1)
            continue
          }
          if (!ent.name.endsWith('.yaml')) continue
          if (isRoot && ent.name.startsWith('_')) continue
          n++
        }
      }
      try { await walk(await fs.resolve('knowledge', { cwd }), true, 0) } catch (e) { return null }
      return n
    }

    async function listTraces(cwd) {
      let base
      try {
        base = await fs.resolve('traces', { cwd })
      } catch (e) {
        return { ok: false, error: 'traces 路径解析失败: ' + String(e && e.message || e) }
      }
      let entries = []
      try {
        entries = await fs.listDir(base)
      } catch (e) {
        // 全新检出无 traces/（gitignored、按需生成）→ 友好空态，而非报错。
        // 注意：resolve 对不存在的路径**不抛错**（沿最近存在的祖先回走、拼回缺失段），
        // 抛 FS_NOT_FOUND 的是 listDir——存在性判断必须挂在 listDir 这一侧。
        if (e && e.code === 'FS_NOT_FOUND') return { ok: true, sessions: [] }
        return { ok: false, error: 'traces 目录不可读: ' + String(e && e.message || e) }
      }
      const kbIds = await loadKbCaseIds(cwd)
      const out = []
      const basePath = fs.processPath(base)
      for (const ent of entries) {
        if (!ent.name.endsWith('.yaml')) continue
        try {
          const target = await fs.resolve(ent.name, { cwd: basePath })
          const text = await fs.readText(target)
          const doc = parseYaml(text)
          if (!doc || typeof doc !== 'object') continue
          const trace = Array.isArray(doc.trace) ? doc.trace : []
          const userSteps = trace.filter(t => t && t.role === 'user').length
          const agentSteps = trace.filter(t => t && t.role === 'agent').length
          const last = trace[trace.length - 1] || null
          const lastRole = last && last.role ? String(last.role) : null
          const lastAction = last && last.action ? String(last.action) : null
          const lastOutput = last && last.output ? String(last.output).slice(0, 120) : null
          const createdAt = doc.created_at ? String(doc.created_at) : null
          const updatedAt = doc.updated_at ? String(doc.updated_at) : null
          const activeCase = doc.active_case && doc.active_case !== 'null' ? String(doc.active_case) : null
          out.push({
            sessionId: doc.session_id ? String(doc.session_id) : ent.name.replace(/\.yaml$/, ''),
            file: ent.name,
            status: doc.status ? String(doc.status) : 'unknown',
            framework: doc.detected_framework ? String(doc.detected_framework) : '',
            platform: doc.detected_platform ? String(doc.detected_platform) : '',
            category: doc.detected_category ? String(doc.detected_category) : '',
            activeCase: activeCase,
            activeCaseInKb: activeCase ? !!(kbIds && kbIds.has(activeCase)) : false,
            // 收起态副标题的原料：问题背景段（要回答"这单在查什么"）。不用最后一个事件的 output——
            // 那常常是产出报告 / 续接 / 回报这类记录维护动作，读者看不懂（实测反馈）。
            summarySnippet: doc.summary ? String(doc.summary).replace(/\s+/g, ' ').trim().slice(0, 140) : null,
            // 反馈债标记：**新口径**是 `feedback.outcome: pending`（配 `feedback.case`），词表见
            // 仓库根 `trace-status.yaml`；旧 trace 里是 `feedback_pending: <case-id>`。本机历史
            // trace 两种都存在，所以两种都读（先新后旧）——只认一种会让另一半会话的"待回报"
            // 从面板上静默消失（词表改了、读取端没跟，就是这类断链）。
            feedbackPending: (function () {
              const fb = doc.feedback
              if (fb && typeof fb === 'object' && String(fb.outcome || '') === 'pending') {
                return fb.case ? String(fb.case) : 'pending'
              }
              if (typeof fb === 'string' && fb.trim() === 'pending') return 'pending'
              return doc.feedback_pending ? String(doc.feedback_pending) : null
            })(),
            feedback: doc.feedback && typeof doc.feedback === 'object' ? String(doc.feedback.outcome || '') : (doc.feedback ? String(doc.feedback) : null),
            userSteps: Number(userSteps) || 0,
            agentSteps: Number(agentSteps) || 0,
            lastAction: lastAction,
            lastRole: lastRole,
            lastOutput: lastOutput,
            createdAt: createdAt,
            updatedAt: updatedAt,
            // 人读定位报告与结构化沉淀候选（diagnose 步骤 6 产出）：报告名与 trace 同名不同后缀，
            // 面板给"打开报告"入口；候选条数给"待沉淀 N 条"，让"这单还能沉淀什么"在列表上就可见。
            reportFile: doc.report_file ? String(doc.report_file) : null,
            sedimentCandidates: Array.isArray(doc.sediment_candidates) ? doc.sediment_candidates.length : 0,
          })
        } catch (e) {
        }
      }
      out.sort((a, b) => {
        const ta = a.updatedAt ? new Date(a.updatedAt).getTime() : null
        const tb = b.updatedAt ? new Date(b.updatedAt).getTime() : null
        if (ta !== null && tb !== null) return tb - ta
        if (ta !== null) return -1
        if (tb !== null) return 1
        return a.file < b.file ? 1 : -1
      })
      return { ok: true, sessions: out }
    }

    // ---- 知识库健康聚合 ----
    async function loadHealth(cwd) {
      try {
        const out = { cases: {}, references: {} }
        try {
          const target = await fs.resolve('knowledge/_index.yaml', { cwd })
          const text = await fs.readText(target)
          const lines = text.split(/\r?\n/)
          let ns = null
          let cat = null
          let inCase = false
          let curScore = null
          let curCat = null
          const catTotal = {}
          let total = 0
          let low = 0
          for (const raw of lines) {
            const line = raw.replace(/\s+#.*$/, '').trimEnd()
            if (line === '' || line.startsWith('#')) continue
            const nsM = /^  ([a-zA-Z0-9_\/-]+):\s*$/.exec(line)
            if (nsM) { ns = nsM[1]; cat = null; continue }
            const catM = /^    ([a-zA-Z0-9_]+):\s*$/.exec(line)
            if (catM && ns) { cat = catM[1]; inCase = false; continue }
            const idM = /^    - id:\s*([A-Za-z0-9_-]+)/.exec(line)
            if (idM && ns && cat) {
              total++
              inCase = true
              curScore = null
              curCat = cat
              catTotal[cat] = (catTotal[cat] || 0) + 1
              continue
            }
            if (inCase) {
              const scoreM = /^\s+score:\s*([\d.]+)/.exec(line)
              if (scoreM) {
                curScore = parseFloat(scoreM[1])
                if (curScore !== null && !isNaN(curScore) && curScore < 0.5) low++
              }
            }
          }
          out.cases.total = total
          out.cases.lowConfidence = low
          out.cases.byCategory = catTotal
          // 逐格容量（判据口径）：头注里的 count/cap 已带 cap，直接透传。
          // 刻意**不**再给 namespace 加总值——判据逐格计，加总口径会让读者看不出是哪一格爆了。
          const hdr = parseIdxHeader(text)
          out.cases.byCell = hdr.cells
          out.cases.indexGeneratedAt = hdr.generatedAt
          // drift：索引头注声明的条数 vs 磁盘实际 case 文件数（面板读索引，索引陈了就报旧数）
          out.cases.declaredTotal = hdr.caseTotal
          out.cases.diskTotal = await countCaseFiles(cwd)
        } catch (e) {
          out.cases.error = String(e && e.message || e)
        }
        try {
          const refRoot = await fs.resolve('references', { cwd })
          const refPath = fs.processPath(refRoot)
          const dirs = await fs.listDir(refRoot)
          const byType = {}
          let total = 0
          let draft = 0
          let stale = 0
          let caseDerived = 0
          const now = Date.now()
          const day = 86400000
          for (const d of dirs) {
            if (!d.name || d.name.startsWith('_') || !d.isDirectory) continue
            let files = []
            try {
              files = await fs.listDir(await fs.resolve(d.name, { cwd: refPath }))
            } catch (e) { continue }
            for (const f of files) {
              if (!f.name || !f.name.endsWith('.yaml') || f.name.startsWith('_')) continue
              let text = ''
              try {
                const fp = await fs.resolve(d.name + '/' + f.name, { cwd: refPath })
                text = await fs.readText(fp)
              } catch (e) { continue }
              total++
              byType[d.name] = (byType[d.name] || 0) + 1
              const sm = /^status:\s*(\S+)/m.exec(text)
              if (sm && sm[1] === 'draft') draft++
              const lm = /^last_verified:\s*['"]?([\d-]+)/m.exec(text)
              if (lm && lm[1]) {
                const t = new Date(lm[1]).getTime()
                if (!isNaN(t) && (now - t) > 90 * day) stale++
              }
              if (/\bcases:\s*\[/m.test(text) || /\bsource_cases:\s*\[/m.test(text)) caseDerived++
            }
          }
          out.references.total = total
          out.references.draftCount = draft
          out.references.staleCount = stale
          out.references.byType = byType
          out.references.caseDerivedCount = caseDerived
        } catch (e) {
          // references/ 缺失（裁剪检出 / sparse-checkout 未含该目录）→ 全零空态，而非报错
          if (e && e.code === 'FS_NOT_FOUND') {
            out.references.total = 0
            out.references.draftCount = 0
            out.references.staleCount = 0
            out.references.byType = {}
            out.references.caseDerivedCount = 0
          } else {
            out.references.error = String(e && e.message || e)
          }
        }
        return { ok: true, ...out }
      } catch (e) {
        return { ok: false, error: '健康统计失败: ' + String(e && e.message || e) }
      }
    }

    // ---- 流程闭环聚合 ----
    async function loadProcessHealth(cwd) {
      try {
        let base
        try {
          base = await fs.resolve('traces', { cwd })
        } catch (e) {
          return { ok: false, error: 'traces 路径解析失败: ' + String(e && e.message || e) }
        }
        let entries = []
        try {
          entries = await fs.listDir(base)
        } catch (e) {
          // 全新检出无 traces/ → 全零空态（与 listTraces 同一口径：判 listDir 的 FS_NOT_FOUND）
          if (e && e.code === 'FS_NOT_FOUND') {
            return { ok: true, total: 0, submitted: 0, promoted: 0, inProgress: 0, resumed: 0, refSessions: 0 }
          }
          return { ok: false, error: 'traces 不可读: ' + String(e && e.message || e) }
        }
        const basePath = fs.processPath(base)
        let total = 0, submitted = 0, promoted = 0, inProgress = 0, resumed = 0, refSessions = 0
        for (const ent of entries) {
          if (!ent.name.endsWith('.yaml')) continue
          try {
            const target = await fs.resolve(ent.name, { cwd: basePath })
            const text = await fs.readText(target)
            const doc = parseYaml(text)
            if (!doc || typeof doc !== 'object') continue
            total++
            const status = doc.status ? String(doc.status) : ''
            if (status === 'in_progress' || status === 'escalated') inProgress++
            const sedObj = readSedimented(doc)
            const state = sedObj ? sedObj.state : null
            if (state === 'submitted') submitted++
            else if (state === 'knowledge' || state === 'archived') promoted++
            const trace = Array.isArray(doc.trace) ? doc.trace : []
            let hasRef = false
            for (const t of trace) {
              const a = t && t.action ? String(t.action) : null
              if (a === 'resume') resumed++
              if (a === 'reference_lookup') hasRef = true
            }
            if (hasRef) refSessions++
          } catch (e) {
          }
        }
        return { ok: true, total: total, submitted: submitted, promoted: promoted, inProgress: inProgress, resumed: resumed, refSessions: refSessions }
      } catch (e) {
        return { ok: false, error: '流程统计失败: ' + String(e && e.message || e) }
      }
    }

    // 证据：两种形态都要吃——内联字符串（老 trace 的 `evidence: {inline: "…"}`）与解析器给出的
    // 对象（块写法 `evidence:` 换行展开）。旧实现只吃字符串，块写法 trace 的证据会被整条丢掉。
    function parseEvidence(ev) {
      if (!ev) return null
      const asList = (v) => {
        // 内联写法里 `files: [a, b]` 到这一步还是"带方括号的字符串"（parseInlineMap 不做流式展开），
        // 先过一遍 yamlScalar 才能得到数组；块写法给的是真数组。
        const val = typeof v === 'string' ? yamlScalar(v) : v
        return Array.isArray(val) ? val.map(x => String(x)).filter(Boolean) : [String(val)]
      }
      const out = {}
      if (typeof ev === 'object') {
        if (ev.inline) out.inline = String(ev.inline)
        if (ev.files) out.files = asList(ev.files)
        if (ev.sources) out.sources = asList(ev.sources)
        if (ev.missing) out.missing = String(ev.missing)
        return Object.keys(out).length ? out : null
      }
      if (typeof ev !== 'string') return null
      const raw = ev.trim()
      if (!/^\{[\s\S]*\}$/.test(raw)) return { inline: ev }
      const inner = parseInlineMap(raw)
      for (const key of ['inline', 'files', 'sources', 'missing']) {
        if (inner[key] === undefined || inner[key] === '') continue
        out[key] = (key === 'inline' || key === 'missing') ? String(inner[key]) : asList(yamlScalar(String(inner[key])))
      }
      return Object.keys(out).length ? out : null
    }

    async function traceDetail(cwd, traceFile) {
      try {
        const target = await fs.resolve('traces/' + traceFile, { cwd })
        const text = await fs.readText(target)
        const doc = parseYaml(text)
        if (!doc || typeof doc !== 'object') return { ok: false, error: 'trace 解析失败' }
        const trace = Array.isArray(doc.trace) ? doc.trace : []
        const steps = trace.map((t, i) => ({
          idx: i,
          role: t && t.role ? String(t.role) : null,
          step: t && t.step ? Number(t.step) : null,
          action: t && t.action ? String(t.action) : null,
          output: t && t.output ? String(t.output).slice(0, 3000) : null,
          reason: t && t.reason ? String(t.reason).slice(0, 3000) : null,
          content: t && t.role === 'user' && t.content ? String(t.content).slice(0, 500) : null,
          evidence: t && t.role === 'user' && t.evidence ? parseEvidence(t.evidence) : null,
        }))
        const refCount = trace.filter(t => t && t.action === 'reference_lookup').length
        const sed = readSedimented(doc)
        const cands = Array.isArray(doc.sediment_candidates) ? doc.sediment_candidates : []
        return {
          ok: true, steps, summary: doc.summary ? String(doc.summary) : null, refCount, sedimented: sed,
          reportFile: doc.report_file ? String(doc.report_file) : null,
          sedimentCandidates: cands.map(c => ({
            kind: c && c.kind ? String(c.kind) : '',
            summary: c && c.summary ? String(c.summary) : '',
            suggestedSkill: c && (c.suggested_skill || c.suggestedSkill) ? String(c.suggested_skill || c.suggestedSkill) : '',
            status: c && c.status ? String(c.status) : '',
          })).filter(c => c.kind || c.summary),
        }
      } catch (e) {
        return { ok: false, error: '读取失败: ' + String(e && e.message || e) }
      }
    }

    // ---- timeline YAML 解析 ----
    function parseFlowValue(v) {
      v = String(v || '').trim()
      if (v === '') return ''
      if (v.startsWith('{')) {
        const obj = parseInlineMap(v)
        const out = {}
        for (const k of Object.keys(obj)) out[k] = parseFlowValue(obj[k])
        return out
      }
      if (/^-?\d+$/.test(v)) return Number(v)
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) return v.slice(1, -1)
      return v
    }
    function parseTimeline(text) {
      const lines = text.split(/\r?\n/)
      const periods = []
      let cur = null
      let inNotes = false
      let notesIndent = 0
      for (const raw of lines) {
        const noComment = raw.replace(/\s+#.*$/, '').trimEnd()
        if (noComment === '') { if (inNotes && cur) cur.notes += '\n'; continue }
        if (inNotes && cur) {
          const indent = noComment.length - noComment.trimStart().length
          if (indent >= notesIndent) { cur.notes += noComment.trim() + '\n'; continue }
          inNotes = false
        }
        if (noComment === 'periods:') continue
        const item = /^  - (.+)$/.exec(noComment)
        if (item) {
          if (cur) periods.push(cur)
          cur = { notes: '' }
          const fm = /^([a-zA-Z0-9_]+):\s*(.*)$/.exec(item[1])
          if (fm) cur[fm[1]] = parseFlowValue(fm[2])
          continue
        }
        if (!cur) continue
        const m = /^    ([a-zA-Z0-9_]+):\s*(.*)$/.exec(noComment)
        if (m) {
          const key = m[1]
          const v = m[2]
          if (key === 'metrics') { cur.metrics = {}; continue }
          if (key === 'notes') { inNotes = true; notesIndent = 6; continue }
          cur[key] = parseFlowValue(v)
          continue
        }
        const mm = /^      ([a-zA-Z0-9_]+):\s*(.*)$/.exec(noComment)
        if (mm && cur.metrics) {
          const key = mm[1]
          cur.metrics[key] = parseFlowValue(mm[2])
          cur._lastMetricKey = key
          continue
        }
        const nm = /^        ([a-zA-Z0-9_/-]+):\s*(.*)$/.exec(noComment)
        if (nm && cur.metrics && cur._lastMetricKey) {
          if (!cur.metrics[cur._lastMetricKey] || typeof cur.metrics[cur._lastMetricKey] !== 'object') cur.metrics[cur._lastMetricKey] = {}
          cur.metrics[cur._lastMetricKey][nm[1]] = parseFlowValue(nm[2])
        }
      }
      if (cur) periods.push(cur)
      return periods
    }
    async function loadTimeline(cwd) {
      try {
        const target = await fs.resolve('metrics/timeline.yaml', { cwd })
        const text = await fs.readText(target)
        const periods = parseTimeline(text)
        for (const p of periods) delete p._lastMetricKey
        return { ok: true, periods }
      } catch (e) {
        return { ok: false, error: 'timeline.yaml 不可读: ' + String(e && e.message || e) }
      }
    }
    // Python 解释器解析（Windows 兼容）：面板用 shell 跑 Python 脚本，但 Windows 上
    // `python3` 常不存在——python.org 安装器装的是 `python.exe` + `py.exe` 启动器；
    // 若 PATH 里还有 Store 的「应用执行别名」占位程序，执行 `python3` 不报"找不到命令"
    // 而是弹 Microsoft Store。因此按候选逐个探测，取第一个能打印 Python 3.x 的
    // （退出码 0 + 版本号双重判据，占位程序两者都过不了）；结果缓存，一次加载只探一轮。
    // 注意：dynamic Cordis 插件不能 import，此函数与 ev-panel 的同名函数是刻意重复的副本。
    let pythonCmd
    async function resolvePython() {
      if (pythonCmd !== undefined) return pythonCmd
      for (const candidate of ['python3', 'python', 'py -3']) {
        try {
          const spec = shell.resolve({ command: candidate + ' --version', stdoutMaxBytes: 4096 })
          const r = await shell.run(spec)
          const out = [r && r.stdout && r.stdout.text, r && r.stderr && r.stderr.text]
            .filter(t => typeof t === 'string').join('\n')
          if (r && r.exitCode === 0 && /Python 3\./.test(out)) { pythonCmd = candidate; return pythonCmd }
        } catch (e) {
          // 候选不可执行 → 试下一个
        }
      }
      pythonCmd = null
      return pythonCmd
    }

    // 指标闭环体检（verdict）：判据在 metrics/gates.yaml，体检在 scripts/metrics_health.py。
    //
    // **为什么面板必须走这个脚本而不是自己算**：阈值落在数据文件里、只此一处（原则二），
    // 面板若自算就是第二份判据副本——实测的结局是"面板显示 85/30 却没有任何结论行"。
    // 脚本既有的三段式（结论 / 证据 / 下一步动作）正是"聚焦"本身；面板只负责把它端到人眼前。
    //
    // 诚实退化：脚本/解释器/依赖缺一不可，缺了就返回可执行的提示，而不是显示"一切正常"。
    let metricsHealthCache = null
    async function loadMetricsVerdict(cwd) {
      if (!shell) {
        return { ok: false, error: '体检需要 shell 服务（当前不可用）——判据与命令见 metrics/gates.yaml 与 scripts/metrics_health.py' }
      }
      if (metricsHealthCache && metricsHealthCache.cwd === cwd) return metricsHealthCache.value
      const value = await buildMetricsVerdict(cwd)
      metricsHealthCache = { cwd: cwd, value: value }
      return value
    }
    // drift：索引头注声明的 case 数 vs 磁盘实际 case 文件数。面板读的是生成物索引，
    // 索引落后于磁盘时面板会安静地显示旧数——这类"看到的不等于现实"必须被说出来。
    async function buildMetricsVerdict(cwd) {
      const res = await runMetricsHealth(cwd)
      if (!res.ok) return res
      const v = res.verdict
      try {
        const target = await fs.resolve('knowledge/_index.yaml', { cwd })
        const text = await fs.readText(target)
        const hdr = parseIdxHeader(text)
        const disk = await countCaseFiles(cwd)
        v.drift = { declared: hdr.caseTotal, disk: disk, generatedAt: hdr.generatedAt }
      } catch (e) {
        v.drift = { declared: null, disk: null, error: String(e && e.message || e) }
      }
      return { ok: true, verdict: v }
    }

    // 体检执行前的上下文守卫 + 失败时的自诊断。
    //
    // 为什么必须有（2026-09-11 实测事故）：`resolveCwd()` 在拿不到会话工作区时返回 `undefined`，
    // 而 `shell.resolve({workdir: undefined})` **不报错**——它退到某个默认目录，于是
    // `python scripts/metrics_health.py` 找不到文件、Python 抛异常，面板上只剩一截
    // 被 `slice(0,400)` 截断的 traceback（连异常类型都被截掉），无从定位。
    // `runLiveMetrics` 一直防着这件事（`if (!shell || !cwd)`），本函数当初漏了。
    // 两条规则：①没有工作区就直接说清，不发起注定失败的命令；②报错带上**执行上下文**
    //（解释器 / 工作目录 / 命令 / 退出码）与 stderr 的**尾部**（traceback 的最后几行才是结论）。
    function shellFail(prefix, py, cwd, r, err) {
      const tailLines = String(err || '').trim().split(/\r?\n/).filter(Boolean).slice(-6)
      const ctx = '［解释器 ' + (py || '—') + ' · 工作目录 ' + (cwd || '（未知）')
        + ' · 命令 ' + ((py || 'python') + ' scripts/metrics_health.py --json')
        + (r && r.exitCode !== null && r.exitCode !== undefined ? ' · exit ' + r.exitCode : '') + '］'
      return {
        ok: false,
        error: prefix + ' ' + ctx + (tailLines.length ? '\n' + tailLines.join('\n') : ''),
        py: py || null,
        cwd: cwd || null,
        exitCode: r ? r.exitCode : null,
        stderrTail: tailLines.join('\n'),
      }
    }

    async function runMetricsHealth(cwd) {
      if (!shell) {
        return { ok: false, error: '体检需要 shell 服务（当前不可用）——判据在 metrics/gates.yaml，'
          + '手工复现：python3 scripts/metrics_health.py' }
      }
      if (!cwd) {
        // 不发起注定失败的命令：说清缺什么、为什么重要、怎么手工复现
        return shellFail('拿不到会话工作区（session.header.cwd），无法定位 scripts/metrics_health.py——'
          + '体检需要以 ascend-sleuth 检出为工作目录运行；面板其余部分（timeline 快照、知识库统计）'
          + '仍可用，但它们不代表判据结论。手工复现：在检出根目录跑 python3 scripts/metrics_health.py',
          null, cwd, null, '')
      }
      const py = await resolvePython()
      if (!py) {
        return { ok: false, error: '未找到可用的 Python 3 解释器（已试 python3 / python / py -3）——'
          + '体检跑的是 scripts/metrics_health.py，装好 Python 3 并确保在 PATH 里' }
      }
      let r = null
      try {
        r = await shell.run(shell.resolve({
          command: py + ' scripts/metrics_health.py --json',
          workdir: cwd,
          timeoutMs: 60000,
          stdoutMaxBytes: 65536,
          // 面板按 UTF-8 读 stdout；钉住子进程编码，防脚本侧漏掉 UTF-8 输出（Windows GBK 管道）
          env: { PYTHONIOENCODING: 'utf-8' },
        }))
      } catch (e) {
        return shellFail('体检脚本执行失败: ' + String(e && e.message || e), py, cwd, null, '')
      }
      const out = r && r.stdout && typeof r.stdout.text === 'string' ? r.stdout.text : ''
      const err = r && r.stderr && typeof r.stderr.text === 'string' ? r.stderr.text : ''
      if (r && r.timedOut) {
        return { ok: false, error: '体检脚本超时（60s）——它内部会跑 verify_references.py，检出很大时可能偏慢',
                 py: py, cwd: cwd, exitCode: r.exitCode }
      }
      const trimmed = out.trim()
      if (trimmed.startsWith('{')) {
        let doc = null
        try {
          doc = JSON.parse(trimmed)
        } catch (e) {
          return { ok: false, error: '体检输出不是合法 JSON: ' + String(e && e.message || e), py: py, cwd: cwd }
        }
        if (doc && typeof doc === 'object' && !Array.isArray(doc)) return { ok: true, verdict: doc }
        return { ok: false, error: '体检输出不是对象', py: py, cwd: cwd }
      }
      if (/ModuleNotFoundError|No module named 'yaml'/.test(err)) {
        return shellFail('体检脚本缺 PyYAML——pip install pyyaml', py, cwd, r, err)
      }
      // traceback 的**末几行**才是结论；别用 slice(0,N) 把头截下来（实测踩过：异常类型被截掉）
      if (err.trim()) return shellFail('体检脚本报错（stderr 末几行）:', py, cwd, r, err)
      return shellFail('体检脚本无输出（脚本不存在？工作区不是 ascend-sleuth 检出？）', py, cwd, r, err)
    }

    async function runLiveMetrics(cwd) {
      if (!shell || !cwd) return { ok: false, error: '实时计算需要 shell 与工作区（当前不可用）' }
      const py = await resolvePython()
      if (!py) {
        return { ok: false, error: '未找到可用的 Python 3 解释器（已试 python3 / python / py -3）——'
          + '实时计算跑的是 scripts/trace_metrics.py，装好 Python 3 并确保在 PATH 里' }
      }
      try {
        const spec = shell.resolve({
          command: py + ' scripts/trace_metrics.py',
          workdir: cwd,
          stdoutMaxBytes: 16384,
          // 面板按 UTF-8 读 stdout；钉住子进程编码，防脚本侧漏掉 UTF-8 输出（Windows GBK 管道）
          env: { PYTHONIOENCODING: 'utf-8' },
        })
        const r = await shell.run(spec)
        let out = null
        if (r && r.stdout && typeof r.stdout.text === 'string' && r.stdout.text.trim()) out = r.stdout.text
        if (out === null && r && r.stderr && typeof r.stderr.text === 'string' && r.stderr.text.trim()) out = r.stderr.text
        if (!out || !out.trim()) return { ok: false, error: 'trace_metrics.py 无输出（traces/ 为空或脚本报错）' }
        return { ok: true, output: out.slice(0, 8000) }
      } catch (e) {
        return { ok: false, error: '实时计算失败: ' + String(e && e.message || e) }
      }
    }

    // 读取沉淀状态——兼容三种写法：块映射（doc.sedimented 为对象，schema 默认）、
    // 内联流映射字符串（面板写入形态 sedimented: {state:…, caseId:…}）、纯字符串。
    function readSedimented(doc) {
      const raw = doc ? doc.sedimented : null
      if (raw && typeof raw === 'object') {
        if (!raw.state) return null
        return { state: String(raw.state), caseId: raw.caseId || raw.case_id || null, inboxPath: raw.inbox_path || null }
      }
      const s = String(raw || '')
      if (!s) return null
      if (s.startsWith('{')) {
        const parsed = parseInlineMap(s)
        if (parsed && parsed.state) return { state: String(parsed.state), caseId: parsed.caseId || parsed.case_id || null, inboxPath: parsed.inbox_path || null }
        return null
      }
      return { state: s }
    }
    // ---- trace YAML 子集解析 -------------------------------------------------
    // 为什么不引库：动态插件不允许 import/require，Host 也没有 YAML 服务（只有 fs/shell/sessions）。
    // 为什么必须支持**块写法**（2026-09-12 修复）：trace 由 agent 手写，schema 允许两种形态——
    // 内联 `- {role: agent, output: "…"}` 与块写法（`- role: agent` 换行缩进展开，长
    // `output`/`reason`/`evidence.inline` 用块标量 `>-`）。旧实现只认内联：遇到块写法时，
    // dash 行只留下 `role`，第二个键就把 inTrace 关掉 → 事件里 **output/content/reason 全丢**，
    // 面板上表现为"agent 回答都是空的"、证据全无。
    // ⚠️ 计数不是健康信号：块写法下 role 仍在 dash 行上，所以 `1u/15a` 这类步数**恰好还是对的**
    //    （实测：16 个事件解析出 32 条、其中 role 全对但 output 0 条）——判断解析是否健康必须看
    //    "事件里有没有 output/content/reason"，不能看步数。
    function splitYamlLine(raw) {
      // 去注释（`#` 前有空白才算注释）+ 去行尾空白；引号内的 # / : 保持原样
      let out = ''
      let quote = null
      for (let i = 0; i < raw.length; i++) {
        const ch = raw[i]
        if (quote) { out += ch; if (ch === quote) quote = null; continue }
        if (ch === '"' || ch === "'") { quote = ch; out += ch; continue }
        if (ch === '#' && (i === 0 || /\s/.test(raw[i - 1]))) break
        out += ch
      }
      return out.replace(/\s+$/, '')
    }
    function yamlUnquote(s) {
      const t = String(s == null ? '' : s).trim()
      if (t.length >= 2 && (t[0] === '"' || t[0] === "'") && t[t.length - 1] === t[0]) {
        const inner = t.slice(1, -1)
        return t[0] === '"'
          ? inner.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\')
          : inner.replace(/''/g, "'")
      }
      return t
    }
    function splitFlow(inner) {
      const parts = []
      let cur = ''
      let quote = null
      let depth = 0
      for (let i = 0; i < inner.length; i++) {
        const ch = inner[i]
        if (quote) { cur += ch; if (ch === quote) quote = null; continue }
        if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue }
        if (ch === '[' || ch === '{') depth++
        if (ch === ']' || ch === '}') depth = Math.max(0, depth - 1)
        if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; continue }
        cur += ch
      }
      if (cur.trim() !== '') parts.push(cur)
      return parts
    }
    function yamlScalar(text) {
      const t = String(text == null ? '' : text).trim()
      if (t === '') return ''
      if (t[0] === '{') return parseInlineMap(t)
      if (t[0] === '[') {
        const inner = t.slice(1, t[t.length - 1] === ']' ? -1 : undefined)
        return splitFlow(inner).map(yamlScalar)
      }
      return yamlUnquote(t)
    }
    function parseYaml(text) {
      // 先折算成"去注释 + 带缩进"的行表，再按缩进递归收结构
      const rows = []
      for (const raw of String(text == null ? '' : text).split(/\r?\n/)) {
        const line = splitYamlLine(raw)
        const body = line.trim()
        if (body === '' || body === '---') continue
        rows.push({ indent: line.length - line.trimStart().length, body: body, raw: line })
      }
      if (!rows.length) return {}
      const cursor = { rows: rows, i: 0 }
      return readYamlMap(cursor, rows[0].indent)
    }
    function readYamlMap(cursor, indent) {
      const obj = {}
      while (cursor.i < cursor.rows.length) {
        const row = cursor.rows[cursor.i]
        if (row.indent < indent) break
        if (row.indent > indent) { cursor.i++; continue }        // 结构错位：跳过而不是崩
        const m = /^([A-Za-z_][A-Za-z0-9_.-]*):(?:\s+(.*))?$/.exec(row.body)
        if (!m) { cursor.i++; continue }
        cursor.i++
        obj[m[1]] = readYamlValue(cursor, indent, m[2] === undefined ? '' : String(m[2]).trim())
      }
      return obj
    }
    function readYamlValue(cursor, indent, rest) {
      if (rest === '') {
        // 空值：下面有更深缩进 → 嵌套块（序列或映射）；否则空字符串
        if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
          const childIndent = cursor.rows[cursor.i].indent
          return /^-(?:\s|$)/.test(cursor.rows[cursor.i].body)
            ? readYamlSeq(cursor, childIndent)
            : readYamlMap(cursor, childIndent)
        }
        return ''
      }
      if (/^[|>][-+]?$/.test(rest)) return readYamlBlockScalar(cursor, indent, rest)
      if (/^-(?:\s|$)/.test(rest)) return yamlScalar(rest.replace(/^-\s*/, ''))
      return yamlScalar(rest)
    }
    function readYamlBlockScalar(cursor, indent, head) {
      // `|` 原样保留换行；`>` 折叠（连续非空行合空格、空行分段）——与 YAML 语义一致
      const literal = head[0] === '|'
      const collected = []
      while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
        collected.push(cursor.rows[cursor.i])
        cursor.i++
      }
      if (!collected.length) return ''
      let baseIndent = collected[0].indent
      for (const r of collected) if (r.indent < baseIndent) baseIndent = r.indent
      const lines = collected.map(r => r.raw.slice(baseIndent))
      if (literal) return lines.join('\n').replace(/\n+$/, '')
      const out = []
      let buf = []
      for (const ln of lines) {
        if (ln.trim() === '') {
          if (buf.length) { out.push(buf.join(' ')); buf = [] }
          out.push('')
        } else {
          buf.push(ln.trim())
        }
      }
      if (buf.length) out.push(buf.join(' '))
      return out.join('\n').replace(/\n+$/, '')
    }
    function readYamlSeq(cursor, indent) {
      const arr = []
      while (cursor.i < cursor.rows.length) {
        const row = cursor.rows[cursor.i]
        if (row.indent !== indent || !/^-(?:\s|$)/.test(row.body)) break
        const rest = row.body.replace(/^-\s*/, '')
        cursor.i++
        if (rest === '') {
          if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
            const childIndent = cursor.rows[cursor.i].indent
            arr.push(/^-(?:\s|$)/.test(cursor.rows[cursor.i].body)
              ? readYamlSeq(cursor, childIndent)
              : readYamlMap(cursor, childIndent))
          } else {
            arr.push('')
          }
          continue
        }
        if (/^[A-Za-z_][A-Za-z0-9_.-]*:(?:\s|$)/.test(rest)) {
          // 块映射项：dash 行上就是第一个键，其余键缩进更深——把 dash 行还原成同缩进的一行，
          // 与后续行一起按同一层解析（键缩进取实际值，2/4 空格两种写法都吃）
          let keyIndent = indent + 2
          for (let k = cursor.i; k < cursor.rows.length; k++) {
            if (cursor.rows[k].indent <= indent) break
            keyIndent = cursor.rows[k].indent
            break
          }
          const subRows = [{ indent: keyIndent, body: rest, raw: ' '.repeat(keyIndent) + rest }]
          while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
            subRows.push(cursor.rows[cursor.i])
            cursor.i++
          }
          arr.push(readYamlMap({ rows: subRows, i: 0 }, keyIndent))
          continue
        }
        arr.push(rest[0] === '{' ? parseInlineMap(rest) : yamlScalar(rest))
      }
      return arr
    }
    function parseInlineMap(text) {
      const obj = {}
      let s = String(text || '').trim()
      if (s.startsWith('{')) s = s.slice(1)
      if (s.endsWith('}')) s = s.slice(0, -1)
      let i = 0
      while (i < s.length) {
        const km = /^\s*([a-zA-Z0-9_]+):\s*/.exec(s.slice(i))
        if (!km) break
        i += km[0].length
        const key = km[1]
        let val = ''
        let depth = 0
        if (s[i] === '"' || s[i] === "'") {
          const q = s[i++]
          while (i < s.length && s[i] !== q) { val += s[i]; i++ }
          i++
        } else {
          while (i < s.length) {
            const ch = s[i]
            if (ch === '[' || ch === '{') depth++
            else if (ch === ']' || ch === '}') depth = Math.max(0, depth - 1)
            if (ch === ',' && depth === 0) break
            val += ch
            i++
          }
          val = val.trim()
        }
        obj[key] = val
        if (s[i] === ',') i++
      }
      return obj
    }

    const tool = harness.defineTool({
      name: 'ascend_trace_status',
      description: '查询 ascend-sleuth 诊断系统当前 traces/ 状态：列出所有诊断会话（session_id/status/framework/category/active_case/feedback.outcome/步骤数/更新时间）。diagnose 流程启动时用于检查未完成 session 或 feedback 债。',
      parameters: {
        type: 'object',
        properties: {
          cwd: { type: 'string', description: 'ascend-sleuth 仓库路径（含 traces/ 目录）；默认当前 session 的工作目录' },
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: {
            sessionCount: { type: 'number' },
            error: { type: 'string' },
            sessions: {
              type: 'array',
              items: {
                type: 'object',
                additionalProperties: false,
                properties: {
                  sessionId: { type: 'string' },
                  status: { type: 'string' },
                  framework: { type: 'string' },
                  category: { type: 'string' },
                  activeCase: { type: 'string' },
                  feedbackPending: { type: 'string' },
                  userSteps: { type: 'number' },
                  agentSteps: { type: 'number' },
                },
              },
            },
          },
        },
        render: (args, value) => {
          const v = value || {}
          const s = v.sessions || []
          if (!s.length) return [{ type: 'text', text: 'traces/ 无诊断会话——运行 /skill:diagnose 开始' }]
          const lines = s.map(x =>
            '- ' + x.sessionId + ' [' + x.status + '] ' +
            (x.framework || '') + (x.category ? '/' + x.category : '') +
            (x.activeCase ? ' 命中:' + x.activeCase : '') +
            (x.feedbackPending ? ' ⏳feedback:' + x.feedbackPending : '') +
            ' (' + x.userSteps + 'u/' + x.agentSteps + 'a)'
          )
          return [{ type: 'text', text: v.sessionCount + ' 个诊断会话:\n' + lines.join('\n') }]
        },
      },
      async execute(args) {
        let cwd = args && args.cwd ? String(args.cwd) : undefined
        if (!cwd) cwd = pickCwdFromSessions()
        const r = await listTraces(cwd)
        if (!r.ok) return { error: r.error }
        return {
          sessionCount: r.sessions.length,
          sessions: r.sessions.map(s => ({
            sessionId: s.sessionId, status: s.status, framework: s.framework,
            category: s.category, activeCase: s.activeCase || '',
            feedbackPending: s.feedbackPending || '', userSteps: s.userSteps, agentSteps: s.agentSteps,
          })),
        }
      },
    })
    // 注册诊断状态工具（diagnose 启动时查未完成 session / feedback 债）。
    // 重名必须降级而不是抛：registerTool 在名字已被占用时**同步抛错**，会把整个
    // apply() 打断——面板的 tab/RPC 全部注册不上，只因为一个顺手带的工具撞了名。
    // 占用者通常是上一次会话遗留的同类插件（host 侧已看不到、无法 stop），
    // 此时同名工具仍然可用，面板本身没有损失，所以只告警不中断。
    let disposer = null
    try {
      disposer = harness.registerTool(ctx, tool)
    } catch (e) {
      console.error('[ascend-panel] ascend_trace_status 注册失败（可能已由其他插件注册），'
        + '面板其余功能照常：' + String(e && e.message || e))
    }

    const handleDisposer = harness.handle('ascend-traces-list', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      const r = await listTraces(cwd)
      if (!r.ok) return { ok: false, error: r.error }
      return { ok: true, sessions: r.sessions }
    })

    const detailDisposer = harness.handle('ascend-traces-detail', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const traceFile = args && args.traceFile ? String(args.traceFile) : null
      if (!traceFile) return { ok: false, error: '缺 traceFile' }
      const cwd = resolveCwd(sessionId)
      return traceDetail(cwd, traceFile)
    })

    const openDisposer = harness.handle('ascend-open-evidence', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const path = args && args.path ? String(args.path) : null
      return openEvidence(sessionId, path)
    })

    const sedDisposer = harness.handle('ascend-update-sedimented', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const traceFile = args && args.traceFile ? String(args.traceFile) : null
      const state = args && args.state ? String(args.state) : null
      const caseId = args && args.caseId ? String(args.caseId) : null
      return updateSedimented(sessionId, traceFile, state, caseId)
    })

    const metricsDisposer = harness.handle('ascend-metrics-load', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadTimeline(cwd)
    })

    const healthDisposer = harness.handle('ascend-kb-health', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadHealth(cwd)
    })

    const processDisposer = harness.handle('ascend-process-health', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadProcessHealth(cwd)
    })

    const verdictDisposer = harness.handle('ascend-metrics-verdict', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadMetricsVerdict(cwd)
    })

    const liveDisposer = harness.handle('ascend-metrics-live', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return runLiveMetrics(cwd)
    })

    return () => {
      if (disposer) disposer()
      if (handleDisposer) handleDisposer()
      if (detailDisposer) detailDisposer()
      if (openDisposer) openDisposer()
      if (sedDisposer) sedDisposer()
      if (metricsDisposer) metricsDisposer()
      if (healthDisposer) healthDisposer()
      if (processDisposer) processDisposer()
      if (verdictDisposer) verdictDisposer()
      if (liveDisposer) liveDisposer()
    }
  },
}