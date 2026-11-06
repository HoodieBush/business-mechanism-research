"""The visible submission contract and output adapters must agree with the gate."""
import json,re,unittest
from copy import deepcopy
from business_mechanism.prompts import compose
from business_mechanism.submission_protocol import clean_example
from business_mechanism.method_coverage import coverage_report,computation_output
from business_mechanism.tool_protocol import normalize_tool_containers
from business_mechanism.workflow import action_catalog
import test_agent_repairs as fixtures


class SubmissionProtocol(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AgentRepairs();self.fixture.setUp()
        self.peer,self.job,self.target=self.fixture.peer()
    def tearDown(self):self.peer.close();self.fixture.tearDown()

    def test_visible_complete_examples_match_schema_and_require_actual_computation(self):
        prompt=compose('critic');model=self.peer.tools['record_review'][0]
        for name,body in re.findall(r'<example id="([^"]+)">(.*?)</example>',prompt,re.S):
            if not re.search(r'函数：\s*record_review\b',body):continue
            value=json.loads(re.search(r'```json\s*(.*?)\s*```',body,re.S).group(1))
            model.model_validate(value)
            if value['phase']=='complete' and value['target_conclusion']=='consistent_in_checked_scope':
                self.assertTrue(value['coverage_checks'])
                self.assertTrue(any(c['action_ref']=='check:EXAMPLE_COMPUTE' for c in value['checks_performed']))
        self.assertNotIn('资源不足只能checkpoint',prompt)
        contract=self.peer.call('get_review_contract',{},'format')
        self.assertEqual(contract['submission_format']['protocol'],'covered-review-v2')
        self.assertEqual(contract['submission_format']['required_coverage_components'],['claim_evidence'])
        self.assertNotIn('json_pointer_examples',contract)

    def test_real_plain_output_has_exact_paths_without_numeric_guessing(self):
        code="import sqlite3,os\nv=sqlite3.connect(os.path.join(os.environ['PUBLIC_DIR'],'business.sqlite')).execute('SELECT MIN(value) FROM observations').fetchone()[0]\nprint('minimum='+str(v))"
        result=self.peer.call('run_python',{'code':code,'purpose':'Exact rendered computation fixture'},'text-compute')
        catalog=action_catalog(self.peer);entry=next(a for a in catalog if a['action_ref']==result['action_ref'])
        self.assertIn({'output_pointer':'/stdout_lines/0','observed':'minimum=0.0'},entry['actual_output_paths'])
        check={'component':'claim_evidence','basis':'recomputed','action_ref':result['action_ref'],'output_pointer':'/stdout_lines/0','relation':'eq','expected':'minimum=0.0'}
        self.assertTrue(coverage_report([check],self.peer.action)['clearance_eligible'])
        for altered in ({'relation':'gt','expected':0},{'output_pointer':'/parsed_stdout/n','expected':0},{'relation':'contains','expected':'0'}):
            self.assertFalse(coverage_report([{**check,**altered}],self.peer.action)['clearance_eligible'])
        failed={'tool':'run_python','result':{'execution':{'exit_code':1,'stdout':'{"minimum":0}'}}}
        self.assertFalse(coverage_report([{**check,'output_pointer':'/parsed_stdout/minimum','expected':0}],lambda _:failed)['clearance_eligible'])
        self.assertEqual(computation_output({'stdout':'complete\nincomplete','stdout_truncated':True})['stdout_lines'],['complete'])
        self.assertNotIn('parsed_stdout',computation_output({'stdout':'{"n":1}','stdout_truncated':True}))

    def test_ready_patch_returns_exact_single_commit_without_another_read(self):
        q=self.peer.call('query_data',{'sql':'SELECT MIN(value) FROM observations','purpose':'Exact zero for format fixture'},'minimum')
        args=clean_example();args.update(source_refs=[self.target['ref']],checks_performed=[{'action_ref':q['action_ref'],'finding':'Actual synthetic minimum is zero.','artifact_refs':[]}],
            coverage_checks=[{'component':'claim_evidence','action_ref':q['action_ref'],'output_pointer':'/preview/0/0','relation':'eq','expected':0}],open_issue_ids=['UNKNOWN'])
        draft=self.peer.call('save_review_draft',{'raw_arguments':json.dumps(args)},'save')
        self.assertFalse(draft['ready_to_commit'])
        fixed=self.peer.call('patch_review_draft',{'draft_ref':draft['draft_ref'],'expected_hash':draft['draft_hash'],
            'field_changes':[{'op':'set','path':'/open_issue_ids','value':[]}]},'fix')
        self.assertTrue(fixed['ready_to_commit']);self.assertTrue(fixed['valid'])
        call=fixed['commit_call'];review=self.peer.call(call['name'],call['arguments'],'commit')
        self.assertEqual(review['phase'],'complete')
        self.assertEqual(json.loads(fixed['raw_arguments'])['checks_performed'],args['checks_performed'])

    def test_fence_and_singleton_are_lossless_but_extra_prose_is_rejected(self):
        args=clean_example();args['coverage_checks']=args['coverage_checks'][0]
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'','tool_calls':[
            {'id':'review','type':'function','function':{'name':'record_review','arguments':'```json\n'+json.dumps(args)+'\n```'}}]}}]}
        normalized,changes,errors=normalize_tool_containers(raw,self.peer.tools)
        self.assertFalse(errors);value=json.loads(normalized['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        self.assertEqual(value['coverage_checks'],[args['coverage_checks']]);self.assertEqual(value['checks_performed'],args['checks_performed'])
        self.assertEqual({c['kind'] for c in changes},{'lossless_json_fence_unwrap','lossless_singleton_coverage_array'})
        self.assertTrue(raw['choices'][0]['message']['tool_calls'][0]['function']['arguments'].startswith('```'))
        mixed=deepcopy(raw);mixed['choices'][0]['message']['tool_calls'][0]['function']['arguments']+='\nChoose whichever finding looks positive.'
        self.assertTrue(normalize_tool_containers(mixed,self.peer.tools)[2])


if __name__=='__main__':unittest.main()
