"""Engineering checks; scripted semantic decisions are not scientific evidence."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult,ChatGeneration
from langgraph.checkpoint.sqlite import SqliteSaver
from world import OfficeWorld
from workspace import sha
from langgraph_migration.science import ScientificWorkspace,scientific_flow
from langgraph_migration.runtime import FrameworkRoles
from test_langgraph_migration import checks
from langgraph_migration.research_queue import view as queue_view,assess as assess_schedule


class PolicyModel(BaseChatModel):
    ws:object=Field(exclude=True)
    role:str
    counts:dict=Field(default_factory=dict)
    @property
    def _llm_type(self):return 'scripted-native-science-test'
    def bind_tools(self,tools,**kwargs):return self
    def _generate(self,messages,**kwargs):
        ws=self.ws;phase=ws.state['workflow']['phase'];i=self.counts.get(phase,0);self.counts[phase]=i+1
        expected='coordination' if self.role=='manager' else phase
        if messages[-1].type!='system' or '当前阶段职责（系统状态提供）' not in messages[-1].content or expected not in messages[-1].content:
            raise AssertionError('authoritative stage objective must reach every actual model call')
        if self.role=='manager':
            if phase=='ready_to_finish':action=('finish_research',{'selected_algorithm_id':'baseline','summary':'scripted science path','limitations':['scripted decisions, no scientific ability claim']})
            else:action=('schedule_task',{'role':ws.workflow()['allowed_roles'][0],'question':'scripted phase '+phase,'inputs':[ws.state['workflow']['latest_packet']] if ws.state['workflow']['latest_packet'] else ws.state['base_source_paths'],'rationale':'native graph engineering check'})
        elif self.role=='analyst':
            actions=[('run_python',{'code':"import os,sqlite3,pandas as pd\nc=sqlite3.connect(os.environ['PUBLIC_DIR']+'/business.sqlite')\nf=pd.read_sql_query('SELECT sku, SUM(sales) recorded_units FROM hourly GROUP BY sku',c)\nf.to_csv(os.environ['WORK_DIR']+'/summary.csv',index=False)",'purpose':'scripted source aggregation','output_semantics':'one row per SKU, recorded hourly sales summed into recorded units, not demand'}),
              ('publish_analysis',{'primary_artifact':str(ws.workers['analyst'].directory/'executions/run_001/summary.csv'),'summary':'scripted aggregate','findings':[],'next_step':'independent information review'})]
            action=actions[i]
        elif self.role=='verifier' and phase=='needs_review':
            packet=ws.packets.validate(ws.state['workflow']['latest_packet'])
            if i==0:action=('read_packet',{'packet_id':packet['id']})
            elif i==1:action=('run_python',{'code':"import os,sqlite3\nc=sqlite3.connect(os.environ['PUBLIC_DIR']+'/business.sqlite');print(c.execute('SELECT sku, SUM(sales) FROM hourly GROUP BY sku').fetchall())",'purpose':'scripted independent raw SQLite','output_semantics':'recorded units per SKU'})
            elif i==2:action=('review_artifact',{'artifact_id':ws.reference(packet['artifact']['path']),'execution_id':next(k for k,v in ws.state['references'].items() if v['kind']=='execution' and '/verifier/' in v['path']),'decision':'accepted','checks':checks('accepted'),'summary':'scripted semantic decision'})
            else:action=('finish_review',{'review_id':ws.state['artifact_reviews'][-1]['id'],'summary':'scripted review delivery'})
        elif self.role=='mechanist':
            packet=ws.packets.validate(ws.state['workflow']['latest_packet'])
            if i==0:action=('save_hypothesis',{'explanation':'check consistency of recorded and physical stock-flow values','scope':'received history, one SKU','alternatives':['recording differences','true low observed demand'],'prediction':'audit can reveal record-flow mismatch','falsification':'audit no mismatch only within audited scope','evidence_files':[packet['artifact']['path']],'change_reason':'scripted new hypothesis','parent_id':None})
            else:action=('finish_hypotheses',{'hypothesis_ids':[ws.state['hypotheses'][-1]['id']],'summary':'scripted hypotheses'})
        elif self.role=='verifier':
            hid=ws.state['workflow']['hypothesis_ids'][0]
            if i==0:action=('prepare_experiment',{'hypothesis_id':hid,'protocol_id':'inventory_records','expected_changed_variables':[],'outcome_product_ids':['S01'],'prediction':'audit stock-flow','analysis_plan':'compare actual recorded fields'})
            elif i==1:action=('run_experiment',{'plan_id':ws.state['study_plans'][-1]['id']})
            elif i==2:action=('record_verdict',{'hypothesis_id':hid,'status':'unresolved','rationale':'scripted scoped audit only, no causal claim','evidence_files':[ws.state['experiments'][-1]['observations']]})
            else:action=('finish_validation',{'hypothesis_ids':[hid],'next_action':'engineer','summary':'scripted non-causal verdict'})
        elif self.role=='engineer':
            if i==0:action=('run_python',{'code':"import os\nopen(os.environ['WORK_DIR']+'/candidate.py','w').write('import numpy as np\\ndef predict(history,future):\\n return np.full(len(future),3.0)\\n')",'purpose':'scripted candidate code','output_semantics':'candidate function, not evidence'})
            elif i==1:action=('evaluate_algorithm',{'code_file':str(ws.workers['engineer'].directory/'executions/run_001/candidate.py'),'hypothesis_ids':[],'rationale':'scripted evaluation adapter check'})
            else:action=('finish_algorithm',{'selected_algorithm_id':'baseline','summary':'scripted selection','limitations':['evaluation mocked in this engineering check']})
        else:raise AssertionError('unexpected summarizer call in short engineering fixture')
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[{'name':action[0],'args':action[1],'id':f'{phase}_{i}','type':'tool_call'}]))])


class InterleavedPolicyModel(PolicyModel):
    """Scripted choices check scheduling, never the quality of a real discovery."""
    def _generate(self,messages,**kwargs):
        ws=self.ws;flow=ws.state['workflow'];phase=flow['phase'];hs=ws.state['hypotheses']
        if self.role=='manager' and phase=='needs_research_decision':
            if len(hs)==1 and hs[0].get('verdicts'):
                role='mechanist';ids=[];gap='independent decision-relevant question; scripted exploration override'
            elif len(hs)==2:role='engineer';ids=[hs[0]['id']];gap=None
            else:role='verifier';ids=[hs[0]['id']];gap=None
            action=('schedule_task',{'role':role,'hypothesis_ids':ids,'evidence_gap':gap,
                'priority_assessment':{'decision_gain':10 if role=='mechanist' else 1,'information_gain':1,'effort_cost':1,'basis':'scripted utility judgments, not measured profit'},
                'question':'scripted incremental task','inputs':[flow['latest_packet']],'rationale':'does not wait for every hypothesis'})
        elif self.role=='mechanist':
            packet=ws.packets.validate(flow['latest_packet'])
            action=('save_hypothesis',{'explanation':'scripted independent candidate '+str(len(hs)+1),'scope':'received history',
                'alternatives':['recording','demand'],'prediction':'scope-limited prediction','falsification':'scope-limited counterexample',
                'evidence_files':[packet['artifact']['path']],'change_reason':'scripted incremental publication','parent_id':None})
        elif self.role=='verifier' and phase=='needs_validation':
            hid=flow['hypothesis_ids'][0];h=next(h for h in hs if h['id']==hid)
            if not h.get('verdicts'):action=('record_verdict',{'hypothesis_id':hid,'status':'unresolved','rationale':'scripted uncertainty; no actual causal inference','evidence_files':[str(ws.public/'history.csv')]})
            else:action=('finish_validation',{'hypothesis_ids':[hid],'next_action':'revise_hypothesis','summary':'scripted recommendation; manager may proceed'})
        else:return super()._generate(messages,**kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='',tool_calls=[{'name':action[0],'args':action[1],'id':f'{phase}_{len(hs)}_{len(ws.state["tasks"])}','type':'tool_call'}]))])


class ScienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_science_')
        cls.root=Path(cls.temp.name);cls.ws=ScientificWorkspace(cls.root/'D001',OfficeWorld('relationship',7400))
        cls.conn=sqlite3.connect(cls.root/'checkpoints.sqlite',check_same_thread=False);cls.saver=SqliteSaver(cls.conn)
    @classmethod
    def tearDownClass(cls):cls.conn.close();cls.temp.cleanup()
    def test_01_standard_sql_reads_record_exact_original_columns(self):
        r=self.ws.workers['verifier'].run("import sqlite3,os\nc=sqlite3.connect(os.environ['PUBLIC_DIR']+'/business.sqlite');print(c.execute('SELECT sku,sales FROM hourly LIMIT 2').fetchall())")
        self.assertTrue(r['ok'],r)
        reads=[x for x in r['source_reads'] if x['table']=='hourly']
        self.assertEqual({c for x in reads for c in x['columns']},{'sku','sales'})
        self.assertTrue(all(x['sha256']==sha(self.ws.public/'business.sqlite') for x in reads))
    def test_02_independent_execution_dirs_and_old_run_write_denied(self):
        worker=self.ws.workers['analyst']
        a=worker.run("open('same.csv','w').write('x\\n1\\n')")
        b=worker.run("open('same.csv','w').write('x\\n1\\n')")
        self.assertNotEqual(a['execution_directory'],b['execution_directory'])
        one=Path(a['execution_directory'])/'same.csv';two=Path(b['execution_directory'])/'same.csv'
        self.assertEqual(sha(one),sha(two));self.assertNotEqual(a['code_file'],b['code_file'])
        r=worker.run(f"open({str(one)!r},'w').write('alter old execution')")
        self.assertFalse(r['ok']);self.assertEqual(one.read_text(),'x\n1\n')
    def test_03_stage_tool_permission_and_output_registration_do_not_change_task_key(self):
        roles=FrameworkRoles(self.ws,self.saver,lambda role:None)
        with self.assertRaisesRegex(ValueError,'unavailable'):self.ws.tool('verifier','run_experiment',{})
        task={'inputs':self.ws.state['base_source_paths']};before=self.ws.task_binding(task)
        path=self.ws.shared/'temporary_registered_input.csv';path.write_text('a\n1\n')
        self.ws.registered_sources.add(str(path))
        self.assertEqual(before,self.ws.task_binding(task))
        self.ws.registered_sources.remove(str(path))
    def test_03b_compact_view_preserves_source_columns_and_exact_definitions(self):
        task=self.ws.initial_context();self.assertNotIn('data_dictionary',task)
        dictionary=json.loads((self.ws.public/'data_dictionary.json').read_text())
        table=next(iter(dictionary['tables']));columns=list(dictionary['tables'][table]['columns'])[:3]
        result=self.ws.tool('analyst','read_field_definitions',{'table':table,'columns':columns})
        self.assertEqual(result['columns'],{c:dictionary['tables'][table]['columns'][c] for c in columns})
        reads=[{'path':'registered','sha256':'version','table':'table','columns':['a']}, {'path':'registered','sha256':'version','table':'table','columns':['b','a']}]
        grouped=self.ws.group_source_reads(reads)
        self.assertEqual(grouped,[{'path':'registered','sha256':'version','table':'table','columns':['a','b']}])
    def test_04_native_five_role_path_and_actual_original_access(self):
        # Fresh worker counts; other checks intentionally executed Python first.
        self.ws=ScientificWorkspace(self.root/'D002',OfficeWorld('relationship',7400))
        models={r:PolicyModel(ws=self.ws,role=r) for r in ('manager','analyst','verifier','mechanist','engineer','context')}
        roles=FrameworkRoles(self.ws,self.saver,lambda role:models[role])
        config={'configurable':{'thread_id':'scripted-business-science'},'recursion_limit':1000}
        score={'code_sha256':'fixture','mean_net_profit_per_site_day':1,'mean_fresh_waste_per_site_day':1,'site_days':1}
        with patch.object(self.ws,'evaluate_code',return_value=score):
            output=scientific_flow(roles,self.saver).invoke({},config)
        self.assertEqual(output['status'],'completed')
        self.assertEqual([t['role'] for t in self.ws.state['tasks']],['analyst','verifier','mechanist','verifier','engineer'])
        self.assertEqual(len(self.ws.state['hypotheses']),1);self.assertEqual(len(self.ws.state['experiments']),1);self.assertEqual(len(self.ws.state['algorithms']),1)
        self.assertEqual(self.ws.state['hypotheses'][0]['status'],'unresolved')
        self.assertTrue(self.ws.state['artifact_reviews'][0]['independent_source_reads'])
        self.assertEqual(self.ws.state['results'][-1]['selected_algorithm_id'],'baseline')
    def test_05_relocated_review_checks_current_copy_and_preserves_versions(self):
        original=ScientificWorkspace(self.root/'R001',OfficeWorld('relationship',7400))
        FrameworkRoles(original,self.saver,lambda role:None)
        code="import os,sqlite3,pandas as pd\nc=sqlite3.connect(os.environ['PUBLIC_DIR']+'/business.sqlite');f=pd.read_sql_query('SELECT sku,SUM(sales) units FROM hourly GROUP BY sku',c);f.to_csv('units.csv',index=False)"
        run=original.tool('analyst','run_python',{'code':code,'purpose':'generic source/version fixture','output_semantics':'recorded units per SKU'})
        published=original.tool('analyst','publish_analysis',{'primary_artifact':run['data_outputs'][0],'summary':'fixture','findings':[],'next_step':'review'})
        original.state['workflow'].update(phase='needs_review',latest_packet=published['packet_id']);original.persist()
        packet=original.tool('verifier','read_packet',{'packet_id':published['packet_id']})
        independent=original.tool('verifier','run_python',{'code':code,'purpose':'independent generic source read','output_semantics':'recorded units per SKU'})
        original.tool('verifier','review_artifact',{'artifact_id':packet['artifact_id'],'execution_id':independent['execution_id'],'decision':'accepted','checks':checks('accepted'),'summary':'scripted semantic fixture only'})
        old_entry=original.state['packets'][published['packet_id']]['artifact']['path']
        old_attachment=original.state['packets'][published['packet_id']]['attachments'][-1]['path']
        copy1=ScientificWorkspace(self.root/'R002',OfficeWorld('relationship',7400),resume_from=original.root)
        copy2=ScientificWorkspace(self.root/'R003',OfficeWorld('relationship',7400),resume_from=copy1.root)
        for name in ('business.sqlite','data_dictionary.json','history.csv','history.csv.meta.json'):
            self.assertEqual(sha(original.public/name),sha(copy2.public/name))
        self.assertEqual(copy2.readable(packet['artifact_id']),copy2.readable(old_entry))
        self.assertIsNotNone(copy2.current_review(old_entry))
        self.assertIsNotNone(copy2.packets.permitted_attachment(old_attachment))
        observation=copy2.workers['verifier'].run("from research_data import read_table\nprint(read_table('hourly')[['sku','sales']].shape)")
        self.assertTrue(observation['ok'],observation)
        self.assertTrue(any(x['path']==str(copy2.public/'business.sqlite') for x in observation['source_reads']))
        with sqlite3.connect(copy2.public/'business.sqlite') as db:db.execute('UPDATE hourly SET sales=sales+1 WHERE rowid=1')
        self.assertIsNone(copy2.current_review(old_entry))
        self.assertIsNotNone(original.current_review(old_entry))
    def test_06_review_projection_retains_checks_versions_and_raw_access(self):
        review={'id':'V999','decision':'rejected','checks':checks('rejected'),'summary':'actual negative finding','artifact_sha256':'exact_version',
          'independent_source_reads':[{'path':'raw','sha256':'v1','table':'t','columns':['a']}]*40+[{'path':'raw','sha256':'v1','table':'t','columns':['b']}]}
        view=self.ws.review_view(review)
        self.assertEqual(view['checks'],review['checks']);self.assertEqual(view['artifact_sha256'],review['artifact_sha256'])
        self.assertEqual(set(view['independent_source_reads'][0]['columns']),{'a','b'})
        self.assertLess(len(json.dumps(view)),len(json.dumps(review)))
        packet_view=self.ws.tool_response_view('manager','read_packet',{'latest_review':review,'accepted_review':review})
        self.assertEqual(packet_view['accepted_review'],{'id':'V999','details_in':'latest_review'})
    def test_07_stage_contract_names_actual_outputs_and_scientific_scope(self):
        ws=self.ws;previous=dict(ws.state['workflow'])
        try:
            ws.state['workflow'].update(phase='needs_validation',hypothesis_ids=['H_fixture'])
            card=ws.phase_contract()
            self.assertEqual(card['role'],'verifier');self.assertEqual(card['assigned_hypothesis_ids'],['H_fixture'])
            self.assertEqual(card['completion'],['record_verdict','finish_validation','request_assistance'])
            self.assertTrue(all(ws.tool_allowed_now(n) for n in card['completion']))
            self.assertFalse(ws.tool_allowed_now('finish_review'))
        finally:ws.state['workflow']=previous
    def test_08_native_incremental_publication_and_advisory_revision(self):
        ws=ScientificWorkspace(self.root/'I001',OfficeWorld('relationship',7400))
        models={r:InterleavedPolicyModel(ws=ws,role=r) for r in ('manager','analyst','verifier','mechanist','engineer','context')}
        roles=FrameworkRoles(ws,self.saver,lambda role:models[role])
        score={'code_sha256':'fixture','mean_net_profit_per_site_day':1,'mean_fresh_waste_per_site_day':1,'site_days':1}
        config={'configurable':{'thread_id':'scripted-incremental-science'},'recursion_limit':1000}
        with patch.object(ws,'evaluate_code',return_value=score):out=scientific_flow(roles,self.saver).invoke({},config)
        self.assertEqual(out['status'],'completed')
        self.assertEqual([t['role'] for t in ws.state['tasks']],['analyst','verifier','mechanist','verifier','mechanist','engineer'])
        self.assertEqual(ws.state['workflow']['validation_recommendation'],'revise_hypothesis')
        self.assertEqual(ws.state['hypotheses'][0]['status'],'unresolved')
        self.assertEqual(ws.state['research_progress'],{'H001':'evaluated','H002':'proposed'})
        self.assertEqual(out['step']['remaining_research_queue'][0]['hypothesis_id'],'H002')
        # Saving itself yielded immediately; no batch completion was necessary.
        self.assertFalse(any(e['tool']=='finish_hypotheses' for e in ws.state['events']))
        self.assertEqual(len(ws.state['algorithms']),1)
        before=len(ws.state['tasks']);again=scientific_flow(roles,self.saver).invoke(None,config)
        self.assertEqual(again['status'],'completed');self.assertEqual(len(ws.state['tasks']),before)
        # The immutable archive stays readable, with epistemic status explicit.
        archive=ws.tool('mechanist','read_artifact',{'path':str(ws.shared/'hypotheses/H002.json'),'offset':0})
        self.assertIn('not reviewed',archive['interpretation'])
        ws.state['workflow'].update(phase='needs_research_decision',hypothesis_ids=['H001'])
        history=ws.history_view('verifier')
        self.assertEqual([h['id'] for h in history['hypotheses']],['H001'])
        self.assertEqual([h['id'] for h in history['hypothesis_index']],['H001','H002'])
        with self.assertRaisesRegex(ValueError,'evidence_gap'):
            ws.tool('manager','schedule_task',{'role':'mechanist','question':'rewrite','inputs':[ws.state['workflow']['latest_packet']],'rationale':'fixture','hypothesis_ids':['H001']})
        ws.tool('manager','schedule_task',{'role':'mechanist','question':'revise one','inputs':[ws.state['workflow']['latest_packet']],'rationale':'fixture','hypothesis_ids':['H001'],'evidence_gap':'specific missing distinction'})
        with self.assertRaisesRegex(ValueError,'parent_id'):
            ws.tool('mechanist','save_hypothesis',{'parent_id':None})
        with self.assertRaisesRegex(ValueError,'parent_id'):
            ws.tool('mechanist','save_hypothesis',{'parent_id':'H002'})
        parent=ws.state['hypotheses'][0]
        child=ws.tool('mechanist','save_hypothesis',{k:parent[k] for k in ('explanation','scope','alternatives','prediction','falsification','evidence_files','change_reason')}|{'parent_id':'H001'})
        self.assertEqual(child['parent_id'],'H001');self.assertEqual(parent['status'],'unresolved')
        ws.state['workflow']['hypothesis_ids']=[child['id']]
        self.assertEqual([h['id'] for h in ws.history_view('mechanist')['hypotheses']],['H001','H003'])
        self.assertEqual(ws.state['research_progress']['H001'],'superseded')
    def test_08b_validation_focus_cannot_borrow_an_old_verdict_or_touch_other_candidates(self):
        ws=ScientificWorkspace(self.root/'F001',OfficeWorld('relationship',7400))
        FrameworkRoles(ws,self.saver,lambda role:None)
        ws.state['hypotheses']=[{'id':'H001','status':'unresolved','author':'mechanist','verdicts':[{'status':'unresolved'}]},
                               {'id':'H002','status':'proposed','author':'mechanist'}]
        ws.state['workflow'].update(phase='needs_research_decision')
        ws.tool('manager','schedule_task',{'role':'verifier','stage':'validation','question':'re-test one','inputs':[],
            'rationale':'specific decision gap','evidence_gap':'new counterexample needed','hypothesis_ids':['H001']})
        with self.assertRaisesRegex(ValueError,'new scoped verdict'):
            ws.tool('verifier','finish_validation',{'hypothesis_ids':['H001'],'next_action':'engineer','summary':'old verdict only'})
        with self.assertRaisesRegex(ValueError,'selected task hypotheses'):
            ws.tool('verifier','record_verdict',{'hypothesis_id':'H002'})
        self.assertEqual(ws.state['research_progress']['H002'],'proposed')
    def test_09_additional_analysis_returns_to_decision_without_expanding_hypotheses(self):
        ws=ScientificWorkspace(self.root/'A001',OfficeWorld('relationship',7400))
        FrameworkRoles(ws,self.saver,lambda role:None)
        old=ws.packets.create(ws.public/'history.csv','analyst')
        ws.state['workflow'].update(phase='needs_research_decision',latest_packet=old['id'])
        # Drive the real graph edges using role receipts; independent semantics
        # and numbers are deliberately outside this scheduling fixture.
        item=ws.tool('manager','schedule_task',{'role':'analyst','question':'resolve gap','inputs':[old['id']],
            'rationale':'specific data gap','evidence_gap':'time window needed for the algorithm decision','hypothesis_ids':[]})
        newer=ws.packets.create(ws.public/'products.csv','analyst')
        class Receipts:
            workspace=ws
            def run(self,role,task):
                if role=='manager':
                    if ws.state['workflow']['phase']=='needs_analysis':return item
                    if ws.state['workflow']['phase']=='needs_review':return {'kind':'scheduled_task','role':'verifier'}
                    self.phase_at_finish=ws.state['workflow']['phase']
                    return {'kind':'finished','selected_algorithm_id':'baseline'}
                return {'packet_id':newer['id']} if role=='analyst' else {'review_id':'V_fixture'}
        receipts=Receipts()
        with patch.object(ws.packets,'current_review',return_value={'decision':'accepted'}):
            scientific_flow(receipts,self.saver).invoke({}, {'configurable':{'thread_id':'scripted-analysis-return'}})
        self.assertEqual(receipts.phase_at_finish,'needs_research_decision')
        self.assertEqual(ws.state['hypotheses'],[])


class QueuePressureTests(unittest.TestCase):
    def state(self,n):
        return {'hypotheses':[{'id':f'H{i:03d}','status':'proposed','parent_id':None} for i in range(1,n+1)]}
    def test_pressure_increases_with_backlog_without_forbidding_exploration(self):
        low=self.state(1);high=self.state(10)
        estimate={'decision_gain':1,'information_gain':1,'effort_cost':1,'basis':'fixture'}
        a=assess_schedule(low,'mechanist',[],estimate);b=assess_schedule(high,'mechanist',[],estimate)
        self.assertLess(b['advisory_score'],a['advisory_score'])
        explore=assess_schedule(high,'mechanist',[],{**estimate,'information_gain':100})
        service=assess_schedule(high,'verifier',['H001'],estimate)
        self.assertGreater(explore['advisory_score'],service['advisory_score'])
        self.assertEqual(len(queue_view(high)['items']),10)
    def test_unresolved_is_scientific_status_and_can_still_reach_engineering(self):
        state=self.state(2);state['hypotheses'][0].update(status='unresolved',verdicts=[{'status':'unresolved'}])
        before=queue_view(state)['remaining_work_units']
        state['research_progress']['H001']='evaluated'
        self.assertLess(queue_view(state)['remaining_work_units'],before)
        self.assertEqual(state['hypotheses'][0]['status'],'unresolved')


if __name__=='__main__':unittest.main()
