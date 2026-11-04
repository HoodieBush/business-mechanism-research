import copy
import unittest

from choice_world import ChoiceWorld
from research_notebook import ResearchNotebook
from research_runtime import ResearchRuntime
from run_scientific import agent_view
from scientific_readiness import SERVICES,readiness,validate_ready_action,validate_request_bindings
from temporal_lab import TemporalLab
from test_research_runtime import public_archive


class ReadinessTests(unittest.TestCase):
    def setUp(self):self.rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"threeway"),"interruptions"),public_archive())
    def action(self,tool,args={}):return {"tool":tool,"args":args,"rationale":"公开计划。","expected_gap":"可执行条件。"}
    def sample(self):return self.rt.call("sample_frontier",{"candidate_id":self.rt.initial_candidate,"count":3,"rationale":"初始覆盖。"})
    def collect(self):return self.rt.call("collect",{"until":"all","repair":True,"refit":True,"assess":False})

    def test_no_data_gates_fitting_without_prescribing_hypothesis_or_scientific_order(self):
        view=agent_view(self.rt);r=readiness(view)
        self.assertEqual(set(r["services"]),SERVICES);self.assertFalse(r["services"]["propose_model"]["ready"])
        self.assertTrue(r["services"]["confirm"]["ready"]);self.assertTrue(r["services"]["sample_and_analyze"]["ready"])
        with self.assertRaisesRegex(ValueError,"training"):validate_ready_action(self.action("fit_pool"),view)
        self.sample();self.assertFalse(readiness(agent_view(self.rt))["services"]["fit_pool"]["ready"])
        self.collect();self.assertTrue(readiness(agent_view(self.rt))["services"]["propose_model"]["ready"])

    def test_pending_capacity_actual_repair_ids_and_source_sites(self):
        self.sample();view=agent_view(self.rt);jid=view["failed_jobs"][0]["job_id"]
        validate_ready_action(self.action("repair",{"job_id":jid,"kind":"execution"}),view)
        with self.assertRaisesRegex(ValueError,"receipt"):validate_ready_action(self.action("repair",{"job_id":jid,"kind":"meter"}),view)
        with self.assertRaisesRegex(ValueError,"allocation"):validate_ready_action(self.action("sample_frontier",{"candidate_id":self.rt.initial_candidate,"count":3}),view)
        bad={"candidate_id":self.rt.initial_candidate,"designs":[{"stage":"source","site":"10","assortment":[],"n":400}],"rationale":"非法柜点。"}
        with self.assertRaisesRegex(ValueError,"stage/site"):validate_ready_action(self.action("sample",bad),view)
        self.assertFalse(readiness(view)["services"]["open_adaptation"]["ready"])

    def test_actual_refutation_gates_revision_and_calendar_gates_new_collection(self):
        self.sample();self.collect()
        bad=self.rt.call("propose_model",{"expression":"min(.95,max(.05,b))","parameters":{"b":[.9,.89,.91]},"rationale":"错误候选测试。"})["result"]["candidate_id"]
        self.rt.call("confirm_and_analyze",{"candidate_id":bad,"repair":True,"rationale":"新确认。"})
        view=agent_view(self.rt);self.assertEqual(view["checks"][0]["state"],"contradicted")
        validate_ready_action(self.action("reopen_research",{"check_id":"K000","rationale":"反驳。","refit":True}),view)
        self.rt.call("reopen_research",{"check_id":"K000","rationale":"反驳。","refit":True})
        self.assertFalse(readiness(agent_view(self.rt))["services"]["reopen_research"]["ready"])
        cutoff=copy.deepcopy(view);cutoff["clock"]=cutoff["limits"]["logical_time"]
        self.assertFalse(readiness(cutoff)["services"]["sample"]["ready"]);self.assertTrue(readiness(cutoff)["services"]["finish"]["ready"])

    def test_notebook_preserves_receipts_and_versions_without_new_training_or_samples(self):
        book=ResearchNotebook();action=self.action("retrieve_memory")
        feedback=self.rt.call(action["tool"],action["args"]);book.observe(action,feedback,self.rt.gateway.clock);book.observe(action,feedback,self.rt.gateway.clock)
        self.assertEqual(len(book.entries),1)
        eid=feedback["result"]["episodes"][0]["episode_id"];read=self.action("read_memory",{"episode_id":eid})
        source=self.rt.call(read["tool"],read["args"]);book.observe(read,source,self.rt.gateway.clock)
        entry=book.entries[-1];self.assertEqual(book.snapshot()["contents"][entry["receipt_id"]],source["result"])
        self.assertEqual(entry["structural_summary"]["target_certification"],"none; source receipt is only a structural prior")
        changed=copy.deepcopy(source);changed["result"]["source_state"]="new_version";book.observe(read,changed,self.rt.gateway.clock)
        self.assertEqual(book.entries[-1]["parent_receipt"],entry["receipt_id"])
        self.assertEqual(self.rt.gateway.used["sessions"],0);self.assertEqual(self.rt.training_ids,set())

    def test_same_response_cannot_guess_a_candidate_created_by_an_earlier_action(self):
        initial=agent_view(self.rt);self.sample();self.collect();current=agent_view(self.rt);cid=self.rt.pool[0]
        action=self.action("confirm",{"candidate_id":cid,"rationale":"确认。"})
        validate_ready_action(action,current)
        with self.assertRaisesRegex(ValueError,"before this API request"):validate_request_bindings(action,initial)
