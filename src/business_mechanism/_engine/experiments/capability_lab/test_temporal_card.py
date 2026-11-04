import unittest
from confirmation import assess
from mechanism_state import temporal_card


class TemporalCardTests(unittest.TestCase):
    def check_at_count(self,k):
        model={"role_patterns":{"heating":["热"],"utensils":["具"]},"expression":.3}
        versions=[{"phase":"confirmation_model_frozen","round":0,"model":model,"training_evidence_ids":[0,1]}]
        check=assess(k,1600,.3,max_checks=6)
        check.update(round=0,experiment_id=2,experiment_ids=[2,3],design={"stage":"source","site":"00","assortment":[]})
        return temporal_card(model,{},versions,[check])

    def test_incomplete_calendar_preserves_actual_refutation(self):
        result=self.check_at_count(900)
        self.assertEqual(result["state"],"refuted_in_listed_conditions")
        self.assertEqual(result["research_coverage_state"],"incomplete");self.assertTrue(result["calendar_incomplete"])
        self.assertEqual(result["completed_checks"],1);self.assertEqual(result["planned_checks"],6)

    def test_partial_support_remains_scoped_with_other_conditions_unresolved(self):
        result=self.check_at_count(480)
        self.assertEqual(result["state"],"supported_in_listed_conditions")
        self.assertEqual(result["research_coverage_state"],"incomplete")
        self.assertEqual(result["untested_scope_state"],"unresolved_extrapolation")


if __name__=="__main__":unittest.main()
