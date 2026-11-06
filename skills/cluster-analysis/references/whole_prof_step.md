# 无分步 prof：整段作为一个汇总 step

当实际摘要中没有有效 step 标识时，整个提供的 prof 按每 rank 一个汇总 step 分析。共享入口是 `scripts/lib/analysis_scope.py::load_steps`，detector、Advisor、集群库、compare 和 Insight 均使用该入口。

## 判定与标识

- TEXT `Step` 为空/空白/NULL/None/NaN 等，DB StepTraceTime 的 `step` 为 NULL/空值：整段合并为 `Step='prof'`，`analysis_scope='whole_prof'`、`synthetic_step=true`。
- 存在有效原始 step 标识时保留分步，不把多个有效 step 合并。摘要未提供编号时，真实 `STEP_TIME` 或 trace `ProfilerStep#` 边界仍作为分步证据，按对应范围推导指标；不会把整段摘要任意分摊到各 step。原始 `0` 是有效编号，不能仅因数值为 0 当作无 step。
- 同一卡的多行无 step 摘要聚合为一行；数值按源摘要求和，未知/无效项保持未知。这是摘要聚合，不宣称对原始事件重新计算了完全相同的上游指标。
- `prof` 只用于派生结果，原始 CSV/DB 不改写。保留 `_raw_step_ids`、来源、参与摘要行数、边界来源和指标定义。
- `coverage.unique_step_count`/rank-step 统计计入 `prof`；`known_step_count` 只统计有效原始标识；`synthetic_step_ranks` 列出使用整段汇总的卡。`db_step_scope`/`db_window_count` 仍是原始 DB 的窗口事实，不是最终分析口径。

## 无摘要时

优先使用主 DB 的 SESSION_TIME_INFO 范围；没有声明会话范围时，合并可读 DB 事件、kernel CSV 与 trace 的观察起止，trace 使用流式扫描。能确定范围则建立一个整段 prof step；没有可靠范围或可读内容时明确报数据不足，不能从目录名字或空文件生成时间。

如果 DB 包含已识别的 ENUM_OVERLAP_ANALYSIS_TYPE 与 OVERLAP_ANALYSIS，可按类型、范围裁剪、区间并集推导计算/通信/Free。保留 `derived_interval_union` 来源定义；它不与 upstream reported 摘要无条件等价。只有起止而缺事件指标时，仅 Stage 有依据，其他项未知，Advisor 不作“正常”判断。

采集边界和上游摘要 Stage 分开：多个摘要行的 Stage 取源值之和；定位范围取整段起止，中间未采集间隙不凭空补成 Free。

## 下游与报告

- cluster 通信耗时、带宽、矩阵行都写入 `step='prof'`，保留原通信实例名与组；合并窗口时保留多条事实，不因改 step 键覆盖同名项。
- compare 只比较相同分析口径；整段与真实分步不混作同一种比较。`prof` 同名只表示各卡整体汇总，不证明采集时窗、请求数或负载一致。
- Whole-prof 数据运行共享内置流水线，避免原生 CLI 对空 step 的版本差异覆盖此规则；有真实 step 的原生优先策略不变。
- P0 在独立中间件目录写 `analysis_scope_cache.json`，后续阶段复用同一分步结果。按源文件大小/修改时间（含 WAL）及小文件内容校验；源发生变化时重新识别。原始大 trace 保持流式读取，避免每个分析阶段再次扫描分步标记。
- 报告明确显示“整个 prof 作为一个汇总 step”；可展示窗口计算、通信、Free 与热点，`prof` 不解释为一次训练迭代或一个推理请求。请求吞吐、TTFT 等需要额外请求/token 证据。
- 缺少比较所需的 Stage/未掩盖通信时，compare 记 unsupported；关键指标未知时不生成无法保留 unknown 的 vendor 集群子报告。已有窗口/事件结果继续交付，主报告说明限制；依赖未知 Overlapped/Communication 的掩盖比例 recipe 也记 unsupported。
- Insight 将卡级事件归入整个 prof 的范围；无法确认范围的事件定位保持来源限制。所有精确时间仍按原有整数 ns 口径。

## 验证

`tests/test_whole_prof.py` 覆盖 TEXT 空 Step、DB NULL-step 多行、真实编号保留、analysis-only、无摘要事件并集、Insight 归属、通信多窗口行保留、缺指标诊断与分步缓存复用/失效。旧 DB 回归已按新规则更新分析层期望；原始 DB NULL/窗口读取契约保留。
