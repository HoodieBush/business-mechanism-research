"""Owner chooses review timing; publication and immutable evidence remain guarded."""
import json
from copy import deepcopy
from pathlib import Path
from ..common import digest, encoded, sha
from ..critic_v01.shared import lifecycle
from ..paired_v13.workspace import ResearchWorkspace as Previous
from ..paired_v10.workspace import ResearchWorkspace as BeforeScopedGuard
from .contracts import TOOLS, schemas
from .context_view import build, read_index


class ResearchWorkspace(Previous):
    tools = TOOLS

    def __init__(self,root,question,world,settings,**kwargs):
        settings = deepcopy(settings)
        settings['paired_v16_sources'] = {p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        self.delegations_ready = False
        super().__init__(root,question,world,settings,**kwargs)
        self.db.execute('CREATE TABLE IF NOT EXISTS review_delegations(job_ref TEXT PRIMARY KEY,request_ref TEXT,version TEXT)')
        self.delegations_ready = True
        with self.db:
            for item in self.records('review_note'):
                if item.get('review_delegation'):
                    self._index_delegation(item)

    def tool_schemas(self):
        return schemas(TOOLS)

    def _index_delegation(self,item):
        d = item['review_delegation']
        self.db.execute('INSERT OR IGNORE INTO review_delegations VALUES (?,?,?)',(d['job_ref'],item['ref'],d['target_version']))

    def _index_review(self,item):
        super()._index_review(item)
        if getattr(self,'delegations_ready',False) and item['record_type']=='review_note' and item.get('review_delegation'):
            self._index_delegation(item)

    def delegated_jobs(self):
        if not self.delegations_ready:
            return []
        return [self.job(r) for r, in self.db.execute('SELECT job_ref FROM review_delegations ORDER BY rowid') if self.job(r)['status'] in ('pending','running')]

    def apply_review(self,job_ref,body,*,author,**kwargs):
        if author=='researcher_self_check' and not any(j['ref']==job_ref for j in self.delegated_jobs()):
            raise ValueError('self verification requires explicit request_review through every entry point')
        return super().apply_review(job_ref,body,author=author,**kwargs)

    def _checked_dispatch(self,name,args,key):
        if name=='run_test':
            plan=self.record(args['plan_ref'],'plan')
            protocol=plan.get('protocol') or {}
            if self.closeout() and protocol.get('is_new_sample') and not any(r['plan_ref']==plan['ref'] for r in self.records('result')):
                raise ValueError('stage closeout preserves existing evidence and responses; no new physical trial')
            # Replace only the nullable protocol check from v11. The prior
            # permissions, result binding, sandbox and durable execution remain.
            return BeforeScopedGuard._checked_dispatch(self,name,args,key)
        if name in ('read_memory','read_artifact') and args['ref'].startswith('research_index:'):
            return read_index(self,**args)
        if name in ('read_memory','read_artifact') and args['ref'].startswith('original:'):
            ref = args['ref'][9:]; item = self.record(ref)
            value = {'original':item,'original_version':digest(item),'lifecycle':lifecycle(self.db,ref)}
            text = encoded(value); end = args['offset']+args['limit']
            return {'ref':args['ref'],'text':text[args['offset']:end],'original_version':digest(item),'next_offset':end if end<len(text) else None}
        if name == 'request_review':
            job = self.job(args['job_ref'])
            if job['status']=='completed':
                return {'job_ref':job['ref'],'status':'completed','review_ref':job['review_ref'],'new_request':False}
            if job['status'] not in ('pending','running'):
                raise ValueError('review episode exhausted/deferred; preserve original endpoint and disagreement')
            if digest(self.record(job['target_ref'])) != job['target_version']:
                raise ValueError('review target version changed')
            active = self.delegated_jobs()
            if any(j['ref']!=job['ref'] for j in active):
                raise ValueError('finish the existing delegated review before scheduling another')
            if self.unanswered():
                raise ValueError('respond to delivered opinions with actual evidence before scheduling the next review')
            row = self.db.execute('SELECT request_ref FROM review_delegations WHERE job_ref=?',(job['ref'],)).fetchone()
            if row:
                return {'job_ref':job['ref'],'request_ref':row[0],'status':job['status'],'new_request':False}
            note = self.add('review_note',{'author':'researcher','hypothesis_refs':self.target_hypotheses(job['target_ref']),
                'review_delegation':{'job_ref':job['ref'],'target_ref':job['target_ref'],'target_version':job['target_version'],'reason':args['reason']},
                'scientific_certification':False})
            return {'job_ref':job['ref'],'request_ref':note['ref'],'status':'scheduled','verification_mode':self.settings['verification_mode'],
                    'next':'self: inspect job packet then review_claim; independent: reviewer runs outside transaction and returns attributed feedback.'}
        if name == 'review_claim' and not any(j['ref']==args['job_ref'] for j in self.delegated_jobs()):
            raise ValueError('explicitly request_review this job before submitting self verification; do not assume every queued claim is the current task')
        result=super()._checked_dispatch(name,args,key)
        targets=([result['ref']] if result.get('ref') else [])+result.get('knowledge_refs',[])
        pending=[j for j in self.jobs('pending') if j['target_ref'] in targets]
        if pending:
            result={**result,'review_choices':[{'job_ref':j['ref'],'target_ref':j['target_ref'],'target_version':j['target_version'],'tool':'request_review','publication':'unreviewed candidate; owner chooses timing'} for j in pending]}
        if name=='finish_research' and result.get('record_type')=='report_draft':
            jobs=[j for j in pending if j['target_ref']==result['ref']]
            if jobs:
                scheduled=self._checked_dispatch('request_review',{'job_ref':jobs[0]['ref'],'reason':'Researcher explicitly submitted this stage report with finish_research; request its publication review.'},key+':publication_review')
                result={**result,'publication_review':scheduled,'handoff':'Submission requests this report review. Ordinary judgments still require explicit owner scheduling. No scientific clearance is granted by submission.'}
        return result

    def context(self):
        return build(self)
