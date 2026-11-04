import argparse
import json
from ..common import ROOT,digest,encoded,write_json
from ..paired_v01.budget import SharedTokenBudget,StudyBudget
from ..growth_probe_v01.environment import World
from .workspace import ResearchWorkspace
from .orchestrator import ResearchRun
from .recovery import prepare
from scripts import research_workflow as wf
from token_budget import reservation_bound


def construct(sid,rid,resume=False):
    path,study=wf.verify(ROOT,sid)
    if (path.parent/'decision.json').exists():raise ValueError('Closed allocation cannot restart')
    registered=next(r for r in study['execution']['runs'] if r['id']==rid)
    receipt=json.loads((path.parent/'executions'/(rid+'.json')).read_text())
    if not resume and receipt['status']!='started':raise ValueError('Matching registered launch required')
    task=next(t for t in json.loads((ROOT/study['execution']['task_manifest']).read_text())['tasks'] if t['id']==registered['task_ids'][0])
    mfile=ROOT/task['parent_manifest_file'];m=json.loads(mfile.read_text())
    if any(str((ROOT/m['parent_root']/p).relative_to(ROOT)) not in study['execution']['files'] for p in m['sha256']):
        raise ValueError('All original paid parent inputs must be frozen')
    settings=m['parent_identity']['settings'];model=settings['model_config']
    pointer=ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    if model['token_budget_pointer']!=str(pointer):raise ValueError('Original explicit project ledger required')
    project=SharedTokenBudget(pointer)
    identity={**m['parent_budget_identity'],'study_id':sid,'run_id':rid,'variant':'growth_probe_v03','parent_manifest_digest':digest(m)}
    if identity['project_budget_id']!=project.auth['id']:raise ValueError('Project ledger mismatch')
    out=path.parent/'results'/rid
    if not resume:settings=prepare(out,m,identity,task['environment'])
    ws=ResearchWorkspace(out/'researcher',m['parent_identity']['question'],World(**task['environment']),settings,reopen=True)
    budget=StudyBudget(out/'common_budget.sqlite',identity)
    return out,ws,ResearchRun(out,ws,model,budget)


def main():
    p=argparse.ArgumentParser();p.add_argument('--study-id',required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--probe-only',action='store_true');a=p.parse_args()
    out,ws,run=construct(a.study_id,a.run_id,a.resume)
    try:
        if a.probe_only:
            before=run.budget.snapshot();run.runtime.drain()
            payload=run.runtime.payload(run.runtime.initial()+run.runtime.cp['messages'][2:])
            assert run.budget.snapshot()==before and run.runtime.cp['pending'] is None
            assert reservation_bound(payload)<=before['remaining_tokens']
            result={'status':'engineering_probe_only','new_paid_calls':0,'inherited_usage':before,
                'pending_batch_drained':True,'original_hypothesis_saved':len(ws.records('hypothesis')),
                'payload_bytes':len(encoded(payload).encode()),'reservation_bound':reservation_bound(payload),
                'normal_generation_options':run.model['generation_options']}
        else:result=run.run(80)
        write_json(out/'runtime_status.json',result);print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status'] in ('completed','engineering_probe_only') else 3
    except Exception as error:
        write_json(out/'runtime_status.json',{'status':'pending','category':'host_error','error_type':type(error).__name__,
            'reason':str(error),'paid_work_preserved':True,'responses':run.runtime.cp['responses']})
        raise
    finally:
        write_json(out/'common_budget_snapshot.json',run.budget.snapshot())
        write_json(out/'execution_guard_snapshot.json',run.guard.inspect());ws.close()


if __name__=='__main__':raise SystemExit(main())
