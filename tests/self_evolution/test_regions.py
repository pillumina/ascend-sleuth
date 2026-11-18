"""归因组件到可变异区的自动推荐。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.regions import recommend  # noqa: E402


class RegionsTest(unittest.TestCase):
    def test_hard_components_rank_regions(self):
        result = recommend({
            "routing": {"events": 3, "hard": 2},
            "case_content": {"events": 1, "hard": 1},
        })
        self.assertEqual(result[0]["region"], "diagnose.routing_hints")
        self.assertEqual(result[0]["hard"], 2)

    def test_knowledge_usage_component_maps_to_usage_region(self):
        result = recommend({"case_retrieval": {"events": 2, "hard": 1}})
        self.assertEqual(result[0]["region"], "diagnose.knowledge_usage")

    def test_source_usage_component_maps_to_source_region(self):
        result = recommend({"source_usage": {"events": 2, "hard": 1}})
        self.assertEqual(result[0]["region"], "diagnose.source_usage")

    def test_unknown_components_return_empty(self):
        self.assertEqual(recommend({"unknown": {"events": 1, "hard": 1}}), [])


if __name__ == "__main__":
    unittest.main()
