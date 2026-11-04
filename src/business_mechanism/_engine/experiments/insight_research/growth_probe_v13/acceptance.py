"""Counter semantics/future evidence/native sources/reference boundaries, zero API."""
import argparse
import json
import os
from pathlib import Path
import unittest
from ..common import ROOT, digest, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World, Environment as OriginalEnvironment
from ..review.workflow_20261025.quiescent_budget import snapshot
from ..review.partial_bound_followup_20261101.reference_feasibility import lower_rate_ratio
from .environment import Environment
from .workspace import ResearchWorkspace

HERE = ROOT / 'experiments/insight_research/review/partial_bound_followup_20261101'


class Checks(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ['GROWTH_V13_OUTPUT']) / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)

    def test_01_definitions_leave_actual_windows_randomization_charges_unchanged(self):
        world = World(seed=4001, entry_rate=24, completion_probability=.4, recording_probability=.5)
        envs = []
        for name, cls in [('original', OriginalEnvironment), ('defined', Environment)]:
            (self.root / name / 'private').mkdir(parents=True)
            env = cls(world);env.materialize(self.root / name / 'public');envs.append(env)
        for operation, windows in [('flow_audit', 8), ('capacity_trial', 12), ('entry_count', 8)]:
            outputs = []
            for i, env in enumerate(envs):
                folder = self.root / str(i) / operation
                receipt = env.perform(folder, operation, operation=operation, windows=windows, purpose='Actual P0 matched-observation control.')
                outputs.append((receipt, json.loads((folder / 'observations.json').read_text())))
            self.assertEqual(outputs[0], outputs[1])
            for row in outputs[1][1]:
                if operation == 'flow_audit':
                    self.assertLessEqual(row['recorded_transactions'], row['completed'])
                    self.assertLessEqual(row['completed'], row['entries'])
        self.assertEqual(envs[0].state(), envs[1].state())
        self.assertEqual((self.root / 'original/public/business.sqlite').read_bytes(), (self.root / 'defined/public/business.sqlite').read_bytes())
        dictionary = json.loads((self.root / 'defined/public/data_dictionary.json').read_text())
        self.assertIn('completed', dictionary['observed_counter_definitions'])
        for name in ('entry_rate', 'completion_probability', 'recording_probability'):
            self.assertNotIn(name, encoded(dictionary))

    def test_02_full_native_candidate_not_fact_and_original_version_is_unambiguous(self):
        old = json.loads((ROOT / 'experiments/insight_research/review/growth_experience_20261031/history_provenance.json').read_text())['archive']
        native = json.loads((HERE / 'native_method_source/provenance.json').read_text())['archive']
        cfg = config();cfg.update(verification_mode='self', experience_mode='episode', project_archives=[old, native])
        cfg['limits'].update(token_allowance=1500000, max_http_attempts=0)
        cfg['execution_policy']['closeout_reserve_tokens'] = 400000
        ws = ResearchWorkspace(self.root / 'researcher', 'Assess register completeness at capacity2 with lawful current evidence.',
            World(seed=4002, entry_rate=24, completion_probability=.4, recording_probability=.5), cfg)
        try:
            self.assertEqual(len(ws.tools), 16)
            self.assertEqual(ws.records('hypothesis'), [])
            self.assertEqual(ws.records('knowledge'), [])
            self.assertEqual(ws.records('state'), [])
            context = ws.experience_context()
            self.assertLessEqual(context['automatic_context_bytes'], 6144)
            self.assertEqual(context['received_stage_order'], [old['stage_id'], native['stage_id']])
            ref = 'archive:SCI073-SERVICE-01:K4d39c8762ff4431b'
            got = ws.call('read_memory', {'ref': ref, 'offset': 0, 'limit': 18000}, 'actual_version_control')
            self.assertEqual(got['original_version'], json.loads(got['text'])['original_version'])
            self.assertNotEqual(got['original_version'], got['sha256'])
            self.assertFalse(got['current_field_view']['scientific_certification'])
            self.assertEqual(got['current_field_view']['effective_text_fields']['research_use'],
                ws.effective_historical_view(ref, got['original_version'])['effective_text_fields']['research_use'])
            schemas = {t['function']['name']: t['function']['description'] for t in ws.tool_schemas()}
            self.assertIn('omit unchanged', schemas['update_research_state'])
            self.assertIn('phase=checkpoint', schemas['review_claim'])
            self.assertEqual(cfg['model_config']['generation_options']['max_tokens'], 65536)
            public = ws.file_ref(ws.public / 'data_dictionary.json', 'public_seen')['ref']
            read = ws.call('read_memory', {'ref': public, 'offset': 0, 'limit': 18000}, 'actual_counter_read')
            self.assertIn('completed', read['text'])
        finally:
            ws.close()

    def test_03_reference_distinguishes_supported_threshold_from_insufficient_bound(self):
        high = lower_rate_ratio(1710, 54, 3008, 94)
        low = lower_rate_ratio(684, 54, 3008, 94)
        self.assertGreater(high, .9)
        self.assertLess(low, .9)
        self.assertEqual(lower_rate_ratio(0, 54, 3008, 94), 0)
        self.assertEqual(108 * 3 + 94 * 2, 512)
        write_json(self.root / 'reference_cases.json', {'potentially_decisive_lower': high,
            'insufficient_lower': low, 'interpretation': 'Low lowerbound never refutes highcompleteness. These are Rootreferencefixtures, notAgentdiscoveries.'})


def main():
    p = argparse.ArgumentParser();p.add_argument('--output', type=Path, required=True);args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False);os.environ['GROWTH_V13_OUTPUT'] = str(args.output / 'cases')
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before == snapshot()
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'project_budget_unchanged': True,
        'scope': '3actual counterdefinition/sameobservations-costs/nativecandidate/normaltools/versionheader/referenceboundary controls. No model benefit, parameterrecovery, methodgrowth or newmechanism proof.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
