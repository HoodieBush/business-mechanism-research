"""Aggregate the preregistered cycle endpoint and separate scientific/business results."""
import argparse
import hashlib
import json
from pathlib import Path

from audit_scientific import audit as science_audit
from audit_organization import audit as organization_audit
from model_protocol import usage_summary
from public_context import unpack
from run_organization import filename


def cycle(run):
    final = run.get("research", {}).get("final")
    if final is None:return {"completed": False, "reason": "no_final_object"}
    cid = final["candidate_id"]
    candidate = next(candidate for candidate in run["research"]["objects"]["candidates"] if candidate["candidate_id"] == cid)
    close = next(event for event in run["research"]["events"] if event["kind"] == "research_decisions_closed")
    analyses = [event for event in run["research"]["events"] if event["kind"] == "independent_check_assessed"
                and event["payload"]["candidate_id"] == cid and event["sequence"] < close["sequence"]]
    finish_records = [record for record in run["model_calls"] if any(action["tool"] == "finish" and feedback.get("ok")
                     for action, feedback in zip(record.get("actions", []), record.get("tool_feedbacks", [])))]
    observed = False
    for record in finish_records:
        state = unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
        observed |= any(check["candidate_id"] == cid and check["state"] is not None for check in state["checks"])
    completed = bool(candidate["training_evidence_ids"] and analyses and finish_records and "terminal_fallback" not in run)
    return {"completed": completed, "final_candidate_id": cid, "target_training_ids": candidate["training_evidence_ids"],
            "checks_of_final_candidate_assessed_before_decision_close": len(analyses),
            "check_outcomes_before_close": [event["payload"]["result"]["state"] for event in analyses],
            "model_chose_finish": bool(finish_records), "runner_fallback": "terminal_fallback" in run,
            "check_feedback_visible_before_finish_request": observed,
            "interpretation": "Research-cycle completion includes negative/inconclusive results and does not establish correct mechanisms or business advantage."}


def analyze(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    rows = []
    calls = []
    for task in manifest["planned_tasks"]:
        path = folder / filename(task)
        if not path.exists():
            rows.append({"file": path.name, "available": False, "issue": "planned_run_missing"})
            continue
        run = json.loads(path.read_text())
        calls.extend(run["model_calls"])
        row = {"file": path.name, "available": True, "strategy": run["strategy"], "status": run["status"],
               "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "used": run["used"], "usage": run["model_usage"]}
        if run["status"] == "execution_failure":
            rows.append({**row, "audit_passed": False, "error": run["error"]})
            continue
        science = science_audit(run); organization = organization_audit(run)
        row.update(audit_passed=science["passed"] and organization["passed"], scientific_audit=science,
                   organization_audit=organization, cycle=cycle(run), card_state=run["mechanism_card"]["state"],
                   checks=[{"check_id": check["check_id"], "candidate_id": check["candidate_id"],
                            "state": None if check["result"] is None else check["result"]["state"]} for check in run["research"]["checks"]],
                   protocol_errors=sum("submission_error" in record for record in run["model_calls"]),
                   rejected_actions=sum(not feedback.get("ok", False) for record in run["model_calls"] for feedback in record.get("tool_feedbacks", [])),
                   effect_rmse=run["private_score"]["heldout_effect_rmse"],
                   operating_regret=run["private_score"]["mean_expected_operating_regret_per_customer"],
                   elapsed_seconds=run["elapsed_seconds"], stop_reason=run.get("coordinator_stop_reason"))
        rows.append(row)
    usage = usage_summary(calls)
    return {"phase": folder.name, "planned": len(manifest["planned_tasks"]), "records": rows,
            "usage": usage, "round_budget": manifest["specification"]["round_reported_token_budget"],
            "under_round_budget": usage["total_tokens"] <= manifest["specification"]["round_reported_token_budget"],
            "all_audits_passed": all(row.get("audit_passed", False) for row in rows),
            "analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "primary_endpoint_definition": manifest["specification"]["primary_endpoint"],
            "aggregation_implementation_timing": "during_development_run; scientific auditing and operating evaluator were frozen before launch",
            "formal_effect_established": False, "full_goal_completed": False,
            "limitations": "One seed/two latent development worlds; actual samples and API use differ. No structural holdout, durable recovery, dynamic inventory or complete ABC. No inferential method-effect claim."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser();parser.add_argument("folder", type=Path);args = parser.parse_args()
    report = analyze(args.folder)
    with (args.folder / "analysis-reference-loop.json").open("x") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"planned": report["planned"], "all_audits_passed": report["all_audits_passed"], "usage": report["usage"]}, ensure_ascii=False))
