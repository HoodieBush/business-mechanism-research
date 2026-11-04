"""Public-state action preconditions, independent of hypothesis truth or score."""
import copy
import re

LEGACY_VERSION="scientific-readiness-v0.1-public-preconditions"
VERSION="scientific-readiness-v0.2-public-analysis-review"
BUNDLES={"sample_and_analyze","confirm_and_analyze"}
SERVICES={"diagnose_history","open_adaptation","retrieve_memory","read_memory","review_memory","fit_pool","propose_model",
    "read_candidate","review_candidate_evidence","suggest_design","sample","sample_frontier","collect","repair","confirm","assess_checks","reopen_research","finish",*BUNDLES}
ORGANIZATION_SERVICES={"dispatch_research_context","append_research_note"}


def action_charge(action,state):
    tool=action["tool"]
    if tool in BUNDLES or tool=="start_discovery_task":return 3
    if tool=="advance_discovery_task":
        task=next((task for task in state.get("discovery_tasks",{}).get("tasks",[]) if task["task_id"]==action["args"]["task_id"]),None)
        return 1 if task is not None and task["status"]=="completed" else 2
    return 1


def readiness(state):
    used=state["used"];limits=state["limits"]
    remaining={k:limits[k]-used[k] for k in ("sessions","arms","cost","tool_calls")}
    slots=state["legal_design_values"]["max_pending_jobs"]-sum(j["status"]=="pending" for j in state["pending_jobs"])
    live=state["clock"]<limits["logical_time"]
    has_training=bool(state["training_evidence_ids"])
    planned=state.get("registered_job_count",used["arms"]+len(state["failed_jobs"]))
    open_catalog="adaptation" in state["catalogs"]
    memory=state["memory_archive_available"]
    sources=state["available_memory_episode_ids"]
    actions_left=state["scientific_actions_limit"]-state["scientific_actions_used"]
    check_slots=max(0,6-len(state["checks"]))
    eligible_checks=[c["check_id"] for c in state["checks"] if c["state"]=="contradicted" and not c["released"]]
    feasible_sample=live and slots>=1 and remaining["sessions"]>=100 and remaining["arms"]>=1 and remaining["cost"]>=5
    feasible_confirm=live and slots>=2 and remaining["sessions"]>=1600 and remaining["arms"]>=2 and remaining["cost"]>=10 and check_slots>0
    executions=[j["job_id"] for j in state["failed_jobs"] if j["attempts"]<2 and slots>=1 and remaining["arms"]>=1 and remaining["sessions"]>=j["action"]["n"] and remaining["cost"]>=5+len(j["action"]["assortment"])]
    meters=[j["job_id"] for j in state["unverified_jobs"]]
    result={}
    def put(name,ok,reason):
        minimum=3 if name in BUNDLES or name=="start_discovery_task" else 2 if name=="advance_discovery_task" else 1
        if name=="advance_discovery_task" and all(task["status"]=="completed" for task in state["discovery_tasks"]["tasks"]):minimum=1
        if actions_left<minimum+(name!="finish"):ok=False;reason="insufficient_scientific_actions_including_terminal_reserve"
        if not live and name not in {"fit_pool","assess_checks","read_candidate","review_candidate_evidence","finish"}:ok=False;reason="calendar_deadline"
        result[name]={"ready":bool(ok),"reason":"public_preconditions_satisfied" if ok else reason,"scientific_action_charge":minimum}
    for name in ("diagnose_history","read_candidate","finish"):put(name,True,"")
    if "public_evidence_store" in state:put("review_candidate_evidence",True,"")
    if "research_organization" in state:
        for name in ORGANIZATION_SERVICES:put(name,True,"")
    put("open_adaptation",open_catalog or planned==0,"ontology_already_frozen_before_catalog_open")
    put("retrieve_memory",memory,"no_public_archive")
    put("read_memory",memory and bool(sources),"retrieve_public_source_ids_first")
    put("review_memory",memory and bool(sources),"retrieve_public_source_ids_first")
    for name in ("fit_pool","propose_model"):put(name,has_training,"no_verified_released_target_training")
    put("suggest_design",live and remaining["cost"]>=5,"no_remaining_design_allocation")
    for name in ("sample","sample_frontier","sample_and_analyze"):put(name,feasible_sample,"no_shared_sampling_or_pending_capacity")
    if "discovery_tasks" in state:
        tasks=state["discovery_tasks"]["tasks"]
        unfinished=any(task["status"] not in {"completed","submission_failed","closed_unresolved","deadline_unresolved"} for task in tasks)
        put("start_discovery_task",feasible_sample and remaining["sessions"]>=400 and not unfinished,"advance_unfinished_task_or_no_frontier_allocation")
        put("advance_discovery_task",any(task["status"]!="submission_failed" for task in tasks),"no_advanceable_registered_discovery_task")
    for name in ("confirm","confirm_and_analyze"):put(name,feasible_confirm,"no_two_cohort_confirmation_allocation")
    # An empty collection/analysis is legal. Report lack of new work separately;
    # it must not be relabelled as a scientific or execution contradiction.
    put("collect",True,"");put("assess_checks",True,"")
    put("repair",live and bool(executions or meters) and remaining["cost"]>=1,"no_eligible_public_repair")
    put("reopen_research",live and bool(eligible_checks) and state["revisions_used"]<state["max_revisions"],"no_unreleased_actual_refutation_or_revision_allocation")
    return {"version":"scientific-readiness-v0.3-shared-organization" if "research_organization" in state else VERSION if "public_evidence_store" in state else LEGACY_VERSION,"services":result,"remaining":remaining,"pending_slots":slots,"check_slots":check_slots,
        "parameter_domains":{"execution_job_ids":executions,"meter_job_ids":meters,"refutation_check_ids":eligible_checks,
            "source_episode_ids":copy.deepcopy(sources),"candidate_count":state.get("candidate_count"),"stage_sites":copy.deepcopy(state["legal_design_values"]["stage_sites"])},
        "no_new_work":{"collect":not any(state[k] for k in ("pending_jobs","failed_jobs","unverified_jobs")),
            "assess_checks":not any(c["state"] is None for c in state["checks"])},
        "limits":"Public feasibility only; candidate quality, scientific value and future observations are unknown. All legal scientific choices remain available."}


def validate_ready_action(action,state):
    view=readiness(state);tool=action["tool"];args=action["args"]
    if tool not in view["services"] or not view["services"][tool]["ready"]:raise ValueError(f"{tool}: public precondition failed ({view['services'].get(tool,{}).get('reason','unknown')})")
    domains=view["parameter_domains"]
    if "candidate_id" in args:
        cid=args["candidate_id"];count=domains["candidate_count"]
        if not isinstance(cid,str) or not re.fullmatch(r"C\d{4,}",cid):raise ValueError("invalid immutable candidate ID")
        if count is not None and not 0<=int(cid[1:])<count:raise ValueError("candidate not registered in current public prefix")
    if tool in ORGANIZATION_SERVICES:
        analyses={a["analysis_id"] for a in state["public_evidence_store"]["analysis_cards"]}
        if not set(args["analysis_ids"])<=analyses:raise ValueError("unknown available analysis reference")
        if tool=="dispatch_research_context":
            org=state["research_organization"]
            if args["target_id"] not in {c["context_id"] for c in org["contexts"]}:raise ValueError("unknown existing organization context")
            if args["kind"]=="expand" and (org["contract"]["mode"]!="C" or len(org["contexts"])>=org["contract"]["max_C_nodes"]):raise ValueError("no C expansion allocation")
    if tool in {"read_memory","review_memory"}:
        ids=[args["episode_id"]] if tool=="read_memory" else args["episode_ids"]
        if not set(ids)<=set(domains["source_episode_ids"]):raise ValueError("unknown public source episode ID")
    if tool=="repair":
        key="execution_job_ids" if args["kind"]=="execution" else "meter_job_ids"
        if args["job_id"] not in domains[key]:raise ValueError("repair job/kind does not match current public receipt")
        if args["kind"]=="execution":
            job=next(j for j in state["failed_jobs"] if j["job_id"]==args["job_id"]);d=job["action"]
            if view["pending_slots"]<1 or view["remaining"]["sessions"]<d["n"] or view["remaining"]["arms"]<1 or view["remaining"]["cost"]<5+len(d["assortment"]):raise ValueError("repair has insufficient public launch allocation")
    if tool=="reopen_research" and args["check_id"] not in domains["refutation_check_ids"]:raise ValueError("no actual unreleased refutation for this check")
    if tool=="collect" and args["refit"] and not state["training_evidence_ids"] and not any(state[k] for k in ("pending_jobs","failed_jobs","unverified_jobs")):
        raise ValueError("collection has no target evidence that can become fit-ready")
    designs=args.get("designs",[]) if tool in {"sample","sample_and_analyze"} else [args["design"]] if tool in {"confirm","confirm_and_analyze"} and "design" in args else []
    for d in designs:
        if d["stage"] not in domains["stage_sites"] or d["site"] not in domains["stage_sites"][d["stage"]]:raise ValueError("design stage/site not currently received and legal")
        ids={p["id"] for p in state["catalogs"][d["stage"]]}
        if not set(d["assortment"])<=ids:raise ValueError("design product ID not in that received catalog")
    if designs:
        count=len(designs) if tool in {"sample","sample_and_analyze"} else 2
        sessions=sum(d["n"] for d in designs) if tool in {"sample","sample_and_analyze"} else 1600
        cost=sum(5+len(d["assortment"]) for d in designs) if tool in {"sample","sample_and_analyze"} else 2*(5+len(designs[0]["assortment"]))
        if count>view["pending_slots"] or count>view["remaining"]["arms"] or sessions>view["remaining"]["sessions"] or cost>view["remaining"]["cost"]:raise ValueError("design batch exceeds shared public allocation")
    if tool=="sample_frontier":
        count=args["count"]
        if count>view["pending_slots"] or count>view["remaining"]["arms"] or count*400>view["remaining"]["sessions"] or count*5>view["remaining"]["cost"]:raise ValueError("frontier batch exceeds public necessary allocation")
    if tool=="start_discovery_task":
        count=args["count"]
        if count>view["pending_slots"] or count>view["remaining"]["arms"] or count*400>view["remaining"]["sessions"] or count*5>view["remaining"]["cost"]:raise ValueError("task batch exceeds public necessary allocation")
    if tool=="advance_discovery_task":
        task=next((task for task in state["discovery_tasks"]["tasks"] if task["task_id"]==args["task_id"]),None)
        if task is None or task["status"]=="submission_failed":raise ValueError("unknown or failed submission task")
        if task["status"]!="completed" and state["scientific_actions_limit"]-state["scientific_actions_used"]<3:raise ValueError("task worker requires two actions and terminal reserve")
    return view


def validate_request_bindings(action,request_state):
    """A batch may consume new receipts, but cannot guess unseen object IDs."""
    args=action["args"];tool=action["tool"]
    if tool=="advance_discovery_task" and args["task_id"] not in {task["task_id"] for task in request_state.get("discovery_tasks",{}).get("tasks",[])}:raise ValueError("task ID was not received before this API request")
    if tool in ORGANIZATION_SERVICES:
        if not set(args["analysis_ids"])<={a["analysis_id"] for a in request_state["public_evidence_store"]["analysis_cards"]}:raise ValueError("analysis was not available before this API request")
        if tool=="dispatch_research_context" and args["target_id"] not in {c["context_id"] for c in request_state["research_organization"]["contexts"]}:raise ValueError("context was not created before this API request")
    if "candidate_id" in args:
        cid=args["candidate_id"];count=request_state.get("candidate_count")
        if count is not None and (not isinstance(cid,str) or not re.fullmatch(r"C\d{4,}",cid) or int(cid[1:])>=count):raise ValueError("candidate ID was not registered before this API request")
    if tool in {"read_memory","review_memory"}:
        ids=[args["episode_id"]] if tool=="read_memory" else args["episode_ids"]
        if not set(ids)<=set(request_state["available_memory_episode_ids"]):raise ValueError("source IDs were not received before this API request")
    if tool=="repair" and args["job_id"] not in {j["job_id"] for key in ("failed_jobs","unverified_jobs") for j in request_state[key]}:raise ValueError("repair receipt was not received before this API request")
    if tool=="reopen_research" and args["check_id"] not in {c["check_id"] for c in request_state["checks"]}:raise ValueError("check ID was not received before this API request")
    designs=args.get("designs",[]) if tool in {"sample","sample_and_analyze"} else [args["design"]] if tool in {"confirm","confirm_and_analyze"} and "design" in args else []
    for d in designs:
        if d["stage"] not in request_state["catalogs"] or not set(d["assortment"])<={p["id"] for p in request_state["catalogs"][d["stage"]]}:raise ValueError("catalog/product IDs were not received before this API request")
