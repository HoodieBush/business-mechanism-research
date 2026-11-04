import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from public_fitting import fit_public_candidate
from run_temporal import Coordinator
from semantic_compile import compile_structured
from temporal_lab import TemporalLab
from temporal_plan import register_plan


class CoordinatorTests(unittest.TestCase):
    def test_invalid_selection_is_counted_without_repair_and_missing_usage_stops_calls(self):
        lab=TemporalLab(ChoiceWorld(95,"threeway"));facts=compile_structured(lab.public_catalog("source"))
        model={"role_patterns":facts["role_patterns"],"expression":.3}
        action={"stage":"source","site":"00","assortment":[],"n":400,"verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"新会话检查。"}
        lab.call("submit_experiment",{"plan":register_plan(lab,model,action,"constant")})
        result={"strategy":"llm_async_coordinator","legal_input":lab.public(),"private_configuration":{"family":"threeway"},
            "model_calls":[],"schedule_decisions":[],"research_versions":[]}
        options=[{"choice_id":"await_next","tool":"await_next","args":{},"expected_feedback":"成熟事件。"},
            {"choice_id":"launch_1","tool":"submit_experiment","action":action,"expected_feedback":"尚未启动的新计划。"}]
        fake={"cache_hit":False,"response":{"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"choice_id":"invented","rationale":"fake","expected_feedback":"fake"})}}]}}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent/"results") as tmp:
            coordinator=Coordinator(lab,result,Path(tmp)/"run.json")
            def request(_,payload):return {"request":copy.deepcopy(payload),**copy.deepcopy(fake)}
            with patch("run_temporal.request_model",side_effect=request) as mocked:
                self.assertEqual(coordinator.choose(options,[{"model":model,"rank":0,"bic":0.}],"common_warm"),options[0])
                self.assertEqual(coordinator.choose(options,[],"common_warm"),options[0]);self.assertEqual(mocked.call_count,1)
            self.assertEqual(len(result["model_calls"]),1);self.assertIn("submission_error",result["model_calls"][0])
            context=json.loads(result["model_calls"][0]["request"]["messages"][1]["content"])
            self.assertEqual(context["verified_evidence"],[]);self.assertNotIn("threeway",json.dumps(context))
            self.assertNotIn("observed_sales",json.dumps(context["pending_jobs"]))
            self.assertEqual(result["schedule_decisions"][1]["policy"],"numeric_fallback_after_api_allocation")

    def test_public_optimizer_matches_existing_optimizer_after_maturity(self):
        lab=TemporalLab(ChoiceWorld(95,"mixed_scope"));facts=compile_structured(lab.public_catalog("source"))
        model={"role_patterns":facts["role_patterns"],"expression":.3}
        ids=[p["id"] for p in lab.public_catalog("source")]
        for arm in ([],ids):
            action={"stage":"source","site":"00","assortment":arm,"n":400,"verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"核实数据上的拟合一致性。"}
            lab.call("submit_experiment",{"plan":register_plan(lab,model,action,"constant")})
        while lab.public_state()["pending_jobs"]:lab.call("await_next",{})
        args={"role_patterns":facts["role_patterns"],"expression":"b+g*heat","parameters":{"b":[.3,.05,.9],"g":[.1,-.5,.5]}}
        public=fit_public_candidate(args,lab.verified_observations(),{"source":lab.public_catalog("source")})
        legacy=lab._core._fit_candidate(args)
        self.assertEqual(public["model"],legacy["model"]);self.assertEqual(public["parameters"],legacy["parameters"])
        unsafe=args|{"expression":"__import__('os').system('x')"}
        with self.assertRaises(ValueError):fit_public_candidate(unsafe,lab.verified_observations(),{"source":lab.public_catalog("source")})


if __name__=="__main__":unittest.main()
