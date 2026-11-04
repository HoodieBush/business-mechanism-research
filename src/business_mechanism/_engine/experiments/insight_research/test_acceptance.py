"""New-entry controls and actual sandbox checks; scripted actors are fixtures."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .common import ROOT, Pending, digest, encoded, sha
from .contracts import schemas
from .workspace import Workspace
from .runtime import Journal, Runtime
from world import OfficeWorld

MODEL = json.loads((ROOT / 'configs/base_model.json').read_text())


def settings():
    example = json.loads((Path(__file__).parent / 'research.example.json').read_text())
    return {k: example[k] for k in ('research_profile', 'verification_mode', 'limits')} | {'model_config': MODEL}


def hypothesis(**changes):
    return {'kind': 'business', 'statement': '示例柜点记录存在负销量', 'scope': '已公开历史hourly',
        'prediction': 'hourly.sales最小值小于0', 'falsification': '最小值非负',
        'alternatives': ['记录字段均非负；业务差异需要另行研究'], 'evidence_refs': [], **changes}


def state(**changes):
    return {'question': '检查记录后应研究什么', 'why': '区别数据质量与业务关系',
        'understanding': '当前还没有独立业务机制证据', 'active_hypothesis_refs': [],
        'alternative_refs': [], 'evidence_refs': [], 'counterevidence_refs': [],
        'incorporated_result_refs': [], 'recent_change': '初始化或依据真实结果修订',
        'open_questions': ['销量截断如何影响解释'], 'next_action': '继续分析', 'next_reason': '保留竞争解释', **changes}


def raw_call(name, args, identifier='c1', **changes):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': '',
        'reasoning_content': 'fixture reasoning retained', 'tool_calls': [{'id': identifier, 'type': 'function',
            'function': {'name': name, 'arguments': encoded(args)}}]}}], **changes}


class FixtureJournal:
    def __init__(self, actions): self.actions = iter(actions); self.requests = []
    def call(self, payload):
        self.requests.append(deepcopy(payload))
        action = next(self.actions)
        return {'response': action() if callable(action) else action}


class ResearchTests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        self.temp = None if configured else tempfile.TemporaryDirectory(prefix='ir_')
        self.folder = Path(configured or self.temp.name) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.world = OfficeWorld('site_weekday', 9137, 'office-business-v0.4')
        self.ws = Workspace(self.folder / 'workspace', '寻找有数据支持的业务认识', self.world, settings())
        self.counter = 0

    def tearDown(self):
        self.ws.close()
        if self.temp: self.temp.cleanup()

    def call(self, name, args=None, key=None):
        self.counter += 1
        return self.ws.call(name, args or {}, key or str(self.counter))

    def h(self, **changes): return self.call('save_hypothesis', hypothesis(**changes))

    def file(self, name='business.sqlite'):
        return next(x['ref'] for x in self.ws.context()['public_files'] if Path(x['path']).name == name)

    def plan(self, h=None, **changes):
        h = h or self.h()
        args = {'hypothesis_ref': h['ref'], 'prediction': h['prediction'], 'contrast': '最低记录量与0比较',
                'observation_unit': '柜点商品小时记录', 'allocation_unit': '无随机分配',
                'analysis': '报告最小值、总行数；不推断潜在需求', 'purpose': '探索性检查',
                'data_refs': [self.file()], 'mode': 'observational',
                'code': "import os,sqlite3,json\nfrom pathlib import Path\ncon=sqlite3.connect(Path(os.environ['PUBLIC_DIR'])/'business.sqlite')\nprint(json.dumps(con.execute('select min(sales),count(*) from hourly').fetchone()))", **changes}
        return self.call('register_test', args)

    def assess(self, h, r, **changes):
        return self.call('record_assessment', {'hypothesis_ref': h['ref'], 'result_refs': [r['ref']],
            'status': 'refuted', 'prediction_coverage': '只覆盖公开历史的记录最小值',
            'rationale': '实际最小值非负，与负数预测不符', 'deviations': [], 'counterevidence_refs': [r['ref']],
            'limitations': ['工程夹具，不是自主业务机制发现'], **changes})

    def test_01_public_boundary_and_no_role_workflow(self):
        context = self.call('read_context')
        self.assertNotIn('site_weekday', encoded(context))
        self.assertNotIn('manager', [x['function']['name'] for x in schemas()])
        self.assertEqual(len(schemas()), 12)
        self.assertEqual(context['resources']['new_trials_remaining'], 2)
        self.assertNotIn('evaluate_algorithm', encoded(schemas()))

    def test_02_old_sources_unchanged(self):
        before = json.loads((Path(__file__).parent / 'legacy_before_sha256.json').read_text())['sha256']
        self.assertTrue(all(sha(ROOT / p) == h for p, h in before.items()))

    def test_03_sql_read_only_with_actual_receipt(self):
        result = self.call('query_data', {'sql': 'select count(*) as n from hourly', 'purpose': '检查记录量'})
        self.assertGreater(result['preview'][0][0], 0)
        self.assertTrue(self.ws.file(result['receipt']['ref'])[0].exists())
        for sql in ('delete from hourly', "attach database '/tmp/ir.sqlite' as x", "select load_extension('/tmp/x')"):
            self.assertFalse(self.call('query_data', {'sql': sql, 'purpose': '权限检查'})['ok'])

    def test_04_reference_versions_and_immutable_hypotheses(self):
        h = self.h(); revised = self.h(statement='修订的关系', parent_ref=h['ref'])
        self.assertEqual(self.ws.record(h['ref'])['statement'], hypothesis()['statement'])
        self.assertEqual(revised['parent_ref'], h['ref'])
        self.assertFalse(self.h(parent_ref='missing')['ok'])
        p = self.ws.public / 'sites.csv'; p.write_text(p.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'version changed'): self.ws.file(self.file('sites.csv'))

    def test_05_actual_sandbox_read_write_and_process_isolation(self):
        secret = self.ws.private / 'secret.txt'; secret.write_text('not-visible')
        code = '''import os,socket,json
from pathlib import Path
checks={}
for label,path,write in TESTS:
    try:
        Path(path).write_text('bad') if write else Path(path).read_text()
        checks[label]=False
    except PermissionError: checks[label]=True
try:
    socket.create_connection(('127.0.0.1',9),timeout=.1);checks['network']=False
except PermissionError:checks['network']=True
Path(os.environ['WORK_DIR'],'value.txt').write_text('ok')
print(json.dumps(checks))
'''
        protected = [('private', str(secret), False), ('repo', str(ROOT / 'experiments/business_team/world.py'), False),
                     ('public_write', str(self.ws.public / 'sites.csv'), True),
                     ('record_write', str(self.ws.science / 'new.txt'), True)]
        result = self.call('run_python', {'code': 'TESTS=' + repr(protected) + '\n' + code, 'purpose': '实际权限检查'})
        self.assertTrue(result['execution']['ok'], result)
        self.assertTrue(all(json.loads(result['execution']['stdout']).values()))
        self.assertEqual(secret.read_text(), 'not-visible')
        private_read = self.call('read_artifact', {'ref': str(secret)})
        self.assertFalse(private_read['ok'])

    def test_06_real_test_idempotence_and_recording(self):
        h = self.h(); plan = self.plan(h)
        first = self.call('run_test', {'plan_ref': plan['ref']}, 'first')
        second = self.call('run_test', {'plan_ref': plan['ref']}, 'second')
        self.assertEqual(first, second); self.assertTrue(first['ok'])
        self.assertEqual(self.ws.worker.count, 1)
        self.assertEqual(first['evidence_nature'], 'exploratory_seen')
        self.assertTrue(first['actual_execution']['source_reads'])
        self.assertEqual(self.ws.unincorporated()[0]['ref'], first['ref'])

    def test_07_execution_failure_not_scientific_refutation(self):
        h = self.h(); p = self.plan(h, code="raise RuntimeError('fixture failure')")
        r = self.call('run_test', {'plan_ref': p['ref']}); self.assertFalse(r['ok'])
        self.assertFalse(self.assess(h, r)['ok'])
        self.assertEqual(self.assess(h, r, status='unresolved')['status'], 'unresolved')
        new = self.plan(h, parent_plan_ref=p['ref'], code="print('repaired new plan')")
        self.assertNotEqual(p['ref'], new['ref'])
        self.assertFalse(self.ws.record(r['ref'])['ok'])

    def test_08_exact_original_subject_required(self):
        h = self.h(); revised = self.h(parent_ref=h['ref'])
        r = self.call('run_test', {'plan_ref': self.plan(h)['ref']})
        self.assertFalse(self.assess(revised, r)['ok'])
        self.assertEqual(self.assess(h, r)['status'], 'refuted')

    def test_09_actual_supply_protocol_and_trial_cap(self):
        h = self.h()
        for index, sku in enumerate(('S11', 'S12')):
            p = self.plan(h, mode='protocol', code=None, protocol_id='support_supply:' + sku,
                          outcome_product_ids=['S01'], expected_changed_variables=['morning_stock:' + sku])
            self.assertFalse('ok' in p and not p['ok'], p)
            r = self.call('run_test', {'plan_ref': p['ref']})
            self.assertTrue(r['ok']); self.assertEqual(r['evidence_nature'], 'intervention')
            self.assertEqual(self.call('run_test', {'plan_ref': p['ref']}), r)
            summary = r['actual_execution']['summary']
            self.assertEqual(summary['site_clusters'], 8)
            self.assertEqual(summary['actual_supply_by_arm'][1]['stock_levels'], [80])
        third = self.plan(h, mode='protocol', code=None, protocol_id='support_supply:S11',
                          outcome_product_ids=['S01'], expected_changed_variables=['morning_stock:S11'])
        self.assertFalse(self.call('run_test', {'plan_ref': third['ref']})['ok'])
        mismatch = self.plan(h, mode='protocol', code=None, protocol_id='support_supply:S11',
                          outcome_product_ids=['S01'], expected_changed_variables=['morning_stock:S01'])
        self.assertFalse(mismatch['ok'])

    def test_10_reconciliation_is_not_new_measurement(self):
        p = self.plan(mode='protocol', code=None, protocol_id='inventory_records',
                      outcome_product_ids=['S01'], expected_changed_variables=[])
        r = self.call('run_test', {'plan_ref': p['ref']})
        self.assertTrue(r['ok']); self.assertEqual(r['evidence_nature'], 'record_reconciliation')
        self.assertEqual(self.ws.trials_started(), 0)

    def test_11_unincorporated_pinned_and_all_hypotheses_disclosed(self):
        h = self.h(); other = self.h(statement='另一个候选')
        r = self.call('run_test', {'plan_ref': self.plan(h)['ref']})
        a = self.assess(h, r)
        finish = {'assessment_refs': [a['ref']], 'other_hypotheses': {other['ref']: '未检验'},
                  'limitations': ['只做了工程夹具检查'], 'open_questions': [], 'measurement_requests': []}
        self.assertFalse(self.call('finish_research', finish)['ok'])
        self.call('update_research_state', state(active_hypothesis_refs=[h['ref'], other['ref']], incorporated_result_refs=[r['ref']], counterevidence_refs=[r['ref']]))
        self.assertFalse(self.call('finish_research', {**finish, 'other_hypotheses': {}})['ok'])
        report = self.call('finish_research', finish)
        self.assertEqual(report['stage_status'], 'inconclusive')
        with self.assertRaisesRegex(ValueError, 'sealed'): self.h()

    def test_12_failed_transaction_recovers_original_python_receipt(self):
        p = self.plan(); original = self.ws.add
        def crash(kind, body):
            if kind == 'result': raise RuntimeError('simulated interruption after execution')
            return original(kind, body)
        with patch.object(self.ws, 'add', side_effect=crash):
            with self.assertRaises(RuntimeError): self.call('run_test', {'plan_ref': p['ref']})
        r = self.call('run_test', {'plan_ref': p['ref']})
        self.assertTrue(r['ok']); self.assertEqual(self.ws.worker.count, 1)

    def test_13_ambiguous_execution_pauses_without_replay(self):
        p = self.plan(); key = 'test:' + p['ref']
        run = self.ws.worker.directory / 'executions/run_001'; run.mkdir(parents=True)
        from .common import write_json
        write_json(self.ws.private / 'effects' / (digest(key) + '.json'),
                   {'directory': str(run), 'receipt': str(run / 'execution_001.json')})
        with self.assertRaises(Pending): self.call('run_test', {'plan_ref': p['ref']})
        self.assertEqual(self.ws.worker.count, 0)

    def test_14_malformed_and_truncated_batches_execute_nothing(self):
        runtime = Runtime(self.ws, MODEL, journal=FixtureJournal([])); runtime.cp['messages'] = runtime.initial()
        malformed = raw_call('save_hypothesis', hypothesis())
        malformed['choices'][0]['message']['tool_calls'].append({'id': 'c2', 'type': 'function',
             'function': {'name': 'run_python', 'arguments': '{bad'}})
        runtime.accept(malformed); runtime.drain()
        truncated = raw_call('save_hypothesis', hypothesis()); truncated['choices'][0]['finish_reason'] = 'length'
        runtime.accept(truncated); runtime.drain()
        self.assertEqual(self.ws.records('hypothesis'), [])
        self.assertIn('fixture reasoning retained', encoded(runtime.cp))
        self.assertIn('protocol_error', encoded(runtime.cp))

    def test_15_paid_tool_cursor_drains_before_another_model_call(self):
        runtime = Runtime(self.ws, MODEL, journal=FixtureJournal([])); runtime.cp['messages'] = runtime.initial()
        runtime.accept(raw_call('save_hypothesis', hypothesis()))
        recovered = Runtime(self.ws, MODEL, journal=FixtureJournal([]))
        result = recovered.run(0)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(len(self.ws.records('hypothesis')), 1)
        self.assertIsNone(recovered.cp['pending'])
        self.assertEqual(recovered.journal.requests, [])

    def test_16_context_rebuild_preserves_all_predictions_and_counterevidence(self):
        hs = [self.h(statement=f'条件{i}') for i in range(9)]
        self.call('update_research_state', state(active_hypothesis_refs=[h['ref'] for h in hs],
            evidence_refs=[hs[0]['ref']], counterevidence_refs=[hs[8]['ref']]))
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        for i in range(12):
            rt.cp['messages'] += [{'role': 'assistant', 'content': 'old' * 100, 'reasoning_content': str(i)},
                                  {'role': 'user', 'content': 'feedback'}]
        rt.compact()
        self.assertEqual(len(rt.cp['messages'][1]['content'].split('original_question')), 2)
        context = json.loads(rt.cp['messages'][1]['content'])
        self.assertEqual(len(context['active_original_hypotheses']), 9)
        self.assertEqual(context['critical_counterevidence'][0]['ref'], hs[8]['ref'])
        self.assertEqual(sum(m['role'] == 'assistant' for m in rt.cp['messages']), 4)

    def test_17_context_boundary_retains_unincorporated_results(self):
        p = self.plan(); r = self.call('run_test', {'plan_ref': p['ref']})
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        with self.assertRaisesRegex(Pending, 'unincorporated'): rt.compact()
        self.assertEqual(self.ws.unincorporated()[0]['ref'], r['ref'])

    def test_18_memory_owner_pagination_and_originals(self):
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        rt.accept(raw_call('read_context', {})); rt.drain()
        search = self.call('search_memory', {'query': 'fixture reasoning', 'kind': 'process'})
        ref = search['hits'][0]['ref']
        first = self.call('read_memory', {'ref': ref, 'limit': 40})
        second = self.call('read_memory', {'ref': ref, 'offset': first['next_offset'], 'limit': 40})
        self.assertNotEqual(first['text'], second['text'])
        self.assertFalse(self.call('read_artifact', {'ref': ref})['ok'])
        self.assertFalse(self.call('read_memory', {'ref': 'process:../../identity'})['ok'])

    def test_19_identity_frozen_and_private_labels_rejected(self):
        with self.assertRaisesRegex(ValueError, 'neutral'):
            Workspace(self.folder / 'site_weekday_case', 'x', self.world, settings())
        changed = settings(); changed['verification_mode'] = 'independent'
        with self.assertRaises(ValueError): Workspace(self.folder / 'other', 'x', self.world, changed)
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            Workspace(self.ws.root, 'silently changed question', self.world, settings(), reopen=True)

    def test_20_thinking_wire_and_zero_allowance_preflight(self):
        rt = Runtime(self.ws, MODEL)
        payload = rt.payload(rt.initial())
        self.assertEqual(payload['thinking']['type'], 'enabled')
        self.assertEqual(payload['max_tokens'], 65536)
        self.assertNotIn('temperature', payload)
        with patch('experiments.insight_research.runtime.request_model', side_effect=AssertionError('must not send')):
            result = rt.run(1)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(rt.journal.state['attempts'], 0)

    def test_21_scripted_negative_result_changes_question_then_finishes(self):
        def action(name, make_args): return lambda: raw_call(name, make_args(), name)
        def hs(): return self.ws.records('hypothesis')
        def rs(): return self.ws.records('result')
        def assessments(): return self.ws.records('assessment')
        actions = [
            raw_call('save_hypothesis', hypothesis()),
            action('register_test', lambda: {'hypothesis_ref': hs()[0]['ref'], 'prediction': hs()[0]['prediction'],
                'contrast': '最小值与0', 'observation_unit': '小时记录', 'allocation_unit': '无',
                'analysis': '只检查公开记录', 'purpose': '初始探索', 'data_refs': [self.file()], 'mode': 'observational',
                'code': "import os,sqlite3\nfrom pathlib import Path\nprint(sqlite3.connect(Path(os.environ['PUBLIC_DIR'])/'business.sqlite').execute('select min(sales) from hourly').fetchone()[0])"}),
            action('run_test', lambda: {'plan_ref': self.ws.records('plan')[0]['ref']}),
            action('record_assessment', lambda: {'hypothesis_ref': hs()[0]['ref'], 'result_refs': [rs()[0]['ref']],
                'status': 'refuted' if float(rs()[0]['actual_execution']['stdout']) >= 0 else 'unresolved',
                'prediction_coverage': '最低记录值', 'rationale': '依据实际输出', 'deviations': [],
                'counterevidence_refs': [rs()[0]['ref']], 'limitations': ['不能推断需求机制']}),
            action('update_research_state', lambda: state(question='应转向柜点和时段条件的业务分析',
                active_hypothesis_refs=[hs()[0]['ref']],
                incorporated_result_refs=[rs()[0]['ref']], counterevidence_refs=[rs()[0]['ref']],
                recent_change='负销量预测被实际记录反驳，继续研究其他解释')),
            action('save_hypothesis', lambda: hypothesis(statement='修订后的条件关系待测', parent_ref=hs()[0]['ref'])),
            action('finish_research', lambda: {'assessment_refs': [assessments()[0]['ref']],
                'other_hypotheses': {hs()[1]['ref']: '待新测量'}, 'limitations': ['脚本工程夹具，不认证模型研究能力'],
                'open_questions': ['哪些条件关系值得检验'], 'measurement_requests': ['补充能区分竞争解释的观测']}),
        ]
        journal = FixtureJournal(actions)
        result = Runtime(self.ws, MODEL, journal=journal).run(8)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.ws.records('assessment')[0]['status'], 'refuted')
        self.assertEqual(len(hs()), 2)
        self.assertIn('柜点', self.ws.state()['question'])
        self.assertNotIn('evaluate_algorithm', encoded(journal.requests))
        self.assertFalse(self.ws.report()['scientific_certification'])

    def test_22_committed_tool_recovered_after_checkpoint_write_failure(self):
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        rt.accept(raw_call('save_hypothesis', hypothesis()))
        original = self.ws.call
        def after_commit(*args):
            result = original(*args)
            raise Pending('fixture crash before cursor save')
        with patch.object(self.ws, 'call', side_effect=after_commit):
            self.assertEqual(rt.run(0)['status'], 'pending')
        self.assertEqual(len(self.ws.records('hypothesis')), 1)
        restored = Runtime(self.ws, MODEL, journal=FixtureJournal([]))
        restored.run(0)
        self.assertEqual(len(self.ws.records('hypothesis')), 1)
        self.assertEqual(sum(m['role'] == 'tool' for m in restored.cp['messages']), 1)

    def test_23_fixed_view_capacity_is_pending_not_refutation(self):
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        # Explicit test fixture overload; production settings remain identity-frozen.
        with patch.dict(self.ws.settings['limits'], {'max_request_bytes': 10}):
            self.assertEqual(rt.run(1)['status'], 'pending')
        self.assertEqual(self.ws.records('assessment'), [])
        self.assertEqual(rt.journal.requests, [])

    def test_24_journal_paid_delivery_is_recovered_exactly_once(self):
        configured = settings(); configured['limits'] = {**configured['limits'], 'token_allowance': 500000, 'max_http_attempts': 2}
        other = Workspace(self.folder / 'other', 'journal fixture', self.world, configured)
        try:
            journal = Journal(other, MODEL)
            rt = Runtime(other, MODEL, journal=journal); rt.cp['messages'] = rt.initial(); rt.save()
            payload = rt.payload()
            fake = {'response': raw_call('save_hypothesis', hypothesis()) | {'usage': {'total_tokens': 10}}}
            with patch('experiments.insight_research.runtime.request_model', return_value=fake) as transport:
                first = journal.call(payload)
                self.assertEqual(journal.call(payload), first)
                self.assertEqual(transport.call_count, 1)
            # Crash after transport receipt, before accept(): recover response without HTTP.
            restored = Runtime(other, MODEL)
            with patch('experiments.insight_research.runtime.request_model', side_effect=AssertionError('no new request')):
                restored.run(0)
            self.assertEqual(len(other.records('hypothesis')), 1)
            self.assertEqual(restored.journal.state['accounted_tokens'], 10)
            self.assertEqual(restored.journal.state['attempts'], 1)
            self.assertIsNone(restored.journal.state['delivery'])
        finally: other.close()

    def test_25_inflight_transport_without_receipt_not_blindly_retried(self):
        configured = settings(); configured['limits'] = {**configured['limits'], 'token_allowance': 500000, 'max_http_attempts': 2}
        other = Workspace(self.folder / 'other', 'transport fixture', self.world, configured)
        try:
            rt = Runtime(other, MODEL)
            with patch('experiments.insight_research.runtime.request_model', side_effect=RuntimeError('simulated process crash')):
                with self.assertRaises(RuntimeError): rt.run(1)
            with patch('experiments.insight_research.runtime.request_model', side_effect=AssertionError('must not replay')):
                restored = Runtime(other, MODEL)
                self.assertEqual(restored.run(1)['status'], 'pending')
            self.assertEqual(restored.journal.state['attempts'], 1)
            self.assertEqual(other.records('hypothesis'), [])
        finally: other.close()

    def test_26_negative_assessment_survives_without_manual_counter_list(self):
        h = self.h(); r = self.call('run_test', {'plan_ref': self.plan(h)['ref']})
        a = self.assess(h, r)
        self.call('update_research_state', state(active_hypothesis_refs=[h['ref']], incorporated_result_refs=[r['ref']]))
        self.assertEqual(self.ws.context()['registered_counter_assessments'][0]['ref'], a['ref'])

    def test_27_duplicate_ids_and_sole_finish_constraint(self):
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        raw = raw_call('read_context', {})
        raw['choices'][0]['message']['tool_calls'] *= 2
        rt.accept(raw); rt.drain()
        self.assertIsNone(rt.cp['pending'])
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)
        raw = raw_call('finish_research', {'assessment_refs': [], 'other_hypotheses': {},
            'limitations': ['fixture'], 'open_questions': [], 'measurement_requests': []})
        raw['choices'][0]['message']['tool_calls'] += raw_call('read_context', {}, 'c2')['choices'][0]['message']['tool_calls']
        rt.accept(raw); rt.drain(); self.assertIsNone(self.ws.report())

    def test_28_resume_identity_and_operation_signature(self):
        h = self.call('save_hypothesis', hypothesis(), 'fixed')
        self.assertEqual(self.call('save_hypothesis', hypothesis(), 'fixed'), h)
        with self.assertRaisesRegex(ValueError, 'changed arguments'):
            self.call('save_hypothesis', hypothesis(statement='changed'), 'fixed')
        reopened = Workspace(self.ws.root, self.ws.question, self.world, settings(), reopen=True)
        try: self.assertEqual(reopened.record(h['ref']), h)
        finally: reopened.close()

    def test_29_rebuild_retains_new_results_with_prior_understanding(self):
        self.call('update_research_state', state())
        r = self.call('run_test', {'plan_ref': self.plan()['ref']})
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        rt.compact()
        self.assertEqual(json.loads(rt.cp['messages'][1]['content'])['unincorporated_results'][0]['ref'], r['ref'])
        self.assertEqual(self.ws.unincorporated()[0]['ref'], r['ref'])

    def test_30_transport_retry_cap_survives_resume(self):
        journal = FixtureJournal([{'error_type': 'transport'}])
        rt = Runtime(self.ws, MODEL, journal=journal)
        self.assertEqual(rt.run(1)['status'], 'pending')
        restored = Runtime(self.ws, MODEL, journal=FixtureJournal([]))
        self.assertEqual(restored.run(1)['status'], 'pending')
        self.assertEqual(restored.journal.requests, [])

    def test_31_report_separates_business_and_data_quality_claims(self):
        assessments = []
        results = []
        for category in ('business', 'data_quality'):
            h = self.h(kind=category, statement='用于报告分类的夹具主张')
            r = self.call('run_test', {'plan_ref': self.plan(h, code="print('fixture evidence')")['ref']})
            results.append(r['ref'])
            assessments.append(self.assess(h, r, status='supported'))
        self.call('update_research_state', state(active_hypothesis_refs=[h['ref'] for h in self.ws.records('hypothesis')], incorporated_result_refs=results))
        report = self.call('finish_research', {'assessment_refs': [a['ref'] for a in assessments],
            'other_hypotheses': {}, 'limitations': ['仅验证分类，不认证主张真实性'],
            'open_questions': [], 'measurement_requests': []})
        self.assertEqual(report['business_insight_assessment_refs'], [assessments[0]['ref']])
        self.assertEqual(len(report['all_assessment_refs']), 2)
        self.assertFalse(report['scientific_certification'])

    def test_32_bad_envelope_and_call_shapes_recover_without_execution(self):
        rt = Runtime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        rt.accept({'choices': [{'finish_reason': 'stop', 'message': 'invalid'}]})
        raw = raw_call('read_context', {})
        raw['choices'][0]['message']['tool_calls'] = {'unexpected': 'object'}
        rt.accept(raw); rt.drain()
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)
        self.assertEqual(rt.cp['responses'], 2)

    def test_33_stale_runtime_reloads_paid_cursor_under_lock(self):
        stale = Runtime(self.ws, MODEL, journal=FixtureJournal([]))
        owner = Runtime(self.ws, MODEL, journal=FixtureJournal([])); owner.cp['messages'] = owner.initial()
        owner.accept(raw_call('save_hypothesis', hypothesis()))
        stale.run(0)
        self.assertEqual(len(self.ws.records('hypothesis')), 1)
        self.assertEqual(stale.cp['responses'], 1)

    def test_34_new_journal_uses_actual_shared_reserve_settle_boundary(self):
        from unittest.mock import MagicMock
        import model_protocol
        from token_budget import SharedTokenBudget, initialize_budget
        pointer = initialize_budget(self.folder / 'fixture_budget', budget_id='offline-fixture',
            limit_tokens=500000, model=MODEL['model'], base_url=MODEL['base_url'], user_instruction='offline test fixture only')
        configured = settings(); configured['model_config'] = {**MODEL, 'token_budget_pointer': str(pointer)}
        configured['limits'] = {**configured['limits'], 'token_allowance': 500000, 'max_http_attempts': 2}
        other = Workspace(self.folder / 'other', 'reserve-settle fixture', self.world, configured)
        class Response:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return encoded(raw_call('read_context', {}) | {'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10}}).encode()
        try:
            opener = MagicMock()
            def open_request(*args, **kwargs):
                snap = SharedTokenBudget(pointer).snapshot()
                self.assertEqual(snap['attempts_reserved'], 1)
                self.assertGreater(snap['unknown_or_inflight_reserve'], 0)
                return Response()
            opener.open.side_effect = open_request
            with patch.object(model_protocol, 'load_api_key', return_value=''), patch.object(model_protocol.urllib.request, 'build_opener', return_value=opener):
                result = Runtime(other, configured['model_config']).run(1)
            self.assertEqual(result['status'], 'pending')
            self.assertEqual(SharedTokenBudget(pointer).snapshot()['reported_tokens'], 10)
            self.assertEqual(json.loads((other.private / 'transport.json').read_text())['accounted_tokens'], 10)
        finally: other.close()

    def test_35_submitted_source_survives_execution_self_rewrite(self):
        code = "from pathlib import Path\nPath(__file__).write_text('rewritten execution copy')\nprint('original executed')"
        result = self.call('run_python', {'code': code, 'purpose': '审计实际提交源码'})
        self.assertTrue(result['execution']['ok'])
        source, _ = self.ws.file(result['execution']['submitted_source']['ref'])
        self.assertEqual(source.read_text(), code)
        self.assertEqual(Path(result['execution']['code_file']).read_text(), 'rewritten execution copy')

    def test_36_explicit_deferral_bounds_view_and_preserves_originals(self):
        hs = [self.h(statement=f'旧问题{i}' + 'x'*2000) for i in range(9)]
        inactive = {h['ref']: '暂缺区分解释所需测量，保留待研究' for h in hs[:-1]}
        saved = self.call('update_research_state', state(active_hypothesis_refs=[hs[-1]['ref']], inactive_hypotheses=inactive))
        context = self.ws.context()
        self.assertEqual([h['ref'] for h in context['active_original_hypotheses']], [hs[-1]['ref']])
        self.assertEqual(context['deferred_questions']['count'], 8)
        self.assertNotIn('known_hypothesis_refs', context['state'])
        self.assertNotIn('inactive_hypotheses', context['state'])
        self.assertEqual(self.ws.record(saved['ref'])['inactive_hypotheses'], inactive)
        self.assertEqual(self.ws.record(hs[0]['ref'])['statement'], hs[0]['statement'])
        self.assertEqual(len(self.call('search_memory', {'kind': 'hypothesis'})['hits']), 9)
        newest = self.h(statement='新问题还没有写进状态')
        self.assertEqual(len(self.ws.context()['active_original_hypotheses']), 2)
        self.assertIn(newest['ref'], [h['ref'] for h in self.ws.context()['active_original_hypotheses']])

    def test_37_no_silent_deferral_or_hiding_outstanding_evidence(self):
        h = self.h()
        self.assertFalse(self.call('update_research_state', state())['ok'])
        r = self.call('run_test', {'plan_ref': self.plan(h)['ref']})
        deferred = state(inactive_hypotheses={h['ref']: '需要不同测量'})
        self.assertFalse(self.call('update_research_state', deferred)['ok'])
        saved = self.call('update_research_state', {**deferred, 'incorporated_result_refs': [r['ref']]})
        self.assertEqual(saved['inactive_hypotheses'][h['ref']], '需要不同测量')
        self.assertEqual(self.ws.context()['active_original_hypotheses'], [])
        self.assertEqual(self.ws.record(r['ref'])['plan_ref'], self.ws.records('plan')[0]['ref'])


if __name__ == '__main__': unittest.main()
