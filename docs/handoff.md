# 跨机交接（把一单诊断交到另一台机器继续）

一次诊断常常不是在同一台机器上做完的：外网机器上做过路由、验证与一部分排查，真正的大日志在内网。
这套机制让那一单**带着状态**过去，而不是靠人读报告转述。

分工一句话：**接管与落位是脚本的机械动作，恢复现场与继续定位是 `/skill:resume-diagnosis` 的动作**。
所以交接包不试图"读懂"这次诊断，它只保证两件事——该在的东西都在，不在的东西被点名。

## 两个投影，一份内容

| 形态 | 走什么通道 | 带什么 |
|---|---|---|
| `handoff-<session_id>.zip` | 文件通道（盘中转、附件） | 证据原件全带，压缩后通常比原文小一个量级 |
| `handoff-<session_id>.md` | 只认文本的通道（邮件正文、IM、剪贴板） | 简报 + 交接单 + trace 全文 + 报告全文 + 体积允许的证据原文 |

两份都由同一份源生成，不存在"哪份是最新的"问题。md 投影里**显式列出没带进来的文件**（超过内联上限的、
总量超限的）——不列的话接手方会把不完整的现场当成完整现场。

## 包内布局：`traces/` 的子集

```
<session_id>.yaml              本次诊断的 trace
<session_id>.report.md         人读定位报告（有则带）
evidence/<session_id>/**       证据原件
handoff/<session_id>.yaml      交接单（机器可读）
handoff/<session_id>.README.txt  给人看的一页说明（接手命令就在里面）
```

相对 `traces/` 是这个布局的全部约定，**故意不发明新结构**：于是导入退化成"落位"，
`resume-diagnosis`、诊断面板、`trace_metrics.py` 全都零改动就能看见这一单（它们只认这个布局）。
若换成 `packages/<sid>/…` 之类的新结构，就得改四处读取端才认得。

元数据放 `handoff/` 子目录也有一条具体理由：`traces/` 的会话发现是**非递归**的 glob `*.yaml`
（面板与 `trace_metrics.py` 都是），所以 `handoff/`、`evidence/` 不会被误读成一单会话。
交接单要是直接放 `traces/<sid>.handoff.yaml`，面板会把它当成一单没有轨迹的会话显示出来。

## 交接单 `handoff/<session_id>.yaml`

| 字段 | 含义 |
|---|---|
| `schema` | `ascend-sleuth-handoff/1`；导入侧按前缀校验，不认就不落位 |
| `session_id` | 这一单的 id（导入侧用它判同名冲突） |
| `exported_at` | 导出时刻。与 `session_id` 一起构成"这份包"的指纹，用于识别重复落位 |
| `origin` | 来源主机名、检出路径、知识库版本 `kb_rev` 及其来源（`trace` 或 `current-checkout`） |
| `intent` / `intent_source` | 交接意图：`continue`（继续定位）/ `verify`（复核结论）/ `escalate`（转上游）；标了是人指定还是按 `status` 推导 |
| `intent_note` | 人手写的一句话（为什么带出去、接手方先看什么） |
| `session` | 上家那一单的状态快照：`status`、`current_step`、`summary`、`active_case`、`excluded_cases`、框架/平台/类别 |
| `needs` | 接手方该先问什么：由 trace 各事件的 `evidence.missing` 与顶层 `last_action` 投影而来 |
| `contents` | 包内清单（路径/字节/类型）、总字节、**未纳入清单 `omitted`（含原因）**、报告文件名 |
| `src_refs` | 这次读过哪些源码（`org/repo@ref` 与引用到的文件）；源码缓存是本地件，接收侧要自己取 |
| `redaction` | `none` / `raw-evidence` / `redacted` 与说明 |
| `imported` | 导入侧落位后追加：导入时刻、落位处、是否改名、导入时的知识库版本与是否匹配、来源指纹 |

`contents.files` 里交接单自身的 `bytes` 是 `null`：写它的时候还不知道它多大，填一个数必然是错的。

## 产出侧

```
python3 scripts/export_trace.py <session_id> [--intent continue|verify|escalate] [--note "…"]
python3 scripts/export_trace.py --list          # 看哪些会话可以导出
```

产出落在 `<traces>/exports/`：`<session_id>/`（包内树）、`handoff-<session_id>.zip`、
`handoff-<session_id>.md`。`traces/exports/` 也是非递归 glob 看不见的目录，不污染会话列表。

体积策略默认单文件 20 MB、证据总量 200 MB，超限的文件进 `omitted` 并在屏幕上列出来（`--include-all` 关掉上限）。
默认值不是判据，是防呆——真要在通道里传大包，按你们的通道容量调参数，或者接受"这些文件另行索取"。

退出码：`0` 产出成功；`2` 找不到会话或参数不合法；`3` 写盘失败。

## 接收侧

```
python3 scripts/import_trace.py <包.zip | 包.md | 包目录>
python3 scripts/import_trace.py <包> --dry-run     # 只校验，不落位
```

它按顺序做四件事，然后打印一屏接手简报：

1. **校验**：交接单 `schema` 认得、trace 能解析、交接单与 trace 的 `session_id` 一致。不一致就拒收——
   包坏了比包不完整更危险，落位一份自相矛盾的 trace 会污染后续所有归因。
2. **点出缺件**：分三类说清，不合并成一句"缺文件"——trace 引用了但包内清单里也没有（上家就没打进包）、
   清单里有但包里没有（传输丢件）、单文件 md 投影未内联（体积上限，需要 zip）。
3. **落位**：按包内布局写进 `traces/`。同名冲突时不覆盖、也不自动合并，落成 `<session_id>-imported-<n>`，
   并把 trace 内部的 `session_id`、`evidence.files` 路径、`report_file` 一起改写（不改写就会指向不存在的文件）。
   同一份包重复接手（`exported_at` 与源 `session_id` 都对上）不重复落位——重复落位会在 `traces/` 里留下
   两单一模一样的记录，给误诊归因和指标添噪声。
4. **比对知识库版本**：与交接单的 `origin.kb_rev` 比本机检出 HEAD，得到一致 / 不一致 / 上家未记录三态。
   不一致时把后果讲出来：`excluded_cases` 里的 id 可能不存在、候选排序可能不同、甚至那条 case 当时还没沉淀。
   这是提示不是阻塞——拦下来只会让人绕过它。

退出码：`0` 已落位（含"重复导入，未重复落位"）；`2` 包不合法；`3` 落位写盘失败；`4` 同名冲突且指定了 `--no-rename`。

## 接手方怎么用

落位之后是 `/skill:resume-diagnosis` 的常规续接，唯一多出来的一步是读 `traces/handoff/<session_id>.yaml`
（外来单才有）：交接意图、上家的待补材料、缺件清单。它的取值口径写在 `skills/resume-diagnosis/SKILL.md`。

面板上，问题卡片展开后有「导出交接包」——它是**直接动作**（面板调脚本、就地回报路径与清单），
与卡片上其余按钮"生成一条复制到对话的指令"不同：导出只读 trace 与证据，落一个 `traces/exports/` 下的
运行时件，不动知识库、不改 trace 内容，删掉目录即撤销。同一行还有交接意图的三选一（默认"继续定位"）。

## 强度与边界

- **机械保证**：包内布局、`session_id` 一致性、同名冲突改名、重复落位识别、版本比对三态、
  缺件三类分述、md 投影的未内联清单、md 通道的截断检测（声明字节与实到字节差得多时点名，
  截断的证据比没有证据更危险——它看起来是齐的）。`python3 scripts/check_handoff.py` 用合成夹具把
  zip 通道、md 通道、改名、重复、`--no-rename`、非法包、版本一致/不一致、全新机器（`traces/` 还不存在）、
  文件名与 `session_id` 不同的历史单逐条真跑，并另跑一段本机真 trace 的端到端
  （CI 检出里没有 `traces/`，那一段会如实跳过）。判据是末行「全部通过」，不是断言条数。
  **该检查目前不进 CI**：它是一次性写就的往返自检，还没有"两次以上真实复发"的记录；
  进 CI 的判据见 `CLAUDE.md` 的「Check-admission criterion」。
- **约定，不是硬门**：`redaction` 只是声明。导出不会替你做脱敏，也不会阻止你把含原始客户日志的包发出去——
  真正的闸门在你们的数据通道上，不是面板或脚本。外→内一般无碍；**内→外**是把客户现场日志与源码摘录带出去，
  按你们的规则处理。方向由人判断，交接单只记录当时的状态。
- **未做的**：跨机双向同步（这套是单向摆渡用的；两台机器在同一张网里能共享同一个 git 或目录时，
  正确做法是共享 `traces/`，不是打包）、交接包历史的集中归档（`traces/exports/` 是本地运行时件，
  按需清理）、自动合并两边各开一单的同一问题（那是判断，交人）。
