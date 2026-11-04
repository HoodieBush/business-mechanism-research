"""Actual zero-API controls for the service registration contract candidate."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

from ..common import ROOT, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v04.acceptance import HISTORY, QUESTION
from ..growth_probe_v03.orchestrator import ResearchRun
from ..growth_probe_v05.orchestrator import ResearchRuntime
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from .workspace import ResearchWorkspace


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['GROWTH_V06_OUTPUT']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.workspaces = []

    def tearDown(self):
        for ws in self.workspaces:
            ws.close()

    def workspace(self, mode='none'):
        cfg = config()
        cfg.update(verification_mode='self', experience_mode=mode,
            project_archives=[] if mode == 'none' else [json.loads(HISTORY.read_text())['archive']])
        cfg['limits'].update(token_allowance=800000, max_http_attempts=0)
        cfg['execution_policy']['closeout_reserve_tokens'] = 250000
        ws = ResearchWorkspace(self.folder / mode / 'researcher', QUESTION,
            World(seed=823, entry_rate=20, completion_probability=.4, recording_probability=1,
                instruments=('observe', 'capacity_trial', 'wait')), cfg)
        self.workspaces.append(ws)
        return ws

    def hypothesis(self, ws):
        catalog = ws.file_ref(ws.public / 'measurement_catalog.json', 'public_seen')['ref']
        h = ws.call('save_hypothesis', {'kind': 'business', 'statement': 'Engineering fixture only.',
            'scope': 'Current engineering service windows.', 'prediction': 'Fixture increment exceeds2.',
            'falsification': 'Fixture increment at or below2.', 'alternatives': ['Other increment.'],
            'evidence_refs': [catalog], 'effect_prediction': None, 'used_memory_refs': []}, 'fixture_h')
        self.assertIn('ref', h)
        return h, catalog

    def test_01_public_schema_matches_supported_analysis_arguments(self):
        ws = self.workspace()
        h, catalog = self.hypothesis(ws)
        args = {'hypothesis_ref': h['ref'], 'prediction': h['prediction'],
            'contrast': 'Fixture mean difference.', 'observation_unit': 'window',
            'allocation_unit': 'window', 'analysis': 'Fixture fixed code.', 'purpose': 'Engineering only.',
            'data_refs': [catalog], 'mode': 'observational', 'code': 'print(1)',
            'expected_changed_variables': [], 'used_memory_refs': []}
        schema = next(t['function']['parameters'] for t in ws.tool_schemas()
                      if t['function']['name'] == 'register_test')
        self.assertIn('code', schema['required'])
        self.assertEqual(schema['properties']['code']['type'], 'string')
        self.assertEqual(schema['properties']['code']['minLength'], 1)
        self.assertEqual(schema['properties']['expected_changed_variables']['maxItems'], 0)
        result = ws.call('register_test', args, 'valid_analysis')
        self.assertIn('ref', result)
        self.assertEqual(ws.environment.state()['spent_credits'], 0)
        self.assertEqual(ws.records('result'), [])

    def test_02_legacy_bad_submission_is_durable_actionable_feedback(self):
        ws = self.workspace()
        h, catalog = self.hypothesis(ws)
        args = {'hypothesis_ref': h['ref'], 'prediction': h['prediction'],
            'contrast': 'Fixture mean difference.', 'observation_unit': 'window',
            'allocation_unit': 'window', 'analysis': 'Fixture wrong action arguments.',
            'purpose': 'Engineering rejection.', 'data_refs': [catalog], 'mode': 'observational',
            'code': None, 'expected_changed_variables': ['capacity_multiplier'], 'used_memory_refs': []}
        before = ws.environment.state()
        rejected = ws.call('register_test', args, 'rejected_original')
        self.assertFalse(rejected['ok'])
        self.assertIn('expected_changed_variables=[]', rejected['error'])
        self.assertIn('before that acquisition', rejected['error'])
        self.assertEqual(ws.call('register_test', args, 'rejected_original'), rejected)
        self.assertEqual(ws.records('plan'), [])
        self.assertEqual(ws.environment.state(), before)
        write_json(self.folder / 'actual_rejection.json', rejected)

    def test_03_actual_preacquisition_sandbox_and_replay(self):
        # Reuse the exact existing actual workflow rehearsal, changing only
        # the candidate workspace constructor in this isolated test process.
        from ..review.growth_experience_20261031 import replay_preacquisition as rehearsal
        old_class, old_argv = rehearsal.ResearchWorkspace, sys.argv
        rehearsal.ResearchWorkspace = ResearchWorkspace
        sys.argv = ['preacquisition_rehearsal', '--output', str(self.folder / 'actual_workflow')]
        try:
            rehearsal.main()
        finally:
            rehearsal.ResearchWorkspace, sys.argv = old_class, old_argv
        result = json.loads((self.folder / 'actual_workflow/acceptance.json').read_text())
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['project_budget_unchanged'])
        self.assertEqual(result['new_paid_calls'], 0)

    def test_04_three_modes_normal_payload_and_actual_private_denial(self):
        public = []
        schemas = []
        for mode in ('none', 'recent', 'episode'):
            ws = self.workspace(mode)
            public.append(ws.identity['public_inputs'])
            schemas.append(encoded(ws.tool_schemas()))
            self.assertEqual(len(ws.tools), 16)
            self.assertEqual(ws.records('hypothesis'), [])
            self.assertLessEqual(len(encoded(ws.context()).encode()), 65536)
            budget = StudyBudget(self.folder / mode / 'common_budget.sqlite',
                {'token_allowance': 800000, 'max_http_attempts': 0,
                 'project_budget_id': 'USER-20261022-CRITIC-10M'}, create=True)
            run = ResearchRun(self.folder / mode, ws, ws.settings['model_config'], budget)
            runtime = ResearchRuntime(ws, ws.settings['model_config'], journal=run.journal)
            payload = runtime.payload(runtime.initial())
            self.assertEqual(payload['max_tokens'], 65536)
            self.assertEqual(payload['thinking']['type'], 'enabled')
            self.assertEqual(budget.snapshot()['http_attempts'], 0)
        self.assertEqual(public[0], public[1])
        self.assertEqual(public[1], public[2])
        self.assertEqual(schemas[0], schemas[1])
        self.assertEqual(schemas[1], schemas[2])
        audit = ROOT / 'experiments/studies/SCI-075/scientific_audit.json'
        denied = self.workspaces[-1].call('run_python',
            {'code': f'print(open({str(audit)!r}).read())', 'purpose': 'Actual private-source denial.'},
            'deny_external_audit')
        self.assertFalse(denied['execution']['ok'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['GROWTH_V06_OUTPUT'] = str(args.output / 'cases')
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before == snapshot()
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'budget_unchanged': True,
        'scope': 'Public schema/backend feedback, actual fixed-code-first path and replay, normal3mode payload and sandbox boundary. Not automatic future-data binding, scientific correctness or model-behavior benefit.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
