"""Offline audit of public memory provenance, target fits and prior checks."""
import argparse
from collections import Counter
import json
from pathlib import Path

from analyze_openworld import read_runs,key
from conditional_memory import ConditionalMemory,archive,digest,validate_archive
from confirmation import assess
from replay_evidence import ReplayEvidence


def audit_memory(row,value):
    if row["status"]!="finished":return {"status":"not_finished","issues":[]}
    issues=[];trace=row["memory_trace"];mode=trace["mode"]
    expected=ConditionalMemory(value,row["legal_input"],row["adaptation_physical_facts"],mode)
    if trace["archive_id"]!=value["archive_id"]:issues.append("wrong_archive_identity")
    if trace["source_acquisition_cost_shared"]!=value["source_acquisition_cost"]:issues.append("wrong_shared_source_cost")
    if trace["retrieval"]!=expected.trace()["retrieval"]:issues.append("retrieval_not_based_on_public_scope")
    if trace["target_likelihood_uses_source_counts"]:issues.append("source_counts_claimed_in_target_fit")
    eligible={e["episode"]["episode_id"] for e in expected.entries if e["eligible"]}
    view=ReplayEvidence(row["legal_input"],row["events"])
    results={r["experiment_id"]:r for r,_ in view.verified_observations()}
    decisions=[d for d in row["design_decisions"] if d["phase"]=="discovery"]
    diagnostics=[]
    for d in decisions:
        action=d["action"]
        priors=expected.prior_predictions(view,action)
        if priors!=d.get("memory_prior_predictions",[]):issues.append("prior_prediction_not_from_frozen_source")
        responses=[r for r in results.values() if r["experiment_id"]<12 and r["stage"]==action["stage"] and
            r["site"]==action["site"] and set(r["assortment"])==set(action["assortment"])]
        if len(responses)!=1:issues.append("missing_unique_future_discovery_cohort");continue
        expected.observe_prior_predictions(priors,responses[0],max_checks=7*len(value["episodes"]))
    if trace["prior_parameter_checks"]!=expected.trace()["prior_parameter_checks"]:issues.append("source_parameter_check_changed")
    if len(trace["prior_parameter_checks"])>7*len(value["episodes"]):issues.append("too_many_prior_checks")
    frozen=[v for v in row["research_versions"] if v["phase"]=="confirmation_model_frozen"]
    if len(frozen)!=len(trace["target_versions"]):issues.append("missing_target_memory_versions")
    for v,t in zip(frozen,trace["target_versions"]):
        if t["instance_id"]!=digest(v["model"]) or t["target_training_ids"]!=v["training_evidence_ids"]:
            issues.append("target_dependency_model_mismatch")
        if not set(t["memory_episode_refs"])<=eligible:issues.append("selected_ineligible_memory_episode")
        checks=[c for c in row["confirmations"] if c["round"]==v["round"]]
        ids=[i for c in checks for i in c["experiment_ids"]]
        if t["target_check_ids"]!=ids or set(ids)&set(t["target_training_ids"]):issues.append("target_check_reused_for_own_memory_version")
        state="refuted_in_target_conditions" if any(c["state"]=="contradicted" for c in checks) else (
            "supported_in_target_conditions" if all(c["state"]=="supported_within_tolerance" for c in checks) else "pending_target_confirmation")
        if t["state"]!=state:issues.append("target_memory_state_not_from_fresh_checks")
    for v in row["research_versions"]:
        for c in v.get("candidate_pool",[]):
            if c.get("origin")!="conditional_memory":continue
            if c["target_training_ids"]!=v["training_evidence_ids"]:issues.append("memory_candidate_uses_other_training_ids")
            if not set(c["memory_episode_refs"])<=eligible:issues.append("memory_candidate_not_from_retrieved_source")
    count=0
    for event in row["events"]:
        tool=event["request"]["tool"];response=event["response"]
        if tool=="experiment":count+=1
        elif tool=="fit_candidate" and response["verified_cohorts"]!=count:issues.append("fit_service_saw_non_target_cohorts")
    try:validate_archive(archive([row["public_memory_export"]]))
    except (ValueError,KeyError,TypeError):issues.append("invalid_target_public_export")
    if row["private_score"]["economics"]!=row["legal_input"]["operating_objective"]:issues.append("operating_evaluator_changed_public_price_contract")
    return {"status":"passed" if not issues else "failed","issues":sorted(set(issues)),
        "retrieved_episodes":len(eligible),"prior_parameter_check_states":dict(Counter(c["state"] for c in trace["prior_parameter_checks"])),
        "supported_source_condition_but_target_parameter_refuted":sum(c["source_condition_state"]=="supported_within_tolerance" and c["state"]=="contradicted" for c in trace["prior_parameter_checks"]),
        "memory_selected_confirmation_rounds":sum(bool(v["memory_episode_refs"]) for v in trace["target_versions"]),
        "memory_selected_then_refuted":sum(bool(v["memory_episode_refs"]) and v["state"]=="refuted_in_target_conditions" for v in trace["target_versions"])}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directory",type=Path)
    args=parser.parse_args();manifest=json.loads((args.directory/"manifest.json").read_text())
    project=Path(__file__).resolve().parents[2]
    archive_path=project/manifest["snapshot"]/manifest["specification"]["memory_archive"]
    value=validate_archive(json.loads(archive_path.read_text()))
    rows=[{"task":list(key(r)),**audit_memory(r,value)} for r in read_runs(args.directory)]
    result={"archive_id":value["archive_id"],"audits":rows,"status_counts":dict(Counter(r["status"] for r in rows)),
        "not_established":["一般因果可迁移性","跨任务源证据撤销后的完整 Agent 运行","完整 LLM 记忆能力与组织价值"]}
    (args.directory/"memory-audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status_counts":result["status_counts"],"retrieved_episodes":sum(r.get("retrieved_episodes",0) for r in rows),
        "memory_selected_rounds":sum(r.get("memory_selected_confirmation_rounds",0) for r in rows),
        "memory_selected_then_refuted":sum(r.get("memory_selected_then_refuted",0) for r in rows),
        "supported_source_condition_but_target_parameter_refuted":sum(r.get("supported_source_condition_but_target_parameter_refuted",0) for r in rows)}))
