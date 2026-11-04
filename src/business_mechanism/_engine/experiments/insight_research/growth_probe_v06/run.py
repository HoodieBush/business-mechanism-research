import argparse
import json
from ..common import ROOT,digest,encoded,sha,write_json
from ..paired_v01.budget import SharedTokenBudget,StudyBudget
from ..growth_probe_v01.environment import World
from ..growth_probe_v03.orchestrator import ResearchRun
from ..growth_probe_v05.orchestrator import ResearchRuntime
from .workspace import ResearchWorkspace
from scripts import research_workflow as wf
from token_budget import reservation_bound


def construct(sid,rid,resume=False):
    path,study=wf.verify(ROOT,sid)
    if (path.parent/'decision.json').exists():raise ValueError('Closed study cannot restart')
    run=next(r for r in study['execution']['runs'] if r['id']==rid)
    receipt=json.loads((path.parent/'executions'/(rid+'.json')).read_text())
    if not resume and receipt['status']!='started':raise ValueError('Matching fresh registered launch required')
    manifest=json.loads((ROOT/study['execution']['task_manifest']).read_text());task=next(t for t in manifest['tasks'] if t['id']==run['task_ids'][0])
    model=json.loads((ROOT/manifest['model_config_file']).read_text())
    pointer=ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    if model['token_budget_pointer']!=str(pointer):raise ValueError('Original project pointer required')
    project=SharedTokenBudget(pointer);mode=run['experience_mode']
    settings={k:task[k] for k in ('limits','execution_policy','workflow_policy','initialization_notice')}
    settings.update(model_config=model,research_profile='paired_research_v1',verification_mode='self',experience_mode=mode,
        project_archives=[] if mode=='none' else [task['native_history']])
    output=path.parent/'results'/rid
    ws=ResearchWorkspace(output/'researcher',task['question'],World(**task['environment']),settings,reopen=resume)
    identity={'study_id':sid,'run_id':rid,'verification_mode':'self','experience_mode':mode,'variant':'growth_probe_v06',
        'token_allowance':task['limits']['token_allowance'],'max_http_attempts':task['limits']['max_http_attempts'],
        'project_budget_id':project.auth['id'],'model_config_sha256':sha(ROOT/manifest['model_config_file']),'task_digest':digest(task)}
    budget=StudyBudget(output/'common_budget.sqlite',identity,create=not resume)
    research=ResearchRun(output,ws,model,budget)
    research.runtime=ResearchRuntime(ws,model,journal=research.journal)
    return output,ws,research


def main():
    p=argparse.ArgumentParser();p.add_argument('--study-id',required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--probe-only',action='store_true');a=p.parse_args()
    out,ws,run=construct(a.study_id,a.run_id,a.resume)
    try:
        if a.probe_only:
            payload=run.runtime.payload(run.runtime.initial())
            result={'status':'engineering_probe_only','new_paid_calls':0,'experience_mode':ws.settings['experience_mode'],
                'payload_bytes':len(encoded(payload).encode()),'reservation_bound':reservation_bound(payload),
                'automatic_experience':ws.experience_context(),'current_scientific_records':len(ws.records('hypothesis')),
                'normal_generation_options':run.model['generation_options'],'public_inputs':ws.identity['public_inputs']}
        else:
            result=run.run(80)
            diagnostic=ws.private/'execution_pause_diagnostic.json'
            if result['status']=='pending' and diagnostic.exists():result={**result,'execution_pause_diagnostic':json.loads(diagnostic.read_text())}
        write_json(out/'runtime_status.json',result);print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status'] in ('completed','engineering_probe_only') else 3
    except Exception as error:
        write_json(out/'runtime_status.json',{'status':'pending','category':'host_error','error_type':type(error).__name__,'reason':str(error),'paid_work_preserved':True})
        raise
    finally:
        write_json(out/'common_budget_snapshot.json',run.budget.snapshot());write_json(out/'execution_guard_snapshot.json',run.guard.inspect());ws.close()


if __name__=='__main__':raise SystemExit(main())
