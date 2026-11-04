import copy
import unittest

from choice_world import ChoiceWorld
from public_inference_replay import extract
from research_runtime import ResearchRuntime
from temporal_lab import TemporalLab


class PublicInferenceReplayTests(unittest.TestCase):
    def prepared(self):
        rt = ResearchRuntime(TemporalLab(ChoiceWorld(5401, "mixed_scope"), "interruptions"), terminal_policy="settle_committed")
        response = rt.call("sample_and_analyze", {"candidate_id": rt.initial_candidate,
            "designs": [{"stage": "source", "site": "00", "assortment": [], "n": 400}],
            "rationale": "核实训练。", "repair": True})
        self.assertTrue(response["ok"])
        cid = rt.pool[0]
        rt.call("confirm_and_analyze", {"candidate_id": cid, "rationale": "原冻结检查。", "repair": True})
        return rt, cid

    def run_dict(self, rt):
        return {"research": rt.snapshot(), "gateway_events": copy.deepcopy(rt.gateway.events), "legal_input": rt.initial}

    def finish(self, rt, cid):
        self.assertTrue(rt.call("finish", {"candidate_id": cid, "claims": "旧检查与未测范围分开。",
            "unresolved": True, "stop_reason": "诊断夹具。"})["ok"])

    def test_original_fit_and_unreleased_checks_remain_separate_even_after_later_discovery(self):
        rt, cid = self.prepared()
        rt.call("sample_and_analyze", {"candidate_id": cid,
            "designs": [{"stage": "source", "site": "00", "assortment": [], "n": 400}],
            "rationale": "后续发现。", "repair": True})
        self.finish(rt, cid);run = self.run_dict(rt)
        original = copy.deepcopy(run)
        a = extract(run, "selected_fit");b = extract(run, "close_released")
        self.assertEqual(a["training_ids"], [0])
        self.assertEqual(b["training_ids"], [0, 3])
        self.assertFalse({1, 2} & set(b["training_ids"]))
        self.assertEqual(run, original)

    def test_actual_released_refutation_can_enter_close_view_but_not_original_fit(self):
        rt, cid = self.prepared()
        bad = rt.call("propose_model", {"expression": "sigmoid(b)", "parameters": {"b": [3., 2.9, 3.1]}, "rationale": "反驳夹具。"})["result"]["candidate_id"]
        rt.call("confirm_and_analyze", {"candidate_id": bad, "rationale": "新检查。", "repair": True})
        self.assertEqual(rt.checks[-1]["result"]["state"], "contradicted")
        release = rt.call("reopen_research", {"check_id": rt.checks[-1]["check_id"], "rationale": "实际释放。", "refit": False})
        self.assertTrue(release["ok"])
        # The declared runtime releases all completed checks after an actual
        # refutation, including the earlier check; it does not release only
        # the trigger's two cohorts.
        self.assertEqual(release["result"]["training_evidence_ids"], [0, 1, 2, 3, 4])
        self.finish(rt, cid);run = self.run_dict(rt)
        self.assertEqual(extract(run, "selected_fit")["training_ids"], [0])
        self.assertEqual(extract(run, "close_released")["training_ids"], [0, 1, 2, 3, 4])

    def test_catalogue_uses_public_response_order_not_equal_clocks(self):
        rt, cid = self.prepared();self.finish(rt, cid);run = self.run_dict(rt)
        run["research"]["events"].append({"sequence": len(run["research"]["events"]),
            "kind": "scientific_tool_response", "available_at": 0,
            "payload": {"request": {"tool": "open_adaptation"},
                "feedback": {"ok": True, "result": {"catalog": [{"id": "future"}]}}}})
        self.assertNotIn("adaptation", extract(run, "selected_fit")["view"].catalogs)
        self.assertNotIn("adaptation", extract(run, "close_released")["view"].catalogs)

    def test_post_close_receipt_is_not_retroactively_available(self):
        rt, cid = self.prepared()
        rt.call("sample", {"candidate_id": cid, "designs": [{"stage": "source", "site": "00", "assortment": [], "n": 400}], "rationale": "关闭前承诺，回执稍后。"})
        self.finish(rt, cid);run = self.run_dict(rt)
        self.assertIn(3, run["research"]["training_evidence_ids"])
        self.assertNotIn(3, extract(run, "close_released")["training_ids"])

    def test_private_scores_and_future_snapshots_are_not_inputs_to_fitting_view(self):
        rt, cid = self.prepared();self.finish(rt, cid);run = self.run_dict(rt)
        run["private_score"] = {"answer": "DO_NOT_USE"}
        run["public_final_state"] = {"mature_evidence": [{"experiment_id": 99, "observed_sales": 999}]}
        result = extract(run, "selected_fit")
        self.assertEqual(result["training_ids"], [0])
        self.assertNotIn(99, [row["experiment_id"] for row, _ in result["view"].verified_observations()])


if __name__ == "__main__":unittest.main()
