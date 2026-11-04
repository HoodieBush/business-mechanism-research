"""Align the public service-analysis schema with the existing execution path.

No extra tool, scientific rule, automatic preregistration certificate or future
observation is supplied. Old versions and already-paid submissions stay intact.
"""
from copy import deepcopy
from ..growth_probe_v04.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def tool_schemas(self):
        tools = deepcopy(super().tool_schemas())
        for tool in tools:
            function = tool['function']
            if function['name'] != 'register_test':
                continue
            parameters = function['parameters']
            props = parameters['properties']
            props['code'] = {'type': 'string', 'minLength': 1, 'description':
                'Exact executable analysis source. You may save it before collecting future windows: '
                'use received catalog/brief refs and a fixed selection/validation rule for future receipts. '
                'Collection is a separate collect_evidence action. Do not claim formal future-data binding or automatic scientific certification.'}
            props['expected_changed_variables'] = {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 0,
                'description': 'Use []. This analysis action manipulates no business variable. '
                'A separate capacity_trial receipt records its actual randomized capacity manipulation.'}
            parameters['required'] = list(dict.fromkeys(parameters.get('required', []) + ['code']))
            function['description'] += (' Service analysis requires fixed nonempty code and expected_changed_variables=[]. '
                'Code may be saved before acquisition; it can also analyze already-seen data. '
                'The timing and received source nature must be reported honestly.')
        return tools

    def _checked_dispatch(self, name, args, key):
        if name == 'register_test' and args.get('mode') == 'observational':
            if not args.get('code') or args.get('expected_changed_variables'):
                raise ValueError('Service analysis registration requires fixed nonempty code and '
                    'expected_changed_variables=[]. This action only analyzes data. '
                    'Use collect_evidence separately for new measurements or capacity manipulation. '
                    'Fixed code can be saved before that acquisition using received catalog/brief refs '
                    'and a declared selection rule for future receipts. No plan was saved by this rejected call.')
        return super()._checked_dispatch(name, args, key)
