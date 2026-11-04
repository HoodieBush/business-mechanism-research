"""One native paid model/tool turn per graph node; no LLM in DB transactions."""
from ..common import Pending
from ..prompt_runtime_v05.runtime import (
    ResearchRun as PreviousRun, ResearchRuntime as PreviousResearchRuntime,
    ReviewerRuntime as PreviousReviewerRuntime, GuardedContextJournal)
from ..prompt_runtime_v05.review import Reviewer
from ..paired_v07.guard import GuardedJournal
from .prompts import compose, source_identity
from .transport import Cooldown


class ResearchRuntime(PreviousResearchRuntime):
    def initial(self):
        messages = super().initial()
        messages[0]['content'] = compose('researcher')
        return messages


class ReviewerRuntime(PreviousReviewerRuntime):
    def initial(self):
        messages = super().initial()
        messages[0]['content'] = compose('critic')
        return messages


class OwnerJournal(Cooldown, GuardedContextJournal):
    pass


class CriticJournal(Cooldown, GuardedJournal):
    pass


class ResearchBackend(PreviousRun):
    def __init__(self, root, workspace, model, study_budget):
        if workspace.settings.get('langgraph_release_sources') != source_identity():
            raise ValueError('release sources differ from registered workspace identity')
        super().__init__(root, workspace, model, study_budget)
        self.journal = OwnerJournal(workspace, model, study_budget, 'researcher',
                                    memory=True, guard=self.guard)
        self.runtime = ResearchRuntime(workspace, model, journal=self.journal)

    def researcher_step(self):
        return self.runtime.run(1)

    def critic_step(self, job, model_steps=1):
        if self.ws.job(job['ref'])['status'] == 'completed':
            return {'status': 'completed', 'job_ref': job['ref']}
        inputs = self.prepare_job(job)
        limit = self.ws.job(job['ref'])['review_http_limit']
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.model,
                    'limits': {**self.ws.settings['limits'], 'max_http_attempts': limit},
                    'prompt_runtime_sources': self.ws.settings['prompt_runtime_sources'],
                    'langgraph_release_sources': source_identity()}
        root = self.root/'reviews'/job['ref']/'critic'
        peer = Reviewer(root, inputs, settings, reopen=root.exists())
        peer.study_budget = self.budget
        try:
            journal = CriticJournal(peer, self.model, self.budget, 'critic:'+job['ref'],
                                    memory=False, guard=self.guard)
            with self.ws.db:
                self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?", (job['ref'],))
            result = ReviewerRuntime(peer, self.model, journal=journal).run(model_steps)
            if result['status'] == 'completed':
                self.import_feedback(job, peer)
            return result
        finally:
            peer.close()
