# ascend-sleuth 诊断面板（DSH 插件）

诊断可视化操作台，对话视图提供两个 tab：

- **诊断**：会话列表（状态/时间/搜索/过滤）→ 展开轨迹（summary/evidence/reason/reference）→ 证据文件打开
- **指标**：**闭环判决**（首屏只列要处理的判据：结论 → 证据 → 下一步 + 可复制指令）→ 状态条（快照新鲜度 + 判据覆盖面 + 索引/磁盘 drift）→ 闭环检验（判据全貌，折叠）→ 容量台账（**逐格** + 历史趋势条）→ 存量体检 → 趋势差分 → timeline 快照 → 实时计算

### 体检器失效与容量趋势（2026-09 三轮）

**① `--check` 三态接进首屏**。体检器现在区分三种结局——`0` 判据全部评过且无越界 / `1` 有判据被违反 /
`2` **有判据没被评估**（结论不可用）。第三态是本轮实测出来的必需项：修前只看"有没有 ✗"，
于是两回假绿都无人喊——一处漏解包让容量判据从未触发、`gates.yaml` 解析失败被
`except: return {}` 吞掉后体检器报 `clean（判据全部评过）`。面板据同一份输出：

- 状态条加"判据 N/M · 可解读性 K/L"（**"没报越界"与"没被检查"从此可区分**）
- 第三态时出现红色 `BrokenDetector` 横幅：点名哪条判据没被评估，并明写
  **"下面列的『没有报出越界』不等于『没有越界』"**，附复现命令与三态退出码语义

**② 容量历史趋势条**。容量是唯一有多个数据点的通道（live 快照只有 3 期且指标口径逐期不同）。
每格画迷你条形（CSS 条形原语，与 ev-panel 的 `.ev-bars` 同一套，不用 SVG）并标净增量
——实测 `inference/vllm-ascend · interrupt` 显示 **`32→85 (+53)`**，从"压线"到"硬上限"的
走势一眼可见。**门槛**：当前值以判决（体检器对磁盘现实的判定）为准，历史只画走势。

做这条时踩到一个形状问题（如实记下）：timeline 里的容量有**三种写法**——
`{count, cap}` 字典（W37-live 起）、`"36/30"` 字符串（W35/W36-capacity）、整块缺席（诊断侧 live 快照）。
只认第一种的话趋势永远只有 1 个点、什么也画不出来。`normalizeCapacity` 归一三种形状后才有 3 个点；
`scripts/panel_render_check.js` 的断言也按同一归一口径独立重算，避免"只认一种形状"悄悄退化。

### 指标 tab 的"闭环判决优先"（2026-09 二轮重做）

一轮重做（下面那节）把"变了什么"提到了首屏，但仍然**没有回答"这算好还是坏"**：
实测面板显示 20+ 行 label/value，其中 `85/30`（soft_cap 的 2.8 倍、已超 hard_cap）
和一格正常的 `8/30` 长得一样；`misdiagnosis_rate 0/3` 被读成"零误诊"。
根因是**判据链在最后一步断了**：

| 层 | 状态 |
|---|---|
| 判据（阈值） | `metrics/gates.yaml` 有 —— 面板**不读**（自己写死 `/30`，还把格子加总到 namespace） |
| 检测器（结论+动作） | `scripts/metrics_health.py` 有 —— 面板**不调** |
| 展示 | 面板把「数据说明」默认折叠，正文是"早期 trace 缺事件"的历史欠账说明 |

二轮改成：**面板不重算判据，只渲染体检脚本的结论**。首屏是 `VerdictCard`——
一行一条判据，恒为 `结论 · 证据 · 下一步`，点开给可复制指令；零越界时不占位，
只留一行"本期无阻塞项 · 已检 N 项判据"。

四个随之修掉的具体缺陷：

| 缺陷 | 实测 | 修法 |
|---|---|---|
| 容量口径与判据不一致 | 面板把 (framework × category) 加总到 namespace 比 `/30`（vllm-ascend 显示 `114/30`），判据是**逐格**计（interrupt 单格 85/30） | `CapacityLedger` 逐格渲染，阈值从 `gates.yaml` 读 |
| 假绿无视觉区分 | `0/3` 与 `85/30` 同等权重；gates 明确判 `misdiagnosis_rate` **不可解读** | 指标行挂「不可解读」徽标 + title 说明；反馈告警改写为"所以标着不可解读（不是 0）" |
| 看到的不等于现实 | 面板读的是**生成物**索引/快照（`case 总数` 来自 `_index.yaml` 头注、还没写进任何指标的 `85/30` 只出现在快照 note 里），陈旧时不标注 | 状态条报快照龄期（`2026-W37-live · 1 天前（阈值 7 天）`）+ 索引↔磁盘 drift（`索引 N ≠ 磁盘 M`；两者一致时不显示告警） |
| 判据不可查 | 读者不知道面板覆盖了哪几条腿 | `CheckLedger` 折叠区列出全部判据项（含 ✓），一行标出来源是 `gates.yaml` |

**阈值的唯一归属**：面板、CI、周批都读 `metrics/gates.yaml`。改判据只改那一处；
`scripts/panel_render_check.js` 有断言钉住"面板报的越界格 == 按 gates 独立算出的越界格"。

**顺带修掉的判据链断点**（本轮实测发现，改面板之前先修它）：
`scripts/metrics_health.py` 里 `MS.collect_structural(root)` 返回 `(out, notes)` 元组，
但调用处没解包 → `structural.get(...)` 抛 AttributeError 被 `except` 吞掉
（`s_notes` 因此恒为空）→ `capacity_by_ns` 恒为空 dict → **容量越界判据从来没触发过一次**，
`--json` 的 `current` 块也跟着恒为 `None`。容量这个最要命的信号（85/30，硬上限 60）
因此只能靠人读快照 note 里的散文才发现。

### 指标 tab 的"变化优先"（2026-09 一轮）

旧版把 7 期 × 10+ 指标全平铺成 label/value 网格，读者得自己逐行找"哪一行和上期不一样"。
一轮改成首屏 `CompareStrip`：只列**动了**的指标（新增 / 变化 / 本期不再采集），
标注 `7 → 11` 与增量，末尾报"N 项持平"；期卡收起时带前 3 项指标摘要。
差分回答"动了什么"，判决回答"这是不是问题"——两者叠加，首屏才既聚焦又可解释。

## 加载方式

本插件是动态 Cordis 插件，定义只存在于当前 DSH 进程，重启后需重新加载。

### 快速开始

在 DSH 对话中粘贴（或直接 `/skill:preload-panel`）：

```
请加载 ascend-sleuth 诊断面板：
① 若会话里没有 panel_from_file 工具，先读 dsh-plugins/loader/panel-from-file.js，
   用 cordis_define（kind: new，idPrefix ldr，code.host ← 全文）+ cordis_run 加载它（host-only，免审批）；
② 然后 panel_from_file(host: dsh-plugins/ascend-panel/panel-host.js,
                        client: dsh-plugins/ascend-panel/panel-client.js,
                        idPrefix: sleu, name: "ascend-sleuth 诊断面板", purpose: "…")。
完成后对话视图应出现「诊断」「指标」两个 tab。
```

`panel_from_file` 读盘 → 定义 → 激活，**只发两个路径**。**不要自己把文件内容重新输出一遍**：两个文件合计 ~70KB，转写要几千 token、几分钟；给路径只要几十 token。`/skill:preload-panel` 是同一流程的 skill 封装（仅 DSH）。

前置条件：agent 具备 `cordis_define` / `cordis_run` 工具；工作区为 ascend-sleuth 仓库（面板读 `traces/`、`knowledge/`、`references/`、`metrics/`）。

### 手动加载

1. 加载 loader（一个会话一次，host-only 免审批）：`cordis_define`（kind: new，idPrefix `ldr`，`code.host` ← `dsh-plugins/loader/panel-from-file.js` 全文）→ `cordis_run`
2. `panel_from_file`（idPrefix `sleu`，`host` / `client` 指本目录两个文件）→ 返回 awaiting-approval 时在 UI 允许 → 出现「诊断」「指标」两个 tab

**形态约束**：文件是 `cordis_define` 需要的函数体（`return { apply(ctx) {...} }`），原样读入/粘贴。不要改成 `export default` / `import`——动态插件代码不经过打包器，ESM 语法无法加载（此前因此失败过一次）。

**改代码后**：读入的是**定义时的快照**——编辑 `panel-*.js` 后要 `panel_from_file`（`pluginId` + `mode: 'update'`）追加新 Package 再切换。

**DSH 版本差异**：`cordis_define` 支持 `codeFile` 时，可跳过 loader 直接
`cordis_define(codeFile.host, codeFile.client)` + `cordis_run`；两者都没有时回退到读全文内联。


### 面板统一色语（2026-09）

本面板与 ev-panel 共用一套颜色角色（`scripts/check_panel_tokens.py` 校验）：
`--c-*` 文字色、`--acc-*` 装饰色、`--fill-*` 实心底、`--btn-*` 渐变端色。
改动：原先直接拿亮色当文字用（`#22c55e` 绿 2.28:1、`#f59e0b` 琥珀 2.15:1，均不达 AA），
现在文字走 `--c-*` 深档；渐变按钮压深一档（原 `#3b82f6` 白字 3.68:1 → `#2563eb` 5.17:1）。

> **跨面板契约不在本文件维护**：颜色角色、字号行高、文案规范、只读边界与依赖缺失时的退化口径，
> 统一见 [../README.md](../README.md)（`dsh-plugins/README.md`）。本文件只写本面板的信息架构与历史。

**五轮追加的角色纪律（一色一义）**：`--d-*` 是"同色相深档"，专供**文字与描边**；
`--acc-*` 只作**大块面 / 进度条 / 图形**；`--tint-*` 是统一轻底纹（亮色 9% / 暗色 15%）。
判据颜色由语义唯一决定：红=越界，琥珀=提示，绿=健康态，紫=不可解读，蓝=品牌与交互。
**为什么加这一层**：实测所有文字色都已过 AA（4.76–7.09:1），而用户仍反馈"配色尖锐"——
根因是同一语义色出现在四处（底纹+左边框+图标+胶囊），以及绿色同时表示"库健康/品牌/容量正常"
三项无关语义。**收敛用色位置比调色值有效**。另补 `--surf` 叠加层与 `--hair` 发丝线
（定义了却没用到等于白写；亮色下 `border-l1` 只 4% 黑，卡片没有边界、层级靠色差硬撑）。

## 依赖

- Host：`fs` / `sessions` / `shell`。`shell` 缺失时证据文件打开、**指标判决**与实时计算降级，其余正常。
- **`ctx.shell` 不是 bash**：服务名写着 "bash execution"，但 **DSH 在 Windows 上把它接到 Windows PowerShell 5.1**
  （实测：bash 语法 `a || b`、`2>/dev/null`、`&` 全部是语法错误）。面板里任何走 `shell` 的命令都必须
  按方言安全写——打开文件那条用了"最可能的方言在前、失败试下一个、按 exit code 判定"的阶梯
  （`Start-Process` → `open` → `xdg-open` → `explorer.exe`），不是一条 bash 链。踩坑记录：
  旧实现 `(open X || xdg-open X) >/dev/null 2>&1 &` 在 PowerShell 下整条命令解析失败，又被后台重定向吞掉，
  用户点「打开报告」**完全没有反应**。要确认某条命令在面板环境里的真实行为，可临时注册一个 host-only
  探针工具（跑 `shell.resolve` + `shell.run` 并回传 exit code/stdout），而不是拿本地 pwsh 的直觉推断。
- **指标判决依赖 Python 3 + PyYAML**（跑 `scripts/metrics_health.py --json`）：解释器按
  `python3` → `python` → `py -3` 逐个探测；缺解释器/缺 PyYAML/超时/无输出都返回**可执行的提示**
  （例如 `pip install pyyaml`），面板显示「体检不可用」而**不是**假装闭环正常。
- **工具重名降级**：host 会注册 `ascend_trace_status`（供 diagnose 查未完成 session / feedback 债）。
  `harness.registerTool` 在名字已被占用时**同步抛错**——曾因此让整个 `apply()` 中断、面板完全加载不上。
  现在改为 try/catch 告警：同名工具仍可用（占用者通常是上次会话遗留的同类插件），面板其余功能照常。
- 工作区：ascend-sleuth 仓库（Host 从 session.header.cwd 解析）。

## 功能

| 能力 | 说明 |
|---|---|
| 会话列表 | 状态徽章/更新时间/计数；搜索（session/状态/框架/定位 case）；过滤（全部/库中已有/新形态/未定位） |
| 轨迹展开 | summary 问题背景；每步 output/reason；evidence（inline 原文折叠/文件点击打开/缺口标记）；reference 参考层徽章 |
| 续接 | 未解决会话生成 resume 指令（复制→对话触发） |
| 沉淀 | 四状态呈现 + 沉淀指令 copy + 双标记操作（Tier2/Tier3 回写） |
| 报告与沉淀入口 | 卡片给「打开报告」（`traces/<session>.report.md`，人读定位报告）与「待沉淀 N 条」（trace `sediment_candidates` 条数）；面板只做入口，不改报告内容 |
| 指标 tab · 闭环判决 | 首屏按 `metrics/gates.yaml` 的判据列出**要处理的**（✗/!），每条可展开取证据、`gates.yaml` 的动作原文与可复制指令；零越界时一行说明 |
| 指标 tab · 状态条 | 最后核验快照的期号与龄期（含阈值）/ live·结构期数 / case·ref 总数 / 索引↔磁盘 drift |
| 指标 tab · 容量台账 | **逐格**（framework × category）`85/30 2.8× 硬上限`，阈值读 `gates.yaml`，正常格折叠计数；每格带历史趋势条与净增量（`32→85 (+53)`） |
| 指标 tab · 体检器失效 | 有判据没被评估时出红色横幅（判据 N/M + 缺口点名 + "没报越界 ≠ 没有越界" + 复现命令），**不显示**"闭环未见阻塞项" |
| 指标 tab · 存量体检 | 知识库健康（case 总数/低置信/category 分布 + reference 草稿/过期/type）+ 流程闭环（沉淀漏斗/续接/参考参与） |
| 指标 tab · 趋势与快照 | 本期 vs 上期差分（只列动了的）+ timeline 期卡（live 置顶 + 小样本/不可解读标注）+ 实时计算 |
| 学习环提示 | 反馈未回报警示 + 回报指令生成（复制→对话触发 feedback 动作） |
| 不可解读标记 | 分母为 0 的指标（误诊率/归因比）显示「不可解读」徽标而非 `0/N`；期卡头报该期有几项不可解读 |

## 回归闸门

`scripts/panel_render_check.js` 的「指标 · 闭环判决」节断言（用真实 `gates.yaml` +
真实 `metrics_health.py --json` 输出，不硬编码计数）：

- 体检 JSON 的字段齐备（`gates` / `readability` / `capacity_cells` / `freshness` / `candidate_commands`）
- **口径一份**：面板报的越界格数 == 按 `gates.yaml` 阈值独立算出的越界格数
- 首屏出现判决条、失败判据文案、容量越界格 `85/30`；「不可解读」被标记且原因可查
- drift 双向测（不等时报、相等时不报 + 合成不一致时能报）
- 点开判决行给出「下一步动作」「可复制指令」，且指令含真实脚本/技能名
- **负样本**：体检不可用时如实报错、且不显示"闭环未见阻塞项"
- 契约：client 每个 RPC 都有 host 声明、host 没有 client 不用的 RPC；
  host 侧不再有 `byNamespace`、不再内联 `30` 做判断、确实走 `metrics_health.py`
- **三态**：用 `scripts/fixtures/make_broken_metrics_root.py` 造两个"判据不可评估"的临时 root
  （多一条未实现的 dimension / gates.yaml 语法坏掉），断言 `--check` 报 **2** 且 verdict 不是 `clean`；
  真实数据下断言 `violations` + `exit 1` + 判据 3/3
- **体检器失效态**：合成 broken verdict → 断言横幅出现、点名缺口、覆盖面显示 3/4、
  且**不**出现"闭环未见阻塞项"
- **趋势条**：按三种容量形状归一后独立重算，断言条形渲染 + 走势与净增量文本一致
- **trace 解析契约**：两种写法都要吃——内联 `- {role: …, output: "…"}` 与块写法（`- role: agent` 换行展开、
  长文本用块标量 `>-`）。断言"事件里有没有 output/content/reason/evidence"，**不看步数**：
  `role` 在 dash 行上，旧实现（只认内联）虽然把事件内容全丢光，步数计数**恰好仍然是对的**——
  于是这个 bug 一路漏到用户面前（表现为"agent 回答都是空的"）。含证据两种形态（内联字符串 / 块映射）。
- **报告与沉淀入口**：host 从 trace 读 `report_file` / `sediment_candidates`；client 给「打开报告」与
  「待沉淀 N 条」；断言面板**只做入口不写报告**（无 write-report RPC）。
- **指令区形态**：按钮横排（`flexWrap`）、展开的命令块只有一处、卡片内不复读提示文案。

## 版本

- 2026-09 · 指标 tab 七轮（说人话）：用户指出面板里全是**变量名**——`cell_soft_cap`、
  `feedback_capture_floor`、`misdiagnosis_rate`——而且句子是对着实现说的
  （"(framework × category) 格子条数超 soft_cap"）。这是**把我自己的内部标识符当成了用户文案**。
  改法：**一个概念两层说法**——
  `metrics_health.py` 的 findings 从 4 元组扩成 5 元组，多一列 `plain`（人话版）；
  判据的**身份**住在脚本那一侧，所以人话也由它提供，**面板只渲染、不做启发式翻译**。
  面板收起态渲染 `plain`，展开区保留技术文案作「判据出处」（维护者仍能拿到判据名回查配置）。
  同轮三处：
  ①**面名改用户语**：`越界 cell_soft_cap` → `容量`，`可解读性` → `数字可信度`；
  ②**一个格子只报一条**——85/30 同时越过 soft(>30) 与 hard(>=60)，旧版渲染成两行几乎一样的话，
  现在合成一条并在判据出处里写清"越过 cell_soft_cap、cell_hard_cap"（越界项 5 → 4）；
  ③**命名空间与类别写中文**：`inference/vllm-ascend · interrupt` → `推理 · vllm-ascend 的「中断类报错」`
  （它们是框架侧的机器标识，直接端给读者等于让人读目录名）。
  回归断言：每条失败判据都必须有人话版、人话版**不得残留实现标识符**、收起态不出现判据名、
  展开区仍能回查到技术文案。
- 2026-09 · 指标 tab 六轮（字体与排版）：用户反馈"字体小、看着累"。**先量再改**——实测原状：
  字号有 **9 档却只差 3.5px**（9.5→13）、正文 11–12px、中文 `line-height` 只有 1.5。
  三处改动：
  ①**字体栈走 token**：`--font-sans`（system-ui 打头 → Windows 现代 UI → 无衬线兜底，
  中文交给系统 PingFang / 微软雅黑 UI）、`--font-mono`、`--font-num`（数字等宽）。
  **不做 web font**：离线/内网会闪烁或失败，中文子集动辄几 MB。
  组件里 100+ 处内联 `fontFamily` 全部改走 token，并以 `.sleu` 作为字体与排版的唯一落点。
  ②**建立字号尺度**（`--t-micro` 10.5 → `--t-xl` 20）：基准从 13 提到 **14.5**（中文在 11–12px 会糊），
  最小 UI 字号从 9.5 提到 10.5；标题走 `.sleu-title`（收紧字距 `-.012em`）。
  ③**中文行高放宽**：`--lh-base` 1.6 / `--lh-prose` 1.75（西文 1.5 够，中文不够）；
  数字一律 `tabular-nums` 等宽对齐（指标/容量/期号同列可比）。
  顺带把"现代观感"落在三件套上：`--elev-1/2` 分层柔和阴影、`--r-sm/md/lg` 圆角尺度、
  `.sleu-row/.sleu-card/.sleu-chip` 的 hover 反馈（**响应感来自交互，不是装饰**）。
  回归新增一节排版契约（字体栈无字面量残留、档位 ≤8、最小字号 ≥10、基准 ≥14、行高 ≥1.6、
  根挂 `.sleu`、阴影/圆角走 token、hover 走 class）——防止后续又漂回"每处各写各的"。
- 2026-09 · 指标 tab 五轮（可读性 + 一色一义）：用户反馈"看着吃力、配色尖锐"。**先算再改**——
  实测所有文字色对白底 4.76–7.09:1、暗色 7.6–10.6:1，**全部已过 WCAG AA**：所以"尖锐"不是对比度不够，
  是**同一语义色被用在太多地方**（红同时出现在底纹+左边框+图标+胶囊+按钮；绿色同时表示
  "库健康/品牌/容量正常"三项无关语义）。三处改动：
  ①**版式改单行流式**：旧版判决行是三栏（图标+66px 标签列+正文），一句话被拆成三段读起来断续；
  现在图标与判据面标签跟正文同行内联、正文自然换行，并要求每行**聚焦一件事**。
  ②**诊断信息不再端给用户**：体检器失效时首屏先说"哪几项没跑 + 所以结论怎样"，把原始异常串、
  判据覆盖面、复现命令与三态语义收进「为什么没跑 / 怎么复现」折叠——旧版首屏直接铺
  `PermissionError: [WinError 5] 拒绝访问。`，读者先撞见实现细节才轮到"我要做什么"。
  ③**一色一义**：新增 `--d-*`（同色相深档）专供文字与描边、`--acc-*` 只作大块面/进度条；
  底纹统一 9%（原先 5/6/8/12/14% 各写各的）；容量台账的"琥珀→红"渐变收掉；红色只留给越界；
  绿色不再兼作品牌；并补上 `--surf` 叠加层与 `--hair` 发丝线（原先定义了却没用到）。
  另修两处：判据文案里的 Markdown `**` 会渲染成字面量；broken 态下状态条说"判据 3/3 全部被评估"
  与横幅"判据不完整"**自相矛盾**（读者会以为其中一句在骗人），现改为"本轮有判据没跑（N 项）"。
- 2026-09 · 指标 tab 四轮半（真因修复）：验收当天用户报「体检脚本报错 + 一截截断的 traceback」，
  实测定位为**受限执行环境里管道创建被拒**（`PermissionError: [WinError 5]`）——
  `collect_structural` 用 `subprocess.run(capture_output=True)` 跑 `verify_references.py`。
  修法：`_run` 在管道被拒时**回退到文件重定向**（输出落 `tempfile` 再读回），
  于是容量判据在面板环境下**照常评估、不降级**；连回退也失败才如实报"结构侧采集失败 + 容量判据未被评估"。
  同轮把降级计数改为**复用 `verify_references.count_entries`**（原先自己写了一份 rglob 规则，
  漏掉 `references/<type>/<family>/x.yaml` 嵌套层，得到 127 而权威是 130——避免漂移的办法不是
  对齐两份规则，是只留一份）。回归里两个场景都钉住（回退成功 → 不降级；回退也失败 → 如实降级）。
- 2026-09 · 指标 tab 四轮（自诊断）：修掉三处"失败时不给线索"的缺陷——
  ①`resolveCwd()` 拿不到 `session.header.cwd` 时返回 `undefined`，而
  `shell.resolve({workdir: undefined})` **不报错**（退到默认目录），于是
  `python scripts/metrics_health.py` 找不到文件、Python 抛异常，面板上只剩一截
  **被 `slice(0,400)` 截掉异常类型**的 traceback，无从定位；现在：工作区解析带兜底
  （会话拿不到就扫已知会话取第一个带 cwd 的）、没有工作区就**不发起注定失败的命令**并说清缺口。
  ②体检失败的错误串改为带**执行上下文**（解释器 / 工作目录 / 命令 / 退出码）+ stderr 的**尾部**
  （traceback 的结论在最后几行，不在头部）。
  ③`metrics_health.py` 的 `collect_structural` 会对脚本整体抛错——异常冒到模块级 →
  **连容量越界这种最要命的信号一起没了**；现在走 `collect_structural_safe()` 防御包装。
  回归：`panel_render_check.js` 从**真实源文件**抽取 `runMetricsHealth`/`shellFail` 配桩运行。
- 2026-09 · 指标 tab 三轮：`--check` 三态接进首屏（判据覆盖面 + 体检器失效横幅）+ 容量历史趋势条。
  同轮修掉体检器两处假绿：`load_yaml` 把解析异常吞成空文档、`--check` 只有 0/1 两态。
- 2026-09 · 指标 tab 二轮：闭环判决（判据进首屏）+ 逐格容量 + 不可解读标记 + 新鲜度/drift。
  同轮修掉 `scripts/metrics_health.py` 里 `collect_structural` 的 tuple 解包 bug——
  它让**容量越界判据从来没生效过**（`structural.get` 抛 AttributeError 被 except 吞掉）。
- 2026-09-01：以运行验证版本重新沉淀（等价原 pkg-48）。此前沉淀因改成 ESM 形态导致加载失败，废弃重建。
