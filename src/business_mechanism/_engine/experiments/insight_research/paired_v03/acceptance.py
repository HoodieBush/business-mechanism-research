"""Frozen full engineering regression and paired-runtime integration checks."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from ..common import ROOT, now, sha, write_json
from ..acceptance import cases
from .. import test_acceptance,test_memory,test_robust,test_continuation,test_closeout
from ..critic_v01 import test_m0
from ..paired_v01 import test_pairing
from ..paired_v02 import test_interface
from . import test_continuation as test_paired_continuation
from token_budget import SharedTokenBudget


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    output=Path(parser.parse_args().output).resolve();output.mkdir(parents=True,exist_ok=False)
    modules=(test_acceptance,test_memory,test_robust,test_continuation,test_closeout,test_m0,test_pairing,test_interface,test_paired_continuation)
    loaded=list(cases(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(m) for m in modules)))
    planned=[x.id() for x in loaded]
    if len(planned)!=len(set(planned)):raise ValueError('duplicate engineering controls')
    write_json(output/'planned_tests.json',planned)
    pointer=ROOT/'experiments/budgets/USER-20261022-CRITIC-10M/pointer.json'
    before={'project':SharedTokenBudget(pointer).snapshot(),'old_active':SharedTokenBudget().snapshot()};write_json(output/'budget_before.json',before)
    started=now()
    with ExitStack() as s:
        s.enter_context(patch.dict(os.environ,{'INSIGHT_ACCEPTANCE_OUTPUT':str(output/'cases')}))
        s.enter_context(patch('model_protocol.load_api_key',side_effect=AssertionError('live credentials forbidden')))
        s.enter_context(patch('socket.getaddrinfo',side_effect=AssertionError('live DNS forbidden')))
        s.enter_context(patch('socket.socket.connect',side_effect=AssertionError('live network forbidden')))
        log=s.enter_context((output/'checks.log').open('x'))
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.TestSuite(loaded))
    after={'project':SharedTokenBudget(pointer).snapshot(),'old_active':SharedTokenBudget().snapshot()};write_json(output/'budget_after.json',after)
    protected=json.loads((ROOT/'experiments/insight_research/review/paired_impl_20261023/baseline.json').read_text())['protected_sources']
    legacy=json.loads((ROOT/'experiments/insight_research/legacy_before_sha256.json').read_text())['sha256']
    v01={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-032/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v01/')}
    v02={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-033/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v02/')}
    unchanged=all(sha(ROOT/p)==v for p,v in {**legacy,**protected,**v01,**v02}.items())
    receipts=[]
    for pattern,kind in (('execution_[0-9]*.json','sandbox'),('backend_receipt.json','protocol')):
        for p in (output/'cases').rglob(pattern):
            receipt=json.loads(p.read_text());fresh=Path(receipt.get('execution_directory','')).resolve()==p.parent.resolve()
            receipts.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'kind':kind,'new_execution':fresh})
    write_json(output/'receipt_index.json',receipts)
    passed=result.wasSuccessful() and not result.skipped and before==after and unchanged
    report={'status':'passed' if passed else 'failed','tests_planned':len(planned),'tests_run':result.testsRun,
        'failures':[x.id() for x,_ in result.failures],'errors':[x.id() for x,_ in result.errors],'skipped':[x.id() for x,_ in result.skipped],
        'paired_v02_sources_unchanged':len(v02) if unchanged else False,'paired_v01_sources_unchanged':len(v01) if unchanged else False,'protected_prior_sources_unchanged':len(protected) if unchanged else False,'legacy_sources_unchanged':len(legacy) if unchanged else False,
        'actual_sandbox_executions':sum(x['kind']=='sandbox' and x['new_execution'] for x in receipts),
        'actual_protocol_receipts':sum(x['kind']=='protocol' and x['new_execution'] for x in receipts),
        'inherited_receipt_copies':sum(not x['new_execution'] for x in receipts),
        'project_and_old_active_budget_unchanged':before==after,'new_paid_calls':0,
        'scientific_effectiveness_certified':False,'started_at':started,'finished_at':now(),'checks_log_sha256':sha(output/'checks.log')}
    write_json(output/'acceptance.json',report);print(json.dumps(report,ensure_ascii=False))
    return 0 if passed else 2


if __name__=='__main__':raise SystemExit(main())
