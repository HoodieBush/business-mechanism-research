"""Provider reasoning compatibility; zero external calls."""
import unittest
from business_mechanism.transport import normalize_provider_response


class ReasoningCompatibility(unittest.TestCase):
    def test_vllm_alias_preserves_original_response(self):
        raw = {'choices': [{'message': {'role': 'assistant', 'reasoning': 'original thought',
                                      'tool_calls': [{'id': '1', 'function': {'name': 'read_context'}}]}}],
               'usage': {'total_tokens': 17}}
        result, changes = normalize_provider_response(raw)
        self.assertEqual(result['choices'][0]['message']['reasoning_content'], 'original thought')
        self.assertEqual(result['choices'][0]['message']['reasoning'], 'original thought')
        self.assertNotIn('reasoning_content', raw['choices'][0]['message'])
        self.assertEqual(result['usage'], raw['usage'])
        self.assertEqual(result['choices'][0]['message']['tool_calls'], raw['choices'][0]['message']['tool_calls'])
        self.assertEqual(changes, [{'choice': 0, 'from': 'reasoning', 'to': 'reasoning_content'}])

    def test_native_field_takes_precedence(self):
        raw = {'choices': [{'message': {'reasoning': 'provider alias', 'reasoning_content': 'native value'}}]}
        result, changes = normalize_provider_response(raw)
        self.assertEqual(result, raw)
        self.assertEqual(changes, [])

    def test_ordinary_response_does_not_invent_reasoning(self):
        raw = {'choices': [{'message': {'role': 'assistant', 'content': 'ready'}}]}
        result, changes = normalize_provider_response(raw)
        self.assertEqual(result, raw)
        self.assertEqual(changes, [])

    def test_malformed_choice_is_retained_for_runtime_error_handling(self):
        for raw in ({'choices': None}, {'choices': [None]}, {'error': 'gateway error'}):
            result, changes = normalize_provider_response(raw)
            self.assertEqual(result, raw)
            self.assertEqual(changes, [])


if __name__ == '__main__':
    unittest.main()
