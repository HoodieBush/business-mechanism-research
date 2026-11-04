"""Ensure API format failures retain evidence without retaining credentials."""
import io
import json
import unittest
from unittest.mock import patch

from lab import ResearchLab, World, model_with
import run_hybrid
import model_protocol
from run_research import qualifies_review


class ModelIntegrationTests(unittest.TestCase):
    def test_truncated_proposal_preserves_raw_response_and_request(self):
        raw = {"choices": [{"finish_reason": "length", "message": {
            "content": '{"role_patterns":', "role": "assistant"}}],
            "usage": {"completion_tokens": 2400}}
        config = {"model": "test-model", "base_url": "https://example.invalid/v1",
                  "generation_options": {"thinking": {"type": "disabled"}}}
        lab = ResearchLab(World())
        lab.call("open_transfer", {})
        with patch.object(run_hybrid, "CONFIG", config), \
             patch.object(model_protocol, "load_api_key", return_value="test-private-credential"), \
             patch.object(model_protocol.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(raw).encode())
            record = run_hybrid.propose_mechanism(
                lab, model_with(0)["role_patterns"], [])
        self.assertEqual(record["response"], raw)
        self.assertEqual(record["request"]["thinking"], {"type": "disabled"})
        self.assertTrue(record["proposal_error"].startswith("response_format:"))
        self.assertNotIn("transport_error", record)
        self.assertNotIn("test-private-credential", json.dumps(record))

    def test_native_submission_rejects_multiple_calls_and_truncation(self):
        config={"structured_output":"function_call"}
        call={"id":"c1","type":"function","function":{
            "name":"submit_candidate","arguments":'{"expression":"b"}'}}
        raw={"choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[call]}}]}
        self.assertEqual(model_protocol.decode_submission(raw,config,"submit_candidate"),{"expression":"b"})
        raw["choices"][0]["message"]["tool_calls"].append(call)
        with self.assertRaisesRegex(ValueError,"exactly one"):
            model_protocol.decode_submission(raw,config,"submit_candidate")
        raw["choices"][0]["message"]["tool_calls"]=[call]
        raw["choices"][0]["finish_reason"]="length"
        with self.assertRaisesRegex(ValueError,"truncated"):
            model_protocol.decode_submission(raw,config,"submit_candidate")

    def test_non_json_envelope_is_archived_and_redacted(self):
        config={"base_url":"https://example.invalid/v1"}
        with patch.object(model_protocol,"load_api_key",return_value="test-private-credential"), \
             patch.object(model_protocol.urllib.request,"build_opener") as opener:
            opener.return_value.open.return_value=io.BytesIO(b"upstream error test-private-credential")
            record=model_protocol.request_model(config,{"model":"test-model"})
        self.assertEqual(record["error_type"],"response_envelope")
        self.assertEqual(record["response_body"],"upstream error [REDACTED]")
        self.assertNotIn("test-private-credential",json.dumps(record))

    def test_usage_counts_format_failures_but_not_reused_local_cache(self):
        raw={"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}
        records=[{"response":raw,"proposal_error":"format"},
                 {"response":raw,"cache_hit":True},{"error_type":"transport"}]
        usage=model_protocol.usage_summary(records)
        self.assertEqual(usage["api_calls"],2)
        self.assertEqual(usage["cache_hits"],1)
        self.assertEqual(usage["total_tokens"],120)
        self.assertEqual(usage["calls_without_reported_usage"],1)

    def test_native_history_keeps_call_id_and_feedback(self):
        raw={"choices":[{"message":{"content":None,"tool_calls":[{
            "id":"actual-call","type":"function","index":0,
            "function":{"name":"submit_action","arguments":'{"tool":"audit","args":{}}'}}]}}]}
        messages=[]
        model_protocol.append_feedback(messages,raw,{"status":"verified"})
        self.assertEqual(messages[1]["tool_call_id"],"actual-call")
        self.assertEqual(messages[1]["role"],"tool")
        self.assertNotIn("index",messages[0]["tool_calls"][0])

    def test_grounding_rule_must_match_per_product_facts(self):
        public={"catalog":[{"id":"heat","description":"加热的自热便携组件"},
                           {"id":"utensils","description":"进餐餐具便携组件"}]}
        proposal={"role_patterns":{"heating":["加热"],"utensils":["便携组件"]},
                  "catalog_roles":{"heat":["heating"],"utensils":["utensils"]}}
        with self.assertRaisesRegex(ValueError,"fact/rule inconsistency"):
            run_hybrid.validate_grounding(proposal,public)
        proposal["role_patterns"]["utensils"]=["餐具"]
        self.assertEqual(run_hybrid.validate_grounding(proposal,public),proposal["role_patterns"])

    def test_grounding_repair_is_bounded_and_failed_attempts_are_counted(self):
        failure={"request":{},"response":{"usage":{"total_tokens":100}},"proposal_error":"invalid"}
        with patch.object(run_hybrid,"ground_roles_once",side_effect=[
                run_hybrid.GroundingError("invalid",failure.copy()),
                run_hybrid.GroundingError("invalid",failure.copy())]) as call:
            with self.assertRaises(run_hybrid.GroundingError) as caught:
                run_hybrid.ground_roles({"catalog":[]})
        self.assertEqual(call.call_count,2)
        self.assertEqual(model_protocol.usage_summary([caught.exception.record])["total_tokens"],200)

    def test_review_uses_program_invariance_not_assortment_size(self):
        catalog=[{"id":"a","description":"水"},{"id":"b","description":"礼袋"}]
        model=model_with(.3)
        prior=[{"stage":"source","assortment":[]}]
        args={"stage":"source","assortment":["a","b"],"verified_supply":True,"verified_meter":True}
        self.assertTrue(qualifies_review(catalog,model,args,prior))
        self.assertFalse(qualifies_review(catalog,model,args,prior+[{"stage":"source","assortment":["a","b"]}]))

    def test_plain_json_fallback_does_not_extract_narrative_or_truncation(self):
        config={"structured_output":"function_call","plain_json_fallback":True}
        raw={"choices":[{"finish_reason":"stop","message":{"content":'{"tool":"audit","args":{}}'}}]}
        self.assertEqual(model_protocol.decode_submission(raw,config,"submit_action")["tool"],"audit")
        raw["choices"][0]["message"]["content"]+='\n</result>'
        with self.assertRaises(ValueError):model_protocol.decode_submission(raw,config,"submit_action")

    def test_mechanism_cannot_redefine_grounded_core_roles(self):
        proposal={"role_patterns":{"heating":["饮用"],"utensils":["餐具"]},
            "expression":"b","parameters":{"b":[.3,.1,.9]},"rationale":"test"}
        raw={"choices":[{"finish_reason":"stop","message":{"content":json.dumps(proposal)}}]}
        lab=ResearchLab(World());lab.call("open_transfer",{})
        with patch.object(run_hybrid,"request_model",return_value={"request":{},"response":raw}), \
             patch.object(run_hybrid,"CONFIG",{"model":"test-model","structured_output":"json_object"}):
            record=run_hybrid.propose_mechanism(lab,model_with(0)["role_patterns"],[])
        self.assertIn("changes grounded core role",record["proposal_error"])
        self.assertEqual(lab.candidates,[])


if __name__ == "__main__":
    unittest.main()
