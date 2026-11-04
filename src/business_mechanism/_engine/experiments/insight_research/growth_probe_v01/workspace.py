"""Small environment adapter on the current scientific record/tool backend."""
from copy import deepcopy
from pathlib import Path
from typing import Literal
from pydantic import Field
from ..common import digest, sha
from ..contracts import Input
from ..paired_v16.contracts import TOOLS as PreviousTools, schemas
from ..paired_v16.workspace import ResearchWorkspace as Previous
from .environment import Environment


class CollectEvidence(Input):
    operation: Literal['observe', 'entry_count', 'flow_audit', 'capacity_trial', 'wait']
    windows: int = Field(ge=1, le=128)
    purpose: str = Field(min_length=1)


TOOLS = {k: v for k, v in PreviousTools.items() if k != 'inspect_evidence'}
TOOLS['collect_evidence'] = (CollectEvidence, 'Collect new evidence through an installed operation in measurement_catalog.json. Declare why it can inform the research. Costs, time and observations persist; duplicate operation recovery never buys a new sample. run_python only analyzes received files and cannot simulate new business feedback as observations.')


class ResearchWorkspace(Previous):
    tools = TOOLS
    environment_class = Environment

    def __init__(self, root, question, world, settings, **kwargs):
        settings = deepcopy(settings)
        settings['growth_probe_v01_sources'] = {p.name: sha(p) for p in Path(__file__).parent.glob('*.py')}
        super().__init__(root, question, world, settings, **kwargs)
        self.environment.bind(self.private)
        self.environment.state()

    def tool_schemas(self):
        return schemas(TOOLS)

    def _checked_dispatch(self, name, args, key):
        if name == 'collect_evidence':
            directory = self.science / 'evidence' / digest(key)[:24]
            result = self.environment.perform(directory, key, **args)
            files = [self.file_ref(directory / n, 'new_observation') for n in ('receipt.json', 'observations.json')]
            return {**result, 'files': files, 'environment_status': self.environment.public_status()}
        return super()._checked_dispatch(name, args, key)

    def context(self):
        context = super().context()
        context['resources'].pop('new_trials_remaining', None)
        context['environment_status'] = self.environment.public_status()
        context['environment_capabilities'] = ('Service windows; collect_evidence obtains new measurements or randomized capacity observations. '
            'Read measurement_catalog.json for installed capabilities and costs. No office inventory or SKU protocols, no private truth access.')
        context['stage_scope'] = 'P0/finite S1 pilot; stage scientific content, not report-publication count, determines research evaluation.'
        return context
