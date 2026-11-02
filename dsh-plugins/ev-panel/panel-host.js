// ev-panel host —— 自演进看板数据服务（EV 卡 / 容量 / 归因聚合 / timeline）
// 用法：cordis_define kind:new → code.host 用本文件全文；code.client 用 panel-client.js 全文。
// host 侧通过 shell 跑 scripts/ev_board_data.py 汇总 JSON（确定性逻辑在脚本，遵循原则二）。
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

    return () => {
      if (handleDisposer) handleDisposer()
      if (healthDisposer) healthDisposer()
      if (detailDisposer) detailDisposer()
    }
  },
}
