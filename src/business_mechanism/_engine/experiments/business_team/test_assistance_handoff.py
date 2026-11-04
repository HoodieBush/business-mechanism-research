"""Capability honesty and native assistance routing; no scientific answer gate."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from world import OfficeWorld
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.science import ScientificWorkspace,scientific_flow
from langgraph_migration.coordination import view
from pydantic import Field


class SupportModel(BaseChatModel):
    prompts:list=Field(default_factory=list)
    @property
    def _llm_type(self):return 'scripted-assistance-contract'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        self.prompts.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[{
            'name':'request_assistance','args':{'reason':'opaque task requires unavailable computation',
            'needed_work':'compute an independently reproducible statistic from original data',
            'requested_capabilities':['python_execution']},'id':'support','type':'tool_call'}]))])


class AssistanceTests(unittest.TestCase):
    def test_native_handoff_preserves_task_and_returns_to_real_supervisor_choices(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_support_') as folder:
            root=Path(folder);ws=ScientificWorkspace(root/'C001',OfficeWorld('confounding',8421,'office-business-v0.3'))
            original={'id':'T001','kind':'scheduled_task','role':'mechanist','question':'opaque scientific question requiring computation',
                      'inputs':sorted(ws.registered_sources),'execution_phase':'needs_hypotheses','hypothesis_ids':[]}
            ws.state['tasks'].append(original);ws.persist();model=SupportModel()
            with sqlite3.connect(root/'checkpoints.sqlite',check_same_thread=False) as connection:
                saver=SqliteSaver(connection);roles=FrameworkRoles(ws,saver,lambda role:model)
                graph=scientific_flow(roles,saver,resume_task_id='T001');conf={'configurable':{'thread_id':'C001:science'}}
                result=graph.invoke({},conf,interrupt_after=['work'])
                self.assertEqual(result['last_result']['kind'],'assistance_requested')
                self.assertEqual(graph.get_state(conf).next,('supervise',))
            request=ws.state['support_requests'][0]
            self.assertEqual(request['original_task'],original)
            self.assertEqual(request['task_id'],'T001')
            self.assertEqual(ws.state['workflow']['phase'],'needs_research_decision')
            self.assertEqual(ws.state['hypotheses'],[])
            self.assertEqual(ws.state['algorithms'],[])
            self.assertEqual(ws.state['results'],[])
            choices=view(ws);self.assertEqual(choices['support_requests'],[request]);self.assertIn('analyst',choices['allowed_roles'])
            prompts='\n'.join(m.content for m in model.prompts[0] if m.type=='system')
            self.assertIn('"python_execution": false',prompts)
            self.assertNotIn('Python执行环境：',prompts)
            self.assertNotIn('标准pandas可用',prompts)
            # The request does not dispatch on behalf of the supervisor.
            self.assertEqual(len(ws.state['tasks']),1)
            task=ws.tool('manager','schedule_task',{'role':'analyst','stage':'analysis','question':'compute requested statistic',
                'inputs':sorted(ws.registered_sources),'rationale':'actual missing capability','evidence_gap':'pending support request'})
            self.assertEqual(task['role'],'analyst')
            self.assertEqual(ws.state['hypotheses'],[])

    def test_professional_role_and_stage_menus_advertise_real_assistance_exit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_support_roles_') as folder:
            ws=ScientificWorkspace(Path(folder)/'C001',OfficeWorld('confounding',8421,'office-business-v0.3'))
            FrameworkRoles(ws,None,lambda role:None)
            for role in ('analyst','mechanist','verifier','engineer'):
                self.assertIn('request_assistance',ws.framework_role_tools[role])
                item=ws._tool(role,'request_assistance',{'reason':'unavailable evidence','needed_work':'independent collection','requested_capabilities':['new_observations']})
                self.assertEqual(item['request']['requester_role'],role)
                self.assertEqual(item['request']['status'],'pending_supervisor_decision')
            self.assertNotIn('request_assistance',ws.framework_role_tools['manager'])
            self.assertEqual(ws.state['hypotheses'],[])


if __name__=='__main__':unittest.main()
