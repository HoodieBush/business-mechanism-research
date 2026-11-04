import copy
import json
from pathlib import Path
import tempfile
import unittest

from audit_agent_usability import analyze, summarize_run


def run_fixture():
    return {"strategy": "B", "status": "actor_budget_stopped", "model_calls": [],
            "research": {"checks": [], "research_organization": {"contexts": [
                {"context_id": "supervisor", "parent_id": None},
                {"context_id": "generator", "parent_id": None},
                {"context_id": "reviewer", "parent_id": None}]}},
            "mechanism_card": {"state": "pending_confirmation"},
            "private_score": {"hidden": "DO_NOT_EXPORT"}}


def request(actions, feedbacks):
    return {"organization_context_id": "supervisor", "actions": actions, "tool_feedbacks": feedbacks,
            "request": {"tools": [], "messages": [{"role": "user", "content": json.dumps({
                "research_state": {"checks": []}})}]}}


class AgentUsabilityTests(unittest.TestCase):
    def test_request_and_action_denominators_are_distinct(self):
        run = run_fixture()
        run["model_calls"] = [request([{"tool": "sample"}, {"tool": "collect"}], [{"ok": True}, {"ok": True}])]
        report = summarize_run(run)
        self.assertEqual((report["api_requests"], report["decoded_actions"], report["tool_successes"]), (1, 2, 2))

    def test_protocol_failure_and_precondition_failure_are_separate(self):
        run = run_fixture()
        invalid = request([], [])
        invalid["submission_error"] = "wrong argument type"
        run["model_calls"] = [invalid, request([{"tool": "confirm"}], [{"ok": False, "executed": False,
                              "public_precondition_rejected": True, "error": "pending capacity"}])]
        report = summarize_run(run)
        self.assertEqual(report["protocol_error_requests"], 1)
        self.assertEqual(report["public_precondition_rejections"], 1)
        self.assertEqual([error["category"] for error in report["error_details"]], ["submission_protocol", "public_precondition"])

    def test_scientific_refutation_is_not_a_tool_failure_or_model_completion(self):
        run = run_fixture()
        run["research"]["checks"] = [{"result": {"state": "contradicted"}}]
        run["model_calls"] = [request([{"tool": "assess_checks"}], [{"ok": True}])]
        run["terminal_fallback"] = {"ok": True}
        report = summarize_run(run)
        self.assertEqual(report["tool_failures"], 0)
        self.assertEqual(report["archived_check_outcomes"], {"contradicted": 1})
        self.assertFalse(report["model_requested_successful_finish"])
        self.assertTrue(report["runner_terminal_fallback"])

    def test_created_roles_do_not_count_as_queried_roles_and_hidden_score_is_absent(self):
        run = run_fixture()
        run["model_calls"] = [request([{"tool": "sample"}], [{"ok": True}])]
        original = copy.deepcopy(run)
        report = summarize_run(run)
        self.assertEqual(report["queried_contexts"], {"supervisor": 1})
        self.assertNotIn("DO_NOT_EXPORT", json.dumps(report))
        self.assertEqual(run, original)

    def test_missing_planned_runs_remain_in_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            tasks = [{"strategy": "B", "family": "one", "profile": "p", "seed": seed} for seed in (1, 2)]
            (folder / "manifest.json").write_text(json.dumps({"planned_tasks": tasks}))
            (folder / "B_one_p_s1.json").write_text(json.dumps(run_fixture()))
            report = analyze(folder)
        self.assertEqual((report["planned_runs"], report["available_runs"], report["missing_runs"]), (2, 1, 1))
        self.assertFalse(report["records"][1]["available"])

    def test_empty_analysis_is_a_signal_and_mismatched_feedback_is_flagged(self):
        run = run_fixture()
        record = request([{"tool": "assess_checks"}, {"tool": "collect"}], [{"ok": True}])
        record["public_precondition_reviews"] = [{"accepted": True, "action": {"tool": "assess_checks"}, "state": {"checks": []}}]
        run["model_calls"] = [record]
        report = summarize_run(run)
        self.assertEqual(report["accepted_assessments_without_unassessed_checks"], 1)
        self.assertEqual(report["tool_failures"], 0)
        self.assertFalse(report["feedback_action_count_matches"])


if __name__ == "__main__":
    unittest.main()
