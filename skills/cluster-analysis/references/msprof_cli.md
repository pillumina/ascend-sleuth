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
- `compare`：双卡/双环境对比（对应 P4；原生 xlsx 由 run_workflow 归一化为 vendor 契约命名）。

## fallback 能力对照（原生不可用/失败时使用）

内置实现依赖 TEXT 产物，不与原生所有格式和诊断能力等价。DB-only 缺少归一化适配时预检失败；已有 cluster_analysis_output 可以走独立报告模式。以 workflow_status.json 的阶段状态和 recipe 能力矩阵为准。

| 能力 | 原生实现 | 本技能 fallback |
|------|----------|-----------------|
| 输入检测 | 文档约定 | `scripts/detect_prof.py` |
| advisor all | `msprof-analyze advisor all` | `scripts/advisor_fallback.py`（全卡聚合；两种路径后均执行，负责归一化契约件） |
| 集群输出件 | `msprof-analyze cluster analysis` | `scripts/cluster_fallback.py`（同 schema db；原生产物缺 db 时自动补齐） |
| 进阶分析 | `msprof-analyze cluster analysis <recipe>` | `scripts/recipe_fallback.py`（正式 23 + 扩展 1 全量；原生产物缺 summary 时自动补齐） |
| 性能比对 | `msprof-analyze compare` | `scripts/compare_fallback.py`（xlsx 中间件 → vendor prof-compare；`--json-only` 模式仅补产 JSON，供原生路径使用） |
| 泳道统计 | trace_view.json 人工分析 | `scripts/swimlane_analyzer.py`（流式解析） |
| 最终报告 | 无 | `scripts/report_generator.py` |

## 探测与回退流程

1. run_workflow **默认原生优先**：以 `shutil.which('msprof-analyze')` 探测；可用 → P1/P2/P3/P4 优先原生 CLI。
2. 原生命令失败（数据格式不支持、缺依赖）→ 立即回退对应 fallback 脚本，不要中断流程。
3. **产物缺口补齐**（原生成功但缺总报告契约件时自动执行）：P2 缺 `cluster_analysis.db` → cluster_fallback.py 补齐；P3 缺 `recipes_summary.json` → recipe_fallback.py 补齐；P4 xlsx 归一化后由 compare_fallback.py `--json-only` 补产 `compare_analysis_result.json`。
4. fallback 产出的 `cluster_analysis_output/cluster_analysis.db` schema 与原生一致，可被 vendor cluster-output-analysis 直接消费。
5. `--no-native` 整体禁用原生（全部使用内置实现）；`--msprof-cli` 兼容保留为 no-op。
