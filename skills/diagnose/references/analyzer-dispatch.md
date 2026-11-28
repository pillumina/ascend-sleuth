# Analyzer Dispatch（整包数据 → 仓库内置分析器）

**何时读**：步骤 5 深度排查，或步骤 3 候选验证缺一个整包里就有的具体指标，而工程师已经交来整包数据时。先查可用分析器和本机启用状态。

需要从 Prof 目录、`dump_info`、日志包或 ftrace 采集包提取数据时，按下面的表选分析器。诊断 agent 核对证据，给出判断与处置建议。

## 先看开关

```bash
python3 scripts/analyzers/cli.py status
python3 scripts/analyzers/cli.py list --json
```

分析器默认关闭。已有适合的本地数据，且 `status` 显示所需分析器已安装但当前关闭时，告诉工程师可以用 `status` 提示的 `enable` 命令开启，同时继续用现有证据排查。工程师明确要求开启时，才代为执行。启用后可在本机后续会话使用。

`status --json` 的 `enable_command` 适用于当前平台。`source` 会说明设置来源。已有 `SLEUTH_ANALYZERS` 环境变量时，以该变量为准。

`list --json` 给出仓库登记的分析器、各自收什么输入与用途；这台机器上装没装看 `status --json` 的 `installed`。下面的选择表按数据形态选，两者对不上时以 `status` 的 `installed` 为准（没装的分析器不要按表硬调）。

## 按数据形态选

| 已确认的数据形态 | 分析器 | 不要用它的情形 |
|---|---|---|
| 一份 Prof 采集（单卡或多卡），或一份集群输出 | `cluster-analysis` | 两次集群结果的前后对照用 `cluster-compare` |
| 两份集群采集或集群结果，各含多 rank / 集群 DB 或 TEXT | `cluster-compare` | 先明确 A/B、同负载、rank/step/window；不可比时只交描述差异 |
| 两份单卡 Prof（NPU 主库或文本导出，或 A 为 GPU trace、B 为 NPU） | `prof-compare` | 集群多卡用 `cluster-compare` |
| `dump_info/` 或 iBMC 一键收集包 | `ibmc_analyzer` | 不接 OS 日志；按内容判断，不按压缩包名 |
| 一份环境快照 JSON，或至少两份含 JSON 内容的环境快照 | `ascend-dump-analyzer` | 单份核对采集环境的版本配套，至少两份可比对配置漂移 |
| plog / slog / 框架日志 / dmesg 等日志 | `issue-analyzer` | 日志归档先解包。时间窗缺失时只扫描，不推断跨机先后 |
| ftrace / Host 采集包，要调度证据 | `cpu-host-performance` | 只有环境 JSON 时不给调度根因；采集与绑核不在自动调用范围 |

数据形态判不出来就问一句，别猜。混在一个包里的，只选当前缺口那一个。

已有数据不够、需要客户现场采集时，不在本节拼命令：按 `collector-dispatch.md` 推荐脚本，采集结果回来后仍走本节的分析器。

有基准和对比两侧的性能读数时，按 `performance-baseline-comparison-reading` 核对可比性、数值和单位。该读法可直接用于工程师给出的读数。

## 怎么调

```bash
python3 scripts/analyzers/cli.py run <分析器名> \
  --inputs "<绝对路径 1>
<绝对路径 2>" \
  --session-id <当前 trace 的 session_id> \
  --purpose "<这次要回答的问题，一句话>"
```

- `--inputs` 只收本机绝对路径：附件先落盘再传路径，不接受 URL。相对路径和不存在会被直接拒，不进入分析。
- `cluster-analysis` 多卡模式会在输入目录写 `cluster_analysis_output/`。先把多卡 Prof 根目录复制到本次运行的工作区，再传副本路径。无法取得副本时，走原诊断流程。
- 多个路径用换行分隔，也可以传 JSON 数组字符串。
- 两组数据比对时，**按 A、B 顺序**传（A 是基准，B 是对比）；`--ab` 只作记录。
- `--out-dir` 可省略；省略时落到主检出的 `traces/evidence/<session_id>/tool-runs/<call_id>/`。
- 也可以直接跑单个适配器：`python3 scripts/analyzers/<分析器名>/run.py --help`。它们和 CLI 共用同一开关与结果格式。

## 结果怎么读

命令会打印四样：状态、≤500 字摘要、≤5 条关键发现、结构化结果路径；末行 `RESULT_JSON=<路径>` 给机器读。

- 摘要里的**事实**可以直接进 trace 与报告；分析器给出的**候选解释**会标 `kind: candidate`，要标「未验证」，不能当根因。
- `findings` 只收有证据的结论。`observations` 是低优先级观察（工具判 P2/P3，工具优先级里 P0 最高、P3 最低；传感器非 ok 读数，以及上游判定未复核的说明）：P2/P3 与传感器项带原始值与等级，上游判定说明带原因与证据位置。**不是结论，也不是噪音**——可以追问、可以写进报告的「待确认项」，但不能写成根因，遇到传感器读数时不要替它下「超限」判断（阈值词条仍在待审）。
- `suppressed` 是被移出发现的判定（带 `reason`）：读到它说明这条判定未被采纳，原因看 `reason`，不要当异常用；`reconciled` 是适配层补读过证据的地方（当前只有 ECC），说明上游漏读后本次已从原始文件补读。
- 完整结果在 `result.json` 的 `findings` / `observations` / `missing` / `artifacts` 里。**不要把 `result.json` 整份贴进上下文**——需要复核时按里面的证据位置去读原文。
- `artifacts` 是分析器自己写出的 HTML / Markdown 报告位置。给用户时直接给路径，**不要把报告内容读进上下文**；需要引用其中结论时，按 `result.json` 里对应的发现转写。
- 诊断 agent 评定严重程度，并给出处置建议与诊断报告。
- 出现新签名 → 回步骤 2/3 重判性质，不要就此定案。

## 失败与退化

进入适配器后的失败一律返回非零退出码，并在 `result.json` 写 `status` + `reason`，不抛异常、不重试。开关关闭更早：`cli.py run` 或适配器入口直接返回 3，不创建输出目录，也没有 `result.json`；按 stderr 的提示给 `enable` 命令。

| reason | 含义 | 动作 |
|---|---|---|
| `analyzer-disabled` | 分析器关闭（入口直接拒绝，没有 `result.json`） | 有匹配的本地材料时给出 `enable` 命令，继续用现有证据排查 |
| `no-python` | 子进程起不来（解释器缺失或不可执行） | 回原诊断流程；需要该工具时请工程师在预配环境检查 Python |
| `bad-input` / `no-input` | 路径或数据形态不对 | 纠正一次；仍不对就请工程师重给 |
| `timeout` | 超过预算（默认 600 s） | 请工程师按 rank / 时间窗裁剪后重给 |
| `analyzer-failed` | 上游入口非零退出 / 没生成结果 | 当真失败，记下来；不要重跑同一输入 |
| `analyzer-crashed` | 适配器捕获到未预期异常 | 当真失败，记下来；附 `detail` |
| `analyzer-not-installed` | 仓库内实现缺失 | 当它不存在；不要自己拼命令行 |

失败**不计入**「候选被排除」，也不能写成「没发现异常」。工具不在时整节跳过，诊断行为与没有它时一致。

## 缺数据时怎么问

`status` 是 `blocked` 或 `failed` 时先读 `result.json` 的 `data_needed`（开关关闭时没有 `result.json`，见上）。它为空表示不是缺数据（例如子进程起不来、分析器崩溃、实现缺失），不要向用户要材料；非空时把它翻成一句具体的话，只问缺的那一项。超时的 `data_needed` 是裁剪建议，按它请工程师缩数据：

| 分析器 | 要用户补的最小数据 |
|---|---|
| `issue-analyzer` | plog / slog / host / device / framework / dmesg 日志目录或文件 |
| `ascend-dump-analyzer` | 一份环境快照 JSON（看版本配套）；要判配置漂移时至少两份 |
| `prof-compare` | 两份单卡 Prof（A 基准、B 对比）。混合对比时 A 为 GPU trace，B 为 NPU |
| `cpu-host-performance` | ftrace / Host 采集包、解包目录、trace 文本或 Chrome JSON |
| `ibmc_analyzer` | `dump_info` 目录或 iBMC 一键收集包 |
| `cluster-analysis` | 一份 prof 目录，或 `cluster_analysis_output` |
| `cluster-compare` | 两份集群数据目录，各含 DB 或 TEXT |

没有现成数据时，按 `collector-dispatch.md` 看有没有对应的现场采集器；推荐后由工程师转客户执行。

`partial` 的 `missing` 列出本次未分析的材料。报告应写明结果覆盖范围。若缺项影响正在验证的判断，只补这一项。

## trace 记什么

复用现有 `run_check` 事件，不新增 action 词表：

```yaml
- {action: run_check, step: 5, check: analyzer_run, analyzer: <名字>, analyzer_version: <版本或 unknown>,
   verdict: hit|empty|blocked|failed, evidence: <result.json 路径>, reason: <一句话>}
```

`analyzer_version` 取 `result.json` 里的 `analyzer_version`；拿不到写 `unknown`，不要省略这个字段——版本与结论要能对上，否则下次结果变了分不清是数据变了还是实现变了。

结论被采纳时，在后续 `hit` 或 `output` 里写清用了哪一条发现；工具跑成功不等于诊断解决。

## 不做什么

- 不在诊断里 `pip install`、`apt install` 或下载第三方脚本。
- 不自动执行采集脚本、`cpu_trace_collect.sh`、`bind_cpu.sh`、`taskset` 或任何会改客户机器状态的命令。需要现场证据时按 `collector-dispatch.md` 推荐采集器，由工程师转客户执行。
- 不把分析器输出直接当根因；不把报告文件内容整份读进上下文。
