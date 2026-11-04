"""A/B/C resource organization over one public Runtime, without environment forks.

Notes are model appraisals, not scientific evidence. B stores exact candidate
groups and role contexts. C stores executable-program/experiment branches.
"""
import copy

from temporal_lab import digest

VERSION = "research-organization-v0.1-shared-runtime-contexts"
MODES = {"A", "B", "C"}
ROLES = {
    "coordinator": "根据公开问题、证据缺口、原检查条件和剩余预算选择研究动作、回退或停止。",
    "supervisor": "维护竞争解释与缺口，给生成/审查上下文分配实际任务；所有调用共用原预算。",
    "generator": "提出或修订可执行的竞争解释；检查已见数据依赖，保留现有解释不足的出口。",
    "reviewer": "审查候选前提、原负证据、可观测预测分歧与代价；讨论和回放不产生独立支持。",
    "branch_researcher": "按父节点公开反馈执行、修程序、修机制或改检验；保存真实错误/等待/分析，不克隆环境。",
}


class ResearchOrganization:
    def __init__(self, mode):
        if mode not in MODES:
            raise ValueError("unknown organization")
        self.mode = mode; self.contexts = {}; self.events = []; self.notes = []
        self.groups = {}; self.members = {}; self.plan_owners = {}; self.check_owners = {}
        self.analysis_ids=set();self.scientific_responses=0
        self.max_nodes = 12
        ids = ["coordinator"] if mode == "A" else ["supervisor", "generator", "reviewer"] if mode == "B" else ["T0000"]
        for context_id in ids:
            role = context_id if mode != "C" else "branch_researcher"
            self.contexts[context_id] = {"context_id": context_id, "role": role,
                "objective": ROLES[role], "parent_id": None, "branch_kind": "initial", "candidate_id": None,
                "analysis_ids": [], "job_ids": [], "check_ids": [], "program_versions": [], "feedback_refs": []}
        self.current = ids[0]

    def contract(self):
        return {"version": VERSION, "mode": self.mode, "scientific_services": "same shared public scientific services",
                "one_runtime": True, "one_api_allocation": True, "one_physical_and_alpha_ledger": True,
                "context_creation_resets_budget": False, "model_appraisals_are_evidence": False,
                "local_action_scientific_charge": 1, "max_C_nodes": self.max_nodes,
                "B_deduplication": "exact executable model plus training/information dependencies; not semantic equivalence",
                "C_implementation_scope": "common safe probability DSL and compiler; no arbitrary Python or world rollback"}

    def _append(self, kind, value, source_event):
        body = {"sequence": len(self.events), "kind": kind, "context_id": self.current,
                "payload": copy.deepcopy(value), "available_at": source_event["available_at"],
                "source_event_sequence": source_event["sequence"], "source_event_sha256": source_event["event_hash"],
                "previous_hash": self.events[-1]["event_hash"] if self.events else None}
        self.events.append(body | {"event_hash": digest(body)})

    def observe(self, event):
        kind = event["kind"]; p = event["payload"]
        context = self.contexts[self.current]
        if kind == "candidate_registered":
            key = digest({"model": p["model"], "training": p["training_evidence_ids"], "information": p.get("information_evidence_ids", [])})
            if key not in self.groups:
                gid = f"H{len(self.groups):04d}"
                self.groups[key] = {"group_id": gid, "identity_sha256": key, "members": [], "origins": [], "criticisms": []}
            group = self.groups[key]; group["members"].append(p["candidate_id"])
            if p["origin"] not in group["origins"]: group["origins"].append(p["origin"])
            self.members[p["candidate_id"]] = group["group_id"]
            if self.mode == "C": context["program_versions"].append(p["candidate_id"])
        elif kind == "registered_plan_linked":
            self.plan_owners[p["job_id"]] = self.current; context["job_ids"].append(p["job_id"])
        elif kind == "check_frozen_before_execution":
            self.check_owners[p["check_id"]] = self.current; context["check_ids"].append(p["check_id"])
        elif kind == "independent_check_assessed":
            self.analysis_ids.add(f"A{p['check_index']:03d}")
            owner = self.check_owners[p["check_id"]]
            self.contexts[owner]["feedback_refs"].append({"kind": kind, "check_id": p["check_id"],
                "state": p["result"]["state"], "source_event_sequence": event["sequence"]})
        elif kind == "scientific_tool_response":
            request = p["request"]; feedback = p["feedback"]
            self.scientific_responses+=1
            if request["tool"] == "dispatch_research_context" and feedback["ok"]:
                result = feedback["result"]; args = request["args"]
                if args["target_id"] not in self.contexts or not set(args["analysis_ids"])<=self.analysis_ids or ("candidate_id" in args and args["candidate_id"] not in self.members):raise ValueError("invalid dispatched context references")
                if result["budget_reset"] is not False or result["shared_scientific_actions_used"]!=self.scientific_responses or result["shared_used"]!=p["used_after"]:raise ValueError("organization attempted a new ledger")
                if args["kind"]=="select":
                    if result["created_context"] is not None or result["context_id"]!=args["target_id"] or "branch_kind" in args:raise ValueError("invalid context selection")
                else:
                    expected={"context_id":f"T{len(self.contexts):04d}","role":"branch_researcher","objective":args["objective"],
                        "parent_id":args["target_id"],"branch_kind":args["branch_kind"],"candidate_id":args.get("candidate_id"),
                        "analysis_ids":copy.deepcopy(args["analysis_ids"]),"job_ids":[],"check_ids":[],"program_versions":[],"feedback_refs":[]}
                    if args["kind"]!="expand" or self.mode!="C" or len(self.contexts)>=self.max_nodes or result["created_context"]!=expected or result["context_id"]!=expected["context_id"]:raise ValueError("invalid executable child branch")
                if result["created_context"] is not None:
                    self.contexts[result["created_context"]["context_id"]] = copy.deepcopy(result["created_context"])
                target = self.contexts[result["context_id"]]
                target.update(objective=args["objective"], candidate_id=args.get("candidate_id"), analysis_ids=copy.deepcopy(args["analysis_ids"]))
                self._append("context_dispatched", result | {"basis": args["objective"]}, event)
                self.current = result["context_id"]
            elif request["tool"] == "append_research_note" and feedback["ok"]:
                args=request["args"]
                if not set(args["analysis_ids"])<=self.analysis_ids or ("candidate_id" in args and args["candidate_id"] not in self.members):raise ValueError("invalid appraisal reference")
                expected={"note_id":f"N{len(self.notes):04d}","context_id":self.current,**copy.deepcopy(args),"available_at":event["available_at"],"epistemic_role":"model_appraisal_not_scientific_evidence"}
                if feedback["result"]!=expected:raise ValueError("appraisal differs from original model submission")
                note = copy.deepcopy(feedback["result"]); self.notes.append(note)
                cid = note.get("candidate_id")
                if cid is not None:
                    group = next(g for g in self.groups.values() if g["group_id"] == self.members[cid])
                    group["criticisms"].append(note["note_id"])
                self._append("model_appraisal_recorded", note, event)
            elif request["tool"] not in {"dispatch_research_context", "append_research_note"}:
                context["feedback_refs"].append({"kind": "tool_result", "tool": request["tool"],
                    "ok": feedback["ok"], "source_event_sequence": event["sequence"],
                    "error": feedback.get("error")})
                self._append("scientific_action_observed", {"tool": request["tool"], "ok": feedback["ok"],
                    "used_before": p["used_before"], "used_after": p["used_after"]}, event)

    def validate_refs(self, args, rt):
        if "candidate_id" in args and args["candidate_id"] not in rt.registry:
            raise ValueError("unknown immutable candidate")
        if not set(args["analysis_ids"]) <= set(rt.public_evidence.latest):
            raise ValueError("unknown available scientific analysis")

    def dispatch(self, args, rt):
        self.validate_refs(args, rt)
        kind = args["kind"]; target = args["target_id"]
        if target not in self.contexts:
            raise ValueError("unknown existing context or parent")
        created = None
        if kind == "expand":
            if self.mode != "C" or len(self.contexts) >= self.max_nodes or "branch_kind" not in args:
                raise ValueError("only C may create a bounded typed child branch")
            cid = f"T{len(self.contexts):04d}"
            created = {"context_id": cid, "role": "branch_researcher", "objective": args["objective"],
                "parent_id": target, "branch_kind": args["branch_kind"], "candidate_id": args.get("candidate_id"),
                "analysis_ids": copy.deepcopy(args["analysis_ids"]), "job_ids": [], "check_ids": [],
                "program_versions": [], "feedback_refs": []}
            target = cid
        elif kind != "select" or "branch_kind" in args:
            raise ValueError("select must target an existing context without a branch kind")
        # Mutation occurs only when the enclosing real scientific response is
        # appended. A failed submission cannot half-create a branch.
        return {"context_id": target, "created_context": created, "budget_reset": False,
                "shared_scientific_actions_used": rt.calls, "shared_used": copy.deepcopy(rt.gateway.used)}

    def note(self, args, rt):
        self.validate_refs(args, rt)
        return {"note_id": f"N{len(self.notes):04d}", "context_id": self.current, **copy.deepcopy(args),
                "available_at": rt.gateway.clock, "epistemic_role": "model_appraisal_not_scientific_evidence"}

    def view(self, public_observations, visible_candidate_ids=None):
        jobs = {j["job_id"]: j["status"] for key in ("pending_jobs", "failed_jobs", "unverified_jobs") for j in public_observations[key]}
        contexts = []
        for original in self.contexts.values():
            item = copy.deepcopy(original)
            item["execution_state"] = {str(j): jobs.get(j, "received") for j in item["job_ids"]}
            contexts.append(item)
        groups=list(self.groups.values())
        if visible_candidate_ids is not None:
            visible=set(visible_candidate_ids)|{c["candidate_id"] for c in self.contexts.values() if c["candidate_id"] is not None}|{n["candidate_id"] for n in self.notes if n.get("candidate_id") is not None}
            groups=[g for g in groups if visible & set(g["members"])]
        return {"contract": self.contract(), "current_context_id": self.current,
                "current_role_objective": ROLES[self.contexts[self.current]["role"]],
                "contexts": contexts, "notes": copy.deepcopy(self.notes),
                "candidate_group_count": len(self.groups), "candidate_groups": copy.deepcopy(groups),
                "candidate_group_projection": "Current public committee and explicitly focused/noted hypotheses; complete exact groups remain in archive.",
                "no_private_branch_score": True}

    def snapshot(self, public_observations):
        return {**self.view(public_observations), "events": copy.deepcopy(self.events),
                "plan_owners": copy.deepcopy(self.plan_owners), "check_owners": copy.deepcopy(self.check_owners)}

    @classmethod
    def from_events(cls, mode, events):
        organization=cls(mode)
        previous=None
        for event in events:
            body={k:v for k,v in event.items() if k!="event_hash"}
            if event["previous_hash"]!=previous or event["event_hash"]!=digest(body):raise ValueError("invalid original organization event source")
            organization.observe(event);previous=event["event_hash"]
        return organization
