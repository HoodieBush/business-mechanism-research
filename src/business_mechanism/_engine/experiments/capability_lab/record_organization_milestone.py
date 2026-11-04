"""Separate engineering trace validity from actual B/C organization acceptance."""
from collections import Counter
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

from audit_organization import analyze
from model_protocol import usage_summary
from record_public_evidence_milestone import ROOT,PROJECT,SETUP,sha,write
from run_organization import filename

PHASE="development_organization_v01_20261012"


def main():
    prior=json.loads((SETUP/"controlled-development-ledger-public-evidence-v01.json").read_text())
    old=json.loads((SETUP/"validation-public-evidence-v01.json").read_text())
    directory=ROOT/"results"/PHASE;manifest=json.loads((directory/"manifest.json").read_text());analysis=analyze(directory)
    paths=[directory/filename(t) for t in manifest["planned_tasks"]];runs=[json.loads(p.read_text()) for p in paths if p.exists()]
    usage=usage_summary([r for d in runs for r in d["model_calls"]]);counts=Counter(prior["status_counts"]);counts.update(d["status"] for d in runs)
    groups={(t["seed"],t["family"]) for t in manifest["planned_tasks"]};seeds={t["seed"] for t in manifest["planned_tasks"]}
    ledger={**prior,"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"prior_ledger":"controlled-development-ledger-public-evidence-v01.json",
        "organization_pilot_phase":PHASE,"organization_pilot_records":len(runs),"organization_pilot_model_usage":usage,
        "organization_pilot_raw_sha256":{str(p.relative_to(PROJECT)):sha(p) for p in paths if p.exists()},
        "total_new_generator_records":prior["total_new_generator_records"]+len(runs),"total_planned_new_generator_runs":prior["total_planned_new_generator_runs"]+manifest["expected_runs"],
        "status_counts":dict(counts),"latent_parameter_groups":prior["latent_parameter_groups"]+len(groups),"price_world_conditions":prior["price_world_conditions"]+len(groups),"seed_clusters":prior["seed_clusters"]+len(seeds),
        "total_model_usage_with_prior_new_generator":{k:v+usage[k] for k,v in prior["total_model_usage_with_prior_new_generator"].items()},
        "organization_interpretation":"First autonomous-entry development pilot. Six LLM tasks stop; B never queries reviewer, C never expands child. Valid traces do not certify complete ABC behavior or superiority. One seed/two worlds, actual samples unequal; no formal effect/power/holdout conclusion."}
    write(SETUP/"controlled-development-ledger-organization-v01.json",ledger)
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    tests=subprocess.run([sys.executable,"-m","unittest","discover","-q"],cwd=ROOT,env=env,text=True,capture_output=True);log=tests.stdout+tests.stderr
    (SETUP/"unit-tests-organization-v01.log").write_text(log);match=re.search(r"Ran (\d+) tests",log)
    diff=subprocess.run(["git","diff","--check"],cwd=PROJECT,text=True,capture_output=True)
    files=subprocess.run(["rg","--files","--hidden","--no-ignore","-g","!.git/**"],cwd=PROJECT,text=True,capture_output=True,check=True).stdout.splitlines()
    credential=Path.home()/".config/leicheng-project/api_key";key=credential.read_bytes().strip()
    hits=[p for p in files if (PROJECT/p).is_file() and key and key in (PROJECT/p).read_bytes()]
    snapshots=[]
    for phase in [s["phase"] for s in old["snapshots"]]+[PHASE]:
        saved=json.loads((ROOT/"results"/phase/"manifest.json").read_text());s=PROJECT/saved["snapshot"]
        snapshots.append({"phase":phase,"hash_mismatches":[p for p,h in saved["source_sha256"].items() if not (s/p).exists() or sha(s/p)!=h],"exit_code":saved.get("exit_code")})
    temporal=json.loads((SETUP/"controlled-development-ledger-temporal-v03.json").read_text())
    hashes={**prior["scientific_raw_sha256"],**prior["terminal_fixture_raw_sha256"],**prior["recovery_challenge_raw_sha256"],**temporal["temporal_raw_sha256"]}
    raw_errors=[p for p,h in hashes.items() if not (PROJECT/p).exists() or sha(PROJECT/p)!=h]
    docs=[PROJECT/"AGENTS.md",ROOT/"README.md"]+list((PROJECT/"documents/库存机制发现Agent框架研究").glob("*.md"));missing=[];links=0
    for path in docs:
        for target in re.findall(r"\]\(([^)]+)\)",path.read_text()):
            target=target.strip().strip("<>")
            if "://" in target or target.startswith(("#","mailto:")):continue
            links+=1
            if not (path.parent/unquote(target.split("#",1)[0])).exists():missing.append({"file":str(path.relative_to(PROJECT)),"target":target})
    validation={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"unit_tests":{"tests":int(match[1]) if match else None,"exit_code":tests.returncode},
        "git_diff_check":{"exit_code":diff.returncode,"output":diff.stdout+diff.stderr},"credential_scan":{"files":len(files),"hits":hits,"mode":oct(credential.stat().st_mode&0o777),"parent_mode":oct(credential.parent.stat().st_mode&0o777),"outside_project":not credential.is_relative_to(PROJECT)},
        "snapshots":snapshots,"prior_raw_hash_mismatches":raw_errors,"local_links":{"checked":links,"missing":missing},
        "organization_trace_audit_passed":sum(r["passed"] for r in analysis["records"]),"all_organization_traces_valid":analysis["all_trace_audits_passed"],
        "organization_behavior_acceptance_passed":analysis["all_BC_behavior_exercised"],"formal_ABC_completed":False,"full_goal_completed":False,
        "initial_json_key_audit_failure_preserved":"analysis-initial-json-key-failure.json","planned_missing_current_runs":[p.name for p in paths if not p.exists()],
        "retained_missing_planned_runs":prior["missing_planned_runs"],"retained_historical_scope_issues":prior["retained_historical_scope_issues"],"all_historical_runs_passed":False,
        "source_sha256":{str(p.relative_to(PROJECT)):sha(p) for p in list(ROOT.glob("*.py"))+docs}}
    validation["current_engineering_validation_passed"]=tests.returncode==diff.returncode==0 and not hits and not raw_errors and not missing and not validation["planned_missing_current_runs"] and not any(s["hash_mismatches"] for s in snapshots) and analysis["all_trace_audits_passed"]
    write(SETUP/"validation-organization-v01.json",validation)
    print(json.dumps({"records":ledger["total_new_generator_records"],"planned":ledger["total_planned_new_generator_runs"],"seeds":ledger["seed_clusters"],"worlds":ledger["latent_parameter_groups"],
        "tests":validation["unit_tests"],"audited":validation["organization_trace_audit_passed"],"snapshots":len(snapshots),"key_hits":len(hits),"new_usage":usage,
        "engineering_passed":validation["current_engineering_validation_passed"],"BC_behavior_passed":validation["organization_behavior_acceptance_passed"]},ensure_ascii=False))


if __name__=="__main__":main()
