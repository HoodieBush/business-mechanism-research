"""Frozen cycle endpoint plus task artifacts; no private-score-based selection."""
import json
from pathlib import Path

from analyze_reference_loop import analyze as analyze_cycles
from audit_discovery_tasks import audit as task_audit


def analyze(folder):
    report = analyze_cycles(folder)
    for row in report["records"]:
        if not row["available"]:continue
        run = json.loads((folder / row["file"]).read_text())
        row["task_audit"] = task_audit(run)
        row["audit_passed"] = row.get("audit_passed", False) and row["task_audit"]["passed"]
        row["model_chose_frontier_actions"] = sum(action["tool"] in {"sample_frontier", "start_discovery_task"}
            for record in run["model_calls"] for action in record.get("actions", []))
        row["task_artifacts"] = [{"task_id": task["task_id"], "status": task["status"], "objective": task["objective"],
            "owner_context_id": task["owner_context_id"], "batch_conditions": len(task["frozen_designs"]), "artifact": task["artifact"]}
            for task in run["research"].get("discovery_tasks", {}).get("tasks", [])]
    report["all_audits_passed"] = all(row.get("audit_passed", False) for row in report["records"])
    report["aggregation_implementation_timing"] = "before_launch"
    report["limitations"] = "One new seed/two development worlds. Task interface and bounded worker are the component; all share original physical/statistical services. Actual samples/API differ; no formal method effect, structural holdout, durable recovery or complete multiagent claim."
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser();parser.add_argument("folder", type=Path);args = parser.parse_args()
    report = analyze(args.folder)
    with (args.folder / "analysis-discovery-tasks.json").open("x") as handle:handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"planned": report["planned"], "all_audits_passed": report["all_audits_passed"], "usage": report["usage"]}, ensure_ascii=False))
