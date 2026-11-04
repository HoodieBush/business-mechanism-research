"""Offline task denominators, paired endpoints, and freeze-boundary auditing."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import itertools
import json
from pathlib import Path
import statistics

from lab import predict
from choice_world import ChoiceWorld
from operating_eval import physical_fact_audit
from confirmation import assess

ENDPOINTS=("heldout_effect_rmse","heldout_probability_rmse","mean_expected_operating_regret_per_customer")


def key(row):
    c=row["private_configuration"]
    return tuple(c[k] for k in ("seed","family","fault","fact_mode"))+(c.get("retail_price",8.),row["strategy"])


def read_runs(directory):
    directory=Path(directory);manifest=json.loads((directory/"manifest.json").read_text())
    rows=[]
    for task in manifest["planned_tasks"]:
        price=task.get("retail_price",manifest.get("specification",{}).get("retail_price",8.))
        name=f"{task['strategy']}_{task['family']}_{task['fault']}_{task['fact_mode']}_s{task['seed']}.json"
        path=directory/name
        row=json.loads(path.read_text()) if path.exists() else {
            "status":"missing_result","strategy":task["strategy"],
            "private_configuration":{k:task[k] for k in ("seed","family","fault","fact_mode")}|{"retail_price":price}}
        if key(row)!=tuple(task[k] for k in ("seed","family","fault","fact_mode"))+(price,task["strategy"]):
            raise ValueError("result disagrees with declared task: "+name)
        rows.append(row)
    return rows


def mean(values):return statistics.mean(values) if values else None


def audit(row):
    if row["status"]!="finished":return {"status":"not_finished","issues":[]}
    issues=[];events=row["events"];experiments={}
    freeze=[i for i,e in enumerate(events) if e["request"]["tool"]=="finish"]
    deployment=[i for i,e in enumerate(events) if e["request"]["tool"]=="deployment_catalog"]
    if len(freeze)!=1 or len(deployment)!=1 or freeze[0]>=deployment[0]:issues.append("deployment not after exactly one freeze")
    if row["deployed_model"]["expression"]!=row["frozen_final"]["model"]["expression"]:issues.append("deployment changed relation")
    catalogs={"source":row["legal_input"]["catalog"]}
    for e in events:
        if e["request"]["tool"]=="open_transfer":catalogs["adaptation"]=e["response"]["catalog"]
        if e["request"]["tool"]=="experiment":
            r=e["response"];experiments[r["experiment_id"]]=e
            if e["request"]["args"]["stage"]=="heldout":issues.append("queried deployment outcomes")
    rounds={v["round"]:v for v in row["research_versions"] if v["phase"]=="confirmation_model_frozen"}
    check_ids=lambda c:c.get("experiment_ids",[c["experiment_id"]])
    final_round=max(rounds)
    final_ids={eid for c in row["confirmations"] if c["round"]==final_round for eid in check_ids(c)}
    cohorts=row.get("confirmation_protocol",{}).get("cohorts_per_check",1)
    max_checks=row.get("confirmation_protocol",{}).get("max_checks",4)
    revision_limit=row.get("workflow_policy",{}).get("max_revisions",len(rounds)-1)
    revision_count=0
    expected_training=set(rounds[0]["training_evidence_ids"]);seen_checks=set();released=set()
    for index,version in sorted(rounds.items()):
        checks=[c for c in row["confirmations"] if c["round"]==index]
        ids={eid for c in checks for eid in check_ids(c)}
        if len(checks)!=2 or len(ids)!=2*cohorts or ids&seen_checks:issues.append("wrong fresh-check counts")
        if set(version["training_evidence_ids"])!=expected_training:issues.append("training version changed without a release")
        seen_checks|=ids
        if index<final_round and revision_count<revision_limit and any(c["state"]=="contradicted" for c in checks):
            revision_count+=1
            released=seen_checks.copy();expected_training|=released
    if released!=set(row.get("released_confirmation_ids",[])):issues.append("revision release rule violated")
    if bool(released)!=bool(row.get("revision_after_confirmation")):issues.append("revision flag disagrees with releases")
    if len(row.get("revision_events",[]))>revision_limit:issues.append("revision policy exceeded")
    for check in row["confirmations"]:
        version=rounds[check["round"]];eid=check["experiment_id"]
        if eid in version["training_evidence_ids"] or any(i>=eid for i in version["training_evidence_ids"]):
            issues.append("confirmation entered its own training version")
        action=experiments[eid]["request"]["args"]
        prediction=predict(version["model"],catalogs[action["stage"]],action["assortment"],tuple(map(int,action["site"])))
        if abs(prediction-action["prediction"])>1e-10 or abs(prediction-check["frozen_prediction"])>1e-10:
            issues.append("check disagrees with frozen model")
        counts=[]
        for eid in check_ids(check):
            e=experiments[eid];a=e["request"]["args"]
            if a!=action:issues.append("pooled check changed its design")
            counts.append(e["response"])
        if sum(c["observed_sales"] for c in counts)!=check["count"] or sum(c["n"] for c in counts)!=check["n"]:
            issues.append("pooled confirmation counts disagree")
        expected=assess(check["count"],check["n"],check["frozen_prediction"],max_checks=max_checks)
        if expected["state"]!=check["state"] or abs(check["per_check_alpha"]-expected["per_check_alpha"])>1e-12:
            issues.append("confirmation rule disagrees with declared look budget")
    trained=set(rounds[final_round]["training_evidence_ids"])
    if trained&final_ids:issues.append("final confirmation reused for fit")
    for call in row["model_calls"]:
        # Model requests contain legal views only, never result metadata.
        for message in call["request"]["messages"]:
            content=message.get("content","")
            if any(name in content for name in ("private_score","private_configuration","class_probabilities","oracle_private")):
                issues.append("private metadata in model request")
    for profile in row["private_score"]["profiles"]:
        for day in profile["daily_trajectories"]:
            for name in ("policy","oracle"):
                r=day[name]
                if r["opening"]!=r["sales"]+r["ending"] or r["demand"]!=r["sales"]+r["lost_sales"]:
                    issues.append("inventory conservation violated")
    return {"status":"passed" if not issues else "failed","issues":sorted(set(issues)),
        "fixture_physical_facts_post_hoc":physical_fact_audit(ChoiceWorld(**row["private_configuration"]),row["deployed_model"])}


def report(rows):
    groups=defaultdict(list)
    for row in rows:
        c=row["private_configuration"];groups[(c["family"],c["fault"],c["fact_mode"],c.get("retail_price",8.),row["strategy"])].append(row)
    summaries=[]
    for (family,fault,mode,price,strategy),group in sorted(groups.items()):
        done=[r for r in group if r["status"]=="finished"]
        summaries.append({"family":family,"fault":fault,"fact_mode":mode,"retail_price":price,"strategy":strategy,
            "total_in_denominator":len(group),"status_counts":dict(Counter(r["status"] for r in group)),
            "finished":len(done),"finished_and_effect_rmse_at_most_5pp":sum(r["private_score"]["heldout_effect_rmse"]<=.05 for r in done),
            "mean_endpoints_conditional_on_finished":{k:mean([r["private_score"][k] for r in done]) for k in ENDPOINTS},
            "mean_sessions_conditional_on_finished":mean([r["used"]["sessions"] for r in done]),
            "mean_cost_conditional_on_finished":mean([r["used"]["cost"] for r in done]),
            "confirmation_states":dict(Counter(c["state"] for r in done for c in r["confirmations"])),
            "confirmation_revisions":sum(bool(r.get("revision_after_confirmation")) for r in done),
            "final_confirmation_scope_unresolved":sum(r["frozen_final"]["unresolved"] for r in done),
            "mechanism_card_states":dict(Counter(r.get("mechanism_card",{}).get("state","legacy_without_card") for r in done))})
    pairs=[];strategies=sorted({r["strategy"] for r in rows});indexed={key(r):r for r in rows}
    tasks=sorted({key(r)[:-1] for r in rows})
    for a,b in itertools.combinations(strategies,2):
        grouped=defaultdict(list)
        for task in tasks:
            ra=indexed.get(task+(a,));rb=indexed.get(task+(b,))
            if ra is None and rb is None:continue
            grouped[task[1:]].append((task[0],ra,rb))
        for (family,fault,mode,price),group in grouped.items():
            done=[(s,ra,rb) for s,ra,rb in group if ra and rb and ra["status"]==rb["status"]=="finished"]
            for endpoint in ENDPOINTS:
                differences=[{ "seed":s,"a_minus_b":ra["private_score"][endpoint]-rb["private_score"][endpoint]} for s,ra,rb in done]
                pairs.append({"family":family,"fault":fault,"fact_mode":mode,"retail_price":price,"method_a":a,"method_b":b,
                    "endpoint":endpoint,"planned_pairs":len(group),"completed_pairs":len(done),
                    "missing_or_failed_pairs":len(group)-len(done),"mean_a_minus_b":mean([r["a_minus_b"] for r in differences]),
                    "individual_differences":differences,
                    "inference":"少量开发种子仅作描述；不以这些样本的重抽样区间声称显著或等效。"})
    usage=Counter()
    for row in rows:
        for k,v in row.get("model_usage",{}).items():usage[k]+=v
    return {"phase":"development_not_blind_test","total_in_denominator":len(rows),"summary":summaries,
        "paired_endpoints":pairs,"model_usage":dict(usage),"boundary_audits":[{"task":list(key(r)),**audit(r)} for r in rows],
        "denominator_note":"失败和未生成结果保留；误差、收益均值以完成为条件，不作零损失填补。"}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directory",type=Path)
    args=parser.parse_args();summary=report(read_runs(args.directory))
    (args.directory/"analysis.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"tasks":summary["total_in_denominator"],"audit_counts":dict(Counter(a["status"] for a in summary["boundary_audits"]))}))
