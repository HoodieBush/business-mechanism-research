import fcntl
from ..common import Pending
from ..paired_v06.references import recover_paid_submission
from ..paired_v07.orchestrator import BaselineRun as OldBaseline,ResearchRun as OldCandidate
from ..paired_v08.review import Reviewer
from .review import ReviewerRuntime

class ReviewExecution:
    def run(self,owner_steps=160):
        lock=(self.root/'research_run.lock').open('a')
        try:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Pending('research run is owned by another controller')
            recover_paid_submission(self.runtime,'review_claim')
            for _ in range(owner_steps):
                with self.ws.db:self.ws.try_seal_report()
                self.ws._publish()
                if self.ws.report():
                    self.runtime.cp.update(status='completed',reason=None);self.runtime.save()
                    return {'status':'completed','report_ref':self.ws.report()['ref']}
                jobs=self.ws.jobs('running')+self.ws.jobs('pending')
                with self.budget.connect() as db:
                    paid={r for r, in db.execute('SELECT DISTINCT role FROM attempts')}
                mode=self.ws.settings['verification_mode']
                paid_jobs=[j for j in jobs if mode=='independent' and 'critic:'+j['ref'] in paid]
                jobs=paid_jobs+[j for j in jobs if j not in paid_jobs]
                unanswered=self.ws.unanswered() if hasattr(self.ws,'unanswered') else []
                if jobs and (paid_jobs or not unanswered):
                    if mode=='independent':self.review_job(jobs[0]);continue
                    job=jobs[0];attempts=self.journal.state['attempts'] if hasattr(self.journal,'state') else self.runtime.cp['responses']
                    with self.ws.db:self.ws.db.execute('INSERT OR IGNORE INTO self_review_clock VALUES (?,?)',(job['ref'],attempts))
                    start=self.ws.db.execute('SELECT start_attempt FROM self_review_clock WHERE job_ref=?',(job['ref'],)).fetchone()[0]
                    if attempts-start>=job['review_http_limit']:raise Pending('registered self review HTTP ceiling reached; retain complete work')
                    for job in jobs:self.prepare_job(job)
                result=self.runtime.run(1)
                if result['status']=='completed':return result
                if result['reason']!='registered model-step slice reached; study can resume':return result
            return {'status':'pending','reason':'registered controller slice reached; counters and paid work retained'}
        except Pending as error:return {'status':'pending','reason':str(error)}
        finally:lock.close()

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
