"""Freeze an equal-capability reference ablation before any model call."""
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


def launch(spec_file):
    spec_file = Path(spec_file).resolve()
    spec = json.loads(spec_file.read_text())
    if not spec_file.is_relative_to(PROJECT / "configs") or spec["strategies"] != ["numeric_full", "native_control", "reference_contract"]:
        raise ValueError("invalid experiment specification")
    policy = json.loads((PROJECT / "configs/experiment_progression.json").read_text())
    dimensions = [spec[key] for key in ("seeds", "families", "profiles")]
    if any(not values or len(values) != len(set(values)) for values in dimensions):raise ValueError("empty/duplicate task dimension")
    if not set(spec["families"]) <= {"threeway", "mixed_scope", "source_joint", "null"}:raise ValueError("unknown family")
    if not set(spec["profiles"]) <= {"staggered", "interruptions"}:raise ValueError("unknown receipt profile")
    tasks = [{"seed": seed, "family": family, "profile": profile, "strategy": strategy}
             for seed in spec["seeds"] for family in spec["families"] for profile in spec["profiles"] for strategy in spec["strategies"]]
    paid = sum(task["strategy"] != "numeric_full" for task in tasks)
    if paid * spec["api_limits"]["reported_tokens"] > spec["round_reported_token_budget"] or spec["round_reported_token_budget"] > policy["default_round_reported_token_budget"]:
        raise ValueError("matrix exceeds shared round allocation")
    if spec["actor_features"] != {"native_control": {"use_state_brief": False, "use_reference_contract": False},
        "reference_contract": {"use_state_brief": False, "use_reference_contract": True}}:raise ValueError("confounded component comparison")
    if spec["scientific_checks"] != {"max_checks": 6, "n_per_cohort": 800, "total_alpha": .05, "tolerance": .05, "max_revisions": 2}:
        raise ValueError("undeclared scientific protocol")
    if not spec["no_scripted_LLM_warmup"] or spec["terminal_policy"] != "settle_committed":raise ValueError("incorrect loop entry or terminal policy")
    phase = spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", phase):raise ValueError("invalid phase")
    output = ROOT / "results" / phase
    snapshot = ROOT / "snapshots" / phase
    if output.exists() or snapshot.exists():raise ValueError("phase already exists")
    output.mkdir(parents=True)
    hashes = {}
    sources = [*ROOT.glob("*.py"), spec_file, PROJECT / "configs/base_model.json",
        PROJECT / "configs/experiment_progression.json", PROJECT / "environment.yml", PROJECT / "configs/conda-osx-arm64.lock.txt"]
    for source in sources:
        relative = source.relative_to(PROJECT)
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {"created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "creation_timing": "before_launch",
        "specification": spec, "planned_tasks": tasks, "expected_runs": len(tasks),
        "snapshot": str(snapshot.relative_to(PROJECT)), "source_sha256": hashes, "status": "prepared"}
    def save():
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    save()
    (snapshot / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    env = os.environ.copy();env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        for path in ROOT.glob("*.py"):compile(path.read_bytes(), str(path), "exec")
    except SyntaxError as error:
        manifest.update(status="preflight_failed", error=str(error));save();return 1
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    (output / "preflight-tests.log").write_text(result.stdout + result.stderr)
    manifest["preflight_exit_code"] = result.returncode
    if result.returncode:
        manifest.update(status="preflight_failed");save();return result.returncode
    result = subprocess.run([sys.executable, str(ROOT / "run_organization.py"), "--spec", str(spec_file)], cwd=ROOT, env=env)
    from run_organization import filename
    manifest.update(status="runner_exited", exit_code=result.returncode,
        observed_runs=sum((output / filename(task)).exists() for task in tasks),
        completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save()
    return result.returncode


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser();parser.add_argument("spec", type=Path)
    raise SystemExit(launch(parser.parse_args().spec))
