<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 方法论变更（skill / scripts / docs / eval）
  about: 修改 skills/、scripts/、docs/、eval/ 等框架本身
  labels: []（按需 gh pr create --label）
PR body 正文从首个 "## " 区块开始。
-->

## 变更内容

- 对象：SKILL.md / 脚本 / 文档 / fixture
- 动机：

## 原则追溯（原则文件的元规则：不可追溯的变更是可疑的）

- 本变更服务哪条设计原则：
- 是否修改了原则/理论本身的语义：否 / 是（需先走 ADR）

## 回归检查（改 skill 本身必做，docs/eval.md）

- [ ] 改动前跑了 golden 套件，基线：N 条通过
- [ ] 改动后重跑，原通过项无一变为失败
- [ ] **本改动对应的 EV 卡带可复现判据**（`predicted_effect.measure`：命令 + 期望，或如实声明不可度量）——reviewer 用 `python3 scripts/ev_measure.py <card-id> --run` 机械复核，不必开全文
- [ ] **若触及输出契约 / 交互形态**（输出模板、结论呈现、追问链形态）：附**盲辨对照**（同问题新旧输出各一份、去掉来源、交不知情者判"哪份更清楚 / 更不像模板"），或说明为何不需要——此类改动的成败是主观的，无对照无法排除"只是换了措辞"；强度为**约定**，由 reviewer 核
- 改前/改后对照（摘要或附完整报告）：

## 人读性自查（约定，非 CI——docs/git-workflow.md「人读性与代号约定」）

- [ ] 人读 prose（描述/变更说明/摘要）中代号首次出现已解码（含义〔代号〕），无高危字母裸用（E/T/G/EV/Phase 系列）
- [ ] **记账号未越界**——roadmap 事项（A/E/M/O/P）、治理缺口（G）、触发信号（T）、落地阶段（Phase）只在各自的计划文档里裸用；本 PR 的 prose 要引用就写中文含义（可跑 `scripts/render_review_summary.py --scan <改动文件>` 自检）
- [ ] **本 PR 新增或改名的机制 / 脚本 / 数据文件逐个列出**（无则写"无"）——每个新名字都是读者的长期成本，列出来才看得见；能不加名字就不加
- [ ] 新增/新引用的代号已登记 docs/glossary.yaml（含 `scope` 字段）
- [ ] PR 描述提供解码审读视图（`--diff` 渲染表，或等价解码摘要——人读 prose，代号已逐次解码），reviewer 无需裸读满屏代号

## Agent 预核意见（机器可填，可选——非 agent 链路提交可留空）

<!-- 基于事实的独立意见，供 reviewer 对齐判断——不替代人审 -->

- 事实依据（golden 回放对照 / trace 回归结果）：
- 行为差异（改动前后的路由/命中差异摘要）：
- 风险标注（涉及流程步骤 / 需 spot-check 项）：

## 影响面

- 涉及的 skill / 流程步骤：
- 对 CLAUDE.md / README / CONTEXT.md 术语表的同步：已检查 / 不涉及
