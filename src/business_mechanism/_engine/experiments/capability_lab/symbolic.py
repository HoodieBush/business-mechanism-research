"""Small symbolic response-model search and observable design disagreement.

The grammar is public and truth-independent; it is not a table of world labels.
Candidate ranking is BIC, not claimed to be a calibrated Bayesian posterior.
"""
from __future__ import annotations

import itertools
import math
import json
from functools import lru_cache

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from lab import VARIABLES, compile_expression, evaluate, model_with, predict
from model_order import candidate_key


def features(patterns, catalog, assortment, external):
    text = [p["description"] for p in catalog if p["id"] in set(assortment)]
    values={"heat":int(any(any(s in t for s in patterns["heating"]) for t in text)),
            "utensils":int(any(any(s in t for s in patterns["utensils"]) for t in text)),
            "external_heat":int(external[0]),"external_utensils":int(external[1]),
            "items":len(assortment)}
    for name,substrings in patterns.items():
        if name not in {"heating","utensils"}:
            values[name]=int(any(any(s in t for s in substrings) for t in text))
    return values


def grammar(patterns, expanded=True, all_factors=False,interaction_order=3):
    atoms=["max(heat,external_heat)","max(utensils,external_utensils)",
           "heat","utensils","external_heat","external_utensils"]
    atoms += [k for k in patterns if k not in {"heating","utensils"}]
    if not expanded:
        return atoms
    expanded_atoms=atoms.copy()
    for left,right in itertools.combinations(atoms,2):
        expanded_atoms.append(f"({left})*({right})")
    # Generic low-order factors and count hinges, including potentially harmful
    # and benign relationships. No feature is labelled as the true mechanism.
    for factors in itertools.combinations(atoms if all_factors else atoms[:6],3):
        expanded_atoms.append("*".join(f"({f})" for f in factors))
    if all_factors and interaction_order>=4:
        for factors in itertools.combinations(atoms,4):
            expanded_atoms.append("*".join(f"({f})" for f in factors))
    expanded_atoms += [f"max(items-{t},0)" for t in range(5)]
    expanded_atoms.append("items")
    return list(dict.fromkeys(expanded_atoms))


@lru_cache(maxsize=256)
def public_dictionary(serialized_patterns,serialized_catalogs,expanded,interaction_order=3):
    """Remove globally redundant atoms using public legal inputs, never outcomes."""
    patterns=json.loads(serialized_patterns);catalogs=json.loads(serialized_catalogs)
    variables=VARIABLES|(set(patterns)-{"heating","utensils"})
    atoms=grammar(patterns,expanded,all_factors=True,interaction_order=interaction_order)
    atoms.sort(key=lambda atom:(len(atom),atom))
    rows=[]
    for stage,catalog in catalogs.items():
        ids=[p["id"] for p in catalog]
        for external in ([(0,0)] if stage=="source" else itertools.product((0,1),repeat=2)):
            for flags in itertools.product((0,1),repeat=len(ids)):
                rows.append(features(patterns,catalog,[pid for pid,f in zip(ids,flags) if f],external))
    signatures=set();retained=[]
    for atom in atoms:
        tree=compile_expression(atom,variables=variables)
        signature=tuple(evaluate(tree,row) for row in rows)
        if signature not in signatures and len(set(signature))>1:
            signatures.add(signature);retained.append(atom)
    return retained


def search(lab,patterns,expanded=True,beam=5,max_terms=3,link="linear",public_dedup=False,interaction_order=3,
           preserve_aliases=False,max_candidates=8):
    data=lab.verified_observations()
    if not data:
        raise ValueError("need verified evidence before symbolic search")
    if link not in {"linear","logit"}:raise ValueError("unknown probability link")
    if public_dedup:
        catalogs={"source":lab.public_catalog("source")}
        if getattr(lab,"transfer_open",False):catalogs["adaptation"]=lab.public_catalog("adaptation")
        atoms=public_dictionary(json.dumps(patterns,sort_keys=True),json.dumps(catalogs,sort_keys=True),expanded,interaction_order)
    else:atoms=grammar(patterns,expanded)
    variables=set(VARIABLES)|(set(patterns)-{"heating","utensils"})
    asts=[compile_expression(atom,variables=variables) for atom in atoms]
    rows=[features(patterns,lab.public_catalog(r["stage"]),r["assortment"],tuple(map(int,r["site"]))) for r,_ in data]
    full_x=np.array([[1.0]+[evaluate(ast,row) for ast in asts] for row in rows])
    n=np.array([r["n"] for r,_ in data],dtype=float)
    k=np.array([sales for _,sales in data],dtype=float)
    y=k/n
    total=n.sum()
    cache={}
    def fit(indices):
        indices=tuple(sorted(indices))
        if indices in cache:
            return cache[indices]
        x=full_x[:,[0]+[i+1 for i in indices]]
        if np.linalg.matrix_rank(x)<x.shape[1]:
            cache[indices]=None
            return None
        target=np.log((k+.5)/(n-k+.5)) if link=="logit" else y
        start=np.linalg.lstsq(x*np.sqrt(n[:,None]),target*np.sqrt(n),rcond=None)[0]
        if link=="logit":
            start=np.clip(start,-6,6);bounds=[(-6,6)]*x.shape[1]
        else:
            start=np.clip(start,-1,1);start[0]=np.clip(start[0],.05,.95)
            bounds=[(.05,.95)]+[(-1,1)]*len(indices)
        def objective(theta):
            raw=x@theta
            p=np.clip(expit(raw),1e-9,1-1e-9) if link=="logit" else np.clip(raw,.05,.95)
            loss=-np.sum(k*np.log(p)+(n-k)*np.log1p(-p))
            gradient=x.T@(n*p-k) if link=="logit" else x.T@((n*p-k)/(p*(1-p))*((raw>=.05)&(raw<=.95)))
            return float(loss),gradient
        opt=minimize(objective,start,jac=True,method="L-BFGS-B",bounds=bounds,options={"maxiter":100})
        theta=opt.x
        terms=[str(float(theta[0]))]+[f"({float(c)})*({atoms[i]})" for c,i in zip(theta[1:],indices)]
        expression="sigmoid("+"+".join(terms)+")" if link=="logit" else "min(0.95,max(0.05,"+"+".join(terms)+"))"
        model={"role_patterns":patterns,"expression":expression}
        p=np.clip(expit(x@theta),1e-9,1-1e-9) if link=="logit" else np.clip(x@theta,.05,.95)
        deviance=0.0
        for ni,ki,pi in zip(n,k,p):
            if ki:deviance+=2*ki*math.log(ki/(ni*pi))
            if ni-ki:deviance+=2*(ni-ki)*math.log((ni-ki)/(ni*(1-pi)))
        result={"model":model,"terms":[atoms[i] for i in indices],"indices":indices,
                "bic":float(2*opt.fun+x.shape[1]*math.log(total)),
                "deviance":float(deviance),"rank":x.shape[1],
                "max_residual":float(np.max(np.abs((k-n*p)/np.sqrt(n*p*(1-p))))),
                "optimizer_success":bool(opt.success),"link":link}
        cache[indices]=result
        return result
    best=[fit(())]
    archive=[best[0]]
    for size in range(1,max_terms+1):
        proposals=set()
        for parent in best:
            for i in range(len(atoms)):
                if i not in parent["indices"]:
                    proposals.add(tuple(sorted(parent["indices"]+(i,))))
        level=[r for indices in sorted(proposals) if (r:=fit(indices)) is not None]
        if not level:break
        level.sort(key=candidate_key)
        best=level[:beam]
        # Beam width controls further combinations, not which already fitted
        # observational aliases survive into the uncertainty/design committee.
        archive+=level if preserve_aliases else best
    archive.sort(key=candidate_key)
    return [{k:v for k,v in r.items() if k!="indices"} for r in archive[:max_candidates]]


def plan(lab,pool,novelty=True,disagreement_weight=1.0):
    """Rank unqueried legal designs using candidate variance and feature distance."""
    best=pool[0]
    competitive=[r for r in pool if r["bic"]-best["bic"]<=6]
    competitive=competitive or [best]
    seen=lab.observed_cohorts()
    result=[]
    past_features=[features(best["model"]["role_patterns"],lab.public_catalog(r["stage"]),r["assortment"],tuple(map(int,r["site"]))) for r in seen]
    namespaces=["source","adaptation"] if lab.transfer_open else ["source"]
    for namespace in namespaces:
        catalog=lab.public_catalog(namespace)
        ids=[p["id"] for p in catalog]
        sites=["00","10","01","11"] if namespace=="adaptation" else ["00"]
        for site in sites:
            ext=tuple(map(int,site))
            for flags in itertools.product((0,1),repeat=len(ids)):
                arm=[pid for pid,flag in zip(ids,flags) if flag]
                if any(r["stage"]==namespace and r["site"]==site and set(r["assortment"])==set(arm) for r in seen):
                    continue
                operation_cost=5+len(arm)
                if lab.used["cost"]+operation_cost>lab.limits["cost"]:
                    continue
                probabilities=[predict(r["model"],catalog,arm,ext) for r in competitive]
                disagreement=float(np.var(probabilities))
                feature=features(best["model"]["role_patterns"],catalog,arm,ext)
                # Distance explicitly covers public measurement dimensions; a
                # different SKU ID alone contributes no novelty.
                # With no received or queued geometry there is no reference
                # for feature novelty. Start from zero novelty; the existing
                # public cost/tie rule then chooses a legal initial design.
                distance=min((sum((feature[v]-old[v])**2/(36 if v=="items" else 1) for v in feature) for old in past_features),default=0.)
                score=(disagreement_weight*disagreement+(.006*distance if novelty else 0))/operation_cost
                result.append((score,disagreement,distance,operation_cost,namespace,site,arm,float(np.mean(probabilities))))
    if not result:return None
    result.sort(key=lambda r:(r[0],r[1] if disagreement_weight else 0,r[2] if novelty else 0,-r[3],r[4],r[5],r[6]),reverse=True)
    score,variance,distance,cost,stage,site,arm,p=result[0]
    return {"assortment":arm,"stage":stage,"site":site,"n":400,
            "verified_supply":True,"verified_meter":True,"prediction":p,
            "rationale":"仅由可执行候选分歧与未覆盖公开特征选择新条件。",
            "design_diagnostics":{"score":score,"model_variance":variance,"feature_distance":distance,
                                  "competitive_models":len(competitive),"cost":cost}}
