import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_scientific import audit
from public_context import unpack
import run_organization
from test_native_science_protocol import raw


class ReferenceLoopTests(unittest.TestCase):
    def test_reference_actor_collects_fits_checks_and_finishes_on_one_original_ledger(self):
        spec=json.loads((run_organization.ROOT.parents[1]/"configs/development_reference_loop_v01.json").read_text())
        spec["phase"]="unit_reference_loop";spec["api_limits"]["calls"]=4;spec["progress_reports"]=False
        steps=[]
        def model(_,payload):
            state=unpack(json.loads(payload["messages"][-1]["content"]))["research_state"]
            if len(steps)==0:
                response=raw("sample_and_analyze",{"candidate_id":state["initial_candidate_id"],"designs":[{"stage":"source","site":"00","assortment":[],"n":400}],"repair":True,"rationale":"取得训练。","expected_gap":"核实需求。"})
            elif len(steps)==1:
                response=raw("confirm_and_analyze",{"candidate_id":state["candidates"][0]["candidate_id"],"design":{"stage":"source","site":"00","assortment":[]},"repair":True,"rationale":"独立检验。","expected_gap":"条件支持。"})
            else:
                response=raw("finish",{"candidate_id":state["checks"][0]["candidate_id"],"claims":"仅原条件结果，其余未决。","unresolved":True,"stop_reason":"回合结束。","rationale":"冻结。","expected_gap":"未测条件。"})
            steps.append(response)
            return {"request":copy.deepcopy(payload),"response":response,"cache_hit":False}
        score={"profiles":[],"heldout_effect_rmse":0.,"mean_expected_operating_regret_per_customer":0.}
        with tempfile.TemporaryDirectory(dir=run_organization.ROOT) as temporary:
            base=Path(temporary);(base/"results"/spec["phase"]).mkdir(parents=True)
            with patch.object(run_organization,"ROOT",base),patch.object(run_organization,"evaluate",return_value=score),patch("research_actor.request_model",side_effect=model),contextlib.redirect_stdout(io.StringIO()):
                result=run_organization.run({"seed":5302,"family":"threeway","profile":"interruptions","strategy":"reference_contract"},spec)
        self.assertEqual(result["status"],"finished_scoped")
        self.assertEqual(len(result["model_calls"]),3)
        self.assertEqual(result["used"]["sessions"],2000)
        check=result["research"]["checks"][0]
        self.assertIsNotNone(check["result"])
        self.assertFalse(set(check["training_evidence_ids"]) & set(check["result"]["experiment_ids"]))
        self.assertTrue(audit(result)["passed"],audit(result))
        mutant=copy.deepcopy(result)
        definition=next(value for value in mutant["model_calls"][0]["request"]["tools"] if value["function"]["name"]=="dispatch_research_context")
        definition["function"]["parameters"]["properties"]["target_id"]["enum"]=["C0000"]
        self.assertIn("native_function_contract_recompute",audit(mutant)["issues"])


if __name__=="__main__":unittest.main()
