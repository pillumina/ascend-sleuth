# 品牌资产

ascend-sleuth 的标识。**纯字标（wordmark），不带独立图标**。

| 文件 | 用途 |
|---|---|
| `logo.svg` | 字标，浅色背景（README 页首，宽 460）|
| `logo-dark.svg` | 字标，深色背景；README 用 `<picture>` + `prefers-color-scheme` 自动切换 |

## 字形

Space Grotesk Bold（SIL OFL 1.1，Florian Karsten，https://github.com/floriankarsten/space-grotesk）。
**字形已转成路径**——SVG 里没有 `<text>`、不引用任何字体，因此任何设备（macOS / Windows / Linux、
GitHub 渲染、PNG 导出）渲染完全一致，不随系统字体变化。代价：改文案要重新生成路径
（Space Grotesk 轮廓 + fontTools），不能直接编辑文字。

## 配色

| 角色 | 浅色背景 | 深色背景 |
|---|---|---|
| 主字 `ascend-` | `#0B0E14` | `#E6EDF3` |
| 强调 `sleuth` | `#C7000B` | `#FF6B5B` |

`#C7000B` 与 README 里 `platform: Ascend NPU` 徽章同属 Ascend 红系。

## 预览与导出

无构建步骤，SVG 可直接拖进浏览器看。需要位图时：

```bash
rsvg-convert -b white -w 1286 docs/assets/logo.svg -o /tmp/logo.png        # 2x
rsvg-convert -b '#0D1117' -w 1286 docs/assets/logo-dark.svg -o /tmp/logo-dark.png
```

favicon / 社交预览图需要方形图标，当前不提供——需要时另做一个方形标记。
