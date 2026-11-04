"""Zero-HTTP mechanism contracts; scripted choices are not discovery evidence."""
import copy
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from execution import PythonWorkspace
from world import OfficeWorld
from workspace import sha
from langgraph_migration.mechanism_research import MechanismWorkspace, mechanism_flow, PROFILE, QUESTION
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles, TaskInputChangedError
from langgraph_migration.explicit_runtime import ExplicitRoles
from langgraph_migration.research_queue import view as queue_view
from langgraph_migration.coordination import view as coordination_view
from test_langgraph_migration import ScriptedModel
from run_mechanism_research import freeze_research, specification


def update(revision=0, **changes):
    return {'expected_revision':revision, 'understanding':'Observed records permit competing explanations; no mechanism yet established.',
        'alternatives':['conditional relationship','common cause','measurement issue'], 'hypothesis_ids':[], 'evidence_files':[],
        'learned':'Initial uncertainty is retained.', 'open_questions':['Which prediction distinguishes the explanations?'],
        'next_step':'Inspect or test the relevant evidence.', 'why_next':'Choose work that changes understanding.', **changes}


def schedule(role='mechanist', stage='hypotheses', **changes):
    return {'role':role, 'stage':stage, 'question':'State one scoped testable interpretation using received observations.',
        'inputs':[], 'hypothesis_ids':[], 'rationale':'Synthetic engineering fixture',
        'expected_information':'Distinguish explanations rather than complete a stage.', **changes}


def finish(**changes):
    return {'outcome':'inconclusive','summary':'Evidence remains insufficient.','conclusions':[],
            'limitations':['Synthetic engineering fixture, no scientific result.'],
            'next_questions':['Obtain a discriminating measurement.'], **changes}


class MechanismTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mechanism_contract_'); self.root=Path(self.temp.name)
        self.network=patch.object(http.client.HTTPConnection,'connect',side_effect=AssertionError('offline test attempted network'))
        self.network.start()

    def tearDown(self): self.network.stop(); self.temp.cleanup()

    def workspace(self, name='case', cls=MechanismWorkspace):
        def forecast(worker, code, history, features, name): return [3.]*len(features), {'fixture':True}
        with patch.object(PythonWorkspace,'forecast',new=forecast):
            ws=cls(self.root/name, OfficeWorld('confounding',9137,'office-business-v0.3'))
        FrameworkRoles(ws,None,lambda role:None)
        return ws

    def hypotheses(self, ws):
        ws.tool('manager','update_research_state',update())
        task=ws.tool('manager','schedule_task',schedule())
        h=ws.tool('mechanist','save_hypothesis',{'explanation':'Synthetic scoped prediction, not private truth.',
            'scope':'S01 in received recorded rows only','alternatives':['measurement dependence'],
            'prediction':'A specified comparison of recorded fields has a stated direction.',
            'falsification':'The defined comparison has the opposite direction.',
            'evidence_files':[str(ws.public/'history.csv')], 'change_reason':'initial fixture'})
        ws.observe_result(task,h); ws.tool('manager','update_research_state',update(1,hypothesis_ids=[h['id']]))
        return h

    def validation_task(self, ws, hid):
        return ws.tool('manager','schedule_task',schedule('verifier','validation',hypothesis_ids=[hid]))

    def test_original_observations_admit_hypothesis_without_mandatory_analysis_packet(self):
        ws=self.workspace(); self.assertEqual(ws.state.get('packets',{}),{})
        self.assertIn('mechanist',ws.workflow()['allowed_roles'])
        h=self.hypotheses(ws)
        self.assertEqual(h['status'],'proposed'); self.assertEqual(ws.state['algorithms'],[])

    def test_supervisor_must_incorporate_returned_result_before_new_decision(self):
        ws=self.workspace()
        with self.assertRaisesRegex(ValueError,'update_research_state'):ws.tool('manager','schedule_task',schedule())
        h=self.hypotheses(ws); task=self.validation_task(ws,h['id'])
        ws.observe_result(task,{'kind':'role_yield','reason':'execution unfinished'})
        with self.assertRaisesRegex(ValueError,'update_research_state'):ws.tool('manager','finish_research',finish())
        ws.tool('manager','update_research_state',update(2,learned='Execution was incomplete, not evidence against the hypothesis.'))
        result=ws.tool('manager','finish_research',finish())
        self.assertNotIn('selected_algorithm_id',result); self.assertEqual(result['outcome'],'inconclusive')

    def test_state_revision_and_original_source_changes_are_detected(self):
        ws=self.workspace(); p=ws.public/'products.csv'
        ws.tool('manager','update_research_state',update(evidence_files=[str(p)]))
        with self.assertRaisesRegex(ValueError,'revision changed'):ws.tool('manager','update_research_state',update())
        p.write_text(p.read_text()+'\n')
        self.assertEqual(ws.research_state_view()['stale_sources'],[str(p)])
        with self.assertRaisesRegex(ValueError,'update_research_state'):ws.tool('manager','finish_research',finish())

    def test_workspace_reopen_preserves_study_state_and_rejects_question_or_old_mode(self):
        ws=self.workspace(); ws.tool('manager','update_research_state',update(learned='retained counterexample marker'))
        before=copy.deepcopy(ws.research_state_view())
        other=MechanismWorkspace(ws.root,ws.world,reopen=True)
        self.assertEqual(other.research_state_view(),before)
        with self.assertRaises(TaskInputChangedError):MechanismWorkspace(ws.root,ws.world,reopen=True,research_question='different question')
        old=self.workspace('legacy',ScientificWorkspace); before=sha(old.shared/'research_history.json')
        with self.assertRaises(TaskInputChangedError):MechanismWorkspace(old.root,old.world,reopen=True)
        self.assertEqual(sha(old.shared/'research_history.json'),before)

    def test_private_label_paths_are_rejected_before_workspace_or_runner_setup(self):
        for name in ('Confounding','con-founding','con_founding'):
            with self.subTest(path=name):
                with self.assertRaisesRegex(TaskInputChangedError,'private world label'):
                    self.workspace(name)
                self.assertFalse((self.root/name).exists())
        base={'phase':'neutral','research_profile':PROFILE,'role_runtime':'explicit_v1',
            'explicit_runtime':{'memory_profile':'research_memory_v1'},'round_reported_token_budget':200000,
            'cases':[{'id':'M001','private_kind':'confounding','seed':1}]}
        for changes in ({'phase':'confounding_probe'},
                        {'output_directory':'experiments/results/Con_Founding'},
                        {'cases':[{'id':'Confounding','private_kind':'confounding','seed':1}]}):
            path=self.root/'spec.json';path.write_text(json.dumps({**base,**changes}))
            with self.assertRaisesRegex(TaskInputChangedError,'private world label'):
                specification(path)

    def test_new_hypothesis_does_not_retire_parent_or_reward_engineering(self):
        ws=self.workspace(); h=self.hypotheses(ws)
        ws.tool('manager','schedule_task',schedule(hypothesis_ids=[h['id']],evidence_gap='Narrow the interpretation after an open question.'))
        child=ws.tool('mechanist','save_hypothesis',{'explanation':'Revised candidate, still untested.','scope':'narrower received scope',
            'alternatives':['original explanation'],'prediction':'Different scoped prediction','falsification':'Opposite result',
            'evidence_files':[str(ws.public/'history.csv')],'change_reason':'new question','parent_id':h['id']})
        queue=queue_view(ws.state)
        self.assertEqual([r['progress'] for r in queue['items']],['proposed','proposed'])
        self.assertEqual(child['parent_id'],h['id']); self.assertIsNone(queue['potential'])

    def test_execution_failure_and_test_mismatch_do_not_create_a_refutation(self):
        for outcome in ('execution_failure','test_mismatch','measurement_gap','indistinguishable'):
            with self.subTest(outcome=outcome):
                ws=self.workspace(outcome); h=self.hypotheses(ws); task=self.validation_task(ws,h['id'])
                result=ws.tool('verifier','finish_validation',{'hypothesis_ids':[h['id']],'outcome_type':outcome,
                    'summary':'Original question not resolved.','evidence_files':[],
                    'limitations':['No matching discriminatory measurement.'],'suggested_next':'Correct the test or request a measurement.'})
                ws.observe_result(task,result)
                self.assertEqual(h['status'],'proposed'); self.assertFalse(h.get('verdicts'))
                self.assertEqual(ws.research_state_view()['latest_result_event']['feedback']['outcome_type'],outcome)
                self.assertTrue(ws.research_state_view()['update_required'])

    def test_support_and_refutation_require_fresh_matching_verdicts(self):
        for outcome,status in [('scoped_support','supported_in_scope'),('counterevidence','refuted')]:
            with self.subTest(outcome=outcome):
                ws=self.workspace(outcome); h=self.hypotheses(ws); self.validation_task(ws,h['id'])
                args={'hypothesis_ids':[h['id']],'outcome_type':outcome,'summary':'Synthetic conclusion',
                      'evidence_files':[str(ws.public/'history.csv')],'limitations':['Fixture only'],'suggested_next':'Examine competing explanations.'}
                with self.assertRaisesRegex(ValueError,'new matching scoped verdict'):ws.tool('verifier','finish_validation',args)
                ws.tool('verifier','record_verdict',{'hypothesis_id':h['id'],'status':status,'rationale':'Synthetic protocol fixture',
                        'evidence_files':[str(ws.public/'history.csv')]})
                result=ws.tool('verifier','finish_validation',args)
                self.assertEqual(result['validation_feedback']['subjects'][0]['prediction'],h['prediction'])
                self.assertEqual(queue_view(ws.state)['items'][0]['progress'],'tested')

    def test_supervisor_cannot_invent_supported_mechanism_or_unknown_evidence(self):
        ws=self.workspace(); h=self.hypotheses(ws)
        claim={'kind':'business_mechanism','hypothesis_id':h['id'],'status':'supported_in_scope','scope':h['scope'],
               'statement':'Unproven assertion','evidence_files':[str(ws.public/'history.csv')]}
        with self.assertRaisesRegex(ValueError,'actual matching verdict'):
            ws.tool('manager','finish_research',finish(outcome='research_completed',conclusions=[claim]))
        with self.assertRaises(ValueError):ws.tool('manager','update_research_state',update(2,evidence_files=['E999']))

    def test_controller_state_is_visible_in_new_manager_task_and_bounded_view(self):
        ws=self.workspace(); marker='cross-task counterexample marker'
        ws.tool('manager','update_research_state',update(learned=marker))
        roles=ExplicitRoles(ws,None,lambda role:None,memory_profile='research_memory_v1')
        from langgraph_migration.context_view import compile_view
        from langchain_core.messages import SystemMessage,HumanMessage
        task={'id':'new_control_task','question':QUESTION,'inputs':[]}
        state={'identity':{'input_versions':{},'task':task},'pending':False,'model_steps':0}
        messages=[SystemMessage(content='fixture'),HumanMessage(content='original')]
        request,meta=compile_view(ws,'manager',task,state,messages,[],{'coordination':coordination_view(ws)},196608)
        text='\n'.join(m.content for m in request)
        self.assertIn(marker,text); self.assertLess(meta['request_bytes'],196608)
        self.assertNotIn('hypothesis_snapshots',json.dumps(ws.research_state_view()))

    def test_actual_two_node_graph_recovers_pending_worker_and_closes_without_engineer(self):
        ws=self.workspace(); manager=ScriptedModel(sequence=[('update_research_state',update()),
            ('schedule_task',schedule('analyst','analysis',question='Inspect feasibility of the current measurement.')),
            ('update_research_state',update(1,learned='Original task is unfinished; no refutation.',next_step='Resume original task.')),
            ('resume_task',{'task_id':'T001'}),
            ('update_research_state',update(2,learned='Measurement unavailable; keep the scientific issue open.',next_step='Request new evidence.')),
            ('finish_research',finish(outcome='waiting_for_evidence',requested_measurements=['A genuinely independent observation.']))])
        analyst=ScriptedModel(sequence=['not delivered yet',('request_assistance',{'reason':'measurement unavailable',
            'needed_work':'Obtain independent evidence.','requested_capabilities':['measurement']})])
        with sqlite3.connect(self.root/'checkpoints.sqlite',check_same_thread=False) as conn:
            saver=SqliteSaver(conn); roles=ExplicitRoles(ws,saver,lambda role:manager if role=='manager' else analyst,
                memory_profile='research_memory_v1',slice_steps=1)
            graph=mechanism_flow(roles,saver); conf={'configurable':{'thread_id':'same-study'},'recursion_limit':40}
            result=graph.invoke({},conf)
            self.assertEqual(result['status'],'completed'); self.assertEqual(result['step']['outcome'],'waiting_for_evidence')
            self.assertEqual([t['role'] for t in ws.state['tasks']],['analyst']); self.assertEqual(analyst.calls,2)
            self.assertEqual(ws.state['mechanism_research']['revision'],3)
            seal=freeze_research(ws,result['step'])
            self.assertFalse(seal['algorithm_selection_required']); self.assertFalse(seal['final_profit_evaluation'])
            self.assertTrue((ws.root/'mechanism_report.json').exists()); self.assertEqual(ws.state['algorithms'],[])
            with self.assertRaises(ValueError):ws.tool('analyst','read_context',{})

    def test_update_operation_recovery_is_idempotent(self):
        ws=self.workspace(); args=update()
        first=ws.tool('manager','update_research_state',args,operation_id='same_update')
        receipt=ws.root/'tool_receipts/same_update.json'; data=json.loads(receipt.read_text())
        data['status']='prepared'; receipt.write_text(json.dumps(data))
        second=ws.tool('manager','update_research_state',args,operation_id='same_update')
        self.assertEqual(first,second); self.assertEqual(ws.state['mechanism_research']['revision'],1)

    def test_refutation_revises_a_hypothesis_then_retests_without_algorithm_stage(self):
        ws=self.workspace(); source=str(ws.public/'history.csv')
        first={'explanation':'Synthetic initial relationship','scope':'original fixture population','alternatives':['different scope'],
            'prediction':'Original recorded comparison is positive.','falsification':'Comparison is negative.',
            'evidence_files':[source],'change_reason':'initial fixture'}
        second={**first,'scope':'revised fixture population','prediction':'Revised comparison is positive.',
                'parent_id':'H001','change_reason':'Actual negative feedback motivates a narrower candidate.'}
        feedback=lambda hid,kind:{'hypothesis_ids':[hid],'outcome_type':kind,'summary':'Scripted engineering evidence only.',
            'evidence_files':[source],'limitations':['No independent scientific certification.'],
            'suggested_next':'Compare the remaining alternatives.'}
        verdict=lambda hid,status:('record_verdict',{'hypothesis_id':hid,'status':status,
            'rationale':'Scripted contract fixture','evidence_files':[source]})
        manager=ScriptedModel(sequence=[('update_research_state',update()),('schedule_task',schedule()),
            ('update_research_state',update(1,hypothesis_ids=['H001'])),
            ('schedule_task',schedule('verifier','validation',hypothesis_ids=['H001'])),
            ('update_research_state',update(2,learned='Original prediction was refuted; retain it and test a revised scope.')),
            ('schedule_task',schedule(hypothesis_ids=['H001'],evidence_gap='A narrower scoped prediction remains open.')),
            ('update_research_state',update(3,hypothesis_ids=['H001','H002'])),
            ('schedule_task',schedule('verifier','validation',hypothesis_ids=['H002'])),
            ('update_research_state',update(4,learned='Revised scope has support; parent refutation remains recorded.')),
            ('finish_research',finish(outcome='research_completed',conclusions=[{'kind':'business_mechanism',
                'hypothesis_id':'H002','status':'supported_in_scope','scope':second['scope'],
                'statement':'Scoped synthetic interpretation only.','evidence_files':[source]}]))])
        mechanist=ScriptedModel(sequence=[('save_hypothesis',first),('save_hypothesis',second)])
        verifier=ScriptedModel(sequence=[verdict('H001','refuted'),('finish_validation',feedback('H001','counterevidence')),
            verdict('H002','supported_in_scope'),('finish_validation',feedback('H002','scoped_support'))])
        roles=ExplicitRoles(ws,None,lambda role:{'manager':manager,'mechanist':mechanist,'verifier':verifier}[role],
            memory_profile='research_memory_v1')
        result=mechanism_flow(roles,None).invoke({}, {'recursion_limit':30})
        self.assertEqual(result['status'],'completed')
        self.assertEqual([t['role'] for t in ws.state['tasks']],['mechanist','verifier','mechanist','verifier'])
        self.assertEqual([h['status'] for h in ws.state['hypotheses']],['refuted','supported_in_scope'])
        self.assertEqual([r['progress'] for r in queue_view(ws.state)['items']],['tested','tested'])
        self.assertEqual(ws.state['algorithms'],[]); self.assertEqual(ws.state['mechanism_research']['revision'],5)

    def test_runner_rejects_legacy_profile_or_private_case_path_before_any_work(self):
        from run_mechanism_research import specification
        p=self.root/'spec.json'; p.write_text(json.dumps({'research_profile':'legacy'}))
        with self.assertRaises(ValueError):specification(p)
        example=Path(__file__).resolve().parents[2]/'configs/mechanism_research.example.json'
        spec=json.loads(example.read_text()); self.assertEqual(specification(example)['research_profile'],PROFILE)
        spec['cases'][0]['id']='../escape'; p.write_text(json.dumps(spec))
        with self.assertRaises(ValueError):specification(p)


if __name__=='__main__':unittest.main()
