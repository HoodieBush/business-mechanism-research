import copy
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from research_runtime import ResearchRuntime
from temporal_lab import TemporalLab,digest


class TerminalReceiptTests(unittest.TestCase):
    def runtime(self,policy="settle_committed",profile="interruptions",deadline=120):return ResearchRuntime(TemporalLab(ChoiceWorld(4001,"threeway"),profile,deadline),terminal_policy=policy)
    def setup_check(self,rt):
        cid=rt.initial_candidate
        rt.call("sample",{"candidate_id":cid,"designs":[{"stage":"source","site":"00","assortment":[],"n":400}],"rationale":"随机起点。"})
        rt.call("collect",{"until":"all","repair":True,"refit":False,"assess":False})
        rt.call("confirm",{"candidate_id":cid,"design":{"stage":"source","site":"00","assortment":[]},"rationale":"独立新检查。"})
        return cid
    def finish(self,rt,cid):return rt.call("finish",{"candidate_id":cid,"claims":"仅原登记条件，未测范围未决。","unresolved":True,"stop_reason":"决策额度结束。"})

    def test_model_plans_and_revision_frozen_before_retries_and_received_results(self):
        rt=self.runtime();cid=self.setup_check(rt);registry=copy.deepcopy(rt.registry);plans=copy.deepcopy(rt.objects["plans"])
        self.assertEqual(len(rt.checks),1);self.assertIsNone(rt.checks[0]["result"])
        with patch.object(rt,"_fit",side_effect=AssertionError("no terminal fit")):result=self.finish(rt,cid)
        self.assertTrue(result["ok"]);self.assertEqual(rt.registry,registry);self.assertEqual(rt.objects["plans"],plans)
        self.assertEqual(rt.revisions,0);self.assertEqual(rt.checks[0]["result"]["n"],1600)
        self.assertEqual(rt.terminal_commitment["model_sha256"],digest(registry[cid]["model"]))
        self.assertEqual(rt.calls,5);self.assertEqual(rt.gateway.used["sessions"],2000)
        closed=next(e for e in rt.events if e["kind"]=="research_decisions_closed")
        self.assertLess(closed["available_at"],rt.checks[0]["result"]["available_at"])
        with self.assertRaises(ValueError):rt.call("fit_pool",{})

    def test_received_only_leaves_pending_and_invalid_resolution_is_atomic(self):
        rt=self.runtime("received_only");cid=self.setup_check(rt);versions=copy.deepcopy(rt.versions)
        invalid=rt.call("finish",{"candidate_id":cid,"claims":"已解决。","unresolved":False,"stop_reason":"停止。"})
        self.assertFalse(invalid["ok"]);self.assertFalse(rt.decisions_closed);self.assertEqual(rt.versions,versions)
        done=self.finish(rt,cid);self.assertTrue(done["ok"]);self.assertTrue(rt.decisions_closed)
        self.assertIsNone(rt.checks[0]["result"]);self.assertEqual(done["result"]["mechanism_card"]["state"],"pending_confirmation")

    def test_deadline_and_gateway_reserve_never_read_late_results_or_mask_missing(self):
        rt=self.runtime(deadline=7);cid=self.setup_check(rt);self.assertTrue(self.finish(rt,cid)["ok"])
        self.assertLessEqual(rt.gateway.clock,7)
        self.assertEqual(rt.terminal_settlement["reason"],"calendar_deadline")
        self.assertTrue(rt.terminal_settlement["unresolved_job_ids"])
        other=self.runtime();cid=self.setup_check(other);other.gateway.limits["tool_calls"]=other.gateway.tool_calls+2
        done=self.finish(other,cid);self.assertTrue(done["ok"])
        self.assertEqual(other.terminal_settlement["reason"],"gateway_reserve_for_finish_and_deployment")
        self.assertIsNone(other.checks[0]["result"])
        other.gateway.call("deployment_catalog",{})
        self.assertEqual(other.gateway.tool_calls,other.gateway.limits["tool_calls"])

    def test_no_cost_for_meter_audit_leaves_unverified_no_certification(self):
        rt=self.runtime();cid=rt.initial_candidate
        rt.call("sample_frontier",{"candidate_id":cid,"count":3,"rationale":"前缀。"});rt.call("collect",{"until":"all","repair":True,"refit":False,"assess":False})
        rt.call("confirm",{"candidate_id":cid,"design":{"stage":"source","site":"00","assortment":[]},"rationale":"新检查。"})
        rt.gateway.limits["cost"]=rt.gateway.used["cost"]
        result=self.finish(rt,cid);self.assertTrue(result["ok"])
        self.assertEqual(rt.terminal_settlement["reason"],"unresolved_execution_or_resource_allocation")
        self.assertIsNone(rt.checks[0]["result"]);self.assertEqual(result["result"]["mechanism_card"]["state"],"pending_confirmation")
