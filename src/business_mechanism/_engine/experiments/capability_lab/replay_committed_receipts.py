"""Matched frozen-action replay; mechanical receipt completion, no model API."""
import argparse
import copy
import json
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--source",type=Path,required=True);parser.add_argument("--snapshot-code",type=Path,required=True);parser.add_argument("--archive",type=Path,required=True);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    # Load the actual prelaunch environment/algorithm source, not current
    # treatment code. The generator is only the simulator, never policy input.
    sys.path.insert(0,str(args.snapshot_code))
    from choice_world import ChoiceWorld
    from research_runtime import ResearchRuntime
    from run_scientific import agent_view,API_LIMITS
    from scientific_readiness import validate_ready_action,validate_request_bindings
    from temporal_lab import TemporalLab,digest
    source=json.loads(args.source.read_text());cfg=source["private_configuration"]
    lab=TemporalLab(ChoiceWorld(cfg["seed"],cfg["family"],"none","structured",cfg["price"]),cfg["profile"],cfg["deadline"])
    lab.limits.update(api_calls=API_LIMITS["calls"],api_tokens=API_LIMITS["reported_tokens"])
    rt=ResearchRuntime(lab,json.loads(args.archive.read_text()));failures=[]
    def stable(value):
        if isinstance(value,list):return [stable(x) for x in value]
        if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in {"wall_seconds","cpu_wall_seconds","event_hash","previous_hash"}}
        return value
    for record in source["model_calls"]:
        request_state=agent_view(rt)
        for action,expected in zip(record.get("actions",[]),record.get("tool_feedbacks",[])):
            if record.get("state_aware"):
                before=agent_view(rt)
                try:validate_request_bindings(action,request_state);validate_ready_action(action,before)
                except ValueError:
                    if expected.get("public_precondition_rejected") is not True:failures.append("precondition_replay_mismatch")
                    continue
            actual=rt.call(action["tool"],action["args"],action["rationale"],action["expected_gap"])
            if stable(actual)!=stable(expected):failures.append("actual_tool_feedback_mismatch")
    # This checks before any new receipt collection. The original fallback
    # finish and deployment are deliberately outside the action prefix.
    original_events=source["research"]["events"]
    matching=stable(rt.events)==stable(original_events[:len(rt.events)])
    if not matching:failures.append("scientific_action_prefix_mismatch")
    prefix_matched=not failures
    planned=copy.deepcopy(rt.checks);registered_models=copy.deepcopy(rt.registry);model=copy.deepcopy(source["frozen_final"]["model"])
    before={"used":copy.deepcopy(lab.used),"completed_checks":sum(c["result"] is not None for c in rt.checks),
        "pending_job_ids":[j["job_id"] for j in lab.public_state()["pending_jobs"]],"registered_checks":len(rt.checks)}
    collected=None
    if not failures and (lab.public_state()["pending_jobs"] or lab.public_state()["failed_jobs"] or lab.public_state()["unverified_jobs"]):
        collected=rt.call("collect",{"until":"all","repair":True,"refit":False,"assess":True},"完成已经冻结的计划及核验；不生成新科学动作。","取得已承诺数据，不追加模型推断。")
        if not collected["ok"]:failures.append("mechanical_collection_failure")
    if rt.registry!=registered_models:failures.append("model_registry_changed_during_receipt_collection")
    if [(c["check_id"],c["candidate_id"],c["job_ids"]) for c in rt.checks]!=[(c["check_id"],c["candidate_id"],c["job_ids"]) for c in planned]:failures.append("new_or_modified_scientific_check")
    final=None
    if not failures:
        cid=source["research"]["final"]["candidate_id"]
        if rt.registry[cid]["model"]!=model:failures.append("source_frozen_model_changed")
        else:final=rt.call("finish",{"candidate_id":cid,"claims":"仅原冻结条件检查；机械收取没有新的解释、参数拟合或独立任务。","unresolved":True,"stop_reason":"matched mechanical receipt replay"},"冻结原模型。","保留条件状态和未测范围。")
    result={"source_file":str(args.source),"source_phase":source["phase"],"strategy":source["strategy"],"source_code_snapshot":str(args.snapshot_code),
        "api_calls":0,"prefix_matched":prefix_matched,"issues":sorted(set(failures)),"before":before,"after":{"used":copy.deepcopy(lab.used),"completed_checks":sum(c["result"] is not None for c in rt.checks),
            "registered_checks":len(rt.checks)},"registry_unchanged":rt.registry==registered_models,"original_card_state":source["mechanism_card"]["state"],
        "replay_card_state":None if not final or not final["ok"] else final["result"]["mechanism_card"]["state"],
        "completed_check_results":[copy.deepcopy(c["result"]) for c in rt.checks if c["result"] is not None],"public_gateway_events":copy.deepcopy(lab.events),"public_research_events":copy.deepcopy(rt.events),
        "frozen_model_sha256":digest(model),"interpretation":"Post-development continuation of the exact recorded public action prefix using its snapshotted simulator/code. No model API, new hypotheses/designs/checks or parameter refit. Retries/measurement audits honor committed plans and spend real shared budget. Same task/stream, no new independent unit or autonomous behavior evidence; not a preregistered treatment effect."}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("strategy","prefix_matched","issues","before","after","original_card_state","replay_card_state")},ensure_ascii=False))
    return 0 if not failures else 1


if __name__=="__main__":raise SystemExit(main())
