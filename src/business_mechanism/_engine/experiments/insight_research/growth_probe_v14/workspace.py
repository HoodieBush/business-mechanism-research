from copy import deepcopy
from pathlib import Path
from ..common import sha
from ..growth_probe_v13.workspace import ResearchWorkspace as Previous
from .context import experience_context


class ResearchWorkspace(Previous):
    experience_context = experience_context

    def __init__(self, root, question, world, settings, **kwargs):
        settings = deepcopy(settings)
        settings['method_retrieval_source'] = {p.name: sha(p) for p in Path(__file__).parent.glob('*.py')}
        super().__init__(root, question, world, settings, **kwargs)
