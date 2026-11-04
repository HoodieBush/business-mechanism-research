import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from ..common import ROOT,encoded,write_json
from ..fusion_rsi_v01.acceptance import config
from ..growth_probe_v01.environment import World
from ..growth_probe_v03.orchestrator import ResearchRun
from ..paired_v01.budget import StudyBudget
from ..review.workflow_20261025.quiescent_budget import snapshot
from .workspace import ResearchWorkspace

QUESTION='Decide whether adding a second capacity unit is worthwhile at an incremental cost of2 recorded transactions/window. Select competing predictions and lawful evidence; keep the conclusion scoped to the new task.'
HISTORY=ROOT/'experiments/insight_research/review/growth_experience_20261031/history_provenance.json'


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder=Path(os.environ['GROWTH_V04_OUTPUT'])/self._testMethodName;self.folder.mkdir(parents=True,exist_ok=False)
        self.ws=[];self.descriptor=json.loads(HISTORY.read_text())['archive']
    def tearDown(self):
        for ws in self.ws:ws.close()
    def workspace(self,mode):
        cfg=config();cfg.update(verification_mode='self',experience_mode=mode,project_archives=[] if mode=='none' else [self.descriptor])
        cfg['limits'].update(token_allowance=800000,max_http_attempts=0)
        ws=ResearchWorkspace(self.folder/mode/'researcher',QUESTION,World(seed=823,entry_rate=20,completion_probability=1,recording_probability=.4,instruments=('observe','capacity_trial','wait')),cfg)
        self.ws.append(ws);return ws

    def test_01_same_current_sources_tools_and_empty_science_across_modes(self):
        cases=[self.workspace(mode) for mode in ('none','recent','episode')]
        self.assertEqual(cases[0].identity['public_inputs'],cases[1].identity['public_inputs'])
        self.assertEqual(cases[1].identity['public_inputs'],cases[2].identity['public_inputs'])
        self.assertEqual(encoded(cases[0].tool_schemas()),encoded(cases[1].tool_schemas()))
        self.assertEqual(encoded(cases[1].tool_schemas()),encoded(cases[2].tool_schemas()))
        for ws in cases:
            self.assertEqual(len(ws.tools),16);self.assertEqual(ws.records('hypothesis'),[]);self.assertEqual(ws.records('knowledge'),[])
            ctx=ws.context();self.assertLessEqual(len(encoded(ctx).encode()),65536)
            for name in ('entry_rate','completion_probability','recording_probability','scientific_audit.json'):
                self.assertNotIn(name,encoded(ctx))
        self.assertEqual(cases[0].context()['prior_experience']['items'],[])
        missing=cases[0].call('read_memory',{'ref':'archive:SCI073-SERVICE-01:H7aa1b2e859c34fda','offset':0,'limit':12000},'unreceived_history')
        self.assertFalse(missing['ok'])

    def test_02_recent_and_episode_selection_have_exact_sources_and_bounded_navigation(self):
        recent=self.workspace('recent');episode=self.workspace('episode')
        a=recent.experience_context();b=episode.experience_context()
        self.assertEqual([x['record_type'] for x in a['items']],['knowledge']*3)
        self.assertEqual([x['record_type'] for x in b['items']],['hypothesis','assessment','result'])
        self.assertEqual(b['selection']['selected_hypothesis'],'H7aa1b2e859c34fda')
        for view in (a,b):
            self.assertLessEqual(view['automatic_context_bytes'],6144)
            self.assertTrue(all(x['historical_not_current_fact'] for x in view['items']))
        query=episode.call('search_memory',{'archive_stage':'SCI073-SERVICE-01','query':'capacity','kind':'hypothesis','include_history':True,'offset':0,'limit':8},'old_search')
        self.assertGreater(query['total'],0)
        old=episode.call('read_memory',{'ref':b['items'][0]['ref'],'offset':0,'limit':12000},'exact_oldH')
        value=json.loads(old['text']);self.assertEqual(value['original']['ref'],'H7aa1b2e859c34fda')
        self.assertIn('materialized_original',old)
        new=episode.call('save_hypothesis',{'kind':'business','statement':'A new scoped hypothesis','scope':'new task only','prediction':'current capacity increment exceeds2',
            'falsification':'new interval upper below2','alternatives':['below-cost increment'],'evidence_refs':[old['materialized_original']['ref']],
            'used_memory_refs':[old['materialized_original']['ref']],'effect_prediction':None},'newH_with_past_source')
        self.assertEqual(new['prediction'],'current capacity increment exceeds2')
        self.assertEqual(len(episode.records('hypothesis')),1);self.assertEqual(episode.records('knowledge'),[])
        write_json(self.folder/'selection_and_readback.json',{'recent':a,'episode':b,'search_total':query['total'],'exact_old_original_preserved':True,'new_science_independent':True})

    def test_03_actual_sandbox_denies_external_audit_and_normal_runtime_initializes(self):
        ws=self.workspace('episode')
        p=ROOT/'experiments/studies/SCI-073/scientific_audit.json'
        result=ws.call('run_python',{'code':f'print(open({str(p)!r}).read())','purpose':'Actual external audit denial'},'deny_root_audit')
        self.assertFalse(result['execution']['ok'])
        budget=StudyBudget(self.folder/'episode/common_budget.sqlite',{'token_allowance':800000,'max_http_attempts':0,'project_budget_id':'USER-20261022-CRITIC-10M'},create=True)
        run=ResearchRun(self.folder/'episode',ws,ws.settings['model_config'],budget)
        payload=run.runtime.payload(run.runtime.initial())
        self.assertEqual(payload['max_tokens'],65536);self.assertEqual(budget.snapshot()['http_attempts'],0)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    os.environ['GROWTH_V04_OUTPUT']=str(a.output/'cases');before=snapshot()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));assert before==snapshot()
    write_json(a.output/'acceptance.json',{'status':'passed' if result.wasSuccessful() else 'failed','actual_tests_run':result.testsRun,'errors':len(result.errors),
        'failures':len(result.failures),'skipped':len(result.skipped),'new_paid_calls':0,'budget_unchanged':True,
        'scope':'3actual history/source/citation/current-state/private-boundary controls, not memory efficacy or long-term growth'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__=='__main__':main()
