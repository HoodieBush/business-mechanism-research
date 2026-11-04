"""Frozen fresh baseline/candidate runs; old science/history are not overwritten."""
import argparse,importlib.util,json
from copy import deepcopy
from pathlib import Path
from ..common import ROOT,digest,sha,write_json
from ..composed_world import create_world
from ..paired_v01.budget import StudyBudget,SharedTokenBudget
from ..paired_v01.initialization import import_initial
from ..paired_v01.contracts import Review
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .continuation import prepare

def initialize_review(ws,path):
    item=json.loads(path.read_text());key='provided_review_sha256'
    row=ws.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    if row:
        if row[0]!=sha(path):raise ValueError('provided review changed')
        return
    job=next(j for j in ws.jobs('pending') if j['target_ref']==item['target_ref'])
    with ws.db:
        ws.apply_review(job['ref'],Review.model_validate(item['review']).model_dump(),author='scripted_initial_review_not_agent_discovery')
        ws.db.execute('INSERT INTO meta VALUES (?,?)',(key,sha(path)))
    ws._publish()

def execute(runner,output,steps):
    try:return runner.run(steps)
    except Exception as error:
        write_json(output/'runtime_status.json',{'status':'pending','category':'host_error','error_type':type(error).__name__,
            'reason':str(error)[:2000],'scientific_refutation':False,'recovery':'Inspect original paid receipts and operations before a new registered action; do not reset or blindly retry.'})
        write_json(output/'common_budget_snapshot.json',runner.budget.snapshot())
        raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--study-id',required=True);p.add_argument('--run-id',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--steps',type=int,default=160);a=p.parse_args()
    spec=importlib.util.spec_from_file_location('registry',ROOT/'scripts/research_workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
    path,study=w.verify(ROOT,a.study_id)
    if (path.parent/'decision.json').exists():raise ValueError('closed allocation cannot restart')
    run=next(r for r in study['execution']['runs'] if r['id']==a.run_id)
    receipt=json.loads((path.parent/'executions'/(a.run_id+'.json')).read_text())
    if receipt.get('study_id')!=a.study_id or receipt.get('run_id')!=a.run_id:raise ValueError('registered launch required')
    if not a.resume and receipt['status']!='started':raise ValueError('fresh registered launch required')
    mode=run.get('verification_mode',run['arm_id']);variant=run.get('variant','candidate')
    if mode not in ('self','independent') or variant!='candidate' or len(run['task_ids'])!=1:raise ValueError('explicit variant,mode and one task required')
    manifest=json.loads(w.local(ROOT,study['execution']['task_manifest']).read_text());task=next(t for t in manifest['tasks'] if t['id']==run['task_ids'][0]);declared=set(study['execution']['files'])
    model_path=manifest['model_config_file']
    if model_path not in declared:raise ValueError('explicit frozen model required')
    model=json.loads((ROOT/model_path).read_text());pointer=ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    if model.get('token_budget_pointer')!=str(pointer):raise ValueError('same explicit project ledger required')
    project=SharedTokenBudget(pointer)
    settings={'research_profile':'paired_research_v1','verification_mode':mode,'limits':task['limits'],'model_config':model,
        'initialization_notice':task.get('initialization_notice','No externally seeded scientific claims.'),
        'workflow_policy':task['workflow_policy'],'execution_policy':task['execution_policy'],
        'entry_v16_sources':{p.name:sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.txt')}}
    world=create_world(**task['environment']);output=path.parent/'results'/a.run_id
    continued=task.get('continuation_manifests',{}).get(a.run_id)
    identity={'study_id':a.study_id,'run_id':a.run_id,'verification_mode':mode,'variant':variant,'token_allowance':task['limits']['token_allowance'],'max_http_attempts':task['limits']['max_http_attempts'],'project_budget_id':project.auth['id'],'model_config_sha256':sha(ROOT/model_path),'task_digest':digest(task)}
    if continued:
        if continued not in declared:raise ValueError('frozen owned continuation required')
        capture=json.loads((ROOT/continued).read_text())
        if any(str(Path(capture['parent_root'])/name) not in declared for name in capture['sha256']):raise ValueError('all inherited files must be frozen')
        old=deepcopy(capture['parent_identity']['settings'])
        old.update({k:v for k,v in settings.items() if k!='entry_v16_sources'})
        old['entry_v16_sources']=settings['entry_v16_sources'];settings=old
        if not a.resume:prepare(output,capture,task['question'],world,settings,identity)
    cls=ResearchWorkspace
    ws=cls(output/'researcher',task['question'],world,settings,reopen=a.resume or bool(continued))
    try:
        for field in ('initial_manifest','provided_review_file'):
            if task.get(field) and task[field] not in declared:raise ValueError('provided material must be frozen')
        if task.get('initial_manifest') and not continued:
            initial_path=ROOT/task['initial_manifest'];initial=json.loads(initial_path.read_text())
            if any(str((initial_path.parent/'files'/f['path']).relative_to(ROOT)) not in declared for f in initial['files']):raise ValueError('freeze all received inputs')
            import_initial(ws,initial_path)
        if task.get('provided_review_file') and not continued:initialize_review(ws,ROOT/task['provided_review_file'])
        identity={'study_id':a.study_id,'run_id':a.run_id,'verification_mode':mode,'variant':variant,
            'token_allowance':task['limits']['token_allowance'],'max_http_attempts':task['limits']['max_http_attempts'],
            'project_budget_id':project.auth['id'],'model_config_sha256':sha(ROOT/model_path),'task_digest':digest(task)}
        budget=StudyBudget(output/'common_budget.sqlite',identity,create=not a.resume and not continued)
        runner=ResearchRun(output,ws,model,budget)
        result=execute(runner,output,a.steps);write_json(output/'runtime_status.json',result);write_json(output/'common_budget_snapshot.json',budget.snapshot());write_json(output/'execution_guard_snapshot.json',runner.guard.inspect())
        print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='completed' else 3
    finally:ws.close()

if __name__=='__main__':raise SystemExit(main())
