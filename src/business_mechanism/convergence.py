"""Durable work in progress, immutable goals and honest hypothesis endpoints.

An execution endpoint never turns an unreviewed claim into an accepted fact.
Limits belong to hypotheses across stages; stage changes cannot reset them.
"""
import json
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from experiments.insight_research.common import digest, encoded, now, write_json

DEFAULT_POLICY = {'max_active_hypotheses': 3, 'hypothesis_requests': 24,
                  'hypothesis_test_runs': 6, 'closeout_requests': 4}
TERMINAL = ('accepted_in_scope', 'refuted', 'inconclusive', 'abandoned', 'superseded')


class Goal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hypothesis_ref: str
    claim_level: Literal['descriptive', 'association', 'causal']
    success_criterion: str = Field(min_length=10)
    falsification_criterion: str = Field(min_length=10)
    inconclusive_condition: str = Field(min_length=10)


class CloseHypothesis(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hypothesis_ref: str
    outcome: Literal['accepted_in_scope', 'refuted', 'inconclusive', 'abandoned', 'superseded']
    reason: str = Field(min_length=10)
    assessment_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    successor_ref: str | None = None


class Focus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hypothesis_ref: str


def initialize(ws):
    ws.db.executescript('''
        CREATE TABLE IF NOT EXISTS release_hypotheses(ref TEXT PRIMARY KEY,body TEXT);
        CREATE TABLE IF NOT EXISTS release_hypothesis_turns(attempt INTEGER PRIMARY KEY,hypothesis TEXT);
        CREATE TABLE IF NOT EXISTS release_hypothesis_events(operation TEXT PRIMARY KEY,body TEXT);
    ''')


def policy(ws):
    value = {**DEFAULT_POLICY, **ws.settings.get('research_policy', {})}
    if any(type(v) is not int or v <= 0 for v in value.values()):
        raise ValueError('Positive finite research policy bounds required')
    return value


def sync(ws):
    """Import legacy Hs without changing their original records or predictions."""
    if hasattr(ws, 'view'): return
    active = ws.db.execute("SELECT count(*) FROM release_hypotheses WHERE json_extract(body,'$.status')='active'").fetchone()[0]
    for h in ws.records('hypothesis'):
        if ws.db.execute('SELECT 1 FROM release_hypotheses WHERE ref=?', (h['ref'],)).fetchone(): continue
        status = 'active' if active < policy(ws)['max_active_hypotheses'] else 'backlog'
        item = {'hypothesis_ref': h['ref'], 'status': status, 'created_at': now(),
                'original_version': digest(h), 'goal': None,
                'original_prediction': h['prediction'], 'original_falsification': h['falsification'],
                'endpoint': None, 'import_policy': 'Existing proposals retained; backlog is untested, not refuted.'}
        ws.db.execute('INSERT INTO release_hypotheses VALUES (?,?)', (h['ref'], encoded(item)))
        active += status == 'active'


def items(ws):
    sync(ws)
    return [json.loads(b) for b, in ws.db.execute('SELECT body FROM release_hypotheses ORDER BY rowid')]


def get(ws, ref):
    ws.record(ref, 'hypothesis'); sync(ws)
    return json.loads(ws.db.execute('SELECT body FROM release_hypotheses WHERE ref=?', (ref,)).fetchone()[0])


def save(ws, item):
    ws.db.execute('UPDATE release_hypotheses SET body=? WHERE ref=?', (encoded(item), item['hypothesis_ref']))


def focus(ws):
    active = [h for h in items(ws) if h['status'] == 'active']
    row = ws.db.execute("SELECT value FROM meta WHERE key='release_focus_hypothesis'").fetchone()
    return next((h for h in active if row and h['hypothesis_ref'] == row[0]), active[0] if active else None)


def active_refs(ws):
    return {h['hypothesis_ref'] for h in items(ws) if h['status'] == 'active'}


def usage(ws, ref):
    return {'requests': ws.db.execute('SELECT count(*) FROM release_hypothesis_turns WHERE hypothesis=?', (ref,)).fetchone()[0],
            'test_runs': sum(r['hypothesis_ref'] == ref for r in ws.records('result'))}


def account_request(ws, attempt):
    h = focus(ws)
    if h:
        with ws.db:
            ws.db.execute('INSERT OR IGNORE INTO release_hypothesis_turns VALUES (?,?)', (attempt, h['hypothesis_ref']))


def agenda(ws):
    hs = items(ws); selected = focus(ws); p = policy(ws)
    def entry(h):
        ref = h['hypothesis_ref']; u = usage(ws, ref)
        assessments = [a for a in ws.records('assessment') if a['hypothesis_ref'] == ref]
        jobs = [j for j in ws.jobs() if ref in ws.target_hypotheses(j['target_ref'])]
        return {'hypothesis_ref': ref, 'status': h['status'], 'original_read_ref': 'original:'+ref,
                'goal': h['goal'], 'endpoint': h['endpoint'], 'usage': u,
                'closeout_due': u['requests'] >= p['hypothesis_requests'] or u['test_runs'] >= p['hypothesis_test_runs'],
                'latest_assessment_ref': assessments[-1]['ref'] if assessments else None,
                'review_jobs': [{'job_ref': j['ref'], 'status': j['status'], 'target_ref': j['target_ref']} for j in jobs[-4:]]}
    active = [entry(h) for h in hs if h['status'] == 'active']
    return {'policy': p, 'focus_hypothesis_ref': selected['hypothesis_ref'] if selected else None,
            'active': active, 'backlog_count': sum(h['status'] == 'backlog' for h in hs),
            'backlog_refs': [h['hypothesis_ref'] for h in hs if h['status'] == 'backlog'][:8],
            'terminal_count': sum(h['status'] in TERMINAL for h in hs),
            'recent_endpoints': [entry(h) for h in hs if h['status'] in TERMINAL][-3:],
            'direction': 'Finish or explicitly close the focus before opening a new branch. Negative and inconclusive endpoints are legitimate. A narrower claim is a new H, never a retroactive change to the original prediction.'}


def activate(ws, ref):
    item = get(ws, ref)
    if item['status'] in TERMINAL: raise ValueError('terminal_hypothesis: create a new version; original endpoint retained')
    if item['status'] != 'active' and len(active_refs(ws)) >= policy(ws)['max_active_hypotheses']:
        raise ValueError('active_hypothesis_limit: close an active hypothesis before activation')
    item['status'] = 'active'; save(ws, item)
    ws.db.execute("INSERT OR REPLACE INTO meta VALUES ('release_focus_hypothesis',?)", (ref,))
    return item


def set_goal(ws, args):
    ref = args['hypothesis_ref']; item = get(ws, ref)
    if item['status'] in TERMINAL: raise ValueError('terminal_hypothesis_goal')
    if item['goal'] == args: return item
    if item['goal'] or any(p['hypothesis_ref'] == ref for p in ws.records('plan')):
        raise ValueError('goal_frozen: goals must precede plans; changed criteria need a new hypothesis, old tests remain exploratory')
    item['goal'] = args; save(ws, item)
    return item


def close(ws, args, key, actor='researcher'):
    item = get(ws, args['hypothesis_ref'])
    if item['status'] in TERMINAL:
        if any(item['endpoint'].get(k) != v for k, v in args.items()):
            raise ValueError('hypothesis_endpoint_conflict: existing endpoint is immutable')
        return item['endpoint']
    ws.references(args['evidence_refs'])
    assessment = ws.record(args['assessment_ref'], 'assessment') if args.get('assessment_ref') else None
    if assessment and assessment['hypothesis_ref'] != args['hypothesis_ref']:
        raise ValueError('assessment_hypothesis_mismatch')
    verified = bool(assessment and ws.clearance(assessment['ref']))
    if args['outcome'] in ('accepted_in_scope', 'refuted'):
        expected = 'supported' if args['outcome'] == 'accepted_in_scope' else 'refuted'
        if not verified or assessment['status'] != expected:
            raise ValueError('verified_endpoint_requires_matching_cleared_assessment')
    if args.get('successor_ref'):
        ws.record(args['successor_ref'], 'hypothesis')
        if args['successor_ref'] == args['hypothesis_ref']: raise ValueError('successor_must_be_different')
    if args['outcome'] == 'superseded' and not args.get('successor_ref'):
        raise ValueError('superseded_endpoint_requires_explicit_successor')
    # Do not strand a paid critic batch, transport delivery or running compute.
    from .workflow import assert_review_work_drained
    assert_review_work_drained(ws)
    endpoint = {**args, 'actor': actor, 'created_at': now(), 'operation': key,
                'verified_assessment': verified, 'scientific_certification': False,
                'original_hypothesis_version': item['original_version']}
    item.update(status=args['outcome'], endpoint=endpoint); save(ws, item)
    ws.db.execute('INSERT OR IGNORE INTO release_hypothesis_events VALUES (?,?)', (key, encoded(endpoint)))
    for j in ws.jobs('pending')+ws.jobs('running'):
        if args['hypothesis_ref'] in ws.target_hypotheses(j['target_ref']):
            ws.db.execute('INSERT OR REPLACE INTO release_task_state VALUES (?,?,?)',
                          (j['ref'], 'blocked_execution', 'Hypothesis closed without implying review completion or clearance'))
    path = ws.root.parent/'deliveries'/('hypothesis-'+args['hypothesis_ref']+'.json')
    write_json(path, endpoint)
    return endpoint


def preflight(ws, name, args):
    p = policy(ws); hs = items(ws); selected = focus(ws)
    if name == 'save_hypothesis' and args.get('activation', 'active') == 'active':
        if len([h for h in hs if h['status'] == 'active']) >= p['max_active_hypotheses']:
            return {'ok': False, 'error_code': 'active_hypothesis_limit', 'agenda': agenda(ws),
                    'next_action': 'Close a current hypothesis or save with activation=backlog. Backlog proposals do not acquire clearance.'}
    target = args.get('hypothesis_ref')
    if name == 'run_test': target = ws.record(args['plan_ref'], 'plan')['hypothesis_ref']
    if name in ('register_test', 'run_test'):
        item = get(ws, target)
        if item['status'] != 'active':
            return {'ok': False, 'error_code': 'hypothesis_not_active', 'hypothesis_ref': target,
                    'next_action': 'Activate backlog within the WIP bound; terminal questions require an explicit new scientific version.'}
    if selected and name in ('register_test', 'run_test', 'run_python', 'start_data_job', 'retry_data_job', 'save_hypothesis'):
        u = usage(ws, selected['hypothesis_ref'])
        if u['requests'] >= p['hypothesis_requests'] or u['test_runs'] >= p['hypothesis_test_runs']:
            return {'ok': False, 'error_code': 'hypothesis_closeout_due', 'hypothesis_ref': selected['hypothesis_ref'],
                    'usage': u, 'next_action': 'Record assessment, request its bounded review, and close_hypothesis. If the evidence remains inadequate, close inconclusive or abandoned. No new branch or computation before this endpoint.'}
    return None


def enforce_endpoints(ws):
    """Bounded execution closure after actual closing opportunity, never success."""
    selected = focus(ws)
    if not selected: return None
    p = policy(ws); u = usage(ws, selected['hypothesis_ref'])
    if u['requests'] < p['hypothesis_requests']+p['closeout_requests']: return None
    return close(ws, {'hypothesis_ref': selected['hypothesis_ref'], 'outcome': 'inconclusive',
        'reason': 'Registered hypothesis request and closeout bounds exhausted; this is an execution endpoint, not refutation.',
        'assessment_ref': None, 'evidence_refs': [r['ref'] for r in ws.records('result') if r['hypothesis_ref'] == selected['hypothesis_ref']],
        'successor_ref': None}, 'request-bound:'+selected['hypothesis_ref'], actor='workflow_guard')
