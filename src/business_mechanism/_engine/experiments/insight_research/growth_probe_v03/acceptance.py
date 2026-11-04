import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from ..common import ROOT,digest,encoded,sha,write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .recovery import capture,prepare
from token_budget import reservation_bound


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder=Path(os.environ['GROWTH_V03_OUTPUT'])/self._testMethodName
        self.folder.mkdir(parents=True,exist_ok=False)
        self.manifest=json.loads(Path(os.environ['GROWTH_V03_PARENT']).read_text())

    def test_01_capability_contract_and_durable_rejection_preserve_numeric_intent(self):
        cfg=config();cfg['verification_mode']='self';cfg['limits']['max_http_attempts']=0
        ws=ResearchWorkspace(self.folder/'researcher','Service interface regression',World(seed=72,entry_rate=8,completion_probability=1,recording_probability=1),cfg)
        try:
            schemas={t['function']['name']:t['function']['parameters'] for t in ws.tool_schemas()}
            self.assertEqual(schemas['save_hypothesis']['properties']['effect_prediction']['type'],'null')
            self.assertEqual(schemas['register_test']['properties']['mode']['enum'],['observational'])
            raw=json.loads((ROOT/self.manifest['parent_root']/'researcher/private/checkpoint.json').read_text())['pending']['calls'][0]['args']
            args=deepcopy(raw);args['evidence_refs']=[]
            rejected=ws.call('save_hypothesis',args,'unsupported')
            self.assertFalse(rejected['ok']);self.assertIn('effect_prediction=null',rejected['error'])
            self.assertFalse((ws.public/'products.csv').exists());self.assertEqual(ws.records('hypothesis'),[])
            args['effect_prediction']=None
            good=ws.call('save_hypothesis',args,'numeric_text_preserved')
            self.assertEqual(good['prediction'],raw['prediction']);self.assertEqual(good['scope'],raw['scope'])
            plan=ws.call('register_test',{'hypothesis_ref':good['ref'],'prediction':'Preserve numeric target','contrast':'capacity2 minus1',
                'observation_unit':'window','allocation_unit':'window','analysis':'received data','purpose':'Reject unavailable capability',
                'data_refs':[ws.file_ref(ws.public/'business.sqlite')['ref']],'mode':'protocol','protocol_id':'inventory-only'},'old_protocol')
            self.assertFalse(plan['ok']);self.assertIn('no inventory',plan['error'])
            write_json(self.folder/'contract_result.json',{'unsupported':rejected,'numeric_hypothesis_ref':good['ref'],'unavailable_protocol':plan,'no_inventory_table_fabricated':True})
        finally:ws.close()

    def test_02_distinct_trial_actions_collect_fresh_windows_recovery_does_not(self):
        cfg=config();cfg['verification_mode']='self';cfg['limits']['max_http_attempts']=0
        ws=ResearchWorkspace(self.folder/'researcher','Actual trial action semantics',World(seed=73,entry_rate=8,completion_probability=1,recording_probability=1),cfg)
        try:
            args={'operation':'capacity_trial','windows':8,'purpose':'Same design, two actual actions'}
            one=ws.call('collect_evidence',args,'new_action_1');two=ws.call('collect_evidence',args,'new_action_2')
            self.assertGreaterEqual(two['observation_start'],one['available_at'])
            self.assertEqual(ws.environment.public_status()['spent_credits'],48)
            before=ws.environment.state();same=ws.call('collect_evidence',args,'new_action_2')
            self.assertEqual(same,two);self.assertEqual(before,ws.environment.state())
            write_json(self.folder/'fresh_vs_recovery.json',{'first':one,'second':two,'duplicate_recovery_unchanged':True,'distinct_actions_are_new_samples':True})
        finally:ws.close()

    def test_03_actual_paid_registration_recovery_retains_original_cost_cursor_and_deadline(self):
        m=self.manifest;parent=ROOT/m['parent_root'];out=self.folder/'copied_run'
        task=json.loads((ROOT/'experiments/studies/SCI-073/tasks.json').read_text())['tasks'][1]
        identity={**m['parent_budget_identity'],'study_id':'ZERO-API-PAID-RECOVERY','run_id':'copied','variant':'growth_probe_v03','parent_manifest_digest':digest(m)}
        settings=prepare(out,m,identity,task['environment'])
        ws=ResearchWorkspace(out/'researcher',m['parent_identity']['question'],World(**task['environment']),settings,reopen=True)
        try:
            budget=StudyBudget(out/'common_budget.sqlite',identity);run=ResearchRun(out,ws,settings['model_config'],budget)
            before=budget.snapshot();pending_before=deepcopy(run.runtime.cp['pending'])
            self.assertEqual(pending_before['cursor'],0);self.assertEqual(before['http_attempts'],6)
            run.runtime.drain()
            self.assertIsNone(run.runtime.cp['pending']);self.assertEqual(budget.snapshot(),before)
            self.assertEqual(len(ws.records('hypothesis')),1)
            self.assertEqual(ws.db.execute("SELECT count(*) FROM operations WHERE status!='completed'").fetchone()[0],0)
            for i in range(1,7):self.assertEqual(sha(ws.private/'http'/f'{i}.json'),sha(parent/'researcher/private/http'/f'{i}.json'))
            messages=run.runtime.cp['messages'];feedback=[json.loads(x['content']) for x in messages[-2:] if x['role']=='tool']
            self.assertEqual(len(feedback),2);self.assertFalse(feedback[0]['ok']);self.assertIn('effect_prediction=null',feedback[0]['error'])
            self.assertEqual(feedback[1]['prediction'],pending_before['calls'][1]['args']['prediction'])
            payload=run.runtime.payload(run.runtime.initial()+messages[2:])
            self.assertLess(reservation_bound(payload),budget.snapshot()['remaining_tokens'])
            with budget.connect() as db:control=db.execute('SELECT started,deadline FROM execution_control').fetchone()
            import sqlite3
            with sqlite3.connect((parent/'common_budget.sqlite').as_uri()+'?mode=ro',uri=True) as db:old=db.execute('SELECT started,deadline FROM execution_control').fetchone()
            self.assertEqual(control,old)
            self.assertEqual(capture(parent),m)
            write_json(self.folder/'paid_recovery_result.json',{'new_paid_calls':0,'inherited_usage':before,'pending_paid_batch_drained':True,
                'original_first_call_rejected_without_word_edit':True,'second_original_prediction_retained':True,'original_deadline':control[1],
                'next_payload_bytes':len(encoded(payload).encode()),'next_reservation_bound':reservation_bound(payload),'old_parent_unchanged':True})
        finally:ws.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--parent-manifest',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);os.environ['GROWTH_V03_OUTPUT']=str(a.output/'cases');os.environ['GROWTH_V03_PARENT']=str(a.parent_manifest)
    before=snapshot();result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert snapshot()==before
    write_json(a.output/'acceptance.json',{'status':'passed' if result.wasSuccessful() else 'failed','actual_tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'new_paid_calls':0,
        'budget_unchanged':True,'scope':'3actual service capability/fresh action/actual paid-parent recovery checks; not scientific efficacy or19newP0 capabilities'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
