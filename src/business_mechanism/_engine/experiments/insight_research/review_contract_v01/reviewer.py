from ..common import encoded
from ..prompt_runtime_v05.review import Reviewer as Previous


class Reviewer(Previous):
    def binding_error(self, submission):
        updates = submission.get('prior_issue_updates', {})
        parent = self.packet.get('previous_feedback')
        known = {issue['issue_id'] for issue in parent['issues']} if parent else set()
        invalid = sorted(set(updates)-known)
        if updates and (not parent or invalid):
            return {'error': 'prior issue bindings do not match this directed recheck',
                    'field': 'prior_issue_updates', 'parent_review_ref': parent.get('ref') if parent else None,
                    'valid_parent_issue_ids': sorted(known), 'invalid_parent_issue_ids': invalid,
                    'repair': 'Keep all substantive findings. This field updates only issues in the explicit parent review. Other historical questions remain in their original reviews; describe them with attribution or define a current issue if warranted. Do not rerun unchanged calculations.'}
        return None

    def dispatch(self, name, args, key):
        if name == 'record_review':
            error = self.binding_error(args)
            if error:
                raise ValueError(encoded(error))
        return super().dispatch(name, args, key)

    def report(self):
        report = super().report()
        return report if report and not self.binding_error(report) else None

    def context(self):
        context = super().context()
        old = super().report()
        error = self.binding_error(old) if old else None
        if error:
            context['unimportable_completed_submission'] = {
                'original_local_review_ref': old['ref'], 'contract_error': error,
                'paid_work': 'Exact local review and full own process remain archived. Repair submission bindings, preserve all scientific findings and evidence. This is not a new verification task.',
                'exact_submission': old}
        return context
