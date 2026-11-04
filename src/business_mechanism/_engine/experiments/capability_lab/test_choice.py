import copy
import itertools
import math
import unittest

import numpy as np

from lab import compile_expression,evaluate,predict
from choice_world import ChoiceLab,ChoiceWorld,economics
from confirmation import assess
from operating_eval import evaluate as operating_evaluate,optimize,order_quantity,profit_at_probability
from semantic_compile import compile_declarations,compile_structured
from symbolic import grammar,public_dictionary,search


class ChoiceTests(unittest.TestCase):
    def test_new_link_is_bounded_and_cannot_execute_python(self):
        for value in (-100.,0.,100.):
            p=evaluate(compile_expression(f"sigmoid({value})"),{})
            self.assertTrue(0<=p<=1)
        with self.assertRaises(ValueError):compile_expression("sigmoid(__import__('os'))")
        with self.assertRaises(ValueError):evaluate(compile_expression("sigmoid(1,2)"),{})

    def test_independent_generator_and_operating_samples_agree(self):
        world=ChoiceWorld(21,"threeway")
        ids=list(world.roles["source"])
        rng=np.random.default_rng(99);c=rng.random(100000);u=rng.random(100000)
        rate=float(np.mean(world.purchases("source",ids,(0,0),c,u)))
        self.assertAlmostEqual(rate,world.probability("source",ids,(0,0)),delta=.008)
        for family in ("source_joint","threeway","mixed_scope","null"):
            world=ChoiceWorld(21,family)
            for ext in itertools.product((0,1),repeat=2):
                for flags in itertools.product((0,1),repeat=len(ids)):
                    arm=[p for p,f in zip(ids,flags) if f]
                    self.assertTrue(0<world.probability("source",arm,ext)<1)

    def test_unknown_role_is_needed_but_not_revealed_as_effect(self):
        world=ChoiceWorld(3,"threeway");lab=ChoiceLab(world)
        h=next(p for p,r in world.roles["source"].items() if r["heating"] and not r["utensils"])
        u=next(p for p,r in world.roles["source"].items() if r["utensils"] and not r["heating"])
        s=next(p for p,r in world.roles["source"].items() if r["sealing"])
        p0=world.probability("source",[],(0,0))
        self.assertEqual(world.probability("source",[h,u],(0,0)),p0)
        self.assertGreater(world.probability("source",[h,u,s],(0,0)),p0+.15)
        self.assertNotIn("threeway",str(lab.public()))
        with self.assertRaises(ValueError):lab.deployment_catalog()

    def test_public_structured_fact_compilation_handles_negation(self):
        world=ChoiceWorld(3)
        catalog=sum((world.catalogs[s] for s in ("source","adaptation","heldout")),[])
        proposal=compile_structured(catalog)
        for product in catalog:
            for role,patterns in proposal["role_patterns"].items():
                matched=any(s in product["description"] for s in patterns)
                self.assertEqual(matched,product["functions"][role])

    def test_declaration_compiler_preserves_even_incorrect_semantic_labels(self):
        world=ChoiceWorld(3);catalog=world.catalogs["source"]
        declared=compile_structured(catalog)
        carrier=next(p["id"] for p in catalog if p["functions"]["carrying"])
        declared["catalog_roles"][carrier].append("heating")
        compiled=compile_declarations(declared,catalog)
        item=next(p for p in catalog if p["id"]==carrier)
        self.assertTrue(any(s in item["description"] for s in compiled["role_patterns"]["heating"]))
        self.assertFalse(item["functions"]["heating"])
        with self.assertRaises(ValueError):compile_declarations(declared,catalog,declared["ontology"]|{"heating":"changed"})

    def test_newsvendor_solution_matches_exhaustive_feasible_orders(self):
        contract=economics()
        for p in (0.,.1,.35,.7,1.):
            q=order_quantity(p,contract)
            best=max(profit_at_probability(p,j,.08,contract) for j in range(contract["stock_capacity"]+1))
            self.assertAlmostEqual(profit_at_probability(p,q,.08,contract),best,places=8)

    def test_optimizer_accounts_for_material_cost_and_slots(self):
        catalog=[{"id":"expensive","retailer_cost_per_session":1.},
                 {"id":"useful","retailer_cost_per_session":.01}]
        def probability(arm,ext):return .6 if "useful" in arm else .3
        choice=optimize(catalog,(0,0),1,probability,economics())
        self.assertEqual(choice["assortment"],["useful"])
        self.assertLessEqual(choice["order_quantity"],economics()["stock_capacity"])

    def test_insufficient_precision_is_inconclusive_not_zero_effect(self):
        self.assertEqual(assess(30,100,.3)["state"],"inconclusive")
        self.assertEqual(assess(3000,10000,.3)["state"],"supported_within_tolerance")
        self.assertEqual(assess(120,400,.6)["state"],"contradicted")

    def test_strong_grammar_allows_interactions_with_new_factors(self):
        patterns={"heating":["加热"],"utensils":["餐具"],"sealing":["密封"]}
        self.assertTrue(any("sealing" in atom and "external_heat" in atom and "utensils" in atom
                            for atom in grammar(patterns,True,all_factors=True)))

    def test_alias_committee_retains_fitted_rivals_beyond_combination_beam(self):
        lab=ChoiceLab(ChoiceWorld(31,"threeway"))
        patterns=compile_structured(lab.public_catalog("source"))["role_patterns"]
        ids=[p["id"] for p in lab.public_catalog("source")]
        for arm in ([],ids):
            lab.call("experiment",{"assortment":arm,"n":400,"stage":"source","site":"00",
                "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"合成共现数据检查观测别名保留。"})
        lab.call("open_transfer",{})
        pool=search(lab,patterns,beam=1,max_terms=1,link="logit",public_dedup=True,
                    interaction_order=4,preserve_aliases=True,max_candidates=32)
        self.assertGreater(len(pool),8)
        self.assertTrue(any("sealing" in str(r["terms"]) for r in pool))
        core=[p["id"] for p in lab.public_catalog("source") if p["functions"]["heating"] or p["functions"]["utensils"]]
        rates=[predict(r["model"],lab.public_catalog("source"),core,(0,0)) for r in pool]
        self.assertGreater(max(rates)-min(rates),.1)

    def test_deployment_facts_are_legal_only_after_freeze(self):
        lab=ChoiceLab(ChoiceWorld(31))
        with self.assertRaises(ValueError):lab.call("deployment_catalog",{})
        facts=compile_structured(lab.public_catalog("source"))
        model={"role_patterns":facts["role_patterns"],"expression":.3}
        lab.call("finish",{"model":model,"claims":"未决模型，供独立部署评价。"})
        frozen=copy.deepcopy(lab.final)
        catalog=lab.call("deployment_catalog",{})
        self.assertEqual(lab.final,frozen)
        self.assertTrue(all("functions" in p for p in catalog))
        with self.assertRaises(ValueError):lab.call("experiment",{})
        self.assertEqual(lab.events[-1]["request"]["tool"],"deployment_catalog")

    def test_operating_trajectories_conserve_inventory_and_use_frozen_relation(self):
        world=ChoiceWorld(31,"null")
        facts=compile_structured(sum(world.catalogs.values(),[]))
        model={"role_patterns":facts["role_patterns"],"expression":world.probability("heldout",[],(0,0))}
        score=operating_evaluate(world,model,copy.deepcopy(model))
        self.assertAlmostEqual(score["mean_expected_operating_regret_per_customer"],0,places=10)
        for profile in score["profiles"]:
            for day in profile["daily_trajectories"]:
                for name in ("policy","oracle"):
                    row=day[name]
                    self.assertEqual(row["opening"],row["sales"]+row["ending"])
                    self.assertEqual(row["demand"],row["sales"]+row["lost_sales"])
        with self.assertRaises(ValueError):operating_evaluate(world,model,model|{"expression":.4})


if __name__=="__main__":unittest.main()
