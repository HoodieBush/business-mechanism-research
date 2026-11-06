"""Business contracts, legacy delivery churn and safe stage closure regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import business_mechanism
from business_mechanism.engine import Reviewer, source_identity
from business_mechanism.service import advance_stage, open_project
from business_mechanism.workflow import review_contract
from business_mechanism.graph import open_graph
from business_mechanism.data_jobs import DataJobs, file_hash
from business_mechanism.migration import migrate_project_copy
from experiments.insight_research.common import Pending, digest, encoded, write_json
import test_agent_repairs as fixtures
example = fixtures.example


class WorkflowRobustness(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AgentRepairs(); self.fixture.setUp()
        self.ws = self.fixture.ws; self.backend = self.fixture.backend
        self.project = self.fixture.project; self.root = self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def business_target(self):
        h = self.ws.call('save_hypothesis', {'kind': 'business', 'statement': 'Synthetic nonnegative observed values.',
            'scope': 'Synthetic table only', 'prediction': 'Minimum is zero.', 'falsification': 'Any negative value.',
            'alternatives': ['Censoring'], 'evidence_refs': [], 'parent_ref': None}, 'business-h')
        with self.ws.db:
            target = self.ws.add('assessment', {'hypothesis_ref': h['ref'], 'result_refs': [], 'status': 'unresolved', 'rationale': 'Fixture contract target only.'})
        job = next(j for j in self.ws.jobs('pending') if j['target_ref'] == target['ref'])
        return h, target, job

    def spec(self, h):
        code = self.ws.science/'method.py'; code.write_text('SELECT MIN(value) FROM observations\n')
        source = self.ws.file_ref(self.ws.public/'business.sqlite'); file = self.ws.file_ref(code)
        return self.ws.call('register_analysis_spec', {'target_ref': h['ref'], 'spec': {
            'dataset_ref': source['ref'], 'filter': 'all', 'sampling': 'full supplied table', 'entity': ['id'],
            'grouping': {}, 'transformations': [], 'estimator': 'SQL minimum', 'uncertainty': 'descriptive only',
            'required_components': ['numeric_claim'], 'claim_level':'descriptive', 'sampling_mode':'census', 'code_ref': file['ref']}}, 'spec')

    def test_business_readiness_blocks_before_paid_review_and_repairs(self):
        h, target, job = self.business_target()
        before = self.backend.budget.snapshot()
        rejected = self.ws.call('request_review', {'job_ref': job['ref'], 'reason': 'Fixture business review'}, 'premature')
        self.assertEqual(rejected['error_code'], 'review_not_ready')
        direct = self.backend.critic_step(job)
        self.assertEqual(direct['execution_state'], 'blocked_execution')
        self.assertEqual(before, self.backend.budget.snapshot())
        self.assertFalse((self.project/'reviews'/job['ref']/'inputs').exists())
        self.spec(h)
        ready = self.ws.call('request_review', {'job_ref': job['ref'], 'reason': 'Ready now'}, 'delegate-ready')
        self.assertNotEqual(ready.get('ok'), False)
        self.assertFalse(self.ws.db.execute('SELECT 1 FROM release_task_state WHERE job=?', (job['ref'],)).fetchone())
        inputs = self.backend.prepare_job(job)
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.fixture.model,
                    'limits': self.ws.settings['limits'], 'release_sources': source_identity()}
        peer = Reviewer(self.project/'reviews'/job['ref']/'critic', inputs, settings)
        try:
            contract = peer.call('get_review_contract', {}, 'contract')['contract']
            self.assertTrue(contract['ready']); self.assertEqual(len(contract['required_components']), 3)
            query = peer.call('query_data', {'sql': 'SELECT MIN(value),COUNT(*) FROM observations', 'purpose': 'Fixture recomputation'}, 'query')
            args = example('review_clean')
            args.update(source_refs=[target['ref']], checks_performed=[{'action_ref': query['action_ref'],
                'finding': 'Synthetic minimum is zero; no real scientific certification.', 'artifact_refs': []}])
            args['coverage_checks'] = [{'component': c, 'action_ref': query['action_ref'],
                'output_pointer': '/preview/0/1' if c=='data_scope' else '/preview/0/0',
                'relation': 'eq', 'expected': 1301 if c=='data_scope' else 0.0} for c in contract['required_components']]
            wrong = deepcopy(args); wrong['coverage_checks'][0]['output_pointer'] = 'n'
            invalid = peer.call('validate_review_submission', {'raw_arguments': encoded(wrong)}, 'invalid')
            self.assertFalse(invalid['valid'])
            self.assertFalse(peer.call('record_review', wrong, 'reject-consistent')['ok'])
            self.assertFalse(peer.report())
            catalog = peer.call('get_review_contract', {}, 'paths')['computation_actions']
            self.assertIn('/preview/0/0', [p['output_pointer'] for a in catalog for p in a['actual_output_paths']])
            self.assertTrue(peer.call('validate_review_submission', {'raw_arguments': encoded(args)}, 'valid')['valid'])
            self.assertEqual(peer.call('record_review', args, 'commit-valid')['phase'], 'complete')
            self.backend.import_feedback(job, peer)
            self.assertTrue(self.ws.clearance(target['ref']))
        finally:
            peer.close()

    def test_spec_requires_actual_versioned_input_and_source_files(self):
        h, target, job=self.business_target()
        source=self.ws.file_ref(self.ws.public/'business.sqlite')
        code=self.ws.science/'not-code.csv';code.write_text('n\n1301\n');code_ref=self.ws.file_ref(code)
        spec={'dataset_ref':source['ref'],'code_ref':code_ref['ref'],'filter':'all','sampling':'full',
              'entity':[],'grouping':{},'transformations':[],'estimator':'minimum','uncertainty':'none',
              'required_components':['numeric_claim']}
        invalid=self.ws.call('register_analysis_spec',{'target_ref':h['ref'],'spec':spec},'wrong-code')
        self.assertFalse(invalid['ok']);self.assertIn('source_required',invalid['error'])
        spec['dataset_ref']=h['ref']
        invalid=self.ws.call('register_analysis_spec',{'target_ref':h['ref'],'spec':spec},'claim-as-data')
        self.assertFalse(invalid['ok']);self.assertIn('file_refs_required',invalid['error'])
        self.assertFalse(review_contract(self.ws,target['ref'])['ready'])

    def test_repeated_finish_has_one_draft_and_bounded_unresolved_exit(self):
        peer, job, target = self.fixture.peer(); peer.close()
        # Legacy report with no publication clearance, just as in the real run.
        with self.ws.db:
            draft = self.ws.add('report_draft', {'all_hypothesis_refs': [target['hypothesis_ref']], 'assessment_refs': [],
                'all_plan_refs': [], 'all_result_refs': [], 'all_assessment_refs': [target['ref']],
                'limitations': ['Fixture unresolved'], 'other_hypotheses': {target['hypothesis_ref']: 'unresolved'}})
        before_records = len(self.ws.records('report_draft'))
        before_jobs = sum(len(self.ws.jobs(s)) for s in ('pending', 'running', 'completed', 'exhausted'))
        args = {'assessment_refs': [], 'other_hypotheses': {target['hypothesis_ref']: 'unresolved'},
                'limitations': ['No publication clearance'], 'open_questions': [], 'measurement_requests': []}
        for i in range(4):
            result = self.ws.call('finish_research', {**args, 'limitations': ['wording revision '+str(i)]}, 'finish-'+str(i))
            self.assertEqual(result['error_code'], 'existing_stage_draft')
        self.assertEqual(len(self.ws.records('report_draft')), before_records)
        self.assertEqual(sum(len(self.ws.jobs(s)) for s in ('pending', 'running', 'completed', 'exhausted')), before_jobs)
        with open_graph(self.backend, thread_id='bounded') as graph:
            state = graph.select({})
            self.assertEqual(state['route'], 'deliver')
            delivered = graph.deliver(state)
        self.assertEqual(delivered['status'], 'stage_closed')
        self.assertFalse(delivered['result']['formal_report'])
        self.assertIsNone(self.ws.report())

    def test_legacy_draft_prose_changes_do_not_reset_progress(self):
        baseline = self.backend.guard.inspect()['requests_without_structural_progress']
        self.assertEqual(baseline, 0)
        for i in range(16):
            with self.ws.db:
                body = {'ref': 'D'+f'{i:016x}', 'record_type': 'report_draft',
                        'limitations': ['same limitation, rewritten '+str(i)], 'other_hypotheses': {'old': str(i)}}
                self.ws.db.execute('INSERT INTO records VALUES (?,?,?)', (body['ref'], 'report_draft', encoded(body)))
            payload = {'model': 'fixture', 'max_tokens': 10, 'messages': [{'role': 'user', 'content': 'local fixture only'}]}
            key = 'fixture-paid-'+str(i)
            self.backend.budget.reserve(key, 'researcher', payload)
            self.backend.budget.settle(key, digest(payload), {'total_tokens': 17})
            self.backend.guard.inspect()
        self.assertEqual(self.backend.guard.inspect()['requests_without_structural_progress'], 16)
        with self.assertRaisesRegex(Pending, 'semantic_stagnation'):
            self.backend.guard.admit(1)
        self.assertEqual(self.backend.budget.snapshot()['http_attempts'], 16)

    def test_batch_result_counts_as_progress_but_recompute_does_not(self):
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        before = self.backend.guard.fingerprint()
        for i in range(2):
            jobs.start('SELECT COUNT(*) FROM observations', [], 'interactive', source['snapshot_ref'], key='q'+str(i))
            result = jobs.run_next(remaining_seconds=40); self.ws.db.commit()
            self.assertEqual(result['status'], 'completed')
            after = self.backend.guard.fingerprint()
            if i == 0:
                self.assertNotEqual(after, before); first = after
            else:
                self.assertEqual(after, first)

    def test_result_paging_alias_becomes_exact_scientific_file_ref(self):
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        jobs.start('SELECT COUNT(*) FROM observations', [], 'interactive', source['snapshot_ref'], key='count')
        result = jobs.run_next(remaining_seconds=40); self.ws.db.commit()
        h = self.ws.call('save_hypothesis', {'kind': 'data_quality', 'statement': 'Fixture row count.',
            'scope': 'Synthetic table', 'prediction': '1301 rows.', 'falsification': 'Different count.',
            'alternatives': ['Source can change.'], 'evidence_refs': [result['result_ref']], 'parent_ref': None}, 'alias-h')
        self.assertTrue(h['evidence_refs'][0].startswith('file:'))
        receipt = next((self.ws.science/'reference_bindings').glob('*.json'))
        binding = json.loads(receipt.read_text())
        self.assertEqual(binding['bindings'][0]['requested_ref'], result['result_ref'])
        self.assertFalse(binding['scientific_text_changed'])

    def test_close_unresolved_retains_costs_and_never_grants_clearance(self):
        peer, job, target = self.fixture.peer(); peer.close()
        before = self.backend.budget.snapshot()
        args = {'outcome': 'unresolved', 'reason': 'Fixture requires new independent evidence.',
                'unresolved_refs': [target['ref']], 'evidence_refs': []}
        first = self.ws.call('close_research_stage', args, 'close-1')
        second = self.ws.call('close_research_stage', args, 'close-2')
        self.assertEqual(first['ref'], second['ref'])
        self.assertIsNone(first['formal_report_ref'])
        self.assertFalse(self.ws.clearance(target['ref']))
        self.assertEqual(self.backend.budget.snapshot(), before)

    def test_close_rejects_queued_compute_and_recovers_paid_close_cursor(self):
        jobs=DataJobs(self.ws);source=jobs.snapshot()
        job=jobs.start('SELECT COUNT(*) FROM observations',[],'interactive',source['snapshot_ref'],key='queued')
        args={'outcome':'unresolved','reason':'Fixture stage closure with no invented scientific clearance.', 'unresolved_refs':[], 'evidence_refs':[]}
        rejected=self.ws.call('close_research_stage',args,'premature-close')
        self.assertFalse(rejected['ok'])
        self.assertIn('finished_or_cancelled_compute',rejected['error'])
        jobs.cancel(job['job_ref'])
        closed=self.ws.call('close_research_stage',args,'close-durable')
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'',
             'tool_calls':[{'id':'replayed-close','type':'function','function':{'name':'close_research_stage','arguments':encoded(args)}}]}}]}
        runtime=self.backend.runtime;runtime.cp['messages']=runtime.initial();runtime.accept(raw,delivery=1)
        self.assertIsNotNone(runtime.cp['pending'])
        with patch('business_mechanism.transport.call_model',side_effect=AssertionError('No request after terminal closure')):
            result=runtime.run(1)
        self.assertEqual(result['status'],'stage_closed')
        self.assertEqual(result['stage_outcome']['ref'],closed['ref'])
        self.assertIsNone(runtime.cp['pending'])

    def test_three_empty_stage_exits_are_not_continuous_research(self):
        cfg = json.loads((self.project/'project.json').read_text()); cfg['max_stages'] = 5
        write_json(self.project/'project.json', cfg)
        for i in range(3):
            result = self.ws.call('close_research_stage', {'outcome': 'blocked',
                'reason': 'Fixture has no new computation or coverage.', 'unresolved_refs': [], 'evidence_refs': []}, 'close-'+str(i))
            self.assertIsNone(result['formal_report_ref'])
            if i < 2:
                self.assertTrue(advance_stage(self.project, cfg, self.ws, self.backend))
        with self.assertRaisesRegex(Pending, 'three closed stages'):
            self.backend.guard.admit(1)

    def test_copy_failure_leaves_fence_before_any_project_can_open(self):
        dest = self.root/'copy-interrupted'
        package = Path(business_mechanism.__file__).parent
        with patch('business_mechanism.migration.shutil.copytree', side_effect=OSError('fixture copy interrupted')):
            with self.assertRaisesRegex(OSError, 'copy interrupted'):
                migrate_project_copy(self.project, dest, baseline_package=package, event_id='copy-failure')
        self.assertTrue((dest/'migration_incomplete.json').exists())
        with self.assertRaisesRegex(ValueError, 'Migration is incomplete'):
            open_project(dest)

    def test_second_migration_does_not_rewrite_first_archive(self):
        self.fixture.test_explicit_baseline_copy_migration_preserves_original_and_reopens()
        source = self.root/'upgraded'
        old_identity = source/'migrations/test-upgrade/identities/researcher/private/identity.json'
        original = old_identity.read_bytes()
        dest = self.root/'upgraded-again'
        migrate_project_copy(source, dest, baseline_package=Path(business_mechanism.__file__).parent, event_id='second-upgrade')
        self.assertEqual((dest/old_identity.relative_to(source)).read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
