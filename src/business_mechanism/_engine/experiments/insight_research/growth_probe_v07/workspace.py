"""Keep historical originals while applying explicit owner field revisions.

The appended state is authoritative; one derived index lives in the existing
workspace database. Actions are not scientific clearance. This version covers
received K records and current-workspace recovery, not arbitrary archive chains.
"""
from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Literal
from pydantic import Field

from ..common import digest, encoded, sha
from ..contracts import Input
from ..paired_v16.contracts import schemas
from ..growth_probe_v06.workspace import ResearchWorkspace as Previous


class HistoricalFieldReview(Input):
    source_ref: str = Field(description='Exact received archive:<stage>:<K ref>, read the original first.')
    source_version: str = Field(pattern='^[0-9a-f]{64}$', description='original_version of that old scientific record, not a wrapper/file hash.')
    field: Literal['statement', 'scope', 'research_use']
    decision: Literal['retain', 'replace', 'withdraw']
    replacement_text: str | None = None
    expected_prior_revision_ref: str | None = Field(default=None, description='Current field revision S ref, if one exists; stale updates are rejected.')
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1, max_length=16)


class UpdateState(Previous.tools['update_research_state'][0]):
    historical_field_reviews: list[HistoricalFieldReview] = Field(default_factory=list, max_length=8,
        description='Optional explicit scoped field revisions of already-read historical K. Keep correct fields; evidence and reason required. Originals remain readable; no scientific certification or inherited clearance.')


class ResearchWorkspace(Previous):
    tools = {**Previous.tools, 'update_research_state': (UpdateState,
        Previous.tools['update_research_state'][1] + ' historical_field_reviews can retain, replace or withdraw exact-version historical K text fields; not automatic truth. Read old original and current revision first.')}

    def __init__(self, root, question, world, settings, **kwargs):
        self.historical_reviews_ready = False
        settings = deepcopy(settings)
        settings['historical_field_review_source'] = sha(Path(__file__))
        super().__init__(root, question, world, settings, **kwargs)
        self.db.executescript('''CREATE TABLE IF NOT EXISTS historical_field_reviews(
            source_ref TEXT,source_version TEXT,field TEXT,state_seq INTEGER,state_ref TEXT,body TEXT,
            PRIMARY KEY(source_ref,source_version,field,state_ref));
            CREATE INDEX IF NOT EXISTS historical_field_lookup ON historical_field_reviews(source_ref,source_version,field,state_seq DESC);''')
        self.historical_reviews_ready = True
        # Rebuild both derived indices/impact flags in chronological order.
        # This also replays explicit later acknowledgements of valid children.
        with self.db:
            self.db.execute('DELETE FROM historical_field_reviews')
            self._rebuild_reviews()

    def tool_schemas(self):
        tools = super().tool_schemas()
        updated = schemas({'update_research_state': self.tools['update_research_state']})[0]
        return [updated if t['function']['name'] == 'update_research_state' else t for t in tools]

    def historical_original(self, ref):
        match = re.fullmatch(r'archive:([A-Za-z0-9_-]{1,80}):(K[A-Za-z0-9]+)', ref)
        if not match:
            raise ValueError('Received archive:<stage>:<K ref> required; only historical knowledge text fields are supported.')
        view = self.archive_view(match[1])
        try:
            record = view.record(match[2])
            if record['record_type'] != 'knowledge':
                raise ValueError('Historical field review supports knowledge originals only.')
            body = {'ref': ref, 'original': record, 'original_version': digest(record),
                'lifecycle': view.review(match[2]), 'already_seen': True, 'scientific_certification': False}
            return match[1], record, body
        finally:
            view.close()

    def field_actions(self, source_ref, version):
        latest = {}
        if not self.historical_reviews_ready:
            return latest
        rows = self.db.execute('SELECT field,body,state_ref FROM historical_field_reviews '
            'WHERE source_ref=? AND source_version=? ORDER BY state_seq DESC', (source_ref, version))
        for field, body, state_ref in rows:
            if field not in latest:
                latest[field] = {**json.loads(body), 'revision_ref': state_ref,
                    'revision_read_ref': 'original:' + state_ref}
        return latest

    def validate_field_review(self, action):
        stage, record, body = self.historical_original(action['source_ref'])
        version = digest(record)
        if action['source_version'] != version:
            raise ValueError('Historical original_version mismatch; read the exact scientific original, not its file/wrapper hash.')
        original_path = self.science / 'project_history' / stage / 'records' / (digest(body) + '.json')
        row = self.db.execute('SELECT ref FROM files WHERE path=?', (str(original_path.relative_to(self.root)),)).fetchone()
        if row is None:
            raise ValueError('Read this historical original with read_memory first; automatic preview is not full receipt.')
        self.file(row[0])
        if not isinstance(record.get(action['field']), str):
            raise ValueError('The selected text field is absent from this exact historical original.')
        current = self.field_actions(action['source_ref'], version).get(action['field'])
        if action['expected_prior_revision_ref'] != (current['revision_ref'] if current else None):
            raise ValueError(encoded({'error': 'stale historical field revision',
                'current_revision_ref': current['revision_ref'] if current else None,
                'repair': 'Read the current revision and explicitly bind expected_prior_revision_ref; do not overwrite it blindly.'}))
        text = action['replacement_text']
        if action['decision'] == 'replace' and (not isinstance(text, str) or not text.strip()):
            raise ValueError('Replacement requires nonempty replacement_text.')
        if action['decision'] != 'replace' and text is not None:
            raise ValueError('retain/withdraw do not accept replacement_text.')
        self.references(action['evidence_refs'])
        for ref in action['evidence_refs']:
            if not ref.startswith('file:'):
                record_type = self.record(ref)['record_type']
                if record_type in ('review', 'review_note', 'review_response', 'review_action'):
                    raise ValueError('Review opinions are not independent scientific evidence; cite actual sources/calculations.')
        return {**action, 'received_source_file_ref': row[0],
            'original_field_sha256': digest(record[action['field']]),
            'scientific_certification': False}

    def index(self, ref, kind, body, hypotheses=(), tags=()):
        super().index(ref, kind, body, hypotheses, tags)
        if kind == 'state' and body.get('historical_field_reviews'):
            addition = encoded(body['historical_field_reviews'])
            self.db.execute('UPDATE search_docs SET text=text||? WHERE ref=?', (addition, ref))
            text = self.db.execute('SELECT text FROM search_docs WHERE ref=?', (ref,)).fetchone()[0]
            self.db.execute('DELETE FROM memory_fts WHERE ref=?', (ref,))
            self.db.execute('INSERT INTO memory_fts(ref,text) VALUES (?,?)', (ref, text))

    def _index_review(self, item):
        if self.historical_reviews_ready and item['record_type'] == 'state':
            seq = self.db.execute('SELECT rowid FROM records WHERE ref=?', (item['ref'],)).fetchone()[0]
            for action in item.get('historical_field_reviews', []):
                self.db.execute('INSERT OR REPLACE INTO historical_field_reviews VALUES (?,?,?,?,?,?)',
                    (action['source_ref'], action['source_version'], action['field'], seq, item['ref'], encoded(action)))
                if action['decision'] in ('replace', 'withdraw'):
                    # Conservative review queue, not automatic scientific
                    # refutation. A valid child can be explicitly acknowledged
                    # by the ordinary memory_reviews in this or a later state.
                    source = action['received_source_file_ref']
                    self.db.execute('''INSERT OR IGNORE INTO affected
                        WITH RECURSIVE descendants(ref) AS (
                          SELECT child FROM dependencies WHERE parent=? UNION
                          SELECT d.child FROM dependencies d JOIN descendants x ON d.parent=x.ref)
                        SELECT ref,? FROM descendants''', (source, source))
        return super()._index_review(item)

    def _checked_dispatch(self, name, args, key):
        if name == 'update_research_state':
            args = deepcopy(args)
            actions = args.get('historical_field_reviews', [])
            keys = [(a['source_ref'], a['source_version'], a['field']) for a in actions]
            if len(keys) != len(set(keys)):
                raise ValueError('One decision per exact historical field in a checkpoint.')
            args['historical_field_reviews'] = [self.validate_field_review(a) for a in actions]
        return super()._checked_dispatch(name, args, key)

    def effective_historical_view(self, source_ref, version):
        actions = self.field_actions(source_ref, version)
        if not actions:
            return None
        _, original, _ = self.historical_original(source_ref)
        fields = {k: original[k] for k in ('statement', 'scope', 'research_use') if k in original}
        for field, action in actions.items():
            if action['decision'] == 'replace':
                fields[field] = action['replacement_text']
            elif action['decision'] == 'withdraw':
                fields.pop(field, None)
        return {'source_ref': source_ref, 'source_version': version, 'effective_text_fields': fields,
            'field_revisions': actions, 'scientific_certification': False,
            'meaning': 'Explicit current owner field interpretation, not a changed historical original or inherited scientific clearance.'}

    def archive_read(self, args):
        out = super().archive_read(args)
        if re.fullmatch(r'archive:[A-Za-z0-9_-]{1,80}:K[A-Za-z0-9]+', args['ref']):
            _, original, _ = self.historical_original(args['ref'])
            view = self.effective_historical_view(args['ref'], digest(original))
            if view:
                out['current_field_view'] = view
        return out

    def archive_search(self, args):
        out = super().archive_search(args)
        for hit in out['hits']:
            if not re.fullmatch(r'archive:[A-Za-z0-9_-]{1,80}:K[A-Za-z0-9]+', hit['ref']):
                continue
            _, original, _ = self.historical_original(hit['ref'])
            view = self.effective_historical_view(hit['ref'], digest(original))
            if view:
                hit['preview'] = encoded(view['effective_text_fields'])[:800]
                hit['current_field_view'] = view
        return out

    def experience_context(self):
        out = super().experience_context()
        items, used = [], 0
        for item in out['items']:
            view = self.effective_historical_view(item['ref'], item['original_version'])
            if view:
                item = {k: v for k, v in item.items() if k not in ('original', 'preview', 'instruction')}
                item['current_field_view'] = view
                item['historical_original_still_readable'] = True
            size = len(encoded(item).encode())
            if used + size > 6144:
                item = {k: item[k] for k in ('ref', 'record_type', 'original_version', 'full_original_read_ref')}
                item['read_current_revision_before_reliance'] = True
            size = len(encoded(item).encode())
            if used + size <= 6144:
                items.append(item)
                used += size
        return {**out, 'items': items, 'automatic_context_bytes': used,
            'revision_lookup': 'Current field decisions also index into ordinary search_memory (without archive_stage). Archive search matches original text, but returned previews/readback apply current field decisions.',
            'revision_scope': 'Received historical K text fields and current workspace/reopen only. Export/import of these revisions into another new stage is not implemented or certified.'}
