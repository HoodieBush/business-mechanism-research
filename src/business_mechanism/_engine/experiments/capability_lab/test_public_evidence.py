import copy
import unittest

from choice_world import ChoiceWorld
from confirmation import assess
from public_context import assert_roundtrip
from public_evidence import PublicEvidenceStore
from research_runtime import ResearchRuntime
from run_scientific import agent_view
from temporal_lab import TemporalLab, digest


class PublicEvidenceTests(unittest.TestCase):
    def runtime(self, profile="staggered"):
        return ResearchRuntime(TemporalLab(ChoiceWorld(4301, "threeway", retail_price=10.), profile))

    def confirm(self, rt):
        response = rt.call("confirm", {"candidate_id": rt.initial_candidate,
                    "design": {"stage": "source", "site": "00", "assortment": []}, "rationale": "预声明独立检查。"})
        self.assertTrue(response["ok"])

    def collect(self, rt, repair=True):
        response = rt.call("collect", {"until": "all", "repair": repair, "refit": False, "assess": True})
        self.assertTrue(response["ok"])

    def test_full_negative_card_keeps_original_state_after_release(self):
        rt = self.runtime(); self.confirm(rt)
        self.assertEqual(rt.public_evidence.view()["analysis_cards"], [])
        self.collect(rt); original = copy.deepcopy(rt.public_evidence.records[0])
        self.assertEqual(original["state"], "contradicted")
        self.assertEqual(original["experiment_ids"], rt.checks[0]["result"]["experiment_ids"])
        self.assertEqual(original["condition"], {"stage": "source", "site": "00", "assortment": []})
        self.assertEqual(original["analysis_contract"]["per_check_alpha"], .05 / 6)
        self.assertTrue(rt.call("reopen_research", {"check_id": "K000", "rationale": "实际反驳后修订。", "refit": False})["ok"])
        latest = rt.public_evidence.view()["analysis_cards"][0]
        self.assertEqual(latest["version"], 1); self.assertTrue(latest["released_to_training"])
        self.assertEqual(latest["state"], original["state"])
        self.assertEqual(rt.public_evidence.records[0], original)
        self.assertEqual(latest["parent_record_sha256"], original["record_sha256"])
        self.assertEqual(PublicEvidenceStore.from_events(rt.events).snapshot(), rt.public_evidence.snapshot())

    def test_revised_candidate_replay_does_not_certify_or_allocate_new_checks(self):
        rt = self.runtime(); self.confirm(rt); self.collect(rt)
        rt.call("reopen_research", {"check_id": "K000", "rationale": "实际反驳后释放。", "refit": False})
        proposal = rt.call("propose_model", {"expression": "sigmoid(b)", "parameters": {"b": [-1., -6, 6]}, "rationale": "旧结果重新估参，须新确认。"})
        self.assertTrue(proposal["ok"]); cid = proposal["result"]["candidate_id"]
        before = copy.deepcopy(rt.checks); revisions = rt.revisions; used = copy.deepcopy(rt.gateway.used)
        response = rt.call("review_candidate_evidence", {"candidate_id": cid})
        self.assertTrue(response["ok"]); row = response["result"]["analyses"][0]
        self.assertEqual(row["certification_role"], "retrospective_diagnostic_only")
        self.assertTrue(row["overlapping_training_or_information_ids"])
        self.assertFalse(row["candidate_available_before_check"])
        self.assertEqual(rt.checks, before); self.assertEqual(rt.revisions, revisions); self.assertEqual(rt.gateway.used, used)
        self.assertEqual(rt.public_evidence.view()["analysis_cards"][0]["state"], "contradicted")

    def test_unverified_receipt_is_not_an_analysis_until_meter_repair(self):
        rt = self.runtime("interruptions")
        rt.call("sample_frontier", {"candidate_id": rt.initial_candidate, "count": 3, "rationale": "公开暖场。"})
        self.collect(rt); self.confirm(rt); self.collect(rt, repair=False)
        self.assertTrue(rt.gateway.public_state()["unverified_jobs"])
        self.assertEqual(rt.public_evidence.view()["analysis_cards"], [])
        self.collect(rt, repair=True)
        self.assertEqual(len(rt.public_evidence.view()["analysis_cards"]), 1)
        self.assertIn(2, rt.public_evidence.view()["analysis_cards"][0]["evidence_versions"])

    def test_public_state_roundtrip_and_replay_reject_tampered_event(self):
        rt = self.runtime(); self.confirm(rt); self.collect(rt)
        view = agent_view(rt); assert_roundtrip(view)
        self.assertEqual(view["public_evidence_store"]["analysis_cards"][0]["n"], 1600)
        changed = copy.deepcopy(rt.events)
        event = next(e for e in changed if e["kind"] == "independent_check_assessed")
        event["payload"]["result"]["state"] = "supported_within_tolerance"
        with self.assertRaises(ValueError): PublicEvidenceStore.from_events(changed)

    def test_synthetic_inconclusive_analysis_remains_inconclusive(self):
        # Explicit synthetic public-unit fixture, not a sampled research record.
        rt = self.runtime(); self.confirm(rt); self.collect(rt)
        events = copy.deepcopy(rt.events); previous = None
        for event in events:
            if event["kind"] == "evidence_received":
                r = event["payload"]["measurement"]
                r["observed_sales"] = 200 if r["experiment_id"] == 0 else 185
            if event["kind"] == "independent_check_assessed":
                event["payload"]["result"].update(assess(385, 1600, .3, max_checks=6))
                for row in event["payload"]["result"]["cohort_results"]:
                    row["observed_sales"] = 200 if row["experiment_id"] == 0 else 185
            event["previous_hash"] = previous
            event["event_hash"] = digest({k: v for k, v in event.items() if k != "event_hash"})
            previous = event["event_hash"]
        store = PublicEvidenceStore.from_events(events)
        self.assertEqual(store.view()["analysis_cards"][0]["state"], "inconclusive")

    def test_rehashed_false_analysis_is_rejected_by_public_receipts(self):
        rt = self.runtime(); self.confirm(rt); self.collect(rt)
        for mutation in ("state", "count", "independence"):
            events = copy.deepcopy(rt.events); previous = None
            for event in events:
                if event["kind"] == "independent_check_assessed":
                    result = event["payload"]["result"]
                    if mutation == "state": result["state"] = "supported_within_tolerance"
                    if mutation == "count": result["count"] += 1
                    if mutation == "independence": result["cohort_results"][1] = copy.deepcopy(result["cohort_results"][0])
                event["previous_hash"] = previous
                event["event_hash"] = digest({k: v for k, v in event.items() if k != "event_hash"})
                previous = event["event_hash"]
            with self.assertRaises(ValueError, msg=mutation): PublicEvidenceStore.from_events(events)
