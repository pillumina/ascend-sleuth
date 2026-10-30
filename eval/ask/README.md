# /ask skill 一轮评测怎么做

一轮 = 10 道题 × 每题最多 2 轮对话。题面跨轮不变；新题只加不改。

## 文件

| 文件 | 内容 |
|---|---|
| `answer-keys.yaml` | 题面与标准答案（kb-ranger 写，唯一题面来源） |
| `cases.yaml` | 从 answer-keys 继承题面，补 turn 2 追问策略与 judge 需要的上下文 |
| `personas.yaml` | 三种角色的问法、追问、满足与放弃条件（只记在评测侧） |
| `rubric.md` | 9 个分项 + 3 条硬失败 + 信息不足题专则 + 反模板检查 |

## 隔离（三条不能破）

1. **ask 子 agent 只看三样**：工作目录 `WT`、`skills/ask/SKILL.md` 全文、用户原话。不给 rubric、answer key、cases，不说"这是评测"。turn 2 时只追加：用户第二句原话 + 它自己 turn 1 的答案全文。
2. **角色模拟不看答案键**：只拿到题面、该角色的 persona 段、ask 的答案全文；产出一句追问。
3. **judge 不看 skill 源文件**：只拿题面、两轮答案、该题 answer key、rubric 维度表与该角色的 need_met 锚点。

## 每题四步（4 次子 agent 调用）

1. `ask(turn 1)`：提示词 = 工作目录 + SKILL.md 全文 + 用户原话（`cases.yaml` 的 `question`）。
2. `persona_sim`：拿 persona 段 + turn 1 答案，产出 turn 2 追问。追问按 `cases.yaml` 的 `turn2_style` 走：`followup`（常规追问）/ `lexical_drift`（口语、错字、英文重问同一点）/ `insufficient_info`（只说"没有更多信息了"）。
3. `ask(turn 2)`：同一个工作目录 + SKILL.md 全文 + turn 2 原话（说明这是同一用户的第二句）。建议用同一会话续跑，退而求其次重发上下文。
4. `judge`：按 `rubric.md` 输出 JSON。

提示词骨架（ask turn 1）：

```text
工作目录：/Users/huangyuxiao/projects/skills/ascend-sleuth-ask
以下是你要遵循的 skill 全文（skills/ask/SKILL.md）：
<SKILL.md 全文>

用户说：
<question>

按 skill 回答。你可以用 bash、grep、read 检索仓库文件。
```

judge 输出格式（每题一条）：

```json
{"case_id":"...","hard_fail":[],"dims":{"correctness":{"score":5,"why":"..."},"sourcing":{},"tri_state":{},"scope":{},"first_action":{},"jargon":{},"brevity":{},"role_fit":{},"robustness":null},"need_met":{"score":4,"why":"..."},"judge_note":"..."}
```

## 指标字段（`metrics.jsonl` 一题一行）

契约固定字段，逐字用：

`case_id, role, layer, turns, skill_chars, refs_read[], answer_chars, est_tokens, dims{}, need_met, hard_fail[], judge_note`

- `turns`：实际轮次（1 或 2）。
- `refs_read[]`：ask 答案或检索里出现并被读过的 ref-id；judge 无法确认时从答案里的出处反推，记 `inferred` 后缀。
- `answer_chars`：两轮答案合计字符数（去空白）。
- `est_tokens`：注入成本粗估 = `skill_chars / 1.6`，四舍五入（对应停手判据第 4 条"注入 ≤4000 token"）。答题成本看 `answer_chars`。
- `dims.robustness`：非漂移题写 `null`。

## 报告落点（`MAIN/eval-reports/ask/`）

- `round-0-probe.md`：探针，一题，确认 ask 子 agent 能用 bash、grep、read。
- `round-N/metrics.jsonl`：一题一行。
- `round-N/summary.md`：每题一行表 + 六条停手判据当前值 + 反模板检查结论 + 角色小结。
- `round-N/transcripts/<case_id>.md`：两轮问答原文，含用户原话、ask 答案、角色追问、judge 依据。
- `round-N/metrics-corrected.jsonl` + `round-N/judge-corrected/`：用修正版 rubric 对同一批 transcripts 复判的结果（含 `cites[]`），与 `metrics.jsonl` 并列，不重跑 ask。
- `round-N/judge-c2/`：judge 校准，两题的第二份独立判分。
- `round-N/extra-probes.md`：坏路径探针与盲辨结果。

## 预算

- 一轮 10 题 ≈ 40 次子 agent 调用（4 次/题）。失败重试的余量另外留 2–4 次。
- judge 提示词 ≤3K token。
- ask 每题检索 ≤2 个文件，答案 ≤400 字（L2 ≤600）。

## 停手判据（每轮在 summary.md 末尾给当前值）

1. 10 题零硬失败。
2. 正确性均值 ≥4.0；L1 全部 5 分。
3. `need_met` 均值 ≥4.0，任一角色 ≥3.5。
4. 注入 ≤4000 token；单题答案 ≤400 字（L2 ≤600）；读文件 ≤2 个。
5. 零"你属于哪类用户"类提问。
6. 老手题的答案里至少一个阈值或判据。

## 口径变更记录

- 2026-10-30（eval 设计审计后）：
  - turn 2 种子不再复述答案里的数值（L2-01 的 5%/1%、L4-02 的 10%/0.2 已改成「你说的那几个判据/阈值怎么用、从哪来」）。理由：用户在 turn 2 先说出数值，答案照抄会被判成"答对"。round-1 已按旧种子跑完，保留原始结果，round-2 用新种子。
  - need_met 只看该角色三条满足项与三条放弃项，judge 不读整份 personas.yaml（personas 的 satisfied_by / gives_up_on 各裁到 3 条）。
  - sourcing 改为逐条核对：每个事实级论断都要核，judge 输出 `cites[]`（claim / ref / quote），核不到写「未核到」。
  - judge 增加一条：turn 2 里用户先说出的数值，答案只是复述时不算独立正确。

- 2026-10-30（round-2 收尾，来自 eval 审计）：`cases.yaml` 每题补 `core_must_include`（2–3 条），rubric 的 correctness 只看这几条，answer-key 其余 must_include 降为加分项。来源：answer key 的必答项顶到 400 字硬线——L1-01 的 must_include 265 字 + must_not 59 字 + first_action 84 字 = 408 字；L3-02 的 must_include 单独 452 字。现行判据下这些题不可能同时满足长度与正确性，L1 全 5 不可达。
- 2026-10-30（round-2 过程说明）：round-2 首跑时 7 道 followup / drift 题的 turn2 原话没有落盘，已重跑这些题的 turn2 并落盘。重跑输入与首跑的关系：turn1 答案文件逐字节未改（首跑的 `ask/<id>-a1.md` 原样复用），persona 提示词相同；u2 是重新生成，措辞可能与首跑那一版有出入。重跑的 a2 是针对重跑生成的 u2 作答，transcript 自洽；首跑 judge 没有拿到 u2，所以全部 10 题带 u2 重判。
