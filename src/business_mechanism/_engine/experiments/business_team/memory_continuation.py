"""Explicit Root-only migration into a new memory-treatment allocation.

Not a budget-only continuation: tool manual, task bindings and runtime policy
are versioned openly. Scientific inputs, original messages, completed actions,
questions, verdicts and cumulative costs must remain unchanged.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from workspace import sha,write_json
from explicit_continuation import tree_hashes,configure_readonly_parent,identity_hash,settled_request_prefix
from langgraph_migration.research_memory import PROFILE

MEMORY_TOOLS = ('search_memory','read_memory','save_working_note')


def manual_change(before, after):
    """Only the declared memory interface and prior approved ref-error help."""
    a,b=deepcopy(before),deepcopy(after)
    for role,names in a['roles'].items():
        if [n for n in b['roles'][role] if n not in MEMORY_TOOLS]!=names:
            raise ValueError('migration changed domain role permissions')
    b['roles']=a['roles']
    for name in MEMORY_TOOLS:b['tools'].pop(name)
    for name in ('read_history',):b['tools'][name]=a['tools'][name]
    b['tools']['resume_task']['description']=a['tools']['resume_task']['description']
    b['tools']['record_verdict']['parameters']['properties']['evidence_files']['description']=a['tools']['record_verdict']['parameters']['properties']['evidence_files']['description']
    if a!=b:
        changed=[key for key in a['tools'] if a['tools'][key]!=b['tools'].get(key)]
        raise ValueError('undeclared tool manual change: '+str(changed))


def canonical_paths(value, roots):
    if isinstance(value,str):
        for root in sorted(roots,key=len,reverse=True):value=value.replace(root,'<WORKSPACE>')
        return value
    if isinstance(value,list):return [canonical_paths(v,roots) for v in value]
    if isinstance(value,dict):return {canonical_paths(k,roots):canonical_paths(v,roots) for k,v in value.items()}
    return value


def compare_bindings(before, after, roots):
    a,b=canonical_paths(before,roots),canonical_paths(after,roots)
    manual='<WORKSPACE>/public/tool_manual.json'
    if manual not in a or manual not in b:raise ValueError('missing received tool manual binding')
    a.pop(manual);b.pop(manual)
    if a!=b:raise ValueError('migration changed scientific inputs, reviews or role prompts')


def migrate_checkpoints(ws,parent,roles,old_policy):
    from langchain_core.messages import messages_from_dict
    from langgraph_migration.runtime import role_task_context
    from langgraph_migration.context_view import compile_view
    from langgraph_migration.coordination import view as coordination
    if roles.policy['compaction']!=PROFILE:raise ValueError('declared memory profile required')
    expected={k:v for k,v in roles.policy.items() if k not in ('recent_turns','request_boundary')}
    expected['compaction']='none'
    previous={k:v for k,v in old_policy.items() if k!='request_boundary'}
    if previous!=expected:raise ValueError('migration changed slices, byte capacity or another original policy')
    roots=[str(ws.root),str(parent),*ws.path_aliases]
    plans=[]
    for path in sorted((ws.root/'explicit_runtime_state').glob('*/*.json')):
        state=json.loads(path.read_text());role=path.parent.name;identity=state['identity']
        if state.get('pending'):raise ValueError('migration requires settled paid tool batches')
        if identity_hash(identity)!=path.stem or identity['runtime']!=old_policy:raise ValueError('original checkpoint identity/policy mismatch')
        task=identity['task'];pin=role+':'+task['id']
        if ws.state['explicit_task_bindings'].get(pin)!=path.stem:raise ValueError('original task pin mismatch')
        if state['task_snapshot']['workspace_root']!=str(parent):raise ValueError('original workspace binding mismatch')
        binding=ws.task_binding(task);compare_bindings(identity['input_versions'],binding,roots)
        changed=deepcopy(state);changed['identity']={'task':task,'input_versions':binding,'runtime':roles.policy}
        snap=changed['task_snapshot'];snap.update(workspace_root=str(ws.root),input_versions=deepcopy(binding))
        if not set(snap['allowed_tools']).issubset(roles.role_tools[role]):raise ValueError('original domain tool no longer permitted')
        snap['allowed_tools']=list(dict.fromkeys([*snap['allowed_tools'],*MEMORY_TOOLS]))
        target=path.with_name(identity_hash(changed['identity'])+'.json')
        if target!=path and target.exists():raise ValueError('migration checkpoint collision')
        view=None
        token=role_task_context.set(snap)
        try:
            ws.validate_task_inputs()
            if not changed.get('role_result'):
                tools=roles._tools(role,snap)
                current={'phase_contract':ws.phase_contract(),'tool_names':[t['function']['name'] for t in tools],
                         'receipt_index':str(ws.workers[role].directory/'framework_receipts/index.json')}
                if role=='manager':current['coordination']=coordination(ws)
                _,view=compile_view(ws,role,task,changed,messages_from_dict(changed['messages']),tools,current,
                                    roles.policy['max_request_bytes'],roles.policy['recent_turns'])
        finally:role_task_context.reset(token)
        assert changed['messages']==state['messages']
        plans.append((path,target,pin,changed,view))
    if not plans:raise ValueError('no original checkpoints to migrate')
    records=[]
    for old,target,pin,state,view in plans:
        write_json(target,state)
        if old!=target:
            for suffix in ('.responses.jsonl','.views.jsonl'):
                source=old.with_suffix(suffix)
                if source.exists():source.rename(target.with_suffix(suffix))
            old.unlink()
        ws.state['explicit_task_bindings'][pin]=target.stem
        item=ws.state.get('runtime_yields',{}).get(state['identity']['task']['id'])
        if item:
            item['checkpoint']=str(target)
            if not state.get('role_result') and item.get('reason','').startswith('request byte boundary reached'):
                if view is None:raise ValueError('byte-bound task has no validated replacement view')
                item.update(status='pending',resumable=True,reason='validated research_memory_v1 view; original task and evidence retained',
                            migration_previous_reason=item['reason'])
        records.append({'task_pin':pin,'new_checkpoint':str(target),'model_steps':state['model_steps'],
                        'completed_calls':state.get('completed_calls'),'messages_sha256':hashlib.sha256(json.dumps(state['messages'],ensure_ascii=False).encode()).hexdigest(),
                        'validated_view':view})
    ws.persist();return records


def prepare_memory_branch(spec_file):
    from run_langgraph_science import ROOT,role_runtime,evaluation_window,output_directory
    from langgraph_migration.science import ScientificWorkspace
    from world import OfficeWorld
    spec=json.loads(Path(spec_file).read_text());out=output_directory(spec);evaluation_window(spec)
    if out.exists():raise ValueError('new allocation already exists; never restart')
    if spec.get('migration')!='explicit_memory_v1' or len(spec['cases'])!=1:raise ValueError('explicit single-case migration protocol required')
    case=spec['cases'][0];parent=(ROOT/case['resume_explicit_from']).resolve();prior_out=parent.parent
    before=tree_hashes(parent);parent_manifest=json.loads((prior_out/'manifest.json').read_text())
    if parent_manifest['status'] not in ('incomplete','interrupted') or (parent/'decision_freeze.json').exists():raise ValueError('parent is not an unfinished unexposed Actor')
    old_spec=parent_manifest['specification'];old_case=next(c for c in old_spec['cases'] if c['id']==case['id'])
    if any(case.get(k)!=old_case.get(k) for k in ('id','seed','private_kind','scenario_version')):raise ValueError('research case changed')
    if spec['research_question']!=old_spec['research_question'] or spec['evaluation_plan']!=old_spec['evaluation_plan']:raise ValueError('original question/evaluation changed')
    calls=(prior_out/'model_calls.jsonl').read_bytes();rows=[json.loads(s) for s in calls.splitlines()]
    if any(not r.get('response',{}).get('usage') for r in rows):raise ValueError('unsettled original usage')
    not_sent=settled_request_prefix(prior_out,rows)
    tokens=sum(r['response']['usage']['total_tokens'] for r in rows)
    if spec['round_reported_token_budget']!=tokens+spec['additional_token_budget']:raise ValueError('cumulative local budget must include original usage')
    out.mkdir(parents=True);destination=out/case['id'];shutil.copytree(parent,destination)
    aliases=json.loads((destination/'path_aliases.json').read_text());aliases={k:str(destination/Path(v).relative_to(parent)) if Path(v).is_relative_to(parent) else v for k,v in aliases.items()}
    aliases[str(parent)]=str(destination);write_json(destination/'path_aliases.json',aliases)
    for name in ('model_calls.jsonl','requests_started.jsonl','admission_events.jsonl','retry_events.jsonl'):
        source=prior_out/name
        if source.exists():shutil.copyfile(source,out/name)
    if Path(str(prior_out/'checkpoints.sqlite')+'-wal').exists():raise ValueError('parent graph has live WAL')
    with sqlite3.connect((prior_out/'checkpoints.sqlite').as_uri()+'?mode=ro&immutable=1',uri=True) as source,sqlite3.connect(out/'checkpoints.sqlite') as target:source.backup(target)
    ws=ScientificWorkspace(destination,OfficeWorld(case['private_kind'],case['seed'],case['scenario_version']),reopen=True)
    configure_readonly_parent(ws,parent)
    scientific={k:deepcopy(ws.state[k]) for k in ('hypotheses','experiments','study_plans','algorithms','results','artifact_reviews','tasks')}
    old_manual=json.loads((ws.public/'tool_manual.json').read_text())
    old_policy=ws.state['framework_runtime'].pop('explicit_policy')
    roles=role_runtime(spec,ws,None,lambda role:None)
    manual_change(old_manual,json.loads((ws.public/'tool_manual.json').read_text()))
    # Bind future requests to the received child files; ancestor inputs remain
    # read-only, but must not accidentally pin an ancestor's old tool manual.
    ws.state['base_source_paths']=[str(ws.readable(p)) for p in ws.state['base_source_paths']]
    migrations=migrate_checkpoints(ws,parent,roles,old_policy)
    assert scientific=={k:ws.state[k] for k in scientific}
    for name,digest in parent_manifest['public_input_sha256'][case['id']].items():
        if name!='public/tool_manual.json' and sha(destination/name)!=digest:raise ValueError('scientific public bytes changed: '+name)
    files=list((ROOT/'experiments/business_team').glob('*.py'))+list((ROOT/'experiments/business_team/langgraph_migration').glob('*.py'))
    files += [Path(spec_file).resolve(),ROOT/'configs/base_model.json',ROOT/'environment.langgraph.yml',ROOT/'configs/langgraph-migration-osx-arm64-pip.lock.txt',ROOT/'experiments/capability_lab/model_protocol.py',ROOT/'experiments/capability_lab/model_credentials.py',ROOT/'experiments/capability_lab/token_budget.py',ROOT/'scripts/check_registry_literals.py']
    hashes={}
    for path in files:
        name=str(path.relative_to(ROOT));target=out/'snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);hashes[name]=sha(path)
    manifest=deepcopy(parent_manifest);manifest.update(status='prepared',specification=spec,source_sha256=hashes,cases=[],
        scope='Explicit memory-treatment continuation of same case; not a budget-only experiment or independent replication.')
    manifest.pop('completed_at',None)
    manifest['public_input_sha256'][case['id']]={name:sha(destination/name) for name in parent_manifest['public_input_sha256'][case['id']]}
    plan=out/'private_evaluation_plan.json';write_json(plan,spec['evaluation_plan']);manifest['private_input_sha256']={plan.name:sha(plan)}
    write_json(out/'manifest.json',manifest)
    if tree_hashes(parent)!=before:raise ValueError('parent changed during memory migration')
    receipt={'parent':str(parent.relative_to(ROOT)),'parent_tree_sha256':before,'parent_reported_tokens':tokens,
        'additional_budget':spec['additional_token_budget'],'inherited_calls':len(rows),'inherited_journal_sha256':hashlib.sha256(calls).hexdigest(),
        'inherited_not_sent_request_indices':not_sent,
        'old_policy':old_policy,'new_policy':roles.policy,'checkpoint_migrations':migrations,'original_messages_and_science_preserved':True,
        'public_change_whitelist':['public/tool_manual.json'],'interpretation':'New treatment changes context assembly and memory tools explicitly; not a causal budget comparison.'}
    write_json(out/'continuation_receipt.json',receipt);return receipt
