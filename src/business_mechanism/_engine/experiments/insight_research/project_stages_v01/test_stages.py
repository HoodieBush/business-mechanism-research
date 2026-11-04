import json,os,unittest,sqlite3
from copy import deepcopy
from unittest.mock import patch
from ..common import ROOT,digest,sha,Pending,encoded,write_json
from ..test_acceptance import state,raw_call
from ..paired_v01.test_pairing import MODEL
from ..paired_v01.budget import StudyBudget
from ..paired_v01.evidence import export_snapshot
from ..open_retail_v12 import test_revision as fixture,test_environment
from .workspace import ResearchWorkspace
from .review import Reviewer
from .orchestrator import ResearchRun
from .controller import Project

MODEL_SHA=sha(ROOT/'experiments/insight_research/review/minimal_critic_v01_20261022/project_model_config.json')
class StageTests(unittest.TestCase):
    def setUp(self):
        self.p=patch.object(test_environment,'ResearchWorkspace',ResearchWorkspace);self.p.start()
        self.fx=fixture.RevisionTests('test_r01_patch_roundtrips_without_unchanged_full_fields');self.fx._testMethodName=self._testMethodName;self.fx.setUp();self.f=self.fx.f
        self.h,self.r,self.a=self.fx.assessed();self.peers=[]
        self.project=Project(self.f.folder/'project',{'project_id':'engineering','project_budget_id':'USER-20261022-CRITIC-10M','model_config_sha256':MODEL_SHA,'max_stages':3,'token_allowance':12000000,'wall_seconds':7200},create=True)
        self.run1=self.runner(self.f.ws,'stage1')
        self.project.register_stage('s1',run_root=self.run1.root,budget=self.run1.budget,question='Researcher chosen scoped initial question')
    def tearDown(self):
        for p in self.peers:p.close()
        self.fx.tearDown();self.p.stop()
    def runner(self,ws,label):
        root=ws.root.parent
        budget=StudyBudget(root/'common_budget.sqlite',{'study_id':label,'run_id':label,'project_budget_id':'USER-20261022-CRITIC-10M','token_allowance':4000000,'max_http_attempts':160,'model_config_sha256':MODEL_SHA},create=True)
        run=ResearchRun(root,ws,MODEL,budget);run.run(0)
        run.runtime.cp.update(status='pending',reason='Engineering finite stage stopped; not scientific refutation');run.runtime.save();return run
    def checkpoint(self,ws=None):
        ws=ws or self.f.ws
        return ws.call('update_research_state',state(active_hypothesis_refs=[self.h['ref']],focus_hypothesis_refs=[],incorporated_result_refs=[self.r['ref']],evidence_refs=[self.r['ref']],next_action='Study another scoped comparison using the previous denominator lesson',next_reason='Researcher direction, not a fixed algorithm stage'),'stage_checkpoint')
    def close1(self):
        if not self.f.ws.db.execute("SELECT 1 FROM operations WHERE key='stage_checkpoint'").fetchone():self.checkpoint()
        return self.project.close_stage('s1',self.run1,{'status':'pending','reason':'finite engineering stop'},next_question='Researcher chooses a new descriptive comparison',scientific_note='Initial fixture A has not been independently checked; an execution pause is not refutation.')
    def second(self,mode='self'):
        cfg=deepcopy(self.f.ws.settings);cfg['project_archives']=self.project.archives();cfg['verification_mode']=mode
        ws=ResearchWorkspace(self.f.folder/('stage2_'+mode)/'researcher','Researcher-selected next comparison',self.f.world,cfg);run=self.runner(ws,'stage2_'+mode)
        self.project.register_stage('s2',run_root=run.root,budget=run.budget,question=ws.question,parent_stage='s1');return ws,run
    def paid_checkpoint(self,run,tokens):
        calls=0
        def provider(config,payload):
            nonlocal calls
            calls+=1;self.assertFalse(run.ws.db.in_transaction)
            args=state(active_hypothesis_refs=[self.h['ref']],focus_hypothesis_refs=[],incorporated_result_refs=[self.r['ref']],evidence_refs=[self.r['ref']]) if run is self.run1 else state(active_hypothesis_refs=[],focus_hypothesis_refs=[],incorporated_result_refs=[],evidence_refs=[])
            raw=raw_call('update_research_state',args);raw['usage']={'total_tokens':tokens};return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider):run.runtime.run(1)
        self.assertEqual(calls,1)

    def test_s01_two_actual_stages_retain_all_paid_requests_and_recall_originals(self):
        self.paid_checkpoint(self.run1,23);handover=self.close1();self.assertEqual(handover['all_role_budget']['accounted_tokens'],23)
        ws,run=self.second()
        try:
            self.paid_checkpoint(run,17)
            recalled=ws.call('read_memory',{'ref':'archive:s1:'+self.h['ref']},'recall')
            self.assertEqual(json.loads(recalled['text'])['original'],self.f.ws.record(self.h['ref']))
            self.assertEqual(len(ws.records('knowledge')),0);self.assertEqual(len(ws.records('hypothesis')),0)
            self.assertEqual(self.project.cumulative_cost()['accounted_tokens'],40);self.assertEqual(self.project.cumulative_cost()['http_attempts'],2)
            sealed=self.project.close_stage('s2',run,{'status':'pending','reason':'second finite stop'},next_question='Next researcher question remains open',scientific_note='No independent new finding has been produced in this engineering stage.')
            self.assertEqual(sealed['cumulative_stage_cost']['accounted_tokens'],40);self.assertEqual(len(self.project.archives()),2)
            self.assertEqual(self.run1.budget.snapshot()['accounted_tokens'],23);self.assertNotEqual(run.runtime.cp['messages'],self.run1.runtime.cp['messages'])
        finally:ws.close()

    def test_s02_prior_date_exposure_cannot_be_reset_by_new_hash_or_workspace(self):
        seen={'dataset_id':'fixed-fresh-source','start':'2026-03-28','end':'2026-06-25','sha256':'1'*64}
        self.project.record_exposure(seen,stage_id='older-study',source_receipt={'sha256':'2'*64,'kind':'scripted exposure receipt'})
        self.close1();cfg=deepcopy(self.f.ws.settings);ws=ResearchWorkspace(self.f.folder/'newdata/researcher','new data admission',self.f.world,cfg);run=self.runner(ws,'newdata')
        try:
            with self.assertRaisesRegex(ValueError,'already_seen'):self.project.register_stage('s2',run_root=run.root,budget=run.budget,question='Different hash does not make the same period new',parent_stage='s1',declared_fresh=[{**seen,'sha256':'3'*64}])
            fresh={**seen,'start':'2026-06-26','end':'2026-07-02'}
            self.assertFalse(self.project.already_seen(fresh));self.assertTrue(self.project.already_seen({**fresh,'start':'2026-06-25'}))
            self.project.register_stage('s2',run_root=run.root,budget=run.budget,question='New future interval is eligible before actual exposure',parent_stage='s1',declared_fresh=[fresh])
        finally:ws.close()

    def test_s03_both_roles_independently_search_and_materialize_same_old_original(self):
        self.close1();ws,run=self.second('independent')
        try:
            # A new current review packet is independent from project history.
            self.f.ws,old=ws,self.f.ws
            try:h,r,a=self.fx.assessed()
            finally:self.f.ws=old
            dest=self.f.folder/'peer_inputs';export_snapshot(ws,dest,a['ref'])
            peer=Reviewer(self.f.folder/'peer',dest,{'research_profile':'paired_critic_v1','model_config':MODEL,'limits':ws.settings['limits'],'project_archives':self.project.archives()});self.peers.append(peer)
            for actor in (ws,peer):
                out=actor.call('search_memory',{'archive_stage':'s1','query':'工程','kind':'hypothesis'},'archive_search')
                self.assertTrue(any(x['ref']=='archive:s1:'+self.h['ref'] for x in out['hits']),out)
            left=ws.call('read_memory',{'ref':'archive:s1:'+self.r['ref']},'owner_old_result');right=peer.call('read_memory',{'ref':'archive:s1:'+self.r['ref']},'peer_old_result')
            self.assertEqual(left['text'],right['text']);self.assertEqual(sha(left['compute_path']),sha(right['compute_path']))
            self.assertEqual(len(ws.tools),15);self.assertEqual(len(peer.tools),6);self.assertNotIn('reasoning_content',left['text'])
        finally:ws.close()

    def test_s04_nonrecent_unbound_withdrawn_history_is_reachable_but_not_current_K(self):
        s=self.f.call('update_research_state',state(active_hypothesis_refs=[self.h['ref']],incorporated_result_refs=[self.r['ref']],evidence_refs=[self.r['ref']],knowledge_updates=[{'kind':'method','statement':'Archived denominator reminder','scope':'Engineering fixed table only','status':'tentative','evidence_refs':[self.r['ref']],'hypothesis_refs':[],'research_use':'Prior denominator lesson'}]))
        k=s['knowledge_refs'][0]
        with self.f.ws.db:self.f.ws._flag(k,'withdraw','Engineering old memory is withdrawn',None)
        self.close1();ws,run=self.second()
        try:
            out=ws.call('search_memory',{'archive_stage':'s1','query':'denominator','kind':'knowledge'},'old_unbound');self.assertEqual(out['hits'][0]['ref'],'archive:s1:'+k)
            self.assertEqual(out['hits'][0]['lifecycle']['status'],'withdraw');self.assertEqual(len(ws.records('knowledge')),0)
            out=ws.call('read_memory',{'ref':'archive:s1:'+k},'withdrawn_original');self.assertFalse(json.loads(out['text'])['lifecycle']['eligible_as_current_premise'])
        finally:ws.close()

    def test_s05_paid_pending_or_undrained_work_blocks_advance_and_preserves_fee(self):
        self.checkpoint();job=self.f.ws.jobs('pending')[0]
        # An undrained owner delivery is sufficient to refuse archival.
        self.run1.journal.state['delivery']={'request_hash':'engineering_pending'};self.run1.journal.save()
        with self.assertRaises(Pending):self.close1()
        with self.assertRaises(Pending):self.project.register_stage('s2',run_root=self.f.folder/'fake',budget=self.run1.budget,question='must not skip paid work',parent_stage='s1')
        self.assertFalse(self.project.archives());self.assertEqual(self.project.stages()[0]['status'],'registered')

    def test_s06_archive_source_and_catalog_tampering_are_detected_without_overwrite(self):
        handover=self.close1();ws,run=self.second()
        try:
            root=Path(handover['archive']['path']);manifest=json.loads((root/'manifest.json').read_text());source=root/'public/business.sqlite';source.chmod(0o644);source.write_bytes(source.read_bytes()+b'changed')
            ref=next(r for r,p,h,n in sqlite3.connect((root/'catalog.sqlite').as_uri()+'?mode=ro',uri=True).execute('select * from files') if p=='public/business.sqlite')
            with self.assertRaises(Pending):ws.call('read_memory',{'ref':'archive:s1:'+ref},'tamper')
            catalog=root/'catalog.sqlite';catalog.chmod(0o644);catalog.write_bytes(catalog.read_bytes()+b'changed')
            with self.assertRaises(Pending):ws.call('search_memory',{'archive_stage':'s1','query':'工程'},'catalog_tamper')
        finally:ws.close()

    def test_s07_no_private_process_or_unregistered_source_access(self):
        self.close1();ws,run=self.second()
        try:
            for ref in ('archive:s1:process:1','archive:s1:../../private/checkpoint.json','archive:missing:'+self.h['ref']):
                out=ws.call('read_memory',{'ref':ref},'deny_'+digest(ref));self.assertFalse(out['ok'],out)
            out=ws.call('search_memory',{'archive_stage':'s1','kind':'process'},'deny_process');self.assertFalse(out['ok'])
            self.assertFalse(list((ws.science/'project_history').glob('**/checkpoint.json')))
        finally:ws.close()

    def test_s08_context_constant_with_many_archives_and_file_hashes_are_lazy(self):
        self.close1();ws,run=self.second()
        try:
            base=self.project.archives()[0];ws.settings['project_archives']=[{**base,'stage_id':'s'+str(i)} for i in range(300)]
            context=ws.context()['project_research_history'];self.assertLess(len(encoded(context).encode()),1600);self.assertEqual(context['stage_count'],300)
            index=ws.call('read_memory',{'ref':'archive_index:240'},'oldpage');self.assertEqual(len(json.loads(index['text'])['items']),8)
            called=[];original=sha
            def count(path):called.append(str(path));return original(path)
            with patch('experiments.insight_research.project_stages_v01.archive.sha',side_effect=count):
                ws.call('search_memory',{'archive_stage':'s0','query':'工程'},'lazy')
            self.assertFalse(any(n.endswith('business.sqlite') for n in called));self.assertTrue(any(n.endswith('catalog.sqlite') for n in called))
        finally:ws.close()

    def test_s09_original_stage_cannot_restart_or_fake_complete_and_cost_conflicts_refused(self):
        with self.assertRaises(ValueError):self.project.close_stage('s1',self.run1,{'status':'completed'},next_question='x',scientific_note='No actual report exists')
        self.close1()
        with self.assertRaises(ValueError):self.project.execute('s1',self.run1,steps=0)
        with self.assertRaises(ValueError):self.project.close_stage('s1',self.run1,{'status':'pending'},next_question='rewrite',scientific_note='Cannot rewrite original handover')

    def test_s10_interrupted_after_archive_recovers_without_new_archive_fee_or_source_change(self):
        self.checkpoint();original=self.project._deduplicate;count=0
        def crash(archive):
            nonlocal count
            count+=1
            if count==1:raise RuntimeError('after complete archive before sealing')
            return original(archive)
        with patch.object(self.project,'_deduplicate',side_effect=crash):
            with self.assertRaises(RuntimeError):self.close1()
            before=self.run1.budget.snapshot();out=self.close1()
        self.assertEqual(out['all_role_budget'],before);self.assertEqual(len(self.project.archives()),1);self.assertEqual(count,2)

    def test_s11_actual_unfinished_paid_critic_is_retained_and_blocks_a_new_stage(self):
        self.checkpoint();job=self.f.ws.jobs('pending')[0]
        def provider(config,payload):
            raw=raw_call('read_memory',{'ref':self.a['ref']});raw['usage']={'total_tokens':17};return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider):
            with self.assertRaises(Pending):self.run1.review_job(job)
        before=self.run1.budget.snapshot();self.assertGreater(before['accounted_tokens'],0)
        with self.assertRaisesRegex(Pending,'paid reviewer work'):self.project.close_stage('s1',self.run1,{'status':'pending'},next_question='next',scientific_note='Paid reviewer is unfinished, not a refutation.')
        self.assertEqual(self.project.stages()[0]['status'],'recovery_required');self.assertEqual(self.run1.budget.snapshot(),before)
        with self.assertRaises(Pending):self.project.register_stage('s2',run_root=self.f.folder/'fake',budget=self.run1.budget,question='cannot skip paid critic',parent_stage='s1')

    def test_s12_real_F_ends_stage_and_new_stage_keeps_research_reachable(self):
        from ..paired_v01.test_pairing import review
        self.fx.clear(self.a,self.r['action_ref']);self.checkpoint()
        d=self.f.call('finish_research',{'assessment_refs':[self.a['ref']],'other_hypotheses':{},'limitations':['Fixture only'],'open_questions':[],'measurement_requests':[]})
        read=self.f.call('read_memory',{'ref':d['ref']});j=next(j for j in self.f.ws.jobs('pending') if j['target_ref']==d['ref'])
        q=self.f.call('review_claim',{'job_ref':j['ref'],'review':review(d['ref'],read['action_ref'])});self.assertEqual(q['phase'],'complete',q)
        source=self.f.ws.publication_source();f=self.f.call('finish_research',{'publication':{k:v for k,v in source.items() if k!='rule'}|{'reason':'Explicit engineering stage publication'}});self.assertEqual(f['record_type'],'report')
        self.run1.runtime.cp.update(status='completed',reason=None);self.run1.runtime.save()
        self.project.close_stage('s1',self.run1,{'status':'completed','report_ref':f['ref']},next_question='A new scoped research question',scientific_note='Engineering F, no general scientific capability proof.')
        ws,run=self.second()
        try:
            self.assertEqual(self.project.execute('s2',run,steps=0)['status'],'pending')
            old=ws.call('read_memory',{'ref':'archive:s1:'+f['ref']},'old_stage_F');self.assertEqual(json.loads(old['text'])['original']['ref'],f['ref']);self.assertIsNone(ws.report())
        finally:ws.close()

    def test_s13_persistent_project_deadline_and_stage_ceiling_do_not_reset(self):
        self.close1();ws,run=self.second()
        try:
            with self.project.connect() as db:db.execute('UPDATE control SET deadline=0')
            before=run.budget.snapshot()
            with self.assertRaises(Pending):self.project.execute('s2',run,steps=1)
            reopened=Project(self.project.root,self.project.identity)
            with self.assertRaises(Pending):reopened.execute('s2',run,steps=1)
            self.assertEqual(run.budget.snapshot(),before)
            limited=Project(self.f.folder/'limited',{'project_budget_id':'USER-20261022-CRITIC-10M','model_config_sha256':MODEL_SHA,'max_stages':1,'token_allowance':4000000,'wall_seconds':7200},create=True)
            limited.register_stage('only',run_root=run.root,budget=run.budget,question='One finite stage')
            with self.assertRaisesRegex(Pending,'stage ceiling'):limited.register_stage('again',run_root=run.root,budget=run.budget,question='No auto stage loop')
        finally:ws.close()

    def test_s14_identical_local_request_keys_are_counted_separately_and_unknown_is_held(self):
        self.paid_checkpoint(self.run1,23);self.close1();ws,run=self.second()
        try:
            self.paid_checkpoint(run,23)
            # Both real local journals use digest(['researcher',1]); even the
            # same total cost must count twice across independent allocations.
            self.assertEqual(self.project.cumulative_cost()['http_attempts'],2);self.assertEqual(self.project.cumulative_cost()['accounted_tokens'],46)
            with run.budget.connect() as db:db.execute('INSERT INTO attempts VALUES (?,?,?,NULL,?,?)',('unknown','researcher',500,'held','unknown'))
            self.assertEqual(self.project.cumulative_cost()['unknown_or_inflight_reserve'],500);self.assertEqual(self.project.cumulative_cost()['accounted_tokens'],546)
        finally:ws.close()

    def test_s15_paid_execution_requires_registered_freeze_and_launch(self):
        # This engineering fixture is intentionally NOT a paid scientific study.
        with self.assertRaises((ValueError,KeyError,FileNotFoundError)):
            self.project.execute('s1',self.run1,steps=1)
        self.assertEqual(self.run1.budget.snapshot()['http_attempts'],0)

    def test_s16_old_confirmation_cannot_become_unseen_in_a_new_project_stage(self):
        self.close1();ws,run=self.second()
        try:
            self.f.ws,old=ws,self.f.ws
            try:
                h,p=self.f.plan(confirmation=False);original=ws.record(p['ref']);args={k:original[k] for k in ws.tools['register_test'][0].model_fields if k in original};args['confirmation']=True
                out=self.f.call('register_test',args);self.assertFalse(out['ok']);self.assertIn('explicit registered source',out['error'])
                source={'dataset_id':'fixture','start':'2026-07-01','end':'2026-07-07','sha256':ws.settings['confirmation_sha256']};ws.settings['project_confirmation_slice']=source;ws.settings['project_seen_sources']=[source]
                out=self.f.call('register_test',args);self.assertFalse(out['ok']);self.assertIn('already_seen',out['error'])
                self.assertFalse((ws.science/'received_confirmation').exists())
            finally:self.f.ws=old
        finally:ws.close()

from pathlib import Path
if __name__=='__main__':unittest.main()
