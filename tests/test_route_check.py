"""route_check（提交前自查：这条 case 会被哪个分支接住）的口径回归测试。

为什么值得测：这个脚本是**内容类 PR 预核**里唯一能跑的动作，而它的结论会被写进 PR 的
「Agent 预核意见」。它错两边的代价不对称——误报（把正常的顺序差异说成问题）会让人忽略它，
漏报（本该报的分支误吸不报）等于这个动作不存在。所以下面钉三件事：
期望分支怎么推、首个命中怎么判、宽词重复怎么列。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import route_check as RC  # noqa: E402

TRIAGE = """branches:
  - id: training_interrupt
    category: interrupt
    symptoms:
      - ["\\\\btimeout\\\\b", "RuntimeError"]
    search_namespaces:
      - training/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: inference_interrupt
    category: interrupt
    symptoms:
      - ["\\\\btimeout\\\\b", "EE9999"]
    search_namespaces:
      - inference/<detected_framework>/
      - common/
    fallback: Tier 3
"""

CASE = """cases:
  - id: {cid}
    title: "{title}"
    category: interrupt
    tags: [t]
    confidence: {{score: 0.5}}
    symptoms:
      - "{sym}"
"""


class RouteCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "triage-tree.yaml").write_text(TRIAGE, encoding="utf-8")
        self.branches = RC.load_branches(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid="T-1", title="t", sym="s"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid, title=title, sym=sym), encoding="utf-8")
        return p

    def test_hits_follow_branch_order(self):
        """按聚合顺序返回——顺序就是"谁先接住"，这正是这个脚本要报的东西。"""
        hits = RC.hits_for("服务 \btimeout\b 了", self.branches)
        self.assertEqual([b for b, _ in hits], ["training_interrupt", "inference_interrupt"])

    def test_hits_report_first_matching_pattern_per_branch(self):
        hits = RC.hits_for("RuntimeError: 超时", self.branches)
        self.assertEqual(hits, [("training_interrupt", "RuntimeError")])

    def test_no_hit_returns_empty(self):
        self.assertEqual(RC.hits_for("完全没有关键词", self.branches), [])

    def test_expected_branch_from_path(self):
        """期望分支从路径推：knowledge/<训推>/<框架>/<性质>/x.yaml → <训推>_<性质>。"""
        p = self.write_case("inference/vllm-ascend/interrupt/X.yaml")
        self.assertEqual(RC.expected_branch(p, self.root), "inference_interrupt")
        p2 = self.write_case("training/verl/precision/X.yaml")
        self.assertEqual(RC.expected_branch(p2, self.root), "training_precision")

    def test_common_case_is_not_judged(self):
        """common/ 的共性 case 不参与路由（框架无关）→ 不该硬套一个期望分支。"""
        p = self.write_case("common/performance/X.yaml")
        self.assertEqual(RC.expected_branch(p, self.root), "")

    def test_wide_words_lists_cross_branch_patterns(self):
        ww = dict(RC.wide_words(self.branches))
        self.assertIn("\\btimeout\\b", ww)
        self.assertEqual(ww["\\btimeout\\b"], ["training_interrupt", "inference_interrupt"])
        self.assertNotIn("EE9999", ww)          # 只在 inference 侧 → 不是宽词

    def test_cli_flags_first_hit_mismatch(self):
        """期望 inference 但首个命中 training → exit 1 并说清缺什么。这是它的全部价值所在。"""
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-MIS", sym="\\btimeout\\b 了")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("首个命中是 training_interrupt", r.stdout)

    def test_cli_passes_when_expected_branch_hits_first(self):
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="T-OK", sym="EE9999 报错")
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"),
                            "knowledge/inference/vllm-ascend/interrupt/X.yaml",
                            "--root", str(self.root)],
                           capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("inference_interrupt", r.stdout)

    def test_cli_wide_words_mode(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/route_check.py"), "--wide-words",
                            "--root", str(self.root)], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("跨分支重复的正则", r.stdout)


if __name__ == "__main__":
    unittest.main()
