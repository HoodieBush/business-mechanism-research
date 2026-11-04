"""API-boundary public replay, without counterfactual behavior or new data."""
import json
from pathlib import Path

from public_context import unpack
from research_notebook import ResearchNotebook
from scientific_readiness import readiness,validate_ready_action

ROOT=Path(__file__).resolve().parent


def analyze():
    rows=[];requests=0;repeated_reads=[];notebooks=[]
    for version in (5,7,8):
        directory=ROOT/"results"/f"development_scientific_v{version:02d}_20261012"
        for path in sorted(directory.glob("llm*.json")):
            run=json.loads(path.read_text());book=ResearchNotebook()
            for i,record in enumerate(run["model_calls"]):
                requests+=1;state=unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
                ready=readiness(state)
                for j,(action,feedback) in enumerate(zip(record.get("actions",[]),record.get("tool_feedbacks",[]))):
                    # Only the first action has this exact pre-action state.
                    # Later batch actions can change availability/IDs/clock.
                    if j==0:
                        try:validate_ready_action(action,state);rejection=None
                        except ValueError as exc:rejection=str(exc)
                        rows.append({"phase":directory.name,"file":path.name,"request_index":i,"tool":action["tool"],
                            "runtime_ok":feedback["ok"],"necessary_precondition_rejection":rejection,"public_ready_services":sum(v["ready"] for v in ready["services"].values())})
                    prior=len(book.entries);book.observe(action,feedback,state["clock"])
                    if action["tool"] in {"diagnose_history","retrieve_memory","read_memory","read_candidate","open_adaptation"} and feedback["ok"] and len(book.entries)==prior:
                        repeated_reads.append({"phase":directory.name,"file":path.name,"request_index":i,"tool":action["tool"]})
            notebooks.append({"phase":directory.name,"file":path.name,"receipts":len(book.entries),"summary":book.view()})
    result={"requests_replayed":requests,"first_actions_checked":len(rows),"necessary_precondition_rejections":sum(r["necessary_precondition_rejection"] is not None for r in rows),
        "same_receipt_repeats":repeated_reads,"records":rows,"notebooks":notebooks,"api_calls":0,
        "interpretation":"Opened development API-boundary replay only. Later batch-action states are not inferred from the first snapshot. Structural/protocol rejected responses are separate. A repeat is not necessarily illegal or irrational; notebook records do not certify target transfer. No counterfactual success, independence or token-saving claim."}
    path=ROOT/"results/setup_deepseek_20261012/readiness-replay-v01.json";path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");return result


if __name__=="__main__":
    r=analyze();print(json.dumps({"requests":r["requests_replayed"],"first_actions":r["first_actions_checked"],"flagged":r["necessary_precondition_rejections"],"repeated_receipts":len(r["same_receipt_repeats"]),"api_calls":0},ensure_ascii=False))
