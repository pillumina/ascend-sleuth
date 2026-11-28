# analyzers（仓库内置分析器）

当前有 7 个分析器通过 Python 命令调用。环境快照支持单份版本配套与多份配置漂移，单卡 Prof 对比提供 Host/Device 热点。`vllm-ascend-tuning` 提供调优说明和配置模板。单卡性能对比的读法见[性能基准对照](../../references/methodologies/performance-baseline-comparison-reading.yaml)。

上游来源、固定提交与许可状态见 [NOTICE.md](NOTICE.md) 和 [PROVENANCE.yaml](PROVENANCE.yaml)。客户现场采集见 [collectors](../collectors/README.md)。

## 目录

```text
scripts/analyzers/
├── cli.py                 查看状态、启停和运行分析器
├── registry.py            分析器清单与输入形态
├── _lib.py                开关、路径校验、子进程、result.json
└── <name>/                适配器、分析脚本、模板和所需参考资料
```

## 启用分析器

分析器默认关闭。`status` 会列出本机可用的分析器，并在关闭时打印启用命令。

```bash
python3 scripts/analyzers/cli.py status
python3 scripts/analyzers/cli.py enable
python3 scripts/analyzers/cli.py disable
```

`enable` 和 `disable` 保存本机设置。同一克隆的各 worktree 共用主检出的 `.local/analyzers.enabled`。Windows 用 `python` 执行相同命令。

自动化可以用环境变量 `SLEUTH_ANALYZERS` 覆盖本机设置。做启用对照时，开启组设为 `on`，关闭组设为 `off`。关闭时，`cli.py run` 和各 `run.py` 返回退出码 `3`。

```bash
# 验证关闭：退出码 3，且输出目录不创建
SLEUTH_ANALYZERS=off python3 scripts/analyzers/cli.py run ibmc_analyzer --inputs /data/bmc/dump_info --out-dir /tmp/should-not-exist
```

## 直接调用

```bash
python3 scripts/analyzers/cli.py status            # 开关与安装状态（人读）
python3 scripts/analyzers/cli.py status --json     # 同上，给机器读
python3 scripts/analyzers/cli.py list --json       # 仓库登记的分析器与输入形态（安装状态看 status）
python3 scripts/analyzers/cli.py run <name> --inputs "<绝对路径 1>
<绝对路径 2>" --session-id <session_id> --purpose "<一句话>"
```

- `--inputs` 只收本机绝对路径；多个用换行分隔，或传 JSON 数组字符串。
- `--out-dir` 可省略；省略时落到主检出的 `traces/evidence/<session_id>/tool-runs/<call_id>/`。
- 两组数据比对时按 **A（基准）、B（对比）** 顺序传。
- 单个分析器也可直接跑：`python3 scripts/analyzers/<name>/run.py --inputs ... --out-dir ...`。
- 输出统一转 UTF-8：Windows 的非 UTF-8 控制台代码页（如 cp1252）下中文摘要不会抛 UnicodeEncodeError。

### 每个分析器的命令

| 分析器 | 输入 | 命令 |
|---|---|---|
| `ibmc_analyzer` | 一个或多个 `dump_info` 目录、机器目录或 iBMC 一键收集包 | `python3 scripts/analyzers/cli.py run ibmc_analyzer --inputs <路径>` |
| `issue-analyzer` | 一个日志目录，或一个/多个日志文件 | `python3 scripts/analyzers/cli.py run issue-analyzer --inputs <路径>` |
| `ascend-dump-analyzer` | 一份环境快照 JSON，或至少两份含 JSON 内容的快照 | `python3 scripts/analyzers/cli.py run ascend-dump-analyzer --inputs <路径>` |
| `cluster-analysis` | 一份 prof 目录或 `cluster_analysis_output` | `python3 scripts/analyzers/cli.py run cluster-analysis --inputs <prof 目录>` |
| `cluster-compare` | 两份集群数据目录（DB 或 TEXT） | `python3 scripts/analyzers/cli.py run cluster-compare --inputs "<A>\n<B>"` |
| `prof-compare` | 两份单卡 Prof（A 基准、B 对比）。混合对比时 A 为 GPU trace，B 为 NPU | `python3 scripts/analyzers/cli.py run prof-compare --inputs "<A>\n<B>"` |
| `cpu-host-performance` | 一份 ftrace/Host 采集包、目录、trace 文本或 Chrome JSON | `python3 scripts/analyzers/cli.py run cpu-host-performance --inputs <trace>` |

`vllm-ascend-tuning` 的上游内容是提示词、调优文档和配置模板。调优时从 [上游说明](https://github.com/hu669293657/skills/tree/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/vllm-ascend-tuning) 进入，命令和参数按部署版本核对。

`prof-compare` 只保留上游的标准库实现：读单卡 NPU 主库或文本导出，对比 Host 算子与 Device kernel 热点，输出耗时差与单次执行序列。上游完整的 msprof-analyze 直比与 xlsx 报告需要在线安装 `msprof-analyze` 和第三方 `openpyxl`，本仓不调用；需要那条路径时按客户环境的工具版本手工执行。

从开发分支试跑 `diagnose` 时，运行 `python3 scripts/build_ref_summary_index.py` 和 `python3 scripts/build_procedure_index.py`，让诊断能查到本分支新增的工具说明和判读方法。主干会自动生成索引。

## 结果

每次调用在输出目录写：

| 文件 | 内容 |
|---|---|
| `result.json` | `status` / `summary` / `findings` / `missing` / `artifacts` / `analyzer_version` / `duration_ms` 等；iBMC 另带 `suppressed` / `observations` / `reconciled` |
| `invocation.json` | 分析器、版本、输入、开关、Python、开始时间 |
| `vendor.log` | 上游命令的 stdout/stderr（图、大段日志不进入上下文） |
| 上游报告 | HTML、Markdown、JSON 或兼容性结果，路径登记在 `result.json` 的 `artifacts` |

`suppressed` 是适配层从发现里移出的判定，每条带 `reason` 与原因说明，原始数值仍留在上游 JSON 产物里。它不属于 `findings`：读到它说明「这条判定未被采纳」，原因看 `reason`（缺证据，或上游按固定 8 卡判出的数量结论被适配层按机型预期重算），不是「这里有问题」。当前只有 `ibmc_analyzer` 用它：`npu_info` 缺失、读取失败、内容无法识别、只有表头或采集报错时，上游会把 NPU 在位判成数量 0（疑似丢卡），适配层改为未知并抑制该条；解析成功时按机型登记的预期卡数重新核对，未登记机型只报数量、不做丢卡判定，上游按固定 8 卡判出的数量结论不直接采用。

`observations` 是低优先级项（工具判 P2/P3、状态不是 ok 的传感器读数，以及上游判定未复核的说明）。P2/P3 与传感器项带原始值、单位、等级与证据位置；上游判定说明带原因与证据位置。P0/P1/P2/P3 是工具自身的优先级（P0 最高），不是诊断的 severity。它不是结论也不是噪音：`findings` 收 P0/P1 与「判定 正常」这类总体结论，P2 若直接丢掉会让「温度越限」这类项从 Agent 眼前消失；但直接塞进 `findings` 又会把工具关注项说成已证实的异常。传感器读数旁的阈值归属未经核对，只在观察项里给数，不给判定。

`reconciled` 记录适配层补读过的证据（当前只有 ECC）：上游用 `encoding="utf-8"` 读 `npu_ecc_info.json`，带 BOM 的真实输入会抛异常并被吞成空，表现为「ECC 全 0」。适配层用 `utf-8-sig` 复读一次：读到非零计数就补进 `findings`，并把来源记进 `reconciled`；计数全 0 进 `observations`；读不出来写进 `missing`，不写成 0。

`status` 取 `ok` / `partial` / `blocked` / `failed`。成功判据是「上游进程正常结束 + 本次写出可读产物」，不是「目录里出现过文件」。

复用同一个输出目录时，适配器按本次子进程写出后的文件身份判定，不会沿用上一次的 `result`、报告或提取结果；上游明确标 `reused` 的缓存产物除外（summary 会注明）。

失败时在 `result.json` 写原因，旧产物不进本次 `artifacts`；iBMC 上游会先清理旧的机器 JSON，保留范围以 `artifacts` 为准。失败时 `data_needed` 给出可执行的材料要求：缺输入、坏输入与上游失败给最小输入形态，超时给裁剪建议；其余失败为空。`missing` 是本次缺的具体项。

`partial` 把本次未分析的材料写入 `missing`，`data_needed` 保持为空。报告按实际覆盖范围引用结果。

开关未开时不会创建 `result.json`；子进程起不来或适配器崩溃时 `data_needed` 为空。

## 依赖

当前分析器用 Python 3.8+ 标准库生成主要结果。集群分析可附带生成工作簿，集群对比从已有集群结果开始；`prof-compare` 的 Host/Device 热点对比只用标准库，不需要 `msprof-analyze` 或 `openpyxl`。

## 客户现场采集（不在自动调用范围）

分析路径本身是离线的：适配器只读已有输入，不调用采集脚本。没有现成数据时返回缺路径/缺数据，由工程师通过 [collectors](../collectors/README.md) 选择脚本交给客户现场执行；采集不在自动调用图里。

`cpu-host-performance` 生成的 `cpu_binder_simple.py` 是建议脚本，本次不执行；执行前需人工核对 PID、线程身份与回退。

## 测试

```bash
python3 -m unittest tests.test_analyzers tests.test_collectors -v
```

测试用临时目录里的合成输入，覆盖开关、坏路径、压缩包路径校验、7 个分析器的报告输出与采集器打包。环境快照还验证了单份版本配套、多份比对与部分成功时的差异报告。

## 已知限制

- `cluster-analysis` 在多卡模式下沿用上游行为，会在 prof 根目录写 `cluster_analysis_output/`；需要输入只读时，先把 prof 目录复制到工作区。
- `cluster-compare` 的 HTML 模板引用 CDN 图表脚本；离线打开时图表可能不显示，表格与 Markdown 报告仍可读。
- `prof-compare` 只做单卡 Host/Device 热点对比，不生成上游的 xlsx 综合报告；集群多卡比对用 `cluster-compare`。
- `ascend-dump-analyzer` 单份只按离线配套矩阵核对；矩阵未覆盖的版本返回 `unknown` 并写进 `missing`，不推断兼容性。
- 复用输出目录时，适配器用文件的修改时间与大小识别本次产物；FAT/exFAT/SMB 等粗粒度时间戳的文件系统可能误判，连续复跑建议每次新建输出目录。
- iBMC tar 包含符号链接、硬链接或设备文件时整包拒绝，zip 只拒绝符号链接；拒绝前不把任何成员写进输出目录，需要处理这类包时先重新打包。
- iBMC 每次运行会清空输出目录下的 `_extracted/`（解包中间产物）；多个进程不要共用同一个 `--out-dir`。
