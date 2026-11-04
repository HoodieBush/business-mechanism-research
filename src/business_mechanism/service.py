"""Local integration API with finite, persistent, cross-role execution limits."""
from copy import deepcopy
import json
from pathlib import Path
import signal
import fcntl
import sqlite3
import sys
import time
from experiments.insight_research.common import Pending, digest, now, sha, write_json
from experiments.insight_research.growth_probe_v01.environment import World
from experiments.insight_research.paired_v01.budget import StudyBudget
from experiments.insight_research.prompt_runtime_v05.prompts import source_identity as prompt_sources
from .data import SQLiteWorld
from .engine import Backend, ResearchWorkspace, SQLiteWorkspace, source_identity
from .graph import open_graph, export_handoff
from .delivery import export_report
from .sandbox import probe_runtime

DEFAULT_LIMITS = {'token_allowance': 2000000, 'max_http_attempts': 80, 'max_transport_retries': 2,
                  'round_wall_seconds': 3600, 'max_request_bytes': 524288, 'recent_turns': 4,
                  'knowledge_context_bytes': 24000}


def validate_model(model, root):
    if any(k in model for k in ('api_key', 'access_token', 'token', 'authorization')):
        raise ValueError('Store credentials outside project configuration; use api_key_file or api_key_env.')
    for k in ('model', 'base_url'):
        if not isinstance(model.get(k), str) or not model[k]:
            raise ValueError('Model configuration requires '+k)
    if model.get('api_key_file') and Path(model['api_key_file']).expanduser().resolve().is_relative_to(root):
        raise ValueError('Credential file must be outside the project directory.')


def create_project(path, question, model, *, data=None, demo=None, limits=None, wall_seconds=7200, max_stages=2):
    """data: folder with business.sqlite, business_brief.md, data_dictionary.json.

    demo: private simulator kwargs. Exactly one input adapter is required.
    Creating a project does not make model calls.
    """
    root = Path(path).expanduser().resolve()
    if root.exists():
        raise ValueError('Project already exists; open or resume it instead of resetting it.')
    if (data is None) == (demo is None):
        raise ValueError('Choose exactly one input adapter: data or demo.')
    if not question.strip() or not 1 <= max_stages <= 100 or wall_seconds <= 0:
        raise ValueError('Nonempty question and finite positive service bounds required.')
    validate_model(model, root)
    cfg = {**DEFAULT_LIMITS, **(limits or {})}
    if any(type(cfg[k]) is not int or cfg[k] <= 0 for k in ('token_allowance', 'max_http_attempts', 'max_request_bytes')):
        raise ValueError('Finite positive execution capacity required.')
    timeout = model.get('request_timeout_seconds', 600)
    if wall_seconds < timeout+45:
        raise ValueError('Wall allowance must admit one model request and tool feedback.')
    kind = 'sqlite' if data is not None else 'service_demo'
    if data is not None:
        source = Path(data).expanduser().resolve()
        for name in ('business.sqlite', 'business_brief.md', 'data_dictionary.json'):
            if not (source/name).is_file() or (source/name).is_symlink():
                raise ValueError('Read-only input folder requires regular '+name)
        json.loads((source/'data_dictionary.json').read_text())
        with sqlite3.connect((source/'business.sqlite').as_uri()+'?mode=ro', uri=True) as check:
            if check.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Input SQLite integrity check failed.')
    else:
        World(**demo)  # Validate before creating anything.
    root.mkdir(parents=True)
    if kind == 'sqlite':
        import shutil
        target = root/'inputs'; target.mkdir()
        with sqlite3.connect((source/'business.sqlite').as_uri()+'?mode=ro', uri=True) as src, sqlite3.connect(target/'business.sqlite') as dst:
            src.backup(dst)
        for name in ('business_brief.md', 'data_dictionary.json'):
            shutil.copyfile(source/name, target/name)
    settings = {'research_profile': 'paired_research_v1', 'verification_mode': 'independent',
                'model_config': deepcopy(model), 'limits': cfg, 'prompt_runtime_sources': prompt_sources(),
                'release_sources': source_identity(), 'workflow_policy': {'max_lineage_reviews': 4},
                'execution_policy': {'active_context_bytes': 65536, 'closeout_reserve_tokens': min(400000, cfg['token_allowance']//3),
                    'review_http_limit': 10, 'wall_seconds': wall_seconds, 'warn_after_requests': 8, 'stop_after_requests': 16},
                'initialization_notice': 'Research starts with the supplied lawful inputs and no harness-provided scientific conclusions. Choose hypotheses and checks yourself; negative and unresolved results are legitimate.'}
    project = {'version': 1, 'created_at': now(), 'question': question, 'input_kind': kind,
               'demo': demo, 'settings': settings, 'max_stages': max_stages, 'active_stage': 1,
               'source_identity': source_identity()}
    write_json(root/'project.json', project)
    world = World(**demo) if kind == 'service_demo' else SQLiteWorld(root/'inputs')
    cls = ResearchWorkspace if kind == 'service_demo' else SQLiteWorkspace
    ws = cls(root/'researcher', question, world, settings)
    try:
        identity = {'study_id': 'local-release', 'run_id': root.name, 'project_budget_id': 'optional-external-ledger',
                    'token_allowance': cfg['token_allowance'], 'max_http_attempts': cfg['max_http_attempts']}
        budget = StudyBudget(root/'common_budget.sqlite', identity, create=True)
        write_json(root/'stage_history.json', [{'stage': 1, 'started_at': now(), 'starting_record_rowid': 0}])
        from types import SimpleNamespace
        initial = SimpleNamespace(root=root, ws=ws, budget=budget)
        export_handoff(initial, 'ready', 'Project created; no model call has been sent.')
        export_report(initial)
    finally:
        ws.close()
    return project_status(root)


def open_project(path):
    root = Path(path).expanduser().resolve()
    project = json.loads((root/'project.json').read_text())
    if project['source_identity'] != source_identity():
        raise ValueError('Source version differs; use the pinned release to resume, or explicitly migrate without overwriting old state.')
    world = World(**project['demo']) if project['input_kind'] == 'service_demo' else SQLiteWorld(root/'inputs')
    cls = ResearchWorkspace if project['input_kind'] == 'service_demo' else SQLiteWorkspace
    ws = cls(root/'researcher', project['question'], world, project['settings'], reopen=True)
    # SQLite is authoritative across a crash between a stage commit and JSON
    # cache/history writes. Never reset a stage marker or paid counters.
    stage = ws.db.execute('SELECT max(stage) FROM release_stages').fetchone()[0]
    if project['active_stage'] != stage:
        project['active_stage'] = stage
        write_json(root/'project.json', project)
    with sqlite3.connect(root/'common_budget.sqlite') as db:
        identity = json.loads(db.execute('SELECT body FROM identity').fetchone()[0])
    return root, project, ws, Backend(root, ws, project['settings']['model_config'], StudyBudget(root/'common_budget.sqlite', identity))


def project_status(path):
    root = Path(path).expanduser().resolve()
    project = json.loads((root/'project.json').read_text())
    with sqlite3.connect((root/'common_budget.sqlite').as_uri()+'?mode=ro', uri=True) as db:
        identity = json.loads(db.execute('SELECT body FROM identity').fetchone()[0])
    status = root/'service_status.json'
    return {'path': str(root), 'active_stage': project['active_stage'], 'max_stages': project['max_stages'],
            'last_execution': json.loads(status.read_text()) if status.exists() else {'status': 'ready'},
            'execution_usage': StudyBudget(root/'common_budget.sqlite', identity).snapshot(),
            'report': str(root/'deliveries/当前研究报告.md'), 'handoff': str(root/'deliveries/阶段交接.md'),
            'archived_reports': [str(p) for p in sorted((root/'deliveries').glob('F*.md'))]}


def request_pause(path, reason='operator request'):
    root = Path(path).expanduser().resolve()
    if not (root/'project.json').exists():
        raise ValueError('Project not found.')
    write_json(root/'pause_requested.json', {'at': now(), 'reason': reason})


def advance_stage(root, project, ws, backend):
    report = ws.report()
    if not report:
        raise Pending('Current stage has no current valid report; preserve unresolved work before advancing.')
    if backend.runtime.cp.get('pending') or backend.journal.state.get('inflight') or backend.journal.state.get('delivery'):
        raise Pending('Drain paid work before advancing a stage.')
    if project['active_stage'] >= project['max_stages']:
        return False
    marker = ws.db.execute('SELECT coalesce(max(rowid),0) FROM records').fetchone()[0]
    with ws.db:
        ws.db.execute("INSERT OR REPLACE INTO meta VALUES ('release_stage_marker',?)", (str(marker),))
        ws.db.execute('INSERT INTO release_stages VALUES (?,?,?,?)',
                      (project['active_stage']+1, marker, report['ref'], now()))
    project['active_stage'] += 1
    write_json(root/'project.json', project)
    history = json.loads((root/'stage_history.json').read_text())
    history.append({'stage': project['active_stage'], 'started_at': now(), 'starting_record_rowid': marker,
                    'previous_report_ref': report['ref'], 'all_prior_science_and_costs_retained': True})
    write_json(root/'stage_history.json', history)
    backend.runtime.cp['messages'].append({'role': 'user', 'content':
        'A new research stage begins after the completed report '+report['ref']+'. Preserve and reuse prior evidence and memory. Decide which next hypothesis, counterevidence or missing measurement is worth studying. Do not re-publish the previous draft as new work. The same total resource limits still apply.'})
    backend.runtime.cp.update(status='running', reason=None); backend.runtime.save()
    return True


def run_project(path, *, stages=1, resume=False):
    if type(stages) is not int or not 1 <= stages <= 100:
        raise ValueError('Finite positive stage count required.')
    probe_runtime()
    root = Path(path).expanduser().resolve()
    lock = (root/'service.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {'status': 'pending', 'reason': 'another service controller owns this project'}
    try:
        root, project, ws, backend = open_project(path)
    except Exception:
        lock.close(); raise
    previous_handler = None
    try:
        if resume:
            (root/'pause_requested.json').unlink(missing_ok=True)
        if __import__('threading').current_thread() is __import__('threading').main_thread():
            previous_handler = signal.signal(signal.SIGTERM, lambda *_: request_pause(root, 'SIGTERM'))
        result = {'status': 'ready'}
        for stage_index in range(stages):
            if ws.report() and not advance_stage(root, project, ws, backend):
                result = {'status': 'completed', 'reason': 'registered stage count reached'}; break
            stage = project['active_stage']
            with open_graph(backend, thread_id='stage-'+str(stage), max_turns=project['settings']['limits']['max_http_attempts']+10) as graph:
                result = graph.invoke(resume=resume)
                for _ in range(3):
                    reason = result.get('reason', '')
                    if 'transport_cooldown:' not in reason:
                        break
                    until = float(reason.split('transport_cooldown:')[1].split()[0])
                    time.sleep(max(0, min(60, until-time.time()+.05)))
                    result = graph.invoke(resume=True)
            result.pop('__interrupt__', None)
            result['stage'] = stage
            write_json(root/'service_status.json', result)
            if result.get('status') != 'completed':
                break
            resume = False
        export_handoff(backend, result.get('status', 'pending'), result.get('reason', 'finite service slice ended'))
        export_report(backend)
        return result
    except Exception as error:
        result = {'status': 'pending', 'reason': type(error).__name__+': '+str(error)}
        write_json(root/'service_status.json', result)
        export_handoff(backend, 'pending', result['reason'])
        export_report(backend)
        raise
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
        ws.close()
        lock.close()
