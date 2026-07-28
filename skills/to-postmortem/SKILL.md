---
name: to-postmortem
description: >
  把一次昇腾问题定位沉淀成知识。输入可以是 Claude Code/Codex 的对话、Kimi/DeepSeek 网页版对话、
  或纯手工排查笔记。提取症状/命令/root_cause/fix，检测框架给命名空间建议，人确认（5秒），
  输出结构化 YAML 草稿 + postmortem.md，过语义校验和脱敏。无论知识产自哪里（本地 agent session / Kimi 网页对话 / 手工笔记），都从这里汇入——这是异构知识来源的统一入口。
---

# To Postmortem

知识注入入口与诊断工具**解耦**——无论问题在哪儿定位的，都能在这里沉淀。这是 ascend-sleuth 体系里最重要的动作：不沉淀，团队下次还得重新踩坑。

## 用法

```
/skill:to-postmortem "[粘贴 Kimi/DeepSeek 的完整对话]

[或粘贴纯手工排查笔记]"
```

## 流程

1. **提取**：从输入中抽出症状、执行的命令和输出、排除的假设、root cause、fix
2. **命名空间建议**：agent 检测或推断框架，给选项，人输入数字确认（约 5 秒）：
   ```
   [1] training/mindspeed-llm/   （检测到 mindspeed-llm）
   [2] training/verl/            （检测到 verl）
   [3] common/                   （跨框架，或不确定）
   ```
   - 完全没涉及框架（纯硬件/CANN/驱动报错）→ 选项变为 `[1] common/`，人按回车
   - 检测到多个框架 → 按置信度排序，第一项标 `(most likely)`
   - 这个确认本身就是质量检查：人在 `mindspeed-llm` 和 `common` 间选，本质在自问"这问题是框架特有的还是通用的"
3. **输出结构化 YAML 草稿 + postmortem.md**：
   - 标 `confidence: high | medium | low`
   - 标 `novelty: new_pattern | variant | covered`
   - 标 `category: interrupt | precision | performance`（按症状判断——interrupt 是 hang/crash/OOM、precision 是 NaN/数值发散、performance 是吞吐/延迟）
   - 标 `tags`（sub-type，如 `oom`、`kv-cache`、`precision.convergence`）
4. **语义校验**（关键，区别于格式校验）：
   - regex 在输入附的真实日志片段上能否匹配
   - `expected` 值类型/数量级合理性
   - `command_template` 里的路径在已知部署模板里是否存在
   - 校验失败 → 标 `needs-structurer-review`（与 `needs-human-review` 区分：前者是格式/语义可疑，后者是语义不明）
5. **脱敏**：扫描 `Bearer ...`、`sk-...`、`password=`、内网 IP 段 → 替换 `[REDACTED]`。在人确认前，不是事后补救。这是 KB 进私有的第二道防线，第一道是 repo 可见性（见 README）
6. 人扫一眼确认 root cause 和 fix → done（30 秒内）

## 产出落点

- `postmortem.md` → `postmortems/YYYY-QN/`
- YAML 草稿 → 随 postmortem 一起，等 `/skill:knowledge-groom` 升格到 `knowledge/<ns>/`

## 为什么是这个体系的核心

团队不能统一 agent 时，知识注入入口必须与诊断工具解耦。`/to-postmortem` 是这个解耦的实现——任何工具的对话都能沉淀。别期望团队成员额外写文档，agent 提取、人审批，成本从 20 分钟降到 30 秒。
