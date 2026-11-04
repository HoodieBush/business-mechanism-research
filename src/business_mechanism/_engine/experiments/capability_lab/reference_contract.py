"""Public reference namespaces and dispatch shape; no scientific ranking."""
import copy

VERSION = "reference-contract-v0.1-public-namespaces"


def clone_schema(value):
    """JSON schema fields are values, not shared Python dictionary identities."""
    if isinstance(value, dict):return {key: clone_schema(child) for key, child in value.items()}
    if isinstance(value, list):return [clone_schema(child) for child in value]
    return copy.deepcopy(value)


def domains(state):
    organization = state.get("research_organization", {})
    contexts = organization.get("contexts", [])
    contract = organization.get("contract", {})
    expand = contract.get("mode") == "C" and len(contexts) < contract["max_C_nodes"]
    return {"analysis_ids": [card["analysis_id"] for card in state.get("public_evidence_store", {}).get("analysis_cards", [])],
            "context_ids": [context["context_id"] for context in contexts],
            "dispatch_kinds": ["select", "expand"] if expand else ["select"],
            "candidate_count": state.get("candidate_count"),
            "epistemic_role": "Available public object references only; appraisals and dispatch do not add evidence."}


def apply_schema(name, parameters, state):
    result = clone_schema(parameters)
    available = domains(state)
    props = result["properties"]
    if "candidate_id" in props:
        props["candidate_id"].update(pattern=r"^C[0-9]{4,}$", description=
            "不可变候选模型版本C...；不是研究上下文ID或分析ID。当前已登记数量见candidate_count。")
    if "analysis_ids" in props:
        props["analysis_ids"]["items"]["enum"] = available["analysis_ids"]
        props["analysis_ids"]["description"] = "已收到分析的字符串ID，通常A...；无可用分析时填[]。不能用检查K...或整数job ID代替。"
    if name == "dispatch_research_context":
        props["target_id"].update(enum=available["context_ids"], description=
            "现存研究上下文或父节点ID；不能填candidate_id。新上下文须等实际回执后才可引用。")
        props["kind"]["enum"] = available["dispatch_kinds"]
        result["allOf"] = [{"if": {"properties": {"kind": {"const": "expand"}}, "required": ["kind"]},
            "then": {"required": ["branch_kind"]}, "else": {"not": {"required": ["branch_kind"]}}}]
    return result


def validate_action(action, state):
    """Enforce the presented domains even when a provider ignores its schema."""
    args = action["args"]
    available = domains(state)
    if "analysis_ids" in args:
        ids = args["analysis_ids"]
        if not isinstance(ids, list) or any(not isinstance(identifier, str) for identifier in ids):
            raise ValueError("analysis_ids must be available string analysis IDs, or []")
        if not set(ids) <= set(available["analysis_ids"]):
            raise ValueError("analysis reference not available in the public request prefix")
    if action["tool"] != "dispatch_research_context":
        return
    if args["target_id"] not in available["context_ids"]:
        raise ValueError("target_id must be an existing research context ID, not a candidate ID")
    if args["kind"] not in available["dispatch_kinds"]:
        raise ValueError("dispatch kind unavailable for this organization or capacity")
    if args["kind"] == "expand" and "branch_kind" not in args:
        raise ValueError("expand requires branch_kind")
    if args["kind"] == "select" and "branch_kind" in args:
        raise ValueError("select must not include branch_kind")
