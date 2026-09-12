#!/usr/bin/env python3
"""report_lint.py —— 人读定位报告的结构自检（diagnose 产出面）

用法：
  python3 scripts/report_lint.py traces/<session_id>.report.md
  python3 scripts/report_lint.py <报告> --trace traces/<session_id>.yaml
  python3 scripts/report_lint.py <报告> --quiet

**刻意不进 CI**（判据强度：原则六——闸门硬度与错误代价匹配）。报告是判断性产出：好不好读、
机制讲没讲透，由人审；能把机器钉住的只有"结构"这一层。硬门会逼出填空式套话，反而伤掉报告
存在的理由（读者要据此自行判断对错）。所以本脚本的定位是 **agent 交付前自检 + 单测式回归**，
不是合入门禁。

检查项（都是结构性的，不评价内容质量）：
  ① 必需小节齐全且非空（元信息 / TL;DR / 背景与现场材料 / 依据链 / 源码分析 / 机制图 /
     修复方案 / 当前状态与下一步 / 沉淀建议；附录可选）
  ② TL;DR 是摘要不是正文（非空、行数有界）
  ③ mermaid 代码块成对闭合，且带语义配色（classDef）——图不配色等于退化成方框堆
  ④ 报告点名的 traces/ 证据路径真实存在（证据落盘纪律的机器面）
  ⑤ 报告写了沉淀建议节时，trace 必须有 sediment_candidates（两侧同源，不许写两套）

退出码：0 通过；1 有失败项；2 用法/文件问题。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 必需小节（按标题关键词匹配，允许编号与措辞小幅差异）
REQUIRED_SECTIONS = [
    ("元信息", 30),
    ("TL;DR", 30),
    ("背景", 60),
    ("依据链", 120),
    ("源码分析", 60),
    ("机制图", 30),
    ("修复方案", 80),
    ("当前状态", 40),
    ("沉淀建议", 60),
    ("附录", 40),        # 时间线 / 命令清单 / 环境备注——跨轮排查靠它
    ("修订记录", 10),    # 报告是活件且 traces/ 无 VCS 历史，变更记录得自带
]
# 元信息必须自证"这份是初判还是已闭环"
META_NEEDS = ["最后更新"]
OPTIONAL_SECTIONS: list[str] = []

HEADING_RE = re.compile(r"^##\s+(.*)$", re.M)
TRACES_PATH_RE = re.compile(r"traces/[A-Za-z0-9._/\-]+")


def split_sections(text: str) -> dict[str, str]:
    """按 `## ` 标题切分：{标题原文: 正文}。"""
    out: dict[str, str] = {}
    marks = list(HEADING_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1).strip()] = text[m.end():end]
    return out


def find_section(sections: dict[str, str], keyword: str) -> tuple[str, str] | None:
    for title, body in sections.items():
        if keyword.lower() in title.lower():
            return title, body
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="报告路径（traces/<session_id>.report.md）")
    ap.add_argument("--trace", default="", help="配套 trace（默认取同目录同名的 .yaml）")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上两级）")
    ap.add_argument("--quiet", action="store_true", help="只打印失败项")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    report = Path(args.report)
    if not report.is_absolute():
        report = Path.cwd() / report
    if not report.is_file():
        print(f"report_lint: 报告不存在: {report}", file=sys.stderr)
        return 2
    text = report.read_text(encoding="utf-8")
    sections = split_sections(text)

    failures: list[str] = []
    checks: list[str] = []

    def ok(label: str) -> None:
        checks.append(label)

    # ① 必需小节齐全且非空
    for keyword, min_chars in REQUIRED_SECTIONS:
        hit = find_section(sections, keyword)
        if hit is None:
            failures.append(f"缺小节「{keyword}」")
            continue
        body = hit[1].strip()
        if len(body) < min_chars:
            failures.append(f"小节「{hit[0]}」内容过短（{len(body)} 字 < {min_chars}）——空节等于没有")
    if not failures:
        ok(f"必需小节齐全且非空（{len(REQUIRED_SECTIONS)} 节）")

    # ①b 元信息自证首次/已修订
    meta = find_section(sections, "元信息")
    if meta is not None:
        absent = [k for k in META_NEEDS if k not in meta[1]]
        if absent:
            failures.append("元信息缺「" + "」「".join(absent) + "」——读者无法判断这份是初判还是已闭环")
        else:
            ok("元信息含最后更新")

    # ② TL;DR 是摘要不是正文
    tldr = find_section(sections, "TL;DR")
    if tldr is not None:
        lines = [ln for ln in tldr[1].splitlines() if ln.strip()]
        if not lines:
            failures.append("TL;DR 为空")
        elif len(lines) > 6:
            failures.append(f"TL;DR 有 {len(lines)} 行非空内容——它是摘要，机制与细节放到第 4、5 节")
        else:
            ok(f"TL;DR 是摘要（{len(lines)} 行）")

    # ③ mermaid 成对 + 语义配色
    fences = re.findall(r"```mermaid\b", text)
    total_fences = len(re.findall(r"^```", text, re.M))
    if fences:
        if total_fences % 2 != 0:
            failures.append(f"代码块围栏不配对（共 {total_fences} 个 ```）——mermaid 块可能没闭合")
        blocks = re.findall(r"```mermaid\b(.*?)```", text, re.S)
        plain = [i + 1 for i, b in enumerate(blocks) if "classDef" not in b]
        if plain:
            failures.append("mermaid 图未定义语义配色（缺 classDef）：第 " + "、".join(map(str, plain)) + " 张")
        else:
            ok(f"mermaid 图 {len(blocks)} 张，均成对闭合且带 classDef")
    else:
        ok("无 mermaid 图（配置层问题可无图）")

    # ④ 报告点名的 traces/ 证据路径必须真实存在
    named = sorted(set(TRACES_PATH_RE.findall(text)))
    missing = [p for p in named if not (root / p).exists()]
    if missing:
        failures.append("报告点名的路径不存在: " + "、".join(missing[:5]))
    else:
        ok(f"点名的 traces/ 路径都存在（{len(named)} 条）")

    # ⑤ 沉淀建议与 trace 的 sediment_candidates 同源
    if find_section(sections, "沉淀建议") is not None:
        if args.trace:
            trace_path = Path(args.trace)
        else:
            # 约定 `<session_id>.report.md` ↔ `<session_id>.yaml`（同名不同后缀，with_suffix 会把
            # `.report.md` 只换掉 `.md` → 得到 `.report.yaml`，所以按后缀前缀手工截）
            name = report.name
            base = name[: -len(".report.md")] if name.endswith(".report.md") else report.stem
            trace_path = report.with_name(base + ".yaml")
        if not trace_path.is_absolute():
            trace_path = Path.cwd() / trace_path
        if not trace_path.is_file():
            failures.append(f"报告有沉淀建议节，但配套 trace 找不到: {trace_path.name}")
        else:
            try:
                import yaml  # 报告自检依赖 PyYAML（与面板 host 的度量脚本同源依赖）
            except ModuleNotFoundError:
                print("report_lint: 需要 PyYAML（pip install pyyaml）", file=sys.stderr)
                return 2
            doc = yaml.safe_load(trace_path.read_text(encoding="utf-8")) or {}
            cands = doc.get("sediment_candidates") or []
            if not cands:
                failures.append("报告有沉淀建议节，但 trace 缺 sediment_candidates（两侧必须同源）")
            else:
                body = find_section(sections, "沉淀建议")[1].lower()
                absent = [str(c.get("kind")) for c in cands if c and str(c.get("kind", "")).lower() not in body]
                if absent:
                    failures.append("trace 里有报告未提到的候选类型: " + "、".join(absent))
                else:
                    ok(f"沉淀建议与 trace 同源（{len(cands)} 条候选）")

    for label in checks:
        if not args.quiet:
            print(f"  ✓ {label}")
    if failures:
        print(f"\n失败 {len(failures)} 项：")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    if not args.quiet:
        print("\n报告结构通过")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()   # Windows 上标准流默认 locale 编码（GBK），✓/✗ 会直接 UnicodeEncodeError
    sys.exit(main())
