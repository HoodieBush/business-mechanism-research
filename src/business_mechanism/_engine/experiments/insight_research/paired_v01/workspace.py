"""One research backend, with explicit self/independent publication review.

LLM calls are owned by the outer runner, never by these transactions. Feedback
has object/version bindings; it is not factual evidence or an automatic edit.
"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import uuid

from ..common import Pending, digest, encoded, now, sha
from ..memory import terms
from ..robust import DEPENDENCY_FIELDS
from ..critic_v01.shared import CheckedWorkspace, lifecycle
from .base import ModeBase
from .contracts import TOOLS, schemas
from .review import validate_review


class ResearchWorkspace(CheckedWorkspace, ModeBase):
    tools = TOOLS
    def tool_schemas(self): return schemas()

    def __init__(self, root, question, world, settings, *, reopen=False):
        settings = deepcopy(settings)
        settings['paired_sources'] = {p.name: sha(p) for p in Path(__file__).parent.iterdir()
            if p.is_file() and p.suffix in ('.py', '.txt')}
        self.jobs_ready = False; self.sealing = False
        super().__init__(root, question, world, settings, reopen=reopen)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS review_jobs(ref TEXT PRIMARY KEY,target TEXT,version TEXT,episode TEXT,round INTEGER,
                status TEXT,review_ref TEXT,parent_review TEXT,reason TEXT);
            CREATE INDEX IF NOT EXISTS jobs_status ON review_jobs(status);
            CREATE TABLE IF NOT EXISTS review_issues(review_ref TEXT,issue_id TEXT,target TEXT,basis TEXT,blocking INTEGER,
                open INTEGER,PRIMARY KEY(review_ref,issue_id,target));
            CREATE TABLE IF NOT EXISTS clearances(target TEXT PRIMARY KEY,version TEXT,review_ref TEXT);
            CREATE TABLE IF NOT EXISTS review_inputs(job_ref TEXT PRIMARY KEY,path TEXT,manifest_sha TEXT);
            CREATE TABLE IF NOT EXISTS self_review_clock(job_ref TEXT PRIMARY KEY,start_attempt INTEGER);
        ''')
        self.jobs_ready = True

    def add(self, kind, body):
        if kind == 'report' and not self.sealing: kind = 'report_draft'
        if kind in ('review', 'review_note', 'review_response', 'review_action', 'report_draft'):
            body = dict(body)
            prefix = {'review': 'Q', 'review_note': 'N', 'review_response': 'B', 'review_action': 'C', 'report_draft': 'D'}[kind]
            ref = body.pop('_record_ref', None) or prefix + uuid.uuid4().hex[:16]
            if not ref.startswith(prefix): raise ValueError('host record prefix differs')
            item = {**body, 'ref': ref, 'record_type': kind, 'created_at': now(), 'author': body.get('author', 'researcher')}
            self.db.execute('INSERT INTO records VALUES (?,?,?)', (ref, kind, encoded(item)))
            self.index(ref, kind, item, item.get('hypothesis_refs', []), [])
            self._index_review(item)
        else: item = super().add(kind, body)
        if self.jobs_ready:
            if kind == 'assessment':
                parent = body.get('supersedes_assessment_ref')
                if parent:
                    prior = self.record(parent, 'assessment')
                    if prior['hypothesis_ref'] != body['hypothesis_ref']: raise ValueError('assessment revision must address the same original hypothesis')
                    self._flag(parent, 'superseded', 'assessment replaced by ' + item['ref'], item['ref'])
                self.enqueue(item['ref'], parent)
            elif kind == 'knowledge' and body['status'] in ('supported_in_scope', 'refuted'):
                self.enqueue(item['ref'], body.get('supersedes_ref'))
            elif kind == 'report_draft': self.enqueue(item['ref'], body.get('supersedes_draft_ref'))
        return item

    def enqueue(self, target, parent=None, *, parent_review=None, reason='New candidate claim'):
        item = self.record(target); version = digest(item)
        exists = self.db.execute("SELECT ref FROM review_jobs WHERE target=? AND version=? AND status IN ('pending','running')", (target, version)).fetchone()
        if exists: return exists[0]
        previous = self.db.execute('SELECT episode,review_ref FROM review_jobs WHERE target=? ORDER BY rowid DESC LIMIT 1', (parent or target,)).fetchone()
        episode = previous[0] if previous else target
        if parent_review is None and previous: parent_review = previous[1]
        count = self.db.execute('SELECT count(*) FROM review_jobs WHERE episode=?', (episode,)).fetchone()[0]
        ref = 'J' + uuid.uuid4().hex[:16]
        status = 'pending' if count < 2 else 'exhausted'
        self.db.execute('INSERT INTO review_jobs VALUES (?,?,?,?,?,?,?,?,?)',
            (ref, target, version, episode, count+1, status, None, parent_review, reason))
        return ref

    def job(self, ref):
        row = self.db.execute('SELECT ref,target,version,episode,round,status,review_ref,parent_review,reason FROM review_jobs WHERE ref=?', (ref,)).fetchone()
        if not row: raise ValueError('received review job required')
        job = dict(zip(('ref','target_ref','target_version','episode','round','status','review_ref','parent_review_ref','reason'), row))
        job['review_http_limit'] = 12 if job['round'] == 1 else 6
        return job

    def jobs(self, status=None):
        rows = self.db.execute('SELECT ref FROM review_jobs' + (' WHERE status=?' if status else '') + ' ORDER BY rowid', (status,) if status else ())
        return [self.job(x[0]) for x in rows]

    def blocked(self, ref):
        if not self.jobs_ready: return False
        return bool(self.db.execute("SELECT 1 FROM review_issues WHERE target=? AND open=1 AND blocking=1 AND basis!='conjecture' LIMIT 1", (ref,)).fetchone())

    def clearance(self, ref):
        row = self.db.execute('SELECT version,review_ref FROM clearances WHERE target=?', (ref,)).fetchone()
        return bool(row and row[0] == digest(self.record(ref)) and lifecycle(self.db,ref)['eligible_as_current_premise'] and not self.blocked(ref))

    def premise(self, ref):
        super().premise(ref)
        if ref.startswith(('file:', 'card:')): return
        item = self.record(ref)
        if item['record_type'] in ('review', 'review_note', 'review_response', 'review_action'):
            raise ValueError('review records are attributed feedback/operation facts, not scientific factual premises; cite the actual data or computation')
        needs = item['record_type'] in ('assessment', 'report_draft') or (
            item['record_type'] == 'knowledge' and item['status'] in ('supported_in_scope', 'refuted'))
        if self.blocked(ref) or needs and not self.clearance(ref):
            raise ValueError(encoded({'error': 'claim awaits current review or an evidence-linked response', 'ref': ref,
                'repair': 'Keep a checkpoint/tentative note; inspect review jobs and feedback. An unreviewed or disputed claim is not a strong current premise.'}))
        seen = getattr(self, '_premise_stack', set())
        if ref in seen: return
        self._premise_stack = seen | {ref}
        try:
            for field in DEPENDENCY_FIELDS:
                values = item.get(field, [])
                for parent in values if isinstance(values,list) else [values] if isinstance(values,str) else []:
                    self.premise(parent)
        finally: self._premise_stack = seen

    def knowledge_filter(self):
        original = super().knowledge_filter()
        if not self.jobs_ready: return original
        return original + " AND NOT EXISTS(SELECT 1 FROM review_issues i WHERE i.target=d.ref AND i.open=1 AND i.blocking=1 AND i.basis!='conjecture') AND (d.kind!='knowledge' OR d.status NOT IN ('supported_in_scope','refuted') OR EXISTS(SELECT 1 FROM clearances c WHERE c.target=d.ref))"

    def knowledge_view(self, ref):
        item = super().knowledge_view(ref)
        item['publication_review'] = {'clearance': self.clearance(ref), 'blocking_issue': self.blocked(ref),
            'needed_for_strong_fact': item['status'] in ('supported_in_scope','refuted')}
        return item

    def card(self, ref):
        item = super().card(ref)
        for assessment in item['latest_assessments_by_status']:
            assessment['publication_review'] = {'clearance': self.clearance(assessment['ref']),
                'blocking_issue': self.blocked(assessment['ref'])}
        return item

    def review_action(self, ref):
        if ref.startswith('event:'):
            try: number = int(ref[6:])
            except ValueError: raise ValueError('actual event: action reference required')
            row = self.db.execute('SELECT body FROM events WHERE id=?', (number,)).fetchone()
            if not row: raise ValueError('actual event reference required')
            return json.loads(row[0])
        item = self.record(ref, 'review_action')
        return item['operation']

    def apply_review(self, job_ref, body, *, author, original_ref=None, record_ref=None):
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

    def target_hypotheses(self, ref):
        item = self.record(ref)
        return [item['hypothesis_ref']] if item.get('hypothesis_ref') else item.get('hypothesis_refs', item.get('all_hypothesis_refs', []))

    def reconcile_issues(self):
        # Owner changes can retire a disputed old object, but cannot turn a
        # reply or an unreviewed replacement into a verified strong fact.
        for review, issue, target in self.db.execute('SELECT review_ref,issue_id,target FROM review_issues WHERE open=1').fetchall():
            responses = [x for x in self.records('review_response') if x['review_ref'] == review and x['issue_id'] == issue]
            if responses and responses[-1]['disposition'] in ('accept', 'revise'):
                if not lifecycle(self.db, target)['eligible_as_current_premise']:
                    self.db.execute('UPDATE review_issues SET open=0 WHERE review_ref=? AND issue_id=? AND target=?', (review, issue, target))

    def respond(self, response, state_ref):
        review = self.record(response['review_ref'], 'review')
        if review['phase'] != 'complete': raise ValueError('respond to a completed review, not a checkpoint')
        issues = {x['issue_id']: x for x in review['issues']}
        if response['issue_id'] not in issues: raise ValueError('response issue does not belong to review')
        self.references(response['evidence_refs'] + response['replacement_refs'])
        for ref in response['evidence_refs']:
            if not ref.startswith('file:') and self.record(ref)['record_type'] in ('review', 'review_response'):
                raise ValueError('a reviewer opinion alone is not evidence for a rebuttal or correction')
        result = self.add('review_response', {**response, 'source_state_ref': state_ref})
        if response['disposition'] == 'rebut':
            job = self.job(review['job_ref'])
            self.enqueue(job['target_ref'], job['target_ref'], parent_review=review['ref'], reason=response['rationale'])
        self.reconcile_issues()
        return result

    def update_state(self, args):
        args = deepcopy(args)
        self_reviews = args.pop('self_reviews'); responses = args.pop('review_responses')
        self.references(args['pending_claim_refs'])
        reviews_saved = []; rejected = []
        for i, entry in enumerate(self_reviews):
            self.db.execute('SAVEPOINT self_review')
            try:
                if self.settings['verification_mode'] != 'self': raise ValueError('independent mode cannot waive peer review with a self report')
                item = self.apply_review(entry['job_ref'], entry['review'], author='researcher_self_check')
                reviews_saved.append(item['ref'])
            except (ValueError, TypeError) as error:
                self.db.execute('ROLLBACK TO self_review'); rejected.append({'input_index': i, 'error': str(error)})
            finally: self.db.execute('RELEASE self_review')
        result = super().update_state(args)
        response_refs = []
        for i, response in enumerate(responses):
            self.db.execute('SAVEPOINT review_response')
            try: response_refs.append(self.respond(response, result['ref'])['ref'])
            except (ValueError, TypeError) as error:
                self.db.execute('ROLLBACK TO review_response'); rejected.append({'response_index': i, 'error': str(error)})
            finally: self.db.execute('RELEASE review_response')
        result.update(review_refs=reviews_saved, response_refs=response_refs, review_rejections=rejected)
        return result

    def try_seal_report(self):
        drafts = self.records('report_draft')
        if not drafts or self.report(): return
        draft = drafts[-1]
        if not self.clearance(draft['ref']): return
        if self.jobs('pending') or self.jobs('running'): return
        for field, kind in (('all_hypothesis_refs','hypothesis'),('all_plan_refs','plan'),('all_result_refs','result'),('all_assessment_refs','assessment')):
            if set(draft[field]) != {x['ref'] for x in self.records(kind)}: return
        try:
            for ref in draft['assessment_refs']: self.premise(ref)
        except ValueError: return
        body = {k: v for k, v in draft.items() if k not in ('ref','record_type','created_at','author')}
        body.update(reviewed_draft_ref=draft['ref'], review_ref=self.db.execute('SELECT review_ref FROM clearances WHERE target=?', (draft['ref'],)).fetchone()[0])
        body['assessment_lifecycle'] = {x['ref']: lifecycle(self.db, x['ref']) for x in self.records('assessment')}
        self.sealing = True
        try: self.add('report', body)
        finally: self.sealing = False

    def _checked_dispatch(self, name, args, key):
        if name in ('read_memory','read_artifact') and args['ref'].startswith('job:'):
            text = encoded(self.job_packet(args['ref'])); end = args['offset'] + args['limit']
            return {'ref': args['ref'], 'text': text[args['offset']:end], 'sha256': digest(text),
                'next_offset': end if end < len(text) else None}
        if name in ('read_memory','read_artifact') and args['ref'].startswith('file:'):
            result = super()._checked_dispatch(name, args, key)
            result['compute_path'] = str(self.file(args['ref'])[0]); return result
        if name in ('read_memory','read_artifact') and args['ref'].startswith(('A','D','Q','B','C','N')):
            item = self.record(args['ref'])
            view = {**item, 'lifecycle': lifecycle(self.db, args['ref']),
                'publication_review': {'clearance': self.clearance(args['ref']), 'blocking_issue': self.blocked(args['ref'])},
                'original_version': digest(item)}
            text = encoded(view); end = args['offset'] + args['limit']
            return {'ref': args['ref'], 'text': text[args['offset']:end], 'sha256': digest(view),
                'next_offset': end if end < len(text) else None}
        if name == 'finish_research':
            parent = args.get('supersedes_draft_ref')
            if parent: self.record(parent, 'report_draft')
            for draft in self.records('report_draft'):
                if all(draft.get(k) == v for k, v in args.items()): return draft
        return super()._checked_dispatch(name, args, key)

    def references(self, refs):
        for ref in refs:
            if ref.startswith('job:'): self.job(ref[4:].split('/',1)[0])
            else: super().references([ref])

    def job_packet(self, ref):
        job_ref, _, navigation = ref.removeprefix('job:').partition('/')
        job = self.job(job_ref)
        row = self.db.execute('SELECT path,manifest_sha FROM review_inputs WHERE job_ref=?', (job_ref,)).fetchone()
        if not row: return {'job': job, 'candidate_record': self.record(job['target_ref']), 'packet_status': 'not prepared yet'}
        root = Path(row[0])
        if sha(root/'manifest.json') != row[1]: raise Pending('review evidence manifest changed')
        manifest = json.loads((root/'manifest.json').read_text())
        if navigation:
            if not navigation.startswith('directory:'): raise ValueError('received review directory required')
            if sha(root/'directories.json') != manifest['files_sha256']['directories.json']: raise Pending('review directory changed')
            directories = json.loads((root/'directories.json').read_text()); name = navigation[10:]
            if name not in directories: raise ValueError('received directory required')
            return {'refs': directories[name], 'total': len(directories[name])}
        if sha(root/'packet.json') != manifest['files_sha256']['packet.json']: raise Pending('review packet changed')
        packet = json.loads((root/'packet.json').read_text())
        for f in packet['public_files']: f['path'] = str(self.file(f['ref'])[0])
        packet['related_records']['index_ref'] = 'job:' + job_ref + '/directory:related'
        packet['all_related_received_results']['index_ref'] = 'job:' + job_ref + '/directory:results'
        packet['path_policy'] = 'Same evidence, researcher paths. Use own PUBLIC_DIR/ARTIFACT_DIR or read_artifact compute_path.'
        return packet

    def call(self, name, args, operation_id):
        result = super().call(name, args, operation_id)
        key = 'test:' + args['plan_ref'] if name == 'run_test' else operation_id
        row = self.db.execute('SELECT id FROM events WHERE operation=?', (key,)).fetchone()
        with self.db: self.reconcile_issues()
        return {**result, 'action_ref': 'event:' + str(row[0])} if row else result

    def context(self):
        context = super().context()
        context.update(research_profile='paired_research_v1', verification_mode=self.settings['verification_mode'])
        if hasattr(self, 'study_budget'): context['common_study_usage'] = self.study_budget.snapshot()
        if self.jobs_ready:
            context['research_knowledge'] = [k for k in context['research_knowledge']
                if not self.blocked(k['ref']) and (k['status'] not in ('supported_in_scope','refuted') or self.clearance(k['ref']))]
            context['memory_selection']['selected_refs'] = [k['ref'] for k in context['research_knowledge']]
            pending = self.jobs('pending') + self.jobs('running')
            context['review_jobs'] = pending + self.jobs('exhausted')
            if pending: context['current_review_packet'] = self.job_packet('job:' + pending[0]['ref'])
            feedback = self.records('review')
            context['review_feedback'] = feedback[-3:]
            context['open_review_issues'] = [{'review_ref': r, 'issue_id': i, 'affected_ref': t,
                'basis': b, 'blocking': bool(v)} for r, i, t, b, v in self.db.execute('SELECT review_ref,issue_id,target,basis,blocking FROM review_issues WHERE open=1')]
            context['review_policy'] = 'Opinion is feedback, not evidence. A correct current assessment and a wrong old memory can be addressed separately. Initial review plus one substantive recheck per explicit revision lineage.'
            context['report_drafts'] = [{'ref': d['ref'], 'stage_status': d['stage_status']} for d in self.records('report_draft')[-2:]]
            context['initialization_notice'] = self.settings.get('initialization_notice', 'No externally seeded scientific claims.')
        return context

    def search(self, query='', kind='all', hypothesis_ref=None, tags=None, status=None, offset=0, limit=8, include_history=True):
        if not include_history: return super().search(query, kind, hypothesis_ref, tags, status, offset, limit)
        words = terms(query); clauses = ['1']; params = []
        if words:
            parts = []; long = [w for w in words if len(w) >= 3]
            if long:
                parts.append('d.ref IN (SELECT ref FROM memory_fts WHERE memory_fts MATCH ?)')
                params.append(' OR '.join('"' + w.replace('"','""') + '"' for w in long))
            parts.append('d.ref IN (SELECT ref FROM doc_tags WHERE tag IN (' + ','.join('?' for _ in words) + '))')
            params.extend(words); clauses.append('(' + ' OR '.join(parts) + ')')
        if kind == 'all': clauses.append("d.kind!='process'")
        else: clauses.append('d.kind=?'); params.append('hypothesis' if kind == 'card' else kind)
        if hypothesis_ref:
            self.record(hypothesis_ref, 'hypothesis'); clauses.append('d.ref IN (SELECT ref FROM doc_hypotheses WHERE hypothesis_ref=?)'); params.append(hypothesis_ref)
        if status: clauses.append('d.status=?'); params.append(status)
        if tags:
            clauses.append('d.ref IN (SELECT ref FROM doc_tags WHERE tag IN (' + ','.join('?' for _ in tags) + '))'); params.extend(t.casefold() for t in tags)
        where = ' FROM search_docs d WHERE ' + ' AND '.join(clauses)
        total = self.db.execute('SELECT count(*)' + where, params).fetchone()[0]
        rows = self.db.execute('SELECT ref,kind,status,text' + where + ' ORDER BY seq DESC,ref LIMIT ? OFFSET ?', [*params, limit, offset])
        hits = [{'ref': 'card:'+ref if kind=='card' else ref, 'kind': k, 'recorded_status': s,
            'preview': text[:800], 'lifecycle': lifecycle(self.db, ref), 'review_blocked': self.blocked(ref)} for ref,k,s,text in rows]
        return {'hits': hits, 'total': total, 'next_offset': offset+limit if total>offset+limit else None,
            'scope': 'Full current lawful archive including history; lifecycle/ranking is not scientific truth.'}
