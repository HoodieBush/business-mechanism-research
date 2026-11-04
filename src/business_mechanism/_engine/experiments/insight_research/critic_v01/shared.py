"""Common candidate guards, independently usable without a critic model.

Historical modules/default entry points are unchanged. Archival access and
current factual eligibility are deliberately different operations.
"""
from copy import deepcopy
from pathlib import Path

from ..common import digest, encoded, sha
from ..robust import RobustWorkspace
from ..runtime_robust import RobustRuntime
from ..runtime_memory import MemoryJournal
from token_budget import reservation_bound

CLOSEOUT_TOOLS = frozenset(('read_context', 'read_artifact', 'read_memory',
    'search_memory', 'query_data', 'run_python', 'record_assessment',
    'update_research_state', 'finish_research'))
NOTICE = ('资源收尾已开启：可回读、检索和复算已经收到的资料，并保存判断、认识或阶段交付。'
          '不启动新试验或新假说分支。核验不够资源时保存疑点并暂停；不要求获得支持或反驳。')


def lifecycle(db, ref):
    """Full explicit review state; not a certificate of scientific correctness."""
    tables = {x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    row = db.execute('SELECT status,reason,state_ref FROM memory_validity WHERE ref=?', (ref,)).fetchone() if 'memory_validity' in tables else None
    affected = [x[0] for x in db.execute('SELECT target FROM affected WHERE ref=? ORDER BY target', (ref,))] if 'affected' in tables else []
    replacement = db.execute('SELECT superseded_by FROM knowledge_current WHERE ref=?', (ref,)).fetchone() if 'knowledge_current' in tables else None
    status = row[0] if row else 'active'
    replaced = replacement[0] if replacement else None
    return {'status': status, 'reason': row[1] if row else '',
        'review_record': row[2] if row else None, 'explicit_dependency_reviews': affected,
        'replacement_ref': replaced, 'eligible_as_current_premise': status == 'active' and not affected and not replaced,
        'certification': 'Lifecycle and explicit dependencies only; not scientific truth.'}


class CheckedWorkspace(RobustWorkspace):
    """The same common patch can be used in a self-review control condition."""
    def __init__(self, root, question, world, settings, *, reopen=False):
        settings = deepcopy(settings)
        settings['common_guard_sources'] = {'shared.py': sha(Path(__file__))}
        self.closeout_mode = False
        super().__init__(root, question, world, settings, reopen=reopen)

    def premise(self, ref):
        if ref.startswith('file:'):
            self.file(ref)
            return
        if ref.startswith('card:'): ref = ref[5:]
        self.record(ref)
        current = lifecycle(self.db, ref)
        if not current['eligible_as_current_premise']:
            raise ValueError(encoded({'error': 'record is not a current factual premise',
                'ref': ref, 'lifecycle': current,
                'repair': 'Read the original and review/replace it with evidence; archive and counterevidence access remain allowed.'}))

    def save_knowledge(self, entry):
        # Preserve RobustWorkspace's optional-entry isolation: an ineligible
        # strong claim must not discard a legal research checkpoint.
        if entry['status'] in ('supported_in_scope', 'refuted'):
            try:
                expected = 'supported' if entry['status'] == 'supported_in_scope' else 'refuted'
                hypotheses = set(entry['hypothesis_refs'])
                matching = set()
                for ref in entry['evidence_refs']:
                    self.premise(ref)
                    if ref.startswith(('file:', 'card:')): continue
                    item = self.record(ref)
                    if item['record_type'] == 'assessment' and item['status'] == expected:
                        matching.add(item['hypothesis_ref'])
                if not hypotheses or not hypotheses <= matching:
                    raise ValueError(encoded({'error': 'strong memory needs an eligible matching assessment for each declared hypothesis',
                        'hypothesis_refs': sorted(hypotheses), 'covered_hypothesis_refs': sorted(matching),
                        'repair': 'Cite assessments for these exact hypotheses, or preserve the claim as tentative/needs_review.'}))
            except ValueError as error:
                index = self.knowledge_entry_index
                self.knowledge_entry_index += 1
                self.knowledge_rejections.append({'input_index': index, 'error': str(error),
                    'action': 'Claim not saved; legal checkpoint and other accepted entries are retained.'})
                return None
        return super().save_knowledge(entry)

    def check_measurement(self, claim):
        if not claim['source_ref'].startswith('file:'):
            result = self.record(claim['source_ref'], 'result')
            allowed = ('mismatched_rows', 'recorded_total', 'verified_total', 'difference_units')
            if result['evidence_nature'] == 'record_reconciliation' and claim['field'] not in allowed:
                source = self.file_ref(self.public / 'observed_facts.json')['ref']
                raise ValueError(encoded({'error': 'field does not belong to this reconciliation result',
                    'source_ref': result['ref'], 'provided_field': claim['field'], 'available_fields': list(allowed),
                    'history_dimensions_source': source,
                    'repair': 'Bind the intended reconciliation field; use observed_facts for history dimensions. Do not drop a binding to bypass the mismatch.'}))
        return super().check_measurement(claim)

    def update_state(self, args):
        # Apply validated lifecycle changes before adding new dependent claims.
        # They are in the outer action transaction; the appended state below
        # rebinds them to its real immutable ref. Otherwise a new valid claim
        # created in the same batch inherits the old withdrawal flag forever.
        for review in args['memory_reviews']:
            self.record(review['target_ref']); self.references(review['evidence_refs'])
            row = self.db.execute('SELECT superseded_by FROM knowledge_current WHERE ref=?', (review['target_ref'],)).fetchone()
            if review['decision'] == 'restore' and row and row[0]: raise ValueError('superseded original cannot be restored; review the replacement')
        for review in args['memory_reviews']:
            self._flag(review['target_ref'], 'active' if review['decision'] == 'restore' else review['decision'],
                review['reason'], None, acknowledge_dependencies=review['decision'] == 'restore')
        restored = {r['target_ref'] for r in args['memory_reviews'] if r['decision'] == 'restore'}
        for ref in args['evidence_refs']:
            if ref not in restored: self.premise(ref)
        return super().update_state(args)

    def _checked_dispatch(self, name, args, key):
        if self.closeout_mode and name not in CLOSEOUT_TOOLS:
            raise ValueError('Resource closeout allows source reads, historical search, recomputation and saving; no new trial/branch. Save uncertainties or pause.')
        if name == 'read_context':
            ctx = self.context()
            return {'context_location': 'Automatically refreshed second message',
                'context_sha256': digest(ctx), 'archive_counts': ctx['archive_counts'],
                'state_ref': (self.state() or {}).get('ref'),
                'unincorporated_result_refs': [x['ref'] for x in ctx['unincorporated_results']]}
        if name == 'record_assessment' and args['status'] != 'unresolved':
            for ref in args['result_refs']: self.premise(ref)
        if name == 'finish_research':
            for ref in args['assessment_refs']: self.premise(ref)
            covered = {self.record(ref, 'assessment')['hypothesis_ref'] for ref in args['assessment_refs']}
            expected = {x['ref'] for x in self.records('hypothesis')} - covered
            if set(args['other_hypotheses']) != expected:
                raise ValueError(encoded({'error': 'other_hypotheses must be the exact uncovered set',
                    'expected_hypothesis_refs': sorted(expected),
                    'unexpected_hypothesis_refs': sorted(set(args['other_hypotheses']) - expected),
                    'repair': 'Give each expected hypothesis a disposition; do not repeat an assessed hypothesis.'}))
        # Bypass only the legacy three-tool resource policy, not Robust's
        # scientific contracts, transaction protection or execution machinery.
        return RobustWorkspace._checked_dispatch(self, name, args, key)


class CheckedRuntime(RobustRuntime):
    def __init__(self, workspace, model_config, *, journal=None):
        super().__init__(workspace, model_config, journal=journal)
        workspace.closeout_mode = bool(self.cp.get('resource_closeout'))

    def initial(self):
        messages = super().initial()
        messages[0]['content'] += '\n完整研究上下文在第二条消息自动刷新；收尾阶段仍可回读、检索及核验已见资料。\n'
        return messages

    def remaining(self):
        if not isinstance(self.journal, MemoryJournal): return None
        return min(self.journal.snapshot()['remaining_admission_tokens'],
            self.ws.settings['limits']['token_allowance'] - self.journal.state['accounted_tokens'])

    def payload(self, messages=None): return self.constrained(super().payload(messages))

    def prepare_payload(self, payload):
        remaining = self.remaining()
        if remaining is not None and remaining < 3 * reservation_bound(payload):
            self.cp['resource_closeout'] = True; self.ws.closeout_mode = True; self.save()
        return self.constrained(super().prepare_payload(self.constrained(payload)))

    def drain(self, deadline=None):
        self.ws.closeout_mode = bool(self.cp.get('resource_closeout'))
        return super().drain(deadline)

    def constrained(self, payload):
        if self.cp.get('resource_closeout'):
            payload['tools'] = [t for t in payload['tools'] if t['function']['name'] in CLOSEOUT_TOOLS]
            if not any(m.get('content') == NOTICE for m in payload['messages']):
                payload['messages'].append({'role': 'user', 'content': NOTICE})
        return payload
