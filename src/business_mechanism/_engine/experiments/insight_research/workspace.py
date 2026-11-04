"""Research records, shared access policy, executable tests and durable receipts.

Private SQLite is the transaction authority. Published records are immutable
materializations. Tool result + record changes commit together; side effects
have a predeclared recovery receipt and never blindly rerun after interruption.
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from .common import ROOT, Pending, digest, encoded, now, sha, write_json
from .contracts import TOOLS, schemas
from .environment import Environment, guard_path
from execution import PythonWorkspace
from experiment_plans import match_changed_variables


class Workspace:
    tools = TOOLS
    environment_class = Environment

    def tool_schemas(self):
        return schemas()

    def __init__(self, root, question, world, settings, *, reopen=False):
        self.root = Path(root).resolve()
        guard_path(self.root)
        if settings.get('research_profile') != 'insight_research_v1' or settings.get('verification_mode') != 'self':
            raise ValueError('this implementation supports insight_research_v1/self only')
        self.public, self.science, self.private = [self.root / x for x in ('public', 'science', 'private')]
        self.environment = self.environment_class(world)
        sources = [ROOT / 'experiments' / 'insight_research' / n for n in
                   ('common.py', 'contracts.py', 'environment.py', 'workspace.py', 'runtime.py')]
        reused = json.loads((Path(__file__).parent / 'reuse_manifest.json').read_text())
        if any(sha(ROOT / p) != h for p, h in reused['sha256'].items()):
            raise ValueError('reused source version changed; review and register a new implementation')
        identity = {'question': question, 'settings': settings, 'tool_contract': self.tool_schemas(),
                    'implementation': {str(p.relative_to(ROOT)): sha(p) for p in sources},
                    'reused_sources': reused['sha256'],
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

    def close(self):
        self.db.close()

    def file_ref(self, path, nature='derived_seen'):
        p = Path(path).resolve()
        if not p.is_file() or not any(p.is_relative_to(r) for r in (self.public, self.science)):
            raise ValueError('file outside published access manifest')
        version = sha(p)
        if p.is_relative_to(self.public) and self.identity['public_inputs'].get(str(p.relative_to(self.public))) != version:
            raise ValueError('frozen public source version changed')
        relative = str(p.relative_to(self.root))
        ref = 'file:' + digest([relative, version])[:24]
        self.db.execute('INSERT OR IGNORE INTO files VALUES (?,?,?,?)', (ref, relative, version, nature))
        return {'ref': ref, 'path': str(p), 'sha256': version, 'nature': nature}

    def file(self, ref):
        row = self.db.execute('SELECT path,hash,nature FROM files WHERE ref=?', (ref,)).fetchone()
        if not row: raise ValueError('received file reference required')
        p = (self.root / row[0]).resolve()
        if not any(p.is_relative_to(r) for r in (self.public, self.science)) or not p.is_file():
            raise ValueError('file outside published access manifest')
        if sha(p) != row[1]: raise ValueError('referenced source version changed; recheck evidence')
        return p, row[2]

    def record(self, ref, kind=None):
        row = self.db.execute('SELECT kind,body FROM records WHERE ref=?', (ref,)).fetchone()
        if not row or (kind and row[0] != kind): raise ValueError('received ' + (kind or 'record') + ' reference required')
        item = json.loads(row[1])
        path = self.science / 'records' / (ref + '.json')
        if path.exists() and json.loads(path.read_text()) != item:
            raise Pending('published record changed; inspect immutable archive')
        return item

    def records(self, kind):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid', (kind,))]

    def references(self, refs):
        for ref in refs:
            self.file(ref) if ref.startswith('file:') else self.record(ref)

    def add(self, kind, body):
        prefixes = {'hypothesis': 'H', 'plan': 'P', 'result': 'R', 'assessment': 'A', 'state': 'S', 'report': 'F'}
        ref = prefixes[kind] + uuid.uuid4().hex[:16]
        item = {'ref': ref, 'record_type': kind, 'created_at': now(), 'author': 'researcher', **body}
        self.db.execute('INSERT INTO records VALUES (?,?,?)', (ref, kind, encoded(item)))
        return item

    def _publish(self):
        for ref, body in self.db.execute('SELECT ref,body FROM records'):
            path = self.science / 'records' / (ref + '.json')
            if path.exists() and json.loads(path.read_text()) != json.loads(body):
                raise Pending('published record changed; inspect immutable archive')
            if not path.exists(): write_json(path, json.loads(body))

    def report(self):
        items = self.records('report')
        return items[-1] if items else None

    def state(self):
        states = self.records('state')
        return states[-1] if states else None

    def unincorporated(self):
        incorporated = {r for s in self.records('state') for r in s['incorporated_result_refs']}
        return [r for r in self.records('result') if r['ref'] not in incorporated]

    def context(self):
        state = self.state()
        # Agent may explicitly defer a question with a reason. Newly created
        # hypotheses and unincorporated results cannot disappear at that boundary.
        active = set(state['active_hypothesis_refs'] if state else [])
        known = set((state or {}).get('known_hypothesis_refs', []))
        active.update(h['ref'] for h in self.records('hypothesis') if h['ref'] not in known)
        active.update(r['hypothesis_ref'] for r in self.unincorporated())
        files = [{'ref': r, 'path': str(self.root / p), 'nature': n} for r, p, n in
                 self.db.execute('SELECT ref,path,nature FROM files WHERE nature="public_seen" ORDER BY path')]
        transport_path = self.private / 'transport.json'
        local = json.loads(transport_path.read_text()) if transport_path.exists() else {}
        return {'research_profile': 'insight_research_v1', 'verification_mode': 'self',
                'original_question': self.question,
                'state': {k: v for k, v in state.items() if k not in ('inactive_hypotheses', 'known_hypothesis_refs')} if state else None,
                'active_original_hypotheses': [self.record(r, 'hypothesis') for r in sorted(active)],
                'unincorporated_results': self.unincorporated(),
                'registered_counter_assessments': [a for a in self.records('assessment')
                    if a['hypothesis_ref'] in active and a['status'] in ('refuted', 'unresolved')],
                'deferred_questions': {'count': len((state or {}).get('inactive_hypotheses', {})),
                    'archive': 'search_memory/read_memory preserve exact predictions, reasons and evidence; defer is not refutation'},
                'critical_counterevidence': [self.record(r) if not r.startswith('file:') else {'ref': r}
                                             for r in (state or {}).get('counterevidence_refs', [])],
                'public_files': files, 'archive_counts': {k: len(self.records(k)) for k in
                    ('hypothesis', 'plan', 'result', 'assessment', 'state')},
                'permissions': {'read_only': [str(self.public), str(self.science)],
                    'python_write': 'current execution WORK_DIR only', 'private_process': 'read_memory owner interface only'},
                'resources': {'new_trials_remaining': 2 - self.trials_started(), 'settings': self.settings['limits'],
                    'local_accounted_tokens': local.get('accounted_tokens', 0),
                    'http_attempts_started': local.get('attempts', 0),
                    'local_remaining_tokens': max(0, self.settings['limits']['token_allowance'] - local.get('accounted_tokens', 0))},
                'interpretation': 'Agent assessments are scientific claims to audit, not backend-certified truth.'}

    def trials_started(self):
        return sum(bool(json.loads(p.read_text()).get('physical_trial')) for p in (self.private / 'effects').glob('*.json'))

    def call(self, name, args, operation_id):
        if name not in self.tools: raise ValueError('unknown research tool')
        args = self.tools[name][0].model_validate(args).model_dump()
        # Plan execution identity is independent of a later model/tool call ID.
        key = 'test:' + args['plan_ref'] if name == 'run_test' else operation_id
        if not key: raise ValueError('runtime operation identity required')
        signature = digest([name, args])
        prior = self.db.execute('SELECT signature,status,result FROM operations WHERE key=?', (key,)).fetchone()
        if prior:
            if prior[0] != signature: raise ValueError('operation identity reused with changed arguments')
            if prior[1] == 'completed':
                self._publish()
                return json.loads(prior[2])
        if self.report(): raise ValueError('study report sealed; further research requires a new study')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO operations VALUES (?,?,?,NULL)', (key, signature, 'prepared'))
        try:
            with self.db:
                result = self.dispatch(name, args, key)
                self.db.execute('UPDATE operations SET status=?,result=? WHERE key=?', ('completed', encoded(result), key))
            self._publish()
            return result
        except (ValueError, TypeError, sqlite3.Error) as error:
            # A rejected tool is also durable feedback; malformed transport never enters here.
            result = {'ok': False, 'error': str(error)}
            with self.db:
                self.db.execute('UPDATE operations SET status=?,result=? WHERE key=?', ('completed', encoded(result), key))
            return result

    def execute_python(self, code, key):
        original = self.science / 'source' / (hashlib.sha256(code.encode()).hexdigest() + '.py')
        original.parent.mkdir(exist_ok=True)
        if original.exists() and original.read_text() != code:
            raise Pending('archived submitted code changed; inspect immutable source')
        if not original.exists(): original.write_text(code)
        def bind(receipt):
            return {**receipt, 'submitted_source': self.file_ref(original)}
        progress = self.private / 'effects' / (digest(key) + '.json')
        if progress.exists():
            item = json.loads(progress.read_text())
            receipt = Path(item['receipt'])
            if receipt.exists(): return bind(json.loads(receipt.read_text()))
            if Path(item['directory']).exists():
                raise Pending('interrupted Python has no completion receipt; inspect before any replay')
        else:
            number = self.worker.count + 1
            directory = self.worker.directory / 'executions' / f'run_{number:03d}'
            write_json(progress, {'directory': str(directory), 'receipt': str(directory / f'execution_{number:03d}.json')})
        return bind(self.worker.run(code, timeout=45))

    def attachments(self, receipt, nature='derived_seen'):
        directory = Path(receipt['execution_directory'])
        return [self.file_ref(p, nature) for p in sorted(directory.rglob('*'))
                if p.is_file() and not any(x in ('tmp', '.matplotlib') for x in p.relative_to(directory).parts)]

    def read(self, ref, offset, limit, *, memory=False):
        if ref.startswith('process:'):
            if not memory: raise ValueError('process records require the owner memory interface')
            name = ref.removeprefix('process:')
            if not name.isdecimal(): raise ValueError('received process reference required')
            path = self.private / 'turns' / (name + '.json')
            if not path.is_file(): raise ValueError('received process reference required')
            content = path.read_text()
            version = sha(path)
        elif ref.startswith('file:'):
            path, _ = self.file(ref)
            if path.suffix in ('.sqlite', '.db'):
                return {'ref': ref, 'compute': 'query_data: read-only SQL over public business.sqlite'}
            if path.suffix == '.csv' and path.stat().st_size > 18000:
                with path.open() as stream:
                    reader = csv.reader(stream)
                    preview = [row for _, row in zip(range(13), reader)]
                return {'ref': ref, 'sha256': sha(path), 'preview': preview, 'preview_only': True,
                        'compute_path': str(path), 'compute': 'Use SQL or sandbox Python for full data; this is a bounded preview.'}
            with path.open() as stream:
                stream.seek(offset); content = stream.read(limit)
                next_offset = stream.tell() if stream.read(1) else None
            return {'ref': ref, 'sha256': sha(path), 'text': content[:limit],
                    'next_offset': next_offset}
        else:
            content = encoded(self.record(ref)); version = digest(json.loads(content))
        return {'ref': ref, 'sha256': version, 'text': content[offset:offset+limit],
                'next_offset': offset + limit if len(content) > offset + limit else None}

    def dispatch(self, name, a, key):
        if name == 'read_context': return self.context()
        if name in ('read_artifact', 'read_memory'):
            return self.read(**a, memory=name == 'read_memory')
        if name == 'query_data':
            source = self.file_ref(self.public / 'business.sqlite', 'public_seen')
            db = sqlite3.connect((self.public / 'business.sqlite').as_uri() + '?mode=ro', uri=True)
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
            db.set_authorizer(lambda act, p1, p2, *_: sqlite3.SQLITE_OK if act in allowed and str(p2).lower() != 'load_extension' else sqlite3.SQLITE_DENY)
            ticks = [0]
            def stop():
                ticks[0] += 1
                return ticks[0] > 10000
            db.set_progress_handler(stop, 1000)
            try:
                cur = db.execute(a['sql']); columns = [d[0] for d in cur.description]
                rows = cur.fetchmany(100001)
                if len(rows) > 100000: raise ValueError('query exceeds 100000 rows; aggregate or narrow')
            finally: db.close()
            directory = self.science / 'queries' / digest(key)[:24]; directory.mkdir(parents=True, exist_ok=True)
            path = directory / 'rows.csv'
            with path.open('w') as stream:
                writer = csv.writer(stream); writer.writerow(columns); writer.writerows(rows)
            receipt = {'sql': a['sql'], 'purpose': a['purpose'], 'source': source,
                       'row_count': len(rows), 'columns': columns, 'file': self.file_ref(path)}
            write_json(directory / 'receipt.json', receipt)
            return {**receipt, 'receipt': self.file_ref(directory / 'receipt.json'), 'preview': rows[:12]}
        if name == 'run_python':
            result = self.execute_python(a['code'], key)
            return {'purpose': a['purpose'], 'execution': result, 'files': self.attachments(result), 'evidence_nature': 'exploratory_seen'}
        if name == 'save_hypothesis':
            self.references(a['evidence_refs'])
            if a['parent_ref']: self.record(a['parent_ref'], 'hypothesis')
            return self.add('hypothesis', a)
        if name == 'register_test':
            hypothesis = self.record(a['hypothesis_ref'], 'hypothesis')
            self.references(a['data_refs'])
            if a['parent_plan_ref']: self.record(a['parent_plan_ref'], 'plan')
            protocol = None
            if a['mode'] == 'observational':
                if not a['code'] or a['protocol_id'] or a['expected_changed_variables']:
                    raise ValueError('observational plan requires fixed code and no intervention')
                nature = 'exploratory_seen'  # All currently exposed data are seen; no fictional holdout.
            else:
                if a['code'] or a['protocol_id'] not in self.protocols:
                    raise ValueError('select a received protocol; custom code is observational analysis')
                protocol = self.protocols[a['protocol_id']]
                match_changed_variables(a['expected_changed_variables'], protocol)
                import pandas as pd
                valid = set(pd.read_csv(self.public / 'products.csv').sku)
                if not a['outcome_product_ids'] or len(a['outcome_product_ids']) != len(set(a['outcome_product_ids'])) or not set(a['outcome_product_ids']) <= valid:
                    raise ValueError('distinct received outcome SKU IDs required')
                nature = 'intervention' if protocol['is_new_sample'] else 'record_reconciliation'
            return self.add('plan', {**a, 'original_prediction': hypothesis['prediction'],
                       'original_scope': hypothesis['scope'], 'evidence_nature': nature, 'protocol': protocol,
                       'data_exposure': 'all declared inputs publicly available before registration',
                       'code_sha256': hashlib.sha256(a['code'].encode()).hexdigest() if a['code'] else None})
        if name == 'run_test':
            plan = self.record(a['plan_ref'], 'plan')
            self.references(plan['data_refs'])
            if plan['mode'] == 'observational':
                execution = self.execute_python(plan['code'], key)
            else:
                progress = self.private / 'effects' / (digest(key) + '.json')
                if progress.exists():
                    item = json.loads(progress.read_text())
                    receipt = Path(item['receipt'])
                    if receipt.exists(): execution = json.loads(receipt.read_text())
                    else: raise Pending('interrupted protocol has no receipt; inspect original operation, do not resample')
                else:
                    trial = plan['protocol']['is_new_sample']
                    slot = self.trials_started()
                    if trial and slot >= 2: raise ValueError('maximum two new supply trials, including interrupted starts')
                    directory = self.science / 'tests' / plan['ref']; directory.mkdir(parents=True, exist_ok=False)
                    write_json(progress, {'directory': str(directory), 'receipt': str(directory / 'backend_receipt.json'),
                                          'physical_trial': trial, 'slot': slot})
                    execution = self.environment.execute(self.public, directory, plan, slot)
            return self.add('result', {'plan_ref': plan['ref'], 'hypothesis_ref': plan['hypothesis_ref'],
                'ok': execution['ok'], 'evidence_nature': plan['evidence_nature'],
                'actual_execution': execution, 'declared_data_refs': plan['data_refs'],
                'readable_inputs': {p: h for p, h in self.identity['public_inputs'].items()},
                'source_observer_limits': 'Cooperative registered CSV/SQLite read observer; not tamper-proof or semantic lineage certification.',
                'attachments': self.attachments(execution, 'intervention_seen' if plan['evidence_nature'] == 'intervention' else 'derived_seen'),
                'limitations': ['Execution success does not certify the analysis or coverage of the hypothesis.']})
        if name == 'record_assessment':
            self.record(a['hypothesis_ref'], 'hypothesis'); self.references(a['counterevidence_refs'])
            results = [self.record(r, 'result') for r in a['result_refs']]
            if any(r['hypothesis_ref'] != a['hypothesis_ref'] for r in results):
                raise ValueError('results must test this exact original hypothesis version')
            if a['status'] != 'unresolved' and any(not r['ok'] for r in results):
                raise ValueError('failed execution cannot support or refute a scientific hypothesis')
            return self.add('assessment', {**a, 'evidence_natures': sorted({r['evidence_nature'] for r in results}),
                        'certification': 'researcher judgment; requires scientific audit'})
        if name == 'update_research_state':
            for r in a['active_hypothesis_refs']: self.record(r, 'hypothesis')
            for r in a['incorporated_result_refs']: self.record(r, 'result')
            self.references(a['alternative_refs'] + a['evidence_refs'] + a['counterevidence_refs'])
            hypotheses = {h['ref'] for h in self.records('hypothesis')}
            active = set(a['active_hypothesis_refs'])
            previous = (self.state() or {}).get('inactive_hypotheses', {})
            inactive = {**previous, **a['inactive_hypotheses']}
            if not set(inactive) <= hypotheses or any(not reason.strip() for reason in inactive.values()):
                raise ValueError('deferred hypotheses require received references and nonempty reasons')
            inactive = {r: reason for r, reason in inactive.items() if r not in active}
            if set(inactive) != hypotheses - active:
                raise ValueError('every inactive hypothesis needs an explicit reason; no silent removal from current research')
            outstanding = {r['hypothesis_ref'] for r in self.unincorporated() if r['ref'] not in a['incorporated_result_refs']}
            if outstanding - active:
                raise ValueError('incorporate outstanding results before deferring their hypothesis')
            # The disposition map is archived, not included in full in each
            # request: only current questions and evidence occupy fixed context.
            return self.add('state', {**a, 'inactive_hypotheses': inactive,
                                     'known_hypothesis_refs': sorted(hypotheses)})
        if name == 'search_memory':
            items = []
            for kind in ('hypothesis', 'plan', 'result', 'assessment', 'state'):
                if a['kind'] in ('all', kind): items.extend(self.records(kind))
            if a['kind'] in ('all', 'process'):
                for p in sorted((self.private / 'turns').glob('*.json')):
                    items.append({'ref': 'process:' + p.stem, 'record_type': 'process', 'content': p.read_text()})
            terms = a['query'].casefold().split()
            ranked = [(sum(encoded(x).casefold().count(t) for t in terms), x) for x in items]
            ranked = [(s, x) for s, x in ranked if not terms or s]
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            page = ranked[a['offset']:a['offset']+a['limit']]
            return {'hits': [{'ref': x['ref'], 'kind': x['record_type'], 'score': s,
                    'preview': encoded(x)[:800]} for s, x in page], 'total': len(ranked),
                    'next_offset': a['offset']+a['limit'] if len(ranked) > a['offset']+a['limit'] else None}
        if name == 'finish_research':
            if self.unincorporated(): raise ValueError('update research state to incorporate every outstanding test result before finishing')
            if not self.state(): raise ValueError('save current research understanding before finishing')
            assessments = [self.record(r, 'assessment') for r in a['assessment_refs']]
            covered = {x['hypothesis_ref'] for x in assessments}
            hypotheses = {h['ref'] for h in self.records('hypothesis')}
            if set(a['other_hypotheses']) != hypotheses - covered:
                raise ValueError('disclose every other registered hypothesis version exactly once')
            insights = [x['ref'] for x in assessments if x['status'] == 'supported' and self.record(x['hypothesis_ref'])['kind'] == 'business']
            return self.add('report', {**a, 'business_insight_assessment_refs': insights,
                    'all_hypothesis_refs': sorted(hypotheses),
                    'all_assessment_refs': [x['ref'] for x in self.records('assessment')],
                    'all_plan_refs': [x['ref'] for x in self.records('plan')],
                    'all_result_refs': [x['ref'] for x in self.records('result')],
                    'stage_status': 'supported_claims' if insights else 'inconclusive',
                    'scientific_certification': False})
        raise ValueError('unimplemented action')
