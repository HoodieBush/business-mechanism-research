import copy
import json
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from research_actor import ScienceActor,compact_feedback,decode_actions
from research_runtime import ResearchRuntime
from run_scientific import API_LIMITS,SCHEMA,agent_view
from temporal_lab import TemporalLab


def response(actions):
    return {"choices":[{"finish_reason":"stop","message":{"content":"下一动作。","tool_calls":[{"id":f"call_{i}","type":"function","function":{"name":"submit_research_action","arguments":json.dumps(a,ensure_ascii=False)}} for i,a in enumerate(actions)]}}],"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}


class ActorTests(unittest.TestCase):
    def setUp(self):self.actions=[{"tool":"diagnose_history","args":{},"rationale":"核对历史。","expected_gap":"记录质量。"},{"tool":"open_adaptation","args":{},"rationale":"商品事实。","expected_gap":"新条件。"}]
    def test_bounded_real_calls_and_complete_object_only(self):
        config={"structured_output":"function_call","plain_json_fallback":True}
        self.assertEqual(decode_actions(response(self.actions),config),self.actions)
        with self.assertRaises(ValueError):decode_actions(response(self.actions*2),config)
        bad=response(self.actions);bad["choices"][0]["finish_reason"]="length"
        with self.assertRaises(ValueError):decode_actions(bad,config)
        raw={"choices":[{"message":{"content":"报告："+json.dumps(self.actions[0])},"finish_reason":"stop"}]}
        with self.assertRaises(ValueError):decode_actions(raw,config)
        wrong=response(self.actions);wrong["choices"][0]["message"]["tool_calls"][0]["function"]["name"]="invented"
        with self.assertRaises(ValueError):decode_actions(wrong,config)

    def test_real_feedback_acknowledges_each_call_and_prevents_restart(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"null")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS);records=[]
        def request(_,payload):return {"request":copy.deepcopy(payload),"cache_hit":False,"response":response(self.actions)}
        with patch("research_actor.request_model",side_effect=request):
            first=actor.next(records);records.append(first);second=actor.next(records)
        self.assertEqual(len(first["tool_feedbacks"]),2);self.assertTrue(all(f["ok"] for f in first["tool_feedbacks"]))
        messages=second["request"]["messages"]
        tools=[m for m in messages if m["role"]=="tool"]
        self.assertEqual([m["tool_call_id"] for m in tools],["call_0","call_1"])
        context=json.loads(messages[-1]["content"])
        self.assertEqual(context["research_state"]["executed_scientific_tools"]["diagnose_history"],1)
        self.assertNotIn("private_configuration",json.dumps(context));self.assertTrue(all(json.loads(t["content"])["ok"] for t in tools))

    def test_invalid_batch_is_not_partially_executed_and_error_reaches_next_context(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"null")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS)
        bad=copy.deepcopy(self.actions);bad[1].pop("rationale")
        def request(_,payload):return {"request":copy.deepcopy(payload),"cache_hit":False,"response":response(bad)}
        with patch("research_actor.request_model",side_effect=request):
            first=actor.next([]);second=actor.next([first])
        self.assertIn("submission_error",first);self.assertEqual(rt.calls,0);self.assertEqual(rt.gateway.used["cost"],0)
        context=json.loads(second["request"]["messages"][-1]["content"])
        self.assertIn("required fields",context["research_state"]["last_protocol_error"])
        self.assertIn("action[1]",context["research_state"]["last_protocol_error"])
        self.assertIn("missing=['rationale']",context["research_state"]["last_protocol_error"])
        self.assertTrue(all(not json.loads(m["content"])["ok"] for m in second["request"]["messages"] if m["role"]=="tool"))

    def test_memory_projection_preserves_all_ids_and_claims_without_repeated_cohorts(self):
        from test_research_runtime import public_archive
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"null")),public_archive())
        feedback=rt.call("retrieve_memory",{},"目录","结构")
        projected=compact_feedback(feedback)["result"]
        self.assertEqual([e["episode_id"] for e in projected["episodes"]],[e["episode_id"] for e in feedback["result"]["episodes"]])
        eid=projected["episodes"][0]["episode_id"]
        raw=rt.call("read_memory",{"episode_id":eid},"来源","范围")
        view=compact_feedback(raw)["result"]
        self.assertEqual(view["conditional_claims"],raw["result"]["conditional_claims"])
        self.assertEqual(view["template"],raw["result"]["template"])
        self.assertNotIn("evidence",view);self.assertNotIn("version_lineage",view)

    def test_malformed_native_envelope_is_recorded_without_history_crash(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"null")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS)
        bad=response(self.actions);bad["choices"][0]["message"]["tool_calls"][0].pop("type")
        with patch("research_actor.request_model",return_value={"request":{},"cache_hit":False,"response":bad}):record=actor.next([])
        self.assertIn("submission_error",record);self.assertEqual(rt.calls,0)

    def test_typed_args_reject_illegal_stages_and_empty_argument_additions_without_coercion(self):
        from research_action_schema import validate_action_args
        with self.assertRaisesRegex(ValueError,"unexpected"):validate_action_args("diagnose_history",{"rationale":"x"})
        design={"candidate_id":"C0000","designs":[{"stage":0,"site":"00","assortment":[],"n":400}],"rationale":"x"}
        with self.assertRaisesRegex(ValueError,"stage"):validate_action_args("sample",design)
        self.assertEqual(design["designs"][0]["stage"],0)
        design["designs"][0]["stage"]="source";validate_action_args("sample",design)
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(99,"null")))
        view=agent_view(rt);self.assertEqual(view["legal_design_values"]["stage_sites"],{"source":["00"]})
