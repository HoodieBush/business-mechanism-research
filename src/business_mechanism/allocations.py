"""Review slices consume the original shared authorization, never reset it."""
import json
import time
from experiments.insight_research.common import encoded, now


def initialize(budget):
    with budget.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS release_review_allocations(event TEXT PRIMARY KEY,job TEXT,additional INTEGER,reason TEXT,created TEXT)')


def review_allocation(owner, budget, job_ref):
    initialize(budget)
    policy = owner.settings['execution_policy']
    with budget.connect() as db:
        extra = db.execute('SELECT coalesce(sum(additional),0) FROM release_review_allocations WHERE job=?', (job_ref,)).fetchone()[0]
    normal = policy['review_http_limit'] + extra
    reserve = policy.get('review_repair_requests', 3)
    return {'job_ref': job_ref, 'normal_requests': normal, 'repair_reserve_requests': reserve,
            'closeout_start_request': max(0, normal-2),
            'maximum_requests': normal+reserve, 'additional_allocated': extra,
            'meaning': 'Final two normal requests and the bounded reserve are for final feedback/repair, including insufficient_evidence without a preexisting draft. Shared attempts, tokens and deadline remain authoritative.'}


def allocate_review_requests(path, job_ref, additional, *, event_id, reason):
    """Idempotently extend a local slice inside unchanged project authorization."""
    from .service import open_project
    if type(additional) is not int or additional <= 0 or not event_id or not reason.strip():
        raise ValueError('Positive finite additional requests, event_id and reason required')
    root, project, ws, backend = open_project(path)
    try:
        job = ws.job(job_ref)
        if job['status'] == 'completed':
            raise ValueError('Completed review cannot receive continuation allocation')
        initialize(backend.budget)
        with backend.budget.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT job,additional,reason FROM release_review_allocations WHERE event=?', (event_id,)).fetchone()
            if prior:
                if prior != (job_ref, additional, reason):
                    raise ValueError('allocation_event_identity_conflict')
            else:
                deadline = db.execute('SELECT deadline FROM execution_control WHERE id=1').fetchone()[0]
                if time.time() >= deadline or additional > backend.budget.snapshot()['remaining_http_attempts']:
                    raise ValueError('Continuation exceeds remaining original authorization')
                db.execute('INSERT INTO release_review_allocations VALUES (?,?,?,?,?)',
                           (event_id, job_ref, additional, reason, now()))
        with ws.db:
            ws.db.execute('DELETE FROM release_task_state WHERE job=?', (job_ref,))
        return review_allocation(ws, backend.budget, job_ref)
    finally:
        ws.close()
