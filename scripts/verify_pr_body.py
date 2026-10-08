#!/usr/bin/env python3
# verify_pr_body.py —— 校验 PR body 的模板结构完整性（kb-checks CI）
#
# 设计约束（2026-08-30 讨论）：
#   - 只校验"用了正确的模板 + 关键结构字段存在"——这是流程完整性的保证
#   - **不校验 Agent 预核意见是否填写**——agent 提交链路未打通的人
#     （内网平台 / 手动提交）不应被硬卡；意见是可选增值，不是流程门槛
#   - 模板结构锚点 = 模板文件里的 "## " 区块标题（五类首节都必须是"背景与动机"、
#     knowledge 类必须有三分类、高风险类必须有触发条款/双签、methodology 必须有回归检查…）
#   - "背景与动机" 只进 REQUIRED_SECTIONS，不进 TEMPLATE_HINTS：它对五类模板都成立，
#     放进特征词只会抬高所有模板的匹配分，让只写了这一节的 body 被误判成某个模板
#   - 必含区块按"行首 `## ` 标题"匹配，不按整段 body 的子串包含：后者会被注释里的同一串
#     字面量绕过（2026-10-08 独立预核给出的反例），门就形同不存在
#
# 用法（CI）：PR body 经 stdin 传入
#   gh pr view <N> --json body --jq .body | python3 scripts/verify_pr_body.py
# 非零退出 = 模板结构缺失（流程没走对）。只警告不拦截 Agent 意见区块。

import re
import sys

# 模板 → 必含的"## "区块锚点（流程完整性的最小集；Agent 意见区块不在此列）
REQUIRED_SECTIONS = {
    "knowledge_intake": ["背景与动机", "预分诊结论", "脱敏自查", "完整性"],
    "knowledge_modification": ["背景与动机", "触发条款", "变更依据", "双签", "影响与回退"],
    "reference": ["背景与动机", "变更类型", "词条清单", "来源与验证状态", "聚类检查"],
    "methodology": ["背景与动机", "变更内容", "原则追溯", "回归检查", "影响面"],
    "structure": ["背景与动机", "变更类型", "依据", "迁移完整性检查单", "双签"],
}

# body 里出现这些特征词 → 判定为对应模板（宽松匹配，防误判）
TEMPLATE_HINTS = {
    "knowledge_intake": ["预分诊结论", "new_pattern", "covered_by", "variant_of"],
    "knowledge_modification": ["触发条款", "变更依据", "双签"],
    "reference": ["词条清单", "聚类检查", "来源与验证状态"],
    "methodology": ["原则追溯", "回归检查", "影响面"],
    "structure": ["迁移完整性检查单", "路由与结构", "triage-tree"],
}


def detect_template(body: str) -> str | None:
    best, best_score = None, 0
    for tpl, hints in TEMPLATE_HINTS.items():
        score = sum(1 for h in hints if h in body)
        if score > best_score:
            best, best_score = tpl, score
    return best if best_score > 0 else None


def main():
    body = sys.stdin.read()
    if not body.strip():
        print("PR body 为空——未使用任何模板")
        sys.exit(1)

    tpl = detect_template(body)
    if tpl is None:
        print("未识别出 PR 模板——body 不含任何模板特征（预分诊/触发条款/词条清单/回归检查/迁移检查单）")
        print("请使用 .github/PULL_REQUEST_TEMPLATE/ 下的对应模板创建 PR")
        sys.exit(1)

    headings = [l.strip() for l in body.splitlines() if l.strip().startswith("## ")]
    missing = [s for s in REQUIRED_SECTIONS[tpl] if not any(h.startswith(f"## {s}") for h in headings)]
    if missing:
        print(f"识别模板: {tpl}，但缺少关键区块: {missing}")
        print("模板流程未走完整（关键结构字段缺失）——按对应模板补全")
        sys.exit(1)

    # Agent 意见：只提示，不拦截（用户约束——内网/手动链路不被卡）
    has_agent = "Agent 预核意见" in body
    hint = "✓" if has_agent else "—（可选：非 agent 链路可留空，不拦截）"
    print(f"识别模板: {tpl}，关键区块齐全 ✓；Agent 预核意见 {hint}")
    sys.exit(0)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
