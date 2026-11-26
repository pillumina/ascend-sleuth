# 步骤 2：分类 → triage-tree（先落负载类型，再在负载类型内判性质）

> **何时读**：每次诊断，收集症状之后（必读）。
> **完成判据**：`triage` 事件写了 `workload_type` / `workload_type_source` / `routed`；键触发与背景层各留一条 `reference_lookup`（含 `skipped` 理由）。
> **本步产出**：`triage` / `triage_semantic` 事件、两条 `reference_lookup` 事件。

加载 `triage-tree.yaml`。它给两样东西：`workload_types:`（合法负载类型 + 每种负载类型的目录面与检索顺序）与
`natures:`（三个性质分支：`interrupt` / `precision` / `performance`，各带 `category` 与症状正则）。
**负载类型与性质不互相竞争**：负载类型由步骤 1 的负载类型那一行确定（材料 / 问他 / 框架名，四档见步骤 1），
性质才由症状匹配判定。所以顺序是：先按负载类型取出候选目录面，再在**这一负载类型内**匹配性质分支。

**分批读取别整份灌进来**：三个性质的症状组是训推共用的（同一份词表服务两种负载类型），
所以"看哪个性质"这一步读的就是 `natures:` 那一份正则；`workload_types:` 是几行常量。
这是分层的直接好处——原先同一个宽词在训推两种负载类型各写一遍（全库实测 57 条），
分支顺序一决定，训练分支就会把推理侧的 case 先接住（全库 72 条），现在这种碰撞结构上不存在。

**triage 决策必记 trace**（`workload_type` 与 `workload_type_source` 是分层后新增的两个字段，**每次都要写**）：
```yaml
- {step: 2, action: triage, workload_type: training, workload_type_source: framework,
   branch: interrupt, category: interrupt, routed: [training/mindspeed-llm/, common/]}
```
- `workload_type`：`training` / `inference`，或 `unknown`（他没答、材料也没写——那就不猜）
- `workload_type_source`：`evidence`（材料里读到的）｜`user`（问他、他答的）｜`framework`（对到了库里目录）｜`unknown`（只有 `workload_type: unknown` 时才用它——四档词表与判定见 `../diagnosis-trace.md`）
- `branch` 现在是**性质**名（`interrupt` / `precision` / `performance`），不再带 `training_` / `inference_` 前缀
  ——负载类型已经在 `workload_type` 里，分支名再带一次就是两处记同一件事。分层前写下的历史 trace 保持原样，不改写。
- `routed` 记的仍是 namespace 列表（**带负载类型前缀**，如 `["inference/vllm-ascend/", "common/"]`）——
  路由准确率的分母取它，所以负载类型在 `routed` 里必须看得到。

路由规则：
- 负载类型已定 → 取该负载类型三个性质分支；框架检测到 → `search_namespaces` 先 `<side>/<framework>/`，再 `common/`
- 负载类型已定但框架未检测到 → 只 `common/`
- **负载类型未知** → 训练与推理都查（`<side>/` 展开成两个负载类型），trace 写 `workload_type: unknown`。这不该是常态：
  按它的代价（候选面翻倍）在 trace 里记一笔，够频繁就说明步骤 1 那句问话没问出去。
- **冲突时先单选，不要求工程师表态**：日志签名与症状性质指向不同 category 时（详见 SKILL「始终要避的坑」），**自动单选**并在一句话里说清两条线——先走症状那条，日志那条写明它需要什么信息才走得通；给一句覆盖点让他能改向。**不要把"你觉得这是哪类问题"抛回去**：那是要他做他做不了的判断。两条线的按需参考入口各走各的（精度 / 性能走数据探询闸门，中断走条件型闸门），不因为先走一条就跳过另一条的记录。注意这里的"冲突"是**性质**之间的（同一负载类型内部），不是负载类型之间的——负载类型不需要在两个候选之间权衡，它是事实。
- **优雅退化**：多个性质弱匹配 / 置信度低 → 加载**该负载类型所有 namespace 的索引**让 quickly_check 筛（索引便宜，退化最坏 ~20K token 仍可控）；测不出负载类型时再退化到训练与推理都查。这救冷启动——triage-tree 第一周是猜的。
- 无法分类 → 直接 Tier 3 关键词检索

**路由准确率**依赖这步的 trace：最终 root cause 所在 namespace 是否在被加载集合里（指标定义见 docs/guide/metrics.md）。路由错（分错桶）和 KB 空（分对了没 case）修复动作相反，必须分开测。

**先验查询（本步骤收尾，先于候选加载）**：两半——**键触发**（把证据里能当检索键的东西当场查掉：错误码 `E1xxxx` / `EIxxxx` / `507xxx` / `0x……`、可 grep 的故障签名（`fault kernel_name=`、`event_id`）、具体环境变量名、要核对的版本组合）与**背景层**（平台 / 软件 / 工具事实）。两半都在**候选加载之前**做，两半都留 trace：

- 错误码 → 读 `ascend-error-code-structure` 的 `module_files` 前缀映射定位族文件（`references/errors/<族>.yaml`），族内 grep code 读 meaning / solution（**按码 grep，不整读全族**：最大一族已到 8000+ token，现算见 `python3 scripts/index_read_cost.py` 的先验层一节）。**族文件里查不到这个码时不要就此收场**——`references/errors/_code-gaps.yaml` 是"错误表缺行但库里有事实"的索引：按 code 查一行，`seen_in` 直接指出该码在哪个故障模式词条里有症状→根因→修法（实测有十余个码属于这种：官方表没有行，隔壁表有答案）。也没有 → 才是真的没有，把码写进 `_code-gaps.yaml` 的 `no_home` 段（覆盖缺口要记录，下次遇到能省一次全库翻找）；
- 故障签名 → 按域定位 `references/fault-patterns/<域>.yaml`，域内 grep symptoms 读 cause / fix；
- 环境变量 → `references/env-vars/<表>.yaml` 内 grep name；
- 版本组合 → `references/compat-matrices/` 按传导链分层，按要核对的层直接读该层文件：framework 层 `references/compat-matrices/vllm-ascend-torch-npu.yaml` / `references/compat-matrices/verl-npu.yaml`、adapter 层 `references/compat-matrices/torch-npu-cann.yaml`、base 层 `references/compat-matrices/cann-hdk.yaml`（CANN↔驱动/固件，如 `cann: 9.0.1` 一行直接给配套 `hdk` 列表）——**先落本库矩阵，再考虑联网查证**（厂商文档站多为 JS 渲染，正文表格常取不到）；
- **背景层（同一次收尾里取，与上面四类并列）** → `references/_summary-index.yaml`（生成索引，背景类 + `active`，**一行一条**）：先按 `applies_to.platforms` 匹配客户平台（含 `cross` 或未填 platforms 视为跨平台），该行 `applies_to.categories` 有值时再按本轮 category 收窄，**再用本次症状里的组件 / 工具 / 平台 / 版本词收窄**，取最相关的 **≤5 行**；行内 `summary` 即背景提示（不读全文），确需细节再按 `id` 读单文件。
  - **一行一条怎么用**：三个条件落在同一行上，一次 `grep -E` 就能带上平台与类别（`grep -E 'platforms: \[[^]]*(A3-910C|cross)' references/_summary-index.yaml | grep -iE 'categories: \[[^]]*interrupt|<组件/工具词>'`）。**别把"筛完还剩几条"当成索引坏了**：绝大多数词条的 `platforms` 含 `cross`（跨平台事实本就该跨平台），前两刀切完剩的仍是两位数行数（现算见 `python3 scripts/index_read_cost.py` 的检索残量一行），真正定案的是第三刀（组件 / 工具词）——它才是本步的判断所在。
  - **没命中就换词再试一次**：按平台/工具的另一种写法再 grep 一次（`A3-910C` 与 `910C`、`vllm-ascend` 与 `vllm_ascend`、工具名与它的子命令名），仍无才记 `miss`。跳过这一步就把"我没想到那个词"记成了"库里没有"。
  - **用 grep 取行，别整读索引**：索引随词条数线性增长，整读等于把全库背景一次性注入上下文——本次成本上限就是这 5 行加一次 grep。

**命中了不等于能套用**：故障模式表按**域**组织，同一个码可以在不同病因下出现（如 `507035` 一家讲 UB 对齐违例、现场那单是索引 buffer 取值越界）。读到词条后先核对它的症状面与**本次证据**是否同一病因，不同就写明"命中但不作根因依据"再继续——把命中当结论是把检索当确诊（原则一）。

**为什么提前到这里**：码 / 签名 / 名的**语义**与"命中哪条 case"无关——不知道 `507903` 是什么意思时，case 层给不出解释，而这个解释正是判断候选真假的输入。排在候选加载之后，等于让判断先于理解。背景层同理（它是与具体事故无关的事实）：`platform-fact` / `software-fact` / `tool` 是**与具体事故无关**的事实（先验层的定义），把它的入口挂在"候选命中"上，等于只开给"库里有同类 case"的单子——库里没有同行案例时（未命中路径）最需要它，而那条路径此前能读到的先验只有流程类。时点提到这里之后，**命中路径与未命中路径都在候选加载前拿到背景**。

**为什么必须有负记录**：这个触发点的价值一半在"查到了什么"，另一半在"**没有可查的键**"。证据里没有可检索键（报错是框架自定义断言文本、Python traceback、业务日志）时记 `outcome: skipped` 并写明理由——不记的话，"库不覆盖这个键"与"根本没查"在数据上完全同形。背景层没有"没有可查的键"这种豁免：平台 / 组件词几乎总有，所以它记 `miss`（查了没有）而不是 `skipped`，只在证据里连平台都判不出时才 `skipped`。

trace 记两条（同一时点、同一 `step`，`purpose` 不同）：`{step: 2, action: reference_lookup, purpose: signature, outcome: hit|miss|skipped, ref_id, platform, output, reason}` 与 `{step: 2, action: reference_lookup, purpose: background, outcome: hit|miss|skipped, ref_id, platform, output, reason}`（`outcome` 三态词表见 `../diagnosis-trace.md`）。**每次诊断都留**（含 `skipped`）——它们是"这一单有没有可查的键""背景层有没有可用的词条"的数据源。