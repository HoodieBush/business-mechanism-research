"""Posthoc public design geometry; no outcome, hidden mechanism or profit ranking."""
import hashlib
import json
from pathlib import Path

import numpy as np

from prediction_design import public_basis
from public_inference_replay import extract

VERSION = "public-design-coverage-v0.1-received-geometry"


def coverage(snapshot):
    view = snapshot["view"]
    designs, z, _, metadata = public_basis(json.dumps(snapshot["patterns"], sort_keys=True),
        json.dumps(view.catalogs, sort_keys=True), interaction_order=4)
    lookup = {design: index for index, design in enumerate(designs)}
    measured = {(row["stage"], row["site"], tuple(sorted(row["assortment"]))) for row, _ in view.verified_observations()}
    indices = sorted(lookup[design] for design in measured)
    singular = np.linalg.svd(z[indices], compute_uv=False)
    rank = int(np.sum(singular > singular[0] * 1e-10)) if len(singular) and singular[0] else 0
    return {"version": VERSION, **metadata, "unique_received_conditions": len(measured), "received_design_rank": rank,
        "unobserved_public_subspace_dimensions": metadata["public_rank"] - rank,
        "observed_sites": sorted({(stage, site) for stage, site, _ in measured}),
        "assortment_sizes": sorted({len(arm) for _, _, arm in measured}),
        "outcomes_used": False, "diagnostic_only": True,
        "interpretation": "Rank of a public linear grammar surrogate. Repeated cohorts improve precision, not geometry rank; a rank deficit is not proof that a sparse/nonlinear mechanism or business decision is unidentified."}


def analyze(parent_dir, output):
    from run_organization import filename
    manifest = json.loads((parent_dir / "manifest.json").read_text());rows = []
    for task in manifest["planned_tasks"]:
        path = parent_dir / filename(task);run = json.loads(path.read_text())
        for mode in ("selected_fit", "close_released"):
            rows.append({"parent_file": path.name, "parent_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "view": mode, "training_ids": extract(run, mode)["training_ids"], **coverage(extract(run, mode))})
    report = {"scope": "posthoc_public_geometry_not_causal_attribution", "records": rows,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "model_api_calls": 0, "new_sessions": 0}
    with output.open("x") as handle:handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for row in rows:print(json.dumps({key: row[key] for key in ("parent_file", "view", "received_design_rank", "public_rank", "unique_received_conditions")}), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser();parser.add_argument("parent_dir", type=Path);parser.add_argument("output", type=Path)
    args = parser.parse_args();analyze(args.parent_dir, args.output)
