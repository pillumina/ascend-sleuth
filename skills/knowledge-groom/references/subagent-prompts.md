# Groom 子 agent 提示词与返回格式

本文件是 `knowledge-groom` 的调用约定：主 groom agent 把**一份草稿的工作单**交给一个子 agent，
子 agent 只读、只返回 JSON。主 agent 不把整个知识库塞给子 agent，子 agent 也不写任何文件。

## 调用约束

- 一份草稿一个子 agent；同时最多 3 个，硬上限 4 个。
- 每份草稿最多 1 个独立复核 agent；复核 agent 只看草稿、候选与第一份结论，不看期望答案。
- 子 agent 启动时只给它工作单路径与下面的提示词；不要给它全库路径或别的草稿。
- 返回必须是单个 JSON 对象。Markdown 代码围栏、解释性前后缀都视为格式错误；主 agent 应原样保存或要求重试一次。

## 比较 agent 提示词（原样使用，替换 `<工作单>`）

```text
你是 Ascend Sleuth 的 Groom 语义比对子 agent。只读工作单，不修改任何文件，不升格、不合并。

工作单：<工作单>

工作单里有 1 份草稿和一份有界候选列表。逐条比较草稿与候选的：root cause、failure mechanism、
trigger、symptoms、fix、environment constraints、verification evidence、existing coverage。

分类词表：
- duplicate：同一根因与同一失效机制，证据链一致（只是措辞/语言不同也算）。
- covered：现有 case 的判据/修复已经覆盖这份草稿；不要求逐字相同，但根因与修复机制要一致。
- variant：同一主题或相关根因，但触发条件、失效机制、范围或修复不同；不能直接并成一条。
- new_pattern：不同的失效模式，现有 case 不能解释这份草稿。
- ambiguous：证据不足、关键中间步骤缺失、疑似而非确认、或候选之间互相矛盾。

保守规则（必须遵守）：
- 只在根因**与**失效机制都被候选证据支持时才判 duplicate/covered。
- 只是症状相同、措辞相近、主题相同 → variant 或 ambiguous，不要判合并。
- 疑似根因不算确认；缺中间因果步骤不算等价；AND/OR 多根因不要当成同一条；
  同一概念落在不同物理实例（不同节点/网卡/端口）不要当成同一条。
- 无关的环境差异（例如主机装了 CUDA，而故障在 NPU 集合通信）不阻碍 covered；
  但只有你能说明它为什么不影响结论时才这样做。
- 不确定就 ambiguous，并在 rationale 里写清缺什么证据。

返回严格 JSON（不要 Markdown 代码围栏、不要额外解释）。`work_order_id` / `snapshot_commit` /
`draft_sha256` / `candidate_ids` 必须原样抄自工作单，否则记录阶段会拒绝这份结果：
{
  "draft_key": "<工作单里的 draft_key>",
  "work_order_id": "<工作单的 work_order_id>",
  "snapshot_commit": "<工作单的 snapshot.commit>",
  "draft_sha256": "<工作单的 draft.case_sha256>",
  "candidate_ids": ["<工作单里的候选 id>", "..."],
  "agent": {"id": "<你的标识>", "role": "comparator"},
  "comparisons": [
    {
      "candidate_case": "<候选 id>",
      "classification": "duplicate|covered|variant|new_pattern|ambiguous",
      "confidence": "high|medium|low",
      "evidence": {
        "root_cause": "same|different|unknown",
        "mechanism": "same|different|unknown",
        "trigger": "same|different|unknown",
        "symptoms": "same|different|unknown",
        "fix": "same|different|unknown",
        "environment": "same|different|unknown",
        "verification": "same|different|unknown"
      },
      "rationale": "<一句话，引用具体证据；不要写“看起来像”>",
      "review_required": true
    }
  ],
  "overall": "duplicate|covered|variant|new_pattern|ambiguous",
  "candidate_case": "<最相关候选 id 或 null>",
  "rationale": "<一句话总结>"
}

必须逐条覆盖工作单里的每一个候选，不能只评价看起来像的。
```

## 独立复核 agent 提示词（只在需要时使用）

触发条件：比较 agent 建议 `duplicate` / `covered`、置信度非 `high`、证据轴出现 `unknown`、
或候选之间结论冲突。复核只做一件事：找**误合并**与**证据缺口**，不负责找新候选。

```text
你是 Ascend Sleuth 的独立复核 agent。下面是一份草稿、候选列表，以及另一个 agent 的比对结论。
你的任务不是重新找候选，而是检查：这个结论有没有把不同根因合并、有没有在证据不足时下结论、
有没有忽略环境/版本/物理实例差异。

工作单：<工作单>
第一份结论：<结论 JSON 的路径或内容>

只返回严格 JSON（四个绑定字段原样抄自工作单）：
{
  "draft_key": "<draft_key>",
  "work_order_id": "<工作单的 work_order_id>",
  "snapshot_commit": "<工作单的 snapshot.commit>",
  "draft_sha256": "<工作单的 draft.case_sha256>",
  "agent": {"id": "<你的标识>", "role": "reviewer"},
  "verdict": "confirm|challenge|insufficient",
  "false_merge_risk": true|false,
  "issues": ["<具体问题，逐条>"],
  "rationale": "<一句话>"
}

判据：
- challenge：结论把不同根因/不同机制/不同物理实例合并了，或证据只够 variant/ambiguous。
- insufficient：关键证据缺失，无法确认；不要用“可能”“大概”补足。
- confirm：证据链成立，且没有发现误合并风险。
- 你只能把结论往保守方向拉，不能把 ambiguous 改成 covered/duplicate。
```

## 主 agent 保存与记录

把每个子 agent 的返回原样保存为：

```text
<results>/<draft_key>.result.json       # 比较 agent
<results>/<draft_key>.review.json       # 复核 agent（最多一个）
```

然后运行：

```bash
python3 scripts/groom_record.py --snapshot <snapshot.json> \
  --work-orders <work-orders.json> --results-dir <results/> --report
```

`groom_record.py` 会重新校验候选覆盖、枚举与理由，并按保守规则聚合；同时核对结果里的
`work_order_id` / `snapshot_commit` / `draft_sha256` / `candidate_ids` 与工作单、快照、当前草稿一致。
**不要手改这些绑定字段**；不一致时整份评估被拒绝为 `binding-mismatch`，不会静默采用。**不要手改聚合结果**；
如果它的结论与你的阅读不一致，先检查子 agent 的 JSON 是否漏了候选或证据轴，再决定是否重跑。

## 失败与降级

- 子 agent 不可用 / 超时 / 返回非 JSON：重试一次；仍失败就把该草稿标 `ambiguous` + 人工复核，
  不要把"没有结果"当成 `new_pattern`。
- 没有子 agent 机制：主 agent 按比较 agent 的同一提示顺序执行，返回同一 schema；不得跳过逐条覆盖。
- 工作单里的候选为 0：没有可比较的对象，`groom_record.py` 会判 `ambiguous` 并进人工复核；
  主 agent 在摘要里写"本轮无候选"，不要用空结果冒充 `new_pattern`。
