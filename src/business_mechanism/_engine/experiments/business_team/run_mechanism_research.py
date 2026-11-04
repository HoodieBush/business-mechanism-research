"""Separate mechanism-research entry; no mandatory algorithm or future profit run."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from langgraph.checkpoint.sqlite import SqliteSaver
from world import OfficeWorld
from workspace import sha, write_json
from environment_readiness import sandbox_probe
from langgraph_migration.mechanism_research import MechanismWorkspace, mechanism_flow, PROFILE, QUESTION, validate_private_path
from langgraph_migration.provider import APIJournal, GatewayChatModel
from run_langgraph_science import ROOT, output_directory, role_runtime


def specification(path):
    spec = json.loads(Path(path).read_text())
    if spec.get('research_profile') != PROFILE or spec.get('role_runtime') != 'explicit_v1':
        raise ValueError('explicit_v1 mechanism profile required; old research is not migrated')
    if spec.get('explicit_runtime', {}).get('memory_profile') != 'research_memory_v1':
        raise ValueError('bounded research memory required for this entry')
    if spec.get('research_access', 'disabled') != 'disabled':
        raise ValueError('external literature-agent extension is not part of this research entry')
    if type(spec.get('round_reported_token_budget')) is not int or spec['round_reported_token_budget'] <= 0:
        raise ValueError('declare a positive existing-budget admission limit')
    if not spec.get('cases') or len({c['id'] for c in spec['cases']}) != len(spec['cases']):
        raise ValueError('declare distinct cases')
    for case in spec['cases']:
        if not case['id'].isalnum() or any(k in case for k in ('resume_from', 'resume_explicit_from')):
            raise ValueError('new neutral case IDs only; resume uses this run own checkpoint')
        validate_private_path(output_directory(spec)/case['id'], case['private_kind'])
    question = spec.get('research_question', QUESTION)
    if not isinstance(question, str) or not question.strip(): raise ValueError('nonempty research question required')
    return spec


def setup(spec_file):
    spec = specification(spec_file); out = output_directory(spec)
    if out.exists(): raise ValueError('existing run may only resume, never overwrite')
    out.mkdir(parents=True)
    ready = sandbox_probe(out/'startup_sandbox_probe'); write_json(out/'environment_readiness.json', ready)
    if not ready['ready']: raise RuntimeError('sandbox unavailable; zero model calls, no fallback')
    test = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_mechanism_research', '-q'],
        cwd=Path(__file__).parent, capture_output=True, text=True)
    (out/'preflight.log').write_text(test.stdout+test.stderr)
    if test.returncode: raise RuntimeError('mechanism contracts failed; zero model calls')
    files = list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).parent/'langgraph_migration').glob('*.py'))
    files += [Path(spec_file).resolve(), ROOT/'configs/base_model.json', ROOT/'environment.langgraph.yml',
        ROOT/'configs/langgraph-migration-osx-arm64-pip.lock.txt']
    files += [ROOT/'experiments/capability_lab'/p for p in ('model_protocol.py','model_credentials.py','token_budget.py')]
    hashes = {}
    for source in files:
        name = source.relative_to(ROOT); target = out/'snapshot'/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target); hashes[str(name)] = sha(source)
    public = {}
    for case in spec['cases']:
        ws = MechanismWorkspace(out/case['id'], OfficeWorld(case['private_kind'], case['seed'], case.get('scenario_version', 'office-business-v0.3')),
            research_question=spec.get('research_question', QUESTION))
        role_runtime(spec, ws, None, lambda role: None)
        public[case['id']] = {str(p.relative_to(ws.root)):sha(p) for p in ws.public.rglob('*') if p.is_file()}
    write_json(out/'manifest.json', {'status':'prepared', 'created_at':datetime.now(timezone.utc).isoformat(),
        'specification':spec, 'source_sha256':hashes, 'public_input_sha256':public, 'cases':[],
        'packages':{n:version(n) for n in ('langgraph','langchain','langchain-core','pydantic','langgraph-checkpoint-sqlite')},
        'scope':'Mechanism research; process completion is not scientific certification or causal evidence of a component benefit.'})
    return out


def freeze_research(ws, decision):
    if ws.state['workflow']['phase'] != 'complete' or decision.get('research_profile') != PROFILE:
        raise ValueError('close the actual mechanism graph before freezing')
    if not any(r == decision and r.get('role') == 'manager' for r in ws.state['results']):
        raise ValueError('actual manager delivery receipt required')
    target = ws.root/'research_freeze.json'
    if target.exists(): raise ValueError('mechanism research already frozen')
    report = ws.root/'mechanism_report.json'; write_json(report, decision)
    files = [report]+list((ws.shared/'research_agenda').glob('*.json'))+list((ws.shared/'hypotheses').glob('*.json'))
    seal = {'actor_closed':True, 'profile':PROFILE, 'decision':decision,
        'sha256':{str(p.relative_to(ws.root)):sha(p) for p in files}, 'algorithm_selection_required':False,
        'scientific_certification':False, 'final_profit_evaluation':False}
    write_json(target, seal); ws.actor_closed = True
    return seal


def run(spec_file, resume=False):
    spec = specification(spec_file); out = output_directory(spec) if resume else setup(spec_file)
    manifest = json.loads((out/'manifest.json').read_text())
    if manifest['specification'] != spec: raise ValueError('frozen specification changed')
    if any(sha(ROOT/p) != h for p,h in manifest['source_sha256'].items()): raise ValueError('frozen source changed')
    if any(version(n) != v for n,v in manifest['packages'].items()): raise ValueError('installed dependency changed')
    for case, files in manifest['public_input_sha256'].items():
        if any(sha(out/case/p) != h for p,h in files.items()): raise ValueError('frozen public input changed')
    config = json.loads((ROOT/'configs/base_model.json').read_text())
    journal = APIJournal(out, config, budget=spec['round_reported_token_budget'], tokens_per_minute=spec.get('model_tokens_per_minute'))
    records = {r['id']:r for r in manifest['cases']}
    manifest['status'] = 'running'; write_json(out/'manifest.json', manifest)
    with sqlite3.connect(out/'checkpoints.sqlite', check_same_thread=False) as conn:
        saver = SqliteSaver(conn)
        for case in spec['cases']:
            path = out/case['id']; record = records.get(case['id'], {'id':case['id']})
            try:
                if (path/'research_freeze.json').exists():
                    seal = json.loads((path/'research_freeze.json').read_text())
                    if any(sha(path/p) != h for p,h in seal['sha256'].items()): raise ValueError('closed report changed')
                    record.update(status='completed', decision=seal['decision']); continue
                ws = MechanismWorkspace(path, OfficeWorld(case['private_kind'],case['seed'],case.get('scenario_version','office-business-v0.3')),
                    research_question=spec.get('research_question', QUESTION), reopen=True)
                ws.resource_reader = journal.public_view
                roles = role_runtime(spec, ws, saver, lambda role: GatewayChatModel(journal=journal, research_role=role))
                graph = mechanism_flow(roles, saver)
                conf = {'configurable':{'thread_id':case['id']+':mechanism'}, 'recursion_limit':2**31-1}
                before = graph.get_state(conf)
                result = before.values if before.values and not before.next else graph.invoke(None if before.values else {}, conf)
                record.update(status=result.get('status','incomplete'), research_state=ws.research_state_view())
                if result.get('status') == 'completed': record['decision'] = freeze_research(ws,result['step'])['decision']
            except KeyboardInterrupt:
                record.update(status='interrupted'); manifest['status']='interrupted'; raise
            except Exception as error:
                record.update(status='incomplete', error_type=type(error).__name__, error=str(error)[:2500])
            finally:
                records[case['id']] = record; manifest.update(cases=list(records.values()), usage=journal.usage())
                write_json(out/'manifest.json', manifest)
    manifest['status'] = 'completed' if all(r['status']=='completed' for r in records.values()) else 'incomplete'
    write_json(out/'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--spec',required=True); parser.add_argument('--resume',action='store_true')
    args=parser.parse_args(); result=run(Path(args.spec),args.resume)
    print(json.dumps({'status':result['status'],'usage':result['usage']},ensure_ascii=False))
    raise SystemExit(0 if result['status']=='completed' else 2)
