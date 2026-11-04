"""Task-level development summaries, paired intervals, and frozen checkpoints."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import copy
import json
from pathlib import Path
import statistics

import numpy as np

from lab import ResearchLab,World,private_score


def average(values):
    return statistics.mean(values) if values else None


def bootstrap_mean(values):
    if not values:return None
    x=np.array(values);rng=np.random.default_rng(20261012)
    means=x[rng.integers(0,len(x),(10000,len(x)))].mean(axis=1)
    return [float(v) for v in np.quantile(means,[.025,.975])]


def read_runs(directory):
    runs=[json.loads(p.read_text()) for p in sorted(Path(directory).glob('*.json'))
            if p.name not in {"manifest.json","analysis.json","quality_curve.json"}]
    manifest=Path(directory)/"manifest.json"
    if manifest.exists():
        planned=json.loads(manifest.read_text()).get("planned_tasks",[])
        present={(r["private_configuration"]["seed"],r["private_configuration"]["family"],
                  r["private_configuration"]["fault"],r["strategy"]) for r in runs}
        for task in planned:
            if (task["seed"],task["family"],task["fault"],task["strategy"]) not in present:
                runs.append({"status":"missing_result","strategy":task["strategy"],
                    "private_configuration":{k:task[k] for k in ("seed","family","fault")}})
    return runs


def summarize(runs):
    groups=defaultdict(list)
    for r in runs:
        groups[(r["private_configuration"]["family"],r["strategy"])].append(r)
    output=[]
    for (family,strategy),rows in sorted(groups.items()):
        complete=[r for r in rows if r["status"]=="finished"]
        output.append({"family":family,"strategy":strategy,"total":len(rows),
            "status_counts":dict(Counter(r["status"] for r in rows)),
            "finished":len(complete),
            "identification_pass":sum(r["private_score"]["operational_identification_pass_5pp"] for r in complete),
            "heldout_effect_rmse_conditional_on_finished":average([r["private_score"]["heldout_effect_rmse"] for r in complete]),
            "mean_sessions":average([r["private_score"]["used"]["sessions"] for r in complete]),
            "mean_cost":average([r["private_score"]["used"]["cost"] for r in complete])})
    return output


def paired(runs,reference="hybrid_frontier"):
    groups=defaultdict(dict)
    for r in runs:
        c=r["private_configuration"]
        groups[(c["family"],c["seed"],c["fault"])][r["strategy"]]=r
    comparisons=defaultdict(list);missing=Counter()
    for (family,seed,fault),methods in groups.items():
        for strategy,row in methods.items():
            if strategy==reference:continue
            baseline=methods.get(reference)
            if not baseline or row["status"]!="finished" or baseline["status"]!="finished":
                missing[(family,strategy)]+=1;continue
            comparisons[(family,strategy)].append({"seed":seed,"fault":fault,
                "difference":baseline["private_score"]["heldout_effect_rmse"]-row["private_score"]["heldout_effect_rmse"]})
    output=[]
    for key in sorted(set(comparisons)|set(missing)):
        rows=comparisons[key];clusters=defaultdict(list)
        for r in rows:clusters[r["seed"]].append(r["difference"])
        values=[average(v) for v in clusters.values()]
        output.append({"family":key[0],"reference":reference,"comparator":key[1],
            "paired_tasks":len(rows),"seed_clusters":len(values),"missing_or_failed_pairs":missing[key],
            "mean_reference_minus_comparator":average(values),
            "seed_cluster_percentile_bootstrap_95":bootstrap_mean(values),
            "note":"开发描述性区间；每类仅四个种子，不用于显著性/样本量结论。"})
    return output


def quality_curve(runs):
    points=[]
    for r in runs:
        if r["status"]!="finished":continue
        experiments=[e for e in r["events"] if e["request"]["tool"]=="experiment"]
        for version in r["research_versions"]:
            ids=set(version["evidence_ids"])
            seen=[e for e in experiments if e["response"]["experiment_id"] in ids]
            evaluator=ResearchLab(World(**r["private_configuration"]),max_cost=112)
            evaluator.receipts=[{"result":copy.deepcopy(e["response"])} for e in seen]
            evaluator.used=copy.deepcopy(seen[-1]["used"])
            evaluator.call("finish",{"model":copy.deepcopy(version["selected_model"]["model"]),
                "claims":"运行中已冻结的候选版本，运行结束后离线评价；结果不反馈给被测方法。"})
            points.append({**r["private_configuration"],"strategy":r["strategy"],
                "arms":len(seen),"sessions":evaluator.used["sessions"],"cost":evaluator.used["cost"],
                "heldout_effect_rmse":private_score(evaluator)["heldout_effect_rmse"]})
    common=[]
    for family in sorted({p["family"] for p in points}):
        for strategy in sorted({p["strategy"] for p in points}):
            rows=[p for p in points if p["family"]==family and p["strategy"]==strategy and p["arms"]==14]
            common.append({"family":family,"strategy":strategy,"checkpoint_arms":14,
                "tasks":len(rows),"mean_sessions":average([p["sessions"] for p in rows]),
                "mean_cost":average([p["cost"] for p in rows]),
                "mean_heldout_effect_rmse":average([p["heldout_effect_rmse"] for p in rows])})
    return {"phase":"post_hoc_development_checkpoints","points":points,"common_14_arm_checkpoint":common,
        "note":"14 臂是看到开发运行预算后选择的共同比较点；正式终点必须事先冻结。"}


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);ap.add_argument("--quality-curve",action="store_true")
    args=ap.parse_args();runs=read_runs(args.directory)
    report={"phase":"development_not_blind_test","total_observed":sum(r["status"]!="missing_result" for r in runs),
        "total_in_denominator":len(runs),"missing_results":sum(r["status"]=="missing_result" for r in runs),
        "summary":summarize(runs),"paired_comparisons":paired(runs),
        "denominator_note":"完成条件均值与失败分母分别保存；不以零误差填补失败。"}
    manifest=args.directory/"manifest.json"
    if manifest.exists():report["expected_runs"]=json.loads(manifest.read_text()).get("expected_runs")
    (args.directory/"analysis.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    if args.quality_curve:
        (args.directory/"quality_curve.json").write_text(json.dumps(quality_curve(runs),ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"runs":len(runs),"groups":len(report["summary"]),"analysis":str(args.directory/"analysis.json")}),flush=True)
