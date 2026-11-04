"""Rerun the five actual controls plus explicit-restoration transition."""
import argparse
import json
import os
from pathlib import Path
import unittest
from ..common import write_json
from ..review.workflow_20261025.quiescent_budget import snapshot
from ..growth_probe_v07 import acceptance as previous
from .workspace import ResearchWorkspace

previous.ResearchWorkspace = ResearchWorkspace


class Checks(previous.Checks):
    def test_06_retain_cannot_silently_restore_old_text(self):
        ws = self.workspace()
        got, original, version = self.read_source(ws)
        brief = ws.file_ref(ws.public / 'business_brief.md', 'public_seen')['ref']
        first = self.checkpoint(ws, [self.action(version, [brief])])
        blocked = self.checkpoint(ws, [self.action(version, [brief], decision='retain',
            replacement_text=None, expected_prior_revision_ref=first['ref'])])
        self.assertFalse(blocked['ok'])
        self.assertIn('cannot undo', blocked['error'])
        self.assertEqual(ws.effective_historical_view(previous.SOURCE, version)['effective_text_fields']['research_use'], previous.REPLACEMENT)
        restored = self.checkpoint(ws, [self.action(version, [brief],
            replacement_text=original['research_use'], expected_prior_revision_ref=first['ref'],
            reason='Engineering explicit restoration fixture, not a correct scientific decision.')])
        self.assertIn('ref', restored, restored)
        self.assertEqual(ws.effective_historical_view(previous.SOURCE, version)['effective_text_fields']['research_use'], original['research_use'])
        self.assertFalse(ws.effective_historical_view(previous.SOURCE, version)['scientific_certification'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['GROWTH_V07_OUTPUT'] = str(args.output / 'cases')
    before = snapshot()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    assert before == snapshot()
    write_json(args.output / 'acceptance.json', {'status': 'passed' if result.wasSuccessful() else 'failed',
        'actual_tests_run': result.testsRun, 'errors': len(result.errors), 'failures': len(result.failures),
        'skipped': len(result.skipped), 'new_paid_calls': 0, 'budget_unchanged': True,
        'scope': '5actual v07controls rerun plus1explicit-restoration control; not6new capabilities. Currentworkspace/reopen only, no scientifictruth or cross-new-stage export/import efficacy.'})
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
