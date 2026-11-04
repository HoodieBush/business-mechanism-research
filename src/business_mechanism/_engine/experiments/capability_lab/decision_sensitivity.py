"""Finite decision stress review of public directions unseen in released data.

Equal predictions at recorded training conditions do not certify the baseline,
identify a population identified set, or calibrate probabilities over scenarios.
"""
import copy
import itertools
import json

from lab import VARIABLES,compile_expression,evaluate,predict,validate_model
from operating_policy import optimize,order_quantity,profit_at_probability,validate_contract
from symbolic import features,public_dictionary
from temporal_lab import digest

VERSION="decision-sensitivity-v0.2-constant-and-affine-alias-directions"
CONTRACT={"version":VERSION,"interaction_order":4,"logit_shifts":[-3.,3.],"probability_shifts":[-.5,.5],
    "direction_families":["training_constant_atoms","affine_training_signature_alias_pairs"],
    "training_prediction_tolerance":1e-12,"prospective_cohort_n":400,
    "execution_allocation_feasibility_checked":False,
    "scope":"finite_single_direction_stress_on_received_catalogs_and_public_single_period_economics",
    "posterior_or_confidence_set":False,"new_scientific_support":False,"formal_VOI_or_deployment_guarantee":False}


def public_directions(atoms,variables,train_features):
    constant=[];groups={}
    for atom in atoms:
        tree=compile_expression(atom,variables=variables);values=[evaluate(tree,row) for row in train_features]
        low=min(values);high=max(values)
        if high-low<=1e-12:
            constant.append({"term":atom,"kind":"training_constant_atom","training_constant":low,
                "tree":{"op":"sub","args":[tree,low]}})
            continue
        signature=tuple((value-low)/(high-low) for value in values)
        complement=tuple(1-value for value in signature)
        if complement<signature:anchor=high;scale=low-high;signature=complement
        else:anchor=low;scale=high-low
        key=tuple(round(value,12) for value in signature)
        normalized={"op":"mul","args":[1/scale,{"op":"sub","args":[tree,anchor]}]}
        groups.setdefault(key,[]).append({"term":atom,"anchor":anchor,"scale":scale,"tree":normalized})
    aliases=[]
    for group in groups.values():
        reference=group[0]
        for other in group[1:]:
            tree={"op":"sub","args":[other["tree"],reference["tree"]]}
            if any(abs(evaluate(tree,row))>1e-12 for row in train_features):continue
            aliases.append({"term":f"affine contrast: {other['term']} vs {reference['term']}",
                "kind":"affine_training_signature_alias_pair","training_constant":None,"tree":tree,
                "members":[{key:item[key] for key in ("term","anchor","scale")} for item in (other,reference)]})
    return constant+aliases


def review(snapshot,contract):
    validate_contract(contract)
    view=snapshot["view"];catalogs=copy.deepcopy(view.catalogs);model=copy.deepcopy(snapshot["selected_original_model"])
    validate_model(model)
    if set(catalogs)-{"source","adaptation"} or "source" not in catalogs:raise ValueError("received source/adaptation catalogues only")
    data=view.verified_observations();ids=set(snapshot["training_ids"]);clock=snapshot["boundary_available_at"]
    if not data or {row["experiment_id"] for row,_ in data}!=ids:raise ValueError("exact nonempty declared training snapshot required")
    if any(not row["verified_supply"] or not row["verified_meter"] or row["available_at"]>clock for row,_ in data):raise ValueError("unverified or future training data")
    for row,sales in data:
        if row["stage"] not in catalogs or row["site"] not in (["00"] if row["stage"]=="source" else ["00","01","10","11"]):raise ValueError("unreceived training conditions")
        if not set(row["assortment"])<={p["id"] for p in catalogs[row["stage"]]} or sales!=row["observed_sales"] or not 0<=sales<=row["n"]:raise ValueError("invalid declared measurements")
    patterns=model["role_patterns"];variables=VARIABLES|(set(patterns)-{"heating","utensils"})
    expression=compile_expression(model["expression"],variables=variables) if isinstance(model["expression"],str) else copy.deepcopy(model["expression"])
    logit=isinstance(expression,dict) and expression.get("op")=="sigmoid"
    geometry=sorted(data,key=lambda item:(item[0]["stage"],item[0]["site"],tuple(sorted(item[0]["assortment"])),item[0]["experiment_id"]))
    train_features=[features(patterns,catalogs[row["stage"]],row["assortment"],tuple(map(int,row["site"]))) for row,_ in geometry]
    trained={(row["stage"],row["site"],tuple(sorted(row["assortment"]))) for row,_ in data}
    quantities={};profits={}
    def quantity(p,c):
        if p not in quantities:quantities[p]=order_quantity(p,c)
        return quantities[p]
    def profit(p,q,cost,c):
        key=(p,q,cost)
        if key not in profits:profits[key]=profit_at_probability(p,q,cost,c)
        return profits[key]
    def policy(catalog,external,slots,probability):return optimize(catalog,external,slots,probability,contract,quantity,profit)
    profiles=[]
    for stage,catalog in catalogs.items():
        for site in (["00"] if stage=="source" else ["00","01","10","11"]):
            ext=tuple(map(int,site))
            for slots in contract["auxiliary_slot_profiles"]:
                nominal=policy(catalog,ext,slots,lambda arm,e:predict(model,catalog,arm,e))
                profiles.append({"stage":stage,"site":site,"slots":slots,"nominal_policy":nominal})
    atoms=public_dictionary(json.dumps(patterns,sort_keys=True),json.dumps(catalogs,sort_keys=True),True,4)
    scenarios=[];directions=[];recommendations=[];inactive=0;unsupported=0
    for direction in public_directions(atoms,variables,train_features):
        atom=direction["term"];tree=direction["tree"];active=False
        for stage,catalog in catalogs.items():
            for site in (["00"] if stage=="source" else ["00","01","10","11"]):
                ext=tuple(map(int,site))
                for size in range(min(max(contract["auxiliary_slot_profiles"]),len(catalog))+1):
                    for products in itertools.combinations(catalog,size):
                        if abs(evaluate(tree,features(patterns,catalog,[p["id"] for p in products],ext)))>1e-12:active=True;break
                    if active:break
                if active:break
            if active:break
        if not active:inactive+=1;continue
        details={key:copy.deepcopy(value) for key,value in direction.items() if key!="tree"}
        directions.append(details)
        for shift in CONTRACT["logit_shifts"] if logit else CONTRACT["probability_shifts"]:
            delta={"op":"mul","args":[shift,tree]}
            base=expression["args"][0] if logit else expression
            augmented={"op":"add","args":[copy.deepcopy(base),delta]}
            stressed={"role_patterns":patterns,"expression":{"op":"sigmoid","args":[augmented]} if logit else augmented}
            try:validate_model(stressed)
            except ValueError:unsupported+=1;continue
            differences=[abs(predict(stressed,catalogs[row["stage"]],row["assortment"],tuple(map(int,row["site"]))) - predict(model,catalogs[row["stage"]],row["assortment"],tuple(map(int,row["site"])))) for row,_ in data]
            if max(differences)>1e-12:raise ValueError("stress changed an original training prediction")
            sid=f"S{len(scenarios):04d}";outcomes=[]
            for profile in profiles:
                stage=profile["stage"];site=profile["site"];ext=tuple(map(int,site));catalog=catalogs[stage];nominal=profile["nominal_policy"]
                alternate=policy(catalog,ext,profile["slots"],lambda arm,e:predict(stressed,catalog,arm,e))
                p=predict(stressed,catalog,nominal["assortment"],ext)
                nominal_value=profit(p,nominal["order_quantity"],nominal["material_cost_per_session"],contract)
                gap=alternate["predicted_expected_profit"]-nominal_value
                if gap < -1e-8:raise ValueError("public policy optimizer inconsistency")
                risk=max(0.,gap)/contract["customers_per_day"]
                changed=(nominal["assortment"],nominal["order_quantity"])!=(alternate["assortment"],alternate["order_quantity"])
                outcomes.append({"stage":stage,"site":site,"slots":profile["slots"],"scenario_policy":alternate,
                    "nominal_policy_scenario_profit":nominal_value,"nominal_policy_scenario_regret_per_customer":risk,"policy_changed":changed})
                if risk<=1e-10:continue
                witnesses=[]
                for arm in (nominal["assortment"],alternate["assortment"]):
                    key=(stage,site,tuple(sorted(arm)))
                    if key in trained:continue
                    pa=predict(model,catalog,arm,ext);pb=predict(stressed,catalog,arm,ext)
                    witnesses.append((abs(pa-pb),-len(arm),tuple(sorted(arm)),pa,pb))
                if not witnesses:continue
                difference,_,arm,pa,pb=max(witnesses)
                if difference<=1e-12:continue
                recommendations.append({"design":{"stage":stage,"site":site,"assortment":list(arm),"n":400},
                    "scenario_id":sid,"term":atom,"nominal_probability":pa,"stress_probability":pb,
                    "profile_scenario_regret_per_customer":risk,"probability_difference":difference,
                    "experimental_resource_cost_units":5+len(arm),
                    "execution_preflight":"not run; check decisions-open, remaining quotas, pending slots and deadline before registration",
                    "interpretation":"distinguishes this training-equivalent stress and nominal model at a decision-relevant condition; not expected value of information"})
            scenarios.append({"scenario_id":sid,"direction":details,"term":atom,"training_constant":direction["training_constant"],"shift":shift,"shift_scale":"logit" if logit else "probability",
                "expression":stressed["expression"],"model_sha256":digest(stressed),"max_training_prediction_difference":max(differences),
                "max_nominal_policy_scenario_regret_per_customer":max(row["nominal_policy_scenario_regret_per_customer"] for row in outcomes),"profiles":outcomes})
    recommendations.sort(key=lambda row:(-row["profile_scenario_regret_per_customer"],-row["probability_difference"],row["experimental_resource_cost_units"],json.dumps(row["design"],sort_keys=True),row["scenario_id"]))
    unique=[];seen=set()
    for row in recommendations:
        key=digest(row["design"])
        if key not in seen:unique.append(row);seen.add(key)
    return {"version":VERSION,"contract":copy.deepcopy(CONTRACT),"nominal_model_sha256":digest(model),
        "public_catalogues_sha256":digest(catalogs),"public_operating_contract":copy.deepcopy(contract),"training_ids":sorted(ids),"training_snapshot_sha256":digest([row for row,_ in data]),
        "nominal_policies":profiles,"reviewed_decision_active_directions":directions,
        "training_constant_decision_active_directions":[row for row in directions if row["kind"]=="training_constant_atom"],
        "affine_alias_decision_active_directions":[row for row in directions if row["kind"]=="affine_training_signature_alias_pair"],
        "decision_inactive_directions":inactive,"unsupported_stresses":unsupported,
        "scenarios":scenarios,"max_nominal_policy_regret_over_reviewed_scenarios":max([row["max_nominal_policy_scenario_regret_per_customer"] for row in scenarios]+[0.]),
        "suggested_discriminating_designs":unique[:3],"model_api_calls":0,"new_sessions":0,
        "limits":"Finite constant-atom/affine-alias single-direction stresses match nominal predictions within numerical tolerance only at recorded released training conditions. General null-space combinations, statistical parameter uncertainty and other programs are not covered. They are not a population identified set, calibrated posterior/confidence set, independent support or a guarantee on all models. Zero reviewed risk does not certify deployment. Private evaluation is never used for selecting stresses or designs."}
