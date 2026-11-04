from pathlib import Path
from copy import deepcopy
from ..common import sha
from ..project_stages_v01.review import Reviewer as Previous,ReviewerRuntime
from .status import ReviewStatusMixin
class Reviewer(ReviewStatusMixin,Previous):
    def __init__(self,root,snapshot,settings,**kwargs):
        settings=deepcopy(settings);settings['project_stages_v02_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,snapshot,settings,**kwargs)
