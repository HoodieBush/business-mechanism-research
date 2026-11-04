"""Evidence survives compact native tool messages; no scientific answer gates."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from pydantic import Field

from langchain_core.messages import ToolMessage,convert_to_openai_messages
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.tool_outputs import dataset_view
from run_information_protocol import InformationWorkspace
from test_langgraph_migration import ScriptedModel,submission


class ObservedScriptedModel(ScriptedModel):
    prompts:list=Field(default_factory=list,exclude=True)
    def _generate(self,messages,**kwargs):
        self.prompts.append(messages)
        return super()._generate(messages,**kwargs)


class ToolOutputTests(unittest.TestCase):
    def test_thin_adapter_summarizes_and_retains_full_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_context_') as directory:
            root=Path(directory);ws=InformationWorkspace(root/'U001',{'domain':'orders','construction':'count'})
            original=ws._tool
            ws._tool=lambda role,name,args: {'large_fixture':'record '*12000,'negative_evidence':'unresolved fixture'} if name=='read_context' else original(role,name,args)
            index=ws.workers['verifier'].directory/'framework_receipts/index.json'
            read_index=('read_artifact',{'path':str(index)})
            # Retain by token weight and wait for enough exchanges to summarize
            # the large tool output itself, rather than repeatedly its prefix.
            model=ObservedScriptedModel(sequence=[('read_context',{}),read_index,read_index,
                'Fixture evidence summary; unresolved; use the deterministic index.',read_index,submission()])
            with sqlite3.connect(root/'checkpoint.sqlite',check_same_thread=False) as conn:
                result=FrameworkRoles(ws,SqliteSaver(conn),lambda role:model).run('verifier',{'question':'force native context compaction'})
            self.assertEqual(model.calls,6);self.assertEqual(result['role'],'verifier')
            summaries=[p for p in model.prompts if len(p)==1 and p[0].type=='human']
            self.assertEqual(len(summaries),1)
            self.assertIn('record '*100,summaries[-1][0].content)
            self.assertIn(str(index),model.prompts[-1][0].content)
            receipts=list((ws.workers['verifier'].directory/'framework_receipts').glob('*.json'))
            self.assertTrue(any('record '*12000 in p.read_text() for p in receipts))
            actions=[json.loads(l)['tool'] for l in (ws.root/'framework_tools.jsonl').read_text().splitlines()]
            self.assertEqual(actions,['read_context']+['read_artifact']*3+['submit_result'])
            entries=json.loads(index.read_text())
            self.assertEqual([e['tool'] for e in entries],actions)
            self.assertTrue(all(ws.readable(e['full_path']).is_file() for e in entries))

    def test_csv_preview_does_not_dump_rows_or_infer_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'observations.csv'
            path.write_text('site,value\n'+''.join(f'001,{i}\n' for i in range(10000)))
            view=dataset_view(path)
            self.assertEqual(view['columns'],['site','value'])
            self.assertEqual(len(view['sample_rows_as_strings']),5)
            self.assertEqual(view['sample_rows_as_strings'][0][0],'001')
            self.assertIsNone(view['row_count']);self.assertNotIn('text',view)

    def test_artifact_raw_audit_delivery_and_permission_checked_receipt_survive(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_outputs_') as directory:
            root=Path(directory);ws=InformationWorkspace(root/'U001',{'domain':'orders','construction':'count'})
            ws.tool_response_view=lambda role,name,result: {'compact_view':True} if name=='submit_result' else result
            model=ScriptedModel(sequence=[submission()])
            with sqlite3.connect(root/'checkpoint.sqlite',check_same_thread=False) as conn:
                saver=SqliteSaver(conn)
                roles=FrameworkRoles(ws,saver,lambda role:model)
                result=roles.run('verifier',{'question':'raw result must drive delivery, not compact view'})
                self.assertEqual(result['role'],'verifier');self.assertNotIn('compact_view',result)
                thread=conn.execute('SELECT DISTINCT thread_id FROM checkpoints').fetchone()[0]
                state=roles.agents['verifier'].get_state({'configurable':{'thread_id':thread}})
                message=next(m for m in state.values['messages'] if isinstance(m,ToolMessage))
                self.assertEqual(message.artifact['feedback']['result'],result)
                converted=convert_to_openai_messages([message])[0]
                self.assertNotIn('artifact',converted)
                self.assertEqual(json.loads(converted['content'])['result'],{'compact_view':True})
                receipt=Path(message.artifact['full_receipt'])
                self.assertTrue(ws.readable(receipt).is_file())
                self.assertEqual(json.loads(receipt.read_text())['result'],result)
                audit=json.loads((ws.root/'framework_tools.jsonl').read_text().splitlines()[-1])
                self.assertEqual(audit['feedback']['result'],result)


if __name__=='__main__':unittest.main()
