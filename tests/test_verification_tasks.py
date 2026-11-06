"""A completed opinion is not a completed verification task or a science pass."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from business_mechanism.engine import Reviewer,source_identity
from business_mechanism import convergence
from business_mechanism.method_coverage import coverage_report
from business_mechanism.workflow import action_catalog
import test_agent_repairs as fixtures


class VerificationTasks(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AgentRepairs();self.fixture.setUp()
        self.ws=self.fixture.ws;self.backend=self.fixture.backend;self.project=self.fixture.project
    def tearDown(self):self.fixture.tearDown()

    def complete_fixture_review(self,peer,job,target,key):
        q=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Actual zero for temporal handoff fixture'},key+'-query')
        args=fixtures.example('review_clean');args.update(source_refs=[target['ref']],
            checks_performed=[{'action_ref':q['action_ref'],'finding':'Exact minimum is zero; no external observation is inferred.','artifact_refs':[]}],
            coverage_checks=[{'component':'claim_evidence','action_ref':q['action_ref'],'output_pointer':'/preview/0/0','relation':'eq','expected':0}])
        peer.call('record_review',args,key+'-review');self.backend.import_feedback(job,peer)

    def test_publication_handoff_releases_work_but_preserves_verified_unpublished_finding(self):
        from business_mechanism.workflow import close_stage
        from business_mechanism.verification_tasks import unpublished_findings,phase,initialize_handoffs
        peer,job,target=self.fixture.peer()
        try:self.complete_fixture_review(peer,job,target,'before-handoff')
        finally:peer.close()
        original=self.ws.record(target['ref']);before=self.backend.budget.snapshot()
        self.assertEqual(phase(self.ws),'deliver_verified_findings')
        with self.ws.db:
            outcome=close_stage(self.ws,outcome='unresolved',reason='Publication is blocked; original verified judgment remains valid.',
                unresolved_refs=[target['ref']],evidence_refs=[],key='publication-handoff')
            self.ws.db.execute('DELETE FROM meta WHERE key IN (?,?)',('release_publication_handoff:'+target['ref'],'release_execution_handoffs_initialized_v2'))
            initialize_handoffs(self.ws)
        self.assertEqual(phase(self.ws),'choose_next_goal')
        self.assertFalse(unpublished_findings(self.ws));deferred=unpublished_findings(self.ws,include_deferred=True)
        self.assertEqual(deferred[0]['publication_handoff']['stage_outcome_ref'],outcome['ref'])
        self.assertTrue(self.ws.clearance(target['ref']));self.assertFalse(self.ws.records('report'))
        self.assertEqual(original,self.ws.record(target['ref']));self.assertEqual(before,self.backend.budget.snapshot())

    def test_handoff_before_verification_cannot_defer_a_new_verified_result(self):
        from business_mechanism.workflow import close_stage
        from business_mechanism.verification_tasks import unpublished_findings,phase,initialize_handoffs
        peer,job,target=self.fixture.peer()
        try:
            with self.ws.db:
                convergence.close(self.ws,{'hypothesis_ref':target['hypothesis_ref'],'outcome':'inconclusive',
                    'reason':'Verification has not completed yet.','assessment_ref':None,'evidence_refs':[],
                    'successor_ref':None},'early-endpoint')
                close_stage(self.ws,outcome='unresolved',reason='The old execution slice ends before independent verification.',
                    unresolved_refs=[target['ref']],evidence_refs=[],key='early-handoff')
            self.complete_fixture_review(peer,job,target,'after-handoff')
            with self.ws.db:
                self.ws.db.execute('DELETE FROM meta WHERE key=?',('release_execution_handoffs_initialized_v2',))
                initialize_handoffs(self.ws)
            self.assertEqual(phase(self.ws),'deliver_verified_findings')
            self.assertTrue(unpublished_findings(self.ws))
            self.assertIsNone(unpublished_findings(self.ws,include_deferred=True)[0]['publication_handoff'])
        finally:peer.close()

    def test_completed_incomplete_review_can_revalidate_same_target_without_new_data(self):
        peer,job,target=self.fixture.peer()
        try:
            computed=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Finite original minimum check'},'min')
            args=fixtures.example('review_clean');args.update(target_conclusion='insufficient_evidence',source_refs=[target['ref']],
                checks_performed=[{'action_ref':computed['action_ref'],'finding':'Computed exact zero; coverage label omitted in the first slice.','artifact_refs':[]}],
                unchecked_scope=['Missing explicit numerical coverage assertion.'],coverage_checks=[])
            peer.call('record_review',args,'incomplete');self.backend.import_feedback(job,peer)
        finally:peer.close()
        old_review=self.ws.job(job['ref'])['review_ref'];before=self.backend.budget.snapshot()
        self.assertFalse(self.ws.clearance(target['ref']))
        old_h=convergence.get(self.ws,target['hypothesis_ref'])
        with self.ws.db:convergence.close(self.ws,{'hypothesis_ref':target['hypothesis_ref'],'outcome':'inconclusive',
            'reason':'Initial method coverage incomplete; original endpoint must remain in history.','assessment_ref':None,
            'evidence_refs':[],'successor_ref':None},'old-endpoint')
        old_endpoint=convergence.get(self.ws,target['hypothesis_ref'])['endpoint']
        readiness=self.ws.call('get_claim_readiness',{'target_ref':target['ref']},'ready')
        self.assertTrue(readiness['verification_followup']['eligible'])
        wrong=self.ws.call('request_revalidation',{'target_ref':target['ref'],'expected_review_ref':'Qwrong',
            'reason':'Explicit bounded method coverage repair.'},'wrong-parent')
        self.assertEqual(wrong['error_code'],'review_followup_version_conflict')
        request={'target_ref':target['ref'],'expected_review_ref':old_review,'reason':'Explicit bounded method coverage repair without changing scientific criteria.'}
        new=self.ws.call('request_revalidation',request,'revalidate')
        self.assertEqual(new,self.ws.call('request_revalidation',request,'revalidate'))
        duplicate=self.ws.call('request_revalidation',request,'duplicate-active')
        self.assertEqual(duplicate['error_code'],'review_already_active')
        for i in range(4):
            rejected=self.ws.call('finish_research',{'assessment_refs':[target['ref']],'other_hypotheses':{},
                'limitations':['Unverified finite fixture.'],'open_questions':[],'measurement_requests':[]},'old-delivery-'+str(i))
            self.assertFalse(rejected['ok'])
        from business_mechanism.graph import open_graph
        with open_graph(self.backend,thread_id='repair-priority') as graph:
            self.assertEqual(graph.select({})['route'],'critic')
        self.assertIsNone(self.ws.stage_outcome())
        new_job=self.ws.job(new['new_job_ref']);inputs=self.backend.prepare_job(new_job)
        peer=Reviewer(self.project/'reviews'/new_job['ref']/'critic',inputs,{'research_profile':'paired_critic_v1',
            'model_config':self.fixture.model,'limits':self.ws.settings['limits'],'release_sources':source_identity()})
        try:
            catalog=action_catalog(peer)
            self.assertTrue(any(a.get('origin')=='prior_directed_review' for a in catalog))
            previous=self.ws.record(old_review);prior=previous['checks_performed'][0]['action_ref']
            args=fixtures.example('review_clean');args.update(source_refs=[target['ref']],
                checks_performed=[{'action_ref':prior,'finding':'Reuse the explicitly allowed parent computation on unchanged inputs; not a new sample.','artifact_refs':[]}],
                coverage_checks=[{'component':'claim_evidence','action_ref':prior,'output_pointer':'/preview/0/0','relation':'eq','expected':0}])
            self.assertEqual(peer.call('record_review',args,'complete-repair')['phase'],'complete')
            self.backend.import_feedback(new_job,peer)
        finally:peer.close()
        self.assertTrue(self.ws.clearance(target['ref']))
        self.assertEqual(before,self.backend.budget.snapshot())
        self.assertEqual(len(self.ws.records('hypothesis')),1);self.assertEqual(len(self.ws.records('result')),0)
        final=convergence.get(self.ws,target['hypothesis_ref'])
        self.assertIn(old_endpoint,final['endpoint_history']);self.assertEqual(old_h['original_version'],final['original_version'])
        with self.ws.db:
            draft=self.ws.add('report_draft',{'all_hypothesis_refs':[target['hypothesis_ref']],'all_plan_refs':[],
                'all_result_refs':[],'all_assessment_refs':[target['ref']],'assessment_refs':[target['ref']],
                'other_hypotheses':{},'limitations':['Finite engineering fixture only.'],'stage_status':'inconclusive'})
        report_job=next(j for j in self.ws.jobs('pending') if j['target_ref']==draft['ref'])
        inputs=self.backend.prepare_job(report_job)
        peer=Reviewer(self.project/'reviews'/report_job['ref']/'critic',inputs,{'research_profile':'paired_critic_v1',
            'model_config':self.fixture.model,'limits':self.ws.settings['limits'],'release_sources':source_identity()})
        try:
            query=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Finite report cross-check'},'query')
            args=fixtures.example('review_clean');args.update(source_refs=[draft['ref']],
                checks_performed=[{'action_ref':query['action_ref'],'finding':'Finite checked record and exact minimum agree.','artifact_refs':[]}],
                coverage_checks=[{'component':'claim_evidence','action_ref':query['action_ref'],'output_pointer':'/preview/0/0','relation':'eq','expected':0}])
            peer.call('record_review',args,'report-check');self.backend.import_feedback(report_job,peer)
        finally:peer.close()
        with self.ws.db:self.ws.try_seal_report()
        self.assertIsNotNone(self.ws.report())
        from business_mechanism.service import advance_stage
        config=json.loads((self.project/'project.json').read_text());advance_stage(self.project,config,self.ws,self.backend)
        for refs in ([target['ref']],[]):
            rejected=self.ws.call('finish_research',{'assessment_refs':refs,'other_hypotheses':{},
                'limitations':['Repeat wording is not a new scope.'],'open_questions':[],'measurement_requests':[]},'republish-'+str(len(refs)))
            self.assertEqual(rejected['error_code'],'no_new_report_scope')
        self.assertEqual(len(self.ws.records('report_draft')),1)

    def test_disclosure_metadata_cannot_cover_numerical_or_other_report_claims(self):
        operation={'tool':'inspect_report_disclosure','result':{'target_ref':'D1','packet_digest':'p1',
            'checks':{'all_hypotheses_disclosed':True}}}
        check={'component':'record_fidelity','basis':'record_checked','action_ref':'audit',
            'output_pointer':'/checks/all_hypotheses_disclosed','relation':'eq','expected':True}
        good=coverage_report([check],lambda _:operation,required=['record_fidelity'],record_target='D1',record_packet_digest='p1')
        self.assertTrue(good['clearance_eligible']);self.assertFalse(good['scientific_certification'])
        for target,packet,component in [('D2','p1','record_fidelity'),('D1','p2','record_fidelity'),('D1','p1','numeric_claim')]:
            bad=coverage_report([{**check,'component':component}],lambda _:operation,required=[component],record_target=target,record_packet_digest=packet)
            self.assertFalse(bad['clearance_eligible'])

    def test_terminal_task_delivery_gets_only_four_extra_requests_without_reset(self):
        from experiments.insight_research.common import Pending,digest
        h=self.ws.call('save_hypothesis',{'kind':'data_quality','statement':'Finite replay fixture only.',
            'scope':'Synthetic supplied table','prediction':'Minimum is nonnegative.','falsification':'Any negative value.',
            'alternatives':['Measurement limits.'],'evidence_refs':[]},'h')
        with self.ws.db:convergence.close(self.ws,{'hypothesis_ref':h['ref'],'outcome':'inconclusive',
            'reason':'Fixture explicitly lacks an independently reviewed result.','assessment_ref':None,'evidence_refs':[],
            'successor_ref':None},'close')
        runtime=self.backend.runtime;runtime.cp['messages']=runtime.initial();payload=runtime.payload();self.backend.guard.inspect()
        for n in range(16):
            key='no-data-'+str(n);self.backend.budget.reserve(key,'researcher',payload);self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
        with self.assertRaisesRegex(Pending,'semantic_stagnation'):self.backend.guard.admit(1)
        response={'response':{'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'Finite closeout fixture.'}}],'usage':{'total_tokens':17}}}
        with patch('business_mechanism.transport.call_model',return_value=response) as provider:
            for _ in range(4):runtime.journal.call(payload);runtime.journal.ack()
            with self.assertRaisesRegex(Pending,'semantic_stagnation'):runtime.journal.call(payload)
            self.assertEqual(provider.call_count,4)
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM release_closeout_turns').fetchone()[0],4)
        self.assertGreaterEqual(self.backend.guard.inspect()['requests_without_structural_progress'],20)
        with patch('business_mechanism.workflow.stage_number',return_value=2):
            with self.assertRaisesRegex(Pending,'semantic_stagnation'):runtime.journal.call(payload)

    def test_bounded_critic_work_does_not_spend_researcher_progress_window(self):
        from experiments.insight_research.common import Pending,digest
        payload={'model':'fixture','max_tokens':10,'messages':[{'role':'user','content':'Role budget fixture.'}]}
        self.backend.guard.inspect()
        for n in range(24):
            key='critic-step-'+str(n);self.backend.budget.reserve(key,'critic:bounded-fixture',payload)
            self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
        state=self.backend.guard.admit(1)
        self.assertEqual(state['requests_without_structural_progress'],24)
        self.assertEqual(state['researcher_requests_without_structural_progress'],0)
        for n in range(16):
            key='root-step-'+str(n);self.backend.budget.reserve(key,'researcher',payload)
            self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
        with self.assertRaisesRegex(Pending,'semantic_stagnation'):self.backend.guard.admit(1)
        self.assertEqual(self.backend.budget.snapshot()['reported_tokens'],40*17)

    def test_unresolved_goal_handoff_ends_execution_without_science_clearance(self):
        from business_mechanism.verification_tasks import phase,pending_disclosures,undisclosed_endpoints
        h=self.ws.call('save_hypothesis',{'kind':'data_quality','statement':'Finite unavailable measurement.',
            'scope':'Fixture only','prediction':'Future count is positive.','falsification':'Future count is zero.',
            'alternatives':['Future data absent.'],'evidence_refs':[]},'unavailable-h')
        with self.ws.db:convergence.close(self.ws,{'hypothesis_ref':h['ref'],'outcome':'inconclusive',
            'reason':'Original future measurement is unavailable.','assessment_ref':None,'evidence_refs':[],
            'successor_ref':None},'unavailable-endpoint')
        original=self.ws.record(h['ref']);before=self.backend.budget.snapshot()
        self.assertEqual(phase(self.ws),'disclose_closed_goals')
        self.ws.call('close_research_stage',{'outcome':'unresolved','reason':'Measurement unavailable; explicit saved handoff.',
            'unresolved_refs':[h['ref']],'evidence_refs':[]},'handoff')
        self.assertEqual(phase(self.ws),'choose_next_goal')
        self.assertFalse(pending_disclosures(self.ws));self.assertEqual(len(undisclosed_endpoints(self.ws)),1)
        self.assertFalse(self.ws.clearance(h['ref']));self.assertFalse(self.ws.records('report'))
        self.assertEqual(original,self.ws.record(h['ref']));self.assertEqual(before,self.backend.budget.snapshot())
        from business_mechanism.service import advance_stage
        config=json.loads((self.project/'project.json').read_text());config['max_stages']=3
        advance_stage(self.project,config,self.ws,self.backend)
        self.assertEqual(phase(self.ws),'choose_next_goal')
        runtime=self.backend.runtime
        self.assertIn('save_hypothesis',{s['function']['name'] for s in runtime.prepare_payload(runtime.payload())['tools']})

    def test_compatible_migration_preserves_exact_verified_clearance(self):
        import shutil,business_mechanism
        from business_mechanism.migration import migrate_project_copy
        from business_mechanism.service import open_project
        peer,job,target=self.fixture.peer()
        try:
            query=peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Exact migration proof fixture'},'minimum')
            args=fixtures.example('review_clean');args.update(source_refs=[target['ref']],
                checks_performed=[{'action_ref':query['action_ref'],'finding':'Exact synthetic zero agrees with the fixed scope.','artifact_refs':[]}],
                coverage_checks=[{'component':'claim_evidence','action_ref':query['action_ref'],'output_pointer':'/preview/0/0','relation':'eq','expected':0}])
            peer.call('record_review',args,'verified');self.backend.import_feedback(job,peer)
        finally:peer.close()
        self.assertTrue(self.ws.clearance(target['ref']))
        baseline=self.fixture.root/'baseline'
        shutil.copytree(Path(business_mechanism.__file__).parent,baseline,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        destination=self.fixture.root/'upgraded';before=self.backend.budget.snapshot()
        receipt=migrate_project_copy(self.project,destination,baseline_package=baseline,event_id='verified-compatible-copy')
        self.assertEqual(len(receipt['exact_current_clearances_retained']),1)
        self.assertFalse(receipt['legacy_clearances_invalidated'])
        _,_,ws,backend=open_project(destination)
        try:
            self.assertTrue(ws.clearance(target['ref']));self.assertEqual(self.ws.record(target['ref']),ws.record(target['ref']))
            self.assertEqual(before,backend.budget.snapshot())
        finally:ws.close()

    def test_active_goal_has_finite_registered_work_slice_despite_old_global_stall(self):
        from experiments.insight_research.common import Pending,digest
        h=self.ws.call('save_hypothesis',{'kind':'data_quality','statement':'Finite goal work admission.',
            'scope':'Fixture only','prediction':'Minimum is zero.','falsification':'Minimum is negative.',
            'alternatives':['Data unavailable.'],'evidence_refs':[]},'bounded-goal')
        runtime=self.backend.runtime;runtime.cp['messages']=runtime.initial();payload=runtime.payload();self.backend.guard.inspect()
        for n in range(16):
            key='old-stall-'+str(n);self.backend.budget.reserve(key,'researcher',payload)
            self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
        response={'response':{'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'Finite goal fixture.'}}],'usage':{'total_tokens':17}}}
        with patch('business_mechanism.transport.call_model',return_value=response) as model:
            for _ in range(28):runtime.journal.call(payload);runtime.journal.ack()
            with self.assertRaisesRegex(Pending,'semantic_stagnation'):runtime.journal.call(payload)
            self.assertEqual(model.call_count,28)
        self.assertEqual(convergence.usage(self.ws,h['ref'])['requests'],28)
        self.assertEqual(self.backend.guard.inspect()['requests_without_structural_progress'],44)
        self.assertEqual(self.backend.budget.snapshot()['reported_tokens'],44*17)

    def test_explicit_new_authorization_grants_finite_window_without_erasing_old_stall(self):
        from business_mechanism.recovery import authorize_window
        from experiments.insight_research.common import Pending,digest
        payload={'model':'fixture','max_tokens':10,'messages':[{'role':'user','content':'Authorization fixture.'}]}
        self.backend.guard.inspect()
        def charge(prefix):
            for n in range(16):
                key=prefix+str(n);self.backend.budget.reserve(key,'researcher',payload)
                self.backend.budget.settle(key,digest(payload),{'total_tokens':17})
        charge('old-')
        with self.assertRaisesRegex(Pending,'semantic_stagnation'):self.backend.guard.admit(1)
        authorize_window(self.project,seconds=86400,event_id='explicit-new-work',reason='Explicit user-authorized intervention fixture.')
        state=self.backend.guard.admit(1)
        self.assertEqual(state['requests_without_structural_progress'],16)
        self.assertEqual(state['requests_since_explicit_authorization'],0)
        charge('new-')
        with self.assertRaisesRegex(Pending,'semantic_stagnation'):self.backend.guard.admit(1)
        self.assertEqual(self.backend.budget.snapshot()['reported_tokens'],32*17)


if __name__=='__main__':unittest.main()
