"""Generic information and framework checks; scripted decisions are not LLM results."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph_migration.collaboration import CollaborativeWorkspace,collaboration_flow
from langgraph_migration.runtime import FrameworkRoles
from test_langgraph_migration import ScriptedModel,checks


def deliver(primary=None,reviews=(),files=()):
    return ('submit_result',{'summary':'scripted component check','primary_artifact':str(primary) if primary else None,
            'evidence_files':list(map(str,files)),'review_ids':list(reviews),'findings':[],'next_step':'check only'})


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_packets_')
        self.root=Path(self.temp.name)
        self.ws=CollaborativeWorkspace(self.root/'P001',{'domain':'orders','construction':'sum','seed_draft':True,'question':'Summarize customer order counts.'})
        self.conn=sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False);self.saver=SqliteSaver(self.conn)
        self.roles=FrameworkRoles(self.ws,self.saver,lambda role:None)
    def tearDown(self):self.conn.close();self.temp.cleanup()
    def review(self,decision='accepted'):
        view=self.ws.tool('verifier','read_packet',{'packet_id':'packet_0001'})
        execution=self.ws.tool('verifier','run_python',{'code':"from research_data import read_table\nprint(read_table('observations').to_pandas())",'purpose':'scripted independent source access','output_semantics':'source preview, no semantic certification'})
        return self.ws.tool('verifier','review_artifact',{'artifact_id':view['artifact_id'],'execution_id':execution['execution_id'],'decision':decision,'checks':checks(decision),'summary':'scripted engineering decision only'})
    def test_binary_original_returns_format_and_access_instead_of_decode_error(self):
        result=self.ws.tool('mechanist','read_artifact',{'path':str(self.ws.public/'business.sqlite')})
        self.assertEqual(result['format'],'sqlite');self.assertIn('query_data',result['access'])
    def test_accepted_packet_exposes_bound_attachments_without_recursive_review(self):
        self.review();view=self.ws.tool('mechanist','read_packet',{'packet_id':'packet_0001'})
        self.assertEqual(view['current_review_status'],'accepted')
        attachments=view['attachments']+view['review_attachments']
        self.assertGreaterEqual(len(attachments),5)
        for item in attachments:
            result=self.ws.tool('mechanist','read_artifact',{'path':item['path']})
            self.assertEqual(result['parent_packet'],'packet_0001');self.assertNotIn('artifact_id',result)
    def test_tampered_attachment_invalidates_packet_or_review(self):
        review=self.review();entry=self.ws.state['packet_reviews'][review['id']]['attachments'][1]
        Path(entry['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'version changed'):self.ws.tool('mechanist','read_packet',{'packet_id':'packet_0001'})
    def test_content_preserving_rewrite_binds_new_execution_not_old_code(self):
        code="from research_data import read_table\nimport os\nread_table('observations').to_csv(os.path.join(os.environ['WORK_DIR'],'same.csv'))"
        first=self.ws.tool('analyst','run_python',{'code':code,'purpose':'first execution','output_semantics':'registered raw rows'})
        path=Path(first['data_outputs'][0]);digest=path.read_bytes()
        second=self.ws.tool('analyst','run_python',{'code':code+'\nprint("new execution, same bytes")','purpose':'content-preserving rewrite','output_semantics':'same registered raw rows'})
        self.assertEqual(path.read_bytes(),digest);self.assertIn(str(path),second['data_outputs'])
        meta=json.loads(Path(str(path)+'.meta.json').read_text())
        self.assertEqual(meta['code_file'],second['code_file']);self.assertEqual(meta['execution_receipt'],second['execution_receipt'])
        packet=self.ws.packets.create(path,'analyst')
        entry=next(e for e in packet['attachments'] if e['kind']=='producer_code')
        self.assertEqual(Path(entry['path']).read_text(),code+'\nprint("new execution, same bytes")')
    def test_data_api_is_precise_and_consumer_cannot_attach_other_unreviewed_data(self):
        self.assertIn('COPY',self.ws.python_api['copy_semantics'])
        self.assertEqual(self.ws.python_api['methods']['Frame']['to_csv'],'(self, path, index=False, interpretations=None)')
        self.review()
        view=self.ws.packets.view('packet_0001','mechanist')
        self.assertEqual(view['delivery_references']['review_ids'],['V001'])
        other=self.ws.workers['analyst'].directory/'unreviewed.csv';other.write_text('x\n1\n')
        with self.assertRaisesRegex(ValueError,'no current independent review'):
            self.ws.tool('mechanist','submit_result',deliver(reviews=['V001'],files=[other])[1])
    def test_rejected_packet_not_readable_by_consumer_but_feedback_readable_by_producer(self):
        self.review('rejected')
        with self.assertRaisesRegex(ValueError,'lacks current'):self.ws.tool('mechanist','read_packet',{'packet_id':'packet_0001'})
        view=self.ws.tool('analyst','read_packet',{'packet_id':'packet_0001'})
        self.assertEqual(view['latest_review']['decision'],'rejected')
    def test_namespaces_and_workflow_preconditions_not_domain_answer_checks(self):
        with self.assertRaisesRegex(ValueError,'allowed roles'):self.ws.tool('manager','schedule_task',{'role':'mechanist','question':'handoff','inputs':['packet_0001'],'rationale':'check'})
        with self.assertRaisesRegex(ValueError,'actual consumer'):self.ws.tool('manager','finish_research',{'summary':'done','limitations':['check']})
        with self.assertRaisesRegex(ValueError,'review_ids'):self.ws.tool('verifier','submit_result',dict(deliver(files=['V001'])[1]))
    def test_interruption_between_state_write_and_tool_receipt_recovers_without_reexecution(self):
        view=self.ws.tool('verifier','read_packet',{'packet_id':'packet_0001'})
        run=self.ws.tool('verifier','run_python',{'code':"from research_data import read_table\nprint(read_table('observations').shape)",'purpose':'receipt recovery fixture','output_semantics':'source shape'})
        args={'artifact_id':view['artifact_id'],'execution_id':run['execution_id'],'decision':'accepted','checks':checks('accepted'),'summary':'scripted decision'}
        review=self.ws.tool('verifier','review_artifact',args,operation_id='interrupted_review')
        self.ws.state['packet_reviews'].pop(review['id']);self.ws.persist()
        receipt=self.ws.root/'tool_receipts/interrupted_review.json'
        record=json.loads(receipt.read_text());record['status']='prepared';record.pop('result');receipt.write_text(json.dumps(record))
        restored=self.ws.tool('verifier','review_artifact',args,operation_id='interrupted_review')
        self.assertEqual(restored,review);self.assertEqual(self.ws.workers['verifier'].count,1)
        self.assertIsNotNone(self.ws.packets.current_review(self.ws.packets.validate('packet_0001')))
        self.ws.state['workflow']['phase']='ready_to_finish'
        args={'summary':'receipt recovery','limitations':['scripted']}
        first=self.ws.tool('manager','finish_research',args,operation_id='interrupted_finish')
        receipt=self.ws.root/'tool_receipts/interrupted_finish.json'
        record=json.loads(receipt.read_text());record['status']='prepared';record.pop('result');receipt.write_text(json.dumps(record))
        self.assertEqual(self.ws.tool('manager','finish_research',args,operation_id='interrupted_finish'),first)
    def test_same_task_with_changed_input_version_does_not_return_cached_result(self):
        self.review()
        task={'question':'input version cache','inputs':[str(self.ws.public/'data_dictionary.json')]}
        for version in ('first','second'):
            if version=='second':
                path=self.ws.public/'data_dictionary.json';data=json.loads(path.read_text());data['version']='changed-source-definition';path.write_text(json.dumps(data))
            model=ScriptedModel(sequence=[deliver(reviews=['V001'])])
            roles=FrameworkRoles(self.ws,self.saver,lambda role:model)
            roles.run('verifier',task);self.assertEqual(model.calls,1)
        self.assertEqual(len(self.ws.state['results']),2)
    def test_native_supervisor_rejection_revision_review_handoff(self):
        def schedule(role,packet):return ('schedule_task',{'role':role,'question':'scripted task','inputs':[packet],'rationale':'component flow'})
        manager=ScriptedModel(sequence=[schedule('verifier','packet_0001'),schedule('analyst','packet_0001'),schedule('verifier','packet_0002'),schedule('mechanist','packet_0002'),('finish_research',{'summary':'component flow finished','limitations':['scripted, not scientific capability']})])
        verifier_actions=[]
        for packet,artifact,execution,decision,review in [('packet_0001','artifact_0001','execution_0002','rejected','V001'),('packet_0002','artifact_0005','execution_0006','accepted','V002')]:
            verifier_actions += [('read_packet',{'packet_id':packet}),('run_python',{'code':"from research_data import read_table\nprint(read_table('observations').to_pandas())",'purpose':'scripted independent access','output_semantics':'source preview'}),('review_artifact',{'artifact_id':artifact,'execution_id':execution,'decision':decision,'checks':checks(decision),'summary':'scripted judgment'}),deliver(reviews=[review])]
        primary=self.ws.workers['analyst'].directory/'new.csv'
        code="from research_data import read_table\nfrom pathlib import Path\nimport os\nf=read_table('observations').groupby(['customer_id']).agg(order_count=('order_id','count'))\nf.to_csv(Path(os.environ['WORK_DIR'])/'new.csv',interpretations={'customer_id':{'meaning':'customer identifier','unit':'identifier'},'order_count':{'meaning':'orders per customer','unit':'orders'}})"
        analyst=ScriptedModel(sequence=[('run_python',{'code':code,'purpose':'scripted new artifact','output_semantics':'one row per customer, number of orders'}),deliver(primary)])
        consumer=ScriptedModel(sequence=[('read_packet',{'packet_id':'packet_0002'}),deliver(reviews=['V002'])])
        models={'manager':manager,'verifier':ScriptedModel(sequence=verifier_actions),'analyst':analyst,'mechanist':consumer}
        roles=FrameworkRoles(self.ws,self.saver,lambda role:models[role])
        flow=collaboration_flow(roles,self.saver);config={'configurable':{'thread_id':'collaborative-test'}}
        result=flow.invoke({},config)
        self.assertEqual(result['status'],'completed');self.assertEqual(self.ws.workflow()['phase'],'complete')
        self.assertEqual([r['decision'] for r in self.ws.state['artifact_reviews']],['rejected','accepted'])
        self.assertEqual([t['role'] for t in self.ws.state['tasks']],['verifier','analyst','verifier','mechanist'])
        counts={role:model.calls for role,model in models.items()}
        self.assertEqual(flow.get_state(config).next,())
        self.assertEqual(flow.invoke(None,config)['status'],'completed')
        self.assertEqual({role:model.calls for role,model in models.items()},counts)


if __name__=='__main__':unittest.main()
