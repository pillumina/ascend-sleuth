#!/usr/bin/env python3
# fixtures/make_broken_metrics_root.py —— 造"体检器不可判定"的临时 root，供回归闸门断言。
#
# 存在的理由（EV-2026-055 的教训）：`metrics_health.py --check` 的退出码三态
# （0 判据全部评过且无越界 / 1 有判据被违反 / 2 有判据未被评估）里，**2 这一态最难自测**——
# 它要求"数据齐备但判据读不到/没实现"，而真实仓库永远给不出这个状态。
# 于是造两个场景：
#   A. gates.yaml 里多一条本体检器不认识的 dimension（判据被声明但没实现）
#   B. gates.yaml 语法坏掉（连判据都读不出来；修前这会让体检器报 "clean"，最危险的假绿）
# 数据侧用 junction 指回真实检出（只读、不复制 173 个 case）——只在 Windows 上可造；
# 非 Windows 退化为复制最小结构（本脚本只服务本地回归，不进 CI）。
#
# 用法：python3 fixtures/make_broken_metrics_root.py --repo <检出根> --out <临时 root> --case A|broken_config
# 写完后由调用方执行：python3 scripts/metrics_health.py --check --root <out>

import argparse
import shutil
import sys
from pathlib import Path

BROKEN_CONFIG_CASE = "broken_config"

# 场景 A 用的假闸门：dimension 不在 IMPLEMENTED_GATE_DIMENSIONS 里
FAKE_GATE = """  - id: brand_new_gate
    dimension: not_implemented_dim
    op: ">"
    value: 1
    meaning: 造出来的未实现判据（回归夹具）
    action: 无
"""


def link_or_copy(src: Path, dst: Path) -> None:
    """目录链接优先（Windows junction 不复制 173 个 case），失败则复制。"""
    if dst.exists():
        return
    try:
        import _winapi  # type: ignore
        _winapi.CreateJunction(str(src), str(dst))
        return
    except Exception:
        pass
    try:
        dst.symlink_to(src, target_is_directory=True)
        return
    except Exception:
        pass
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--case", required=True, choices=["A", BROKEN_CONFIG_CASE])
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "metrics").mkdir(parents=True)

    gates = (repo / "metrics" / "gates.yaml").read_text(encoding="utf-8")
    timeline_src = repo / "metrics" / "timeline.yaml"
    if timeline_src.exists():
        shutil.copy2(timeline_src, out / "metrics" / "timeline.yaml")

    if args.case == "A":
        # 在 cell_hard_cap 之前插一条本体检器不认识的判据
        marker = "  - id: cell_hard_cap"
        if marker not in gates:
            print(f"夹具前提不成立：{marker!r} 不在 gates.yaml 里（格式变了？）", file=sys.stderr)
            return 1
        gates = gates.replace(marker, FAKE_GATE + marker, 1)
    else:
        # 语法坏掉：在第一个 value 行尾追加非法内容
        lines = gates.split("\n")
        for i, line in enumerate(lines):
            if line.strip().startswith("value:"):
                lines[i] = line + ": broken"
                break
        gates = "\n".join(lines)

    (out / "metrics" / "gates.yaml").write_text(gates, encoding="utf-8")
    # 数据侧就位（判据之外的部分要与真实检出等价，否则 exit 2 会来自"数据缺失"而不是"判据不可判定"）
    link_or_copy(repo / "knowledge", out / "knowledge")
    link_or_copy(repo / "scripts", out / "scripts")
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
