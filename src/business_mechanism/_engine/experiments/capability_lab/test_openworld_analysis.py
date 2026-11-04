import json
from pathlib import Path
import tempfile
import unittest

from analyze_openworld import key,read_runs,report
from confirmation import exact_check_power
from mechanism_state import card
from freeze_batch import launch


class OpenworldAnalysisTests(unittest.TestCase):
    def test_fact_modes_remain_distinct_and_missing_runs_count(self):
        tasks=[{"seed":1,"family":"null","fault":"none","strategy":"numeric_frontier","fact_mode":mode}
               for mode in ("structured","text")]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/"manifest.json").write_text(json.dumps({"planned_tasks":tasks}))
            row={"strategy":"numeric_frontier","status":"semantic_compilation_failure",
                "private_configuration":{k:tasks[0][k] for k in ("seed","family","fault","fact_mode")}}
            (path/"numeric_frontier_null_none_structured_s1.json").write_text(json.dumps(row))
            summary=report(read_runs(path))
        self.assertEqual(summary["total_in_denominator"],2)
        self.assertEqual({r["fact_mode"] for r in summary["summary"]},{"structured","text"})
        self.assertTrue(all(r["mean_endpoints_conditional_on_finished"]["heldout_effect_rmse"] is None for r in summary["summary"]))

    def test_confirmation_power_is_enumerated_not_assumed(self):
        small=exact_check_power(.5,.5,400)
        large=exact_check_power(.5,.5,1600)
        self.assertEqual(small["supported_within_tolerance"],0)
        self.assertGreater(large["supported_within_tolerance"],.8)
        for row in (small,large):
            self.assertAlmostEqual(sum(row[k] for k in ("inconclusive","contradicted","supported_within_tolerance")),1,places=10)

    def test_price_contexts_are_not_merged_into_one_task(self):
        rows=[]
        for price in (8.,10.):
            for strategy in ("numeric_full_frontier","memory_scoped_frontier"):
                rows.append({"status":"semantic_compilation_failure","strategy":strategy,
                    "private_configuration":{"seed":1,"family":"null","fault":"none","fact_mode":"structured","retail_price":price}})
        summary=report(rows)
        self.assertEqual(len({key(r) for r in rows}),4)
        self.assertEqual(len(summary["summary"]),4)
        self.assertEqual({r["retail_price"] for r in summary["paired_endpoints"]},{8.,10.})
        self.assertTrue(all(r["planned_pairs"]==1 for r in summary["paired_endpoints"]))

    def test_result_cannot_silently_change_declared_public_price(self):
        task={"seed":1,"family":"null","fault":"none","strategy":"numeric_full_frontier","fact_mode":"structured"}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/"manifest.json").write_text(json.dumps({"planned_tasks":[task],"specification":{"retail_price":10.}}))
            row={"status":"execution_failure","strategy":task["strategy"],"private_configuration":{k:task[k] for k in ("seed","family","fault","fact_mode")}|{"retail_price":8.}}
            (path/"numeric_full_frontier_null_none_structured_s1.json").write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError,"declared task"):read_runs(path)

    def test_mechanism_card_does_not_reuse_support_after_revision(self):
        first={"expression":.3,"role_patterns":{"heating":["H"],"utensils":["U"]}}
        second=first|{"expression":.4}
        versions=[{"phase":"confirmation_model_frozen","round":i,"model":model,"training_evidence_ids":list(range(i+1))}
                  for i,model in enumerate((first,second))]
        checks=[{"round":i,"state":state,"design":{"stage":"source","site":"00","assortment":[str(i)]},
                 "experiment_id":i+5,"n":1600,"frozen_prediction":.3 if i==0 else .4,"exact_probability_interval":[.36,.44]}
                for i,state in enumerate(("contradicted","supported_within_tolerance"))]
        result=card(second,{"heating":"H","utensils":"U"},versions,checks)
        self.assertEqual(result["state"],"supported_in_listed_conditions")
        self.assertEqual(len(result["conditional_claims"]),1)
        self.assertEqual(result["version_lineage"][0]["check_states"],["contradicted"])
        self.assertEqual(result["untested_scope_state"],"unresolved_extrapolation")
        checks[-1]["state"]="contradicted"
        self.assertEqual(card(second,{},versions,checks)["state"],"refuted_in_listed_conditions")
        with self.assertRaises(ValueError):card(first,{},versions,checks)

    def test_released_check_is_not_confirmation_even_if_model_is_unchanged(self):
        model={"expression":.3,"role_patterns":{"heating":["H"],"utensils":["U"]}}
        versions=[{"phase":"confirmation_model_frozen","round":i,"model":model,
            "training_evidence_ids":[0] if i==0 else [0,5]} for i in (0,1)]
        checks=[{"round":i,"state":"supported_within_tolerance","design":{"stage":"source","site":"00","assortment":[]},
            "experiment_id":i+5,"n":1600,"frozen_prediction":.3,"exact_probability_interval":[.27,.33]} for i in (0,1)]
        result=card(model,{},versions,checks)
        self.assertEqual([c["round"] for c in result["conditional_claims"]],[1])

    def test_manifest_cannot_claim_a_different_confirmation_error_rule(self):
        spec={"runner":"run_openworld","phase":"invalid_confirmation_test_not_launched",
            "strategies":["numeric_frontier"],"seeds":[1],"families":["null"],"faults":["none"],
            "confirmation":{"rounds":3,"max_checks":4}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"spec.json";path.write_text(json.dumps(spec))
            with self.assertRaisesRegex(ValueError,"statistical rule differs"):launch(path)


if __name__=="__main__":unittest.main()
