"""Prospective deterministic fixture for terminal execution, not an LLM study."""
import argparse
import copy
import json
from pathlib import Path

from choice_world import ChoiceWorld
from model_protocol import usage_summary
from operating_eval import evaluate
from research_runtime import ResearchRuntime
from semantic_compile import compile_structured
from temporal_lab import TemporalLab,digest

ROOT=Path(__file__).resolve().parent
VERSION="terminal-fixture-v0.1-prospective-policy-comparison"


def filename(t):return f"{t['terminal_policy']}_{t['family']}_{t['profile']}_d{t['deadline']}_s{t['seed']}.json"


def run(task,phase,price):
    path=ROOT/"results"/phase/filename(task)
    if path.exists():raise ValueError("result exists")
    lab=TemporalLab(ChoiceWorld(task["seed"],task["family"],"none","structured",price),task["profile"],task["deadline"])
    lab.limits.update(api_calls=16,api_tokens=80000)
    rt=ResearchRuntime(lab,terminal_policy=task["terminal_policy"])
    result={"phase":phase,"version":VERSION,"strategy":"deterministic_terminal_fixture","terminal_policy":task["terminal_policy"],
        "private_configuration":{k:task[k] for k in ("seed","family","profile","deadline")}|{"price":price},"legal_input":copy.deepcopy(rt.initial),"model_calls":[],
        "scientific_protocol":{"max_checks":6,"n_per_cohort":800,"cohorts_per_check":2,"total_alpha":.05,"tolerance":.05},"status":"running"}
    def call(tool,args={}):
        response=rt.call(tool,args,"固定公开输入执行夹具。","检验已承诺回执终止策略。")
        if not response["ok"]:raise ValueError(response["error"])
        return response["result"]
    try:
        call("diagnose_history");call("open_adaptation")
        products=lab.public_catalog("source")
        h=next(p["id"] for p in products if p["functions"]["heating"] and not p["functions"]["utensils"])
        u=next(p["id"] for p in products if p["functions"]["utensils"] and not p["functions"]["heating"])
        call("sample",{"candidate_id":rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":a,"n":400} for a in ([],[h],[u])],"rationale":"公开三臂起点，仅用于计划/回执夹具。"})
        call("collect",{"until":"all","repair":True,"refit":True,"assess":False})
        cid=rt.pool[0]
        call("confirm",{"candidate_id":cid,"rationale":"固定一次新条件检查后结束研究决策。"})
        result["decision_prefix_research_events"]=copy.deepcopy(rt.events);result["decision_prefix_gateway_events"]=copy.deepcopy(lab.events)
        result["decision_prefix_used"]=copy.deepcopy(lab.used);result["selected_candidate_id"]=cid
        call("finish",{"candidate_id":cid,"claims":"固定夹具仅检验原登记条件；未测范围和机制唯一性未决。","unresolved":True,"stop_reason":"预声明在一项确认排队后停止决策。"})
        result["frozen_final"]=copy.deepcopy(rt.final["frozen_final"]);result["mechanism_card"]=copy.deepcopy(rt.final["mechanism_card"])
        result["frozen_expression_sha256"]=digest(lab.final["model"]["expression"])
        deployment=lab.call("deployment_catalog",{});facts=compile_structured(lab.public_catalog("source")+lab.public_catalog("adaptation")+deployment)
        result["deployment_physical_facts"]=facts;result["deployed_model"]={"role_patterns":facts["role_patterns"],"expression":copy.deepcopy(lab.final["model"]["expression"])}
        result["private_score"]=evaluate(lab._core._world,lab.final["model"],result["deployed_model"])
        result["status"]="finished_scoped"
    except Exception as error:result.update(status="execution_failure",error=type(error).__name__+": "+str(error))
    result.update(research=rt.snapshot(),gateway_events=copy.deepcopy(lab.events),used=copy.deepcopy(lab.used),public_final_state=lab.public_state(),model_usage=usage_summary([]))
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"file":path.name,"status":result["status"],"clock":lab.clock,"completed_checks":sum(c["result"] is not None for c in rt.checks),"state":result.get("mechanism_card",{}).get("state"),"error":result.get("error")}),flush=True)
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--spec",type=Path,required=True);args=ap.parse_args();spec=json.loads(args.spec.read_text())
    for seed in spec["seeds"]:
        for family in spec["families"]:
            for profile in spec["profiles"]:
                for deadline in spec["deadlines"]:
                    for policy in spec["terminal_policies"]:run({"seed":seed,"family":family,"profile":profile,"deadline":deadline,"terminal_policy":policy},spec["phase"],spec["price"])
