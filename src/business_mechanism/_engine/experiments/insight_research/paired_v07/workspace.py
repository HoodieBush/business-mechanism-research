from copy import deepcopy
from pathlib import Path
import uuid
from ..common import digest,encoded,sha
from ..paired_v06.workspace import ResearchWorkspace as Previous

class ResearchWorkspace(Previous):
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings)
        settings['paired_v07_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        self.workflow=settings.get('workflow_policy',{})
        super().__init__(root,question,world,settings,**kwargs)

    def unanswered(self,refs=None):
        answered={(b['review_ref'],b['issue_id']) for b in self.records('review_response')}
        pending=[]
        for q in self.records('review'):
            if q['phase']!='complete':continue
            for issue in q['issues']:
                if (q['ref'],issue['issue_id']) in answered:continue
                if refs is not None and not set(issue['affected_refs']).intersection(refs):continue
                pending.append({'review_ref':q['ref'],'issue_id':issue['issue_id'],'affected_refs':issue['affected_refs'],
                    'basis':issue['basis'],'blocking':issue['blocking'],'claim_impact':issue['claim_impact']})
        return pending

    def response_receipt(self):
        return {'review_response_refs':[b['ref'] for b in self.records('review_response')],
                'deferred_opinion_refs':[{'review_ref':b['review_ref'],'issue_id':b['issue_id'],'response_ref':b['ref']}
                    for b in self.records('review_response') if b['disposition']=='defer'],
                'response_scope':'Recorded evidence-linked dispositions, not scientific certification.'}

    def add(self,kind,body):
        if kind in ('report','report_draft'):body={**body,**self.response_receipt()}
        result=super().add(kind,body)
        if result['record_type']=='report_draft' and body.get('supersedes_draft_ref'):
            self._flag(body['supersedes_draft_ref'],'superseded','draft replaced by '+result['ref'],result['ref'])
        return result

    def enqueue(self,target,parent=None,*,parent_review=None,reason='New candidate claim'):
        item=self.record(target);version=digest(item)
        row=self.db.execute("SELECT ref FROM review_jobs WHERE target=? AND version=? AND status IN ('pending','running')",(target,version)).fetchone()
        if row:return row[0]
        previous=self.db.execute('SELECT episode,review_ref FROM review_jobs WHERE target=? ORDER BY rowid DESC LIMIT 1',(parent or target,)).fetchone()
        episode=previous[0] if previous else target
        if parent_review is None and previous:parent_review=previous[1]
        count=self.db.execute('SELECT count(*) FROM review_jobs WHERE episode=?',(episode,)).fetchone()[0]
        cap=self.workflow.get('max_lineage_reviews',4)
        if type(cap)is not int or not 2<=cap<=4:raise ValueError('registered lineage review bound must be between2and4')
        ref='J'+uuid.uuid4().hex[:16]
        self.db.execute('INSERT INTO review_jobs VALUES (?,?,?,?,?,?,?,?,?)',
            (ref,target,version,episode,count+1,'pending' if count<cap else 'exhausted',None,parent_review,reason))
        return ref

    def clearance(self,ref):
        return super().clearance(ref) and not self.unanswered({ref})

    def apply_review(self,job_ref,body,*,author,**kwargs):
        if author=='researcher_self_check' and self.unanswered():
            raise ValueError('respond to prior review opinions with evidence before the next self review')
        return super().apply_review(job_ref,body,author=author,**kwargs)

    def try_seal_report(self):
        if self.unanswered():return
        return super().try_seal_report()

    def _checked_dispatch(self,name,args,key):
        if name in ('finish_research','review_claim') and self.unanswered():
            raise ValueError(encoded({'error':'review opinions need explicit evidence-linked responses first','unanswered':self.unanswered(),
                'repair':'Use update_research_state.review_responses: review_ref,issue_id,disposition(accept/revise/rebut/defer),rationale,evidence_refs,replacement_refs. Checkpoints and evidence tools remain available. A reply does not certify the opinion or close a still-valid error.'}))
        return super()._checked_dispatch(name,args,key)

    def context(self):
        ctx=super().context()
        ctx['unanswered_review_opinions']=self.unanswered()
        ctx['feedback_workflow']='Before recheck/publication, explicitly accept/revise/rebut/defer every delivered issue with original evidence. You choose research direction; a checkpoint can retain pending claims. No opinion is a factual premise.'
        ctx['review_policy']='Each new version is reviewed; unchanged original calculations may be reused with exact refs/versions. Four reviews maximum per explicit lineage,18first/6later,within shared limits; no automatic scientific clearance.'
        return ctx
