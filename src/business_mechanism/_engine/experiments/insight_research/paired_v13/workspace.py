from pathlib import Path
from copy import deepcopy
from ..common import sha
from ..paired_v12.workspace import ResearchWorkspace as Previous

class ResearchWorkspace(Previous):
    def __init__(self,root,question,world,settings,**kwargs):
        settings=deepcopy(settings);settings['paired_v13_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,question,world,settings,**kwargs)
