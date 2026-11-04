import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from discovery_tasks import SERVICES
from audit_discovery_tasks import audit as task_audit
from audit_scientific import audit as scientific_audit
from audit_organization import audit as organization_audit
from native_science_protocol import function_definitions
from research_runtime import ResearchRuntime
from run_scientific import agent_view
from scientific_readiness import readiness, validate_ready_action, validate_request_bindings
from temporal_lab import TemporalLab, digest
from public_context import pack,unpack


class DiscoveryTaskTests(unittest.TestCase):
    def runtime(self, enabled=True, deadline=120):
        rt = ResearchRuntime(TemporalLab(ChoiceWorld(5502, "mixed_scope"), "interruptions", deadline),
            terminal_policy="settle_committed", organization_mode="A", use_discovery_tasks=enabled)
        self.assertTrue(rt.call("open_adaptation", {})["ok"])
        return rt

    def start(self, rt, count=3, repair=True):
        return rt.call("start_discovery_task", {"candidate_id": rt.initial_candidate, "count": count,
            "objective": "取得能区分公开候选的发现数据。", "rationale": "有限公开frontier批次。", "repair": repair})

    def finish(self, rt):
        return rt.call("finish", {"candidate_id": rt.pool[0] if rt.pool else rt.initial_candidate,
            "claims": "批次拟合未独立认证。", "unresolved": True, "stop_reason": "夹具停止。"})

    def test_task_uses_same_frontier_measurements_and_model_as_common_primitives(self):
        task_rt = self.runtime();plain_rt = self.runtime(False)
        result = self.start(task_rt);self.assertTrue(result["ok"])
        task = result["result"];self.assertEqual(task["status"], "completed")
        self.assertEqual(task_rt.calls, 4)  # opening + outer + sample + worker
        self.assertTrue(plain_rt.call("sample_frontier", {"candidate_id": plain_rt.initial_candidate, "count": 3, "rationale": "有限公开frontier批次。"})["ok"])
        self.assertTrue(plain_rt.call("collect", {"until": "all", "repair": True, "refit": True, "assess": False})["ok"])
        def rows(rt):return [{key: row[key] for key in ("stage", "site", "assortment", "n", "observed_sales", "verified_supply", "verified_meter")}
                            for row, _ in rt.gateway.verified_observations()]
        self.assertEqual(rows(task_rt), rows(plain_rt))
        self.assertEqual(task_rt.registry[task_rt.pool[0]]["model"], plain_rt.registry[plain_rt.pool[0]]["model"])
        self.assertEqual(task_rt.gateway.used, plain_rt.gateway.used)
        self.assertFalse(task["artifact"]["independent_support"])
        registered = next(event for event in task_rt.events if event["kind"] == "discovery_task_registered")
        self.assertLess(registered["sequence"], min(event["sequence"] for event in task_rt.events if event["kind"] == "registered_plan_linked"))
        self.assertEqual(registered["payload"]["frozen_designs"], task["frozen_designs"])

    def test_rejected_batch_has_no_task_plan_or_sampling_and_keeps_terminal_action(self):
        rt = self.runtime();rt.gateway.limits["sessions"] = 400
        used = copy.deepcopy(rt.gateway.used)
        result = self.start(rt)
        self.assertFalse(result["ok"]);self.assertEqual(rt.gateway.used, used)
        self.assertEqual(rt.discovery_tasks.tasks, {});self.assertEqual(rt.jobs, {})
        rt = self.runtime();rt.max_calls = rt.calls + 3
        self.assertFalse(self.start(rt)["ok"])
        self.assertTrue(self.finish(rt)["ok"])

    def test_unverified_or_failed_batch_is_not_fitted_then_advance_finishes_original_jobs(self):
        rt = self.runtime();task = self.start(rt, repair=False)["result"]
        self.assertNotEqual(task["status"], "completed");self.assertIsNone(task["artifact"])
        self.assertEqual(rt.pool, [])
        jobs = set(rt.jobs);plans = digest(rt.objects["plans"]);before = rt.calls
        advanced = rt.call("advance_discovery_task", {"task_id": task["task_id"], "rationale": "核实原批次。", "repair": True})
        self.assertTrue(advanced["ok"]);self.assertEqual(advanced["result"]["status"], "completed")
        self.assertEqual(set(rt.jobs), jobs);self.assertEqual(digest(rt.objects["plans"]), plans)
        self.assertEqual(rt.calls - before, 2)
        self.assertEqual(len(advanced["result"]["artifact"]["owned_experiment_ids"]), 3)

    def test_completed_advance_is_cached_and_does_not_refit_or_resample(self):
        rt = self.runtime();task = self.start(rt)["result"]
        used = copy.deepcopy(rt.gateway.used);registry = digest(rt.registry);count = len(rt.events);before = rt.calls
        response = rt.call("advance_discovery_task", {"task_id": task["task_id"], "rationale": "读取已完成产物。", "repair": True})
        self.assertEqual(response["result"], task);self.assertEqual(rt.gateway.used, used)
        self.assertEqual(digest(rt.registry), registry);self.assertEqual(rt.calls - before, 1)
        self.assertEqual(len(rt.events) - count, 1)

    def test_worker_does_not_retry_an_unowned_failed_job(self):
        rt = self.runtime()
        self.assertTrue(rt.call("sample", {"candidate_id": rt.initial_candidate,
            "designs": [{"stage": "source", "site": "00", "assortment": [], "n": 400},
                        {"stage": "source", "site": "00", "assortment": [], "n": 400}], "rationale": "其他原计划。"})["ok"])
        failed = rt.gateway.public_state()["failed_jobs"][0];other = failed["job_id"];attempts = failed["attempts"]
        task = self.start(rt, count=1)["result"]
        self.assertEqual(task["status"], "completed");self.assertNotIn(other, task["job_ids"])
        failed = next(job for job in rt.gateway.public_state()["failed_jobs"] if job["job_id"] == other)
        self.assertEqual(failed["attempts"], attempts)

    def test_later_meter_repair_preserves_cohorts_and_produces_verified_artifact(self):
        rt = self.runtime();self.start(rt)
        task = self.start(rt)["result"]
        self.assertEqual(task["status"], "completed")
        self.assertIn(3, task["job_ids"])
        events = [event for event in rt.gateway.events if event.get("request", {}).get("tool") == "reconcile_measurement"]
        self.assertEqual([event["request"]["args"]["job_id"] for event in events], [3])
        self.assertEqual(rt.gateway.used["sessions"], 2400)
        self.assertEqual(len(rt.gateway.verified_observations()), 6)

    def test_concurrent_confirmation_receipts_are_not_released_or_used_by_task_fit(self):
        rt = self.runtime();self.start(rt, count=1)
        cid = rt.pool[0]
        self.assertTrue(rt.call("confirm", {"candidate_id": cid, "rationale": "未释放检查。"})["ok"])
        task = self.start(rt, count=1)["result"]
        self.assertEqual(task["status"], "completed")
        check_jobs = set(rt.checks[0]["job_ids"])
        eligible_jobs = {row["job_id"] for row, _ in rt.gateway.verified_observations()}
        self.assertFalse(eligible_jobs & check_jobs)
        self.assertFalse(rt.checks[0]["released"])
        self.assertEqual(rt.revisions, 0)

    def test_deadline_and_terminal_receipts_cannot_complete_or_refit_a_closed_task(self):
        rt = self.runtime(deadline=2);task = self.start(rt)["result"]
        self.assertEqual(task["status"], "deadline_unresolved");self.assertIsNone(task["artifact"])
        rt = self.runtime();task = self.start(rt, repair=False)["result"]
        registry = digest(rt.registry);self.assertTrue(self.finish(rt)["ok"])
        self.assertEqual(digest(rt.registry), registry)
        self.assertEqual(rt.discovery_tasks.tasks[task["task_id"]]["status"], "closed_unresolved")
        self.assertIsNone(rt.discovery_tasks.tasks[task["task_id"]]["artifact"])
        with self.assertRaises(ValueError):rt.discovery_tasks.advance(rt, {"task_id": task["task_id"], "repair": True})

    def test_public_task_domains_and_request_bindings_do_not_admit_future_ids(self):
        rt = self.runtime();before = agent_view(rt)
        tools = {item["function"]["name"] for item in function_definitions(before)}
        self.assertIn("start_discovery_task", tools);self.assertNotIn("advance_discovery_task", tools)
        self.start(rt);after = agent_view(rt)
        action = {"tool": "advance_discovery_task", "args": {"task_id": "D0000", "rationale": "已收到。", "repair": True}}
        validate_ready_action(action, after)
        with self.assertRaises(ValueError):validate_request_bindings(action, before)
        validate_request_bindings(action, after)
        action["args"]["task_id"] = "C0000"
        with self.assertRaises(ValueError):validate_ready_action(action, after)
        disabled = agent_view(self.runtime(False))
        self.assertFalse(SERVICES & set(readiness(disabled)["services"]))
        self.assertFalse(SERVICES & {item["function"]["name"] for item in function_definitions(disabled)})

    def test_actual_task_protocol_and_scientific_audit_end_to_end_with_mock_api(self):
        import run_organization
        steps = iter(("open_adaptation", "start_discovery_task", "confirm_and_analyze", "finish"))
        def request(_, payload):
            state = unpack(json.loads(payload["messages"][-1]["content"]))["research_state"]
            tool = next(steps);cid = state["candidates"][0]["candidate_id"] if state["candidates"] else state["initial_candidate_id"]
            args = {"rationale": "协议夹具，不是付费科研结果。", "expected_gap": "验证真实工具与产物审计。"}
            if tool == "start_discovery_task":args.update(candidate_id=cid, count=3, objective="有限发现批次。", repair=True)
            if tool == "confirm_and_analyze":args.update(candidate_id=cid, repair=True)
            if tool == "finish":args.update(candidate_id=cid, claims="仅实际条件反馈，未测范围未决。", unresolved=True, stop_reason="协议夹具结束。")
            raw = {"choices": [{"finish_reason": "stop", "message": {"content": "", "tool_calls": [{"id": "call_test", "type": "function",
                "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
            return {"request": copy.deepcopy(payload), "cache_hit": False, "response": raw}
        spec = {"phase": "unit_mock_task_protocol", "price": 10., "deadline": 120, "terminal_policy": "settle_committed",
            "api_limits": {"calls": 4, "reported_tokens": 250000, "max_output_tokens": 2400, "admission_policy": "provider_prompt_ratio"},
            "actor_features": {"discovery_tasks": {"use_discovery_tasks": True, "use_reference_contract": True, "use_confirmation_phase": True}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);(root / "results" / spec["phase"]).mkdir(parents=True)
            with patch("run_organization.ROOT", root), patch("research_actor.request_model", side_effect=request), patch("builtins.print"):
                run = run_organization.run({"seed": 5502, "family": "mixed_scope", "profile": "interruptions", "strategy": "discovery_tasks"}, spec)
            # Auditors consume the saved JSON artifact, as in real experiments.
            run = json.loads(next((root / "results" / spec["phase"]).glob("*.json")).read_text())
        self.assertEqual(run["status"], "finished_scoped", run.get("error"))
        self.assertTrue(task_audit(run)["passed"], task_audit(run))
        self.assertTrue(scientific_audit(run)["passed"], scientific_audit(run))
        self.assertTrue(organization_audit(run)["passed"], organization_audit(run))
        changed = copy.deepcopy(run)
        event = next(event for event in changed["research"]["events"] if event["kind"] == "discovery_task_updated" and event["payload"]["status"] == "completed")
        event["payload"]["artifact"]["owned_experiment_ids"] = [999]
        self.assertFalse(task_audit(changed)["passed"])
        changed = copy.deepcopy(run)
        event = next(event for event in changed["research"]["events"] if event["kind"] == "discovery_task_updated" and event["payload"]["status"] == "completed")
        event["payload"]["frozen_designs"][0]["n"] = 800
        self.assertFalse(task_audit(changed)["passed"])
        changed=copy.deepcopy(run);record=changed["model_calls"][-1]
        context=unpack(json.loads(record["request"]["messages"][-1]["content"]))
        context["research_state"]["confirmation_status"]["checks"][0]["analysis_phase"]="FAKE_READY"
        record["request"]["messages"][-1]["content"]=json.dumps(pack(context),ensure_ascii=False)
        self.assertIn("confirmation_phase_public_prefix_recompute",scientific_audit(changed)["issues"])


if __name__ == "__main__":unittest.main()
