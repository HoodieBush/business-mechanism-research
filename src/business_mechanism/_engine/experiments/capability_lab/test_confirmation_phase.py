import copy
import json
import unittest
from unittest.mock import patch

from confirmation_phase import from_events,phases
from choice_world import ChoiceWorld
from native_science_protocol import function_definitions
from public_context import unpack
from research_actor import ScienceActor
from research_runtime import ResearchRuntime
from run_scientific import agent_view,SCHEMA
from scientific_readiness import action_charge,readiness
from temporal_lab import TemporalLab,digest


class ConfirmationPhaseTests(unittest.TestCase):
    def check(self):return {"check_id": "K000", "candidate_id": "C0001", "job_ids": [4, 5], "state": None, "released": False}
    def row(self, job, time=3, version=1, verified=True):return {"job_id": job, "experiment_id": 20+job,
        "available_at": time, "evidence_version": version, "verified_supply": True, "verified_meter": verified}

    def test_protection_does_not_prevent_analysis_of_complete_verified_inputs(self):
        check = self.check();rows = [self.row(4), self.row(5)];original = copy.deepcopy((check, rows))
        result = phases([check], rows, 3)["checks"][0]
        self.assertEqual(result["analysis_phase"], "ready_to_assess")
        self.assertEqual(result["training_permission"], "protected_from_fitting")
        self.assertIsNone(result["analysis_outcome"]);self.assertEqual((check, rows), original)

    def test_future_verification_is_not_backdated_and_job_ids_are_not_experiment_ids(self):
        rows = [self.row(4), self.row(5, verified=False), self.row(5, time=8, version=2)]
        early = phases([self.check()], rows, 3)["checks"][0]
        self.assertEqual(early["analysis_phase"], "awaiting_verified_inputs")
        self.assertEqual(early["unverified_measurement_ids"], [25])
        self.assertEqual(phases([self.check()], rows, 8)["checks"][0]["analysis_phase"], "ready_to_assess")

    def test_release_and_analysis_remain_separate_when_prior_outcome_exists(self):
        check = self.check();check.update(state="contradicted", released=True)
        result = phases([check], [self.row(4), self.row(5)], 3)["checks"][0]
        self.assertEqual(result["analysis_phase"], "assessed")
        self.assertEqual(result["analysis_outcome"], "contradicted")
        self.assertEqual(result["training_permission"], "released_for_refitting")

    def prepared(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(5702,"mixed_scope"),"interruptions"),terminal_policy="settle_committed",organization_mode="A")
        rt.call("sample_and_analyze",{"candidate_id":rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":[],"n":400}],"rationale":"公共训练。","repair":True})
        rt.call("confirm",{"candidate_id":rt.pool[0],"rationale":"原独立检查。"})
        rt.call("collect",{"until":"all","repair":True,"refit":False,"assess":False})
        return rt

    def test_event_projection_distinguishes_ready_assessed_and_released_without_mutation(self):
        rt=self.prepared();before=digest(rt.snapshot());projection=from_events(rt.events,rt.gateway.clock)
        self.assertEqual(projection["checks"][0]["analysis_phase"],"ready_to_assess")
        self.assertEqual(digest(rt.snapshot()),before)
        rt.call("assess_checks",{})
        projected=from_events(rt.events,rt.gateway.clock)
        self.assertEqual(projected["checks"][0]["analysis_phase"],"assessed")
        self.assertEqual(projected["checks"][0]["training_permission"],"protected_from_fitting")
        self.assertEqual(projected,phases(rt.checks,rt.gateway.public_state()["mature_evidence"],rt.gateway.clock))

    def test_actor_flag_changes_only_delivered_phase_context_not_tools_or_state(self):
        limits={"calls":32,"reported_tokens":250000,"max_output_tokens":2400,"admission_policy":"provider_prompt_ratio"}
        runs=[];payloads=[];base=self.prepared()
        for enabled in (False,True):
            rt=copy.deepcopy(base);actor=ScienceActor(rt,agent_view,SCHEMA,limits,"native",True,use_reference_contract=True,use_confirmation_phase=enabled)
            def request(_,payload):
                payloads.append(copy.deepcopy(payload))
                return {"request":copy.deepcopy(payload),"cache_hit":False,"response":{"choices":[{"finish_reason":"stop","message":{"content":"", "tool_calls":[{"id":"call_test","type":"function","function":{"name":"assess_checks","arguments":json.dumps({"rationale":"只分析原冻结检查。","expected_gap":"取得原条件结论。"},ensure_ascii=False)}}]}}],"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}}
            with patch("research_actor.request_model",side_effect=request):record=actor.next([])
            self.assertTrue(record["tool_feedbacks"][0]["ok"])
            runs.append((rt,record))
        self.assertEqual(payloads[0]["tools"],payloads[1]["tools"])
        plain=unpack(json.loads(payloads[0]["messages"][-1]["content"]))["research_state"]
        augmented=unpack(json.loads(payloads[1]["messages"][-1]["content"]))["research_state"]
        phase=augmented.pop("confirmation_status")
        self.assertEqual(plain,augmented);self.assertEqual(readiness(plain),readiness(augmented))
        self.assertEqual(phase["checks"][0]["analysis_phase"],"ready_to_assess")
        self.assertEqual(runs[0][0].gateway.used,runs[1][0].gateway.used)
        self.assertEqual(runs[0][0].training_ids,runs[1][0].training_ids)
        self.assertNotIn("confirmation_phase_version",runs[0][1]);self.assertIn("confirmation_phase_version",runs[1][1])

    def test_partial_check_and_future_events_are_not_complete(self):
        check=self.check();check["job_ids"]=[4]
        self.assertEqual(phases([check],[self.row(4)],3)["checks"][0]["receipt_phase"],"incomplete_registered_check")
        rt=self.prepared();prefix=copy.deepcopy(rt.events);clock=rt.gateway.clock
        rt.call("assess_checks",{})
        for event in rt.events[len(prefix):]:event["available_at"]=clock+1
        self.assertEqual(from_events(rt.events,clock),from_events(prefix,clock))

    def test_task_batch_admission_counts_inner_actions_before_any_execution(self):
        rt=ResearchRuntime(TemporalLab(ChoiceWorld(5702,"mixed_scope")),organization_mode="A",use_discovery_tasks=True);rt.max_calls=3
        limits={"calls":32,"reported_tokens":250000,"max_output_tokens":2400,"admission_policy":"provider_prompt_ratio"}
        actor=ScienceActor(rt,agent_view,SCHEMA,limits,"native",True)
        args=[("start_discovery_task",{"candidate_id":rt.initial_candidate,"count":1,"objective":"有界批次。","rationale":"计费边界。","expected_gap":"原计划产物。","repair":True}),
              ("finish",{"candidate_id":rt.initial_candidate,"claims":"未决。","unresolved":True,"stop_reason":"额度停止。","rationale":"边界。","expected_gap":"冻结。"})]
        def request(_,payload):return {"request":copy.deepcopy(payload),"cache_hit":False,"response":{"choices":[{"finish_reason":"stop","message":{"content":"","tool_calls":[{"id":f"call_{i}","type":"function","function":{"name":name,"arguments":json.dumps(value,ensure_ascii=False)}} for i,(name,value) in enumerate(args)]}}],"usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}}
        with patch("research_actor.request_model",side_effect=request):record=actor.next([])
        self.assertIn("scientific batch exceeds",record["submission_error"])
        self.assertEqual(rt.calls,0);self.assertEqual(rt.jobs,{})
        self.assertEqual(rt.discovery_tasks.tasks,{})


if __name__ == "__main__":unittest.main()
