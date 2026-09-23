"""生成物与源的端到端：人交什么、门在什么时候红、union 合并的结果算不算通过。

这次改动的三条主张，每条都得能被一条命令证伪：
  ① **改了 case / 加了路由词却忘重建 → 门红**，且报错给出重跑命令（安全网没丢）；
  ② **PR 带上生成物（分片、总表、聚合）→ 门绿**（生成物随 PR 走，谁都不需要在合并后再跑命令）；
  ③ **union 合并出来的生成物（内容齐全、顺序非规范）→ 覆盖门绿**，逐字节自检红但只是提示——
     它逼不出"再跑一次收尾命令"。
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
    """一个临时仓库：模拟"一个人改完 case 与路由词，把生成物一起提交"的全过程。"""

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

    def add_route_word(self, word="gpWordE2E", family="10-interrupt.yaml",
                       branch="interrupt"):
        p = self.repo / "triage-tree.d" / family
        lines = p.read_text(encoding="utf-8").split("\n")
        start = next(i for i, l in enumerate(lines) if l.strip() == f"- id: {branch}")
        si = next(i for i in range(start, len(lines)) if lines[i].strip() == "symptoms:")
        at = si + 1
        while at < len(lines) and (not lines[at].strip() or lines[at].startswith("      ")):
            at += 1
        lines.insert(at, f'      - ["{word}"]')
        p.write_text("\n".join(lines), encoding="utf-8")

    def regenerate(self):
        """改完内容后跑一次生成器（这是提交前唯一的固定动作）。"""
        self.gate("scripts/build_index.py")
        self.gate("scripts/build_triage_tree.py")

    def gate(self, *args):
        return sh(self.repo, "python3", *args)

    # ---------------------------------------------------------------- ① 安全网还在
    def test_forgetting_to_regenerate_is_red_with_actionable_message(self):
        self.add_case()
        p = self.gate("scripts/build_index.py", "--check")
        self.assertEqual(p.returncode, 1)
        self.assertIn("TEST-GP-1", p.stdout)
        self.assertIn("build_index.py", p.stdout)      # 报错里给的动作就是那条命令

    def test_forgetting_the_route_word_rebuild_is_red(self):
        self.add_route_word()
        p = self.gate("scripts/build_triage_tree.py", "--check-coverage")
        self.assertEqual(p.returncode, 1)
        self.assertIn("缺症状组", p.stdout)

    # ---------------------------------------------------------------- ② PR 带生成物就绿
    def test_pr_with_generated_files_passes_all_gates(self):
        self.add_case()
        self.add_route_word()
        self.regenerate()
        self.assertEqual(self.gate("scripts/build_index.py", "--check").returncode, 0)
        self.assertEqual(self.gate("scripts/build_index.py", "--check", "--canonical").returncode, 0)
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check-sources").returncode, 0)
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check-coverage").returncode, 0)
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check").returncode, 0)

    # ---------------------------------------------------------------- ③ union 的结果算通过
    def test_union_merged_files_pass_coverage_but_flag_canonical(self):
        """模拟平台上的 union 合并：分片里两条 case 的顺序被换过、聚合里两句路由词的顺序被换过。
        内容齐全 → 门绿；逐字节自检红（可选归一化），**不许**因此逼人再跑一遍。"""
        self.add_case("TEST-GP-A")
        self.add_case("TEST-GP-B")
        self.add_route_word("gpWordMine", branch="interrupt")
        self.add_route_word("gpWordTheirs", branch="interrupt")
        self.regenerate()

        cell = self.repo / "knowledge" / "_index" / "inference__vllm-ascend__interrupt.yaml"
        rows = cell.read_text(encoding="utf-8").split("\n    - id: ")
        self.assertGreaterEqual(len(rows), 3)
        cell.write_text("\n    - id: ".join([rows[0]] + list(reversed(rows[1:]))), encoding="utf-8")

        agg = self.repo / "triage-tree.yaml"
        lines = agg.read_text(encoding="utf-8").split("\n")
        i_mine = next(i for i, l in enumerate(lines) if '"gpWordMine"' in l)
        i_theirs = next(i for i, l in enumerate(lines) if '"gpWordTheirs"' in l)
        lines[i_mine], lines[i_theirs] = lines[i_theirs], lines[i_mine]
        agg.write_text("\n".join(lines), encoding="utf-8")

        self.assertEqual(self.gate("scripts/build_index.py", "--check").returncode, 0)
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check-coverage").returncode, 0)
        self.assertNotEqual(self.gate("scripts/build_index.py", "--check", "--canonical").returncode, 0)
        self.assertNotEqual(self.gate("scripts/build_triage_tree.py", "--check").returncode, 0)

    def test_regenerate_normalizes_after_union(self):
        """归一化是可选动作：跑一次生成器，逐字节自检就绿了。"""
        self.add_case("TEST-GP-A")
        self.add_route_word("gpWordMine", branch="interrupt")
        self.regenerate()
        agg = self.repo / "triage-tree.yaml"
        agg.write_text(agg.read_text(encoding="utf-8") + "# 手工加的一行（非规范形态）\n",
                       encoding="utf-8")
        self.assertNotEqual(self.gate("scripts/build_triage_tree.py", "--check").returncode, 0)
        self.gate("scripts/build_triage_tree.py")
        self.assertEqual(self.gate("scripts/build_triage_tree.py", "--check").returncode, 0)

    # ---------------------------------------------------------------- 读侧不变
    def test_aggregate_still_readable_and_complete(self):
        self.add_route_word("gpWordE2E")
        self.regenerate()
        doc = yaml.safe_load((self.repo / "triage-tree.yaml").read_text(encoding="utf-8"))
        self.assertEqual([b["id"] for b in doc["natures"]][0], "interrupt")
        self.assertIn("gpWordE2E", (self.repo / "triage-tree.yaml").read_text(encoding="utf-8"))

    def test_counts_are_computed_not_stored(self):
        """结构数字不再落进生成物：要数字就现算（这也是 union 能用的前提）。"""
        self.add_case("TEST-GP-A")
        self.regenerate()
        head = (self.repo / "knowledge" / "_index.yaml").read_text(encoding="utf-8").split("namespaces:")[0]
        self.assertNotIn("case 总数：", head)
        self.assertNotIn("容量(", head)
        out = sh(self.repo, "python3", "scripts/index_counts.py", "--json").stdout
        self.assertEqual(yaml.safe_load(out)["total"], 169)


if __name__ == "__main__":
    unittest.main()
