"""Preregistered model-visible feedback endpoint and public analysis opportunities."""
import hashlib
import json
from pathlib import Path

from analyze_reference_loop import analyze as analyze_cycles
from confirmation_phase import from_events
from public_context import unpack


def opportunities(run):
    rows=[]
    for index,record in enumerate(run["model_calls"]):
        prefix=run["research"]["events"][:record["public_research_event_count"]]
        projection=from_events(prefix,record["clock"])
        ready=[check for check in projection["checks"] if check["analysis_phase"]=="ready_to_assess"]
        explicit=any(feedback.get("ok") and (action["tool"] in {"assess_checks","confirm_and_analyze"} or action["tool"]=="collect" and action["args"]["assess"])
            for action,feedback in zip(record.get("actions",[]),record.get("tool_feedbacks",[])))
        finish_ids={action["args"]["candidate_id"] for action in record.get("actions",[]) if action["tool"]=="finish"}
        rows.append({"request_number":index+1,"ready_check_ids":[check["check_id"] for check in ready],
            "explicit_analysis_action_executed":explicit,"finish_with_ready_final_candidate_check_ids":[check["check_id"] for check in ready if check["candidate_id"] in finish_ids]})
    return rows


def analyze(folder):
    report=analyze_cycles(folder)
    for row in report["records"]:
        if not row["available"] or row["status"]=="execution_failure":continue
        run=json.loads((folder/row["file"]).read_text());cycle=row["cycle"]
        row["primary_model_visible_feedback_cycle"]=None if row["strategy"]=="numeric_full" else bool(cycle["completed"] and cycle["check_feedback_visible_before_finish_request"])
        traces=opportunities(run);row["public_analysis_opportunities"]=traces
        row["ready_analysis_requests"]=sum(bool(trace["ready_check_ids"]) for trace in traces)
        row["explicit_analysis_at_ready_requests"]=sum(bool(trace["ready_check_ids"]) and trace["explicit_analysis_action_executed"] for trace in traces)
        row["finish_requests_with_ready_unanalysed_final_candidate"]=sum(bool(trace["finish_with_ready_final_candidate_check_ids"]) for trace in traces)
    report["aggregation_implementation_timing"]="before_launch"
    report["analysis_source_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["limitations"]="One new seed/two development worlds. Projection plus field definitions is the component, no new tools or statistical permissions. Finish-internal analysis is excluded from the primary model-visible-feedback endpoint. Opportunity counts are descriptive, actual budgets differ; no causal method effect, structure holdout, complete multiagent, durable recovery or dynamic-inventory claim."
    return report


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("folder",type=Path);args=parser.parse_args();report=analyze(args.folder)
    with (args.folder/"analysis-confirmation-phase.json").open("x") as handle:handle.write(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"planned":report["planned"],"all_audits_passed":report["all_audits_passed"],"usage":report["usage"]},ensure_ascii=False))
