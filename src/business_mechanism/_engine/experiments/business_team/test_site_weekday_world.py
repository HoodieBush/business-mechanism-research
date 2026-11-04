"""Private scene validity and observable contracts, never discovery grading."""
import json
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from world import OfficeWorld, START, site_frame, operating_orders
from scenario_contract import VERSION, EXTENDED_VERSION, SUPPORT_STOCK_CAP
from workspace import write_json
from langgraph_migration.mechanism_research import MechanismWorkspace
from langgraph_migration.runtime import FrameworkRoles
from development_evaluation import evaluate


class PrivateStructureTests(unittest.TestCase):
    def test_new_structure_cannot_be_silently_used_in_old_versions(self):
        for version in ('office-business-v0.2', VERSION):
            with self.assertRaises(ValueError): OfficeWorld('site_weekday', 9137, version)
        with self.assertRaises(ValueError): OfficeWorld('site_weekday', 9137, 'unregistered')
        self.assertTrue(OfficeWorld('site_weekday', 9137, EXTENDED_VERSION).revised)

    def test_interaction_changes_only_declared_site_days_and_not_supply(self):
        for seed in (9137, 2026102002, 87031):
            candidate = OfficeWorld('site_weekday', seed, EXTENDED_VERSION)
            control = OfficeWorld('record_fault', seed, VERSION)
            for day in range(35):
                for site in site_frame().site:
                    original, stock = control.day_context(day, site)
                    actual, new_stock = candidate.day_context(day, site)
                    friday = (START+pd.Timedelta(days=day)).weekday() == 4
                    multiplier = {'C01':.55, 'C05':1.45}.get(site, 1.) if friday else 1.
                    self.assertAlmostEqual(actual/original, multiplier)
                    self.assertEqual(new_stock, stock)
                    self.assertEqual(candidate.support_plan(day, site), control.support_plan(day, site))

    def test_existing_worlds_keep_identical_observations_in_new_schema_version(self):
        for kind in ('relationship','confounding','record_fault'):
            with self.subTest(kind=kind):
                old = OfficeWorld(kind, 9137, VERSION)
                new = OfficeWorld(kind, 9137, EXTENDED_VERSION)
                for a,b in zip(old.generate(0,7), new.generate(0,7)):
                    pd.testing.assert_frame_equal(a,b)
                pd.testing.assert_frame_equal(old.features(0,7), new.features(0,7))

    def test_realised_records_preserve_negative_controls_and_stock_accounting(self):
        new = OfficeWorld('site_weekday', 9137, EXTENDED_VERSION)
        # Corrected record_fault has the same neutral demand/supply streams;
        # it supplies a control without either measurement loss or utensil effect.
        neutral = OfficeWorld('record_fault', 9137, VERSION)
        observed,_ = new.generate(0,7)
        control,_ = neutral.generate(0,7,corrected=True)
        affected = observed.weekday.eq(4) & observed.site.isin(['C01','C05'])
        pd.testing.assert_frame_equal(observed[~affected], control[~affected])
        self.assertTrue((observed.loc[affected,'sales'] != control.loc[affected,'sales']).any())
        self.assertTrue((observed.opening_stock+observed.restock-observed.sales == observed.closing_stock).all())
        self.assertNotIn('s11_hour_start_stock', observed)
        self.assertFalse(any('traffic' in c or 'demand' in c for c in observed))


class SceneWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get('PROCESS_ACCEPTANCE_OUTPUT')
        cls.temp = None if configured else tempfile.TemporaryDirectory(prefix='scene_contract_')
        cls.root = Path(configured or cls.temp.name).resolve()/'M001'
        cls.root.mkdir(parents=True, exist_ok=False)
        cls.ws = MechanismWorkspace(cls.root/'workspace', OfficeWorld('site_weekday',9137,EXTENDED_VERSION))
        FrameworkRoles(cls.ws,None,lambda role:None)

    @classmethod
    def tearDownClass(cls):
        if cls.temp: cls.temp.cleanup()

    def test_public_contract_and_private_code_boundary(self):
        ws=self.ws
        self.assertEqual(json.loads((ws.public/'operating_rules.json').read_text())['scenario_version'],EXTENDED_VERSION)
        self.assertEqual(json.loads((ws.public/'evaluation_contract.json').read_text())['scenario_version'],EXTENDED_VERSION)
        context=json.dumps(ws.initial_context(),ensure_ascii=False)
        self.assertNotIn('site_weekday',context)
        for name in ('business_brief.md','research_objective.md','data_dictionary.json','operating_rules.json'):
            self.assertNotIn('site_weekday',(ws.public/name).read_text())
        private=[str(Path(__file__).with_name('world.py')),str(ws.root/'mechanism_identity.json')]
        result=ws.workers['verifier'].run('import json\na=[]\nfor p in '+repr(private)+':\n try:\n  open(p).read();a.append("LEAK")\n except PermissionError:a.append("blocked")\nprint(json.dumps(a))')
        self.assertTrue(result['ok'],result)
        self.assertEqual(json.loads(result['stdout']),['blocked','blocked'])
        write_json(self.root/'privacy.json',result)

    def test_registered_supply_trial_preserves_its_actual_intervention(self):
        ws=self.ws;ws.state['workflow']['phase']='needs_hypotheses'
        h=ws.tool('mechanist','save_hypothesis',{'explanation':'Engineering fixture checking actual intervention, not a discovery.',
            'scope':'registered operation','alternatives':['operation mismatch'],'prediction':'Declared support supply changes while fresh opening is fixed.',
            'falsification':'Actual manipulated or fixed settings differ.','evidence_files':[str(ws.public/'history.csv')],'change_reason':'environment acceptance'})
        ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=[h['id']])
        protocol=next(p for p in ws.experiment_capabilities.values() if p['kind']=='supply_trial')
        products=[k.split(':',1)[1] for k in protocol['fixed_variables'] if k.startswith('morning_stock:')]
        plan=ws.tool('verifier','prepare_experiment',{'hypothesis_id':h['id'],'protocol_id':protocol['id'],
            'outcome_product_ids':products,'expected_changed_variables':protocol['changed_variables'],
            'prediction':'Operation fixture only.','analysis_plan':'Verify actual intervention; do not infer customer cause.'})
        receipt=ws.tool('verifier','run_experiment',{'plan_id':plan['id']})
        rows=pd.read_csv(receipt['observations']);morning=rows[rows.hour.eq(9)]
        treated=morning[morning.sku.eq(protocol['support_sku']) & morning.treatment.eq(1)]
        self.assertEqual(set(treated.opening_stock),{SUPPORT_STOCK_CAP})
        for field,value in protocol['fixed_variables'].items():
            if field.startswith('morning_stock:'):
                self.assertEqual(set(morning[morning.sku.eq(field.split(':',1)[1])].opening_stock),{value})
        self.assertEqual(receipt['actual_protocol'],plan['protocol'])

    def test_development_evaluation_reconstructs_same_extended_world(self):
        ws=self.ws
        receipt=evaluate(ws,ws.public/'baseline.py',name='extended_scene_acceptance')
        files=receipt['observation_files']
        forecasts=pd.read_csv(files['forecast_rows']['path'])
        condition=receipt['condition']
        world=OfficeWorld('site_weekday',condition['simulation_seed'],EXTENDED_VERSION)
        features=world.features(condition['first_day'],condition['calendar_days'])
        orders=operating_orders(features,forecasts.predicted_demand_mean.to_numpy())
        _,expected=world.generate(condition['first_day'],condition['calendar_days'],orders=orders)
        actual=pd.read_csv(files['daily_finance']['path'])
        self.assertEqual(actual[['site','day']].to_dict('records'),expected[['site','day']].to_dict('records'))
        np.testing.assert_allclose(actual.net_profit,expected.net_profit,rtol=1e-12)
        write_json(self.root/'evaluation_scope.json',{'actual_sandbox_forecast':True,'same_world_reconstruction':True,
            'scientific_discovery_certified':False,'receipt':receipt['evaluation_id']})


if __name__ == '__main__': unittest.main()
