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

**4. 目录**（批量导入历史案例，如从团队 wiki 导出的记录）：

```
/skill:to-postmortem ~/cases/wiki-export/
```

扫描目录下 `.md`/`.txt`，每个文件各成一条。大文件逐个处理，不全量载入 context。目录模式就是批量导入历史案例的入口——不需要单独的批量导入 skill。

**二进制文档（`.docx`/`.doc`/`.pptx`/`.xlsx`/`.rtf`/`.epub`）预处理**：客户报告、排查记录、汇报材料常是这些格式，先取到文本再走上面四种输入。**约束是不变量，不是工具**——只要满足三条：①文本取自原文件（不凭标题或上下文编造）②出处可核验 ③材料不外传（客户/内部文档不上传第三方服务）。工具怎么选、能不能装，都是这三条之下的实现细节。

省事的首选（装得上就用，装不上别卡死）：

```bash
npx -y @firecrawl/anydoc <file> -o <file>.md     # Node ≥ 20，首次自动下载，保留表格/公式/脚注
# 无 Node 但有 Python ≥ 3.10：
pip install firecrawl-anydoc
python -c "import anydoc,sys; print(anydoc.to_markdown(sys.argv[1]))" <file>
```

**anydoc 或任何库都装不上（离线、无 Node/Python、版本冲突）→ 先自己找路，不要直接判失败。** 已知可行的零依赖路线（这些格式本质都是 zip + XML）：

- `.docx`：`python -m zipfile -e <file> out/`（Windows 无 Python 时用 `[System.IO.Compression.ZipFile]::ExtractToDirectory`）后读 `out/word/document.xml`，按 `<w:p>` 段落取 `<w:t>` 文本拼回；`out/word/media/` 是内嵌图片。
- `.pptx`：`ppt/slides/slide*.xml`（备注在 `ppt/notesSlides/`）；`.xlsx`：`xl/sharedStrings.xml` + `xl/worksheets/sheet*.xml`；`.odt`/`.ods`/`.odp`：`content.xml`。
- 这条路拿到的文本通常够沉淀（case 要的是症状/命令/根因，不是版式）；**丢掉的表格结构/排版如实记进 postmortem**，别假装完整。
- 探索出的新路线跑通了，值得固化 → 收尾的伴随演进评估会看到"重复手动动作"信号并决定是否写成步骤（见 `/skill:evolve-check`），**不要在这里自己加卡**。
- 真的都抽不出来 → **明确告诉用户"这份文件抽不出来，请转成 md 或贴文本"，不静默跳过附件**——附件里的报错原文正是 case 的 symptoms 证据。
- **目录模式**的扫描范围随之扩展到上述扩展名，逐份取到文本后再成条。
- **截图**：纯文本通道（anydoc 或 XML 提取）都只出文字，文档里的定位截图会被丢掉（anydoc 无占位、无告警）。`.docx`/`.pptx`/`.xlsx`/`.odt` 都是 zip，用 `python -m zipfile -e <file> out/` 取 `word/media/`（pptx 为 `ppt/media/`，xlsx 为 `xl/media/`），再用**自己的图片识别能力直接读图**（模型支持图片输入时）。
- **读不了图就如实记缺口**：在 postmortem 里列「未提取的证据」清单（文件名 + 所在段落上下文 + 未识别原因），草稿标 `needs-human-review`。**不要拿截图的标题或上下文推测报错原文**——`symptoms` 只写文本里确有的内容。
- **不外传**：不要用 `--ocr hosted`（把整份文档上传第三方服务）；客户材料一律本地处理。

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
   - 标 `verification: {source: <档>, detail: <引用>}`——**这一档决定草稿能不能升格**：自诊断的问题（带 `source_session`）**默认要等来源 trace 的 `feedback.outcome: resolved`** 才会被 groom 升格；没闭环就该如实标 `investigation`，并知道它会被闸门拦下（除非补强外部证据并走 owner 双签）。别为了让草稿过关而抬高档位——档位是外部证据强度，不是主观评价——**来源验证状态**（与 confidence 区分：confidence=内容判断质量，verification=外部证据强度）。**档位按「来源形态」分，不按 issue 分**——issue 只是外部来源之一，官方案例文档与本地闭环同样是来源：
     - `upstream-fix-merged`：来源是上游 issue 且关联 fix PR 已合入（references 含 `pull/<n>` 或确认 merged）——内容被外部验证（根因+修复代码合入），最强档；
     - `upstream-official-doc`：来源是**上游官方发布的案例/指南文档**（如框架仓库 `best_practices/` 下的定位实践、官方 troubleshooting 指南），含完整定位链与验证结论——内容被上游发布验证，但无指向本问题的 fix PR；
     - `upstream-maintainer-confirmed`：上游 issue 维护者确认 resolution 但无 fix PR 引用；
     - `investigation`：本地深度排查/源码分析定位（`source_ref` 佐证），无上游确认；
     - `engineer-report`：工程师现场回报验证过（最强现场证据，rare）。
     `detail` 记 issue/PR 号、文档路径或来源路径。无明确外部验证 → 不填 verification（如实：仅调查级）
   - 标 `novelty: new_pattern | variant | covered`（**pre-triage，对比现有 case 判定**）：用**命中 (namespace × category) 的索引分片** `knowledge/_index/<ns>__<category>.yaml`（category 未定回退 `<ns>.yaml`；已知 namespace 时不读全库总表）按 symptoms/tags 定位候选，再全量读候选 case 本体比对 root_cause/fix——无重叠 → `new_pattern`；同主题不同形态 → `variant`（注明 `variant_of:<case-id>`）；已有 case 覆盖 → `covered`（注明 `covered_by:<case-id>`）。**给出证据**（如"同算子×同网络，增量=升级修复"），groom 复核该标签而非重判
   - 标 `category: interrupt | precision | performance` **三选一，无 other**（按症状判断——interrupt 是 hang/crash/OOM/启动失败、precision 是 NaN/数值发散/输出错误/乱码、performance 是吞吐/延迟）。分不进去 → 由人确认归入最接近的分类，不设 other
   - 标 `tags`（sub-type，如 `oom`、`kv-cache`、`precision.convergence`）
   - 根因定位到源码时（如 vllm-ascend 某文件某行），标 `source_ref: {repo, ref, file, line}`——`ref` 用触发版本对应的 commit/tag，`line` 可选。源码不落库，只记代码指针（诊断按需取该版本片段）
   - **来源是诊断 session 时，标 `source_session: <session_id>`**（case 内字段，非注释）——它是反馈结算判定「自证」的唯一依据：来源 session 自己回报的 resolve 记 `confidence.self_resolved`、不计入 `hits`（同一份证据不数两次）。不写这个字段，结算只能退回「计入 hits」，等于让产地自证冒充独立命中。
3.5. **triage 路由同步（知识增长自动补全路由）**：产出 case 草稿后，检查该 case 的 `symptoms` 关键词能否被路由正则（`triage-tree.yaml`，生成物）路由到正确 namespace。**加词改的是源**：`triage-tree.d/<族>.yaml`（一族一文件，如 `40-inference-interrupt.yaml`），改完跑 `python3 scripts/build_triage_tree.py`——聚合的 `triage-tree.yaml` 不进 PR，不要提交它（CI 有门拦；合并后由合并者重建）：
   - 能 → 无需动作（路由已覆盖）；
   - 不能（新形态 OOD，正则没识别）→ 在产出报告里给出**路由症状建议**（新正则追加到对应**族文件**里该分支的 `symptoms`，如 "过度思考" → `50-inference-precision.yaml`），随 case PR 一并提交（structure 部分，人审确认）——**triage 随知识入库增长，不靠手工补**；拿不准放哪个分支 → 建议标 `needs-review`，groom 定夺。同一族两人同一天加词不会冲突（该目录配了 union 合并，两边都留住）。
4. **语义校验**（关键，区别于格式校验）：
   - **先跑结构校验的确定性工具**：`python3 scripts/verify_case_draft.py <草稿路径>`——它管机械可判的那一半（YAML 可解析、必需字段非空、`category`/`severity`/`fix_type` 取值合法、`ref_knowledge` 不悬挂且指向 active 词条、`quickly_check.expected` 的 regex 可编译且无空分支、`diagnosis` 无空步）。草稿在 inbox 期间没有任何门（CI 的 `build_index` 只在 case 进 `knowledge/` 后才解析它），所以这一步是它唯一的确定性检查点；也支持 `--all` 校全库。
   - regex 在输入附的真实日志片段上能否匹配
   - `expected` 值类型/数量级合理性
   - `command_template` 里的路径在已知部署模板里是否存在
   - 校验失败 → 标 `needs-structurer-review`（与 `needs-human-review` 区分：前者是格式/语义可疑，后者是语义不明）
5. **脱敏**：扫描 `Bearer ...`、`sk-...`、`password=`、内网 IP 段 → 替换 `[REDACTED]`。在人确认前，不是事后补救。这是 KB 进私有的第二道防线，第一道是 repo 可见性（见 README）
6. 人扫一眼确认 root cause 和 fix → done（30 秒内）

## 产出落点

**草稿落在哪个 inbox**：先 `python3 scripts/shared_dir.py inbox` 取绝对路径（锚在**主检出**、跨 worktree 共写；写相对 `postmortems/inbox/` 的草稿，转正时在 worktree 里读不到、清 worktree 就丢）。下面是相对仓库根的写法：

- `postmortems/inbox/<case-id>.md`（postmortem 或指针）
- `postmortems/inbox/<case-id>.case.yaml`（YAML 草稿）
- inbox 是**待审队列**（见 `postmortems/inbox/README.md`）：每周 `/skill:knowledge-groom` 批处理三分类（new_pattern / variant_of / covered_by）后人审。审完：postmortem 转正 `../YYYY-QN/`（covered 也转正——Tier 3 语料，不是丢弃）、new 的草稿升格 `knowledge/<ns>/`

**同一个问题只沉淀一次**——本 skill **只有新增路径、没有更新模式**，重复调用不会改已有条目：

- 闭环结果不走这里。它通过来源 trace 的 `feedback` 事件流转（`pending` → 现场确认 `resolved`），结算读 trace、不读 inbox 草稿，**所以闭环不需要第二次沉淀、也不需要第二个 PR**。
- 再调一次只会新增草稿，且分诊时被 novelty 判成 `covered_by`（因为知识库已有这条）→ 被当已覆盖处理，属空转。
- 若后来拿到更强的证据（实测对照、上游 fix PR 等），要改的是**已升格 case 的 `verification` 档位**，直接编辑该文件走知识修改流程——不经过本 skill。
- 已经重复沉淀了：删掉 inbox 里那份重复草稿即可，别让它进 groom。

**生成后明确告诉用户存哪了**——报出具体路径（如 `postmortems/inbox/custA-ep-hang.md`）和 YAML 草稿位置，说明"周审后转正"，别让工程师去找自己的产出。

**写草稿时的行文**：postmortem 与 case 词条都是给人读、给人审的文本，按 `docs/spec/writing-norms.md` 写（可选论证层，不影响本 skill 执行）；本面的定制条款见该文件 §3 的「case / reference 词条」与「postmortem」两行——症状句要能直接当 grep 判据，`root_cause` / `fix` 只写结论与依据，时间线只放可观察事实。

**结算与提 PR 的粒度（别每次闭环都开 PR）**：诊断现场回报 fix 结果后，trace 里记 `feedback` 事件即可（`feedback.outcome: pending` → 现场确认后置 `resolved`）。**confidence 的结算与入库按周批走一次**——groom 的结算步骤跑 `settle_trace_feedback.py`，一个 knowledge_modification PR 覆盖当期全部变更。本地连着定位多个问题时，不要每闭环一个就提一个 PR：`hits` 只影响候选排序（排序对时效不敏感），而结算游标是 gitignored 的共享运行时件、不进 git。理由是三条写入点的**git 归属刻意不同**：现场记录含客户信息故不进 git，置信度是学习环的持久知识故必须入库，指标时序是周节奏的人复核汇总故不等每次反馈。

**回写来源 trace 的沉淀状态（诊断闭环）**：若本次沉淀来源是一个诊断 trace（输入提到 `traces/<session_id>.yaml`，或用户从诊断面板"沉淀此案例"触发），产出草稿落 inbox 后**回写该 trace 的 `sedimented.state: submitted`**（动作发生时写，零推断）——诊断面板据此显示"已提交沉淀待审"，不再重复提示沉淀。转正（`knowledge`/`archived`）由用户在面板/对话确认时更新，本 skill 不写。

## 收尾 evolve-check（伴随演进评估，默认执行）

**先落执行记录**（evolve-check 读它作现场）：
`python3 scripts/log_skill_exec.py --skill to-postmortem --products "<case-id>(submitted),..." --reason "<一句话根因/来源>" --source <来源 skill> --tokens <估算>`

草稿产出、出最终报告前，执行一次伴随演进评估（`read skills/evolve-check/SKILL.md`
遵循）：对照它的触发条件表看本轮现场——同族沉淀满三条（归纳 reference 候选）、replay/Tier 3
暴露覆盖缺口、提取/校验环节有重复手动动作与流程摩擦。**内容动作直接执行、不产卡**：
归纳 reference 走 `/skill:to-reference --ingest-cases`，补 case 走本流程；只有信号连带
要求改**行为面**（triage 分支、skill 步骤、闸门绑定、索引形态）时，才
`scripts/ev_proposal.py --new` 产卡并自行验证执行（产卡 → golden/S2 验证 → 进攒批）；
无信号则报告加一行"evolve-check：无演进信号"。这是流程默认收尾，**不需要用户另说
"改进系统"**——演进由数据触发，像人学习。产出与流程报告一并给出。

## 为什么是这个体系的核心

团队不能统一 agent 时，知识注入入口必须与诊断工具解耦。`/to-postmortem` 是这个解耦的实现——任何工具的对话都能沉淀。别期望团队成员额外写文档，agent 提取、人审批，成本从 20 分钟降到 30 秒。
