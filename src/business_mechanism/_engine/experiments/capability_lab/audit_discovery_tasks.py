"""Check task versions, frozen batches and actual received/fitted artifacts."""
import copy

from temporal_lab import digest


def audit(run):
    research = run["research"];board = research.get("discovery_tasks")
    if board is None:return {"passed": True, "enabled": False, "registered": 0, "completed": 0, "issues": []}
    issues = [];tasks = {};latest = {};candidates = {};plans = {};closed = False
    def check(condition, name):
        if not condition and name not in issues:issues.append(name)
    fixed = ("task_id", "owner_context_id", "objective", "rationale", "input_candidate_id", "input_candidate_sha256", "input_model_sha256",
             "input_training_ids", "input_public_prefix_sha256", "design_method", "frozen_designs", "shared_limits_sha256")
    for index, event in enumerate(research["events"]):
        payload = event["payload"];kind = event["kind"]
        if kind == "candidate_registered":candidates[payload["candidate_id"]] = payload
        elif kind == "evidence_received":latest[payload["measurement"]["experiment_id"]] = payload["measurement"]
        elif kind == "registered_plan_linked":plans[payload["job_id"]] = payload
        elif kind == "research_decisions_closed":closed = True
        elif kind in {"discovery_task_registered", "discovery_task_updated"}:
            tid = payload["task_id"];old = tasks.get(tid)
            if kind == "discovery_task_registered":
                check(old is None and payload["version"] == 1 and payload["previous_version_sha256"] is None, "task_registration_unique")
                check(not closed and payload["status"] == "registered" and not payload["job_ids"] and payload["artifact"] is None, "task_frozen_before_launch")
                check(payload["input_public_prefix_sha256"] == research["events"][index-1]["event_hash"], "task_exact_input_prefix")
                candidate = candidates.get(payload["input_candidate_id"], {})
                check(candidate.get("content_hash") == payload["input_candidate_sha256"] and digest(candidate.get("model")) == payload["input_model_sha256"], "task_input_candidate_version")
                check(candidate.get("training_evidence_ids") == payload["input_training_ids"], "task_input_training_version")
                check(payload["shared_limits_sha256"] == digest(run["legal_input"]["limits"]), "task_shared_ledger")
                check(1 <= len(payload["frozen_designs"]) <= 3 and all(d["n"] == 400 for d in payload["frozen_designs"]), "task_declared_frontier_batch")
            else:
                check(old is not None and payload["version"] == old["version"]+1 and payload["previous_version_sha256"] == digest(old), "task_version_chain")
                if old is not None:check(all(payload[key] == old[key] for key in fixed), "task_definition_immutable")
            if payload["job_ids"]:
                actual = [plans[job] for job in payload["job_ids"] if job in plans]
                check(len(actual) == len(payload["job_ids"]) and all(plan["candidate_id"] == payload["input_candidate_id"] and plan["purpose"] == "discovery" for plan in actual), "task_owned_frozen_discovery_jobs")
                designs = [{key: plan["plan"]["action"][key] for key in ("stage", "site", "assortment", "n")} for plan in actual]
                check(designs == payload["frozen_designs"][:len(designs)], "task_execution_matches_frozen_batch")
            if payload["status"] == "completed":
                check(not closed, "no_task_completion_after_decisions_close")
                artifact = payload["artifact"] or {};owned = set(payload["job_ids"])
                rows = [row for row in latest.values() if row["job_id"] in owned and row["verified_supply"] and row["verified_meter"]]
                check(len(rows) == len(owned) == len(payload["frozen_designs"]), "task_all_owned_receipts_verified")
                check(artifact.get("owned_experiment_ids") == sorted(row["experiment_id"] for row in rows) and artifact.get("owned_measurement_snapshot_sha256") == digest(rows), "task_artifact_actual_measurement_versions")
                candidate = candidates.get(artifact.get("best_candidate_id"), {})
                check(candidate.get("training_evidence_ids") == artifact.get("training_evidence_ids") and set(artifact.get("owned_experiment_ids", [])) <= set(candidate.get("training_evidence_ids", [])), "task_actual_fitted_candidate")
                check(artifact.get("independent_support") is False, "task_fitting_not_independent_support")
            else:check(payload["artifact"] is None, "unfinished_task_has_no_completed_artifact")
            tasks[tid] = copy.deepcopy(payload)
    check(list(tasks.values()) == board["tasks"], "task_snapshot_matches_append_versions")
    return {"passed": not issues, "enabled": True, "registered": len(tasks), "completed": sum(task["status"] == "completed" for task in tasks.values()),
        "states": {tid: task["status"] for tid, task in tasks.items()}, "issues": issues}
