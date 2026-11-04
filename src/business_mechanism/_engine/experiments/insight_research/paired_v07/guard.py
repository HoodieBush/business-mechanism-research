"""Same persisted request/time/no-structural-progress protection for all roles."""
import json,time
from ..common import Pending,digest,encoded
from ..paired_v01.budget import StudyJournal

def meaningful(value):
    if isinstance(value,list):return [meaningful(x) for x in value]
    if isinstance(value,dict):return {k:meaningful(v) for k,v in value.items() if k not in ('ref','created_at','author','source_state_ref')}
    return value

class ProgressGuard:
    def __init__(self,root,owner,budget,*,clock=time.time):
        self.root,self.owner,self.budget,self.clock=root,owner,budget,clock
        self.policy=owner.settings.get('execution_policy',{})
        self.wall=self.policy.get('wall_seconds',7200);self.warn=self.policy.get('warn_after_requests',8);self.stop=self.policy.get('stop_after_requests',16)
        if not 0<self.warn<self.stop or self.wall<=0:raise ValueError('positive registered guard limits required')
        started=clock()
        with budget.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS execution_control(id INTEGER PRIMARY KEY,started REAL,deadline REAL,fingerprint TEXT,last_progress_request INTEGER)')
            db.execute('INSERT OR IGNORE INTO execution_control VALUES(1,?,?,NULL,0)',(started,started+self.wall))

    def fingerprint(self):
        # Read/search or timestamp-only changes do not pretend to be new work.
        items=[]
        for body, in self.owner.db.execute("SELECT body FROM records WHERE kind NOT IN ('review_action','review_note')"):
            items.append(digest(meaningful(json.loads(body))))
        file_hashes={h for p,h in self.owner.db.execute('SELECT path,hash FROM files') if p.endswith('rows.csv') or p.endswith('_stdout.txt')}
        import sqlite3
        for path in self.root.glob('reviews/*/critic/private/critic.sqlite'):
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                items.extend(digest(meaningful(json.loads(b))) for b, in db.execute('SELECT body FROM records'))
                file_hashes.update(h for p,h in db.execute('SELECT path,hash FROM files') if p.endswith('rows.csv') or p.endswith('_stdout.txt'))
        return digest([sorted(set(items)),sorted(file_hashes)])

    def inspect(self):
        count=self.budget.snapshot()['http_attempts'];fingerprint=self.fingerprint()
        with self.budget.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            started,deadline,previous,last=db.execute('SELECT started,deadline,fingerprint,last_progress_request FROM execution_control WHERE id=1').fetchone()
            if previous!=fingerprint:
                last=count;db.execute('UPDATE execution_control SET fingerprint=?,last_progress_request=? WHERE id=1',(fingerprint,last))
        return {'started_at_unix':started,'deadline_unix':deadline,'remaining_wall_seconds':deadline-self.clock(),
                'requests_without_structural_progress':count-last,'warn_after_requests':self.warn,'stop_after_requests':self.stop,
                'meaning':'Saved scientific interpretation or new data-content signature; not correctness or complete semantic-loop detection.'}

    def admit(self,timeout):
        s=self.inspect()
        if s['remaining_wall_seconds']<timeout+45:raise Pending('persistent study wall deadline cannot admit a new request; paid work retained')
        if s['requests_without_structural_progress']>=self.stop:raise Pending('registered no-structural-progress ceiling reached; retain context, not scientific refutation')
        return s

class GuardedJournal(StudyJournal):
    def __init__(self,*args,guard,**kwargs):super().__init__(*args,**kwargs);self.guard=guard

    def call(self,payload):
        paid=self.state.get('inflight') or self.state.get('delivery')
        if paid:
            from ..runtime_memory import reconstruct_request
            # Never regenerate a time-dependent notice for an already paid request.
            payload=reconstruct_request(self.ws.private,paid['attempt'])
        else:
            s=self.guard.admit(self.config.get('request_timeout_seconds',600))
            left=self.study.snapshot()['remaining_http_attempts']
            role_left=self.ws.settings['limits']['max_http_attempts']-self.state['attempts']
            if min(left,role_left)<=8:
                payload={**payload,'messages':[*payload['messages'],{'role':'user','content':
                    f'Shared remaining model requests: {left}; this role/review: {role_left}. Count all roles. Save actual checks and unresolved scope; do not repeat completed work. A checkpoint does not imply scientific refutation.'}]}
            if s['requests_without_structural_progress']>=self.guard.warn:
                payload={**payload,'messages':[*payload['messages'],{'role':'user','content':
                    'Execution notice: several requests produced no saved scientific interpretation or new data-content signature. Save a source-linked checkpoint describing the concrete uncertainty/next step, change the analysis, or deliver an honest unresolved stage. Reading and recomputation remain available; do not repeat unchanged work.'}]}
            if len(encoded(payload).encode())>self.ws.settings['limits']['max_request_bytes']:
                raise Pending('request including execution notice exceeds registered context guard; retain complete paid work')
        return super().call(payload)
