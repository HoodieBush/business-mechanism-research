"""Persistent role-level graph, backed by the original scientific database.

Each role node admits at most one new model turn. Native checkpoints drain
already paid work first; a second operation journal bridges checkpoint gaps.
"""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import sqlite3
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt
from ..common import Pending, encoded, now, write_json

SLICE = 'registered model-step slice reached; study can resume'


class State(TypedDict, total=False):
    sequence: int
    turns: int
    route: str
    job_ref: str
    status: str
    reason: str
    result: dict


def classify(reason):
    if 'transport_cooldown:' in reason:
        return 'transient_cooldown'
    if any(x in reason for x in ('allocation', 'ceiling', 'admission', 'deadline', 'HTTP', 'wall limit')):
        return 'resource_stop'
    if any(x in reason for x in ('context', 'capacity', 'request_bytes')):
        return 'context_repair'
    return 'needs_inspection'


def export_handoff(backend, status, reason):
    """Read-only, deterministic delivery on every pause, slice and completion."""
    ws = backend.ws
    packet = {'at': now(), 'execution_status': status, 'reason': reason,
              'question': ws.identity['question'], 'formal_report': ws.report(),
              'records': {kind: ws.records(kind) for kind in (
                  'hypothesis', 'assessment', 'knowledge', 'state', 'review',
                  'review_response', 'report_draft')},
              'pending_jobs': ws.jobs('pending')+ws.jobs('running'),
              'budget': backend.budget.snapshot(),
              'classification': 'Readable handoff; never automatic scientific certification'}
    directory = backend.root/'deliveries'
    directory.mkdir(exist_ok=True)
    write_json(directory/'latest.json', packet)
    parts = ['# 机制研究阶段交接', '', '问题：'+packet['question'], '',
             '执行状态：'+status, '', '停止或交接原因：'+reason, '',
             '这是原始记录的可读导出。正式报告是否形成，以数据库中的 formal_report 为准。', '']
    if packet['formal_report']:
        parts += ['## 研究者正式报告', '', '```json', encoded(packet['formal_report']), '```', '']
    for kind, label in [('hypothesis', '假说及原预测'), ('assessment', '候选判断与证据'),
                        ('review', '独立核验'), ('review_response', '研究者回应'),
                        ('report_draft', '研究者报告草稿'), ('state', '研究进展与下一步')]:
        records = packet['records'][kind]
        parts += ['## '+label, '']
        if not records:
            parts += ['尚无对应记录。', '']
        for record in records:
            parts += ['```json', json.dumps(record, ensure_ascii=False, indent=2), '```', '']
    parts += ['## 待完成工作', '', '```json', json.dumps(packet['pending_jobs'], ensure_ascii=False, indent=2),
              '```', '', '费用与完整状态见 latest.json；原始证据、过程与版本均保留在研究工作区。', '']
    path = directory/'阶段交接.md'
    path.write_text('\n'.join(parts))
    return str(path)


class ResearchGraph:
    def __init__(self, backend, checkpointer, *, thread_id, max_turns=80):
        if max_turns <= 0:
            raise ValueError('finite positive graph turn bound required')
        self.backend, self.thread_id, self.max_turns = backend, thread_id, max_turns
        self.operations = backend.root/'graph_operations.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operations(thread TEXT,seq INTEGER,role TEXT,job TEXT,baseline INTEGER,result TEXT,PRIMARY KEY(thread,seq))')
        builder = StateGraph(State)
        for name in ('select', 'researcher', 'critic', 'deliver', 'pause'):
            builder.add_node(name, getattr(self, name))
        builder.add_edge(START, 'select')
        builder.add_conditional_edges('select', lambda s: s['route'],
                                      {x: x for x in ('researcher', 'critic', 'deliver', 'pause')})
        for role in ('researcher', 'critic'):
            builder.add_conditional_edges(role, lambda s: s['route'], {'select': 'select', 'pause': 'pause'})
        builder.add_edge('pause', 'select')
        builder.add_edge('deliver', END)
        self.graph = builder.compile(checkpointer=checkpointer)
        self.config = {'configurable': {'thread_id': thread_id}, 'recursion_limit': max_turns*4+20}

    def connect(self):
        return sqlite3.connect(self.operations, timeout=10)

    def select(self, state):
        ws = self.backend.ws
        self.backend.start_closeout()
        with ws.db:
            ws.try_seal_report()
        ws._publish()
        if ws.report():
            return {'route': 'deliver', 'status': 'completed', 'reason': 'formal topic report saved'}
        if state.get('turns', 0) >= self.max_turns:
            return {'route': 'pause', 'status': 'pending', 'reason': 'registered graph turn ceiling reached'}
        with self.backend.budget.connect() as db:
            paid_roles = {role for role, in db.execute('SELECT DISTINCT role FROM attempts')}
        all_jobs = ws.jobs('running')+ws.jobs('pending')
        paid = [job for job in all_jobs if 'critic:'+job['ref'] in paid_roles]
        requested = ws.delegated_jobs()
        pending = paid+[job for job in requested if job['ref'] not in {j['ref'] for j in paid}]
        return {'route': 'critic' if pending else 'researcher',
                'job_ref': pending[0]['ref'] if pending else '',
                'sequence': state.get('sequence', 0)+1, 'status': 'running', 'reason': ''}

    def role_checkpoint(self, role, job):
        path = (self.backend.ws.private/'checkpoint.json' if role == 'researcher' else
                self.backend.root/'reviews'/job/'critic/private/checkpoint.json')
        return json.loads(path.read_text()) if path.exists() else {'responses': 0}

    def step(self, role, state):
        seq, job = state['sequence'], state.get('job_ref', '')
        with self.connect() as db:
            row = db.execute('SELECT role,job,baseline,result FROM operations WHERE thread=? AND seq=?',
                             (self.thread_id, seq)).fetchone()
            if not row:
                baseline = self.role_checkpoint(role, job)['responses']
                db.execute('INSERT INTO operations VALUES (?,?,?,?,?,NULL)',
                           (self.thread_id, seq, role, job, baseline))
            else:
                if row[:2] != (role, job):
                    raise RuntimeError('graph operation role identity changed')
                if row[3]:
                    return json.loads(row[3])
                baseline = row[2]
        # A role completed before the graph checkpoint was saved: drain only,
        # never generate another model turn in the same graph operation.
        advanced = self.role_checkpoint(role, job)['responses'] > baseline
        try:
            if role == 'researcher':
                result = self.backend.runtime.run(0) if advanced else self.backend.researcher_step()
            else:
                result = self.backend.critic_step(self.backend.ws.job(job), model_steps=0 if advanced else 1)
            continuing = result['status'] == 'completed' or result.get('reason') == SLICE
            update = {'route': 'select' if continuing else 'pause', 'result': result,
                      'turns': state.get('turns', 0)+1,
                      'status': 'running' if continuing else 'pending', 'reason': result.get('reason', '')}
        except Exception as error:
            # Unexpected faults are visible and paused, never retried as science.
            update = {'route': 'pause', 'status': 'pending', 'turns': state.get('turns', 0)+1,
                      'reason': type(error).__name__+': '+str(error),
                      'result': {'error_type': type(error).__name__, 'scientific_status_changed': False}}
        with self.connect() as db:
            db.execute('UPDATE operations SET result=? WHERE thread=? AND seq=?',
                       (encoded(update), self.thread_id, seq))
        return update

    def researcher(self, state):
        return self.step('researcher', state)

    def critic(self, state):
        return self.step('critic', state)

    def pause(self, state):
        path = export_handoff(self.backend, 'pending', state.get('reason', ''))
        decision = interrupt({'status': 'pending', 'reason': state.get('reason', ''),
                              'category': classify(state.get('reason', '')), 'handoff': path,
                              'resume': 'same thread, native paid work and scientific records retained'})
        if decision != 'continue':
            raise ValueError('resume with the explicit string continue')
        return {'route': 'select', 'reason': '', 'status': 'running'}

    def deliver(self, state):
        path = export_handoff(self.backend, 'completed', state.get('reason', ''))
        return {'status': 'completed', 'result': {'report_ref': self.backend.ws.report()['ref'], 'handoff': path}}

    def invoke(self, *, resume=False):
        lock = (self.backend.root/'research_run.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = self.graph.get_state(self.config)
            if current.values.get('status') == 'completed':
                return current.values
            if current.tasks and any(task.interrupts for task in current.tasks):
                if not resume:
                    return {**current.values, 'status': 'pending', 'resume_required': True}
                request = Command(resume='continue')
            else:
                request = None if current.values else {'sequence': 0, 'turns': 0}
            result = self.graph.invoke(request, self.config, durability='sync')
            if '__interrupt__' in result:
                result['status'] = 'pending'
            export_handoff(self.backend, result.get('status', 'pending'), result.get('reason', ''))
            return result
        except Exception as error:
            export_handoff(self.backend, 'pending', type(error).__name__+': '+str(error))
            raise
        finally:
            lock.close()


@contextmanager
def open_graph(backend, *, thread_id, max_turns=80):
    with SqliteSaver.from_conn_string(str(backend.root/'graph_checkpoints.sqlite')) as saver:
        yield ResearchGraph(backend, saver, thread_id=thread_id, max_turns=max_turns)
