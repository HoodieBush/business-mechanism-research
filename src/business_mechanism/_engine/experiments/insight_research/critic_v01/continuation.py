"""Explicit continuation of an unfinished critic, preserving usage and work.

This is a new registered allocation, never a reopened closed study. Only the
critic's own artifacts/process are copied; no developer assessment is imported.
"""
import fcntl
import json
from pathlib import Path
import shutil
import sqlite3

from ..common import ROOT, Pending, sha, write_json
from .workspace import CriticWorkspace

PRIVATE_FILES = frozenset(('identity.json', 'critic.sqlite', 'checkpoint.json', 'transport.json'))
PRIVATE_DIRS = frozenset(('effects', 'turns', 'http', 'requests'))


def owned(name):
    parts = Path(name).parts
    if not parts or any(p in ('..', 'tmp', '.matplotlib') for p in parts): return False
    if parts[0] == 'artifacts': return True
    return len(parts) >= 2 and parts[0] == 'private' and (
        len(parts) == 2 and parts[1] in PRIVATE_FILES or parts[1] in PRIVATE_DIRS)


def capture(parent, snapshot, new_limits, *, base=ROOT):
    parent, snapshot = Path(parent).resolve(), Path(snapshot).resolve()
    lock = (parent / 'private/runtime.lock').open('rb')
    try:
        try: fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError: raise Pending('critic is running; drain and stop before continuation capture')
        identity = json.loads((parent / 'private/identity.json').read_text())
        cp = json.loads((parent / 'private/checkpoint.json').read_text())
        transport = json.loads((parent / 'private/transport.json').read_text())
        if cp['status'] != 'pending' or cp.get('pending') or transport.get('inflight') or transport.get('delivery'):
            raise Pending('critic has undrained paid work or is not pending')
        if identity['snapshot_manifest_sha256'] != sha(snapshot / 'manifest.json'):
            raise ValueError('continuation must preserve the same evidence projection')
        prior = identity['settings']['limits']
        if new_limits['token_allowance'] != prior['token_allowance']:
            raise ValueError('M0 continuation keeps the original cumulative token ceiling')
        if not prior['max_http_attempts'] < new_limits['max_http_attempts'] <= min(12, prior['max_http_attempts'] + 6):
            raise ValueError('one bounded extension of at most six cumulative HTTP attempts required')
        if any(v != new_limits.get(k) for k, v in prior.items() if k != 'max_http_attempts'):
            raise ValueError('continuation cannot silently change other research resources')
        with sqlite3.connect((parent / 'private/critic.sqlite').as_uri() + '?mode=ro', uri=True) as db:
            if db.execute("SELECT 1 FROM records WHERE kind='review'").fetchone(): raise ValueError('completed review cannot be continued')
        paths = [p for p in parent.rglob('*') if p.is_file() and owned(str(p.relative_to(parent)))]
        if any(p.is_symlink() for p in paths): raise ValueError('critic continuation cannot follow symlinks')
        return {'format': 'critic_continuation_v1', 'parent_root': str(parent.relative_to(base)),
            'snapshot': str(snapshot.relative_to(base)), 'parent_identity': identity,
            'parent_http_attempts': transport['attempts'], 'parent_accounted_tokens': transport['accounted_tokens'],
            'new_limits': new_limits, 'sha256': {str(p.relative_to(parent)): sha(p) for p in paths},
            'scope': 'Same unfinished review and cumulative token ceiling; own paid process only; not a new independent sample.'}
    finally: lock.close()


def prepare(root, snapshot, settings, manifest, *, base=ROOT):
    root, snapshot = Path(root).resolve(), Path(snapshot).resolve()
    base = Path(base).resolve()
    parent = (base / manifest['parent_root']).resolve()
    if not parent.is_relative_to(base) or not snapshot.is_relative_to(base): raise ValueError('registered project paths required')
    if snapshot != (base / manifest['snapshot']).resolve(): raise ValueError('continuation snapshot differs')
    if settings['limits'] != manifest['new_limits']: raise ValueError('continuation resources differ')
    if settings['model_config'] != manifest['parent_identity']['settings']['model_config']:
        raise ValueError('continuation model configuration differs')
    # Revalidate pending state, same source and limits at actual preparation,
    # not only when the manifest was first written.
    received = capture(parent, snapshot, settings['limits'], base=base)
    if received != manifest: raise ValueError('critic parent changed after capture')
    if root == parent or root.is_relative_to(parent) or parent.is_relative_to(root): raise ValueError('new isolated critic root required')
    ws = CriticWorkspace(root, snapshot, settings); ws.close()
    for name, expected in manifest['sha256'].items():
        if not owned(name) or sha(parent / name) != expected: raise ValueError('critic parent file changed')
        destination = root / ('private/parent_identity.json' if name == 'private/identity.json' else name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(parent / name, destination)
        if sha(destination) != expected: raise Pending('critic continuation copy changed')
    transport = json.loads((root / 'private/transport.json').read_text())
    if transport['attempts'] != manifest['parent_http_attempts'] or transport['accounted_tokens'] != manifest['parent_accounted_tokens']:
        raise ValueError('critic continuation reset cumulative usage')
    write_json(root / 'private/continuation.json', {
        'parent_root': manifest['parent_root'], 'inherited_http_attempts': transport['attempts'],
        'inherited_accounted_tokens': transport['accounted_tokens'], 'same_review_not_new_sample': True,
        'remaining_cumulative_tokens': settings['limits']['token_allowance'] - transport['accounted_tokens']})
