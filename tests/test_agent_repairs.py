"""Real sandbox and durable recovery regressions; no provider calls."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import os
import subprocess
import unittest
from unittest.mock import patch
from business_mechanism import create_project
from business_mechanism.service import open_project
from business_mechanism.engine import Reviewer, ReviewerRuntime, source_identity
from business_mechanism.data_jobs import DataJobs, PROFILES, file_hash
from business_mechanism.review_drafts import ReviewDrafts
from business_mechanism.allocations import allocate_review_requests, review_allocation
from business_mechanism.graph import open_graph
from business_mechanism.transport import ExecutionJournal
from business_mechanism.migration import migrate_project_copy
from experiments.insight_research.common import Pending, digest
from experiments.insight_research.prompt_runtime_v05.examples import examples


def example(label):
    return deepcopy(next(a for l, n, a in examples('critic') if l == label))


class AgentRepairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bmr-repair-')
        self.root = Path(self.temp.name)
        data = self.root/'data'; data.mkdir()
        with sqlite3.connect(data/'business.sqlite') as db:
            db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY,g INTEGER,value REAL)')
            db.executemany('INSERT INTO observations VALUES (?,?,?)', [(i, i % 7, (i % 19)*.5) for i in range(1301)])
        (data/'business_brief.md').write_text('Synthetic recovery fixture only.')
        (data/'data_dictionary.json').write_text('{}')
        self.model = {'model': 'fixture', 'base_url': 'http://127.0.0.1:1/v1', 'request_timeout_seconds': 1,
                      'generation_options': {'max_tokens': 1024}}
        self.project = self.root/'project'
        create_project(self.project, 'Synthetic recovery checks', self.model, data=data)
        _, _, self.ws, self.backend = open_project(self.project)

    def tearDown(self):
        self.ws.close(); self.temp.cleanup()

    def peer(self):
        h = self.ws.call('save_hypothesis', {'kind': 'data_quality', 'statement': 'Values are nonnegative.',
            'scope': 'Synthetic fixture', 'prediction': 'Minimum value is zero.',
            'falsification': 'A negative supplied value.', 'alternatives': ['The scale may be censored.'],
            'evidence_refs': [], 'parent_ref': None}, 'h')
        with self.ws.db:
            target = self.ws.add('assessment', {'hypothesis_ref': h['ref'], 'result_refs': [],
                'status': 'inconclusive', 'rationale': 'Synthetic target for contract tests; not a scientific finding.'})
        job = next(j for j in self.ws.jobs('pending') if j['target_ref'] == target['ref'])
        self.ws.call('request_review', {'job_ref': job['ref'], 'reason': 'Explicit fixture verification'}, 'delegate')
        inputs = self.backend.prepare_job(job)
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.model,
                    'limits': self.ws.settings['limits'], 'release_sources': source_identity()}
        peer = Reviewer(self.project/'reviews'/job['ref']/'critic', inputs, settings)
        return peer, job, target

    def test_full_query_global_semantics_and_versioned_pages(self):
        jobs = DataJobs(self.ws); profile = jobs.profile()
        for index, sql in enumerate([
            'SELECT g,AVG(value),COUNT(DISTINCT value) FROM observations GROUP BY g ORDER BY AVG(value) DESC,g',
            'SELECT DISTINCT value FROM observations ORDER BY value DESC',
            'SELECT id,g,value FROM observations WHERE value>=? ORDER BY id',
        ]):
            parameters = [3.5] if index == 2 else []
            queued = jobs.start(sql, parameters, 'interactive', profile['snapshot_ref'], key='q'+str(index))
            # A restart uses the same durable queue; no model turns are spent.
            done = DataJobs(self.ws).run_next(remaining_seconds=40)
            self.assertEqual(done['status'], 'completed', done)
            self.assertEqual(done['job_ref'], queued['job_ref'])
            rows = []; cursor = None
            while True:
                page = jobs.read(done['result_ref'], cursor, 13)
                self.assertEqual(page['coverage'], 'complete_for_declared_query')
                rows.extend(page['rows']); cursor = page['next_cursor']
                if not cursor: break
            with sqlite3.connect(self.ws.public/'business.sqlite') as db:
                expected = [list(r) for r in db.execute(sql, parameters)]
            self.assertEqual(rows, expected)
            self.assertLessEqual(len(json.dumps(page)), 25000)
        bad_cursor = __import__('base64').urlsafe_b64encode(json.dumps(['wrong-result', 1]).encode()).decode()
        with self.assertRaisesRegex(ValueError, 'version_conflict'):
            jobs.read(done['result_ref'], bad_cursor, 5)

    def test_runtime_finishes_queued_compute_before_next_model_turn(self):
        calls = []
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        def response(config, payload):
            calls.append(payload)
            if len(calls) == 1:
                name = 'start_data_job'
                args = {'snapshot_ref': source['snapshot_ref'], 'sql': 'SELECT id FROM observations ORDER BY id',
                        'parameters': [], 'resource_profile': 'interactive'}
            else:
                done = DataJobs(self.ws).jobs()[0]
                self.assertEqual(done['status'], 'completed')
                name = 'read_data_result'
                args = {'result_ref': done['result_ref'], 'cursor': None, 'limit': 2}
            raw = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': '',
                'tool_calls': [{'id': 'tool-'+str(len(calls)), 'type': 'function',
                                'function': {'name': name, 'arguments': json.dumps(args)}}]}}],
                'usage': {'total_tokens': 17}}
            return {'response': raw}
        with patch('business_mechanism.transport.call_model', side_effect=response):
            self.backend.runtime.run(1)
            self.assertEqual(jobs.jobs()[0]['status'], 'queued')
            self.backend.runtime.run(1)
            self.backend.runtime.run(0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.backend.budget.snapshot()['reported_tokens'], 34)
        tool = json.loads(self.backend.runtime.cp['messages'][-1]['content'])
        self.assertEqual(tool['rows'], [[0], [1]])

    def test_write_denied_and_cancel_preserves_incomplete(self):
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        jobs.start('DELETE FROM observations', [], 'interactive', source['snapshot_ref'], key='write')
        result = jobs.run_next(remaining_seconds=40)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['coverage'], 'incomplete')
        self.assertEqual(result['error']['error_code'], 'sql_error')
        queued = jobs.start('SELECT * FROM observations', [], 'interactive', source['snapshot_ref'], key='cancel')
        jobs.cancel(queued['job_ref'])
        self.assertEqual(jobs.get(queued['job_ref'])['status'], 'cancelled')
        self.assertIsNone(jobs.get(queued['job_ref'])['result_ref'])
        with sqlite3.connect(self.ws.public/'business.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 1301)

    def test_running_cancel_and_time_limit_are_typed(self):
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        sql = 'WITH RECURSIVE t(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM t WHERE x<1000000000) SELECT SUM(x) FROM t'
        queued = jobs.start(sql, [], 'interactive', source['snapshot_ref'], key='running-cancel')
        cancelled = threading.Event()
        def cancel():
            time.sleep(.15); jobs.cancel(queued['job_ref']); cancelled.set()
        thread = threading.Thread(target=cancel); thread.start()
        result = jobs.run_next(remaining_seconds=40); thread.join()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertEqual(result['coverage'], 'incomplete')
        jobs.start(sql, [], 'interactive', source['snapshot_ref'], key='timeout')
        with patch.dict(PROFILES, {'interactive': {**PROFILES['interactive'], 'seconds': 1}}):
            result = jobs.run_next(remaining_seconds=5)
        self.assertEqual(result['error']['error_code'], 'time_limit', result)
        self.assertIsNone(result['result_ref'])

    def test_disk_and_memory_limits_produce_incomplete_receipts(self):
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        jobs.start('SELECT id,value FROM observations', [], 'interactive', source['snapshot_ref'], key='disk-limit')
        with patch.dict(PROFILES, {'interactive': {**PROFILES['interactive'], 'disk_bytes': 8192}}):
            disk = jobs.run_next(remaining_seconds=40)
        self.assertEqual(disk['error']['error_code'], 'disk_limit', disk)
        self.assertEqual(disk['coverage'], 'incomplete')
        jobs.start('SELECT HEX(ZEROBLOB(100000000))', [], 'interactive', source['snapshot_ref'], key='memory-limit')
        with patch.dict(PROFILES, {'interactive': {**PROFILES['interactive'], 'memory_bytes': 32*1024*1024}}):
            memory = jobs.run_next(remaining_seconds=40)
        self.assertEqual(memory['error']['error_code'], 'memory_limit', memory)
        self.assertEqual(memory['coverage'], 'incomplete')

    def test_crashed_partial_attempt_reconciles_then_retries_without_mixing(self):
        jobs = DataJobs(self.ws); source = jobs.snapshot()
        item = jobs.start('SELECT id FROM observations ORDER BY id', [], 'interactive', source['snapshot_ref'], key='interrupted')
        partial = self.ws.science/'partial-injection'; partial.mkdir()
        with sqlite3.connect(partial/'result.sqlite') as db:
            db.execute('CREATE TABLE result_rows(n INTEGER PRIMARY KEY,payload TEXT)')
            db.execute("INSERT INTO result_rows VALUES(1,'[-999]')")
        (partial/'metrics.json').write_text(json.dumps({'status': 'partial', 'coverage': 'incomplete',
            'columns': ['id'], 'output_rows': 1, 'error': {'error_code': 'worker_interrupted'}}))
        item['status'] = 'running'
        item['attempts'] = [{'attempt': 1, 'status': 'running', 'directory': str(partial)}]
        jobs.save(item)
        recovered = jobs.run_next(remaining_seconds=40)
        self.assertEqual(recovered['status'], 'partial')
        self.assertIsNone(recovered['result_ref'])
        original = file_hash(partial/'result.sqlite')
        jobs.retry(item['job_ref'], key='retry-1'); jobs.retry(item['job_ref'], key='retry-1')
        complete = jobs.run_next(remaining_seconds=40)
        self.assertEqual(len(complete['attempts']), 2)
        self.assertEqual(complete['attempts'][-1]['output_rows'], 1301)
        self.assertEqual(jobs.read(complete['result_ref'], None, 2)['rows'], [[0], [1]])
        self.assertEqual(file_hash(partial/'result.sqlite'), original)

    def test_invalid_raw_draft_patch_cas_and_idempotent_commit(self):
        peer, job, h = self.peer()
        try:
            action = peer.call('query_data', {'sql': 'SELECT MIN(value) FROM observations', 'purpose': 'Independent minimum'}, 'query')
            args = example('review_clean')
            args.update(source_refs=[h['ref']], checks_performed=[{'action_ref': action['action_ref'], 'finding': 'Minimum is zero.', 'artifact_refs': []}])
            args['coverage_checks'] = [{'component': 'claim_evidence', 'action_ref': action['action_ref'],
                'output_pointer': '/preview/0/0', 'relation': 'eq', 'expected': 0.0}]
            args['comment'] = 'Must preserve this original unrecognized field.'
            runtime = ReviewerRuntime(peer, self.model, journal=self.backend.journal)
            runtime.cp['messages'] = runtime.initial()
            raw = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': '',
                'tool_calls': [{'id': 'bad', 'type': 'function', 'function': {'name': 'record_review', 'arguments': json.dumps(args)}}]}}]}
            runtime.accept(raw)
            self.assertIsNone(runtime.cp['pending'])
            drafts = ReviewDrafts(peer); draft = drafts.current()
            self.assertEqual(json.loads(draft['raw_arguments']), args)
            self.assertIn('/comment', [e['path'] for e in draft['validation_errors']])
            self.assertIn('repair_packet', runtime.prepare_payload(runtime.payload())['messages'][-1]['content'])
            changes = [{'op': 'remove', 'path': '/comment', 'value': None}]
            fixed = drafts.patch(draft['draft_ref'], draft['draft_hash'], changes, key='repair')
            replay = drafts.patch(draft['draft_ref'], draft['draft_hash'], changes, key='repair')
            self.assertEqual(fixed['draft_ref'], replay['draft_ref'])
            self.assertEqual(json.loads(fixed['raw_arguments'])['checks_performed'], args['checks_performed'])
            with self.assertRaisesRegex(ValueError, 'version_conflict'):
                drafts.patch(draft['draft_ref'], draft['draft_hash'], changes, key='stale')
            committed = peer.call('commit_review', {'draft_ref': fixed['draft_ref'], 'expected_hash': fixed['draft_hash']}, 'commit')
            self.assertEqual(committed['phase'], 'complete', committed)
            again = peer.call('commit_review', {'draft_ref': fixed['draft_ref'], 'expected_hash': fixed['draft_hash']}, 'different-delivery')
            self.assertEqual(committed, again)
            self.assertEqual(len(peer.records('review')), 1)
        finally:
            peer.close()

    def test_commit_batch_is_atomic_and_original_paid_message_is_preserved(self):
        peer, _, _ = self.peer()
        try:
            runtime = ReviewerRuntime(peer, self.model, journal=self.backend.journal)
            runtime.cp['messages'] = runtime.initial()
            raw = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': '',
                'tool_calls': [{'id': 'commit', 'type': 'function', 'function': {'name': 'commit_review',
                    'arguments': json.dumps({'draft_ref': 'unknown', 'expected_hash': 'unknown'})}},
                    {'id': 'query', 'type': 'function', 'function': {'name': 'query_data',
                     'arguments': json.dumps({'sql': 'SELECT COUNT(*) FROM observations', 'purpose': 'must not execute'})}}]}}]}
            runtime.accept(raw, delivery=1); runtime.accept(raw, delivery=1)
            self.assertEqual(runtime.cp['responses'], 1)
            self.assertIsNone(runtime.cp['pending'])
            self.assertEqual(peer.db.execute('SELECT COUNT(*) FROM actions').fetchone()[0], 0)
            self.assertEqual(json.loads((peer.private/'turns/1.json').read_text()), raw)
        finally:
            peer.close()

    def test_empty_affected_refs_stay_explicit_and_invalid(self):
        peer, _, h = self.peer()
        try:
            args = example('review_issue'); args['source_refs'] = [h['ref']]
            args['issues'][0]['affected_refs'] = []
            args['issues'].append({**deepcopy(args['issues'][0]), 'issue_id': 'SECOND'})
            draft = ReviewDrafts(peer).save(json.dumps(args), key='bad-refs')
            paths = [e['path'] for e in draft['validation_errors']]
            self.assertIn('/issues/0/affected_refs', paths)
            self.assertIn('/issues/1/affected_refs', paths)
            self.assertEqual(len(json.loads(draft['raw_arguments'])['issues']), 2)
            self.assertFalse(peer.report())
        finally:
            peer.close()

    def test_metadata_only_completed_review_does_not_clear_target(self):
        peer, job, target = self.peer()
        try:
            action = peer.call('read_memory', {'ref': target['ref'], 'offset': 0, 'limit': 1000}, 'metadata')
            args = example('review_clean')
            args.update(source_refs=[target['ref']], checks_performed=[{
                'action_ref': action['action_ref'], 'finding': 'Only read original target.', 'artifact_refs': []}])
            rejected = peer.call('record_review', args, 'metadata-consistent')
            self.assertFalse(rejected['ok'])
            self.assertIn('coverage_incomplete', rejected['error'])
            args['target_conclusion'] = 'insufficient_evidence'
            done = peer.call('record_review', args, 'review')
            self.assertEqual(done['phase'], 'complete')
            self.backend.import_feedback(job, peer)
            self.assertEqual(self.ws.job(job['ref'])['status'], 'completed')
            self.assertFalse(self.ws.clearance(target['ref']))
            review = self.ws.record(self.ws.job(job['ref'])['review_ref'])
            self.assertFalse(review['method_coverage']['clearance_eligible'])
        finally:
            peer.close()

    def test_analysis_spec_cannot_change_an_existing_hypothesis_review_snapshot(self):
        peer, _, target = self.peer()
        try:
            source = self.ws.file_ref(self.ws.public/'business.sqlite')
            code = self.ws.science/'spec-source.py'; code.write_text('print(0)\n')
            ref = self.ws.file_ref(code)
            result = self.ws.call('register_analysis_spec', {'target_ref': target['hypothesis_ref'], 'spec': {
                'dataset_ref': source['ref'], 'filter': 'all supplied rows', 'sampling': 'all', 'entity': [],
                'grouping': {}, 'transformations': [], 'estimator': 'SQL minimum', 'uncertainty': 'descriptive only',
                'required_components': ['numeric_claim'], 'code_ref': ref['ref']}}, 'late-spec')
            self.assertFalse(result['ok'])
            self.assertIn('analysis_spec_after_snapshot', result['error'])
        finally:
            peer.close()

    def test_blocked_job_does_not_hold_scheduler_and_allocation_is_additive(self):
        peer, job, _ = self.peer(); peer.close()
        with self.ws.db:
            self.ws.db.execute('INSERT INTO release_task_state VALUES (?,?,?)', (job['ref'], 'blocked_execution', 'fixture local cap'))
        before = self.backend.budget.snapshot()
        with open_graph(self.backend, thread_id='test') as graph:
            route = graph.select({})
            self.assertEqual(route['route'], 'researcher')
        grant = allocate_review_requests(self.project, job['ref'], 2, event_id='continuation-1', reason='Explicit repair fixture')
        again = allocate_review_requests(self.project, job['ref'], 2, event_id='continuation-1', reason='Explicit repair fixture')
        self.assertEqual(grant, again)
        self.assertEqual(grant['normal_requests'], 12)
        self.assertEqual(before, self.backend.budget.snapshot())
        with self.backend.budget.connect() as db:
            deadline = db.execute('SELECT deadline FROM execution_control').fetchone()[0]
        self.assertGreater(deadline, __import__('time').time())

    def test_local_cap_keeps_repair_reserve_and_never_resets_counts(self):
        peer, job, h = self.peer()
        try:
            peer.review_allocation = review_allocation(self.ws, self.backend.budget, job['ref'])
            journal = ExecutionJournal(peer, self.model, self.backend.budget, 'critic:'+job['ref'], memory=False, guard=self.backend.guard)
            journal.state['attempts'] = 10
            with patch.object(journal.guard, 'admit', side_effect=Pending('fixture closeout deadline')):
                with self.assertRaisesRegex(Pending, 'fixture closeout deadline'):
                    journal.call({})
            ReviewDrafts(peer).save('{"comment":"original invalid draft"}', key='draft')
            # At 10 a repair is admissible, but the shared deadline still gates
            # it. Stop before HTTP to prove reserve is not a counter reset.
            with patch.object(journal.guard, 'admit', side_effect=Pending('fixture deadline')):
                with self.assertRaisesRegex(Pending, 'fixture deadline'):
                    journal.call({})
            journal.state['attempts'] = 13
            with self.assertRaisesRegex(Pending, 'review_execution_blocked'):
                journal.call({})
            self.assertEqual(journal.state['attempts'], 13)
        finally:
            peer.close()

    def test_explicit_baseline_copy_migration_preserves_original_and_reopens(self):
        # The original installed environment is retained specifically for old
        # runs. No HTTP service is contacted by this source-bound fixture.
        repo = Path(__file__).resolve().parents[1]
        old_python = repo/'.venv/bin/python'
        baseline = repo/'.venv/lib/python3.12/site-packages/business_mechanism'
        if not old_python.exists() or not baseline.exists():
            self.skipTest('Optional original installed 0.1.5 source bundle unavailable')
        old_root = self.root/'old-project'
        script = '''import json,sys
from business_mechanism import create_project
from business_mechanism.service import open_project
root,data=sys.argv[1:]
model={'model':'fixture','base_url':'http://127.0.0.1:1/v1','request_timeout_seconds':1,'generation_options':{'max_tokens':1024}}
create_project(root,'Baseline migration fixture',model,data=data)
_,_,ws,b=open_project(root)
h=ws.call('save_hypothesis',{'kind':'data_quality','statement':'Original prediction retained.','scope':'Synthetic fixture','prediction':'Values nonnegative.','falsification':'A negative value.','alternatives':['Scale is censored.'],'evidence_refs':[],'parent_ref':None},'baseline-h')
with ws.db:
    target=ws.add('assessment',{'hypothesis_ref':h['ref'],'result_refs':[],'status':'inconclusive','rationale':'Fixture only.'})
job=next(j for j in ws.jobs('pending') if j['target_ref']==target['ref'])
ws.call('request_review',{'job_ref':job['ref'],'reason':'Synthetic baseline review'},'delegate')
inputs=b.prepare_job(job)
from business_mechanism.engine import Reviewer,ReviewerRuntime,source_identity
from business_mechanism.transport import ExecutionJournal
from experiments.insight_research.common import digest
from experiments.insight_research.prompt_runtime_v05.examples import examples
settings={'research_profile':'paired_critic_v1','model_config':model,'limits':{**ws.settings['limits'],'max_http_attempts':10},'release_sources':source_identity()}
peer=Reviewer(b.root/'reviews'/job['ref']/'critic',inputs,settings)
journal=ExecutionJournal(peer,model,b.budget,'critic:'+job['ref'],memory=False,guard=b.guard)
rt=ReviewerRuntime(peer,model,journal=journal);rt.cp['messages']=rt.initial()
args=next(a for label,name,a in examples('critic') if label=='review_clean')
args={**args,'source_refs':[target['ref']],'comment':'Original invalid comment retained.'}
for i in range(1,11):
    payload=rt.payload();key=digest(['critic:'+job['ref'],i]);bound=b.budget.reserve(key,'critic:'+job['ref'],payload)
    raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'','tool_calls':[{'id':'bad-'+str(i),'type':'function','function':{'name':'record_review','arguments':json.dumps(args)}}]}}],'usage':{'total_tokens':17}}
    journal.persist_request(i,payload);journal.persist_response(i,{'response':raw});b.budget.settle(key,digest(payload),raw['usage'])
    rt.accept(raw,delivery=i)
journal.state.update(attempts=10,accounted_tokens=170,inflight=None,delivery=None);journal.save()
peer.close()
ws.close()
'''
        subprocess.run([str(old_python), '-c', script, str(old_root), str(self.root/'data')],
                       env={**os.environ, 'PYTHONPATH': ''}, check=True, capture_output=True, text=True)
        original = (old_root/'project.json').read_bytes()
        records_before = (old_root/'researcher/private/records.sqlite').read_bytes()
        result = migrate_project_copy(old_root, self.root/'upgraded', baseline_package=baseline, event_id='test-upgrade')
        self.assertEqual((old_root/'project.json').read_bytes(), original)
        self.assertEqual((old_root/'researcher/private/records.sqlite').read_bytes(), records_before)
        self.assertTrue(result['all_budget_rows_and_original_deadline_preserved'])
        _, _, ws, backend = open_project(self.root/'upgraded')
        try:
            self.assertEqual(ws.records('hypothesis')[0]['statement'], 'Original prediction retained.')
            self.assertEqual(backend.budget.snapshot()['http_attempts'], 10)
            self.assertEqual(backend.budget.snapshot()['reported_tokens'], 170)
            self.assertTrue((self.root/'upgraded/pause_requested.json').exists())
            job = ws.jobs('pending')[0]
            result = backend.critic_step(job, model_steps=0)
            self.assertEqual(result['status'], 'pending')
            draft_path = self.root/'upgraded/reviews'/job['ref']/'critic/private/review_drafts.sqlite'
            with sqlite3.connect(draft_path) as db:
                draft = json.loads(db.execute('SELECT body FROM drafts LIMIT 1').fetchone()[0])
            self.assertIn('Original invalid comment retained.', draft['raw_arguments'])
            self.assertEqual(backend.budget.snapshot()['http_attempts'], 10)
        finally:
            ws.close()


if __name__ == '__main__':
    unittest.main()
