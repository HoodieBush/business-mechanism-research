"""Sequential research steps and persisted review jobs, outside transactions."""
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import shutil

from ..common import Pending, digest, encoded, sha, write_json
from ..runtime_memory import MEMORY_PROMPT
from ..runtime_robust import ROBUST_PROMPT
from ..critic_v01.shared import CheckedRuntime
from .budget import StudyJournal
from .contracts import Review
from .evidence import export_snapshot
from .review import Reviewer, ReviewerRuntime


class ResearchRuntime(CheckedRuntime):
    def initial(self):
        context = self.ws.context()
        context['session_progress'] = {'responses_completed': self.cp['responses'], 'continuing_same_research': self.cp['responses'] > 0}
        context['uncheckpointed_work'] = self.ws.checkpoint_work()
        prompt = (Path(__file__).parent / 'researcher_prompt.txt').read_text()
        scientific = ROBUST_PROMPT.replace('本配置提供结构化事实核对及记忆复核，不增加研究角色。', '本配置提供结构化事实核对及记忆复核。')
        return [{'role': 'system', 'content': prompt + MEMORY_PROMPT + scientific},
            {'role': 'user', 'content': encoded(context)}]

    def remaining(self):
        if isinstance(self.journal, StudyJournal): return self.journal.snapshot()['remaining_admission_tokens']
        return super().remaining()

    def prepare_payload(self, payload):
        payload = super().prepare_payload(payload)
        if isinstance(self.journal, StudyJournal):
            from token_budget import reservation_bound
            if reservation_bound(payload) > self.journal.snapshot()['remaining_admission_tokens']:
                self.compact(); payload = self.constrained(self.payload())
            left = self.journal.study.snapshot()['remaining_http_attempts']
            if left <= 3:
                payload['messages'].append({'role': 'user', 'content':
                    f'全研究所有角色共同还剩{left}次HTTP额度。保存已理解工作、回应相关意见，明确未决；不要求正面结果，不重复已有检查。'})
        return payload


def replace_refs(value, mapping):
    if isinstance(value, str):
        if value in mapping: return mapping[value]
        for old, new in mapping.items():
            if old.startswith(('file:', 'check:')): value = value.replace(old, new)
        return value
    if isinstance(value, list): return [replace_refs(x, mapping) for x in value]
    if isinstance(value, dict): return {k: replace_refs(v, mapping) for k, v in value.items()}
    return value


class ResearchRun:
    def __init__(self, root, workspace, model, study_budget, *, owner_journal=None, reviewer_journal_factory=None):
        self.root = Path(root).resolve(); self.ws, self.model, self.budget = workspace, model, study_budget
        workspace.study_budget = study_budget
        self.reviewer_journal_factory = reviewer_journal_factory
        self.journal = owner_journal or StudyJournal(workspace, model, study_budget, 'researcher', memory=True)
        self.runtime = ResearchRuntime(workspace, model, journal=self.journal)

    def prepare_job(self, job):
        directory = self.root / 'reviews' / job['ref']
        inputs = directory / 'inputs'
        if not inputs.exists():
            staging = directory / 'projection_pending'
            if staging.exists():
                # Only this app-created, unpaid projection staging area can be
                # rebuilt. Research originals and paid reviewer work are not deleted.
                if digest(self.ws.record(job['target_ref'])) != job['target_version']: raise Pending('job target changed while projecting')
                shutil.rmtree(staging)
            export_snapshot(self.ws, staging, job['target_ref'])
            packet = json.loads((staging/'packet.json').read_text())
            if job['parent_review_ref']:
                packet['previous_feedback'] = self.ws.record(job['parent_review_ref'])
                packet['researcher_responses'] = [b for b in self.ws.records('review_response') if b['review_ref'] == job['parent_review_ref']]
            write_json(staging/'packet.json', packet)
            manifest = json.loads((staging/'manifest.json').read_text()); manifest['files_sha256']['packet.json'] = sha(staging/'packet.json')
            write_json(staging/'manifest.json', manifest)
            staging.rename(inputs)
        packet = json.loads((inputs/'packet.json').read_text())
        if packet['target_ref'] != job['target_ref'] or packet['target_version'] != job['target_version']:
            raise Pending('prepared review packet target identity differs')
        with self.ws.db:
            old = self.ws.db.execute('SELECT manifest_sha FROM review_inputs WHERE job_ref=?', (job['ref'],)).fetchone()
            if old and old[0] != sha(inputs/'manifest.json'): raise Pending('prepared review inputs changed')
            self.ws.db.execute('INSERT OR IGNORE INTO review_inputs VALUES (?,?,?)', (job['ref'], str(inputs), sha(inputs/'manifest.json')))
        return inputs

    def import_feedback(self, job, reviewer):
        if self.ws.job(job['ref'])['status'] == 'completed': return
        original = reviewer.report()
        if not original: raise Pending('reviewer has no completed review')
        mapping = {'directory:'+name: 'job:'+job['ref']+'/directory:'+name for name in ('all','related','results')}
        imported = self.ws.science / 'review_runs' / job['ref']
        for path in reviewer.science.rglob('*'):
            if not path.is_file() or any(p in ('tmp','.matplotlib') for p in path.relative_to(reviewer.science).parts): continue
            target = imported / path.relative_to(reviewer.science); target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if sha(target) != sha(path): raise Pending('imported reviewer artifact changed')
            else: shutil.copyfile(path, target)
        actions = [(ref, json.loads(body)) for ref, body in reviewer.db.execute('SELECT ref,body FROM actions ORDER BY rowid')]
        notes = [json.loads(body) for body, in reviewer.db.execute("SELECT body FROM records WHERE kind='checkpoint' ORDER BY rowid")]
        for ref, _ in actions: mapping[ref] = 'C' + digest([job['ref'],ref])[:16]
        for note in notes: mapping[note['ref']] = 'N' + digest([job['ref'],note['ref']])[:16]
        new_ref = 'Q' + digest([job['ref'],original['ref']])[:16]
        mapping[original['ref']] = new_ref
        with self.ws.db:
            for old_ref, relative in reviewer.db.execute('SELECT ref,path FROM files'):
                path = imported / (Path(relative).relative_to('artifacts'))
                mapping[old_ref] = self.ws.file_ref(path, 'review_computation_seen')['ref']
            for ref, action in actions:
                self.ws.add('review_action', {'_record_ref': mapping[ref], 'author': 'critic_tool',
                    'job_ref': job['ref'], 'origin_action_ref': ref, 'operation': replace_refs(action, mapping),
                    'hypothesis_refs': self.ws.target_hypotheses(job['target_ref'])})
            for note in notes:
                self.ws.add('review_note', {'_record_ref': mapping[note['ref']], 'author': 'critic',
                    'job_ref': job['ref'], 'original_ref': note['ref'], 'note': replace_refs(note, mapping)})
            body = replace_refs({k: original[k] for k in Review.model_fields}, mapping)
            self.ws.apply_review(job['ref'], body, author='independent_critic', original_ref=original['ref'], record_ref=new_ref)
        self.ws._publish()

    def review_job(self, job):
        inputs = self.prepare_job(job)
        settings = {'research_profile': 'paired_critic_v1', 'model_config': self.model,
            'limits': {**self.ws.settings['limits'], 'max_http_attempts': 12 if job['round'] == 1 else 6}}
        reviewer_root = self.root/'reviews'/job['ref']/'critic'
        reviewer = Reviewer(reviewer_root, inputs, settings, reopen=reviewer_root.exists())
        try:
            journal = self.reviewer_journal_factory(reviewer, job) if self.reviewer_journal_factory else StudyJournal(
                reviewer, self.model, self.budget, 'critic:'+job['ref'])
            with self.ws.db: self.ws.db.execute("UPDATE review_jobs SET status='running' WHERE ref=?", (job['ref'],))
            result = ReviewerRuntime(reviewer, self.model, journal=journal).run(settings['limits']['max_http_attempts'])
            if result['status'] != 'completed': raise Pending('review job pending: '+result['reason'])
            self.import_feedback(job, reviewer)
        finally: reviewer.close()

    def run(self, owner_steps=80):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = (self.root/'research_run.lock').open('a')
        try:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise Pending('research run is owned by another controller')
            for _ in range(owner_steps):
                with self.ws.db: self.ws.try_seal_report()
                self.ws._publish()
                if self.ws.report():
                    self.runtime.cp.update(status='completed', reason=None); self.runtime.save()
                    return {'status':'completed','report_ref':self.ws.report()['ref']}
                pending = self.ws.jobs('pending') + self.ws.jobs('running')
                if pending:
                    if self.ws.settings['verification_mode'] == 'independent':
                        self.review_job(pending[0]); continue
                    current = pending[0]
                    attempts = self.journal.state['attempts'] if isinstance(self.journal,StudyJournal) else self.runtime.cp['responses']
                    with self.ws.db:
                        self.ws.db.execute('INSERT OR IGNORE INTO self_review_clock VALUES (?,?)',(current['ref'],attempts))
                    started = self.ws.db.execute('SELECT start_attempt FROM self_review_clock WHERE job_ref=?',(current['ref'],)).fetchone()[0]
                    if attempts - started >= current['review_http_limit']:
                        raise Pending('self review job reached the same registered per-review HTTP ceiling; preserve work and disagreement')
                    for job in pending: self.prepare_job(job)
                result = self.runtime.run(1)
                if result['status'] == 'completed': return result
                if result['reason'] != 'registered model-step slice reached; study can resume':
                    return result
            return {'status':'pending','reason':'registered controller slice reached; shared counters and pending jobs retained'}
        except Pending as error:
            return {'status':'pending','reason':str(error)}
        finally: lock.close()
