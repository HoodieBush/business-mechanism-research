"""Native protocol regressions, including a saved paid failure; zero live API.

Scripted repair proves the engineering path, never LLM repair/scientific ability.
"""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.provider import APIJournal, GatewayChatModel, gateway_message
from langgraph_migration.runtime import FrameworkRoles
from run_information_protocol import InformationWorkspace
from run_langgraph_migration import reopen_workspace

FIXTURE = Path(__file__).resolve().parents[2] / 'experiments/studies/ENG-005/fixtures/cap002_invalid_response.json'


def call(name, arguments, identity):
    return {'id': identity, 'type': 'function', 'function': {
        'name': name, 'arguments': arguments if isinstance(arguments, str) else json.dumps(arguments)}}


def response(*calls, content=None):
    return {'role': 'assistant', 'content': content, 'tool_calls': list(calls)}


def submit(identity='done'):
    return response(call('submit_result', {'summary': 'scripted protocol fixture', 'evidence_files': [],
                    'findings': [], 'next_step': 'engineering fixture complete'}, identity))


class JournalFixture:
    def __init__(self, sequence):
        self.sequence = sequence
        self.payloads = []
        self.config = {'model': 'engineering-fixture'}
        self.max_output = 7000

    def call(self, role, payload):
        self.payloads.append(copy.deepcopy(payload))
        if not self.sequence:
            raise AssertionError('Unexpected model call; completed work must not repeat')
        raw = self.sequence.pop(0)
        if isinstance(raw, Exception):
            raise raw
        return {'request_index': len(self.payloads), 'response': {
            'choices': [{'message': raw, 'finish_reason': 'tool_calls'}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 3, 'total_tokens': 15}}}


class GatewayProtocolTests(unittest.TestCase):
    def test_actual_bad_response_roundtrip_preserves_raw_id_arguments_and_usage(self):
        saved = json.loads(FIXTURE.read_text())
        raw = saved['response']['choices'][0]['message']
        journal = JournalFixture([raw, response(content='after feedback')])
        model = GatewayChatModel(journal=journal, research_role='verifier')
        message = model.invoke('actual old protocol failure')
        self.assertEqual(len(message.invalid_tool_calls), 1)
        self.assertEqual(message.tool_calls, [])
        original = raw['tool_calls'][0]
        self.assertEqual(message.invalid_tool_calls[0]['args'], original['function']['arguments'])
        self.assertEqual(message.usage_metadata['total_tokens'], 15)
        model.invoke([HumanMessage(content='task'), message,
                      ToolMessage(content='invalid arguments', tool_call_id=original['id'], status='error')])
        wire = journal.payloads[-1]['messages']
        self.assertEqual(wire[1]['tool_calls'], [{k: original[k] for k in ('id','type','function')}])
        self.assertEqual(wire[2]['tool_call_id'], original['id'])

    def test_non_object_json_never_becomes_valid_empty_arguments(self):
        for arguments in ('[]', 'null', '42', 'false', '"text"', '[1]', '{broken'):
            with self.subTest(arguments=arguments):
                message = gateway_message(response(call('read_context', arguments, 'bad-shape')))
                self.assertEqual(message.tool_calls, [])
                self.assertEqual(message.invalid_tool_calls[0]['args'], arguments)

    def test_valid_empty_object_and_text_remain_valid(self):
        message = gateway_message(response(call('read_context', {}, 'valid')))
        self.assertEqual(message.tool_calls[0]['args'], {})
        self.assertEqual(message.invalid_tool_calls, [])
        self.assertEqual(gateway_message(response(content='plain text')).content, 'plain text')
        with self.assertRaisesRegex(ValueError, 'assistant message'):
            gateway_message({'role': 'user', 'content': 'not a completion'})

    def test_invalid_tool_output_cannot_be_accepted_as_a_clean_summary(self):
        from langgraph_migration.summary_reuse import SummaryRejected, validate_summary
        message = gateway_message(response(call('read_context', '{broken', 'invalid-summary'),
                                           content='A short summary that also attempts a broken tool call.'))
        message.response_metadata['finish_reason'] = 'stop'
        with self.assertRaisesRegex(SummaryRejected, 'summary_returned_tool_calls'):
            validate_summary(message, [HumanMessage(content='original facts '*1000)])

    def test_real_journal_persists_original_bad_response_once_without_transport_retry(self):
        saved = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            journal = APIJournal(directory, {'model': 'engineering-fixture'}, budget=None, tokens_per_minute=None)
            with patch('langgraph_migration.provider.request_model', return_value={'response': saved['response']}) as request:
                message = GatewayChatModel(journal=journal, research_role='verifier').invoke('journal regression')
            self.assertEqual(request.call_count, 1)
            self.assertEqual(len(message.invalid_tool_calls), 1)
            records = [json.loads(x) for x in (Path(directory)/'model_calls.jsonl').read_text().splitlines()]
            self.assertEqual(records[0]['response'], saved['response'])
            self.assertEqual(records[0]['transport_retry_number'], 0)
            self.assertFalse((Path(directory)/'retry_events.jsonl').exists())
            self.assertEqual(journal.usage()['total_tokens'], saved['response']['usage']['total_tokens'])


class NativeInvalidCallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_gateway_')
        self.root = Path(self.temp.name)
        self.ws = InformationWorkspace(self.root/'U001', {'domain': 'orders', 'construction': 'count'})
        (self.ws.root/'role_prompts.json').write_text(json.dumps(self.ws.role_prompts))
        self.connection = sqlite3.connect(self.root/'checkpoints.sqlite', check_same_thread=False)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def roles(self, journal):
        return FrameworkRoles(self.ws, SqliteSaver(self.connection),
                              lambda role: GatewayChatModel(journal=journal, research_role=role))

    def actions(self):
        path = self.ws.root/'framework_tools.jsonl'
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def assert_error_feedback(self, journal, index, bad):
        wire = journal.payloads[index]['messages']
        assistants = [m for m in wire if m['role']=='assistant' and
                      any(c['id']==bad['id'] for c in m.get('tool_calls', []))]
        self.assertEqual(len(assistants), 1)
        original = next(c for c in assistants[0]['tool_calls'] if c['id']==bad['id'])
        # SDK omits response-only stream index; IDs/name/argument bytes persist.
        self.assertEqual(original, {k: bad[k] for k in ('id','type','function')})
        errors = [m for m in wire if m['role']=='tool' and m.get('tool_call_id')==bad['id']]
        self.assertEqual(len(errors), 1)
        self.assertIn('could not be executed', errors[0]['content'])
        # Every wire error/result has a preceding originating assistant call.
        seen = set()
        for m in wire:
            if m['role']=='assistant':
                seen.update(c['id'] for c in m.get('tool_calls', []))
            elif m['role']=='tool':
                self.assertIn(m['tool_call_id'], seen)

    def test_actual_invalid_only_feedback_then_scripted_delivery(self):
        raw = json.loads(FIXTURE.read_text())['response']['choices'][0]['message']
        journal = JournalFixture([raw, submit()])
        result = self.roles(journal).run('verifier', {'question': 'known invalid wire engineering replay'})
        self.assertEqual(result['role'], 'verifier')
        self.assert_error_feedback(journal, 1, raw['tool_calls'][0])
        self.assertEqual([a['tool'] for a in self.actions()], ['submit_result'])
        self.assertEqual(len(self.ws.state['results']), 1)

    def test_mixed_batch_executes_only_valid_registered_call(self):
        bad = call('run_python', '{"code":"unterminated', 'bad-python')
        journal = JournalFixture([response(call('read_context', {}, 'read'), bad), submit()])
        self.roles(journal).run('verifier', {'question': 'mixed protocol fixture'})
        self.assert_error_feedback(journal, 1, bad)
        self.assertEqual([a['tool'] for a in self.actions()], ['read_context', 'submit_result'])

    def test_terminal_with_invalid_sibling_is_rejected_before_successful_solo_retry(self):
        bad = call('read_context', 'null', 'invalid-sibling')
        first = submit('premature');first['tool_calls'].append(bad)
        journal = JournalFixture([first, submit('valid-solo')])
        self.roles(journal).run('verifier', {'question': 'terminal batching fixture'})
        self.assert_error_feedback(journal, 1, bad)
        actions = self.actions()
        self.assertEqual([a['feedback']['ok'] for a in actions], [False, True])
        self.assertIn('alone', actions[0]['feedback']['error'])
        self.assertEqual(len(self.ws.state['results']), 1)

    def test_checkpoint_recovery_preserves_invalid_feedback_without_replaying_success(self):
        bad = call('read_context', '[]', 'bad-after-success')
        task = {'question': 'persistent invalid-call engineering fixture'}
        journal = JournalFixture([response(call('read_context', {}, 'read-once')),
                                  response(bad), RuntimeError('scripted interruption before correction')])
        with self.assertRaisesRegex(RuntimeError, 'scripted interruption'):
            self.roles(journal).run('verifier', task)
        self.assert_error_feedback(journal, 2, bad)
        self.connection.close()
        self.connection = sqlite3.connect(self.root/'checkpoints.sqlite', check_same_thread=False)
        self.ws = reopen_workspace(self.ws.root)
        resumed = JournalFixture([submit('after-restart')])
        self.roles(resumed).run('verifier', task)
        self.assert_error_feedback(resumed, 0, bad)
        self.assertEqual([a['tool'] for a in self.actions()], ['read_context', 'submit_result'])
        # Completed role reopening requires no further model/tool work.
        self.roles(JournalFixture([])).run('verifier', task)
        self.assertEqual(len(self.actions()), 2)


if __name__ == '__main__':
    unittest.main()
