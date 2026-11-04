"""One registered zero-paid engineering validation, old suite plus M0 tests."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ..common import ROOT, now, sha, write_json
from ..acceptance import cases
from .. import test_acceptance, test_memory, test_robust, test_continuation, test_closeout
from . import test_m0
from token_budget import SharedTokenBudget

POINTER = ROOT / 'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    args = parser.parse_args(); output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in
        (test_acceptance, test_memory, test_robust, test_continuation, test_closeout, test_m0))
    loaded = list(cases(suite)); planned = [c.id() for c in loaded]
    if len(planned) != len(set(planned)): raise ValueError('duplicate engineering checks')
    write_json(output / 'planned_tests.json', planned)
    before = {'project': SharedTokenBudget(POINTER).snapshot(), 'legacy_active': SharedTokenBudget().snapshot()}
    write_json(output / 'budget_before.json', before); started = now()
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {'INSIGHT_ACCEPTANCE_OUTPUT': str(output / 'cases')}))
        stack.enter_context(patch('model_protocol.load_api_key', side_effect=AssertionError('live credentials forbidden')))
        stack.enter_context(patch('socket.getaddrinfo', side_effect=AssertionError('live DNS forbidden')))
        stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('live network forbidden')))
        log = stack.enter_context((output / 'checks.log').open('x'))
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.TestSuite(loaded))
    after = {'project': SharedTokenBudget(POINTER).snapshot(), 'legacy_active': SharedTokenBudget().snapshot()}
    write_json(output / 'budget_after.json', after)
    old = json.loads((ROOT / 'experiments/insight_research/legacy_before_sha256.json').read_text())['sha256']
    previous = json.loads((ROOT / 'experiments/insight_research/review/critic_m0_impl_20261022/baseline.json').read_text())['runtime_sha256']
    unchanged = all(sha(ROOT / p) == h for p, h in {**old, **previous}.items())
    receipts = []
    for pattern, kind in (('execution_[0-9]*.json', 'sandbox'), ('backend_receipt.json', 'protocol')):
        for path in (output / 'cases').rglob(pattern):
            item = json.loads(path.read_text())
            fresh = Path(item.get('execution_directory', '')).resolve() == path.parent.resolve()
            receipts.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'kind': kind, 'new_execution': fresh})
    write_json(output / 'receipt_index.json', receipts)
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == len(planned) and before == after and unchanged
    report = {'status': 'passed' if passed else 'failed', 'tests_planned': len(planned), 'tests_run': result.testsRun,
        'failures': [c.id() for c, _ in result.failures], 'errors': [c.id() for c, _ in result.errors],
        'skipped': [c.id() for c, _ in result.skipped], 'old_source_files_unchanged': len(old),
        'prior_single_researcher_source_files_unchanged': len(previous),
        'actual_sandbox_executions': sum(r['kind'] == 'sandbox' and r['new_execution'] for r in receipts),
        'actual_protocol_receipts': sum(r['kind'] == 'protocol' and r['new_execution'] for r in receipts),
        'inherited_receipts_not_new': sum(not r['new_execution'] for r in receipts),
        'budget_unchanged': before == after, 'new_paid_calls': 0,
        'scientific_discovery_certified': False, 'started_at': started, 'finished_at': now(), 'log_sha256': sha(output / 'checks.log')}
    write_json(output / 'acceptance.json', report); print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == '__main__': raise SystemExit(main())
