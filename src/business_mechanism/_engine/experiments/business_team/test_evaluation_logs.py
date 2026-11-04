"""Observable logging preserves policy outcomes and excludes private simulator fields."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from development_evaluation import evaluate,observation_frames
from langgraph_migration.science import ScientificWorkspace
from scenario_contract import VERSION
from world import OfficeWorld
from workspace import sha
from langgraph_migration.runtime import FrameworkRoles,role_task_context


class EvaluationLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_eval_logs_')
        cls.ws=ScientificWorkspace(Path(cls.temp.name)/'business',OfficeWorld('relationship',7441,VERSION))
        cls.receipt=evaluate(cls.ws,cls.ws.public/'baseline.py',name='observable_logging')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def frames(self):return {name:pd.read_csv(item['path']) for name,item in self.receipt['observation_files'].items()}

    def test_public_logs_align_forecasts_observations_and_daily_aggregation(self):
        ws=self.ws;frames=self.frames();dictionary=json.loads((ws.public/'data_dictionary.json').read_text())
        self.assertEqual(set(frames),{'forecast_rows','observed_hourly','daily_finance','site_days','order_decisions'})
        for name,item in self.receipt['observation_files'].items():
            frame=frames[name];self.assertFalse(frame.duplicated(item['key']).any())
            self.assertEqual(sha(item['path']),item['sha256'])
            meta=json.loads(Path(item['metadata_file']).read_text())
            self.assertEqual(set(meta['column_definitions']),set(frame))
            self.assertEqual(meta['code_sha256'],self.receipt['code_sha256'])
            self.assertEqual(meta['condition'],self.receipt['condition'])
            for definition in meta['column_definitions'].values():self.assertTrue({'meaning','unit','aggregation','available_at'}<=set(definition))
            self.assertIn(item['path'],ws.registered_sources)
            self.assertTrue((frame.day>=112).all());self.assertTrue((frame.day<140).all())
        observed=frames['observed_hourly'];forecast=frames['forecast_rows'];key=['site','day','sku','hour']
        self.assertEqual(set(observed),set(dictionary['tables']['hourly']['columns']))
        self.assertEqual(set(forecast)-{'predicted_demand_mean'},set(dictionary['tables']['prediction_features']['columns']))
        self.assertEqual(set(map(tuple,forecast[key].to_numpy())),set(map(tuple,observed[observed.sku.isin(forecast.sku.unique())][key].to_numpy())))
        expected_features=ws.world.features(112,14)
        pd.testing.assert_frame_equal(forecast[list(expected_features)],expected_features,check_dtype=False)
        # The executable forecast output, not a reconstructed or invented model.
        predictions=json.loads((ws.workers['evaluator'].directory/'observable_logging_predictions.json').read_text())
        np.testing.assert_allclose(forecast.predicted_demand_mean,predictions,rtol=1e-12,atol=1e-12)
        fresh=set(pd.read_csv(ws.public/'products.csv').query("category=='鲜食'").sku)
        affected=observed[observed.sku.isin(fresh)].assign(observed_stockout_hours=lambda f:(f.available_minutes<60).astype(int)).groupby(['site','day']).observed_stockout_hours.sum()
        daily=frames['daily_finance'].merge(affected,on=['site','day'],validate='one_to_one')
        pd.testing.assert_frame_equal(daily[frames['site_days'].columns],frames['site_days'],check_dtype=False)

    def test_export_changes_no_historical_operating_values(self):
        source=Path(__file__).parent/'results/development_langgraph_science_v09_20261014/B101'
        old=json.loads((source/'artifacts/development_evaluations/D0001/receipt.json').read_text())
        self.assertEqual(sha(self.ws.public/'baseline.py'),old['code_sha256'])
        self.assertEqual(sha(self.ws.public/'history.csv'),old['history_sha256'])
        old_rows=pd.read_csv(source/'artifacts/development_evaluations/D0001/site_days.csv')
        pd.testing.assert_frame_equal(pd.read_csv(self.receipt['observations']),old_rows,check_exact=False,rtol=1e-12,atol=1e-12)

    def test_public_projection_ignores_extra_private_fields_and_rejects_future_inputs(self):
        frames=self.frames();features=frames['forecast_rows'].drop(columns='predicted_demand_mean')
        hourly=frames['observed_hourly'].assign(latent_demand=999,world_kind='private',treatment=1)
        finance=frames['daily_finance'].assign(mechanism_parameter=123,treatment=1)
        logs,_=observation_frames(self.ws,features,frames['forecast_rows'].predicted_demand_mean,hourly,finance,frames['site_days'])
        for name in ('observed_hourly','daily_finance'):
            self.assertFalse({'latent_demand','world_kind','treatment','mechanism_parameter'}&set(logs[name]))
        with self.assertRaisesRegex(ValueError,'prediction feature columns'):
            observation_frames(self.ws,features.assign(sales=999),np.zeros(len(features)),hourly,finance,frames['site_days'])

    def test_reuse_validates_all_files_and_metadata_without_regeneration(self):
        for key in ('forecast_rows','observed_hourly','daily_finance','order_decisions'):
            for field in ('path','metadata_file'):
                path=Path(self.receipt['observation_files'][key][field]);original=path.read_bytes()
                try:
                    path.write_bytes(original+b'\nchanged')
                    with patch.object(self.ws.workers['evaluator'],'forecast') as forecast:
                        with self.assertRaisesRegex(ValueError,'observations changed'):evaluate(self.ws,self.ws.public/'baseline.py')
                        forecast.assert_not_called()
                finally:path.write_bytes(original)
        with patch.object(self.ws.workers['evaluator'],'forecast') as forecast:
            receipt=evaluate(self.ws,self.ws.public/'baseline.py');forecast.assert_not_called()
        self.assertTrue(receipt['reused_existing_receipt'])

    def test_collection_permissions_preserve_original_claim_boundaries(self):
        ws=self.ws;FrameworkRoles(ws,None,None);original=dict(ws.state['workflow'])
        hypotheses=json.dumps(ws.state['hypotheses'],sort_keys=True)
        try:
            for role,phase in [('analyst','needs_analysis'),('verifier','needs_validation')]:
                ws.state['workflow']['phase']=phase
                task={'id':'log_access_'+role,'inputs':[]}
                token=role_task_context.set(ws.capture_task(role,task,ws.task_binding(task)))
                try:
                    self.assertTrue(ws.tool_allowed_now('evaluate_program'))
                    self.assertFalse(ws.tool_allowed_now('record_evaluation_review'))
                    result=ws.tool(role,'evaluate_program',{'program_id':'baseline','condition_id':'standard'})
                    self.assertEqual(set(result['observation_files']),set(self.receipt['observation_files']))
                    visible=ws.tool_response_view(role,'evaluate_program',result)
                    self.assertNotIn('execution_receipt',visible)
                    self.assertEqual(visible['full_evaluation_receipt'],result['receipt_file'])
                finally:role_task_context.reset(token)
            self.assertEqual(json.dumps(ws.state['hypotheses'],sort_keys=True),hypotheses)
        finally:ws.state['workflow']=original


if __name__=='__main__':unittest.main()
