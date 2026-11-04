"""Evidence-state agent with executable candidates and truth-free counterexamples.

All methods receive the same tool catalog, model and shared research budgets.
Workflow scheduling and compilation checks are the experimental treatments.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import datetime
import hashlib
import json
from pathlib import Path
import time

from lab import ResearchLab, World, private_score, predict
from model_protocol import (ACTION_SCHEMA, append_feedback, decode_submission,
                            request_model, structured_request, submission_transport, usage_summary)
from run_qwen_pilot import SYSTEM, parse_action


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
CONFIG = json.loads((PROJECT / "configs/base_model.json").read_text())
WORKFLOW_VERSION = "research-v0.5-protocol-development"
COMMON = SYSTEM + "\nexpression 可用受限算术字符串。fit_candidate 能估计你提出的结构的数值参数；check_model 可检查程序实际预测与文字是否一致。不能把模型内的拟合当新证据。最终可用 finish args={candidate_id:整数,claims:文字} 引用拟合版本。合理分配样本与成本，至少预留模型拟合与收尾调用。所有工具都向所有比较方法开放。工具反馈若说明未知变量，检查拼写，或在 role_patterns 声明对应商品描述因素。不要原样重复失败调用。若某项能力尚未确认，claims 清楚说明未决，可在 finish.args 添加 unresolved=true 结束当前研究并保留模型。"


def qualifies_review(catalog,model,args,prior):
    """An unqueried transformation predicted invariant by the armed program."""
    if args.get("stage","source")!="source" or not args.get("verified_supply") or not args.get("verified_meter"):
        return False
    arm=set(args.get("assortment",[]))
    anchors=[r for r in prior if r["stage"]=="source"]
    if any(arm==set(r["assortment"]) for r in anchors):return False
    p=predict(model,catalog,list(arm),(0,0))
    return any(abs(p-predict(model,catalog,r["assortment"],(0,0)))<=.02 for r in anchors)


def episode(seed, family, fault, strategy, calls=28, phase="development", out_dir=None):
    out_dir = Path(out_dir) if out_dir else ROOT / "results" / phase
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{strategy}_{family}_{fault}_s{seed}.json"
    lab = ResearchLab(World(seed, family, fault))
    system = COMMON
    if strategy != "generic":
        system += "\n本工作流在 finish 前自动核验模型在已核实实验上的预测残差；优先拟合候选程序，看到模型与成熟数据明显冲突时修订结构或声明未决。模型不自动等于你的文字。"
    if strategy == "frontier":
        system += "\n本工作流在第一版模型后安排一次未覆盖前提审查：在候选预测近似不变的合法条件中，检验尚未探索的变化。系统给出建议但不知道真实效果。若出现冲突，要扩张结构，并针对多个新条件核验，而不是只修改原因名称。"
    messages = [{"role":"system","content":system},
                {"role":"user","content":json.dumps(lab.public(),ensure_ascii=False)}]
    result = {"phase":phase,"workflow_version":WORKFLOW_VERSION,"strategy":strategy,
              "model_config":CONFIG,"generation":{"temperature":0,"max_tokens":4096,"enable_thinking":False,**CONFIG.get("generation_options",{})},
              "private_evaluator_configuration":{"seed":seed,"family":family,"fault":fault},
              "initial_legal_input":copy.deepcopy(messages),"calls":[],"status":"running"}
    frontier_done, frontier_armed, transport_failures, protocol_failures = False, None, 0, 0
    frontier_model=None
    for step in range(calls):
        state = {"workflow_state":"research","used":lab.used.copy(),"remaining_model_calls":calls-step}
        if strategy == "frontier" and lab.candidates and not frontier_done and len(lab._valid_data())>=4:
            suggestion = lab._suggest_probe(len(lab.candidates)-1)
            if "assortment" in suggestion and lab.used["sessions"]+suggestion["n"]<=lab.limits["sessions"] and lab.used["cost"]+5+len(suggestion["assortment"])<=lab.limits["cost"] and lab.used["arms"]<lab.limits["arms"]:
                state.update(workflow_state="counterexample_review",suggested_experiment=suggestion,
                             instruction="优先完成这项预测不变前提检验，或自行选一项改变未覆盖因素的新条件；它不是已知有效动作。")
                frontier_armed = suggestion
                frontier_model=copy.deepcopy(lab.candidates[-1]["model"])
        if strategy != "generic":
            if not lab.candidates and len(lab._valid_data())>=4:
                state["instruction"]="已有至少四项有效 cohort，请先 fit_candidate 编译目前的解释并查看实际程序残差，再决定下一步。"
            messages.append({"role":"user","content":json.dumps({"research_state":state},ensure_ascii=False)})
        payload = {"model":CONFIG["model"],"messages":messages,"temperature":0,"max_tokens":4096,
                   "chat_template_kwargs":{"enable_thinking":False},"response_format":{"type":"json_object"}}
        payload.update(CONFIG.get("generation_options",{}))
        payload=structured_request(payload,CONFIG,"submit_action",ACTION_SCHEMA)
        record = {"step":step,"request":copy.deepcopy(payload),"workflow_state":state}
        start = time.monotonic()
        try:
            api_record=request_model(CONFIG,payload)
            record.update(api_record)
            if "response" not in record:
                raise OSError(record["error"])
            raw=record["response"]
            record["raw_response"]=raw
            try:
                action=parse_action(json.dumps(decode_submission(raw,CONFIG,"submit_action")))
                record["submission_transport"]=submission_transport(raw)
                record["action"]=action
                protocol_failures=0
                if strategy != "generic" and action["tool"]=="finish" and not action["args"].get("unresolved",False):
                    model = lab._candidate(action["args"]["candidate_id"])["model"] if "candidate_id" in action["args"] else action["args"]["model"]
                    diagnostic=lab._check_model(model)
                    if max(abs(r["standardized_residual"]) for r in diagnostic["residuals"])>4:
                        raise ValueError("程序核验发现明显预测冲突："+json.dumps(diagnostic,ensure_ascii=False)+"。请修订结构和重新拟合；若不能确认，claims 应明确未决并可用未决收尾。")
                    if frontier_armed is not None and not frontier_done:
                        raise ValueError("仍有未完成的反例审查，请执行建议或等价的新条件。")
                prior=lab.observed_cohorts()
                feedback=lab.call(action["tool"],action["args"])
                if strategy=="frontier" and frontier_armed is not None and action["tool"]=="experiment":
                    if qualifies_review(lab.public_catalog("source"),frontier_model,action["args"],prior):
                        frontier_done=True
            except (ValueError,KeyError,TypeError,SyntaxError) as error:
                if "action" not in record:
                    record["protocol_error"]=str(error)
                    protocol_failures+=1
                feedback={"error":str(error),"used":lab.used.copy(),"instruction":"此调用没有生成新有效数据；修正动作或结构。错误调用仍计入模型预算。"}
            record["feedback"]=feedback
            append_feedback(messages,raw,feedback)
        except Exception as error:
            category=record.get("error_type")
            if category in {"http","transport"}:
                record["transport_error"]=type(error).__name__+": "+str(error)
                transport_failures+=1
            elif category=="response_envelope" or "response" in record:
                record["protocol_error"]=type(error).__name__+": "+str(error)
                protocol_failures+=1
            else:
                record["execution_error"]=type(error).__name__+": "+str(error)
                result["status"]="execution_failure"
            messages.append({"role":"user","content":"该调用失败，尚无新增工具数据；检查上一次输出和协议。"})
        record["elapsed_seconds"]=round(time.monotonic()-start,3)
        result["calls"].append(record)
        result["model_usage"]=usage_summary(result["calls"])
        result["events"]=lab.events
        result["used"]=lab.used.copy()
        result["candidates"]=lab.candidates
        result["frontier_probe_done"]=frontier_done
        if lab.final is not None:
            result["status"]="finished"
            result["frozen_final"]=lab.final
            result["private_score"]=private_score(lab)
        elif transport_failures>=3:
            result["status"]="transport_failure"
        elif protocol_failures>=3:
            result["status"]="protocol_failure"
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        if result["status"]!="running":
            break
    if result["status"]=="running":
        result["status"]="call_limit_without_frozen_model"
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    compact={"seed":seed,"family":family,"fault":fault,"strategy":strategy,"status":result["status"],
             "calls":len(result["calls"]),"used":lab.used.copy(),"score":result.get("private_score"),"output":str(out)}
    print(json.dumps(compact,ensure_ascii=False),flush=True)
    return compact


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--seeds",default="105")
    ap.add_argument("--families",default="complement,crowding")
    ap.add_argument("--strategies",default="generic,verified_program,frontier")
    ap.add_argument("--faults",default="none")
    ap.add_argument("--workers",type=int,default=2)
    ap.add_argument("--calls",type=int,default=28)
    ap.add_argument("--phase",default="development")
    args=ap.parse_args()
    tasks=[(int(seed),family,fault,strategy) for seed in args.seeds.split(",")
           for family in args.families.split(",") for fault in args.faults.split(",")
           for strategy in args.strategies.split(",")]
    existing=[ROOT/"results"/args.phase/f"{strategy}_{family}_{fault}_s{seed}.json" for seed,family,fault,strategy in tasks]
    if any(p.exists() for p in existing):ap.error("result already exists; use a new declared phase")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(episode,*task,calls=args.calls,phase=args.phase) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            future.result()


if __name__=="__main__":
    main()
