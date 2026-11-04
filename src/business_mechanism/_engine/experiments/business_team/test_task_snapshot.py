"""Task-authority/recovery checks; scripted choices are not scientific results."""
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage,ToolMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.runtime import FrameworkRoles,role_task_context,TaskInputChangedError
from langgraph_migration.science import ScientificWorkspace
from world import OfficeWorld


class SnapshotModel(BaseChatModel):
    ws:object=Field(exclude=True)
    interrupt:bool=False
    change_source:bool=False
    calls:int=0
    @property
    def _llm_type(self):return 'scripted-task-authority'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        self.calls+=1
        self_check=role_task_context.get()
        if self_check is None or self_check['phase_contract']['phase']!='needs_hypotheses':raise AssertionError('native model lost its task authority')
        if messages[-1].type!='system' or 'needs_hypotheses' not in messages[-1].content:raise AssertionError('system instructions lost the pinned duty')
        prior=[m for m in messages if isinstance(m,ToolMessage) and m.name=='read_context']
        if not prior:
            self.ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=['different_coordinator_assignment']);self.ws.persist()
            if self.change_source:
                p=self.ws.public/'products.csv';p.write_bytes(p.read_bytes()+b'\n')
            name='read_context';args={}
        else:
            received=json.loads(prior[-1].content)['result']
            if received['workflow']['phase']!='needs_hypotheses' or received['workflow']['hypothesis_ids']!=[]:
                raise AssertionError('tool feedback followed another coordinator assignment')
            if self.interrupt:raise KeyboardInterrupt('fixture after durable context receipt')
            name='save_hypothesis';args={'explanation':'scripted task fixture','scope':'received history','alternatives':['fixture alternative'],
                'prediction':'fixture conditional prediction','falsification':'fixture negative outcome','evidence_files':[str(self.ws.public/'history.csv')],
                'change_reason':'fixture incremental publication','parent_id':None}
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[{'name':name,'args':args,'id':f'fixture_{self.calls}','type':'tool_call'}]))])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_task_')
        self.root=Path(self.temp.name);self.ws=ScientificWorkspace(self.root/'S001',OfficeWorld('relationship',7400))
        self.ws.state['workflow']['phase']='needs_hypotheses';self.ws.persist()
        self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
    def tearDown(self):self.conn.close();self.temp.cleanup()
    def test_native_role_and_restart_use_durable_task_not_new_coordinator_phase(self):
        task={'id':'durable_fixture','inputs':self.ws.state['base_source_paths']}
        first=SnapshotModel(ws=self.ws,interrupt=True);roles=FrameworkRoles(self.ws,self.saver,lambda role:first)
        with self.assertRaises(KeyboardInterrupt):roles.run('mechanist',task)
        oldroot=self.ws.root;self.ws=ScientificWorkspace(oldroot,OfficeWorld('relationship',7400),reopen=True)
        second=SnapshotModel(ws=self.ws);roles=FrameworkRoles(self.ws,self.saver,lambda role:second)
        result=roles.run('mechanist',task)
        self.assertEqual(result['id'],'H001');self.assertEqual(second.calls,1)
        self.assertEqual(sum(e['tool']=='read_context' for e in self.ws.state['events']),1)
        self.assertEqual(roles.run('mechanist',task)['id'],'H001');self.assertEqual(second.calls,1)
        thread=self.conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE 'S001:mechanist:%'").fetchone()[0]
        state=roles.agents['mechanist'].get_state({'configurable':{'thread_id':thread}}).values
        self.assertEqual(state['task_snapshot']['workflow']['phase'],'needs_hypotheses')
        self.assertEqual(state['task_snapshot']['workspace_root'],str(oldroot))
    def test_changed_input_aborts_and_audits_instead_of_paid_error_loop(self):
        model=SnapshotModel(ws=self.ws,change_source=True);roles=FrameworkRoles(self.ws,self.saver,lambda role:model)
        with self.assertRaises(TaskInputChangedError):roles.run('mechanist',{'id':'changed_fixture','inputs':self.ws.state['base_source_paths']})
        self.assertEqual(model.calls,1);self.assertEqual(self.ws.state['hypotheses'],[])
        self.assertEqual(self.ws.state['events'][-1]['result']['error_type'],'TaskInputChangedError')
    def test_concurrent_contexts_keep_distinct_permissions_without_claiming_concurrent_tools(self):
        FrameworkRoles(self.ws,self.saver,lambda role:None)
        binding=self.ws.task_binding({'inputs':[]});barrier=threading.Barrier(2)
        def inspect(phase):
            task=self.ws.capture_task('verifier',{'id':phase,'execution_phase':phase,'inputs':[]},binding)
            token=role_task_context.set(task)
            try:
                barrier.wait(timeout=5)
                return self.ws.phase_contract()['phase'],self.ws.tool_allowed_now('review_artifact'),self.ws.tool_allowed_now('record_verdict')
            finally:role_task_context.reset(token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(inspect,'needs_review');b=pool.submit(inspect,'needs_validation')
            self.assertEqual(a.result(),('needs_review',True,False));self.assertEqual(b.result(),('needs_validation',False,True))
        self.assertIsNone(role_task_context.get())
    def test_hypothesis_definition_is_pinned_but_added_feedback_is_allowed(self):
        FrameworkRoles(self.ws,self.saver,lambda role:None)
        h=self.ws.tool('mechanist','save_hypothesis',{'explanation':'fixture','scope':'received history','alternatives':['alternative'],
            'prediction':'fixture prediction','falsification':'fixture counterexample','evidence_files':[str(self.ws.public/'history.csv')],
            'change_reason':'fixture','parent_id':None})
        task=self.ws.capture_task('verifier',{'id':'definition_fixture','execution_phase':'needs_validation','hypothesis_ids':[h['id']],'inputs':[]},self.ws.task_binding({'inputs':[]}))
        token=role_task_context.set(task)
        try:
            h.update(status='unresolved',verdicts=[{'status':'unresolved'}]);self.ws.validate_task_inputs()
            h['prediction']='silently changed prediction'
            with self.assertRaisesRegex(TaskInputChangedError,'definition changed'):self.ws.validate_task_inputs()
        finally:role_task_context.reset(token)


if __name__=='__main__':unittest.main()
