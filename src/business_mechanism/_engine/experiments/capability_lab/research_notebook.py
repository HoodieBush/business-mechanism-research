"""Task-local public reading receipts; source counts never become target data."""
import copy

from temporal_lab import digest

VERSION="research-notebook-v0.1-public-read-receipts"
READS={"diagnose_history","open_adaptation","retrieve_memory","read_memory","read_candidate","review_memory"}


class ResearchNotebook:
    def __init__(self):self.entries=[];self._queries={};self._contents={}

    def observe(self,action,feedback,clock):
        if action["tool"] not in READS or not feedback.get("ok"):return
        result=copy.deepcopy(feedback["result"]);key=digest({"tool":action["tool"],"args":action["args"]});content=digest(result)
        previous=self._queries.get(key)
        if previous is not None and previous["content_sha256"]==content:return
        refs=[result[k] for k in ("episode_id","candidate_id","archive_id","initial_candidate_id") if k in result]
        entry={"receipt_id":f"R{len(self.entries):03d}","tool":action["tool"],"args":copy.deepcopy(action["args"]),"available_at":clock,
            "query_sha256":key,"content_sha256":content,"object_refs":refs,"parent_receipt":None if previous is None else previous["receipt_id"]}
        if action["tool"]=="read_memory":entry["structural_summary"]={"episode_id":result["episode_id"],"source_state":result["source_state"],
            "template_expression":None if result["template"] is None else result["template"]["expression"],"source_price":result["public_context"]["operating_objective"]["retail_price"],
            "conditional_claim_ids":[c["claim_id"] for c in result["conditional_claims"]],"target_certification":"none; source receipt is only a structural prior"}
        self.entries.append(entry);self._queries[key]=entry;self._contents[entry["receipt_id"]]=result

    def view(self):
        return {"version":VERSION,"receipts":copy.deepcopy(list(self._queries.values())),
            "scope":"Only successful task-local public reads. Original contents remain retrievable through the same source/candidate service and are archived under receipt hashes. No target likelihood data or independent samples are added."}

    def snapshot(self):return {"version":VERSION,"entries":copy.deepcopy(self.entries),"contents":copy.deepcopy(self._contents)}
