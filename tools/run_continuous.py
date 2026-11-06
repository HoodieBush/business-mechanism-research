"""Observe one real project for a finite wall-clock window, without resetting it.

Run in tmux using the installed venv. Each completed stage continues from the
same project. Structural pauses are recorded and monitored, not bypassed.
"""
import argparse
import hashlib
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


def timestamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat()


def recovery_event_id(output, controller_slice):
    # The recovery ledger is copied across experiments. A local slice number
    # alone can replay an unrelated predecessor's completed recovery receipt.
    namespace = hashlib.sha256(str(Path(output).resolve()).encode()).hexdigest()[:24]
    return f'supervisor-{namespace}-slice-{controller_slice}'


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def connect(path):
    return sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=5)


def sample(project):
    configuration = read_json(project / 'project.json')
    with connect(project / 'common_budget.sqlite') as db:
        count, reported, accounted = db.execute('SELECT count(*),coalesce(sum(actual),0),coalesce(sum(coalesce(actual,bound)),0) FROM attempts').fetchone()
        roles = {role: {'requests': n, 'reported_tokens': tokens} for role, n, tokens in
                 db.execute('SELECT role,count(*),coalesce(sum(actual),0) FROM attempts GROUP BY role')}
        statuses = dict(db.execute('SELECT status,count(*) FROM attempts GROUP BY status'))
    with connect(project / 'researcher/private/records.sqlite') as db:
        records = dict(db.execute('SELECT kind,count(*) FROM records GROUP BY kind'))
        jobs = dict(db.execute('SELECT status,count(*) FROM review_jobs GROUP BY status'))
        events = db.execute('SELECT count(*) FROM events').fetchone()[0]
        has_outcomes = db.execute("SELECT 1 FROM sqlite_master WHERE name='release_stage_outcomes'").fetchone()
        outcomes = [json.loads(b) for b, in db.execute('SELECT body FROM release_stage_outcomes ORDER BY stage')] if has_outcomes else []
    return {'at': timestamp(), 'active_stage': configuration['active_stage'], 'records': records,
            'review_jobs': jobs, 'tool_events': events, 'requests': count,
            'reported_tokens': reported, 'accounted_tokens': accounted,
            'unknown_or_inflight_reserve': accounted - reported, 'attempt_statuses': statuses,
            'roles': roles, 'archived_reports': [p.name for p in sorted((project / 'deliveries').glob('F*.md'))],
            'last_execution': read_json(project / 'service_status.json', {'status': 'ready'}),
            'stage_outcomes': outcomes, 'semantic_health': read_json(project/'semantic_health.json', None)}


def classify_pending(reason, remaining):
    if 'semantic_stagnation:' in reason:
        return 'semantic_stagnation'
    if 'operator requested pause' in reason:
        return 'operator_pause'
    if 'transport_cooldown:' in reason:
        return 'transient_cooldown'
    if reason == 'registered model-step slice reached; study can resume':
        return 'resumable_slice'
    if reason.startswith(('registered graph turn ceiling reached','bounded fixed context cannot fit',
                          'fixed critical context/latest complete turn still exceeds guard')):
        return 'recoverable_task_stall'
    if 'persistent study wall deadline' in reason and remaining <= 700:
        return 'scheduled_admission_drain'
    return 'structural_pause'


def final_report(output, project, manifest, state):
    final = sample(project)
    findings = {}
    with connect(project / 'researcher/private/records.sqlite') as db:
        for kind in ('hypothesis', 'assessment', 'knowledge', 'review', 'review_response', 'report'):
            findings[kind] = [json.loads(body) for body, in db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid', (kind,))]
    elapsed = time.time() - manifest['started_unix']
    summary = {'started_at': manifest['started_at'], 'ended_at': timestamp(),
               'scheduled_end_at': manifest['deadline_at'], 'elapsed_seconds': elapsed,
               'full_observation_window_completed': elapsed >= manifest['duration_seconds'],
               'token_limit': None, 'request_limit': None, 'final_snapshot': final,
               'first_structural_pause': state.get('first_structural_pause'),
               'controller_slices': state['controller_slices'], 'stage_completions': state['stage_completions'],
               'child_alive_observed_seconds': state['child_alive_observed_seconds'],
               'failed_or_stalled_observed_seconds': state['failed_or_stalled_observed_seconds'],
               'forced_child_termination': state.get('forced_child_termination', False),
               'stop_reason': state.get('stop_reason'), 'science_records': findings,
               'scope': 'Observed process continuity, saved research progress and formal reports are separate outcomes. Findings are model-authored and not automatically scientifically correct.'}
    summary['recovery_events'] = state.get('recovery_events', [])
    summary['uninterrupted_research_window'] = (summary['full_observation_window_completed']
        and state.get('first_structural_pause') is None and not state.get('watchdog_triggered') and not state.get('recovery_events'))
    initial = manifest.get('initial_snapshot', {})
    summary['segment_usage'] = {key: final[key]-initial.get(key, 0) for key in ('requests', 'reported_tokens', 'accounted_tokens')}
    summary['initial_snapshot'] = initial
    summary['unresolved_stage_closures'] = state.get('unresolved_stage_closures', 0)
    write_json(output / 'summary.json', summary)
    lines = ['# 24小时研究运行观察', '', '开始：' + manifest['started_at'], '结束：' + summary['ended_at'],
             '计划结束：' + manifest['deadline_at'], '',
             '完整观察窗口完成：' + str(summary['full_observation_window_completed']),
             '累计模型请求：' + str(final['requests']), '累计已报告tokens：' + str(final['reported_tokens']),
             '本段新增模型请求：' + str(summary['segment_usage']['requests']),
             '本段新增已报告tokens：' + str(summary['segment_usage']['reported_tokens']),
             '保留的未知/在途预约：' + str(final['unknown_or_inflight_reserve']),
             '完成阶段：' + str(state['stage_completions']), '正式报告数：' + str(len(final['archived_reports'])),
             '首次结构性停止：' + json.dumps(state.get('first_structural_pause'), ensure_ascii=False),
             '', '进程存活、研究进展和结论正确性分别评价；以下是原记录导出，不自动认证业务机制。',
             '', '## 正式报告', '']
    lines += [str(project / 'deliveries' / name) for name in final['archived_reports']] or ['尚无正式报告。']
    for kind in ('hypothesis', 'assessment', 'knowledge'):
        lines += ['', '## ' + kind, '']
        for record in findings[kind]:
            lines += ['```json', json.dumps(record, ensure_ascii=False, indent=2), '```', '']
    lines += ['', '完整核验、回应和状态见summary.json、events.jsonl、heartbeats.jsonl及原研究工作区。']
    (output / '24小时运行结果.md').write_text('\n'.join(lines) + '\n')


def supervise(project, output, duration, heartbeat=60, drain_seconds=660, *, resume_first=False, deadline_unix=None, continuation_of=None):
    from business_mechanism.engine import source_identity
    from business_mechanism.service import request_pause

    project, output = project.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = (output / 'supervisor.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (output / 'run.json').exists():
        raise ValueError('An observation already exists here; never reset its clock or records.')
    configuration = read_json(project / 'project.json')
    if source_identity() != configuration['source_identity']:
        raise ValueError('Installed source identity differs from the prepared project.')
    started = time.time()
    if deadline_unix is not None:
        duration = deadline_unix-started
        if not 0 < duration <= 86400:
            raise ValueError('Continuation must use a future original deadline within 24 hours; never extend it silently.')
    manifest = {'started_at': timestamp(started), 'started_unix': started,
                'deadline_at': timestamp(started + duration), 'deadline_unix': started + duration,
                'started_local': datetime.fromtimestamp(started, ZoneInfo('Asia/Shanghai')).isoformat(),
                'deadline_local': datetime.fromtimestamp(started + duration, ZoneInfo('Asia/Shanghai')).isoformat(),
                'duration_seconds': duration, 'project': str(project), 'pid': os.getpid(),
                'token_limit': None, 'request_limit': None,
                'native_integer_compatibility_values': {key: configuration['settings']['limits'][key] for key in ('token_allowance', 'max_http_attempts')},
                'native_max_stages': configuration['max_stages'],
                'single_response_max_tokens': configuration['settings']['model_config']['generation_options']['max_tokens'],
                'source_identity': source_identity(), 'supervisor_sha256': __import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),
                'authorization': 'User requested one 24-hour continuous run with no token/quota limit.',
                'recovery_policy': 'Resume native cooldowns, completed stages and registered bounded task rotations. Recovery events are scoped to this observation; all paid counters, no-progress history, rejected tools, hypotheses and evidence are retained.',
                'recovery_event_namespace': recovery_event_id(output, 0),
                'deadline_policy': 'Stop at the 24-hour wall clock; let the current paid batch drain, up to the configured grace, then terminate its process group.'}
    manifest.update(initial_snapshot=sample(project), resume_first=resume_first,
                    continuation_of=continuation_of,
                    authorization='User authorized robustness repairs and continuation within the original deadline.' if continuation_of else manifest['authorization'])
    authorization_window=read_json(project/'authorization_window.json')
    if authorization_window and abs(authorization_window['deadline_unix']-manifest['deadline_unix'])<.01:
        manifest.update(authorization_window=authorization_window,
                        authorization=authorization_window['reason'],
                        deadline_policy='Explicit newly authorized finite window; prior deadline, failed observations and all costs remain in the authorization receipt. Automatic task recovery cannot extend this deadline.')
    write_json(output / 'run.json', manifest)
    state = {'phase': 'starting', 'controller_slices': 0, 'stage_completions': 0,
             'unresolved_stage_closures': 0,
             'child_alive_observed_seconds': 0, 'failed_or_stalled_observed_seconds': 0,
             'first_structural_pause': None, 'stop_reason': None}
    state.update(recovery_events=[], last_activity_unix=started, watchdog_triggered=False)
    watchdog_seconds = configuration['settings']['limits']['round_wall_seconds']+120
    last_activity = None
    child = None
    handle = None
    next_attempt = started
    next_sample = started
    previous_tick = started
    stop = {'reason': None}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(reason='operator SIGTERM'))
    signal.signal(signal.SIGINT, lambda *_: stop.update(reason='operator SIGINT'))
    env = dict(os.environ)
    env['PATH'] = str(Path(sys.executable).absolute().parent) + os.pathsep + env.get('PATH', '')

    def event(kind, **details):
        row = {'at': timestamp(), 'event': kind, **details}
        with (output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)

    try:
        event('observation_started', deadline=manifest['deadline_at'])
        while time.time() < manifest['deadline_unix'] and not stop['reason']:
            now = time.time()
            elapsed = max(0, now - previous_tick)
            if child and child.poll() is None:
                state['child_alive_observed_seconds'] += elapsed
            if state['phase'] in ('structural_pause', 'semantic_stagnation', 'controller_error', 'registered_stage_limit'):
                state['failed_or_stalled_observed_seconds'] += elapsed
            previous_tick = now
            if child and child.poll() is not None:
                code = child.returncode
                handle.close()
                child = None
                result = read_json(project / 'service_status.json', {})
                reason = result.get('reason', '')
                event('controller_exit', exit_code=code, result=result)
                if code == 0 and result.get('status') in ('completed', 'stage_closed'):
                    state['stage_completions'] += int(result['status'] == 'completed')
                    state['unresolved_stage_closures'] += int(result['status'] == 'stage_closed')
                    current = read_json(project / 'project.json')
                    if current['active_stage'] >= current['max_stages']:
                        state['phase'] = 'registered_stage_limit'
                        reason = 'native registered stage ceiling reached'
                    else:
                        state['phase'] = 'between_stages'
                        next_attempt = now
                else:
                    state['phase'] = classify_pending(reason, manifest['deadline_unix'] - now) if code == 3 else 'controller_error'
                    if state['phase'] in ('transient_cooldown', 'resumable_slice'):
                        next_attempt = now + (60 if state['phase'] == 'transient_cooldown' else 1)
                    elif state['phase'] == 'operator_pause':
                        stop['reason'] = 'operator requested pause'
                if state['phase'] in ('semantic_stagnation','recoverable_task_stall'):
                    from business_mechanism.recovery import recover_execution
                    event_id = recovery_event_id(output, state['controller_slices'])
                    try:
                        receipt = recover_execution(project, reason=reason, event_id=event_id)
                        state['recovery_events'].append(receipt)
                        state['phase'] = 'between_stages'; next_attempt = now+1
                        event('task_rotated', receipt=receipt)
                    except (ValueError, OSError, sqlite3.Error) as error:
                        state['phase'] = 'structural_pause'
                        reason = 'Automatic recovery refused: '+str(error)
                        event('task_rotation_refused', reason=reason)
                if state['phase'] in ('structural_pause', 'semantic_stagnation', 'controller_error', 'registered_stage_limit') and state['first_structural_pause'] is None:
                    state['first_structural_pause'] = {'at': timestamp(), 'reason': reason or 'controller exited without a durable result', 'exit_code': code}
            if not child and now >= next_attempt and state['phase'] in ('starting', 'between_stages', 'transient_cooldown', 'resumable_slice'):
                state['controller_slices'] += 1
                handle = (output / ('controller-' + str(state['controller_slices']) + '.log')).open('a')
                command = [sys.executable, '-u', '-m', 'business_mechanism.cli', 'run', str(project), '--stages', '1']
                if state['controller_slices'] > 1 or resume_first:
                    command.append('--resume')
                child = subprocess.Popen(command, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
                state['phase'] = 'running'
                event('controller_started', pid=child.pid, command=command)
            if now >= next_sample:
                try:
                    snapshot = sample(project)
                    activity = (snapshot['requests'], snapshot['tool_events'], len(snapshot['archived_reports']))
                    if activity != last_activity:
                        last_activity = activity; state['last_activity_unix'] = now
                    if child and child.poll() is None and now-state['last_activity_unix'] > watchdog_seconds and not state['watchdog_triggered']:
                        state['watchdog_triggered'] = True
                        stop['reason'] = 'controller_watchdog: no durable activity beyond registered round bound'
                        event('controller_watchdog', child_pid=child.pid, seconds=watchdog_seconds,
                              policy='Cooperative stop and bounded process-group drain; preserve inflight reservations, do not blindly replay paid work.')
                    row = {**snapshot, 'phase': state['phase'], 'elapsed_seconds': now - started,
                           'remaining_seconds': max(0, manifest['deadline_unix'] - now),
                           'child_pid': child.pid if child else None, 'supervisor_pid': os.getpid(),
                           'first_structural_pause': state['first_structural_pause']}
                    row.update(recovery_count=len(state['recovery_events']),
                               seconds_without_durable_activity=now-state['last_activity_unix'],
                               watchdog_seconds=watchdog_seconds,
                               research_running=bool(child and child.poll() is None))
                    with (output / 'heartbeats.jsonl').open('a') as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                    write_json(output / 'status.json', row)
                    if int((now - started) // 3600) != state.get('last_hour'):
                        state['last_hour'] = int((now - started) // 3600)
                        write_json(output / ('hour-' + str(state['last_hour']) + '.json'), row)
                except (OSError, sqlite3.Error, ValueError) as error:
                    event('sampling_error', error=type(error).__name__ + ': ' + str(error))
                next_sample = now + heartbeat
            time.sleep(min(1, max(.01, manifest['deadline_unix'] - time.time())))
        state['stop_reason'] = stop['reason'] or '24-hour observation wall deadline reached'
    except Exception as error:
        state['stop_reason'] = 'supervisor error: ' + type(error).__name__ + ': ' + str(error)
        event('supervisor_error', error=state['stop_reason'])
    finally:
        request_pause(project, state['stop_reason'] or 'supervisor stopped')
        if child and child.poll() is None:
            child.send_signal(signal.SIGTERM)
            drain_deadline = time.time() + drain_seconds
            event('paid_batch_drain_started', child_pid=child.pid, grace_seconds=drain_seconds)
            while child.poll() is None and time.time() < drain_deadline:
                time.sleep(1)
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                state['forced_child_termination'] = True
                event('forced_child_termination', unknown_reservations_retained=True)
        if handle and not handle.closed:
            handle.close()
        state['phase'] = 'ended'
        final_report(output, project, manifest, state)
        write_json(output / 'status.json', {**sample(project), **state, 'ended_at': timestamp()})
        event('observation_ended', reason=state['stop_reason'])
        lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--duration-seconds', type=int, default=86400)
    parser.add_argument('--heartbeat-seconds', type=float, default=60)
    parser.add_argument('--drain-seconds', type=int, default=660)
    parser.add_argument('--resume-first', action='store_true')
    parser.add_argument('--deadline-unix', type=float)
    parser.add_argument('--continuation-of', type=Path)
    args = parser.parse_args()
    if not 0 < args.duration_seconds <= 86400 or args.heartbeat_seconds <= 0 or args.drain_seconds < 0:
        parser.error('Provide a finite positive duration of at most 24 hours and valid observation intervals.')
    supervise(args.project, args.output, args.duration_seconds, args.heartbeat_seconds, args.drain_seconds,
              resume_first=args.resume_first, deadline_unix=args.deadline_unix,
              continuation_of=str(args.continuation_of) if args.continuation_of else None)
