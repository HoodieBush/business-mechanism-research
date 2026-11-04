import copy
import json
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from native_science_protocol import decode_native,function_definitions
from research_actor import ScienceActor
from research_runtime import ResearchRuntime,TOOLS
from run_scientific import API_LIMITS,SCHEMA,agent_view
from temporal_lab import TemporalLab


def raw(name,args):return {"choices":[{"finish_reason":"stop","message":{"tool_calls":[{"id":"call_0","type":"function","function":{"name":name,"arguments":json.dumps(args,ensure_ascii=False)}}],"content":""}}],"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}


class NativeScienceTests(unittest.TestCase):
    def test_flat_metadata_and_primitive_arguments_have_one_rationale_without_coercion(self):
        config={"plain_json_fallback":True};r=raw("repair",{"job_id":1,"kind":"execution","rationale":"重试。","expected_gap":"真实执行。"})
        action=decode_native(r,config)[0]
        self.assertEqual(action["args"],{"job_id":1,"kind":"execution"});self.assertIs(type(action["args"]["job_id"]),int)
        self.assertEqual({f["function"]["name"] for f in function_definitions()},set(TOOLS))
        bad=raw("repair",{"job_id":"1","kind":"execution","rationale":"重试。","expected_gap":"真实执行。"})
        with self.assertRaises(ValueError):decode_native(bad,config)
        proposal=raw("propose_model",{"expression":"sigmoid(b)","parameters":{"b":[-.8,-6,6]},"rationale":"竞争模型。","expected_gap":"独立确认。"})
        a=decode_native(proposal,config)[0];self.assertEqual(a["args"]["rationale"],a["rationale"])
        truncated=copy.deepcopy(r);truncated["choices"][0]["finish_reason"]="length"
        with self.assertRaises(ValueError):decode_native(truncated,config)

    def test_actual_native_function_feedback_and_whole_json_fallback(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null")));actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS,"native")
        r=raw("diagnose_history",{"rationale":"核对。","expected_gap":"记录质量。"})
        with patch("research_actor.request_model",side_effect=lambda _,p:{"request":copy.deepcopy(p),"cache_hit":False,"response":r}):first=actor.next([]);second=actor.next([first])
        self.assertTrue(first["tool_feedbacks"][0]["ok"]);self.assertEqual(first["actions"][0]["args"],{})
        self.assertNotIn("submit_research_action",[x["function"]["name"] for x in first["request"]["tools"]])
        self.assertEqual([m["tool_call_id"] for m in second["request"]["messages"] if m["role"]=="tool"],["call_0"])
        fallback={"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"tool":"diagnose_history","arguments":{"rationale":"核对。","expected_gap":"记录质量。"}})}}]}
        self.assertEqual(decode_native(fallback,{"plain_json_fallback":True})[0]["args"],{})
        fallback["choices"][0]["message"]["content"]="报告："+fallback["choices"][0]["message"]["content"]
        with self.assertRaises(ValueError):decode_native(fallback,{"plain_json_fallback":True})
