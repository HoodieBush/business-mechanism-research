import copy
import unittest

from choice_world import ChoiceWorld
from lab import predict
from public_fitting import fit_public_candidate
from semantic_compile import compile_structured
from temporal_lab import TemporalLab,digest
from temporal_plan import register_plan


def action(lab,arm=(),n=400):
    return {"stage":"source","site":"00","assortment":list(arm),"n":n,
        "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"新会话检验常数假设。"}


class TemporalTests(unittest.TestCase):
    def setUp(self):
        self.lab=TemporalLab(ChoiceWorld(91,"threeway"))
        self.model={"role_patterns":compile_structured(self.lab.public_catalog("source"))["role_patterns"],"expression":.3}
        self.args={"role_patterns":self.model["role_patterns"],"expression":"b","parameters":{"b":[.3,.05,.95]}}

    def submit(self,lab=None,arm=(),n=400):
        lab=lab or self.lab
        return lab.call("submit_experiment",{"plan":register_plan(lab,self.model,action(lab,arm,n),"constant")})

    def test_future_private_outcomes_do_not_change_views_or_fits(self):
        ack=self.submit();before=copy.deepcopy(self.lab.public_state())
        self.assertNotIn("observed_sales",str(before));self.assertEqual(self.lab.verified_observations(),[])
        self.lab._jobs[ack["job_id"]]["_private_result"]["observed_sales"]=399
        self.assertEqual(before,self.lab.public_state());self.assertEqual(self.lab.verified_observations(),[])
        with self.assertRaises(ValueError):self.lab.call("fit_candidate",self.args)
        self.assertFalse(any("observed_sales" in str(e["payload"]) for e in self.lab.events))
        self.lab.call("await_next",{})
        row,k=self.lab.verified_observations()[0]
        self.assertEqual(k,399);self.assertLess(row["occurred_at"],row["available_at"])
        self.assertLessEqual(row["available_at"],self.lab.clock)

    def test_registration_is_before_sampling_and_hash_matches(self):
        ack=self.submit();event=self.lab.events[0]
        self.assertEqual(event["kind"],"plan_registered")
        self.assertEqual(event["used"]["sessions"],0)
        self.assertEqual(ack["plan_id"],digest({"registered_at":0,"job_id":0,"plan":event["payload"]["plan"]}))
        frozen=event["payload"]["plan"];self.assertEqual(frozen["action"]["prediction"],predict(frozen["model"],self.lab.public_catalog("source"),[],(0,0)))

    def test_malformed_plan_and_capacity_do_not_start_unregistered_jobs(self):
        p=register_plan(self.lab,self.model,action(self.lab),"constant")
        for change in ({"n":True},{"assortment":["missing"]},{"prediction":.8},{"verified_meter":False}):
            bad=copy.deepcopy(p);bad["action"].update(change)
            with self.assertRaises(ValueError):self.lab.call("submit_experiment",{"plan":bad})
        self.assertEqual(self.lab.used["sessions"],0);self.assertEqual(self.lab._jobs,{})
        self.assertFalse(any(e["kind"]=="plan_registered" for e in self.lab.events))
        for _ in range(3):self.submit()
        with self.assertRaises(ValueError):self.submit()
        self.assertEqual(len(self.lab._jobs),3);self.assertEqual(self.lab.used["sessions"],1200)

    def test_execution_repair_is_same_plan_and_no_failed_samples(self):
        lab=TemporalLab(ChoiceWorld(91,"threeway"),profile="interruptions")
        self.submit(lab);before=lab.used.copy();failed=self.submit(lab)
        self.assertEqual(failed["status"],"execution_failed");self.assertEqual(lab.used["sessions"],before["sessions"])
        self.assertEqual(lab.used["cost"],before["cost"]+1)
        retried=lab.call("retry_execution",{"job_id":failed["job_id"]})
        self.assertEqual(failed["plan_id"],retried["plan_id"]);self.assertEqual(lab.used["sessions"],800)
        with self.assertRaises(ValueError):lab.call("retry_execution",{"job_id":failed["job_id"]})
        self.assertEqual(len([e for e in lab.events if e["kind"]=="plan_registered"]),2)

    def test_reconciliation_preserves_old_record_and_no_extra_cohort(self):
        lab=TemporalLab(ChoiceWorld(91,"threeway"),profile="interruptions")
        for _ in range(4):
            ack=self.submit(lab)
            if ack["status"]=="execution_failed":lab.call("retry_execution",{"job_id":ack["job_id"]})
            while lab.public_state()["pending_jobs"]:lab.call("await_next",{})
        bad=lab.public_state()["unverified_jobs"][0];eid=bad["experiment_id"]
        self.assertNotIn(eid,[r["experiment_id"] for r,_ in lab.verified_observations()]);before=lab.used.copy()
        lab.call("reconcile_measurement",{"job_id":bad["job_id"]})
        self.assertNotIn(eid,[r["experiment_id"] for r,_ in lab.verified_observations()])
        lab.call("await_next",{});fixed=next(r for r,_ in lab.verified_observations() if r["experiment_id"]==eid)
        self.assertEqual(fixed["evidence_version"],2);self.assertEqual(fixed["occurred_at"],bad["measurement"]["occurred_at"])
        self.assertEqual(lab.used["sessions"],before["sessions"]);self.assertEqual(lab.used["arms"],before["arms"])
        old=next(e["payload"] for e in lab.events if e["kind"]=="measurement_received" and e["payload"]["experiment_id"]==eid)
        self.assertFalse(old["verified_meter"]);self.assertGreater(fixed["observed_sales"],old["observed_sales"])

    def test_training_scope_excludes_fresh_confirmation_and_matches_public_fit(self):
        self.submit();self.lab.call("await_next",{});self.lab.set_fit_scope([0])
        self.submit(n=800);self.lab.call("await_next",{})
        fit=self.lab.call("fit_candidate",self.args)
        direct=fit_public_candidate(self.args,self.lab.verified_observations(),{"source":self.lab.public_catalog("source")})
        self.assertEqual(fit["model"],direct["model"]);self.assertEqual([r["experiment_id"] for r in fit["residuals"]],[0])
        self.assertEqual(len(self.lab.public_state()["mature_evidence"]),2)
        with self.assertRaises(ValueError):self.lab.set_fit_scope([999])

    def test_deadline_does_not_deliver_future_outcomes(self):
        lab=TemporalLab(ChoiceWorld(91,"threeway"),deadline=1)
        self.submit(lab,n=800);lab.call("await_next",{})
        self.assertEqual(lab.clock,1);self.assertEqual(lab.verified_observations(),[])
        with self.assertRaises(ValueError):lab.call("await_next",{})
        with self.assertRaises(ValueError):lab.call("finish",{"model":self.model,"claims":"已确认。"})
        lab.call("finish",{"model":self.model,"claims":"截止前没有回执，结果未决。","unresolved":True})
        self.assertTrue(lab.call("deployment_catalog",{}))
        with self.assertRaises(ValueError):lab.call("fit_candidate",self.args)

    def test_out_of_order_delivery_uses_only_available_results(self):
        ids=[p["id"] for p in self.lab.public_catalog("source")]
        # Design-only delays differ; choose three legal alternatives.
        plans=[register_plan(self.lab,self.model,action(self.lab,a),"constant") for a in ([],[ids[0]],[ids[1]])]
        lags=[1+int(digest({"stage":"source","site":"00","n":400,"assortment":sorted(p["action"]["assortment"])})[:8],16)%4 for p in plans]
        order=sorted(range(3),key=lambda i:lags[i],reverse=True)
        for i in order:self.lab.call("submit_experiment",{"plan":plans[i]})
        self.lab.call("await_next",{});mature=self.lab.public_state()["mature_evidence"]
        self.assertTrue(mature);self.assertTrue(all(r["available_at"]==self.lab.clock for r in mature))
        if len(set(lags))>1:self.assertNotIn(0,[r["experiment_id"] for r in mature])
        self.assertEqual(len(self.lab.verified_observations()),len(mature))

    def test_budget_rejection_is_atomic_before_registration(self):
        self.lab._core._reserve(cost=self.lab.limits["cost"])
        with self.assertRaises(ValueError):self.submit()
        self.assertEqual(self.lab._jobs,{})
        self.assertEqual(self.lab.used["sessions"],0)
        self.assertFalse(any(e["kind"]=="plan_registered" for e in self.lab.events))
        self.assertEqual(self.lab.events[-1]["kind"],"tool_failure")


if __name__=="__main__":unittest.main()
