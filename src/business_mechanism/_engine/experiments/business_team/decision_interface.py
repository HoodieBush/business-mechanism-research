"""Publish the actual operating policy and observed-action schema, not demand."""
from copy import deepcopy
from pathlib import Path
import shutil

import ordering_policy
from contracts import HOURS, field_definition
from scenario_contract import SALE_STOCK_CAP

VERSION = 'forecast-order-interface-v1'
FILE = 'decision_interface.json'
POLICY_FILE = 'ordering_policy.py'
HISTORY_FILE = 'historical_opening.csv'


def initialize(ws, *, fresh):
    from workspace import sha, write_json
    if fresh:
        shutil.copyfile(Path(ordering_policy.__file__), ws.public / POLICY_FILE)
        historical = ws.history.loc[ws.history.hour == HOURS[0],
                                    ['day', 'date', 'site', 'sku', 'hour', 'opening_stock']].copy()
        if historical.duplicated(ordering_policy.KEY).any():
            raise ValueError('historical opening observations need unique day/site/sku keys')
        historical.to_csv(ws.public / HISTORY_FILE, index=False)
        history_columns = {name: field_definition(name, structured=True) for name in historical}
        history_columns['opening_stock']['available_at'] = 'historical observed 09:00 opening; not an output of the candidate forecast'
        history_schema = {'storage': HISTORY_FILE, 'key': ordering_policy.KEY,
            'row_grain': 'one historical business day × site × SKU, observed at09:00',
            'columns': history_columns,
            'scope': 'Actual historical opening observations, including exogenous support supply. Usual sale-goods allocations predate the supplied predict programs; registered trial overrides are separate.'}
        sidecar = ws.annotate(ws.public / HISTORY_FILE, {'producer': 'environment',
            'key': history_schema['key'], 'row_grain': history_schema['row_grain'],
            'column_definitions': history_columns, 'semantics_status': history_schema['scope']})
        history_schema.update(sha256=sha(ws.public / HISTORY_FILE), metadata_file=Path(sidecar).name,
                              metadata_sha256=sha(sidecar))
        decision_columns = {name: field_definition(name, structured=True) for name in ordering_policy.KEY}
        decision_columns.update(deepcopy(ordering_policy.DECISION_FIELDS))
        manifest = {'version': VERSION,
            'implementation': {'file': POLICY_FILE, 'sha256': sha(ws.public / POLICY_FILE)},
            'parameters': ordering_policy.specification(SALE_STOCK_CAP),
            'source_files': {name: sha(ws.public / name) for name in ('products.csv', 'operating_rules.json')},
            'exports': {'historical_opening': history_schema,
                'order_decisions': {'storage': 'per-evaluation CSV; exact path in describe_evaluation observation_files.order_decisions',
                    'key': ordering_policy.KEY, 'row_grain': 'one business day × site × sale SKU',
                    'columns': decision_columns,
                    'scope': 'Fixed policy arithmetic followed by actually observed opening inventory. Plan/execution differences are retained, not a scientific verdict.'}},
            'limits': ['The policy Poisson model is an ordering assumption, not the hidden demand process.',
                       'Hour09 opening follows the order action; it is not an input column of the forecast program.',
                       'Research programs still change predict only; publishing the rule does not expand action permissions.',
                       'CSV export schemas are not new tables in business.sqlite.']}
        write_json(ws.public / FILE, manifest)
    manifest = load(ws)
    if manifest:
        ws.registered_sources.update(str(ws.public / name) for name in
                                      (FILE, POLICY_FILE, HISTORY_FILE, HISTORY_FILE + '.meta.json'))
        ws.registered_data_sources.add(str(ws.public / HISTORY_FILE))
    return manifest


def load(ws):
    import json
    from workspace import sha
    path = ws.public / FILE
    if not path.exists():
        return None  # Old immutable workspaces keep their original interface.
    manifest = json.loads(path.read_text())
    if manifest['version'] != VERSION:
        raise ValueError('unknown decision interface version; do not silently migrate')
    source = ws.readable(str(ws.public / manifest['implementation']['file']))
    expected = manifest['implementation']['sha256']
    if sha(source) != expected or sha(Path(ordering_policy.__file__)) != expected:
        raise ValueError('public and backend ordering policy versions differ; start a new phase')
    if manifest['parameters'] != ordering_policy.specification(SALE_STOCK_CAP):
        raise ValueError('public decision parameters differ from the actual fixed policy')
    for filename, expected in manifest['source_files'].items():
        if sha(ws.readable(str(ws.public / filename))) != expected:
            raise ValueError('decision interface source changed: ' + filename)
    history = manifest['exports']['historical_opening']
    for filename, expected in [(history['storage'], history['sha256']),
                               (history['metadata_file'], history['metadata_sha256'])]:
        if sha(ws.readable(str(ws.public / filename))) != expected:
            raise ValueError('historical opening source changed: ' + filename)
    return manifest


def exported_definition(ws, table):
    manifest = load(ws)
    if manifest and table in manifest['exports']:
        return manifest['exports'][table]
    return None
