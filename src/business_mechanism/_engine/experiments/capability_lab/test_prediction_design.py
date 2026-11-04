import copy
import json
import unittest

import numpy as np

from choice_world import ChoiceLab,ChoiceWorld
from prediction_design import integrated_reduction,plan_prediction,public_basis,whiten
from semantic_compile import compile_structured


class PredictionDesignTests(unittest.TestCase):
    def test_variance_gain_matches_explicit_covariance_update(self):
        info=np.array([[3.,.2],[.2,2.]])
        moment=np.array([[1.,.3],[.3,.7]])
        rows=np.array([[1.,0.],[0.,1.],[1.,1.]])
        before=np.trace(np.linalg.solve(info,moment))
        gains=integrated_reduction(info,moment,rows,weight=2)
        for row,gain in zip(rows,gains):
            after=np.trace(np.linalg.solve(info+2*np.outer(row,row),moment))
            self.assertAlmostEqual(gain,before-after,places=12)
            self.assertGreaterEqual(gain,0)

    def test_whitening_removes_redundancy_without_changing_function_space(self):
        x=np.array([[1.,0.],[1.,1.],[1.,2.],[1.,3.]])
        redundant=np.column_stack((x,x[:,1],3*x[:,0]-x[:,1]))
        z,_=whiten(x);r,_=whiten(redundant)
        self.assertEqual(z.shape,r.shape)
        np.testing.assert_allclose(z@z.T,r@r.T,atol=1e-11)
        np.testing.assert_allclose(z.T@z/len(z),np.eye(z.shape[1]),atol=1e-11)

    def test_physical_role_rename_does_not_change_public_design(self):
        lab=ChoiceLab(ChoiceWorld(3401),max_cost=200)
        source=lab.public_catalog("source");lab.call("open_transfer",{})
        adaptation=lab.public_catalog("adaptation")
        patterns=compile_structured(source+adaptation)["role_patterns"]
        for arm in ([],[source[0]["id"]]):
            lab.call("experiment",{"assortment":arm,"n":400,"stage":"source","site":"00",
                "verified_supply":True,"verified_meter":True,"prediction":.3,"rationale":"仅检查公开参数表示不变性。"})
        renamed=copy.deepcopy(patterns);renamed["portable_container"]=renamed.pop("carrying")
        catalogs=json.dumps({"source":source,"adaptation":adaptation},sort_keys=True)
        d,z,_,meta=public_basis(json.dumps(patterns,sort_keys=True),catalogs)
        rd,rz,_,rmeta=public_basis(json.dumps(renamed,sort_keys=True),catalogs)
        self.assertEqual(d,rd);self.assertEqual(meta["public_rank"],rmeta["public_rank"])
        self.assertLess(meta["public_rank"],meta["public_columns"])
        np.testing.assert_allclose(z@z.T,rz@rz.T,atol=1e-9)
        for criterion in ("i","d"):
            a=plan_prediction(lab,{"role_patterns":patterns,"expression":.3},criterion)
            b=plan_prediction(lab,{"role_patterns":renamed,"expression":.3},criterion)
            self.assertEqual((a["stage"],a["site"],a["assortment"]),(b["stage"],b["site"],b["assortment"]))
            self.assertAlmostEqual(a["design_diagnostics"]["gain"],b["design_diagnostics"]["gain"],places=8)


if __name__=="__main__":unittest.main()
