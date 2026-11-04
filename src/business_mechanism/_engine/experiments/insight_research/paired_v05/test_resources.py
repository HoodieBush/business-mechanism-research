"""Late research actions, unchanged hard admission, real resume and correction."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ..paired_v02 import test_interface as fixtures
from ..test_acceptance import settings,state,raw_call,FixtureJournal
from ..common import ROOT,Pending,digest
from ..critic_v01.shared import lifecycle
from ..composed_world import ComposedWorld
from ..paired_v01.budget import StudyBudget,StudyJournal
from token_budget import reservation_bound
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .continuation import prepare

MODEL,review=fixtures.MODEL,fixtures.review


class ResourceTests(unittest.TestCase):
    setUp=fixtures.InterfaceTests.setUp
    tearDown=fixtures.InterfaceTests.tearDown
    call=fixtures.InterfaceTests.call
    source=fixtures.InterfaceTests.source
    save=fixtures.InterfaceTests.save
    budget=fixtures.InterfaceTests.budget

    def make(self,mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=MODEL)
        config['limits'].update(token_allowance=2500000,max_http_attempts=80,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','有证据的业务认识，工程夹具不计模型能力',ComposedWorld(),config)
        return self.ws

    def test_s01_low_resource_flag_keeps_all_tools_and_actual_hypothesis_creation(self):
        run=ResearchRun(self.folder/'self',self.ws,MODEL,self.budget(),owner_journal=FixtureJournal([]))
        run.runtime.cp['resource_closeout']=True;self.ws.closeout_mode=True
        p=run.runtime.prepare_payload(run.runtime.payload(run.runtime.initial()))
        self.assertEqual({x['function']['name'] for x in p['tools']},set(self.ws.tools))
        from ..test_acceptance import hypothesis
        h=self.call('save_hypothesis',hypothesis(evidence_refs=[self.source()]))
        self.assertIn('ref',h,h);self.assertIn('硬上限不变',p['messages'][-1]['content'])

    def test_s02_hard_shared_budget_still_rejects_before_provider(self):
        tiny=StudyBudget(self.folder/'tiny.sqlite',{'project_budget_id':'USER-20261022-CRITIC-10M','token_allowance':10,'max_http_attempts':80},create=True)
        journal=StudyJournal(self.ws,MODEL,tiny,'researcher',memory=True)
        payload={'model':MODEL['model'],'max_tokens':65536,'messages':[{'role':'user','content':'test'}]}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=AssertionError('no call')) as provider:
            with self.assertRaises(Pending):journal.call(payload)
            self.assertEqual(provider.call_count,0)
        self.assertEqual(tiny.snapshot()['http_attempts'],0)

    def test_s03_real_unsaved_work_and_costs_retained_with_explicit_local_extension(self):
        path=ROOT/'experiments/insight_research/review/paired_impl_20261023/prepared_continuation_v05/self.json'
        manifest=json.loads(path.read_text());old=manifest['parent_identity'];config={**old['settings'],'limits':{**old['settings']['limits'],'token_allowance':2500000},'continuation_binding':{'manifest':'engineering','sha256':digest(manifest)}}
        identity={**manifest['parent_budget_identity'],'study_id':'engineering_soft_resource','token_allowance':2500000}
        env=old['environment_identity'];world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version'])
        base=self.folder.resolve()
        if not base.is_relative_to(ROOT):
            tmp=tempfile.TemporaryDirectory(prefix='resource_resume_',dir=path.parent.parent);self.addCleanup(tmp.cleanup);base=Path(tmp.name)
        output=base/'actual';prepare(output,manifest,old['question'],world,config,identity)
        ws=ResearchWorkspace(output/'researcher',old['question'],world,config,reopen=True);budget=StudyBudget(output/'common_budget.sqlite',identity)
        try:
            self.assertEqual(budget.snapshot()['accounted_tokens'],manifest['inherited_tokens'])
            self.assertEqual(budget.snapshot()['http_attempts'],manifest['inherited_attempts'])
            run=ResearchRun(output,ws,MODEL,budget)
            payload=run.runtime.prepare_payload(run.runtime.payload())
            self.assertIn('save_hypothesis',{x['function']['name'] for x in payload['tools']})
            self.assertLessEqual(reservation_bound(payload),budget.snapshot()['remaining_tokens'])
            self.assertTrue(run.runtime.cp['messages']);self.assertTrue(ws.checkpoint_work()['pending'])
            self.assertEqual(ws.records('hypothesis'),[]);self.assertEqual(ws.records('state'),[])
        finally:ws.close()

    def test_s04_actual_numeric_wrong_judgment_corrects_with_original_prediction_preserved(self):
        self.make('independent');source=self.source()
        with sqlite3.connect((self.ws.public/'business.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            wrong,right=db.execute('SELECT avg(price),sum(price*sales)*1.0/sum(sales) FROM hourly WHERE price>0').fetchone()
        self.assertGreater(abs(wrong-right),1e-7)
        prediction=f'给定正价记录的记录销售额除以记录件数等于{wrong:.10f}元/件，误差不超过0.0000001。'
        h=self.call('save_hypothesis',{'kind':'business','statement':prediction,'scope':'给定全部正价hourly记录，不外推需求或未来','prediction':prediction,
            'falsification':'同范围实际加权汇总超出误差界','alternatives':['未加权均价可能不等于每件销售额'],'evidence_refs':[source]})
        def measured(sql):
            code="import os,sqlite3\nfrom pathlib import Path\ndb=sqlite3.connect(Path(os.environ['PUBLIC_DIR'])/'business.sqlite')\nprint(db.execute("+repr(sql)+").fetchone()[0])"
            p=self.call('register_test',{'hypothesis_ref':h['ref'],'prediction':prediction,'contrast':'同范围实际算术','observation_unit':'记录售出件','allocation_unit':'无','analysis':'保留实际执行','purpose':'错误修订回归夹具','data_refs':[source],'mode':'observational','code':code})
            return self.call('run_test',{'plan_ref':p['ref']})
        bad=measured('SELECT avg(price) FROM hourly WHERE price>0')
        a=self.call('record_assessment',{'hypothesis_ref':h['ref'],'result_refs':[bad['ref']],'status':'supported','prediction_coverage':'脚本故意把记录均价当每件销售额','rationale':'故意错误旧判断','deviations':[],'counterevidence_refs':[],'limitations':['工程提供错误，待实际复算纠正']})
        k=self.save(knowledge_updates=[{'kind':'method','statement':'每件销售额直接取记录price算术平均','scope':'正价记录每售出件口径','status':'tentative','evidence_refs':[source],'research_use':'工程坏记忆'}])['knowledge_refs'][0]
        def factory(peer,job):
            def complete():
                ref,body=peer.db.execute("SELECT ref,body FROM actions WHERE json_extract(body,'$.tool')='query_data' ORDER BY rowid DESC LIMIT 1").fetchone();artifact=json.loads(body)['result']['file']['ref']
                changes={}
                if job['target_ref']==a['ref']:
                    issue={'issue_id':'numeric','type':'reproduced_contradiction','description':'实际加权汇总与未加权预测不同','affected_refs':[a['ref'],k],
                        'basis':'recomputed','blocking':True,'evidence_locations':[h['ref'],artifact],'action_refs':[ref],'check_artifact_refs':[artifact],
                        'claim_impact':'旧支持判断与方法不适用每售出件口径','minimal_next_step':'依据原预测修订并撤回旧方法'}
                    changes={'target_conclusion':'changes_needed','issues':[issue],'open_issue_ids':['numeric']}
                return raw_call('record_review',review(job['target_ref'],ref,**changes),identifier='complete')
            return FixtureJournal([raw_call('query_data',{'sql':'SELECT sum(price*sales)*1.0/sum(sales) AS correct_value FROM hourly WHERE price>0','purpose':'实际复算同范围每件销售额'},identifier='compute'),complete])
        run=ResearchRun(self.folder/'independent',self.ws,MODEL,self.budget(),owner_journal=FixtureJournal([]),reviewer_journal_factory=factory)
        first=self.ws.jobs('pending')[0];run.review_job(first);q=self.ws.job(first['ref'])['review_ref'];self.assertFalse(self.ws.clearance(a['ref']))
        good=measured('SELECT sum(price*sales)*1.0/sum(sales) FROM hourly WHERE price>0')
        changed=self.call('record_assessment',{'hypothesis_ref':h['ref'],'result_refs':[good['ref']],'status':'refuted','prediction_coverage':f'同范围加权值{right}与原{wrong}不同','rationale':'修正计算口径后按原预测诚实反驳','deviations':[],'counterevidence_refs':[bad['ref']],'limitations':['同一已见资料复算，不是新样本'],'supersedes_assessment_ref':a['ref']})
        saved=self.save(evidence_refs=[good['ref']],pending_claim_refs=[changed['ref']],
            memory_reviews=[{'target_ref':k,'decision':'withdraw','reason':'加权口径复算否定此方法的用途','evidence_refs':[good['ref']]}],
            review_responses=[{'review_ref':q,'issue_id':'numeric','disposition':'revise','rationale':'原预测不改，按真数据反驳并撤回旧方法','evidence_refs':[good['ref']],'replacement_refs':[changed['ref']]}])
        self.assertTrue(saved['response_refs']);run.review_job(self.ws.jobs('pending')[0])
        self.assertTrue(self.ws.clearance(changed['ref']));self.assertFalse(lifecycle(self.ws.db,a['ref'])['eligible_as_current_premise'])
        self.assertFalse(lifecycle(self.ws.db,k)['eligible_as_current_premise']);self.assertEqual(self.ws.record(h['ref'])['prediction'],prediction)
        draft=self.call('finish_research',{'assessment_refs':[changed['ref']],'other_hypotheses':{},'limitations':['工程数值回归，不是模型科学能力'],'open_questions':[],'measurement_requests':[]})
        run.review_job(self.ws.jobs('pending')[0])
        with self.ws.db:self.ws.try_seal_report()
        self.assertIsNotNone(self.ws.report());self.assertEqual(self.ws.report()['assessment_refs'],[changed['ref']])


if __name__=='__main__':unittest.main()
