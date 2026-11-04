"""Actual two-native-stage continuity checks, not scientific truth tests."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from ..common import ROOT, digest, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v03.orchestrator import ResearchRun
from ..growth_probe_v05.orchestrator import ResearchRuntime
from ..growth_probe_v04.acceptance import HISTORY, QUESTION
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from ..growth_probe_v07.acceptance import Checks as CheckHelpers, SOURCE
from .workspace import ResearchWorkspace

NATIVE = ROOT / 'experiments/insight_research/review/growth_transfer_20261031/native_candidate_stage/provenance.json'


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['GROWTH_V09_OUTPUT']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.workspaces = []
        self.number = 0

    def tearDown(self):
        for ws in self.workspaces:
            ws.close()

    call = CheckHelpers.call
    checkpoint = CheckHelpers.checkpoint
    action = CheckHelpers.action

    def workspace(self, mode='recent', missing_source=False):
        cfg = config()
        old = json.loads(HISTORY.read_text())['archive']
        new = json.loads(NATIVE.read_text())['archive']
        cfg.update(verification_mode='self', experience_mode=mode,
            project_archives=[] if mode == 'none' else ([new] if missing_source else [old, new]))
        cfg['limits'].update(token_allowance=1500000, max_http_attempts=0)
        cfg['execution_policy']['closeout_reserve_tokens'] = 400000
        ws = ResearchWorkspace(self.folder / mode / 'researcher', QUESTION,
            World(seed=823, entry_rate=20, completion_probability=.4, recording_probability=1), cfg)
        self.workspaces.append(ws)
        return ws

    def test_01_imports_actual_native_decisions_without_copying_scientific_facts(self):
        ws = self.workspace()
        self.assertEqual(ws.records('hypothesis'), [])
        self.assertEqual(ws.records('knowledge'), [])
        self.assertEqual(ws.records('state'), [])
        _, original, _ = ws.historical_original(SOURCE)
        view = ws.effective_historical_view(SOURCE, digest(original))
        self.assertIsNotNone(view)
        self.assertEqual(view['effective_text_fields']['scope'], original['scope'])
        self.assertTrue(all(a['imported_from_received_stage'] for a in view['field_revisions'].values()))
        self.assertTrue(all(a['revision_read_ref'].startswith('archive:SCI077-FIELD-REVIEW:') for a in view['field_revisions'].values()))
        self.assertFalse(view['scientific_certification'])
        self.assertEqual(ws.imported_revision_rejections, [])
        write_json(self.folder / 'actual_imported_view.json', view)

    def test_02_long_real_revision_keeps_bounded_exact_navigation_and_can_be_read(self):
        ws = self.workspace()
        automatic = ws.experience_context()
        self.assertLessEqual(automatic['automatic_context_bytes'], 6144)
        self.assertLessEqual(len(automatic['items']), 3)
        item = next(i for i in automatic['items'] if i['ref'] == SOURCE)
        self.assertTrue(item.get('current_field_view') or item.get('current_revision_read_refs'))
        if item.get('current_revision_read_refs'):
            revision = self.call(ws, 'read_memory', {'ref': item['current_revision_read_refs'][0], 'offset': 0, 'limit': 18000})
            self.assertIn('materialized_original', revision)
        original = self.call(ws, 'read_memory', {'ref': SOURCE, 'offset': 0, 'limit': 18000})
        self.assertIn('current_field_view', original)
        self.assertEqual(json.loads(original['text'])['original']['ref'], 'K4d39c8762ff4431b')
        evidence = original['current_field_view']['field_revisions']['research_use']['evidence_read_refs'][0]
        got = self.call(ws, 'read_memory', {'ref': evidence, 'offset': 0, 'limit': 18000})
        self.assertIn('materialized_original', got)
        self.assertLessEqual(len(encoded(ws.context()).encode()), 65536)

    def test_03_current_override_and_explicit_withdrawal_survive_reopen(self):
        ws = self.workspace()
        got = self.call(ws, 'read_memory', {'ref': SOURCE, 'offset': 0, 'limit': 18000})
        original = json.loads(got['text'])['original']
        version = digest(original)
        inherited = ws.field_actions(SOURCE, version)['research_use']
        brief = ws.file_ref(ws.public / 'business_brief.md', 'public_seen')['ref']
        changed = self.checkpoint(ws, [self.action(version, [brief], replacement_text='Engineering local override only.',
            expected_prior_revision_ref=inherited['revision_ref'])])
        self.assertIn('ref', changed, changed)
        self.assertEqual(ws.effective_historical_view(SOURCE, version)['effective_text_fields']['research_use'], 'Engineering local override only.')
        removed = self.checkpoint(ws, reviews=[{'target_ref': changed['ref'], 'decision': 'withdraw',
            'reason': 'Explicitly withdraw this engineering revision record, not the old scientific original.', 'evidence_refs': [brief]}])
        self.assertIn('ref', removed, removed)
        self.assertEqual(ws.field_actions(SOURCE, version)['research_use']['revision_ref'], inherited['revision_ref'])
        root, world, question, settings = ws.root, ws.environment.world, ws.question, deepcopy(ws.settings)
        ws.close()
        self.workspaces.remove(ws)
        reopened = ResearchWorkspace(root, question, world, settings, reopen=True)
        self.workspaces.append(reopened)
        self.assertEqual(reopened.field_actions(SOURCE, version)['research_use']['revision_ref'], inherited['revision_ref'])
        self.assertEqual(reopened.historical_original(SOURCE)[1], original)

    def test_04_missing_source_is_visible_not_silently_applied(self):
        ws = self.workspace(missing_source=True)
        self.assertEqual(len(ws.imported_revision_rejections), 3)
        self.assertEqual(ws.db.execute('SELECT count(*) FROM historical_field_reviews').fetchone()[0], 0)
        self.assertEqual(ws.context()['history_import_status']['unapplied_total'], 3)
        failed = self.call(ws, 'read_memory', {'ref': SOURCE, 'offset': 0, 'limit': 12000})
        self.assertFalse(failed['ok'])

    def test_05_three_modes_normal_capacity_and_private_denial(self):
        public = []
        for mode in ('none', 'recent', 'episode'):
            ws = self.workspace(mode)
            public.append(ws.identity['public_inputs'])
            self.assertEqual(len(ws.tools), 16)
            self.assertLessEqual(len(encoded(ws.context()).encode()), 65536)
            budget = StudyBudget(self.folder / mode / 'common_budget.sqlite',
                {'token_allowance': 1500000, 'max_http_attempts': 0,
                 'project_budget_id': 'USER-20261022-CRITIC-10M'}, create=True)
            run = ResearchRun(self.folder / mode, ws, ws.settings['model_config'], budget)
            runtime = ResearchRuntime(ws, ws.settings['model_config'], journal=run.journal)
            payload = runtime.payload(runtime.initial())
            self.assertEqual(payload['max_tokens'], 65536)
            self.assertEqual(payload['thinking']['type'], 'enabled')
            self.assertEqual(budget.snapshot()['http_attempts'], 0)
        self.assertEqual(public[0], public[1])
        self.assertEqual(public[1], public[2])
        audit = ROOT / 'experiments/studies/SCI-077/scientific_audit.json'
        denied = self.call(self.workspaces[-1], 'run_python', {'code': f'print(open({str(audit)!r}).read())',
            'purpose': 'Actual external scientific-audit denial.'})
        self.assertFalse(denied['execution']['ok'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['GROWTH_V09_OUTPUT'] = str(args.output / 'cases')
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before == snapshot()
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'budget_unchanged': True,
        'scope': '5actual two-native-stage import/read/long-navigation/evidence/sourceversion/currentwithdrawal/reopen/missing-source/normal/privacy controls. No semantic correctness or lifelong efficacy certified.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
