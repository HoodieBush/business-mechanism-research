import copy
import math
import unittest

from decision_sensitivity import review
from lab import predict
from operating_policy import optimize,order_quantity,profit_at_probability
from public_inference_replay import PublicInferenceView


class DecisionSensitivityTests(unittest.TestCase):
    def contract(self):return {"customers_per_day":80,"stock_capacity":60,"retail_price":10.,"purchase_cost":3.,"salvage_value":.5,"auxiliary_slot_profiles":[1]}
    def snapshot(self,complete=False,cost=.02,linear=False):
        catalog=[{"id":"u","description":"spoon","retailer_cost_per_session":cost}]
        model={"role_patterns":{"heating":["heater"],"utensils":["spoon"]},"expression":.2 if linear else f"sigmoid({math.log(.2/.8)})"}
        rows=[{"experiment_id":0,"job_id":4,"stage":"source","site":"00","assortment":[],"n":400,"observed_sales":80,
            "evidence_version":1,"available_at":3,"verified_supply":True,"verified_meter":True}]
        if complete:rows.append(rows[0]|{"experiment_id":1,"job_id":5,"assortment":["u"]})
        return {"view":PublicInferenceView({"source":catalog},rows),"training_ids":[row["experiment_id"] for row in rows],"boundary_available_at":3,"selected_original_model":model}

    def test_unseen_direction_preserves_training_likelihood_and_changes_profitable_decision(self):
        snapshot=self.snapshot();result=review(snapshot,self.contract())
        self.assertGreater(result["max_nominal_policy_regret_over_reviewed_scenarios"],1)
        self.assertTrue(result["scenarios"]);self.assertFalse(result["contract"]["posterior_or_confidence_set"])
        for scenario in result["scenarios"]:
            stressed=snapshot["selected_original_model"]|{"expression":scenario["expression"]}
            self.assertAlmostEqual(predict(stressed,snapshot["view"].catalogs["source"],[],(0,0)),.2,places=12)
            for profile in scenario["profiles"]:
                choice=profile["scenario_policy"]
                self.assertLessEqual(len(choice["assortment"]),1)
                self.assertTrue(0<=choice["order_quantity"]<=60)
        self.assertEqual(result["suggested_discriminating_designs"][0]["design"]["assortment"],["u"])

    def test_expensive_material_makes_prediction_stress_decision_irrelevant(self):
        result=review(self.snapshot(cost=1000.),self.contract())
        self.assertTrue(result["training_constant_decision_active_directions"])
        self.assertTrue(result["scenarios"])
        self.assertEqual(result["max_nominal_policy_regret_over_reviewed_scenarios"],0.)
        self.assertEqual(result["suggested_discriminating_designs"],[])

    def test_covering_the_missing_condition_removes_this_unidentified_direction(self):
        result=review(self.snapshot(complete=True),self.contract())
        self.assertEqual(result["training_constant_decision_active_directions"],[])
        self.assertEqual(result["scenarios"],[])
        self.assertIn("does not certify",result["limits"])

    def test_linear_and_logit_stress_preserve_original_input_and_ignore_private_fields(self):
        for linear in (False,True):
            snapshot=self.snapshot(linear=linear);before=copy.deepcopy(snapshot["selected_original_model"])
            reference=review(snapshot,self.contract());snapshot["private_score"]={"secret":"DO_NOT_USE"};snapshot["future_evidence"]=[{"observed_sales":9999}]
            self.assertEqual(reference,review(snapshot,self.contract()))
            self.assertEqual(snapshot["selected_original_model"],before)
            self.assertTrue(all(s["max_training_prediction_difference"]<=1e-12 for s in reference["scenarios"]))

    def test_future_unverified_and_out_of_scope_training_is_rejected(self):
        for key,value in (("verified_meter",False),("available_at",4),("stage","heldout")):
            snapshot=self.snapshot();snapshot["view"].data[0][0][key]=value
            with self.assertRaises(ValueError):review(snapshot,self.contract())
        snapshot=self.snapshot();snapshot["training_ids"]=[999]
        with self.assertRaises(ValueError):review(snapshot,self.contract())

    def test_shared_newsvendor_matches_brute_force_integer_profit_maximum(self):
        import operating_eval
        self.assertIs(operating_eval.optimize,optimize)
        contract=self.contract()|{"customers_per_day":12,"stock_capacity":10}
        for p in (0.,.05,.3,.5,.95,1.):
            q=order_quantity(p,contract)
            brute=max(profit_at_probability(p,k,.02,contract) for k in range(11))
            self.assertAlmostEqual(profit_at_probability(p,q,.02,contract),brute,places=10)

    def correlated(self,inverse=False):
        snapshot=self.snapshot()
        snapshot["view"].catalogs["source"].append({"id":"h","description":"heater","retailer_cost_per_session":.06})
        rows=[copy.deepcopy(snapshot["view"].data[0][0]),copy.deepcopy(snapshot["view"].data[0][0])]
        rows[0]["assortment"]=["h"] if inverse else []
        rows[1].update(experiment_id=1,job_id=5,assortment=["u"] if inverse else ["h","u"])
        snapshot["view"]=PublicInferenceView(snapshot["view"].catalogs,rows);snapshot["training_ids"]=[0,1]
        return snapshot

    def test_cooccurring_functions_have_alias_risk_even_without_constant_atom_directions(self):
        snapshot=self.correlated();result=review(snapshot,self.contract()|{"auxiliary_slot_profiles":[1,2]})
        self.assertEqual(result["training_constant_decision_active_directions"],[])
        self.assertTrue(result["affine_alias_decision_active_directions"])
        self.assertGreater(result["max_nominal_policy_regret_over_reviewed_scenarios"],1)
        self.assertTrue(all(s["max_training_prediction_difference"]<=1e-12 for s in result["scenarios"]))
        self.assertEqual(len(result["suggested_discriminating_designs"][0]["design"]["assortment"]),1)

    def test_inverse_affine_aliases_are_not_mistaken_for_identification(self):
        result=review(self.correlated(inverse=True),self.contract()|{"auxiliary_slot_profiles":[1,2]})
        self.assertTrue(result["affine_alias_decision_active_directions"])
        self.assertTrue(all(s["max_training_prediction_difference"]<=1e-12 for s in result["scenarios"]))

    def test_geometry_review_is_invariant_to_receipt_row_order(self):
        snapshot=self.correlated();a=review(snapshot,self.contract())
        snapshot["view"].data.reverse();b=review(snapshot,self.contract())
        a.pop("training_snapshot_sha256");b.pop("training_snapshot_sha256")
        self.assertEqual(a,b)


if __name__=="__main__":unittest.main()
