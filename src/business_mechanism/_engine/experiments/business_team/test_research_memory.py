"""Scripted, zero-HTTP contracts. No autonomous research capability claim."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
import test_minimal_research as fixtures
from test_langgraph_migration import ScriptedModel
from langgraph_migration.explicit_runtime import ExplicitRoles
from langgraph_migration.runtime import TaskInputChangedError
from langgraph_migration import research_memory as memory
from workspace import write_json


class ResearchMemoryTests(unittest.TestCase):
    workspace = fixtures.MinimalResearchTests.workspace
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='research_memory_')
        self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def roles(self, ws, model=None, **kwargs):
        return ExplicitRoles(ws, None, lambda role:model, memory_profile=memory.PROFILE, **kwargs)
    def task(self, name='research'):
        return {'id':name,'question':'Investigate S01; keep alternatives, original day < 84 and uncertainty.',
                'inputs':[], 'execution_phase':'needs_analysis'}
    def hypotheses(self, ws, count=1):
        for i in range(count):
            h={'id':f'H{i+1:03d}', 'author':'mechanist', 'explanation':f'S01 candidate {i}: consider counterexample',
               'scope':'original site and price', 'prediction':'day < 84, recorded sales only',
               'alternatives':['supply censoring','preference change'], 'falsification':'specified counterexample',
               'status':'refuted' if i%2 else 'unresolved', 'parent_id':None,
               'evidence_files':[str(ws.public/'history.csv')], 'verdicts':[]}
            ws.state['hypotheses'].append(h)
            write_json(ws.shared/'hypotheses'/(h['id']+'.json'),h)
        ws.persist()
    def test_opt_in_policy_and_registry_cannot_change_an_existing_workspace(self):
        ws=self.workspace(); ExplicitRoles(ws,None,lambda role:None)
        with self.assertRaises(TaskInputChangedError):self.roles(ws)
        other=self.workspace('memory');roles=self.roles(other)
        self.assertIn('save_working_note',roles.role_tools['analyst'])
        self.assertNotIn('save_working_note',ws.framework_role_tools['analyst'])
        with self.assertRaises(TaskInputChangedError):ExplicitRoles(other,None,lambda role:None)
    def test_paged_catalog_keeps_negative_candidates_and_allows_different_scope(self):
        ws=self.workspace();self.roles(ws);self.hypotheses(ws,25)
        first=ws.tool('analyst','search_memory',{'query':'counterexample','kind':'hypothesis','scope':'new price','limit':3})
        self.assertEqual(first['total'],25);self.assertEqual(len(first['items']),3)
        self.assertTrue(all(r['scope_differences'] for r in first['items']))
        seen=[r['object_ref'] for r in first['items']];cursor=first['next_cursor']
        while cursor:
            page=ws.tool('analyst','search_memory',{'query':'counterexample','kind':'hypothesis','scope':'new price','limit':3,'cursor':cursor})
            seen += [r['object_ref'] for r in page['items']];cursor=page['next_cursor']
        self.assertEqual(len(set(seen)),25)
        self.assertIn('refuted',{r['recorded_status'] for r in memory.search(ws,'analyst',kind='hypothesis',limit=12)['items']})
        before=memory.search(ws,'analyst',kind='hypothesis')
        for p in (ws.root/'research_memory').glob('catalog_*.json'):p.unlink()
        self.assertEqual(memory.search(ws,'analyst',kind='hypothesis'),before)
        ws.state['hypotheses'][0]['prediction']='changed original object'
        with self.assertRaisesRegex(ValueError,'page changed'):
            memory.search(ws,'analyst',query='counterexample',kind='hypothesis',scope='new price',limit=3,cursor=first['next_cursor'])
    def test_full_object_pages_pin_version_and_preserve_original_prediction(self):
        ws=self.workspace();self.roles(ws);self.hypotheses(ws)
        h=ws.state['hypotheses'][0];h['explanation']='long reasoning '*2200
        first=memory.read(ws,'analyst','hypothesis:H001');text=first['text'];offset=first['next_offset']
        while offset:
            part=memory.read(ws,'analyst','hypothesis:H001',offset,first['version'])
            text += part['text'];offset=part['next_offset']
        self.assertEqual(json.loads(text)['prediction'],'day < 84, recorded sales only')
        with self.assertRaisesRegex(ValueError,'requires first-page'):memory.read(ws,'analyst','hypothesis:H001',1)
        h['prediction']='different prediction'
        with self.assertRaisesRegex(ValueError,'changed'):memory.read(ws,'analyst','hypothesis:H001',12000,first['version'])
    def test_private_note_trace_and_receipts_do_not_reenter_shared_history(self):
        ws=self.workspace();marker='PRIVATE_REASONING_MUST_NOT_BE_SHARED'
        model=ScriptedModel(sequence=[('save_working_note',{'summary':marker,'source_refs':[],
            'open_questions':['still unknown'],'next_steps':['test alternatives']}),'unfinished'])
        roles=self.roles(ws,model);result=roles.run('analyst',self.task())
        note=memory.notes_for(ws,'analyst')[0]
        self.assertNotIn(marker,(ws.shared/'research_history.json').read_text())
        for p in ws.shared.rglob('*.json'):self.assertNotIn(marker,p.read_text(),str(p))
        self.assertEqual(json.loads(memory.read(ws,'analyst',note['object_ref'])['text'])['summary'],marker)
        checkpoint=json.loads(Path(result['checkpoint']).read_text())
        thread=Path(result['checkpoint']).stem;ref=f'trace:{thread}:{len(checkpoint["messages"])}'
        first=memory.read(ws,'analyst',ref);text=first['text'];offset=first['next_offset']
        while offset:
            part=memory.read(ws,'analyst',ref,offset,first['version'])
            text+=part['text'];offset=part['next_offset']
        self.assertTrue(marker in text)
        for ref in [note['object_ref'],ref]:
            with self.assertRaises(ValueError):memory.read(ws,'verifier',ref)
        for p in (ws.root/'research_memory').rglob('*.json'):
            with self.assertRaisesRegex(ValueError,'outside'):roles.execute('verifier','read_artifact',{'path':str(p)})
        with self.assertRaisesRegex(ValueError,'manager'):memory.read(ws,'analyst','coordination')
    def test_note_source_correction_marks_review_without_changing_scientific_status(self):
        ws=self.workspace();self.hypotheses(ws)
        data=ws.shared/'analyst'/'measurement.csv';data.write_text('value\n1\n')
        model=ScriptedModel(sequence=[('save_working_note',{'summary':'tentative comparison','source_refs':[str(data),'hypothesis:H001'],
            'open_questions':['interpretation unknown'],'next_steps':[]}),'unfinished'])
        self.roles(ws,model).run('analyst',self.task())
        note=memory.notes_for(ws,'analyst')[0]
        data.write_text('value\n2\n');ws.state['hypotheses'][0]['prediction']='revised source object'
        status=memory.note_dependencies(ws,'analyst',note)
        self.assertEqual(status['dependency_state'],'needs_review')
        self.assertEqual(set(status['changed_dependencies']),{str(data),'hypothesis:H001'})
        row=memory.search(ws,'analyst',kind='working_note')['items'][0]
        self.assertEqual(row['dependency_state'],'needs_review')
        self.assertEqual(ws.state['hypotheses'][0]['status'],'unresolved')
    def test_growing_history_rotates_views_preserves_notes_and_raw_prefixes(self):
        ws=self.workspace();self.hypotheses(ws,100)
        model=ScriptedModel(sequence=[('save_working_note',{'summary':'day < 84; competing explanations remain open',
            'source_refs':['hypothesis:H001'],'open_questions':['censoring or preference?'],'next_steps':['compare predictions']})]+
            ['long private interpretation '+('research detail '*1200) for _ in range(12)]+
            [('request_assistance',{'reason':'new measurement needed','needed_work':'discriminate explanations','requested_capabilities':['measurement']})])
        roles=self.roles(ws,model,max_request_bytes=65000,recent_turns=2)
        original=ScriptedModel._generate;requests=[]
        def generate(instance,messages,**kwargs):
            requests.append(messages)
            return original(instance,messages,**kwargs)
        prefixes=[]
        with patch.object(ScriptedModel,'_generate',new=generate):
            for _ in range(20):
                result=roles.run('analyst',self.task())
                path=next((ws.root/'explicit_runtime_state/analyst').glob('*.json'))
                raw=json.loads(path.read_text())
                if prefixes:self.assertEqual(raw['messages'][:len(prefixes[-1])],prefixes[-1])
                prefixes.append(raw['messages'])
                if result.get('kind')=='assistance_requested':break
        self.assertEqual(result['kind'],'assistance_requested')
        views=[json.loads(line) for line in path.with_suffix('.views.jsonl').read_text().splitlines()]
        self.assertEqual(raw['model_steps'],14);self.assertEqual(model.calls,14)
        self.assertGreater(views[-1]['epoch'],2)
        self.assertTrue(all(v['request_bytes']<=65000 for v in views))
        self.assertGreater(views[-1]['raw_request_bytes'],65000)
        self.assertIn('day < 84',''.join(str(m.content) for m in requests[-1]))
        self.assertIn('censoring or preference?',''.join(str(m.content) for m in requests[-1]))
        trace=memory.read(ws,'analyst','trace:'+path.stem)
        self.assertEqual(len(trace['object_ref'].split(':')),3)
        old_ref=trace['object_ref'];old_version=trace['version']
        # Reading an older prefix survives future appends and pagination.
        self.assertEqual(memory.read(ws,'analyst',old_ref,0,old_version)['version'],old_version)
        self.assertEqual(ws.state['hypotheses'][0]['prediction'],'day < 84, recorded sales only')
    def test_search_cursor_survives_its_own_trace_growth(self):
        ws=self.workspace();self.hypotheses(ws,20)
        model=ScriptedModel(sequence=[('search_memory',{'limit':2}),'unfinished'])
        self.roles(ws,model).run('analyst',self.task())
        event=json.loads((ws.root/'framework_tools.jsonl').read_text().splitlines()[0])
        cursor=event['feedback']['result']['next_cursor']
        page=memory.search(ws,'analyst',limit=2,cursor=cursor)
        self.assertEqual(len(page['items']),2)
    def test_interrupted_paid_batch_does_not_repeat_note_or_call_model(self):
        ws=self.workspace();model=ScriptedModel(sequence=[])
        response=AIMessage(content='',tool_calls=[{'name':'save_working_note','args':{'summary':'unique preserved reasoning',
            'source_refs':[],'open_questions':[],'next_steps':[]},'id':'note','type':'tool_call'},
            {'name':'read_history','args':{},'id':'history','type':'tool_call'}])
        roles=self.roles(ws,model,slice_tools=2)
        result=ChatResult(generations=[ChatGeneration(message=response)])
        with patch.object(ScriptedModel,'_generate',return_value=result) as generate:
            with patch.object(ws,'event',side_effect=RuntimeError('controlled interruption after tool commit')):
                with self.assertRaisesRegex(RuntimeError,'controlled interruption'):roles.run('analyst',self.task())
            self.assertEqual(len(memory.notes_for(ws,'analyst')),1)
            output=roles.run('analyst',self.task())
        self.assertEqual(generate.call_count,1);self.assertEqual(len(memory.notes_for(ws,'analyst')),1)
        self.assertEqual(output['status'],'pending')
        self.assertEqual([e['tool'] for e in ws.state['events']],['save_working_note','read_history'])
        self.assertTrue(all(e['result']['ok'] for e in ws.state['events']))
    def test_history_page_passes_the_real_response_adapter_successfully(self):
        ws=self.workspace();roles=self.roles(ws);self.hypotheses(ws,20)
        content,artifact=roles.execute('analyst','read_history',{'limit':3})
        visible=json.loads(content)
        self.assertTrue(artifact['feedback']['ok'])
        self.assertEqual(len(visible['result']['items']),3)
        self.assertIsNotNone(visible['result']['next_cursor'])
    def test_input_changes_after_rotation_are_still_rejected(self):
        ws=self.workspace();model=ScriptedModel(sequence=['not done'])
        roles=self.roles(ws,model);task=self.task();roles.run('analyst',task)
        with self.assertRaises(TaskInputChangedError):roles.run('analyst',{**task,'question':'silently replace original research'})
        p=ws.public/'products.csv';p.write_text('changed input')
        with self.assertRaises(TaskInputChangedError):roles.run('analyst',task)
        self.assertEqual(model.calls,1)
    def test_source_correction_propagates_to_dependent_notes_without_erasing_them(self):
        ws=self.workspace();p=ws.shared/'analyst'/'data.csv';p.write_text('x\n1\n')
        model=ScriptedModel(sequence=[('save_working_note',{'summary':'first observation','source_refs':[str(p)]}),
            ('save_working_note',{'summary':'tentative next interpretation','source_refs':['note:analyst:00001']}),'unfinished'])
        self.roles(ws,model).run('analyst',self.task())
        p.write_text('x\n2\n')
        page=memory.search(ws,'analyst',kind='working_note')
        self.assertEqual(len(page['items']),2)
        self.assertTrue(all(row['dependency_state']=='needs_review' for row in page['items']))
        self.assertEqual(len(memory.notes_for(ws,'analyst')),2)


if __name__ == '__main__': unittest.main()
