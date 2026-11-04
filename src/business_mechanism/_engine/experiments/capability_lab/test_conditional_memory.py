import copy
import math
import unittest

from choice_world import ChoiceLab,ChoiceWorld
from conditional_memory import ConditionalMemory,archive,coefficient_template,digest,export_episode
from confirmation import assess
from lab import compile_expression,evaluate
from operating_eval import evaluate as operating_evaluate
from semantic_compile import compile_structured
from audit_memory import audit_memory
from run_memory_withdrawal_replay import replay


def fixture():
    lab=ChoiceLab(ChoiceWorld(91));public=lab.public();catalog=lab.public_catalog("source")
    facts=compile_structured(catalog)
    model={"role_patterns":facts["role_patterns"],"expression":"sigmoid(-0.8472978603872037+1.2*max(items-2,0))"}
    events=[]
    for i,(n,k) in enumerate([(400,120),(800,240),(800,240)]):
        r={"experiment_id":i,"stage":"source","site":"00","assortment":[],"n":n,
            "observed_sales":k,"verified_supply":True,"verified_meter":True,"frozen_prediction":.3}
        events.append({"request":{"tool":"experiment","args":{}},"response":r})
    checks=[assess(480,1600,.3,max_checks=4)|{"round":0,"experiment_id":1,"experiment_ids":[1,2],
        "design":{"stage":"source","site":"00","assortment":[]}}]
    versions=[{"phase":"confirmation_model_frozen","round":0,"model":model,"training_evidence_ids":[0]}]
    used={"sessions":2000,"arms":3,"cost":15}
    return public,facts,events,versions,checks,used


class ConditionalMemoryTests(unittest.TestCase):
    def test_export_excludes_private_and_retains_public_provenance(self):
        args=list(fixture());args[0]["private_score"]={"secret_answer":True};args[0]["seed"]=999
        episode=export_episode(*args)
        self.assertNotIn("private_score",str(episode));self.assertNotIn("secret_answer",str(episode))
        self.assertEqual(len(episode["conditional_claims"]),1)
        self.assertEqual(len(episode["historical_checks"]),1)
        self.assertEqual(len(episode["conditional_claims"][0]["dependencies"]),2)
        changed=list(fixture());changed[4]=copy.deepcopy(changed[4]);changed[4][0]["state"]="contradicted"
        with self.assertRaisesRegex(ValueError,"public counts"):export_episode(*changed)

    def test_coefficient_adapter_preserves_feature_constants_and_clamp(self):
        _,facts,*_=fixture()
        for expr in ["sigmoid(-1.1+0.8*max(items-2,0))","min(0.95,max(0.05,0.3+(-0.2)*max(items-2,0)))"]:
            source={"expression":expr,"role_patterns":facts["role_patterns"]};t=coefficient_template(source)
            tree=compile_expression(t["expression"],{k:v[0] for k,v in t["parameters"].items()})
            original=compile_expression(expr)
            for items in range(7):self.assertAlmostEqual(evaluate(tree,{"items":items}),evaluate(original,{"items":items}))
            self.assertEqual(len(t["parameters"]),2)

    def test_context_gate_does_not_promote_matching_source_to_target_support(self):
        args=fixture();value=archive([export_episode(*args)]);public,facts=args[:2]
        matching=ConditionalMemory(value,public,facts)
        self.assertTrue(matching.entries[0]["eligible"])
        self.assertEqual(matching.trace()["retrieval"][0]["target_evidence_status"],"unconfirmed")
        changed=copy.deepcopy(public);changed["operating_objective"]["retail_price"]=10.
        guarded=ConditionalMemory(value,changed,facts)
        self.assertFalse(guarded.entries[0]["eligible"])
        self.assertIn("public_context_changed",guarded.trace()["retrieval"][0]["scope_flags"])
        self.assertTrue(ConditionalMemory(value,changed,facts,"unscoped").entries[0]["eligible"])

    def test_evidence_retraction_marks_dependents_stale_without_erasure(self):
        args=fixture();value=archive([export_episode(*args)]);memory=ConditionalMemory(value,*args[:2])
        eid=value["episodes"][0]["conditional_claims"][0]["dependencies"][0]
        before=copy.deepcopy(memory.archive);update=memory.invalidate_evidence(eid,"公开计数回执更正，需复核")
        self.assertEqual(len(update["affected_episodes"]),1)
        self.assertFalse(memory.entries[0]["eligible"])
        self.assertEqual(memory.trace()["retrieval"][0]["status"],"stale_requires_source_review")
        self.assertEqual(memory.archive,before)
        with self.assertRaisesRegex(ValueError,"unknown source"):memory.invalidate_evidence("not-an-evidence-id","x")

    def test_tampered_archive_and_extra_private_fields_rejected(self):
        args=fixture();value=archive([export_episode(*args)])
        bad=copy.deepcopy(value);bad["episodes"][0]["source_state"]="invented"
        with self.assertRaisesRegex(ValueError,"hash mismatch"):ConditionalMemory(bad,*args[:2])
        e=copy.deepcopy(value["episodes"][0]);e["private_score"]=1;e["episode_id"]=digest({k:v for k,v in e.items() if k!="episode_id"})
        with self.assertRaisesRegex(ValueError,"public episode fields"):ConditionalMemory(archive([e]),*args[:2])

    def test_source_counts_never_enter_target_fit_or_rank_identification(self):
        args=fixture();value=archive([export_episode(*args)]);lab=ChoiceLab(ChoiceWorld(92))
        facts=compile_structured(lab.public_catalog("source"));memory=ConditionalMemory(value,lab.public(),facts)
        lab.call("experiment",{"stage":"source","site":"00","assortment":[],"n":400,
            "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"目标独立数据"})
        self.assertEqual(memory.fit_candidates(lab),[]) # hinge is unidentified here
        lab.call("experiment",{"stage":"source","site":"00","assortment":[p["id"] for p in lab.public_catalog("source")],"n":400,
            "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"目标独立数据"})
        fitted=memory.fit_candidates(lab)
        self.assertEqual(len(fitted),1)
        self.assertEqual(fitted[0]["target_training_ids"],[0,1])
        self.assertAlmostEqual(fitted[0]["bic"]-fitted[0]["deviance"],2*math.log(800))
        self.assertEqual(lab.used["sessions"],800)
        self.assertFalse(memory.trace()["target_likelihood_uses_source_counts"])

    def test_public_price_change_affects_demand_and_operating_contract(self):
        original=ChoiceWorld(93);explicit=ChoiceWorld(93,retail_price=8.);changed=ChoiceWorld(93,retail_price=10.)
        for external in [(0,0),(1,1)]:
            self.assertEqual(original.probability("source",[],external),explicit.probability("source",[],external))
            self.assertLess(changed.probability("source",[],external),original.probability("source",[],external))
        lab=ChoiceLab(changed);self.assertEqual(lab.public()["operating_objective"]["retail_price"],10.)
        facts=compile_structured(sum((changed.catalogs[s] for s in ("source","adaptation","heldout")),[]))
        model={"expression":.3,"role_patterns":facts["role_patterns"]}
        self.assertEqual(operating_evaluate(changed,model,model)["economics"]["retail_price"],10.)

    def test_actual_trace_audit_rejects_wrong_dependency_and_shared_cost(self):
        args=fixture();e=export_episode(*args);value=archive([e]);memory=ConditionalMemory(value,*args[:2])
        memory.record_target_version({"model":args[3][0]["model"],"origin":"conditional_memory",
            "memory_episode_refs":[e["episode_id"]]},[0],0,args[4])
        row={"status":"finished","legal_input":args[0],"adaptation_physical_facts":args[1],"events":args[2],
            "research_versions":args[3],"confirmations":args[4],"design_decisions":[],"memory_trace":memory.trace(),
            "public_memory_export":e,"private_score":{"economics":args[0]["operating_objective"]}}
        self.assertEqual(audit_memory(row,value)["status"],"passed")
        bad=copy.deepcopy(row);bad["memory_trace"]["target_versions"][0]["memory_episode_refs"]=["not-an-episode"]
        self.assertIn("selected_ineligible_memory_episode",audit_memory(bad,value)["issues"])
        bad=copy.deepcopy(row);bad["memory_trace"]["source_acquisition_cost_shared"]["sessions"]+=400
        self.assertIn("wrong_shared_source_cost",audit_memory(bad,value)["issues"])
        result=replay(row,value)
        self.assertEqual(result["status"],"passed")
        self.assertEqual(result["after"]["target_versions"][0]["state"],"supported_in_target_conditions")
        self.assertEqual(result["after"]["target_versions"][0]["source_dependency_state"],"stale_requires_review")


if __name__=="__main__":unittest.main()
