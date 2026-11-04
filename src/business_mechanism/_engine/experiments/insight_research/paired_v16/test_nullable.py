import json
import unittest
from copy import deepcopy
from ..common import ROOT, digest
from ..paired_v14 import test_delegation as old
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .continuation import prepare
from ..paired_v01.budget import StudyBudget
from ..composed_world import ComposedWorld
from ..paired_v01.test_pairing import MODEL


class NullableTests(unittest.TestCase):
    setUp=old.DelegationTests.setUp
    tearDown=old.DelegationTests.tearDown
    call=old.DelegationTests.call
    source=old.DelegationTests.source
    assessed=old.DelegationTests.assessed
    save=old.DelegationTests.save
    budget=old.DelegationTests.budget

    def make(self,mode):
        old.DelegationTests.make(self,mode)
        settings=deepcopy(self.ws.settings);question=self.ws.question;world=self.ws.environment.world;self.ws.close()
        self.ws=ResearchWorkspace(self.folder/(mode+'_v15')/'researcher',question,world,settings)
        return self.ws

    def closeout(self):
        budget=self.budget();self.ws.study_budget=budget
        with budget.connect() as db:
            db.execute("INSERT INTO flags VALUES ('stage_closeout','engineering explicit closeout')")

    def plan(self,protocol=False):
        from ..test_acceptance import hypothesis
        h=self.call('save_hypothesis',hypothesis())
        args={'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'工程','observation_unit':'记录','allocation_unit':'无',
            'analysis':'实际原代码','purpose':'空协议与收尾边界','data_refs':[self.source()],'mode':'observational','code':"print('lawful existing-data calculation')"}
        if protocol:
            args.update(mode='protocol',code=None,protocol_id='support_supply:S11',outcome_product_ids=['S01'],expected_changed_variables=['morning_stock:S11'])
        plan=self.call('register_test',args);self.assertIn('ref',plan,plan);return plan

    def test_n01_nullable_observational_protocol_runs_during_closeout(self):
        plan=self.plan();before=digest(self.ws.record(plan['ref']));self.closeout()
        result=self.call('run_test',{'plan_ref':plan['ref']})
        self.assertTrue(result['ok'],result)
        self.assertEqual(digest(self.ws.record(plan['ref'])),before)
        self.assertEqual(self.ws.trials_started(),0)

    def test_n02_physical_new_trial_still_blocked_during_closeout(self):
        plan=self.plan(protocol=True);self.closeout()
        result=self.call('run_test',{'plan_ref':plan['ref']})
        self.assertFalse(result['ok'],result)
        self.assertEqual(self.ws.trials_started(),0)

    def recover(self,mode):
        manifest=json.loads((ROOT/'experiments/insight_research/review/workflow_20261025/continuation_v15'/(mode+'.json')).read_text())
        old_identity=manifest['parent_identity'];settings=deepcopy(old_identity['settings']);env=old_identity['environment_identity']
        world=ComposedWorld(kind=env['kind'],seed=env['seed'],scenario_version=env['version'])
        identity={**manifest['parent_budget_identity'],'study_id':'engineering_pending_'+mode}
        root=self.folder/('copy_'+mode)
        prepare(root,manifest,old_identity['question'],world,settings,identity)
        ws=ResearchWorkspace(root/'researcher',old_identity['question'],world,settings,reopen=True);self.addCleanup(ws.close)
        budget=StudyBudget(root/'common_budget.sqlite',identity);run=ResearchRun(root,ws,MODEL,budget)
        before=budget.snapshot();records=ws.db.execute('SELECT ref,body FROM records ORDER BY rowid').fetchall()
        pending=deepcopy(run.runtime.cp['pending']);self.assertIsNotNone(pending)
        run.runtime.drain()
        self.assertIsNone(run.runtime.cp['pending'])
        self.assertEqual(budget.snapshot(),before)
        self.assertEqual(run.runtime.cp['responses'],pending['response'])
        after=ws.db.execute('SELECT ref,body FROM records ORDER BY rowid').fetchall()
        self.assertEqual(after[:len(records)],records)
        new=ws.records('result')[-1]
        self.assertEqual(new['plan_ref'],pending['calls'][pending['cursor']]['args']['plan_ref'])
        if mode=='self':
            self.assertTrue(new['ok'],new)
        else:
            # The frozen independent code uses its ancestor's absolute path.
            # Preserve the exact code and actual sandbox failure; recovery is
            # not permission widening or silent scientific-code rewriting.
            self.assertFalse(new['ok'],new)
            self.assertIn('unable to open database file',new['actual_execution']['stderr'])
            self.assertEqual(len(ws.records('assessment')),sum(json.loads(body)['record_type']=='assessment' for _,body in records))
        self.assertEqual(new['actual_execution']['submitted_source']['sha256'],ws.record(new['plan_ref'])['code_sha256'])
        self.assertFalse(ws.db.execute("SELECT 1 FROM operations WHERE status!='completed'").fetchone())

    def test_n03_real_self_paid_cursor_drains_without_new_request_or_fee(self):
        self.recover('self')

    def test_n04_real_independent_cursor_preserves_actual_code_failure_without_fee_or_refutation(self):
        self.recover('independent')


if __name__=='__main__':unittest.main()
