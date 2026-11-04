"""A project survives finite stages; old studies/paid work never get reset.

Registration is deterministic and has no model calls. A researcher supplies
the next question; there is no forced algorithm role or automatic positive
result. The controller can execute an already constructed registered runner.
"""
from contextlib import contextmanager
from datetime import date
import fcntl,json,re,shutil,sqlite3,os,time
from pathlib import Path
from ..common import Pending,digest,encoded,sha,write_json,now
from ..paired_v12.continuation import capture
from ..paired_v01.evidence import EvidenceView
from .projection import export_stage

def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',value):raise ValueError('plain bounded stage identifier required')
    return value

class Project:
    def __init__(self,root,identity,*,create=False):
        self.root=Path(root).resolve();self.path=self.root/'project.sqlite';self.identity=identity
        if not identity.get('project_budget_id') or not identity.get('model_config_sha256'):raise ValueError('explicit existing budget and model identity required')
        if any(type(identity.get(k)) is not int or identity[k]<=0 for k in ('max_stages','token_allowance','wall_seconds')):raise ValueError('explicit positive project stage/token/persistent wall ceilings required')
        if create:
            self.root.mkdir(parents=True,exist_ok=False)
            with sqlite3.connect(self.path) as db:
                db.executescript('CREATE TABLE identity(body TEXT); CREATE TABLE stages(id TEXT PRIMARY KEY,body TEXT,status TEXT); CREATE TABLE exposures(id TEXT PRIMARY KEY,body TEXT); CREATE TABLE control(started REAL,deadline REAL);')
                db.execute('INSERT INTO identity VALUES (?)',(encoded(identity),))
                started=time.time();db.execute('INSERT INTO control VALUES (?,?)',(started,started+identity['wall_seconds']))
        with self.connect() as db:
            if json.loads(db.execute('SELECT body FROM identity').fetchone()[0])!=identity:raise ValueError('project identity differs; never reset')
    def connect(self):return sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=30)
    @contextmanager
    def lock(self):
        with (self.root/'controller.lock').open('a') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise Pending('project controller is active')
            yield
    def stages(self):
        with self.connect() as db:return [json.loads(b)|{'status':s} for b,s in db.execute('SELECT body,status FROM stages ORDER BY rowid')]
    def exposures(self):
        with self.connect() as db:return [json.loads(b) for b, in db.execute('SELECT body FROM exposures ORDER BY rowid')]
    def validate_slice(self,s):
        if set(s)!={'dataset_id','start','end','sha256'} or not s['dataset_id'] or not re.fullmatch('[0-9a-f]{64}',s['sha256']):raise ValueError('exact immutable dataset identity/date span/source hash required')
        if date.fromisoformat(s['start'])>date.fromisoformat(s['end']):raise ValueError('invalid observation interval')
    def already_seen(self,s):
        self.validate_slice(s)
        return [x for x in self.exposures() if x['dataset_id']==s['dataset_id'] and not (s['end']<x['start'] or s['start']>x['end'])]
    def record_exposure(self,s,*,stage_id,source_receipt):
        self.validate_slice(s)
        if not source_receipt or not isinstance(source_receipt,dict) or not source_receipt.get('sha256'):raise ValueError('source exposure receipt required')
        item={**s,'stage_id':identifier(stage_id),'source_receipt':source_receipt,'nature':'seen_observations_not_new_validation'}
        with self.lock(),self.connect() as db:db.execute('INSERT OR IGNORE INTO exposures VALUES (?,?)',(digest(item),encoded(item)))
    def register_stage(self,stage_id,*,run_root,budget,question,parent_stage=None,declared_fresh=()):
        stage_id=identifier(stage_id)
        if not question.strip():raise ValueError('researcher-selected next question required')
        with self.lock():
            stages=self.stages()
            if len(stages)>=self.identity['max_stages']:raise Pending('registered project stage ceiling reached; do not loop by creating new stages')
            with self.connect() as db:deadline=db.execute('SELECT deadline FROM control').fetchone()[0]
            if time.time()>=deadline:raise Pending('persistent project deadline reached; retain research and fees')
            if self.cumulative_cost()['accounted_tokens']+budget.identity['token_allowance']>self.identity['token_allowance']:raise Pending('remaining project-stage envelope cannot admit this finite allocation')
            if any(s['status'] in ('registered','running','recovery_required') for s in stages):raise Pending('finish/drain the current stage before a new registered stage')
            if stages and parent_stage!=stages[-1]['id']:raise ValueError('new stage must explicitly acknowledge the latest handover')
            if not stages and parent_stage is not None:raise ValueError('unknown parent stage')
            for s in declared_fresh:
                if self.already_seen(s):raise ValueError('already_seen_observations: a new workspace cannot restore unseen status')
            if budget.identity.get('project_budget_id')!=self.identity['project_budget_id']:raise ValueError('same global budget required')
            if budget.identity.get('model_config_sha256')!=self.identity['model_config_sha256']:raise ValueError('registered common model identity required')
            root=Path(run_root).resolve()
            if (root/'continuation_import.json').exists():raise ValueError('a migrated same-case allocation is not a new stage; register explicit recovery/accounting instead of counting inherited rows as new requests')
            if budget.path!=root/'common_budget.sqlite':raise ValueError('stage budget must belong to this run')
            if any(s['run_root']==str(root) or s['budget_path']==str(budget.path) for s in stages):raise ValueError('new stage cannot reuse an old run/allocation')
            item={'id':stage_id,'run_root':str(root),'budget_path':str(budget.path),'budget_identity':budget.identity,'question':question,'parent_stage':parent_stage,
                'declared_fresh':list(declared_fresh),'archives':self.archives(),'registered_at':now(),'scientific_status':'not_adjudicated'}
            with self.connect() as db:db.execute('INSERT INTO stages VALUES (?,?,?)',(stage_id,encoded(item),'registered'))
            return item
    def archives(self):
        out=[]
        for s in self.stages():
            if not s.get('archive'):continue
            if sha(Path(s['handover_path']))!=s['handover_sha256']:raise Pending('immutable stage handover changed')
            if sha(Path(s['archive']['path'])/'manifest.json')!=s['archive']['manifest_sha256']:raise Pending('immutable stage archive changed')
            out.append(s['archive'])
        return out
    def cumulative_cost(self):
        # Existing StudyJournal keys are ROLE-LOCAL (role, attempt), not globally
        # unique. A new independent allocation can legitimately reuse them.
        # Namespace by immutable stage budget identity; same-case copied ledgers
        # are deliberately refused at new-stage registration, never deduped by
        # coincidental key/content equality.
        rows={}
        for s in self.stages():
            with sqlite3.connect(Path(s['budget_path']).as_uri()+'?mode=ro',uri=True) as db:
                identity=json.loads(db.execute('SELECT body FROM identity').fetchone()[0])
                if identity!=s['budget_identity']:raise Pending('stage budget identity changed')
                for row in db.execute('SELECT key,role,bound,actual,payload_hash,status FROM attempts'):
                    key=digest([s['budget_path'],s['budget_identity'],row[0]])
                    rows[key]=row
        known=sum(r[3] or 0 for r in rows.values());used=sum(r[2] if r[3] is None else r[3] for r in rows.values())
        return {'http_attempts':len(rows),'reported_tokens':known,'unknown_or_inflight_reserve':used-known,'accounted_tokens':used,'by_durable_request':rows,
            'scope':'All independent stage allocations remain cumulative, with role-local keys namespaced by the immutable ledger identity. Migrated same-case ledgers cannot masquerade as new stages. The same existing project ledger remains authoritative for admission; no new authorization.'}
    def _deduplicate(self,archive):
        # Store one immutable content copy even when later lawful projections
        # mention a historical materialized source again. Never use symlinks.
        objects=self.root/'objects';objects.mkdir(exist_ok=True)
        manifest=json.loads((archive/'manifest.json').read_text())
        for name,h in manifest['files_sha256'].items():
            source=archive/name
            if source.is_symlink() or not source.resolve().is_relative_to(archive) or sha(source)!=h:raise Pending('unsafe archive source')
            obj=objects/h
            if obj.exists():
                if obj.is_symlink() or sha(obj)!=h:raise Pending('immutable object changed')
            else:shutil.copyfile(source,obj);obj.chmod(0o444)
            source.unlink();os.link(obj,source)
    def close_stage(self,stage_id,runner,result,*,next_question,scientific_note):
        identifier(stage_id)
        if result.get('status') not in ('completed','pending') or not scientific_note.strip():raise ValueError('explicit execution result and scoped scientific note required')
        with self.lock():
            item=next(s for s in self.stages() if s['id']==stage_id)
            if item['status'] not in ('registered','running','recovery_required'):raise ValueError('stage already sealed; do not rewrite its endpoint')
            if Path(item['run_root'])!=runner.root.resolve() or item['budget_identity']!=runner.budget.identity:raise ValueError('actual runner identity mismatch')
            final=runner.ws.report()
            if (result['status']=='completed')!=bool(final):raise ValueError('execution completion must agree with the actual F, not caller prose')
            # Capture refuses active controllers, undrained paid responses,
            # missing paid receipts or altered scientific originals.
            before=capture(runner.root,base=runner.root.parent)
            with runner.budget.connect() as db:paid={r for r, in db.execute('SELECT DISTINCT role FROM attempts')}
            unresolved_paid=[j['ref'] for j in runner.ws.jobs() if 'critic:'+j['ref'] in paid and j['status'] not in ('completed','deferred')]
            if unresolved_paid:
                item['paid_unfinished_jobs']=unresolved_paid
                with self.connect() as db:db.execute('UPDATE stages SET body=?,status=? WHERE id=?',(encoded({k:v for k,v in item.items() if k!='status'}),'recovery_required',stage_id))
                raise Pending('paid reviewer work remains unfinished; keep exact run for registered recovery before advancing')
            archive=self.root/'archives'/stage_id
            prepared=self.root/'preparing'/(stage_id+'.json')
            if prepared.exists():
                if json.loads(prepared.read_text())!=before:raise Pending('prepared handover source changed; preserve original instead of resetting')
            else:write_json(prepared,before)
            if (archive/'manifest.json').exists():
                view=EvidenceView(archive)
                try:
                    if view.manifest['record_original_versions']!={r:digest(json.loads(b)) for r,b in runner.ws.db.execute('SELECT ref,body FROM records')}:raise Pending('prepared archive source versions differ')
                finally:view.close()
            elif archive.exists():raise Pending('incomplete archive retained; inspect partial export before explicit recovery')
            else:
                if not runner.ws.records('state'):raise Pending('save an actual research checkpoint before stage handover')
                with (runner.ws.private/'runtime.lock').open('a') as lock:
                    fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
                    runner.ws.db.execute('BEGIN')
                    try:export_stage(runner.ws,archive)
                    finally:runner.ws.db.rollback()
            after=capture(runner.root,base=runner.root.parent)
            if before!=after:raise Pending('stage changed during handover; retain both captures, do not advance')
            self._deduplicate(archive)
            descriptor={'stage_id':stage_id,'path':str(archive),'manifest_sha256':sha(archive/'manifest.json')}
            handover={'stage_id':stage_id,'execution_result':result,'scientific_note':scientific_note,'next_question':next_question,
                'original_checkpoint':before,'all_role_budget':runner.budget.snapshot(),'cumulative_stage_cost':self.cumulative_cost(),'source_exposures':self.exposures(),'archive':descriptor,
                'open_review_jobs':runner.ws.jobs('pending')+runner.ws.jobs('running'),'pending_object_revisions':runner.ws.pending_repairs(),
                'unanswered_opinions':runner.ws.unanswered(),'assessment_statuses':{a['ref']:a['status'] for a in runner.ws.records('assessment')},
                'scientific_certification':False,'meaning':'F ends this finite stage only. Execution pause is not scientific refutation. Old originals, paid logs and unresolved work remain preserved at their original run root.'}
            path=self.root/'handovers'/(stage_id+'.json');write_json(path,handover)
            item.update(archive=descriptor,handover_path=str(path),handover_sha256=sha(path),scientific_status='scoped_claims_and_unresolved_work',execution_status=result['status'],next_question=next_question)
            with self.connect() as db:db.execute('UPDATE stages SET body=?,status=? WHERE id=?',(encoded({k:v for k,v in item.items() if k!='status'}),'sealed',stage_id))
            return handover
    def execute(self,stage_id,runner,*,steps=160):
        """Run an already registered runner; direction is in its own saved state.

        This does not bypass study registration or launch/resume authorization.
        Call close_stage explicitly with evidence-linked scientific context.
        """
        with self.lock(),self.connect() as db:
            item=next(s for s in self.stages() if s['id']==stage_id)
            if item['status'] not in ('registered','running','recovery_required'):raise ValueError('sealed stage cannot restart')
            if Path(item['run_root'])!=runner.root.resolve() or item['budget_identity']!=runner.budget.identity:raise ValueError('runner identity mismatch')
            deadline=db.execute('SELECT deadline FROM control').fetchone()[0]
            if time.time()>=deadline:raise Pending('persistent project deadline reached; paid recovery/archival remains available')
            if steps>0:
                import importlib.util
                from ..common import ROOT
                spec=importlib.util.spec_from_file_location('project_stage_registry',ROOT/'scripts/research_workflow.py');wf=importlib.util.module_from_spec(spec);spec.loader.exec_module(wf)
                sid=runner.budget.identity.get('study_id');rid=runner.budget.identity.get('run_id')
                path,_=wf.verify(ROOT,sid)
                if (path.parent/'decision.json').exists():raise ValueError('closed allocation cannot restart through the project controller')
                receipt=path.parent/'executions'/(identifier(rid)+'.json')
                if not receipt.exists() or json.loads(receipt.read_text()).get('status') not in ('started','process_error'):raise ValueError('explicit registered launch/resume required before paid project execution')
                if runner.root.resolve()!=path.parent/'results'/rid:raise ValueError('runner must match its registered study/run output')
            # Common guard is used by ALL roles, and never extends a deadline
            # after a new stage or controller restart.
            with runner.budget.connect() as local:local.execute('UPDATE execution_control SET deadline=min(deadline,?) WHERE id=1',(deadline,))
            db.execute("UPDATE stages SET status='running' WHERE id=?",(stage_id,))
        return runner.run(steps)
