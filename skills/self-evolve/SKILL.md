---
name: self-evolve
description: >
  自演进执行引擎（第一批落地）。跑一轮"系统改进自己"的闭环：观测真实信号 →
  产候选 idea 卡 → 校验 → 攒批 → 聚合 PR 给人审。把已落地的确定性工具链
  （verify_proposals.py / component_tally.py / s2_calibration.py /
  replay_golden.py + proposals/ideas 卡体系）串成一轮可重复执行的会话。
  触发语义同 knowledge-groom（disable-model-invocation，人显式触发，防自发
  批量改库）。机制设计见 docs/evolution-pipeline.md（可选论证层）；本文件
  自包含执行参数。
disable-model-invocation: true
---

# Self-Evolve

> **本地执行说明**：本 skill 标记 `disable-model-invocation`（防 agent 自发启动批量改库/批量自演进）——skill 工具加载会报 "not available for model invocation"，这是预期。用户明确要求跑一轮自演进时，agent 直接 `read` 本文件手动遵循流程即可；或用户输入 `/skill:self-evolve` 直接触发。

让系统改进自己：诊断系统的运行数据 → 带轨迹依据的改进 idea → 验证 → 人审合入。一轮 = 一次有状态会话（有停止条件、可 resume、出报告）。

## 触发

手动运行。用户说"跑一轮自演进""看看有什么可改进的""持续改进 X"时触发。产出**候选 idea 卡 + 聚合 PR** 交人审，不自动合入结构级改动。

## 运行模式（先对齐，不猜）

执行前与用户确认介入度（一句话即可）：

- **全自动（hands-off）**：改到目标完成，一次性聚合 PR 给人审；每个改动有记录 + 验证 + 独立 commit
- **关键人审（default）**：自动跑，关键改动攒到轮末一个 PR 给人审

用户没说 → 默认 hands-off（设计默认）。若用户表达含糊（范围/目标不清）→ 先澄清再执行，不边跑边猜。

## 一轮流程

### 0. 装载上下文（观测）
读聚合（不读 case 全文——token 预算）：
- `knowledge/_index.yaml` 头注 → 容量信号（超 soft_cap 的格子）
- `python3 scripts/component_tally.py` → 组件失败台账（mis 侧；无数据如实跳过）
- `metrics/timeline.yaml` → 指标趋势
- `proposals/ideas/` 现有卡（避免重复/冲突，§5.2 冲突检测）
产出本轮的信号清单（每个信号带出处，无数据不产候选——诚实退化）。

### 0.5 自动采集与测试（全自动 evolving 的数据摄入环节）
让系统自己找新数据并测试，不等人喂。按序执行：
1. **自动拉取上游 issue**：`python3 scripts/auto_fetch.py`——增量拉全部已配源的新
   closed issue（读 ingest-state 游标，排除已处理，更新游标）；候选在
   `.auto-fetch/`。
2. **扩 S2 校准集**：`python3 scripts/s2_calibration.py --repo <slug> --output
   eval/s2/<slug>.yaml --incremental`——只补真新增（跳过已收录 + 排除
   not_planned）。
3. **自动 replay 测试**：`python3 scripts/s2_replay.py --prepare`（产输入）→
   `--todo`（列待测）→ **对每条 high/medium 置信条目按 diagnose 流程诊断**，
   结论写 `.s2-replay/<issue>.result.yaml` → `--collect`（对照评分）。
   **测试的意义**：用已闭环 issue（resolution 已知）验证诊断系统"从现象能否
   定位根因"——命中 = 检索/根因正确；miss = 覆盖缺口（进候选）。
4. **官方文档源**：有新增/变更的文档类别时 `python3 scripts/fetch_docs.py
   --fetch-all`（清单 config/doc-sources.yaml）→ 草稿供 to-reference 提炼。
   动态页正文提取用 agent-browser 渲染（curl 只取到导航框架时）。
5. **观测结果并入信号清单**：把 replay 的 miss 项、容量、台账信号汇总为
   本轮候选依据（step 0 的信号清单 + 本节采集结果一起驱动产卡）。

### 1. 产候选 idea 卡
信号 → 卡（每卡一个文件 `proposals/ideas/EV-<YYYY>-<NNN>.yaml`）：
- **先 `python3 scripts/ev_proposal.py --list`** 看现有卡（查重/冲突，§5.2 纪律）
- **`python3 scripts/ev_proposal.py --new`** 生成新卡骨架（自动分配下一个
  EV 卡号 + 复制模板）——不要手动数卡号/手写 YAML（格式易错）
- 骨架按 `examples/sample-idea.yaml` 填：layer / title / status=candidate /
  authorization / dimension / source_signals（带 trajectory 出处）/
  hypothesis / predicted_effect / validation / risk / principle_refs /
  decisions
- **只产建议与证据，不自行合入**（原则五）

### 2. 校验
`python3 scripts/verify_proposals.py` —— 卡必须过 schema 校验（状态词表/
枚举/交叉引用）。校验失败 → 修卡，不跳过。

### 3. 攒批与聚合 PR
- 本轮多张卡（或单卡）改动攒到批边界（一轮结束 / 攒够 10 张 / 用户要求
  任务级攒批到目标完成）
- 每卡独立 commit（可逐卡 revert）；聚合 PR body 按卡列 EV id + 验证结果
  + 授权级别，dual 卡标 kb/high-risk
- PR 模板按批内最高风险选（structure/methodology/knowledge_modification）
- 人审 PR 后合入；打回的卡 revert 其 commit，其余照常

### 4. 报告
本轮产出汇总：产了几张卡、各卡状态、验证依据、成本（token）、下一步建议。
报告落 `proposals/reviews/`（运行时，gitignore）。

## 验证先于合入（不把验证推迟到合入后）

- **即时判定类**（检索/路由/skill 流程）：eval 在合入前完成（S2 replay /
  golden）——用 `scripts/s2_calibration.py` 建的校准集或 `eval/golden` 回放，
  通过才进批。PR 呈现的是已验证改动。
- **真实反馈类**（content/fix）：合入前完成实现 + S2 佐证，合入后观察窗等
  真实场景（由 diagnose 使用 + 反馈结算）——如实标注"已实现待真实确认"，
  不冒充已验证。

## 停止条件（任一满足即停，出报告）

- 预算耗尽（本轮 token 上限，与用户对齐时确认）
- 产出达标（validated/候选达 N 张，默认 3）
- 无新信号（信号清单为空或全 rejected）
- 人中断

## 边界（不做）

- 指标口径只有人能改（agent 不自改评分定义）
- 不碰客户现场（不执行生产变更）
- 蓝图态（超时降级 unconfirmed/stale/策略记忆/稳态降频）未实现——触发
  条件出现才启用（见 docs/evolution-pipeline.md §11.1，可选论证层）

## 依赖的工具链（均已落地）

| 工具 | 用途 |
|---|---|
| `scripts/ev_proposal.py` | 产卡辅助：新卡号分配 / 卡骨架生成 / 现有卡概览（步骤 1 必用） |
| `scripts/verify_proposals.py` | idea 卡 schema 校验（每轮必跑） |
| `scripts/auto_fetch.py` | 自动增量拉取上游 issue（步骤 0.5：数据摄入） |
| `scripts/s2_calibration.py` | 构建 S2 issue-replay 校准集（--incremental 只补新增） |
| `scripts/s2_replay.py` | S2 replay 记录/对照评分/待测清单（--todo，步骤 0.5 测试） |
| `scripts/fetch_docs.py` | 官方文档源抓取（config/doc-sources.yaml，动态页用 agent-browser） |
| `scripts/component_tally.py` | 组件失败台账（观测信号源） |
| `scripts/replay_golden.py` | golden 套件 replay 编排（M2 雏形，即时判定类验证） |
| `proposals/ideas/` | 卡资产（入 git，随 PR 进出） |
