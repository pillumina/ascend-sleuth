// panel-bundle-stub-loader.mjs —— check_panel_bundle.js 用的解析钩子
//
// 生成物 `dsh-plugins/dsh-sleuth-panels/lib/index.js` 里有一句
// `import { defineTool } from '@deepseek-ai/dsh-tools'`：真实运行时由 DSH Desktop 注册的
// `@deepseek-ai/*` 模块回退从安装处解析（见 resources/host-module-fallback.mjs），
// 在仓库里裸跑 node 解析不到。
//
// 这里优先用**真品**：check_panel_bundle.js 探到已安装的 DSH 时会把根目录写进
// `DSH_SLEUTH_TOOLS_ROOT`，于是冒烟测试用真的 `defineTool` 校验工具定义——参数写法不对会当场红
// （实测踩过：面板用 JSON-Schema 包装写法、真品只认 DSL，装进 profile 后整个 host 半挂不上）。
// 找不到 DSH 时退回本地 stub，调用侧会如实说明这一次校验的强度。
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const stubUrl = pathToFileURL(join(here, 'panel-bundle-dsh-tools-stub.mjs')).href

function realToolsUrl() {
  const root = process.env.DSH_SLEUTH_TOOLS_ROOT
  if (root === undefined || root === '') return null
  const entry = join(root, 'node_modules', '@deepseek-ai', 'dsh-tools', 'lib', 'index.js')
  return existsSync(entry) ? pathToFileURL(entry).href : null
}

export function resolve(specifier, context, nextResolve) {
  if (specifier === '@deepseek-ai/dsh-tools') {
    const real = realToolsUrl()
    return { url: real === null ? stubUrl : real, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}
