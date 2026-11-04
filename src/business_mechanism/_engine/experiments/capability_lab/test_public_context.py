import copy
import json
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from public_context import assert_roundtrip,compact_json,unpack
from research_action_schema import validate_action_args
from research_actor import ScienceActor,compact_feedback,refer_current_candidates
from research_runtime import ResearchRuntime
from run_scientific import API_LIMITS,SCHEMA,agent_view
from temporal_lab import TemporalLab
from test_research_actor import response


class PublicContextTests(unittest.TestCase):
    def test_roundtrip_preserves_rows_absence_types_and_nested_arithmetic(self):
        value={"observations":[{"job_id":1,"count":17,"verified":False,"value":None},{"job_id":2,"count":19,"verified":True,"value":1.2345678901234567}],
            "heterogeneous":[{"a":None},{"b":False}],"model":{"expression":{"op":"sigmoid","args":[{"op":"add","args":[-.3,{"op":"mul","args":[1.2345678901234567,{"var":"heat"}]}]}]}}}
        encoded=assert_roundtrip(value)
        self.assertEqual(unpack(json.loads(compact_json(encoded))),value)
        self.assertIn("_table",encoded["observations"]);self.assertIn("_ast",encoded["model"]["expression"])
        self.assertIs(type(unpack(encoded)["observations"][0]["job_id"]),int)
        with self.assertRaisesRegex(ValueError,"width"):unpack({"_table":{"columns":["n"],"rows":[[1,2]]}})

    def test_actual_gateway_failed_integer_job_is_repaired_through_typed_actor(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null"),"interruptions"))
        queued=rt.call("sample_frontier",{"candidate_id":rt.initial_candidate,"count":3,"rationale":"公共起点。"})
        self.assertTrue(queued["ok"]);jid=rt.gateway.public_state()["failed_jobs"][0]["job_id"]
        self.assertIs(type(jid),int)
        validate_action_args("repair",{"job_id":jid,"kind":"execution"})
        with self.assertRaisesRegex(ValueError,"integer"):validate_action_args("repair",{"job_id":str(jid),"kind":"execution"})
        actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS)
        action={"tool":"repair","args":{"job_id":jid,"kind":"execution"},"rationale":"同计划修复。","expected_gap":"真实执行。"}
        with patch("research_actor.request_model",side_effect=lambda _,p:{"request":copy.deepcopy(p),"cache_hit":False,"response":response([action])}):record=actor.next([])
        self.assertTrue(record["tool_feedbacks"][0]["ok"])
        context=unpack(json.loads(record["request"]["messages"][-1]["content"]))
        self.assertEqual(context["research_state"]["failed_jobs"][0]["job_id"],jid)
        self.assertEqual(rt.gateway.used["sessions"],1200)

    def test_admission_stop_is_explained_without_an_api_attempt_or_forced_science_action(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null")));limits={**API_LIMITS,"reported_tokens":1}
        actor=ScienceActor(rt,agent_view,SCHEMA,limits)
        with patch("research_actor.request_model") as request:self.assertIsNone(actor.next([]));request.assert_not_called()
        self.assertGreater(actor.last_preflight["next_request_byte_plus_output_bound"],1)
        self.assertEqual(rt.calls,0)

    def test_candidate_references_only_replace_identical_current_immutable_summaries(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null")))
        rt.call("sample_frontier",{"candidate_id":rt.initial_candidate,"count":3,"rationale":"公共采样。"})
        raw=rt.call("collect",{"until":"all","repair":True,"refit":True,"assess":False})
        state=agent_view(rt);feedback=compact_feedback(raw)
        reduced=refer_current_candidates(feedback,state)
        old=feedback["result"]["fit"]["candidates"];new=reduced["result"]["fit"]["candidates"]
        self.assertEqual(len(old),len(new));self.assertEqual(len(state["candidates"]),6)
        self.assertTrue(all(c.get("current_state_reference") for c in new))
        self.assertEqual([c["candidate_id"] for c in old],[c["candidate_id"] for c in new])
        self.assertLess(len(compact_json(reduced)),len(compact_json(feedback)))
        changed=copy.deepcopy(state);changed["candidates"][0]["bic"]+=1
        unchanged=refer_current_candidates(feedback,changed)["result"]["fit"]["candidates"][0]
        self.assertIn("model",unchanged)
