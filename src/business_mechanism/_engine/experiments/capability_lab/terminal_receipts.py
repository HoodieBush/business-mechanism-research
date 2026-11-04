"""Deterministic completion of committed jobs after research decisions close."""
import copy

VERSION="terminal-receipts-v0.1-frozen-decision-settlement"
POLICIES={"received_only","settle_committed"}


def settle(runtime,commitment,max_steps=100):
    gateway=runtime.gateway;start=copy.deepcopy(gateway.used);trace=[];reason="committed_jobs_complete"
    jobs=set(commitment["job_ids"])
    def public():
        value=gateway.public_state()
        if any(j["job_id"] not in jobs for key in ("pending_jobs","failed_jobs","unverified_jobs") for j in value[key]):raise ValueError("uncommitted job after decision close")
        return value
    def call(tool,args):
        if gateway.tool_calls>=gateway.limits["tool_calls"]-2:return False
        response=gateway.call(tool,args);trace.append({"tool":tool,"args":copy.deepcopy(args),"response":copy.deepcopy(response),"available_at":gateway.clock})
        runtime._sync();return True
    for _ in range(max_steps):
        state=public()
        if not any(state[k] for k in ("pending_jobs","failed_jobs","unverified_jobs")):break
        if gateway.clock>=gateway.deadline:reason="calendar_deadline";break
        if gateway.tool_calls>=gateway.limits["tool_calls"]-2:reason="gateway_reserve_for_finish_and_deployment";break
        progress=False
        for job in state["failed_jobs"]:
            if job["attempts"]>=2:continue
            slots=gateway.max_pending-sum(j["status"]=="pending" for j in public()["pending_jobs"])
            a=job["plan"]["action"];used=gateway.used
            if slots and used["sessions"]+a["n"]<=gateway.limits["sessions"] and used["arms"]+1<=gateway.limits["arms"] and used["cost"]+5+len(a["assortment"])<=gateway.limits["cost"]:
                progress=call("retry_execution",{"job_id":job["job_id"]}) or progress
        for job in public()["unverified_jobs"]:
            if gateway.used["cost"]<gateway.limits["cost"]:progress=call("reconcile_measurement",{"job_id":job["job_id"]}) or progress
        if public()["pending_jobs"]:progress=call("await_next",{}) or progress
        if not progress:reason="unresolved_execution_or_resource_allocation";break
    else:reason="bounded_settlement_steps"
    runtime._sync();runtime._assess();state=public()
    unresolved=[j["job_id"] for key in ("pending_jobs","failed_jobs","unverified_jobs") for j in state[key]]
    return {"version":VERSION,"reason":reason,"used_before":start,"used_after":copy.deepcopy(gateway.used),"trace":trace,
        "unresolved_job_ids":sorted(set(unresolved)),"extra_api_calls":0,"new_designs":0,"new_hypotheses":0,"parameter_refits":0}
