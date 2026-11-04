"""Real workspace/sandbox counterexamples and recovery, not scientific scores."""
from copy import deepcopy
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ..common import Pending, digest, encoded, sha, write_json
from ..composed_world import ComposedWorld
from ..test_acceptance import FixtureJournal, MODEL, raw_call, settings, state, hypothesis
from ..runtime import Journal
from .shared import CheckedWorkspace, CheckedRuntime, lifecycle
from .snapshot import EvidenceView, export_snapshot
from .workspace import CriticWorkspace
from .runtime import CriticRuntime


def review_args(target, **changes):
    return {'phase': 'complete', 'checked_scope': ['限定本次可见原记录'],
        'unchecked_scope': ['没有新增独立观测或机制认证'], 'source_refs': [target],
        'checks_performed': [], 'issues': [], 'open_issue_ids': [],
        'next_action': '将意见交回发现者，按证据推进', **changes}


class M0Tests(unittest.TestCase):
    def setUp(self):
        configured = os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        self.temp = None if configured else tempfile.TemporaryDirectory(prefix='review_')
        self.folder = Path(configured or self.temp.name) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.ws = CheckedWorkspace(self.folder / 'owner', '根据实际证据研究业务关系', ComposedWorld(), settings())
        self.counter = 0; self.critic = None

    def tearDown(self):
        if self.critic: self.critic.close()
        self.ws.close()
        if self.temp: self.temp.cleanup()

    def call(self, name, args):
        self.counter += 1
        return self.ws.call(name, args, 'owner-' + str(self.counter))

    def h(self, **changes): return self.call('save_hypothesis', hypothesis(**changes))

    def source(self, name='business.sqlite'):
        return next(x['ref'] for x in self.ws.context()['public_files'] if Path(x['path']).name == name)

    def assessed(self):
        h = self.h()
        p = self.call('register_test', {'hypothesis_ref': h['ref'], 'prediction': h['prediction'],
            'contrast': '只检查给定记录', 'observation_unit': '记录行', 'allocation_unit': '无分配',
            'analysis': '工程路径，不作机制认证', 'purpose': '实际沙箱检查', 'data_refs': [self.source()],
            'mode': 'observational', 'code': "print('actual observed-data analysis receipt')"})
        r = self.call('run_test', {'plan_ref': p['ref']})
        self.assertTrue(r['ok'], r)
        a = self.call('record_assessment', {'hypothesis_ref': h['ref'], 'result_refs': [r['ref']],
            'status': 'supported', 'prediction_coverage': '仅工程夹具范围', 'rationale': '合成的候选判断，仍需审查',
            'deviations': [], 'counterevidence_refs': [], 'limitations': ['不是科学能力证据']})
        self.assertIn('ref', a, a)
        return h, r, a

    def save(self, **changes):
        hs = [x['ref'] for x in self.ws.records('hypothesis')]
        return self.call('update_research_state', state(active_hypothesis_refs=hs,
            focus_hypothesis_refs=hs, incorporated_result_refs=[x['ref'] for x in self.ws.records('result')], **changes))

    def knowledge(self, **changes):
        return {'kind': 'observation', 'statement': '需核验的研究认识', 'scope': '已见历史',
            'status': 'tentative', 'evidence_refs': [self.source('observed_facts.json')],
            'counterevidence_refs': [], 'hypothesis_refs': [], 'tags': ['history'],
            'research_use': '有条件地指导研究问题', **changes}

    def critic_for(self, target):
        export_snapshot(self.ws, self.folder / 'inputs', target)
        config = settings(); config['limits'].update(token_allowance=500000, max_http_attempts=6,
            max_request_bytes=524288, round_wall_seconds=3600)
        self.critic = CriticWorkspace(self.folder / 'critic', self.folder / 'inputs', config)
        return self.critic

    def test_01_wrong_hypothesis_cannot_borrow_a_strong_assessment(self):
        h, r, a = self.assessed(); other = self.h(statement='另一个研究对象')
        bad = self.knowledge(status='supported_in_scope', hypothesis_refs=[other['ref']], evidence_refs=[a['ref']])
        good = self.knowledge(statement='保留正确绑定的工程记录', status='supported_in_scope',
            hypothesis_refs=[h['ref']], evidence_refs=[a['ref']])
        result = self.save(knowledge_updates=[bad, good])
        self.assertIn('ref', result); self.assertEqual(len(result['knowledge_rejections']), 1)
        self.assertEqual(len(result['knowledge_refs']), 1)
        self.assertEqual(self.ws.record(result['knowledge_refs'][0])['hypothesis_refs'], [h['ref']])
        self.assertEqual(self.ws.state()['ref'], result['ref'])

    def test_02_multi_hypothesis_and_unbound_strong_claims_need_coverage(self):
        h, r, a = self.assessed(); other = self.h()
        entries = [self.knowledge(status='supported_in_scope', evidence_refs=[a['ref']], hypothesis_refs=refs)
            for refs in ([], [h['ref'], other['ref']])]
        result = self.save(knowledge_updates=entries)
        self.assertEqual(len(result['knowledge_rejections']), 2)
        self.assertEqual(result['knowledge_refs'], [])

    def test_03_withdrawn_own_status_not_allowed_in_supported_report(self):
        h, r, a = self.assessed()
        saved = self.save(memory_reviews=[{'target_ref': a['ref'], 'decision': 'withdraw',
            'reason': '先撤回原判断等待核实', 'evidence_refs': [r['ref']]}])
        self.assertIn('ref', saved)
        self.assertFalse(lifecycle(self.ws.db, a['ref'])['eligible_as_current_premise'])
        result = self.call('finish_research', {'assessment_refs': [a['ref']], 'other_hypotheses': {},
            'limitations': ['仍有未决问题'], 'open_questions': [], 'measurement_requests': []})
        self.assertFalse(result['ok']); self.assertIsNone(self.ws.report())
        self.assertEqual(self.ws.record(a['ref'])['status'], 'supported')
        read = self.call('read_memory', {'ref': a['ref']})
        self.assertIn(a['ref'], read['text'])

    def test_04_restore_then_derive_in_same_batch_and_rollback_invalid_state(self):
        h, r, a = self.assessed()
        self.save(memory_reviews=[{'target_ref': a['ref'], 'decision': 'withdraw', 'reason': '待复核', 'evidence_refs': [r['ref']]}])
        review = {'target_ref': a['ref'], 'decision': 'restore', 'reason': '依原证据恢复工程范围判断', 'evidence_refs': [r['ref']]}
        bad = self.call('update_research_state', state(active_hypothesis_refs=['H_missing'], memory_reviews=[review]))
        self.assertFalse(bad['ok']); self.assertEqual(self.ws.review(a['ref'])['status'], 'withdraw')
        result = self.save(memory_reviews=[review], knowledge_updates=[self.knowledge(status='supported_in_scope',
            hypothesis_refs=[h['ref']], evidence_refs=[a['ref']])])
        self.assertEqual(len(result['knowledge_refs']), 1, result)
        k = result['knowledge_refs'][0]
        self.assertTrue(lifecycle(self.ws.db, k)['eligible_as_current_premise'])
        self.assertEqual(self.ws.review(a['ref'])['review_record'], result['ref'])

    def test_05_closeout_keeps_real_reads_sql_python_and_no_new_trial(self):
        h, r, a = self.assessed()
        waiting = self.call('register_test', {'hypothesis_ref': h['ref'], 'prediction': h['prediction'],
            'contrast': '尚未执行', 'observation_unit': '行', 'allocation_unit': '无', 'analysis': '不应运行',
            'purpose': '收尾拒绝新执行', 'data_refs': [self.source()], 'mode': 'observational', 'code': "print('not run')"})
        self.ws.closeout_mode = True
        read = self.call('read_memory', {'ref': h['ref']}); self.assertIn(h['ref'], read['text'])
        sql = self.call('query_data', {'sql': 'select count(*) as n from hourly', 'purpose': '核对已见数据'})
        self.assertEqual(sql['preview'][0][0], 57600)
        result = self.call('run_python', {'code': "print('actual closeout check')", 'purpose': '核验已见资料'})
        self.assertTrue(result['execution']['ok'], result)
        before = self.ws.trials_started()
        self.assertFalse(self.call('save_hypothesis', hypothesis())['ok'])
        worker_before = self.ws.worker.count
        self.assertFalse(self.call('run_test', {'plan_ref': waiting['ref']})['ok'])
        self.assertEqual(self.call('run_test', {'plan_ref': r['plan_ref']})['ref'], r['ref'])
        self.assertEqual(self.ws.worker.count, worker_before)
        self.assertEqual(self.ws.trials_started(), before)
        runtime = CheckedRuntime(self.ws, MODEL, journal=FixtureJournal([]))
        runtime.cp['resource_closeout'] = True
        payload = runtime.payload(runtime.initial())
        tools = {x['function']['name'] for x in payload['tools']}
        self.assertTrue({'read_memory', 'query_data', 'run_python'} <= tools)
        self.assertNotIn('run_test', tools)

    def test_06_reconciliation_feedback_names_actual_legal_fields(self):
        h = self.h()
        p = self.call('register_test', {'hypothesis_ref': h['ref'], 'prediction': h['prediction'],
            'contrast': '库存与记录算术', 'observation_unit': '行', 'allocation_unit': '无', 'analysis': '同源记录',
            'purpose': '字段接口', 'data_refs': [self.source()], 'mode': 'protocol',
            'protocol_id': 'inventory_records', 'outcome_product_ids': ['S03'], 'expected_changed_variables': []})
        r = self.call('run_test', {'plan_ref': p['ref']})
        with self.assertRaises(ValueError) as error:
            self.ws.check_measurement({'source_ref': r['ref'], 'field': 'row_count', 'value': None})
        feedback = json.loads(str(error.exception))
        self.assertIn('difference_units', feedback['available_fields'])
        self.assertEqual(feedback['history_dimensions_source'], self.source('observed_facts.json'))

    def test_07_historical_unlinked_superseded_and_second_page_search(self):
        h, r, a = self.assessed()
        old = self.save(knowledge_updates=[self.knowledge(statement='历史加权方法 weekday', tags=['weekday'])])['knowledge_refs'][0]
        replacement = self.save(knowledge_updates=[self.knowledge(statement='修订方法 weekday', supersedes_ref=old, revision_reason='核实适用范围', tags=['weekday'])])['knowledge_refs'][0]
        for n in range(10): self.save(knowledge_updates=[self.knowledge(statement=f'后续笔记 {n}', tags=['later'])])
        self.save(memory_reviews=[{'target_ref': replacement, 'decision': 'quarantine', 'reason': '有争议', 'evidence_refs': [r['ref']]}])
        critic = self.critic_for(a['ref'])
        first = critic.call('search_memory', {'kind': 'knowledge', 'limit': 8}, 's1')
        second = critic.call('search_memory', {'kind': 'knowledge', 'offset': first['next_offset'], 'limit': 8}, 's2')
        found = {x['ref']: x for x in first['hits'] + second['hits']}
        self.assertIn(old, found); self.assertIn(replacement, found)
        self.assertEqual(found[old]['lifecycle']['replacement_ref'], replacement)
        self.assertEqual(found[replacement]['lifecycle']['status'], 'quarantine')
        exact = critic.call('search_memory', {'query': 'weekday', 'kind': 'knowledge'}, 's3')
        self.assertEqual(exact['total'], 2)
        self.assertEqual(critic.call('search_memory', {'kind': 'knowledge', 'lifecycle_status': 'quarantine'}, 's4')['total'], 1)

    def test_08_projection_excludes_raw_messages_and_filters_nested_read_replies(self):
        h, r, a = self.assessed(); sentinel = 'PRIVATE_REASONING_SENTINEL_8f31'
        write_json(self.ws.private / 'turns/1.json', {'reasoning_content': sentinel})
        with self.ws.db:
            self.ws.event('private-read', 'read_memory', {'ref': 'process:1'}, {'text': sentinel})
        before = sha(self.ws.private / 'records.sqlite')
        critic = self.critic_for(a['ref'])
        self.assertEqual(sha(self.ws.private / 'records.sqlite'), before)
        self.assertNotIn(sentinel.encode(), (critic.view.root / 'catalog.sqlite').read_bytes())
        self.assertFalse(any('private' in p.relative_to(critic.view.root).parts for p in critic.view.root.rglob('*')))
        denied = critic.call('read_memory', {'ref': 'process:1'}, 'private-denied')
        self.assertFalse(denied['ok'])
        action = critic.call('search_memory', {'kind': 'action'}, 'actions')
        self.assertGreater(action['total'], 0)

    def test_09_real_critic_sql_sandbox_sources_and_private_files_are_isolated(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        secret = self.ws.private / 'hidden.txt'; secret.write_text('private')
        own_secret = critic.private / 'hidden.txt'; own_secret.write_text('private')
        public = critic.public / 'business_brief.md'
        before = sha(public)
        tests = [('owner_private', str(secret), False), ('critic_private', str(own_secret), False),
            ('source_write', str(public), True), ('owner_write', str(self.ws.science / 'bad.txt'), True)]
        code = "from pathlib import Path\nimport os,json\nchecks={}\n"
        code += 'tests=' + repr(tests) + "\nfor label,path,write in tests:\n try:\n  Path(path).write_text('bad') if write else Path(path).read_text()\n  checks[label]=False\n except PermissionError: checks[label]=True\n"
        code += "Path(os.environ['WORK_DIR'],'check.json').write_text(json.dumps(checks))\nprint(json.dumps(checks))"
        run = critic.call('run_python', {'code': code, 'purpose': '实际隔离边界'}, 'sandbox')
        self.assertTrue(run['execution']['ok'], run)
        self.assertTrue(all(json.loads(run['execution']['stdout']).values()))
        self.assertEqual(sha(public), before)
        sql = critic.call('query_data', {'sql': 'select sum(sales) as n from hourly', 'purpose': '独立核对'}, 'sql')
        self.assertIn('action_ref', sql)
        for i, statement in enumerate(('delete from hourly', "attach database '/tmp/review.db' as x", "select load_extension('/tmp/x')")):
            self.assertFalse(critic.call('query_data', {'sql': statement, 'purpose': '权限检查'}, 'bad-sql' + str(i))['ok'])
        path = sql['file']['path']
        own_read = critic.call('run_python', {'code': f"from pathlib import Path\nprint(Path({path!r}).read_text())", 'purpose': '读取自己的核验输出'}, 'own-read')
        self.assertTrue(own_read['execution']['ok'], own_read)

    def test_10_review_requires_actual_action_refs_and_keeps_target_binding(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        fake = critic.call('record_review', review_args(a['ref'], checks_performed=[{'action_ref': 'check:invented', 'finding': '假装已复算'}]), 'fake')
        self.assertFalse(fake['ok']); self.assertIsNone(critic.report())
        read = critic.call('read_memory', {'ref': r['ref']}, 'actual-read')
        complete = critic.call('record_review', review_args(a['ref'], checks_performed=[{'action_ref': read['action_ref'], 'finding': '实际展开了原结果'}]), 'review')
        self.assertEqual(complete['target_ref'], a['ref'])
        self.assertEqual(complete['target_version'], digest(self.ws.record(a['ref'])))
        self.assertFalse(complete['scientific_certification'])
        self.assertEqual(critic.call('record_review', review_args(a['ref'], checks_performed=[{'action_ref': read['action_ref'], 'finding': '实际展开了原结果'}]), 'review'), complete)

    def test_11_interrupted_paid_tool_cursor_reuses_actual_execution(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        raw = raw_call('run_python', {'code': "print('one execution')", 'purpose': '恢复检查'}, identifier='single')
        runtime = CriticRuntime(critic, MODEL, journal=FixtureJournal([]))
        runtime.cp['messages'] = runtime.initial(); runtime.accept(raw)
        operation = digest([str(critic.root), 1, 'single'])
        first = critic.call('run_python', {'code': "print('one execution')", 'purpose': '恢复检查'}, operation)
        before = critic.worker.count
        config = critic.settings; critic.close(); self.critic = None
        self.critic = CriticWorkspace(self.folder / 'critic', self.folder / 'inputs', config, reopen=True)
        reopened = CriticRuntime(self.critic, MODEL, journal=FixtureJournal([]))
        reopened.run(0)
        self.assertEqual(self.critic.worker.count, before)
        self.assertEqual(json.loads(reopened.cp['messages'][-1]['content'])['action_ref'], first['action_ref'])
        self.assertIsNone(reopened.cp['pending'])

    def test_12_bad_or_mixed_model_batches_execute_zero_tools(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        runtime = CriticRuntime(critic, MODEL, journal=FixtureJournal([])); runtime.cp['messages'] = runtime.initial()
        raw = raw_call('query_data', {'sql': 'select count(*) from hourly', 'purpose': '不得执行'})
        raw['choices'][0]['finish_reason'] = 'length'; runtime.accept(raw)
        self.assertIsNone(runtime.cp['pending'])
        mixed = raw_call('record_review', review_args(a['ref']))
        mixed['choices'][0]['message']['tool_calls'].extend(raw_call('query_data', {'sql': 'select 1', 'purpose': '不得执行'}, identifier='other')['choices'][0]['message']['tool_calls'])
        runtime.accept(mixed)
        self.assertIsNone(runtime.cp['pending']); self.assertIsNone(critic.report())
        archived = json.loads((critic.private / 'turns/2.json').read_text())
        self.assertEqual(archived, mixed)

    def test_13_checkpoint_compaction_preserves_new_work_and_capacity(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        runtime = CriticRuntime(critic, MODEL, journal=FixtureJournal([])); runtime.cp['messages'] = runtime.initial()
        with self.assertRaises(Pending): runtime.compact()
        runtime.accept(raw_call('record_review', review_args(a['ref'], phase='checkpoint'), identifier='checkpoint'))
        runtime.drain()
        runtime.accept(raw_call('read_memory', {'ref': r['ref']}, identifier='new-work')); runtime.drain()
        suffix = deepcopy(runtime.cp['messages'][2:]); runtime.compact()
        self.assertEqual(runtime.cp['messages'][2:], suffix)
        payload = runtime.payload(); self.assertEqual(payload['max_tokens'], 65536)
        self.assertEqual(payload['thinking']['type'], 'enabled')
        self.assertNotIn('temperature', payload)

    def test_14_snapshot_and_resume_reject_changed_inputs_or_settings(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        settings_before = deepcopy(critic.settings)
        critic.close(); self.critic = None
        changed = deepcopy(settings_before); changed['limits']['token_allowance'] += 1
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            CriticWorkspace(self.folder / 'critic', self.folder / 'inputs', changed, reopen=True)
        target = self.folder / 'inputs/public/business_brief.md'; target.write_text(target.read_text() + '\nchanged')
        with self.assertRaises(Pending): EvidenceView(self.folder / 'inputs')

    def test_15_export_refuses_undrained_owner_and_no_output_is_created(self):
        h, r, a = self.assessed()
        write_json(self.ws.private / 'checkpoint.json', {'pending': {'cursor': 0}})
        with self.assertRaisesRegex(Pending, 'undrained'):
            export_snapshot(self.ws, self.folder / 'not-created', a['ref'])
        self.assertFalse((self.folder / 'not-created').exists())

    def test_16_paid_response_delivery_recovers_without_a_second_request(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        journal = Journal(critic, MODEL)
        runtime = CriticRuntime(critic, MODEL, journal=journal)
        raw = raw_call('record_review', review_args(a['ref']))
        raw['usage'] = {'prompt_tokens': 5, 'completion_tokens': 5, 'total_tokens': 10}
        with patch('experiments.insight_research.runtime.request_model', return_value={'response': raw}), \
             patch.object(runtime, 'accept', side_effect=RuntimeError('simulated crash after durable HTTP response')):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'): runtime.run(1)
        self.assertIsNotNone(journal.state['delivery'])
        config = critic.settings; critic.close(); self.critic = None
        self.critic = CriticWorkspace(self.folder / 'critic', self.folder / 'inputs', config, reopen=True)
        reopened = CriticRuntime(self.critic, MODEL, journal=Journal(self.critic, MODEL))
        with patch('experiments.insight_research.runtime.request_model', side_effect=AssertionError('must not request again')):
            result = reopened.run(0)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(reopened.journal.state['attempts'], 1)
        self.assertEqual(reopened.journal.state['accounted_tokens'], 10)
        self.assertIsNone(reopened.journal.state['delivery'])

    def test_17_query_receipt_recovery_keeps_exact_wire_result(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        args = {'sql': 'select count(*) as n,avg(price) as price from hourly', 'purpose': '保留精确回执'}
        original = critic.call('query_data', args, 'query-recovery')
        # Simulate the outer action transaction being lost after its filesystem
        # receipt: reconstruction must not rerun SQL or change numeric types.
        with critic.db:
            critic.db.execute('DELETE FROM operations WHERE key=?', ('query-recovery',))
            critic.db.execute('DELETE FROM actions WHERE ref=?', (original['action_ref'],))
        recovered = critic.call('query_data', args, 'query-recovery')
        self.assertEqual(encoded(original), encoded(recovered))

    def test_18_plain_text_repair_points_to_real_critic_tools(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        runtime = CriticRuntime(critic, MODEL, journal=FixtureJournal([])); runtime.cp['messages'] = runtime.initial()
        runtime.accept({'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '核验尚未完成'}}]})
        self.assertIn('record_review', runtime.cp['messages'][-1]['content'])
        self.assertNotIn('finish_research', runtime.cp['messages'][-1]['content'])

    def test_19_navigation_views_are_citable_without_exposing_private_process(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        result = critic.call('record_review', review_args(a['ref'], phase='checkpoint',
            source_refs=['directory:results', 'card:' + h['ref']]), 'navigation')
        self.assertEqual(result['phase'], 'checkpoint')
        self.assertIsNone(critic.report())

    def test_20_allocation_cannot_duplicate_or_hide_excess_with_negative_allowance(self):
        from .run import allocation
        manifest = {'tasks': [{'id': name, 'limits': {'token_allowance': 500000, 'max_http_attempts': 6}} for name in ('one', 'two')],
            'phase_token_cap': 1000000, 'all_role_allowances_sum': 1000000}
        study = {'execution': {'runs': [{'task_ids': [name], 'replicate_id': 0} for name in ('one', 'two')]}}
        self.assertEqual(len(allocation(study, manifest)), 2)
        duplicate = deepcopy(study); duplicate['execution']['runs'].append({'task_ids': ['one'], 'replicate_id': 0})
        with self.assertRaises(ValueError): allocation(duplicate, manifest)
        bad = deepcopy(manifest); bad['tasks'][0]['limits']['token_allowance'] = 1500000; bad['tasks'][1]['limits']['token_allowance'] = -500000
        with self.assertRaises(ValueError): allocation(study, bad)
        bad = deepcopy(manifest); bad['tasks'][0]['limits']['max_http_attempts'] = 7
        with self.assertRaises(ValueError): allocation(study, bad)

    def pending_critic(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        runtime = CriticRuntime(critic, MODEL, journal=FixtureJournal([raw_call('read_memory', {'ref': r['ref']})]))
        runtime.run(1)
        write_json(critic.private / 'transport.json', {'attempts': 6, 'accounted_tokens': 1000,
            'inflight': None, 'delivery': None, 'fixture_not_real_usage': True})
        return h, r, a, critic

    def test_21_explicit_continuation_preserves_process_actions_and_usage(self):
        from .continuation import capture, prepare
        h, r, a, critic = self.pending_critic()
        limits = deepcopy(critic.settings['limits']); limits['max_http_attempts'] = 12
        manifest = capture(critic.root, critic.view.root, limits, base=self.folder)
        config = deepcopy(critic.settings); config['limits'] = limits
        destination = self.folder / 'continued'
        prepare(destination, critic.view.root, config, manifest, base=self.folder)
        with sqlite3.connect(destination / 'private/critic.sqlite') as db:
            old_action = db.execute('SELECT ref FROM actions LIMIT 1').fetchone()[0]
        continued = CriticWorkspace(destination, critic.view.root, config, reopen=True)
        try:
            self.assertEqual(json.loads((continued.private / 'transport.json').read_text())['accounted_tokens'], 1000)
            self.assertEqual(continued.context()['continuation']['inherited_http_attempts'], 6)
            args = review_args(a['ref'], checks_performed=[{'action_ref': old_action, 'finding': '继续使用原核验事实'}])
            rt = CriticRuntime(continued, MODEL, journal=FixtureJournal([raw_call('record_review', args)]))
            self.assertEqual(rt.run(1)['status'], 'completed')
            self.assertEqual(rt.cp['responses'], 2)
            self.assertEqual(continued.report()['target_version'], critic.packet['target_version'])
        finally: continued.close()
        self.assertTrue(all(sha(critic.root / n) == v for n, v in manifest['sha256'].items()))

    def test_22_continuation_rejects_reset_new_model_or_changed_parent(self):
        from .continuation import capture, prepare
        h, r, a, critic = self.pending_critic()
        limits = deepcopy(critic.settings['limits']); limits['max_http_attempts'] = 12
        bad = deepcopy(limits); bad['token_allowance'] += 1
        with self.assertRaises(ValueError): capture(critic.root, critic.view.root, bad, base=self.folder)
        bad = deepcopy(limits); bad['max_http_attempts'] = 13
        with self.assertRaises(ValueError): capture(critic.root, critic.view.root, bad, base=self.folder)
        manifest = capture(critic.root, critic.view.root, limits, base=self.folder)
        config = deepcopy(critic.settings); config['limits'] = limits
        different = deepcopy(config); different['model_config']['model'] = 'other-model'
        with self.assertRaises(ValueError): prepare(self.folder / 'bad', critic.view.root, different, manifest, base=self.folder)
        p = critic.private / 'turns/1.json'; p.write_text(p.read_text() + '\n')
        with self.assertRaises(ValueError): prepare(self.folder / 'changed', critic.view.root, config, manifest, base=self.folder)

    def test_23_request_boundary_notice_keeps_prerequisite_tools_and_honest_reason(self):
        h, r, a = self.assessed(); critic = self.critic_for(a['ref'])
        journal = Journal(critic, MODEL); journal.state['attempts'] = 5
        runtime = CriticRuntime(critic, MODEL, journal=journal)
        payload = runtime.prepare_payload(runtime.payload(runtime.initial()))
        self.assertTrue(any('还剩1次请求' in str(m.get('content')) for m in payload['messages']))
        self.assertEqual(len(payload['tools']), 6)
        journal.state['attempts'] = 6
        result = runtime.run(0)
        self.assertIn('cumulative critic HTTP allocation reached', result['reason'])

    def test_24_summary_separates_inherited_and_new_charges(self):
        from .summarize import summarize
        private = self.folder / 'summary/results/continued/critic/private'; private.mkdir(parents=True)
        with sqlite3.connect(private / 'critic.sqlite') as db:
            db.executescript('CREATE TABLE records(kind TEXT,body TEXT); CREATE TABLE actions(body TEXT);')
        write_json(private / 'transport.json', {'attempts': 7, 'accounted_tokens': 1100})
        write_json(private / 'continuation.json', {'inherited_http_attempts': 6, 'inherited_accounted_tokens': 1000})
        result = summarize(self.folder / 'summary')
        self.assertEqual(result['total_new_http_attempts'], 1)
        self.assertEqual(result['total_new_accounted_tokens'], 100)
        self.assertEqual(result['total_accounted_tokens'], 1100)

    def test_25_continuation_excludes_developer_side_files(self):
        from .continuation import capture, prepare
        h, r, a, critic = self.pending_critic()
        (critic.private / 'root_audit.json').write_text('developer-private-sentinel')
        limits = deepcopy(critic.settings['limits']); limits['max_http_attempts'] = 12
        manifest = capture(critic.root, critic.view.root, limits, base=self.folder)
        self.assertNotIn('private/root_audit.json', manifest['sha256'])
        config = deepcopy(critic.settings); config['limits'] = limits
        destination = self.folder / 'isolated'
        prepare(destination, critic.view.root, config, manifest, base=self.folder)
        self.assertFalse((destination / 'private/root_audit.json').exists())


if __name__ == '__main__': unittest.main()
