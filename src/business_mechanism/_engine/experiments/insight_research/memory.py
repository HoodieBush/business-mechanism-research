"""Hypothesis cards, incremental research knowledge and scoped retrieval.

The immutable scientific records remain authoritative. Cards are derived views;
knowledge is explicitly attributed researcher interpretation, never ground truth.
Indexes/status tables rebuild from append-only records and tool events.
"""
from __future__ import annotations
from copy import deepcopy
import json
import re
import sqlite3
import uuid
from .common import Pending, digest, encoded, now, sha, write_json
from .contracts_memory import TOOLS, schemas
from .workspace import Workspace


def terms(query):
    words = re.findall(r'[a-zA-Z_][a-zA-Z_0-9]*|[\u4e00-\u9fff]+', query.casefold())
    expanded = []
    for word in words:
        if re.fullmatch(r'[\u4e00-\u9fff]+', word) and len(word) > 4:
            expanded.extend(word[i:i+3] for i in range(len(word)-2))
        elif len(word) >= 2: expanded.append(word)
    return list(dict.fromkeys(expanded))[:32]


def file_refs(value):
    if isinstance(value, str) and value.startswith('file:'): yield value
    elif isinstance(value, dict):
        for v in value.values(): yield from file_refs(v)
    elif isinstance(value, list):
        for v in value: yield from file_refs(v)


class MemoryWorkspace(Workspace):
    tools = TOOLS

    def tool_schemas(self): return schemas()

    def __init__(self, root, question, world, settings, *, reopen=False):
        settings = deepcopy(settings)
        settings['research_memory_profile'] = 'hypothesis_cards_v1'
        from pathlib import Path
        settings['memory_sources'] = {n: sha(Path(__file__).parent / n) for n in
                                     ('memory.py', 'contracts_memory.py', 'runtime_memory.py')}
        super().__init__(root, question, world, settings, reopen=reopen)
        self.db.executescript('''
            CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
            CREATE TABLE IF NOT EXISTS hypothesis_status(ref TEXT PRIMARY KEY,status TEXT,reason TEXT);
            CREATE TABLE IF NOT EXISTS incorporated(ref TEXT PRIMARY KEY,state_ref TEXT);
            CREATE TABLE IF NOT EXISTS card_notes(ref TEXT PRIMARY KEY,state_ref TEXT,note TEXT);
            CREATE TABLE IF NOT EXISTS knowledge_current(ref TEXT PRIMARY KEY,superseded_by TEXT);
            CREATE TABLE IF NOT EXISTS search_docs(ref TEXT PRIMARY KEY,kind TEXT,status TEXT,text TEXT,seq INTEGER);
            CREATE INDEX IF NOT EXISTS docs_kind_status ON search_docs(kind,status,seq);
            CREATE TABLE IF NOT EXISTS doc_hypotheses(ref TEXT,hypothesis_ref TEXT,PRIMARY KEY(ref,hypothesis_ref));
            CREATE INDEX IF NOT EXISTS docs_hypothesis ON doc_hypotheses(hypothesis_ref,ref);
            CREATE TABLE IF NOT EXISTS doc_tags(ref TEXT,tag TEXT,PRIMARY KEY(ref,tag));
            CREATE INDEX IF NOT EXISTS docs_tag ON doc_tags(tag,ref);
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(ref UNINDEXED,text,tokenize='trigram');
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,operation TEXT UNIQUE,body TEXT);
            CREATE INDEX IF NOT EXISTS events_tool_id ON events(json_extract(body,'$.tool'),id);
            CREATE TABLE IF NOT EXISTS event_files(event_id INTEGER,file_ref TEXT,PRIMARY KEY(event_id,file_ref));
            CREATE INDEX IF NOT EXISTS events_file ON event_files(file_ref,event_id);
            CREATE TABLE IF NOT EXISTS retrievals(attempt INTEGER PRIMARY KEY,body TEXT);
        ''')
        indexed = self.db.execute("SELECT count(*) FROM search_docs WHERE kind!='process'").fetchone()[0]
        original = self.db.execute('SELECT count(*) FROM records').fetchone()[0]
        if indexed != original: self.rebuild_index()

    def rebuild_index(self):
        """One explicit/startup pass from originals; never invoked per request."""
        with self.db:
            for table in ('search_docs', 'memory_fts', 'doc_hypotheses', 'doc_tags',
                          'hypothesis_status', 'incorporated', 'card_notes', 'knowledge_current', 'event_files'):
                self.db.execute('DELETE FROM ' + table)
            for ref, kind, text in self.db.execute('SELECT ref,kind,body FROM records ORDER BY rowid'):
                body = json.loads(text)
                related = [ref] if kind == 'hypothesis' else body.get('hypothesis_refs', [])
                if body.get('hypothesis_ref'): related = [body['hypothesis_ref']]
                self.index(ref, kind, body, related, body.get('tags', []))
                if kind == 'hypothesis': self.db.execute('INSERT INTO hypothesis_status VALUES (?,"new","")', (ref,))
                elif kind == 'knowledge':
                    self.db.execute('INSERT INTO knowledge_current VALUES (?,NULL)', (ref,))
                    if body.get('supersedes_ref'): self.db.execute('UPDATE knowledge_current SET superseded_by=? WHERE ref=?', (ref, body['supersedes_ref']))
                elif kind == 'state':
                    for h in body['active_hypothesis_refs']: self.db.execute('UPDATE hypothesis_status SET status="active",reason="" WHERE ref=?', (h,))
                    for h, reason in body['inactive_hypotheses'].items():
                        if h not in body['active_hypothesis_refs']: self.db.execute('UPDATE hypothesis_status SET status="paused",reason=? WHERE ref=?', (reason, h))
                    for r in body['incorporated_result_refs']: self.db.execute('INSERT OR IGNORE INTO incorporated VALUES (?,?)', (r, ref))
                    for h, note in body.get('hypothesis_notes', {}).items(): self.db.execute('INSERT OR REPLACE INTO card_notes VALUES (?,?,?)', (h, ref, note))
            for number, text in self.db.execute('SELECT id,body FROM events ORDER BY id'):
                body = json.loads(text); args = body['arguments']; ref = 'event:' + str(number)
                self.index(ref, 'process', {'purpose': args.get('purpose', body['tool']), 'statement': args.get('question', ''),
                    'tags': args.get('used_memory_refs', [])}, body['hypothesis_refs'])
                self.db.execute('UPDATE search_docs SET seq=? WHERE ref=?', (number, ref))
                for source in set(file_refs(body['result'])):
                    self.db.execute('INSERT OR IGNORE INTO event_files VALUES (?,?)', (number, source))
            # Re-associate analysis that preceded the first hypothesis.
            for ref, text in self.db.execute('SELECT ref,body FROM records WHERE kind="hypothesis"'):
                for source in json.loads(text)['evidence_refs']:
                    for (event,) in self.db.execute('SELECT event_id FROM event_files WHERE file_ref=?', (source,)):
                        self.db.execute('INSERT OR IGNORE INTO doc_hypotheses VALUES (?,?)', ('event:' + str(event), ref))

    def _publish(self):
        saved = self.db.execute('SELECT value FROM meta WHERE key="published_sequence"').fetchone()
        cursor = int(saved[0]) if saved else 0
        for seq, ref, body in self.db.execute('SELECT rowid,ref,body FROM records WHERE rowid>? ORDER BY rowid', (cursor,)):
            path = self.science / 'records' / (ref + '.json')
            if path.exists() and json.loads(path.read_text()) != json.loads(body):
                raise Pending('published record changed; inspect immutable archive')
            if not path.exists(): write_json(path, json.loads(body))
            cursor = seq
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('published_sequence', str(cursor)))

    def state(self):
        row = self.db.execute('SELECT body FROM records WHERE kind="state" ORDER BY rowid DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def report(self):
        row = self.db.execute('SELECT body FROM records WHERE kind="report" ORDER BY rowid DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None

    def index(self, ref, kind, body, hypotheses=(), tags=()):
        # Store only search-bearing text. Code, raw thoughts and large outputs
        # are linked originals, never rescanned at every retrieval.
        fields = ('statement', 'scope', 'prediction', 'falsification', 'alternatives', 'analysis',
                  'rationale', 'understanding', 'recent_change', 'next_action', 'research_use', 'purpose', 'tags')
        text = encoded({k: body[k] for k in fields if k in body})
        if kind == 'result':
            execution = body['actual_execution']
            text += encoded(execution.get('summary', {})) + execution.get('stdout', '')[:2048]
        seq = self.db.execute('SELECT rowid FROM records WHERE ref=?', (ref,)).fetchone()
        self.db.execute('INSERT OR REPLACE INTO search_docs VALUES (?,?,?,?,?)',
                        (ref, kind, body.get('status', ''), text, seq[0] if seq else 0))
        self.db.execute('DELETE FROM memory_fts WHERE ref=?', (ref,))
        self.db.execute('INSERT INTO memory_fts(ref,text) VALUES (?,?)', (ref, text))
        for h in hypotheses:
            self.db.execute('INSERT OR IGNORE INTO doc_hypotheses VALUES (?,?)', (ref, h))
        for tag in tags:
            self.db.execute('INSERT OR IGNORE INTO doc_tags VALUES (?,?)', (ref, tag.casefold()))

    def add(self, kind, body):
        if kind == 'knowledge':
            ref = 'K' + uuid.uuid4().hex[:16]
            item = {'ref': ref, 'record_type': kind, 'created_at': now(), 'author': 'researcher', **body}
            self.db.execute('INSERT INTO records VALUES (?,?,?)', (ref, kind, encoded(item)))
        else: item = super().add(kind, body)
        ref = item['ref']
        related = [ref] if kind == 'hypothesis' else body.get('hypothesis_refs', [])
        if body.get('hypothesis_ref'): related = [body['hypothesis_ref']]
        self.index(ref, kind, item, related, body.get('tags', []))
        if kind == 'hypothesis':
            self.db.execute('INSERT INTO hypothesis_status VALUES (?,?,?)', (ref, 'new', ''))
            # Link pre-hypothesis exploration to this hypothesis through its
            # actual file citations, including a query's receipt and output.
            for source in body['evidence_refs']:
                for (event,) in self.db.execute('SELECT event_id FROM event_files WHERE file_ref=?', (source,)):
                    self.db.execute('INSERT OR IGNORE INTO doc_hypotheses VALUES (?,?)', ('event:' + str(event), ref))
        return item

    def unincorporated(self):
        return [json.loads(r[0]) for r in self.db.execute('''SELECT r.body FROM records r
            LEFT JOIN incorporated i ON i.ref=r.ref WHERE r.kind='result' AND i.ref IS NULL ORDER BY r.rowid''')]

    def checkpoint_work(self):
        """Bounded navigation to work not yet followed by a saved interpretation.

        A checkpoint is not proof that the researcher understood the work. It
        prevents silently discarding its only working account before a hypothesis
        exists; original source/analysis events always remain independently readable.
        """
        saved = self.db.execute('''SELECT id FROM events
            WHERE json_extract(body,'$.tool')='update_research_state'
            AND json_extract(body,'$.result.ref') IS NOT NULL ORDER BY id DESC LIMIT 1''').fetchone()
        frontier = saved[0] if saved else 0
        tools = ('read_artifact', 'query_data', 'run_python', 'save_hypothesis',
                 'register_test', 'run_test', 'record_assessment')
        marks = ','.join('?' for _ in tools)
        rows = self.db.execute('SELECT id,body FROM events WHERE json_extract(body,\'$.tool\') IN ('
            + marks + ') AND id>? ORDER BY id DESC LIMIT 7', [*tools, frontier]).fetchall()
        items = []
        for number, body in rows[:6]:
            event = json.loads(body)
            items.append({'event_ref': 'event:' + str(number), 'tool': event['tool'],
                'evidence_refs': list(dict.fromkeys(file_refs(event['result'])))[:8]})
        return {'pending': bool(rows), 'recent_work': items, 'more_work_available': len(rows) > 6,
                'meaning': 'Research activity since the last saved state; not a scientific conclusion or proof of understanding.'}

    def references(self, refs):
        for ref in refs:
            if ref.startswith('card:'): self.record(ref[5:], 'hypothesis')
            else: super().references([ref])

    def linked(self, hypothesis_ref, kind, limit=3, status=None):
        clauses = ['l.hypothesis_ref=?', 'd.kind=?']; params = [hypothesis_ref, kind]
        if status: clauses.append('d.status=?'); params.append(status)
        rows = self.db.execute('SELECT d.ref FROM search_docs d JOIN doc_hypotheses l ON l.ref=d.ref WHERE '
            + ' AND '.join(clauses) + ' ORDER BY d.seq DESC LIMIT ?', [*params, limit])
        return [self.record(r[0]) for r in rows]

    def counts(self, hypothesis_ref):
        return dict(self.db.execute('''SELECT d.kind,count(*) FROM search_docs d JOIN doc_hypotheses l ON l.ref=d.ref
            WHERE l.hypothesis_ref=? GROUP BY d.kind''', (hypothesis_ref,)))

    def result_view(self, item):
        execution = item['actual_execution']
        return {k: item[k] for k in ('ref', 'plan_ref', 'hypothesis_ref', 'ok', 'evidence_nature')} | {
            'actual_summary': execution.get('summary'), 'stdout_preview': execution.get('stdout', '')[:3000],
            'stdout_preview_only': len(execution.get('stdout', '')) > 3000 or execution.get('stdout_truncated', False),
            'error': execution.get('error', execution.get('stderr', ''))[:1000],
            'full_record': {'tool': 'read_memory', 'ref': item['ref']},
            'submitted_source': execution.get('submitted_source')}

    def card(self, hypothesis_ref):
        h = self.record(hypothesis_ref, 'hypothesis')
        status = self.db.execute('SELECT status,reason FROM hypothesis_status WHERE ref=?', (hypothesis_ref,)).fetchone()
        notes = self.db.execute('SELECT note,state_ref FROM card_notes WHERE ref=?', (hypothesis_ref,)).fetchone()
        judgments = []
        # Preserve a visible opposing/uncertain judgment even if the most recent
        # assessment claims support. All conditions remain in the paged archive.
        for verdict in ('supported', 'refuted', 'unresolved'):
            judgments.extend(self.linked(hypothesis_ref, 'assessment', 1, verdict))
        return {'ref': 'card:' + hypothesis_ref, 'record_type': 'card', 'original_hypothesis': h,
            'research_status': status[0], 'defer_reason': status[1],
            'working_note': {'text': notes[0], 'source_state': notes[1]} if notes else None,
            'latest_assessments_by_status': judgments,
            'latest_results': [self.result_view(x) for x in self.linked(hypothesis_ref, 'result', 2)],
            'archive_counts': self.counts(hypothesis_ref),
            'coverage': 'Recent representatives, not the complete evidence history. Consult the scoped index before judging all evidence.',
            'full_process': {'tool': 'search_memory', 'kind': 'process', 'hypothesis_ref': hypothesis_ref},
            'all_tests_and_evidence': {'tool': 'search_memory', 'hypothesis_ref': hypothesis_ref},
            'parent_card': 'card:' + h['parent_ref'] if h.get('parent_ref') else None}

    def knowledge_view(self, ref):
        item = self.record(ref, 'knowledge')
        source_state = 'current'
        invalid = []
        for source in item['evidence_refs'] + item['counterevidence_refs']:
            try: self.references([source])
            except (ValueError, Pending): invalid.append(source); source_state = 'needs_review'
        return {**item, 'source_state': source_state, 'changed_source_refs': invalid,
                'certification': 'attributed research memory, not automatically certified scientific truth'}

    def knowledge_filter(self):
        return ''

    def search(self, query='', kind='all', hypothesis_ref=None, tags=None, status=None, offset=0, limit=8):
        if hypothesis_ref: self.record(hypothesis_ref, 'hypothesis')
        words = terms(query)
        joins = ''; where = []; params = []
        if words:
            # Trigram FTS cannot match a two-character Chinese word. Exact
            # indexed tags cover short terms; longer text uses FTS candidates.
            long = [t for t in words if len(t) >= 3]
            candidates = []
            if long:
                candidates.append('d.ref IN (SELECT ref FROM memory_fts WHERE memory_fts MATCH ?)')
                params.append(' OR '.join('"' + t.replace('"', '""') + '"' for t in long))
            candidates.append('EXISTS(SELECT 1 FROM doc_tags q WHERE q.ref=d.ref AND q.tag IN (' + ','.join('?' for _ in words) + '))')
            params.extend(words)
            where.append('(' + ' OR '.join(candidates) + ')')
        if kind == 'all': where.append("d.kind!='process'")
        else: where.append('d.kind=?'); params.append('hypothesis' if kind == 'card' else kind)
        if hypothesis_ref:
            where.append('EXISTS(SELECT 1 FROM doc_hypotheses l WHERE l.ref=d.ref AND l.hypothesis_ref=?)'); params.append(hypothesis_ref)
        if status: where.append('d.status=?'); params.append(status)
        if tags:
            where.append('EXISTS(SELECT 1 FROM doc_tags t WHERE t.ref=d.ref AND t.tag IN (' + ','.join('?' for _ in tags) + '))')
            params.extend(t.casefold() for t in tags)
        # Superseded knowledge stays readable by its exact original ref.
        where.append("(d.kind!='knowledge' OR EXISTS(SELECT 1 FROM knowledge_current k WHERE k.ref=d.ref AND k.superseded_by IS NULL))")
        if self.knowledge_filter(): where.append(self.knowledge_filter())
        clause = ' FROM search_docs d ' + joins + ' WHERE ' + ' AND '.join(where)
        total = self.db.execute('SELECT count(*)' + clause, params).fetchone()[0]
        order = 'd.seq DESC'
        rows = self.db.execute('SELECT d.ref,d.kind,d.status,d.text' + clause + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', [*params, limit, offset])
        hits = [{'ref': 'card:' + ref if kind == 'card' else ref, 'kind': 'card' if kind == 'card' else typ,
                 'recorded_status': state, 'preview': text[:800]} for ref, typ, state, text in rows]
        return {'hits': hits, 'total': total, 'next_offset': offset + limit if total > offset + limit else None,
                'scope': {'study': 'current lawful workspace only', 'hypothesis_ref': hypothesis_ref, 'tags': tags or [],
                          'query': query, 'raw_model_thoughts_searched': False}, 'method': 'SQLite indexed relations + FTS5 trigram candidates, newest first; rank is not truth'}

    def context(self):
        state = self.state()
        outstanding = self.unincorporated()
        focus = list((state or {}).get('focus_hypothesis_refs', []))
        if not focus:
            row = self.db.execute("SELECT ref FROM hypothesis_status WHERE status!='paused' ORDER BY rowid DESC LIMIT 1").fetchone()
            focus = [row[0]] if row else []
        # Newly registered hypotheses are announced by paged index, and the
        # current one enters focus; no full historical hypothesis registry.
        new_count = self.db.execute('SELECT count(*) FROM hypothesis_status WHERE status="new"').fetchone()[0]
        required_h = list(dict.fromkeys(focus + [r['hypothesis_ref'] for r in outstanding]))
        critical = []
        for ref in (state or {}).get('counterevidence_refs', []):
            item = {'ref': ref} if ref.startswith('file:') else self.record(ref)
            critical.append(self.result_view(item) if item.get('record_type') == 'result' else item)
        current = {k: v for k, v in (state or {}).items() if k not in
                   ('inactive_hypotheses', 'hypothesis_notes', 'knowledge_updates', 'knowledge_refs', 'known_hypothesis_frontier')}
        query = ' '.join([self.question, (state or {}).get('question', ''), (state or {}).get('next_action', '')])
        knowledge = []
        for h in focus:
            knowledge.extend(x['ref'] for x in self.search(kind='knowledge', hypothesis_ref=h, limit=6)['hits'])
        knowledge.extend(x['ref'] for x in self.search(query=query, kind='knowledge', limit=6)['hits'])
        fallback = not knowledge
        if fallback:
            knowledge.extend(x['ref'] for x in self.search(kind='knowledge', limit=3)['hits'])
        selected = []; used_bytes = 0
        for ref in dict.fromkeys(knowledge):
            entry = self.knowledge_view(ref); size = len(encoded(entry).encode())
            if used_bytes + size <= self.settings['limits'].get('knowledge_context_bytes', 7000):
                selected.append(entry); used_bytes += size
        local_path = self.private / 'transport.json'
        local = json.loads(local_path.read_text()) if local_path.exists() else {}
        files = [{'ref': ref, 'path': path} for ref, path in
                 self.db.execute('SELECT ref,path FROM files WHERE nature="public_seen" ORDER BY path')]
        recent = []
        for number, body in self.db.execute('SELECT id,body FROM events ORDER BY id DESC LIMIT 6'):
            event = json.loads(body); result = event['result']
            if event['tool'] not in ('query_data', 'run_python', 'read_artifact', 'read_memory'): continue
            preview = result.get('text', '')[:800]
            if event['tool'] == 'query_data': preview = encoded(result.get('preview', []))[:800]
            if event['tool'] == 'run_python': preview = result.get('execution', {}).get('stdout', '')[:800]
            recent.append({'event_ref': 'event:' + str(number), 'tool': event['tool'],
                'purpose': event['arguments'].get('purpose', ''), 'source_ref': event['arguments'].get('ref'),
                'next_offset': result.get('next_offset'), 'preview': preview, 'preview_only': True})
        return {'research_profile': 'insight_research_v1', 'verification_mode': 'self',
            'research_memory_profile': 'hypothesis_cards_v1', 'original_question': self.question,
            'state': current or None, 'focus_hypothesis_refs': focus,
            'hypothesis_cards': [self.card(h) for h in required_h],
            'unincorporated_results': [self.result_view(r) for r in outstanding], 'critical_counterevidence': critical,
            'new_hypotheses_pending_state': {'count': new_count, 'index': {'tool': 'search_memory', 'kind': 'card'}},
            'research_knowledge': selected, 'memory_selection': {'query': query, 'selected_refs': [x['ref'] for x in selected],
                'required_refs': ['card:' + h for h in required_h] + [r['ref'] for r in outstanding],
                'optional_candidates': len(set(knowledge)), 'optional_bytes': used_bytes,
                'latest_entries_fallback': fallback,
                'why': 'Exact focused hypothesis links, then current question lexical retrieval; full process is available by scoped index.'},
            'public_files': files, 'archive_counts': dict(self.db.execute('SELECT kind,count(*) FROM records GROUP BY kind')),
            'recent_process_navigation': recent,
            'public_file_paths': 'Relative to workspace; sandbox Python uses the PUBLIC_DIR environment variable.',
            'permissions': {'read_only': [str(self.public), str(self.science)], 'python_write': 'current WORK_DIR only',
                'private_process': 'owner read_memory only; no other studies, private truth or evaluator files'},
            'resources': {'settings': self.settings['limits'], 'new_trials_remaining': 2-self.trials_started(),
                'local_accounted_tokens': local.get('accounted_tokens', 0), 'http_attempts_started': local.get('attempts', 0)},
            'interpretation': 'Cards and memory are research aids; actual source, scope, counterevidence and statistical validity still require review.'}

    def update_state(self, a):
        active = set(a['active_hypothesis_refs'])
        for ref in active | set(a['inactive_hypotheses']) | set(a['hypothesis_notes']): self.record(ref, 'hypothesis')
        if not set(a['focus_hypothesis_refs']) <= active: raise ValueError('focus must be an active received hypothesis')
        for ref in a['incorporated_result_refs']: self.record(ref, 'result')
        self.references(a['alternative_refs'] + a['evidence_refs'] + a['counterevidence_refs'] + a['used_memory_refs'])
        missing = {r[0] for r in self.db.execute("SELECT ref FROM hypothesis_status WHERE status IN ('active','new')")} - active
        if missing - set(a['inactive_hypotheses']): raise ValueError('explicit reasons required for newly deferred hypotheses')
        if any(not reason.strip() for reason in a['inactive_hypotheses'].values()): raise ValueError('nonempty deferral reason required')
        pending = {r['hypothesis_ref'] for r in self.unincorporated() if r['ref'] not in a['incorporated_result_refs']}
        if pending - active: raise ValueError('incorporate outstanding results before deferral')
        knowledge = []
        for entry in a['knowledge_updates']:
            item = self.save_knowledge(entry)
            if item is not None: knowledge.append(item['ref'])
        # Only this delta is archived. Current dispositions live in a derived,
        # rebuildable table rather than being copied into every state version.
        body = {k: v for k, v in a.items() if k != 'knowledge_updates'}
        body['knowledge_refs'] = knowledge
        body['known_hypothesis_frontier'] = self.db.execute('SELECT coalesce(max(rowid),0) FROM records WHERE kind="hypothesis"').fetchone()[0]
        saved = self.add('state', body)
        for ref in active: self.db.execute('UPDATE hypothesis_status SET status="active",reason="" WHERE ref=?', (ref,))
        for ref, reason in a['inactive_hypotheses'].items():
            if ref not in active: self.db.execute('UPDATE hypothesis_status SET status="paused",reason=? WHERE ref=?', (reason, ref))
        for ref in a['incorporated_result_refs']: self.db.execute('INSERT OR IGNORE INTO incorporated VALUES (?,?)', (ref, saved['ref']))
        for ref, note in a['hypothesis_notes'].items(): self.db.execute('INSERT OR REPLACE INTO card_notes VALUES (?,?,?)', (ref, saved['ref'], note))
        # The next fixed context supplies the current interpretation. Keep a
        # small receipt here rather than duplicating all of it in tool history.
        return {'ref': saved['ref'], 'record_type': 'state', 'knowledge_refs': knowledge,
                'focus_hypothesis_refs': a['focus_hypothesis_refs'],
                'incorporated_result_refs': a['incorporated_result_refs'],
                'readback': {'tool': 'read_memory', 'ref': saved['ref']}}

    def save_knowledge(self, entry):
        """One claim. The baseline caller retains its original batch transaction."""
        self.references(entry['evidence_refs'] + entry['counterevidence_refs'])
        for ref in entry['hypothesis_refs']: self.record(ref, 'hypothesis')
        if entry['status'] in ('supported_in_scope', 'refuted'):
            target = 'supported' if entry['status'] == 'supported_in_scope' else 'refuted'
            matching = [self.record(r) for r in entry['evidence_refs'] if not r.startswith(('file:', 'card:'))]
            if not any(x.get('record_type') == 'assessment' and x.get('status') == target for x in matching):
                raise ValueError('scientific memory status requires a matching actual assessment; tentative remains available')
        if entry['status'] == 'provided':
            if entry['kind'] != 'provided_rule' or not all(r.startswith('file:') and self.file(r)[1] == 'public_seen' for r in entry['evidence_refs']):
                raise ValueError('provided memory requires received public source files')
        parent = entry['supersedes_ref']
        if parent:
            self.record(parent, 'knowledge')
            row = self.db.execute('SELECT superseded_by FROM knowledge_current WHERE ref=?', (parent,)).fetchone()
            if not row or row[0] or not entry['revision_reason'].strip(): raise ValueError('supersede a current memory with a concrete revision reason')
        item = self.add('knowledge', entry)
        self.db.execute('INSERT INTO knowledge_current VALUES (?,NULL)', (item['ref'],))
        if parent: self.db.execute('UPDATE knowledge_current SET superseded_by=? WHERE ref=?', (item['ref'], parent))
        return item

    def event(self, key, name, args, result):
        if self.db.execute('SELECT 1 FROM events WHERE operation=?', (key,)).fetchone(): return
        focused = (self.state() or {}).get('focus_hypothesis_refs', [])
        related = [args['hypothesis_ref']] if args.get('hypothesis_ref') else focused
        if name == 'run_test': related = [self.record(args['plan_ref'])['hypothesis_ref']]
        if name == 'save_hypothesis' and result.get('ref'): related = [result['ref']]
        body = {'tool': name, 'arguments': args, 'result': result, 'created_at': now(), 'hypothesis_refs': related}
        body['model_response_ref'] = getattr(self, 'response_ref', None)
        cursor = self.db.execute('INSERT INTO events(operation,body) VALUES (?,?)', (key, encoded(body)))
        ref = 'event:' + str(cursor.lastrowid)
        self.index(ref, 'process', {'purpose': args.get('purpose', name), 'statement': args.get('question', ''),
                   'tags': args.get('used_memory_refs', [])}, related)
        self.db.execute('UPDATE search_docs SET seq=? WHERE ref=?', (cursor.lastrowid, ref))
        for source in set(file_refs(result)):
            self.db.execute('INSERT OR IGNORE INTO event_files VALUES (?,?)', (cursor.lastrowid, source))

    def call(self, name, args, operation_id):
        result = super().call(name, args, operation_id)
        # Also repair an error event if the process died after its durable
        # rejection receipt but before the owner process index was committed.
        key = 'test:' + args['plan_ref'] if name == 'run_test' else operation_id
        with self.db: self.event(key, name, args, result)
        return result

    def dispatch(self, name, a, key):
        self.references(a.get('used_memory_refs', []))
        if name == 'update_research_state': result = self.update_state(a)
        elif name == 'search_memory': result = self.search(**a)
        elif name in ('read_memory', 'read_artifact') and a['ref'].startswith(('card:', 'event:')):
            if name != 'read_memory': raise ValueError('memory views/process require owner read_memory interface')
            ref = a['ref']
            if ref.startswith('card:'): item = self.card(ref[5:])
            else:
                try: number = int(ref[6:])
                except ValueError: raise ValueError('received event reference required')
                row = self.db.execute('SELECT body FROM events WHERE id=?', (number,)).fetchone()
                if not row: raise ValueError('received event reference required')
                item = json.loads(row[0])
            text = encoded(item); end = a['offset'] + a['limit']
            result = {'ref': ref, 'sha256': digest(item), 'text': text[a['offset']:end], 'next_offset': end if end < len(text) else None}
        else: result = super().dispatch(name, a, key)
        self.event(key, name, a, result)
        return result
