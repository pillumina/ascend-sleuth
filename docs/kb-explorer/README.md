# 昇腾知识浏览器（KB Explorer）· demo v1

面向人的先验知识层检索/学习界面。数据源 `references/`（102 词条）+ `triage-tree.yaml`，
渲染成单个**自包含 HTML**（无外部依赖，`file://` 双击即可打开）。

## 打开

```
open docs/kb-explorer/index.html
```

## 重新生成

`references/` 或 `triage-tree.yaml` 变更后：

```
python3 scripts/build_kb_explorer.py
```

模板在 `scripts/kb-explorer/template.html`（含全部 CSS/JS 与 `__KB_JSON__` 占位），
生成器把语料 JSON 内联进 `docs/kb-explorer/index.html`。

## 视图

- **总览**：检索 + 四个起点（错误码 / 方法论 / 日志位置 / triage 路由）+ 目录
- **方法论**：flow 渲染为步骤流（when_to_use 分流 → action → 可复制 check 命令）
- **表格族**（错误码 / 故障模式 / 环境变量 / 兼容矩阵）：泛型表格渲染，优先列 + 额外列兜底
- **事实/工具**：claim/evidence、命令卡、坑点、副作用+回滚
- **词条详情**：来源类型徽章（official-doc / case-derived / engineer-input × 校验状态 × 核验时间）、
  平台/版本/框架/类别 chips、related_references 跳转 + 反向引用（派生视图）
- **搜索**：词条级加权全文检索（title/summary/id/全文），支持错误码数字、命令、路径、平台名
- **triage**：症状路由分支（正则关键词明细可展开）

## Demo 边界（有意为之）

- **不含 knowledge/（case 层）**——case 含客户数据（private），v1 只做 references（public 方法论）。
  首页/路由图均有标注。
- **case↔reference 反链（ref_knowledge）**：schema 已定义但全库暂无 case 填充，
  随 diagnose/to-reference 沉淀累积后，再在词条页加「被哪些 case 引用（role）」视图。
- 本目录产物未接 CI；demo 定型后再决定沉淀载体（docs 静态站 vs DSH 面板知识 tab）。
