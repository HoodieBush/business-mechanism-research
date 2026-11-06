"""Scientific counterexamples to availability-only acceptance."""
import unittest
import numpy as np
import pandas as pd
from business_mechanism.method_coverage import coverage_report, fixed_effects_design, sampling_coverage, json_pointer


class MethodCoverage(unittest.TestCase):
    def test_source_method_checks_need_real_source_receipts_and_numeric_reproduction(self):
        from pathlib import Path
        code='ratio = light_mean / baseline_mean\n'
        operations={'read':{'tool':'read_artifact','arguments':{'ref':'file:source'},'result':{'text':code}},
            'compute':{'tool':'run_python','arguments':{'code':code+'print(ratio)'},'result':{'execution':{'ok':True,'stdout':'{"ratio":1.3}'}}}}
        numeric={'component':'numeric_claim','action_ref':'compute','output_pointer':'/parsed_stdout/ratio','relation':'eq','expected':1.3}
        inspected={'component':'transformation','action_ref':'read','output_pointer':'/text','relation':'contains',
            'expected':'light_mean / baseline_mean','basis':'source_inspected',
            'justification':'The exact declared code divides the group mean by its observed baseline; this checks the declared ratio transformation.'}
        report=coverage_report([numeric,inspected],operations.__getitem__,required=['numeric_claim','transformation'],source_file=lambda _:Path('method.py'))
        self.assertTrue(report['clearance_eligible']);self.assertFalse(report['scientific_certification'])
        bad=coverage_report([numeric,inspected],operations.__getitem__,required=['numeric_claim','transformation'],source_file=lambda _:Path('metadata.json'))
        self.assertFalse(bad['clearance_eligible'])
        forged={**inspected,'component':'numeric_claim'}
        self.assertFalse(coverage_report([forged],operations.__getitem__,source_file=lambda _:Path('method.py'))['clearance_eligible'])

    def test_shared_recomputation_requires_explained_exact_executed_method(self):
        code='raw_square = raw_x ** 2\nwithin_square = raw_square - entity_mean\n'
        operation={'tool':'run_python','arguments':{'code':code},'result':{'execution':{'ok':True,'stdout':'{"within_square":4}'}}}
        checks=[{'component':component,'action_ref':'compute','output_pointer':'/parsed_stdout/within_square','relation':'eq','expected':4,
                 'method_fragment':fragment,'justification':reason}
            for component,fragment,reason in [
                ('transformation','raw_square = raw_x ** 2','This actual computation expands the raw regressor before the entity transformation.'),
                ('estimator','within_square = raw_square - entity_mean','This actual computation subtracts the entity mean from the raw expanded column.')]]
        self.assertTrue(coverage_report(checks,lambda _:operation,required=['transformation','estimator'])['clearance_eligible'])
        checks[1]['method_fragment']='invented_method_never_executed()'
        self.assertFalse(coverage_report(checks,lambda _:operation,required=['transformation','estimator'])['clearance_eligible'])

    def test_output_pointer_rejects_python_negative_indexes_and_bad_escapes(self):
        value={'rows':[[1,2]],'a/b':{'~':3}}
        self.assertEqual(json_pointer(value,'/a~1b/~0'),3)
        for pointer in ('rows/0/0','/rows/0/-1','/rows/00/0','/a~2b'):
            with self.assertRaises(ValueError):json_pointer(value,pointer)

    def test_metadata_cannot_clear_method_and_reversed_numeric_claim_fails(self):
        operations = {
            'read': {'tool': 'read_memory', 'result': {'n': 100}},
            'query': {'tool': 'query_data', 'result': {'row_count': 1, 'preview': [[19.7446, 18.7916]]}},
        }
        for ref, pointer in [('read', '/n'), ('query', '/row_count')]:
            report = coverage_report([{'component': 'claim_evidence', 'action_ref': ref,
                'output_pointer': pointer, 'relation': 'gt', 'expected': 0}], operations.__getitem__)
            self.assertFalse(report['clearance_eligible'])
        reversed_claim = coverage_report([{'component': 'claim_evidence', 'action_ref': 'query',
            'output_pointer': '/preview/0/1', 'relation': 'gt', 'expected': 19.7446}], operations.__getitem__)
        self.assertFalse(reversed_claim['clearance_eligible'])
        limited = coverage_report([{'component': 'claim_evidence', 'action_ref': 'query',
            'output_pointer': '/preview/0/0', 'relation': 'gt', 'expected': 0}], operations.__getitem__,
            required=['claim_evidence', 'estimator'])
        self.assertEqual(limited['missing_components'], ['estimator'])

    def test_polynomial_is_expanded_before_full_entity_demeaning(self):
        frame = pd.DataFrame({'entity': [1, 1, 1, 2, 2, 2], 'x': [1, 2, 4, 2, 4, 9]})
        design = fixed_effects_design(frame, ['entity'], {'x': [1, 2]})
        expected = frame.x**2-(frame.x**2).groupby(frame.entity).transform('mean')
        np.testing.assert_allclose(design['x^2'], expected)
        wrong = (frame.x-frame.x.groupby(frame.entity).transform('mean'))**2
        self.assertFalse(np.allclose(design['x^2'], wrong))
        np.testing.assert_allclose(design.groupby(frame.entity).mean().values, 0, atol=1e-14)

    def test_periodic_rowid_sample_discloses_date_selection(self):
        frame = pd.DataFrame([(e, day) for e in range(3) for day in range(90)], columns=['entity', 'date'])
        selected = frame.iloc[9::10]
        result = sampling_coverage(frame, selected, ['entity'], 'date')
        self.assertEqual(result['population_dates'], 90)
        self.assertEqual(result['sample_dates'], 9)
        self.assertEqual(result['sample_entities'], 3)
        self.assertTrue(result['dates_omitted'])
        self.assertFalse(result['randomness_certified'])


if __name__ == '__main__':
    unittest.main()
