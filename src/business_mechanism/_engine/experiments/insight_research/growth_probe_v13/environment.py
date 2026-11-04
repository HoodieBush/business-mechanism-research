"""Clarify normal measurement definitions without altering observations/actions."""
import json
from ..common import write_json
from ..growth_probe_v01.environment import Environment as Previous

COUNTER_SEMANTICS = {
    'window': 'One equal-duration closed service cohort; no carry-over requests or retrospective register backfill in this diagnostic episode.',
    'entries': 'Number of distinct requests entering this cohort during its window.',
    'completed': 'Number of those distinct entering requests whose service completes in that same window; each request completes at most once.',
    'recorded_transactions': 'Number of those completed requests entered in the transaction register in that window; each completed request is entered at most once. This is not a definition of completed.',
    'capacity_multiplier': 'Capacity assigned for the window before its outcomes. Available operations and fields remain exactly as listed in measurement_catalog.json.',
    'sampling_scope': 'Independent same-duration windows in this stable deployment; the exogenous request-arrival process has the same law across measurement operations and randomized capacity settings. Its rate is not provided.',
    'target_quantity': 'Register completeness at a specified capacity is the fraction of completed requests that are recorded, aggregated over the corresponding population of windows; it is a ratio of total counts, not an average of per-window fractions.'}


class Environment(Previous):
    def materialize(self, public):
        super().materialize(public)
        path = public / 'data_dictionary.json'
        data = json.loads(path.read_text())
        data['observed_counter_definitions'] = COUNTER_SEMANTICS
        data['measurement_contract_version'] = 'closed-cohort-count-definitions-v2'
        write_json(path, data)
        with (public / 'business_brief.md').open('a') as stream:
            stream.write('\nThe data_dictionary.json defines the observed counters and their sampling population. These are normal measurement definitions for this finite deployment, not hidden probabilities or a supplied scientific explanation. Use the actual installed fields; a definition does not mean every counter is measured under every capacity.\n')
