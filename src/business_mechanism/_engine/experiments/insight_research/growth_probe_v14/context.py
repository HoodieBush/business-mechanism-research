"""Versioned selector: native method tags only, public query only, same budget."""
from copy import deepcopy
import math
from ..common import digest, encoded
from ..memory import terms
from ..growth_probe_v12.context import reserve_navigation, experience_context as original_experience_context


def experience_context(self):
    if self.settings.get('experience_mode', 'none') != 'episode':
        return original_experience_context(self)
    mode = 'episode'
    rows = self.received_history_rows
    hypotheses = [(stage, r) for _, stage, _, r in rows if r['record_type'] == 'hypothesis']
    query = set(terms(self.question))
    tokens = {(stage, r['ref']): set(w for field in ('statement', 'prediction', 'falsification', 'scope', 'tags')
        for w in terms(encoded(r.get(field, '')))) for stage, r in hypotheses}
    scores = {key: sum(1 + math.log((len(hypotheses) + 1) / (1 + sum(t in ts for ts in tokens.values())))
        for t in query & value) for key, value in tokens.items()}
    def is_method(record):
        return record.get('kind') == 'method' or bool(set(t.casefold() for t in record.get('tags', [])) & {'method', 'research_method', 'procedure', 'research_procedure'})
    methods = [(stage, r) for stage, r in hypotheses if is_method(r) and scores[(stage, r['ref'])] > 0]
    if not methods:
        return original_experience_context(self)
    method_stage, method = max(methods, key=lambda x: scores[(x[0], x[1]['ref'])])
    method_key = (method_stage, method['ref'])
    business = [(stage, r) for stage, r in hypotheses if not is_method(r)]
    selected = [(method_stage, method)]
    if business:
        stage, h = max(business, key=lambda x: scores[(x[0], x[1]['ref'])])
        selected.append((stage, h))
        linked = [r for _, s, _, r in rows if s == stage and r['record_type'] == 'assessment' and r.get('hypothesis_ref') == h['ref']]
        if linked:
            selected.append((stage, linked[-1]))
    else:
        for kind in ('assessment', 'result'):
            linked = [r for _, s, _, r in rows if s == method_stage and r['record_type'] == kind and r.get('hypothesis_ref') == method['ref']]
            if linked:
                selected.append((method_stage, linked[-1]))
    selection = {'rule': 'Native method-tagged H by same public-question match, then business H and latest A; fallback exactly to original selector if no scored method. 3slots/6KB unchanged.',
        'query_terms': sorted(query), 'method_candidate_ref': 'archive:' + method_stage + ':' + method['ref'],
        'scope': 'Method activation and presentation component; native tag/body unchanged, unverified candidate not truth.'}
    candidates = []
    for stage, record in selected:
        ref = 'archive:' + stage + ':' + record['ref']
        version = digest(record)
        item = {'ref': ref, 'record_type': record['record_type'], 'original_version': version,
            'source_lifecycle': self.received_history_lifecycle[(stage, record['ref'])],
            'source_review_status': self.source_status(stage, record['ref']),
            'historical_not_current_fact': True, 'full_original_read_ref': ref}
        view = self.effective_historical_view(ref, version)
        is_method_slot = (stage, record['ref']) == method_key
        if is_method_slot:
            # Full original statement/scope, not a Root summary or recommendation.
            # Detailed bookkeeping stays at the exact original read ref; candidate
            # status is explicit and never inherited as factual clearance.
            item.pop('source_review_status', None)
            item['source_lifecycle'] = {'status': item['source_lifecycle'].get('status', 'unknown'),
                'eligible_as_current_premise': False, 'scientific_certification': False}
            item['method_candidate_only'] = True
            item['projection_only'] = True
            item['native_method_fields'] = {k: deepcopy(record[k]) for k in ('statement', 'scope', 'kind', 'tags') if k in record}
            item['instruction'] = 'Native method candidate, not fact. Read exact original and linked evidence/reviews before relying; full source status available on read.'
        elif view:
            item['current_field_view'] = view
        elif len(encoded(record).encode()) <= 1800:
            item['original'] = deepcopy(record)
        else:
            item['preview_only'] = True
            item['preview'] = {k: str(record[k])[:360] for k in ('statement', 'scope', 'prediction', 'falsification', 'rationale', 'status') if k in record}
            if record['record_type'] == 'result':
                item['preview']['stdout'] = record['actual_execution'].get('stdout', '')[:700]
            item['instruction'] = 'Preview incomplete; read exact original before using scientific content.'
        minimum = {k: item[k] for k in ('ref', 'record_type', 'original_version', 'full_original_read_ref')}
        if view:
            minimum['current_revision_read_refs'] = sorted({v['revision_read_ref'] for v in view['field_revisions'].values()})
        minimum['instruction'] = 'Read original and current revisions before reliance; all originals remain available.'
        candidates.append((item, minimum))
    items = reserve_navigation(candidates, 6144)
    used = sum(len(encoded(item).encode()) for item in items)
    return {'mode': mode, 'items': items, 'automatic_context_bytes': used, 'automatic_context_cap': 6144,
        'selection': selection, 'received_stage_order': [d['stage_id'] for d in self.archive_descriptors()],
        'common_scope': 'Earlier native scoped observations, errors and owner interpretations; neither old labels nor field decisions are current scientific truth.',
        'citation': 'Read archive ref, cite its returned materialized file; imported revision evidence_read_refs are qualified received history, not current-file IDs.',
        'revision_lookup': 'Local revision text indexes ordinary current search; received states/source files remain readable through their archive_stage. Original archive keyword matching is unchanged.'}
