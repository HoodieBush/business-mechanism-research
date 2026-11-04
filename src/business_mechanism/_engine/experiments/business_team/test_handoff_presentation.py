"""Message/state engineering checks, zero paid models or science certificates."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import ToolMessage
from langgraph_migration.handoff import CANDIDATE, LEGACY, control_contract, handoff_message
from langgraph_migration.runtime import FrameworkRoles, TaskInputChangedError
from langgraph_migration.science import ScientificWorkspace
from run_information_protocol import InformationWorkspace
from run_langgraph_migration import reopen_workspace
from world import OfficeWorld
from test_tool_outputs import ObservedScriptedModel
from test_langgraph_migration import submission
import test_gateway_protocol as gateway_checks
import test_langgraph_science as science_checks


def frames(messages):
    result=[]
    for message in messages:
        if message.type!='human' or not isinstance(message.content,str):continue
        try:value=json.loads(message.content)
        except ValueError:continue
        if isinstance(value,dict) and value.get('message_kind')=='research_handoff':result.append(value)
    return result


def system_text(messages):
    return '\n'.join(m.content for m in messages if m.type=='system' and isinstance(m.content,str))


class SubjectWorkspace(InformationWorkspace):
    def capture_task(self,role,task,binding):
        return {'task_id':task.get('id'),'role':role,'workspace_root':str(self.root),
                'stage':'engineering_fixture','phase_contract':deepcopy(self.fixture_contract)}


class HandoffPresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_handoff_')
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def workspace(self):
        ws=SubjectWorkspace(self.root/'case',{'domain':'orders','construction':'count'})
        ws.fixture_contract={'phase':'engineering_fixture','objective':'retain original research identity',
            'evaluation_subject':{'claim':'opaque upstream empirical claim, not an established fact',
                                  'program_ids':['amber','violet'],'version':'fixture1'},
            'prediction_subjects':[{'hypothesis_id':'opaque_h','scope':'given17-day conditional population',
                                    'prediction':'opaque conditional prediction'}]}
        ws.handoff_presentation=CANDIDATE
        (ws.root/'role_prompts.json').write_text(json.dumps(ws.role_prompts))
        return ws

    def test_view_lifts_exact_subject_without_mutating_backend_or_givens(self):
        ws=self.workspace();original=deepcopy(ws.fixture_contract)
        control=control_contract(original,CANDIDATE)
        message=handoff_message({'task_id':'f','question':'Given model support9..30, answer conditional guarantee.'},
                                {'phase_contract':original})
        value=json.loads(message.content)
        self.assertEqual(value['registered_subjects']['evaluation_subject'],original['evaluation_subject'])
        self.assertEqual(value['registered_subjects']['prediction_subjects'],original['prediction_subjects'])
        self.assertNotIn('evaluation_subject',control)
        self.assertEqual(control['objective'],original['objective'])
        self.assertEqual(original,ws.fixture_contract)
        self.assertIn('support9..30',value['received_request']['question'])
        self.assertEqual(control_contract(original,LEGACY),original)

    def test_real_gateway_wire_places_original_request_in_human_not_system(self):
        from langgraph_migration.provider import GatewayChatModel
        ws=self.workspace();question='opaque upstream claim and given scope: keep exact "quotes" and\nnewlines.'
        journal=gateway_checks.JournalFixture([gateway_checks.submit()])
        with sqlite3.connect(self.root/'wire.sqlite',check_same_thread=False) as connection:
            roles=FrameworkRoles(ws,SqliteSaver(connection),lambda role:GatewayChatModel(journal=journal,research_role=role))
            roles.run('verifier',{'id':'wire','question':question})
            saved=next(roles.saver.list(None)).checkpoint['channel_values']
        wire=journal.payloads[0]['messages']
        data=[json.loads(m['content']) for m in wire if m['role']=='user' and m['content'].startswith('{')]
        payload=next(v for v in data if v.get('message_kind')=='research_handoff')
        self.assertEqual(payload['received_request'],{'task_id':'wire','question':question})
        self.assertEqual(payload['registered_subjects']['evaluation_subject'],ws.fixture_contract['evaluation_subject'])
        self.assertFalse(any(question in m['content'] for m in wire if m['role']=='system'))
        self.assertEqual(frames(saved['messages']),[])  # presentation never grows the checkpoint history
        self.assertEqual(saved['handoff_presentation'],CANDIDATE)

    def test_compaction_reinjects_original_subject_and_question_without_new_authority(self):
        ws=self.workspace();original=ws._tool
        ws._tool=lambda role,name,args: {'large_fixture':'record '*12000} if name=='read_context' else original(role,name,args)
        index=ws.workers['verifier'].directory/'framework_receipts/index.json'
        read=('read_artifact',{'path':str(index)})
        model=ObservedScriptedModel(sequence=[('read_context',{}),read,read,
            'An inaccurate summary suggests a different objective.',read,submission()])
        question='Exact17-day conditional objective remains after compaction.'
        with sqlite3.connect(self.root/'compact.sqlite',check_same_thread=False) as connection:
            roles=FrameworkRoles(ws,SqliteSaver(connection),lambda role:model)
            roles.run('verifier',{'id':'compact','question':question})
            final=frames(model.prompts[-1])
            self.assertEqual(len(final),1)
            self.assertEqual(final[0]['received_request']['question'],question)
            self.assertEqual(final[0]['registered_subjects']['prediction_subjects'],ws.fixture_contract['prediction_subjects'])
            self.assertNotIn(question,system_text(model.prompts[-1]))
            self.assertEqual(frames(next(roles.saver.list(None)).checkpoint['channel_values']['messages']),[])
        summaries=[p for p in model.prompts if len(p)==1 and p[0].type=='human']
        self.assertEqual(len(summaries),1)

    def test_gateway_serialized_summary_preserves_original_handoff(self):
        from langgraph_migration.provider import GatewayChatModel
        ws=self.workspace();original=ws._tool
        ws._tool=lambda role,name,args: {'large_fixture':'record '*12000} if name=='read_context' else original(role,name,args)
        index=ws.workers['verifier'].directory/'framework_receipts/index.json'
        actions=iter([('read_context',{}),('read_artifact',{'path':str(index)}),
                      ('read_artifact',{'path':str(index)}),submission()])
        root=self.root
        class Journal:
            config={'model':'fixture','context_summary_layout':'serialized'}
            max_output=7000
            def __init__(self):self.root=root;self.calls=[]
            def call(self,role,payload):
                if role=='context':
                    message={'content':'Observed original tool evidence remains archived. The research object is unresolved until actual delivery. No additional scientific result established.'}
                    finish='stop'
                else:
                    name,args=next(actions)
                    message=gateway_checks.response(gateway_checks.call(name,args,'call_'+str(len(self.calls))))
                    finish='tool_calls'
                record={'request_index':len(self.calls)+1,'role':role,'task':None,'request':payload,
                    'response':{'usage':{'prompt_tokens':12000,'completion_tokens':30,'total_tokens':12030},
                                'choices':[{'finish_reason':finish,'message':message}]}}
                self.calls.append(record);return record
        journal=Journal();question='Original conditional objective survives real Gateway summary wiring.'
        with sqlite3.connect(self.root/'gateway_summary.sqlite',check_same_thread=False) as connection:
            roles=FrameworkRoles(ws,SqliteSaver(connection),lambda role:GatewayChatModel(journal=journal,research_role=role))
            result=roles.run('verifier',{'id':'gateway_summary','question':question})
        self.assertEqual(result['role'],'verifier')
        summaries=[r for r in journal.calls if r['role']=='context'];self.assertEqual(len(summaries),1)
        last=next(r for r in reversed(journal.calls) if r['role']=='verifier')['request']['messages']
        data=[json.loads(m['content']) for m in last if m['role']=='user' and m['content'].startswith('{')]
        frame=next(d for d in data if d.get('message_kind')=='research_handoff')
        self.assertEqual(frame['received_request']['question'],question)
        self.assertEqual(frame['registered_subjects']['evaluation_subject'],ws.fixture_contract['evaluation_subject'])
        self.assertFalse(any(question in m['content'] for m in last if m['role']=='system'))
        events=[json.loads(line) for line in (self.root/'summary_events.jsonl').read_text().splitlines()]
        self.assertEqual(events[-1]['event'],'accepted')

    def test_restart_uses_pinned_subject_and_does_not_reexecute_successful_tool(self):
        ws=self.workspace();task={'id':'resume','question':'Preserve exact scope, not an upstream conclusion.'}
        connection=sqlite3.connect(self.root/'resume.sqlite',check_same_thread=False)
        try:
            first=ObservedScriptedModel(sequence=[('read_context',{})])
            with self.assertRaisesRegex(AssertionError,'unexpected model call'):
                FrameworkRoles(ws,SqliteSaver(connection),lambda role:first).run('verifier',task)
            connection.close();connection=sqlite3.connect(self.root/'resume.sqlite',check_same_thread=False)
            reopened=reopen_workspace(ws.root)
            with self.assertRaisesRegex(TaskInputChangedError,'workspace handoff'):
                FrameworkRoles(reopened,SqliteSaver(connection),lambda role:ObservedScriptedModel(sequence=[]))
            reopened.handoff_presentation=CANDIDATE
            resumed=ObservedScriptedModel(sequence=[submission()])
            roles=FrameworkRoles(reopened,SqliteSaver(connection),lambda role:resumed)
            roles.run('verifier',task)
            self.assertEqual(frames(resumed.prompts[0])[0]['registered_subjects']['evaluation_subject'],ws.fixture_contract['evaluation_subject'])
            self.assertEqual(resumed.calls,1)
            done=ObservedScriptedModel(sequence=[])
            FrameworkRoles(reopened,SqliteSaver(connection),lambda role:done).run('verifier',task)
            self.assertEqual(done.calls,0)
            actions=[json.loads(x)['tool'] for x in (ws.root/'framework_tools.jsonl').read_text().splitlines()]
            self.assertEqual(actions,['read_context','submit_result'])
        finally:connection.close()

    def test_mode_is_bound_and_different_task_does_not_inherit_previous_subject(self):
        ws=self.workspace()
        with sqlite3.connect(self.root/'identity.sqlite',check_same_thread=False) as connection:
            saver=SqliteSaver(connection);first=ObservedScriptedModel(sequence=[submission()])
            roles=FrameworkRoles(ws,saver,lambda role:first)
            task={'id':'identity','question':'one original objective'}
            roles.run('verifier',task)
            self.assertEqual(frames(first.prompts[0])[0]['received_request']['question'],task['question'])
            ws.handoff_presentation=LEGACY
            with self.assertRaisesRegex(TaskInputChangedError,'presentation changed'):roles.run('verifier',task)
            with self.assertRaisesRegex(TaskInputChangedError,'workspace handoff'):
                FrameworkRoles(ws,saver,lambda role:ObservedScriptedModel(sequence=[]))
            ws.handoff_presentation=CANDIDATE
            ws.fixture_contract={'phase':'another','prediction_subjects':[{'prediction':'copper-only new subject'}]}
            other=ObservedScriptedModel(sequence=[submission()])
            FrameworkRoles(ws,saver,lambda role:other).run('verifier',{'id':'other','question':'second original objective'})
            text=json.dumps(frames(other.prompts[0]),ensure_ascii=False)
            self.assertIn('copper-only',text);self.assertNotIn('opaque upstream',text)

    def test_unknown_mode_fails_before_model(self):
        ws=self.workspace();ws.handoff_presentation='unregistered_mode'
        model=ObservedScriptedModel(sequence=[])
        with sqlite3.connect(self.root/'invalid.sqlite',check_same_thread=False) as connection:
            with self.assertRaisesRegex(ValueError,'Unknown handoff'):
                FrameworkRoles(ws,SqliteSaver(connection),lambda role:model)
        self.assertEqual(model.calls,0)

    def test_scientific_subject_lift_preserves_native_permissions_and_backend_snapshot(self):
        for mode in (LEGACY,CANDIDATE):
            with self.subTest(mode=mode):
                ws=ScientificWorkspace(self.root/mode,OfficeWorld('relationship',7801))
                ws.handoff_presentation=mode
                claim='OPAQUE empirical no-control claim, requires evidence, not truth.'
                subject={'type':'program_evaluation','claim':claim,'program_ids':['baseline'],'code_versions':{'baseline':'opaque_fixture_version'}}
                ws.state['workflow'].update(phase='needs_evaluation_review',evaluation_subject=subject)
                ws.persist()
                # Verifier is never allowed to create a mechanist hypothesis,
                # even when the received request asks to do so.
                model=ObservedScriptedModel(sequence=[('save_hypothesis',{}),
                    ('request_assistance',{'reason':'engineering-only fixture','needed_work':'fixture complete',
                                           'requested_capabilities':['fixture']})])
                with sqlite3.connect(self.root/(mode+'.sqlite'),check_same_thread=False) as connection:
                    roles=FrameworkRoles(ws,SqliteSaver(connection),lambda role:model)
                    roles.run('verifier',{'id':'science','question':'OPAQUE request: inspect this claim; keep given business parameters.'})
                    state=next(roles.saver.list(None)).checkpoint['channel_values']
                    self.assertEqual(state['task_snapshot']['phase_contract']['evaluation_subject'],subject)
                self.assertEqual(ws.state['hypotheses'],[])
                errors=[m for m in model.prompts[-1] if isinstance(m,ToolMessage) and m.status=='error']
                self.assertTrue(errors)
                if mode==CANDIDATE:
                    self.assertNotIn(claim,system_text(model.prompts[0]))
                    self.assertEqual(frames(model.prompts[0])[0]['registered_subjects']['evaluation_subject'],subject)
                    self.assertIn('needs_evaluation_review',system_text(model.prompts[0]))
                else:self.assertIn(claim,system_text(model.prompts[0]))

    def test_existing_native_five_role_path_runs_under_optional_presentation(self):
        name='test_04_native_five_role_path_and_actual_original_access'
        check=science_checks.ScienceTests(methodName=name)
        check.root=self.root/'five_role'
        with sqlite3.connect(self.root/'five_role.sqlite',check_same_thread=False) as connection:
            check.saver=SqliteSaver(connection)
            original=science_checks.ScientificWorkspace
            def opted_workspace(*args,**kwargs):
                workspace=original(*args,**kwargs)
                workspace.handoff_presentation=CANDIDATE
                return workspace
            with patch.object(science_checks,'ScientificWorkspace',side_effect=opted_workspace):
                getattr(check,name)()


if __name__=='__main__':unittest.main()
