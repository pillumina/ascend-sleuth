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

**快照语义 + 幂等重载**：读入的是**定义时**的文件内容——改文件不会自动生效。
但**重复调用同一条命令即可重载**：工具会先查本 session 的插件清单，找到同 `idPrefix`
的插件就复用它（追加新 Package + 自动切到 update 模式），返回 `reused: true`，
**不会堆出重复插件**。所以改完 `panel-*.js` 直接再调一次即可，不必记 `pluginId` 与 `mode`。

- 跨 session（DSH 重启后）找不到旧插件，会新建一个同 tab id 的插件：新 tab 覆盖旧 tab 的
  显示，旧插件的 RPC 仍在但不再被 tab 使用（DSH 的 `define(kind: 'update')` 只允许
  追加到当前 session 拥有的插件，跨 session 认领不了）。
- 想显式指定时仍可传 `pluginId` + `mode: 'update'`。

## 跨 session 与进程全局（实测）

两件事都实测过（用探针插件 + 开新会话观察），结论对使用者很关键：

1. **工具注册是进程全局的**。动态插件用自身 `ctx` 注册的工具，其他 session 的 agent 也看得到
   （实测：探针工具出现在另一个 session 的工具目录里）。所以本 loader 是"一个进程一份"：
   - 新 session **不必**再加载 loader，直接就有 `panel_from_file` 可用；
   - 第二个 session 再加载 loader 会撞名，但**不会报错**——loader 捕获后只打一条提示，
     工具照常可用。要刷新 loader 自身代码，只能重启 DSH。
2. **面板插件是 per-session 的**，且 `define(kind:'existing')` 只允许追加到**当前 session 拥有**
   的插件。所以新 session 加载面板时**认领不了旧 session 的插件**，会新建一个同 tab id 的
   插件：新 tab 覆盖旧 tab 的显示（slot 的 id 是"占用该格"语义），**旧插件仍在跑**
   （RPC handler 还在、仍读它自己 session 的工作目录）。想彻底清掉，重启 DSH，
   或在各 session 里对自己的插件 `cordis_stop`。

一句话：**同 session 重复调用 = 真重载；跨 session 调用 = 新建并覆盖显示。**

## 成对 RPC 一致性守卫

面板的 host/client 通过 `harness.handle` / `host.call` 成对通信。若两半取自**不同版本**
（最典型：相对路径按会话工作区解析，而改过代码的副本在别的 worktree），会出现"client 调了
host 没有的 RPC"——症状是**加载成功、点开才报错**，从现象看不出根因（2026-09 实际踩过：
展开报 `unrecognized arguments: --detail`）。

加载前会扫出 client 调的 RPC 名与 host 声明的 handler 名，任一方引用不到另一方就**拒绝加载**
并指出缺哪个，而不是让人加载完再点到报错。这是通用检查，不针对某个面板。

## 幂等规则的校验

`scripts/check_loader_idempotency.js` 用**规则副本**给"重复调用=重载"的匹配逻辑做单元测试
（动态插件的代码是函数体、不能 import），并断言 loader 源文件里仍有对应标记，防测试与实现漂移：

```
node scripts/check_loader_idempotency.js
```

覆盖：同 session 同前缀命中 / 跨 session 不认领（否则 `define(kind:'existing')` 抛归属错误）/
精确 id 优先 / 旧写法 `evbd-99` 也能命中 / mode 自动推导 / 返回 `reused` 标记。

## 失败时

- 工具没注册上（`fs` 或 `dynamicCordisRunner` 缺失）→ 看 `cordis_inspect_self ldr-*` 诊断；
- `idPrefix` 报 `must contain 3–6 lowercase English letters` → 前缀只能小写字母，别带数字；
- 路径报"文件不存在/不是普通文件" → 确认会话工作区是 ascend-sleuth 仓库根。
