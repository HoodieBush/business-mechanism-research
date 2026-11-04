"""Shared scientific-review contract; observation is not automatic truth."""
from copy import deepcopy
from pathlib import Path

from ..common import digest, sha
from ..critic_v01.workspace import CriticWorkspace
from ..critic_v01.runtime import CriticRuntime
from .contracts import REVIEW_TOOLS, schemas


def validate_review(body, record, reference, action):
    reference(body['source_refs'])
    ids = [x['issue_id'] for x in body['issues']]
    if len(ids) != len(set(ids)) or not set(body['open_issue_ids']) <= set(ids):
        raise ValueError('unique issue IDs, open IDs must belong to this review')
    versions = {}
    for check in body['checks_performed']:
        action(check['action_ref']); reference(check['artifact_refs'])
    for issue in body['issues']:
        if len(issue['affected_refs']) != len(set(issue['affected_refs'])):
            raise ValueError('affected_refs must contain each scientific object once')
        for ref in issue['affected_refs']:
            item = record(ref)
            if item['record_type'] not in ('hypothesis', 'plan', 'result', 'assessment', 'knowledge', 'state', 'report_draft'):
                raise ValueError('affected_refs must identify actual scientific objects, not reviewer opinions')
            versions[ref] = digest(item)
        for ref in issue['action_refs']: action(ref)
        reference(issue['check_artifact_refs'])
        if issue['basis'] == 'recomputed' and not issue['action_refs']:
            raise ValueError('recomputed issue needs actual check actions')
        if issue['type'] == 'reproduced_contradiction' and issue['basis'] == 'conjecture':
            raise ValueError('a conjecture cannot be labelled a reproduced contradiction')
    return versions


class Reviewer(CriticWorkspace):
    tools = REVIEW_TOOLS
    def tool_schemas(self): return schemas(REVIEW_TOOLS)

    def __init__(self, root, snapshot, settings, *, reopen=False):
        settings = deepcopy(settings)
        settings['review_v2_sources'] = {p.name: sha(p) for p in Path(__file__).parent.iterdir()
            if p.is_file() and p.suffix in ('.py', '.txt')}
        super().__init__(root, snapshot, settings, reopen=reopen)

    def dispatch(self, name, args, key):
        if name == 'record_review':
            versions = validate_review(args, self.view.record, self.references, self.action)
            args = {**args, 'affected_versions': versions}
        return super().dispatch(name, args, key)


class ReviewerRuntime(CriticRuntime):
    def initial(self):
        from ..common import encoded
        prompt = (Path(__file__).parent / 'reviewer_prompt.txt').read_text()
        return [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': encoded(self.ws.context())}]
