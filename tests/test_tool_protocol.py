"""Lossless nested-container wire compatibility and no-HTTP paid recovery."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from business_mechanism.tool_protocol import normalize_tool_containers, recover_protocol_rejection, strict_json
from experiments.insight_research.runtime import Runtime as NativeRuntime
from experiments.insight_research.common import digest, encoded, write_json
import test_workflow_robustness as fixtures


class ToolProtocol(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.WorkflowRobustness();self.fixture.setUp()
        self.ws=self.fixture.ws;self.runtime=self.fixture.backend.runtime
        h,_,_=self.fixture.business_target()
        code=self.ws.science/'source.py';code.write_text('print(0)\n')
        self.spec={'dataset_ref':self.ws.file_ref(self.ws.public/'business.sqlite')['ref'],
            'code_ref':self.ws.file_ref(code)['ref'],'filter':'text {"do_not_decode":1}',
            'sampling':'all','entity':['id'],'grouping':{},'transformations':[],
            'estimator':'descriptive fixture','uncertainty':'not a scientific certification',
            'required_components':['numeric_claim']}
        self.args={'target_ref':h['ref'],'spec':json.dumps(self.spec)}
        self.raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'',
            'tool_calls':[{'id':'spec-call','type':'function','function':{'name':'register_analysis_spec','arguments':encoded(self.args)}}]}}],
            'usage':{'total_tokens':17}}
        self.runtime.cp['messages']=self.runtime.initial();self.runtime.save()

    def tearDown(self):
        self.fixture.tearDown()

    def test_schema_exposes_inline_object_and_lossless_decode_preserves_prose(self):
        schema=next(s for s in self.ws.tool_schemas() if s['function']['name']=='register_analysis_spec')
        self.assertEqual(schema['function']['parameters']['properties']['spec']['type'],'object')
        normalized,changes,errors=normalize_tool_containers(self.raw,self.ws.tools)
        value=json.loads(normalized['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        self.assertEqual(value['spec'],self.spec)
        self.assertEqual(value['spec']['filter'],'text {"do_not_decode":1}')
        self.assertEqual(changes[0]['path'],'/spec');self.assertFalse(errors)
        self.assertIsInstance(json.loads(self.raw['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['spec'],str)

    def test_live_accept_has_canonical_pending_and_exact_original_archive(self):
        self.runtime.accept(self.raw,delivery=1)
        from business_mechanism.method_coverage import AnalysisSpec
        self.assertEqual(self.runtime.cp['pending']['calls'][0]['args']['spec'],AnalysisSpec.model_validate(self.spec).model_dump())
        self.assertEqual(json.loads((self.ws.private/'turns/1.json').read_text()),self.raw)
        self.assertTrue((self.ws.private/'wire_normalizations/1.json').exists())
        with patch('business_mechanism.transport.call_model',side_effect=AssertionError('no extra HTTP')):
            self.runtime.run(0)
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM release_analysis_specs').fetchone()[0],1)

    def test_duplicate_outer_json_rejects_whole_mixed_batch(self):
        raw=deepcopy(self.raw)
        other=deepcopy(raw['choices'][0]['message']['tool_calls'][0]);other['id']='duplicate'
        other['function']['arguments']='{"target_ref":"first","target_ref":"second","spec":{}}'
        raw['choices'][0]['message']['tool_calls'].append(other)
        self.runtime.accept(raw,delivery=1)
        self.assertIsNone(self.runtime.cp['pending'])
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM release_analysis_specs').fetchone()[0],0)
        self.assertEqual(json.loads((self.ws.private/'turns/1.json').read_text()),raw)
        with self.assertRaisesRegex(ValueError,'duplicate JSON field'):
            strict_json('{"blocking":true,"blocking":false}')

    def test_unknown_fields_are_never_dropped(self):
        raw=deepcopy(self.raw);args=deepcopy(self.args);args['comment']='Scientific material that must not be deleted'
        raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']=encoded(args)
        normalized,_,_=normalize_tool_containers(raw,self.ws.tools)
        value=json.loads(normalized['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        self.assertEqual(value['comment'],args['comment'])
        self.runtime.accept(raw);self.assertIsNone(self.runtime.cp['pending'])

    def test_malformed_function_after_paid_request_is_rejected_without_crashing(self):
        self.runtime.journal.persist_request(1,self.runtime.payload())
        raw=deepcopy(self.raw);raw['choices'][0]['message']['tool_calls'][0]['function']=None
        self.runtime.accept(raw,delivery=1)
        self.assertIsNone(self.runtime.cp['pending'])
        self.assertEqual(json.loads((self.ws.private/'turns/1.json').read_text()),raw)
        receipt=json.loads((self.ws.private/'wire_normalizations/1.json').read_text())
        self.assertEqual(receipt['errors'][0]['error_code'],'invalid_tool_json')

    def test_crash_restores_original_raw_then_drains_once(self):
        self.runtime.accept(self.raw,delivery=1)
        normalized,_,_=normalize_tool_containers(self.raw,self.ws.tools)
        write_json(self.ws.private/'turns/1.json',normalized)
        with patch('business_mechanism.transport.call_model',side_effect=AssertionError('no new request')):
            self.runtime.run(0);self.runtime.run(0)
        self.assertEqual(json.loads((self.ws.private/'turns/1.json').read_text()),self.raw)
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM release_analysis_specs').fetchone()[0],1)

    def test_replay_previously_paid_zero_tool_rejection_without_recharging(self):
        journal=self.runtime.journal;payload=self.runtime.payload();key=digest([journal.role,1])
        bound=journal.study.reserve(key,journal.role,payload)
        journal.persist_request(1,payload);journal.persist_response(1,{'response':self.raw})
        journal.study.settle(key,digest(payload),self.raw['usage'])
        journal.state.update(attempts=1,accounted_tokens=17,inflight=None,delivery=None);journal.save()
        # Recreate the old parser's rejection, before the new compatibility
        # layer. The response and synthetic cost are durable and acknowledged.
        NativeRuntime.accept(self.runtime,self.raw,delivery=1)
        self.assertIsNone(self.runtime.cp['pending']);before=journal.study.snapshot()
        with patch('business_mechanism.transport.call_model',side_effect=AssertionError('paid response must not be resent')):
            first=recover_protocol_rejection(self.runtime,'known-container-fix')
            again=recover_protocol_rejection(self.runtime,'known-container-fix')
        self.assertEqual(first,again);self.assertNotEqual(first['result'].get('ok'),False)
        self.assertEqual(journal.study.snapshot(),before)
        self.assertEqual(self.runtime.cp['responses'],1);self.assertEqual(journal.state['attempts'],1)
        self.assertEqual(self.ws.db.execute('SELECT count(*) FROM release_analysis_specs').fetchone()[0],1)
        self.assertEqual(json.loads((self.ws.private/'turns/1.json').read_text()),self.raw)


if __name__ == '__main__':
    unittest.main()
