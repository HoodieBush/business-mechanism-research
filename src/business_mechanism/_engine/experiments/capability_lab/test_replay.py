"""Shared evidence controls must preserve the original observation boundary."""
import unittest
from replay_evidence import ReplayEvidence
from run_openworld_replay import training_view


class ReplayTests(unittest.TestCase):
    def test_replay_excludes_unverified_and_never_exposes_truth_or_sampling(self):
        r={"experiment_id":0,"n":400,"observed_sales":120,
            "verified_supply":True,"verified_meter":False}
        event={"request":{"tool":"experiment","args":{}},"response":r}
        view=ReplayEvidence({"catalog":[{"id":"a","description":"加热"}]},[event])
        self.assertEqual(view.verified_observations(),[])
        with self.assertRaisesRegex(ValueError,"not received"):
            view.public_catalog("heldout")
        self.assertFalse(hasattr(view,"_world"))
        self.assertFalse(hasattr(view,"experiment"))
        verified={"request":{"tool":"reconcile","args":{"experiment_id":0}},
                  "response":{"verified_sales":220}}
        view=ReplayEvidence({"catalog":[]},[event,verified])
        self.assertEqual(view.verified_observations()[0][1],220)
        copy=view.verified_observations();copy[0][0]["n"]=1
        self.assertEqual(view.verified_observations()[0][0]["n"],400)

    def test_adaptation_is_in_public_dictionary_but_final_checks_are_excluded(self):
        def experiment(i,stage):
            return {"request":{"tool":"experiment","args":{}},"response":{
                "experiment_id":i,"n":400,"observed_sales":120,"stage":stage,
                "verified_supply":True,"verified_meter":True}}
        parent={"legal_input":{"catalog":[]},"events":[experiment(0,"source"),
            {"request":{"tool":"open_transfer","args":{}},"response":{"catalog":[]}},
            experiment(1,"adaptation"),experiment(2,"adaptation")],
            "research_versions":[{"phase":"confirmation_model_frozen","training_evidence_ids":[0,1]}]}
        view=training_view(parent)
        self.assertTrue(view.transfer_open)
        self.assertEqual([r["experiment_id"] for r,_ in view.verified_observations()],[0,1])
        self.assertFalse(hasattr(view,"_world"))
        with self.assertRaises(ValueError):view.public_catalog("heldout")


if __name__=="__main__":unittest.main()
