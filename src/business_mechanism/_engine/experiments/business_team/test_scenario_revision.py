"""Scenario/interface consistency checks, not task-specific answer grading."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from langgraph.checkpoint.sqlite import SqliteSaver
from contracts import HOURS
from scenario_contract import VERSION,operating_rules
from world import OfficeWorld
from workspace import sha
from development_evaluation import evaluate,describe,program
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles,role_task_context,TaskInputChangedError
from langgraph_migration.dependencies import resolve_task


class RevisedScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_scene_')
        cls.root=Path(cls.temp.name)
        cls.ws=ScientificWorkspace(cls.root/'scene',OfficeWorld('relationship',8917,VERSION))
        cls.conn=sqlite3.connect(cls.root/'checkpoint.sqlite',check_same_thread=False)
        cls.saver=SqliteSaver(cls.conn);FrameworkRoles(cls.ws,cls.saver,lambda role:None)
    @classmethod
    def tearDownClass(cls):cls.conn.close();cls.temp.cleanup()

    def test_public_objects_preserve_entities_and_morning_information(self):
        ws=self.ws
        with sqlite3.connect(ws.public/'business.sqlite') as db:
            hourly=pd.read_sql('SELECT * FROM hourly',db)
            plans=pd.read_sql('SELECT * FROM support_plans',db)
            features=pd.read_sql('SELECT * FROM prediction_features',db)
        self.assertEqual(len(hourly),len(ws.history))
        self.assertFalse(hourly.duplicated(['site','day','sku','hour']).any())
        self.assertFalse(plans.duplicated(['site','day','support_sku']).any())
        self.assertNotIn('s11_hour_start_stock',hourly)
        morning=hourly[hourly.hour==HOURS[0]].merge(plans,left_on=['site','day','sku'],right_on=['site','day','support_sku'],validate='one_to_one')
        self.assertTrue((morning.opening_stock==morning.planned_opening_stock).all())
        definitions=json.loads((ws.public/'data_dictionary.json').read_text())
        for col in features:
            self.assertIn('available_at',definitions['tables']['prediction_features']['columns'][col])
        for col in features.columns[features.columns.str.startswith('planned_')]:
            entity=definitions['tables']['prediction_features']['columns'][col]['entity']
            matched=features.merge(plans[plans.support_sku==entity],on=['site','day'],validate='many_to_one')
            self.assertTrue((matched[col]==matched.planned_opening_stock).all())
            joined=ws.history.merge(features[['site','day','sku','hour',col]],on=['site','day','sku','hour'],suffixes=('_history','_feature'),validate='one_to_one')
            self.assertTrue((joined[col+'_history']==joined[col+'_feature']).all())
        for outcome in ('sales','closing_stock','available_minutes'):self.assertNotIn(outcome,features)

    def test_capacity_contract_matches_actual_categories_and_trial_supply(self):
        ws=self.ws;rules=json.loads((ws.public/'operating_rules.json').read_text())
        self.assertEqual(rules,operating_rules())
        morning=ws.history[ws.history.hour==HOURS[0]]
        for category,rows in morning.groupby('category'):
            key='support_goods' if category=='配套用品' else 'sale_goods'
            self.assertLessEqual(rows.opening_stock.max(),rules[key]['daily_stock_cap'])
        support=pd.read_csv(ws.public/'products.csv').query("category=='配套用品'").sku
        sites=pd.read_csv(ws.public/'sites.csv').site
        allocation={(day,site):1 for day in range(84,98) for site in sites}
        usual,_=ws.world.generate(84,14,main_high=True)
        for sku in support:
            protocol=ws.experiment_capabilities['support_supply:'+sku]
            treated,_=ws.world.generate(84,14,assignment=allocation,support_sku=sku,main_high=True)
            a=usual[(usual.sku==sku)&(usual.hour==HOURS[0])].opening_stock.to_numpy()
            b=treated[(treated.sku==sku)&(treated.hour==HOURS[0])].opening_stock.to_numpy()
            self.assertTrue((a!=b).any(),'advertised supply operation needs an actual treatment contrast')
            self.assertTrue((b==protocol['arms']['treatment']['morning_stock:'+sku]).all())
            for variable,value in protocol['fixed_variables'].items():
                if variable.startswith('morning_stock:'):
                    product=variable.split(':',1)[1]
                    for data in (usual,treated):self.assertTrue((data[(data.sku==product)&(data.hour==HOURS[0])].opening_stock==value).all())

    def test_operational_receipt_is_paired_observed_and_reused(self):
        ws=self.ws;filename=ws.public/'baseline.py'
        with patch.object(ws.workers['evaluator'],'forecast',wraps=ws.workers['evaluator'].forecast) as forecast:
            first=evaluate(ws,filename,name='contract_test')
            again=evaluate(ws,filename,name='same_condition_different_label')
            self.assertEqual(forecast.call_count,1)
        self.assertEqual(first['evaluation_id'],again['evaluation_id']);self.assertTrue(again['reused_existing_receipt'])
        obs=pd.read_csv(first['observations'])
        self.assertFalse(obs.duplicated(['site','day']).any())
        self.assertAlmostEqual(obs.net_profit.mean(),first['mean_net_profit_per_site_day'])
        self.assertAlmostEqual(obs.fresh_waste.mean(),first['mean_fresh_waste_per_site_day'])
        self.assertEqual(obs.observed_stockout_hours.sum(),first['observed_stockout_hours'])
        self.assertFalse(any('demand' in col or 'world' in col for col in obs))
        other=evaluate(ws,filename,'replication_1',name='replication_test')
        self.assertEqual(first['history_sha256'],other['history_sha256'])
        self.assertNotEqual(first['condition'],other['condition'])
        self.assertEqual(set(map(tuple,obs[['site','day']].to_numpy())),set(map(tuple,pd.read_csv(other['observations'])[['site','day']].to_numpy())))
        with patch.object(ws.workers['evaluator'],'forecast') as forecast:
            with self.assertRaisesRegex(ValueError,'registered'):evaluate(ws,filename,'imagined_cost_ratio')
            forecast.assert_not_called()

    def test_strong_reference_uses_same_available_features_at_fit_and_predict(self):
        ws=self.ws
        score=evaluate(ws,ws.public/'strong_numeric.py',name='strong_feature_contract')
        self.assertTrue(np.isfinite(score['mean_net_profit_per_site_day']))
        text=(ws.public/'strong_numeric.py').read_text()
        self.assertNotIn('future.rename',text)
        self.assertTrue(set(pd.read_csv(ws.public/'development_features.csv',nrows=0)) >= {'planned_s11_morning_stock','planned_s12_morning_stock'})

    def test_hypothesis_verdict_keeps_the_original_prediction_subject(self):
        ws=self.ws
        old_flow=dict(ws.state['workflow'])
        try:
            ws.state['workflow'].update(phase='needs_hypotheses',hypothesis_ids=[])
            h=ws.tool('mechanist','save_hypothesis',{'explanation':'Generic measurement hypothesis fixture','scope':'registered observations',
                'alternatives':['alternative explanation'],'prediction':'The originally registered measurable prediction.',
                'falsification':'A contrary measurement','evidence_files':[str(ws.public/'history.csv')],'change_reason':'interface fixture','parent_id':None})
            ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=[h['id']])
            verdict=ws.tool('verifier','record_verdict',{'hypothesis_id':h['id'],'status':'unresolved',
                'rationale':'An unverified language explanation cannot replace the saved subject.','evidence_files':[str(ws.public/'history.csv')]})
            self.assertEqual(verdict['subject']['prediction'],h['prediction'])
            self.assertEqual(verdict['subject']['scope'],h['scope'])
            self.assertEqual(verdict['subject']['type'],'hypothesis_prediction')
            self.assertTrue(verdict['subject']['definition_sha256'])
        finally:ws.state['workflow']=old_flow

    def test_persisted_development_receipts_restore_without_repeating_evaluation(self):
        ws=self.ws
        receipt=evaluate(ws,ws.public/'baseline.py',name='before_reopen')
        ws.persist()
        restored=ScientificWorkspace(ws.root,OfficeWorld('relationship',8917,VERSION),reopen=True)
        with patch.object(restored.workers['evaluator'],'forecast') as forecast:
            same=evaluate(restored,restored.public/'baseline.py',name='after_reopen')
            forecast.assert_not_called()
        self.assertEqual(receipt['evaluation_id'],same['evaluation_id'])
        self.assertFalse(restored.requires_independent_review(same['observations']))

    def test_evaluation_review_binds_claim_without_relabelling_hypothesis(self):
        ws=self.ws
        args={'role':'verifier','stage':'evaluation_review','program_ids':['baseline','strong_numeric'],
              'hypothesis_ids':[],'evaluation_claim':'Compare these exact programs in registered development conditions.'}
        resolved=resolve_task(ws,args,ws.workflow())
        task={'id':'typed_review_fixture',**args,**resolved,'workflow':{**ws.state['workflow'],'evaluation_subject':resolved['evaluation_subject']}}
        binding=ws.task_binding(task);snapshot=ws.capture_task('verifier',task,binding)
        token=role_task_context.set(snapshot)
        old_hypotheses=json.dumps(ws.state['hypotheses'],sort_keys=True)
        try:
            self.assertFalse(ws.tool_allowed_now('record_verdict'))
            self.assertTrue(ws.tool_allowed_now('evaluate_program'))
            with self.assertRaisesRegex(ValueError,'unavailable'):ws.tool('verifier','record_verdict',{})
            review=ws.tool('verifier','record_evaluation_review',{'status':'unresolved','rationale':'Interface fixture, no scientific certification','evidence_files':[str(ws.public/'baseline.py')]},operation_id='typed_review_commit')
            again=ws.tool('verifier','record_evaluation_review',{'status':'unresolved','rationale':'Interface fixture, no scientific certification','evidence_files':[str(ws.public/'baseline.py')]},operation_id='typed_review_commit')
            self.assertEqual(review['id'],again['id'])
            self.assertEqual(review['subject'],resolved['evaluation_subject'])
            self.assertEqual(old_hypotheses,json.dumps(ws.state['hypotheses'],sort_keys=True))
            ws.tool('verifier','finish_evaluation_review',{'review_id':review['id'],'summary':'scripted typed subject delivery'})
            original=(ws.public/'baseline.py').read_bytes()
            try:
                (ws.public/'baseline.py').write_bytes(original+b'\n# changed input\n')
                with self.assertRaises(TaskInputChangedError):ws.validate_task_inputs()
            finally:(ws.public/'baseline.py').write_bytes(original)
        finally:role_task_context.reset(token)
        with self.assertRaisesRegex(ValueError,'hypothesis IDs'):resolve_task(ws,{**args,'hypothesis_ids':['H999']},ws.workflow())
        with self.assertRaisesRegex(ValueError,'program IDs'):resolve_task(ws,{**args,'program_ids':['unknown']},ws.workflow())

    def test_all_controls_are_selectable_and_final_evaluation_stays_outside_actor_receipts(self):
        ws=self.ws
        catalogue=describe(ws)
        self.assertTrue(all(p['selectable'] for p in catalogue['programs']))
        for item in catalogue['programs']:self.assertEqual(sha(program(ws,item['program_id'])),item['code_sha256'])
        before=json.dumps(ws.state['development_evaluations'],sort_keys=True)
        score=ws.evaluate_code(ws.public/'baseline.py',first_day=140,days=1,name='final_fixture')
        self.assertNotIn('observations',score)
        self.assertEqual(before,json.dumps(ws.state['development_evaluations'],sort_keys=True))


if __name__=='__main__':unittest.main()
