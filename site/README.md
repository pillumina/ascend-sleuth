# 介绍页

`index.html` 是单文件静态页：CSS、JS、字体都内联，没有构建步骤，也不依赖外部资源。

本地预览：

```sh
python3 -m http.server 8756 --bind 127.0.0.1 --directory site
```

部署：`.github/workflows/pages.yml` 在 `main` 上的 `site/**` 或该 workflow 变更时，把 `site/` 作为 Pages artifact 发布。首次启用时，仓库 Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。

失败重跑：

- 同一 run 里 artifact 名带 attempt 序号，失败的 job 可以直接重跑。
- artifact 名不带 attempt 序号的旧 run 仍跑旧 YAML，重跑会失败。这类 run 另开一次，用 `gh workflow run pages.yml`。
- Pages 判定内容无效的失败，重跑同样失败，要先改内容。

自定义域名：在 Pages 设置里配置，或在 `site/` 放 `CNAME`；换域名后同步 README 顶部的 landing page 链接。
