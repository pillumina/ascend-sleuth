# 这些骨架从哪来

> 这份文件只记录来源，不重复规则。规则正文在 [SKILL.md](../SKILL.md) 与 `type-catalog.md`；这里回答「凭什么这么定」和「将来该去重查谁」。
> 引用的都是公开的写作规范与传统模板，不含本仓路径——换项目不用改这一份。词句层的来源在文末单独一段。

## 按规则归类

| 规则 | 主要来源 |
|---|---|
| 先定类型再写；一类一套固定小节；参考类只描述、不指导不解释 | Diátaxis、Divio、Google 技术写作指南、Microsoft Writing Style Guide、Kubernetes 文档风格、GitLab 内容类型 |
| 入口五件事、结论先行、渐进披露、标题写成读者要做的那件事 | plainlanguage.gov、Google 技术写作指南、NN/g 的扫读研究、《Docs for Developers》 |
| 机制说明的节序：范围与不变量 → 最小可执行模型 → 完整机制 → 边界与失败模式 | arc42 的节序与「黑盒 / 白盒递归分解」 |
| 图的规则：独立可读、图例、元素给类型与职责、关系线写清传什么 | C4 model 的 diagram notation 与 tooling |
| 提案：动机只讲问题、非目标、替代方案给代价、缺点不可空 | Rust RFC、PEP、IETF RFC 的模板与流程、Kubernetes Enhancement Proposal、Oxide RFD、Squarespace RFC |
| 决策记录：状态枚举、已接受不改写、双向 supersede、被否不删 | Nygard 的 ADR 原文、MADR、adr.github.io 模板集 |
| 状态字段与「已落地要能确认」 | MADR 的 Confirmation 节 |
| 复盘节序、行动项表、无责归因、用词不夸大、时间线给来源 | Google SRE Book 的 postmortem 章节与示例、PagerDuty postmortem 指南与 anti-patterns |
| 不设字数上限、一节不超七小节、出边不超五条 | arc42 的拆分判据、Diátaxis 的 map、C4 的分层克制 |
| 能机检的条目：单 h1、标题不跳级、代码块标语言、术语唯一、必填小节齐备 | markdownlint、remark-lint、Vale、textlint 的中文分句插件、zhlint |
| 误报三档处置：改写 / 进例外表 / 行内豁免 | GitLab 的 Vale 政策；Kubernetes、Red Hat、Grafana 的真实抑制清单 |
| 类型名不跨规范搬运；引入新类型名前先写判据 | Diátaxis 的 compass 两问，与各规范的同名异义对照（Tutorial 在 Diátaxis 是新手课、在 Kubernetes 是端到端走查；Troubleshooting 在 Diátaxis 属 how-to、在 GitLab 是并列第四类） |
| 条目标强度；规范性引用与资料性引用分开；提案头部带决议链接 | IETF RFC 2119 的约束词分级、RFC 7322 的引用分类、PEP 1 的头部字段 |
| 一般信息在前，例外与条件在后 | plainlanguage.gov、Google 技术写作指南 |
| 每个论断给出处；同一件事只有一个来源 | Write the Docs 的单一来源实践，加上本仓 `docs/spec/writing-norms.md` §6 记的漂移教训 |
| 接入顺序与误报处置（先格式项、再配置项、最后词表项） | GitLab 的 Vale 政策（error / warning / suggestion 三级与提级条件） |
| 中文行文、标点与排版的条目 | 阮一峰《中文技术文档的写作规范》、《中文文案排版指北》、微软简体中文本地化风格指南、W3C《中文排版需求》、OpenHarmony 写作规范、腾讯云对外发布文档规范、阿里巴巴 Java 开发手册·注释规约、ASD-STE100、zhlint 的中文规则 |
| 中文句长与段落长度的经验阈值 | yikeke/zh-style-guide（一句 100 字、一段 50–200 字、不超过 250 字）。英文可读性研究没有中文对应值，所以这些数字一律标成本仓自定 |
| 入口段不超过三句 | NN/g 的阅读时长换算（英文约 100 词）。中文没有对应研究，取句数不取字数 |

## 没被采用的部分

- 英文可读性阈值（词数、句数、可读性分数）对中文没有对应研究，不搬。本规范一律用结构性约束替代数字上限。
- 「黑话密度」的净效应有争议（有研究说少量术语反而提升可信度），不写成「已证明降低理解」。
- 云厂的支柱→原则→评审体系、ISO 42010 的完整视点框架，成本高于收益，只借「原则编号化、每条一句可判定」。
- 外链可达性检查：天然不稳，主流项目直接关掉。
- 提案流程制度（受理门槛、champion、审阅权分离、审阅只允许 yes 或 not yet、「什么不需要走提案流程」）：本仓的提案落在 PR 与 EV 卡上，这些制度没有载体。
- Markdown frontmatter 的必填字段与枚举：本仓的 Markdown 没有 frontmatter，登记与字段检查在 `docs/_manifest.yaml` 与各自的脚本里，不另开一处。
- 四列术语表（概念｜首选术语｜避免词｜允许例外）：`docs/glossary.yaml` 是设计层代号词表与范围表，不是术语表；另建一份等于开出第二个真相源。术语一致性靠「一个概念一个词」加人审。
- 标点行首行尾禁则与标点挤压：由渲染器处理；本仓源文件不硬换行，写成条目只会造出查不动的规则。
- 英文特有的条目（there is / there are、冠词、英文词数可读性分数）：中文没有对应结构，搬不过来。
- 完整 SCQA 修辞结构与 Mayer 的 modality / voice / personalization 三条：只取 coherence、segmenting、pre-training，其余与本仓读者（带着明确故障来检索的专家）不匹配。
- 「网页平均只读 28%」这类结论：不能反推「本仓每篇必须短」，读者是来查一条具体答案的。
- 「类型学与导航必须同轴」：Diátaxis 主张一页一类型，GitLab 允许页内多 topic，本规范取前者。
- 决策记录的节序取「状态最前」：Nygard 的原文把 Context 放最前、Status 在后，MADR 与 adr.github.io 的模板把 Status 提到最前。这里跟后者——读者先要知道这条还算不算数，不值得为忠于一份模板让每个人先读一遍背景。

## 词句层的来源

`docs/spec/writing-norms.md` 面向中文词句，条目出自另一条线：阮一峰的中文技术文档写作规范、《中文文案排版指北》、微软简体中文本地化风格指南、W3C 的《中文排版需求》、OpenHarmony 写作规范、阿里巴巴 Java 开发手册的注释规约、ASD-STE100 的受控语言思路、zhlint 的中文规则。
上半段（§1.1 行文）沿用这几位；下半段（§1.2 标点与排版、§1.3 数字与文件名）里可机械检查的部分，可查性参照的是 zhlint 一类工具，阈值与「本仓现状」的实测数见该文件本身。中文没有官方受控词表，所以本仓只能声称「按本项目规则检查通过」，不能声称合规。
