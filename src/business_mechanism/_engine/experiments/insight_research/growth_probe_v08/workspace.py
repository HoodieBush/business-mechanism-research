from copy import deepcopy
from ..growth_probe_v07.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def tool_schemas(self):
        tools = deepcopy(super().tool_schemas())
        for tool in tools:
            if tool['function']['name'] == 'update_research_state':
                definition = tool['function']['parameters']['$defs']['HistoricalFieldReview']
                definition['properties']['decision']['description'] = (
                    'retain preserves an unmodified original field. After replace/withdraw, specify '
                    'the intended text explicitly with replace (including restoration of old original text) '
                    'and bind expected_prior_revision_ref; retain cannot silently undo a correction.')
        return tools

    def validate_field_review(self, action):
        validated = super().validate_field_review(action)
        current = self.field_actions(action['source_ref'], action['source_version']).get(action['field'])
        if action['decision'] == 'retain' and current and current['decision'] != 'retain':
            raise ValueError('retain cannot undo an existing field replacement/withdrawal. '
                'Use replace with the explicit intended text and expected_prior_revision_ref; '
                'restoring an old original value requires an evidence-linked explicit replacement.')
        return validated
