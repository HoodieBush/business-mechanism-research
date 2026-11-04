"""Native persistence and control checks, not evidence of real fee/science gains."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.durable_context import PROFILE
from langgraph_migration.provider import gateway_messages
from langgraph_migration.runtime import FrameworkRoles, role_task_context
from langgraph_migration.science import ScientificWorkspace
from test_langgraph_migration import ScriptedModel
from test_tool_outputs import ObservedScriptedModel
from world import OfficeWorld


def snapshots(messages):
    values = []
    for message in messages:
        if message.type != 'human' or not isinstance(message.content, str):
            continue
        try:
            value = json.loads(message.content)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get('kind') == 'framework_runtime_accounting':
            values.append(value)
    return values


class DurableContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_durable_context_')
        self.root = Path(self.temp.name)
        self.ws = ScientificWorkspace(self.root / 'case', OfficeWorld('relationship', 18023))
        self.ws.harness_context_profile = PROFILE
        self.ws.state['workflow']['phase'] = 'needs_hypotheses'
        self.ws.persist()
        self.attach_costs()
        self.connection = sqlite3.connect(self.root / 'checkpoints.sqlite', check_same_thread=False)
        self.saver = SqliteSaver(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def attach_costs(self):
        self.ws.resource_reader = lambda: {'reported_tokens': len(self.ws.state['events']) * 100,
                                         'shared_admission_limit': None, 'fixture_only': True}

    def hypothesis(self):
        return ('save_hypothesis', {'explanation': 'Engineering fixture, not a discovery.',
            'scope': 'Received fixture history', 'alternatives': ['Other explanation'],
            'prediction': 'An untested prediction', 'falsification': 'A contrary observation',
            'evidence_files': [str(self.ws.public / 'history.csv')], 'change_reason': 'Fixture', 'parent_id': None})

    def task(self):
        return {'id': 'durable-cost-fixture', 'question': 'Keep this original scoped research question.',
                'inputs': self.ws.state['base_source_paths']}

    def roles(self, model, summary=None):
        summary = summary or ScriptedModel(sequence=['Exact sources remain in their receipts; no new evidence.'] * 6)
        return FrameworkRoles(self.ws, self.saver, lambda role: summary if role == 'context' else model)

    def test_actual_second_request_extends_first_including_latest_cost_snapshot(self):
        model = ObservedScriptedModel(sequence=[('read_context', {}), self.hypothesis()])
        result = self.roles(model).run('mechanist', self.task())
        self.assertEqual(result['id'], 'H001')
        first, second = map(gateway_messages, model.prompts)
        self.assertEqual(second[:len(first)], first)
        self.assertEqual([m['role'] for m in first].count('system'), 1)
        self.assertEqual([m['role'] for m in second].count('system'), 1)
        self.assertIn('needs_hypotheses', first[0]['content'])
        self.assertIn(self.task()['question'], first[0]['content'])
        values = snapshots(model.prompts[-1])
        self.assertEqual([v['research_costs']['reported_tokens'] for v in values], [0, 100])
        self.assertTrue(all(v['research_costs']['shared_admission_limit'] is None for v in values))

    def test_sqlite_resume_keeps_snapshot_and_does_not_repeat_completed_tool(self):
        class Interrupted(ObservedScriptedModel):
            def _generate(self, messages, **kwargs):
                if self.calls == 1:
                    self.prompts.append(deepcopy(messages))
                    raise KeyboardInterrupt('fixture after durable read')
                return super()._generate(messages, **kwargs)
        model = Interrupted(sequence=[('read_context', {})])
        with self.assertRaises(KeyboardInterrupt):
            self.roles(model).run('mechanist', self.task())
        pending = gateway_messages(model.prompts[-1])
        self.ws = ScientificWorkspace(self.ws.root, OfficeWorld('relationship', 18023), reopen=True)
        self.ws.harness_context_profile = PROFILE
        self.attach_costs()
        resumed = ObservedScriptedModel(sequence=[self.hypothesis()])
        roles = self.roles(resumed)
        self.assertEqual(roles.run('mechanist', self.task())['id'], 'H001')
        self.assertEqual(gateway_messages(resumed.prompts[0]), pending)
        self.assertEqual(sum(e['tool'] == 'read_context' for e in self.ws.state['events']), 1)
        self.assertEqual(roles.run('mechanist', self.task())['id'], 'H001')
        self.assertEqual(resumed.calls, 1)

    def test_real_native_compaction_keeps_current_snapshot_and_original_task(self):
        original = self.ws._tool
        self.ws._tool = lambda role, name, args: ({'large_observation': 'record ' * 16000,
            'negative_result': 'Unresolved fixture, not a new fact.'} if name == 'read_context' else original(role, name, args))
        index = self.ws.workers['mechanist'].directory / 'framework_receipts/index.json'
        read = ('read_artifact', {'path': str(index)})
        model = ObservedScriptedModel(sequence=[('read_context', {}), read, read, read, self.hypothesis()])
        summary = ScriptedModel(sequence=['Unresolved original observation remains in its exact tool receipt.'] * 8)
        self.roles(model, summary).run('mechanist', self.task())
        self.assertGreater(summary.calls, 0)
        self.assertIn(self.task()['question'], model.prompts[-1][0].content)
        values = snapshots(model.prompts[-1])
        self.assertTrue(values)
        self.assertEqual(values[-1]['research_costs']['reported_tokens'], 400)
        self.assertTrue(any('record ' * 16000 in p.read_text() for p in (self.ws.workers['mechanist'].directory / 'framework_receipts').glob('*.json')))

    def test_all_five_roles_retain_original_permission_filters_and_unknown_profile_fails(self):
        roles = self.roles(ScriptedModel(sequence=[]))
        stages = {'manager': 'needs_research_decision', 'analyst': 'needs_analysis',
                  'mechanist': 'needs_hypotheses', 'verifier': 'needs_review', 'engineer': 'needs_algorithm'}
        for role, phase in stages.items():
            received = {'id': role, 'inputs': [], 'execution_phase': phase}
            snapshot = self.ws.capture_task(role, received, self.ws.task_binding(received))
            token = role_task_context.set(snapshot)
            try:
                self.assertEqual('run_python' in snapshot['allowed_tools'], 'run_python' in self.ws.framework_role_tools[role])
                if role != 'verifier':
                    self.assertFalse(self.ws.tool_allowed_now('record_verdict'))
                roles.build(role)
            finally:
                role_task_context.reset(token)
        self.ws.harness_context_profile = 'unknown'
        with self.assertRaisesRegex(ValueError, 'Unknown harness'):
            roles.build('analyst')


if __name__ == '__main__':
    unittest.main()
