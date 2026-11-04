"""Freeze numerical refits on parent training evidence, then privately evaluate.

Final parent confirmation cohorts remain excluded. Replay adds neither sessions
nor independent tasks; the wider search is a developer diagnostic.
"""
import argparse
import concurrent.futures
import copy
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

from choice_world import ChoiceWorld
from model_order import candidate_key
from numeric_pool import numeric_pool
from operating_eval import evaluate
from replay_evidence import ReplayEvidence

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]


def training_view(parent):
    version=[v for v in parent["research_versions"] if v["phase"]=="confirmation_model_frozen"][-1]
    ids=set(version["training_evidence_ids"])
    events=[e for e in parent["events"] if e["request"]["tool"]!="experiment" or e["response"]["experiment_id"] in ids]
    view=ReplayEvidence(parent["legal_input"],events)
    if {r["experiment_id"] for r,_ in view.verified_observations()}!=ids:
        raise ValueError("parent training IDs do not match verified replay data")
    return view


def replay(parent_path,beam,max_terms,output):
    start=time.monotonic();parent=json.loads(parent_path.read_text())
    name=f"{parent_path.stem}__beam{beam}_terms{max_terms}.json";path=output/name
    row={"status":"running","parent_file":str(parent_path.relative_to(PROJECT)),
        "parent_sha256":hashlib.sha256(parent_path.read_bytes()).hexdigest(),"parent_strategy":parent["strategy"],
        "private_configuration":parent["private_configuration"],"beam":beam,"max_terms":max_terms,
        "new_sessions":0,"model_api_calls":0,"independent_unit":"parent world; paired diagnostic"}
    try:
        view=training_view(parent)
        patterns=parent["adaptation_physical_facts"]["role_patterns"]
        pool=numeric_pool(view,patterns,True,beam,max_terms)
        row.update(status="model_frozen",candidate_pool=pool,
            evidence_ids=[r["experiment_id"] for r,_ in view.verified_observations()],
            frozen_model=copy.deepcopy(pool[0]["model"]))
        # Write a reviewable frozen candidate before invoking any private world.
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+"\n")
        deployed=copy.deepcopy(row["frozen_model"])
        deployed["role_patterns"]=parent["deployment_physical_facts"]["role_patterns"]
        score=evaluate(ChoiceWorld(**parent["private_configuration"]),row["frozen_model"],deployed)
        row.update(status="finished",private_score=score,parent_private_score=parent["private_score"])
    except Exception as error:row.update(status="replay_failure",error=type(error).__name__+": "+str(error))
    row["elapsed_seconds"]=time.monotonic()-start
    path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"parent":parent_path.name,"beam":beam,"max_terms":max_terms,"status":row["status"],
        "deviance":row.get("candidate_pool",[{}])[0].get("deviance"),
        "effect_rmse":row.get("private_score",{}).get("heldout_effect_rmse"),"error":row.get("error")}),flush=True)
    return row


def launch(spec_path):
    spec=json.loads(spec_path.read_text());phase=spec["phase"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+",phase):raise ValueError("invalid phase")
    output=ROOT/"results"/phase;snapshot=ROOT/"snapshots"/phase
    if output.exists() or snapshot.exists():raise ValueError("phase already exists")
    parents=[]
    for source in spec["sources"]:
        p=PROJECT/source
        for f in sorted(p.glob("*.json")):
            if f.name in {"manifest.json","analysis.json"}:continue
            r=json.loads(f.read_text())
            if r.get("status")=="finished" and r["private_configuration"]["family"] in spec["families"]:parents.append(f)
    tasks=[(p,setting["beam"],setting["max_terms"]) for p in parents for setting in spec["settings"]]
    if not tasks:raise ValueError("no declared replay tasks")
    hashes={}
    for p in list(ROOT.glob("*.py"))+[PROJECT/"configs/base_model.json",PROJECT/"environment.yml",PROJECT/"configs/conda-osx-arm64.lock.txt"]:
        rel=p.relative_to(PROJECT);q=snapshot/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
        hashes[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    manifest={"creation_timing":"before_launch","created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "specification":spec,"expected_runs":len(tasks),"snapshot":str(snapshot.relative_to(PROJECT)),
        "source_sha256":hashes,"parent_sha256":{str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in parents},
        "planned_tasks":[{"parent":str(p.relative_to(PROJECT)),"beam":b,"max_terms":t} for p,b,t in tasks],"status":"prepared"}
    for directory in (output,snapshot):(directory/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    with concurrent.futures.ThreadPoolExecutor(max_workers=spec.get("workers",1)) as executor:
        futures=[executor.submit(replay,p,b,t,output) for p,b,t in tasks]
        rows=[f.result() for f in futures]
    summary={"phase":"development_replay_not_independent_tasks","total":len(tasks),
        "finished":sum(r["status"]=="finished" for r in rows),"new_sessions":0,"model_api_calls":0,
        "rows":[{k:r.get(k) for k in ("parent_file","parent_strategy","private_configuration","beam","max_terms","status","elapsed_seconds")}|
            {"deviance":r.get("candidate_pool",[{}])[0].get("deviance"),
             "effect_rmse":r.get("private_score",{}).get("heldout_effect_rmse"),
             "operating_regret":r.get("private_score",{}).get("mean_expected_operating_regret_per_customer")} for r in rows]}
    (output/"analysis.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    manifest.update(status="finished",observed_runs=len(rows),completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("specification",type=Path)
    launch(parser.parse_args().specification)
