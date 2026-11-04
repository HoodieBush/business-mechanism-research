"""Replay an explicit source-evidence withdrawal against actual target traces.

This is a fault-injection acceptance trajectory, not a new cohort experiment or
an assertion that the source publisher actually withdrew these observations.
The source archive and the target's own evidence remain immutable.
"""
import argparse
import copy
import json
from pathlib import Path

from analyze_openworld import read_runs
from conditional_memory import ConditionalMemory,digest


def replay(row,value):
    memory=ConditionalMemory(value,row["legal_input"],row["adaptation_physical_facts"],row["memory_trace"]["mode"])
    memory.target_links=copy.deepcopy(row["memory_trace"]["target_versions"])
    selected=next((v for v in memory.target_links if v["memory_episode_refs"]),None)
    if selected is None:return None
    episode_id=selected["memory_episode_refs"][0]
    episode=next(e for e in value["episodes"] if e["episode_id"]==episode_id)
    evidence_id=episode["version_lineage"][-1]["training_dependencies"][0]
    before=memory.trace();source_before=digest(memory.archive)
    update=memory.invalidate_evidence(evidence_id,"开发故障注入：源回执被发布方撤回，等待重新核查；此事件为模拟输入。")
    after=memory.trace()
    affected=[v for v in after["target_versions"] if episode_id in v["memory_episode_refs"]]
    issues=[]
    if digest(memory.archive)!=source_before:issues.append("original_source_evidence_erased")
    if any(e["eligible"] for e in memory.entries if e["episode"]["episode_id"]==episode_id):issues.append("withdrawn_source_still_retrieved")
    if any(v["source_dependency_state"]!="stale_requires_review" for v in affected):issues.append("dependent_instance_not_marked_stale")
    for old,new in zip(before["target_versions"],after["target_versions"]):
        if any(old[k]!=new[k] for k in ("instance_id","target_training_ids","target_check_ids","state")):
            issues.append("independent_target_evidence_or_check_rewritten")
    return {"target_public_episode_id":row["public_memory_export"]["episode_id"],
        "scenario":"declared_source_receipt_withdrawal_fault_injection", "new_sessions":0,"model_api_calls":0,
        "source_archive_id":value["archive_id"],"before":before,"public_update":update,"after":after,
        "next_research_action":"复核被撤回源证据及其依赖；暂停该源条目的新复用，保留目标自身独立检查，不把源撤销自动当作目标科学反证。",
        "status":"passed" if not issues else "failed","issues":issues}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("directories",nargs="+",type=Path);parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error("withdrawal replay already exists")
    rows=[];project=Path(__file__).resolve().parents[2]
    for directory in args.directories:
        manifest=json.loads((directory/"manifest.json").read_text())
        value=json.loads((project/manifest["snapshot"]/manifest["specification"]["memory_archive"]).read_text())
        for row in read_runs(directory):
            if row["status"]!="finished":continue
            result=replay(row,value)
            if result is not None:rows.append(result)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({"phase":"development_state_replay_not_independent_tasks", "records":rows,
        "new_sessions":0,"model_api_calls":0,"source_withdrawal_is_simulated":True,
        "status_counts":{s:sum(r["status"]==s for r in rows) for s in ("passed","failed")}},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"replays":len(rows),"passed":sum(r["status"]=="passed" for r in rows),"new_sessions":0,"model_api_calls":0}))
