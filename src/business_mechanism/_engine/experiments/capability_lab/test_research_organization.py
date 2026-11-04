import copy
import unittest

from choice_world import ChoiceWorld
from native_science_protocol import decode_native
from research_organization import ResearchOrganization
from research_runtime import ResearchRuntime
from run_scientific import agent_view
from scientific_readiness import validate_request_bindings
from temporal_lab import TemporalLab


class OrganizationTests(unittest.TestCase):
    def runtime(self, mode):
        return ResearchRuntime(TemporalLab(ChoiceWorld(4501, "threeway")), organization_mode=mode)

    def dispatch(self, rt, target, kind="select", **extra):
        return rt.call("dispatch_research_context", {"kind": kind, "target_id": target, "objective": "根据公开负证据选择下一步。", "analysis_ids": [], **extra})

    def test_B_persistent_review_context_keeps_one_physical_ledger(self):
        rt=self.runtime("B"); limits=copy.deepcopy(rt.gateway.limits); used=copy.deepcopy(rt.gateway.used)
        self.assertTrue(self.dispatch(rt,"generator")["ok"])
        self.assertEqual(rt.organization.current,"generator")
        rt.call("append_research_note", {"kind":"premise_review","text":"商品功能不自动证明购买效应，需要竞争解释。","analysis_ids":[],"candidate_id":rt.initial_candidate})
        self.assertTrue(self.dispatch(rt,"reviewer")["ok"])
        self.assertEqual(rt.calls,3);self.assertEqual(rt.gateway.used,used);self.assertEqual(rt.gateway.limits,limits)
        self.assertEqual(rt.organization.notes[0]["context_id"],"generator")
        self.assertEqual(rt.organization.notes[0]["epistemic_role"],"model_appraisal_not_scientific_evidence")
        self.assertEqual(ResearchOrganization.from_events("B",rt.events).snapshot(rt.gateway.public_state()),rt.organization.snapshot(rt.gateway.public_state()))

    def test_C_parent_waiting_child_can_process_public_work_without_fork(self):
        rt=self.runtime("C")
        rt.call("confirm",{"candidate_id":rt.initial_candidate,"design":{"stage":"source","site":"00","assortment":[]},"rationale":"原预算的独立检查。"})
        before=copy.deepcopy(rt.gateway.used);checks=len(rt.checks)
        response=self.dispatch(rt,"T0000","expand",branch_kind="redesign",candidate_id=rt.initial_candidate)
        self.assertTrue(response["ok"]);self.assertEqual(rt.organization.current,"T0001")
        self.assertEqual(rt.gateway.used,before);self.assertEqual(len(rt.checks),checks);self.assertEqual(rt.revisions,0)
        self.assertEqual(rt.organization.contexts["T0001"]["parent_id"],"T0000")
        self.assertEqual(rt.organization.plan_owners[0],"T0000")
        self.assertTrue(rt.call("diagnose_history",{})["ok"])
        self.assertIsNone(rt.checks[0]["result"])
        self.assertTrue(rt.call("collect",{"until":"all","repair":True,"refit":False,"assess":True})["ok"])
        self.assertEqual(rt.organization.contexts["T0000"]["feedback_refs"][-1]["kind"],"independent_check_assessed")
        self.assertFalse(rt.organization.contexts["T0001"]["check_ids"])
        self.assertEqual(rt.gateway.used["sessions"],1600)
        self.assertEqual(ResearchOrganization.from_events("C",rt.events).snapshot(rt.gateway.public_state()),rt.snapshot()["research_organization"])
        import json
        from audit_organization import audit
        serialized={"organization_mode":"C","research":json.loads(json.dumps(rt.snapshot())),
            "public_final_state":rt.gateway.public_state(),"legal_input":rt.initial,"model_calls":[],"strategy":"C"}
        self.assertTrue(audit(serialized)["passed"],audit(serialized))

    def test_A_cannot_expand_and_failed_dispatch_is_atomic(self):
        rt=self.runtime("A"); before=copy.deepcopy(rt.organization.contexts)
        self.assertFalse(self.dispatch(rt,"coordinator","expand",branch_kind="new_mechanism")["ok"])
        self.assertEqual(rt.organization.contexts,before);self.assertEqual(rt.organization.current,"coordinator")
        other=self.runtime("C");before=copy.deepcopy(other.organization.contexts)
        self.assertFalse(self.dispatch(other,"T0000","expand",branch_kind="refine",analysis_ids=["A999"])["ok"])
        self.assertEqual(other.organization.contexts,before)

    def test_native_dispatch_must_be_last_and_new_context_cannot_be_guessed(self):
        import json
        raw={"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[
            {"id":"c0","type":"function","function":{"name":"dispatch_research_context","arguments":json.dumps({"kind":"select","target_id":"supervisor","objective":"审查。","analysis_ids":[],"rationale":"选择。","expected_gap":"缺口。"})}},
            {"id":"c1","type":"function","function":{"name":"diagnose_history","arguments":json.dumps({"rationale":"诊断。","expected_gap":"缺口。"})}}]}}]}
        with self.assertRaises(ValueError):decode_native(raw,{})
        rt=self.runtime("C");state=agent_view(rt)
        self.dispatch(rt,"T0000","expand",branch_kind="refine")
        action={"tool":"dispatch_research_context","args":{"kind":"select","target_id":"T0001","objective":"选择。","analysis_ids":[]}}
        with self.assertRaises(ValueError):validate_request_bindings(action,state)

    def test_node_limit_and_terminal_close_do_not_reset_resources(self):
        rt=self.runtime("C")
        for _ in range(11):self.assertTrue(self.dispatch(rt,"T0000","expand",branch_kind="refine")["ok"])
        self.assertFalse(self.dispatch(rt,"T0000","expand",branch_kind="refine")["ok"])
        self.assertEqual(len(rt.organization.contexts),12);self.assertEqual(rt.gateway.used["sessions"],0)
        done=rt.call("finish",{"candidate_id":rt.initial_candidate,"claims":"未确认停止。","unresolved":True,"stop_reason":"预算停止。"})
        self.assertTrue(done["ok"])
        with self.assertRaises(ValueError):self.dispatch(rt,"T0000")
