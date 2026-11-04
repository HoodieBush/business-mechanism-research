"""Narrow owned recovery: paid, unfinished hypothesis registration, no resampling."""
from contextlib import ExitStack
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
from ..common import ROOT,Pending,digest,sha,write_json
from ..paired_v16.continuation import allowed as before_allowed
from ..paired_v01.budget import StudyBudget
from ..growth_probe_v01.environment import World
from .workspace import ResearchWorkspace


def read(path):return json.loads(Path(path).read_text())


def allowed(name):
    return name=='researcher/private/environment_state.json' or before_allowed(name)


def capture(parent):
    parent=Path(parent).resolve()
    with ExitStack() as stack:
        for lockpath in (parent/'research_run.lock',parent/'researcher/private/runtime.lock'):
            lock=stack.enter_context(lockpath.open('rb'))
            try:fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise Pending('Parent controller/role is live; no recovery copy')
        ws=parent/'researcher';owner=ws/'private';cp=read(owner/'checkpoint.json');transport=read(owner/'transport.json')
        if transport.get('inflight') or transport.get('delivery'):raise Pending('Unsettled paid transport; preserve original')
        pending=cp.get('pending') or {};calls=pending.get('calls',[])
        if pending.get('cursor')!=0 or not calls or any(c['name']!='save_hypothesis' for c in calls):
            raise Pending('Only a complete unfinished scientific-registration batch can migrate')
        raw=read(owner/'turns'/(str(pending['response'])+'.json'))
        if read(owner/'http'/(str(cp['delivered_attempt'])+'.json'))['response']!=raw:
            raise Pending('Paid response and raw cursor source differ')
        original=raw['choices'][0]['message']['tool_calls']
        if len(original)!=len(calls):raise Pending('Original complete batch differs')
        from ..growth_probe_v01.workspace import TOOLS
        for old,current in zip(original,calls):
            parsed=TOOLS[current['name']][0].model_validate(json.loads(old['function']['arguments'])).model_dump()
            if old['id']!=current['id'] or old['function']['name']!=current['name'] or parsed!=current['args']:
                raise Pending('Paid scientific words/cursor changed')
        with sqlite3.connect((owner/'records.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            if db.execute('SELECT count(*) FROM records').fetchone()[0]:
                raise Pending('This recovery proof is for registration before any scientific record')
            expected=digest([str(ws),pending['response'],calls[0]['id']])
            prepared=db.execute("SELECT key,signature FROM operations WHERE status!='completed'").fetchall()
            if prepared!=[(expected,digest([calls[0]['name'],calls[0]['args']]))]:
                raise Pending('Prepared registration identity differs; no automatic replay')
            for ref,path,h in db.execute('SELECT ref,path,hash FROM files'):
                if sha(ws/path)!=h:raise Pending('Received original changed: '+ref)
        if any((owner/'effects').glob('*.json')):raise Pending('Unproven external effects; no replay')
        status=read(parent/'runtime_status.json')
        if status.get('category')!='host_error':raise Pending('Stopped host-error evidence required')
        with sqlite3.connect((parent/'common_budget.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            identity=json.loads(db.execute('SELECT body FROM identity').fetchone()[0])
            rows=db.execute('SELECT * FROM attempts').fetchall()
            if any(r[-1]=='in_flight' for r in rows):raise Pending('Local paid request is live')
            if len(rows)!=transport['attempts'] or sum(r[3] if r[3] is not None else r[2] for r in rows)!=transport['accounted_tokens']:
                raise Pending('Local/role fees differ')
        paths=[]
        for p in parent.rglob('*'):
            name=str(p.relative_to(parent))
            if allowed(name) and p.is_symlink():raise Pending('No symlink recovery')
            if allowed(name) and p.is_file():paths.append(p)
        return {'parent_root':str(parent.relative_to(ROOT)),'parent_identity':read(owner/'identity.json'),
            'parent_budget_identity':identity,'inherited_tokens':transport['accounted_tokens'],
            'inherited_requests':transport['attempts'],'pending_response':pending['response'],
            'call_ids':[c['id'] for c in calls],'original_workspace':str(ws),
            'raw_turn_sha256':sha(owner/'turns'/(str(pending['response'])+'.json')),
            'sha256':{str(p.relative_to(parent)):sha(p) for p in paths},
            'scope':'Same paid task, same original prediction words and all costs; only accurate capability rejection/recovery, no scientific answer or new sample.'}


def prepare(output,manifest,budget_identity,environment):
    parent=ROOT/manifest['parent_root'];output=Path(output).resolve()
    if capture(parent)!=manifest:raise Pending('Original stopped parent changed')
    if output.exists():raise ValueError('Never overwrite a recovery')
    old=manifest['parent_identity'];settings=deepcopy(old['settings']);prior=manifest['parent_budget_identity']
    for k in ('token_allowance','max_http_attempts','project_budget_id'):
        if budget_identity[k]!=prior[k]:raise ValueError('No implicit quota reset/extension: '+k)
    output.mkdir(parents=True)
    ws=ResearchWorkspace(output/'researcher',old['question'],World(**environment),settings)
    try:
        for key in ('public_inputs','environment_identity','reused_sources','question'):
            if ws.identity[key]!=old[key]:raise Pending('Recovery changed received environment/question: '+key)
    finally:ws.close()
    for name,h in manifest['sha256'].items():
        if not name.startswith('researcher/'):continue
        relative=Path(name).relative_to('researcher')
        if str(relative)=='private/identity.json':relative=Path('private/parent_identity.json')
        source=parent/name;target=output/'researcher'/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if sha(target)!=h:raise Pending('Recovery copied source differs: '+name)
    budget=StudyBudget(output/'common_budget.sqlite',budget_identity,create=True)
    with sqlite3.connect((parent/'common_budget.sqlite').as_uri()+'?mode=ro',uri=True) as source,budget.connect() as dest:
        dest.executemany('INSERT INTO attempts VALUES(?,?,?,?,?,?)',source.execute('SELECT * FROM attempts').fetchall())
        dest.executemany('INSERT INTO flags VALUES(?,?)',source.execute('SELECT * FROM flags').fetchall())
        dest.execute('CREATE TABLE execution_control(id INTEGER PRIMARY KEY,started REAL,deadline REAL,fingerprint TEXT,last_progress_request INTEGER)')
        controls=source.execute('SELECT * FROM execution_control').fetchall()
        dest.executemany('INSERT INTO execution_control VALUES(?,?,?,?,?)',controls)
        assert dest.execute('SELECT * FROM execution_control').fetchall()==controls
    assert budget.snapshot()['accounted_tokens']==manifest['inherited_tokens']
    assert budget.snapshot()['http_attempts']==manifest['inherited_requests']
    for name in ('checkpoint.json','transport.json','environment_state.json'):
        assert (output/'researcher/private'/name).read_bytes()==(parent/'researcher/private'/name).read_bytes()
    write_json(output/'researcher/private/paid_registration_recovery.json',{
        'response':manifest['pending_response'],'raw_turn_sha256':manifest['raw_turn_sha256'],
        'original_workspace':manifest['original_workspace'],'call_ids':manifest['call_ids']})
    write_json(output/'continuation_import.json',{'parent_digest':digest(manifest),
        'inherited_usage':budget.snapshot(),'same_case_not_new_sample':True,
        'scientific_records_and_paid_context_originally_identical':True,
        'persistent_deadline_and_control_unchanged':True,
        'capability_change':'Unavailable inventory structured prediction/protocol is explicitly rejected; numeric text and old original preserved.',
        'no_scientific_answers_injected':True,'new_paid_calls':0})
    return settings
