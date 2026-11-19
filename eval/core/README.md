# 核心评测集

`eval/core/samples/` 放 tracked 的核心样本，只收 `origin: core`、`status: active` 的：

- `purpose: test`：终判样本，封存，不参与调参。
- `purpose: regression`：回归样本，只做硬通过/硬回退，不做 accept 统计。

字段与本地样本相同；用 `sample export-core --id <id>` 从本地 active/core 样本移入。
改这些文件走 PR；不要用本地 `sample review/promote` 改写它们，`SampleStore` 会拒绝
在本地写一个同 id 的影子文件。

`test-stage.yaml` 记录 6 条 test 的终判阶段状态。当前是 `not_started`：
pilot 只消费外部 trace，仓内没有执行 diagnose replay 的 runner，6 条 test
还没有 baseline/candidate 两臂输出。补上两臂 trace 后把 status 改成
`complete`，`brief` 的 `test_stage_not_started` 就会消失。
