# RSI 实验台（dsh-rsi-observatory）

DSH 插件：左侧栏一个「实验台」图标，主区一整页，只读查看 RSI 的实验、提案与判定历史。

- **只读**：不写仓库、不联网、不改实验记录。
- **数据只来自 RSIStore**：host 经 shell 跑 `scripts/rsi_observatory.py`，脚本只用
  `open_store()` / `read()` / `history()`；插件不读 `rsi-events.jsonl`，也不读
  `proposals.jsonl` / `conclusions.jsonl` / `experiments.jsonl` 这些投影。
- **独立安装**：装在 DSH profile 里，与本仓其它面板包分开登记，卸载即消失。

## 页面

| 区域 | 内容 |
|---|---|
| 左栏 | 「实验 / 提案」切换。实验行给判定圆点、标题、提案号、target、时间；提案行给状态与关联实验数 |
| 概览 | 判定摘要、七阶段派生视图、判定卡（原因、配对 b/c/n、p 值、alpha_eff、成本、约束）、执行与回滚 |
| 提案 | target、范围、改动类型、状态、预期、风险、回滚、改动文件与 diff |
| 事件 | `history()` 的事件流，按 kind 过滤，点开看原始 `data`（长字符串按 4KB 截断） |

阶段是**派生视图**：`attribute` / `select_region` / `select_candidate` / `propose` / `execute` /
`judge` / `gate`，只有 store 事件里能找到对应字段的才标「有记录」，其余标「无记录」。RSI 事件没有
逐阶段时间，所以这里不画时间线。

## 数据与失败路径

| 情况 | 界面 |
|---|---|
| store 为空 | 「还没有实验记录」+ 数据源（backend/path）+ 刷新 |
| 没有 shell 服务 | `E_NO_SHELL`：当前宿主不提供命令执行 |
| 找不到含桥脚本的检出 | `E_NO_REPO`：在 `config.repo` 填绝对路径，或从该检出开会话 |
| 没有 Python 3 | `E_NO_PYTHON`：列出试过的 `python3 / python / py -3` |
| 缺 PyYAML | `E_PYTHON_DEPS`：给安装命令 |
| JSONL 有一行坏 / 未知后端 | `E_STORE`：保留路径与 `RecordError` 原文，整页错误态 |
| 找不到某条实验 | `E_NOT_FOUND`（桥脚本退出码 4） |

`read()` 是全量读取并逐条校验事件，一行坏就整份读不出；此时不渲染半份数据，避免把缺行读成「没有这条」。

## 安装

```
plugin_manager install_bundle(target: "<本目录绝对路径>")
```

或桌面版自带 CLI：

```
<DSH 安装目录>/runtime/cli/bin/dsh plugin --profile desktop add "<本目录绝对路径>"
```

装完刷新页面；侧栏图标没出现时重启 DSH Desktop（host 半的 RPC 路由在进程启动时装载）。
本包暂不加入 `scripts/lib/panel_desktop.js` 的 `PANEL_PACKAGES`，所以 `panel_install.js --all`
不会装它；要进默认四包之外的安装路，另开改动。

## 配置

`apply(ctx, config)` 读三个可选键，写在 `cordis.patch.yml` 的 `config` 段：

| 键 | 默认 | 用途 |
|---|---|---|
| `repo` | 会话工作区候选里第一个含桥脚本的检出 | 直接指定仓库根 |
| `python` | 自动探测 `python3` / `python` / `py -3` | 指定解释器 |
| `cacheTtlMs` | `30000` | 结果复用窗口；界面「刷新」带 `refresh:true` 绕过 |

本包没有导出 `Config` schema，键不做类型校验；取值不合法时按默认值退化。

## 只读边界

- host 只注册 `/rsi-observatory` 的 prefix RPC 路由，客户端只调用 `rsi-list` / `rsi-detail`。
- 桥脚本只接受 `list` 与 `detail`，`experimentId` 在 host 先按 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
  校验，再以固定参数拼进命令行。
- 不写 `knowledge/`、`postmortems/`、`proposals/`、`traces/`，也不写 store。

## 验证

```
python3 -m unittest tests.self_evolution.test_rsi_observatory -v
node dsh-plugins/dsh-rsi-observatory/test/host.test.mjs
node dsh-plugins/dsh-rsi-observatory/test/client.test.mjs
python3 scripts/rsi_observatory.py list --json
```

前三条不需要 DSH；第四条在真实仓库上跑一次，确认本机 store 与脚本可用。浏览器里的排版、亮暗主题
与交互仍要在真机看一眼，测试只覆盖加载、注册、渲染文本与失败路径。

## 版本迭代

没有构建步骤：`lib/client.js` 就是客户端源码，`host/index.js` 就是 host 源码。改源码后 bump
`package.json` 的 `version`，按原路重装；同版本重装不会换产物。

## 已知限制

- 目前 RSI 写侧只有 `experiment` 事件（`record_experiment`），没有独立的 `proposal` / `decision` /
  `rollout` 事件；所以「提案」列表只包含**已经进入实验**的提案，未跑的提案不可见。
- 逐样本成绩不在 store 事件里：`rollout` 只有样本编号与 arms 计数，`experiment` 只有均分与配对
  b/c/n。页面因此只列样本编号，不做改前/改后对比表。
- `experiment_id` 默认是 `EX-<proposal_id>`：同一提案跑两次会复用 id。页面用 `event_id` 区分行，
  并在 `gaps` 里标 `id_collision`。
- 事件里嵌着完整 proposal，`artifact.diff` 可能很大；桥脚本把单字符串截到 4000 字符并标
  `truncated`，详情页没有分页。

## 界面目标

- 信息层级：实验标题说明“哪条候选、解决哪个问题”；摘要先给结论、样本、成本、回滚，再展开七个实验环节。提案页只显示提案与关联实验，不复用实验概览。
- 数据准确：逐样本表显示问题标题、独立评审的判定标准和对照/候选变化，使用 `table`/`caption`/`scope`；长 diff 默认折叠，显示文件数与增删行数。
- 响应式：主布局按容器宽度在 860px 切单列，在 560px 把逐样本表改为堆叠卡片。
- 可读性：数字使用 tabular-nums；时间、耗时、词元按人读单位显示；不使用只对作者有意义的缩写。
- 可访问性：焦点环、键盘可滚动表格、语义化表头、`prefers-reduced-motion` 下不加过渡。
- 视觉：浅色/深色都使用 DSH 主题变量；卡片、侧栏、状态 pill 统一圆角与细边框。

已知边界：视觉在静态预览与 client 测试里检查，真实宿主仍需重启后逐屏看；旧记录没有逐样本分数时只显示已有字段。
