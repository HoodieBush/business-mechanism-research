"""Controlled public-fact discovery, fresh confirmation, and inventory deployment.

Inference receives only public catalogs and mature verified tool data. The private
choice generator and operational scorer are called outside model contexts.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import copy
import hashlib
import json
import math
from pathlib import Path
import time

from choice_world import ChoiceLab,ChoiceWorld
from confirmation import assess
from conditional_memory import ConditionalMemory,export_episode
from lab import predict
from model_order import candidate_key
from mechanism_state import card
from model_protocol import CANDIDATE_SCHEMA,decode_submission,request_model,structured_request,submission_transport,usage_summary
from numeric_design import plan_dopt
from numeric_pool import numeric_pool
from prediction_design import plan_prediction
from operating_eval import evaluate
from run_research import CONFIG
from semantic_compile import CompilationError,compile_structured,compile_text
from symbolic import features,plan,search

ROOT=Path(__file__).resolve().parent
VERSION="openworld-v0.9-conditional-memory-development"
STRATEGIES={"numeric_frontier","numeric_full_frontier","numeric_full_frontier_once","numeric_dopt","numeric_whitened_dopt","numeric_iopt","proposer_frontier","proposer_full_frontier","memory_scoped_frontier","memory_unscoped_frontier"}


def filename(seed,family,fault,strategy,fact_mode):
    return f"{strategy}_{family}_{fault}_{fact_mode}_s{seed}.json"


def save(path,result,lab):
    result.update(events=copy.deepcopy(lab.events),used=lab.used.copy(),
                  model_usage=usage_summary(result["model_calls"]))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")


def compile_stage(catalog,result,ontology=None):
    if result["private_configuration"]["fact_mode"]=="structured":return compile_structured(catalog)
    try:
        proposal,records=compile_text(catalog,CONFIG,ontology)
        result["model_calls"].extend(records);return proposal
    except CompilationError as error:
        result["model_calls"].extend(error.records);raise


def propose(lab,facts,pool,previous=(),confirmations=()):
    system="你提出可执行且能被新操作反驳的购买概率关系。你不知道生成器。只依据已收到的实物事实和已核实实验；商品功能不直接证明购买效应。可以提出任何使用 heat,utensils,external_heat,external_utensils,items 与 role_patterns 已声明因素的 + - * min/max/单参数 sigmoid 结构，最多 8 个参数，每个参数 [初值,下界,上界] 在 [-6,6]。不允许除法、幂、Python、潜在心理变量。表达式是购买概率，不是文字原因。先比较数据或执行问题与结构缺口，再提出竞争解释和可反驳条件。不能改变已经编译的实物角色；必须原样保留 role_patterns。输出 role_patterns、expression、parameters、rationale，随后统一统计工具拟合参数。"
    context={"goal":lab.public()["task"],"operating_objective":lab.public()["operating_objective"],
        "source_catalog":lab.public_catalog("source"),"adaptation_catalog":lab.public_catalog("adaptation"),
        "physical_role_definitions":facts["ontology"],"role_patterns":facts["role_patterns"],
        "expression_variable_mapping":{"heating":"heat","utensils":"utensils",
            **{k:k for k in facts["role_patterns"] if k not in {"heating","utensils"}}},
        "verified_condition_table":[{"experiment_id":r["experiment_id"],"stage":r["stage"],"site":r["site"],
            "assortment":r["assortment"],"n":r["n"],"verified_sales":k,"observed_rate":k/r["n"],
            "frozen_prediction":r["frozen_prediction"],"public_executable_features":features(facts["role_patterns"],lab.public_catalog(r["stage"]),r["assortment"],tuple(map(int,r["site"])))}
            for r,k in lab.verified_observations()],
        "released_confirmation_feedback":list(confirmations),
        "previous_models":pool[:3],
        "previous_submission_feedback":[{k:r[k] for k in ("proposal","proposal_error","fit_result") if k in r} for r in previous]}
    payload={"model":CONFIG["model"],"messages":[{"role":"system","content":system},
        {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":0,"max_tokens":2400,
        **CONFIG.get("generation_options",{})}
    record=request_model(CONFIG,structured_request(payload,CONFIG,"submit_candidate",CANDIDATE_SCHEMA))
    if "response" not in record:return record
    try:
        proposal=decode_submission(record["response"],CONFIG,"submit_candidate")
        record["proposal"]=proposal;record["submission_transport"]=submission_transport(record["response"])
        if proposal["role_patterns"]!=facts["role_patterns"]:raise ValueError("proposal changed frozen physical facts")
        args={k:proposal[k] for k in ("role_patterns","expression","parameters")}
        record["fit_result"]=lab.call("fit_candidate",args);record["fit_args"]=args
    except (ValueError,KeyError,TypeError,SyntaxError) as error:record["proposal_error"]=str(error)
    return record


def fit_pool(lab,patterns,expanded,proposals,memory=None):
    candidates=numeric_pool(lab,patterns,expanded)
    if memory is not None:candidates+=memory.fit_candidates(lab)
    n=sum(r["n"] for r,_ in lab.verified_observations())
    for record in proposals:
        if "fit_args" not in record:continue
        fit=lab.call("fit_candidate",record["fit_args"])
        rank=len(record["fit_args"]["parameters"])
        candidates.append({"model":fit["model"],"terms":[record["fit_args"]["expression"]],
            "bic":fit["binomial_deviance"]+rank*math.log(n),"deviance":fit["binomial_deviance"],"rank":rank,
            "max_residual":max(abs(r["standardized_residual"]) for r in fit["residuals"]),
            "optimizer_success":fit["optimizer_success"],"origin":"llm_proposal"})
    candidates.sort(key=candidate_key)
    return candidates[:48]


def select(lab,pool,strategy,early=False):
    if strategy=="numeric_dopt":return plan_dopt(lab,pool[0]["model"],public_dedup=True,interaction_order=4)
    if strategy in {"numeric_whitened_dopt","numeric_iopt"}:
        return plan_prediction(lab,pool[0]["model"],"d" if strategy=="numeric_whitened_dopt" else "i")
    if early:
        lab.candidates.append({"model":copy.deepcopy(pool[0]["model"])})
        action=lab.call("suggest_probe",{"candidate_id":len(lab.candidates)-1})
        if "assortment" in action:
            action.pop("selection_note",None);return action
    return plan(lab,pool,novelty=True)


def run(seed,family,fault,strategy,fact_mode,phase,confirmation_cohorts=1,confirmation_n=400,confirmation_rounds=2,memory_archive=None,retail_price=8.):
    path=ROOT/"results"/phase/filename(seed,family,fault,strategy,fact_mode)
    if path.exists():raise ValueError("result already exists")
    path.parent.mkdir(parents=True,exist_ok=True)
    if confirmation_cohorts not in (1,2,3) or not 100<=confirmation_n<=800 or confirmation_rounds not in (1,2,3,4):
        raise ValueError("invalid confirmation allocation")
    max_checks=2*confirmation_rounds
    revision_limit=min(1,confirmation_rounds-1) if strategy=="numeric_full_frontier_once" else confirmation_rounds-1
    revisions=0
    lab=ChoiceLab(ChoiceWorld(seed,family,fault,fact_mode,retail_price),max_cost=148+52*(confirmation_cohorts-1)+22*confirmation_cohorts*(confirmation_rounds-2),
        max_arms=12+max_checks*confirmation_cohorts,max_sessions=4800+max_checks*confirmation_cohorts*confirmation_n)
    result={"phase":phase,"version":VERSION,"strategy":strategy,"model_config":CONFIG,
        "private_configuration":{"seed":seed,"family":family,"fault":fault,"fact_mode":fact_mode,"retail_price":retail_price},
        "legal_input":lab.public(),"model_calls":[],"research_versions":[],"confirmations":[],"status":"running",
        "design_decisions":[],
        "workflow_policy":{"max_revisions":revision_limit},
        "confirmation_protocol":{"max_checks":max_checks,"rounds":confirmation_rounds,"cohorts_per_check":confirmation_cohorts,"n_per_cohort":confirmation_n,
            "n_per_check":confirmation_cohorts*confirmation_n,"total_alpha":.05,"tolerance":.05}}
    start=time.monotonic();proposals=[];memory=None
    try:
        facts=compile_stage(lab.public_catalog("source"),result)
        result["source_physical_facts"]=copy.deepcopy(facts)
        lab.call("audit",{});lab.call("reconcile",{})
        catalog=lab.public_catalog("source");patterns=facts["role_patterns"]
        role=lambda p:(features(patterns,catalog,[p["id"]],(0,0))["heat"],features(patterns,catalog,[p["id"]],(0,0))["utensils"])
        h=next(p["id"] for p in catalog if role(p)==(1,0));u=next(p["id"] for p in catalog if role(p)==(0,1))
        combo=next(p["id"] for p in catalog if role(p)==(1,1))
        for arm in ([],[h],[u],[h,u],[combo]):
            lab.call("experiment",{"assortment":arm,"stage":"source","site":"00","n":400,
                "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"共同的公开核心功能析因起点；不预设因果效果。"})
        transfer=lab.call("open_transfer",{})
        facts=compile_stage(catalog+transfer["catalog"],result,facts["ontology"])
        result["adaptation_physical_facts"]=copy.deepcopy(facts);patterns=facts["role_patterns"]
        if strategy.startswith("memory_") and memory_archive is None:raise ValueError("memory policy requires a declared public archive")
        if memory_archive is not None:
            mode="scoped" if strategy=="memory_scoped_frontier" else "unscoped" if strategy=="memory_unscoped_frontier" else "disabled"
            memory=ConditionalMemory(memory_archive,lab.public(),facts,mode)
            result["memory_trace"]=memory.trace()
        expanded=strategy in {"numeric_dopt","numeric_whitened_dopt","numeric_iopt","numeric_full_frontier","numeric_full_frontier_once","proposer_full_frontier","memory_scoped_frontier","memory_unscoped_frontier"}
        for iteration in range(8):
            pool=fit_pool(lab,patterns,expanded,proposals,memory)
            if not expanded and pool[0]["deviance"]>3*len(lab.verified_observations()):
                expanded=True;pool=fit_pool(lab,patterns,True,proposals,memory)
            last,k=lab.verified_observations()[-1];p=last["frozen_prediction"]
            surprise=abs((k-last["n"]*p)/max(.001,math.sqrt(last["n"]*p*(1-p))))
            if strategy in {"proposer_frontier","proposer_full_frontier"} and surprise>4 and len(proposals)<2:
                record=propose(lab,facts,pool,proposals);record["evidence_version"]=len(lab.receipts)
                proposals.append(record);result["model_calls"].append(record)
                pool=fit_pool(lab,patterns,expanded,proposals,memory)
            result["research_versions"].append({"version":iteration,"phase":"discovery",
                "training_evidence_ids":[r["experiment_id"] for r,_ in lab.verified_observations()],
                "expanded":expanded,"candidate_pool":copy.deepcopy(pool)})
            save(path,result,lab)
            if lab.used["arms"]>=12:break
            action=select(lab,pool,strategy,early=iteration==0)
            if action is None:raise ValueError("no feasible discovery design")
            result["design_decisions"].append({"phase":"discovery","evidence_ids":[r["experiment_id"] for r,_ in lab.verified_observations()],
                "action":copy.deepcopy(action)})
            action.pop("design_diagnostics",None)
            if lab.used["cost"]+5+len(action["assortment"])+11*max_checks*confirmation_cohorts>lab.limits["cost"]:
                raise ValueError("cannot reserve declared fresh confirmation operations")
            priors=memory.prior_predictions(lab,action) if memory is not None else []
            if memory is not None:result["design_decisions"][-1]["memory_prior_predictions"]=priors
            save(path,result,lab)
            response=lab.call("experiment",action)
            if memory is not None:
                memory.observe_prior_predictions(priors,response,max_checks=7*len(memory.archive["episodes"]))
                result["memory_trace"]=memory.trace()
        fit_training_ids=[r["experiment_id"] for r,_ in lab.verified_observations()]
        for round_index in range(confirmation_rounds):
            # No fit/proposal call sees confirmation outcomes until explicitly
            # released after round 1 refutes this frozen candidate.
            frozen=copy.deepcopy(pool[0]["model"])
            result["research_versions"].append({"phase":"confirmation_model_frozen","round":round_index,
                "model":frozen,"training_evidence_ids":fit_training_ids.copy()})
            save(path,result,lab)
            checks=[]
            for _ in range(2):
                action=plan(lab,pool,novelty=True)
                if action is None:raise ValueError("no feasible fresh confirmation design")
                action["n"]=confirmation_n
                action["prediction"]=predict(frozen,lab.public_catalog(action["stage"]),action["assortment"],tuple(map(int,action["site"])))
                action["rationale"]=f"新 cohort 确认已冻结概率；最多 {max_checks} 项 Clopper-Pearson/Bonferroni 检查，5pp 容差；功效不足保持未决。"
                result["design_decisions"].append({"phase":"confirmation","round":round_index,
                    "action":copy.deepcopy(action)})
                action.pop("design_diagnostics",None)
                save(path,result,lab)
                responses=[lab.call("experiment",action) for _ in range(confirmation_cohorts)]
                check=assess(sum(r["observed_sales"] for r in responses),sum(r["n"] for r in responses),action["prediction"],max_checks=max_checks)
                check.update(round=round_index,experiment_id=responses[0]["experiment_id"],
                    experiment_ids=[r["experiment_id"] for r in responses],cohort_results=responses,design=action)
                checks.append(check);result["confirmations"].append(check);save(path,result,lab)
            if memory is not None:
                memory.record_target_version(pool[0],fit_training_ids,round_index,checks)
                result["memory_trace"]=memory.trace();save(path,result,lab)
            if round_index<confirmation_rounds-1 and revisions<revision_limit and any(c["state"]=="contradicted" for c in checks):
                revisions+=1
                result["revision_after_confirmation"]=True;expanded=True
                result["released_confirmation_ids"]=[eid for c in result["confirmations"] for eid in c["experiment_ids"]]
                result.setdefault("revision_events",[]).append({"after_round":round_index,
                    "released_confirmation_ids":result["released_confirmation_ids"].copy(),"trigger":"fresh_condition_contradicted"})
                if strategy in {"proposer_frontier","proposer_full_frontier"} and len(proposals)<3:
                    record=propose(lab,facts,pool,proposals,result["confirmations"]);record["evidence_version"]=len(lab.receipts)
                    proposals.append(record);result["model_calls"].append(record)
                pool=fit_pool(lab,patterns,True,proposals,memory)
                fit_training_ids=[r["experiment_id"] for r,_ in lab.verified_observations()]
        result["status"]="mechanism_frozen"
        result["mechanism_card"]=card(pool[0]["model"],facts["ontology"],result["research_versions"],result["confirmations"])
        lab.call("finish",{"model":copy.deepcopy(pool[0]["model"]),
            "unresolved":result["mechanism_card"]["state"]!="supported_in_listed_conditions",
            "claims":"核实数据拟合的操作概率；只有机制卡列出的条件可获得支持，未测范围仍未决；unresolved 仅指当前确认范围。不唯一识别心理或消费者类型；部署仅作离线评价。"})
        result["frozen_final"]=copy.deepcopy(lab.final)
        if memory is not None:
            result["public_memory_export"]=export_episode(result["legal_input"],facts,lab.events,result["research_versions"],result["confirmations"],lab.used)
        result["frozen_expression_sha256"]=hashlib.sha256(json.dumps(lab.final["model"]["expression"],sort_keys=True).encode()).hexdigest()
        save(path,result,lab)
        deployment=lab.call("deployment_catalog",{})
        bound=compile_stage(catalog+transfer["catalog"]+deployment,result,facts["ontology"])
        result["deployment_physical_facts"]=bound
        deployed={"role_patterns":bound["role_patterns"],"expression":copy.deepcopy(lab.final["model"]["expression"])}
        result["deployed_model"]=deployed
        result["private_score"]=evaluate(lab._world,lab.final["model"],deployed)
        result["status"]="finished"
    except Exception as error:
        result.update(status="execution_failure",error=type(error).__name__+": "+str(error))
        if isinstance(error,CompilationError):result["status"]="semantic_compilation_failure"
    result["elapsed_seconds"]=time.monotonic()-start;save(path,result,lab)
    print(json.dumps({"seed":seed,"family":family,"strategy":strategy,"facts":fact_mode,"status":result["status"],
        "effect_rmse":result.get("private_score",{}).get("heldout_effect_rmse"),
        "operating_regret":result.get("private_score",{}).get("mean_expected_operating_regret_per_customer"),
        "model_usage":result["model_usage"],"used":lab.used,"error":result.get("error")}),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--seeds",required=True);ap.add_argument("--families",required=True)
    ap.add_argument("--strategies",required=True);ap.add_argument("--faults",default="none")
    ap.add_argument("--fact-modes",default="structured");ap.add_argument("--phase",required=True)
    ap.add_argument("--workers",type=int,default=1)
    ap.add_argument("--confirmation-cohorts",type=int,default=1);ap.add_argument("--confirmation-n",type=int,default=400)
    ap.add_argument("--confirmation-rounds",type=int,default=2)
    ap.add_argument("--memory-archive",type=Path);ap.add_argument("--retail-price",type=float,default=8.)
    args=ap.parse_args()
    if not set(args.strategies.split(','))<=STRATEGIES:ap.error("unknown strategy")
    memory_archive=json.loads(args.memory_archive.read_text()) if args.memory_archive else None
    tasks=[(int(s),f,x,m,t,args.phase) for s in args.seeds.split(',') for f in args.families.split(',')
        for x in args.faults.split(',') for m in args.strategies.split(',') for t in args.fact_modes.split(',')]
    if any((ROOT/'results'/args.phase/filename(*task[:5])).exists() for task in tasks):ap.error("result already exists")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(run,*task,args.confirmation_cohorts,args.confirmation_n,args.confirmation_rounds,memory_archive,args.retail_price) for task in tasks]
        for future in concurrent.futures.as_completed(futures):future.result()
