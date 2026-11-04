"""Task-cluster power planning, never a post-hoc significance claim.

Normal paired differences are an explicit design assumption. Small development
samples motivate variance sensitivity scenarios, not a definitive sample size.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

from scipy.stats import nct,t

from analyze_openworld import key,read_runs


def normal_paired_power(delta,sd,n,alpha=.05):
    if n<2 or sd<=0 or not 0<alpha<1:raise ValueError("invalid power scenario")
    cutoff=t.ppf(1-alpha/2,n-1);noncentrality=n**.5*delta/sd
    return float(nct.sf(cutoff,n-1,noncentrality)+nct.cdf(-cutoff,n-1,noncentrality))


def paired_clusters(rows,method_a,method_b,failure_loss=2.):
    indexed={key(r):r for r in rows};contexts=sorted({key(r)[:-1] for r in rows})
    clusters=defaultdict(list);failed=0
    for context in contexts:
        a=indexed.get(context+(method_a,));b=indexed.get(context+(method_b,))
        if a is None or b is None:raise ValueError("both methods must be declared in every cluster context")
        def loss(row):
            nonlocal failed
            if row["status"]!="finished":failed+=1;return failure_loss
            value=row["private_score"]["heldout_effect_rmse"]
            if not 0<=value<=2:raise ValueError("effect RMSE outside probability-difference bound")
            return value
        clusters[context[0]].append(loss(a)-loss(b))
    values=[{"seed":seed,"contexts":len(v),"mean_a_minus_b":statistics.mean(v)} for seed,v in sorted(clusters.items())]
    return {"method_a":method_a,"method_b":method_b,"failure_loss":failure_loss,"failed_or_missing_method_runs":failed,
        "seed_clusters":values,"cluster_count":len(values),
        "development_sd":statistics.stdev(r["mean_a_minus_b"] for r in values) if len(values)>1 else None,
        "estimand":"每个种子内对所有已声明家族/条件等权平均，再在种子簇间比较。失败以理论最坏效应误差 2 计；原始失败分母另保留。"}


def plan(rows,method_a,method_b,comparisons=2):
    paired=paired_clusters(rows,method_a,method_b)
    alpha=.05/comparisons
    sds=sorted(set([.02,.05,.1,.2]+([paired["development_sd"]] if paired["development_sd"] else [])))
    scenarios=[]
    for delta in (.01,.02,.05):
        for sd in sds:
            sizes=(8,16,32,64,128,256,512)
            powers=[{"seed_clusters":n,"power":normal_paired_power(delta,sd,n,alpha)} for n in sizes]
            scenarios.append({"assumed_improvement":delta,"assumed_cluster_sd":sd,"per_comparison_alpha":alpha,
                "power_grid":powers,"first_grid_size_with_at_least_80pct":next((r["seed_clusters"] for r in powers if r["power"]>=.8),None)})
    return {"phase":"development_power_planning_not_preregistered","paired_development_summary":paired,
        "candidate_primary_comparisons":comparisons,"familywise_alpha":.05,"scenarios":scenarios,
        "assumptions":["独立种子簇、配对差异近似正态；家族和方法重复不作为独立样本。",
            "改善 1/2/5pp 是待冻结的设计情景，不能由本次最优结果反推主要效应。",
            "开发期方差仅作敏感性输入；少量种子不能提供可靠总体方差。",
            "最终任务结构、方法或失败分布变化时须重新做开发功效；不在正式结果打开后追改。"],
        "not_established":["正式所需样本数","非正态稳健推断的实际功效","未出现关系组合的方差与服务漂移"]}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directory",type=Path)
    parser.add_argument("--method-a",required=True);parser.add_argument("--method-b",required=True)
    parser.add_argument("--comparisons",type=int,default=2)
    args=parser.parse_args()
    if args.comparisons<1:parser.error("comparisons must be positive")
    result=plan(read_runs(args.directory),args.method_a,args.method_b,args.comparisons)
    (args.directory/"task-power-planning.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result["paired_development_summary"],ensure_ascii=False))
