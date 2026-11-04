from copy import deepcopy
from pathlib import Path
from ..common import sha
from ..write_outcomes_v02.review import Reviewer as Previous,ReviewerRuntime
from .archive import ArchiveAccess
from .contracts import REVIEW_TOOLS,schemas
class Reviewer(ArchiveAccess,Previous):
    tools=REVIEW_TOOLS
    def __init__(self,root,snapshot,settings,**kwargs):
        settings=deepcopy(settings);settings['project_stages_v01_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,snapshot,settings,**kwargs)
    def tool_schemas(self):return schemas(REVIEW_TOOLS)
    def dispatch(self,name,args,key):
        if name in ('read_memory','read_artifact') and args['ref'].startswith(('archive:','archive_index:')):return self.archive_read(args)
        if name=='search_memory':
            if args.get('archive_stage') is not None:return self.archive_search(args)
            args={k:v for k,v in args.items() if k!='archive_stage'}
        return super().dispatch(name,args,key)
    def context(self):return {**super().context(),'project_research_history':self.archive_context()}
