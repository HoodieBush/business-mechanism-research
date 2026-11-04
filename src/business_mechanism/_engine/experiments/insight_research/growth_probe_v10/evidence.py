"""Versioned projection accepts genuine field-revision states, never disguises them as K.

Export/file/privacy/transaction guards are reused verbatim from paired_v01;
only the legitimate target kind and explicit changed-field navigation expand.
"""
import json,fcntl,shutil,sqlite3
from pathlib import Path
from ..common import Pending,digest,encoded,now,sha,write_json
from ..critic_v01.shared import lifecycle
from ..paired_v01.evidence import SEARCH_FIELDS,filtered_action,EvidenceView

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
    target = owner.record(target_ref)
    if target['record_type'] not in ('assessment', 'knowledge', 'report_draft') and not (target['record_type']=='state' and target.get('historical_field_reviews')):
        raise ValueError('Assessment, knowledge, report draft or actual historical-field revision state required')
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
        if kind == 'review_action':
            operation = item['operation']
            text += encoded({'tool': operation['tool'], 'purpose': operation['arguments'].get('purpose', '')})
        if kind in ('review','review_note','review_response','review_action'):
            review = {**review, 'eligible_as_current_premise': False,
                'certification': 'Attributed review/operation record, not scientific truth.'}
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
        focus = set(target.get('hypothesis_refs', target.get('all_hypothesis_refs', target.get('active_hypothesis_refs', []))))
        if target.get('hypothesis_ref'): focus.add(target['hypothesis_ref'])
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
                if field=='evidence_refs':
                    values = list(values) + [r for a in item.get('historical_field_reviews',[]) for r in a.get('evidence_refs',[])]
                if isinstance(values, str): values = [values]
                for value in values:
                    if value.startswith('card:'): value = value[5:]
                    if value not in related and value in originals:
                        related.add(value); pending.append(value)
        related.add(target_ref)
        result_refs = sorted(r for r in related if view.record(r)['record_type'] == 'result')
        packet = {'format': 'critic_packet_v1', 'target_ref': target_ref,
            'target_version': originals[target_ref], 'candidate_record': target, 'target_kind': target['record_type'],
            'original_hypotheses': [hypotheses[h] for h in sorted(focus) if h in hypotheses],
            'related_hypothesis_refs': sorted(focus),
            'related_records': {'count': len(related), 'index_ref': 'directory:related'},
            'all_related_received_results': {'count': len(result_refs), 'index_ref': 'directory:results'},
            'public_files': view.public_files(),
            'path_policy': 'Original receipts preserve original paths. Use read_artifact(ref) for the current compute_path, or PUBLIC_DIR and ARTIFACT_DIR; owner private paths are not mounted.',
            'history_search': 'Full lawful corpus, including unlinked/old/withdrawn/replaced knowledge; results are not truth.',
            'original_question': owner.question,
            'unlinked_scope': 'Automatic links use hypothesis lineage and explicit citations. Search other lawful records independently.',
            'evidence_semantics': 'All exposed history is seen; review computation is not a new independent sample.'}
        if target.get('historical_field_reviews'):
            contrasts=[]
            for action in target['historical_field_reviews']:
                path,_=owner.file(action['received_source_file_ref'])
                original=json.loads(path.read_text())['original']
                contrasts.append({'source_ref':action['source_ref'],'source_version':action['source_version'],
                    'field':action['field'],'old_text':original[action['field']],
                    'decision':action['decision'],'candidate_text':action['replacement_text'],
                    'original_file_ref':action['received_source_file_ref'],'evidence_refs':action['evidence_refs'],
                    'scientific_certification':False})
            packet['field_revision_contrasts']=contrasts
            packet['field_review_instruction']='Review the actual candidate state fields and their source scope, not only a numerically correct related assessment. Identify exact affected state/version/field in each issue. Owner may preserve correct parts, revise, rebut or retain uncertainty; review text is not fact.'
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
