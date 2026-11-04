from ..common import Pending
from ..paired_v07.orchestrator import BaselineRun as OldBaseline,ResearchRun as OldCandidate
from .review import Reviewer,ReviewerRuntime

class ReviewExecution:
    def review_job(self,job):
        if self.ws.job(job['ref'])['status']=='completed':return
        inputs=self.prepare_job(job)
        settings={'research_profile':'paired_critic_v1','model_config':self.model,'limits':{**self.ws.settings['limits'],'max_http_attempts':18}}
        root=self.root/'reviews'/job['ref']/'critic';peer=Reviewer(root,inputs,settings,reopen=root.exists());peer.study_budget=self.budget
        try:
            journal=self.reviewer_journal_factory(peer,job)
            with self.ws.db:self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?",(job['ref'],))
            result=ReviewerRuntime(peer,self.model,journal=journal).run(18)
            if result['status']!='completed':raise Pending('review job pending: '+result['reason'])
            self.import_feedback(job,peer)
        finally:peer.close()

class BaselineRun(ReviewExecution,OldBaseline):
    pass

class ResearchRun(ReviewExecution,OldCandidate):
    pass
