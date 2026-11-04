from copy import deepcopy
from pathlib import Path
import re
from ..common import digest, sha
from ..growth_probe_v10.workspace import ResearchWorkspace as Previous
from ..growth_probe_v12.context import experience_context
from .environment import Environment


class ResearchWorkspace(Previous):
    environment_class = Environment
    experience_context = experience_context

    def __init__(self, root, question, world, settings, **kwargs):
        settings = deepcopy(settings)
        settings['measurement_semantics_adapter'] = {p.name: sha(p) for p in Path(__file__).parent.glob('*.py')}
        super().__init__(root, question, world, settings, **kwargs)

    def tool_schemas(self):
        tools = super().tool_schemas()
        for tool in tools:
            name = tool['function']['name']
            if name == 'update_research_state':
                tool['function']['description'] += (' historical_field_reviews is a delta: omit unchanged current fields. '
                    'Do not repeat a previous replacement merely to preserve it; omission keeps the current effective value. '
                    'Use the archive read receipt original_version as source_version, not its wrapper sha256.')
            elif name == 'review_claim':
                tool['function']['description'] += (' A phase=checkpoint saves unfinished verification. Continue that same job to phase=complete '
                    'before responding to it as an owner; prior_issue_updates is for an explicitly directed recheck, not an unfinished same-job checkpoint. '
                    'A replacement candidate retains its own separate review job.')
        return tools

    def archive_read(self, args):
        result = super().archive_read(args)
        ref = args['ref']
        if re.fullmatch(r'archive:[A-Za-z0-9_-]{1,80}:K[A-Za-z0-9]+', ref):
            original = self.historical_original(ref)[1]
            result['original_version'] = digest(original)
            result['citation_usage'] = ('Use original_version for historical_field_reviews.source_version; '
                'use materialized_original.ref in evidence/citation fields. sha256 identifies the received wrapper file, not the scientific original.')
        return result
