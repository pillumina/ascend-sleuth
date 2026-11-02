"""端到端并发场景：两个独立 inbox、同一 M0 groom、A 先合入、B 过期、重跑后通过。

这是任务里 TOCTOU 场景的可执行版本。它不证明语义去重正确（那需要 agent 判断），
只证明**工作流**在并发合入时不会拿旧结论放行。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, git, init_repo, make_index, run_py, write_case, write_draft,
)


def run_ok(test, repo, *args):
    p = run_py(repo, *args)
    test.assertEqual(p.returncode, 0, f"{args}\n{p.stdout}\n{p.stderr}")
    return p


def groom_once(test, clone, draft_key, coverage_case=None):
    """跑一遍 snapshot → candidates → fake agent result → record，返回 (meta, marker, work)。"""
    base = clone.parent
    snap = base / "snap.json"
    p = run_ok(test, clone, "scripts/groom_snapshot.py", "--remote", "origin", "--json",
               "--snapshot-dir", str(base / "snaps"))
    snap.write_text(p.stdout, encoding="utf-8")
    meta = json.loads(p.stdout)
    work = base / "work.json"
    run_ok(test, clone, "scripts/groom_candidates.py", "--snapshot", str(snap),
           "--all", "--out", str(work), "--top", "8")
    order = json.loads(work.read_text(encoding="utf-8"))["orders"][0]
    comparisons = []
    for cand in order["candidates"]:
        is_target = coverage_case and cand["id"] == coverage_case
        comparisons.append({
            "candidate_case": cand["id"],
            "classification": "covered" if is_target else "new_pattern",
            "confidence": "high",
            "evidence": {
                "root_cause": "same" if is_target else "different",
                "mechanism": "same" if is_target else "different",
                "fix": "same" if is_target else "different",
            },
            "rationale": "同一根因与失效机制" if is_target else "根因不同",
            "review_required": False,
        })
    results = base / "results"
    results.mkdir(exist_ok=True)
    (results / f"{draft_key}.result.json").write_text(json.dumps({
        "draft_key": draft_key, "agent": {"id": "fake-comparator"}, "comparisons": comparisons,
        "work_order_id": order["work_order_id"],
        "snapshot_commit": order["snapshot"]["commit"],
        "draft_sha256": order["draft"]["case_sha256"],
        "candidate_ids": [c["id"] for c in order["candidates"]],
    }, ensure_ascii=False), encoding="utf-8")
    run_ok(test, clone, "scripts/groom_record.py", "--snapshot", str(snap),
           "--work-orders", str(work), "--results-dir", str(results))
    marker = run_ok(test, clone, "scripts/groom_record.py", "--snapshot", str(snap),
                    "--pr-marker", "--draft-key", draft_key).stdout
    return meta, marker, work


class ConcurrentWorkflowTest(unittest.TestCase):
    def test_a_merges_before_b(self):
        with tempfile.TemporaryDirectory(prefix="groom-flow-") as tmp:
            base = Path(tmp)
            origin = base / "origin.git"
            git(base, "init", "--bare", "-q", str(origin))
            seed = init_repo(base / "seed")
            write_case(seed, "knowledge/inference/vllm-ascend/interrupt/CASE-BASE.yaml",
                       cid="CASE-BASE", title="unrelated baseline", symptoms=("baseline",),
                       root_cause="baseline", fix="none", tags=("baseline",))
            make_index(seed)
            git(seed, "remote", "add", "origin", str(origin))
            git(seed, "push", "-q", "-u", "origin", "main")

            a = base / "clone-a"
            b = base / "clone-b"
            for clone in (a, b):
                git(base, "clone", "-q", "-b", "main", str(origin), str(clone))
                git(clone, "config", "user.email", "x@example.com")
                git(clone, "config", "user.name", "x")

            write_draft(a, key="draft-a", cid="DRAFT-A",
                        title="网络链路中断导致 HCCL 集合通信超时",
                        symptoms=("HCCL timeout during allreduce", "network link down"),
                        root_cause="网络链路故障导致 HCCL 超时",
                        fix="恢复链路后重启训练", tags=("hccl", "network"),
                        sig="HCCL timeout")
            write_draft(b, key="draft-b", cid="DRAFT-B",
                        title="interconnect interruption blocked collective communication",
                        symptoms=("collective communication blocked", "HCCL timeout"),
                        root_cause="网络链路中断导致 HCCL 超时",
                        fix="恢复链路后重启训练", tags=("hccl", "network"),
                        sig="HCCL timeout")

            m0 = git(a, "rev-parse", "HEAD").stdout.strip()
            meta_a, marker_a, _ = groom_once(self, a, "draft-a")
            self.assertEqual(meta_a["commit"], m0)

            # B 与 A 独立：在 A 合入**之前**对同一个 M0 完成 groom
            meta_b, marker_b, work_b = groom_once(self, b, "draft-b")
            self.assertEqual(meta_b["commit"], m0)
            write_case(b, "knowledge/inference/vllm-ascend/interrupt/CASE-NET-B.yaml",
                       cid="CASE-NET-B", title="collective communication blocked by interconnect interruption",
                       symptoms=("collective communication blocked", "HCCL timeout"),
                       root_cause="网络链路中断导致 HCCL 超时", fix="恢复链路后重启训练",
                       tags=("hccl", "network"), sig="HCCL timeout")
            commit_all(b, "PR-B: add case")
            before = (b / "postmortems/inbox/draft-b.case.yaml").read_bytes()

            # A 把草稿升格为 case，提 PR 并合入 main（模拟）
            write_case(a, "knowledge/inference/vllm-ascend/interrupt/CASE-NET-LINK.yaml",
                       cid="CASE-NET-LINK", title="HCCL timeout caused by network link down",
                       symptoms=("HCCL timeout during allreduce", "network link down"),
                       root_cause="网络链路故障导致 HCCL 超时", fix="恢复链路后重启训练",
                       tags=("hccl", "network"), sig="HCCL timeout")
            commit_all(a, "PR-A: add case")
            make_index(a)          # 模拟合入后主干 job 重建生成物
            git(a, "push", "-q", "origin", "main")
            m1 = git(a, "rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(m0, m1)

            # B 合入前复核：base 已是 M1 → stale + 可能撞车
            git(b, "fetch", "-q", "origin", "main")
            body = base / "pr-b.md"
            body.write_text(marker_b, encoding="utf-8")
            p = run_py(b, "scripts/groom_recheck.py", "--pr-body-file", str(body),
                       "--base", m1, "--head", "HEAD")
            self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
            self.assertIn("assessment-stale", p.stdout)
            self.assertIn("possible-duplicate-after-merge", p.stdout)

            # B 对 M1 重跑 groom：候选里应看到 A 已合入的 case，评估为 covered
            git(b, "fetch", "-q", "origin", "main")
            git(b, "reset", "--hard", "-q", m0)     # covered 意味着不升格；撤掉本地 PR 的 case
            meta_b2, marker_b2, work_b2 = groom_once(self, b, "draft-b",
                                                     coverage_case="CASE-NET-LINK")
            self.assertEqual(meta_b2["commit"], m1)
            ids = [c["id"] for c in json.loads(work_b2.read_text(encoding="utf-8"))["orders"][0]["candidates"]]
            snap_dir = Path(json.loads(work_b2.read_text(encoding="utf-8"))["snapshot"]["worktree"])
            idx_text = (snap_dir / "knowledge" / "_index.yaml").read_text(encoding="utf-8")
            snap_case = (snap_dir / "knowledge/inference/vllm-ascend/interrupt/CASE-NET-LINK.yaml").exists()
            snap_head = git(snap_dir, "rev-parse", "HEAD").stdout.strip() if (snap_dir / ".git").exists() else None
            self.assertIn("CASE-NET-LINK", ids,
                          f"meta={meta_b2.get('commit')} worktree={meta_b2.get('worktree')} "
                          f"snap_dir={snap_dir} index={meta_b2.get('index')} "
                          f"index_has={'CASE-NET-LINK' in idx_text} case_file={snap_case} "
                          f"snap_head={snap_head} "
                          f"work={work_b2.read_text(encoding='utf-8')[:800]}")

            # 人确认 covered，生成新 marker；复核通过
            run_ok(self, b, "scripts/groom_decide.py", "--snapshot", str(b.parent / "snap.json"),
                   "--draft-key", "draft-b", "--decision", "covered",
                   "--candidate", "CASE-NET-LINK", "--by", "owner-b", "--note", "同一根因")
            marker_b2 = run_ok(self, b, "scripts/groom_record.py",
                               "--snapshot", str(b.parent / "snap.json"),
                               "--pr-marker", "--draft-key", "draft-b").stdout
            body.write_text(marker_b2, encoding="utf-8")
            p = run_py(b, "scripts/groom_recheck.py", "--pr-body-file", str(body),
                       "--base", m1, "--head", "HEAD")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

            # 数据完整性：草稿原字节未改、人决定保留、历史有两轮评估
            self.assertEqual((b / "postmortems/inbox/draft-b.case.yaml").read_bytes(), before)
            import yaml
            sidecars = list((b / "postmortems/inbox/.groom/assessments").glob("*.yaml"))
            self.assertEqual(len(sidecars), 1)
            doc = yaml.safe_load(sidecars[0].read_text(encoding="utf-8"))
            self.assertEqual(doc["human_decision"]["decision"], "covered")
            self.assertEqual(doc["assessment"]["proposed_novelty"], "covered")
            assessed = [h for h in doc["history"] if h["event"] == "assessed"]
            self.assertGreaterEqual(len(assessed), 2)
            self.assertNotEqual(assessed[0]["knowledge_commit"], assessed[-1]["knowledge_commit"])

            # 仍没有自动升格 / 自动合并：B 的 knowledge 目录没有新增 case
            self.assertFalse((b / "knowledge/inference/vllm-ascend/interrupt/CASE-NET-LINK.yaml").exists())


if __name__ == "__main__":
    unittest.main()
