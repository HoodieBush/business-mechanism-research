"""Same v04 research component, with a common runtime diagnostic adapter."""
import argparse
import json
from ..common import write_json
from ..growth_probe_v04.run import construct as construct_science
from .orchestrator import ResearchRuntime


def construct(sid,rid,resume=False):
    out,ws,run=construct_science(sid,rid,resume)
    run.runtime=ResearchRuntime(ws,run.model,journal=run.journal)
    return out,ws,run


def main():
    p=argparse.ArgumentParser();p.add_argument('--study-id',required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--resume',action='store_true');p.add_argument('--probe-only',action='store_true');a=p.parse_args()
    out,ws,run=construct(a.study_id,a.run_id,a.resume)
    try:
        if a.probe_only:
            from ..common import encoded
            from token_budget import reservation_bound
            payload=run.runtime.payload(run.runtime.initial())
            result={'status':'engineering_probe_only','new_paid_calls':0,'runtime_profile':'precise_pause_diagnostics_v1',
                'scientific_component':'unchanged_growth_probe_v04','experience_mode':ws.settings['experience_mode'],
                'payload_bytes':len(encoded(payload).encode()),'reservation_bound':reservation_bound(payload),
                'normal_generation_options':run.model['generation_options']}
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
