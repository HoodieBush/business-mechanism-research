"""Export a lawful, frozen evidence projection, not an owner's private runtime.

The caller supplies an already authorized workspace. No generator/settings,
raw model messages, transport logs, root audits or unregistered files are copied.
"""
import json
import fcntl
import shutil
import sqlite3
from pathlib import Path

from ..common import Pending, digest, encoded, now, sha, write_json
from ..memory import file_refs, terms
from .shared import lifecycle

SEARCH_FIELDS = ('statement', 'scope', 'prediction', 'falsification', 'alternatives',
    'analysis', 'rationale', 'understanding', 'recent_change', 'next_action',
    'research_use', 'purpose', 'tags')
FACT_TOOLS = frozenset(('query_data', 'run_python', 'save_hypothesis', 'register_test',
    'run_test', 'record_assessment', 'update_research_state', 'finish_research'))


def filtered_action(number, event):
    tool = event['tool']
    # Read/search replies can contain an embedded owner process response. Never
    # copy their text, preview or recursive reply into the critic projection.
    if tool in FACT_TOOLS:
        result = event['result']
    else:
        result = {k: event['result'][k] for k in ('ok', 'ref', 'sha256', 'next_offset', 'error') if k in event['result']}
        result['artifact_refs'] = sorted(set(file_refs(event['result'])))
        result['content_omitted'] = 'Read the referenced lawful original, not an embedded owner conversation.'
    return {'ref': 'action:' + str(number), 'record_type': 'action', 'tool': tool,
        'arguments': event['arguments'], 'result': result,
        'hypothesis_refs': event.get('hypothesis_refs', []), 'created_at': event.get('created_at')}


def export_snapshot(owner, destination, target_ref):
    if owner.db.in_transaction: raise ValueError('commit owner transaction before exporting evidence')
    lock = (owner.private / 'runtime.lock').open('a')
    try:
        try: fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError: raise Pending('owner is running; stop and drain it before evidence export')
        for name in ('transport.json', 'checkpoint.json'):
            p = owner.private / name
            item = json.loads(p.read_text()) if p.exists() else {}
            if item.get('inflight') or item.get('delivery') or item.get('pending'):
                raise Pending('owner has undrained paid work; recover it before evidence export')
        if owner.db.execute("SELECT 1 FROM operations WHERE status!='completed' LIMIT 1").fetchone():
            raise Pending('owner has a prepared operation; recover it before evidence export')
        owner.db.execute('BEGIN')
        try: return _export_snapshot(owner, destination, target_ref)
        finally: owner.db.rollback()
    finally: lock.close()


def _export_snapshot(owner, destination, target_ref):
    target = owner.record(target_ref, 'assessment')
    destination = Path(destination).resolve()
    if destination.is_relative_to(owner.root) or owner.root.is_relative_to(destination):
        raise ValueError('evidence projection must be outside the owner workspace')
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'public').mkdir(); (destination / 'science').mkdir()
    catalog = sqlite3.connect(destination / 'catalog.sqlite')
    catalog.executescript('''
        CREATE TABLE docs(ref TEXT PRIMARY KEY,kind TEXT,body TEXT,text TEXT,status TEXT,lifecycle TEXT,seq INTEGER);
        CREATE INDEX docs_kind_status ON docs(kind,status,seq);
        CREATE INDEX docs_lifecycle ON docs(lifecycle,seq);
        CREATE TABLE links(ref TEXT,hypothesis TEXT,PRIMARY KEY(ref,hypothesis));
        CREATE INDEX links_hypothesis ON links(hypothesis,ref);
        CREATE TABLE tags(ref TEXT,tag TEXT,PRIMARY KEY(ref,tag));
        CREATE INDEX tags_tag ON tags(tag,ref);
        CREATE VIRTUAL TABLE fts USING fts5(ref UNINDEXED,text,tokenize='trigram');
        CREATE TABLE lifecycle(ref TEXT PRIMARY KEY,body TEXT);
        CREATE TABLE files(ref TEXT PRIMARY KEY,path TEXT,hash TEXT,nature TEXT);
    ''')
    files = {}
    originals = {}
    hypotheses = {}

    def add(item, seq, review):
        ref, kind = item['ref'], item['record_type']
        text = encoded({k: item[k] for k in SEARCH_FIELDS if k in item})
        if kind == 'result':
            execution = item['actual_execution']
            text += encoded(execution.get('summary', {})) + execution.get('stdout', '')[:2048]
        if kind == 'action':
            text += encoded({'tool': item['tool'], 'purpose': item['arguments'].get('purpose', '')})
        catalog.execute('INSERT INTO docs VALUES (?,?,?,?,?,?,?)',
            (ref, kind, encoded(item), text, item.get('status', ''), review['status'], seq))
        catalog.execute('INSERT INTO lifecycle VALUES (?,?)', (ref, encoded(review)))
        catalog.execute('INSERT INTO fts VALUES (?,?)', (ref, text))
        related = [ref] if kind == 'hypothesis' else item.get('hypothesis_refs', [])
        if item.get('hypothesis_ref'): related = [item['hypothesis_ref']]
        for h in set(related): catalog.execute('INSERT OR IGNORE INTO links VALUES (?,?)', (ref, h))
        for tag in set(item.get('tags', [])):
            catalog.execute('INSERT OR IGNORE INTO tags VALUES (?,?)', (ref, tag.casefold()))

    try:
        with catalog:
            for ref, path, version, nature in owner.db.execute('SELECT ref,path,hash,nature FROM files ORDER BY path'):
                source, _ = owner.file(ref)  # Enforces received path and current hash.
                relative = source.relative_to(owner.root)
                if relative.parts[0] not in ('public', 'science'): raise ValueError('non-public source in file manifest')
                copied = destination / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                if copied.exists():
                    if sha(copied) != version: raise Pending('conflicting versions at the same received path')
                else: shutil.copyfile(source, copied)
                if sha(copied) != version: raise Pending('source changed while projecting evidence')
                catalog.execute('INSERT INTO files VALUES (?,?,?,?)', (ref, str(relative), version, nature))
                files[str(relative)] = version
            # All public inputs must be received, including the real dictionary
            # and source observer needed by the unchanged sandbox launcher.
            for name, version in owner.identity['public_inputs'].items():
                if files.get('public/' + name) != version: raise ValueError('missing received public source: ' + name)
            for seq, ref, body in owner.db.execute('SELECT rowid,ref,body FROM records ORDER BY rowid'):
                item = owner.record(ref)
                add(item, seq, lifecycle(owner.db, ref))
                originals[ref] = digest(item)
                if item['record_type'] == 'hypothesis': hypotheses[ref] = item
            for number, body in owner.db.execute('SELECT id,body FROM events ORDER BY id'):
                item = filtered_action(number, json.loads(body))
                add(item, number, {'status': 'active', 'eligible_as_current_premise': False,
                    'certification': 'Operation facts, not an additional observation.'})
    finally:
        catalog.close()
    files['catalog.sqlite'] = sha(destination / 'catalog.sqlite')
    write_json(destination / 'manifest.json', {'format': 'lawful_evidence_projection_v1',
        'created_at': now(), 'files_sha256': files, 'record_original_versions': originals,
        'excluded': ['private model messages', 'private transport', 'generator/settings',
            'root audits/scoring', 'unregistered files'],
        'scope': 'Same received world; immutable evidence projection, not new scientific observations.'})
    view = EvidenceView(destination)
    try:
        focus = {target['hypothesis_ref']}
        changed = True
        while changed:
            changed = False
            for ref, h in hypotheses.items():
                parent = h.get('parent_ref')
                if parent and (ref in focus or parent in focus):
                    before = len(focus); focus.update((ref, parent)); changed |= len(focus) != before
        related = set()
        for h in focus:
            related.update(x[0] for x in view.db.execute('SELECT ref FROM links WHERE hypothesis=?', (h,)))
        # Add explicit records cited by the target/related records recursively;
        # file refs remain navigable through the received-file directory.
        pending = list(related | {target_ref})
        while pending:
            ref = pending.pop()
            item = view.record(ref)
            for field in ('evidence_refs', 'counterevidence_refs', 'result_refs', 'data_refs', 'assessment_refs', 'plan_ref'):
                values = item.get(field, [])
                if isinstance(values, str): values = [values]
                for value in values:
                    if value.startswith('card:'): value = value[5:]
                    if value not in related and value in originals:
                        related.add(value); pending.append(value)
        related.add(target_ref)
        result_refs = sorted(r for r in related if view.record(r)['record_type'] == 'result')
        packet = {'format': 'critic_packet_v1', 'target_ref': target_ref,
            'target_version': originals[target_ref], 'candidate_assessment': target,
            'original_hypothesis': hypotheses[target['hypothesis_ref']],
            'related_hypothesis_refs': sorted(focus),
            'related_records': {'count': len(related), 'index_ref': 'directory:related'},
            'all_related_received_results': {'count': len(result_refs), 'index_ref': 'directory:results'},
            'public_files': view.public_files(),
            'path_policy': 'Original receipts preserve original paths. Use read_artifact(ref) for the current compute_path, or PUBLIC_DIR and ARTIFACT_DIR; owner private paths are not mounted.',
            'history_search': 'Full lawful corpus, including unlinked/old/withdrawn/replaced knowledge; results are not truth.',
            'original_question': owner.question,
            'unlinked_scope': 'Automatic links use hypothesis lineage and explicit citations. Search other lawful records independently.',
            'evidence_semantics': 'All exposed history is seen; review computation is not a new independent sample.'}
        directories = {'related': sorted(related), 'results': result_refs,
            'all': [x[0] for x in view.db.execute('SELECT ref FROM docs ORDER BY seq,ref')]}
        write_json(destination / 'directories.json', directories)
        write_json(destination / 'packet.json', packet)
    finally: view.close()
    manifest = json.loads((destination / 'manifest.json').read_text())
    for name in ('directories.json', 'packet.json'): manifest['files_sha256'][name] = sha(destination / name)
    write_json(destination / 'manifest.json', manifest)
    return {'snapshot': str(destination), 'manifest_sha256': sha(destination / 'manifest.json'),
        'packet_sha256': sha(destination / 'packet.json'), 'target_ref': target_ref}


class EvidenceView:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.manifest = json.loads((self.root / 'manifest.json').read_text())
        for name, expected in self.manifest['files_sha256'].items():
            p = (self.root / name).resolve()
            if not p.is_relative_to(self.root) or not p.is_file() or sha(p) != expected:
                raise Pending('evidence projection file changed: ' + name)
        self.db = sqlite3.connect((self.root / 'catalog.sqlite').as_uri() + '?mode=ro', uri=True)

    def close(self): self.db.close()

    def record(self, ref):
        row = self.db.execute('SELECT body FROM docs WHERE ref=?', (ref,)).fetchone()
        if not row: raise ValueError('received scientific record or action reference required')
        return json.loads(row[0])

    def review(self, ref):
        row = self.db.execute('SELECT body FROM lifecycle WHERE ref=?', (ref,)).fetchone()
        if not row: raise ValueError('received record required')
        return json.loads(row[0])

    def file(self, ref):
        row = self.db.execute('SELECT path,hash,nature FROM files WHERE ref=?', (ref,)).fetchone()
        if not row: raise ValueError('received file reference required')
        path = (self.root / row[0]).resolve()
        if not path.is_relative_to(self.root) or sha(path) != row[1]: raise Pending('received source changed')
        return path, row[2]

    def public_files(self):
        return [{'ref': r, 'path': str(self.root / p), 'sha256': h, 'nature': n}
            for r, p, h, n in self.db.execute("SELECT ref,path,hash,nature FROM files WHERE path LIKE 'public/%' ORDER BY path")]

    def search(self, query='', kind='all', hypothesis_ref=None, status=None, lifecycle_status=None, offset=0, limit=8):
        clauses = ['1']; params = []
        words = terms(query)
        if query.strip() and not words:
            return {'hits': [], 'total': 0, 'next_offset': None, 'query_notice': 'Use a searchable term of at least two characters.'}
        if words:
            parts = []; long = [w for w in words if len(w) >= 3]
            if long:
                parts.append('d.ref IN (SELECT ref FROM fts WHERE fts MATCH ?)')
                params.append(' OR '.join('"' + w.replace('"', '""') + '"' for w in long))
            parts.append('d.ref IN (SELECT ref FROM tags WHERE tag IN (' + ','.join('?' for _ in words) + '))')
            params.extend(words); clauses.append('(' + ' OR '.join(parts) + ')')
        if kind != 'all': clauses.append('d.kind=?'); params.append(kind)
        if hypothesis_ref:
            if self.record(hypothesis_ref)['record_type'] != 'hypothesis': raise ValueError('hypothesis reference required')
            clauses.append('d.ref IN (SELECT ref FROM links WHERE hypothesis=?)'); params.append(hypothesis_ref)
        if status is not None: clauses.append('d.status=?'); params.append(status)
        if lifecycle_status is not None: clauses.append('d.lifecycle=?'); params.append(lifecycle_status)
        where = ' FROM docs d WHERE ' + ' AND '.join(clauses)
        total = self.db.execute('SELECT count(*)' + where, params).fetchone()[0]
        rows = self.db.execute('SELECT ref,kind,status,text' + where + ' ORDER BY seq DESC,ref LIMIT ? OFFSET ?', [*params, limit, offset])
        return {'hits': [{'ref': r, 'kind': k, 'recorded_status': s, 'preview': t[:800], 'lifecycle': self.review(r)} for r, k, s, t in rows],
            'total': total, 'next_offset': offset + limit if total > offset + limit else None,
            'scope': 'Full lawful projected corpus; no lifecycle exclusion; explicit hypothesis filter does not include unlinked knowledge.',
            'method': 'SQLite relation/tag indexes and FTS5 trigram candidates; ranking is not truth.'}
