"""Study-local admission shared by every role, under the existing project ledger.

No new project authorization. Unknown usage keeps its local reservation; a
durable response can settle the same local row again without double charge.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from ..common import Pending, digest, encoded
from ..runtime import Journal
from ..runtime_memory import MemoryJournal
from token_budget import SharedTokenBudget, reservation_bound, reported_total
from model_protocol import request_model


class StudyBudget:
    def __init__(self, path, identity, *, create=False):
        self.path = Path(path).resolve(); self.identity = identity
        if any(type(identity.get(k)) is not int or identity[k] < 0 for k in ('token_allowance','max_http_attempts')):
            raise ValueError('nonnegative shared study token and request ceilings required')
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists(): raise ValueError('study budget exists; never reset')
            with sqlite3.connect(self.path) as db:
                db.executescript('''CREATE TABLE identity(body TEXT);
                    CREATE TABLE attempts(key TEXT PRIMARY KEY,role TEXT,bound INTEGER,actual INTEGER,payload_hash TEXT,status TEXT);
                    CREATE TABLE flags(key TEXT PRIMARY KEY,value TEXT);''')
                db.execute('INSERT INTO identity VALUES (?)', (encoded(identity),))
        with self.connect() as db:
            if json.loads(db.execute('SELECT body FROM identity').fetchone()[0]) != identity:
                raise ValueError('study budget identity differs; cannot reset or extend implicitly')

    def connect(self): return sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=30)

    def snapshot(self):
        with self.connect() as db:
            used, known, count = db.execute('SELECT coalesce(sum(coalesce(actual,bound)),0),coalesce(sum(actual),0),count(*) FROM attempts').fetchone()
            halted = db.execute("SELECT value FROM flags WHERE key='halted'").fetchone()
        return {'accounted_tokens': used, 'reported_tokens': known, 'unknown_reserve': used-known,
            'http_attempts': count, 'remaining_tokens': max(0, self.identity['token_allowance']-used),
            'remaining_http_attempts': max(0, self.identity['max_http_attempts']-count), 'halted': halted[0] if halted else None}

    def reserve(self, key, role, payload):
        amount = reservation_bound(payload)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM attempts WHERE key=?', (key,)).fetchone():
                raise Pending('study attempt already exists without its role delivery; inspect original, never resend')
            used, count = db.execute('SELECT coalesce(sum(coalesce(actual,bound)),0),count(*) FROM attempts').fetchone()
            if db.execute("SELECT 1 FROM flags WHERE key='halted'").fetchone(): raise Pending('shared study budget halted')
            if used + amount > self.identity['token_allowance'] or count >= self.identity['max_http_attempts']:
                raise Pending('shared all-role study allocation cannot admit this request')
            db.execute('INSERT INTO attempts VALUES (?,?,?,NULL,?,?)', (key, role, amount, digest(payload), 'in_flight'))
        return amount

    def settle(self, key, payload_hash, usage):
        actual = reported_total(usage)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT bound,actual,payload_hash,status FROM attempts WHERE key=?', (key,)).fetchone()
            if not row or row[2] != payload_hash: raise Pending('study settlement identity mismatch')
            if row[3] != 'in_flight':
                if row[1] != actual: raise Pending('conflicting study settlement; no refund/reset')
                return row[0] if actual is None else actual
            db.execute('UPDATE attempts SET actual=?,status=? WHERE key=?',
                (actual, 'unknown' if actual is None else 'settled', key))
            if actual is not None and actual > row[0]:
                db.execute("INSERT OR REPLACE INTO flags VALUES ('halted',?)", ('reported usage exceeded local reservation',))
        return row[0] if actual is None else actual


class StudyJournal(Journal):
    """Same response delivery protocol, with an atomic shared local reservation."""
    def __init__(self, workspace, config, study_budget, role, *, memory=False):
        super().__init__(workspace, config)
        self.study, self.role, self.memory = study_budget, role, memory
        pointer = config.get('token_budget_pointer')
        if not pointer or SharedTokenBudget(pointer).auth['id'] != study_budget.identity['project_budget_id']:
            raise ValueError('role model configuration must bind the registered project ledger')

    def persist_request(self, attempt, payload):
        if self.memory: return MemoryJournal.persist_request(self, attempt, payload)
        return super().persist_request(attempt, payload)

    def persist_response(self, attempt, record):
        record = deepcopy(record); record.pop('request', None)
        record['request_archive'] = 'requests/' + str(attempt) + '.json'
        return super().persist_response(attempt, record)

    def snapshot(self):
        if not self.config.get('token_budget_pointer'): raise ValueError('explicit project budget pointer required')
        project = SharedTokenBudget(self.config['token_budget_pointer']).snapshot()
        local = self.study.snapshot()
        return {**project, 'remaining_admission_tokens': min(project['remaining_admission_tokens'], local['remaining_tokens']),
            'study_usage': local}

    def call(self, payload):
        if self.state.get('delivery'):
            item = self.state['delivery']
            if digest(payload) != item['request_hash']: raise Pending('recover original paid role delivery first')
            return json.loads((self.ws.private / 'http' / (str(item['attempt']) + '.json')).read_text())
        item = self.state.get('inflight')
        if item:
            if digest(payload) != item['request_hash']: raise Pending('inflight role request identity differs')
            receipt = self.ws.private / 'http' / (str(item['attempt']) + '.json')
            if not receipt.exists(): raise Pending('role transport has no durable response; preserve reservations, do not retry blindly')
            record = json.loads(receipt.read_text())
        else:
            limits = self.ws.settings['limits']; snap = self.snapshot(); bound = reservation_bound(payload)
            if self.state['attempts'] >= limits['max_http_attempts']: raise Pending('registered role request cap reached')
            if snap['status'] != 'open' or bound > snap['remaining_admission_tokens']:
                raise Pending('project or common study admission does not fit; no request sent')
            attempt = self.state['attempts'] + 1
            key = digest([self.role, attempt])
            self.study.reserve(key, self.role, payload)
            item = {'attempt': attempt, 'request_hash': digest(payload), 'reservation': bound, 'study_key': key}
            self.state['attempts'] = attempt; self.state['inflight'] = item; self.save()
            self.persist_request(attempt, payload)
            record = request_model(self.config, payload)
            self.persist_response(attempt, record)
        cost = self.study.settle(item['study_key'], item['request_hash'], record.get('response', {}).get('usage'))
        self.state['accounted_tokens'] += cost
        self.state['inflight'] = None; self.state['delivery'] = item; self.save()
        return record
