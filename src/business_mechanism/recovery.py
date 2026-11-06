"""Bounded, journaled task rotation. No erasure, inference or unpaid replay."""
import json
import time
from contextlib import ExitStack
import fcntl
from pathlib import Path
from experiments.insight_research.common import digest, encoded, now, write_json
from . import convergence

RECOVERABLE = ('semantic_stagnation:', 'registered graph turn ceiling reached',
               'bounded fixed context cannot fit', 'fixed critical context/latest complete turn still exceeds guard')


def recover_execution(path, *, reason, event_id):
    from .service import open_project
    from .workflow import assert_review_work_drained, archive_stage_window, close_stage
    root = Path(path).resolve()
    if not event_id or not reason.startswith(RECOVERABLE):
        raise ValueError('Only registered semantic/context/graph task stalls can rotate automatically')
    with ExitStack() as locks:
        for p in (root/'service.lock', root/'research_run.lock', root/'researcher/private/runtime.lock'):
            stream = locks.enter_context(p.open('a')); fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, cfg, ws, backend = open_project(root)
        try:
            with backend.budget.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS release_recoveries(event TEXT PRIMARY KEY,body TEXT)')
                row = db.execute('SELECT body FROM release_recoveries WHERE event=?', (event_id,)).fetchone()
                if row: return json.loads(row[0])
                attempts = backend.budget.snapshot()['http_attempts']; fingerprint = backend.guard.fingerprint()
                previous = [json.loads(b) for b, in db.execute('SELECT body FROM release_recoveries')]
                if len([r for r in previous if r['evidence_fingerprint'] == fingerprint]) >= 3:
                    raise ValueError('recovery_limit: three task rotations without new scientific evidence; preserve a readable blocked state')
            if backend.runtime.cp.get('pending') or backend.journal.state.get('inflight') or backend.journal.state.get('delivery'):
                raise ValueError('recovery_requires_drained_paid_researcher_work')
            assert_review_work_drained(ws)
            receipt_path = root/'recovery_events'/(digest(event_id)+'.json')
            selected = convergence.focus(ws)
            receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
            if receipt and (receipt['event_id'] != event_id or receipt['reason'] != reason):
                raise ValueError('recovery_event_conflict')
            if receipt and receipt.get('focus_ref'):
                selected = convergence.get(ws, receipt['focus_ref'])
            if receipt is None:
                archive_id = archive_stage_window(backend.runtime)
                receipt = {'event_id': event_id, 'created_at': now(), 'reason': reason,
                'evidence_fingerprint': fingerprint, 'at_request': attempts, 'archive_id': archive_id,
                'external_provider_calls': 0, 'scientific_status_changed': False,
                'costs_reset': False, 'counters_reset': False, 'endpoint': None, 'status': 'prepared',
                'focus_ref': selected['hypothesis_ref'] if selected else None}
                write_json(receipt_path, receipt)
            selected = convergence.get(ws, receipt['focus_ref']) if receipt['focus_ref'] else None
            with ws.db:
                if selected:
                    receipt['endpoint'] = convergence.close(ws, {'hypothesis_ref': selected['hypothesis_ref'],
                        'outcome': 'inconclusive', 'reason': 'Execution task rotated after bounded stall: '+reason,
                        'assessment_ref': None, 'evidence_refs': [], 'successor_ref': None},
                        'recovery:'+event_id, actor='recovery_controller')
                outcome = close_stage(ws, outcome='blocked', reason='Automatic bounded recovery; original unresolved work preserved: '+reason,
                    unresolved_refs=[a['ref'] for a in ws.records('assessment') if not ws.clearance(a['ref'])],
                    evidence_refs=[], key='recovery:'+event_id, actor='recovery_controller')
                receipt['stage_outcome_ref'] = outcome['ref']
            receipt['status'] = 'completed'
            with backend.budget.connect() as db:
                db.execute('INSERT INTO release_recoveries VALUES (?,?)', (event_id, encoded(receipt)))
            write_json(receipt_path, receipt)
            return receipt
        finally:
            ws.close()


def recovery_baseline(budget, fingerprint):
    with budget.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='release_recoveries'").fetchone(): return 0
        values = [json.loads(b) for b, in db.execute('SELECT body FROM release_recoveries')]
    return max((v['at_request'] for v in values if v['status'] == 'completed' and v['evidence_fingerprint'] == fingerprint), default=0)


def authorize_window(path, *, seconds, event_id, reason, max_stages=None):
    """Explicit operator authorization, never implicit on restart or recovery."""
    from .service import open_project
    if type(seconds) is not int or not 0 < seconds <= 86400 or not event_id or not reason:
        raise ValueError('Explicit finite authorization of at most 24 hours required')
    if max_stages is not None and (type(max_stages) is not int or not 1<=max_stages<=10000):
        raise ValueError('Finite authorized stage bound of at most 10000 required')
    root = Path(path).resolve()
    with (root/'service.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, cfg, ws, backend = open_project(root)
        try:
            if backend.runtime.cp.get('pending') or backend.journal.state.get('inflight') or backend.journal.state.get('delivery'):
                raise ValueError('authorization_requires_drained_paid_work')
            with backend.budget.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS release_authorization_windows(event TEXT PRIMARY KEY,body TEXT)')
                prior = db.execute('SELECT body FROM release_authorization_windows WHERE event=?', (event_id,)).fetchone()
                if prior:
                    receipt = json.loads(prior[0])
                    if receipt['seconds'] != seconds or receipt['reason'] != reason or receipt.get('max_stages') != max_stages: raise ValueError('authorization_event_conflict')
                    if max_stages is not None:
                        cfg['max_stages']=max_stages; write_json(root/'project.json',cfg)
                    return receipt
                before = backend.budget.snapshot()
                started, deadline = db.execute('SELECT started,deadline FROM execution_control WHERE id=1').fetchone()
                at = time.time()
                receipt = {'event_id': event_id, 'reason': reason, 'seconds': seconds, 'created_at': now(),
                    'previous_started_unix': started, 'previous_deadline_unix': deadline,
                    'started_unix': at, 'deadline_unix': at+seconds, 'inherited_usage': before,
                    'previous_max_stages':cfg['max_stages'], 'max_stages':max_stages,
                    'meaning': 'A newly authorized intervention window; not a claim that the prior experiment ran uninterrupted.'}
                db.execute('INSERT INTO release_authorization_windows VALUES (?,?)', (event_id, encoded(receipt)))
                db.execute('UPDATE execution_control SET started=?,deadline=? WHERE id=1', (at, at+seconds))
            write_json(root/'authorization_window.json', receipt)
            if max_stages is not None:
                cfg['max_stages']=max_stages; write_json(root/'project.json',cfg)
            return receipt
        finally:
            ws.close()
