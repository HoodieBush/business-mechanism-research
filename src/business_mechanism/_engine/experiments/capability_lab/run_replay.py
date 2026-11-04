"""Numerical inference on exactly the received cohorts; never sample new data.

Replay is paired with its parent task, not an additional independent experiment.
Private evaluation is called only after the public-evidence model is frozen.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from lab import ResearchLab,World,private_score
from replay_evidence import ReplayEvidence
from symbolic import search


def replay(source_path,output_dir):
    start=time.monotonic();source_path=Path(source_path)
    parent=json.loads(source_path.read_text())
    out=Path(output_dir)/source_path.name
    if out.exists():raise ValueError("replay already exists")
    record={"phase":"development_shared_data_replay","parent_file":str(source_path),
        "parent_sha256":hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "parent_strategy":parent["strategy"],"strategy":"static_expanded_grammar_replay",
        "private_configuration":parent["private_configuration"],
        "new_sessions":0,"model_api_calls":0,"independent_unit":"parent task",
        "parent_status":parent["status"],"parent_private_score":parent.get("private_score"),
        "status":"running"}
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        # Pass only legally received facts and tool outputs to inference.
        view=ReplayEvidence(parent["legal_input"],parent.get("events",[]))
        patterns=parent["patterns"]
        pool=search(view,patterns,expanded=True,max_terms=3)
        record.update(status="model_frozen",candidate_pool=pool,
            evidence_ids=[r["experiment_id"] for r,_ in view.verified_observations()],
            frozen_final={"model":copy.deepcopy(pool[0]["model"]),
                "claims":"共享已收到的 cohort 和相同角色映射；静态完整语法数值拟合，未采集新证据。"})
        out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
        # The inference view has no World, truth, scorer, or experiment method.
        evaluator=ResearchLab(World(**parent["private_configuration"]),max_cost=112)
        evaluator.receipts=[{"result":copy.deepcopy(r)} for r in view.cohorts]
        evaluator.used=copy.deepcopy(parent.get("used",parent.get("events",[{}])[-1].get("used",{"sessions":0,"arms":0,"cost":0})))
        evaluator.call("finish",record["frozen_final"])
        record.update(status="finished",private_score=private_score(evaluator),
            reused_experiment_budget=evaluator.used)
    except (ValueError,KeyError,TypeError) as error:
        record.update(status="replay_failure",error=type(error).__name__+": "+str(error))
    record["elapsed_seconds"]=time.monotonic()-start
    out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    return record


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("source",type=Path);ap.add_argument("output",type=Path)
    args=ap.parse_args()
    files=sorted(args.source.glob("*.json")) if args.source.is_dir() else [args.source]
    results=[]
    for p in files:
        if p.name=="manifest.json":continue
        r=replay(p,args.output);results.append(r)
    print(json.dumps({"total":len(results),"finished":sum(r["status"]=="finished" for r in results),
        "new_sessions":0,"model_api_calls":0}),flush=True)
