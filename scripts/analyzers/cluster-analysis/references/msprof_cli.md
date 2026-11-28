# msprof-analyze 原生 CLI 与 fallback 能力对照

## 原生 CLI（默认优先：PATH 中存在 msprof-analyze 即启用）

```bash
msprof-analyze advisor {all|computation|schedule} <prof_dir> [-o <output>]
msprof-analyze compare -d <base_dir> -c <compare_dir> [-o <output>]
msprof-analyze cluster analysis -d <prof_dir> [-o <output>] [--top_num N]
msprof-analyze cluster analysis -d <prof_dir> --bp <标杆数据>   # 标杆对比（参数拼写以 `msprof-analyze cluster analysis --help` 实际输出为准）
```

- `advisor all`：全场景诊断（对应 P1；原生产物仅留档，advisor.md/json 始终由内置实现归一化）。
- `cluster analysis`：生成/更新 `cluster_analysis_output`（对应 P2），追加 recipe 名称可单跑某项进阶分析（对应 P3）。
- `compare`：双卡/双环境对比（对应 P4；原生 xlsx 由 run_workflow 按卡对归一化命名）。

## fallback 能力对照（原生不可用/失败时使用）

内置实现支持 TEXT 和具备相应能力的 DB-only 产物。只提供可读的集群输出时，工作流执行集群汇总和支持的 recipe，再生成 P7 主报告。具体支持范围见 workflow_status.json 的阶段状态和 recipe 能力矩阵。

| 能力 | 原生实现 | 本技能 fallback |
|------|----------|-----------------|
| 输入检测 | 文档约定 | `scripts/detect_prof.py` |
| advisor all | `msprof-analyze advisor all` | `scripts/advisor_fallback.py`（全卡聚合；两种路径后均执行，负责归一化契约件） |
| 集群输出件 | `msprof-analyze cluster analysis` | `scripts/cluster_fallback.py`（原生无可用集群汇总时生成） |
| 进阶分析 | `msprof-analyze cluster analysis <recipe>` | `scripts/recipe_fallback.py`（正式 23 + 扩展 1，生成统一的出报汇总） |
| 性能比对 | `msprof-analyze compare` | `scripts/compare_fallback.py`（xlsx 中间件 → 内置 prof-compare；`--json-only` 模式仅补产 JSON，供原生路径使用） |
| 泳道统计 | trace_view.json 人工分析 | `scripts/swimlane_analyzer.py`（流式解析） |
| 最终报告 | 无 | `scripts/report_generator.py` |

## 探测与回退流程

1. run_workflow 探测 `msprof-analyze`，可用时在 P1、P2、P4 使用原生 CLI。已有集群输出以只读方式复用，P3 原生补充分析仅针对本次由 P2 原生生成的产物。
2. 原生命令失败（数据格式不支持、缺依赖）→ 立即回退对应 fallback 脚本，不要中断流程。
3. P2 生成的集群输出需有可用的步骤汇总。P3 通过 recipe_fallback.py 生成 P7 的 `recipes_summary.json`。P4 的原生 xlsx 归一化后由 compare_fallback.py `--json-only` 生成 `compare_analysis_result.json`。
4. fallback 产出的 `cluster_analysis_output/cluster_analysis.db` schema 与原生一致，供进阶 recipe 和总报告使用。
5. `--no-native` 整体禁用原生（全部使用内置实现）；`--msprof-cli` 兼容保留为 no-op。
