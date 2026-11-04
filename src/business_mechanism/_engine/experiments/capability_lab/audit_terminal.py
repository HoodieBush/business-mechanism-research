"""Independent public replay and paired acceptance for terminal policies."""
import copy
import hashlib
import json
from pathlib import Path

from audit_scientific import audit as scientific_audit
from run_terminal import filename
from temporal_lab import digest


def audit(run):
    result=scientific_audit(run);issues=list(result["issues"]);r=run["research"];commit=r["terminal_commitment"]
    def check(ok,name):
        if not ok:issues.append(name)
    check(commit is not None and r["decisions_closed"],"decision_plane_closed")
    if commit:
        index=next(i for i,e in enumerate(r["events"]) if e["kind"]=="research_decisions_closed")
        before=r["events"][:index];after=r["events"][index+1:]
        registry={e["payload"]["candidate_id"]:e["payload"] for e in before if e["kind"]=="candidate_registered"}
        check(digest(registry)==commit["registry_sha256"],"registry_frozen_before_results")
        check(digest(r["objects"]["plans"])==commit["plans_sha256"],"committed_plan_set")
        check(commit["candidate_id"]==r["final"]["candidate_id"] and commit["model_sha256"]==digest(run["frozen_final"]["model"]),"no_terminal_model_selection_or_refit")
        check(commit["check_ids"]==[c["check_id"] for c in r["checks"]] and commit["job_ids"]==sorted(int(j) for j in r["jobs"]),"no_new_check_or_job")
        check(not any(e["kind"] in {"candidate_registered","public_pool_fitted","check_frozen_before_execution","confirmation_evidence_released","registered_plan_linked"} for e in after),"no_new_research_after_close")
        check(r["terminal_policy"]==run["legal_input"]["terminal_receipt_contract"]["policy"]==run["terminal_policy"],"predeclared_terminal_policy")
        check(commit["revisions"]==r["revisions"],"no_terminal_revision")
    settlement=r["terminal_settlement"]
    check(settlement is not None and all(settlement[k]==0 for k in ("extra_api_calls","new_designs","new_hypotheses","parameter_refits")),"settlement_capabilities")
    if run["terminal_policy"]=="settle_committed" and "trace" in settlement:
        check(all(t["tool"] in {"retry_execution","reconcile_measurement","await_next"} for t in settlement["trace"]),"only_committed_executor_tools")
        check(all(t["available_at"]<=run["legal_input"]["limits"]["logical_time"] for t in settlement["trace"]),"no_postdeadline_receipt")
    return {**result,"passed":not issues,"issues":sorted(set(issues))}


def stable(value):
    if isinstance(value,list):return [stable(v) for v in value]
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in {"cpu_wall_seconds","wall_seconds","event_hash","previous_hash"}}
    return value


def analyze(directory):
    directory=Path(directory);manifest=json.loads((directory/"manifest.json").read_text());runs={};reports=[]
    for task in manifest["planned_tasks"]:
        name=filename(task);p=directory/name
        if not p.exists():reports.append({"file":name,"passed":False,"issues":["missing_planned_run"]});continue
        run=json.loads(p.read_text());runs[name]=run;reports.append({"file":name,**audit(run)})
    pairs=[]
    for task in manifest["planned_tasks"]:
        if task["terminal_policy"]!="received_only":continue
        a=runs[filename(task)];b=runs[filename(task|{"terminal_policy":"settle_committed"})]
        pairs.append({**{k:task[k] for k in ("seed","family","profile","deadline")},
            "same_scientific_action_prefix":stable(a["decision_prefix_research_events"])==stable(b["decision_prefix_research_events"]),
            "same_gateway_prefix":a["decision_prefix_gateway_events"]==b["decision_prefix_gateway_events"],
            "same_preclose_used":a["decision_prefix_used"]==b["decision_prefix_used"],"same_frozen_model":a["frozen_final"]["model"]==b["frozen_final"]["model"],
            "same_private_score":a["private_score"]==b["private_score"],"received_checks":sum(c["result"] is not None for c in a["research"]["checks"]),
            "settled_checks":sum(c["result"] is not None for c in b["research"]["checks"]),"received_state":a["mechanism_card"]["state"],"settled_state":b["mechanism_card"]["state"],
            "used_delta":{k:b["used"][k]-a["used"][k] for k in a["used"]},"settlement_reason":b["research"]["terminal_settlement"]["reason"]})
    project=Path(__file__).resolve().parents[2];snapshot=project/manifest["snapshot"]
    bad=[rel for rel,sha in manifest["source_sha256"].items() if hashlib.sha256((snapshot/rel).read_bytes()).hexdigest()!=sha]
    result={"phase":manifest["specification"]["phase"],"planned_runs":manifest["expected_runs"],"records":reports,"pairs":pairs,"snapshot_mismatches":bad,
        "all_passed":not bad and all(r["passed"] for r in reports) and all(all(p[k] for k in ("same_scientific_action_prefix","same_gateway_prefix","same_preclose_used","same_frozen_model","same_private_score")) for p in pairs),
        "api_calls":0,"interpretation":"Prospective deterministic termination/receipt execution fixture. Exact within-condition prefix and unchanged model/profit checks; variants share latent worlds and streams. Scope-state availability changes are not new mechanism accuracy or autonomous Agent performance."}
    (directory/"analysis.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");return result


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);args=ap.parse_args();r=analyze(args.directory)
    print(json.dumps({"planned":r["planned_runs"],"passed":sum(x["passed"] for x in r["records"]),"all_passed":r["all_passed"],"issues":[x for x in r["records"] if not x["passed"]],"pairs":r["pairs"]},ensure_ascii=False,indent=2))
