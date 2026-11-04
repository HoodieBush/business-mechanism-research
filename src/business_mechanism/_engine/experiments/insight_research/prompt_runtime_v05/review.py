"""Typed reference diagnostics; native validation and scientific content are unchanged."""
from ..common import encoded
from ..paired_v13.review import Reviewer as PreviousReviewer
from ..paired_v06.references import ACTION_PATTERN


class Reviewer(PreviousReviewer):
    def normalize_submission(self,name,args):
        corrected,changes=super().normalize_submission(name,args)
        if name=='record_review':
            for issue in corrected.get('issues',[]):
                if issue.get('type')!='reproduced_contradiction' or issue.get('action_refs'):
                    continue
                refs=[]
                for location in issue.get('evidence_locations',[]):
                    for ref in ACTION_PATTERN.findall(location):
                        try:self.action(ref)
                        except (ValueError,KeyError,TypeError):continue
                        if ref not in refs:refs.append(ref)
                if refs:
                    issue['action_refs']=refs
                    changes['explicit_action_links'][issue['issue_id']]=refs
        return corrected,changes

    def dispatch(self, name, args, key):
        if name == 'record_review':
            ids=[item['issue_id'] for item in args['issues']]
            duplicates=sorted({ref for ref in ids if ids.count(ref)>1})
            unknown=sorted(set(args['open_issue_ids'])-set(ids))
            if duplicates or unknown:
                raise ValueError(encoded({'error':'issue ID bindings invalid',
                    'field':'issues[].issue_id / open_issue_ids',
                    'duplicate_current_ids':duplicates,'unknown_open_ids':unknown,
                    'valid_current_ids':ids,
                    'repair':'Keep all substantive findings. Give each current issue a unique ID; open_issue_ids refers only to this review. Old issues stay in original Q; prior_issue_updates only for the explicit parent review.'}))
            for i, issue in enumerate(args['issues']):
                for j, ref in enumerate(issue['affected_refs']):
                    try:
                        self.view.record(ref)
                    except ValueError as error:
                        raise ValueError(encoded({
                            'error': str(error),
                            'field': f'issues[{i}].affected_refs[{j}]', 'invalid_ref': ref,
                            'expected': 'received H/P/R/A/K/S/D/B scientific object; not file/action/check/Q',
                            'repair': 'Keep the file as evidence. Identify the actual scientific claim/record affected; do not discard the finding.'})) from error
            actions = [(f'checks_performed[{i}].action_ref', x['action_ref'])
                       for i, x in enumerate(args['checks_performed'])]
            actions += [(f'issues[{i}].action_refs[{j}]', ref)
                        for i, x in enumerate(args['issues']) for j, ref in enumerate(x['action_refs'])]
            for field, ref in actions:
                try:
                    self.action(ref)
                except ValueError as error:
                    raise ValueError(encoded({
                        'error': str(error), 'field': field, 'invalid_ref': ref,
                        'expected': 'actual check: action_ref returned by a tool in this critic task',
                        'repair': 'Researcher action: references are source material. Use the check: returned when you inspected it.'})) from error
        return super().dispatch(name, args, key)
