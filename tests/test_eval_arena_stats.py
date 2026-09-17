"""eval_arena 打分侧的两处口径（本卡机制修正）。

护两件事：
① **result 字段两套写法都认**：盘上的 result 文件写 `tier2_hit` / `routing_ok` / `root_cause_ok`，
   而工具早期只读 `hit_case` / `route` / `rc_match`。只认一套的代价是**结论一致（rc）一路恒为
   None**——判定少一路证据，账本里也分不清"没有数据"和"结论不一致"。
② **缺参要明确退化**：`--gate` 不给 baseline/candidate 时，旧行为是拿空路径去读仓库根，报
   "Is a directory" 这种和真因无关的错；现在退 2 并打印"下一步该建池/跑 stats"。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_arena as ea  # noqa: E402
import yaml  # noqa: E402

POOL = """\
name: pool-t
split: selection
issues:
  - {id: "101", expected_ns: "inference/vllm-ascend", fix_ref: "PR#1"}
  - {id: "102", expected_ns: "inference/vllm-ascend", fix_ref: "PR#2"}
"""

NEW_STYLE = """\
namespace: inference/vllm-ascend
category: interrupt
hit_case: ""
tier2_hit: false
routing_ok: true
root_cause_ok: true
"""

OLD_STYLE = """\
namespace: inference/vllm-ascend
route: ok
hit_case: CASE-A
rc_match: false
"""


class StatsFieldCompatTest(unittest.TestCase):
    def _run(self, results):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        arena = root / ".s2-replay" / "arena"
        arena.mkdir(parents=True)
        (arena / "pool-t.yaml").write_text(POOL, encoding="utf-8")
        for iid, text in results.items():
            (root / ".s2-replay" / f"{iid}.result.yaml").write_text(text, encoding="utf-8")
        self.assertEqual(ea.cmd_stats(root, arena / "pool-t.yaml"), 0, "cmd_stats 应成功")
        return yaml.safe_load((arena / "stats-pool-t.yaml").read_text(encoding="utf-8"))

    def test_reads_new_style_fields(self):
        s = self._run({"101": NEW_STYLE, "102": NEW_STYLE})
        self.assertTrue(all(v["route_ok"] for v in s["issues"]))
        self.assertTrue(all(v["rc_match"] is True for v in s["issues"]),
                        "root_cause_ok 必须被读成 rc_match（旧实现恒为 None）")
        self.assertTrue(all(v["hit"] is False for v in s["issues"]))

    def test_reads_old_style_fields(self):
        s = self._run({"101": OLD_STYLE, "102": OLD_STYLE})
        self.assertTrue(all(v["hit"] for v in s["issues"]))
        self.assertTrue(all(v["rc_match"] is False for v in s["issues"]))
        self.assertTrue(all(v["route_ok"] for v in s["issues"]))

    def test_pool_hash_written(self):
        s = self._run({"101": NEW_STYLE, "102": NEW_STYLE})
        self.assertTrue(s.get("pool_hash"), "池内容哈希缺失 → 复用计数无法按量尺归零")


class GateArgValidationTest(unittest.TestCase):
    def test_gate_without_args_exits_2_with_next_step(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_arena.py"), "--gate"],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(p.returncode, 2)
        self.assertIn("baseline", p.stderr)
        self.assertIn("--self-test", p.stderr, "缺数据时要说清该怎么走，而不是报与真因无关的错")


if __name__ == "__main__":
    unittest.main()
