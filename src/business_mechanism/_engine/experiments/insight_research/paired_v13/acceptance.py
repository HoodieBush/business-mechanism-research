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
from ..paired_v03 import test_continuation as test_paired_continuation
from ..paired_v04 import test_import
from ..paired_v05 import test_resources
from ..paired_v06 import test_references
from ..paired_v07 import test_workflow
from ..paired_v08 import test_common_review
from ..paired_v09 import test_bootstrap
from ..review.workflow_20261024 import test_response_followup as test_response
from ..paired_v11 import test_scoped
from ..paired_v12 import test_restoration,test_journal_memory
from . import test_admission
from token_budget import SharedTokenBudget


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    output=Path(parser.parse_args().output).resolve();output.mkdir(parents=True,exist_ok=False)
    modules=(test_acceptance,test_memory,test_robust,test_continuation,test_closeout,test_m0,test_pairing,test_interface,test_paired_continuation,test_import,test_resources,test_references,test_workflow,test_common_review,test_bootstrap,test_response,test_scoped,test_restoration,test_journal_memory,test_admission)
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
    v03={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-034/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v03/')}
    v04={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-036/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v04/')}
    v05={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-038/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v05/')}
    v06={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-039/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v06/')}
    v07={p:h for p,h in json.loads((ROOT/'experiments/studies/ENG-055/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v07/')}
    v08={p:h for p,h in json.loads((ROOT/'experiments/studies/ENG-056/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v08/')}
    v09={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-044/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v09/')}
    v10={p:h for p,h in json.loads((ROOT/'experiments/studies/ENG-059/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v10/')}
    v11={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-045/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v11/')}
    v12={p:h for p,h in json.loads((ROOT/'experiments/studies/SCI-046/freeze.json').read_text())['sha256'].items() if p.startswith('experiments/insight_research/paired_v12/')}
    unchanged=all(sha(ROOT/p)==v for p,v in {**legacy,**protected,**v01,**v02,**v03,**v04,**v05,**v06,**v07,**v08,**v09,**v10,**v11,**v12}.items())
    receipts=[]
    for pattern,kind in (('execution_[0-9]*.json','sandbox'),('backend_receipt.json','protocol')):
        for p in (output/'cases').rglob(pattern):
            receipt=json.loads(p.read_text());fresh=Path(receipt.get('execution_directory','')).resolve()==p.parent.resolve()
            receipts.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'kind':kind,'new_execution':fresh})
    write_json(output/'receipt_index.json',receipts)
    passed=result.wasSuccessful() and not result.skipped and before==after and unchanged
    report={'status':'passed' if passed else 'failed','tests_planned':len(planned),'tests_run':result.testsRun,
        'failures':[x.id() for x,_ in result.failures],'errors':[x.id() for x,_ in result.errors],'skipped':[x.id() for x,_ in result.skipped],
        'paired_v12_sources_unchanged':len(v12) if unchanged else False,'paired_v11_sources_unchanged':len(v11) if unchanged else False,'paired_v10_sources_unchanged':len(v10) if unchanged else False,'paired_v09_sources_unchanged':len(v09) if unchanged else False,'paired_v08_sources_unchanged':len(v08) if unchanged else False,'paired_v07_sources_unchanged':len(v07) if unchanged else False,'paired_v06_sources_unchanged':len(v06) if unchanged else False,'paired_v05_sources_unchanged':len(v05) if unchanged else False,'paired_v04_sources_unchanged':len(v04) if unchanged else False,'paired_v03_sources_unchanged':len(v03) if unchanged else False,'paired_v02_sources_unchanged':len(v02) if unchanged else False,'paired_v01_sources_unchanged':len(v01) if unchanged else False,'protected_prior_sources_unchanged':len(protected) if unchanged else False,'legacy_sources_unchanged':len(legacy) if unchanged else False,
        'actual_sandbox_executions':sum(x['kind']=='sandbox' and x['new_execution'] for x in receipts),
        'actual_protocol_receipts':sum(x['kind']=='protocol' and x['new_execution'] for x in receipts),
        'inherited_receipt_copies':sum(not x['new_execution'] for x in receipts),
        'project_and_old_active_budget_unchanged':before==after,'new_paid_calls':0,
        'scientific_effectiveness_certified':False,'started_at':started,'finished_at':now(),'checks_log_sha256':sha(output/'checks.log')}
    write_json(output/'acceptance.json',report);print(json.dumps(report,ensure_ascii=False))
    return 0 if passed else 2


if __name__=='__main__':raise SystemExit(main())
