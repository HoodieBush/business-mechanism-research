from copy import deepcopy
from pathlib import Path
from datetime import date
from ..common import sha,encoded,Pending
from ..stage_delivery_v01.workspace import ResearchWorkspace as Previous,FreshResearchWorkspace as FreshPrevious
from .archive import ArchiveAccess
from .contracts import TOOLS,schemas
class ProjectMixin(ArchiveAccess):
    tools=TOOLS
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings);settings['project_stages_v01_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)
    def tool_schemas(self):return schemas(TOOLS)
    def _checked_dispatch(self,name,args,key):
        if name=='register_test' and args.get('confirmation') and self.archive_descriptors():
            source=self.settings.get('project_confirmation_slice');seen=self.settings.get('project_seen_sources',[])
            if not source or source.get('sha256')!=self.settings.get('confirmation_sha256'):raise ValueError('project confirmation needs its explicit registered source identity/date slice; old archive/workspace does not restore unseen status')
            if date.fromisoformat(source['start'])>date.fromisoformat(source['end']):raise ValueError('invalid registered confirmation interval')
            if any(x['sha256']==source['sha256'] or (x['dataset_id']==source['dataset_id'] and not (source['end']<x['start'] or source['start']>x['end'])) for x in seen):
                raise ValueError('already_seen_project_source: use ordinary observed-data analysis, not a newly unseen confirmation claim')
        if name in ('read_memory','read_artifact') and args['ref'].startswith(('archive:','archive_index:')):return self.archive_read(args)
        if name=='search_memory':
            if args.get('archive_stage') is not None:return self.archive_search(args)
            args={k:v for k,v in args.items() if k!='archive_stage'}
        return super()._checked_dispatch(name,args,key)
    def context(self):
        ctx=super().context();ctx['project_research_history']=self.archive_context()
        limit=self.settings.get('execution_policy',{}).get('active_context_bytes',65536)
        if len(encoded(ctx).encode())>limit:ctx['review_interface'].pop('recent_actual_actions',None)
        if len(encoded(ctx).encode())>limit:raise Pending('bounded project history context cannot fit; preserve all original archives')
        return ctx
class ResearchWorkspace(ProjectMixin,Previous):pass
class FreshResearchWorkspace(ProjectMixin,FreshPrevious):pass
