import json,unittest
from pathlib import Path
from unittest.mock import patch
from ..common import Pending,digest,encoded
from ..composed_world import ComposedWorld
from ..test_acceptance import settings,state,raw_call,FixtureJournal
from ..paired_v02 import test_interface as fixtures
from ..critic_v01.shared import lifecycle
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .guard import ProgressGuard,GuardedJournal

class WorkflowTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    assessed=fixtures.InterfaceTests.assessed
    save=fixtures.InterfaceTests.save
    budget=fixtures.InterfaceTests.budget

    def make(self,mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=fixtures.MODEL,
            workflow_policy={'max_lineage_reviews':4},execution_policy={'wall_seconds':7200,'warn_after_requests':8,'stop_after_requests':16})
        config['limits'].update(token_allowance=3000000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','工程控制：反馈先回应与逐版本审查',ComposedWorld(),config)
        return self.ws

    def issue(self,ref,blocking=False):
        return {'issue_id':'scope','type':'methodological_disagreement','description':'保留工程范围疑点','affected_refs':[ref],
                'basis':'observed','blocking':blocking,'evidence_locations':[ref],'action_refs':[],'check_artifact_refs':[],
                'claim_impact':'工程夹具不是科学认证','minimal_next_step':'依据原件回应'}

    def seeded(self,issue_target=None):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        body=fixtures.review(a['ref'],r['action_ref'],issues=[self.issue(issue_target or a['ref'])],open_issue_ids=['scope'])
        with self.ws.db:q=self.ws.apply_review(job['ref'],body,author='scripted_engineering')
        return h,r,a,q

    def reply(self,q,r,disposition='defer',replacement_refs=None):
        return {'review_ref':q['ref'],'issue_id':'scope','disposition':disposition,'rationale':'实际原件支持的保留或修订理由',
                'evidence_refs':[r['ref']],'replacement_refs':replacement_refs or []}

    def test_w01_opinion_requires_response_but_checkpoint_stays_available(self):
        h,r,a,q=self.seeded()
        self.assertFalse(self.ws.clearance(a['ref']))
        result=self.call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],'open_questions':[],'measurement_requests':[]})
        self.assertFalse(result['ok']);self.assertIn('explicit evidence-linked',result['error'])
        s=self.save(pending_claim_refs=[a['ref']]);self.assertIn('ref',s);self.assertEqual(len(self.ws.unanswered()),1)

    def test_w02_defer_is_valid_trace_and_does_not_claim_issue_resolved(self):
        h,r,a,q=self.seeded();saved=self.save(review_responses=[self.reply(q,r)])
        self.assertEqual(len(saved['response_refs']),1);self.assertEqual(self.ws.unanswered(),[]);self.assertTrue(self.ws.clearance(a['ref']))
        draft=self.call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围，争议尚未解决'],'open_questions':[],'measurement_requests':[]})
        d=self.ws.record(draft['ref']);self.assertEqual(d['deferred_opinion_refs'][0]['issue_id'],'scope')
        self.assertEqual(self.ws.db.execute("SELECT open FROM review_issues WHERE review_ref=?",(q['ref'],)).fetchone()[0],1)
        with self.ws.db:
            job=next(j for j in self.ws.jobs('pending') if j['target_ref']==d['ref'])
            self.ws.apply_review(job['ref'],fixtures.review(d['ref'],r['action_ref']),author='scripted_engineering')
            self.ws.try_seal_report()
        self.assertEqual(self.ws.report()['deferred_opinion_refs'][0]['response_ref'],saved['response_refs'][0])

    def test_w03_wrong_old_memory_does_not_block_correct_unrelated_assessment(self):
        k=self.save(knowledge_updates=[{'kind':'method','statement':'工程待审旧方法','scope':'旧用途','status':'tentative','evidence_refs':[self.source()],'research_use':'夹具'}])['knowledge_refs'][0]
        h,r,a,q=self.seeded(k);self.assertTrue(self.ws.clearance(a['ref']))
        self.assertEqual(self.ws.unanswered({a['ref']}),[]);self.assertEqual(self.ws.unanswered({k})[0]['issue_id'],'scope')

    def test_w04_four_versions_reviewable_without_automatic_clearance_fifth_exhausted(self):
        h,r,a=self.assessed()
        for n in range(1,6):
            job=next(j for j in self.ws.jobs() if j['target_ref']==a['ref'])
            self.assertEqual(job['round'],n);self.assertEqual(job['status'],'pending' if n<=4 else 'exhausted')
            self.assertFalse(self.ws.clearance(a['ref']))
            if n==5:break
            with self.ws.db:self.ws.apply_review(job['ref'],fixtures.review(a['ref'],r['action_ref']),author='scripted_engineering')
            a=self.call('record_assessment',{'hypothesis_ref':h['ref'],'result_refs':[r['ref']],'status':'unresolved',
                'prediction_coverage':'工程版本'+str(n),'rationale':'声明改变仍须核验','deviations':[],'counterevidence_refs':[],
                'limitations':['不是科学效果'],'supersedes_assessment_ref':a['ref']})

    def test_w05_owner_response_precedes_independent_recheck_and_delta_packet(self):
        self.make('independent');h,r,a,q=self.seeded()
        revised=self.call('record_assessment',{'hypothesis_ref':h['ref'],'result_refs':[r['ref']],'status':'unresolved',
            'prediction_coverage':'工程修订','rationale':'保留适用范围','deviations':[],'counterevidence_refs':[],
            'limitations':['工程夹具'],'supersedes_assessment_ref':a['ref']})
        reply=self.reply(q,r,'revise',[revised['ref']])
        owner=FixtureJournal([raw_call('update_research_state',state(active_hypothesis_refs=[h['ref']],focus_hypothesis_refs=[h['ref']],
            incorporated_result_refs=[r['ref']],pending_claim_refs=[revised['ref']],review_responses=[reply]))])
        def peer_factory(peer,job):
            self.assertEqual(len(self.ws.records('review_response')),1)
            packet=peer.packet;self.assertEqual(len(packet['researcher_responses']),1)
            self.assertEqual(packet['workflow_delta']['previous_object_ref'],a['ref'])
            self.assertIn('rationale',packet['workflow_delta']['changed_fields'])
            def complete():
                check=peer.db.execute('SELECT ref FROM actions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                return raw_call('record_review',fixtures.review(revised['ref'],check))
            return FixtureJournal([raw_call('query_data',{'sql':'SELECT count(*) FROM hourly','purpose':'实际核验'}),complete])
        run=ResearchRun(self.folder/'independent',self.ws,fixtures.MODEL,self.budget(),owner_journal=owner,reviewer_journal_factory=peer_factory)
        run.run(2);self.assertTrue(self.ws.clearance(revised['ref']))

    def test_w06_embedded_self_review_cannot_bypass_response(self):
        h,r,a,q=self.seeded()
        s=self.save(self_reviews=[{'job_ref':q['job_ref'],'review':fixtures.review(a['ref'],r['action_ref'])}])
        self.assertTrue(s['review_rejections']);self.assertEqual(len(self.ws.records('review')),1)

    def test_w07_replaced_report_draft_marked_superseded(self):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        with self.ws.db:self.ws.apply_review(job['ref'],fixtures.review(a['ref'],r['action_ref']),author='scripted_engineering')
        self.save()
        body={'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],'open_questions':[],'measurement_requests':[]}
        d1=self.call('finish_research',body);d2=self.call('finish_research',{**body,'limitations':['工程修订范围'],'supersedes_draft_ref':d1['ref']})
        self.assertIn('ref',d2);self.assertFalse(lifecycle(self.ws.db,d1['ref'])['eligible_as_current_premise'])

    def test_w08_wall_deadline_persists_and_rejects_before_new_request(self):
        budget=self.budget();clock=[1000.];guard=ProgressGuard(self.folder/'self',self.ws,budget,clock=lambda:clock[0])
        deadline=guard.inspect()['deadline_unix'];clock[0]+=300
        again=ProgressGuard(self.folder/'self',self.ws,budget,clock=lambda:clock[0]);self.assertEqual(again.inspect()['deadline_unix'],deadline)
        clock[0]=deadline-100
        with self.assertRaisesRegex(Pending,'persistent study wall'):again.admit(600)
        self.assertEqual(budget.snapshot()['http_attempts'],0)

    def test_w09_no_structural_progress_pause_and_meaningful_checkpoint_recovery(self):
        budget=self.budget();guard=ProgressGuard(self.folder/'self',self.ws,budget,clock=lambda:1000.);guard.inspect()
        payload={'model':fixtures.MODEL['model'],'max_tokens':65536,'messages':[]}
        for n in range(16):
            budget.reserve(str(n),'engineering',payload);budget.settle(str(n),digest(payload),{'total_tokens':0})
        with self.assertRaisesRegex(Pending,'no-structural-progress'):guard.admit(600)
        self.save(understanding='新的有来源检查点，明确尚无结论及下一步');self.assertEqual(guard.admit(600)['requests_without_structural_progress'],0)
        first=guard.fingerprint();self.save(understanding='新的有来源检查点，明确尚无结论及下一步');self.assertEqual(guard.fingerprint(),first)

    def test_w10_expired_guard_recovers_original_paid_response_once(self):
        budget=self.budget();clock=[1000.];guard=ProgressGuard(self.folder/'self',self.ws,budget,clock=lambda:clock[0])
        journal=GuardedJournal(self.ws,fixtures.MODEL,budget,'researcher',memory=True,guard=guard)
        payload={'model':fixtures.MODEL['model'],'max_tokens':65536,'messages':[{'role':'system','content':'engineering'},{'role':'user','content':'{}'}]}
        key=digest(['researcher',1]);bound=budget.reserve(key,'researcher',payload)
        journal.state.update(attempts=1,inflight={'attempt':1,'request_hash':digest(payload),'reservation':bound,'study_key':key})
        journal.persist_request(1,payload);journal.persist_response(1,{'response':{'choices':[],'usage':{'total_tokens':11}}});journal.save()
        clock[0]=guard.inspect()['deadline_unix']+1
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no new provider call')):
            result=journal.call({'messages':[]});journal.call({'messages':[]})
        self.assertEqual(result['response']['usage']['total_tokens'],11);self.assertEqual(budget.snapshot()['accounted_tokens'],11)
        journal.ack()
        with self.assertRaises(Pending):journal.call(payload)
        self.assertEqual(budget.snapshot()['http_attempts'],1)

    def test_w11_real_provided_science_and_review_import_same_public_input(self):
        from ..common import ROOT
        from ..paired_v01.initialization import import_initial
        from .run import initialize_review
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode='independent',model_config=fixtures.MODEL)
        initial=ROOT/'experiments/insight_research/review/workflow_20261024/controlled'
        self.ws=ResearchWorkspace(self.folder/'provided/researcher','受控共同输入',ComposedWorld(seed=73147),config)
        import_initial(self.ws,initial/'initial/manifest.json');initialize_review(self.ws,initial/'provided_review.json')
        self.assertEqual(len(self.ws.records('result')),2);self.assertEqual(len(self.ws.records('review')),1)
        self.assertEqual(len(self.ws.unanswered()),2)
        initialize_review(self.ws,initial/'provided_review.json');self.assertEqual(len(self.ws.records('review')),1)

    def test_w12_opinion_itself_is_not_evidence_for_a_response(self):
        h,r,a,q=self.seeded();reply=self.reply(q,r);reply['evidence_refs']=[q['ref']]
        result=self.save(review_responses=[reply]);self.assertTrue(result['review_rejections'])
        self.assertFalse(self.ws.records('review_response'));self.assertTrue(self.ws.unanswered())

if __name__=='__main__':unittest.main()
