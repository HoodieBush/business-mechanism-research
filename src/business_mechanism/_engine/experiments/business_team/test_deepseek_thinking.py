"""Thinking/tool/checkpoint compatibility. All responses are offline fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_from_dict, messages_to_dict
from langgraph_migration.provider import APIJournal, GatewayChatModel, gateway_message, gateway_messages
from langgraph_migration.explicit_runtime import ExplicitRoles
from langgraph_migration.context_view import size
from langgraph_migration.pacing import SharedTokenPacer
from test_gateway_protocol import JournalFixture, call, response
import test_minimal_research as fixtures
from token_budget import SharedTokenBudget, initialize_budget, reservation_bound
import model_protocol


OPTIONS = {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'max_tokens': 65536}


class ThinkingTests(unittest.TestCase):
    workspace = fixtures.MinimalResearchTests.workspace

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='thinking_contract_')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_tool_and_text_reasoning_survive_json_checkpoint_and_next_request(self):
        raw = response(call('read_context', {}, 'first'), content='checking')
        raw['reasoning_content'] = 'synthetic private reasoning 中文'
        text = response(content='done'); text['reasoning_content'] = 'synthetic final reasoning'
        journal = JournalFixture([raw, text, response(content='next')])
        journal.config['generation_options'] = copy.deepcopy(OPTIONS)
        model = GatewayChatModel(journal=journal, research_role='analyst')
        first = model.invoke('fixture task')
        history = [HumanMessage(content='fixture task'), first,
                   ToolMessage(content='fixture result', tool_call_id='first')]
        restored = messages_from_dict(json.loads(json.dumps(messages_to_dict(history))))
        second = model.invoke(restored)
        model.invoke([*restored, second, HumanMessage(content='next task')])
        self.assertEqual(journal.payloads[1]['messages'][1]['reasoning_content'], raw['reasoning_content'])
        self.assertEqual(journal.payloads[2]['messages'][3]['reasoning_content'], text['reasoning_content'])
        self.assertEqual(journal.payloads[1]['messages'][2]['tool_call_id'], 'first')
        self.assertNotIn('temperature', journal.payloads[1])
        self.assertEqual(journal.payloads[1]['max_tokens'], 65536)

    def test_invalid_arguments_preserve_reasoning_and_tool_id(self):
        raw = response(call('read_context', '{broken', 'invalid'))
        raw['reasoning_content'] = 'synthetic protocol fixture'
        message = gateway_message(raw)
        wire = gateway_messages([message])[0]
        self.assertEqual(wire['reasoning_content'], raw['reasoning_content'])
        self.assertEqual(wire['tool_calls'][0]['function']['arguments'], '{broken')
        self.assertEqual(wire['tool_calls'][0]['id'], 'invalid')

    def test_reasoning_is_counted_in_context_capacity(self):
        small = AIMessage(content='same')
        large = AIMessage(content='same', additional_kwargs={'reasoning_content': '研究'*9000})
        self.assertGreater(size([large], []), size([small], []) + 50000)

    def test_legacy_feedback_keeps_provider_reasoning_for_all_turns(self):
        for calls in [[], [call('submit', {}, 'legacy')]]:
            with self.subTest(tool=bool(calls)):
                raw = {'choices': [{'message': {**response(*calls), 'reasoning_content': 'synthetic'}}]}
                history = []
                model_protocol.append_feedback(history, raw, {'ok': False})
                self.assertEqual(history[0]['reasoning_content'], 'synthetic')
                if calls: self.assertEqual(history[1]['tool_call_id'], 'legacy')

    def test_structured_auto_selection_still_rejects_wrong_function(self):
        config = {'generation_options': OPTIONS, 'structured_output': 'function_call'}
        payload = model_protocol.structured_request({'messages': [{'role': 'system', 'content': 'task'}],
            'temperature': 0, 'presence_penalty': 0.1}, config, 'submit', {'type': 'object'})
        self.assertEqual(payload['tool_choice'], 'auto')
        self.assertNotIn('temperature', payload); self.assertNotIn('presence_penalty', payload)
        wrong = {'choices': [{'message': response(call('other', {}, 'wrong'))}]}
        with self.assertRaisesRegex(ValueError, 'unexpected submission'):
            model_protocol.decode_submission(wrong, config, 'submit')
        disabled = model_protocol.structured_request({'messages': [{'role': 'system', 'content': 'task'}],
            'temperature': 0}, {'structured_output': 'function_call'}, 'submit', {'type': 'object'})
        self.assertEqual(disabled['tool_choice']['function']['name'], 'submit')
        self.assertEqual(disabled['temperature'], 0)

    def test_journal_configured_output_and_legacy_fixture_defaults(self):
        pacer = SharedTokenPacer(self.root/'pacing', None)
        current = APIJournal(self.root, {'model': 'fixture', 'generation_options': OPTIONS}, pacer=pacer)
        legacy = APIJournal(self.root, {'model': 'fixture'}, pacer=pacer)
        self.assertEqual(current.max_output, 65536)
        self.assertEqual(legacy.max_output, 7000)

    def test_ambiguous_batch_feedback_does_not_lose_reasoning(self):
        ws = self.workspace(); roles = ExplicitRoles(ws, None, lambda role: None)
        message = gateway_message({**response(call('read_context', {}, 'dup'), call('read_context', {}, 'dup')),
                                   'reasoning_content': 'synthetic preserved reasoning'})
        messages = [message]; state = {'pending': True, 'pending_message': 0}
        with patch.object(roles, 'execute') as execute:
            self.assertEqual(roles._execute_pending('analyst', state, messages, 'fixture', self.root/'check.json', 8), 0)
            execute.assert_not_called()
        restored = messages_from_dict(json.loads((self.root/'check.json').read_text())['messages'])
        self.assertEqual(gateway_messages(restored)[0]['reasoning_content'], 'synthetic preserved reasoning')
        self.assertFalse(state['pending']); self.assertFalse(restored[0].tool_calls)

    def test_truncated_complete_looking_calls_never_execute(self):
        ws = self.workspace(); roles = ExplicitRoles(ws, None, lambda role: None)
        raw = {**response(call('read_context', {}, 'truncated')), 'reasoning_content': 'synthetic'}
        message = gateway_message(raw, finish_reason='length')
        self.assertFalse(message.tool_calls); self.assertEqual(len(message.invalid_tool_calls), 1)
        state = {'pending': True, 'pending_message': 0}; messages = [message]
        with patch.object(roles, 'execute') as execute:
            roles._execute_pending('analyst', state, messages, 'fixture', self.root/'truncated.json', 8)
            execute.assert_not_called()
        self.assertEqual(messages[-1].status, 'error')
        self.assertIn('Truncated', messages[-1].content)
        self.assertEqual(gateway_messages(messages)[0]['reasoning_content'], 'synthetic')

    def test_http_reserves_effective_output_and_counts_reasoning_once(self):
        pointer = initialize_budget(self.root/'fake_budget', budget_id='thinking-fixture', limit_tokens=200000,
            model='thinking-fixture', base_url='https://fixture.invalid/v1', user_instruction='offline fixture only')
        config = {'model': 'thinking-fixture', 'base_url': 'https://fixture.invalid/v1',
                  'token_budget_pointer': str(pointer), 'generation_options': OPTIONS}
        payload = {'model': config['model'], 'messages': [{'role': 'user', 'content': 'fixture'}], 'temperature': 0}
        effective = model_protocol.generation_request(payload, config)
        raw = {'choices': [{'finish_reason': 'stop', 'message': response(content='ok')}],
               'usage': {'prompt_tokens': 9, 'completion_tokens': 6, 'total_tokens': 15,
                         'completion_tokens_details': {'reasoning_tokens': 5}}}
        reply = MagicMock(); reply.__enter__.return_value = reply; reply.read.return_value = json.dumps(raw).encode()
        reply.status = 200; reply.headers = {}
        opener = MagicMock()
        def open_fake(req, **kwargs):
            sent = json.loads(req.data)
            self.assertEqual(sent, effective)
            self.assertEqual(SharedTokenBudget(pointer).snapshot()['unknown_or_inflight_reserve'], reservation_bound(effective))
            return reply
        opener.open.side_effect = open_fake
        with patch.object(model_protocol, 'load_api_key', return_value=''), patch.object(model_protocol.urllib.request, 'build_opener', return_value=opener):
            record = model_protocol.request_model(config, payload)
        self.assertEqual(SharedTokenBudget(pointer).snapshot()['reported_tokens'], 15)
        self.assertEqual(model_protocol.usage_summary([record])['reasoning_tokens'], 5)
        self.assertEqual(payload.get('temperature'), 0)  # caller's input was not mutated


if __name__ == '__main__':
    unittest.main()
