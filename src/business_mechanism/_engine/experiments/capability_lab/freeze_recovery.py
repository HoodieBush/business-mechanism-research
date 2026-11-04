"""Freeze the entire conditional continuation matrix before any paid call."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from research_queue import CONTRACT, VERSION
from run_recovery import STRATEGIES, filename
from temporal_lab import digest

ROOT = Path(__file__).resolve().parent; PROJECT = ROOT.parents[1]


def launch(spec_file):
    spec_file = Path(spec_file).resolve(); spec = json.loads(spec_file.read_text())
    if not spec_file.is_relative_to(PROJECT / "configs") or spec["runner"] != "run_recovery":
        raise ValueError("invalid specification")
    if spec["research_workflow_version"] != VERSION or spec["terminal_policy"] != "received_only" or spec["strategies"] != STRATEGIES:
        raise ValueError("workflow contract mismatch")
    if spec["numeric_additional_checks"] != 2 or spec["api_limits"] != {"calls": 8, "reported_tokens": 80000, "max_output_tokens": 1600}:
        raise ValueError("allocation mismatch")
    for key in ("seeds", "families", "profiles"):
        if not spec[key] or len(set(spec[key])) != len(spec[key]):
            raise ValueError("empty/duplicate dimension")
    if any(type(s) is not int for s in spec["seeds"]) or not set(spec["families"]) <= {"threeway", "mixed_scope", "source_joint", "null"} or not set(spec["profiles"]) <= {"staggered", "interruptions"}:
        raise ValueError("invalid task")
    if type(spec["deadline"]) is not int or spec["deadline"] < 8 or spec["price"] <= 0:
        raise ValueError("invalid environment")
    phase = spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", phase):
        raise ValueError("invalid phase")
    out = ROOT / "results" / phase; snapshot = ROOT / "snapshots" / phase
    if out.exists() or snapshot.exists():
        raise ValueError("phase exists")
    tasks = [dict(seed=s, family=f, profile=p, strategy=m) for s in spec["seeds"] for f in spec["families"]
             for p in spec["profiles"] for m in spec["strategies"]]
    hashes = {}
    for source in list(ROOT.glob("*.py")) + [spec_file, PROJECT / "configs/base_model.json", PROJECT / "environment.yml", PROJECT / "configs/conda-osx-arm64.lock.txt"]:
        rel = source.relative_to(PROJECT); dest = snapshot / rel; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest); hashes[str(rel)] = hashlib.sha256(source.read_bytes()).hexdigest()
    out.mkdir(parents=True)
    manifest = {"created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "creation_timing": "before_launch",
                "specification": spec, "workflow_contract": CONTRACT, "workflow_contract_sha256": digest(CONTRACT),
                "planned_tasks": tasks, "expected_runs": len(tasks), "snapshot": str(snapshot.relative_to(PROJECT)),
                "source_sha256": hashes, "status": "prepared"}
    def save():
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    save(); (snapshot / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        for p in ROOT.glob("*.py"):
            compile(p.read_text(), str(p), "exec")
    except SyntaxError as error:
        manifest.update(status="preflight_failed", exit_code=1, error=str(error)); save(); return 1
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    (out / "preflight-tests.log").write_text(tests.stdout + tests.stderr)
    manifest["preflight_exit_code"] = tests.returncode
    if tests.returncode:
        manifest.update(status="preflight_failed", exit_code=tests.returncode); save(); return tests.returncode
    process = subprocess.run([sys.executable, str(ROOT / "run_recovery.py"), "--spec", str(spec_file)], cwd=ROOT, env=env)
    manifest.update(status="runner_exited", exit_code=process.returncode, completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    observed_runs=sum((out / filename(t)).exists() for t in tasks))
    save(); return process.returncode


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("spec", type=Path); args = ap.parse_args(); raise SystemExit(launch(args.spec))
