"""Pacing/accounting/restart tests; no external model calls."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph_migration.pacing import SharedTokenPacer
from langgraph_migration.provider import APIJournal


class FakeClock:
    def __init__(self):self.now=1000.;self.waits=[]
    def time(self):return self.now
    def wait(self, seconds):self.waits.append(seconds);self.now+=seconds


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.clock=FakeClock()
    def tearDown(self):self.temp.cleanup()
    def pacer(self):return SharedTokenPacer(self.root/'shared',60,clock=self.clock.time,wait=self.clock.wait)

    def test_actual_usage_refunds_estimate_without_burst_credit(self):
        pacer=self.pacer()
        with pacer.attempt(100,{'role':'analyst'}) as charge:
            self.clock.now+=3
            charge['reported_tokens']=10
        self.assertEqual(self.clock.now,1010)
        self.clock.now+=1000  # Long idle does not buy a burst.
        with pacer.attempt(1,{'role':'context'}) as charge:charge['reported_tokens']=20
        self.assertEqual(self.clock.now,2030)
        self.assertLessEqual(max(self.clock.waits),30)

    def test_unthrottled_calls_keep_reported_and_unknown_accounting_without_new_delay(self):
        pacer=SharedTokenPacer(self.root/'shared',None,clock=self.clock.time,wait=self.clock.wait)
        with pacer.attempt(100,{'role':'analyst'}) as charge:charge['reported_tokens']=10
        restarted=SharedTokenPacer(self.root/'shared',None,clock=self.clock.time,wait=self.clock.wait)
        with restarted.attempt(700,{'role':'context'}):pass
        self.assertEqual(self.clock.waits,[])
        events=[json.loads(line) for line in (self.root/'shared/events.jsonl').read_text().splitlines()]
        settled=[e for e in events if e['status'] in ('settled','usage_unknown')]
        self.assertEqual([e['pacing_tokens'] for e in settled],[10,700])
        self.assertEqual([e['reported_tokens'] for e in settled],[10,None])
        self.assertTrue(all(e['tokens_per_minute'] is None for e in events))

    def test_default_journal_has_no_artificial_rate_but_can_explicitly_restore_one(self):
        a,b=self.root/'unlimited',self.root/'limited';a.mkdir();b.mkdir()
        self.assertIsNone(APIJournal(a,{'model':'fixture'}).pacer.rate)
        self.assertEqual(APIJournal(b,{'model':'fixture'},tokens_per_minute=20_000).pacer.rate,20_000)

    def test_unknown_usage_and_restart_preserve_reservation(self):
        with self.assertRaisesRegex(RuntimeError,'interrupted'):
            with self.pacer().attempt(70,{'role':'verifier'}):raise RuntimeError('interrupted')
        with self.pacer().attempt(10,{'role':'engineer'}):pass
        self.assertEqual(self.clock.now,1080)
        state=json.loads((self.root/'shared/state.json').read_text())
        self.assertIsNone(state['reported_tokens']);self.assertEqual(state['pacing_tokens'],10)

    def test_retries_and_context_share_pacer_and_keep_unknown_separate(self):
        responses=[{'response':{},'error_type':'transport','error':'timeout'},
                   {'response':{'usage':{'prompt_tokens':12,'completion_tokens':8,'total_tokens':20}}},
                   {'response':{'usage':{'prompt_tokens':9,'completion_tokens':1,'total_tokens':10}}}]
        a,b=self.root/'a',self.root/'b';a.mkdir();b.mkdir()
        journal=APIJournal(a,{'model':'fixture'},max_output=10,pacer=self.pacer())
        context=APIJournal(b,{'model':'fixture'},max_output=10,pacer=self.pacer())
        payload={'messages':[{'role':'user','content':'same request'}]}
        with patch('langgraph_migration.provider.request_model',side_effect=responses) as request,patch('langgraph_migration.provider.interruptible_wait'):
            journal.call('verifier',payload);context.call('context',payload)
        self.assertEqual(request.call_args_list[0],request.call_args_list[1])
        events=[json.loads(l) for l in (self.root/'shared/events.jsonl').read_text().splitlines()]
        self.assertEqual([e['identity']['role'] for e in events if e['status']=='in_flight_or_interrupted'],['verifier','verifier','context'])
        self.assertEqual(self.clock.now-1000,journal.calls[0]['admission_estimate']+30)
        self.assertEqual(journal.usage()['total_tokens'],20)
        self.assertEqual(journal.usage()['calls_without_reported_usage'],1)
        self.assertIsNone(context.public_view()['shared_admission_limit'])

    def test_separate_processes_cannot_overlap_or_reset_debt(self):
        code=('from langgraph_migration.pacing import SharedTokenPacer\n'
              'import sys,time\n'
              'with SharedTokenPacer(sys.argv[1],60000).attempt(250,{"process":sys.argv[2]}) as charge:\n'
              ' time.sleep(.02)\n charge["reported_tokens"]=150\n')
        procs=[subprocess.Popen([sys.executable,'-B','-c',code,str(self.root/'processes'),str(i)],cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i in range(2)]
        for process in procs:
            _,error=process.communicate(timeout=15);self.assertEqual(process.returncode,0,error.decode())
        events=[json.loads(l) for l in (self.root/'processes/events.jsonl').read_text().splitlines()]
        starts=[e for e in events if e['status']=='in_flight_or_interrupted']
        self.assertEqual(len(starts),2)
        self.assertGreaterEqual(starts[1]['started_at']-starts[0]['started_at'],.149)
        self.assertEqual([e['status'] for e in events],['in_flight_or_interrupted','settled']*2)


if __name__=='__main__':unittest.main()
