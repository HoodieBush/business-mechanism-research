"""Freeze a diagnostic matrix and public models before private evaluation."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from audit_scientific import audit
from public_inference_replay import VERSION, extract, infer
from run_organization import filename

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x") as handle:handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def launch(spec_path):
    spec_path = Path(spec_path).resolve();spec = json.loads(spec_path.read_text())
    if not spec_path.is_relative_to(PROJECT / "configs") or not re.fullmatch(r"[a-zA-Z0-9_-]+", spec["phase"]):raise ValueError("invalid stage")
    if spec["views"] != ["selected_fit", "close_released"] or not spec["include_all_parent_tasks"]:raise ValueError("invalid diagnostic matrix")
    if spec["max_new_model_api_calls"] != 0 or spec["max_new_sessions"] != 0:raise ValueError("replay cannot call models or sample")
    parent_dir = ROOT / "results" / spec["parent_phase"]
    parent_manifest = json.loads((parent_dir / "manifest.json").read_text())
    parents = [parent_dir / filename(task) for task in parent_manifest["planned_tasks"]]
    tasks = [{"parent": str(path.relative_to(PROJECT)), "parent_sha256": sha(path), "view": view}
             for path in parents for view in spec["views"]]
    output = ROOT / "results" / spec["phase"];snapshot = ROOT / "snapshots" / spec["phase"]
    if output.exists() or snapshot.exists():raise ValueError("stage already exists")
    output.mkdir(parents=True);hashes = {}
    for source in [*ROOT.glob("*.py"), spec_path, PROJECT / "environment.yml", PROJECT / "configs/conda-osx-arm64.lock.txt",
                   parent_dir / "manifest.json", *parents]:
        relative = source.relative_to(PROJECT);destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True);shutil.copy2(source, destination);hashes[str(relative)] = sha(source)
    manifest = {"created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "creation_timing": "before_replay",
        "version": VERSION, "specification": spec, "planned_tasks": tasks, "expected_replays": len(tasks),
        "source_sha256": hashes, "snapshot": str(snapshot.relative_to(PROJECT)), "status": "prepared",
        "independent_units": "original parent worlds only; replay does not increase science-task count"}
    def save():
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    save();write_new(snapshot / "manifest.json", manifest)
    env = os.environ.copy();env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    write_new(output / "preflight-tests.json", {"exit_code": tests.returncode, "log": tests.stdout + tests.stderr})
    audits = {path.name: audit(json.loads(path.read_text())) for path in parents}
    write_new(output / "parent-audits.json", audits)
    if tests.returncode or not all(row["passed"] for row in audits.values()):
        manifest["status"] = "preflight_failed";save();return 1
    rows = []
    for task in tasks:
        start = time.monotonic();parent_path = PROJECT / task["parent"]
        if sha(parent_path) != task["parent_sha256"]:raise ValueError("parent changed after freezing")
        parent = json.loads(parent_path.read_text());name = parent_path.stem + "__" + task["view"]
        row = {**task, "parent_strategy": parent["strategy"], "parent_status": parent["status"],
               "new_sessions": 0, "model_api_calls": 0, "scientific_confirmation_added": False}
        try:
            public = extract(parent, task["view"]);fitted = infer(public)
            row.update({key: value for key, value in public.items() if key not in {"view", "patterns", "candidates", "selected_original_model"}})
            row.update({key: value for key, value in fitted.items() if key != "model"})
            row.update(status="model_frozen", frozen_model=fitted["model"],
                       training_sessions=sum(measurement["n"] for measurement, _ in public["view"].verified_observations()),
                       exact_original_expression=fitted["model"]["expression"] == public["selected_original_model"]["expression"])
            frozen = output / (name + "__frozen-public.json")
            write_new(frozen, row);row["frozen_public_artifact_sha256"] = sha(frozen)
            # Private imports and scoring happen only after the public-selected
            # candidate has been saved. They cannot determine candidate order.
            from choice_world import ChoiceWorld
            from operating_eval import evaluate
            deployed = json.loads(json.dumps(fitted["model"]))
            deployed["role_patterns"] = parent["deployment_physical_facts"]["role_patterns"]
            cfg = parent["private_configuration"]
            world = ChoiceWorld(cfg["seed"], cfg["family"], "none", "structured", cfg["price"])
            row.update(status="finished", private_score=evaluate(world, fitted["model"], deployed))
            row["parent_private_score_summary"] = {key: parent["private_score"][key] for key in
                ("heldout_effect_rmse", "mean_expected_operating_regret_per_customer")}
        except Exception as error:row.update(status="replay_failure", error=type(error).__name__ + ": " + str(error))
        row["elapsed_seconds"] = time.monotonic() - start
        write_new(output / (name + ".json"), row);rows.append(row)
        print(json.dumps({"parent": parent_path.name, "view": task["view"], "status": row["status"],
            "training_ids": row.get("training_ids"), "regret": row.get("private_score", {}).get("mean_expected_operating_regret_per_customer"),
            "error": row.get("error")}, ensure_ascii=False), flush=True)
    compact = [{key: row.get(key) for key in ("parent", "view", "parent_strategy", "parent_status", "status", "training_ids", "training_sessions",
                "best_public_fit", "candidate_count", "proposal_classes_refitted", "exact_original_expression", "parent_private_score_summary", "error")}
               | {"private_score_summary": {key: row.get("private_score", {}).get(key) for key in
                   ("heldout_effect_rmse", "mean_expected_operating_regret_per_customer")}} for row in rows]
    write_new(output / "analysis-public-inference-replay.json", {"phase": spec["phase"], "records": compact,
        "all_replays_finished": all(row["status"] == "finished" for row in rows), "new_sessions": 0, "model_api_calls": 0,
        "limitations": "Same original two development worlds and common private scoring streams. Conditional inference diagnostic; differences do not establish causal method effects or autonomous recovery.",
        "full_goal_completed": False})
    manifest.update(status="finished" if all(row["status"] == "finished" for row in rows) else "replay_failures",
        observed_replays=len(rows), completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat());save()
    return 0 if manifest["status"] == "finished" else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser();parser.add_argument("spec", type=Path)
    raise SystemExit(launch(parser.parse_args().spec))
