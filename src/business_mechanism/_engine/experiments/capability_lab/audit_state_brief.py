"""Project the new brief on saved public API prefixes; no new experiment."""
import argparse
import hashlib
import json
from pathlib import Path

from public_context import unpack
from state_brief import state_brief, VERSION


def analyze(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    rows = []
    missing = []
    source_hashes = {}
    for task in manifest["planned_tasks"]:
        name = f"{task['strategy']}_{task['family']}_{task['profile']}_s{task['seed']}.json"
        path = folder / name
        if not path.exists():
            missing.append(name)
            continue
        content = path.read_bytes()
        source_hashes[name] = hashlib.sha256(content).hexdigest()
        run = json.loads(content)
        for index, record in enumerate(run["model_calls"]):
            request = record["request"]
            state = unpack(json.loads(request["messages"][-1]["content"]))["research_state"]
            brief = state_brief(state)
            original = state.get("action_preconditions", {}).get("services")
            same_menu = original is None or brief["available_services"] == sorted(
                key for key, value in original.items() if value["ready"])
            rows.append({"source_file": name, "request_index": index,
                         "original_public_event_count": record["public_research_event_count"],
                         "brief": brief, "original_public_feasibility_menu_preserved": same_menu})
    return {"version": VERSION, "source_phase": folder.name,
            "source_hashes": source_hashes, "planned_runs": len(manifest["planned_tasks"]),
            "missing_runs": missing, "api_prefixes": len(rows), "records": rows,
            "all_public_menus_preserved": all(row["original_public_feasibility_menu_preserved"] for row in rows),
            "new_model_calls": 0, "new_measurements": 0, "agent_behavior_gain_established": False,
            "interpretation": "Retrospective public-state projection; the original agents did not receive this brief. Not new independent evidence or a behavior effect."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.folder)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("planned_runs", "api_prefixes", "missing_runs", "all_public_menus_preserved")}))


if __name__ == "__main__":
    main()
