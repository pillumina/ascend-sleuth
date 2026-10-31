# 诊断状态机的总体设计：词表、投影、写入口与面板交互

状态：设计稿（待评审）
范围：诊断记录（`traces/`）的 `status` 轴与面板上的状态呈现/修改；`feedback` 轴与 `sedimented` 轴只定义边界与写入口归属，不在本 PR 内改判据。
读者：要实现它的人、要评审它的人、要判断这条设计是否与仓库既有约束冲突的人。

## 1 背景与动机

### 1.1 触发

面板是诊断记录的主要查看面，但改状态要经过：切到会话 → 切到「诊断」tab → 在列表里重新找到这一单 → 展开卡片 → 点「收尾」→ 选一项 → 复制一句中文指令 → 粘回对话 → 等 agent 改 YAML。共八步，且依赖一个仍然活着的对话。

同时，状态词表与状态判据散在至少五个读端与三个写点里，其中面板是 JS、脚本是 Python，代码无法共享，只能靠注释提醒「改一处必须同步另一处」（`dsh-plugins/ascend-panel/panel-client.js:846-852` 自己写着这句话）。

### 1.2 不做的代价

- 用户的真实结局落不进数据：`archived` 只覆盖「问题自行消失 / 环境变更后不复现 / 没走诊断」，缺「已转交他人」与「与另一单重复」两种（`trace-status.yaml:48-57`）。于是这类单只能被写成 `resolved`（虚高解决率）或 `not_resolved`（冤枉命中的 case）。
- 无命中单的升格闸门只认 `status: resolved`（`scripts/verify_case_draft.py:233`），标错一次就丢一条本可入库的结论。
- 加一个状态要改五处以上（词表、面板两份标签表、host 计数、升格闸门、导出意图推导、skill 正文），且没有任何一处会在漏改时报错。

### 1.3 做完的变化

1. 面板上改状态成为一次直接动作：展开卡片 → 选结论 → 填必填项 → 确认；不需要对话。写入经唯一脚本，脚本校验必填项并追加转移事件。
2. 状态规则只存在于一门语言（Python）与一个数据文件（`trace-status.yaml`）。面板不再实现任何判据，只渲染服务端给出的「当前允许的动作」。
3. 每条转移留一条 `transitions` 记录（谁、何时、从什么到什么、为什么），非法转移在写入时被拒，历史转移可被核对。

## 2 现状核对（设计依据，全部实测）

| 事实 | 证据 |
|---|---|
| 同一判据有五个实现 | 升格闸门 `scripts/verify_case_draft.py:233`；沉淀清点 `scripts/sediment_batch.py:46` 的 `TERMINAL`；导出意图 `scripts/export_trace.py:196`；面板判决 `dsh-plugins/ascend-panel/panel-client.js:857-868`；host 在办计数 `dsh-plugins/ascend-panel/panel-host.js:906` |
| 面板内标签有三份 | `panel-client.js:348` 的 `statusMeta`、`panel-client.js:4063` 的 `STATUS_LABEL`、`panel-client.js:2075` 的 `statusAccent`（`archived` 缺项，落到灰） |
| 面板已在写 trace | `ascend-update-sedimented` → `panel-host.js:240-262` 用行拼接 + `fs.writeText` 改 `sedimented` 块；UI 入口 `panel-client.js:1448` |
| 「面板只读」声明与代码不符 | `dsh-plugins/README.md` 的「只读边界」行写「不做决策与写入」；实际有三处写：导出交接包、重建本机明细、`sedimented` |
| 写子进程的沙箱约束 | `panel-host.js:24-48`：写操作必须显式 `{mode:'workspace-write', workspaceRoot: cwd}`，否则默认根是 DSH 自己的检出，写仓库被拒且只报 `Operation not permitted` |
| `stop_reason` 与状态语义重叠 | `scripts/trace_metrics.py:107-110` 的 `abandoned` / `escalated_tier3` 与 `archived` / `escalated` 表达同一件事的两个侧面 |
| 报告是活件、修订留痕 | `skills/diagnose/references/report-template.md:17-26` |
| 误诊归因只有两值 | `skills/diagnose/references/diagnosis-procedure.md:345` 的 `verdict: case_error|execution_error` |
| 现场解决率与内容验证分属两个通道 | `docs/guide/metrics.md:105`（S1 现场 / S2 内容验证，不混算） |

## 3 目标与非目标

### 3.1 目标

1. 状态与「收尾结论」在面板上可看、可改，写入可校验、可追溯、可撤销。
2. 状态规则单点定义：加一个状态、加一条转移、改一条必填，都只改一个文件。
3. 面板与脚本不可能给出不同判断：面板不实现判据。
4. 老数据（无转移事件、无收尾结论）不被判成违规，也不需要一次性清洗。

### 3.2 非目标（本 PR 不做）

- 回报轴（`feedback.outcome`）的面板写入与新字段：设计见 §9，实现排 PR2。
- 跨机同步、认领队列、锁：`traces/` 只在本机，锁保护不到另一台机器；两机同一问题的合并仍是人的判断（`docs/guide/handoff.md:149`）。
- 新增状态值：仍是 4 个业务值 + 1 个兼容值。理由见 §4.4。
- 沉淀轴的判据改写：只在写入口上收拢（§6.4）。

## 4 状态模型

### 4.1 状态

| 值 | 含义（口径唯一） | 终态 | 可续接 |
|---|---|---|---|
| `in_progress` | 诊断未给出结论，或结论已给出但仍在跟进 | 否 | 是 |
| `resolved` | 结论已写入报告（根因明确，或明确的下一步已给出）。**不表示 fix 在现场生效** | 是 | 否 |
| `escalated` | 本地无法定位，已转交上级或厂商跟进 | 是 | 否 |
| `archived` | 不再跟进这单，且不对 fix 是否有效下判断 | 是 | 否 |
| `unknown` | 旧记录未写状态；新写入不使用 | 否 | 否 |

`resolved` 与「现场是否生效」是两条轴：前者 `status`，后者 `feedback.outcome`。二者不互相赋值。

### 4.2 转移表

| 从 | 到 | 必填 | 附带的收尾结论 |
|---|---|---|---|
| `in_progress` / `unknown` | `resolved` | `summary`、`severity`、`fix_emitted`、`ended_at`；命中 case 时 `feedback.outcome` 必须有值 | 隐含 `ending.kind = root_cause` |
| `in_progress` / `unknown` | `escalated` | `summary`、`ended_at`、`ending.handed_to` | `ending.kind = handed_off` |
| `in_progress` / `unknown` | `archived` | `summary`、`ended_at`、`ending.kind` 取 `not_reproducible` / `duplicate` / `no_diagnosis` / `withdrawn`；`duplicate` 另需 `ending.duplicate_of` | 对应 kind |
| 任意终态 | `in_progress` | 无（重新打开） | 当前 `ending` 移入转移事件，顶层清空 |
| 任意终态 | 任意终态 | 禁止 | 由面板的「修正结论」在脚本内展开为「重开 + 收尾」两条事件 |

一条额外规则：**终态写 `ending` 时不要求 `stop_reason`**。`stop_reason` 记的是「探索在哪一步停下」（`resolved_confirmed` / `halted_ask_user` / `budget_exhausted` / `escalated_tier3` / `abandoned` / `unknown`），与「这单为什么结束」不是同一个问题。两者同时出现时，读端以 `ending` 为准，`stop_reason` 只进停止点统计。这条规则同时替代之前讨论里「要不要再加一个 archived_reason 字段」的分歧：加一个字段，就是第四根轴；这里只加「终态的收尾结论」，且由转移表声明它何时必填。

### 4.3 三条轴的单写者

| 字段 | 唯一写者 | 读端 |
|---|---|---|
| `status` / `ended_at` / `ending` | `scripts/trace_transition.py` | 投影器、面板、导出、指标 |
| `feedback.outcome` / `feedback_pending_since` | 回报写入（PR2 的同一脚本子命令；PR1 内仍是 agent 按 skill 写） | 投影器、结算脚本、面板 |
| `sedimented` | `scripts/trace_transition.py --field sedimented`（替换面板现有的行拼接写） | 投影器、groom、面板 |

三条轴不许互相赋值：`resolved` 不写 `feedback`，`feedback.outcome: resolved` 不把 `status` 改成什么。这是「解耦」的可执行定义。

### 4.4 为什么不新增状态值

「已定位但等现场确认」是 `status: resolved` 加 `feedback.outcome: pending`，不是第五个状态。新增状态值会让五个读端各多一个分支，且历史数据要迁移；而它要表达的差别已经存在于 `feedback` 轴。面板上通过徽标区分三态：待现场确认 / 现场已确认 / 结论待核对。

## 5 数据契约

### 5.1 `trace-status.yaml` 新增段

```yaml
# 状态转移表：写入口按它校验必填项，面板按它生成按钮，读端不重复实现规则
axes:
  status:     { writer: scripts/trace_transition.py, single_writer: true }
  outcome:    { writer: scripts/trace_transition.py --field outcome, single_writer: true }
  sedimented: { writer: scripts/trace_transition.py --field sedimented, single_writer: true }

ending_kinds:
  - { value: root_cause,        label: 根因明确 }
  - { value: not_reproducible,  label: 问题未复现 }
  - { value: handed_off,        label: 转交他人跟进, requires: [handed_to] }
  - { value: duplicate,         label: 与已有单重复, requires: [duplicate_of] }
  - { value: no_diagnosis,      label: 未走诊断 }
  - { value: withdrawn,         label: 主动撤回 }

transitions:
  - { from: [in_progress, unknown], to: resolved,
      requires: [summary, severity, fix_emitted, ended_at],
      ending: root_cause,
      action_label: 已定位 }
  - { from: [in_progress, unknown], to: escalated,
      requires: [summary, ended_at], ending: handed_off,
      action_label: 转交上游 }
  - { from: [in_progress, unknown], to: archived,
      requires: [summary, ended_at], ending_choices: [not_reproducible, duplicate, no_diagnosis, withdrawn],
      action_label: 不再跟进 }
  - { from: [resolved, escalated, archived], to: in_progress, action_label: 重新打开 }
```

约束：`transitions` 里出现的 `from` / `to` 必须都在 `status:` 段声明过；`ending_kinds` 里出现的 `requires` 必须都在 §5.3 的字段清单里。`scripts/verify_trace_status.py` 校验这两条。

### 5.2 trace 顶层新增字段

```yaml
ended_at: "2026-10-31T14:32:00+08:00"   # 终态写一次
ending:                                  # 终态必填；重新打开时清空
  kind: handed_off                       # 取 ending_kinds
  handed_to: "张工 · CANN 组"             # kind=handed_off 必填
  duplicate_of: ""                       # kind=duplicate 必填；issue / case 号优先，session_id 只作本机补充
  note: "转给上游时带上了交接包"            # 可选，一句话
transitions:                             # 只追加；本 PR 起每次转移写一条
  - { at: "2026-10-31T14:32:00+08:00", from: in_progress, to: archived,
      kind: handed_off, by: user, source: panel, note: "" }
```

`handed_to` 与 `duplicate_of` 都要求「跨机可解析」：优先写 issue 号、case 号或人名+团队；写本地 `session_id` 时 `duplicate_of` 只作为本机线索，面板会标注「本机线索」。

### 5.3 字段清单（必填校验依据）

`summary`（非空）、`severity`（枚举，见 case-schema）、`fix_emitted`（布尔）、`ended_at`（ISO 8601）、`ending.kind`（枚举）、`ending.handed_to`（非空串）、`ending.duplicate_of`（非空串）。

## 6 组件

### 6.1 投影器 `scripts/trace_state.py`

唯一实现派生判据的地方。`--json` 输出：

```json
{
  "schema": "ascend-sleuth-trace-state/1",
  "generated_at": "…",
  "vocab": {
    "statuses": [{"value":"resolved","label":"已定位","terminal":true,"resumable":false}],
    "endings":  [{"value":"handed_off","label":"转交他人跟进"}],
    "actions":  [{"id":"close-resolved","label":"已定位","to":"resolved","requires":[…]},
                 {"id":"reopen","label":"重新打开","to":"in_progress"}]
  },
  "sessions": [{
    "sessionId": "2026-10-30-0915-verl-nanloss",
    "file": "2026-10-30-0915-verl-nanloss.yaml",
    "status": "resolved",
    "ending": {"kind": "root_cause", "handed_to": "", "duplicate_of": ""},
    "endedAt": "…",
    "feedback": {"outcome": "pending", "pendingSince": "…"},
    "sedimented": {"state": "none", "case_id": ""},
    "derived": {"open": false, "closed": true, "needSed": true, "needReview": false,
                "needPromote": false, "needConfirm": true, "stale": false},
    "actions": ["reopen", "correct-ending"],
    "provenance": {"statusBy": "user", "statusAt": "…", "source": "panel"}
  }]
}
```

派生量的口径（从现有实现搬过来，写明出处，避免口径再造）：

- `closed`：命中单看 `feedback.outcome == resolved`；无命中单看 `status == resolved` 且没有显式 outcome（与 `verify_case_draft.py` 同口径）。
- `needSed` / `needReview` / `needPromote` / 空记录：沿用 `panel-client.js:872-912` 的四条判据，搬进 Python。
- `needConfirm`：`status == resolved` 且 `feedback.outcome == pending`（新增，对应「待现场确认」徽标）。
- `stale`：`in_progress` 且 `updated_at` 超过 N 天（N 由现有 `LEDGER` 的「近 30 天」口径决定，不另造）。

`needConfirm` 与 `needReview` 不重叠：前者是「等现场回报」，后者是「有报告但没有 case 类沉淀候选」。

### 6.2 写入口 `scripts/trace_transition.py`

```
python3 scripts/trace_transition.py <session_id> --to archived --kind handed_off --handed-to "张工 · CANN 组" [--note "…"] \
    [--by user|agent|cli] [--source panel|cli|agent] [--dry-run] [--json]
python3 scripts/trace_transition.py <session_id> --field sedimented --state submitted --inbox-path … [--apply]
```

行为：

1. 解析目标文件（`shared_dir.py traces` 的主检出路径），读当前 `status` 与 `ending`。
2. 按 §4.2 校验：转移是否合法、必填是否齐全、`ending` 取值是否合法。
3. 写入：行级替换 `status` / `ended_at` / `ending` / `updated_at`（保留注释），并在 `transitions:` 下追加一条；先写临时文件再 rename，写完重新解析校验，不一致就回滚。
4. CAS：调用方传入 `--expect-status` 时，若当前值不等则返回 `E_STATE_CHANGED`（退出码 3），面板据此提示「这单已被改为 X」。
5. 输出：人读一行结论；`--json` 给 `{ok, from, to, changed:[…], event:{…}}`，失败给 `{ok:false, code, message, requires:[…]}`。
6. `--dry-run` 只校验不改盘（面板预览与测试用）。

退出码：0 成功；2 参数或必填缺失（含 `requires` 列表）；3 状态已变（CAS 失败）；4 写入后校验失败（已回滚）。

### 6.3 一致性检查 `scripts/verify_trace_status.py`

只做机械可判项，进 CI：

- 词表自洽：`transitions` 的 `from`/`to` 都在 `status` 段；`ending_kinds` 的 `requires` 都在字段清单。
- 每条 trace：终态必须有 `ended_at` 与 `ending.kind`；`handed_off` 必须有 `handed_to`；`duplicate` 必须有 `duplicate_of`；`in_progress` 不得有 `ending`。
- `transitions` 每条：`from`/`to` 合法、与上一条的 `to` 接得上（首条例外）、`at` 是 ISO 8601。
- 不检查历史合法转移（老记录没有事件），只检查字段一致性；`--strict` 才要求每条终态都有 `transitions` 记录。

### 6.4 面板

**RPC（host 侧）**

- `ascend-trace-state`：返回 §6.1 的投影。列表读它与读原 `ascend-traces-list` 合并成一次调用（避免两倍解析），带 TTL 缓存，常量沿用现有 `CACHE_TTL_MS` 的做法。
- `ascend-trace-transition`：参数 `{sessionId, action, payload}`，host 调 `trace_transition.py --json` 并把结果原样回给 client；失败时把脚本的 `requires` 与退出码带回。
- `ascend-update-sedimented`：删除现有行拼接实现，改为调用 `trace_transition.py --field sedimented`。

**权限与降级**

- 写调用显式传 `{mode:'workspace-write', workspaceRoot: <主检出>}`；主检出路径由 `shared_dir.py traces` 解析，解析不到就退回会话 cwd。
- 会话档位不足以写时，按钮渲染为「复制命令」（现有导出交接包的 fallback 思路），点击复制一条可粘贴的命令，不报错、不装作成功。
- 面板包版本：改源码后必须 bump `dsh-plugins/dsh-sleuth-panels/package.json` 的 `version` 并重跑 `scripts/build_panel_bundle.js`。

**client 侧**

- 不再有 `RESUMEABLE` / `statusMeta` / `STATUS_LABEL` / `statusAccent` 四份常量；标签、颜色、可用动作全部来自投影的 `vocab` 与 `actions`。
- 卡片动作区：进行中显示「收尾」入口；终态显示「重新打开」与「修正结论」。点击后在卡片内联展开（不弹窗），选项即投影给的 `actions`。
- 行级入口：状态文字本身是按钮（整行展开按钮之外的兄弟节点），点击同样打开内联编辑器。若实现成本高，PR1 先只做卡片内入口，行级入口排 PR1.5，设计不因此改变。
- 提交后原地更新该行（用 RPC 返回的 `from`/`to` 与事件时间），浮一条「已记录：… · 撤销」；撤销 = 反向转移（终态 → in_progress），记一条事件，不删历史。
- 失败：缺必填时把该字段标红并保留已填内容；`E_STATE_CHANGED` 时提示「这单已被改为 X，是否按当前状态继续」并刷新该行。

### 6.5 skills 侧（PR3，本 PR 只改必须同步的部分）

`diagnose` 与 `resume-diagnosis` 收尾时调用 `trace_transition.py`，不再写「改 YAML」的散文；正文里的状态词表段落改为指向 `trace-status.yaml`。`to-postmortem` 的 `sedimented` 回写同样走脚本。

## 7 面板文案（本 PR 一并改）

| 现在 | 改为 |
|---|---|
| 结局 / 这单结束了？ | 收尾结论 / 本单收尾 |
| 改结局 | 修正结论 |
| 不跟了 | 不再跟进 |
| 转上游 | 转交上游 |
| 与另一单重复 / 没走诊断 / 问题不复现 | 与已有单重复 / 未走诊断 / 问题未复现 |
| 标于 … · 你 | 由你记录于 … |
| 提交 / 撤回 / 批量提交 | 确认收尾 / 撤销 / 应用到已选 N 单 |
| 已定位（有结论）/ 已定位 · fix 生效 | 已定位 · 根因明确 / 已定位 · 现场已验证 |

行文按 `docs/spec/writing-norms.md`：动作与对象分开（收尾是动作、结论是对象）；同一事物一个名字（状态 / 结论 / 回报 / 沉淀）。

## 8 兼容与迁移

- 老 trace 没有 `ending`、没有 `transitions`：投影器以顶层 `status` 为准；`verify_trace_status.py` 默认不要求事件，`--strict` 才要求。
- 首次对老 trace 做转移时，写入口先补一条 `{from: <当前 status>, to: <目标>, source, by}`；不追溯更早的历史。
- 不为历史数据批量补 `ending`：补出来的值只能是猜的。面板对缺失的终态显示「结论未记录」，并在需要时给一次「补记结论」的动作。

## 9 回报轴（设计留接口，PR2 实现）

新增 `field_report` 记录（不是状态值）：

```yaml
field_report:
  source: field | upstream        # 现场验证 / 上游答复，两者不混算（metrics.md:105）
  result: fix_effective | other_way | partial | ineffective
  aligned: true | false           # 现象与报告结论是否一致
  note: "一句话现象"
  at: "…"
  by: user
```

映射：`fix_effective → outcome resolved`；`other_way → outcome resolved + aligned false`；`partial → partial`；`ineffective → not_resolved`。`aligned: false` 时进「待核对结论」，由 agent 判定三种结果：只修订报告（不判误诊）、`case_error`、`execution_error`。面板只记事实，不判对错；日志与截图仍走对话落证据。

## 10 门与验收

1. `python3 scripts/verify_trace_status.py --check`：词表自洽 + 字段一致性。
2. `python3 scripts/verify_trace_status.py --all --strict`：本机 traces 全量（不进 CI，报现状）。
3. `python3 -m unittest tests.test_trace_transition tests.test_trace_state -v`：写入口与投影器的用例（含 CAS、必填缺失、重开、修正结论、老数据）。
4. `python3 scripts/verify_case_draft.py --all`、`python3 scripts/sediment_batch.py`：既有读端不被改动破坏。
5. `node scripts/panel_render_check.js`：新增断言——终态卡不出现收尾入口、编辑器只渲染投影给的 actions、文案无旧词（「结局」「不跟了」「转上游」）、写调用显式带 `workspace-write`。
6. `node scripts/build_panel_bundle.js --check`、`python3 scripts/build_docs_index.py --check`、`python3 scripts/verify_proposals.py --check`（若改卡）。
7. 一条可复跑的 measure：构造一份临时 trace，跑「收尾 → 重开 → 修正结论」三步，断言 `transitions` 三条、终态字段齐全、`verify_trace_status` 通过、投影的 `actions` 在每步只含合法项。

## 11 风险与回退

| 风险 | 处理 |
|---|---|
| 面板写权限不足（worktree / 只读会话） | 降级为复制命令；不无声失败 |
| 并发写同一单 | CAS（`--expect-status`）+ 写入后重解析校验；冲突返回 3 并让面板刷新 |
| 行级替换写坏 YAML | 临时文件 + rename + 重解析；失败回滚并返回 4 |
| 旧面板包与新词表不匹配 | 面板只渲染服务端动作；旧包最多少一个按钮 |
| 既有读端被改坏 | `verify_case_draft` / `sediment_batch` / `export_trace` 的既有测试与命令全部复跑 |

回退：拆分提交，脚本与词表一个提交、面板一个提交、skills 一个提交；面板回退只需重装上一个 bundle 版本（`package.json` 的 `version` 是安装器判新旧依据）。

## 12 分阶段落地

| 阶段 | 内容 | 估时 |
|---|---|---|
| PR1 | 词表转移段 + `trace_state.py` + `trace_transition.py` + `verify_trace_status.py` + 单测 + 面板接投影与内联编辑器（含文案）+ `sedimented` 改写入口 + README 边界白名单 | 3.5 天 |
| PR1.5 | 行级状态按钮（行 DOM 从 `button` 改为 `div role=button`，需要同步面板渲染检查） | 0.5 天 |
| PR2 | 回报轴（§9）：面板回报入口、`field_report` 写入、「待核对结论」派生与核对流程 | 1.5 天 |
| PR3 | skills 去词表：`diagnose` / `resume-diagnosis` / `to-postmortem` 改调脚本 | 0.5 天 |
