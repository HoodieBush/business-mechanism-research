"""One typed function per scientific service; no nested action-name wrapper."""
import copy
import json

from research_action_schema import ARGS,TEXT,validate_action_args
from research_runtime import TOOLS
from reference_contract import clone_schema

VERSION="native-science-v0.2-optional-reference-domains"


def function_definitions(state=None,reference_contract=False):
    from scientific_readiness import readiness
    ready=readiness(state) if state is not None else None
    if reference_contract and state is None:raise ValueError("reference domains require received public state")
    out=[]
    for name,args in ARGS.items():
        if ready is not None and (name not in ready["services"] or not ready["services"][name]["ready"]):continue
        parameters=clone_schema(args)
        parameters["properties"].update(rationale=copy.deepcopy(TEXT),expected_gap=copy.deepcopy(TEXT))
        parameters["required"]=list(dict.fromkeys([*parameters["required"],"rationale","expected_gap"]))
        if state is not None:
            domains=ready["parameter_domains"]
            if name=="advance_discovery_task":parameters["properties"]["task_id"]["enum"]=[task["task_id"] for task in state["discovery_tasks"]["tasks"] if task["status"]!="submission_failed"]
            if name=="read_memory":parameters["properties"]["episode_id"]["enum"]=domains["source_episode_ids"]
            if name=="review_memory":parameters["properties"]["episode_ids"]["items"]["enum"]=domains["source_episode_ids"]
            if name=="reopen_research":parameters["properties"]["check_id"]["enum"]=domains["refutation_check_ids"]
            if name=="repair":
                parameters["oneOf"]=[{"properties":{"kind":{"const":kind},"job_id":{"enum":ids}}} for kind,ids in (("execution",domains["execution_job_ids"]),("meter",domains["meter_job_ids"])) if ids]
            for design_key in ("design","designs"):
                if design_key not in parameters["properties"]:continue
                design=parameters["properties"][design_key]
                if design_key=="designs":design=design["items"]
                variants=[]
                for stage,sites in domains["stage_sites"].items():
                    variant=copy.deepcopy(design);variant.pop("oneOf",None)
                    variant["properties"]["stage"]["enum"]=[stage];variant["properties"]["site"]["enum"]=sites
                    variant["properties"]["assortment"]["items"]["enum"]=[p["id"] for p in state["catalogs"][stage]]
                    variants.append(variant)
                parameters["properties"][design_key]=({"type":"array","minItems":1,"maxItems":min(3,ready["pending_slots"]),"items":{"oneOf":variants}} if design_key=="designs" else {"oneOf":variants})
        if reference_contract:
            from reference_contract import apply_schema
            parameters=apply_schema(name,parameters,state)
        out.append({"type":"function","function":{"name":name,"description":TOOLS[name].split("；",1)[-1],"parameters":parameters}})
    return out


def decode_native(raw,config):
    choice=raw["choices"][0]
    if choice.get("finish_reason")=="length":raise ValueError("truncated output")
    calls=choice["message"].get("tool_calls") or []
    if calls:
        if not 1<=len(calls)<=3:raise ValueError("submit 1..3 native scientific function calls")
        if any(not isinstance(c,dict) or c.get("type")!="function" or not isinstance(c.get("id"),str) or not c["id"] for c in calls):raise ValueError("invalid native function identity")
        if len({c["id"] for c in calls})!=len(calls):raise ValueError("duplicate native function identity")
        submissions=[{"tool":c["function"]["name"],"arguments":json.loads(c["function"]["arguments"])} for c in calls]
    else:
        if not config.get("plain_json_fallback",False):raise ValueError("no actual scientific function call")
        submissions=[json.loads(choice["message"].get("content") or "")]
    actions=[]
    for i,submission in enumerate(submissions):
        if not isinstance(submission,dict) or set(submission)!={"tool","arguments"}:raise ValueError(f"native[{i}]: whole object fields must be tool,arguments")
        tool=submission["tool"];arguments=submission["arguments"]
        if tool not in ARGS or not isinstance(arguments,dict):raise ValueError(f"native[{i}]: unknown service or non-object arguments")
        fields=set(ARGS[tool]["properties"])|{"rationale","expected_gap"}
        if set(arguments)-fields:raise ValueError(f"native[{i}]: unexpected={sorted(set(arguments)-fields)}")
        if any(not isinstance(arguments.get(k),str) or not arguments[k].strip() for k in ("rationale","expected_gap")):raise ValueError(f"native[{i}]: rationale and expected_gap are required nonempty strings")
        args={k:copy.deepcopy(v) for k,v in arguments.items() if k in ARGS[tool]["properties"]}
        validate_action_args(tool,args)
        actions.append({"tool":tool,"args":args,"rationale":arguments["rationale"],"expected_gap":arguments["expected_gap"]})
    if any(a["tool"]=="finish" for a in actions[:-1]):raise ValueError("finish must be last")
    if any(a["tool"]=="dispatch_research_context" for a in actions[:-1]):raise ValueError("context dispatch must be last; the next context acts in a later model request")
    return actions
