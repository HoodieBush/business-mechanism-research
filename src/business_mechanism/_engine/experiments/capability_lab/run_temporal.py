"""Bounded public-feedback coordination under a shared research calendar.

All policies use the same public numeric inference and registered checks. The
LLM treatment chooses scheduling actions only; it is not a full multi-agent
framework. API wall time is reported separately from simulated research ticks.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import copy
import json
from pathlib import Path
import time

from choice_world import ChoiceWorld
from confirmation import assess
from mechanism_state import temporal_card
from model_protocol import decode_submission,request_model,structured_request,submission_transport,usage_summary
from numeric_pool import numeric_pool
from operating_eval import evaluate
from run_research import CONFIG
from semantic_compile import compile_structured
from symbolic import features,plan
from temporal_lab import TemporalLab,digest
from temporal_plan import register_plan

ROOT=Path(__file__).resolve().parent
VERSION="temporal-v0.3-separate-calendar-and-conditional-state"
STRATEGIES={"numeric_serial","numeric_async","llm_async_coordinator"}
API_PHASE_LIMITS={"common_warm":2,"adaptive_discovery":3,"confirmation":3}
SCHEDULE_SCHEMA={"type":"object","properties":{"choice_id":{"type":"string"},"rationale":{"type":"string"},
    "expected_feedback":{"type":"string"}},"required":["choice_id","rationale","expected_feedback"],"additionalProperties":False}


def filename(seed,family,profile,strategy):return f"{strategy}_{family}_{profile}_s{seed}.json"


def save(path,result,lab):
    result.update(events=copy.deepcopy(lab.events),public_final_state=lab.public_state(),used=lab.used,
        model_usage=usage_summary(result["model_calls"]))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")


class Coordinator:
    def __init__(self,lab,result,path):
        self.lab=lab;self.result=result;self.path=path
        self.strategy=result["strategy"];self._pool_key=None;self._pool=None

    def fit(self,patterns):
        rows=self.lab.verified_observations()
        key=digest([(r["experiment_id"],r["evidence_version"],k) for r,k in rows])
        if key!=self._pool_key:
            self._pool=numeric_pool(self.lab,patterns,True);self._pool_key=key
            self.result["research_versions"].append({"phase":"public_fit_snapshot","clock":self.lab.clock,
                "training_evidence_ids":[r["experiment_id"] for r,_ in rows],"candidate_pool":copy.deepcopy(self._pool)})
            self.lab._record("public_fit_snapshot",{"training_evidence_ids":[r["experiment_id"] for r,_ in rows],
                "candidate_models_sha256":digest([r["model"] for r in self._pool])})
        return self._pool

    def choose(self,options,pool,phase):
        selected=options[0];record={"phase":phase,"clock":self.lab.clock,"options":copy.deepcopy(options),
            "available_training_ids":[r["experiment_id"] for r,_ in self.lab.verified_observations()],"policy":"numeric_priority"}
        if self.strategy=="llm_async_coordinator":
            state=self.lab.public_state()
            context={"task":self.result["legal_input"]["task"],"temporal_contract":self.result["legal_input"]["temporal_contract"],
                "operating_objective":self.result["legal_input"]["operating_objective"],"scientific_phase":phase,
                "clock":state["clock"],"deadline":state["deadline"],"limits":state["limits"],"used":state["used"],
                "public_catalogs":{stage:self.lab.public_catalog(stage) for stage in ("source","adaptation") if stage=="source" or self.lab.transfer_open},
                "training_scope":state["training_scope"],
                "pending_jobs":[{k:j[k] for k in ("job_id","status","expected_report_at","audit_expected_at") if k in j}|
                    {"registered_action":copy.deepcopy(j["plan"]["action"]),"claim_id":j["plan"]["claim_id"],"purpose":j["plan"]["analysis"]["purpose"]} for j in state["pending_jobs"]],
                "failed_jobs":[{"job_id":j["job_id"],"status":j["status"],"attempts":j["attempts"]} for j in state["failed_jobs"]],
                "unverified_jobs":[{"job_id":j["job_id"],"status":j["status"]} for j in state["unverified_jobs"]],
                "verified_evidence":[{k:r[k] for k in ("experiment_id","stage","site","assortment","n","observed_sales","frozen_prediction","occurred_at","available_at","evidence_version")} for r,_ in self.lab.verified_observations()],
                "frozen_or_current_candidates":[{k:r[k] for k in ("model","bic","rank") if k in r} for r in (pool or [])[:2]],
                "legal_choices":options}
            system="你负责机制研究的事件调度。仅依据当前已收到的公开证据，从 legal_choices 选一个 choice_id，给一两句 rationale 和 expected_feedback。目标是在共享日历与操作限额内得到有信息且核实的证据，避免不必要等待；等待也可能使后续自适应设计更好。未启动失败不是机制反证；核验失败须修复才能拟合。pending_jobs.registered_action 是已排队设计，legal_choices 中的 launch 是尚未启动的新设计；不同商品组合不能因同 site 就当作重复。public_catalogs.functions 是实物功能，不证明购买效应。排队设计不含未来结果。common_warm 是固定析因起点；adaptive_discovery 可用当前成熟证据规划；confirmation 的关系与训练范围已经冻结，新增检查不用于当前模型拟合。只能选择调度，不能改科学计划或捏造结果。截止时无回执保持未决。调用 submit_schedule 提交，字段恰为 choice_id,rationale,expected_feedback。"
            payload=structured_request({"model":CONFIG["model"],"messages":[{"role":"system","content":system},
                {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":0,"max_tokens":900,
                **CONFIG.get("generation_options",{})},CONFIG,"submit_schedule",SCHEDULE_SCHEMA)
            spent=usage_summary(self.result["model_calls"])
            # Byte count is a deliberately conservative preflight, not the
            # provider's tokenizer. Missing usage prevents further API calls.
            preflight=len(json.dumps(payload,ensure_ascii=False).encode())+900
            phase_calls=sum(r.get("scientific_phase")==phase for r in self.result["model_calls"])
            can_call=len(options)>1 and phase_calls<API_PHASE_LIMITS[phase] and spent["api_calls"]<8 and spent["calls_without_reported_usage"]==0 and spent["total_tokens"]+preflight<=60000
            if can_call:
                api=request_model(CONFIG,payload);api.update(clock=self.lab.clock,scientific_phase=phase,
                    training_evidence_ids=record["available_training_ids"],preflight_byte_plus_output_bound=preflight)
                try:
                    if "response" not in api:raise ValueError("no decoded API response")
                    submission=decode_submission(api["response"],CONFIG,"submit_schedule")
                    if set(submission)!={"choice_id","rationale","expected_feedback"} or any(not isinstance(submission[k],str) or not submission[k].strip() for k in submission):raise ValueError("invalid schedule fields")
                    selected=next(o for o in options if o["choice_id"]==submission["choice_id"])
                    api.update(submission=submission,submission_transport=submission_transport(api["response"]))
                    record.update(policy="llm_schedule_choice",submission=submission)
                except (ValueError,KeyError,TypeError,StopIteration) as error:
                    api["submission_error"]=str(error);record.update(policy="numeric_fallback_after_api_error")
                self.result["model_calls"].append(api)
            else:record.update(policy="deterministic_single_legal_action" if len(options)==1 else "numeric_fallback_after_api_allocation",preflight_byte_plus_output_bound=preflight)
        record["selected_choice_id"]=selected["choice_id"];self.result["schedule_decisions"].append(record)
        self.lab._record("schedule_choice",{k:copy.deepcopy(record[k]) for k in ("phase","policy","selected_choice_id","available_training_ids")})
        save(self.path,self.result,self.lab);return selected

    def dispatch(self,job_planner,count,pool_provider,phase):
        """Dispatch a fixed number of planned cohorts; repair and wait openly."""
        jobs=[];submitted=0
        while self.lab.clock<self.lab.deadline:
            state=self.lab.public_state();active=len(state["pending_jobs"])
            capacity=1 if self.strategy=="numeric_serial" else self.lab.max_pending
            options=[]
            for j in state["failed_jobs"]:
                if len([p for p in state["pending_jobs"] if p["status"]=="pending"])<self.lab.max_pending:
                    options.append({"choice_id":f"retry_{j['job_id']}","tool":"retry_execution","args":{"job_id":j["job_id"]},"expected_feedback":"重试同一冻结计划；失败不增加样本。"})
            for j in state["unverified_jobs"]:
                options.append({"choice_id":f"reconcile_{j['job_id']}","tool":"reconcile_measurement","args":{"job_id":j["job_id"]},"expected_feedback":"延迟获取原始计数，无新增 cohort。"})
            proposed=None;pool=pool_provider()
            if submitted<count and active<capacity:
                proposed=job_planner(submitted,pool)
                options.append({"choice_id":f"launch_{submitted}","tool":"submit_experiment","registered_plan_sha256":digest(proposed),
                    "action":copy.deepcopy(proposed["action"]),"claim_id":proposed["claim_id"],"expected_feedback":"先获得排队或未启动回执，未来才有计数。"})
            if state["pending_jobs"]:options.append({"choice_id":"await_next","tool":"await_next","args":{},"expected_feedback":"收到最早成熟公开事件或到达截止。"})
            if not options:break
            selected=self.choose(options,pool,phase)
            if selected["tool"]=="submit_experiment":
                response=self.lab.call("submit_experiment",{"plan":proposed});jobs.append(response["job_id"]);submitted+=1
            else:self.lab.call(selected["tool"],selected["args"])
            save(self.path,self.result,self.lab)
            state=self.lab.public_state()
            if submitted==count and not any(state[k] for k in ("pending_jobs","failed_jobs","unverified_jobs")):break
        return jobs


def run(seed,family,profile,strategy,phase,deadline=120):
    path=ROOT/"results"/phase/filename(seed,family,profile,strategy)
    if path.exists():raise ValueError("result already exists")
    path.parent.mkdir(parents=True,exist_ok=True)
    lab=TemporalLab(ChoiceWorld(seed,family,"none","structured"),profile=profile,deadline=deadline)
    result={"phase":phase,"version":VERSION,"strategy":strategy,"private_configuration":{"seed":seed,"family":family,"profile":profile,"deadline":deadline},
        "legal_input":lab.public(),"model_config":CONFIG,"model_calls":[],"schedule_decisions":[],"research_versions":[],"confirmations":[],
        "status":"running","confirmation_protocol":{"rounds":3,"max_checks":6,"cohorts_per_check":2,"n_per_cohort":800,"total_alpha":.05,"tolerance":.05},
        "workflow_policy":{"max_revisions":2,"common_warm_cohorts":5,"adaptive_discovery_cohorts":7,"llm_role":"schedule choices only",
            "api_calls":8,"api_reported_token_limit":60000,"api_phase_limits":API_PHASE_LIMITS,"api_only_multiple_choices":True,
            "calendar_excludes_api_wall_seconds":True,"stationary_research_ticks":True}}
    start=time.monotonic();coordinator=Coordinator(lab,result,path)
    try:
        lab.call("audit_history",{});lab.call("reconcile_history",{});transfer=lab.call("open_transfer",{})
        catalog=lab.public_catalog("source");facts=compile_structured(catalog+transfer["catalog"]);patterns=facts["role_patterns"]
        result["physical_facts"]=facts
        role=lambda p:(features(patterns,catalog,[p["id"]],(0,0))["heat"],features(patterns,catalog,[p["id"]],(0,0))["utensils"])
        h=next(p["id"] for p in catalog if role(p)==(1,0));u=next(p["id"] for p in catalog if role(p)==(0,1));combo=next(p["id"] for p in catalog if role(p)==(1,1))
        warm=([],[h],[u],[h,u],[combo]);initial={"role_patterns":patterns,"expression":.3}
        pool=[{"model":initial,"bic":0.,"rank":0}]
        def warm_plan(i,_):
            action={"stage":"source","site":"00","assortment":warm[i],"n":400,"verified_supply":True,"verified_meter":True,
                "prediction":.3,"rationale":"共同的公开核心功能析因起点；不预设因果效果。"}
            return register_plan(lab,initial,action,"common_warm_constant")
        coordinator.dispatch(warm_plan,5,lambda:pool,"common_warm")
        def current_pool():
            return coordinator.fit(patterns) if lab.verified_observations() else pool
        if lab.clock<deadline:
            def discovery_plan(i,current):
                action=plan(lab,current,novelty=True)
                if action is None:raise ValueError("no legal public discovery design")
                return register_plan(lab,current[0]["model"],action,f"discovery_{i}")
            coordinator.dispatch(discovery_plan,7,current_pool,"adaptive_discovery")
        pool=current_pool();training_ids=[r["experiment_id"] for r,_ in lab.verified_observations()]
        lab.set_fit_scope(training_ids)
        for round_index in range(3):
            frozen=copy.deepcopy(pool[0]["model"])
            result["research_versions"].append({"phase":"confirmation_model_frozen","round":round_index,"clock":lab.clock,
                "model":frozen,"training_evidence_ids":training_ids.copy()})
            save(path,result,lab)
            if lab.clock>=deadline:break
            check_actions={}
            def confirmation_plan(i,_):
                index=i//2
                if index not in check_actions:
                    action=plan(lab,pool,novelty=True)
                    if action is None:raise ValueError("no legal fresh confirmation condition")
                    action["n"]=800;action["rationale"]="对冻结关系用两个 n=800 新 cohort 作一项条件检查；最多六项 CP/Bonferroni，5pp 容差，缺失保持未决。"
                    check_actions[index]=action
                return register_plan(lab,frozen,check_actions[index],f"confirmation_round_{round_index}_check_{index}","confirmation")
            jobs=coordinator.dispatch(confirmation_plan,4,lambda:pool,"confirmation")
            by_job={r["job_id"]:r for r in lab.public_state()["mature_evidence"] if r["verified_supply"] and r["verified_meter"]}
            checks=[]
            for index in range(2):
                selected=jobs[2*index:2*index+2]
                if len(selected)!=2 or not all(j in by_job for j in selected):continue
                rows=[copy.deepcopy(by_job[j]) for j in selected];p=rows[0]["frozen_prediction"]
                check=assess(sum(r["observed_sales"] for r in rows),sum(r["n"] for r in rows),p,max_checks=6)
                check.update(round=round_index,experiment_id=rows[0]["experiment_id"],experiment_ids=[r["experiment_id"] for r in rows],
                    cohort_results=rows,design=register_plan(lab,frozen,check_actions[index],"scope","confirmation")["action"],available_at=lab.clock)
                checks.append(check);result["confirmations"].append(check)
                lab._record("confirmation_assessed",{"round":round_index,"experiment_ids":check["experiment_ids"],"state":check["state"]})
            if lab.clock>=deadline:break
            if round_index<2 and any(c["state"]=="contradicted" for c in checks):
                training_ids=[r["experiment_id"] for r in lab.public_state()["mature_evidence"] if r["verified_supply"] and r["verified_meter"]]
                lab.set_fit_scope(training_ids)
                result.setdefault("revision_events",[]).append({"after_round":round_index,"clock":lab.clock,"training_evidence_ids":training_ids.copy(),"trigger":"fresh_condition_contradicted"})
                pool=current_pool()
        result["mechanism_card"]=temporal_card(pool[0]["model"],facts["ontology"],result["research_versions"],result["confirmations"])
        incomplete=len(result["confirmations"])<6
        lab.call("finish",{"model":copy.deepcopy(pool[0]["model"]),"unresolved":incomplete or result["mechanism_card"]["state"]!="supported_in_listed_conditions",
            "claims":"仅列出条件可获得独立支持；截止缺失与执行失败不作为反证，核验失败须修复；未测组合仍未决。部署只作共同离线评价。"})
        result["frozen_final"]=copy.deepcopy(lab.final);result["frozen_expression_sha256"]=digest(lab.final["model"]["expression"])
        deployment=lab.call("deployment_catalog",{})
        bound=compile_structured(catalog+transfer["catalog"]+deployment);result["deployment_physical_facts"]=bound
        deployed={"role_patterns":bound["role_patterns"],"expression":copy.deepcopy(lab.final["model"]["expression"])}
        result["deployed_model"]=deployed;result["private_score"]=evaluate(lab._core._world,lab.final["model"],deployed)
        result["status"]="deadline_unresolved" if incomplete else "finished"
    except Exception as error:result.update(status="execution_failure",error=type(error).__name__+": "+str(error))
    result["elapsed_seconds"]=time.monotonic()-start;save(path,result,lab)
    print(json.dumps({"seed":seed,"family":family,"profile":profile,"strategy":strategy,"status":result["status"],"used":lab.used,
        "checks":len(result["confirmations"]),"rmse":result.get("private_score",{}).get("heldout_effect_rmse"),"api":result["model_usage"],"error":result.get("error")}),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--seeds",required=True);ap.add_argument("--families",required=True)
    ap.add_argument("--profiles",required=True);ap.add_argument("--strategies",required=True);ap.add_argument("--phase",required=True)
    ap.add_argument("--workers",type=int,default=1);ap.add_argument("--deadline",type=int,default=120)
    args=ap.parse_args()
    if not set(args.strategies.split(','))<=STRATEGIES:ap.error("unknown strategy")
    tasks=[(int(s),f,p,m,args.phase,args.deadline) for s in args.seeds.split(',') for f in args.families.split(',') for p in args.profiles.split(',') for m in args.strategies.split(',')]
    if any((ROOT/'results'/args.phase/filename(*t[:4])).exists() for t in tasks):ap.error("result already exists")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for future in concurrent.futures.as_completed([executor.submit(run,*task) for task in tasks]):future.result()
