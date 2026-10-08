# 本仓落点：层、面、边界

> 这一份是 [SKILL.md](../SKILL.md) 的**项目落点**。类型判定、各类骨架、跨类型硬规则与项目无关，可以整份搬到别的仓库；换项目只改本文件。
> 本文件里的层名、路径与门名都取自当前仓库，改动它们的清单是 `docs/_manifest.yaml` 与 `.github/workflows/kb-checks.yml`。

## 1 `docs/` 的六层各自装什么类型

`docs/` 下的层不是文档类型，是「什么时候读」的分组（定义在 `docs/_manifest.yaml` 的 `layers:`）。同一个层里的文档按同一类写，读者不必每篇重新猜结构。

| 层目录 | 层回答的读者问题 | 文档类型 | 骨架见 |
|---|---|---|---|
| `docs/README.md`、`docs/demo-walkthrough.md` | 这套系统在做什么，我该从哪读起 | 导览 | type-catalog.md §导览 |
| `docs/spec/*.md` | 某个设计或改动合不合规 | 规范条文 | §规范条文 |
| `docs/mechanism/*.md` | 要改机制本身时，它怎么运作、边界在哪 | 机制说明 | §机制说明 |
| `docs/guide/*.md` | 我要把那个环节做出来 | 操作指南 | §操作指南 |
| `docs/plan/*.md` | 下一步做什么、什么时候算做完 | 计划 | §计划 |
| `docs/adr/*.md` | 当初为什么这样选，能不能推翻 | 决策记录 | §决策记录 |

新增一篇文档时，先定位它属于哪一层；层对了类型就定了，类型定了骨架就定了。层本身的选择写进 `docs/_manifest.yaml` 的 `docs:` 段——登记是硬要求，未登记的 `.md` 会让 `docs-index` 门报红。

## 2 全部人读面 → 类型与现有写点

下表是 `docs/spec/writing-norms.md` §3 那份「人读面清单」的**篇章层**对应表。词句怎么写看 writing-norms；每面该有哪些节、按什么顺序，看这张表。

| 面 | 按哪类写 | 依哪份文本写 |
|---|---|---|
| `docs/**` 正文 | 见上一节的九类之一 | 本 spec + `type-catalog.md` |
| `docs/adr/*.md` | 决策记录 | 本 spec + `type-catalog.md` |
| `skills/**/SKILL.md` | 规范条文 | 本 spec + `type-catalog.md`；另有 skill 自身的结构约束，受 `skill-self-contained` 门约束 |
| 定位报告 `traces/*.report.md` | 复盘 | 自带模板 `skills/diagnose/references/report-template.md`，以模板为准 |
| trace 人读字段 | 未映射到九类 | 自带模板 `skills/diagnose/references/diagnosis-trace.md` |
| 诊断对话输出 | 未映射到九类 | 无固定骨架，见 `skills/diagnose/SKILL.md` 的输出格式一节 |
| case / reference 词条 | 参考词条 | 自带 schema：`skills/to-postmortem/SKILL.md`、`skills/to-reference/SKILL.md` |
| EV 卡 `proposals/ideas/*.yaml` | 提案 | 自带 schema：`docs/mechanism/pipeline.md` §7「改进项的 schema 与状态机」 |
| postmortem `postmortems/**` | 复盘 | 本 spec + `type-catalog.md`；产出模板在 `skills/to-postmortem/SKILL.md` |
| PR body / 评审摘要 | 提案 | 自带五类模板：`.github/PULL_REQUEST_TEMPLATE/` |
| 面板文案 | 未映射到九类 | 自带清单：`dsh-plugins/README.md` 的定制条款一节 |
| 指标注记 | 未映射到九类 | 无固定骨架，写在 `metrics/timeline.d/*.yaml` 里 |
| 对话回复 | 未映射到九类 | 无固定骨架，见 `CLAUDE.md` 的对话回复条 |

第一列的面名取自 `docs/spec/writing-norms.md` §3 那份清单，本表不另造面名。第二列只出现两类值：九类名，或「未映射到九类」；不出现别的类型名，也不把类型名和别的标签叠在一格里。

第三列写这一面实际依哪份文本写。写「本 spec + `type-catalog.md`」的，按本 spec 的小节骨架写；写「自带模板 / 自带 schema」的以那份模板为准——它可能与本 spec 的骨架不同，冲突时以模板为准，因为模板是该面对外的输出契约。本 spec 只在这些模板要改、或要新增一类面时提供判定口径。判据只有一条：该面**读者手上有什么**，这决定它是共用条目还是要定制（writing-norms §4）。

## 3 与 `docs/spec/writing-norms.md` 的边界

两篇互指，各管一层，**不互为副本**：

| | writing-norms | 本 spec |
|---|---|---|
| 管什么 | 词句层：一条怎么说、什么词不能用、哪些原值必须保留 | 篇章层：这是哪类文档、该有哪些节、按什么顺序、多长、图放哪、状态怎么标 |
| 读者 | 正在写具体一句话的人 | 正要动笔写一篇文档，或要改一篇结构散掉的文档的人 |
| 何时读 | 动笔前与提交前自查 | 定类型与列大纲时 |

两边冲突时，事实与可核查性优先（writing-norms §0 与 §2）：本 spec 的任何结构调整都不得删掉编号、命令、数字与报错原文。

**本 spec 不内联 writing-norms 的条目，只指路。** writing-norms §6 规定 `skills/**` 要自包含，例外清单针对的是「进 agent 上下文的面」（报告、trace、case 词条、诊断对话输出）——它们执行时确实可能读不到 `docs/`。本 spec 服务的是 `docs/` 与 skill 正文这个面，而这个面的写点就在仓库里，`docs/` 必然在手边；再抄一份会立刻破坏 §6 记的核对不变量（关键短语的命中数应当是固定的那几个文件，多一个就要查清）。跨项目复用时，词句层按目标项目自己的规范走，不由本仓的条目代管。

## 4 本仓已经定下、但此前没有写成文的约定

这几条在仓库里是既成事实，但没有任何文件写过，于是每篇文档都靠人记：

- **一段一行**：中文段落在源文件里不硬换行，长行交给编辑器软换行。现状如此（`docs/mechanism/pipeline.md` 非空行 457、平均 151 字符），代价是 PR 里改一句话会让整段进 diff——接受这个代价，换掉它要重排全仓并让后续每次编辑都产生重排噪音。
- **直角引号**：正文一律用「」，不用弯引号。现状：`grep -rn '“' docs --include=*.md` 只命中 `docs/spec/writing-norms.md` 第 40 条的反例那一处（`docs/kb-explorer/*.js` 等素材文件里有，不属正文）。
- **中文含义在前、内部代号放括号**：读者不先读一遍 `docs/` 就读不懂的词，都要当场展开。
- **数字与名单不手写**：凡是「共 N 篇 / 共 N 个」这类计数，从 `docs/_manifest.yaml` 生成，正文里不写死。

## 5 本仓已有的机械门（别重复造）

写规则前先看这里：已经有机检的，本 spec 不重复描述；想让新规则进 CI，按 writing-norms §5 的准入三条判（①机械可查 ②后果确定 ③复发 ≥2 次），三条都满足才写进去，判断性条目留人审，不假装硬化。

| 门 | 管什么 |
|---|---|
| `docs-index` | `docs/**` 未登记即红；生成区块与清单不一致即红 |
| `skill-self-contained` | `skills/**` 内不得出现 ADR 号、日期、卡号等外部锚点 |
| `unit-tests` | 索引生成物、计数、日期等不变量 |
| `panel-checks` | 面板文案的排版与退化路径 |
| `pr-template` | PR body 的节齐全 |
| 各面自带的 `*_lint.py` / `verify_*.py` | 结构、枚举、字段溯源；都不读行文 |

一句话概括现状：**结构与枚举已经有机检，行文一律靠人审**。本 spec 新增的可机检条目应当落在「结构」这一侧。
