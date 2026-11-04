"""P0 checks on actual tools, files, sandboxes and public-interface references."""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from ..common import ROOT, encoded, write_json
from ..fusion_rsi_v01.acceptance import config
from ..paired_v01.budget import StudyBudget
from ..paired_v16.orchestrator import ResearchRun
from ..review.workflow_20261025.quiescent_budget import snapshot
from .environment import World, Environment
from .workspace import ResearchWorkspace
from .evaluation import capacity_analysis, capture_analysis, reference_score


class Checks(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['GROWTH_P0_OUTPUT']) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.cfg = config(); self.cfg['verification_mode'] = 'self'; self.cfg['limits']['max_http_attempts'] = 0
        self.world = World(seed=471, entry_rate=20, completion_probability=.4, recording_probability=1)
        self.ws = ResearchWorkspace(self.folder/'actor/researcher', 'Study recorded transactions and capacity through lawful evidence.', self.world, self.cfg)
        self.counter = 0

    def tearDown(self):
        self.ws.close()

    def call(self, operation, windows, purpose='P0 public-interface reference', key=None):
        self.counter += 1
        return self.ws.call('collect_evidence', {'operation': operation, 'windows': windows, 'purpose': purpose}, key or 'p0_'+str(self.counter))

    def observations(self, out):
        return json.loads(Path(next(f['path'] for f in out['files'] if Path(f['path']).name == 'observations.json')).read_text())

    def test_01_actual_public_sources_query_and_tool_catalog(self):
        context = self.ws.context()
        self.assertIn('collect_evidence', self.ws.tools); self.assertNotIn('inspect_evidence', self.ws.tools)
        for secret in ['entry_rate', 'completion_probability', 'recording_probability', 'environment_state.json']:
            self.assertNotIn(secret, encoded(context))
        public = json.loads((self.ws.public/'measurement_catalog.json').read_text())
        self.assertTrue(public['operations']['flow_audit']['available'])
        out = self.ws.call('query_data', {'sql':'SELECT count(*),sum(recorded_transactions) FROM logs','purpose':'Read received historical records'}, 'query')
        self.assertEqual(out['preview'][0][0], 24)

    def test_02_actual_counter_and_audit_invariants(self):
        meter = self.call('entry_count', 8); audit = self.call('flow_audit', 8)
        self.assertNotIn('completed', self.observations(meter)[0])
        for row in self.observations(audit):
            self.assertGreaterEqual(row['entries'], row['completed'])
            self.assertGreaterEqual(row['completed'], row['recorded_transactions'])
        self.assertEqual(audit['evidence_nature'], 'new_measurement')
        self.assertFalse(audit['scientific_certification'])
        self.assertEqual(self.ws.environment.public_status()['spent_credits'], 40)

    def test_03_real_randomized_trial_actual_assignment_and_time(self):
        out = self.call('capacity_trial', 32); rows = self.observations(out)
        self.assertEqual(sum(r['capacity_multiplier']==1 for r in rows), 16)
        self.assertEqual(sum(r['capacity_multiplier']==2 for r in rows), 16)
        self.assertTrue(all(24 <= r['window'] < 56 for r in rows))
        self.assertEqual(out['available_at'], 57)
        self.assertEqual(out['changed_variable'], 'capacity_multiplier')
        self.assertEqual(self.ws.environment.public_status()['clock'], 57)

    def test_04_action_changes_completion_not_external_requests(self):
        for tick in range(24, 64):
            one = self.world.window(tick, 1); two = self.world.window(tick, 2)
            self.assertEqual(one['entries'], two['entries'])
            self.assertGreaterEqual(two['completed'], one['completed'])
            self.assertGreaterEqual(two['recorded_transactions'], one['recorded_transactions'])

    def test_05_idempotent_actual_tool_and_argument_identity(self):
        one = self.call('entry_count', 8, key='stable')
        before = self.ws.environment.state()
        two = self.call('entry_count', 8, key='stable')
        self.assertEqual(one, two); self.assertEqual(before, self.ws.environment.state())
        with self.assertRaises(ValueError): self.call('entry_count', 16, key='stable')

    def test_06_host_commit_recovers_without_recharge_or_resample(self):
        args = {'operation':'flow_audit','windows':8,'purpose':'P0 interrupted host publication'}
        from ..common import digest
        directory = self.ws.science/'evidence'/digest('interrupted')[:24]
        first = self.ws.environment.perform(directory, 'interrupted', **args)
        state = self.ws.environment.state(); root = self.ws.root
        # Simulate loss of only the derived publication after durable env effect.
        (directory/'receipt.json').unlink(); (directory/'observations.json').unlink()
        self.ws.close(); self.ws = ResearchWorkspace(root, self.ws.question, self.world, self.cfg, reopen=True)
        second = self.ws.call('collect_evidence', args, 'interrupted')
        self.assertEqual(first['credit_charge'], second['credit_charge'])
        self.assertEqual(state, self.ws.environment.state())
        self.assertEqual(len(self.observations(second)), 8)

    def test_07_uninstalled_operation_is_honest_and_has_no_effect(self):
        world = World(seed=3, entry_rate=8, completion_probability=1, recording_probability=1,
                      instruments=('observe','capacity_trial','wait'))
        other = ResearchWorkspace(self.folder/'limited/researcher', 'Study lawful available information.', world, self.cfg)
        try:
            before = other.environment.state()
            out = other.call('collect_evidence', {'operation':'entry_count','windows':8,'purpose':'Check instrument availability'}, 'unsupported')
            self.assertFalse(out['ok']); self.assertEqual(before, other.environment.state())
        finally: other.close()

    def test_08_bounded_resources_wait_and_invalid_trial(self):
        start = self.ws.environment.state()
        bad = self.call('capacity_trial', 3); self.assertFalse(bad['ok'])
        self.assertEqual(start, self.ws.environment.state())
        out = self.call('wait', 5)
        self.assertEqual(out['evidence_nature'], 'no_observation'); self.assertEqual(self.observations(out), [])
        self.call('capacity_trial', 128)
        before = self.ws.environment.state()
        bad = self.call('capacity_trial', 128)
        self.assertFalse(bad['ok']); self.assertEqual(before, self.ws.environment.state())

    def test_09_actual_python_reads_received_new_data(self):
        evidence = self.call('flow_audit', 8)
        filename = next(f['path'] for f in evidence['files'] if Path(f['path']).name=='observations.json')
        out = self.ws.call('run_python', {'code':f"import json\nr=json.load(open({filename!r})); print(len(r)); assert all(x['entries']>=x['completed']>=x['recorded_transactions'] for x in r)",
            'purpose':'Actual sandbox computation on received evidence'}, 'analysis')
        self.assertTrue(out['execution']['ok'], out); self.assertEqual(out['execution']['stdout'].strip(), '8')

    def test_10_actual_sandbox_private_boundary(self):
        private = str(self.ws.private/'environment_state.json')
        source = str(Path(__file__).parent/'environment.py')
        for i, path in enumerate([private, source]):
            out = self.ws.call('run_python', {'code':f"print(open({path!r}).read())", 'purpose':'P0 actual private-content denial'}, 'denial_'+str(i))
            self.assertFalse(out['execution']['ok'], out)
            self.assertNotIn('recording_probability', out['execution'].get('stdout',''))

    def test_11_observational_equivalence_is_not_hidden_label_recovery(self):
        worlds = [World(seed=13, entry_rate=a, completion_probability=b, recording_probability=c)
                  for a,b,c in [(8,1,1),(20,.4,1),(20,1,.4)]]
        for w in worlds: self.assertAlmostEqual(w.expected(), 8.)
        # Marked-Poisson thinning gives Poi(lambda*p*q); all count PMFs match.
        pmfs = [[math.exp(-w.expected())*w.expected()**k/math.factorial(k) for k in range(24)] for w in worlds]
        self.assertEqual(pmfs[0], pmfs[1]); self.assertEqual(pmfs[1], pmfs[2])
        # First and third also match every installed observe/capacity setting.
        for c in [1,2]: self.assertEqual(worlds[0].expected(c), worlds[2].expected(c))
        self.assertNotEqual(worlds[1].expected(2), worlds[1].expected(1))

    def test_12_three_way_reference_scoring_rejects_degenerate_policies(self):
        truths = ['supported','refuted','unresolved']
        self.assertEqual(sum(reference_score(t,t) for t in truths), 3)
        for constant in truths:
            self.assertEqual(sum(reference_score(t,constant) for t in truths), 1)
        with self.assertRaises(ValueError): reference_score('true','supported')

    def test_13_actual_reference_case_uses_public_tools_and_fixed_budget(self):
        self.call('entry_count', 16); self.call('flow_audit', 16)
        trial = self.call('capacity_trial', 128)
        analysis = capacity_analysis(self.observations(trial))
        self.assertEqual(analysis['decision'], 'supported', analysis)
        self.assertEqual(analysis['arm_windows'], [64,64])
        self.assertEqual(self.ws.environment.public_status()['spent_credits'], 464)
        write_json(self.folder/'reference_case.json', {'trial_receipt':trial,'analysis':analysis,
            'scope':'Engineering reference, not Agent research or confirmation', 'new_paid_calls':0})

    def test_14_finite_signal_design_diagnostic(self):
        decisions = {'capacity':{},'low_entries':{}}
        for label, params in [('capacity',(20,.4,1)), ('low_entries',(8,1,1))]:
            for seed in range(100):
                world = World(seed=seed, entry_rate=params[0], completion_probability=params[1], recording_probability=params[2])
                rng = np.random.default_rng(np.random.SeedSequence([seed,58,719]))
                arms = rng.permutation([1]*64+[2]*64)
                rows = [world.window(t,int(c)) for t,c in zip(range(58,186),arms)]
                decision = capacity_analysis(rows)['decision']
                decisions[label][decision] = decisions[label].get(decision,0)+1
        self.assertGreaterEqual(decisions['capacity'].get('supported',0), 95)
        self.assertGreaterEqual(decisions['low_entries'].get('refuted',0), 95)
        write_json(self.folder/'signal_diagnostic.json', {'100_seeds_each':decisions,
            'scope':'Development design calibration only; not 200 Agent research samples or final confirmation'})

    def test_15_actual_model_runtime_payload_no_paid_call(self):
        identity = {'token_allowance':2000000,'max_http_attempts':0,'project_budget_id':'USER-20261022-CRITIC-10M'}
        budget = StudyBudget(self.folder/'actor/common_budget.sqlite', identity, create=True)
        with patch('experiments.insight_research.paired_v01.budget.request_model', side_effect=AssertionError('No paid call in P0')):
            runner = ResearchRun(self.folder/'actor', self.ws, self.cfg['model_config'], budget)
            initial = runner.runtime.initial(); request = runner.runtime.payload(initial)
        from token_budget import reservation_bound
        self.assertFalse(self.ws.db.in_transaction)
        self.assertIn('collect_evidence',encoded(request)); self.assertNotIn('entry_rate',encoded(request))
        self.assertEqual(request['max_tokens'],65536)
        self.assertEqual(budget.snapshot()['http_attempts'],0)
        write_json(self.folder/'startup_probe.json', {'payload_bytes':len(encoded(request).encode()),
            'reservation_bound':reservation_bound(request),'tools':len(self.ws.tools),'new_paid_calls':0,
            'scope':'Actual current self-mode runtime payload; no claim of completed research'})

    def test_16_three_actual_reference_conditions_ground_scoring(self):
        # The three labels below come from actual public observations or their
        # documented absence, not from three arbitrary supplied expected labels.
        reference = []
        for number, (rate, service, capture, limited, expected) in enumerate([
                (20,.4,1,False,'supported'),(20,1,.4,False,'refuted'),(20,1,.4,True,'unresolved')]):
            world = World(seed=89,entry_rate=rate,completion_probability=service,recording_probability=capture,
                          instruments=('observe','capacity_trial','wait') if limited else ('observe','entry_count','flow_audit','capacity_trial','wait'))
            ws = ResearchWorkspace(self.folder/f'unit{number}/researcher','Check register target through received lawful evidence.',world,self.cfg)
            try:
                out = ws.call('collect_evidence',{'operation':'observe' if limited else 'flow_audit','windows':16,'purpose':'P0 reference target check'},'reference')
                rows = self.observations(out); assessment = capture_analysis(rows)
                self.assertEqual(assessment['decision'],expected,assessment)
                reference.append({'expected':expected,'observed_decision':assessment['decision'],'assessment':assessment,
                                  'evidence':out['files'],'scope':'Engineering reference, not Agent output'})
            finally: ws.close()
        self.assertEqual(sum(reference_score(x['expected'],x['observed_decision']) for x in reference),3)
        for constant in ['supported','refuted','unresolved']:
            self.assertEqual(sum(reference_score(x['expected'],constant) for x in reference),1)
        write_json(self.folder/'three_way_reference.json',reference)


def main():
    p = argparse.ArgumentParser(); p.add_argument('--output', required=True); a = p.parse_args()
    output = Path(a.output); output.mkdir(parents=True,exist_ok=False)
    os.environ['GROWTH_P0_OUTPUT'] = str(output/'cases'); before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    after = snapshot(); assert before == after, 'project budget changed during zero-API P0'
    write_json(output/'acceptance.json', {'status':'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'new_paid_calls':0,'budget_unchanged':True,
        'scope':'Actual P0 environment/record tools/sandbox/reference/scoring/runtime startup, not S1/S2 efficacy'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__': main()
