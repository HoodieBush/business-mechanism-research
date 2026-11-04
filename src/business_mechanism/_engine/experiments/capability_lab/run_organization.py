"""End-to-end A/B/C development pilot, one science ledger per task.

All LLMs choose their scientific actions from the start. Local organization
actions are charged; contexts never get a new API, sample or alpha allocation.
"""
import argparse
import copy
import json
from pathlib import Path
import time

from choice_world import ChoiceWorld
from model_protocol import usage_summary
from operating_eval import evaluate
from research_action_schema import SCHEMA
from research_actor import ScienceActor
from research_runtime import ResearchRuntime
from run_research import CONFIG
from run_scientific import agent_view
from semantic_compile import compile_structured
from temporal_lab import TemporalLab, digest

ROOT=Path(__file__).resolve().parent
VERSION="organization-pilot-v0.2-consistent-native-and-reference-ablation"
STRATEGIES=["numeric_full","A","B","C"]


def filename(t):return f"{t['strategy']}_{t['family']}_{t['profile']}_s{t['seed']}.json"


def numeric(rt, save):
    def call(tool,args=None):
        response=rt.call(tool,{} if args is None else args,"完整字典数值对照。","区分公开功能与范围，独立检查。")
        save()
        if not response["ok"]:raise ValueError(response["error"])
    call("diagnose_history");call("open_adaptation")
    catalog=rt.gateway.public_catalog("source")
    h=next(p["id"] for p in catalog if p["functions"]["heating"] and not p["functions"]["utensils"])
    u=next(p["id"] for p in catalog if p["functions"]["utensils"] and not p["functions"]["heating"])
    both=next(p["id"] for p in catalog if p["functions"]["heating"] and p["functions"]["utensils"])
    for arms in (([],[h],[u]),([h,u],[both])):
        call("sample",{"candidate_id":rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":a,"n":400} for a in arms],"rationale":"公开析因暖场。"})
        call("collect",{"until":"all","repair":True,"refit":len(arms)==2,"assess":False})
    for count in (3,3,1):
        if rt.gateway.clock>=rt.gateway.deadline:break
        call("sample_frontier",{"candidate_id":rt.pool[0],"count":count,"rationale":"共同公开分歧/特征覆盖。"})
        call("collect",{"until":"all","repair":True,"refit":True,"assess":False})
    for _ in range(6):
        if rt.gateway.clock>=rt.gateway.deadline:break
        call("confirm",{"candidate_id":rt.pool[0],"rationale":"原总错误额度内独立确认。"})
        call("collect",{"until":"all","repair":True,"refit":False,"assess":True})
        c=rt.checks[-1]
        if rt.gateway.clock<rt.gateway.deadline and c["result"] and c["result"]["state"]=="contradicted" and rt.revisions<2:
            call("reopen_research",{"check_id":c["check_id"],"rationale":"实际反驳后共同重估。","refit":True})
    call("finish",{"candidate_id":rt.pool[0],"claims":"仅原独立检查列出条件；结构唯一性/未测范围未决。","unresolved":True,"stop_reason":"数值策略预算流程结束。"})


def run(task,spec):
    path=ROOT/"results"/spec["phase"]/filename(task)
    if path.exists():raise ValueError("result exists")
    limits=spec["api_limits"];mode="A" if task["strategy"] in {"numeric_full","native_control","reference_contract","discovery_tasks","confirmation_phase"} else task["strategy"]
    actor_features=copy.deepcopy(spec.get("actor_features",{}).get(task["strategy"],{}))
    lab=TemporalLab(ChoiceWorld(task["seed"],task["family"],"none","structured",spec["price"]),task["profile"],spec["deadline"])
    lab.limits.update(api_calls=limits["calls"],api_tokens=limits["reported_tokens"])
    rt=ResearchRuntime(lab,terminal_policy=spec["terminal_policy"],organization_mode=mode,use_discovery_tasks=actor_features.get("use_discovery_tasks",False))
    result={"phase":spec["phase"],"version":VERSION,"strategy":task["strategy"],"organization_mode":mode,"actor_features":actor_features,
        "private_configuration":{k:task[k] for k in ("seed","family","profile")}|{"price":spec["price"],"deadline":spec["deadline"]},
        "legal_input":copy.deepcopy(rt.initial),"model_config":CONFIG,"model_calls":[],"status":"running",
        "scientific_protocol":{"max_checks":6,"n_per_cohort":800,"cohorts_per_check":2,"total_alpha":.05,"tolerance":.05,
            "max_revisions":2,"max_scientific_actions":64,"api_limits":limits,"LLM_scripted_warmup":False,
            "api_and_cpu_wall_time_excluded_from_research_ticks":True}}
    actors={};start=time.monotonic()
    def save():
        result.update(research=rt.snapshot(),gateway_events=copy.deepcopy(lab.events),used=copy.deepcopy(lab.used),
            public_final_state=lab.public_state(),model_usage=usage_summary(result["model_calls"]))
        if actors:result["reading_notebooks"]={k:a.notebook.snapshot() for k,a in actors.items()}
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    try:
        if task["strategy"]=="numeric_full":numeric(rt,save)
        else:
            errors=0
            while not rt.closed and rt.calls<rt.max_calls-1 and lab.tool_calls<lab.limits["tool_calls"]-2:
                context_id=rt.organization.current
                if context_id not in actors:actors[context_id]=ScienceActor(rt,agent_view,SCHEMA,limits,wire_mode="native",state_aware=True,**{k:v for k,v in actor_features.items() if k!="use_discovery_tasks"})
                actor=actors[context_id]
                record=actor.next(result["model_calls"])
                if record is None:
                    result["coordinator_stop_reason"]="api_allocation_exhausted_or_preflight"
                    result["api_stop_preflight"]=copy.deepcopy(actor.last_preflight);break
                result["model_calls"].append(record);save()
                if spec.get("progress_reports"):print(json.dumps({"task":path.name,"api_calls":result["model_usage"]["api_calls"],"reported_tokens":result["model_usage"]["total_tokens"],
                    "science_actions":rt.calls,"checks":len(rt.checks),"completed_checks":sum(c["result"] is not None for c in rt.checks)}),flush=True)
                invalid="submission_error" in record or not all(f.get("ok",False) for f in record.get("tool_feedbacks",[]))
                errors=errors+1 if invalid else 0
                if errors>=3:result["coordinator_stop_reason"]="three_consecutive_invalid_actions";break
                if lab.clock>=lab.deadline:result["coordinator_stop_reason"]="calendar_deadline";break
            if not rt.closed:
                cid=rt.checks[-1]["candidate_id"] if rt.checks else rt.pool[0] if rt.pool else rt.initial_candidate
                response=rt.call("finish",{"candidate_id":cid,"claims":"策略停止，仅实际独立所列条件可评价，其它范围未决。",
                    "unresolved":True,"stop_reason":result.get("coordinator_stop_reason","scientific_action_budget")},"事前模型冻结终止规则。","不追加科学研究，按已声明规则收取原任务。")
                result["terminal_fallback"]=response
                if not response["ok"]:raise ValueError(response["error"])
        result.update(frozen_final=copy.deepcopy(rt.final["frozen_final"]),mechanism_card=copy.deepcopy(rt.final["mechanism_card"]),
            frozen_expression_sha256=digest(lab.final["model"]["expression"]))
        deployment=lab.call("deployment_catalog",{})
        facts=compile_structured(lab.public_catalog("source")+(lab.public_catalog("adaptation") if lab.transfer_open else [])+deployment)
        result["deployment_physical_facts"]=facts;result["deployed_model"]={"role_patterns":facts["role_patterns"],"expression":copy.deepcopy(lab.final["model"]["expression"])}
        result["private_score"]=evaluate(lab._core._world,lab.final["model"],result["deployed_model"])
        result["status"]="actor_budget_stopped" if "terminal_fallback" in result else "deadline_unresolved" if lab.clock>=lab.deadline else "finished_scoped"
    except Exception as error:result.update(status="execution_failure",error=type(error).__name__+": "+str(error))
    result["elapsed_seconds"]=time.monotonic()-start;save()
    print(json.dumps({"file":path.name,"status":result["status"],"contexts":len(rt.organization.contexts),"notes":len(rt.organization.notes),
        "checks":len(rt.checks),"completed_checks":sum(c["result"] is not None for c in rt.checks),"usage":result["model_usage"],"error":result.get("error")}),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--spec",required=True,type=Path);args=ap.parse_args();spec=json.loads(args.spec.read_text())
    for seed in spec["seeds"]:
        for family in spec["families"]:
            for profile in spec["profiles"]:
                for strategy in spec["strategies"]:run(dict(seed=seed,family=family,profile=profile,strategy=strategy),spec)
