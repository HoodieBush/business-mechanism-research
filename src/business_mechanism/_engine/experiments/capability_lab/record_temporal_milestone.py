"""Reproducible developer-only accounting and acceptance; no Agent inputs."""
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

from audit_temporal import summarize
from compare_temporal_phases import compare,final_measurements,load
from model_protocol import usage_summary

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1];SETUP=ROOT/"results/setup_deepseek_20261012"
TEMPORAL_PHASES=("development_temporal_v01_20261012","development_temporal_deadline_v01_20261012",
    "development_temporal_coordinator_v01_20261012","development_temporal_coordinator_v02_20261012","development_temporal_scope_v03_20261012")


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def main():
    old=json.loads((SETUP/"controlled-development-ledger-v09.json").read_text());analyses=[];temporal=[];manifests=[];raw_hashes={}
    latent=set();contexts=set();seeds=set()
    for phase in old["phases"]:
        directory=ROOT/"results"/phase["phase"];manifest=json.loads((directory/"manifest.json").read_text());manifests.append(manifest)
        price=manifest["specification"].get("retail_price",8.)
        for t in manifest["planned_tasks"]:
            latent.add((t["seed"],t["family"],t["fault"]));contexts.add((t["seed"],t["family"],t["fault"],price));seeds.add(t["seed"])
    timing_conditions=set()
    for phase in TEMPORAL_PHASES:
        directory=ROOT/"results"/phase;a=summarize(directory);analyses.append(a)
        manifest=json.loads((directory/"manifest.json").read_text());manifests.append(manifest)
        for t in manifest["planned_tasks"]:
            p=directory/f"{t['strategy']}_{t['family']}_{t['profile']}_s{t['seed']}.json";r=json.loads(p.read_text());temporal.append(r)
            raw_hashes[str(p.relative_to(PROJECT))]=sha(p)
            latent.add((t["seed"],t["family"],"none"));contexts.add((t["seed"],t["family"],"none",8.));seeds.add(t["seed"])
            timing_conditions.add((t["seed"],t["family"],t["profile"],manifest["specification"]["deadline"]))
    temporal_usage=usage_summary([c for r in temporal for c in r["model_calls"]]);combined_usage={k:old["total_model_usage"][k]+temporal_usage[k] for k in temporal_usage}
    counts=Counter(old["status_counts"]);counts.update(r["status"] for r in temporal)
    issues=[{"phase":a["phase"],**r} for a in analyses for r in a["records"] if not r["passed"]]
    corrected=[]
    for seed in (3701,3702):
        for profile in ("staggered","interruptions"):
            for strategy in ("numeric_serial","numeric_async"):
                a=load("development_temporal_deadline_v01_20261012",seed,"mixed_scope",profile,strategy)
                b=load("development_temporal_scope_v03_20261012",seed,"mixed_scope",profile,strategy)
                corrected.append({"seed":seed,"profile":profile,"strategy":strategy,"same_received_measurements":final_measurements(a)==final_measurements(b),
                    "old_card_state":a["mechanism_card"]["state"],"new_card_state":b["mechanism_card"]["state"],"new_research_coverage":b["mechanism_card"]["research_coverage_state"]})
    write(SETUP/"temporal-scope-correction-v03.json",{"pairs":corrected,"interpretation":"Paired opened-world development correction; old raw summaries retained, no new independent evidence or accuracy gain claimed."})
    ledger={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"prior_ledger":"controlled-development-ledger-v09.json",
        "legacy_openworld_records":old["total_run_records"],"temporal_run_records":len(temporal),"total_new_generator_records":old["total_run_records"]+len(temporal),
        "status_counts":dict(counts),"latent_parameter_groups":len(latent),"price_world_conditions":len(contexts),"seed_clusters":len(seeds),
        "temporal_underlying_parameter_worlds":len({(r['private_configuration']['seed'],r['private_configuration']['family']) for r in temporal}),
        "temporal_event_conditions":len(timing_conditions),"temporal_event_condition_key":["seed","family","profile","deadline"],
        "temporal_phases":[{"phase":a["phase"],"planned_runs":a["planned_runs"],"audit_passed":sum(r["passed"] for r in a["records"]),
            "known_scope_issues":sum(not r["passed"] for r in a["records"]),"model_usage":a["model_usage"]} for a in analyses],
        "temporal_model_usage":temporal_usage,"total_model_usage_with_prior_new_generator":combined_usage,
        "retained_historical_scope_issues":issues,"new_scope_batch_all_passed":all(r["passed"] for r in analyses[-1]["records"]),
        "temporal_raw_sha256":raw_hashes,"shared_numeric_replays_separate":old["shared_inference_replay_separate"],
        "simulated_withdrawal_replays_separate":old["source_withdrawal_state_replay_separate"],"legacy_usage_ledger_separate":old["legacy_usage_ledger_separate"],
        "interpretation":"Development records, not independent tasks; different methods/versions/deadlines share latent worlds and design streams. Provider tokens are not billed currency. Two old scope-summary bugs are preserved and explicitly audited, not silently corrected in raw data.",
        "not_established":["full open scientific coordinator","autonomous memory scope recovery","multi-period inventory","full-cost fairness","automatic workflow search","full same-capability A/B/C","formal structural holdout","LLM necessity"]}
    write(SETUP/"controlled-development-ledger-temporal-v03.json",ledger)
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    tests=subprocess.run([sys.executable,"-m","unittest","discover"],cwd=ROOT,env=env,text=True,capture_output=True)
    log=tests.stdout+tests.stderr;(SETUP/"unit-tests-temporal-v03.log").write_text(log)
    match=re.search(r"Ran (\d+) tests",log)
    diff=subprocess.run(["git","diff","--check"],cwd=PROJECT,text=True,capture_output=True)
    listed=subprocess.run(["rg","--files","--hidden","--no-ignore","-g","!.git/**"],cwd=PROJECT,text=True,capture_output=True,check=True).stdout.splitlines()
    credential=Path.home()/".config/leicheng-project/api_key";key=credential.read_bytes().strip();hits=[]
    for name in listed:
        p=PROJECT/name
        if p.is_file() and key and key in p.read_bytes():hits.append(name)
    snapshots=[]
    for manifest in manifests:
        path=PROJECT/manifest["snapshot"]
        bad=[rel for rel,expected in manifest["source_sha256"].items() if not (path/rel).is_file() or sha(path/rel)!=expected]
        snapshots.append({"phase":manifest["specification"]["phase"],"creation_timing":manifest["creation_timing"],"hash_mismatches":bad,"exit_code":manifest.get("exit_code")})
    replay=json.loads((ROOT/"results/development_inference_replay_v06_20261012/manifest.json").read_text());path=PROJECT/replay["snapshot"]
    snapshots.append({"phase":replay["specification"]["phase"],"creation_timing":replay["creation_timing"],
        "hash_mismatches":[rel for rel,expected in replay["source_sha256"].items() if not (path/rel).is_file() or sha(path/rel)!=expected],"exit_code":replay.get("exit_code")})
    missing=[];links=0
    docs=[PROJECT/"AGENTS.md",ROOT/"README.md"]+list((PROJECT/"documents/库存机制发现Agent框架研究").glob("*.md"))
    for p in docs:
        for target in re.findall(r"\]\(([^)]+)\)",p.read_text()):
            target=target.strip().strip("<>")
            if "://" in target or target.startswith(("#","mailto:")):continue
            target=unquote(target.split("#",1)[0]);links+=1
            if not (p.parent/target).exists():missing.append({"file":str(p.relative_to(PROJECT)),"target":target})
    provenance=json.loads((ROOT/"results/memory_archive/development_sources_v09_20261012.provenance.json").read_text())
    bad_sources=[r["source_file"] for r in provenance["source_runs"] if sha(ROOT/r["source_file"])!=r["source_sha256"]]
    pairs=compare();write(SETUP/"temporal-paired-comparisons-v03.json",pairs)
    challenges=json.loads((SETUP/"temporal-audit-challenges-v03.json").read_text())
    validation={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"unit_tests":{"tests":int(match[1]) if match else None,"exit_code":tests.returncode},
        "git_diff_check":{"exit_code":diff.returncode,"output":diff.stdout+diff.stderr},
        "credential_scan":{"scanned_files":len(listed),"hits":hits,"credential_mode":oct(credential.stat().st_mode&0o777),"parent_mode":oct(credential.parent.stat().st_mode&0o777),"outside_project":not credential.is_relative_to(PROJECT)},
        "snapshots":snapshots,"local_links":{"checked":links,"missing":missing},"memory_source_hash_mismatches":bad_sources,
        "temporal_audit_passed":sum(r["passed"] for a in analyses for r in a["records"]),"retained_historical_scope_issues":issues,
        "new_scope_batch_all_passed":ledger["new_scope_batch_all_passed"],"deadline_prefixes_all_passed":pairs["all_prefix_checks_passed"],
        "scope_correction_shared_measurements":all(r["same_received_measurements"] for r in corrected),
        "audit_challenge_types":len(challenges["checks"]),"audit_challenges_all_caught":challenges["all_caught"],"all_historical_runs_passed":not issues,
        "source_sha256":{str(p.relative_to(PROJECT)):sha(p) for p in list(ROOT.glob("*.py"))+docs}}
    validation["current_validation_passed"]=tests.returncode==diff.returncode==0 and not hits and not missing and not bad_sources and all(not x["hash_mismatches"] for x in snapshots) and ledger["new_scope_batch_all_passed"] and pairs["all_prefix_checks_passed"] and validation["scope_correction_shared_measurements"] and challenges["all_caught"]
    write(SETUP/"validation-temporal-v03.json",validation)
    print(json.dumps({"records":ledger["total_new_generator_records"],"status_counts":ledger["status_counts"],"parameter_worlds":len(latent),"seeds":len(seeds),
        "temporal_audit_passed":validation["temporal_audit_passed"],"historical_issues":len(issues),"tests":validation["unit_tests"],
        "scan_files":len(listed),"key_hits":len(hits),"snapshots":len(snapshots),"snapshot_errors":sum(len(x["hash_mismatches"]) for x in snapshots),
        "link_errors":missing,"api_usage":combined_usage,"current_validation_passed":validation["current_validation_passed"]},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
