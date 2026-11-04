"""Versioned complete prompts, existing native research tools and guarded transport."""
from ..common import Pending
from ..cost_context_v01.runtime import ContextStudyJournal, ResearchRuntime as LayoutRuntime
from ..growth_probe_v10.orchestrator import ResearchRun as PreviousRun
from ..paired_v07.guard import GuardedJournal
from ..paired_v13.review import ReviewerRuntime as PreviousReviewerRuntime
from .review import Reviewer
from ..paired_v16.guard import ProgressGuard
from .prompts import compose, source_identity


class GuardedContextJournal(ContextStudyJournal, GuardedJournal):
    """Retain the exact layout archive while every new call passes admission."""
    pass


class ResearchRuntime(LayoutRuntime):
    def initial(self):
        messages = super().initial()
        messages[0]['content'] = compose('researcher')
        return messages


class ReviewerRuntime(PreviousReviewerRuntime):
    def initial(self):
        messages = super().initial()
        messages[0]['content'] = compose('critic')
        return messages


class ResearchRun(PreviousRun):
    def __init__(self, root, workspace, model, study_budget, **kwargs):
        if workspace.settings['verification_mode'] != 'independent':
            raise ValueError('this candidate is the dual-agent release path')
        if workspace.settings.get('prompt_runtime_sources') != source_identity():
            raise ValueError('bind the exact complete prompt package in the new workspace identity')
        if kwargs:
            raise ValueError('candidate supplies explicit researcher and critic journals')
        self.guard = ProgressGuard(root, workspace, study_budget)
        journal = GuardedContextJournal(workspace, model, study_budget, 'researcher',
                                        memory=True, guard=self.guard)
        factory = lambda peer, job: GuardedJournal(peer, model, study_budget, 'critic:'+job['ref'],
                                                   memory=False, guard=self.guard)
        super().__init__(root, workspace, model, study_budget,
                         owner_journal=journal, reviewer_journal_factory=factory)
        self.runtime = ResearchRuntime(workspace, model, journal=self.journal)

    def review_job(self, job):
        if self.ws.job(job['ref'])['status'] == 'completed':
            return
        inputs = self.prepare_job(job)
        limit = self.ws.job(job['ref'])['review_http_limit']
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.model,
                    'limits': {**self.ws.settings['limits'], 'max_http_attempts': limit},
                    'prompt_runtime_sources': source_identity()}
        root = self.root/'reviews'/job['ref']/'critic'
        peer = Reviewer(root, inputs, settings, reopen=root.exists())
        peer.study_budget = self.budget
        try:
            journal = self.reviewer_journal_factory(peer, job)
            with self.ws.db:
                self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?", (job['ref'],))
            result = ReviewerRuntime(peer, self.model, journal=journal).run(limit)
            if result['status'] != 'completed':
                raise Pending('review job pending: '+result['reason'])
            self.import_feedback(job, peer)
        finally:
            peer.close()
