// ev-panel host —— 自演进看板数据服务（EV 卡 / 容量 / 归因聚合 / timeline）
// 用法：cordis_define kind:new → code.host 用本文件全文；code.client 用 panel-client.js 全文。
// host 侧通过 shell 跑 scripts/ev_board_data.py 汇总 JSON（确定性逻辑在脚本，遵循原则二）。
// 同一张 RPC 分发表也承载整页「Ascend Sleuth」知识库子页的三条端点
// （`ascend-kb-sync-*`）：它们与自演进同属全库读数，数据同样全由脚本产出。
return {
  apply(ctx) {
    // **没有 fs 守卫**：本插件不读数据文件——数据全由 `shell` 跑 Python 脚本产出
    // （`ev_board_data.py` / `evolution_health.py`）。原先照抄 ascend-panel 写的是
    // `const fs = ctx.get('fs'); if (fs === undefined) return`，后果是 fs 服务缺席时
    // **整个插件什么都不注册**（两个 RPC 全没、tab 点开即死）。fs 现在只用来挑会话（见下），
    // 缺席就退回"会话列表第一个带 cwd 的"，不影响注册与数据读取。
    // 退化是**逐调用**的：`shell` 缺 → runScript 返回「shell 不可用」；工作区缺 →
    // 「无法解析工作区」。两者都有断言（panel_render_check 的 `[ev-panel host 失败路径]` 一节）。
    const sessions = ctx.get('sessions')
    const shell = ctx.get('shell')
    // 会话的沙箱档位（显式授予 > 会话最后一条 sandbox/mode 事件 > 部署默认）。服务缺席时
    // readPolicy 返回 undefined，调用点把策略省掉、交回 shell 默认，行为与改动前一致。
    const sandboxPolicySvc = ctx.get('sandboxPolicy')
    // 仅用于**挑会话**：整页面板没有会话上下文时要判断哪个会话的工作目录能跑数据脚本
    // （列一次 `scripts/` 看有没有 `ev_board_data.py`）。看板的数据文件仍然只经 shell 由 Python 读，
    // 本插件不读任何数据文件——fs 缺席时退回"会话列表第一个带 cwd 的"，与改动前一致。
    const fsSvc = ctx.get('fs')

    function sessionCwds() {
      if (!sessions || typeof sessions.list !== 'function') return []
      try {
        const out = []
        for (const s of sessions.list() || []) {
          const c = s && s.header && s.header.cwd ? String(s.header.cwd) : ''
          if (c && out.indexOf(c) < 0) out.push(c)
        }
        return out
      } catch (e) {
        return []
      }
    }
    async function looksLikeBoardRoot(dir) {
      if (!fsSvc || !dir) return false
      try {
        const entries = (await fsSvc.listDir(await fsSvc.resolve('scripts', { cwd: dir }))) || []
        return entries.some(e => e && e.name === 'ev_board_data.py')
      } catch (e) {
        return false
      }
    }
    async function resolveCwd(sessionId) {
      let direct
      if (sessions && sessionId) {
        let s = null
        try { s = sessions.get(sessionId) } catch (e) { s = null }
        if (s && s.header && s.header.cwd) direct = String(s.header.cwd)
      }
      if (direct && await looksLikeBoardRoot(direct)) return direct
      // 整页面板没有会话上下文（sessionId 为空）→ 退到"会话列表里能跑看板的那一个"。
      // **不能取第一个带 cwd 的**：DSH 默认工作区留下过一个空会话、在会话列表里排在前面，取第一个
      // 会把脚本路径算到那个空目录（2026-11-03 实测：`python3 scripts/ev_board_data.py` 报 can't open file）。
      const list = sessionCwds()
      for (const c of list) {
        if (c !== direct && await looksLikeBoardRoot(c)) return c
      }
      return direct || (list.length ? list[0] : undefined)
    }

    // 只读脚本的沙箱档位 = 本会话自己选的那一档。**刻意与 ascend-panel 重复**（同 resolvePython）：
    // dynamic Cordis 插件不能 import，两边各留一份副本。写死 `workspace-write` 会在受限令牌
    // runner 起不来子进程的机器上把看板一起堵死（实测：三条候选全返回 3221225794 = 0xC0000142）。
    function readPolicy(sessionId) {
      if (!sandboxPolicySvc || typeof sandboxPolicySvc.resolve !== 'function') return undefined
      let session = null
      try { session = sessions && sessionId ? sessions.get(sessionId) : null } catch (e) { session = null }
      // 无会话（整页面板）时用"第一个带 cwd 的会话"的档位。不传 session 会落到部署默认
      //（workspace-write + launch-root），在受限令牌 runner 上子进程起不来，界面只剩
      //「找不到 Python」——那是误导：解释器在、是沙箱把进程挡在启动之前。
      if (session === null && sessions && typeof sessions.list === 'function') {
        try {
          for (const s of sessions.list() || []) {
            if (s && s.header && s.header.cwd) { session = s; break }
          }
        } catch (e) {
          session = null
        }
      }
      try {
        const policy = session ? sandboxPolicySvc.resolve({ session: session }) : sandboxPolicySvc.resolve()
        if (policy && typeof policy.mode === 'string') return policy
      } catch (e) {
        return undefined
      }
      return undefined
    }

    function policyNote(policy) {
      if (!policy) return '沙箱档位：未指定（跟随 shell 默认）'
      return '沙箱档位：' + String(policy.mode) + (policy.workspaceRoot ? '，根 ' + String(policy.workspaceRoot) : '')
    }

    // 子进程根本没起来（NTSTATUS / 负数退出码 / runner 的 127+方言）——与"没装 Python"是两回事。
    function looksLikeSpawnFailure(exitCode, text) {
      const code = Number(exitCode)
      if (Number.isFinite(code) && code < 0) return true
      if (Number.isFinite(code) && code >= 0xC0000000) return true
      if (code === 127 && /windows-acl-run|sandbox/i.test(String(text || ''))) return true
      return false
    }

    // Python 解释器解析（Windows 兼容）：面板用 shell 跑 Python 脚本，但 Windows 上
    // `python3` 常不存在——python.org 安装器装的是 `python.exe` + `py.exe` 启动器；
    // 若 PATH 里还有 Store 的「应用执行别名」占位程序，执行 `python3` 不报"找不到命令"
    // 而是弹 Microsoft Store。因此按候选逐个探测，取第一个能打印 Python 3.x 的
    // （退出码 0 + 版本号双重判据，占位程序两者都过不了）；成功缓存、失败不缓存（环境修好后自愈）。
    // 注意：dynamic Cordis 插件不能 import，此函数与 ascend-panel 的同名函数是刻意重复的副本。
    // 探活**跟随会话档位**（见 readPolicy）：写死 workspace-write 会在受限令牌 runner 起不来
    // 子进程的机器上让三条候选全挂，而报出来只有一句「未找到 Python」——真因被吞。
    let pythonCmd
    async function resolvePython(cwd, policy) {
      if (pythonCmd !== undefined) return pythonCmd
      let lastError = ''
      let spawnFailed = false
      for (const candidate of ['python3', 'python', 'py -3']) {
        try {
          const spec = shell.resolve({
            command: candidate + ' --version',
            workdir: cwd,
            stdoutMaxBytes: 4096,
            ...(policy ? { sandboxPolicy: policy } : {}),
          })
          const r = await shell.run(spec)
          const out = [r && r.stdout && r.stdout.text, r && r.stderr && r.stderr.text]
            .filter(t => typeof t === 'string').join('\n')
          if (r && r.exitCode === 0 && /Python 3\./.test(out)) {
            pythonCmd = candidate
            resolvePython.lastError = ''
            return pythonCmd
          }
          if (looksLikeSpawnFailure(r && r.exitCode, out)) spawnFailed = true
          lastError = candidate + ' 退出码 ' + String(r && r.exitCode) + '：' + (out.trim() || '（无输出）').slice(0, 200)
        } catch (e) {
          // 候选不可执行 → 试下一个；异常原文要留下来，否则报出来只有那句误导的「没找到 Python」
          lastError = candidate + ' 执行失败：' + String(e && e.message || e).slice(0, 300)
        }
      }
      // 失败**不进缓存**：解释器或执行环境修好后，下一次调用就自愈，不必重载面板。
      // 内网 Win11 现场：工作区文件权限修好后，面板仍一直报同一句错，直到重载插件——
      // 旧写法的 `pythonCmd = null` 把这次失败当成了结论（`null !== undefined`）。
      resolvePython.lastError = spawnFailed
        ? lastError + '\n（三条候选都是"进程起来了但初始化失败"，即受限环境把子进程挡在启动之前：'
          + '这与解释器有没有装、装在哪都无关。本会话若已是「完全权限」仍如此，属平台侧沙箱问题。）'
        : lastError
      return null
    }

    async function runScript(sessionId, scriptName, extraArgs) {
      const cwd = await resolveCwd(sessionId)
      if (!cwd) return { ok: false, error: '无法解析工作区' }
      if (!shell) return { ok: false, error: 'shell 不可用' }
      const policy = readPolicy(sessionId)
      const py = await resolvePython(cwd, policy)
      if (!py) {
        return { ok: false, error: '未找到可用的 Python 3 解释器（已试 python3 / python / py -3）——'
          + '自演进看板的数据脚本 ' + scriptName + ' 需要它，装好 Python 3 并确保在 PATH 里'
          + '\n' + policyNote(policy)
          + (resolvePython.lastError ? '\n探测失败原因：' + resolvePython.lastError : '') }
      }
      try {
        const spec = shell.resolve({
          command: py + ' ' + scriptName + (extraArgs ? ' ' + extraArgs : ''),
          workdir: cwd,
          stdoutMaxBytes: 4 * 1024 * 1024, // EV 卡聚合 JSON 随库增长（实测 89KB），防截断
          // 面板按 UTF-8 读 stdout；钉住子进程编码，防脚本侧漏掉 UTF-8 输出（Windows GBK 管道）
          env: { PYTHONIOENCODING: 'utf-8' },
          // 只读脚本 → 跟随会话档位（与诊断面板同一规则：写死 workspace-write 会在受限令牌
          // runner 起不来子进程的机器上把看板一起堵死）
          ...(policy ? { sandboxPolicy: policy } : {}),
        })
        const r = await shell.run(spec)
        const stdout = r && r.stdout && typeof r.stdout.text === 'string' ? r.stdout.text : ''
        if (!stdout.trim()) {
          const stderrStr = r && r.stderr && typeof r.stderr.text === 'string' ? r.stderr.text : ''
          if (looksLikeSpawnFailure(r && r.exitCode, stderrStr)) {
            return { ok: false, error: '自演进看板的数据脚本没跑起来：子进程在受限环境里被挡在启动之前'
              + '（与 Python / PyYAML 是否安装无关）——' + policyNote(policy)
              + '\n脚本 ' + scriptName + '（工作目录 ' + cwd + '）'
              + '\n手工复现：在仓库根目录执行 ' + py + ' ' + scriptName + (extraArgs ? ' ' + extraArgs : '')
              + '\n退出码 ' + String(r && r.exitCode) + '；把本会话切到「完全权限」或按平台侧沙箱问题处理。' }
          }
          if (/no module named ['\"]?yaml/i.test(stderrStr)) {
            return { ok: false, error: '运行自演进看板需要 PyYAML——面板实际按解释器 ' + py + ' 跑，'
              + '要给这个解释器装：' + py + ' -m pip install pyyaml（' + policyNote(policy) + '）后重开面板' }
          }
          const err = stderrStr || scriptName + ' 无输出'
          return { ok: false, error: String(err).slice(0, 800) }
        }
        let data = null
        try {
          data = JSON.parse(stdout)
        } catch (e) {
          return { ok: false, error: scriptName + ' 输出非 JSON: ' + String(e && e.message || e) }
        }
        return { ok: true, data }
      } catch (e) {
        // 走到这里的常见成因是**执行环境**问题而不是数据问题：受限环境不允许创建管道
        // （Windows 上报 `PermissionError: [WinError 5] 拒绝访问`）。原先只说一句
        // "看板数据读取失败: <msg>"，读者既不知道是哪个脚本、也没有手工复现的路。
        // 补齐三样：脚本名与工作目录、可复制的手工复现命令、以及"这不是数据问题"的判断。
        const msg = String(e && e.message || e)
        return { ok: false, error: '看板数据读取失败: ' + msg
          + '\n脚本 ' + scriptName + '（工作目录 ' + cwd + '）'
          + '\n手工复现：在仓库根目录执行 ' + py + ' ' + scriptName + (extraArgs ? ' ' + extraArgs : '')
          + '\n若提示拒绝访问 / EPERM，是执行环境不允许创建管道所致，与数据无关。' }
      }
    }

    const BOARD_SCRIPT = 'scripts/ev_board_data.py'
    const HEALTH_SCRIPT = 'scripts/evolution_health.py'

    function loadBoard(sessionId) {
      return runScript(sessionId, BOARD_SCRIPT, null)
    }

    // 判决层：与「指标」tab 拉 metrics_health 同形。为什么单独一次调用而不是并进 board：
    // 判决来自 evolution_health.py（判据在 proposals/gates.yaml），一次失败不该影响另一块；
    // 合并会让"体检器坏了"与"没有数据"在客户端再次混成一个错误。
    function loadHealth(sessionId) {
      return runScript(sessionId, HEALTH_SCRIPT, '--json')
    }

    // —— 结果复用：两个脚本各自要起一次 Python（实测 0.76 秒 / 1.09 秒，换 libyaml 后端后
    // 0.36 秒 / 0.32 秒），而面板每次切回 tab 都会重新挂载组件、重新发起这两条 RPC。
    // 同一份数据在几十秒内不会变，重复起进程只是让读者等。
    // 窗口取 30 秒：覆盖"切走再切回"，又把陈旧上限压在读者能感知的量级以内；
    // `refresh: true`（面板「刷新」按钮）显式绕过窗口。
    // 缓存的是结果本身，**含失败**——失败同样按窗口返回（脚本缺依赖是稳定事实），
    // 要立刻重试就点「刷新」。界面上的数据时间戳（`generated_at`）照旧是脚本生成时刻，
    // 复用不会把它刷新成"现在"，读者看到的时间就是这份数据的真实生成时刻。
    const CACHE_TTL_MS = 30000
    const resultCache = new Map()   // key → { at, promise }；存 promise 让并发挂载共享同一次执行
    function cached(key, force, run) {
      const hit = resultCache.get(key)
      if (!force && hit && (Date.now() - hit.at) < CACHE_TTL_MS) return hit.promise
      const promise = run()
      resultCache.set(key, { at: Date.now(), promise: promise })
      return promise
    }

    // 单卡全文：面板点开某张卡时才拉（列表页只带摘要，不把 36 张卡的完整决策链
    // 一次性塞进客户端）。id 只放行 EV-YYYY-NNN 形状，防 shell 注入。
    function loadIdeaDetail(sessionId, ideaId) {
      const id = String(ideaId || '')
      if (!/^EV-\d{4}-\d{3,}$/.test(id)) return Promise.resolve({ ok: false, error: '非法卡 id: ' + id })
      return runScript(sessionId, BOARD_SCRIPT, '--detail ' + id)
    }

    // ── 知识库子页：同步源、同步状态与同步动作 ──────────────────────────────
    //
    // 整页「Ascend Sleuth」的第三个子页（知识库）。与自演进同一取舍：读数全由脚本产出
    // （`scripts/kb_sync.py` / `scripts/pr_status.py`），本插件不读数据文件、不改 git。
    // 打开页面只跑 `--show` 与两条只读查询（都不联网）；点「立即同步」才跑 `--merge`。
    // 配置写 `.local/settings.json`，经 `pr_status.py --set-sync` 落盘。
    const KB_SYNC_SCRIPT = 'scripts/kb_sync.py'
    const PR_STATUS_SCRIPT = 'scripts/pr_status.py'

    // 仓库根：判据取 `scripts/pr_status.py`（本机已有），**不拿 kb_sync.py 当判据**——
    // 同步脚本还没落地时仍要能列出远端、并给出「脚本缺失」的降级，而不是把整页报成
    // "解析不到工作区"（那会把缺一个文件说成缺一个会话）。
    async function looksLikeSleuthRoot(dir) {
      if (!fsSvc || !dir) return false
      try {
        const entries = (await fsSvc.listDir(await fsSvc.resolve('scripts', { cwd: dir }))) || []
        return entries.some(e => e && e.name === 'pr_status.py')
      } catch (e) {
        return false
      }
    }
    async function resolveSyncCwd(sessionId) {
      let direct
      if (sessions && sessionId) {
        let s = null
        try { s = sessions.get(sessionId) } catch (e) { s = null }
        if (s && s.header && s.header.cwd) direct = String(s.header.cwd)
      }
      if (direct && await looksLikeSleuthRoot(direct)) return direct
      const list = sessionCwds()
      for (const c of list) {
        if (c !== direct && await looksLikeSleuthRoot(c)) return c
      }
      return direct || (list.length ? list[0] : undefined)
    }

    function syncStr(v) {
      return v === null || v === undefined ? '' : String(v)
    }
    function syncNum(v) {
      const n = Number(v)
      return Number.isFinite(n) ? n : null
    }
    // 脚本可能把 JSON 夹在别的输出里（git 自己的提示、Python 的告警），取最外层对象。
    function syncJsonOf(text) {
      const s = String(text || '').trim()
      if (!s) return null
      try { return JSON.parse(s) } catch (e) { /* 继续找最外层对象 */ }
      const start = s.indexOf('{')
      const end = s.lastIndexOf('}')
      if (start < 0 || end <= start) return null
      try { return JSON.parse(s.slice(start, end + 1)) } catch (e) { return null }
    }
    // 进程级失败（非 0 退出、超时、输出非 JSON）按原因分类。业务失败另由 syncReasonOf 分。
    function syncFailureOf(scriptName, text, exitCode, timedOut) {
      const t = String(text || '')
      const head = t.trim().split(/\r?\n/).filter(Boolean)[0] || ''
      if (timedOut) return { code: 'E_TIMEOUT', message: '脚本 ' + scriptName + ' 超时' }
      if (/can't open file|No such file or directory/i.test(t)
        && t.indexOf(scriptName.replace(/^scripts\//, '')) >= 0) {
        return { code: 'E_NO_SCRIPT', message: '脚本 ' + scriptName + ' 不存在' }
      }
      if (/not a git repository/i.test(t)) return { code: 'E_NOT_GIT', message: '当前目录不是 git 检出' }
      if (/unrecognized arguments|invalid choice|the following arguments are required|error: argument/i.test(t)) {
        return { code: 'E_UNSUPPORTED', message: '脚本 ' + scriptName + ' 不支持这次调用的参数' }
      }
      if (/permission denied|operation not permitted|EPERM|EACCES/i.test(t)) {
        return { code: 'E_PERM', message: '当前会话不能写仓库' }
      }
      return { code: 'E_SCRIPT', message: '脚本 ' + scriptName + ' 退出码 ' + String(exitCode) + (head ? '：' + head.slice(0, 200) : '') }
    }

    // 跑一条同步脚本：工作目录 = 仓库根；只读与写动作都跟随会话自己的沙箱档位
    // （与自演进同一取舍：写死 workspace-write 会在受限令牌 runner 上把子进程挡在启动前）。
    async function runSyncScript(sessionId, scriptName, argv, timeoutMs) {
      const cwd = await resolveSyncCwd(sessionId)
      if (!cwd) return { ok: false, code: 'E_NO_CWD', message: '解析不到仓库目录', cwd: null }
      if (!shell) return { ok: false, code: 'E_SHELL', message: 'shell 服务不可用', cwd: cwd }
      const policy = readPolicy(sessionId)
      const py = await resolvePython(cwd, policy)
      if (!py) {
        return { ok: false, code: 'E_PYTHON', message: '找不到 Python 3 解释器', cwd: cwd,
          detail: resolvePython.lastError ? String(resolvePython.lastError).slice(0, 400) : '' }
      }
      const command = py + ' ' + scriptName + (argv ? ' ' + argv : '')
      let r
      try {
        r = await shell.run(shell.resolve({
          command: command,
          workdir: cwd,
          timeoutMs: timeoutMs || 20000,
          stdoutMaxBytes: 4 * 1024 * 1024,
          env: { PYTHONIOENCODING: 'utf-8' },
          ...(policy ? { sandboxPolicy: policy } : {}),
        }))
      } catch (e) {
        return { ok: false, code: 'E_SCRIPT', message: '脚本执行失败', cwd: cwd, command: command,
          detail: String(e && e.message || e).slice(0, 400) }
      }
      const stdout = r && r.stdout && typeof r.stdout.text === 'string' ? r.stdout.text : ''
      const stderr = r && r.stderr && typeof r.stderr.text === 'string' ? r.stderr.text : ''
      const failed = !r || r.timedOut || r.aborted || Number(r.exitCode) !== 0
      if (failed) {
        const why = syncFailureOf(scriptName, (stderr || stdout), r && r.exitCode, !!(r && r.timedOut))
        return { ok: false, code: why.code, message: why.message, cwd: cwd, command: command,
          exitCode: r && r.exitCode, detail: String(stderr || stdout || '').trim().slice(0, 600) }
      }
      const data = syncJsonOf(stdout)
      if (data === null) {
        return { ok: false, code: 'E_BAD_OUTPUT', message: '脚本输出不是 JSON', cwd: cwd, command: command,
          detail: String(stdout || stderr).trim().slice(0, 400) }
      }
      return { ok: true, data: data, cwd: cwd, command: command }
    }
    function syncDocOf(result) {
      if (!result || result.ok !== true) return null
      const raw = result.data
      if (!raw || typeof raw !== 'object') return null
      return raw.data && typeof raw.data === 'object' ? raw.data : raw
    }
    // 脚本把失败写在 JSON 信封里（exit 0 + {ok:false,error:{code,message}}）也算失败。
    function syncEnvelopeError(doc) {
      if (!doc || typeof doc !== 'object' || doc.ok !== false) return null
      const err = doc.error && typeof doc.error === 'object' ? doc.error : null
      if (!err) return null
      return { code: String(err.code || 'E_SCRIPT'), message: String(err.message || '脚本报错') }
    }
    // kb_sync 的业务失败写在 `reason` 里（脚本一律 exit 0）：这些取值 → 面板的失败码。
    function syncReasonOf(reason) {
      const r = String(reason || '')
      if (!r) return null
      if (r === 'timeout') return { code: 'E_TIMEOUT', message: 'fetch 超时' }
      if (r === 'lock') return { code: 'E_LOCK', message: '远端的引用锁被占用' }
      if (r === 'no-remote') return { code: 'E_NO_REMOTE', message: '配置的远端不存在' }
      if (r === 'not-a-repo') return { code: 'E_NOT_GIT', message: '当前目录不是 git 检出' }
      if (r === 'disabled') return { code: 'E_DISABLED', message: '同步已关闭（个人设置）' }
      if (r === 'offline') return { code: 'E_OFFLINE', message: '离线部署（deployment.yaml）' }
      if (r === 'dirty') return { code: 'E_DIRTY', message: '工作区有未提交改动' }
      if (r === 'not-ff' || r === 'not-ancestor') return { code: 'E_NOT_FF', message: '本地提交不能快进' }
      if (r === 'branch-mismatch') return { code: 'E_BRANCH', message: '当前不在配置分支上' }
      if (r === 'merge-in-progress') return { code: 'E_MERGE_IN_PROGRESS', message: '上一次合并还没结束' }
      if (r === 'auto-merge-off') return { code: 'E_AUTO_MERGE_OFF', message: '自动合并已关闭' }
      if (r === 'same-repo') return { code: 'E_SAME_REPO', message: '配置远端与 origin 不同源' }
      if (r === 'status-failed') return { code: 'E_SCRIPT', message: 'git status 读取失败' }
      if (/^exit-\d+$/.test(r)) return { code: 'E_FETCH', message: 'fetch 退出码 ' + r.slice(5) }
      return { code: 'E_SCRIPT', message: '同步脚本报错：' + r }
    }
    // 同步状态分两种结局：读不到（ok=false），与读到了但状态是关闭 / 离线 / 失败（state）。
    // 后者仍带着本机读数（本机版本、落后数），页面不该因此整块空白。
    //
    // 状态以 `--show --json` 的真实字段为准：`enabled`（bool）、`offline`（bool）、
    // `reason`（串）。关闭与离线都是**状态**（脚本回 ok=false），不是读不到：
    //   enabled:false → ok:false, reason:"disabled"
    //   offline:true  → ok:false, offline:true, reason:"offline"
    // 面板不自己拼这两条输出，只读脚本给的取值；`reason` 仍用于超时 / 无远端 / 非检出等失败。
    function syncStatusOf(result) {
      if (!result || result.ok !== true) {
        return { ok: false, code: (result && result.code) || 'E_SCRIPT',
          message: (result && result.message) || '读不到同步状态',
          detail: result && result.detail ? String(result.detail) : '' }
      }
      const doc = syncDocOf(result)
      if (!doc) return { ok: false, code: 'E_BAD_OUTPUT', message: '同步状态不是对象', detail: '' }
      const env = syncEnvelopeError(doc)
      if (env) return { ok: false, code: env.code, message: env.message, detail: '' }
      const reason = syncStr(doc.reason)
      if (doc.ok === false && reason === 'not-a-repo') {
        return { ok: false, code: 'E_NOT_GIT', message: '当前目录不是 git 检出', detail: '' }
      }
      // 脚本的真实字段；旧脚本没带这两个开关时按"开"处理，不把缺字段读成关闭。
      const enabled = doc.enabled !== false && doc.enabled !== 'false'
      let offline = doc.offline === true || doc.offline === 'true'
        || (doc.offline !== null && typeof doc.offline === 'object' && doc.offline.declared === true)
      // 兼容只给 reason 的旧脚本：两个开关字段缺席时，reason 是唯一能判断状态的来源。
      if (reason === 'offline') offline = true
      const offlineSource = offline ? 'deployment.yaml' : ''
      const sameRepoRaw = doc.same_repo
      const sameRepo = sameRepoRaw === true ? true : (sameRepoRaw === false ? false : null)
      const data = {
        remote: syncStr(doc.remote),
        branch: syncStr(doc.branch),
        local_rev: syncStr(doc.local_rev),
        remote_rev: syncStr(doc.remote_rev),
        behind: syncNum(doc.behind),
        ahead: syncNum(doc.ahead),
        skipped: doc.skipped === true,
        last_checked: syncStr(doc.last_checked) || syncStr(doc.last_ok_at) || syncStr(doc.attempted_at) || null,
        last_reason: syncStr(doc.last_reason) || reason,
        enabled: enabled,
        offline: offline,
        offline_source: offlineSource,
        reason: reason,
        same_repo: sameRepo,
        config: null,
      }
      if (offline) {
        return { ok: true, data: data, state: 'offline',
          error: { code: 'E_OFFLINE', message: '离线部署（deployment.yaml）' } }
      }
      if (!enabled) {
        return { ok: true, data: data, state: 'disabled',
          error: { code: 'E_DISABLED', message: '同步已关闭（个人设置）' } }
      }
      if (doc.ok !== false) {
        return { ok: true, data: data, state: 'ok', error: null }
      }
      // `--show` 在"没配远端"与"远端分支还没 fetch 过"时也回 ok=false，但 reason 是空的：
      // 这两种是状态（不是故障），页面仍要显示本机读数与下一步。
      if (!reason) {
        if (!data.remote) return { ok: true, data: data, state: 'no-remote', error: null }
        if (!data.remote_rev) return { ok: true, data: data, state: 'unfetched', error: null }
      }
      const why = syncReasonOf(reason) || { code: 'E_SCRIPT', message: '同步状态读取失败' }
      if (why.code === 'E_OFFLINE') {
        data.offline = true
        data.offline_source = 'deployment.yaml'
        return { ok: true, data: data, state: 'offline', error: why }
      }
      if (why.code === 'E_DISABLED') {
        data.enabled = false
        return { ok: true, data: data, state: 'disabled', error: why }
      }
      return { ok: true, data: data, state: 'error', error: why }
    }
    // `pr_status.py --json`（无 flag 时是 status）：settings 段里的 sync 与配置来源。
    function syncSettingsOf(result) {
      if (!result || result.ok !== true) {
        return { ok: false, code: (result && result.code) || 'E_SCRIPT',
          message: (result && result.message) || '读不到本机设置',
          detail: result && result.detail ? String(result.detail) : '' }
      }
      const doc = syncDocOf(result)
      if (!doc) return { ok: false, code: 'E_BAD_OUTPUT', message: '设置不是对象', detail: '' }
      const env = syncEnvelopeError(doc)
      if (env) return { ok: false, code: env.code, message: env.message, detail: '' }
      const settings = doc.settings && typeof doc.settings === 'object' ? doc.settings : null
      if (!settings) return { ok: false, code: 'E_BAD_OUTPUT', message: '设置段不存在', detail: '' }
      const sync = settings.sync && typeof settings.sync === 'object' ? settings.sync : null
      const target = settings.target && typeof settings.target === 'object' ? settings.target : null
      return { ok: true, data: {
        config: syncStr(settings.config) || 'default',
        problem: syncStr(settings.problem),
        path: syncStr(settings.path),
        sha256: syncStr(doc.settings_sha256),
        sync: sync ? {
          remote: syncStr(sync.remote),
          branch: syncStr(sync.branch),
          enabled: sync.enabled !== false,
          auto_merge: sync.auto_merge !== false,
        } : null,
        target: target ? { remote: syncStr(target.remote), base: syncStr(target.base) } : null,
      } }
    }
    // 两个开关与配置来源：优先本机设置（`pr_status.py --json`），脚本自带 config 对象时也认。
    function syncConfigOf(settingsPart, syncData) {
      if (settingsPart && settingsPart.ok === true && settingsPart.data.sync) {
        const cfgSync = settingsPart.data.sync
        return {
          auto_check: cfgSync.enabled !== false,
          auto_merge: cfgSync.auto_merge !== false,
          source: settingsPart.data.config === 'file' ? 'personal' : 'default',
          path: settingsPart.data.path || '.local/settings.json',
        }
      }
      const raw = syncData && syncData.config
      if (raw && typeof raw === 'object') return raw
      return null
    }
    function syncTargetsOf(result) {
      if (!result || result.ok !== true) {
        return { ok: false, code: (result && result.code) || 'E_SCRIPT',
          message: (result && result.message) || '读不到远端列表',
          detail: result && result.detail ? String(result.detail) : '' }
      }
      const doc = syncDocOf(result)
      if (!doc) return { ok: false, code: 'E_BAD_OUTPUT', message: '远端列表不是对象', detail: '' }
      const env = syncEnvelopeError(doc)
      if (env) return { ok: false, code: env.code, message: env.message, detail: '' }
      const remotes = Array.isArray(doc.remotes) ? doc.remotes.map(r => ({
        name: syncStr(r && r.name),
        url: syncStr(r && r.url),
        host: syncStr(r && r.host),
        base: syncStr(r && r.base),
        last_used: r && r.last_used ? String(r.last_used) : '',
        platform: syncStr(r && r.platform),
        platform_name: syncStr(r && r.platform_name),
      })).filter(r => r.name) : []
      const target = doc.target && typeof doc.target === 'object'
        ? { remote: syncStr(doc.target.remote), base: syncStr(doc.target.base) } : null
      return { ok: true, data: { remotes: remotes, target: target, recommendation: doc.recommendation || null } }
    }
    // 远端名、分支名与 CAS 令牌会拼进命令行：只放行不含空白与 shell 元字符的取值。
    function syncSafeRef(value) {
      return /^[^\s'"`$;&|<>\\]{1,120}$/.test(String(value || ''))
    }

    const handleDisposer = harness.handle('ev-board-load', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      return cached('board|' + (await resolveCwd(sessionId) || '?'), !!(args && args.refresh === true),
        () => loadBoard(sessionId))
    })

    const healthDisposer = harness.handle('ev-health-load', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      return cached('health|' + (await resolveCwd(sessionId) || '?'), !!(args && args.refresh === true),
        () => loadHealth(sessionId))
    })

    const detailDisposer = harness.handle('ev-idea-detail', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const ideaId = args && args.ideaId ? String(args.ideaId) : ''
      const r = await loadIdeaDetail(sessionId, ideaId)
      if (!r.ok) return r
      const payload = r.data || {}
      if (payload.ok === false) return { ok: false, error: payload.error || '读取失败' }
      return { ok: true, idea: payload.idea }
    })

    // 一次读全：同步状态 + 本机设置 + 远端清单。三段各自成败——kb_sync.py 缺失时
    // 仍要能列远端、读到两个开关，而不是整页只剩一句"读不到"。
    const kbShowDisposer = harness.handle('ascend-kb-sync-show', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const syncRaw = await runSyncScript(sessionId, KB_SYNC_SCRIPT, '--show --json', 20000)
      const settingsRaw = await runSyncScript(sessionId, PR_STATUS_SCRIPT, '--json', 20000)
      const targetsRaw = await runSyncScript(sessionId, PR_STATUS_SCRIPT, '--list-targets --json', 20000)
      const settingsPart = syncSettingsOf(settingsRaw)
      const syncPart = syncStatusOf(syncRaw)
      if (syncPart.ok === true) syncPart.data.config = syncConfigOf(settingsPart, syncPart.data)
      return {
        ok: true,
        cwd: syncRaw.cwd || settingsRaw.cwd || targetsRaw.cwd || null,
        config_path: (settingsPart.ok === true && settingsPart.data.path) || '.local/settings.json',
        settings_sha256: settingsPart.ok === true ? settingsPart.data.sha256 : '',
        sync: syncPart,
        settings: settingsPart,
        targets: syncTargetsOf(targetsRaw),
      }
    })

    // 「立即同步」：只有这一个动作会碰远端（fetch + 条件合并都在脚本里，面板不拼 git）。
    const kbMergeDisposer = harness.handle('ascend-kb-sync-merge', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const r = await runSyncScript(sessionId, KB_SYNC_SCRIPT, '--merge --json', 180000)
      if (!r.ok) return { ok: false, code: r.code, message: r.message, cwd: r.cwd || null, detail: r.detail || '' }
      const doc = syncDocOf(r) || {}
      const env = syncEnvelopeError(doc)
      if (env) return { ok: false, code: env.code, message: env.message, cwd: r.cwd || null, detail: '' }
      if (doc.ok === false) {
        const why = syncReasonOf(doc.reason) || { code: 'E_SCRIPT', message: '同步失败' }
        return { ok: false, code: why.code, message: why.message, cwd: r.cwd || null,
          offline: why.code === 'E_OFFLINE', detail: '' }
      }
      const merged = String(doc.merge || '') === 'ff-only'
      const blocked = merged ? null : syncReasonOf(doc.reason)
      return {
        ok: true,
        cwd: r.cwd || null,
        merged: merged,
        merged_rev: merged ? syncStr(doc.local_rev) : '',
        previous_rev: merged ? syncStr(doc.local_rev_before) : '',
        behind: merged ? syncNum(doc.behind_before) : syncNum(doc.behind),
        reason_code: blocked ? blocked.code : '',
        reason_text: blocked ? blocked.message : '',
      }
    })

    // 「保存」：写 `.local/settings.json` 的 sync 段（远端 / 分支 / 两个开关）。
    // 两个开关在脚本里的名字：自动检查更新 = `sync.enabled`（--enable / --disable），
    // 自动合并 = `sync.auto_merge`（--auto-merge on|off）。CAS 令牌用读到的那份设置指纹。
    const kbSaveDisposer = harness.handle('ascend-kb-sync-save', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      const remote = args && args.remote ? String(args.remote).trim() : ''
      const branch = args && args.branch ? String(args.branch).trim() : ''
      const expect = args && args.expectSha256 ? String(args.expectSha256).trim() : ''
      if (!remote) return { ok: false, code: 'E_ARGS', message: '没有选远端' }
      if (!syncSafeRef(remote) || (branch && !syncSafeRef(branch))) {
        return { ok: false, code: 'E_ARGS', message: '远端或分支名含不支持的字符' }
      }
      if (expect && !/^[0-9a-f]{64}$/i.test(expect)) {
        return { ok: false, code: 'E_ARGS', message: '设置指纹不是 64 位十六进制' }
      }
      const autoCheck = args && args.autoCheck === true
      const autoMerge = args && args.autoMerge === true
      const argv = ['--set-sync', '--remote', remote]
      if (branch) argv.push('--branch', branch)
      argv.push(autoCheck ? '--enable' : '--disable')
      argv.push('--auto-merge', autoMerge ? 'on' : 'off')
      if (expect) argv.push('--expect-sha256', expect)
      argv.push('--json')
      const r = await runSyncScript(sessionId, PR_STATUS_SCRIPT, argv.join(' '), 20000)
      if (!r.ok) return { ok: false, code: r.code, message: r.message, cwd: r.cwd || null, detail: r.detail || '' }
      const doc = syncDocOf(r) || {}
      const env = syncEnvelopeError(doc)
      if (env) return { ok: false, code: env.code, message: env.message, cwd: r.cwd || null, detail: '' }
      return {
        ok: true,
        cwd: r.cwd || null,
        config_path: syncStr(doc.settings) || '.local/settings.json',
        settings_sha256: syncStr(doc.sha256),
        saved: { remote: remote, branch: branch, auto_check: autoCheck, auto_merge: autoMerge },
      }
    })

    return () => {
      if (handleDisposer) handleDisposer()
      if (healthDisposer) healthDisposer()
      if (detailDisposer) detailDisposer()
      if (kbShowDisposer) kbShowDisposer()
      if (kbMergeDisposer) kbMergeDisposer()
      if (kbSaveDisposer) kbSaveDisposer()
    }
  },
}
