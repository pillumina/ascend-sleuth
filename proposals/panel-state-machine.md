# 诊断状态机的总体设计：词表、投影、写入口与面板交互

状态：设计稿第 2 版（第 1 轮评审的 6 条阻断 + 5 条阻断已处置，见 §13）
范围：诊断记录（`traces/`）的 `status` 轴与面板上的状态呈现/修改；`feedback` 与 `sedimented` 两轴只定义边界与写入口归属，判据不在本 PR 内改。
读者：实现者、评审者、要判断它与仓库既有约束是否冲突的人。

## 1 背景与动机

### 1.1 触发

面板是诊断记录的主要查看面，但改状态要八步：切会话 → 切「诊断」tab → 在列表里重新找到这一单 → 展开卡片 → 点「收尾」→ 选一项 → 复制一句中文指令 → 粘回对话等 agent 改 YAML。它依赖一个仍然活着的对话。

状态词表与判据散在五个读端与三个写点里；面板是 JS、脚本是 Python，代码不能共享，只能靠注释提醒「改一处必须同步另一处」（`dsh-plugins/ascend-panel/panel-client.js:846-852`）。

### 1.2 不做的代价

- 用户的真实收尾方式落不进数据：`archived` 只覆盖「问题自行消失 / 环境变更后不复现 / 没走诊断」（`trace-status.yaml:48-57`），缺「与已有单重复」与「主动撤回」；「有人接手了」只能塞进 `escalated`，而 `escalated` 连转给谁都不记。
- 无命中单的升格闸门只认 `status: resolved`（`scripts/verify_case_draft.py:233`），标错一次丢一条本可入库的结论。
- 加一个状态要改五处以上，且漏改不报错。

### 1.3 做完的变化

1. 面板上改状态成为一次直接动作：展开卡片 → 选收尾方式 → 填必填项 → 确认收尾。不需要对话。
2. 状态规则只存在于一门语言（Python）与一个数据文件（`trace-status.yaml`）。面板不实现判据，只渲染服务端给出的动作与字段。
3. 每次转移追加一条 `transitions` 记录（谁、何时、从什么到什么、收尾方式、来源），非法转移在写入时被拒。

## 2 现状核对（设计依据，全部实测）

| 事实 | 证据 |
|---|---|
| 同一判据有五个以上实现 | `verify_case_draft.py:229-236`；`sediment_batch.py:46`；`export_trace.py:196-203`；`replay_trace.py:101-103`；`panel-client.js:857-912`；`panel-host.js:906` 的 `inProgress` 把 `escalated` 计作在办 |
| 面板内标签三份 | `panel-client.js:348` `statusMeta`、`:4063` `STATUS_LABEL`、`:2075` `statusAccent`（`archived` 缺项） |
| 面板已在写 trace | `ascend-update-sedimented` → `panel-host.js:233-272` 行拼接 + `fs.writeText`；UI 入口 `panel-client.js:1448`（且把 `caseId` 传成 `s.sessionId`，是 bug） |
| 「面板只读」声明与代码不符 | `dsh-plugins/README.md` 只读边界行；实际三处写：导出交接包、重建本机明细、`sedimented` |
| 子进程写沙箱约束 | `panel-host.js:24-48`：写必须显式 `{mode:'workspace-write', workspaceRoot: cwd}`，否则默认根是 DSH 检出，被拒只报 `Operation not permitted` |
| `ended_at` 是成本右边界，不是收尾时刻 | `diagnosis_state.yaml.example:40`；读端 `trace_entry_activity.py:481-484`、`:549-575`；面板成本列 `panel-client.js:1674` |
| `resolved_at` 已存在但无人校验 | `diagnosis_state.yaml.example:63` |
| `stop_reason` 与状态语义部分重叠 | `trace_metrics.py:107-110`（`abandoned` / `escalated_tier3`） |
| 报告是活件、修订留痕 | `report-template.md:17-26` |
| 误诊归因只有两值 | `diagnosis-procedure.md:345` |
| S1 现场与 S2 内容验证不混算 | `docs/guide/metrics.md:105` |
| 本机实况：20 份 trace，`ending` 与 `ended_at` 各 0 份 | `traces/*.yaml` |
| CI 里没有 `traces/` | `.gitignore:7` |

## 3 目标与非目标

### 3.1 目标

1. 状态与收尾方式在面板上可看、可改；写入可校验、可追溯、可撤销。
2. 加状态、加转移、改必填只改 `trace-status.yaml` 一处；Python 侧读端改调库，JS 侧没有判据。
3. 老数据不被判违规，不需要一次性清洗。
4. 失败与降级可见：不假装成功，不把写入落到错误的检出。

### 3.2 非目标（本 PR）

- 回报轴（`feedback` 的写入口与面板回报表单）：设计见 §9，实现排 PR2。
- 批量收尾：PR2。理由见 §13（UX-B3）。
- 跨机同步、认领队列、锁之外的协调：`traces/` 只在本机（`docs/guide/handoff.md:149`）。
- 新增状态值：仍是 4 个业务值 + `unknown`。

## 4 状态模型

### 4.1 状态

| 值 | 面板标签 | 含义 | 终态 | 可续接 |
|---|---|---|---|---|
| `in_progress` | 进行中 | 诊断未给出结论，或结论已给出但仍在跟进 | 否 | 是 |
| `resolved` | 已定位 | 定位结论已写入报告（根因明确，或明确的下一步已给出）。**不表示 fix 在现场生效** | 是 | 否 |
| `escalated` | 已转交他人 | 本地不再跟进，已交给别人（厂商 / 技术支持 / 同事）。必填「转交给谁」 | 是 | 否 |
| `archived` | 不再跟进 | 不再跟进且没有人接手（未复现 / 与已有单重复 / 未走诊断 / 主动撤回） | 是 | 否 |
| `unknown` | 状态未记录 | 旧记录未写状态；新写入不使用 | 否 | 否 |

两个与旧词表的差别，都是行为变更，要在 PR 里写明：

1. `escalated` 的标签从「已转上游」改为「已转交他人」，语义扩到「任何接手方」；`resumable: false` 维持不变，而面板旧常量 `RESUMEABLE = { escalated: true }`（`panel-client.js:359`）随之删除。
2. 「有人接手了」只由 `escalated` 表达，不再塞进 `archived`。`archived` 的收尾方式只有四种，全部是「没人接手」的情形。

### 4.2 收尾方式（`ending`）

| kind | 面板标签 | 必填 | 用于状态 |
|---|---|---|---|
| `root_cause` | 根因明确 | 无 | `resolved`（隐含，不写盘） |
| `handed_off` | 转交他人跟进 | `handed_to` | `escalated` |
| `not_reproducible` | 问题未复现 | 无 | `archived` |
| `duplicate` | 与已有单重复 | `duplicate_of` | `archived` |
| `no_diagnosis` | 未走诊断 | 无 | `archived` |
| `withdrawn` | 主动撤回 | 无 | `archived` |

`handed_to`：接手方，写「名字 · 团队」或 issue 号；`duplicate_of`：被重复的那一单，收窄为 `case:<id>` 或 `session:<session_id>` 两种形式，本机存在性可校验（`session:` 用 `sediment_batch.py:66-76` 的命名归组规则匹配）。

### 4.3 转移表

| 从 | 到 | 本次必须提供（`requires`） | 必须已存在（`preconditions`） | 收尾方式 |
|---|---|---|---|---|
| `in_progress` / `unknown` | `resolved` | 无 | `summary`、`severity`、`fix_emitted`；命中 case 时 `feedback.outcome` 有值 | `root_cause` |
| `in_progress` / `unknown` | `escalated` | `handed_to` | `summary` | `handed_off` |
| `in_progress` / `unknown` | `archived` | `ending.kind`（四种之一）；`duplicate` 另需 `duplicate_of` | `summary` | 对应 kind |
| 任意终态 | `in_progress` | 无 | 无 | `ending` 移入事件，顶层清空 |
| 任意终态 | 任意另一终态 | 同对应行 | 同对应行 | 由脚本展开为「重开 + 收尾」两条事件；面板动作名「改收尾方式」 |

补充规则：

1. **`preconditions` 与 `requires` 分开**。`requires` 是本次调用要写的字段；`preconditions` 是必须已存在的字段。面板对可补录的 preconditions（`summary` / `severity` / `fix_emitted`）在编辑器里给输入位；不可补录的（`feedback.outcome`）在面板上给「先去回报」的引导与一条可复制命令，不把字段塞进收尾表单。
2. **`ended_at` 不参与收尾**。它是成本右边界（见 §2），由诊断自己写；收尾时刻记在 `transitions[-1].at`。`resolved` 的日期继续用已有的 `resolved_at`，`verify_trace_status.py` 校验「status=resolved ⇒ resolved_at 非空（有 transitions 的单）」。
3. **`stop_reason` 由写入口写**。收尾时写 `closed_by_user`（词表新增一个值），agent 可传 `--stop-reason` 覆盖。不加这一步，面板收尾的单会系统性落进「未记录」，把停止点分布抹掉。
4. 三条轴不互相赋值：`resolved` 不写 `feedback`；`feedback.outcome: resolved` 不改 `status`。

### 4.4 为什么不新增状态值

「已定位但等现场确认」是 `status: resolved` 加 `feedback.outcome: pending`，不是第五个状态。新增状态值会让五个读端各多一个分支并要求历史迁移；而这条差别已经存在于 `feedback` 轴。面板用徽标与点形区分三态：待回报 / 已确认 / 回报与报告不一致。

## 5 数据契约

### 5.1 `trace-status.yaml` 新增段

```yaml
axes:
  status:     { writer: scripts/trace_transition.py }
  outcome:    { writer: scripts/trace_transition.py --field outcome }
  sedimented: { writer: scripts/trace_transition.py --field sedimented }

ending_kinds:
  - { value: root_cause,       label: 根因明确,      statuses: [resolved] }
  - { value: handed_off,       label: 转交他人跟进,  statuses: [escalated], requires: [handed_to] }
  - { value: not_reproducible, label: 问题未复现,    statuses: [archived] }
  - { value: duplicate,        label: 与已有单重复,  statuses: [archived], requires: [duplicate_of] }
  - { value: no_diagnosis,     label: 未走诊断,      statuses: [archived] }
  - { value: withdrawn,        label: 主动撤回,      statuses: [archived] }

transitions:
  - from: [in_progress, unknown]
    to: resolved
    action: close-resolved
    action_label: 已定位
    ending: root_cause
    preconditions: [summary, severity, fix_emitted]
    preconditions_if_case: [feedback.outcome]
  - from: [in_progress, unknown]
    to: escalated
    action: close-escalated
    action_label: 转交他人跟进
    ending: handed_off
    requires: [handed_to]
    preconditions: [summary]
  - from: [in_progress, unknown]
    to: archived
    action: close-archived
    action_label: 不再跟进
    ending_choices: [not_reproducible, duplicate, no_diagnosis, withdrawn]
    preconditions: [summary]
  - from: [resolved, escalated, archived]
    to: in_progress
    action: reopen
    action_label: 重新打开
  - from: [resolved, escalated, archived]
    to: any-other-terminal
    action: correct-ending
    action_label: 改收尾方式
    expands_to: [reopen, close-*]
```

约束：`from` / `to` 必须都在 `status:` 段；`ending_kinds[].statuses` 必须与 `transitions[].ending`/`ending_choices` 一致；`requires`/`preconditions` 必须都在 §5.3 的字段清单里。`verify_trace_status.py --check` 校验这两条（CI 跑这一半）。

### 5.2 trace 顶层字段

```yaml
ending:                                  # 终态必填；重新打开时清空（旧值进事件）
  kind: handed_off
  handed_to: "张工 · CANN 组"             # kind=handed_off 必填
  duplicate_of: ""                       # kind=duplicate 必填，形如 case:VLLM-ASC-11312 或 session:2026-10-20-1030-vllm-oom-a
  note: ""                               # 可选，一句话
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

`ended_at` 不写（成本口径）。收尾时刻只从 `transitions[-1].at` 读；老数据没有事件时退回 `updated_at`，并在投影里标 `timeSource: updated_at`。

### 5.3 字段清单

`summary`（非空）、`severity`（三档）、`fix_emitted`（布尔）、`ending.kind`（枚举）、`ending.handed_to`（非空）、`ending.duplicate_of`（`case:` / `session:` 前缀 + 非空 id）、`feedback.outcome`（枚举；命中单收尾的前置条件）。

## 6 组件

### 6.1 库 `scripts/_trace_state.py`（唯一判据实现）

对外函数：

```python
load_traces(traces_root) -> list[Trace]          # 解析 + 容错
derive(trace, kb_case_ids) -> Derived            # 见下表，纯函数
actions_for(trace, vocab, can_write) -> list     # 合法动作；含 requires/preconditions/kind 候选
project(traces_root, kb_root, host_caps) -> dict # 面板与 CLI 共用的 JSON
```

派生量（口径出处写在函数注释里，逐条标注搬自哪一行）：

| 字段 | 口径 | 出处 |
|---|---|---|
| `closed` | 命中单看 `feedback.outcome == resolved`；无命中单看 `status == resolved` 且无显式 outcome | `verify_case_draft.py:229-236` |
| `sedState` | `sedimented.state` 或 `none` | `panel-host.js:875` |
| `caseKind` | case / placeholder / none（占位串正则同 `panel-host.js:337-344`） | 同上 |
| `skeleton` | 无 summary、无报告、无候选 | `panel-client.js:884` |
| `needSed` / `needReview` / `needPromote` / `needWork` | 沿用 `panel-client.js:872-912` 四条 | 同左 |
| `needConfirm` | `status == resolved` 且 `feedback.outcome == pending` | 新增 |
| `submitted` | `sedState == submitted` | `panel-client.js:906` |
| `valueRank` | 沿用 `panel-client.js:915-935` 的档次与破平 | 同左 |
| `timeSource` | 有 `transitions` 用 `at`，否则 `updated_at` | 新增 |

`valueRank` 与排序是**面板排序的判据**，也必须搬，否则「按价值」会有两套（`panel-client.js:2594-2598` 自己写着这一点）。

### 6.2 投影器 CLI `scripts/trace_state.py`

薄封装：`--json` 打印 `project(...)`；`--session <id>` 打单条；`--check` 只做词表自洽（给 CI）。schema 版本 `ascend-sleuth-trace-state/1`，放在输出的 `schemeVersion` 字段，写入口与 host 都带握手。

### 6.3 写入口 `scripts/trace_transition.py`

```
python3 scripts/trace_transition.py <session_id> --to archived --kind duplicate --duplicate-of case:VLLM-ASC-11312 \
    [--summary …] [--severity …] [--fix-emitted true|false] [--stop-reason closed_by_user] \
    [--by user] [--source panel] [--expect-sha256 <hex>] [--dry-run] [--json]
python3 scripts/trace_transition.py <session_id> --field sedimented --state submitted --inbox-path … --apply
python3 scripts/trace_transition.py <session_id> --reopen [--by … ] [--json]
```

实现要求（对应评审 S2）：

1. 用 `yaml.compose()` 找顶层键的 mark，不用正则找 `^status:`（block scalar 里可能出现同名文本）。
2. 写入：`os.replace` 原子替换；写前取 `log_lock`（`scripts/exec_log_path.py:215`）；写后重解析并深比较未被触碰的顶层键，不一致即回滚（退出码 4）。
3. CAS：`--expect-sha256` 比对文件内容哈希；未传时按读到的 status/ending 比对，冲突返回 3，并在 `--json` 里给 `current: {status, ending, at, by, source}`。
4. 原子写用 `_stdio.write_text_lf` 保持换行风格；输入 BOM / CRLF / 无尾换行都要能写回原风格。
5. 事件：`from`、`to`、`ending`（本次写入后的完整快照）、`prev_ending`（本次之前的完整快照）、`by`、`source`、`at`、`note`。重开时 `ending` 为 `null`、`prev_ending` 为旧值。
6. 输出：人读一行；`--json` `{ok, from, to, changed:[…], event:{…}, current:{…}}`；失败 `{ok:false, code, message, requires:[…], preconditions:[…]}`。
7. 退出码：0 成功；2 参数/必填缺失；3 状态已变；4 写入校验失败（已回滚）；5 主检出解析不到或不可写（fail closed，不退回会话 cwd）。

### 6.4 一致性检查 `scripts/verify_trace_status.py`

- `--check`（CI 可跑，不需要 traces）：词表自洽（§5.1 的两条约束）+ `trace-status.yaml` 与 `panel-client.js` 不再有状态字面量（grep 门见 §10）。
- `--all`（本机，报现状）：字段一致性。**只检查有 `transitions` 记录的单**（grandfather：老单不判违规），另单列「老终态单缺收尾方式」的计数。
- `--strict`（本机）：要求所有终态单都有 `transitions` 记录与 `ending`；不通过项列出 session 与缺什么。

### 6.5 面板

**RPC**

- `ascend-traces-list` 保持名字与形状，新增 `state` 字段承载投影（`derived`、`actions`、`provenance`、`capabilities`），避免客户端第二次调用；`INDEX_SCHEMA` 加一位、`INDEX_CORE_FIELDS` 同步（漏改会让旧缓存把新字段喂成 undefined，`panel-host.js:427-432` 有先例）。
- `ascend-trace-transition`：参数 `{sessionId, action, payload, expectSha256}`；host 调脚本 `--json`，把结果原样返回；不自行判对错。
- `ascend-update-sedimented`：删除行拼接实现，改调 `trace_transition.py --field sedimented`；顺手修 `caseId: s.sessionId` 的 bug（应传命中的 case id）。
- `ascend-process-health` 与 `ascend-session-marks` 的在办口径改为读投影的 `derived`（现在把 `escalated` 计作在办，`panel-host.js:906`）。
- `ascend_trace_status` 工具输出补 `ending.label` 与 `nextActions`（工具 schema 是 `additionalProperties: false`，要同步）。

**能力位与降级**

- 投影带 `capabilities: {canWrite, writeRoot, reason}`。`canWrite` 由 host 计算：`resolveCwd()`/`mainCheckoutOf()`（`panel-host.js:136-191`）解析到主检出且 shell 档位允许写时为 true。
- `canWrite: false` 时动作按钮渲染为「复制命令」，不显示「确认收尾」；命令前缀写清「在仓库根目录运行」。
- 写入的 workspaceRoot 一律用主检出；解析不到就直接失败（退出码 5），**不退回会话 cwd**——退回会把状态写进 worktree 里的另一份 trace。
- 脚本与面板握手：脚本输出 `schemeVersion`，host 不接受未知版本并提示「主检出的脚本版本比面板新/旧」。

**客户端**

- 删除 `RESUMEABLE`、`statusMeta`、`STATUS_LABEL`、`statusAccent` 四份常量；标签、颜色、动作、候选 kind 全部来自投影 `vocab` 与 `actions`。
- 卡片动作区：进行中显示「收尾」（含三个动作）；终态显示「重新打开」「改收尾方式」；老终态单缺 `ending` 时额外给「补记收尾方式」（`backfill-ending`，写入口按 terminal→terminal 展开）。
- 编辑器交互（照 `diagnostic-ledger` 浮层已建立的键盘约定，`panel-client.js:4276-4300`）：
  - 打开时焦点进编辑器标题；`↑↓/←→` 在收尾方式组内移动，`Enter` 选中并落到必填项，`Enter` 在提交按钮上提交，`Esc` 关闭并把焦点还给触发按钮；草稿在关闭前二次确认。
  - 数字键 `1-4` 只在收尾方式组内生效，且键盘提示印在选项上。
  - 收尾方式用 `role=radiogroup` + `aria-checked`；触发按钮带 `aria-expanded`/`aria-controls`；错误用 `role=alert` + `aria-invalid` + `aria-describedby`，并把焦点移到第一个错误字段；成功条 `role=status` + `aria-live=polite`；`.dot`/`▾` 加 `aria-hidden`。
  - 触发按钮最小 32px 高、左右留 8px；编辑器打开时 `scrollIntoView({block:'nearest'})`。
- 提交：只在 RPC `ok:true` 后更新界面；提交中按钮禁用并显示「正在写入…」；失败按 `E_PERM` / `E_NOT_FOUND` / `E_IO` / `E_SCHEMA` / `E_STATE_CHANGED` 各给一句原因与下一步，保留编辑器与已填内容。
- `E_STATE_CHANGED` 文案给「已被 {by} 于 {at} 改为 {状态}」；新状态是终态时只给「刷新查看」与「复制命令」，仍是进行中才给「按当前状态重试」。
- 提交成功后用返回的完整投影刷新该行（不是只用 from/to 拼），保持徽标一致；若该行已不匹配当前筛选，留在原位显示「已从本筛选移出 · 撤销」，不立即消失。
- 行级入口：行保持现有 `<button>`；状态按钮作为**行按钮之外的兄弟节点**（flex 包一层），不改行 DOM、不牺牲键盘可达性。PR1 只做卡片内入口；若不做行级入口，状态列不显示小三角、hover 下划线与 `cursor:pointer`，避免「看起来能点」。

**列表信息预算**

- 收起态第二行最多一个收尾方式徽标 + 一个欠账徽标（待回报 / 待沉淀 / 待复核）；其余进展开态。
- 记录来源（本机用户 / agent / 上一台机器）右对齐固定槽位，窄屏隐藏只留 tooltip。
- 状态列：点 + 文字。`in_progress` 蓝实心，`escalated` 灰实心，`resolved` 灰实心，`archived` 灰实心，`unknown` 空心灰；「待回报」用**空心琥珀环**（形状 + 颜色双重区分，侧栏已有空心环先例 `panel-client.js:636`）。绿色只给「fix 已验证」「库中已有」这类正向证据徽标，不给状态列。这条改动的取舍（牺牲"已定位"一眼绿色的可扫性）列入人审清单。

### 6.6 skills 与既有写者的白名单

- 白名单：`trace_begin.py`（建单写初始 `status: in_progress`）、`import_trace.py`（交接包落位写导入状态）、`sediment_batch.py`（`sedimented` 回写）。三者在文档里写明「不是转移」，不追加 `transitions`。
- `diagnose` / `resume-diagnosis` 的收尾改为调 `trace_transition.py`；正文里的状态词表段落改为指向 `trace-status.yaml`（PR3）。
- `to-postmortem` 的 `sedimented` 回写改调 `trace_transition.py --field sedimented`（PR3）。

## 7 面板文案（本 PR 一并改，逐条对应评审表）

| 现在 | 改为 | 说明 |
|---|---|---|
| 结局 / 这单结束了？ | 收尾方式 / 本单收尾 | 「结论」只留给定位结论 |
| 改结局 / 修正结论 | 改收尾方式 | 它不改报告结论，名不副实；说明写「会留下两条记录：重新打开、再收尾」 |
| 不跟了 | 不再跟进 | |
| 转上游 / 已转上游 | 转交他人跟进 / 已转交他人 | 接手方可以是厂商、技术支持或同事 |
| 已定位（有结论）/ 已定位 · fix 生效 | 已定位（结论已写入报告） | 「现场是否已验证」是另一条轴的徽标，不进收尾选项 |
| 与另一单重复 / 没走诊断 / 问题不复现 | 与已有单重复 / 未走诊断 / 问题未复现 | |
| 标于 … · 你 / 已标为 / 标过 / 终态 / 重开 | 记录于 … · 本机用户 / 已记录为 / 记录过 / 已收尾的单 / 重新打开 | 「由你」在导入单上是假的；「终态」「重开」是内部词 |
| 待现场确认 / 等回报 / 待回报 | 待回报 | 一个状态一个名字 |
| 结论待核对 / 待核对结论 / 待复核 | 报告待复核（任务） / 回报与报告不一致（事实） | 两个「待核对」互为倒装 |
| 提交 / 撤回 / 批量提交 / 应用到已选 N 单 | 确认收尾（转交时「确认转交」）/ 撤销（回到进行中）/ 收尾这 N 单 | 批量排 PR2 |
| 没有对应案例 / 无对应案例 / 无内容记录 | 未命中知识库 case / 空记录 | 同一事物两名 |
| 结算于 / agent 收尾 | 由 agent 记录于 … | 「结算」是银行词；provenance 统一模板 |
| 回报现场结果 / 上游答复 | 回报结果 / 厂商答复 | 来源选「厂商答复」时「现场」不成立 |
| 按报告的修复解决 / 用别的方法解决 / 部分解决 / 没解决 | fix 生效（按报告）/ fix 生效（其他方法）/ 部分生效 / 未生效 | 与 outcome 词表一致（PR2） |
| 结论未记录 / 补记结论 | 未记录收尾方式 / 补记收尾方式 | |
| `E_STATE_CHANGED` 等错误码上屏 | 只给人话 + 「复制命令」 | 内部码进 tooltip，不上正文 |
| `vllm 0.6` | `vLLM 0.6` | 行文规范第 39 条 |

## 8 兼容与迁移

- 老 trace 无 `ending` / 无 `transitions`：投影以顶层 `status` 为准，`timeSource` 标 `updated_at`；`verify --all` 只列「老终态单缺收尾方式」的计数，不判违规；`--strict` 才要求。
- 首次对老单转移时追加一条 `{from: <旧 status>, to: <新>, source, by}`，不追溯更早历史。
- 不为历史数据批量补 `ending`（补出来只能是猜的）；面板给「补记收尾方式」动作，一次一单。
- `ended_at` 保持原义（成本右边界），不由写入口改写；老单里已有的 `ended_at` 原样保留。

## 9 回报轴（设计留接口，PR2）

`field_report`（不是状态值）：`source: field|vendor`、`result: effective|other_way|partial|ineffective`、`note`、`at`、`by`。映射：`effective → outcome resolved`；`other_way → resolved + aligned false`；`partial → partial`；`ineffective → not_resolved`。`aligned false` 进「报告待复核」，agent 判三种结果：只修订报告（不判误诊）、`case_error`、`execution_error`。面板只记事实，不判对错；日志与截图仍走对话落证据。

## 10 门与验收

1. `python3 scripts/verify_trace_status.py --check`：词表自洽 + 「状态字面量只许出现在 `trace-status.yaml` 与 `_trace_state.py`」的 grep 门。CI 可跑（不依赖 traces）。
2. `python3 scripts/verify_trace_status.py --all`：本机字段一致性（老单只报计数）。
3. `python3 -m unittest discover tests -v`：新增 `tests/test_trace_transition.py`、`tests/test_trace_state.py`。
4. `python3 scripts/verify_case_draft.py --all`、`python3 scripts/sediment_batch.py`、`python3 scripts/export_trace.py --list`：既有读端不被改坏。
5. `node scripts/panel_render_check.js`：新增断言（渲染文本，不扫源码）——终态卡无收尾入口；进行中卡无「重新打开」；只渲染投影给的 actions，未知 action 不渲染；文案无旧词（按精确 token：`不跟了`、`转上游`、`结局`、`已解决 · fix 生效`，并允许新词 `转交上游` 之外的组合）；`aria-expanded`/`aria-checked`/`role=alert`/`aria-live` 存在；三个写调用点各自的 `workspace-write` + `--expect-sha256` + `--json`；四组失败用例（缺必填、CAS 冲突、`canWrite:false`、RPC 失败）保留内容并给复制命令。
6. `node scripts/check_panel_tokens.js`、`node scripts/check_panel_bundle.js`、`node scripts/panel_rpc_probe.js --selftest`：RPC 计数与 fs 守卫断言同步（`panel_render_check.js:3557-3575` 那个 `pinned === 2` 改成逐调用点）。
7. `node scripts/build_panel_bundle.js --check`、`--version` bump。
8. `python3 scripts/build_docs_index.py --check`、`python3 scripts/verify_proposals.py --check`（若加卡）。
9. 一条可复跑 measure：临时 trace 上跑「收尾 → 重新打开 → 改收尾方式」，断言 `transitions` 三条、每条 `prev_ending` 完整、终态字段齐全、`--check` 通过、`actions_for` 每步只给合法项。
10. 人审清单（机械判不了，写进 PR body）：收尾方式选项是否互斥；焦点顺序与播报；颜色语义与列表可扫性；60 单密度；文案语气。

## 11 风险与回退

| 风险 | 处理 |
|---|---|
| 写权限不足 / 主检出不唯一 | `capabilities.canWrite` + 退出码 5 + fail closed；降级为复制命令 |
| 并发写同一单 | `log_lock` + `--expect-sha256` + 写后深比较；冲突返回 3 并给 `current` |
| 行替换写坏 YAML | `yaml.compose()` 定位 + `os.replace` + 深比较 + 回滚；测试覆盖 §9 的边界样例 |
| 旧面板包与新词表不匹配 | 面板只渲染服务端动作；握手失败给一句提示 |
| 既有读端被改坏 | 五条既有命令与 `unittest` 全跑 |
| 老数据被误判 | grandfather 规则 + `--all` 只报计数 |

回退：脚本与词表一个提交、面板一个提交、skills 一个提交；面板回退只需重装上一个 bundle 版本（`package.json` 的 `version` 是安装器判新旧依据）。

## 12 分阶段落地

| 阶段 | 内容 | 估时 |
|---|---|---|
| PR1 | 词表转移段 + `_trace_state.py` + `trace_state.py` + `trace_transition.py` + `verify_trace_status.py` + 单测 + 面板接投影与卡片内编辑器（含文案、无障碍、失败路径）+ `sedimented` 改写入口 + 既有读端改调库 + 五处门与断言同步 + README 边界白名单 | 4 天 |
| PR1.5 | 行级状态按钮（行按钮 + 兄弟节点布局） | 0.5 天 |
| PR2 | 回报轴（§9）+ 批量收尾（逐单 expect-sha、逐单结果、预览） | 2 天 |
| PR3 | skills 去词表（diagnose / resume-diagnosis / to-postmortem 改调脚本） | 0.5 天 |

## 13 第 1 轮评审处置

### 架构评审（6 阻断 / 11 重要）

| 编号 | 结论与处置 |
|---|---|
| B1 handed_off 落点矛盾 | 改为「转交一律走 escalated」，`archived` 的四种 kind 全部是「没人接手」；示例命令同步改（§4.1/§4.2/§4.3） |
| B2 老数据被判违规 | 引入 grandfather：只检查有 `transitions` 的单；`--all` 只报计数，`--strict` 才要求（§6.4/§8） |
| B3 CAS 只比 status 会丢更新 | CAS 改文件 sha256 + `log_lock` + 写后深比较（§6.3） |
| B4 重开丢 handed_to/duplicate_of | 事件带 `ending` 与 `prev_ending` 完整快照；`ended_at` 不参与收尾（§5.2/§6.3） |
| B5 投影契约不足 | 补齐 actions 的 kind 候选、requires/preconditions、status 颜色与顺序、severity 词表、derived 全集（含 valueRank）、capabilities（§6.1） |
| B6 outcome 规则无处落地 | `requires` 与 `preconditions` 分开；outcome 归后者，面板给「先去回报」引导（§4.3） |
| I1 ended_at 语义冲突 | 不新增收尾时刻字段，`ended_at` 保持成本右边界；收尾时刻取 `transitions.at`；`resolved_at` 纳入校验（§4.3 规则 2） |
| I2 stop_reason 系统性缺记 | 新增 `closed_by_user`，写入口默认写，可 `--stop-reason` 覆盖（§4.3 规则 3） |
| I3 读端漏 4 处 | 补 `replay_trace`、`ascend-session-marks`、`ascend-process-health`、`ascend_trace_status`；inProgress 口径改读投影（§6.5） |
| I4 投影需要两个根 | `project(traces_root, kb_root, …)`，host 传两侧检出（§6.1） |
| I5 缓存与常量名 | 投影自带 mtime/size 缓存；改用真实存在的常量，并说明 `INDEX_SCHEMA`/`INDEX_CORE_FIELDS` 要同步（§6.5） |
| I6 缺能力位、cwd 回退 | 加 `capabilities`，用 `resolveCwd`/`mainCheckoutOf`；解析不到 fail closed（§6.5/§6.3） |
| I7 现有门会红 | 列进 §10.5：旧文案断言、RPC 计数、fs 守卫、fixtures、bundle 冒烟 |
| I8 其他写者未列 | §6.6 白名单；顺手修 `caseId: s.sessionId` 的 bug |
| I9 「只改一处/不漂移」无路径 | Python 读端 import `_trace_state`；加 grep 门（§10.1） |
| I10 stale 无依据 | 删除该派生量 |
| I11 duplicate_of 不可验证 | 收窄为 `case:` / `session:` 前缀 + 本机存在性校验（§4.2） |

### 交互评审（5 阻断 / 9 重要）

| 编号 | 结论与处置 |
|---|---|
| B1 两条轴并成一个枚举 | 收尾选项只留「已定位」；「现场已验证」是徽标，不是选项（§4.4/§7） |
| B2 必填项界面填不了 | `requires` 进表单；可补录的 `preconditions` 给输入位并预填；不可补录的给引导（§4.3 规则 1） |
| B3 批量无设计且会伪造事实 | 批量移出 PR1，排 PR2，且「问题未复现 / 重复」不允许批量（§3.2/§12） |
| B4 失败与降级不完整 | 按错误码分别给原因与下一步；只在 RPC ok 后更新；主检出 fail closed；补能力位（§6.5） |
| B5 行级入口自相矛盾 | 行保持 `<button>`，状态按钮作兄弟节点；PR1 不做行级时撤掉全部可点外观（§6.5） |
| I1 键盘声明与实现不符 | 照浮层约定：焦点入编辑器、方向键组内移动、Enter 选中/提交、Esc 关闭还焦点、数字键只在组内（§6.5） |
| I2 无障碍缺失 | 补齐 aria-expanded/controls、radiogroup、role=alert、aria-live、aria-hidden、32px 命中区（§6.5） |
| I3 终态动作语义不清 | 「改收尾方式」+ 说明两条记录；修正后给「查看历史」；`reopen`/`correct-ending`/`backfill-ending` 进动作词表（§6.5） |
| I4 两种转交打架 | 只保留 `escalated` 一种转交（§4.1） |
| I5 文案表未落地 | §7 整表重写，含 `上游`→`厂商/技术支持`、`结算于`→`由 … 记录于`、`vLLM` 大小写 |
| I6 颜色越界与不可能组合 | 状态列改中性色，绿色只给正向证据；删掉无命中单的「fix 已验证」；暗色主题沿用面板既有 token（§6.5） |
| I7 60 单信息预算 | 第二行最多两个徽标；来源固定槽位；提交后用完整投影刷新；筛选移出时留原位与撤销（§6.5） |
| I8 渲染断言会误伤 | 断言改渲染文本、精确 token、逐调用点；补四组失败用例（§10.5） |
| I9 PR1.5 裁剪可接受但路径要改 | 接受裁剪；PR1 撤可点外观；PR1.5 用兄弟节点布局（§6.5/§12） |

## 14 第 1 轮评审遗留项的决定

1. **状态列配色**：不整体改中性色。状态列按「这单在哪一步」上色：进行中蓝、已定位绿、已转交他人灰、不再跟进灰、未记录空心灰；「待回报」用空心琥珀环（形状 + 颜色）。同时在 `dsh-plugins/README.md` 的颜色角色表加一条例外说明：状态列颜色表达进度，不表达「该不该你做事」；绿色不表示 fix 已验证，已验证只由徽标承担。取这条而不是全灰，是因为评审 I7 与现有「扫列表先看状态列」的用法（`panel-client.js:2074`）冲突，全灰会让 60 单的可扫性明显下降；颜色语义靠这条例外与本条说明固定下来。
2. **`withdrawn` 保留**：边界写进词表注释——`no_diagnosis` 是「从未开始诊断」，`withdrawn` 是「诊断进行过但主动中止且没有结论」（如材料不足）。两者都不下 fix 是否有效的判断。
3. **`escalated` 标签**：状态标签改为「已转交他人」，不保留「上游」作父标签；接手方类型（厂商 / 技术支持 / 同事）由 `ending.handed_to` 的自由文本与输入提示表达，不再引入枚举。
