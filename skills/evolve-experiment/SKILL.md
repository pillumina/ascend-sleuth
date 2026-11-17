---
name: evolve-experiment
description: >
  用当前 agent 的 subagent/任务编排能力跑一次 baseline 与候选 skill 的对照实验，不依赖 Claude/Codex CLI 或 GEPA 库。
  用户要验证一个 skill 改动、做自演进实验、或需要 judge/rollout 但不想接外部模型时使用。
  产出 baseline/candidate 分数、失败反馈和 gate 判定，并记录到本地实验记录；不自动改文件、不合入。
---

# Evolve Experiment（子 agent 编排实验）

这是 agent-agnostic 的实验协议：有 subagent 工具的 harness 都能跑；没有就停，不退化成外部 CLI。

## 触发

- 用户要验证一个 skill 改动是否比 baseline 好；
- `self-evolve` 产出一个候选 skill，需要同批对照；
- 需要 LLM judge 但没有外部 API/CLI，当前 agent 可以派 subagent。

不触发：单纯补样本走 `eval-ingest`；纯知识入库走 `issue-ingest`/`to-reference`。

## 硬规则

1. 先冻结样本与版本：同一条样本只出现在一个实验里；holdout/test 不参与候选生成。
2. task subagent 只看输入，**不把 expected、judge 反馈或 case 正文给它**，防止泄题。
3. judge subagent 只看 expected/rubric 与候选输出；同一 judge prompt 对 baseline/candidate 复用。
4. reflection 只产 skill 文本，不改仓库、不改样本、不写 expected。
5. 一次只改一个 skill/组件；baseline 和 candidate 用同一批样本、同一 judge。
6. gate 不通过就记 `reject`/`insufficient`，不自动合入。

## 拓扑

```text
samples
  ├─ baseline task agents → judge agents → baseline scores
  ├─ reflection agent（看失败反馈）→ candidate skill
  └─ candidate task agents → judge agents → candidate scores
        → paired gate → experiment record
```

每个 subagent 用结构化输出：

- task：`{"diagnosis": "..."}`；
- judge：`{"score": 0 或 1, "feedback": "一句话"}`；
- reflection：`{"skill": "改进后的 skill 文本"}`。

## 步骤

1. **选样本**：从当前评测集取小型 smoke（如 2–5 条）或正式批（9/30 条）；记录 sample id。没有样本就停，不造数据。
2. **baseline**：为每条样本派一个 task subagent，system 段放当前 skill，user 段只放输入；收集 diagnosis。
3. **judge baseline**：为每条样本派 judge subagent，给 expected/rubric 与 diagnosis；收集 score/feedback。
4. **reflection**：把失败项（sample id、expected、diagnosis、feedback）交给 reflection subagent，产候选 skill；没有失败就不改，直接记 `insufficient`（无提升空间）。
5. **candidate**：用同一批样本、候选 skill，重复 task + judge。
6. **gate**：
   - candidate 平均分高于 baseline，且没有样本从 1 掉到 0：`accept`；
   - 有回归：`reject`；
   - 分数持平但样本不足：`insufficient`；
   - 数据/版本不完整：`unknown`。
7. **记录**：

   ```bash
   python3 scripts/evolve.py experiment record --file result.json
   ```

   `result.json` 至少含 `target_kind`、`target_component`、`algorithm`、`algorithm_version`、`execution`、`decision`、`samples`、`baseline`、`candidate`；本 skill 的 execution 写 `subagent`，并显式写 `eval_profile_id: subagent_judge`、`eval_ready: false`；baseline/candidate 的 `samples` 必须同集合。
8. **停点**：记录后停；合入另走 review/PR，不由本 skill 自动做。

## 失败与边界

| 情形 | 行为 |
|---|---|
| 没有 subagent/任务工具 | 停；不要改调外部 CLI 冒充 |
| 样本含客户数据 | 不派给 subagent；先脱敏或不跑 |
| task 输出为空 | 该条记失败，不补 0 分以外的猜测 |
| judge 分歧大 | 加第二 judge 或降为 `insufficient` |
| baseline 全对 | 没有提升空间，记 `insufficient`，不硬造候选 |
| candidate 有回归 | 记 `reject`，保留失败反馈 |
| 模型/上下文不稳定 | 缩样本或停；不刷分 |

## 与其他入口的关系

- `self-evolve` 负责发现改什么；本 skill 负责验证一个候选 skill；
- 本 skill 是一次 reflection 对照；要候选池/Pareto/预算循环用 `evolve-gepa`；
- 官方 `gepa` 库走 `GepaOptimizer`，需要同步 task_lm；不要把 subagent 实验记成官方库结果；
- `eval-ingest` 负责补样本；
- `gepa` 适配器是可选 proposer；没有 GEPA 库时，本 skill 的 reflection 仍是合法实验，但算法名写 `subagent-reflection`，不要写成 `gepa`。
