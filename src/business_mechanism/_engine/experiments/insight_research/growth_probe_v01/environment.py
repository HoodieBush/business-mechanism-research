"""A service pipeline with separate business and recording processes.

Only published observations leave this host-side object. Randomness is bound
to window and event, not to the number of previous tool calls.
"""
from copy import deepcopy
import csv
import json
from pathlib import Path
import sqlite3
import numpy as np
from ..common import digest, sha, write_json

CATALOG = {
    'observe': {'cost_per_window': 1, 'latency': 0, 'measurement': 'recorded transactions only', 'changed_variable': None},
    'entry_count': {'cost_per_window': 2, 'latency': 1, 'measurement': 'entry counter plus recorded transactions', 'changed_variable': None},
    'flow_audit': {'cost_per_window': 3, 'latency': 1, 'measurement': 'sampled requests, completed requests and recorded transactions', 'changed_variable': None},
    'capacity_trial': {'cost_per_window': 3, 'latency': 1, 'measurement': 'recorded transactions by randomized capacity setting', 'changed_variable': 'capacity_multiplier'},
    'wait': {'cost_per_window': 0, 'latency': 0, 'measurement': 'no observations collected', 'changed_variable': None},
}
BRIEF = '''Study a service operation whose recorded transactions are low. Decide what can be learned about the process, whether increasing capacity is worthwhile, and what further evidence would change your understanding. Select competing explanations and evidence yourself; no correct cause is supplied.
This is a developmental simulation, not a real enterprise. A window is one equal-duration service period. Requests can enter, complete, and be entered into the transaction register. The historical table logs contains only recorded transactions and capacity settings; it is not a count of all requests. Capacity is currently1; adding a second capacity unit has an incremental per-window cost equal to2 recorded transactions. The economic question is whether its expected recorded increment exceeds2. Separately, the operator's register-completeness target is at least90% of completed requests; assess whether evidence supports this target or whether it remains unknown. These are task requirements, not universal scientific-effect thresholds.
The measurement_catalog.json lists available operations, resource charges and delays. Measures collect NEW windows; they do not reveal the unobserved past. Capacity trials randomize equally between multipliers1 and2 across new windows. Only completion capacity is manipulated; neither entry intensity nor the recording process is deliberately changed. Not every operation is installed at every deployment. Unsupported requests fail without data or charges. Waiting advances business time without observations. Existing history is seen, and no legal operation reveals hidden simulator parameters.
There are512 evidence credits and at most512 logical windows after history. Each action is limited to128 windows; trials require an even number. State and charges persist across calls. Results distinguish observation windows and availability time. Source files/receipts can be reread without buying another sample. An evidence receipt is an observation, not a scientific verdict. Save original predictions, actual analysis, revisions, alternative explanations and justified uncertainty. Different causes may remain observationally equivalent under the available instruments. Do not treat arbitrary hypothesis names, tool success or simulation source guesses as discoveries.'''


class World:
    kind = 'service_diagnostic'
    scenario_version = 'service-process-p0-v1'

    def __init__(self, *, seed, entry_rate, completion_probability, recording_probability,
                 instruments=('observe', 'entry_count', 'flow_audit', 'capacity_trial', 'wait')):
        if type(seed) is not int or seed < 0 or not 0 < entry_rate <= 32:
            raise ValueError('bounded positive arrival rate and integer seed required')
        if not 0 < completion_probability <= 1 or not 0 < recording_probability <= 1:
            raise ValueError('probabilities must be in (0,1]')
        if not set(instruments) <= set(CATALOG) or not {'observe', 'wait'} <= set(instruments):
            raise ValueError('explicit lawful instruments required')
        self.seed = seed
        self.parameters = {'entry_rate': entry_rate, 'completion_probability': completion_probability,
                           'recording_probability': recording_probability, 'instruments': list(instruments)}

    def window(self, tick, capacity=1):
        # A marked dominating Poisson process gives identical external requests
        # and recording marks when the capacity action alone is changed.
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, tick, 4109]))
        marks = rng.random((int(rng.poisson(32)), 3))
        arrivals = marks[:, 0] < self.parameters['entry_rate'] / 32
        served = arrivals & (marks[:, 1] < min(1., capacity * self.parameters['completion_probability']))
        recorded = served & (marks[:, 2] < self.parameters['recording_probability'])
        return {'window': tick, 'entries': int(arrivals.sum()), 'completed': int(served.sum()),
                'recorded_transactions': int(recorded.sum()), 'capacity_multiplier': capacity}

    def expected(self, capacity=1):
        p = self.parameters
        return p['entry_rate'] * min(1., capacity * p['completion_probability']) * p['recording_probability']


class Environment:
    def __init__(self, world):
        self.world = world
        self.state_path = None

    def materialize(self, public):
        public = Path(public)
        public.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(public / 'business.sqlite') as db:
            db.execute('CREATE TABLE logs(window INTEGER PRIMARY KEY,recorded_transactions INTEGER,capacity_multiplier INTEGER)')
            db.executemany('INSERT INTO logs VALUES (?,?,?)',
                           [(i, self.world.window(i)['recorded_transactions'], 1) for i in range(24)])
        (public / 'business_brief.md').write_text(BRIEF)
        write_json(public / 'experiment_contract.json', {})  # Native evidence uses collect_evidence, never office protocols.
        write_json(public / 'data_dictionary.json', {'tables': {'logs': {'columns': {
            'window': 'equal-duration observed period,0..23', 'recorded_transactions': 'count entered into transaction register',
            'capacity_multiplier': 'capacity units relative to original setting'}}},
            'unit': 'transactions per equal-duration window', 'history': 'seen observations, no validation claim'})
        write_json(public / 'measurement_catalog.json', {
            'operations': {k: {**v, 'available': k in self.world.parameters['instruments']} for k, v in CATALOG.items()},
            'max_windows_per_action': 128, 'evidence_credits': 512, 'future_window_limit': 512,
            'trial_assignment': 'balanced randomized windows, assigned before outcomes; capacity1 vs2'})
        self.bind(public.parent / 'private')
        state = {'identity': digest([self.world.seed, self.world.parameters]), 'clock': 24, 'spent_credits': 0,
                 'actions': {}}
        if self.state_path.exists():
            raise ValueError('new environment state already exists')
        write_json(self.state_path, state)

    def bind(self, private):
        self.state_path = Path(private) / 'environment_state.json'

    def state(self):
        state = json.loads(self.state_path.read_text())
        if state['identity'] != digest([self.world.seed, self.world.parameters]):
            raise ValueError('environment identity differs; never reset live state')
        return state

    def public_status(self):
        s = self.state()
        return {'clock': s['clock'], 'spent_credits': s['spent_credits'],
                'remaining_credits': 512 - s['spent_credits'], 'remaining_windows': 536 - s['clock'],
                'completed_evidence_actions': len(s['actions'])}

    def perform(self, directory, key, *, operation, windows, purpose):
        if operation not in CATALOG or operation not in self.world.parameters['instruments']:
            raise ValueError('operation not installed; consult measurement_catalog.json')
        if type(windows) is not int or not 1 <= windows <= 128:
            raise ValueError('windows must be an integer in1..128')
        if operation == 'capacity_trial' and windows % 2:
            raise ValueError('balanced capacity trial requires an even number of windows')
        signature = digest([operation, windows, purpose]); state = self.state()
        if key in state['actions']:
            saved = state['actions'][key]
            if saved['signature'] != signature:
                raise ValueError('evidence operation identity reused with different arguments')
        else:
            p = CATALOG[operation]; cost = p['cost_per_window'] * windows
            end = state['clock'] + windows; available = end + p['latency']
            if state['spent_credits'] + cost > 512 or available > 536:
                raise ValueError('evidence resource/time limit; no action or observation occurred')
            allocations = np.ones(windows, dtype=int)
            if operation == 'capacity_trial':
                rng = np.random.default_rng(np.random.SeedSequence([self.world.seed, state['clock'], 719]))
                allocations = rng.permutation([1] * (windows//2) + [2] * (windows//2))
            rows = []
            for tick, capacity in zip(range(state['clock'], end), allocations):
                raw = self.world.window(tick, int(capacity))
                columns = ['window', 'recorded_transactions', 'capacity_multiplier']
                if operation in ('entry_count', 'flow_audit'): columns.append('entries')
                if operation == 'flow_audit': columns.append('completed')
                if operation != 'wait': rows.append({k: raw[k] for k in columns})
            receipt = {'operation': operation, 'purpose': purpose, 'new_observation': operation != 'wait',
                       'evidence_nature': 'no_observation' if operation == 'wait' else 'randomized_intervention' if operation == 'capacity_trial' else 'new_measurement',
                       'observation_start': state['clock'], 'observation_end_exclusive': end, 'available_at': available,
                       'windows': windows, 'credit_charge': cost, 'changed_variable': p['changed_variable'],
                       'measurement': p['measurement'], 'rows': len(rows), 'scientific_certification': False}
            saved = {'signature': signature, 'receipt': receipt, 'rows': rows}
            # Host-side durable commit precedes publication; replay materializes
            # these same rows after a crash instead of collecting fresh data.
            state['actions'][key] = saved; state['clock'] = available; state['spent_credits'] += cost
            write_json(self.state_path, state)
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
        for name, content in [('receipt.json', saved['receipt']), ('observations.json', saved['rows'])]:
            path = directory / name
            if path.exists() and json.loads(path.read_text()) != content:
                raise ValueError('published evidence changed; preserve original state')
            if not path.exists(): write_json(path, content)
        return deepcopy(saved['receipt'])

    def execute(self, *args, **kwargs):
        raise ValueError('No office SKU protocol; use the installed collect_evidence operations')
