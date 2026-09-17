---
name: reference-ingest
description: >
  从 GitCode 等可按 API 枚举的**文档仓**批量摄取官方文档，沉淀为 reference 先验词条（面向训练/推理的中断、精度、性能定位）。编排「仓库文档面普查 → 增量扫描（path×blob sha 记账，防重复抓取与重复评估）→ 候选筛选 → 按需抓正文到本地缓存（ref-docs/，git-ignored，sha 校验）→ 抽取 → 走 to-reference 归类产出 → mark 回写判定」；状态文件 reference-ingest-state.json 是唯一台账，`skipped` 也记账（判过不沉淀的文档下一轮不再评估）。以 token 节省为设计约束：脚本只拉目录树、正文按候选抓、码块与日志裁剪后再读。这是「文档语料 → reference」的统一批量注入入口，与 issue-ingest（issue → case）、to-reference（零散来源 → reference）互补。
---

# Reference Ingest

把**上游文档仓**里的官方文档批量吸收成先验知识。适合：组织（如 GitCode 的 `cann`）下有几十个仓，每个仓的 `docs/` 里散着真正专业的定位手册、错误码表、FAQ、调优指南，而人工一篇篇读不现实、读完也记不住读过哪些。

## 与相邻 skill 的分工（先分清再动手）

| 入口 | 输入 | 产出 | 幂等状态 |
|---|---|---|---|
| `issue-ingest` | 上游 issue 线程 | case 草稿 → inbox | `ingest-state.json`（按 issue 号） |
| `to-reference` | 零散来源（内联 / 单文件 / URL / case 归纳） | reference 词条（active） | 无（单次产出） |
| **本 skill** | **成规模的文档仓** | reference 词条（active，走 to-reference 的产出规则） | `reference-ingest-state.json`（按 path × blob sha） |

**产出规则不在本 skill 里**：怎么归类（type 选择）、怎么写（schema 完整性、零注释、symptom 可 grep）、grill 强度、深审门槛——全部以 `skills/to-reference/SKILL.md` 为准，本 skill 只负责**把候选正文以最低成本、可追溯、不重复的方式交到那一步**。

## 前置

无外部 CLI 依赖：`scripts/gc_docs.py` 直连 GitCode API（读公开仓不需要 token）。任务开始前先确认它可用（`python3 scripts/gc_docs.py repos --org cann | head -3`）；报错就先修脚本而不是改走手工路径。

## 输入方式

```
/skill:reference-ingest cann/hccl                    # 指定仓：扫全仓文档面并给候选
/skill:reference-ingest --org cann --status          # 看台账：各源决策分布（哪些仓扫过、多少未评）
/skill:reference-ingest cann/hccl --prefix docs/zh/user_guide/fault_diagnosis   # 指定子面（推荐：先吃结构化手册）
/skill:reference-ingest "继续沉淀"                    # 续接：读台账找 pending 与未扫的源，按优先级推进
```

| 用户给到什么 | agent 行为 |
|---|---|
| 指定仓/子面 | 直接 scan → 筛 → 抓 → 抽取 |
| 只说"继续" | 读 `reference-ingest-state.json`：先清 pending，再按价值表取下一个源；报一句进度与下一批选题 |
| 给"想吸收某主题的知识" | 在已扫源里按路径关键词检索（`status <repo> --decision pending` + 关键词），不重新全量扫 |

## 状态文件是唯一台账（`reference-ingest-state.json`）

结构与字段含义见 `docs/guide/reference-ingest-pipeline.md`。执行侧只需记住三条：

1. **写入口只有 `mark`**，别手工编辑 JSON（`scan` 会更新扫描游标，`mark` 写判定）；
2. **`skipped` 必须带 `--note`**：一句话理由，下一轮不再复核这篇（脚本强制，缺 note 直接报错退出）；
3. **同一克隆内串行**：`fetch`/`mark` 是 read-modify-write，与 `ingest-state.json` 同一纪律，别并发跑。

## 流程

### 0. 选源与**仓级判定**（先给整仓一个结论，再决定要不要扫）

整仓不纳入的仓（算子库/模板库、治理与竞赛、行业 SIG、agent 知识仓、框架适配仓）**不需要扫树**——扫大仓可能几分钟，而结论早由仓的类别确定。用仓级判定记账，下一轮不必再扫、也不必再判：

```bash
python3 scripts/gc_docs.py triage <repo> --decision rejected --note "算子库/模板库：文档以 API 参考与样例为主，非独立于事故的先验知识"
python3 scripts/gc_docs.py triage <repo> --decision candidate --note "文档面大或含工具/库文档，留待后续批次按价值排序评估"
python3 scripts/gc_docs.py triage <repo> --decision selected --note "已按价值优先级纳入并完成沉淀"
```

三种取值：`selected`（已纳入并沉淀）/ `candidate`（候选待评估，进下一轮选源池）/ `rejected`（不纳入，理由必填）。**仓级判定与文档级 `mark` 并存、互不覆盖**：仓级说"这个仓要不要看"，文档级说"这一篇沉不沉"。

### 0.1 选源排序（哪些仓值得吃）

判据是"仓里有没有面向问题定位的**文档**"，不是 star 数：

- 先看 `gc_docs.py repos`（组织全仓 + star + 描述）；
- 再看文档面结构：`scan <repo> --prefix docs/`（只拉目录树，成本≈0）；
- 高价值形态：分级故障诊断手册（`fault_diagnosis/`）、FAQ 集、错误码参考（`error_code_ref/`）、调优/精度方法页、profiling 采集与解读、`appendix/faq_failure_cases` 一类实战集合；
- 低价值形态（默认不碰）：API 参考面（逐接口罗列，无判据）、教程/训练营、竞赛与治理文书、算法/编程范式教程、源码与模板库。

**已确认的优先级**（前批已吃 `cann/cann-samples`）：`hccl`（通信故障诊断手册）→ `runtime`（FAQ + 错误码参考）→ `oam-tools`（asys 故障收集与解析）→ `docs`（CANN 公共文档仓，按判据摘取）→ cann-recipes-\* / asc-tools / ops-test-kit / shmem / cann-learning-hub。

### 1. scan：增量扫描（零模型成本）

> 只对 `selected`/`candidate` 的仓做这一步；`rejected` 的仓在第 0 步就结束了。

```bash
python3 scripts/gc_docs.py scan hccl --prefix docs/zh/user_guide/fault_diagnosis --top 40
python3 scripts/gc_docs.py scan runtime --json > /tmp/cand.json     # 供 fetch --from-scan
```

输出 `新增=N 变更=M 已定=K 未变待评=J` 与候选表。**新增与变更才是本轮工作量**——已定（harvested/skipped）与未变的不会再来烦你，这就是"防止重复抓取"的落地方式。

### 2. 筛候选（用路径，不用正文）

先按路径名把明显不值得沉淀的批掉并记账（一次 `mark` 可传多个路径）：

```bash
python3 scripts/gc_docs.py mark hccl --decision skipped \
  --note "索引/导航页，正文在子页（已由子页覆盖）" \
  --path "docs/zh/user_guide/fault_diagnosis/README.md,docs/zh/user_guide/fault_diagnosis/_dump_a.md"
```

判据：**这一页里有没有能当 grep 判据或处理动作的东西**。只有链接列表的伞页/索引页、只有日志 dump 的证据页、只有接口清单的 API 页 → skipped（理由写清，供人审回看）；带"现象/原因/解决"或"判据/阈值/命令"的页 → 进候选。

两类东西不该出现在候选表里，脚本已按默认规则排除（`AGENT_KB_DIRS` 与 basename 规则）：**各仓自带的 agent 知识目录**（`.claude/`、`.agents/`、`.codex/`、`.opencode/`——只作线索、不作权威源）与**构建/依赖清单**（`CMakeLists.txt`、`requirements*.txt`）。若某个仓确有例外（例如正文就写在某清单里），用该仓的 `config.exclude` / `config.exts` 单独放宽，不要改全局默认。

### 3. fetch：按需抓正文（含逐字节校验）

```bash
python3 scripts/gc_docs.py fetch hccl --from-scan /tmp/cand.json
```

正文落到**主检出**的 `ref-docs/<owner>/<repo>/<commit12>/<path>`（git-ignored，同一克隆所有 worktree 共读；已存在则复用，不重抓）。抓取时按 git blob sha 与目录树逐字节比对：上游改过、或路径返回了 HTML 页壳，当场报错而不是静默入库。

### 4. 抽取（token 纪律的执行点）

| 情形 | 做法 |
|---|---|
| 单篇 < ~30KB | 直接读，但**先剥日志码块**（下面的压缩手法） |
| 一个主题 30–150KB | 剥码块后拼成一个 bundle，一次读全（同批主题一起判定，避免反复回读） |
| 单篇超大（> ~150KB）或纯 API 参考 | 按标题跳读所需小节；只引用判据与命令，不整篇入上下文 |

剥码块的手法（日志 dump 占文档体积的一半以上，且本仓库本就要求日志裁剪）：

```bash
python3 - <<'EOF'
import re,glob
out=[]
for f in sorted(glob.glob('<缓存目录>/*.md')):
    t=open(f,encoding='utf-8').read()
    t=re.sub(r'```.*?```','[码块省略]',t,flags=re.S)
    out.append(f"\n===== FILE: {f} =====\n"+t.strip())
open('/tmp/bundle.md','w',encoding='utf-8').write(''.join(out))
EOF
```

**码块里的内容按需再取**：命令/阈值/枚举表只在需要写进词条时，针对那一篇单独 grep 出码块（`grep -n -A6 "<关键字>" <缓存文件>`），而不是把整篇码块读进来。

### 5. 产出词条（严格按 to-reference）

- 归类与写出规则全在 `skills/to-reference/SKILL.md`（本 skill 不重复）；产出前**先查已有词条**，能追加就不新建（append-don't-create），主题聚合走 `related_references`（relate-don't-merge）；
- `sources` 里 `official-doc.url` 用可点开的仓内路径（`https://gitcode.com/cann/<repo>/blob/master/<path>`；整面子面可用 `tree/` 目录 URL），`version` 写「仓 + commit 短 sha + 抓取日期」以钉住版本；`verification` 按是否逐字核验如实标；
- 本批次真正读过的每一篇都要在状态里留下 `refs`（哪条词条消费了它）——这是"来源可追溯"与"下一轮不重评"的同一条记录。

### 6. grill 与 mark

- `official-doc` 属弱 grill：不必逐条确认，但**批次范围与取舍要向用户交代一句**（吃了哪个子面、跳过了什么、为什么）；
- 产出后回写判定：

```bash
python3 scripts/gc_docs.py mark hccl --decision harvested --refs hccl-comm-init-and-link-faults \
  --path "docs/zh/user_guide/fault_diagnosis/link_timeout_EI0006.md,..."
```

### 7. 收尾（本批的固定动作）

```bash
python3 scripts/verify_references.py --check
python3 scripts/build_ref_summary_index.py && python3 scripts/build_procedure_index.py
python3 scripts/gc_docs.py status          # 台账核对：本批 harvested/skipped/pending 是否归零
```

PR body 里必须写清的：**吃了哪些源与子面、跳过了哪些、未提取的图（`figures/*.png` 一类）**、`verification` 口径、以及 token 成本量级。批次结束接 `/skill:evolve-check`（流程摩擦与 miss 是演进信号）。

## 批次节奏

**一批 = 一个主题**（通常 = 某仓的一个子面），走一次 PR：批太小则 PR 噪声大，批太大则人审不动。同一主题跨仓时按主题聚合产出，但**扫描与记账仍按仓**。批与批之间不必等确认（除非选题有歧义）；进度以"台账 + 一句选题"呈报给用户。
