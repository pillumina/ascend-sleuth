# sleuth-console —— 整页「Ascend Sleuth」（常驻包里的第三个源文件）

> **跨面板契约不在本文件维护**：颜色角色、字号行高、文案规范、只读边界与依赖缺失时的退化口径，
> 统一见 [../README.md](../README.md)（`dsh-plugins/README.md`）。本文件只写这一页的形式与装配。

把指标、自演进与知识库装进**一个整页**：左侧栏一个图标，点进去三个子页。会话里因此只剩「诊断」一个 tab。

## 为什么是整页，不是两个 tab

指标与自演进读的是**全库**（`metrics/`、`proposals/`、`knowledge/`），与当前会话无关。挂在
`conversation.view` 上要付三笔账：

1. **必须开一单诊断才能看库**——`conversation.view` 只在有会话时渲染；
2. **每个会话各记一份"停在哪个全局页"**，同一个全局页在 N 个会话里有 N 份选中态；
3. **会话 tab 行被全局内容占位**：对话 / 轨迹 / 诊断 / 指标 / 自演进，五个 tab 里两个不随会话变。

整页挂在 `main` 的 keyed 条目上，root 作用域，没有会话也能打开。

## 三个注册面（id 必须对齐）

| 注册面 | 值 | 作用 |
|---|---|---|
| `main` | `key: 'ascend-sleuth-console'` | 整页组件；布局按 `ctx.layout.selectPanel(id)` 选中它 |
| `sidebar.panellist` | `id: 'ascend-sleuth-console'`、`order: 30`、`label: 'Ascend Sleuth'` | 左侧栏图标行；同一个 id 才点得到上面那页 |
| `conversation.view` | 只剩 `ascend-diagnose`（面板源码注册） | 会话里这一单的轨迹与证据 |

`check_panel_bundle.js` 把三个注册面连 id/order 一起断言——`main` 的 key 与图标 id 不一致时，
点图标会抛错并保留原选中态，症状是"图标点了没反应"。

## 视图登记表：三个源文件怎么接上（知识库子页在同页注册）

两个面板是独立的动态方言文件，视图组件（`MetricsView` / `BoardView`）定义在各自闭包里；知识库视图（`KnowledgeView`）定义在整页自己的源码里。生成器在
包里建一个 `SLEUTH_VIEWS = {}`，面板 apply 时把自己的视图写进去，本页按 id 取来渲染：

```js
// 面板（panel-client.js 末尾）：有整页容器就登记视图，没有就退回 conversation.view
if (typeof SLEUTH_VIEWS !== 'undefined' && SLEUTH_VIEWS !== null) {
  SLEUTH_VIEWS.metrics = (props) => React.createElement(MetricsView, props)
} else {
  slots.inject('conversation.view', () => slots.register({ id: 'ascend-metrics', … }, MetricsView))
}
```

`typeof` 守卫是给**动态热加载路径**的：那条路把 `panel-client.js` 原文当函数体加载，没有整页容器，
于是面板照旧注册 tab，本页的 apply 直接安静退出（不注册 `main`，也不报错）。两条路的界面形态因此
不同，但视图组件是同一份。

## 图标

`icon.svg` 是设计源，`console-client.js` 里内联同一组几何数据（方框 + 读数折线，两笔都用
`currentColor`，亮/暗主题自动跟随）。`panel_render_check.js` 逐条比对 `icon.svg` 的方框尺寸与
`path` 数据是否都在客户端源码里——只改一处会变成两个图标，闸门红。

方框取芯片的形（昇腾平台），里面一条体检读数线：读的是全库健康，不是某一单的轨迹。

## 只读与退化

- 只渲染 RPC 读到的数据、给可复制指令，不做决策、不写仓库（与两个面板同一条边界）。
- 视图没登记时给一行说明（"这个子页没接上…"），不空白、不拿另一页的数据顶上。
- 子页数据缺件时由各自面板如实报缺（缺哪个文件、重建命令），本页不重算。

## 回归闸门

- `node scripts/panel_render_check.js` 的「整页 · Ascend Sleuth」一节：两个面板真的登记了视图、整页与图标
  同 id、默认子页与切换各渲染出对应内容、视图缺失时有说明、图标与 `icon.svg` 同形。
- `node scripts/check_panel_bundle.js`：产物里三个注册面齐、会话里只剩一个 tab、三个界面首屏各发出
  一条 RPC。
- `node scripts/build_panel_bundle.js --check`：`lib/` 与三个源文件一致。
