"""只追加 JSONL 记录：顺序、缺失文件、坏行、追加锁。"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.records import (  # noqa: E402
    ConclusionStore,
    JsonlStore,
    RecordError,
    RunStore,
    conclusion_path,
    run_path,
)


class JsonlStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "records.jsonl"
        self.store = JsonlStore(self.path)

    def test_append_and_read_in_order(self):
        self.store.append({"decision": "accept", "b": 4})
        self.store.append({"decision": "reject", "reason": "回归"})
        records = self.store.read()
        self.assertEqual([record["decision"] for record in records], ["accept", "reject"])
        self.assertEqual(records[1]["reason"], "回归")

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(self.store.read(), [])
        self.assertEqual(self.store.last(), [])

    def test_last(self):
        for index in range(5):
            self.store.append({"i": index})
        self.assertEqual([record["i"] for record in self.store.last(2)], [3, 4])
        self.assertEqual(self.store.last(0), [])

    def test_append_rejects_non_object(self):
        with self.assertRaises(TypeError):
            self.store.append(["not", "an", "object"])  # type: ignore[arg-type]

    def test_invalid_json_raises(self):
        self.path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
        with self.assertRaises(RecordError) as ctx:
            self.store.read()
        self.assertIn("line 2", str(ctx.exception))

    @unittest.skipUnless(os.name == "posix", "并发追加锁由 fcntl 保证，只在 POSIX 验证")
    def test_concurrent_appends_keep_every_line(self):
        def worker(worker_id):
            for index in range(10):
                self.store.append({"worker": worker_id, "i": index})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        records = self.store.read()
        self.assertEqual(len(records), 80)
        self.assertEqual({record["worker"] for record in records}, set(range(8)))

    def test_conclusion_and_run_paths(self):
        self.assertEqual(
            conclusion_path(self.root),
            self.root / ".s2-replay" / "evolve" / "conclusions.jsonl",
        )
        self.assertEqual(
            run_path(self.root),
            self.root / ".s2-replay" / "evolve" / "runs.jsonl",
        )
        ConclusionStore.for_root(self.root).append({"decision": "accept"})
        RunStore.for_root(self.root).append({"sample": "S-1"})
        self.assertEqual(len(ConclusionStore.for_root(self.root).read()), 1)
        self.assertEqual(len(RunStore.for_root(self.root).read()), 1)


if __name__ == "__main__":
    unittest.main()
