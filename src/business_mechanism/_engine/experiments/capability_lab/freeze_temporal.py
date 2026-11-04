"""Prelaunch manifests for event-time treatments; never reuse old phase paths."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]


def launch(spec):
    if spec["runner"]!="run_temporal":raise ValueError("wrong runner")
    for name in ("seeds","families","profiles","strategies"):
        if not spec[name] or len(set(spec[name]))!=len(spec[name]):raise ValueError("empty or duplicate dimension")
    if not set(spec["strategies"])<={"numeric_serial","numeric_async","llm_async_coordinator"}:raise ValueError("invalid policy")
    if not set(spec["profiles"])<={"staggered","interruptions"}:raise ValueError("invalid public event mechanism")
    if not set(spec["families"])<={"source_joint","threeway","mixed_scope","null"}:raise ValueError("invalid private family")
    if type(spec["deadline"]) is not int or spec["deadline"]<1:raise ValueError("invalid deadline")
    expected_limits={"sessions":14400,"arms":24,"cost":276,"logical_time":spec["deadline"],"tool_calls":200,"api_calls":8,"api_tokens":60000}
    if spec.get("limits")!=expected_limits:raise ValueError("declared allocation differs from runner")
    if spec.get("confirmation")!={"rounds":3,"max_checks":6,"cohorts_per_check":2,"n_per_cohort":800,"total_alpha":.05,"tolerance":.05}:raise ValueError("declared analysis differs from runner")
    if "coordinator_api_allocation" in spec and spec["coordinator_api_allocation"]!={"common_warm":2,"adaptive_discovery":3,"confirmation":3}:raise ValueError("API allocation mismatch")
    phase=spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",phase):raise ValueError("invalid phase")
    output=ROOT/"results"/phase;snapshot=ROOT/"snapshots"/phase
    if output.exists() or snapshot.exists():raise ValueError("phase exists")
    tasks=[dict(seed=s,family=f,profile=p,strategy=m) for s in spec["seeds"] for f in spec["families"] for p in spec["profiles"] for m in spec["strategies"]]
    command=[sys.executable,str(ROOT/"run_temporal.py"),"--phase",phase,"--workers",str(spec.get("workers",1)),"--deadline",str(spec["deadline"])]
    for name in ("seeds","families","profiles","strategies"):command.extend(["--"+name,",".join(map(str,spec[name]))])
    files=list(ROOT.glob("*.py"))+[PROJECT/"configs/base_model.json",PROJECT/"environment.yml",PROJECT/"configs/conda-osx-arm64.lock.txt"]
    spec_file=PROJECT/"configs"/spec["specification_file"]
    if not spec_file.is_file() or json.loads(spec_file.read_text())!=spec:raise ValueError("specification file mismatch")
    files.append(spec_file)
    hashes={}
    for p in files:
        rel=p.relative_to(PROJECT);q=snapshot/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        hashes[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    manifest={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"creation_timing":"before_launch",
        "specification":spec,"planned_tasks":tasks,"expected_runs":len(tasks),"source_sha256":hashes,
        "command_argv":command,"snapshot":str(snapshot.relative_to(PROJECT)),"status":"prepared"}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    (snapshot/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    process=subprocess.run(command,cwd=ROOT,env=env,check=False)
    manifest.update(status="runner_exited",exit_code=process.returncode,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        observed_runs=sum((output/f"{t['strategy']}_{t['family']}_{t['profile']}_s{t['seed']}.json").exists() for t in tasks))
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return process.returncode
