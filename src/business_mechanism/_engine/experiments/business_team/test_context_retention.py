"""Native optional compaction policy; no model network, domain answers or quotas."""
import json
from pathlib import Path
import tempfile
import unittest
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from langgraph_migration.context_policy import context_middleware,retention_trigger
from langgraph_migration.provider import GatewayChatModel


class Journal:
    max_output=7000
    def __init__(self,root,profile='legacy',responses=None):
        self.root=root;self.config={'model':'fixture','context_retention_profile':profile}
        self.responses=responses or ['Original objective; 17units/day; source=/received/data.csv; unresolved.']
        self.calls=[]
    def call(self,role,payload):
        self.calls.append({'role':role,'request':payload})
        value=self.responses[min(len(self.calls)-1,len(self.responses)-1)]
        return {'request_index':len(self.calls),'response':{'choices':[{'finish_reason':'stop','message':{'content':value}}]}}


class ContextRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def middleware(self,profile='legacy',responses=None):
        journal=Journal(self.root,profile,responses)
        result=context_middleware(GatewayChatModel(journal=journal,research_role='analyst'))
        return result,journal
    def history(self,repeats=3000):
        messages=[HumanMessage(content='Original objective and records. '+('Observation identifier 17units/day. '*repeats)),
            AIMessage(content='',tool_calls=[{'id':'original-read','name':'read','args':{},'type':'tool_call'}]),
            ToolMessage(content='Actual received evidence, unresolved.',tool_call_id='original-read'),
            HumanMessage(content='Retain original units, condition and source.'),
            AIMessage(content='No decision yet.'),HumanMessage(content='Continue the same research.')]
        for index,message in enumerate(messages):message.id='fixture-message-'+str(index)
        return messages
    def test_optional_profile_retains_full_medium_history_without_summary_call(self):
        old,legacy=self.middleware();new,candidate=self.middleware('cache_continuity_v1')
        messages=self.history();state={'messages':messages};before=[m.model_dump()for m in messages]
        count=new.token_counter(messages)
        self.assertGreater(count,12000);self.assertLess(count,32000)
        self.assertIsNone(new.before_model(state,None))
        self.assertEqual(candidate.calls,[])
        self.assertEqual([m.model_dump()for m in messages],before)
        self.assertIsNotNone(old.before_model(state,None))
        self.assertEqual(len(legacy.calls),1)
    def test_large_history_still_uses_guarded_native_summary(self):
        middleware,journal=self.middleware('cache_continuity_v1')
        state={'messages':self.history(10000)}
        self.assertGreater(middleware.token_counter(state['messages']),32000)
        result=middleware.before_model(state,None)
        self.assertIsNotNone(result);self.assertEqual(len(journal.calls),1)
        self.assertEqual(journal.calls[0]['role'],'context')
        self.assertEqual(journal.calls[0]['request']['max_tokens'],7000)
        text=json.dumps(result,default=str)
        self.assertIn('source=/received/data.csv',text)
        self.assertIn('original-read',text) # recent real AI/Tool pair kept intact
    def test_two_protocol_rejections_preserve_original_history(self):
        middleware,journal=self.middleware('cache_continuity_v1',
            ['<message type="ai"><tool_call name="invented">{}</tool_call></message>'])
        state={'messages':self.history(10000)};before=[m.model_dump()for m in state['messages']]
        self.assertIsNone(middleware.before_model(state,None))
        self.assertEqual(len(journal.calls),2)
        self.assertEqual([m.model_dump()for m in state['messages']],before)
    def test_current_sdk_clauses_use_AND_and_unknown_profile_fails_before_call(self):
        legacy,journal=self.middleware()
        self.assertFalse(legacy._should_summarize(self.history(1),100))
        self.assertFalse(legacy._should_summarize(self.history(1)[:2],50000))
        with self.assertRaisesRegex(ValueError,'Unknown context retention profile'):
            self.middleware('unknown')
        self.assertEqual(journal.calls,[])

    def window_config(self, window=1048576):
        return {'model':'fixture','base_url':'https://fixture.invalid/v1',
                'context_retention_profile':'provider_window_v1',
                'context_capacity':{'model':'fixture','base_url':'https://fixture.invalid/v1',
                    'context_window_tokens':window,'source':'declared fixture metadata, not a live capacity test'}}

    def test_provider_capacity_keeps_large_original_history_with_no_summary(self):
        journal=Journal(self.root);journal.config=self.window_config()
        middleware=context_middleware(GatewayChatModel(journal=journal,research_role='analyst'))
        state={'messages':self.history(10000)};before=[m.model_dump()for m in state['messages']]
        self.assertIsNone(middleware.before_model(state,None))
        self.assertEqual(journal.calls,[])
        self.assertEqual([m.model_dump()for m in state['messages']],before)
        threshold=retention_trigger('provider_window_v1',config=journal.config)['tokens']
        self.assertEqual(threshold,838860)
        self.assertLessEqual(threshold+7000+65536,1048576)

    def test_capacity_cannot_silently_transfer_to_another_model_or_route(self):
        for field in ('model','base_url'):
            config=self.window_config();config[field]='different'
            with self.assertRaisesRegex(ValueError,'different model route'):
                retention_trigger('provider_window_v1',config=config)
        with self.assertRaisesRegex(ValueError,'explicit context_capacity'):
            retention_trigger('provider_window_v1')

    def test_small_window_uses_existing_guarded_summary_and_rejects_impossible_budget(self):
        journal=Journal(self.root);journal.config=self.window_config(80000)
        middleware=context_middleware(GatewayChatModel(journal=journal,research_role='analyst'))
        self.assertIsNotNone(middleware.before_model({'messages':self.history()},None))
        self.assertEqual(len(journal.calls),1)
        self.assertEqual(journal.calls[0]['request']['max_tokens'],7000)
        for window in (True,0,70000):
            with self.assertRaises(ValueError):
                retention_trigger('provider_window_v1',config=self.window_config(window))


if __name__=='__main__':unittest.main(verbosity=2)
