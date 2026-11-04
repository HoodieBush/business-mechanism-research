"""Independent public event audit of original-ledger workflow wakeups."""
import copy
import json
from pathlib import Path

from audit_scientific import audit as scientific_audit
from temporal_lab import digest


def audit_queue(run):
    issues = []
    def check(ok, name):
        if not ok:
            issues.append(name)
    queue = run["research_queue"]; research = run["research"]; gateway = run["gateway_events"]
    contract = queue["contract"]; check(contract == run["legal_input"]["research_workflow_contract"], "queue_contract_not_rewritten")
    check(contract["worker_api_calls"] == 0 and contract["worker_parameter_refits"] == 0 and contract["worker_new_plans"] == 0 and not contract["budget_reset_on_wakeup"], "queue_worker_restrictions")
    statuses = {}; waiting = {}; wait_prefixes = {}; previous = None
    for index, event in enumerate(queue["events"]):
        body = {k: v for k, v in event.items() if k != "event_hash"}
        check(event["sequence"] == index and event["previous_hash"] == previous and event["event_hash"] == digest(body), "queue_hash_chain")
        previous = event["event_hash"]; cid = event["context_id"]; payload = event["payload"]
        count = event["research_event_count"]; gcount = event["gateway_event_count"]
        prefix = research["events"][:count]; gprefix = gateway[:gcount]
        check(0 < count <= len(research["events"]) and prefix[-1]["event_hash"] == event["research_prefix_hash"], "queue_research_prefix")
        check(0 < gcount <= len(gateway) and digest(gprefix) == event["gateway_prefix_sha256"], "queue_gateway_prefix")
        check(all(e["available_at"] <= event["available_at"] for e in prefix + gprefix), "queue_no_future_prefix")
        def remaining(value):
            calls = sum(e["kind"] == "scientific_tool_response" for e in prefix)
            checks = sum(e["kind"] == "check_frozen_before_execution" for e in prefix)
            revisions = sum(e["kind"] == "confirmation_evidence_released" for e in prefix)
            expected = {"scientific_actions": 64 - calls, "checks": 6 - checks, "revisions": 2 - revisions,
                        "unspent_declared_alpha": (6 - checks) * .05 / 6,
                        "physical": {k: run["legal_input"]["limits"][k] - gprefix[-1]["used"][k] for k in run["used"]}}
            check(value == expected, "queue_remaining_original_ledger")
        if "remaining" in payload:
            remaining(payload["remaining"])
        kind = event["kind"]
        if kind == "context_registered":
            check(cid not in statuses and payload["contract_sha256"] == digest(contract), "queue_registration")
            statuses[cid] = "running"
        elif kind == "context_waiting":
            check(statuses.get(cid) in {"running", "runnable"}, "queue_wait_transition")
            waiting[cid] = copy.deepcopy(payload["job_ids"]); statuses[cid] = "waiting"
            wait_prefixes[cid] = (count, gcount)
            plans = {e["payload"]["job_id"] for e in prefix if e["kind"] == "registered_plan_linked"}
            check(bool(waiting[cid]) and set(waiting[cid]) <= plans, "queue_wait_registered_jobs")
        elif kind == "context_woken":
            check(statuses.get(cid) == "waiting", "queue_wake_transition")
            receipt = payload["receipt"]; remaining(payload["remaining_after"])
            rstart, gstart = wait_prefixes[cid]
            worker_events = research["events"][rstart:count]
            check(not any(e["kind"] in {"candidate_registered", "public_pool_fitted", "registered_plan_linked", "check_frozen_before_execution", "confirmation_evidence_released"} for e in worker_events), "queue_worker_no_decision_events")
            actual_trace = [{"tool": e["request"]["tool"], "args": e["request"]["args"],
                             "response": e["payload"], "available_at": e["available_at"]}
                            for e in gateway[gstart:gcount] if e["kind"] == "tool_response"]
            check(receipt["trace"] == actual_trace, "queue_worker_actual_gateway_trace")
            before = payload["remaining_before"]; after = payload["remaining_after"]
            check(before["checks"] == after["checks"] and before["revisions"] == after["revisions"] and before["unspent_declared_alpha"] == after["unspent_declared_alpha"], "queue_no_alpha_or_revision_reset")
            check(before["scientific_actions"] - after["scientific_actions"] in {0, 1}, "queue_receipt_charge")
            check(payload["research_event_count"] == count and payload["research_prefix_hash"] == event["research_prefix_hash"], "queue_wake_analysis_prefix")
            for step in receipt["trace"]:
                check(step["tool"] in contract["worker_actions"] and step["available_at"] <= event["available_at"], "queue_worker_actions")
                if step["tool"] != "await_next":
                    check(step["args"]["job_id"] in waiting[cid], "queue_worker_committed_jobs")
            if "extra_api_calls" in receipt:
                check(receipt["extra_api_calls"] == receipt["new_designs"] == receipt["new_hypotheses"] == receipt["parameter_refits"] == 0, "queue_worker_no_scientific_search")
            expected_checks = [{"check_id": e["payload"]["check_id"], "candidate_id": e["payload"]["candidate_id"], "state": None}
                               for e in prefix if e["kind"] == "check_frozen_before_execution"]
            assessments = {e["payload"]["check_id"]: e["payload"]["result"]["state"] for e in prefix if e["kind"] == "independent_check_assessed"}
            for c in expected_checks:
                c["state"] = assessments.get(c["check_id"])
            check(payload["checks"] == expected_checks, "queue_actual_frozen_analysis")
        elif kind == "context_runnable":
            check(statuses.get(cid) in {"running", "runnable", "waiting"}, "queue_ready_transition"); statuses[cid] = "runnable"
        elif kind == "context_dispatched":
            check(statuses.get(cid) == "runnable", "queue_dispatch_transition"); statuses[cid] = "running"
        elif kind == "context_terminal":
            check(any(e["kind"] == "research_decisions_closed" for e in prefix), "queue_terminal_after_close"); statuses[cid] = "terminal"
        else:
            check(False, "queue_unknown_event")
    check(all(value == queue["contexts"][cid]["status"] for cid, value in statuses.items()), "queue_final_status")
    limits = run["scientific_protocol"]["api_limits"]
    check(run["model_usage"]["api_calls"] <= limits["calls"] and run["model_usage"]["total_tokens"] <= limits["reported_tokens"], "queue_original_api_allocation")
    for record in run["model_calls"]:
        from public_context import unpack
        state = unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
        context = state["workflow_context"]
        check(context["status"] == "running" and context["contract_sha256"] == digest(contract), "api_only_dispatched_context")
        wake = context["last_wakeup"]
        check(wake is not None and wake["research_event_count"] <= record["public_research_event_count"], "api_after_available_wakeup")
    return {"passed": not issues, "issues": sorted(set(issues))}


def normalize(value):
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in {"cpu_wall_seconds", "wall_seconds", "event_hash", "previous_hash", "research_prefix_hash", "gateway_prefix_sha256"}}
    return value


def analyze(folder):
    folder = Path(folder); manifest = json.loads((folder / "manifest.json").read_text()); records = []
    from run_recovery import filename
    groups = {}
    for task in manifest["planned_tasks"]:
        path = folder / filename(task)
        if not path.exists():
            records.append({"file": path.name, "passed": False, "issues": ["planned_run_missing"]}); continue
        run = json.loads(path.read_text()); science = scientific_audit(run); queue = audit_queue(run)
        records.append({"file": path.name, "passed": science["passed"] and queue["passed"], "scientific": science, "queue": queue,
                        "entry_check_state": run["research"]["checks"][0]["result"]["state"],
                        "checks": len(run["research"]["checks"]), "revisions": run["research"]["revisions"],
                        "card_state": run["mechanism_card"]["state"], "usage": run["model_usage"], "used": run["used"],
                        "effect_rmse": run["private_score"]["heldout_effect_rmse"], "regret": run["private_score"]["mean_expected_operating_regret_per_customer"]})
        key = (task["seed"], task["family"], task["profile"]); groups.setdefault(key, []).append(run)
    comparisons = []
    for key, runs in groups.items():
        prefix = lambda r: normalize({k: r[k] for k in ("entry_research_events", "entry_gateway_events", "entry_used", "entry_candidate_id", "first_wakeup")})
        comparisons.append({"task": list(key), "same_entry_and_wakeup": len(runs) == 3 and all(prefix(r) == prefix(runs[0]) for r in runs[1:])})
    # Prefix SHA values refer to timing-sensitive hashes. Compare their resolved
    # event content above rather than requiring wall-clock measurements to agree.
    result = {"phase": manifest["specification"]["phase"], "records": records, "comparisons": comparisons,
              "passed": all(r["passed"] for r in records) and all(c["same_entry_and_wakeup"] for c in comparisons)}
    (folder / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("folder", type=Path); args = ap.parse_args()
    result = analyze(args.folder); print(json.dumps(result, ensure_ascii=False, indent=2))
