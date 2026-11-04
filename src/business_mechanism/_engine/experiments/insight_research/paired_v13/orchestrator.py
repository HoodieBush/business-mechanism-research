from ..common import Pending
from ..paired_v12.orchestrator import ResearchRun as PreviousRun,ResearchRuntime as PreviousRuntime
from .context import compact_with_admission
from .review import Reviewer,ReviewerRuntime

class ResearchRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial();messages[0]['content']+='\n上下文若已从自己的完整档案重建，own_journal_memory提供精确归档及own_log/own_process入口。它不是自动科学总结；先结合原假说、结果、审查和近期完整回合恢复当前问题，必要时分页回读自己档案。日志/私人推理不能当事实证据，不必重做已完成计算。'
        return messages
    def compact(self):
        return compact_with_admission(self,super().compact)

class ResearchRun(PreviousRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)
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
