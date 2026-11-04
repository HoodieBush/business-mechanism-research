"""Isolated reviewer state and tools over a frozen lawful evidence projection."""
import json
from pathlib import Path
import sqlite3
import uuid

from ..common import Pending, digest, encoded, now, sha, write_json
from ..environment import guard_path
from ..workspace import Workspace
from .contracts import TOOLS, schemas
from .snapshot import EvidenceView
from execution import PythonWorkspace


class CriticWorkspace:
    tools = TOOLS
    execute_python = Workspace.execute_python
    attachments = Workspace.attachments

    def tool_schemas(self): return schemas()

    def __init__(self, root, snapshot, settings, *, reopen=False):
        self.root = Path(root).resolve(); guard_path(self.root)
        self.view = EvidenceView(snapshot)
        if self.root.is_relative_to(self.view.root) or self.view.root.is_relative_to(self.root):
            self.view.close(); raise ValueError('critic output and read-only evidence must be separate trees')
        self.packet = json.loads((self.view.root / 'packet.json').read_text())
        self.public = self.view.root / 'public'
        self.science, self.private = self.root / 'artifacts', self.root / 'private'
        self.settings = settings
        self.question = self.packet['original_question']
        sources = {str(p.name): sha(p) for p in Path(__file__).parent.iterdir() if p.suffix in ('.py', '.txt') and p.is_file()}
        identity = {'profile': 'critic_m0_v1', 'settings': settings,
            'packet_digest': digest(self.packet), 'snapshot_manifest_sha256': sha(self.view.root / 'manifest.json'),
            'sources': sources, 'tool_contract': self.tool_schemas()}
        if not reopen:
            self.root.mkdir(parents=True, exist_ok=False)
            self.science.mkdir(); self.private.mkdir()
            write_json(self.private / 'identity.json', identity)
        elif json.loads((self.private / 'identity.json').read_text()) != identity:
            self.view.close(); raise ValueError('critic identity changed; register a new task')
        self.identity = identity
        self.db = sqlite3.connect(self.private / 'critic.sqlite')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS records(ref TEXT PRIMARY KEY,kind TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS files(ref TEXT PRIMARY KEY,path TEXT,hash TEXT,nature TEXT);
            CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY,signature TEXT,result TEXT);
            CREATE TABLE IF NOT EXISTS actions(ref TEXT PRIMARY KEY,body TEXT);
        ''')
        self.worker = PythonWorkspace(self.science / 'compute', self.public, self.view.root, per_execution=True)
        self.worker.readonly_input_roots = (self.science,)
        self._publish()

    def close(self):
        self.db.close(); self.view.close()

    def records(self, kind):
        return [json.loads(x[0]) for x in self.db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid', (kind,))]

    def state(self):
        items = self.records('checkpoint')
        return items[-1] if items else None

    def report(self):
        items = self.records('review')
        return items[-1] if items else None

    def _publish(self):
        for ref, body in self.db.execute('SELECT ref,body FROM records'):
            path = self.science / 'reviews' / (ref + '.json')
            if path.exists() and json.loads(path.read_text()) != json.loads(body): raise Pending('published review changed')
            if not path.exists(): write_json(path, json.loads(body))

    def context(self):
        local = json.loads((self.private / 'transport.json').read_text()) if (self.private / 'transport.json').exists() else {}
        continuation = json.loads((self.private / 'continuation.json').read_text()) if (self.private / 'continuation.json').exists() else None
        return {'role': 'critic', 'review_task': self.packet, 'packet_digest': self.identity['packet_digest'],
            'saved_checkpoint': self.state(),
            'continuation': continuation,
            'directories': ['directory:related', 'directory:results', 'directory:all'],
            'paths': {'PUBLIC_DIR': str(self.public), 'ARTIFACT_DIR': str(self.view.root), 'python_write': 'WORK_DIR only'},
            'resources': {'limits': self.settings['limits'], 'local_accounted_tokens': local.get('accounted_tokens', 0),
                'http_attempts_started': local.get('attempts', 0),
                'remaining_http_attempts': max(0, self.settings['limits']['max_http_attempts'] - local.get('attempts', 0))},
            'records_are_claims': 'Source assertions and lifecycle eligibility are not certified scientific truth.'}

    def file_ref(self, path, nature='review_computation'):
        path = Path(path).resolve()
        if path.is_relative_to(self.view.root):
            relative = str(path.relative_to(self.view.root))
            row = self.view.db.execute('SELECT ref FROM files WHERE path=?', (relative,)).fetchone()
            if not row: raise ValueError('received evidence-file reference required')
            _, source_nature = self.view.file(row[0])
            return {'ref': row[0], 'path': str(path), 'sha256': sha(path), 'nature': source_nature}
        if not path.is_relative_to(self.science) or not path.is_file(): raise ValueError('file outside critic artifact directory')
        relative, version = str(path.relative_to(self.root)), sha(path)
        ref = 'file:' + digest(['critic', relative, version])[:24]
        self.db.execute('INSERT OR IGNORE INTO files VALUES (?,?,?,?)', (ref, relative, version, nature))
        return {'ref': ref, 'path': str(path), 'sha256': version, 'nature': nature}

    def file(self, ref):
        row = self.db.execute('SELECT path,hash,nature FROM files WHERE ref=?', (ref,)).fetchone()
        if not row: return self.view.file(ref)
        path = (self.root / row[0]).resolve()
        if not path.is_relative_to(self.science) or sha(path) != row[1]: raise Pending('critic artifact version changed')
        return path, row[2]

    def record(self, ref):
        row = self.db.execute('SELECT body FROM records WHERE ref=?', (ref,)).fetchone()
        return json.loads(row[0]) if row else self.view.record(ref)

    def action(self, ref):
        row = self.db.execute('SELECT body FROM actions WHERE ref=?', (ref,)).fetchone()
        if not row: raise ValueError('actual action_ref from this critic task required')
        return json.loads(row[0])

    def references(self, refs):
        for ref in refs:
            if ref.startswith('file:'): self.file(ref)
            elif ref.startswith('check:'): self.action(ref)
            elif ref.startswith(('card:', 'directory:')): self.read(ref, 0, 1, memory=True)
            else: self.record(ref)

    def read(self, ref, offset, limit, *, memory=False):
        if ref.startswith(('process:', 'event:')):
            raise ValueError('Owner conversations are excluded. Use action: references for filtered operation facts.')
        if ref.startswith('directory:'):
            directories = json.loads((self.view.root / 'directories.json').read_text())
            name = ref.removeprefix('directory:')
            if name not in directories: raise ValueError('received directory required')
            # Directory text is paged with the same exact-read interface. Count
            # and complete ordering are retained, never a hidden latest-N list.
            item = {'ref': ref, 'total': len(directories[name]), 'refs': directories[name]}
        elif ref.startswith('check:'): item = self.action(ref)
        elif ref.startswith('card:'):
            h = self.view.record(ref[5:])
            if h['record_type'] != 'hypothesis': raise ValueError('hypothesis required')
            item = {'ref': ref, 'original_hypothesis': h, 'lifecycle': self.view.review(ref[5:]),
                'all_linked_records': self.view.search(hypothesis_ref=ref[5:], limit=8),
                'coverage': 'First page only; use search_memory to continue; unlinked old knowledge needs global search.'}
        elif ref.startswith('file:'):
            result = Workspace.read(self, ref, offset, limit, memory=False)
            result['compute_path'] = str(self.file(ref)[0])
            return result
        else:
            item = self.record(ref)
            if not ref.startswith('Q'):
                item = {**item, 'lifecycle': self.view.review(ref), 'original_version': self.view.manifest['record_original_versions'].get(ref)}
        text = encoded(item); end = offset + limit
        return {'ref': ref, 'sha256': digest(item), 'text': text[offset:end], 'next_offset': end if end < len(text) else None}

    def call(self, name, args, operation_id):
        if name not in self.tools: raise ValueError('unknown critic tool')
        args = self.tools[name][0].model_validate(args).model_dump()
        if not operation_id: raise ValueError('durable operation identity required')
        signature = digest([name, args])
        prior = self.db.execute('SELECT signature,result FROM operations WHERE key=?', (operation_id,)).fetchone()
        if prior:
            if prior[0] != signature: raise ValueError('operation identity reused with changed arguments')
            self._publish(); return json.loads(prior[1])
        if self.report(): raise ValueError('review complete; no additional actions')
        try:
            with self.db:
                result = self.dispatch(name, args, operation_id)
                action_ref = 'check:' + digest(operation_id)[:24]
                result = {**result, 'action_ref': action_ref}
                self.db.execute('INSERT INTO actions VALUES (?,?)', (action_ref,
                    encoded({'tool': name, 'arguments': args, 'result': result})))
                self.db.execute('INSERT INTO operations VALUES (?,?,?)', (operation_id, signature, encoded(result)))
            self._publish(); return result
        except (ValueError, TypeError, sqlite3.Error) as error:
            result = {'ok': False, 'error': str(error)}
            with self.db:
                self.db.execute('INSERT INTO operations VALUES (?,?,?)', (operation_id, signature, encoded(result)))
            return result

    def dispatch(self, name, args, key):
        if name in ('read_memory', 'read_artifact'): return self.read(**args, memory=name == 'read_memory')
        if name == 'search_memory': return self.view.search(**args)
        if name == 'query_data':
            directory = self.science / 'queries' / digest(key)[:24]
            receipt = directory / 'tool_result.json'
            if directory.exists():
                if not receipt.exists(): raise Pending('interrupted query without receipt; inspect before replay')
                result = json.loads(receipt.read_text())
                if result['sql'] != args['sql'] or result['purpose'] != args['purpose']: raise Pending('query receipt identity differs')
                for item in (result['file'], result['source'], result['receipt']):
                    if sha(Path(item['path'])) != item['sha256']: raise Pending('query receipt source/output changed')
                    self.file_ref(item['path'])
                return result
            result = Workspace.dispatch(self, name, args, key)
            write_json(receipt, result)
            return result
        if name == 'run_python':
            receipt = self.execute_python(args['code'], key)
            return {'purpose': args['purpose'], 'execution': receipt, 'files': self.attachments(receipt),
                'evidence_nature': 'review_computation_on_seen_data'}
        if name == 'record_review':
            self.references(args['source_refs'])
            declared = {issue['issue_id'] for issue in args['issues']}
            if len(declared) != len(args['issues']) or not set(args['open_issue_ids']) <= declared:
                raise ValueError('unique issue IDs and open_issue_ids contained in issues required')
            for check in args['checks_performed']:
                self.action(check['action_ref']); self.references(check['artifact_refs'])
            for issue in args['issues']:
                for ref in issue['action_refs']: self.action(ref)
                self.references(issue['check_artifact_refs'])
                if issue['type'] == 'reproduced_contradiction' and not issue['action_refs']:
                    raise ValueError('reproduced contradiction requires an actual check action, not a claimed computation')
            kind = 'review' if args['phase'] == 'complete' else 'checkpoint'
            item = {'ref': 'Q' + uuid.uuid4().hex[:16], 'record_type': kind, 'author': 'critic',
                'created_at': now(), 'target_ref': self.packet['target_ref'], 'target_version': self.packet['target_version'],
                'packet_digest': self.identity['packet_digest'], 'scientific_certification': False, **args}
            self.db.execute('INSERT INTO records VALUES (?,?,?)', (item['ref'], kind, encoded(item)))
            return item
        raise ValueError('unknown critic action')
