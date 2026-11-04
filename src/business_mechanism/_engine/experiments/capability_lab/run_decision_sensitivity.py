"""Freeze all parent public-prefix reviews; no model call, sampling or scorer."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from audit_scientific import audit
from decision_sensitivity import CONTRACT,review
from public_inference_replay import extract

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path,value):
    with path.open("x") as handle:handle.write(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def launch(spec_path):
    spec_path=Path(spec_path).resolve();spec=json.loads(spec_path.read_text())
    if not spec_path.is_relative_to(PROJECT/"configs") or not re.fullmatch(r"[a-zA-Z0-9_-]+",spec["phase"]):raise ValueError("invalid stage")
    if spec["views"]!=["selected_fit","close_released"] or not spec["include_all_parent_tasks"]:raise ValueError("incomplete diagnostic matrix")
    if spec["new_model_api_calls"] or spec["new_sessions"] or spec["private_evaluation_for_selection"] or spec["live_actor_intervention"]:raise ValueError("offline public review only")
    for key in ("direction_families","interaction_order","logit_shifts","probability_shifts","training_prediction_tolerance"):
        if spec[key]!=CONTRACT[key]:raise ValueError("undeclared sensitivity contract")
    parent_dir=ROOT/"results"/spec["parent_phase"];parent_manifest=json.loads((parent_dir/"manifest.json").read_text())
    parents=[parent_dir/f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json" for task in parent_manifest["planned_tasks"]]
    tasks=[{"parent":str(path.relative_to(PROJECT)),"parent_sha256":sha(path),"view":mode} for path in parents for mode in spec["views"]]
    output=ROOT/"results"/spec["phase"];snapshot=ROOT/"snapshots"/spec["phase"]
    if output.exists() or snapshot.exists():raise ValueError("stage already exists")
    output.mkdir(parents=True);hashes={}
    for source in [*ROOT.glob("*.py"),spec_path,PROJECT/"environment.yml",PROJECT/"configs/conda-osx-arm64.lock.txt",parent_dir/"manifest.json",*parents]:
        relative=source.relative_to(PROJECT);destination=snapshot/relative
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination);hashes[str(relative)]=sha(source)
    manifest={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"creation_timing":"before_review",
        "specification":spec,"planned_tasks":tasks,"expected_reviews":len(tasks),"source_sha256":hashes,
        "snapshot":str(snapshot.relative_to(PROJECT)),"status":"prepared","new_independent_scientific_units":0}
    def save():(output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    save();write_new(snapshot/"manifest.json",manifest)
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    tests=subprocess.run([sys.executable,"-m","unittest","discover","-q"],cwd=ROOT,env=env,text=True,capture_output=True)
    write_new(output/"preflight-tests.json",{"exit_code":tests.returncode,"log":tests.stdout+tests.stderr})
    audits={path.name:audit(json.loads(path.read_text())) for path in parents};write_new(output/"parent-audits.json",audits)
    if tests.returncode or not all(value["passed"] for value in audits.values()):manifest["status"]="preflight_failed";save();return 1
    summaries=[]
    for task in tasks:
        start=time.monotonic();path=PROJECT/task["parent"]
        if sha(path)!=task["parent_sha256"]:raise ValueError("parent changed after freeze")
        run=json.loads(path.read_text());public=extract(run,task["view"]);name=path.stem+"__"+task["view"]
        rows=public["view"].verified_observations()
        write_new(output/(name+"__public-input.json"),{"catalogs":public["view"].catalogs,"measurements":[row for row,_ in rows],
            "model":public["selected_original_model"],"training_ids":public["training_ids"],"boundary_available_at":public["boundary_available_at"],
            "public_prefix_sha256":public["public_prefix_sha256"],"operating_contract":run["legal_input"]["operating_objective"]})
        summary={**task,"parent_strategy":run["strategy"],"training_ids":public["training_ids"]}
        try:
            result=review(public,run["legal_input"]["operating_objective"])
            write_new(output/(name+".json"),{**summary,"status":"finished","result":result})
            summary.update(status="finished",training_sessions=sum(row["n"] for row,_ in rows),
                directions=len(result["reviewed_decision_active_directions"]),constant_directions=len(result["training_constant_decision_active_directions"]),
                alias_directions=len(result["affine_alias_decision_active_directions"]),scenarios=len(result["scenarios"]),
                decision_inactive_directions=result["decision_inactive_directions"],unsupported_stresses=result["unsupported_stresses"],
                max_reviewed_scenario_regret=result["max_nominal_policy_regret_over_reviewed_scenarios"],designs=result["suggested_discriminating_designs"])
        except (ValueError,KeyError,TypeError) as error:
            summary.update(status="review_failure",error=type(error).__name__+": "+str(error));write_new(output/(name+".json"),summary)
        summary["elapsed_seconds"]=time.monotonic()-start;summaries.append(summary)
        print(json.dumps({key:summary.get(key) for key in ("parent_strategy","view","status","directions","scenarios","max_reviewed_scenario_regret","elapsed_seconds","error")}),flush=True)
    write_new(output/"analysis-decision-sensitivity.json",{"phase":spec["phase"],"records":summaries,
        "all_reviews_finished":all(row["status"]=="finished" for row in summaries),"new_model_api_calls":0,"new_sessions":0,"new_independent_scientific_units":0,
        "limitations":"Offline public diagnostics on original two development worlds. Finite stress loss is neither true-world regret nor a calibrated uncertainty bound; no actual Agent use or business gain established, no live execution preflight.","full_goal_completed":False})
    manifest.update(status="finished" if all(row["status"]=="finished" for row in summaries) else "review_failures",observed_reviews=len(summaries),completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat());save()
    return 0 if manifest["status"]=="finished" else 1


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("spec",type=Path)
    raise SystemExit(launch(parser.parse_args().spec))
