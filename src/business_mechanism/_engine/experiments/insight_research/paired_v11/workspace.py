from pathlib import Path
from copy import deepcopy
from ..common import digest,encoded,sha
from ..critic_v01.shared import lifecycle
from ..paired_v10.workspace import ResearchWorkspace as Previous
from .contracts import TOOLS,schemas
from .statistic import inspect

class ResearchWorkspace(Previous):
    tools=TOOLS
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings);settings['paired_v11_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)
    def tool_schemas(self):return schemas(TOOLS)

    def index(self,ref,kind,body,hypotheses=(),tags=()):
        super().index(ref,kind,body,hypotheses,tags)
        if kind in ('review','review_response','report_draft','report'):
            extra=encoded({k:body[k] for k in ('issues','checked_scope','unchecked_scope','object_reviews','deferred_review_jobs') if k in body})[:24000]
            row=self.db.execute('SELECT text FROM search_docs WHERE ref=?',(ref,)).fetchone()
            text=row[0]+' '+extra;self.db.execute('UPDATE search_docs SET text=? WHERE ref=?',(text,ref))
            self.db.execute('DELETE FROM memory_fts WHERE ref=?',(ref,));self.db.execute('INSERT INTO memory_fts VALUES (?,?)',(ref,text))

    def _index_review(self,item):
        super()._index_review(item)
        if item['record_type']=='review_response':
            for action in item.get('object_reviews',[]):
                self._flag(action['target_ref'],'active' if action['decision']=='restore' else action['decision'],action['reason'],item['ref'],acknowledge_dependencies=action['decision']=='restore')
        if item['record_type']=='report_draft':
            for job_ref,reason in item.get('deferred_review_jobs',{}).items():
                job=self.job(job_ref)
                self.db.execute("UPDATE review_jobs SET status='deferred',reason=? WHERE ref=?",('Explicit stage deferral: '+reason,job_ref))
                self._flag(job['target_ref'],'quarantine','Unreviewed judgment excluded from this stage: '+reason,item['ref'])

    def data_references(self,refs):
        self.references(refs)
        for ref in refs:
            if not ref.startswith('file:') and self.record(ref)['record_type'] in ('review','review_response','review_note','review_action'):
                raise ValueError('opinion/response/action records are not scientific data evidence; cite actual received files/results')

    def respond(self,response,state_ref):
        q=self.record(response['review_ref'],'review');issue=next((i for i in q['issues'] if i['issue_id']==response['issue_id']),None)
        if issue is None:raise ValueError('response issue does not belong to review')
        response=deepcopy(response)
        actions=response.get('object_reviews',[])
        if len({a['target_ref'] for a in actions})!=len(actions):raise ValueError('one explicit lifecycle action per affected object')
        for action in actions:
            target=action['target_ref']
            if target not in issue['affected_refs']:raise ValueError('lifecycle action must match an object affected by this exact issue')
            if action['expected_version'] is None:
                action['expected_version']=q.get('affected_versions',{}).get(target)
            if digest(self.record(target))!=action['expected_version']:raise ValueError('affected object version differs; read original before repair')
            self.data_references(action['evidence_refs'])
            if action['decision']=='restore' and (lifecycle(self.db,target)['replacement_ref'] or lifecycle(self.db,target)['status']=='superseded'):raise ValueError('superseded original cannot be restored')
        return super().respond(response,state_ref)

    def unanswered(self,refs=None):
        active={(b['review_ref'],b['issue_id']) for b in self.records('review_response') if lifecycle(self.db,b['ref'])['status']=='active'}
        return [{'review_ref':q['ref'],'issue_id':i['issue_id'],'affected_refs':i['affected_refs'],'basis':i['basis'],'blocking':i['blocking'],'claim_impact':i['claim_impact']}
                for q in self.records('review') if q['phase']=='complete' for i in q['issues']
                if (q['ref'],i['issue_id']) not in active and (refs is None or set(i['affected_refs']).intersection(refs))]

    def closeout(self):
        if not hasattr(self,'study_budget'):return None
        with self.study_budget.connect() as db:
            row=db.execute("SELECT value FROM flags WHERE key='stage_closeout'").fetchone()
        return row[0] if row else None

    def validate_deferrals(self,args):
        jobs=args.get('deferred_review_jobs',{})
        if jobs and not self.closeout():raise ValueError('explicit review deferral is available only in registered stage closeout')
        if not jobs:return
        with self.study_budget.connect() as db:paid={r for r, in db.execute('SELECT DISTINCT role FROM attempts')}
        for ref,reason in jobs.items():
            job=self.job(ref);target=self.record(job['target_ref'])
            if not reason.strip() or target['record_type']!='assessment' or job['status'] not in ('pending','running'):
                raise ValueError('nonempty reason and active assessment review required for deferral')
            if job['target_ref'] in args['assessment_refs']:raise ValueError('cannot defer a judgment published as a current assessment')
            if 'critic:'+ref in paid:raise ValueError('paid reviewer work must be drained/preserved, not deferred by stage publication')

    def _checked_dispatch(self,name,args,key):
        if name=='inspect_evidence':
            return inspect(self,args,key,lambda data,op:super(ResearchWorkspace,self)._checked_dispatch('run_python',data,op))
        if name=='record_assessment':
            for ref in args['supporting_artifact_refs']:
                if not ref.startswith('file:'):raise ValueError('supporting_artifact_refs accepts actual received files only')
                self.file(ref)
            h=self.record(args['hypothesis_ref'],'hypothesis')
            for part in args['component_adjudications']:
                if not part['original_criterion'].strip() or part['original_criterion'] not in h['falsification']:
                    raise ValueError('component must quote an exact original falsification criterion, not a newly invented rule')
                self.data_references(part['evidence_refs'])
        if name=='run_test' and self.closeout():
            plan=self.record(args['plan_ref'],'plan')
            if plan.get('protocol',{}).get('is_new_sample') and not any(r['plan_ref']==plan['ref'] for r in self.records('result')):
                raise ValueError('registered stage closeout reserves remaining work for existing evidence/response/delivery; no new physical trial. Original plan remains saved, not refuted.')
        if name=='finish_research':self.validate_deferrals(args)
        result=super()._checked_dispatch(name,args,key)
        if name in ('read_artifact','read_memory') and not args['ref'].startswith(('file:','job:','event:','process:','directory:')):
            try:item=self.record(args['ref'].removeprefix('card:'))
            except ValueError:item=None
            if item:result={**result,'original_version':digest(item)}
        if name=='respond_to_review' and result.get('ref'):
            q=self.record(args['review_ref']);issue=next(i for i in q['issues'] if i['issue_id']==args['issue_id'])
            result={**result,'affected_object_state':{ref:lifecycle(self.db,ref) for ref in issue['affected_refs']},
                    'repair_scope':'Explicit object/dependency state only, not semantic repair certification.'}
        return result

    def context(self):
        ctx=super().context();ctx['scoped_computation']='inspect_evidence reanalyses received CSV/hourlySQLite. Explicit hour/arm/product/site/unit/confidence/clusters/df travel with values. No non-significance=>absence, no failure-to-reject=>equivalence.'
        ctx['assessment_policy']='result_refs only formal original-H results; auxiliary files in supporting_artifact_refs. component_adjudications quote original falsifiers. Numeric status alone does not establish a mechanism.'
        ctx['object_version_policy']='read_memory/read_artifact returns original_version uniformly. object_reviews may omit expected_version to bind the received opinion affected_versions exactly; explicit mismatches are rejected.'
        ctx['repair_policy']='respond_to_review.object_reviews can explicitly quarantine/withdraw/restore an affected object at expected_version with original evidence. A new summary or acceptance does not fix an old claim. Check dependent_review_queue.'
        ctx['stage_closeout']=self.closeout()
        if ctx['stage_closeout']:
            ctx['stage_delivery']='Save/absorb paid work, respond to issues, and finish an honest finite stage. You may exclude unreviewed assessments via other_hypotheses and explicitly defer their unpaid jobs using finish_research.deferred_review_jobs. They become quarantined; all originals disclosed; report still reviewed. No new physical trial, formed hypotheses may still be saved.'
        return ctx
