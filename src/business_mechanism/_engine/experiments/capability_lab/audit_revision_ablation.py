"""Verify a same-budget revision ablation differs only after its opportunity."""
import argparse
import json
from pathlib import Path

from analyze_openworld import key,read_runs


def audit_pairs(rows):
    indexed={key(row):row for row in rows};contexts=sorted({key(row)[:-1] for row in rows})
    output=[]
    for context in contexts:
        a=indexed[context+("numeric_full_frontier_once",)];b=indexed[context+("numeric_full_frontier",)]
        issues=[]
        if a["status"]!="finished" or b["status"]!="finished":issues.append("incomplete_pair")
        else:
            if a["legal_input"]!=b["legal_input"]:issues.append("public_input_or_limits_differ")
            cohorts=a["confirmation_protocol"]["cohorts_per_check"]
            prefix=12+4*cohorts
            ea=[e for e in a["events"] if e["request"]["tool"]=="experiment"]
            eb=[e for e in b["events"] if e["request"]["tool"]=="experiment"]
            for left,right in zip(ea[:prefix],eb[:prefix]):
                la=left["request"]["args"];ra=right["request"]["args"]
                if any(la[k]!=ra[k] for k in ("stage","site","assortment","n","verified_supply","verified_meter")):
                    issues.append("pre_opportunity_design_differs")
                if abs(la["prediction"]-ra["prediction"])>1e-9:issues.append("pre_opportunity_prediction_differs")
                if left["response"]!=right["response"]:
                    # Frozen-prediction roundoff is checked above separately.
                    omit=lambda response:{k:v for k,v in response.items() if k not in {"frozen_prediction"}}
                    if omit(left["response"])!=omit(right["response"]):issues.append("pre_opportunity_evidence_differs")
            if len(ea)!=len(eb) or a["used"]["sessions"]!=b["used"]["sessions"]:issues.append("actual_sample_budgets_differ")
            if a["confirmation_protocol"]!=b["confirmation_protocol"]:issues.append("error_rules_differ")
            if a["model_usage"]["api_calls"] or b["model_usage"]["api_calls"]:issues.append("unexpected_API_calls")
        output.append({"task":list(context),"status":"passed" if not issues else "failed","issues":sorted(set(issues)),
            "post_opportunity_design_equality_required":False,
            "note":"第二次修订会改变后续模型与设计；只要求修订机会之前完全同信息、同预测和实际样本预算。操作成本上限相同，实际成本另报。"})
    return output


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directory",type=Path);args=parser.parse_args()
    pairs=audit_pairs(read_runs(args.directory))
    (args.directory/"prefix-audit.json").write_text(json.dumps({"pairs":pairs},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"pairs":len(pairs),"passed":sum(r["status"]=="passed" for r in pairs)}))
    raise SystemExit(0 if all(r["status"]=="passed" for r in pairs) else 1)
