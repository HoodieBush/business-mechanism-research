"""Frozen fresh runs or explicit same-case all-role continuations."""
import argparse,importlib.util,json
from ..common import ROOT,digest,sha,write_json
from ..composed_world import create_world
from ..paired_v01.budget import StudyBudget
from ..paired_v01.initialization import import_initial
from token_budget import SharedTokenBudget
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .continuation import prepare


def main():
    p=argparse.ArgumentParser();p.add_argument('--study-id',required=True);p.add_argument('--run-id',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--steps',type=int,default=80);a=p.parse_args()
    spec=importlib.util.spec_from_file_location('registry',ROOT/'scripts/research_workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
    path,study=w.verify(ROOT,a.study_id)
    if (path.parent/'decision.json').exists():raise ValueError('closed study cannot restart')
    run=next(r for r in study['execution']['runs'] if r['id']==a.run_id)
    receipt=json.loads((path.parent/'executions'/(a.run_id+'.json')).read_text())
    if receipt.get('study_id')!=a.study_id or receipt.get('run_id')!=a.run_id:raise ValueError('registered launch required')
    if not a.resume and receipt['status']!='started':raise ValueError('fresh launch receipt required')
    if len(run['task_ids'])!=1 or run['arm_id'] not in ('self','independent'):raise ValueError('one task and explicit mode required')
    manifest=json.loads(w.local(ROOT,study['execution']['task_manifest']).read_text());task=next(t for t in manifest['tasks'] if t['id']==run['task_ids'][0]);declared=set(study['execution']['files'])
    model_path=manifest['model_config_file']
    if model_path not in declared:raise ValueError('frozen explicit model configuration required')
    model=json.loads((ROOT/model_path).read_text());pointer=ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    if model.get('token_budget_pointer')!=str(pointer):raise ValueError('original project pointer required')
    project=SharedTokenBudget(pointer)
    settings={'research_profile':'paired_research_v1','verification_mode':run['arm_id'],'limits':task['limits'],'model_config':model,
        'initialization_notice':task.get('initialization_notice','No externally seeded scientific claims.')}
    identity={'study_id':a.study_id,'run_id':a.run_id,'verification_mode':run['arm_id'],'token_allowance':task['limits']['token_allowance'],
        'max_http_attempts':task['limits']['max_http_attempts'],'project_budget_id':project.auth['id'],'model_config_sha256':sha(ROOT/model_path),'task_digest':digest(task)}
    output=path.parent/'results'/a.run_id;world=create_world(**task['environment']);continued=task.get('continuation_manifests',{}).get(run['arm_id'])
    if continued:
        if continued not in declared:raise ValueError('frozen continuation capture required')
        capture=json.loads((ROOT/continued).read_text())
        if any(str((ROOT/capture['parent_root']/name).relative_to(ROOT)) not in declared for name in capture['sha256']):raise ValueError('every inherited file must be frozen')
        settings['continuation_binding']={'manifest':continued,'sha256':sha(ROOT/continued),'same_case_not_new_sample':True}
        if not a.resume:prepare(output,capture,task['question'],world,settings,identity)
        else:
            imported=json.loads((output/'continuation_import.json').read_text())
            if imported['manifest_digest']!=digest(capture):raise ValueError('continuation binding differs')
    ws=ResearchWorkspace(output/'researcher',task['question'],world,settings,reopen=a.resume or bool(continued))
    try:
        if task.get('initial_manifest') and not continued:
            name=task['initial_manifest']
            if name not in declared:raise ValueError('frozen provided state required')
            initpath=ROOT/name;initial=json.loads(initpath.read_text())
            if any(str((initpath.parent/'files'/entry['path']).relative_to(ROOT)) not in declared for entry in initial['files']):raise ValueError('freeze all provided files')
            import_initial(ws,initpath)
        budget=StudyBudget(output/'common_budget.sqlite',identity,create=not a.resume and not continued)
        result=ResearchRun(output,ws,model,budget).run(a.steps)
        write_json(output/'runtime_status.json',result);write_json(output/'common_budget_snapshot.json',budget.snapshot());print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='completed' else 3
    finally:ws.close()


if __name__=='__main__':raise SystemExit(main())
