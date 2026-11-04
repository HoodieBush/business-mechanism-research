import json
from pathlib import Path
import tempfile
import unittest
from analyze_results import read_runs,summarize


class DenominatorTests(unittest.TestCase):
    def test_missing_task_stays_in_denominator_without_zero_loss_imputation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            tasks=[{"seed":1,"family":"null","fault":"none","strategy":strategy}
                   for strategy in ("hybrid_frontier","symbolic_dopt")]
            (path/"manifest.json").write_text(json.dumps({"planned_tasks":tasks}))
            (path/"one.json").write_text(json.dumps({"strategy":"hybrid_frontier","status":"execution_failure",
                "private_configuration":{"seed":1,"family":"null","fault":"none"}}))
            rows=read_runs(path);summary=summarize(rows)
        self.assertEqual(len(rows),2)
        self.assertEqual(sum(s["total"] for s in summary),2)
        self.assertEqual({r["status"] for r in rows},{"execution_failure","missing_result"})
        self.assertTrue(all(s["heldout_effect_rmse_conditional_on_finished"] is None for s in summary))


if __name__=="__main__":unittest.main()
