import argparse
import os
from pathlib import Path
import unittest
from ..common import write_json
from ..growth_probe_v01.acceptance import Checks as PreviousChecks
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from .orchestrator import ResearchRun


class Checks(PreviousChecks):
    def runner(self):
        identity={'token_allowance':2000000,'max_http_attempts':0,'project_budget_id':'USER-20261022-CRITIC-10M'}
        b=StudyBudget(self.folder/'actor/common_budget.sqlite',identity,create=True)
        return ResearchRun(self.folder/'actor',self.ws,self.cfg['model_config'],b)

    def test_17_new_evidence_changes_actual_guard_but_reread_does_not(self):
        runner=self.runner();before=runner.guard.fingerprint()
        out=self.call('entry_count',8);after=runner.guard.fingerprint()
        self.assertNotEqual(before,after)
        self.ws.call('read_artifact',{'ref':out['files'][1]['ref'],'offset':0,'limit':12000},'reread')
        self.assertEqual(after,runner.guard.fingerprint())
        self.assertEqual(runner.budget.snapshot()['http_attempts'],0)

    def test_18_wait_and_rejection_do_not_pretend_to_be_new_observations(self):
        runner=self.runner();before=runner.guard.fingerprint()
        self.call('wait',8);self.assertEqual(before,runner.guard.fingerprint())
        self.call('capacity_trial',3);self.assertEqual(before,runner.guard.fingerprint())

    def test_19_current_runner_keeps_guard_deadline_and_normal_model_payload(self):
        runner=self.runner();first=runner.guard.inspect()
        out=self.call('flow_audit',8);signature=runner.guard.fingerprint()
        from ..paired_v16.guard import ProgressGuard as OldGuard
        old=OldGuard(runner.root,self.ws,runner.budget)
        self.assertNotEqual(signature,old.fingerprint())
        from .orchestrator import ProgressGuard
        reopened=ProgressGuard(runner.root,self.ws,runner.budget)
        self.assertEqual(reopened.fingerprint(),signature)
        self.assertEqual(first['deadline_unix'],reopened.inspect()['deadline_unix'])
        request=runner.runtime.payload(runner.runtime.initial())
        self.assertEqual(request['max_tokens'],65536)
        self.assertFalse(self.ws.db.in_transaction)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    output=Path(a.output);output.mkdir(parents=True,exist_ok=False)
    os.environ['GROWTH_P0_OUTPUT']=str(output/'cases');before=snapshot()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before==snapshot()
    write_json(output/'acceptance.json',{'status':'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'new_paid_calls':0,'budget_unchanged':True,
        'scope':'16P0 checks rerun plus3new received-observation progress integration checks; not19new independent capabilities'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
