"""Real transport boundary with fake HTTP only; never contacts the provider."""
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

from langgraph_migration.provider import APIJournal
from token_budget import SharedTokenBudget, TokenBudgetStop, initialize_budget, reservation_bound
import model_protocol


PAYLOAD = {'model':'budget-fixture','messages':[{'role':'user','content':'测试共享预算'}],'max_tokens':20}


class FakeResponse:
    status = 200
    headers = {'X-Oneapi-Request-Id':'fixture-provider-id'}
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self):
        return json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'ok'}}],
                           'usage':{'prompt_tokens':9,'completion_tokens':1,'total_tokens':10,
                                    'prompt_tokens_details':{'cached_tokens':9}}}).encode()


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.pointer=initialize_budget(self.root/'budget',budget_id='fixture',limit_tokens=200000,
            model='budget-fixture',base_url='https://fixture.invalid/v1',user_instruction='test only')
        self.config={'model':'budget-fixture','base_url':'https://fixture.invalid/v1',
                     'token_budget_pointer':str(self.pointer)}
    def tearDown(self):self.tmp.cleanup()
    def budget(self):return SharedTokenBudget(self.pointer)

    def test_reservation_precedes_send_and_cached_input_counts_in_full(self):
        opener=MagicMock()
        def open_fake(*args,**kwargs):
            self.assertEqual(self.budget().snapshot()['unknown_or_inflight_reserve'],reservation_bound(PAYLOAD))
            return FakeResponse()
        opener.open.side_effect=open_fake
        with patch.object(model_protocol,'load_api_key',return_value='fixture-secret'),patch.object(model_protocol.urllib.request,'build_opener',return_value=opener):
            record=model_protocol.request_model(self.config,PAYLOAD)
        self.assertEqual(self.budget().snapshot()['reported_tokens'],10)
        self.assertEqual(self.budget().snapshot()['unknown_or_inflight_reserve'],0)
        self.assertEqual(record['provider_request_id'],'fixture-provider-id')
        self.assertNotIn('fixture-secret',json.dumps(record))

    def test_analyst_summary_retry_and_new_journal_share_one_authorization(self):
        opener=MagicMock();opener.open.side_effect=[urllib.error.URLError('fixture timeout'),FakeResponse(),FakeResponse()]
        roots=[self.root/'first',self.root/'second']
        for p in roots:p.mkdir()
        first=APIJournal(roots[0],self.config,max_output=20)
        second=APIJournal(roots[1],self.config,max_output=20)
        with patch.object(model_protocol,'load_api_key',return_value=''),patch.object(model_protocol.urllib.request,'build_opener',return_value=opener),patch('langgraph_migration.provider.interruptible_wait'):
            first.call('analyst',PAYLOAD);second.call('context',PAYLOAD)
        state=self.budget().snapshot()
        self.assertEqual(state['attempts_reserved'],3)
        self.assertEqual(state['reported_tokens'],20)
        self.assertEqual(state['unknown_or_inflight_reserve'],reservation_bound(PAYLOAD))

    def test_restart_does_not_refund_an_inflight_or_unknown_attempt(self):
        self.budget().reserve(PAYLOAD)
        restarted=self.budget()
        self.assertEqual(restarted.snapshot()['unknown_or_inflight_reserve'],reservation_bound(PAYLOAD))
        r=restarted.reserve(PAYLOAD);restarted.settle(r,None)
        self.assertEqual(self.budget().snapshot()['accounted_tokens'],2*reservation_bound(PAYLOAD))

    def test_denial_and_missing_budget_never_open_HTTP(self):
        large={**PAYLOAD,'max_tokens':200001}
        opener=MagicMock()
        with patch.object(model_protocol,'load_api_key',return_value=''),patch.object(model_protocol.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(TokenBudgetStop):model_protocol.request_model(self.config,large)
            missing={**self.config,'token_budget_pointer':str(self.root/'missing.json')}
            with self.assertRaises(TokenBudgetStop):model_protocol.request_model(missing,PAYLOAD)
        opener.open.assert_not_called()
        self.assertEqual(self.budget().snapshot()['status'],'exhausted')

    def test_no_further_allocation_can_use_exhausted_authorization(self):
        budget=self.budget()
        with self.assertRaises(TokenBudgetStop):budget.reserve({**PAYLOAD,'max_tokens':200001})
        with self.assertRaises(TokenBudgetStop):self.budget().reserve(PAYLOAD)

    def test_deleted_database_or_modified_authorization_fails_closed(self):
        auth=self.root/'budget/authorization.json';auth.write_text(auth.read_text()+' ')
        with self.assertRaises(TokenBudgetStop):self.budget()
        auth.write_text(auth.read_text()[:-1]);(self.root/'budget/ledger.sqlite').unlink()
        with self.assertRaises(TokenBudgetStop):self.budget()
        self.assertFalse((self.root/'budget/ledger.sqlite').exists())

    def test_duplicate_settlement_cannot_refund_twice(self):
        budget=self.budget();r=budget.reserve(PAYLOAD);budget.settle(r,{'total_tokens':5})
        with self.assertRaises(TokenBudgetStop):budget.settle(r,{'total_tokens':0})
        self.assertEqual(budget.snapshot()['reported_tokens'],5)

    def test_bad_usage_stays_unknown_and_breached_bound_halts(self):
        budget=self.budget();r=budget.reserve(PAYLOAD)
        budget.settle(r,{'total_tokens':0,'prompt_tokens':9,'completion_tokens':1})
        self.assertEqual(budget.snapshot()['unknown_or_inflight_reserve'],reservation_bound(PAYLOAD))
        r=budget.reserve(PAYLOAD);budget.settle(r,{'total_tokens':r['reserved_tokens']+1})
        self.assertEqual(budget.snapshot()['status'],'halted')
        with self.assertRaises(TokenBudgetStop):budget.reserve(PAYLOAD)

    def test_manual_stop_is_persistent_and_cannot_reinitialize(self):
        self.budget().stop('user stop')
        with self.assertRaises(TokenBudgetStop):self.budget().reserve(PAYLOAD)
        with self.assertRaises(FileExistsError):
            initialize_budget(self.root/'budget',budget_id='replacement',limit_tokens=999999,
                model='budget-fixture',base_url='https://fixture.invalid/v1',user_instruction='not allowed')

    def test_concurrent_processes_cannot_spend_the_same_remaining_tokens(self):
        pointer=initialize_budget(self.root/'concurrent',budget_id='concurrent',
            limit_tokens=reservation_bound(PAYLOAD)+1,model='budget-fixture',
            base_url='https://fixture.invalid/v1',user_instruction='fixture')
        code=('import json,sys\nfrom token_budget import SharedTokenBudget,TokenBudgetStop\n'
              'try: SharedTokenBudget(sys.argv[1]).reserve(json.loads(sys.argv[2]))\n'
              'except TokenBudgetStop: sys.exit(3)\n')
        cap=Path(model_protocol.__file__).parent
        procs=[subprocess.Popen([sys.executable,'-B','-c',code,str(pointer),json.dumps(PAYLOAD)],cwd=cap,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
        statuses=[]
        for proc in procs:
            _,err=proc.communicate(timeout=20);statuses.append(proc.returncode)
            self.assertIn(proc.returncode,[0,3],err.decode())
        self.assertEqual(statuses.count(0),1)
        snap=SharedTokenBudget(pointer).snapshot()
        self.assertEqual(snap['attempts_reserved'],1)
        self.assertLessEqual(snap['accounted_tokens'],snap['limit_tokens'])


if __name__=='__main__':unittest.main()
