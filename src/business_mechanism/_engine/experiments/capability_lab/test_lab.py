"""Tests of scientific validity boundaries, not incidental implementation details."""
import copy
import unittest

from lab import ResearchLab, World, model_with, op, predict, private_score, var
from run_reference import certify, role_ids


def request(lab, **overrides):
    args = {"assortment": [], "site": "00", "stage": "source", "n": 400,
            "verified_supply": False, "verified_meter": False,
            "prediction": 0.3, "rationale": "事前登记"}
    args.update(overrides)
    return lab.call("experiment", args)


class ValidityTests(unittest.TestCase):
    def test_observational_equivalence_and_discriminating_actions(self):
        self.assertTrue(certify()["matched_histories"])
        histories = [ResearchLab(World(fault=f, family="null")).public()["history"]
                     for f in ("none", "supply", "report")]
        self.assertEqual(histories[0], histories[1])
        self.assertEqual(histories[1], histories[2])

    def test_unverified_receipts_do_not_expose_demand_or_truth(self):
        lab = ResearchLab(World(family="null", fault="supply"))
        result = request(lab)
        self.assertEqual(result["observed_sales"], 120)
        self.assertFalse(any(k in result for k in ["demand", "probability", "true_sales", "private_fault"]))
        self.assertEqual(lab.call("inspect_execution", {"experiment_id": 0})["physical_opening"], 120)
        verified = request(lab, verified_supply=True)
        self.assertGreater(verified["observed_sales"], result["observed_sales"])

    def test_default_meter_can_fail_after_supply_verification(self):
        lab = ResearchLab(World(family="null", fault="report"))
        r = request(lab, verified_supply=True)
        self.assertEqual(r["observed_sales"], 120)
        raw = lab.call("reconcile", {"experiment_id": 0})
        self.assertGreater(raw["verified_sales"], raw["recorded_sales"])

    def test_failed_validation_and_budget_do_not_create_data(self):
        lab = ResearchLab(World(), max_sessions=400)
        with self.assertRaises(ValueError):
            request(lab, prediction=None)
        self.assertEqual(lab.used["sessions"], 0)
        request(lab)
        before = copy.deepcopy(lab.used)
        with self.assertRaises(ValueError):
            request(lab)
        self.assertEqual(lab.used, before)
        self.assertEqual(len(lab.receipts), 1)

    def test_repeat_is_fresh_and_replay_is_not_new_evidence(self):
        lab = ResearchLab(World())
        first, second = request(lab), request(lab)
        self.assertNotEqual(first["independence_group"], second["independence_group"])
        before = lab.used["sessions"]
        lab.call("reconcile", {"experiment_id": 0})
        self.assertEqual(lab.used["sessions"], before)

    def test_frozen_prediction_and_final_survive_caller_mutation(self):
        lab = ResearchLab(World())
        result = request(lab)
        result["frozen_prediction"] = 0.99
        self.assertEqual(lab.receipts[0]["result"]["frozen_prediction"], 0.3)
        final = {"model": model_with(0.3), "claims": "未决"}
        lab.call("finish", final)
        final["model"]["expression"] = 0.99
        self.assertEqual(lab.final["model"]["expression"], 0.3)
        with self.assertRaises(ValueError):
            request(lab)

    def test_no_sampling_access_to_final_catalog_or_private_score(self):
        lab = ResearchLab(World())
        with self.assertRaises(ValueError):
            request(lab, stage="heldout")
        with self.assertRaises(ValueError):
            lab.call("private_score", {})

    def test_semantic_model_transfers_ids_but_checks_external_condition(self):
        world = World()
        expression = op("add", 0.3, op("mul", 0.25,
                          op("max", var("heat"), var("external_heat")),
                          op("max", var("utensils"), var("external_utensils"))))
        model = model_with(expression)
        h, u = role_ids({"catalog": world.catalogs["heldout"]})
        self.assertEqual(predict(model, world.catalogs["heldout"], [u], (1, 0)), 0.55)
        self.assertEqual(predict(model, world.catalogs["heldout"], [h], (1, 0)), 0.3)
        lab = ResearchLab(world)
        lab.call("finish", {"model": model, "claims": "仅用于可识别的功能覆盖关系"})
        self.assertLess(private_score(lab)["heldout_probability_rmse"], 1e-12)

    def test_model_cannot_execute_source(self):
        lab = ResearchLab(World())
        with self.assertRaises(ValueError):
            lab.call("finish", {"model": model_with({"op": "exec", "args": ["import os", 1]}),
                                "claims": "非法"})

    def test_candidate_fit_requires_verified_observation(self):
        lab = ResearchLab(World(family="null", fault="report"))
        request(lab)
        candidate = {"role_patterns": model_with(0)["role_patterns"], "expression": "b",
                     "parameters": {"b": [0.3,0.05,0.9]}}
        with self.assertRaises(ValueError):
            lab.call("fit_candidate", candidate)
        request(lab, verified_supply=True, verified_meter=True)
        fit = lab.call("fit_candidate", candidate)
        self.assertEqual(fit["verified_cohorts"],1)
        self.assertEqual(fit["unverified_cohorts_excluded"],1)
        self.assertGreater(fit["parameters"]["b"],0.4)

    def test_new_text_factors_allowed_but_unmeasured_latents_rejected(self):
        model = {"role_patterns":{"heating":["加热"],"utensils":["餐具"],"combo":["组合包"]},
                 "expression":"0.3+0.2*combo"}
        world = World()
        combo = next(p["id"] for p in world.catalogs["source"] if "组合包" in p["description"])
        self.assertAlmostEqual(predict(model,world.catalogs["source"],[combo],(0,0)),0.5)
        model["expression"]="0.3+0.2*psychological_need"
        with self.assertRaises(ValueError):
            predict(model,world.catalogs["source"],[combo],(0,0))

    def test_math_strings_do_not_open_python_execution(self):
        world=World()
        for text in ["__import__('os').system('id')","(lambda:1)()","heat.__class__","heat**200","[1][0]"]:
            with self.assertRaises((ValueError,SyntaxError)):
                predict(model_with(text),world.catalogs["source"],[],(0,0))


if __name__ == "__main__":
    unittest.main()
