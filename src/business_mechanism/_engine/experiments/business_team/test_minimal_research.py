"""Process/engineering acceptance only. All model decisions are scripted.

Actual domain tools, sandbox and observations run locally; no HTTP is allowed.
These tests cannot certify autonomous discovery or architectural superiority.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage,SystemMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from execution import PythonWorkspace,last_number
from contracts import field_definition
from world import OfficeWorld
from workspace import ResearchWorkspace,sha,write_json
from langgraph_migration.science import ScientificWorkspace,scientific_flow
from langgraph_migration.explicit_runtime import ExplicitRoles,ControlIncomplete
from langgraph_migration.runtime import TaskInputChangedError,FrameworkRoles
from langgraph_migration.provider import APIJournal
from run_langgraph_science import ROOT,setup,evaluate_closed_case,evaluation_window,role_runtime,freeze_decision
from test_langgraph_migration import ScriptedModel
from test_langgraph_science import PolicyModel


class ExplicitPolicy(PolicyModel):
    """Reuse a scripted action policy, checking the new input protocol first."""
    verdict_status:str='unresolved'
    def _generate(self,messages,**kwargs):
        assert messages[-1].type=='human' and 'phase_contract' in messages[-1].content
        phase='coordination' if self.role=='manager' else self.ws.state['workflow']['phase']
        assert phase in messages[-1].content
        # Parent fixture checks the legacy system wrapper; its decisions are
        # deliberately reused without attributing them to the language model.
        adapted=[*messages,SystemMessage(content='当前阶段职责（系统状态提供）'+phase)]
        result=super()._generate(adapted,**kwargs)
        for call in result.generations[0].message.tool_calls:
            if call['name']=='record_verdict':call['args']['status']=self.verdict_status
        return result


class MinimalResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='minimal_research_')
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def request_prefix(self,events=(),returned=(1,),started=(1,2)):
        from explicit_continuation import settled_request_prefix
        directory=self.root/'prefix';directory.mkdir(exist_ok=True)
        (directory/'requests_started.jsonl').write_text(''.join(json.dumps({'request_index':i})+'\n' for i in started))
        (directory/'admission_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        return settled_request_prefix(directory,[{'request_index':i} for i in returned])
    def test_continuation_accepts_only_proven_not_sent_budget_request(self):
        self.assertEqual(self.request_prefix([{'request_index':2,'status':'shared_budget_stopped','request_sent':False}]),[2])
    def test_continuation_unknown_or_sent_request_still_rejected(self):
        for events in [[],[{'request_index':2,'status':'shared_budget_stopped','request_sent':True}],
                       [{'request_index':2,'status':'unverified','request_sent':False}]]:
            with self.assertRaisesRegex(ValueError,'unsettled'):self.request_prefix(events)
    def test_continuation_rejects_overlapping_response_and_not_sent_record(self):
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            self.request_prefix([{'request_index':2,'status':'shared_budget_stopped','request_sent':False}],returned=(1,2))
    def test_continuation_ordinary_settled_prefix_unchanged(self):
        self.assertEqual(self.request_prefix(returned=(1,2)),[])
    def workspace(self,name='case'):
        # State tests don't need baseline model fitting. This is explicitly a
        # fixture, not a successful sandbox/execution receipt.
        def forecast(worker,code,history,features,name):return [3.]*len(features),{'fixture':True}
        with patch.object(PythonWorkspace,'forecast',new=forecast):
            ws=ScientificWorkspace(self.root/name,OfficeWorld('confounding',9137,'office-business-v0.3'))
        FrameworkRoles(ws,None,lambda role:None)
        return ws

    def test_real_supervisor_graph_observes_yield_and_resumes_then_can_close_inconclusive(self):
        ws=self.workspace()
        manager=ScriptedModel(sequence=[
            ('schedule_task',{'role':'analyst','stage':'analysis','question':'inspect available evidence','inputs':[],'rationale':'fixture'}),
            ('resume_task',{'task_id':'T001'}),
            ('finish_research',{'selected_algorithm_id':'baseline','outcome':'inconclusive','summary':'missing independent evidence','limitations':['original analysis unfinished; no scientific conclusion']})])
        analyst=ScriptedModel(sequence=[('read_history',{}),('request_assistance',{'reason':'unavailable observation','needed_work':'obtain a new measurement','requested_capabilities':['measurement']})])
        with sqlite3.connect(self.root/'yield.sqlite',check_same_thread=False) as conn:
            roles=ExplicitRoles(ws,SqliteSaver(conn),lambda role:manager if role=='manager' else analyst,slice_steps=1)
            output=scientific_flow(roles,roles.saver).invoke({}, {'configurable':{'thread_id':'supervised-yield'},'recursion_limit':20})
        self.assertEqual(output['status'],'completed');self.assertEqual(manager.calls,3)
        self.assertEqual(len(ws.state['tasks']),1);self.assertEqual(analyst.calls,2)
        self.assertEqual(output['step']['outcome'],'inconclusive')

    def test_frozen_task_input_change_cannot_silently_start_new_context(self):
        ws=self.workspace();model=ScriptedModel(sequence=['unfinished'])
        task={'id':'frozen','question':'original question','inputs':[],'execution_phase':'needs_analysis'}
        roles=ExplicitRoles(ws,None,lambda role:model)
        roles.run('analyst',task)
        with self.assertRaises(TaskInputChangedError):roles.run('analyst',{**task,'question':'replacement question'})
        self.assertEqual(model.calls,1)

    def test_received_research_question_reaches_model_as_task_data(self):
        ws=self.workspace();question='Public task fixture: inspect one scoped record claim, preserve uncertainty.'
        model=ScriptedModel(sequence=[('finish_research',{'selected_algorithm_id':'baseline','outcome':'inconclusive','summary':'fixture','limitations':['no science claim']})])
        original=ScriptedModel._generate
        def generate(instance,messages,**kwargs):
            tasks=[json.loads(m.content)['task'] for m in messages if m.type=='human' and m.content.startswith('{') and '"task"' in m.content]
            self.assertEqual(tasks[0]['question'],question)
            self.assertFalse(any(question in m.content for m in messages if m.type=='system'))
            return original(instance,messages,**kwargs)
        with sqlite3.connect(self.root/'question.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn);roles=ExplicitRoles(ws,saver,lambda role:model)
            with patch.object(ScriptedModel,'_generate',new=generate):
                output=scientific_flow(roles,saver,research_question=question).invoke({}, {'configurable':{'thread_id':'received-question'}})
        self.assertEqual(output['status'],'completed')

    def test_collaboration_context_python_example_names_real_sql_table(self):
        import re
        from types import SimpleNamespace
        from python_reference import reference
        from langgraph_migration.collaboration import CollaborativeWorkspace
        ws=self.workspace()
        legacy=SimpleNamespace(public=ws.public,shared=ws.shared,workflow=lambda:{},
            contract=json.loads((ws.public/'data_dictionary.json').read_text()),case_context={'business_question':'fixture','entry':'fixture'})
        examples=re.findall(r'read_table\([\"\x27]([^\"\x27]+)[\"\x27]\)',CollaborativeWorkspace.initial_context(legacy)['python_tool'])
        self.assertTrue(examples)
        for name in examples:self.assertIn(name,reference(ws.public)['registered_sql_tables'])

    def test_continuation_preserves_dialogue_cursor_and_parent(self):
        import shutil
        from explicit_continuation import tree_hashes,configure_readonly_parent,relocate_explicit_checkpoints
        parent=self.workspace('parent');task={'id':'original','question':'original scoped question','inputs':[],'execution_phase':'needs_analysis'}
        first=ScriptedModel(sequence=['original unfinished marker'])
        original_roles=ExplicitRoles(parent,None,lambda role:first)
        original_roles.run('analyst',task)
        before=tree_hashes(parent.root);target=(self.root/'child').resolve();shutil.copytree(parent.root,target)
        write_json(target/'path_aliases.json',{str(parent.root):str(target)})
        child=ScientificWorkspace(target,OfficeWorld('confounding',9137,'office-business-v0.3'),reopen=True)
        configure_readonly_parent(child,parent.root)
        model=ScriptedModel(sequence=[('request_assistance',{'reason':'fixture','needed_work':'new measurement','requested_capabilities':['measurement']})])
        roles=ExplicitRoles(child,None,lambda role:model)
        self.assertEqual({p.name:sha(p) for p in parent.public.iterdir() if p.is_file()},
                         {p.name:sha(p) for p in child.public.iterdir() if p.is_file()})
        old=next((parent.root/'explicit_runtime_state/analyst').glob('*.json'));old_state=json.loads(old.read_text())
        receipt=relocate_explicit_checkpoints(child,parent.root,roles)
        new=json.loads(Path(receipt[0]['new_checkpoint']).read_text())
        self.assertEqual(new['messages'],old_state['messages']);self.assertEqual(new['model_steps'],1)
        self.assertEqual(new['task_snapshot']['workspace_root'],str(target))
        self.assertEqual(new['identity'],old_state['identity'])
        delivered=roles.run('analyst',task)
        self.assertEqual(delivered['kind'],'assistance_requested');self.assertEqual(model.calls,1)
        self.assertEqual(tree_hashes(parent.root),before)
        final=json.loads(Path(receipt[0]['new_checkpoint']).read_text())
        self.assertEqual(final['model_steps'],2)

    def test_continuation_rejects_changed_runtime_and_pending_batch(self):
        import shutil
        from explicit_continuation import relocate_explicit_checkpoints
        parent=self.workspace('parent');task={'id':'original','question':'original','inputs':[],'execution_phase':'needs_analysis'}
        ExplicitRoles(parent,None,lambda role:ScriptedModel(sequence=['unfinished'])).run('analyst',task)
        target=(self.root/'child').resolve();shutil.copytree(parent.root,target);write_json(target/'path_aliases.json',{str(parent.root):str(target)})
        child=ScientificWorkspace(target,OfficeWorld('confounding',9137,'office-business-v0.3'),reopen=True)
        roles=ExplicitRoles(child,None,lambda role:None)
        checkpoint=next((target/'explicit_runtime_state/analyst').glob('*.json'));state=json.loads(checkpoint.read_text());state['pending']=True;write_json(checkpoint,state)
        with self.assertRaisesRegex(ValueError,'settled tool batch'):relocate_explicit_checkpoints(child,parent.root,roles)
        state['pending']=False;write_json(checkpoint,state);roles.policy={**roles.policy,'slice_tools':99}
        with self.assertRaisesRegex(ValueError,'runtime policy'):relocate_explicit_checkpoints(child,parent.root,roles)

    def test_continuation_rejects_changed_input_version(self):
        import shutil
        from explicit_continuation import relocate_explicit_checkpoints
        parent=self.workspace('parent');task={'id':'original','question':'original','inputs':[str(parent.public/'products.csv')],'execution_phase':'needs_analysis'}
        ExplicitRoles(parent,None,lambda role:ScriptedModel(sequence=['unfinished'])).run('analyst',task)
        target=(self.root/'child').resolve();shutil.copytree(parent.root,target);write_json(target/'path_aliases.json',{str(parent.root):str(target)})
        child=ScientificWorkspace(target,OfficeWorld('confounding',9137,'office-business-v0.3'),reopen=True)
        (child.public/'products.csv').write_text('changed input')
        with self.assertRaisesRegex(ValueError,'input bytes'):relocate_explicit_checkpoints(child,parent.root,ExplicitRoles(child,None,lambda role:None))

    def test_manager_slices_resume_same_control_task_before_dispatch(self):
        ws=self.workspace();manager=ScriptedModel(sequence=[('read_context',{}),('read_history',{}),
            ('schedule_task',{'role':'analyst','stage':'analysis','question':'inspect evidence','inputs':[],'rationale':'fixture'}),
            ('finish_research',{'selected_algorithm_id':'baseline','outcome':'inconclusive','summary':'measurement unavailable','limitations':['fixture']})])
        analyst=ScriptedModel(sequence=[('request_assistance',{'reason':'missing observation','needed_work':'measure independently','requested_capabilities':['measurement']})])
        with sqlite3.connect(self.root/'manager_slice.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn);roles=ExplicitRoles(ws,saver,lambda role:manager if role=='manager' else analyst,slice_tools=1)
            result=scientific_flow(roles,saver).invoke({}, {'configurable':{'thread_id':'manager-slices'},'recursion_limit':20})
        self.assertEqual(result['status'],'completed');self.assertEqual(manager.calls,4)
        self.assertEqual(len(ws.state['tasks']),1)
        self.assertEqual(len(ws.state['supervision_inputs']),2)
        other=self.workspace('manager_bytes');never=ScriptedModel(sequence=[])
        with self.assertRaises(ControlIncomplete):
            ExplicitRoles(other,None,lambda role:never,max_request_bytes=1024).run('manager',{'id':'byte_stop','question':'fixture','inputs':[]})
        self.assertEqual(never.calls,0)

    def test_full_runner_preflight_can_create_each_evidence_directory_once(self):
        # This tests the real setup composition, not the nested suites' results.
        # Their actual sandbox executions are separately required by acceptance.
        with tempfile.TemporaryDirectory(dir=ROOT/'experiments/business_team/results',prefix='unit_setup_') as folder:
            base=Path(folder);output=base/'phase';spec=base/'spec.json'
            write_json(spec,{'phase':'setup_fixture','output_directory':str(output.relative_to(ROOT)),
                             'role_runtime':'explicit_v1','cases':[]})
            paths=[]
            def claim(path):
                paths.append(Path(path));Path(path).mkdir(parents=True,exist_ok=False)
            def probe(path):claim(path);return {'ready':True,'fixture':True}
            def acceptance(path,mode):claim(path);return {'status':'passed','fixture':True,'mode':mode}
            with patch('environment_readiness.sandbox_probe',side_effect=probe),patch('process_acceptance.run',side_effect=acceptance):
                self.assertEqual(setup(spec),output)
            self.assertEqual(len(paths),3);self.assertEqual(len(set(paths)),3)

    def test_role_transcripts_are_not_shared_artifacts(self):
        ws=self.workspace();model=ScriptedModel(sequence=['private transcript fixture'])
        roles=ExplicitRoles(ws,None,lambda role:model)
        task={'id':'private_context','question':'context boundary fixture','inputs':[],'execution_phase':'needs_analysis'}
        yielded=roles.run('analyst',task)
        checkpoint=Path(yielded['checkpoint'])
        for path in (checkpoint,checkpoint.with_suffix('.responses.jsonl')):
            self.assertTrue(path.is_file())
            with self.assertRaisesRegex(ValueError,'outside'):
                roles.execute('verifier','read_artifact',{'path':str(path)})
        self.assertFalse(checkpoint.is_relative_to(ws.shared))
        # An old shared-storage workspace must not silently resume a new empty
        # private conversation under the same experiment identity.
        policy=ws.state['framework_runtime']['explicit_policy']
        policy.pop('checkpoint_storage',None)
        with self.assertRaises(TaskInputChangedError):ExplicitRoles(ws,None,lambda role:model)

    def test_tool_batch_is_serial_and_can_yield_mid_response_without_another_model_call(self):
        ws=self.workspace();model=ScriptedModel(sequence=[])
        response=AIMessage(content='',tool_calls=[{'name':name,'args':{},'id':str(i),'type':'tool_call'} for i,name in enumerate(('read_history','read_context'))])
        roles=ExplicitRoles(ws,None,lambda role:model,slice_tools=1)
        task={'id':'serial_batch','question':'read sources in order','inputs':[],'execution_phase':'needs_analysis'}
        with patch.object(ScriptedModel,'_generate',return_value=ChatResult(generations=[ChatGeneration(message=response)])) as generate:
            first=roles.run('analyst',task);second=roles.run('analyst',task)
        self.assertEqual(generate.call_count,1)
        self.assertEqual(first['kind'],'role_yield');self.assertEqual(second['kind'],'role_yield')
        self.assertEqual([e['tool'] for e in ws.state['events']],['read_history','read_context'])

    def test_counter_restart_and_exclusive_creation_above_999(self):
        directory=self.root/'worker';directory.mkdir()
        (directory/'analysis_999.py').write_text('old')
        (directory/'analysis_1000.py').write_text('new')
        (directory/'query_1001.csv').write_text('x\n1\n')
        worker=PythonWorkspace(directory,self.root,self.root,per_execution=True)
        self.assertEqual(worker.count,1000)
        self.assertEqual(last_number(directory,'query_','.csv'),1001)
        (directory/'executions/run_1001').mkdir(parents=True)
        with self.assertRaises(FileExistsError):worker.run('print(1)')
        self.assertEqual((directory/'analysis_1000.py').read_text(),'new')

    def test_scoped_verdicts_cannot_erase_previous_refutation(self):
        ws=self.workspace();ws.require_artifact_review=False
        h={'id':'H001','scope':'original population','prediction':'two competing claims','status':'proposed','evidence_files':[]}
        ws.state['hypotheses']=[h];ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=['H001'])
        for status in ('refuted','supported_in_scope','unresolved'):
            ws.tool('verifier','record_verdict',{'hypothesis_id':'H001','status':status,'rationale':'scripted scoped interpretation','evidence_files':[str(ws.public/'history.csv')]})
        self.assertEqual(h['status'],'mixed');self.assertEqual(len(h['verdicts']),3)
        self.assertEqual(h['verdict_statuses'],['refuted','supported_in_scope','unresolved'])

    def test_evidence_reference_failure_identifies_item_without_dropping_or_resolving_object(self):
        ws=self.workspace();observations=ws.shared/'experiments/E001/observations.csv'
        observations.parent.mkdir(parents=True);observations.write_text('sales\n1\n')
        ws.state['experiments']=[{'id':'E001','observations':str(observations)}]
        exact=ws.reference(observations);before=json.dumps(ws.state,sort_keys=True)
        with self.assertRaisesRegex(ValueError,r'evidence_files\[1\].*E001.*experiment object.*observations.csv'):
            ws.refs([exact,'E001'])
        self.assertEqual(json.dumps(ws.state,sort_keys=True),before)
        self.assertEqual(ws.refs([exact]),[str(observations)])
        for invalid in ('E999','V001','../private.json'):
            with self.assertRaisesRegex(ValueError,r'evidence_files\[0\]'):
                ws.refs([invalid])

    def test_byte_blocked_task_cannot_be_resumed_as_a_soft_slice(self):
        ws=self.workspace();task=ws.tool('manager','schedule_task',{'role':'analyst','question':'inspect','inputs':[],'rationale':'fixture'})
        model=ScriptedModel(sequence=[]);roles=ExplicitRoles(ws,None,lambda role:model,max_request_bytes=1024)
        received={k:v for k,v in task.items() if k not in ('kind','operation_id')}
        yielded=roles.run('analyst',received)
        self.assertEqual(yielded['status'],'blocked');self.assertFalse(yielded['resumable'])
        checkpoint=Path(yielded['checkpoint']);original=checkpoint.read_bytes()
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'cannot resume.*byte'):
                ws.tool('manager','resume_task',{'task_id':task['id']})
        self.assertEqual(checkpoint.read_bytes(),original);self.assertEqual(model.calls,0)
        # Old pending records carried the same deterministic hard-bound reason.
        ws.state['runtime_yields'][task['id']]['status']='pending'
        ws.state['runtime_yields'][task['id']].pop('resumable')
        with self.assertRaisesRegex(ValueError,'cannot resume.*byte'):
            ws.tool('manager','resume_task',{'task_id':task['id']})

    def test_null_exit_needs_no_hypothesis_or_invented_engineering(self):
        ws=self.workspace()
        args={'selected_algorithm_id':'baseline','summary':'insufficient evidence to justify work','limitations':['no scientific claim'],'outcome':'inconclusive'}
        model=ScriptedModel(sequence=[('finish_research',args)])
        with sqlite3.connect(self.root/'graph.sqlite',check_same_thread=False) as conn:
            roles=ExplicitRoles(ws,SqliteSaver(conn),lambda role:model)
            result=scientific_flow(roles,roles.saver).invoke({}, {'configurable':{'thread_id':'null'}})
        self.assertEqual(result['status'],'completed')
        self.assertFalse(result['step']['engineering_delivered'])
        self.assertEqual(result['step']['outcome'],'inconclusive')
        self.assertFalse(ws.state['hypotheses']);self.assertFalse(ws.state['algorithms'])

    def test_no_engineering_cannot_claim_completed_research_or_new_program(self):
        ws=self.workspace()
        for selected,outcome in [('baseline','research_completed'),('strong_numeric','no_change')]:
            with self.assertRaisesRegex(ValueError,'without engineering'):
                ws.tool('manager','finish_research',{'selected_algorithm_id':selected,'summary':'fixture','limitations':['fixture'],'outcome':outcome})

    def test_slice_yields_then_supervisor_resumes_original_thread(self):
        ws=self.workspace()
        task=ws.tool('manager','schedule_task',{'role':'analyst','stage':'analysis','question':'inspect source without inventing results','inputs':[], 'rationale':'fixture'})
        received={k:v for k,v in task.items() if k not in ('kind','operation_id')}
        model=ScriptedModel(sequence=[('read_history',{}),('request_assistance',{'reason':'need independent source','needed_work':'collect missing observation','requested_capabilities':['measurement']})])
        roles=ExplicitRoles(ws,None,lambda role:model,slice_steps=1)
        first=roles.run('analyst',received)
        self.assertEqual(first['kind'],'role_yield');self.assertEqual(len(ws.state['results']),0)
        self.assertEqual(first['status'],'pending');self.assertTrue(first['resumable'])
        resumed=ws.tool('manager','resume_task',{'task_id':task['id']})
        self.assertEqual(resumed,task)
        second=roles.run('analyst',received)
        self.assertEqual(second['kind'],'assistance_requested');self.assertEqual(model.calls,2)
        self.assertEqual(ws.state['runtime_yields'][task['id']]['status'],'delivered')
        self.assertEqual(len(ws.state['tasks']),1)
        ws.state['runtime_yields'][task['id']]['status']='pending'
        self.assertEqual(roles.run('analyst',received),second);self.assertEqual(model.calls,2)
        self.assertEqual(ws.state['runtime_yields'][task['id']]['status'],'delivered')

    def test_pending_paid_response_recovers_without_duplicate_side_effect_or_model_call(self):
        ws=self.workspace()
        task=ws.tool('manager','schedule_task',{'role':'analyst','question':'read and hand over','inputs':[],'rationale':'fixture'})
        received={k:v for k,v in task.items() if k not in ('kind','operation_id')}
        model=ScriptedModel(sequence=[('request_assistance',{'reason':'missing observation','needed_work':'measure independently','requested_capabilities':['measurement']})])
        roles=ExplicitRoles(ws,None,lambda role:model)
        original=roles._save;crashed=[False]
        def save(path,state,messages):
            if state.get('role_result') and not crashed[0]:
                crashed[0]=True;raise RuntimeError('injected crash after side effect, before inner checkpoint')
            original(path,state,messages)
        with patch.object(roles,'_save',side_effect=save):
            with self.assertRaisesRegex(RuntimeError,'injected crash'):roles.run('analyst',received)
        self.assertEqual(len(ws.state['support_requests']),1)
        self.assertEqual(roles.run('analyst',received)['kind'],'assistance_requested')
        self.assertEqual(len(ws.state['support_requests']),1);self.assertEqual(model.calls,1)

    def test_text_only_yields_once_and_context_boundary_sends_no_model_call(self):
        ws=self.workspace()
        task={'id':'T_text','question':'incomplete task','inputs':[],'execution_phase':'needs_analysis'}
        model=ScriptedModel(sequence=['done in words'])
        result=ExplicitRoles(ws,None,lambda role:model).run('analyst',task)
        self.assertEqual(result['kind'],'role_yield');self.assertEqual(result['model_steps'],1)
        other=self.workspace('bytes');never=ScriptedModel(sequence=[])
        result=ExplicitRoles(other,None,lambda role:never,max_request_bytes=1024).run('analyst',task)
        self.assertEqual(result['kind'],'role_yield');self.assertEqual(never.calls,0)
        with self.assertRaises(TaskInputChangedError):ExplicitRoles(other,None,lambda role:never,max_request_bytes=2048)

    def test_budget_notsent_is_excluded_but_real_unknown_is_retained(self):
        write_json(self.root/'unused.json',{})
        (self.root/'requests_started.jsonl').write_text('\n'.join(json.dumps({'request_index':i,'admission_estimate':100}) for i in (1,2,3)))
        (self.root/'admission_events.jsonl').write_text(json.dumps({'request_index':1,'request_sent':False})+'\n'+json.dumps({'request_index':2,'request_sent':True}))
        self.assertEqual(APIJournal(self.root,{}).unknown_usage_reserve(),200)

    def test_observation_time_and_executable_evaluation_window(self):
        self.assertIn('after business-day close',field_definition('observed_stockout_hours',True)['available_at'])
        self.assertEqual(evaluation_window({'evaluation_plan':{'evaluation_window':{'first_day':180,'calendar_days':7}}}),{'first_day':180,'calendar_days':7})
        for window in ({'first_day':112,'calendar_days':7},{'first_day':140,'calendar_days':True},{'first_day':140,'calendar_days':0}):
            with self.assertRaises(ValueError):evaluation_window({'evaluation_plan':{'evaluation_window':window}})

    def test_evaluator_recovery_reuses_completed_labels_and_never_runs_actor(self):
        ws=self.workspace();path=ws.root
        decision={'selected_algorithm_id':'baseline','outcome':'inconclusive'}
        with self.assertRaisesRegex(ValueError,'close the Actor'):freeze_decision(ws,path,decision,{})
        ws.state['workflow']['phase']='complete'  # explicit state fixture, not autonomous delivery
        with self.assertRaisesRegex(ValueError,'actual manager delivery'):freeze_decision(ws,path,decision,{})
        ws.state['workflow']['phase']='needs_analysis'
        model=ScriptedModel(sequence=[('finish_research',decision|{'summary':'scoped no-change control','limitations':['fixture, no scientific result']})])
        with sqlite3.connect(self.root/'freeze.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn);roles=ExplicitRoles(ws,saver,lambda role:model)
            decision=scientific_flow(roles,saver).invoke({}, {'configurable':{'thread_id':'freeze-delivery'}})['step']
        freeze_decision(ws,path,decision,{})
        with self.assertRaisesRegex(ValueError,'already frozen'):freeze_decision(ws,path,decision,{})
        calls=[]
        def evaluate(filename,**kw):
            calls.append(kw['name'])
            if len(calls)==2:raise RuntimeError('injected final evaluator failure')
            return {'code_sha256':sha(filename),'score':1}
        record={}
        with patch.object(ws,'evaluate_code',side_effect=evaluate):
            with self.assertRaisesRegex(RuntimeError,'injected'):evaluate_closed_case(ws,path,{},record)
            evaluate_closed_case(ws,path,{},record)
        self.assertEqual(calls.count('final_selected'),1);self.assertEqual(len(calls),5)
        self.assertEqual(len(record['final_evaluation']),4);self.assertEqual(record['status'],'completed')
        with self.assertRaisesRegex(ValueError,'Actor closed'):ExplicitRoles(ws,None,lambda role:None).run('manager',{'question':'illegal reopen'})
        before={str(p.relative_to(ws.public)):sha(p) for p in ws.public.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError,'closed research'):ScientificWorkspace(path,ws.world,reopen=True)
        recovered=ScientificWorkspace(path,ws.world,reopen=True,evaluation_only=True)
        self.assertEqual(before,{str(p.relative_to(ws.public)):sha(p) for p in ws.public.rglob('*') if p.is_file()})
        with self.assertRaisesRegex(ValueError,'Actor closed'):recovered.tool('manager','read_history',{})

    def test_five_roles_actual_sandbox_and_development_evaluation_allow_refutation(self):
        from environment_readiness import sandbox_probe
        if not sandbox_probe(self.root/'sandbox')['ready']:
            self.skipTest('macOS sandbox cannot launch in this session; full tool integration NOT verified')
        ws=ScientificWorkspace(self.root/'full',OfficeWorld('confounding',9137,'office-business-v0.3'))
        models={role:ExplicitPolicy(ws=ws,role=role,verdict_status='refuted') for role in ('manager','analyst','mechanist','verifier','engineer')}
        with sqlite3.connect(self.root/'full.sqlite',check_same_thread=False) as conn:
            roles=role_runtime({'role_runtime':'explicit_v1'},ws,SqliteSaver(conn),lambda role:models[role])
            with patch('langgraph_migration.runtime.create_agent',side_effect=AssertionError('high-level loop forbidden')),patch('langgraph_migration.provider.request_model',side_effect=AssertionError('real API forbidden')):
                output=scientific_flow(roles,roles.saver).invoke({}, {'configurable':{'thread_id':'actual-tools'},'recursion_limit':100})
        self.assertEqual(output['status'],'completed')
        self.assertEqual([t['role'] for t in ws.state['tasks']],['analyst','verifier','mechanist','verifier','engineer'])
        self.assertEqual(ws.state['hypotheses'][0]['status'],'refuted')
        self.assertEqual(output['step']['selected_algorithm_id'],'baseline')
        comparison=ws.state['algorithms'][0]['behavior_comparisons']['baseline']['comparisons']
        self.assertGreater(comparison['forecast_rows']['changed_rows'],0)
        self.assertIn('order_decisions',comparison)
        self.assertIn('没有新增实物盘点',ws.state['experiments'][0]['summary']['scope'])


if __name__=='__main__':unittest.main()
