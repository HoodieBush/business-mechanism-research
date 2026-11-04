"""Post-development semantic mutation checks, separate from experiment tasks."""
import copy
import json
from pathlib import Path

from audit_scientific import audit
from temporal_lab import digest

ROOT=Path(__file__).resolve().parent


def rehash_research(run):
    for candidate in run["research"]["objects"]["candidates"]:
        candidate["content_hash"]=digest({k:v for k,v in candidate.items() if k not in {"candidate_id","content_hash"}})
    objects={c["candidate_id"]:c for c in run["research"]["objects"]["candidates"]}
    previous=None
    for event in run["research"]["events"]:
        if event["kind"]=="candidate_registered":event["payload"]=copy.deepcopy(objects[event["payload"]["candidate_id"]])
        event["previous_hash"]=previous;event["event_hash"]=digest({k:v for k,v in event.items() if k!="event_hash"});previous=event["event_hash"]
    for record in run["model_calls"]:
        if "public_research_event_count" in record:record["public_research_prefix_hash"]=run["research"]["events"][record["public_research_event_count"]-1]["event_hash"]


def challenge(directory):
    directory=Path(directory)
    manifest=json.loads((directory/"manifest.json").read_text());seed=manifest["specification"]["seeds"][0]
    numeric=json.loads((directory/f"numeric_review_mixed_scope_interruptions_s{seed}.json").read_text())
    actor=json.loads((directory/f"llm_scientific_threeway_interruptions_s{seed}.json").read_text())
    reports=[]
    def check(name,original,mutate,label,rehash=False):
        run=copy.deepcopy(original);mutate(run)
        if rehash:rehash_research(run)
        result=audit(run)
        reports.append({"challenge":name,"expected_issue":label,"caught":not result["passed"] and label in result["issues"],"issues":result["issues"]})
    check("future_training_even_with_valid_hashes",numeric,lambda r:r["research"]["objects"]["candidates"][0].update(training_evidence_ids=[999999]),"candidate_no_future_training",True)
    check("source_cohort_entering_target_fit",numeric,lambda r:r["research"]["objects"]["candidates"][0].update(training_evidence_ids=["source-only-cohort"]),"candidate_confirmation_release",True)
    def own_confirmation(r):
        c=r["research"]["checks"][0];model=next(x for x in r["research"]["objects"]["candidates"] if x["candidate_id"]==c["candidate_id"])
        model["information_evidence_ids"]=c["result"]["experiment_ids"].copy()
    check("exposed_confirmation_used_to_certify_model",numeric,own_confirmation,"confirmation_independent_of_model_information",True)
    check("free_source_certification",numeric,lambda r:next(e["payload"] for e in r["research"]["events"] if e["kind"]=="memory_scope_reviewed").update(source_counts_pooled=True),"memory_no_inherited_certification",True)
    check("physical_sample_cost_reset",numeric,lambda r:r["used"].update(sessions=0),"final_physical_budget")
    def pending_count(r):
        c=r["model_calls"][0];context=json.loads(c["request"]["messages"][-1]["content"])
        context["research_state"]["pending_jobs"]=[{"job_id":"J_fake","observed_sales":1}]
        c["request"]["messages"][-1]["content"]=json.dumps(context,ensure_ascii=False)
    check("pending_future_count_in_api_view",actor,pending_count,"api_pending_count_boundary")
    def private_view(r):
        c=r["model_calls"][0];context=json.loads(c["request"]["messages"][-1]["content"]);context["private_score"]={"hidden":True}
        c["request"]["messages"][-1]["content"]=json.dumps(context,ensure_ascii=False)
    check("private_evaluation_in_api_context",actor,private_view,"api_private_boundary")
    check("poststop_probability_change",numeric,lambda r:r["deployed_model"].update(expression=.99),"frozen_deployment")
    check("poststop_invented_product_binding",numeric,lambda r:r["deployed_model"]["role_patterns"].update(heating=["fabricated"]),"public_deployment_role_binding")
    check("duplicate_alpha_allocation",numeric,lambda r:r["research"]["checks"][1].update(check_index=0),"unique_declared_check_allocation")
    if "public_research_event_count" in actor["model_calls"][0]:
        check("same_clock_public_prefix_hash_change",actor,lambda r:r["model_calls"][0].update(public_research_prefix_hash="invalid"),"api_public_event_prefix")
        def unresolved_reference(r):
            m=next(m for c in r["model_calls"] for m in c["request"]["messages"] if m["role"]=="tool")
            m["content"]=json.dumps({"ok":True,"result":{"candidate_id":"C_missing","current_state_reference":"research_state.candidates"}})
        check("candidate_feedback_reference_absent_from_current_view",actor,unresolved_reference,"api_candidate_references_resolve")
        def malformed_table(r):
            c=r["model_calls"][0];context=json.loads(c["request"]["messages"][-1]["content"])
            context["research_state"]["verified_condition_table"]={"_table":{"columns":["experiment_id"],"rows":[[1,2]]}}
            c["request"]["messages"][-1]["content"]=json.dumps(context,ensure_ascii=False)
        check("malformed_table_cannot_hide_extra_count",actor,malformed_table,"api_context_encoding")
    aware_file=directory/f"llm_state_aware_threeway_interruptions_s{seed}.json"
    if aware_file.exists():
        aware=json.loads(aware_file.read_text())
        def readiness_override(r):
            c=r["model_calls"][0];context=json.loads(c["request"]["messages"][-1]["content"])
            context["research_state"]["action_preconditions"]["services"]["fit_pool"]["ready"]=True
            c["request"]["messages"][-1]["content"]=json.dumps(context,ensure_ascii=False)
        check("no_data_fit_ready_flag_changed",aware,readiness_override,"public_readiness_recompute")
        check("past_read_receipt_inserted_before_request",aware,lambda r:r["model_calls"][0]["notebook_before_request"]["entries"].append({"fake":True}),"public_notebook_replay")
        def review_flip(r):
            review=next(v for c in r["model_calls"] for v in c.get("public_precondition_reviews",[]));review["accepted"]=not review["accepted"]
        check("per_action_acceptance_overridden",aware,review_flip,"public_review_decision_recompute")
    out={"source_phase":directory.name,"source_audits_passed":audit(numeric)["passed"] and audit(actor)["passed"],"challenges":reports,
        "all_caught":all(x["caught"] for x in reports),"interpretation":"Post-development acceptance mutations of archived opened tasks. Rehashed semantic corruptions test beyond hash mismatch. These are not new independent tasks, preregistered treatment effects, or proof against arbitrary private information leaks."}
    (directory/"audit-challenges.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n");return out


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);args=ap.parse_args();r=challenge(args.directory)
    print(json.dumps({"source_audits_passed":r["source_audits_passed"],"all_caught":r["all_caught"],"challenges":r["challenges"]},ensure_ascii=False,indent=2))
