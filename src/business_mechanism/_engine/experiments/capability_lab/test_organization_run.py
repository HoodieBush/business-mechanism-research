import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_organization import audit
from audit_scientific import audit as scientific_audit
import run_organization
from test_native_science_protocol import raw


class OrganizationRunTests(unittest.TestCase):
    def test_shared_API_budget_and_separate_persistent_context_notebooks(self):
        spec=json.loads((run_organization.ROOT.parents[1]/"configs/development_organization_v01.json").read_text())
        spec["phase"]="unit_only";spec["api_limits"]["calls"]=2
        responses=[raw("dispatch_research_context",{"kind":"select","target_id":"generator","objective":"提出竞争解释。","analysis_ids":[],"rationale":"分配研究。","expected_gap":"解释缺口。"}),
            raw("append_research_note",{"kind":"premise_review","text":"实物功能尚无购买效应证据。","analysis_ids":[],"candidate_id":"C0000","rationale":"保留前提缺口。","expected_gap":"需要新测量。"})]
        def request(_,payload):return {"request":copy.deepcopy(payload),"cache_hit":False,"response":responses.pop(0)}
        score={"profiles":[],"heldout_effect_rmse":0.,"mean_expected_operating_regret_per_customer":0.}
        with tempfile.TemporaryDirectory(dir=run_organization.ROOT) as directory:
            root=Path(directory);(root/"results"/spec["phase"]).mkdir(parents=True)
            with patch.object(run_organization,"ROOT",root),patch.object(run_organization,"evaluate",return_value=score),patch("research_actor.request_model",side_effect=request) as model,contextlib.redirect_stdout(io.StringIO()):
                result=run_organization.run(dict(seed=4501,family="threeway",profile="interruptions",strategy="B"),spec)
        self.assertEqual(result["status"],"actor_budget_stopped")
        self.assertEqual(model.call_count,2);self.assertEqual(result["model_usage"]["api_calls"],2)
        self.assertEqual([r["organization_context_id"] for r in result["model_calls"]],["supervisor","generator"])
        self.assertEqual(set(result["reading_notebooks"]),{"supervisor","generator"})
        self.assertEqual(result["used"]["sessions"],0)
        self.assertTrue(scientific_audit(result)["passed"],scientific_audit(result))
        self.assertTrue(audit(result)["passed"],audit(result))
        self.assertFalse(audit(result)["organization_behavior_exercised"])
        mutant=copy.deepcopy(result);mutant["research"]["research_organization"]["contexts"][1]["parent_id"]="fake"
        self.assertFalse(audit(mutant)["passed"])
