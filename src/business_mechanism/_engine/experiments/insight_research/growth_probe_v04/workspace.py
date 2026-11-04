from copy import deepcopy
import json
import math
from ..common import Pending,digest,encoded
from ..memory import terms
from ..paired_v16.contracts import schemas
from ..project_stages_v01.archive import ArchiveAccess
from ..project_stages_v02.status import ReviewStatusMixin
from ..growth_probe_v03.workspace import ResearchWorkspace as Previous


class Search(Previous.tools['search_memory'][0]):
    archive_stage:str|None=None


class ResearchWorkspace(ReviewStatusMixin,ArchiveAccess,Previous):
    tools={**Previous.tools,'search_memory':(Search,Previous.tools['search_memory'][1]+' Optional archive_stage selects explicitly received historical originals; empty query enumerates them.')}

    def tool_schemas(self):
        tools=super().tool_schemas()
        new=schemas({'search_memory':self.tools['search_memory']})[0]
        return [new if t['function']['name']=='search_memory' else t for t in tools]

    def _checked_dispatch(self,name,args,key):
        if name in ('read_memory','read_artifact') and args['ref'].startswith(('archive:','archive_index:')):
            return self.archive_read(args)
        if name=='search_memory':
            if args.get('archive_stage') is not None:return self.archive_search(args)
            args={k:v for k,v in args.items() if k!='archive_stage'}
        return super()._checked_dispatch(name,args,key)

    def experience_context(self):
        mode=self.settings.get('experience_mode','none')
        if mode not in ('none','recent','episode'):raise ValueError('Registered experience mode required')
        if mode=='none':
            if self.archive_descriptors():raise ValueError('No-experience condition must not receive history')
            return {'mode':mode,'items':[],'history_available':False}
        descriptors=self.archive_descriptors()
        if len(descriptors)!=1:raise ValueError('This finite selector uses one explicitly registered history')
        stage=descriptors[0]['stage_id'];view=self.archive_view(stage)
        try:
            rows=[(seq,json.loads(body)) for seq,body in view.db.execute('SELECT seq,body FROM docs ORDER BY seq')]
            selected=[];selection={}
            if mode=='recent':
                selected=[r for _,r in reversed(rows) if r['record_type']=='knowledge'][:3]
                selection={'rule':'Most recent3native knowledge records, no truth or efficacy filter'}
            else:
                hypotheses=[r for _,r in rows if r['record_type']=='hypothesis']
                query=set(terms(self.question));tokens={r['ref']:set(w for field in ('statement','prediction','falsification','scope','tags') for w in terms(encoded(r.get(field,'')))) for r in hypotheses}
                score={r['ref']:sum(1+math.log((len(hypotheses)+1)/(1+sum(t in ts for ts in tokens.values()))) for t in query&tokens[r['ref']]) for r in hypotheses}
                if hypotheses:
                    # Ties follow original chronological order, never hidden
                    # labels, current outcomes or Root scientific corrections.
                    h=max(hypotheses,key=lambda r:score[r['ref']]);selected=[h]
                    for kind in ('assessment','result'):
                        linked=[r for _,r in rows if r['record_type']==kind and r.get('hypothesis_ref')==h['ref']]
                        if linked:selected.append(linked[-1])
                    selection={'rule':'Question text match to one originalH, then latest linkedA/R; source status is not current applicability',
                        'query_terms':sorted(query),'selected_hypothesis':h['ref'],'match_score':score[h['ref']]}
            items=[];used=0
            for r in selected:
                ref='archive:'+stage+':'+r['ref']
                status=self.source_status(stage,r['ref'])
                item={'ref':ref,'record_type':r['record_type'],'original_version':digest(r),'source_lifecycle':view.review(r['ref']),
                    'source_review_status':status,'historical_not_current_fact':True,'full_original_read_ref':ref}
                if len(encoded(r).encode())<=1800:item['original']=r
                else:
                    item.update(preview_only=True,preview={k:str(r[k])[:360] for k in ('statement','scope','prediction','falsification','rationale','status') if k in r})
                    if r['record_type']=='result':item['preview']['stdout']=r['actual_execution'].get('stdout','')[:700]
                    item['instruction']='Preview is incomplete; read the exact original before using its scientific content.'
                if used+len(encoded(item).encode())>6144:
                    item={k:item[k] for k in ('ref','record_type','original_version','historical_not_current_fact','full_original_read_ref')}
                    item['preview_moved_to_original']=True
                if used+len(encoded(item).encode())<=6144:
                    items.append(item);used+=len(encoded(item).encode())
            return {'mode':mode,'items':items,'automatic_context_bytes':used,'automatic_context_cap':6144,'selection':selection,
                'common_scope':'Earlier research in a related task, including mistaken/unfinished claims. Read originals and decide applicability to current data; no old claim is automatically a current premise.',
                'citation':'Read archive ref to obtain materialized_original.ref; cite that received file in evidence_refs/used_memory_refs. Archive IDs are navigation, not current H/K IDs.'}
        finally:view.close()

    def context(self):
        ctx=super().context();ctx['project_research_history']=self.archive_context();ctx['prior_experience']=self.experience_context()
        if len(encoded(ctx).encode())>self.settings['execution_policy']['active_context_bytes']:
            raise Pending('Bounded current view plus registered history navigation exceeds capacity; exact originals retained')
        return ctx
