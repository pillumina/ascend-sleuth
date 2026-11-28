# Trace → Rank/线程 → NUMA → 执行 → 验证 → 回滚

本页说明完整 Skill 中的现场审计 CLI。它在目标主机发现对象，为 locality/partition 单独生成 `plan.json`，记录自身变更并验证业务指标。按服务器预算生成客户专用 `cpu_binder_simple.py` 与 `bind_design.json` 时，使用[客户生成指南](https://github.com/hu669293657/skills/blob/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/cpu-host-performance/references/customer_script.md)。定制容量预算另见[规划分支](https://github.com/hu669293657/skills/blob/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/cpu-host-performance/references/custom_binding.md)。这两项属于上游完整 Skill 的定制生成链，本仓不交付对应生成器；本页保留的现场审计入口可直接使用。

## 入口与环境

现场采集分发 `cpu_trace_collect.sh`，原生 Ascend Dump 使用宿主机的 `python3`。闭环执行需要把完整 Skill 目录复制到 Linux 宿主机，使用 Python 3.8+ 标准库。入口为 `python3 scripts/ascend_bind.py --help`。离线分析和业务 A/B 文件比较可在 Windows 执行。现场 discovery、apply、audit、rollback 支持 Linux。

此流程继承在用“通用绑核脚本”的显式拓扑与 ACL/release 识别思路，采用 v2 包的默认预览、全局设备池、journal 与读回思路；没有照搬固定 Main/ACL/Release 核数、按显存只选一个 PID、自动内存迁移或仅 TID 出生时间回滚。训练设计中的 Rank 和 DataLoader 进程树已经接入现场发现；启动训练的 rank wrapper 与模型业务指标采集仍由业务负责，本工具不启动训练或猜测业务日志格式。

## 一次完整实验

以下 PID 和路径必须替换为现场值。任务需保持相同 PID 代次；重启作业后重新采集和规划。将业务中的绑核控制交给本工具之前，先核验并关闭同一对象上的框架内置 binder；参数因框架版本而异，不自动修改框架配置。`disabled` 表示已关闭，`absent` 表示确认没有该控制器；未知时只能预览。

```bash
SKILL_DIR=/path/cpu-host-performance
JOB_PID=12345
CASE_DIR=$(mktemp -d /tmp/hostbind.XXXXXX)

# A：同负载稳定期，业务自行记录下述 before.json，多轮采样剔除热身。
sudo bash "$SKILL_DIR/scripts/cpu_trace_collect.sh" --duration 30 \
  --pid "$JOB_PID" --output "$CASE_DIR/before-capture"
python3 "$SKILL_DIR/analyzer/analyze_cpu_trace.py" "$CASE_DIR/before-capture" \
  --output-dir "$CASE_DIR/before-report"

# 只读：从 NPU 占卡表筛选 JOB_PID 及后代，发现占卡主进程、Rank 标签及主进程的全部线程。
python3 "$SKILL_DIR/scripts/ascend_bind.py" plan \
  --report-data "$CASE_DIR/before-report/report_data.json" --pid "$JOB_PID" \
  --framework-binding disabled --output "$CASE_DIR/plan.json"

# 只读执行预检；检查 plan.json 中 pools/actions/workers 及 warnings。
python3 "$SKILL_DIR/scripts/ascend_bind.py" apply \
  --plan "$CASE_DIR/plan.json" --state "$CASE_DIR/state.json"

# 显式执行：全部预检 → journal → 按主 PID 执行 taskset -apc → 逐线程读回 → 再次审计。
python3 "$SKILL_DIR/scripts/ascend_bind.py" apply \
  --plan "$CASE_DIR/plan.json" --state "$CASE_DIR/state.json" --execute

# B：在完全相同负载下记录 after.json，填入此次 plan.json 的 plan_id。
sudo bash "$SKILL_DIR/scripts/cpu_trace_collect.sh" --duration 30 \
  --pid "$JOB_PID" --output "$CASE_DIR/after-capture"
python3 "$SKILL_DIR/analyzer/analyze_cpu_trace.py" "$CASE_DIR/after-capture" \
  --output-dir "$CASE_DIR/after-report"

# 默认只比较；无收益/退化/证据不足均自动回滚是独立的显式执行选项。
python3 "$SKILL_DIR/scripts/ascend_bind.py" verify \
  --before "$CASE_DIR/before.json" --after "$CASE_DIR/after.json" \
  --before-report "$CASE_DIR/before-report/report_data.json" \
  --after-report "$CASE_DIR/after-report/report_data.json" \
  --plan "$CASE_DIR/plan.json" --state "$CASE_DIR/state.json" \
  --output "$CASE_DIR/verification.json" --live-audit --rollback-on-fail --execute

# 需要恢复时也可单独执行；不加 --execute 只展示 journal 状态。
python3 "$SKILL_DIR/scripts/ascend_bind.py" rollback --state "$CASE_DIR/state.json" --execute
```

以上业务样本 `before.json` / `after.json` 是业务测试程序导出的输入，不会由 Trace 或本工具凭空生成。先获得真实业务指标，再执行 verify。无业务样本时可运行 `audit --plan ...` 证明当前配置生效，性能结论保持待验证。

报告和客户生成器提供相同的 Python 模板，以及描述本次目标的 `bind_design.json`。模板在 `python3 cpu_binder_simple.py -c bind_design.json` 时直接执行，须先现场核对对象、权限和授权。它不调用本页 CLI，也不创建可供本页 rollback 使用的 state 文件。

## Rank、设备与线程发现

- 目标必须由 `--pid`、`--process-regex` 或可重复的 `--worker GLOBAL_LOGIC_NPU:HOST_PID` 明确限定。自动发现保留所有匹配占卡 PID，不按显存最大值筛除 Worker。
- `npu-smi info -m` 将卡/芯片映射到全局逻辑 NPU；进程表确定实际 PID 占卡关系；带明确 CPU Affinity 标题的 topo 确定 NPU→CPU。未知/矛盾/不完整的表拒绝规划。
- Rank 只读取 `RANK / LOCAL_RANK / WORLD_SIZE / LOCAL_WORLD_SIZE / GROUP_RANK` 和三种 visible devices 白名单字段，不保存完整 environ。子进程可能继承 Rank 环境，因此不凭相同 Rank 合并进程，也不按 LOCAL_RANK 直接推断全局 NPU。缺 Rank 时仍可凭已核验的 NPU/PID 做 Worker 级计划，明确 Rank 未知。
- 白名单 Rank 也加入采集包的 `process_start/end.json.rank_env`；报告对象清单显示 Rank / Local Rank。`acl_thread`、`release_thread`、DataLoader、HCCL/NCCL、pin_memory、tokenizer 和 main/unknown 是角色线索，不能单凭名称自动专核。
- 已有子进程由同代 PPID 链归属；有自身 NPU 归属时使用自己的映射。启动器、未占卡的 DataLoader 和其他关联进程只用于报告清单。
- 同 PID 占多个不同池且无线程设备归属时阻断；同 NPU 多 PID 默认共享该卡池，不承诺每 PID 独占。

## NUMA 分配

`locality` 是默认策略：显式 NPU affinity ∩ online ∩ 每个 TID 有效 cpuset；无可读 cpuset 时仅允许其当前 allowed 子集。已在该池内且有效的窄掩码保留。要求池内在线 CPU 都有可靠 CPU→NUMA 映射且归属一个节点；跨节点或缺映射时阻断，不能从卡号/连接关系猜 NUMA。

`--allocation partition` 是显式的均分实验候选：读取所有 NPU（包括未选中/当前空闲卡）的完整拓扑，按相同原始亲和池分组，再按全局逻辑 NPU ID 分配完整 SMT sibling 组。它不使用固定核数、不根据正在运行的卡数扩大池，不拆开同一物理核；非相同池部分重叠、SMT 不完整/不对称或核心组不足时拒绝。它没有宣称按实测需求最优；现有 Analyzer 的运行/等待需求建议可作为另外的证据，收益仍由业务 A/B 验证。

逐线程核验 cpuset。对各线程的许可范围取公共交集。公共目标为空或会改变需保留的本地掩码时，停止生成现场计划。CPU 亲和性不隔离其他业务/IRQ，不改变 quota，不迁移已有页，不设置新页的内存策略。IRQ/dev 亲和、irqbalance、migratepages、membind 不在此事务范围内；需要对应独立证据与独立实验。

不支持当前 npu-smi 文本格式时，允许人工核验全部卡的 JSON；必须同时显式给 `--worker`。示例仅表示结构，实际 CPU/NPU 值来自现场：

```json
{"id_space":"global_logic","verified_by":"operator / ticket / timestamp","npu_cpus":{"0":"0-15","1":"16-31"}}
```

人工映射取代自动设备表，工具无法证明人工选择的 PID 确实占用相应设备；验证责任由 `verified_by` 所指操作者承担。全部卡必须包含，不能只列本次选中的卡。

## 事务、漂移与恢复

plan 绑定报告 SHA256、boot_id、宿主 PID namespace、PID/TID starttime、父关系、原掩码、逐 TID cpuset、完整 CPU/NPU/NUMA/SMT 拓扑；plan_id 是整份计划的校验和。不能编辑计划后继续执行，应重新 plan。状态文件必须全新，不覆盖已有回滚记录。

执行前全量预检；每次变更前持久化 WRITING 意图并 fsync，再紧贴 taskset 调用核验身份/掩码/cpuset。执行后读回并核验身份，结束后复查全部线程集合与拓扑。本工具的 apply/rollback 持同一个 flock，防止本工具并发；它不能锁住框架/管理员的 affinity 写入。taskset 通过数字 PID 枚举线程，存在非原子的线程集合变化窗口，双重核验缩小窗口并在发现变化时停止，不宣称内核级原子事务。SIGINT/SIGTERM 和普通失败触发尽力恢复；SIGKILL/掉电后用持久化 journal 显式 rollback。

恢复逐项验证 boot/namespace、TGID/进程/线程出生、父关系和当前掩码。当前仍为该日志写入的值时才恢复原值并读回；外部改动保留为 CONFLICT。失败 syscall 不接管当时读到的任意外部值；成功 syscall 的非空目标子集读回会记录并尝试恢复；含目标池之外 CPU 的读回视作外部漂移。外部写入恰好等于目标或其子集时无法凭掩码区分来源，应保证只有一个 affinity 控制器。CPU 离线、cpuset 收缩或权限变化可能导致恢复失败，保留逐项结果，不把失败计为成功。

`RESTORED` 表示日志项恢复且未发现未跟踪任务；`RESTORED_WITH_SKIPS` 表示退出/身份变化项未触碰；`RESTORE_INCOMPLETE` 表示冲突、失败、未跟踪新任务或无法验证。新线程可能继承已改过的 affinity，回滚会标为 UNTRACKED。新建子进程也可能继承掩码，子进程的恢复由业务侧管理。

可选 `apply --watch-seconds 60 --interval 1 --execute ...` 做有限时长只读审计；发现主进程新线程、亲和漂移、重启或拓扑变化即停止并尝试回滚，不与框架持续抢写，不自动重连新 Rank。watch 正常到期保留绑定；需要恢复应显式 rollback。默认不启动后台守护进程。

## 业务指标输入与结论

两份文件采用相同 workload、metric、warmup、轮数与每轮样本数；每轮 warmup 剔除后默认至少 30 个样本，至少 3 轮。完整记录数据、模型/版本、batch、sequence、并行策略、精度、框架/驱动版本、背景负载、热身/采样窗口，可在 workload 中增加字段，前后需完全相同。线程 affinity 是实验变量，不放进要求一致的 workload 指纹。

结构示例（runs 的数组仅展示写法，3 个样本不足验收，不能冒充真实业务测量）：

```json
{
  "schema_version":1,
  "workload":{"model":"model-version","batch_size":8,"sequence_length":2048,
    "parallelism":"tp8-dp1","dataset":"dataset-version","precision":"bf16","framework":"exact-version"},
  "metric":{"name":"step_time","unit":"ms","direction":"lower"},
  "warmup":1,"runs":[[1000,101,100],[1000,100,99],[1000,102,101]],"errors":0,
  "plan_id":"after.json 填入实际计划校验和；before.json 可省略"
}
```

主指标可选 step_time、samples/s、tokens/s、TTFT、TPOT 等，用 `higher`/`lower` 明确方向；一次实验一个主指标。compare_measurements 校验数值有限且正、指标/单位/方向一致、负载一致，先剔热身，再用每轮 median 的 median 比较中心值；延迟取 P95 坏尾、吞吐取 P5 坏尾。默认最小收益 2%、容许坏尾退化 5% 是可改实验阈值，不是硬件官方标准；跨轮波动大于收益且超过5%时为 INCONCLUSIVE，建议 A/B/A 或随机交叉实验。

| 状态 | 含义 / 默认建议 |
|---|---|
| PASS | 主指标收益达阈值且坏尾未退化、配置证据齐全；保留候选，结论是经验性 A/B 收益 |
| NO_GAIN | 主指标收益不足阈值；建议回滚 |
| REGRESSION | 中心/坏尾退化或新增业务错误；建议回滚 |
| INCONCLUSIVE | 业务样本不足/无效、不一致、波动过大、Trace/配置/身份缺证据；不声称性能收益 |

verify 要求 before report 与 plan 的 Trace 摘要一致、前后同 host/boot/namespace，after report 前后快照都能确认每个计划 TID 的同代身份和目标 affinity，并检查额外新任务；after.json 的 plan_id 必须吻合 APPLIED journal。复用未绑核的旧报告不能通过。保存实际 `sched`（ms）、scheduler_quality、thread_metrics、迁移、竞争、NPU/NUMA 和采集完整性作为辅证，不用 CPU 平均利用率替代业务收益。快照只证明采样端点，不能证明整段 affinity 从未被其他工具改写；需结合 watch/业务日志解释。

`verify --rollback-on-fail --execute` 明确授权任何非 PASS 都尝试恢复。没有该选项时只输出判定，不修改 affinity。退出码：0=操作完成/预览通过/性能PASS；2=参数、身份或执行错误；3=漂移/非PASS；4=回滚不完整。所有 JSON 留在实验目录，不清理原采集包。

## 验证范围

仓库测试使用明确合成的 proc/sysfs/Trace 和模拟 affinity 后端，覆盖预检、SMT、身份复用、部分失败、读回、回滚冲突、新任务和性能判定。实际 openEuler/Kunpeng/Ascend 硬件、驱动 npu-smi 文本变体与业务收益须现场验证；本地通过不等于真实 NPU 性能提升。
