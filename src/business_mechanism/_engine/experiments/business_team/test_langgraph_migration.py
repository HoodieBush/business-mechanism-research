"""Native framework checks with scripted models, never model ability evidence."""
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from run_information_protocol import InformationWorkspace
from run_langgraph_migration import reopen_workspace
from langgraph_migration.runtime import FrameworkRoles,information_flow
from langgraph_migration.provider import APIJournal
from langgraph_migration.pacing import SharedTokenPacer


class ScriptedModel(BaseChatModel):
    sequence:list=Field(exclude=True)
    calls:int=0
    @property
    def _llm_type(self):return 'scripted-framework-test'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        if self.calls>=len(self.sequence):raise AssertionError('unexpected model call; completed work must not repeat')
        action=self.sequence[self.calls];self.calls+=1
        message=AIMessage(content=action) if isinstance(action,str) else AIMessage(content='',tool_calls=[{'name':action[0],'args':action[1],'id':f'unit_{self.calls}','type':'tool_call'}])
        return ChatResult(generations=[ChatGeneration(message=message)])


def submission(files=()):return ('submit_result',{'summary':'scripted engineering fixture','evidence_files':list(map(str,files)),'findings':[],'next_step':'fixture finished'})
def checks(decision):
    return [{'aspect':aspect,'status':'problem' if decision=='rejected' and aspect=='interpretation' else 'checked',
             'rationale':'scripted protocol fixture; not independent semantic model judgment'}
            for aspect in ('source_binding','transformation','units','grain','availability','interpretation')]


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_langgraph_')
        self.root=Path(self.temp.name)
        self.ws=InformationWorkspace(self.root/'U001',{'domain':'orders','construction':'count'})
        (self.ws.root/'role_prompts.json').write_text(json.dumps(self.ws.role_prompts))
        self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
    def tearDown(self):self.conn.close();self.temp.cleanup()
    def roles(self,models):return FrameworkRoles(self.ws,self.saver,lambda role:models[role])
    def reviewer(self,decision):
        return ScriptedModel(sequence=[('read_artifact',{'path':str(self.ws.draft)}),
             ('run_python',{'code':"from research_data import read_table\nprint(read_table('observations').shape)",'purpose':'scripted independent access','output_semantics':'shape only'}),
             ('review_artifact',{'artifact_id':'artifact_0001','execution_id':'execution_0002','decision':decision,'checks':checks(decision),'summary':'scripted review'}),submission([self.ws.draft])])
    def test_framework_repairs_typed_argument_error_then_finishes(self):
        model=ScriptedModel(sequence=[('read_context',{'unexpected':True}),('read_context',{}),submission()])
        result=self.roles({'verifier':model}).run('verifier',{'question':'unit protocol validation'})
        self.assertEqual(result['role'],'verifier');self.assertEqual(model.calls,3)
        actions=[json.loads(l) for l in (self.ws.root/'framework_tools.jsonl').read_text().splitlines()]
        self.assertFalse(actions[0]['feedback']['ok']);self.assertTrue(actions[1]['feedback']['ok'])
    def test_failed_submission_does_not_end_role(self):
        model=ScriptedModel(sequence=[submission(['missing.csv']),submission()])
        result=self.roles({'verifier':model}).run('verifier',{'question':'invalid terminal input'})
        self.assertEqual(model.calls,2);self.assertEqual(result['evidence_files'],[])
    def test_text_intention_does_not_finish_or_repeat_completed_execution(self):
        model=ScriptedModel(sequence=['I will now inspect the data.',
            ('run_python',{'code':"open('once.txt','w').write('executed')",'purpose':'actual execution','output_semantics':'execution marker'}),
            'The work is complete.',submission()])
        result=self.roles({'verifier':model}).run('verifier',{'question':'generic actual-action completion'})
        self.assertEqual(model.calls,4);self.assertEqual(result['role'],'verifier')
        actions=[json.loads(l) for l in (self.ws.root/'framework_tools.jsonl').read_text().splitlines()]
        self.assertEqual([a['tool'] for a in actions],['run_python','submit_result'])
        self.assertEqual(len(list(self.ws.workers['verifier'].directory.glob('analysis_*.py'))),1)
    def test_text_recovery_checkpoints_continue_without_replaying_tools(self):
        task={'question':'interrupt during generic text-only recovery'}
        model=ScriptedModel(sequence=[('read_context',{}),'I will deliver later.'])
        with self.assertRaisesRegex(AssertionError,'unexpected model call'):
            self.roles({'verifier':model}).run('verifier',task)
        self.conn.close();self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
        self.ws=reopen_workspace(self.ws.root)
        resumed=ScriptedModel(sequence=[submission()])
        result=self.roles({'verifier':resumed}).run('verifier',task)
        self.assertEqual(result['role'],'verifier');self.assertEqual(resumed.calls,1)
        actions=[json.loads(l) for l in (self.ws.root/'framework_tools.jsonl').read_text().splitlines()]
        self.assertEqual([a['tool'] for a in actions],['read_context','submit_result'])
    def test_unknown_usage_retries_reserve_global_cost_without_claiming_tokens(self):
        pacer=SharedTokenPacer(self.root/'test_pacing',1_000_000_000)
        journal=APIJournal(self.root,{'model':'fixture'},budget=300,max_output=100,pacer=pacer)
        payload={'messages':[{'role':'user','content':'x'*100}]}
        with patch('langgraph_migration.provider.request_model',return_value={'response':{},'error_type':'transport','error':'timeout'} ) as request,patch('langgraph_migration.provider.interruptible_wait'):
            with self.assertRaisesRegex(RuntimeError,'reported-cost admission'):
                journal.call('verifier',payload)
        self.assertEqual(request.call_count,1)
        self.assertGreater(journal.unknown_usage_reserve(),0);self.assertEqual(journal.usage()['total_tokens'],0)
        self.assertEqual(journal.usage()['calls_without_reported_usage'],1)
        # Separate-process admission retains the reservation; no request repeats.
        restored=APIJournal(self.root,{'model':'fixture'},budget=300,max_output=100,pacer=pacer)
        with patch('langgraph_migration.provider.request_model') as request:
            with self.assertRaisesRegex(RuntimeError,'reported-cost admission'):restored.call('verifier',payload)
            request.assert_not_called()
    def test_different_tasks_do_not_share_receipts_when_provider_ids_repeat(self):
        for question in ('first task','different task'):
            model=ScriptedModel(sequence=[('read_context',{}),submission()])
            self.roles({'verifier':model}).run('verifier',{'question':question})
        self.assertEqual(len(self.ws.state['results']),2)
        self.assertNotEqual(self.ws.state['results'][0]['operation_id'],self.ws.state['results'][1]['operation_id'])
    def test_completed_role_reopens_without_repeating_python_or_model(self):
        code="from pathlib import Path\np=Path('counter.txt');p.write_text(str(int(p.read_text())+1 if p.exists() else 1))"
        model=ScriptedModel(sequence=[('run_python',{'code':code,'purpose':'restart execution counter','output_semantics':'one execution count'}),submission()])
        task={'question':'same saved task'};first=self.roles({'verifier':model}).run('verifier',task)
        self.conn.close();self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
        self.ws=reopen_workspace(self.ws.root)
        second=self.roles({'verifier':ScriptedModel(sequence=[])}).run('verifier',task)
        self.assertEqual(first,second);self.assertEqual((self.ws.workers['verifier'].directory/'counter.txt').read_text(),'1')
    def test_reviewed_handoff_resumes_at_consumer(self):
        consumer=ScriptedModel(sequence=[('read_artifact',{'path':str(self.ws.draft)}),submission([self.ws.draft])])
        roles=self.roles({'verifier':self.reviewer('accepted'),'mechanist':consumer})
        config={'configurable':{'thread_id':'parent-flow'}}
        flow=information_flow(roles,self.saver,interrupt_before_consumer=True)
        flow.invoke({},config);self.assertEqual(flow.get_state(config).next,('consume',));self.assertEqual(consumer.calls,0)
        self.conn.close();self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
        self.ws=reopen_workspace(self.ws.root)
        reopened=self.roles({'verifier':ScriptedModel(sequence=[]),'mechanist':consumer})
        output=information_flow(reopened,self.saver).invoke(None,config)
        self.assertEqual(output['status'],'handoff_completed');self.assertEqual(consumer.calls,2)
    def test_rejected_handoff_blocks_consumer_with_correct_permissions(self):
        consumer=ScriptedModel(sequence=[])
        output=information_flow(self.roles({'verifier':self.reviewer('rejected'),'mechanist':consumer}),self.saver).invoke({}, {'configurable':{'thread_id':'blocked'}})
        self.assertEqual(output['decision'],'rejected');self.assertEqual(output['status'],'handoff_blocked');self.assertEqual(consumer.calls,0)
        # A valid original input is still readable; rejection is not a missing menu.
        self.assertTrue('read_artifact' in self.ws.tool_menus['mechanist'])


if __name__=='__main__':unittest.main()
