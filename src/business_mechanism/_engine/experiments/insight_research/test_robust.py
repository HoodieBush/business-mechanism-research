"""Actual composition, numeric contracts, memory repair and exact-repeat tests."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from scipy.stats import t
from .common import ROOT, Pending, encoded
from .composed_world import ComposedWorld, MECHANISMS
from .robust import RobustWorkspace
from .runtime_robust import RobustRuntime
from .statistics import estimate, prediction_verdict
from .test_acceptance import MODEL, settings, hypothesis, state, raw_call, FixtureJournal
from . import test_acceptance as fixtures
from world import OfficeWorld


class SceneTests(unittest.TestCase):
    def record(self,name,data):
        configured=os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        if configured:
            path=Path(configured)/'private_scene_diagnostics'/(name+'.json'); path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x') as stream: json.dump(data,stream,ensure_ascii=False,indent=2)

    def test_01_independent_switches_match_four_legacy_scenes(self):
        for flag,kind in [('cutlery_demand','relationship'),('supply_selection','confounding'),
                          ('sales_underrecording','record_fault'),('site_weekday','site_weekday')]:
            with self.subTest(flag=flag):
                new=ComposedWorld(mechanisms=[flag]); old=OfficeWorld(kind,9137,'office-business-v0.4')
                a,b=new.generate(0,7); x,y=old.generate(0,7)
                pd.testing.assert_frame_equal(a,x,check_like=True)
                pd.testing.assert_frame_equal(b,y,check_like=True)
                self.record(flag,{'rows':len(a),'recorded_sales':int(a.sales.sum()),'business_day_units':len(b),'single_switch_matches_legacy':True})

    def test_02_all_enabled_and_masks_have_distinct_identity(self):
        self.assertEqual(set(ComposedWorld().mechanisms),set(MECHANISMS))
        self.assertEqual(ComposedWorld(mechanisms=[]).mechanisms,())
        for bad in (['unknown'],['cutlery_demand']*2):
            with self.assertRaises(ValueError): ComposedWorld(mechanisms=bad)
        self.record('composition_identity',{'version':ComposedWorld().scenario_version,'default_mechanisms':ComposedWorld().mechanisms})

    def test_03_observation_error_does_not_change_physical_inventory(self):
        a,profit=ComposedWorld().generate(0,14)
        b,correct=ComposedWorld().generate(0,14,corrected=True)
        self.assertTrue((a.sales!=b.sales).any())
        pd.testing.assert_frame_equal(a.drop(columns='sales'),b.drop(columns='sales'))
        pd.testing.assert_frame_equal(profit,correct)
        self.assertTrue((b.opening_stock+b.restock-b.closing_stock==b.sales).all())
        self.record('observation_and_physical_flow',{'mismatched_rows':int((a.sales!=b.sales).sum()),'physical_inventory_unchanged':True,'corrected_reconciliation_all_equal':True})

    def test_04_demand_and_calendar_effects_remain_when_stacked(self):
        full=ComposedWorld(); without=ComposedWorld(mechanisms=[x for x in MECHANISMS if x!='cutlery_demand'])
        a,_=full.generate(0,14,corrected=True); b,_=without.generate(0,14,corrected=True)
        self.assertLess(a[a.sku=='S01'].sales.sum(),b[b.sku=='S01'].sales.sum())
        neutral=ComposedWorld(mechanisms=[x for x in MECHANISMS if x!='site_weekday'])
        for site,ratio in [('C01',.55),('C05',1.45),('C02',1.)]:
            self.assertAlmostEqual(full.day_context(4,site)[0]/neutral.day_context(4,site)[0],ratio)
        for site in ('C01','C05'): self.assertEqual(full.day_context(3,site),neutral.day_context(3,site))
        self.record('stacked_demand',{'all_on_physical_S01_sales':int(a[a.sku=='S01'].sales.sum()),'without_cutlery_effect_S01_sales':int(b[b.sku=='S01'].sales.sum()),'calendar_ratios':{'C01':.55,'C05':1.45,'C02':1.}})

    def test_05_supply_selection_changes_plans_not_base_traffic(self):
        full=ComposedWorld(); without=ComposedWorld(mechanisms=[x for x in MECHANISMS if x!='supply_selection'])
        differences=0
        for day in range(30):
            for site in ('C01','C05','C08'):
                a,b=full.day_context(day,site),without.day_context(day,site)
                self.assertEqual(a[0],b[0]); differences+=a[1]!=b[1]
        self.assertGreater(differences,0)
        self.record('stacked_supply_selection',{'different_support_plans':differences,'compared_contexts':90,'base_traffic_equal':True})


class NumericTests(unittest.TestCase):
    def test_01_reproduces_actual_receipt_and_correct_confidence(self):
        workspace=ROOT/'experiments/studies/SCI-023/results/research/case/workspace'
        rows=pd.read_csv(workspace/'science/tests/Pa748e631f9bd4098/observations.csv')
        selected=['S'+str(i).zfill(2) for i in range(1,12)]
        actual=estimate(rows,selected); target=estimate(rows,['S01'])
        self.assertAlmostEqual(actual['estimate'],9.)
        np.testing.assert_allclose(actual['interval'],[-37.02890847290939,55.02890847290938])
        np.testing.assert_allclose(target['interval'],[-7.792812997241863,6.642812997241863])
        self.assertEqual(target['critical_quantile'],.9875)
        self.assertEqual(prediction_verdict(target,{'minimum_effect':2.,'direction':'increase'}),'unresolved')

    def test_02_direction_magnitude_and_small_cluster_guards(self):
        self.assertEqual(prediction_verdict({'interval':[3.,5.]},{'minimum_effect':2.,'direction':'increase'}),'supported')
        self.assertEqual(prediction_verdict({'interval':[-1.,1.]},{'minimum_effect':2.,'direction':'increase'}),'refuted')
        self.assertEqual(prediction_verdict({'interval':[-5.,-3.]},{'minimum_effect':2.,'direction':'decrease'}),'supported')
        rows=pd.DataFrame([{'site':'A','day':0,'treatment':0,'sku':'S01','sales':1},{'site':'A','day':1,'treatment':1,'sku':'S01','sales':2}])
        with self.assertRaises(ValueError): estimate(rows,['S01'])


class RobustTests(unittest.TestCase):
    call=fixtures.ResearchTests.call
    h=fixtures.ResearchTests.h
    file=fixtures.ResearchTests.file
    plan=fixtures.ResearchTests.plan

    def setUp(self):
        configured=os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        self.temp=None if configured else tempfile.TemporaryDirectory(prefix='ic_')
        self.folder=Path(configured or self.temp.name)/self._testMethodName
        self.folder.mkdir(parents=True,exist_ok=False)
        self.world=ComposedWorld()
        self.ws=RobustWorkspace(self.folder/'workspace','研究有数据依据的业务关系',self.world,settings())
        self.counter=0

    def tearDown(self):
        self.ws.close()
        if self.temp: self.temp.cleanup()

    def knowledge(self,**changes):
        return {'kind':'observation','statement':'历史有60个营业日','scope':'给定历史资料','status':'tentative',
            'evidence_refs':[self.file('observed_facts.json')],'counterevidence_refs':[],
            'hypothesis_refs':[],'tags':['营业日'],'research_use':'核对分析单位',
            'supersedes_ref':None,'revision_reason':'','measurements':[],**changes}

    def save_state(self,h=None,**changes):
        active=[h['ref']] if h else []
        return self.call('update_research_state',state(active_hypothesis_refs=active,focus_hypothesis_refs=active,**changes))

    def trial(self):
        h=self.h(statement='提高指定供给对S01记录销量有正效应',prediction='预先指定目标S01的站内销量差应为正',
            effect_prediction={'outcome_product_ids':['S01'],'direction':'increase','minimum_effect':0.})
        p=self.plan(h,mode='protocol',code=None,protocol_id='support_supply:S11',outcome_product_ids=['S01'],
            expected_changed_variables=['morning_stock:S11'],outcome_groups={'comparison':['S02'],'nonfresh':['S03','S04']})
        self.assertIn('ref',p,p)
        r=self.call('run_test',{'plan_ref':p['ref']}); self.assertTrue(r['ok'])
        return h,p,self.ws.record(r['ref'])

    def test_r01_observed_dimensions_and_private_scene_boundary(self):
        context=self.ws.context(); self.assertEqual(context['observed_history_facts']['business_days'],60)
        self.assertEqual(context['observed_history_facts']['row_count'],57600)
        self.assertEqual(len(self.ws.tool_schemas()),12)
        for private in MECHANISMS: self.assertNotIn(private,encoded(context))
        self.assertNotIn('private_scene_switches',encoded(context))

    def test_r02_bad_dimension_rejected_and_valid_binding_resolves_exact_value(self):
        source=self.file('observed_facts.json')
        bad=self.knowledge(measurements=[{'source_ref':source,'field':'business_days','value':82.}])
        rejected=self.save_state(knowledge_updates=[bad])
        self.assertIn('ref',rejected); self.assertEqual(len(rejected['knowledge_rejections']),1)
        self.assertEqual(self.ws.records('knowledge'),[])
        good=self.knowledge(measurements=[{'source_ref':source,'field':'business_days'}])
        k=self.save_state(knowledge_updates=[good])['knowledge_refs'][0]
        self.assertEqual(self.ws.knowledge_view(k)['bound_measurements'][0]['value'],60)

    def test_r03_quarantine_excludes_default_retrieval_but_exact_read_warns(self):
        k=self.save_state(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        self.save_state(memory_reviews=[{'target_ref':k,'decision':'quarantine','reason':'需要依据实际资料复核','evidence_refs':[self.file('observed_facts.json')]}])
        self.assertEqual(self.call('search_memory',{'kind':'knowledge'})['total'],0)
        self.assertEqual(self.ws.context()['research_knowledge'],[])
        read=self.call('read_memory',{'ref':k}); self.assertEqual(read['review']['status'],'quarantine')
        self.assertEqual(json.loads(read['text'])['statement'],'历史有60个营业日')

    def test_r04_revision_keeps_old_record_and_does_not_taint_correct_replacement(self):
        k=self.save_state(knowledge_updates=[self.knowledge(statement='旧的未经核对解释')])['knowledge_refs'][0]
        original=deepcopy(self.ws.record(k))
        new=self.save_state(knowledge_updates=[self.knowledge(supersedes_ref=k,revision_reason='以实际维度资料修订',
            measurements=[{'source_ref':self.file('observed_facts.json'),'field':'business_days'}])])['knowledge_refs'][0]
        self.assertEqual(self.ws.record(k),original)
        old=self.call('read_memory',{'ref':k}); self.assertEqual(old['replacement_ref'],new)
        self.assertEqual(old['review']['status'],'superseded')
        self.assertEqual(self.ws.review(new)['explicit_dependency_reviews'],[])
        self.assertEqual(self.call('search_memory',{'kind':'knowledge'})['hits'][0]['ref'],new)

    def test_r05_explicit_dependents_marked_and_reviewed_without_rewriting_hypothesis(self):
        k=self.save_state(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        h=self.h(evidence_refs=[k],used_memory_refs=[k]); original=deepcopy(h)
        evidence=[self.file('observed_facts.json')]
        self.save_state(h,memory_reviews=[{'target_ref':k,'decision':'withdraw','reason':'撤回这个依据','evidence_refs':evidence}])
        self.assertIn(k,self.ws.card(h['ref'])['review']['explicit_dependency_reviews'])
        self.save_state(h,memory_reviews=[{'target_ref':h['ref'],'decision':'restore','reason':'原预测保留作为待检验猜想，不再以旧记忆为事实','evidence_refs':evidence}])
        self.assertEqual(self.ws.card(h['ref'])['review']['explicit_dependency_reviews'],[])
        self.assertEqual(self.ws.record(h['ref']),original)
        self.assertEqual(self.ws.review(k)['status'],'withdraw')

    def test_r06_rebuild_and_reopen_preserve_memory_review(self):
        k=self.save_state(knowledge_updates=[self.knowledge(status='needs_review')])['knowledge_refs'][0]
        before=self.ws.review(k); self.ws.rebuild_index(); self.assertEqual(self.ws.review(k),before)
        configured=deepcopy(self.ws.settings)
        self.ws.close(); self.ws=RobustWorkspace(self.folder/'workspace','研究有数据依据的业务关系',self.world,configured,reopen=True)
        self.assertEqual(self.ws.review(k),before)
        self.assertEqual(self.call('search_memory',{'kind':'knowledge'})['total'],0)

    def test_r07_optional_claim_rejection_preserves_checkpoint_and_replay_is_idempotent(self):
        bad=self.knowledge(evidence_refs=['file:missing'])
        result=self.save_state(knowledge_updates=[self.knowledge(),bad])
        self.assertIn('ref',result); self.assertEqual(len(self.ws.records('knowledge')),1)
        self.assertEqual(len(result['knowledge_rejections']),1)
        args={'ref':self.file('business_brief.md')}
        one=self.call('read_artifact',args,'fixed'); two=self.call('read_artifact',args,'fixed')
        self.assertEqual(one,two)
        self.assertEqual(self.ws.db.execute('SELECT count FROM loop_counter WHERE id=1').fetchone()[0],1)

    def test_r08_normal_review_is_not_a_loop_but_unchanged_reads_pause(self):
        ref=self.file('business_brief.md')
        journal=FixtureJournal([raw_call('read_artifact',{'ref':ref}) for _ in range(5)])
        runtime=RobustRuntime(self.ws,MODEL,journal=journal)
        result=runtime.run(6)
        self.assertEqual(result['status'],'pending'); self.assertIn('repeated action',result['reason'])
        self.assertEqual(len(journal.requests),5)
        self.call('read_artifact',{'ref':self.file('data_dictionary.json')})
        self.assertEqual(self.ws.db.execute('SELECT blocked FROM loop_counter WHERE id=1').fetchone()[0],0)

    def test_r09_changed_page_and_sql_are_allowed_and_notice_is_archived_exactly(self):
        ref=self.file('business_brief.md')
        for i in range(3): result=self.call('read_artifact',{'ref':ref})
        self.assertIn('loop_notice',result)
        archived=json.loads(self.ws.db.execute('SELECT body FROM events ORDER BY id DESC LIMIT 1').fetchone()[0])
        self.assertEqual(archived['result'],result)
        page=self.call('read_artifact',{'ref':ref,'offset':100,'limit':100})
        self.assertNotIn('loop_guard',page)
        query=self.call('query_data',{'sql':'select count(*) from hourly','purpose':'new actual question'})
        self.assertEqual(query['preview'][0][0],57600)

    def test_r10_trial_labels_primary_secondary_calendar_and_confidence(self):
        h,p,r=self.trial(); stats=r['actual_execution']['statistics']
        self.assertEqual(stats['primary']['product_ids'],['S01'])
        self.assertEqual(stats['primary']['critical_quantile'],.9875)
        self.assertEqual(stats['calendar']['calendar_days_requested'],14)
        self.assertEqual(stats['calendar']['business_days_observed'],10)
        self.assertEqual(stats['primary']['site_day_units'],80)
        self.assertEqual(stats['secondary']['comparison']['product_ids'],['S02'])
        again=self.call('run_test',{'plan_ref':p['ref']})
        self.assertEqual(again['ref'],r['ref']); self.assertEqual(self.ws.trials_started(),1)

    def test_r11_wrong_primary_and_false_numeric_verdict_are_rejected(self):
        h,p,r=self.trial()
        wrong=self.plan(h,mode='protocol',code=None,protocol_id='support_supply:S11',outcome_product_ids=['S11'],expected_changed_variables=['morning_stock:S11'])
        self.assertFalse(wrong['ok'])
        correct=r['actual_execution']['statistics']['prediction_check']['compatible_verdict']
        wrong_verdict='refuted' if correct!='refuted' else 'supported'
        args={'hypothesis_ref':h['ref'],'result_refs':[r['ref']],'status':wrong_verdict,
            'prediction_coverage':'数字判据夹具','rationale':'故意错误结论','deviations':[],
            'counterevidence_refs':[],'limitations':['工程夹具，不作科学认证']}
        self.assertFalse(self.call('record_assessment',args)['ok'])
        accepted=self.call('record_assessment',{**args,'status':'unresolved','rationale':'保留实际不确定性'})
        self.assertIn('ref',accepted)

    def test_r12_wrong_confidence_memory_rejected_valid_measurement_retained(self):
        h,p,r=self.trial()
        claim={'source_ref':r['ref'],'field':'confidence','value':.95}
        bad=self.knowledge(evidence_refs=[r['ref']],measurements=[claim])
        rejected=self.save_state(h,incorporated_result_refs=[r['ref']],knowledge_updates=[bad])
        self.assertEqual(len(rejected['knowledge_rejections']),1)
        self.assertEqual(self.ws.unincorporated(),[])
        good=self.knowledge(evidence_refs=[r['ref']],measurements=[{**claim,'value':.975}])
        receipt=self.save_state(h,incorporated_result_refs=[r['ref']],knowledge_updates=[good])
        self.assertIn('ref',receipt)
        self.assertEqual(self.ws.knowledge_view(receipt['knowledge_refs'][0])['bound_measurements'][0]['value'],.975)

    def test_r13_actual_sandbox_denies_private_generator_and_identity(self):
        targets=[str(ROOT/'experiments/insight_research/composed_world.py'),str(self.ws.private/'identity.json')]
        code='from pathlib import Path\nfor path in '+repr(targets)+':\n try:\n  Path(path).read_bytes()\n  print("LEAK")\n except PermissionError:\n  print("DENIED")'
        result=self.call('run_python',{'code':code,'purpose':'验证私有源码及场景开关实际读取边界'})
        self.assertTrue(result['execution']['ok']); self.assertEqual(result['execution']['stdout'].split(),['DENIED','DENIED'])

    def test_r14_corrected_memory_survives_window_rebuild_with_old_dialogue_retained(self):
        k=self.save_state(knowledge_updates=[self.knowledge(statement='旧的错误营业天数解释')])['knowledge_refs'][0]
        new=self.save_state(knowledge_updates=[self.knowledge(supersedes_ref=k,revision_reason='用实际观测维度修复',
            measurements=[{'source_ref':self.file('observed_facts.json'),'field':'business_days'}])])['knowledge_refs'][0]
        runtime=RobustRuntime(self.ws,MODEL,journal=FixtureJournal([]))
        runtime.cp['responses']=4
        runtime.cp['messages']=runtime.initial()+[{'role':'assistant','content':'历史曾说有82天，此处故意保留旧原对话'}]
        runtime.compact(); context=json.loads(runtime.cp['messages'][1]['content'])
        self.assertEqual(context['research_knowledge'][0]['ref'],new)
        self.assertTrue(any(x['ref']==k and x['status']=='superseded' for x in context['memory_review_queue']))
        self.assertTrue(context['session_progress']['continuing_same_research'])
        self.assertEqual(self.call('read_memory',{'ref':k})['replacement_ref'],new)

    def test_r15_registered_fixture_is_explicit_idempotent_and_not_model_discovery(self):
        from .repair_fixture import prepare
        prepare(self.ws,{'initialization':'memory_repair_v1'})
        self.assertEqual(len(self.ws.records('knowledge')),2)
        self.assertEqual(len(self.ws.records('hypothesis')),1)
        before=self.ws.db.execute('SELECT count(*) FROM records').fetchone()[0]
        (self.ws.private/'repair_fixture.json').unlink()
        prepare(self.ws,{'initialization':'memory_repair_v1'})
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM records').fetchone()[0],before)
        self.assertEqual(self.ws.trials_started(),0)
        self.assertIn('test harness',self.ws.context()['initialization_notice'])
        self.assertEqual({x['author'] for x in self.ws.records('knowledge')},{'test_harness'})

    def test_r16_new_knowledge_cannot_clear_inherited_review_flag(self):
        evidence=[self.file('observed_facts.json')]
        k=self.save_state(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        self.save_state(memory_reviews=[{'target_ref':k,'decision':'quarantine','reason':'依据待核对','evidence_refs':evidence}])
        child=self.save_state(knowledge_updates=[self.knowledge(evidence_refs=[k])])['knowledge_refs'][0]
        self.assertIn(k,self.ws.review(child)['explicit_dependency_reviews'])
        self.assertEqual(self.call('search_memory',{'kind':'knowledge'})['total'],0)
        self.assertFalse(self.save_state(evidence_refs=[child])['ok'])
        self.ws.rebuild_index()
        self.assertIn(k,self.ws.review(child)['explicit_dependency_reviews'])

    def test_r17_restoring_parent_requires_separate_descendant_review(self):
        evidence=[self.file('observed_facts.json')]
        k=self.save_state(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        h=self.h(evidence_refs=[k],used_memory_refs=[k])
        self.save_state(h,memory_reviews=[{'target_ref':k,'decision':'quarantine','reason':'需要重新核对','evidence_refs':evidence}])
        self.save_state(h,memory_reviews=[{'target_ref':k,'decision':'restore','reason':'仅复核此条，后代尚待检查','evidence_refs':evidence}])
        self.assertEqual(self.ws.review(k)['status'],'active')
        self.assertIn(k,self.ws.review(h['ref'])['explicit_dependency_reviews'])
        self.ws.rebuild_index()
        self.assertIn(k,self.ws.review(h['ref'])['explicit_dependency_reviews'])
        self.save_state(h,memory_reviews=[{'target_ref':h['ref'],'decision':'restore','reason':'单独核对这个假说后保留为猜想','evidence_refs':evidence}])
        self.assertEqual(self.ws.review(h['ref'])['explicit_dependency_reviews'],[])


    def test_r18_single_site_estimator_rejected_before_trial_registration(self):
        rejected=self.h(effect_prediction={'outcome_product_ids':['S01'],'site_ids':['C01']})
        self.assertFalse(rejected['ok']); self.assertIn('at least two',rejected['error'])
        self.assertEqual(self.ws.records('hypothesis'),[])
        self.assertEqual(self.ws.trials_started(),0)

    def test_r19_verified_measurement_source_is_added_without_duplicate_input(self):
        source=self.file('observed_facts.json')
        note=self.knowledge(evidence_refs=[self.file('business.sqlite')],measurements=[{'source_ref':source,'field':'business_days'}])
        k=self.save_state(knowledge_updates=[note])['knowledge_refs'][0]
        self.assertIn(source,self.ws.record(k)['evidence_refs'])
        self.assertEqual(self.ws.knowledge_view(k)['bound_measurements'][0]['value'],60)
        self.assertNotIn(source,note['evidence_refs'])

    def test_r20_unsupported_binding_has_actionable_lawful_repair(self):
        h=self.h(); p=self.plan(h); r=self.call('run_test',{'plan_ref':p['ref']})
        note=self.knowledge(evidence_refs=[r['ref']],measurements=[{'source_ref':r['ref'],'field':'business_days'}])
        rejected=self.save_state(h,incorporated_result_refs=[r['ref']],knowledge_updates=[note])
        self.assertIn('ref',rejected)
        self.assertIn(self.file('observed_facts.json'),rejected['knowledge_rejections'][0]['error'])
        self.assertIn('without measurements',rejected['knowledge_rejections'][0]['error'])
        note['measurements'][0]['source_ref']=self.file('observed_facts.json')
        accepted=self.save_state(h,incorporated_result_refs=[r['ref']],knowledge_updates=[note])
        self.assertIn('ref',accepted)


    def test_r21_false_target_does_not_invalidate_its_actual_counterevidence(self):
        k=self.save_state(knowledge_updates=[self.knowledge(statement='一个后来撤回的前提')])['knowledge_refs'][0]
        h=self.h(evidence_refs=[k],used_memory_refs=[k]); p=self.plan(h)
        r=self.call('run_test',{'plan_ref':p['ref']})
        a=fixtures.ResearchTests.assess(self,h,r)
        self.save_state(h,incorporated_result_refs=[r['ref']],memory_reviews=[{'target_ref':k,'decision':'withdraw','reason':'原前提错误；检验的原数据计数仍有效','evidence_refs':[self.file('observed_facts.json')]}])
        self.assertIn(k,self.ws.review(h['ref'])['explicit_dependency_reviews'])
        for record in (p,r,a): self.assertEqual(self.ws.review(record['ref'])['explicit_dependency_reviews'],[])
        new=self.save_state(h,knowledge_updates=[self.knowledge(evidence_refs=[r['ref'],a['ref']])])['knowledge_refs'][0]
        self.assertEqual(self.ws.review(new)['explicit_dependency_reviews'],[])
        self.save_state(h,memory_reviews=[{'target_ref':a['ref'],'decision':'withdraw','reason':'若实际判断本身被撤回，下游仍须复核','evidence_refs':[self.file('observed_facts.json')]}])
        self.assertIn(a['ref'],self.ws.review(new)['explicit_dependency_reviews'])

    def test_r22_existing_memory_can_be_reviewed_and_used_in_one_atomic_state(self):
        source=self.file('observed_facts.json')
        k=self.save_state(knowledge_updates=[self.knowledge(status='needs_review')])['knowledge_refs'][0]
        saved=self.save_state(evidence_refs=[k],memory_reviews=[{'target_ref':k,'decision':'restore','reason':'与公开维度逐项核对，保留此条','evidence_refs':[source]}])
        self.assertIn('ref',saved)
        self.assertEqual(self.ws.review(saved['ref'])['explicit_dependency_reviews'],[])
        self.ws.rebuild_index()
        self.assertEqual(self.ws.review(k)['status'],'active')
        self.assertEqual(self.ws.review(saved['ref'])['explicit_dependency_reviews'],[])

    def test_r23_inspiration_is_retained_without_treating_it_as_a_truth_premise(self):
        k=self.save_state(knowledge_updates=[self.knowledge(status='needs_review')])['knowledge_refs'][0]
        saved=self.save_state(used_memory_refs=[k])
        self.assertIn('ref',saved)
        self.assertEqual(self.ws.review(saved['ref'])['explicit_dependency_reviews'],[])
        rejected=self.save_state(evidence_refs=[k])
        self.assertFalse(rejected['ok']); self.assertIn(k,rejected['error'])

    def test_r24_missing_disposition_feedback_names_the_actual_hypothesis(self):
        h=self.h(); rejected=self.save_state()
        self.assertFalse(rejected['ok']); self.assertIn(h['ref'],rejected['error'])
        accepted=self.save_state(inactive_hypotheses={h['ref']:'本阶段暂不研究，原预测保留'})
        self.assertIn('ref',accepted)


    def test_r25_result_receipt_keeps_statistics_and_exact_original_without_protocol_duplication(self):
        h,p,r=self.trial()
        brief=self.call('run_test',{'plan_ref':p['ref']})
        self.assertEqual(brief['statistics'],r['actual_execution']['statistics'])
        self.assertEqual(brief['attachments'],r['attachments'])
        self.assertNotIn('actual_execution',brief)
        self.assertLess(len(encoded(brief)),.8*len(encoded(r)))
        parts=[]; offset=0
        while True:
            page=self.call('read_memory',{'ref':r['ref'],'offset':offset,'limit':18000}); parts.append(page['text'])
            if page['next_offset'] is None: break
            offset=page['next_offset']
        self.assertEqual(json.loads(''.join(parts)),r)
        self.assertEqual(self.ws.trials_started(),1)

    def test_r26_rejected_optional_scientific_claim_does_not_lose_unsaved_work(self):
        self.call('read_artifact',{'ref':self.file('business_brief.md')})
        self.assertTrue(self.ws.checkpoint_work()['pending'])
        saved=self.save_state(understanding='保留探索认识，尚无实际判断',knowledge_updates=[self.knowledge(status='supported_in_scope')])
        self.assertEqual(len(saved['knowledge_rejections']),1)
        self.assertEqual(self.ws.records('knowledge'),[])
        self.assertFalse(self.ws.checkpoint_work()['pending'])
        runtime=RobustRuntime(self.ws,MODEL,journal=FixtureJournal([]))
        runtime.cp['messages']=runtime.initial(); runtime.compact()
        self.assertEqual(json.loads(runtime.cp['messages'][1]['content'])['state']['understanding'],'保留探索认识，尚无实际判断')

    def test_r27_invalid_checkpoint_still_rolls_back_the_whole_action(self):
        result=self.save_state(evidence_refs=['file:missing'],knowledge_updates=[self.knowledge()])
        self.assertFalse(result['ok'])
        self.assertEqual(self.ws.records('state'),[])
        self.assertEqual(self.ws.records('knowledge'),[])

    def test_r28_warning_receipt_replay_does_not_duplicate_state_or_accepted_claims(self):
        args=state(knowledge_updates=[self.knowledge(),self.knowledge(status='supported_in_scope')])
        first=self.call('update_research_state',args,'checkpoint-warning')
        again=self.call('update_research_state',args,'checkpoint-warning')
        self.assertEqual(first,again)
        self.assertEqual(len(self.ws.records('state')),1)
        self.assertEqual(len(self.ws.records('knowledge')),1)
        self.assertEqual(len(first['knowledge_rejections']),1)


if __name__=='__main__': unittest.main()
