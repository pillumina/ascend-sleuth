"""生成物分工的端到端测试：人交什么、合并者补什么、哪道门在哪个面上红。

这次改动的主张有三条，每条都得能被一条命令证伪：
  ① **改了 case 忘重建分片 → PR 门红**（安全网还在，没有因为"生成物不进 PR"就丢掉校验）；
  ② **PR 不带生成物（总表 / triage 聚合）也能过 PR 门**（人不必碰那两张"谁都得重写一遍"的表）；
  ③ **合并者收尾跑完，两张表与源逐字节一致、并且能看到新内容**
     （本平台不允许 CI 推主干，这一步由合并者一条命令完成；忘了会在主干上红并打印这条命令）。
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

CASE = """cases:
  - id: {cid}
    title: "生成物分工实验 {cid}"
    category: interrupt
    tags: [exp]
    confidence:
      score: 0.5
    symptoms:
      - "分工实验症状 {cid}"
"""


def sh(cwd: Path, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


class GeneratedPlaneTest(unittest.TestCase):
    """一个临时仓库：模拟「一个人改完 case 与路由词，合并者收尾补生成物」的全过程。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="generated-plane-")
        self.repo = Path(self.tmp.name) / "repo"
        r = self.repo
        r.mkdir(parents=True)
        shutil.copytree(ROOT / "knowledge", r / "knowledge")
        shutil.copytree(ROOT / "scripts", r / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "triage-tree.d", r / "triage-tree.d")
        for name in (".gitattributes", "triage-tree.yaml"):
            shutil.copy2(ROOT / name, r / name)
        sh(r, "git", "init", "-q", "-b", "main")
        sh(r, "git", "config", "user.email", "t@example.com")
        sh(r, "git", "config", "user.name", "t")
        sh(r, "git", "add", "-A")
        sh(r, "git", "commit", "-qm", "base")

    def tearDown(self):
        self.tmp.cleanup()

    # ---------------------------------------------------------------- 人的动作
    def add_case(self, cid="TEST-GP-1"):
        p = self.repo / "knowledge" / "inference" / "vllm-ascend" / "interrupt" / f"{cid}.yaml"
        p.write_text(CASE.format(cid=cid), encoding="utf-8")

    def add_route_word(self, word="gpWordE2E"):
        p = self.repo / "triage-tree.d" / "40-inference-interrupt.yaml"
        lines = p.read_text(encoding="utf-8").split("\n")
        start = next(i for i, l in enumerate(lines) if l.strip() == "- id: inference_interrupt")
        si = next(i for i in range(start, len(lines)) if lines[i].strip() == "symptoms:")
        at = si + 1
        while at < len(lines) and (not lines[at].strip() or lines[at].startswith("      ")):
            at += 1
        lines.insert(at, f'      - ["{word}"]')
        p.write_text("\n".join(lines), encoding="utf-8")

    def gate(self, *args):
        return sh(self.repo, "python3", *args)

    def merger_rebuild(self):
        """合并者收尾：重建两张生成物表并提交（一条命令的机械动作）。"""
        self.gate("scripts/build_index.py")
        self.gate("scripts/build_triage_tree.py")
        sh(self.repo, "git", "add", "knowledge/_index.yaml", "knowledge/_index", "triage-tree.yaml")
        sh(self.repo, "git", "commit", "-qm", "chore(generated): 主干重建")

    # ---------------------------------------------------------------- ① 安全网还在
    def test_forgetting_to_rebuild_shards_is_red_with_actionable_message(self):
        self.add_case()
        rc = self.gate("scripts/build_index.py", "--check").returncode
        self.assertEqual(rc, 1)
        out = self.gate("scripts/build_index.py", "--check").stdout
        self.assertIn("TEST-GP-1", out)
        self.assertIn("build_index.py", out)      # 报错里给的动作就是那条命令

    def test_forgetting_to_rebuild_shards_also_makes_main_gate_red(self):
        """分片没重建时，主干门也是红的——所以"忘了重建"不会静默留下不一致。"""
        self.add_case()
        self.assertNotEqual(self.gate("scripts/build_index.py", "--check", "--master").returncode, 0)

    # ---------------------------------------------------------------- ② PR 不必带生成物
    def test_pr_gates_pass_without_touching_generated_tables(self):
        """人改了 case + 路由词、重建了分片，但**没碰**总表与 triage 聚合 → PR 门绿。

        这是本次改动的核心：那两张"谁都得重写一遍"的表不再出现在 PR 里，也就不再撞。
        """
        self.add_case()
        self.add_route_word()
        self.gate("scripts/build_index.py")                  # 本地重建（分片要提交）
        # 把两张生成物表退回主干版本，模拟"PR 里不带它们"
        (self.repo / "knowledge" / "_index.yaml").unlink()
        sh(self.repo, "git", "checkout", "--", "triage-tree.yaml")
        self.assertEqual(self.gate("scripts/build_index.py", "--check").returncode, 0)
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check-sources").returncode, 0)
        # 而主干门此刻应当是红的——它由合并者的收尾负责，不是由这个 PR 负责
        self.assertNotEqual(self.gate("scripts/build_index.py", "--check", "--master").returncode, 0)
        self.assertNotEqual(self.gate("scripts/build_triage_tree.py", "--check").returncode, 0)

    def test_triage_pr_gate_does_not_need_the_aggregate(self):
        """triage 的 PR 门比的是源（一族一文件），不是聚合——否则人人都得改那张聚合表。"""
        self.add_route_word()
        (self.repo / "triage-tree.yaml").unlink()
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check-sources").returncode, 0)

    # ---------------------------------------------------------------- ③ 合并者收尾后就一致
    def test_merger_rebuild_brings_both_generated_tables_back_in_sync(self):
        self.add_case()
        self.add_route_word()
        self.gate("scripts/build_index.py")
        (self.repo / "knowledge" / "_index.yaml").unlink()

        self.merger_rebuild()

        self.assertEqual(self.gate("scripts/build_index.py", "--check", "--master").returncode, 0)
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check").returncode, 0)
        # 新内容必须真的进了两张表（不然"门绿"只是自己跟自己一致）
        idx = (self.repo / "knowledge" / "_index.yaml").read_text(encoding="utf-8")
        tri = (self.repo / "triage-tree.yaml").read_text(encoding="utf-8")
        self.assertIn("TEST-GP-1", idx)
        self.assertIn("gpWordE2E", tri)
        # 分片也看得到（阶段一真读的是它，不是总表）
        cell = (self.repo / "knowledge" / "_index" / "inference__vllm-ascend__interrupt.yaml")
        self.assertIn("TEST-GP-1", cell.read_text(encoding="utf-8"))

    def test_generated_tables_are_reproducible(self):
        """同一份源重建两次 → 字节相同。主干门敢逐字节比，就靠这条。"""
        self.add_case()
        self.merger_rebuild()
        first = (self.repo / "knowledge" / "_index.yaml").read_bytes(), \
                (self.repo / "triage-tree.yaml").read_bytes()
        self.merger_rebuild()
        second = (self.repo / "knowledge" / "_index.yaml").read_bytes(), \
                 (self.repo / "triage-tree.yaml").read_bytes()
        self.assertEqual(first, second)

    def test_aggregate_still_readable_by_consumers(self):
        """读侧不变：聚合仍是合法 YAML，分支结构照旧（diagnose / verify_references 读它）。"""
        self.add_route_word()
        self.merger_rebuild()
        doc = yaml.safe_load((self.repo / "triage-tree.yaml").read_text(encoding="utf-8"))
        self.assertEqual([b["id"] for b in doc["branches"]][0], "training_interrupt")
        self.assertIn("gpWordE2E", (self.repo / "triage-tree.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
