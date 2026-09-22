return {
  apply(ctx) {
    const fs = ctx.get('fs')
    const sessions = ctx.get('sessions')
    const shell = ctx.get('shell')

    // fs 缺失时**只降级依赖它的功能**，不再让整个插件静默不注册。
    //
    // 原先这里写的是 `if (fs === undefined) return`：后果是 fs 缺席时**两个 tab 一起死**——
    // 连指标 tab 的「闭环判决」「实时计算」也没了，而那两项只跑脚本、根本不用 fs
    // （`loadMetricsVerdict` / `runLiveMetrics` 全程无 fs 调用，已由测试逐函数核对）。
    // "挂载了却什么都没贡献"是最难查的失败形态：面板不报错，只是什么都没发生。
    //
    // 现在的分工（按函数核对过）：需要 fs 的六个 RPC → traces-list / traces-detail /
    // update-sedimented / metrics-load / kb-health / process-health；不需要 → open-evidence
    // （只走 shell 打开文件）/ metrics-verdict（drift 那步已在 try 里，降级即可）/ metrics-live。
    const needFs = () => ({
      ok: false,
      error: '该功能需要 fs 服务（读写仓库文件），当前不可用；'
        + '指标 tab 的「闭环判决」「实时计算」不经 fs，仍然可用',
    })

    // ── 跑子进程的沙箱写权限根（每个 shell.resolve 调用点都要带）──────────────────────
    //
    // 写法：`sandboxPolicy: { mode: 'workspace-write', workspaceRoot: cwd }`——**不能省**。
    //
    // 为什么（实测）：`shell.resolve` 不给 `sandboxPolicy` 时，shell 实现自己的默认根是
    // **DSH 自己的检出**（实测 workspaceRoot = …/deepseek-harness），于是子进程写仓库里的任何路径
    // 都被沙箱拒掉，报出来只有一句 `[Errno 1] Operation not permitted`——读者从这句看不出是沙箱干的
    // （文件权限与 ACL 都正常，`ls -lOe` 查下来毫无异常）。交接包导出是面板里第一个"子进程写文件"的
    // 功能，一头撞上它；其余 RPC 当时只读，所以一直没暴露。
    //
    // `workspace-write` 是够用的最小一档：写只许落在检出内（导出写 `<检出>/traces/exports/`），
    // 读不受限（解释器在别处、脚本要读仓库内文件都照常）。它比本会话自身的文件策略更窄，不是提权。
    //
    // 不抽成 helper 的原因：`panel_render_check` 会把下面几个函数**单独抽出来求值**（只注入
    // shell / resolvePython），引外部 helper 会直接 ReferenceError。漏带的调用点由该检查的
    // 源级断言兜（策略数 ≠ 脚本调用数即红）。

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
      // 外部 URL 走同一条打开通路（trace 里 agent 查到的资料就是 http(s) 链接，读者要能一键打开）。
      // URL **不能拼 cwd**——拼了会去开一个不存在的本地路径；仓库内相对路径的守卫（拒绝绝对路径与 ..）
      // 也只对文件成立，所以先分流再各自校验。
      const isUrl = /^https?:\/\//i.test(p)
      if (!isUrl && (p.startsWith('/') || p.includes('..'))) return { opened: false, error: '拒绝非仓库路径' }
      if (p.indexOf("'") >= 0 || p.indexOf('"') >= 0) return { opened: false, error: '路径含引号，拒绝拼命令' }
      if (!shell) return { opened: false, error: 'shell 不可用' }
      const full = isUrl ? p : cwd + '/' + p
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

    // —— 逐格容量与条数：**现算**（scripts/index_counts.py），不再解析索引头注 ——
    //
    // 为什么改：那几个数字原先写在生成物（knowledge/_index.yaml）头注里，是**共享热点**——
    // 两人并发改不同框架时会撞同一段文本，或各自写出漂移的数（根因见 scripts/index_counts.py 头注）。
    // 数字从生成物里拿掉之后，面板读的是 case 文件本身，没有会腐烂的第二份副本。
    // 上一次的教训也在：loadHealth 曾把格子加总到 namespace 再比 /30，于是 vllm-ascend 显示 114/30，
    // 读者推不出"interrupt 是唯一爆掉的格子"——判据逐格计，面板就必须逐格显。
    // 索引条目数（生成物里真实列了几条）——与磁盘 case 文件数对照，索引陈旧/丢条目时立刻可见。
    // 面板读的是索引，不是磁盘：两者不等就得说出来（这类"看到的不等于现实"是面板最容易骗人的地方）。
    async function countIndexEntries(cwd) {
      try {
        const target = await fs.resolve('knowledge/_index.yaml', { cwd })
        const text = await fs.readText(target)
        let n = 0
        for (const line of text.split(/\r?\n/)) {
          if (/^- id:\s*\S/.test(line.trim())) n++
        }
        return n
      } catch (e) {
        return null
      }
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

    // `active_case` 有两种取值：真实 case id，或"没命中"时被写进去的占位/说明串
    // （例 `pending-investigation (upstream #12345)`）。占位串不是 case id——把它当 case 显示，
    // 读者会以为"定位到了 pending-investigation 这个 case"，并按它生成"该 case 的 fix 生效了吗"
    // 这类指令。同一个坑在 `feedback.case` 上已经踩过一次（占位串被当成 case id，2026-09 修过），
    // 这里按同一口径分开：host 出 `activeCaseKind`，原值照旧带出去（面板要能显示 trace 里写了什么）。
    // 占位串词表：`pending-investigation` 是 `feedback.case` 里定义的那个占位串（"没命中 case、
    // 只给了建议"），agent 有时把它连同说明一起写进 `active_case`（例
    // `pending-investigation (upstream #12345)`）——所以按前缀判，而不是全等。
    const PLACEHOLDER_CASE = /^pending[-_]investigation\b/i
    // 字面量空值：等价于"没有 case"（面板按未定位显示，不必把 null/none 端上屏）
    const EMPTY_CASE = /^(null|none|nil|n\/?a|unknown)$/i
    function activeCaseKindOf(value) {
      const v = value === null || value === undefined ? '' : String(value).trim()
      if (!v || EMPTY_CASE.test(v)) return null
      return PLACEHOLDER_CASE.test(v) ? 'placeholder' : 'case'
    }
    // 报告名的归一：契约是"文件名（与 trace 同目录）"，但 trace 里常被写成**带目录的路径**
    // （`traces/x.report.md`、`traces\x.report.md`、`./traces/x.report.md`、`C:/repo/traces/x.report.md`）。
    // 而面板读报告与"打开报告"时统一在 `traces/` 下拼路径——这类写法于是拼成 `traces/traces/…`
    // （实测症状：点「打开报告」后资源管理器找的是 `…\ascend-sleuth\traces\traces\…`）。
    // 所以这里把 `traces/` 及其之前的部分剥掉，只留 traces/ 内的相对名。
    function normalizeReportName(value) {
      const s = String(value == null ? '' : value).trim().replace(/\\/g, '/').replace(/^\.\//, '')
      if (!s) return null
      const m = /(?:^|\/)traces\/(.+)$/.exec(s)
      return m ? m[1] : s
    }
    // 报告入口指向哪个文件：trace 里记的 `report_file`（**顶层与 report 事件里都认**）→ 退到同名规则。
    //
    // 为什么要认两种来源（2026-09-14 实测）：trace 写作文档给的是**事件内**写法
    // （`- {step: 6, action: report, report_file: "<session>.report.md", …}`），而面板只读顶层字段
    // ——于是报告明明落在 traces/ 里，卡片上却没有「看报告」入口。同名回退在 `readReport` 里一直
    // 就有（真点得到），缺的是"入口先出现"这一步。`fileNames` 给 traces/ 的条目名集合；
    // 传 null 表示不查存在性（读报告时用，真读不到会有明确的读失败）。
    function reportFileOf(doc, fileNames, traceFile) {
      const recorded = normalizeReportName(doc && doc.report_file)
      if (recorded) return { name: recorded, source: 'trace' }
      const events = doc && Array.isArray(doc.trace) ? doc.trace : []
      for (let i = events.length - 1; i >= 0; i--) {
        const name = normalizeReportName(events[i] && events[i].report_file)
        if (name) return { name: name, source: 'trace' }
      }
      const base = String(traceFile || '').replace(/\.yaml$/, '')
      const sid = doc && doc.session_id ? String(doc.session_id) : ''
      for (const cand of [base ? base + '.report.md' : null, sid ? sid + '.report.md' : null]) {
        if (cand && fileNames && fileNames.has(cand)) return { name: cand, source: 'name' }
      }
      return null
    }

    // 外来单的交接单（`traces/handoff/<sid>.yaml`，`import_trace.py` 落位时留档，口径见 docs/guide/handoff.md）。
    // 读不到就返回 null——卡片按普通单显示，**不编造**"外来"标记（标错比不标更坏：读者会去追一个
    // 不存在的上家）。
    async function readHandoffNote(handoffDir, sid) {
      if (!handoffDir || !sid) return null
      try {
        const doc = parseYaml(await fs.readText(await fs.resolve(sid + '.yaml', { cwd: handoffDir })))
        if (!doc || typeof doc !== 'object') return null
        const imp = (doc.imported && typeof doc.imported === 'object') ? doc.imported : {}
        const intent = String(doc.intent || '')
        return {
          host: (doc.origin && doc.origin.host) ? String(doc.origin.host) : '',
          // 词表与 export/import 脚本一致；不认识的取值留空，别把原始串当标签上屏
          intent: { continue: 1, verify: 1, escalate: 1 }[intent] ? intent : '',
          exportedAt: doc.exported_at ? String(doc.exported_at) : '',
          importedAt: imp.imported_at ? String(imp.imported_at) : '',
          renamedFrom: imp.renamed_from ? String(imp.renamed_from) : null,
          kbRevMatch: typeof imp.kb_rev_match === 'boolean' ? imp.kb_rev_match : null,
          needs: Array.isArray(doc.needs) ? doc.needs.length : 0,
        }
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
      // traces/ 的条目名：报告入口的同名回退要用它（见 reportFileOf）
      const fileNames = new Set(entries.map(e => e && e.name).filter(Boolean))
      // 外来单（从别的机器接手来的那一单）：交接单在 `traces/handoff/<sid>.yaml`。
      // 一次 listDir 拿到全集，**不按单逐个 stat**；目录不存在（从没接手过外来单）是空集，不是错误。
      let handoffDir = null
      const handoffIds = new Set()
      try {
        const hbase = await fs.resolve('handoff', { cwd: basePath })
        handoffDir = fs.processPath(hbase)
        for (const e of (await fs.listDir(hbase)) || []) {
          if (e && e.name && e.name.endsWith('.yaml')) handoffIds.add(e.name.replace(/\.yaml$/, ''))
        }
      } catch (e) {
      }
      for (const ent of entries) {
        if (!ent.name.endsWith('.yaml')) continue
        try {
          const target = await fs.resolve(ent.name, { cwd: basePath })
          const text = await fs.readText(target)
          const stats = {}
          const doc = parseYaml(text, stats)
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
          const rep = reportFileOf(doc, fileNames, ent.name)
          const sessionId = doc.session_id ? String(doc.session_id) : ent.name.replace(/\.yaml$/, '')
          // 外来标记按 session_id 与文件名两种键查（两者通常相同，但不保证——trace 文件名与
          // 它里面的 session_id 是两件事）
          const isForeign = handoffIds.has(sessionId) || handoffIds.has(ent.name.replace(/\.yaml$/, ''))
          out.push({
            sessionId: sessionId,
            handoff: isForeign ? await readHandoffNote(handoffDir, sessionId) : null,
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
            // 反馈轴的**分型**：`feedback.case` 有两种取值——真实 case id，或占位串
            // `pending-investigation`（词表在 `diagnosis_state.yaml.example` 里明确允许它表示
            // "没命中 case、只给了建议"）。占位串**不是** case id：读成后者会让面板说
            // "结果待回报：pending-investigation"（读起来像有个 fix 等验证），也会让
            // `resume-diagnosis` 去回写一个不存在的 case 的 confidence。所以这里把两种分开：
            //   'case'    = 给了可应用 fix、等回报（feedback 轴承载结果）
            //   'no-case' = 没命中 case，等的是**现场补材料**（结果记在 status 与 summary 里）
            feedbackKind: (function () {
              const fb = doc.feedback
              const out = (fb && typeof fb === 'object') ? String(fb.outcome || '') : (typeof fb === 'string' ? fb.trim() : '')
              if (out !== 'pending') return null
              const cs = (fb && typeof fb === 'object' && fb.case) ? String(fb.case) : ''
              return (cs && cs !== 'pending-investigation') ? 'case' : 'no-case'
            })(),
            feedbackCase: (function () {
              const fb = doc.feedback
              const cs = (fb && typeof fb === 'object' && fb.case) ? String(fb.case) : ''
              return (cs && cs !== 'pending-investigation') ? cs : null
            })(),
            // "在等什么"：无命中单等的不是 fix verdict，而是材料。取**最近一条带 `evidence.missing`
            // 的事件**（那是"还缺什么"的最新陈述），退到顶层 `last_action`。
            waitingFor: (function () {
              for (let i = trace.length - 1; i >= 0; i--) {
                const ev = trace[i] && trace[i].evidence
                if (ev && ev.missing) return String(ev.missing).replace(/\s+/g, ' ').trim()
              }
              return doc.last_action ? String(doc.last_action).replace(/\s+/g, ' ').trim() : null
            })(),
            userSteps: Number(userSteps) || 0,
            agentSteps: Number(agentSteps) || 0,
            lastAction: lastAction,
            lastRole: lastRole,
            lastOutput: lastOutput,
            createdAt: createdAt,
            updatedAt: updatedAt,
            // 人读定位报告与结构化沉淀候选（diagnose 步骤 6 产出）：报告名与 trace 同名不同后缀，
            // 面板给"打开报告"入口；候选条数给"沉淀建议 N 条"，让"这单还能沉淀什么"在列表上就可见
            // （明细含 case 与先验两类，在展开后的沉淀区分家呈现）。
            // 报告名的来源分两种（trace 记录 / 同名规则），client 据此说明入口是怎么来的。
            reportFile: rep ? rep.name : null,
            reportSource: rep ? rep.source : null,
            // `active_case` 是 case id 还是"没命中"的占位/说明串（见 activeCaseKindOf）
            activeCaseKind: activeCaseKindOf(activeCase),
            sedimentCandidates: Array.isArray(doc.sediment_candidates) ? doc.sediment_candidates.length : 0,
            // 轨迹解析没收下的行数（见 anomalyOf）：列表上的步数由同一份解析结果算出，
            // 解析少了就标在卡片上，别让"1 用户输入"看起来像这单真的只有一步。
            parseAnomaly: anomalyOf(stats),
          })
        } catch (e) {
        }
      }
      // 排序：**按诊断开始时间倒序**（最新的在最上），`updated_at` 只作同刻并列时的次序。
      // 为什么不用 `updated_at` 当主键：它是 agent 写 trace 时手填的字段，写错或漏刷新都会
      // 直接改列表次序（实测：某次 session 的 created_at 最新，却因 updated_at 被填成较早的
      // 时刻而排在中间，读者按"最新在最上"找不到它）；`created_at` 建 session 时写一次、
      // 之后按约定不改，是唯一能当"何时开始诊断"的键。活跃度改由卡片上的状态徽章与
      // `updated_at` 字段本身承载，不再借排序表达。
      // 两者都缺时退到文件名——文件名以日期开头，字典序仍近似时间序。
      const ts = (v) => {
        const t = v ? new Date(v).getTime() : NaN
        return Number.isNaN(t) ? null : t
      }
      out.sort((a, b) => {
        const ca = ts(a.createdAt)
        const cb = ts(b.createdAt)
        if (ca !== null && cb !== null && ca !== cb) return cb - ca
        const ua = ts(a.updatedAt)
        const ub = ts(b.updatedAt)
        if (ua !== null && ub !== null && ua !== ub) return ub - ua
        if (ua !== null && ub === null) return -1
        if (ub !== null && ua === null) return 1
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
          // 逐格容量**不在这里**：判据逐格计，真值走 metrics_health 那条链（capacity_cells，
          // 由 scripts/index_counts.py 现算）。这里曾顺手也调一次 index_counts 填 byCell/liveTotal，
          // 但全仓没有读者、每次渲染多付约 1 秒，而且失败时只写了一个没人读的字段
          // （countsError）——"统计读不到"在界面上长得和"本来就没数据"一样。删掉。
          // drift：索引里**真实列出的条目数** vs 磁盘 case 文件数（面板读索引，索引丢了条目就报出来）
          out.cases.declaredTotal = total
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

    // 记录维护类动作——与 panel-client.js 的 PROC_ACTIONS 同值（人读视图收起它们）。
    // 两处必须一致：host 用它找"人读视图的可见末条"来判定位结论的落点，client 用它过滤渲染；
    // 任一侧单独改动都会让"结论块"与"轨迹末条"指向不同的事件。
    const HOST_PROC_ACTIONS = { report: true, resume: true, feedback: true, attribution: true }

    // 证据：两种形态都要吃——内联字符串（老 trace 的 `evidence: {inline: "…"}`）与解析器给出的
    // 对象（块写法 `evidence:` 换行展开）。旧实现只吃字符串，块写法 trace 的证据会被整条丢掉。
    function parseEvidence(ev) {
      if (!ev) return null
      // 内联证据的渲染上限，与 output/reason 同口径（见 traceDetail）。
      // **必须同时给出原文长度**：卡面「证据 N 字」那个徽标读的是 inlineChars——只切片不给长度，
      // 徽标就会说"证据 3000 字"，而原文可能是 4 万字（面板在"不静默截断"上已有先例：报告超限时
      // 如实说"还有 N 块未渲染"）。
      const INLINE_MAX = 3000
      const asList = (v) => {
        // 内联写法里 `files: [a, b]` 到这一步还是"带方括号的字符串"（parseInlineMap 不做流式展开），
        // 先过一遍 yamlScalar 才能得到数组；块写法给的是真数组。
        const val = typeof v === 'string' ? yamlScalar(v) : v
        return Array.isArray(val) ? val.map(x => String(x)).filter(Boolean) : [String(val)]
      }
      const out = {}
      if (typeof ev === 'object') {
        if (ev.inline) {
          const raw = String(ev.inline)
          out.inline = raw.slice(0, INLINE_MAX)
          out.inlineChars = raw.length
        }
        if (ev.files) out.files = asList(ev.files)
        if (ev.sources) out.sources = asList(ev.sources)
        if (ev.missing) out.missing = String(ev.missing)
        return Object.keys(out).length ? out : null
      }
      if (typeof ev !== 'string') return null
      const raw = ev.trim()
      if (!/^\{[\s\S]*\}$/.test(raw)) return { inline: ev.slice(0, INLINE_MAX), inlineChars: ev.length }
      const inner = parseInlineMap(raw)
      for (const key of ['inline', 'files', 'sources', 'missing']) {
        if (inner[key] === undefined || inner[key] === '') continue
        if (key === 'inline') {
          const s0 = String(inner[key])
          out.inline = s0.slice(0, INLINE_MAX)
          out.inlineChars = s0.length
        } else {
          out[key] = (key === 'missing') ? String(inner[key]) : asList(yamlScalar(String(inner[key])))
        }
      }
      return Object.keys(out).length ? out : null
    }

    // ── 事件的"关联面"字段（这一步用到/查到了什么外部东西）──────────────────────────
    // 与"证据"分开：证据是现场材料（日志/文件），关联是外部知识（KB case / 先验词条 / 外部资料）。
    // 为什么要提：trace 里这些字段一直在写，而 traceDetail 只提 7 个字段，全被丢掉了——
    // 读者想回答"这单关联了哪些 case / 哪些 reference / 查了哪些外部资料"只能去翻 YAML。
    //
    // **两种写法都要吃**（schema 漂移，实测）：
    //   reference 单条：`ref_id: <id>`（旧 13 份都是这个）
    //   reference 多条：`ref_ids: [a, b, c]`（最新一份起）
    //   只看一种，最丰富的那份反而读不出来。
    function eventList(v) {
      if (v === undefined || v === null) return []
      if (Array.isArray(v)) return v.map(x => String(x)).filter(Boolean)
      const s = String(v).trim()
      if (!s) return []
      if (/^\[[\s\S]*\]$/.test(s)) {
        return s.slice(1, -1).split(',').map(x => x.trim().replace(/^["']|["']$/g, '')).filter(Boolean)
      }
      return [s]
    }
    const eventStr = (v, max) => (v === undefined || v === null || v === '' ? null : String(v).slice(0, max || 300))

    async function traceDetail(cwd, traceFile) {
      try {
        const target = await fs.resolve('traces/' + traceFile, { cwd })
        const text = await fs.readText(target)
        const stats = {}
        const doc = parseYaml(text, stats)
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
          // 关联面（见 eventList/eventStr 的注释）：这一步用到/查到了什么外部东西。
          // `outcome` 只对 reference_lookup 有意义——feedback 事件也有 outcome（resolved/pending），
          // 那是**回报结果**不是"先验命中"，所以 client 只在参考层步骤上渲染它（这里照原样带出）。
          caseId: eventStr(t && t.case, 80),
          candidates: eventList(t && t.candidates),
          refs: eventList(t && (t.ref_ids !== undefined ? t.ref_ids : t.ref_id)),
          purpose: eventStr(t && t.purpose, 40),
          outcome: eventStr(t && t.outcome, 20),
          note: eventStr(t && t.note, 500),
          toolCalls: eventList(t && t.tool_calls).map(x => x.slice(0, 400)),
          // 外部资料链接：**两种位置都要吃**——user 事件写在 evidence.sources 里，
          // agent 事件写成顶层 `sources:`（实测：agent 的 gh issue view / web_fetch 走后者）。
          // 只吃前者等于 agent 查到的资料一条都看不到。
          sources: (function () {
            const top = eventList(t && t.sources)
            const ev = (t && t.role === 'user' && t.evidence) ? parseEvidence(t.evidence) : null
            const inner = (ev && ev.sources) ? ev.sources : []
            return top.concat(inner).filter((u, k, a) => a.indexOf(u) === k)
          })(),
        }))
        const refCount = trace.filter(t => t && t.action === 'reference_lookup').length
        const sed = readSedimented(doc)
        const cands = Array.isArray(doc.sediment_candidates) ? doc.sediment_candidates : []
        // 定位结论的落点：`conclusion: true` 是显式标记；否则退到一条约定——**人读视图里可见的最后一条**
        // 若为 `hit`，它也当结论（老 trace 没有该标记，但末条写结论曾是个别 session 的自觉做法）。
        // 约定取的是**可见末条**：报告 / 续接 / 回报 / 归因是记录维护动作，人读视图会收起它们，
        // 所以结论不是"文件里的最后一个事件"（真实 trace 的末条常常是 report/feedback）。
        const conclusionIndex = (function () {
          for (let i = trace.length - 1; i >= 0; i--) {
            const a = trace[i] && trace[i].action ? String(trace[i].action) : null
            if (a && HOST_PROC_ACTIONS[a]) continue
            return (a === 'hit' || (trace[i] && trace[i].conclusion === true)) ? i : -1
          }
          return -1
        })()
        if (conclusionIndex >= 0 && steps[conclusionIndex]) steps[conclusionIndex].isConclusion = true
        return {
          ok: true, steps, summary: doc.summary ? String(doc.summary) : null, refCount, sedimented: sed,
          conclusionIndex: conclusionIndex,
          reportFile: (function () { const r = reportFileOf(doc, null, traceFile); return r ? r.name : null })(),
          sedimentCandidates: cands.map(c => ({
            kind: c && c.kind ? String(c.kind) : '',
            summary: c && c.summary ? String(c.summary) : '',
            suggestedSkill: c && (c.suggested_skill || c.suggestedSkill) ? String(c.suggested_skill || c.suggestedSkill) : '',
            status: c && c.status ? String(c.status) : '',
          })).filter(c => c.kind || c.summary),
          parseAnomaly: anomalyOf(stats),
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
    // 期次解析：**缩进按相对层级判定，不写死空格数**。
    //
    // 为什么（实测）：`metrics/timeline.yaml` 由 `scripts/build_timeline.py` 生成，而 PyYAML
    // 默认把序列项顶格写在键下（`periods:` 的下一行就是 `- period:`）；历史上手写的版本是
    // 2 空格缩进。旧实现把四种层级写死成 2/4/6/8 空格，于是**生成物一条期次都解析不出来**
    // ——实测真实文件解析出 0 期，而面板把"解析失败"渲染成「尚无 live 快照」（文件里有 3 期
    // live）。数据在、结论假，正是这个面板最该防的那类缺陷；解析器因此改成以 `- period:`
    // 那条的缩进为基准逐层 +2，两种形状都能读。
    function parseTimeline(text) {
      const lines = text.split(/\r?\n/)
      const periods = []
      let cur = null
      let notesIndent = 0
      let itemIndent = null      // `- period:` 那条的缩进 = 其余层级的基准
      let blockKey = null        // 块标量（`notes: |-`、`source: >-`）的目标键
      for (const raw of lines) {
        const noComment = raw.replace(/\s+#.*$/, '').trimEnd()
        if (noComment === '') { if (blockKey && cur) cur[blockKey] += '\n'; continue }
        const indent = noComment.length - noComment.trimStart().length
        const body = noComment.trimStart()
        if (blockKey && cur) {
          if (indent >= notesIndent) { cur[blockKey] += body + '\n'; continue }
          blockKey = null
        }
        if (body === 'periods:') continue
        const item = /^- (.+)$/.exec(body)
        if (item && (itemIndent === null || indent === itemIndent)) {
          if (itemIndent === null) itemIndent = indent
          if (cur) periods.push(cur)
          cur = { notes: '' }
          const fm = /^([a-zA-Z0-9_]+):\s*(.*)$/.exec(item[1])
          if (fm) cur[fm[1]] = parseFlowValue(fm[2])
          continue
        }
        if (!cur || itemIndent === null) continue
        const m = /^([a-zA-Z0-9_/-]+):\s*(.*)$/.exec(body)
        if (!m) continue
        const key = m[1]
        const v = m[2]
        const rel = indent - itemIndent
        if (rel <= 2) {
          if (key === 'metrics') { cur.metrics = {}; continue }
          // `notes: >-` 走块标量（后续更深行并入该键）；`notes: 一句话` 是行内值
          //（旧实现两种都进块模式，行内值会被整条丢掉）。
          if (v && /^[>|][-+]?$/.test(v)) { cur[key] = ''; blockKey = key; notesIndent = indent + 2; continue }
          cur[key] = parseFlowValue(v)
          continue
        }
        if (rel <= 4 && cur.metrics) {
          cur.metrics[key] = parseFlowValue(v)
          cur._lastMetricKey = key
          continue
        }
        if (cur.metrics && cur._lastMetricKey) {
          if (!cur.metrics[cur._lastMetricKey] || typeof cur.metrics[cur._lastMetricKey] !== 'object') cur.metrics[cur._lastMetricKey] = {}
          cur.metrics[cur._lastMetricKey][key] = parseFlowValue(v)
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
        // 解析完整性：文件声明了 periods 却一条期次都没解析出来 = **解析器与结构不符**，
        // 不等于"没有数据"。两者混在一起时面板会显示「尚无 live 快照」——而文件里明明有
        // （实测踩过：真实文件 3 期 live、解析 0 期、面板说没有）。所以把它作为独立字段
        // 交给客户端，由客户端分别渲染。
        const declared = /^\s*periods:/m.test(text)
        return { ok: true, periods, integrity: (declared && periods.length === 0) ? 'unparsed' : 'ok' }
      } catch (e) {
        return { ok: false, error: 'timeline.yaml 不可读: ' + String(e && e.message || e) }
      }
    }

    // ---- 人读定位报告（这单要交付出去的那份东西）----
    // 只读文本，不改写；报告名取 trace 的 `report_file`（缺字段时按同名规则回退
    // `<trace 同名>.report.md`，与 diagnose 的产出规则一致）。限长避免把整份报告塞进 RPC
    // （实测最长一份 36KB；512KB 是上限，超了如实标 truncated，由客户端提示"看全文请打开文件"）。
    const REPORT_MAX_CHARS = 512 * 1024
    async function readReport(cwd, traceFile) {
      if (!traceFile) return { ok: false, error: '缺 traceFile' }
      try {
        const traceTarget = await fs.resolve('traces/' + traceFile, { cwd })
        const doc = parseYaml(await fs.readText(traceTarget))
        // 报告名与列表侧同一口径（trace 记录 → 同名规则），否则会出现"卡片上有入口、点开找的是
        // 另一个文件名"。这里不查存在性：真读不到会由下面的 readText 如实报错。
        const resolved = reportFileOf(doc, null, traceFile)
        const name = resolved ? resolved.name : String(traceFile).replace(/\.yaml$/, '') + '.report.md'
        const rel = 'traces/' + name
        const target = await fs.resolve(rel, { cwd })
        const text = await fs.readText(target)
        const truncated = text.length > REPORT_MAX_CHARS
        return {
          ok: true,
          path: rel,
          text: truncated ? text.slice(0, REPORT_MAX_CHARS) : text,
          chars: text.length,
          truncated: truncated,
        }
      } catch (e) {
        return { ok: false, error: '报告不可读: ' + String(e && e.message || e) }
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
    //
    // —— 结果复用（为什么不是"每挂载一次跑一次"，也不是"永久缓存"）——
    // 面板切走再切回会重新挂载组件、重新发起这条 RPC，而体检要起一次 Python（实测冷启动 0.68 秒，
    // 其中大部分是 verify_references 解析 351 个 YAML 文件）。原先这里按 cwd **永久**缓存：
    // 切回确实不用等，但代价是改了脚本或数据后面板仍显示旧判决，直到插件重载——"看到的不等于现实"
    // 且没有出口。现在两头都收掉：窗口内复用（切走再切回不重跑），窗口外自动重跑，
    // 另接受 `refresh: true` 显式绕过（客户端的「重新体检」按钮走这条路，读者不必等窗口过期）。
    // 窗口取 30 秒：覆盖"来回切 tab"这一动作，又把陈旧上限压到读者能感知的量级以内。
    // 复用**失败结果**同样按窗口返回（体检不可用是稳定事实，重跑十次也是同一句提示），
    // 读者要立刻重试就点「重新体检」。
    const VERDICT_TTL_MS = 30000
    const verdictCache = new Map()   // key(cwd) → { at, promise }；存 promise 让并发挂载共享同一次体检
    function loadMetricsVerdict(cwd, force) {
      if (!shell) {
        return Promise.resolve({ ok: false, error: '体检需要 shell 服务（当前不可用）——判据与命令见 metrics/gates.yaml 与 scripts/metrics_health.py' })
      }
      const key = cwd || '?'
      const hit = verdictCache.get(key)
      if (!force && hit && (Date.now() - hit.at) < VERDICT_TTL_MS) return hit.promise
      const promise = buildMetricsVerdict(cwd)
      verdictCache.set(key, { at: Date.now(), promise: promise })
      return promise
    }
    // drift：索引头注声明的 case 数 vs 磁盘实际 case 文件数。面板读的是生成物索引，
    // 索引落后于磁盘时面板会安静地显示旧数——这类"看到的不等于现实"必须被说出来。
    async function buildMetricsVerdict(cwd) {
      const res = await runMetricsHealth(cwd)
      if (!res.ok) return res
      const v = res.verdict
      try {
        v.drift = { declared: await countIndexEntries(cwd), disk: await countCaseFiles(cwd) }
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
          sandboxPolicy: { mode: 'workspace-write', workspaceRoot: cwd },   // 见上面「跑子进程的沙箱写权限根」
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
          sandboxPolicy: { mode: 'workspace-write', workspaceRoot: cwd },   // 见上面「跑子进程的沙箱写权限根」
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

    // 交接包（跨机）：把这一单打包给另一台机器接着定位（外网定位到一半、真正的大日志在内网）。
    //
    // 与卡片上其余按钮的分工不同：那些是"生成一条复制到对话的指令"（面板不改状态），这个按钮
    // **直接干活**——它只读 trace 与证据、落一个 gitignore 的运行时件（`traces/exports/`），
    // 不动知识库、不改 trace 内容，不想要了删掉那个目录即撤销。既然可逆、又不需要语义判断，
    // 让它绕 agent 一圈（复制指令 → 粘到对话 → agent 跑脚本）只是多两步。
    async function exportHandoff(cwd, traceFile, intent) {
      const rel = 'traces/' + String(traceFile || '')
      // 文件名来自面板自己的列表，仍然按白名单卡一道：它要拼进命令行
      if (!/^traces\/[^\/\\"']+\.yaml$/.test(rel)) {
        return { ok: false, error: '非法 trace 文件名（拒绝拼命令）：' + String(traceFile) }
      }
      const wanted = String(intent || 'continue')
      const safeIntent = ['continue', 'verify', 'escalate'].indexOf(wanted) >= 0 ? wanted : 'continue'
      const manual = 'python3 scripts/export_trace.py ' + rel + ' --intent ' + safeIntent
      if (!shell) return { ok: false, error: '导出需要 shell 服务（当前不可用）。手工复现：' + manual }
      if (!cwd) {
        return { ok: false, error: '拿不到会话工作区（session.header.cwd），定位不到 scripts/export_trace.py。'
          + '手工复现：在 ascend-sleuth 检出根目录跑 ' + manual }
      }
      const py = await resolvePython()
      if (!py) {
        return { ok: false, error: '未找到可用的 Python 3 解释器（已试 python3 / python / py -3）。'
          + '手工复现：' + manual }
      }
      let r = null
      try {
        r = await shell.run(shell.resolve({
          command: py + ' scripts/export_trace.py ' + rel + ' --intent ' + safeIntent + ' --json',
          workdir: cwd,
          timeoutMs: 120000,
          stdoutMaxBytes: 262144,
          // 面板按 UTF-8 读 stdout；钉住子进程编码，防脚本侧漏掉 UTF-8 输出（Windows GBK 管道）
          env: { PYTHONIOENCODING: 'utf-8' },
          sandboxPolicy: { mode: 'workspace-write', workspaceRoot: cwd },   // 见上面「跑子进程的沙箱写权限根」
        }))
      } catch (e) {
        return { ok: false, error: '导出脚本执行失败: ' + String(e && e.message || e), manual: manual }
      }
      if (r && r.timedOut) {
        return { ok: false, error: '导出超时（120s）——证据文件很大时会偏慢。手工复现：' + manual }
      }
      // 沙箱拒绝要单独说清：它表现为子进程一句 EPERM，读者从后半段看不出是沙箱干的
      if (r && r.sandbox && r.sandbox.denied) {
        return {
          ok: false, manual: manual,
          error: '导出被沙箱拒绝（mode=' + String(r.sandbox.mode)
            + (r.sandbox.enforcement ? '，enforcement=' + String(r.sandbox.enforcement) : '')
            + '）：写权限的 workspace 根不是本会话工作区时，子进程写 ' + cwd + '/traces/exports/ 会被拒。'
            + '手工复现（不受面板沙箱限制）：' + manual,
        }
      }
      const out = r && r.stdout && typeof r.stdout.text === 'string' ? r.stdout.text : ''
      const err = r && r.stderr && typeof r.stderr.text === 'string' ? r.stderr.text : ''
      // 脚本的 stdout 末行就是 JSON（人读那几行在它前面）；逐行从后往前找第一段 '{'
      let doc = null
      const lines = out.trim().split('\n')
      for (let i = lines.length - 1; i >= 0; i--) {
        const t = lines[i].trim()
        if (t.indexOf('{') === 0) {
          try { doc = JSON.parse(t) } catch (e) { doc = null }
          break
        }
      }
      if (!doc || typeof doc !== 'object') {
        const tail = (err || out).trim().split('\n').slice(-4).join(' / ')
        return { ok: false, error: '导出脚本没有给出 JSON 结果：' + (tail || '（无输出）'), manual: manual }
      }
      if (!doc.ok) return { ok: false, error: String(doc.error || '导出失败'), manual: manual }
      // 面板的「打开目录」走 openEvidence，它拒绝绝对路径——这里换成仓库内相对路径（不在检出内就不给）
      const cwdN = String(cwd).replace(/\\/g, '/').replace(/\/+$/, '')
      const dirN = String(doc.dir || '').replace(/\\/g, '/')
      const dirRel = dirN.indexOf(cwdN + '/') === 0 ? dirN.slice(cwdN.length + 1) : null
      // **脚本吐 snake_case，面板 UI 用 camelCase——这条缝在这里收口**，别让 client 去认脚本的字段名。
      // 实测踩过：client 读 `zipBytes`/`mdBytes` 而脚本吐 `zip_bytes`/`md_bytes`，于是结果行永远显示
      // "zip 0 B + md 0 B"——文件其实是好的（196.8 KB / 71.0 KB），面板报了个假数字，读者会以为导出了空包。
      // 更糟的是当初那条断言把**错误的字段名**钉死在源码上，绿着放过了它；现在改成"client 读的键
      // host 必须都给"的成对断言（panel_render_check）。
      return Object.assign({}, doc, {
        zipBytes: doc.zip_bytes,
        mdBytes: doc.md_bytes,
        totalBytes: doc.total_bytes,
        dirRel: dirRel,
        manual: manual,
      })
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
    // ---- 权威口径是 PyYAML，不是这个解析器 ------------------------------------
    // 脚本侧读同一份 trace 用的是 PyYAML（`trace_metrics.py` / `settle_trace_feedback.py` /
    // `replay_trace.py`），面板自己写的这个子集解析器必须与它**在事件这一层**给出同样的结果。
    // 两者不一致的后果实测过：文件里 9 条事件、面板上只剩第一条，而文件本身完全正常
    // （2026-09-14，Windows 上用户报的"卡片打开只有第一步用户"）。所以这里把"合法 YAML 的形状"
    // 逐条对齐，并把**解析器没收下的行**计数出来交给面板上屏——宁可说"可能不完整"，不许
    // 静默地把一条事件当成全部。

    // 值是否以行内流集合开头（`{…}` / `[…]`）。判据要严：只有紧跟键冒号或序列 dash 的
    // `{`/`[` 才是流集合；`summary: 文本里有 {` 里的花括号是标量内容，不能当作集合接下去。
    function flowStartIndex(body) {
      let m = /^-[ \t]+([{[])/.exec(body)
      if (m) return m[0].length - 1
      m = /^[A-Za-z_][A-Za-z0-9_.-]*:[ \t]*([{[])/.exec(body)
      if (m) return m[0].length - 1
      if (body[0] === '{' || body[0] === '[') return 0
      return -1
    }
    // 从 from 起数括号深度；引号内的括号与 `\"` 转义不算（返回 0 表示已闭合）
    function flowBalance(text, from) {
      let depth = 0
      let quote = null
      for (let i = from; i < text.length; i++) {
        const ch = text[i]
        if (quote) {
          if (ch === '\\' && quote === '"') { i++; continue }
          if (ch === quote) quote = null
          continue
        }
        if (ch === '"' || ch === "'") { quote = ch; continue }
        if (ch === '{' || ch === '[') depth++
        else if (ch === '}' || ch === ']') { depth--; if (depth <= 0) return 0 }
      }
      return depth
    }
    // 解析器没收下的行（跳过或吞掉）。stats 由调用方给；不给就只算不报。
    function markDropped(cursor, row, why) {
      if (!cursor.dropped || !row) return
      cursor.dropped.push({ line: row.line, body: row.body, why: why })
    }
    // 解析器没收下的行 → 交给面板上屏的一行物证（没有就 null）。
    // 为什么要它：解析器少读几条事件时，面板上看到的步数是**错的但看不出来**——
    // 实测症状是"文件里 9 条、面板上 1 条"，读者没有任何线索知道少了。宁可说
    // "可能不完整"并给出行号，也不许把一条事件当成全部。
    function anomalyOf(stats) {
      const dropped = (stats && stats.dropped) || []
      const unbalanced = (stats && stats.unbalanced) || []
      if (!dropped.length && !unbalanced.length) return null
      return {
        dropped: dropped.length,
        firstLine: dropped.length ? (dropped[0].line || null) : (unbalanced[0] || null),
        sample: dropped.length ? String(dropped[0].body || '').slice(0, 80) : '',
        unbalancedFlow: unbalanced.length > 0,
      }
    }
    function parseYaml(text, stats) {
      // 先折算成"去注释 + 带缩进"的行表，再按缩进递归收结构
      const lines = String(text == null ? '' : text).replace(/^\uFEFF/, '').split(/\r?\n/)
      const rows = []
      for (let i = 0; i < lines.length; i++) {
        const line = splitYamlLine(lines[i])
        const body = line.trim()
        if (body === '' || body === '---') continue
        // 缩进只数 ASCII 空格与制表符。别写 `line.length - line.trimStart().length`：
        // `trimStart()` 连 U+00A0 / U+FEFF 一起吃掉，于是这类字符被算成缩进——实测（2026-09-14）
        // 带 BOM 且首行不是注释的文件，第一个键的缩进算成 1、比兄弟深一格，解析器读完
        // 第一个键就收工（整份文档只剩 `session_id`）。
        rows.push({ indent: /^[ \t]*/.exec(line)[0].length, body: body, raw: line, line: i + 1 })
      }
      // 行内流集合跨行：`- {role: user, step: 1,` + 续行是合法 YAML（长行被折行时就是这样，
      // PyYAML 照收 N 条），而旧实现逐行读，第一行之后的续行既不是新键也不是新 dash →
      // 整段被跳过，序列到此为止。这里把未闭合的流集合与后续行并成一行再解析。
      for (let i = 0; i < rows.length; i++) {
        const row = rows[i]
        const from = flowStartIndex(row.body)
        if (from < 0) continue
        let depth = flowBalance(row.body, from)
        if (depth <= 0) continue
        let j = i + 1
        while (depth > 0 && j < rows.length) {
          row.body += ' ' + rows[j].body
          depth = flowBalance(row.body, from)
          j++
        }
        // 括号始终没闭合：这份文件不是合法 YAML（PyYAML 也会拒）。别把后续内容当它的内容吞掉，
        // 如实记一行，让面板说"可能不完整"。
        if (depth > 0 && stats) (stats.unbalanced = stats.unbalanced || []).push(row.line)
        rows.splice(i + 1, j - i - 1)
      }
      if (!rows.length) return {}
      if (stats && !stats.dropped) stats.dropped = []
      const cursor = { rows: rows, i: 0, dropped: (stats && stats.dropped) || [] }
      const doc = readYamlMap(cursor, rows[0].indent)
      for (const left of rows.slice(cursor.i)) markDropped(cursor, left, '解析器没读到')
      return doc
    }
    function readYamlMap(cursor, indent) {
      const obj = {}
      while (cursor.i < cursor.rows.length) {
        const row = cursor.rows[cursor.i]
        if (row.indent < indent) break
        if (row.indent > indent) { markDropped(cursor, row, '缩进比同层更深的散行'); cursor.i++; continue }
        const m = /^([A-Za-z_][A-Za-z0-9_.-]*):(?:\s+(.*))?$/.exec(row.body)
        if (!m) { markDropped(cursor, row, '既不是键值行、也不是序列项'); cursor.i++; continue }
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
        // 序列项与键**同缩进**：PyYAML 生成的 YAML 就是这个形状（`trace:` 的下一行直接是
        // `- role: …`），YAML 规范也允许。旧实现只认"更深"，这种文件解析出 0 条事件。
        if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent === indent
          && /^-(?:\s|$)/.test(cursor.rows[cursor.i].body)) return readYamlSeq(cursor, indent)
        return ''
      }
      if (/^[|>][-+]?$/.test(rest)) return readYamlBlockScalar(cursor, indent, rest)
      if (/^-(?:\s|$)/.test(rest)) return yamlScalar(rest.replace(/^-\s*/, ''))
      // 标量续行：值非空时，比本键更深的后续行只能是这个标量的续行（YAML 里标量之后
      // 不能再跟映射）。旧实现整段跳过：`output: 第一行` 换行 `  第二行` 只读出"第一行"，
      // 而多行正文里若有一行以 `- ` 开头，还会被算成"被丢弃的事件行"。
      // 与 PyYAML 的差别：换行在此保留（PyYAML 会把普通标量的换行折成空格），内容不丢。
      if (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
        const parts = [rest]
        while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
          parts.push(cursor.rows[cursor.i].body)
          cursor.i++
        }
        return yamlScalar(parts.join('\n'))
      }
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
          const subRows = [{ indent: keyIndent, body: rest, raw: ' '.repeat(keyIndent) + rest, line: row.line }]
          while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
            subRows.push(cursor.rows[cursor.i])
            cursor.i++
          }
          // 子游标共用 dropped：这段收进来的行里若还有没人认领的（缩进既不属于本项的键、
          // 也不构成合法结构），原来的写法是**静默丢掉**——症状就是"事件少了几条而没人知道"。
          const sub = { rows: subRows, i: 0, dropped: cursor.dropped }
          arr.push(readYamlMap(sub, keyIndent))
          for (const left of subRows.slice(sub.i)) markDropped(cursor, left, '在本事件内没有归属')
          continue
        }
        // 序列项是标量（普通标量 / 引号标量 / 行内集合）时的续行：比本层更深的后续行只能是
        // 这个标量的续行（YAML 里标量之后不能再跟映射）。不并进来会有两个后果：值被截断，
        // 且那几行会被算成"被丢弃的事件行"——`tool_calls` 里一条跨行的记录就够误报一次。
        const parts = [rest]
        while (cursor.i < cursor.rows.length && cursor.rows[cursor.i].indent > indent) {
          parts.push(cursor.rows[cursor.i].body)
          cursor.i++
        }
        if (parts.length > 1) { arr.push(yamlScalar(parts.join('\n'))); continue }
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
      description: '查询 ascend-sleuth 诊断系统当前 traces/ 状态：列出所有诊断会话（session_id/status/framework/category/active_case/feedback.outcome/步骤数/更新时间）。用于诊断收尾核对、续接（/skill:resume-diagnosis）与面板待办时查看会话状态与待回报的反馈债。注意：它不是新诊断开屏的必查项——新问题的第一屏只服务新问题，别在开屏逐单追问历史 pending。',
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
    // 注册会话状态工具（面板与诊断收尾/续接时核对会话状态与待回报的反馈债；
    // **不是新诊断开屏的必查项**——旧描述把它说成"新诊断一启动就该查会话与反馈债"，
    // 与 skill 里"开屏不追问旧单"的口径相反，会把 agent 带成开屏先审旧单）。
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
      if (!fs) return needFs()
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      const r = await listTraces(cwd)
      if (!r.ok) return { ok: false, error: r.error }
      return { ok: true, sessions: r.sessions }
    })

    const detailDisposer = harness.handle('ascend-traces-detail', async (args) => {
      if (!fs) return needFs()
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
      if (!fs) return needFs()
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const traceFile = args && args.traceFile ? String(args.traceFile) : null
      const state = args && args.state ? String(args.state) : null
      const caseId = args && args.caseId ? String(args.caseId) : null
      return updateSedimented(sessionId, traceFile, state, caseId)
    })

    const metricsDisposer = harness.handle('ascend-metrics-load', async (args) => {
      if (!fs) return needFs()
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadTimeline(cwd)
    })

    // 报告正文（只读）。面板不给"写入报告"的入口——报告归 diagnose 产，见其 report-template。
    const reportDisposer = harness.handle('ascend-read-report', async (args) => {
      if (!fs) return needFs()
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const traceFile = args && args.traceFile ? String(args.traceFile) : null
      const cwd = resolveCwd(sessionId)
      return readReport(cwd, traceFile)
    })

    const healthDisposer = harness.handle('ascend-kb-health', async (args) => {
      if (!fs) return needFs()
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadHealth(cwd)
    })

    const processDisposer = harness.handle('ascend-process-health', async (args) => {
      if (!fs) return needFs()
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return loadProcessHealth(cwd)
    })

    const verdictDisposer = harness.handle('ascend-metrics-verdict', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      // `refresh: true` = 绕过复用窗口强制重跑（面板「重新体检」按钮）
      return loadMetricsVerdict(cwd, !!(args && args.refresh === true))
    })

    const liveDisposer = harness.handle('ascend-metrics-live', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const cwd = resolveCwd(sessionId)
      return runLiveMetrics(cwd)
    })

    // 导出交接包（跨机继续定位）。与 open-evidence 一样只依赖 shell，不需要 fs 服务。
    const exportDisposer = harness.handle('ascend-export-trace', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const traceFile = args && args.traceFile ? String(args.traceFile) : null
      if (!traceFile) return { ok: false, error: '缺 traceFile' }
      const cwd = resolveCwd(sessionId)
      return exportHandoff(cwd, traceFile, args && args.intent)
    })

    return () => {
      if (disposer) disposer()
      if (handleDisposer) handleDisposer()
      if (detailDisposer) detailDisposer()
      if (openDisposer) openDisposer()
      if (sedDisposer) sedDisposer()
      if (metricsDisposer) metricsDisposer()
      if (reportDisposer) reportDisposer()
      if (healthDisposer) healthDisposer()
      if (processDisposer) processDisposer()
      if (verdictDisposer) verdictDisposer()
      if (liveDisposer) liveDisposer()
      if (exportDisposer) exportDisposer()
    }
  },
}