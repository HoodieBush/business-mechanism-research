import copy
import unittest
from unittest.mock import patch

from choice_world import ChoiceWorld
from native_science_protocol import function_definitions
from reference_contract import domains, validate_action
from research_actor import ScienceActor
from research_runtime import ResearchRuntime
from run_scientific import API_LIMITS, SCHEMA, agent_view
from temporal_lab import TemporalLab
from test_native_science_protocol import raw


class ReferenceContractTests(unittest.TestCase):
    def runtime(self, mode):
        return ResearchRuntime(TemporalLab(ChoiceWorld(5301, "threeway")), organization_mode=mode)

    def definitions(self, state):
        return {value["function"]["name"]: value["function"]["parameters"]
                for value in function_definitions(state, reference_contract=True)}

    def action(self, kind="select", target="coordinator", **args):
        return {"tool": "dispatch_research_context", "args": {
            "kind": kind, "target_id": target, "objective": "研究公开条件。", "analysis_ids": [], **args}}

    def test_domains_distinguish_candidate_analysis_and_existing_context_without_mutating_state(self):
        state = agent_view(self.runtime("A")); original = copy.deepcopy(state)
        definition = self.definitions(state)["dispatch_research_context"]
        self.assertEqual(definition["properties"]["target_id"]["enum"], ["coordinator"])
        self.assertEqual(definition["properties"]["kind"]["enum"], ["select"])
        self.assertEqual(definition["properties"]["analysis_ids"]["items"]["enum"], [])
        self.assertNotIn("enum", definition["properties"]["objective"])
        self.assertNotIn("enum", definition["properties"]["candidate_id"])
        self.assertNotIn("pattern", definition["properties"]["objective"])
        self.assertNotIn("pattern", definition["properties"]["rationale"])
        validate_action(self.action(), state)
        with self.assertRaisesRegex(ValueError, "context ID"):
            validate_action(self.action(target="C0000"), state)
        with self.assertRaises(ValueError):
            validate_action(self.action(analysis_ids=[0]), state)
        self.assertEqual(state, original)

    def test_product_domain_never_contaminates_candidate_or_reason_fields(self):
        state = agent_view(self.runtime("A"))
        for use_contract in (False, True):
            definitions = {value["function"]["name"]: value["function"]["parameters"]
                for value in function_definitions(state, reference_contract=use_contract)}
            self.assertNotIn("enum", definitions["confirm"]["properties"]["candidate_id"])
            self.assertNotIn("enum", definitions["confirm"]["properties"]["rationale"])
            self.assertNotIn("pattern", definitions["append_research_note"]["properties"]["text"])

    def test_A_B_cannot_expand_and_C_expansion_needs_branch_kind(self):
        for mode, target in (("A", "coordinator"), ("B", "supervisor")):
            state = agent_view(self.runtime(mode))
            with self.assertRaisesRegex(ValueError, "unavailable"):
                validate_action(self.action("expand", target, branch_kind="refine"), state)
        state = agent_view(self.runtime("C"))
        self.assertEqual(domains(state)["dispatch_kinds"], ["select", "expand"])
        with self.assertRaisesRegex(ValueError, "requires"):
            validate_action(self.action("expand", "T0000"), state)
        validate_action(self.action("expand", "T0000", branch_kind="refine"), state)
        with self.assertRaisesRegex(ValueError, "must not"):
            validate_action(self.action("select", "T0000", branch_kind="refine"), state)

    def test_new_child_domain_updates_and_future_refs_remain_rejected(self):
        rt = self.runtime("C"); before = agent_view(rt)
        rt.call("dispatch_research_context", self.action("expand", "T0000", branch_kind="refine")["args"])
        after = agent_view(rt)
        child = self.action("select", "T0001")
        with self.assertRaises(ValueError):validate_action(child, before)
        validate_action(child, after)
        after["public_evidence_store"]["analysis_cards"] = [{"analysis_id": "A000"}]
        self.assertEqual(self.definitions(after)["append_research_note"]["properties"]["analysis_ids"]["items"]["enum"], ["A000"])
        with self.assertRaises(ValueError):validate_action(self.action("select", "T0001", analysis_ids=["A001"]), after)

    def test_C_node_capacity_disables_expand_without_disabling_select(self):
        rt = self.runtime("C")
        for _ in range(11):rt.call("dispatch_research_context", self.action("expand", "T0000", branch_kind="refine")["args"])
        state = agent_view(rt)
        self.assertEqual(self.definitions(state)["dispatch_research_context"]["properties"]["kind"]["enum"], ["select"])
        validate_action(self.action("select", "T0000"), state)

    def test_native_transport_has_no_nonexistent_wrapper_instruction_and_wrapper_still_has_its_function(self):
        for mode in ("native", "wrapper"):
            rt = self.runtime("A"); actor = ScienceActor(rt, agent_view, SCHEMA, API_LIMITS, mode, True)
            response = raw("diagnose_history", {"rationale": "核查。", "expected_gap": "记录质量。"})
            with patch("research_actor.request_model", side_effect=lambda _, payload: {"request": copy.deepcopy(payload), "cache_hit": False, "response": response}):record = actor.next([])
            system = record["request"]["messages"][0]["content"]
            instruction = "输出协议：必须调用 API 函数 submit_research_action"
            if mode == "native":
                self.assertNotIn(instruction, system)
                self.assertNotIn("submit_research_action", [value["function"]["name"] for value in record["request"]["tools"]])
                self.assertTrue(record["tool_feedbacks"][0]["ok"])
            else:self.assertIn(instruction, system)

    def test_ignored_provider_schema_does_not_create_context_or_charge_science(self):
        rt = self.runtime("A")
        actor = ScienceActor(rt, agent_view, SCHEMA, API_LIMITS, "native", True, use_reference_contract=True)
        response = raw("dispatch_research_context", {"kind": "expand", "target_id": "C0000", "objective": "新研究。", "analysis_ids": [], "branch_kind": "refine", "rationale": "计划。", "expected_gap": "新条件。"})
        with patch("research_actor.request_model", side_effect=lambda _, payload: {"request": copy.deepcopy(payload), "cache_hit": False, "response": response}):record = actor.next([])
        self.assertFalse(record["tool_feedbacks"][0]["executed"])
        self.assertEqual(len(rt.organization.contexts), 1)
        self.assertEqual(rt.calls, 0)
        self.assertEqual(rt.gateway.used["sessions"], 0)
        self.assertIn("reference_contract_version", record)


if __name__ == "__main__":unittest.main()
