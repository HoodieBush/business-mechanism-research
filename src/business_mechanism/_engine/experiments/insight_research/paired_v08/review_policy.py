"""Versioned policy: researcher responses are auditable decisions, never factual premises.

Validation/application follow v01; only B is added to affected-object types.
All original checks, bindings, explicit issue updates and clearances remain.
"""
from ..common import digest

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
            if item['record_type'] not in ('hypothesis', 'plan', 'result', 'assessment', 'knowledge', 'state', 'report_draft', 'review_response'):
                raise ValueError('affected_refs must identify actual scientific objects or researcher responses; reviewer opinions remain excluded')
            versions[ref] = digest(item)
        for ref in issue['action_refs']: action(ref)
        reference(issue['check_artifact_refs'])
        if issue['basis'] == 'recomputed' and not issue['action_refs']:
            raise ValueError('recomputed issue needs actual check actions')
        if issue['type'] == 'reproduced_contradiction' and issue['basis'] == 'conjecture':
            raise ValueError('a conjecture cannot be labelled a reproduced contradiction')
    return versions

def apply_review(self, job_ref, body, *, author, original_ref=None, record_ref=None):
    if author=='researcher_self_check' and hasattr(self,'unanswered') and self.unanswered():
        raise ValueError('respond to prior opinions before the next self review')
    job = self.job(job_ref)
    if job['status'] == 'completed':
        existing = self.record(job['review_ref'])
        if existing['review_digest'] != digest(body): raise ValueError('completed review content differs')
        return existing
    if job['status'] not in ('pending', 'running'): raise ValueError('review episode limit reached; preserve disagreement')
    if digest(self.record(job['target_ref'])) != job['target_version']: raise ValueError('review target changed')
    versions = validate_review(body, self.record, self.references, self.review_action)
    item = self.add('review', {**body, 'author': author, 'job_ref': job_ref,
        '_record_ref': record_ref, 'review_digest': digest(body),
        'target_ref': job['target_ref'], 'target_version': job['target_version'],
        'hypothesis_refs': self.target_hypotheses(job['target_ref']),
        'affected_versions': versions, 'original_review_ref': original_ref, 'scientific_certification': False})
    if body['phase'] == 'checkpoint': return item
    if body.get('prior_issue_updates'):
        if not job['parent_review_ref']: raise ValueError('prior issue updates require a directed recheck')
        prior = self.record(job['parent_review_ref'], 'review')
        known = {x['issue_id'] for x in prior['issues']}
        if not set(body['prior_issue_updates']) <= known: raise ValueError('unknown prior issue in recheck')
        if not body['checks_performed']: raise ValueError('resolving prior issues needs actual checks')
        for issue, decision in body['prior_issue_updates'].items():
            self.db.execute('UPDATE review_issues SET open=? WHERE review_ref=? AND issue_id=?',
                (decision == 'still_open', prior['ref'], issue))
    for issue in body['issues']:
        for target in issue['affected_refs']:
            self.db.execute('INSERT INTO review_issues VALUES (?,?,?,?,?,?)', (item['ref'], issue['issue_id'], target,
                issue['basis'], bool(issue['blocking']), issue['issue_id'] in body['open_issue_ids']))
    if body['target_conclusion'] == 'consistent_in_checked_scope' and not self.blocked(job['target_ref']):
        self.db.execute('INSERT OR REPLACE INTO clearances VALUES (?,?,?)', (job['target_ref'], job['target_version'], item['ref']))
    self.db.execute("UPDATE review_jobs SET status='completed',review_ref=? WHERE ref=?", (item['ref'], job_ref))
    self.reconcile_issues()
    return item

class ReviewPolicy:
    apply_review=apply_review
