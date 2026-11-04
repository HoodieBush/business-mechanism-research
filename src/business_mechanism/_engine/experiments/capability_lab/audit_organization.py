"""Public context/branch replay and actual organization-use endpoints."""
import json
from pathlib import Path

from audit_scientific import audit as scientific_audit
from public_context import unpack
from model_protocol import usage_summary
from research_organization import ResearchOrganization
from temporal_lab import digest


def observed_jobs(events):
    statuses={}
    for event in events:
        p=event["payload"];kind=event["kind"]
        if kind=="tool_response" and event["request"]["tool"] in {"submit_experiment","retry_execution"}:statuses[p["job_id"]]=p["status"]
        elif kind in {"measurement_received","measurement_revised"}:statuses[p["job_id"]]="received" if p["verified_meter"] and p["verified_supply"] else "measurement_unverified"
        elif kind=="tool_response" and event["request"]["tool"]=="reconcile_measurement":statuses[event["request"]["args"]["job_id"]]="awaiting_audit"
    result={"pending_jobs":[],"failed_jobs":[],"unverified_jobs":[]}
    for job_id,status in statuses.items():
        key="pending_jobs" if status in {"pending","awaiting_audit"} else "failed_jobs" if status=="execution_failed" else "unverified_jobs" if status=="measurement_unverified" else None
        if key:result[key].append({"job_id":job_id,"status":status})
    return result


def audit(run):
    issues=[]
    def check(ok,label):
        if not ok:issues.append(label)
    research=run["research"];mode=run["organization_mode"];events=research["events"]
    try:
        archive=ResearchOrganization.from_events(mode,events)
        expected_archive=json.loads(json.dumps(archive.snapshot(run["public_final_state"])))
        check(expected_archive==research["research_organization"],"organization_archive_replay")
        check(archive.contract()==run["legal_input"]["research_organization_contract"],"organization_contract_frozen")
    except (ValueError,KeyError,TypeError):return {"passed":False,"issues":["invalid_organization_source"]}
    for event in events:
        if event["kind"]!="scientific_tool_response":continue
        p=event["payload"]
        if p["request"]["tool"] in {"dispatch_research_context","append_research_note"}:check(p["used_before"]==p["used_after"],"local_organization_no_new_physical_ledger")
    for index,record in enumerate(run["model_calls"]):
        count=record["public_research_event_count"];gcount=record["public_gateway_event_count"]
        prefix=events[:count];gateway=run["gateway_events"][:gcount]
        check(digest(gateway)==record["public_gateway_prefix_sha256"],"organization_API_gateway_prefix")
        state=unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
        organization=ResearchOrganization.from_events(mode,prefix)
        visible=[c["candidate_id"] for c in state["candidates"]]+[c["candidate_id"] for c in state["checks"]]+[
            e["payload"]["candidate_id"] for e in prefix if e["kind"]=="candidate_registered" and e["payload"]["origin"]=="policy_proposal"]
        expected=organization.view(observed_jobs(gateway),visible)
        check(state["research_organization"]==expected,"API_public_organization_context")
        check(record["organization_context_id"]==organization.current,"API_dispatched_persistent_context")
        check(state["api_resource_review"]["calls_left"]==run["scientific_protocol"]["api_limits"]["calls"]-usage_summary(run["model_calls"][:index])["api_calls"],"shared_context_API_call_allocation")
    queried={r["organization_context_id"] for r in run["model_calls"]}
    candidate_programs={digest(e["payload"]["model"]["expression"]) for e in events if e["kind"]=="candidate_registered"}
    if mode=="A":used=bool(run["model_calls"] or run["strategy"]=="numeric_full")
    elif mode=="B":used={"supervisor","generator","reviewer"}<=queried and bool(archive.notes) and len(candidate_programs)>1
    else:
        children=[c for c in archive.contexts.values() if c["parent_id"] is not None]
        used=any(c["context_id"] in queried and (c["job_ids"] or c["program_versions"]) and c["feedback_refs"] for c in children)
    return {"passed":not issues,"issues":sorted(set(issues)),"organization_behavior_exercised":used,
        "queried_contexts":sorted(queried),"contexts":len(archive.contexts),"candidate_groups":len(archive.groups),
        "notes":len(archive.notes),"child_branches":sum(c["parent_id"] is not None for c in archive.contexts.values()),
        "interpretation":"Trace validity and actual organization use are separate from scientific success or formal ABC attribution."}


def analyze(folder):
    from run_organization import filename
    folder=Path(folder);manifest=json.loads((folder/"manifest.json").read_text());records=[]
    for task in manifest["planned_tasks"]:
        path=folder/filename(task)
        if not path.exists():records.append({"file":path.name,"passed":False,"issues":["planned_run_missing"]});continue
        run=json.loads(path.read_text())
        if run["status"]=="execution_failure":records.append({"file":path.name,"passed":False,"issues":[run["error"]]});continue
        science=scientific_audit(run);organization=audit(run)
        records.append({"file":path.name,"passed":science["passed"] and organization["passed"],"status":run["status"],"scientific":science,"organization":organization,
            "card_state":run["mechanism_card"]["state"],"usage":run["model_usage"],"used":run["used"],
            "effect_rmse":run["private_score"]["heldout_effect_rmse"],"regret":run["private_score"]["mean_expected_operating_regret_per_customer"]})
    result={"records":records,"all_trace_audits_passed":all(r["passed"] for r in records),
        "all_BC_behavior_exercised":all(r.get("organization",{}).get("organization_behavior_exercised",False) for r in records if r["file"].startswith(("B_","C_"))),
        "formal_ABC_completed":False,"interpretation":"One development seed/two latent worlds, no structural holdout, dynamic inventory or automatic meta-research. Failures/unexercised organization remain in denominator."}
    (folder/"analysis.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");return result


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("folder",type=Path);args=ap.parse_args();print(json.dumps(analyze(args.folder),ensure_ascii=False,indent=2))
