import copy
import unittest

from choice_world import ChoiceWorld
from research_runtime import ResearchRuntime
from temporal_lab import TemporalLab


class ScientificBundleTests(unittest.TestCase):
    def runtime(self):return ResearchRuntime(TemporalLab(ChoiceWorld(98,"null"),"interruptions"))
    def designs(self,rt):return [{"stage":"source","site":"00","assortment":[] if i==0 else [rt.initial["catalog"][i]["id"]],"n":400} for i in range(3)]
    def test_sample_bundle_matches_explicit_primitives_and_charges_all_actions(self):
        a=self.runtime();b=self.runtime();args={"candidate_id":a.initial_candidate,"designs":self.designs(a),"rationale":"共同自选条件。"}
        a.call("sample",args);a.call("collect",{"until":"all","repair":True,"refit":True,"assess":False})
        f=b.call("sample_and_analyze",args|{"repair":True})
        self.assertTrue(f["ok"]);self.assertEqual((a.calls,b.calls),(2,3));self.assertEqual(a.gateway.used,b.gateway.used)
        self.assertEqual(a.gateway.public_state()["mature_evidence"],b.gateway.public_state()["mature_evidence"])
        self.assertEqual(a.registry[a.pool[0]]["model"],b.registry[b.pool[0]]["model"])
        self.assertEqual([t["tool"] for t in f["result"]["bundle_trace"]],["sample","collect"])

    def test_confirmation_bundle_never_fits_or_revises_its_new_checks(self):
        rt=self.runtime();rt.call("sample_and_analyze",{"candidate_id":rt.initial_candidate,"designs":self.designs(rt),"rationale":"新数据。","repair":True})
        training=rt.training_ids.copy();before=copy.deepcopy(rt.registry);cid=rt.pool[0]
        f=rt.call("confirm_and_analyze",{"candidate_id":cid,"rationale":"独立新确认。","repair":True})
        self.assertTrue(f["ok"]);self.assertEqual(rt.training_ids,training);self.assertEqual(rt.registry,before);self.assertEqual(rt.revisions,0)
        c=rt.checks[0];self.assertEqual(c["result"]["n"],1600);self.assertFalse(set(c["result"]["experiment_ids"])&training)
        self.assertFalse(c["released"]);self.assertFalse(rt.closed);self.assertEqual(rt.calls,6)

    def test_illegal_condition_and_insufficient_bundle_action_capacity_are_atomic(self):
        rt=self.runtime();args={"candidate_id":rt.initial_candidate,"designs":self.designs(rt),"rationale":"条件。","repair":True}
        args["designs"][0]["site"]="10";f=rt.call("sample_and_analyze",args)
        self.assertFalse(f["ok"]);self.assertEqual(rt.jobs,{});self.assertEqual(rt.gateway.used["sessions"],0)
        args["designs"][0]["site"]="00";rt.max_calls=rt.calls+2;f=rt.call("sample_and_analyze",args)
        self.assertFalse(f["ok"]);self.assertEqual(rt.jobs,{})
