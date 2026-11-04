"""Registered service-environment adapter; normal journal and shared accounting."""
import argparse
import importlib.util
import json
from ..common import ROOT, digest, encoded, sha, write_json
from ..paired_v01.budget import StudyBudget, SharedTokenBudget
from .orchestrator import ResearchRun
from ..growth_probe_v01.environment import World
from ..growth_probe_v01.workspace import ResearchWorkspace


def construct(study_id, run_id, *, resume=False):
    spec = importlib.util.spec_from_file_location('workflow', ROOT/'scripts/research_workflow.py')
    wf = importlib.util.module_from_spec(spec); spec.loader.exec_module(wf)
    path, study = wf.verify(ROOT, study_id)
    if (path.parent/'decision.json').exists(): raise ValueError('closed study cannot restart')
    run = next(r for r in study['execution']['runs'] if r['id']==run_id)
    receipt = json.loads((path.parent/'executions'/(run_id+'.json')).read_text())
    if receipt['study_id'] != study_id or receipt['run_id'] != run_id:
        raise ValueError('matching registered launch required')
    if not resume and receipt['status'] != 'started': raise ValueError('fresh run already started')
    manifest = json.loads((ROOT/study['execution']['task_manifest']).read_text())
    task = next(t for t in manifest['tasks'] if t['id']==run['task_ids'][0])
    model_path = manifest['model_config_file']
    if model_path not in study['execution']['files']: raise ValueError('model must be frozen')
    model = json.loads((ROOT/model_path).read_text())
    pointer = ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    if model['token_budget_pointer'] != str(pointer): raise ValueError('same explicit original project ledger required')
    project = SharedTokenBudget(pointer)
    settings = {k:task[k] for k in ('limits','execution_policy','workflow_policy','initialization_notice')}
    settings.update(research_profile='paired_research_v1',verification_mode=run['verification_mode'],model_config=model)
    world = World(**task['environment'])
    output = path.parent/'results'/run_id
    ws = ResearchWorkspace(output/'researcher',task['question'],world,settings,reopen=resume)
    identity = {'study_id':study_id,'run_id':run_id,'verification_mode':run['verification_mode'],
        'variant':'growth_probe_v02','token_allowance':task['limits']['token_allowance'],
        'max_http_attempts':task['limits']['max_http_attempts'],'project_budget_id':project.auth['id'],
        'model_config_sha256':sha(ROOT/model_path),'task_digest':digest(task)}
    budget = StudyBudget(output/'common_budget.sqlite',identity,create=not resume)
    runner = ResearchRun(output,ws,model,budget)
    return output,ws,runner


def main():
    p=argparse.ArgumentParser();p.add_argument('--study-id',required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--probe-only',action='store_true');p.add_argument('--steps',type=int,default=80)
    a=p.parse_args();output,ws,runner=construct(a.study_id,a.run_id,resume=a.resume)
    try:
        if a.probe_only:
            from token_budget import reservation_bound
            request=runner.runtime.payload(runner.runtime.initial())
            result={'status':'engineering_probe_only','new_paid_calls':0,'tools':len(ws.tools),
                    'payload_bytes':len(encoded(request).encode()),'reservation_bound':reservation_bound(request),
                    'environment_status':ws.environment.public_status(),'scientific_records':len(ws.records('hypothesis')),
                    'model_generation_options':ws.settings['model_config']['generation_options']}
        else: result=runner.run(a.steps)
        write_json(output/'runtime_status.json',result)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status'] in ('completed','engineering_probe_only') else 3
    finally:
        write_json(output/'common_budget_snapshot.json',runner.budget.snapshot())
        write_json(output/'execution_guard_snapshot.json',runner.guard.inspect());ws.close()


if __name__=='__main__': raise SystemExit(main())
