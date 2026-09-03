---
name: to-postmortem
description: >
  把一次或多次昇腾问题定位沉淀成知识。输入支持内联粘贴、单个/多个文件路径、或整个目录（批量导入历史案例）。提取症状/命令/root_cause/fix，检测框架给命名空间建议（批量模式一次确认），人确认，输出结构化 YAML 草稿 + postmortem.md，过语义校验和脱敏。无论知识产自哪里（本地 agent session / Kimi 网页对话 / 手工笔记 / wiki 导出），都从这里汇入——这是异构知识来源的统一入口。
---

# To Postmortem

知识注入入口与诊断工具**解耦**——无论问题在哪儿定位的，都能在这里沉淀。这是 ascend-sleuth 体系里最重要的动作：不沉淀，团队下次还得重新踩坑。

## 输入方式

接受四种输入：

**1. 内联粘贴**（单条，最常用）：

```
/skill:to-postmortem "[把 Kimi/DeepSeek 对话、或手工排查笔记粘进来]"
```

**2. 单个文件路径**（大文档，免复制粘贴）：

```
/skill:to-postmortem ~/cases/custA/notes.md
```

agent 读取文件，后续流程同内联。

**3. 多个文件**（一次沉淀几条相关 case，各自独立成文）：

```
/skill:to-postmortem ~/cases/custA/notes.md ~/cases/custB/hang.md
```

**4. 目录**（批量导入历史案例，如内网 wiki 导出）：

```
/skill:to-postmortem ~/cases/wiki-export/
```

扫描目录下 `.md`/`.txt`，每个文件各成一条。大文件逐个处理，不全量载入 context。目录模式就是批量导入历史案例的入口——不需要单独的批量导入 skill。

## 流程

1. **提取**：从输入中抽出——
   - 症状、执行的命令和输出、排除的假设、root cause、fix
   - **级联噪声**：文档中标注了“次级现象”“不需要单独分析”“误导”的症状——提取为 case 的忽略项（diagnosis 里加一条“忽略 X 级联报错，都是根因后的 noise”）。昇腾调试里极常见——一个根因级联出几十条 secondary error
   - **code-patch 的 file:line**：如果 fix 涉及代码改动，提取精确的 file:line（如 `conn.py:31-41`）。code-patch 的 file:line = env-var fix 的 `export X=Y`——是 fix 的可执行部分
2. **命名空间建议**：agent 检测或推断框架，给选项，人输入数字确认（约 5 秒）：
   ```
   [1] training/mindspeed-llm/   （检测到 mindspeed-llm）
   [2] training/verl/            （检测到 verl）
   [3] common/                   （跨框架，或不确定）
   ```
   - 完全没涉及框架（纯硬件/CANN/驱动报错）→ 选项变为 `[1] common/`，人按回车
   - 检测到多个框架 → 按置信度排序，第一项标 `(most likely)`
   - 这个确认本身就是质量检查：人在 `mindspeed-llm` 和 `common` 间选，本质在自问“这问题是框架特有的还是通用的”
   - **批量模式**（多个文件/目录输入时）：命名空间确认改为一次批量——agent 按检测到的框架分组报告（如“12 个 mindspeed-llm、5 个 verl、3 个 common”），人一次确认或调整。语义校验仍逐个跑，失败的标 `needs-structurer-review`。批量模式不逐个 30 秒确认，改成抽审。
3. **输出结构化 YAML 草稿 + postmortem.md**：
   - **postmortem 策略**：源是混乱对话/手工笔记 → 写完整 postmortem.md（提炼+结构化）；**源已经是结构化文档**（调查报告/issue/wiki）→ postmortem.md 只写指针（`# 原文见：<source-url/path>`），不重写。YAML case 草稿两种情况都照常产出。
   - 标 `confidence: high | medium | low`——**人的调查质量判断**（五天详查 vs 随手记录），不是来源验证
   - 标 `verification: {source: <档>, detail: <引用>}`——**来源验证状态**（与 confidence 区分：confidence=内容判断质量，verification=外部证据强度）：
     - `upstream-fix-merged`：来源是上游 issue 且关联 fix PR 已合入（references 含 `pull/<n>` 或确认 merged）——内容被外部验证（根因+修复代码合入），最强档；
     - `upstream-maintainer-confirmed`：上游 issue 维护者确认 resolution 但无 fix PR 引用；
     - `investigation`：本地深度排查/源码分析定位（`source_ref` 佐证），无上游确认；
     - `engineer-report`：工程师现场回报验证过（最强现场证据，rare）。
     `detail` 记 issue/PR 号或来源路径。无明确外部验证 → 不填 verification（如实：仅调查级）
   - 标 `novelty: new_pattern | variant | covered`（**pre-triage，对比现有 case 判定**）：用 `knowledge/_index.yaml` 按 symptoms/tags 定位候选，全量读比对 root_cause/fix——无重叠 → `new_pattern`；同主题不同形态 → `variant`（注明 `variant_of:<case-id>`）；已有 case 覆盖 → `covered`（注明 `covered_by:<case-id>`）。**给出证据**（如"同算子×同网络，增量=升级修复"），groom 复核该标签而非重判
   - 标 `category: interrupt | precision | performance` **三选一，无 other**（按症状判断——interrupt 是 hang/crash/OOM/启动失败、precision 是 NaN/数值发散/输出错误/乱码、performance 是吞吐/延迟）。分不进去 → 由人确认归入最接近的分类，不设 other
   - 标 `tags`（sub-type，如 `oom`、`kv-cache`、`precision.convergence`）
   - 根因定位到源码时（如 vllm-ascend 某文件某行），标 `source_ref: {repo, ref, file, line}`——`ref` 用触发版本对应的 commit/tag，`line` 可选。源码不落库，只记代码指针（诊断按需取该版本片段）
3.5. **triage 路由同步（知识增长自动补全路由）**：产出 case 草稿后，检查该 case 的 `symptoms` 关键词能否被 `triage-tree.yaml` 正则路由到正确 namespace：
   - 能 → 无需动作（路由已覆盖）；
   - 不能（新形态 OOD，正则没识别）→ 在产出报告里给出**路由症状建议**（新正则追加到对应分支的 `symptoms`，如 "过度思考" → inference_precision），随 case PR 一并提交（structure 部分，人审确认）——**triage 随知识入库增长，不靠手工补**；拿不准放哪个分支 → 建议标 `needs-review`，groom 定夺。
4. **语义校验**（关键，区别于格式校验）：
   - regex 在输入附的真实日志片段上能否匹配
   - `expected` 值类型/数量级合理性
   - `command_template` 里的路径在已知部署模板里是否存在
   - 校验失败 → 标 `needs-structurer-review`（与 `needs-human-review` 区分：前者是格式/语义可疑，后者是语义不明）
5. **脱敏**：扫描 `Bearer ...`、`sk-...`、`password=`、内网 IP 段 → 替换 `[REDACTED]`。在人确认前，不是事后补救。这是 KB 进私有的第二道防线，第一道是 repo 可见性（见 README）
6. 人扫一眼确认 root cause 和 fix → done（30 秒内）

## 产出落点

- `postmortems/inbox/<case-id>.md`（postmortem 或指针）
- `postmortems/inbox/<case-id>.case.yaml`（YAML 草稿）
- inbox 是**待审队列**（见 `postmortems/inbox/README.md`）：每周 `/skill:knowledge-groom` 批处理三分类（new_pattern / variant_of / covered_by）后人审。审完：postmortem 转正 `../YYYY-QN/`（covered 也转正——Tier 3 语料，不是丢弃）、new 的草稿升格 `knowledge/<ns>/`

**生成后明确告诉用户存哪了**——报出具体路径（如 `postmortems/inbox/custA-ep-hang.md`）和 YAML 草稿位置，说明"周审后转正"，别让工程师去找自己的产出。

**回写来源 trace 的沉淀状态（诊断闭环）**：若本次沉淀来源是一个诊断 trace（输入提到 `traces/<session_id>.yaml`，或用户从诊断面板"沉淀此案例"触发），产出草稿落 inbox 后**回写该 trace 的 `sedimented.state: submitted`**（动作发生时写，零推断）——诊断面板据此显示"已提交沉淀待审"，不再重复提示沉淀。转正（`knowledge`/`archived`）由用户在面板/对话确认时更新，本 skill 不写。

## 收尾 evolve-check（伴随演进评估，默认执行）

**先落执行记录**（evolve-check 读它作现场）：
`python3 scripts/log_skill_exec.py --skill to-postmortem --products "<case-id>(submitted),..." --reason "<一句话根因/来源>" --source <来源 skill> --tokens <估算>`

草稿产出、出最终报告前，执行一次伴随演进评估（`read skills/evolve-check/SKILL.md`
遵循）：本轮沉淀 ≥3 条同根因/同族 case（T1 → 归纳 reference 候选）、replay/Tier 3
暴露覆盖缺口（T2）、或提取/校验环节有重复手动动作与流程摩擦（T3/T4）时，**agent
自动产 idea 卡并自行验证执行**（ev_proposal 产卡 → golden/S2 验证 → 进攒批）；无
信号则报告加一行"evolve-check：无演进信号"。这是流程默认收尾，**不需要用户另说
"改进系统"**——演进由数据触发，像人学习。产出与流程报告一并给出。

## 为什么是这个体系的核心

团队不能统一 agent 时，知识注入入口必须与诊断工具解耦。`/to-postmortem` 是这个解耦的实现——任何工具的对话都能沉淀。别期望团队成员额外写文档，agent 提取、人审批，成本从 20 分钟降到 30 秒。
