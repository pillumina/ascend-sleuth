<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: Reference 知识变更（导入 / 转正 / 修订）
  about: 先验知识层（references/）的词条导入、转正或修订
  labels: []（按需 gh pr create --label）
PR body 正文从首个 "## " 区块开始。
  首屏一个视图的写法见 methodology.md 的「变更内容」一节；本模板的证据与合入风险由
  「来源与验证状态」与「高风险检查」两节承担。
-->

## 背景与动机

<!-- 三行以内，一行一件事：哪条先验知识缺失或过期（谁在什么场景下找不到）→ 不补会怎样 → 补上之后问答哪一点不一样。 -->

- 触发：
- 不做的代价：
- 做完的变化：

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

<!-- 独立 = 与作者不同的会话（另起 session 或 subagent），不是外部第三方，别读成担保。
     三档强度、产出格式与为什么不做成 CI 门，见 docs/guide/git-workflow.md 的「独立预核」一节。
     这段只放 reviewer 判断要用的内容：结论、按严重度排的问题、查过什么。
     命令输出与逐条证据留在预核报告里，末行给链接即可，不复制进 body。 -->

- 结论（`MERGE_READY: yes/no`，加一句最要紧的理由）：
- 核对的版本（提交号或文件哈希；还没提交写「改动前」）：
- 来源可信度（official-doc 高 / engineer-input 中 / case-derived 视案例数）：
- 问题（逐条按严重度写：阻断级 / 重要级 / 建议级，每条一句话 + `文件:行`；没有写「无发现」）：
- 覆盖清单（查了哪些门与文件、跑了什么命令、结果如何；没查到的部分一并写明；没查出问题也要写）：
- 反例与可复跑命令（脚本与机制类填构造的反例、命令与实测结果；文档与内容类写「不适用」及原因）：
- 人读文本三项判定（可读性 / 逻辑性 / 黑话，各一行结论；没发现写「无发现」，没碰人读文本写「不适用」）：
- 预核报告（链接或 `文件:行`；没有写「无」）：

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
