"""Append-only public scientific analyses, including failures and dependencies.

Only already available research events are consumed. No gateway, world, fitting
routine, score, or private configuration is read by this store.
"""
import copy

from confirmation import assess
from temporal_lab import digest

VERSION = "public-evidence-v0.1-versioned-conditional-analyses"


class PublicEvidenceStore:
    def __init__(self):
        self.records = []
        self.candidates = {}
        self.plans = {}
        self.checks = {}
        self.measurements = {}
        self.latest = {}
        self.diagnostics = []
        self.event_count = 0
        self.event_prefix_hash = None

    def _append(self, card, event):
        old = self.latest.get(card["analysis_id"])
        value = copy.deepcopy(card)
        value.update(version=0 if old is None else old["version"] + 1,
                     parent_record_sha256=None if old is None else old["record_sha256"],
                     source_event_sequence=event["sequence"], source_event_sha256=event["event_hash"],
                     available_at=event["available_at"])
        value["record_sha256"] = digest(value)
        self.records.append(value); self.latest[value["analysis_id"]] = value

    def observe(self, event):
        if event["sequence"] != self.event_count or event["previous_hash"] != self.event_prefix_hash:
            raise ValueError("evidence store requires the next original public event")
        self.event_count += 1; self.event_prefix_hash = event["event_hash"]
        p = event["payload"]; kind = event["kind"]
        if kind == "candidate_registered":
            self.candidates[p["candidate_id"]] = {"model_sha256": digest(p["model"]),
                "training_evidence_ids": copy.deepcopy(p["training_evidence_ids"]),
                "information_evidence_ids": copy.deepcopy(p.get("information_evidence_ids", [])),
                "available_at": p["available_at"]}
        elif kind == "registered_plan_linked":
            self.plans[p["job_id"]] = copy.deepcopy(p)
        elif kind == "check_frozen_before_execution":
            self.checks[p["check_id"]] = copy.deepcopy(p)
        elif kind == "evidence_received":
            measurement = p["measurement"]
            self.measurements[measurement["experiment_id"]] = copy.deepcopy(measurement)
        elif kind == "independent_check_assessed":
            result = p["result"]; candidate = self.candidates[p["candidate_id"]]
            rows = result["cohort_results"]
            if any(not r["verified_supply"] or not r["verified_meter"] or r["available_at"] > event["available_at"] for r in rows):
                raise ValueError("cannot archive unavailable or unverified scientific analysis")
            if len(rows) != 2 or len({r["independence_group"] for r in rows}) != 2 or any(r != self.measurements.get(r["experiment_id"]) for r in rows):
                raise ValueError("analysis must use two original latest public cohort receipts")
            exact = assess(sum(r["observed_sales"] for r in rows), sum(r["n"] for r in rows), result["frozen_prediction"], max_checks=6)
            if any(result[k] != v for k, v in exact.items()) or result["n"] != 1600:
                raise ValueError("analysis must match the declared exact calculation")
            if candidate["available_at"] > p["registered_at"] or any(
                digest(self.plans[j]["plan"]["model"]) != candidate["model_sha256"] or
                self.plans[j]["plan"]["action"]["prediction"] != result["frozen_prediction"] for j in p["job_ids"]):
                raise ValueError("analysis differs from the registered candidate or prediction")
            evidence_ids = copy.deepcopy(result["experiment_ids"])
            dependencies = set(candidate["training_evidence_ids"]) | set(candidate["information_evidence_ids"])
            value = {"analysis_id": f"A{p['check_index']:03d}", "check_id": p["check_id"], "candidate_id": p["candidate_id"],
                "frozen_model_sha256": candidate["model_sha256"], "registered_at": p["registered_at"],
                "analyzed_at": result["available_at"],
                "condition": {k: copy.deepcopy(result["design"][k]) for k in ("stage", "site", "assortment")},
                "count": result["count"], "n": result["n"], "frozen_prediction": result["frozen_prediction"],
                "exact_probability_interval": copy.deepcopy(result["exact_probability_interval"]),
                "prediction_tolerance_band": copy.deepcopy(result["prediction_tolerance_band"]),
                "state": result["state"],
                "analysis_contract": {k: result[k] for k in ("total_alpha", "max_checks", "per_check_alpha")},
                "experiment_ids": evidence_ids, "independence_groups": [r["independence_group"] for r in rows],
                "evidence_versions": [r["evidence_version"] for r in rows],
                "plan_ids": [self.plans[j]["plan_id"] for j in p["job_ids"]],
                "training_evidence_ids": copy.deepcopy(candidate["training_evidence_ids"]),
                "information_evidence_ids": copy.deepcopy(candidate["information_evidence_ids"]),
                "independent_of_registered_model": not bool(dependencies & set(evidence_ids)),
                "released_to_training": p["released"],
                "scope": "Only the original frozen model and listed condition; untested conditions and unique mechanism remain unresolved."}
            if not value["independent_of_registered_model"]:
                raise ValueError("confirmation has an information/training dependency on its own outcome")
            self._append(value, event)
        elif kind == "confirmation_evidence_released":
            released = set(p["training_evidence_ids"])
            for old in list(self.latest.values()):
                if not old["released_to_training"] and set(old["experiment_ids"]) <= released:
                    card = {k: copy.deepcopy(v) for k, v in old.items() if k not in
                        {"version", "parent_record_sha256", "source_event_sequence", "source_event_sha256", "available_at", "record_sha256"}}
                    card["released_to_training"] = True
                    self._append(card, event)
        elif kind == "scientific_tool_response" and p["request"]["tool"] == "diagnose_history" and p["feedback"]["ok"]:
            result = p["feedback"]["result"]
            self.diagnostics.append({"source_event_sequence": event["sequence"], "source_event_sha256": event["event_hash"],
                "available_at": event["available_at"], "observed_issue": result["observed_issue"],
                "supply_receipt": copy.deepcopy(result["supply_receipt"]), "meter_receipt": copy.deepcopy(result["meter_receipt"]),
                "scope": "Historical audit only; not randomized demand evidence or a mechanism check."})

    def view(self):
        # The bounded task has at most six analyses. None are dropped by state,
        # fit rank, positive/negative outcome, or release into later training.
        return {"version": VERSION, "analysis_cards": copy.deepcopy(list(self.latest.values())),
                "last_history_diagnosis": None if not self.diagnostics else copy.deepcopy(self.diagnostics[-1]),
                "public_event_count": self.event_count, "public_event_prefix_hash": self.event_prefix_hash,
                "rule": "Original analyses never change state on refit/release. Released checks cannot certify their own revised models; retrospective candidate replay is diagnostic only."}

    def snapshot(self):
        return {**self.view(), "records": copy.deepcopy(self.records), "history_diagnostics": copy.deepcopy(self.diagnostics)}

    @classmethod
    def from_events(cls, events):
        store = cls(); previous = None
        for event in events:
            body = {k: v for k, v in event.items() if k != "event_hash"}
            if event["previous_hash"] != previous or event["event_hash"] != digest(body):
                raise ValueError("invalid original research event hash chain")
            store.observe(event); previous = event["event_hash"]
        return store


def retrospective_review(candidate_id, candidate, store, catalogs, prediction):
    """Public model checking on observed conditions, never certification."""
    rows = []
    dependencies = set(candidate["training_evidence_ids"]) | set(candidate.get("information_evidence_ids", []))
    for analysis in store.latest.values():
        c = analysis["condition"]
        p = prediction(candidate["model"], catalogs[c["stage"]], c["assortment"], tuple(map(int, c["site"])))
        lower, upper = analysis["exact_probability_interval"]
        gap = max(lower - p, p - upper, 0.)
        rows.append({"analysis_id": analysis["analysis_id"], "analysis_record_sha256": analysis["record_sha256"],
            "condition": copy.deepcopy(c), "observed_rate": analysis["count"] / analysis["n"],
            "candidate_prediction": p, "distance_to_observed_interval": gap,
            "outside_5pp_expanded_observed_interval": gap > .05,
            "overlapping_training_or_information_ids": sorted(dependencies & set(analysis["experiment_ids"])),
            "candidate_available_before_check": candidate["available_at"] <= analysis["registered_at"],
            "original_check_state": analysis["state"], "original_checked_candidate_id": analysis["candidate_id"],
            "certification_role": "retrospective_diagnostic_only"})
    return {"candidate_id": candidate_id, "candidate_content_sha256": candidate["content_hash"], "analyses": rows,
            "interpretation": "Public descriptive replay, not independent confirmation, calibrated posterior, or a new multiple-testing allocation. A revised explanation needs a newly registered independent check."}
