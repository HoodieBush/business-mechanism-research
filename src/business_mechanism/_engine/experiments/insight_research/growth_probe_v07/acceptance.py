"""Finite actual database/retrieval/recovery controls, zero external model calls."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from ..common import ROOT, digest, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v04.acceptance import HISTORY, QUESTION
from ..growth_probe_v03.orchestrator import ResearchRun
from ..growth_probe_v05.orchestrator import ResearchRuntime
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from .workspace import ResearchWorkspace

SOURCE = 'archive:SCI073-SERVICE-01:K4d39c8762ff4431b'
REPLACEMENT = 'Distinct new acquisition calls collect new windows; exact interrupted-operation replay alone recovers its cached sample. UniqueRevisedAcquisitionRule.'


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['GROWTH_V07_OUTPUT']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.workspaces = []
        self.number = 0

    def tearDown(self):
        for ws in self.workspaces:
            ws.close()

    def workspace(self, mode='recent'):
        cfg = config()
        cfg.update(verification_mode='self', experience_mode=mode,
            project_archives=[] if mode == 'none' else [json.loads(HISTORY.read_text())['archive']])
        cfg['limits'].update(token_allowance=1200000, max_http_attempts=0)
        cfg['execution_policy']['closeout_reserve_tokens'] = 300000
        world = World(seed=823, entry_rate=20, completion_probability=.4, recording_probability=1)
        ws = ResearchWorkspace(self.folder / mode / 'researcher', QUESTION, world, cfg)
        self.workspaces.append(ws)
        return ws

    def call(self, ws, tool, args):
        self.number += 1
        return ws.call(tool, args, 'fixture_' + str(self.number))

    def read_source(self, ws):
        got = self.call(ws, 'read_memory', {'ref': SOURCE, 'offset': 0, 'limit': 18000})
        body = json.loads(got['text'])
        return got, body['original'], body['original_version']

    def action(self, version, refs, **changes):
        return {'source_ref': SOURCE, 'source_version': version, 'field': 'research_use',
            'decision': 'replace', 'replacement_text': REPLACEMENT,
            'expected_prior_revision_ref': None, 'reason': 'Engineering fixture checked the public acquisition contract.',
            'evidence_refs': refs, **changes}

    def checkpoint(self, ws, actions=(), active=(), reviews=()):
        catalog = ws.file_ref(ws.public / 'measurement_catalog.json', 'public_seen')['ref']
        return self.call(ws, 'update_research_state', {'question': QUESTION, 'why': 'Engineering field-revision checkpoint.',
            'understanding': 'Engineering fixture only; source field actions are not scientific truth certification.',
            'active_hypothesis_refs': list(active), 'inactive_hypotheses': {}, 'alternative_refs': [],
            'evidence_refs': [catalog], 'counterevidence_refs': [], 'incorporated_result_refs': [],
            'recent_change': 'Explicit field review fixture.', 'open_questions': [],
            'next_action': 'Read exact old original and current field view.', 'next_reason': 'Check actual applied revision.',
            'knowledge_updates': [], 'memory_reviews': list(reviews), 'historical_field_reviews': list(actions)})

    def test_01_read_and_original_version_are_required(self):
        ws = self.workspace()
        _, original, body = ws.historical_original(SOURCE)
        version = digest(original)
        catalog = ws.file_ref(ws.public / 'measurement_catalog.json', 'public_seen')['ref']
        before = ws.environment.state()
        bad = self.checkpoint(ws, [self.action(version, [catalog])])
        self.assertFalse(bad['ok'])
        self.assertIn('Read this historical original', bad['error'])
        got, original, version = self.read_source(ws)
        bad = self.checkpoint(ws, [self.action(got['materialized_original']['sha256'], [catalog])])
        self.assertFalse(bad['ok'])
        self.assertIn('original_version mismatch', bad['error'])
        self.assertEqual(ws.records('state'), [])
        self.assertEqual(ws.environment.state(), before)

    def test_02_mixed_record_effective_views_and_actual_search(self):
        ws = self.workspace()
        got, original, version = self.read_source(ws)
        file = Path(got['materialized_original']['path'])
        old_bytes = file.read_bytes()
        brief = ws.file_ref(ws.public / 'business_brief.md', 'public_seen')['ref']
        result = self.checkpoint(ws, [self.action(version, [brief]),
            self.action(version, [brief], field='statement', decision='retain', replacement_text=None)])
        self.assertIn('ref', result, result)
        read = self.call(ws, 'read_memory', {'ref': SOURCE, 'offset': 0, 'limit': 18000})
        self.assertEqual(json.loads(read['text'])['original'], original)
        self.assertEqual(file.read_bytes(), old_bytes)
        view = read['current_field_view']
        self.assertEqual(view['effective_text_fields']['statement'], original['statement'])
        self.assertEqual(view['effective_text_fields']['research_use'], REPLACEMENT)
        self.assertFalse(view['scientific_certification'])
        automatic = ws.experience_context()
        selected = next(i for i in automatic['items'] if i['ref'] == SOURCE)
        self.assertNotIn('original', selected)
        self.assertEqual(selected['current_field_view']['effective_text_fields']['research_use'], REPLACEMENT)
        self.assertLessEqual(automatic['automatic_context_bytes'], 6144)
        search = self.call(ws, 'search_memory', {'query': 'UniqueRevisedAcquisitionRule', 'kind': 'all',
            'include_history': True, 'offset': 0, 'limit': 8})
        self.assertIn(result['ref'], [h['ref'] for h in search['hits']])
        old_search = self.call(ws, 'search_memory', {'archive_stage': 'SCI073-SERVICE-01', 'query': '',
            'kind': 'knowledge', 'include_history': True, 'offset': 0, 'limit': 8})
        hit = next(h for h in old_search['hits'] if h['ref'] == SOURCE)
        self.assertIn('UniqueRevisedAcquisitionRule', hit['preview'])
        self.assertEqual(ws.records('knowledge'), [])
        write_json(self.folder / 'actual_effective_view.json', view)

    def test_03_existing_valid_child_needs_explicit_acknowledgement_and_survives_reopen(self):
        ws = self.workspace()
        got, original, version = self.read_source(ws)
        source = got['materialized_original']['ref']
        brief = ws.file_ref(ws.public / 'business_brief.md', 'public_seen')['ref']
        h = self.call(ws, 'save_hypothesis', {'kind': 'data_quality',
            'statement': 'Engineering child cites the independently valid statement field.',
            'scope': 'Fixture only.', 'prediction': 'Fixture catalog lacks capacity2completion count.',
            'falsification': 'A received capacity2completion count.', 'alternatives': ['Such a counter exists.'],
            'evidence_refs': [source], 'used_memory_refs': [], 'effect_prediction': None})
        changed = self.checkpoint(ws, [self.action(version, [brief])], active=[h['ref']])
        self.assertIn('ref', changed, changed)
        self.assertTrue(ws.review(h['ref'])['explicit_dependency_reviews'])
        # A new summary/omitted source does not acknowledge the old child.
        self.assertIn('ref', self.checkpoint(ws, active=[h['ref']]))
        self.assertTrue(ws.review(h['ref'])['explicit_dependency_reviews'])
        acknowledged = self.checkpoint(ws, active=[h['ref']], reviews=[{'target_ref': h['ref'],
            'decision': 'restore', 'reason': 'Checked the still-valid statement field against received brief; unrelated research_use revision does not refute this child.',
            'evidence_refs': [brief]}])
        self.assertIn('ref', acknowledged, acknowledged)
        self.assertEqual(ws.review(h['ref'])['explicit_dependency_reviews'], [])
        root, question, settings = ws.root, ws.question, deepcopy(ws.settings)
        # Workspace stores environment.world, not a private source in role data.
        world = ws.environment.world
        ws.close()
        self.workspaces.remove(ws)
        reopened = ResearchWorkspace(root, question, world, settings, reopen=True)
        self.workspaces.append(reopened)
        self.assertEqual(reopened.review(h['ref'])['explicit_dependency_reviews'], [])
        self.assertEqual(reopened.effective_historical_view(SOURCE, version)['effective_text_fields']['research_use'], REPLACEMENT)
        self.assertEqual(reopened.record(h['ref'])['statement'], h['statement'])

    def test_04_stale_update_is_rejected_and_opinion_is_not_fact_evidence(self):
        ws = self.workspace()
        got, original, version = self.read_source(ws)
        brief = ws.file_ref(ws.public / 'business_brief.md', 'public_seen')['ref']
        first = self.checkpoint(ws, [self.action(version, [brief])])
        self.assertIn('ref', first, first)
        stale = self.checkpoint(ws, [self.action(version, [brief], replacement_text='Blind overwrite.')])
        self.assertFalse(stale['ok'])
        self.assertIn('stale historical field revision', stale['error'])
        note = ws.add('review_note', {'hypothesis_refs': [], 'statement': 'Engineering attributed opinion only.'})
        rejected = self.checkpoint(ws, [self.action(version, [note['ref']], expected_prior_revision_ref=first['ref'])])
        self.assertFalse(rejected['ok'])
        self.assertIn('not independent scientific evidence', rejected['error'])
        withdrawn = self.checkpoint(ws, [self.action(version, [brief], expected_prior_revision_ref=first['ref'],
            decision='withdraw', replacement_text=None)])
        self.assertIn('ref', withdrawn, withdrawn)
        self.assertNotIn('research_use', ws.effective_historical_view(SOURCE, version)['effective_text_fields'])
        self.assertEqual(ws.historical_original(SOURCE)[1], original)

    def test_05_normal_capacity_and_private_boundary_remain(self):
        ws = self.workspace()
        self.assertEqual(len(ws.tools), 16)
        self.assertLessEqual(len(encoded(ws.context()).encode()), 65536)
        budget = StudyBudget(self.folder / 'common_budget.sqlite', {'token_allowance': 1200000,
            'max_http_attempts': 0, 'project_budget_id': 'USER-20261022-CRITIC-10M'}, create=True)
        run = ResearchRun(self.folder, ws, ws.settings['model_config'], budget)
        runtime = ResearchRuntime(ws, ws.settings['model_config'], journal=run.journal)
        payload = runtime.payload(runtime.initial())
        self.assertEqual(payload['max_tokens'], 65536)
        self.assertEqual(payload['thinking']['type'], 'enabled')
        denied = self.call(ws, 'run_python', {'code': f'print(open({str(ROOT / "experiments/studies/SCI-076/scientific_audit.json")!r}).read())',
            'purpose': 'Actual external audit denial.'})
        self.assertFalse(denied['execution']['ok'])
        self.assertEqual(budget.snapshot()['http_attempts'], 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['GROWTH_V07_OUTPUT'] = str(args.output / 'cases')
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before == snapshot()
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'budget_unchanged': True,
        'scope': '5actual historical-field/source/read/search/impact/acknowledgement/reopen/stale/privacy controls, current workspace only. No scientific correctness, long-term effect or cross-new-stage export/import claim.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
