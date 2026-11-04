"""Explicit mode initializer, copied/versioned from the original constructor.

Cooperative MRO inserts this initializer between MemoryWorkspace and the old
Workspace; all research/storage methods stay reused. Neither old files nor
mode identities are patched or disguised as self.
"""
from pathlib import Path
import json
import sqlite3
from ..common import ROOT, sha, write_json
from ..workspace import Workspace
from ..environment import guard_path
from execution import PythonWorkspace


class ModeBase(Workspace):
    def __init__(self, root, question, world, settings, *, reopen=False):
        self.root = Path(root).resolve()
        guard_path(self.root)
        if settings.get('research_profile') != 'paired_research_v1' or settings.get('verification_mode') not in ('self', 'independent'):
            raise ValueError('paired_research_v1 requires explicit self or independent mode')
        self.public, self.science, self.private = [self.root / x for x in ('public', 'science', 'private')]
        self.environment = self.environment_class(world)
        sources = [ROOT / 'experiments' / 'insight_research' / n for n in
                   ('common.py', 'contracts.py', 'environment.py', 'workspace.py', 'runtime.py')]
        reused = json.loads((Path(__file__).parent.parent / 'reuse_manifest.json').read_text())
        if any(sha(ROOT / p) != h for p, h in reused['sha256'].items()):
            raise ValueError('reused source version changed; review and register a new implementation')
        identity = {'question': question, 'settings': settings, 'tool_contract': self.tool_schemas(),
                    'implementation': {str(p.relative_to(ROOT)): sha(p) for p in sources},
                    'reused_sources': reused['sha256'],
                    'paired_initializer': sha(Path(__file__)),
                    'environment_identity': {'kind': world.kind, 'seed': world.seed, 'version': world.scenario_version}}
        if not reopen:
            self.root.mkdir(parents=True, exist_ok=False)
            self.science.mkdir(); self.private.mkdir()
            self.environment.materialize(self.public)
            identity['public_inputs'] = {str(p.relative_to(self.public)): sha(p) for p in self.public.iterdir() if p.is_file()}
            write_json(self.private / 'identity.json', identity)
        else:
            frozen = json.loads((self.private / 'identity.json').read_text())
            if {k: v for k, v in frozen.items() if k != 'public_inputs'} != identity:
                raise ValueError('study identity changed; cannot silently resume')
            identity = frozen
            if any(sha(self.public / p) != h for p, h in identity['public_inputs'].items()):
                raise ValueError('public input changed; preserve old study and register new inputs')
        self.identity = identity
        self.question, self.settings = question, settings
        self.protocols = json.loads((self.public / 'experiment_contract.json').read_text())
        self.db = sqlite3.connect(self.private / 'records.sqlite')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS records(ref TEXT PRIMARY KEY, kind TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS files(ref TEXT PRIMARY KEY, path TEXT, hash TEXT, nature TEXT);
            CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY, signature TEXT, status TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        ''')
        with self.db:
            for p in self.public.iterdir():
                if p.is_file(): self.file_ref(p, 'public_seen')
        self.worker = PythonWorkspace(self.science / 'compute', self.public, self.science, per_execution=True)
        self._publish()
