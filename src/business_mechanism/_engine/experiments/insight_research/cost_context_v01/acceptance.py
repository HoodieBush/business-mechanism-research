"""Finite actual database/journal/sandbox checks; zero provider calls."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ..common import ROOT, Pending, digest, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v14.acceptance import archives
from ..growth_probe_v14.workspace import ResearchWorkspace
from ..paired_v01.budget import StudyBudget
from ..runtime_memory import reconstruct_request
from ..test_acceptance import hypothesis, state, raw_call
from .runtime import ResearchRun
from .wire import organize, restore_logical, current_context, VIEW, REPEAT


def request(context=None, receipts=()):
    messages = [{'role': 'system', 'content': 'Fixture original scientific instructions.'},
        {'role': 'user', 'content': encoded(context or {'question': 'Fixture business question', 'pending': ['R1']})}]
    for i, (tool, body) in enumerate(receipts):
        call_id = 'call' + str(i)
        messages.extend([{'role': 'assistant', 'content': '', 'reasoning_content': 'Original reasoning',
            'tool_calls': [{'id': call_id, 'type': 'function', 'function': {'name': tool, 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': call_id, 'content': encoded(body)}])
    return {'model': 'fixture', 'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high',
        'max_tokens': 65536, 'messages': messages, 'tools': [], 'tool_choice': 'auto'}


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['COST_CONTEXT_OUTPUT']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.open = []

    def tearDown(self):
        for ws in self.open:
            ws.close()

    def runtime(self, reopen=False):
        cfg = config()
        cfg.update(verification_mode='self', experience_mode='episode', project_archives=archives())
        cfg['limits']['max_http_attempts'] = 80
        world = World(seed=19071, entry_rate=24, completion_probability=.3, recording_probability=.7)
        ws = ResearchWorkspace(self.folder / 'actor/researcher', 'Engineering source/state preservation only', world, cfg, reopen=reopen)
        self.open.append(ws)
        identity = {'token_allowance': 2000000, 'max_http_attempts': 80,
            'project_budget_id': 'USER-20261022-CRITIC-10M', 'scope': 'Engineering fixture, no provider charge'}
        budget = StudyBudget(self.folder / 'actor/common_budget.sqlite', identity, create=not reopen)
        run = ResearchRun(self.folder / 'actor', ws, cfg['model_config'], budget)
        return ws, run

    def test_01_full_state_supersession_and_all_generation_options_roundtrip(self):
        context = {'question': 'Original task', 'withdrawals': ['Kold'], 'unincorporated_results': ['R2'],
            'open_disputes': ['Q1'], 'source_versions': {'Kold': 'v1'}, 'resources': {'left': 2000}}
        original = request(context)
        candidate = organize(original)
        self.assertEqual(restore_logical(candidate), original)
        self.assertEqual(current_context(candidate)[1], context)
        self.assertEqual(organize(candidate), candidate)
        self.assertEqual(candidate['max_tokens'], 65536)
        self.assertNotIn('temperature', candidate)
        self.assertEqual(sum(VIEW in m['content'] for m in candidate['messages'] if m['role'] == 'user'), 2)
        self.assertEqual(original['messages'][1]['content'], encoded(context))

    def test_02_repeated_read_receipts_are_not_deleted_or_rewritten(self):
        body = {'ref': 'file:old', 'text': 'Original received observation. ' * 200,
            'lifecycle': {'status': 'withdrawn'}, 'version': 'exact-v1'}
        original = request(receipts=[('read_artifact', body), ('read_artifact', body)])
        candidate = organize(original)
        tools = [m for m in candidate['messages'] if m['role'] == 'tool']
        self.assertEqual(tools[0]['content'], encoded(body))
        self.assertEqual(tools[1]['content'], encoded(body))
        self.assertEqual(restore_logical(candidate), original)
        # If the old turn leaves the window, the remaining receipt stays full.
        shortened = deepcopy(original); shortened['messages'] = original['messages'][:2] + original['messages'][-2:]
        self.assertEqual([m for m in organize(shortened)['messages'] if m['role'] == 'tool'][0]['content'], encoded(body))

    def test_03_new_evidence_failures_and_changed_versions_remain_full(self):
        body = {'ok': True, 'text': 'Raw new evidence ' * 200, 'version': 'v1'}
        failed = {**body, 'ok': False, 'error': 'Preserve the real failure'}
        changed = {**body, 'version': 'v2'}
        for receipts in ([('collect_evidence', body), ('collect_evidence', body)],
                [('read_memory', failed), ('read_memory', failed)],
                [('read_memory', body), ('read_memory', changed)]):
            original = request(receipts=receipts)
            self.assertEqual([m for m in organize(original)['messages'] if m['role'] == 'tool'],
                [m for m in original['messages'] if m['role'] == 'tool'])

    def test_04_unfinished_paid_batches_and_corrupt_pointers_cannot_pass(self):
        p = request(receipts=[('read_memory', {'text': 'x' * 3000})])
        p['messages'].pop()
        with self.assertRaises(Pending): organize(p)
        original = request(receipts=[('read_memory', {'text': 'x' * 3000})] * 2)
        candidate = organize(original)
        candidate['messages'][-2]['content'] = encoded({REPEAT: {'old_prototype': True}})
        with self.assertRaises(Pending): restore_logical(candidate)
        candidate = organize(original)
        body = json.loads(candidate['messages'][-1]['content']);body[VIEW]['context']['pending'] = []
        candidate['messages'][-1]['content'] = encoded(body)
        with self.assertRaises(Pending): current_context(candidate)

    def test_05_real_workspace_journal_wire_reconstruction_and_permission_boundary(self):
        ws, run = self.runtime()
        run.runtime.cp['messages'] = run.runtime.initial()
        payload = run.runtime.payload()
        self.assertEqual(len(ws.tools), 16)
        self.assertEqual(current_context(payload)[1], json.loads(run.runtime.initial()[1]['content']))
        run.journal.persist_request(1, payload)
        self.assertEqual(reconstruct_request(ws.private, 1), payload)
        retrieval = json.loads(ws.db.execute('SELECT body FROM retrievals WHERE attempt=1').fetchone()[0])
        self.assertEqual(retrieval['context_sha256'], digest(current_context(payload)[1]))
        forbidden = str(ROOT / 'experiments/studies/SCI-082/scientific_audit.json')
        out = ws.call('run_python', {'code': 'from pathlib import Path\nprint(Path('+repr(forbidden)+').read_text())', 'purpose': 'Engineering forbidden Root audit read'}, 'boundary')
        self.assertFalse(out['execution']['ok'])
        self.assertFalse(ws.db.in_transaction)

    def test_06_actual_paid_delivery_fixture_reopen_drains_once_without_resend(self):
        ws, run = self.runtime()
        run.runtime.cp['messages'] = run.runtime.initial();run.runtime.save()
        payload = run.runtime.payload()
        original_system = deepcopy(payload['messages'][0])
        fixture = {'response': raw_call('read_context', {}, 'paid_call', usage={'total_tokens': 123})}
        with patch('experiments.insight_research.paired_v01.budget.request_model', return_value=fixture) as transport:
            first = run.journal.call(payload)
            self.assertEqual(run.journal.call(payload)['response'], first['response'])
            self.assertEqual(transport.call_count, 1)
        run.runtime.accept(first['response'], 1);run.journal.ack()
        self.assertIsNotNone(run.runtime.cp['pending'])
        self.open.remove(ws);ws.close()
        ws, resumed = self.runtime(reopen=True)
        resumed.runtime.drain()
        resumed.runtime.drain()
        self.assertIsNone(resumed.runtime.cp['pending'])
        count = ws.db.execute("SELECT count(*) FROM events WHERE json_extract(body,'$.tool')='read_context'").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(resumed.budget.snapshot()['reported_tokens'], 123)
        self.assertEqual(resumed.budget.snapshot()['http_attempts'], 1)
        self.assertEqual(reconstruct_request(ws.private, 1), payload)
        self.assertEqual(restore_logical(resumed.runtime.payload())['messages'][0], original_system)

    def test_07_actual_withdrawal_remains_current_and_original_remains_readable(self):
        ws, run = self.runtime()
        h = ws.call('save_hypothesis', hypothesis(statement='Engineering candidate, no business claim'), 'h')
        source = ws.file_ref(ws.public / 'data_dictionary.json')['ref']
        action = ws.tools['update_research_state'][0].model_validate(state(
            question=ws.question, evidence_refs=[source], inactive_hypotheses={h['ref']: 'Engineering withdrawn branch'}, memory_reviews=[{'target_ref': h['ref'],
                'decision': 'withdraw', 'reason': 'Engineering explicit withdrawal', 'evidence_refs': [source]}])).model_dump()
        saved = ws.call('update_research_state', action, 'withdraw')
        self.assertIn('ref', saved, saved)
        run.runtime.cp['messages'] = run.runtime.initial()
        payload = run.runtime.payload();view = current_context(payload)[1]
        self.assertEqual(view, json.loads(run.runtime.initial()[1]['content']))
        read = ws.call('read_memory', {'ref': h['ref'], 'offset': 0, 'limit': 18000}, 'read_old')
        self.assertEqual(json.loads(read['text'])['ref'], h['ref'])
        from ..critic_v01.shared import lifecycle
        self.assertEqual(lifecycle(ws.db, h['ref'])['status'], 'withdraw')
        with self.assertRaises(ValueError): ws.premise(h['ref'])
        self.assertEqual(restore_logical(payload)['messages'][1]['content'], encoded(view))


def main():
    p = argparse.ArgumentParser();p.add_argument('--output', type=Path, required=True);a=p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False);os.environ['COST_CONTEXT_OUTPUT'] = str(a.output / 'cases')
    # The exact charge assertion belongs to a quiescent registered engineering
    # run. A pure replay during another authorized job is recorded separately.
    from ..review.workflow_20261025.quiescent_budget import snapshot
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    after = snapshot();assert before == after
    write_json(a.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_provider_calls': 0, 'project_unchanged': True,
        'fixture_local_tokens_are_not_real_cost': 123,
        'scope': 'Finite wire/state/archive/tool/sandbox/actual-local-delivery controls. No model quality, provider cache or cash-saving certification.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':main()
