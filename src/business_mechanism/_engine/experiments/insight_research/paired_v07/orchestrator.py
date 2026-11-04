import fcntl,json
from pathlib import Path
from ..common import Pending,sha,write_json,digest
from ..paired_v06.orchestrator import ResearchRun as PreviousRun,ResearchRuntime as PreviousRuntime
from ..paired_v06.review import Reviewer,ReviewerRuntime
from ..paired_v06.references import recover_paid_submission
from .guard import ProgressGuard,GuardedJournal

class BaselineRun(PreviousRun):
    """Unmodified v06 research logic, with the same external resource protection."""
    def __init__(self,root,workspace,model,study_budget,*,owner_journal=None,reviewer_journal_factory=None):
        root=Path(root).resolve();self.guard=ProgressGuard(root,workspace,study_budget)
        journal=owner_journal or GuardedJournal(workspace,model,study_budget,'researcher',memory=True,guard=self.guard)
        factory=reviewer_journal_factory or (lambda peer,job:GuardedJournal(peer,model,study_budget,'critic:'+job['ref'],guard=self.guard))
        super().__init__(root,workspace,model,study_budget,owner_journal=journal,reviewer_journal_factory=factory)

class ResearchRuntime(PreviousRuntime):
    def initial(self):
        messages=super().initial()
        messages[0]['content']+='\n收到每条审查意见后，用update_research_state.review_responses逐条登记接受/修订/反驳/保留争议、理由和原始证据。可先保存新判断，随后回应，再启动复审。defer是合法的诚实未决；意见不是事实，不需要机械接受。最终交付前须回应所有已交付意见。审查包给出变更和既有计算入口，必要回读仍可用；数值或适用范围改变必须重新核验。'
        return messages

class ResearchRun(BaselineRun):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.runtime=ResearchRuntime(self.ws,self.model,journal=self.journal)

    def prepare_job(self,job):
        inputs=super().prepare_job(job)
        packet=json.loads((inputs/'packet.json').read_text())
        if 'workflow_delta' in packet:return inputs
        if (inputs.parent/'critic/private/identity.json').exists():raise Pending('cannot modify an already consumed review projection')
        target=self.ws.record(job['target_ref']);parent_ref=target.get('supersedes_assessment_ref') or target.get('supersedes_ref') or target.get('supersedes_draft_ref')
        parent=self.ws.record(parent_ref) if parent_ref else None
        metadata={'ref','created_at','author'}
        changed=sorted(k for k in set(target)|set(parent or {}) if k not in metadata and (parent or {}).get(k)!=target.get(k))
        reviewed=[]
        refs=target.get('assessment_refs',[])+([parent_ref] if parent_ref else [])
        for ref in dict.fromkeys(refs):
            item=self.ws.record(ref);row=self.ws.db.execute('SELECT version,review_ref FROM clearances WHERE target=?',(ref,)).fetchone()
            reviewed.append({'ref':ref,'version':digest(item),'prior_review_ref':row[1] if row and row[0]==digest(item) else None,
                'eligible_current':self.ws.clearance(ref),'evidence_refs':item.get('result_refs',item.get('evidence_refs',[]))})
        packet['workflow_delta']={'target_ref':job['target_ref'],'target_version':job['target_version'],'previous_object_ref':parent_ref,
            'previous_object_version':digest(parent) if parent else None,'changed_fields':changed,'prior_material':reviewed,
            'instruction':'Focus on changed claims, prior issue responses and original computation artifacts. Existing computations may be reused only for unchanged inputs/scope. A prior opinion is not factual evidence or a new sample. Full archive remains available; every new object still needs its own review.'}
        write_json(inputs/'packet.json',packet)
        manifest=json.loads((inputs/'manifest.json').read_text());manifest['files_sha256']['packet.json']=sha(inputs/'packet.json');write_json(inputs/'manifest.json',manifest)
        with self.ws.db:self.ws.db.execute('UPDATE review_inputs SET manifest_sha=? WHERE job_ref=?',(sha(inputs/'manifest.json'),job['ref']))
        return inputs

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
                pending=self.ws.jobs('pending')+self.ws.jobs('running')
                unanswered=self.ws.unanswered()
                if pending and not unanswered:
                    if self.ws.settings['verification_mode']=='independent':self.review_job(pending[0]);continue
                    job=pending[0];attempts=self.journal.state['attempts'] if hasattr(self.journal,'state') else self.runtime.cp['responses']
                    with self.ws.db:self.ws.db.execute('INSERT OR IGNORE INTO self_review_clock VALUES (?,?)',(job['ref'],attempts))
                    start=self.ws.db.execute('SELECT start_attempt FROM self_review_clock WHERE job_ref=?',(job['ref'],)).fetchone()[0]
                    if attempts-start>=job['review_http_limit']:raise Pending('registered self review HTTP ceiling reached; retain complete work')
                    for job in pending:self.prepare_job(job)
                # Feedback gets an owner turn before a recheck. Evidence and checkpoints stay available.
                result=self.runtime.run(1)
                if result['status']=='completed':return result
                if result['reason']!='registered model-step slice reached; study can resume':return result
            return {'status':'pending','reason':'registered controller slice reached; counters and paid work retained'}
        except Pending as error:return {'status':'pending','reason':str(error)}
        finally:lock.close()
