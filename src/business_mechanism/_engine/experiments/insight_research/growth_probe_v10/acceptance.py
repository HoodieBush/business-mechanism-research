"""Actual field-target projection/Q/B/revision controls; scripted, zero API."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from ..common import ROOT, digest, write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v04.acceptance import HISTORY, QUESTION
from ..growth_probe_v07.acceptance import Checks as Helpers, SOURCE
from ..paired_v01.budget import StudyBudget
from ..paired_v01.test_pairing import review
from ..paired_v13.review import Reviewer
from ..review.workflow_20261025.quiescent_budget import snapshot
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun


class Checks(unittest.TestCase):
    call = Helpers.call
    checkpoint = Helpers.checkpoint
    action = Helpers.action

    def setUp(self):
        self.folder = Path(os.environ['GROWTH_V10_OUTPUT']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.workspaces = []
        self.number = 0

    def tearDown(self):
        for ws in self.workspaces:
            ws.close()

    def workspace(self, mode='self'):
        cfg = config()
        cfg.update(verification_mode=mode, experience_mode='recent',
            project_archives=[json.loads(HISTORY.read_text())['archive']])
        cfg['limits'].update(token_allowance=1200000, max_http_attempts=0)
        cfg['execution_policy']['closeout_reserve_tokens'] = 300000
        ws = ResearchWorkspace(self.folder / mode / 'researcher', QUESTION,
            World(seed=823, entry_rate=20, completion_probability=.4, recording_probability=1), cfg)
        self.workspaces.append(ws)
        return ws

    def candidate(self, ws, text='Engineering unvalidated field interpretation.'):
        got = self.call(ws, 'read_memory', {'ref': SOURCE, 'offset': 0, 'limit': 18000})
        original = json.loads(got['text'])['original']
        brief = ws.file_ref(ws.public / 'business_brief.md', 'public_seen')['ref']
        result = self.checkpoint(ws, [self.action(digest(original), [brief], replacement_text=text)])
        self.assertIn('ref', result, result)
        return result, original, brief

    def runner(self, ws):
        folder = ws.root.parent
        budget = StudyBudget(folder / 'common_budget.sqlite', {'token_allowance': 1200000,
            'max_http_attempts': 0, 'project_budget_id': 'USER-20261022-CRITIC-10M'}, create=True)
        return ResearchRun(folder, ws, ws.settings['model_config'], budget)

    def test_01_actual_state_target_and_projection_keep_original_kind(self):
        ws = self.workspace()
        candidate, original, brief = self.candidate(ws)
        jobs = [j for j in ws.jobs('pending') if j['target_ref'] == candidate['ref']]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(ws.delegated_jobs(), [])
        self.assertEqual(jobs[0]['target_version'], digest(ws.record(candidate['ref'])))
        self.assertTrue(candidate['review_choices'])
        run = self.runner(ws)
        inputs = run.prepare_job(jobs[0])
        packet = json.loads((inputs / 'packet.json').read_text())
        self.assertEqual(packet['target_kind'], 'state')
        self.assertEqual(packet['candidate_record'], ws.record(candidate['ref']))
        contrast = packet['field_revision_contrasts'][0]
        self.assertEqual(contrast['old_text'], original['research_use'])
        self.assertEqual(contrast['candidate_text'], 'Engineering unvalidated field interpretation.')
        self.assertFalse(contrast['scientific_certification'])
        with self.assertRaises(ValueError):
            ws.premise(candidate['ref'])
        self.assertEqual(run.budget.snapshot()['http_attempts'], 0)

    def test_02_independent_read_opinion_reply_and_actual_replacement(self):
        ws = self.workspace('independent')
        candidate, original, brief = self.candidate(ws)
        run = self.runner(ws)
        job = next(j for j in ws.jobs() if j['target_ref'] == candidate['ref'])
        requested = self.call(ws, 'request_review', {'job_ref': job['ref'], 'reason': 'Engineering explicit field review.'})
        self.assertEqual(requested['status'], 'scheduled')
        inputs = run.prepare_job(job)
        peer = Reviewer(self.folder / 'peer', inputs, {'research_profile': 'paired_critic_v1',
            'model_config': ws.settings['model_config'], 'limits': ws.settings['limits']})
        try:
            got = peer.call('read_artifact', {'ref': candidate['ref'], 'offset': 0, 'limit': 18000}, 'actual_field_read')
            self.assertIn('historical_field_reviews', got['text'])
            source = peer.call('read_artifact', {'ref': brief, 'offset': 0, 'limit': 12000}, 'actual_source_read')
            self.assertIn('NEW windows', source['text'])
            issue = {'issue_id': 'field_gap', 'description': 'Engineering candidate text has no supported source interpretation.',
                'type': 'missing_evidence', 'affected_refs': [candidate['ref']], 'basis': 'observed', 'blocking': True,
                'evidence_locations': [candidate['ref'] + '.historical_field_reviews[0].replacement_text'],
                'action_refs': [got['action_ref']], 'check_artifact_refs': [],
                'claim_impact': 'Do not use this unvalidated field as a strong premise.',
                'minimal_next_step': 'Provide an explicit source-linked field revision or retain unresolved.'}
            body = review(candidate['ref'], got['action_ref'], source_refs=[candidate['ref'], brief],
                target_conclusion='changes_needed', issues=[issue], open_issue_ids=['field_gap'])
            self.assertIn('ref', peer.call('record_review', body, 'engineering_opinion'))
            run.import_feedback(job, peer)
        finally:
            peer.close()
        q = ws.job(job['ref'])['review_ref']
        reply = self.call(ws, 'respond_to_review', {'review_ref': q, 'issue_id': 'field_gap',
            'disposition': 'accept', 'rationale': 'Engineering acknowledgement alone.',
            'evidence_refs': [brief], 'replacement_refs': [], 'object_reviews': []})
        self.assertIn('ref', reply, reply)
        self.assertTrue(ws.blocked(candidate['ref']))
        self.assertEqual(ws.effective_historical_view(SOURCE, digest(original))['effective_text_fields']['research_use'], 'Engineering unvalidated field interpretation.')
        with self.assertRaises(ValueError):
            ws.premise(candidate['ref'])
        replacement = self.checkpoint(ws, [self.action(digest(original), [brief],
            replacement_text='Engineering explicit corrected interpretation.', expected_prior_revision_ref=candidate['ref'])])
        self.assertIn('ref', replacement, replacement)
        next_job = next(j for j in ws.jobs() if j['target_ref'] == replacement['ref'])
        self.assertEqual(next_job['episode'], job['episode'])
        self.assertEqual(next_job['round'], 2)
        revised = self.call(ws, 'respond_to_review', {'review_ref': q, 'issue_id': 'field_gap',
            'disposition': 'revise', 'rationale': 'Engineering actual new field plus retirement of disputed old state.',
            'evidence_refs': [brief], 'replacement_refs': [replacement['ref']],
            'object_reviews': [{'target_ref': candidate['ref'], 'expected_version': None,
                'decision': 'quarantine', 'reason': 'Disputed old interpretation preserved but inactive.', 'evidence_refs': [brief]}]})
        self.assertIn('ref', revised, revised)
        self.assertFalse(ws.clearance(replacement['ref']))
        self.assertEqual(ws.effective_historical_view(SOURCE, digest(original))['effective_text_fields']['scope'], original['scope'])
        self.assertEqual(ws.effective_historical_view(SOURCE, digest(original))['effective_text_fields']['research_use'], 'Engineering explicit corrected interpretation.')
        with self.assertRaises(ValueError):
            ws.premise(replacement['ref'])
        self.assertEqual(run.budget.snapshot()['http_attempts'], 0)

    def test_03_self_packet_and_lineage_reopen_do_not_reset_or_autoinvoke(self):
        ws = self.workspace()
        candidate, original, brief = self.candidate(ws)
        job = next(j for j in ws.jobs() if j['target_ref'] == candidate['ref'])
        # Explicit re-enqueue of the same exact object is idempotent.
        self.assertEqual(ws.enqueue(candidate['ref']), job['ref'])
        run = self.runner(ws)
        inputs = run.prepare_job(job)
        self.assertEqual(ws.job_packet('job:' + job['ref'])['target_ref'], candidate['ref'])
        root, world, settings = ws.root, ws.environment.world, deepcopy(ws.settings)
        ws.close()
        self.workspaces.remove(ws)
        reopened = ResearchWorkspace(root, QUESTION, world, settings, reopen=True)
        self.workspaces.append(reopened)
        self.assertEqual(len(reopened.jobs()), 1)
        self.assertEqual(reopened.jobs()[0]['target_version'], job['target_version'])
        self.assertEqual(reopened.delegated_jobs(), [])
        self.assertEqual(json.loads((inputs / 'packet.json').read_text())['candidate_record'], reopened.record(candidate['ref']))

    def test_04_self_review_uses_same_exact_state_and_preserves_other_fields(self):
        ws = self.workspace()
        candidate, original, brief = self.candidate(ws)
        job = next(j for j in ws.jobs() if j['target_ref'] == candidate['ref'])
        self.call(ws, 'request_review', {'job_ref': job['ref'], 'reason': 'Engineering explicit self-verification.'})
        run = self.runner(ws)
        run.prepare_job(job)
        read = self.call(ws, 'read_memory', {'ref': candidate['ref'], 'offset': 0, 'limit': 18000})
        body = review(candidate['ref'], read['action_ref'], source_refs=[candidate['ref'], brief])
        result = self.call(ws, 'review_claim', {'job_ref': job['ref'], 'review': body})
        self.assertIn('ref', result, result)
        self.assertEqual(ws.job(job['ref'])['status'], 'completed')
        self.assertTrue(ws.clearance(candidate['ref']))
        ws.premise(candidate['ref'])
        view = ws.effective_historical_view(SOURCE, digest(original))
        self.assertEqual(view['effective_text_fields']['scope'], original['scope'])
        self.assertEqual(ws.record(ws.job(job['ref'])['review_ref'])['author'], 'researcher_self_check')
        self.assertEqual(run.budget.snapshot()['http_attempts'], 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['GROWTH_V10_OUTPUT'] = str(args.output / 'cases')
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before == snapshot()
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'budget_unchanged': True,
        'scope': '4actual fieldstatejob/projection/independentlegalread/scriptedQ/import/B/noautomaticrepair/newfield/lineage/selfpacket/selfsubmission/reopen controls. Engineering opinions only, no real-model or scientific benefit proof.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
