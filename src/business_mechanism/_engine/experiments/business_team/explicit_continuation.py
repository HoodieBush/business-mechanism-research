"""New allocation from an unfinished explicit checkpoint; parent evidence stays read-only.

Only runtime path bindings move. Received bytes, original messages, task text,
tool permissions, cursor, policy and hypothesis/evidence versions are preserved.
Parent public/artifacts remain readable for absolute paths in existing scripts;
parent runtime/checkpoints/credentials and writes remain outside Actor access.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from workspace import sha,write_json


def tree_hashes(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(Path(root).rglob('*'))
            if p.is_file() and not p.name.endswith(('-wal','-shm'))}


def canonical(value,root):
    if isinstance(value,str):return value.replace(str(root),'<WORKSPACE>')
    if isinstance(value,list):return [canonical(v,root) for v in value]
    if isinstance(value,dict):return {canonical(k,root):canonical(v,root) for k,v in value.items()}
    return value


def identity_hash(identity):
    return hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def settled_request_prefix(prior_out,rows):
    """A recorded pre-send budget rejection is not an unknown provider call.

    Preserve its start/admission records and serial; never invent a response or
    refund any usage. All genuinely unreturned/unsettled requests still block.
    """
    prior_out=Path(prior_out)
    starts=[json.loads(s) for s in (prior_out/'requests_started.jsonl').read_text().splitlines()]
    admissions=prior_out/'admission_events.jsonl'
    events=[json.loads(s) for s in admissions.read_text().splitlines()] if admissions.exists() else []
    not_sent={e['request_index'] for e in events if e.get('status')=='shared_budget_stopped' and e.get('request_sent') is False}
    completed={r['request_index'] for r in rows};started={r['request_index'] for r in starts}
    if len(completed)!=len(rows) or len(started)!=len(starts) or completed & not_sent or started!=completed|not_sent:
        raise ValueError('parent has unsettled or ambiguous requests; only proven pre-send budget rejections are excluded')
    return sorted(not_sent)


def configure_readonly_parent(workspace,parent):
    parent=Path(parent).resolve()
    if (parent/'decision_freeze.json').exists():raise ValueError('cannot continue an Actor exposed to final evaluation')
    if workspace.root==parent or workspace.root.is_relative_to(parent):raise ValueError('new sibling allocation required')
    if workspace.path_aliases.get(str(parent))!=str(workspace.root):raise ValueError('missing exact continuation path alias')
    workspace.preserve_received_python_api=True
    ancestors=[Path(source).resolve() for source,target in workspace.path_aliases.items() if target==str(workspace.root)]
    for source in ancestors:
        if source==workspace.root or (source/'decision_freeze.json').exists():raise ValueError('invalid or final-exposed ancestor')
        if sha(source/'public/history.csv')!=sha(workspace.public/'history.csv'):raise ValueError('ancestor observation version changed')
    for worker in workspace.workers.values():
        worker.readonly_input_roots=tuple(p for source in ancestors for p in (source/'public',source/'artifacts'))


def relocate_explicit_checkpoints(workspace,parent,roles):
    """Validate every binding before moving checkpoints; no new model invocation."""
    parent=Path(parent).resolve();base=workspace.root/'explicit_runtime_state'
    plans=[]
    for old in sorted(base.glob('*/*.json')):
        state=json.loads(old.read_text());role=old.parent.name;identity=state['identity']
        if state.get('pending'):raise ValueError('continuation requires a settled tool batch; preserve ambiguous parent')
        if identity_hash(identity)!=old.stem:raise ValueError('parent checkpoint identity mismatch')
        if identity['runtime']!=roles.policy:raise ValueError('runtime policy cannot change in budget-only continuation')
        task=identity['task'];binding=workspace.task_binding(task)
        if canonical(canonical(binding,workspace.root),parent)!=canonical(identity['input_versions'],parent):
            raise ValueError('continuation changed input bytes, evidence versions or roles')
        if state['task_snapshot']['workspace_root']!=str(parent):raise ValueError('checkpoint belongs to a different parent')
        new_identity={'task':deepcopy(task),'input_versions':binding,'runtime':roles.policy}
        target=old.with_name(identity_hash(new_identity)+'.json')
        pin=role+':'+task['id']
        if workspace.state['explicit_task_bindings'].get(pin)!=old.stem:raise ValueError('parent task pin mismatch')
        changed=deepcopy(state);changed['identity']=new_identity
        changed['task_snapshot']['workspace_root']=str(workspace.root)
        changed['task_snapshot']['input_versions']=deepcopy(binding)
        assert changed['messages']==state['messages']
        plans.append((old,target,changed,pin))
    if not plans:raise ValueError('no explicit checkpoints to continue')
    records=[]
    for old,target,state,pin in plans:
        if target!=old and target.exists():raise ValueError('checkpoint collision')
        message_sha=hashlib.sha256(json.dumps(state['messages'],ensure_ascii=False).encode()).hexdigest()
        write_json(target,state)
        response=old.with_suffix('.responses.jsonl');new_response=target.with_suffix('.responses.jsonl')
        if response.exists() and response!=new_response:response.rename(new_response)
        if old!=target:old.unlink()
        workspace.state['explicit_task_bindings'][pin]=target.stem
        for item in workspace.state.get('runtime_yields',{}).values():
            if item.get('checkpoint')==str(parent/old.relative_to(workspace.root)):item['checkpoint']=str(target)
        records.append({'task_pin':pin,'old_checkpoint':str(parent/old.relative_to(workspace.root)),
                        'new_checkpoint':str(target),'messages_sha256_unchanged':message_sha,
                        'model_steps':state['model_steps'],'completed_calls':state.get('completed_calls')})
    workspace.persist();return records


def prepare_branch(spec_file):
    """Root-only setup; native run(..., resume=True) then owns all actual actions."""
    from run_langgraph_science import ROOT,role_runtime,evaluation_window,output_directory
    from process_acceptance import run as acceptance
    from langgraph_migration.science import ScientificWorkspace
    from world import OfficeWorld
    spec=json.loads(Path(spec_file).read_text());out=output_directory(spec);evaluation_window(spec)
    if out.exists():raise ValueError('new allocation already exists; never restart')
    if len(spec['cases'])!=1:raise ValueError('one additional-budget allocation per branch')
    case=spec['cases'][0];parent=(ROOT/case['resume_explicit_from']).resolve();prior_out=parent.parent
    before=tree_hashes(parent)
    parent_manifest=json.loads((prior_out/'manifest.json').read_text())
    if parent_manifest['status'] not in ('incomplete','interrupted'):raise ValueError('parent is not an unfinished allocation')
    if (parent/'decision_freeze.json').exists():raise ValueError('parent Actor already closed')
    original_spec=parent_manifest['specification'];original_case=next(c for c in original_spec['cases'] if c['id']==case['id'])
    for key in ('id','seed','private_kind','scenario_version'):
        if case.get(key)!=original_case.get(key):raise ValueError('budget-only continuation changed case '+key)
    if spec.get('research_question')!=original_spec.get('research_question') or spec.get('explicit_runtime')!=original_spec.get('explicit_runtime'):
        raise ValueError('budget-only continuation changed question or runtime')
    calls=(prior_out/'model_calls.jsonl').read_bytes();rows=[json.loads(s) for s in calls.splitlines()]
    if any(not r.get('response',{}).get('usage') for r in rows):raise ValueError('unknown parent local usage requires separate explicit protocol')
    not_sent=settled_request_prefix(prior_out,rows)
    prior_tokens=sum(r['response']['usage']['total_tokens'] for r in rows)
    if spec['round_reported_token_budget']!=prior_tokens+spec['additional_token_budget']:raise ValueError('additional local budget must preserve prior actual usage')
    out.mkdir(parents=True)
    for mode in ('controls','sandbox'):
        result=acceptance(out/('preflight_'+mode),mode)
        if result['status']!='passed':raise ValueError('actual branch preflight did not pass: '+mode)
    destination=out/case['id'];shutil.copytree(parent,destination)
    aliases=json.loads((destination/'path_aliases.json').read_text())
    aliases={k:str(destination/Path(v).relative_to(parent)) if Path(v).is_relative_to(parent) else v for k,v in aliases.items()}
    aliases[str(parent)]=str(destination);write_json(destination/'path_aliases.json',aliases)
    for name in ('model_calls.jsonl','requests_started.jsonl','admission_events.jsonl','retry_events.jsonl'):
        source=prior_out/name
        if source.exists():shutil.copyfile(source,out/name)
    with sqlite3.connect((prior_out/'checkpoints.sqlite').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(out/'checkpoints.sqlite') as target:
        source.backup(target)
    ws=ScientificWorkspace(destination,OfficeWorld(case['private_kind'],case['seed'],case['scenario_version']),reopen=True)
    configure_readonly_parent(ws,parent)
    roles=role_runtime(spec,ws,None,lambda role:None)
    migrated=relocate_explicit_checkpoints(ws,parent,roles)
    for name,digest in parent_manifest['public_input_sha256'][case['id']].items():
        if sha(destination/name)!=digest:raise ValueError('received public input changed')
    files=list((ROOT/'experiments/business_team').glob('*.py'))+list((ROOT/'experiments/business_team/langgraph_migration').glob('*.py'))
    files+=[Path(spec_file).resolve(),ROOT/'configs/base_model.json',ROOT/'environment.langgraph.yml',ROOT/'configs/langgraph-migration-osx-arm64-pip.lock.txt',ROOT/'experiments/capability_lab/model_protocol.py',ROOT/'experiments/capability_lab/model_credentials.py',ROOT/'experiments/capability_lab/token_budget.py',ROOT/'scripts/check_registry_literals.py']
    hashes={}
    for path in files:
        name=str(path.relative_to(ROOT));target=out/'snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);hashes[name]=sha(path)
    manifest=deepcopy(parent_manifest);manifest.update(status='prepared',specification=spec,source_sha256=hashes,
        cases=[],scope='Additional-budget continuation of same observed case and full explicit dialogue; not an independent replication.')
    manifest.pop('completed_at',None)
    plan=out/'private_evaluation_plan.json';write_json(plan,spec['evaluation_plan']);manifest['private_input_sha256']={plan.name:sha(plan)}
    write_json(out/'manifest.json',manifest)
    if tree_hashes(parent)!=before:raise ValueError('parent evidence changed during branch setup')
    receipt={'parent':str(parent.relative_to(ROOT)),'parent_tree_sha256':before,'parent_reported_tokens':prior_tokens,
        'additional_budget':spec['additional_token_budget'],'cumulative_local_limit':spec['round_reported_token_budget'],
        'inherited_calls':len(rows),'inherited_journal_bytes':len(calls),'inherited_journal_sha256':hashlib.sha256(calls).hexdigest(),
        'inherited_not_sent_request_indices':not_sent,
        'checkpoint_relocations':migrated,'messages_preserved':True,'public_bytes_preserved':True,'parent_unchanged':True,
        'readonly_parent_roots':[str(parent/'public'),str(parent/'artifacts')],
        'limits':'Path binding relocation is a continuation transport change, not a convergence intervention. Raw parent dialogue/cursor preserved; absolute parent business data read-only, parent runtime denied.'}
    write_json(out/'continuation_receipt.json',receipt);return receipt
