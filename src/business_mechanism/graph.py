"""Release graph adds cooperative pause and delivery after every safe turn."""
from contextlib import contextmanager
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from experiments.insight_research.langgraph_release_v02.graph import ResearchGraph as Previous, export_handoff as previous_handoff
from .delivery import export_report
import json
from experiments.insight_research.common import encoded, write_json
from .workflow import close_stage, stage_number
from .data_jobs import DataJobs
from . import convergence
from . import verification_tasks
from .workflow import assert_review_work_drained


def export_handoff(backend, status, reason):
    path = previous_handoff(backend, status, reason)
    outcome = backend.ws.stage_outcome()
    if outcome:
        packet_path = backend.root/'deliveries/latest.json'
        packet = json.loads(packet_path.read_text())
        packet['stage_outcome'] = outcome
        write_json(packet_path, packet)
        with open(path, 'a') as stream:
            stream.write('\n\n## 未决阶段交接\n\n'+outcome['reason']+'\n\n此交接不授予科学主张clearance；原证据、异议与费用保留。\n')
    return path


class ResearchGraph(Previous):
    def select(self, state):
        pause = self.backend.root/'pause_requested.json'
        if pause.exists():
            return {'route': 'pause', 'status': 'pending', 'reason': 'operator requested pause; current paid tool batch drained'}
        ws=self.backend.ws
        if (not ws.stage_outcome() and not ws.report() and not convergence.active_refs(ws)
                and not self.backend.runtime.cp.get('pending') and not ws.delegated_jobs()):
            tasks=verification_tasks.repair_tasks(ws)
            if tasks:
                try:
                    assert_review_work_drained(ws)
                    task=tasks[0]
                    with ws.db:
                        verification_tasks.request(ws,{'target_ref':task['target_ref'],'expected_review_ref':task['expected_review_ref'],
                            'reason':'Workflow priority: complete missing method coverage of this unchanged planned finding before another branch.'},
                            'workflow-revalidation:'+task['expected_review_ref'])
                except ValueError as error:
                    if 'requires_drained' not in str(error) and 'requires_finished' not in str(error):raise
        if not self.backend.runtime.cp.get('pending'):
            try:
                with self.backend.ws.db: convergence.enforce_endpoints(self.backend.ws)
            except ValueError as error:
                if 'requires_drained' not in str(error) and 'requires_finished' not in str(error): raise
        outcome = self.backend.ws.stage_outcome()
        if not outcome:
            ws = self.backend.ws
            fingerprint = self.backend.guard.fingerprint()
            count = ws.db.execute('SELECT count(*) FROM release_delivery_attempts WHERE stage=? AND fingerprint=?',
                                (stage_number(ws), fingerprint)).fetchone()[0]
            computing = any(j['status'] in ('queued', 'running') for j in DataJobs(ws).jobs())
            repairing=any(j.get('parent_review_ref') for j in ws.delegated_jobs())
            if count >= 4 and not computing and not repairing:
                with ws.db:
                    outcome = close_stage(ws, outcome='blocked', reason='Repeated delivery without new evidence or coverage; bounded unresolved handoff.',
                        unresolved_refs=[a['ref'] for a in ws.records('assessment') if not ws.clearance(a['ref'])],
                        evidence_refs=[], key='bounded-delivery:'+str(stage_number(ws)), actor='workflow_guard')
        if outcome:
            return {'route': 'deliver', 'status': 'stage_closed', 'reason': outcome['reason']}
        result = super().select(state)
        if result.get('route') in ('researcher', 'critic'):
            ws = self.backend.ws
            blocked = {r[0] for r in ws.db.execute('SELECT job FROM release_task_state')}
            jobs = ws.jobs('running')+ws.jobs('pending')
            drain = []
            for job in jobs:
                private = self.backend.root/'reviews'/job['ref']/'critic/private'
                checkpoint = private/'checkpoint.json'
                transport = private/'transport.json'
                cp = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
                http = json.loads(transport.read_text()) if transport.exists() else {}
                # Past payment alone is not an outstanding delivery. Actual
                # paid tool batches are drained even when a slice is blocked.
                if cp.get('pending') or http.get('delivery') or http.get('inflight'):
                    drain.append(job)
            ready = drain+[j for j in ws.delegated_jobs() if j['ref'] not in blocked and j['ref'] not in {d['ref'] for d in drain}]
            result.update(route='critic' if ready else 'researcher', job_ref=ready[0]['ref'] if ready else '')
        export_handoff(self.backend, result.get('status', 'running'), result.get('reason', 'safe turn checkpoint'))
        export_report(self.backend)
        return result

    def step(self, role, state):
        result = super().step(role, state)
        if (result.get('result', {}).get('execution_state') == 'blocked_execution'
                or result.get('result', {}).get('status') == 'stage_closed'):
            result.update(route='select', status='running')
            with self.connect() as db:
                db.execute('UPDATE operations SET result=? WHERE thread=? AND seq=?',
                           (encoded(result), self.thread_id, state['sequence']))
        return result

    def deliver(self, state):
        outcome = self.backend.ws.stage_outcome()
        if outcome:
            path = export_handoff(self.backend, 'stage_closed', outcome['reason'])
            export_report(self.backend)
            return {'status': 'stage_closed', 'reason': outcome['reason'],
                    'result': {'stage_outcome': outcome, 'formal_report': False, 'handoff': path}}
        result = super().deliver(state)
        export_report(self.backend)
        return result

    def invoke(self, *, resume=False):
        # Earlier reports may become obsolete after new, version-bound feedback.
        # Restart the selector with the same counters, never return a stale END.
        current = self.graph.get_state(self.config)
        if current.values.get('status') == 'stage_closed' and self.backend.ws.stage_outcome():
            return current.values
        if current.values.get('status') == 'completed' and not self.backend.ws.report():
            self.graph.update_state(self.config, {'status': 'running', 'reason': ''}, as_node='pause')
        result = super().invoke(resume=resume)
        export_report(self.backend)
        return result


@contextmanager
def open_graph(backend, *, thread_id, max_turns=80):
    with SqliteSaver.from_conn_string(str(backend.root/'graph_checkpoints.sqlite')) as saver:
        yield ResearchGraph(backend, saver, thread_id=thread_id, max_turns=max_turns)
