from pathlib import Path
from copy import deepcopy
from ..common import sha
from ..paired_v12.review import Reviewer as Previous,ReviewerRuntime as PreviousRuntime
from .context import compact_with_admission

class Reviewer(Previous):
    def __init__(self,root,snapshot,settings,**kwargs):
        settings=deepcopy(settings);settings['paired_v13_sources']={p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}
        super().__init__(root,snapshot,settings,**kwargs)

class ReviewerRuntime(PreviousRuntime):
    def compact(self):return compact_with_admission(self,super().compact)
