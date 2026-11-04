"""Finite discovery tasks over the original public runtime and shared ledger.

Workers execute only a frozen batch. They neither release confirmation data nor
select further experiments, and this in-process board is not durable recovery.
"""
import copy
import time

from temporal_lab import digest

VERSION = "discovery-tasks-v0.1-frozen-public-frontier-batch"
SERVICES = {"start_discovery_task", "advance_discovery_task"}
CONTRACT = {"version": VERSION, "design_method": "existing_public_committee_novelty_frontier",
    "batch_conditions": [1, 3], "worker_max_steps": 100, "execution_attempts_max": 2,
    "new_environment_or_budget": False, "independent_support_created": False,
    "start_scientific_action_charge": 3, "advance_scientific_action_charge": 2,
    "fit_only_when_all_owned_receipts_verified_and_decisions_open": True,
    "persistent_across_processes": False}


class DiscoveryTasks:
    def __init__(self):self.tasks = {}

    def _save(self, rt, task, **updates):
        value = copy.deepcopy(task);value.update(updates)
        value["version"] = task.get("version", 0) + 1
        value["previous_version_sha256"] = digest(task) if task.get("version") else None
        value["available_at"] = rt.gateway.clock
        self.tasks[value["task_id"]] = value
        rt._event("discovery_task_registered" if value["version"] == 1 else "discovery_task_updated", value)
        return value

    def start(self, rt, args):
        if any(task["status"] not in {"completed", "submission_failed", "closed_unresolved", "deadline_unresolved"} for task in self.tasks.values()):
            raise ValueError("advance the existing unfinished discovery task before starting another")
        if rt.calls + 2 >= rt.max_calls:raise ValueError("task needs two inner scientific actions and a finish reserve")
        designs = rt._frontier_designs(args["candidate_id"], args["count"])
        rt._validate_sampling_batch(args["candidate_id"], designs, args["rationale"])
        if rt.gateway.tool_calls + 2 * len(designs) + 1 > rt.gateway.limits["tool_calls"] - 2:
            raise ValueError("insufficient launch/receipt gateway allocation with terminal reserve")
        candidate = rt.registry[args["candidate_id"]]
        task = self._save(rt, {"task_id": f"D{len(self.tasks):04d}", "version": 0,
            "owner_context_id": rt.organization.current if rt.organization is not None else "single_coordinator",
            "objective": args["objective"], "rationale": args["rationale"], "status": "registered",
            "input_candidate_id": args["candidate_id"], "input_candidate_sha256": candidate["content_hash"],
            "input_model_sha256": digest(candidate["model"]), "input_training_ids": candidate["training_evidence_ids"],
            "input_public_prefix_sha256": rt.events[-1]["event_hash"],
            "design_method": CONTRACT["design_method"], "frozen_designs": designs,
            "shared_limits_sha256": digest(rt.gateway.limits), "job_ids": [], "artifact": None})
        before_jobs = set(rt.jobs)
        submitted = rt.call("sample", {"candidate_id": args["candidate_id"], "designs": designs, "rationale": args["rationale"]})
        task = self._save(rt, task, job_ids=sorted(set(rt.jobs) - before_jobs),
            status="awaiting_receipts" if submitted["ok"] else "submission_failed",
            submission_error=None if submitted["ok"] else submitted["error"])
        if submitted["ok"]:task = self._work(rt, task, args["repair"])
        return copy.deepcopy(task)

    def advance(self, rt, args):
        task = self.tasks[args["task_id"]]
        if task["status"] == "completed":return copy.deepcopy(task)
        if task["status"] == "submission_failed":raise ValueError("partial submission is retained as failed; no automatic new plans")
        if rt.calls + 1 >= rt.max_calls:raise ValueError("worker needs one scientific action and a finish reserve")
        return copy.deepcopy(self._work(rt, task, args["repair"]))

    def _work(self, rt, task, repair):
        if rt.closed or rt.decisions_closed:raise ValueError("no task worker fitting after decision closure")
        rt.calls += 1;started = time.monotonic();used_before = copy.deepcopy(rt.gateway.used);trace = []
        owned = set(task["job_ids"]);gateway = rt.gateway
        def state():
            public = gateway.public_state()
            return {key: [job for job in public[key] if job["job_id"] in owned]
                    for key in ("pending_jobs", "failed_jobs", "unverified_jobs")}
        def call(tool, arguments):
            if gateway.tool_calls >= gateway.limits["tool_calls"] - 2:return False
            response = gateway.call(tool, arguments)
            trace.append({"tool": tool, "args": copy.deepcopy(arguments), "response": copy.deepcopy(response)})
            rt._sync();return True
        reason = "owned_receipts_complete"
        try:
            for _ in range(CONTRACT["worker_max_steps"]):
                current = state()
                if not any(current.values()):break
                if gateway.clock >= gateway.deadline:reason = "calendar_deadline";break
                progress = False
                if repair:
                    for job in current["failed_jobs"]:
                        d = job["plan"]["action"];used = gateway.used
                        slots = gateway.max_pending - sum(j["status"] == "pending" for j in gateway.public_state()["pending_jobs"])
                        if job["attempts"] < 2 and slots and used["sessions"] + d["n"] <= gateway.limits["sessions"] and used["arms"] + 1 <= gateway.limits["arms"] and used["cost"] + 5 + len(d["assortment"]) <= gateway.limits["cost"]:
                            progress = call("retry_execution", {"job_id": job["job_id"]}) or progress
                    for job in state()["unverified_jobs"]:
                        if gateway.used["cost"] < gateway.limits["cost"]:progress = call("reconcile_measurement", {"job_id": job["job_id"]}) or progress
                if state()["pending_jobs"]:progress = call("await_next", {}) or progress
                if not progress:reason = "repair_or_resources_required";break
            else:reason = "bounded_worker_steps"
            rt._sync();current = state()
            receipts = [row for row in gateway.public_state()["mature_evidence"] if row["job_id"] in owned and row["verified_supply"] and row["verified_meter"]]
            complete = len(receipts) == len(owned) == len(task["frozen_designs"])
            fit = rt._fit() if complete else None
            status = "completed" if complete else "deadline_unresolved" if gateway.clock >= gateway.deadline else "needs_repair" if current["failed_jobs"] or current["unverified_jobs"] else "awaiting_receipts"
            artifact = None if fit is None else {"owned_experiment_ids": sorted(row["experiment_id"] for row in receipts),
                "owned_measurement_snapshot_sha256": digest(receipts), "training_evidence_ids": fit["training_evidence_ids"],
                "candidate_ids": rt.pool[:6], "best_candidate_id": rt.pool[0],
                "owned_unique_conditions": len({(row["stage"], row["site"], tuple(sorted(row["assortment"]))) for row in receipts}),
                "independent_support": False, "unresolved_scope": "new candidate requires fresh independent checks; untested conditions remain unresolved"}
            task = self._save(rt, task, status=status, worker_reason=reason, artifact=artifact)
            feedback = {"ok": True, "result": {"task_id": task["task_id"], "status": status, "trace": trace, "parameter_fit_performed": fit is not None}}
        except (ValueError, KeyError, TypeError) as error:
            task = self._save(rt, task, status="worker_error", worker_error=type(error).__name__ + ": " + str(error))
            feedback = {"ok": False, "error": task["worker_error"], "trace": trace}
        rt._event("scientific_tool_response", {"request": {"tool": "discovery_task_worker", "args": {"task_id": task["task_id"], "repair": repair},
            "rationale": "执行原冻结发现批次。", "expected_gap": "取得可追踪回执和共同拟合产物，不产生独立认证。"},
            "feedback": feedback, "used_before": used_before, "used_after": copy.deepcopy(gateway.used), "wall_seconds": time.monotonic() - started})
        return task

    def close(self, rt):
        for task in list(self.tasks.values()):
            if task["status"] not in {"completed", "submission_failed", "closed_unresolved", "deadline_unresolved"}:
                self._save(rt, task, status="closed_unresolved", worker_reason="decisions_closed_before_task_artifact")

    def view(self):return {"contract": copy.deepcopy(CONTRACT), "tasks": copy.deepcopy(list(self.tasks.values()))}
