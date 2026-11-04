import unittest
from model_admission import estimate


class AdmissionTests(unittest.TestCase):
    def test_observed_usage_is_distinct_from_bytes_and_can_admit_an_affordable_request(self):
        payload={"messages":[{"content":"库存"*1000}],"max_tokens":1000}
        previous={"request":payload,"response":{"usage":{"prompt_tokens":2000}}}
        legacy=estimate(payload,[])
        measured=estimate(payload,[previous],"provider_prompt_ratio")
        self.assertGreater(legacy["estimated_tokens"],measured["estimated_tokens"])
        self.assertEqual(measured["estimated_tokens"],4000)
        self.assertFalse(measured["tokenizer_verified"])

    def test_first_or_unreported_prompt_uses_fallback_and_unknown_policy_is_rejected(self):
        payload={"max_tokens":1000,"messages":[]}
        result=estimate(payload,[{"response":{"usage":{}}}],"provider_prompt_ratio")
        self.assertTrue(result["fallback_to_bytes"])
        self.assertEqual(result["estimated_tokens"],estimate(payload,[])["estimated_tokens"])
        with self.assertRaises(ValueError):estimate(payload,[],"guess")
