# ev-panel —— 自演进看板（DSH 插件）

对话视图第三个 tab「自演进」：把 evolve-check / self-evolve 产出的演进状态可视化，
让"看到系统在自演进"成为可能（run.md §6 领域视图落地：卡流转为主，容量/归因/指标为辅）。

## 视图区块

- **Idea 卡状态机**：EV 卡按状态分组（candidate → proposed → in_experiment → pending_merge → adopted → validated/rolled_back/superseded/rejected），每卡展示 id/layer/authorization/risk/信号/预期/decisions 尾条——追溯链入口（卡 → 证据 → PR）
- **知识库容量**：namespace × category 格子填充度（_index 头注），超 soft_cap 红标
- **流程演进信号**：归因事件按需聚合（trace attribution + S2 replay 路由 miss 候选）——**无数据显示"数据积累中"，不画假图**（诚实退化）
- **指标趋势**：timeline live 期趋势（routed_accuracy）

## 数据流

```
scripts/ev_board_data.py  ← 确定性聚合（EV 卡/容量/归因/timeline → JSON，原则二）
   ↑ shell 调用
panel-host.js  harness.handle('ev-board-load')  ← host RPC
   ↑ host.call
panel-client.js  conversation.view 注册 'ascend-evolve'（order 22）
```

## 加载

同 ascend-panel：agent 读本目录两个文件 → `cordis_define`（kind: new）→ `cordis_run`。
或 `/skill:preload-panel` 的 ev-panel 变体（见 skills/preload-panel）。

前置：DSH 会话工作区为 ascend-sleuth 仓库；python3 + PyYAML 可用（数据脚本依赖）。
