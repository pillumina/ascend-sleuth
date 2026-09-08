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
// 用法（一个 DSH 会话一次）：
//   cordis_define(kind: new, idPrefix: 'ldr', code.host ← 本文件全文)  →  cordis_run（host-only，免审批）
//   panel_from_file(host: 'dsh-plugins/ev-panel/panel-host.js',
//                   client: 'dsh-plugins/ev-panel/panel-client.js',
//                   idPrefix: 'evbd', name: '…', purpose: '…')
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

    harness.registerTool(ctx, harness.defineTool({
      name: 'panel_from_file',
      description:
        'Define and activate a dynamic Cordis Package whose Host (and optional Client) half is read from a workspace file. '
        + 'Use it for panel-style plugins whose source already lives in the repository: pass paths, never re-emit the source. '
        + 'Reading a client half requires user approval at activation, exactly like cordis_run. '
        + 'Omit client to load a host-only package, which activates without approval. '
        + 'Editing a source file needs a NEW Package (call again with pluginId + mode "update").',
      parameters: {
        host: { type: 'string', required: true, description: 'Host-half source path, resolved against the session workspace.' },
        client: { type: 'string', description: 'Client-half source path. Omit for a host-only package (no approval).' },
        name: { type: 'string', required: true, description: 'Package label.' },
        purpose: { type: 'string', required: true, description: 'One-sentence, user-facing purpose.' },
        idPrefix: { type: 'string', description: 'Semantic prefix (3–6 lowercase letters) for a NEW Plugin; give this or pluginId.' },
        pluginId: { type: 'string', description: 'Existing Plugin ID to append a Package to; give this or idPrefix.' },
        mode: { type: 'string', enum: ['run', 'update'], description: 'run (default) for the first activation, update to switch versions.' },
      },
      output: {
        schema: { type: 'json' },
        render(args, value) {
          const v = value || {}
          const status = String(v.status)
          const run = v.pluginRunId === undefined ? '' : ' (' + String(v.pluginRunId) + ')'
          return [{
            type: 'text',
            text: status === 'awaiting-approval'
              ? String(v.pluginId) + '/' + String(v.packageId) + ' is awaiting user approval' + run + '.'
              : status === 'starting'
                ? String(v.pluginId) + '/' + String(v.packageId) + ' is starting asynchronously' + run + '.'
                : String(v.pluginId) + '/' + String(v.packageId) + ' is running' + run + '.',
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
        const receipt = runner.define({
          sessionId: agent.id,
          plugin: args.pluginId === undefined
            ? { kind: 'new', idPrefix: String(args.idPrefix) }
            : { kind: 'existing', pluginId: String(args.pluginId) },
          name: String(args.name),
          purpose: String(args.purpose),
          code: clientCode === undefined ? { host: hostCode } : { host: hostCode, client: clientCode },
        })
        const outcome = await runner.run(
          agent,
          receipt.pluginId,
          receipt.packageId,
          args.mode === 'update' ? 'update' : 'run',
          exec.signal,
        )
        if (outcome === undefined || outcome.ok !== true) {
          throw new Error('激活失败: ' + String(outcome === undefined ? '无返回' : outcome.message))
        }
        return {
          pluginId: String(receipt.pluginId),
          packageId: String(receipt.packageId),
          pluginRunId: String(outcome.pluginRunId),
          status: String(outcome.status),
          mode: String(outcome.mode),
        }
      },
    }))
  },
}
