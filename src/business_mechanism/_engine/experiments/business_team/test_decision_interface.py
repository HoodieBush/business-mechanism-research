"""Generic source/decision/execution contracts; no scientific answer gates."""
import ast
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import ordering_policy
from contracts import HOURS
from decision_interface import load
from development_evaluation import evaluate
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.science import ScientificWorkspace
from scenario_contract import VERSION, SALE_STOCK_CAP
from world import OfficeWorld
from workspace import sha


class DecisionInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_decision_interface_')
        cls.ws = ScientificWorkspace(Path(cls.temp.name)/'business', OfficeWorld('relationship', 9331, VERSION))
        FrameworkRoles(cls.ws, None, None)
        cls.receipt = evaluate(cls.ws, cls.ws.public/'baseline.py', name='decision_contract')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_public_implementation_and_parameters_identify_actual_shared_policy(self):
        ws = self.ws
        interface = load(ws)
        self.assertEqual(sha(ws.public/'ordering_policy.py'), sha(ordering_policy.__file__))
        self.assertEqual(interface['implementation']['sha256'], self.receipt['decision_policy_sha256'])
        self.assertEqual(sha(ws.public/'decision_interface.json'), self.receipt['decision_interface_sha256'])
        self.assertEqual(interface['parameters'], ordering_policy.specification(SALE_STOCK_CAP))
        for name, digest in interface['source_files'].items():
            self.assertEqual(sha(ws.public/name), digest)
        module = ast.parse((ws.public/'ordering_policy.py').read_text())
        imports = [n.module for n in ast.walk(module) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(module) if isinstance(n, ast.Import) for a in n.names]
        self.assertEqual(set(imports), {'numpy','pandas','scipy.stats'})
        self.assertFalse((ws.public/'world.py').exists())

    def test_historical_opening_is_observed_state_from_prior_supply_policy(self):
        ws = self.ws
        historical = pd.read_csv(ws.public/'historical_opening.csv')
        expected = ws.history.loc[ws.history.hour==HOURS[0],historical.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(historical, expected, check_dtype=False)
        self.assertFalse(historical.duplicated(ordering_policy.KEY).any())
        goods = historical.merge(pd.read_csv(ws.public/'products.csv')[['sku','category']],on='sku',validate='many_to_one')
        sale = goods[goods.category!='配套用品']
        self.assertTrue((sale.opening_stock==sale.category.map(ordering_policy.historical_sale_stock)).all())
        self.assertIn('not outputs of the supplied predict programs',load(ws)['parameters']['history_sale_supply']['scope'])

    def test_decision_trace_is_keyed_prediction_to_actual_state_with_separate_schema(self):
        ws = self.ws; receipt = self.receipt
        files = receipt['observation_files']
        decisions = pd.read_csv(files['order_decisions']['path'])
        forecasts = pd.read_csv(files['forecast_rows']['path'])
        hourly = pd.read_csv(files['observed_hourly']['path'])
        expected = forecasts.groupby(ordering_policy.KEY).predicted_demand_mean.sum().rename('expected')
        joined = decisions.set_index(ordering_policy.KEY).join(expected,validate='one_to_one')
        np.testing.assert_allclose(joined.daily_forecast_mean,joined.expected,atol=1e-12,rtol=1e-12)
        observed = hourly[hourly.hour==HOURS[0]][ordering_policy.KEY+['opening_stock']]
        joined = decisions.merge(observed,on=ordering_policy.KEY,validate='one_to_one')
        np.testing.assert_array_equal(joined.executed_opening_stock,joined.opening_stock)
        np.testing.assert_array_equal(joined.order_quantity,joined.executed_opening_stock)
        self.assertTrue((decisions.execution_difference==0).all())
        self.assertTrue(decisions.loc[decisions.critical_fractile>=1,'unconstrained_quantity'].isna().all())
        metadata = json.loads(Path(files['order_decisions']['metadata_file']).read_text())
        self.assertEqual(set(metadata['column_definitions']),set(decisions))
        self.assertEqual(metadata['decision_policy_sha256'],sha(ws.public/'ordering_policy.py'))
        for definition in metadata['column_definitions'].values():
            self.assertTrue({'meaning','unit','aggregation','available_at'}<=set(definition))
        for name in ('order_quantity','executed_opening_stock','execution_difference'):
            self.assertNotIn(name,forecasts)
        with self.assertRaisesRegex(sqlite3.OperationalError,'no such table'):
            ws.tool('analyst','query_data',{'sql':'SELECT * FROM order_decisions','output_semantics':'CSV is not a SQLite table'})

    def test_execution_differences_are_logged_without_answer_based_rejection(self):
        features = pd.DataFrame([{'day':1,'site':'opaque','sku':'generic'}])
        products = pd.DataFrame([{'sku':'generic','price':10.,'unit_cost':5.,'salvage':0.}])
        orders,trace = ordering_policy.operating_orders(features,[10.],products,50,with_trace=True)
        expected = next(iter(orders.values()))
        observed = pd.DataFrame([{'day':1,'site':'opaque','sku':'generic','hour':9,'opening_stock':expected-3}])
        result = ordering_policy.attach_execution(trace,observed)
        self.assertEqual(result.execution_difference.iloc[0],-3)
        self.assertEqual(result.executed_opening_stock.iloc[0],expected-3)
        with self.assertRaisesRegex(ValueError,'missing actually observed'):
            ordering_policy.attach_execution(trace,observed.assign(hour=10))
        with self.assertRaises(pd.errors.MergeError):
            ordering_policy.attach_execution(trace,pd.concat([observed,observed]))

    def test_five_roles_can_read_source_and_export_definitions_and_python_can_import_it(self):
        ws = self.ws
        for role in ('manager','analyst','mechanist','verifier','engineer'):
            with self.subTest(role=role):
                context=ws.tool(role,'read_context',{})
                self.assertEqual(context['decision_interface']['shared_policy_source'],str(ws.public/'ordering_policy.py'))
                view=ws.tool(role,'read_artifact',{'path':context['decision_interface']['shared_policy_source']})
                self.assertIn('def operating_orders',view['text'])
                definition=ws.tool(role,'read_field_definitions',{'table':'order_decisions','columns':['order_quantity','executed_opening_stock']})
                self.assertIn('CSV',definition['storage'])
                self.assertEqual(definition['definition_source']['sha256'],sha(ws.public/'decision_interface.json'))
                self.assertIn('after actual order execution',definition['columns']['executed_opening_stock']['available_at'])
        code=('import os,json,pandas as pd,numpy as np\nfrom pathlib import Path\n'
              'from ordering_policy import operating_orders\n'
              'p=Path(os.environ["PUBLIC_DIR"])\n'
              'f=pd.read_csv(p/"development_features.csv")\n'
              'products=pd.read_csv(p/"products.csv")\n'
              'orders,trace=operating_orders(f,np.zeros(len(f)),products,50,with_trace=True)\n'
              'assert len(orders)==len(trace) and not trace.empty\n'
              'print("public shared rule imported and calculated")\n')
        result=ws.tool('verifier','run_python',{'code':code,'purpose':'Public interface access contract','output_semantics':'Source access and calculation only, not a scientific result'})
        self.assertTrue(result['ok'],result.get('stderr'))
        self.assertIn('public shared rule imported',result['stdout'])

    def test_source_and_receipt_version_conflicts_fail_without_reforecast(self):
        ws=self.ws
        for path in (ws.public/'ordering_policy.py',ws.public/'decision_interface.json',ws.public/'products.csv',
                     Path(self.receipt['observation_files']['order_decisions']['path']),
                     Path(self.receipt['observation_files']['order_decisions']['metadata_file'])):
            original=path.read_bytes()
            try:
                path.write_bytes(original+b'\nchanged')
                with patch.object(ws.workers['evaluator'],'forecast') as forecast:
                    with self.assertRaises(ValueError):evaluate(ws,ws.public/'baseline.py')
                    forecast.assert_not_called()
            finally:
                path.write_bytes(original)
        before={str(p):sha(p) for p in ws.public.iterdir() if p.is_file()}
        restored=ScientificWorkspace(ws.root,OfficeWorld('relationship',9331,VERSION),reopen=True)
        FrameworkRoles(restored,None,None)  # Same manual materialisation as the actual runner.
        self.assertEqual(before,{str(p):sha(p) for p in restored.public.iterdir() if p.is_file()})
        with patch.object(restored.workers['evaluator'],'forecast') as forecast:
            same=evaluate(restored,restored.public/'baseline.py')
            forecast.assert_not_called()
        self.assertTrue(same['reused_existing_receipt'])


if __name__=='__main__':
    unittest.main(verbosity=2)
