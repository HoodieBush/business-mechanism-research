import json,unittest
from ..composed_world import ComposedWorld
from ..critic_v01.shared import lifecycle
from ..paired_v02 import test_interface as fixtures
from ..paired_v07 import test_workflow as workflow
from ..test_acceptance import settings,FixtureJournal,raw_call
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun

class ResponseTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    assessed=fixtures.InterfaceTests.assessed
    save=fixtures.InterfaceTests.save
    budget=fixtures.InterfaceTests.budget
    issue=workflow.WorkflowTests.issue
    seeded=workflow.WorkflowTests.seeded
    reply=workflow.WorkflowTests.reply

    def make(self,mode,review_limit=18):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=fixtures.MODEL,
            workflow_policy={'max_lineage_reviews':4},execution_policy={'wall_seconds':7200,'warn_after_requests':8,'stop_after_requests':16,'review_http_limit':review_limit})
        config['limits'].update(token_allowance=3000000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','工程：窄回应与类型可发现性',ComposedWorld(),config);return self.ws

    def test_n01_direct_reply_both_modes_no_fabricated_state_and_idempotent(self):
        for mode in ['self','independent']:
            if mode!='self':self.make(mode)
            h,r,a,q=self.seeded();self.assertIsNone(self.ws.state())
            args=self.reply(q,r)
            first=self.ws.call('respond_to_review',args,'same');again=self.ws.call('respond_to_review',args,'same')
            self.assertEqual(first,again);self.assertEqual(len(self.ws.records('review_response')),1)
            self.assertIsNone(self.ws.record(first['ref'])['source_state_ref']);self.assertIsNone(self.ws.state());self.assertEqual(self.ws.unanswered(),[])
            with self.assertRaises(ValueError):self.ws.premise(first['ref'])

    def test_n02_accepting_does_not_repair_active_old_memory(self):
        k=self.save(knowledge_updates=[{'kind':'method','statement':'故意错误的工程旧方法','scope':'工程','status':'tentative','evidence_refs':[self.source()],'research_use':'回归'}])['knowledge_refs'][0]
        h,r,a,q=self.seeded(k);self.call('respond_to_review',self.reply(q,r,'accept'))
        self.assertEqual(self.ws.db.execute('SELECT open FROM review_issues WHERE review_ref=?',(q['ref'],)).fetchone()[0],1)
        self.assertTrue(lifecycle(self.ws.db,k)['eligible_as_current_premise'])
        self.save(memory_reviews=[{'target_ref':k,'decision':'withdraw','reason':'工程原件证明旧方法错误','evidence_refs':[r['ref']]}])
        self.assertFalse(lifecycle(self.ws.db,k)['eligible_as_current_premise'])
        self.assertEqual(self.ws.db.execute('SELECT open FROM review_issues WHERE review_ref=?',(q['ref'],)).fetchone()[0],0)

    def test_n03_opinion_as_evidence_and_unknown_issue_rejected_without_response(self):
        h,r,a,q=self.seeded();args=self.reply(q,r);args['evidence_refs']=[q['ref']]
        out=self.call('respond_to_review',args);self.assertFalse(out['ok'])
        args=self.reply(q,r);args['issue_id']='does_not_exist';self.assertFalse(self.call('respond_to_review',args)['ok'])
        self.assertEqual(self.ws.records('review_response'),[]);self.assertTrue(self.ws.unanswered())

    def test_n04_review_and_response_searchable_without_fact_promotion(self):
        h,r,a,q=self.seeded();b=self.call('respond_to_review',self.reply(q,r))
        for kind,ref in [('review',q['ref']),('review_response',b['ref'])]:
            found=self.call('search_memory',{'kind':kind});self.assertIn(ref,[x['ref'] for x in found['hits']])
            with self.assertRaises(ValueError):self.ws.premise(ref)
        self.assertEqual(len(self.ws.tools),14)

    def test_n05_same_policy_drives_context_job_and_actual_peer_capacity(self):
        self.make('independent',12);h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        self.assertEqual(job['review_http_limit'],12);ctx=self.ws.context();self.assertIn('allows12',ctx['review_policy']);self.assertNotIn('6later',ctx['review_policy'])
        def factory(peer,job):
            self.assertEqual(peer.settings['limits']['max_http_attempts'],12)
            def finish():
                action=peer.db.execute('SELECT ref FROM actions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                return raw_call('record_review',fixtures.review(a['ref'],action))
            return FixtureJournal([raw_call('query_data',{'sql':'SELECT count(*) FROM hourly','purpose':'真实SQL后的工程核验'}),finish])
        ResearchRun(self.folder/'independent',self.ws,fixtures.MODEL,self.budget(),reviewer_journal_factory=factory).review_job(job)
        self.assertEqual(self.ws.job(job['ref'])['status'],'completed')

    def test_n06_wrong_result_type_precise_feedback_never_rewrites_science(self):
        h,r,a=self.assessed();args={k:a[k] for k in ['hypothesis_ref','result_refs','status','prediction_coverage','rationale','deviations','counterevidence_refs','limitations']}
        file=self.source();args['result_refs']=[r['ref'],file];out=self.call('record_assessment',args)
        self.assertFalse(out['ok']);error=json.loads(out['error']);self.assertEqual(error['invalid_ref'],file);self.assertEqual(error['field'],'result_refs')
        self.assertEqual(len(self.ws.records('assessment')),1)

    def test_n07_runtime_can_reply_then_deliver_honest_engineering_report(self):
        h,r,a,q=self.seeded();self.save(pending_claim_refs=[a['ref']],incorporated_result_refs=[r['ref']])
        def finish():return raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['仅工程，争议保留'],'open_questions':['未决意见'],'measurement_requests':[]})
        def review():
            job=next(j for j in self.ws.jobs('pending') if self.ws.record(j['target_ref'])['record_type']=='report_draft')
            return raw_call('review_claim',{'job_ref':job['ref'],'review':fixtures.review(job['target_ref'],r['action_ref'])})
        owner=FixtureJournal([raw_call('respond_to_review',self.reply(q,r)),finish,review])
        out=ResearchRun(self.folder/'self',self.ws,fixtures.MODEL,self.budget(),owner_journal=owner).run(4)
        self.assertEqual(out['status'],'completed',out);self.assertEqual(len(self.ws.records('review_response')),1)
        self.assertEqual(self.ws.report()['deferred_opinion_refs'][0]['issue_id'],'scope')

if __name__=='__main__':unittest.main()
