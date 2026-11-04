"""Persistent shared admission budget at the actual model transport boundary.

No credentials, network, agent runtime, or automatic budget creation/reset.
Unknown usage retains its reservation. SQLite commits before any request sends.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

DEFAULT_POINTER = Path(__file__).resolve().parents[1] / 'budgets/active.json'


class TokenBudgetStop(RuntimeError):
    pass


def fail(reason):
    raise TokenBudgetStop('shared reported-cost admission stop: ' + reason)


def reservation_bound(payload):
    maximum = payload.get('max_completion_tokens', payload.get('max_tokens'))
    if type(maximum) is not int or maximum <= 0:
        fail('a positive explicit output limit is required')
    # Deliberately conservative bytes, not an exact provider tokenizer. Includes
    # all messages, tools, JSON and an extra template allowance. Unexpected
    # provider overhead/usage exceeding it halts the entire authorization.
    return 2 * len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) + maximum + 16384


def reported_total(usage):
    if not isinstance(usage, dict):
        return None
    total = usage.get('total_tokens')
    if type(total) is not int or total < 0:
        return None
    parts = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens')]
    if any(v is not None and (type(v) is not int or v < 0) for v in parts):
        return None
    if all(v is not None for v in parts) and sum(parts) > total:
        return None
    return total


class SharedTokenBudget:
    def __init__(self, pointer=DEFAULT_POINTER):
        self.pointer = Path(pointer).resolve()
        try:
            binding = json.loads(self.pointer.read_text())
            authorization = Path(binding['authorization'])
            if not authorization.is_absolute():
                authorization = self.pointer.parent / authorization
            self.authorization = authorization.resolve()
            raw = self.authorization.read_bytes()
            self.auth_sha = hashlib.sha256(raw).hexdigest()
            self.auth = json.loads(raw)
            if self.auth_sha != binding['sha256']:
                fail('authorization hash changed')
            if type(self.auth['limit_tokens']) is not int or self.auth['limit_tokens'] <= 0:
                fail('invalid authorization')
            self.database = self.authorization.parent / 'ledger.sqlite'
            # Opening rw fails if the ledger was deleted; never reset to zero.
            with self.connect() as con:
                meta = con.execute('SELECT id, limit_tokens, auth_sha FROM budget').fetchone()
                if meta != (self.auth['id'], self.auth['limit_tokens'], self.auth_sha):
                    fail('ledger and authorization disagree')
        except (OSError, ValueError, KeyError, sqlite3.Error) as error:
            fail('missing or invalid persistent budget: ' + type(error).__name__)

    def connect(self):
        return sqlite3.connect(self.database.as_uri() + '?mode=rw', uri=True, timeout=30)

    def snapshot(self):
        with self.connect() as con:
            row = con.execute('SELECT id, limit_tokens, status, reason FROM budget').fetchone()
            total, known, unknown, count = con.execute(
                'SELECT COALESCE(SUM(COALESCE(actual,reserved)),0), '
                'COALESCE(SUM(actual),0), '
                'COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0), '
                'COUNT(*) FROM attempts').fetchone()
        return {'budget_id': row[0], 'limit_tokens': row[1], 'status': row[2], 'reason': row[3],
                'reported_tokens': known, 'unknown_or_inflight_reserve': unknown,
                'accounted_tokens': total, 'remaining_admission_tokens': max(0, row[1]-total),
                'attempts_reserved': count}

    def reserve(self, payload, metadata=None):
        if payload.get('model') != self.auth['model']:
            fail('model is outside the authorization')
        amount = reservation_bound(payload)
        attempt_id = uuid.uuid4().hex
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            limit, status = con.execute('SELECT limit_tokens,status FROM budget').fetchone()
            used = con.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM attempts').fetchone()[0]
            if status != 'open':
                fail('authorization is ' + status)
            if amount + used > limit:
                con.execute("UPDATE budget SET status='exhausted', reason=?",
                            ('next conservative reservation does not fit remaining budget',))
                con.commit()
                fail('cumulative authorization cannot admit another request')
            con.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?)',
                        (attempt_id, time.time(), amount, None, 'in_flight',
                         hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                         json.dumps(metadata or {},ensure_ascii=False), None))
        return {'budget_id': self.auth['id'], 'attempt_id': attempt_id, 'reserved_tokens': amount}

    def settle(self, reservation, usage, provider_request_id=None):
        actual = reported_total(usage)
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT reserved,actual,status FROM attempts WHERE id=?',
                              (reservation['attempt_id'],)).fetchone()
            if row is None:
                fail('reservation missing')
            if row[2] != 'in_flight':
                fail('reservation already settled; no double refund')
            status = 'usage_unknown' if actual is None else 'settled'
            con.execute('UPDATE attempts SET actual=?,status=?,provider_request_id=? WHERE id=?',
                        (actual,status,provider_request_id,reservation['attempt_id']))
            if actual is not None and actual > row[0]:
                con.execute("UPDATE budget SET status='halted',reason=?",
                            ('provider-reported usage exceeded conservative reservation',))
        return {**reservation, 'reported_tokens': actual, 'status': status,
                'authorization_status': self.snapshot()['status']}

    def stop(self, reason):
        with self.connect() as con:
            con.execute("UPDATE budget SET status='stopped',reason=?", (reason,))


def initialize_budget(directory, *, budget_id, limit_tokens, model, base_url, user_instruction):
    """Explicit one-time authorization helper. Existing files are never replaced."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    auth = {'id': budget_id, 'limit_tokens': limit_tokens, 'model': model,
            'base_url': base_url.rstrip('/'), 'authorized_at_unix': time.time(),
            'user_instruction': user_instruction,
            'scope': 'All subsequent experiment model inputs+outputs, roles, summaries, retries and allocations; cached input counts in full. No automatic reset.',
            'admission': '2*serialized_UTF8_bytes + explicit_max_output + 16384; unknown usage retains reservation; provider bound breach halts authorization.'}
    if type(limit_tokens) is not int or limit_tokens <= 0:
        raise ValueError('positive integer limit required')
    authorization = directory/'authorization.json'
    with authorization.open('x') as f:
        json.dump(auth,f,ensure_ascii=False,indent=2);f.write('\n')
    sha = hashlib.sha256(authorization.read_bytes()).hexdigest()
    with sqlite3.connect(directory/'ledger.sqlite') as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=FULL')
        con.execute('CREATE TABLE budget (id TEXT PRIMARY KEY, limit_tokens INTEGER, auth_sha TEXT, status TEXT, reason TEXT)')
        con.execute('CREATE TABLE attempts (id TEXT PRIMARY KEY, started REAL, reserved INTEGER, actual INTEGER, status TEXT, payload_sha TEXT, metadata TEXT, provider_request_id TEXT)')
        con.execute('INSERT INTO budget VALUES (?,?,?,?,?)', (budget_id,limit_tokens,sha,'open',None))
    pointer = directory/'pointer.json'
    with pointer.open('x') as f:
        json.dump({'authorization': str(authorization), 'sha256': sha},f,indent=2);f.write('\n')
    return pointer
