"""Read-only receipt, analysis and training permissions; not scientific advice."""
import copy

VERSION = "confirmation-phase-v0.2-public-event-derived-states"


def phases(checks, public_measurements, clock):
    latest = {}
    for row in public_measurements:
        if row["available_at"] > clock:continue
        key = row["job_id"]
        if key not in latest or row["evidence_version"] > latest[key]["evidence_version"]:latest[key] = row
    result = []
    for check in checks:
        jobs = check["job_ids"];received = [latest[job] for job in jobs if job in latest]
        verified = [row for row in received if row["verified_supply"] and row["verified_meter"]]
        complete = len(verified) == len(jobs) == 2
        analysis = check.get("state")
        if "result" in check:analysis = None if check["result"] is None else check["result"]["state"]
        result.append({"check_id": check["check_id"], "candidate_id": check["candidate_id"],
            "receipt_phase": "incomplete_registered_check" if len(jobs) != 2 else "verified_complete" if complete else "received_needs_verification" if len(received) == len(jobs) else "awaiting_receipts",
            "verified_measurement_ids": [row["experiment_id"] for row in verified],
            "unverified_measurement_ids": [row["experiment_id"] for row in received if row not in verified],
            "missing_job_ids": [job for job in jobs if job not in latest],
            "analysis_phase": "assessed" if analysis is not None else "ready_to_assess" if complete else "awaiting_verified_inputs",
            "analysis_outcome": analysis,
            "training_permission": "released_for_refitting" if check["released"] else "protected_from_fitting",
            "protection_does_not_block_independent_analysis": True})
    return {"version": VERSION, "checks": copy.deepcopy(result), "read_only": True,
        "note": "Received/verified, independently assessed, and released for later training are separate states. This projection performs no analysis, release, fit, sampling or scientific certification."}


def from_events(events, clock):
    """Reconstruct only actually public checks/receipts at the given prefix."""
    checks = {};measurements = []
    for event in events:
        if event["available_at"] > clock:continue
        kind = event["kind"];payload = event["payload"]
        if kind == "check_frozen_before_execution":checks[payload["check_id"]] = copy.deepcopy(payload)
        elif kind == "registered_plan_linked" and payload["purpose"] == "confirmation":checks[payload["check_id"]]["job_ids"].append(payload["job_id"])
        elif kind == "independent_check_assessed":checks[payload["check_id"]] = copy.deepcopy(payload)
        elif kind == "confirmation_evidence_released":
            for check in checks.values():
                if check["result"] is not None:check["released"] = True
        elif kind == "evidence_received":measurements.append(copy.deepcopy(payload["measurement"]))
    return phases(list(checks.values()), measurements, clock)
