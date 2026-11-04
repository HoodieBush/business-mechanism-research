"""Developer-only scientific workflow accounting, preserving prior raw phases."""
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

from audit_scientific import summarize
from challenge_scientific_audit import challenge
from model_protocol import usage_summary

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1];SETUP=ROOT/"results/setup_deepseek_20261012"
PHASES=tuple(f"development_scientific_v{v:02d}_20261012" for v in range(1,5))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")


def main(through_version=4):
    phases_to_read=tuple(f"development_scientific_v{v:02d}_20261012" for v in range(1,through_version+1));tag=f"v{through_version:02d}"
    validation_path=SETUP/f"validation-scientific-{tag}.json"
    if not validation_path.exists():write(validation_path,{"status":"validation_in_progress"})
    prior=json.loads((SETUP/"controlled-development-ledger-temporal-v03.json").read_text())
    prior_validation=json.loads((SETUP/"validation-temporal-v03.json").read_text())
    runs=[];analyses=[];manifests=[];hashes={};latent=set();contexts=set();seeds=set();missing_runs=[]
    for phase in phases_to_read:
        directory=ROOT/"results"/phase;analysis=summarize(directory);analyses.append(analysis)
        manifest=json.loads((directory/"manifest.json").read_text());manifests.append(manifest)
        for task in manifest["planned_tasks"]:
            p=directory/f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json"
            latent.add((task["seed"],task["family"],"none"));contexts.add((task["seed"],task["family"],"none",manifest["specification"]["price"]));seeds.add(task["seed"])
            if not p.exists():
                missing_runs.append({"phase":phase,"file":p.name,"task":task,"manifest_exit_code":manifest.get("exit_code"),"observed_phase_runs":manifest.get("observed_runs")});continue
            r=json.loads(p.read_text());runs.append(r);hashes[str(p.relative_to(PROJECT))]=sha(p)
    # These newly opened worlds have new seeds, so they do not duplicate prior
    # latent/context keys. No method/version/stream repeats become extra units.
    prior_seeds=set()
    for entry in json.loads((SETUP/"controlled-development-ledger-v09.json").read_text())["phases"]:
        m=json.loads((ROOT/"results"/entry["phase"]/"manifest.json").read_text());prior_seeds.update(t["seed"] for t in m["planned_tasks"])
    for entry in prior["temporal_phases"]:
        m=json.loads((ROOT/"results"/entry["phase"]/"manifest.json").read_text());prior_seeds.update(t["seed"] for t in m["planned_tasks"])
    if seeds&prior_seeds:raise ValueError("new-world accounting requires full key-union audit for overlapping seeds")
    usage=usage_summary([c for r in runs for c in r["model_calls"]]);base=prior["total_model_usage_with_prior_new_generator"]
    combined={k:base[k]+usage[k] for k in usage};counts=Counter(prior["status_counts"]);counts.update(r["status"] for r in runs)
    def measurements(r):
        return sorted((x["stage"],x["site"],tuple(x["assortment"]),x["n"],x["observed_sales"],x["evidence_version"]) for x in r["public_final_state"]["mature_evidence"])
    numeric_repeats=[]
    groups={}
    for r in runs:
        if r["strategy"].startswith("numeric_"):
            c=r["private_configuration"];key=(c["seed"],c["family"],c["profile"],c["price"],r["strategy"]);groups.setdefault(key,[]).append(r)
    for key,items in groups.items():
        numeric_repeats.append({"seed":key[0],"family":key[1],"profile":key[2],"price":key[3],"strategy":key[4],"phases":len(items),"same_received_measurements":all(measurements(x)==measurements(items[0]) for x in items),
            "same_frozen_model":all(x["frozen_final"]["model"]==items[0]["frozen_final"]["model"] for x in items)})
    ledger={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"prior_ledger":"controlled-development-ledger-temporal-v03.json",
        "prior_new_generator_records":prior["total_new_generator_records"],"scientific_run_records":len(runs),"total_new_generator_records":prior["total_new_generator_records"]+len(runs),
        "scientific_planned_runs":sum(m["expected_runs"] for m in manifests),"total_planned_new_generator_runs":prior["total_new_generator_records"]+sum(m["expected_runs"] for m in manifests),"missing_planned_runs":missing_runs,
        "status_counts":dict(counts),"scientific_status_counts":dict(Counter(r["status"] for r in runs)),
        "latent_parameter_groups":prior["latent_parameter_groups"]+len(latent),"price_world_conditions":prior["price_world_conditions"]+len(contexts),
        "seed_clusters":prior["seed_clusters"]+len(seeds),"new_scientific_seed_clusters":sorted(seeds),"scientific_underlying_parameter_worlds":len(latent),
        "scientific_phases":[{"phase":a["phase"],"planned_runs":a["planned_runs"],"audit_passed":sum(x["passed"] for x in a["records"]),"model_usage":a["model_usage"]} for a in analyses],
        "scientific_model_usage":usage,"total_model_usage_with_prior_new_generator":combined,"scientific_raw_sha256":hashes,
        "numeric_version_repeats":numeric_repeats,"retained_historical_scope_issues":prior["retained_historical_scope_issues"],
        "shared_numeric_replays_separate":prior["shared_numeric_replays_separate"],"simulated_withdrawal_replays_separate":prior["simulated_withdrawal_replays_separate"],
        "legacy_usage_ledger_separate":prior["legacy_usage_ledger_separate"],
        "interpretation":"Opened development. All scientific actor budget/protocol stops and pre-run missing tasks retained; correct accounting is not successful discovery. Methods/versions share latent worlds. Same caps do not equal realized samples/full computing costs. One raw LLM conditional confirmation in v09 is not full autonomous discovery, formal validation or organization-effect evidence.",
        "not_established":["reliable complete LLM scientific workflow and refutation recovery","LLM autonomous scope recovery","multi-target/resumable coordinator","new ontology discovery","multi-period inventory","full-cost fairness","automatic workflow search","full same-capability A/B/C","formal structural holdout","LLM necessity"]}
    write(SETUP/f"controlled-development-ledger-scientific-{tag}.json",ledger)
    challenges=challenge(ROOT/"results"/phases_to_read[-1]);env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    tests=subprocess.run([sys.executable,"-m","unittest","discover"],cwd=ROOT,env=env,text=True,capture_output=True)
    log=tests.stdout+tests.stderr;(SETUP/f"unit-tests-scientific-{tag}.log").write_text(log);match=re.search(r"Ran (\d+) tests",log)
    diff=subprocess.run(["git","diff","--check"],cwd=PROJECT,text=True,capture_output=True)
    listed=subprocess.run(["rg","--files","--hidden","--no-ignore","-g","!.git/**"],cwd=PROJECT,text=True,capture_output=True,check=True).stdout.splitlines()
    credential=Path.home()/".config/leicheng-project/api_key";key=credential.read_bytes().strip()
    hits=[name for name in listed if (PROJECT/name).is_file() and key and key in (PROJECT/name).read_bytes()]
    snapshots=[]
    phases=[x["phase"] for x in prior_validation["snapshots"]]+list(phases_to_read)
    for phase in phases:
        m=json.loads((ROOT/"results"/phase/"manifest.json").read_text());p=PROJECT/m["snapshot"]
        snapshots.append({"phase":phase,"creation_timing":m["creation_timing"],"hash_mismatches":[rel for rel,expected in m["source_sha256"].items() if not (p/rel).is_file() or sha(p/rel)!=expected],"exit_code":m.get("exit_code")})
    docs=[PROJECT/"AGENTS.md",ROOT/"README.md"]+list((PROJECT/"documents/库存机制发现Agent框架研究").glob("*.md"));links=0;missing=[]
    for p in docs:
        for target in re.findall(r"\]\(([^)]+)\)",p.read_text()):
            target=target.strip().strip("<>")
            if "://" in target or target.startswith(("#","mailto:")):continue
            target=unquote(target.split("#",1)[0]);links+=1
            if not (p.parent/target).exists():missing.append({"file":str(p.relative_to(PROJECT)),"target":target})
    provenance=json.loads((ROOT/"results/memory_archive/development_sources_v09_20261012.provenance.json").read_text())
    source_errors=[r["source_file"] for r in provenance["source_runs"] if sha(ROOT/r["source_file"])!=r["source_sha256"]]
    old_raw_errors=[name for name,expected in prior["temporal_raw_sha256"].items() if sha(PROJECT/name)!=expected]
    validation={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"unit_tests":{"tests":int(match[1]) if match else None,"exit_code":tests.returncode},
        "git_diff_check":{"exit_code":diff.returncode,"output":diff.stdout+diff.stderr},"credential_scan":{"scanned_files":len(listed),"hits":hits,
            "credential_mode":oct(credential.stat().st_mode&0o777),"parent_mode":oct(credential.parent.stat().st_mode&0o777),"outside_project":not credential.is_relative_to(PROJECT)},
        "snapshots":snapshots,"local_links":{"checked":links,"missing":missing},"memory_source_hash_mismatches":source_errors,"prior_temporal_raw_hash_mismatches":old_raw_errors,
        "scientific_audit_passed":sum(x["passed"] for a in analyses for x in a["records"]),"scientific_audit_total":sum(m["expected_runs"] for m in manifests),"scientific_actual_run_records":len(runs),"missing_planned_runs":missing_runs,"actor_stops_retained":sum(r["status"]=="actor_budget_stopped" for r in runs),
        "scientific_audit_challenge_types":len(challenges["challenges"]),"scientific_audit_challenges_all_caught":challenges["all_caught"],
        "retained_historical_scope_issues":prior["retained_historical_scope_issues"],"all_historical_runs_passed":not prior["retained_historical_scope_issues"] and not missing_runs,
        "source_sha256":{str(p.relative_to(PROJECT)):sha(p) for p in list(ROOT.glob("*.py"))+docs}}
    allowed_missing={x["phase"] for x in missing_runs if x["phase"]=="development_scientific_v06_20261012" and x["manifest_exit_code"]==1 and x["observed_phase_runs"]==0}
    validation["current_validation_passed"]=tests.returncode==diff.returncode==0 and not hits and not missing and not source_errors and not old_raw_errors and all(not x["hash_mismatches"] for x in snapshots) and all(x["passed"] or a["phase"] in allowed_missing and x["issues"]==["missing_planned_run"] for a in analyses for x in a["records"]) and all(x["passed"] for x in analyses[-1]["records"]) and challenges["all_caught"] and all(x["same_received_measurements"] and x["same_frozen_model"] for x in numeric_repeats)
    write(validation_path,validation)
    print(json.dumps({"records":ledger["total_new_generator_records"],"status_counts":ledger["status_counts"],"parameter_worlds":ledger["latent_parameter_groups"],"seeds":ledger["seed_clusters"],
        "scientific_audit_passed":validation["scientific_audit_passed"],"actor_stops":validation["actor_stops_retained"],"tests":validation["unit_tests"],"key_hits":len(hits),
        "snapshot_count":len(snapshots),"snapshot_mismatches":sum(len(x["hash_mismatches"]) for x in snapshots),"link_errors":missing,
        "scientific_usage":usage,"combined_usage":combined,"current_validation_passed":validation["current_validation_passed"]},ensure_ascii=False,indent=2))


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("--through-version",type=int,default=4,choices=range(4,10));args=ap.parse_args();main(args.through_version)
