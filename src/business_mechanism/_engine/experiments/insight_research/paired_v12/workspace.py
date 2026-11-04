from pathlib import Path
from copy import deepcopy
from ..common import sha
from .journal_memory import own_context,read_own_memory
from ..critic_v01.shared import lifecycle
from ..paired_v11.workspace import ResearchWorkspace as Previous

class ResearchWorkspace(Previous):
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings);settings['paired_v12_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)

    def validate_restorations(self,actions):
        for action in actions:
            if action['decision']!='restore':continue
            ref=action['target_ref'];self.record(ref)
            replacement=self.db.execute("SELECT ref FROM records WHERE json_extract(body,'$.supersedes_assessment_ref')=? OR json_extract(body,'$.supersedes_ref')=? OR json_extract(body,'$.supersedes_draft_ref')=? LIMIT 1",(ref,ref,ref)).fetchone()
            if replacement:raise ValueError('immutable replacement chain exists; review/revise the replacement, do not restore superseded original: '+replacement[0])

    def respond(self,response,state_ref):
        self.validate_restorations(response.get('object_reviews',[]))
        return super().respond(response,state_ref)

    def _checked_dispatch(self,name,args,key):
        if name in ('read_memory','read_artifact') and args['ref'].startswith(('own_context:','own_process:','own_log:')):
            return read_own_memory(self,**args)
        if name=='update_research_state':self.validate_restorations(args.get('memory_reviews',[]))
        return super()._checked_dispatch(name,args,key)

    def _index_review(self,item):
        previous={}
        if item['record_type']=='report_draft':
            previous={self.job(j)['target_ref']:lifecycle(self.db,self.job(j)['target_ref']) for j in item.get('deferred_review_jobs',{})}
        super()._index_review(item)
        if item['record_type']=='assessment' and item.get('supersedes_assessment_ref'):
            self._flag(item['supersedes_assessment_ref'],'superseded','assessment replaced by '+item['ref'],item['ref'])
        if item['record_type']=='report_draft' and item.get('supersedes_draft_ref'):
            self._flag(item['supersedes_draft_ref'],'superseded','draft replaced by '+item['ref'],item['ref'])
        for ref,state in previous.items():
            if state['status'] in ('superseded','withdraw'):
                self._flag(ref,state['status'],state['reason'],state['review_record'])

    def context(self):
        context=super().context();context['own_journal_memory']=own_context(self);context['archived_path_policy']='Original conversations/receipts can retain old absolute paths. Read actual file refs for the current compute_path; sandbox work uses current PUBLIC_DIR/WORK_DIR. Originals stay immutable.';return context
