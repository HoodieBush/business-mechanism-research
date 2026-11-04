"""Decision visibility and factual costs, not LLM/scientific ability checks."""
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from pydantic import Field
from langchain_core.messages import AIMessage,HumanMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph_migration.runtime import FrameworkRoles,role_task_context
from langgraph_migration.provider import APIJournal,append_json
from langgraph_migration.science import scientific_flow
from langgraph_migration.coordination import view
import test_task_dependencies as fixtures


class CostTests(unittest.TestCase):
    def test_summary_and_retry_use_pinned_task_and_reserve_unknown_cost(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_costs_') as directory:
            root=Path(directory);journal=APIJournal(root,{'model':'fixture'},budget=1000000,max_output=100)
            task={'workspace_root':str(root/'C001'),'task_id':'T001','role':'verifier','stage':'validation'}
            token=role_task_context.set(task)
            payload={'model':'fixture','messages':[{'role':'user','content':'fixture'}]}
            def request(config,body):
                if journal.serial==1:return {'request':body,'response':{},'error_type':'transport','error':'RemoteDisconnected'}
                return {'request':body,'response':{'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}}
            try:
                with patch('langgraph_migration.provider.request_model',side_effect=request),patch('langgraph_migration.provider.interruptible_wait'):
                    journal.call('context',payload)
                public=journal.public_view()
            finally:role_task_context.reset(token)
            starts=[json.loads(l) for l in (root/'requests_started.jsonl').read_text().splitlines()]
            self.assertEqual([c['request_index'] for c in journal.calls],[1,2])
            self.assertEqual([c['request'] for c in starts],[payload,payload])
            self.assertTrue(all(c['task']==starts[0]['task'] for c in journal.calls))
            self.assertEqual(public['reported_tokens'],120)
            self.assertEqual(public['current_task']['returned_attempts'],2)
            self.assertEqual(public['current_task']['task']['assigned_role'],'verifier')
            self.assertEqual(public['current_task']['task']['stage'],'validation')
            self.assertGreater(public['unknown_usage_reserve_estimate'],0)
            self.assertEqual(public['remaining_admission_estimate'],1000000-120-public['unknown_usage_reserve_estimate'])
            self.assertNotIn('request',json.dumps(public))
            restored=APIJournal(root,{},budget=1000000,max_output=100)
            self.assertEqual(restored.public_view()['by_model_role'],public['by_model_role'])
    def test_legacy_untraced_and_inflight_attempts_are_not_fabricated_as_task_cost(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_costs_') as directory:
            root=Path(directory)
            append_json(root/'model_calls.jsonl',{'request_index':1,'role':'analyst','response':{'usage':{'total_tokens':80}},'admission_estimate':500})
            append_json(root/'requests_started.jsonl',{'request_index':1,'admission_estimate':500})
            append_json(root/'requests_started.jsonl',{'request_index':2,'admission_estimate':600})
            journal=APIJournal(root,{},budget=1000);public=journal.public_view()
            self.assertEqual(public['reported_tokens'],80);self.assertEqual(public['unknown_usage_reserve_estimate'],600)
            self.assertEqual(public['remaining_admission_estimate'],320);self.assertEqual(public['unattributed_attempts'],1)
            self.assertEqual(public['recent_task_costs'],[]);self.assertEqual(public['current_task']['returned_attempts'],0)


class CoordinatorPolicy(BaseChatModel):
    ws:object=Field(exclude=True)
    old_id:str
    pending_id:str
    hid:str
    @property
    def _llm_type(self):return 'scripted-coordination-visibility'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        if not self.ws.workflow()['finish_allowed']:
            initial=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
            if 'workflow' in initial['task'] or 'workflow' in initial['context']:raise AssertionError('supervisor still receives global pipeline assignment')
            menu=initial['context']['coordination']
            if menu['available_tasks']['algorithm'][0]['evidence_packet_ids']!=[self.old_id]:raise AssertionError('follow-up packet became hypothesis dependency')
            if menu['packets'][-1]['packet_id']!=self.pending_id:raise AssertionError('pending work disappeared')
            if messages[-1].type!='system' or 'coordination' not in messages[-1].content or 'needs_review' in messages[-1].content:raise AssertionError('manager duty still uses worker stage')
            action=('schedule_task',{'role':'engineer','stage':'algorithm','packet_id':self.old_id,'hypothesis_ids':[self.hid],
                'question':'scripted available branch','rationale':'scripted dependency choice'})
        # This test mocks the engineering worker, so it has no real engineering
        # delivery. Match the existing explicit inconclusive-close contract.
        else:action=('finish_research',{'selected_algorithm_id':'baseline','outcome':'inconclusive','summary':'scripted ready choice','limitations':['fixture, no scientific or profit claim']})
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[
            {'name':action[0],'args':action[1],'id':self.ws.state['workflow']['phase'],'type':'tool_call'}]))])


class CoordinationTests(unittest.TestCase):
    code=fixtures.ScopedDependencyTests.code
    setUp=fixtures.ScopedDependencyTests.setUp
    tearDown=fixtures.ScopedDependencyTests.tearDown
    publish=fixtures.ScopedDependencyTests.publish
    review=fixtures.ScopedDependencyTests.review
    hypothesis=fixtures.ScopedDependencyTests.hypothesis
    def test_followup_topic_is_not_an_evidence_dependency_and_worker_stage_stays_pinned(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        pending=self.publish(self.code.replace('SUM(sales) units','COUNT(*) observations'))
        ws.state['information_jobs'][pending]['hypothesis_ids']=[hid]
        board=view(ws)
        self.assertEqual(board['available_tasks']['algorithm'][0]['evidence_packet_ids'],[old])
        self.assertEqual(board['packets'][-1]['followup_hypothesis_ids'],[hid])
        worker=ws.capture_task('verifier',{'id':'review','execution_phase':'needs_review','inputs':[pending]},ws.task_binding({'inputs':[pending]}))
        self.assertEqual(worker['phase_contract']['phase'],'needs_review')
        manager=ws.capture_task('manager',{'id':'manager','workflow':ws.workflow(),'inputs':[pending]},ws.task_binding({'inputs':[pending]}))
        self.assertEqual(manager['phase_contract']['phase'],'coordination');self.assertEqual(manager['workflow']['hypothesis_ids'],[])
    def test_native_manager_view_preserves_choices_and_pending_work_without_global_assignment(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        pending=self.publish(self.code.replace('SUM(sales) units','COUNT(*) observations'))
        manager=CoordinatorPolicy(ws=ws,old_id=old,pending_id=pending,hid=hid)
        engineer=fixtures.BranchPolicy(ws=ws,role='engineer',accepted_id=old,hypothesis_id=hid)
        models={'manager':manager,'engineer':engineer}
        roles=FrameworkRoles(ws,self.saver,lambda role:models.get(role,manager))
        out=scientific_flow(roles,self.saver).invoke({}, {'configurable':{'thread_id':'native-coordinator-view'},'recursion_limit':100})
        self.assertEqual(out['status'],'completed');self.assertEqual(out['step']['remaining_information_jobs'][0]['packet_id'],pending)
        self.assertEqual(ws.state['hypotheses'][0]['status'],'unresolved')
    def test_live_cost_reader_changes_without_changing_input_binding(self):
        ws=self.ws;values={'reported_tokens':10};ws.resource_reader=lambda:dict(values)
        task={'id':'manager','inputs':ws.state['base_source_paths']};before=ws.task_binding(task)
        self.assertEqual(view(ws)['research_costs']['reported_tokens'],10)
        values['reported_tokens']=90
        self.assertEqual(view(ws)['research_costs']['reported_tokens'],90)
        self.assertEqual(ws.task_binding(task),before)
    def test_provided_code_uses_same_review_policy_in_dispatch_and_task_capture(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        ws.state['hypotheses'][0]['evidence_files'].append(str(ws.public/'baseline.py'))
        item=ws.tool('manager','schedule_task',{'role':'engineer','stage':'algorithm','packet_id':old,
            'hypothesis_ids':[hid],'question':'fixture compare provided algorithm','rationale':'fixture original code is not derived measurement'})
        snapshot=ws.capture_task('engineer',item,ws.task_binding(item))
        self.assertEqual(list(snapshot['input_reviews']),[old])
        token=role_task_context.set(snapshot)
        try:ws.validate_task_inputs()
        finally:role_task_context.reset(token)
        self.assertIn(str(ws.public/'baseline.py'),snapshot['input_versions'])
        ws.tool('manager','schedule_task',{'role':'engineer','stage':'algorithm','packet_id':old,
            'hypothesis_ids':[hid],'inputs':[ws.reference(ws.public/'baseline.py')],
            'question':'fixture explicit provided reference','rationale':'same original-source policy'})
        derived=ws.shared/'baseline.py';derived.write_text('units\n1\n')
        self.assertTrue(ws.requires_independent_review(derived))
        with self.assertRaisesRegex(ValueError,'independent review'):ws.require_reviewed([str(derived)])
    def test_received_native_task_continues_without_reasking_manager_or_accepting_new_draft(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        ws.state['hypotheses'][0]['evidence_files'].append(str(ws.public/'baseline.py'))
        pending=self.publish(self.code.replace('SUM(sales) units','COUNT(*) observations'))
        item=ws.tool('manager','schedule_task',{'role':'engineer','stage':'algorithm','packet_id':old,
            'hypothesis_ids':[hid],'question':'existing received task','rationale':'continue actual recorded choice'})
        manager=CoordinatorPolicy(ws=ws,old_id=old,pending_id=pending,hid=hid)
        engineer=fixtures.BranchPolicy(ws=ws,role='engineer',accepted_id=old,hypothesis_id=hid)
        roles=FrameworkRoles(ws,self.saver,lambda role:engineer if role=='engineer' else manager)
        graph=scientific_flow(roles,self.saver,resume_task_id=item['id'])
        out=graph.invoke({}, {'configurable':{'thread_id':'resume-received-task'},'recursion_limit':100})
        self.assertEqual(out['status'],'completed');self.assertEqual(len(ws.state['tasks']),1)
        self.assertEqual([t['role'] for t in ws.state['tasks']],['engineer'])
        self.assertEqual(out['step']['remaining_information_jobs'][0]['packet_id'],pending)
        self.assertIsNone(ws.packets.current_review(ws.packets.validate(pending)))
        with self.assertRaisesRegex(ValueError,'actual received'):
            scientific_flow(roles,self.saver,resume_task_id='missing').invoke({}, {'configurable':{'thread_id':'missing-received-task'}})


if __name__=='__main__':unittest.main()
