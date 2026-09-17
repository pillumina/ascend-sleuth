# 元层 eval 台（arena）——WikiSkill 式 train/val 分离 + 门控自演进

> **给谁读**：要改元层 eval 台（train/val 分离、门控协议、影响账本）的人；**什么时候读**：你要改评测机制本身的稳定性判据时；**读完能做什么**：能说清 train/val 分离怎么防「拿同一批数据自证」，门控协议在哪一层生效。
> **论证层——日常不必读。** 执行规则与机制地图见 [../evolution.md](../evolution.md)。

> 机制决议：EV-2026-013。对应 WikiSkill（arXiv 2608.27454）的元层：候选改动在
> held-out 评测集上**严格提升才接受**、否则回滚、结果留影响账本。本台把 S2 replay
> 从"单池评测"升级为"train/val 分离 + 门控 + 账本"的 eval 台，服务检索/路由层
> 组件（triage 文本 / quickly_check / case 排序）的演进门控。交互层（ixn-replay，
> O8）与归因层是兄弟台，机制见 docs/mechanism/ixn-replay.md。

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

`--stats` 除聚合指标外还写**逐条判决向量**（每条 issue 的 hit/route_ok/rc_match）与**池内容哈希**：
前者是配对检验的输入（没有它，判定只能退回点估计，判词上限降为 weak_accept），后者是"量尺身份"
（池内容变＝换量尺，复用计数归零）。

test/selection 分离前单池运行，分数标注 source: issue-replay。

**两条读数口径（实测喂出来的，别绕过）**：

1. **路由率的分母只算"有真值"的条目**：池条目可能只有 resolution、没有 `expected_ns`（实测一批 20 条里 11 条如此，它们是从 issue 池直接选的、没人标注归属）。把这类算进路由率会凭空造出失败——`--stats` 因此把它们排除在分母外并打印条数，`route_ok.unjudgeable` 字段可读。
2. **非诊断样本不进命中率**：issue 正文为空、或 resolution 是"请把问题描述清楚"这类（实测 1 条：标题 `[Bug]: wait`、正文空白），任何诊断都不可能有结论。这类样本要么单列、要么从命中率分母剔除，否则同时高估（分母虚增）与低估（拉低命中率）。判据：输入文件里没有可判别信号 = 非诊断样本。

**本轮全量重放结果（20/20 条已评分）**：路由 9/9（只有 9 条有路由真值）、命中 **2/20**、结论一致（root_cause_ok）13/20。命中低是**符合预期**的：S2 池从"未沉淀的 closed issue"里选样，池本身就是**覆盖缺口的探针**——它按设计就该大量 miss（miss 即"库里没有这条知识"的缺口信号，走补 case 候选）；它不是"已有 case 的外部验证通道"（那需要池里放已沉淀的 issue，属另一类样本）。

## 4. 门控协议（候选改动 → 接受/回滚）

作用于**检索/路由层组件**（triage 分支文本、quickly_check、case 内容/排序）与低风险 content：

1. 候选 = EV 卡（前置元流程，带 before 反例）；
2. **无回归**：golden 全部通过（改动不倒退）；
3. **提升门（配对 + 复用折减）**：在 selection 池上候选侧 vs baseline 重放对照。判定不是
   "两个比例各看一遍、涨了就收"，而是只数**同一批 issue 上方向不一致的对子**（candidate
   独家命中 b / baseline 独家命中 c）做精确单侧检验，并与阈值比：**判定阈值 α_eff = α/(k+1)**，
   k 是同一份池（同名 + 同内容哈希）上已做过的判定次数。三态判词：
   - `accept`：无回归 + 方向性提升 + p ≤ α_eff → 门控通过；
   - `weak_accept`：无回归 + 提升，但证据不足（p > α_eff，或缺逐条向量）→ **不算门控通过**，
     改动可以留，但不能据此把卡判 validated（补样本/扩池重跑，或如实记证据不足）；
   - `reject`：有回归、无提升，或 baseline 与 candidate 的池哈希不同（跨池纪元不可比）。
   为什么不是"涨了就收"：反复对**同一个池**做接受决定是一串不受控的适应性检验，每次单独看
   都"涨了"，合起来假接受会累积；池越小越严重（16 条池一次翻转就是 +6.25 个百分点，一次翻转
   即可判"提升"）。配对检验让"一次翻转"不再自动成立，复用折减让"反复用同一个池刷通过"自动变难。
   不通过则 **回滚**（git revert / 分支丢弃）；
4. **账本**：`scripts/eval_arena.py --gate` 把 候选 id / 组件 / 分数对照 / 配对读数（b、c、p）/
   复用序号 k / α 与 α_eff / 判词 append 进 `.s2-replay/arena/impact.yaml`（本地；结论随方法论
   PR 投影）。同一份池复用次数达阈值由判据层报出（`proposals/gates.yaml` 的
   `pool_reuse_uncontrolled`，读数见 `scripts/evolution_health.py`）——**复用超限的动作是重新选样
   （换量尺、计数归零）或扩池**，不是把标准说松；
5. 高风险的 dual 级改动（triage 结构等）门控通过后仍按 kb/high-risk 双签送人审——门控是"数据门槛"，不替代人闸（原则五/六）。

判词本身也要有牙齿：`--self-test` 用合成样本复现三态（单次翻转只给 weak_accept、复用 k 次后
同一提升降级、回归必 reject、跨池不可比、无向量降级、复用计数按池哈希归零），CI 跑它
（`kb-checks` 的 arena-gate-rule）。判据写坏了、只会判 accept 了，CI 就红。

golden 无回归 + val 严格提升 与 SkillOpt/WikiSkill 的 `R_val > R_best` 语义同构（pipeline §12 已吸收）；
本节的配对/复用折减是在此之上的**统计口径收紧**：那些工作的闸门语义是"val 上更好就接受"，
本台进一步要求"更好"在配对意义上达到证据门槛。

## 5. 工具

`scripts/eval_arena.py`：
- `--build-pool`：**从已跟踪的 S2 校准集派生池**（`eval/s2/vllm-ascend.yaml` → `.s2-replay/arena/pool-*.yaml`），
  确定性、可复核——池是本地运行件，靠这条命令任何人都能重建，不必依赖"某次会话留下的文件"。
  默认只取 `split=selection`（test 条目标 `held_out: true`，不参与 gate 决策）；`--only-scored` 只收已有 result 的条目；
- `--pool <yaml>`：校验池文件结构；
- `--stats <pool>`：聚合各 issue 的 result → 指标 + 逐条向量 + 池哈希（写 .s2-replay/arena/stats-*.yaml）。
  **先复制一份 baseline stats 再跑改后侧**——两次 `--stats` 写同一个文件名，覆盖掉 baseline
  就没有配对数据了（`cp stats-pool-val.yaml baseline.yaml` 之后才重跑）；
- `--gate --baseline <stats-a> --candidate <stats-b> [--alpha 0.1]`：配对判定（accept /
  weak_accept / reject）+ 追加影响账本；
- `--self-test`：复现判词（合成样本，无需本地池数据；CI 跑它）；
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
| **落地** | 接受判据 v2（配对 + 复用折减 + 三态判词）+ `--self-test` 进 CI（arena-gate-rule）+ 复用判据（`pool_reuse_uncontrolled`） | 随本机制变更 |
| 推进 | selection 池 expected 标注 + baseline replay（首批 17 条） | 池文件落地后下一批（subagent 执行） |
| 推进 | 门控端到端运转一次（真实 miss → 候选 → gate → 合入） | baseline 可用后 |
| 蓝图 | test 分离（selection ≥20）、归因/交互层入台、分数进 timeline（样本 ≥10 带分母） | 规模/数据触发 |

## 8. 原则追溯

| 元素 | 原则 |
|---|---|
| val 永不沉淀、self_consistent 不虚增、分数带分母 | 十（诚实退化）、三 |
| golden 无回归 + val 严格提升 + 回滚 | 一（验证先于交付）、七（变更可逆） |
| 门控是数据门槛不替代人闸（dual 仍双签） | 五（建议与决定分离）、六（闸门硬度） |
| 配对 + 复用折减 + 三态判词（weak_accept 不算通过） | 十（诚实退化：证据不足就说不足，不把"看起来涨了"当门控通过）、十一（判据本身也要可证伪——`--self-test` 进 CI） |
| 池从 ingest 候选按规则选、test 分离按规模闸门 | 十一（数据触发） |
