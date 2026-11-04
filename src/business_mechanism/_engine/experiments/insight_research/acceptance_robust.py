"""Registered zero-model scene validation or full consistency regression."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from .common import ROOT, now, sha, write_json
from .acceptance import cases
from . import test_acceptance, test_memory, test_robust
from token_budget import SharedTokenBudget


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    parser.add_argument('--suite',choices=['scene','full'],required=True)
    args=parser.parse_args(); output=Path(args.output).resolve(); output.mkdir(parents=True,exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(test_robust.SceneTests) if args.suite=='scene' else unittest.TestSuite(
        [unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_acceptance,test_memory,test_robust)])
    loaded=list(cases(suite)); planned=[c.id() for c in loaded]
    assert len(planned)==len(set(planned))==(5 if args.suite=='scene' else 100)
    write_json(output/'planned_tests.json',planned)
    before=SharedTokenBudget().snapshot(); write_json(output/'budget_before.json',before); started=now()
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ,{'INSIGHT_ACCEPTANCE_OUTPUT':str(output/'cases')}))
        stack.enter_context(patch('model_protocol.load_api_key',side_effect=AssertionError('live credentials forbidden')))
        stack.enter_context(patch('socket.getaddrinfo',side_effect=AssertionError('live DNS forbidden')))
        stack.enter_context(patch('socket.socket.connect',side_effect=AssertionError('live network forbidden')))
        log=stack.enter_context((output/'checks.log').open('x'))
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.TestSuite(loaded))
    after=SharedTokenBudget().snapshot(); write_json(output/'budget_after.json',after)
    baseline=json.loads((Path(__file__).parent/'legacy_before_sha256.json').read_text())['sha256']
    unchanged=all(sha(ROOT/p)==h for p,h in baseline.items())
    passed=result.wasSuccessful() and not result.skipped and result.testsRun==len(planned) and before==after and unchanged
    report={'status':'passed' if passed else 'failed','suite':args.suite,'tests_planned':len(planned),'tests_run':result.testsRun,
        'failures':[c.id() for c,_ in result.failures],'errors':[c.id() for c,_ in result.errors],
        'skipped':[c.id() for c,_ in result.skipped],'legacy_source_files_unchanged':len(baseline) if unchanged else False,
        'actual_sandbox_executions':len(list((output/'cases').rglob('execution_[0-9]*.json'))),
        'actual_protocol_receipts':len(list((output/'cases').rglob('backend_receipt.json'))),
        'new_model_calls':0,'global_budget_unchanged':before==after,'scientific_discovery_certified':False,
        'started_at':started,'finished_at':now(),'checks_log_sha256':sha(output/'checks.log')}
    write_json(output/'acceptance.json',report); print(json.dumps(report,ensure_ascii=False))
    return 0 if passed else 2


if __name__=='__main__': raise SystemExit(main())
