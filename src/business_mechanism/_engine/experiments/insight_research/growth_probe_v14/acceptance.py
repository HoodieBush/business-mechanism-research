"""Actual source/capacity/fallback checks for one retrieval component, zero API."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from ..common import ROOT, digest, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v13.workspace import ResearchWorkspace as Original
from ..review.workflow_20261025.quiescent_budget import snapshot
from .workspace import ResearchWorkspace

HERE = ROOT / 'experiments/insight_research/review/method_retrieval_20261101'
QUESTION = 'For the current service deployment, can the received records and lawful measurements establish whether register completeness at capacity2 meets the operator target of at least90%? Choose explanations and evidence yourself, keep scope and uncertainty explicit; prior research is scoped history, not current fact.'


def archives():
    return [json.loads(p.read_text())['archive'] for p in (
        ROOT / 'experiments/insight_research/review/growth_experience_20261031/history_provenance.json',
        ROOT / 'experiments/insight_research/review/partial_bound_followup_20261101/native_method_source/provenance.json',
        HERE / 'native_business_source/provenance.json')]


class Checks(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ['GROWTH_V14_OUTPUT']) / self._testMethodName
        self.workspaces = []

    def tearDown(self):
        for ws in self.workspaces:
            ws.close()

    def workspace(self, name, cls, question=QUESTION):
        cfg = config();cfg.update(verification_mode='self', experience_mode='episode', project_archives=archives())
        cfg['limits'].update(token_allowance=2000000, max_http_attempts=0)
        cfg['execution_policy']['closeout_reserve_tokens'] = 600000
        ws = cls(self.root / name / 'researcher', question, World(seed=4003, entry_rate=24,
            completion_probability=.4, recording_probability=.5), cfg)
        self.workspaces.append(ws)
        return ws

    def test_01_method_activation_preserves_same_public_native_sources_and_fixed_budget(self):
        original = self.workspace('original', Original)
        candidate = self.workspace('candidate', ResearchWorkspace)
        a = original.experience_context();b = candidate.experience_context()
        self.assertEqual(original.identity['public_inputs'], candidate.identity['public_inputs'])
        self.assertEqual(original.archive_descriptors(), candidate.archive_descriptors())
        self.assertEqual(len(original.received_history_rows), len(candidate.received_history_rows))
        self.assertEqual(original.received_history_rows, candidate.received_history_rows)
        self.assertEqual(original.records('hypothesis'), [])
        self.assertEqual(candidate.records('hypothesis'), [])
        self.assertEqual(candidate.records('knowledge'), [])
        self.assertEqual(candidate.records('state'), [])
        self.assertLessEqual(len(b['items']), 3)
        self.assertLessEqual(b['automatic_context_bytes'], 6144)
        self.assertEqual(b['automatic_context_cap'], a['automatic_context_cap'])
        item = b['items'][0]
        self.assertTrue(item['method_candidate_only'])
        stage, ref = item['ref'].split(':', 2)[1:]
        source = candidate.received_history_lookup[(stage, ref)]
        self.assertEqual(item['native_method_fields']['statement'], source['statement'])
        self.assertEqual(item['original_version'], digest(source))
        self.assertFalse(item['source_lifecycle']['eligible_as_current_premise'])
        self.assertFalse(item['source_lifecycle']['scientific_certification'])
        self.assertEqual(len(candidate.tools), len(original.tools))
        self.assertEqual(len(candidate.tools), 16)
        write_json(self.root / 'actual_source_contexts.json', {'original': a, 'candidate': b,
            'scope': 'Same sourceaccess andnormalcapacity; activation/presentation component differs. Not scientific superiority.'})

    def test_02_no_matching_native_method_falls_back_exactly(self):
        question = 'Quasar spectroscopic continuum emission spectroscopy cosmology.'
        original = self.workspace('original', Original, question)
        candidate = self.workspace('candidate', ResearchWorkspace, question)
        self.assertEqual(candidate.experience_context(), original.experience_context())

    def test_03_actual_method_source_read_does_not_create_current_scientific_facts(self):
        ws = self.workspace('candidate', ResearchWorkspace)
        item = ws.experience_context()['items'][0]
        got = ws.call('read_memory', {'ref': item['ref'], 'offset': 0, 'limit': 18000}, 'actual_native_method_read')
        self.assertIn('materialized_original', got)
        body = json.loads(got['text'])
        self.assertEqual(digest(body['original']), item['original_version'])
        self.assertIn('method', [t.lower() for t in body['original'].get('tags', [])])
        self.assertEqual(ws.records('hypothesis'), [])
        self.assertEqual(ws.records('knowledge'), [])
        # No hidden deployment parameter, Root evaluation or retraction repair
        # is inserted into a method statement by the selector.
        self.assertEqual(body['original']['statement'], item['native_method_fields']['statement'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);os.environ['GROWTH_V14_OUTPUT']=str(args.output/'cases')
    before=snapshot();result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before==snapshot()
    write_json(args.output/'acceptance.json',{'status':'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped),
        'new_paid_calls':0,'project_budget_unchanged':True,'scope':'3actual source/equalpublic/3slot6KB/nativefulltext/noautomaticfacts/exactfallback/read controls. Retrieval/presentation only, not method utility or longtermgrowth.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
