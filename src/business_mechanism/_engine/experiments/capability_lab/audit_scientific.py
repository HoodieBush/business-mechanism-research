"""Public replay acceptance for free scientific workflows, including early stops."""
from collections import Counter
import copy
import json
from pathlib import Path

from confirmation import assess
from lab import predict,validate_model
from mechanism_state import card
from model_protocol import usage_summary
from public_context import unpack
from research_notebook import ResearchNotebook
from public_evidence import PublicEvidenceStore,retrospective_review
from scientific_readiness import readiness,validate_ready_action,validate_request_bindings
from semantic_compile import compile_structured
from temporal_lab import digest


def audit(run):
    issues=[]
    def check(ok,label):
        if not ok:issues.append(label)
    if "private_score" not in run or run.get("status")=="execution_failure":return {"passed":False,"issues":["not_frozen_and_evaluated"],"status":run.get("status")}
    research=run["research"];catalogs={"source":run["legal_input"]["catalog"]};plans={};started={};receipts=[];latest={};sessions=arms=cost=tools=clock=0;finish=None;deployment=None
    check(run["scientific_protocol"]["max_checks"]==6 and run["scientific_protocol"]["n_per_cohort"]==800 and run["scientific_protocol"]["total_alpha"]==.05 and run["scientific_protocol"]["tolerance"]==.05,"fixed_analysis_contract")
    for index,e in enumerate(run["gateway_events"]):
        now=e["available_at"];check(clock<=now<=run["legal_input"]["limits"]["logical_time"] and e["occurred_at"]<=now and e["event_id"]==index,"gateway_time");clock=now
        kind=e["kind"];p=e["payload"]
        if "request" in e:tools+=1;check(e["request_time"]<=now,"request_time")
        if kind=="plan_registered":
            j=p["job_id"];check(j not in plans,"unique_registered_plan");plans[j]=p|{"at":now}
            check(p["plan_id"]==digest({"registered_at":now,"job_id":j,"plan":p["plan"]}),"registered_hash")
            check(set(p["plan"])=={"claim_id","model","action","estimand","randomization_unit","analysis","stopping","rationale"},"complete_preoutcome_plan")
            a=p["plan"]["action"];validate_model(p["plan"]["model"])
            check(abs(a["prediction"]-predict(p["plan"]["model"],catalogs[a["stage"]],a["assortment"],tuple(map(int,a["site"]))))<1e-10,"registered_program_prediction")
        elif kind in {"measurement_received","measurement_revised"}:
            j=p["job_id"];eid=p["experiment_id"];check(j in started and p["available_at"]==now and p["occurred_at"]==started[j]["collection_complete_at"],"measurement_maturity")
            a=plans[j]["plan"]["action"];check(all(p[k]==a[k] for k in ("stage","site","assortment","n")) and p["frozen_prediction"]==a["prediction"],"measurement_matches_plan")
            if kind=="measurement_revised":check(eid in latest and not latest[eid]["verified_meter"] and p["evidence_version"]==2 and started[j].get("audit_at")==now,"revision_no_new_cohort")
            else:check(eid not in latest and p["evidence_version"]==1,"new_independence_group")
            latest[eid]=copy.deepcopy(p);receipts.append(copy.deepcopy(p))
        elif kind=="tool_response":
            tool=e["request"]["tool"]
            if tool in {"audit_history","reconcile_history"}:cost+=1
            elif tool=="open_transfer":catalogs["adaptation"]=p["catalog"]
            elif tool in {"submit_experiment","retry_execution"}:
                j=p["job_id"];check(j in plans and plans[j]["plan_id"]==p["plan_id"],"started_registered_plan")
                check("observed_sales" not in p and "measurement" not in p,"future_count_in_ack")
                if p["status"]=="execution_failed":cost+=1;check(p["samples_consumed"]==0 and j not in started,"failure_not_new_evidence")
                else:
                    a=plans[j]["plan"]["action"];check(j not in started,"one_sampling_start_per_job")
                    started[j]=copy.deepcopy(p);sessions+=a["n"];arms+=1;cost+=5+len(a["assortment"])
                    check(p["started_at"]==e["request_time"] and p["collection_complete_at"]<p["expected_report_at"],"collection_before_report")
            elif tool=="reconcile_measurement":cost+=1;started[e["request"]["args"]["job_id"]]["audit_at"]=e["request_time"]+2;check(p["new_samples"]==0,"meter_repair_no_sampling")
            elif tool=="finish":finish=index
            elif tool=="deployment_catalog":deployment=index;catalogs["deployment"]=p;check(finish is not None and finish<index,"deployment_after_stop")
            check(e["used"]["sessions"]==sessions and e["used"]["arms"]==arms and e["used"]["cost"]==cost,"gateway_budget_replay")
        if "request" in e:check(e["used"]["tool_calls"]==tools,"gateway_tool_calls")
    check(run["used"]=={"sessions":sessions,"arms":arms,"cost":cost,"logical_time":clock,"tool_calls":tools},"final_physical_budget")
    check(all(run["used"][k]<=run["legal_input"]["limits"][k] for k in run["used"]),"physical_caps")
    check(run["public_final_state"]["mature_evidence"]==list(latest.values()),"public_latest_versions")
    previous=None;candidates={};declared_training=set();science_calls=0
    if "public_evidence_store" in research:
        try:check(PublicEvidenceStore.from_events(research["events"]).snapshot()==research["public_evidence_store"],"public_analysis_archive_replay")
        except (ValueError,KeyError,TypeError):check(False,"public_analysis_archive_replay")
    def available(time):return {r["experiment_id"] for r in receipts if r["available_at"]<=time and r["verified_supply"] and r["verified_meter"]}
    def discoveries(time):return {r["experiment_id"] for r in receipts if r["available_at"]<=time and r["verified_supply"] and r["verified_meter"] and plans[r["job_id"]]["plan"]["analysis"]["purpose"]=="discovery"}
    for i,e in enumerate(research["events"]):
        body={k:v for k,v in e.items() if k!="event_hash"};check(e["sequence"]==i and e["previous_hash"]==previous and e["event_hash"]==digest(body),"research_hash_chain");previous=e["event_hash"]
        p=e["payload"];now=e["available_at"]
        if e["kind"]=="candidate_registered":
            cid=p["candidate_id"];check(cid not in candidates,"immutable_candidate_id")
            check(p["content_hash"]==digest({k:v for k,v in p.items() if k not in {"candidate_id","content_hash"}}),"immutable_candidate_hash")
            check(set(p["training_evidence_ids"])<=available(now),"candidate_no_future_training")
            valid=discoveries(now)|declared_training;check(set(p["training_evidence_ids"])<=valid,"candidate_confirmation_release")
            check(set(p.get("information_evidence_ids",[]))<=available(now),"candidate_information_availability")
            validate_model(p["model"]);candidates[cid]=p
        elif e["kind"]=="public_pool_fitted":check(set(p["training_evidence_ids"])==discoveries(now)|declared_training,"pool_target_released_only")
        elif e["kind"]=="registered_plan_linked":
            j=p["job_id"];cid=p["candidate_id"]
            check(cid in candidates and p["plan_id"]==plans[j]["plan_id"] and p["plan"]==plans[j]["plan"],"runtime_gateway_plan_link")
            check(p["plan"]["model"]==candidates[cid]["model"] and p["training_evidence_ids"]==candidates[cid]["training_evidence_ids"],"plan_candidate_commitment")
        elif e["kind"]=="confirmation_evidence_released":
            trigger=next(c for c in research["checks"] if c["check_id"]==p["trigger_check_id"])
            check(trigger["result"] is not None and trigger["result"]["state"]=="contradicted" and trigger["result"]["available_at"]<=now,"release_actual_refutation")
            declared_training=set(p["training_evidence_ids"]);check(declared_training<=available(now),"release_available_only")
        elif e["kind"]=="memory_scope_reviewed":check(p["source_counts_pooled"] is False and p["usage"]=="structure_refit_only" and p["target_state"]=="unconfirmed","memory_no_inherited_certification")
        elif e["kind"]=="scientific_tool_response":
            science_calls+=1
            if p["request"]["tool"]=="review_candidate_evidence" and p["feedback"]["ok"]:
                try:
                    cid=p["request"]["args"]["candidate_id"]
                    expected=retrospective_review(cid,candidates[cid],PublicEvidenceStore.from_events(research["events"][:i]),catalogs,predict)
                    check(p["feedback"]["result"]==expected,"retrospective_diagnostic_recompute")
                except (ValueError,KeyError,TypeError):check(False,"retrospective_diagnostic_recompute")
    check(science_calls==research["calls"]<=64 and research["revisions"]<=2,"science_action_caps")
    check(research["objects"]["candidates"]==list(candidates.values()),"candidate_objects_append_only")
    check(len(research["checks"])<=6 and [c["check_index"] for c in research["checks"]]==list(range(len(research["checks"]))) and len({c["check_id"] for c in research["checks"]})==len(research["checks"]),"unique_declared_check_allocation")
    for c in research["checks"]:
        check(len(c["job_ids"])==2 and c["registered_at"]<=min(plans[j]["at"] for j in c["job_ids"]),"check_registered_before_execution")
        check(c["check_index"]<6,"check_maximum")
        model=candidates[c["candidate_id"]]["model"]
        if c["result"] is None:continue
        r=c["result"];check(r["n"]==1600 and len(set(r["experiment_ids"]))==2,"fixed_independent_confirmation")
        dependencies=set(c["training_evidence_ids"])|set(candidates[c["candidate_id"]].get("information_evidence_ids",[]))
        check(not dependencies&set(r["experiment_ids"]),"confirmation_independent_of_model_information")
        rows=r["cohort_results"];check(all(x==latest[x["experiment_id"]] and x["available_at"]<=r["available_at"] and x["verified_supply"] and x["verified_meter"] for x in rows),"confirmation_valid_receipts")
        expected=assess(sum(x["observed_sales"] for x in rows),1600,r["frozen_prediction"],max_checks=6)
        check(all(r[k]==v for k,v in expected.items()),"confirmation_exact_recompute")
        check(all(plans[j]["plan"]["model"]==model for j in c["job_ids"]),"check_frozen_model")
    completed=[c["result"] for c in research["checks"] if c["result"] is not None]
    expected_card=card(run["frozen_final"]["model"],research["final"]["mechanism_card"]["physical_definitions"],research["versions"],completed)
    check(run["mechanism_card"]["state"]==expected_card["state"] and run["mechanism_card"]["conditional_claims"]==expected_card["conditional_claims"],"scoped_card_recompute")
    usage=usage_summary(run["model_calls"]);api_limits=run["scientific_protocol"].get("api_limits",{"calls":16,"reported_tokens":80000})
    check(usage==run["model_usage"] and usage["api_calls"]<=api_limits["calls"] and usage["total_tokens"]<=api_limits["reported_tokens"],"api_usage_and_caps")
    if "api_limits" in run["scientific_protocol"]:check(api_limits["calls"]==run["legal_input"]["limits"]["api_calls"] and api_limits["reported_tokens"]==run["legal_input"]["limits"]["api_tokens"],"api_declared_task_allocation")
    notebook=ResearchNotebook();context_notebooks={}
    for record in run["model_calls"]:
        if "organization_context_id" in record:notebook=context_notebooks.setdefault(record["organization_context_id"],ResearchNotebook())
        try:context=unpack(json.loads(record["request"]["messages"][-1]["content"]));state=context["research_state"]
        except (ValueError,TypeError,KeyError):check(False,"api_context_encoding");continue
        if record.get("state_aware"):
            check(record["notebook_before_request"]==notebook.snapshot() and state["reading_notebook"]==notebook.view(),"public_notebook_replay")
            check(state["action_preconditions"]==readiness(state),"public_readiness_recompute")
            reviews=record.get("public_precondition_reviews",[])
            check(len(reviews)==len(record.get("actions",[]))==len(record.get("tool_feedbacks",[])),"per_action_public_review_count")
            for review,action,feedback in zip(reviews,record.get("actions",[]),record.get("tool_feedbacks",[])):
                before=review["state"];check(review["action"]==action,"public_review_action_identity")
                try:
                    if record.get("reference_contract_version"):
                        from reference_contract import validate_action as validate_references
                        validate_references(action,state);validate_references(action,before)
                    validate_request_bindings(action,state);validate_ready_action(action,before);accepted=True
                except ValueError:accepted=False
                check(accepted==review["accepted"],"public_review_decision_recompute")
                prefix=research["events"][:review["research_event_count"]]
                check(before["candidate_count"]==sum(e["kind"]=="candidate_registered" for e in prefix),"review_no_future_candidate_count")
                check(all("observed_sales" not in j and "measurement" not in j for j in before["pending_jobs"]),"review_pending_count_boundary")
                check(set(before["training_evidence_ids"])<=available(before["clock"]),"review_received_training_only")
                if not accepted:check(feedback.get("executed") is False and feedback.get("public_precondition_rejected") is True,"rejected_action_not_executed")
                if feedback["ok"]:
                    actual=next((e for e in research["events"][review["research_event_count"]:] if e["kind"]=="scientific_tool_response" and e["payload"]["request"]==action),None)
                    check(actual is not None,"notebook_actual_public_response")
                    if actual is not None:notebook.observe(action,feedback,actual["available_at"])
        if record.get("native_protocol_version"):
            from native_science_protocol import function_definitions
            expected_functions=function_definitions(state if record.get("state_aware") else None,
                reference_contract=bool(record.get("reference_contract_version")))
            if "research_organization" not in state:expected_functions=[value for value in expected_functions if value["function"]["name"] not in {"dispatch_research_context","append_research_note"}]
            check(record["request"]["tools"]==expected_functions,"native_function_contract_recompute")
        if "public_research_event_count" in record:
            count=record["public_research_event_count"];prefix=research["events"][:count]
            check(type(count) is int and 0<count<=len(research["events"]) and prefix[-1]["event_hash"]==record["public_research_prefix_hash"],"api_public_event_prefix")
            public_candidates={e["payload"]["candidate_id"]:e["payload"] for e in prefix if e["kind"]=="candidate_registered"}
            check(("confirmation_status" in state)==bool(record.get("confirmation_phase_version")),"confirmation_phase_delivery_marker")
            if record.get("confirmation_phase_version"):
                from confirmation_phase import from_events
                try:
                    expected_phase=from_events(prefix,record["clock"])
                    check(state["confirmation_status"]==expected_phase and record["confirmation_phase_version"]==expected_phase["version"],"confirmation_phase_public_prefix_recompute")
                except (ValueError,KeyError,TypeError):check(False,"confirmation_phase_public_prefix_recompute")
            if "public_evidence_store" in state:
                try:check(state["public_evidence_store"]==PublicEvidenceStore.from_events(prefix).view(),"api_public_conditional_analyses")
                except (ValueError,KeyError,TypeError):check(False,"api_public_conditional_analyses")
            for candidate in state["candidates"]:
                cid=candidate["candidate_id"];check(cid in public_candidates,"api_candidate_available_before_request")
                if cid in public_candidates:
                    original=public_candidates[cid]
                    check(all(candidate[k]==original[k] for k in candidate if k!="expression") and candidate["expression"]==original["model"]["expression"],"api_immutable_candidate_summary")
            def references(value):
                if isinstance(value,list):return all(references(v) for v in value)
                if not isinstance(value,dict):return True
                if "current_state_reference" in value:return set(value)=={"candidate_id","current_state_reference"} and value["candidate_id"] in {c["candidate_id"] for c in state["candidates"]}
                return all(references(v) for v in value.values())
            check(all(references(unpack(json.loads(m["content"]))) for m in record["request"]["messages"] if m["role"]=="tool"),"api_candidate_references_resolve")
        check(state["clock"]==record["clock"] and set(record["public_training_ids"])<=available(record["clock"]),"api_public_time")
        check(not any(k in context or k in state for k in ("private_configuration","private_score","generator","source_code")),"api_private_boundary")
        for row in state["verified_condition_table"]:
            candidates_r=[r for r in receipts if r["experiment_id"]==row["experiment_id"] and r["available_at"]<=record["clock"] and r["verified_supply"] and r["verified_meter"]]
            check(bool(candidates_r) and all(row[k]==candidates_r[-1][k] for k in row),"api_verified_received_only")
        check(all("observed_sales" not in j and "measurement" not in j for j in state["pending_jobs"]),"api_pending_count_boundary")
    if "reading_notebook" in run:check(run["reading_notebook"]==notebook.snapshot(),"final_public_notebook")
    if "discovery_tasks" in research:
        from audit_discovery_tasks import audit as task_audit
        try:
            task_result=task_audit(run)
            for issue in task_result["issues"]:check(False,"discovery_task:"+issue)
        except (ValueError,KeyError,TypeError,IndexError):check(False,"discovery_task:malformed_archive")
    if "reading_notebooks" in run:check(run["reading_notebooks"]=={k:v.snapshot() for k,v in context_notebooks.items()},"final_organization_notebooks")
    check(deployment is not None and run["deployed_model"]["expression"]==run["frozen_final"]["model"]["expression"] and run["frozen_expression_sha256"]==digest(run["deployed_model"]["expression"]),"frozen_deployment")
    if deployment is not None:
        facts=compile_structured([p for rows in catalogs.values() for p in rows])
        check(run["deployment_physical_facts"]==facts and run["deployed_model"]["role_patterns"]==facts["role_patterns"],"public_deployment_role_binding")
    for profile in run["private_score"]["profiles"]:
        for day in profile["daily_trajectories"]:
            for key in ("policy","oracle"):
                r=day[key];check(r["opening"]==r["sales"]+r["ending"] and r["demand"]==r["sales"]+r["lost_sales"],"inventory_conservation")
    return {"passed":not issues,"issues":sorted(set(issues)),"status":run["status"],"registered_checks":len(research["checks"]),"completed_checks":len(completed),
        "proposal_candidates":sum(c["origin"]=="policy_proposal" for c in candidates.values()),"memory_reviews":len(research["memory_reviews"])}


def summarize(directory):
    directory=Path(directory);manifest=json.loads((directory/"manifest.json").read_text());records=[];runs=[]
    for task in manifest["planned_tasks"]:
        name=f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json";p=directory/name
        if not p.exists():records.append({"file":name,"passed":False,"issues":["missing_planned_run"]});continue
        run=json.loads(p.read_text());runs.append(run);report=audit(run)
        expected={k:task[k] for k in ("seed","family","profile")}|{"price":manifest["specification"]["price"],"deadline":manifest["specification"]["deadline"]}
        if run["private_configuration"]!=expected or run["strategy"]!=task["strategy"]:report["passed"]=False;report["issues"].append("manifest_task_mismatch")
        records.append({"file":name,**report})
    out={"phase":manifest["specification"]["phase"],"planned_runs":manifest["expected_runs"],"records":records,"status_counts":dict(Counter(r["status"] for r in runs)),
        "model_usage":usage_summary([c for r in runs for c in r["model_calls"]]),"endpoints":[{"seed":r["private_configuration"]["seed"],"family":r["private_configuration"]["family"],"strategy":r["strategy"],
            "status":r["status"],"sessions":r["used"]["sessions"],"clock":r["used"]["logical_time"],"checks":sum(c["result"] is not None for c in r["research"]["checks"]),
            "effect_rmse":r.get("private_score",{}).get("heldout_effect_rmse"),"regret":r.get("private_score",{}).get("mean_expected_operating_regret_per_customer")} for r in runs],
        "interpretation":"Opened development worlds. Runtime/actor/macro controls are components, not full same-capability A/B/C. Failed/early/budget stops retained; unequal realized samples and CPU/API wall costs separately reported."}
    (directory/"analysis.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n");return out


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);args=ap.parse_args();r=summarize(args.directory)
    print(json.dumps({"planned":r["planned_runs"],"passed":sum(x["passed"] for x in r["records"]),"issues":[x for x in r["records"] if not x["passed"]],"endpoints":r["endpoints"],"usage":r["model_usage"]},ensure_ascii=False,indent=2))
