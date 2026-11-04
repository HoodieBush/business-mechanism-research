"""Real local integration controls for both modes and shared reservations."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ..common import ROOT, Pending, digest, encoded
from ..composed_world import ComposedWorld
from ..test_acceptance import settings, state, hypothesis, raw_call, FixtureJournal
from .contracts import Review
from .budget import StudyBudget, StudyJournal
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun

MODEL = json.loads((ROOT/'experiments/insight_research/review/minimal_critic_v01_20261022/project_model_config.json').read_text())


def review(target, action, **changes):
    return {'phase':'complete','target_conclusion':'consistent_in_checked_scope',
        'checked_scope':['实际工程原件与指定对象'],'unchecked_scope':['不是科学发现或可靠性认证'],
        'source_refs':[target], 'checks_performed':[{'action_ref':action,'finding':'实际查看或执行原件','artifact_refs':[]}],
        'issues':[],'open_issue_ids':[],'next_action':'依据证据继续研究',**changes}


class PairingTests(unittest.TestCase):
    def setUp(self):
        out=os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        self.temp=None if out else tempfile.TemporaryDirectory(prefix='pair_')
        self.folder=Path(out or self.temp.name)/self._testMethodName;self.folder.mkdir(parents=True,exist_ok=False)
        self.ws=None;self.counter=0
        self.make('self')

    def tearDown(self):
        if self.ws:self.ws.close()
        if self.temp:self.temp.cleanup()

    def make(self, mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=MODEL)
        config['limits'].update(token_allowance=2000000,max_http_attempts=80,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','核验真实记录并持续研究',ComposedWorld(),config)
        return self.ws

    def call(self,name,args):
        self.counter+=1;return self.ws.call(name,args,'op'+str(self.counter))

    def source(self):return next(x['ref'] for x in self.ws.context()['public_files'] if Path(x['path']).name=='business.sqlite')

    def assessed(self):
        h=self.call('save_hypothesis',hypothesis())
        p=self.call('register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'限定已见记录',
            'observation_unit':'记录行','allocation_unit':'无','analysis':'工程范围','purpose':'真实执行','data_refs':[self.source()],
            'mode':'observational','code':"print('real integration receipt')"})
        r=self.call('run_test',{'plan_ref':p['ref']});self.assertTrue(r['ok'],r)
        a=self.call('record_assessment',{'hypothesis_ref':h['ref'],'result_refs':[r['ref']],'status':'supported',
            'prediction_coverage':'只用于工程数据流','rationale':'夹具声明仍待核验','deviations':[],
            'counterevidence_refs':[],'limitations':['不是科学能力证据']})
        self.assertIn('ref',a,a);return h,r,a

    def save(self,**changes):
        hs=[x['ref'] for x in self.ws.records('hypothesis')]
        return self.call('update_research_state',state(active_hypothesis_refs=hs,focus_hypothesis_refs=hs,
            incorporated_result_refs=[x['ref'] for x in self.ws.records('result')],**changes))

    def clear(self,target,action):
        job=next(j for j in self.ws.jobs('pending') if j['target_ref']==target)
        result=self.save(self_reviews=[{'job_ref':job['ref'],'review':review(target,action)}])
        self.assertFalse(result['review_rejections'],result);return self.ws.job(job['ref'])['review_ref']

    def knowledge(self,**changes):
        return {'kind':'method','statement':'有待验证的研究方法','scope':'当前公开记录','status':'tentative',
            'evidence_refs':[self.source()],'research_use':'指导下一步问题',**changes}

    def budget(self):
        return StudyBudget(self.folder/'study_budget.sqlite',{'study_id':'engineering','project_budget_id':'USER-20261022-CRITIC-10M',
            'token_allowance':2000000,'max_http_attempts':80},create=True)

    def test_01_explicit_mode_identity_and_old_entry_remains_unchanged(self):
        self.assertEqual(self.ws.identity['settings']['verification_mode'],'self')
        self.make('independent');self.assertEqual(self.ws.context()['verification_mode'],'independent')
        with self.assertRaises(ValueError):
            ResearchWorkspace(self.folder/'independent/researcher','核验真实记录并持续研究',ComposedWorld(),
                {**self.ws.settings,'verification_mode':'self'},reopen=True)

    def test_02_candidate_gate_and_legal_state_survive_optional_strong_claim(self):
        h,r,a=self.assessed()
        self.assertEqual(len(self.ws.jobs('pending')),1)
        k=self.knowledge(status='supported_in_scope',hypothesis_refs=[h['ref']],evidence_refs=[a['ref']])
        result=self.save(knowledge_updates=[k]);self.assertIn('ref',result)
        self.assertEqual(len(result['knowledge_rejections']),1)
        self.clear(a['ref'],r['action_ref'])
        result=self.save(knowledge_updates=[k]);self.assertEqual(len(result['knowledge_refs']),1)
        ref=result['knowledge_refs'][0]
        self.assertFalse(self.ws.clearance(ref));self.assertEqual(self.ws.context()['research_knowledge'],[])
        self.clear(ref,r['action_ref'])
        self.ws.premise(ref)

    def test_03_correct_target_and_wrong_old_memory_are_separate(self):
        h,r,a=self.assessed();k=self.save(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        job=self.ws.jobs('pending')[0]
        issue={'issue_id':'old-note','description':'原方法需要修订','type':'reproduced_contradiction','affected_refs':[k],
            'basis':'recomputed','blocking':True,'evidence_locations':[r['ref']],'action_refs':[r['action_ref']],
            'check_artifact_refs':[],'claim_impact':'只影响旧记忆，不否定正确当前判断','minimal_next_step':'显式复核旧记忆'}
        result=self.save(self_reviews=[{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'],issues=[issue],open_issue_ids=['old-note'])}])
        self.assertFalse(result['review_rejections'],result)
        self.assertTrue(self.ws.clearance(a['ref']));self.assertTrue(self.ws.blocked(k))
        q=self.ws.job(job['ref'])['review_ref']
        self.save(memory_reviews=[{'target_ref':k,'decision':'withdraw','reason':'原计算支持撤回','evidence_refs':[r['ref']]}],
            review_responses=[{'review_ref':q,'issue_id':'old-note','disposition':'revise','rationale':'已撤回原方法',
                'evidence_refs':[r['ref']],'replacement_refs':[]}])
        self.assertFalse(self.ws.blocked(k));self.assertEqual(self.ws.review(k)['status'],'withdraw')
        self.assertTrue(self.ws.clearance(a['ref']))

    def test_04_conjecture_is_advisory_and_review_text_is_not_fact(self):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        issue={'issue_id':'possible','description':'过程因果仅是可能解释','type':'methodological_disagreement',
            'affected_refs':[a['ref']],'basis':'conjecture','blocking':True,'evidence_locations':[a['ref']],
            'action_refs':[],'check_artifact_refs':[],'claim_impact':'建议补查','minimal_next_step':'需要采用记录'}
        result=self.save(self_reviews=[{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'],issues=[issue],open_issue_ids=['possible'])}])
        self.assertFalse(result['review_rejections'],result);self.assertTrue(self.ws.clearance(a['ref']))
        with self.assertRaises(ValueError):self.ws.premise(self.ws.job(job['ref'])['review_ref'])

    def test_05_independent_mode_cannot_self_waive_review(self):
        self.make('independent');h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        result=self.save(self_reviews=[{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'])}])
        self.assertIn('ref',result);self.assertEqual(len(result['review_rejections']),1)
        self.assertFalse(self.ws.clearance(a['ref']))

    def test_06_report_draft_waits_and_seals_only_after_review(self):
        h,r,a=self.assessed();self.clear(a['ref'],r['action_ref'])
        draft=self.call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],
            'open_questions':[],'measurement_requests':[]})
        self.assertEqual(draft['record_type'],'report_draft');self.assertIsNone(self.ws.report())
        self.clear(draft['ref'],r['action_ref']);self.assertIsNone(self.ws.report())
        with self.ws.db:self.ws.try_seal_report()
        self.assertEqual(self.ws.report()['reviewed_draft_ref'],draft['ref'])

    def test_07_revision_keeps_old_verdict_and_one_directed_recheck(self):
        h,r,a=self.assessed();self.clear(a['ref'],r['action_ref'])
        args={k:v for k,v in self.ws.record(a['ref']).items() if k in self.ws.tools['record_assessment'][0].model_fields}
        args.update(status='unresolved',supersedes_assessment_ref=a['ref'],rationale='依证据修订原判断')
        changed=self.call('record_assessment',args);self.assertIn('ref',changed,changed)
        self.assertEqual(self.ws.record(a['ref'])['status'],'supported')
        self.assertEqual(self.ws.review(a['ref'])['status'],'superseded')
        job=self.ws.jobs('pending')[0];self.assertEqual(job['round'],2)
        self.clear(changed['ref'],r['action_ref'])
        args['supersedes_assessment_ref']=changed['ref'];args['rationale']='再次修改'
        third=self.call('record_assessment',args)
        self.assertTrue(any(j['target_ref']==third['ref'] and j['status']=='exhausted' for j in self.ws.jobs()))

    def test_08_dual_import_actual_review_and_next_packet_contains_no_private_thoughts(self):
        self.make('independent');h,r,a=self.assessed();budget=self.budget()
        def factory(reviewer,job):
            def read():return raw_call('read_memory',{'ref':a['ref']},identifier='read')
            def finish():
                action=reviewer.db.execute('SELECT ref FROM actions ORDER BY rowid LIMIT 1').fetchone()[0]
                return raw_call('record_review',review(a['ref'],action),identifier='final')
            return FixtureJournal([read,finish])
        run=ResearchRun(self.folder/'independent',self.ws,MODEL,budget,owner_journal=FixtureJournal([]),reviewer_journal_factory=factory)
        job=self.ws.jobs('pending')[0];run.review_job(job)
        self.assertTrue(self.ws.clearance(a['ref']))
        q=self.ws.record(self.ws.job(job['ref'])['review_ref']);self.assertEqual(q['author'],'independent_critic')
        self.assertTrue(self.ws.records('review_action'))
        k=self.save(knowledge_updates=[self.knowledge(status='supported_in_scope',hypothesis_refs=[h['ref']],evidence_refs=[a['ref']])])['knowledge_refs'][0]
        next_job=next(j for j in self.ws.jobs('pending') if j['target_ref']==k)
        inputs=run.prepare_job(next_job)
        from .evidence import EvidenceView
        view=EvidenceView(inputs)
        try:
            self.assertFalse(view.review(q['ref'])['eligible_as_current_premise'])
            self.assertEqual(view.record(k)['record_type'],'knowledge')
        finally:view.close()

    def test_09_all_role_admission_unknown_usage_and_idempotent_settlement(self):
        budget=self.budget();payload={'model':'test','max_tokens':100,'messages':[{'role':'user','content':'test'}]}
        bound=budget.reserve('owner','researcher',payload)
        self.assertEqual(budget.snapshot()['accounted_tokens'],bound)
        budget.reserve('critic','critic:J',payload)
        self.assertEqual(budget.snapshot()['http_attempts'],2)
        budget.settle('owner',digest(payload),{'total_tokens':50});budget.settle('owner',digest(payload),{'total_tokens':50})
        budget.settle('critic',digest(payload),{})
        self.assertEqual(budget.snapshot()['accounted_tokens'],50+bound)
        with self.assertRaises(Pending):budget.reserve('owner','researcher',payload)

    def test_10_local_role_crash_recovers_without_new_provider_call(self):
        budget=self.budget();journal=StudyJournal(self.ws,MODEL,budget,'researcher',memory=True)
        payload={'model':MODEL['model'],'max_tokens':100,'messages':[{'role':'system','content':'test'},{'role':'user','content':'{}'}]}
        record={'response':{'usage':{'total_tokens':10},'choices':[]}}
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value=record), \
             patch.object(budget,'settle',side_effect=RuntimeError('after durable response')):
            with self.assertRaises(RuntimeError):journal.call(payload)
        self.assertIsNotNone(journal.state['inflight'])
        reopened=StudyJournal(self.ws,MODEL,budget,'researcher',memory=True)
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no second request')):
            reopened.call(payload)
        self.assertEqual(budget.snapshot()['http_attempts'],1);self.assertEqual(budget.snapshot()['accounted_tokens'],10)
        self.assertEqual(reopened.state['accounted_tokens'],10)

    def test_11_whole_single_run_self_checks_and_seals(self):
        h,r,a=self.assessed();budget=self.budget()
        def saving(target):
            job=next(j for j in self.ws.jobs('pending') if j['target_ref']==target)
            return raw_call('update_research_state',state(active_hypothesis_refs=[h['ref']],focus_hypothesis_refs=[h['ref']],
                incorporated_result_refs=[r['ref']],self_reviews=[{'job_ref':job['ref'],'review':review(target,r['action_ref'])}]))
        def finish():
            return raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],
                'open_questions':[],'measurement_requests':[]})
        journal=FixtureJournal([lambda:saving(a['ref']),finish,lambda:saving(self.ws.records('report_draft')[-1]['ref'])])
        result=ResearchRun(self.folder/'self',self.ws,MODEL,budget,owner_journal=journal).run(8)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(self.ws.records('review')),2)
        self.assertEqual(self.ws.report()['business_insight_assessment_refs'],[a['ref']])

    def test_12_whole_dual_run_feedback_and_report_import(self):
        self.make('independent');h,r,a=self.assessed();budget=self.budget()
        def factory(reviewer,job):
            def finish():
                action=reviewer.db.execute('SELECT ref FROM actions ORDER BY rowid LIMIT 1').fetchone()[0]
                return raw_call('record_review',review(job['target_ref'],action),identifier='final')
            return FixtureJournal([raw_call('read_memory',{'ref':job['target_ref']},identifier='read'),finish])
        def saving():return raw_call('update_research_state',state(active_hypothesis_refs=[h['ref']],focus_hypothesis_refs=[h['ref']],incorporated_result_refs=[r['ref']]))
        def finish():return raw_call('finish_research',{'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程范围'],'open_questions':[],'measurement_requests':[]})
        result=ResearchRun(self.folder/'independent',self.ws,MODEL,budget,owner_journal=FixtureJournal([saving,finish]),reviewer_journal_factory=factory).run(8)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(self.ws.records('review')),2)
        self.assertTrue(all(q['author']=='independent_critic' for q in self.ws.records('review')))

    def test_13_failed_state_rolls_back_provisional_self_clearance(self):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        bad=state(active_hypothesis_refs=['H_missing'],self_reviews=[{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'])}])
        result=self.call('update_research_state',bad)
        self.assertFalse(result['ok']);self.assertFalse(self.ws.clearance(a['ref']))
        self.assertEqual(self.ws.records('review'),[])

    def test_14_later_withdrawal_blocks_old_clearance_and_descendants(self):
        h,r,a=self.assessed();self.clear(a['ref'],r['action_ref'])
        k=self.save(knowledge_updates=[self.knowledge(status='supported_in_scope',hypothesis_refs=[h['ref']],evidence_refs=[a['ref']])])['knowledge_refs'][0]
        self.clear(k,r['action_ref'])
        self.save(memory_reviews=[{'target_ref':r['ref'],'decision':'withdraw','reason':'结果原件需要复核','evidence_refs':[self.source()]}])
        self.assertFalse(self.ws.clearance(a['ref']));self.assertFalse(self.ws.clearance(k))
        with self.assertRaises(ValueError):self.ws.premise(k)
        self.assertEqual(self.ws.context()['research_knowledge'],[])

    def test_15_common_study_limit_applies_across_roles(self):
        from token_budget import reservation_bound
        p={'model':'test','max_tokens':100,'messages':[{'role':'user','content':'shared'}]};bound=reservation_bound(p)
        b=StudyBudget(self.folder/'small.sqlite',{'token_allowance':bound+10,'max_http_attempts':2,'project_budget_id':'USER-20261022-CRITIC-10M'},create=True)
        b.reserve('r','researcher',p)
        with self.assertRaises(Pending):b.reserve('c','critic',p)
        self.assertEqual(b.snapshot()['http_attempts'],1)
        b.settle('r',digest(p),{'total_tokens':1});b.reserve('c','critic',p)
        self.assertEqual(b.snapshot()['http_attempts'],2)

    def test_16_pending_claim_is_checkpoint_navigation_not_a_premise(self):
        h,r,a=self.assessed()
        result=self.save(evidence_refs=[r['ref']],pending_claim_refs=[a['ref']])
        self.assertIn('ref',result);self.assertEqual(self.ws.state()['pending_claim_refs'],[a['ref']])
        with self.assertRaises(ValueError):self.ws.premise(a['ref'])

    def test_17_evidence_linked_rebuttal_can_retract_wrong_review_once(self):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0]
        issue={'issue_id':'misread','description':'脚本模拟审查者错读','type':'methodological_disagreement',
            'affected_refs':[a['ref']],'basis':'observed','blocking':True,'evidence_locations':[a['ref']],
            'action_refs':[r['action_ref']],'check_artifact_refs':[],'claim_impact':'暂不能强复用','minimal_next_step':'回读原件'}
        result=self.save(self_reviews=[{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'],
            target_conclusion='changes_needed',issues=[issue],open_issue_ids=['misread'])}])
        self.assertFalse(result['review_rejections'],result);self.assertFalse(self.ws.clearance(a['ref']))
        q=self.ws.job(job['ref'])['review_ref']
        self.save(review_responses=[{'review_ref':q,'issue_id':'misread','disposition':'rebut',
            'rationale':'实际结果与原预测范围一致，需据原件更正该意见','evidence_refs':[r['ref']],'replacement_refs':[]}])
        recheck=self.ws.jobs('pending')[0];self.assertEqual(recheck['round'],2)
        result=self.save(self_reviews=[{'job_ref':recheck['ref'],'review':review(a['ref'],r['action_ref'],prior_issue_updates={'misread':'retracted'})}])
        self.assertFalse(result['review_rejections'],result);self.assertTrue(self.ws.clearance(a['ref']))
        self.assertFalse(self.ws.blocked(a['ref']))

    def test_18_provided_initial_state_identical_across_modes_and_test_not_reexecuted(self):
        from .initialization import import_initial
        manifest=ROOT/'experiments/insight_research/review/paired_impl_20261023/prepared_controlled/initial/manifest.json'
        task=json.loads((manifest.parent.parent/'tasks.json').read_text())['tasks'][0]
        records=[];world=task['environment']
        for name,mode in (('left','self'),('right','independent')):
            config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=MODEL)
            ws=ResearchWorkspace(self.folder/name,task['question'],ComposedWorld(**world),config)
            try:
                import_initial(ws,manifest)
                records.append([x[0] for x in ws.db.execute('SELECT body FROM records ORDER BY rowid')])
                r=ws.records('result')[0];before=ws.worker.count
                repeated=ws.call('run_test',{'plan_ref':r['plan_ref']},'reuse')
                self.assertEqual(repeated['ref'],r['ref']);self.assertEqual(ws.worker.count,before)
                self.assertEqual(ws.context()['verification_mode'],mode)
            finally:ws.close()
        self.assertEqual(records[0],records[1])

    def test_19_old_memory_repair_flags_downstream_without_invalidating_true_target(self):
        h,r,a=self.assessed()
        first=self.save(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        second=self.save(knowledge_updates=[self.knowledge(statement='依赖旧方法的笔记',evidence_refs=[first])])['knowledge_refs'][0]
        saved=self.save(evidence_refs=[second]);old_state=saved['ref']
        job=self.ws.jobs('pending')[0]
        issue={'issue_id':'upstream','description':'旧方法应撤回，派生笔记需复核','type':'reproduced_contradiction',
            'affected_refs':[first,second],'basis':'recomputed','blocking':True,'evidence_locations':[r['ref']],
            'action_refs':[r['action_ref']],'check_artifact_refs':[],'claim_impact':'只影响旧记忆链','minimal_next_step':'复核并隔离旧链'}
        result=self.save(self_reviews=[{'job_ref':job['ref'],'review':review(a['ref'],r['action_ref'],issues=[issue],open_issue_ids=['upstream'])}])
        self.assertFalse(result['review_rejections'],result)
        self.save(memory_reviews=[{'target_ref':first,'decision':'withdraw','reason':'实际证据不支持原方法','evidence_refs':[r['ref']]}],
            review_responses=[{'review_ref':self.ws.job(job['ref'])['review_ref'],'issue_id':'upstream','disposition':'revise',
                'rationale':'撤回上游并保留下游待复核标记','evidence_refs':[r['ref']],'replacement_refs':[]}])
        self.assertIn(first,self.ws.review(second)['explicit_dependency_reviews'])
        self.assertTrue(self.ws.review(old_state)['explicit_dependency_reviews'])
        self.assertTrue(self.ws.clearance(a['ref']))
        with self.assertRaises(ValueError):self.ws.premise(second)


    def test_20_self_review_ceiling_survives_controller_reopen(self):
        h,r,a=self.assessed();budget=self.budget();job=self.ws.jobs('pending')[0]
        self.assertEqual(job['review_http_limit'],12)
        with self.ws.db:self.ws.db.execute('INSERT INTO self_review_clock VALUES (?,?)',(job['ref'],0))
        run=ResearchRun(self.folder/'self',self.ws,MODEL,budget,owner_journal=FixtureJournal([]))
        run.runtime.cp['responses']=12;run.runtime.save()
        for _ in range(2):
            reopened=ResearchRun(self.folder/'self',self.ws,MODEL,budget,owner_journal=FixtureJournal([]))
            result=reopened.run(1)
            self.assertEqual(result['status'],'pending',result)
            self.assertIn('same registered per-review HTTP ceiling',result['reason'])
            self.assertEqual(self.ws.job(job['ref'])['status'],'pending')
        self.assertEqual(budget.snapshot()['http_attempts'],0)


if __name__=='__main__':unittest.main()
