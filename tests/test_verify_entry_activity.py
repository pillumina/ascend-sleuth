#!/usr/bin/env python3
"""`scripts/verify_entry_activity.py` 的门：唯一键、归周、引用、部署名。

为什么单开这份测试：这一层是**记录的唯一约束**，而它此前只有 CI 在真实仓库上跑——真实
仓库里出现过的两种坏行都没有回归测试兜住：

1. 同一 (run, kind, id) 写了两次、内容不同。这不是"重复保留"（union 合并会留下逐字节
   相同的两份，那没问题），而是同一次运行被写了两遍不同结果——多半是并发重跑时游标
   没清。真实出现过：一次 polish 里重算记录，`2026-10-18-2138` 的 bash 行出现了两种
   p90，CI 直接红。
2. run 的周与文件名的周对不上。归周错了，本期增量会算进别的周，而看板上看不出来。

两种都只在"写脚本的人踩过一次"之后才会想到，所以在这里各钉一条。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_entry_activity as v  # noqa: E402
from _stdio import pin_utf8_stdio  # noqa: E402

# 脚本函数在本进程内被直接调用，print 也会写到测试进程的 stdout：Windows 上
# 重定向成管道/文件时默认 cp936，非 GBK 字符（✓ ✗ ⚠）会直接抛 UnicodeEncodeError。
pin_utf8_stdio()

HEADER = "# 测试用源文件\n"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "metrics" / "entry-activity.d").mkdir(parents=True)
        # 一条真实存在的案例 id：引用检查要能过
        self.case_id = "VLLM-ASC-10322"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, rows: list[str]):
        (self.root / "metrics" / "entry-activity.d" / name).write_text(
            HEADER + "\n".join(rows) + "\n", encoding="utf-8")

    def run_verify(self):
        code, detail = v.verify(self.root)
        # 所有"该报红"的类别合成一袋，测试按类别挑
        problems = (detail.get("problems") or []) + (detail.get("week_mismatch") or []) \
            + (detail.get("orphans") or []) + (detail.get("duplicates") or []) \
            + (detail.get("generated") or [])
        return code, problems, (detail.get("notes") or [])


class UniqueKeyTest(Fixture):
    def test_same_key_byte_identical_is_allowed(self):
        """union 合并会留下逐字节相同的两份行：那不是冲突，只算一次。"""
        row = ("- {run: 2026-10-17-2124, deployment: ascend-sleuth, kind: case, id: "
               + self.case_id + ", selected: 1, loaded: 1, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}")
        self.write("2026-W42.yaml", [row, row])
        _code, problems, notes = self.run_verify()
        self.assertEqual([p for p in problems if "重复且内容不同" in p], [])
        self.assertTrue(any("逐字节相同" in n for n in notes))

    def test_same_key_different_content_is_red(self):
        """同一次运行写了两种结果 = 并发重跑留下的冲突行，必须报红。"""
        a = ("- {run: 2026-10-17-2124, deployment: ascend-sleuth, kind: case, id: "
             + self.case_id + ", selected: 1, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}")
        b = ("- {run: 2026-10-17-2124, deployment: ascend-sleuth, kind: case, id: "
             + self.case_id + ", selected: 2, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}")
        self.write("2026-W42.yaml", [a, b])
        _code, problems, _ = self.run_verify()
        self.assertTrue(any("重复且内容不同" in p for p in problems), problems)

    def test_different_run_same_id_is_not_duplicate(self):
        """两次运行各写一行是正常追加，不是重复。"""
        a = ("- {run: 2026-10-17-2124, deployment: ascend-sleuth, kind: case, id: "
             + self.case_id + ", selected: 1, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}")
        b = ("- {run: 2026-10-17-2138, deployment: ascend-sleuth, kind: case, id: "
             + self.case_id + ", selected: 1, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}")
        self.write("2026-W42.yaml", [a, b])
        _code, problems, _ = self.run_verify()
        self.assertEqual([p for p in problems if "重复且内容不同" in p], [])


class WeekTest(Fixture):
    def test_run_week_must_match_file_week(self):
        """run 落在哪一周，就得写在那一周的文件里——归周错了看板上看不出来。"""
        row = ("- {run: 2026-10-17-2124, deployment: ascend-sleuth, kind: case, id: "
               + self.case_id + ", selected: 1, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}")
        self.write("2026-W41.yaml", [row])       # 故意的：W42 的行写进了 W41
        _code, problems, _ = self.run_verify()
        self.assertTrue(any("落在" in p and "写在" in p for p in problems), problems)

    def test_baseline_run_is_not_week_checked(self):
        """搬运行用 `baseline-<日期>` 当 run，没有周，不该被判归周失败。"""
        row = ("- {run: baseline-2026-10-17, deployment: ascend-sleuth, kind: baseline, id: "
               + self.case_id + ", resolved: 1, misdiagnosed: 0, self_resolved: 0}")
        self.write("2026-W42.yaml", [row])
        _code, problems, _ = self.run_verify()
        self.assertEqual([p for p in problems if "落在" in p], [])


class RefTest(Fixture):
    def test_unknown_id_is_red(self):
        """id 必须在知识库里查得到，否则聚合时这条记录永远匹配不上任何条目。"""
        row = "- {run: 2026-10-17-2124, deployment: ascend-sleuth, kind: case, id: VLLM-ASC-00000, selected: 1, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0, excluded: 0}"
        self.write("2026-W42.yaml", [row])
        _code, problems, _ = self.run_verify()
        self.assertTrue(any("VLLM-ASC-00000" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
