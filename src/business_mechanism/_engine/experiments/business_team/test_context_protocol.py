"""Native usage interoperability and actionable task visibility; zero paid calls."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.context_policy import context_middleware
from langgraph_migration.provider import GatewayChatModel
from langgraph_migration.coordination import view
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.science import ScientificWorkspace
from test_tool_outputs import ObservedScriptedModel
from world import OfficeWorld
from scenario_contract import VERSION


class JournalFixture:
    config={'model':'fixture'}
    max_output=7000
    def __init__(self,usage):self.usage=usage;self.requests=[]
    def call(self,role,payload):
        self.requests.append((role,payload))
        return {'request_index':len(self.requests),'response':{'usage':self.usage,'choices':[{'message':{'content':'fixture summary'}}]}}


class ContextProtocolTests(unittest.TestCase):
    def test_native_usage_metadata_and_context_output_window_keep_shared_journal(self):
        journal=JournalFixture({'prompt_tokens':11,'completion_tokens':4,'total_tokens':15})
        role=GatewayChatModel(journal=journal,research_role='verifier')
        message=role.invoke('fixture')
        self.assertEqual(message.usage_metadata,{'input_tokens':11,'output_tokens':4,'total_tokens':15})
        summary=context_middleware(role).model
        self.assertIs(summary.journal,journal)
        self.assertEqual(summary.research_role,'context')
        summary.invoke('fixture compression')
        self.assertEqual(journal.requests[-1][1]['max_tokens'],7000)
        self.assertEqual(journal.requests[0][1]['max_tokens'],7000)
        missing=GatewayChatModel(journal=JournalFixture(None),research_role='verifier').invoke('unknown usage')
        self.assertIsNone(missing.usage_metadata)

    def test_presented_role_stage_is_actually_dispatchable_and_reinjected_each_request(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_context_protocol_') as directory:
            root=Path(directory);ws=ScientificWorkspace(root/'case',OfficeWorld('relationship',7551,VERSION))
            choices=view(ws)
            self.assertEqual(choices['allowed_roles'],['analyst'])
            self.assertEqual(choices['currently_allowed_role_stage_pairs'],[{'role':'analyst','stage':'analysis'}])
            self.assertFalse(choices['stage_duties']['evaluation_review']['role_allowed_now'])
            args={'role':'analyst','stage':'analysis','question':'generic data analysis fixture',
                  'inputs':[str(ws.public/'history.csv')],'rationale':'actual initial readiness'}
            model=ObservedScriptedModel(sequence=[('schedule_task',args)])
            with sqlite3.connect(root/'native.sqlite',check_same_thread=False) as conn:
                result=FrameworkRoles(ws,SqliteSaver(conn),lambda role:model).run('manager',{'id':'dispatch_fixture','question':'choose a legal task'})
            self.assertEqual(result['role'],'analyst');self.assertEqual(result['stage'],'analysis')
            self.assertEqual(model.prompts[0][-1].type,'system')
            self.assertIn('currently_allowed_role_stage_pairs',model.prompts[0][-1].content)
            self.assertFalse(ws.tool_allowed_now('read_packet'))
            # Both historic invalid role/stage combinations remain rejected;
            # the fix exposes existing rules rather than silently repairing args.
            with self.assertRaisesRegex(ValueError,'verifier duty'):
                ws.tool('manager','schedule_task',{**args,'stage':'evaluation_review','program_ids':['baseline'],'evaluation_claim':'fixture'})
            with self.assertRaisesRegex(ValueError,'allowed_roles'):
                ws.tool('manager','schedule_task',{**args,'role':'verifier','stage':'evaluation_review','program_ids':['baseline'],'evaluation_claim':'fixture'})


if __name__=='__main__':unittest.main()
