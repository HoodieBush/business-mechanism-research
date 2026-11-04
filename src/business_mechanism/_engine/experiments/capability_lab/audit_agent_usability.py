"""Read-only development diagnostics, separate from scientific effectiveness.

Uses saved requests, feedback and public research objects. Never invokes an
agent, simulator, fitter or scorer. Missing planned runs remain in the denominator.
The output is for developers, not a source of evidence for a tested agent.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import median

from public_context import unpack

VERSION = "agent-usability-audit-v0.1-saved-traces"


def size_summary(values):
    return None if not values else {"min": min(values), "median": median(values), "max": max(values)}


def summarize_run(run):
    records = run["model_calls"]
    actions = [action for record in records for action in record.get("actions", [])]
    feedbacks = [feedback for record in records for feedback in record.get("tool_feedbacks", [])]
    errors = []
    contexts = Counter()
    request_bytes = []
    function_counts = []
    empty_assessments = 0
    model_finished = False
    for index, record in enumerate(records):
        request = record["request"]
        request_bytes.append(len(json.dumps(request, ensure_ascii=False).encode()))
        function_counts.append(len(request.get("tools", [])))
        contexts[record.get("organization_context_id", "unspecified")] += 1
        if "submission_error" in record:
            errors.append({"request_index": index, "category": "submission_protocol",
                           "error": record["submission_error"]})
        for action, feedback in zip(record.get("actions", []), record.get("tool_feedbacks", [])):
            if action["tool"] == "finish" and feedback.get("ok"):
                model_finished = True
            if not feedback.get("ok"):
                category = "public_precondition" if feedback.get("public_precondition_rejected") else "tool_failure"
                errors.append({"request_index": index, "category": category,
                               "tool": action["tool"], "error": feedback.get("error")})
        for review in record.get("public_precondition_reviews", []):
            # A legal empty analysis is a scheduling signal, not a scientific error.
            if review["accepted"] and review["action"]["tool"] == "assess_checks":
                empty_assessments += not any(check["state"] is None for check in review["state"]["checks"])
    organization = run["research"].get("research_organization", {})
    children = [context for context in organization.get("contexts", []) if context["parent_id"] is not None]
    checks = run["research"]["checks"]
    outcomes = Counter(check["result"]["state"] if check.get("result") else "unresolved" for check in checks)
    protocol_errors = sum("submission_error" in record for record in records)
    precondition_errors = sum(bool(feedback.get("public_precondition_rejected")) for feedback in feedbacks)
    preflight = run.get("api_stop_preflight")
    last_visible_checks = None
    if records:
        state = unpack(json.loads(records[-1]["request"]["messages"][-1]["content"]))["research_state"]
        last_visible_checks = dict(Counter(check["state"] or "unresolved" for check in state["checks"]))
    return {
        "strategy": run["strategy"], "status": run["status"],
        "api_requests": len(records), "protocol_error_requests": protocol_errors,
        "decoded_actions": len(actions), "feedback_count": len(feedbacks),
        "tool_successes": sum(bool(feedback.get("ok")) for feedback in feedbacks),
        "tool_failures": sum(not feedback.get("ok", False) for feedback in feedbacks),
        "public_precondition_rejections": precondition_errors,
        "feedback_action_count_matches": all(len(record.get("actions", [])) == len(record.get("tool_feedbacks", [])) for record in records),
        "error_details": errors, "tool_choices": dict(Counter(action["tool"] for action in actions)),
        "queried_contexts": dict(contexts), "child_branches_created": len(children),
        "child_branches_queried": sum(context["context_id"] in contexts for context in children),
        "accepted_assessments_without_unassessed_checks": empty_assessments,
        "request_serialized_bytes": size_summary(request_bytes),
        "exposed_function_counts": size_summary(function_counts),
        "model_requested_successful_finish": model_finished,
        "runner_terminal_fallback": "terminal_fallback" in run,
        "registered_checks": len(checks), "archived_check_outcomes": dict(outcomes),
        "check_states_visible_before_last_request": last_visible_checks,
        "final_card_state": run.get("mechanism_card", {}).get("state"),
        "coordinator_stop_reason": run.get("coordinator_stop_reason"),
        "reported_tokens": run.get("model_usage", {}).get("total_tokens", 0),
        "admission_at_stop": None if preflight is None else {
            "calls_left": preflight["calls_left"], "reported_tokens_left": preflight["tokens_left"],
            "byte_plus_output_heuristic": preflight["next_request_byte_plus_output_bound"],
            "tokenizer_verified": False},
        "interpretation": "Checks may include declared terminal receipt settlement; archived support is not autonomous task completion. Tool success is not scientific success."
    }


def analyze(folder):
    folder = Path(folder)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    rows = []
    for task in manifest["planned_tasks"]:
        name = f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json"
        path = folder / name
        if not path.exists():
            rows.append({"file": name, "available": False, "issue": "planned_run_missing"})
            continue
        content = path.read_bytes()
        row = summarize_run(json.loads(content))
        rows.append({"file": name, "available": True, "source_sha256": hashlib.sha256(content).hexdigest(), **row})
    available = [row for row in rows if row["available"]]
    llm = [row for row in available if row["api_requests"]]
    return {
        "version": VERSION, "study_scope": "stage_0_retrospective_development_diagnostics",
        "source_phase": folder.name, "planned_runs": len(rows), "available_runs": len(available),
        "missing_runs": len(rows) - len(available), "llm_runs": len(llm),
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "totals": {key: sum(row[key] for row in llm) for key in (
            "api_requests", "protocol_error_requests", "decoded_actions", "tool_successes",
            "tool_failures", "public_precondition_rejections", "reported_tokens")},
        "records": rows, "new_api_calls": 0, "new_measurements": 0,
        "independent_new_tasks": 0, "scientific_performance_claim": False,
        "limitations": "Correlated development traces; no causal attribution of failures, no state-recovery test, no new agent behavior or efficacy result."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.folder)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # An existing report must not silently be replaced.
    with args.output.open("x") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("planned_runs", "available_runs", "missing_runs", "totals")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
