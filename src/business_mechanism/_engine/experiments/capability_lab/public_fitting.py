"""Safe candidate fitting on an explicit public evidence snapshot only."""
import copy
import math

import numpy as np
from scipy.optimize import minimize

from lab import FUNCTIONS,VARIABLES,compile_expression,predict,validate_model


def check_public_model(model,data,catalogs,total_cohorts=None):
    validate_model(model)
    if not data:raise ValueError("no jointly verified cohorts available")
    residuals=[];deviance=0.
    for r,k in data:
        p=float(np.clip(predict(model,catalogs[r["stage"]],r["assortment"],tuple(map(int,r["site"]))),1e-6,1-1e-6));n=r["n"]
        if k:deviance+=2*k*math.log(k/(n*p))
        if n>k:deviance+=2*(n-k)*math.log((n-k)/(n*(1-p)))
        residuals.append({"experiment_id":r["experiment_id"],"observed_rate":k/n,"program_probability":p,
            "standardized_residual":round((k-n*p)/math.sqrt(n*p*(1-p)),3)})
    return {"verified_cohorts":len(data),"unverified_cohorts_excluded":(total_cohorts if total_cohorts is not None else len(data))-len(data),
        "binomial_deviance":round(deviance,4),"residuals":residuals,
        "note":"训练拟合诊断，不是独立确认；修订机制需要新条件的冻结预测与测量。"}


def fit_public_candidate(args,data,catalogs,candidate_id=0,total_cohorts=None):
    params=args.get("parameters")
    if not isinstance(params,dict) or not 1<=len(params)<=8:raise ValueError("declare 1..8 parameters")
    names=[];starts=[];bounds=[]
    for name,spec in params.items():
        if not isinstance(name,str) or not name.isidentifier() or name in VARIABLES or name in {"min","max","sigmoid"}:raise ValueError("invalid parameter name")
        if not isinstance(spec,list) or len(spec)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in spec):
            raise ValueError("parameter spec is [start,lower,upper]")
        start,lo,hi=spec
        if not -6<=lo<=start<=hi<=6 or lo>=hi:raise ValueError("invalid parameter bounds")
        names.append(name);starts.append(start);bounds.append((lo,hi))
    if not data:raise ValueError("no jointly verified cohorts available")
    patterns=args["role_patterns"];template=args["expression"]
    if set(names)&set(patterns):raise ValueError("parameter names cannot collide with declared role factors")
    def make(values):
        return {"role_patterns":copy.deepcopy(patterns),"expression":compile_expression(template,dict(zip(names,values)),VARIABLES|(set(patterns)-set(FUNCTIONS)))}
    validate_model(make(starts))
    def objective(values):
        model=make(values);loss=0.
        for r,k in data:
            p=float(np.clip(predict(model,catalogs[r["stage"]],r["assortment"],tuple(map(int,r["site"]))),1e-6,1-1e-6))
            loss-=k*math.log(p)+(r["n"]-k)*math.log(1-p)
        return loss
    rng=np.random.default_rng(0)
    trials=[np.array(starts)]+[np.array([rng.uniform(lo,hi) for lo,hi in bounds]) for _ in range(2)]
    fits=[minimize(objective,start,method="L-BFGS-B",bounds=bounds,options={"maxiter":150}) for start in trials]
    best=min(fits,key=lambda fit:fit.fun);model=make(best.x)
    return {"candidate_id":candidate_id,"model":model,"parameters":{name:round(float(x),6) for name,x in zip(names,best.x)},
        "optimizer_success":bool(best.success),"template":template,**check_public_model(model,data,catalogs,total_cohorts)}
