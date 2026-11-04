"""Generic task text survives native compaction/restart; no domain answer gate."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.runtime import FrameworkRoles,TaskInputChangedError
from run_information_protocol import InformationWorkspace
from test_tool_outputs import ObservedScriptedModel
from test_langgraph_migration import submission


class TaskInstructionTests(unittest.TestCase):
    def test_original_question_survives_compaction_and_different_tasks_do_not_leak(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_task_instruction_') as directory:
            root=Path(directory);ws=InformationWorkspace(root/'case',{'domain':'orders','construction':'count'})
            original=ws._tool
            ws._tool=lambda role,name,args: {'large_fixture':'record '*12000} if name=='read_context' else original(role,name,args)
            index=ws.workers['verifier'].directory/'framework_receipts/index.json'
            read_index=('read_artifact',{'path':str(index)})
            question='opaque objective A: compare amber and violet; preserve the 17-day scope; report any unfinished part.'
            first=ObservedScriptedModel(sequence=[('read_context',{}),read_index,read_index,
                'Different goal from a deliberately unfaithful summary.',read_index,submission()])
            with sqlite3.connect(root/'checkpoint.sqlite',check_same_thread=False) as conn:
                saver=SqliteSaver(conn)
                result=FrameworkRoles(ws,saver,lambda role:first).run('verifier',{'id':'opaque_A','question':question})
                self.assertEqual(result['role'],'verifier')
                summaries=[p for p in first.prompts if len(p)==1 and p[0].type=='human']
                self.assertEqual(len(summaries),1)
                last=first.prompts[-1]
                self.assertIn(question,last[0].content)
                self.assertFalse(any(question in str(m.content) for m in last if m.type!='system'))
                self.assertIn('Different goal',str(last))
                second_question='opaque objective B: inspect copper and retain a null result.'
                second=ObservedScriptedModel(sequence=[submission()])
                FrameworkRoles(ws,saver,lambda role:second).run('verifier',{'id':'opaque_B','question':second_question})
                self.assertIn(second_question,second.prompts[0][0].content)
                self.assertNotIn(question,second.prompts[0][0].content)

    def test_interrupted_task_recovers_its_question_without_replaying_completed_tool(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_task_restart_') as directory:
            root=Path(directory);ws=InformationWorkspace(root/'case',{'domain':'orders','construction':'count'})
            task={'id':'opaque_resume','question':'preserve this exact objective after the model process restarts'}
            first=ObservedScriptedModel(sequence=[('read_context',{})])
            with sqlite3.connect(root/'checkpoint.sqlite',check_same_thread=False) as conn:
                saver=SqliteSaver(conn)
                with self.assertRaisesRegex(AssertionError,'unexpected model call'):
                    FrameworkRoles(ws,saver,lambda role:first).run('verifier',task)
                resumed=ObservedScriptedModel(sequence=[submission()])
                FrameworkRoles(ws,saver,lambda role:resumed).run('verifier',task)
                self.assertIn(task['question'],resumed.prompts[0][0].content)
                actions=[json.loads(s)['tool'] for s in (ws.root/'framework_tools.jsonl').read_text().splitlines()]
                self.assertEqual(actions,['read_context','submit_result'])

    def test_legacy_checkpoint_backfill_and_conflicting_question_are_distinct(self):
        for replacement in (None,{'task_id':'legacy','question':'a conflicting objective'}):
            with self.subTest(replacement=replacement),tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_task_legacy_') as directory:
                root=Path(directory);ws=InformationWorkspace(root/'case',{'domain':'orders','construction':'count'})
                task={'id':'legacy','question':'the original unchanged caller objective'}
                with sqlite3.connect(root/'checkpoint.sqlite',check_same_thread=False) as conn:
                    saver=SqliteSaver(conn);first=ObservedScriptedModel(sequence=[('read_context',{})])
                    roles=FrameworkRoles(ws,saver,lambda role:first)
                    with self.assertRaisesRegex(AssertionError,'unexpected model call'):
                        roles.run('verifier',task)
                    latest=next(saver.list(None))
                    config={'configurable':{'thread_id':latest.config['configurable']['thread_id']}}
                    roles.agents['verifier'].update_state(config,{'task_instruction':replacement})
                    resumed=ObservedScriptedModel(sequence=[submission()])
                    roles=FrameworkRoles(ws,saver,lambda role:resumed)
                    if replacement is None:
                        roles.run('verifier',task)
                        self.assertIn(task['question'],resumed.prompts[0][0].content)
                    else:
                        with self.assertRaises(TaskInputChangedError):roles.run('verifier',task)
                        self.assertEqual(resumed.calls,0)


if __name__=='__main__':unittest.main()
