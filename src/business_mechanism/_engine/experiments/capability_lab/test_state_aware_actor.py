import copy
import json
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from native_science_protocol import function_definitions
from public_context import unpack
from research_actor import ScienceActor
from research_runtime import ResearchRuntime
from run_scientific import API_LIMITS,SCHEMA,agent_view
from temporal_lab import TemporalLab
from test_native_science_protocol import raw


class StateAwareActorTests(unittest.TestCase):
    def test_only_unexecutable_services_are_masked_and_free_scientific_choices_reopen_with_data(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"mixed_scope")))
        names={t["function"]["name"] for t in function_definitions(agent_view(rt))}
        self.assertNotIn("fit_pool",names);self.assertNotIn("propose_model",names)
        self.assertIn("confirm_and_analyze",names);self.assertIn("sample_and_analyze",names);self.assertIn("finish",names)
        rt.call("sample_and_analyze",{"candidate_id":rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":[],"n":400}],"repair":True,"rationale":"新测量。"})
        names={t["function"]["name"] for t in function_definitions(agent_view(rt))}
        self.assertIn("propose_model",names);self.assertIn("confirm_and_analyze",names)

    def test_ignored_function_mask_gets_real_feedback_without_fake_execution_or_data(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"mixed_scope")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS,"native",True)
        response=raw("fit_pool",{"rationale":"无数据拟合。","expected_gap":"测试拒绝。"})
        with patch("research_actor.request_model",side_effect=lambda _,p:{"request":copy.deepcopy(p),"cache_hit":False,"response":response}):record=actor.next([])
        self.assertFalse(record["tool_feedbacks"][0]["ok"]);self.assertFalse(record["tool_feedbacks"][0]["executed"])
        self.assertEqual(rt.calls,0);self.assertEqual(rt.gateway.used["sessions"],0)
        self.assertFalse(record["public_precondition_reviews"][0]["accepted"])

    def test_successful_read_contents_and_hash_references_persist(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"mixed_scope")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS,"native",True)
        response=raw("diagnose_history",{"rationale":"核对。","expected_gap":"计数质量。"})
        with patch("research_actor.request_model",side_effect=lambda _,p:{"request":copy.deepcopy(p),"cache_hit":False,"response":response}):first=actor.next([]);second=actor.next([first])
        state=unpack(json.loads(second["request"]["messages"][-1]["content"]))["research_state"]
        self.assertEqual(len(state["reading_notebook"]["receipts"]),1)
        self.assertEqual(state["reading_notebook"]["receipts"][0]["tool"],"diagnose_history")
        self.assertEqual(actor.notebook.snapshot()["contents"]["R000"],first["tool_feedbacks"][0]["result"])

    def test_batch_checks_later_action_against_updated_state_without_future_counts(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"mixed_scope")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS,"native",True)
        response=raw("sample",{"candidate_id":rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":[],"n":400}],"rationale":"先采样。","expected_gap":"获得数据。"})
        second=raw("collect",{"until":"all","repair":True,"refit":True,"assess":False,"rationale":"收到后拟合。","expected_gap":"当前候选。"})["choices"][0]["message"]["tool_calls"][0]
        second["id"]="call_1";response["choices"][0]["message"]["tool_calls"].append(second)
        with patch("research_actor.request_model",side_effect=lambda _,p:{"request":copy.deepcopy(p),"cache_hit":False,"response":response}):record=actor.next([])
        self.assertTrue(all(f["ok"] for f in record["tool_feedbacks"]))
        before,after=[r["state"] for r in record["public_precondition_reviews"]]
        self.assertEqual(before["pending_jobs"],[]);self.assertEqual(len(after["pending_jobs"]),1)
        self.assertEqual(after["verified_condition_table"],[]);self.assertNotIn("observed_sales",after["pending_jobs"][0])
        self.assertEqual(rt.training_ids,{0})
