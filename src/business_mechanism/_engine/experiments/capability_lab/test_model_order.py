"""Roundoff must not decide an observational tie with different extrapolation."""
import unittest
from lab import model_with
from model_order import candidate_key


class OrderingTests(unittest.TestCase):
    def test_numerical_tie_prefers_smaller_program_without_origin_bias(self):
        simple={"bic":8.0,"model":model_with("0.3+0.2*max(heat,external_heat)"),"terms":["simple"],"origin":"symbolic_search"}
        complex={"bic":8.0-4e-13,"model":model_with("0.3+0.2*max(heat,external_heat)*utensils"),"terms":["complex"],"origin":"llm_proposed_structure"}
        self.assertEqual(sorted([complex,simple],key=candidate_key)[0],simple)
        complex["bic"]=7.9
        self.assertEqual(sorted([simple,complex],key=candidate_key)[0],complex)


if __name__=="__main__":unittest.main()
