"""Complete frozen protocols constructed from public executable models."""
import copy
from lab import predict


def register_plan(lab,model,action,claim_id,purpose="discovery"):
    action=copy.deepcopy(action);action.pop("design_diagnostics",None)
    action["prediction"]=predict(model,lab.public_catalog(action["stage"]),action["assortment"],tuple(map(int,action["site"])))
    analysis={"purpose":"discovery","rule":"descriptive_fit_only"} if purpose=="discovery" else {
        "purpose":"confirmation","rule":"clopper_pearson","max_checks":6,"total_alpha":.05,"tolerance":.05}
    if purpose not in {"discovery","confirmation"}:raise ValueError("invalid scientific phase")
    return {"claim_id":claim_id,"model":copy.deepcopy(model),"action":action,
        "estimand":"purchase_probability_in_fixed_condition","randomization_unit":"qualified_session",
        "analysis":analysis,"stopping":{"deadline":lab.deadline,"missing_result":"unresolved",
            "execution_failure":"repair_before_science","unverified_meter":"exclude_until_reconciled"},
        "rationale":action["rationale"]}
