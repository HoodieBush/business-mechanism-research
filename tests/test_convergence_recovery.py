"""Real task, paid cursor and context boundaries; never a provider call."""
from copy import deepcopy
import json
import sqlite3
import time
import unittest
from unittest.mock import patch
import test_agent_repairs as fixtures
from business_mechanism import convergence
from business_mechanism.context_window import compact
from business_mechanism.engine import ReviewerRuntime
from business_mechanism.allocations import review_allocation
from business_mechanism.method_coverage import coverage_report
from business_mechanism.recovery import authorize_window, recover_execution
from business_mechanism.service import open_project
from experiments.insight_research.common import encoded, write_json


class ConvergenceRecovery(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AgentRepairs(); self.fixture.setUp()
        self.ws=self.fixture.ws; self.backend=self.fixture.backend; self.project=self.fixture.project

    def tearDown(self): self.fixture.tearDown()

    def hypothesis(self, n=0, activation='active'):
        return self.ws.call('save_hypothesis', {'kind':'business','statement':'Finite fixture count '+str(n),
            'scope':'Only supplied observations','prediction':'The supplied table contains 1301 rows.',
            'falsification':'Any other exact count rejects this finite prediction.',
            'alternatives':['Source version differs.'],'evidence_refs':[],'activation':activation}, 'h-'+str(n))

    def close(self, h, outcome='inconclusive', **kw):
        return self.ws.call('close_hypothesis', {'hypothesis_ref':h['ref'],'outcome':outcome,
            'reason':'Fixture evidence is explicitly inadequate for a verified conclusion.',
            'evidence_refs':[], **kw}, 'close-'+h['ref']+'-'+outcome)

    def test_wip_backlog_and_terminal_endpoint_preserve_original(self):
        hs=[self.hypothesis(i) for i in range(3)]
        rejected=self.hypothesis(3); self.assertEqual(rejected['error_code'],'active_hypothesis_limit')
        backlog=self.hypothesis(4, 'backlog'); self.assertEqual(convergence.get(self.ws,backlog['ref'])['status'],'backlog')
        original=self.ws.record(hs[0]['ref']); self.close(hs[0])
        self.ws.call('focus_hypothesis',{'hypothesis_ref':backlog['ref']},'activate')
        self.assertEqual(len(convergence.active_refs(self.ws)),3)
        self.assertEqual(original,self.ws.record(hs[0]['ref']))
        self.assertFalse(self.ws.clearance(hs[0]['ref']))
        with self.assertRaisesRegex(ValueError,'terminal_hypothesis'):
            convergence.activate(self.ws,hs[0]['ref'])

    def test_unverified_positive_and_refutation_cannot_be_accepted(self):
        h=self.hypothesis()
        for outcome in ('accepted_in_scope','refuted'):
            result=self.close(h,outcome)
            self.assertFalse(result['ok']); self.assertIn('matching_cleared',result['error'])
        self.assertEqual(convergence.get(self.ws,h['ref'])['status'],'active')

    def test_goal_is_immutable_and_late_goal_is_not_preregistration(self):
        h=self.hypothesis(); goal={'hypothesis_ref':h['ref'],'claim_level':'descriptive',
            'success_criterion':'The exact count equals 1301 rows.',
            'falsification_criterion':'The exact count differs from 1301 rows.',
            'inconclusive_condition':'The data or computation cannot be verified.'}
        self.assertEqual(self.ws.call('set_hypothesis_goal',goal,'goal')['goal'],goal)
        failed=self.ws.call('set_hypothesis_goal',{**goal,'success_criterion':'Replace the criterion after observing data.'},'goal-edit')
        self.assertFalse(failed['ok']); self.assertIn('goal_frozen',failed['error'])

    def test_request_bound_closes_inconclusive_without_resetting_budget(self):
        h=self.hypothesis(); before=self.backend.budget.snapshot()
        for attempt in range(1,29): convergence.account_request(self.ws,attempt)
        blocked=self.ws.call('save_hypothesis',{'kind':'business','statement':'Another branch.',
            'scope':'Fixture','prediction':'Positive.','falsification':'Negative.',
            'alternatives':['Source is different.'],'evidence_refs':[]},'no-branch')
        self.assertEqual(blocked['error_code'],'hypothesis_closeout_due')
        with self.ws.db: endpoint=convergence.enforce_endpoints(self.ws)
        self.assertEqual(endpoint['outcome'],'inconclusive'); self.assertFalse(endpoint['verified_assessment'])
        self.assertEqual(before,self.backend.budget.snapshot())
        self.assertEqual(convergence.usage(self.ws,h['ref'])['requests'],28)

    def test_invalid_plan_drains_paid_batch_then_valid_call_and_replays(self):
        runtime=self.backend.runtime; runtime.cp['messages']=runtime.initial()
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'',
            'tool_calls':[{'id':'bad-plan','type':'function','function':{'name':'run_test','arguments':encoded({'plan_ref':'P7de5b791fa16ba9'})}},
                {'id':'good-query','type':'function','function':{'name':'query_data','arguments':encoded({'sql':'SELECT COUNT(*) FROM observations','purpose':'Recovery fixture exact count'})}}]}}]}
        runtime.accept(raw,delivery=1); before=self.backend.budget.snapshot()
        with patch('business_mechanism.transport.call_model',side_effect=AssertionError('No HTTP in batch drain')):
            runtime.run(0)
        outputs=[json.loads(m['content']) for m in runtime.cp['messages'] if m['role']=='tool']
        self.assertEqual(outputs[-2]['error_code'],'invalid_object_reference')
        self.assertEqual(outputs[-1]['preview'],[[1301]])
        self.assertIsNone(runtime.cp['pending']); self.assertEqual(before,self.backend.budget.snapshot())
        first=self.ws.call('run_test',{'plan_ref':'Pmissing'},'durable-rejection')
        self.assertEqual(first,self.ws.call('run_test',{'plan_ref':'Pmissing'},'durable-rejection'))
        with self.assertRaisesRegex(ValueError,'tool_operation_identity_conflict'):
            self.ws.call('run_test',{'plan_ref':'Pother'},'durable-rejection')

    def test_unexpected_value_error_is_still_a_hard_fault(self):
        with patch.object(self.ws,'_business_call',side_effect=ValueError('unexpected implementation defect')):
            with self.assertRaisesRegex(ValueError,'implementation defect'):
                self.ws.call('read_context',{},'unknown-defect')

    def test_large_latest_turn_can_archive_zero_recent_turns(self):
        runtime=self.backend.runtime; runtime.cp['messages']=runtime.initial()+[
            {'role':'assistant','content':'A'*600000}, {'role':'user','content':'Long exact turn remains in own archive.'}]
        runtime.cp['responses']=1; runtime.save()
        before=self.backend.budget.snapshot(); compact(runtime)
        self.assertEqual(runtime.cp['journal_recovery']['retained_complete_recent_turns'],0)
        archive=self.ws.private/'context_archives'/(runtime.cp['journal_recovery']['archive_id']+'.json')
        self.assertEqual(len(json.loads(archive.read_text())[2]['content']),600000)
        self.assertEqual(before,self.backend.budget.snapshot())

    def test_one_numeric_assertion_cannot_fake_seven_component_checks(self):
        op={'tool':'query_data','result':{'preview':[[42]]}}
        checks=[{'component':c,'action_ref':'q','output_pointer':'/preview/0/0','relation':'eq','expected':42}
                for c in ('claim_evidence','data_scope','sampling','estimator','numeric_claim')]
        result=coverage_report(checks,lambda _:op,required=[c['component'] for c in checks])
        self.assertFalse(result['clearance_eligible']); self.assertIn('estimator',result['missing_components'])

    def test_method_requirements_follow_applicability_before_review(self):
        from business_mechanism.workflow import spec_components
        spec={'claim_level':'association','sampling_mode':'census','grouping':{},'transformations':[],
              'required_components':['numeric_claim']}
        self.assertEqual(spec_components(spec),{'data_scope','numeric_claim','estimator'})
        spec.update(grouping={'g':'declared grouping'},transformations=['declared raw expansion'],sampling_mode='sampled')
        self.assertEqual(spec_components(spec),{'data_scope','numeric_claim','estimator','grouping','transformation','sampling'})

    def test_critic_has_final_submission_capacity_without_invalid_draft(self):
        peer,job,target=self.fixture.peer()
        try:
            peer.review_allocation=review_allocation(self.ws,self.backend.budget,job['ref'])
            from business_mechanism.transport import ExecutionJournal
            journal=ExecutionJournal(peer,self.fixture.model,self.backend.budget,'critic:'+job['ref'],memory=False,guard=self.backend.guard)
            journal.state['attempts']=10
            with patch.object(journal.guard,'admit',side_effect=__import__('experiments.insight_research.common',fromlist=['Pending']).Pending('stop before HTTP')):
                with self.assertRaisesRegex(Exception,'stop before HTTP'):journal.call({})
            runtime=ReviewerRuntime(peer,self.fixture.model,journal=journal); runtime.cp['messages']=runtime.initial()
            payload=runtime.prepare_payload(runtime.payload())
            names={s['function']['name'] for s in payload['tools']}
            self.assertIn('record_review',names); self.assertNotIn('run_python',names); self.assertNotIn('start_data_job',names)
        finally:peer.close()

    def test_verified_publication_has_bounded_closeout_without_faking_new_science(self):
        from business_mechanism.engine import Reviewer,source_identity
        from business_mechanism.transport import ExecutionJournal
        from experiments.insight_research.common import Pending,digest
        peer,job,target=self.fixture.peer()
        try:
            query=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Finite minimum fixture'},'min')
            args=fixtures.example('review_clean');args.update(source_refs=[target['ref']],
                checks_performed=[{'action_ref':query['action_ref'],'finding':'Exact synthetic minimum is zero.','artifact_refs':[]}],
                coverage_checks=[{'component':'claim_evidence','action_ref':query['action_ref'],'output_pointer':'/preview/0/0','relation':'eq','expected':0}])
            peer.call('record_review',args,'checked');self.backend.import_feedback(job,peer)
        finally:peer.close()
        with self.ws.db:
            draft=self.ws.add('report_draft',{'all_hypothesis_refs':[target['hypothesis_ref']],'all_plan_refs':[],
                'all_result_refs':[],'all_assessment_refs':[target['ref']],'assessment_refs':[target['ref']],
                'other_hypotheses':{},'limitations':['Fixture scope only.'],'stage_status':'inconclusive'})
        job=next(j for j in self.ws.jobs('pending') if j['target_ref']==draft['ref'])
        inputs=self.backend.prepare_job(job)
        peer=Reviewer(self.project/'reviews'/job['ref']/'critic',inputs,{'research_profile':'paired_critic_v1',
            'model_config':self.fixture.model,'limits':self.ws.settings['limits'],'release_sources':source_identity()})
        try:
            peer.review_allocation=review_allocation(self.ws,self.backend.budget,job['ref'])
            journal=ExecutionJournal(peer,self.fixture.model,self.backend.budget,'critic:'+job['ref'],memory=False,guard=self.backend.guard)
            self.backend.guard.inspect()
            payload={'model':'fixture','max_tokens':10,'messages':[{'role':'user','content':'Finite publication fixture'}]}
            for n in range(16):
                key='stable-'+str(n);self.backend.budget.reserve(key,'researcher',payload);self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
            with self.assertRaisesRegex(Pending,'semantic_stagnation'):self.backend.guard.admit(1)
            with patch('business_mechanism.transport.call_model',return_value={'response':{'choices':[{'message':{'role':'assistant','content':'fixture'},'finish_reason':'stop'}],'usage':{'total_tokens':17}}}) as model:
                journal.call(payload);journal.ack();self.assertEqual(model.call_count,1)
            self.assertGreaterEqual(self.backend.guard.inspect()['requests_without_structural_progress'],16)
            with self.ws.db:self.ws.db.execute('DELETE FROM clearances WHERE target=?',(target['ref'],))
            with patch('business_mechanism.transport.call_model',side_effect=AssertionError('Unverified findings cannot bypass guard')):
                with self.assertRaisesRegex(Pending,'semantic_stagnation'):journal.call(payload)
            journal.state['attempts']=peer.review_allocation['maximum_requests']
            with self.assertRaisesRegex(Pending,'review_execution_blocked'):journal.call(payload)
        finally:peer.close()

    def test_new_authorization_is_explicit_idempotent_and_keeps_costs(self):
        before=self.backend.budget.snapshot()
        receipt=authorize_window(self.project,seconds=86400,event_id='fixture-new-window',reason='Explicit finite fixture authorization.',max_stages=10000)
        self.assertGreater(receipt['deadline_unix'],time.time()+86390)
        self.assertEqual(receipt,authorize_window(self.project,seconds=86400,event_id='fixture-new-window',reason='Explicit finite fixture authorization.',max_stages=10000))
        self.assertEqual(json.loads((self.project/'project.json').read_text())['max_stages'],10000)
        self.assertEqual(before,self.backend.budget.snapshot())

    def test_worker_output_flood_is_bounded_and_not_a_successful_calculation(self):
        result=self.ws.worker.run("print('x'*3000000)",timeout=5)
        self.assertFalse(result['ok']); self.assertEqual(result['error_code'],'worker_output_limit')
        self.assertLessEqual(len(result['stdout']),12000)
        self.assertEqual(result['coverage'],'incomplete')

    def test_transient_backoff_and_new_slice_keep_total_failures_and_paid_budget(self):
        from business_mechanism.transport_recovery import cooldown,resume_transient_window
        from experiments.insight_research.common import Pending
        runtime=self.backend.runtime; journal=runtime.journal
        journal.state.update(attempts=3,inflight=None,delivery=None); journal.save()
        write_json(self.ws.private/'http/3.json',{'http_status':503,'error_type':'http'})
        before=self.backend.budget.snapshot()
        with self.assertRaisesRegex(Pending,'transport_cooldown'): cooldown(journal)
        marker=self.ws.private/'transport_cooldown.json'; value=json.loads(marker.read_text()); value['until_unix']=time.time()-1; write_json(marker,value)
        runtime.cp['transport_failures']=3; runtime.save()
        self.assertIsNone(resume_transient_window(runtime))
        self.assertEqual(runtime.cp['transport_failures'],0)
        self.assertEqual(runtime.cp['transport_failures_total_before_retry'],3)
        self.assertEqual(runtime.cp['transport_retry_windows'][0]['after_attempt'],3)
        self.assertEqual(journal.state['attempts'],3); self.assertEqual(before,self.backend.budget.snapshot())

    def test_sixty_paid_batch_replays_keep_errors_costs_and_bounded_context(self):
        from experiments.insight_research.common import digest
        runtime=self.backend.runtime; runtime.cp['messages']=runtime.initial()
        for number in range(1,61):
            payload={'model':'fixture','messages':[{'role':'user','content':'Already paid fixture batch '+str(number)}],'max_tokens':10}
            key=digest(['researcher',number]); self.backend.budget.reserve(key,'researcher',payload)
            self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
            raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'',
                'tool_calls':[{'id':'bad-'+str(number),'type':'function','function':{'name':'run_test','arguments':encoded({'plan_ref':'Pmissing'})}},
                    {'id':'read-'+str(number),'type':'function','function':{'name':'query_data','arguments':encoded({'sql':'SELECT COUNT(*) FROM observations','purpose':'Finite replay stress fixture'})}}]}}]}
            runtime.journal.state['attempts']=number; runtime.journal.save()
            write_json(self.ws.private/'http'/f'{number}.json',{'response':raw})
            runtime.accept(raw,delivery=number)
            with patch('business_mechanism.transport.call_model',side_effect=AssertionError('No provider during replay')):runtime.run(0)
            self.assertIsNone(runtime.cp['pending'])
            if number%10==0:compact(runtime)
        self.assertEqual(self.backend.budget.snapshot()['http_attempts'],60)
        self.assertEqual(self.backend.budget.snapshot()['reported_tokens'],1020)
        self.assertEqual(len(list((self.ws.science/'tool_errors').glob('*.json'))),60)
        self.assertLess(len(encoded(runtime.payload()).encode()),self.ws.settings['limits']['max_request_bytes']*.80)

    def test_migration_keeps_invalid_paid_call_for_rejection_without_http(self):
        from business_mechanism.migration import migrate_project_copy
        import business_mechanism
        runtime=self.backend.runtime; runtime.cp['messages']=runtime.initial()
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'',
            'tool_calls':[{'id':'paid-bad-plan','type':'function','function':{'name':'run_test','arguments':encoded({'plan_ref':'Pnot_received'})}}]}}], 'usage':{'total_tokens':17}}
        runtime.journal.state.update(attempts=1,inflight=None,delivery=None); runtime.journal.save()
        payload={'model':'fixture','messages':[{'role':'user','content':'Fixture paid instruction'}],'max_tokens':10}
        from experiments.insight_research.common import digest
        key=digest(['researcher',1]); self.backend.budget.reserve(key,'researcher',payload); self.backend.budget.settle(key,digest(payload),raw['usage'])
        write_json(self.ws.private/'http/1.json',{'response':raw}); runtime.accept(raw,delivery=1)
        before=self.backend.budget.snapshot(); destination=self.fixture.root/'migrated-paid'
        receipt=migrate_project_copy(self.project,destination,baseline_package=__import__('pathlib').Path(business_mechanism.__file__).parent,
                                    event_id='invalid-paid-migration',retain_invalid_paid_reference=True)
        self.assertEqual(len(receipt['retained_invalid_paid_batches']),1)
        _,_,new_ws,new_backend=open_project(destination)
        try:
            with patch('business_mechanism.transport.call_model',side_effect=AssertionError('No HTTP during paid migration drain')):
                new_backend.runtime.run(0)
            self.assertIsNone(new_backend.runtime.cp['pending']); self.assertEqual(before,new_backend.budget.snapshot())
            self.assertIsNotNone(json.loads(runtime.path.read_text())['pending'])
        finally:new_ws.close()

    def test_recovery_keeps_science_costs_and_does_not_reclose_another_hypothesis(self):
        h=self.hypothesis(); self.hypothesis(1); self.backend.runtime.cp['messages']=self.backend.runtime.initial(); self.backend.runtime.save()
        before=self.backend.budget.snapshot(); original=self.ws.records('hypothesis')
        receipt=recover_execution(self.project,reason='semantic_stagnation: fixture no new evidence',event_id='recovery-1')
        again=recover_execution(self.project,reason='semantic_stagnation: fixture no new evidence',event_id='recovery-1')
        self.assertEqual(receipt,again); self.assertEqual(before,self.backend.budget.snapshot())
        self.assertEqual(original,self.ws.records('hypothesis'))
        self.assertFalse(self.ws.clearance(h['ref']))
        self.assertEqual(len(convergence.active_refs(self.ws)),1)


if __name__=='__main__': unittest.main()
