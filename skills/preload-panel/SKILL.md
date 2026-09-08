---
name: preload-panel
description: >
  在 DSH 会话中热加载 ascend-sleuth 面板插件：用 cordis_define 的 codeFile 直接指向
  dsh-plugins/<panel>/ 下的 panel-host.js 与 panel-client.js（Host 读盘快照，不要转写
  全文），再 cordis_run 激活，对话视图出现对应 tab。面板选择：
  - ascend-panel →「诊断」「指标」两个 tab（诊断会话/轨迹/证据 + 知识库健康）
  - ev-panel →「自演进」tab（EV 卡状态机 / 容量热力 / 归因与 S2 反馈 / timeline）
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
| 自演进看板 | `dsh-plugins/ev-panel/` | `ascend-evolve`(22) | EV 卡状态机 / 容量热力 / 归因与 S2 反馈 / timeline |

## 依赖预检（激活前跑，避免面板加载后白屏/报错）

面板 host 已做优雅退化（自演进 JSON 不截断、无 traces/ 显示空态、缺 pyyaml 给提示），
但 loader 在激活前跑一次预检，能把"依赖缺失"改成**主动告知**而不是面板里一条报错：

- **通用**：确认会话工作区是 ascend-sleuth 仓库（Host 从 `session.header.cwd` 解析数据目录）。
- **ev-panel（自演进）**：确认 `python3` + PyYAML 可用——
  ```bash
  python3 -c "import yaml; print('pyyaml ok')" # 失败 → pip install pyyaml（或 brew install pyyaml）
  ```
  若失败，先告知用户"自演进看板需要 PyYAML，请 `pip install pyyaml`"，再决定是否仍加载
  （host 也会给同样提示，但 loader 提前讲更友好）。
- **ascend-panel（诊断）**：`traces/` 可能不存在（gitignored、按需生成）——host 已把
  "目录不存在"当空态处理，无需预建；但如果用户预期有历史诊断却显示为空，提示
  "运行 /skill:diagnose 后生成 traces/"。指标 tab 的「实时计算」用 `shell` 跑
  `scripts/trace_metrics.py`，同样需要 pyyaml。

## 流程

1. **确定要加载的面板**：用户要诊断可视化 → ascend-panel；要自演进状态（EV 卡/
   容量/归因）→ ev-panel；两者可同时加载（不同 tab id，互不冲突）。

2. **创建插件**：`cordis_define`（kind: new，idPrefix：ascend-panel 用 `sleu`、
   ev-panel 用 `evbd`），**优先用文件路径**（`cordis_define` 支持 `codeFile` 时）：

   ```
   codeFile.host   ← dsh-plugins/<面板>/panel-host.js
   codeFile.client ← dsh-plugins/<面板>/panel-client.js
   ```

   Host 读盘后把源码快照进 Package——**不要自己把文件内容重新输出一遍**（面板两个文件
   合计 ~70KB，转写要几千 token、几分钟；给路径只要几十 token）。文件是函数体形态
   （`return { apply(ctx) {...} }`），原样读入即可，别改形态——动态插件代码不经过打包器，
   `export default` / `import` 等 ESM 语法无法加载。

   若该 DSH 版本的工具**没有** `codeFile` 参数（返回 unknown property / 校验失败），
   回退到内联：读两个文件全文 → `code.host` / `code.client` 原样粘贴。

3. **激活**：`cordis_run`（mode: run）。若返回 awaiting-approval，告知用户需在 UI 允许
   （Client 半需授权）；授权后插件激活，对话视图出现对应 tab。

4. **验证**：确认插件 running 且无 waitingFor（`cordis_inspect_self`）；tab 出现在
   对话视图（conversation.view 插槽，按上表 id 核对）。自演进看板首次打开会调
   `scripts/ev_board_data.py` 汇总数据——确认数据区渲染（EV 卡/容量有真实数据，
   归因/S2 反馈可能显示"数据积累中"，如实）。若见"数据加载失败"，按顶部
   「依赖预检」逐条排查（pyyaml / traces / 工作区）。

## 交互原则

面板是**只读可视化 + 指令生成器**——展示状态、生成续接/沉淀指令供用户触发，
面板自身不做决策与写入（唯一例外：诊断面板的沉淀状态标记由用户在面板确认后
更新）。自演进看板纯只读：展示 EV 卡状态与演进信号，产卡/验证走 agent + 攒批。

## 依赖

- DSH 会话（`cordis_define` / `cordis_run` / `cordis_inspect_self` 工具）
- 工作区为 ascend-sleuth 仓库（Host 从 session.header.cwd 解析数据目录）
- Host 服务：`fs` / `sessions` / `shell`
- **ev-panel（自演进）**：`python3` + **PyYAML**（`scripts/ev_board_data.py` 聚合数据）——
  缺 pyyaml 时 host 会提示安装；loader 侧建议激活前预检（见「依赖预检」）。
- **ascend-panel（指标「实时计算」）**：`shell` + `python3`（`scripts/trace_metrics.py`，同样需 pyyaml）。
- 诊断「打开证据」依赖 `open`/`xdg-open`（macOS/Linux 均可用）。

## 说明

- 动态插件定义只存在于当前 DSH 进程，重启后需重新加载（本 skill 即为此设计）。
- 仓库内 `dsh-plugins/<面板>/` 是代码的权威版本（含 README 使用说明）；本 skill 是
  加载入口，两者分离——改代码走仓库，加载走这里。
