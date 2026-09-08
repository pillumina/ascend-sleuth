return {
  apply(ctx) {
    const fs = ctx.get('fs')
    if (fs === undefined) return
    const sessions = ctx.get('sessions')
    const shell = ctx.get('shell')

    function resolveCwd(sessionId) {
      if (sessions && sessionId) {
        const s = sessions.get(sessionId)
        if (s && s.header && s.header.cwd) return s.header.cwd
      }
      return undefined
    }

    async function openEvidence(sessionId, path) {
      if (!path) return { opened: false, error: '缺路径' }
      const cwd = resolveCwd(sessionId)
      if (!cwd) return { opened: false, error: '无法解析工作区' }
      const p = String(path)
      if (p.startsWith('/') || p.includes('..')) return { opened: false, error: '拒绝非仓库路径' }
      if (!shell) return { opened: false, error: 'shell 不可用' }
      try {
        const full = cwd + '/' + p
        const quote = JSON.stringify(full)
        const cmd = '(open ' + quote + ' || xdg-open ' + quote + ') >/dev/null 2>&1 &'
        const spec = shell.resolve({ command: cmd })
        await shell.run(spec)
        return { opened: true }
      } catch (e) {
        return { opened: false, error: '打开失败: ' + String(e && e.message || e) }
      }
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
            feedbackPending: doc.feedback_pending ? String(doc.feedback_pending) : null,
            feedback: doc.feedback ? String(doc.feedback) : null,
            userSteps: Number(userSteps) || 0,
            agentSteps: Number(agentSteps) || 0,
            lastAction: lastAction,
            lastRole: lastRole,
            lastOutput: lastOutput,
            createdAt: createdAt,
            updatedAt: updatedAt,
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
          const nsCells = {}
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
              const key = ns + '/' + cat
              nsCells[key] = (nsCells[key] || 0) + 1
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
          const nsAgg = {}
          for (const key of Object.keys(nsCells)) {
            const idx = key.lastIndexOf('/')
            const nsk = key.slice(0, idx)
            const ck = key.slice(idx + 1)
            if (!nsAgg[nsk]) nsAgg[nsk] = { total: 0, byCat: {} }
            nsAgg[nsk].total += nsCells[key]
            nsAgg[nsk].byCat[ck] = nsCells[key]
          }
          out.cases.byNamespace = nsAgg
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

    function parseEvidence(str) {
      if (!str || typeof str !== 'string') return null
      const m = /^\{\s*(.*)\s*\}$/.exec(str.trim())
      if (!m) return null
      const inner = parseInlineMap('{' + m[1] + '}')
      const out = {}
      if (inner.inline) out.inline = String(inner.inline)
      if (inner.files) {
        const fm = /^\[\s*(.*)\s*\]$/.exec(String(inner.files).trim())
        out.files = fm ? String(fm[1]).split(',').map(x => x.trim().replace(/^["']|["']$/g, '')).filter(Boolean) : [String(inner.files)]
      }
      if (inner.sources) out.sources = [String(inner.sources)]
      if (inner.missing) out.missing = String(inner.missing)
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
        return { ok: true, steps, summary: doc.summary ? String(doc.summary) : null, refCount, sedimented: sed }
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
    async function runLiveMetrics(cwd) {
      if (!shell || !cwd) return { ok: false, error: '实时计算需要 shell 与工作区（当前不可用）' }
      try {
        const spec = shell.resolve({
          command: 'python3 scripts/trace_metrics.py',
          workdir: cwd,
          stdoutMaxBytes: 16384,
          // 面板按 UTF-8 读 stdout；钉住子进程编码，防脚本侧漏掉 UTF-8 输出（Windows GBK 管道）
          env: { PYTHONIOENCODING: 'utf-8' },
        })
        const r = await shell.run(spec)
        let out = null
        if (r && r.stdout && typeof r.stdout.text === 'string' && r.stdout.text.trim()) out = r.stdout.text
        if (out === null && r && typeof r.stderr === 'string' && r.stderr.trim()) out = r.stderr
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
    function parseYaml(text) {
      const lines = text.split(/\r?\n/)
      const doc = {}
      const trace = []
      let inTrace = false
      let blockKey = null      // 当前块映射的键（sedimented / feedback 等）
      let blockIndent = -1     // 块头缩进（其子行缩进更深）
      for (const raw of lines) {
        const trimmed = raw.trim()
        const isTraceItem = /^-\s*\{/.test(trimmed)
        const noComment = isTraceItem ? raw.trimEnd() : raw.replace(/\s+#.*$/, '').trimEnd()
        if (noComment === '') continue
        const indent = noComment.length - noComment.trimStart().length
        if (inTrace) {
          const tm = /^\s*-\s*(.*)$/.exec(noComment)
          if (tm) { trace.push(parseInlineMap(tm[1])); continue }
          if (/^[a-zA-Z_]+:/.test(noComment)) { inTrace = false; blockKey = null }
          else continue
        }
        if (noComment.trim() === 'trace:') { inTrace = true; blockKey = null; continue }
        const m = /^([a-zA-Z_]+):\s*(.*)$/.exec(noComment.trim())
        if (!m) continue
        const rawVal = m[2]
        const v = rawVal.replace(/^["']|["']$/g, '')
        // 块映射的子行（缩进比块头更深）→ 收进嵌套对象
        if (blockKey !== null && indent > blockIndent) {
          doc[blockKey][m[1]] = v
          continue
        }
        blockKey = null
        if (rawVal === '') {          // 空值 → 块映射头（sedimented:/feedback:）
          doc[m[1]] = {}
          blockKey = m[1]
          blockIndent = indent
        } else if (v === '[]') {
          doc[m[1]] = []
        } else {
          doc[m[1]] = v
        }
      }
      if (trace.length) doc.trace = trace
      return doc
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
      description: '查询 ascend-sleuth 诊断系统当前 traces/ 状态：列出所有诊断会话（session_id/status/framework/category/active_case/feedback_pending/步骤数/更新时间）。diagnose 流程启动时用于检查未完成 session 或 feedback 债。',
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
      execute: async (args) => {
        let cwd = args && args.cwd ? String(args.cwd) : undefined
        if (!cwd && sessions) {
          const all = sessions.list()
          for (const s of all) {
            if (s && s.header && s.header.cwd) { cwd = s.header.cwd; break }
          }
        }
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
    const disposer = harness.registerTool(ctx, tool)

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
      if (liveDisposer) liveDisposer()
    }
  },
}