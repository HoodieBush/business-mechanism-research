"""Shared assortment/newsvendor optimizer and private independent trajectories."""
import itertools
import math

import numpy as np

from lab import predict
from choice_world import economics
from operating_policy import optimize,order_quantity,profit_at_probability


def physical_fact_audit(world,deployed_model):
    """Fixture-label evaluation after freeze; never compiler repair feedback."""
    catalog=sum((world.catalogs[s] for s in ("source","adaptation","heldout")),[])
    patterns=deployed_model["role_patterns"]
    predicted={name:tuple(any(s in p["description"] for s in values) for p in catalog)
               for name,values in patterns.items()}
    truth={name:tuple(world.roles[stage][p["id"]][name] for stage in ("source","adaptation","heldout")
                      for p in world.catalogs[stage]) for name in world.roles["source"][catalog[0]["id"]]}
    core_errors=sum(a!=b for name in ("heating","utensils") for a,b in zip(predicted[name],truth[name]))
    coverage={name:[role for role,signature in predicted.items() if role not in {"heating","utensils"} and signature==values]
              for name,values in truth.items() if name not in {"heating","utensils"}}
    return {"core_classifications":2*len(catalog),"core_errors":core_errors,
        "core_accuracy":1-core_errors/(2*len(catalog)),"extra_function_signature_matches":coverage,
        "note":"私有策划事实标签的离线核对；额外角色按全目录实物签名匹配，不能证明名称含义或人类独立标注一致性。"}


def evaluate(world,frozen_model,deployed_model):
    if frozen_model["expression"]!=deployed_model["expression"]:raise ValueError("deployment changed frozen probability relation")
    catalog=world.catalogs["heldout"];contract=economics(world.retail_price)
    probabilities=[];effects=[]
    ids=[p["id"] for p in catalog]
    for external in itertools.product((0,1),repeat=2):
        baseline_p=predict(deployed_model,catalog,[],external)
        baseline_t=world.probability("heldout",[],external)
        for flags in itertools.product((0,1),repeat=len(ids)):
            arm=[pid for pid,flag in zip(ids,flags) if flag]
            p=predict(deployed_model,catalog,arm,external);t=world.probability("heldout",arm,external)
            probabilities.append((p-t)**2);effects.append(((p-baseline_p)-(t-baseline_t))**2)
    profiles=[]
    for external in itertools.product((0,1),repeat=2):
        for slots in contract["auxiliary_slot_profiles"]:
            policy=optimize(catalog,external,slots,lambda arm,ext:predict(deployed_model,catalog,arm,ext),contract)
            oracle=optimize(catalog,external,slots,lambda arm,ext:world.probability("heldout",arm,ext),contract)
            p=world.probability("heldout",policy["assortment"],external)
            value=profit_at_probability(p,policy["order_quantity"],policy["material_cost_per_session"],contract)
            regret=oracle["predicted_expected_profit"]-value
            if regret < -1e-8:raise ValueError("optimizer/evaluator consistency violated")
            rng=np.random.default_rng(world.seed+901933+slots*111+external[0]*19+external[1]*71)
            classes=rng.random((contract["days_per_profile"],contract["customers_per_day"]))
            buys=rng.random(classes.shape)
            daily=[]
            for day in range(contract["days_per_profile"]):
                def rollout(choice):
                    demand=int(world.purchases("heldout",choice["assortment"],external,classes[day],buys[day]).sum())
                    q=choice["order_quantity"];sales=min(q,demand);ending=q-sales
                    profit=contract["retail_price"]*sales+contract["salvage_value"]*ending-contract["purchase_cost"]*q-contract["customers_per_day"]*choice["material_cost_per_session"]
                    return {"demand":demand,"opening":q,"sales":sales,"ending":ending,"lost_sales":demand-sales,"profit":profit}
                daily.append({"day":day,"policy":rollout(policy),"oracle":rollout(oracle)})
            profiles.append({"external":list(external),"auxiliary_slots":slots,"policy":policy,
                "oracle_private":oracle,"true_expected_profit":value,"expected_regret":max(0.,regret),"daily_trajectories":daily})
    return {"heldout_probability_rmse":math.sqrt(float(np.mean(probabilities))),
        "heldout_effect_rmse":math.sqrt(float(np.mean(effects))),"heldout_conditions":len(effects),
        "mean_expected_operating_regret_per_customer":float(np.mean([p["expected_regret"] for p in profiles]))/contract["customers_per_day"],
        "mean_realized_policy_profit_per_day":float(np.mean([d["policy"]["profit"] for p in profiles for d in p["daily_trajectories"]])),
        "fixture_physical_fact_audit":physical_fact_audit(world,deployed_model),
        "economics":contract,"profiles":profiles,"note":"独立新需求流的合成单日易腐库存；不是企业收益或一般多期库存证明。"}
