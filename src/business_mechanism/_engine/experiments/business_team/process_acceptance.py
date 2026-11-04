"""Strict zero-model process acceptance, with persistent engineering evidence.

Controls use explicit fixtures; sandbox suite runs actual code and final
evaluation. A skipped check never qualifies as acceptance. No paid model call.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from workspace import sha,write_json
from environment_readiness import sandbox_probe

CONTROL_MODULES=('test_minimal_research','test_behavior_comparison','test_science_input_freeze',
                 'test_context_retention','test_token_budget','test_acceptance_gate')


def cases(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from cases(item)
        else:yield item


def classify(result,expected):
    if result.errors or result.failures:return 'failed'
    if result.skipped:return 'incomplete_skipped_checks'
    if result.testsRun!=expected:return 'incomplete_test_coverage'
    if result.expectedFailures or result.unexpectedSuccesses:return 'incomplete_expected_failure'
    return 'passed'


@contextmanager
def offline_transport_guard():
    # Importing the existing gateway installs its ordinary capability_lab path.
    from langgraph_migration import provider
    with patch('model_protocol.load_api_key',side_effect=AssertionError('live credentials forbidden in engineering acceptance')),patch(
        'socket.getaddrinfo',side_effect=AssertionError('network DNS forbidden in engineering acceptance')),patch(
        'socket.socket.connect',side_effect=AssertionError('network connection forbidden in engineering acceptance')):
        yield


def run(output,mode='controls',memory=False):
    output=Path(output).resolve()
    if output.exists():raise ValueError('acceptance output already exists; never overwrite/restart an allocation')
    output.mkdir(parents=True)
    record={'started_at':datetime.now(timezone.utc).isoformat(),'mode':mode,'model_calls':0,
            'scientific_ability_certified':False,'status':'running','evidence_scope':'engineering process acceptance only',
            'environment':{'python':sys.version,'packages':{n:version(n) for n in ('langgraph','langchain','langchain-core','langchain-openai','langgraph-checkpoint-sqlite','pydantic','numpy','pandas','scipy')}}}
    write_json(output/'acceptance.json',record)
    if mode=='sandbox':
        probe=sandbox_probe(output/'environment_probe');write_json(output/'environment.json',probe)
        if not probe['ready']:
            record.update(status='blocked_sandbox',required_checks_executed=False)
            write_json(output/'acceptance.json',record);return record
        names=['test_process_integration','test_business_team']
    else:names=list(CONTROL_MODULES)
    if memory:
        names.append('test_research_memory_sandbox' if mode=='sandbox' else 'test_research_memory')
        record['research_memory_profile']='research_memory_v1'
    loaded=list(cases(unittest.defaultTestLoader.loadTestsFromNames(names)))
    # This old optional integration check belongs to the separate strict suite.
    if mode=='controls':loaded=[c for c in loaded if not c.id().endswith('test_five_roles_actual_sandbox_and_development_evaluation_allow_refutation')]
    ids=[c.id() for c in loaded]
    write_json(output/'planned_tests.json',ids)
    # Budget tests must exercise real transport bookkeeping with their own fake
    # opener/key. Block live credentials and network beneath that boundary;
    # patching request_model itself would invalidate those tests.
    with (output/'checks.log').open('x') as stream,patch.dict(os.environ,{'PROCESS_ACCEPTANCE_OUTPUT':str(output/'cases')}),offline_transport_guard():
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestSuite(loaded))
    record.update(status=classify(result,len(ids)),tests_planned=len(ids),tests_run=result.testsRun,
        failures=[c.id() for c,_ in result.failures],errors=[c.id() for c,_ in result.errors],
        skipped=[{'id':c.id(),'reason':reason} for c,reason in result.skipped],
        finished_at=datetime.now(timezone.utc).isoformat(),checks_log_sha256=sha(output/'checks.log'))
    write_json(output/'acceptance.json',record)
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    parser.add_argument('--mode',choices=('controls','sandbox'),default='controls')
    parser.add_argument('--memory',action='store_true');args=parser.parse_args()
    result=run(args.output,args.mode,memory=args.memory);print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status']=='passed' else 2)
