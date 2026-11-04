"""Reuse the original event controller, budgets and persisted review jobs."""
from ..common import Pending
from ..paired_v01.orchestrator import ResearchRun as PreviousRun,ResearchRuntime as PreviousRuntime
from ..paired_v01.budget import StudyJournal
from .review import Reviewer,ReviewerRuntime


class ResearchRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial()
        messages[0]['content']+='\n自查优先用独立动作review_claim(job_ref,review)提交，不必同时重填研究状态。该动作仍由同一研究者、同一上下文完成。update_research_state继续用于认识、回应和记忆修订。存在待审任务时先针对当前目标核验，完成后继续自主研究；回读和复算始终可用。\n'
        return messages

    def constrained(self,payload):
        payload=super().constrained(payload)
        if self.cp.get('resource_closeout') and not any(t['function']['name']=='review_claim' for t in payload['tools']):
            payload['tools'].extend(t for t in self.ws.tool_schemas() if t['function']['name']=='review_claim')
        return payload

    def prepare_payload(self,payload):
        payload=super().prepare_payload(payload)
        if self.ws.settings['verification_mode']=='self':
            pending=self.ws.jobs('pending')+self.ws.jobs('running')
            if pending:
                job=pending[0]
                start=self.ws.db.execute('SELECT start_attempt FROM self_review_clock WHERE job_ref=?',(job['ref'],)).fetchone()
                attempts=self.journal.state['attempts'] if isinstance(self.journal,StudyJournal) else self.cp['responses']
                left=job['review_http_limit']-(attempts-start[0]) if start else job['review_http_limit']
                payload['messages'].append({'role':'user','content':
                    f"当前待审任务{job['ref']}，对象{job['target_ref']}；本项核验还可请求{left}次，含接下来这次。请用review_claim提交已做核验及未查范围；不是重写整份研究状态，也不要求支持结论。"})
        return payload


class ResearchRun(PreviousRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)

    def review_job(self,job):
        inputs=self.prepare_job(job)
        settings={'research_profile':'paired_critic_v1','model_config':self.model,
            'limits':{**self.ws.settings['limits'],'max_http_attempts':job['review_http_limit']}}
        root=self.root/'reviews'/job['ref']/'critic'
        reviewer=Reviewer(root,inputs,settings,reopen=root.exists());reviewer.study_budget=self.budget
        try:
            journal=self.reviewer_journal_factory(reviewer,job) if self.reviewer_journal_factory else StudyJournal(
                reviewer,self.model,self.budget,'critic:'+job['ref'])
            with self.ws.db:self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?",(job['ref'],))
            result=ReviewerRuntime(reviewer,self.model,journal=journal).run(job['review_http_limit'])
            if result['status']!='completed':raise Pending('review job pending: '+result['reason'])
            self.import_feedback(job,reviewer)
        finally:reviewer.close()
