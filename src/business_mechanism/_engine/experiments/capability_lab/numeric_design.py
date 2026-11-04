"""Regularized greedy log-determinant design on the public full grammar.

This is a linear design surrogate, not true binomial EIG or a calibrated posterior.
It exposes unknown grammar directions even when fitted programs agree.
"""
import itertools
import math

import numpy as np

from lab import VARIABLES,compile_expression,evaluate,predict
from symbolic import features,grammar,public_dictionary
import json


def logdet_gain(matrix,row):
    return math.log1p(float(row@np.linalg.solve(matrix,row)))


def plan_dopt(lab,model,public_dedup=False,interaction_order=3):
    patterns=model["role_patterns"]
    variables=VARIABLES|(set(patterns)-{"heating","utensils"})
    if public_dedup:
        catalogs={stage:lab.public_catalog(stage) for stage in (["source","adaptation"] if lab.transfer_open else ["source"])}
        atoms=public_dictionary(json.dumps(patterns,sort_keys=True),json.dumps(catalogs,sort_keys=True),True,interaction_order)
    else:atoms=grammar(patterns,True)
    asts=[compile_expression(atom,variables=variables) for atom in atoms]
    def vector(catalog,arm,site):
        row=features(patterns,catalog,arm,tuple(map(int,site)))
        return [1.0]+[evaluate(ast,row) for ast in asts]
    designs=[];rows=[]
    for stage in (["source","adaptation"] if lab.transfer_open else ["source"]):
        catalog=lab.public_catalog(stage);ids=[p["id"] for p in catalog]
        for site in (["00"] if stage=="source" else ["00","10","01","11"]):
            for flags in itertools.product((0,1),repeat=len(ids)):
                arm=[pid for pid,flag in zip(ids,flags) if flag]
                designs.append((stage,site,arm));rows.append(vector(catalog,arm,site))
    x=np.asarray(rows)
    # Scaling is fixed by the legally offered design space, never by outcomes.
    scale=np.maximum(np.max(np.abs(x),axis=0),1)
    x=x/scale
    info=np.eye(x.shape[1]) # Declared ridge strength 1, not an estimated prior.
    seen=set()
    for r,_ in lab.verified_observations():
        row=np.asarray(vector(lab.public_catalog(r["stage"]),r["assortment"],r["site"]))/scale
        info+=r["n"]/400*np.outer(row,row)
        seen.add((r["stage"],r["site"],tuple(sorted(r["assortment"]))))
    solved=np.linalg.solve(info,x.T).T
    gains=np.log1p(np.einsum("ij,ij->i",x,solved))
    candidates=[]
    for (stage,site,arm),gain in zip(designs,gains):
        cost=5+len(arm)
        if (stage,site,tuple(sorted(arm))) in seen or lab.used["cost"]+cost>lab.limits["cost"]:continue
        candidates.append((float(gain)/cost,float(gain),-cost,stage,site,arm))
    if not candidates:return None
    score,gain,_,stage,site,arm=max(candidates)
    return {"stage":stage,"site":site,"assortment":arm,"n":400,
        "verified_supply":True,"verified_meter":True,
        "prediction":predict(model,lab.public_catalog(stage),arm,tuple(map(int,site))),
        "rationale":"按公开完整语法的正则化线性信息矩阵，贪心最大化每成本 log-det 增益；不是生成器真值或 EIG。",
        "design_diagnostics":{"criterion":"regularized_linear_logdet_per_cost",
            "score":score,"logdet_gain":gain,"ridge_strength":1,"basis_dimension":x.shape[1],"cost":5+len(arm)}}
