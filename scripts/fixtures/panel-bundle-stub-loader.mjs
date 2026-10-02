// panel-bundle-stub-loader.mjs —— check_panel_bundle.js 用的解析钩子
//
// 生成物 `dsh-plugins/dsh-sleuth-panels/lib/index.js` 里有一句
// `import { defineTool } from '@deepseek-ai/dsh-tools'`：真实运行时由 DSH Desktop 注册的
// `@deepseek-ai/*` 模块回退从安装处解析（见 resources/host-module-fallback.mjs），
// 但在仓库里裸跑 node 解析不到。这里把该裸包名指到本地 stub，好让冒烟测试**原样加载**
// 生成物（不改一个字节），验的是真文件。
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const stubUrl = pathToFileURL(join(here, 'panel-bundle-dsh-tools-stub.mjs')).href

export function resolve(specifier, context, nextResolve) {
  if (specifier === '@deepseek-ai/dsh-tools') {
    return { url: stubUrl, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}
