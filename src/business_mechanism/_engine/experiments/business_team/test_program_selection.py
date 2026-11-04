"""Catalogue -> native terminal tool -> durable selection, no scientific grading."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver

from world import OfficeWorld
from scenario_contract import VERSION
from development_evaluation import describe, program
from workspace import ResearchWorkspace
from langgraph_migration.science import ScientificWorkspace
from langgraph_migration.runtime import FrameworkRoles
from test_langgraph_migration import ScriptedModel


class ProgramSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_selection_')
        cls.root = Path(cls.temp.name)
        cls.ws = ScientificWorkspace(cls.root/'scene', OfficeWorld('confounding', 9021, VERSION))
        cls.connection = sqlite3.connect(cls.root/'native.sqlite', check_same_thread=False)
        cls.saver = SqliteSaver(cls.connection)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        cls.temp.cleanup()

    def test_every_advertised_program_reaches_native_manager_delivery(self):
        ws = self.ws
        catalogue = describe(ws)['programs']
        for entry in catalogue:
            if not entry['selectable']:
                continue
            pid = entry['program_id']
            # A constructed completed-work precondition; not a model's scientific result.
            ws.state['workflow'].update(phase='ready_to_finish', hypothesis_ids=[])
            ws.state['engineering_selection'] = {'selected_algorithm_id': pid, 'task_id': 'engineering_fixture'}
            ws.persist()
            action = ('finish_research', {'selected_algorithm_id': pid,
                      'summary': 'Native selection-contract fixture; no scientific claim.',
                      'limitations': ['Constructed precondition, not an autonomous research result.']})
            model = ScriptedModel(sequence=[action])
            result = FrameworkRoles(ws, self.saver, lambda role: model).run('manager',
                {'id': 'selection_'+pid, 'question': 'Commit the actually advertised program identity.', 'inputs': []})
            self.assertEqual(result['selected_algorithm_id'], pid)
            stored = json.loads((ws.shared/'manager'/f"result_{result['result_number']:03d}.json").read_text())
            self.assertEqual(stored['selected_algorithm_id'], pid)
            self.assertEqual(program(ws, result['selected_algorithm_id']).resolve(), Path(entry['code_file']).resolve())
            self.assertEqual(model.calls, 1)

    def test_selection_policy_is_extensible_without_domain_program_names(self):
        class CatalogueWorkspace(ResearchWorkspace):
            def selectable_program_ids(self):
                return {'catalogued_controller'}
        ws = CatalogueWorkspace.__new__(CatalogueWorkspace)
        ws.root = self.root/'generic'
        ws.public, ws.shared = ws.root/'public', ws.root/'artifacts'
        (ws.shared/'manager').mkdir(parents=True, exist_ok=True)
        ws.public.mkdir(exist_ok=True)
        ws.state = {'results': [], 'algorithms': []}
        ws.operation = None
        result = ws.deliver('manager', {'selected_algorithm_id': 'catalogued_controller',
                            'summary': 'generic registry fixture', 'findings': [], 'evidence_files': [], 'next_step': 'done'})
        self.assertEqual(result['selected_algorithm_id'], 'catalogued_controller')
        with self.assertRaises(ValueError):
            ws.deliver('manager', {'selected_algorithm_id': 'unregistered_controller', 'evidence_files': []})


if __name__ == '__main__':
    unittest.main()
