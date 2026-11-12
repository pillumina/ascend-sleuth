# dsh-sleuth-autoclose

ascend-sleuth 的自动收尾插件。装在 DSH profile 里，常驻运行：按配置的间隔调一次
`scripts/groom_sweep.py`，由它查 PR 合入、核对证据、收尾并清理。

装完即可用：不需要填检出路径或解释器，默认打开自动检测、间隔 24 小时，启动后先跑一次；
新装的首轮只出预览，面板确认后才真正移草稿、删评估与快照。

## 首次运行

新装（没有 `autoclose-state.json`）第一轮只跑 dry-run，把「将处理 N 项」写进状态；面板
「自动收尾」显示预览，点「确认并执行」后下一次才带 `--apply`。已经有 `lastRun` 的老状态
按已确认迁移，不会升级后突然只出预览。

## 前置

- 解释器要有 PyYAML：`python -c "import yaml"` 能通过。插件探测解释器时会同时校验它。
- GitHub 状态查询走 `gh`：先 `gh auth login`，或让 DSH 进程环境里有 `GH_TOKEN`。

## 装

本插件是 `dsh-sleuth-panels` 的依赖，随面板包一起安装。用户只装面板；面板「自动收尾」页的开关就是启用/停用，停止功能不用卸载。

### 随面板装

1. 打开左侧栏「插件」页，点「添加插件 / 从本地安装」。
2. 粘贴**面板包**的绝对路径 `<仓库>/dsh-plugins/dsh-sleuth-panels`。这个包会带上 `dsh-sleuth-autoclose`；不要单独粘本目录。
3. 界面提示需要重启时，完全退出 DSH 再打开。打开「自动收尾」页，开关默认开；关掉开关就停定时器，不需要卸载。
4. 首轮只做预览，面板点「确认并执行」后才会真正移草稿、删评估与快照（见「首次运行」）。
5. 卸载面板会一起移除本插件。不要单独卸载 `dsh-sleuth-autoclose`，否则面板页会失去后台任务。

### 只调试本插件（开发）

面板包已经带本插件；下面两条仅在单独调试插件时用，生产安装不需要。

```
plugin_manager install_bundle(target: '<本目录绝对路径>')
```

或：

```
<安装目录>/runtime/cli/bin/dsh plugin --profile <profile> add "<本目录绝对路径>"
```

`dsh plugin add` 只把包装进 profile 依赖，不会登记成 bundle；只走这条路时，还要在
profile 的 `dsh.profile.bundles` 里补 `dsh-sleuth-autoclose`，否则 DSH 启动时不会加载它。
`plugin_manager install_bundle` 会同时完成依赖与 bundle 登记。

装完重启 DSH 生效。

卸：

```
plugin_manager remove_bundle(target: 'dsh-sleuth-autoclose')
```

卸载后重启 DSH；插件的 `ctx.effect` 清理函数会停掉定时器与 30 秒配置轮询。

## 自动发现

| 项 | 规则 |
|---|---|
| 检出 | 依次看：当前会话的 `cwd`、插件自身所在检出（link 安装时就是仓库）、进程 `cwd`；每个候选先用 `git rev-parse --git-common-dir` 归到主检出，再找 `scripts/groom_sweep.py` |
| 解释器 | 依次探测 `python3`、`python`、`py -3`，只选能 `import yaml` 且版本为 3.x 的；宿主能跑但沙箱里跑不起来的候选会被跳过 |

启动时没找到检出的，30 秒后再找一次；用户打开一个检出后不需要重启 DSH。

## 配

`cordis.patch.yml` 的 `config`（一般不用改）：

| 字段 | 默认 | 含义 |
|---|---|---|
| `enabled` | `true` | 开关；关掉即清定时器，手动流程不受影响 |
| `repo` | 空 | 可选覆盖：主检出绝对路径；空值走自动发现 |
| `intervalMinutes` | `1440` | 间隔（分钟），最小 1；面板保存的也是这个字段 |
| `intervalHours` | 无 | 旧字段，仍兼容；`intervalMinutes` 优先 |
| `python` | 空 | 可选覆盖：解释器命令；空值自动探测 |
| `runOnStart` | `true` | DSH 启动后是否立即跑一次（补上关闭期间到期的检查） |

改配置后重启 DSH 生效。面板里的「查询间隔」写到主检出
`postmortems/inbox/.groom/autoclose-config.json`，最多 30 秒被插件读到，不需要重启。

## 行为

- 每次运行调 `groom_sweep --repo <检出> --apply --fetch --source plugin --json`。
- 失败时 `lastSummary` 取具体草稿的 `status`/`reason`（如「收尾失败：<draft>：…」），并写 `lastFailure`；面板「待本地处理」显示失败状态与原因。没有 `sweep-log` 的失败（台账锁、Python、shell）由面板用状态文件兜底。
- shell 的权限档位取发现检出所用会话的档位（与面板的 `readPolicy(session)` 一致）：会话是完全权限就不走沙箱，工作区写档位下受沙箱限制；没有会话时退回部署默认。插件不硬编码 workspace-write。
- 结果由 sweep 自己写 `.groom/sweep-log.jsonl`；插件另写运行状态
  `.groom/autoclose-state.json`，面板读这两份。
- 连续失败 3 次自动暂停（`paused`），避免每天刷同一错误；恢复用 `resume` 或配置
  `resume: true`。
- 找不到检出或 Python 不算失败，状态里写原因；发现后最迟 30 秒内补跑。
- 有 `note`（如「无事可做」）时照常返回成功。

## 恢复暂停

连续失败 3 次会暂停，`paused: true` 写进状态文件
`postmortems/inbox/.groom/autoclose-state.json`。恢复方式：

- 面板「自动收尾」的「恢复调度」：写 `resume: true`，插件 30 秒内读到后清零暂停与失败计数，并立即跑一轮 sweep，不需要重启；
- 面板的「立即运行一次」：写 `runNow: true`，只强制跑这一轮，不改暂停状态，也不清零连续失败计数；清零走恢复调度；
- 配置里加 `resume: true` 并重启：启动时做同样的事；
- 调用插件返回的 `resume()`：同样清零并写回状态文件。

`resume` 是一次性字段：插件读过就删掉，避免每 30 秒重复清零。

## 边界

- DSH 关闭时不跑；需要 7×24 得用系统计划任务，不在本插件范围。
- 只做收尾，不自动合入、不自动开 PR、不替人做决定。
- 不注册 tab、不 import Copilot、不改其他面板；面板读的是 sweep-log 与状态文件。
- 手动兜底始终在：Copilot 的「已合入 · 待收尾」指令与 groom 开场照旧。

## 自测

```
node test/host-smoke.mjs
```
