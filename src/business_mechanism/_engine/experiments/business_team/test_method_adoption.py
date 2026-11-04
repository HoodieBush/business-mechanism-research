"""Input isolation and real native/sandbox contracts, not scientific ability tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from langgraph.checkpoint.sqlite import SqliteSaver

from run_method_adoption import (ROOT, MethodWorkspace, UnlimitedJournal, create_inputs)
from langgraph_migration.runtime import FrameworkRoles
from test_langgraph_migration import ScriptedModel, submission


class MethodAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix='unit_method_')
        self.root = Path(self.temp.name)
        self.literature = self.root/'source_paper'
        self.literature.mkdir()
        (self.literature/'mackinnon_nielsen_webb_2022.txt').write_text('Original-method fixture; not a task answer.')
        (self.literature/'mackinnon_nielsen_webb_2022.html').write_text('<article>Original-method fixture</article>')
        (self.literature/'source.json').write_text(json.dumps({'title': 'source fixture', 'url': 'https://example.invalid/source',
             'version': 'fixture', 'extraction': 'fixture for source-access checks, not an actual paper'}))
        self.source = ROOT/'experiments/business_team/results/development_langgraph_science_v09_20261014'

    def tearDown(self):
        self.temp.cleanup()

    def make(self, name='local', arm='local_only', case='M02'):
        directory = self.root/name
        create_inputs(directory, case, arm, self.source, self.literature)
        return MethodWorkspace(directory)

    def test_same_observations_question_and_dictionary_only_literature_differs(self):
        a = self.make()
        b = self.make('provided', 'provided_literature')
        for name in ('observations.csv', 'business.sqlite', 'task.json', 'data_dictionary.json', 'source_access.py'):
            self.assertEqual((a.public/name).read_bytes(), (b.public/name).read_bytes())
        self.assertEqual(json.loads((a.public/'literature_index.json').read_text()), [])
        self.assertEqual(len(json.loads((b.public/'literature_index.json').read_text())), 1)
        self.assertEqual(a.role_prompts, b.role_prompts)

    def test_counterpart_and_private_sources_are_not_readable_by_role_or_sandbox(self):
        a = self.make()
        b = self.make('provided', 'provided_literature')
        target = b.public/'literature/mackinnon_nielsen_webb_2022.txt'
        with self.assertRaisesRegex(ValueError, 'outside'):
            a.readable(target)
        code = ('import os\nfrom pathlib import Path\n'
                'assert (Path(os.environ["PUBLIC_DIR"])/"task.json").read_text()\n'
                f'try:\n    open({str(target)!r}).read()\n'
                'except PermissionError:\n    print("counterpart denied")\n'
                'else:\n    raise AssertionError("cross-condition leakage")\n')
        receipt = a.tool('verifier', 'run_python', {'code': code, 'purpose': 'isolation fixture', 'output_semantics': 'access check'}, 'unit_isolation')
        self.assertTrue(receipt['ok'], receipt.get('stderr'))
        self.assertIn('counterpart denied', receipt['stdout'])

    def test_original_business_observations_are_copied_without_value_or_grain_change(self):
        ws = self.make(case='M01')
        frame = pd.read_csv(ws.public/'observations.csv')
        self.assertEqual(len(frame), 320)
        for eid, program, condition in [('D0001', 'baseline', 'standard'), ('D0002', 'numeric_refit', 'standard'),
                                       ('D0003', 'baseline', 'replication_1'), ('D0004', 'numeric_refit', 'replication_1')]:
            original = pd.read_csv(self.source/f'B101/artifacts/development_evaluations/{eid}/site_days.csv')
            actual = frame[(frame.program == program) & (frame.condition == condition)][original.columns].reset_index(drop=True)
            pd.testing.assert_frame_equal(original, actual)
        binary = ws._tool('verifier', 'read_artifact', {'path': str(ws.public/'business.sqlite')})
        self.assertEqual(binary['format'], 'sqlite')

    def test_program_identity_export_preserves_label_code_receipt_and_condition(self):
        a=self.make(case='M01')
        b=self.make('provided','provided_literature',case='M01')
        from workspace import sha
        identity=json.loads((a.public/'program_identity.json').read_text())
        self.assertEqual((a.public/'program_identity.json').read_bytes(),(b.public/'program_identity.json').read_bytes())
        observations=pd.read_csv(a.public/'observations.csv')
        for eid,record in identity.items():
            original=self.source/f'B101/artifacts/development_evaluations/{eid}'
            self.assertEqual(sha(a.public/record['code_file']),record['code_sha256'])
            self.assertEqual((a.public/record['code_file']).read_bytes(),(b.public/record['code_file']).read_bytes())
            self.assertEqual(sha(original/'receipt.json'),record['source_receipt_sha256'])
            self.assertEqual(sha(original/'site_days.csv'),record['source_data_sha256'])
            selected=observations[(observations.program==record['program_label'])&(observations.condition==record['observation_condition'])]
            self.assertEqual(len(selected),len(pd.read_csv(original/'site_days.csv')))
        m04=self.make('missing_measurement',case='M04')
        self.assertEqual(identity,json.loads((m04.public/'program_identity.json').read_text()))

    def test_native_checkpoint_restart_does_not_repeat_delivered_analysis(self):
        ws = self.make()
        task = {'id': 'M_review', 'question': 'native fixture', 'inputs': [str(ws.public/'task.json')]}
        connection = sqlite3.connect(self.root/'native.sqlite', check_same_thread=False)
        try:
            model = ScriptedModel(sequence=[('read_context', {}), submission()])
            first = FrameworkRoles(ws, SqliteSaver(connection), lambda role: model).run('verifier', task)
            self.assertEqual(model.calls, 2)
        finally:
            connection.close()
        connection = sqlite3.connect(self.root/'native.sqlite', check_same_thread=False)
        try:
            resumed = MethodWorkspace(ws.root)
            never = ScriptedModel(sequence=[])
            second = FrameworkRoles(resumed, SqliteSaver(connection), lambda role: never).run('verifier', task)
            self.assertEqual(first, second)
            self.assertEqual(never.calls, 0)
        finally:
            connection.close()

    def test_unlimited_cost_view_is_valid_json_and_retains_usage(self):
        journal = UnlimitedJournal(self.root, {'model': 'fixture'})
        view = journal.public_view()
        self.assertIsNone(view['shared_admission_limit'])
        self.assertIsNone(view['remaining_admission_estimate'])
        self.assertEqual(view['reported_tokens'], 0)
        json.dumps(view, allow_nan=False)

    def test_backend_and_advertised_role_permissions_agree_for_text_adapter(self):
        ws = self.make()
        with self.assertRaisesRegex(ValueError, 'outside role permissions'):
            ws.tool('engineer', 'read_artifact', {'path': str(ws.public/'task.json')})
        response = ws.tool('verifier', 'read_artifact', {'path': str(ws.public/'task.json')})
        self.assertEqual(response['format'], 'utf-8 text')


if __name__ == '__main__':
    unittest.main()
