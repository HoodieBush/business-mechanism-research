"""One frozen engineering allocation; real sandbox, no live credentials/network."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from .common import ROOT, now, sha, write_json
from . import test_acceptance
from token_budget import SharedTokenBudget


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite): yield from cases(item)
        else: yield item


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    args = parser.parse_args(); output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = SharedTokenBudget().snapshot(); write_json(output / 'budget_before.json', before)
    loaded = list(cases(unittest.defaultTestLoader.loadTestsFromModule(test_acceptance)))
    planned = [c.id() for c in loaded]
    assert len(planned) == len(set(planned)) == 37
    write_json(output / 'planned_tests.json', planned)
    started = now()
    write_json(output / 'acceptance.json', {'status': 'running', 'started_at': started,
        'tests_planned': len(planned), 'scientific_discovery_certified': False})
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {'INSIGHT_ACCEPTANCE_OUTPUT': str(output / 'cases')}))
        stack.enter_context(patch('model_protocol.load_api_key', side_effect=AssertionError('live credentials forbidden in acceptance')))
        stack.enter_context(patch('socket.getaddrinfo', side_effect=AssertionError('live DNS forbidden in acceptance')))
        stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('live network forbidden in acceptance')))
        log = stack.enter_context((output / 'checks.log').open('x'))
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.TestSuite(loaded))
    after = SharedTokenBudget().snapshot(); write_json(output / 'budget_after.json', after)
    baseline = json.loads((Path(__file__).parent / 'legacy_before_sha256.json').read_text())['sha256']
    unchanged = all(sha(ROOT / p) == h for p, h in baseline.items())
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == len(planned) and before == after and unchanged
    report = {'status': 'passed' if passed else 'failed', 'tests_planned': len(planned), 'tests_run': result.testsRun,
        'failures': [c.id() for c, _ in result.failures], 'errors': [c.id() for c, _ in result.errors],
        'skipped': [c.id() for c, _ in result.skipped], 'old_source_files_unchanged': len(baseline) if unchanged else False,
        'actual_sandbox_executions': len(list((output / 'cases').rglob('execution_[0-9]*.json'))),
        'actual_protocol_receipts': len(list((output / 'cases').rglob('backend_receipt.json'))),
        'new_model_calls': 0, 'global_budget_unchanged': before == after,
        'scientific_discovery_certified': False, 'scripted_actor_is_fixture': True,
        'started_at': started, 'finished_at': now(), 'checks_log_sha256': sha(output / 'checks.log')}
    write_json(output / 'acceptance.json', report); print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == '__main__': raise SystemExit(main())
