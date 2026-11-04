"""Evidence-scoped mechanism cards; no generator, scorer, or hidden task labels."""
import copy
import hashlib
import json


def card(model,ontology,versions,checks):
    frozen=[v for v in versions if v["phase"]=="confirmation_model_frozen"]
    current=frozen[-1]
    if current["model"]!=model:raise ValueError("final model differs from last frozen confirmation version")
    # Earlier rounds only apply to the current claim if the entire executable
    # model is unchanged. A refuted old relation is retained in the lineage.
    applicable_rounds={v["round"] for v in frozen if v["model"]==model}
    training=set(current["training_evidence_ids"])|set(current.get("information_evidence_ids",[]))
    applicable=[c for c in checks if c["round"] in applicable_rounds
        and not training.intersection(c.get("experiment_ids",[c["experiment_id"]]))]
    if any(c["state"]=="contradicted" for c in applicable):state="refuted_in_listed_conditions"
    elif applicable and all(c["state"]=="supported_within_tolerance" for c in applicable):state="supported_in_listed_conditions"
    else:state="pending_confirmation"
    identity=hashlib.sha256(json.dumps({"model":model,"ontology":ontology},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {"mechanism_id":identity,"physical_definitions":copy.deepcopy(ontology),"frozen_model":copy.deepcopy(model),
        "state":state,"training_evidence_ids":current["training_evidence_ids"].copy(),
        "conditional_claims":[{"round":c["round"],"state":c["state"],
            "condition":{k:copy.deepcopy(c["design"][k]) for k in ("stage","site","assortment")},
            "experiment_ids":c.get("experiment_ids",[c["experiment_id"]]),"n":c["n"],
            "frozen_prediction":c["frozen_prediction"],"tolerance":.05,
            "exact_probability_interval":c["exact_probability_interval"]} for c in applicable],
        "version_lineage":[{"round":v["round"],"model":copy.deepcopy(v["model"]),
            "training_evidence_ids":v["training_evidence_ids"].copy(),
            "check_states":[c["state"] for c in checks if c["round"]==v["round"]]} for v in frozen],
        "untested_scope_state":"unresolved_extrapolation",
        "identification_limits":["心理中介及消费者类型未唯一识别","确认条件不代表所有组合或新目录"],
        "deployment_scope":"离线强制部署评价；含未确认模型，不是已获机制认证的生产策略。"}


def temporal_card(model,ontology,versions,checks,max_checks=6):
    """Execution coverage never erases already known conditional evidence."""
    result=card(model,ontology,versions,checks)
    result.update(calendar_incomplete=len(checks)<max_checks,
        research_coverage_state="incomplete" if len(checks)<max_checks else "complete",
        completed_checks=len(checks),planned_checks=max_checks)
    return result
