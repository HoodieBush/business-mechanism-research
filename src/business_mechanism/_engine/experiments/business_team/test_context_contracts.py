"""Generic context contracts and captured real failures, with zero live models."""
from html import escape
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import get_buffer_string
from langgraph.checkpoint.sqlite import SqliteSaver

from langgraph_migration.provider import GatewayChatModel
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.summary_reuse import SummaryRejected, validate_summary
from run_information_protocol import InformationWorkspace
from run_langgraph_migration import reopen_workspace
from run_method_adoption import ROOT, MethodWorkspace, create_inputs
from test_langgraph_migration import ScriptedModel, submission
from workspace import sha, write_json

def finished(text):
    return AIMessage(content=text, response_metadata={'finish_reason': 'stop'})


class SummaryContractTests(unittest.TestCase):
    def test_actual_sdk_xml_and_escaped_continuations_are_not_indices(self):
        source = [HumanMessage(content='original received observation ' * 1500)]
        transcript = get_buffer_string([
            HumanMessage(content='read the received source'),
            AIMessage(content='received action', tool_calls=[{
                'id': 'opaque-source-id', 'name': 'lookup', 'args': {}, 'type': 'tool_call'}]),
            ToolMessage(content='received feedback', tool_call_id='opaque-source-id')], format='xml')
        legacy = get_buffer_string([AIMessage(content='', additional_kwargs={
            'function_call': {'name': 'lookup', 'arguments': '{}'}})], format='xml')
        variants = [transcript, escape(transcript), escape(escape(transcript)), legacy,
                    '</message> continuation', '<TOOL_CALL id="opaque">{}</TOOL_CALL>',
                    '<｜DSML｜invoke name="lookup">x</｜DSML｜invoke>']
        for text in variants:
            with self.subTest(text=text[:55]), self.assertRaisesRegex(SummaryRejected, 'tool_protocol_markup'):
                validate_summary(finished(text), source)

    def test_math_source_locations_and_plain_prose_are_not_semantically_graded(self):
        source = [HumanMessage(content='original received observation ' * 1500)]
        text = ('Unresolved, source=/received/receipt.json. E[C(q,D)] >= 0; x < y, n > 0. '
                '<math><mi>x</mi></math>; <message-passing> is a technical term. '
                'tool_call is an identifier, not an executed call. '
                'A prose claim can still be wrong; this validator does not certify it.')
        self.assertEqual(validate_summary(finished(text), source), text)

    def test_native_reject_retry_or_retain_then_sqlite_reopen_does_not_execute_fake_tools(self):
        bad = get_buffer_string([AIMessage(content='simulated action', tool_calls=[{
            'id': 'unexecuted-opaque-id', 'name': 'lookup', 'args': {}, 'type': 'tool_call'}]),
            ToolMessage(content='fabricated-context-value', tool_call_id='unexecuted-opaque-id')], format='xml')
        for layout, all_bad in [('serialized', False), ('serialized', True), ('prefix', False)]:
            with self.subTest(layout=layout, all_bad=all_bad), tempfile.TemporaryDirectory(
                    dir=Path(__file__).parent, prefix='unit_context_protocol_') as temporary:
                root = Path(temporary)
                ws = InformationWorkspace(root / 'case', {'domain': 'orders', 'construction': 'count'})
                write_json(ws.root / 'role_prompts.json', ws.role_prompts)
                original = ws._tool
                ws._tool = lambda role, name, args: {'large_received_observation': 'record ' * 12000} if name == 'read_context' else original(role, name, args)
                receipt_index = ws.workers['verifier'].directory / 'framework_receipts/index.json'
                actions = iter([('read_context', {}), ('read_artifact', {'path': str(receipt_index)}),
                                ('read_artifact', {'path': str(receipt_index)}), submission()])

                class Journal:
                    config = {'model': 'fixture', 'context_summary_layout': layout}
                    max_output = 7000

                    def __init__(self):
                        self.root, self.calls, self.context_calls = root, [], 0

                    def call(self, role, payload):
                        if role == 'context':
                            self.context_calls += 1
                            text = bad if all_bad or self.context_calls == 1 else 'Original observation is archived in its tool receipt. Original objective and unresolved status remain; no new execution is established.'
                            message, finish = {'content': text}, 'stop'
                        else:
                            name, args = next(actions)
                            message = {'content': '', 'tool_calls': [{
                                'id': 'real_fixture_' + str(len(self.calls)), 'type': 'function',
                                'function': {'name': name, 'arguments': json.dumps(args)}}]}
                            finish = 'tool_calls'
                        record = {'request_index': len(self.calls) + 1, 'role': role, 'task': None,
                                  'request': payload, 'response': {'choices': [{'message': message, 'finish_reason': finish}]}}
                        self.calls.append(record)
                        return record

                journal = Journal()
                task = {'id': 'context_contract', 'question': 'Preserve original objective and actual received evidence.'}
                checkpoint = root / 'checkpoints.sqlite'
                with sqlite3.connect(checkpoint, check_same_thread=False) as connection:
                    result = FrameworkRoles(ws, SqliteSaver(connection),
                        lambda role: GatewayChatModel(journal=journal, research_role=role)).run('verifier', task)
                self.assertEqual(result['role'], 'verifier')
                events = [json.loads(x) for x in (root / 'summary_events.jsonl').read_text().splitlines()]
                rejected = [x for x in events if x['event'] == 'rejected']
                self.assertGreaterEqual(len(rejected), 2 if all_bad else 1)
                self.assertTrue(all(x['reason'] == 'summary_returned_tool_protocol_markup' for x in rejected))
                self.assertEqual(any(x['event'] == 'accepted' for x in events), not all_bad)
                professional = [r for r in journal.calls if r['role'] == 'verifier']
                self.assertFalse(any('fabricated-context-value' in json.dumps(r['request']) for r in professional))
                if all_bad:
                    self.assertIn('large_received_observation', json.dumps(professional[-1]['request']))
                tools = [json.loads(x) for x in (ws.root / 'framework_tools.jsonl').read_text().splitlines()]
                self.assertEqual([x['tool'] for x in tools], ['read_context', 'read_artifact', 'read_artifact', 'submit_result'])
                calls_before = len(journal.calls)
                restored = reopen_workspace(ws.root)
                with sqlite3.connect(checkpoint, check_same_thread=False) as connection:
                    again = FrameworkRoles(restored, SqliteSaver(connection),
                        lambda role: GatewayChatModel(journal=journal, research_role=role)).run('verifier', task)
                self.assertEqual(result, again)
                self.assertEqual(len(journal.calls), calls_before)


class ReceivedPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_received_paths_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.unreceived = self.root / 'unreceived.txt'
        self.unreceived.write_text('outside the received workspace')

    def make(self, name):
        root = self.root / name
        create_inputs(root, 'M02', 'local_only', self.root / 'unused', self.root / 'unused')
        return root

    def assert_received_database_usable(self, ws, expected_rows):
        before = sha(ws.public / 'data_dictionary.json')
        context = ws.tool('verifier', 'read_context', {}, 'received-context')
        database = context['business_database']  # Never replace this with a constructed path.
        self.assertEqual(Path(database), (ws.public / 'business.sqlite').resolve())
        binding = context['source_binding']
        self.assertEqual(binding['database_sha256'], sha(database))
        self.assertEqual(binding['dictionary_sha256'], before)
        self.assertEqual(binding['dictionary_version'], ws.contract['version'])
        self.assertEqual(binding['dictionary_version_field'], 'version')
        self.assertEqual(binding['metadata_version_field'], 'dictionary_version')
        code = ('import sqlite3\n'
                f'database={database!r}\n'
                'with sqlite3.connect("file:"+database+"?mode=ro",uri=True) as con:\n'
                f' assert con.execute("SELECT COUNT(*) FROM {"hourly" if expected_rows==57600 else "observations"}").fetchone()[0]=={expected_rows}\n'
                f'try:\n open({str(self.unreceived)!r}).read()\n'
                'except PermissionError:\n print("unreceived file denied")\n'
                'else:\n raise AssertionError("sandbox resource boundary widened")\n'
                'print("received database opened")\n')
        actual = ws.tool('verifier', 'run_python', {'code': code, 'purpose': 'Received resource access contract',
                        'output_semantics': 'Access only, no scientific conclusion'}, 'received-database-open')
        self.assertTrue(actual['ok'], actual.get('stderr'))
        self.assertIn('unreceived file denied', actual['stdout'])
        table = 'hourly' if expected_rows == 57600 else 'observations'
        query = ws.tool('verifier', 'query_data', {'sql': f'SELECT COUNT(*) AS n FROM {table}',
                        'output_semantics': 'Same source row count'}, 'received-database-query')
        self.assertEqual(query['preview'], [{'n': expected_rows}])
        self.assertEqual(sha(ws.public / 'data_dictionary.json'), before)

    def test_relative_current_absolute_and_known_relocation_use_received_context(self):
        for kind in ('relative', 'current_absolute', 'known_relocation'):
            with self.subTest(kind=kind):
                root = self.make(kind + ' space 测试')
                dictionary = root / 'public/data_dictionary.json'
                value = json.loads(dictionary.read_text())
                origin = self.root / 'archived_origin/public'
                if kind == 'current_absolute':
                    value['database_file'] = str(root / 'public/business.sqlite')
                elif kind == 'known_relocation':
                    value['database_file'] = str(origin / 'business.sqlite')
                write_json(dictionary, value)
                ws = MethodWorkspace(root)
                if kind == 'known_relocation':
                    ws.path_aliases = {str(origin): str(ws.public)}
                self.assert_received_database_usable(ws, 160)

    def test_unknown_external_wrong_local_and_escaping_alias_fail_before_model(self):
        external = self.make('other_workspace') / 'public/business.sqlite'
        for kind in ('external', 'escaping_alias', 'different_local_database'):
            with self.subTest(kind=kind):
                root = self.make(kind)
                dictionary = root / 'public/data_dictionary.json'
                value = json.loads(dictionary.read_text())
                if kind == 'different_local_database':
                    shutil.copyfile(root / 'public/business.sqlite', root / 'public/other.sqlite')
                    value['database_file'] = 'other.sqlite'
                else:
                    value['database_file'] = str(self.root / 'unknown_origin/business.sqlite') if kind == 'escaping_alias' else str(external)
                write_json(dictionary, value)
                ws = MethodWorkspace(root)
                if kind == 'escaping_alias':
                    ws.path_aliases = {str(self.root / 'unknown_origin'): str(external.parent)}
                never = ScriptedModel(sequence=[])
                with sqlite3.connect(root / 'checkpoint.sqlite', check_same_thread=False) as connection:
                    roles = FrameworkRoles(ws, SqliteSaver(connection), lambda role: never)
                    with self.assertRaisesRegex(ValueError, 'outside|registered SQL database'):
                        roles.run('verifier', {'id': 'unbound-input', 'question': 'Use actual received inputs.'})
                self.assertEqual(never.calls, 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
