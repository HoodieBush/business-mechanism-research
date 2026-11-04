import json
from ..prompt_runtime_v05.workspace import ResearchWorkspace as Previous
from ..critic_v01.shared import lifecycle


class ResearchWorkspace(Previous):
    def report_revision_obligations(self, ref):
        """Accepted report corrections bind the immutable draft, not a note.

        This checks an author's declared disposition/version, not whether the
        critic is scientifically right or whether new prose is correct.
        """
        obligations = []
        for q in self.records('review'):
            if q.get('phase') != 'complete':
                continue
            for issue in q['issues']:
                if ref not in issue['affected_refs']:
                    continue
                responses = [b for b in self.records('review_response')
                             if b['review_ref'] == q['ref'] and b['issue_id'] == issue['issue_id']
                             and lifecycle(self.db, b['ref'])['status'] == 'active']
                if responses and responses[-1]['disposition'] in ('accept', 'revise'):
                    obligations.append({'draft_ref': ref, 'review_ref': q['ref'],
                                        'issue_id': issue['issue_id'], 'response_ref': responses[-1]['ref'],
                                        'reason': 'Accepted correction affects this immutable draft. Save a successor draft and review that version; a changed note/reply cannot update its text.'})
        return obligations

    def clearance(self, ref):
        if self.record(ref)['record_type'] == 'report_draft' and self.report_revision_obligations(ref):
            return False
        return super().clearance(ref)

    def report(self):
        for report in reversed(self.records('report')):
            if not lifecycle(self.db, report['ref'])['eligible_as_current_premise']:
                continue
            draft = report.get('reviewed_draft_ref')
            if draft and self.report_revision_obligations(draft):
                continue
            return report
        return None

    def _checked_dispatch(self, name, args, key):
        if name == 'collect_evidence' and self.closeout():
            # Keep the same recovery exception as native run_test: already
            # committed physical observations remain replayable after closeout.
            if key not in self.environment.state()['actions']:
                raise ValueError('Stage closeout: save/inspect existing evidence, respond and deliver; no new physical measurement. Existing operations remain replayable; this does not refute any hypothesis.')
        return super()._checked_dispatch(name, args, key)

    def context(self):
        context = super().context()
        # Bounded actual execution feedback, including partial memory writes.
        # No generated summary and no automatic scientific fact promotion.
        rows = self.db.execute('SELECT id,body FROM events ORDER BY id DESC LIMIT 6').fetchall()
        context['recent_execution_feedback'] = [
            {'ref': 'event:'+str(i), 'tool': e.get('tool'), 'result': e.get('result')}
            for i, body in reversed(rows)
            for e in [json.loads(body)]
            if e.get('result', {}).get('ok') is False or e.get('result', {}).get('knowledge_rejections')]
        context['delivery_contract'] = {
            'topic_report_tool': 'finish_research',
            'automatic_handoff_is_formal_report': False,
            'research_direction': 'researcher chooses; event-triggered independent critique',
            'execution_pause_is_scientific_rejection': False}
        drafts = self.records('report_draft')
        context['report_revision_obligations'] = self.report_revision_obligations(drafts[-1]['ref']) if drafts else []
        context['archived_report_refs'] = [r['ref'] for r in self.records('report')]
        return context
