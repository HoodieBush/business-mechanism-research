"""Real sandbox, data, reviews and measurement; researcher choices are scripted."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from world import OfficeWorld
from workspace import write_json
from langgraph_migration.mechanism_research import MechanismWorkspace, mechanism_flow
from langgraph_migration.explicit_runtime import ExplicitRoles
from test_process_integration import ProcessPolicy
from test_mechanism_research import update, schedule, finish
from run_mechanism_research import freeze_research


class MechanismProcessPolicy(ProcessPolicy):
    def _generate(self,messages,**kwargs):
        ws=self.ws
        if self.role!='manager':
            result=super()._generate(messages,**kwargs)
            for call in result.generations[0].message.tool_calls:
                if call['name']=='finish_validation':
                    h=ws.state['hypotheses'][-1]
                    call['args']={'hypothesis_ids':[h['id']],
                        'outcome_type':'scoped_support' if self.verdict_status=='supported_in_scope' else 'counterevidence',
                        'summary':'Actual registered record audit, scripted interpretation.',
                        'evidence_files':[ws.state['experiments'][-1]['observations']],
                        'limitations':['Same simulation records; not independent physical measurement or causal discovery.'],
                        'suggested_next':'Update what the record check establishes and leave mechanism questions open.'}
            return result
        state=ws.research_state_view(); hs=ws.state['hypotheses']; packets=ws.state.get('packets',{})
        if state['update_required']:
            action=('update_research_state',update(state['revision'],hypothesis_ids=[h['id'] for h in hs],
                learned='Read the actual latest delivery; record consistency and causal explanations remain distinct.'))
        elif not packets:action=('schedule_task',schedule('analyst','analysis'))
        elif not ws.state['artifact_reviews']:
            action=('schedule_task',schedule('verifier','information_review',packet_id=list(packets)[-1]))
        elif not hs:action=('schedule_task',schedule())
        elif not hs[-1].get('verdicts'):action=('schedule_task',schedule('verifier','validation',hypothesis_ids=[hs[-1]['id']]))
        else:
            h=hs[-1];action=('finish_research',finish(outcome='research_completed',conclusions=[{
                'kind':'data_quality','hypothesis_id':h['id'],'status':h['status'],'scope':h['scope'],
                'statement':'Scoped record claim only; actual data audit does not establish a demand mechanism.',
                'evidence_files':[ws.state['experiments'][-1]['observations']]}]))
        n=self.counts.get('manager',0);self.counts['manager']=n+1
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[{
            'name':action[0],'args':action[1],'id':f'manager_{n}','type':'tool_call'}]))])


class MechanismSandboxTests(unittest.TestCase):
    def setUp(self):
        configured=os.environ.get('PROCESS_ACCEPTANCE_OUTPUT')
        self.temp=None if configured else tempfile.TemporaryDirectory(prefix='mechanism_sandbox_')
        self.root=Path(configured or self.temp.name).resolve()/self._testMethodName
        self.root.mkdir(parents=True,exist_ok=False)
    def tearDown(self):
        if self.temp:self.temp.cleanup()

    def full_path(self,status):
        ws=MechanismWorkspace(self.root/'workspace',OfficeWorld('confounding',9137,'office-business-v0.3'))
        models={r:MechanismProcessPolicy(ws=ws,role=r,verdict_status=status) for r in ('manager','analyst','mechanist','verifier')}
        with sqlite3.connect(self.root/'graph.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn);roles=ExplicitRoles(ws,saver,lambda role:models[role],memory_profile='research_memory_v1')
            result=mechanism_flow(roles,saver).invoke({}, {'configurable':{'thread_id':'sandbox:'+status},'recursion_limit':60})
        self.assertEqual(result['status'],'completed')
        self.assertEqual([t['role'] for t in ws.state['tasks']],['analyst','verifier','mechanist','verifier'])
        self.assertEqual(ws.state['hypotheses'][0]['status'],status)
        self.assertTrue(ws.state['artifact_reviews'][0]['independent_source_reads'])
        self.assertEqual(ws.state['algorithms'],[]);self.assertEqual(ws.state['mechanism_research']['revision'],5)
        private=[ws.root/'mechanism_identity.json',*list((ws.root/'explicit_runtime_state').rglob('*.json'))[:1]]
        code='import json\nresults=[]\nfor p in '+repr(list(map(str,private)))+':\n try:\n  open(p).read();results.append("LEAK")\n except PermissionError:results.append("blocked")\nprint(json.dumps(results))'
        privacy=ws.workers['verifier'].run(code)
        self.assertTrue(privacy['ok'],privacy);self.assertEqual(json.loads(privacy['stdout']),['blocked']*len(private))
        frozen=freeze_research(ws,result['step'])
        with self.assertRaises(ValueError):MechanismWorkspace(ws.root,ws.world,reopen=True)
        write_json(self.root/'evidence.json',{'status':'passed','scientific_ability_certified':False,
            'scripted_choices':True,'model_calls':0,'actual_archive':str(ws.root),'freeze':frozen,'private_input_denial':privacy})

    def test_scoped_support_closes_without_algorithm_or_profit_evaluation(self):self.full_path('supported_in_scope')
    def test_actual_counterevidence_closes_without_automatic_engineering(self):self.full_path('refuted')


if __name__=='__main__':unittest.main()
