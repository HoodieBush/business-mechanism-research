"""v09 selection and views unchanged; reserve all minimum refs before previews.

The selector below is the original static v09 method, with only its packing
block replaced. No runtime source rewriting, new model call or larger cap.
"""
from copy import deepcopy
import math
from types import MethodType
from ..common import Pending, digest, encoded
from ..memory import terms


def reserve_navigation(candidates, cap):
    items = [minimum for full, minimum in candidates]
    sizes = [len(encoded(item).encode()) for item in items]
    used = sum(sizes)
    if used > cap:
        raise Pending('Minimum exact history navigation exceeds fixed budget; full originals remain retained.')
    for i, (full, minimum) in enumerate(candidates):
        size = len(encoded(full).encode())
        if used - sizes[i] + size <= cap:
            used = used - sizes[i] + size
            items[i] = full
            sizes[i] = size
    return items


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
    candidates = []
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


def install_history_packer(workspace):
    # Explicit candidate adapter, installed only by a new registered continuation.
    # Keep the original workspace identity/scientific tools and data unchanged.
    workspace.experience_context = MethodType(experience_context, workspace)
