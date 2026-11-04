"""Readiness regression: unrelated draft must not block accepted evidence.

Semantic reviews below are scripted fixtures, not LLM scientific evidence.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.runtime import FrameworkRoles,role_task_context,TaskInputChangedError
from langgraph_migration.science import ScientificWorkspace,scientific_flow
from test_langgraph_migration import checks
from world import OfficeWorld


class DependencyTests(unittest.TestCase):
    def test_ready_engineering_uses_accepted_packet_while_other_packet_waits_review(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_dependency_') as directory:
            root=Path(directory);ws=ScientificWorkspace(root/'D001',OfficeWorld('relationship',7400))
            con=sqlite3.connect(root/'checkpoints.sqlite',check_same_thread=False)
            try:
                FrameworkRoles(ws,SqliteSaver(con),lambda role:None)
                code="import os,sqlite3,pandas as pd\nc=sqlite3.connect(os.environ['PUBLIC_DIR']+'/business.sqlite');f=pd.read_sql_query('SELECT sku,SUM(sales) units FROM hourly GROUP BY sku',c);f.to_csv('units.csv',index=False)"
                run=ws.tool('analyst','run_python',{'code':code,'purpose':'fixture known data','output_semantics':'recorded units per SKU'})
                pub=ws.tool('analyst','publish_analysis',{'primary_artifact':run['data_outputs'][0],'summary':'fixture','findings':[],'next_step':'review'})
                accepted_id=pub['packet_id'];ws.state['workflow'].update(phase='needs_review',latest_packet=accepted_id)
                packet=ws.tool('verifier','read_packet',{'packet_id':accepted_id})
                independent=ws.tool('verifier','run_python',{'code':code,'purpose':'independent fixture read','output_semantics':'recorded units per SKU'})
                ws.tool('verifier','review_artifact',{'artifact_id':packet['artifact_id'],'execution_id':independent['execution_id'],
                    'decision':'accepted','checks':checks('accepted'),'summary':'scripted semantics, no research claim'})
                ws.state['workflow']['phase']='needs_hypotheses'
                h=ws.tool('mechanist','save_hypothesis',{'explanation':'fixture uncertainty','scope':'received aggregate','alternatives':['fixture alternative'],
                    'prediction':'scope-limited fixture','falsification':'fixture counterexample','evidence_files':[packet['artifact']['path']],
                    'change_reason':'fixture','parent_id':None})
                ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=[h['id']])
                ws.tool('verifier','record_verdict',{'hypothesis_id':h['id'],'status':'unresolved','rationale':'scripted uncertainty',
                    'evidence_files':[str(ws.public/'history.csv')]})
                ws.state['research_progress'][h['id']]='validated'
                ws.state['workflow']['phase']='needs_analysis'
                other=ws.tool('analyst','run_python',{'code':code.replace('SUM(sales) units','COUNT(*) observations'),
                    'purpose':'separate draft','output_semantics':'observations per SKU, separate from accepted aggregate'})
                draft=ws.tool('analyst','publish_analysis',{'primary_artifact':other['data_outputs'][0],'summary':'separate pending draft','findings':[],'next_step':'review'})
                ws.state['workflow'].update(phase='needs_review',latest_packet=draft['packet_id']);ws.persist()
                self.assertIsNotNone(ws.packets.current_review(ws.packets.validate(accepted_id)))
                self.assertIsNone(ws.packets.current_review(ws.packets.validate(draft['packet_id'])))
                self.assertIn('engineer',ws.workflow()['allowed_roles'])
                task=ws.tool('manager','schedule_task',{'role':'engineer','stage':'algorithm','packet_id':accepted_id,
                    'inputs':[accepted_id],'hypothesis_ids':[h['id']],'question':'evaluate using accepted evidence',
                    'rationale':'unrelated pending draft is not a dependency'})
                snapshot=ws.capture_task('engineer',task,ws.task_binding(task))
                self.assertEqual(snapshot['workflow']['latest_packet'],accepted_id)
                self.assertEqual(snapshot['phase_contract']['phase'],'needs_algorithm')
                self.assertIsNone(ws.packets.current_review(ws.packets.validate(draft['packet_id'])))
            finally:con.close()


class BranchPolicy(BaseChatModel):
    ws:object=Field(exclude=True)
    role:str
    accepted_id:str
    hypothesis_id:str
    calls:int=0
    @property
    def _llm_type(self):return 'scripted-dependency-branch-test'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        self.calls+=1
        if self.role=='manager':
            if self.ws.state.get('engineering_selection'):
                action=('finish_research',{'selected_algorithm_id':'baseline','summary':'fixture choice with pending work disclosed',
                    'limitations':['scripted scheduling, no LLM discovery or profit claim']})
            else:
                action=('schedule_task',{'role':'engineer','stage':'algorithm','packet_id':self.accepted_id,
                    'hypothesis_ids':[self.hypothesis_id],'question':'fixture independent ready branch','rationale':'pending draft is a different dependency'})
        elif self.role=='engineer':
            bound=role_task_context.get()
            if bound['workflow']['latest_packet']!=self.accepted_id or bound['phase_contract']['phase']!='needs_algorithm':
                raise AssertionError('native professional lost its selected evidence/stage')
            action=('finish_algorithm',{'selected_algorithm_id':'baseline','summary':'fixture chooses unchanged baseline',
                'limitations':['engineering fixture, no evaluated improvement']})
        else:raise AssertionError('unrelated pending review must not be invoked by this scripted branch')
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[
            {'name':action[0],'args':action[1],'id':self.role+str(self.calls),'type':'tool_call'}]))])


class ScopedDependencyTests(unittest.TestCase):
    code="import os,sqlite3,pandas as pd\nc=sqlite3.connect(os.environ['PUBLIC_DIR']+'/business.sqlite');pd.read_sql_query('SELECT sku,SUM(sales) units FROM hourly GROUP BY sku',c).to_csv('units.csv',index=False)"
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_scoped_dependencies_')
        self.root=Path(self.temp.name);self.ws=ScientificWorkspace(self.root/'D001',OfficeWorld('relationship',7400))
        self.con=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.con)
        FrameworkRoles(self.ws,self.saver,lambda role:None)
    def tearDown(self):self.con.close();self.temp.cleanup()
    def publish(self,code=None):
        ws=self.ws;ws.state['workflow']['phase']='needs_analysis'
        run=ws.tool('analyst','run_python',{'code':code or self.code,'purpose':'fixture aggregate','output_semantics':'fixture recorded units per SKU'})
        self.assertTrue(run['ok'])
        result=ws.tool('analyst','publish_analysis',{'primary_artifact':run['data_outputs'][0],'summary':'scripted data fixture','findings':[],'next_step':'independent fixture review'})
        ws.state['workflow'].update(phase='needs_review',latest_packet=result['packet_id']);ws.persist()
        return result['packet_id']
    def review(self,pid,decision='accepted'):
        ws=self.ws
        packet=ws.packets.view(pid,'verifier')
        run=ws.tool('verifier','run_python',{'code':self.code,'purpose':'fixture independent original read','output_semantics':'recorded units per SKU'})
        return ws.tool('verifier','review_artifact',{'artifact_id':packet['artifact_id'],'execution_id':run['execution_id'],
            'decision':decision,'checks':checks(decision),'summary':'scripted information review, no science claim'})
    def hypothesis(self,pid):
        ws=self.ws;ws.state['workflow'].update(phase='needs_hypotheses',revision_required=False)
        h=ws.tool('mechanist','save_hypothesis',{'explanation':'fixture decision uncertainty','scope':'fixture accepted aggregate',
            'alternatives':['fixture competitor'],'prediction':'fixture scoped prediction','falsification':'fixture counterexample',
            'evidence_files':[ws.packets.validate(pid)['artifact']['path']],'change_reason':'fixture','parent_id':None})
        ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=[h['id']])
        ws.tool('verifier','record_verdict',{'hypothesis_id':h['id'],'status':'unresolved','rationale':'scripted uncertainty',
            'evidence_files':[str(ws.public/'history.csv')]})
        ws.state['research_progress'][h['id']]='validated'
        return h['id']
    def task(self,role,**kwargs):
        return self.ws.tool('manager','schedule_task',{'role':role,'question':'fixture scoped task','rationale':'fixture dependency',**kwargs})
    def test_unreviewed_target_and_wrong_stage_cannot_borrow_old_acceptance(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        draft=self.publish(self.code.replace('SUM(sales) units','COUNT(*) observations'))
        with self.assertRaisesRegex(ValueError,'accepted independent review'):
            self.task('engineer',stage='algorithm',packet_id=draft,hypothesis_ids=[hid])
        with self.assertRaisesRegex(ValueError,'stage duties'):
            self.task('engineer',stage='information_review',packet_id=old,hypothesis_ids=[hid])
        artifact=ws.reference(ws.packets.validate(old)['artifact']['path'])
        item=self.task('engineer',stage='algorithm',inputs=[artifact],hypothesis_ids=[hid])
        self.assertEqual(item['packet_id'],old);self.assertEqual(item['inputs'],[old])
        self.assertIsNone(ws.packets.current_review(ws.packets.validate(draft)))
    def test_review_finishes_selected_packet_and_retains_other_pending_job(self):
        ws=self.ws;first=self.publish();other=self.publish(self.code.replace('SUM(sales) units','COUNT(*) observations'))
        item=self.task('verifier',stage='information_review',packet_id=first)
        snapshot=ws.capture_task('verifier',item,ws.task_binding(item));token=role_task_context.set(snapshot)
        try:
            run=ws.tool('verifier','run_python',{'code':self.code,'purpose':'independent fixture read','output_semantics':'recorded units per SKU'})
            with self.assertRaisesRegex(ValueError,'selected task packet'):
                ws.tool('verifier','review_artifact',{'artifact_id':ws.reference(ws.packets.validate(other)['artifact']['path']),
                    'execution_id':run['execution_id'],'decision':'accepted','checks':checks('accepted'),'summary':'wrong task target'})
            review=ws.tool('verifier','review_artifact',{'artifact_id':ws.reference(ws.packets.validate(first)['artifact']['path']),
                'execution_id':run['execution_id'],'decision':'accepted','checks':checks('accepted'),'summary':'scripted accepted first'})
            result=ws.tool('verifier','finish_review',{'review_id':review['id'],'summary':'finish first only'})
        finally:role_task_context.reset(token)
        self.assertEqual(result['packet_id'],first)
        self.assertEqual(ws.state['workflow']['latest_packet'],other)
        self.assertIsNone(ws.packets.current_review(ws.packets.validate(other)))
        jobs={p['packet_id']:p for p in ws.workflow()['dependencies']['packets']}
        self.assertEqual(jobs[first]['status'],'accepted');self.assertEqual(jobs[other]['status'],'pending_review')
        self.assertTrue(jobs[other]['active_followup'])
    def test_native_branch_finishes_with_pending_job_disclosed_and_resumes_without_repeat(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        pending=self.publish(self.code.replace('SUM(sales) units','COUNT(*) observations'))
        models={role:BranchPolicy(ws=ws,role=role,accepted_id=old,hypothesis_id=hid)
            for role in ('manager','engineer','verifier','context','analyst','mechanist')}
        roles=FrameworkRoles(ws,self.saver,lambda role:models[role]);graph=scientific_flow(roles,self.saver)
        conf={'configurable':{'thread_id':'native-scoped-branch'},'recursion_limit':100}
        out=graph.invoke({},conf)
        self.assertEqual(out['status'],'completed');self.assertEqual(ws.state['research_progress'][hid],'evaluated')
        self.assertEqual(ws.state['hypotheses'][0]['status'],'unresolved')
        self.assertEqual(ws.state['workflow']['latest_packet'],pending)
        self.assertEqual([p['packet_id'] for p in out['step']['remaining_information_jobs']],[pending])
        self.assertIsNone(ws.packets.current_review(ws.packets.validate(pending)))
        calls=sum(m.calls for m in models.values());graph.invoke(None,conf)
        self.assertEqual(sum(m.calls for m in models.values()),calls)
        self.assertEqual([t['role'] for t in ws.state['tasks']],['engineer'])
    def test_changed_acceptance_aborts_bound_task_instead_of_silently_reusing_it(self):
        ws=self.ws;old=self.publish();self.review(old);hid=self.hypothesis(old)
        item=self.task('engineer',stage='algorithm',packet_id=old,hypothesis_ids=[hid])
        snapshot=ws.capture_task('engineer',item,ws.task_binding(item))
        ws.state['workflow'].update(phase='needs_review',latest_packet=old)
        self.review(old,'rejected')
        token=role_task_context.set(snapshot)
        try:
            with self.assertRaisesRegex(TaskInputChangedError,'information review changed'):
                ws.tool('engineer','read_context',{})
        finally:role_task_context.reset(token)


if __name__=='__main__':unittest.main()
