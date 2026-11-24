# 脚本层：入口、共享模块与加脚本的检查单

你只在两种时候需要这篇：要新增一个 `scripts/*.py`，或要判断某段逻辑该放脚本、共享模块还是 `evolve` 包。
日常诊断与内容流程不必读。

## 1 入口与库

`scripts/` 没有子包，所有脚本在同一目录（下称平铺命名空间）。里面的文件有两种角色，混用会让改动同时牵动入口与引用方。

| 角色 | 标志 | 要求 |
|---|---|---|
| 入口 | 顶层 `scripts/<name>.py`，有 `if __name__ == "__main__"` | 只做参数、编排与输出；业务规则不放这里 |
| 库 | 下划线开头，如 `_trace_state.py`、`_fs.py` | 只被 import，不直接跑；不读命令行 |
| 双角色 | 顶层但没有下划线，同时被别的脚本 import | 过渡态：新逻辑先拆到 `_` 模块，入口保留 `main` 与兼容 re-export |

`kb_sync.py` 与 `pr_status.py` 已经按这个方向拆过：库层在 `_kb_sync.py`/`_pr_status.py`，入口只留
argparse/main 与 re-export，旧调用方（含测试的 `mock.patch.object(kb_sync, …)`）仍按原模块名访问。
仍属双角色、尚未拆的还有 `index_read_cost`、`verify_references`、`score_entries`、`build_index`、
`ev_board_data` 等；新代码不要再往入口脚本里写库函数。

## 2 共享模块

| 模块 | 管什么 | 什么时候用 |
|---|---|---|
| `_cli.py` | `main_entry`、`fail`、`emit`、`base_parser`/`add_common_args` | 所有入口的收尾；新脚本用 `base_parser` 拿 `--root`/`--json` |
| `_stdio.py` | UTF-8 标准流、`write_text_lf` | 入口由 `main_entry` 统一处理；写固定 LF 文本时用 |
| `_fs.py` | 原子写、YAML 读写 | 写共享账本、生成物、状态文件 |
| `_yaml.py` | YAML 解析后端（`load_file`） | 读 YAML 文件优先走它，不直接 `yaml.safe_load(read_text())` |
| `exec_log_path.py` | 运行时件的路径解析（执行记录、`evolve`、`traces`…） | 读或写跨 worktree 共享的运行时件 |
| `shared_dir.py` | agent 侧的同一件事的 CLI 入口 | agent 需要问「这份记录该落哪」时 |
| `_trace_state.py` | trace 词表、状态投影 | 读 `traces/` 的脚本共用 |
| `groom_common.py` | groom 系列的草稿/评估读取 | groom 相关脚本 |
| `entry_activity.py` | 条目使用记录的本机明细写入 | 知识库面板与指标 |
| `_settings.py` | `.local/settings.json` 的 schema、默认值、CAS 写 | 读/写部署配置 |
| `_kb_sync.py` / `_pr_status.py` | 同步与 PR 记录的库层（入口脚本只留 CLI） | 改这两个流程的规则时 |
| `_ev_cards.py` | 合入指针判定（`ev_proposal` 与 `ev_board_data` 的唯一口径） | 读积压/水位时 |

## 3 命令行约定

- 入口收尾一律 `raise SystemExit(main_entry(main))`；`main_entry` 负责钉 stdio、把 `SystemExit`/`BrokenPipe`/`Ctrl-C` 归一成整数。静态检查在 `tests/test_cli_contract.py`。
- 退出码只有三个通用含义：`0` 成功/无问题、`1` 有发现、`2` 用法或读取错误。脚本特有的码（如 `3`）在文件头写清。
- 新脚本用 `_cli.base_parser(description, json_output=True)`；已有脚本的 `--root`/`--json` 语义不要顺手改动，逐脚本迁移。
- 错误输出走 stderr，一行一句话；不要把异常吞掉当成普通失败。
- 机器消费的输出加 `--json`；键名一旦被面板或脚本读取，补一条键级测试。
- `docs/mechanism/status.md` 的「确认方式」可执行项由 `python3 scripts/status_check.py` 跑（`--list` 只看清单、`--only` 按机制名过滤）；只证明存在性的 `ls`/`grep` 不计为通过。

## 4 路径与写入

- 运行时件（`traces/`、执行记录、`evolve` 队列与结论、`proposals/` 草稿）锚到主检出，用 `exec_log_path` / `shared_dir` 解析；不要写相对路径。
- `.s2-replay/`、`.ixn-replay/`、`eval-reports/` 是开发期产物，随 worktree 消失属正常；要长期保留的记录不放在这里。
- 写共享账本、生成物、状态文件用 `_fs.atomic_write_text`；只写临时文件或测试夹具可以直接 `write_text`。
- 读 YAML 文件走 `_yaml.load_file`（或 `_fs.load_yaml`）；直接 `yaml.safe_load(path.read_text())` 只在需要自定义错误包装时使用。

## 5 环境变量

脚本层读这些变量；未登记的变量不要再新增，确有需要先补进这张表并写明用途。

| 变量 | 用途 | 主要读取处 |
|---|---|---|
| `SLEUTH_TRACE` / `SLEUTH_OUT` / `SLEUTH_INPUT` | runner 传给被测 agent 的单次输入/输出路径 | `agent_adapter.py`、`stage_runner.py`、`smoke_runner.py` |
| `SLEUTH_SAMPLE_ID` / `SLEUTH_SHORT_ID` / `SLEUTH_ARM` / `SLEUTH_STAGE` | 当前样本、短 id、对照臂与 stage 名 | 同上 |
| `SLEUTH_AGENT_CMD` | `agent=command` 模式下的外部命令 | `agent_adapter.py` |
| `SLEUTH_DSH_BIN` | DSH CLI 路径（默认取 PATH 或安装目录） | `agent_adapter.py`、`judge_adapter.py` |
| `SLEUTH_DSH_ALLOW_STORED` | 允许用已存凭据跑 headless | `agent_adapter.py` |
| `DEEPSEEK_API_KEY` | headless 认证 | `agent_adapter.py` |
| `SLEUTH_RSI_STORE_BACKEND` / `SLEUTH_RSI_STORE_PATH` | 实验事件存储后端与路径覆盖 | `evolve/store/config.py` |
| `ASCEND_SLEUTH_DEPLOYMENT` | 部署标识（指标/条目使用记录分组） | `entry_activity.py` |
| `DSH_HOME` / `XDG_DATA_HOME` / `APPDATA` | DSH 会话与平台数据目录 | `harness_usage.py`、`trace_entry_activity.py` |

## 6 没有自动测试的脚本

这些脚本当前没有单测、也没有对应 CI job，改动后只能在真实部署或本机手工验证。新增测试成本高于收益时，改动说明里写明验证方式。

`audit_skill_cost`、`auto_fetch`、`bench_sediment_queue`、`build_kb_explorer`、`capacity_health`、`fetch_issues`、`flow_pool`、`ixn_replay`、`migrate_upstream_anchors`、`replay_prep`、`validate_rsi_full_flow`、`validate_rsi_gepa`、`validate_rsi_replay`。

## 7 加一个脚本的检查单

1. 先判断能不能是现有脚本的一个子命令；能就别新建。
2. 文件名：入口不带下划线；纯库用 `_` 开头。不要再新增双角色模块。
3. 入口收尾 `raise SystemExit(main_entry(main))`；新脚本用 `_cli.base_parser`。
4. 读 YAML 走 `_yaml.load_file`；写共享文件走 `_fs.atomic_write_text`；跨 worktree 运行时件走 `exec_log_path`。
5. 有 `--json` 就给键级测试；有判定逻辑就把纯函数拆出来单测。外网/交互型在文件头写 `manual-only` 与验证方式。
6. 在 `docs/` 或脚本头注释里写清「什么时候用它」；被 skill 或 CI 调用就同步更新引用。
7. 跑 `python3 -m unittest discover tests` 与 `python3 scripts/check_test_portability.py`；新增文档登记进 `docs/_manifest.yaml` 后跑 `python3 scripts/build_docs_index.py`。
