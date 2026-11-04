"""Freeze the complete task-component matrix before model calls or sampling."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]


def launch(spec_path):
    spec_path = Path(spec_path).resolve();spec = json.loads(spec_path.read_text())
    if not spec_path.is_relative_to(PROJECT / "configs") or spec["strategies"] != ["numeric_full", "native_control", "discovery_tasks"]:raise ValueError("invalid component specification")
    if spec["actor_features"] != {
        "native_control": {"use_state_brief": False, "use_reference_contract": True, "use_discovery_tasks": False},
        "discovery_tasks": {"use_state_brief": False, "use_reference_contract": True, "use_discovery_tasks": True}}:raise ValueError("confounded component comparison")
    if spec["scientific_checks"] != {"max_checks": 6, "n_per_cohort": 800, "total_alpha": .05, "tolerance": .05, "max_revisions": 2}:raise ValueError("changed confirmation protocol")
    if spec["terminal_policy"] != "settle_committed" or not spec["no_scripted_LLM_warmup"]:raise ValueError("invalid research entry or terminal policy")
    return launch_matrix(spec_path,spec)


def launch_matrix(spec_path,spec):
    """Shared freeze/execute machinery; component callers validate their arms."""
    dimensions = [spec[key] for key in ("seeds", "families", "profiles")]
    if any(not values or len(values) != len(set(values)) for values in dimensions):raise ValueError("empty/duplicate task dimension")
    if not set(spec["families"]) <= {"threeway", "mixed_scope", "source_joint", "null"} or not set(spec["profiles"]) <= {"staggered", "interruptions"}:raise ValueError("unknown task family/profile")
    tasks = [{"seed": seed, "family": family, "profile": profile, "strategy": strategy}
        for seed in spec["seeds"] for family in spec["families"] for profile in spec["profiles"] for strategy in spec["strategies"]]
    policy = json.loads((PROJECT / "configs/experiment_progression.json").read_text())
    paid = sum(task["strategy"] != "numeric_full" for task in tasks)
    if paid * spec["api_limits"]["reported_tokens"] > spec["round_reported_token_budget"] or spec["round_reported_token_budget"] > policy["default_round_reported_token_budget"]:raise ValueError("matrix exceeds shared model budget")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", spec["phase"]):raise ValueError("invalid phase")
    output = ROOT / "results" / spec["phase"];snapshot = ROOT / "snapshots" / spec["phase"]
    if output.exists() or snapshot.exists():raise ValueError("stage already exists")
    output.mkdir(parents=True);hashes = {}
    for source in [*ROOT.glob("*.py"), spec_path, PROJECT / "configs/base_model.json", PROJECT / "configs/experiment_progression.json",
                   PROJECT / "environment.yml", PROJECT / "configs/conda-osx-arm64.lock.txt"]:
        relative = source.relative_to(PROJECT);destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(source, destination)
        hashes[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {"created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "creation_timing": "before_launch",
        "specification": spec, "planned_tasks": tasks, "expected_runs": len(tasks), "snapshot": str(snapshot.relative_to(PROJECT)),
        "source_sha256": hashes, "status": "prepared"}
    def save():(output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    save();(snapshot / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    env = os.environ.copy();env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    (output / "preflight-tests.log").write_text(tests.stdout + tests.stderr)
    manifest["preflight_exit_code"] = tests.returncode
    if tests.returncode:manifest["status"] = "preflight_failed";save();return tests.returncode
    result = subprocess.run([sys.executable, str(ROOT / "run_organization.py"), "--spec", str(spec_path)], cwd=ROOT, env=env)
    from run_organization import filename
    manifest.update(status="runner_exited", exit_code=result.returncode, observed_runs=sum((output / filename(task)).exists() for task in tasks),
        completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat());save()
    return result.returncode


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser();parser.add_argument("spec", type=Path)
    raise SystemExit(launch(parser.parse_args().spec))
