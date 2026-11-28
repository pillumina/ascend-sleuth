# DB-only 适配契约（references/db_support.md）

实际分析先经 `scripts/lib/analysis_scope.py` 统一口径：无分步时整段按每卡一个 `prof` step。原始 DB NULL-step/窗口事实仍由下述 reader 保留；详见 [whole_prof_step.md](whole_prof_step.md)。

TEXT 导出缺失时，fallback 链路经共享适配层 `scripts/lib/prof_data.py` 直接读取 rank 级
`analysis.db` 与主 profiler DB。本文是该适配的单一事实来源：已验证 schema、单位、scope
语义、来源标记与当前限制。所有脚本禁止绕过 prof_data 自行实现 DB 读取 SQL。

## 1. 适配范围（当前已实现）

| 能力 | TEXT 来源 | DB 来源 | 消费阶段 |
|---|---|---|---|
| step/window 摘要 | `step_trace_time.csv` | `analysis.db::StepTraceTime` | P1 advisor、P2 cluster、P4 compare、P6a |
| 通信汇总 | `communication.json` | `analysis.db::CommAnalyzerTime` | P1 advisor、P4 compare、P6a |
| 通信带宽/矩阵 | `communication*.json` | `analysis.db::CommAnalyzerBandwidth/Matrix` | P2 cluster |
| rank/device 映射 | 目录名/profiler_info | 主 DB `RANK_DEVICE_MAP`、`StepTraceTime.deviceId` | P0 detect、P2 cluster |
| 主机信息 | 目录名推断 | 主 DB `HOST_INFO` | P2 cluster |
| 会话起止 | — | 主 DB `SESSION_TIME_INFO` | P6a |
| 计算热点 | `kernel_details.csv`/`op_statistic.csv` | 主 DB `TASK⋈COMPUTE_TASK_INFO⋈STRING_IDS`（流式聚合） | P6a |
| 泳道 | `trace_view.json`/`kernel_details.csv` | **不支持**（记 unsupported，DB-only 无流式泳道证据） | P6 |

不依赖原始采集目录（`PROF_*/` 下的原始二进制），不需要重导出 TEXT。

## 2. 已验证 schema（真实样本）

来源：`db/ddp_level1_20261012_033349`（4 rank，6 有效 step）、`db/qwen3_8b_tp4_100`
（4 rank，1 个 NULL-step 采集窗）。样本只证明该版本行为，不构成全集承诺。

- `analysis.db::StepTraceTime`：列 `deviceId, step, computing,
  communication_not_overlapped, overlapped, communication, free, stage, bubble,
  communication_not_overlapped_and_exclude_receive, preparing`。**单位 us**（与 CSV 同口径）。
  旧 schema 无 `deviceId` 列（列存在性按表探测，不按列号读取）。
- `analysis.db::CommAnalyzer{Time,Bandwidth,Matrix}`：时间列**单位 ms**，transit_size 单位
  MB，bandwidth 单位 GB/s（由 transit_size/transit_time/bandwidth 自洽关系实测验证）。
  `step` 列为 `'stepN'` 形式或常量 `'step'`，**不能当训练 step id**（见 §3）。
- 主 DB（`ascend_pytorch_profiler_*.db`）：`RANK_DEVICE_MAP(rankId, deviceId)`、
  `HOST_INFO(hostUid, hostName)`、`SESSION_TIME_INFO(startTimeNs, endTimeNs)`、
  `STEP_TIME(id, startNs, endNs)`（Qwen 样本无 STEP_TIME 表）、`TASK`、
  `COMPUTE_TASK_INFO`、`STRING_IDS`、`OVERLAP_ANALYSIS`、`COMMUNICATION_OP`。
- WAL：DDP 主 DB 带 `-wal/-shm`。**纪律：带 `-wal` 的库用 `mode=ro` 打开（可读已提交
  数据）；仅对确认无 WAL 的静态库用 `immutable=1`**。禁止对含 WAL 的库用 immutable
  （会漏读已提交行）。

## 3. step 与采集窗（capture window）语义

- `StepTraceTime.step` 非 NULL → `scope_kind='step'`，step_id 为原始标识。
- 原始 reader 中 `step` 为 NULL → `scope_kind='capture_window'`，保留采集窗来源。
  分析入口中，没有有效原始 step 时将所有这类行合为一个 `prof` 汇总 step；
  `w1..wN` 仅是原始窗口身份或混合数据的未编号行，不作为纯无分步输入的分析标签。
- 恰有一个采集窗且存在 `SESSION_TIME_INFO` 时，窗口边界 = 会话起止；多窗口且无
  `STEP_TIME` 时不猜测边界，事件窗口归属记为未知并输出限制说明。
- `CommAnalyzerTime.step` 的映射：`'stepN'` → `'N'`（与 StepTraceTime step id 对齐）；
  无法解析且恰有一个采集窗 → 该窗口标签；否则 `'unknown'`，计数写入 status_info，
  不静默丢行。
- 采集窗口径下禁止输出迭代吞吐、按 step 的比较结论；比较结果在
  `compare_analysis_result.json` 以 `step_scope='whole_prof'`（无分步数据） 声明。

## 4. 派生产物来源标记（可追溯性）

`cluster_fallback` 建库时写入：

- `ClusterBaseInfo` 新增键：`step_source`、`step_id_semantics`
  （`= capture window ...` 说明）、`device_map_source`、`host_source`、
  `communication_source`。
- `status_info`：`null_metric_cells_converted_to_zero`（DB 摘要 NULL 指标按 0 参与
  派生统计的单元格数）、`comm_rows_with_unmapped_step`。
- `RankDeviceMap.deviceId`：真实 device 优先（rank≠device），缺失时回退 rank，
  回退事实记录在 `device_map_source='rank_as_device_fallback'`。

advisor/compare 输出在 md/json 中标注 `source`/`scope`/`step_source`；P6a 计算证据
带 `compute_source`（`kernel_details.csv` 或 `main_db:TASK+COMPUTE_TASK_INFO`，
后者通信算子按 `COMM_NAME_PATTERN` 名称启发过滤，属候选证据）。

## 5. 单位速查

| 数据 | 单位 |
|---|---|
| StepTraceTime 全部指标 | us |
| CommAnalyzerTime elapse/transit/wait/sync/idle | ms |
| CommAnalyzerBandwidth/Matrix transit_size | MB |
| bandwidth | GB/s |
| 主 DB 事件 startNs/endNs、SESSION_TIME_INFO、STEP_TIME | ns |

## 6. 当前限制

1. 泳道（P6）与依赖 `trace_view.json`/`operator_details.csv` 的 recipe 在 DB-only 下
   unsupported（标注原因，不算失败）。
2. P6a 的 PMU 流水线比例在 DB 路径不可用（`TASK_PMU_INFO` 未接入）；计算热点为
   TASK 聚合候选证据。
3. 双导出（同目录 TEXT+DB）并存时仍按 TEXT 优先路由；空 Step 与 NULL-step 均进入整段单 step 规则；TEXT/DB 同名
   指标存在实测口径差异（官方双导出 115/369 项超容差），不得混拼为单一指标。
4. 集群输出件仍生成于 prof 根目录 `cluster_analysis_output/`（既有目录契约），
   属派生产物，以 ClusterBaseInfo/status_info 来源键区分于官方原生输出
   （`gen_by='npu-perf-analyzer cluster_fallback'`）。
5. 多会话、repeat、多 device/进程、MindSpore/纯 msprof 采集等场景未由现有样本覆盖；
   覆盖声明以样本+版本为准。
