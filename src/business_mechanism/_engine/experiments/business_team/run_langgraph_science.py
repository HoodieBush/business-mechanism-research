"""Frozen five-role business development matrix. Final evaluation stays outside Actors."""
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
from world import OfficeWorld
from workspace import sha,write_json
from langgraph_migration.science import ScientificWorkspace,scientific_flow
from langgraph_migration.runtime import FrameworkRoles
from langgraph_migration.provider import APIJournal,GatewayChatModel
from langgraph_migration.sources import enable_research
from langgraph_migration.coordination import prior_costs
from development_evaluation import program as program_file

ROOT=Path(__file__).resolve().parents[2]


def role_runtime(spec,ws,saver,factory):
    profile=spec.get('role_runtime','framework')
    if profile=='framework':return FrameworkRoles(ws,saver,factory)
    if profile=='explicit_v1':
        if spec.get('harness_context_profile','legacy')!='legacy' or spec.get('handoff_presentation','legacy')!='legacy':
            raise ValueError('explicit_v1 has its own ordinary task presentation and no middleware; do not combine legacy context/handoff treatments')
        from langgraph_migration.explicit_runtime import ExplicitRoles
        return ExplicitRoles(ws,saver,factory,**spec.get('explicit_runtime',{}))
    raise ValueError('unknown role_runtime: '+str(profile))


def evaluation_window(spec):
    # Narrative review rubrics are annotations. Only these typed fields control
    # the evaluator; never infer executable parameters from prose.
    window=spec.get('evaluation_plan',{}).get('evaluation_window',{'first_day':140,'calendar_days':28})
    if set(window)!={'first_day','calendar_days'} or any(type(v) is not int for v in window.values()):
        raise ValueError('evaluation_window needs integer first_day/calendar_days')
    if window['first_day']<126 or window['calendar_days']<1:
        raise ValueError('final window must follow all development/trial windows and have positive days')
    return window


def evaluate_closed_case(ws,path,spec,record):
    """Recover evaluator work after closure without constructing any live role."""
    frozen=json.loads((path/'decision_freeze.json').read_text())
    if frozen.get('actor_closed') is not True:raise ValueError('explicit Actor closure required')
    selected=program_file(ws,frozen['selected_algorithm_id'])
    programs={'selected':selected,**{n:ws.public/(n+'.py') for n in ('baseline','numeric_refit','strong_numeric')}}
    hashes={name:sha(code) for name,code in programs.items()}
    if frozen.get('program_sha256')!=hashes:raise ValueError('closed program identity changed or missing; do not silently refreeze')
    window=evaluation_window(spec)
    if frozen.get('evaluation_window')!=window:raise ValueError('closed evaluation window changed')
    progress_file=path/'final_evaluation_progress.json'
    identity={'program_sha256':hashes,'evaluation_window':window,'freeze_sha256':sha(path/'decision_freeze.json')}
    progress=json.loads(progress_file.read_text()) if progress_file.exists() else {'identity':identity,'scores':{}}
    if progress['identity']!=identity:raise ValueError('evaluation recovery identity changed')
    record.update(actor_closed=True,final_evaluation=progress['scores'])
    for label,filename in programs.items():
        if label in progress['scores']:continue
        score=ws.evaluate_code(filename,first_day=window['first_day'],days=window['calendar_days'],name='final_'+label)
        score.pop('execution_receipt',None)
        progress['scores'][label]=score;write_json(progress_file,progress)
    record.update(status='completed',final_evaluation=progress['scores'])
    for key in ('error','error_type'):record.pop(key,None)


def freeze_decision(ws,path,decision,spec):
    """Freeze the actual closed graph delivery before any final observation."""
    target=path/'decision_freeze.json'
    if target.exists():raise ValueError('decision already frozen; use evaluation-only recovery')
    if ws.state['workflow']['phase']!='complete':raise ValueError('close the Actor graph before freezing its decision')
    if decision.get('kind')!='finished' or not any(r==decision and r.get('role')=='manager' for r in ws.state['results']):
        raise ValueError('freeze an actual manager delivery receipt, not a constructed decision')
    selected=decision['selected_algorithm_id']
    programs={'selected':program_file(ws,selected),**{n:ws.public/(n+'.py') for n in ('baseline','numeric_refit','strong_numeric')}}
    frozen={'selected_algorithm_id':selected,'actor_closed':True,'event_count':len(ws.state['events']),
        'hypotheses':ws.state['hypotheses'],'algorithm_ids':[a['id'] for a in ws.state['algorithms']],
        'decision':decision,'program_sha256':{n:sha(p) for n,p in programs.items()},'evaluation_window':evaluation_window(spec)}
    write_json(target,frozen);return frozen


def output_directory(spec):
    output=(ROOT/spec['output_directory']).resolve() if spec.get('output_directory') else ROOT/'experiments/business_team/results'/spec['phase']
    if not output.is_relative_to((ROOT/'experiments').resolve()):raise ValueError('research outputs must stay under experiments')
    return output


def setup(spec_file):
    spec=json.loads(Path(spec_file).read_text());out=output_directory(spec)
    evaluation_window(spec)
    if spec.get('role_runtime','framework') not in ('framework','explicit_v1'):raise ValueError('unknown role_runtime')
    from langgraph_migration.context_policy import retention_trigger
    context_config=json.loads((ROOT/'configs/base_model.json').read_text())
    context_config['context_capacity']=spec.get('context_capacity')
    retention_trigger(spec.get('context_retention_profile','legacy'),config=context_config)
    from langgraph_migration.durable_context import PROFILE as DURABLE_PROFILE
    if spec.get('harness_context_profile','legacy') not in ('legacy',DURABLE_PROFILE):
        raise ValueError('Unknown harness context profile')
    if out.exists():raise ValueError('existing phase may only resume; never overwrite')
    out.mkdir(parents=True)
    from environment_readiness import sandbox_probe
    readiness=sandbox_probe(out/'startup_sandbox_probe')
    write_json(out/'environment_readiness.json',readiness)
    if not readiness['ready']:raise RuntimeError('sandbox unavailable in this execution session; inspect environment_readiness.json; zero model calls, no unsandboxed fallback')
    if spec.get('role_runtime','framework')=='explicit_v1':
        from process_acceptance import run as run_acceptance
        for mode in ('controls','sandbox'):
            if spec.get('explicit_runtime',{}).get('memory_profile','none')!='none':
                result=run_acceptance(out/('preflight_'+mode),mode,memory=True)
            else:result=run_acceptance(out/('preflight_'+mode),mode)
            if result['status']!='passed':raise RuntimeError('strict '+mode+' acceptance incomplete; zero model API calls: '+result['status'])
    else:
        test=subprocess.run([sys.executable,'-m','unittest','-v','test_minimal_research.py','test_python_reference.py','test_token_budget.py','test_registry_integrity.py','test_assistance_handoff.py','test_operational_memory.py','test_summary_reuse.py','test_context_contracts.py','test_task_instruction.py','test_context_protocol.py','test_context_retention.py','test_durable_context.py','test_evaluation_logs.py','test_decision_interface.py','test_science_input_freeze.py','test_sources.py','test_model_pacing.py','test_tool_outputs.py','test_program_selection.py','test_scenario_revision.py','test_coordination.py','test_task_dependencies.py','test_task_snapshot.py','test_experiment_plans.py','test_langgraph_science.py','test_langgraph_collaboration.py','test_langgraph_migration.py','test_information_protocol.py','test_business_team.py','test_handoff_presentation.py'],cwd=Path(__file__).parent,capture_output=True,text=True)
        (out/'preflight-tests.log').write_text(test.stdout+test.stderr)
        if test.returncode:raise RuntimeError('preflight failed; zero model API calls')
    files=list(Path(__file__).parent.glob('*.py'))+list((Path(__file__).parent/'langgraph_migration').glob('*.py'))
    files += [Path(spec_file).resolve(),ROOT/'configs/base_model.json',ROOT/'environment.langgraph.yml',ROOT/'configs/langgraph-migration-osx-arm64-pip.lock.txt',ROOT/'experiments/capability_lab/model_protocol.py',ROOT/'experiments/capability_lab/model_credentials.py',ROOT/'experiments/capability_lab/token_budget.py',ROOT/'scripts/check_registry_literals.py']
    hashes={}
    for path in files:
        relative=path.relative_to(ROOT);target=out/'snapshot'/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target);hashes[str(relative)]=sha(path)
    manifest={'status':'prepared','created_at':datetime.now(timezone.utc).isoformat(),'specification':spec,'source_sha256':hashes,
      'packages':{n:version(n) for n in ('langgraph','langchain','langchain-core','langchain-openai','langgraph-checkpoint-sqlite','pydantic','numpy','pandas','scipy')},
      'scope':'full five-role development pilot on concrete business simulation; no method-effect or structural holdout claim','cases':[],'runtime_profile':spec.get('role_runtime','framework')}
    manifest['model_call_pacing']={'manual_tokens_per_minute':spec.get('model_tokens_per_minute'),
        'scope':'None removes artificial token pacing; shared serialization, usage accounting and provider reconnect/backoff remain.'}
    for case in spec['cases']:
        parent=ROOT/case['resume_from'] if case.get('resume_from') else None
        ws=ScientificWorkspace(out/case['id'],OfficeWorld(case['private_kind'],case['seed'],case.get('scenario_version','office-business-v0.2')),resume_from=parent)
        ws.harness_context_profile=spec.get('harness_context_profile','legacy')
        if spec.get('research_access')=='autonomous':enable_research(ws)
        # Materialise the same native registry manual before freezing public
        # input hashes. This constructs no agents and makes no model calls.
        role_runtime(spec,ws,None,lambda role:None)
        if parent:
            if any(sha(parent/'public'/name)!=sha(ws.public/name) for name in ('business.sqlite','history.csv','data_dictionary.json')):raise ValueError('continuation public observations or contract changed')
            manifest.setdefault('continuations',{})[case['id']]={'parent':str(parent.relative_to(ROOT)),'old_role_contexts':'archived in parent; new role threads start from unchanged data, prior artifacts and actual negative reviews','inherited_workflow':ws.workflow()}
            ws.state['previous_phase_costs']=prior_costs(parent.parent);ws.persist()
            if case.get('replan_from_existing_archive'):
                # Explicit coordinator migration from an old batch assignment.
                # Prior hypotheses/verdicts/unfinished work remain unmodified;
                # the manager now chooses the next subset from that archive.
                ws.state['workflow']['phase']='needs_research_decision';ws.persist()
                manifest['continuations'][case['id']]['coordinator_replan']='Existing batch assignment released for manager choice; no new verdict, sampling or algorithm result manufactured.'
            if case.get('resume_received_task_id'):
                if case.get('replan_from_existing_archive'):raise ValueError('choose received-task continuation or coordinator replan, not both')
                task=next((t for t in ws.state['tasks'] if t['id']==case['resume_received_task_id']),None)
                if not task or task.get('kind')!='scheduled_task':raise ValueError('received task ID not present in actual parent archive')
                manifest['continuations'][case['id']]['received_task_continuation']={'task_id':task['id'],'role':task['role'],'scope':'Original actual manager assignment, unchanged; no new manager choice or invented professional result.'}
        manifest.setdefault('public_input_sha256',{})[case['id']]={str(p.relative_to(ws.root)):sha(p) for p in ws.public.rglob('*') if p.is_file()}
    if spec.get('evaluation_plan'):
        plan=out/'private_evaluation_plan.json';write_json(plan,spec['evaluation_plan'])
        manifest['private_input_sha256']={plan.name:sha(plan)}
    write_json(out/'manifest.json',manifest);return out


def run(spec_file,resume=False,evaluate_only=False):
    spec=json.loads(Path(spec_file).read_text());out=output_directory(spec)
    if not resume:out=setup(spec_file)
    manifest=json.loads((out/'manifest.json').read_text())
    if any(sha(ROOT/n)!=h for n,h in manifest['source_sha256'].items()):raise ValueError('frozen code changed; open a new phase')
    for case,inputs in manifest.get('public_input_sha256',{}).items():
        if any(sha(out/case/name)!=value for name,value in inputs.items()):raise ValueError('frozen public input changed; open a new phase')
    if any(sha(out/name)!=value for name,value in manifest.get('private_input_sha256',{}).items()):raise ValueError('frozen private evaluation plan changed')
    for name,expected in manifest.get('packages',{}).items():
        if version(name)!=expected:raise ValueError('installed dependency changed: '+name+'; open a new phase')
    evaluation_window(spec)
    if evaluate_only and any(not (out/c['id']/'decision_freeze.json').exists() for c in spec['cases']):
        raise ValueError('evaluation-only requires every Actor to be closed')
    manifest['status']='running';write_json(out/'manifest.json',manifest)
    config=json.loads((ROOT/'configs/base_model.json').read_text());config.setdefault('request_timeout_seconds',180)
    config['context_summary_layout']=spec.get('context_summary_layout','serialized')
    config['context_retention_profile']=spec.get('context_retention_profile','legacy')
    config['context_capacity']=spec.get('context_capacity')
    journal=APIJournal(out,config,budget=spec['round_reported_token_budget'],tokens_per_minute=spec.get('model_tokens_per_minute'))
    con=sqlite3.connect(out/'checkpoints.sqlite',check_same_thread=False);saver=SqliteSaver(con)
    records={c['id']:c for c in manifest['cases']}
    try:
        for case in spec['cases']:
            path=out/case['id']
            ws=ScientificWorkspace(path,OfficeWorld(case['private_kind'],case['seed'],case.get('scenario_version','office-business-v0.2')),reopen=True,evaluation_only=(path/'decision_freeze.json').exists())
            ws.harness_context_profile=spec.get('harness_context_profile','legacy')
            ws.handoff_presentation=case.get('handoff_presentation',spec.get('handoff_presentation','legacy'))
            if case.get('resume_explicit_from'):
                from explicit_continuation import configure_readonly_parent
                configure_readonly_parent(ws,ROOT/case['resume_explicit_from'])
            if spec.get('research_access')=='autonomous':enable_research(ws)
            ws.resource_reader=journal.public_view
            old_serial=journal.serial;record=records.get(case['id'],{'id':case['id']})
            print('START',case['id'],ws.workflow()['phase'],flush=True)
            try:
                if not (path/'decision_freeze.json').exists():
                    roles=role_runtime(spec,ws,saver,lambda role:GatewayChatModel(journal=journal,research_role=role))
                    graph=scientific_flow(roles,saver,resume_task_id=case.get('resume_received_task_id'),research_question=spec.get('research_question'));conf={'configurable':{'thread_id':case['id']+':science'},'recursion_limit':2**31-1}
                    before=graph.get_state(conf)
                    values=before.values if before.values and not before.next else graph.invoke(None if before.values else {},conf)
                    record.update(status=values.get('status','incomplete'),state=values,workflow=ws.workflow())
                if not (path/'decision_freeze.json').exists() and record.get('status')=='completed':
                    freeze_decision(ws,path,values['step'],spec)
                if (path/'decision_freeze.json').exists():evaluate_closed_case(ws,path,spec,record)
            except KeyboardInterrupt:
                record.update(status='interrupted',workflow=ws.workflow());manifest['status']='interrupted';raise
            except Exception as error:
                from langgraph_migration.provider import TokenBudgetStop
                stopped=isinstance(error,TokenBudgetStop) or 'reported-cost admission' in str(error)
                record.update(status='cost_admission_stopped' if stopped else 'final_evaluation_failed' if (path/'decision_freeze.json').exists() else 'failed',error_type=type(error).__name__,error=str(error)[:2500],workflow=ws.workflow())
            finally:
                record.update(api_attempts_this_process=journal.serial-old_serial,
                  science_counts={'hypotheses':len(ws.state['hypotheses']),'parented_revisions':sum(bool(h.get('parent_id')) for h in ws.state['hypotheses']),
                    'new_trials':sum(e['kind']=='supply_trial' for e in ws.state['experiments']),'inventory_audits':sum(e['kind']=='inventory_audit' for e in ws.state['experiments']),'algorithms':len(ws.state['algorithms'])},
                  actual_task_roles=[t['role'] for t in ws.state['tasks']],results=len(ws.state['results']))
                records[case['id']]=record;manifest.update(cases=list(records.values()),usage=journal.usage())
                write_json(path/'case_result.json',record);write_json(out/'manifest.json',manifest)
            print('CASE',case['id'],record['status'],record['science_counts'],flush=True)
            if record['status']!='completed':break
    finally:con.close()
    manifest.update(status='completed' if len(records)==len(spec['cases']) and all(r['status']=='completed' for r in records.values()) else 'incomplete',completed_at=datetime.now(timezone.utc).isoformat(),
      usage=journal.usage(),frozen_source_hashes_unchanged=all(sha(ROOT/n)==h for n,h in manifest['source_sha256'].items()))
    write_json(out/'manifest.json',manifest);print(json.dumps({'status':manifest['status'],'usage':manifest['usage'],'cases':[(c['id'],c['status']) for c in manifest['cases']]},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spec',required=True);p.add_argument('--resume',action='store_true');p.add_argument('--prepare-only',action='store_true');p.add_argument('--evaluate-only',action='store_true');args=p.parse_args()
    if args.prepare_only:print(setup(args.spec))
    else:run(args.spec,args.resume or args.evaluate_only,args.evaluate_only)
