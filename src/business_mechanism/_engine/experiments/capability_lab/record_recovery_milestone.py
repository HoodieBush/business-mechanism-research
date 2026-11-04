"""Developer ledger for the conditional continuation study; no model calls."""
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

from audit_recovery import analyze
from model_protocol import usage_summary
from run_recovery import filename

ROOT = Path(__file__).resolve().parent; PROJECT = ROOT.parents[1]
SETUP = ROOT / "results/setup_deepseek_20261012"
PHASE = "development_recovery_v01_20261012"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    prior = json.loads((SETUP / "controlled-development-ledger-terminal-v01.json").read_text())
    old_validation = json.loads((SETUP / "validation-terminal-v01.json").read_text())
    folder = ROOT / "results" / PHASE; manifest = json.loads((folder / "manifest.json").read_text())
    analysis = analyze(folder)
    paths = [folder / filename(task) for task in manifest["planned_tasks"]]
    runs = [json.loads(p.read_text()) for p in paths if p.exists()]
    model_usage = usage_summary([record for run in runs for record in run["model_calls"]])
    counts = Counter(prior["status_counts"]); counts.update(run["status"] for run in runs)
    groups = {(task["seed"], task["family"]) for task in manifest["planned_tasks"]}
    seeds = {task["seed"] for task in manifest["planned_tasks"]}
    ledger = {**prior, "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "prior_ledger": "controlled-development-ledger-terminal-v01.json", "recovery_challenge_phase": PHASE,
              "recovery_challenge_records": len(runs), "recovery_challenge_planned": manifest["expected_runs"],
              "recovery_challenge_model_usage": model_usage,
              "recovery_challenge_raw_sha256": {str(p.relative_to(PROJECT)): sha(p) for p in paths if p.exists()},
              "total_new_generator_records": prior["total_new_generator_records"] + len(runs),
              "total_planned_new_generator_runs": prior["total_planned_new_generator_runs"] + manifest["expected_runs"],
              "status_counts": dict(counts), "latent_parameter_groups": prior["latent_parameter_groups"] + len(groups),
              "price_world_conditions": prior["price_world_conditions"] + len(groups),
              "seed_clusters": prior["seed_clusters"] + len(seeds),
              "total_model_usage_with_prior_new_generator": {k: v + model_usage[k] for k, v in prior["total_model_usage_with_prior_new_generator"].items()},
              "recovery_interpretation": "Conditional public-entry challenge, not autonomous discovery/ABC/locked test. Two LLMs reopen on actual refutation; one new scoped confirmation, no operating gain. Extra numeric coverage refutes the identical model. Shared entry and policies are correlated repeats; a unit fixture also uses this development seed."}
    write(SETUP / "controlled-development-ledger-recovery-v01.json", ledger)
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    log = tests.stdout + tests.stderr; (SETUP / "unit-tests-recovery-v01.log").write_text(log)
    match = re.search(r"Ran (\d+) tests", log)
    diff = subprocess.run(["git", "diff", "--check"], cwd=PROJECT, text=True, capture_output=True)
    files = subprocess.run(["rg", "--files", "--hidden", "--no-ignore", "-g", "!.git/**"], cwd=PROJECT, text=True, capture_output=True, check=True).stdout.splitlines()
    credential = Path.home() / ".config/leicheng-project/api_key"; key = credential.read_bytes().strip()
    hits = [p for p in files if (PROJECT / p).is_file() and key and key in (PROJECT / p).read_bytes()]
    snapshots = []
    for phase in [record["phase"] for record in old_validation["snapshots"]] + [PHASE]:
        saved = json.loads((ROOT / "results" / phase / "manifest.json").read_text()); directory = PROJECT / saved["snapshot"]
        snapshots.append({"phase": phase, "hash_mismatches": [p for p, h in saved["source_sha256"].items() if not (directory / p).exists() or sha(directory / p) != h], "exit_code": saved.get("exit_code")})
    temporal = json.loads((SETUP / "controlled-development-ledger-temporal-v03.json").read_text())
    hashes = {**prior["scientific_raw_sha256"], **prior["terminal_fixture_raw_sha256"], **temporal["temporal_raw_sha256"]}
    old_errors = [p for p, h in hashes.items() if not (PROJECT / p).exists() or sha(PROJECT / p) != h]
    docs = [PROJECT / "AGENTS.md", ROOT / "README.md"] + list((PROJECT / "documents/库存机制发现Agent框架研究").glob("*.md"))
    missing = []; links = 0
    for path in docs:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            target = target.strip().strip("<>")
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            links += 1
            if not (path.parent / unquote(target.split("#", 1)[0])).exists():
                missing.append({"file": str(path.relative_to(PROJECT)), "target": target})
    validation = {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "unit_tests": {"tests": int(match[1]) if match else None, "exit_code": tests.returncode},
                  "git_diff_check": {"exit_code": diff.returncode, "output": diff.stdout + diff.stderr},
                  "credential_scan": {"files": len(files), "hits": hits, "mode": oct(credential.stat().st_mode & 0o777),
                      "parent_mode": oct(credential.parent.stat().st_mode & 0o777), "outside_project": not credential.is_relative_to(PROJECT)},
                  "snapshots": snapshots, "prior_raw_hash_mismatches": old_errors, "local_links": {"checked": links, "missing": missing},
                  "recovery_audit_passed": sum(record["passed"] for record in analysis["records"]),
                  "shared_entries_passed": all(c["same_entry_and_wakeup"] for c in analysis["comparisons"]),
                  "planned_missing_current_runs": [p.name for p in paths if not p.exists()],
                  "retained_missing_planned_runs": prior["missing_planned_runs"],
                  "retained_historical_scope_issues": prior["retained_historical_scope_issues"], "all_historical_runs_passed": False,
                  "mutation_tests": "test_recovery_audit rehashed alpha, false analysis, omitted actual trace, worker scientific decision; expected substantive issue required",
                  "source_sha256": {str(p.relative_to(PROJECT)): sha(p) for p in list(ROOT.glob("*.py")) + docs}}
    validation["current_validation_passed"] = tests.returncode == diff.returncode == 0 and not hits and not old_errors and not missing and not validation["planned_missing_current_runs"] and not any(s["hash_mismatches"] for s in snapshots) and analysis["passed"]
    write(SETUP / "validation-recovery-v01.json", validation)
    print(json.dumps({"records": ledger["total_new_generator_records"], "planned": ledger["total_planned_new_generator_runs"],
                      "worlds": ledger["latent_parameter_groups"], "seeds": ledger["seed_clusters"], "tests": validation["unit_tests"],
                      "audited": validation["recovery_audit_passed"], "snapshots": len(snapshots), "key_hits": len(hits),
                      "new_usage": model_usage, "current_validation_passed": validation["current_validation_passed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
