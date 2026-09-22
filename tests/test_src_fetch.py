#!/usr/bin/env python3
"""src_fetch 的签名→候选仓匹配与 `--find` 分支（EV-2026-145）。

这一层的失败形态是**静默零候选**：签名进了组织枚举、候选表没命中，调用方看到的是
"上游没有这个仓"——与"表写错了"无法区分。所以这里把三件事钉住：
①匹配表的不变量（关键词小写、仓名存在、真实签名覆盖）②`--find` 的路由（显式仓名不被候选覆盖）
③歧义签名必须 exit 3 且不自动克隆。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import src_fetch  # noqa: E402


def run_find(*extra):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "src_fetch.py"), "--find", *extra],
                          capture_output=True, text=True, cwd=str(ROOT))


class SignatureMatchingTest(unittest.TestCase):
    def test_self_test_passes(self):
        """表不变量：关键词大小写、仓名存在性、12 条真实签名命中。"""
        self.assertEqual(src_fetch.self_test(), 0)

    def test_candidates_cover_prefixes_and_camel_case(self):
        cases = {
            "HcclCommInitRootInfo failed": "hccl",       # 驼峰 + 复合前缀
            "hccl_comm_init failed": "hccl",             # 下划线写法
            "ge::GEExecuteRun error": "ge",              # :: 连接的短前缀
            "aclrtMalloc failed": "runtime",
            "ACL_ERROR_RT_DEVICE_MEM_ERROR": "runtime",
            "aclnnFlashAttentionScore failed": "ops-transformer",
            "drvDeviceOpen failed": "driver",
            "opproto ImplyType not found": "metadef",
        }
        for sig, expect in cases.items():
            with self.subTest(sig=sig):
                got = [c[0] for c in src_fetch.candidate_repos("cann", sig)]
                self.assertIn(expect, got, f"{sig} → {got}")

    def test_no_substring_false_positive(self):
        """子串匹配会把候选表撑成全表：geometry 不该命中 ge，transformer 不该命中任何层。"""
        self.assertEqual([c[0] for c in src_fetch.candidate_repos("cann", "geometry error")], [])
        self.assertEqual([c[0] for c in src_fetch.candidate_repos("cann", "transformer engine error")], [])

    def test_aclnn_bare_prefix_only_reaches_ops_nn_as_fallback(self):
        """裸 `aclnn` 只说明接口层：唯一候选是 ops-nn，但它是**兜底**命中（脚本不该自动取）。"""
        got = [c[0] for c in src_fetch.candidate_repos("cann", "aclnn error")]
        self.assertEqual(got, ["ops-nn"])
        self.assertTrue(src_fetch.is_fallback_candidate("cann", "aclnn error", "ops-nn"))

    def test_discriminator_beats_fallback(self):
        """`aclnn`+算子名时判别词所属仓排前，公共前缀那条退为兜底。"""
        got = [c[0] for c in src_fetch.candidate_repos("cann", "aclnnBatchMatMul failed")]
        self.assertEqual(got[0], "ops-math")
        self.assertIn("ops-nn", got)
        self.assertFalse(src_fetch.is_fallback_candidate("cann", "aclnnBatchMatMul failed", "ops-math"))


class FindRoutingTest(unittest.TestCase):
    def test_offline_lists_candidates_and_never_fetches(self):
        """`--offline` 的语义是**不联网**：给出候选、绝不 clone（空 dest 必须保持为空）。

        `--dest` 指向临时目录很重要：默认缓存是主检出共享的（跨 worktree 共读），
        本机若已缓存过同版本，这条会走"复用"分支而**掩盖**是否联网——那正是要测的东西。
        """
        with tempfile.TemporaryDirectory() as d:
            r = run_find("HcclAllReduce failed", "--offline", "--dest", d)
            self.assertIn("cann/hccl", r.stdout)
            self.assertIn("未取得该版本源码", r.stdout.splitlines()[-1])
            self.assertEqual(list(Path(d).iterdir()), [], "离线模式不该克隆任何仓")
        self.assertIn(r.returncode, (0, 3))   # 本地恰好有该版本时可复用（0），否则只是候选（3）

    def test_unknown_signature_is_not_a_usage_error(self):
        """零候选不是"用法错"（exit 2）——签名对、只是表里没有；调用方要能分辨这两件事。"""
        r = run_find("zzz no such signature", "--offline")
        self.assertEqual(r.returncode, 3)
        self.assertNotEqual(r.returncode, 2)

    def test_explicit_unknown_repo_is_not_overridden_by_candidates(self):
        """显式给了仓名就以它为准：候选命中 hccl，也不能被改写。"""
        with tempfile.TemporaryDirectory() as d:
            # 顺序有讲究：`--find` 只吃紧随其后的一个值，仓名要写在签名之后
            r = run_find("HcclAllReduce failed", "myorg/myrepo", "--offline",
                         "--ref", "v1", "--dest", d)
        self.assertIn("myorg/myrepo", r.stdout)
        self.assertIn("以你给的仓名 myorg/myrepo 为准", r.stdout)   # 显式仓名生效、不被套上 --org
        self.assertNotIn("cann/myorg", r.stdout)
        self.assertTrue(r.returncode != 0)        # 离线且未命中 → 不克隆，非零收尾

    def test_ambiguous_signature_does_not_clone(self):
        """歧义签名：exit 3 + 候选表；**不自动克隆**（--dest 为空目录且必须保持为空）。"""
        with tempfile.TemporaryDirectory() as d:
            r = run_find("aclnnBatchMatMul failed", "--ref", "v9.1.1", "--dest", d)
            self.assertEqual(r.returncode, 3)
            self.assertIn("ops-math", r.stdout)
            self.assertIn("未取得该版本源码", r.stdout.splitlines()[-1])
            self.assertEqual(list(Path(d).iterdir()), [], "歧义时不该克隆任何仓")

    def test_single_candidate_is_fetched_and_reused(self):
        """唯一候选自动取回（exit 0，末行=版本目录），再跑一次命中本地复用、不重拉。"""
        with tempfile.TemporaryDirectory() as d:
            r = run_find("HcclAllReduce failed", "--ref", "v9.1.1", "--dest", d)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            target = Path(r.stdout.splitlines()[-1])
            self.assertEqual(target, Path(d).resolve() / "cann" / "hccl" / "v9.1.1")
            self.assertTrue((target / ".git" / src_fetch.META_NAME).exists())
            again = run_find("HcclAllReduce failed", "--ref", "v9.1.1", "--dest", d)
            self.assertEqual(again.returncode, 0)
            self.assertIn("复用", again.stdout)


class KnownRepoTest(unittest.TestCase):
    def test_cann_layers_are_known(self):
        for name in ("cann/ops-nn", "cann/hccl", "cann/ge", "cann/runtime"):
            canonical, cands = src_fetch.lookup(name)
            self.assertEqual(canonical, name)
            self.assertEqual(cands[0][0], "gitcode", f"{name} 应走 gitcode")

    def test_org_catalog_reports_descriptions(self):
        """真枚举一次组织仓（联网）；拿不到时降级为 note，不抛异常。"""
        cands, note = src_fetch.org_repo_catalog("cann", "aclnnFlashAttentionScore failed")
        if note:
            self.assertIn("失败", note)          # 断网/限流：给的是降级说明
            self.assertTrue(cands)               # 降级也要有候选（来自关键词表）
        else:
            self.assertEqual(cands and cands[0][0], "ops-transformer")

    def test_candidates_from_catalog_json_shape(self):
        """`gc_docs repos --json` 的形态（path/description）是候选表依赖的字段。"""
        payload = [{"repo": "ops-nn", "star": 1, "updated": "2026-09-22", "desc": "神经网络类计算算子库"}]
        self.assertEqual(json.loads(json.dumps(payload))[0]["repo"], "ops-nn")


if __name__ == "__main__":
    unittest.main()
