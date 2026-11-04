"""Read-only workflow cues from the received public research state.

Does not rank hypotheses, inspect a world, fit, collect, or grant support. Several
work items may coexist: waiting for a receipt need not prevent other research.
"""
import copy

from scientific_readiness import readiness

VERSION = "state-brief-v0.1-public-work-items"


def state_brief(state):
    ready = readiness(state)
    services = ready["services"]
    work = []

    def add(kind, references, tools, reason):
        work.append({"kind": kind, "references": copy.deepcopy(references),
                     "available_tools": [tool for tool in tools if services.get(tool, {}).get("ready")],
                     "reason": reason, "epistemic_role": "workflow_cue_not_scientific_evidence"})

    evidence = state.get("public_evidence_store", {})
    if evidence.get("last_history_diagnosis") is None:
        add("history_quality_unclassified", [], ["diagnose_history"],
            "历史销量不足以区分供给与记录问题，核查结果不作为随机需求样本。")
    if "adaptation" not in state["catalogs"]:
        add("adaptation_catalog_not_received", [], ["open_adaptation"],
            "若要研究适应条件，目录须在首次采样冻结本体前取得；重复读取不增加证据。")
    for job in state["failed_jobs"]:
        add("execution_failed", [{"job_id": job["job_id"], "status": job["status"]}],
            (["repair"] if job["job_id"] in ready["parameter_domains"]["execution_job_ids"] else []) + ["collect"],
            "原实验执行失败，不是科学反驳；只能按实际修复权限处理。")
    for job in state["unverified_jobs"]:
        add("measurement_unverified", [{"job_id": job["job_id"], "status": job["status"]}],
            ["repair", "collect"], "尚未核实的计数不可用于拟合或独立确认。")
    if state["pending_jobs"]:
        add("receipts_pending", [{key: job[key] for key in
            ("job_id", "status", "expected_report_at", "audit_expected_at") if key in job}
            for job in state["pending_jobs"]], ["collect"],
            "只知道待回执状态，没有未来计数；可等待或并行处理其他已收到的研究资料。")
    training = set(state["training_evidence_ids"])
    if not training:
        add("no_released_target_training", [],
            ["suggest_design", "sample", "sample_frontier", "sample_and_analyze"],
            "数值拟合/自由模型提案需要核实且已释放的目标证据；初始模型仍可合法检验。")
    else:
        add("target_training_available", [{"experiment_id": identifier} for identifier in sorted(training)],
            ["fit_pool", "propose_model", "review_candidate_evidence", "suggest_design"],
            "可估参或提出结构；拟合、旧证据回放和BIC都不授予独立支持。")
    for check in state["checks"]:
        refs = [{key: check[key] for key in ("check_id", "candidate_id", "job_ids", "released")}]
        if check["state"] is None:
            add("registered_check_unresolved", refs, ["collect", "assess_checks"],
                "检查已冻结，结果尚未分析；未成熟/未核实不能按零效应或成功处理。")
        elif check["state"] == "contradicted" and not check["released"]:
            add("actual_refutation_available", refs,
                ["review_candidate_evidence", "reopen_research"],
                "原模型在列出条件受到反驳；是否重开由策略决定，修订须用新独立检验。")
    unchecked = [candidate["candidate_id"] for candidate in state["candidates"]
                 if candidate.get("training_evidence_ids") and not any(
                     check["candidate_id"] == candidate["candidate_id"] for check in state["checks"])]
    if unchecked:
        add("fitted_candidates_without_registered_checks", [{"candidate_id": identifier} for identifier in unchecked],
            ["read_candidate", "review_candidate_evidence", "suggest_design", "confirm", "confirm_and_analyze"],
            "这些可见候选尚未登记独立检查；仍可先区分竞争解释，不要求立即确认。")
    actions_left = state["scientific_actions_limit"] - state["scientific_actions_used"]
    if state["clock"] >= state["limits"]["logical_time"] or actions_left <= 1:
        add("terminal_pressure", [], ["assess_checks", "finish"],
            "截止或动作额度不足；已收到证据与未决范围分开，停止不等于科学认证。")
    elif not any(services[tool]["ready"] for tool in ("sample", "confirm")):
        add("new_measurement_allocation_unavailable", [],
            ["collect", "review_candidate_evidence", "assess_checks", "finish"],
            "新采样或确认当前不可执行，可能是容量或资源限制；不是模型已被否定。")
    # Retain all original condition outcomes, including released negative checks.
    outcomes = [{key: copy.deepcopy(check[key]) for key in
                 ("check_id", "candidate_id", "state", "released")} for check in state["checks"]]
    org = state.get("research_organization", {})
    return {"version": VERSION, "clock": state["clock"], "work_items": work,
            "reference_domains": {"visible_candidate_ids": [candidate["candidate_id"] for candidate in state["candidates"]],
                "initial_candidate_id": state["initial_candidate_id"],
                "available_analysis_ids": [card["analysis_id"] for card in evidence.get("analysis_cards", [])],
                "available_context_ids": [context["context_id"] for context in org.get("contexts", [])],
                **copy.deepcopy(ready["parameter_domains"])},
            "registered_condition_outcomes": outcomes,
            "remaining_resources": {**copy.deepcopy(ready["remaining"]), "scientific_actions": actions_left,
                "logical_ticks": max(0, state["limits"]["logical_time"] - state["clock"]),
                "pending_slots": ready["pending_slots"], "check_slots": ready["check_slots"]},
            "available_services": sorted(tool for tool, value in services.items() if value["ready"]),
            "current_context_id": org.get("current_context_id"),
            "history_diagnosis_received": evidence.get("last_history_diagnosis") is not None,
            "verified_training_sessions": sum(row["n"] for row in state["verified_condition_table"]
                                              if row["experiment_id"] in training),
            "scope": "Routing cues only; multiple items may coexist, no fixed scientific order, no hypothesis-quality mask. Support applies only to the frozen model and listed condition.",
            "business_boundary": "Research sessions and logical ticks are not inventory periods. Business decisions use frozen relationships and are evaluated separately from scientific support."}
