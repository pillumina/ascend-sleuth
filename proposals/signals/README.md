# 演进信号台账

内容流程收尾的轻量产物。一条信号一个文件，随 PR 提交；由深度轮分诊，不直接产 EV 卡。

## 谁写

`skills/evolve-check/SKILL.md` 第 3 步：所有部署角色收尾都只写这里；不产 EV 卡、不跑 RSI。

```bash
python3 scripts/evolve_signals.py add --signal T10 --signal-text "自审发现的缺口" \
  --target skills/evolve-check/SKILL.md --evidence "一句话证据" \
  --trajectory "products/VLLM-ASC-123(submitted)" --suggested "建议动作" --source evolve-check
```

## 谁读

- 上游维护者：`python3 scripts/evolve_signals.py export` 生成可粘贴的 issue / MR 描述；批到之后产卡。
- 上游的深度轮：`proposals/signals/` 是观测输入之一（跨部署汇总的信号源）。

## 文件名为什么不带序号

序号在本地递增，两个部署各产各的必然重号——那正是这类部署不产卡的原因。文件名取
`sha256(signal | target_component | evidence)` 的前 8 位：同一信号重复出现得到同一个文件，
只把 `occurrences` 与 `last_seen` 往上加；证据改写了就是另一条（不做模糊合并）。

## 字段

| 字段 | 含义 |
|---|---|
| `id` | 内容哈希前 8 位 |
| `signal` / `signal_text` | 信号编号与中文含义（编号随触发条件表变，含义是给人读的那份） |
| `target_component` | 要改的组件：skill 路径、脚本名或组件名 |
| `evidence` | 一句话证据，写聚合值或现象，不写客户原文 |
| `suggested_action` | 建议动作，一句话；没有方案就留空（信号可以先于方案存在） |
| `trajectory` | 出处：产出 id、trace、replay 结果，可多条 |
| `deployment` | 部署标识（与指标侧同口径） |
| `first_seen` / `last_seen` / `occurrences` | 首次、最近、出现次数 |
| `status` | `new` → `triaged`（分诊过）→ `promoted`（已产卡）/ `dropped`（不跟）；`export` 默认不导 `dropped` |
| `status_note` / `status_at` | 改状态时的一句话理由与时间 |

## 边界

- 不产卡：本目录只有信号，没有状态机、没有预测、没有验证门。产卡与验证在上游。
- **不做实验、不做验证、不写预测**：记录方只交现象与出处。已经跑过的命令与输出可以写进 `evidence`，没跑过的不许编——下游凑出的判据上游不会采信，还会把现象污染成结论。
- 判优先级、读组件、写 `measure`、跑验证，都是上游手动跑深度轮时的事。
- 脱敏：`evidence` 与 `trajectory` 不得含客户现场原文（同 case 入库纪律）。
