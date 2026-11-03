# fixtures：合成测试数据

这里的 trace 与 JSON 全是**合成的**。任何一份真实诊断 trace 都不得复制进本目录：真实 trace 含客户现场信息，属私有面。

数据分三层：

| 路径 | 角色 |
|---|---|
| `trace-samples/*.yaml` | 源：三份手写 YAML，形状照 ascend-sleuth 的 `traces/*.yaml` |
| `trace-samples/evidence/<session_id>/` | 源：trace 里 `evidence.files` 指向的小文本文件 |
| `list-sample.json`、`detail-*.json` | 生成物：host 归一化后的契约样例，测试与页面冒烟直接读 |

三份 trace 各覆盖一类形状：

- `2026-01-02-demo-a3-w8a8-garble.yaml`：resolved。用户证据四件套（inline / files / sources / missing）、分诊、检索、并行核验、先验查照、命中、归因、结论、回报 resolved，并沉淀 case。
- `2026-01-03-demo-a3-kv-load-stall.yaml`：in_progress。同一 step 内 7 个并行动作（6 条不同 verdict 的核验 + Tier 3）、源码分析（tool_calls）、未覆盖、排除 6 个候选；output 里带风险词，供 insights 风险规则断言。
- `2026-01-04-demo-a2-resume-report.yaml`：中断续接。resume、report、`sedimented: inbox`、`feedback: pending`；每个事件一个 step。

约束：

- session id 用 `2026-01-0x-demo-*`；case 编号用 `VLLM-ASC-90xx` / `REF-*`；错误码、日志行、URL 全部自造（URL 用 `https://example.com/...`）。
- 公开产品名（`vllm-ascend`、`A3-910C`、`A2-910B`、`inference_interrupt` 等）保留，其余字段值不取自真实现场。

## 重新生成 JSON

```
python3 fixtures/build-fixtures.py
```

脚本把 `fixtures/trace-samples/` 复制进临时目录、补 `scripts/metrics_health.py` 标记，再调用 `host/index.js` 的 `createHost`（假 fs + sessions）导出 list / detail 的实际输出。`repo.path`、`generatedAt`、`version` 换成固定占位，所以每次生成字节一致。事件数最多的那份同时写成 `detail-sample.json`。

PyYAML 会回读三份 trace 做交叉校验：顶层是映射、事件数与 host 归一化结果一致、`evidence.files` 指向的文件存在。校验失败即退出，不写半份文件。

依赖：python3 + PyYAML、node。脚本仅开发用，不进插件运行时。
