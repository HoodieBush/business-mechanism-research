"""Research-memory contracts, scaling, reconstruction and actual computations."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .common import ROOT, Pending, digest, encoded, sha
from .memory import MemoryWorkspace
from .runtime_memory import MemoryRuntime, MemoryJournal, reconstruct_request
from .test_acceptance import MODEL, settings, hypothesis, state, raw_call, FixtureJournal
from . import test_acceptance as fixtures
from world import OfficeWorld


class MemoryTests(unittest.TestCase):
    call = fixtures.ResearchTests.call
    h = fixtures.ResearchTests.h
    file = fixtures.ResearchTests.file
    plan = fixtures.ResearchTests.plan
    assess = fixtures.ResearchTests.assess

    def setUp(self):
        configured = os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        self.temp = None if configured else tempfile.TemporaryDirectory(prefix='im_')
        self.folder = Path(configured or self.temp.name) / self._testMethodName
        self.folder.mkdir(parents=True, exist_ok=False)
        self.world = OfficeWorld('site_weekday', 9137, 'office-business-v0.4')
        self.ws = MemoryWorkspace(self.folder / 'workspace', '研究库存记录和业务关系', self.world, settings())
        self.counter = 0

    def tearDown(self):
        self.ws.close()
        if self.temp: self.temp.cleanup()

    def knowledge(self, **changes):
        return {'kind': 'provided_rule', 'statement': '库存是时点状态，跨小时加总不能解释为晨间配货',
            'scope': '公开字段契约中的opening_stock', 'status': 'provided',
            'evidence_refs': [self.file('data_dictionary.json')], 'counterevidence_refs': [],
            'hypothesis_refs': [], 'tags': ['库存', 'opening_stock'],
            'research_use': '提出供给解释前核查分析单位', 'supersedes_ref': None, 'revision_reason': '', **changes}

    def save_state(self, h=None, **changes):
        active = [h['ref']] if h else []
        return self.call('update_research_state', state(active_hypothesis_refs=active,
            focus_hypothesis_refs=active, **changes))

    def test_01_cards_keep_opposing_judgments_and_full_process(self):
        h = self.h(); p = self.plan(h); r = self.call('run_test', {'plan_ref': p['ref']})
        negative = self.assess(h, r)
        positive = self.assess(h, r, status='supported', rationale='夹具故意提交相反判断，不认证科学正确')
        card = self.ws.card(h['ref'])
        self.assertEqual({a['status'] for a in card['latest_assessments_by_status']}, {'supported', 'refuted'})
        self.assertEqual(card['original_hypothesis']['prediction'], h['prediction'])
        self.assertGreater(card['archive_counts']['process'], 0)
        self.assertEqual(card['full_process']['hypothesis_ref'], h['ref'])
        self.assertEqual(self.ws.record(negative['ref'])['status'], 'refuted')

    def test_02_knowledge_auto_retrieved_from_exact_focus(self):
        h = self.h()
        saved = self.save_state(h, knowledge_updates=[self.knowledge(hypothesis_refs=[h['ref']])],
                                hypothesis_notes={h['ref']: '先检查计量单位，尚无业务关系结论'})
        context = self.ws.context()
        self.assertEqual(context['research_knowledge'][0]['ref'], saved['knowledge_refs'][0])
        self.assertEqual(context['research_knowledge'][0]['status'], 'provided')
        self.assertEqual(context['hypothesis_cards'][0]['working_note']['source_state'], saved['ref'])
        self.assertIn('card:' + h['ref'], context['memory_selection']['required_refs'])

    def test_03_incremental_revision_retains_old_evidence(self):
        original = self.save_state(knowledge_updates=[self.knowledge()])['knowledge_refs'][0]
        revised = self.save_state(knowledge_updates=[self.knowledge(supersedes_ref=original,
            statement='修订说明：晨间量取09点各SKU首行，其他时点另按研究目标处理', revision_reason='明确适用时间粒度')])['knowledge_refs'][0]
        refs = {x['ref'] for x in self.call('search_memory', {'kind': 'knowledge'})['hits']}
        self.assertIn(revised, refs); self.assertNotIn(original, refs)
        self.assertEqual(self.ws.record(original)['statement'], self.knowledge()['statement'])
        self.assertFalse(self.save_state(knowledge_updates=[self.knowledge(supersedes_ref=original, revision_reason='重复替换旧版')])['ok'])

    def test_04_unsupported_memory_status_rejected(self):
        result = self.save_state(knowledge_updates=[self.knowledge(kind='relationship', status='supported_in_scope')])
        self.assertFalse(result['ok'])
        self.assertEqual(self.ws.records('knowledge'), [])
        self.assertFalse(self.save_state(knowledge_updates=[self.knowledge(kind='relationship', status='provided')])['ok'])

    def test_05_exploration_before_hypothesis_is_linked(self):
        query = self.call('query_data', {'sql': 'select min(sales) as minimum from hourly', 'purpose': '初始记录探索'})
        h = self.h(evidence_refs=[query['receipt']['ref']])
        hits = self.call('search_memory', {'kind': 'process', 'hypothesis_ref': h['ref']})['hits']
        originals = [json.loads(self.call('read_memory', {'ref': x['ref']})['text']) for x in hits]
        self.assertIn('query_data', [x['tool'] for x in originals])
        self.assertTrue(any(x['result'].get('preview') == [[0]] for x in originals))
        self.ws.rebuild_index()
        self.assertTrue(self.ws.search(kind='process', hypothesis_ref=h['ref'])['hits'])

    def test_06_scoped_indexed_search_and_chinese_tags(self):
        a = self.h(statement='alpha-pattern', tags=['opening_stock'])
        b = self.h(statement='beta-pattern', tags=['其他'])
        with patch.object(self.ws, 'records', side_effect=AssertionError('no full archive scanning')):
            result = self.call('search_memory', {'kind': 'card', 'query': 'alpha-pattern', 'tags': ['opening_stock']})
        self.assertEqual(result['hits'][0]['ref'], 'card:' + a['ref'])
        self.call('update_research_state', state(active_hypothesis_refs=[a['ref'], b['ref']],
                  focus_hypothesis_refs=[a['ref']], knowledge_updates=[self.knowledge(hypothesis_refs=[a['ref']])]))
        selected = self.call('search_memory', {'kind': 'knowledge', 'query': '库存', 'hypothesis_ref': a['ref']})
        self.assertEqual(selected['total'], 1)
        self.assertEqual(self.call('search_memory', {'kind': 'knowledge', 'hypothesis_ref': b['ref']})['total'], 0)
        (self.ws.private / 'turns').mkdir(exist_ok=True)
        (self.ws.private / 'turns/999.json').write_text('not JSON; default retrieval must never open raw turns')
        self.assertFalse(self.call('search_memory', {'query': 'raw thoughts'})['scope']['raw_model_thoughts_searched'])

    def test_07_state_storage_linear_and_view_bounded(self):
        previous = None
        sizes = []
        for i in range(140):
            h = self.h(statement='历史候选问题' + str(i))
            paused = {previous['ref']: '资料不足，暂存待进一步测量'} if previous else {}
            receipt = self.save_state(h, inactive_hypotheses=paused)
            saved = self.ws.record(receipt['ref'])
            self.assertNotIn('known_hypothesis_refs', saved)
            self.assertLessEqual(len(saved['inactive_hypotheses']), 1)
            sizes.append(len(encoded(saved).encode())); previous = h
        self.assertLess(max(sizes)-min(sizes), 400)
        with patch.object(self.ws, 'records', side_effect=AssertionError('no full-history context scan')):
            context = self.ws.context()
        self.assertEqual(len(context['hypothesis_cards']), 1)
        self.assertLess(len(encoded(context).encode()), 15000)
        self.assertEqual(self.call('search_memory', {'kind': 'card', 'limit': 3})['total'], 140)

    def test_08_changed_source_is_review_not_refutation(self):
        q = self.call('query_data', {'sql': 'select count(*) from hourly', 'purpose': 'source version fixture'})
        saved = self.save_state(knowledge_updates=[self.knowledge(kind='observation', status='tentative', evidence_refs=[q['file']['ref']])])
        source, _ = self.ws.file(q['file']['ref']); source.write_text('changed\n')
        view = self.ws.knowledge_view(saved['knowledge_refs'][0])
        self.assertEqual(view['source_state'], 'needs_review'); self.assertEqual(view['status'], 'tentative')

    def test_09_duplicate_operation_does_not_duplicate_process(self):
        args = hypothesis()
        one = self.call('save_hypothesis', args, 'same'); two = self.call('save_hypothesis', args, 'same')
        self.assertEqual(one, two)
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM events').fetchone()[0], 1)

    def test_10_index_rebuild_preserves_cards_and_revisions(self):
        h = self.h()
        saved = self.save_state(h, knowledge_updates=[self.knowledge(hypothesis_refs=[h['ref']])], hypothesis_notes={h['ref']: '等待检验'})
        original = self.ws.card(h['ref'])
        self.ws.rebuild_index()
        self.assertEqual(self.ws.card(h['ref']), original)
        self.assertEqual(self.ws.context()['research_knowledge'][0]['ref'], saved['knowledge_refs'][0])

    def test_11_message_objects_reconstruct_thinking_without_copies(self):
        journal = MemoryJournal(self.ws, MODEL)
        rt = MemoryRuntime(self.ws, MODEL, journal=journal)
        first = rt.payload(rt.initial())
        journal.persist_request(1, first)
        second = deepcopy(first); second['messages'].append({'role': 'assistant', 'content': 'step', 'reasoning_content': 'retained thinking'})
        journal.persist_request(2, second)
        self.assertEqual(reconstruct_request(self.ws.private, 2), second)
        self.assertEqual(len(list((self.ws.private / 'message_objects').glob('*.json'))), 3)
        journal.persist_response(2, {'request': second, 'response': {'usage': {'total_tokens': 1}}})
        self.assertNotIn('request', json.loads((self.ws.private / 'http/2.json').read_text()))
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM retrievals').fetchone()[0], 2)

    def test_12_memory_context_survives_new_window_and_drives_revision_fixture(self):
        h = self.h(kind='data_quality'); p = self.plan(h); r = self.call('run_test', {'plan_ref': p['ref']})
        a = self.assess(h, r)
        saved = self.save_state(h, incorporated_result_refs=[r['ref']], counterevidence_refs=[r['ref']],
            hypothesis_notes={h['ref']: '负记录解释被否定，继续检查其他解释'},
            knowledge_updates=[self.knowledge(kind='observation', status='tentative',
                statement='当前最低记录销量为0，负数记录解释被反驳；不解决库存截断问题',
                evidence_refs=[a['ref']], hypothesis_refs=[h['ref']])])
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        rt.cp['messages'] += [{'role': 'assistant', 'content': 'old material', 'reasoning_content': 'old reasoning'}, {'role': 'user', 'content': 'feedback'}]
        rt.compact()
        context = json.loads(rt.cp['messages'][1]['content'])
        self.assertEqual(context['hypothesis_cards'][0]['original_hypothesis']['prediction'], h['prediction'])
        self.assertEqual(context['hypothesis_cards'][0]['latest_assessments_by_status'][0]['status'], 'refuted')
        memory = saved['knowledge_refs'][0]
        new = self.h(statement='待检验的库存条件关系', parent_ref=h['ref'], used_memory_refs=[memory])
        self.assertEqual(new['used_memory_refs'], [memory])
        self.assertEqual(self.ws.record(h['ref'])['prediction'], h['prediction'])

    def test_13_unincorporated_results_cannot_be_hidden_by_focus(self):
        h = self.h(); r = self.call('run_test', {'plan_ref': self.plan(h)['ref']})
        self.assertFalse(self.save_state(inactive_hypotheses={h['ref']: '先研究别的问题'})['ok'])
        context = self.ws.context()
        self.assertEqual(context['unincorporated_results'][0]['ref'], r['ref'])
        self.assertEqual(context['hypothesis_cards'][0]['original_hypothesis']['ref'], h['ref'])

    def test_14_actual_model_tool_event_links_owner_response(self):
        h = self.h(); self.save_state(h)
        journal = FixtureJournal([raw_call('query_data', {'sql': 'select min(sales) from hourly', 'purpose': '记录下界检查'})])
        result = MemoryRuntime(self.ws, MODEL, journal=journal).run(1)
        self.assertEqual(result['status'], 'pending')
        hits = self.call('search_memory', {'kind': 'process', 'hypothesis_ref': h['ref']})['hits']
        bodies = [json.loads(self.call('read_memory', {'ref': x['ref']})['text']) for x in hits if x['ref'].startswith('event:')]
        query = next(x for x in bodies if x['tool'] == 'query_data')
        self.assertEqual(query['model_response_ref'], 'process:1')
        self.assertEqual(query['result']['preview'], [[0]])
        self.assertIn('fixture reasoning retained', self.call('read_memory', {'ref': 'process:1'})['text'])

    def test_15_admission_compaction_keeps_fixed_memory(self):
        from token_budget import reservation_bound
        h = self.h(); self.save_state(h)
        journal = MemoryJournal(self.ws, MODEL)
        rt = MemoryRuntime(self.ws, MODEL, journal=journal); rt.cp['messages'] = rt.initial()
        remaining = reservation_bound(rt.payload()) + 1000
        rt.cp['messages'] += [{'role': 'assistant', 'content': 'optional old history ' * 1500, 'reasoning_content': 'retained in archive'},
                              {'role': 'user', 'content': 'old feedback'}]
        with patch.dict(self.ws.settings['limits'], {'token_allowance': 1000000}), patch.object(journal, 'snapshot', return_value={'remaining_admission_tokens': remaining}):
            payload = rt.prepare_payload(rt.payload())
        self.assertLessEqual(reservation_bound(payload), remaining)
        self.assertEqual(json.loads(payload['messages'][1]['content'])['hypothesis_cards'][0]['original_hypothesis']['ref'], h['ref'])

    def test_16_actual_sandbox_cannot_read_memory_database(self):
        private = self.ws.private / 'records.sqlite'
        code = 'from pathlib import Path\ntry:\n Path(' + repr(str(private)) + ").read_bytes()\n print('LEAK')\nexcept PermissionError:\n print('DENIED')"
        result = self.call('run_python', {'code': code, 'purpose': '检查记忆和过程的实际读取边界'})
        self.assertTrue(result['execution']['ok'])
        self.assertEqual(result['execution']['stdout'].strip(), 'DENIED')
        self.assertFalse(self.call('read_memory', {'ref': str(private)})['ok'])

    def test_17_high_context_without_results_does_not_request_maintenance(self):
        self.save_state()
        journal = FixtureJournal([raw_call('query_data', {
            'sql': 'select count(*) from hourly', 'purpose': '继续已有研究'})])
        rt = MemoryRuntime(self.ws, MODEL, journal=journal)
        rt.cp['messages'] = rt.initial()
        original = len(encoded(rt.payload()).encode())
        rt.cp['messages'].append({'role': 'assistant', 'content': 'x' * 16000})
        size = len(encoded(rt.payload()).encode())
        self.ws.settings['limits']['max_request_bytes'] = size + 1500
        self.assertGreater(size, self.ws.settings['limits']['max_request_bytes'] * .70)
        self.assertGreater(size, original)
        rt.save(); rt.run(1)
        sent = journal.requests[0]
        self.assertEqual(sent['messages'][-1]['role'], 'assistant')
        self.assertNotIn('上下文接近保护边界', encoded(sent))
        self.assertEqual(len(self.ws.records('state')), 1)
        self.assertEqual(self.ws.search(kind='process', query='继续已有研究')['total'], 1)

    def test_18_small_state_receipt_keeps_full_readable_original(self):
        understanding = '完整认识与条件保存在原件中。' * 100
        receipt = self.save_state(understanding=understanding,
                                  knowledge_updates=[self.knowledge()])
        self.assertLess(len(encoded(receipt).encode()), 1000)
        self.assertNotIn('understanding', receipt)
        original = json.loads(self.call('read_memory', {'ref': receipt['ref'], 'limit': 12000})['text'])
        self.assertEqual(original['understanding'], understanding)
        self.assertEqual(original['knowledge_refs'], receipt['knowledge_refs'])
        self.assertEqual(self.ws.context()['state']['understanding'], understanding)

    def test_19_new_window_keeps_actual_session_and_next_action(self):
        next_action = '继续核对公开记录的计量单位，再选择可区分竞争解释的分析'
        saved = self.save_state(next_action=next_action)
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([]))
        rt.cp['responses'] = 5
        rt.cp['messages'] = rt.initial() + [{'role': 'assistant', 'content': '已完成读取'}]
        rt.compact()
        context = json.loads(rt.cp['messages'][1]['content'])
        self.assertTrue(context['session_progress']['continuing_same_research'])
        self.assertEqual(context['session_progress']['responses_completed'], 5)
        self.assertEqual(rt.cp['context_windows'], 1)
        self.assertEqual(context['state']['ref'], saved['ref'])
        self.assertEqual(context['state']['next_action'], next_action)
        self.assertIsNone(rt.context_notice())

    def test_20_actual_outstanding_result_remains_visible_to_capacity_notice(self):
        h = self.h(); r = self.call('run_test', {'plan_ref': self.plan(h)['ref']})
        self.save_state(h)
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([]))
        self.assertIn('unincorporated_results', rt.context_notice())
        view = json.loads(rt.initial()[1]['content'])
        self.assertEqual(view['unincorporated_results'][0]['ref'], r['ref'])
        self.assertEqual(view['hypothesis_cards'][0]['original_hypothesis']['prediction'], h['prediction'])
        self.save_state(h, incorporated_result_refs=[r['ref']])
        self.assertIsNone(rt.context_notice())

    def test_21_unrecorded_hypothesis_still_requires_source_linked_state(self):
        self.h()
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([]))
        self.assertIn('已有假说', rt.context_notice())
        rt.cp['messages'] = rt.initial()
        with self.assertRaises(Pending): rt.compact()

    def test_22_pre_hypothesis_read_gets_one_work_checkpoint_not_empty_audit(self):
        self.call('read_artifact', {'ref': self.file('business_brief.md')})
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([]))
        self.assertTrue(self.ws.checkpoint_work()['pending'])
        self.assertIn('保存', rt.context_notice())
        self.assertNotIn('吸收未决检验结果', rt.context_notice())
        self.save_state(evidence_refs=[self.file('business_brief.md')])
        self.call('read_context'); self.call('search_memory', {'kind': 'result'})
        self.assertFalse(self.ws.checkpoint_work()['pending'])
        self.assertIsNone(rt.context_notice())

    def test_23_unsaved_exploration_cannot_silently_disappear_at_compaction(self):
        self.call('query_data', {'sql': 'select count(*) from hourly', 'purpose': '首个假说前的真实探索'})
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([]))
        rt.cp['messages'] = rt.initial() + [{'role': 'assistant', 'content': '尚未保存的探索思路'}]
        original = deepcopy(rt.cp['messages'])
        with self.assertRaises(Pending): rt.compact()
        self.assertEqual(rt.cp['messages'], original)
        self.assertEqual(rt.cp['context_windows'], 0)

    def test_24_saved_pre_hypothesis_observation_survives_compaction(self):
        result = self.call('query_data', {'sql': 'select min(sales) from hourly', 'purpose': '首个假说前观察'})
        self.save_state(understanding='当前公开记录的最小销量为0，尚无潜在需求结论',
            evidence_refs=[result['receipt']['ref']], next_action='研究库存截断的竞争解释')
        rt = MemoryRuntime(self.ws, MODEL, journal=FixtureJournal([])); rt.cp['messages'] = rt.initial()
        rt.compact(); context = json.loads(rt.cp['messages'][1]['content'])
        self.assertIn('最小销量为0', context['state']['understanding'])
        self.assertFalse(context['uncheckpointed_work']['pending'])
        self.assertEqual(context['state']['evidence_refs'], [result['receipt']['ref']])

    def test_25_failed_checkpoint_does_not_clear_new_work(self):
        self.call('read_artifact', {'ref': self.file('business_brief.md')})
        rejected = self.save_state(evidence_refs=['file:missing'])
        self.assertFalse(rejected['ok'])
        self.assertTrue(self.ws.checkpoint_work()['pending'])
        self.ws.rebuild_index()
        work = self.ws.checkpoint_work()
        self.assertTrue(work['pending']); self.assertEqual(len(work['recent_work']), 1)
        self.assertEqual(work['recent_work'][0]['evidence_refs'], [self.file('business_brief.md')])


    def checkpoint_then_query(self):
        journal = FixtureJournal([
            raw_call('update_research_state', state(next_action='执行计量检查')),
            raw_call('query_data', {'sql': 'select min(sales) from hourly', 'purpose': '检查点后的真实观察'})])
        rt = MemoryRuntime(self.ws, MODEL, journal=journal)
        rt.cp['messages'] = rt.initial() + [{'role': 'assistant', 'content': '已在检查点吸收的早期长对话' * 100}]
        rt.save(); rt.run(2)
        return rt

    def test_26_compaction_keeps_whole_unsaved_suffix_after_checkpoint(self):
        rt = self.checkpoint_then_query()
        previous = deepcopy(rt.cp['messages'])
        anchor = next(i for i,m in enumerate(previous) if m['role']=='assistant' and
                      any(c['function']['name']=='update_research_state' for c in m.get('tool_calls',[])))
        rt.compact()
        self.assertEqual(rt.cp['messages'][2:], previous[anchor:])
        self.assertNotIn('早期长对话', encoded(rt.cp['messages']))
        self.assertTrue(json.loads(rt.cp['messages'][1]['content'])['uncheckpointed_work']['pending'])
        self.assertIn('检查点后的真实观察', encoded(rt.cp['messages']))

    def test_27_oversized_unsaved_suffix_still_preserves_original(self):
        rt = self.checkpoint_then_query(); previous = deepcopy(rt.cp['messages'])
        self.ws.settings['limits']['max_request_bytes'] = len(encoded(rt.payload(rt.initial())).encode()) + 100
        with self.assertRaises(Pending): rt.compact()
        self.assertEqual(rt.cp['messages'], previous)

    def test_28_budget_pressure_cannot_drop_unsaved_suffix(self):
        from token_budget import reservation_bound
        rt = self.checkpoint_then_query(); journal = MemoryJournal(self.ws, MODEL); rt.journal = journal
        remaining = reservation_bound(rt.payload(rt.initial()))
        with patch.dict(self.ws.settings['limits'], {'token_allowance': 1000000}), patch.object(journal, 'snapshot', return_value={'remaining_admission_tokens': remaining}):
            with self.assertRaises(Pending): rt.prepare_payload(rt.payload())
        self.assertIn('检查点后的真实观察', encoded(rt.cp['messages']))
        self.assertTrue(self.ws.checkpoint_work()['pending'])


if __name__ == '__main__': unittest.main()
