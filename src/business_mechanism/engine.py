"""Version-bound release facade over the proven scientific/tool backend."""
from copy import deepcopy
from pathlib import Path
from experiments.insight_research.common import Pending, sha, digest
from experiments.insight_research.langgraph_release_v02.workspace import ResearchWorkspace as PreviousWorkspace
from experiments.insight_research.langgraph_release_v02.backend import ResearchBackend as PreviousBackend
from experiments.insight_research.prompt_runtime_v05.runtime import ResearchRuntime as PreviousResearchRuntime, ReviewerRuntime as PreviousReviewerRuntime
from experiments.insight_research.review_contract_v02.reviewer import Reviewer as CheckedReviewer
from .prompts import compose
from .context_window import compact as rebuild_context
from .workflow import EvidenceProgressGuard as ProgressGuard, review_contract, review_coverage, stage_outcome
from experiments.insight_research.common import write_json
from .data import SQLiteEnvironment
from .transport import ExecutionJournal
from .sandbox import restrict_worker
from .business_tools import BusinessTools, DurableToolsRuntime
from .allocations import review_allocation
from .method_coverage import coverage_report
from . import convergence
import json


def source_identity():
    here = Path(__file__).parent
    return {p.name: sha(p) for p in sorted(here.glob('*.py'))}


class ResearchWorkspace(BusinessTools, PreviousWorkspace):
    def jobs(self, status=None):
        jobs = super().jobs(status)
        if getattr(self, '_sealing_current_stage', False) and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='release_task_state'").fetchone():
            blocked = {r[0] for r in self.db.execute('SELECT job FROM release_task_state')}
            jobs = [j for j in jobs if j['ref'] not in blocked]
        return jobs

    def unanswered(self, refs=None):
        if refs is None and self.stage_marker():
            refs = {ref for ref, in self.db.execute("SELECT ref FROM records WHERE rowid>? AND kind IN ('hypothesis','plan','result','assessment','knowledge','state','report_draft','review_response')", (self.stage_marker(),))}
        if refs is None and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='release_hypotheses'").fetchone():
            active = convergence.active_refs(self)
            refs = active | {r['ref'] for kind in ('hypothesis','plan','result','assessment','knowledge','state','report_draft','review_response')
                    for r in self.records(kind) if set(self.target_hypotheses(r['ref'])) & active}
        return super().unanswered(refs)

    def stage_outcome(self):
        return stage_outcome(self)

    def enqueue(self, target, parent=None, *, parent_review=None, reason='New candidate claim'):
        # Refuse before inserting another exhausted episode. Historical rows
        # remain untouched; new work needs a real new scientific version.
        active = self.db.execute("SELECT ref FROM review_jobs WHERE target=? AND version=? AND status IN ('pending','running')",
                                 (target, digest(self.record(target)))).fetchone()
        if active: return active[0]
        previous = self.db.execute('SELECT episode FROM review_jobs WHERE target=? ORDER BY rowid DESC LIMIT 1',
                                   (parent or target,)).fetchone()
        if previous:
            count = self.db.execute('SELECT count(*) FROM review_jobs WHERE episode=?', (previous[0],)).fetchone()[0]
            if count >= self.workflow.get('max_lineage_reviews', 4):
                raise ValueError('review_lineage_exhausted: preserve current target and feedback; close_research_stage unresolved or conduct new research instead of resubmitting the report')
        return super().enqueue(target, parent, parent_review=parent_review, reason=reason)

    def apply_review(self, job_ref, body, *, author, **kwargs):
        coverage = getattr(self, '_incoming_coverage', {}).get(job_ref)
        if coverage is None:
            coverage = coverage_report([], lambda ref: None)
        result = super().apply_review(job_ref, {**body, 'method_coverage': coverage}, author=author, **kwargs)
        if body['phase'] == 'complete' and not coverage['clearance_eligible']:
            self.db.execute('DELETE FROM clearances WHERE target=?', (self.job(job_ref)['target_ref'],))
        return result

    def delegated_jobs(self):
        jobs = super().delegated_jobs()
        # This method is also called during historical initialization.
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='release_task_state'").fetchone():
            return jobs
        blocked = {r[0] for r in self.db.execute('SELECT job FROM release_task_state')}
        return [j for j in jobs if j['ref'] not in blocked]

    def add(self,kind,body):
        if kind=='review' and body.get('job_ref'):
            provenance=[]
            refs={c['action_ref'] for c in body.get('checks_performed',[])}
            refs.update(r for i in body.get('issues',[]) for r in i.get('action_refs',[]))
            for ref in sorted(refs):
                if not ref.startswith('C'):continue
                item=self.record(ref,'review_action')
                if item['job_ref']!=body['job_ref']:
                    provenance.append({'source_action_ref':ref,'source_action_version':digest(item),
                        'origin_job_ref':item['job_ref'],'origin_tool':item['operation']['tool'],
                        'kind':'reused_prior_tool_output','new_computation_in_this_review':False,'scientific_certification':False})
            if provenance:body={**body,'reused_check_provenance':provenance}
        return super().add(kind,body)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        restrict_worker(self)
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS release_stages(stage INTEGER PRIMARY KEY,marker INTEGER,previous_report TEXT,created TEXT)')
            self.db.execute("INSERT OR IGNORE INTO release_stages VALUES (1,0,NULL,'initial')")

    def stage_marker(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='release_stage_marker'").fetchone()
        return int(row[0]) if row else 0

    def after_marker(self, ref):
        row = self.db.execute('SELECT rowid FROM records WHERE ref=?', (ref,)).fetchone()
        return bool(row and row[0] > self.stage_marker())

    def report(self):
        report = super().report()
        return report if report and self.after_marker(report['ref']) else None

    def try_seal_report(self):
        drafts = self.records('report_draft')
        if drafts and not self.after_marker(drafts[-1]['ref']):
            return
        self._sealing_current_stage = True
        try:
            result = super().try_seal_report()
            report = self.report()
            if report:
                from .verification_tasks import record_delivery
                for ref in report.get('assessment_refs', []):
                    a = self.record(ref, 'assessment'); h = convergence.get(self, a['hypothesis_ref'])
                    if h['status'] in ('active', 'backlog') and self.clearance(ref):
                        outcome = {'supported':'accepted_in_scope','refuted':'refuted'}.get(a['status'],'inconclusive')
                        convergence.close(self, {'hypothesis_ref':a['hypothesis_ref'],'outcome':outcome,
                            'reason':'Scoped assessment included in the independently reviewed formal stage report '+report['ref'],
                            'assessment_ref':ref,'evidence_refs':a['result_refs'],'successor_ref':None},
                            'formal-report:'+report['ref']+':'+ref,actor='publication_controller')
                record_delivery(self,report)
            return result
        finally:
            self._sealing_current_stage = False

    def context(self):
        context = super().context()
        context['release_stage'] = {'marker': self.stage_marker(),
            'earlier_reports': [r['ref'] for r in self.records('report') if not self.after_marker(r['ref'])],
            'policy': 'Keep prior evidence and memory. Finish active hypothesis goals/review repairs before new branches. An execution stage handoff is not a hypothesis endpoint. Reused computations are not new samples; a valid scoped review or negative endpoint is useful completion, not re-publication of old prose.'}
        if isinstance(self.environment, SQLiteEnvironment):
            context['environment_capabilities'] = 'Read-only supplied business SQLite. Observational formal tests and independent recomputation are available; no new physical measurement or intervention is installed.'
            context['stage_scope'] = 'Business mechanism research on the supplied data; state association, causal limitations and applicability explicitly.'
        return context


class SQLiteWorkspace(ResearchWorkspace):
    environment_class = SQLiteEnvironment


class Reviewer(BusinessTools, CheckedReviewer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        restrict_worker(self)


class ErrorDeliveryRecovery:
    def run(self,*args,**kwargs):
        delivery=self.journal.state.get('delivery')
        if delivery:
            attempt=delivery['attempt']
            receipt=self.ws.private/'http'/f'{attempt}.json'
            if receipt.exists():
                record=json.loads(receipt.read_text())
                if not (record.get('response') or {}).get('choices'):
                    # The error receipt and all charges are durable. Recover
                    # the gap before native ack, exactly once across restarts.
                    if self.cp.get('error_delivery_acknowledged_attempt',0)<attempt:
                        self.cp['transport_failures']+=1
                        self.cp['error_delivery_acknowledged_attempt']=attempt
                        self.save()
                    self.journal.ack()
        return super().run(*args,**kwargs)


class ResearchRuntime(DurableToolsRuntime,ErrorDeliveryRecovery,PreviousResearchRuntime):
    def initial(self):
        messages = super().initial(); messages[0]['content'] = compose('researcher')
        return messages

    def compact(self):
        return rebuild_context(self)


class ReviewerRuntime(DurableToolsRuntime,ErrorDeliveryRecovery,PreviousReviewerRuntime):
    def initial(self):
        messages = super().initial(); messages[0]['content'] = compose('critic')
        return messages

    def compact(self):
        return rebuild_context(self)


class Backend(PreviousBackend):
    def prepare_job(self, job):
        inputs = super().prepare_job(job)
        packet = json.loads((inputs/'packet.json').read_text())
        if 'release_review_contract' in packet:
            return inputs
        if (inputs.parent/'critic/private/identity.json').exists():
            return inputs  # Frozen legacy projection; never rewrite consumed input.
        packet['release_review_contract'] = review_contract(self.ws, job['target_ref'])
        write_json(inputs/'packet.json', packet)
        manifest = json.loads((inputs/'manifest.json').read_text())
        manifest['files_sha256']['packet.json'] = sha(inputs/'packet.json')
        write_json(inputs/'manifest.json', manifest)
        with self.ws.db:
            self.ws.db.execute('UPDATE review_inputs SET manifest_sha=? WHERE job_ref=?', (sha(inputs/'manifest.json'), job['ref']))
        return inputs

    def import_feedback(self, job, reviewer):
        original = reviewer.report()
        coverage = review_coverage(reviewer, original or {})
        self.ws._incoming_coverage = {job['ref']: {**coverage, 'origin_job_ref': job['ref']}}
        try:
            result=super().import_feedback(job, reviewer)
            from .verification_tasks import record_verified_endpoint
            with self.ws.db:record_verified_endpoint(self.ws,job)
            return result
        finally:
            self.ws._incoming_coverage = {}

    def __init__(self, root, workspace, model, execution_budget):
        if workspace.settings.get('release_sources') != source_identity():
            raise ValueError('Release source identity changed; use the pinned version to resume.')
        self.root = Path(root).resolve()
        self.ws, self.model, self.budget = workspace, model, execution_budget
        self.reserve = workspace.settings['execution_policy']['closeout_reserve_tokens']
        workspace.study_budget = execution_budget
        self.guard = ProgressGuard(self.root, workspace, execution_budget)
        self.journal = ExecutionJournal(workspace, model, execution_budget, 'researcher', memory=True, guard=self.guard)
        self.runtime = ResearchRuntime(workspace, model, journal=self.journal)

    def critic_step(self, job, model_steps=1):
        if self.ws.job(job['ref'])['status'] == 'completed':
            return {'status': 'completed', 'job_ref': job['ref']}
        readiness = review_contract(self.ws, job['target_ref'])
        if not readiness['ready']:
            with self.ws.db:
                self.ws.db.execute('INSERT OR REPLACE INTO release_task_state VALUES (?,?,?)',
                    (job['ref'], 'blocked_execution', 'review_not_ready: register the missing analysis spec before paid review'))
            return {'status': 'pending', 'execution_state': 'blocked_execution', 'contract': readiness,
                    'reason': 'review_not_ready: missing analysis spec; no model request sent'}
        inputs = self.prepare_job(job)
        allocation = review_allocation(self.ws, self.budget, job['ref'])
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.model,
                    'limits': {**self.ws.settings['limits']},
                    'release_sources': source_identity()}
        root = self.root/'reviews'/job['ref']/'critic'
        peer = Reviewer(root, inputs, settings, reopen=root.exists())
        peer.study_budget = self.budget
        peer.review_allocation = allocation
        try:
            journal = ExecutionJournal(peer, self.model, self.budget, 'critic:'+job['ref'], memory=False, guard=self.guard)
            with self.ws.db:
                self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?", (job['ref'],))
            result = ReviewerRuntime(peer, self.model, journal=journal).run(model_steps)
            if result['status'] == 'completed':
                self.import_feedback(job, peer)
                with self.ws.db:
                    self.ws.db.execute('DELETE FROM release_task_state WHERE job=?', (job['ref'],))
            elif 'review_execution_blocked:' in result.get('reason', ''):
                with self.ws.db:
                    self.ws.db.execute('INSERT OR REPLACE INTO release_task_state VALUES (?,?,?)',
                        (job['ref'], 'blocked_execution', result['reason']))
                result = {**result, 'execution_state': 'blocked_execution', 'job_ref': job['ref'],
                          'scientific_status_changed': False}
            return result
        finally:
            peer.close()
