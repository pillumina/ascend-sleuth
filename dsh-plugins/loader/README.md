# loader —— 一次性加载器（`panel_from_file` 工具）

`panel-from-file.js` 是一个 **host-only 动态插件**（~1.5KB），加载后注册 `panel_from_file`
工具：按工作区路径读 Host/Client 两半源码 → `dynamicCordisRunner.define()` → `run()`。

**为什么需要它**：面板两个文件合计 ~70KB。旧流程要求 agent 把全文重新输出进
`cordis_define` 的 `code.host` / `code.client`（约 2 万 output token、3–6 分钟）；
用这个工具只需发**两个路径**（几十 token，秒级）。

**为什么不用 DSH 补丁**：只用两个 DSH 公开机制——

- `harness.registerTool(ctx, harness.defineTool({...}))`：动态包注册 model-facing 工具；
- `ctx.get('dynamicCordisRunner')`：拿注册表服务，`define()` 后 `run(exec.agent, …)`。

因此**任何带 Cordis 工具的 DSH 版本都能用**，其他机器只需 `git pull` 本仓库。
真实面板源码仍进**不可变 Package**（`cordis_inspect_self` 可审计），审批流与
`cordis_run` 完全一致。

## 用法（每个 DSH 会话一次）

```
1) 加载 loader（host-only，免审批，几秒）
   cordis_define(kind: new, idPrefix: 'ldr', code.host ← panel-from-file.js 全文)
   cordis_run(mode: run)
   —— DSH 支持 codeFile 时也可 codeFile.host 指本文件路径，更省 token

2) 加载面板
   panel_from_file(host:   dsh-plugins/<面板>/panel-host.js,
                   client: dsh-plugins/<面板>/panel-client.js,
                   idPrefix: 'sleu' | 'evbd', name, purpose)
   —— 有 client 半 → 返回 awaiting-approval，需在 UI 允许；授权后 tab 出现
```

会话里已有 `panel_from_file`（工具目录能查到）时**不要重复加载 loader**——重复注册同名
工具会失败。

## 参数

| 参数 | 说明 |
|---|---|
| `host` | 必填，Host 半路径（相对会话工作区或绝对） |
| `client` | Client 半路径；省略 = host-only 包，免审批 |
| `name` / `purpose` | Package 标签与一句话用途（给人看） |
| `idPrefix` | 新建 Plugin 的语义前缀（3–6 个小写字母，只能字母） |
| `pluginId` | 追加到已有 Plugin 时用（与 `idPrefix` 二选一） |
| `mode` | `run`（默认）/ `update` |

**快照语义**：读入的是**定义时**的文件内容。改了 `panel-*.js` 后要传 `pluginId` +
`mode: 'update'` 追加新 Package 再切换——改文件不会自动生效。

## 失败时

- 工具没注册上（`fs` 或 `dynamicCordisRunner` 缺失）→ 看 `cordis_inspect_self ldr-*` 诊断；
- `idPrefix` 报 `must contain 3–6 lowercase English letters` → 前缀只能小写字母，别带数字；
- 路径报"文件不存在/不是普通文件" → 确认会话工作区是 ascend-sleuth 仓库根。
