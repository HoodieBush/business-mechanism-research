"""Two-role migration probe; start/resume are separate OS processes.

Constructed fixtures test framework compatibility, not business discovery.
Existing business tools and audited model transport are thin adapters.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
from importlib.metadata import version
from langgraph.checkpoint.sqlite import SqliteSaver
from run_information_protocol import InformationWorkspace
from execution import PythonWorkspace
from workspace import sha,write_json
from langgraph_migration.runtime import FrameworkRoles,information_flow
from langgraph_migration.provider import APIJournal,GatewayChatModel

ROOT=Path(__file__).resolve().parents[2]


def reopen_workspace(root):
    ws=InformationWorkspace.__new__(InformationWorkspace)
    ws.root=Path(root).resolve();ws.public=ws.root/'public';ws.shared=ws.root/'artifacts'
    ws.path_aliases={};ws.require_artifact_review=True
    ws.state=json.loads((ws.shared/'research_history.json').read_text())
    ws.workers={role:PythonWorkspace(ws.shared/role,ws.public,ws.shared) for role in ('manager','analyst','verifier','mechanist','engineer','evaluator')}
    from execution import last_number
    ws.query_count=last_number(ws.shared,'query_','.csv')
    ws.operation=None;ws.delegate=None;ws.contract=json.loads((ws.public/'data_dictionary.json').read_text())
    ws.registered_data_sources={str(ws.public/'business.sqlite')}
    ws.registered_sources=ws.registered_data_sources|{str(ws.public/'data_dictionary.json')}
    ws.data_source={'database_sha256':sha(ws.public/'business.sqlite'),'dictionary_sha256':sha(ws.public/'data_dictionary.json'),'dictionary_version':ws.contract['version']}
    ws.draft=ws.workers['analyst'].directory/'export.csv'
    ws.role_prompts=json.loads((ws.root/'role_prompts.json').read_text())
    return ws


def setup(spec_file):
    spec=json.loads(Path(spec_file).read_text());output=ROOT/'experiments/business_team/results'/spec['phase']
    if output.exists():raise ValueError('existing phase may only resume; never overwrite')
    output.mkdir(parents=True)
    test=subprocess.run([sys.executable,'-m','unittest','-v','test_langgraph_migration.py'],cwd=Path(__file__).parent,capture_output=True,text=True)
    (output/'preflight-tests.log').write_text(test.stdout+test.stderr)
    if test.returncode:raise RuntimeError('framework preflight failed; no API')
    files=list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).parent/'langgraph_migration').glob('*.py'))
    files += [Path(spec_file).resolve(),ROOT/'configs/base_model.json',ROOT/'configs/langgraph-migration-osx-arm64-pip.lock.txt',ROOT/'environment.langgraph.yml',ROOT/'experiments/capability_lab/model_protocol.py',ROOT/'experiments/capability_lab/model_credentials.py']
    hashes={}
    for path in files:
        relative=path.relative_to(ROOT);dest=output/'snapshot'/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest);hashes[str(relative)]=sha(path)
    manifest={'status':'running','created_at':datetime.now(timezone.utc).isoformat(),'specification':spec,'source_sha256':hashes,
              'packages':{name:version(name) for name in ('langgraph','langchain','langchain-core','langgraph-checkpoint-sqlite','pydantic')},
              'scope':'native framework loops and process recovery; two active roles, existing constructed inputs; no new business mechanism trial', 'cases':[]}
    for case in spec['cases']:
        ws=InformationWorkspace(output/case['id'],case)
        write_json(ws.root/'role_prompts.json',ws.role_prompts)
        manifest.setdefault('fixture_sha256',{})[case['id']]={name:sha(path) for name,path in {'database':ws.public/'business.sqlite','dictionary':ws.public/'data_dictionary.json','artifact':ws.draft,'lineage':Path(str(ws.draft)+'.lineage.json')}.items()}
    write_json(output/'manifest.json',manifest)
    return output


def run(spec_file,resume=False):
    spec=json.loads(Path(spec_file).read_text());output=ROOT/'experiments/business_team/results'/spec['phase']
    if not resume:output=setup(spec_file)
    manifest=json.loads((output/'manifest.json').read_text())
    if any(sha(ROOT/name)!=value for name,value in manifest['source_sha256'].items()):raise ValueError('frozen code/dependencies changed; cannot resume this phase')
    config=json.loads((ROOT/'configs/base_model.json').read_text());config['request_timeout_seconds']=180
    journal=APIJournal(output,config,budget=spec['round_reported_token_budget'])
    connection=sqlite3.connect(output/'checkpoints.sqlite',check_same_thread=False);saver=SqliteSaver(connection)
    prior={c['id']:c for c in manifest['cases']}
    try:
        for case in spec['cases']:
            ws=reopen_workspace(output/case['id'])
            roles=FrameworkRoles(ws,saver,lambda role:GatewayChatModel(journal=journal,research_role=role))
            graph=information_flow(roles,saver,interrupt_before_consumer=not resume)
            run_config={'configurable':{'thread_id':case['id']+':flow'},'recursion_limit':2**31-1}
            before=graph.get_state(run_config)
            record=prior.get(case['id'],{'id':case['id']})
            old_calls=journal.serial
            try:
                if before.values and not before.next:values=before.values
                else:values=graph.invoke(None if before.values else {},run_config)
                after=graph.get_state(run_config)
                record.update(status='awaiting_process_restart' if after.next else values.get('status','incomplete'),
                              state=values,next_nodes=list(after.next),api_attempts_this_process=journal.serial-old_calls,
                              expected_decision_match=values.get('decision')==case['expected_decision'])
            except KeyboardInterrupt:
                record.update(status='interrupted');manifest['status']='interrupted';raise
            except Exception as error:
                record.update(status='failed',error_type=type(error).__name__,error=str(error)[:1800])
            finally:
                write_json(ws.root/'framework_case_result.json',record)
                prior[case['id']]=record;manifest.update(cases=list(prior.values()),usage=journal.usage())
                write_json(output/'manifest.json',manifest)
            print('CASE',case['id'],record['status'],record.get('state',{}).get('decision'),flush=True)
    finally:
        connection.close()
    final_status='awaiting_process_restart' if any(c['status']=='awaiting_process_restart' for c in manifest['cases']) else 'completed_with_failures' if any(c['status']=='failed' for c in manifest['cases']) else 'completed'
    manifest.update(status=final_status,
                    frozen_source_hashes_unchanged=all(sha(ROOT/n)==h for n,h in manifest['source_sha256'].items()),usage=journal.usage())
    write_json(output/'manifest.json',manifest)
    print(json.dumps({'status':manifest['status'],'usage':manifest['usage'],'cases':[(c['id'],c['status']) for c in manifest['cases']]},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--spec',required=True);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();run(args.spec,args.resume)
