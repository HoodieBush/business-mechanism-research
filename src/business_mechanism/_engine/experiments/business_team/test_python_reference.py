"""Real helper signatures, file/schema distinction and native visibility; no API."""
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from python_reference import materialize,short_help
from execution import PythonWorkspace
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles
from world import OfficeWorld


class PythonReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='unit_python_reference_')
        self.root=Path(self.tmp.name).resolve();self.public=self.root/'public';self.public.mkdir()
        shutil.copyfile(Path(__file__).with_name('provenance.py'),self.public/'research_data.py')
        with sqlite3.connect(self.public/'business.sqlite') as con:
            con.execute('CREATE TABLE events (entity TEXT, period INTEGER, value REAL)')
            con.executemany('INSERT INTO events VALUES (?,?,?)',[('a',0,2),('a',1,3),('b',1,4)])
        (self.public/'joined.csv').write_text('entity,period,value,segment\na,0,2,x\na,1,3,x\nb,1,4,y\n')
        definitions={x:{'meaning':x,'unit':'fixture'} for x in ['entity','period','value']}
        (self.public/'data_dictionary.json').write_text(json.dumps({'version':'fixture','database_file':str(self.public/'business.sqlite'),
            'tables':{'events':{'columns':definitions,'row_grain':'entity x period'},'export_schema_only':{'columns':{},'row_grain':'CSV export'}}}))
    def tearDown(self):self.tmp.cleanup()

    def test_signatures_and_help_are_bound_to_actual_shipped_module(self):
        data=materialize(self.public)
        spec=importlib.util.spec_from_file_location('received_reference_fixture',self.public/'research_data.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(data['api_signatures']['read_table'],str(inspect.signature(module.read_table)))
        for name in ['__init__','to_pandas','to_csv','merge','groupby']:
            self.assertEqual(data['api_signatures']['Frame'][name],str(inspect.signature(getattr(module.Frame,name))))
        for name in ['columns','shape']:
            self.assertIsInstance(getattr(module.Frame,name),property)
            self.assertEqual(data['api_signatures']['Frame'][name],'property; access without ()')
        self.assertIsNotNone(inspect.getdoc(module.read_table))
        self.assertIsNotNone(inspect.getdoc(module.Frame.to_csv))
        self.assertIn('read_table(name)',short_help(data))
        self.assertIn('base_dir',short_help(data))
        self.assertLess(len(short_help(data)),1100)

    def test_actual_SQL_and_joined_CSV_structure_are_not_conflated(self):
        data=materialize(self.public)
        self.assertEqual(set(data['registered_sql_tables']),{'events'})
        self.assertEqual(data['registered_sql_tables']['events']['columns'],['entity','period','value'])
        self.assertEqual(data['csv_files']['joined.csv']['column_count'],4)
        self.assertEqual(data['csv_files']['joined.csv']['columns'][-1],'segment')
        self.assertNotIn('assign',data['api_signatures']['Frame'])

    def test_tool_definition_stays_identical_across_native_workspace_paths(self):
        descriptions=[];locations=[]
        for name in ['different_alpha','different_beta']:
            ws=ScientificWorkspace(self.root/name,OfficeWorld('confounding',92181,'office-business-v0.3'))
            FrameworkRoles(ws,None,lambda role:None)
            context=ws.initial_context();locations.append(context['python_api_reference'])
            data=ws.tool('analyst','read_artifact',{'path':context['python_api_reference']})
            self.assertIn('python-reference-v1',data['text'])
            manual=json.loads((ws.public/'tool_manual.json').read_text())
            descriptions.append(manual['tools'])
            self.assertNotIn(str(ws.public),manual['tools']['run_python']['description'])
        self.assertNotEqual(locations[0],locations[1])
        self.assertEqual(descriptions[0],descriptions[1])

    def test_reference_is_deterministic_and_refreshes_after_real_source_change(self):
        materialize(self.public);before=(self.public/'python_api.json').read_bytes()
        materialize(self.public);self.assertEqual(before,(self.public/'python_api.json').read_bytes())
        src=self.public/'research_data.py';src.write_text(src.read_text()+'\ndef received_extra(x, optional=7):\n    return x\n')
        new=materialize(self.public)
        self.assertEqual(new['api_signatures']['received_extra'],'(x, optional=7)')
        self.assertNotEqual(json.loads(before)['source_sha256'],new['source_sha256'])

    def test_actual_sandbox_executes_documented_tracked_and_pandas_paths(self):
        data=materialize(self.public)
        code=('import os,json\nfrom pathlib import Path\n'
              'api=json.loads(Path(os.environ["PUBLIC_DIR"]).joinpath("python_api.json").read_text())\n'
              'table_name="events"\ncsv_name="joined.csv"\ngroup_keys=["entity"]\nvalue_column="value"\n'
              'output_path=str(Path(os.environ["WORK_DIR"])/"tracked.csv")\noutput_meaning="sum of recorded fixture values by entity"\n'
              'exec(api["examples"]["registered_table_to_pandas"])\n'
              'exec(api["examples"]["tracked_aggregation"])\n'
              'exec(api["examples"]["CSV_to_pandas"])\n'
              'output_path=str(Path(os.environ["WORK_DIR"])/"ordinary.csv")\n'
              'exec(api["examples"]["ordinary_pandas_export"])\n'
              'print(df.shape)\n')
        result=PythonWorkspace(self.root/'worker',self.public,self.root/'shared').run(code)
        self.assertTrue(result['ok'],result)
        self.assertIn('(3, 4)',result['stdout'])
        outputs=[Path(p) for p in result['data_outputs']]
        self.assertIn('tracked.csv',[p.name for p in outputs])
        self.assertIn('ordinary.csv',[p.name for p in outputs])
        lineage=json.loads(next(p for p in Path(result['execution_directory']).glob('*.lineage.json')).read_text())
        self.assertEqual(lineage['verification_status'],'draft_not_semantically_verified')

    def test_reference_reachable_in_native_context_and_actual_tool_schema(self):
        ws=ScientificWorkspace(self.root/'W001',OfficeWorld('confounding',92181,'office-business-v0.3'))
        original={k:tuple(v) for k,v in ws.framework_role_tools.items()}
        roles=FrameworkRoles(ws,None,lambda role:None)
        context=ws.initial_context();path=Path(context['python_api_reference'])
        self.assertTrue(path.is_file())
        self.assertFalse(ws.requires_independent_review(path))
        response=ws.tool('analyst','read_artifact',{'path':str(path)})
        self.assertIn('python-reference-v1',response['text'])
        manual=json.loads((ws.public/'tool_manual.json').read_text())
        self.assertIn('read_table(name)',manual['tools']['run_python']['description'])
        self.assertIn('CSV',roles.descriptions['run_python'])
        self.assertEqual(original,{k:tuple(v) for k,v in ws.framework_role_tools.items()})
        self.assertNotIn('run_python',ws.framework_role_tools['mechanist'])
        self.assertNotIn('run_python',ws.framework_role_tools['manager'])


if __name__=='__main__':unittest.main()
