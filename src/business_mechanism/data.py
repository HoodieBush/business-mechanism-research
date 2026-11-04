"""Read-only business SQLite input; no invented intervention capability."""
import json
from pathlib import Path
import shutil
import sqlite3
from experiments.insight_research.common import ROOT, digest, write_json, sha
from experiments.insight_research.growth_probe_v01.environment import Environment as BaseEnvironment


class SQLiteWorld:
    kind = 'business_sqlite'
    scenario_version = 'business-sqlite-v1'
    seed = 0

    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.parameters = {'instruments': [], 'input_sha256': {name: sha(self.folder/name)
            for name in ('business.sqlite', 'business_brief.md', 'data_dictionary.json')}}


class SQLiteEnvironment(BaseEnvironment):
    def materialize(self, public):
        public = Path(public); public.mkdir(parents=True, exist_ok=False)
        source = self.world.folder
        with sqlite3.connect((source/'business.sqlite').as_uri()+'?mode=ro', uri=True) as db, sqlite3.connect(public/'business.sqlite') as dest:
            db.backup(dest)
        shutil.copyfile(source/'business_brief.md', public/'business_brief.md')
        supplied = json.loads((source/'data_dictionary.json').read_text())
        tables = {}
        with sqlite3.connect((public/'business.sqlite').as_uri()+'?mode=ro', uri=True) as db:
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"):
                quoted = name.replace('"', '""')
                columns = [r[1] for r in db.execute('PRAGMA table_info("'+quoted+'")')]
                definitions = supplied.get('tables', {}).get(name, {})
                definitions = definitions.get('columns', definitions)
                tables[name] = {'columns': {column: definitions.get(column, 'No field definition supplied.') for column in columns}}
        write_json(public/'data_dictionary.json', {'database_file': 'business.sqlite', 'tables': tables,
                   'supplied_dictionary': supplied, 'schema_source': 'Observed SQLite schema; field definitions supplied by the data owner.'})
        shutil.copyfile(ROOT/'experiments/business_team/source_access.py', public/'source_access.py')
        write_json(public/'experiment_contract.json', {})
        write_json(public/'measurement_catalog.json', {'operations': {},
            'description': 'Only the supplied observational SQLite data are available. No physical interventions or new independent observations are installed.'})
        self.bind(public.parent/'private')
        write_json(self.state_path, {'identity': digest([self.world.seed, self.world.parameters]),
                                    'clock': 0, 'spent_credits': 0, 'actions': {}})

    def public_status(self):
        self.state()
        return {'input_mode': 'read_only_business_sqlite', 'new_measurement_operations': [],
                'observation_exposure': 'All supplied data are received; reuse does not create independent validation.'}

    def perform(self, *args, **kwargs):
        raise ValueError('No external measurement service installed. Analyze supplied data or report the needed measurement explicitly.')
