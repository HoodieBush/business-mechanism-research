import copy
import unittest

from audit_revision_ablation import audit_pairs


class RevisionAblationTests(unittest.TestCase):
    def test_prefix_gate_detects_early_changes_and_allows_later_policy_effects(self):
        rows=[]
        for strategy in ("numeric_full_frontier_once","numeric_full_frontier"):
            events=[]
            for i in range(24):
                args={"stage":"source","site":"00","assortment":[],"n":400 if i<12 else 800,
                    "verified_supply":True,"verified_meter":True,"prediction":.3}
                events.append({"request":{"tool":"experiment","args":args},
                    "response":{"experiment_id":i,"observed_sales":120,"frozen_prediction":.3}})
            rows.append({"strategy":strategy,"private_configuration":{"seed":1,"family":"null","fault":"none","fact_mode":"structured"},
                "status":"finished","legal_input":{"limits":{"sessions":14400}},"events":events,"used":{"sessions":14400},
                "confirmation_protocol":{"cohorts_per_check":2,"rounds":3,"max_checks":6},"model_usage":{"api_calls":0}})
        later=copy.deepcopy(rows);later[1]["events"][20]["response"]["observed_sales"]=240
        self.assertEqual(audit_pairs(later)[0]["status"],"passed")
        earlier=copy.deepcopy(rows);earlier[1]["events"][19]["response"]["observed_sales"]=240
        self.assertIn("pre_opportunity_evidence_differs",audit_pairs(earlier)[0]["issues"])
        different_budget=copy.deepcopy(rows);different_budget[1]["used"]["sessions"]=16000
        self.assertIn("actual_sample_budgets_differ",audit_pairs(different_budget)[0]["issues"])


if __name__=="__main__":unittest.main()
