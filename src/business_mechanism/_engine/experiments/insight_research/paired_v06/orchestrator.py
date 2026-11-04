from ..common import Pending
from ..paired_v05.orchestrator import ResearchRun as PreviousRun,ResearchRuntime as PreviousRuntime
from ..paired_v01.budget import StudyJournal
from .references import recover_paid_submission
from .review import Reviewer,ReviewerRuntime

class ResearchRuntime(PreviousRuntime):
    def run(self,max_model_steps=8):
        recover_paid_submission(self,'review_claim')
        return super().run(max_model_steps)

class ResearchRun(PreviousRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)

    def run(self,owner_steps=80):
        if self.ws.settings['verification_mode']=='self':recover_paid_submission(self.runtime,'review_claim')
        return super().run(owner_steps)

    def review_job(self,job):
        if self.ws.job(job['ref'])['status']=='completed':return
        inputs=self.prepare_job(job)
        settings={'research_profile':'paired_critic_v1','model_config':self.model,
                  'limits':{**self.ws.settings['limits'],'max_http_attempts':job['review_http_limit']}}
        root=self.root/'reviews'/job['ref']/'critic'
        reviewer=Reviewer(root,inputs,settings,reopen=root.exists());reviewer.study_budget=self.budget
        try:
            journal=self.reviewer_journal_factory(reviewer,job) if self.reviewer_journal_factory else StudyJournal(reviewer,self.model,self.budget,'critic:'+job['ref'])
            with self.ws.db:self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?",(job['ref'],))
            result=ReviewerRuntime(reviewer,self.model,journal=journal).run(job['review_http_limit'])
            if result['status']!='completed':raise Pending('review job pending: '+result['reason'])
            self.import_feedback(job,reviewer)
        finally:reviewer.close()
