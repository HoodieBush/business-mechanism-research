"""Actual DB/sandbox controls for the smaller verification interface."""
import json,unittest
from ..paired_v01 import test_pairing as fixtures
MODEL,review=fixtures.MODEL,fixtures.review
from ..test_acceptance import settings,state,raw_call,FixtureJournal
from ..composed_world import ComposedWorld
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .review import Reviewer


class InterfaceTests(unittest.TestCase):
    setUp=fixtures.PairingTests.setUp
    tearDown=fixtures.PairingTests.tearDown
    call=fixtures.PairingTests.call
    source=fixtures.PairingTests.source
    assessed=fixtures.PairingTests.assessed
    save=fixtures.PairingTests.save
    budget=fixtures.PairingTests.budget

    def make(self,mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=MODEL)
        config['limits'].update(token_allowance=2000000,max_http_attempts=80,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','核验真实记录并持续研究',ComposedWorld(),config)
        return self.ws

    def test_i01_direct_self_review_cycle_keeps_existing_state(self):
        h,r,a=self.assessed();self.save(evidence_refs=[r['ref']],pending_claim_refs=[a['ref']]);old=self.ws.state()['ref']
        def verify(target):
            job=next(j for j in self.ws.jobs('pending') if j['target_ref']==target)
            return raw_call('review_claim',{'job_ref':job['ref'],'review':review(target,r['action_ref'])})
        def finish():return raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],'open_questions':[],'measurement_requests':[]})
        journal=FixtureJournal([lambda:verify(a['ref']),finish,lambda:verify(self.ws.records('report_draft')[-1]['ref'])])
        result=ResearchRun(self.folder/'self',self.ws,MODEL,self.budget(),owner_journal=journal).run(8)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(self.ws.state()['ref'],old);self.assertEqual(len(self.ws.records('review')),2)
        self.assertTrue(self.ws.report())

    def test_i02_independent_cannot_waive_with_direct_self_tool(self):
        self.make('independent');h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        result=self.call('review_claim',{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'])})
        self.assertFalse(result['ok']);self.assertFalse(self.ws.clearance(a['ref']))
        self.assertEqual(len(self.ws.tool_schemas()),13);self.assertEqual(self.ws.records('review'),[])

    def test_i03_wrong_hash_ref_has_same_precise_feedback_for_both_roles(self):
        h,r,a=self.assessed();source=self.ws.file(self.source())[0]
        from ..common import sha
        wrong='file:'+sha(source)
        run=ResearchRun(self.folder/'self',self.ws,MODEL,self.budget(),owner_journal=FixtureJournal([]))
        job=self.ws.jobs('pending')[0];inputs=run.prepare_job(job)
        reviewer=Reviewer(self.folder/'peer',inputs,{'limits':self.ws.settings['limits'],'model_config':MODEL})
        try:
            for actor in (self.ws,reviewer):
                with self.assertRaises(ValueError) as ctx:actor.references([wrong])
                err=json.loads(str(ctx.exception));self.assertEqual(err['invalid_ref'],wrong)
                self.assertEqual(err['matching_received_versions'][0]['ref'],self.source())
            with self.assertRaises(ValueError) as ctx:reviewer.references(['file:'+'0'*64])
            self.assertEqual(json.loads(str(ctx.exception))['matching_received_versions'],[])
            self.assertEqual(reviewer.records('review'),[])
        finally:reviewer.close()

    def test_i04_closeout_keeps_direct_review_and_reports_same_remaining_slice(self):
        h,r,a=self.assessed();run=ResearchRun(self.folder/'self',self.ws,MODEL,self.budget(),owner_journal=FixtureJournal([]))
        job=self.ws.jobs('pending')[0]
        with self.ws.db:self.ws.db.execute('INSERT INTO self_review_clock VALUES (?,?)',(job['ref'],0))
        run.runtime.cp['responses']=11;run.runtime.cp['resource_closeout']=True;self.ws.closeout_mode=True
        payload=run.runtime.prepare_payload(run.runtime.payload(run.runtime.initial()))
        names={t['function']['name'] for t in payload['tools']}
        self.assertTrue({'review_claim','read_memory','search_memory','query_data','run_python'}<=names)
        self.assertIn('还可请求1次',payload['messages'][-1]['content'])
        result=self.call('review_claim',{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'])})
        self.assertEqual(result['record_type'],'review');self.assertTrue(self.ws.clearance(a['ref']))

    def test_i05_independent_feedback_import_and_sealing_uses_same_backend(self):
        self.make('independent');h,r,a=self.assessed()
        self.save(evidence_refs=[r['ref']],pending_claim_refs=[a['ref']])
        def factory(reviewer,job):
            def finish():
                action=reviewer.db.execute('SELECT ref FROM actions ORDER BY rowid LIMIT 1').fetchone()[0]
                return raw_call('record_review',review(job['target_ref'],action),identifier='final')
            self.assertTrue(hasattr(reviewer,'study_budget'))
            return FixtureJournal([raw_call('read_memory',{'ref':job['target_ref']},identifier='read'),finish])
        def finish():return raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],'open_questions':[],'measurement_requests':[]})
        result=ResearchRun(self.folder/'independent',self.ws,MODEL,self.budget(),owner_journal=FixtureJournal([finish]),reviewer_journal_factory=factory).run(8)
        self.assertEqual(result['status'],'completed',result)
        self.assertTrue(all(q['author']=='independent_critic' for q in self.ws.records('review')))


if __name__=='__main__':unittest.main()
