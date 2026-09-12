#!/usr/bin/env python3
# make_degraded_evolve_root.py —— 造"退化检出根"，供面板退化路径的回归断言使用
#
# 为什么需要它：面板的退化分支（无 exec-log / 无 timeline / 无卡 / 判据文件缺席）原先只在
# **本机恰好缺该文件**时才被执行——而工作机上 exec-log 与 timeline 都在，于是"exec-log
# 不存在会怎样"从未被任何一次回归跑过，rehearse 的沙箱又会把 metrics/ 一并复制过去，
# 同样命中正常分支。实测是用户问出来的，不该靠运气。
#
# 用法：
#   python3 scripts/fixtures/make_degraded_evolve_root.py --repo . --out <根> --case no-exec-log
# case 取值：no-exec-log | no-metrics | empty-cards | no-gates | broken-gates
# 造出的根是**最小可运行集**（metrics/timeline.yaml 是真数据的一份拷贝，卡取一张真实卡），
# 让退化只发生在被考察的那一处，其余走真实路径。

import argparse
import shutil
import sys
from pathlib import Path

# 本文件在 scripts/fixtures/ 下——`_stdio` 在 scripts/，需要把父目录加进来
# （同级夹具 make_broken_metrics_root.py 不用输出中文，所以没遇到这一条）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CASES = ("no-exec-log", "no-metrics", "empty-cards", "no-gates", "broken-gates")
# 运行时件：造退化根时**一律不拷**（它们的缺席正是要被测的路径；真机上它们是否在是偶然的）
RUNTIME_SKIP = ("skill-exec-log.yaml", "skill-exec-log.yaml.lock",
                "ev-measure-log.yaml", "ev-measure-log.yaml.lock")


def main():
    ap = argparse.ArgumentParser(description="造退化检出根（面板退化路径回归用）")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--case", required=True, choices=CASES)
    args = ap.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    needs_metrics = args.case != "no-metrics"
    if needs_metrics:
        (out / "metrics").mkdir()
        src = repo / "metrics" / "timeline.yaml"
        if src.exists():
            shutil.copy(src, out / "metrics" / "timeline.yaml")

    needs_card = args.case != "empty-cards"
    if needs_card:
        (out / "proposals" / "ideas").mkdir(parents=True)
        cards = sorted((repo / "proposals" / "ideas").glob("*.yaml"))
        if cards:
            shutil.copy(cards[-1], out / "proposals" / "ideas" / cards[-1].name)

    if args.case in ("no-gates", "broken-gates"):
        (out / "proposals").mkdir(parents=True, exist_ok=True)
    if args.case == "broken-gates":
        (out / "proposals" / "gates.yaml").write_text("gates: [ 这不是合法的 mapping\n",
                                                      encoding="utf-8")
    elif args.case != "no-gates":
        src = repo / "proposals" / "gates.yaml"
        if src.exists():
            (out / "proposals").mkdir(parents=True, exist_ok=True)   # empty-cards 时 proposals/ 尚未建
            shutil.copy(src, out / "proposals" / "gates.yaml")

    # 知识库索引头注（容量判据的来源）：缺席也是合法退化路径，这里不拷，保持"最小集"
    print(str(out))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
