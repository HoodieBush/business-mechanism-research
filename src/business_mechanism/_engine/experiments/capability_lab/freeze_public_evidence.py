"""Archive replay inputs and source before zero-API evidence reconstruction."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent; PROJECT = ROOT.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launch(spec_file):
    spec_file = Path(spec_file).resolve(); spec = json.loads(spec_file.read_text())
    if not spec_file.is_relative_to(PROJECT / "configs") or spec["runner"] != "replay_public_evidence":
        raise ValueError("invalid specification")
    if any(spec[k] != 0 for k in ("new_api_calls", "new_samples", "new_independent_units")) or spec["historical_actor_received_new_view"] is not False:
        raise ValueError("not an archive-only replay")
    if not spec["source_files"] or len(set(spec["source_files"])) != len(spec["source_files"]):
        raise ValueError("empty/duplicate replay input")
    sources = [(PROJECT / p).resolve() for p in spec["source_files"]]
    if any(not p.is_relative_to(ROOT / "results") or not p.is_file() for p in sources):
        raise ValueError("source outside the archived public-study runs")
    phase = spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", phase):
        raise ValueError("invalid phase")
    out = ROOT / "results" / phase; snapshot = ROOT / "snapshots" / phase
    if out.exists() or snapshot.exists():
        raise ValueError("phase exists")
    hashes = {}
    for source in list(ROOT.glob("*.py")) + [spec_file, PROJECT / "configs/base_model.json", PROJECT / "environment.yml", PROJECT / "configs/conda-osx-arm64.lock.txt"]:
        rel = source.relative_to(PROJECT); dest = snapshot / rel; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest); hashes[str(rel)] = sha(source)
    out.mkdir(parents=True)
    manifest = {"created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "creation_timing": "before_replay_not_before_original_studies",
                "specification": spec, "source_sha256": hashes, "source_raw_sha256": {str(p.relative_to(PROJECT)): sha(p) for p in sources},
                "snapshot": str(snapshot.relative_to(PROJECT)), "expected_source_records": len(sources), "status": "prepared"}
    def save():
        (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    save(); (snapshot / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    env = os.environ.copy(); env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        for path in ROOT.glob("*.py"): compile(path.read_text(), str(path), "exec")
    except SyntaxError as error:
        manifest.update(status="preflight_failed", exit_code=1, error=str(error)); save(); return 1
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-q"], cwd=ROOT, env=env, text=True, capture_output=True)
    (out / "preflight-tests.log").write_text(tests.stdout + tests.stderr); manifest["preflight_exit_code"] = tests.returncode
    if tests.returncode:
        manifest.update(status="preflight_failed", exit_code=tests.returncode); save(); return tests.returncode
    process = subprocess.run([sys.executable, str(ROOT / "replay_public_evidence.py"), str(spec_file)], cwd=ROOT, env=env)
    manifest.update(status="replay_exited", exit_code=process.returncode, completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save(); return process.returncode


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("spec", type=Path); args = ap.parse_args(); raise SystemExit(launch(args.spec))
