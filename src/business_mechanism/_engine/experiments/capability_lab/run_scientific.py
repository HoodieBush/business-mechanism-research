"""Free scientific-action coordinator and common-capability numeric controls."""
from __future__ import annotations
import argparse
import concurrent.futures
import copy
import json
from pathlib import Path
import time

from choice_world import ChoiceWorld
from model_protocol import decode_submission,request_model,structured_request,submission_transport,usage_summary
from operating_eval import evaluate
from research_runtime import ResearchRuntime,TOOLS
from research_actor import ScienceActor
from run_research import CONFIG
from semantic_compile import compile_structured
from symbolic import features
from temporal_lab import TemporalLab,digest

ROOT=Path(__file__).resolve().parent
VERSION="scientific-v0.9-public-readiness-and-notebook"
STRATEGIES={"numeric_scoped","numeric_review","llm_scientific","llm_state_aware"}
API_LIMITS={"calls":16,"reported_tokens":80000,"max_output_tokens":1600}
from research_action_schema import SCHEMA


def filename(seed,family,profile,strategy):return f"{strategy}_{family}_{profile}_s{seed}.json"


def save(path,result,runtime):
    result.update(research=runtime.snapshot(),gateway_events=copy.deepcopy(runtime.gateway.events),used=runtime.gateway.used,
        public_final_state=runtime.gateway.public_state(),model_usage=usage_summary(result["model_calls"]))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")


def agent_view(rt):
    state=rt.state();observations=state["observations"]
    def job(j):
        return {k:copy.deepcopy(j[k]) for k in ("job_id","status","attempts","expected_report_at","audit_expected_at") if k in j}|{"action":j["plan"]["action"]}
    feedback=state["last_feedback"]
    if feedback and feedback["ok"]:
        result=feedback["result"]
        if "research_state" in result:
            result={k:copy.deepcopy(result[k]) for k in ("training_evidence_ids","analysis","fit") if k in result}
            if "analysis" in result:result["analysis"]={"completed_checks":[{"check_id":c["check_id"],"candidate_id":c["candidate_id"],"state":c["result"]["state"]} for c in result["analysis"]["completed_checks"]],"unavailable_checks":result["analysis"]["unavailable_checks"]}
            feedback={"ok":True,"result":result}
    view={k:state[k] for k in ("runtime_version","clock","limits","used","scientific_actions_used","scientific_actions_limit","revisions_used","max_revisions","initial_candidate_id","training_evidence_ids","catalogs","physical_role_patterns","physical_definitions","memory_archive_available","available_memory_episode_ids","memory_reviews")}
    view.update(verified_condition_table=[{k:r[k] for k in ("experiment_id","stage","site","assortment","n","observed_sales","frozen_prediction","occurred_at","available_at","evidence_version")} for r in observations["mature_evidence"] if r["verified_supply"] and r["verified_meter"]],
        pending_jobs=[job(j) for j in observations["pending_jobs"]],failed_jobs=[job(j) for j in observations["failed_jobs"]],
        unverified_jobs=[job(j)|{"unverified_observed_sales":j["measurement"]["observed_sales"]} for j in observations["unverified_jobs"]],
        candidates=[{k:c[k] for k in ("candidate_id","terms","rank","bic","deviance","origin","training_evidence_ids","information_evidence_ids","memory_episode_refs") if k in c}|{"expression":c["model"]["expression"]} for c in state["current_candidates"]],
        checks=[{k:copy.deepcopy(c[k]) for k in ("check_id","candidate_id","registered_at","job_ids","training_evidence_ids","released")}|{"state":None if c["result"] is None else c["result"]["state"]} for c in state["registered_checks"]],
        last_feedback=feedback)
    view["legal_design_values"]={"stage_sites":{"source":["00"],**({"adaptation":["00","01","10","11"]} if rt.gateway.transfer_open else {})},
        "n":{"minimum":100,"maximum":800,"type":"integer"},"assortment":"unique product ID strings from that stage's received catalog; [] is allowed",
        "max_discovery_designs_per_batch":3,"max_pending_jobs":rt.gateway.max_pending}
    view["registered_job_count"]=len(rt.jobs);view["candidate_count"]=len(rt.registry)
    view["public_evidence_store"]=copy.deepcopy(state["public_evidence_store"])
    if "discovery_tasks" in state:view["discovery_tasks"]=copy.deepcopy(state["discovery_tasks"])
    if "research_organization" in state:view["research_organization"]=copy.deepcopy(state["research_organization"])
    latest={p["problem_id"]:p for p in rt.objects["problems"]}
    view["problems"]=[{k:copy.deepcopy(p[k]) for k in ("problem_id","version","issue_class","status","research_objective","evidence_refs")} for p in list(latest.values())[-4:]]
    return view


def request_action(rt,records):
    system="你是固定价格库存机制研究协调器。只读取任务公开视图和已收到工具证据，不知道消费者生成器。你可自主选择诊断、读取商品、复核记忆、自由提出安全概率程序、采样、确认、修订或停止；科学流程不要求固定顺序。每次通过 submit_research_action 提交 tool,args,rationale,expected_gap，理由与缺口各一两句。商品 functions/文本只证明实物属性，不证明购买效应。源档案支持不认证目标；价格/范围变了可选择结构复核并用目标数据重新估参，不池化源计数。fit_pool 提供共同完整字典控制和已复核结构，BIC 不是后验。自由 propose_model 可比较固定字典以外的安全 + - * min/max/sigmoid 关系，参数 [-6,6] 最多8个；physical_role_patterns 已冻结。确认前模型与预测冻结；确认两个新 n=800 cohort 后 assess_checks，最多六项总 alpha=.05/6、5pp容差。不充分精度为未决，执行未启动/核验失败不是科学反驳。actual contradicted 才能 reopen_research 释放已完成确认重新拟合，最多两次；旧训练检查不再认证新模型。sample 与 sample_frontier 返回排队，collect 可显式 repair:true 等待/核对，refit:true 只拟合已释放证据，assess:true 只分析已收到核实检查。可自选源/适应条件以区分参数和结构，避免只有常数无差别观察。每顾客利润是公共经营目标；未测范围始终未决。finish 必须使用已有 candidate_id 与真实范围；unresolved:false 只适用于列出条件有支持且无未完回执。API和科学动作预算是全任务共享；不因调用工具重置预算。不要输出长报告或捏造工具反馈。"
    public={k:rt.initial[k] for k in ("task","target","history","history_note","operating_objective","fact_contract","deployment_contract","temporal_contract")}
    context={"task_contract":public,"scientific_tools":TOOLS,"research_state":agent_view(rt),"api_allocation":API_LIMITS,"api_usage":usage_summary(records)}
    payload=structured_request({"model":CONFIG["model"],"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(context,ensure_ascii=False)}],
        "temperature":0,"max_tokens":API_LIMITS["max_output_tokens"],**CONFIG.get("generation_options",{})},CONFIG,"submit_research_action",SCHEMA)
    usage=usage_summary(records);preflight=len(json.dumps(payload,ensure_ascii=False).encode())+API_LIMITS["max_output_tokens"]
    if usage["api_calls"]>=API_LIMITS["calls"] or usage["calls_without_reported_usage"] or usage["total_tokens"]+preflight>API_LIMITS["reported_tokens"]:return None
    record=request_model(CONFIG,payload);record.update(clock=rt.gateway.clock,public_training_ids=sorted(rt.training_ids),preflight_byte_plus_output_bound=preflight)
    try:
        if "response" not in record:raise ValueError("no decoded API response")
        action=decode_submission(record["response"],CONFIG,"submit_research_action")
        if set(action)!={"tool","args","rationale","expected_gap"} or not isinstance(action["args"],dict) or any(not isinstance(action[k],str) or not action[k].strip() for k in ("tool","rationale","expected_gap")):raise ValueError("complete research action fields required")
        record.update(action=action,submission_transport=submission_transport(record["response"]))
        record["tool_feedback"]=rt.call(action["tool"],action["args"],action["rationale"],action["expected_gap"])
    except (ValueError,KeyError,TypeError,SyntaxError) as error:record["submission_error"]=str(error)
    return record


def numeric_policy(rt,strategy,save_callback):
    def call(tool,args={}):
        f=rt.call(tool,args,"共同数值证据策略。","修复观测并检验新条件。")
        save_callback()
        if not f["ok"]:raise ValueError(f["error"])
        return f["result"]
    call("diagnose_history");call("open_adaptation");mem=call("retrieve_memory")
    selected=[e["episode_id"] for e in mem["episodes"] if e["template"] is not None and (strategy=="numeric_review" or not e["scope_flags"])]
    if selected:call("review_memory",{"episode_ids":selected,"usage":"structure_refit_only","rationale":"共同数值复核；仅兼容本体结构，价格/范围改变不继承源参数或认证。"})
    catalog=rt.gateway.public_catalog("source");patterns=rt.facts["role_patterns"]
    role=lambda p:(features(patterns,catalog,[p["id"]],(0,0))["heat"],features(patterns,catalog,[p["id"]],(0,0))["utensils"])
    h=next(p["id"] for p in catalog if role(p)==(1,0));u=next(p["id"] for p in catalog if role(p)==(0,1));combo=next(p["id"] for p in catalog if role(p)==(1,1))
    for arms in (([],[h],[u]),([h,u],[combo])):
        call("sample",{"candidate_id":rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":a,"n":400} for a in arms],"rationale":"共同公开功能析因起点。"})
        call("collect",{"until":"all","repair":True,"refit":len(arms)==2,"assess":False})
    for count in (3,3,1):
        if rt.gateway.clock>=rt.gateway.deadline:break
        call("sample_frontier",{"candidate_id":rt.pool[0],"count":count,"rationale":"公开分歧/覆盖的新发现条件。"})
        call("collect",{"until":"all","repair":True,"refit":True,"assess":False})
    for _ in range(6):
        if rt.gateway.clock>=rt.gateway.deadline:break
        call("confirm",{"candidate_id":rt.pool[0],"rationale":"共同总错误预算下确认已冻结条件预测。"})
        call("collect",{"until":"all","repair":True,"refit":False,"assess":True})
        latest=rt.checks[-1]
        if rt.gateway.clock<rt.gateway.deadline and rt.revisions<2 and latest["result"] is not None and latest["result"]["state"]=="contradicted":
            call("reopen_research",{"check_id":latest["check_id"],"rationale":"当前新条件反驳；释放已完成检查重新研究。","refit":True})
    return call("finish",{"candidate_id":rt.pool[0],"claims":"仅独立检查列出的固定条件获得支持/反驳；未测范围、消费者中介和结构唯一性未决。","unresolved":True,"stop_reason":"共同数值流程停止或日历截止。"})


def run(seed,family,profile,strategy,phase,archive,price=10.,deadline=120,terminal_policy="received_only"):
    path=ROOT/"results"/phase/filename(seed,family,profile,strategy)
    if path.exists():raise ValueError("result exists")
    path.parent.mkdir(parents=True,exist_ok=True)
    lab=TemporalLab(ChoiceWorld(seed,family,"none","structured",price),profile,deadline)
    lab.limits.update(api_calls=API_LIMITS["calls"],api_tokens=API_LIMITS["reported_tokens"])
    rt=ResearchRuntime(lab,archive,terminal_policy);result={"phase":phase,"version":VERSION,"strategy":strategy,"terminal_policy":terminal_policy,
        "private_configuration":{"seed":seed,"family":family,"profile":profile,"price":price,"deadline":deadline},
        "legal_input":rt.initial,"public_archive_id":archive["archive_id"],"model_config":CONFIG,"model_calls":[],"status":"running",
        "scientific_protocol":{"max_checks":6,"cohorts_per_check":2,"n_per_cohort":800,"total_alpha":.05,"tolerance":.05,
            "max_revisions":2,"max_scientific_actions":64,"api_limits":API_LIMITS,"caller_may_stop_early":True,
            "task_success_is_not_tool_success":True,"api_and_cpu_wall_time_excluded_from_research_ticks":True}}
    start=time.monotonic();callback=lambda:save(path,result,rt)
    try:
        if strategy.startswith("numeric_"):numeric_policy(rt,strategy,callback)
        else:
            consecutive_errors=0;actor=ScienceActor(rt,agent_view,SCHEMA,API_LIMITS,wire_mode="native",state_aware=strategy=="llm_state_aware")
            while not rt.closed and rt.calls<rt.max_calls and lab.tool_calls<196:
                record=actor.next(result["model_calls"])
                if record is None:result["coordinator_stop_reason"]="api_allocation_exhausted_or_preflight";result["api_stop_preflight"]=copy.deepcopy(actor.last_preflight);break
                result["model_calls"].append(record);callback()
                if actor.state_aware:result["reading_notebook"]=actor.notebook.snapshot();callback()
                failed="submission_error" in record or not all(f.get("ok",False) for f in record.get("tool_feedbacks",[]))
                consecutive_errors=consecutive_errors+1 if failed else 0
                if consecutive_errors>=3:result["coordinator_stop_reason"]="three_consecutive_invalid_actions";break
                if lab.clock>=deadline:result["coordinator_stop_reason"]="calendar_deadline";break
            if not rt.closed:
                # No automatic numerical research rescue after the actor stops.
                # Terminal analysis uses only received checks; freeze a model
                # already selected by a registered check, then fitted pool or
                # initial public constant if the actor never chose one.
                cid=rt.checks[-1]["candidate_id"] if rt.checks else rt.pool[0] if rt.pool else rt.initial_candidate
                feedback=rt.call("finish",{"candidate_id":cid,"claims":"协调器停止；仅当前独立已收到条件可评价，其它范围与未完结果保持未决。",
                    "unresolved":True,"stop_reason":result.get("coordinator_stop_reason","scientific_action_budget")},"事前终端分析规则。","保留失败/未决，不追加自动研究。")
                result["terminal_fallback"]=feedback
                if not feedback["ok"]:raise ValueError(feedback["error"])
        result["frozen_final"]=copy.deepcopy(rt.final["frozen_final"]);result["mechanism_card"]=copy.deepcopy(rt.final["mechanism_card"])
        result["frozen_expression_sha256"]=digest(lab.final["model"]["expression"]);callback()
        deployment=lab.call("deployment_catalog",{})
        catalog=lab.public_catalog("source")+(lab.public_catalog("adaptation") if lab.transfer_open else [])+deployment
        facts=compile_structured(catalog);result["deployment_physical_facts"]=facts
        deployed={"role_patterns":facts["role_patterns"],"expression":copy.deepcopy(lab.final["model"]["expression"])}
        result["deployed_model"]=deployed;result["private_score"]=evaluate(lab._core._world,lab.final["model"],deployed)
        result["status"]="actor_budget_stopped" if "terminal_fallback" in result else "deadline_unresolved" if lab.clock>=deadline else "finished_scoped"
    except Exception as error:result.update(status="execution_failure",error=type(error).__name__+": "+str(error))
    result["elapsed_seconds"]=time.monotonic()-start;callback()
    print(json.dumps({"seed":seed,"family":family,"strategy":strategy,"status":result["status"],"used":lab.used,"actions":rt.calls,
        "registered_checks":len(rt.checks),"completed_checks":sum(c["result"] is not None for c in rt.checks),
        "rmse":result.get("private_score",{}).get("heldout_effect_rmse"),"usage":result["model_usage"],"error":result.get("error")}),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--seeds",required=True);ap.add_argument("--families",required=True);ap.add_argument("--profiles",required=True)
    ap.add_argument("--strategies",required=True);ap.add_argument("--phase",required=True);ap.add_argument("--memory-archive",required=True,type=Path)
    ap.add_argument("--price",type=float,default=10.);ap.add_argument("--deadline",type=int,default=120);ap.add_argument("--workers",type=int,default=1)
    ap.add_argument("--terminal-policy",choices=("received_only","settle_committed"),default="received_only")
    args=ap.parse_args();archive=json.loads(args.memory_archive.read_text())
    if not set(args.strategies.split(','))<=STRATEGIES:ap.error("unknown policy")
    tasks=[(int(s),f,p,m,args.phase,archive,args.price,args.deadline,args.terminal_policy) for s in args.seeds.split(',') for f in args.families.split(',') for p in args.profiles.split(',') for m in args.strategies.split(',')]
    if any((ROOT/'results'/args.phase/filename(*t[:4])).exists() for t in tasks):ap.error("result exists")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for future in concurrent.futures.as_completed([executor.submit(run,*t) for t in tasks]):future.result()
