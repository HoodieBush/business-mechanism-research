from pathlib import Path
from copy import deepcopy
from ..common import sha
from ..project_stages_v01.workspace import ResearchWorkspace as Previous,FreshResearchWorkspace as FreshPrevious
from .status import ReviewStatusMixin
class VersionMixin(ReviewStatusMixin):
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings);settings['project_stages_v02_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)
class ResearchWorkspace(VersionMixin,Previous):pass
class FreshResearchWorkspace(VersionMixin,FreshPrevious):pass
