"""Inference diagnostics from original public event prefixes, not a live actor.

selected_fit uses exactly the final candidate's original training snapshot.
close_released uses only discovery/released evidence before decision closure.
Neither includes post-close receipts or unreleased confirmation measurements.
"""
import copy
import math

from model_order import candidate_key
from numeric_pool import numeric_pool
from public_fitting import fit_public_candidate
from temporal_lab import digest

VERSION = "public-inference-replay-v0.1-two-public-prefixes"


class PublicInferenceView:
    def __init__(self, catalogs, measurements):
        self.catalogs = copy.deepcopy(catalogs)
        self.data = [(copy.deepcopy(row), row["observed_sales"]) for row in measurements]
        self.transfer_open = "adaptation" in self.catalogs

    def public_catalog(self, stage):
        return copy.deepcopy(self.catalogs[stage])

    def verified_observations(self):
        return copy.deepcopy(self.data)


def extract(run, mode):
    events = run["research"]["events"]
    cid = run["research"]["final"]["candidate_id"]
    selected_event = next(event for event in events if event["kind"] == "candidate_registered" and event["payload"]["candidate_id"] == cid)
    selected = selected_event["payload"]
    if mode == "selected_fit":
        boundary = selected_event
    elif mode == "close_released":
        boundary = next(event for event in events if event["kind"] == "research_decisions_closed")
    else:raise ValueError("unknown replay mode")
    prefix = events[:boundary["sequence"]]
    latest = {};jobs = {};released = set();candidates = []
    catalogs = {"source": copy.deepcopy(run["legal_input"]["catalog"])}
    for event in prefix:
        kind = event["kind"];payload = event["payload"]
        if kind == "evidence_received":latest[payload["measurement"]["experiment_id"]] = payload["measurement"]
        elif kind == "registered_plan_linked":jobs[payload["job_id"]] = payload
        elif kind == "confirmation_evidence_released":released.update(payload["training_evidence_ids"])
        elif kind == "candidate_registered":candidates.append(payload)
        elif kind == "scientific_tool_response" and payload["request"]["tool"] == "open_adaptation" and payload["feedback"]["ok"]:
            # Event order, rather than clock equality, determines which public
            # catalogue receipt was actually available at this boundary.
            catalogs["adaptation"] = copy.deepcopy(payload["feedback"]["result"]["catalog"])
    if mode == "selected_fit":
        ids = set(selected["training_evidence_ids"])
        # The selected proposal was already submitted and fitted before its
        # registration; retaining its original class is not a new proposal.
        candidates.append(selected)
    else:
        ids = released | {row["experiment_id"] for row in latest.values()
            if jobs.get(row["job_id"], {}).get("purpose") == "discovery" and row["verified_supply"] and row["verified_meter"]}
    rows = [row for row in latest.values() if row["experiment_id"] in ids]
    if {row["experiment_id"] for row in rows} != ids or not rows:
        raise ValueError("replay training IDs must all exist in the public prefix")
    if any(not row["verified_supply"] or not row["verified_meter"] or row["available_at"] > boundary["available_at"] for row in rows):
        raise ValueError("replay contains unverified or future evidence")
    patterns = selected["model"]["role_patterns"]
    return {"view": PublicInferenceView(catalogs, rows), "patterns": copy.deepcopy(patterns),
            "candidates": copy.deepcopy(candidates), "training_ids": sorted(ids),
            "selected_candidate_id": cid, "boundary_event_sequence": boundary["sequence"],
            "boundary_available_at": boundary["available_at"],
            "public_prefix_sha256": digest(prefix), "measurement_snapshot_sha256": digest(rows),
            "selected_original_model": copy.deepcopy(selected["model"])}


def infer(snapshot):
    view = snapshot["view"]
    pool = numeric_pool(view, snapshot["patterns"], expanded=True)
    proposals = {digest(candidate["fit_args"]): candidate["fit_args"] for candidate in snapshot["candidates"]
                 if candidate.get("fit_args") and candidate["origin"] == "policy_proposal"}
    n = sum(row["n"] for row, _ in view.verified_observations())
    for args in proposals.values():
        fitted = fit_public_candidate(args, view.verified_observations(), view.catalogs)
        rank = len(args["parameters"])
        pool.append({"model": fitted["model"], "terms": [args["expression"]], "rank": rank,
                     "deviance": fitted["binomial_deviance"], "bic": fitted["binomial_deviance"] + rank * math.log(n),
                     "origin": "policy_proposal", "optimizer_success": fitted["optimizer_success"]})
    pool.sort(key=candidate_key)
    return {"model": copy.deepcopy(pool[0]["model"]), "best_public_fit": {
        key: copy.deepcopy(pool[0][key]) for key in ("terms", "rank", "bic", "deviance", "origin")},
        "proposal_classes_refitted": len(proposals), "candidate_count": len(pool),
        "selection_rule": "same public BIC/program-size ordering; no private prediction or profit selection"}
