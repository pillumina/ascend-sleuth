<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: Reference 知识变更（导入 / 转正 / 修订）
  about: 先验知识层（references/）的词条导入、转正或修订
  labels: []（按需 gh pr create --label）
PR body 正文从首个 "## " 区块开始。
  首屏一个视图的写法见 methodology.md 的「变更内容」一节；本模板的证据与合入风险由
  「来源与验证状态」与「高风险检查」两节承担。
-->

## 变更类型

- [ ] **导入**：to-reference 产出的新词条（`status: active` 直进正式 type 目录）→ 本 PR review 通过合入即生效
- [ ] **遗留 draft 转正**：历史 draft → active（修订 3 前产出；审核通过，无内容改动）
- [ ] **修订**：修改 active 词条内容（= 修改已生效知识 → **kb/high-risk 双签**，见下）

## 词条清单（机器可填）

| id | type | 内容 | 状态变更 |
|---|---|---|---|
| `ascend-xxx` | software-fact | 一句话摘要 | 导入（active，合入即生效） |
| ... | | | |

## 来源与验证状态

- 来源类型：`official-doc` / `engineer-input` / `case-derived`
- `verification`：`cross-checked-source`（说明核验范围）/ `auto-extracted`（reviewer 需 spot-check）
- 词条间 `related_references` 互链情况（关联不合并）

## Agent 预核意见（**由独立 agent 产出**；作者不得代填；低风险改动可留空）

<!-- 独立 = 新上下文的 agent，看不到作者的推理过程——作者自评漏掉的东西，正是这一段要抓的
     （实测：一次结构改动的作者自评漏了 1 条阻断级 + 2 条重要级问题，独立 agent 评出来了）。
     三档强度、产出格式与「为什么不做成 CI 门」见 docs/guide/git-workflow.md 的「评审把手」。
     没查出问题也要给覆盖清单——否则「没问题」与「没查」在 PR 上长得一样。
     不替代人审；高风险改动仍需双签。 -->

- 预核者（独立 agent 的 session / 模型；与作者上下文无关）：
- 事实依据（来源类型 / 引用数据 / 与现有词条的聚类比对）：
- 期望正确性（来源可信度：official-doc 高 / engineer-input 中 / case-derived 视案例数）：
- 风险标注（需 spot-check 项 / 修订场景的高风险点）：
- 覆盖清单（跑了哪些门 / 哪些命令 / 结果；没查出问题也照写）：
- 反例与可复跑命令（改了判定逻辑、生成器或门时必填；文档与内容类写「不适用」并说明为什么）：
- 结论（`MERGE_READY: yes/no` + 最关键的 1–2 条）：

## 聚类检查（机器可填）

- [ ] 去重：无现有词条完全覆盖本次内容
- [ ] 数据集类（error-code / fault-pattern / env-var-table）：族/域/模块归属正确，**追加不新建**（已有族则追加条目，不新建文件）
- [ ] `applies_to` 从来源结构化字段映射，未超出来源声明

## 完整性（机器校验）

- [ ] CI 绿：`verify_references.py --check`（id 唯一、schema 强校验、深审门槛——active 词条产出时即达标）
- [ ] 词条零注释行（`grep -c "#"` = 0）
- [ ] `status` 与生命周期规则一致（导入即 active；遗留 draft 转正除外）

## EV 卡（按准入范围判断，常规导入无需）

- 常规词条**导入**（新增词条、不改行为面）**不需要 EV 卡**——决策记录即本模板的上述区块。
- 属于以下四类之一才需附卡号：①从数据推断的归纳（case 归纳、扩 reference 家族）；②改行为面（triage 分支、skill 流程、闸门绑定、表族追加）；③修订已合入的 active 词条；④索引与口径类机制改动。
- 卡号（如适用）：

## 高风险检查（修订场景必填）

修订 active 词条内容 → 按知识修改规则 **kb/high-risk 双签**（methodology 模板 + 双 owner 签署）；仅导入（新词条即 active）与遗留 draft 转正不触发。小修（错别字/补一句）可直接改 YAML + 本 PR，大修用 `/skill:to-reference --update <ref-id>`。
