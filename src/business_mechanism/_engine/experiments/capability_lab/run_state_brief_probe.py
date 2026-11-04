"""Frozen one-step public-state interface probe, not a scientific rollout.

Sixteen fresh model calls; validates proposed actions without executing tools.
Seven cases reuse real public API prefixes, one is a declared deadline/action
exhaustion transformation. Cases are correlated development fixtures.
"""
import copy
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys

import numpy
import scipy

from model_protocol import request_model, usage_summary
from native_science_protocol import decode_native, function_definitions
from public_context import unpack
from run_research import CONFIG
from scientific_readiness import readiness, validate_ready_action, validate_request_bindings
from state_brief import state_brief

ROOT = Path(__file__).resolve().parent
PHASE = "development_state_brief_probe_v01_20261012"
VERSION = "state-brief-probe-v0.1-one-step-contract-validation"
SYSTEM = "你是库存机制研究协调者，只看公共状态和已经收到的证据。本次仅选择一个下一步科学动作，使用一个具名函数；rationale与expected_gap各一句。动作将在接口层验证，不执行，因此不要声称取得了新数据或完成了研究。依据当前证据缺口、执行状态、原检查和资源选择；合法探索、并行研究和未决停止都允许。执行失败、未核实计数与科学反驳分开；拟合不是独立支持，旧数据不能认证自己的新模型。只使用请求前已有对象ID，商品用途不证明购买效应。表达式只能用公开算术变量，参数为[初值,下界,上界]。"


def load_prefix(phase, name, index):
    path = ROOT / "results" / phase / name
    content = path.read_bytes()
    run = json.loads(content)
    record = run["model_calls"][index]
    state = unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
    contract = {key: run["legal_input"][key] for key in (
        "task", "target", "history", "history_note", "operating_objective", "temporal_contract", "terminal_receipt_contract")}
    return {"state": state, "task_contract": contract,
            "recent_messages": copy.deepcopy(record["request"]["messages"][1:-1]),
            "provenance": {"file": str(path.relative_to(ROOT)), "request_index": index,
                "source_sha256": hashlib.sha256(content).hexdigest(),
                "original_public_event_count": record["public_research_event_count"], "transformation": None}}


def cases():
    organization = "development_organization_v01_20261012"
    a = "A_threeway_interruptions_s4601.json"
    specs = [
        ("no_data", organization, a, 0),
        ("pending", organization, a, 5),
        ("unverified", organization, a, 6),
        ("execution_failure", organization, a, 3),
        ("fitted_unconfirmed", organization, "A_mixed_scope_interruptions_s4601.json", 5),
        ("confirmation_pending", organization, "B_threeway_interruptions_s4601.json", 6),
        ("actual_refutation", "development_recovery_v01_20261012", "llm_recovery_threeway_interruptions_s4201.json", 0)]
    result = [{"case_id": identifier, **load_prefix(phase, name, index)} for identifier, phase, name, index in specs]
    terminal = copy.deepcopy(result[4])
    terminal["case_id"] = "deadline_and_last_action"
    terminal["state"]["clock"] = terminal["state"]["limits"]["logical_time"]
    terminal["state"]["scientific_actions_used"] = terminal["state"]["scientific_actions_limit"] - 1
    terminal["state"]["action_preconditions"] = readiness(terminal["state"])
    terminal["provenance"]["transformation"] = "Set public clock to deadline and scientific actions remaining to one; no new or altered measurements."
    result.append(terminal)
    return result


def freeze(folder):
    policy = json.loads((ROOT.parents[1] / "configs" / "experiment_progression.json").read_text())
    matrix = []
    inputs = cases()
    for index, case in enumerate(inputs):
        methods = ("without_brief", "with_brief") if index % 2 == 0 else ("with_brief", "without_brief")
        matrix.extend({"case_id": case["case_id"], "method": method} for method in methods)
    folder.mkdir(exist_ok=False)
    snapshot = folder / "source_snapshot"
    snapshot.mkdir()
    hashes = {}
    for path in sorted(ROOT.glob("*.py")):
        content = path.read_bytes()
        compile(content, str(path), "exec")
        hashes[path.name] = hashlib.sha256(content).hexdigest()
        shutil.copyfile(path, snapshot / path.name)
    manifest = {"phase": PHASE, "version": VERSION, "planned_tasks": matrix,
        "primary_endpoint": "decoded_single_action_passes_current_public_contract_and_request_bindings",
        "all_tools_executed": False, "model_config": CONFIG,
        "round_reported_token_budget": policy["default_round_reported_token_budget"],
        "model_calls_planned": len(matrix), "max_output_tokens": 1600, "retries": 0,
        "temperature": 0, "system_prompt": SYSTEM, "same_tools_for_both_methods": True,
        "environment": {"python": platform.python_version(), "numpy": numpy.__version__,
                        "scipy": scipy.__version__, "interpreter": sys.executable},
        "source_hashes": hashes, "policy": policy,
        "inputs_sha256": hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "limitations": "One call per method/case, correlated development snapshots, no scientific rollout, tool execution, new measurements, independent tasks, profit or causal attribution."}
    (folder / "cases.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + "\n")
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest, {case["case_id"]: case for case in inputs}


def run():
    test_log = ROOT / "results" / "development_state_brief_v01_20261012" / "unit-tests.log"
    if not test_log.read_text().rstrip().endswith("OK"):
        raise ValueError("full offline suite must pass before paid calls")
    folder = ROOT / "results" / PHASE
    manifest, inputs = freeze(folder)
    records = []
    summaries = []
    for index, task in enumerate(manifest["planned_tasks"]):
        case = inputs[task["case_id"]]
        state = copy.deepcopy(case["state"])
        if task["method"] == "with_brief":
            state["workflow_brief"] = state_brief(state)
        prompt = SYSTEM + ("workflow_brief只是公共待办提示，多个事项可并存，不是正确答案或固定科学顺序。" if task["method"] == "with_brief" else "")
        payload = {"model": CONFIG["model"], "messages": [{"role": "system", "content": prompt},
            *copy.deepcopy(case["recent_messages"]), {"role": "user", "content": json.dumps({
                "task_contract": case["task_contract"], "research_state": state}, ensure_ascii=False)}],
            "tools": function_definitions(case["state"]), "tool_choice": "auto",
            "parallel_tool_calls": False, "temperature": 0, "max_tokens": manifest["max_output_tokens"],
            **CONFIG.get("generation_options", {})}
        usage = usage_summary(records)
        bound = len(json.dumps(payload, ensure_ascii=False).encode()) + manifest["max_output_tokens"]
        if usage["calls_without_reported_usage"] or usage["total_tokens"] + bound > manifest["round_reported_token_budget"]:
            break
        record = request_model(CONFIG, payload)
        record.update(task=task, tools_executed=False, valid_public_contract=False,
                      source_provenance=case["provenance"], round_admission_byte_heuristic=bound)
        try:
            actions = decode_native(record["response"], CONFIG)
            record["actions"] = actions
            if len(actions) != 1:
                raise ValueError("this probe requires exactly one next action")
            validate_request_bindings(actions[0], case["state"])
            validate_ready_action(actions[0], case["state"])
            record["valid_public_contract"] = True
        except (KeyError, ValueError, TypeError, SyntaxError) as error:
            record["validation_error"] = str(error)
        records.append(record)
        filename = f"{index:02d}_{task['case_id']}_{task['method']}.json"
        with (folder / filename).open("x") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        summaries.append({"file": filename, **task, "valid_public_contract": record["valid_public_contract"],
                          "selected_tools": [action["tool"] for action in record.get("actions", [])],
                          "validation_error": record.get("validation_error")})
        print(json.dumps({"completed": len(records), "planned": len(manifest["planned_tasks"]),
                          "task": task, "valid_public_contract": record["valid_public_contract"],
                          "reported_tokens": usage_summary(records)["total_tokens"]}), flush=True)
    aggregate = {"planned_tasks": len(manifest["planned_tasks"]), "completed_tasks": len(records),
        "missing_tasks": manifest["planned_tasks"][len(records):], "records": summaries,
        "usage": usage_summary(records), "new_measurements": 0, "independent_new_business_tasks": 0,
        "end_to_end_agent_gain_established": False, "business_gain_established": False,
        "interpretation": manifest["limitations"]}
    with (folder / "analysis.json").open("x") as handle:
        handle.write(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"completed_tasks": len(records), "usage": aggregate["usage"]}), flush=True)


if __name__ == "__main__":
    run()
