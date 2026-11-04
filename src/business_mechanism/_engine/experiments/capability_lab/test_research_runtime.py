import copy
import unittest

from choice_world import ChoiceLab,ChoiceWorld
from conditional_memory import archive,export_episode
from confirmation import assess
from lab import compile_expression
from mechanism_state import card
from research_runtime import ResearchRuntime
from semantic_compile import compile_structured
from temporal_lab import TemporalLab,digest


def public_archive():
    lab=ChoiceLab(ChoiceWorld(97,"null"));facts=compile_structured(lab.public_catalog("source"))
    model={"role_patterns":facts["role_patterns"],"expression":compile_expression("min(.95,max(.05,.3))")}
    for n in (400,800,800):
        lab.call("experiment",{"stage":"source","site":"00","assortment":[],"n":n,"verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"公开记忆测试源。"})
    rows=[copy.deepcopy(r["result"]) for r in lab.receipts[1:]]
    check=assess(sum(r["observed_sales"] for r in rows),1600,.3,max_checks=6)
    check.update(round=0,experiment_id=1,experiment_ids=[1,2],cohort_results=rows,design={"stage":"source","site":"00","assortment":[]})
    versions=[{"phase":"confirmation_model_frozen","round":0,"model":model,"training_evidence_ids":[0]}]
    return archive([export_episode(lab.public(),facts,lab.events,versions,[check],lab.used)])


class RuntimeTests(unittest.TestCase):
    def setUp(self):self.rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null")),public_archive())
    def call(self,tool,args={}):return self.rt.call(tool,args,"测试科学动作。","公开证据边界。")
    def sample(self,n=400):
        return self.call("sample",{"candidate_id":self.rt.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":[],"n":n}],"rationale":"新样本检验。"})
    def collect(self,refit=True,analyse=False):return self.call("collect",{"until":"all","repair":True,"refit":refit,"assess":analyse})
    def bad_model(self):
        return self.call("propose_model",{"expression":"min(.95,max(.05,b))","parameters":{"b":[.9,.89,.91]},"rationale":"刻意错误模型用于反驳与训练依赖边界。"})["result"]["candidate_id"]

    def test_pending_counts_never_enter_runtime_training(self):
        self.assertTrue(self.sample()["ok"]);self.assertFalse(self.call("fit_pool")["ok"])
        self.assertEqual(self.rt.training_ids,set());self.assertEqual(self.rt.gateway.verified_observations(),[])
        self.collect();self.assertEqual(self.rt.training_ids,{0})
        self.assertTrue(self.rt.pool);self.assertTrue(all(self.rt.registry[c]["training_evidence_ids"]==[0] for c in self.rt.pool))

    def test_received_catalog_can_be_reread_after_sampling_without_refreezing_models(self):
        first=self.call("open_adaptation")["result"]
        self.sample();before=copy.deepcopy(self.rt.registry);facts=copy.deepcopy(self.rt.facts);used=copy.deepcopy(self.rt.gateway.used)
        again=self.call("open_adaptation")
        self.assertTrue(again["ok"]);self.assertEqual(again["result"],first)
        self.assertEqual(self.rt.registry,before);self.assertEqual(self.rt.facts,facts);self.assertEqual(self.rt.gateway.used,used);self.assertEqual(self.rt.training_ids,set())
        other=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null")))
        other.call("sample",{"candidate_id":other.initial_candidate,"designs":[{"stage":"source","site":"00","assortment":[],"n":400}],"rationale":"首采样。"})
        self.assertFalse(other.call("open_adaptation",{})["ok"])

    def test_design_service_can_bootstrap_with_no_received_or_queued_evidence(self):
        suggested=self.call("suggest_design",{"candidate_id":self.rt.initial_candidate})
        self.assertTrue(suggested["ok"]);d=suggested["result"]["design"]
        self.assertEqual((d["stage"],d["site"],d["assortment"]),("source","00",[]))
        queued=self.call("sample_frontier",{"candidate_id":self.rt.initial_candidate,"count":3,"rationale":"零样本公共覆盖。"})
        self.assertTrue(queued["ok"]);self.assertEqual(self.rt.training_ids,set())

    def test_unknown_confirmation_and_capacity_failure_do_not_consume_slots(self):
        cid=self.rt.initial_candidate
        bad=self.call("confirm",{"candidate_id":cid,"design":{"stage":"source","site":"00","assortment":["unknown"]},"rationale":"非法配置。"})
        self.assertFalse(bad["ok"]);self.assertEqual(self.rt.checks,[]);self.assertEqual(self.rt.versions,[])
        self.sample();before=copy.deepcopy(self.rt.gateway.used)
        result=self.call("sample_frontier",{"candidate_id":cid,"count":3,"rationale":"容量边界。"})
        self.assertFalse(result["ok"]);self.assertEqual(self.rt.gateway.used["sessions"],before["sessions"])

    def test_confirmation_is_excluded_until_actual_refutation_release(self):
        self.sample();self.collect();cid=self.bad_model()
        check=self.call("confirm",{"candidate_id":cid,"design":{"stage":"source","site":"00","assortment":[]},"rationale":"新独立会话确认。"})
        self.assertTrue(check["ok"]);self.assertEqual(self.call("assess_checks")["result"]["completed_checks"],[])
        self.collect(refit=False,analyse=True)
        self.assertEqual(self.rt.training_ids,{0});self.assertEqual(self.rt.checks[0]["result"]["state"],"contradicted")
        self.call("fit_pool");self.assertTrue(all(self.rt.registry[c]["training_evidence_ids"]==[0] for c in self.rt.pool))
        released=self.call("reopen_research",{"check_id":"K000","rationale":"真实条件反驳后重新研究。","refit":True})
        self.assertTrue(released["ok"]);self.assertEqual(self.rt.training_ids,{0,1,2})
        self.assertFalse(self.call("reopen_research",{"check_id":"K000","rationale":"不能重复释放。","refit":True})["ok"])

    def test_old_checks_do_not_certify_revised_model(self):
        self.sample();self.collect();cid=self.bad_model()
        self.call("confirm",{"candidate_id":cid,"rationale":"新独立条件。"});self.collect(refit=False,analyse=True)
        self.call("reopen_research",{"check_id":"K000","rationale":"反驳后释放。","refit":True})
        best=self.rt.pool[0]
        done=self.call("finish",{"candidate_id":best,"claims":"修订后的模型尚无新确认。","unresolved":True,"stop_reason":"测试终止。"})
        self.assertTrue(done["ok"]);self.assertEqual(done["result"]["mechanism_card"]["state"],"pending_confirmation")
        self.assertEqual(done["result"]["mechanism_card"]["conditional_claims"],[])

    def test_scope_changed_memory_requires_review_and_target_only_refit(self):
        self.rt=ResearchRuntime(TemporalLab(ChoiceWorld(98,"null",retail_price=10.)),public_archive())
        retrieved=self.call("retrieve_memory")["result"];ep=retrieved["episodes"][0]
        self.assertIn("public_context_changed",ep["scope_flags"]);self.assertFalse(self.rt.memory.entries[0]["eligible"])
        review=self.call("review_memory",{"episode_ids":[ep["episode_id"]],"usage":"structure_refit_only","rationale":"价格变化使旧参数可疑；只保留结构并使用目标数据重估。"})
        self.assertTrue(review["ok"]);self.assertFalse(review["result"]["source_counts_pooled"])
        self.sample();self.collect()
        mem=[self.rt.registry[c] for c in self.rt.pool if self.rt.registry[c]["origin"]=="conditional_memory"]
        self.assertTrue(mem);self.assertTrue(all(c["training_evidence_ids"]==[0] and c["target_training_ids"]==[0] for c in mem))
        self.assertEqual(self.rt.gateway.used["sessions"],400)

    def test_unconfirmed_finish_cannot_claim_resolved_and_is_atomic(self):
        before=copy.deepcopy(self.rt.versions)
        refused=self.call("finish",{"candidate_id":self.rt.initial_candidate,"claims":"已证明。","unresolved":False,"stop_reason":"足够。"})
        self.assertFalse(refused["ok"]);self.assertEqual(self.rt.versions,before);self.assertIsNone(self.rt.final)
        done=self.call("finish",{"candidate_id":self.rt.initial_candidate,"claims":"没有独立确认，保持未决。","unresolved":True,"stop_reason":"早停。"})
        self.assertTrue(done["ok"]);self.assertEqual(self.rt.gateway.used["sessions"],0)
        before=copy.deepcopy(self.rt.gateway.events);self.rt.state();self.assertEqual(before,self.rt.gateway.events)

    def test_freely_proposed_structure_is_safe_and_old_versions_immutable(self):
        self.sample();self.collect();old=copy.deepcopy(self.rt.registry)
        proposed=self.call("propose_model",{"expression":"sigmoid(b+g*heat*utensils)","parameters":{"b":[-.8,-6.,6.],"g":[.2,-6.,6.]},"rationale":"可操作竞争关系。"})
        self.assertTrue(proposed["ok"])
        unsafe=self.call("propose_model",{"expression":"__import__('os').system('x')","parameters":{"b":[0.,-1.,1.]},"rationale":"危险。"})
        self.assertFalse(unsafe["ok"])
        for cid,candidate in old.items():self.assertEqual(candidate,self.rt.registry[cid])

    def test_hash_chained_event_log_and_independence_ids(self):
        self.sample();self.collect()
        previous=None
        for event in self.rt.events:
            body={k:v for k,v in event.items() if k!="event_hash"}
            self.assertEqual(event["previous_hash"],previous);self.assertEqual(event["event_hash"],digest(body));previous=event["event_hash"]
        ids=[e["independence_group"] for e in self.rt.objects["evidence"]]
        self.assertEqual(ids,["cohort-0"])

    def test_structure_proposal_tracks_all_exposed_confirmation_data(self):
        self.sample();self.collect();cid=self.bad_model()
        self.call("confirm",{"candidate_id":cid,"rationale":"独立检查。"});self.collect(refit=False,analyse=True)
        new=self.call("propose_model",{"expression":"sigmoid(b)","parameters":{"b":[-.8,-6.,6.]},"rationale":"看过反馈后提出新解释。"})["result"]["candidate_id"]
        candidate=self.rt.registry[new]
        self.assertEqual(candidate["training_evidence_ids"],[0])
        self.assertEqual(candidate["information_evidence_ids"],[0,1,2])

    def test_seen_checks_do_not_certify_even_an_identical_reconstructed_program(self):
        self.sample();self.collect();cid=self.bad_model()
        self.call("confirm",{"candidate_id":cid,"rationale":"独立检查。"});self.collect(refit=False,analyse=True)
        model=self.rt.registry[cid]["model"];versions=copy.deepcopy(self.rt.versions)
        before=card(model,self.rt.facts["ontology"],versions,[self.rt.checks[0]["result"]])
        self.assertEqual(before["state"],"refuted_in_listed_conditions")
        versions.append({"phase":"confirmation_model_frozen","round":1,"model":copy.deepcopy(model),"training_evidence_ids":[0],"information_evidence_ids":[0,1,2]})
        after=card(model,self.rt.facts["ontology"],versions,[self.rt.checks[0]["result"]])
        self.assertEqual(after["state"],"pending_confirmation");self.assertEqual(after["conditional_claims"],[])


if __name__=="__main__":unittest.main()
