# 演示讲稿：Ascend-Sleuth 完整目标态演示

约 20 分钟的连贯演示，从第一次接触项目的人视角，走完全部环节。可现场操作，也可回放。每幕标注**讲什么**（口语脚本）、**展示什么**（操作/素材）、**互动点**。

开场一句话：**这是一个会自我变准的诊断知识库。知识从每次问题定位中沉淀，经预分诊和机器门控入库，下次同类问题直接命中。今天我们从零走一遍这条闭环。**

---

## 开场：全景可视化（约 2 分钟）

**展示**：打开 `docs/diagrams/ascend-sleuth-architecture.html`（浏览器，light 主题）。

**互动**：
- 右上角 Light/Dark 切换、搜索框（搜"triage"看聚焦）、点击节点看关系追踪、聚焦视图
- 指出两个循环：诊断循环（上排，每次问题）与演化循环（下排，每周 git 门控）
- 指出 2.5 层（references）：错误码/故障模式/方法论，诊断的"先验辅助"

**讲**：这张图就是系统的全部。上面是诊断，下面是演化，中间靠沉淀和转正连接。接下来的每一幕都会回到这张图。

---

## 第一幕：为什么需要（约 2 分钟）

**讲**：昇腾支持工程师每天面对三类问题：训练/推理中断、精度异常、性能退化。根因高度重复，但知识散在个人笔记、IM、wiki 里。新 case 每周出现，平台差异（A2/A3/A5）还在扩大，靠个人手工维护撑不过几周。

**展示**：`knowledge/inference/vllm-ascend/interrupt/` 的 30+ 条 case——"同一个错误码 507xxx，反复出现，现在有结论了"。

**互动点**：问听众"你们遇到过 507015 或 MoeDistributeDispatch 报错吗"——命中他们的真实痛点。

---

## 第二幕：上手（约 3 分钟，可现场操作）

**展示**（现场）：
1. `git clone` 本仓 → 看 `.dsh/skills` 已跟踪（`ls -la .dsh/skills`）
2. 在仓库目录打开 DSH → `/skill:` 列表出现 6 个 skill（演示热刷新：改一个 SKILL.md 的 description → 列表即时更新）
3. 其他 agent：跑 `bash scripts/enable-agent-skills.sh`（为已装的 Claude Code/Cursor 等建 symlink）
4. 架构图交互版再点一下（呼应开场）

**讲**：仓库即 workspace。clone 即用（DSH 零配置），git pull 全员同步，热刷新即时生效。不需要装任何东西。

**互动点**：让听众现场跑一次 `enable-agent-skills.sh`，看自己装了哪个 agent 就被自动配置。

---

## 第三幕：一次真实诊断（约 5 分钟，核心）

**场景**（真实）：vllm-ascend issue #12723（首次真实诊断演示的输入）或一个新 issue。

**展示**（现场 `/skill:diagnose`）：
1. 输入症状（框架/平台/报错栈尾）
2. **Tier 1**：triage-tree 路由到 namespace（展示 `triage-tree.yaml` 命中分支）
3. **Tier 2**：读 `_index.yaml` 过滤候选（展示候选列表 + confidence）
4. **2.5 reference 加载**：报错里的错误码 → `references/errors/` 族表 grep 命中（展示 meaning/solution）——强调"先验层只读 active、按签名检索"
5. **验证**：diagnosis checks 对照客户信息 → severity 闸门 → fix 输出（展示 fix 是建议，人应用）
6. **trace**：`diagnosis_state-*.yaml` 落盘（展示每一步记录）

**互动点**：让听众提供他们手上的一个真实症状，现场走一遍（若未命中 → 演示 Tier 3 fallback + 诚实退化路径）。

---

## 第四幕：沉淀（约 3 分钟）

**展示**（三种入口，选一两个现场演示）：
1. `/skill:to-postmortem`：粘贴一段调查笔记 → 提取症状/根因/fix → draft 进 `postmortems/inbox/`（展示草稿 + pre-triage 标签）
2. `/skill:to-reference`：官方文档片段 → 词条 draft 进 `references/`（展示零注释、verification 声明）
3. `/skill:issue-ingest`（回放或现场）：`--repo vllm-project/vllm-ascend --labels triaged` → 拉取/过滤/候选 → 评估沉淀（展示幂等：ingest-state 的 processed/config）

**讲**：任何来源都能汇入。agent 自动提取 + 预分诊标签，人的成本压缩到审稿。

---

## 第五幕：groom + 门控（约 3 分钟）

**展示**：
1. `postmortems/inbox/` 待审队列（现场若为空，用历史案例演示）
2. **预分诊三分类**：new / variant / covered + 证据（展示真实实例：`VLLM-ASC-9503` 被预分诊为 `variant_of 12461`——同算子×同网络，并入）
3. **PR 门控**：reference 模板/knowledge_intake 模板（展示 #48 的真实 PR）→ kb-checks CI（index-freshness / reference-validation / skill-self-contained）
4. **高风险双签**：改 active case 的 compat/fix → kb/high-risk 标注（展示 #45 的 12461 并入实例）

**互动点**：给听众一个真实 draft，现场预分诊——让他们自己判 new/variant/covered，对照 agent 的建议。

---

## 第六幕：知识演化与观测（约 3 分钟）

**展示**：
1. **case → reference 提炼**：groom R8 的"同 tag case ≥3 → 建议 `--ingest-cases`"信号（展示 MoE 通信算子族 4 条 case → `ascend-moe-comm-triage` methodology）
2. **错误码补表**：507015 追加进 cann-runtime 族表（追加不新建）
3. **观测回写**：groom R6 的 reference hits / trace_metrics 输出（展示 metrics 口径——无数据如实显示 0）
4. **架构图回到全景**：指出今天走的每一环在图上哪里

**互动点**：问听众"哪个环节你希望下周就能用上"——把演示落到他们的实际需求。

---

## 收尾（约 1 分钟）

**讲**：从一次诊断到知识沉淀，到预分诊、门控、转正，再到提炼成方法论——每个环节今天都走到了。这套系统交付的是机制 + 持续变厚的知识。第一个团队的诊断会触发诚实退化路径（空库提示、Tier 3 兜底）——那是设计预期，每次兜底后沉淀，知识库随使用变厚。

**展示**：交互架构图全景收尾。

---

## 演示素材清单（全部真实，可复用）

| 素材 | 位置 |
|---|---|
| 交互架构图 | `docs/diagrams/ascend-sleuth-architecture.html`（light）|
| 真实诊断输入 | vllm-ascend #12723（或现场听众提供）|
| 实例 PR（含预分诊/双签/CI）| #45（12461 并入）、#47、#48 |
| case 族示例 | `knowledge/inference/vllm-ascend/interrupt/`（42 条）|
| reference 示例 | `references/errors/`（族表）、`references/methodologies/` |
| agent 使能 | `scripts/enable-agent-skills.sh` |
| 管道状态 | `ingest-state.json`（processed/config/游标）|

## 演示前检查

- [ ] clone 到干净目录，`/skill:` 列表 6 个 skill 可见
- [ ] 交互架构图在本机浏览器可打开（file:// 即可）
- [ ] 准备 1-2 个真实症状输入（第三幕用）
- [ ] `postmortems/inbox/` 至少有一条可预分诊的 draft（或演示时现场产生）
- [ ] gh CLI 已登录（issue-ingest 实演用）
