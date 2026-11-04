import json,math,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from scipy.stats import t
from ..common import digest
from ..composed_world import ComposedWorld
from ..critic_v01.shared import lifecycle
from ..paired_v02 import test_interface as fixtures
from ..paired_v07 import test_workflow as workflow
from ..test_acceptance import settings,FixtureJournal,raw_call
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .review import Reviewer
from ..paired_v01.evidence import export_snapshot

class ScopedTests(unittest.TestCase):
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

    def make(self,mode):
        if self.ws:self.ws.close()
        config=settings();config.update(research_profile='paired_research_v1',verification_mode=mode,model_config=fixtures.MODEL,
            workflow_policy={'max_lineage_reviews':4},execution_policy={'wall_seconds':7200,'warn_after_requests':8,'stop_after_requests':16,'review_http_limit':18,'closeout_reserve_tokens':1300000})
        config['limits'].update(token_allowance=3000000,max_http_attempts=160,max_request_bytes=524288,knowledge_context_bytes=24000)
        self.ws=ResearchWorkspace(self.folder/mode/'researcher','工程反例：范围、对象修订与有限交付',ComposedWorld(),config);return self.ws

    def csv(self):
        code='''import csv,os
from pathlib import Path
p=Path(os.environ['WORK_DIR'])/'observations.csv'
with p.open('w') as f:
 w=csv.DictWriter(f,fieldnames=['site','day','hour','sku','treatment','sales','opening_stock','closing_stock','restock','available_minutes']);w.writeheader()
 for i in range(8):
  for arm in [0,1]:
   for sku in ['S01','S02']:
    for hour in [7,8]:
     sales=i+1+(i+1 if arm and sku=='S01' else 0);opening=100-(hour-7)*sales if arm else 0
     w.writerow(dict(site='C%02d'%(i+1),day=arm,hour=hour,sku=sku,treatment=arm,sales=sales,opening_stock=opening,closing_stock=opening-sales,restock=0,available_minutes=60 if arm else 0))
print('Explicit synthetic arithmetic counterexample, not real business evidence.')'''
        r=self.call('run_python',{'code':code,'purpose':'真实沙箱构造不同小时/不同聚类的工程反例'})
        return next(f['ref'] for f in r['files'] if f['path'].endswith('/observations.csv'))

    def inspect(self,ref,analysis='daily_sales_effect',**extra):
        return self.call('inspect_evidence',{'source_ref':ref,'analysis':analysis,'product_ids':['S01'],**extra})

    def closeout(self):
        b=self.budget();self.ws.study_budget=b
        with b.connect() as db:db.execute("INSERT INTO flags VALUES ('stage_closeout','engineering explicit stage')")
        return b

    def test_s01_scoped_intervals_use_actual6and8cluster_df(self):
        ref=self.csv();r=self.inspect(ref,site_groups={'six':['C01','C02','C03','C04','C05','C06']})
        self.assertTrue(r['ok'],r);s=r['statistics'];self.assertFalse(s['is_new_sample']);self.assertFalse(s['scientific_certification'])
        all=s['estimates']['all_selected_sites'];six=s['estimates']['six']
        self.assertEqual((all['df'],six['df']),(7,5));self.assertEqual(all['estimate'],9);self.assertEqual(six['estimate'],7)
        self.assertAlmostEqual(six['interval'][1],7+t.ppf(.9875,5)*six['se']);self.assertEqual(s['scope']['hours_observed'],[7,8])

    def test_s02_first_observed_hour_and_control_zero_hours_never_pooled(self):
        r=self.inspect(self.csv(),'inventory_by_arm');self.assertTrue(r['ok'],r)
        g=r['statistics']['groups'];self.assertEqual(g['1:S01']['first_observed_hours'],[7]);self.assertEqual(g['1:S01']['first_observed_stock_counts'],{'100.0':8})
        self.assertEqual(g['0:S01']['zero_opening_inventory_sku_hour_rows'],16);self.assertEqual(g['1:S01']['zero_opening_inventory_sku_hour_rows'],0)

    def test_s03_same_sandbox_calculator_available_to_critic(self):
        ref=self.csv();h,r,a=self.assessed();inputs=self.folder/'inputs';export_snapshot(self.ws,inputs,a['ref'])
        peer=Reviewer(self.folder/'peer',inputs,{'research_profile':'paired_critic_v1','model_config':fixtures.MODEL,'limits':self.ws.settings['limits']});self.addCleanup(peer.close)
        args={'source_ref':ref,'analysis':'daily_sales_effect','product_ids':['S01'],'comparison_product_ids':['S02']}
        out=peer.call('inspect_evidence',args,'peer-statistic');self.assertTrue(out['ok'],out)
        self.assertEqual(out['statistics']['estimates']['all_selected_sites']['estimate'],9)
        self.assertEqual(len(self.ws.tools),15);self.assertEqual(len(peer.tools),7)

    def test_s04_bad_scope_fails_without_inventing_zero_or_reading_private_path(self):
        ref=self.csv();r=self.inspect(ref,site_groups={'bad':['C99']});self.assertFalse(r['ok']);self.assertNotIn('statistics',r)
        unknown=self.inspect('/etc/passwd');self.assertFalse(unknown['ok'])

    def test_s05_version_bound_repair_flags_downstream_and_rebuilds(self):
        k=self.save(knowledge_updates=[{'kind':'method','statement':'工程旧错误','scope':'工程','status':'tentative','evidence_refs':[self.source()],'research_use':'反例'}])['knowledge_refs'][0]
        dependent=self.save(evidence_refs=[k])['ref'];h,r,a,q=self.seeded(k)
        args=self.reply(q,r,'accept');args['object_reviews']=[{'target_ref':k,'expected_version':digest(self.ws.record(k)),'decision':'withdraw','reason':'实际原件说明方法不成立','evidence_refs':[r['ref']]}]
        b=self.call('respond_to_review',args);self.assertIn('ref',b,b)
        self.assertFalse(lifecycle(self.ws.db,k)['eligible_as_current_premise']);self.assertTrue(lifecycle(self.ws.db,dependent)['explicit_dependency_reviews'])
        self.assertTrue(self.ws.clearance(a['ref']));self.assertEqual(self.ws.unanswered(),[])
        self.ws._rebuild_reviews();self.assertEqual(lifecycle(self.ws.db,k)['status'],'withdraw');self.assertTrue(lifecycle(self.ws.db,dependent)['explicit_dependency_reviews'])

    def test_s06_wrong_version_or_unaffected_object_cannot_change_memory(self):
        h,r,a,q=self.seeded();args=self.reply(q,r,'revise');args['object_reviews']=[{'target_ref':a['ref'],'expected_version':'wrong','decision':'withdraw','reason':'工程','evidence_refs':[r['ref']]}]
        self.assertFalse(self.call('respond_to_review',args)['ok']);self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'active');self.assertEqual(self.ws.records('review_response'),[])
        args['object_reviews'][0].update(target_ref=h['ref'],expected_version=digest(h));self.assertFalse(self.call('respond_to_review',args)['ok'])

    def test_s07_original_components_and_auxiliary_artifacts_do_not_replace_formalR(self):
        h,r,a=self.assessed();args={k:a[k] for k in ['hypothesis_ref','result_refs','status','prediction_coverage','rationale','deviations','counterevidence_refs','limitations']}
        args.update(supporting_artifact_refs=[self.source()],component_adjudications=[{'original_criterion':h['falsification'],'disposition':'unresolved','rationale':'原条件单独记录','evidence_refs':[r['ref']]}],supersedes_assessment_ref=a['ref'])
        saved=self.call('record_assessment',args);self.assertIn('ref',saved,saved);self.assertEqual(saved['result_refs'],[r['ref']])
        args['component_adjudications'][0]['original_criterion']='newposthoccriterion';self.assertFalse(self.call('record_assessment',args)['ok'])

    def test_s08_feedback_description_terms_are_actually_searchable(self):
        h,r,a=self.assessed();job=self.ws.jobs('pending')[0];issue=self.issue(a['ref']);issue['description']='uniquescopeword'
        with self.ws.db:q=self.ws.apply_review(job['ref'],fixtures.review(a['ref'],r['action_ref'],issues=[issue],open_issue_ids=['scope']),author='engineering')
        found=self.call('search_memory',{'kind':'review','query':'uniquescopeword'});self.assertIn(q['ref'],[v['ref'] for v in found['hits']])
        with self.assertRaises(ValueError):self.ws.premise(q['ref'])

    def test_s09_explicit_unpaid_deferral_can_deliver_without_promoting_judgment(self):
        h,r,a=self.assessed();self.save();b=self.closeout();job=self.ws.jobs('pending')[0]
        draft=self.call('finish_research',{'assessment_refs':[],'other_hypotheses':{h['ref']:'原判断未核验，本阶段不发布为成果'},'limitations':['有限工程交付'],'open_questions':['待核验'],'measurement_requests':[],'deferred_review_jobs':{job['ref']:'资源内暂缓未发表判断'}})
        self.assertIn('ref',draft,draft);self.assertEqual(self.ws.job(job['ref'])['status'],'deferred');self.assertFalse(self.ws.clearance(a['ref']))
        pending=self.ws.jobs('pending')[0]
        with self.ws.db:self.ws.apply_review(pending['ref'],fixtures.review(draft['ref'],r['action_ref']),author='engineering');self.ws.try_seal_report()
        final=self.ws.report();self.assertIsNotNone(final);self.assertEqual(final['stage_status'],'inconclusive');self.assertIn(a['ref'],final['all_assessment_refs']);self.assertEqual(final['assessment_refs'],[])

    def test_s10_deferral_cannot_hide_a_published_or_paid_target(self):
        self.make('independent');h,r,a=self.assessed();self.save();b=self.closeout();job=self.ws.jobs('pending')[0]
        args={'assessment_refs':[a['ref']],'other_hypotheses':{},'limitations':['工程'],'open_questions':[],'measurement_requests':[],'deferred_review_jobs':{job['ref']:'工程'}}
        self.assertFalse(self.call('finish_research',args)['ok']);self.assertEqual(self.ws.job(job['ref'])['status'],'pending')
        with b.connect() as db:db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',('engineering-paid-role','critic:'+job['ref'],1,1,'engineering','settled'))
        args.update(assessment_refs=[],other_hypotheses={h['ref']:'未决'});self.assertFalse(self.call('finish_research',args)['ok']);self.assertEqual(self.ws.records('report_draft'),[])

    def test_s11_all_role_cost_triggers_persistent_closeout(self):
        h,r,a=self.assessed();b=self.budget();run=ResearchRun(self.folder/'self',self.ws,fixtures.MODEL,b)
        with b.connect() as db:db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',('engineering-policy-cost','critic:engineering',1800000,1800000,'engineering','settled'))
        run.start_closeout();self.assertTrue(self.ws.closeout());self.assertEqual(b.snapshot()['accounted_tokens'],1800000)
        again=ResearchRun(self.folder/'self',self.ws,fixtures.MODEL,b);again.start_closeout();self.assertTrue(self.ws.closeout())

    def test_s12_realJournal_paid_response_retained_and_no_double_charge(self):
        h,r,a,q=self.seeded();b=self.budget();run=ResearchRun(self.folder/'self',self.ws,fixtures.MODEL,b)
        payload=run.runtime.payload(run.runtime.initial());args=self.reply(q,r)
        raw=raw_call('respond_to_review',args);raw['usage']={'total_tokens':13}
        with patch('experiments.insight_research.paired_v01.budget.request_model',return_value={'response':raw}) as provider:
            first=run.journal.call(payload);same=run.journal.call(payload)
        self.assertEqual(provider.call_count,1);self.assertEqual(first['response'],same['response']);self.assertEqual(b.snapshot()['accounted_tokens'],13);self.assertEqual(b.snapshot()['http_attempts'],1)

    def test_s13_realJournals_end_to_end_repair_and_peer_inspection_charge_both_roles(self):
        self.make('independent');h,r,a,q=self.seeded();self.save();b=self.budget();root=self.folder/'independent'
        reply=self.reply(q,r,'revise');reply['object_reviews']=[{'target_ref':a['ref'],'expected_version':digest(self.ws.record(a['ref'])),'decision':'withdraw','reason':'工程范围撤下旧判断','evidence_refs':[r['ref']]}]
        count={'owner':0,'peer':0}
        def provider(config,payload):
            if any(t['function']['name']=='record_review' for t in payload['tools']):
                count['peer']+=1;job=next(j for j in self.ws.jobs('running') if self.ws.record(j['target_ref'])['record_type']=='report_draft')
                if count['peer']==1:raw=raw_call('inspect_evidence',{'source_ref':self.source(),'analysis':'record_balance','product_ids':['S01']})
                else:
                    import sqlite3
                    with sqlite3.connect(root/'reviews'/job['ref']/'critic/private/critic.sqlite') as db:action=db.execute('SELECT ref FROM actions ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                    raw=raw_call('record_review',fixtures.review(job['target_ref'],action))
            else:
                count['owner']+=1
                raw=raw_call('respond_to_review',reply) if count['owner']==1 else raw_call('finish_research',{'assessment_refs':[],'other_hypotheses':{h['ref']:'原判断撤下，工程阶段未决'},'limitations':['不是科研效果'],'open_questions':['未决'],'measurement_requests':[]})
            raw['usage']={'total_tokens':19};return {'response':raw}
        with patch('experiments.insight_research.paired_v01.budget.request_model',side_effect=provider):out=ResearchRun(root,self.ws,fixtures.MODEL,b).run(8)
        self.assertEqual(out['status'],'completed',out);self.assertEqual(count,{'owner':2,'peer':2})
        self.assertEqual(b.snapshot()['http_attempts'],4);self.assertEqual(b.snapshot()['accounted_tokens'],76)
        self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'withdraw');self.assertEqual(self.ws.report()['stage_status'],'inconclusive')

    def test_s14_closeout_keeps_formed_hypothesis_but_stops_new_trial_and_numeric_guard_remains(self):
        self.closeout()
        h=self.call('save_hypothesis',{'kind':'business','statement':'工程已形成预测','scope':'工程8柜点','prediction':'增加至少一百万','falsification':'未达到阈值','alternatives':['未决'],'evidence_refs':[self.source()],
            'effect_prediction':{'outcome_product_ids':['S11'],'site_ids':[],'direction':'increase','minimum_effect':1000000}})
        self.assertIn('ref',h,h)
        p=self.call('register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'登记供给对比','observation_unit':'site-day','allocation_unit':'site-day','analysis':'后端原估计量','purpose':'工程门禁','data_refs':[self.source()],
            'mode':'protocol','protocol_id':'support_supply:S11','outcome_product_ids':['S11'],'expected_changed_variables':['morning_stock:S11']})
        self.assertIn('ref',p,p);self.assertFalse(self.call('run_test',{'plan_ref':p['ref']})['ok']);self.assertEqual(self.ws.trials_started(),0)

    def test_s15_numeric_guard_unchanged_with_component_adjudication(self):
        h=self.call('save_hypothesis',{'kind':'business','statement':'工程量化门禁','scope':'工程8柜点','prediction':'增加至少一百万','falsification':'未达到阈值','alternatives':['未决'],'evidence_refs':[self.source()],
            'effect_prediction':{'outcome_product_ids':['S11'],'site_ids':[],'direction':'increase','minimum_effect':1000000}})
        p=self.call('register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'登记供给对比','observation_unit':'site-day','allocation_unit':'site-day','analysis':'后端原估计量','purpose':'工程门禁','data_refs':[self.source()],
            'mode':'protocol','protocol_id':'support_supply:S11','outcome_product_ids':['S11'],'expected_changed_variables':['morning_stock:S11']})
        r=self.call('run_test',{'plan_ref':p['ref']});self.assertIn('ref',r,r)
        args={'hypothesis_ref':h['ref'],'result_refs':[r['ref']],'status':'supported','prediction_coverage':'工程错误通过','rationale':'不得绕门禁','deviations':[],'counterevidence_refs':[],'limitations':['工程']}
        self.assertFalse(self.call('record_assessment',args)['ok'])
        args.update(status='unresolved',component_adjudications=[{'original_criterion':h['falsification'],'disposition':'triggered','rationale':'原条款单独披露，整体仍不作机制认证','evidence_refs':[r['ref']]}])
        self.assertIn('ref',self.call('record_assessment',args))

    def test_s16_old_superseded_assessment_cannot_be_restored_by_reply(self):
        h,r,a,q=self.seeded();args={k:a[k] for k in ['hypothesis_ref','result_refs','status','prediction_coverage','rationale','deviations','counterevidence_refs','limitations']}
        args.update(status='unresolved',supersedes_assessment_ref=a['ref']);new=self.call('record_assessment',args);self.assertIn('ref',new,new)
        reply=self.reply(q,r,'revise');reply['object_reviews']=[{'target_ref':a['ref'],'expected_version':digest(self.ws.record(a['ref'])),'decision':'restore','reason':'不应复活被替换旧判断','evidence_refs':[r['ref']]}]
        self.assertFalse(self.call('respond_to_review',reply)['ok']);self.assertEqual(lifecycle(self.ws.db,a['ref'])['status'],'superseded')

    def test_s17_program_binds_omitted_version_to_exact_received_issue_object(self):
        h,r,a,q=self.seeded();reply=self.reply(q,r,'revise');reply['object_reviews']=[{'target_ref':a['ref'],'decision':'quarantine','reason':'保留原件并隔离待查判断','evidence_refs':[r['ref']]}]
        out=self.call('respond_to_review',reply);self.assertIn('ref',out,out)
        saved=self.ws.record(out['ref']);self.assertEqual(saved['object_reviews'][0]['expected_version'],q['affected_versions'][a['ref']])
        read=self.call('read_memory',{'ref':a['ref']});self.assertEqual(read['original_version'],digest(self.ws.record(a['ref'])))

if __name__=='__main__':unittest.main()
