"""Behavior attribution regressions, independent of sandbox or model calls."""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from behavior_comparison import compare
from workspace import sha


class BehaviorComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def receipt(self,name,prediction=2.,order=50,profit=10.,day=1):
        frames={'forecast_rows':(pd.DataFrame([dict(site='x',day=day,sku='generic',hour=9,predicted_demand_mean=prediction)]),['site','day','sku','hour']),
                'order_decisions':(pd.DataFrame([dict(site='x',day=day,sku='generic',order_quantity=order)]),['site','day','sku']),
                'site_days':(pd.DataFrame([dict(site='x',day=day,net_profit=profit)]),['site','day'])}
        files={}
        for table,(frame,key) in frames.items():
            path=self.root/(name+'_'+table+'.csv');frame.to_csv(path,index=False)
            files[table]={'path':str(path),'sha256':sha(path),'key':key}
        return {'evaluation_id':name,'code_sha256':name,'history_sha256':'fixed','condition_id':'fixed','observation_files':files}
    def test_different_code_hash_does_not_mean_different_behavior(self):
        result=compare(self.receipt('different_code_1'),self.receipt('different_code_2'))
        self.assertTrue(all(x['changed_rows']==0 for x in result['comparisons'].values()))
    def test_prediction_change_can_stop_at_order_rule(self):
        result=compare(self.receipt('left',prediction=3),self.receipt('right',prediction=2))['comparisons']
        self.assertEqual(result['forecast_rows']['changed_rows'],1)
        self.assertEqual(result['order_decisions']['changed_rows'],0)
        self.assertEqual(result['site_days']['changed_rows'],0)
    def test_order_and_profit_changes_are_separate_measures(self):
        result=compare(self.receipt('left',order=40,profit=8),self.receipt('right'))['comparisons']
        self.assertEqual(result['forecast_rows']['changed_rows'],0)
        self.assertEqual(result['order_decisions']['signed_delta_sum'],-10)
        self.assertEqual(result['site_days']['signed_delta_sum'],-2)
    def test_mismatched_population_condition_and_tampering_refused(self):
        left=self.receipt('left');right=self.receipt('right',day=2)
        with self.assertRaisesRegex(ValueError,'populations differ'):compare(left,right)
        right=self.receipt('right');right['condition_id']='other'
        with self.assertRaisesRegex(ValueError,'matched inputs'):compare(left,right)
        right['condition_id']='fixed'
        Path(right['observation_files']['forecast_rows']['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'bytes changed'):compare(left,right)


if __name__=='__main__':unittest.main()
