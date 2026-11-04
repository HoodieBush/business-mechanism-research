"""Snapshot a declared task matrix before launching it, without shell execution."""
from __future__ import annotations

import argparse
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


def launch(spec_path):
    spec=json.loads(Path(spec_path).read_text())
    runner=spec["runner"]
    if runner=="run_scientific":
        from freeze_scientific import launch as launch_scientific
        return launch_scientific(spec)
    if runner=="run_temporal":
        from freeze_temporal import launch as launch_temporal
        return launch_temporal(spec)
    if runner not in {"run_hybrid","run_research","run_openworld"}:raise ValueError("unsupported runner")
    allowed={"run_hybrid":{"hybrid_frontier","hybrid_disagreement","symbolic_fixed","symbolic_random","symbolic_coverage","symbolic_dopt","no_expansion"},
             "run_research":{"generic","verified_program","frontier"},
             "run_openworld":{"numeric_frontier","numeric_full_frontier","numeric_full_frontier_once","numeric_dopt","numeric_whitened_dopt","numeric_iopt","proposer_frontier","proposer_full_frontier","memory_scoped_frontier","memory_unscoped_frontier"}}
    if not set(spec["strategies"])<=allowed[runner]:raise ValueError("unknown strategy")
    for name in ("seeds","families","faults","strategies"):
        if not spec[name] or len(set(spec[name]))!=len(spec[name]):raise ValueError("empty or duplicated task dimension: "+name)
    phase=spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",phase):raise ValueError("invalid phase directory")
    output=ROOT/"results"/phase
    snapshot=ROOT/"snapshots"/phase
    if output.exists() or snapshot.exists():raise ValueError("phase already exists; choose a new declared phase")
    tasks=[{"seed":seed,"family":family,"fault":fault,"strategy":strategy}
           for seed in spec["seeds"] for family in spec["families"]
           for fault in spec["faults"] for strategy in spec["strategies"]]
    if runner=="run_openworld":
        modes=spec.get("fact_modes",["structured"])
        if not modes or len(set(modes))!=len(modes) or not set(modes)<={"structured","text"}:
            raise ValueError("invalid public fact modes")
        tasks=[task|{"fact_mode":mode} for task in tasks for mode in modes]
    command=[sys.executable,str(ROOT/(runner+".py")),"--phase",phase,
        "--workers",str(spec.get("workers",1))]
    for name in ("seeds","families","faults","strategies"):
        command.extend(["--"+name,",".join(map(str,spec[name]))])
    if runner=="run_hybrid":
        if not spec.get("llm",True):command.append("--no-llm")
        if spec.get("random_parameters",False):command.append("--random-parameters")
    elif "calls" in spec:
        command.extend(["--calls",str(spec["calls"])])
    if runner=="run_openworld":
        command.extend(["--fact-modes",",".join(modes)])
        allocation=spec.get("confirmation",{})
        cohorts=allocation.get("cohorts_per_check",1);n=allocation.get("cohort_n",400);rounds=allocation.get("rounds",2)
        if cohorts not in (1,2,3) or rounds not in (1,2,3,4) or not 100<=n<=800:
            raise ValueError("invalid confirmation allocation")
        if allocation.get("max_checks",2*rounds)!=2*rounds or allocation.get("total_alpha",.05)!=.05 or allocation.get("tolerance",.05)!=.05:
            raise ValueError("declared statistical rule differs from runner")
        command.extend(["--confirmation-cohorts",str(cohorts),"--confirmation-n",str(n),"--confirmation-rounds",str(rounds)])
        actual={"sessions":4800+2*rounds*cohorts*n,"arms":12+2*rounds*cohorts,"cost":148+52*(cohorts-1)+22*cohorts*(rounds-2)}
        if "limits" in spec and spec["limits"]!=actual:raise ValueError("declared budget differs from runner allocation")
        price=spec.get("retail_price",8.)
        if type(price) not in (int,float) or not 6<=price<=12:raise ValueError("invalid public retail price")
        command.extend(["--retail-price",str(price)])
        if "memory_archive" in spec:
            memory_path=(PROJECT/spec["memory_archive"]).resolve()
            if not memory_path.is_file() or not memory_path.is_relative_to(PROJECT):raise ValueError("memory archive must be a project file")
            from conditional_memory import validate_archive
            memory_value=validate_archive(json.loads(memory_path.read_text()))
            diagnostic=spec.get("memory_prior_diagnostic",{})
            rule={"max_checks":7*len(memory_value["episodes"]),"total_alpha":.05,"tolerance":.05}
            if any(diagnostic.get(k,v)!=v for k,v in rule.items()):raise ValueError("declared memory diagnostic differs from runner")
            command.extend(["--memory-archive",str(memory_path)])
        elif any(s.startswith("memory_") for s in spec["strategies"]):raise ValueError("memory archive not declared")
    files=list(ROOT.glob("*.py"))+[PROJECT/"configs/base_model.json",PROJECT/"environment.yml",PROJECT/"configs/conda-osx-arm64.lock.txt"]
    if runner=="run_openworld" and "memory_archive" in spec:files.append(memory_path)
    hashes={}
    for p in files:
        rel=p.relative_to(PROJECT);q=snapshot/rel
        q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        hashes[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    manifest={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "creation_timing":"before_launch","specification":spec,"expected_runs":len(tasks),
        "planned_tasks":tasks,"command_argv":command,"source_sha256":hashes,
        "status":"prepared","snapshot":str(snapshot.relative_to(PROJECT))}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    (snapshot/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    env=os.environ.copy();env["PYTHONDONTWRITEBYTECODE"]="1"
    run=subprocess.run(command,cwd=ROOT,env=env,check=False)
    manifest.update(status="runner_exited",exit_code=run.returncode,
        completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        observed_runs=sum((output/(f"{t['strategy']}_{t['family']}_{t['fault']}"+
            (f"_{t['fact_mode']}" if "fact_mode" in t else "")+f"_s{t['seed']}.json")).exists() for t in tasks))
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    return run.returncode


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("specification",type=Path)
    args=ap.parse_args();raise SystemExit(launch(args.specification))
