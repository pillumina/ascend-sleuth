---
name: preload-panel
description: >
  在 DSH 会话中热加载 ascend-sleuth 面板插件：读取 dsh-plugins/<panel>/ 下的
  panel-host.js 与 panel-client.js，用 cordis_define 创建动态 Cordis 插件并
  cordis_run 激活，对话视图出现对应 tab。面板选择：
  - ascend-panel →「诊断」「指标」两个 tab（诊断会话/轨迹/证据 + 知识库健康）
  - ev-panel →「自演进」tab（EV 卡状态机 / 容量热力 / 台账与 S2 归因 / timeline）
  仅 DSH 可用——依赖 DSH 的 cordis_define / cordis_run 工具
  与 conversation.view 插槽；其他 agent（Claude Code / Codex / pi）无此机制。
---

# Preload Panel

DSH 会话中加载可视化面板（诊断 / 指标 / 自演进）。每个面板是独立动态插件，各占
conversation.view 一个 tab（list 插槽，按 order 排列，可共存）。

## 触发

用户需要面板但当前会话没有对应 tab 时，用本 skill 加载。

## 面板清单

| 面板 | 目录 | tab id / label | 视图 |
|---|---|---|---|
| 诊断面板 | `dsh-plugins/ascend-panel/` | `ascend-diagnose`(20) / `ascend-metrics`(21) | 会话列表/轨迹/证据 + 知识库健康/指标 |
| 自演进看板 | `dsh-plugins/ev-panel/` | `ascend-evolve`(22) | EV 卡状态机 / 容量热力 / 台账归因 / timeline |

## 流程

1. **确定要加载的面板**：用户要诊断可视化 → ascend-panel；要自演进状态（EV 卡/
   容量/台账）→ ev-panel；两者可同时加载（不同 tab id，互不冲突）。

2. **读插件代码**：读 `<面板目录>/panel-host.js`（Host 半）与 `<面板目录>/panel-client.js`
   （Client 半）。文件是 `cordis_define` 需要的函数体形态（`return { apply(ctx) {...} }`），
   **原样粘贴，不要改形态**——动态插件代码不经过打包器，`export default` / `import`
   等 ESM 语法无法加载。

3. **创建插件**：`cordis_define`（kind: new，idPrefix：ascend-panel 用 `sleu`、
   ev-panel 用 `evbd`）：
   - `code.host` ← panel-host.js 全文
   - `code.client` ← panel-client.js 全文

4. **激活**：`cordis_run`（mode: run）。若返回 awaiting-approval，告知用户需在 UI 允许
   （Client 半需授权）；授权后插件激活，对话视图出现对应 tab。

5. **验证**：确认插件 running 且无 waitingFor（`cordis_inspect_self`）；tab 出现在
   对话视图（conversation.view 插槽，按上表 id 核对）。自演进看板首次打开会调
   `scripts/ev_board_data.py` 汇总数据——确认数据区渲染（EV 卡/容量有真实数据，
   台账/归因可能显示"数据积累中"，如实）。

## 交互原则

面板是**只读可视化 + 指令生成器**——展示状态、生成续接/沉淀指令供用户触发，
面板自身不做决策与写入（唯一例外：诊断面板的沉淀状态标记由用户在面板确认后
更新）。自演进看板纯只读：展示 EV 卡状态与演进信号，产卡/验证走 agent + 攒批。

## 依赖

- DSH 会话（`cordis_define` / `cordis_run` / `cordis_inspect_self` 工具）
- 工作区为 ascend-sleuth 仓库（Host 从 session.header.cwd 解析数据目录）
- Host 服务：`fs` / `sessions` / `shell`
- 自演进看板额外依赖：python3 + PyYAML（`scripts/ev_board_data.py` 聚合数据）

## 说明

- 动态插件定义只存在于当前 DSH 进程，重启后需重新加载（本 skill 即为此设计）。
- 仓库内 `dsh-plugins/<面板>/` 是代码的权威版本（含 README 使用说明）；本 skill 是
  加载入口，两者分离——改代码走仓库，加载走这里。
