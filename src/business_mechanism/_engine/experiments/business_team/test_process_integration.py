"""Real sandbox process coverage with scripted decisions and persistent evidence.

No model science claim: policies deliberately choose the statements and verdicts.
All data access, review bindings, experiments, candidates and evaluations are real.
No skip or unsandboxed fallback is permitted in this suite.
"""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.provider import append_json,gateway_messages
from langgraph_migration.science import ScientificWorkspace,scientific_flow
from langgraph_migration.explicit_runtime import ExplicitRoles
from run_langgraph_science import freeze_decision,evaluate_closed_case
from test_minimal_research import ExplicitPolicy
from test_langgraph_migration import ScriptedModel
from workspace import sha,write_json
from world import OfficeWorld


class ProcessPolicy(ExplicitPolicy):
    def _generate(self,messages,**kwargs):
        ws=self.ws
        append_json(ws.root/'scripted_requests.jsonl',{'role':self.role,'messages':gateway_messages(messages),
                    'authority':'scripted engineering policy inputs; zero model API calls'})
        output=super()._generate(messages,**kwargs)
        fresh=pd.read_csv(ws.public/'products.csv').query("category == '鲜食'").sku.tolist()
        for call in output.generations[0].message.tool_calls:
            args=call['args'];name=call['name']
            if name=='save_hypothesis':
                prediction={'supported_in_scope':'提供历史中所选鲜食每行的记录销量与开库存+补入-关库存相等。',
                            'refuted':'提供历史中所选鲜食至少一行记录销量与开库存+补入-关库存不相等。',
                            'unresolved':'注册配套晨间供给干预会改变所选鲜食记录销量，观测仅适用于实际试验条件。'}[self.verdict_status]
                args.update(explanation='Scripted statement for process coverage; not autonomous discovery',
                    scope='received fresh SKUs '+str(fresh)+'; received history for record checks or registered site-day trial',
                    prediction=prediction,falsification='核对原预测、实际测量对象和不确定性；记录一致性不认证需求因果关系。')
            elif name=='prepare_experiment':
                protocol=(next(p for p in ws.experiment_capabilities.values() if p['is_new_sample'])
                          if self.verdict_status=='unresolved' else ws.experiment_capabilities['inventory_records'])
                args.update(protocol_id=protocol['id'],expected_changed_variables=protocol['changed_variables'],
                            outcome_product_ids=fresh,prediction=ws.state['hypotheses'][-1]['prediction'])
            elif name=='record_verdict':
                args['rationale']='Scripted scoped verdict; audit actual rows/registered trial and retain uncertainty. No mechanism certification.'
            elif name=='evaluate_algorithm':
                args['hypothesis_ids']=list(ws.state['workflow']['hypothesis_ids'])
                args['rationale']='Test whether this fixed candidate changes observed predictions/orders; no claimed superiority or mechanism discovery.'
            elif name=='finish_algorithm':args['limitations']=['Actual sandbox/evaluation executed; scripted choices do not establish autonomous science.']
        return output


class ProcessIntegrationTests(unittest.TestCase):
    def setUp(self):
        configured=os.environ.get('PROCESS_ACCEPTANCE_OUTPUT')
        self.temp=None if configured else tempfile.TemporaryDirectory(prefix='real_process_acceptance_')
        base=Path(configured or self.temp.name).resolve()
        self.root=base/self._testMethodName;self.root.mkdir(parents=True,exist_ok=False)
    def tearDown(self):
        if self.temp:self.temp.cleanup()

    def test_continuation_parent_business_inputs_readonly_runtime_denied(self):
        from types import SimpleNamespace
        from execution import PythonWorkspace
        from explicit_continuation import configure_readonly_parent
        grandparent=self.root/'grandparent';parent=self.root/'parent';child=self.root/'child'
        for root in (grandparent,parent,child):
            for name in ('public','artifacts','explicit_runtime_state'):(root/name).mkdir(parents=True)
            (root/'public/received.txt').write_text('received input')
            (root/'public/history.csv').write_text('same received history')
            (root/'explicit_runtime_state/private.txt').write_text('private conversation')
        worker=PythonWorkspace(child/'artifacts/verifier',child/'public',child/'artifacts',per_execution=True)
        ws=SimpleNamespace(root=child,public=child/'public',path_aliases={str(parent):str(child),str(grandparent):str(child)},workers={'verifier':worker})
        configure_readonly_parent(ws,parent)
        code='import json\nresults=[]\nfor path,mode in '+repr([(str(parent/'public/received.txt'),'r'),(str(parent/'public/received.txt'),'w'),(str(parent/'explicit_runtime_state/private.txt'),'r'),(str(child/'explicit_runtime_state/private.txt'),'r'),(str(grandparent/'public/received.txt'),'r'),(str(grandparent/'explicit_runtime_state/private.txt'),'r')])+':\n try:\n  with open(path,mode) as f: results.append("allowed")\n except PermissionError:results.append("blocked")\nprint(json.dumps(results))'
        result=worker.run(code)
        self.assertTrue(result['ok'],result);self.assertEqual(json.loads(result['stdout']),['allowed','blocked','blocked','blocked','allowed','blocked'])
        self.assertEqual((parent/'public/received.txt').read_text(),'received input')
        write_json(parent/'decision_freeze.json',{'actor_closed':True})
        with self.assertRaisesRegex(ValueError,'final evaluation'):configure_readonly_parent(ws,parent)

    def close_and_evaluate(self,ws,output,inject_failure=False):
        checkpoints=sorted((ws.root/'explicit_runtime_state').rglob('*.json'))
        self.assertTrue(checkpoints)
        checkpoint=checkpoints[0];response=checkpoint.with_suffix('.responses.jsonl')
        self.assertTrue(response.is_file())
        code='import json\nout=[]\nfor path in '+repr([str(checkpoint),str(response)])+':\n try:\n  open(path).read();out.append("LEAK")\n except PermissionError:out.append("blocked")\nprint(json.dumps(out))'
        privacy=ws.workers['verifier'].run(code)
        self.assertTrue(privacy['ok'],privacy)
        self.assertEqual(json.loads(privacy['stdout']),['blocked','blocked'])
        write_json(ws.root/'private_context_isolation.json',{'checkpoint':str(checkpoint),'response':str(response),
                    'actual_sandbox_receipt':privacy,'scope':'Actual file denial; not independent scientific judgment'})
        public_before={str(p.relative_to(ws.public)):sha(p) for p in ws.public.rglob('*') if p.is_file()}
        frozen=freeze_decision(ws,ws.root,output['step'],{})
        with self.assertRaisesRegex(ValueError,'Actor closed'):ws.tool('manager','read_history',{})
        record={};real=ws.evaluate_code;calls=[]
        def evaluate(filename,**kwargs):
            self.assertTrue(json.loads((ws.root/'decision_freeze.json').read_text())['actor_closed'])
            calls.append(kwargs['name'])
            if inject_failure and len(calls)==2:raise RuntimeError('controlled evaluator interruption after first persisted label')
            return real(filename,**kwargs)
        with patch.object(ws,'evaluate_code',side_effect=evaluate):
            if inject_failure:
                with self.assertRaisesRegex(RuntimeError,'controlled evaluator interruption'):
                    evaluate_closed_case(ws,ws.root,{},record)
            evaluate_closed_case(ws,ws.root,{},record)
        self.assertEqual(record['status'],'completed');self.assertEqual(len(record['final_evaluation']),4)
        self.assertEqual(calls.count('final_selected'),1)
        self.assertEqual(public_before,{str(p.relative_to(ws.public)):sha(p) for p in ws.public.rglob('*') if p.is_file()})
        write_json(ws.root/'acceptance_evidence.json',{'frozen':frozen,'final':record,'evaluator_calls':calls,
                    'public_input_sha256':public_before,'model_calls':0,'scripted_decisions':True})
        return record

    def full_path(self,status):
        # Fixed developer fixture. Kind/seed are not delivered to an autonomous Actor.
        ws=ScientificWorkspace(self.root/'workspace',OfficeWorld('confounding',9137,'office-business-v0.3'))
        roles_by_name={role:ProcessPolicy(ws=ws,role=role,verdict_status=status) for role in ('manager','analyst','mechanist','verifier','engineer')}
        with sqlite3.connect(self.root/'graph.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn);roles=ExplicitRoles(ws,saver,lambda role:roles_by_name[role])
            with patch('langgraph_migration.runtime.create_agent',side_effect=AssertionError('high-level loop forbidden')):
                result=scientific_flow(roles,saver).invoke({}, {'configurable':{'thread_id':'process:'+status},'recursion_limit':100})
        self.assertEqual(result['status'],'completed')
        self.assertEqual([t['role'] for t in ws.state['tasks']],['analyst','verifier','mechanist','verifier','engineer'])
        h=ws.state['hypotheses'][0];verdict=h['verdicts'][0]
        self.assertEqual(h['status'],status);self.assertEqual(verdict['subject']['prediction'],h['prediction'])
        self.assertTrue(ws.state['artifact_reviews'][0]['independent_source_reads'])
        algorithm=ws.state['algorithms'][0];self.assertEqual(algorithm['hypothesis_ids'],[h['id']])
        report=algorithm['behavior_comparisons']['baseline']['comparisons']
        self.assertGreater(report['forecast_rows']['changed_rows'],0)
        self.assertEqual(report['order_decisions']['status'],'compared')
        if status=='unresolved':
            trial=ws.state['experiments'][0];self.assertEqual(trial['kind'],'supply_trial')
            lo,hi=trial['summary']['cluster_interval_97_5'];self.assertLessEqual(lo,0);self.assertGreaterEqual(hi,0)
        else:
            observed=pd.read_csv(ws.state['experiments'][0]['observations'])
            mismatches=(observed.sales!=observed.opening_stock+observed.restock-observed.closing_stock).sum()
            self.assertEqual(int(mismatches),0)  # supports equality, refutes existence of mismatch on these rows
        self.close_and_evaluate(ws,result,inject_failure=status=='refuted')

    def test_supported_scoped_record_prediction(self):self.full_path('supported_in_scope')
    def test_refuted_prediction_and_actual_final_evaluator_recovery(self):self.full_path('refuted')
    def test_unresolved_intervention_and_actual_trial(self):self.full_path('unresolved')
    def test_no_change_without_hypotheses_and_actual_final_evaluation(self):
        ws=ScientificWorkspace(self.root/'workspace',OfficeWorld('confounding',9137,'office-business-v0.3'))
        model=ScriptedModel(sequence=[('finish_research',{'selected_algorithm_id':'baseline','outcome':'no_change',
            'summary':'Scripted no-change control path','limitations':['No hypothesis or new algorithm; not autonomous research evidence']})])
        with sqlite3.connect(self.root/'graph.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn);roles=ExplicitRoles(ws,saver,lambda role:model)
            result=scientific_flow(roles,saver).invoke({}, {'configurable':{'thread_id':'process:no_change'}})
        self.assertFalse(ws.state['hypotheses']);self.assertFalse(result['step']['engineering_delivered'])
        self.assertEqual(result['step']['outcome'],'no_change')
        self.close_and_evaluate(ws,result)


if __name__=='__main__':unittest.main()
