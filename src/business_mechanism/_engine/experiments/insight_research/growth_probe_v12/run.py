"""Registered same-workspace continuation; no cloning, recharging or clock reset."""
import argparse
import json
from ..common import ROOT, sha, write_json
from ..growth_probe_v10.run import construct
from ..growth_probe_v11.recovery import RecoveryRuntime
from ..growth_probe_v05.orchestrator import ResearchRuntime
from .context import install_history_packer
from scripts import research_workflow as wf


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--study-id', required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--probe-only', action='store_true')
    args = p.parse_args()
    path, study = wf.verify(ROOT, args.study_id)
    if (path.parent / 'decision.json').exists():
        raise ValueError('Closed continuation cannot restart.')
    receipt = json.loads((path.parent / 'executions' / (args.run_id + '.json')).read_text())
    if receipt['status'] != 'started':
        raise ValueError('Matching fresh registered continuation launch required.')
    manifest = json.loads((ROOT / study['execution']['task_manifest']).read_text())
    run = next(r for r in study['execution']['runs'] if r['id'] == args.run_id)
    task = next(t for t in manifest['tasks'] if t['id'] == run['task_ids'][0])
    amendment_file = run.get('amendment_file') or task['amendment_file']
    amendment = json.loads((ROOT / amendment_file).read_text())
    parent = ROOT / amendment['parent_output']
    original = parent / 'researcher/private/checkpoint.json'
    if sha(original) != amendment['checkpoint_sha256']:
        raise ValueError('Original paid parent checkpoint changed; inspect registered continuation.')
    output = path.parent / 'results' / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    if args.probe_only:
        # This preflight deliberately opens no mutable parent workspace/database.
        result = {'status': 'engineering_probe_only', 'new_paid_calls': 0,
            'checkpoint_matches': True, 'original_role_attempts': amendment['initial_role_attempts'],
            'transport_failures_retained': amendment['initial_transport_failures'],
            'additional_attempts': amendment['additional_attempts'],
            'same_paid_workspace': str(parent), 'original_deadline_unix': amendment['original_deadline_unix'],
            'scope': 'Full registered continuation command and static parent binding; actual runtime/DB behavior covered by separate controls.'}
        write_json(output / 'runtime_status.json', result)
        print(json.dumps(result))
        return 0
    actual, ws, runner = construct(amendment['parent_study'], amendment['parent_run'], resume=True)
    try:
        if actual != parent:
            raise ValueError('Registered continuation must use the original paid workspace.')
        install_history_packer(ws)
        runner.runtime = (RecoveryRuntime(ws, runner.model, journal=runner.journal, amendment=amendment)
            if amendment['additional_attempts'] else ResearchRuntime(ws, runner.model, journal=runner.journal))
        result = runner.run(80)
        write_json(output / 'runtime_status.json', result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'completed' else 3
    finally:
        write_json(output / 'common_budget_snapshot.json', runner.budget.snapshot())
        write_json(output / 'execution_guard_snapshot.json', runner.guard.inspect())
        write_json(output / 'continuation_receipt.json', {'parent_output': amendment['parent_output'],
            'same_workspace': True, 'same_all_role_budget': True, 'prior_costs_not_reset': True,
            'scientific_records_or_messages_not_rewritten_by_root': True, 'amendment_file': amendment_file, 'common_history_adapter_sha256': sha(ROOT / 'experiments/insight_research/growth_probe_v12/context.py')})
        ws.close()


if __name__ == '__main__':
    raise SystemExit(main())
