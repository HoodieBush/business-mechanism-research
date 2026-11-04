"""Current common-service validation; archive replay adds no experimental units."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

from audit_scientific import audit
from public_evidence import PublicEvidenceStore
from research_action_schema import ARGS

ROOT = Path(__file__).resolve().parent; PROJECT = ROOT.parents[1]
SETUP = ROOT / "results/setup_deepseek_20261012"
PHASE = "public_evidence_replay_v01_20261012"


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value): path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    prior = json.loads((SETUP / "controlled-development-ledger-recovery-v01.json").read_text())
    old_validation = json.loads((SETUP / "validation-recovery-v01.json").read_text())
    folder = ROOT / "results" / PHASE; replay = json.loads((folder / "replay.json").read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    replay_checks = []
    for record in replay["records"]:
        source = json.loads((PROJECT / record["source_file"]).read_text())
        archive = PublicEvidenceStore.from_events(source["research"]["events"])
        replay_checks.append(archive.snapshot() == record["archive"])
        for boundary in record["request_boundaries"]:
            prefix = source["research"]["events"][:boundary["original_research_event_count"]]
            replay_checks.append(PublicEvidenceStore.from_events(prefix).view() == boundary["public_analysis_view"])
    ledger = {**prior, "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "prior_ledger": "controlled-development-ledger-recovery-v01.json",
              "public_evidence_archive_replay_separate": {"phase": PHASE, "source_records": replay["source_records"],
                  "original_request_boundaries": replay["original_request_boundaries"], "analysis_instances": replay["analysis_instances"],
                  "versioned_analysis_records": replay["versioned_analysis_records"], "api_calls": 0,
                  "new_samples": 0, "new_independent_units": 0, "historical_actor_received_new_view": False,
                  "artifact_sha256": sha(folder / "replay.json")}}
    write(SETUP / "controlled-development-ledger-public-evidence-v01.json", ledger)
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    log = tests.stdout + tests.stderr; (SETUP / "unit-tests-public-evidence-v01.log").write_text(log)
    match = re.search(r"Ran (\d+) tests", log)
    diff = subprocess.run(["git", "diff", "--check"], cwd=PROJECT, text=True, capture_output=True)
    paths = subprocess.run(["rg", "--files", "--hidden", "--no-ignore", "-g", "!.git/**"], cwd=PROJECT, text=True, capture_output=True, check=True).stdout.splitlines()
    credential = Path.home() / ".config/leicheng-project/api_key"; key = credential.read_bytes().strip()
    hits = [p for p in paths if (PROJECT / p).is_file() and key and key in (PROJECT / p).read_bytes()]
    snapshots = []
    for phase in [s["phase"] for s in old_validation["snapshots"]] + [PHASE]:
        saved = json.loads((ROOT / "results" / phase / "manifest.json").read_text()); snapshot = PROJECT / saved["snapshot"]
        snapshots.append({"phase": phase, "hash_mismatches": [p for p, h in saved["source_sha256"].items() if not (snapshot / p).exists() or sha(snapshot / p) != h], "exit_code": saved.get("exit_code")})
    temporal = json.loads((SETUP / "controlled-development-ledger-temporal-v03.json").read_text())
    raw_hashes = {**prior["scientific_raw_sha256"], **prior["terminal_fixture_raw_sha256"],
                  **prior["recovery_challenge_raw_sha256"], **temporal["temporal_raw_sha256"], **manifest["source_raw_sha256"]}
    errors = [p for p, h in raw_hashes.items() if not (PROJECT / p).exists() or sha(PROJECT / p) != h]
    audits = []
    for path in {**prior["scientific_raw_sha256"], **prior["terminal_fixture_raw_sha256"], **prior["recovery_challenge_raw_sha256"]}:
        result = audit(json.loads((PROJECT / path).read_text()))
        audits.append({"file": path, **result})
    docs = [PROJECT / "AGENTS.md", ROOT / "README.md"] + list((PROJECT / "documents/库存机制发现Agent框架研究").glob("*.md"))
    missing = []; links = 0
    for path in docs:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            target = target.strip().strip("<>")
            if "://" in target or target.startswith(("#", "mailto:")): continue
            links += 1
            if not (path.parent / unquote(target.split("#", 1)[0])).exists():
                missing.append({"file": str(path.relative_to(PROJECT)), "target": target})
    validation = {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "unit_tests": {"tests": int(match[1]) if match else None, "exit_code": tests.returncode},
        "git_diff_check": {"exit_code": diff.returncode, "output": diff.stdout + diff.stderr},
        "credential_scan": {"files": len(paths), "hits": hits, "mode": oct(credential.stat().st_mode & 0o777),
            "parent_mode": oct(credential.parent.stat().st_mode & 0o777), "outside_project": not credential.is_relative_to(PROJECT)},
        "snapshots": snapshots, "prior_raw_hash_mismatches": errors, "local_links": {"checked": links, "missing": missing},
        "scientific_audits": audits, "archive_replay_checks": len(replay_checks), "archive_replay_all_passed": all(replay_checks),
        "common_scientific_service_count": len(ARGS), "current_actor_has_paid_validation": False,
        "retained_missing_planned_runs": prior["missing_planned_runs"], "retained_historical_scope_issues": prior["retained_historical_scope_issues"],
        "all_historical_runs_passed": False,
        "source_sha256": {str(p.relative_to(PROJECT)): sha(p) for p in list(ROOT.glob("*.py")) + docs}}
    validation["current_validation_passed"] = tests.returncode == diff.returncode == 0 and not hits and not errors and not missing and not any(s["hash_mismatches"] for s in snapshots) and all(replay_checks) and all(a["passed"] for a in audits)
    write(SETUP / "validation-public-evidence-v01.json", validation)
    print(json.dumps({"tests": validation["unit_tests"], "scientific_audits": len(audits), "scientific_passed": sum(a["passed"] for a in audits),
                      "replay_checks": len(replay_checks), "snapshots": len(snapshots), "raw_mismatches": len(errors), "key_hits": len(hits),
                      "link_errors": len(missing), "current_validation_passed": validation["current_validation_passed"]}, ensure_ascii=False))


if __name__ == "__main__": main()
