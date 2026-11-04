"""Frozen paid pilot of packets and four-role supervised information research.

Small developer inputs are not a new business mechanism or a blind benchmark.
No expected decision/answer is given to the Actors. Never overwrite old phases.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime,timezone
from importlib.metadata import version
from langgraph.checkpoint.sqlite import SqliteSaver
from run_langgraph_migration import reopen_workspace
from workspace import sha,write_json
from langgraph_migration.collaboration import CollaborativeWorkspace,collaboration_flow
from langgraph_migration.packets import EvidencePackets
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.provider import APIJournal,GatewayChatModel

ROOT=Path(__file__).resolve().parents[2]


def reopen_collaboration(root):
    ws=reopen_workspace(root);ws.__class__=CollaborativeWorkspace
    ws.case_context=json.loads((ws.root/'case_context.json').read_text());ws.packets=EvidencePackets(ws)
    card=ws.public/'python_data_api.json'
    ws.python_api=json.loads(card.read_text()) if card.exists() else None
    if card.exists():ws.registered_sources.add(str(card))
    return ws


def setup(spec_file):
    spec=json.loads(Path(spec_file).read_text());output=ROOT/'experiments/business_team/results'/spec['phase']
    if output.exists():raise ValueError('existing phase must resume; never overwrite')
    output.mkdir(parents=True)
    test=subprocess.run([sys.executable,'-m','unittest','-v','test_langgraph_collaboration.py','test_langgraph_migration.py','test_information_protocol.py','test_business_team.py'],cwd=Path(__file__).parent,capture_output=True,text=True)
    (output/'preflight-tests.log').write_text(test.stdout+test.stderr)
    if test.returncode:raise RuntimeError('preflight failed; zero model API calls')
    files=list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).parent/'langgraph_migration').glob('*.py'))
    files += [Path(spec_file).resolve(),ROOT/'configs/base_model.json',ROOT/'environment.langgraph.yml',ROOT/'configs/langgraph-migration-osx-arm64-pip.lock.txt',ROOT/'experiments/capability_lab/model_protocol.py',ROOT/'experiments/capability_lab/model_credentials.py']
    hashes={}
    for path in files:
        relative=path.relative_to(ROOT);dest=output/'snapshot'/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest);hashes[str(relative)]=sha(path)
    manifest={'status':'running','created_at':datetime.now(timezone.utc).isoformat(),'specification':spec,'source_sha256':hashes,
              'packages':{name:version(name) for name in ('langgraph','langchain','langchain-core','langgraph-checkpoint-sqlite','pydantic')},
              'scope':'component development: four actual role contexts, producer code, independent review, supervisor revision and typed handoff; constructed developer inputs, no causal trial or business improvement claim','cases':[]}
    for case in spec['cases']:
        ws=CollaborativeWorkspace(output/case['id'],case)
        manifest.setdefault('input_sha256',{})[case['id']]={name:sha(path) for name,path in {'database':ws.public/'business.sqlite','dictionary':ws.public/'data_dictionary.json'}.items()}
    write_json(output/'manifest.json',manifest)
    return output


def run(spec_file,resume=False):
    spec=json.loads(Path(spec_file).read_text());output=ROOT/'experiments/business_team/results'/spec['phase']
    if not resume:output=setup(spec_file)
    manifest=json.loads((output/'manifest.json').read_text())
    if any(sha(ROOT/path)!=digest for path,digest in manifest['source_sha256'].items()):raise ValueError('frozen sources changed; open a new phase, do not resume')
    config=json.loads((ROOT/'configs/base_model.json').read_text());config['request_timeout_seconds']=180
    journal=APIJournal(output,config,budget=spec['round_reported_token_budget'])
    connection=sqlite3.connect(output/'checkpoints.sqlite',check_same_thread=False);saver=SqliteSaver(connection)
    records={c['id']:c for c in manifest['cases']}
    try:
        for case in spec['cases']:
            ws=reopen_collaboration(output/case['id'])
            roles=FrameworkRoles(ws,saver,lambda role:GatewayChatModel(journal=journal,research_role=role))
            graph=collaboration_flow(roles,saver)
            binding=ws.task_binding({'inputs':sorted(ws.registered_sources)})
            import hashlib
            key=hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()[:16]
            run_config={'configurable':{'thread_id':case['id']+':collaboration:'+key},'recursion_limit':2**31-1}
            before=graph.get_state(run_config);start=journal.serial;record=records.get(case['id'],{'id':case['id']})
            print('START',case['id'],ws.workflow()['phase'],flush=True)
            try:
                values=before.values if before.values and not before.next else graph.invoke(None if before.values else {},run_config)
                record.update(status=values.get('status','incomplete'),state=values,workflow=ws.workflow(),api_attempts_this_process=journal.serial-start)
            except KeyboardInterrupt:
                record.update(status='interrupted',workflow=ws.workflow());manifest['status']='interrupted';raise
            except Exception as error:
                record.update(status='failed',error_type=type(error).__name__,error=str(error)[:1800],workflow=ws.workflow())
            finally:
                record['reviews']=ws.state['artifact_reviews'];record['task_roles']=[t['role'] for t in ws.state['tasks']]
                record['packet_ids']=list(ws.state.get('packets',{}));record['results_count']=len(ws.state['results'])
                records[case['id']]=record;manifest.update(cases=list(records.values()),usage=journal.usage())
                write_json(ws.root/'case_result.json',record);write_json(output/'manifest.json',manifest)
            print('CASE',case['id'],record['status'],record['task_roles'],flush=True)
    finally:connection.close()
    manifest.update(status='completed_with_failures' if any(c['status']!='completed' for c in records.values()) else 'completed',
                    completed_at=datetime.now(timezone.utc).isoformat(),usage=journal.usage(),
                    frozen_source_hashes_unchanged=all(sha(ROOT/n)==h for n,h in manifest['source_sha256'].items()))
    write_json(output/'manifest.json',manifest)
    print(json.dumps({'status':manifest['status'],'usage':manifest['usage'],'cases':[(c['id'],c['status']) for c in manifest['cases']]},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--spec',required=True);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();run(args.spec,args.resume)
