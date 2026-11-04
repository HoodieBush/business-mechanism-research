import copy
import unittest

from choice_world import ChoiceLab, ChoiceWorld
from public_inference_replay import PublicInferenceView
from semantic_compile import compile_structured
from audit_public_design_coverage import coverage


class PublicDesignCoverageTests(unittest.TestCase):
    def test_counts_do_not_change_geometry_and_repeated_conditions_add_no_rank(self):
        catalog = ChoiceLab(ChoiceWorld(5402)).public_catalog("source")
        patterns = compile_structured(catalog)["role_patterns"]
        rows = [{"stage": "source", "site": "00", "assortment": [], "observed_sales": 1},
                {"stage": "source", "site": "00", "assortment": [], "observed_sales": 99}]
        a = coverage({"view": PublicInferenceView({"source": catalog}, rows), "patterns": patterns})
        changed = copy.deepcopy(rows);changed[0]["observed_sales"] = 999999
        b = coverage({"view": PublicInferenceView({"source": catalog}, changed), "patterns": patterns})
        self.assertEqual(a, b)
        self.assertEqual(a["received_design_rank"], 1)
        self.assertEqual(a["unique_received_conditions"], 1)
        self.assertFalse(a["outcomes_used"])


if __name__ == "__main__":unittest.main()
