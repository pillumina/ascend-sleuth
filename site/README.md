# 介绍页

`index.html` 是单文件静态页：CSS、JS、字体都内联，没有构建步骤，也不依赖外部资源。

本地预览：

```sh
python3 -m http.server 8756 --bind 127.0.0.1 --directory site
```

部署：`.github/workflows/pages.yml` 在 `main` 上的 `site/**` 或该 workflow 变更时，把 `site/` 作为 Pages artifact 发布。首次启用时，仓库 Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。

自定义域名：在 Pages 设置里配置，或在 `site/` 放 `CNAME`；换域名后同步 README 顶部的 landing page 链接。
