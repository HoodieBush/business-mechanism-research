"""Changed public/private study inputs must fail before model admission."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_langgraph_science import ROOT,run
from workspace import sha


class ScienceInputFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'experiments/business_team/results',prefix='unit_input_freeze_')
        self.root=Path(self.temp.name);(self.root/'C/public').mkdir(parents=True)
        self.public=self.root/'C/public/data.txt';self.public.write_text('original observation')
        self.private=self.root/'private_evaluation_plan.json';self.private.write_text('{}')
        self.spec=self.root/'spec.json';self.spec.write_text(json.dumps({'phase':self.root.name}))
        manifest={'source_sha256':{},'public_input_sha256':{'C':{'public/data.txt':sha(self.public)}},
                  'private_input_sha256':{self.private.name:sha(self.private)}}
        (self.root/'manifest.json').write_text(json.dumps(manifest))
    def tearDown(self):self.temp.cleanup()
    def test_changed_public_input_makes_no_model_journal(self):
        self.public.write_text('changed observation')
        with patch('run_langgraph_science.APIJournal') as journal:
            with self.assertRaisesRegex(ValueError,'public input changed'):run(self.spec,resume=True)
            journal.assert_not_called()
    def test_changed_private_plan_makes_no_model_journal(self):
        self.private.write_text('{"changed":true}')
        with patch('run_langgraph_science.APIJournal') as journal:
            with self.assertRaisesRegex(ValueError,'private evaluation plan changed'):run(self.spec,resume=True)
            journal.assert_not_called()
    def test_changed_installed_dependency_makes_no_model_journal(self):
        path=self.root/'manifest.json';manifest=json.loads(path.read_text())
        manifest['packages']={'pydantic':'deliberately-different-version'}
        path.write_text(json.dumps(manifest))
        with patch('run_langgraph_science.APIJournal') as journal:
            with self.assertRaisesRegex(ValueError,'installed dependency changed'):run(self.spec,resume=True)
            journal.assert_not_called()


if __name__=='__main__':unittest.main()
