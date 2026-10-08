# 元层 eval 台（arena）：train/val 分离与门控自演进

> 本文写给要改机制自身的元层评测的人。eval 台（下称 arena）是自演进机制在评测层的那部分：它给检索/路由层的候选改动做门控，把 issue 回放拆成 train（供改动参考的样本）与 val（判定改动好坏的样本）两套样本，候选改动在 val 样本上达到证据门槛才接受，否则回滚，结果写进影响账本。
>
> 本文说清三件事：train/val 分离怎么防住拿同一批数据自证，门控协议在哪一层生效，影响账本记了什么。日常执行规则与机制地图见 [rsi-mechanism.md](rsi-mechanism.md)。正文不用内部简称；改脚本、查数据文件之前，先用文末[名词对照](#9-名词对照)把正文用词换成代码与文件里的名字。池的样本条数、已吸收条数与已评分条数随运行变化，本文只在解释判据时引用读数，并写明复算命令。

本台的设计决议是改进项 EV-2026-013。它对应 WikiSkill（arXiv 2608.27454）在元层的做法：候选改动在 held-out 样本（留出、不参与调参的样本）上严格提升才接受，否则回滚，结果写进影响账本。本台把 S2 回放从单池评测升级为 train/val 分离加门控与账本，用来给检索/路由层组件（triage 分支文本、quickly_check、case 内容与排序）的演进做门控。交互层 [ixn-replay.md](ixn-replay.md) 与归因层是兄弟台。

---

## 1. 分层与角色

五套样本各有分工。

| 集 | 内容 | 角色 | 数据来源 |
|---|---|---|---|
| golden | 28 条构造例 | 无回归底线：任何改动都不许让其中一条倒退 | `eval/golden/`（提交进仓库） |
| selection | 未沉淀的 closed/completed issue（held-out） | 候选改动的前后对照评分（门控入口） | 从 ingest 池选样并标 expected，写进本地 `.s2-replay/arena/` |
| regression | 答案已进知识库的样本（自洽样本） | train 信号；不参与门控判定（`--gate` 拒绝） | `--build-pool` 按 case 实名从同一份校准集拆出（`pool-*-absorbed.yaml`） |
| test | 与 selection 分离的 held-out 子集 | validated 终判，防对 selection 过拟合 | 判定池的可评样本数达到触发线后划出，算法见下 |
| smoke/self | 已沉淀 case 的源 issue | train 信号；自洽样本照原值记 `self_consistent` | 知识库 case 的源 issue 重放 |

val 区的 issue 只用于评测：不写进知识库，评测结果也不回喂给知识侧，避免被评的改动从评测数据里学到答案。自洽样本照原值记 `self_consistent`，不计入外部验证。答案已进知识库的样本（下称已吸收样本）由 `--build-pool` 按 case 实名拆进回归池（`role: regression`）：答案已在库里的样本留在判定池，会让判定池的分数虚高，所以判定池里不留它们。

终判子集（test）什么时候划出来，由池规模闸门决定。闸门的条数不是拍出来的，是拿判据反推出来的。先定这套判定要支撑几次判定，记为 K；K 由 owner 定，下面只给「给定 K 需要多少条可评样本」的算法，不替 owner 选 K。池规模这个缺口本身的盘点见 [rsi-mechanism.md](rsi-mechanism.md) 第 8 节的已知缺口第 4 条。

- 第 k 次复用同一个池时，判定阈值折减为 `α_eff = α/(k+1)`（α 默认 0.10，k 从 0 起算）。折减在调用点 `scripts/eval_arena.py:677-678`；`reuse_index()` 本身只按池名与池哈希计数，见 `scripts/eval_arena.py:359-371`。要判 `accept`，配对检验须满足 `P(Bin(b+c, 0.5) ≥ b) ≤ α_eff`，其中 b 是 candidate 独家命中数、c 是 baseline 独家命中数。
- c > 0 不会自动否决，但会摊薄证据：检验的 n 变成 b + c，同一个 b 的 p 值随之变大。k = 0 时，c = 0 只要 b = 4 就达线，c = 1 要 b = 6。下面的反推取 c = 0，给出需要样本最少的情形。
- 取 c = 0：`b*(k)` 是满足 `2^-b ≤ α/(k+1)` 的最小 b，取值为 4、5、5、6、6、6、7、7、7…（k 从 0 起算）。判过的题不能翻第二次，所以要支撑 K 次判定，selection 侧留下的可评样本数至少要有 `Σ_{k<K} b*(k)`：4（K=1）、9（K=2）、14（K=3）、20（K=4）、26（K=5）。
- 终判子集自己也要按同一条判定线判一次，因此至少要有 `b*(0) = 4` 条。两笔相加就是划出终判子集的触发线：判定池的可评样本数 ≥ `4 + Σ_{k<K} b*(k)`，即 8（K=1）、13（K=2）、18（K=3）、24（K=4）。
- 现状（2026-10 读数，见第 3 节）：判定池 9 行、可评 8 行（1 条非诊断样本已剔出），按上式只够 K = 1；升到 13 条才够支撑 2 次判定并同时留下终判子集。本文件与 [roadmap.md](../plan/roadmap.md) 里都没有「判定池 ≥20 条」这个目标：`≥20` 的出处是 `proposals/ideas/EV-2026-013.yaml:80` 的「③test/selection 分离按规模闸门（selection ≥20）启用」，说的是 selection 侧条数，正好等于 K = 4 时 selection 侧的 Σ = 20，两条口径由此对齐。
- 这个下限是必要条件，不是充分条件：它只说池子大到够得上判定线，能不能真判成还取决于池里有多少条真会翻转的题（前一轮 20 条池实测只翻 2 条，缺口主要在这里）。样本条数由 `--stats` 输出的「N/M 条已评分」与 `held_out_skipped` 现算，不另外维护一份数字。

---

## 2. 池构建

候选来自 ingest-state 里 vllm-ascend 的 processed 集合，去掉答案已进知识库的 issue；条数随知识库与 issue 池变化，由 `--build-pool` 打印的 `absorption` 现算（2026-09 立卡时的量级是 processed 325 条）。筛选规则：issue 处于 closed 且 state_reason=completed（resolution 可溯），内容是实体缺陷或用法问题（排除文档类、营销类与 not_planned）。

首批 selection 17 条（2026-09）记在本地运行件 `.s2-replay/arena/pool-val.yaml`：#14483/#14467/#14448/#14306/#14265/#14082/#13974/#13792/#13719/#13627/#13441/#13379/#13339/#13255/#12933/#12677/#12658，覆盖 interrupt/performance/precision 与 DS-V4-Flash/GLM-5.2/MTP/PD/mooncake 等族。此后校准集重新选样，现行 selection 样本是 `eval/s2/vllm-ascend.yaml` 里的 19 条（见本节吸收分流一段），两批 id 不重叠。

expected 标注（namespace/category/fix_ref）由 agent 读 issue 线程产出。工具只提供池文件与校验，标注本身是协议（与 S2 同构）。标注时若发现输入里没有可判别信号（正文空白、只有环境信息），在校准集行上标 `non_diagnostic`，写真值或写一句原因；空字符串等同未标注。这类行不进命中率分母、不进配对，也不进吸收指纹，见第 3 节。

收样判据落在 `scripts/s2_calibration.py`。原来的「实体 Bug/Usage 内容」只落在人工约定上，代码用的是「标题不在 6 项黑名单里」且「labels 为空或含 `bug`/`triaged`」；`triaged` 近乎恒真，于是流程单也能进池。实测一条：`#12490 [Misc]: Close cherry-pick PR #12265` 的 labels 只有 `triaged`，进了判定池，回放时才发现没有可诊断内容，三组症状正则命中数全 0。该条已按下面的判据从校准集删掉（卡 EV-2026-176）。现行判据是机械的两步：

1. 标题带流程或文档类前缀的硬拒，连 `--include-weak` 也不收。前缀列在 `NON_DIAGNOSTIC_PREFIXES`：`[Doc]`/`[docs]`/`[Documentation]`/`[Feature]`/`[Feature Request]`/`[Question]`/`[Misc]`/`[Build]`/`[CI]`/`[Test]`/`[Refactor]`/`[Chore]`/`[Release]`，以及小写 `docs:`/`doc:`/`feat:`/`chore:`/`ci:`/`test:`/`refactor:`。
2. 其余条目要有明确的缺陷信号：标题前缀是 `[Bug]`/`[bug]`/`[BugFix]`/`[bugfix]`/`[Usage]`（`[Usage]` 按「实体 Bug/Usage」收），或 labels 里含 `bug`。只剩 `triaged` 标签、或标题没有前缀的算弱信号，默认不收；候选清单会把它们逐条打印出来，要看就带 `--include-weak`（弱信号接在严格候选之后，`--limit` 先被严格候选填满时不会进池）。

同一窗口（closed 加 `triaged`，最近 400 条）量过一次：旧规则通过 339 条，这套判据通过 331 条，另外 21 条落进弱信号、48 条被第 1 条硬拒，三者相加正好 400。当时 20 条校准集里只有 `#12490`（`[Misc]`）与 `#12947`（弱信号）会被挡下，其余 18 条都带 `bug` 标签或 `[Bug]` 前缀。`#12490` 现已删除（卡 EV-2026-176），现行 19 条里只剩 `#12947` 会被这条通道挡下。弱信号这条通道留着，是因为里面既有真实缺陷（`#12947` 就是：无前缀，labels 只有 `triaged`，后来撞上了真实的 fix PR #12948），也有不带流程或文档类前缀的流程单，后者第 1 条挡不到。一票否决会连真实缺陷一起丢掉，所以把它挡在默认值上，把判断留给人。窗口里的 issue 列表一直在动，这几个数只作量级参考，不当阈值用。

吸收分流：`--build-pool` 从同一份校准集派生两条池，判定池 `pool-val.yaml`（`role: judgment`，只留未吸收样本）与回归池 `pool-val-absorbed.yaml`（`role: regression`；`--gate` 按 `role` 字段拒绝它，不看文件名）。吸收判据是 case 实名：`knowledge/` 下存在 `VLLM-ASC-<issue>.yaml`（前缀可用 `--case-prefix` 改）。不用「issue 号出现在正文里」做判据，因为正文提到别的 issue 是常事：`knowledge/inference/vllm-ascend/interrupt/VLLM-ASC-13639.yaml` 的边界判别里就写着 14871，文本搜索会把未吸收的样本误判成已吸收。case 实名还要求文件名 stem 匹配命名规则 `^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+$`（全大写、以 issue 号结尾）：`knowledge/` 下 169 个 stem 里 138 个匹配，31 个不匹配（都是没有 issue 号的自有名，如 `COMMON-CPU-CACHE-MISS`）。前缀在库里零匹配时 `--build-pool` 仍退出 0，但会把警告写到 stderr，并把 `cases_with_prefix` 记 0。

池内容的一轮读数（2026-10-05，跑 `python3 scripts/eval_arena.py --build-pool` 会打出当前数字）：`eval/s2/vllm-ascend.yaml` 的 19 条 selection 样本里 10 条已吸收；分流前它们混在判定池里，分流后判定池 9 条、回归池 10 条。池内容因此变化，`pool_hash` 随之变化，同一池的复用计数归零。重新选样即换了判定输入，计数归零是既有规则。

池文件里的 `absorption` 记五个键：`case_prefix`、`cases_in_kb`、`cases_with_prefix`、`samples`、`absorbed`。前缀在库里一条 case 都没匹配到时，`cases_with_prefix` 为 0，命令把这件事打到 stderr；「回归池 0 条」在两种情形下都会打印，一种是没有样本被吸收，另一种是吸收判据没有输入。

吸收状态在运行期重判。吸收若只在 `--build-pool` 那一刻判定，沉淀闭环随后把某条样本的答案收进知识库，池会变旧而判定照旧出结论。两条池文件因此各记一个 `absorption_rev`：把本池参与判定的每一行按 `id:该行的答案是否已在库里` 排序拼接后取 sha256 前 12 位。`held_out: true` 的行不计入：终判子集本来就不进判定，它被吸收不改变这次判定测的是诊断能力还是从库里查到答案，把它算进去，同一份池就会在存储与重算两边得出不同指纹，一份本来有效的判定被拒。

指纹只覆盖本池的行，不用整库 case 实名集合：后者会把任何一条与样本无关的新 case 也算成池过期，而沉淀是本仓常态，门会长期拒绝出判词，最后被人绕过。`--stats` 每次重算这个指纹并把结论写进 stats；`--gate` 在判定时刻按 stats 里记下的逐行样本 id 再算一遍，因为沉淀可能正好落在 `--stats` 与 `--gate` 之间，沿用那份记录就会漏掉这一段。对不上说明池里某条样本的答案已被吸收：`--gate` 不出判词、退出码 3、不写影响账本（作废的运行不得推高复用计数），stderr 列出新被吸收的样本 id 并提示重跑 `--build-pool` 与 `--stats`。`--stats` 本身恒退出 0（它是产物生成器，不是判定命令），发现不新鲜在 stdout 打一行警告，判定以 `--gate` 为准。

池文件没有该字段时（旧池、手写池）按未校验放行，但两条命令都会写明新鲜度无法校验：没有校验必须与校验通过可区分（原则十）。第三种状态是有指纹、但那份 stats 没记下逐行样本 id（本字段落地前的产物）：判定时刻算不出新指纹，`--gate` 写明判定时刻无法重算，沿用 `--stats` 那一刻的读数（账本里 `absorption_recheck.recomputed` 为假），不把它当成校验通过。

---

## 3. 评分口径（复用 S2 result schema）

每条 issue 跑一次 diagnose 回放，写 `.s2-replay/<issue>.result.yaml`，沿用已有 schema：namespace/category/hit_case/root_cause/rc_match/route，另加下面的 `ground_truth`。聚合指标都带分母：

- 命中率 hit_rate：hit_case 非空的比例（tier2 命中）；
- 路由正确率 route_ok：route 与 expected_ns 一致的比例；
- 结论一致率 rc_match：结论与 resolution 一致的比例（`rc_match` 字段，人工核验兜底）；
- 可证伪性 `ground_truth`：这个 issue 的外部结论是什么形态，取 `maintainer-conclusion`（维护者判词）、`fix-merged`（已合入 fix PR）、`both`、`none`（没有外部结论）。写 `none` 的样本在结算时整体跳过：结论一致与否在这类样本上没有真值，记 `consistent` 判不出对错，记 `inconsistent` 则会把一条假复审信号压到 case 上（实测 #10913 命中 VLLM-ASC-8646，但该 issue 以 NOT_PLANNED 关闭，没有维护者结论）。字段缺席按旧行为处理，存量 result 不受影响。

判定侧也要读这个字段。此前只有结算侧（`scripts/settle_s2_feedback.py`）按上面的规则办事，判定侧不读它：同一条 `ground_truth: none` 的样本，结算跳过，而 `--stats` 只要它写了 `root_cause_ok: true` 就把没有真值的猜测记成结论一致，推高结论一致率。现在 `--stats` 同样把 `none` 的行剔出结论一致率分母（逐条向量的 `rc_match` 记空），各取值条数写进 `stats["ground_truth"]`（`counts`/`none`/`absent`），`--gate` 把两侧读数记进账本。

`--stats` 除聚合指标外还写逐条判决向量（每条 issue 的 hit/route_ok/rc_match）与池内容哈希：前者是配对检验的输入（没有它，判定只能退回点估计，判词上限降为 `weak_accept`），后者是这份池的身份（池内容变，复用计数归零）。逐条向量只收参与判定的行：`held_out: true` 的行整体跳过，跳过条数记在 `held_out_skipped`，向量条目带 `held_out` 字段（恒为假，只为读起来能对上口径）。标了 `non_diagnostic` 的行同样整体跳过（不读 result、不进指标、不进向量），清单记在 `non_diagnostic_rows`（id 加原因）。

`--stats` 同时把本次重算的吸收状态指纹写进 `absorption_recheck`（第 2 节），并收集每条 result 的重放版本 `kb_rev`（口径同 `scripts/kb_rev.py`：检出短 sha，脏工作区带后缀）写进 `replay_revs`（`counts`/`absent`/`mixed`）；多于一个版本时打印 ⚠。`--gate` 把两侧的 `replay_revs` 与 `ground_truth` 一起记进账本并同样告警，不拒判的理由见下面第 3 条。

test/selection 分离前单池运行，分数标注 `source: issue-replay`。

评分口径有三条，都是从实测里得出来的，不要绕过：

1. 路由率的分母只算有真值的条目。池条目可能只有 resolution、没有 `expected_ns`：实测判定池 9 行里 7 行如此；剔掉那条非诊断样本后参评 8 行，其中只有 2 行标了 `expected_ns`，它们是从 issue 池直接选的，没有人标注归属。把这类算进路由率会凭空造出失败，`--stats` 因此把它们排除在分母外并打印条数，读数见 `route_ok.unjudgeable`。
2. 非诊断样本不进命中率。issue 正文里没有可判别的现象（空白，或只有环境信息），或 resolution 是「请把问题描述清楚」这类，任何诊断都不可能有结论。这类样本要么单列、要么从命中率分母剔除，否则同时高估（分母虚增）与低估（拉低命中率）。实测 1 条：`12980`，标题 `[Bug]: wait`，正文只有 `### Your current environment` 段的环境信息，末尾 `### 🐛Describe the bug` 段为空。判据是输入文件里没有可判别信号即非诊断样本，由人下（读校准集那一行的输入），代码不按正文长度猜：机器猜会把描述简短但可判别的样本一并剔掉，那是把不可判的样本算成失败。空字符串等同未标注（`non_diagnostic: ""` 与 `false` 都按未标注处理，该行照旧进判定）。落点：校准集行上的 `non_diagnostic`（真值或一句原因）→ `--build-pool` 原样带进池行 → `--stats` 单列 `non_diagnostic_rows`，并从命中率分母、逐条向量与吸收指纹里剔除（不进指纹的理由同 `held_out`，见第 2 节）；`--gate` 把两侧条数记进账本，手写或旧版 stats 带着这类向量时 `vectors()` 再滤一道。
3. 重放版本留痕，只告警不拒判。result 里原本没有「这次回放在哪份知识库上跑」这句话，而一批结果常常跨若干次 `git pull` 才跑完，跨版本混算出来的分数前后不可比，同一个候选改动两次统计出的差异可能全部来自知识库版本变了。本轮实测的 9 条结果横跨两次代码推进（`3c3ba14` → `d29d450`），这个跨版本判断是当次回放留下的旁证推出来的（结果文件自己一条都没记版本，产物里核不到；下次重放请照下面的落点写 `kb_rev`）。落点：`--stats` 收 `kb_rev` 写 `replay_revs`，混版本打印 ⚠；`--gate` 记进账本并同样告警。版本号由回放者取值（`python3 scripts/kb_rev.py` 末行），result 里没写就记 `absent`，代码不回填。不拒判的理由：混算是数据质量问题，不是判定不成立，做成拒绝会把这批分数没法比和改动没通过混成一个信号（原则十）。

本轮重放读数（2026-10，判定池 9 条，其中 8 条已评分）：路由 2/2（参评 8 行里只有 2 行标了 `expected_ns`，其余 6 行不计入分母）、命中 0/8、结论一致（`root_cause_ok`）5/6。这是删掉一条不可诊断样本后的池，见卡 EV-2026-176。另有 2 条 result 没记 `ground_truth`，`root_cause_ok` 取不到值，按 `scripts/eval_arena.py` 的既有行为不计入这一项的分母；它们仍留在命中率分母 8 里。上一轮 20 条单池的读数是路由 9/9、命中 2/20、结论一致 13/20；分流后判定池换了内容（`pool_hash` 变、复用计数归零），两轮不可直接比。

命中低是设计使然：S2 池从未沉淀的 closed issue 里选样，池本身就是用来暴露覆盖缺口的，按设计就该大量不命中，不命中即库里没有这条知识，走补 case 候选。它不是已有 case 的外部验证通道。

第三类样本（`eval/s2/vllm-ascend-cross.yaml`）是与某条 case 的来源 issue 不同、但错误签名与该 case 对得上的 issue，即另一个现场撞上同一条知识。构造方式机械：拿 case 的 quickly_check 签名去 issue 池里搜同签名的非来源 issue，只收已关闭且有维护者结论（维护者判词或已合入 fix PR）的条目；没有外部结论的样本产不出可证伪的 `consistent`，收了也只会变成不可判读的记录。样本的 `expected` 里记 `target_case`（该签名期望撞上的 case）与 `cross_ref`；判定口径是「是否命中目标 case，且结论与 issue 实际处置一致」，命中且一致则记进该 case 的 `validation_record.consistent`（非来源 issue，不是自证）。

独立性守卫：结算前先查该 case 正文有没有引用这个 issue 号（`#N`、`issues/N`、`pulls/N`），引用了就按非独立记 `self_consistent`。实测第一批三条 cross 样本全都不独立：#16446 与 #1767 是各自 case 的来源；#2723 虽然与 VLLM-ASC-1767 没有来源关系，但那条 case 的 `verification.detail` 里写着「#2723 上同一维护者记为…」，命中的结论正是撰写时从它那儿读来的。守卫只挡正文点名这一种，同一族判词或同一 fix PR 的关联识别不了，所以 `consistent` 的语义只能是「不是来源、也未在正文被引用」。

选样纪律：下一个 cross 样本必须挑既非该 case 来源、又未被该 case 引用的同签名 issue，否则样本再多也只会累积 `self_consistent`。

外部验证占比不再是判据。原判据要求外部验证卡占比下限 1/3，实测不可达。以 2026-10 的终态卡为例：方法能走外部的（`golden_replay` 与 `issue_replay`）只有 19 张，其余 154 张里 87 张是 `metrics_compare`（有可复现命令，客观但不来自系统之外）、67 张是 `scan_review`（人或 agent 自审），而这两类改的组件能被回放碰到的只有个位数，可达上限约 18%。原判据的动作文案自己就写着「只能自证的卡片…不计入外部验证」，把它们排除出分子却留在分母里，占比到不了 1/3。占比因此降为体检器的读数（外部验证占比与可复现证据占比都由 `python3 scripts/evolution_health.py` 的输出现算，同期读数为 11% 与 70%），判据改问通道还在不在用：`external_verification_stall` 在最近一次外部验证之后又产出 20 张以上终态卡时报警。理由是这条通道缺的是跑，不是改口径，判据要能被人一次动作清掉。

---

## 4. 门控协议：接受与回滚

门控作用在检索/路由层组件（triage 分支文本、quickly_check、case 内容与排序）与低风险 content 上。

1. 候选是改进项卡（前置元流程，带 before 反例）。
2. 无回归（本池指标不降）：`--gate` 只校验这一层，账本记 `no_regression_scope: arena-pool-only`。golden 全量无回归是另一步，不在 `--gate` 命令内：`scripts/replay_golden.py` 逐条 fixture 跑完整诊断（每条都要模型），目前是手动或半自动步骤。门控这一步的范围只到本池，不要把命令读成跑了 golden。
3. 提升门（配对检验加复用折减）：在 selection 池上做候选侧与 baseline 的重放对照。`held_out: true` 的行跳过，不读 result、不进指标、不进配对，终判子集不参与门控。无回归的比率取自 stats 的 `metrics`；手写 stats 要自己把 `held_out` 行与非诊断行剔除。判定不是「两个比例各看一遍、涨了就收」，而是只数同一批 issue 上方向不一致的对子（candidate 独家命中 b、baseline 独家命中 c）做精确单侧检验，再与阈值比。判定阈值是 `α_eff = α/(k+1)`，k 是同一份池（同名加同内容哈希）上已做过的判定次数。三态判词是：
   - `accept`：无回归加方向性提升，且 p ≤ α_eff，门控通过；
   - `weak_accept`：无回归且有提升，但证据不足（p > α_eff，或缺逐条向量），不算门控通过；改动可以留，但不能据此把卡判 validated，要补样本、扩池重跑，或直接记证据不足；
   - `reject`：有回归、无提升，或 baseline 与 candidate 的池哈希不同（池内容不同，分数不可比）。
   为什么不是涨了就收：反复对同一个池做接受决定是一串不受控的适应性检验，每次单独看都涨了，合起来假接受会累积；池越小越严重（判定池现为 9 条，一次翻转就是 +11 个百分点，一次翻转即可判提升）。配对检验让一次翻转不再自动成立，复用折减让反复用同一个池刷通过自动变难。不通过则回滚（`git revert` 或丢弃分支）。
4. 账本：`scripts/eval_arena.py --gate` 把候选 id、组件、分数对照、配对读数（b、c、p）、复用序号 k、α 与 α_eff、判词、无回归范围（`no_regression_scope: arena-pool-only`）、两侧的吸收状态重判记录（`absorption_recheck`，判定时刻重算所得）、两侧的非诊断样本条数（`non_diagnostic_rows`）追加进 `.s2-replay/arena/impact.yaml`（本地文件，结论随方法论 PR 投影）。同一份池的复用次数达阈值由判据层报出（`proposals/gates.yaml` 的 `pool_reuse_uncontrolled`，读数见 `scripts/evolution_health.py`）。复用超限的动作是重新选样（池内容改变、计数归零）或扩池，不是把标准说松。
5. 高风险的 dual 级改动（triage 结构等）门控通过后仍按 kb/high-risk 双签送人审：门控是数据门槛，不替代人闸（原则五、六）。

`--gate` 的退出码（判词是数据，不是命令成败）：0 表示判定成立且已写账本（`accept`/`weak_accept`/`reject` 都算成立，`reject` 也要留档）；1 表示读文件失败或池结构错；2 表示用法输入问题（缺参、把回归池当判定池）；3 表示池已不新鲜（`absorption_rev` 对不上，见第 2 节），判词作废、账本不写。

`--self-test` 用合成样本复现三态：单次翻转只给 `weak_accept`、复用若干次后同一提升降级、回归必 `reject`、跨池不可比、无向量降级、复用计数按池哈希归零。CI 跑它（`kb-checks` 的 `arena-gate-rule`）。判据写坏了、只会判 `accept` 了，CI 就红。

golden 无回归加 val 严格提升，与 SkillOpt/WikiSkill 的 `R_val > R_best` 语义同构（[pipeline.md](pipeline.md) 第 12 节已吸收）。本节的配对检验与复用折减是在此之上把统计口径收紧：那些工作的闸门语义是 val 上更好就接受，本台进一步要求更好在配对意义上达到证据门槛。

---

## 5. 工具

`scripts/eval_arena.py` 的子命令：

- `--build-pool`：从已跟踪的 S2 校准集派生池（`eval/s2/vllm-ascend.yaml` → `.s2-replay/arena/pool-*.yaml`），确定性、可复核，池是本地运行件，跑这条命令任何人都能重建，不必依赖某次会话留下的文件。默认只取 `split=selection`（test 条目标 `held_out: true`，不参与 gate 决策）；`--only-scored` 只收已有 result 的条目；同时按吸收状态拆出 `<同名>-absorbed.yaml`（`role: regression`）；两个池文件各写自己的 `absorption_rev`（第 2 节的指纹，判定池与回归池行不同，各算一份）；`--case-prefix` 指定 case 实名前缀（默认 `VLLM-ASC`，文件名 stem 还要匹配第 2 节那条命名规则，否则该 case 不算命中）。
- `--pool <yaml>`：校验池文件结构，并打印吸收状态指纹、`held_out` 条数与非诊断样本条数。
- `--stats <pool>`：聚合各 issue 的 result，得到指标、逐条向量与池哈希，写 `.s2-replay/arena/stats-*.yaml`。`held_out: true` 的行跳过（不读 result、不进指标、不进逐条向量），跳过条数记 `held_out_skipped`；标了 `non_diagnostic` 的行同样跳过，清单（id 加原因）记 `non_diagnostic_rows`。顶层另写 `case_prefix`、`judged_ids`（本池参与判定的每一行 id，判定时刻的重算靠它，不能用逐条向量代替：没跑 replay 的样本不在向量里，按向量重算会把指纹算成空字符串的哈希、把有效的池误判成不新鲜）、`ground_truth`（各取值条数：`counts`/`none`/`absent`）、`replay_revs`（这批 result 的重放版本集合：`counts`/`absent`/`mixed`，混版本打印 ⚠），以及 `absorption_recheck: {rev_pool, rev_now, checked, stale, newly_absorbed}`。判定前先看 `stale`；`--stats` 恒退出 0，判定以 `--gate` 为准，`--gate` 在判定时刻自己再算一遍（见第 2 节）。跑改后侧之前先复制一份 baseline stats：两次 `--stats` 写同一个文件名，覆盖掉 baseline 就没有配对数据了（`cp stats-pool-val.yaml baseline.yaml` 之后才重跑）。
- `--gate --baseline <stats-a> --candidate <stats-b> [--alpha 0.1]`：配对判定（`accept`/`weak_accept`/`reject`）并追加影响账本（含两侧的非诊断样本条数 `non_diagnostic_rows`、`ground_truth` 与 `replay_revs` 读数）；对混版本与 `ground_truth: none` 打印告警但照常出判词（第 3 节第 3 条）。判定时刻按 stats 记下的逐行样本 id 重算吸收状态（stats 没记这份 id 时写明判定时刻无法重算并沿用原读数，见第 2 节）；任一侧对不上则不出判词、退出码 3、不写账本（退出码表见第 4 节）。
- `--self-test`：用合成样本复现判词，不需要本地池数据；CI 跑它。
- `--rc-check <pool>`：结论一致的离线对照（agent 的 root_cause 对标注 resolution_summary，启发式信号加人工核验清单；这是归因层与结论一致的评分件，auto 不终判）。`held_out: true` 的行与非诊断行同样跳过，两类都不可能有可判的结论。

---

## 6. 与既有机制的关系

- S2 评测（[pipeline.md](pipeline.md) 第 2.1 节）：本台是 S2 的门控化形态。S2 单池评测照旧用于日常，arena 是演进时的门，改动时才跑。
- 路由错例演进（从 trace 提取路由错例，产出 triage 修订建议）与 fixture 回放半自动化：arena 提供它们的自动评分数据源（[roadmap.md](../plan/roadmap.md) 里的两个可演进事项）。
- 交互层 [ixn-replay.md](ixn-replay.md)：兄弟台，本台管检索/路由层。
- [pipeline.md](pipeline.md) 第 12a 节（WikiSkill）：本台把第 12 节末句预留的类 SkillOpt 实验正式化，作用域是流程与 skill 层里可自动评分的子组件。

---

## 7. 分级与闸门

| 状态 | 内容 | 触发 |
|---|---|---|
| 已落地 | 设计文档与 `eval_arena.py` 的三个子命令（pool/stats/gate），改进项 EV-2026-013 | 无 |
| 已落地 | 接受判据（配对检验、复用折减、三态判词）；`--self-test` 进 CI（`kb-checks` 的 `arena-gate-rule`）；复用判据 `pool_reuse_uncontrolled`；池按吸收状态分流（吸收样本只进回归池，`--gate` 拒绝回归池）；吸收状态在本池范围内运行期重判（`absorption_rev` 对不上则 `--gate` 退出 3、不写账本）；`held_out` 在 `--stats` 与 `--gate` 生效；非诊断样本剔出命中率分母与配对；无回归范围写进账本（`no_regression_scope: arena-pool-only`）；证据面留痕（`ground_truth: none` 剔出结论一致率分母，重放版本 `kb_rev` 进 `replay_revs` 并在跨版本时告警） | 随本机制变更 |
| 推进 | selection 池的 expected 标注与基线回放（现行 19 条；基线已出一轮，判定池 9 条里 8 条有逐条向量） | 继续扩样本 |
| 推进 | 门控端到端运转一次（真实 miss → 候选 → gate → 合入） | baseline 可用后 |
| 蓝图 | test 分离（触发线按判定线反推，见第 1 节）、归因层与交互层入台、分数进 timeline（样本 ≥10 且带分母）、判定池扩容（分流已落地，新增未吸收样本仍要人工选样与标注；下一步的闸门在样本规模，见第 1 节） | 规模或数据触发 |

---

## 8. 原则追溯

| 元素 | 原则 |
|---|---|
| val 样本不写进知识库、`self_consistent` 不虚增、分数带分母 | 十（诚实退化）、三 |
| golden 无回归加 val 严格提升加回滚 | 一（验证先于交付）、七（变更可逆） |
| 门控是数据门槛，不替代人闸（dual 仍双签） | 五（建议与决定分离）、六（闸门硬度） |
| 配对检验、复用折减、三态判词（`weak_accept` 不算通过） | 十（诚实退化：证据不足就说不足，不把看起来涨了当门控通过）、十一（判据本身也要可证伪：`--self-test` 进 CI） |
| 池从 ingest 候选按规则选、test 分离按判定池条数 | 十一（数据触发） |
| 评估池按吸收状态分流与扩容 | 十（诚实退化：已沉淀的样本进回归池，不虚增判定样本）、十一（数据触发） |
| 吸收状态在运行期重判、无回归范围写进账本、没有校验与校验通过可区分 | 十（诚实退化：池不新鲜就拒绝出判词；命令没做的事不写成做到了）、六（闸门硬度：拒绝要机械可判） |

---

## 9. 名词对照

正文用白话。改脚本、查数据文件时，用这张表换成代码与文件里的实际名字。

| 正文里说 | 代码与文件里的名字 |
|---|---|
| eval 台、arena | `scripts/eval_arena.py` |
| 改进项卡 | `proposals/ideas/` 下的卡 |
| 回归样本、golden | `eval/golden/` 下的 fixture，`scripts/replay_golden.py` |
| 对照样本集、校准集 | `eval/s2/vllm-ascend.yaml`、`eval/s2/vllm-ascend-cross.yaml` |
| 判定池 | `.s2-replay/arena/pool-val.yaml`（`role: judgment`） |
| 回归池 | `.s2-replay/arena/pool-val-absorbed.yaml`（`role: regression`） |
| 已吸收样本 | 答案已进知识库的样本，判据是 `knowledge/` 下存在 `VLLM-ASC-<issue>.yaml` |
| 吸收状态指纹 | `absorption_rev`、`absorption_recheck` |
| 池规模闸门、触发线 | 判定池可评样本数 ≥ `4 + Σ_{k<K} b*(k)` |
| 判定阈值折减 | `α_eff = α/(k+1)`、`ALPHA_DEFAULT`、`reuse_index()` |
| 三态判词 | `accept`、`weak_accept`、`reject`，`decide()` |
| 影响账本 | `.s2-replay/arena/impact.yaml` |
| 池内容哈希 | `pool_hash` |
| 逐条判决向量 | stats 的 `issues`，`vectors()` |
| 重放版本 | `kb_rev`、`replay_revs`、`scripts/kb_rev.py` |
| 用历史问题重跑 | S2 issue-replay，`scripts/s2_replay.py` |
| 结算 | `scripts/settle_s2_feedback.py` |
| 收样判据 | `scripts/s2_calibration.py`、`NON_DIAGNOSTIC_PREFIXES` |
| 判据、体检器 | `proposals/gates.yaml`、`metrics/gates.yaml`、`scripts/evolution_health.py` |
| 每周批审 | `knowledge-groom` |
