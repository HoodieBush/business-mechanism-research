"""Generic compaction contracts; no task-specific answer gates or paid calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage,HumanMessage,SystemMessage,convert_to_openai_messages
from langchain_core.outputs import ChatGeneration,ChatResult

from langgraph_migration.context_policy import SUMMARY_PROMPT
from langgraph_migration.provider import GatewayChatModel
from langgraph_migration.summary_reuse import (
    RetainingSummaryMiddleware,SummaryRejected,recorded_prefix,validated_summarizer)


class SummaryModel(BaseChatModel):
    journal:object=Field(exclude=True)
    sequence:list
    seen:list=Field(default_factory=list)
    @property
    def _llm_type(self):return 'summary-contract-fixture'
    def _generate(self,messages,**kwargs):
        self.seen.append({'messages':convert_to_openai_messages(messages),'kwargs':kwargs})
        message=self.sequence.pop(0)
        if isinstance(message,Exception):raise message
        return ChatResult(generations=[ChatGeneration(message=message)])


def answer(text='original objective; 17 items/day; negative result; source=/received/report.json; unresolved',finish='stop',**kwargs):
    return AIMessage(content=text,response_metadata={'finish_reason':finish},**kwargs)


class SummaryReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.history=[HumanMessage(content='original question: preserve null result, units and limits. '+('received evidence '*1000)),AIMessage(content='actual analysis, unresolved')]
        self.tools=[{'type':'function','function':{'name':'read','description':'read received evidence','parameters':{'type':'object','properties':{}}}}]
        self.prefix=[{'role':'system','content':'fixed role and original task'},*convert_to_openai_messages(self.history)]
        self.journal=SimpleNamespace(root=Path(self.temp.name),config={},calls=[{'request_index':7,'role':'analyst','task':None,'request':{'messages':self.prefix+[{'role':'system','content':'complete current state'}],'tools':self.tools}}])
    def model(self,sequence):return SummaryModel(journal=self.journal,sequence=sequence)
    def test_reuses_exact_sent_system_history_and_tools_without_mutating_them(self):
        before=json.dumps(self.journal.calls,sort_keys=True);model=self.model([answer()])
        text=validated_summarizer(model,'analyst','prefix',SUMMARY_PROMPT)(self.history)
        seen=model.seen[0]
        self.assertEqual(seen['messages'][:-1],self.prefix)
        self.assertEqual(seen['kwargs']['tools'],self.tools)
        self.assertEqual(seen['kwargs']['tool_choice'],'none')
        self.assertEqual(seen['messages'][-1]['role'],'system')
        self.assertIn('fixed role and original task',seen['messages'][-1]['content'])
        self.assertIn('本次不继续研究任务或执行任何工具',seen['messages'][-1]['content'])
        self.assertIn('source=/received/report.json',text)
        self.assertEqual(json.dumps(self.journal.calls,sort_keys=True),before)
    def test_role_task_or_actual_history_mismatch_cannot_borrow_another_prefix(self):
        self.assertIsNone(recorded_prefix(self.journal,self.history,'verifier'))
        with patch('langgraph_migration.summary_reuse.task_trace',return_value={'task_id':'different'}):
            self.assertIsNone(recorded_prefix(self.journal,self.history,'analyst'))
        changed=[HumanMessage(content='different original objective'),*self.history[1:]]
        self.assertIsNone(recorded_prefix(self.journal,changed,'analyst'))
    def test_no_matching_prefix_falls_back_to_complete_serialized_source(self):
        model=self.model([answer()]);validated_summarizer(model,'verifier','prefix',SUMMARY_PROMPT)(self.history)
        self.assertEqual(len(model.seen[0]['messages']),1)
        self.assertIn('original question:',model.seen[0]['messages'][0]['content'])
        self.assertNotIn('tools',model.seen[0]['kwargs'])
    def test_truncated_summary_is_repaired_before_any_replacement(self):
        model=self.model([answer('incomplete',finish='length'),answer()])
        result=validated_summarizer(model,'analyst','prefix',SUMMARY_PROMPT)(self.history)
        self.assertEqual(result,answer().content);self.assertEqual(len(model.seen),2)
        events=[json.loads(x)for x in (self.journal.root/'summary_events.jsonl').read_text().splitlines()]
        self.assertEqual([x['event']for x in events],['selected','rejected','accepted'])
    def test_failed_compaction_keeps_original_history_and_does_not_land_checkpoint(self):
        model=self.model([answer('partial',finish='length'),answer('partial again',finish='length')])
        middleware=RetainingSummaryMiddleware(model=model,trigger=('messages',2),keep=('messages',1),
            trim_tokens_to_summarize=None,summarizer=validated_summarizer(model,'analyst','prefix',SUMMARY_PROMPT))
        state={'messages':[HumanMessage(content='precise original evidence '*1000),AIMessage(content='actual failed action'),HumanMessage(content='current task')]}
        before=[m.content for m in state['messages']]
        self.assertIsNone(middleware.before_model(state,None))
        self.assertEqual([m.content for m in state['messages']],before)
        self.assertEqual(len(model.seen),2)
    def test_tool_protocol_output_never_becomes_summary(self):
        model=self.model([answer('<｜DSML｜invoke name="read">x</｜DSML｜invoke>'),answer('',tool_calls=[{'id':'x','name':'read','args':{},'type':'tool_call'}])])
        with self.assertRaises(SummaryRejected):validated_summarizer(model,'analyst','prefix',SUMMARY_PROMPT)(self.history)
    def test_malformed_summary_tool_arguments_can_be_repaired_without_losing_evidence(self):
        model=self.model([json.JSONDecodeError('invalid tool arguments','{',1),answer()])
        text=validated_summarizer(model,'analyst','prefix',SUMMARY_PROMPT)(self.history)
        self.assertIn('negative result',text);self.assertEqual(len(model.seen),2)
    def test_gateway_propagates_finish_reason_and_has_no_hidden_context_only_cap(self):
        class Journal:
            config={'model':'fixture'};max_output=7000
            def call(self,role,payload):
                self.payload=payload
                return {'request_index':1,'response':{'choices':[{'finish_reason':'length','message':{'content':'partial'}}]}}
        journal=Journal();message=GatewayChatModel(journal=journal,research_role='context').invoke('summary fixture')
        self.assertEqual(message.response_metadata['finish_reason'],'length')
        self.assertEqual(journal.payload['max_tokens'],7000)


if __name__=='__main__':unittest.main()
