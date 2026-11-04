"""Copy only an owned stopped run, preserving every role's paid work and cost.

New identities are created in a new run; original identities are separately
retained. Only derived review-input paths relocate. Scientific bodies, request
archives, tool cursors, all local charges and project charges are not reset.
"""
from contextlib import ExitStack
from copy import deepcopy
import fcntl,json,shutil,sqlite3
from pathlib import Path
from ..common import ROOT,Pending,digest,sha,write_json
from ..continuation import allowed as owner_allowed
from ..critic_v01.continuation import owned as critic_allowed
from ..paired_v01.budget import StudyBudget
from .review import Reviewer
from .workspace import ResearchWorkspace


def read(path):return json.loads(Path(path).read_text())


def allowed(name):
    parts=Path(name).parts
    if not parts or any(p in ('..','tmp','.matplotlib') for p in parts):return False
    if name in ('common_budget.sqlite','runtime_status.json','common_budget_snapshot.json'):return True
    if parts[0]=='researcher':
        return str(Path(*parts[1:])).startswith('private/context_archives/') or owner_allowed(str(Path(*parts[1:])))
    if len(parts)>3 and parts[0]=='reviews':
        if parts[2]=='inputs':return True
        if parts[2]=='critic':return str(Path(*parts[3:])).startswith('private/context_archives/') or critic_allowed(str(Path(*parts[3:])))
    return False


def capture(parent,*,base=ROOT):
    parent=Path(parent).resolve();base=Path(base).resolve()
    with ExitStack() as stack:
        lock=stack.enter_context((parent/'research_run.lock').open('rb'))
        try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise Pending('research controller is live; do not fork its paid work')
        roles=[parent/'researcher',*parent.glob('reviews/*/critic')];role_states={}
        for role in roles:
            transport_path=role/'private/transport.json';checkpoint_path=role/'private/checkpoint.json'
            state=read(transport_path) if transport_path.exists() else {'attempts':0,'accounted_tokens':0}
            cp=read(checkpoint_path) if checkpoint_path.exists() else {'status':'unstarted','pending':None}
            if cp['status']=='unstarted':
                if state['attempts'] or list((role/'private/http').glob('*.json')):raise Pending('paid role missing checkpoint; do not fabricate recovery')
                if role.name=='critic':
                    with sqlite3.connect((role/'private/critic.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as fresh_db:
                        if any(fresh_db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() for table in ('records','operations','actions')):raise Pending('unstarted critic contains uncheckpointed actions')
            if state.get('inflight') or state.get('delivery') or cp.get('pending'):
                raise Pending('drain and acknowledge every paid role before capture')
            if cp['status'] not in ('pending','completed','unstarted'):raise Pending('role has no stopped checkpoint')
            role_name='researcher' if role.name=='researcher' else 'critic:'+role.parent.name
            role_states[role_name]=state
            for n in range(1,state['attempts']+1):
                if not (role/'private/http'/f'{n}.json').is_file():raise Pending('paid role receipt missing')
        identity=read(parent/'researcher/private/identity.json')
        with sqlite3.connect((parent/'common_budget.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            budget_identity=json.loads(db.execute('SELECT body FROM identity').fetchone()[0])
            rows=[list(r) for r in db.execute('SELECT * FROM attempts')]
            if any(r[-1]=='in_flight' for r in rows):raise Pending('common study reservation still in flight')
        for role,state in role_states.items():
            selected=[r for r in rows if r[1]==role]
            if len(selected)!=state['attempts'] or sum(r[2] if r[3] is None else r[3] for r in selected)!=state['accounted_tokens']:
                raise ValueError('role and common cumulative charges disagree')
        if set(r[1] for r in rows)-set(role_states):raise ValueError('common ledger has an uncaptured role')
        with sqlite3.connect((parent/'researcher/private/records.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            if db.execute("SELECT 1 FROM operations WHERE status!='completed' LIMIT 1").fetchone():raise Pending('owner has a prepared operation')
            for ref,body in db.execute('SELECT ref,body FROM records'):
                if read(parent/'researcher/science/records'/(ref+'.json'))!=json.loads(body):raise ValueError('published scientific original differs')
            for ref,name,version in db.execute('SELECT ref,path,hash FROM files'):
                file=parent/'researcher'/name
                if not owner_allowed(name) or file.is_symlink() or not file.is_file() or sha(file)!=version:raise ValueError('received file changed: '+ref)
        paths=[]
        for p in parent.rglob('*'):
            name=str(p.relative_to(parent))
            if allowed(name) and p.is_symlink():raise ValueError('continuation cannot follow symlinks')
            if allowed(name) and p.is_file():paths.append(p)
        return {'format':'paired_continuation_v1','parent_root':str(parent.relative_to(base)),
            'parent_identity':identity,'parent_budget_identity':budget_identity,
            'inherited_attempts':len(rows),'inherited_tokens':sum(r[2] if r[3] is None else r[3] for r in rows),
            'sha256':{str(p.relative_to(parent)):sha(p) for p in paths},
            'scope':'Same case and owned process, not a new independent sample; no evaluator or hidden mechanisms.'}


def copy_files(parent,dest,manifest,prefix,*,skip_identity=False):
    for name,version in manifest['sha256'].items():
        if not name.startswith(prefix):continue
        relative=Path(name).relative_to(prefix)
        if skip_identity and str(relative)=='private/identity.json':relative=Path('private/parent_identity.json')
        source=parent/name;target=dest/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if sha(target)!=version:raise Pending('continuation copy differs: '+name)


def prepare(output,manifest,question,world,settings,budget_identity,*,base=ROOT):
    output=Path(output).resolve();base=Path(base).resolve();parent=(base/manifest['parent_root']).resolve()
    if not parent.is_relative_to(base) or not output.is_relative_to(base):raise ValueError('owned project paths required')
    if capture(parent,base=base)!=manifest:raise ValueError('parent changed after frozen continuation capture')
    if output.exists():raise ValueError('new continuation run required; never overwrite a run')
    old=manifest['parent_identity'];prior=manifest['parent_budget_identity']
    for key in ('token_allowance','max_http_attempts','project_budget_id'):
        if budget_identity[key]!=prior[key]:raise ValueError('continuation cannot reset or expand common '+key)
    for key in ('model_config','limits','verification_mode','research_profile'):
        if settings[key]!=old['settings'][key]:raise ValueError('continuation cannot silently change '+key)
    if question!=old['question']:raise ValueError('continuation question differs')
    output.mkdir(parents=True)
    for name in ('common_budget.sqlite','runtime_status.json','common_budget_snapshot.json'):
        if name in manifest['sha256']:
            target=output/'parent_run'/name;target.parent.mkdir(exist_ok=True)
            shutil.copyfile(parent/name,target)
            if sha(target)!=manifest['sha256'][name]:raise ValueError('parent administrative original differs')
    fresh=ResearchWorkspace(output/'researcher',question,world,settings)
    try:
        for key in ('public_inputs','environment_identity','reused_sources','tool_contract','question'):
            if fresh.identity[key]!=old[key]:raise ValueError('continuation changes '+key)
        for key in ('private_scene_switches','robust_sources','memory_sources'):
            if fresh.identity['settings'].get(key)!=old['settings'].get(key):raise ValueError('continuation changes common '+key)
    finally:fresh.close()
    # Fresh identity stays explicit; imported scientific DB and paid archives
    # are byte-identical copies. No old scientific body is rewritten.
    copy_files(parent,output/'researcher',manifest,'researcher/',skip_identity=True)
    for name,version in manifest['sha256'].items():
        if not name.startswith('reviews/') or Path(name).parts[2]!='inputs':continue
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(parent/name,target)
        if sha(target)!=version:raise Pending('evidence projection copy differs')
    dbpath=output/'researcher/private/records.sqlite'
    with sqlite3.connect(dbpath) as db:
        for job,path in db.execute('SELECT job_ref,path FROM review_inputs').fetchall():
            relative=Path(path).relative_to(parent)
            db.execute('UPDATE review_inputs SET path=? WHERE job_ref=?',(str(output/relative),job))
    for role in parent.glob('reviews/*/critic'):
        job=role.parent.name
        with sqlite3.connect(dbpath) as db:round_no=db.execute('SELECT round FROM review_jobs WHERE ref=?',(job,)).fetchone()[0]
        config={'research_profile':'paired_critic_v1','model_config':settings['model_config'],
            'limits':{**settings['limits'],'max_http_attempts':18}}
        target=output/'reviews'/job/'critic'
        peer=Reviewer(target,output/'reviews'/job/'inputs',config);peer.close()
        copy_files(parent,target,manifest,'reviews/'+job+'/critic/',skip_identity=True)
        previous=read(role/'private/identity.json')['settings']['limits'];new=config['limits']
        if any(v!=new[k] for k,v in previous.items() if k!='max_http_attempts'):
            raise ValueError('continuation changes critic resources')
        if not previous['max_http_attempts']<=new['max_http_attempts']<=previous['max_http_attempts']+6:
            raise ValueError('critic extension must be bounded by six cumulative opportunities')
        transport=read(target/'private/transport.json') if (target/'private/transport.json').exists() else {'attempts':0,'accounted_tokens':0}
        write_json(target/'private/continuation.json',{'same_review_not_new_sample':True,
            'inherited_http_attempts':transport['attempts'],'inherited_accounted_tokens':transport['accounted_tokens'],
            'new_cumulative_http_cap':new['max_http_attempts'],'parent':str(role.relative_to(base))})
    budget=StudyBudget(output/'common_budget.sqlite',budget_identity,create=True)
    with sqlite3.connect((parent/'common_budget.sqlite').as_uri()+'?mode=ro',uri=True) as source,budget.connect() as dest:
        rows=source.execute('SELECT * FROM attempts').fetchall();dest.executemany('INSERT INTO attempts VALUES (?,?,?,?,?,?)',rows)
        dest.executemany('INSERT INTO flags VALUES (?,?)',source.execute('SELECT * FROM flags').fetchall())
    snapshot=budget.snapshot()
    if snapshot['http_attempts']!=manifest['inherited_attempts'] or snapshot['accounted_tokens']!=manifest['inherited_tokens']:
        raise ValueError('continuation lost common cumulative charges')
    with sqlite3.connect((parent/'common_budget.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as control_source,budget.connect() as control_dest:
        rows=control_source.execute('SELECT * FROM execution_control').fetchall()
        control_dest.execute('CREATE TABLE execution_control(id INTEGER PRIMARY KEY,started REAL,deadline REAL,fingerprint TEXT,last_progress_request INTEGER)')
        control_dest.executemany('INSERT INTO execution_control VALUES (?,?,?,?,?)',rows)
        if control_dest.execute('SELECT * FROM execution_control').fetchall()!=rows:raise ValueError('persistent execution control changed')
    write_json(output/'continuation_import.json',{'manifest_digest':digest(manifest),'inherited_usage':snapshot,
        'original_scientific_records_retained':True,'identity_migration':'fresh source identity plus separately preserved parent_identity.json',
        'only_derived_db_change':'review_inputs paths relocated; scientific bodies/events/operations/cursors unchanged'})
