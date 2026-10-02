// panel-bundle-dsh-tools-stub.mjs —— `@deepseek-ai/dsh-tools` 的最小替身（只给冒烟测试用）
//
// 真品给工具定义打标记；面板在常驻包里只注册一个附带工具（ascend_trace_status），
// 冒烟测试只关心它有没有走到注册这一步，不关心标记，所以原样返回即可。
export function defineTool(definition) {
  return definition
}
