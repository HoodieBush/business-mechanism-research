"""Offline replay of public availability, registration, repairs and budgets."""
import argparse
import copy
import json
from pathlib import Path
import statistics

from confirmation import assess
from lab import predict,validate_model
from mechanism_state import card
from model_protocol import usage_summary
from temporal_lab import digest


def audit(run):
    failures=[]
    def check(condition,label):
        if not condition:failures.append(label)
    if run.get("status") not in {"finished","deadline_unresolved"}:return {"passed":False,"failures":["run_not_frozen"],"status":run.get("status")}
    public=run["legal_input"];limits=public["limits"];deadline=limits["logical_time"]
    check(all(h["occurred_at"]<=h["available_at"]<=0 for h in public["history"]),"historical_time")
    catalogs={"source":public["catalog"]};jobs={};latest={};fit_scope=None;clock=0;tool_calls=0;cost=0;sessions=0;arms=0
    started={};fit_events=[];receipts=[];frozen_at=None;deployment_at=None;registered_ids=[]
    for index,e in enumerate(run["events"]):
        kind=e["kind"];payload=e["payload"];now=e["available_at"]
        check(e["event_id"]==index and clock<=now<=deadline and e["occurred_at"]<=now,f"event_time_{index}");clock=now
        if "request" in e:
            tool_calls+=1;check(e["request_time"]<=now,f"request_time_{index}")
        if kind=="plan_registered":
            j=payload["job_id"];p=payload["plan"];a=p["action"];registered_ids.append(j)
            check(j not in jobs,f"unique_plan_{j}")
            check(payload["plan_id"]==digest({"registered_at":now,"job_id":j,"plan":p}),f"plan_hash_{j}")
            validate_model(p["model"])
            check(abs(a["prediction"]-predict(p["model"],catalogs[a["stage"]],a["assortment"],tuple(map(int,a["site"]))))<1e-10,f"executable_prediction_{j}")
            check(p["stopping"]=={"deadline":deadline,"missing_result":"unresolved","execution_failure":"repair_before_science","unverified_meter":"exclude_until_reconciled"},f"stopping_{j}")
            check(p["estimand"]=="purchase_probability_in_fixed_condition" and p["randomization_unit"]=="qualified_session",f"estimand_{j}")
            jobs[j]={"plan":copy.deepcopy(p),"plan_id":payload["plan_id"],"registered_at":now,"training_at_registration":set(r["experiment_id"] for r in latest.values() if r["verified_supply"] and r["verified_meter"] and (fit_scope is None or r["experiment_id"] in fit_scope))}
        elif kind in {"measurement_received","measurement_revised"}:
            r=payload;j=r["job_id"];eid=r["experiment_id"];receipts.append(copy.deepcopy(r))
            check(j in started and started[j]["experiment_id"]==eid,f"receipt_started_{index}")
            if j not in started:continue
            s=started[j];a=jobs[j]["plan"]["action"]
            check(r["occurred_at"]==s["collection_complete_at"]<=now and r["available_at"]==now,f"receipt_maturity_{index}")
            check(all(r[k]==a[k] for k in ("stage","site","assortment","n")),f"receipt_design_{index}")
            check(r["frozen_prediction"]==a["prediction"] and 0<=r["observed_sales"]<=r["n"],f"receipt_counts_{index}")
            if kind=="measurement_received":check(eid not in latest and r["evidence_version"]==1,f"new_receipt_{index}")
            else:
                check(eid in latest and not latest[eid]["verified_meter"] and r["evidence_version"]==2 and r["verified_meter"],f"revision_receipt_{index}")
                check(s.get("audit_expected_at")==now,f"audit_delay_{index}")
            latest[eid]=copy.deepcopy(r)
        elif kind=="fit_scope_frozen":
            ids=payload["training_ids"];valid={r["experiment_id"] for r in latest.values() if r["verified_supply"] and r["verified_meter"]}
            check(ids is None or set(ids)<=valid,f"fit_scope_available_{index}");fit_scope=None if ids is None else set(ids)
        elif kind=="public_fit_snapshot":
            valid={r["experiment_id"] for r in latest.values() if r["verified_supply"] and r["verified_meter"] and (fit_scope is None or r["experiment_id"] in fit_scope)}
            check(set(payload["training_evidence_ids"])==valid,f"fit_no_future_{index}")
            fit_events.append((now,payload["training_evidence_ids"],payload["candidate_models_sha256"]))
        elif kind=="schedule_choice":
            valid={r["experiment_id"] for r in latest.values() if r["verified_supply"] and r["verified_meter"] and (fit_scope is None or r["experiment_id"] in fit_scope)}
            check(set(payload["available_training_ids"])==valid,f"schedule_no_future_{index}")
        elif kind=="tool_response":
            request=e["request"];tool=request["tool"]
            if tool in {"audit_history","reconcile_history"}:cost+=1
            elif tool=="open_transfer":catalogs["adaptation"]=copy.deepcopy(payload["catalog"])
            elif tool in {"submit_experiment","retry_execution"}:
                j=payload["job_id"];check(j in jobs and payload["plan_id"]==jobs[j]["plan_id"],f"ack_registered_{index}")
                check("observed_sales" not in payload and "measurement" not in payload,f"ack_no_future_{index}")
                if payload["status"]=="execution_failed":
                    cost+=1;check(payload["samples_consumed"]==0 and j not in started,f"failure_not_science_{index}")
                else:
                    check(j not in started,f"unique_start_{index}");a=jobs[j]["plan"]["action"]
                    started[j]=copy.deepcopy(payload);sessions+=a["n"];arms+=1;cost+=5+len(a["assortment"])
                    check(payload["started_at"]==e["request_time"] and payload["collection_complete_at"]>e["request_time"] and payload["expected_report_at"]>payload["collection_complete_at"],f"start_time_{index}")
            elif tool=="reconcile_measurement":
                cost+=1;j=request["args"]["job_id"];started[j]["audit_expected_at"]=e["request_time"]+2
                check(payload["new_samples"]==0 and payload["expected_report_at"]==e["request_time"]+2,f"repair_no_samples_{index}")
            elif tool=="finish":frozen_at=index
            elif tool=="deployment_catalog":
                check(frozen_at is not None and frozen_at<index,f"deploy_after_freeze_{index}");deployment_at=index
            check(e["used"]["sessions"]==sessions and e["used"]["arms"]==arms and e["used"]["cost"]==cost,f"event_budget_{index}")
        if "request" in e:check(e["used"]["tool_calls"]==tool_calls,f"tool_budget_{index}")
    check(sorted(jobs)==list(range(len(jobs))),"job_numbering")
    check(run["used"]=={"sessions":sessions,"arms":arms,"cost":cost,"logical_time":clock,"tool_calls":tool_calls},"final_budget")
    check(all(run["used"][k]<=limits[k] for k in run["used"]),"limits")
    check(run["public_final_state"]["mature_evidence"]==list(latest.values()),"final_latest_only")
    for j in run["public_final_state"]["pending_jobs"]:
        check("_private_result" not in j,"pending_private_result")
        if j["status"]=="pending":check("measurement" not in j,"pending_outcome")
    for v in run["research_versions"]:
        if v["phase"]=="public_fit_snapshot":
            check((v["clock"],v["training_evidence_ids"],digest([r["model"] for r in v["candidate_pool"]])) in fit_events,"fit_snapshot_link")
    frozen={v["round"]:v for v in run["research_versions"] if v["phase"]=="confirmation_model_frozen"}
    for c in run["confirmations"]:
        ids=c["experiment_ids"];v=frozen[c["round"]]
        check(len(ids)==2 and len(set(ids))==2 and not set(ids)&set(v["training_evidence_ids"]),"independent_confirmation")
        rows=c["cohort_results"]
        check(all(r==latest.get(r["experiment_id"]) and r["available_at"]<=c["available_at"] and r["verified_supply"] and r["verified_meter"] for r in rows),"confirmation_maturity")
        check(c["n"]==1600 and c["count"]==sum(r["observed_sales"] for r in rows),"fixed_confirmation_n")
        expected=assess(c["count"],c["n"],c["frozen_prediction"],max_checks=6)
        check(all(c[k]==value for k,value in expected.items()),"exact_confirmation_recompute")
        for r in rows:
            j=r["job_id"];p=jobs[j]["plan"]
            check(p["model"]==v["model"] and jobs[j]["registered_at"]>=v["clock"],"confirmation_frozen_model")
            check(p["analysis"]=={"purpose":"confirmation","rule":"clopper_pearson","max_checks":6,"total_alpha":.05,"tolerance":.05},"confirmation_predeclared")
            check(set(v["training_evidence_ids"])==jobs[j]["training_at_registration"],"confirmation_training_frozen")
    usage=usage_summary(run["model_calls"]);check(usage==run["model_usage"],"api_usage")
    check(usage["api_calls"]<=8 and usage["total_tokens"]<=60000,"api_allocation")
    for record in run["model_calls"]:
        context=json.loads(record["request"]["messages"][1]["content"])
        check(context["clock"]==record["clock"] and set(record["training_evidence_ids"])=={r["experiment_id"] for r in context["verified_evidence"]},"api_training_snapshot")
        for row in context["verified_evidence"]:
            matches=[r for r in receipts if r["experiment_id"]==row["experiment_id"] and r["available_at"]<=record["clock"] and r["verified_meter"] and r["verified_supply"]]
            check(bool(matches) and all(row[k]==matches[-1][k] for k in row),"api_no_future")
        check(not any(k in context for k in ("private_configuration","private_score","source_code","generator")),"api_private_boundary")
        check(all("measurement" not in j and "observed_sales" not in j for j in context["pending_jobs"]),"api_pending_no_outcome")
    check(deployment_at is not None,"deployment_receipt")
    check(run["deployed_model"]["expression"]==run["frozen_final"]["model"]["expression"] and run["frozen_expression_sha256"]==digest(run["deployed_model"]["expression"]),"frozen_deployment")
    check(run["frozen_final"]["model"]==frozen[max(frozen)]["model"],"final_confirmation_version")
    if run["status"]=="finished":check(len(run["confirmations"])==6,"finished_all_checks")
    else:check(clock==deadline and len(run["confirmations"])<6 and run["frozen_final"]["unresolved"],"deadline_unresolved")
    expected_card=card(run["frozen_final"]["model"],run["physical_facts"]["ontology"],run["research_versions"],run["confirmations"])
    check(run["mechanism_card"]["state"]==expected_card["state"],"conditional_state_not_erased_by_calendar")
    if run["version"]=="temporal-v0.3-separate-calendar-and-conditional-state":
        check(run["mechanism_card"]["research_coverage_state"]==("incomplete" if len(run["confirmations"])<6 else "complete"),"separate_calendar_coverage")
    for profile in run["private_score"]["profiles"]:
        for day in profile["daily_trajectories"]:
            for name in ("policy","oracle"):
                r=day[name];check(r["opening"]==r["sales"]+r["ending"] and r["demand"]==r["sales"]+r["lost_sales"],"inventory_conservation")
    return {"passed":not failures,"failures":sorted(set(failures)),"status":run["status"],"checks":len(run["confirmations"]),
        "execution_failures":sum(e["kind"]=="tool_response" and isinstance(e["payload"],dict) and e["payload"].get("status")=="execution_failed" for e in run["events"]),
        "measurement_revisions":sum(e["kind"]=="measurement_revised" for e in run["events"]),"physical_cohorts":arms,"logical_time":clock}


def summarize(directory):
    directory=Path(directory);manifest=json.loads((directory/"manifest.json").read_text());records=[];by_key={}
    for task in manifest["planned_tasks"]:
        name=f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json";path=directory/name
        if not path.exists():records.append({"file":name,"passed":False,"failures":["missing_planned_run"]});continue
        run=json.loads(path.read_text());key=(task["seed"],task["family"],task["profile"],task["strategy"])
        expected={k:task[k] for k in ("seed","family","profile")}|{"deadline":manifest["specification"]["deadline"]}
        check=audit(run)
        if run["private_configuration"]!=expected or run["strategy"]!=task["strategy"]:check["passed"]=False;check["failures"].append("task_manifest_mismatch")
        records.append({"file":name,**check});by_key[key]=run
    groups=[]
    for family in manifest["specification"]["families"]:
        for profile in manifest["specification"]["profiles"]:
            for strategy in manifest["specification"]["strategies"]:
                runs=[r for k,r in by_key.items() if k[1:]==(family,profile,strategy)]
                scored=[r for r in runs if "private_score" in r]
                groups.append({"family":family,"profile":profile,"strategy":strategy,"planned":len(manifest["specification"]["seeds"]),
                    "observed":len(runs),"finished":sum(r["status"]=="finished" for r in runs),"deadline_unresolved":sum(r["status"]=="deadline_unresolved" for r in runs),
                    "mean_clock":statistics.mean(r["used"]["logical_time"] for r in runs) if runs else None,
                    "mean_sessions":statistics.mean(r["used"]["sessions"] for r in runs) if runs else None,
                    "mean_checks":statistics.mean(len(r["confirmations"]) for r in runs) if runs else None,
                    "mean_effect_rmse":statistics.mean(r["private_score"]["heldout_effect_rmse"] for r in scored) if scored else None,
                    "mean_regret_per_customer":statistics.mean(r["private_score"]["mean_expected_operating_regret_per_customer"] for r in scored) if scored else None})
    output={"phase":manifest["specification"]["phase"],"planned_runs":manifest["expected_runs"],"records":records,"groups":groups,
        "model_usage":usage_summary([c for r in by_key.values() for c in r["model_calls"]]),
        "interpretation":"Development only. Seeds are clusters; methods and event profiles share underlying worlds. Calendar is simulated research time, excludes API/CPU wall time. Same caps do not imply same realized evidence under a deadline."}
    (directory/"analysis.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    return output


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);args=ap.parse_args();out=summarize(args.directory)
    print(json.dumps({"planned":out["planned_runs"],"passed":sum(r["passed"] for r in out["records"]),"failures":[r for r in out["records"] if not r["passed"]],"groups":out["groups"],"usage":out["model_usage"]},ensure_ascii=False,indent=2))
