"""Typed public action contract; no generated outcomes or policy sequence."""
import copy


def obj(properties=None,optional=()):
    properties=properties or {}
    return {"type":"object","properties":properties,"required":[k for k in properties if k not in optional],"additionalProperties":False}


TEXT={"type":"string","minLength":1};BOOL={"type":"boolean"}
IDS={"type":"array","items":TEXT,"minItems":1,"uniqueItems":True}
CONDITION=obj({"stage":{"type":"string","enum":["source","adaptation"]},"site":{"type":"string","enum":["00","01","10","11"]},
    "assortment":{"type":"array","items":TEXT,"uniqueItems":True}})
CONDITION["oneOf"]=[{"properties":{"stage":{"const":"source"},"site":{"const":"00"}}},{"properties":{"stage":{"const":"adaptation"}}}]
DESIGN=copy.deepcopy(CONDITION);DESIGN["properties"]["n"]={"type":"integer","minimum":100,"maximum":800};DESIGN["required"].append("n")
ARGS={
    "diagnose_history":obj(),"open_adaptation":obj(),"retrieve_memory":obj(),"fit_pool":obj(),"assess_checks":obj(),
    "read_memory":obj({"episode_id":TEXT}),
    "review_memory":obj({"episode_ids":IDS,"usage":{"type":"string","enum":["structure_refit_only"]},"rationale":TEXT}),
    "propose_model":obj({"expression":TEXT,"parameters":{"type":"object","minProperties":1,"maxProperties":8,
        "additionalProperties":{"type":"array","minItems":3,"maxItems":3,"items":{"type":"number"}}},"rationale":TEXT}),
    "read_candidate":obj({"candidate_id":TEXT}),"review_candidate_evidence":obj({"candidate_id":TEXT}),"suggest_design":obj({"candidate_id":TEXT}),
    "dispatch_research_context":obj({"kind":{"type":"string","enum":["select","expand"]},"target_id":TEXT,"objective":TEXT,
        "analysis_ids":{"type":"array","items":TEXT,"uniqueItems":True},"candidate_id":TEXT,
        "branch_kind":{"type":"string","enum":["debug","refine","replicate","redesign","new_mechanism"]}},optional=("candidate_id","branch_kind")),
    "append_research_note":obj({"kind":{"type":"string","enum":["premise_review","mechanism_critique","design_comparison","negative_followup","execution_error"]},
        "text":TEXT,"analysis_ids":{"type":"array","items":TEXT,"uniqueItems":True},"candidate_id":TEXT},optional=("candidate_id",)),
    "sample":obj({"candidate_id":TEXT,"designs":{"type":"array","minItems":1,"maxItems":3,"items":DESIGN},"rationale":TEXT}),
    "sample_frontier":obj({"candidate_id":TEXT,"count":{"type":"integer","minimum":1,"maximum":3},"rationale":TEXT}),
    "start_discovery_task":obj({"candidate_id":TEXT,"count":{"type":"integer","minimum":1,"maximum":3},"objective":TEXT,"rationale":TEXT,"repair":BOOL}),
    "advance_discovery_task":obj({"task_id":TEXT,"rationale":TEXT,"repair":BOOL}),
    "collect":obj({"until":{"type":"string","enum":["next","all"]},"repair":BOOL,"refit":BOOL,"assess":BOOL}),
    "repair":obj({"job_id":{"type":"integer","minimum":0},"kind":{"type":"string","enum":["execution","meter"]}}),
    "confirm":obj({"candidate_id":TEXT,"design":CONDITION,"rationale":TEXT},optional=("design",)),
    "reopen_research":obj({"check_id":TEXT,"rationale":TEXT,"refit":BOOL}),
    "finish":obj({"candidate_id":TEXT,"claims":TEXT,"unresolved":BOOL,"stop_reason":TEXT}),
    "sample_and_analyze":obj({"candidate_id":TEXT,"designs":{"type":"array","minItems":1,"maxItems":3,"items":DESIGN},"rationale":TEXT,"repair":BOOL}),
    "confirm_and_analyze":obj({"candidate_id":TEXT,"design":CONDITION,"rationale":TEXT,"repair":BOOL},optional=("design",))}
SCHEMA=obj({"tool":{"type":"string","enum":sorted(ARGS)},"args":{"type":"object"},"rationale":TEXT,"expected_gap":TEXT})
SCHEMA["oneOf"]=[{"properties":{"tool":{"const":name},"args":args}} for name,args in ARGS.items()]


def validate_action_args(tool,args):
    """Reject malformed arguments, without inserting, coercing or repairing."""
    def visit(value,schema,path):
        kind=schema.get("type")
        if kind=="object":
            if not isinstance(value,dict):raise ValueError(f"{path}: object required")
            missing=set(schema.get("required",[]))-set(value)
            if missing:raise ValueError(f"{path}: missing={sorted(missing)}")
            props=schema.get("properties",{});extra=set(value)-set(props);additional=schema.get("additionalProperties",True)
            if extra and additional is False:raise ValueError(f"{path}: unexpected={sorted(extra)}")
            if not schema.get("minProperties",0)<=len(value)<=schema.get("maxProperties",float('inf')):raise ValueError(f"{path}: invalid property count")
            for k,v in value.items():
                child=props.get(k,additional)
                if isinstance(child,dict):visit(v,child,f"{path}.{k}")
        elif kind=="array":
            if not isinstance(value,list) or not schema.get("minItems",0)<=len(value)<=schema.get("maxItems",float('inf')):raise ValueError(f"{path}: invalid array size/type")
            if schema.get("uniqueItems") and any(x in value[:i] for i,x in enumerate(value)):raise ValueError(f"{path}: duplicate items")
            for i,v in enumerate(value):visit(v,schema["items"],f"{path}[{i}]")
        elif kind=="string":
            if not isinstance(value,str) or len(value.strip())<schema.get("minLength",0):raise ValueError(f"{path}: nonempty string required")
        elif kind=="boolean":
            if type(value) is not bool:raise ValueError(f"{path}: boolean required")
        elif kind in {"integer","number"}:
            valid=type(value) is int if kind=="integer" else type(value) in (int,float)
            if not valid or not schema.get("minimum",-float('inf'))<=value<=schema.get("maximum",float('inf')):raise ValueError(f"{path}: invalid {kind} or range")
        if "enum" in schema and value not in schema["enum"]:raise ValueError(f"{path}: choose {schema['enum']}")
    if tool not in ARGS:raise ValueError("unknown typed scientific action")
    visit(args,ARGS[tool],f"{tool}.args")
    conditions=args.get("designs",[]) if tool in {"sample","sample_and_analyze"} else [args["design"]] if tool in {"confirm","confirm_and_analyze"} and "design" in args else []
    for i,condition in enumerate(conditions):
        if condition["stage"]=="source" and condition["site"]!="00":raise ValueError(f"{tool}.args.condition[{i}]: source site must be '00'; other sites require a received adaptation catalog")
