import unittest
import numpy as np
from numeric_design import logdet_gain


class DesignTests(unittest.TestCase):
    def test_logdet_gain_rewards_unmeasured_direction(self):
        info=np.diag([100.,1.])
        covered=np.array([1.,0.]);uncovered=np.array([0.,1.])
        self.assertGreater(logdet_gain(info,uncovered),logdet_gain(info,covered))
        _,before=np.linalg.slogdet(info)
        _,after=np.linalg.slogdet(info+np.outer(uncovered,uncovered))
        self.assertAlmostEqual(logdet_gain(info,uncovered),after-before)


if __name__=="__main__":unittest.main()
