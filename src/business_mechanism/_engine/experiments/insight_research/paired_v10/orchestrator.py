from ..paired_v09.orchestrator import ResearchRun as Previous
from ..paired_v09.review import ReviewerRuntime
from ..paired_v08.review import Reviewer
from ..common import Pending
from ..paired_v07.orchestrator import ResearchRuntime as PreviousRuntime

class ResearchRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial()
        messages[0]['content']+='\n可用respond_to_review单独保存一条逐意见处置，不必重写当前研究认识。search_memory可明确选择review/review_response。record_assessment.result_refs只收对应原假说的正式R；file、event、Q不是R。实际核验额度由同一登记策略生成，具体额度看当前context.review_policy和剩余提示，原旧6次提示不适用。'
        return messages

class ResearchRun(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)

    def review_job(self,job):
        if self.ws.job(job['ref'])['status']=='completed':return
        inputs=self.prepare_job(job);limit=self.ws.job(job['ref'])['review_http_limit']
        settings={'research_profile':'paired_critic_v1','model_config':self.model,'limits':{**self.ws.settings['limits'],'max_http_attempts':limit}}
        root=self.root/'reviews'/job['ref']/'critic';peer=Reviewer(root,inputs,settings,reopen=root.exists());peer.study_budget=self.budget
        try:
            journal=self.reviewer_journal_factory(peer,job)
            with self.ws.db:self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?",(job['ref'],))
            result=ReviewerRuntime(peer,self.model,journal=journal).run(limit)
            if result['status']!='completed':raise Pending('review job pending: '+result['reason'])
            self.import_feedback(job,peer)
        finally:peer.close()
