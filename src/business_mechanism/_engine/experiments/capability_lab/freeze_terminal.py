"""Prelaunch freeze and regression gate for zero-API terminal-policy fixtures."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[1]


def launch(spec_file):
    spec_file=Path(spec_file).resolve();spec=json.loads(spec_file.read_text())
    if not spec_file.is_relative_to(PROJECT/"configs") or spec["runner"]!="run_terminal":raise ValueError("invalid specification")
    if spec["terminal_policies"]!=["received_only","settle_committed"] or spec["api_calls"]!=0 or spec["decision_stop"]!="after_one_registered_confirmation":raise ValueError("fixture policy contract mismatch")
    for key in ("seeds","families","profiles","deadlines"):
        if not spec[key] or len(set(spec[key]))!=len(spec[key]):raise ValueError("empty/duplicate task dimension")
    if not set(spec["families"])<={"threeway","mixed_scope","source_joint","null"} or not set(spec["profiles"])<={"staggered","interruptions"} or any(type(d) is not int or d<8 for d in spec["deadlines"]):raise ValueError("invalid task")
    phase=spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",phase):raise ValueError("invalid phase")
    out=ROOT/"results"/phase;snapshot=ROOT/"snapshots"/phase
    if out.exists() or snapshot.exists():raise ValueError("phase exists")
    tasks=[dict(seed=s,family=f,profile=p,deadline=d,terminal_policy=t) for s in spec["seeds"] for f in spec["families"] for p in spec["profiles"] for d in spec["deadlines"] for t in spec["terminal_policies"]]
    hashes={}
    for source in list(ROOT.glob("*.py"))+[spec_file,PROJECT/"configs/base_model.json",PROJECT/"environment.yml",PROJECT/"configs/conda-osx-arm64.lock.txt"]:
        rel=source.relative_to(PROJECT);dest=snapshot/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest);hashes[str(rel)]=hashlib.sha256(source.read_bytes()).hexdigest()
    out.mkdir(parents=True)
    manifest={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"creation_timing":"before_launch","specification":spec,"planned_tasks":tasks,"expected_runs":len(tasks),
        "snapshot":str(snapshot.relative_to(PROJECT)),"source_sha256":hashes,"status":"prepared"}
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");(snapshot/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    try:
        for p in ROOT.glob("*.py"):compile(p.read_text(),str(p),"exec")
    except SyntaxError as error:
        manifest.update(status="preflight_failed",exit_code=1,error=str(error));(out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");return 1
    checks=subprocess.run([sys.executable,"-m","unittest","discover","-q"],cwd=ROOT,env=env,text=True,capture_output=True)
    (out/"preflight-tests.log").write_text(checks.stdout+checks.stderr);manifest["preflight_exit_code"]=checks.returncode
    if checks.returncode:
        manifest.update(status="preflight_failed",exit_code=checks.returncode);(out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");return checks.returncode
    process=subprocess.run([sys.executable,str(ROOT/"run_terminal.py"),"--spec",str(spec_file)],cwd=ROOT,env=env)
    manifest.update(status="runner_exited",exit_code=process.returncode,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    from run_terminal import filename
    manifest["observed_runs"]=sum((out/filename(task)).exists() for task in tasks)
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n");return process.returncode


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("spec",type=Path);args=ap.parse_args();raise SystemExit(launch(args.spec))
