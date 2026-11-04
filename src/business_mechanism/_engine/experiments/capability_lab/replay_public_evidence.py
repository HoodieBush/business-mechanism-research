"""Zero-API public-event replay; historical actors did not receive the new view."""
import copy
import json
from pathlib import Path

from audit_scientific import audit
from lab import predict
from public_context import assert_roundtrip, compact_json, unpack
from public_evidence import PublicEvidenceStore, retrospective_review
from temporal_lab import digest

ROOT = Path(__file__).resolve().parent; PROJECT = ROOT.parents[1]


def replay(source):
    source = Path(source); run = json.loads(source.read_text())
    research = run["research"]; events = research["events"]
    store = PublicEvidenceStore.from_events(events)
    catalogs = {"source": copy.deepcopy(run["legal_input"]["catalog"])}
    for event in run["gateway_events"]:
        if event["kind"] == "tool_response" and event["request"]["tool"] == "open_transfer":
            catalogs["adaptation"] = copy.deepcopy(event["payload"]["catalog"])
    candidates = {event["payload"]["candidate_id"]: event["payload"] for event in events if event["kind"] == "candidate_registered"}
    boundaries = []
    for index, record in enumerate(run["model_calls"]):
        count = record["public_research_event_count"]; prefix = events[:count]
        if prefix[-1]["event_hash"] != record["public_research_prefix_hash"]:
            raise ValueError("original API event prefix mismatch")
        current = PublicEvidenceStore.from_events(prefix)
        public = unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
        projection = copy.deepcopy(public) | {"public_evidence_store": current.view()}
        assert_roundtrip(projection)
        ids = [candidate["candidate_id"] for candidate in public["candidates"]]
        if any(candidates[cid]["available_at"] > record["clock"] or cid not in current.candidates for cid in ids):
            raise ValueError("retrospective query references a future candidate")
        boundaries.append({"request_index": index, "original_research_event_count": count,
                           "original_research_prefix_hash": record["public_research_prefix_hash"],
                           "public_analysis_view": current.view(),
                           "state_bytes_before": len(compact_json(assert_roundtrip(public)).encode()),
                           "state_bytes_with_analysis_cards": len(compact_json(assert_roundtrip(projection)).encode()),
                           "candidate_reviews": [retrospective_review(cid, candidates[cid], current, catalogs, predict) for cid in ids]})
    frozen = research["final"]["candidate_id"]
    return {"source_file": str(source.relative_to(PROJECT)), "source_status": run["status"],
            "original_scientific_audit": audit(run), "archive": store.snapshot(), "request_boundaries": boundaries,
            "frozen_candidate_review": retrospective_review(frozen, candidates[frozen], store, catalogs, predict),
            "new_api_calls": 0, "new_samples": 0, "new_independent_units": 0,
            "historical_actor_received_new_view": False}


def main(spec_file):
    spec = json.loads(Path(spec_file).read_text()); out = ROOT / "results" / spec["phase"]
    results = [replay(PROJECT / source) for source in spec["source_files"]]
    summary = {"phase": spec["phase"], "source_records": len(results),
               "original_request_boundaries": sum(len(r["request_boundaries"]) for r in results),
               "analysis_instances": sum(len(r["archive"]["analysis_cards"]) for r in results),
               "versioned_analysis_records": sum(len(r["archive"]["records"]) for r in results),
               "all_original_scientific_audits_passed": all(r["original_scientific_audit"]["passed"] for r in results),
               "new_api_calls": 0, "new_samples": 0, "new_independent_units": 0,
               "interpretation": "Public archive/diagnostic replay only, without counterfactual actor performance, new independence, paid validation or token-saving claims.", "records": results}
    (out / "replay.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("spec", type=Path); args = ap.parse_args(); main(args.spec)
