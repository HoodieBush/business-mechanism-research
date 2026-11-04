import copy
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from research_queue import ResearchQueue
from research_runtime import ResearchRuntime
from temporal_lab import TemporalLab


class ResearchQueueTests(unittest.TestCase):
    def runtime(self, deadline=120):
        return ResearchRuntime(TemporalLab(ChoiceWorld(4101, "threeway", retail_price=10.), "interruptions", deadline))

    def check(self, rt):
        f = rt.call("confirm", {"candidate_id": rt.initial_candidate,
                    "design": {"stage": "source", "site": "00", "assortment": []}, "rationale": "新独立条件。"})
        self.assertTrue(f["ok"])

    def test_waiting_worker_wakes_refutation_without_fitting_or_releasing(self):
        rt = self.runtime(); self.check(rt); q = ResearchQueue(); q.register("original", rt)
        fixed = copy.deepcopy(rt.registry); training = rt.training_ids.copy(); limits = copy.deepcopy(rt.gateway.limits)
        self.assertIsNone(q.pop_ready()); self.assertIsNone(rt.checks[0]["result"])
        with patch.object(rt, "_fit", side_effect=AssertionError("worker cannot fit")):
            wake = q.advance("original")
        self.assertEqual(wake["checks"][0]["state"], "contradicted")
        self.assertEqual(rt.registry, fixed); self.assertEqual(rt.training_ids, training)
        self.assertFalse(rt.checks[0]["released"]); self.assertEqual(rt.revisions, 0)
        self.assertEqual(rt.gateway.limits, limits); self.assertEqual(rt.calls, 2)
        self.assertEqual(q.pop_ready(), "original"); self.assertIsNone(q.pop_ready())
        before = q.remaining("original")
        f = rt.call("reopen_research", {"check_id": "K000", "rationale": "收到实际反驳后继续。", "refit": False})
        self.assertTrue(f["ok"]); self.assertEqual(rt.revisions, 1)
        self.assertEqual(q.remaining("original")["checks"], before["checks"])
        self.assertEqual(q.remaining("original")["unspent_declared_alpha"], before["unspent_declared_alpha"])
        self.assertEqual(q.remaining("original")["scientific_actions"], before["scientific_actions"] - 1)

    def test_fifo_and_contexts_share_the_same_original_ledger(self):
        rt = self.runtime(); q = ResearchQueue(); q.register("a", rt); q.register("b", rt)
        self.assertEqual(q.pop_ready(), "a")
        rt.call("diagnose_history", {})
        self.assertEqual(q.remaining("a"), q.remaining("b"))
        q.after_decision("a")
        self.assertEqual(q.pop_ready(), "b"); self.assertIsNone(q.pop_ready())
        q.after_decision("b"); self.assertEqual(q.pop_ready(), "a")
        with self.assertRaises(ValueError): q.register("a", self.runtime())

    def test_shared_waiters_do_not_double_charge_received_jobs(self):
        rt = self.runtime(); self.check(rt); q = ResearchQueue()
        q.register("a", rt); q.register("b", rt)
        q.advance("a"); used = copy.deepcopy(rt.gateway.used); calls = rt.calls
        self.assertIsNone(q.pop_ready())
        wake = q.advance("b")
        self.assertEqual(wake["receipt"]["reason"], "committed_jobs_already_received")
        self.assertEqual(rt.calls, calls); self.assertEqual(rt.gateway.used, used)
        self.assertEqual(q.pop_ready(), "a")

    def test_deadline_and_reserves_wake_unresolved_without_reset(self):
        rt = self.runtime(deadline=1); self.check(rt); q = ResearchQueue(); q.register("short", rt)
        wake = q.advance("short")
        self.assertEqual(wake["receipt"]["reason"], "calendar_deadline")
        self.assertIsNone(rt.checks[0]["result"]); self.assertLessEqual(rt.gateway.clock, 1)
        self.assertEqual(q.pop_ready(), "short")
        other = self.runtime(); self.check(other); q.register("reserve", other)
        other.max_calls = other.calls + 1
        used = copy.deepcopy(other.gateway.used)
        wake = q.advance("reserve")
        self.assertEqual(wake["receipt"]["reason"], "scientific_reserve_for_finish")
        self.assertEqual(other.gateway.used, used); self.assertIsNone(other.checks[0]["result"])
        self.assertEqual(q.remaining("reserve")["scientific_actions"], 1)

    def test_closed_context_never_reopens_and_waiting_cannot_add_jobs(self):
        rt = self.runtime(); self.check(rt); q = ResearchQueue(); q.register("stale", rt)
        rt.call("finish", {"candidate_id": rt.initial_candidate, "claims": "未决停止。", "unresolved": True, "stop_reason": "停止。"})
        self.assertIsNone(q.advance("stale")); self.assertIsNone(q.pop_ready())
        with self.assertRaises(ValueError): q.register("revive", rt)
        other = self.runtime(); q.register("other", other); q.pop_ready(); self.check(other); q.after_decision("other")
        other.call("sample", {"candidate_id": other.initial_candidate, "designs": [
            {"stage": "source", "site": "00", "assortment": [], "n": 100}], "rationale": "非法并行外部修改。"})
        with self.assertRaises(ValueError): q.advance("other")
