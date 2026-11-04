"""Developer-side export: public memory and a separate private provenance index."""
import argparse
import hashlib
import json
from pathlib import Path

from analyze_openworld import read_runs
from conditional_memory import archive,export_episode


def export(source,output,strategy="numeric_full_frontier"):
    if output.exists() or output.with_suffix(".provenance.json").exists():raise ValueError("memory export already exists")
    episodes=[];provenance=[]
    # All matching source runs, including unconfirmed/refuted models; never
    # select by private scores or knowledge of the target worlds.
    for row in read_runs(source):
        if row["strategy"]!=strategy:continue
        if row["status"]!="finished":raise ValueError("source matrix has unfinished selected episode")
        e=export_episode(row["legal_input"],row["adaptation_physical_facts"],row["events"],
            row["research_versions"],row["confirmations"],row["used"])
        episodes.append(e)
        c=row["private_configuration"];name=f"{strategy}_{c['family']}_{c['fault']}_{c['fact_mode']}_s{c['seed']}.json"
        path=source/name
        provenance.append({"episode_id":e["episode_id"],"source_file":str(path),
            "source_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    value=archive(episodes);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    output.with_suffix(".provenance.json").write_text(json.dumps({"not_for_agent_context":True,
        "public_archive_id":value["archive_id"],"source_runs":provenance},ensure_ascii=False,indent=2)+"\n")
    return {"archive_id":value["archive_id"],"episodes":len(episodes),"source_acquisition_cost":value["source_acquisition_cost"]}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("source",type=Path);parser.add_argument("output",type=Path)
    parser.add_argument("--strategy",default="numeric_full_frontier")
    args=parser.parse_args();print(json.dumps(export(args.source,args.output,args.strategy)))
