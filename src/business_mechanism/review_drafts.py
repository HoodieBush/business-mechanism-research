"""Private, immutable review drafts. Repairs never infer scientific content."""
from copy import deepcopy
import json
import sqlite3
from pydantic import ValidationError
from experiments.insight_research.common import digest, encoded, now
from .tool_protocol import strict_json


def pointer(parts):
    return '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)


class ReviewDrafts:
    def __init__(self, workspace):
        self.ws = workspace
        self.path = workspace.private/'review_drafts.sqlite'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS drafts(ref TEXT PRIMARY KEY,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS heads(lineage TEXT PRIMARY KEY,ref TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS repairs(key TEXT PRIMARY KEY,signature TEXT,ref TEXT);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def validate(self, raw):
        try:
            value = strict_json(raw)
            value = self.ws.tools['record_review'][0].model_validate(value).model_dump()
        except ValidationError as error:
            return [{'path': pointer(e['loc']), 'error_code': e['type'],
                     'message': e['msg'], 'input': e.get('input')}
                    for e in error.errors(include_url=False, include_context=False)]
        except (ValueError, TypeError) as error:
            return [{'path': '/', 'error_code': 'invalid_json', 'message': str(error)}]
        errors = []
        binding = self.ws.binding_error(value) if hasattr(self.ws, 'binding_error') else None
        if binding:
            errors.append({'path': '/prior_issue_updates', 'error_code': 'parent_issue_binding', **binding})
        ids = [issue['issue_id'] for issue in value['issues']]
        if len(ids) != len(set(ids)):
            errors.append({'path': '/issues', 'error_code': 'duplicate_issue_id'})
        if not set(value['open_issue_ids']) <= set(ids):
            errors.append({'path': '/open_issue_ids', 'error_code': 'unknown_issue_id', 'valid_issue_ids': ids})
        for i, issue in enumerate(value['issues']):
            for j, ref in enumerate(issue['affected_refs']):
                try:
                    record = self.ws.view.record(ref)
                    if record['record_type'] not in ('hypothesis', 'plan', 'result', 'assessment', 'knowledge', 'state', 'report_draft', 'review_response'):
                        raise ValueError('Actual scientific object required; files, actions and opinions are evidence only')
                except (ValueError, KeyError) as error:
                    errors.append({'path': f'/issues/{i}/affected_refs/{j}', 'error_code': 'invalid_affected_ref',
                                   'input': ref, 'message': str(error)})
        for i, check in enumerate(value['checks_performed']):
            try:
                self.ws.action(check['action_ref']); self.ws.references(check['artifact_refs'])
            except (ValueError, KeyError) as error:
                errors.append({'path': f'/checks_performed/{i}', 'error_code': 'invalid_check_reference', 'message': str(error)})
        # Match the actual dispatch policy too, including source_refs, issue
        # actions/artifacts and auditable researcher-response targets. This is
        # pure validation: no review is stored and no opinion is inferred.
        from experiments.insight_research.paired_v08.review_policy import validate_review
        try: validate_review(value, self.ws.view.record, self.ws.references, self.ws.action)
        except (ValueError,KeyError,TypeError) as error:
            errors.append({'path':'/source_refs_or_checks_or_issues','error_code':'review_reference_contract','message':str(error)})
        from .workflow import coverage_errors
        errors.extend(coverage_errors(self.ws, value))
        return errors

    def save(self, raw_arguments, *, key, parent=None, changes=None):
        raw = raw_arguments
        packet = self.ws.packet
        scope = [packet['target_ref'], packet['target_version'], self.ws.identity['packet_digest']]
        ref = 'draft:' + digest([scope, key, raw, parent])[:24]
        lineage = self.read(parent)['lineage'] if parent else ref
        item = {'draft_ref': ref, 'draft_hash': digest(raw), 'lineage': lineage,
                'parent': parent, 'created_at': now(), 'target_ref': scope[0],
                'target_version': scope[1], 'packet_digest': scope[2],
                'raw_arguments': raw, 'changes': changes or [],
                'validation_errors': self.validate(raw), 'scientific_certification': False}
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO drafts VALUES (?,?)', (ref, encoded(item)))
            db.execute('INSERT OR IGNORE INTO heads VALUES (?,?)', (lineage, ref))
        return self.read(ref)

    def read(self, ref):
        with self.connect() as db:
            row = db.execute('SELECT body FROM drafts WHERE ref=?', (ref,)).fetchone()
            if not row:
                raise ValueError('Unknown owned draft_ref')
            item = json.loads(row[0])
            head = db.execute('SELECT ref FROM heads WHERE lineage=?', (item['lineage'],)).fetchone()[0]
        committed = self.ws.db.execute('SELECT result FROM release_draft_commits WHERE ref=?', (ref,)).fetchone()
        return {**item, 'is_head': head == ref, 'head_ref': head,
                'commit_result': json.loads(committed[0]) if committed else None}

    def current(self):
        with self.connect() as db:
            row = db.execute('SELECT ref FROM heads ORDER BY rowid DESC LIMIT 1').fetchone()
        return self.read(row[0]) if row else None

    def check(self, ref, expected_hash):
        item = self.read(ref)
        if item['draft_hash'] != expected_hash or not item['is_head']:
            raise ValueError('draft_version_conflict: read head_ref and explicitly rebase changes')
        if (item['target_ref'], item['target_version'], item['packet_digest']) != (
                self.ws.packet['target_ref'], self.ws.packet['target_version'], self.ws.identity['packet_digest']):
            raise ValueError('stale_draft_target: no automatic rebinding')
        return item

    def patch(self, ref, expected_hash, changes, *, key):
        signature = digest([ref, expected_hash, changes])
        with self.connect() as db:
            prior = db.execute('SELECT signature,ref FROM repairs WHERE key=?', (key,)).fetchone()
        if prior:
            if prior[0] != signature:
                raise ValueError('repair_operation_identity_conflict')
            return self.read(prior[1])
        item = self.check(ref, expected_hash)
        value = json.loads(item['raw_arguments'])
        before = deepcopy(value)
        for change in changes:
            path = change['path']
            if not path.startswith('/') or path == '/':
                raise ValueError('Use a nonempty JSON pointer to a field; no implicit full replacement')
            parts = [p.replace('~1', '/').replace('~0', '~') for p in path[1:].split('/')]
            current = value
            try:
                for p in parts[:-1]:
                    current = current[int(p)] if isinstance(current, list) else current[p]
                field = int(parts[-1]) if isinstance(current, list) else parts[-1]
                if change['op'] == 'remove':
                    del current[field]
                else:
                    current[field] = change['value']
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise ValueError('patch_path_invalid: '+path) from error
        successor = self.save(encoded(value), key=key, parent=ref,
                              changes=[{'patch': changes, 'before_hash': digest(before), 'after_hash': digest(value)}])
        with self.connect() as db:
            cur = db.execute('UPDATE heads SET ref=? WHERE lineage=? AND ref=?',
                             (successor['draft_ref'], item['lineage'], ref))
            if cur.rowcount != 1:
                raise ValueError('draft_version_conflict: concurrent patch retained but not promoted')
            db.execute('INSERT INTO repairs VALUES (?,?,?)', (key, signature, successor['draft_ref']))
        return self.read(successor['draft_ref'])

    def commit(self, ref, expected_hash, dispatch):
        item = self.check(ref, expected_hash)
        if item['commit_result']:
            return item['commit_result']
        errors = self.validate(item['raw_arguments'])
        if errors:
            return {'ok': False, 'error_code': 'review_schema_invalid', 'executed_reviews': 0,
                    'draft_ref': ref, 'draft_hash': expected_hash, 'validation_errors': errors}
        args = self.ws.tools['record_review'][0].model_validate_json(item['raw_arguments']).model_dump()
        result = dispatch(args)
        # The workspace operation transaction is authoritative. On a crash,
        # dispatch uses the same deterministic review key before retrying.
        self.ws.db.execute('INSERT OR IGNORE INTO release_draft_commits VALUES (?,?)', (ref, encoded(result)))
        return result

    def packet(self):
        item = self.current()
        if not item or item['commit_result']:
            return None
        errors=[]
        for original in item['validation_errors'][:8]:
            error=dict(original)
            for key,value in list(error.items()):
                if len(encoded(value).encode())>600:
                    error[key]={'preview_only':True,'original_hash':digest(value),'preview':encoded(value)[:300],
                                'read':'read_review_draft(section=validation_errors,offset,limit)'}
            errors.append(error)
        return {k: item[k] for k in ('draft_ref', 'draft_hash', 'head_ref',
                                    'target_ref', 'target_version')} | {
            'validation_errors': errors, 'validation_error_count':len(item['validation_errors']),
            'reference_index': {'scientific_target': self.ws.packet['target_ref'],
                                'received_objects': 'directory:all', 'related_objects': 'directory:related',
                                'policy': 'Select affected_refs explicitly; do not substitute current target for an older affected object.'},
            'action': 'read_review_draft, patch only explicit fields, then commit_review. Preserve every finding and scope; schema validity is not scientific correctness.'}
