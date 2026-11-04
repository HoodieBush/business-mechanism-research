"""Known-fixture continuation controls and an immutable SCI026 input replay.

Scripted calls and the synthetic parent's 1234 tokens are test data, not API
usage or evidence of autonomous judgment. Imported receipts are not new trials.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from .common import ROOT, Pending, digest, encoded, sha, write_json
from .continuation import ContinuationWorkspace, prepare, snapshot
from .runtime_continuation import ContinuationRuntime
from .runtime_memory import MemoryJournal, reconstruct_request
from .robust import RobustWorkspace
from .composed_world import ComposedWorld, create_world
from .test_acceptance import MODEL, settings, hypothesis, state, raw_call, FixtureJournal


class ContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = os.environ.get('INSIGHT_ACCEPTANCE_OUTPUT')
        cls.temp = None if output else tempfile.TemporaryDirectory(prefix='ic_')
        cls.base = Path(output or cls.temp.name) / 'continuation'
        cls.base.mkdir(parents=True, exist_ok=False)
        cls.question = '围绕实际记录持续研究业务关系，保留原预测与未决项'
        ws = RobustWorkspace(cls.base / 'parent/workspace', cls.question, ComposedWorld(), settings())
        number = 0
        def call(name, args):
            nonlocal number
            number += 1
            return ws.call(name, args, 'parent:' + str(number))
        source = ws.file_ref(ws.public / 'business.sqlite')['ref']
        facts = ws.file_ref(ws.public / 'observed_facts.json')['ref']
        h1 = call('save_hypothesis', hypothesis(kind='data_quality', statement='核对库存与记录销量', prediction='库存出库与记录是否相同', evidence_refs=[source]))
        h2 = call('save_hypothesis', hypothesis(statement='供给对S01记录销量的影响', prediction='S01柜点日差大于零', evidence_refs=[source],
            effect_prediction={'outcome_product_ids':['S01'], 'direction':'increase', 'minimum_effect':0.}))
        hs = [h1['ref'], h2['ref']]
        call('update_research_state', state(active_hypothesis_refs=hs, focus_hypothesis_refs=hs, evidence_refs=[source],
            knowledge_updates=[{'kind':'observation','statement':'计数是给定历史的覆盖维度，不是独立消费者',
            'scope':'给定hourly','status':'tentative','evidence_refs':[facts],'research_use':'明确研究单位',
            'measurements':[{'source_ref':facts,'field':'business_days'}]}]))
        plans = []
        for h, protocol, outcomes, changed in ((h1,'inventory_records',['S01'],[]),(h2,'support_supply:S11',['S01'],['morning_stock:S11'])):
            plan = call('register_test', {'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'原预测对应的已声明协议',
                'observation_unit':'柜点日','allocation_unit':'柜点日或无干预','analysis':'核对原件并保留未决',
                'purpose':'工程夹具，不认证自主研究','data_refs':[source],'mode':'protocol','protocol_id':protocol,
                'outcome_product_ids':outcomes,'expected_changed_variables':changed})
            assert 'ref' in plan, plan
            plans.append(plan)
        cls.results = [call('run_test', {'plan_ref':p['ref']}) for p in plans]
        assert all(r['ok'] for r in cls.results)
        call('run_python', {'purpose':'创建一个需要继承编号的实际分析原件','code':"print('parent calculation')"})
        cls.hypotheses, cls.plans = [h1,h2], plans
        cls.raw = {'choices':[{'finish_reason':'stop','message':{'role':'assistant',
                    'content':'fixture checkpoint; judgment not performed','reasoning_content':'fixture process, not scientific evidence'}}]}
        write_json(ws.private / 'turns/1.json', cls.raw)
        payload = {'model':MODEL['model'],'messages':[{'role':'system','content':'Engineering fixture.'},
                    {'role':'user','content':encoded(ws.context())}], 'max_tokens':65536}
        journal = MemoryJournal(ws, MODEL); journal.persist_request(1, payload)
        journal.persist_response(1, {'response':cls.raw})
        write_json(ws.private / 'transport.json', {'attempts':1,'accounted_tokens':1234,'inflight':None,'delivery':None})
        write_json(ws.private / 'checkpoint.json', {'status':'pending','reason':'synthetic fixture stop','messages':[],
            'pending':None,'responses':1,'context_windows':0,'transport_failures':0})
        (ws.private / 'runtime.lock').touch()
        ws.close()
        cls.manifest = snapshot(cls.base / 'parent/workspace', {'study_id':'FIXTURE','run_id':'parent'}, root=cls.base)
        cls.manifest_path = cls.base / 'parent_manifest.json'; write_json(cls.manifest_path, cls.manifest)

    @classmethod
    def tearDownClass(cls):
        if cls.temp: cls.temp.cleanup()

    def setUp(self):
        self.folder = self.base / self._testMethodName; self.folder.mkdir(exist_ok=False)
        self.ws = None; self.counter = 0

    def tearDown(self):
        if self.ws: self.ws.close()

    def child(self, *, manifest_path=None, root=None, world=None, question=None, configure=None):
        root = root or self.base; path = manifest_path or self.manifest_path
        spec = {'continuation':{'manifest':str(path.relative_to(root)),'sha256':sha(path)}}
        config = settings(); config['continuation'] = spec['continuation']
        config['limits'].update(token_allowance=430336,max_http_attempts=8,max_request_bytes=524288,knowledge_context_bytes=24000)
        if configure: configure(config)
        self.config = config; self.spec = spec; self.project = root
        self.ws = ContinuationWorkspace(self.folder / 'workspace', question or self.question, world or ComposedWorld(), config)
        prepare(self.ws, spec, root=root)
        return self.ws

    def call(self, name, args, key=None):
        self.counter += 1
        return self.ws.call(name, args, key or 'child:' + str(self.counter))

    def read_all(self, ref):
        parts=[]; offset=0
        while True:
            page=self.call('read_memory',{'ref':ref,'offset':offset,'limit':18000});parts.append(page['text'])
            if page['next_offset'] is None: return json.loads(''.join(parts))
            offset=page['next_offset']

    def test_c01_original_records_and_file_refs_are_byte_identical(self):
        ws=self.child()
        for name,version in self.manifest['sha256'].items():
            if name.startswith(('public/','science/')): self.assertEqual(sha(ws.root/name),version)
        self.assertEqual(len(ws.records('hypothesis')),2)
        self.assertEqual(len(ws.unincorporated()),2)
        self.assertEqual(ws.trials_started(),1)
        self.assertEqual([ws.record(h['ref']) for h in self.hypotheses],self.hypotheses)

    def test_c02_parent_stays_unchanged_after_import_and_child_actions(self):
        self.child();self.call('query_data',{'sql':'select count(*) from hourly','purpose':'对子研究执行合法复算'})
        for name,version in self.manifest['sha256'].items():self.assertEqual(sha(self.base/'parent/workspace'/name),version)

    def test_c03_current_paths_worker_number_and_actual_sandbox_boundaries(self):
        ws=self.child(); self.assertEqual(ws.worker.count,1)
        r=ws.record(self.results[1]['ref']); view=ws.result_view(r)
        self.assertTrue(all(Path(f['path']).is_relative_to(ws.root) for f in view['attachments']))
        old=ws.science/'compute/executions/run_001/analysis_001.py'; before=sha(old)
        paths=[old,ws.private/'identity.json',self.base/'parent/workspace/private/identity.json',ROOT/'experiments/studies/SCI-026/scientific_review.json']
        code='from pathlib import Path\n'
        for path in paths:
            mode='w' if path==old else 'r'
            code+=f"try:\n    open({str(path)!r},{mode!r})\n    print('ALLOWED')\nexcept PermissionError:\n    print('DENIED')\n"
        result=self.call('run_python',{'code':code,'purpose':'真实沙箱验证旧原件不可写及私有资料拒读'})
        self.assertTrue(result['execution']['ok'],result)
        self.assertEqual(result['execution']['stdout'].count('DENIED'),4)
        self.assertEqual(sha(old),before);self.assertIn('run_002',result['execution']['execution_directory'])

    def test_c04_repeated_inherited_trial_reuses_original_without_sampling(self):
        ws=self.child()
        with patch.object(ws.environment,'execute',side_effect=AssertionError('cannot rerun inherited trial')):
            one=self.call('run_test',{'plan_ref':self.plans[1]['ref']})
            two=self.call('run_test',{'plan_ref':self.plans[1]['ref']})
        self.assertEqual(one,two);self.assertEqual(one['ref'],self.results[1]['ref'])
        self.assertIn('statistics',one);self.assertNotIn('actual_execution',one)
        self.assertEqual(ws.trials_started(),1)

    def test_c05_new_physical_trial_is_not_authorized_by_this_phase(self):
        ws=self.child(); h=self.hypotheses[1]
        plan=self.call('register_test',{'hypothesis_ref':h['ref'],'prediction':h['prediction'],'contrast':'对照方案',
            'observation_unit':'柜点日','allocation_unit':'柜点日','analysis':'仅测试拒绝新样本',
            'purpose':'工程边界','data_refs':[ws.file_ref(ws.public/'business.sqlite')['ref']],
            'mode':'protocol','protocol_id':'support_supply:S12','outcome_product_ids':['S01'],
            'expected_changed_variables':['morning_stock:S12']})
        result=self.call('run_test',{'plan_ref':plan['ref']})
        self.assertFalse(result['ok']);self.assertIn('no new physical',result['error'])
        self.assertEqual(ws.trials_started(),1)

    def test_c06_unfinished_paid_tools_inflight_and_prepared_operations_are_rejected(self):
        for case in ('pending','inflight','prepared'):
            with self.subTest(case=case):
                parent=self.folder/case/'workspace';shutil.copytree(self.base/'parent/workspace',parent)
                if case=='pending':
                    cp=json.loads((parent/'private/checkpoint.json').read_text());cp['pending']={'calls':[{}],'cursor':0};write_json(parent/'private/checkpoint.json',cp)
                elif case=='inflight':
                    data=json.loads((parent/'private/transport.json').read_text());data['inflight']={'attempt':2};write_json(parent/'private/transport.json',data)
                else:
                    with sqlite3.connect(parent/'private/records.sqlite') as db:db.execute("INSERT INTO operations VALUES ('unsafe','s','prepared',NULL)")
                with self.assertRaises(Pending):snapshot(parent,{'study_id':'FIXTURE'},root=self.base)

    def test_c07_counter_or_manifest_tampering_is_rejected(self):
        value=deepcopy(self.manifest);value['inherited_trials']=0
        path=self.folder/'tampered_manifest.json';write_json(path,value)
        with self.assertRaisesRegex(ValueError,'metadata'):
            self.child(manifest_path=path)
        self.assertEqual(self.ws.records('result'),[])

    def test_c08_changed_environment_or_model_cannot_silently_continue(self):
        with self.assertRaisesRegex(ValueError,'public_inputs'):
            self.child(world=ComposedWorld(seed=9138))
        self.ws.close();self.ws=None
        self.folder=self.folder/'model';self.folder.mkdir()
        def change(config):config['model_config']=deepcopy(config['model_config']);config['model_config']['model']='not-the-parent-model'
        with self.assertRaisesRegex(ValueError,'model_config'):self.child(configure=change)

    def test_c09_owner_archives_and_unsaved_navigation_remain_readable(self):
        self.child();context=self.ws.context();text=encoded(context)
        for label in ('cutlery_demand','sales_underrecording','private_scene_switches','scientific_review','numeric_audit'):self.assertNotIn(label,text)
        self.assertEqual(len(self.ws.tool_schemas()),12)
        self.assertEqual(self.read_all('process:1'),self.raw)
        self.assertEqual(self.read_all('parent_request:1'),reconstruct_request(self.base/'parent/workspace/private',1))
        self.assertEqual(self.read_all('carryover:index'),self.manifest['uncheckpointed_work'])
        self.assertFalse(self.call('read_artifact',{'ref':'parent_request:1'})['ok'])

    def test_c10_reopen_and_prepare_do_not_duplicate_or_reset_research(self):
        ws=self.child();counts=dict(ws.db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))
        prepare(ws,self.spec,root=self.base);self.assertEqual(dict(ws.db.execute('SELECT kind,count(*) FROM records GROUP BY kind')),counts)
        ws.close();self.ws=ContinuationWorkspace(self.folder/'workspace',self.question,ComposedWorld(),self.config,reopen=True)
        prepare(self.ws,self.spec,root=self.base)
        self.assertEqual(self.ws.trials_started(),1);self.assertEqual(self.ws.worker.count,1)
        self.assertEqual(ContinuationRuntime(self.ws,MODEL).cp['responses'],1)
        self.assertFalse((self.ws.private/'transport.json').exists())
        self.assertEqual(self.ws.context()['continuation']['prior_reported_tokens'],1234)

    def test_c11_scripted_judgments_state_compaction_and_report_complete(self):
        ws=self.child();hs=[h['ref'] for h in self.hypotheses];rs=[r['ref'] for r in self.results]
        def assessments():
            calls=[]
            for h,r in zip(hs,rs):
                args={'hypothesis_ref':h,'result_refs':[r],'status':'unresolved','prediction_coverage':'只解释实际收到的记录范围',
                    'rationale':'保留原预测和范围；程序执行并非完整机制证明','deviations':[],'counterevidence_refs':[],
                    'limitations':['脚本夹具，不是模型判断有效性的证明']}
                calls.extend(raw_call('record_assessment',args,identifier=h)['choices'][0]['message']['tool_calls'])
            return {'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'','tool_calls':calls}}]}
        def checkpoint():return raw_call('update_research_state',state(active_hypothesis_refs=hs,focus_hypothesis_refs=hs,
            evidence_refs=rs,incorporated_result_refs=rs,understanding='已有结果已吸收，当前诚实未决，后续需补证据'))
        def finish():return raw_call('finish_research',{'assessment_refs':[a['ref'] for a in ws.records('assessment')],
            'other_hypotheses':{},'limitations':['脚本流程，不认证科学能力'],'open_questions':['下一次需要什么证据'],
            'measurement_requests':[]})
        journal=FixtureJournal([assessments,checkpoint,finish]);runtime=ContinuationRuntime(ws,MODEL,journal=journal)
        runtime.run(2);self.assertEqual(ws.unincorporated(),[]);runtime.compact()
        result=runtime.run(1);self.assertEqual(result['status'],'completed')
        self.assertEqual(ws.report()['stage_status'],'inconclusive');self.assertEqual(len(journal.requests),3)
        self.assertEqual(ws.trials_started(),1)

    def test_c12_real_SCI026_replay_preserves_all_originals_and_two_results(self):
        path=ROOT/'experiments/insight_research/review/continuation_20261021/parent_manifest.json'
        actual=json.loads(path.read_text());question=actual['identity']['question']
        ws=self.child(manifest_path=path,root=ROOT,question=question)
        self.assertEqual(len(ws.records('hypothesis')),4);self.assertEqual(len(ws.unincorporated()),2)
        self.assertEqual(len(ws.context()['hypothesis_cards']),4)
        self.assertEqual(ws.trials_started(),1);self.assertEqual(ws.worker.count,11)
        self.assertEqual(ContinuationRuntime(ws,MODEL).cp['responses'],32)
        for name,version in actual['sha256'].items():
            if name.startswith(('public/','science/')):self.assertEqual(sha(ws.root/name),version)
        full=ws.unincorporated();by_ref={r['ref']:r for r in ws.context()['unincorporated_results']}
        for result in full:
            self.assertEqual(by_ref[result['ref']]['statistics'],result['actual_execution'].get('statistics'))
        for card in ws.context()['hypothesis_cards']:
            for result in card['latest_results']:self.assertEqual(result['context_entry'],'unincorporated_results')

    def test_c13_parent_record_mutation_is_rejected(self):
        parent=self.folder/'changed/workspace';shutil.copytree(self.base/'parent/workspace',parent)
        target=parent/'science/records'/(self.hypotheses[0]['ref']+'.json');item=json.loads(target.read_text());item['prediction']='changed';write_json(target,item)
        with self.assertRaisesRegex(ValueError,'published record'):snapshot(parent,{'study_id':'FIXTURE'},root=self.base)

    def test_c14_received_reconciliation_units_bind_and_wrong_claim_does_not_block_state(self):
        ws=self.child();source=self.results[0]['ref'];totals=ws.result_view(ws.record(source))['reconciliation_totals']
        note={'kind':'observation','statement':'记录件数与库存隐含出库的差和异常行数分别记录','scope':'当前原始台账',
            'status':'tentative','evidence_refs':[source],'research_use':'避免混淆统计单位',
            'measurements':[{'source_ref':source,'field':'difference_units'},{'source_ref':source,'field':'mismatched_rows'}]}
        bad=deepcopy(note);bad['measurements'][0]['value']=totals['difference_units']+1
        result=self.call('update_research_state',state(active_hypothesis_refs=[h['ref'] for h in self.hypotheses],
            evidence_refs=[source],knowledge_updates=[bad,note]))
        self.assertEqual(len(result['knowledge_rejections']),1);self.assertEqual(len(result['knowledge_refs']),1)
        view=ws.knowledge_view(result['knowledge_refs'][0]);self.assertEqual([m['unit'] for m in view['bound_measurements']],['items','rows'])
        self.assertEqual(view['bound_measurements'][0]['value'],totals['difference_units'])

    def test_c15_result_notice_is_independent_of_window_pressure(self):
        ws=self.child();runtime=ContinuationRuntime(ws,MODEL)
        payload=runtime.payload(runtime.initial())
        self.assertLess(len(encoded(payload).encode()),ws.settings['limits']['max_request_bytes']*.7)
        result=runtime.prepare_payload(payload)
        self.assertIn('已有结果待处理',result['messages'][-1]['content'])
        self.assertEqual(runtime.journal.state['attempts'],0)


if __name__=='__main__':unittest.main()
