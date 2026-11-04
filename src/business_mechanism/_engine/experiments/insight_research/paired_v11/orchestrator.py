import fcntl
from ..common import Pending
from ..paired_v06.references import recover_paid_submission
from ..paired_v10.orchestrator import ResearchRun as Previous,ResearchRuntime as PreviousRuntime
from .review import Reviewer,ReviewerRuntime

class ResearchRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial();messages[0]['content']+='\n用inspect_evidence复核已见数据，可显式选择商品、点位组和商品效应差，按实际聚类数和自由度计算。辅助文件放supporting_artifact_refs；原反证条款可逐项component_adjudications，主数值门禁不代表整个机制。错误对象需实际版本修订或撤回；回应可用object_reviews，不能只改摘要。进入stage_closeout后先保存、回应、交付有限认识；允许明确暂缓未启动的判断核验并隔离对象，不能发表它为已支持事实。原件/全部结果/未决仍披露，报告仍需核验。'
        return messages

class ResearchRun(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)
        self.reserve=self.ws.settings.get('execution_policy',{}).get('closeout_reserve_tokens',1300000)
        if type(self.reserve)is not int or not 0<self.reserve<self.budget.identity['token_allowance']:raise ValueError('registered positive closeout reserve below local total required')

    def start_closeout(self):
        snap=self.budget.snapshot()
        if snap['remaining_tokens']<=self.reserve or snap['remaining_http_attempts']<=24:
            with self.budget.connect() as db:db.execute("INSERT OR IGNORE INTO flags VALUES ('stage_closeout',?)",('Registered finite-stage reserve reached; preserve evidence and deliver or honestly pause.',))

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

    def run(self,owner_steps=160):
        lock=(self.root/'research_run.lock').open('a')
        try:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Pending('research run is owned by another controller')
            recover_paid_submission(self.runtime,'review_claim')
            for _ in range(owner_steps):
                self.start_closeout()
                with self.ws.db:self.ws.try_seal_report()
                self.ws._publish()
                if self.ws.report():
                    self.runtime.cp.update(status='completed',reason=None);self.runtime.save()
                    return {'status':'completed','report_ref':self.ws.report()['ref']}
                jobs=self.ws.jobs('running')+self.ws.jobs('pending')
                with self.budget.connect() as db:
                    paid={r for r, in db.execute('SELECT DISTINCT role FROM attempts')}
                    chosen=db.execute("SELECT 1 FROM flags WHERE key='closeout_owner_choice'").fetchone()
                mode=self.ws.settings['verification_mode'];paid_jobs=[j for j in jobs if mode=='independent' and 'critic:'+j['ref'] in paid]
                jobs=paid_jobs+[j for j in jobs if j not in paid_jobs]
                choose=bool(self.ws.closeout() and not chosen and not paid_jobs)
                if choose:
                    with self.budget.connect() as db:db.execute("INSERT OR IGNORE INTO flags VALUES ('closeout_owner_choice','one persisted owner decision opportunity')")
                if jobs and not choose and (paid_jobs or not self.ws.unanswered()):
                    if mode=='independent':self.review_job(jobs[0]);continue
                    job=jobs[0];attempts=self.journal.state['attempts'] if hasattr(self.journal,'state') else self.runtime.cp['responses']
                    with self.ws.db:self.ws.db.execute('INSERT OR IGNORE INTO self_review_clock VALUES (?,?)',(job['ref'],attempts))
                    start=self.ws.db.execute('SELECT start_attempt FROM self_review_clock WHERE job_ref=?',(job['ref'],)).fetchone()[0]
                    if attempts-start>=job['review_http_limit']:raise Pending('registered self review HTTP ceiling reached; retain complete work')
                    for job in jobs:self.prepare_job(job)
                result=self.runtime.run(1)
                if result['status']=='completed':return result
                if result['reason']!='registered model-step slice reached; study can resume':return result
            return {'status':'pending','reason':'registered controller slice reached; costs and paid work retained'}
        except Pending as error:return {'status':'pending','reason':str(error)}
        finally:lock.close()
