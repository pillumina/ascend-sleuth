// ev-panel host —— 自演进看板数据服务（EV 卡 / 容量 / 归因聚合 / timeline）
// 用法：cordis_define kind:new → code.host 用本文件全文；code.client 用 panel-client.js 全文。
// host 侧通过 shell 跑 scripts/ev_board_data.py 汇总 JSON（确定性逻辑在脚本，遵循原则二）。
return {
  apply(ctx) {
    // **刻意没有 fs 守卫**：本插件的 host 从不读写文件——数据全由 `shell` 跑 Python 脚本产出
    // （`ev_board_data.py` / `evolution_health.py`）。原先照抄 ascend-panel 写的是
    // `const fs = ctx.get('fs'); if (fs === undefined) return`，后果是 fs 服务缺席时
    // **整个插件什么都不注册**（两个 RPC 全没、tab 点开即死），而它一个 fs 调用都没有——
    // "挂载了却什么都没贡献"是最难查的失败形态。
    // 现在的退化是**逐调用**的：`shell` 缺 → runScript 返回「shell 不可用」；工作区缺 →
    // 「无法解析工作区」。两者都有断言（panel_render_check 的 `[ev-panel host 失败路径]` 一节）。
    const sessions = ctx.get('sessions')
    const shell = ctx.get('shell')

    function resolveCwd(sessionId) {
      if (sessions && sessionId) {
        const s = sessions.get(sessionId)
        if (s && s.header && s.header.cwd) return s.header.cwd
      }
      return undefined
    }

    // Python 解释器解析（Windows 兼容）：面板用 shell 跑 Python 脚本，但 Windows 上
    // `python3` 常不存在——python.org 安装器装的是 `python.exe` + `py.exe` 启动器；
    // 若 PATH 里还有 Store 的「应用执行别名」占位程序，执行 `python3` 不报"找不到命令"
    // 而是弹 Microsoft Store。因此按候选逐个探测，取第一个能打印 Python 3.x 的
    // （退出码 0 + 版本号双重判据，占位程序两者都过不了）；结果缓存，一次加载只探一轮。
    // 注意：dynamic Cordis 插件不能 import，此函数与 ascend-panel 的同名函数是刻意重复的副本。
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

    async function runScript(sessionId, scriptName, extraArgs) {
      const cwd = resolveCwd(sessionId)
      if (!cwd) return { ok: false, error: '无法解析工作区' }
      if (!shell) return { ok: false, error: 'shell 不可用' }
      const py = await resolvePython()
      if (!py) {
        return { ok: false, error: '未找到可用的 Python 3 解释器（已试 python3 / python / py -3）——'
          + '自演进看板的数据脚本 ' + scriptName + ' 需要它，装好 Python 3 并确保在 PATH 里' }
      }
      try {
        const spec = shell.resolve({
          command: py + ' ' + scriptName + (extraArgs ? ' ' + extraArgs : ''),
          workdir: cwd,
          stdoutMaxBytes: 4 * 1024 * 1024, // EV 卡聚合 JSON 随库增长（实测 89KB），防截断
          // 面板按 UTF-8 读 stdout；钉住子进程编码，防脚本侧漏掉 UTF-8 输出（Windows GBK 管道）
          env: { PYTHONIOENCODING: 'utf-8' },
        })
        const r = await shell.run(spec)
        const stdout = r && r.stdout && typeof r.stdout.text === 'string' ? r.stdout.text : ''
        if (!stdout.trim()) {
          const stderrStr = r && r.stderr && typeof r.stderr.text === 'string' ? r.stderr.text : ''
          if (/no module named ['\"]?yaml/i.test(stderrStr)) {
            return { ok: false, error: '运行自演进看板需要 PyYAML——请安装：pip install pyyaml（或 brew install pyyaml）后重开面板' }
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

    // 单卡全文：面板点开某张卡时才拉（列表页只带摘要，不把 36 张卡的完整决策链
    // 一次性塞进客户端）。id 只放行 EV-YYYY-NNN 形状，防 shell 注入。
    function loadIdeaDetail(sessionId, ideaId) {
      const id = String(ideaId || '')
      if (!/^EV-\d{4}-\d{3,}$/.test(id)) return Promise.resolve({ ok: false, error: '非法卡 id: ' + id })
      return runScript(sessionId, BOARD_SCRIPT, '--detail ' + id)
    }

    const handleDisposer = harness.handle('ev-board-load', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      return loadBoard(sessionId)
    })

    const healthDisposer = harness.handle('ev-health-load', async (args) => {
      const sessionId = args && args.sessionId ? String(args.sessionId) : null
      return loadHealth(sessionId)
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
