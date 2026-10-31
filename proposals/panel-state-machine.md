# 诊断状态机的总体设计：词表、投影、写入口与面板交互

状态：设计稿第 3 版（两轮评审共 11 条阻断、20 条重要已处置，见 §13）
范围：诊断记录（`traces/`）的 `status` 轴与面板上的状态呈现/修改；`feedback` 与 `sedimented` 两轴只定义写入口归属。
读者：实现者、评审者、判断它与仓库既有约束是否冲突的人。

## 1 背景与动机

面板是诊断记录的主要查看面，但改状态要八步：切会话 → 切「诊断」tab → 在列表里重新找到这一单 → 展开 → 点「收尾」→ 选一项 → 复制中文指令 → 粘回对话等 agent 改 YAML。它依赖一个仍然活着的对话。

状态词表与判据散在五个以上读端与三个写点；面板是 JS、脚本是 Python，代码不能共享，只能靠注释提醒「改一处必须同步另一处」（`dsh-plugins/ascend-panel/panel-client.js:846-852`）。

不做的代价：真实收尾方式落不进数据（`archived` 缺「重复」「撤回」；`escalated` 连转给谁都不记，`trace-status.yaml:48-57`）；无命中单的升格闸门只认 `status: resolved`（`verify_case_draft.py:233`），标错一次丢一条本可入库的结论；加一个状态要改五处以上且漏改不报错。

做完的变化：面板上一次直接动作完成收尾，不需要对话；规则只在一门语言（Python）与一个数据文件里，面板不实现判据；每次转移留一条可核对的记录。

## 2 现状核对（全部实测）

| 事实 | 证据 |
|---|---|
| 同一判据五个以上实现 | `verify_case_draft.py:229-236`；`sediment_batch.py:46`；`export_trace.py:196-203`；`replay_trace.py:101-103`；`panel-client.js:857-912`；`panel-host.js:906` 把 `escalated` 计作在办 |
| 面板内标签三份 | `panel-client.js:348`、`:4063`、`:2075`（`archived` 缺项） |
| 面板已在写 trace | `ascend-update-sedimented` → `panel-host.js:233-272` 行拼接 + `fs.writeText`；入口 `panel-client.js:1448`（`caseId` 传成 `s.sessionId`，是 bug） |
| 「只读」声明与代码不符 | `dsh-plugins/README.md` 只读边界行；实际三处写：导出包、重建明细、`sedimented` |
| 写子进程沙箱约束 | `panel-host.js:24-48`：写必须显式 `workspace-write` + `workspaceRoot`，否则默认根是 DSH 检出 |
| `ended_at` 是成本右边界 | `diagnosis_state.yaml.example:40`；`trace_entry_activity.py:481-484`、`:549-575` |
| `resolved_at` 已存在但无人校验 | `diagnosis_state.yaml.example:63` |
| `stop_reason` 与状态语义部分重叠 | `trace_metrics.py:107-110` |
| 报告是活件、修订留痕 | `report-template.md:17-26` |
| 误诊归因只有两值 | `diagnosis-procedure.md:345` |
| S1 现场与 S2 内容验证不混算 | `docs/guide/metrics.md:105` |
| 本机 20 份 trace：`ending` 与 `ended_at` 各 0 份 | `traces/*.yaml` |
| CI 里没有 `traces/` | `.gitignore:7` |
| 列表缓存按文件版本键控 | `panel-host.js:423-434` |
| 面板包版本是安装器判新旧依据 | `dsh-plugins/README.md`「面板包版本」行 |

## 3 目标与非目标

目标：①状态与收尾方式在面板可看可改，写入可校验、可追溯、可撤销；②加状态/加转移/改必填只改 `trace-status.yaml` 一处，Python 读端调库、JS 无判据；③老数据不判违规、不清洗；④失败与降级可见，不假装成功、不写错检出。

非目标（本 PR）：回报轴（PR2，§9）；批量收尾（PR2）；跨机同步与认领（`handoff.md:149`）；新增状态值。

## 4 状态模型

### 4.1 状态

| 值 | 面板标签 | 含义 | 终态 | 可续接 |
|---|---|---|---|---|
| `in_progress` | 进行中 | 未给出结论，或结论已给出但仍在跟进 | 否 | 是 |
| `resolved` | 已定位 | 定位结论已写入报告。**不表示 fix 在现场生效** | 是 | 否 |
| `escalated` | 已转交他人 | 本地不再跟进，已交给别人（厂商 / 技术支持 / 同事）；必填转交给谁 | 是 | 否 |
| `archived` | 不再跟进 | 不再跟进且没人接手（未复现 / 重复 / 未走诊断 / 主动撤回） | 是 | 否 |
| `unknown` | 状态未记录 | 旧记录未写状态；新写入不使用 | 否 | 否 |

行为变更两条，PR 里写明：①`escalated` 标签从「已转上游」改为「已转交他人」，语义扩到任何接手方；面板旧的 `RESUMEABLE = { escalated: true }`（`panel-client.js:359`）删除。②「有人接手了」只由 `escalated` 表达，不再塞进 `archived`。

### 4.2 收尾方式（`ending`）

| kind | 面板标签 | 必填 | 用于状态 |
|---|---|---|---|
| `root_cause` | 根因明确 | 无 | `resolved` |
| `handed_off` | 转交他人跟进 | `handed_to` | `escalated` |
| `not_reproducible` | 问题未复现 | 无 | `archived` |
| `duplicate` | 与已有单重复 | `duplicate_of` | `archived` |
| `no_diagnosis` | 未走诊断 | 无 | `archived` |
| `withdrawn` | 主动撤回 | 无 | `archived` |

**所有终态都写 `ending`，包括 `resolved`**（写 `{kind: root_cause}`）。否则「终态必有收尾方式」与面板行为互相打架：面板收出来的单会立刻显示「未记录收尾方式」，`--strict` 也红。`root_cause` 在列表上不显示徽标（常态）。

`withdrawn` 与 `no_diagnosis` 的边界：`no_diagnosis` 是「从未开始诊断」，`withdrawn` 是「进行过但主动中止且没有结论」（如材料不足）；两者都不下 fix 是否有效的判断。

`handed_to` 写「名字 · 团队」或 issue 号；`duplicate_of` 收窄为 `case:<id>` / `session:<session_id>`，本机可校验（`session:` 用 `sediment_batch.py:66-76` 的命名归组规则）。

### 4.3 转移表

| 从 | 到 | 本次写 | 必须已存在 |
|---|---|---|---|
| `in_progress` / `unknown` | `resolved` | `requires: [resolved_at]`（写入口填写盘时刻）；`fillable: [summary, severity, fix_emitted]` | 命中真实 case 时 `feedback.outcome` |
| `in_progress` / `unknown` | `escalated` | `requires: [ending.handed_to]`；`fillable: [summary]` | 无 |
| `in_progress` / `unknown` | `archived` | `requires: [ending.kind]`（`duplicate` 另需 `ending.duplicate_of`）；`fillable: [summary]` | 无 |
| 任意终态 | `in_progress` | 无（`ending` 移入事件后清空顶层） | 无 |
| 带 `ending` 的终态 | 另一终态 | 同对应收尾行 | 同对应行 |
| 缺 `ending` 的终态 | 同一终态 | `requires: [ending.kind]`（补记，不重开） | 无 |

规则：

1. **字段三类**：`requires` 本次必须提供并写盘；`fillable` 已有就沿用、缺失时面板给输入位并由写入口写盘；`must_exist` 必须已存在，写入口不写、面板不给输入位（缺失时给「先去回报」引导与可复制命令）。
2. **`ended_at` 不参与收尾**（它是成本右边界）。收尾时刻记 `transitions[-1].at`；`resolved` 另写 `resolved_at`（同一次写盘的时刻，ISO 8601 日期）。
3. **`stop_reason` 由写入口写 `closed_by_user`**，agent 可 `--stop-reason` 覆盖。该值必须同步加到 `trace_metrics.py` 的 `KNOWN_STOP_REASONS`（`:107-110`）与 `diagnosis-trace.md` 的停止点词表；不同步，面板收尾的单会被既有指标报成词表外违规。
4. 三条轴不互相赋值：`resolved` 不写 `feedback`；`feedback.outcome: resolved` 不改 `status`。

### 4.4 为什么不新增状态值

「已定位但等现场确认」是 `status: resolved` 加 `feedback.outcome: pending`。面板用徽标与点形区分三态：**待回报 / fix 已验证 / 回报与报告不一致**；这三个名字全仓统一，不再出现「已确认」「待现场确认」等变体。

## 5 数据契约

### 5.1 `trace-status.yaml` 改动

`status:` 段要改三条（面板标签与含义都从这份文件读）：`escalated` → `label: 已转交他人`、`meaning: 本地不再跟进，已交给别人`、`when_to_set: 本地无法定位或问题归属别人；必须记 ending.handed_to`；`archived` → `meaning: 不再跟进且没有人接手`、`when_to_set: 未复现 / 与已有单重复 / 未走诊断 / 主动撤回`；`unknown` → `label: 状态未记录`。

新增：

```yaml
axes:
  - { field: status,     writer: scripts/trace_transition.py,                   stage: PR1 }
  - { field: outcome,    writer: scripts/trace_transition.py --field outcome,   stage: PR2 }
  - { field: sedimented, writer: scripts/trace_transition.py --field sedimented, stage: PR1 }

stop_reasons:
  - { value: closed_by_user, label: 用户在面板收尾 }   # 其余值在 trace_metrics.py，PR1 只加这一个

ending_kinds:
  - { value: root_cause,       label: 根因明确,     statuses: [resolved] }
  - { value: handed_off,       label: 转交他人跟进, statuses: [escalated], requires: [ending.handed_to] }
  - { value: not_reproducible, label: 问题未复现,   statuses: [archived] }
  - { value: duplicate,        label: 与已有单重复, statuses: [archived], requires: [ending.duplicate_of] }
  - { value: no_diagnosis,     label: 未走诊断,     statuses: [archived] }
  - { value: withdrawn,        label: 主动撤回,     statuses: [archived] }

transitions:
  - { from: [in_progress, unknown], to: resolved,  action: close-resolved,  action_label: 已定位,
      ending: root_cause, requires: [resolved_at], fillable: [summary, severity, fix_emitted],
      must_exist_if_case: [feedback.outcome], expands_to: [] }
  - { from: [in_progress, unknown], to: escalated, action: close-escalated, action_label: 转交他人跟进,
      ending: handed_off, requires: [ending.handed_to], fillable: [summary], expands_to: [] }
  - { from: [in_progress, unknown], to: archived,  action: close-archived,  action_label: 不再跟进,
      ending_choices: [not_reproducible, duplicate, no_diagnosis, withdrawn],
      requires: [ending.kind], fillable: [summary], expands_to: [] }
  - { from: [resolved, escalated, archived], to: in_progress, action: reopen,
      action_label: 重新打开, expands_to: [] }
  - { from: [resolved, escalated, archived], to: [resolved, escalated, archived], except_same: true,
      action: correct-ending, action_label: 改收尾方式,
      expands_to: [reopen, close-resolved, close-escalated, close-archived] }
  - { from: [resolved, escalated, archived], to: [resolved, escalated, archived], same_status: true,
      action: backfill-ending, action_label: 补记收尾方式,
      requires: [ending.kind], expands_to: [] }
```

键定义（`verify_trace_status.py --check` 全查）：`from`/`to` 元素必须是 `status:` 段声明过的值；`except_same: true` 表示 `to` 里与当前状态相同的那个不合法；`same_status: true` 是唯一允许状态不变的动作（补记）；`expands_to` 必须是本段出现过的 action id，空列表表示不展开；`ending`/`ending_choices` 必须与 `ending_kinds[].statuses` 一致；`must_exist_if_case` 是命中真实 case 时才要求的 `must_exist`。字段引用一律写 §5.3 的路径（`ending.handed_to`）。

### 5.2 trace 顶层字段

```yaml
ending:                                  # 终态必填；重新打开时清空（旧值进事件）
  kind: handed_off
  handed_to: "张工 · CANN 组"
  duplicate_of: ""
  note: ""
transitions:                             # 只追加
  - at: "2026-10-31T14:32:00+08:00"
    from: in_progress
    to: escalated
    ending: { kind: handed_off, handed_to: "张工 · CANN 组", duplicate_of: "", note: "" }
    prev_ending: null
    by: user                             # user | agent | cli
    source: panel                        # panel | cli | agent | import
    note: ""
```

`ended_at` 不改写。收尾时刻从 `transitions[-1].at` 读；老数据没有事件时退回 `updated_at`，投影标 `timeSource: updated_at`。

### 5.3 字段清单

`summary`（非空）、`severity`（枚举，见 `docs/spec/case-schema.md`）、`fix_emitted`（布尔）、`resolved_at`（ISO 8601 日期）、`ending.kind`（枚举）、`ending.handed_to`（非空）、`ending.duplicate_of`（`case:` / `session:` + 非空 id）、`feedback.outcome`（枚举）。

## 6 组件

### 6.1 库 `scripts/_trace_state.py`

```python
load_traces(traces_root) -> list[Trace]        # 解析 + 容错 + 每份文件算 sha256
derive(trace, kb_case_ids) -> Derived          # 纯函数
actions_for(trace, vocab, can_write) -> list   # 合法动作
project(traces_root, kb_root, caps) -> dict    # 面板与 CLI 共用
```

**投影 JSON（客户端唯一消费的形状）**：

```json
{
  "schemeVersion": "ascend-sleuth-trace-state/1",
  "generatedAt": "2026-10-31T18:00:00+08:00",
  "capabilities": {"canWrite": true, "writeRoot": "/abs/ascend-sleuth", "reason": ""},
  "vocab": {
    "statuses": [{"value": "resolved", "label": "已定位", "terminal": true, "resumable": false,
                  "color": "var(--c-green)", "accent": "var(--acc-green)", "order": 20}],
    "endings": [{"value": "handed_off", "label": "转交他人跟进", "requires": ["ending.handed_to"]}],
    "severities": [{"value": "benign"}, {"value": "service-affecting"}, {"value": "data-loss-risk"}],
    "actions": [{"id": "close-archived", "label": "不再跟进", "to": "archived",
                 "requires": ["ending.kind"], "fillable": ["summary"], "mustExist": [],
                 "endingChoices": [{"value": "duplicate", "label": "与已有单重复",
                                    "requires": ["ending.duplicate_of"]}]}]
  },
  "sessions": [{
    "sessionId": "2026-10-30-0915-verl-nanloss", "file": "2026-10-30-0915-verl-nanloss.yaml",
    "contentSha256": "…", "status": "resolved",
    "ending": {"kind": "root_cause", "handed_to": "", "duplicate_of": "", "note": ""},
    "feedback": {"outcome": "pending", "pendingSince": "…"},
    "sedimented": {"state": "none", "case_id": ""},
    "provenance": {"statusBy": "agent", "statusAt": "…", "source": "agent", "timeSource": "transitions"},
    "derived": {"open": false, "closed": true, "needSed": true, "needReview": false, "needPromote": false,
                "needConfirm": true, "skeleton": false, "submitted": false,
                "caseKind": "none", "sedState": "none", "valueRank": 4},
    "transitions": [{"at": "…", "from": "in_progress", "to": "resolved", "ending": "root_cause",
                     "by": "agent", "source": "agent"}],
    "actions": ["reopen", "correct-ending"]
  }]
}
```

派生量口径与出处：`closed`（命中单看 `feedback.outcome == resolved`；无命中单看 `status == resolved` 且无显式 outcome，`verify_case_draft.py:229-236`）、`sedState`（`panel-client.js:854`）、`caseKind`（占位串正则同 `panel-host.js:337-344`）、`skeleton`（`panel-client.js:884`）、`open`/`needSed`/`needReview`/`needPromote`（`panel-client.js:857-912`）、`needConfirm`（`resolved` 且 `outcome == pending`，新增）、`submitted`（`panel-client.js:906`）、`valueRank`（`panel-client.js:915-935` 的档次与破平，必须搬，那里自己写着「两处各算一份就会给出两套价值」）、`timeSource`（有 `transitions` 用 `at`，否则 `updated_at`）。

### 6.2 CLI `scripts/trace_state.py`

薄封装：`--json` 打印 `project(...)`；`--session <id>` 打单条；`--check` 只做词表自洽（CI 用）。投影自带 mtime+size 缓存（`traces/` 11MB、单份最大约 104KB），缓存放 `traces/.state-cache.json`，schema 变更即丢弃重建。

### 6.3 写入口 `scripts/trace_transition.py`

```
python3 scripts/trace_transition.py <sid> --to archived --kind duplicate --duplicate-of case:VLLM-ASC-11312 \
    [--summary …] [--severity …] [--fix-emitted true|false] [--stop-reason closed_by_user] \
    [--by user] [--source panel] [--expect-sha256 <hex>] [--dry-run] [--json]
python3 scripts/trace_transition.py <sid> --field sedimented --state submitted --inbox-path … [--dry-run]
python3 scripts/trace_transition.py <sid> --reopen [--json]
```

要求：

1. 定位顶层键用 `yaml.compose()` 的 mark，不用正则找 `^status:`（block scalar 里可能出现同名文本）。
2. 写前取 `log_lock`（`scripts/exec_log_path.py:215`）；`os.replace` 原子替换；换行风格用 `_stdio.write_text_lf`；保留 BOM / CRLF / 无尾换行。
3. 写后重解析并深比较未被触碰的顶层键，不一致回滚（退出码 4）。
4. CAS：`--expect-sha256` 比对内容哈希；未传时按 status + ending 比对（面板路径必须传）。
5. 写集合：`status`、`ending`、`resolved_at`（仅 resolved）、`updated_at`、`stop_reason`，加本次传入的 `fillable`；其余不动。
6. 事件：`at`、`from`、`to`、`ending`（本次后的完整快照，重开时 `null`）、`prev_ending`、`by`、`source`、`note`。
7. 输出：人读一行；`--json` 给 `{ok, from, to, changed, event, current}`；失败给 `{ok:false, code, message, requirements:[…]}`。
8. **写入语义统一**：三个子命令默认写盘，`--dry-run` 才只校验（不沿用 `sediment_batch.py` 那套 `--apply`）。

场景 → 退出码 → `code` → 客户端一句人话（client 只认 `code`）：

| 场景 | 退出码 | code | 人话 |
|---|---|---|---|
| 成功 | 0 | — | 已记录 |
| 缺必填 / 非法转移 / 词表不符 | 2 | `E_SCHEMA` | 「缺 X」或「这一步不允许」+ 缺失字段 |
| CAS 冲突 | 3 | `E_STATE_CHANGED` | 「已被 {谁} 于 {时间} 改为 {状态}」 |
| 写后校验失败（已回滚） | 4 | `E_IO` | 「写入失败，记录未改动」 |
| trace 不存在 | 6 | `E_NOT_FOUND` | 「这一单不在这台机器上」 |
| 主检出不唯一 / 不可写 | 5 | `E_PERM` | 「当前会话没有写权限」+ 复制命令 |
| 脚本版本不匹配 | 7 | `E_SCHEMA_VERSION` | 「主检出的脚本与面板版本不一致」 |

### 6.4 一致性检查 `scripts/verify_trace_status.py`

- `--check`（CI，不需要 traces）：词表自洽（§5.1 全部键与引用）+ grep 门（状态字面量只许出现在 `trace-status.yaml` 与 `_trace_state.py`）。
- `--all`（本机报现状）：字段一致性与事件校验——终态必有 `ending`；`handed_off` 有 `handed_to`；`duplicate` 有 `duplicate_of`；`in_progress` 无 `ending`；有 `transitions` 的单校验每条 `from`/`to` 合法、与上一条 `to` 接得上、`at` 是 ISO 8601、`ending`/`prev_ending` 形状正确；另列「老终态单缺收尾方式」计数。**grandfather**：只有带 `transitions` 的单做「终态必有 ending」；**导入单**（`traces/handoff/<sid>.yaml` 存在）不计入 `--strict`。
- `--strict`（本机）：所有非导入终态单都要有 `transitions` 与 `ending`。

### 6.5 面板

RPC：

- `ascend-traces-list` 保持形状，每单新增 `state`（§6.1 的 session 片段）。`state` **不进** `INDEX_CORE_FIELDS`（依赖 KB 检出与 host 能力），每次刷新由 host 现算；`INDEX_SCHEMA` 只在新增 core 字段时 +1。
- `ascend-trace-transition`：`{sessionId, action, payload, expectSha256}`，`expectSha256` **必填**（来自投影 `contentSha256`）；host 原样转发并回传，不判对错。
- `ascend-update-sedimented`：删除行拼接，改调 `trace_transition.py --field sedimented`；顺手修 `caseId: s.sessionId` 的 bug。
- `ascend-process-health` 与 `ascend-session-marks` 的「在办」改读 `derived.open`（现在把 `escalated` 计作在办，`panel-host.js:906`）。
- `ascend_trace_status` 工具补 `ending.label` 与 `nextActions`（工具 schema 是 `additionalProperties: false`，需同步）。
- `ascend-traces-detail` 的收尾区补 `transitions`（只读折叠「收尾记录」）。

能力位与降级：

- `canWrite` / `writeRoot` **只用** `mainCheckoutOf(rawCwdOf(sessionId))`（`panel-host.js:136-176`）判断，不复用 `resolveCwd()` 的返回值——它解析不到时会退回会话 cwd（`panel-host.js:186-191`），正好会写出「状态写进 worktree、面板仍读主检出」的错。解析不到即 `canWrite:false`，写入口退出码 5。
- `canWrite:false` 时入口按钮不变，编辑器照常收集必填；最后一步的「确认收尾」换成「复制命令（在仓库根目录运行）」，命令带已填值、sessionId 与 sha256。
- 写入的 workspaceRoot 一律用 `writeRoot`；脚本自己解析文件也只用主检出，解析不到 fail closed（5），不退回会话 cwd。
- 握手：脚本输出 `schemeVersion`，host 不接受未知版本并提示刷新面板包。

客户端：

- 删除 `RESUMEABLE`、`statusMeta`、`STATUS_LABEL`、`statusAccent`；标签、颜色、动作、kind 候选全部来自投影。
- 动作区：进行中 →「收尾」（三个动作）；有 `ending` 的终态 →「重新打开」+「改收尾方式」；缺 `ending` 的终态 →「补记收尾方式」+「重新打开」。后两者互斥。
- 编辑器：打开时焦点进编辑器标题并 `scrollIntoView({block:'nearest'})`；`↑↓/←→` 组内移动，`Enter` 选中并落到必填，`Enter` 在提交按钮上提交，`Esc` 关闭并把焦点还给触发按钮；有输入时用原生 `confirm()` 确认后丢弃。数字键个数按投影动作数动态生成（PR1 为 `1-3`），号码印在选项上，输入框聚焦时不生效。
- 无障碍：`role=radiogroup` + `aria-checked` + `aria-labelledby` 指向编辑器标题；触发按钮 `aria-expanded`/`aria-controls`；错误 `role=alert` + `aria-invalid` + `aria-describedby` 并把焦点移到第一个错误字段；成功条 `role=status` + `aria-live=polite`；`.dot`/`▾` 加 `aria-hidden`；触发按钮最小 32px 高、左右 8px。
- 提交：只在 RPC `ok:true` 后更新；提交中禁用并显示「正在写入…」；失败按 `code` 给原因与下一步，保留编辑器与已填内容；`E_STATE_CHANGED` 的 `{谁}` 映射成「本机用户 / agent / 命令行」、时间 `MM-DD HH:mm`、状态用面板标签；新状态是终态时只给「刷新查看」与「复制命令」，仍是进行中才给「按当前状态重试」。
- 成功后用返回的完整投影刷新该行；若不匹配当前筛选，留在原位显示「已从本筛选移出 · 撤销」，不立即消失。
- 「改收尾方式」成功后 toast「原记录保留，可在收尾记录里查看」；展开态「收尾记录」折叠渲染 `transitions`（时间、从→到、收尾方式、来源）。
- 行级入口：行保持现有 `<button>`；状态按钮作为行按钮之外的兄弟节点（flex 包一层），不改行 DOM、不牺牲键盘可达性。PR1 只做卡片内入口；不做行级入口时撤掉小三角、hover 下划线与 `cursor:pointer`。

列表信息预算：

- 收起态第二行最多一个收尾方式徽标（`root_cause` 不显示）+ 一个欠账徽标（待回报 / 待沉淀 / 报告待复核）。
- 记录来源右对齐固定槽位（「记录于 10-31 14:32 · 本机用户 / agent / 上一台机器」），窄屏隐藏留 tooltip。
- 状态列按进度上色：进行中蓝、已定位绿、已转交他人灰、不再跟进灰、未记录空心灰；`resolved + feedback: not_resolved / partial` 不用绿（改灰），否则与旁边「fix 未生效」红徽标矛盾；`resolved + pending` 用空心琥珀环。README 颜色角色表加例外：状态列颜色表达进度，不表达「该不该你做事」；绿色不表示 fix 已验证。

### 6.6 既有写者白名单与 skills

- 白名单（**不是转移、不追加 `transitions`**）：`trace_begin.py`（建单写初始 `in_progress`）、`import_trace.py`（导入状态）、`sediment_batch.py`（`sedimented` 回写，PR3 改调写入口）。
- `--strict` 排除导入单，否则交接包来的终态单永远过不了。
- `diagnose` / `resume-diagnosis` 收尾改调 `trace_transition.py`，正文状态词表段落指向 `trace-status.yaml`（PR3）。
- `to-postmortem` 的 `sedimented` 回写改调 `trace_transition.py --field sedimented`（PR3）。

## 7 面板文案

| 现在 | 改为 | 说明 |
|---|---|---|
| 结局 / 这单结束了？ | 收尾方式 / 本单收尾 | 「结论」只留给定位结论 |
| 改结局 / 修正结论 | 改收尾方式 | 说明「会留下两条记录：重新打开、再收尾」 |
| 不跟了 | 不再跟进 | |
| 转上游 / 已转上游 | 转交他人跟进 / 已转交他人 | 接手方可为厂商、技术支持或同事 |
| 已定位（有结论）/ 已定位 · fix 生效 | 已定位（结论已写入报告） | 已验证是徽标，不进收尾选项 |
| 与另一单重复 / 没走诊断 / 问题不复现 | 与已有单重复 / 未走诊断 / 问题未复现 | |
| 标于 … · 你 / 已标为 / 标过 / 终态 / 重开 | 记录于 … · 本机用户 / 已记录为 / 记录过 / 已收尾的单 / 重新打开 | 「由你」在导入单上是假的 |
| 待现场确认 / 等回报 / 待回报 | 待回报 | 一个状态一个名字 |
| 结论待核对 / 待核对结论 / 待复核 | 报告待复核（任务） / 回报与报告不一致（事实） | 两个「待核对」互为倒装 |
| 提交 / 撤回 / 批量提交 / 应用到已选 N 单 | 确认收尾（转交时「确认转交」）/ 撤销（回到进行中）/ 收尾这 N 单 | 批量排 PR2 |
| 没有对应案例 / 无对应案例 / 无内容记录 | 未命中知识库 case / 空记录 | 同一事物两名 |
| 结算于 / agent 收尾 | 由 agent 记录于 … | 「结算」是银行词 |
| 结论未记录 / 补记结论 | 未记录收尾方式 / 补记收尾方式 | |
| `E_STATE_CHANGED` 等错误码上屏 | 只给人话 +「复制命令」 | 内部码进 tooltip |
| `vllm 0.6` | `vLLM 0.6` | 行文规范 |
| 回报现场结果 / 上游答复（PR2） | 回报结果 / 厂商答复 | 来源选「厂商答复」时「现场」不成立 |
| 按报告的修复解决 / 用别的方法解决 / 部分解决 / 没解决（PR2） | fix 生效（按报告）/ fix 生效（其他方法）/ 部分生效 / 未生效 | 与 outcome 词表一致 |

## 8 兼容与迁移

- 老 trace 无 `ending` / 无 `transitions`：投影以顶层 `status` 为准，`timeSource` 标 `updated_at`；`--all` 只列计数，`--strict` 才要求（且排除导入单）。
- 首次给老单补记时追加完整事件：
  ```yaml
  - { at: "2026-10-31T14:32:00+08:00", from: archived, to: archived,
      ending: {kind: duplicate, handed_to: "", duplicate_of: "case:VLLM-ASC-11312", note: ""},
      prev_ending: null, by: user, source: panel, note: "补记收尾方式" }
  ```
- 不为历史数据批量补 `ending`；面板对缺 `ending` 的终态单给「补记收尾方式」（同状态写，不重开）。
- `ended_at` 保持原义，不由写入口改写。

## 9 回报轴（PR2 设计留接口）

`field_report`（不是状态值）：`source: field|vendor`、`result: effective|other_way|partial|ineffective`、`note`、`at`、`by`。映射：`effective → outcome resolved`；`other_way → resolved + 回报与报告不一致`；`partial → partial`；`ineffective → not_resolved`。「不一致」进「报告待复核」，agent 判三种结果：只修订报告（不判误诊）、`case_error`、`execution_error`。面板只记事实；日志与截图仍走对话落证据。

## 10 门与验收

1. `python3 scripts/verify_trace_status.py --check`：词表自洽 + 状态字面量 grep 门（CI 可跑）。
2. `python3 scripts/verify_trace_status.py --all`：本机字段与事件一致性（老单只报计数）。
3. `python3 -m unittest discover tests -v`：新增 `tests/test_trace_transition.py`、`tests/test_trace_state.py`。
4. 既有读端回归：`verify_case_draft.py --all`、`sediment_batch.py`、`export_trace.py --list`、`replay_trace.py --help`、`metrics_health.py`。
5. `node scripts/panel_render_check.js`（断言用渲染文本）：终态卡无「收尾」入口；缺 `ending` 的终态卡只有「补记收尾方式」+「重新打开」；进行中卡无「重新打开」；只渲染投影给的 actions，未知 action 不渲染；数字键数 = 选项数；旧词按 §7 逐行生成精确 token 禁用（`结局`、`不跟了`、`转上游`、`标于`、`终态`、`重开`、`结算于`、`待现场确认`、`结论待核对`、`没有对应案例`、`上游答复`、`vllm`）；`aria-expanded`/`aria-checked`/`role=alert`/`aria-live`/`aria-labelledby` 存在；写调用分两类断言（转移与沉淀带 `workspace-write` + `--expect-sha256` + `--json`；导出与重建只带 `workspace-write`），替换 `panel_render_check.js:2416-2422` 的全局计数；四组失败用例（缺必填、CAS 冲突、`canWrite:false`、RPC 失败）保留内容并给复制命令。
6. `check_panel_tokens.js`、`check_panel_bundle.js`、`panel_rpc_probe.js --selftest`：RPC 计数与 fs 守卫同步、新端点 stub。
7. `build_panel_bundle.js --check` + `package.json` 版本 bump。
8. `build_docs_index.py --check`；`trace_metrics.py` 与 `diagnosis-trace.md` 已含 `closed_by_user`。
9. 可复跑 measure：临时 trace 上跑「收尾 → 重新打开 → 改收尾方式」，断言 `transitions` 三条、`prev_ending` 完整、`resolved_at` 已写、`--check` 通过、`actions_for` 每步只给合法项。
10. 人审清单（写进 PR body）：收尾方式是否互斥；焦点顺序与播报；颜色语义与列表可扫性；60 单密度；文案语气。

## 11 风险与回退

| 风险 | 处理 |
|---|---|
| 写权限不足 / 主检出不唯一 | `capabilities`（只用 `mainCheckoutOf`）+ 退出码 5 + fail closed + 复制命令 |
| 并发写同一单 | `log_lock` + `--expect-sha256` + 写后深比较；冲突返回 3 与 `current` |
| 行替换写坏 YAML | `yaml.compose()` + `os.replace` + 深比较 + 回滚；测试覆盖块标量内出现 `status:`、CRLF、BOM、无尾换行 |
| 旧面板包与新词表不匹配 | 面板只渲染服务端动作；握手失败给提示 |
| 既有读端被改坏 | 五条既有命令与 `unittest` 全跑 |
| 老数据被误判 | grandfather + 导入单排除 + `--all` 只报计数 |

回退：脚本与词表一个提交、面板一个提交、skills 一个提交；面板回退重装上一个 bundle 版本。

## 12 分阶段落地

| 阶段 | 内容 | 估时 |
|---|---|---|
| PR1 | 词表 + `_trace_state.py` + `trace_state.py` + `trace_transition.py` + `verify_trace_status.py` + 单测 + 面板接投影与卡片内编辑器（文案、无障碍、失败路径、收尾记录）+ `sedimented` 改写入口 + 读端改调库 + 门与断言同步 + README 边界白名单 | 4 天 |
| PR1.5 | 行级状态按钮（行按钮 + 兄弟节点布局） | 0.5 天 |
| PR2 | 回报轴（§9）+ 批量收尾（逐单 sha、逐单结果、预览） | 2 天 |
| PR3 | skills 去词表 | 0.5 天 |

## 13 评审处置（两轮合并）

| 问题 | 处置 | 落点 |
|---|---|---|
| handed_off 在两状态间矛盾（A-B1 / U-I4） | 转交只走 `escalated`；archived 四种 kind 全部「没人接手」 | §4.1/§4.2/§5.1 |
| 老数据被判违规（A-B2） | grandfather + 导入单排除 + `--strict` 边界 | §6.4/§8/§6.6 |
| CAS 丢更新（A-B3） | 内容 sha256 + `log_lock` + 写后深比较 | §6.3 |
| 重开丢字段（A-B4） | 事件带 `ending` / `prev_ending` 快照 | §5.2/§6.3 |
| 投影契约不足（A-B5 / A2-B2） | §6.1 完整 JSON：statuses 含 color/order、endings、severities、actions 含三类字段与 kind 候选、derived 全集、capabilities、sha256 | §6.1 |
| outcome 规则无落点（A-B6） | `requires`/`fillable`/`must_exist` 三类，outcome 归 `must_exist_if_case` | §4.3/§5.1 |
| `resolved_at` 无写者（A2-B1 / U-G10） | 进 `close-resolved` 的 `requires`，写入口填写盘时刻 | §4.3/§5.1/§6.3 |
| 配色三处互斥（A2-B3 / U-G3） | 按进度上色 + README 例外 + 反向回报不用绿 | §6.5/§14 |
| 哨兵值与 backfill（A2-B4 / U-G2） | 定义 `except_same`/`same_status`/`expands_to`，补 `backfill-ending`；终端两动作互斥 | §5.1/§6.5 |
| `closed_by_user` 未同步（A2-I5） | 写进规则 3 与 §10.8 | §4.3/§10 |
| sha 无来源（A2-I6 / U-G4） | 投影每单 `contentSha256`，RPC 必填 | §6.1/§6.5 |
| 三类字段定义不清（A2-I7） | §5.1 三类定义与校验 | §5.1 |
| strict 与导入单冲突（A2-I8） | 排除导入单 | §6.4/§6.6 |
| 三条「已处置」没落正文（A2-I9） | 投影缓存（§6.2）、`replay_trace` 进 §6.5/§10.4、颜色与 severity 进 §6.1 | 各节 |
| 事件校验与示例（A2-I10） | §6.4 写回校验；§8 示例补全 | §6.4/§8 |
| `state` 被版本缓存（A2-I11） | `state` 不进 `INDEX_CORE_FIELDS`，每次刷新现算 | §6.5 |
| 退出码与 E 码无映射（A2-I12 / U-G6） | §6.3 映射表 | §6.3 |
| withdrawn 边界与断言词（A2-I13） | §4.2 写边界；断言 token 按 §7 生成 | §4.2/§10 |
| 未定义键与字段写法（A2-I14） | §5.1 键定义与路径写法 | §5.1 |
| 行号引用错（A2-I15） | 改 `panel-client.js:854`、`panel_render_check.js:2416-2422` | §6.1/§10 |
| 白名单与分阶段冲突（A2-I16） | `axes` 标 `stage`，白名单写「不是转移」 | §5.1/§6.6 |
| CLI 语义不一致（A2-I17） | 三子命令默认写盘，`--dry-run` 才校验 | §6.3 |
| 两轴并成一个枚举（U-B1） | 收尾只留「已定位」；已验证是徽标 | §4.4/§7 |
| 必填项界面填不了（U-B2） | `requires` 进表单，`fillable` 给输入位，`must_exist` 给引导 | §4.3/§5.1 |
| 批量伪造事实（U-B3） | 移出 PR1；「未复现/重复」不许批量 | §3.2/§12 |
| 失败与降级不完整（U-B4 / U-G5 / U-G7） | 错误码表 + 只在 ok 后更新 + fail closed + 能力位只用 `mainCheckoutOf` + 入口不变、末步换复制命令 | §6.3/§6.5 |
| 行级入口矛盾（U-B5 / U-I9） | 行按钮 + 兄弟节点；PR1 不做则撤可点外观 | §6.5/§12 |
| `root_cause` 不写盘（U-G1） | 所有终态都写 `ending`，`root_cause` 不显示徽标 | §4.2 |
| 数字键 1-4 与 3 个动作（U-G8） | 按投影动作数动态生成 | §6.5 |
| 旧词断言漏项/误伤（U-G9） | 按 §7 逐行生成 token；写调用分两类断言；行号改正 | §10 |
| 新术语没回写 §7（U-G11） | 统一「fix 已验证」「报告待复核」；`by` 映射成人话 | §7/§6.5 |
| 键盘与无障碍（U-I1 / U-I2 / S2） | 焦点入编辑器、方向键组内、Enter 选中/提交、Esc 还焦点、`confirm()`；`aria-labelledby` 等全套 | §6.5 |
| 终态动作语义（U-I3） | 「改收尾方式」+ 两条记录说明 + 收尾记录折叠 | §6.5 |
| 文案表未落地（U-I5） | §7 整表 | §7 |
| 颜色越界与不可能组合（U-I6） | 状态列按进度上色 + 反向回报例外；删无命中单的「fix 已验证」 | §6.5/§14 |
| 60 单信息预算（U-I7） | 第二行最多两个徽标；来源固定槽位；筛选移出留原位 | §6.5 |
| 渲染断言误伤（U-I8） | 渲染文本 + 精确 token + 逐调用点 + 四组失败用例 | §10.5 |
| 「查看历史」缺入口（U-S1） | 展开态「收尾记录」折叠 | §6.5 |

## 14 已定的取舍

1. **状态列按进度上色**，不整体改中性色；README 颜色角色表加例外；`resolved + not_resolved/partial` 不用绿，`resolved + pending` 用空心琥珀环。
2. **`withdrawn` 保留**：`no_diagnosis` = 从未开始诊断，`withdrawn` = 进行过但主动中止且无结论。
3. **`escalated` 标签**改为「已转交他人」，不保留「上游」父标签；接手方类型由 `handed_to` 自由文本与输入提示表达。
4. **批量收尾**排 PR2，逐单 `--expect-sha256`、逐单结果；「问题未复现 / 与已有单重复」不允许批量。
5. **行级入口**排 PR1.5；PR1 只做卡片内入口，且不做行级可点外观。
