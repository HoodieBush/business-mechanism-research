"""Research agent: LLM grounds roles; numeric components execute research loops.

Failure-driven structural grammar expansion and hypothesis-conditional design are
explicit algorithm modules. The evaluator is only invoked after frozen output.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import json
import hashlib
import math
from pathlib import Path
import random
import time
import threading

from lab import ResearchLab, World, model_with, private_score, predict
from model_protocol import (CANDIDATE_SCHEMA, GROUNDING_SCHEMA, decode_submission,
                            request_model, structured_request, submission_transport, usage_summary)
from run_research import CONFIG
from symbolic import features, plan, search
from model_order import candidate_key
from numeric_design import plan_dopt


ROOT=Path(__file__).resolve().parent
VERSION="hybrid-v0.12-numeric-design-development"
GROUNDING_LOCK=threading.Lock()


class GroundingError(ValueError):
    def __init__(self, message, record):
        super().__init__(message)
        self.record=record


def save_result(out, result):
    records=[result[k] for k in ("grounding_call","transfer_grounding_call") if k in result]
    records+=result.get("mechanism_proposals",[])
    result["model_usage"]=usage_summary(records)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")


def validate_grounding(proposal,public):
    patterns=proposal["role_patterns"]
    if set(patterns)!={"heating","utensils"} or any(not isinstance(v,list) or not v or any(not isinstance(s,str) or not s for s in v) for v in patterns.values()):
        raise ValueError("invalid grounding proposal")
    descriptions=[p["description"] for p in public["catalog"]]
    if any(not any(s in t for t in descriptions) for values in patterns.values() for s in values):
        raise ValueError("grounding pattern lacks public textual evidence")
    facts=proposal["catalog_roles"]
    if not isinstance(facts,dict) or set(facts)!={p["id"] for p in public["catalog"]}:
        raise ValueError("catalog_roles must cover each public product exactly")
    for product in public["catalog"]:
        declared=facts[product["id"]]
        if not isinstance(declared,list) or len(set(declared))!=len(declared) or not set(declared)<={"heating","utensils"}:
            raise ValueError("invalid catalog role facts")
        matched={role for role,values in patterns.items() if any(s in product["description"] for s in values)}
        if matched!=set(declared):
            raise ValueError("fact/rule inconsistency for product "+product["id"]+": declared="+str(declared)+", matched="+str(sorted(matched)))
    return patterns


def ground_roles(public):
    attempts=[]
    correction=None
    for _ in range(2):
        try:
            patterns,record=ground_roles_once(public,correction)
            record["previous_attempts"]=attempts
            return patterns,record
        except GroundingError as error:
            record=error.record
            if record.get("error_type"):
                record["previous_attempts"]=attempts
                raise
            attempts.append(record)
            correction={"previous_submission":record.get("proposal"),
                        "public_contract_error":str(error),
                        "instruction":"只依据目录修正事实与规则，优先使用最短、明确表示功能且可覆盖各商品的子串；不能借机推断购买效果。"}
    record["previous_attempts"]=attempts[:-1]
    raise GroundingError(record["proposal_error"],record)


def ground_roles_once(public,correction=None):
    system="你是商品事实研究员。根据任务目标与目录描述，将商品事实对应到可测功能。只输出 JSON: {\"role_patterns\":{\"heating\":[\"商品描述子串\"],\"utensils\":[\"商品描述子串\"]},\"premises\":\"功能事实不等于因果效果；说明当前可核查前提\"}。不要猜购买率、实验答案或文件内容。每个列表的子串应在目录描述中出现。使用功能词而非完整商品描述，确保单一功能、组合商品和不同品牌均可匹配；避免包装或品牌词替代功能。若输入含旧商品和新商品，输出覆盖两组事实的统一映射。"
    payload={"model":CONFIG["model"],"messages":[{"role":"system","content":system},
             {"role":"user","content":json.dumps(public,ensure_ascii=False)}],"temperature":0,
             "max_tokens":1200,"chat_template_kwargs":{"enable_thinking":False},"response_format":{"type":"json_object"}}
    payload.update(CONFIG.get("generation_options",{}))
    payload["messages"][0]["content"] += "\n另须输出 catalog_roles：字典键覆盖目录中每个商品 id，值为该描述直接提供的功能列表（heating、utensils 或空列表）。先逐商品读取功能，再将其编译为 role_patterns；两者对每个商品必须完全一致。组合商品应分别记录其功能；包装、品牌和泛称不能替代功能证据。premises 用简短文字说明可核查前提。"
    if correction is not None:
        payload["messages"].append({"role":"user","content":json.dumps(correction,ensure_ascii=False)})
    payload=structured_request(payload,CONFIG,"submit_grounding",GROUNDING_SCHEMA)
    cache=ROOT/"results"/"grounding_cache"
    cache.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(json.dumps({"base_url":CONFIG["base_url"],"request":payload},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    cache_file=cache/(digest+".json")
    with GROUNDING_LOCK:
        if cache_file.exists():
            record=json.loads(cache_file.read_text())
            record["cache_hit"]=True
        else:
            record=request_model(CONFIG,payload)
            # Do not make a temporary transport failure a permanent cache entry.
            if "response" in record:
                cache_file.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    if "response" not in record:
        raise GroundingError(record["error"],record)
    try:
        proposal=decode_submission(record["response"],CONFIG,"submit_grounding")
        record["submission_transport"]=submission_transport(record["response"])
        record["proposal"]=proposal
        patterns=validate_grounding(proposal,public)
    except (ValueError,KeyError,TypeError) as error:
        record["proposal_error"]="response_format_or_grounding: "+str(error)
        raise GroundingError(record["proposal_error"],record) from error
    return patterns,record


def canonical_ids(catalog,patterns):
    ids={}
    for p in catalog:
        f=features(patterns,catalog,[p["id"]],(0,0))
        key=(f["heat"],f["utensils"])
        if key in {(1,0),(0,1)} and key not in ids:ids[key]=p["id"]
    if len(ids)!=2:raise ValueError("role mapping does not supply separately testable functions")
    return ids[1,0],ids[0,1]


def propose_mechanism(lab,patterns,previous_pool):
    """Separate proposer context. Input contains only received, verified data."""
    system="你是机制结构提案 Agent。结合商品事实、已核实实验与之前模型，提出一个可执行、可被新实验推翻的购买概率结构。你不知道真实生成器。只能使用公开因素 heat,utensils,external_heat,external_utensils,items，以及在 role_patterns 中声明的商品描述子串因素。允许 + - * min/max，不允许除法、幂、条件语法、潜在心理变量或 Python 代码。先检查观测与执行问题，再考虑结构；不可预设所有商品或外部功能都等效。输出 JSON: {\"role_patterns\":{\"heating\":[\"子串\"],\"utensils\":[\"子串\"]},\"expression\":\"b+g*heat\",\"parameters\":{\"b\":[0.3,0.05,0.9],\"g\":[0.1,-0.5,0.5]},\"rationale\":\"证据、竞争解释和可反驳条件\"}。例子仅示范格式，不是答案。参数后续由统计工具拟合，声明 1..8 个参数，名字不可与因素冲突。请避免重复明显与数据不符的结构。"
    context={"source_catalog":lab.public_catalog("source"),"adaptation_catalog":lab.public_catalog("adaptation"),
             "previous_role_mapping":patterns,"verified_experiments":[r|{"verified_sales":k} for r,k in lab.verified_observations()],
             "previous_candidate_models":previous_pool[:3]}
    payload={"model":CONFIG["model"],"messages":[{"role":"system","content":system},
             {"role":"user","content":json.dumps(context,ensure_ascii=False)}],"temperature":0,
             "max_tokens":2400,"chat_template_kwargs":{"enable_thinking":False},"response_format":{"type":"json_object"}}
    payload.update(CONFIG.get("generation_options",{}))
    payload=structured_request(payload,CONFIG,"submit_candidate",CANDIDATE_SCHEMA)
    record=request_model(CONFIG,payload)
    if "response" not in record:return record
    try:
        proposal=decode_submission(record["response"],CONFIG,"submit_candidate")
        record["submission_transport"]=submission_transport(record["response"])
    except (ValueError,KeyError,TypeError) as error:
        record["proposal_error"]="response_format: "+str(error)
        return record
    record["proposal"]=proposal
    try:
        args={k:proposal[k] for k in ["role_patterns","expression","parameters"]}
        # Structural proposals may add factors, but cannot silently redefine the
        # operational meanings of the already grounded heating/utensils facts.
        catalog=context["source_catalog"]+context["adaptation_catalog"]
        for product in catalog:
            for role in ("heating","utensils"):
                before=any(s in product["description"] for s in patterns[role])
                after=any(s in product["description"] for s in args["role_patterns"][role])
                if before!=after:raise ValueError("proposal changes grounded core role for "+product["id"])
        if any(not any(s in p["description"] for p in catalog) for values in args["role_patterns"].values() for s in values):
            raise ValueError("proposed factor lacks public textual evidence")
        record["fit_result"]=lab.call("fit_candidate",args)
        record["fit_args"]=args
    except (ValueError,KeyError,TypeError,SyntaxError) as error:
        record["proposal_error"]=str(error)
    return record


def fitted_proposal(lab,record):
    if "fit_args" not in record:return None
    fit=lab.call("fit_candidate",record["fit_args"])
    k=len(record["fit_args"]["parameters"])
    n=sum(r["n"] for r,_ in lab.verified_observations())
    return {"model":fit["model"],"terms":[record["fit_args"]["expression"]],
            # Deviance omits the same saturated-likelihood constant for all models.
            "relative_bic":fit["binomial_deviance"]+k*math.log(n),
            "deviance":fit["binomial_deviance"],"rank":k,
            "max_residual":max(abs(r["standardized_residual"]) for r in fit["residuals"]),
            "origin":"llm_proposed_structure","optimizer_success":fit["optimizer_success"]}


def run(seed,family,fault,strategy="hybrid_frontier",phase="development_hybrid",llm=True,random_parameters=False):
    out=ROOT/"results"/phase/f"{strategy}_{family}_{fault}_s{seed}.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    lab=ResearchLab(World(seed,family,fault,random_parameters),max_cost=112)
    result={"phase":phase,"version":VERSION,"strategy":strategy,"model_config":CONFIG,
            "private_configuration":{"seed":seed,"family":family,"fault":fault,"random_parameters":random_parameters},
            "legal_input":lab.public(),"research_versions":[],"status":"running"}
    start=time.monotonic()
    if llm:
        try:
            patterns,record=ground_roles(lab.public())
            result["grounding_call"]=record
        except Exception as error:
            if isinstance(error,GroundingError):result["grounding_call"]=error.record
            result["status"]="grounding_failure";result["error"]=str(error)
            save_result(out,result)
            print(json.dumps({"seed":seed,"family":family,"strategy":strategy,"status":result["status"]}),flush=True)
            return result
    else:
        patterns=model_with(0)["role_patterns"]
        result["grounding"]="fixed_public_keyword_comparator"
    result["patterns"]=patterns
    save_result(out,result)
    lab.call("audit",{});lab.call("reconcile",{})
    h,u=canonical_ids(lab.public()["catalog"],patterns)
    # A declared, shared diagnostic warm start. It establishes an estimable
    # response surface; it contains no response labels or true parameters.
    combo=next((p["id"] for p in lab.public()["catalog"] if features(patterns,lab.public()["catalog"],[p["id"]],(0,0))["heat"] and features(patterns,lab.public()["catalog"],[p["id"]],(0,0))["utensils"]),None)
    warm=[[],[h],[u],[h,u]]+([[combo]] if combo else [])
    for arm in warm:
        lab.call("experiment",{"assortment":arm,"stage":"source","site":"00","n":400,
                 "verified_supply":True,"verified_meter":True,"prediction":.3,
                 "rationale":"公开角色映射的固定析因诊断；不预设关系有效。"})
    rng=random.Random(seed+515)
    adaptation=lab.call("open_transfer",{})
    if llm:
        try:
            patterns,record=ground_roles({"task":"将旧事实映射复核后扩展到新品牌，不能由功能相同推出效果相同。",
                                         "catalog":lab.public()["catalog"]+adaptation["catalog"],
                                         "previous_role_patterns":patterns})
            result["transfer_grounding_call"]=record
            result["patterns"]=patterns
        except Exception as error:
            if isinstance(error,GroundingError):result["transfer_grounding_call"]=error.record
            result.update(status="transfer_grounding_failure",error=str(error),events=lab.events)
            save_result(out,result)
            return result
    ah,au=canonical_ids(adaptation["catalog"],patterns)
    fixed_queue=[(site,([ah] if a else [])+([au] if b else [])) for site in ["10","01","11"] for a,b in [(0,0),(1,0),(0,1),(1,1)]]
    expanded=strategy=="symbolic_dopt"
    result["mechanism_proposals"]=[]
    previous_pool=[]
    for iteration in range(13):
        pool=search(lab,patterns,expanded=expanded,max_terms=3)
        expansion_event=None
        if not expanded and strategy!="no_expansion" and pool[0]["deviance"]>3*len(lab.verified_observations()):
            expansion_event={"from":"additive","trigger":"binomial_lack_of_fit_development_threshold",
                             "deviance":pool[0]["deviance"],"cohorts":len(lab.verified_observations())}
            expanded=True
            pool=search(lab,patterns,expanded=True,max_terms=3)
        data=lab.verified_observations()
        last_observation=data[-1][0]
        frozen_p=last_observation["frozen_prediction"]
        surprise=abs((data[-1][1]-last_observation["n"]*frozen_p)/max(.001,(last_observation["n"]*frozen_p*(1-frozen_p))**.5))
        if llm and (iteration==0 or (surprise>4 and len(result["mechanism_proposals"])<3)):
            try:
                proposal=propose_mechanism(lab,patterns,previous_pool)
                proposal["evidence_version"]=len(data)
                result["mechanism_proposals"].append(proposal)
            except Exception as error:
                result["mechanism_proposals"].append({"transport_error":str(error),"evidence_version":len(data)})
        # Rank proposed programs with the numerical grammar in the same evidence.
        # Model selection never consults the private evaluator.
        n=sum(r["n"] for r,_ in data)
        for candidate in pool:candidate["relative_bic"]=candidate["deviance"]+candidate["rank"]*math.log(n)
        for proposal in result["mechanism_proposals"]:
            try:
                candidate=fitted_proposal(lab,proposal)
                if candidate is not None:pool.append(candidate)
            except (ValueError,KeyError,TypeError,SyntaxError):pass
        pool.sort(key=lambda r:candidate_key(r,"relative_bic"))
        pool=pool[:8]
        for candidate in pool:candidate["bic"]=candidate["relative_bic"]
        previous_pool=copy.deepcopy(pool)
        selected=copy.deepcopy(pool[0])
        version={"version":iteration,"evidence_ids":[r["result"]["experiment_id"] for r in lab.receipts],
                 "candidate_pool":pool,"selected_model":selected,
                 "state":"unresolved" if selected["max_residual"]>4 else "predictively_supported_in_measured_scope"}
        version["expansion_event"]=expansion_event
        result["research_versions"].append(version)
        if lab.used["arms"]>=16 or lab.used["sessions"]+400>lab.limits["sessions"]:break
        if iteration==0 and strategy in {"hybrid_frontier","no_expansion"}:
            # Reserve a real operation early. It challenges a program-derived
            # invariant, rather than choosing a known hidden-world diagnostic.
            lab.candidates.append({"model":selected["model"]})
            proposed=lab.call("suggest_probe",{"candidate_id":len(lab.candidates)-1})
            if "assortment" not in proposed:
                proposed=plan(lab,pool,novelty=True)
            else:
                proposed.pop("selection_note",None)
                version["frontier_probe"]=True
        elif strategy=="symbolic_fixed":
            if not fixed_queue:break
            site,arm=fixed_queue.pop(0)
            proposed={"assortment":arm,"stage":"adaptation","site":site,"n":400,
                      "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"固定全上下文析因"}
        elif strategy=="symbolic_random":
            all_ids=[p["id"] for p in adaptation["catalog"]]
            arm=[pid for pid in all_ids if rng.random()<.5]
            proposed={"assortment":arm,"stage":"adaptation","site":rng.choice(["00","10","01","11"]),
                      "n":400,"verified_supply":True,"verified_meter":True,"prediction":.3,
                      "rationale":"公开空间随机覆盖强数值对照"}
        elif strategy=="symbolic_coverage":
            proposed=plan(lab,pool,novelty=True,disagreement_weight=0)
            if proposed is None:break
        elif strategy=="symbolic_dopt":
            proposed=plan_dopt(lab,selected["model"])
            if proposed is None:break
        else:
            proposed=plan(lab,pool,novelty=strategy!="hybrid_disagreement")
            if proposed is None:break
        diagnostics=proposed.pop("design_diagnostics",None)
        version["next_design_diagnostics"]=diagnostics
        if strategy in {"symbolic_fixed","symbolic_random"}:
            proposed["prediction"]=predict(selected["model"],lab.public_catalog(proposed["stage"]),proposed["assortment"],tuple(map(int,proposed["site"])))
        if lab.used["cost"]+5+len(proposed["assortment"])>lab.limits["cost"]:break
        lab.call("experiment",proposed)
        result["events"]=lab.events
        save_result(out,result)
    model=result["research_versions"][-1]["selected_model"]["model"]
    uncertain=result["research_versions"][-1]["selected_model"]["max_residual"]>4
    lab.call("finish",{"model":model,"claims":"从商品事实对应功能，按已核实数据生成并扩张算术候选；候选排序为 BIC，非校准后验。操作关系只在测得条件受支持，心理中介未识别；未测条件是冻结外推。",
                       "unresolved":uncertain})
    result.update(status="finished",events=lab.events,used=lab.used.copy(),frozen_final=lab.final,
                  private_score=private_score(lab),elapsed_seconds=time.monotonic()-start)
    save_result(out,result)
    print(json.dumps({"seed":seed,"family":family,"fault":fault,"strategy":strategy,
                      "status":result["status"],"rmse":result["private_score"]["heldout_probability_rmse"],
                      "effect_rmse":result["private_score"]["heldout_effect_rmse"],"used":lab.used,
                      "seconds":round(result["elapsed_seconds"],2)},ensure_ascii=False),flush=True)
    return result


def safe_run(task,phase,llm,random_parameters):
    try:
        return run(*task,phase=phase,llm=llm,random_parameters=random_parameters)
    except Exception as error:
        seed,family,fault,strategy=task
        out=ROOT/"results"/phase/f"{strategy}_{family}_{fault}_s{seed}.json"
        out.parent.mkdir(parents=True,exist_ok=True)
        result=json.loads(out.read_text()) if out.exists() else {"private_configuration":{"seed":seed,"family":family,"fault":fault},"strategy":strategy}
        result.update(status="execution_failure",error=type(error).__name__+": "+str(error))
        save_result(out,result)
        print(json.dumps({"seed":seed,"family":family,"strategy":strategy,"status":"execution_failure","error":str(error)}),flush=True)
        return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--seeds",default="107")
    ap.add_argument("--families",default="complement,crowding,null")
    ap.add_argument("--strategies",default="hybrid_frontier,hybrid_disagreement,symbolic_fixed,symbolic_random,no_expansion")
    ap.add_argument("--faults",default="none")
    ap.add_argument("--phase",default="development_hybrid")
    ap.add_argument("--workers",type=int,default=3)
    ap.add_argument("--no-llm",action="store_true")
    ap.add_argument("--random-parameters",action="store_true")
    args=ap.parse_args()
    tasks=[(int(seed),family,fault,strategy) for seed in args.seeds.split(",") for family in args.families.split(",") for fault in args.faults.split(",") for strategy in args.strategies.split(",")]
    existing=[ROOT/"results"/args.phase/f"{strategy}_{family}_{fault}_s{seed}.json" for seed,family,fault,strategy in tasks]
    if any(p.exists() for p in existing):ap.error("result already exists; use a new declared phase")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(safe_run,task,args.phase,not args.no_llm,args.random_parameters) for task in tasks]
        for future in concurrent.futures.as_completed(futures):future.result()


if __name__=="__main__":main()
