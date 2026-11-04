import copy
import json
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from public_context import unpack
from research_actor import ScienceActor
from research_runtime import ResearchRuntime
from run_scientific import API_LIMITS, SCHEMA, agent_view
from state_brief import state_brief, VERSION
from temporal_lab import TemporalLab
from test_native_science_protocol import raw


def base_state():
    return agent_view(ResearchRuntime(TemporalLab(ChoiceWorld(99, "threeway"))))


def public_cases():
    """Synthetic public-state contract fixtures, not new business-world tasks."""
    base = base_state()
    trained = copy.deepcopy(base)
    trained["training_evidence_ids"] = [0]
    trained["verified_condition_table"] = [{"experiment_id": 0, "n": 400}]
    # The initial prior is a separate public ID; the fitted committee is empty
    # before data. Do not assume a fitted candidate exists in the initial view.
    trained["candidates"] = [{"candidate_id": "C0001", "origin": "numeric_pool",
        "training_evidence_ids": [0], "information_evidence_ids": [],
        "expression": .3, "terms": [], "rank": 0, "bic": 0., "deviance": 0.}]
    trained["candidate_count"] = 2
    cases = [("no_data", base)]
    for name, key, status in (("pending", "pending_jobs", "pending"),
                              ("unverified", "unverified_jobs", "measurement_unverified"),
                              ("execution_failure", "failed_jobs", "execution_failed")):
        state = copy.deepcopy(base)
        state[key] = [{"job_id": 0, "status": status, "attempts": 1, "expected_report_at": 2,
                       "action": {"stage": "source", "site": "00", "assortment": [], "n": 400}}]
        cases.append((name, state))
    cases.append(("fitted_unconfirmed", trained))
    checking = copy.deepcopy(trained)
    checking["checks"] = [{"check_id": "K000", "candidate_id": "C0001", "state": None,
                           "released": False, "job_ids": [1, 2]}]
    cases.append(("confirmation_pending", checking))
    refuted = copy.deepcopy(checking)
    refuted["checks"][0]["state"] = "contradicted"
    refuted["public_evidence_store"]["analysis_cards"] = [{"analysis_id": "A000"}]
    cases.append(("actual_refutation", refuted))
    terminal = copy.deepcopy(trained)
    terminal["clock"] = terminal["limits"]["logical_time"]
    cases.append(("deadline", terminal))
    return cases


class StateBriefTests(unittest.TestCase):
    def kinds(self, state):
        return {item["kind"] for item in state_brief(state)["work_items"]}

    def test_eight_public_states_preserve_distinct_execution_and_science_cues(self):
        expected = {"no_data": "no_released_target_training", "pending": "receipts_pending",
                    "unverified": "measurement_unverified", "execution_failure": "execution_failed",
                    "fitted_unconfirmed": "fitted_candidates_without_registered_checks",
                    "confirmation_pending": "registered_check_unresolved",
                    "actual_refutation": "actual_refutation_available", "deadline": "terminal_pressure"}
        for name, state in public_cases():
            with self.subTest(name=name):
                self.assertIn(expected[name], self.kinds(state))

    def test_unverified_or_pending_counts_never_become_training_or_refutations(self):
        for name, state in public_cases()[1:4]:
            state["private_score"] = {"answer": "DO_NOT_EXPOSE"}
            state["future_sales"] = "DO_NOT_EXPOSE"
            state["unverified_jobs"] = state["unverified_jobs"] + [{"job_id": 90, "status": "measurement_unverified", "unverified_observed_sales": 900}]
            original = copy.deepcopy(state)
            brief = state_brief(state)
            self.assertEqual(brief["verified_training_sessions"], 0)
            self.assertNotIn("actual_refutation_available", self.kinds(state))
            self.assertNotIn("DO_NOT_EXPOSE", json.dumps(brief))
            self.assertNotIn("unverified_observed_sales", json.dumps(brief))
            self.assertEqual(state, original)

    def test_released_refutation_is_retained_but_not_available_for_reopen(self):
        state = dict(public_cases())["actual_refutation"]
        state["checks"][0]["released"] = True
        brief = state_brief(state)
        self.assertEqual(brief["registered_condition_outcomes"][0]["state"], "contradicted")
        self.assertNotIn("actual_refutation_available", self.kinds(state))
        self.assertEqual(brief["reference_domains"]["refutation_check_ids"], [])

    def test_waiting_can_coexist_with_hypothesis_development_without_order_mask(self):
        state = dict(public_cases())["fitted_unconfirmed"]
        state["pending_jobs"] = dict(public_cases())["pending"]["pending_jobs"]
        brief = state_brief(state)
        self.assertIn("receipts_pending", self.kinds(state))
        self.assertIn("target_training_available", self.kinds(state))
        self.assertIn("propose_model", brief["available_services"])
        self.assertIn("collect", brief["available_services"])

    def test_exhausted_budget_never_suggests_new_measurement_and_preserves_scoped_exit(self):
        state = dict(public_cases())["fitted_unconfirmed"]
        state["scientific_actions_used"] = state["scientific_actions_limit"] - 1
        brief = state_brief(state)
        self.assertEqual(brief["available_services"], ["finish"])
        self.assertIn("terminal_pressure", self.kinds(state))
        self.assertEqual(brief["reference_domains"]["available_analysis_ids"], [])

    def test_exhausted_retry_is_not_suggested_when_another_job_can_be_repaired(self):
        state = dict(public_cases())["execution_failure"]
        exhausted = copy.deepcopy(state["failed_jobs"][0])
        exhausted.update(job_id=1, attempts=2)
        state["failed_jobs"].append(exhausted)
        items = [item for item in state_brief(state)["work_items"] if item["kind"] == "execution_failed"]
        self.assertIn("repair", items[0]["available_tools"])
        self.assertNotIn("repair", items[1]["available_tools"])

    def test_real_public_actor_receives_brief_and_feature_is_explicitly_opt_in(self):
        runtime = ResearchRuntime(TemporalLab(ChoiceWorld(99, "threeway")))
        with self.assertRaises(ValueError):
            ScienceActor(runtime, agent_view, SCHEMA, API_LIMITS, use_state_brief=True)
        actor = ScienceActor(runtime, agent_view, SCHEMA, API_LIMITS, "native", True, True)
        response = raw("diagnose_history", {"rationale": "核查记录。", "expected_gap": "辨别观测问题。"})
        with patch("research_actor.request_model", side_effect=lambda _, payload: {"request": copy.deepcopy(payload), "cache_hit": False, "response": response}):
            record = actor.next([])
        state = unpack(json.loads(record["request"]["messages"][-1]["content"]))["research_state"]
        self.assertEqual(state["workflow_brief"]["version"], VERSION)
        self.assertEqual(record["state_brief_version"], VERSION)
        self.assertTrue(record["tool_feedbacks"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
