import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_recovery import audit_queue
from audit_scientific import audit
import run_recovery
from temporal_lab import digest


class RecoveryAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = json.loads((run_recovery.ROOT.parents[1] / "configs/development_recovery_v01.json").read_text())
        spec["phase"] = "unit_only"
        score = {"profiles": [], "heldout_effect_rmse": 0., "mean_expected_operating_regret_per_customer": 0.}
        with tempfile.TemporaryDirectory(dir=run_recovery.ROOT) as directory:
            root = Path(directory); (root / "results" / spec["phase"]).mkdir(parents=True)
            with patch.object(run_recovery, "ROOT", root), patch.object(run_recovery, "evaluate", return_value=score), contextlib.redirect_stdout(io.StringIO()):
                cls.fixture = run_recovery.run(dict(seed=4201, family="threeway", profile="interruptions", strategy="frozen_reference"), spec)

    def test_actual_public_fixture_and_worker_trace_pass_independent_audits(self):
        self.assertTrue(audit(self.fixture)["passed"], audit(self.fixture))
        self.assertTrue(audit_queue(self.fixture)["passed"], audit_queue(self.fixture))

    def test_rehashed_false_alpha_and_analysis_are_caught(self):
        for kind in ("alpha", "analysis", "trace", "new_decision"):
            mutant = copy.deepcopy(self.fixture)
            wake = next(e for e in mutant["research_queue"]["events"] if e["kind"] == "context_woken")
            if kind == "alpha":
                wake["payload"]["remaining_after"]["checks"] = 6
                wake["payload"]["remaining_after"]["unspent_declared_alpha"] = .05
            elif kind == "analysis":
                wake["payload"]["checks"][0]["state"] = "supported_within_tolerance"
            elif kind == "trace":
                wake["payload"]["receipt"]["trace"] = []
            else:
                event = next(e for e in mutant["research"]["events"] if e["kind"] == "independent_check_assessed")
                event["kind"] = "confirmation_evidence_released"
            previous = None
            for event in mutant["research_queue"]["events"]:
                event["previous_hash"] = previous
                event["event_hash"] = digest({k: v for k, v in event.items() if k != "event_hash"})
                previous = event["event_hash"]
            result = audit_queue(mutant)
            self.assertFalse(result["passed"], kind)
            expected = {"alpha": "queue_remaining_original_ledger", "analysis": "queue_actual_frozen_analysis",
                        "trace": "queue_worker_actual_gateway_trace", "new_decision": "queue_worker_no_decision_events"}
            self.assertIn(expected[kind], result["issues"], kind)
