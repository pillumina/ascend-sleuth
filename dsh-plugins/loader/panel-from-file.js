// panel-from-file.js —— 一次性加载器（Host 半，host-only）
//
// 作用：注册 `panel_from_file` 工具——按工作区路径读 Host/Client 两半源码，
// 走 dynamicCordisRunner.define() + run() 定义并激活。于是加载面板只需发**两个路径**，
// 不必把 ~70KB 源码转写进 cordis_define（那要几千 output token、几分钟）。
//
// 与 cordis_define 的 codeFile 参数的区别：本文件不依赖任何 DSH 补丁，
// 只用两个公开机制（harness.registerTool / ctx.get('dynamicCordisRunner')），
// 因此在任何带 Cordis 工具的 DSH 版本上都能用；真实面板源码仍进不可变 Package
// （可被 cordis_inspect_self 审计），审批流不变。
//
// **幂等（2026-09）**：改完面板代码再调一次是常事，所以重复调用不再新建插件——
// 先查 inventory 找本 session 已存在的同前缀插件，找到就复用（追加新 Package +
// mode update），返回 reused: true。不传 pluginId 也不会再堆出重复插件。
// 归属约束：DSH 的 define(kind: 'existing') 要求插件属于当前 session，因此只在
// 本 session 内查找；跨 session（如 DSH 重启后）会新建一个同 tab id 的插件，
// 新 tab 覆盖旧 tab 的显示（旧插件的 RPC 仍在，只是不再被 tab 使用）。
//
// 用法（一个 DSH 会话一次）：
//   cordis_define(kind: new, idPrefix: 'ldr', code.host ← 本文件全文)  →  cordis_run（host-only，免审批）
//   panel_from_file(host: 'dsh-plugins/ev-panel/panel-host.js',
//                   client: 'dsh-plugins/ev-panel/panel-client.js',
//                   idPrefix: 'evbd', name: '…', purpose: '…')
// 改代码后再调**同一条**命令即可重载；也可传 pluginId + mode: 'update' 显式指定。
// 若会话里已有 panel_from_file（cordis_inspect_query 的 Tool 目录可查），直接调用，不要重复加载。
return {
  name: 'panel-from-file',
  apply(ctx) {
    const fs = ctx.get('fs')
    const runner = ctx.get('dynamicCordisRunner')
    if (fs === undefined || runner === undefined) {
      console.error('[panel-from-file] 需要 fs 与 dynamicCordisRunner 服务；当前至少缺一个，工具未注册')
      return
    }

    async function readHalf(path, cwd) {
      const target = await fs.resolve(String(path), cwd === undefined ? {} : { cwd })
      const info = await fs.stat(target)
      if (info === undefined) throw new Error('文件不存在: ' + target.displayPath)
      if (info.type !== 'file') throw new Error('不是普通文件: ' + target.displayPath)
      return await fs.readText(target)
    }

    // 成对 RPC 一致性守卫：面板的 host/client 通过 harness.handle / host.call 成对通信。
    // 若两半取自不同版本（最典型：路径按会话工作区解析，改过代码的副本在别的 worktree），
    // 会出现"client 调了 host 没有的 RPC"——症状是加载成功、点开才报错，很难从现象看根因。
    // 通用实现：扫出 client 调的 RPC 名与 host 声明的 handler 名，任一方引用不到另一方就拒绝。
    function rpcNames(code, pattern) {
      const out = []
      let m
      const re = new RegExp(pattern, 'g')
      while ((m = re.exec(code)) !== null) {
        if (out.indexOf(m[1]) < 0) out.push(m[1])
      }
      return out
    }
    function assertRpcPair(hostCode, clientCode) {
      if (clientCode === undefined) return
      const called = rpcNames(clientCode, "host\\.call\\(\\s*'([^']+)'")
      const handled = rpcNames(hostCode, "harness\\.handle\\(\\s*'([^']+)'")
      const missing = called.filter(n => hostCode.indexOf("'" + n + "'") < 0)
      const unused = handled.filter(n => clientCode.indexOf("'" + n + "'") < 0)
      if (missing.length === 0 && unused.length === 0) return
      const parts = []
      if (missing.length) parts.push('client 调用了 host 未声明的 RPC: ' + missing.join(', '))
      if (unused.length) parts.push('host 声明了 client 未使用的 RPC: ' + unused.join(', '))
      throw new Error('host/client 两半不是同一版本——' + parts.join('；')
        + '。请确认 host 与 client 指向同一份代码（相对路径按会话工作区解析，'
        + '改过代码的副本可能在别的 worktree）。')
    }

    // 找本 session 已存在的同前缀插件（重复调用 → 复用而非新建）
    function findExisting(agentId, idPrefix) {
      if (typeof runner.inventory !== 'function' || idPrefix === undefined) return undefined
      const prefix = String(idPrefix)
      let rows = []
      try {
        rows = runner.inventory() || []
      } catch (e) {
        return undefined
      }
      // 归属过滤：DSH 只允许追加到当前 session 拥有的插件
      const mine = rows.filter(r => r && r.agentId === agentId)
      // 优先精确前缀（evbd-12），退化为"以前缀开头"（防前缀带数字后缀的旧写法）
      return mine.find(r => r.pluginId === prefix)
        || mine.find(r => String(r.pluginId).replace(/-\d+$/, '') === prefix)
        || mine.find(r => String(r.pluginId).startsWith(prefix + '-'))
    }

    // 工具注册是**进程全局**的（实测：动态插件用自身 ctx 注册的工具，其他 session 的
    // agent 也看得到），所以本 loader 是"一个进程一份"：
    //   - 好处：新 session 不必自己加载 loader，直接就有 panel_from_file 可用；
    //   - 代价：第二个 session 再加载 loader 会撞名——这时**不抛错**，因为工具已经可用，
    //     抛错只会让人以为"loader 坏了"。真正需要刷新 loader 自身代码时，重启 DSH。
    let registered = false
    try {
      harness.registerTool(ctx, harness.defineTool({
        name: 'panel_from_file',
      description:
        'Define and activate a dynamic Cordis Package whose Host (and optional Client) half is read from a workspace file. '
        + 'Use it for panel-style plugins whose source already lives in the repository: pass paths, never re-emit the source. '
        + 'Reading a client half requires user approval at activation, exactly like cordis_run. '
        + 'Omit client to load a host-only package, which activates without approval. '
        + 'Idempotent by idPrefix: calling again with the same idPrefix (after editing a source file) reuses the '
        + 'existing plugin of this session, appends a new Package, and switches to it (reused: true) — no duplicate '
        + 'plugins pile up. Pass pluginId + mode "update" only when targeting a plugin explicitly.',
      parameters: {
        host: { type: 'string', required: true, description: 'Host-half source path, resolved against the session workspace.' },
        client: { type: 'string', description: 'Client-half source path. Omit for a host-only package (no approval).' },
        name: { type: 'string', required: true, description: 'Package label.' },
        purpose: { type: 'string', required: true, description: 'One-sentence, user-facing purpose.' },
        idPrefix: { type: 'string', description: 'Semantic prefix (3–6 lowercase letters). Reused on repeat calls to reload that plugin; give this or pluginId.' },
        pluginId: { type: 'string', description: 'Existing Plugin ID to append a Package to; give this or idPrefix.' },
        mode: { type: 'string', enum: ['run', 'update'], description: 'run (default) for the first activation, update to switch versions. Auto-derived when idPrefix matches an existing plugin.' },
      },
      output: {
        schema: { type: 'json' },
        render(args, value) {
          const v = value || {}
          const status = String(v.status)
          const run = v.pluginRunId === undefined ? '' : ' (' + String(v.pluginRunId) + ')'
          const tail = v.reused === true ? ' [reloaded existing plugin]' : ''
          return [{
            type: 'text',
            text: status === 'awaiting-approval'
              ? String(v.pluginId) + '/' + String(v.packageId) + ' is awaiting user approval' + run + tail + '.'
              : status === 'starting'
                ? String(v.pluginId) + '/' + String(v.packageId) + ' is starting asynchronously' + run + tail + '.'
                : String(v.pluginId) + '/' + String(v.packageId) + ' is running' + run + tail + '.',
          }]
        },
      },
      async execute(args, exec) {
        const agent = exec && exec.agent
        if (agent === undefined || agent.session === undefined || agent.session.header === undefined) {
          throw new Error('panel_from_file 需要 agent 会话上下文（拿不到工作区）')
        }
        if (args.pluginId === undefined && args.idPrefix === undefined) {
          throw new Error('需要 idPrefix（新建 Plugin）或 pluginId（追加 Package）之一')
        }
        const cwd = agent.session.header.cwd
        const hostCode = await readHalf(args.host, cwd)
        const clientCode = args.client === undefined || args.client === '' ? undefined : await readHalf(args.client, cwd)
        // 两半必须同版本：不一致就拒绝，别让人加载完再点到报错
        assertRpcPair(hostCode, clientCode)

        // 幂等：同前缀重复调用 = 重载（复用已有插件，不新建）
        const existing = args.pluginId === undefined ? findExisting(agent.id, args.idPrefix) : undefined
        const targetPluginId = args.pluginId === undefined
          ? (existing === undefined ? undefined : existing.pluginId)
          : String(args.pluginId)

        const receipt = runner.define({
          sessionId: agent.id,
          plugin: targetPluginId === undefined
            ? { kind: 'new', idPrefix: String(args.idPrefix) }
            : { kind: 'existing', pluginId: targetPluginId },
          name: String(args.name),
          purpose: String(args.purpose),
          code: clientCode === undefined ? { host: hostCode } : { host: hostCode, client: clientCode },
        })

        // mode：显式传入优先；复用已有插件时，有成功版本才用 update，否则 run（首次激活）
        let mode = args.mode === 'update' ? 'update' : 'run'
        if (args.mode === undefined && targetPluginId !== undefined) {
          const row = (() => {
            try { return (runner.inventory() || []).find(r => r && r.pluginId === targetPluginId) } catch (e) { return undefined }
          })()
          mode = row !== undefined && row.currentPackageId !== undefined ? 'update' : 'run'
        }

        const outcome = await runner.run(agent, receipt.pluginId, receipt.packageId, mode, exec.signal)
        if (outcome === undefined || outcome.ok !== true) {
          throw new Error('激活失败: ' + String(outcome === undefined ? '无返回' : outcome.message))
        }
        return {
          pluginId: String(receipt.pluginId),
          packageId: String(receipt.packageId),
          pluginRunId: String(outcome.pluginRunId),
          status: String(outcome.status),
          mode: String(outcome.mode),
          reused: targetPluginId !== undefined,
        }
      },
      }))
      registered = true
    } catch (e) {
      const msg = String(e && e.message || e)
      if (/already registered/.test(msg)) {
        console.error('[panel-from-file] panel_from_file 已由本进程内先前的 loader 注册（工具注册是进程全局的），'
          + '本次跳过注册——工具仍可直接使用；只有需要更新 loader 自身代码时才需重启 DSH。')
      } else {
        console.error('[panel-from-file] 注册失败: ' + msg)
      }
    }
    if (!registered) return
  },
}
