"""Rerun4 transport controls plus2 actual paused native-history controls, no API."""
import argparse
import json
import os
from pathlib import Path
import shutil
import unittest
from ..common import ROOT, Pending, digest, encoded, sha, write_json
from ..growth_probe_v01.environment import World
from ..growth_probe_v10.workspace import ResearchWorkspace
from ..growth_probe_v11.acceptance import Checks as TransportChecks
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from .context import install_history_packer, reserve_navigation

PARENTS = ROOT / 'experiments/insight_research/review/growth_field_review_20261101/recovery_parents'


class HistoryChecks(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ['GROWTH_V12_OUTPUT']) / self._testMethodName
        self.workspaces = []

    def tearDown(self):
        for ws in self.workspaces:
            ws.close()

    def parent(self, mode):
        source = PARENTS / mode
        target = self.root / mode
        shutil.copytree(source, target)
        identity = json.loads((target / 'researcher/private/identity.json').read_text())
        task = json.loads((ROOT / 'experiments/studies/SCI-079/tasks.json').read_text())['tasks'][0]
        ws = ResearchWorkspace(target / 'researcher', task['question'], World(**task['environment']), identity['settings'], reopen=True)
        self.workspaces.append(ws)
        import sqlite3
        with sqlite3.connect(target / 'common_budget.sqlite') as db:
            budget_identity = json.loads(db.execute('SELECT body FROM identity').fetchone()[0])
        ws.study_budget = StudyBudget(target / 'common_budget.sqlite', budget_identity, create=False)
        return ws

    def test_01_actual_failed_native_state_and_exact_revision_refs_recover(self):
        ws = self.parent('independent')
        records = ws.records('state')
        self.assertEqual(len(records), 1)
        with self.assertRaises(Pending) as error:
            ws.experience_context()
        self.assertIn('6KBcap', str(error.exception))
        before = ws.study_budget.snapshot()
        source_ref = records[0]['historical_field_reviews'][0]['source_ref']
        source_version = records[0]['historical_field_reviews'][0]['source_version']
        original = ws.historical_original(source_ref)[1]
        install_history_packer(ws)
        view = ws.experience_context()
        self.assertEqual(len(view['items']), 3)
        self.assertLessEqual(view['automatic_context_bytes'], 6144)
        self.assertIn(source_ref, [i['ref'] for i in view['items']])
        self.assertIn('original:' + records[0]['ref'], encoded(view))
        self.assertEqual(ws.context()['prior_experience'], view)
        self.assertEqual(ws.records('state'), records)
        effective = ws.effective_historical_view(source_ref, source_version)
        self.assertEqual(effective['effective_text_fields']['scope'], original['scope'])
        self.assertEqual(effective['effective_text_fields']['research_use'], records[0]['historical_field_reviews'][0]['replacement_text'])
        # Same original operation returns its durable completed receipt; no
        # duplicate scientific state, request or physical observation is created.
        raw = json.loads((ws.private / 'turns/11.json').read_text())
        call = next(c for c in raw['choices'][0]['message']['tool_calls'] if c['function']['name'] == 'update_research_state')
        args = json.loads(call['function']['arguments'])
        original_root = ROOT / 'experiments/studies/SCI-079/results/independent/researcher'
        key = digest([str(original_root), 11, call['id']])
        cached = ws.call('update_research_state', args, key)
        self.assertEqual(cached['ref'], records[0]['ref'])
        self.assertEqual(ws.records('state'), records)
        self.assertEqual(before, ws.study_budget.snapshot())
        write_json(self.root / 'native_reproduction.json', {'old_raises': str(error.exception),
            'new_context_bytes': view['automatic_context_bytes'], 'exact_all_three_sources_retained': True,
            'original_state_unchanged': True, 'cached_receipt_same_state': True, 'all_local_costs_unchanged': True})

    def test_02_reserve_all_minimum_refs_and_preserve_pre_revision_selection(self):
        candidates = [({'ref': str(i), 'text': 'x' * n}, {'ref': str(i), 'read': str(i)}) for i, n in enumerate((6060, 50, 50))]
        packed = reserve_navigation(candidates, 6144)
        self.assertEqual([i['ref'] for i in packed], ['0', '1', '2'])
        self.assertLessEqual(sum(len(encoded(i).encode()) for i in packed), 6144)
        ws = self.parent('self')
        old = ws.experience_context()
        install_history_packer(ws)
        current = ws.experience_context()
        self.assertEqual([i['ref'] for i in current['items']], [i['ref'] for i in old['items']])
        self.assertEqual(current['selection'], old['selection'])
        self.assertEqual(current['received_stage_order'], old['received_stage_order'])
        self.assertEqual(current['automatic_context_cap'], 6144)
        self.assertEqual(ws.study_budget.snapshot()['accounted_tokens'], 374102)
        self.assertEqual(ws.study_budget.snapshot()['unknown_reserve'], 362912)
        cp = json.loads((ws.private / 'checkpoint.json').read_text())
        self.assertEqual(cp['transport_failures'], 2)
        self.assertEqual(ws.records('hypothesis'), [])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['GROWTH_V11_OUTPUT'] = str(args.output / 'transport_cases')
    os.environ['GROWTH_V12_OUTPUT'] = str(args.output / 'history_cases')
    before = snapshot()
    parents = {str(p.relative_to(PARENTS)): sha(p) for p in PARENTS.rglob('*') if p.is_file()}
    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (TransportChecks, HistoryChecks)])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    assert before == snapshot()
    assert all(sha(PARENTS / p) == h for p, h in parents.items())
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'project_budget_unchanged': True,
        'scope': '4actual transport controls rerun plus2new historypacking/nativepausedS/cachedoperation/cost/oldselector controls. Parent paid snapshots unchanged. No model or scientific role benefit certified.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
