"""Explicit copy-only upgrade from a verified bundle of the same pinned engine.

Only drained workspaces using the exact same pinned engine are compatible.
Original identities/code are archived; scientific records and charges stay exact.
"""
from contextlib import ExitStack
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
from experiments.insight_research.common import digest, now, write_json
from .data_jobs import file_hash


def _rows(path, table):
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
        return db.execute('SELECT * FROM "'+table+'" ORDER BY rowid').fetchall()


def _sources(package):
    return {p.name: file_hash(p) for p in sorted(package.glob('*.py'))}


def migrate_project_copy(source, destination, *, baseline_package, event_id, retain_invalid_paid_reference=False):
    """Create a paused upgraded copy. Does not start or pay for any model call.

    baseline_package must be the actual installed old business_mechanism folder,
    matching every old public source hash and the unchanged engine manifest.
    A failed/incomplete migration remains fenced and is never opened as a run.
    """
    from .engine import ResearchWorkspace, Reviewer, source_identity
    from .service import open_project
    source = Path(source).resolve(); dest = Path(destination).resolve()
    baseline = Path(baseline_package).resolve()
    if not event_id or len(event_id) > 100 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in event_id):
        raise ValueError('Safe nonempty migration event_id required')
    if dest.exists() or dest.is_relative_to(source) or source.is_relative_to(dest):
        raise ValueError('New destination outside original project required')
    project = json.loads((source/'project.json').read_text())
    if (source/'migration_incomplete.json').exists():
        raise ValueError('source_migration_incomplete')
    if _sources(baseline) != project['source_identity']:
        raise ValueError('baseline_source_mismatch: supply the exact original installed package')
    current = Path(__file__).parent
    if json.loads((baseline/'engine_manifest.json').read_text()) != json.loads((current/'engine_manifest.json').read_text()):
        raise ValueError('unsupported_engine_migration: no algorithm/source rebinding permitted')
    manifest = json.loads((baseline/'engine_manifest.json').read_text())['files']
    for relative, version in manifest.items():
        if file_hash(baseline/'_engine'/relative) != version:
            raise ValueError('baseline_engine_integrity_failed')
    with ExitStack() as stack:
        private_roots = [source/'researcher/private', *sorted(source.glob('reviews/*/critic/private'))]
        locks = [source/'service.lock', source/'research_run.lock',
                 *[p/'runtime.lock' for p in private_roots if (p/'runtime.lock').exists()]]
        for path in locks:
            stream = stack.enter_context(path.open('a'))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('migration_requires_paused_workspace: another owner is active') from None
        checkpoints = [p/'checkpoint.json' for p in private_roots if (p/'checkpoint.json').exists()]
        retained_pending = []
        for path in checkpoints:
            cp = json.loads(path.read_text()); pending = cp.get('pending')
            if not pending: continue
            if not retain_invalid_paid_reference or path != source/'researcher/private/checkpoint.json':
                raise ValueError('migration_requires_drained_paid_tools')
            calls = pending['calls']
            if pending['cursor'] != 0 or len(calls) != 1 or calls[0]['name'] != 'run_test':
                raise ValueError('migration_pending_recovery_only_single_invalid_run_test')
            ref = calls[0]['args'].get('plan_ref')
            with sqlite3.connect((source/'researcher/private/records.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                row = db.execute('SELECT kind FROM records WHERE ref=?',(ref,)).fetchone()
            if row and row[0] == 'plan': raise ValueError('migration_pending_plan_is_valid: drain with its pinned version')
            number = cp['responses']; attempt = cp.get('delivered_attempt')
            raw = json.loads((path.parent/'turns'/f'{number}.json').read_text())
            http = json.loads((path.parent/'http'/f'{attempt}.json').read_text())
            transport = json.loads((path.parent/'transport.json').read_text())
            wire_calls = raw['choices'][0]['message']['tool_calls']
            if (pending['response'] != number or transport['attempts'] != attempt or http.get('response') != raw
                    or len(wire_calls) != 1 or wire_calls[0]['id'] != calls[0]['id']
                    or wire_calls[0]['function']['name'] != 'run_test'
                    or json.loads(wire_calls[0]['function']['arguments']) != calls[0]['args']):
                raise ValueError('migration_pending_original_paid_response_mismatch')
            with sqlite3.connect((source/'common_budget.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                paid = db.execute('SELECT status FROM attempts WHERE key=?',(digest(['researcher',attempt]),)).fetchone()
            if not paid or paid[0] not in ('settled','unknown'): raise ValueError('migration_pending_paid_ledger_required')
            retained_pending.append({'source_response':number,'source_attempt':attempt,'original_response_hash':digest(raw),
                'original_call':calls[0],'action':'Retain exact paid batch for typed input rejection under the new wrapper; no plan substitution, no HTTP or computation.'})
        for path in [p/'transport.json' for p in private_roots if (p/'transport.json').exists()]:
            http = json.loads(path.read_text())
            if http.get('inflight') or http.get('delivery'):
                raise ValueError('migration_requires_acknowledged_transport: keep unknown reserves and recover with old version first')
        # Symlinks can reach outside the snapshot. Fail instead of traversing
        # arbitrary external paths or sharing writable inodes with the old run.
        if any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError('migration_external_symlink_unsupported')
        dest.mkdir(parents=True)
        fence = dest/'migration_incomplete.json'
        write_json(fence, {'event_id': event_id, 'source': str(source), 'started_at': now()})
        shutil.copytree(source, dest, dirs_exist_ok=True)
        audit = dest/'migrations'/event_id; audit.mkdir(parents=True)
        shutil.copytree(baseline, audit/'baseline_package', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        project_before = deepcopy(project)
        immutable_records = _rows(source/'researcher/private/records.sqlite', 'records')
        budget_tables = ('identity', 'attempts', 'flags', 'execution_control')
        budget_before = {}
        for table in budget_tables:
            try:
                budget_before[table] = _rows(source/'common_budget.sqlite', table)
            except sqlite3.OperationalError:
                pass
        edits = []
        identities = [dest/'researcher/private/identity.json', *sorted(dest.glob('reviews/*/critic/private/identity.json'))]
        for path in identities:
            old = json.loads(path.read_text()); updated = deepcopy(old)
            if 'release_sources' not in old.get('settings', {}):
                raise ValueError('unsupported_workspace_identity: no explicit public source binding')
            cls = Reviewer if 'tool_contract' in old and any(s['function']['name'] == 'record_review' for s in old['tool_contract']) else ResearchWorkspace
            prototype = cls.__new__(cls); prototype.configure_tools()
            updated['tool_contract'] = prototype.tool_schemas()
            updated['settings']['release_sources'] = source_identity()
            if cls is Reviewer:
                updated['settings']['limits'] = deepcopy(project['settings']['limits'])
            else:
                updated['settings']['execution_policy']['review_repair_requests'] = 3
            relative = str(path.relative_to(dest))
            write_json(audit/'identities'/relative, old)
            write_json(path, updated)
            edits.append({'path': relative, 'before_hash': digest(old), 'after_hash': digest(updated),
                          'changed_fields': ['settings.release_sources', 'tool_contract',
                            'settings.limits' if cls is Reviewer else 'settings.execution_policy.review_repair_requests']})
        project['source_identity'] = source_identity()
        project['settings']['release_sources'] = source_identity()
        project['settings']['execution_policy']['review_repair_requests'] = 3
        project['migration'] = {'event_id': event_id, 'source': str(source), 'at': now(),
                                'original_source_identity': project_before['source_identity']}
        write_json(audit/'original_project.json', project_before)
        write_json(dest/'project.json', project)
        # Reuse only exact version-bound proofs under unchanged proof code and
        # the same current contract. Legacy coverage-free opinions stay archived.
        with sqlite3.connect(dest/'researcher/private/records.sqlite') as db:
            copied_clearances = db.execute('SELECT * FROM clearances').fetchall()
        old_clearances=[]; retained_clearances=[]; proof_rechecks=[]
        _, _, proof_ws, _ = open_project(dest, _migration_validation=True)
        try:
            from .workflow import review_contract,recheck_saved_coverage
            proof_code_unchanged=all((baseline/name).is_file() and file_hash(baseline/name)==file_hash(current/name)
                for name in ('review_drafts.py','engine.py'))
            with proof_ws.db:
                for entry in copied_clearances:
                    target, version, review_ref=entry
                    review=proof_ws.record(review_ref,'review')
                    coverage=review.get('method_coverage',{})
                    contract=review_contract(proof_ws,target)
                    valid=(proof_code_unchanged and version==digest(proof_ws.record(target))
                        and review.get('target_ref')==target and review.get('target_version')==version
                        and review.get('target_conclusion')=='consistent_in_checked_scope'
                        and coverage.get('clearance_eligible') is True
                        and coverage.get('review_contract')==contract)
                    if valid:
                        try:
                            rechecked=recheck_saved_coverage(proof_ws,review,contract)
                            valid=rechecked['clearance_eligible']
                        except (ValueError,KeyError,TypeError,OSError) as error:
                            rechecked={'clearance_eligible':False,'error':str(error)};valid=False
                        proof_rechecks.append({'target':target,'review_ref':review_ref,'current_coverage':rechecked,
                            'new_computation_or_observation':False})
                    if valid:retained_clearances.append(entry)
                    else:
                        old_clearances.append(entry)
                        proof_ws.db.execute('DELETE FROM clearances WHERE target=?',(target,))
        finally:proof_ws.close()
        checkpoint_changes = []
        for path in [dest/p.relative_to(source) for p in checkpoints]:
            cp = json.loads(path.read_text())
            write_json(audit/'checkpoints'/path.relative_to(dest), cp)
            old_hash = digest(cp)
            if cp.get('messages'):
                from .prompts import compose
                role = 'researcher' if path.is_relative_to(dest/'researcher') else 'critic'
                if cp['messages'][0].get('role') == 'system':
                    cp['messages'][0]['content'] = compose(role)
                cp['messages'].append({'role': 'user', 'content': json.dumps({
                    'explicit_migration_event': event_id, 'new_project_root': str(dest),
                    'policy': 'Original records, predictions, costs and deadline are retained. Re-read file refs for current compute paths. Old clearances need component coverage; migration is not new evidence.'})})
                write_json(path, cp)
                checkpoint_changes.append({'path': str(path.relative_to(dest)), 'before_hash': old_hash,
                                           'after_hash': digest(cp), 'active_role_instructions_updated': True})
        if _rows(dest/'researcher/private/records.sqlite', 'records') != immutable_records:
            raise ValueError('migration_scientific_records_changed')
        for table, rows in budget_before.items():
            if _rows(dest/'common_budget.sqlite', table) != rows:
                raise ValueError('migration_budget_or_deadline_changed: '+table)
        receipt = {'event_id': event_id, 'completed_at': now(), 'source': str(source), 'destination': str(dest),
                   'original_source_identity': project_before['source_identity'], 'new_source_identity': source_identity(),
                   'identity_changes': edits, 'scientific_records_preserved': len(immutable_records),
                   'checkpoint_changes': checkpoint_changes,
                   'retained_invalid_paid_batches': retained_pending,
                   'all_budget_rows_and_original_deadline_preserved': True,
                   'legacy_clearances_invalidated': old_clearances, 'external_provider_calls': 0,
                   'exact_current_clearances_retained': retained_clearances,
                   'saved_proof_rechecks': proof_rechecks,
                   'limitations': 'Same pinned engine and drained transport only. Original absolute paths remain historical evidence; resolve current paths via file refs. No automatic execution or authorization extension.'}
        write_json(audit/'receipt.json', receipt)
        write_json(dest/'pause_requested.json', {'at': now(), 'reason': 'Migrated copy awaits explicit resume; original experiment is unchanged.'})
        # Only remove the fence after an actual reopen has validated every
        # native identity. open_project accepts this fence only for validation.
        _, _, ws, _ = open_project(dest, _migration_validation=True)
        ws.close()
        fence.unlink()
        return receipt
