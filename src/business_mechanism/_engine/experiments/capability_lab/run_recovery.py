"""Prospective continuation challenge after a shared, public scientific prefix.

This is a conditional entry challenge, not end-to-end autonomous discovery or
an A/B/C organization comparison. Outcomes do not choose which tasks run.
"""
import argparse
import copy
import json
from pathlib import Path
import time

from choice_world import ChoiceWorld
from model_protocol import usage_summary
from operating_eval import evaluate
from research_action_schema import SCHEMA
from research_actor import ScienceActor
from research_queue import CONTRACT, ResearchQueue
from research_runtime import ResearchRuntime
from run_research import CONFIG
from run_scientific import agent_view
from semantic_compile import compile_structured
from temporal_lab import TemporalLab, digest

ROOT = Path(__file__).resolve().parent
VERSION = "recovery-challenge-v0.1-public-entry-original-budget"
STRATEGIES = ["frozen_reference", "numeric_recovery", "llm_recovery"]


def filename(t):
    return f"{t['strategy']}_{t['family']}_{t['profile']}_s{t['seed']}.json"


def run(task, spec):
    path = ROOT / "results" / spec["phase"] / filename(task)
    if path.exists():
        raise ValueError("result exists")
    limits = spec["api_limits"]
    lab = TemporalLab(ChoiceWorld(task["seed"], task["family"], "none", "structured", spec["price"]),
                      task["profile"], spec["deadline"])
    lab.limits.update(api_calls=limits["calls"], api_tokens=limits["reported_tokens"])
    rt = ResearchRuntime(lab, terminal_policy=spec["terminal_policy"])
    rt.initial["research_workflow_contract"] = copy.deepcopy(CONTRACT)
    queue = ResearchQueue(); context_id = "original_research"
    result = {"phase": spec["phase"], "version": VERSION, "strategy": task["strategy"],
              "private_configuration": {k: task[k] for k in ("seed", "family", "profile")} |
                  {"deadline": spec["deadline"], "price": spec["price"]},
              "legal_input": copy.deepcopy(rt.initial), "model_config": CONFIG, "model_calls": [], "status": "running",
              "scientific_protocol": {"max_checks": 6, "n_per_cohort": 800, "cohorts_per_check": 2,
                  "total_alpha": .05, "tolerance": .05, "max_revisions": 2, "max_scientific_actions": 64,
                  "api_limits": limits, "entry_challenge": spec["entry_challenge"],
                  "api_and_cpu_wall_time_excluded_from_research_ticks": True}}

    def save():
        result.update(research=rt.snapshot(), research_queue=queue.snapshot(),
                      gateway_events=copy.deepcopy(lab.events), used=copy.deepcopy(lab.used),
                      public_final_state=lab.public_state(), model_usage=usage_summary(result["model_calls"]))
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    def call(tool, args=None):
        f = rt.call(tool, {} if args is None else args, "事前声明的公共挑战策略。", "核对或检验新条件。")
        save()
        if not f["ok"]:
            raise ValueError(f["error"])
        return f["result"]

    def receive_and_dispatch():
        if queue.contexts[context_id]["status"] == "waiting":
            queue.advance(context_id); save()
        if queue.pop_ready() != context_id:
            raise ValueError("original context was not runnable")

    started = time.monotonic()
    try:
        call("diagnose_history"); call("open_adaptation")
        products = lab.public_catalog("source")
        h = next(p["id"] for p in products if p["functions"]["heating"] and not p["functions"]["utensils"])
        u = next(p["id"] for p in products if p["functions"]["utensils"] and not p["functions"]["heating"])
        call("sample", {"candidate_id": rt.initial_candidate, "designs": [
            {"stage": "source", "site": "00", "assortment": a, "n": 400} for a in ([], [h], [u])],
            "rationale": "公共三臂起点，不依据私有世界选择。"})
        call("collect", {"until": "all", "repair": True, "refit": True, "assess": False})
        call("confirm", {"candidate_id": rt.pool[0], "rationale": "公开分歧前沿登记一项新条件检查。"})
        result["entry_research_events"] = copy.deepcopy(rt.events)
        result["entry_gateway_events"] = copy.deepcopy(lab.events)
        result["entry_used"] = copy.deepcopy(lab.used)
        result["entry_candidate_id"] = rt.checks[0]["candidate_id"]
        queue.register(context_id, rt); receive_and_dispatch()
        result["first_wakeup"] = queue.view(context_id)
        save()
        if task["strategy"] == "numeric_recovery":
            for _ in range(spec["numeric_additional_checks"]):
                latest = rt.checks[-1]
                if lab.clock >= lab.deadline or rt.calls >= rt.max_calls - 4:
                    break
                if latest["result"] is not None and latest["result"]["state"] == "contradicted" and not latest["released"] and rt.revisions < 2:
                    call("reopen_research", {"check_id": latest["check_id"], "rationale": "实际新条件反驳后释放证据重估。", "refit": True})
                call("confirm", {"candidate_id": rt.pool[0], "rationale": "剩余原检查额度中独立再确认。"})
                queue.after_decision(context_id); receive_and_dispatch()
        elif task["strategy"] == "llm_recovery":
            def view(runtime):
                return agent_view(runtime) | {"research_workflow_contract": copy.deepcopy(CONTRACT),
                                             "workflow_context": queue.view(context_id)}
            actor = ScienceActor(rt, view, SCHEMA, limits, wire_mode="native", state_aware=True)
            errors = 0
            while not rt.closed and rt.calls < rt.max_calls - 1 and lab.tool_calls < lab.limits["tool_calls"] - 2:
                record = actor.next(result["model_calls"])
                if record is None:
                    result["coordinator_stop_reason"] = "api_allocation_exhausted_or_preflight"
                    result["api_stop_preflight"] = copy.deepcopy(actor.last_preflight); break
                result["model_calls"].append(record)
                result["reading_notebook"] = actor.notebook.snapshot(); save()
                queue.after_decision(context_id)
                if rt.closed:
                    break
                invalid = "submission_error" in record or not all(f.get("ok", False) for f in record.get("tool_feedbacks", []))
                errors = errors + 1 if invalid else 0
                if errors >= 3:
                    result["coordinator_stop_reason"] = "three_consecutive_invalid_actions"; break
                if lab.clock >= lab.deadline:
                    result["coordinator_stop_reason"] = "calendar_deadline"; break
                # No data-plane work after the decision allocation is exhausted.
                if usage_summary(result["model_calls"])["api_calls"] >= limits["calls"]:
                    result["coordinator_stop_reason"] = "api_call_allocation"; break
                receive_and_dispatch()
        if not rt.closed:
            cid = rt.checks[-1]["candidate_id"] if task["strategy"] == "llm_recovery" else rt.pool[0]
            call("finish", {"candidate_id": cid, "claims": "仅独立检查所列条件；未测范围与机制唯一性未决。",
                            "unresolved": True, "stop_reason": result.get("coordinator_stop_reason", "事前挑战策略结束。")})
            if queue.contexts[context_id]["status"] == "waiting":
                queue.advance(context_id)
            else:
                queue.after_decision(context_id)
            if task["strategy"] == "llm_recovery":
                result["terminal_fallback"] = True
        result.update(frozen_final=copy.deepcopy(rt.final["frozen_final"]), mechanism_card=copy.deepcopy(rt.final["mechanism_card"]),
                      frozen_expression_sha256=digest(lab.final["model"]["expression"]))
        deployment = lab.call("deployment_catalog", {})
        facts = compile_structured(lab.public_catalog("source") + lab.public_catalog("adaptation") + deployment)
        result["deployment_physical_facts"] = facts
        result["deployed_model"] = {"role_patterns": facts["role_patterns"], "expression": copy.deepcopy(lab.final["model"]["expression"])}
        result["private_score"] = evaluate(lab._core._world, lab.final["model"], result["deployed_model"])
        result["status"] = "actor_budget_stopped" if result.get("terminal_fallback") else "finished_scoped"
    except Exception as error:
        result.update(status="execution_failure", error=type(error).__name__ + ": " + str(error))
    result["elapsed_seconds"] = time.monotonic() - started; save()
    print(json.dumps({"file": path.name, "status": result["status"], "checks": len(rt.checks), "revisions": rt.revisions,
                      "usage": result["model_usage"], "error": result.get("error")}), flush=True)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--spec", type=Path, required=True); args = ap.parse_args()
    spec = json.loads(args.spec.read_text())
    for seed in spec["seeds"]:
        for family in spec["families"]:
            for profile in spec["profiles"]:
                for strategy in spec["strategies"]:
                    run(dict(seed=seed, family=family, profile=profile, strategy=strategy), spec)
