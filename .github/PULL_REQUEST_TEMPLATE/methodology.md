<!-- 模板元数据（GitHub 不解析 PR 模板 frontmatter，置于注释内避免正文渲染成粗体块）：
  name: 方法论变更（skill / scripts / docs / eval）
  about: 修改 skills/、scripts/、docs/、eval/ 等框架本身
  labels: []（按需 gh pr create --label）
PR body 正文从首个 "## " 区块开始。
-->

## 变更内容

<!-- 首屏放一个视图：目录树 / diff sketch / 调用链 / mermaid 任选，只留回答"改了什么"所需的信息。
     视图下面最多三行文字，一行说一件事。论证留给 EV 卡的 decisions，细节留给 trace / postmortem，
     这里不复述已有承载处。 -->

（此处放一个视图：目录树 / diff sketch / 调用链 / mermaid）

- 对象：SKILL.md / 脚本 / 文档 / fixture
- 动机：

## 证据（改前 → 改后，成对给；一条改动一行）

<!-- 贴真实输出，不转述成"已验证"。可复现判据直接粘 `python3 scripts/ev_measure.py <卡号> --run` 的输出。
     没有对照的改动写「无对照：<原因>」，不静默省略。面板 / 文档类改动可附截图。 -->

- `<命令>`：改前 `<输出>` → 改后 `<输出>`

## 原则追溯（原则文件的元规则：不可追溯的变更是可疑的）

- 本变更服务哪条设计原则：
- 是否修改了原则/理论本身的语义：否 / 是（需先走 ADR）

## 回归检查（改 skill 本身必做，docs/guide/eval.md）

- [ ] 改动前跑了 golden 套件，基线：N 条通过
- [ ] 改动后重跑，原通过项无一变为失败
- [ ] **若改动了 `eval/golden/**` 或它指向的 case**：按「更新 fixture 头注 → `python3 scripts/eval_scorecard.py --build` → 账本随夹具同 PR 提交」记账；自查跑 `--check`（CI `eval-scorecard` 会验夹具哈希，夹具改了不重建账本即红）
- [ ] **本改动对应的 EV 卡带可复现判据**（`predicted_effect.measure`：命令 + 期望，或如实声明不可度量）——reviewer 用 `python3 scripts/ev_measure.py <card-id> --run` 机械复核，不必开全文
- [ ] **若触及输出契约 / 交互形态**（输出模板、结论呈现、追问链形态）：附**盲辨对照**（同问题新旧输出各一份、去掉来源、交不知情者判"哪份更清楚 / 更不像模板"），或说明为何不需要——此类改动的成败是主观的，无对照无法排除"只是换了措辞"；强度为**约定**，由 reviewer 核
- [ ] **若改动交接包链路**（`scripts/export_trace.py` / `import_trace.py` / `docs/guide/handoff.md`）：
      `python3 scripts/check_handoff.py` 末行「全部通过」。该检查**不进 CI**（新检查尚无复发记录，
      准入判据见 `CLAUDE.md`），所以在这一步自查
- 对照结论见上节「证据」（此处只写完整报告的位置）：

## 人读性自查（约定，非 CI——docs/guide/git-workflow.md「人读性与代号约定」）

- [ ] 本 PR 的 prose 符合 `docs/spec/writing-norms.md`（共用条目 + §3 的「PR body」定制条款）
- [ ] 人读 prose（描述/变更说明/摘要）中代号首次出现已解码（含义〔代号〕），无高危字母裸用（E/T/G/EV/Phase 系列）
- [ ] **记账号未越界**——roadmap 事项（A/E/M/O/P）、治理缺口（G）、触发信号（T）、落地阶段（Phase）只在各自的计划文档里裸用；本 PR 的 prose 要引用就写中文含义（可跑 `scripts/render_review_summary.py --scan <改动文件>` 自检）
- [ ] **本 PR 新增或改名的机制 / 脚本 / 数据文件逐个列出**（无则写"无"）——每个新名字都是读者的长期成本，列出来才看得见；能不加名字就不加
- [ ] 新增/新引用的代号已登记 docs/glossary.yaml（含 `scope` 字段）
- [ ] PR 描述提供解码审读视图（`--diff` 渲染表，或等价解码摘要——人读 prose，代号已逐次解码），reviewer 无需裸读满屏代号

## Agent 预核意见（**由独立 agent 产出**；作者不得代填；低风险改动可留空）

<!-- 独立 = 新上下文的 agent，看不到作者的推理过程——作者自评漏掉的东西，正是这一段要抓的
     （实测：一次结构改动的作者自评漏了 1 条阻断级 + 2 条重要级问题，独立 agent 评出来了）。
     三档强度、产出格式与「为什么不做成 CI 门」见 docs/guide/git-workflow.md 的「评审把手」。
     没查出问题也要给覆盖清单——否则「没问题」与「没查」在 PR 上长得一样。
     不替代人审；高风险改动仍需双签。 -->

- 预核者（独立 agent 的 session / 模型；与作者上下文无关）：
- 事实依据（golden 回放对照 / trace 回归结果）：
- 行为差异（改动前后的路由/命中差异摘要）：
- 文档类改动另查：`docs/spec/writing-norms.md` §1 的共用条目逐条对照（报命中项 + 行号）；
  文中每个可验证声明（路径 / 命令 / 字段名 / 代号）逐个核对与实现是否一致：
- 覆盖清单（跑了哪些门 / 哪些命令 / 结果；没查出问题也照写）：
- 反例与可复跑命令（改了判定逻辑、生成器或门时必填；文档与内容类写「不适用」并说明为什么）：
- 结论（`MERGE_READY: yes/no` + 最关键的 1–2 条）：

## 影响面与合入风险

- 涉及的 skill / 流程步骤：
- 对 CLAUDE.md / README / CONTEXT.md 术语表的同步：已检查 / 不涉及
- 回退：可逐卡 revert / 不可回退（`decisions` 已追加、审计档案已改）/ 需 reseal（封存对照集）
- 生效时点：合入即生效 / 下次 groom / 下次周批
- 读数变化：无 / 有（列出哪条判据、改判原因）
