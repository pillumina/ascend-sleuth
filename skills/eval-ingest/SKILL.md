---
name: eval-ingest
description: >
  评测集补充：从 GitHub 或本地 issue 导出建诊断候选样本，跑 dry-run、确认导入、补 expected、复核入池。
  用户说“补评测集/补 field 样本/从 issue 加评估样本”，或 self-evolve 的 run 显示 field 评估不足时使用。
  只产 candidate，不自动 active、不改 case 知识、不自动合并；与 issue-ingest（case 沉淀）是两条出口。
---

# Eval Ingest（评测集补充）

这是评测集的补充入口，不是 case 沉淀入口。`issue-ingest` 产出 case 草稿；本 skill 产出候选样本。两者可以消费同一条 issue，但 processed 分命名空间，互不吞并。

## 触发

- 用户说“补评测集”“从 issue 补些评估样本”“field 样本不够”；
- `python3 scripts/evolve.py run` 的 `next_actions` 出现 `field_eval_short`；
- 已有样本被吸收、test 失效或目标族缺口，需要补 field/core。

不触发：用户要沉淀 case → `/skill:issue-ingest`；用户要跑一轮改进 → `/skill:self-evolve`。

## 交互顺序

```mermaid
flowchart TD
  A[问 repo / labels / limit / min-comments / dry-run] --> B[ingest-issues --dry-run]
  B --> C{候选列表}
  C -->|改参数| A
  C -->|确认| D[ingest-issues 正式执行]
  D --> E[set-answer 补 expected]
  E --> F[check → review]
  F -->|通过| G[active/field → draw-test]
  F -->|拒绝| H[rejected，不进评测池]
  G --> I[promote core（需要时）]
```

只问四类事：哪个 repo、哪些 label、取多少条、先 dry-run 还是直接导。其余由脚本做：元数据拉取、PR/已处理/label/评论/标题过滤、按需取 body、查重、state 幂等。

## 步骤

1. **确认参数**：repo、labels、min-comments、limit、是否 dry-run；默认先 dry-run。
2. **dry-run**：

   ```bash
   python3 scripts/evolve.py sample ingest-issues \
     --repo <repo> --labels <labels> --limit <n> --dry-run
   ```

   给用户看候选编号/标题/跳过原因；参数不对回到第 1 步。

3. **正式导入**：去掉 `--dry-run`。默认 state 写当前检出的 `ingest-state.json` 的 `<source_id>/evaluation` 命名空间；样本库仍锚主检出。
4. **补答案**：逐条

   ```bash
   python3 scripts/evolve.py sample set-answer --id <id> --expected '<json>'
   ```

   答案来自维护者核过的 issue resolution/fix；不把评论里未确认的猜测当答案。

5. **复核**：`sample check --id <id>`，再 `sample review --id <id> --approve|--reject`。ingest 不自动 active。
6. **入池**：通过后是 active/field evaluation；需要 test 时 `sample draw-test`；需要 core 时 `sample promote --id <id> --to core`。
7. **停点**：达到 field/test 目标就停；候选拒绝、body 空、重复来源如实计数，不补假样本。

## 分支与失败

| 情形 | 行为 |
|---|---|
| gh 未安装/未登录 | 停下，给安装/`gh auth login` 修法；不写半份样本 |
| source 不可达/本地 cache 坏 | 退出 2；dry-run 也失败，不更新 state |
| PR 混入、已处理、label 不匹配、评论少、标题排除 | 跳过并计数；不创建样本 |
| body 空/太短/标题像 feature | 跳过；不进入候选 |
| 重复 source/id | 跳过；第二次运行幂等 |
| 候选没有答案 | 留 candidate；`review` 会拒绝，先 `set-answer` |
| review 拒绝 | 留 rejected；不进入评测池 |
| test 退休/失效 | 先 `absorb`，再 `draw-test` 按剩余槽位补齐 |
| 维护者拿不准答案 | 不猜；留 candidate 或拒绝，记原因 |

## 边界

- 只建 candidate；不自动 active、不自动 promote core、不自动合并。
- 不改 `knowledge/`、`references/`、case 草稿；case 沉淀走 `/skill:issue-ingest`。
- 评论、关联 PR、resolution 不进入样本 `input`，防止泄题。
- 所有人都能调用本 skill；写权限仍由 policy、CODEOWNERS、分支保护和人工 review 约束。
- 完整来源协议、过滤规则和 state 语义见 [evaluation.md](../../docs/mechanism/evaluation.md)。
