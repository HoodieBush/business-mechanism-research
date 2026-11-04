"""Explicit same-environment continuation. Parent bytes remain immutable.

Only scientific records, lawful files and owner process archives are imported.
No evaluator reports, hidden generator, old transport allowance or live queue is
made active. The parent snapshot is a frozen input, not a new scientific sample.
"""
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import re
import shutil
import sqlite3
from .common import ROOT, Pending, digest, encoded, sha, write_json
from .memory import file_refs
from .robust import RobustWorkspace
from .runtime_memory import reconstruct_request


def read(path):
    return json.loads(Path(path).read_text())


def local(root, name):
    path = (Path(root) / name).resolve()
    if Path(name).is_absolute() or '..' in Path(name).parts or not path.is_relative_to(Path(root).resolve()):
        raise ValueError('continuation path must stay inside its declared root')
    return path


def allowed(name):
    parts = Path(name).parts
    if not parts or any(p in ('..', 'tmp', '.matplotlib') for p in parts): return False
    if parts[0] in ('public', 'science'): return True
    return len(parts) > 1 and parts[0] == 'private' and parts[1] in (
        'records.sqlite', 'identity.json', 'checkpoint.json', 'transport.json',
        'turns', 'requests', 'message_objects', 'http', 'effects', 'parent_run', 'continuation.json')


def verify_files(parent, manifest):
    for name, version in manifest['sha256'].items():
        path = local(parent, name)
        if not allowed(name) or (Path(parent) / name).is_symlink() or not path.is_file() or sha(path) != version:
            raise ValueError('parent snapshot changed or has an unlawful file: ' + name)


def snapshot(parent, provenance, *, root=ROOT):
    """Read-only snapshot, also used with synthetic parents in engineering tests."""
    parent = Path(parent).resolve(); relative = str(parent.relative_to(Path(root).resolve()))
    lock = (parent / 'private/runtime.lock').open('rb')
    try:
        try: fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError: raise Pending('parent is still owned by a running process')
        cp = read(parent / 'private/checkpoint.json'); transport = read(parent / 'private/transport.json')
        if cp['status'] != 'pending' or cp.get('pending') or cp.get('transport_failures'):
            raise Pending('parent needs a stopped checkpoint with all paid tools drained')
        if transport.get('inflight') or transport.get('delivery'):
            raise Pending('parent has an unsettled or unacknowledged paid response')
        with sqlite3.connect((parent / 'private/records.sqlite').as_uri() + '?mode=ro', uri=True) as db:
            if db.execute("SELECT 1 FROM operations WHERE status!='completed' LIMIT 1").fetchone():
                raise Pending('parent has a prepared operation; recover it before continuation')
            if db.execute("SELECT 1 FROM records WHERE kind='report' LIMIT 1").fetchone():
                raise ValueError('this continuation entry handles unfinished research only')
            for ref, body in db.execute('SELECT ref,body FROM records'):
                if read(parent / 'science/records' / (ref + '.json')) != json.loads(body):
                    raise ValueError('parent published record does not match its database')
            for ref, name, version in db.execute('SELECT ref,path,hash FROM files'):
                path = local(parent, name)
                if not allowed(name) or not path.is_file() or sha(path) != version:
                    raise ValueError('parent received file changed: ' + ref)
            last = db.execute("SELECT max(id) FROM events WHERE json_extract(body,'$.tool')='update_research_state' AND json_extract(body,'$.result.ref') IS NOT NULL").fetchone()[0] or 0
            work = []
            for number, body in db.execute('SELECT id,body FROM events WHERE id>? ORDER BY id', (last,)):
                item = json.loads(body)
                if item['tool'] == 'model_response': continue
                work.append({'event_ref': 'event:' + str(number), 'tool': item['tool'],
                    'purpose': item['arguments'].get('purpose', ''), 'result_ref': item['result'].get('ref'),
                    'evidence_refs': list(dict.fromkeys(file_refs(item['result']))),
                    'model_response_ref': item.get('model_response_ref')})
            active = [r[0] for r in db.execute("SELECT ref FROM hypothesis_status WHERE status IN ('active','new')")]
        effects = [read(p) for p in (parent / 'private/effects').glob('*.json')]
        for effect in effects:
            receipt = Path(effect['receipt'])
            if not receipt.is_relative_to(parent / 'science') or not receipt.is_file():
                raise Pending('parent effect has no completed lawful receipt; do not replay it')
        identity = read(parent / 'private/identity.json')
        if any(not (parent / 'private/turns' / (str(i) + '.json')).is_file() for i in range(1, cp['responses'] + 1)):
            raise Pending('parent logical response archive is incomplete')
        paths = []
        for folder in ('public', 'science', 'private'):
            for path in (parent / folder).rglob('*'):
                name = str(path.relative_to(parent))
                if allowed(name) and path.is_symlink(): raise ValueError('symlinks cannot enter a continuation')
                if allowed(name) and path.is_file(): paths.append(path)
        prior = read(parent / 'private/continuation.json') if (parent / 'private/continuation.json').exists() else None
        manifest = {'format': 'research-continuation-v1', 'parent_workspace': relative, 'provenance': provenance,
            'identity': identity, 'sha256': {str(p.relative_to(parent)): sha(p) for p in paths},
            'inherited_trials': sum(bool(e.get('physical_trial')) for e in effects) + (prior['inherited_trials'] if prior else 0),
            'parent_responses': cp['responses'], 'parent_phase_tokens': transport['accounted_tokens'],
            'prior_reported_tokens': transport['accounted_tokens'] + (prior['prior_reported_tokens'] if prior else 0),
            'active_hypothesis_refs': active, 'last_state_event': last, 'uncheckpointed_work': work,
            'parent_local_attempts': transport['attempts']}
        verify_files(parent, manifest)
        for attempt in range(1, transport['attempts'] + 1): reconstruct_request(parent / 'private', attempt)
        if read(parent / 'private/checkpoint.json') != cp or read(parent / 'private/transport.json') != transport:
            raise Pending('parent advanced while taking the snapshot')
        return manifest
    finally: lock.close()


def registered_snapshot(study_id, run_id, *, root=ROOT):
    from scripts import research_workflow as workflow
    path, study = workflow.find(root, study_id)
    if run_id not in {r['id'] for r in study['execution']['runs']}: raise ValueError('unknown parent run')
    decision = path.parent / 'decision.json'; seal = read(path.parent / 'freeze.json')
    if not decision.is_file(): raise ValueError('new continuation phase requires the parent allocation to be reviewed')
    if read(decision)['protocol_sha256'] != sha(path): raise ValueError('parent protocol changed')
    for name, version in read(decision)['evidence_sha256'].items():
        if sha(local(root, name)) != version: raise ValueError('parent reviewed evidence changed')
    for name, version in seal['sha256'].items():
        if sha(path.parent / 'source_archive' / name) != version: raise ValueError('parent source archive changed')
    parent = path.parent / 'results' / run_id / 'case/workspace'
    return snapshot(parent, {'study_id': study_id, 'run_id': run_id, 'protocol_sha256': sha(path),
        'decision_sha256': sha(decision), 'freeze_sha256': sha(path.parent / 'freeze.json')}, root=root)


class ContinuationWorkspace(RobustWorkspace):
    def __init__(self, root, question, world, settings, *, reopen=False):
        settings = deepcopy(settings)
        if 'continuation' not in settings: raise ValueError('explicit frozen continuation configuration required')
        settings['continuation_sources'] = {n: sha(Path(__file__).parent / n) for n in
            ('continuation.py', 'runtime_continuation.py', 'run_continuation.py')}
        self.carryover = None
        super().__init__(root, question, world, settings, reopen=reopen)

    def trials_started(self):
        return super().trials_started() + (self.carryover['inherited_trials'] if self.carryover else 0)

    def attachment_view(self, item):
        result = deepcopy(item)
        for value in result.get('attachments', []):
            path, _ = self.file(value['ref']); value['path'] = str(path)
        return result

    def result_view(self, item):
        view = super().result_view(item)
        view['attachments'] = self.attachment_view(item)['attachments']
        summary = view.get('actual_summary') or {}
        if item['evidence_nature'] == 'record_reconciliation' and {'recorded_total', 'verified_total'} <= summary.keys():
            view['reconciliation_totals'] = {'recorded_units': summary['recorded_total'],
                'implied_stock_outflow_units': summary['verified_total'],
                'difference_units': summary['verified_total'] - summary['recorded_total'],
                'mismatched_rows': summary['mismatched_rows'],
                'meaning': 'Arithmetic of received totals; row count and item count differ. Stock outflow is not independent measurement of sales or latent demand.'}
        return view

    def context(self):
        context = super().context()
        if not self.carryover: return context
        inherited = self.carryover
        # All received original targets of this bounded closing phase remain visible.
        refs = list(dict.fromkeys(context['focus_hypothesis_refs'] + inherited['active_hypothesis_refs']))
        context['hypothesis_cards'] = [self.card(ref) for ref in refs]
        pinned_results = {r['ref'] for r in context['unincorporated_results']}
        for card in context['hypothesis_cards']:
            card['latest_results'] = [({'ref': r['ref'], 'context_entry': 'unincorporated_results',
                'full_record': r['full_record']} if r['ref'] in pinned_results else r) for r in card['latest_results']]
        context['continuation'] = {'parent': inherited['provenance'], 'same_research': True,
            'inherited_responses': inherited['parent_responses'], 'prior_reported_tokens': inherited['prior_reported_tokens'],
            'inherited_trials': inherited['inherited_trials'], 'new_physical_trials_allowed': 0,
            'original_records_unchanged': True,
            'historical_workspace': str(Path(inherited['parent_workspace'])),
            'current_workspace': str(self.root),
            'path_policy': 'Use current attachment paths or read_artifact(file ref). Paths inside original records are historical, never permission to read the parent workspace.',
            'unsaved_work_count': len(inherited['uncheckpointed_work']),
            'unsaved_work_index': {'tool': 'read_memory', 'ref': 'carryover:index'},
            'parent_request_archive': 'read_memory(parent_request:<attempt>), owner only; old process:N and event:N remain available.'}
        context['resources']['global_new_trials_remaining'] = 2 - self.trials_started()
        context['resources']['new_trials_remaining'] = 0
        return context

    def _checked_dispatch(self, name, a, key):
        if name in ('read_artifact', 'read_memory') and (a['ref'] == 'carryover:index' or a['ref'].startswith('parent_request:')):
            if name != 'read_memory': raise ValueError('owner process requires read_memory')
            if a['ref'] == 'carryover:index': item = self.carryover['uncheckpointed_work']
            else:
                match = re.fullmatch(r'parent_request:([1-9][0-9]*)', a['ref'])
                if not match: raise ValueError('received parent request number required')
                attempt = int(match[1])
                if not 1 <= attempt <= self.carryover['parent_local_attempts']: raise ValueError('received parent request number required')
                item = reconstruct_request(self.private / 'parent_run', attempt)
            text = encoded(item); end = a['offset'] + a['limit']
            return {'ref': a['ref'], 'sha256': digest(item), 'text': text[a['offset']:end],
                    'next_offset': end if end < len(text) else None, 'historical_original': True}
        if name == 'run_test':
            plan = self.record(a['plan_ref'], 'plan')
            if plan['mode'] == 'protocol' and plan['protocol']['is_new_sample']:
                raise ValueError('this closing phase allows existing results only; no new physical supply trial')
        return super()._checked_dispatch(name, a, key)


def prepare(workspace, spec, *, root=ROOT):
    config = spec['continuation']; manifest_path = local(root, config['manifest'])
    if sha(manifest_path) != config['sha256']: raise ValueError('frozen continuation manifest changed')
    manifest = read(manifest_path)
    if manifest['format'] != 'research-continuation-v1': raise ValueError('unknown continuation format')
    parent = local(root, manifest['parent_workspace']); verify_files(parent, manifest)
    if snapshot(parent, manifest['provenance'], root=root) != manifest:
        raise ValueError('continuation metadata does not match the stopped parent snapshot')
    identity = workspace.identity; old = manifest['identity']
    for field in ('public_inputs', 'environment_identity', 'question', 'reused_sources'):
        if identity[field] != old[field]: raise ValueError('continuation must preserve parent ' + field)
    for field in ('model_config', 'private_scene_switches'):
        if identity['settings'][field] != old['settings'][field]: raise ValueError('continuation must preserve parent ' + field)
    if identity['settings']['robust_sources']['composed_world.py'] != old['settings']['robust_sources']['composed_world.py']:
        raise ValueError('same-environment continuation cannot change the generator')
    if identity['implementation']['experiments/insight_research/environment.py'] != old['implementation']['experiments/insight_research/environment.py']:
        raise ValueError('same-environment continuation cannot change the environment adapter')
    marker = workspace.db.execute("SELECT value FROM meta WHERE key='continuation_import'").fetchone()
    if marker and marker[0] != config['sha256']: raise ValueError('child already belongs to a different parent snapshot')
    if not marker:
        if workspace.db.execute('SELECT 1 FROM records LIMIT 1').fetchone(): raise ValueError('continuation requires a fresh child workspace')
        for name, version in manifest['sha256'].items():
            source = local(parent, name)
            destination = local(workspace.root, name) if not name.startswith('private/') else local(workspace.private / 'parent_run', name[8:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if sha(destination) != version: raise ValueError('child input differs from parent snapshot: ' + name)
            else: shutil.copyfile(source, destination)
            if name.startswith('private/turns/'):
                active_turn = local(workspace.root, name); active_turn.parent.mkdir(parents=True, exist_ok=True)
                if active_turn.exists() and sha(active_turn) != version: raise ValueError('inherited turn changed')
                if not active_turn.exists(): shutil.copyfile(source, active_turn)
        source = sqlite3.connect((workspace.private / 'parent_run/records.sqlite').as_uri() + '?mode=ro', uri=True)
        try:
            with workspace.db:
                for row in source.execute('SELECT rowid,ref,kind,body FROM records ORDER BY rowid'):
                    workspace.db.execute('INSERT INTO records(rowid,ref,kind,body) VALUES (?,?,?,?)', row)
                for row in source.execute('SELECT ref,path,hash,nature FROM files'):
                    workspace.db.execute('INSERT OR IGNORE INTO files VALUES (?,?,?,?)', row)
                for row in source.execute('SELECT id,operation,body FROM events ORDER BY id'):
                    workspace.db.execute('INSERT INTO events VALUES (?,?,?)', row)
                workspace.db.execute("INSERT OR REPLACE INTO meta VALUES ('continuation_import',?)", (config['sha256'],))
        finally: source.close()
    workspace.carryover = manifest
    # Imported originals and parent process files must stay byte-identical on reopen.
    for name, version in manifest['sha256'].items():
        target = local(workspace.root, name) if not name.startswith('private/') else local(workspace.private / 'parent_run', name[8:])
        if sha(target) != version: raise Pending('imported original changed: ' + name)
        if name.startswith('private/turns/') and sha(local(workspace.root, name)) != version:
            raise Pending('inherited logical response changed')
    workspace.rebuild_index(); workspace._publish()
    with workspace.db:
        for item in workspace.records('result'):
            args = {'plan_ref': item['plan_ref']}; key = 'test:' + item['plan_ref']
            receipt = {**workspace.result_view(item), 'receipt_scope': 'Inherited actual result; full unchanged execution via full_record.'}
            workspace.db.execute('INSERT OR IGNORE INTO operations VALUES (?,?,?,?)',
                (key, digest(['run_test', args]), 'completed', encoded(receipt)))
    # Per-execution worker numbering must continue after copied executions.
    numbers = [int(p.name[4:]) for p in (workspace.science / 'compute/executions').glob('run_*') if p.name[4:].isdigit()]
    workspace.worker.count = max([workspace.worker.count, *numbers])
    write_json(workspace.private / 'continuation.json', manifest)
    checkpoint = workspace.private / 'checkpoint.json'
    if not checkpoint.exists():
        if (workspace.private / 'transport.json').exists(): raise Pending('child transport exists without its checkpoint')
        write_json(checkpoint, {'status': 'pending', 'reason': 'new continuation phase, same research', 'messages': [],
            'pending': None, 'responses': manifest['parent_responses'], 'context_windows': 0, 'transport_failures': 0})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--parent-study', required=True)
    parser.add_argument('--run-id', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); output = local(ROOT, args.output)
    if output.exists(): raise ValueError('manifest already exists')
    value = registered_snapshot(args.parent_study, args.run_id)
    write_json(output, value); print(encoded({'files': len(value['sha256']), 'manifest_sha256': sha(output)}))
