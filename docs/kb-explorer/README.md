# 昇腾知识浏览器（KB Explorer）· v2（工作台 × 期刊质感）

面向人的先验知识层检索/学习界面。数据源 `references/`（105 词条）+ `triage-tree.yaml`。
设计定位：**诊断现场快查优先** —— 报错在手 → ≤5 秒定位错误码含义/命令/根因，同时保留学习浏览的期刊质感。

## 打开

```
open docs/kb-explorer/index.html
```

or 本地起服务（更稳，推荐）：

```
cd docs/kb-explorer && python3 -m http.server 8080
# http://127.0.0.1:8080
```

## 重新生成

`references/` 或 `triage-tree.yaml` 变更后：

```
python3 scripts/build_kb_explorer.py
```

源码在 `scripts/kb-explorer/src/`（分模块 CSS/JS，无 node 依赖），
生成器 `scripts/build_kb_explorer.py` 把 CSS/JS 拼接、语料 JSON 内联成静态目录：

```
docs/kb-explorer/
  index.html   页面壳（顶栏 / 主区 / toast）
  app.css      设计系统（src/*.css 按序拼接）
  app.js       应用（src/*.js 按序拼接，经典 script，file:// 直接可开）
  kb-data.js   语料 JSON（const KB = …，与 app 分离便于体积感知）
```

## v2 设计要点

- **布局**：启动台首页（大搜索 + 场景卡 + 最近浏览 + 数据域）+ 双栏检索（master-detail）
  + 独立词条页 + 症状路由图。
- **交互**：全局搜索（⌘K / `/` 唤起，输入联想、↑↓ / Enter 导航）、列表 ↔ 详情原地切换、
  命令工具卡一键复制 + toast、步骤流 timeline、可展开来源面板、键盘上下键浏览。
- **动效**：路由 View Transition、面板内容淡入、卡片 hover 位移/光晕、reveal 滚动渐显、
  复制态 morph + toast；全部尊重 `prefers-reduced-motion`。
- **视觉**：暖纸 × 赤陶 oklch 品牌（沿用 v1），light/dark 双主题（跟随系统 + 手动持久化）；
  语义状态色对齐诊断 severity（信息/警告/危险/成功）；命令深底 mono 块为视觉锚点。
- **约束**：零外部依赖、零构建工具链；产物可审计、离线可开。case 层（knowledge/）为私有，未纳入。

## Demo 边界（同 v1）

- **不含 knowledge/（case 层）**——case 含客户数据（private），只做 references（public 方法论）。
- **case↔reference 反链（ref_knowledge）**：schema 已定义但全库暂无 case 填充，随沉淀累积后加「被哪些 case 引用」视图。
- 本目录产物未接 CI；定型后再决定沉淀载体（docs 静态站 vs DSH 面板知识 tab）。
