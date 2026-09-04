# 元层 eval 台（arena）——WikiSkill 式 train/val 分离 + 门控自演进

> 机制决议：EV-2026-013。对应 WikiSkill（arXiv 2608.27454）的元层：候选改动在
> held-out 评测集上**严格提升才接受**、否则回滚、结果留影响账本。本台把 S2 replay
> 从"单池评测"升级为"train/val 分离 + 门控 + 账本"的 eval 台，服务检索/路由层
> 组件（triage 文本 / quickly_check / case 排序）的演进门控。交互层（ixn-replay，
> O8）与归因层是兄弟台，机制见 docs/evolution-ixn-replay.md。

## 1. 分层与角色

| 集 | 内容 | 角色 | 数据来源 |
|---|---|---|---|
| **golden** | 23 条构造例 | 无回归保险（任何改动不许倒退） | eval/golden/（提交） |
| **selection**（val 门用） | 未沉淀 closed/completed issue（held-out） | 候选改动的前后对照评分（门控） | ingest 池选样 + expected 标注（本地 .s2-replay/arena/） |
| **test**（终判） | 与 selection 分离的 held-out 子集 | validated 终判（防对 selection 过拟合） | 池规模闸门：selection ≥20 后启用分离（现单池，同 §2.1 纪律） |
| **smoke/self** | 已沉淀 case 的源 issue | train/回归信号（self_consistent 如实标注） | KB case 源 issue 重放 |

**纪律**：val 区 issue **永不沉淀**（只评测、不进知识侧、反馈不回喂——扰动不从评测学）；self_consistent 不虚增外部验证。

## 2. 池构建（本次首批，2026-09）

候选 = ingest-state processed（vllm-ascend 325）减去 KB 已沉淀（102）→ 233 未沉淀；筛选规则：
closed 且 state_reason=completed（resolution 可溯）+ 实体 Bug/Usage 内容（排除 Doc/营销类与 not_planned）。
首批 **selection 17 条**（见 .s2-replay/arena/pool-val.yaml，本地运行件）：#14483/#14467/#14448/
#14306/#14265/#14082/#13974/#13792/#13719/#13627/#13441/#13379/#13339/#13255/#12933/#12677/#12658
——覆盖 interrupt/performance/precision 与 DS-V4-Flash/GLM-5.2/MTP/PD/mooncake 等族。
expected 标注（namespace/category/fix_ref）由 agent 读 issue 线程产出；**工具只提供池文件与校验，
标注是协议**（与 S2 同构）。

## 3. 评分口径（复用 S2 result schema）

每条 issue 一次 diagnose replay 写 `.s2-replay/<issue>.result.yaml`（已有 schema：
namespace/category/hit_case/root_cause/rc_match/route）。聚合指标（带分母，口径纪律）：

- **命中率** hit_rate = hit_case 非空比例（tier2 命中）；
- **路由正确率** route_ok = route 与 expected_ns 一致比例；
- **结论一致率** rc_match = 结论与 resolution 一致比例（rc_match 字段，人工核验兜底）。

test/selection 分离前单池运行，分数标注 source: issue-replay。

## 4. 门控协议（候选改动 → 接受/回滚）

作用于**检索/路由层组件**（triage 分支文本、quickly_check、case 内容/排序）与低风险 content：

1. 候选 = EV 卡（前置元流程，带 before 反例）；
2. **无回归**：golden 全部通过（改动不倒退）；
3. **提升门**：在 selection 池上候选侧 vs baseline 重放对照——命中率提升 或（持平 + 反例命中且归因闭合）才接受；否则 **回滚**（git revert / 分支丢弃）；
4. **账本**：`scripts/eval_arena.py --gate` 把 候选 id / 组件 / 分数对照 / 结局 append 进 `.s2-replay/arena/impact.yaml`（本地；结论随方法论 PR 投影）；
5. 高风险的 dual 级改动（triage 结构等）门控通过后仍按 kb/high-risk 双签送人审——门控是"数据门槛"，不替代人闸（原则五/六）。

golden 无回归 + val 严格提升 与 SkillOpt/WikiSkill 的 `R_val > R_best` 语义同构（pipeline §12 已吸收）。

## 5. 工具

`scripts/eval_arena.py`：
- `--pool <yaml>`：校验池文件结构；
- `--stats <pool>`：聚合各 issue 的 result → 指标（写 .s2-replay/arena/stats-*.yaml）；
- `--gate --baseline <stats-a> --candidate <stats-b>`：对照判定 + 追加影响账本；
- `--rc-check <pool>`：结论一致离线对照（agent root_cause vs 标注 resolution_summary，
  启发式信号 + 人工核验清单——归因层/结论一致的评分件，auto 不终判）。

## 6. 与既有机制的关系

- S2（§2.1）：本台是 S2 的"门控化"形态；S2 单池评测照旧（日常），arena 是演进门（改动时跑）；
- E2/M2：arena 提供它们的自动评分数据源（triage 修订建议的对照基础）；
- O8/ixn：交互层兄弟台；本台管检索/路由层；
- §12a（WikiSkill）：本台即"§12 末句预留的类 SkillOpt 实验"的正式化（作用域 L2 可自动评分子组件）。

## 7. 分级与闸门

| 分级 | 内容 | 何时 |
|---|---|---|
| **第一批（本 PR）** | 设计文档 + eval_arena.py v1（pool/stats/gate）+ EV-2026-013 | 现在 |
| 推进 | selection 池 expected 标注 + baseline replay（首批 17 条） | 池文件落地后下一批（subagent 执行） |
| 推进 | 门控端到端运转一次（真实 miss → 候选 → gate → 合入） | baseline 可用后 |
| 蓝图 | test 分离（selection ≥20）、归因/交互层入台、分数进 timeline（样本 ≥10 带分母） | 规模/数据触发 |

## 8. 原则追溯

| 元素 | 原则 |
|---|---|
| val 永不沉淀、self_consistent 不虚增、分数带分母 | 十（诚实退化）、三 |
| golden 无回归 + val 严格提升 + 回滚 | 一（验证先于交付）、七（变更可逆） |
| 门控是数据门槛不替代人闸（dual 仍双签） | 五（建议与决定分离）、六（闸门硬度） |
| 池从 ingest 候选按规则选、test 分离按规模闸门 | 十一（数据触发） |
