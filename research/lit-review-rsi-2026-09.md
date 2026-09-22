# RSI / 自演化机制 / skill 库准入 — literature slice, 2026-01 → 2026-09（+ 2023–2025 锚点）

核验于 2026-09-17。目的是两件事：**为现有设计找外部背书**，以及**找可直接落地的元机制增量**。
每条标注核验强度：【自核】= 本轮直接抓取一手页（arXiv abs / ACL / proceedings）；【转核】= 由调研子代理抓一手页后转述（URL 已给，未二次亲验）；【存疑】= 未找到一手来源或质量不足。

排名按"与本项目机制的相关度 × 证据强度"，不按新奇度。

---

## 0. 三句话结论

1. **范式级背书**：2026 年出现了一条明确的路线转移——自我改进的持久对象从 *agent* 换成 *受治理的知识库*。斯坦福/加州理工的 [Knowledge-Centric Self-Improvement](https://arxiv.org/abs/2607.19592) 说的正是本项目论题：agent 通用且可弃，唯一持久物是 curated KB；因此改进**更可审、可迁移、可移植**，且能迁移到 held-out 任务与**跨 LLM 家族**。
2. **闸门是全场的承重墙**：所有报告"单调安全增益"的系统都把功劳归给**接受规则**而非提议者；最可复现的负结果是**无闸门的自我演化默认高风险**（自策展上下文在一个基准近最优、在另一个崩到 0.14）。
3. **本项目已测出的缺口有精确解**：「接受者形同虚设」在 2026 年的文献里有名字与数学——[PACE](https://arxiv.org/abs/2606.08106) 证明"分数涨了就接受"是对同一 dev 估计的**适应性多重检验**，等于 agent 在对自己 p-hacking；并给出 anytime-valid 的接受判据。本仓对应的缺口不是判据报红，而是**终态卡里从未出现"试了、评估不成立、不采纳"**（"换方向"有 5 张，"不采纳"为 0）——判据读数与这个事实要分开读（见 §2.1 的勘误）。

---

## 1. 直接背书（现有设计 ← 外部证据）

| 现有设计 | 外部证据 | 关系 |
|---|---|---|
| 三级知识 + skill 自包含 + 方法论/知识资产分面 + fork 模式；「知识库是资产、agent 可弃」 | Knowledge-Centric Self-Improvement（Stanford/Caltech，2026-07，[2607.19592](https://arxiv.org/abs/2607.19592)）：改进被收进知识而非 agent，因此更可审、可迁移、可移植；跨 held-out 任务与跨 LLM 家族迁移；相对 agent-centric 基线省 token 成本【自核】 | **同构**。这是本项目论题目前最强的一手背书，且它把"可迁移/可移植"做成了可测量主张 |
| `eval/holdout.yaml` 按内容哈希钉住的**硬门** + "此前通过的不许变失败" | RSEA（[2606.28374](https://arxiv.org/abs/2606.28374)）：在 disjoint held-out 上严格 keep-better 才提交，使递归自演化**单调安全**（任何基准上都不显著差于基座，且有害时回退 vanilla ReAct）；对照 Dynamic Cheatsheet 无闸门在线策展：ALFWorld 70.7% 近最优，WebShop 崩到 **0.14**（ReAct 0.43）【自核】 | **支持"硬门而非监控指标"**。0.70→0.14 就是"自策展知识无一刀切验收集"的形态 |
| `confidence.self_resolved` 与 `hits` 分离（自证不计命中） | Ratchet（Amazon，[2605.22148](https://arxiv.org/abs/2605.22148)）：judge 把失败判为通过的比例 ≥ (1−τ)/2 时，**任何样本量都退不掉一条 skill**；两个错误方向不对称——通过误判为失败只损失样本效率，失败误判为通过**置换掉淘汰统计量且规则内无法修正**。审计锚点：LLM 自写 skill **+0.0pp**，人写 **+16.2pp**【自核】 | **直接背书**。"工程师自报 resolve"就是那个错误方向；把自证隔离出去不是口径洁癖 |
| 每命名空间 cap + 软退休 + 冷却/复活；"库无界则信噪比单调不增" | Ratchet/ Library Drift（[2605.19576](https://arxiv.org/abs/2605.19576)，FAGEN@ICML 2026）【转核】：不维护的库会**漂移到"注入 skill 比不注入更差"**；修法是按实测贡献淘汰 + 宽度上限 C + 约束合成（100 轮 MBPP+ hard 切片 pass@1 0.258 → 0.584）。消融：关掉注入=停在平地（+0.002），**过早退休=主动有害**（−0.019） | cap 是承重结构（也出现在收敛界里），"过早退休有害"背书"cold case 不退休" |
| ADR-0002 不上向量检索、检索走词法/结构 | 大 skill 库检索比较（[2608.06196](https://arxiv.org/abs/2608.06196)）【转核】：690 skills / 117 条**非回显**查询，混合词法+embedding top-5 73.5%±8.0；把词法换成类型化关系图**显著更差**（−11.2pt, p=0.0007），98.6% 的边连的是排序器已经召回的 skill；作者自写查询会把 hit@5 高估**最多 44 点** | 图/关系层不能换召回；且"自写查询高估"是评测查询必须来自真实 trace 的证据 |
| 检索式必须来自真实 trace、不信作者构造 | 同上【转核】 | 与 `docs/eval.md`「回放记录会腐烂、要当场重跑」同向 |
| 误诊归因先读 trace 再改知识/流程 | StarHarness（ServiceNow，[2608.24804](https://arxiv.org/abs/2608.24804)）：诊断侧的收益被记为 **fewer false-positive diagnoses** + 轨迹变短；trace 分析把增益归因到接口修复/环境约定/压缩搜索的运维知识【自核】 | 同构，且它把"更少假阳性诊断"当作一等指标——正是误诊率想动的东西 |
| 不变量写进结构、结构类规则不为功能让步 | Falsifiable Release Gates（[2607.13070](https://arxiv.org/abs/2607.13070)）：六个版本、能力翻倍，INV-1..6 **一次没改**；验收套件 122 → 563 条；自动拒掉一个"只会抬高置信度"的候选；治理路径 0.021 ms/请求【自核】 | 承重证据在"负空间"：能力翻倍而不变量不变。本项目同样声明但**无法证实**（见 §2.3） |

---

## 2. 可采纳的元机制增量（按收益/成本排序）

### 2.1 把"接受判据"从单次通过升级为序贯检验（最高优先）

- **证据**：【自核】[PACE: Anytime-Valid Acceptance Tests for Self-Evolving Agents](https://arxiv.org/abs/2606.08106)（2026-06-06）。核心论点：**薄弱环节是 acceptor 不是 proposer**；把"分数涨了就留"重复几百次＝不受控的适应性多重检验，agent 在对自己 p-hacking。数据：有真改进混在噪声里时，greedy 接受 **30–42% 假接受、10–33% 有害编辑**；**根本没真增益**时，greedy 每轮提交 **13–21 次虚假自改**（72–100% 为假），把最脆的 agent 压低 4.9 分，而 PACE 停在基线。方法：候选与现任在**同一批实例**上配对比较，用 testing-by-betting 的 e-process 累积决定性证据，在 optional stopping 下控制**每个候选的假接受概率**，评估成本还降约 18%。
- **落到哪（已按此落地，见 §6）**：不是 `ev_measure.py`（那是"卡里声明的期望 vs 当前检出一次执行"，不是接受者），而是**元层评测台的门控判据** `scripts/eval_arena.py --gate` ——它此前正是点估计"涨了就收"。
- **为什么现在做**：判据读数要按口径读——`scripts/evolution_health.py` 的 `no_negative_feedback` 判的是终态卡里"不采纳 + 换方向"的合计，**该合计当前为 5（全部来自"换方向"，"不采纳"为 0）**，即判据不越界；真正缺的是"试了、评估不成立、不采纳"这一种结局（一次也没有），而点估计接受者正是让这种结局难以出现的那类规则。**勘误**：本文早期版本写成"该判据当场就是红的"，实际读数以脚本为准；`docs/evolution.md` 的同处过期表述已随本次改动修正。
- **成本量级**：脚本改造半天（已花）；存量卡不追溯（按原则十，别事后补写证据）。

### 2.2 产卡者看不到验收样本（三段切分）

- **证据**：【自核】StarHarness（[2608.24804](https://arxiv.org/abs/2608.24804)）：把演化池三分——**proposer 可见的 search 任务 / 对 proposer 隐藏的 selection 任务 / 另留 held-out 测泛化**；三个企业基准 +20–35 个百分点，4–12 次被接受的改动，增益在**被排除出演化过程的任务上仍然保持**，且跨 GPT/Qwen 家族迁移。
- **现状缺口**：本项目的 holdout 是"封存 + 哈希"，但产卡 agent 仍读得到 `eval/golden/`、也读得到自己写进卡里的 `predicted_effect.measure`——即"改被测对象的手同时改得到量尺"只被哈希挡了一半。
- **判决（核实后）**：**部分成立，且统计的那一半已随 §2.1 落地**。落地的部分：池内容哈希＝量尺身份（换池即换纪元），判定阈值按复用序号折减——"拿同一个小池反复刷接受"在机制上被挡住。未落地的部分：真正的**盲切分**（对产卡者隐藏的 selection 集）在本仓做不出来——仓库自己的闸门是"selection ≥20 后才启 test/selection 分离"，当前池 16 条且本地无池文件；16 条再切两半，两边都不足以做任何统计判定。故**不建第二套机制**，登记为既有闸门未达，池扩容后再评估。

### 2.3 给闸门做"牙齿测试"

- **证据**：【自核】Falsifiable Release Gates（[2607.13070](https://arxiv.org/abs/2607.13070)）：作者用自己的规则要求——**故意弄坏被校验的模型，看校验器是否给出最短反例**；不能红的闸门与没有闸门在观测上不可区分。
- **本项目现状**：`holdout-integrity`、`build_index.py --check`、`verify_proposals --check` 都声明为硬门，但**没有记录证明它们曾经红过**。
- **判决（核实后）**：**已存在，本条建议作废**。`scripts/rehearse_evolve_loop.py` 的定位就是这件事（"正例走通、负例必须报错"），其中封存对照集一段逐条断言"改动封存夹具 → `--check` 红""删除 → 红""reseal 后恢复绿且提示要带变更标签"；卡规则、执行记录、共享路径、源码缓存各有负例断言。**勘误**：本文早期版本写"今天没有任何记录证明这些门曾红过"，是未读演练脚本就下的判断。实测 `rehearse --no-panel` 172/174 通过，未通过的两项与本主题无关（见 §6）。

### 2.4 commit-first：让任何 LLM 判断先独立作答再看候选

- **证据**：【自核】[More Convincing, Not More Correct](https://arxiv.org/abs/2607.05904)（2026-07-07）：无参考 judge 在候选条件下打的是**可信度不是正确性**，自博弈把 judge 通过率从 0.72 推到 0.94，而真准确率停在 **0.20**；三 judge 集成仍接受其中 55%（集成不是缓解）。决定性变量是**顺序**：judge 先给出自己的答案再看候选，假阳性率 **0.719 → 0.012**。三家独立结果一致：**改 rubric/提示词来修 judge 会 plateau**，增益来自输出顺序、准入规则、宽度上限这类结构约束。
- **落到哪（已落地）**：groom 预分诊改成"先写自己的症状签名/根因假设/修复族方向，再看候选取证"，写进 `skills/knowledge-groom/SKILL.md` 第 1 步（判断性规范强度，如实标注不进 CI、不改闸门硬度）。

### 2.5 陈旧条目按"内容"而不是"新鲜度"路由复核注意力

- **证据**：【转核】[When Stale Constraints Go Unchecked](https://arxiv.org/abs/2608.25553)：在验证预算只有两条记录时，16 个模型极少复核"读起来已经定论"的约束（约 1/5 episode 去查来源），一旦来源被取代就产出 77.3% / 74.7% / 74.7% 的**陈旧一致决策**。把同样两个槽位中的一条改派给关键路径，挽回 +74.0 / +72.7 / +61.3 个百分点；一条**内容型**分派规则（"优先看那些对当前候选方向声明了限制的记忆"）挽回 +89.3 分，而**新鲜度提示无效**。
- **落到哪（已落地）**：groom 新增「复核注意力的排序」节——按"对本改动面声明了限制"排（compat 区间、expected 阈值、fix_on_mismatch、severity 断言），不按 `last_verified` 排；落点是批审清单单列段 + 高风险变更签字前的顺序。

> 备选（有冲突，需权衡）：【转核】[Habituation at the Gate](https://arxiv.org/abs/2606.22721)（KDD 2026 workshop，400 名重复 reviewer、11,429 次评审、7 个月）：**同一批人**对 agent PR 的批准率 30.1% → 36.8%（p<10⁻⁶），按经验十分位累计差 +14.5pp，同时**评审延迟 ×3.5、行内评论 −22%**（p=0.0014）——多的是排队时间，少的是实际检视。这与 `docs/roadmap.md`「不采集使用/协作/KPI 类观测指标」的既有否决冲突。可行形态是**自身对照的匿名趋势**（本期 vs 上期的批准率与评论密度），不按人建账。

---

## 3. 明确不取 / 反直觉警告

| 不要做 | 依据 |
|---|---|
| **别把"多产候选卡"当解法** | 【自核】[Safe Harness Self-Evolution](https://arxiv.org/abs/2609.08175)（2026-09-08，理论）：生成与认证是**两个不同约束**；当前任务表现不决定"生成合格改动的概率"；**评估受限时，多生成候选不提高成功更新的保证**（于是会出现"还有改进机会却停滞"）；且当期望奖励逼近上界，**识别真实改进的最坏评估成本发散**。→ 支持 M5 token 治理与稳态降频，反对以产卡数量为进度指标 |
| **别靠重写 judge 的 rubric/提示词来修判定** | 【自核】[2607.05904](https://arxiv.org/abs/2607.05904) 明确报告 rubric 重写 plateau；【转核】[PROCTOR](https://arxiv.org/abs/2609.02246) 同样报告 rubric 修补无效，唯一稳定增益来自对 judge 输出**顺序**的结构约束 |
| **别指望关系图/知识图谱层救检索召回** | 【转核】[2608.06196](https://arxiv.org/abs/2608.06196)：图替换显著更差（−11.2pt）；73% 的排序器 miss 在图上不可达 |
| **别用自写查询评测检索** | 【转核】同上：作者自写查询把 hit@5 高估最多 44 点 → 评测查询必须来自真实 trace |
| **别把 skill/知识写长写全** | 【转核】SkillsBench（[2602.12670](https://arxiv.org/abs/2602.12670)）：聚焦（≤3 模块）的 skill **优于**更大更全的捆绑；【自核】[Agent Skills Can Be Harmful](https://arxiv.org/abs/2608.11888)：307 个 skill 致失败样本里，功能性失败**很少来自明显无关的 skill**，而是"看似相关"的 skill 让 agent 错误实现或漏掉必需环节；最大的效率退化来源是 **Excessive Procedure**——过度验证（67 例）与重型实现流水线（30 例），即"把验收清单变成必须执行的工作" |
| **别高估"自我偏好"叙事** | 【转核】[Are LLM Evaluators Really Narcissists?](https://arxiv.org/abs/2601.22548)（ICML 2026）：控制评估者能力基线后，既往自偏好结论只有 51% 的样本保持显著——多数是把低能力噪声读成身份偏差 |

---

## 4. 与既有 §12 / §12a 的增量关系

`docs/mechanism/pipeline.md` §12（SkillOpt）、§12a（WikiSkill, Google Research）已吸收"验证门语义 + 自动评分集 + 知识/skill 分层 + 先例咨询"。本轮增量不在那两条线上，而在三处：

1. **接受规则的统计性质**（PACE）：既有两节都只说"严格提升才接受"，没说"反复用同一个小 dev 集接受"会累积假接受。这是新的一层。
2. **提案者可见性切分**（StarHarness）：既有设计把独立性押在 holdout 封存上，没有"proposer 不可见的 selection 集"这一层。
3. **闸门自身的可证伪性**（Falsifiable Release Gates 的牙齿测试）：既有 `docs/eval.md` 把强度分级写得很清楚，但没有"证明这道门会红"的动作。

其余（commit-first、陈旧条目分派、多候选无益、skill 过长的害处）是补丁级，不动结构。

---

## 5. 证据强度分级（引用时按此降级）

**同行评审**：【转核】DGM（ICLR 2026，Sakana AI/UBC；SWE-bench 20.0→50.0、Polyglot 14.2→30.7，archive 树 + 每步基准验证）、GRASP（EMNLP 2026 Main，[2605.29668](https://arxiv.org/abs/2605.29668)）、SAGE（ACL 2026 Long，[aclanthology 2026.acl-long.69](https://aclanthology.org/2026.acl-long.69/)）、APEX-EM（EMNLP 2026）、ACE（ICLR 2026）、MemEvolve（ICML 2026 poster）、Habituation（KDD 2026 workshop）、专家漏检 AI 错误（PNAS Nexus 2026, pgag146）、MSR 2026 文档 PR（[2601.20171](https://arxiv.org/abs/2601.20171)）。

**预印本但实验强**：【自核】RSEA、StarHarness、Ratchet、PACE、More Convincing、Agent Skills Can Be Harmful、HarnessBank、Skill-α（[2608.01678](https://arxiv.org/abs/2608.01678)）；【转核】SkillsBench、Library Drift、SEAGym、Stale Constraints、检索比较。

**弱（可作思路，不可作论据）**：【转核】Regimes（[2606.10241](https://arxiv.org/abs/2606.10241)，单作者，效应量小且部分不显著）、PROCTOR（[2609.02246](https://arxiv.org/abs/2609.02246)，工业经验目录非对照实验）、[Promotion Governance](https://zenodo.org/records/21185637)（Zenodo 工作论文，28 例；"未治理升格 92.86% 挽回但 53.57% 有害升格，治理后 0% 有害、25% after-success"——只能当**准入控制前沿**的示意）、Temporal Validity（[2606.26511](https://arxiv.org/abs/2606.26511)，单作者）。

**未核到一手，不要引用**：所谓 "The Goodhart Shift: Measuring Train–Holdout Divergence…"（只找到 HF 日推数据集与厂商博客，未见 arXiv/会议一手）；AlphaEvolve 一周年数字（Google 博客正文抓取被截断，仅有二手）；OpenAI 2026-09 的 RSI 披露（openai.com 403，仅 Fortune 二手；企业自述、无独立验证）；各家 lab 安全框架里关于"自我改进阈值"的条款（2026 版未见一手）。METR Frontier Risk Report（2026-05-19）已核到，但主题是失准/擅自部署，**不是**自我改进治理，别混用。

**方法备注**：抓取过程中出现过一层 HTTP 代理域名（`arxiv-org.ezproxy.*`）出现在搜索结果里；本文件所有【自核】条目都用 `arxiv.org/abs/...` 直接复核过标题、作者与摘要，不依赖代理镜像。

---

## 6. 逐条判决与落地状态（核实后）

| # | 建议 | 判决 | 落地 |
|---|---|---|---|
| 2.1 | 接受判据升级为配对 + 复用折减 | **有明确正向收益，已做** | `scripts/eval_arena.py`（逐条向量 + 池哈希、配对判定、复用折减、三态判词、`--self-test`）＋ CI 新 job `arena-gate-rule` ＋ 判据 `pool_reuse_uncontrolled`（`proposals/gates.yaml` + `scripts/evolution_health.py`）＋ `evolve-check`/`self-evolve` 验证门写明 accept-only ＋ `docs/mechanism/eval-arena.md` 同步。卡：EV-2026-105 |
| 2.2 | 产卡者看不到验收样本 | **部分成立，统计的一半已随 2.1 落地；盲切分不做** | 池哈希＝量尺身份、复用折减挡住"刷同一个池"；真盲切分等池 ≥20（仓库既有闸门的 test/selection 分离条件），当前池 16 条且本地无池文件 |
| 2.3 | 闸门牙齿测试 | **已存在，本条作废（勘误）** | `scripts/rehearse_evolve_loop.py` 本就是"负例必须报错"的演练：封存夹具被改/被删必红、reseal 提示标签、卡规则与执行记录各有负例断言 |
| 2.4 | commit-first（先判后看） | **有收益，已做** | `skills/knowledge-groom/SKILL.md` 第 1 步顺序纪律。卡：EV-2026-106（如实声明不可度量） |
| 2.5 | 陈旧条目按内容分派复核 | **有收益，已做** | `skills/knowledge-groom/SKILL.md` 新增「复核注意力的排序」节（判断性规范，不进 CI）。卡：EV-2026-106 |

落地证据（同一批改动，分支 `kb/evolve-gate-hardening`）：

- `python3 scripts/eval_arena.py --self-test` → 12 项断言全过（单次翻转降级、复用折减、回归 reject、跨池不可比、无向量降级、复用计数归零）。
- 合成池端到端：账本复用序号 0→1、阈值 0.1→0.05，同一份提升在首次判 accept、第二次起降为 weak_accept；旧 stats 无向量时判词上限 weak_accept。
- 判据层：`evolution_health` 报 8 条判据 7 条已评估，新判据因本地无账本如实报"数据源缺失"。
- 演练：`rehearse_evolve_loop.py --no-panel` 172/174，新 job 被其"CI 命令逐条复跑"覆盖；两项失败在改动前的 main 上同样失败，且**都不影响 CI**（PR CI 10 个 job 全绿）：面板"空区块不占位"断言只在本地有非空 tally 时走到（CI 干净检出里通过）；演练脚本硬编码容量断言写 85/30 而实际 86/30（脚本内数字腐烂）。
- 已开 PR：**#241**（https://github.com/pillumina/ascend-sleuth/pull/241），CI 全绿，待人审。分支 `kb/evolve-gate-hardening`，worktree 在 `../ascend-sleuth-gatehard`。

顺带核到、**未修**的既有缺陷（与本批改动无关，留证）：

1. `docs/git-workflow.md` 说 kb-checks 等价两条命令，实际 9 个 job、20+ 条命令；
2. `scripts/rehearse_evolve_loop.py` 的容量断言硬编码 85/30（数据已 86/30）→ 演练常年一红；
3. 面板渲染检查的"空区块不占位"断言在当前数据下常年红；
4. `scripts/ev_proposal.py` 的用法注释写了 `--status`，实现里没有该参数（文档与实现不符）。

（`docs/evolution.md` 里"否决为 0"的过期表述已随本批改动修正。）
