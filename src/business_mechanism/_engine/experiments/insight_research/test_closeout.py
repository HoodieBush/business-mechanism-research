"""Resource-policy regression and actual SCI027 continuation replay, zero API."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from . import test_continuation as fixtures
from .closeout import CLOSEOUT_TOOLS, CloseoutWorkspace
from .common import ROOT, Pending, encoded, sha
from .composed_world import ComposedWorld
from .continuation import prepare
from .runtime_closeout import CloseoutRuntime, NOTICE
from .test_acceptance import FixtureJournal, MODEL, raw_call, settings, state
from token_budget import reservation_bound


class CloseoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        if output:
            with patch.dict(os.environ, {'INSIGHT_ACCEPTANCE_OUTPUT': str(Path(output) / 'closeout')}):
                fixtures.ContinuationTests.setUpClass.__func__(cls)
        else:
            fixtures.ContinuationTests.setUpClass.__func__(cls)

    tearDownClass = classmethod(fixtures.ContinuationTests.tearDownClass.__func__)
    setUp = fixtures.ContinuationTests.setUp
    tearDown = fixtures.ContinuationTests.tearDown
    call = fixtures.ContinuationTests.call

    def child(self, *, manifest_path=None, root=None, question=None):
        root = root or self.base
        path = manifest_path or self.manifest_path
        self.spec = {'continuation': {'manifest': str(path.relative_to(root)), 'sha256': sha(path)}}
        self.config = settings() | {'continuation': self.spec['continuation']}
        self.config['limits'].update(token_allowance=1337243, max_http_attempts=12,
            max_request_bytes=524288, knowledge_context_bytes=24000)
        self.ws = CloseoutWorkspace(self.folder / 'workspace', question or self.question, ComposedWorld(), self.config)
        prepare(self.ws, self.spec, root=root)
        return self.ws

    def test_e01_read_context_ack_preserves_full_fixed_evidence(self):
        ws = self.child()
        full = ws.context()
        reply = self.call('read_context', {})
        self.assertLess(len(encoded(reply).encode()), 1500)
        self.assertEqual(reply['archive_counts'], full['archive_counts'])
        self.assertEqual(reply['unincorporated_result_refs'], [r['ref'] for r in full['unincorporated_results']])
        # The read itself adds a lawful process event; compare the current
        # cards rather than requiring their process counts to stay stale.
        full = ws.context()
        context = json.loads(CloseoutRuntime(ws, MODEL).initial()[1]['content'])
        self.assertEqual(context['hypothesis_cards'], full['hypothesis_cards'])
        self.assertEqual(context['unincorporated_results'], full['unincorporated_results'])
        self.assertEqual(len(ws.tool_schemas()), 12)

    def test_e02_budget_transition_is_latched_on_wire_and_reopen(self):
        ws = self.child()
        runtime = CloseoutRuntime(ws, MODEL)
        runtime.cp['messages'] = runtime.initial()
        amount = reservation_bound(runtime.payload()) * 2
        with patch.object(runtime.journal, 'snapshot', return_value={'remaining_admission_tokens': amount}):
            payload = runtime.prepare_payload(runtime.payload())
        self.assertEqual({t['function']['name'] for t in payload['tools']}, CLOSEOUT_TOOLS)
        self.assertTrue(runtime.cp['resource_closeout'])
        self.assertTrue(ws.closeout_mode)
        self.assertEqual(payload['max_tokens'], 65536)
        self.assertEqual(payload['thinking']['type'], 'enabled')
        self.assertIn(NOTICE, [m.get('content') for m in payload['messages']])
        ws.close()
        self.ws = CloseoutWorkspace(self.folder / 'workspace', self.question, ComposedWorld(), self.config, reopen=True)
        prepare(self.ws, self.spec, root=self.base)
        reopened = CloseoutRuntime(self.ws, MODEL)
        with patch.object(reopened.journal, 'snapshot', return_value={'remaining_admission_tokens': 10000000}):
            again = reopened.prepare_payload(reopened.payload())
        self.assertEqual({t['function']['name'] for t in again['tools']}, CLOSEOUT_TOOLS)

    def test_e03_generous_normal_phase_keeps_all_tools_and_capacity(self):
        ws = self.child()
        runtime = CloseoutRuntime(ws, MODEL)
        runtime.cp['messages'] = runtime.initial()
        with patch.object(runtime.journal, 'snapshot', return_value={'remaining_admission_tokens': 10000000}):
            payload = runtime.prepare_payload(runtime.payload())
        self.assertEqual(len(payload['tools']), 12)
        self.assertFalse(ws.closeout_mode)
        self.assertEqual(ws.settings['limits']['max_request_bytes'], 524288)
        self.assertEqual(ws.settings['limits']['knowledge_context_bytes'], 24000)

    def test_e04_server_blocks_optional_work_without_running_python(self):
        ws = self.child()
        ws.closeout_mode = True
        before = ws.worker.count
        with patch.object(ws.worker, 'run', side_effect=AssertionError('no new computation may execute')):
            result = self.call('run_python', {'code': "print('must not run')", 'purpose': 'optional work'})
        self.assertFalse(result['ok'])
        self.assertIn('Save uncertainties', result['error'])
        self.assertEqual(ws.worker.count, before)
        self.assertEqual(ws.trials_started(), 1)
        self.assertFalse(self.call('read_context', {})['ok'])

    def test_e05_actual_SCI027_chain_retains_all_35_responses_and_cost(self):
        path = ROOT / 'experiments/insight_research/review/continuation_20261021/SCI027_parent_manifest.json'
        manifest = json.loads(path.read_text())
        ws = self.child(manifest_path=path, root=ROOT, question=manifest['identity']['question'])
        self.assertEqual(ws.trials_started(), 1)
        self.assertEqual(ws.worker.count, 13)
        self.assertEqual(CloseoutRuntime(ws, MODEL).cp['responses'], 35)
        self.assertEqual(ws.context()['continuation']['prior_reported_tokens'], 1798784)
        self.assertEqual(len(ws.unincorporated()), 2)
        for n, version in manifest['sha256'].items():
            if n.startswith(('public/', 'science/')):
                self.assertEqual(sha(ws.root / n), version)
        self.assertEqual(len(list((ws.private / 'turns').glob('*.json'))), 35)

    def test_e06_latched_script_saves_uncertainty_compacts_and_reports(self):
        ws = self.child()
        hs = [h['ref'] for h in self.hypotheses]
        rs = [r['ref'] for r in self.results]
        def assess():
            calls = []
            for h, r in zip(hs, rs):
                args = {'hypothesis_ref': h, 'result_refs': [r], 'status': 'unresolved',
                    'prediction_coverage': '脚本只检查记录和资源路径', 'rationale': '尚需科学核验，不能认定支持',
                    'deviations': [], 'counterevidence_refs': [], 'limitations': ['脚本而非真实模型判断']}
                calls.extend(raw_call('record_assessment', args, identifier=h)['choices'][0]['message']['tool_calls'])
            return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': '', 'tool_calls': calls}}]}
        def save():
            return raw_call('update_research_state', state(active_hypothesis_refs=hs,
                focus_hypothesis_refs=hs, evidence_refs=rs, incorporated_result_refs=rs,
                understanding='当前仅有范围内的结果，保留科学疑点，下批次需核实'))
        def finish():
            return raw_call('finish_research', {'assessment_refs': [a['ref'] for a in ws.records('assessment')],
                'other_hypotheses': {}, 'limitations': ['仅脚本流程'], 'open_questions': ['进一步核验原预测覆盖'], 'measurement_requests': []})
        journal = FixtureJournal([assess, save, finish])
        runtime = CloseoutRuntime(ws, MODEL, journal=journal)
        with patch.object(runtime, 'remaining', return_value=400000):
            runtime.run(2)
            runtime.compact()
            self.assertEqual(runtime.run(1)['status'], 'completed')
        self.assertTrue(runtime.cp['resource_closeout'])
        self.assertEqual(ws.report()['stage_status'], 'inconclusive')
        for request in journal.requests:
            self.assertEqual({t['function']['name'] for t in request['tools']}, CLOSEOUT_TOOLS)
        self.assertEqual(ws.trials_started(), 1)

    def test_e07_unaffordable_unsaved_suffix_reports_budget_not_context(self):
        ws = self.child()
        runtime = CloseoutRuntime(ws, MODEL)
        runtime.cp['messages'] = runtime.initial()
        before = deepcopy(runtime.cp['messages'])
        with patch.object(runtime.journal, 'snapshot', return_value={'remaining_admission_tokens': 1}):
            with self.assertRaisesRegex(Pending, 'token admission.*not the model context limit'):
                runtime.prepare_payload(runtime.payload())
        self.assertEqual(runtime.cp['messages'], before)
        self.assertTrue(ws.checkpoint_work()['pending'])


if __name__ == '__main__':
    unittest.main()
