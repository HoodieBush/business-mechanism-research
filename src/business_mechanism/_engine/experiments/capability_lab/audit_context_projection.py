"""No-API matched public payload replay; it does not predict agent behavior."""
import copy
import json
from pathlib import Path

from public_context import VERSION,assert_roundtrip,compact_json,unpack
from temporal_lab import digest

ROOT=Path(__file__).resolve().parent


def analyze(directory):
    directory=Path(directory);reports=[];candidate_count=0;public_evidence_count=0
    for path in sorted(directory.glob("*_s*.json")):
        run=json.loads(path.read_text())
        # Verify on all archived public candidates, not only the model's last
        # successful request. The replay never reads private_score/configuration.
        for candidate in run["research"]["objects"]["candidates"]:
            assert_roundtrip(candidate);candidate_count+=1
        public_evidence_count+=len(run["public_final_state"]["mature_evidence"])
        for i,record in enumerate(run["model_calls"]):
            payload=copy.deepcopy(record["request"]);message_checks=[]
            for message in payload["messages"]:
                if message["role"] not in {"user","tool"}:continue
                try:value=json.loads(message["content"])
                except (ValueError,TypeError):continue
                projected=assert_roundtrip(value);message["content"]=compact_json(projected)
                message_checks.append({"role":message["role"],"canonical_sha256":digest(value),"restored_sha256":digest(unpack(json.loads(message["content"]))),"equal":unpack(projected)==value})
            old=len(json.dumps(record["request"],ensure_ascii=False).encode());new=len(json.dumps(payload,ensure_ascii=False).encode())
            reports.append({"file":path.name,"request_index":i,"old_request_bytes":old,"structural_request_bytes":new,"ratio":new/old,"message_roundtrips":message_checks})
    old=sum(r["old_request_bytes"] for r in reports);new=sum(r["structural_request_bytes"] for r in reports)
    result={"source_phase":directory.name,"encoding":VERSION,"requests_replayed":len(reports),"public_candidates_roundtripped":candidate_count,
        "public_latest_evidence_rows":public_evidence_count,"old_request_bytes":old,"structural_request_bytes":new,"byte_reduction_fraction":1-new/old if old else None,
        "all_exact_roundtrips":all(c["equal"] and c["canonical_sha256"]==c["restored_sha256"] for r in reports for c in r["message_roundtrips"]),"records":reports,
        "api_calls":0,"interpretation":"Matched opened public payload encoding replay. ASTs/types/rows roundtrip exactly. Byte reduction is not a provider-token, billing, context-comprehension, scientific-success or independent-task result. New resource guidance and corrected integer job schema are separate changes."}
    output=ROOT/"results/setup_deepseek_20261012/public-context-replay-v01.json";output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");return result


if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("directory",type=Path);args=ap.parse_args();r=analyze(args.directory)
    print(json.dumps({k:v for k,v in r.items() if k!="records"},ensure_ascii=False,indent=2))
