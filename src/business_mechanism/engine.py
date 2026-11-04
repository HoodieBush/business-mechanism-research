"""Version-bound release facade over the proven scientific/tool backend."""
from copy import deepcopy
from pathlib import Path
from experiments.insight_research.common import Pending, sha, digest
from experiments.insight_research.langgraph_release_v02.workspace import ResearchWorkspace as PreviousWorkspace
from experiments.insight_research.langgraph_release_v02.backend import ResearchBackend as PreviousBackend
from experiments.insight_research.prompt_runtime_v05.runtime import ResearchRuntime as PreviousResearchRuntime, ReviewerRuntime as PreviousReviewerRuntime
from experiments.insight_research.review_contract_v02.reviewer import Reviewer as CheckedReviewer
from .prompts import compose
from experiments.insight_research.paired_v12.journal_memory import rebuild_from_owned_journal
from experiments.insight_research.paired_v16.guard import ProgressGuard
from .data import SQLiteEnvironment
from .transport import ExecutionJournal
from .sandbox import restrict_worker
import json


def source_identity():
    here = Path(__file__).parent
    return {p.name: sha(p) for p in sorted(here.glob('*.py'))}


class ResearchWorkspace(PreviousWorkspace):
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
        return super().try_seal_report()

    def context(self):
        context = super().context()
        context['release_stage'] = {'marker': self.stage_marker(),
            'earlier_reports': [r['ref'] for r in self.records('report') if not self.after_marker(r['ref'])],
            'policy': 'Keep prior evidence and memory. Decide the next worthwhile question yourself. A new stage requires new research work, not re-publication of the old draft. An unresolved or negative finding is legitimate.'}
        if isinstance(self.environment, SQLiteEnvironment):
            context['environment_capabilities'] = 'Read-only supplied business SQLite. Observational formal tests and independent recomputation are available; no new physical measurement or intervention is installed.'
            context['stage_scope'] = 'Business mechanism research on the supplied data; state association, causal limitations and applicability explicitly.'
        return context


class SQLiteWorkspace(ResearchWorkspace):
    environment_class = SQLiteEnvironment


class Reviewer(CheckedReviewer):
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


class ResearchRuntime(ErrorDeliveryRecovery,PreviousResearchRuntime):
    def initial(self):
        messages = super().initial(); messages[0]['content'] = compose('researcher')
        return messages

    def compact(self):
        return rebuild_from_owned_journal(self)


class ReviewerRuntime(ErrorDeliveryRecovery,PreviousReviewerRuntime):
    def initial(self):
        messages = super().initial(); messages[0]['content'] = compose('critic')
        return messages

    def compact(self):
        return rebuild_from_owned_journal(self)


class Backend(PreviousBackend):
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
        inputs = self.prepare_job(job)
        limit = self.ws.job(job['ref'])['review_http_limit']
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.model,
                    'limits': {**self.ws.settings['limits'], 'max_http_attempts': limit},
                    'release_sources': source_identity()}
        root = self.root/'reviews'/job['ref']/'critic'
        peer = Reviewer(root, inputs, settings, reopen=root.exists())
        peer.study_budget = self.budget
        try:
            journal = ExecutionJournal(peer, self.model, self.budget, 'critic:'+job['ref'], memory=False, guard=self.guard)
            with self.ws.db:
                self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?", (job['ref'],))
            result = ReviewerRuntime(peer, self.model, journal=journal).run(model_steps)
            if result['status'] == 'completed':
                self.import_feedback(job, peer)
            return result
        finally:
            peer.close()
