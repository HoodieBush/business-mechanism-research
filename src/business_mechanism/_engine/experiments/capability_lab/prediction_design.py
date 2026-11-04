"""Public-subspace D/I design surrogates invariant to redundant basis columns.

Whitening and the integration domain use public legal inputs, never outcomes or
deployment facts. This is a regularized linear surrogate, not binomial EIG.
"""
import itertools
import json
from functools import lru_cache

import numpy as np

from lab import VARIABLES,compile_expression,evaluate,predict
from symbolic import features,public_dictionary


def whiten(x):
    _,singular,vt=np.linalg.svd(x/np.sqrt(len(x)),full_matrices=False)
    keep=singular>singular[0]*1e-10
    transform=vt[keep].T/singular[keep]
    return x@transform,transform


def integrated_reduction(info,moment,rows,weight=1.):
    solved=np.linalg.solve(info,rows.T).T
    leverage=np.einsum("ij,ij->i",rows,solved)
    numerator=np.einsum("ij,jk,ik->i",solved,moment,solved)
    return weight*numerator/(1+weight*leverage)


@lru_cache(maxsize=128)
def public_basis(serialized_patterns,serialized_catalogs,interaction_order=4):
    patterns=json.loads(serialized_patterns);catalogs=json.loads(serialized_catalogs)
    variables=VARIABLES|(set(patterns)-{"heating","utensils"})
    atoms=public_dictionary(serialized_patterns,serialized_catalogs,True,interaction_order)
    trees=[compile_expression(a,variables=variables) for a in atoms]
    designs=[];rows=[]
    for stage in (s for s in ("source","adaptation") if s in catalogs):
        catalog=catalogs[stage];ids=sorted(p["id"] for p in catalog)
        for site in (["00"] if stage=="source" else ["00","10","01","11"]):
            for flags in itertools.product((0,1),repeat=len(ids)):
                arm=[pid for pid,f in zip(ids,flags) if f]
                values=features(patterns,catalog,arm,tuple(map(int,site)))
                designs.append((stage,site,tuple(arm)))
                rows.append([1.]+[evaluate(tree,values) for tree in trees])
    x=np.asarray(rows);z,_=whiten(x)
    target=[i for i,d in enumerate(designs) if d[0]==("adaptation" if "adaptation" in catalogs else "source")]
    moment=z[target].T@z[target]/len(target)
    return designs,z,moment,{"public_columns":x.shape[1],"public_rank":z.shape[1],
        "legal_conditions":len(designs),"integration_conditions":len(target),
        "integration_domain":"adaptation" if "adaptation" in catalogs else "source"}


def plan_prediction(lab,model,criterion="i",interaction_order=4):
    if criterion not in {"i","d"}:raise ValueError("unknown public-subspace criterion")
    patterns=model["role_patterns"]
    catalogs={s:lab.public_catalog(s) for s in (["source","adaptation"] if lab.transfer_open else ["source"])}
    designs,z,moment,metadata=public_basis(json.dumps(patterns,sort_keys=True),json.dumps(catalogs,sort_keys=True),interaction_order)
    lookup={design:i for i,design in enumerate(designs)};info=np.eye(z.shape[1]);seen=set()
    for row,_ in lab.verified_observations():
        design=(row["stage"],row["site"],tuple(sorted(row["assortment"])))
        v=z[lookup[design]];info+=row["n"]/400*np.outer(v,v);seen.add(design)
    solved=np.linalg.solve(info,z.T).T
    gains=integrated_reduction(info,moment,z) if criterion=="i" else np.log1p(np.einsum("ij,ij->i",z,solved))
    feasible=[]
    for i,(stage,site,arm) in enumerate(designs):
        cost=5+len(arm)
        if (stage,site,arm) in seen or lab.used["cost"]+cost>lab.limits["cost"]:continue
        # Equivalent public parameterizations can differ by roundoff after SVD.
        feasible.append((round(float(gains[i])/cost,10),round(float(gains[i]),10),-cost,stage,site,arm,i))
    if not feasible:return None
    score,gain,_,stage,site,arm,index=max(feasible)
    before=float(np.trace(np.linalg.solve(info,moment)))
    reduction=float(integrated_reduction(info,moment,z[index:index+1])[0])
    return {"stage":stage,"site":site,"assortment":list(arm),"n":400,
        "verified_supply":True,"verified_meter":True,
        "prediction":predict(model,catalogs[stage],arm,tuple(map(int,site))),
        "rationale":"公开函数子空间去冗余并白化；按单位操作成本的线性预测方差减量或 log-det 增益选择，非真值或校准后验。",
        "design_diagnostics":{**metadata,"criterion":"public_subspace_integrated_variance" if criterion=="i" else "public_subspace_logdet",
            "score":score,"gain":gain,"ridge_strength":1,"cost":5+len(arm),
            "integrated_variance_before":before,"integrated_variance_reduction":reduction}}
