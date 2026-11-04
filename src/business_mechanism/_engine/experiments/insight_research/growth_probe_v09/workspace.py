"""Continue a registered chronological history without copying it as facts.

Originals are cached once from authenticated received catalogs for bounded
navigation. Archive reads still authenticate files. Imported field decisions
remain attributed owner interpretations; they can be scientifically wrong.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from ..common import Pending, digest, encoded, sha
from ..critic_v01.shared import lifecycle
from ..memory import terms
from ..growth_probe_v08.workspace import ResearchWorkspace as Previous


class ResearchWorkspace(Previous):
    def __init__(self, root, question, world, settings, **kwargs):
        self.received_history_rows = []
        self.received_history_lookup = {}
        self.received_history_lifecycle = {}
        self.imported_revision_rejections = []
        settings = deepcopy(settings)
        settings['multi_stage_history_source'] = sha(Path(__file__))
        super().__init__(root, question, world, settings, **kwargs)
        descriptors = self.archive_descriptors()
        ids = [d['stage_id'] for d in descriptors]
        if len(ids) != len(set(ids)):
            raise ValueError('Received chronological archive stage IDs must be unique.')
        for stage_index, descriptor in enumerate(descriptors):
            stage = descriptor['stage_id']
            view = self.archive_view(stage)
            try:
                rows = [(seq, json.loads(body)) for seq, body in view.db.execute(
                    "SELECT seq,body FROM docs WHERE kind IN ('hypothesis','plan','result','assessment','knowledge','state') ORDER BY seq")]
                for seq, record in rows:
                    key = (stage, record['ref'])
                    self.received_history_rows.append((stage_index, stage, seq, record))
                    self.received_history_lookup[key] = record
                    self.received_history_lifecycle[key] = view.review(record['ref'])
            finally:
                view.close()
        # Current rows are positive sequence numbers. Received rows are older
        # and follow the explicitly registered chronological archive order.
        with self.db:
            for stage_index, stage, seq, record in self.received_history_rows:
                if record['record_type'] != 'state':
                    continue
                origin = 'archive:' + stage + ':' + record['ref']
                for action in record.get('historical_field_reviews', []):
                    try:
                        self.validate_received_action(stage, action)
                    except (ValueError, KeyError, TypeError) as error:
                        self.imported_revision_rejections.append({'origin_ref': origin,
                            'source_ref': action.get('source_ref'), 'reason': str(error)})
                        continue
                    rank = (stage_index - len(descriptors) - 1) * 1000000000 + seq
                    self.db.execute('INSERT OR REPLACE INTO historical_field_reviews VALUES (?,?,?,?,?,?)',
                        (action['source_ref'], action['source_version'], action['field'], rank, origin, encoded(action)))

    def validate_received_action(self, origin_stage, action):
        _, original, _ = self.historical_original(action['source_ref'])
        if digest(original) != action['source_version']:
            raise ValueError('Imported source original_version mismatch; action not applied.')
        if action['field'] not in ('statement', 'scope', 'research_use'):
            raise ValueError('Unsupported imported text field.')
        if action['original_field_sha256'] != digest(original[action['field']]):
            raise ValueError('Imported original field differs.')
        if action['decision'] not in ('retain', 'replace', 'withdraw'):
            raise ValueError('Unsupported imported decision.')
        if action['decision'] == 'replace' and not action.get('replacement_text', '').strip():
            raise ValueError('Imported replacement has no text.')
        view = self.archive_view(origin_stage)
        try:
            source, _ = view.file(action['received_source_file_ref'])
            receipt = json.loads(source.read_text())
            if receipt.get('ref') != action['source_ref'] or receipt.get('original_version') != action['source_version']:
                raise ValueError('Imported revision does not bind its actual received original.')
        finally:
            view.close()

    def historical_original(self, ref):
        match = re.fullmatch(r'archive:([A-Za-z0-9_-]{1,80}):(K[A-Za-z0-9]+)', ref)
        key = (match[1], match[2]) if match else None
        if key not in self.received_history_lookup:
            return super().historical_original(ref)
        record = deepcopy(self.received_history_lookup[key])
        body = {'ref': ref, 'original': record, 'original_version': digest(record),
            'lifecycle': deepcopy(self.received_history_lifecycle[key]), 'already_seen': True, 'scientific_certification': False}
        return match[1], record, body

    def field_actions(self, source_ref, version):
        latest = {}
        if not self.historical_reviews_ready:
            return latest
        rows = self.db.execute('SELECT field,body,state_ref FROM historical_field_reviews '
            'WHERE source_ref=? AND source_version=? ORDER BY state_seq DESC', (source_ref, version))
        for field, body, ref in rows:
            if field in latest:
                continue
            imported = ref.startswith('archive:')
            if imported:
                _, stage, old_ref = ref.split(':', 2)
                status = self.received_history_lifecycle.get((stage, old_ref), {})
            else:
                status = lifecycle(self.db, ref)
            # Explicit withdrawal/quarantine of a revision must take effect.
            # Mere dependency questions remain visible; they do not silently
            # invalidate an unrelated field decision or certify it correct.
            if status.get('status', 'active') != 'active':
                continue
            action = json.loads(body)
            if imported:
                evidence = action.pop('evidence_refs', [])
                action['original_evidence_refs'] = evidence
                action['evidence_read_refs'] = ['archive:' + stage + ':' + r for r in evidence]
                action['original_received_source_file_ref'] = action.pop('received_source_file_ref')
            latest[field] = {**action, 'revision_ref': ref,
                'revision_read_ref': ref if imported else 'original:' + ref,
                'revision_lifecycle': status, 'imported_from_received_stage': imported,
                'scientific_certification': False}
        return latest

    def tool_schemas(self):
        tools = super().tool_schemas()
        for tool in tools:
            if tool['function']['name'] == 'update_research_state':
                definition = tool['function']['parameters']['$defs']['HistoricalFieldReview']
                definition['properties']['expected_prior_revision_ref']['description'] = (
                    'Bind the exact revision_ref returned in current_field_view: local S ref or qualified archive:<stage>:<S ref>. Read it before updating.')
        return tools

    def experience_context(self):
        mode = self.settings.get('experience_mode', 'none')
        if mode == 'none':
            if self.archive_descriptors():
                raise ValueError('No-history condition cannot receive archives.')
            return {'mode': mode, 'items': [], 'history_available': False}
        if mode not in ('recent', 'episode') or not self.archive_descriptors():
            raise ValueError('Explicit history mode and received chronological archives required.')
        rows = self.received_history_rows
        if mode == 'recent':
            selected = [(stage, r) for _, stage, _, r in reversed(rows) if r['record_type'] == 'knowledge'][:3]
            selection = {'rule': 'Most recent3nativeK in registered chronological stages; no truth/efficacy filter.'}
        else:
            hypotheses = [(stage, r) for _, stage, _, r in rows if r['record_type'] == 'hypothesis']
            query = set(terms(self.question))
            tokens = {(stage, r['ref']): set(w for field in ('statement', 'prediction', 'falsification', 'scope', 'tags')
                for w in terms(encoded(r.get(field, '')))) for stage, r in hypotheses}
            scores = {key: sum(1 + math.log((len(hypotheses) + 1) / (1 + sum(t in ts for ts in tokens.values())))
                for t in query & value) for key, value in tokens.items()}
            selected = []
            if hypotheses:
                stage, h = max(hypotheses, key=lambda x: scores[(x[0], x[1]['ref'])])
                selected = [(stage, h)]
                for kind in ('assessment', 'result'):
                    linked = [r for _, s, _, r in rows if s == stage and r['record_type'] == kind and r.get('hypothesis_ref') == h['ref']]
                    if linked:
                        selected.append((stage, linked[-1]))
            selection = {'rule': 'Same question-text H match then same-stage latestA/R, across received chronological stages.', 'query_terms': sorted(query)}
        items, used = [], 0
        for stage, record in selected:
            ref = 'archive:' + stage + ':' + record['ref']
            version = digest(record)
            item = {'ref': ref, 'record_type': record['record_type'], 'original_version': version,
                'source_lifecycle': self.received_history_lifecycle[(stage, record['ref'])],
                'source_review_status': self.source_status(stage, record['ref']),
                'historical_not_current_fact': True, 'full_original_read_ref': ref}
            view = self.effective_historical_view(ref, version)
            if view:
                item['current_field_view'] = view
            elif len(encoded(record).encode()) <= 1800:
                item['original'] = deepcopy(record)
            else:
                item['preview_only'] = True
                item['preview'] = {k: str(record[k])[:360] for k in ('statement', 'scope', 'prediction', 'falsification', 'rationale', 'status') if k in record}
                if record['record_type'] == 'result':
                    item['preview']['stdout'] = record['actual_execution'].get('stdout', '')[:700]
                item['instruction'] = 'Preview incomplete; read exact original before using scientific content.'
            if used + len(encoded(item).encode()) > 6144:
                item = {k: item[k] for k in ('ref', 'record_type', 'original_version', 'full_original_read_ref')}
                if view:
                    item['current_revision_read_refs'] = sorted({v['revision_read_ref'] for v in view['field_revisions'].values()})
                item['instruction'] = 'Read original and current revisions before reliance; all originals remain available.'
            size = len(encoded(item).encode())
            if used + size > 6144:
                raise Pending('Critical received-history revision navigation exceeds fixed6KBcap; no source silently certified/dropped.')
            items.append(item)
            used += size
        return {'mode': mode, 'items': items, 'automatic_context_bytes': used, 'automatic_context_cap': 6144,
            'selection': selection, 'received_stage_order': [d['stage_id'] for d in self.archive_descriptors()],
            'common_scope': 'Earlier native scoped observations, errors and owner interpretations; neither old labels nor field decisions are current scientific truth.',
            'citation': 'Read archive ref, cite its returned materialized file; imported revision evidence_read_refs are qualified received history, not current-file IDs.',
            'revision_lookup': 'Local revision text indexes ordinary current search; received states/source files remain readable through their archive_stage. Original archive keyword matching is unchanged.'}

    def context(self):
        out = super().context()
        out['history_import_status'] = {'received_stages': len(self.archive_descriptors()),
            'indexed_received_scientific_records': len(self.received_history_rows),
            'unapplied_revision_inputs': self.imported_revision_rejections[:8],
            'unapplied_total': len(self.imported_revision_rejections),
            'scope': 'Finite authenticated chronology cached once, bounded prompt navigation; not scalable lifelong memory efficacy or scientific validation.'}
        if len(encoded(out).encode()) > self.settings['execution_policy']['active_context_bytes']:
            raise Pending('Bounded research navigation plus exact history-import status exceeds current view; full sources retained.')
        return out
