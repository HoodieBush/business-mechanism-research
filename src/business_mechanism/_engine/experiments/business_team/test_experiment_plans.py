"""Operation contract/recovery checks, not LLM scientific ability evidence."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from langgraph.checkpoint.sqlite import SqliteSaver
from experiment_plans import match_changed_variables
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles
from world import OfficeWorld


class GenericDesignTests(unittest.TestCase):
    def test_requested_manipulation_is_bound_across_domains(self):
        for actual,other in [('support_supply','main_inventory'),('thermostat_setpoint','sensor_units')]:
            protocol={'changed_variables':[actual],'fixed_variables':{other:'unchanged'}}
            match_changed_variables([actual],protocol)
            with self.assertRaisesRegex(ValueError,'does not match'):match_changed_variables([other],protocol)
            with self.assertRaises(ValueError):match_changed_variables([actual,actual],protocol)


class PreparedStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_study_')
        self.root=Path(self.temp.name);self.ws=ScientificWorkspace(self.root/'P001',OfficeWorld('relationship',7400))
        self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
        FrameworkRoles(self.ws,self.saver,lambda role:None)
        self.ws.state['workflow']['phase']='needs_hypotheses'
        h=self.ws.tool('mechanist','save_hypothesis',{'explanation':'engineering operation fixture, no scientific claim','scope':'received sources','alternatives':['fixture alternatives'],
            'prediction':'operation metadata and sampling are consistent','falsification':'metadata and physical settings differ','evidence_files':[str(self.ws.public/'history.csv')],'change_reason':'fixture','parent_id':None})
        self.ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=[h['id']]);self.ws.persist();self.hid=h['id']
        self.protocol=next(p for p in self.ws.experiment_capabilities.values() if p['kind']=='supply_trial')
        self.outcomes=[k.split(':',1)[1] for k in self.protocol['fixed_variables'] if k.startswith('morning_stock:')]
    def tearDown(self):self.conn.close();self.temp.cleanup()
    def prepare(self,expected=None):
        return self.ws.tool('verifier','prepare_experiment',{'hypothesis_id':self.hid,'protocol_id':self.protocol['id'],
            'outcome_product_ids':self.outcomes,'expected_changed_variables':self.protocol['changed_variables'] if expected is None else expected,
            'prediction':'engineering fixture','analysis_plan':'check physical operation metadata, no science verdict'},operation_id='prepare_fixture')
    def test_prepare_rejects_different_intervention_without_sampling(self):
        with patch.object(self.ws.world,'generate') as sample:
            with self.assertRaisesRegex(ValueError,'does not match'):self.prepare(['morning_stock:'+self.outcomes[0]])
            sample.assert_not_called()
        self.assertEqual(self.ws.state['experiments'],[]);self.assertEqual(self.ws.state.get('study_plans',[]),[])
    def test_actual_arms_match_plan_and_same_plan_never_resamples(self):
        plan=self.prepare();self.assertEqual(self.ws.state['experiments'],[])
        with patch.object(self.ws.world,'generate',wraps=self.ws.world.generate) as sample:
            first=self.ws.tool('verifier','run_experiment',{'plan_id':plan['id']},operation_id='execute_fixture')
            second=self.ws.tool('verifier','run_experiment',{'plan_id':plan['id']},operation_id='different_call_same_plan')
            self.assertEqual(sample.call_count,1)
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.ws.state['experiments']),1)
        import pandas as pd
        data=pd.read_csv(first['observations']);morning=data[data.hour==9]
        for variable,value in plan['protocol']['fixed_variables'].items():
            if variable.startswith('morning_stock:'):
                sku=variable.split(':',1)[1];self.assertEqual(set(morning[morning.sku==sku].opening_stock),{value})
        support=plan['protocol']['support_sku'];treated=morning[(morning.sku==support)&(morning.treatment==1)]
        self.assertEqual(set(treated.opening_stock),{plan['protocol']['arms']['treatment']['morning_stock:'+support]})
        self.assertEqual(first['actual_protocol'],plan['protocol'])
    def test_modified_plan_is_rejected_before_sampling(self):
        plan=self.prepare();p=self.ws.shared/'study_plans'/(plan['id']+'.json')
        changed=json.loads(p.read_text());changed['outcome_product_ids']=[];p.write_text(json.dumps(changed))
        with patch.object(self.ws.world,'generate') as sample:
            with self.assertRaisesRegex(ValueError,'version changed'):self.ws.tool('verifier','run_experiment',{'plan_id':plan['id']},operation_id='tampered_execute')
            sample.assert_not_called()
    def test_committed_experiment_recovers_binding_without_resampling(self):
        plan=self.prepare()
        with patch.object(self.ws,'bind_study_result',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.ws.tool('verifier','run_experiment',{'plan_id':plan['id']},operation_id='interrupted_execute')
        self.assertEqual(len(self.ws.state['experiments']),1)
        self.ws=ScientificWorkspace(self.ws.root,OfficeWorld('relationship',7400),reopen=True)
        FrameworkRoles(self.ws,self.saver,lambda role:None)
        with patch.object(self.ws.world,'generate') as sample:
            result=self.ws.tool('verifier','run_experiment',{'plan_id':plan['id']},operation_id='interrupted_execute')
            sample.assert_not_called()
        self.assertEqual(result['plan_id'],plan['id']);self.assertEqual(self.ws.state['study_runs'][plan['id']]['status'],'completed')
        self.assertEqual(len(self.ws.state['experiments']),1)
    def test_ambiguous_uncommitted_execution_does_not_resample(self):
        plan=self.prepare();self.ws.state['study_runs']={plan['id']:{'operation_id':'missing_operation','status':'executing'}}
        with patch.object(self.ws.world,'generate') as sample:
            with self.assertRaisesRegex(ValueError,'ambiguous'):self.ws.tool('verifier','run_experiment',{'plan_id':plan['id']},operation_id='fresh_operation')
            sample.assert_not_called()
        another=self.ws.tool('verifier','prepare_experiment',{'hypothesis_id':self.hid,'protocol_id':self.protocol['id'],
            'outcome_product_ids':self.outcomes,'expected_changed_variables':self.protocol['changed_variables'],'prediction':'fixture','analysis_plan':'fixture'},operation_id='another_plan')
        with patch.object(self.ws.world,'generate') as sample:
            with self.assertRaisesRegex(ValueError,'prior physical'):self.ws.tool('verifier','run_experiment',{'plan_id':another['id']},operation_id='new_plan_cannot_bypass_ambiguity')
            sample.assert_not_called()


if __name__=='__main__':unittest.main()
