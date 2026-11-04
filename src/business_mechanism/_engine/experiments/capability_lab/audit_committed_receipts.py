"""Acceptance for matched simulator continuations; no policy/API inputs."""
import hashlib
import json
from pathlib import Path

from confirmation import assess
from temporal_lab import digest

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1]


def audit(directory):
    directory=Path(directory);manifest=json.loads((directory/"manifest.json").read_text());reports=[]
    snapshot=PROJECT/manifest["snapshot"]
    mismatches=[p for p,h in manifest["source_sha256"].items() if hashlib.sha256((snapshot/p).read_bytes()).hexdigest()!=h]
    original_snapshot=PROJECT/manifest["source_snapshot"]
    source_mismatches=[p for p,h in manifest["source_snapshot_sha256"].items() if hashlib.sha256((original_snapshot/p).read_bytes()).hexdigest()!=h]
    for task in manifest["planned_tasks"]:
        name=f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json";p=directory/name;issues=[]
        if not p.exists():reports.append({"file":name,"passed":False,"issues":["missing"]});continue
        r=json.loads(p.read_text());original=json.loads(Path(r["source_file"]).read_text())
        if not r["prefix_matched"] or r["issues"] or not r["registry_unchanged"] or r["api_calls"]!=0:issues.append("prefix_model_or_api_contract")
        if r["frozen_model_sha256"]!=digest(original["frozen_final"]["model"]):issues.append("original_frozen_model_changed")
        if r["before"]["registered_checks"]!=r["after"]["registered_checks"] or r["after"]["registered_checks"]!=len(original["research"]["checks"]):issues.append("check_added_or_removed")
        for key,value in r["after"]["used"].items():
            if value>original["legal_input"]["limits"][key] or value<r["before"]["used"][key]:issues.append("shared_budget")
        forbidden={"public_pool_fitted","candidate_registered","check_frozen_before_execution","confirmation_evidence_released"}
        # Events beyond the original recorded action prefix may only receive,
        # verify and assess existing plans, followed by the same model finish.
        # Explicit unchanged registry/check/model checks above cover the full
        # continuation; event-kind counts cover allocation/revision side paths.
        for kind in forbidden:
            if sum(e["kind"]==kind for e in r["public_research_events"])!=sum(e["kind"]==kind for e in original["research"]["events"]):issues.append("new_scientific_version_or_revision")
        for c in r["completed_check_results"]:
            expected=assess(sum(x["observed_sales"] for x in c["cohort_results"]),1600,c["frozen_prediction"],max_checks=6)
            if any(c[k]!=v for k,v in expected.items()) or len(c["experiment_ids"])!=2 or not all(x["verified_meter"] and x["verified_supply"] for x in c["cohort_results"]):issues.append("confirmation_recompute")
        reports.append({"file":name,"passed":not issues,"issues":sorted(set(issues)),"before":r["before"],"after":r["after"],"original_card":r["original_card_state"],"replay_card":r["replay_card_state"]})
    result={"phase":manifest["phase"],"records":reports,"snapshot_mismatches":mismatches,"original_snapshot_mismatches":source_mismatches,
        "all_passed":not mismatches and not source_mismatches and all(r["passed"] for r in reports),"api_calls":0,"independent_units_added":0,
        "interpretation":"Matched post-development mechanical continuation of four recorded LLM paths; version/plan/registry/cost and exact CP acceptance, not new independent experiments or Agent performance."}
    (directory/"analysis.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");return result


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);args=ap.parse_args();r=audit(args.directory)
    print(json.dumps({"all_passed":r["all_passed"],"records":r["records"],"snapshot_errors":r["snapshot_mismatches"]+r["original_snapshot_mismatches"]},ensure_ascii=False,indent=2))
