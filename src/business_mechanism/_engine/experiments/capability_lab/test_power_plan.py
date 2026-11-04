import unittest
from power_plan import normal_paired_power,paired_clusters


class PowerPlanTests(unittest.TestCase):
    def test_noncentral_t_power_controls_null_and_increases_with_information(self):
        self.assertAlmostEqual(normal_paired_power(0,.1,30,.025),.025,places=10)
        self.assertGreater(normal_paired_power(.02,.1,128,.025),normal_paired_power(.02,.1,32,.025))
        self.assertGreater(normal_paired_power(.05,.1,32,.025),normal_paired_power(.02,.1,32,.025))

    def test_seed_is_unit_and_failure_cannot_be_zero_loss(self):
        rows=[]
        for seed in (1,2):
            for family in ("threeway","null"):
                for method in ("a","b"):
                    failed=seed==1 and family=="threeway" and method=="a"
                    rows.append({"strategy":method,"private_configuration":{"seed":seed,"family":family,"fault":"none","fact_mode":"structured"},
                        "status":"missing_result" if failed else "finished","private_score":{"heldout_effect_rmse":.1 if method=="a" else .2}})
        result=paired_clusters(rows,"a","b")
        self.assertEqual(result["cluster_count"],2)
        self.assertEqual(result["failed_or_missing_method_runs"],1)
        self.assertAlmostEqual(result["seed_clusters"][0]["mean_a_minus_b"],.85)
        self.assertEqual(result["seed_clusters"][0]["contexts"],2)
        self.assertAlmostEqual(result["seed_clusters"][1]["mean_a_minus_b"],-.1)


if __name__=="__main__":unittest.main()
