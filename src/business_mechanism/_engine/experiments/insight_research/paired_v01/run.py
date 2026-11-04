"""Frozen matched-run entry: two modes, one common study-local allowance."""
import argparse
import importlib.util
import json

from ..common import ROOT, digest, sha, write_json
from ..composed_world import create_world
from .budget import StudyBudget
from .initialization import import_initial
from .orchestrator import ResearchRun
from .workspace import ResearchWorkspace
from token_budget import SharedTokenBudget


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--study-id',required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--steps',type=int,default=80)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('paired_registry',ROOT/'scripts/research_workflow.py')
    workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(workflow)
    path,study=workflow.verify(ROOT,args.study_id)
    if (path.parent/'decision.json').exists():raise ValueError('closed experiment cannot be restarted')
    run=next(x for x in study['execution']['runs'] if x['id']==args.run_id)
    receipt=json.loads((path.parent/'executions'/(args.run_id+'.json')).read_text())
    if receipt.get('study_id')!=args.study_id or receipt.get('run_id')!=args.run_id:raise ValueError('registered launch required')
    if not args.resume and receipt['status']!='started':raise ValueError('new launch receipt required')
    if len(run['task_ids'])!=1 or run['arm_id'] not in ('self','independent'):raise ValueError('one paired task and an explicit mode required')
    tasks=json.loads(workflow.local(ROOT,study['execution']['task_manifest']).read_text())
    task=next(t for t in tasks['tasks'] if t['id']==run['task_ids'][0])
    declared=set(study['execution']['files'])
    model_path=tasks['model_config_file']
    if model_path not in declared:raise ValueError('frozen model configuration required')
    model=json.loads(workflow.local(ROOT,model_path).read_text())
    pointer=ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    if model.get('token_budget_pointer')!=str(pointer):raise ValueError('explicit original project ledger required')
    project=SharedTokenBudget(pointer)
    if project.auth['id']!='USER-20261022-CRITIC-10M':raise ValueError('project ledger identity differs')
    settings={'research_profile':'paired_research_v1','verification_mode':run['arm_id'],
        'limits':task['limits'],'model_config':model,'initialization_notice':task.get('initialization_notice','No externally seeded scientific claims.')}
    output=path.parent/'results'/args.run_id
    world=create_world(**task['environment'])
    ws=ResearchWorkspace(output/'researcher',task['question'],world,settings,reopen=args.resume)
    try:
        if task.get('initial_manifest'):
            name=task['initial_manifest']
            if name not in declared:raise ValueError('frozen provided state required')
            manifest_path=workflow.local(ROOT,name);manifest=json.loads(manifest_path.read_text())
            inputs={str((manifest_path.parent/'files'/f['path']).relative_to(ROOT)) for f in manifest['files']}
            if not inputs<=declared:raise ValueError('every provided source must be frozen')
            import_initial(ws,manifest_path)
        identity={'study_id':args.study_id,'run_id':args.run_id,'verification_mode':run['arm_id'],
            'token_allowance':task['limits']['token_allowance'],'max_http_attempts':task['limits']['max_http_attempts'],
            'project_budget_id':project.auth['id'],'model_config_sha256':sha(ROOT/model_path),
            'task_digest':digest(task)}
        budget_path=output/'common_budget.sqlite'
        budget=StudyBudget(budget_path,identity,create=not args.resume)
        result=ResearchRun(output,ws,model,budget).run(args.steps)
        write_json(output/'runtime_status.json',result);write_json(output/'common_budget_snapshot.json',budget.snapshot())
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='completed' else 3
    finally:ws.close()


if __name__=='__main__':raise SystemExit(main())
