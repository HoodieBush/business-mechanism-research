"""Developer-only terminal fixture ledger and regression/privacy acceptance."""
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

from audit_terminal import analyze
from run_terminal import filename

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1];SETUP=ROOT/"results/setup_deepseek_20261012"
PHASE="development_terminal_v01_20261012"


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n")


def main():
    validation_path=SETUP/"validation-terminal-v01.json"
    if not validation_path.exists():write(validation_path,{"status":"in_progress"})
    prior=json.loads((SETUP/"controlled-development-ledger-scientific-v09.json").read_text());oldv=json.loads((SETUP/"validation-scientific-v09.json").read_text())
    directory=ROOT/"results"/PHASE;manifest=json.loads((directory/"manifest.json").read_text());analysis=analyze(directory)
    runs=[json.loads((directory/filename(t)).read_text()) for t in manifest["planned_tasks"]]
    checks=json.loads((directory/"audit-challenges.json").read_text());counts=Counter(prior["status_counts"]);counts.update(r["status"] for r in runs)
    groups={(t["seed"],t["family"]) for t in manifest["planned_tasks"]};seeds={t["seed"] for t in manifest["planned_tasks"]}
    ledger={**prior,"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"prior_ledger":"controlled-development-ledger-scientific-v09.json",
        "terminal_fixture_records":len(runs),"total_new_generator_records":prior["total_new_generator_records"]+len(runs),"total_planned_new_generator_runs":prior["total_planned_new_generator_runs"]+manifest["expected_runs"],
        "status_counts":dict(counts),"latent_parameter_groups":prior["latent_parameter_groups"]+len(groups),"price_world_conditions":prior["price_world_conditions"]+len(groups),"seed_clusters":prior["seed_clusters"]+len(seeds),
        "terminal_fixture_phase":PHASE,"terminal_fixture_raw_sha256":{str((directory/filename(t)).relative_to(PROJECT)):sha(directory/filename(t)) for t in manifest["planned_tasks"]},
        "terminal_underlying_parameter_worlds":len(groups),"terminal_paired_conditions":len(analysis["pairs"]),"terminal_api_calls":0,
        "terminal_interpretation":"Deterministic execution fixtures separate from LLM performance; one confirmation planned per task, same within-condition action prefix/model/score. Sixteen newly received conditions refute unchanged predictions; this is evidence completion, not model improvement. Profiles/deadlines/policies are correlated repeats."}
    write(SETUP/"controlled-development-ledger-terminal-v01.json",ledger)
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    tests=subprocess.run([sys.executable,"-m","unittest","discover","-q"],cwd=ROOT,env=env,text=True,capture_output=True);log=tests.stdout+tests.stderr
    (SETUP/"unit-tests-terminal-v01.log").write_text(log);match=re.search(r"Ran (\d+) tests",log)
    diff=subprocess.run(["git","diff","--check"],cwd=PROJECT,text=True,capture_output=True)
    files=subprocess.run(["rg","--files","--hidden","--no-ignore","-g","!.git/**"],cwd=PROJECT,text=True,capture_output=True,check=True).stdout.splitlines()
    credential=Path.home()/".config/leicheng-project/api_key";key=credential.read_bytes().strip()
    hits=[name for name in files if (PROJECT/name).is_file() and key and key in (PROJECT/name).read_bytes()]
    snapshots=[]
    phases=[r["phase"] for r in oldv["snapshots"]]+[oldv["committed_receipts_replay"]["phase"],PHASE]
    for phase in phases:
        m=json.loads((ROOT/"results"/phase/"manifest.json").read_text());s=PROJECT/m["snapshot"]
        snapshots.append({"phase":phase,"hash_mismatches":[p for p,h in m["source_sha256"].items() if not (s/p).exists() or sha(s/p)!=h],"exit_code":m.get("exit_code")})
    old_errors=[p for p,h in {**prior["scientific_raw_sha256"]}.items() if sha(PROJECT/p)!=h]
    temporal=json.loads((SETUP/"controlled-development-ledger-temporal-v03.json").read_text())
    old_errors.extend(p for p,h in temporal["temporal_raw_sha256"].items() if sha(PROJECT/p)!=h)
    docs=[PROJECT/"AGENTS.md",ROOT/"README.md"]+list((PROJECT/"documents/库存机制发现Agent框架研究").glob("*.md"));missing=[];links=0
    for p in docs:
        for target in re.findall(r"\]\(([^)]+)\)",p.read_text()):
            target=target.strip().strip("<>")
            if "://" in target or target.startswith(("#","mailto:")):continue
            links+=1;t=unquote(target.split("#",1)[0])
            if not (p.parent/t).exists():missing.append({"file":str(p.relative_to(PROJECT)),"target":target})
    validation={"checked_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"unit_tests":{"tests":int(match[1]) if match else None,"exit_code":tests.returncode},"git_diff_check":{"exit_code":diff.returncode,"output":diff.stdout+diff.stderr},
        "credential_scan":{"files":len(files),"hits":hits,"mode":oct(credential.stat().st_mode&0o777),"parent_mode":oct(credential.parent.stat().st_mode&0o777),"outside_project":not credential.is_relative_to(PROJECT)},
        "snapshots":snapshots,"prior_raw_hash_mismatches":old_errors,"local_links":{"checked":links,"missing":missing},"terminal_audit_passed":sum(x["passed"] for x in analysis["records"]),
        "terminal_pairs_passed":analysis["all_passed"],"terminal_challenge_types":len(checks["challenges"]),"terminal_challenges_all_caught":checks["all_caught"],
        "retained_missing_planned_runs":prior["missing_planned_runs"],"retained_historical_scope_issues":prior["retained_historical_scope_issues"],"all_historical_runs_passed":False,
        "source_sha256":{str(p.relative_to(PROJECT)):sha(p) for p in list(ROOT.glob("*.py"))+docs}}
    validation["current_validation_passed"]=tests.returncode==diff.returncode==0 and not hits and not old_errors and not missing and not any(s["hash_mismatches"] for s in snapshots) and analysis["all_passed"] and checks["all_caught"]
    write(validation_path,validation)
    print(json.dumps({"records":ledger["total_new_generator_records"],"planned":ledger["total_planned_new_generator_runs"],"worlds":ledger["latent_parameter_groups"],"seeds":ledger["seed_clusters"],"tests":validation["unit_tests"],"terminal_audit_passed":validation["terminal_audit_passed"],"snapshot_count":len(snapshots),"key_hits":len(hits),"link_errors":missing,"current_validation_passed":validation["current_validation_passed"]},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
