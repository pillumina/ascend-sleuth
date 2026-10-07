# 元层 eval 台（arena）——WikiSkill 式 train/val 分离 + 门控自演进

> **给谁读**：要改元层 eval 台（train/val 分离、门控协议、影响账本）的人；**什么时候读**：你要改评测机制本身的稳定性判据时；**读完能做什么**：能说清 train/val 分离怎么防「拿同一批数据自证」，门控协议在哪一层生效。
> **论证层——日常不必读。** 执行规则与机制地图见 [rsi-mechanism.md](rsi-mechanism.md)。

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
| **regression**（池内分流） | 答案已进知识库的样本（自洽样本，self_consistent） | train/回归信号；不参与门控判定（`--gate` 拒绝） | `--build-pool` 按 case 实名（`knowledge/` 下有同名 case 文件）从同一源拆出（`pool-*-absorbed.yaml`） |
| **test**（终判） | 与 selection 分离的 held-out 子集 | validated 终判（防对 selection 过拟合） | 池规模闸门：**判定池（未吸收样本）条数够支撑判定之后**才划出终判子集——按名义 selection 条数触发会把可判定的题变少（现单池，同 §2.1 纪律） |
| **smoke/self** | 已沉淀 case 的源 issue | train/回归信号（self_consistent 照原值记） | KB case 源 issue 重放 |

**纪律**：val 区 issue **永不沉淀**（只评测、不进知识侧、反馈不回喂——扰动不从评测学）；自洽样本照原值记 `self_consistent`，不计入外部验证。答案已进知识库的样本（下称已吸收样本）由 `--build-pool` 按 case 实名拆进回归池（`role: regression`），判定池里不留它们：答案已在库里的样本留在判定池，会让判定池的分数虚高。

## 2. 池构建（本次首批，2026-09）

候选 = ingest-state processed（vllm-ascend 325）减去 KB 已沉淀（102）→ 233 未沉淀；筛选规则：
closed 且 state_reason=completed（resolution 可溯）+ 实体 Bug/Usage 内容（排除 Doc/营销类与 not_planned）。
首批 **selection 17 条**（见 .s2-replay/arena/pool-val.yaml，本地运行件）：#14483/#14467/#14448/
#14306/#14265/#14082/#13974/#13792/#13719/#13627/#13441/#13379/#13339/#13255/#12933/#12677/#12658
——覆盖 interrupt/performance/precision 与 DS-V4-Flash/GLM-5.2/MTP/PD/mooncake 等族。
expected 标注（namespace/category/fix_ref）由 agent 读 issue 线程产出；**工具只提供池文件与校验，
标注是协议**（与 S2 同构）。标注时若发现输入里没有可判别信号（正文空白、只有环境信息），在校准集行上
标 `non_diagnostic`（真值，或一句原因；空字符串等同未标注）；这类行不进命中率分母、不进配对、也不进吸收指纹，见 §3。

**收样判据（2026-10 收紧，落在 `scripts/s2_calibration.py`）**：上面那句「实体 Bug/Usage 内容」原来只
落在人工约定上，代码用的是「标题不在 6 项黑名单里」且「labels 为空**或**含 `bug`/`triaged`」——`triaged`
近乎恒真，于是流程单也能进池（实测一条：`#12490 [Misc]: Close cherry-pick PR #12265`，labels 只有
`triaged`，进了判定池、回放时才发现没有可诊断内容，三组症状正则命中数全 0）。现在判据是机械的两步：
①标题带流程/文档类前缀（`NON_DIAGNOSTIC_PREFIXES`：`[Doc]`/`[docs]`/`[Documentation]`/`[Feature]`/
`[Feature Request]`/`[Question]`/`[Misc]`/`[Build]`/`[CI]`/`[Test]`/`[Refactor]`/`[Chore]`/`[Release]`，
以及小写 `docs:`/`doc:`/`feat:`/`chore:`/`ci:`/`test:`/`refactor:`）**硬拒**，连 `--include-weak` 也不收；
②其余要求有明确缺陷信号：标题前缀是 `[Bug]`/`[bug]`/`[BugFix]`/`[bugfix]`/`[Usage]`（`[Usage]` 按本节的
「实体 Bug/Usage」在收），或 labels 里含 `bug`。只剩 `triaged` 标签、或标题没有前缀的算**弱信号**——默认
不收，但候选清单会把它们逐条打印出来，要看就带 `--include-weak`（弱信号接在严格候选之后，
`--limit` 先被严格候选填满时不会进池）。这条通道留着是因为弱信号里两种东西
混在一起：既有会被 ① 挡掉的流程单，也有真实缺陷（实测 `#12947` 无前缀、labels 只有
`triaged`，后来撞上了真实的 fix PR #12948）——一票否决会连后者一起丢掉，所以挡在默认值上、把判断
留给人。同一窗口（closed + `triaged`，最近 400 条）量过一次：旧规则通过 339 条，这套判据通过 331 条
（另外 21 条落进弱信号档、48 条被 ① 硬拒，三者相加正好 400）；
当时 20 条校准集里只有 `#12490`（`[Misc]`）与 `#12947`（弱信号）会被挡，其余 18 条都带 `bug` 标签或
`[Bug]` 前缀。窗口里的 issue 列表一直在动，这两个数只作量级参考，别当阈值用。

**吸收分流（2026-10 落地）**：`--build-pool` 从同一份校准集派生两条池：判定池 `pool-val.yaml`
（`role: judgment`，只留未吸收样本）与回归池 `pool-val-absorbed.yaml`
（`role: regression`；`--gate` 按 `role` 字段拒绝它，不看文件名）。吸收判据是 **case 实名**：
`knowledge/` 下存在 `VLLM-ASC-<issue>.yaml`（前缀可用 `--case-prefix` 改），不用"issue 号出现在
正文里"：正文提到别的 issue 是常事（实测 `knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-13639.yaml`
的边界判别里就写着 14871），文本搜索会把未吸收的样本误判成已吸收。case 实名还要求文件名 stem 匹配
命名规则 `^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$`（全大写、以 issue 号结尾）：`knowledge/` 下 169 个
stem 里 138 个匹配，31 个不匹配（都是没有 issue 号的自有名，如 `COMMON-CPU-CACHE-MISS`）。
前缀在库里零匹配时 `--build-pool` 仍退出 0，但会把警告写到 stderr，并把 `cases_with_prefix` 记 0。
当时实测（2026-10-05，跑 `python scripts/eval_arena.py --build-pool` 会打出当前数字）：
`eval/s2/vllm-ascend.yaml` 的 20 条 selection 样本里 10 条已吸收，分流前它们混在判定池里，
分流后判定池 10 条、回归池 10 条。池内容因此变化，`pool_hash` 随之变化，同一池的复用计数归零
（重新选样即换量尺，计数随之归零，这是既有规则）。
池文件里的 `absorption` 记五个键：`case_prefix`、`cases_in_kb`、`cases_with_prefix`、`samples`、
`absorbed`。前缀在库里一条 case 都没匹配到时，`cases_with_prefix` 为 0，命令把这件事打到 stderr：
"回归池 0 条"在两种情形下都会打印，一种是没有样本被吸收，另一种是吸收判据没有输入。

**吸收状态在运行期重判（2026-10 落地）**：吸收若只在 `--build-pool` 那一刻判定，沉淀闭环随后把某条
样本的答案收进知识库，池会变旧而判定照旧出结论。两条池文件因此各记一个 `absorption_rev`：把
**本池参与判定的每一行**按 `id:该行的答案是否已在库里` 排序拼接后取 sha256 前 12 位。`held_out: true`
的行不计入：终判子集本来就不进判定，它被吸收不改变这次判定测的是检索还是背诵，把它算进去只会
造出假过期（同一份池在存储与重算两边得出不同指纹，一份本来有效的判定被拒）。指纹只覆盖本池的
行，不用整库 case 实名集合——后者会把任何一条与样本无关的新 case 也算成池过期，而沉淀是本仓常态，
门会长期拒绝出判词，最后被人绕过。`--stats` 每次重算这个指纹并把结论写进 stats；`--gate` 在判定时刻
按 stats 里记下的逐行样本 id 再算一遍——沉淀可能正好落在 `--stats` 与 `--gate` 之间，沿用那份记录就会
漏掉这一段。对不上说明池里某条样本的答案已被吸收：`--gate` 不出判词、退出码 3、不写影响账本（作废的
运行不得推高复用计数），stderr 列出新被吸收的样本 id 并提示重跑 `--build-pool` 与 `--stats`。`--stats`
本身恒退 0（它是产物生成器，不是判定命令），发现不新鲜在 stdout 打一行警告，判定以 `--gate` 为准。
池文件没有该字段时（旧池、手写池）按未校验放行，但两条命令都会写明"新鲜度无法校验"——"没有校验"
必须与"校验通过"可区分（原则十）。第三种状态是"有指纹、但那份 stats 没记下逐行样本 id"（本字段
落地前的产物）：判定时刻算不出新指纹，`--gate` 写明"判定时刻无法重算"、沿用 `--stats` 那一刻的读数
（账本里 `absorption_recheck.recomputed` 为假），不把它当成校验通过。

## 3. 评分口径（复用 S2 result schema）

每条 issue 一次 diagnose replay 写 `.s2-replay/<issue>.result.yaml`（已有 schema：
namespace/category/hit_case/root_cause/rc_match/route，另见下条 `ground_truth`）。聚合指标（带分母，口径纪律）：

- **命中率** hit_rate = hit_case 非空比例（tier2 命中）；
- **路由正确率** route_ok = route 与 expected_ns 一致比例；
- **结论一致率** rc_match = 结论与 resolution 一致比例（rc_match 字段，人工核验兜底）；
- **可证伪性**（2026-09 加的声明字段）`ground_truth`：这个 issue 的外部结论是什么形态——
  `maintainer-conclusion`（维护者判词）/ `fix-merged`（已合入 fix PR）/ `both` / **`none`（无外部结论）**。
  写 `none` 的样本在结算时**整体跳过**：结论一致与否在这类样本上没有真值，记 `consistent` 无从判对，
  记 `inconsistent` 则会把一条假复审信号压到 case 上（实测 #10913 命中 VLLM-ASC-8646 但该 issue 以
  NOT_PLANNED 关闭、无维护者结论）。字段缺席按旧行为（存量 result 不受影响）。
  **2026-10 补上判定侧的读取方**：此前只有结算侧（`scripts/settle_s2_feedback.py`）按这句话办事，
  判定侧不读它——同一条 `ground_truth: none` 的样本，结算跳过、而 `--stats` 只要它写了
  `root_cause_ok: true` 就把"没有真值的猜测"记成"结论一致"，推高结论一致率。现在 `--stats` 同样把
  `none` 的行剔出结论一致率分母（逐条向量的 `rc_match` 记空），各取值条数写进 `stats["ground_truth"]`
  （`counts` / `none` / `absent`），`--gate` 把两侧读数记进账本。

`--stats` 除聚合指标外还写**逐条判决向量**（每条 issue 的 hit/route_ok/rc_match）与**池内容哈希**：
前者是配对检验的输入（没有它，判定只能退回点估计，判词上限降为 weak_accept），后者是"量尺身份"
（池内容变＝换量尺，复用计数归零）。逐条向量只收参与判定的行：`held_out: true` 的行整体跳过，
跳过条数记在 `held_out_skipped`，向量条目带 `held_out` 字段（恒为假，只为读起来能对上口径）。
标了 `non_diagnostic` 的行同样整体跳过（不读 result、不进指标、不进向量），清单记在
`non_diagnostic_rows`（id + 原因）。
`--stats` 同时把本次重算的吸收状态指纹写进 `absorption_recheck`（§2），并收集每条 result 的**重放版本**
`kb_rev`（口径同 `scripts/kb_rev.py`：检出短 sha，脏工作区带后缀）写进 `replay_revs`
（`counts` / `absent` / `mixed`）；多于一个版本时打印 ⚠。`--gate` 把两侧的 `replay_revs` 与
`ground_truth` 一起记进账本并同样告警（为什么不拒判，见下面第 3 条）。

test/selection 分离前单池运行，分数标注 source: issue-replay。

**三条读数口径（实测喂出来的，别绕过）**：

1. **路由率的分母只算"有真值"的条目**：池条目可能只有 resolution、没有 `expected_ns`（实测一批 20 条里 11 条如此，它们是从 issue 池直接选的、没人标注归属）。把这类算进路由率会凭空造出失败——`--stats` 因此把它们排除在分母外并打印条数，`route_ok.unjudgeable` 字段可读。
2. **非诊断样本不进命中率（2026-10 落地，此前只有口径、没有读取方）**：issue 正文里没有可判别的现象（空白，或只有环境信息）、或 resolution 是"请把问题描述清楚"这类（实测 1 条：标题 `[Bug]: wait`、正文只有 `### Your current environment` 段的环境信息、末尾 `### 🐛Describe the bug` 段为空），任何诊断都不可能有结论。这类样本要么单列、要么从命中率分母剔除，否则同时高估（分母虚增）与低估（拉低命中率）。
   判据：**输入文件里没有可判别信号即非诊断样本**——判据由人下（读校准集那一行的输入），代码不按正文长度猜：机器猜会把"描述简短但可判别"的样本一并剔掉，那是把不可判的样本算成失败。空字符串等同未标注（`non_diagnostic: ""` 与 `false` 都按未标注处理，该行照旧进判定）。
   落点：校准集行上的 `non_diagnostic`（真值或一句原因）→ `--build-pool` 原样带进池行 → `--stats` 单列 `non_diagnostic_rows`，并从命中率分母、逐条向量与吸收指纹里剔除（不进指纹的理由同 `held_out`：它被吸收不改变这次判定测的是检索还是背诵，算进去只会造出假过期）；`--gate` 把两侧条数记进账本，手写/旧版 stats 带着这类向量时 `vectors()` 再滤一道。

3. **重放版本留痕：只告警，不拒判（2026-10 落地）**：result 里原本没有"这次回放在哪份知识库上跑的"这句话，而一批结果常常跨若干次 `git pull` 才跑完——跨版本混算出来的分数前后不可比，同一个候选改动两次统计出的差异可能全部来自知识库版本变了。
   本轮实测的 9 条结果就横跨两次代码推进（`3c3ba14` → `d29d450`）——这个跨版本判断是当次回放留下的旁证推出来的（结果文件自己一条都没记版本，产物里核不到；下次重放请照下面落点写 `kb_rev`）。
   落点：`--stats` 收 `kb_rev` 写 `replay_revs`，混版本打印 ⚠；`--gate` 记进账本并同样告警。版本号由回放者取值（`python3 scripts/kb_rev.py` 末行），result 里没写就记 `absent`，代码不回填。
   **不拒判**：混算是数据质量问题，不是判定不成立，做成拒绝会把"这批分数没法比"和"改动没通过"混成一个信号（原则十）。

**本轮全量重放结果（20/20 条已评分）**：路由 9/9（只有 9 条有路由真值）、命中 **2/20**、结论一致（root_cause_ok）13/20。命中低是**符合预期**的：S2 池从"未沉淀的 closed issue"里选样，池本身就是**覆盖缺口的探针**——它按设计就该大量 miss（miss 即"库里没有这条知识"的缺口信号，走补 case 候选）；它不是"已有 case 的外部验证通道"。

**第三类样本已落地（2026-09 新增，`eval/s2/vllm-ascend-cross.yaml`）**：第三类样本 = 与某条 case 的来源 issue **不同**、但错误签名与该 case 对得上的 issue（"另一个现场撞上同一条知识"）。构造方式是机械的：拿 case 的 quickly_check 签名去 issue 池里搜**同签名的非来源 issue**，只收**已关闭且有维护者结论**（维护者判词 / 已合入 fix PR）的条目——没有外部结论的样本产不出可证伪的 `consistent`，收了也只会变成不可判读的记录。样本的 `expected` 里记 `target_case`（该签名期望撞上的 case）与 `cross_ref`；判定口径是"是否命中目标 case 且结论与 issue 实际处置一致"，命中且一致 → 该 case 的 `validation_record.consistent`（非来源 issue，不是自证）。**独立性守卫（半硬）**：结算前先查该 case 正文有没有引用这个 issue 号（`#N` / `issues/N` / `pulls/N`），引用了就按非独立记 `self_consistent`——实测第一批三条 cross 样本**全都不独立**：#16446、#1767 是各自 case 的来源，#2723 虽然与 VLLM-ASC-1767 无来源关系，但那条 case 的 `verification.detail` 里就写着「#2723 上同一维护者记为…」，命中的结论正是撰写时从它那儿读来的。守卫只挡「正文点名」这一种，同一族判词/同一 fix PR 的关联识别不了，所以 `consistent` 的语义只能是「不是来源、也未在正文被引用」。**选样纪律（本轮实测推出来的）**：下一个 cross 样本必须挑**既非该 case 来源、又未被该 case 引用**的同签名 issue，否则样本再多也只会累积 `self_consistent`。
**外部验证占比不再是判据**：原判据（外部验证卡占比下限 1/3）实测**不可达**——123 张终态卡里只有 14 张的方法能走外部，其余 66 张是 metrics_compare（可复现命令）、43 张是 scan_review（自审），而被这两类改的组件能由回放"碰到"的只有个位数，可达上限约 18%；且原 action 文案自己就写着"只能自证的卡片…不计入外部验证"，即把它们排除出分子却留在分母里。占比降为体检器的读数（外部回放 11.4% · 可复现证据 68.3%，见 `evolution_health.py` 的读数节），判据改问**通道还在不在用**（`external_verification_stall`：最近一次外部验证之后又产出 20 张以上终态卡即报警）。理由是：这个通道缺的是"跑"，不是"改口径"——判据要能被人一次动作清掉。

## 4. 门控协议（候选改动 → 接受/回滚）

作用于**检索/路由层组件**（triage 分支文本、quickly_check、case 内容/排序）与低风险 content：

1. 候选 = EV 卡（前置元流程，带 before 反例）；
2. **无回归（本池指标不降）**：`--gate` 只校验这一层，账本记 `no_regression_scope: arena-pool-only`。
   golden 全量无回归是**另一步**：`scripts/replay_golden.py` 逐条 fixture 跑完整诊断（每条都要模型），
   目前是手动/半自动步骤（golden 回放半自动化的雏形），**不在 `--gate` 命令内**。2026-10 之前本节把它写成门控的第 2 步，
   而 `--gate` 从未执行它——属于文档承诺了、工具没接线；现在把这个范围写进账本，不再声称命令做了它没做的事；
3. **提升门（配对 + 复用折减）**：在 selection 池上候选侧 vs baseline 重放对照（`held_out: true` 的行
   跳过：不读 result、不进指标、不进配对——终判子集不参与门控。无回归的比率取自 stats 的 `metrics`，
   手写 stats 要自己把 `held_out` 行与非诊断行剔除）。判定不是
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
   复用序号 k / α 与 α_eff / 判词 / 无回归范围（`no_regression_scope: arena-pool-only`）/
   两侧的吸收状态重判记录（`absorption_recheck`，判定时刻重算所得）/ 两侧的非诊断样本条数
   （`non_diagnostic_rows`）append 进 `.s2-replay/arena/impact.yaml`（本地；结论随方法论
   PR 投影）。同一份池复用次数达阈值由判据层报出（`proposals/gates.yaml` 的
   `pool_reuse_uncontrolled`，读数见 `scripts/evolution_health.py`）——**复用超限的动作是重新选样
   （换量尺、计数归零）或扩池**，不是把标准说松；
5. 高风险的 dual 级改动（triage 结构等）门控通过后仍按 kb/high-risk 双签送人审——门控是"数据门槛"，不替代人闸（原则五/六）。

`--gate` 的退出码（判词是数据，不是命令成败）：**0** = 判定成立且已写账本（accept / weak_accept /
reject 都算成立，reject 也要留档）；**1** = 读文件失败或池结构错；**2** = 用法输入问题（缺参、把回归池
当判定池）；**3** = 池已不新鲜（`absorption_rev` 对不上，见 §2），判词作废、账本不写。

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
  同时按吸收状态拆出 `<同名>-absorbed.yaml`（`role: regression`）；两个池文件各写自己的 `absorption_rev`
  （§2 的指纹，判定池与回归池行不同，各算一份）；`--case-prefix` 指定 case 实名前缀（默认 `VLLM-ASC`，
  文件名 stem 还要匹配 §2 那条命名规则，否则该 case 不算命中）；
- `--pool <yaml>`：校验池文件结构，并打印吸收状态指纹、`held_out` 条数与非诊断样本条数；
- `--stats <pool>`：聚合各 issue 的 result → 指标 + 逐条向量 + 池哈希（写 .s2-replay/arena/stats-*.yaml）。
  `held_out: true` 的行跳过（不读 result、不进指标、不进逐条向量），跳过条数记 `held_out_skipped`；
  标了 `non_diagnostic` 的行同样跳过，清单（id + 原因）记 `non_diagnostic_rows`；
  顶层另写 `case_prefix`、`judged_ids`（本池参与判定的每一行 id；判定时刻的重算靠它，
  不能用逐条向量代替——没跑 replay 的样本不在向量里，按向量重算会把指纹算成空字符串的哈希、
  把有效的池误判成不新鲜）、`ground_truth`（可证伪性各取值条数：`counts` / `none` / `absent`）、
  `replay_revs`（这批 result 的重放版本集合：`counts` / `absent` / `mixed`，混版本打印 ⚠），
  以及 `absorption_recheck: {rev_pool, rev_now, checked, stale, newly_absorbed}`——
  判定前先看 `stale`（`--stats` 恒退 0，判定以 `--gate` 为准；`--gate` 在判定时刻自己再算一遍，见 §2）。**先复制一份 baseline stats 再跑改后侧**——两次 `--stats` 写同一个文件名，覆盖掉 baseline
  就没有配对数据了（`cp stats-pool-val.yaml baseline.yaml` 之后才重跑）；
- `--gate --baseline <stats-a> --candidate <stats-b> [--alpha 0.1]`：配对判定（accept /
  weak_accept / reject）+ 追加影响账本（含两侧的非诊断样本条数 `non_diagnostic_rows`、两侧的
  `ground_truth` 与 `replay_revs` 读数）；对混版本与 `ground_truth: none` 打印告警但照常出判词
  （§3 第三条口径）；
  判定时刻按 stats 记下的逐行样本 id 重算吸收状态
  （stats 没记这份 id 时写明"判定时刻无法重算"并沿用原读数，见 §2），
  任一侧对不上则不出判词、退出码 3、不写账本（退出码表见 §4）；
- `--self-test`：复现判词（合成样本，无需本地池数据；CI 跑它）；
- `--rc-check <pool>`：结论一致离线对照（agent root_cause vs 标注 resolution_summary，
  启发式信号 + 人工核验清单——归因层/结论一致的评分件，auto 不终判）；`held_out: true` 的行与
  非诊断行同样跳过（两类都不可能有可判的结论）。

## 6. 与既有机制的关系

- S2（§2.1）：本台是 S2 的"门控化"形态；S2 单池评测照旧（日常），arena 是演进门（改动时跑）；
- E2/M2：arena 提供它们的自动评分数据源（triage 修订建议的对照基础）；
- O8/ixn：交互层兄弟台；本台管检索/路由层；
- §12a（WikiSkill）：本台即"§12 末句预留的类 SkillOpt 实验"的正式化（作用域 L2 可自动评分子组件）。

## 7. 分级与闸门

| 分级 | 内容 | 何时 |
|---|---|---|
| **第一批（本 PR）** | 设计文档 + eval_arena.py v1（pool/stats/gate）+ EV-2026-013 | 现在 |
| **落地** | 接受判据 v2（配对 + 复用折减 + 三态判词）+ `--self-test` 进 CI（arena-gate-rule）+ 复用判据（`pool_reuse_uncontrolled`）+ 池按吸收状态分流（吸收样本只进回归池、`--gate` 拒绝回归池）+ 吸收状态在本池范围内运行期重判（`absorption_rev` 对不上则 `--gate` 退出 3、不写账本）+ `held_out` 在 `--stats`/`--gate` 真正生效 + 非诊断样本剔出命中率分母与配对 + 无回归范围写进账本（`no_regression_scope: arena-pool-only`）+ 证据面留痕（`ground_truth: none` 剔出结论一致率分母、重放版本 `kb_rev` 进 `replay_revs` 并在跨版本时告警） | 随本机制变更 |
| 推进 | selection 池 expected 标注 + baseline replay（首批 17 条） | 池文件落地后下一批（subagent 执行） |
| 推进 | 门控端到端运转一次（真实 miss → 候选 → gate → 合入） | baseline 可用后 |
| 蓝图 | test 分离（闸门口径＝判定池条数，见 §1 与 §2；不按名义 selection 条数触发）、归因/交互层入台、分数进 timeline（样本 ≥10 带分母）、判定池扩容（分流已落地；新增未吸收样本仍要人工选样与标注。当前先卡在 baseline 重放没跑过——没有逐条向量，配对检验没有输入） | 规模/数据触发 |

## 8. 原则追溯

| 元素 | 原则 |
|---|---|
| val 永不沉淀、self_consistent 不虚增、分数带分母 | 十（诚实退化）、三 |
| golden 无回归 + val 严格提升 + 回滚 | 一（验证先于交付）、七（变更可逆） |
| 门控是数据门槛不替代人闸（dual 仍双签） | 五（建议与决定分离）、六（闸门硬度） |
| 配对 + 复用折减 + 三态判词（weak_accept 不算通过） | 十（诚实退化：证据不足就说不足，不把"看起来涨了"当门控通过）、十一（判据本身也要可证伪——`--self-test` 进 CI） |
| 池从 ingest 候选按规则选、test 分离按判定池条数 | 十一（数据触发） |
| 评估池按吸收状态分流（已落地）与扩容（待数据） | 十（诚实退化：已沉淀的样本进回归池，不虚增判定样本）、十一（数据触发） |
| 吸收状态在运行期重判、无回归范围写进账本（`arena-pool-only`）、"没有校验"与"校验通过"可区分 | 十（诚实退化：池不新鲜就拒绝出判词；命令没做的事不写成做到了）、六（闸门硬度：拒绝要机械可判） |
