import fcntl
from pathlib import Path
from ..common import Pending, encoded
from token_budget import reservation_bound
from ..paired_v13.orchestrator import ResearchRun as PreviousRun, ResearchRuntime as PreviousRuntime
from ..paired_v12.journal_memory import rebuild_from_owned_journal
from ..paired_v06.references import recover_paid_submission
from .guard import ProgressGuard


class ResearchRuntime(PreviousRuntime):
    def initial(self):
        context = self.ws.context()
        context['session_progress'] = {'responses_completed':self.cp['responses'],'continuing_same_research':self.cp['responses']>0}
        return [{'role':'system','content':(Path(__file__).parent/'researcher_prompt.txt').read_text()},
                {'role':'user','content':encoded(context)}]

    def compact(self):
        return rebuild_from_owned_journal(self)

    def prepare_payload(self,payload):
        remaining = self.journal.snapshot()['remaining_admission_tokens']
        maximum = self.ws.settings['limits']['max_request_bytes']
        if len(encoded(payload).encode())>maximum or reservation_bound(payload)>remaining:
            self.compact(); payload = self.payload()
        if len(encoded(payload).encode())>maximum or reservation_bound(payload)>remaining:
            raise Pending('complete bounded research request cannot fit remaining admission; exact originals and paid work retained')
        return payload


class ResearchRun(PreviousRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.guard = ProgressGuard(self.root,self.ws,self.budget)
        if hasattr(self.journal,'guard'):
            self.journal.guard = self.guard
        self.runtime = ResearchRuntime(self.ws,self.model,journal=self.journal)

    def run(self,owner_steps=160):
        lock = (self.root/'research_run.lock').open('a')
        try:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise Pending('research run is owned by another controller')
            recover_paid_submission(self.runtime,'review_claim')
            for _ in range(owner_steps):
                self.start_closeout()
                with self.ws.db:
                    self.ws.try_seal_report()
                self.ws._publish()
                if self.ws.report():
                    self.runtime.cp.update(status='completed',reason=None); self.runtime.save()
                    return {'status':'completed','report_ref':self.ws.report()['ref']}
                with self.budget.connect() as db:
                    paid = {r for r, in db.execute('SELECT DISTINCT role FROM attempts')}
                all_jobs = self.ws.jobs('running')+self.ws.jobs('pending')
                mode = self.ws.settings['verification_mode']
                paid_jobs = [j for j in all_jobs if mode=='independent' and 'critic:'+j['ref'] in paid]
                requested = self.ws.delegated_jobs()
                jobs = paid_jobs+[j for j in requested if j['ref'] not in {x['ref'] for x in paid_jobs}]
                if jobs:
                    job = jobs[0]
                    if mode=='independent':
                        self.review_job(job)
                        continue
                    attempts = self.journal.state['attempts'] if hasattr(self.journal,'state') else self.runtime.cp['responses']
                    with self.ws.db:
                        self.ws.db.execute('INSERT OR IGNORE INTO self_review_clock VALUES (?,?)',(job['ref'],attempts))
                    start = self.ws.db.execute('SELECT start_attempt FROM self_review_clock WHERE job_ref=?',(job['ref'],)).fetchone()[0]
                    if attempts-start >= job['review_http_limit']:
                        raise Pending('registered self review HTTP ceiling reached; preserve complete work')
                    self.prepare_job(job)
                # No pending-job auto-preemption. Every delivered feedback is
                # followed by an owner decision, including after all replies.
                result = self.runtime.run(1)
                if result['status']=='completed':
                    return result
                if result['reason']!='registered model-step slice reached; study can resume':
                    return result
            return {'status':'pending','reason':'registered controller slice reached; all costs and paid work retained'}
        except Pending as error:
            return {'status':'pending','reason':str(error)}
        finally:
            lock.close()
