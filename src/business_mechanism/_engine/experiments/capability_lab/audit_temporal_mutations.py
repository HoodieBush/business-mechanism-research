"""After-run audit challenge checks; no new outcomes or independent samples."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from audit_temporal import audit


def challenge(run):
    checks=[]
    def apply(name,mutate):
        changed=copy.deepcopy(run);mutate(changed);report=audit(changed)
        checks.append({"name":name,"caught":not report["passed"],"failures":report["failures"]})
    def find(r,kind):return next(e for e in r["events"] if e["kind"]==kind)
    def leak_ack(r):
        e=next(e for e in r["events"] if e.get("request",{}).get("tool")=="submit_experiment" and e["kind"]=="tool_response" and e["payload"]["status"]=="pending")
        e["payload"]["observed_sales"]=333
    apply("future_count_in_launch_ack",leak_ack)
    apply("future_availability_in_receipt",lambda r:find(r,"measurement_received")["payload"].__setitem__("available_at",r["used"]["logical_time"]+1))
    apply("future_id_in_fit",lambda r:find(r,"public_fit_snapshot")["payload"]["training_evidence_ids"].append(9999))
    def train_check(r):
        c=r["confirmations"][0];v=next(v for v in r["research_versions"] if v["phase"]=="confirmation_model_frozen" and v["round"]==c["round"])
        v["training_evidence_ids"].append(c["experiment_ids"][0])
    apply("own_confirmation_used_for_training",train_check)
    if any(e["kind"]=="measurement_revised" for e in run["events"]):
        apply("repair_claimed_new_cohort",lambda r:find(r,"measurement_revised")["payload"].__setitem__("n",801))
    apply("missing_budget",lambda r:r["used"].__setitem__("sessions",0))
    apply("deployment_relation_changed",lambda r:r["deployed_model"].__setitem__("expression",.9))
    apply("conditional_state_erased_or_changed",lambda r:r["mechanism_card"].__setitem__("state","refuted_in_listed_conditions" if r["mechanism_card"]["state"]!="refuted_in_listed_conditions" else "pending_confirmation"))
    if run["model_calls"]:
        def api_pending(r):
            rec=next(rec for rec in r["model_calls"] if json.loads(rec["request"]["messages"][1]["content"])["pending_jobs"])
            ctx=json.loads(rec["request"]["messages"][1]["content"]);ctx["pending_jobs"][0]["observed_sales"]=333
            rec["request"]["messages"][1]["content"]=json.dumps(ctx,ensure_ascii=False)
        apply("future_count_in_api_pending_context",api_pending)
    return {"original_passed":audit(run)["passed"],"checks":checks,"all_caught":all(c["caught"] for c in checks),
        "scope":"Synthetic after-run trace alterations test audit sensitivity, not live agent abilities or new independent outcomes."}


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("result",type=Path);ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args();report=challenge(json.loads(args.result.read_text()))
    report.update(source_file=str(args.result),source_sha256=hashlib.sha256(args.result.read_bytes()).hexdigest(),
        audit_code_sha256=hashlib.sha256((Path(__file__).parent/"audit_temporal.py").read_bytes()).hexdigest())
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n");print(json.dumps(report,ensure_ascii=False,indent=2))
