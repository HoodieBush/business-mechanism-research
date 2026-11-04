"""Public, in-process pause/receive/wake scheduling on the original ledger.

The worker collects registered jobs and assesses frozen checks. It never fits,
releases confirmation evidence, chooses a candidate, or calls a model.
"""
import copy
import time
from collections import deque

from temporal_lab import digest
from terminal_receipts import settle

VERSION = "research-queue-v0.1-original-ledger-wakeup"
CONTRACT = {
    "version": VERSION,
    "scheduling": "FIFO runnable contexts; wait for all currently committed jobs",
    "receipt_scientific_action_charge": 1,
    "receipt_max_steps": 100,
    "gateway_reserve": 2,
    "scientific_action_reserve": 1,
    "worker_actions": ["retry_execution", "reconcile_measurement", "await_next"],
    "worker_api_calls": 0,
    "worker_parameter_refits": 0,
    "worker_new_plans": 0,
    "worker_confirmation_release": False,
    "budget_reset_on_wakeup": False,
    "persistence": "in_process_only",
}


class ResearchQueue:
    def __init__(self):
        self.contexts = {}
        self.ready = deque()
        self.events = []

    def _event(self, context_id, kind, payload):
        rt = self.contexts[context_id]["runtime"]
        body = {"sequence": len(self.events), "context_id": context_id,
                "kind": kind, "available_at": rt.gateway.clock,
                "research_event_count": len(rt.events),
                "research_prefix_hash": rt.events[-1]["event_hash"],
                "gateway_event_count": len(rt.gateway.events),
                "gateway_prefix_sha256": digest(rt.gateway.events),
                "payload": copy.deepcopy(payload),
                "previous_hash": self.events[-1]["event_hash"] if self.events else None}
        self.events.append(body | {"event_hash": digest(body)})

    @staticmethod
    def _unreceived(rt):
        state = rt.gateway.public_state()
        return sorted({j["job_id"] for k in ("pending_jobs", "failed_jobs", "unverified_jobs") for j in state[k]})

    def register(self, context_id, rt):
        if not isinstance(context_id, str) or not context_id or context_id in self.contexts:
            raise ValueError("unique nonempty context identity required")
        if rt.closed or rt.decisions_closed:
            raise ValueError("cannot revive a closed research decision context")
        self.contexts[context_id] = {"runtime": rt, "status": "running",
                                     "wake_count": 0, "waiting_job_ids": [], "last_wakeup": None}
        self._event(context_id, "context_registered", {"contract_sha256": digest(CONTRACT),
                    "remaining": self.remaining(context_id)})
        self.after_decision(context_id)

    def remaining(self, context_id):
        rt = self.contexts[context_id]["runtime"]
        return {"physical": {k: rt.gateway.limits[k] - rt.gateway.used[k] for k in rt.gateway.used},
                "scientific_actions": rt.max_calls - rt.calls,
                "checks": 6 - len(rt.checks), "revisions": 2 - rt.revisions,
                "unspent_declared_alpha": (6 - len(rt.checks)) * .05 / 6}

    def _ready(self, context_id, cause):
        item = self.contexts[context_id]
        item["status"] = "runnable"
        if context_id not in self.ready:
            self.ready.append(context_id)
        self._event(context_id, "context_runnable", {"cause": cause, "remaining": self.remaining(context_id)})

    def after_decision(self, context_id):
        item = self.contexts[context_id]; rt = item["runtime"]
        if item["status"] not in {"running", "runnable"}:
            raise ValueError("decision completed outside a runnable context")
        if context_id in self.ready:
            self.ready.remove(context_id)
        if rt.closed or rt.decisions_closed:
            item["status"] = "terminal"
            self._event(context_id, "context_terminal", {"remaining": self.remaining(context_id)})
            return
        jobs = self._unreceived(rt)
        if jobs and rt.gateway.clock < rt.gateway.deadline:
            item.update(status="waiting", waiting_job_ids=jobs)
            self._event(context_id, "context_waiting", {"job_ids": jobs, "remaining": self.remaining(context_id)})
        else:
            self._ready(context_id, "calendar_deadline" if rt.gateway.clock >= rt.gateway.deadline else "decision_feedback")

    def advance(self, context_id):
        item = self.contexts[context_id]; rt = item["runtime"]
        if item["status"] != "waiting":
            raise ValueError("only a waiting context can receive committed jobs")
        if rt.closed or rt.decisions_closed:
            item["status"] = "terminal"
            self._event(context_id, "context_terminal", {"cause": "decisions_closed_while_waiting"})
            return None
        jobs = item["waiting_job_ids"]
        if not set(self._unreceived(rt)) <= set(jobs):
            raise ValueError("new job registered while context was suspended")
        before = self.remaining(context_id)
        # Preserve a finish action. No new ledger or revised check allocation.
        if not self._unreceived(rt):
            receipt = {"reason": "committed_jobs_already_received", "unresolved_job_ids": [], "trace": []}
        elif rt.calls >= rt.max_calls - CONTRACT["scientific_action_reserve"]:
            receipt = {"reason": "scientific_reserve_for_finish", "unresolved_job_ids": self._unreceived(rt), "trace": []}
        else:
            fixed = {"registry": digest(rt.registry), "plans": digest(rt.objects["plans"]),
                     "check_ids": [c["check_id"] for c in rt.checks], "revisions": rt.revisions,
                     "released": [c["released"] for c in rt.checks]}
            used = copy.deepcopy(rt.gateway.used); rt.calls += 1; started = time.monotonic()
            receipt = settle(rt, {"job_ids": jobs}, CONTRACT["receipt_max_steps"])
            actual = {"registry": digest(rt.registry), "plans": digest(rt.objects["plans"]),
                      "check_ids": [c["check_id"] for c in rt.checks], "revisions": rt.revisions,
                      "released": [c["released"] for c in rt.checks]}
            if actual != fixed:
                raise ValueError("receipt worker changed scientific decisions")
            feedback = {"ok": True, "result": copy.deepcopy(receipt)}
            rt.last_feedback = feedback
            rt._event("scientific_tool_response", {"request": {"tool": "collect_committed_receipts",
                      "args": {"job_ids": jobs}, "rationale": "事前队列执行规则。",
                      "expected_gap": "收取原测量并唤醒原研究，不自动修订。"},
                      "feedback": feedback, "used_before": used,
                      "used_after": copy.deepcopy(rt.gateway.used), "wall_seconds": time.monotonic() - started})
        wake = {"receipt": receipt, "remaining_before": before,
                "remaining_after": self.remaining(context_id),
                "research_event_count": len(rt.events),
                "research_prefix_hash": rt.events[-1]["event_hash"],
                "checks": [{"check_id": c["check_id"], "candidate_id": c["candidate_id"],
                            "state": None if c["result"] is None else c["result"]["state"]} for c in rt.checks]}
        item["wake_count"] += 1; item["last_wakeup"] = wake
        self._event(context_id, "context_woken", wake)
        self._ready(context_id, receipt["reason"])
        return copy.deepcopy(wake)

    def pop_ready(self):
        # At most one active decision/receipt worker per shared task ledger.
        for _ in range(len(self.ready)):
            context_id = self.ready.popleft(); item = self.contexts[context_id]
            if item["runtime"].closed or item["runtime"].decisions_closed:
                item["status"] = "terminal"
                self._event(context_id, "context_terminal", {"cause": "closed_before_dispatch"})
                continue
            if any(other is not item and other["runtime"] is item["runtime"] and
                   other["status"] in {"running", "waiting"} for other in self.contexts.values()):
                self.ready.append(context_id)
                continue
            item["status"] = "running"
            self._event(context_id, "context_dispatched", {"remaining": self.remaining(context_id)})
            return context_id
        return None

    def view(self, context_id):
        item = self.contexts[context_id]
        wake = item["last_wakeup"]
        return {"context_id": context_id, "workflow_version": VERSION,
                "contract_sha256": digest(CONTRACT), "status": item["status"],
                "wake_count": item["wake_count"], "remaining": self.remaining(context_id),
                "last_wakeup": None if wake is None else {k: copy.deepcopy(wake[k]) for k in
                    ("remaining_before", "remaining_after", "research_event_count", "research_prefix_hash", "checks")},
                "last_receipt_reason": None if wake is None else wake["receipt"]["reason"]}

    def snapshot(self):
        return {"version": VERSION, "contract": copy.deepcopy(CONTRACT),
                "contexts": {k: self.view(k) for k in self.contexts},
                "ready": list(self.ready), "events": copy.deepcopy(self.events)}
